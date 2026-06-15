"""
╔══════════════════════════════════════════════════════════════════════════════╗
║ omen_router_modules/classifier.py — Clasificador de prompts (4 capas)       ║
║ OMEN AI Router V14 (build V21)                                              ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ Capa 0: agent_id header de OpenClaw                                         ║
║ Capa 1: LRU cache async con TTL                                             ║
║ Capa 2: Similitud coseno con vectores de referencia (embeddings)            ║
║ Capa 3: Phi-4-mini LLM fallback                                             ║
║ Default: PROFUNDO                                                            ║
║                                                                              ║
║ [V21-C1] Módulo separado para testabilidad.                                 ║
║ [V21-C2] Coseno optimizado con numpy (fallback a Python puro).              ║
║ [V21-C3] Cache con versionado (invalida al recalcular vectores).            ║
║ [V21-C4] deque para rate limiting en lugar de lista.                        ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import asyncio
import hashlib
import logging
import time
from collections import OrderedDict
from typing import Optional

import httpx

from .config import (
    AGENT_TO_NIVEL,
    EMBED_CPU_URL,
    EMBED_DESCRIPTIONS,
    EMBED_MODEL,
    EMBED_THRESHOLD,
    PHI4_CPU_TAGS,
    PHI4_CPU_URL,
    PHI4_FALLBACK,
    PHI4_MODEL,
    RUTAS,
    SYSTEM_PHI4,
)

# [V21-C2] Intentar usar numpy para coseno optimizado
try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False

log = logging.getLogger("omen-router.classifier")

# ─────────────────────────────────────────────────────────────────────────────
# ESTADO INTERNO
# ─────────────────────────────────────────────────────────────────────────────
_vectores_referencia: dict[str, list[float]] = {}
_phi4_model_activo: Optional[str] = None

# [V21-C3] Cache con versionado
_cache: OrderedDict = OrderedDict()
_cache_lock = asyncio.Lock()
_cache_version: int = 0
_CACHE_MAX = 256
_CACHE_TTL = 300.0  # 5 minutos

# Métricas del clasificador (referencia externa desde metrics module)
_clasificador_capas: dict = {
    "agente": 0,
    "cache": 0,
    "embed": 0,
    "phi4": 0,
    "default": 0,
    "alias": 0,
}
_capas_lock = asyncio.Lock()


# ─────────────────────────────────────────────────────────────────────────────
# COSENO — [V21-C2] Optimizado con numpy si disponible
# ─────────────────────────────────────────────────────────────────────────────
def coseno(a: list[float], b: list[float]) -> float:
    """Similitud coseno entre dos vectores. Usa numpy si está disponible."""
    if not a or not b or len(a) != len(b):
        return 0.0

    if _HAS_NUMPY:
        va = np.array(a, dtype=np.float32)
        vb = np.array(b, dtype=np.float32)
        dot = np.dot(va, vb)
        norm_a = np.linalg.norm(va)
        norm_b = np.linalg.norm(vb)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(dot / (norm_a * norm_b))

    # Fallback Python puro
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# ─────────────────────────────────────────────────────────────────────────────
# CACHE LRU ASYNC — [V21-C3] Con versionado
# ─────────────────────────────────────────────────────────────────────────────
def _cache_key(prompt: str, agent_id: str) -> str:
    """Genera clave de caché basada en hash del prompt + agent_id."""
    raw = f"{agent_id}::{prompt[:200]}"
    return hashlib.md5(raw.encode()).hexdigest()


async def cache_get(prompt: str, agent_id: str) -> Optional[str]:
    """Obtiene un nivel cacheado si existe y no ha expirado."""
    key = _cache_key(prompt, agent_id)
    async with _cache_lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        nivel, ts, version = entry
        # [V21-C3] Invalidar si la versión de vectores cambió
        if version != _cache_version:
            del _cache[key]
            return None
        if (time.monotonic() - ts) > _CACHE_TTL:
            del _cache[key]
            return None
        _cache.move_to_end(key)
        return nivel


async def cache_put(prompt: str, nivel: str, agent_id: str) -> None:
    """Almacena un resultado de clasificación en caché."""
    key = _cache_key(prompt, agent_id)
    async with _cache_lock:
        _cache[key] = (nivel, time.monotonic(), _cache_version)
        _cache.move_to_end(key)
        while len(_cache) > _CACHE_MAX:
            _cache.popitem(last=False)


def invalidate_cache() -> None:
    """[V21-C3] Invalida toda la caché incrementando la versión."""
    global _cache_version
    _cache_version += 1
    log.info(f"[CACHE] Invalidada (nueva versión: {_cache_version})")


# ─────────────────────────────────────────────────────────────────────────────
# PRECALCULAR VECTORES DE REFERENCIA
# ─────────────────────────────────────────────────────────────────────────────
async def precalcular_vectores(http_client: httpx.AsyncClient) -> int:
    """
    Precalcula los vectores de referencia para el clasificador de embeddings.
    Retorna el número de vectores calculados exitosamente.
    [V21-C3] Invalida caché al recalcular.
    """
    global _vectores_referencia
    ok_count = 0
    for nivel, desc in EMBED_DESCRIPTIONS.items():
        try:
            r = await http_client.post(
                EMBED_CPU_URL, json={"model": EMBED_MODEL, "prompt": desc}
            )
            if r.status_code == 200:
                embedding = r.json().get("embedding", [])
                if embedding:
                    _vectores_referencia[nivel] = embedding
                    ok_count += 1
        except Exception as e:
            log.warning(f"[EMBED] No se pudo vectorizar {nivel}: {e}")

    if ok_count > 0:
        invalidate_cache()

    log.info(f"[EMBED] {ok_count}/{len(EMBED_DESCRIPTIONS)} vectores de referencia precalculados")
    return ok_count


# ─────────────────────────────────────────────────────────────────────────────
# DETECTAR PHI4
# ─────────────────────────────────────────────────────────────────────────────
async def detectar_phi4(http_client: httpx.AsyncClient) -> Optional[str]:
    """Detecta qué modelo Phi-4 está disponible en la instancia CPU."""
    global _phi4_model_activo
    try:
        r = await http_client.get(PHI4_CPU_TAGS)
        if r.status_code == 200:
            modelos = [m["name"] for m in r.json().get("models", [])]
            if PHI4_MODEL in modelos:
                _phi4_model_activo = PHI4_MODEL
            elif PHI4_FALLBACK in modelos:
                _phi4_model_activo = PHI4_FALLBACK
    except Exception:
        pass
    return _phi4_model_activo


# ─────────────────────────────────────────────────────────────────────────────
# CLASIFICACIÓN POR EMBEDDINGS (Capa 2)
# ─────────────────────────────────────────────────────────────────────────────
async def clasificar_embeddings(
    prompt: str, http_client: httpx.AsyncClient
) -> Optional[str]:
    """Capa 2: similitud coseno con vectores de referencia."""
    if not _vectores_referencia:
        return None
    try:
        r = await http_client.post(
            EMBED_CPU_URL, json={"model": EMBED_MODEL, "prompt": prompt}
        )
        if r.status_code != 200:
            return None
        prompt_vec = r.json().get("embedding", [])
        if not prompt_vec:
            return None

        sims = {n: coseno(prompt_vec, v) for n, v in _vectores_referencia.items()}
        best_nivel, best_sim = max(sims.items(), key=lambda x: x[1])
        log.debug(f"[EMBED] best={best_nivel}({best_sim:.3f})")
        return best_nivel if best_sim >= EMBED_THRESHOLD else None
    except Exception as e:
        log.warning(f"[EMBED] Error: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# CLASIFICACIÓN POR PHI4 (Capa 3)
# ─────────────────────────────────────────────────────────────────────────────
async def clasificar_phi4(
    prompt: str, http_client: httpx.AsyncClient
) -> Optional[str]:
    """Capa 3: Phi-4-mini como fallback LLM."""
    if not _phi4_model_activo:
        return None
    try:
        r = await http_client.post(
            PHI4_CPU_URL,
            json={
                "model": _phi4_model_activo,
                "system": SYSTEM_PHI4,
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


# ─────────────────────────────────────────────────────────────────────────────
# CLASIFICADOR PRINCIPAL — 4 capas
# ─────────────────────────────────────────────────────────────────────────────
async def clasificar(
    prompt: str, agent_id: str, http_client: httpx.AsyncClient
) -> tuple[str, str]:
    """
    Clasificador de 4 capas:
      Capa 0: agent_id header de OpenClaw
      Capa 1: LRU cache (incluye agent_id)
      Capa 2: embeddings coseno
      Capa 3: Phi-4-mini LLM fallback
      Default: PROFUNDO
    """
    # Capa 0: agente OpenClaw
    if agent_id and agent_id in AGENT_TO_NIVEL:
        nivel = AGENT_TO_NIVEL[agent_id]
        async with _capas_lock:
            _clasificador_capas["agente"] += 1
        return nivel, "agente"

    # Capa 1: caché LRU
    cached = await cache_get(prompt, agent_id)
    if cached:
        async with _capas_lock:
            _clasificador_capas["cache"] += 1
        return cached, "cache"

    # Capa 2: embeddings
    nivel = await clasificar_embeddings(prompt, http_client)
    if nivel:
        await cache_put(prompt, nivel, agent_id)
        async with _capas_lock:
            _clasificador_capas["embed"] += 1
        return nivel, "embed"

    # Capa 3: Phi-4
    nivel = await clasificar_phi4(prompt, http_client)
    if nivel:
        await cache_put(prompt, nivel, agent_id)
        async with _capas_lock:
            _clasificador_capas["phi4"] += 1
        return nivel, "phi4"

    # Default
    async with _capas_lock:
        _clasificador_capas["default"] += 1
    return "PROFUNDO", "default"


def get_capas_stats() -> dict:
    """Retorna estadísticas de las capas del clasificador."""
    return dict(_clasificador_capas)


def get_cache_size() -> int:
    """Retorna el número de entradas en caché."""
    return len(_cache)


def get_phi4_model() -> Optional[str]:
    """Retorna el modelo Phi4 activo."""
    return _phi4_model_activo


def get_vectores_count() -> int:
    """Retorna el número de vectores de referencia precalculados."""
    return len(_vectores_referencia)
