#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║         OMEN AI CLUSTER — Orchestrador Semántico V6  (build V13)           ║
║         RTX 4070 8GB · Intel Ultra 7 · 32GB RAM · SSD exFAT               ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  V13 añade sobre V12:                                                        ║
║  ✔ [V13-A] Nivel PRECISO     → Phi-4-reasoning:plus        (máx exactitud) ║
║  ✔ [V13-A] Nivel PRECISO_OPT → Phi-4-reasoning:14b-q4_K_M (optimizada)    ║
║            Ambos con opciones CoT: temperature=0.6, top_p=0.95             ║
║  ✔ [V13-B] RAG injection desde ChromaDB (vault Obsidian)                   ║
║            Enriquece el contexto con notas locales antes de rutear         ║
║  ✔ [V13-C] Descripción PRECISO en clasificador 3-capas                     ║
║  ✔ [V13-D] /health refleja estado de ChromaDB y SearXNG                    ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Niveles completos V13:                                                      ║
║   CHAT        → TabbAPI :5000  llama-3.1-8b-exl2            (6.71GB VRAM)  ║
║   INSTANTANEO → TabbAPI :5000  qwen2.5-coder-7b-exl2        (6.95GB VRAM)  ║
║   AGIL        → SGLang  :30000 llama-3.1-8b-awq             (5.74GB VRAM)  ║
║   PROFUNDO    → Ollama  :11434 deepseek-r1:14b               (~7GB híb.)   ║
║   PRECISO     → Ollama  :11434 phi4-reasoning:plus           (~7.5GB híb.) ║
║   PRECISO_OPT → Ollama  :11434 phi4-reasoning:14b-q4_K_M    (~7GB híb.)   ║
║   MASIVO      → Ollama  :11434 qwen2.5:32b                   (8GB+11GB RAM)║
║                                                                              ║
║  Herramientas externas (consultadas por el router):                          ║
║   ChromaDB :8001 → RAG sobre vault Obsidian                                ║
║   SearXNG  :8888 → búsqueda web privada (vía plugin OpenClaw)              ║
║   Ollama CPU:11435 → nomic-embed-text + phi4-mini (clasificador)           ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import asyncio
import json
import logging
import time
from collections import Counter, OrderedDict
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
log = logging.getLogger("router-v6")

# ─────────────────────────────────────────────────────────────────────────────
#  RUTAS V13 — Arquitectura completa de 7 niveles de razonamiento
# ─────────────────────────────────────────────────────────────────────────────
RUTAS: dict[str, dict] = {

    # ── Nivel CHAT: conversación y preguntas generales ──────────────────────
    "CHAT": {
        "url":            "http://localhost:5000/v1/chat/completions",
        "health_url":     "http://localhost:5000/health",
        "modelo":         "llama-3.1-8b-exl2",
        "contenedor":     "exllamav2-api",
        "tabbyapi_swap":  True,
        "descripcion":    "Conversación casual, preguntas generales, traducciones",
        "vram_gb":        6.71,
        "context_window": 8192,
        "max_tokens":     4096,
        "timeout_s":      35.0,
        "opciones_extra": None,
    },

    # ── Nivel INSTANTANEO: código rápido ───────────────────────────────────
    "INSTANTANEO": {
        "url":            "http://localhost:5000/v1/chat/completions",
        "health_url":     "http://localhost:5000/health",
        "modelo":         "qwen2.5-coder-7b-exl2",
        "contenedor":     "exllamav2-api",
        "tabbyapi_swap":  True,
        "descripcion":    "Código rápido, snippets, funciones cortas, autocompletado",
        "vram_gb":        6.95,
        "context_window": 4096,
        "max_tokens":     2048,
        "timeout_s":      35.0,
        "opciones_extra": None,
    },

    # ── Nivel AGIL: agentes, documentos, contexto largo ────────────────────
    "AGIL": {
        "url":            "http://localhost:30000/v1/chat/completions",
        "health_url":     "http://localhost:30000/health",
        "modelo":         "llama-3.1-8b-awq",
        "contenedor":     "sglang-server",
        "tabbyapi_swap":  False,
        "descripcion":    "Agentes multi-paso, resúmenes, análisis de documentos",
        "vram_gb":        5.74,
        "context_window": 32768,
        "max_tokens":     8192,
        "timeout_s":      70.0,
        "opciones_extra": None,
    },

    # ── Nivel PROFUNDO: razonamiento y debugging ────────────────────────────
    "PROFUNDO": {
        "url":            "http://localhost:11434/v1/chat/completions",
        "health_url":     "http://localhost:11434/api/tags",
        "modelo":         "deepseek-r1:14b",
        "modelo_nuevo":   "deepseek-r1:8b-0528-qwen3",
        "contenedor":     None,
        "tabbyapi_swap":  False,
        "descripcion":    "Razonamiento profundo, debugging complejo, lógica general",
        "vram_gb":        7.0,
        "context_window": 16384,
        "max_tokens":     8192,
        "timeout_s":      130.0,
        "opciones_extra": None,
    },

    # ── [V13-A] Nivel PRECISO: Phi-4-reasoning:plus — máxima exactitud ─────
    "PRECISO": {
        "url":            "http://localhost:11434/v1/chat/completions",
        "health_url":     "http://localhost:11434/api/tags",
        "modelo":         "phi4-reasoning:plus",
        "contenedor":     None,
        "tabbyapi_swap":  False,
        "descripcion":    "Phi Mayor Precisión — matemáticas, STEM, lógica formal exacta",
        "vram_gb":        7.5,        # Híbrido GPU+RAM (11GB total)
        "context_window": 16384,
        "max_tokens":     4096,       # Limitado para controlar longitud del CoT
        "timeout_s":      200.0,      # CoT puede ser largo en 8GB
        # [V13-A] Parámetros recomendados por Microsoft para Phi-4-reasoning
        "opciones_extra": {
            "temperature": 0.6,
            "top_p": 0.95,
        },
    },

    # ── [V13-A] Nivel PRECISO_OPT: Phi-4-reasoning Q4_K_M — optimizada ─────
    "PRECISO_OPT": {
        "url":            "http://localhost:11434/v1/chat/completions",
        "health_url":     "http://localhost:11434/api/tags",
        "modelo":         "phi4-reasoning:14b-q4_K_M",
        "contenedor":     None,
        "tabbyapi_swap":  False,
        "descripcion":    "Phi Optimizada — STEM y ciencias, más rápida que :plus",
        "vram_gb":        7.0,
        "context_window": 16384,
        "max_tokens":     4096,
        "timeout_s":      160.0,
        "opciones_extra": {
            "temperature": 0.6,
            "top_p": 0.95,
        },
    },

    # ── Nivel MASIVO: análisis de documentos grandes ────────────────────────
    "MASIVO": {
        "url":            "http://localhost:11434/v1/chat/completions",
        "health_url":     "http://localhost:11434/api/tags",
        "modelo":         "qwen2.5:32b",
        "contenedor":     None,
        "tabbyapi_swap":  False,
        "descripcion":    "Análisis masivo: libros enteros, logs largos, codebases",
        "vram_gb":        8.0,
        "context_window": 32768,
        "max_tokens":     16384,
        "timeout_s":      320.0,
        "opciones_extra": None,
    },
}

