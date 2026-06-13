#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║ OMEN AI CLUSTER — Orchestrador Semántico V10 (build V17)                   ║
║ RTX 4070 8GB · Intel Ultra 7 · 32GB RAM · SSD exFAT                        ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ V17 — Correcciones integrales de auditoría:                                ║
║  ✔ [V17-R1]  9 SyntaxError resueltos definitivamente (delimitadores)        ║
║  ✔ [V17-R2]  PHI4_DIRECTO: verificación de disponibilidad + fallback GPU    ║
║  ✔ [V17-R3]  _conmutar_vram: fallback inmediato ante docker.NotFound        ║
║  ✔ [V17-R4]  _cache_get/_cache_put: clave incluye agent_id (no colisión)   ║
║  ✔ [V17-R5]  RAG_MAX_DIST alineado con MCP (distancia coseno 0.35)         ║
║  ✔ [V17-R6]  asyncio.Lock en top-level del módulo (no en coroutine)         ║
║  ✔ [V17-R7]  _background_health: tarea schedulada en _startup correctamente ║
║  ✔ [V17-R8]  _startup declara globales (_rag_disponible, _chroma_collection ║
║              _phi4_model_activo) antes de asignar                           ║
║  ✔ [V17-R9]  Métricas thread-safe: Counter() es seguro pero añadimos lock   ║
║              para evitar race condition en incrementos compuestos           ║
║  ✔ [V17-R10] _proxy: generador async con manejo de CancelledError          ║
║  ✔ [V17-R11] Versión y build actualizados a V10 / V17                      ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ Heredado de V9/V16 (funcionalidades completas):                            ║
║  ✔ [V16-S2]  _proxy generador async completo                               ║
║  ✔ [V14-1]   ChromaDB RAG: UUID de colección resuelto en startup            ║
║  ✔ [V14-2]   _rag_disponible actualizado dinámicamente cada 30s             ║
║  ✔ [V14-3]   asyncio.Lock serializa conmutaciones de VRAM                  ║
║  ✔ [V14-4]   Caché TTL 15s en /health                                      ║
║  ✔ [V14-5]   RotatingFileHandler 50MB × 3 backups                          ║
║  ✔ [V14-6]   PRECISO_OPT auto-seleccionado (prompts < 300 chars)           ║
║  ✔ [V14-7]   Copia defensiva en _rag_inject                                ║
║  ✔ [V14-8]   Campo modelo_nuevo obsoleto eliminado de PROFUNDO              ║
║  ✔ [V14-9]   Clave duplicada phi4-reasoning:14b corregida                  ║
║  ✔ [V14-10]  RAG_TOP_K=6 (consistente con mcp.json)                       ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ Niveles V17:                                                                ║
║  CHAT        → TabbAPI  :5000  llama-3.1-8b-exl2        (6.71GB VRAM)     ║
║  INSTANTANEO → TabbAPI  :5000  qwen2.5-coder-7b-exl2    (6.95GB VRAM)     ║
║  AGIL        → SGLang   :30000 llama-3.1-8b-awq          (5.74GB VRAM)     ║
║  PROFUNDO    → Ollama   :11434 deepseek-r1:14b           (~7GB  híb.)      ║
║  PRECISO     → Ollama   :11434 phi4-reasoning:plus       (~7.5GB híb.)     ║
║  PRECISO_OPT → Ollama   :11434 phi4-reasoning:14b-q4_K_M (~7GB  híb.)     ║
║  MASIVO      → Ollama   :11434 qwen2.5:32b               (8GB+11GB RAM)    ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import asyncio
import json
import logging
import os
import time
from collections import Counter, OrderedDict
from logging.handlers import RotatingFileHandler
from typing import Optional

import docker
import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

# ─────────────────────────────────────────────────────────────────────────────
# LOGGING — RotatingFileHandler 50MB × 3 backups + StreamHandler consola
# [V17-R1] Paréntesis de cierre explícitos en todas las estructuras
# ─────────────────────────────────────────────────────────────────────────────
_LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "router_v10.log")

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        RotatingFileHandler(
            _LOG_FILE,
            maxBytes=50 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        ),
    ],
)
log = logging.getLogger("router-v10")

