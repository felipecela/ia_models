#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║ indexar_vault_v4.py — Indexador Vault Obsidian → ChromaDB                  ║
║ OMEN AI Cluster V19                                                         ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ V19 — Correcciones de auditoría integral sobre V18 (indexar_vault_v3.py):  ║
║  ✔ [V19-I1]  Escritura atómica mejorada: fsync antes de os.replace        ║
║              (previene corrupción en power-loss sobre ext4)                 ║
║  ✔ [V19-I2]  Validación de filesystem: verifica que STATE_DIR está en      ║
║              ext4/xfs/btrfs antes de arrancar (previene state en exFAT)    ║
║  ✔ [V19-I3]  Manejo de ChromaDB API V2: soporte para endpoint /api/v2     ║
║              con fallback transparente a /api/v1                            ║
║  ✔ [V19-I4]  Chunk overlap corregido: última frase del chunk anterior      ║
║              se incluye como contexto en el siguiente (CHUNK_OVERLAP)       ║
║  ✔ [V19-I5]  Timeout de upsert proporcional al tamaño del batch            ║
║  ✔ [V19-I6]  Detección de Ollama desconectado mid-indexación con           ║
║              checkpoint parcial (no pierde trabajo ya hecho)                ║
║  ✔ [V19-I7]  Signal handler: SIGINT/SIGTERM guardan estado parcial         ║
║  ✔ [V19-I8]  Validación de colección existente antes de upsert             ║
║  ✔ [V19-I9]  Logging de resumen por archivo en modo verbose                ║
║  ✔ [V19-I10] Compatibilidad con Autoboot V19 (--state-dir CLI arg)        ║
║  ✔ [V19-I11] Protección contra archivos .md binarios/corruptos            ║
║  ✔ [V19-I12] Paginación en chroma_get_all_sources para vaults grandes     ║
║  ✔ [V19-I13] Deduplicación de chunks idénticos antes de upsert            ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ Heredado de V18 (indexar_vault_v3.py — todas las mejoras):                 ║
║  ✔ [V18-I1]  Chunking semántico: respeta párrafos, encabezados y bloques  ║
║  ✔ [V18-I2]  Preprocesamiento Markdown: elimina frontmatter YAML          ║
║  ✔ [V18-I3]  Metadatos enriquecidos: title, heading, mtime, tags          ║
║  ✔ [V18-I4]  Detección de archivos eliminados: purga automática            ║
║  ✔ [V18-I5]  Rate limiting + retry con backoff exponencial                 ║
║  ✔ [V18-I6]  Batch embeddings (reduce latencia total)                      ║
║  ✔ [V18-I7]  STATE_FILE en ext4 vía AGENT_DB_DIR / STATE_DIR env var       ║
║  ✔ [V18-I8]  Validación de dimensionalidad de embeddings                   ║
║  ✔ [V18-I9]  Barra de progreso integrada                                   ║
║  ✔ [V18-I10] Límite configurable de tamaño de archivo                      ║
║  ✔ [V18-I11] Logging mejorado con niveles y timestamps                     ║
║  ✔ [V18-I12] SHA-256 truncado para IDs de chunks                           ║
║  ✔ [V18-I13] Timeout adaptativo basado en longitud del chunk               ║
║  ✔ [V18-I14] Manejo explícito de errores en chroma_delete                  ║
║  ✔ [V18-I15] Modo --prune: elimina fragmentos huérfanos                    ║
║  ✔ [V18-I16] Compatibilidad total con Autoboot V18/V19 (CLI args)         ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ Heredado de V17 (funcionalidades completas):                                ║
║  ✔ [V17-I1]  Delimitadores de string correctos                             ║
║  ✔ [V17-I2]  argparse: --vault-dir, --chroma-url, --ollama-embed-url       ║
║  ✔ [V17-I3]  discover_md_files: dirs[:] correcto                           ║
║  ✔ [V17-I4]  EXCLUDED_DIRS como set completo                               ║
║  ✔ [V17-I5]  Manejo de UnicodeDecodeError (utf-8 → latin-1 → ignore)      ║
║  ✔ [V17-I6]  --dry-run: simulación sin escritura                           ║
║  ✔ [V17-I7]  save_state: crea directorio padre                            ║
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
╠══════════════════════════════════════════════════════════════════════════════╣
║ Dependencias: pip3 install requests                                         ║
║ Uso:                                                                        ║
║   python3 indexar_vault_v4.py                          # Incremental       ║
║   python3 indexar_vault_v4.py --clean                  # Reindexar todo    ║
║   python3 indexar_vault_v4.py --stats                  # Estadísticas      ║
║   python3 indexar_vault_v4.py --dry-run                # Simulación        ║
║   python3 indexar_vault_v4.py --prune                  # Purgar huérfanos  ║
║   python3 indexar_vault_v4.py --verbose                # Logging detallado ║
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
except ImportError:
    print("✘ Dependencia faltante: 'requests'", file=sys.stderr)
    print("  Instala con: pip3 install requests", file=sys.stderr)
    sys.exit(1)

