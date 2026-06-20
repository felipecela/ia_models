#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║ orchestrator_router_V14.py — OMEN AI Router V14 (build V26)                ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ Router inteligente multi-nivel para orquestación de modelos locales.        ║
║                                                                              ║
║ Arquitectura refactorizada:                                                  ║
║ • config.py         → Configuración centralizada                             ║
║ • classifier.py     → Clasificador de prompts (4 capas)                     ║
║ • agent_engine.py   → Motor de agente autónomo                              ║
║ • proxy.py          → Proxy HTTP y gestión de VRAM                          ║
║ • rag.py            → Inyección RAG desde ChromaDB                          ║
║                                                                              ║
║ CORRECCIONES V25:                                                            ║
║ ✔ [V25-C1] sanitize_for_ollama normaliza messages[].content array→string.  ║
║            OpenClaw con agente/tools activos envía content como lista       ║
║            de dicts multimodal (OpenAI format). Ollama /api/chat requiere  ║
║            content como string plano → HTTP 400:                           ║
║            "cannot unmarshal array into Go struct field               ║
║             ChatRequest.messages.content of type string"               ║
║            El bloque se ejecuta antes de inject_thinking / check_tools,    ║
║            que asumen content ya como string.                               ║
║            Imágenes/tipos no-text → placeholder "[imagen omitida]".        ║
║                                                                              ║
║ ✔ [V25-FIX-STREAM] Generadores de streaming mantienen context manager      ║
║            abierto. Antes: stream se cerraba prematuramente causando        ║
║            "Attempted to read or stream content, but stream closed".       ║
║            Ahora: async with está DENTRO del generador.                    ║
║                                                                              ║
║ ✔ [V25-FIX-TOKENS] Validación de tokens antes de proxy_request.           ║
║            Estima tokens en messages y trunca si excede max_ctx.           ║
║            Problema: RAG injection + prompts largos → 19321 tokens > 16384 ║
║            contexto (deepseek-r1:14b). Ahora trunca manteniendo system     ║
║            prompts + último mensaje usuario.                                ║
║                                                                              ║
║                                                                              ║
║ CORRECCIONES V24:                                                            ║
║ ✔ [V24-P1] _proxy_streaming: una sola conexión HTTP.                       ║
║ ✔ [V24-D1] log.debug restaurado en sanitize_for_ollama().                  ║
║ ✔ [V24-VS] Version strings actualizadas a 14.24.0.                         ║
║                                                                              ║
║ CORRECCIONES V23:                                                            ║
║ ✔ [V23-S1] sanitize_for_ollama() llamado PRIMERO en la cadena.             ║
║ ✔ [V23-S3] max_completion_tokens → options.num_predict.                    ║
║                                                                              ║
║ (historial completo en comentarios internos de cada módulo)                 ║
║                                                                              ║
║ CORRECCIONES V27 (este fichero + proxy.py + config.py):                     ║
║ ✔ [V27-A1] Banner/versión unificada a build V26 en todos los puntos.        ║
║ ✔ [V27-A2] /v1/models catálogo actualizado para modelos Ollama GPU V26.     ║
║ ✔ [V27-A3] FastAPI app version="14.26.0".                                   ║
║ ✔ [V27-A4] Guard None en request.client para log de autenticación.          ║
║ ✔ [V27-B1] proxy.py: connect=10.0 en _proxy_json y _handle_fallback_json.   ║
║ ✔ [V27-C1] proxy.py: max_tokens raíz → options.num_predict + body.pop.      ║
║ ✔ [V27-C2] proxy.py/config.py: clave phi4-reasoning normalizada lowercase.  ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ Requisitos: pip3 install fastapi uvicorn httpx numpy                        ║
║ Ejecución:  python3 orchestrator_router_V14.py                              ║
║ Puerto:     8000 (configurable con ROUTER_PORT)                             ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import asyncio
import json
import logging
import os
import time
import uuid
from collections import deque
from contextlib import asynccontextmanager, closing
from logging.handlers import RotatingFileHandler
from typing import Optional

import httpx
import uvicorn
from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse

# ─────────────────────────────────────────────────────────────────────────────
# MÓDULOS INTERNOS
# ─────────────────────────────────────────────────────────────────────────────
from omen_router_modules.config import (
    AGENT_DB_DIR,
    AGENT_TO_NIVEL,
    ALIAS_A_NIVEL,
    CHROMA_URL,
    DB_PATH,
    EMBED_CPU_URL,
    EMBED_THRESHOLD,
    HEALTH_TTL,
    LOG_BACKUP_COUNT,
    LOG_DIR,
    LOG_FILE,
    LOG_MAX_BYTES,
    MAX_ACTIVE_TASKS,
    MAX_PROMPT_LEN,
    PHI4_CPU_CHAT_URL,
    PHI4_CPU_TAGS,
    PHI4_GPU_CHAT_URL,
    RATE_LIMIT_MAX,
    RATE_LIMIT_WINDOW,
    RUTAS,
    TIMEOUT_FALLBACK,
    detect_filesystem,
)