# ─────────────────────────────────────────────────────────────────────────────
# RUTAS V17 — 7 niveles de razonamiento
# ─────────────────────────────────────────────────────────────────────────────
RUTAS: dict[str, dict] = {
    "CHAT": {
        "url": "http://localhost:5000/v1/chat/completions",
        "health_url": "http://localhost:5000/health",
        "modelo": "llama-3.1-8b-exl2",
        "contenedor": "exllamav2-api",
        "tabbyapi_swap": True,
        "descripcion": "Conversación casual, preguntas generales, traducciones",
        "vram_gb": 6.71,
        "context_window": 8192,
        "max_tokens": 4096,
        "timeout_s": 35.0,
        "opciones_extra": None,
    },
    "INSTANTANEO": {
        "url": "http://localhost:5000/v1/chat/completions",
        "health_url": "http://localhost:5000/health",
        "modelo": "qwen2.5-coder-7b-exl2",
        "contenedor": "exllamav2-api",
        "tabbyapi_swap": True,
        "descripcion": "Código rápido, snippets, funciones cortas, autocompletado",
        "vram_gb": 6.95,
        "context_window": 4096,
        "max_tokens": 2048,
        "timeout_s": 35.0,
        "opciones_extra": None,
    },
    "AGIL": {
        "url": "http://localhost:30000/v1/chat/completions",
        "health_url": "http://localhost:30000/health",
        "modelo": "llama-3.1-8b-awq",
        "contenedor": "sglang-server",
        "tabbyapi_swap": False,
        "descripcion": "Agentes multi-paso, resúmenes, análisis de documentos",
        "vram_gb": 5.74,
        "context_window": 32768,
        "max_tokens": 8192,
        "timeout_s": 70.0,
        "opciones_extra": None,
    },
    "PROFUNDO": {
        "url": "http://localhost:11434/v1/chat/completions",
        "health_url": "http://localhost:11434/api/tags",
        "modelo": "deepseek-r1:14b",
        "contenedor": None,
        "tabbyapi_swap": False,
        "descripcion": "Razonamiento profundo, debugging complejo, lógica general",
        "vram_gb": 7.0,
        "context_window": 16384,
        "max_tokens": 8192,
        "timeout_s": 130.0,
        "opciones_extra": None,
    },
    "PRECISO": {
        "url": "http://localhost:11434/v1/chat/completions",
        "health_url": "http://localhost:11434/api/tags",
        "modelo": "phi4-reasoning:plus",
        "contenedor": None,
        "tabbyapi_swap": False,
        "descripcion": "Phi Mayor Precisión — matemáticas, STEM, lógica formal exacta",
        "vram_gb": 7.5,
        "context_window": 16384,
        "max_tokens": 4096,
        "timeout_s": 200.0,
        "opciones_extra": {"temperature": 0.6, "top_p": 0.95},
    },
    "PRECISO_OPT": {
        "url": "http://localhost:11434/v1/chat/completions",
        "health_url": "http://localhost:11434/api/tags",
        "modelo": "phi4-reasoning:14b-q4_K_M",
        "contenedor": None,
        "tabbyapi_swap": False,
        "descripcion": "Phi Optimizada — STEM y ciencias, más rápida que :plus",
        "vram_gb": 7.0,
        "context_window": 16384,
        "max_tokens": 4096,
        "timeout_s": 160.0,
        "opciones_extra": {"temperature": 0.6, "top_p": 0.95},
    },
    "MASIVO": {
        "url": "http://localhost:11434/v1/chat/completions",
        "health_url": "http://localhost:11434/api/tags",
        "modelo": "qwen2.5:32b",
        "contenedor": None,
        "tabbyapi_swap": False,
        "descripcion": "Análisis masivo: libros enteros, logs largos, codebases",
        "vram_gb": 8.0,
        "context_window": 32768,
        "max_tokens": 16384,
        "timeout_s": 320.0,
        "opciones_extra": None,
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# INCOMPATIBILIDADES DE VRAM
# ─────────────────────────────────────────────────────────────────────────────
_INCOMPATIBLES: dict[str, list[str]] = {
    "CHAT":        ["sglang-server"],
    "INSTANTANEO": ["sglang-server"],
    "AGIL":        ["exllamav2-api"],
    "PROFUNDO":    ["exllamav2-api", "sglang-server"],
    "PRECISO":     ["exllamav2-api", "sglang-server"],
    "PRECISO_OPT": ["exllamav2-api", "sglang-server"],
    "MASIVO":      ["exllamav2-api", "sglang-server"],
}

# ─────────────────────────────────────────────────────────────────────────────
# TIMEOUT-FALLBACK — bajada automática de nivel si el backend falla
# ─────────────────────────────────────────────────────────────────────────────
_TIMEOUT_FALLBACK: dict[str, str] = {
    "MASIVO":      "PROFUNDO",
    "PRECISO":     "PROFUNDO",
    "PRECISO_OPT": "PROFUNDO",
    "PROFUNDO":    "AGIL",
    "INSTANTANEO": "CHAT",
}

# ─────────────────────────────────────────────────────────────────────────────
# PRE-ROUTING POR AGENTE OPENCLAW (header X-OpenClaw-Agent)
# ─────────────────────────────────────────────────────────────────────────────
_AGENT_TO_NIVEL: dict[str, str] = {
    "coder":      "INSTANTANEO",
    "analyst":    "MASIVO",
    "reasoner":   "PRECISO",
    "researcher": "AGIL",
}

# ─────────────────────────────────────────────────────────────────────────────
# ALIAS MODELO → NIVEL (override manual desde OpenClaw o API)
# ─────────────────────────────────────────────────────────────────────────────
ALIAS_A_NIVEL: dict[str, Optional[str]] = {
    # Auto (clasificador decide)
    "ruteador-auto": None, "auto": None, "default": None,
    # CHAT
    "chat": "CHAT", "llama-3.1-8b-exl2": "CHAT", "llama3.1": "CHAT",
    # INSTANTANEO
    "instantaneo": "INSTANTANEO", "instant": "INSTANTANEO",
    "exllama": "INSTANTANEO", "tabby": "INSTANTANEO",
    "qwen2.5-coder-7b-exl2": "INSTANTANEO",
    "codigo": "INSTANTANEO",
    "coder": "INSTANTANEO",
    # AGIL
    "agil": "AGIL", "sglang": "AGIL", "llama-3.1-8b-awq": "AGIL",
    # PROFUNDO
    "profundo": "PROFUNDO", "deepseek-r1:14b": "PROFUNDO",
    "deepseek-r1": "PROFUNDO", "r1": "PROFUNDO",
    # PRECISO — Phi Mayor Precisión
    "preciso": "PRECISO",
    "phi-mayor-precision": "PRECISO",
    "phi mayor precision": "PRECISO",
    "phi4-reasoning:plus": "PRECISO",
    "phi4-reasoning": "PRECISO",
    "phi-preciso": "PRECISO",
    # PRECISO_OPT — Phi Optimizada
    "preciso-opt": "PRECISO_OPT",
    "phi-optimizada": "PRECISO_OPT",
    "phi optimizada": "PRECISO_OPT",
    "phi4-reasoning:14b-q4_k_m": "PRECISO_OPT",
    "phi4-reasoning:14b-q4_K_M": "PRECISO_OPT",
    # MASIVO
    "masivo": "MASIVO", "qwen2.5:32b": "MASIVO", "qwen": "MASIVO",
    # PHI4 directo CPU (clasificador)
    "phi4": "PHI4_DIRECTO", "phi-4": "PHI4_DIRECTO",
    "phi4-mini": "PHI4_DIRECTO", "phi": "PHI4_DIRECTO",
}

# ─────────────────────────────────────────────────────────────────────────────
# CLASIFICADOR — Capa 2: Embeddings (nomic-embed-text en CPU)
# ─────────────────────────────────────────────────────────────────────────────
_EMBED_DESCRIPTIONS: dict[str, str] = {
    "CHAT":
        "conversación casual saludo preguntas simples respuesta corta "
        "chit-chat traducción explicación sencilla consulta rápida",
    "INSTANTANEO":
        "completar código escribir función snippet líneas de código "
        "Python C C++ Bash autocompletado tab refactoring rápido script",
    "AGIL":
        "resumir documento analizar archivo agente multi-paso contexto largo "
        "leer correos múltiples documentos extraer información mantener historial",
    "PROFUNDO":
        "razonamiento lógico debugging error complejo memory leak "
        "race condition algoritmo complejo diseño de sistema arquitectura",
    "PRECISO":
        "matemáticas álgebra cálculo integral derivada estadística probabilidad "
        "física química biología ciencias posgrado lógica formal resultado exacto numérico STEM",
    "MASIVO":
        "analizar libro entero miles de líneas logs de sistema codebase completo "
        "revisar proyecto completo documento muy largo gran volumen contexto extenso",
}

EMBED_MODEL     = "nomic-embed-text"
EMBED_THRESHOLD = 0.63
EMBED_CPU_URL   = "http://localhost:11435/api/embeddings"

# ─────────────────────────────────────────────────────────────────────────────
# CLASIFICADOR — Capa 3: Phi-4-mini como fallback LLM (CPU :11435)
# ─────────────────────────────────────────────────────────────────────────────
PHI4_CPU_URL  = "http://localhost:11435/api/generate"
PHI4_CPU_TAGS = "http://localhost:11435/api/tags"
PHI4_MODEL    = "phi4-mini"
PHI4_FALLBACK = "phi4"

# [V17-R1] Paréntesis de cierre explícito en string multilínea
_SYSTEM_PHI4 = (
    "Eres un clasificador de tareas. Responde SOLO con una de estas palabras exactas:\n"
    " CHAT — conversación casual, saludos, preguntas simples, traducciones cortas.\n"
    " INSTANTANEO — código corto: snippets, funciones, autocompletado, Bash.\n"
    " AGIL — resúmenes, agente multi-paso, análisis de archivos, contexto largo.\n"
    " PROFUNDO — debugging complejo, diseño de sistemas, razonamiento lógico general.\n"
    " PRECISO — matemáticas exactas (álgebra, cálculo, estadística), ciencias a nivel "
    "universitario o posgrado, lógica formal, problemas STEM con resultado numérico, física, química.\n"
    " MASIVO — libros enteros, logs muy largos (>500 líneas), codebases completas.\n"
    "Responde SOLO la palabra. Sin puntuación. Sin explicación."
)

_phi4_model_activo: Optional[str] = None

# ─────────────────────────────────────────────────────────────────────────────
# [V17-R2] PHI4_DIRECTO — URL correcta para Ollama CPU (chat completions)
# ─────────────────────────────────────────────────────────────────────────────
PHI4_CPU_CHAT_URL   = "http://localhost:11435/v1/chat/completions"
PHI4_GPU_CHAT_URL   = "http://localhost:11434/v1/chat/completions"
_phi4_cpu_available = False  # se verifica en _startup

# ─────────────────────────────────────────────────────────────────────────────
# RAG — ChromaDB
# [V17-R5] RAG_MAX_DIST=0.35 (distancia coseno) — consistente con
#           SIMILARITY_THRESHOLD=0.65 en mcp.json (1 - 0.35 = 0.65)
# ─────────────────────────────────────────────────────────────────────────────
CHROMA_URL        = "http://localhost:8001"
CHROMA_COLLECTION = "obsidian_vault"
RAG_TOP_K         = 6
RAG_MAX_DIST      = 0.35   # distancia coseno (menor = más similar)
RAG_NIVELES       = {"AGIL", "PROFUNDO", "PRECISO", "PRECISO_OPT", "MASIVO"}

_rag_disponible        = False
_chroma_collection_id: Optional[str] = None

# ─────────────────────────────────────────────────────────────────────────────
# [V17-R4] CACHÉ LRU — clave incluye agent_id para evitar colisiones
# ─────────────────────────────────────────────────────────────────────────────
_cache: OrderedDict[str, str] = OrderedDict()
_CACHE_MAX, _CACHE_KEY_LEN = 256, 300

def _cache_get(prompt: str, agent_id: str = "") -> Optional[str]:
    k = f"{agent_id}:{prompt[:_CACHE_KEY_LEN]}"
    if k in _cache:
        _cache.move_to_end(k)
        return _cache[k]
    return None

def _cache_put(prompt: str, nivel: str, agent_id: str = "") -> None:
    k = f"{agent_id}:{prompt[:_CACHE_KEY_LEN]}"
    if len(_cache) >= _CACHE_MAX:
        _cache.popitem(last=False)
    _cache[k] = nivel

# ─────────────────────────────────────────────────────────────────────────────
# MÉTRICAS
# [V17-R9] _metricas_lock para evitar race conditions en incrementos compuestos
# ─────────────────────────────────────────────────────────────────────────────
_metricas = {
    "requests_por_nivel": Counter(),
    "errores_por_nivel":  Counter(),
    "fallbacks":          Counter(),
    "latencia_total_ms":  Counter(),
    "clasificador_capas": Counter(),
    "rag_inyecciones":    0,
    "cambios_vram":       0,
}
_metricas_lock = asyncio.Lock()

# ─────────────────────────────────────────────────────────────────────────────
# ESTADO GLOBAL
# [V17-R1] Llaves de cierre explícitas
# ─────────────────────────────────────────────────────────────────────────────
_estado = {
    "ruta_activa":       None,
    "tabbyapi_modelo":   None,
    "tabbyapi_cargando": False,
}

_vectores_referencia: dict[str, list[float]] = {}

# ─────────────────────────────────────────────────────────────────────────────
# [V14-3] LOCK GLOBAL PARA CONMUTACIONES DE VRAM
# [V17-R6] Creado en top-level del módulo (no dentro de coroutine/función)
# ─────────────────────────────────────────────────────────────────────────────
_vram_lock = asyncio.Lock()

# ─────────────────────────────────────────────────────────────────────────────
# [V14-4] CACHÉ TTL PARA ENDPOINT /health (15 segundos)
# ─────────────────────────────────────────────────────────────────────────────
_HEALTH_TTL    = 15.0
_health_cache: dict = {"data": None, "ts": 0.0}

# ─────────────────────────────────────────────────────────────────────────────
# DOCKER CLIENT
# ─────────────────────────────────────────────────────────────────────────────
try:
    _docker = docker.from_env()
    log.info("✔ Docker client conectado")
except Exception as _e:
    log.warning(f"⚠ Docker no disponible: {_e}")
    _docker = None

# ─────────────────────────────────────────────────────────────────────────────
# FASTAPI APP
# ─────────────────────────────────────────────────────────────────────────────
app = FastAPI(title="OMEN AI Router V10", version="10.17.0")

# ─────────────────────────────────────────────────────────────────────────────
# UTILIDADES INTERNAS
# ─────────────────────────────────────────────────────────────────────────────

async def _health_ok(url: str, timeout: float = 3.0) -> bool:
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.get(url)
            return r.status_code < 400
    except Exception:
        return False


async def _esperar_backend(url: str, timeout: int = 90, label: str = "") -> bool:
    """Espera que un backend responda OK. Retorna True si responde en tiempo."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if await _health_ok(url):
            return True
        await asyncio.sleep(3)
    log.warning(f"[WAIT] Timeout ({timeout}s) esperando {label or url}")
    return False


async def _asegurar_modelo_tabbyapi(nivel: str) -> None:
    """
    Carga el modelo correcto en TabbAPI vía /v1/model/load.
    Spinlock con finally garantizado para liberar tabbyapi_cargando.
    """
    modelo_objetivo = RUTAS[nivel]["modelo"]
    if _estado["tabbyapi_modelo"] == modelo_objetivo:
        return

    if _estado["tabbyapi_cargando"]:
        # Esperar a que el swap previo termine (máx 90s)
        deadline = time.monotonic() + 90
        while _estado["tabbyapi_cargando"] and time.monotonic() < deadline:
            await asyncio.sleep(2)
        if _estado["tabbyapi_modelo"] == modelo_objetivo:
            return

    _estado["tabbyapi_cargando"] = True
    try:
        log.info(f"[TABBY] Cargando modelo {modelo_objetivo}…")
        async with httpx.AsyncClient(timeout=30.0) as c:
            await c.post(
                "http://localhost:5000/v1/model/unload",
                json={},
            )
        await asyncio.sleep(2)
        async with httpx.AsyncClient(timeout=30.0) as c:
            resp = await c.post(
                "http://localhost:5000/v1/model/load",
                json={"name": modelo_objetivo},
            )
            if resp.status_code < 300:
                _estado["tabbyapi_modelo"] = modelo_objetivo
                log.info(f"[TABBY] ✔ Modelo {modelo_objetivo} cargado")
            else:
                log.error(f"[TABBY] ✘ Error cargando {modelo_objetivo}: {resp.status_code}")
    except Exception as e:
        log.error(f"[TABBY] ✘ Excepción cargando modelo: {e}")
    finally:
        _estado["tabbyapi_cargando"] = False


async def _conmutar_vram(nivel: str) -> str:
    """
    Detiene contenedores incompatibles y arranca el contenedor del nivel dado.
    [V17-R3] Fallback inmediato ante docker.errors.NotFound en lugar de timeout.
    Usa _vram_lock para serializar conmutaciones concurrentes.
    """
    async with _vram_lock:
        if _estado["ruta_activa"] == nivel:
            return RUTAS[nivel]["url"]

        if _docker is None:
            log.warning("[VRAM] Docker no disponible — sin gestión de contenedores")
            return RUTAS[nivel]["url"]

        incompatibles = _INCOMPATIBLES.get(nivel, [])
        for cont_name in incompatibles:
            try:
                c = _docker.containers.get(cont_name)
                if c.status == "running":
                    log.info(f"[VRAM] Deteniendo {cont_name}…")
                    c.stop(timeout=10)
                    log.info(f"[VRAM] {cont_name} detenido")
            except docker.errors.NotFound:
                log.debug(f"[VRAM] {cont_name} no existe — sin acción")
            except Exception as e:
                log.warning(f"[VRAM] Error deteniendo {cont_name}: {e}")

        contenedor = RUTAS[nivel].get("contenedor")
        if contenedor:
            try:
                c = _docker.containers.get(contenedor)
                if c.status != "running":
                    log.info(f"[VRAM] Arrancando {contenedor}…")
                    c.start()
                    log.info(f"[VRAM] {contenedor} arrancado")
                    async with _metricas_lock:
                        _metricas["cambios_vram"] += 1
            except docker.errors.NotFound:
                # [V17-R3] Fallback inmediato — no esperar timeout del proxy
                log.error(f"[VRAM] {contenedor!r} no existe — Autoboot no ejecutado")
                fb = _TIMEOUT_FALLBACK.get(nivel)
                if fb:
                    log.warning(f"[VRAM] Fallback automático: {nivel} → {fb}")
                    async with _metricas_lock:
                        _metricas["fallbacks"][f"vram_notfound_{nivel}"] += 1
                    _estado["ruta_activa"] = fb
                    return RUTAS[fb]["url"]
                return RUTAS[nivel]["url"]
            except Exception as e:
                log.error(f"[VRAM] Error arrancando {contenedor}: {e}")

        # Swap de modelo dentro de TabbAPI si aplica
        if RUTAS[nivel].get("tabbyapi_swap"):
            await _asegurar_modelo_tabbyapi(nivel)

        _estado["ruta_activa"] = nivel
        return RUTAS[nivel]["url"]


async def _rag_inject(body: dict, prompt: str, nivel: str) -> dict:
    """
    Inyecta fragmentos relevantes del vault Obsidian (ChromaDB) en el system prompt.
    [V14-7] Copia defensiva del body para no mutar el original del caller.
    """
    if not _rag_disponible or nivel not in RAG_NIVELES or not prompt.strip():
        return body

    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            # Obtener embedding del prompt
            emb_resp = await c.post(
                EMBED_CPU_URL,
                json={"model": EMBED_MODEL, "prompt": prompt},
            )
            if emb_resp.status_code != 200:
                return body
            embedding = emb_resp.json().get("embedding", [])
            if not embedding:
                return body

            # Buscar en ChromaDB
            q_resp = await c.post(
                f"{CHROMA_URL}/api/v1/collections/{_chroma_collection_id}/query",
                json={
                    "query_embeddings": [embedding],
                    "n_results": RAG_TOP_K,
                    "include": ["documents", "distances"],
                },
            )
            if q_resp.status_code != 200:
                return body

            data = q_resp.json()
            docs      = (data.get("documents") or [[]])[0]
            distances = (data.get("distances") or [[]])[0]

            fragmentos = [
                doc for doc, dist in zip(docs, distances)
                if dist <= RAG_MAX_DIST and doc.strip()
            ]

            if not fragmentos:
                return body

        # [V14-7] Copia defensiva
        body = dict(body)
        msgs = list(body.get("messages", []))

        ctx_text = "\n\n---\n\n".join(fragmentos)
        rag_bloque = (
            f"[CONTEXTO DEL VAULT OBSIDIAN — {len(fragmentos)} fragmento(s) relevantes]\n\n"
            f"{ctx_text}\n\n"
            "[Fin del contexto. Usa esta información si es relevante para la pregunta.]"
        )

        if msgs and msgs[0].get("role") == "system":
            msgs[0] = {**msgs[0], "content": msgs[0]["content"] + "\n\n" + rag_bloque}
        else:
            msgs.insert(0, {"role": "system", "content": rag_bloque})

        body["messages"] = msgs
        async with _metricas_lock:
            _metricas["rag_inyecciones"] += 1
        log.info(f"[RAG] ✔ {len(fragmentos)} fragmentos inyectados (dist≤{RAG_MAX_DIST})")

    except Exception as e:
        log.warning(f"[RAG] ✘ Error en inyección: {e}")

    return body


async def _precalcular_vectores() -> None:
    """Precalcula los vectores de referencia para el clasificador de embeddings."""
    global _vectores_referencia
    ok_count = 0
    async with httpx.AsyncClient(timeout=20.0) as c:
        for nivel, desc in _EMBED_DESCRIPTIONS.items():
            try:
                r = await c.post(EMBED_CPU_URL, json={"model": EMBED_MODEL, "prompt": desc})
                if r.status_code == 200:
                    _vectores_referencia[nivel] = r.json()["embedding"]
                    ok_count += 1
            except Exception as e:
                log.warning(f"[EMBED] No se pudo vectorizar {nivel}: {e}")
    log.info(f"[EMBED] {ok_count}/{len(_EMBED_DESCRIPTIONS)} vectores de referencia precalculados")


def _coseno(a: list[float], b: list[float]) -> float:
    """Similitud coseno entre dos vectores."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot   = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


async def _clasificar_embeddings(prompt: str) -> Optional[str]:
    """
    Capa 2 del clasificador: similitud coseno con vectores de referencia.
    Retorna el nivel más cercano si supera EMBED_THRESHOLD, else None.
    """
    if not _vectores_referencia:
        return None
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.post(EMBED_CPU_URL, json={"model": EMBED_MODEL, "prompt": prompt})
            if r.status_code != 200:
                return None
            prompt_vec = r.json().get("embedding", [])
            if not prompt_vec:
                return None
        sims = {n: _coseno(prompt_vec, v) for n, v in _vectores_referencia.items()}
        best_nivel, best_sim = max(sims.items(), key=lambda x: x[1])
        log.debug(f"[EMBED] sims={sims} → best={best_nivel}({best_sim:.3f})")
        return best_nivel if best_sim >= EMBED_THRESHOLD else None
    except Exception as e:
        log.warning(f"[EMBED] Error: {e}")
        return None


async def _detectar_phi4() -> Optional[str]:
    """Detecta qué modelo Phi-4 está disponible en la instancia CPU."""
    try:
        async with httpx.AsyncClient(timeout=8.0) as c:
            r = await c.get(PHI4_CPU_TAGS)
            if r.status_code == 200:
                modelos = [m["name"] for m in r.json().get("models", [])]
                if PHI4_MODEL in modelos:
                    return PHI4_MODEL
                if PHI4_FALLBACK in modelos:
                    return PHI4_FALLBACK
    except Exception:
        pass
    return None


async def _clasificar_phi4(prompt: str) -> Optional[str]:
    """
    Capa 3 del clasificador: Phi-4-mini como fallback LLM.
    Solo se invoca si la capa de embeddings no alcanzó el threshold.
    """
    if not _phi4_model_activo:
        return None
    try:
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.post(
                PHI4_CPU_URL,
                json={
                    "model": _phi4_model_activo,
                    "system": _SYSTEM_PHI4,
                    "prompt": prompt[:600],
                    "stream": False,
                    "options": {"num_predict": 10, "temperature": 0.0},
                },
            )
            if r.status_code == 200:
                respuesta = r.json().get("response", "").strip().upper().split()[0]
                if respuesta in RUTAS:
                    return respuesta
    except Exception as e:
        log.warning(f"[PHI4] Error: {e}")
    return None


async def _clasificar(prompt: str, agent_id: str = "") -> tuple[str, str]:
    """
    Clasificador de 4 capas:
      Capa 0: agent_id header de OpenClaw
      Capa 1: LRU cache (incluye agent_id)
      Capa 2: embeddings coseno
      Capa 3: Phi-4-mini LLM fallback
      Default: PROFUNDO
    Retorna (nivel, fuente).
    """
    # Capa 0: agente OpenClaw
    if agent_id and agent_id in _AGENT_TO_NIVEL:
        nivel = _AGENT_TO_NIVEL[agent_id]
        async with _metricas_lock:
            _metricas["clasificador_capas"]["agente"] += 1
        return nivel, "agente"

    # Capa 1: caché LRU (con agent_id en clave)
    cached = _cache_get(prompt, agent_id)
    if cached:
        async with _metricas_lock:
            _metricas["clasificador_capas"]["cache"] += 1
        return cached, "cache"

    # Capa 2: embeddings
    nivel = await _clasificar_embeddings(prompt)
    if nivel:
        _cache_put(prompt, nivel, agent_id)
        async with _metricas_lock:
            _metricas["clasificador_capas"]["embed"] += 1
        return nivel, "embed"

    # Capa 3: Phi-4
    nivel = await _clasificar_phi4(prompt)
    if nivel:
        _cache_put(prompt, nivel, agent_id)
        async with _metricas_lock:
            _metricas["clasificador_capas"]["phi4"] += 1
        return nivel, "phi4"

    # Default
    async with _metricas_lock:
        _metricas["clasificador_capas"]["default"] += 1
    return "PROFUNDO", "default"


async def _background_health() -> None:
    """
    Tarea de fondo: monitoriza ChromaDB y actualiza _rag_disponible cada 30s.
    [V17-R7] Schedulada en _startup (no directamente en top-level).
    """
    global _rag_disponible, _chroma_collection_id
    while True:
        try:
            async with httpx.AsyncClient(timeout=5.0) as c:
                r = await c.get(f"{CHROMA_URL}/api/v1/heartbeat")
                disponible = r.status_code == 200
                if disponible and not _chroma_collection_id:
                    r2 = await c.post(
                        f"{CHROMA_URL}/api/v1/collections",
                        json={"name": CHROMA_COLLECTION, "metadata": {"hnsw:space": "cosine"}, "get_or_create": True},
                    )
                    if r2.status_code == 200:
                        _chroma_collection_id = r2.json().get("id")
                if _rag_disponible != disponible:
                    log.info(f"[RAG] ChromaDB: {'✔ disponible' if disponible else '✘ no disponible'}")
                    _rag_disponible = disponible
        except Exception:
            if _rag_disponible:
                log.warning("[RAG] ChromaDB perdido — RAG desactivado")
                _rag_disponible = False
        await asyncio.sleep(30)


def _inject_opciones_extra(body: dict, nivel: str) -> dict:
    """Inyecta opciones específicas del nivel (temperature, top_p, etc.)."""
    extras = RUTAS[nivel].get("opciones_extra") or {}
    if extras:
        for k, v in extras.items():
            body.setdefault(k, v)
    return body


def _inject_thinking(body: dict, nivel: str, modelo: str) -> dict:
    """
    Activa el modo <think> de DeepSeek-R1 y desactiva para niveles simples.
    Solo aplica a modelos que lo soportan.
    """
    if "deepseek-r1" in modelo.lower() and nivel in {"PROFUNDO"}:
        body.setdefault("options", {})
        body["options"]["think"] = True
    return body


def _check_tools(body: dict, nivel: str, modelo: str) -> None:
    """Elimina el campo 'tools' si el modelo/nivel no lo soporta (evita errores 400)."""
    if "tools" in body and nivel in {"PROFUNDO", "PRECISO", "PRECISO_OPT", "MASIVO"}:
        log.debug(f"[TOOLS] Eliminando 'tools' para nivel {nivel} (no soportado)")
        body.pop("tools", None)
        body.pop("tool_choice", None)


# ─────────────────────────────────────────────────────────────────────────────
# [V17-R10] PROXY ASYNC — con manejo explícito de CancelledError
# ─────────────────────────────────────────────────────────────────────────────
async def _proxy(
    body: dict,
    target_url: str,
    request: Request,
    streaming: bool,
    nivel: str,
) -> StreamingResponse | JSONResponse:
    """
    Proxy HTTP hacia el backend seleccionado.
    Soporta streaming SSE y respuesta JSON completa.
    Implementa fallback automático ante timeout.
    """
    timeout_s = RUTAS.get(nivel, {}).get("timeout_s", 60.0) if nivel in RUTAS else 60.0

    async def _gen():
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s)) as c:
                async with c.stream("POST", target_url, json=body) as resp:
                    async for chunk in resp.aiter_bytes():
                        yield chunk
        except asyncio.CancelledError:
            log.debug(f"[PROXY] Stream cancelado por el cliente ({nivel})")
        except httpx.TimeoutException:
            log.warning(f"[PROXY] Timeout ({timeout_s}s) en {nivel}")
            fb = _TIMEOUT_FALLBACK.get(nivel)
            if fb:
                log.info(f"[PROXY] Fallback: {nivel} → {fb}")
                async with _metricas_lock:
                    _metricas["fallbacks"][f"timeout_{nivel}"] += 1
                fb_url = RUTAS[fb]["url"]
                body_fb = dict(body)
                body_fb["model"] = RUTAS[fb]["modelo"]
                async with httpx.AsyncClient(timeout=httpx.Timeout(RUTAS[fb]["timeout_s"])) as c2:
                    async with c2.stream("POST", fb_url, json=body_fb) as resp2:
                        async for chunk in resp2.aiter_bytes():
                            yield chunk
            else:
                err = json.dumps({"error": {"message": f"Timeout en {nivel} sin fallback", "type": "timeout"}})
                yield f"data: {err}\n\ndata: [DONE]\n\n".encode()
        except Exception as e:
            log.error(f"[PROXY] Error en {nivel}: {e}")
            err = json.dumps({"error": {"message": str(e), "type": "proxy_error"}})
            if streaming:
                yield f"data: {err}\n\ndata: [DONE]\n\n".encode()

    if streaming:
        return StreamingResponse(_gen(), media_type="text/event-stream")

    # Modo JSON completo
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s)) as c:
            resp = await c.post(target_url, json=body)
            return JSONResponse(content=resp.json(), status_code=resp.status_code)
    except httpx.TimeoutException:
        fb = _TIMEOUT_FALLBACK.get(nivel)
        if fb:
            async with _metricas_lock:
                _metricas["fallbacks"][f"timeout_{nivel}"] += 1
            fb_url = RUTAS[fb]["url"]
            body_fb = {**body, "model": RUTAS[fb]["modelo"]}
            async with httpx.AsyncClient(timeout=httpx.Timeout(RUTAS[fb]["timeout_s"])) as c2:
                resp2 = await c2.post(fb_url, json=body_fb)
                return JSONResponse(content=resp2.json(), status_code=resp2.status_code)
        return JSONResponse(
            content={"error": {"message": f"Timeout en {nivel}", "type": "timeout"}},
            status_code=504,
        )
    except Exception as e:
        log.error(f"[PROXY] Error JSON en {nivel}: {e}")
        return JSONResponse(
            content={"error": {"message": str(e), "type": "proxy_error"}},
            status_code=502,
        )