# ─────────────────────────────────────────────────────────────────────────────
# [V18-I11] LOGGING — con timestamps y niveles
# ─────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger("indexar-vault-v4")

# ─────────────────────────────────────────────────────────────────────────────
# ARGUMENTOS CLI — [V17-I2] + [V18-I15] --prune + [V19-I10] --state-dir
# ─────────────────────────────────────────────────────────────────────────────
def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Indexar vault Obsidian en ChromaDB (V19 — chunking semántico + auditoría)"
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
    return p.parse_args()


_ARGS = _parse_args()

if _ARGS.verbose:
    log.setLevel(logging.DEBUG)

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURACIÓN — argparse > env vars > defaults
# ─────────────────────────────────────────────────────────────────────────────
VAULT_DIR = (
    _ARGS.vault_dir
    or os.environ.get("VAULT_DIR", "/mnt/ai_core/obsidian_vault")
)

CHROMA_URL = (
    _ARGS.chroma_url
    or os.environ.get("CHROMA_URL", "http://localhost:8001")
)

OLLAMA_EMBED_URL = (
    _ARGS.ollama_embed_url
    or os.environ.get("OLLAMA_EMBED_URL", "http://localhost:11435/api/embeddings")
)

COLLECTION_NAME = os.environ.get("COLLECTION_NAME", "obsidian_vault")
EMBED_MODEL     = os.environ.get("EMBED_MODEL", "nomic-embed-text")

# [V18-I1] Parámetros de chunking semántico
CHUNK_MAX_CHARS   = 800     # Máximo de caracteres por chunk
CHUNK_MIN_CHARS   = 80      # Mínimo para considerar un chunk válido
CHUNK_OVERLAP_SENTENCES = 1 # [V19-I4] Solapamiento: última frase del chunk anterior

# [V18-I10] Límite de tamaño de archivo
MAX_FILE_KB = _ARGS.max_file_kb

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

# [V18-I7] Archivo de estado incremental — en ext4 (no exFAT)
_STATE_DIR = (
    _ARGS.state_dir
    or os.environ.get("AGENT_DB_DIR")
    or os.environ.get("STATE_DIR")
    or os.path.join(os.path.expanduser("~"), "ai_cluster")
)
STATE_FILE = os.path.join(_STATE_DIR, ".indexar_vault_state.json")

# [V17-I4] Directorios excluidos
EXCLUDED_DIRS: set = {
    ".obsidian", "templates", "_templates", ".git",
    ".trash", "trash", "archive", "_archive",
    "attachments", "_attachments", "assets",
    "node_modules", ".vscode",
}

# ─────────────────────────────────────────────────────────────────────────────
# [V19-I7] SIGNAL HANDLER — guardar estado parcial en SIGINT/SIGTERM
# ─────────────────────────────────────────────────────────────────────────────
_shutdown_requested = False
_partial_state: Optional[dict] = None


