#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║ omen_router_modules/proxy.py — Proxy HTTP y gestión de VRAM               ║
║ OMEN AI Router V14 (build V24)                                              ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ [V21-P1] Estado transitorio "SWITCHING" durante conmutación VRAM (H-01).  ║
║ [V21-P2] Error HTTP real en streaming pre-chunk (H-09).                   ║
║ [V21-P3] Reutilización de httpx.AsyncClient (H-22/H-38).                  ║
║ [V21-P4] Thinking por modelo, no solo por nivel (H-12).                   ║
║                                                                             ║
║ CORRECCIONES V22:                                                           ║
║ [V22-T1] inject_thinking: activado también para phi4-reasoning:*.          ║
║ [V22-T2] check_tools: convierte tools a texto plano para sin soporte.      ║
║ [V22-C1] inject_opciones_extra: num_ctx=16384 para niveles GPU.            ║
║ [V22-C2] check_tools: corregido bug — devolvía None (ahora dict).          ║
║                                                                             ║
║ CORRECCIONES V23:                                                           ║
║ [V23-S1] sanitize_for_ollama(): elimina campos OpenAI incompatibles        ║
║           (stream_options, max_completion_tokens, logprobs, etc.).         ║
║ [V23-S2] sanitize_for_ollama() se llama PRIMERO en la cadena.              ║
║ [V23-S3] max_completion_tokens → options.num_predict antes de eliminar.   ║
║                                                                             ║
║ CORRECCIONES V24:                                                           ║
║ [V24-P1] _proxy_streaming: eliminada doble llamada HTTP. Antes se hacía    ║
║           un http_client.post() completo solo para leer el status_code,    ║
║           lo que obligaba a Ollama a generar la respuesta ENTERA dos veces ║
║           para cada request en streaming (crítico en MASIVO/qwen2.5:32b). ║
║           Ahora se usa http_client.stream() una sola vez: el status HTTP   ║
║           llega con las cabeceras, antes de consumir el body, por lo que   ║
║           se puede detectar el error 400/5xx sin coste de generación.      ║
║ [V24-D1] Log de campos del body restaurado como log.debug() (nivel DEBUG,  ║
║           silencioso en producción pero visible con --log-level debug).    ║
║           En V22 se eliminó por completo; en V24 se recupera como debug    ║
║           para facilitar futuros diagnósticos de campos inesperados        ║
║           enviados por OpenClaw u otros clientes OpenAI-compatibles.       ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import asyncio
import json
import logging
import time
from typing import Optional

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

# ─────────────────────────────────────────────────────────────────────────────
# [V22] CAPACIDADES POR MODELO
# ─────────────────────────────────────────────────────────────────────────────

# Modelos con soporte nativo de function-calling en Ollama
_TOOLS_SUPPORTED = {
    "qwen2.5:32b",
    "qwen2.5:7b",
    "qwen2.5-coder:7b",
    "llama3.1:8b",
    "llama3.2:3b",
    "mistral:7b",
    "mistral-nemo",
}

# Modelos que admiten "think" en options{} (razonamiento extendido)
_THINK_MODELS = {
    "deepseek-r1:14b",
    "phi4-reasoning:plus",
    "phi4-reasoning:14b-q4_k_m",
}

# Niveles que apuntan a la GPU y necesitan contexto extendido
_GPU_NIVELES = {"PROFUNDO", "PRECISO", "PRECISO_OPT", "MASIVO", "AGIL"}

# Contexto mínimo garantizado para niveles GPU (en tokens)
_MIN_CTX_GPU = 16384

# ─────────────────────────────────────────────────────────────────────────────
# [V23-S1] CAMPOS OPENAI INCOMPATIBLES CON OLLAMA /api/chat
# ─────────────────────────────────────────────────────────────────────────────
_OLLAMA_UNSUPPORTED = {
    "stream_options",          # include_usage — solo OpenAI
    "max_completion_tokens",   # alias OpenAI; Ollama usa options.num_predict
    "logprobs",
    "top_logprobs",
    "service_tier",
    "store",
}


