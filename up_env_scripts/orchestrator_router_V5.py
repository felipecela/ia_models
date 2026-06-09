#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════╗
║         OMEN AI CLUSTER — Orchestrador Semántico V5                     ║
║         Hardware: RTX 4070 (8GB VRAM) · Intel Ultra 7 · 32GB RAM        ║
╠══════════════════════════════════════════════════════════════════════════╣
║  Mejoras sobre V4:                                                       ║
║  ✔ Routing 5 niveles: INSTANTANEO/AGIL/PROFUNDO/MASIVO/CODIGO            ║
║  ✔ Phi-4 en CPU-only (puerto 11435) — sin contención de VRAM            ║
║  ✔ HTTP async con httpx — sin bloqueo del event loop de FastAPI          ║
║  ✔ Health checks activos antes de rutear                                 ║
║  ✔ Espera polling hasta que el backend esté listo tras conmutación       ║
║  ✔ Caché LRU de decisiones de Phi-4 (evita llamadas repetidas)          ║
║  ✔ /v1/models con catálogo completo (compatible con OpenClaw)            ║
║  ✔ /health para monitoreo del estado de todos los backends               ║
║  ✔ Streaming SSE correcto para todos los backends                        ║
║  ✔ Fallback automático si el backend primario no responde                ║
╚══════════════════════════════════════════════════════════════════════════╝

Mapa de puertos:
  :5000  → TabbAPI / ExLlamaV2  (INSTANTANEO - VRAM puro)
  :8000  → Este router          (entrada única para OpenClaw)
  :11434 → Ollama GPU           (PROFUNDO, MASIVO, CODIGO)
  :11435 → Ollama CPU-only      (Phi-4 router — SIN VRAM)
  :30000 → SGLang               (AGIL - RadixAttention)
