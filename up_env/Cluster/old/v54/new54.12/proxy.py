#!/usr/bin/env python3
"""
proxy.py - OMEN AI Router V14 (build V27)
Proxy HTTP y gestion de VRAM.

Cambios:
V21-P1: Estado transitorio SWITCHING durante conmutacion VRAM.
V21-P3: Reutilizacion de httpx.AsyncClient.
V22-T1: inject_thinking para phi4-reasoning:*.
V22-T2: check_tools serializa tools a texto plano.
V22-C1: inject_opciones_extra garantiza num_ctx=16384 en GPU.
V22-C2: check_tools devuelve dict (antes None).
V23-S1: sanitize_for_ollama elimina campos OpenAI incompatibles.
V23-S3: max_completion_tokens -> options.num_predict.
V24-P1: _proxy_streaming usa una sola conexion HTTP (sin doble generacion).
V24-D1: log.debug de campos del body restaurado en sanitize_for_ollama.
V25-C1: sanitize_for_ollama normaliza messages[].content array -> string.
         Ollama /api/chat requiere content como string plano. OpenClaw con
         agente/tools activos envia content como lista de dicts multimodal
         -> Ollama responde HTTP 400 (cannot unmarshal array into string).
V25-FIX: Dos correcciones críticas:
  [V25-FIX-STREAM] Generadores _gen() y _gen_fb() mantienen context manager
         abierto durante ejecución. Antes el stream se cerraba prematuramente
         causando "Attempted to read or stream content, but stream closed".
  [V25-FIX-TOKENS] Validación de tokens antes de enviar. Estima tokens en
         messages y valida contra max_ctx del modelo. Si excede, trunca
         manteniendo system prompts + último user message.
"""

import asyncio
import json
import logging

import httpx
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse

from omen_router_modules.config import (
    RUTAS,
    TABBYAPI_MODEL_LOAD,
    TABBYAPI_MODEL_UNLOAD,
    TABBYAPI_MODELS,
    TIMEOUT_FALLBACK,
)

log = logging.getLogger("omen-router.proxy")

# ---------------------------------------------------------------------------
# CAPACIDADES POR MODELO
# ---------------------------------------------------------------------------

_TOOLS_SUPPORTED = {
    "qwen2.5:32b",
    "qwen2.5:7b",
    "qwen2.5-coder:7b",
    "llama3.1:8b",
    "llama3.2:3b",
    "mistral:7b",
    "mistral-nemo",
}

_THINK_MODELS = {
    "deepseek-r1:14b",
    "phi4-reasoning:plus",
    "phi4-reasoning:14b-q4_k_m",
}

_GPU_NIVELES = {"PROFUNDO", "PRECISO", "PRECISO_OPT", "MASIVO", "AGIL"}
_MIN_CTX_GPU = 16384

# ---------------------------------------------------------------------------
# [V25-FIX-TOKENS] Estimación de tokens y validación de contexto
# ---------------------------------------------------------------------------

# Contextos máximos por modelo (en tokens)
_MODEL_MAX_CTX = {
    "deepseek-r1:14b": 16384,
    "phi4-reasoning:plus": 16384,
    "phi4-reasoning:14b-q4_k_m": 16384,
    "qwen2.5:32b": 4096,   # [V28-CTX-ALIGN] Alineado con options.num_ctx real de MASIVO
    "qwen2.5:7b": 32768,
    "qwen2.5-coder:7b": 32768,
    "qwen2.5-coder-7b-exl2": 32768,
    "llama-3.1-8b-exl2": 8192,
    "llama-3.1-8b-awq": 8192,
    "llama3.1:8b": 8192,
    "llama3.2:3b": 8192,
    "mistral:7b": 32768,
    "mistral-nemo": 32768,
}