# ─────────────────────────────────────────────────────────────────────────────
#  INCOMPATIBILIDADES DE VRAM
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
#  [V13-A] TIMEOUT-FALLBACK — bajada automática de nivel si el backend falla
# ─────────────────────────────────────────────────────────────────────────────
_TIMEOUT_FALLBACK: dict[str, str] = {
    "MASIVO":      "PROFUNDO",
    "PRECISO":     "PROFUNDO",      # phi4-reasoning:plus → deepseek-r1
    "PRECISO_OPT": "PROFUNDO",      # phi4-reasoning:q4   → deepseek-r1
    "PROFUNDO":    "AGIL",
    "INSTANTANEO": "CHAT",
}

# ─────────────────────────────────────────────────────────────────────────────
#  [V13-A] PRE-ROUTING POR AGENTE OPENCLAW (header X-OpenClaw-Agent)
# ─────────────────────────────────────────────────────────────────────────────
_AGENT_TO_NIVEL: dict[str, str] = {
    "coder":      "INSTANTANEO",
    "analyst":    "MASIVO",
    "reasoner":   "PRECISO",     # @reasoner → Phi-4-reasoning:plus
    "researcher": "AGIL",        # @researcher → SGLang (contexto largo para RAG+web)
}

# ─────────────────────────────────────────────────────────────────────────────
#  ALIAS MODELO → NIVEL (override manual desde OpenClaw o API)
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
    "codigo": "INSTANTANEO",   # "codigo" → INSTANTANEO (Qwen Coder 7B es el modelo de código)
    "coder": "INSTANTANEO",
    # AGIL
    "agil": "AGIL", "sglang": "AGIL", "llama-3.1-8b-awq": "AGIL",
    # PROFUNDO
    "profundo": "PROFUNDO", "deepseek-r1:14b": "PROFUNDO",
    "deepseek-r1": "PROFUNDO", "r1": "PROFUNDO",
    # [V13-A] PRECISO — Phi Mayor Precisión (phi4-reasoning:plus)
    "preciso": "PRECISO",
    "phi-mayor-precision": "PRECISO",
    "phi mayor precision": "PRECISO",
    "phi4-reasoning:plus": "PRECISO",
    "phi4-reasoning": "PRECISO",
    "phi-preciso": "PRECISO",
    # [V13-A] PRECISO_OPT — Phi Optimizada (phi4-reasoning:14b-q4_K_M)
    "preciso-opt": "PRECISO_OPT",
    "phi-optimizada": "PRECISO_OPT",
    "phi optimizada": "PRECISO_OPT",
    "phi4-reasoning:14b-q4_k_m": "PRECISO_OPT",
    "phi4-reasoning:14b-q4_k_m": "PRECISO_OPT",
    # MASIVO
    "masivo": "MASIVO", "qwen2.5:32b": "MASIVO", "qwen": "MASIVO",
    # PHI4 mini directo CPU (clasificador)
    "phi4": "PHI4_DIRECTO", "phi-4": "PHI4_DIRECTO",
    "phi4-mini": "PHI4_DIRECTO", "phi": "PHI4_DIRECTO",
}