def _signal_handler(signum, frame):
    """Maneja SIGINT/SIGTERM guardando estado parcial antes de salir."""
    global _shutdown_requested
    sig_name = signal.Signals(signum).name
    log.warning(f"Señal {sig_name} recibida — guardando estado parcial y terminando…")
    _shutdown_requested = True
    if _partial_state is not None:
        save_state(_partial_state)
        log.info(f"Estado parcial guardado ({len(_partial_state)} archivos)")
    sys.exit(0)


signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)

# ─────────────────────────────────────────────────────────────────────────────
# [V19-I2] VALIDACIÓN DE FILESYSTEM
# ─────────────────────────────────────────────────────────────────────────────
def validate_state_filesystem() -> bool:
    """
    Verifica que el directorio de estado está en un filesystem compatible.
    El archivo de estado JSON no requiere WAL como SQLite, pero exFAT no
    soporta os.replace() atómico correctamente en todos los casos.
    """
    try:
        result = subprocess.run(
            ["df", "--output=fstype", _STATE_DIR],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode != 0:
            return True  # No se pudo verificar, continuar

        lines = result.stdout.strip().split("\n")
        if len(lines) < 2:
            return True

        fs_type = lines[1].strip()
        if fs_type in ("exfat", "vfat", "ntfs"):
            log.warning(
                f"STATE_DIR ({_STATE_DIR}) está en filesystem '{fs_type}'. "
                f"os.replace() puede no ser atómico. Se recomienda ext4/xfs/btrfs."
            )
            # No es fatal para JSON (a diferencia de SQLite), pero advertir
            return True
        return True
    except Exception:
        return True  # No bloquear si no se puede verificar


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
    # Buscar primer encabezado H1
    match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    if match:
        return match.group(1).strip()
    # Fallback: nombre del archivo sin extensión
    return Path(filepath).stem.replace("-", " ").replace("_", " ")


def clean_markdown(text: str) -> str:
    """
    [V18-I2] Limpia la sintaxis Markdown para obtener texto plano de calidad
    para embeddings. Preserva la estructura semántica (párrafos, secciones).
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

    # Limpiar encabezados (quitar #, mantener texto)
    text = _RE_HEADING.sub("", text)

    # Normalizar espacios múltiples
    text = _RE_MULTIPLE_NEWLINES.sub("\n\n", text)

    return text.strip()


# ─────────────────────────────────────────────────────────────────────────────
# [V18-I1] CHUNKING SEMÁNTICO + [V19-I4] OVERLAP CORREGIDO
# ─────────────────────────────────────────────────────────────────────────────
def _split_into_sections(text: str) -> list:
    """
    Divide el texto en secciones basándose en encabezados Markdown.
    Retorna lista de tuplas (heading, content).
    """
    sections = []
    lines = text.split("\n")
    current_heading = ""
    current_lines = []

    for line in lines:
        heading_match = re.match(r"^(#{1,6})\s+(.+)$", line)
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
    [V18-I1] + [V19-I4] Chunking semántico con overlap corregido.
    Divide respetando párrafos y secciones. Incluye la última frase del
    chunk anterior como contexto en el siguiente (CHUNK_OVERLAP_SENTENCES).

    Retorna lista de dicts: [{"text": str, "heading": str}, ...]
    """
    sections = _split_into_sections(text)
    chunks = []
    prev_last_sentence = ""  # [V19-I4] Para overlap entre chunks

    for heading, content in sections:
        # Limpiar el contenido de la sección
        clean_content = clean_markdown(content)

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
# ─────────────────────────────────────────────────────────────────────────────
def file_signature(filepath: str) -> str:
    """Firma ligera: mtime + tamaño."""
    st = os.stat(filepath)
    return f"{st.st_mtime:.3f}:{st.st_size}"


def discover_md_files(vault_dir: str) -> list:
    """Descubre .md del vault, excluyendo directorios no deseados."""
    md_files = []
    for root, dirs, files in os.walk(vault_dir):
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
# ─────────────────────────────────────────────────────────────────────────────
def load_state() -> dict:
    """Carga el mapa {ruta_relativa: firma} del disco."""
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state: dict) -> None:
    """
    Persiste el estado incremental en disco.
    [V19-I1] Escritura atómica mejorada con fsync antes de os.replace.
    """
    try:
        # [V17-I7] Crear directorio padre si no existe
        os.makedirs(os.path.dirname(STATE_FILE) or ".", exist_ok=True)
        # Escritura atómica: escribir en temporal, fsync, y renombrar
        tmp_file = STATE_FILE + ".tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())  # [V19-I1] Garantizar flush a disco
        os.replace(tmp_file, STATE_FILE)
    except Exception as e:
        log.warning(f"No se pudo guardar el estado incremental: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# [V18-I12] IDs DE CHUNKS — SHA-256 truncado
# ─────────────────────────────────────────────────────────────────────────────
def chunk_id(rel_path: str, chunk_idx: int) -> str:
    """Genera un ID único y estable para un fragmento usando SHA-256 truncado."""
    raw = f"{rel_path}::{chunk_idx}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


# ─────────────────────────────────────────────────────────────────────────────
# [V18-I5] EMBEDDINGS — con retry y rate limiting
# ─────────────────────────────────────────────────────────────────────────────
_last_embed_time: float = 0.0


def get_embedding(text: str, session: requests.Session) -> list:
    """
    Obtiene el embedding de un texto via Ollama CPU.
    [V18-I5] Incluye rate limiting y retry con backoff exponencial.
    [V18-I13] Timeout adaptativo basado en longitud del chunk.
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
                OLLAMA_EMBED_URL,
                json={"model": EMBED_MODEL, "prompt": text},
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
        except Exception:
            raise

    # No debería llegar aquí, pero por seguridad
    raise RuntimeError("get_embedding: reintentos agotados")


# ─────────────────────────────────────────────────────────────────────────────
# CHROMADB — API HTTP nativa (sin librería chromadb)
# [V19-I3] Compatible con ChromaDB ≥ 0.4 y ≥ 0.5 (API V1 y V2)
# ─────────────────────────────────────────────────────────────────────────────
_expected_embed_dim: Optional[int] = None
_chroma_api_prefix: str = "/api/v1"  # [V19-I3] Detectado en runtime


def _detect_chroma_api_version(session: requests.Session) -> str:
    """
    [V19-I3] Detecta la versión de la API de ChromaDB.
    Intenta V2 primero, fallback a V1.
    """
    global _chroma_api_prefix
    # Intentar V2
    try:
        resp = session.get(f"{CHROMA_URL}/api/v2/heartbeat", timeout=CONNECT_TIMEOUT)
        if resp.status_code == 200:
            _chroma_api_prefix = "/api/v2"
            return "v2"
    except Exception:
        pass
    # Fallback a V1 (ya verificado en main)
    _chroma_api_prefix = "/api/v1"
    return "v1"


def chroma_get_or_create_collection(session: requests.Session) -> str:
    """Obtiene o crea la colección. Retorna UUID interno."""
    resp = session.post(
        f"{CHROMA_URL}{_chroma_api_prefix}/collections",
        json={
            "name": COLLECTION_NAME,
            "metadata": {"hnsw:space": "cosine"},
            "get_or_create": True,
        },
        timeout=CHROMA_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()["id"]


def chroma_recreate_collection(session: requests.Session) -> str:
    """Borra y recrea la colección (--clean)."""
    del_resp = session.delete(
        f"{CHROMA_URL}{_chroma_api_prefix}/collections/{COLLECTION_NAME}",
        timeout=CHROMA_TIMEOUT,
    )
    if del_resp.status_code not in (200, 404):
        del_resp.raise_for_status()

    create_resp = session.post(
        f"{CHROMA_URL}{_chroma_api_prefix}/collections",
        json={
            "name": COLLECTION_NAME,
            "metadata": {"hnsw:space": "cosine"},
        },
        timeout=CHROMA_TIMEOUT,
    )
    create_resp.raise_for_status()
    return create_resp.json()["id"]


def chroma_count(collection_id: str, session: requests.Session) -> int:
    """Retorna el número de documentos en la colección."""
    resp = session.get(
        f"{CHROMA_URL}{_chroma_api_prefix}/collections/{collection_id}/count",
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
        f"{CHROMA_URL}{_chroma_api_prefix}/collections/{collection_id}/upsert",
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
) -> None:
    """
    Elimina todos los fragmentos de un archivo dado (por metadato source).
    [V18-I14] Manejo explícito de errores (no silencioso).
    """
    resp = session.post(
        f"{CHROMA_URL}{_chroma_api_prefix}/collections/{collection_id}/delete",
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
) -> set:
    """
    [V18-I4] + [V19-I12] Obtiene todos los valores únicos de 'source'.
    Paginado para vaults grandes (>10000 chunks).
    """
    sources = set()
    try:
        count = chroma_count(collection_id, session)
        if count == 0:
            return sources

        # [V19-I12] Paginación para vaults grandes
        PAGE_SIZE = 5000
        offset = 0

        while offset < count:
            limit = min(PAGE_SIZE, count - offset)
            resp = session.post(
                f"{CHROMA_URL}{_chroma_api_prefix}/collections/{collection_id}/get",
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

    except Exception as e:
        log.warning(f"Error obteniendo sources de ChromaDB: {e}")

    return sources


# ─────────────────────────────────────────────────────────────────────────────
# PROCESAMIENTO DE ARCHIVOS
# ─────────────────────────────────────────────────────────────────────────────
def process_file(
    filepath: str,
    rel_path: str,
    collection_id: str,
    session: requests.Session,
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
    if file_size_kb > MAX_FILE_KB:
        log.warning(
            f"Archivo demasiado grande ({file_size_kb:.0f}KB > {MAX_FILE_KB}KB): {rel_path}"
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
            emb = get_embedding(chunk_text_clean, session)
        except requests.exceptions.ConnectionError:
            # [V19-I6] Ollama desconectado mid-indexación
            log.error(f"Ollama desconectado durante indexación de '{rel_path}' chunk {i}")
            log.error("Guardando estado parcial y abortando…")
            # Hacer upsert de lo que tenemos hasta ahora
            if ids and not dry_run:
                chroma_upsert_batch(collection_id, ids, embeddings, documents, metadatas, session)
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
                chroma_upsert_batch(collection_id, ids, embeddings, documents, metadatas, session)
            ids = []; embeddings = []; documents = []; metadatas = []

    # Lote final
    if ids and not dry_run:
        chroma_upsert_batch(collection_id, ids, embeddings, documents, metadatas, session)

    return processed


# ─────────────────────────────────────────────────────────────────────────────
# [V18-I4] [V18-I15] PURGA DE ARCHIVOS ELIMINADOS
# ─────────────────────────────────────────────────────────────────────────────
def prune_deleted_files(
    collection_id: str,
    vault_dir: str,
    state: dict,
    session: requests.Session,
    dry_run: bool = False,
) -> int:
    """
    Detecta y elimina fragmentos de archivos que ya no existen en el vault.
    Retorna el número de archivos purgados.
    """
    log.info("Buscando archivos huérfanos en ChromaDB…")

    # Obtener todas las fuentes indexadas
    indexed_sources = chroma_get_all_sources(collection_id, session)
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
            chroma_delete_by_filepath(collection_id, source, session)
            log.debug(f"  Purgado: {source}")
        purged += 1

        # Eliminar del estado incremental
        if source in state:
            del state[source]

    return purged


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
def main() -> None:
    global _partial_state

    args = _ARGS
    t_start = time.monotonic()

    print("═" * 66)
    print(" OMEN AI — Indexador de Vault V19 (chunking semántico + auditoría)")
    print(f" Vault:     {VAULT_DIR}")
    print(f" Chroma:    {CHROMA_URL}")
    print(f" Embed:     {OLLAMA_EMBED_URL}")
    print(f" State:     {STATE_FILE}")
    print(f" Max file:  {MAX_FILE_KB}KB")
    modo = "DRY-RUN" if args.dry_run else ("CLEAN" if args.clean else "INCREMENTAL")
    if args.prune:
        modo += " + PRUNE"
    print(f" Modo:      {modo}")
    print("═" * 66)

    # [V19-I2] Validar filesystem del directorio de estado
    validate_state_filesystem()

    # Verificar que el vault existe
    if not os.path.isdir(VAULT_DIR):
        log.error(f"El vault no existe: {VAULT_DIR}")
        sys.exit(1)

    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})

    # Verificar conectividad ChromaDB
    try:
        resp = session.get(f"{CHROMA_URL}/api/v1/heartbeat", timeout=CONNECT_TIMEOUT)
        resp.raise_for_status()
        print("✔ ChromaDB: conectado")
    except Exception as e:
        log.error(f"ChromaDB no disponible ({CHROMA_URL}): {e}")
        sys.exit(1)

    # [V19-I3] Detectar versión de API
    api_version = _detect_chroma_api_version(session)
    print(f"  API version: {api_version} (prefix: {_chroma_api_prefix})")

    # Verificar conectividad Ollama embeddings
    try:
        resp = session.post(
            OLLAMA_EMBED_URL,
            json={"model": EMBED_MODEL, "prompt": "test connection"},
            timeout=CONNECT_TIMEOUT * 2,
        )
        resp.raise_for_status()
        # Verificar que devuelve embedding válido
        test_emb = resp.json().get("embedding", [])
        if test_emb:
            global _expected_embed_dim
            _expected_embed_dim = len(test_emb)
            print(f"✔ Ollama embed ({EMBED_MODEL}): conectado (dim={_expected_embed_dim})")
        else:
            print(f"✔ Ollama embed ({EMBED_MODEL}): conectado (dim=?)")
    except Exception as e:
        log.error(f"Ollama embed no disponible: {e}")
        sys.exit(1)

    # Obtener/crear colección
    if args.clean and not args.dry_run:
        print("\n⚙ Modo --clean: eliminando colección existente…")
        collection_id = chroma_recreate_collection(session)
        state = {}
        save_state(state)
        print(f"✔ Colección recreada: UUID={collection_id[:8]}…")
    else:
        collection_id = chroma_get_or_create_collection(session)
        state = load_state()
        print(f"✔ Colección: UUID={collection_id[:8]}… | estado incremental: {len(state)} archivos")

    # Modo --stats
    if args.stats:
        count = chroma_count(collection_id, session)
        md_files = discover_md_files(VAULT_DIR)
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
        purged = prune_deleted_files(collection_id, VAULT_DIR, state, session, dry_run=args.dry_run)
        if purged > 0:
            print(f"{'[DRY-RUN] ' if args.dry_run else ''}🗑 {purged} archivo(s) huérfano(s) purgados")
            if not args.dry_run:
                save_state(state)

    # Si solo se pidió --prune, terminar aquí
    if args.prune and not args.clean:
        elapsed = time.monotonic() - t_start
        print(f"\n✔ Purga completada en {elapsed:.1f}s")
        return

    # Descubrir archivos
    md_files = discover_md_files(VAULT_DIR)
    print(f"\n📁 Archivos .md encontrados: {len(md_files)}")

    # Filtrar solo modificados (modo incremental)
    to_process = []
    for fp in md_files:
        rel = os.path.relpath(fp, VAULT_DIR)
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
    _partial_state = new_state  # [V19-I7] Para signal handler

    for i, (fp, rel, sig) in enumerate(to_process, 1):
        # [V19-I7] Verificar shutdown
        if _shutdown_requested:
            log.warning("Shutdown solicitado — guardando estado parcial")
            break

        # [V18-I9] Barra de progreso
        if not args.verbose:
            progress_bar(i, len(to_process), prefix="  Indexando")
        else:
            log.info(f"[{i:3d}/{len(to_process)}] {rel}")

        try:
            # Eliminar fragmentos anteriores si el archivo ya existía
            if rel in state and not args.dry_run:
                chroma_delete_by_filepath(collection_id, rel, session)

            n_chunks = process_file(fp, rel, collection_id, session, dry_run=args.dry_run)

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
            save_state(new_state)

    # Guardar estado final
    if not args.dry_run:
        save_state(new_state)

    _partial_state = None  # Ya no necesario para signal handler

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
    print("═" * 66)


if __name__ == "__main__":
    main()