# ─────────────────────────────────────────────────────────────────────────────
# STARTUP
# [V17-R7] _background_health se lanza aquí con asyncio.create_task
# [V17-R8] globals declarados antes de asignar
# [V17-R2] Verificación de disponibilidad de phi4 en CPU
# ─────────────────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def _startup():
    global _phi4_model_activo, _rag_disponible, _chroma_collection_id, _phi4_cpu_available

    log.info("═" * 66)
    log.info(" OMEN AI Router V10 (build V17) — iniciando…")
    log.info("═" * 66)

    # Precalcular vectores de referencia (embed clasificador)
    await _precalcular_vectores()

    # Detectar Phi-4 en instancia CPU
    _phi4_model_activo = await _detectar_phi4()
    if _phi4_model_activo:
        log.info(f"[PHI4] Clasificador LLM: {_phi4_model_activo} (CPU :11435)")
    else:
        log.warning("[PHI4] Sin clasificador LLM — solo embeddings activos")

    # [V17-R2] Verificar que phi4/phi4-mini está disponible en CPU para PHI4_DIRECTO
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.get(PHI4_CPU_TAGS)
            if r.status_code == 200:
                modelos_cpu = [m["name"] for m in r.json().get("models", [])]
                _phi4_cpu_available = any(
                    m in modelos_cpu for m in ["phi4-mini", "phi4", "phi4:latest"]
                )
    except Exception:
        _phi4_cpu_available = False

    if not _phi4_cpu_available:
        log.warning(
            "[V17-R2] phi4/phi4-mini NO disponible en Ollama CPU (:11435). "
            "PHI4_DIRECTO usará Ollama GPU (:11434) como fallback. "
            "Para usarlo en CPU: docker exec ollama-cpu-router ollama pull phi4-mini"
        )

    # Verificar ChromaDB inicial
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.get(f"{CHROMA_URL}/api/v1/heartbeat")
            if r.status_code == 200:
                r2 = await c.post(
                    f"{CHROMA_URL}/api/v1/collections",
                    json={"name": CHROMA_COLLECTION, "metadata": {"hnsw:space": "cosine"}, "get_or_create": True},
                )
                if r2.status_code == 200:
                    _chroma_collection_id = r2.json().get("id")
                    _rag_disponible = True
                    log.info(f"[RAG] ✔ ChromaDB: colección UUID={str(_chroma_collection_id)[:8]}…")
    except Exception as e:
        log.warning(f"[RAG] ChromaDB no disponible en startup: {e}")

    # [V17-R7] Lanzar tarea background de monitorización
    asyncio.create_task(_background_health())

    log.info("═" * 66)
    log.info(f" Niveles: {', '.join(RUTAS.keys())}")
    log.info(f" Clasificador: embed({len(_vectores_referencia)}) + {_phi4_model_activo or '⚠ sin LLM'}")
    log.info(f" RAG ChromaDB: {'✔ UUID=' + str(_chroma_collection_id)[:8] if _rag_disponible else '⚠ no disponible'}")
    log.info(f" PHI4 CPU: {'✔' if _phi4_cpu_available else '⚠ fallback a GPU'}")
    log.info(f" Log: {_LOG_FILE} (RotatingFileHandler 50MB×3)")
    log.info("═" * 66)