def sanitize_for_ollama(body: dict, nivel: str, model: str) -> dict:
    """[V23-S1] Elimina campos OpenAI que Ollama /api/chat no acepta.
    Actúa sobre TODAS las peticiones independientemente del nivel o modelo.
    [V23-S3] Convierte max_completion_tokens → options.num_predict para
    preservar el límite de tokens antes de eliminar el campo fuente.
    [V24-D1] Loguea los campos eliminados a nivel DEBUG para diagnóstico.
    """
    removed = []

    # max_completion_tokens → options.num_predict (preservar valor)
    if "max_completion_tokens" in body:
        mct = body.pop("max_completion_tokens")
        removed.append("max_completion_tokens")
        if "max_tokens" not in body:
            opts = body.setdefault("options", {})
            if not isinstance(opts, dict):
                opts = {}
                body["options"] = opts
            opts.setdefault("num_predict", mct)

    # Eliminar resto de campos incompatibles
    for campo in (_OLLAMA_UNSUPPORTED - {"max_completion_tokens"}):
        if campo in body:
            body.pop(campo)
            removed.append(campo)

    if removed:
        log.debug(f"[V23-S1] sanitize_for_ollama [{nivel}/{model}] eliminados: {removed}")

    # [V24-D1] Log DEBUG de todos los campos presentes en el body (diagnóstico)
    campos = list(body.keys())
    non_msg = {k: v for k, v in body.items() if k != "messages"}
    log.debug(
        f"[V24-D1] body_campos={campos} | non_msg={json.dumps(non_msg, ensure_ascii=False, default=str)[:400]}"
    )

    return body


# ─────────────────────────────────────────────────────────────────────────────
# ESTADO DE VRAM — [V21-P1] Con estado transitorio
# ─────────────────────────────────────────────────────────────────────────────
_vram_lock = asyncio.Lock()
_vram_switch_event = asyncio.Event()
_vram_switch_event.set()  # Inicialmente no hay switch en curso

_estado: dict = {
    "ruta_activa": "CHAT",
    "tabbyapi_modelo": "llama-3.1-8b-exl2",
    "switching": False,  # [V21-P1] Estado transitorio
}

# Métricas del proxy
_proxy_metrics = {
    "cambios_vram": 0,
    "fallbacks": {},
}

_metrics_lock = asyncio.Lock()


# ─────────────────────────────────────────────────────────────────────────────
# CONMUTACIÓN DE VRAM — [V21-P1] Con estado transitorio
# ─────────────────────────────────────────────────────────────────────────────
async def conmutar_vram(nivel: str, http_client: httpx.AsyncClient) -> str:
    """Conmuta el modelo en VRAM si es necesario para el nivel solicitado.
    [V21-P1] Estado transitorio: peticiones concurrentes esperan al switch.
    Retorna la URL del backend a usar.
    """
    ruta = RUTAS[nivel]

    if ruta["backend"] != "tabbyapi":
        return ruta["url"]

    modelo_requerido = ruta["modelo"]

    if _estado["tabbyapi_modelo"] == modelo_requerido and not _estado["switching"]:
        return ruta["url"]

    if _estado["switching"]:
        log.debug(f"[VRAM] Esperando switch en curso para {nivel}…")
        try:
            await asyncio.wait_for(_vram_switch_event.wait(), timeout=60.0)
        except asyncio.TimeoutError:
            log.error("[VRAM] Timeout esperando switch — usando URL actual")
            return ruta["url"]

    if _estado["tabbyapi_modelo"] == modelo_requerido:
        return ruta["url"]

    async with _vram_lock:
        if _estado["tabbyapi_modelo"] == modelo_requerido:
            return ruta["url"]

        _estado["switching"] = True
        _vram_switch_event.clear()

        try:
            log.info(f"[VRAM] Conmutando: {_estado['tabbyapi_modelo']} → {modelo_requerido}")

            try:
                await http_client.post(TABBYAPI_MODEL_UNLOAD, timeout=30.0)
            except Exception as e:
                log.warning(f"[VRAM] Error descargando modelo: {e}")

            try:
                resp = await http_client.post(
                    TABBYAPI_MODEL_LOAD,
                    json={"model_name": modelo_requerido},
                    timeout=120.0,
                )
                if resp.status_code == 200:
                    async with _vram_lock:
                        _estado["tabbyapi_modelo"] = modelo_requerido
                        _estado["ruta_activa"] = nivel
                    async with _metrics_lock:
                        _proxy_metrics["cambios_vram"] += 1
                    log.info(f"[VRAM] ✔ Modelo cargado: {modelo_requerido}")
                else:
                    log.error(f"[VRAM] Error cargando {modelo_requerido}: HTTP {resp.status_code}")
            except httpx.TimeoutException:
                log.error(f"[VRAM] Timeout cargando {modelo_requerido}")
            except Exception as e:
                log.error(f"[VRAM] Error inesperado: {e}")

        finally:
            async with _vram_lock:
                _estado["switching"] = False
            _vram_switch_event.set()

    return ruta["url"]


# ─────────────────────────────────────────────────────────────────────────────
# INYECCIONES EN EL BODY
# ─────────────────────────────────────────────────────────────────────────────

