#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════╗
║         OMEN AI CLUSTER — Orchestrador Semántico V6                     ║
║         Hardware: RTX 4070 8GB VRAM · Intel Ultra 7 · 32GB RAM          ║
╠══════════════════════════════════════════════════════════════════════════╣
║  Mejoras V6 sobre V5 (según análisis V12):                              ║
║  ✔ [M1] Clasificador 3 capas: Agente→Embeddings→Phi-4-mini              ║
║         ~0ms / ~26ms / ~0.7s — 132x más rápido que Phi-4 full          ║
║  ✔ [M2] Nivel CHAT separado (llama-3.1-8b-exl2) + INSTANTANEO=Coder    ║
║         TabbAPI con carga dinámica de modelo vía /v1/model/load         ║
║  ✔ [M3] Re-routing dinámico por timeout: MASIVO→PROFUNDO→AGIL           ║
║  ✔ [M4] Pre-routing por header X-OpenClaw-Agent (0ms, sin LLM)         ║
║  ✔ [M5] Endpoint /metrics con contadores por nivel y latencia           ║
║  ✔ [M6] Qwen3 thinking mode: inyecta /think o /no_think automático      ║
║  ✔ [M7] Tool-calling awareness con warning para modelos sin soporte     ║
║  ✔ [M8] contextWindow por nivel en /v1/models                           ║
║                                                                          ║
║  Niveles en V6:                                                          ║
║    CHAT        → TabbAPI :5000  llama-3.1-8b-exl2   (6.71GB)           ║
║    INSTANTANEO → TabbAPI :5000  qwen2.5-coder-7b    (6.95GB)           ║
║    AGIL        → SGLang  :30000 llama-3.1-8b-awq    (5.74GB)           ║
║    PROFUNDO    → Ollama  :11434 deepseek-r1:14b/*    (~7GB híb.)        ║
║    MASIVO      → Ollama  :11434 qwen2.5:32b          (8GB+11GB RAM)     ║
║  * Si deepseek-r1:8b-0528-qwen3 está instalado se usa en su lugar       ║
╚══════════════════════════════════════════════════════════════════════════╝

Mapa de puertos:
  :5000  → TabbAPI/ExLlamaV2    (CHAT + INSTANTANEO — model switching)
  :8000  → Este router           (entrada única para OpenClaw)
  :11434 → Ollama GPU            (PROFUNDO + MASIVO)
  :11435 → Ollama CPU-only       (nomic-embed-text + Phi-4-mini)
  :30000 → SGLang RadixAttention (AGIL)
"""

import asyncio
import json
import logging
import os
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
#  ARQUITECTURA DE RUTAS V6
#  NOTA: CHAT e INSTANTANEO usan el mismo contenedor (exllamav2-api)
#  pero con modelos diferentes — el router gestiona el switching via TabbAPI
# ─────────────────────────────────────────────────────────────────────────────
RUTAS: dict[str, dict] = {
    "CHAT": {
        "url":            "http://localhost:5000/v1/chat/completions",
        "health_url":     "http://localhost:5000/health",
        "modelo":         "llama-3.1-8b-exl2",
        "contenedor":     "exllamav2-api",
        "tabbyapi_swap":  True,   # Requiere carga dinámica de modelo
        "descripcion":    "Conversación casual, preguntas generales, traducciones",
        "vram_gb":        6.71,
        "context_window": 8192,
        "max_tokens":     4096,
        "timeout_s":      30.0,
    },
    "INSTANTANEO": {
        "url":            "http://localhost:5000/v1/chat/completions",
        "health_url":     "http://localhost:5000/health",
        "modelo":         "qwen2.5-coder-7b-exl2",
        "contenedor":     "exllamav2-api",
        "tabbyapi_swap":  True,
        "descripcion":    "Código rápido, snippets, autocompletado, funciones cortas",
        "vram_gb":        6.95,
        "context_window": 4096,
        "max_tokens":     2048,
        "timeout_s":      30.0,
    },
    "AGIL": {
        "url":            "http://localhost:30000/v1/chat/completions",
        "health_url":     "http://localhost:30000/health",
        "modelo":         "llama-3.1-8b-awq",
        "contenedor":     "sglang-server",
        "tabbyapi_swap":  False,
        "descripcion":    "Agentes, resúmenes, documentos largos, contexto multi-archivo",
        "vram_gb":        5.74,
        "context_window": 32768,
        "max_tokens":     8192,
        "timeout_s":      60.0,
    },
    "PROFUNDO": {
        "url":            "http://localhost:11434/v1/chat/completions",
        "health_url":     "http://localhost:11434/api/tags",
        "modelo":         "deepseek-r1:14b",    # Se detecta R1-0528 en runtime
        "modelo_nuevo":   "deepseek-r1:8b-0528-qwen3",  # Si disponible, se usa
        "contenedor":     None,    # Servicio nativo systemd
        "tabbyapi_swap":  False,
        "descripcion":    "Razonamiento profundo, matemáticas, debugging complejo",
        "vram_gb":        7.0,
        "context_window": 16384,
        "max_tokens":     8192,
        "timeout_s":      120.0,
    },
    "MASIVO": {
        "url":            "http://localhost:11434/v1/chat/completions",
        "health_url":     "http://localhost:11434/api/tags",
        "modelo":         "qwen2.5:32b",
        "contenedor":     None,
        "tabbyapi_swap":  False,
        "descripcion":    "Análisis masivo: libros, logs largos, codebases completas",
        "vram_gb":        8.0,
        "context_window": 32768,
        "max_tokens":     16384,
        "timeout_s":      300.0,
    },
}

# ─────────────────────────────────────────────────────────────────────────────
#  [M3] TIMEOUT-FALLBACK: si el nivel actual falla, bajar un escalón
# ─────────────────────────────────────────────────────────────────────────────
_TIMEOUT_FALLBACK: dict[str, str] = {
    "MASIVO":      "PROFUNDO",   # Qwen 32B demasiado lento → DeepSeek R1
    "PROFUNDO":    "AGIL",       # DeepSeek R1 saturado → SGLang
    "INSTANTANEO": "CHAT",       # Qwen Coder no cargó → Llama general
}

# ─────────────────────────────────────────────────────────────────────────────
#  [M4] MAPEO AGENTE OPENCLAW → NIVEL (pre-routing sin LLM)
# ─────────────────────────────────────────────────────────────────────────────
_AGENT_TO_NIVEL: dict[str, str] = {
    "coder":    "INSTANTANEO",
    "analyst":  "MASIVO",
    "reasoner": "PROFUNDO",
}

# ─────────────────────────────────────────────────────────────────────────────
#  ALIAS DE MODELO → NIVEL (manual override desde OpenClaw)
# ─────────────────────────────────────────────────────────────────────────────
ALIAS_A_NIVEL: dict[str, Optional[str]] = {
    # Auto-routing (None = clasificador decide)
    "ruteador-auto": None, "auto": None, "default": None,
    # CHAT
    "chat": "CHAT", "llama-3.1-8b-exl2": "CHAT", "llama3.1": "CHAT",
    # INSTANTANEO
    "instantaneo": "INSTANTANEO", "instant": "INSTANTANEO",
    "exllama": "INSTANTANEO", "tabby": "INSTANTANEO",
    "qwen2.5-coder-7b-exl2": "INSTANTANEO", "coder": "INSTANTANEO",
    "codigo": "INSTANTANEO",   # Alias CODIGO → INSTANTANEO (Qwen Coder 7B)
    # AGIL
    "agil": "AGIL", "sglang": "AGIL", "llama-3.1-8b-awq": "AGIL",
    # PROFUNDO
    "profundo": "PROFUNDO", "deepseek-r1:14b": "PROFUNDO",
    "deepseek-r1": "PROFUNDO", "r1": "PROFUNDO",
    # MASIVO
    "masivo": "MASIVO", "qwen2.5:32b": "MASIVO", "qwen": "MASIVO",
    # PHI4 directo en CPU
    "phi4": "PHI4_DIRECTO", "phi-4": "PHI4_DIRECTO",
    "phi4-mini": "PHI4_DIRECTO", "phi": "PHI4_DIRECTO",
}

# ─────────────────────────────────────────────────────────────────────────────
#  [M1] CLASIFICADOR — CAPA 2: Descripciones de referencia para embeddings
# ─────────────────────────────────────────────────────────────────────────────
_EMBED_DESCRIPTIONS: dict[str, str] = {
    "CHAT":
        "conversación casual saludos preguntas simples respuestas cortas "
        "chit-chat traducciones explicaciones sencillas",
    "INSTANTANEO":
        "completar código escribir función snippet corto líneas de código "
        "Python C C++ Bash autocompletado tab-completion refactoring rápido",
    "AGIL":
        "resumir documento analizar archivo agente multi-paso contexto largo "
        "leer correos múltiples documentos extraer información mantener contexto",
    "PROFUNDO":
        "razonamiento matemático paso a paso demostración debuggear error complejo "
        "memory leak race condition algoritmo lógica avanzada resolver problema difícil",
    "MASIVO":
        "analizar libro entero miles de líneas logs de sistema codebase completo "
        "revisar proyecto completo documento muy largo cientos de páginas gran volumen",
}

EMBED_MODEL = "nomic-embed-text"
EMBED_THRESHOLD = 0.65       # Score mínimo de confianza para aceptar embedding
EMBED_CPU_URL = "http://localhost:11435/api/embeddings"

# ─────────────────────────────────────────────────────────────────────────────
#  [M1] CLASIFICADOR — CAPA 3: Phi-4-mini como fallback LLM (CPU)
# ─────────────────────────────────────────────────────────────────────────────
PHI4_CPU_URL   = "http://localhost:11435/api/generate"
PHI4_CPU_TAGS  = "http://localhost:11435/api/tags"
PHI4_MODEL     = "phi4-mini"     # Preferido (3.8B). Si no está, usar "phi4"
PHI4_FALLBACK  = "phi4"          # Ya descargado (9.1GB), por si phi4-mini no está

_phi4_model_activo: Optional[str] = None   # Se detecta en startup

_SYSTEM_PHI4 = (
    "Eres un clasificador de tareas. Responde SOLO con una de estas palabras exactas:\n"
    "  CHAT — conversación casual, saludos, preguntas simples, traducciones cortas.\n"
    "  INSTANTANEO — código corto: snippets, funciones, autocompletado, Bash.\n"
    "  AGIL — resúmenes, agente multi-paso, análisis de archivos, contexto largo.\n"
    "  PROFUNDO — razonamiento matemático, debugging complejo, lógica avanzada.\n"
    "  MASIVO — libros enteros, logs muy largos, codebases completas.\n"
    "Responde SOLO la palabra. Sin puntuación. Sin explicación."
)

# ─────────────────────────────────────────────────────────────────────────────
#  CACHÉ LRU DE DECISIONES (aplica a todas las capas del clasificador)
# ─────────────────────────────────────────────────────────────────────────────
_cache: OrderedDict[str, str] = OrderedDict()
_CACHE_MAX = 256
_CACHE_KEY_LEN = 300

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
#  [M5] MÉTRICAS DE USO POR NIVEL
# ─────────────────────────────────────────────────────────────────────────────
_metricas = {
    "requests_por_nivel":   Counter(),
    "errores_por_nivel":    Counter(),
    "fallbacks_por_nivel":  Counter(),
    "latencia_total_ms":    Counter(),
    "clasificador_capas":   Counter(),  # embedding / phi4-mini / agente / cache / alias
    "cambios_vram":         0,
}

# ─────────────────────────────────────────────────────────────────────────────
#  ESTADO GLOBAL DE LA VRAM Y TABBYAPI
# ─────────────────────────────────────────────────────────────────────────────
_estado = {
    "ruta_activa": None,
    "tabbyapi_modelo": None,       # Modelo actualmente cargado en TabbAPI
    "tabbyapi_cargando": False,    # Lock para evitar cargas paralelas
}

# ─────────────────────────────────────────────────────────────────────────────
#  VECTORES DE REFERENCIA (calculados en startup)
# ─────────────────────────────────────────────────────────────────────────────
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
#  INCOMPATIBILIDADES DE VRAM
#  CHAT e INSTANTANEO comparten contenedor — SGLang incompatible con TabbAPI
# ─────────────────────────────────────────────────────────────────────────────
_INCOMPATIBLES: dict[str, list[str]] = {
    "CHAT":        ["sglang-server"],
    "INSTANTANEO": ["sglang-server"],
    "AGIL":        ["exllamav2-api"],
    "PROFUNDO":    ["exllamav2-api", "sglang-server"],
    "MASIVO":      ["exllamav2-api", "sglang-server"],
}

# ─────────────────────────────────────────────────────────────────────────────
#  UTILIDADES: COSENO DE SIMILITUD (sin numpy para mínimas dependencias)
# ─────────────────────────────────────────────────────────────────────────────
def _coseno(a: list[float], b: list[float]) -> float:
    dot   = sum(x * y for x, y in zip(a, b))
    mag_a = sum(x * x for x in a) ** 0.5
    mag_b = sum(x * x for x in b) ** 0.5
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)

# ─────────────────────────────────────────────────────────────────────────────
#  HEALTH CHECK
# ─────────────────────────────────────────────────────────────────────────────
async def _health_ok(url: str, timeout: float = 3.0) -> bool:
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.get(url)
            return r.status_code < 500
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
#  [M2] TABBYAPI MODEL SWITCHING
#  Permite usar CHAT (llama-3.1-8b) e INSTANTANEO (qwen-coder) en el mismo :5000
# ─────────────────────────────────────────────────────────────────────────────
async def _asegurar_modelo_tabbyapi(model_name: str) -> bool:
    """Carga el modelo en TabbAPI si no es el actualmente activo."""
    if _estado["tabbyapi_modelo"] == model_name:
        return True  # Ya está cargado

    if _estado["tabbyapi_cargando"]:
        # Esperar a que termine la carga en curso (máx 90s)
        for _ in range(30):
            await asyncio.sleep(3)
            if not _estado["tabbyapi_cargando"]:
                break

    _estado["tabbyapi_cargando"] = True
    log.info(f"[TABBYAPI] Cargando modelo '{model_name}'…")
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(
                "http://localhost:5000/v1/model/load",
                json={"name": model_name, "max_seq_len": 4096, "cache_mode": "Q4"},
            )
        if r.status_code < 400:
            _estado["tabbyapi_modelo"] = model_name
            # Esperar a que el modelo esté listo
            await _esperar_backend("http://localhost:5000/health", intentos=20, pausa=3.0)
            ok_flag = True
        else:
            log.warning(f"[TABBYAPI] Carga devolvió HTTP {r.status_code}: {r.text[:200]}")
            ok_flag = False
    except Exception as exc:
        log.error(f"[TABBYAPI] Error al cargar {model_name}: {exc}")
        ok_flag = False
    finally:
        _estado["tabbyapi_cargando"] = False
    return ok_flag

# ─────────────────────────────────────────────────────────────────────────────
#  GESTIÓN DE VRAM (EXCLUSIÓN MUTUA)
# ─────────────────────────────────────────────────────────────────────────────
async def _conmutar_vram(nivel: str) -> str:
    ruta = RUTAS[nivel]

    if _docker:
        # Parar contenedores incompatibles
        for nombre in _INCOMPATIBLES.get(nivel, []):
            try:
                c = _docker.containers.get(nombre)
                if c.status == "running":
                    log.info(f"[VRAM] Liberando: parando '{nombre}'…")
                    c.stop(timeout=8)
            except docker.errors.NotFound:
                pass
            except Exception as ex:
                log.warning(f"[VRAM] No se pudo parar '{nombre}': {ex}")

        # Arrancar el contenedor del destino (si aplica)
        contenedor = ruta.get("contenedor")
        if contenedor:
            try:
                c = _docker.containers.get(contenedor)
                if c.status != "running":
                    log.info(f"[VRAM] Activando: arrancando '{contenedor}'…")
                    c.start()
                    await _esperar_backend(ruta["health_url"])
            except docker.errors.NotFound:
                log.error(f"[VRAM] '{contenedor}' no existe. ¿Ejecutaste Autoboot_Cluster_V12.sh?")
            except Exception as ex:
                log.warning(f"[VRAM] Error con '{contenedor}': {ex}")
    else:
        log.warning("[VRAM] Docker no disponible — asumiendo backends ya activos")

    # [M2] Si el nivel usa TabbAPI, asegurar que el modelo correcto está cargado
    if ruta.get("tabbyapi_swap"):
        await _asegurar_modelo_tabbyapi(ruta["modelo"])

    _estado["ruta_activa"] = nivel
    _metricas["cambios_vram"] += 1
    return ruta["url"]

# ─────────────────────────────────────────────────────────────────────────────
#  [M1] CAPA 2 DEL CLASIFICADOR: Embeddings con nomic-embed-text
# ─────────────────────────────────────────────────────────────────────────────
async def _precalcular_vectores():
    """Precalcula embeddings de referencia al arrancar el router."""
    global _vectores_referencia
    log.info("[EMBED] Precalculando vectores de referencia con nomic-embed-text…")
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
    log.info(f"[EMBED] {ok_count}/{len(_EMBED_DESCRIPTIONS)} vectores precalculados")

async def _clasificar_con_embeddings(prompt: str) -> tuple[Optional[str], float]:
    """
    Clasifica el prompt usando similitud coseno contra vectores de referencia.
    Retorna (nivel, score_maximo). Score < EMBED_THRESHOLD = baja confianza.
    """
    if not _vectores_referencia:
        return None, 0.0
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.post(EMBED_CPU_URL, json={"model": EMBED_MODEL, "prompt": prompt[:400]})
            r.raise_for_status()
            v_prompt = r.json()["embedding"]

        scores = {nivel: _coseno(v_prompt, v_ref) for nivel, v_ref in _vectores_referencia.items()}
        mejor_nivel = max(scores, key=scores.get)
        mejor_score = scores[mejor_nivel]
        log.info(f"[EMBED] Scores: {', '.join(f'{k}={v:.3f}' for k,v in sorted(scores.items(), key=lambda x: -x[1]))}")
        return mejor_nivel, mejor_score
    except Exception as ex:
        log.warning(f"[EMBED] Error en clasificación: {ex}")
        return None, 0.0

# ─────────────────────────────────────────────────────────────────────────────
#  [M1] CAPA 3 DEL CLASIFICADOR: Phi-4-mini como fallback LLM
# ─────────────────────────────────────────────────────────────────────────────
async def _detectar_phi4_disponible() -> str:
    """Detecta si phi4-mini está disponible; si no, usa phi4."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(PHI4_CPU_TAGS)
            tags = r.json()
            nombres = [m.get("name", "") for m in tags.get("models", [])]
            if any("phi4-mini" in n for n in nombres):
                log.info(f"[PHI4] ✔ Usando phi4-mini como clasificador LLM (más rápido)")
                return "phi4-mini"
            elif any("phi4" in n for n in nombres):
                log.info(f"[PHI4] ⚠ phi4-mini no encontrado, usando phi4 como fallback")
                return "phi4"
    except Exception:
        pass
    log.warning("[PHI4] No se pudo detectar phi4/phi4-mini. Clasificador LLM desactivado.")
    return ""

async def _clasificar_con_phi4mini(prompt: str) -> str:
    """Fallback LLM: usa Phi-4-mini en CPU cuando embedding score < umbral."""
    if not _phi4_model_activo:
        return "AGIL"

    payload = {
        "model": _phi4_model_activo,
        "prompt": f"{_SYSTEM_PHI4}\n\nPetición: {prompt[:500]}\nClasificación:",
        "stream": False,
        "options": {"temperature": 0.0, "num_predict": 10, "num_gpu": 0},
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as c:
            r = await c.post(PHI4_CPU_URL, json=payload)
            r.raise_for_status()
            raw = r.json().get("response", "AGIL").strip().upper()

        for nivel in ("CHAT", "INSTANTANEO", "AGIL", "PROFUNDO", "MASIVO"):
            if nivel in raw:
                return nivel
        log.warning(f"[PHI4] Respuesta no reconocida: '{raw}', fallback a AGIL")
        return "AGIL"
    except Exception as ex:
        log.error(f"[PHI4] Error: {ex}. Fallback a AGIL.")
        return "AGIL"

# ─────────────────────────────────────────────────────────────────────────────
#  [M1] CLASIFICADOR PRINCIPAL — 3 capas
# ─────────────────────────────────────────────────────────────────────────────
async def _clasificar(prompt: str, agent_id: str = "") -> tuple[str, str]:
    """
    Retorna (nivel, fuente) donde fuente indica qué capa tomó la decisión.

    Capa 0 — Agente OpenClaw (header X-OpenClaw-Agent): ~0ms
    Capa 1 — Caché LRU: ~0ms
    Capa 2 — Embeddings nomic-embed-text: ~26ms
    Capa 3 — Phi-4-mini (CPU): ~700ms
    """
    # Capa 0: Agente de OpenClaw
    if agent_id and agent_id in _AGENT_TO_NIVEL:
        nivel = _AGENT_TO_NIVEL[agent_id]
        log.info(f"[CLASE-AGENTE] '{agent_id}' → {nivel}")
        _metricas["clasificador_capas"]["agente"] += 1
        return nivel, "agente"

    # Capa 1: Caché
    cached = _cache_get(prompt)
    if cached:
        log.info(f"[CLASE-CACHE] Hit → {cached}")
        _metricas["clasificador_capas"]["cache"] += 1
        return cached, "cache"

    # Capa 2: Embeddings
    t0 = time.monotonic()
    nivel_embed, score = await _clasificar_con_embeddings(prompt)
    t_embed = (time.monotonic() - t0) * 1000
    log.info(f"[CLASE-EMBED] '{nivel_embed}' score={score:.3f} ({t_embed:.0f}ms)")

    if nivel_embed and score >= EMBED_THRESHOLD:
        _cache_put(prompt, nivel_embed)
        _metricas["clasificador_capas"]["embedding"] += 1
        return nivel_embed, f"embed({score:.2f})"

    # Capa 3: Phi-4-mini
    log.info(f"[CLASE-PHI4] Score {score:.3f} < {EMBED_THRESHOLD} → consultando {_phi4_model_activo}")
    t0 = time.monotonic()
    nivel_phi4 = await _clasificar_con_phi4mini(prompt)
    t_phi4 = (time.monotonic() - t0) * 1000
    log.info(f"[CLASE-PHI4] '{nivel_phi4}' ({t_phi4:.0f}ms)")
    _cache_put(prompt, nivel_phi4)
    _metricas["clasificador_capas"]["phi4"] += 1
    return nivel_phi4, f"phi4({t_phi4:.0f}ms)"

# ─────────────────────────────────────────────────────────────────────────────
#  [M6] QWEN3 THINKING MODE
#  Inyecta /think o /no_think en el system prompt según el nivel
# ─────────────────────────────────────────────────────────────────────────────
def _inyectar_thinking(body: dict, nivel: str, modelo: str) -> dict:
    """Para modelos Qwen3, activa chain-of-thought en PROFUNDO y lo desactiva en otros."""
    if "qwen3" not in modelo.lower():
        return body

    think_cmd = "/think" if nivel == "PROFUNDO" else "/no_think"
    msgs = body.get("messages", [])

    if msgs and msgs[0].get("role") == "system":
        content = msgs[0].get("content", "")
        if "/think" not in content and "/no_think" not in content:
            msgs[0]["content"] = f"{think_cmd}\n{content}"
    else:
        msgs.insert(0, {"role": "system", "content": think_cmd})

    body["messages"] = msgs
    log.info(f"[QWEN3] Inyectado '{think_cmd}' para nivel {nivel}")
    return body

# ─────────────────────────────────────────────────────────────────────────────
#  [M7] TOOL-CALLING AWARENESS
# ─────────────────────────────────────────────────────────────────────────────
def _verificar_tools(body: dict, nivel: str, modelo: str):
    """Advierte si el request usa tools pero el modelo puede no soportarlas."""
    if not body.get("tools"):
        return
    if nivel in ("PROFUNDO", "MASIVO") and "r1" in modelo and "0528" not in modelo:
        log.warning(
            f"[TOOLS] Modelo '{modelo}' puede no soportar function calling. "
            f"Considera migrar a deepseek-r1:8b-0528-qwen3 (sección 4.1 del análisis V12)."
        )
    elif nivel in ("INSTANTANEO", "CHAT"):
        log.warning(
            f"[TOOLS] TabbAPI/ExLlamaV2 no soporta function calling. "
            f"Considera usar nivel AGIL (SGLang) o PROFUNDO (Ollama) para peticiones con tools."
        )

# ─────────────────────────────────────────────────────────────────────────────
#  PROXY HTTP CON STREAMING Y [M3] FALLBACK POR TIMEOUT
# ─────────────────────────────────────────────────────────────────────────────
async def _hacer_proxy(
    body: dict,
    target_url: str,
    request: Request,
    streaming: bool,
    nivel: str,
) -> StreamingResponse | JSONResponse:
    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in ("host", "content-length", "transfer-encoding")
    }
    headers["content-type"] = "application/json"
    timeout_s = RUTAS[nivel]["timeout_s"]

    async def _gen():
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(timeout_s, connect=12.0)
            ) as c:
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

    # No-streaming: acumular y devolver JSON; implementar fallback por timeout
    chunks: list[bytes] = []
    connection_failed = False

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_s, connect=12.0)
        ) as c:
            resp = await c.post(target_url, json=body, headers=headers)
            chunks.append(resp.content)
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        log.warning(f"[FALLBACK] {nivel} falló ({type(exc).__name__}): {exc}")
        connection_failed = True

    # [M3] Si falló, intentar nivel de fallback
    if connection_failed:
        fallback_nivel = _TIMEOUT_FALLBACK.get(nivel)
        if fallback_nivel:
            log.info(f"[FALLBACK] Reintentando con {fallback_nivel}…")
            _metricas["fallbacks_por_nivel"][nivel] += 1
            fallback_url = await _conmutar_vram(fallback_nivel)
            body_fb = dict(body)
            body_fb["model"] = RUTAS[fallback_nivel]["modelo"]
            return await _hacer_proxy(body_fb, fallback_url, request, streaming=False, nivel=fallback_nivel)
        return JSONResponse(
            content={"error": f"Nivel {nivel} no disponible y sin fallback configurado"},
            status_code=503,
        )

    full = b"".join(chunks)
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
    return JSONResponse(content={"error": "No se pudo parsear la respuesta del backend"}, status_code=502)

# ─────────────────────────────────────────────────────────────────────────────
#  FASTAPI APP
# ─────────────────────────────────────────────────────────────────────────────
app = FastAPI(title="OMEN AI Router V6", version="6.0.0")


@app.on_event("startup")
async def _startup():
    """Inicialización async: detectar Phi-4, precalcular vectores de embedding."""
    global _phi4_model_activo
    _phi4_model_activo = await _detectar_phi4_disponible()
    await _precalcular_vectores()
    log.info("═" * 62)
    log.info("  Router V6 listo. Clasificador activo:")
    log.info(f"    Capa 2: Embeddings ({EMBED_MODEL}) — umbral {EMBED_THRESHOLD}")
    log.info(f"    Capa 3: {_phi4_model_activo or '⚠ NO DISPONIBLE'}")
    log.info("═" * 62)


@app.get("/")
async def raiz():
    return {"servicio": "OMEN AI Router V6", "endpoints": ["/health", "/metrics", "/v1/models", "/v1/chat/completions"]}


@app.get("/health")
async def endpoint_health():
    """Estado de todos los backends y del clasificador."""
    backends: dict[str, bool] = {}
    vistos = set()
    for nombre, ruta in RUTAS.items():
        url = ruta["health_url"]
        if url not in vistos:
            backends[nombre] = await _health_ok(url)
            vistos.add(url)
        else:
            backends[nombre] = backends.get(next(n for n, r in RUTAS.items() if r["health_url"] == url), False)

    embed_ok = await _health_ok(EMBED_CPU_URL.replace("/api/embeddings", "/api/tags"))
    phi4_ok  = bool(_phi4_model_activo) and embed_ok

    return {
        "status": "ok",
        "version": "6.0.0",
        "ruta_activa": _estado["ruta_activa"],
        "tabbyapi_modelo": _estado["tabbyapi_modelo"],
        "backends": backends,
        "clasificador": {
            "embed_model": EMBED_MODEL,
            "embed_vectores": len(_vectores_referencia),
            "phi4_model": _phi4_model_activo,
            "phi4_disponible": phi4_ok,
            "embed_threshold": EMBED_THRESHOLD,
        },
        "cache_decisiones": len(_cache),
    }


@app.get("/metrics")
async def endpoint_metrics():
    """[M5] Métricas de uso por nivel: requests, errores, latencia, fallbacks."""
    niveles = list(RUTAS.keys())
    reqs = _metricas["requests_por_nivel"]
    lats = _metricas["latencia_total_ms"]

    latencia_promedio = {}
    for n in niveles:
        if reqs[n] > 0:
            latencia_promedio[n] = round(lats[n] / reqs[n], 1)
        else:
            latencia_promedio[n] = 0.0

    return {
        "requests_por_nivel":       dict(reqs),
        "errores_por_nivel":        dict(_metricas["errores_por_nivel"]),
        "fallbacks_por_nivel":      dict(_metricas["fallbacks_por_nivel"]),
        "latencia_promedio_ms":     latencia_promedio,
        "cambios_vram_total":       _metricas["cambios_vram"],
        "clasificador_capas":       dict(_metricas["clasificador_capas"]),
        "cache_hit_ratio":          (
            round(_metricas["clasificador_capas"]["cache"] /
                  max(1, sum(_metricas["clasificador_capas"].values())), 3)
        ),
    }


@app.get("/v1/models")
async def endpoint_modelos():
    """[M8] Catálogo de modelos con contextWindow y maxTokens (compatible con OpenClaw)."""
    ts = int(time.time())
    catalog = [
        {"id": "ruteador-auto",        "name": "🤖 Auto — clasificador 3 capas",
         "context_window": 32768, "max_tokens": 16384},
        {"id": "chat",                  "name": "💬 Chat (Llama 3.1 8B EXL2)",
         "context_window": 8192,  "max_tokens": 4096},
        {"id": "instantaneo",           "name": "⚡ Instantáneo (Qwen2.5 Coder 7B)",
         "context_window": 4096,  "max_tokens": 2048},
        {"id": "agil",                  "name": "🚀 Ágil (SGLang · agentes y documentos)",
         "context_window": 32768, "max_tokens": 8192},
        {"id": "profundo",              "name": "🧠 Profundo (DeepSeek R1 14B / 0528)",
         "context_window": 16384, "max_tokens": 8192},
        {"id": "masivo",                "name": "🔬 Masivo (Qwen2.5 32B · análisis completo)",
         "context_window": 32768, "max_tokens": 16384},
        {"id": "codigo",                "name": "💻 Código → Instantáneo (Qwen Coder 7B)",
         "context_window": 4096,  "max_tokens": 2048},
        {"id": "phi4",                  "name": "🔷 Phi-4 CPU (clasificador directo)",
         "context_window": 16384, "max_tokens": 4096},
        # Aliases técnicos
        {"id": "deepseek-r1:14b"},
        {"id": "qwen2.5:32b"},
        {"id": "llama-3.1-8b-awq"},
        {"id": "qwen2.5-coder-7b-exl2"},
        {"id": "llama-3.1-8b-exl2"},
    ]
    return {
        "object": "list",
        "data": [
            {
                "id": m["id"],
                "object": "model",
                "created": ts,
                "owned_by": "omen-local",
                "context_window": m.get("context_window"),
                "max_tokens": m.get("max_tokens"),
                "name": m.get("name", ""),
            }
            for m in catalog
        ],
    }


@app.post("/v1/chat/completions")
async def endpoint_chat(request: Request):
    t_inicio = time.monotonic()

    body = await request.json()
    modelo_raw   = body.get("model", "ruteador-auto").strip()
    modelo_lower = modelo_raw.lower()
    mensajes     = body.get("messages", [])
    prompt       = mensajes[-1].get("content", "") if mensajes else ""
    es_streaming = body.get("stream", False)

    # [M4] Header de agente OpenClaw
    agent_id = request.headers.get("x-openclaw-agent", "").strip().lower()

    log.info(f"\n{'─'*64}")
    log.info(f"[REQ] modelo='{modelo_raw}'  agente='{agent_id}'  stream={es_streaming}")
    log.info(f"[PROMPT] {prompt[:120]}…")

    # ── Resolver nivel ────────────────────────────────────────────────────
    nivel = ALIAS_A_NIVEL.get(modelo_lower)

    if nivel == "PHI4_DIRECTO":
        # Phi-4 CPU directo (sin VRAM)
        log.info("[MODO] → Phi-4 CPU directo")
        body["model"] = _phi4_model_activo or "phi4"
        target = PHI4_CPU_URL.replace("/api/generate", "/v1/chat/completions")
        result = await _hacer_proxy(body, target, request, es_streaming, nivel="CHAT")
        return result

    elif nivel is None:
        # Auto-routing: clasificador 3 capas
        nivel, fuente = await _clasificar(prompt, agent_id)
        log.info(f"[MODO: AUTO] → {nivel} (fuente: {fuente})")

    else:
        log.info(f"[MODO: MANUAL] → {nivel}")
        _metricas["clasificador_capas"]["alias"] += 1

    # ── Conmutar VRAM y obtener URL destino ───────────────────────────────
    target_url = await _conmutar_vram(nivel)
    body["model"] = RUTAS[nivel]["modelo"]

    # [M6] Qwen3 thinking mode
    body = _inyectar_thinking(body, nivel, body["model"])

    # [M7] Tool-calling awareness
    _verificar_tools(body, nivel, body["model"])

    log.info(f"[PROXY] {nivel} → '{body['model']}' @ {target_url}")

    # ── Métricas: iniciar conteo ─────────────────────────────────────────
    _metricas["requests_por_nivel"][nivel] += 1

    try:
        result = await _hacer_proxy(body, target_url, request, es_streaming, nivel=nivel)
    except Exception as exc:
        _metricas["errores_por_nivel"][nivel] += 1
        raise exc

    # Registrar latencia
    latencia_ms = (time.monotonic() - t_inicio) * 1000
    _metricas["latencia_total_ms"][nivel] += latencia_ms
    log.info(f"[DONE] {nivel} → {latencia_ms:.0f}ms")

    return result


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    log.info("═" * 64)
    log.info("  OMEN AI Router V6  —  http://0.0.0.0:8000")
    log.info("  Endpoints:")
    log.info("    GET  /           → info del router")
    log.info("    GET  /health     → estado de todos los backends")
    log.info("    GET  /metrics    → métricas por nivel [NUEVO V6]")
    log.info("    GET  /v1/models  → catálogo con contextWindow [NUEVO V6]")
    log.info("    POST /v1/chat/completions → proxy inteligente 3 capas")
    log.info("═" * 64)
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")
