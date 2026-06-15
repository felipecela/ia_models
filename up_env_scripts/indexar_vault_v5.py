#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║ indexar_vault_v5.py — Indexador Vault Obsidian → ChromaDB                  ║
║ OMEN AI Cluster V20                                                         ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ V20 — Correcciones de auditoría integral sobre V19 (indexar_vault_v4.py):  ║
║  ✔ [V20-I1]  Signal handler seguro: solo marca flag, sin sys.exit(0)       ║
║              El bucle principal guarda estado y cierra limpiamente          ║
║  ✔ [V20-I2]  Fallback real de filesystem: lógica idéntica al router        ║
║              Si STATE_DIR está en exFAT, busca alternativa en ext4          ║
║  ✔ [V20-I3]  Sesión HTTP con HTTPAdapter + Retry para ChromaDB             ║
║              3 reintentos automáticos en 502/503/504 y ConnectionError      ║
║  ✔ [V20-I4]  file_signature mejorada: mtime + size + hash parcial (1KB)    ║
║              Elimina falsos negativos en exFAT (resolución 2s de mtime)    ║
║  ✔ [V20-I5]  Sub-headings preservados en chunks como separadores           ║
║              Mejora la calidad semántica del embedding                      ║
║  ✔ [V20-I6]  get_embedding: retry también en ValueError/KeyError           ║
║              Maneja respuestas 200 con body inválido                        ║
║  ✔ [V20-I7]  Timeout global configurable (--max-time) con estado parcial   ║
║  ✔ [V20-I8]  chroma_get_all_sources: logging de total esperado vs obtenido ║
║  ✔ [V20-I9]  process_file: siempre delete antes de upsert (no solo update) ║
║              Previene duplicados si el state se pierde/corrompe             ║
║  ✔ [V20-I10] argparse movido a main() (testabilidad de imports)            ║
║  ✔ [V20-I11] validate_state_dir renombrado y con fallback real             ║
║  ✔ [V20-I12] os.walk con followlinks=False explícito                       ║
║  ✔ [V20-I13] Guard contra reentrada en save_state durante signal           ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ Heredado de V19 (indexar_vault_v4.py — todas las mejoras):                 ║
║  ✔ [V19-I1..I13] Todas las mejoras de V19 mantenidas                       ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ Heredado de V18 (indexar_vault_v3.py — todas las mejoras):                 ║
║  ✔ [V18-I1..I16] Todas las mejoras de V18 mantenidas                       ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ Características:                                                            ║
║  • Indexación INCREMENTAL semántica — solo archivos modificados             ║
║  • Chunking inteligente por secciones/párrafos (no corta frases)           ║
║  • API HTTP nativa — sin dependencia de la librería 'chromadb'             ║
║  • Compatible con ChromaDB ≥ 0.4 (UUID en todas las llamadas)              ║
║  • Upserts por lotes — reduce llamadas HTTP al mínimo                      ║
║  • Purga automática de archivos eliminados del vault                       ║
║  • Exclusión automática de .obsidian/, templates/, .trash/, etc.           ║
║  • Modos: incremental, --clean, --stats, --dry-run, --verbose, --prune    ║
║  • Graceful shutdown: SIGINT/SIGTERM guardan estado parcial                ║
║  • Timeout global configurable (--max-time)                                ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ Dependencias: pip3 install requests urllib3                                  ║
║ Uso:                                                                        ║
║   python3 indexar_vault_v5.py                          # Incremental       ║
║   python3 indexar_vault_v5.py --clean                  # Reindexar todo    ║
║   python3 indexar_vault_v5.py --stats                  # Estadísticas      ║
║   python3 indexar_vault_v5.py --dry-run                # Simulación        ║
║   python3 indexar_vault_v5.py --prune                  # Purgar huérfanos  ║
║   python3 indexar_vault_v5.py --verbose                # Logging detallado ║
║   python3 indexar_vault_v5.py --max-time 3600          # Timeout 1 hora   ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import argparse
import hashlib
import json
import logging
import os
import re
import signal
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    import requests
    from requests.adapters import HTTPAdapter
except ImportError:
    print("✘ Dependencia faltante: 'requests'", file=sys.stderr)
    print("  Instala con: pip3 install requests", file=sys.stderr)
    sys.exit(1)

try:
    from urllib3.util.retry import Retry
except ImportError:
    # urllib3 viene con requests, pero por si acaso
    Retry = None  # type: ignore[assignment, misc]

# ─────────────────────────────────────────────────────────────────────────────
# [V18-I11] LOGGING — con timestamps y niveles
# ─────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger("indexar-vault-v5")

# ─────────────────────────────────────────────────────────────────────────────
# [V20-I1] SIGNAL HANDLER — seguro, sin sys.exit, sin reentrada
# [V20-I13] Guard contra reentrada en save_state
# ─────────────────────────────────────────────────────────────────────────────
_shutdown_requested = False
_partial_state: Optional[dict] = None
_saving_state = False  # [V20-I13] Guard contra reentrada


def _signal_handler(signum, frame):
    """
    [V20-I1] Maneja SIGINT/SIGTERM de forma segura.
    Solo marca el flag — el bucle principal se encarga de guardar estado y salir.
    NO llama a sys.exit() para permitir limpieza ordenada.
    """
    global _shutdown_requested
    sig_name = signal.Signals(signum).name
    log.warning(f"Señal {sig_name} recibida — solicitando shutdown limpio…")
    _shutdown_requested = True


signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURACIÓN — defaults (argparse se ejecuta en main())
# ─────────────────────────────────────────────────────────────────────────────

# [V18-I1] Parámetros de chunking semántico
CHUNK_MAX_CHARS   = 800     # Máximo de caracteres por chunk
CHUNK_MIN_CHARS   = 80      # Mínimo para considerar un chunk válido
CHUNK_OVERLAP_SENTENCES = 1 # [V19-I4] Solapamiento: última frase del chunk anterior

# Parámetros de red
BATCH_SIZE       = 24       # Chunks por lote de upsert
EMBED_BATCH_SIZE = 8        # Embeddings por llamada batch (si soportado)
EMBED_TIMEOUT    = 45.0     # Timeout base para embeddings
CHROMA_TIMEOUT   = 20.0
CONNECT_TIMEOUT  = 5.0

# [V18-I5] Rate limiting
EMBED_RATE_LIMIT  = 0.05    # Segundos mínimos entre llamadas a Ollama
MAX_RETRIES       = 3       # Reintentos con backoff exponencial
BACKOFF_BASE      = 2.0     # Base del backoff (2^intento segundos)