def estimate_tokens(text: str) -> int:
    """Estima tokens usando heurística: ~1 token ≈ 4 caracteres.
    [V25-FIX-TOKENS] Método simple pero efectivo para detección temprana."""
    if not isinstance(text, str):
        text = str(text)
    # Regla empírica: whitespace cuenta como tokens también
    return max(1, len(text.split()) + len(text) // 4)

def estimate_body_tokens(body: dict) -> int:
    """Estima tokens totales en el body (messages + system prompts).
    [V25-FIX-TOKENS]"""
    total = 0
    
    # Messages
    for msg in body.get("messages", []):
        if isinstance(msg, dict):
            content = msg.get("content", "")
            if isinstance(content, str):
                total += estimate_tokens(content)
            elif isinstance(content, list):
                # Fallback si aún hay arrays (antes de sanitize)
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        total += estimate_tokens(part.get("text", ""))
    
    # System prompts inyectados en tools
    if "tools" in body:
        tools_text = "\n".join(str(t) for t in body["tools"])
        total += estimate_tokens(tools_text)
    
    # Margen de seguridad: +10% para headers/control tokens
    return int(total * 1.1)

def validate_and_truncate_messages(body: dict, nivel: str, model: str) -> dict:
    """[V25-FIX-TOKENS] Valida que los mensajes caben en el contexto.
    Si no, trunca el historial manteniendo system + últimos mensajes.
    [V26-FIX] Recalcula tokens después de cada truncamiento hasta caber en contexto.
    """
    
    max_ctx = _MODEL_MAX_CTX.get(model, 16384)
    # Reservar 20% para respuesta + overhead
    max_input_tokens = int(max_ctx * 0.8)
    
    estimated = estimate_body_tokens(body)
    
    if estimated <= max_input_tokens:
        log.debug("[V25-TOKEN] OK: %d tokens (max %d) en %s", estimated, max_input_tokens, model)
        return body
    
    log.warning(
        "[V25-TOKEN] Exceso de tokens: %d > %d (%s/%s)",
        estimated, max_input_tokens, nivel, model
    )
    
    messages = body.get("messages", [])
    if not messages:
        return body
    
    # Mantener: system messages + último user message
    system_msgs = [m for m in messages if isinstance(m, dict) and m.get("role") == "system"]
    user_msgs = [m for m in messages if isinstance(m, dict) and m.get("role") != "system"]
    
    if user_msgs:
        # [V26-FIX] Mantener solo el último mensaje del usuario
        new_messages = system_msgs + [user_msgs[-1]]
    else:
        new_messages = system_msgs
    
    body["messages"] = new_messages
    new_estimated = estimate_body_tokens(body)
    
    # [V26-FIX] Si aún excede, truncar el contenido del mensaje usuario
    if new_estimated > max_input_tokens and user_msgs:
        last_user = user_msgs[-1]
        content = last_user.get("content", "")
        if isinstance(content, str):
            # Truncar por palabras hasta caber
            words = content.split()
            while len(words) > 5 and estimate_body_tokens(body) > max_input_tokens:
                words.pop()
            last_user["content"] = " ".join(words)
            new_estimated = estimate_body_tokens(body)
            log.info("[V26-FIX-CONTENT] Contenido truncado a %d palabras", len(words))
    
    log.info("[V25-TOKEN] Truncado: %d → %d tokens", estimated, new_estimated)
    return body


# ---------------------------------------------------------------------------
# [V23-S1] CAMPOS OPENAI INCOMPATIBLES CON OLLAMA /api/chat
# ---------------------------------------------------------------------------

_OLLAMA_UNSUPPORTED = {
    "stream_options",
    "max_completion_tokens",
    "logprobs",
    "top_logprobs",
    "service_tier",
    "store",
}

def sanitize_for_ollama(body: dict, nivel: str, model: str) -> dict:
    """[V23-S1] Elimina campos OpenAI que Ollama no acepta.
    [V23-S3] Convierte max_completion_tokens -> options.num_predict.
    [V24-D1] Loguea campos eliminados a nivel DEBUG.
    [V25-C1] Normaliza messages[].content array -> string plano.
             Ollama /api/chat exige content como string. OpenClaw con modo
             agente envia content como lista multimodal OpenAI, lo que provoca
             HTTP 400: cannot unmarshal array into Go struct field
             ChatRequest.messages.content of type string.
             Este bloque se ejecuta PRIMERO, antes de inject_thinking y
             check_tools, que asumen que content ya es string.
    """
    removed = []

    # ── [V25-C1] Normalizar content array -> string ──────────────────────────
    # [V26-TOOLS] Incluir tool_result como contexto en el mensaje
    for msg in body.get("messages", []):
        content = msg.get("content")
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, dict):
                    ptype = part.get("type", "")
                    if ptype == "text":
                        parts.append(part.get("text", ""))
                    elif ptype == "tool_result":
                        # [V26-TOOLS] Incluir resultados de tools como contexto
                        tool_use_id = part.get("tool_use_id", "unknown")
                        tool_content = part.get("content", "")
                        if isinstance(tool_content, str):
                            parts.append(f"[Tool '{tool_use_id}' result]: {tool_content}")
                        else:
                            # Si el contenido es complejo (JSON, etc), convertir a string
                            parts.append(f"[Tool '{tool_use_id}' result]: {str(tool_content)[:500]}")
                    elif ptype in ("image_url", "image"):
                        # Modelos Ollama de este cluster no son multimodales.
                        parts.append("[imagen omitida — modelo sin soporte multimodal]")
                    # Otros tipos se descartan
                elif isinstance(part, str):
                    parts.append(part)
            msg["content"] = "\n".join(parts)
            log.debug(
                "[V25-C1] content array->string en role='%s' (%d partes)",
                msg.get("role", "?"), len(content),
            )
    # ─────────────────────────────────────────────────────────────────────────

    # [V23-S3] max_completion_tokens -> options.num_predict
    if "max_completion_tokens" in body:
        mct = body.pop("max_completion_tokens")
        removed.append("max_completion_tokens")
        if "max_tokens" not in body:
            opts = body.get("options", {})
            if not isinstance(opts, dict):
                opts = {}
            opts.setdefault("num_predict", mct)
            body["options"] = opts

    # [V23-S1] Eliminar campos OpenAI no soportados por Ollama
    for campo in (_OLLAMA_UNSUPPORTED - {"max_completion_tokens"}):
        if campo in body:
            body.pop(campo)
            removed.append(campo)

    if removed:
        log.debug("[V23-S1] sanitize_for_ollama [%s/%s] eliminados: %s", nivel, model, removed)

    non_msg = {k: v for k, v in body.items() if k != "messages"}
    log.debug(
        "[V24-D1] body_campos=%s | non_msg=%s",
        list(body.keys()),
        json.dumps(non_msg, ensure_ascii=False, default=str)[:400],
    )

    return body