from omen_router_modules.classifier import (
    clasificar,
    get_cache_size,
    get_capas_stats,
    get_phi4_model,
    get_vectores_count,
    detectar_phi4,
    precalcular_vectores,
)

from omen_router_modules.agent_engine import (
    TaskStatus,
    TERMINAL_STATES,
    get_active_tasks,
    get_metrics as get_agent_metrics,
    init_db,
    resume_pending_tasks,
    run_task,
    set_shutdown as agent_shutdown,
    wait_active_tasks,
)

from omen_router_modules.proxy import (
    conmutar_vram,
    get_estado,
    get_proxy_metrics,
    inject_opciones_extra,
    inject_thinking,
    check_tools,
    sanitize_for_ollama,   # [V23-S1] — [V25-C1] ahora también normaliza content array→str
    proxy_request,
)

from omen_router_modules.rag import (
    background_health,
    get_collection_id,
    get_inyecciones,
    init_chroma,
    is_disponible as rag_disponible,
    rag_inject,
)

# ─────────────────────────────────────────────────────────────────────────────
# LOGGING — [V21-LOG1] Configuración estructurada
# ─────────────────────────────────────────────────────────────────────────────
os.makedirs(LOG_DIR, exist_ok=True)

log = logging.getLogger("omen-router")
log.setLevel(logging.DEBUG)

_ch = logging.StreamHandler()
_ch.setLevel(logging.INFO)
_ch.setFormatter(logging.Formatter(
    "[%(asctime)s] %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S"
))
log.addHandler(_ch)

try:
    _fh = RotatingFileHandler(LOG_FILE, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT)
    _fh.setLevel(logging.DEBUG)
    _fh.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(name)s: %(message)s"))
    log.addHandler(_fh)
except Exception as e:
    log.warning(f"No se pudo crear log file ({LOG_FILE}): {e}")

# ─────────────────────────────────────────────────────────────────────────────
# [V21-RL1] RATE LIMITING — Con deque (O(1) cleanup)
# ─────────────────────────────────────────────────────────────────────────────
_rate_limit_requests: deque = deque()
_rate_limit_lock = asyncio.Lock()

async def _check_rate_limit() -> bool:
    """Verifica rate limit global. Retorna True si se permite la request."""
    now = time.monotonic()
    async with _rate_limit_lock:
        cutoff = now - RATE_LIMIT_WINDOW
        while _rate_limit_requests and _rate_limit_requests[0] < cutoff:
            _rate_limit_requests.popleft()
        if len(_rate_limit_requests) >= RATE_LIMIT_MAX:
            return False
        _rate_limit_requests.append(now)
        return True

# ─────────────────────────────────────────────────────────────────────────────
# [V21-SEC1] API KEY PARA ENDPOINTS ADMIN
# ─────────────────────────────────────────────────────────────────────────────
_ADMIN_API_KEY = os.environ.get("OMEN_ADMIN_KEY", "")

if not _ADMIN_API_KEY:
    import warnings
    warnings.warn(
        "[SECURITY] OMEN_ADMIN_KEY no configurado. Endpoints /metrics y /health accesibles sin autenticación.",
        category=RuntimeWarning,
        stacklevel=2
    )

def _check_admin_auth(request: Request) -> bool:
    """[V21-SEC1] Verifica autenticación para endpoints administrativos.
    [V26-SEC] Mejora: log detallado de intentos fallidos.
    """
    if not _ADMIN_API_KEY:
        return True
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        valid = auth[7:] == _ADMIN_API_KEY
        if not valid:
            log.warning(f"[AUTH] Bearer token inválido desde {str(request.client or 'unknown')}")
        return valid
    key_param = request.query_params.get("key", "")
    if key_param:
        valid = key_param == _ADMIN_API_KEY
        if not valid:
            log.warning(f"[AUTH] Query key inválido desde {str(request.client or 'unknown')}")
        return valid
    log.debug(f"[AUTH] Sin credentials desde {str(request.client or 'unknown')}")
    return False

# ─────────────────────────────────────────────────────────────────────────────
# MÉTRICAS — [V21-M1] Con lock en lectura
# ─────────────────────────────────────────────────────────────────────────────
_metricas_lock = asyncio.Lock()
_metricas: dict = {
    "requests_por_nivel": {n: 0 for n in RUTAS},
    "errores_por_nivel":  {n: 0 for n in RUTAS},
    "latencia_total_ms":  {n: 0.0 for n in RUTAS},
}

