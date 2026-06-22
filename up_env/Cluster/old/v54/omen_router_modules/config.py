#!/usr/bin/env python3
"""
omen_router_modules/config.py — Configuración centralizada
OMEN AI Router V14 (build V27)

[V21-R1] Módulo de configuración separado.
[V21-R2] Todas las constantes validadas y documentadas.
[V26-INFRA] Remapeo: TabbyAPI/SgLang desactivados -> todo en Ollama GPU.
[V27-C1] FIX: "phi4-mini" alias conflictivo eliminado (apuntaba a PHI4_DIRECTO
         sobreescribiendo la entrada CHAT). Ahora una sola entrada -> CHAT.
         PHI4_DIRECTO solo via "phi4-direct" / "phi4-directo".
[V27-C2] FIX: opciones_extra con max_tokens migrado a options.num_predict.
         Ollama ignora max_tokens en root del body.
         Las rutas CHAT/INSTANTANEO/AGIL/CODIGO usan sub-dict "options".
[V27-C3] FIX: LOG_FILE -> router_v14.log (unifica con redireccion Autoboot).
[V27-C4] FIX: URLs con 127.0.0.1 explicito (evita resolucion IPv6 localhost).
"""

import os
import subprocess

# ---------------------------------------------------------------------------
# FILESYSTEM DETECTION
# ---------------------------------------------------------------------------
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
    Valida que el directorio de la DB esta en un filesystem compatible.
    Si no, busca alternativa segura (ext4/tmpfs).
    Retorna la ruta segura a usar.
    """
    if os.path.isdir(candidate):
        fs = detect_filesystem(candidate)
        if fs not in _UNSAFE_FS:
            return candidate

    if not os.path.exists(candidate):
        try:
            os.makedirs(candidate, exist_ok=True)
            fs = detect_filesystem(candidate)
            if fs not in _UNSAFE_FS:
                return candidate
        except OSError:
            pass

    home_candidate = os.path.join(os.path.expanduser("~"), "ai_cluster")
    os.makedirs(home_candidate, exist_ok=True)
    fs = detect_filesystem(home_candidate)
    if fs not in _UNSAFE_FS:
        return home_candidate

    tmp_candidate = os.path.join("/tmp", "omen_agent_db")
    os.makedirs(tmp_candidate, exist_ok=True)
    return tmp_candidate


# ---------------------------------------------------------------------------
# DIRECTORIO DE LA DB DEL AGENTE
# ---------------------------------------------------------------------------
_AGENT_DB_DIR_RAW = os.environ.get(
    "AGENT_DB_DIR",
    os.path.join(os.path.expanduser("~"), "ai_cluster"),
)
AGENT_DB_DIR: str = validate_db_dir(_AGENT_DB_DIR_RAW)
DB_PATH: str = os.path.join(AGENT_DB_DIR, "agent_tasks.db")

# ---------------------------------------------------------------------------
# URLS DE BACKENDS
# [V27-C4] 127.0.0.1 explicito para evitar resolucion IPv6 de "localhost"
# ---------------------------------------------------------------------------
OLLAMA_GPU_URL  = os.environ.get("OLLAMA_GPU_URL",  "http://127.0.0.1:11434")
OLLAMA_CPU_URL  = os.environ.get("OLLAMA_CPU_URL",  "http://127.0.0.1:11435")
SGLANG_URL      = os.environ.get("SGLANG_URL",      "http://127.0.0.1:30000")
TABBYAPI_URL    = os.environ.get("TABBYAPI_URL",    "http://127.0.0.1:5000")
CHROMA_URL      = os.environ.get("CHROMA_URL",      "http://127.0.0.1:8001")
SEARXNG_URL     = os.environ.get("SEARXNG_URL",     "http://127.0.0.1:8888")

# Endpoints derivados
OLLAMA_GPU_CHAT       = f"{OLLAMA_GPU_URL}/api/chat"
OLLAMA_GPU_GENERATE   = f"{OLLAMA_GPU_URL}/api/generate"
OLLAMA_CPU_CHAT       = f"{OLLAMA_CPU_URL}/api/chat"
OLLAMA_CPU_GENERATE   = f"{OLLAMA_CPU_URL}/api/generate"
SGLANG_CHAT           = f"{SGLANG_URL}/v1/chat/completions"
TABBYAPI_CHAT         = f"{TABBYAPI_URL}/v1/chat/completions"
TABBYAPI_MODEL_LOAD   = f"{TABBYAPI_URL}/v1/model/load"
TABBYAPI_MODEL_UNLOAD = f"{TABBYAPI_URL}/v1/model/unload"
TABBYAPI_MODELS       = f"{TABBYAPI_URL}/v1/models"

# Embeddings
EMBED_CPU_URL   = f"{OLLAMA_CPU_URL}/api/embeddings"
EMBED_MODEL     = os.environ.get("EMBED_MODEL", "nomic-embed-text")
EMBED_THRESHOLD = float(os.environ.get("EMBED_THRESHOLD", "0.52"))

# Phi4 (clasificador LLM)
PHI4_CPU_URL      = f"{OLLAMA_CPU_URL}/api/generate"
PHI4_CPU_CHAT_URL = f"{OLLAMA_CPU_URL}/api/chat"
PHI4_CPU_TAGS     = f"{OLLAMA_CPU_URL}/api/tags"
PHI4_GPU_CHAT_URL = f"{OLLAMA_GPU_URL}/api/chat"
PHI4_MODEL        = "phi4-mini"
PHI4_FALLBACK     = "phi4:latest"

# ChromaDB RAG
CHROMA_COLLECTION = os.environ.get("CHROMA_COLLECTION", "obsidian_vault")
RAG_TOP_K         = int(os.environ.get("RAG_TOP_K", "5"))
RAG_MAX_DIST      = float(os.environ.get("RAG_MAX_DIST", "0.75"))
RAG_NIVELES       = frozenset({"PROFUNDO", "AGIL", "MASIVO", "PRECISO", "PRECISO_OPT"})

# ---------------------------------------------------------------------------
# RUTAS DE MODELOS
# [V26-INFRA] Todo en Ollama GPU
# [V27-C2] opciones_extra usa sub-dict "options" con num_predict (Ollama)
#           en lugar de max_tokens en root del body (ignorado por Ollama)
# ---------------------------------------------------------------------------
RUTAS: dict = {
    "CHAT": {
        "modelo": "phi4-mini:latest",
        "url": OLLAMA_GPU_CHAT,
        "backend": "ollama_gpu",
        "health_url": f"{OLLAMA_GPU_URL}/api/tags",
        "timeout_s": 60.0,
        "opciones_extra": {"temperature": 0.7, "options": {"num_predict": 2048}},
    },
    "INSTANTANEO": {
        "modelo": "phi4-mini:latest",
        "url": OLLAMA_GPU_CHAT,
        "backend": "ollama_gpu",
        "health_url": f"{OLLAMA_GPU_URL}/api/tags",
        "timeout_s": 30.0,
        "opciones_extra": {"temperature": 0.3, "options": {"num_predict": 1024}},
    },
    "AGIL": {
        "modelo": "phi4:latest",
        "url": OLLAMA_GPU_CHAT,
        "backend": "ollama_gpu",
        "health_url": f"{OLLAMA_GPU_URL}/api/tags",
        "timeout_s": 90.0,
        "opciones_extra": {"temperature": 0.6, "options": {"num_predict": 4096}},
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
        # [V28-MASIVO] Timeout ampliado — preferimos penalizar tiempo, no razonamiento.
        # qwen2.5:32b puede tardar ~25-32s en carga en frío en RTX 8GB.
        # num_ctx y num_predict controlados por _CTX_POR_NIVEL en proxy.py (4096).
        "timeout_s": 360.0,
        "opciones_extra": {
            "temperature": 0.4,
            "options": {
                "num_ctx": 4096,
                "num_predict": 1024,
            }
        },
    },
    "CODIGO": {
        "modelo": "deepseek-coder-v2:latest",
        "url": OLLAMA_GPU_CHAT,
        "backend": "ollama_gpu",
        "health_url": f"{OLLAMA_GPU_URL}/api/tags",
        "timeout_s": 90.0,
        "opciones_extra": {"temperature": 0.2, "options": {"num_predict": 3072}},
    },
}

# ---------------------------------------------------------------------------
# ALIAS -> NIVEL
# [V27-C1] UNA sola entrada "phi4-mini" -> "CHAT"
#           (eliminada segunda entrada que sobreescribia con PHI4_DIRECTO)
# ---------------------------------------------------------------------------
ALIAS_A_NIVEL: dict = {
    # Auto-routing
    "ruteador-auto": None,
    "auto":          None,
    # Niveles directos
    "chat":                "CHAT",
    "instantaneo":         "INSTANTANEO",
    "instantaneo":         "INSTANTANEO",
    "agil":                "AGIL",
    "profundo":            "PROFUNDO",
    "deep":                "PROFUNDO",
    "preciso":             "PRECISO",
    "phi-mayor-precision": "PRECISO",
    "phi-optimizada":      "PRECISO_OPT",
    "masivo":              "MASIVO",
    "massive":             "MASIVO",
    "codigo":              "CODIGO",
    "code":                "CODIGO",
    # Modelos directos por nombre exacto
    "deepseek-r1:14b":            "PROFUNDO",
    "qwen2.5:32b":                "MASIVO",
    "phi4-mini:latest":           "CHAT",
    "phi4-mini":                  "CHAT",        # [V27-C1] unica entrada, sin PHI4_DIRECTO
    "phi4:latest":                "AGIL",
    "phi4":                       "AGIL",
    "deepseek-coder-v2:latest":   "CODIGO",
    "deepseek-coder-v2":          "CODIGO",
    "phi4-reasoning:plus":        "PRECISO",
    "phi4-reasoning:14b-q4_k_m": "PRECISO_OPT",
    # Modelos legacy -> equivalentes Ollama GPU
    "llama-3.1-8b-awq":           "AGIL",
    "llama-3.1-8b-exl2":          "CHAT",
    "qwen2.5-coder-7b-exl2":      "CODIGO",
    # PHI4_DIRECTO solo via alias explicito [V27-C1]
    "phi4-direct":   "PHI4_DIRECTO",
    "phi4-directo":  "PHI4_DIRECTO",
    # Agente autonomo
    "agent-autonomo": "AGENT",
    "agente":         "AGENT",
}

# ---------------------------------------------------------------------------
# TIMEOUT FALLBACK
# ---------------------------------------------------------------------------
_TIMEOUT_FALLBACK_RAW: dict = {
    "PROFUNDO": "AGIL",
    "MASIVO":   "PROFUNDO",
    "PRECISO":  "PRECISO_OPT",
    "AGIL":     "CHAT",
}


def _validate_fallback_chain(fallbacks: dict) -> dict:
    """Valida que no existan ciclos en la cadena de fallback."""
    for start in fallbacks:
        visited = {start}
        current = fallbacks.get(start)
        while current:
            if current in visited:
                raise ValueError(
                    f"Ciclo detectado en TIMEOUT_FALLBACK: {start} -> ... -> {current}"
                )
            visited.add(current)
            current = fallbacks.get(current)
    return fallbacks


TIMEOUT_FALLBACK: dict = _validate_fallback_chain(_TIMEOUT_FALLBACK_RAW)

# ---------------------------------------------------------------------------
# AGENT ENGINE CONFIG
# ---------------------------------------------------------------------------
MAX_ACTIVE_TASKS         = int(os.environ.get("MAX_ACTIVE_TASKS", "3"))
MAX_PROMPT_LEN           = int(os.environ.get("MAX_PROMPT_LEN", "10000"))
AGENT_CONTEXT_MAX_TOKENS = int(os.environ.get("AGENT_CONTEXT_MAX_TOKENS", "12000"))

AGENT_TO_NIVEL: dict = {
    "research":  "PROFUNDO",
    "code":      "CODIGO",
    "creative":  "AGIL",
    "quick":     "INSTANTANEO",
    "analysis":  "MASIVO",
    "precise":   "PRECISO",
}

# ---------------------------------------------------------------------------
# RATE LIMITING
# ---------------------------------------------------------------------------
RATE_LIMIT_MAX    = int(os.environ.get("RATE_LIMIT_MAX", "60"))
RATE_LIMIT_WINDOW = float(os.environ.get("RATE_LIMIT_WINDOW", "60.0"))

# ---------------------------------------------------------------------------
# LOGGING
# [V27-C3] LOG_FILE -> router_v14.log (unifica con redireccion del Autoboot)
# ---------------------------------------------------------------------------
LOG_DIR = os.environ.get(
    "OMEN_LOG_DIR",
    os.path.join(os.path.expanduser("~"), "ai_cluster", "logs"),
)
LOG_FILE         = os.path.join(LOG_DIR, "router_v14.log")  # [V27-C3]
LOG_MAX_BYTES    = 50 * 1024 * 1024
LOG_BACKUP_COUNT = 3

HEALTH_TTL = 15.0

# ---------------------------------------------------------------------------
# CLASIFICADOR
# ---------------------------------------------------------------------------
EMBED_DESCRIPTIONS: dict = {
    "CHAT":        "conversacion casual, saludo, pregunta simple, charla informal, respuesta corta",
    "INSTANTANEO": "pregunta rapida, definicion, dato concreto, calculo simple, traduccion breve",
    "AGIL":        "analisis de documento, resumen extenso, investigacion, agente con herramientas, RAG",
    "PROFUNDO":    "razonamiento complejo, matematicas avanzadas, logica formal, problema multi-paso, deduccion",
    "PRECISO":     "razonamiento preciso, verificacion formal, demostracion, analisis riguroso, correccion de pruebas",
    "MASIVO":      "analisis masivo de datos, documento muy largo, comparacion extensa, sintesis de multiples fuentes",
    "CODIGO":      "programacion, codigo fuente, debugging, refactoring, script, funcion, algoritmo, API",
}

SYSTEM_PHI4: str = (
    "Eres un clasificador de prompts. Responde SOLO con UNA palabra: "
    "CHAT, INSTANTANEO, AGIL, PROFUNDO, PRECISO, MASIVO o CODIGO. "
    "CHAT=conversacion simple. INSTANTANEO=pregunta rapida/dato. "
    "AGIL=analisis/documentos/agentes. PROFUNDO=razonamiento complejo/matematicas. "
    "PRECISO=verificacion rigurosa/formal. MASIVO=analisis extenso/multiples fuentes. "
    "CODIGO=programacion/codigo."
)