# ─────────────────────────────────────────────────────────────────────────────
#  CLASIFICADOR — Capa 2: Embeddings (nomic-embed-text en CPU)
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
EMBED_THRESHOLD = 0.63     # Score mínimo para aceptar decisión de embeddings
EMBED_CPU_URL   = "http://localhost:11435/api/embeddings"

# ─────────────────────────────────────────────────────────────────────────────
#  CLASIFICADOR — Capa 3: Phi-4-mini como fallback LLM (CPU :11435)
# ─────────────────────────────────────────────────────────────────────────────
PHI4_CPU_URL  = "http://localhost:11435/api/generate"
PHI4_CPU_TAGS = "http://localhost:11435/api/tags"
PHI4_MODEL    = "phi4-mini"
PHI4_FALLBACK = "phi4"

# [V13-A] Sistema de clasificación actualizado con PRECISO
_SYSTEM_PHI4 = (
    "Eres un clasificador de tareas. Responde SOLO con una de estas palabras exactas:\n"
    "  CHAT — conversación casual, saludos, preguntas simples, traducciones cortas.\n"
    "  INSTANTANEO — código corto: snippets, funciones, autocompletado, Bash.\n"
    "  AGIL — resúmenes, agente multi-paso, análisis de archivos, contexto largo.\n"
    "  PROFUNDO — debugging complejo, diseño de sistemas, razonamiento lógico general.\n"
    "  PRECISO — matemáticas exactas (álgebra, cálculo, estadística), ciencias a nivel "
    "universitario o posgrado, lógica formal, problemas STEM con resultado numérico, física, química.\n"
    "  MASIVO — libros enteros, logs muy largos (>500 líneas), codebases completas.\n"
    "Responde SOLO la palabra. Sin puntuación. Sin explicación."
)

_phi4_model_activo: Optional[str] = None

# ─────────────────────────────────────────────────────────────────────────────
#  [V13-B] CONFIGURACIÓN RAG — ChromaDB
# ─────────────────────────────────────────────────────────────────────────────
CHROMA_URL        = "http://localhost:8001"
CHROMA_COLLECTION = "obsidian_vault"
RAG_TOP_K         = 4      # Fragmentos a recuperar del vault
RAG_MAX_DIST      = 0.35   # Distancia coseno máxima (0.35 ≈ similitud > 0.65)
RAG_NIVELES       = {"AGIL", "PROFUNDO", "PRECISO", "PRECISO_OPT", "MASIVO"}
# RAG no se aplica en CHAT/INSTANTANEO (demasiado rápidos para enriquecerlos)

_rag_disponible = False    # Se verifica en startup

# ─────────────────────────────────────────────────────────────────────────────
#  CACHÉ LRU DE DECISIONES (aplica a todas las capas del clasificador)
# ─────────────────────────────────────────────────────────────────────────────
_cache: OrderedDict[str, str] = OrderedDict()
_CACHE_MAX, _CACHE_KEY_LEN = 256, 300

def _cache_get(prompt: str) -> Optional[str]:
    k = prompt[:_CACHE_KEY_LEN]
    if k in _cache:
        _cache.move_to_end(k)
        return _cache[k]
    return None

def _cache_put(prompt: str, nivel: str):
    k = prompt[:_CACHE_KEY_LEN]
    if len(_cache) >= _CACHE_MAX:
        _cache.popitem(last=False)
    _cache[k] = nivel

# ─────────────────────────────────────────────────────────────────────────────
#  MÉTRICAS
# ─────────────────────────────────────────────────────────────────────────────
_metricas = {
    "requests_por_nivel":  Counter(),
    "errores_por_nivel":   Counter(),
    "fallbacks":           Counter(),
    "latencia_total_ms":   Counter(),
    "clasificador_capas":  Counter(),
    "rag_inyecciones":     0,
    "cambios_vram":        0,
}

# ─────────────────────────────────────────────────────────────────────────────
#  ESTADO GLOBAL
# ─────────────────────────────────────────────────────────────────────────────
_estado = {
    "ruta_activa":       None,
    "tabbyapi_modelo":   None,
    "tabbyapi_cargando": False,
}
_vectores_referencia: dict[str, list[float]] = {}

# ─────────────────────────────────────────────────────────────────────────────
#  DOCKER CLIENT
# ─────────────────────────────────────────────────────────────────────────────
try:
    _docker = docker.from_env()
    log.info("✔ Docker client conectado")
except Exception as _e:
    log.warning(f"⚠ Docker no disponible: {_e}")
    _docker = None