# ─────────────────────────────────────────────────────────────────────────────
# HEALTH CHECK — [V21-HC1] Con cliente compartido
# ─────────────────────────────────────────────────────────────────────────────
_health_cache: dict = {"data": None, "ts": 0.0}

async def _health_ok(url: str, http_client: httpx.AsyncClient, timeout: float = 3.0) -> bool:
    try:
        r = await http_client.get(url, timeout=timeout)
        return r.status_code < 500
    except Exception:
        return False

# ─────────────────────────────────────────────────────────────────────────────
# PHI4 CPU STATE
# ─────────────────────────────────────────────────────────────────────────────
_phi4_cpu_available: bool = False

# ─────────────────────────────────────────────────────────────────────────────
# SHARED HTTP CLIENT — [V21-P3]
# ─────────────────────────────────────────────────────────────────────────────
_shared_http_client: Optional[httpx.AsyncClient] = None

# ═══════════════════════════════════════════════════════════════════════════════
# FASTAPI APP
# ═══════════════════════════════════════════════════════════════════════════════
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _phi4_cpu_available, _shared_http_client

    log.info("═" * 66)
    log.info(" OMEN AI Router V14 (build V26) — iniciando…")
    log.info("═" * 66)

    # [V26-TIMEOUT] Sin timeout global — cada operación especifica el suyo
    _shared_http_client = httpx.AsyncClient(
        timeout=None,  # No hay timeout global; cada request especifica timeout_s
        limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
    )

    init_db()
    await precalcular_vectores(_shared_http_client)

    phi4_model = await detectar_phi4(_shared_http_client)
    if phi4_model:
        log.info(f"[PHI4] Clasificador LLM: {phi4_model} (CPU :11435)")
    else:
        log.warning("[PHI4] Sin clasificador LLM — solo embeddings activos")

    try:
        r = await _shared_http_client.get(PHI4_CPU_TAGS, timeout=5.0)
        if r.status_code == 200:
            modelos_cpu = [m["name"] for m in r.json().get("models", [])]
            _phi4_cpu_available = any(
                m in modelos_cpu for m in ["phi4-mini", "phi4", "phi4:latest"]
            )
    except Exception:
        _phi4_cpu_available = False

    if not _phi4_cpu_available:
        log.warning("[V21] phi4/phi4-mini NO disponible en Ollama CPU (:11435). PHI4_DIRECTO usará GPU.")

    await init_chroma(_shared_http_client)
    health_task = asyncio.create_task(background_health())

    resumed = await resume_pending_tasks()
    if resumed:
        log.info(f"[AGENT] {resumed} tarea(s) reanudada(s)")

    log.info("═" * 66)
    log.info(f" Niveles: {', '.join(RUTAS.keys())}")
    log.info(f" Clasificador: embed({get_vectores_count()}) + {phi4_model or '⚠ sin LLM'}")
    log.info(f" RAG ChromaDB: {'✔ UUID=' + str(get_collection_id())[:8] if rag_disponible() else '⚠ no disponible'}")
    log.info(f" PHI4 CPU: {'✔' if _phi4_cpu_available else '⚠ fallback a GPU'}")
    log.info(f" Agent DB: {DB_PATH}")
    log.info(f" Agent DB FS: {detect_filesystem(AGENT_DB_DIR)}")
    log.info(f" Max tasks: {MAX_ACTIVE_TASKS}")
    log.info(f" Rate limit: {RATE_LIMIT_MAX} req/{RATE_LIMIT_WINDOW}s")
    log.info(f" Admin auth: {'✔ configurada' if _ADMIN_API_KEY else '⚠ sin protección'}")
    log.info(f" Log: {LOG_FILE} (RotatingFileHandler {LOG_MAX_BYTES // (1024*1024)}MB×{LOG_BACKUP_COUNT})")
    log.info(f" Versión: 14.26.0 (V26 fixes: token truncation, tool_result handling, debug logs)")
    log.info("═" * 66)

    yield  # App running

    # ── Shutdown ──────────────────────────────────────────────────────────
    log.info("[SHUTDOWN] Iniciando graceful shutdown…")
    agent_shutdown()

    remaining = await wait_active_tasks(timeout=30.0)
    if remaining:
        log.warning(f"[SHUTDOWN] {remaining} tarea(s) no finalizaron — forzando cierre")

    health_task.cancel()
    try:
        await health_task
    except asyncio.CancelledError:
        pass

    if _shared_http_client:
        await _shared_http_client.aclose()

    log.info("[SHUTDOWN] ✔ Router V14 detenido correctamente")