# ---------------------------------------------------------------------------
# ESTADO DE VRAM
# ---------------------------------------------------------------------------

_vram_lock = asyncio.Lock()
_vram_switch_event = asyncio.Event()
_vram_switch_event.set()

_estado: dict = {
    "ruta_activa": "CHAT",
    "tabbyapi_modelo": "llama-3.1-8b-exl2",
    "switching": False,
}

_proxy_metrics: dict = {
    "cambios_vram": 0,
    "fallbacks": {},
}

_metrics_lock = asyncio.Lock()

async def conmutar_vram(nivel: str, http_client: httpx.AsyncClient) -> str:
    """Conmuta el modelo en VRAM si es necesario. Retorna la URL del backend."""
    ruta = RUTAS[nivel]

    if ruta["backend"] != "tabbyapi":
        return ruta["url"]

    modelo_requerido = ruta["modelo"]

    if _estado["tabbyapi_modelo"] == modelo_requerido and not _estado["switching"]:
        return ruta["url"]

    if _estado["switching"]:
        log.debug("[VRAM] Esperando switch en curso para %s...", nivel)
        try:
            await asyncio.wait_for(_vram_switch_event.wait(), timeout=60.0)
        except asyncio.TimeoutError:
            log.error("[VRAM] Timeout esperando switch -- usando URL actual")
            return ruta["url"]

    if _estado["tabbyapi_modelo"] == modelo_requerido:
        return ruta["url"]

    async with _vram_lock:
        if _estado["tabbyapi_modelo"] == modelo_requerido:
            return ruta["url"]

        _estado["switching"] = True
        _vram_switch_event.clear()

        try:
            log.info("[VRAM] Conmutando: %s -> %s", _estado["tabbyapi_modelo"], modelo_requerido)

            try:
                await http_client.post(TABBYAPI_MODEL_UNLOAD, timeout=30.0)
            except Exception as exc:
                log.warning("[VRAM] Error descargando modelo: %s", exc)

            try:
                resp = await http_client.post(
                    TABBYAPI_MODEL_LOAD,
                    json={"model_name": modelo_requerido},
                    timeout=120.0,
                )

                if resp.status_code == 200:
                    _estado["tabbyapi_modelo"] = modelo_requerido
                    _estado["ruta_activa"] = nivel
                    async with _metrics_lock:
                        _proxy_metrics["cambios_vram"] += 1
                    log.info("[VRAM] Modelo cargado: %s", modelo_requerido)
                else:
                    log.error(
                        "[VRAM] Error cargando %s: HTTP %s",
                        modelo_requerido, resp.status_code,
                    )

            except httpx.TimeoutException:
                log.error("[VRAM] Timeout cargando %s", modelo_requerido)
            except Exception as exc:
                log.error("[VRAM] Error inesperado: %s", exc)

        finally:
            _estado["switching"] = False
            _vram_switch_event.set()

    return ruta["url"]