# [V17-I4] Directorios excluidos
EXCLUDED_DIRS: set = {
    ".obsidian", "templates", "_templates", ".git",
    ".trash", "trash", "archive", "_archive",
    "attachments", "_attachments", "assets",
    "node_modules", ".vscode",
}


# ─────────────────────────────────────────────────────────────────────────────
# [V20-I2] [V20-I11] VALIDACIÓN DE FILESYSTEM — con fallback real
# Lógica idéntica al router (_validate_db_dir) para coherencia arquitectónica.
# ─────────────────────────────────────────────────────────────────────────────
_UNSAFE_FS = {"exfat", "vfat", "fat32", "ntfs", "fuseblk"}


def _detect_filesystem(path: str) -> str:
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


def _validate_state_dir(candidate: str) -> str:
    """
    [V20-I2][V20-I11] Valida que el directorio de estado está en un filesystem
    compatible. Si no, busca alternativa segura (idéntico al router).
    Retorna la ruta segura a usar.
    """
    # Intentar el candidato principal
    if os.path.isdir(candidate):
        fs = _detect_filesystem(candidate)
        if fs not in _UNSAFE_FS:
            return candidate
        log.warning(
            f"[V20-I2] STATE_DIR ({candidate}) está en filesystem '{fs}' "
            f"(incompatible con escritura atómica fiable). Buscando alternativa…"
        )
    elif not os.path.exists(candidate):
        # Intentar crear
        try:
            os.makedirs(candidate, exist_ok=True)
            fs = _detect_filesystem(candidate)
            if fs not in _UNSAFE_FS:
                return candidate
        except OSError:
            pass

    # Fallback 1: $HOME/ai_cluster
    home_candidate = os.path.join(os.path.expanduser("~"), "ai_cluster")
    os.makedirs(home_candidate, exist_ok=True)
    fs = _detect_filesystem(home_candidate)
    if fs not in _UNSAFE_FS:
        log.info(f"[V20-I2] Usando directorio alternativo: {home_candidate} (fs={fs})")
        return home_candidate

    # Fallback 2: /tmp (siempre tmpfs o ext4 en Linux)
    tmp_candidate = os.path.join("/tmp", "omen_vault_state")
    os.makedirs(tmp_candidate, exist_ok=True)
    log.warning(f"[V20-I2] Usando /tmp como último recurso: {tmp_candidate}")
    return tmp_candidate


# ─────────────────────────────────────────────────────────────────────────────
# [V20-I3] SESIÓN HTTP CON RETRY ADAPTER
# ─────────────────────────────────────────────────────────────────────────────
def _create_session() -> requests.Session:
    """
    [V20-I3] Crea una sesión HTTP con retry automático para ChromaDB.
    Reintenta en errores 502, 503, 504 y errores de conexión.
    """
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})

    if Retry is not None:
        retry_strategy = Retry(
            total=3,
            backoff_factor=1.0,
            status_forcelist=[502, 503, 504],
            allowed_methods=["GET", "POST", "DELETE"],
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
    else:
        log.warning("[V20-I3] urllib3.Retry no disponible — sin retry automático en sesión")

    return session


# ─────────────────────────────────────────────────────────────────────────────
# [V18-I9] BARRA DE PROGRESO — sin dependencias externas
# ─────────────────────────────────────────────────────────────────────────────
def progress_bar(current: int, total: int, prefix: str = "", width: int = 40) -> None:
    """Imprime una barra de progreso en la misma línea."""
    if total == 0:
        return
    pct = current / total
    filled = int(width * pct)
    bar = "█" * filled + "░" * (width - filled)
    sys.stdout.write(f"\r{prefix} [{bar}] {current}/{total} ({pct*100:.1f}%)")
    if current >= total:
        sys.stdout.write("\n")
    sys.stdout.flush()


# ─────────────────────────────────────────────────────────────────────────────
# [V18-I2] PREPROCESAMIENTO MARKDOWN
# ─────────────────────────────────────────────────────────────────────────────
_RE_FRONTMATTER = re.compile(r"^---\s*\n.*?\n---\s*\n", re.DOTALL)
_RE_OBSIDIAN_LINK = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
_RE_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_RE_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]+\)")
_RE_CODE_BLOCK = re.compile(r"```[\s\S]*?```")
_RE_INLINE_CODE = re.compile(r"`[^`]+`")
_RE_BOLD_ITALIC = re.compile(r"(\*{1,3}|_{1,3})(.+?)\1")
_RE_HEADING = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_RE_TAGS = re.compile(r"#([a-zA-Z0-9_/\-]+)")
_RE_MULTIPLE_NEWLINES = re.compile(r"\n{3,}")
_RE_CALLOUT = re.compile(r"^>\s*\[!.*?\].*$", re.MULTILINE)


def extract_frontmatter_tags(text: str) -> list:
    """Extrae tags del frontmatter YAML si existe."""
    tags = []
    match = _RE_FRONTMATTER.match(text)
    if match:
        fm = match.group(0)
        # Buscar línea "tags: [...]" o "tags:\n  - ..."
        tag_line = re.search(r"tags:\s*\[([^\]]+)\]", fm)
        if tag_line:
            tags = [t.strip().strip("'\"") for t in tag_line.group(1).split(",")]
        else:
            # Buscar formato YAML con guiones
            in_tags = False
            for line in fm.split("\n"):
                if line.strip().startswith("tags:"):
                    in_tags = True
                    continue
                if in_tags:
                    if line.strip().startswith("- "):
                        tags.append(line.strip()[2:].strip("'\""))
                    elif line.strip() and not line.startswith(" "):
                        break
    # También buscar tags inline (#tag)
    inline_tags = _RE_TAGS.findall(text[:2000])  # Solo primeros 2000 chars
    tags.extend(inline_tags)
    return list(set(tags))[:20]  # Máximo 20 tags


def extract_title(text: str, filepath: str) -> str:
    """Extrae el título del documento (primer H1 o nombre del archivo)."""
    match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    if match:
        return match.group(1).strip()
    return Path(filepath).stem.replace("-", " ").replace("_", " ")