app = FastAPI(
    title="OMEN AI Router V14",
    version="14.26.0",
    lifespan=lifespan,
)

# ═══════════════════════════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/")
async def raiz():
    return {
        "servicio": "OMEN AI Router V14",
        "build": "V26",
        "version": "14.26.0",
        "niveles": list(RUTAS.keys()),
        "agent": True,
        "fixes": ["[V26] Token truncation fixed", "[V26] Tool result handling improved", "[V26] Debug logging for OpenClaw"]
    }


@app.get("/health")
async def health(request: Request):
    """Health check con caché TTL + estado del Agent Engine."""
    now = time.monotonic()
    if _health_cache["data"] and (now - _health_cache["ts"]) < HEALTH_TTL:
        return _health_cache["data"]

    if not _shared_http_client:
        return JSONResponse(content={"status": "starting"}, status_code=503)

    vistos: dict[str, bool] = {}
    backends: dict[str, bool] = {}
    for n, r in RUTAS.items():
        url = r["health_url"]
        if url not in vistos:
            vistos[url] = await _health_ok(url, _shared_http_client)
        backends[n] = vistos[url]

    chroma_ok  = await _health_ok(f"{CHROMA_URL}/api/v2/heartbeat", _shared_http_client)
    
    # [V26-DEBUG] Track ChromaDB status changes (safe null check)
    cached_data = _health_cache.get("data") or {}
    prev_chroma_ok = cached_data.get("herramientas", {}).get("chromadb_rag") if isinstance(cached_data, dict) else None
    if prev_chroma_ok is not None and prev_chroma_ok != chroma_ok:
        log.warning(f"[HEALTH] ChromaDB estado cambió: {prev_chroma_ok} → {chroma_ok}")
    
    searxng_ok = await _health_ok("http://localhost:8888/search?q=test&format=json", _shared_http_client, timeout=4.0)
    embed_ok   = await _health_ok(EMBED_CPU_URL.replace("/api/embeddings", "/api/tags"), _shared_http_client)

    from omen_router_modules.agent_engine import _db_conn
    agent_stats = {"db_path": DB_PATH, "db_exists": os.path.exists(DB_PATH)}
    try:
        with closing(_db_conn()) as conn:
            agent_stats["tasks_total"]  = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
            agent_stats["tasks_active"] = conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE status IN (?, ?, ?)",
                (TaskStatus.PLANNING, TaskStatus.EXECUTING, TaskStatus.VALIDATING),
            ).fetchone()[0]
    except Exception:
        agent_stats["tasks_total"]  = 0
        agent_stats["tasks_active"] = 0

    result = {
        "status":         "ok",
        "version":        "14.26.0",
        "build":          "V26",
        "ruta_activa":    get_estado()["ruta_activa"],
        "tabbyapi_model": get_estado()["tabbyapi_modelo"],
        "backends":       backends,
        "herramientas": {
            "chromadb_rag":    chroma_ok,
            "searxng_web":     searxng_ok,
            "ollama_cpu_embed": embed_ok,
        },
        "clasificador": {
            "embed_vectores": get_vectores_count(),
            "phi4_model":     get_phi4_model(),
            "phi4_cpu_avail": _phi4_cpu_available,
            "embed_threshold": EMBED_THRESHOLD,
        },
        "rag_disponible":    rag_disponible(),
        "chroma_collection": get_collection_id(),
        "cache_entradas":    get_cache_size(),
        "agent":             agent_stats,
    }

    _health_cache.update({"data": result, "ts": now})
    return result


@app.get("/metrics")
async def metrics(request: Request):
    """[V21-M1] Métricas con lock en lectura."""
    if not _check_admin_auth(request):
        return JSONResponse(content={"error": "Unauthorized"}, status_code=401)

    async with _metricas_lock:
        reqs = dict(_metricas["requests_por_nivel"])
        errs = dict(_metricas["errores_por_nivel"])
        lats = dict(_metricas["latencia_total_ms"])

    proxy_metrics = get_proxy_metrics()
    agent_metrics = get_agent_metrics()
    capas = get_capas_stats()

    return {
        "requests_por_nivel": reqs,
        "errores_por_nivel":  errs,
        "fallbacks":          proxy_metrics.get("fallbacks", {}),
        "latencia_prom_ms":   {n: round(lats[n] / max(1, reqs[n]), 1) for n in RUTAS},
        "cambios_vram":       proxy_metrics.get("cambios_vram", 0),
        "rag_inyecciones":    get_inyecciones(),
        "clasificador_capas": capas,
        "cache_hit_ratio":    round(capas.get("cache", 0) / max(1, sum(capas.values())), 3),
        "agent": {
            "tasks_total":     agent_metrics.get("tasks_total", 0),
            "tasks_ok":        agent_metrics.get("tasks_ok", 0),
            "tasks_failed":    agent_metrics.get("tasks_failed", 0),
            "tasks_cancelled": agent_metrics.get("tasks_cancelled", 0),
            "avg_duration_s":  round(
                agent_metrics.get("total_duration_s", 0) /
                max(1, agent_metrics.get("tasks_ok", 0) + agent_metrics.get("tasks_failed", 0)), 1
            ),
            "active_now": len(get_active_tasks()),
            "max_active": MAX_ACTIVE_TASKS,
        },
    }