# ---------------------------------------------------------------------------
# INYECCIONES EN EL BODY
# ---------------------------------------------------------------------------

def inject_opciones_extra(body: dict, nivel: str, modelo: str = "") -> dict:
    """[V22-C1] Inyecta opciones del nivel y garantiza num_ctx >= 16384 en GPU.
    [V27-C2] FIX: opciones_extra puede incluir sub-dict 'options' con num_predict.
             Se mergea en body["options"] correctamente.
             Ollama ignora "max_tokens" en root -> solo atiende options.num_predict.
    """
    extras = RUTAS[nivel].get("opciones_extra") or {}
    for k, v in extras.items():
        if k == "options" and isinstance(v, dict):
            # [V27-C2] Mergear sub-dict options en body["options"]
            opts = body.get("options", {})
            if not isinstance(opts, dict):
                opts = {}
            for ok, ov in v.items():
                opts.setdefault(ok, ov)
            body["options"] = opts
        else:
            body.setdefault(k, v)

    if nivel in _GPU_NIVELES:
        opts = body.get("options", {})
        if not isinstance(opts, dict):
            opts = {}
        if opts.get("num_ctx", 0) < _MIN_CTX_GPU:
            opts["num_ctx"] = _MIN_CTX_GPU
        if "max_tokens" in body and "num_predict" not in opts:
            opts["num_predict"] = body["max_tokens"]
        body["options"] = opts

    return body

def inject_thinking(body: dict, nivel: str, modelo: str) -> dict:
    """[V22-T1] Activa razonamiento extendido para modelos compatibles."""
    modelo_lower = modelo.lower()
    body.pop("think", None)

    if modelo_lower in _THINK_MODELS or nivel in {"PROFUNDO", "PRECISO", "PRECISO_OPT"}:
        opts = body.get("options", {})
        if not isinstance(opts, dict):
            opts = {}
        opts["think"] = True
        body["options"] = opts
        log.debug("[THINK] Activado para modelo='%s' nivel='%s'", modelo, nivel)

    return body

def check_tools(body: dict, nivel: str, modelo: str) -> dict:
    """[V22-T2] Serializa tools a texto plano si el modelo no tiene soporte nativo.
    [V22-C2] Retorna siempre dict.
    """
    tools = body.get("tools")
    if not tools:
        return body

    modelo_lower = modelo.lower()

    if any(m in modelo_lower for m in _TOOLS_SUPPORTED):
        log.debug("[TOOLS] Soporte nativo para '%s' -- tools conservadas", modelo)
        return body

    log.debug("[TOOLS] Sin soporte nativo en '%s' -- convirtiendo a texto plano", modelo)

    tools_parts = [
        "\n\n[AVAILABLE TOOLS]\n",
        "To use a tool, reply ONLY with a JSON object:\n",
        ' {"tool": "<tool_name>", "arguments": {}}\n\n',
    ]

    tools_text = "".join(tools_parts)

    for t in tools:
        func = t.get("function", t)
        name = func.get("name", "unknown")
        desc = func.get("description", "")
        params = func.get("parameters", {})
        required = params.get("required", [])
        props = params.get("properties", {})
        tools_text += "* %s: %s\n" % (name, desc)
        for p_name, p_def in props.items():
            req_label = "required" if p_name in required else "optional"
            p_desc = p_def.get("description", "")
            tools_text += "  - %s (%s): %s\n" % (p_name, req_label, p_desc)
    tools_text += "[END TOOLS]\n"

    messages = body.get("messages", [])
    injected = False
    for msg in messages:
        if isinstance(msg, dict) and msg.get("role") == "system":
            content = msg.get("content", "")
            msg["content"] = (content if isinstance(content, str) else "") + tools_text
            injected = True
            break

    if not injected:
        messages.insert(0, {"role": "system", "content": tools_text.strip()})

    body["messages"] = messages
    body.pop("tools", None)
    body.pop("tool_choice", None)

    return body