# ─────────────────────────────────────────────────────────────────────────────
# ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/")
async def raiz():
    return {
        "servicio": "OMEN AI Router V10",
        "build":    "V17",
        "version":  "10.17.0",
        "niveles":  list(RUTAS.keys()),
    }


@app.get("/health")
async def health():
    """[V14-4] Caché TTL 15s — evita N health-checks síncronos por polling de OpenClaw."""
    now = time.monotonic()
    if _health_cache["data"] and (now - _health_cache["ts"]) < _HEALTH_TTL:
        return _health_cache["data"]

    vistos:   dict[str, bool] = {}
    backends: dict[str, bool] = {}
    for n, r in RUTAS.items():
        url = r["health_url"]
        if url not in vistos:
            vistos[url] = await _health_ok(url)
        backends[n] = vistos[url]

    chroma_ok   = await _health_ok(f"{CHROMA_URL}/api/v1/heartbeat")
    searxng_ok  = await _health_ok("http://localhost:8888/search?q=test&format=json", timeout=4.0)
    obsidian_ok = await _health_ok("http://localhost:3000", timeout=4.0)
    embed_ok    = await _health_ok(EMBED_CPU_URL.replace("/api/embeddings", "/api/tags"))

    result = {
        "status":          "ok",
        "version":         "10.17.0",
        "ruta_activa":     _estado["ruta_activa"],
        "tabbyapi_model":  _estado["tabbyapi_modelo"],
        "backends":        backends,
        "herramientas": {
            "chromadb_rag":    chroma_ok,
            "searxng_web":     searxng_ok,
            "obsidian_ui":     obsidian_ok,
            "ollama_cpu_embed": embed_ok,
        },
        "clasificador": {
            "embed_vectores":  len(_vectores_referencia),
            "phi4_model":      _phi4_model_activo,
            "phi4_cpu_avail":  _phi4_cpu_available,
            "embed_threshold": EMBED_THRESHOLD,
        },
        "rag_disponible":     _rag_disponible,
        "chroma_collection":  _chroma_collection_id,
        "cache_entradas":     len(_cache),
    }
    _health_cache.update({"data": result, "ts": now})
    return result