def clean_markdown(text: str, preserve_subheadings: bool = False) -> str:
    """
    [V18-I2] Limpia la sintaxis Markdown para obtener texto plano de calidad
    para embeddings. Preserva la estructura semántica (párrafos, secciones).
    [V20-I5] Opción para preservar sub-headings como separadores semánticos.
    """
    # Eliminar frontmatter YAML
    text = _RE_FRONTMATTER.sub("", text)

    # Eliminar bloques de código (no aportan a la semántica general)
    text = _RE_CODE_BLOCK.sub("[código]", text)

    # Eliminar imágenes
    text = _RE_IMAGE.sub("", text)

    # Resolver links de Obsidian: [[nota|alias]] → alias, [[nota]] → nota
    text = _RE_OBSIDIAN_LINK.sub(lambda m: m.group(2) or m.group(1), text)

    # Resolver links Markdown: [texto](url) → texto
    text = _RE_MD_LINK.sub(r"\1", text)

    # Eliminar inline code backticks (mantener contenido)
    text = _RE_INLINE_CODE.sub(lambda m: m.group(0)[1:-1], text)

    # Eliminar bold/italic markers (mantener contenido)
    text = _RE_BOLD_ITALIC.sub(r"\2", text)

    # Eliminar callouts de Obsidian
    text = _RE_CALLOUT.sub("", text)

    # [V20-I5] Headings: preservar como separadores o eliminar
    if preserve_subheadings:
        # Convertir headings a separadores semánticos (mantener texto, añadir separador)
        text = re.sub(r"^#{1,6}\s+(.+)$", r"— \1 —", text, flags=re.MULTILINE)
    else:
        text = _RE_HEADING.sub("", text)

    # Normalizar espacios múltiples
    text = _RE_MULTIPLE_NEWLINES.sub("\n\n", text)

    return text.strip()


# ─────────────────────────────────────────────────────────────────────────────
# [V18-I1] CHUNKING SEMÁNTICO + [V19-I4] OVERLAP + [V20-I5] SUB-HEADINGS
# ─────────────────────────────────────────────────────────────────────────────
def _split_into_sections(text: str) -> list:
    """
    Divide el texto en secciones basándose en encabezados Markdown de nivel 1-2.
    Sub-headings (nivel 3+) se mantienen dentro de la sección padre.
    Retorna lista de tuplas (heading, content).
    """
    sections = []
    lines = text.split("\n")
    current_heading = ""
    current_lines = []

    for line in lines:
        # Solo dividir en H1 y H2 (secciones principales)
        heading_match = re.match(r"^(#{1,2})\s+(.+)$", line)
        if heading_match:
            # Guardar sección anterior
            if current_lines:
                content = "\n".join(current_lines).strip()
                if content:
                    sections.append((current_heading, content))
            current_heading = heading_match.group(2).strip()
            current_lines = []
        else:
            current_lines.append(line)

    # Última sección
    if current_lines:
        content = "\n".join(current_lines).strip()
        if content:
            sections.append((current_heading, content))

    return sections if sections else [("", text)]


def _extract_last_sentence(text: str) -> str:
    """Extrae la última frase de un texto para overlap entre chunks."""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    if sentences:
        return sentences[-1]
    return ""


def chunk_text_semantic(text: str) -> list:
    """
    [V18-I1] + [V19-I4] + [V20-I5] Chunking semántico con overlap y sub-headings.
    Divide respetando párrafos y secciones. Incluye la última frase del
    chunk anterior como contexto en el siguiente (CHUNK_OVERLAP_SENTENCES).
    Sub-headings (H3+) se preservan como separadores semánticos dentro del chunk.

    Retorna lista de dicts: [{"text": str, "heading": str}, ...]
    """
    sections = _split_into_sections(text)
    chunks = []
    prev_last_sentence = ""  # [V19-I4] Para overlap entre chunks

    for heading, content in sections:
        # [V20-I5] Limpiar contenido preservando sub-headings como separadores
        clean_content = clean_markdown(content, preserve_subheadings=True)

        if not clean_content or len(clean_content.strip()) < CHUNK_MIN_CHARS:
            continue

        # Si la sección cabe en un solo chunk, usarla directamente
        if len(clean_content) <= CHUNK_MAX_CHARS:
            # [V19-I4] Agregar overlap si hay contexto previo
            if prev_last_sentence and CHUNK_OVERLAP_SENTENCES > 0:
                overlap_text = f"[…] {prev_last_sentence}\n\n{clean_content}"
                if len(overlap_text) <= CHUNK_MAX_CHARS * 1.1:  # 10% tolerancia
                    chunks.append({"text": overlap_text, "heading": heading})
                else:
                    chunks.append({"text": clean_content, "heading": heading})
            else:
                chunks.append({"text": clean_content, "heading": heading})
            prev_last_sentence = _extract_last_sentence(clean_content)
            continue

        # Dividir por párrafos (doble newline)
        paragraphs = [p.strip() for p in clean_content.split("\n\n") if p.strip()]

        current_chunk = ""
        # [V19-I4] Iniciar con overlap si hay contexto previo
        if prev_last_sentence and CHUNK_OVERLAP_SENTENCES > 0:
            current_chunk = f"[…] {prev_last_sentence}"

        for para in paragraphs:
            # Si el párrafo solo ya excede el máximo, dividir por frases
            if len(para) > CHUNK_MAX_CHARS:
                # Guardar chunk actual si tiene contenido
                if current_chunk.strip() and len(current_chunk.strip()) >= CHUNK_MIN_CHARS:
                    chunks.append({"text": current_chunk.strip(), "heading": heading})
                    prev_last_sentence = _extract_last_sentence(current_chunk.strip())
                    current_chunk = ""

                # Dividir párrafo largo por frases
                sentences = re.split(r"(?<=[.!?])\s+", para)
                sent_chunk = ""
                for sent in sentences:
                    if len(sent_chunk) + len(sent) + 1 > CHUNK_MAX_CHARS:
                        if sent_chunk.strip() and len(sent_chunk.strip()) >= CHUNK_MIN_CHARS:
                            chunks.append({"text": sent_chunk.strip(), "heading": heading})
                            prev_last_sentence = _extract_last_sentence(sent_chunk.strip())
                        sent_chunk = sent
                    else:
                        sent_chunk = f"{sent_chunk} {sent}".strip() if sent_chunk else sent
                if sent_chunk.strip() and len(sent_chunk.strip()) >= CHUNK_MIN_CHARS:
                    current_chunk = sent_chunk
                continue

            # Verificar si agregar este párrafo excede el máximo
            test = f"{current_chunk}\n\n{para}".strip() if current_chunk else para
            if len(test) > CHUNK_MAX_CHARS:
                # Guardar chunk actual y empezar nuevo
                if current_chunk.strip() and len(current_chunk.strip()) >= CHUNK_MIN_CHARS:
                    chunks.append({"text": current_chunk.strip(), "heading": heading})
                    prev_last_sentence = _extract_last_sentence(current_chunk.strip())
                current_chunk = para
            else:
                current_chunk = test

        # Guardar último chunk de la sección
        if current_chunk.strip() and len(current_chunk.strip()) >= CHUNK_MIN_CHARS:
            chunks.append({"text": current_chunk.strip(), "heading": heading})
            prev_last_sentence = _extract_last_sentence(current_chunk.strip())

    return chunks