# ---------------------------------------------------------------------------
# PROXY HTTP -- [V24-P1] Una sola conexion en streaming
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# [V28-FORMAT] CONVERSIÓN FORMATO OLLAMA → OPENAI CHAT COMPLETIONS
# ---------------------------------------------------------------------------
# Ollama /api/chat devuelve: {"model":..., "message":{"role":..., "content":...}, "done":true}
# OpenAI espera: {"id":..., "object":"chat.completion", "choices":[...]}
# OpenClaw está configurado como openai-completions → requiere formato OpenAI.
# Sin esta conversión: reason=format / "incomplete terminal response"

import time as _time

def _ollama_to_openai_json(content: dict, modelo_usado: str) -> dict:
    """[V28-FORMAT] Convierte respuesta Ollama /api/chat → OpenAI Chat Completions."""
    text = ""
    if isinstance(content, dict):
        msg = content.get("message") or {}
        if isinstance(msg, dict):
            text = msg.get("content") or ""
        elif "response" in content:
            text = content.get("response") or ""

    finish = (
        content.get("done_reason")
        or ("stop" if content.get("done") else None)
        or "stop"
    )

    return {
        "id": "chatcmpl-omen-local",
        "object": "chat.completion",
        "created": int(_time.time()),
        "model": modelo_usado,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": text,
                },
                "finish_reason": finish,
            }
        ],
        "usage": {
            "prompt_tokens": content.get("prompt_eval_count", 0),
            "completion_tokens": content.get("eval_count", 0),
            "total_tokens": (
                content.get("prompt_eval_count", 0) + content.get("eval_count", 0)
            ),
        },
    }


async def proxy_request(
    body: dict,
    target_url: str,
    request: Request,
    streaming: bool,
    nivel: str,
    http_client: httpx.AsyncClient,
):
    """Proxy HTTP hacia el backend con fallback automatico.
    [V25-FIX-TOKENS] Valida tokens antes de enviar.
    [V27-ORDER] FIX: sanitize_for_ollama ANTES de validate_and_truncate.
    """
    timeout_s    = RUTAS.get(nivel, {}).get("timeout_s", 60.0)
    modelo_usado = body.get("model", "unknown")
    # [V27-ORDER] sanitize PRIMERO (arrays->string), LUEGO truncar tokens
    body = sanitize_for_ollama(body, nivel, modelo_usado)
    
    # [V25-FIX-TOKENS] Validar y truncar si es necesario
    body = validate_and_truncate_messages(body, nivel, modelo_usado)

    if streaming:
        return await _proxy_streaming(
            body, target_url, request, nivel, timeout_s, modelo_usado, http_client
        )
    return await _proxy_json(
        body, target_url, request, nivel, timeout_s, modelo_usado, http_client
    )