@app.get("/metrics")
async def metrics():
    reqs = _metricas["requests_por_nivel"]
    lats = _metricas["latencia_total_ms"]
    return {
        "requests_por_nivel": dict(reqs),
        "errores_por_nivel":  dict(_metricas["errores_por_nivel"]),
        "fallbacks":          dict(_metricas["fallbacks"]),
        "latencia_prom_ms":   {n: round(lats[n] / max(1, reqs[n]), 1) for n in RUTAS},
        "cambios_vram":       _metricas["cambios_vram"],
        "rag_inyecciones":    _metricas["rag_inyecciones"],
        "clasificador_capas": dict(_metricas["clasificador_capas"]),
        "cache_hit_ratio": round(
            _metricas["clasificador_capas"]["cache"] /
            max(1, sum(_metricas["clasificador_capas"].values())), 3
        ),
    }


@app.get("/v1/models")
async def modelos():
    ts = int(time.time())
    catalog = [
        {"id": "ruteador-auto",        "name": "🤖 Auto — clasificador 4 capas",                   "ctx": 32768, "max": 16384},
        {"id": "chat",                  "name": "💬 Chat (Llama 3.1 8B EXL2)",                     "ctx": 8192,  "max": 4096},
        {"id": "instantaneo",           "name": "⚡ Instantáneo (Qwen2.5 Coder 7B)",               "ctx": 4096,  "max": 2048},
        {"id": "agil",                  "name": "🚀 Ágil (SGLang · agentes, documentos)",          "ctx": 32768, "max": 8192},
        {"id": "profundo",              "name": "🧠 Profundo (DeepSeek R1 14B)",                   "ctx": 16384, "max": 8192},
        {"id": "phi-mayor-precision",   "name": "🎯 Phi Mayor Precisión (phi4-reasoning:plus)",    "ctx": 16384, "max": 4096},
        {"id": "phi-optimizada",        "name": "⚡ Phi Optimizada (phi4-reasoning:14b-q4_K_M)",   "ctx": 16384, "max": 4096},
        {"id": "masivo",                "name": "🔬 Masivo (Qwen2.5 32B · análisis extenso)",     "ctx": 32768, "max": 16384},
        {"id": "codigo",                "name": "💻 Código → Inst. (Qwen Coder 7B)",              "ctx": 4096,  "max": 2048},
        {"id": "phi4",                  "name": "🔷 Phi-4 CPU (clasificador directo)",             "ctx": 16384, "max": 4096},
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
                "id":             m["id"],
                "object":         "model",
                "created":        ts,
                "owned_by":       "omen-local",
                "name":           m.get("name", ""),
                "context_window": m.get("ctx"),
                "max_tokens":     m.get("max"),
            }
            for m in catalog
        ],
    }


