"""
╔══════════════════════════════════════════════════════════════════════════════╗
║ omen_router_modules/agent_engine.py — Motor de Agente Autónomo              ║
║ OMEN AI Router V14 (build V21)                                              ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ Ciclo: PLAN → EXECUTE → VALIDATE con subtareas y reintentos.               ║
║                                                                              ║
║ [V21-A1] Módulo separado del monolito.                                      ║
║ [V21-A2] Truncamiento inteligente de contexto (H-04).                       ║
║ [V21-A3] Sanitización de respuestas del LLM (H-35).                        ║
║ [V21-A4] Validación robusta de JSON del agente.                             ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import asyncio
import json
import logging
import sqlite3
import time
import uuid
from contextlib import closing
from datetime import datetime, timezone
from typing import Optional

import httpx

from .config import (
    AGENT_CONTEXT_MAX_TOKENS,
    DB_PATH,
    MAX_ACTIVE_TASKS,
    RUTAS,
    SGLANG_CHAT,
)

log = logging.getLogger("omen-router.agent")

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTES
# ─────────────────────────────────────────────────────────────────────────────
_MAX_RESPONSE_SIZE = 50_000  # [V21-A3] Máximo chars de respuesta del LLM
_MAX_SUBTASKS = 10
_MAX_RETRIES_PER_SUBTASK = 2

# ─────────────────────────────────────────────────────────────────────────────
# ESTADO
# ─────────────────────────────────────────────────────────────────────────────
_active_agent_tasks: set[str] = set()
_shutdown_event = asyncio.Event()

# Métricas
_agent_metrics = {
    "tasks_total": 0,
    "tasks_ok": 0,
    "tasks_failed": 0,
    "tasks_cancelled": 0,
    "total_duration_s": 0.0,
}
_metrics_lock = asyncio.Lock()


# ─────────────────────────────────────────────────────────────────────────────
# TASK STATUS
# ─────────────────────────────────────────────────────────────────────────────
class TaskStatus:
    PENDING = "PENDING"
    PLANNING = "PLANNING"
    EXECUTING = "EXECUTING"
    VALIDATING = "VALIDATING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


TERMINAL_STATES = frozenset({TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED})


# ─────────────────────────────────────────────────────────────────────────────
# DATABASE
# ─────────────────────────────────────────────────────────────────────────────
def _db_conn() -> sqlite3.Connection:
    """Crea una conexión SQLite con row_factory."""
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db() -> None:
    """Inicializa las tablas del agente si no existen."""
    with closing(_db_conn()) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                prompt TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'PENDING',
                total_subtasks INTEGER DEFAULT 0,
                completed_subtasks INTEGER DEFAULT 0,
                current_iteration INTEGER DEFAULT 0,
                max_iterations INTEGER DEFAULT 3,
                final_result TEXT,
                error_message TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT
            );
            CREATE TABLE IF NOT EXISTS subtasks (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                seq_order INTEGER NOT NULL,
                description TEXT NOT NULL,
                required_level TEXT DEFAULT 'AGIL',
                status TEXT NOT NULL DEFAULT 'PENDING',
                result TEXT,
                error_feedback TEXT,
                retry_count INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (task_id) REFERENCES tasks(id)
            );
            CREATE TABLE IF NOT EXISTS task_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                phase TEXT NOT NULL,
                message TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                FOREIGN KEY (task_id) REFERENCES tasks(id)
            );
            CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
            CREATE INDEX IF NOT EXISTS idx_subtasks_task ON subtasks(task_id);
            CREATE INDEX IF NOT EXISTS idx_logs_task ON task_logs(task_id);
        """)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _task_log(task_id: str, phase: str, message: str) -> None:
    """Registra un evento en el log de la tarea."""
    try:
        with closing(_db_conn()) as conn:
            conn.execute(
                "INSERT INTO task_logs (task_id, phase, message, timestamp) VALUES (?, ?, ?, ?)",
                (task_id, phase, message, _now_iso()),
            )
            conn.commit()
    except Exception as e:
        log.warning(f"[AGENT] Error logging tarea {task_id[:8]}: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# [V21-A2] TRUNCAMIENTO INTELIGENTE DE CONTEXTO
# ─────────────────────────────────────────────────────────────────────────────
def _truncate_context(messages: list[dict], max_chars: int = None) -> list[dict]:
    """
    [V21-A2] Trunca el contexto del agente manteniendo:
    - El system prompt (siempre)
    - Los últimos N mensajes (priorizados)
    - Un resumen compacto de mensajes intermedios descartados

    max_chars aproxima el límite de tokens (4 chars ≈ 1 token).
    """
    if max_chars is None:
        max_chars = AGENT_CONTEXT_MAX_TOKENS * 4  # ~4 chars per token

    # Calcular tamaño total
    total_chars = sum(len(m.get("content", "")) for m in messages)
    if total_chars <= max_chars:
        return messages

    if len(messages) <= 3:
        # Truncar contenido de mensajes individuales
        result = []
        for m in messages:
            content = m.get("content", "")
            if len(content) > max_chars // len(messages):
                content = content[: max_chars // len(messages)] + "\n[… truncado por límite de contexto]"
            result.append({**m, "content": content})
        return result

    # Mantener system (primero) + últimos 4 mensajes
    system_msgs = [m for m in messages if m.get("role") == "system"]
    non_system = [m for m in messages if m.get("role") != "system"]

    keep_last = min(4, len(non_system))
    kept_tail = non_system[-keep_last:]
    discarded = non_system[:-keep_last]

    # Generar resumen compacto de lo descartado
    if discarded:
        summary_parts = []
        for m in discarded[-3:]:  # Solo resumir los últimos 3 descartados
            role = m.get("role", "?")
            content = m.get("content", "")[:100]
            summary_parts.append(f"[{role}]: {content}…")

        summary_msg = {
            "role": "system",
            "content": (
                f"[Contexto truncado: {len(discarded)} mensajes anteriores omitidos. "
                f"Últimos descartados:\n" + "\n".join(summary_parts) + "]"
            ),
        }
        return system_msgs + [summary_msg] + kept_tail

    return system_msgs + kept_tail


# ─────────────────────────────────────────────────────────────────────────────
# [V21-A3] SANITIZACIÓN DE RESPUESTA
# ─────────────────────────────────────────────────────────────────────────────
def _sanitize_llm_response(text: str) -> str:
    """[V21-A3] Limita el tamaño de la respuesta del LLM para prevenir DoS."""
    if len(text) > _MAX_RESPONSE_SIZE:
        log.warning(f"[AGENT] Respuesta LLM truncada: {len(text)} → {_MAX_RESPONSE_SIZE} chars")
        return text[:_MAX_RESPONSE_SIZE]
    return text


def _parse_agent_json(text: str) -> Optional[dict]:
    """
    [V21-A4] Parsea JSON de la respuesta del agente con validación robusta.
    Busca el primer bloque JSON válido en la respuesta.
    """
    text = _sanitize_llm_response(text)

    # Intentar parsear directamente
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    # Buscar bloques ```json ... ```
    import re
    json_blocks = re.findall(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    for block in json_blocks:
        try:
            data = json.loads(block)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            continue

    # Buscar primer { ... } balanceado
    start = text.find("{")
    if start >= 0:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        data = json.loads(text[start:i + 1])
                        if isinstance(data, dict):
                            return data
                    except json.JSONDecodeError:
                        break
                    break

    return None


# ─────────────────────────────────────────────────────────────────────────────
# LLM CALL
# ─────────────────────────────────────────────────────────────────────────────
async def _agent_call_llm(
    messages: list[dict],
    http_client: httpx.AsyncClient,
    nivel: str = "AGIL",
    timeout: float = 120.0,
) -> Optional[str]:
    """Llama al LLM para el agente con el nivel especificado."""
    # [V21-A2] Truncar contexto antes de enviar
    messages = _truncate_context(messages)

    url = RUTAS.get(nivel, RUTAS["AGIL"])["url"]
    model = RUTAS.get(nivel, RUTAS["AGIL"])["modelo"]

    try:
        r = await http_client.post(
            url,
            json={
                "model": model,
                "messages": messages,
                "stream": False,
                "options": {"temperature": 0.3, "num_predict": 4096},
            },
            timeout=timeout,
        )
        if r.status_code == 200:
            data = r.json()
            # Compatibilidad Ollama / OpenAI API
            if "message" in data:
                return _sanitize_llm_response(data["message"].get("content", ""))
            elif "choices" in data:
                choices = data["choices"]
                if choices:
                    return _sanitize_llm_response(
                        choices[0].get("message", {}).get("content", "")
                    )
        else:
            log.warning(f"[AGENT-LLM] Error {r.status_code} en nivel {nivel}")
    except httpx.TimeoutException:
        log.warning(f"[AGENT-LLM] Timeout ({timeout}s) en nivel {nivel}")
    except Exception as e:
        log.error(f"[AGENT-LLM] Error: {e}")

    return None


# ─────────────────────────────────────────────────────────────────────────────
# PLANNING PHASE
# ─────────────────────────────────────────────────────────────────────────────
_PLAN_SYSTEM = """Eres un agente planificador. Dada una tarea, genera un plan de ejecución.
Responde SOLO con JSON válido con esta estructura:
{
  "subtasks": [
    {"description": "...", "required_level": "AGIL|PROFUNDO|CODIGO|MASIVO|PRECISO"}
  ]
}
Máximo 10 subtareas. Cada subtarea debe ser atómica y verificable.
Niveles: AGIL (general), PROFUNDO (razonamiento), CODIGO (programación), MASIVO (análisis extenso), PRECISO (verificación).
"""


async def _plan_task(
    task_id: str, prompt: str, http_client: httpx.AsyncClient
) -> Optional[list[dict]]:
    """Genera el plan de subtareas para una tarea."""
    messages = [
        {"role": "system", "content": _PLAN_SYSTEM},
        {"role": "user", "content": f"Planifica la siguiente tarea:\n\n{prompt}"},
    ]

    response = await _agent_call_llm(messages, http_client, nivel="AGIL")
    if not response:
        return None

    parsed = _parse_agent_json(response)
    if not parsed or "subtasks" not in parsed:
        log.warning(f"[AGENT] Plan inválido para tarea {task_id[:8]}")
        return None

    subtasks = parsed["subtasks"]
    if not isinstance(subtasks, list) or not subtasks:
        return None

    # Limitar y validar
    subtasks = subtasks[:_MAX_SUBTASKS]
    valid_levels = set(RUTAS.keys())
    for st in subtasks:
        if not isinstance(st, dict) or "description" not in st:
            return None
        level = st.get("required_level", "AGIL")
        if level not in valid_levels:
            st["required_level"] = "AGIL"

    return subtasks


# ─────────────────────────────────────────────────────────────────────────────
# EXECUTION PHASE
# ─────────────────────────────────────────────────────────────────────────────
async def _execute_subtask(
    task_id: str,
    subtask: dict,
    context: list[dict],
    http_client: httpx.AsyncClient,
) -> Optional[str]:
    """Ejecuta una subtarea individual."""
    nivel = subtask.get("required_level", "AGIL")
    description = subtask.get("description", "")

    messages = context + [
        {"role": "user", "content": f"Ejecuta la siguiente subtarea:\n\n{description}"},
    ]

    return await _agent_call_llm(messages, http_client, nivel=nivel, timeout=150.0)


# ─────────────────────────────────────────────────────────────────────────────
# VALIDATION PHASE
# ─────────────────────────────────────────────────────────────────────────────
_VALIDATE_SYSTEM = """Eres un validador de resultados. Evalúa si el resultado de una subtarea es correcto y completo.
Responde SOLO con JSON:
{"valid": true/false, "feedback": "explicación breve si es inválido"}
"""


async def _validate_subtask(
    description: str,
    result: str,
    http_client: httpx.AsyncClient,
) -> tuple[bool, str]:
    """Valida el resultado de una subtarea."""
    messages = [
        {"role": "system", "content": _VALIDATE_SYSTEM},
        {
            "role": "user",
            "content": f"Subtarea: {description}\n\nResultado:\n{result[:2000]}",
        },
    ]

    response = await _agent_call_llm(messages, http_client, nivel="AGIL", timeout=60.0)
    if not response:
        return True, ""  # Si no puede validar, asumir válido

    parsed = _parse_agent_json(response)
    if parsed:
        valid = parsed.get("valid", True)
        feedback = parsed.get("feedback", "")
        return bool(valid), str(feedback)[:500]

    return True, ""


# ─────────────────────────────────────────────────────────────────────────────
# SYNTHESIS PHASE
# ─────────────────────────────────────────────────────────────────────────────
async def _synthesize_results(
    prompt: str,
    subtask_results: list[dict],
    http_client: httpx.AsyncClient,
) -> Optional[str]:
    """Sintetiza los resultados de todas las subtareas en una respuesta final."""
    results_text = "\n\n---\n\n".join(
        f"**Subtarea {i+1}:** {r['description']}\n**Resultado:** {r['result'][:1000]}"
        for i, r in enumerate(subtask_results)
        if r.get("result")
    )

    messages = [
        {
            "role": "system",
            "content": "Sintetiza los resultados de las subtareas en una respuesta final coherente y completa para el usuario.",
        },
        {
            "role": "user",
            "content": f"Tarea original: {prompt}\n\nResultados de subtareas:\n{results_text}",
        },
    ]

    return await _agent_call_llm(messages, http_client, nivel="AGIL", timeout=120.0)


# ─────────────────────────────────────────────────────────────────────────────
# MAIN TASK RUNNER
# ─────────────────────────────────────────────────────────────────────────────
async def run_task(task_id: str) -> None:
    """
    Ejecuta el ciclo completo de una tarea del agente:
    PLAN → EXECUTE (con reintentos) → VALIDATE → SYNTHESIZE
    """
    _active_agent_tasks.add(task_id)
    t0 = time.monotonic()

    try:
        # Obtener tarea de la DB
        with closing(_db_conn()) as conn:
            task = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not task:
                return

        prompt = task["prompt"]
        max_iterations = task["max_iterations"]

        # Actualizar estado a PLANNING
        with closing(_db_conn()) as conn:
            conn.execute(
                "UPDATE tasks SET status=?, updated_at=? WHERE id=?",
                (TaskStatus.PLANNING, _now_iso(), task_id),
            )
            conn.commit()
        _task_log(task_id, "PLANNING", "Generando plan de ejecución…")

        async with httpx.AsyncClient(timeout=180.0) as http_client:
            # ── PLANNING ──
            subtasks_plan = await _plan_task(task_id, prompt, http_client)
            if not subtasks_plan:
                _fail_task(task_id, "No se pudo generar un plan válido")
                return

            # Guardar subtareas en DB
            with closing(_db_conn()) as conn:
                for i, st in enumerate(subtasks_plan):
                    st_id = str(uuid.uuid4())
                    conn.execute(
                        "INSERT INTO subtasks (id, task_id, seq_order, description, required_level, status, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (st_id, task_id, i + 1, st["description"], st["required_level"], "PENDING", _now_iso()),
                    )
                conn.execute(
                    "UPDATE tasks SET status=?, total_subtasks=?, updated_at=? WHERE id=?",
                    (TaskStatus.EXECUTING, len(subtasks_plan), _now_iso(), task_id),
                )
                conn.commit()

            _task_log(task_id, "PLANNING", f"Plan generado: {len(subtasks_plan)} subtareas")

            # ── EXECUTION ──
            context = [
                {"role": "system", "content": f"Estás ejecutando la tarea: {prompt[:500]}"},
            ]
            subtask_results = []

            for iteration in range(max_iterations):
                # Verificar cancelación
                if _shutdown_event.is_set():
                    _cancel_task(task_id, "Shutdown del sistema")
                    return

                with closing(_db_conn()) as conn:
                    task_check = conn.execute(
                        "SELECT status FROM tasks WHERE id=?", (task_id,)
                    ).fetchone()
                    if task_check and task_check["status"] == TaskStatus.CANCELLED:
                        return

                with closing(_db_conn()) as conn:
                    conn.execute(
                        "UPDATE tasks SET current_iteration=?, updated_at=? WHERE id=?",
                        (iteration + 1, _now_iso(), task_id),
                    )
                    conn.commit()

                # Obtener subtareas pendientes
                with closing(_db_conn()) as conn:
                    pending = conn.execute(
                        "SELECT * FROM subtasks WHERE task_id=? AND status != 'COMPLETED' ORDER BY seq_order",
                        (task_id,),
                    ).fetchall()

                if not pending:
                    break  # Todas completadas

                for st_row in pending:
                    if _shutdown_event.is_set():
                        _cancel_task(task_id, "Shutdown del sistema")
                        return

                    st_desc = st_row["description"]
                    st_id = st_row["id"]

                    _task_log(task_id, "EXECUTING", f"Subtarea {st_row['seq_order']}: {st_desc[:80]}")

                    result = await _execute_subtask(
                        task_id,
                        {"description": st_desc, "required_level": st_row["required_level"]},
                        context,
                        http_client,
                    )

                    if not result:
                        # Retry
                        retry_count = st_row["retry_count"] + 1
                        if retry_count <= _MAX_RETRIES_PER_SUBTASK:
                            with closing(_db_conn()) as conn:
                                conn.execute(
                                    "UPDATE subtasks SET retry_count=?, error_feedback=? WHERE id=?",
                                    (retry_count, "Sin respuesta del LLM", st_id),
                                )
                                conn.commit()
                            _task_log(task_id, "EXECUTING", f"Reintento {retry_count} para subtarea {st_row['seq_order']}")
                            continue
                        else:
                            with closing(_db_conn()) as conn:
                                conn.execute(
                                    "UPDATE subtasks SET status='FAILED', error_feedback=? WHERE id=?",
                                    ("Reintentos agotados", st_id),
                                )
                                conn.commit()
                            continue

                    # ── VALIDATION ──
                    with closing(_db_conn()) as conn:
                        conn.execute(
                            "UPDATE tasks SET status=?, updated_at=? WHERE id=?",
                            (TaskStatus.VALIDATING, _now_iso(), task_id),
                        )
                        conn.commit()

                    valid, feedback = await _validate_subtask(st_desc, result, http_client)

                    if valid:
                        with closing(_db_conn()) as conn:
                            conn.execute(
                                "UPDATE subtasks SET status='COMPLETED', result=? WHERE id=?",
                                (result[:5000], st_id),
                            )
                            conn.execute(
                                "UPDATE tasks SET completed_subtasks=completed_subtasks+1, "
                                "status=?, updated_at=? WHERE id=?",
                                (TaskStatus.EXECUTING, _now_iso(), task_id),
                            )
                            conn.commit()

                        subtask_results.append({"description": st_desc, "result": result})
                        # Añadir al contexto (truncado)
                        context.append({"role": "assistant", "content": f"Subtarea completada: {result[:500]}"})
                        _task_log(task_id, "VALIDATING", f"Subtarea {st_row['seq_order']} ✔ validada")
                    else:
                        retry_count = st_row["retry_count"] + 1
                        with closing(_db_conn()) as conn:
                            conn.execute(
                                "UPDATE subtasks SET retry_count=?, error_feedback=? WHERE id=?",
                                (retry_count, feedback[:500], st_id),
                            )
                            conn.commit()
                        _task_log(task_id, "VALIDATING", f"Subtarea {st_row['seq_order']} ✘ inválida: {feedback[:100]}")

            # ── SYNTHESIS ──
            if subtask_results:
                _task_log(task_id, "SYNTHESIS", "Sintetizando resultados…")
                final_result = await _synthesize_results(prompt, subtask_results, http_client)

                if final_result:
                    with closing(_db_conn()) as conn:
                        conn.execute(
                            "UPDATE tasks SET status=?, final_result=?, completed_at=?, updated_at=? WHERE id=?",
                            (TaskStatus.COMPLETED, final_result[:10000], _now_iso(), _now_iso(), task_id),
                        )
                        conn.commit()
                    _task_log(task_id, "COMPLETED", "Tarea completada exitosamente")
                    async with _metrics_lock:
                        _agent_metrics["tasks_ok"] += 1
                else:
                    _fail_task(task_id, "No se pudo sintetizar el resultado final")
            else:
                _fail_task(task_id, "Ninguna subtarea completada exitosamente")

    except asyncio.CancelledError:
        _cancel_task(task_id, "Tarea cancelada")
    except Exception as e:
        log.error(f"[AGENT] Error fatal en tarea {task_id[:8]}: {e}")
        _fail_task(task_id, f"Error interno: {str(e)[:200]}")
    finally:
        _active_agent_tasks.discard(task_id)
        duration = time.monotonic() - t0
        async with _metrics_lock:
            _agent_metrics["total_duration_s"] += duration


def _fail_task(task_id: str, error: str) -> None:
    """Marca una tarea como fallida."""
    with closing(_db_conn()) as conn:
        conn.execute(
            "UPDATE tasks SET status=?, error_message=?, completed_at=?, updated_at=? WHERE id=?",
            (TaskStatus.FAILED, error, _now_iso(), _now_iso(), task_id),
        )
        conn.commit()
    _task_log(task_id, "FAILED", error)
    log.warning(f"[AGENT] Tarea {task_id[:8]} fallida: {error}")


def _cancel_task(task_id: str, reason: str) -> None:
    """Marca una tarea como cancelada."""
    with closing(_db_conn()) as conn:
        conn.execute(
            "UPDATE tasks SET status=?, error_message=?, updated_at=? WHERE id=?",
            (TaskStatus.CANCELLED, reason, _now_iso(), task_id),
        )
        conn.commit()
    _task_log(task_id, "CANCELLED", reason)


# ─────────────────────────────────────────────────────────────────────────────
# RESUME PENDING TASKS
# ─────────────────────────────────────────────────────────────────────────────
async def resume_pending_tasks() -> int:
    """
    Reanuda tareas que quedaron en estado activo tras un reinicio.
    [V21-A5] Marca tareas EXECUTING como FAILED si llevan >1h sin actualización
    para evitar relanzar tareas potencialmente corruptas.
    """
    resumed = 0
    try:
        with closing(_db_conn()) as conn:
            pending = conn.execute(
                "SELECT id, updated_at FROM tasks WHERE status IN (?, ?, ?)",
                (TaskStatus.PLANNING, TaskStatus.EXECUTING, TaskStatus.VALIDATING),
            ).fetchall()

        if not pending:
            return 0

        log.info(f"[AGENT] Encontradas {len(pending)} tarea(s) pendientes tras reinicio")

        for row in pending:
            # [V21-A5] Verificar antigüedad
            try:
                updated = datetime.fromisoformat(row["updated_at"])
                age_seconds = (datetime.now(timezone.utc) - updated).total_seconds()
                if age_seconds > 3600:  # Más de 1 hora
                    _fail_task(row["id"], f"Tarea abandonada tras reinicio (antigüedad: {age_seconds:.0f}s)")
                    log.warning(f"[AGENT] Tarea {row['id'][:8]} marcada como fallida (demasiado antigua)")
                    continue
            except (ValueError, TypeError):
                pass

            asyncio.create_task(run_task(row["id"]))
            resumed += 1
            await asyncio.sleep(1.0)  # Throttling

    except Exception as e:
        log.warning(f"[AGENT] Error reanudando tareas: {e}")

    return resumed


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────
def get_active_tasks() -> set[str]:
    return _active_agent_tasks


def get_metrics() -> dict:
    return dict(_agent_metrics)


def set_shutdown() -> None:
    _shutdown_event.set()


def is_shutdown() -> bool:
    return _shutdown_event.is_set()


async def wait_active_tasks(timeout: float = 30.0) -> int:
    """Espera a que las tareas activas finalicen. Retorna las que no finalizaron."""
    if not _active_agent_tasks:
        return 0
    deadline = time.monotonic() + timeout
    while _active_agent_tasks and time.monotonic() < deadline:
        await asyncio.sleep(1)
    return len(_active_agent_tasks)