async def _proxy_streaming(
    body: dict,
    target_url: str,
    request: Request,
    nivel: str,
    timeout_s: float,
    modelo_usado: str,
    http_client: httpx.AsyncClient,
):
    """[V24-P1] Proxy streaming con UNA SOLA conexion HTTP.
    [V25-FIX] Mantiene el context manager abierto durante toda la generación."""
    
    resp_headers = {
        "X-Omen-Model-Used": modelo_usado,
        "X-Omen-Nivel": nivel,
    }

    async def _gen():
        """Generador que mantiene la conexión abierta mientras envía chunks."""
        try:
            async with http_client.stream(
                "POST",
                target_url,
                json=body,
                timeout=httpx.Timeout(timeout_s, connect=10.0),
            ) as resp:
                if resp.status_code >= 400:
                    raw = await resp.aread()
                    error_text = raw[:500].decode("utf-8", errors="replace")
                    log.warning(
                        "[PROXY] Backend retorno %s en %s: %s",
                        resp.status_code, nivel, error_text[:120],
                    )
                    err = json.dumps({
                        "error": {
                            "message": "Backend error",
                            "type": "backend_error",
                            "details": error_text,
                        }
                    })
                    yield ("data: " + err + "\n\ndata: [DONE]\n\n").encode()
                    return

                # [V28-FORMAT-STREAM] Convertir NDJSON de Ollama → OpenAI SSE
                # Ollama /api/chat devuelve líneas JSON: {"message":{"content":"..."}, "done":false}
                # OpenClaw espera SSE:  data: {"choices":[{"delta":{"content":"..."}}]}
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue

                    msg = obj.get("message") or {}
                    delta_text = ""
                    if isinstance(msg, dict):
                        delta_text = msg.get("content") or ""

                    if delta_text:
                        sse_obj = {
                            "id": "chatcmpl-omen-local",
                            "object": "chat.completion.chunk",
                            "created": 0,
                            "model": modelo_usado,
                            "choices": [{
                                "index": 0,
                                "delta": {"content": delta_text},
                                "finish_reason": None
                            }]
                        }
                        yield ("data: " + json.dumps(sse_obj, ensure_ascii=False) + "\n\n").encode("utf-8")

                    if obj.get("done"):
                        finish_reason = obj.get("done_reason") or "stop"
                        done_obj = {
                            "id": "chatcmpl-omen-local",
                            "object": "chat.completion.chunk",
                            "created": 0,
                            "model": modelo_usado,
                            "choices": [{
                                "index": 0,
                                "delta": {},
                                "finish_reason": finish_reason
                            }]
                        }
                        yield ("data: " + json.dumps(done_obj, ensure_ascii=False) + "\n\n").encode("utf-8")
                        yield b"data: [DONE]\n\n"
                        log.debug("[V28-FORMAT-STREAM] Stream completado (%s finish=%s)", modelo_usado, finish_reason)
                        return

        except asyncio.CancelledError:
            log.debug("[PROXY] Stream cancelado por el cliente (%s)", nivel)
        except httpx.TimeoutException:
            log.warning(
                "[PROXY] Timeout (%ss) en streaming %s -- intentando fallback",
                timeout_s, nivel,
            )
            # [V27-FB] FIX: intentar fallback en cadena igual que _proxy_json
            fb = TIMEOUT_FALLBACK.get(nivel)
            if fb:
                log.info("[PROXY] Fallback streaming timeout: %s -> %s", nivel, fb)
                async with _metrics_lock:
                    key = "timeout_" + nivel
                    _proxy_metrics["fallbacks"][key] = (
                        _proxy_metrics["fallbacks"].get(key, 0) + 1
                    )
                fb_url     = RUTAS[fb]["url"]
                body_fb    = dict(body)
                body_fb["model"] = RUTAS[fb]["modelo"]
                fb_timeout = RUTAS[fb]["timeout_s"]
                try:
                    async with http_client.stream(
                        "POST",
                        fb_url,
                        json=body_fb,
                        timeout=httpx.Timeout(fb_timeout, connect=10.0),
                    ) as resp_fb:
                        if resp_fb.status_code >= 400:
                            err = json.dumps({
                                "error": {
                                    "message": f"Fallback {fb} error {resp_fb.status_code}",
                                    "type": "fallback_error",
                                }
                            })
                            yield ("data: " + err + "\n\ndata: [DONE]\n\n").encode()
                            return
                        # [V28-FORMAT-STREAM-FB] Formato SSE en fallback streaming
                        async for line in resp_fb.aiter_lines():
                            if not line:
                                continue
                            try:
                                obj = json.loads(line)
                            except Exception:
                                continue
                            msg = obj.get("message") or {}
                            dt = (msg.get("content") or "") if isinstance(msg, dict) else ""
                            if dt:
                                sse = {"id": "chatcmpl-omen-local", "object": "chat.completion.chunk",
                                       "created": 0, "model": modelo_usado,
                                       "choices": [{"index": 0, "delta": {"content": dt}, "finish_reason": None}]}
                                yield ("data: " + json.dumps(sse, ensure_ascii=False) + "\n\n").encode("utf-8")
                            if obj.get("done"):
                                fr = obj.get("done_reason") or "stop"
                                done = {"id": "chatcmpl-omen-local", "object": "chat.completion.chunk",
                                        "created": 0, "model": modelo_usado,
                                        "choices": [{"index": 0, "delta": {}, "finish_reason": fr}]}
                                yield ("data: " + json.dumps(done, ensure_ascii=False) + "\n\n").encode("utf-8")
                                yield b"data: [DONE]\n\n"
                                return
                    return
                except Exception as fb_exc:
                    log.error(
                        "[PROXY] Fallback streaming %s tambien fallo: %s",
                        fb, fb_exc,
                    )
            err = json.dumps(
                {"error": {"message": "Timeout en " + nivel, "type": "timeout"}}
            )
            yield ("data: " + err + "\n\ndata: [DONE]\n\n").encode()
        except Exception as exc:
            log.error("[PROXY] Error en streaming %s: %s", nivel, exc)
            err = json.dumps(
                {"error": {"message": str(exc), "type": "proxy_error"}}
            )
            yield ("data: " + err + "\n\ndata: [DONE]\n\n").encode()

    return StreamingResponse(
        _gen(), media_type="text/event-stream", headers=resp_headers
    )

