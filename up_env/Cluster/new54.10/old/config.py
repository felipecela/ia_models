"""
╔══════════════════════════════════════════════════════════════════════════════╗
║ omen_router_modules/config.py — Configuración centralizada                  ║
║ OMEN AI Router V14 (build V26)                                              ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ Extraído del monolito orchestrator_router_V13.py para mejorar               ║
║ legibilidad, mantenibilidad y testabilidad.                                 ║
║                                                                              ║
║ [V21-R1] Módulo de configuración separado.                                  ║
║ [V21-R2] Todas las constantes validadas y documentadas.                     ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import os
import subprocess
from typing import Optional

# ─────────────────────────────────────────────────────────────────────────────
# FILESYSTEM DETECTION
# ─────────────────────────────────────────────────────────────────────────────
_UNSAFE_FS = frozenset({"exfat", "vfat", "fat32", "ntfs", "fuseblk"})


def detect_filesystem(path: str) -> str:
    """Detecta el tipo de filesystem de un directorio dado."""
    try:
        result = subprocess.run(
            ["df", "--output=fstype", path],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            lines = result.stdout.strip().split("\n")
            if len(lines) >= 2:
                return lines[1].strip().lower()
    except Exception:
        pass
    return "unknown"


def validate_db_dir(candidate: str) -> str:
    """
    Valida que el directorio de la DB está en un filesystem compatible.
    Si no, busca alternativa segura (ext4/tmpfs).
    Retorna la ruta segura a usar.
    """
    if os.path.isdir(candidate):
        fs = detect_filesystem(candidate)
        if fs not in _UNSAFE_FS:
            return candidate

    # Intentar crear
    if not os.path.exists(candidate):
        try:
            os.makedirs(candidate, exist_ok=True)
            fs = detect_filesystem(candidate)
            if fs not in _UNSAFE_FS:
                return candidate
        except OSError:
            pass

    # Fallback 1: $HOME/ai_cluster
    home_candidate = os.path.join(os.path.expanduser("~"), "ai_cluster")
    os.makedirs(home_candidate, exist_ok=True)
    fs = detect_filesystem(home_candidate)
    if fs not in _UNSAFE_FS:
        return home_candidate

    # Fallback 2: /tmp
    tmp_candidate = os.path.join("/tmp", "omen_agent_db")
    os.makedirs(tmp_candidate, exist_ok=True)
    return tmp_candidate


# ─────────────────────────────────────────────────────────────────────────────
# DIRECTORIO DE LA DB DEL AGENTE — [V21-R2] Lazy init post-validación
# ─────────────────────────────────────────────────────────────────────────────
_AGENT_DB_DIR_RAW = os.environ.get("AGENT_DB_DIR", os.path.join(os.path.expanduser("~"), "ai_cluster"))
AGENT_DB_DIR: str = validate_db_dir(_AGENT_DB_DIR_RAW)
DB_PATH: str = os.path.join(AGENT_DB_DIR, "agent_tasks.db")

# ─────────────────────────────────────────────────────────────────────────────
# URLS DE BACKENDS
# ─────────────────────────────────────────────────────────────────────────────
OLLAMA_GPU_URL = os.environ.get("OLLAMA_GPU_URL", "http://localhost:11434")
OLLAMA_CPU_URL = os.environ.get("OLLAMA_CPU_URL", "http://localhost:11435")
SGLANG_URL = os.environ.get("SGLANG_URL", "http://localhost:30000")
TABBYAPI_URL = os.environ.get("TABBYAPI_URL", "http://localhost:5000")
CHROMA_URL = os.environ.get("CHROMA_URL", "http://localhost:8001")
SEARXNG_URL = os.environ.get("SEARXNG_URL", "http://localhost:8888")

# Endpoints derivados
OLLAMA_GPU_CHAT = f"{OLLAMA_GPU_URL}/api/chat"
OLLAMA_GPU_GENERATE = f"{OLLAMA_GPU_URL}/api/generate"
OLLAMA_CPU_CHAT = f"{OLLAMA_CPU_URL}/api/chat"
OLLAMA_CPU_GENERATE = f"{OLLAMA_CPU_URL}/api/generate"
SGLANG_CHAT = f"{SGLANG_URL}/v1/chat/completions"
TABBYAPI_CHAT = f"{TABBYAPI_URL}/v1/chat/completions"
TABBYAPI_MODEL_LOAD = f"{TABBYAPI_URL}/v1/model/load"
TABBYAPI_MODEL_UNLOAD = f"{TABBYAPI_URL}/v1/model/unload"
TABBYAPI_MODELS = f"{TABBYAPI_URL}/v1/models"

# Embeddings
EMBED_CPU_URL = f"{OLLAMA_CPU_URL}/api/embeddings"
EMBED_MODEL = os.environ.get("EMBED_MODEL", "nomic-embed-text")
EMBED_THRESHOLD = float(os.environ.get("EMBED_THRESHOLD", "0.52"))

# Phi4 (clasificador LLM)
PHI4_CPU_URL = f"{OLLAMA_CPU_URL}/api/generate"
PHI4_CPU_CHAT_URL = f"{OLLAMA_CPU_URL}/api/chat"
PHI4_CPU_TAGS = f"{OLLAMA_CPU_URL}/api/tags"
PHI4_GPU_CHAT_URL = f"{OLLAMA_GPU_URL}/api/chat"
PHI4_MODEL = "phi4-mini"
PHI4_FALLBACK = "phi4:latest"

# ChromaDB RAG
CHROMA_COLLECTION = os.environ.get("CHROMA_COLLECTION", "obsidian_vault")
RAG_TOP_K = int(os.environ.get("RAG_TOP_K", "5"))
RAG_MAX_DIST = float(os.environ.get("RAG_MAX_DIST", "0.75"))
RAG_NIVELES = frozenset({"PROFUNDO", "AGIL", "MASIVO", "PRECISO", "PRECISO_OPT"})

# ─────────────────────────────────────────────────────────────────────────────
# RUTAS DE MODELOS — Tabla de enrutamiento principal (V26: Solo Ollama GPU) [V27-config]
# [V26-INFRA] Remapeo: TabbyAPI/SgLang desactivados → todo en Ollama GPU
# ─────────────────────────────────────────────────────────────────────────────
RUTAS: dict = {
    "CHAT": {
        "modelo": "phi4-mini:latest",
        "url": OLLAMA_GPU_CHAT,
        "backend": "ollama_gpu",
        "health_url": f"{OLLAMA_GPU_URL}/api/tags",
        "timeout_s": 60.0,
        "opciones_extra": {"temperature": 0.7, "max_tokens": 2048},  # [V27-C1] max_tokens → options.num_predict via proxy sanitize
    },
    "INSTANTANEO": {
        "modelo": "phi4-mini:latest",
        "url": OLLAMA_GPU_CHAT,
        "backend": "ollama_gpu",
        "health_url": f"{OLLAMA_GPU_URL}/api/tags",
        "timeout_s": 30.0,
        "opciones_extra": {"temperature": 0.3, "max_tokens": 1024},  # [V27-C1]
    },
    "AGIL": {
        "modelo": "phi4:latest",
        "url": OLLAMA_GPU_CHAT,
        "backend": "ollama_gpu",
        "health_url": f"{OLLAMA_GPU_URL}/api/tags",
        "timeout_s": 90.0,
        "opciones_extra": {"temperature": 0.6, "max_tokens": 4096},  # [V27-C1]
    },
    "PROFUNDO": {
        "modelo": "deepseek-r1:14b",
        "url": OLLAMA_GPU_CHAT,
        "backend": "ollama_gpu",
        "health_url": f"{OLLAMA_GPU_URL}/api/tags",
        "timeout_s": 180.0,
        "opciones_extra": {"temperature": 0.2},
    },
    "PRECISO": {
        "modelo": "phi4-reasoning:plus",
        "url": OLLAMA_GPU_CHAT,
        "backend": "ollama_gpu",
        "health_url": f"{OLLAMA_GPU_URL}/api/tags",
        "timeout_s": 150.0,
        "opciones_extra": {"temperature": 0.1},
    },
    "PRECISO_OPT": {
        "modelo": "phi4-reasoning:14b-q4_k_m",
        "url": OLLAMA_GPU_CHAT,
        "backend": "ollama_gpu",
        "health_url": f"{OLLAMA_GPU_URL}/api/tags",
        "timeout_s": 120.0,
        "opciones_extra": {"temperature": 0.1},
    },
    "MASIVO": {
        "modelo": "qwen2.5:32b",
        "url": OLLAMA_GPU_CHAT,
        "backend": "ollama_gpu",
        "health_url": f"{OLLAMA_GPU_URL}/api/tags",
        "timeout_s": 240.0,
        "opciones_extra": {"temperature": 0.4},
    },
    "CODIGO": {
        "modelo": "deepseek-coder-v2:latest",
        "url": OLLAMA_GPU_CHAT,
        "backend": "ollama_gpu",
        "health_url": f"{OLLAMA_GPU_URL}/api/tags",
        "timeout_s": 90.0,
        "opciones_extra": {"temperature": 0.2, "max_tokens": 3072},  # [V27-C1]
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# ALIAS → NIVEL (mapeo de model IDs a niveles de enrutamiento)
# ─────────────────────────────────────────────────────────────────────────────
ALIAS_A_NIVEL: dict = {
    # Auto-routing
    "ruteador-auto": None,
    "auto": None,
    # Niveles directos
    "chat": "CHAT",
    "instantaneo": "INSTANTANEO",
    "instantáneo": "INSTANTANEO",
    "agil": "AGIL",
    "ágil": "AGIL",
    "profundo": "PROFUNDO",
    "deep": "PROFUNDO",
    "preciso": "PRECISO",
    "phi-mayor-precision": "PRECISO",
    "phi-optimizada": "PRECISO_OPT",
    "masivo": "MASIVO",
    "massive": "MASIVO",
    "codigo": "CODIGO",
    "code": "CODIGO",
    # Modelos directos
    "deepseek-r1:14b": "PROFUNDO",
    "qwen2.5:32b": "MASIVO",
    "phi4-mini:latest": "CHAT",
    "phi4-mini": "CHAT",
    "phi4:latest": "AGIL",
    "phi4": "AGIL",
    "deepseek-coder-v2:latest": "CODIGO",
    "deepseek-coder-v2": "CODIGO",
    "phi4-reasoning:plus": "PRECISO",
    "phi4-reasoning:14b-q4_k_m": "PRECISO_OPT",
    # Modelos anteriores (legacy)
    "llama-3.1-8b-awq": "AGIL",
    "llama-3.1-8b-exl2": "CHAT",
    "qwen2.5-coder-7b-exl2": "CODIGO",
    # Phi4 directo
    "phi4-direct": "PHI4_DIRECTO",
    "phi4-mini": "PHI4_DIRECTO",
    # Agente autónomo
    "agent-autonomo": "AGENT",
    "agente": "AGENT",
}

# ─────────────────────────────────────────────────────────────────────────────
# TIMEOUT FALLBACK — [V21-R3] Con validación anti-ciclos
# ─────────────────────────────────────────────────────────────────────────────
_TIMEOUT_FALLBACK_RAW: dict = {
    "PROFUNDO": "AGIL",
    "MASIVO": "PROFUNDO",
    "PRECISO": "PRECISO_OPT",
    "AGIL": "CHAT",
}


def _validate_fallback_chain(fallbacks: dict) -> dict:
    """[V21-R3] Valida que no existan ciclos en la cadena de fallback."""
    for start in fallbacks:
        visited = {start}
        current = fallbacks.get(start)
        while current:
            if current in visited:
                raise ValueError(
                    f"Ciclo detectado en TIMEOUT_FALLBACK: {start} → ... → {current}"
                )
            visited.add(current)
            current = fallbacks.get(current)
    return fallbacks


TIMEOUT_FALLBACK: dict = _validate_fallback_chain(_TIMEOUT_FALLBACK_RAW)

# ─────────────────────────────────────────────────────────────────────────────
# AGENT ENGINE CONFIG
# ─────────────────────────────────────────────────────────────────────────────
MAX_ACTIVE_TASKS = int(os.environ.get("MAX_ACTIVE_TASKS", "3"))
MAX_PROMPT_LEN = int(os.environ.get("MAX_PROMPT_LEN", "10000"))
AGENT_CONTEXT_MAX_TOKENS = int(os.environ.get("AGENT_CONTEXT_MAX_TOKENS", "12000"))

# Mapeo agente OpenClaw → nivel
AGENT_TO_NIVEL: dict = {
    "research": "PROFUNDO",
    "code": "CODIGO",
    "creative": "AGIL",
    "quick": "INSTANTANEO",
    "analysis": "MASIVO",
    "precise": "PRECISO",
}

# ─────────────────────────────────────────────────────────────────────────────
# RATE LIMITING
# ─────────────────────────────────────────────────────────────────────────────
RATE_LIMIT_MAX = int(os.environ.get("RATE_LIMIT_MAX", "60"))
RATE_LIMIT_WINDOW = float(os.environ.get("RATE_LIMIT_WINDOW", "60.0"))

# ─────────────────────────────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────────────────────────────
LOG_DIR = os.environ.get("OMEN_LOG_DIR", os.path.join(os.path.expanduser("~"), "ai_cluster", "logs"))
LOG_FILE = os.path.join(LOG_DIR, "orchestrator_router.log")
LOG_MAX_BYTES = 50 * 1024 * 1024  # 50MB
LOG_BACKUP_COUNT = 3

# ─────────────────────────────────────────────────────────────────────────────
# HEALTH CHECK
# ─────────────────────────────────────────────────────────────────────────────
HEALTH_TTL = 15.0  # Segundos de caché del health check

# ─────────────────────────────────────────────────────────────────────────────
# CLASIFICADOR — Descripciones para vectores de referencia
# ─────────────────────────────────────────────────────────────────────────────
EMBED_DESCRIPTIONS: dict = {
    "CHAT": "conversación casual, saludo, pregunta simple, charla informal, respuesta corta",
    "INSTANTANEO": "pregunta rápida, definición, dato concreto, cálculo simple, traducción breve",
    "AGIL": "análisis de documento, resumen extenso, investigación, agente con herramientas, RAG",
    "PROFUNDO": "razonamiento complejo, matemáticas avanzadas, lógica formal, problema multi-paso, deducción",
    "PRECISO": "razonamiento preciso, verificación formal, demostración, análisis riguroso, corrección de pruebas",
    "MASIVO": "análisis masivo de datos, documento muy largo, comparación extensa, síntesis de múltiples fuentes",
    "CODIGO": "programación, código fuente, debugging, refactoring, script, función, algoritmo, API",
}

# System prompt para Phi4 clasificador
SYSTEM_PHI4: str = (
    "Eres un clasificador de prompts. Responde SOLO con UNA palabra: "
    "CHAT, INSTANTANEO, AGIL, PROFUNDO, PRECISO, MASIVO o CODIGO. "
    "CHAT=conversación simple. INSTANTANEO=pregunta rápida/dato. "
    "AGIL=análisis/documentos/agentes. PROFUNDO=razonamiento complejo/matemáticas. "
    "PRECISO=verificación rigurosa/formal. MASIVO=análisis extenso/múltiples fuentes. "
    "CODIGO=programación/código."
)