def inject_opciones_extra(body: dict, nivel: str, modelo: str = "") -> dict:
    """[V21] Inyecta opciones específicas del nivel.
    [V22-C1] Garantiza num_ctx >= 16384 para niveles GPU.
    """
    extras = RUTAS[nivel].get("opciones_extra") or {}
    for k, v in extras.items():
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
    """[V21-P4] Activa modo de razonamiento extendido.
    [V22-T1] Ampliado para cubrir phi4-reasoning:*.
    """
    modelo_lower = modelo.lower()
    body.pop("think", None)

    if modelo_lower in _THINK_MODELS or nivel in {"PROFUNDO", "PRECISO", "PRECISO_OPT"}:
        opts = body.get("options", {})
        if not isinstance(opts, dict):
            opts = {}
        opts["think"] = True
        body["options"] = opts
        log.debug(f"[THINK] Activado para modelo='{modelo}' nivel='{nivel}'")

    return body


def check_tools(body: dict, nivel: str, modelo: str) -> dict:
    """[V22-T2] Gestión de tools según capacidad del modelo destino.
    Modelos sin soporte nativo: serializa tools como texto en system prompt.
    [V22-C2] Retorna body modificado (antes devolvía None).
    """
    tools = body.get("tools")

    if not tools:
        return body

    modelo_lower = modelo.lower()

    if any(m in modelo_lower for m in _TOOLS_SUPPORTED):
        log.debug(f"[TOOLS] Soporte nativo para '{modelo}' — tools conservadas")
        return body

    log.debug(f"[TOOLS] Sin soporte nativo en '{modelo}' — convirtiendo a texto plano")

    tools_text = (
        "

[AVAILABLE TOOLS]
"
        "To use a tool, reply ONLY with a JSON object: "
        "{"tool": "<name>", "arguments": {}}

"
    )

    for t in tools:
        func = t.get("function", t)
        name = func.get("name", "unknown")
        desc = func.get("description", "")
        params = func.get("parameters", {})
        required = params.get("required", [])
        props = params.get("properties", {})
        tools_text += f"• {name}: {desc}
"
        for p_name, p_def in props.items():
            req_label = "required" if p_name in required else "optional"
            p_desc = p_def.get("description", "")
            tools_text += f"  - {p_name} ({req_label}): {p_desc}
"
    tools_text += "[END TOOLS]
"

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


# ─────────────────────────────────────────────────────────────────────────────
# PROXY HTTP
# [V24-P1] _proxy_streaming: una sola conexión HTTP (elimina doble generación)
# ─────────────────────────────────────────────────────────────────────────────

async def proxy_request(
    body: dict,
    target_url: str,
    request: Request,
    streaming: bool,
    nivel: str,
    http_client: httpx.AsyncClient,
) -> "StreamingResponse | JSONResponse":
    """Proxy HTTP hacia el backend seleccionado con fallback automático."""
    timeout_s = RUTAS.get(nivel, {}).get("timeout_s", 60.0)
    modelo_usado = body.get("model", "unknown")

    if streaming:
        return await _proxy_streaming(body, target_url, request, nivel, timeout_s, modelo_usado, http_client)
    else:
        return await _proxy_json(body, target_url, request, nivel, timeout_s, modelo_usado, http_client)


async def _proxy_streaming(
    body: dict,
    target_url: str,
    request: Request,
    nivel: str,
    timeout_s: float,
    modelo_usado: str,
    http_client: httpx.AsyncClient,
) -> "StreamingResponse | JSONResponse":
    """[V24-P1] Proxy streaming con UNA SOLA conexión HTTP.
    El status code llega con las cabeceras HTTP, antes de consumir el body,
    por lo que se puede detectar error 400/5xx sin coste de generación.
    Elimina la doble llamada del V21/V22/V23 que obligaba a Ollama a generar
    la respuesta completa dos veces (crítico en MASIVO con qwen2.5:32b).
    """
    try:
        async with http_client.stream(
            "POST",
            target_url,
            json=body,
            timeout=httpx.Timeout(timeout_s, connect=10.0),
        ) as resp:
            # El status HTTP llega con las cabeceras — sin coste de generación
            if resp.status_code >= 400:
                error_text = (await resp.aread())[:500].decode("utf-8", errors="replace")
                log.warning(f"[PROXY] Backend retornó {resp.status_code} en {nivel}: {error_text[:120]}")
                return JSONResponse(
                    content={"error": {"message": "Backend error", "type": "backend_error", "details": error_text}},
                    status_code=resp.status_code,
                    headers={"X-Omen-Model-Used": modelo_usado, "X-Omen-Nivel": nivel},
                )

            # Stream directo al cliente — sin buffer intermedio
            headers = {"X-Omen-Model-Used": modelo_usado, "X-Omen-Nivel": nivel}

            async def _gen():
                try:
                    async for chunk in resp.aiter_bytes():
                        yield chunk
                except asyncio.CancelledError:
                    log.debug(f"[PROXY] Stream cancelado por el cliente ({nivel})")
                except httpx.TimeoutException:
                    log.warning(f"[PROXY] Timeout ({timeout_s}s) en streaming {nivel}")
                    err = json.dumps({"error": {"message": f"Timeout en {nivel}", "type": "timeout"}})
                    yield f"data: {err}