async def _proxy_json(
    body: dict,
    target_url: str,
    request: Request,
    nivel: str,
    timeout_s: float,
    modelo_usado: str,
    http_client: httpx.AsyncClient,
) -> JSONResponse:
    """Proxy en modo JSON completo con fallback."""
    try:
        resp = await http_client.post(
            target_url, json=body, timeout=httpx.Timeout(timeout_s)
        )
        # [V27-JSON] Proteger contra cuerpo no-JSON (Ollama puede retornar
        # texto plano o HTML en errores HTTP 5xx)
        try:
            content = resp.json()
        except Exception:
            raw_text = resp.text[:500]
            log.error(
                "[PROXY] Respuesta no-JSON de backend %s (HTTP %s): %s",
                nivel, resp.status_code, raw_text,
            )
            return JSONResponse(
                content={
                    "error": {
                        "message": f"Backend retorno respuesta no-JSON (HTTP {resp.status_code})",
                        "type": "backend_error",
                        "details": raw_text,
                    }
                },
                status_code=502,
                headers={"X-Omen-Model-Used": modelo_usado, "X-Omen-Nivel": nivel},
            )
        # [V28-FORMAT] Convertir respuesta Ollama → formato OpenAI Chat Completions
        # OpenClaw usa openai-completions y espera {"choices":[{"message":...}]}
        if resp.status_code < 400:
            openai_content = _ollama_to_openai_json(content, modelo_usado)
            log.debug("[V28-FORMAT] Ollama→OpenAI: finish=%s tokens=%s",
                      openai_content["choices"][0]["finish_reason"],
                      openai_content["usage"]["total_tokens"])
            response = JSONResponse(content=openai_content, status_code=200)
        else:
            response = JSONResponse(content=content, status_code=resp.status_code)
        response.headers["X-Omen-Model-Used"] = modelo_usado
        response.headers["X-Omen-Nivel"] = nivel
        return response
    except httpx.TimeoutException:
        return await _handle_timeout_fallback_json(body, nivel, modelo_usado, http_client)
    except Exception as exc:
        log.error("[PROXY] Error JSON en %s: %s", nivel, exc)
        return JSONResponse(
            content={"error": {"message": str(exc), "type": "proxy_error"}},
            status_code=502,
        )