# ─────────────────────────────────────────────────────────────────────────────
#  UTILIDADES
# ─────────────────────────────────────────────────────────────────────────────
def _coseno(a: list[float], b: list[float]) -> float:
    dot   = sum(x * y for x, y in zip(a, b))
    mag_a = sum(x * x for x in a) ** 0.5
    mag_b = sum(x * x for x in b) ** 0.5
    return (dot / (mag_a * mag_b)) if mag_a and mag_b else 0.0

async def _health_ok(url: str, timeout: float = 3.0) -> bool:
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            return (await c.get(url)).status_code < 500
    except Exception:
        return False

async def _esperar_backend(url: str, intentos: int = 25, pausa: float = 2.5) -> bool:
    for i in range(intentos):
        if await _health_ok(url):
            return True
        log.info(f"  ⏳ Esperando {url} ({i+1}/{intentos})…")
        await asyncio.sleep(pausa)
    return False

# ─────────────────────────────────────────────────────────────────────────────
#  TABBYAPI MODEL SWITCHING (CHAT ↔ INSTANTANEO)
# ─────────────────────────────────────────────────────────────────────────────
async def _asegurar_modelo_tabbyapi(model_name: str) -> bool:
    if _estado["tabbyapi_modelo"] == model_name:
        return True
    if _estado["tabbyapi_cargando"]:
        for _ in range(30):
            await asyncio.sleep(3)
            if not _estado["tabbyapi_cargando"]:
                break
    _estado["tabbyapi_cargando"] = True
    log.info(f"[TABBYAPI] Cargando '{model_name}'…")
    try:
        async with httpx.AsyncClient(timeout=120.0) as c:
            r = await c.post(
                "http://localhost:5000/v1/model/load",
                json={"name": model_name, "max_seq_len": 4096, "cache_mode": "Q4"},
            )
        if r.status_code < 400:
            _estado["tabbyapi_modelo"] = model_name
            await _esperar_backend("http://localhost:5000/health", intentos=20, pausa=3.0)
            return True
        log.warning(f"[TABBYAPI] HTTP {r.status_code}: {r.text[:150]}")
        return False
    except Exception as exc:
        log.error(f"[TABBYAPI] Error: {exc}")
        return False
    finally:
        _estado["tabbyapi_cargando"] = False

# ─────────────────────────────────────────────────────────────────────────────
#  GESTIÓN DE VRAM (EXCLUSIÓN MUTUA)
# ─────────────────────────────────────────────────────────────────────────────
async def _conmutar_vram(nivel: str) -> str:
    ruta = RUTAS[nivel]
    if _docker:
        for nombre in _INCOMPATIBLES.get(nivel, []):
            try:
                c = _docker.containers.get(nombre)
                if c.status == "running":
                    log.info(f"[VRAM] Liberando: parando '{nombre}'…")
                    c.stop(timeout=8)
            except docker.errors.NotFound:
                pass
            except Exception as ex:
                log.warning(f"[VRAM] Error parando '{nombre}': {ex}")
        contenedor = ruta.get("contenedor")
        if contenedor:
            try:
                c = _docker.containers.get(contenedor)
                if c.status != "running":
                    log.info(f"[VRAM] Arrancando '{contenedor}'…")
                    c.start()
                    await _esperar_backend(ruta["health_url"])
            except docker.errors.NotFound:
                log.error(f"[VRAM] '{contenedor}' no existe. Ejecuta Autoboot_Cluster_V13.sh primero.")
            except Exception as ex:
                log.warning(f"[VRAM] Error arrancando '{contenedor}': {ex}")
    else:
        log.warning("[VRAM] Docker no disponible — asumiendo backends activos")
    if ruta.get("tabbyapi_swap"):
        await _asegurar_modelo_tabbyapi(ruta["modelo"])
    _estado["ruta_activa"] = nivel
    _metricas["cambios_vram"] += 1
    return ruta["url"]