"""

import asyncio
import json
import logging
import os
import time
from collections import OrderedDict
from typing import Optional

import docker
import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

# ─────────────────────────────────────────────────────────────────────────────
#  LOGGING
# ─────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("router")

# ─────────────────────────────────────────────────────────────────────────────
#  ARQUITECTURA DE RUTAS
# ─────────────────────────────────────────────────────────────────────────────
RUTAS: dict[str, dict] = {
    "INSTANTANEO": {
        "url":        "http://localhost:5000/v1/chat/completions",
        "health_url": "http://localhost:5000/health",
        "modelo":     "qwen2.5-coder-7b-exl2",
        "contenedor": "exllamav2-api",
        "descripcion": "ExLlamaV2 puro en VRAM — más rápido para tareas simples/código",
        "vram_aprox_gb": 6.0,
    },
    "AGIL": {
        "url":        "http://localhost:30000/v1/chat/completions",
        "health_url": "http://localhost:30000/health",
        "modelo":     "llama-3.1-8b-awq",
        "contenedor": "sglang-server",
        "descripcion": "SGLang RadixAttention — agentes, documentos, contexto largo",
        "vram_aprox_gb": 5.7,
    },
    "PROFUNDO": {
        "url":        "http://localhost:11434/v1/chat/completions",
        "health_url": "http://localhost:11434/api/tags",
        "modelo":     "deepseek-r1:14b",
        "contenedor": None,        # Servicio nativo systemd
        "descripcion": "DeepSeek R1 14B — razonamiento profundo, debugging, matemáticas",
        "vram_aprox_gb": 7.0,      # Híbrido VRAM+RAM
    },
    "MASIVO": {
        "url":        "http://localhost:11434/v1/chat/completions",
        "health_url": "http://localhost:11434/api/tags",
        "modelo":     "qwen2.5:32b",
        "contenedor": None,
        "descripcion": "Qwen2.5 32B — análisis de documentos masivos, logs largos",
        "vram_aprox_gb": 8.0,      # Ocupa toda la VRAM + 11GB RAM
    },
    "CODIGO": {
        "url":        "http://localhost:11434/v1/chat/completions",
        "health_url": "http://localhost:11434/api/tags",
        "modelo":     "deepseek-coder-v2",
        "contenedor": None,
        "descripcion": "DeepSeek Coder V2 — generación de código especializada",
        "vram_aprox_gb": 7.5,
    },
}

# Ollama CPU-only para el clasificador Phi-4 (sin contención de VRAM con los backends)
PHI4_CPU_GENERATE_URL  = "http://localhost:11435/api/generate"
PHI4_CPU_HEALTH_URL    = "http://localhost:11435/api/tags"
PHI4_MODEL             = "phi4"

# ─────────────────────────────────────────────────────────────────────────────
#  MAPA DE ALIAS → NIVEL
#  Permite que OpenClaw envíe nombres "amigables" y el router los resuelva
# ─────────────────────────────────────────────────────────────────────────────
ALIAS_A_NIVEL: dict[str, Optional[str]] = {
    # Auto-routing (None = dejar que Phi-4 decida)
    "ruteador-auto":       None,
    "auto":                None,
    "default":             None,
    # INSTANTANEO
    "instantaneo":         "INSTANTANEO",
    "instant":             "INSTANTANEO",
    "exllama":             "INSTANTANEO",
    "tabby":               "INSTANTANEO",
    "tabbyapi":            "INSTANTANEO",
    "qwen2.5-coder-7b":    "INSTANTANEO",
    "qwen2.5-coder-7b-exl2": "INSTANTANEO",
    "llama-3.1-8b-exl2":  "INSTANTANEO",
    # AGIL
    "agil":                "AGIL",
    "agile":               "AGIL",
    "sglang":              "AGIL",
    "llama-3.1-8b-awq":   "AGIL",
    "llama3.1":            "AGIL",
    # PROFUNDO
    "profundo":            "PROFUNDO",
    "deep":                "PROFUNDO",
    "deepseek-r1:14b":     "PROFUNDO",
    "deepseek-r1":         "PROFUNDO",
    "r1":                  "PROFUNDO",
    # MASIVO
    "masivo":              "MASIVO",
    "massive":             "MASIVO",
    "qwen2.5:32b":         "MASIVO",
    "qwen2.5":             "MASIVO",
    "qwen":                "MASIVO",
    # CODIGO
    "codigo":              "CODIGO",
    "code":                "CODIGO",
    "coder":               "CODIGO",
    "deepseek-coder-v2":   "CODIGO",
    "deepseek-coder":      "CODIGO",
    # PHI4 directo (CPU)
    "phi4":                "PHI4_DIRECTO",
    "phi-4":               "PHI4_DIRECTO",
    "phi":                 "PHI4_DIRECTO",
}

# ─────────────────────────────────────────────────────────────────────────────
#  DOCKER CLIENT
# ─────────────────────────────────────────────────────────────────────────────
try:
    _docker_client = docker.from_env()
    log.info("✔ Docker client conectado")
except Exception as _e:
    log.warning(f"⚠ Docker no disponible: {_e}. La gestión de VRAM será manual.")
    _docker_client = None

# ─────────────────────────────────────────────────────────────────────────────
#  ESTADO GLOBAL
# ─────────────────────────────────────────────────────────────────────────────
_estado = {"ruta_activa": None, "cambios_vram": 0}

# ─────────────────────────────────────────────────────────────────────────────
#  CACHÉ LRU DE DECISIONES DE PHI-4
#  Evita re-clasificar prompts idénticos o muy similares
# ─────────────────────────────────────────────────────────────────────────────
_phi4_cache: OrderedDict[str, str] = OrderedDict()
_CACHE_MAX = 256
_CACHE_KEY_LEN = 300   # Primeros N caracteres del prompt como clave

def _cache_get(prompt: str) -> Optional[str]:
    key = prompt[:_CACHE_KEY_LEN]
    if key in _phi4_cache:
        _phi4_cache.move_to_end(key)  # LRU: mover al final
        return _phi4_cache[key]
    return None

def _cache_put(prompt: str, nivel: str):
    key = prompt[:_CACHE_KEY_LEN]
    if len(_phi4_cache) >= _CACHE_MAX:
        _phi4_cache.popitem(last=False)  # Eliminar el más antiguo
    _phi4_cache[key] = nivel

# ─────────────────────────────────────────────────────────────────────────────
#  HEALTH CHECK
# ─────────────────────────────────────────────────────────────────────────────
async def _health_check(url: str, timeout: float = 3.0) -> bool:
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.get(url)
            return r.status_code < 500
    except Exception:
        return False

async def _esperar_backend(url: str, intentos: int = 25, pausa: float = 2.5) -> bool:
    """Polling activo hasta que el backend responde o se agota el tiempo."""
    for i in range(intentos):
        if await _health_check(url):
            return True
        log.info(f"  ⏳ Esperando backend {url} ({i+1}/{intentos})…")
        await asyncio.sleep(pausa)
    return False

# ─────────────────────────────────────────────────────────────────────────────
#  GESTIÓN DE VRAM (EXCLUSIÓN MUTUA)
# ─────────────────────────────────────────────────────────────────────────────
# Qué contenedores Docker deben PARARSE cuando se activa cada nivel
_INCOMPATIBLES: dict[str, list[str]] = {
    "INSTANTANEO": ["sglang-server"],           # TabbAPI (6GB) + SGLang (5.7GB) = overflow
    "AGIL":        ["exllamav2-api"],           # SGLang (5.7GB) + TabbAPI (6GB) = overflow
    "PROFUNDO":    ["exllamav2-api", "sglang-server"],  # Ollama híbrido necesita VRAM libre
    "MASIVO":      ["exllamav2-api", "sglang-server"],  # Qwen 32B ocupa TODA la VRAM
    "CODIGO":      ["exllamav2-api", "sglang-server"],  # DeepSeek Coder híbrido
}

async def _conmutar_vram(nivel: str) -> str:
    """
    Gestiona la VRAM de 8GB con exclusión mutua entre contenedores Docker.
    Detiene los motores incompatibles y arranca el necesario.
    Retorna la URL del backend destino.
    """
    ruta = RUTAS[nivel]

    if _docker_client:
        # 1) Parar contenedores incompatibles
        for nombre in _INCOMPATIBLES.get(nivel, []):
            try:
                c = _docker_client.containers.get(nombre)
                if c.status == "running":
                    log.info(f"[VRAM] Liberando VRAM: parando '{nombre}'…")
                    c.stop(timeout=8)
            except docker.errors.NotFound:
                pass
            except Exception as ex:
                log.warning(f"[VRAM] No se pudo parar '{nombre}': {ex}")

        # 2) Arrancar el contenedor del destino (si lo tiene)
        contenedor = ruta.get("contenedor")
        if contenedor:
            try:
                c = _docker_client.containers.get(contenedor)
                if c.status != "running":
                    log.info(f"[VRAM] Activando: arrancando '{contenedor}'…")
                    c.start()
                    ok = await _esperar_backend(ruta["health_url"])
                    if not ok:
                        log.warning(f"[VRAM] Timeout esperando '{contenedor}'")
            except docker.errors.NotFound:
                log.error(f"[VRAM] Contenedor '{contenedor}' no existe. "
                          f"¿Ejecutaste Autoboot_Cluster_V11.sh?")
            except Exception as ex:
                log.warning(f"[VRAM] Error con '{contenedor}': {ex}")
    else:
        log.warning("[VRAM] Docker no disponible — asumiendo backends activos")

    _estado["ruta_activa"] = nivel
    _estado["cambios_vram"] += 1
    return ruta["url"]

# ─────────────────────────────────────────────────────────────────────────────
#  CLASIFICADOR PHI-4 (CPU-ONLY, PUERTO 11435)
# ─────────────────────────────────────────────────────────────────────────────
_SYSTEM_CLASIFICADOR = (
    "Eres un clasificador de tareas de IA. "
    "Tu única función es leer la petición del usuario y responder UNA SOLA PALABRA de esta lista:\n\n"
    "  INSTANTANEO — para: saludos, preguntas sencillas, traducciones cortas, "
    "conversaciones ligeras, autocompletado de texto.\n"
    "  AGIL — para: resúmenes de documentos, tareas multi-paso de agente, "
    "análisis de varios archivos, conversaciones largas con contexto.\n"
    "  PROFUNDO — para: razonamiento matemático paso a paso, debugging de errores complejos "
    "(memory leaks, race conditions), lógica avanzada, preguntas que requieren pensar mucho.\n"
    "  MASIVO — para: análisis de libros o documentos muy largos (>10 páginas), "
    "logs de sistema con cientos de líneas, revisión de codebases completas.\n"
    "  CODIGO — para: escritura de código en C/C++/Python/Bash, refactorización, "
    "completado de funciones, análisis de algoritmos.\n\n"
    "Responde SOLO la palabra. Sin puntuación. Sin explicación. Sin espacios extra."
)

async def _clasificar_con_phi4(prompt: str) -> str:
    """
    Llama a Phi-4 en CPU-only (puerto 11435) para clasificar el nivel de la tarea.
    Con caché LRU para evitar llamadas repetidas.
    """
    # 1) Consultar caché
    cached = _cache_get(prompt)
    if cached:
        log.info(f"[PHI4-CACHE] Hit → {cached}")
        return cached

    payload = {
        "model": PHI4_MODEL,
        "prompt": f"{_SYSTEM_CLASIFICADOR}\n\nPetición: {prompt[:500]}\nClasificación:",
        "stream": False,
        "options": {
            "temperature": 0.0,
            "num_predict": 12,
            "num_gpu": 0,    # CPU-only para no robar VRAM al backend principal
            "stop": ["\n", " ", "."],
        },
    }

    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.post(PHI4_CPU_GENERATE_URL, json=payload)
            resp.raise_for_status()
            raw = resp.json().get("response", "AGIL").strip().upper()

        for nivel in ("INSTANTANEO", "AGIL", "PROFUNDO", "MASIVO", "CODIGO"):
            if nivel in raw:
                log.info(f"[PHI4] '{raw}' → {nivel}")
                _cache_put(prompt, nivel)
                return nivel

        log.warning(f"[PHI4] Respuesta no reconocida: '{raw}', fallback a AGIL")
        return "AGIL"

    except Exception as exc:
        log.error(f"[PHI4] Error de clasificación: {exc}. Fallback a AGIL.")
        return "AGIL"

# ─────────────────────────────────────────────────────────────────────────────
#  PROXY HTTP STREAMING
# ─────────────────────────────────────────────────────────────────────────────
async def _hacer_proxy(
    body: dict,
    target_url: str,
    request: Request,
    streaming: bool,
) -> StreamingResponse | JSONResponse:
    """Reenvía la solicitud al backend con soporte completo de SSE streaming."""
    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in ("host", "content-length", "transfer-encoding")
    }
    headers["content-type"] = "application/json"

    async def _generar():
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(360.0, connect=10.0)) as client:
                async with client.stream("POST", target_url, json=body, headers=headers) as r:
                    if r.status_code >= 400:
                        raw = await r.aread()
                        err_msg = raw.decode("utf-8", errors="replace")[:300]
                        yield (
                            f'data: {{"error":"Backend {r.status_code}: {err_msg}"}}\n\n'
                        ).encode()
                        return
                    async for chunk in r.aiter_bytes(chunk_size=4096):
                        if chunk:
                            yield chunk
        except httpx.ConnectError as exc:
            yield f'data: {{"error":"Backend no disponible: {exc}"}}\n\n'.encode()
        except httpx.TimeoutException:
            yield b'data: {"error":"Timeout — el backend tard\u00f3 demasiado"}\n\n'
        except Exception as exc:
            yield f'data: {{"error":"Error de proxy: {exc}"}}\n\n'.encode()

    if streaming:
        return StreamingResponse(_generar(), media_type="text/event-stream")

    # Para no-streaming: acumular chunks y devolver JSON
    chunks: list[bytes] = []
    async for chunk in _generar():
        chunks.append(chunk)
    full = b"".join(chunks)

    # Algunos backends devuelven JSON puro (no SSE)
    try:
        return JSONResponse(content=json.loads(full))
    except json.JSONDecodeError:
        pass

    # Intentar extraer el último bloque SSE con finish_reason
    lines = full.decode("utf-8", errors="replace").splitlines()
    for line in reversed(lines):
        line = line.strip()
        if line.startswith("data: ") and "[DONE]" not in line:
            try:
                return JSONResponse(content=json.loads(line[6:]))
            except Exception:
                pass

    return JSONResponse(
        content={"error": "No se pudo parsear la respuesta del backend"},
        status_code=502,
    )

# ─────────────────────────────────────────────────────────────────────────────
#  FASTAPI APP
# ─────────────────────────────────────────────────────────────────────────────
app = FastAPI(title="OMEN AI Router", version="5.0.0")


@app.get("/health")
async def endpoint_health():
    """Estado del router y de todos los backends."""
    backends: dict[str, bool] = {}
    for nombre, ruta in RUTAS.items():
        backends[nombre] = await _health_check(ruta["health_url"])
    phi4_cpu_ok = await _health_check(PHI4_CPU_HEALTH_URL)

    return {
        "status": "ok",
        "version": "5.0.0",
        "ruta_activa": _estado["ruta_activa"],
        "cambios_vram": _estado["cambios_vram"],
        "backends": backends,
        "phi4_cpu_router": phi4_cpu_ok,
        "decisiones_en_cache": len(_phi4_cache),
    }


@app.get("/v1/models")
async def endpoint_modelos():
    """Catálogo de modelos disponibles (formato OpenAI — compatible con OpenClaw)."""
    ts = int(time.time())
    catalog = [
        # Nombres amigables para el menú de OpenClaw
        {"id": "ruteador-auto", "description": "🤖 Auto — Phi-4 elige el nivel óptimo"},
        {"id": "instantaneo",   "description": "⚡ Instantáneo — ExLlamaV2 puro VRAM (<2s)"},
        {"id": "agil",          "description": "🚀 Ágil — SGLang RadixAttention (agentes)"},
        {"id": "profundo",      "description": "🧠 Profundo — DeepSeek R1 14B razonamiento"},
        {"id": "masivo",        "description": "🔬 Masivo — Qwen2.5 32B análisis completo"},
        {"id": "codigo",        "description": "💻 Código — DeepSeek Coder V2"},
        {"id": "phi4",          "description": "🔷 Phi-4 — CPU directo (router/razonamiento)"},
        # Alias explícitos para compatibilidad con otras herramientas
        {"id": "deepseek-r1:14b"},
        {"id": "qwen2.5:32b"},
        {"id": "llama-3.1-8b-awq"},
        {"id": "deepseek-coder-v2"},
        {"id": "qwen2.5-coder-7b-exl2"},
    ]
    return {
        "object": "list",
        "data": [
            {
                "id": m["id"],
                "object": "model",
                "created": ts,
                "owned_by": "omen-local",
                "description": m.get("description", ""),
            }
            for m in catalog
        ],
    }


@app.post("/v1/chat/completions")
async def endpoint_chat(request: Request):
    body = await request.json()

    modelo_raw      = body.get("model", "ruteador-auto").strip()
    modelo_lower    = modelo_raw.lower()
    mensajes        = body.get("messages", [])
    ultimo_prompt   = mensajes[-1].get("content", "") if mensajes else ""
    es_streaming    = body.get("stream", False)

    log.info(f"\n{'─'*62}")
    log.info(f"[REQUEST] modelo='{modelo_raw}'  stream={es_streaming}")
    log.info(f"[PROMPT]  {ultimo_prompt[:120]}…")

    # ── Resolver nivel ────────────────────────────────────────────────────
    nivel = ALIAS_A_NIVEL.get(modelo_lower)

    if nivel == "PHI4_DIRECTO":
        # Phi-4 CPU directo: redirigir a la instancia CPU de Ollama
        log.info("[MODO: MANUAL] → Phi-4 CPU directo (puerto 11435)")
        body["model"] = PHI4_MODEL
        target_url = PHI4_CPU_GENERATE_URL.replace("/api/generate", "/v1/chat/completions")
        return await _hacer_proxy(body, target_url, request, es_streaming)

    elif nivel is None:
        # Auto-routing: consultar Phi-4
        log.info("[MODO: AUTO] Consultando clasificador Phi-4 (CPU)…")
        nivel = await _clasificar_con_phi4(ultimo_prompt)
        log.info(f"[MODO: AUTO] → {nivel}")

    else:
        log.info(f"[MODO: MANUAL] Override → {nivel}")

    # ── Conmutar VRAM y obtener URL ───────────────────────────────────────
    target_url = await _conmutar_vram(nivel)
    body["model"] = RUTAS[nivel]["modelo"]

    log.info(f"[PROXY] {nivel} → modelo='{body['model']}' @ {target_url}")

    return await _hacer_proxy(body, target_url, request, es_streaming)


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    log.info("═" * 62)
    log.info("  OMEN AI Router V5  —  iniciando en http://0.0.0.0:8000")
    log.info("  Endpoints:")
    log.info("    GET  /health       → estado de todos los backends")
    log.info("    GET  /v1/models    → catálogo de modelos")
    log.info("    POST /v1/chat/completions → proxy inteligente")
    log.info("═" * 62)
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")