async def _handle_timeout_fallback(
    body: dict,
    request: Request,
    nivel: str,
    modelo_usado: str,
    http_client: httpx.AsyncClient,
):
    """Maneja timeout con fallback en modo streaming.
    [V25-FIX] Mantiene el context manager abierto durante la generación."""
    fb = TIMEOUT_FALLBACK.get(nivel)
    if fb:
        if await request.is_disconnected():
            log.debug("[PROXY] Cliente desconectado -- cancelando fallback")
            return JSONResponse(
                content={"error": {"message": "Client disconnected"}},
                status_code=499,
            )

        log.info("[PROXY] Fallback timeout: %s -> %s", nivel, fb)
        async with _metrics_lock:
            key = "timeout_" + nivel
            _proxy_metrics["fallbacks"][key] = (
                _proxy_metrics["fallbacks"].get(key, 0) + 1
            )

        fb_url = RUTAS[fb]["url"]
        body_fb = dict(body)
        body_fb["model"] = RUTAS[fb]["modelo"]
        fb_timeout = RUTAS[fb]["timeout_s"]

        async def _gen_fb():
            try:
                async with http_client.stream(
                    "POST",
                    fb_url,
                    json=body_fb,
                    timeout=httpx.Timeout(fb_timeout),
                ) as resp:
                    if resp.status_code >= 400:
                        err = json.dumps(
                            {"error": {"message": "Fallback error %d" % resp.status_code}}
                        )
                        yield ("data: " + err + "\n\ndata: [DONE]\n\n").encode()
                        return
                    # [V28-FORMAT-STREAM-GFB] Formato SSE en _gen_fb timeout handler
                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        try:
                            obj = json.loads(line)
                        except Exception:
                            continue
                        msg = obj.get("message") or {}
                        dt = (msg.get("content") or "") if isinstance(msg, dict) else ""
                        if dt:
                            sse = {"id": "chatcmpl-omen-local", "object": "chat.completion.chunk",
                                   "created": 0, "model": RUTAS[fb]["modelo"],
                                   "choices": [{"index": 0, "delta": {"content": dt}, "finish_reason": None}]}
                            yield ("data: " + json.dumps(sse, ensure_ascii=False) + "\n\n").encode("utf-8")
                        if obj.get("done"):
                            fr = obj.get("done_reason") or "stop"
                            done = {"id": "chatcmpl-omen-local", "object": "chat.completion.chunk",
                                    "created": 0, "model": RUTAS[fb]["modelo"],
                                    "choices": [{"index": 0, "delta": {}, "finish_reason": fr}]}
                            yield ("data: " + json.dumps(done, ensure_ascii=False) + "\n\n").encode("utf-8")
                            yield b"data: [DONE]\n\n"
                            return
            except Exception as exc:
                err = json.dumps(
                    {"error": {"message": str(exc), "type": "fallback_error"}}
                )
                yield ("data: " + err + "\n\ndata: [DONE]\n\n").encode()

        return StreamingResponse(
            _gen_fb(),
            media_type="text/event-stream",
            headers={
                "X-Omen-Model-Used": RUTAS[fb]["modelo"],
                "X-Omen-Nivel": fb,
            },
        )

    return JSONResponse(
        content={
            "error": {
                "message": "Timeout en " + nivel + " sin fallback",
                "type": "timeout",
            }
        },
        status_code=504,
        headers={"X-Omen-Model-Used": modelo_usado, "X-Omen-Nivel": nivel},
    )

async def _handle_timeout_fallback_json(
    body: dict,
    nivel: str,
    modelo_usado: str,
    http_client: httpx.AsyncClient,
) -> JSONResponse:
    """Maneja timeout con fallback en modo JSON."""
    fb = TIMEOUT_FALLBACK.get(nivel)
    if fb:
        async with _metrics_lock:
            key = "timeout_" + nivel
            _proxy_metrics["fallbacks"][key] = (
                _proxy_metrics["fallbacks"].get(key, 0) + 1
            )

        fb_url = RUTAS[fb]["url"]
        body_fb = dict(body)
        body_fb["model"] = RUTAS[fb]["modelo"]
        try:
            resp2 = await http_client.post(
                fb_url,
                json=body_fb,
                timeout=httpx.Timeout(RUTAS[fb]["timeout_s"]),
            )
            response = JSONResponse(content=resp2.json(), status_code=resp2.status_code)
            response.headers["X-Omen-Model-Used"] = RUTAS[fb]["modelo"]
            response.headers["X-Omen-Nivel"] = fb
            return response
        except Exception as exc:
            log.error("[PROXY] Fallback JSON tambien fallo: %s", exc)

    return JSONResponse(
        content={"error": {"message": "Timeout en " + nivel, "type": "timeout"}},
        status_code=504,
    )

# ---------------------------------------------------------------------------
# PUBLIC API
# ---------------------------------------------------------------------------

def get_estado() -> dict:
    """Retorna el estado actual de VRAM."""
    return dict(_estado)

def get_proxy_metrics() -> dict:
    """Retorna metricas del proxy."""
    return dict(_proxy_metrics)