# ─────────────────────────────────────────────────────────────────────────────
#  [V13-B] RAG INJECTION desde ChromaDB (vault Obsidian)
#  Se aplica en niveles AGIL, PROFUNDO, PRECISO, PRECISO_OPT y MASIVO.
#  Si ChromaDB no está disponible o no hay resultados relevantes, continúa sin RAG.
# ─────────────────────────────────────────────────────────────────────────────
async def _rag_inject(body: dict, prompt: str, nivel: str) -> dict:
    """Enriquece el contexto del prompt con fragmentos del vault de Obsidian."""
    if nivel not in RAG_NIVELES or not _rag_disponible:
        return body
    try:
        async with httpx.AsyncClient(timeout=6.0) as c:
            # Obtener embedding del prompt vía Ollama CPU
            r_emb = await c.post(
                EMBED_CPU_URL,
                json={"model": EMBED_MODEL, "prompt": prompt[:400]},
            )
            r_emb.raise_for_status()
            embedding = r_emb.json()["embedding"]

            # Buscar en ChromaDB por similitud coseno
            r_chroma = await c.post(
                f"{CHROMA_URL}/api/v1/collections/{CHROMA_COLLECTION}/query",
                json={
                    "query_embeddings": [embedding],
                    "n_results": RAG_TOP_K,
                    "include": ["documents", "metadatas", "distances"],
                },
            )
            r_chroma.raise_for_status()
            data  = r_chroma.json()
            docs  = data.get("documents",  [[]])[0]
            metas = data.get("metadatas",  [[]])[0]
            dists = data.get("distances",  [[]])[0]

            # Filtrar por umbral de distancia
            relevantes = [
                (d, m) for d, m, dist in zip(docs, metas, dists)
                if dist <= RAG_MAX_DIST and d.strip()
            ]

            if not relevantes:
                return body

            context_parts = [
                f"[Nota: {m.get('source','desconocida')}]\n{d}"
                for d, m in relevantes
            ]
            rag_block = (
                "=== CONTEXTO DE TU BASE DE CONOCIMIENTO LOCAL ===\n"
                + "\n\n".join(context_parts)
                + "\n=== FIN DEL CONTEXTO LOCAL ===\n\n"
                "Si alguno de los fragmentos anteriores es relevante para la pregunta, "
                "incorpóralo en tu respuesta citando el nombre del archivo fuente.\n"
            )

            msgs = body.get("messages", [])
            if msgs and msgs[0].get("role") == "system":
                msgs[0]["content"] = rag_block + msgs[0]["content"]
            else:
                msgs.insert(0, {"role": "system", "content": rag_block})
            body["messages"] = msgs

            _metricas["rag_inyecciones"] += 1
            log.info(f"[RAG] Inyectados {len(relevantes)} fragmentos del vault (dist≤{RAG_MAX_DIST})")

    except Exception as exc:
        log.debug(f"[RAG] No disponible o sin resultados: {exc}")
    return body

# ─────────────────────────────────────────────────────────────────────────────
#  [V13-A] INYECCIÓN DE OPCIONES EXTRA PARA PHI-4-REASONING
#  Controla la longitud del CoT y temperatura recomendada por Microsoft
# ─────────────────────────────────────────────────────────────────────────────
def _inject_opciones_extra(body: dict, nivel: str) -> dict:
    extras = RUTAS[nivel].get("opciones_extra")
    if not extras:
        return body
    # Sólo inyectar si el usuario no especificó options
    if "options" not in body:
        body["options"] = dict(extras)
    return body

# ─────────────────────────────────────────────────────────────────────────────
#  QWEN3 THINKING MODE — inyecta /think o /no_think según nivel
# ─────────────────────────────────────────────────────────────────────────────
def _inject_thinking(body: dict, nivel: str, modelo: str) -> dict:
    if "qwen3" not in modelo.lower():
        return body
    think_cmd = "/think" if nivel in ("PROFUNDO", "PRECISO", "PRECISO_OPT") else "/no_think"
    msgs = body.get("messages", [])
    if msgs and msgs[0].get("role") == "system":
        if "/think" not in msgs[0].get("content", "") and "/no_think" not in msgs[0].get("content", ""):
            msgs[0]["content"] = f"{think_cmd}\n{msgs[0]['content']}"
    else:
        msgs.insert(0, {"role": "system", "content": think_cmd})
    body["messages"] = msgs
    return body

# ─────────────────────────────────────────────────────────────────────────────
#  TOOL-CALLING AWARENESS
# ─────────────────────────────────────────────────────────────────────────────
def _check_tools(body: dict, nivel: str, modelo: str):
    if not body.get("tools"):
        return
    if nivel in ("INSTANTANEO", "CHAT"):
        log.warning(f"[TOOLS] TabbAPI/ExLlamaV2 no soporta function calling. "
                    "Usa AGIL o PROFUNDO para peticiones con tools.")
    elif "reasoning" in modelo.lower():
        log.info(f"[TOOLS] Phi-4-reasoning tiene soporte limitado de function calling. "
                 "Para tools complejas prefiere nivel AGIL (SGLang).")

# ─────────────────────────────────────────────────────────────────────────────
#  CLASIFICADOR — Capa 2: Embeddings con nomic-embed-text
# ─────────────────────────────────────────────────────────────────────────────
async def _precalcular_vectores():
    log.info("[EMBED] Precalculando vectores de referencia para 6 niveles…")
    ok_count = 0
    for nivel, desc in _EMBED_DESCRIPTIONS.items():
        try:
            async with httpx.AsyncClient(timeout=30.0) as c:
                r = await c.post(EMBED_CPU_URL, json={"model": EMBED_MODEL, "prompt": desc})
                r.raise_for_status()
                _vectores_referencia[nivel] = r.json()["embedding"]
                ok_count += 1
        except Exception as ex:
            log.warning(f"[EMBED] No se pudo precalcular '{nivel}': {ex}")
    log.info(f"[EMBED] {ok_count}/{len(_EMBED_DESCRIPTIONS)} vectores listos")

async def _clasificar_embeddings(prompt: str) -> tuple[Optional[str], float]:
    if not _vectores_referencia:
        return None, 0.0
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.post(EMBED_CPU_URL, json={"model": EMBED_MODEL, "prompt": prompt[:400]})
            r.raise_for_status()
            v = r.json()["embedding"]
        scores = {n: _coseno(v, ref) for n, ref in _vectores_referencia.items()}
        mejor = max(scores, key=scores.get)
        log.info("[EMBED] " + "  ".join(f"{k}={v:.3f}" for k, v in sorted(scores.items(), key=lambda x: -x[1])))
        return mejor, scores[mejor]
    except Exception as ex:
        log.warning(f"[EMBED] Error: {ex}")
        return None, 0.0