# ─────────────────────────────────────────────────────────────────────────────
# UTILIDADES DE ARCHIVOS
# [V20-I4] file_signature mejorada con hash parcial
# [V20-I12] os.walk con followlinks=False explícito
# ─────────────────────────────────────────────────────────────────────────────
def file_signature(filepath: str) -> str:
    """
    [V20-I4] Firma robusta: mtime + tamaño + hash parcial (primer 1KB).
    El hash parcial elimina falsos negativos en exFAT donde mtime tiene
    resolución de 2 segundos y puede cambiar al montar/desmontar.
    """
    st = os.stat(filepath)
    # Hash parcial del inicio del archivo (rápido, detecta cambios de contenido)
    try:
        with open(filepath, "rb") as f:
            header = f.read(1024)
        partial_hash = hashlib.md5(header).hexdigest()[:8]
    except OSError:
        partial_hash = "00000000"
    return f"{st.st_mtime:.3f}:{st.st_size}:{partial_hash}"


def discover_md_files(vault_dir: str) -> list:
    """
    Descubre .md del vault, excluyendo directorios no deseados.
    [V20-I12] followlinks=False explícito para evitar indexar symlinks externos.
    """
    md_files = []
    for root, dirs, files in os.walk(vault_dir, followlinks=False):
        # [V17-I3] Modificación in-place de dirs
        dirs[:] = [
            d for d in dirs
            if d.lower() not in EXCLUDED_DIRS and not d.startswith(".")
        ]
        for fname in files:
            if fname.endswith(".md") and not fname.startswith("."):
                md_files.append(os.path.join(root, fname))
    return sorted(md_files)