data: [DONE]

".encode()
                except Exception as e:
                    log.error(f"[PROXY] Error en streaming {nivel}: {e}")
                    err = json.dumps({"error": {"message": str(e), "type": "proxy_error"}})
                    yield f"data: {err}

data: [DONE]

".encode()

            return StreamingResponse(_gen(), media_type="text/event-stream", headers=headers)

    except httpx.TimeoutException:
        return await _handle_timeout_fallback(body, request, nivel, modelo_usado, http_client)
    except Exception as e:
        log.error(f"[PROXY] Error conectando a {nivel}: {e}")
        return JSONResponse(
            content={"error": {"message": str(e), "type": "proxy_error"}},
            status_code=502,
            headers={"X-Omen-Model-Used": modelo_usado, "X-Omen-Nivel": nivel},
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
        resp = await http_client.post(target_url, json=body, timeout=httpx.Timeout(timeout_s))
        response = JSONResponse(content=resp.json(), status_code=resp.status_code)
        response.headers["X-Omen-Model-Used"] = modelo_usado
        response.headers["X-Omen-Nivel"] = nivel
        return response
    except httpx.TimeoutException:
        return await _handle_timeout_fallback_json(body, nivel, modelo_usado, http_client)
    except Exception as e:
        log.error(f"[PROXY] Error JSON en {nivel}: {e}")
        return JSONResponse(
            content={"error": {"message": str(e), "type": "proxy_error"}},
            status_code=502,
        )


async def _handle_timeout_fallback(
    body: dict,
    request: Request,
    nivel: str,
    modelo_usado: str,
    http_client: httpx.AsyncClient,
) -> "StreamingResponse | JSONResponse":
    """Maneja timeout con fallback en modo streaming."""
    fb = TIMEOUT_FALLBACK.get(nivel)
    if fb:
        if await request.is_disconnected():
            log.debug("[PROXY] Cliente desconectado — cancelando fallback")
            return JSONResponse(content={"error": {"message": "Client disconnected"}}, status_code=499)

        log.info(f"[PROXY] Fallback timeout: {nivel} → {fb}")
        async with _metrics_lock:
            _proxy_metrics["fallbacks"][f"timeout_{nivel}"] = (
                _proxy_metrics["fallbacks"].get(f"timeout_{nivel}", 0) + 1
            )

        fb_url = RUTAS[fb]["url"]
        body_fb = {**body, "model": RUTAS[fb]["modelo"]}
        fb_timeout = RUTAS[fb]["timeout_s"]

        async def _gen_fb():
            try:
                async with http_client.stream("POST", fb_url, json=body_fb, timeout=httpx.Timeout(fb_timeout)) as resp:
                    if resp.status_code >= 400:
                        err = json.dumps({"error": {"message": f"Fallback error {resp.status_code}"}})
                        yield f"data: {err}

data: [DONE]

".encode()
                        return
                    async for chunk in resp.aiter_bytes():
                        yield chunk
            except Exception as e:
                err = json.dumps({"error": {"message": str(e), "type": "fallback_error"}})
                yield f"data: {err}

data: [DONE]

".encode()

        headers = {"X-Omen-Model-Used": RUTAS[fb]["modelo"], "X-Omen-Nivel": fb}
        return StreamingResponse(_gen_fb(), media_type="text/event-stream", headers=headers)

    return JSONResponse(
        content={"error": {"message": f"Timeout en {nivel} sin fallback", "type": "timeout"}},
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
            _proxy_metrics["fallbacks"][f"timeout_{nivel}"] = (
                _proxy_metrics["fallbacks"].get(f"timeout_{nivel}", 0) + 1
            )
        fb_url = RUTAS[fb]["url"]
        body_fb = {**body, "model": RUTAS[fb]["modelo"]}
        try:
            resp2 = await http_client.post(fb_url, json=body_fb, timeout=httpx.Timeout(RUTAS[fb]["timeout_s"]))
            response = JSONResponse(content=resp2.json(), status_code=resp2.status_code)
            response.headers["X-Omen-Model-Used"] = RUTAS[fb]["modelo"]
            response.headers["X-Omen-Nivel"] = fb
            return response
        except Exception as e:
            log.error(f"[PROXY] Fallback JSON también falló: {e}")

    return JSONResponse(
        content={"error": {"message": f"Timeout en {nivel}", "type": "timeout"}},
        status_code=504,
    )


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────
def get_estado() -> dict:
    """Retorna el estado actual de VRAM (copia defensiva)."""
    return dict(_estado)


def get_proxy_metrics() -> dict:
    """Retorna métricas del proxy."""
    return dict(_proxy_metrics)