# ─────────────────────────────────────────────────────────────────────────────
#  CLASIFICADOR — Capa 3: Phi-4-mini en CPU
# ─────────────────────────────────────────────────────────────────────────────
async def _detectar_phi4() -> str:
    try:
        async with httpx.AsyncClient(timeout=8.0) as c:
            tags = (await c.get(PHI4_CPU_TAGS)).json()
            nombres = [m.get("name", "") for m in tags.get("models", [])]
            if any("phi4-mini" in n for n in nombres):
                log.info("✔ phi4-mini disponible como clasificador LLM")
                return "phi4-mini"
            if any("phi4" in n for n in nombres):
                log.info("⚠ Usando phi4 como fallback clasificador (instala phi4-mini para mayor velocidad)")
                return PHI4_FALLBACK
    except Exception:
        pass
    log.warning("⚠ phi4/phi4-mini no encontrado. Clasificador LLM desactivado.")
    return ""

async def _clasificar_phi4(prompt: str) -> str:
    if not _phi4_model_activo:
        return "AGIL"
    payload = {
        "model": _phi4_model_activo,
        "prompt": f"{_SYSTEM_PHI4}\n\nPetición: {prompt[:500]}\nClasificación:",
        "stream": False,
        "options": {"temperature": 0.0, "num_predict": 12, "num_gpu": 0},
    }
    try:
        async with httpx.AsyncClient(timeout=35.0) as c:
            r = await c.post(PHI4_CPU_URL, json=payload)
            r.raise_for_status()
            raw = r.json().get("response", "AGIL").strip().upper()
        for nivel in ("CHAT", "INSTANTANEO", "AGIL", "PROFUNDO", "PRECISO", "MASIVO"):
            if nivel in raw:
                # PRECISO en texto cubre tanto PRECISO como PRECISO_OPT: usamos PRECISO (plus) por defecto
                return nivel
        return "AGIL"
    except Exception as exc:
        log.error(f"[PHI4] Error: {exc}. Fallback a AGIL.")
        return "AGIL"

# ─────────────────────────────────────────────────────────────────────────────
#  CLASIFICADOR PRINCIPAL — 3 capas encadenadas
# ─────────────────────────────────────────────────────────────────────────────
async def _clasificar(prompt: str, agent_id: str = "") -> tuple[str, str]:
    # Capa 0: Agente OpenClaw (0ms)
    if agent_id and agent_id in _AGENT_TO_NIVEL:
        nivel = _AGENT_TO_NIVEL[agent_id]
        _metricas["clasificador_capas"]["agente"] += 1
        return nivel, f"agente({agent_id})"
    # Capa 1: Caché (0ms)
    if cached := _cache_get(prompt):
        _metricas["clasificador_capas"]["cache"] += 1
        return cached, "cache"
    # Capa 2: Embeddings (~26ms)
    nivel_e, score = await _clasificar_embeddings(prompt)
    if nivel_e and score >= EMBED_THRESHOLD:
        _cache_put(prompt, nivel_e)
        _metricas["clasificador_capas"]["embedding"] += 1
        return nivel_e, f"embed({score:.2f})"
    # Capa 3: Phi-4-mini (~700ms)
    log.info(f"[CLASE] Score {score:.3f} < {EMBED_THRESHOLD} → Phi-4 LLM")
    nivel_p = await _clasificar_phi4(prompt)
    _cache_put(prompt, nivel_p)
    _metricas["clasificador_capas"]["phi4"] += 1
    return nivel_p, "phi4"