@app.get("/v1/models")
async def modelos():
    ts = int(time.time())
    catalog = [
        {"id": "ruteador-auto",    "name": "Auto — clasificador 4 capas",            "ctx": 32768, "max": 16384},
        {"id": "chat",             "name": "Chat rápido (phi4-mini)",               "ctx": 8192,  "max": 4096},
        {"id": "instantaneo",      "name": "Instantáneo (phi4-mini · respuesta ultra-rápida)",         "ctx": 4096,  "max": 2048},
        {"id": "agil",             "name": "Ágil (phi4 · análisis, documentos, agentes)",    "ctx": 32768, "max": 8192},
        {"id": "profundo",         "name": "Profundo (DeepSeek R1 14B)",             "ctx": 16384, "max": 8192},
        {"id": "phi-mayor-precision", "name": "Phi Mayor Precisión (phi4-reasoning:plus)", "ctx": 16384, "max": 4096},
        {"id": "phi-optimizada",   "name": "Phi Optimizada (phi4-reasoning:14b-q4_K_M)", "ctx": 16384, "max": 4096},
        {"id": "masivo",           "name": "Masivo (Qwen2.5 32B · análisis extenso)","ctx": 32768, "max": 16384},
        {"id": "codigo",           "name": "Código (deepseek-coder-v2 · programación)",         "ctx": 4096,  "max": 2048},
        {"id": "phi4",             "name": "Phi-4 CPU (clasificador directo)",       "ctx": 16384, "max": 4096},
        {"id": "agent-autonomo",   "name": "Agente Autónomo (planifica+ejecuta+valida)", "ctx": 32768, "max": 16384},
        {"id": "deepseek-r1:14b"},
        {"id": "qwen2.5:32b"},
        {"id": "llama-3.1-8b-awq"},
        {"id": "qwen2.5-coder-7b-exl2"},
        {"id": "llama-3.1-8b-exl2"},
        {"id": "phi4-reasoning:plus"},
        {"id": "phi4-reasoning:14b-q4_K_M"},
    ]
    return {
        "object": "list",
        "data": [
            {
                "id": m["id"],
                "object": "model",
                "created": ts,
                "owned_by": "omen-local",
                "name": m.get("name", ""),
                "context_window": m.get("ctx"),
                "max_tokens": m.get("max"),
            }
            for m in catalog
        ],
    }


