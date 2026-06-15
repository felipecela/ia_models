"""
╔══════════════════════════════════════════════════════════════════════════════╗
║ omen_router_modules/proxy.py — Proxy HTTP y gestión de VRAM                 ║
║ OMEN AI Router V14 (build V21)                                              ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ [V21-P1] Estado transitorio "SWITCHING" durante conmutación VRAM (H-01).    ║
║ [V21-P2] Error HTTP real en streaming pre-chunk (H-09).                     ║
║ [V21-P3] Reutilización de httpx.AsyncClient (H-22/H-38).                   ║
║ [V21-P4] Thinking por modelo, no solo por nivel (H-12).                     ║
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
    """
    Conmuta el modelo en VRAM si es necesario para el nivel solicitado.
    [V21-P1] Implementa estado transitorio: las peticiones concurrentes
    esperan a que la conmutación finalice en vez de ver estado inconsistente.
    Retorna la URL del backend a usar.
    """
    ruta = RUTAS[nivel]

    # Si no es TabbyAPI, no necesita conmutación
    if ruta["backend"] != "tabbyapi":
        return ruta["url"]

    modelo_requerido = ruta["modelo"]

    # Fast path: ya está cargado y no hay switch en curso
    if _estado["tabbyapi_modelo"] == modelo_requerido and not _estado["switching"]:
        return ruta["url"]

    # Esperar si hay un switch en curso (máx 60s)
    if _estado["switching"]:
        log.debug(f"[VRAM] Esperando switch en curso para {nivel}…")
        try:
            await asyncio.wait_for(_vram_switch_event.wait(), timeout=60.0)
        except asyncio.TimeoutError:
            log.error("[VRAM] Timeout esperando switch — usando URL actual")
            return ruta["url"]

        # Después de esperar, verificar si ya está el modelo correcto
        if _estado["tabbyapi_modelo"] == modelo_requerido:
            return ruta["url"]

    # Adquirir lock para realizar el switch
    async with _vram_lock:
        # Double-check después de adquirir lock
        if _estado["tabbyapi_modelo"] == modelo_requerido:
            return ruta["url"]

        # [V21-P1] Marcar estado transitorio
        _estado["switching"] = True
        _vram_switch_event.clear()

    try:
        log.info(f"[VRAM] Conmutando: {_estado['tabbyapi_modelo']} → {modelo_requerido}")

        # Descargar modelo actual
        try:
            await http_client.post(TABBYAPI_MODEL_UNLOAD, timeout=30.0)
        except Exception as e:
            log.warning(f"[VRAM] Error descargando modelo: {e}")

        # Cargar nuevo modelo
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
        # [V21-P1] Limpiar estado transitorio
        async with _vram_lock:
            _estado["switching"] = False
        _vram_switch_event.set()

    return ruta["url"]


# ─────────────────────────────────────────────────────────────────────────────
# INYECCIONES EN EL BODY
# ─────────────────────────────────────────────────────────────────────────────
def inject_opciones_extra(body: dict, nivel: str) -> dict:
    """Inyecta opciones específicas del nivel (temperature, top_p, etc.)."""
    extras = RUTAS[nivel].get("opciones_extra") or {}
    for k, v in extras.items():
        body.setdefault(k, v)
    return body


def inject_thinking(body: dict, nivel: str, modelo: str) -> dict:
    """
    [V21-P4] Activa el modo <think> de DeepSeek-R1.
    Ahora verifica el MODELO destino, no solo el nivel.
    """
    if "deepseek-r1" in modelo.lower():
        # Activar thinking para niveles que lo requieren
        if nivel in {"PROFUNDO", "MASIVO"}:
            body.setdefault("options", {})
            body["options"]["think"] = True
    return body


def check_tools(body: dict, nivel: str, modelo: str) -> None:
    """Elimina 'tools' si el modelo/nivel no lo soporta."""
    if "tools" in body and nivel in {"PROFUNDO", "PRECISO", "PRECISO_OPT", "MASIVO"}:
        log.debug(f"[TOOLS] Eliminando 'tools' para nivel {nivel}")
        body.pop("tools", None)
        body.pop("tool_choice", None)


# ─────────────────────────────────────────────────────────────────────────────
# PROXY HTTP — [V21-P2] Con manejo mejorado de errores en streaming
# ─────────────────────────────────────────────────────────────────────────────
async def proxy_request(
    body: dict,
    target_url: str,
    request: Request,
    streaming: bool,
    nivel: str,
    http_client: httpx.AsyncClient,
) -> StreamingResponse | JSONResponse:
    """
    Proxy HTTP hacia el backend seleccionado con fallback automático.
    [V21-P2] Para errores pre-chunk, retorna JSONResponse con status real.
    """
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
) -> StreamingResponse | JSONResponse:
    """Proxy en modo streaming con fallback."""

    # [V21-P2] Intentar conectar primero para detectar errores pre-stream
    try:
        # Usar un cliente con timeout para la conexión inicial
        resp_check = await http_client.post(
            target_url,
            json={**body, "stream": True},
            timeout=httpx.Timeout(timeout_s, connect=10.0),
        )
        # Si hay error HTTP, retornar directamente sin streaming
        if resp_check.status_code >= 400:
            error_text = resp_check.text[:500]
            log.warning(f"[PROXY] Backend retornó {resp_check.status_code} en {nivel}")
            return JSONResponse(
                content={"error": {"message": f"Backend error", "type": "backend_error", "details": error_text}},
                status_code=resp_check.status_code,
                headers={"X-Omen-Model-Used": modelo_usado, "X-Omen-Nivel": nivel},
            )
    except httpx.TimeoutException:
        # Manejar timeout con fallback
        return await _handle_timeout_fallback(body, request, nivel, modelo_usado, http_client)
    except Exception as e:
        log.error(f"[PROXY] Error conectando a {nivel}: {e}")
        return JSONResponse(
            content={"error": {"message": str(e), "type": "proxy_error"}},
            status_code=502,
            headers={"X-Omen-Model-Used": modelo_usado, "X-Omen-Nivel": nivel},
        )

    # Si la conexión fue exitosa, hacer streaming real
    async def _gen():
        try:
            async with http_client.stream("POST", target_url, json=body, timeout=httpx.Timeout(timeout_s)) as resp:
                if resp.status_code >= 400:
                    error_body = await resp.aread()
                    err = json.dumps({"error": {"message": f"Backend error {resp.status_code}", "type": "backend_error"}})
                    yield f"data: {err}\n\ndata: [DONE]\n\n".encode()
                    return
                async for chunk in resp.aiter_bytes():
                    yield chunk
        except asyncio.CancelledError:
            log.debug(f"[PROXY] Stream cancelado por el cliente ({nivel})")
        except httpx.TimeoutException:
            log.warning(f"[PROXY] Timeout ({timeout_s}s) en streaming {nivel}")
            err = json.dumps({"error": {"message": f"Timeout en {nivel}", "type": "timeout"}})
            yield f"data: {err}\n\ndata: [DONE]\n\n".encode()
        except Exception as e:
            log.error(f"[PROXY] Error en streaming {nivel}: {e}")
            err = json.dumps({"error": {"message": str(e), "type": "proxy_error"}})
            yield f"data: {err}\n\ndata: [DONE]\n\n".encode()

    headers = {"X-Omen-Model-Used": modelo_usado, "X-Omen-Nivel": nivel}
    return StreamingResponse(_gen(), media_type="text/event-stream", headers=headers)


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
) -> StreamingResponse | JSONResponse:
    """Maneja timeout con fallback en modo streaming."""
    fb = TIMEOUT_FALLBACK.get(nivel)
    if fb:
        if await request.is_disconnected():
            log.debug("[PROXY] Cliente desconectado — cancelando fallback")
            return JSONResponse(content={"error": {"message": "Client disconnected"}}, status_code=499)

        log.info(f"[PROXY] Fallback timeout: {nivel} → {fb}")
        async with _metrics_lock:
            _proxy_metrics["fallbacks"][f"timeout_{nivel}"] = _proxy_metrics["fallbacks"].get(f"timeout_{nivel}", 0) + 1

        fb_url = RUTAS[fb]["url"]
        body_fb = {**body, "model": RUTAS[fb]["modelo"]}
        fb_timeout = RUTAS[fb]["timeout_s"]

        async def _gen_fb():
            try:
                async with http_client.stream("POST", fb_url, json=body_fb, timeout=httpx.Timeout(fb_timeout)) as resp:
                    if resp.status_code >= 400:
                        err = json.dumps({"error": {"message": f"Fallback error {resp.status_code}"}})
                        yield f"data: {err}\n\ndata: [DONE]\n\n".encode()
                        return
                    async for chunk in resp.aiter_bytes():
                        yield chunk
            except Exception as e:
                err = json.dumps({"error": {"message": str(e), "type": "fallback_error"}})
                yield f"data: {err}\n\ndata: [DONE]\n\n".encode()

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
            _proxy_metrics["fallbacks"][f"timeout_{nivel}"] = _proxy_metrics["fallbacks"].get(f"timeout_{nivel}", 0) + 1

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