# ─────────────────────────────────────────────────────────────────────────────
#  PROXY HTTP CON FALLBACK DINÁMICO POR TIMEOUT
# ─────────────────────────────────────────────────────────────────────────────
async def _proxy(body: dict, target_url: str, request: Request,
                 streaming: bool, nivel: str) -> StreamingResponse | JSONResponse:
    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in ("host", "content-length", "transfer-encoding")
    }
    headers["content-type"] = "application/json"
    timeout_s = RUTAS[nivel]["timeout_s"]

    async def _gen():
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s, connect=12.0)) as c:
                async with c.stream("POST", target_url, json=body, headers=headers) as r:
                    if r.status_code >= 400:
                        raw = await r.aread()
                        yield f'data: {{"error":"Backend {r.status_code}: {raw.decode()[:200]}"}}\n\n'.encode()
                        return
                    async for chunk in r.aiter_bytes(chunk_size=4096):
                        if chunk:
                            yield chunk
        except httpx.ConnectError as e:
            yield f'data: {{"error":"Backend no disponible: {e}"}}\n\n'.encode()
        except httpx.TimeoutException:
            yield f'data: {{"error":"Timeout ({timeout_s}s) en nivel {nivel}"}}\n\n'.encode()
        except Exception as e:
            yield f'data: {{"error":"Error proxy: {e}"}}\n\n'.encode()

    if streaming:
        return StreamingResponse(_gen(), media_type="text/event-stream")

    # No-streaming: con fallback por timeout/error
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s, connect=12.0)) as c:
            resp = await c.post(target_url, json=body, headers=headers)
        full = resp.content
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        log.warning(f"[FALLBACK] {nivel} → {type(exc).__name__}")
        fb = _TIMEOUT_FALLBACK.get(nivel)
        if fb:
            _metricas["fallbacks"][nivel] += 1
            fb_url = await _conmutar_vram(fb)
            body["model"] = RUTAS[fb]["modelo"]
            return await _proxy(body, fb_url, request, streaming=False, nivel=fb)
        return JSONResponse({"error": f"Nivel {nivel} no disponible y sin fallback"}, status_code=503)

    try:
        return JSONResponse(content=json.loads(full))
    except json.JSONDecodeError:
        pass
    for line in reversed(full.decode("utf-8", errors="replace").splitlines()):
        line = line.strip()
        if line.startswith("data: ") and "[DONE]" not in line:
            try:
                return JSONResponse(content=json.loads(line[6:]))
            except Exception:
                pass
    return JSONResponse({"error": "No se pudo parsear la respuesta del backend"}, status_code=502)

# ─────────────────────────────────────────────────────────────────────────────
#  FASTAPI APP
# ─────────────────────────────────────────────────────────────────────────────
app = FastAPI(title="OMEN AI Router V6 — Build V13", version="6.13.0")


@app.on_event("startup")
async def _startup():
    global _phi4_model_activo, _rag_disponible

    _phi4_model_activo = await _detectar_phi4()
    await _precalcular_vectores()

    # Verificar ChromaDB para RAG
    try:
        async with httpx.AsyncClient(timeout=4.0) as c:
            r = await c.get(f"{CHROMA_URL}/api/v1/heartbeat")
            _rag_disponible = r.status_code < 400
    except Exception:
        _rag_disponible = False

    log.info("═" * 66)
    log.info(f"  OMEN Router V6 (build V13) listo en http://0.0.0.0:8000")
    log.info(f"  Niveles: CHAT · INSTANTANEO · AGIL · PROFUNDO · PRECISO · PRECISO_OPT · MASIVO")
    log.info(f"  Clasificador: embed({len(_vectores_referencia)}) + {_phi4_model_activo or '⚠ sin LLM'}")
    log.info(f"  RAG ChromaDB: {'✔ ACTIVO' if _rag_disponible else '⚠ no disponible (ejecuta ChromaDB)'}")
    log.info("═" * 66)


@app.get("/")
async def raiz():
    return {
        "servicio": "OMEN AI Router V6",
        "build":    "V13",
        "version":  "6.13.0",
        "niveles":  list(RUTAS.keys()),
    }


@app.get("/health")
async def health():
    vistos: dict[str, bool] = {}
    backends: dict[str, bool] = {}
    for n, r in RUTAS.items():
        url = r["health_url"]
        if url not in vistos:
            vistos[url] = await _health_ok(url)
        backends[n] = vistos[url]

    chroma_ok  = await _health_ok(f"{CHROMA_URL}/api/v1/heartbeat")
    searxng_ok = await _health_ok("http://localhost:8888/search?q=test&format=json", timeout=4.0)
    obsidian_ok= await _health_ok("http://localhost:3000", timeout=4.0)
    embed_ok   = await _health_ok(EMBED_CPU_URL.replace("/api/embeddings", "/api/tags"))

    return {
        "status":         "ok",
        "version":        "6.13.0",
        "ruta_activa":    _estado["ruta_activa"],
        "tabbyapi_model": _estado["tabbyapi_modelo"],
        "backends":       backends,
        "herramientas": {
            "chromadb_rag":    chroma_ok,
            "searxng_web":     searxng_ok,
            "obsidian_ui":     obsidian_ok,
            "ollama_cpu_embed": embed_ok,
        },
        "clasificador": {
            "embed_vectores":  len(_vectores_referencia),
            "phi4_model":      _phi4_model_activo,
            "embed_threshold": EMBED_THRESHOLD,
        },
        "rag_disponible":  _rag_disponible,
        "cache_entradas":  len(_cache),
    }


@app.get("/metrics")
async def metrics():
    reqs = _metricas["requests_por_nivel"]
    lats = _metricas["latencia_total_ms"]
    return {
        "requests_por_nivel":  dict(reqs),
        "errores_por_nivel":   dict(_metricas["errores_por_nivel"]),
        "fallbacks":           dict(_metricas["fallbacks"]),
        "latencia_prom_ms":    {n: round(lats[n]/max(1,reqs[n]),1) for n in RUTAS},
        "cambios_vram":        _metricas["cambios_vram"],
        "rag_inyecciones":     _metricas["rag_inyecciones"],
        "clasificador_capas":  dict(_metricas["clasificador_capas"]),
        "cache_hit_ratio":     round(
            _metricas["clasificador_capas"]["cache"] /
            max(1, sum(_metricas["clasificador_capas"].values())), 3
        ),
    }