def read_md_file(filepath: str) -> str:
    """
    Lee un archivo .md con manejo robusto de encoding.
    [V17-I5] Intenta UTF-8, luego latin-1; ignora errores como último recurso.
    [V19-I11] Detecta archivos binarios/corruptos.
    """
    # [V19-I11] Verificar que no es un archivo binario
    try:
        with open(filepath, "rb") as f:
            header = f.read(512)
            # Si tiene muchos bytes nulos, probablemente es binario
            null_ratio = header.count(b'\x00') / max(len(header), 1)
            if null_ratio > 0.1:
                log.debug(f"Archivo parece binario (null ratio={null_ratio:.2f}): {filepath}")
                return ""
    except OSError:
        return ""

    for enc in ("utf-8", "latin-1", "utf-8-sig"):
        try:
            with open(filepath, "r", encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    # Último recurso
    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


# ─────────────────────────────────────────────────────────────────────────────
# ESTADO INCREMENTAL
# [V20-I13] Guard contra reentrada en save_state
# ─────────────────────────────────────────────────────────────────────────────
def load_state(state_file: str) -> dict:
    """Carga el mapa {ruta_relativa: firma} del disco."""
    try:
        with open(state_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state: dict, state_file: str) -> None:
    """
    Persiste el estado incremental en disco.
    [V19-I1] Escritura atómica mejorada con fsync antes de os.replace.
    [V20-I13] Guard contra reentrada (si signal llega durante escritura).
    """
    global _saving_state
    if _saving_state:
        log.debug("[V20-I13] save_state ya en ejecución — evitando reentrada")
        return

    _saving_state = True
    try:
        # [V17-I7] Crear directorio padre si no existe
        os.makedirs(os.path.dirname(state_file) or ".", exist_ok=True)
        # Escritura atómica: escribir en temporal, fsync, y renombrar
        tmp_file = state_file + ".tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())  # [V19-I1] Garantizar flush a disco
        os.replace(tmp_file, state_file)
    except Exception as e:
        log.warning(f"No se pudo guardar el estado incremental: {e}")
    finally:
        _saving_state = False


# ─────────────────────────────────────────────────────────────────────────────
# [V18-I12] IDs DE CHUNKS — SHA-256 truncado
# ─────────────────────────────────────────────────────────────────────────────
def chunk_id(rel_path: str, chunk_idx: int) -> str:
    """Genera un ID único y estable para un fragmento usando SHA-256 truncado."""
    raw = f"{rel_path}::{chunk_idx}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


# ─────────────────────────────────────────────────────────────────────────────
# [V18-I5] EMBEDDINGS — con retry y rate limiting
# [V20-I6] Retry también en ValueError/KeyError (body inválido con status 200)
# ─────────────────────────────────────────────────────────────────────────────
_last_embed_time: float = 0.0


def get_embedding(text: str, session: requests.Session, ollama_url: str, embed_model: str) -> list:
    """
    Obtiene el embedding de un texto via Ollama CPU.
    [V18-I5] Incluye rate limiting y retry con backoff exponencial.
    [V18-I13] Timeout adaptativo basado en longitud del chunk.
    [V20-I6] Retry en ValueError/KeyError además de Timeout/ConnectionError.
    """
    global _last_embed_time

    # Rate limiting
    elapsed = time.monotonic() - _last_embed_time
    if elapsed < EMBED_RATE_LIMIT:
        time.sleep(EMBED_RATE_LIMIT - elapsed)

    # Timeout adaptativo: base + 0.01s por cada 100 chars
    adaptive_timeout = EMBED_TIMEOUT + (len(text) / 100) * 0.01

    for attempt in range(MAX_RETRIES):
        try:
            _last_embed_time = time.monotonic()
            resp = session.post(
                ollama_url,
                json={"model": embed_model, "prompt": text},
                timeout=adaptive_timeout,
            )
            resp.raise_for_status()
            data = resp.json()

            if "embedding" not in data:
                raise ValueError(f"Ollama no devolvió 'embedding'. Keys: {list(data.keys())}")

            embedding = data["embedding"]

            # [V18-I8] Validación de dimensionalidad
            if not embedding or not isinstance(embedding, list):
                raise ValueError(f"Embedding vacío o tipo inválido: {type(embedding)}")

            return embedding

        except requests.exceptions.Timeout:
            if attempt < MAX_RETRIES - 1:
                wait = BACKOFF_BASE ** (attempt + 1)
                log.debug(f"Timeout en embedding (intento {attempt+1}), reintentando en {wait:.1f}s…")
                time.sleep(wait)
            else:
                raise
        except requests.exceptions.ConnectionError:
            if attempt < MAX_RETRIES - 1:
                wait = BACKOFF_BASE ** (attempt + 1)
                log.debug(f"Error de conexión (intento {attempt+1}), reintentando en {wait:.1f}s…")
                time.sleep(wait)
            else:
                raise
        except (ValueError, KeyError):
            # [V20-I6] Retry en respuestas 200 con body inválido
            if attempt < MAX_RETRIES - 1:
                wait = BACKOFF_BASE ** (attempt + 1)
                log.debug(f"Body inválido en embedding (intento {attempt+1}), reintentando en {wait:.1f}s…")
                time.sleep(wait)
            else:
                raise
        except Exception:
            raise

    # No debería llegar aquí, pero por seguridad
    raise RuntimeError("get_embedding: reintentos agotados")


# ─────────────────────────────────────────────────────────────────────────────
# CHROMADB — API HTTP nativa (sin librería chromadb)
# [V19-I3] Compatible con ChromaDB ≥ 0.4 y ≥ 0.5 (API V1 y V2)
# [V20-I8] Logging mejorado en paginación
# ─────────────────────────────────────────────────────────────────────────────
_expected_embed_dim: Optional[int] = None
_chroma_api_prefix: str = "/api/v1"  # [V19-I3] Detectado en runtime


def _detect_chroma_api_version(session: requests.Session, chroma_url: str) -> str:
    """
    [V19-I3] Detecta la versión de la API de ChromaDB.
    Intenta V2 primero, fallback a V1.
    """
    global _chroma_api_prefix
    # Intentar V2
    try:
        resp = session.get(f"{chroma_url}/api/v2/heartbeat", timeout=CONNECT_TIMEOUT)
        if resp.status_code == 200:
            _chroma_api_prefix = "/api/v2"
            return "v2"
    except Exception:
        pass
    # Fallback a V1
    _chroma_api_prefix = "/api/v1"
    return "v1"


def chroma_get_or_create_collection(session: requests.Session, chroma_url: str, collection_name: str) -> str:
    """Obtiene o crea la colección. Retorna UUID interno."""
    resp = session.post(
        f"{chroma_url}{_chroma_api_prefix}/collections",
        json={
            "name": collection_name,
            "metadata": {"hnsw:space": "cosine"},
            "get_or_create": True,
        },
        timeout=CHROMA_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()["id"]


def chroma_recreate_collection(session: requests.Session, chroma_url: str, collection_name: str) -> str:
    """Borra y recrea la colección (--clean)."""
    del_resp = session.delete(
        f"{chroma_url}{_chroma_api_prefix}/collections/{collection_name}",
        timeout=CHROMA_TIMEOUT,
    )
    if del_resp.status_code not in (200, 404):
        del_resp.raise_for_status()

    create_resp = session.post(
        f"{chroma_url}{_chroma_api_prefix}/collections",
        json={
            "name": collection_name,
            "metadata": {"hnsw:space": "cosine"},
        },
        timeout=CHROMA_TIMEOUT,
    )
    create_resp.raise_for_status()
    return create_resp.json()["id"]


def chroma_count(collection_id: str, session: requests.Session, chroma_url: str) -> int:
    """Retorna el número de documentos en la colección."""
    resp = session.get(
        f"{chroma_url}{_chroma_api_prefix}/collections/{collection_id}/count",
        timeout=CHROMA_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def chroma_upsert_batch(
    collection_id: str,
    ids: list,
    embeddings: list,
    documents: list,
    metadatas: list,
    session: requests.Session,
    chroma_url: str,
) -> None:
    """
    Upsert de un lote de fragmentos en ChromaDB.
    [V18-I8] Valida dimensionalidad antes de enviar.
    [V19-I5] Timeout proporcional al tamaño del batch.
    [V19-I13] Deduplicación de IDs antes de enviar.
    """
    global _expected_embed_dim

    if not ids:
        return

    # [V19-I13] Deduplicar por ID (mantener último)
    seen_ids = {}
    for i, doc_id in enumerate(ids):
        seen_ids[doc_id] = i
    if len(seen_ids) < len(ids):
        unique_indices = sorted(seen_ids.values())
        ids        = [ids[i] for i in unique_indices]
        embeddings = [embeddings[i] for i in unique_indices]
        documents  = [documents[i] for i in unique_indices]
        metadatas  = [metadatas[i] for i in unique_indices]

    # Validar dimensionalidad
    if embeddings:
        dim = len(embeddings[0])
        if _expected_embed_dim is None:
            _expected_embed_dim = dim
        else:
            invalid = [i for i, e in enumerate(embeddings) if len(e) != _expected_embed_dim]
            if invalid:
                log.warning(
                    f"Embeddings con dimensión incorrecta en posiciones {invalid[:5]}… "
                    f"(esperado={_expected_embed_dim}, encontrado={[len(embeddings[i]) for i in invalid[:5]]})"
                )
                # Filtrar los inválidos
                valid_mask = [i for i in range(len(embeddings)) if len(embeddings[i]) == _expected_embed_dim]
                ids        = [ids[i] for i in valid_mask]
                embeddings = [embeddings[i] for i in valid_mask]
                documents  = [documents[i] for i in valid_mask]
                metadatas  = [metadatas[i] for i in valid_mask]
                if not ids:
                    return

    # [V19-I5] Timeout proporcional al batch size
    batch_timeout = CHROMA_TIMEOUT + (len(ids) * 0.5)

    resp = session.post(
        f"{chroma_url}{_chroma_api_prefix}/collections/{collection_id}/upsert",
        json={
            "ids":        ids,
            "embeddings": embeddings,
            "documents":  documents,
            "metadatas":  metadatas,
        },
        timeout=batch_timeout,
    )
    resp.raise_for_status()


def chroma_delete_by_filepath(
    collection_id: str,
    rel_path: str,
    session: requests.Session,
    chroma_url: str,
) -> None:
    """
    Elimina todos los fragmentos de un archivo dado (por metadato source).
    [V18-I14] Manejo explícito de errores (no silencioso).
    """
    resp = session.post(
        f"{chroma_url}{_chroma_api_prefix}/collections/{collection_id}/delete",
        json={"where": {"source": rel_path}},
        timeout=CHROMA_TIMEOUT,
    )
    if resp.status_code == 200:
        log.debug(f"Fragmentos eliminados para: {rel_path}")
    elif resp.status_code == 404:
        log.debug(f"No existían fragmentos para: {rel_path}")
    else:
        log.warning(
            f"Error eliminando fragmentos de '{rel_path}': "
            f"HTTP {resp.status_code} — {resp.text[:200]}"
        )


def chroma_get_all_sources(
    collection_id: str,
    session: requests.Session,
    chroma_url: str,
) -> set:
    """
    [V18-I4] + [V19-I12] + [V20-I8] Obtiene todos los valores únicos de 'source'.
    Paginado para vaults grandes (>10000 chunks).
    [V20-I8] Logging de total esperado vs obtenido.
    """
    sources = set()
    try:
        count = chroma_count(collection_id, session, chroma_url)
        if count == 0:
            return sources

        # [V19-I12] Paginación para vaults grandes
        PAGE_SIZE = 5000
        offset = 0
        total_metadatas_received = 0

        while offset < count:
            limit = min(PAGE_SIZE, count - offset)
            resp = session.post(
                f"{chroma_url}{_chroma_api_prefix}/collections/{collection_id}/get",
                json={
                    "include": ["metadatas"],
                    "limit": limit,
                    "offset": offset,
                },
                timeout=CHROMA_TIMEOUT * 3,
            )
            if resp.status_code == 200:
                data = resp.json()
                metadatas = data.get("metadatas", [])
                total_metadatas_received += len(metadatas)
                for meta in metadatas:
                    if meta and "source" in meta:
                        sources.add(meta["source"])
                # Si devolvió menos de lo pedido, terminamos
                if len(metadatas) < limit:
                    break
            else:
                log.warning(f"Error en paginación de sources (offset={offset}): HTTP {resp.status_code}")
                break
            offset += limit

        # [V20-I8] Logging de total esperado vs obtenido
        if total_metadatas_received < count:
            log.warning(
                f"[V20-I8] chroma_get_all_sources: esperados {count} chunks, "
                f"recibidos {total_metadatas_received} ({len(sources)} fuentes únicas)"
            )
        else:
            log.debug(f"chroma_get_all_sources: {len(sources)} fuentes únicas de {count} chunks")

    except Exception as e:
        log.warning(f"Error obteniendo sources de ChromaDB: {e}")

    return sources


# ─────────────────────────────────────────────────────────────────────────────
# PROCESAMIENTO DE ARCHIVOS
# [V20-I9] Siempre delete antes de upsert (previene duplicados)
# ─────────────────────────────────────────────────────────────────────────────
def process_file(
    filepath: str,
    rel_path: str,
    collection_id: str,
    session: requests.Session,
    chroma_url: str,
    ollama_url: str,
    embed_model: str,
    max_file_kb: int,
    dry_run: bool = False,
) -> int:
    """
    Procesa un único archivo .md:
    1. Lee y preprocesa (limpia Markdown).
    2. Divide en chunks semánticos.
    3. Genera embeddings con rate limiting.
    4. Upsert en ChromaDB por lotes con metadatos enriquecidos.
    Retorna el número de fragmentos procesados.
    """
    # [V18-I10] Verificar tamaño
    file_size_kb = os.path.getsize(filepath) / 1024
    if file_size_kb > max_file_kb:
        log.warning(
            f"Archivo demasiado grande ({file_size_kb:.0f}KB > {max_file_kb}KB): {rel_path}"
        )
        # Procesar igualmente pero con advertencia

    text = read_md_file(filepath)
    if not text.strip():
        return 0

    # [V18-I3] Extraer metadatos enriquecidos
    title = extract_title(text, filepath)
    tags = extract_frontmatter_tags(text)
    mtime = datetime.fromtimestamp(
        os.path.getmtime(filepath), tz=timezone.utc
    ).isoformat()

    # [V18-I1] Chunking semántico
    chunks = chunk_text_semantic(text)
    if not chunks:
        return 0

    # [V20-I9] Siempre eliminar chunks previos antes de insertar nuevos
    # Previene duplicados si el state se pierde/corrompe
    if not dry_run:
        chroma_delete_by_filepath(collection_id, rel_path, session, chroma_url)

    ids        = []
    embeddings = []
    documents  = []
    metadatas  = []
    processed  = 0

    for i, chunk_data in enumerate(chunks):
        # [V19-I7] Verificar si se pidió shutdown
        if _shutdown_requested:
            log.info(f"Shutdown solicitado — interrumpiendo procesamiento de '{rel_path}'")
            break

        chunk_text_clean = chunk_data["text"]
        chunk_heading = chunk_data["heading"]

        try:
            emb = get_embedding(chunk_text_clean, session, ollama_url, embed_model)
        except requests.exceptions.ConnectionError:
            # [V19-I6] Ollama desconectado mid-indexación
            log.error(f"Ollama desconectado durante indexación de '{rel_path}' chunk {i}")
            log.error("Guardando estado parcial y abortando…")
            # Hacer upsert de lo que tenemos hasta ahora
            if ids and not dry_run:
                chroma_upsert_batch(collection_id, ids, embeddings, documents, metadatas, session, chroma_url)
            raise
        except Exception as e:
            log.debug(f"Embedding error en '{rel_path}' chunk {i}: {e}")
            continue

        ids.append(chunk_id(rel_path, i))
        embeddings.append(emb)
        documents.append(chunk_text_clean)
        metadatas.append({
            "source":       rel_path,
            "title":        title[:200],
            "heading":      chunk_heading[:200] if chunk_heading else "",
            "chunk_index":  i,
            "total_chunks": len(chunks),
            "mtime":        mtime,
            "tags":         ",".join(tags[:10]) if tags else "",
            "word_count":   len(chunk_text_clean.split()),
        })
        processed += 1

        # Upsert por lotes
        if len(ids) >= BATCH_SIZE:
            if not dry_run:
                chroma_upsert_batch(collection_id, ids, embeddings, documents, metadatas, session, chroma_url)
            ids = []; embeddings = []; documents = []; metadatas = []

    # Lote final
    if ids and not dry_run:
        chroma_upsert_batch(collection_id, ids, embeddings, documents, metadatas, session, chroma_url)

    return processed


# ─────────────────────────────────────────────────────────────────────────────
# [V18-I4] [V18-I15] PURGA DE ARCHIVOS ELIMINADOS
# ─────────────────────────────────────────────────────────────────────────────
def prune_deleted_files(
    collection_id: str,
    vault_dir: str,
    state: dict,
    session: requests.Session,
    chroma_url: str,
    dry_run: bool = False,
) -> int:
    """
    Detecta y elimina fragmentos de archivos que ya no existen en el vault.
    Retorna el número de archivos purgados.
    """
    log.info("Buscando archivos huérfanos en ChromaDB…")

    # Obtener todas las fuentes indexadas
    indexed_sources = chroma_get_all_sources(collection_id, session, chroma_url)
    if not indexed_sources:
        log.info("No se encontraron fuentes indexadas — nada que purgar")
        return 0

    # Verificar cuáles ya no existen en el vault
    orphans = []
    for source in indexed_sources:
        full_path = os.path.join(vault_dir, source)
        if not os.path.exists(full_path):
            orphans.append(source)

    if not orphans:
        log.info(f"✔ Todas las {len(indexed_sources)} fuentes indexadas existen en el vault")
        return 0

    log.info(f"Encontrados {len(orphans)} archivo(s) huérfano(s) para purgar")

    purged = 0
    for source in orphans:
        if dry_run:
            log.info(f"  [DRY-RUN] Purgaría: {source}")
        else:
            chroma_delete_by_filepath(collection_id, source, session, chroma_url)
            log.debug(f"  Purgado: {source}")
        purged += 1

        # Eliminar del estado incremental
        if source in state:
            del state[source]

    return purged


# ─────────────────────────────────────────────────────────────────────────────
# [V20-I10] ARGUMENTOS CLI — movidos a función llamada desde main()
# ─────────────────────────────────────────────────────────────────────────────
def _parse_args() -> argparse.Namespace:
    """[V20-I10] Parse de argumentos CLI. Se ejecuta solo desde main()."""
    p = argparse.ArgumentParser(
        description="Indexar vault Obsidian en ChromaDB (V20 — chunking semántico + auditoría integral)"
    )
    p.add_argument("--vault-dir",        default=None, help="Ruta al vault Obsidian")
    p.add_argument("--chroma-url",       default=None, help="URL de ChromaDB (ej. http://localhost:8001)")
    p.add_argument("--ollama-embed-url", default=None, help="URL embeddings Ollama CPU")
    p.add_argument("--state-dir",        default=None, help="Directorio para el estado incremental (ext4)")
    p.add_argument("--clean",   action="store_true", help="Borra todo y reindexar desde cero")
    p.add_argument("--stats",   action="store_true", help="Mostrar estadísticas de la colección")
    p.add_argument("--dry-run", action="store_true", help="Simular sin escribir en ChromaDB")
    p.add_argument("--prune",   action="store_true", help="Eliminar fragmentos de archivos ya inexistentes")
    p.add_argument("--verbose", action="store_true", help="Logging detallado por archivo")
    p.add_argument("--max-file-kb", type=int, default=500,
                   help="Tamaño máximo de archivo a indexar en KB (default: 500)")
    p.add_argument("--max-time", type=int, default=0,
                   help="[V20-I7] Timeout global en segundos (0=sin límite, default: 0)")
    return p.parse_args()


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
def main() -> None:
    global _partial_state, _expected_embed_dim

    # [V20-I10] argparse ejecutado aquí, no a nivel de módulo
    args = _parse_args()

    if args.verbose:
        log.setLevel(logging.DEBUG)

    # ── Configuración ──────────────────────────────────────────────────────
    vault_dir = (
        args.vault_dir
        or os.environ.get("VAULT_DIR", "/mnt/ai_core/obsidian_vault")
    )
    chroma_url = (
        args.chroma_url
        or os.environ.get("CHROMA_URL", "http://localhost:8001")
    )
    ollama_url = (
        args.ollama_embed_url
        or os.environ.get("OLLAMA_EMBED_URL", "http://localhost:11435/api/embeddings")
    )
    collection_name = os.environ.get("COLLECTION_NAME", "obsidian_vault")
    embed_model = os.environ.get("EMBED_MODEL", "nomic-embed-text")
    max_file_kb = args.max_file_kb

    # [V20-I2] Directorio de estado con fallback real
    state_dir_raw = (
        args.state_dir
        or os.environ.get("AGENT_DB_DIR")
        or os.environ.get("STATE_DIR")
        or os.path.join(os.path.expanduser("~"), "ai_cluster")
    )
    state_dir = _validate_state_dir(state_dir_raw)
    state_file = os.path.join(state_dir, ".indexar_vault_state.json")

    t_start = time.monotonic()
    max_time = args.max_time  # [V20-I7]

    print("═" * 66)
    print(" OMEN AI — Indexador de Vault V20 (chunking semántico + auditoría)")
    print(f" Vault:     {vault_dir}")
    print(f" Chroma:    {chroma_url}")
    print(f" Embed:     {ollama_url}")
    print(f" State:     {state_file}")
    print(f" State FS:  {_detect_filesystem(state_dir)}")
    print(f" Max file:  {max_file_kb}KB")
    if max_time > 0:
        print(f" Max time:  {max_time}s")
    modo = "DRY-RUN" if args.dry_run else ("CLEAN" if args.clean else "INCREMENTAL")
    if args.prune:
        modo += " + PRUNE"
    print(f" Modo:      {modo}")
    print("═" * 66)

    # Verificar que el vault existe
    if not os.path.isdir(vault_dir):
        log.error(f"El vault no existe: {vault_dir}")
        sys.exit(1)

    # [V20-I3] Crear sesión con retry adapter
    session = _create_session()

    # Verificar conectividad ChromaDB
    try:
        resp = session.get(f"{chroma_url}/api/v1/heartbeat", timeout=CONNECT_TIMEOUT)
        resp.raise_for_status()
        print("✔ ChromaDB: conectado")
    except Exception as e:
        log.error(f"ChromaDB no disponible ({chroma_url}): {e}")
        sys.exit(1)

    # [V19-I3] Detectar versión de API
    api_version = _detect_chroma_api_version(session, chroma_url)
    print(f"  API version: {api_version} (prefix: {_chroma_api_prefix})")

    # Verificar conectividad Ollama embeddings
    try:
        resp = session.post(
            ollama_url,
            json={"model": embed_model, "prompt": "test connection"},
            timeout=CONNECT_TIMEOUT * 2,
        )
        resp.raise_for_status()
        # Verificar que devuelve embedding válido
        test_emb = resp.json().get("embedding", [])
        if test_emb:
            _expected_embed_dim = len(test_emb)
            print(f"✔ Ollama embed ({embed_model}): conectado (dim={_expected_embed_dim})")
        else:
            print(f"✔ Ollama embed ({embed_model}): conectado (dim=?)")
    except Exception as e:
        log.error(f"Ollama embed no disponible: {e}")
        sys.exit(1)

    # Obtener/crear colección
    if args.clean and not args.dry_run:
        print("\n⚙ Modo --clean: eliminando colección existente…")
        collection_id = chroma_recreate_collection(session, chroma_url, collection_name)
        state = {}
        save_state(state, state_file)
        print(f"✔ Colección recreada: UUID={collection_id[:8]}…")
    else:
        collection_id = chroma_get_or_create_collection(session, chroma_url, collection_name)
        state = load_state(state_file)
        print(f"✔ Colección: UUID={collection_id[:8]}… | estado incremental: {len(state)} archivos")

    # Modo --stats
    if args.stats:
        count = chroma_count(collection_id, session, chroma_url)
        md_files = discover_md_files(vault_dir)
        elapsed = time.monotonic() - t_start
        print(f"\n📊 Estadísticas del vault:")
        print(f"   Fragmentos en ChromaDB:   {count}")
        print(f"   Archivos .md en el vault: {len(md_files)}")
        print(f"   Archivos indexados:       {len(state)}")
        print(f"   Archivos pendientes:      {len(md_files) - len(state)}")
        print(f"   Dimensión embeddings:     {_expected_embed_dim or '?'}")
        print(f"   API ChromaDB:             {api_version}")
        print(f"   Tiempo total:             {elapsed:.1f}s")
        return

    # [V18-I4] [V18-I15] Purga de archivos eliminados
    if args.prune or not args.clean:
        purged = prune_deleted_files(collection_id, vault_dir, state, session, chroma_url, dry_run=args.dry_run)
        if purged > 0:
            print(f"{'[DRY-RUN] ' if args.dry_run else ''}🗑 {purged} archivo(s) huérfano(s) purgados")
            if not args.dry_run:
                save_state(state, state_file)

    # Si solo se pidió --prune, terminar aquí
    if args.prune and not args.clean:
        elapsed = time.monotonic() - t_start
        print(f"\n✔ Purga completada en {elapsed:.1f}s")
        return

    # Descubrir archivos
    md_files = discover_md_files(vault_dir)
    print(f"\n📁 Archivos .md encontrados: {len(md_files)}")

    # Filtrar solo modificados (modo incremental)
    to_process = []
    for fp in md_files:
        rel = os.path.relpath(fp, vault_dir)
        sig = file_signature(fp)
        if args.clean or state.get(rel) != sig:
            to_process.append((fp, rel, sig))

    print(f"   → {len(to_process)} para procesar"
          f"{' (dry-run)' if args.dry_run else ''}")

    if not to_process:
        print("✔ Vault ya actualizado — nada que indexar")
        return

    # Procesar
    stats = {"ok": 0, "err": 0, "chunks": 0, "skipped": 0}
    new_state = dict(state)
    _partial_state = new_state  # Para signal handler (solo lectura del flag)

    for i, (fp, rel, sig) in enumerate(to_process, 1):
        # [V19-I7] [V20-I1] Verificar shutdown (flag marcado por signal handler)
        if _shutdown_requested:
            log.warning("Shutdown solicitado — guardando estado parcial")
            break

        # [V20-I7] Verificar timeout global
        if max_time > 0 and (time.monotonic() - t_start) > max_time:
            log.warning(f"Timeout global alcanzado ({max_time}s) — guardando estado parcial")
            break

        # [V18-I9] Barra de progreso
        if not args.verbose:
            progress_bar(i, len(to_process), prefix="  Indexando")
        else:
            log.info(f"[{i:3d}/{len(to_process)}] {rel}")

        try:
            n_chunks = process_file(
                fp, rel, collection_id, session,
                chroma_url, ollama_url, embed_model, max_file_kb,
                dry_run=args.dry_run,
            )

            if n_chunks > 0:
                stats["ok"] += 1
                stats["chunks"] += n_chunks
                new_state[rel] = sig
            else:
                stats["skipped"] += 1
                new_state[rel] = sig  # Marcar como procesado aunque sin chunks

            if args.verbose:
                log.info(f"  ✔ {n_chunks} fragmentos")

        except requests.exceptions.ConnectionError:
            # [V19-I6] Ollama desconectado — guardar estado parcial y abortar
            stats["err"] += 1
            log.error(f"Conexión perdida procesando '{rel}' — abortando indexación")
            log.error("El estado parcial se guardará. Reejecutar para continuar.")
            break

        except Exception as e:
            stats["err"] += 1
            log.warning(f"Error procesando '{rel}': {e}")
            if args.verbose:
                traceback.print_exc()

        # Guardar estado incremental cada 50 archivos
        if not args.dry_run and i % 50 == 0:
            save_state(new_state, state_file)

    # Guardar estado final
    if not args.dry_run:
        save_state(new_state, state_file)

    _partial_state = None  # Ya no necesario

    elapsed = time.monotonic() - t_start
    print(f"\n{'═' * 66}")
    print(f"{'[DRY-RUN] ' if args.dry_run else ''}Indexación completada:")
    print(f"   Archivos OK:      {stats['ok']}")
    print(f"   Archivos Error:   {stats['err']}")
    print(f"   Archivos vacíos:  {stats['skipped']}")
    print(f"   Fragmentos:       {stats['chunks']}")
    print(f"   Dimensión embed:  {_expected_embed_dim or '?'}")
    print(f"   API ChromaDB:     {api_version}")
    print(f"   Tiempo total:     {elapsed:.1f}s")
    if stats["ok"] > 0 and elapsed > 0:
        print(f"   Velocidad:        {stats['ok'] / elapsed:.1f} archivos/s")
    if args.dry_run:
        print("   ⚠ Dry-run: ningún dato fue escrito en ChromaDB")
    if _shutdown_requested:
        print("   ⚠ Indexación interrumpida por señal — estado parcial guardado")
    if max_time > 0 and (time.monotonic() - t_start) > max_time:
        print("   ⚠ Indexación interrumpida por timeout global — estado parcial guardado")
    print("═" * 66)


if __name__ == "__main__":
    main()