@app.post("/v1/chat/completions")
async def chat(request: Request):
    t0 = time.monotonic()

    body       = await request.json()
    modelo_raw = body.get("model", "ruteador-auto").strip()
    modelo_lower = modelo_raw.lower()
    mensajes   = body.get("messages", [])
    prompt     = mensajes[-1].get("content", "") if mensajes else ""
    streaming  = body.get("stream", False)
    agent_id   = request.headers.get("x-openclaw-agent", "").strip().lower()

    log.info(f"\n{'─'*66}")
    log.info(f"[REQ] modelo='{modelo_raw}' agente='{agent_id}' stream={streaming}")
    log.info(f"[PROMPT] {prompt[:130]}…")

    # ── Resolver nivel ─────────────────────────────────────────────────────
    nivel = ALIAS_A_NIVEL.get(modelo_lower)

    if nivel == "PHI4_DIRECTO":
        # [V17-R2] Verificar disponibilidad en CPU; si no → GPU
        log.info("[MODO] → Phi-4 CPU directo")
        if _phi4_cpu_available:
            target = PHI4_CPU_CHAT_URL
            phi4_model = _phi4_model_activo or "phi4-mini"
        else:
            log.warning("[V17-R2] phi4 no disponible en CPU — redirigiendo a GPU :11434")
            target = PHI4_GPU_CHAT_URL
            phi4_model = _phi4_model_activo or "phi4"
        body["model"] = phi4_model
        return await _proxy(body, target, request, streaming, nivel="CHAT")

    elif nivel is None:
        nivel, fuente = await _clasificar(prompt, agent_id)
        log.info(f"[MODO: AUTO] → {nivel} (fuente: {fuente})")
    else:
        log.info(f"[MODO: MANUAL] → {nivel}")
        async with _metricas_lock:
            _metricas["clasificador_capas"]["alias"] += 1

    # [V14-6] Auto-selección de PRECISO_OPT para prompts cortos
    if nivel == "PRECISO" and len(prompt) < 300:
        nivel = "PRECISO_OPT"
        log.info("[PRECISO_OPT] Prompt < 300 chars — usando variante optimizada")

    # ── RAG injection ───────────────────────────────────────────────────────
    body = await _rag_inject(body, prompt, nivel)

    # ── Conmutar VRAM ───────────────────────────────────────────────────────
    target_url = await _conmutar_vram(nivel)
    body["model"] = RUTAS[nivel]["modelo"]

    # ── Ajustes del body ────────────────────────────────────────────────────
    body = _inject_opciones_extra(body, nivel)
    body = _inject_thinking(body, nivel, body["model"])
    _check_tools(body, nivel, body["model"])

    log.info(f"[PROXY] {nivel} → '{body['model']}' @ {target_url}")

    # ── Métricas y envío ────────────────────────────────────────────────────
    async with _metricas_lock:
        _metricas["requests_por_nivel"][nivel] += 1
    try:
        result = await _proxy(body, target_url, request, streaming, nivel)
    except Exception as exc:
        async with _metricas_lock:
            _metricas["errores_por_nivel"][nivel] += 1
        raise exc

    async with _metricas_lock:
        _metricas["latencia_total_ms"][nivel] += (time.monotonic() - t0) * 1000
    return result


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run(
        "orchestrator_router_V10:app",
        host="0.0.0.0",
        port=8000,
        log_level="info",
        reload=False,
    )