@app.get("/v1/models")
async def modelos():
    ts = int(time.time())
    catalog = [
        # ── Nombres amigables para OpenClaw ────────────────────────────────
        {"id": "ruteador-auto",       "name": "🤖 Auto — clasificador 3 capas",              "ctx": 32768, "max": 16384},
        {"id": "chat",                "name": "💬 Chat (Llama 3.1 8B EXL2)",                  "ctx": 8192,  "max": 4096},
        {"id": "instantaneo",         "name": "⚡ Instantáneo (Qwen2.5 Coder 7B)",             "ctx": 4096,  "max": 2048},
        {"id": "agil",                "name": "🚀 Ágil (SGLang · agentes, documentos)",        "ctx": 32768, "max": 8192},
        {"id": "profundo",            "name": "🧠 Profundo (DeepSeek R1 14B)",                 "ctx": 16384, "max": 8192},
        # [V13-A] Phi-4-reasoning — dos variantes con nombres de usuario
        {"id": "phi-mayor-precision", "name": "🎯 Phi Mayor Precisión (phi4-reasoning:plus)",  "ctx": 16384, "max": 4096},
        {"id": "phi-optimizada",      "name": "⚡ Phi Optimizada (phi4-reasoning:14b-q4_K_M)","ctx": 16384, "max": 4096},
        {"id": "masivo",              "name": "🔬 Masivo (Qwen2.5 32B · análisis extenso)",    "ctx": 32768, "max": 16384},
        {"id": "codigo",              "name": "💻 Código → Inst. (Qwen Coder 7B)",             "ctx": 4096,  "max": 2048},
        {"id": "phi4",                "name": "🔷 Phi-4 CPU (clasificador directo)",            "ctx": 16384, "max": 4096},
        # ── Aliases técnicos ────────────────────────────────────────────────
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

    body         = await request.json()
    modelo_raw   = body.get("model", "ruteador-auto").strip()
    modelo_lower = modelo_raw.lower()
    mensajes     = body.get("messages", [])
    prompt       = mensajes[-1].get("content", "") if mensajes else ""
    streaming    = body.get("stream", False)
    agent_id     = request.headers.get("x-openclaw-agent", "").strip().lower()

    log.info(f"\n{'─'*66}")
    log.info(f"[REQ] modelo='{modelo_raw}'  agente='{agent_id}'  stream={streaming}")
    log.info(f"[PROMPT] {prompt[:130]}…")

    # ── Resolver nivel ────────────────────────────────────────────────────
    nivel = ALIAS_A_NIVEL.get(modelo_lower)

    if nivel == "PHI4_DIRECTO":
        log.info("[MODO] → Phi-4 CPU directo")
        body["model"] = _phi4_model_activo or "phi4"
        target = PHI4_CPU_URL.replace("/api/generate", "/v1/chat/completions")
        return await _proxy(body, target, request, streaming, nivel="CHAT")

    elif nivel is None:
        nivel, fuente = await _clasificar(prompt, agent_id)
        log.info(f"[MODO: AUTO] → {nivel}  (fuente: {fuente})")
    else:
        log.info(f"[MODO: MANUAL] → {nivel}")
        _metricas["clasificador_capas"]["alias"] += 1

    # ── [V13-B] RAG injection ──────────────────────────────────────────────
    body = await _rag_inject(body, prompt, nivel)

    # ── Conmutar VRAM ─────────────────────────────────────────────────────
    target_url = await _conmutar_vram(nivel)
    body["model"] = RUTAS[nivel]["modelo"]

    # ── [V13-A] Opciones extra para Phi-4-reasoning ───────────────────────
    body = _inject_opciones_extra(body, nivel)

    # ── Qwen3 thinking mode ───────────────────────────────────────────────
    body = _inject_thinking(body, nivel, body["model"])

    # ── Tool-calling awareness ────────────────────────────────────────────
    _check_tools(body, nivel, body["model"])

    log.info(f"[PROXY] {nivel} → '{body['model']}' @ {target_url}")

    # ── Enviar y medir ────────────────────────────────────────────────────
    _metricas["requests_por_nivel"][nivel] += 1
    try:
        result = await _proxy(body, target_url, request, streaming, nivel)
    except Exception as exc:
        _metricas["errores_por_nivel"][nivel] += 1
        raise exc

    _metricas["latencia_total_ms"][nivel] += (time.monotonic() - t0) * 1000
    return result


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    log.info("═" * 66)
    log.info("  OMEN AI Router V6 (build V13)  →  http://0.0.0.0:8000")
    log.info("  GET  /            info del router")
    log.info("  GET  /health      estado completo (backends + herramientas)")
    log.info("  GET  /metrics     métricas de uso por nivel")
    log.info("  GET  /v1/models   catálogo con contextWindow")
    log.info("  POST /v1/chat/completions  proxy inteligente 3 capas + RAG")
    log.info("═" * 66)
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")