@app.post("/v1/chat/completions")
async def chat(request: Request):
    """Endpoint principal de chat con clasificación y enrutamiento."""
    t0 = time.monotonic()

    if not await _check_rate_limit():
        return JSONResponse(
            content={"error": {"message": f"Rate limit exceeded ({RATE_LIMIT_MAX} req/min)", "type": "rate_limit"}},
            status_code=429,
        )

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            content={"error": {"message": "Body JSON inválido", "type": "validation_error"}},
            status_code=400,
        )

    if not isinstance(body, dict):
        return JSONResponse(
            content={"error": {"message": "Body debe ser un objeto JSON", "type": "validation_error"}},
            status_code=400,
        )

    mensajes = body.get("messages", [])
    if not isinstance(mensajes, list) or not mensajes:
        return JSONResponse(
            content={"error": {"message": "El campo 'messages' es obligatorio y debe ser una lista no vacía", "type": "validation_error"}},
            status_code=400,
        )

    last_msg = mensajes[-1]
    if not isinstance(last_msg, dict) or "content" not in last_msg:
        return JSONResponse(
            content={"error": {"message": "Cada mensaje debe tener 'role' y 'content'", "type": "validation_error"}},
            status_code=400,
        )

    modelo_raw  = str(body.get("model", "ruteador-auto")).strip()
    modelo_lower = modelo_raw.lower()
    # [V25-C1] content puede ser lista aún; sanitize_for_ollama la normalizará.
    # Para clasificar usamos sólo el fragmento de texto si es string.
    raw_content = last_msg.get("content", "")
    if isinstance(raw_content, list):
        prompt = " ".join(
            p.get("text", "") for p in raw_content
            if isinstance(p, dict) and p.get("type") == "text"
        )
    else:
        prompt = raw_content if isinstance(raw_content, str) else ""

    streaming  = body.get("stream", False)
    agent_id   = request.headers.get("x-openclaw-agent", "").strip().lower()

    log.info(f"\n{'─' * 66}")
    log.info(f"[REQ] modelo='{modelo_raw}' agente='{agent_id}' stream={streaming}")
    log.info(f"[PROMPT] {prompt[:130]}…")
    
    # [V26-DEBUG] Log detallado para OpenClaw requests
    if agent_id:
        content_types = []
        for m in mensajes:
            if isinstance(m, dict):
                c = m.get("content")
                if isinstance(c, list):
                    content_types.extend([p.get("type", "unknown") for p in c if isinstance(p, dict)])
                else:
                    content_types.append("string")
        log.debug(f"[OPENCLAW-AGENT] agent_id='{agent_id}' | content_types={content_types} | tools={'tools' in body}")

    # ── Resolver nivel ─────────────────────────────────────────────────────
    nivel = ALIAS_A_NIVEL.get(modelo_lower)

    if nivel == "PHI4_DIRECTO":
        log.info("[MODO] → Phi-4 CPU directo")
        phi4_model = get_phi4_model() or "phi4-mini"
        if _phi4_cpu_available:
            target = PHI4_CPU_CHAT_URL
        else:
            log.warning("[V21] phi4 no disponible en CPU — redirigiendo a GPU")
            target = PHI4_GPU_CHAT_URL
        body["model"] = phi4_model
        return await proxy_request(body, target, request, streaming, "CHAT", _shared_http_client)

    elif nivel == "AGENT":
        return JSONResponse(
            content={"error": {"message": "Usa POST /v1/agent/tasks para el agente autónomo", "type": "redirect"}},
            status_code=400,
        )

    elif nivel is None:
        nivel, fuente = await clasificar(prompt, agent_id, _shared_http_client)
        log.info(f"[MODO: AUTO] → {nivel} (fuente: {fuente})")
    else:
        log.info(f"[MODO: MANUAL] → {nivel}")

    if nivel == "PRECISO" and len(prompt) < 300:
        nivel = "PRECISO_OPT"
        log.info("[PRECISO_OPT] Prompt < 300 chars — usando variante optimizada")

    # ── RAG injection ───────────────────────────────────────────────────────
    body = await rag_inject(body, prompt, nivel, _shared_http_client)

    # ── Conmutar VRAM ───────────────────────────────────────────────────────
    target_url   = await conmutar_vram(nivel, _shared_http_client)
    body["model"] = RUTAS[nivel]["modelo"]

    # ── Ajustes del body ────────────────────────────────────────────────────
    # [V25-C1] sanitize PRIMERO — normaliza content array→str + limpia campos OpenAI
    body = sanitize_for_ollama(body, nivel, body["model"])
    body = inject_opciones_extra(body, nivel, body["model"])
    body = inject_thinking(body, nivel, body["model"])
    body = check_tools(body, nivel, body["model"])

    log.info(f"[PROXY] {nivel} → '{body['model']}' @ {target_url}")

    # ── Métricas y envío ────────────────────────────────────────────────────
    async with _metricas_lock:
        _metricas["requests_por_nivel"][nivel] += 1

    try:
        result = await proxy_request(body, target_url, request, streaming, nivel, _shared_http_client)
    except Exception as exc:
        async with _metricas_lock:
            _metricas["errores_por_nivel"][nivel] += 1
        raise exc

    async with _metricas_lock:
        _metricas["latencia_total_ms"][nivel] += (time.monotonic() - t0) * 1000
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# ENDPOINTS — Autonomous Reasoning Agent
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/v1/agent/tasks")
async def create_agent_task(request: Request):
    """Crea una nueva tarea para el agente autónomo."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            content={"error": {"message": "Body JSON inválido", "type": "validation_error"}},
            status_code=400,
        )

    if not isinstance(body, dict):
        return JSONResponse(
            content={"error": {"message": "Body debe ser un objeto JSON", "type": "validation_error"}},
            status_code=400,
        )

    prompt = body.get("prompt", "").strip() if isinstance(body.get("prompt"), str) else ""

    if not prompt:
        return JSONResponse(
            content={"error": {"message": "El campo 'prompt' es obligatorio", "type": "validation_error"}},
            status_code=400,
        )

    if len(prompt) > MAX_PROMPT_LEN:
        return JSONResponse(
            content={"error": {"message": f"Prompt demasiado largo ({len(prompt)} chars, máx {MAX_PROMPT_LEN})", "type": "validation_error"}},
            status_code=400,
        )

    if len(get_active_tasks()) >= MAX_ACTIVE_TASKS:
        return JSONResponse(
            content={"error": {"message": f"Límite de tareas activas alcanzado ({MAX_ACTIVE_TASKS})", "type": "rate_limit"}},
            status_code=429,
        )

    max_iterations = min(max(body.get("max_iterations", 3), 1), 10)
    task_id = str(uuid.uuid4())
    now = _now_iso()

    from omen_router_modules.agent_engine import _db_conn
    with closing(_db_conn()) as conn:
        conn.execute(
            "INSERT INTO tasks (id, prompt, status, max_iterations, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (task_id, prompt, TaskStatus.PENDING, max_iterations, now, now),
        )
        conn.commit()

    asyncio.create_task(run_task(task_id))
    log.info(f"[AGENT] Nueva tarea creada: {task_id[:8]}… (max_iter={max_iterations})")

    return JSONResponse(
        content={
            "task_id": task_id,
            "status": TaskStatus.PENDING,
            "message": "Tarea creada. Usa GET /v1/agent/tasks/{task_id} para consultar el progreso.",
        },
        status_code=202,
    )


@app.get("/v1/agent/tasks/{task_id}")
async def get_agent_task(task_id: str):
    """Consulta el estado y resultado de una tarea del agente."""
    from omen_router_modules.agent_engine import _db_conn
    with closing(_db_conn()) as conn:
        task = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not task:
            return JSONResponse(
                content={"error": {"message": "Tarea no encontrada", "type": "not_found"}},
                status_code=404,
            )

        subtasks = conn.execute(
            "SELECT id, seq_order, description, required_level, status, retry_count, error_feedback "
            "FROM subtasks WHERE task_id=? ORDER BY seq_order",
            (task_id,),
        ).fetchall()

        logs = conn.execute(
            "SELECT phase, message, timestamp FROM task_logs WHERE task_id=? ORDER BY id DESC LIMIT 20",
            (task_id,),
        ).fetchall()

    response = {
        "task_id":             task["id"],
        "status":              task["status"],
        "prompt":              task["prompt"][:200] + ("…" if len(task["prompt"]) > 200 else ""),
        "total_subtasks":      task["total_subtasks"],
        "completed_subtasks":  task["completed_subtasks"],
        "current_iteration":   task["current_iteration"],
        "max_iterations":      task["max_iterations"],
        "created_at":          task["created_at"],
        "updated_at":          task["updated_at"],
        "completed_at":        task["completed_at"],
        "error_message":       task["error_message"],
        "subtasks": [
            {
                "id": st["id"], "seq_order": st["seq_order"], "description": st["description"],
                "required_level": st["required_level"], "status": st["status"],
                "retry_count": st["retry_count"], "error_feedback": st["error_feedback"],
            }
            for st in subtasks
        ],
        "recent_logs": [
            {"phase": l["phase"], "message": l["message"], "timestamp": l["timestamp"]}
            for l in logs
        ],
    }

    if task["status"] == TaskStatus.COMPLETED and task["final_result"]:
        response["final_result"] = task["final_result"]

    return JSONResponse(content=response)


@app.get("/v1/agent/tasks")
async def list_agent_tasks(status: Optional[str] = None, limit: int = 20):
    """Lista las tareas del agente."""
    from omen_router_modules.agent_engine import _db_conn
    with closing(_db_conn()) as conn:
        if status:
            tasks = conn.execute(
                "SELECT id, status, prompt, total_subtasks, completed_subtasks, created_at, updated_at, completed_at "
                "FROM tasks WHERE status=? ORDER BY created_at DESC LIMIT ?",
                (status.upper(), min(limit, 100)),
            ).fetchall()
        else:
            tasks = conn.execute(
                "SELECT id, status, prompt, total_subtasks, completed_subtasks, created_at, updated_at, completed_at "
                "FROM tasks ORDER BY created_at DESC LIMIT ?",
                (min(limit, 100),),
            ).fetchall()

    return JSONResponse(content={
        "tasks": [
            {
                "task_id": t["id"], "status": t["status"],
                "prompt_preview": t["prompt"][:100] + ("…" if len(t["prompt"]) > 100 else ""),
                "total_subtasks": t["total_subtasks"], "completed_subtasks": t["completed_subtasks"],
                "created_at": t["created_at"], "completed_at": t["completed_at"],
            }
            for t in tasks
        ],
        "count": len(tasks),
    })


@app.delete("/v1/agent/tasks/{task_id}")
async def cancel_agent_task(task_id: str):
    """Cancela una tarea en ejecución."""
    from omen_router_modules.agent_engine import _db_conn
    with closing(_db_conn()) as conn:
        task = conn.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not task:
            return JSONResponse(
                content={"error": {"message": "Tarea no encontrada", "type": "not_found"}},
                status_code=404,
            )

        if task["status"] in TERMINAL_STATES:
            return JSONResponse(
                content={"message": f"Tarea ya finalizada con estado: {task['status']}"},
                status_code=409,
            )

        conn.execute(
            "UPDATE tasks SET status=?, updated_at=? WHERE id=?",
            (TaskStatus.CANCELLED, _now_iso(), task_id),
        )
        conn.commit()

    log.info(f"[AGENT] Tarea {task_id[:8]} cancelada")
    return JSONResponse(content={"message": "Tarea cancelada", "task_id": task_id})


@app.get("/v1/agent/tasks/{task_id}/result")
async def get_agent_task_result(task_id: str):
    """Obtiene el resultado final de una tarea completada."""
    from omen_router_modules.agent_engine import _db_conn
    with closing(_db_conn()) as conn:
        task = conn.execute(
            "SELECT status, final_result, error_message FROM tasks WHERE id=?", (task_id,)
        ).fetchone()

    if not task:
        return JSONResponse(
            content={"error": {"message": "Tarea no encontrada", "type": "not_found"}},
            status_code=404,
        )

    if task["status"] != TaskStatus.COMPLETED:
        return JSONResponse(
            content={"error": {"message": f"Tarea en estado '{task['status']}'", "type": "not_ready"}, "status": task["status"]},
            status_code=202,
        )

    return JSONResponse(content={"task_id": task_id, "status": TaskStatus.COMPLETED, "result": task["final_result"]})


@app.get("/v1/agent/tasks/{task_id}/stream")
async def stream_agent_task(task_id: str):
    """Streaming SSE del progreso de una tarea."""
    from omen_router_modules.agent_engine import _db_conn
    with closing(_db_conn()) as conn:
        task = conn.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()

    if not task:
        return JSONResponse(
            content={"error": {"message": "Tarea no encontrada", "type": "not_found"}},
            status_code=404,
        )

    async def _event_stream():
        last_log_id = 0
        while True:
            try:
                with closing(_db_conn()) as conn:
                    current = conn.execute(
                        "SELECT status, completed_subtasks, total_subtasks FROM tasks WHERE id=?",
                        (task_id,),
                    ).fetchone()

                    new_logs = conn.execute(
                        "SELECT id, phase, message, timestamp FROM task_logs "
                        "WHERE task_id=? AND id > ? ORDER BY id",
                        (task_id, last_log_id),
                    ).fetchall()

                if not current:
                    yield f"data: {json.dumps({'event': 'error', 'message': 'Tarea eliminada'})}\n\n"
                    return

                for log_entry in new_logs:
                    last_log_id = log_entry["id"]
                    event_data = {
                        "event":     "log",
                        "phase":     log_entry["phase"],
                        "message":   log_entry["message"],
                        "timestamp": log_entry["timestamp"],
                    }
                    yield f"data: {json.dumps(event_data, ensure_ascii=False)}\n\n"

                progress_data = {
                    "event":     "progress",
                    "status":    current["status"],
                    "completed": current["completed_subtasks"],
                    "total":     current["total_subtasks"],
                }
                yield f"data: {json.dumps(progress_data)}\n\n"

                if current["status"] in TERMINAL_STATES:
                    with closing(_db_conn()) as conn:
                        final = conn.execute(
                            "SELECT final_result, error_message FROM tasks WHERE id=?", (task_id,)
                        ).fetchone()
                    done_data = {
                        "event":  "done",
                        "status": current["status"],
                        "result": final["final_result"] if final else None,
                        "error":  final["error_message"] if final else None,
                    }
                    yield f"data: {json.dumps(done_data, ensure_ascii=False)}\n\n"
                    return

            except asyncio.CancelledError:
                return
            except Exception as e:
                yield f"data: {json.dumps({'event': 'error', 'message': str(e)})}\n\n"
                return

            await asyncio.sleep(2)

    return StreamingResponse(_event_stream(), media_type="text/event-stream")


# ─────────────────────────────────────────────────────────────────────────────
# UTILIDADES
# ─────────────────────────────────────────────────────────────────────────────
def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    port = int(os.environ.get("ROUTER_PORT", "8000"))
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info",
        access_log=False,
    )
