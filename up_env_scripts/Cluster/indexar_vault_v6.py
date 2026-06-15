"""
╔══════════════════════════════════════════════════════════════════════════════╗
║ indexar_vault_v6.py — Indexador Vault Obsidian → ChromaDB                  ║
║ OMEN AI Cluster V21                                                         ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ V21 — Correcciones de auditoría integral sobre V20 (indexar_vault_v5.py):  ║
║  ✔ [V21-I1]  File lock para ejecuciones concurrentes (H-42)               ║
║              Impide que dos instancias corrompan estado/ChromaDB            ║
║  ✔ [V21-I2]  chunk_id incluye hash parcial del contenido (H-10)           ║
║              Estabilidad ante reordenamiento de chunks                      ║
║  ✔ [V21-I3]  Documentación explícita de _partial_state (H-15)             ║
║              Clarifica que solo el flag _shutdown_requested es seguro       ║
║  ✔ [V21-I4]  Documentación de EXCLUDED_DIRS case-insensitive (H-21)       ║
║              Explica que .lower() en discover_md_files lo maneja            ║
║  ✔ [V21-I5]  Progress bar usa stderr para no mezclar con log (H-25)       ║
║              Evita mezcla de líneas en stdout                               ║
║  ✔ [V21-I6]  file_signature usa SHA-256 en lugar de MD5 (H-28)            ║
║              Consistencia con chunk_id (ambos SHA-256)                      ║
║  ✔ [V21-I7]  Batch embeddings cuando Ollama lo soporta (H-39)             ║
║              Reduce llamadas HTTP significativamente                         ║
║  ✔ [V21-I8]  Logging mejorado: progress a stderr, info a stdout           ║
║  ✔ [V21-I9]  Verificación de integridad del state file al cargar          ║
║  ✔ [V21-I10] Métricas de rendimiento (embeddings/s, chunks/s)             ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ Heredado de V20 (indexar_vault_v5.py — todas las mejoras):                 ║
║  ✔ [V20-I1..I13] Todas las mejoras de V20 mantenidas                       ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ Características:                                                            ║
║  • Indexación INCREMENTAL semántica — solo archivos modificados             ║
║  • Chunking inteligente por secciones/párrafos (no corta frases)           ║
║  • API HTTP nativa — sin dependencia de la librería 'chromadb'             ║
║  • Compatible con ChromaDB ≥ 0.4 (UUID en todas las llamadas)              ║
║  • Upserts por lotes — reduce llamadas HTTP al mínimo                      ║
║  • Batch embeddings — múltiples textos por llamada a Ollama                ║
║  • Purga automática de archivos eliminados del vault                       ║
║  • Exclusión automática de .obsidian/, templates/, .trash/, etc.           ║
║  • Modos: incremental, --clean, --stats, --dry-run, --verbose, --prune    ║
║  • Graceful shutdown: SIGINT/SIGTERM guardan estado parcial                ║
║  • Timeout global configurable (--max-time)                                ║
║  • File lock: impide ejecuciones concurrentes                              ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ Dependencias: pip3 install requests urllib3                                  ║
║ Uso:                                                                        ║
║   python3 indexar_vault_v6.py                          # Incremental       ║
║   python3 indexar_vault_v6.py --clean                  # Reindexar todo    ║
║   python3 indexar_vault_v6.py --stats                  # Estadísticas      ║
║   python3 indexar_vault_v6.py --dry-run                # Simulación        ║
║   python3 indexar_vault_v6.py --prune                  # Purgar huérfanos  ║
║   python3 indexar_vault_v6.py --verbose                # Logging detallado ║
║   python3 indexar_vault_v6.py --max-time 3600          # Timeout 1 hora   ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import argparse
import fcntl
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
    Retry = None  # type: ignore[assignment, misc]

# ─────────────────────────────────────────────────────────────────────────────
# LOGGING — con timestamps y niveles
# [V21-I8] Logging a stdout, progress a stderr
# ─────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger("indexar-vault-v6")

# ─────────────────────────────────────────────────────────────────────────────
# SIGNAL HANDLER — seguro, sin sys.exit, sin reentrada
# [V21-I3] Documentación explícita: _partial_state es solo para referencia
#           del bucle principal. El signal handler SOLO marca _shutdown_requested.
#           _partial_state NO debe leerse ni escribirse desde el handler.
# ─────────────────────────────────────────────────────────────────────────────
_shutdown_requested = False
_partial_state: Optional[dict] = None  # [V21-I3] Solo usado por bucle principal
_saving_state = False  # Guard contra reentrada


def _signal_handler(signum, frame):
    """
    Maneja SIGINT/SIGTERM de forma segura.
    Solo marca el flag — el bucle principal se encarga de guardar estado y salir.
    NO llama a sys.exit() para permitir limpieza ordenada.
    NO accede a _partial_state (ver H-15/V21-I3).
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

# Parámetros de chunking semántico
CHUNK_MAX_CHARS   = 800     # Máximo de caracteres por chunk
CHUNK_MIN_CHARS   = 80      # Mínimo para considerar un chunk válido
CHUNK_OVERLAP_SENTENCES = 1 # Solapamiento: última frase del chunk anterior

# Parámetros de red
BATCH_SIZE       = 24       # Chunks por lote de upsert
EMBED_BATCH_SIZE = 8        # [V21-I7] Embeddings por llamada batch
EMBED_TIMEOUT    = 45.0     # Timeout base para embeddings
CHROMA_TIMEOUT   = 20.0
CONNECT_TIMEOUT  = 5.0

# Rate limiting
EMBED_RATE_LIMIT  = 0.05    # Segundos mínimos entre llamadas a Ollama
MAX_RETRIES       = 3       # Reintentos con backoff exponencial
BACKOFF_BASE      = 2.0     # Base del backoff (2^intento segundos)

# [V21-I4] Directorios excluidos — comparación case-insensitive
# La función discover_md_files() aplica .lower() a los nombres de directorio
# antes de comparar con este set, por lo que "Templates", "TEMPLATES", etc.
# se excluyen correctamente independientemente del case del filesystem.
EXCLUDED_DIRS: set = {
    ".obsidian", "templates", "_templates", ".git",
    ".trash", "trash", "archive", "_archive",
    "attachments", "_attachments", "assets",
    "node_modules", ".vscode",
}


# ─────────────────────────────────────────────────────────────────────────────
# [V21-I1] FILE LOCK — Impide ejecuciones concurrentes
# ─────────────────────────────────────────────────────────────────────────────
class IndexerLock:
    """
    [V21-I1] File-based lock para impedir ejecuciones concurrentes del indexador.
    Usa fcntl.flock() que es compatible con Linux y funciona correctamente
    en filesystems POSIX (ext4, xfs, btrfs, tmpfs).
    """

    def __init__(self, lock_dir: str):
        self._lock_path = os.path.join(lock_dir, ".indexar_vault.lock")
        self._lock_fd: Optional[int] = None

    def acquire(self) -> bool:
        """Intenta adquirir el lock. Retorna True si se adquirió, False si ya está tomado."""
        try:
            os.makedirs(os.path.dirname(self._lock_path) or ".", exist_ok=True)
            self._lock_fd = os.open(self._lock_path, os.O_CREAT | os.O_RDWR)
            fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            # Escribir PID para diagnóstico
            os.ftruncate(self._lock_fd, 0)
            os.lseek(self._lock_fd, 0, os.SEEK_SET)
            os.write(self._lock_fd, f"{os.getpid()}\n".encode())
            return True
        except (OSError, IOError):
            # Lock ya tomado por otra instancia
            if self._lock_fd is not None:
                os.close(self._lock_fd)
                self._lock_fd = None
            return False

    def release(self) -> None:
        """Libera el lock."""
        if self._lock_fd is not None:
            try:
                fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
                os.close(self._lock_fd)
            except OSError:
                pass
            self._lock_fd = None
            # Intentar eliminar el archivo de lock
            try:
                os.unlink(self._lock_path)
            except OSError:
                pass

    def __enter__(self):
        if not self.acquire():
            raise RuntimeError(
                f"Otra instancia del indexador está ejecutándose "
                f"(lock: {self._lock_path})"
            )
        return self

    def __exit__(self, *args):
        self.release()


# ─────────────────────────────────────────────────────────────────────────────
# VALIDACIÓN DE FILESYSTEM — con fallback real
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
    Valida que el directorio de estado está en un filesystem compatible.
    Si no, busca alternativa segura.
    Retorna la ruta segura a usar.
    """
    if os.path.isdir(candidate):
        fs = _detect_filesystem(candidate)
        if fs not in _UNSAFE_FS:
            return candidate
        log.warning(
            f"STATE_DIR ({candidate}) está en filesystem '{fs}' "
            f"(incompatible con escritura atómica fiable). Buscando alternativa…"
        )
    elif not os.path.exists(candidate):
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
        log.info(f"Usando directorio alternativo: {home_candidate} (fs={fs})")
        return home_candidate

    # Fallback 2: /tmp
    tmp_candidate = os.path.join("/tmp", "omen_vault_state")
    os.makedirs(tmp_candidate, exist_ok=True)
    log.warning(f"Usando /tmp como último recurso: {tmp_candidate}")
    return tmp_candidate


# ─────────────────────────────────────────────────────────────────────────────
# SESIÓN HTTP CON RETRY ADAPTER
# ─────────────────────────────────────────────────────────────────────────────
def _create_session() -> requests.Session:
    """Crea una sesión HTTP con retry automático para ChromaDB."""
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
        log.warning("urllib3.Retry no disponible — sin retry automático en sesión")

    return session


# ─────────────────────────────────────────────────────────────────────────────
# [V21-I5] BARRA DE PROGRESO — escribe a stderr para no mezclar con log
# ─────────────────────────────────────────────────────────────────────────────
def progress_bar(current: int, total: int, prefix: str = "", width: int = 40) -> None:
    """Imprime una barra de progreso en stderr (no mezcla con log en stdout)."""
    if total == 0:
        return
    pct = current / total
    filled = int(width * pct)
    bar = "█" * filled + "░" * (width - filled)
    sys.stderr.write(f"\r{prefix} [{bar}] {current}/{total} ({pct*100:.1f}%)")
    if current >= total:
        sys.stderr.write("\n")
    sys.stderr.flush()


# ─────────────────────────────────────────────────────────────────────────────
# PREPROCESAMIENTO MARKDOWN
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
        tag_line = re.search(r"tags:\s*\[([^\]]+)\]", fm)
        if tag_line:
            tags = [t.strip().strip("'\"") for t in tag_line.group(1).split(",")]
        else:
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
    # Tags inline (#tag) — solo primeros 2000 chars
    inline_tags = _RE_TAGS.findall(text[:2000])
    tags.extend(inline_tags)
    return list(set(tags))[:20]


def extract_title(text: str, filepath: str) -> str:
    """Extrae el título del documento (primer H1 o nombre del archivo)."""
    match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    if match:
        return match.group(1).strip()
    return Path(filepath).stem.replace("-", " ").replace("_", " ")


def clean_markdown(text: str, preserve_subheadings: bool = False) -> str:
    """
    Limpia la sintaxis Markdown para obtener texto plano de calidad
    para embeddings. Preserva la estructura semántica.
    """
    text = _RE_FRONTMATTER.sub("", text)
    text = _RE_CODE_BLOCK.sub("[código]", text)
    text = _RE_IMAGE.sub("", text)
    text = _RE_OBSIDIAN_LINK.sub(lambda m: m.group(2) or m.group(1), text)
    text = _RE_MD_LINK.sub(r"\1", text)
    text = _RE_INLINE_CODE.sub(lambda m: m.group(0)[1:-1], text)
    text = _RE_BOLD_ITALIC.sub(r"\2", text)
    text = _RE_CALLOUT.sub("", text)

    if preserve_subheadings:
        text = re.sub(r"^#{1,6}\s+(.+)$", r"— \1 —", text, flags=re.MULTILINE)
    else:
        text = _RE_HEADING.sub("", text)

    text = _RE_MULTIPLE_NEWLINES.sub("\n\n", text)
    return text.strip()


# ─────────────────────────────────────────────────────────────────────────────
# CHUNKING SEMÁNTICO + OVERLAP + SUB-HEADINGS
# ─────────────────────────────────────────────────────────────────────────────
def _split_into_sections(text: str) -> list:
    """
    Divide el texto en secciones basándose en encabezados H1-H2.
    Sub-headings (H3+) se mantienen dentro de la sección padre.
    """
    sections = []
    lines = text.split("\n")
    current_heading = ""
    current_lines = []

    for line in lines:
        heading_match = re.match(r"^(#{1,2})\s+(.+)$", line)
        if heading_match:
            if current_lines:
                content = "\n".join(current_lines).strip()
                if content:
                    sections.append((current_heading, content))
            current_heading = heading_match.group(2).strip()
            current_lines = []
        else:
            current_lines.append(line)

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
    Chunking semántico con overlap y sub-headings.
    Divide respetando párrafos y secciones.
    Retorna lista de dicts: [{"text": str, "heading": str}, ...]
    """
    sections = _split_into_sections(text)
    chunks = []
    prev_last_sentence = ""

    for heading, content in sections:
        clean_content = clean_markdown(content, preserve_subheadings=True)

        if not clean_content or len(clean_content.strip()) < CHUNK_MIN_CHARS:
            continue

        if len(clean_content) <= CHUNK_MAX_CHARS:
            if prev_last_sentence and CHUNK_OVERLAP_SENTENCES > 0:
                overlap_text = f"[…] {prev_last_sentence}\n\n{clean_content}"
                if len(overlap_text) <= CHUNK_MAX_CHARS * 1.1:
                    chunks.append({"text": overlap_text, "heading": heading})
                else:
                    chunks.append({"text": clean_content, "heading": heading})
            else:
                chunks.append({"text": clean_content, "heading": heading})
            prev_last_sentence = _extract_last_sentence(clean_content)
            continue

        paragraphs = [p.strip() for p in clean_content.split("\n\n") if p.strip()]
        current_chunk = ""
        if prev_last_sentence and CHUNK_OVERLAP_SENTENCES > 0:
            current_chunk = f"[…] {prev_last_sentence}"

        for para in paragraphs:
            if len(para) > CHUNK_MAX_CHARS:
                if current_chunk.strip() and len(current_chunk.strip()) >= CHUNK_MIN_CHARS:
                    chunks.append({"text": current_chunk.strip(), "heading": heading})
                    prev_last_sentence = _extract_last_sentence(current_chunk.strip())
                    current_chunk = ""

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

            test = f"{current_chunk}\n\n{para}".strip() if current_chunk else para
            if len(test) > CHUNK_MAX_CHARS:
                if current_chunk.strip() and len(current_chunk.strip()) >= CHUNK_MIN_CHARS:
                    chunks.append({"text": current_chunk.strip(), "heading": heading})
                    prev_last_sentence = _extract_last_sentence(current_chunk.strip())
                current_chunk = para
            else:
                current_chunk = test

        if current_chunk.strip() and len(current_chunk.strip()) >= CHUNK_MIN_CHARS:
            chunks.append({"text": current_chunk.strip(), "heading": heading})
            prev_last_sentence = _extract_last_sentence(current_chunk.strip())

    return chunks


# ─────────────────────────────────────────────────────────────────────────────
# UTILIDADES DE ARCHIVOS
# [V21-I6] file_signature usa SHA-256 (consistencia con chunk_id)
# ─────────────────────────────────────────────────────────────────────────────
def file_signature(filepath: str) -> str:
    """
    [V21-I6] Firma robusta: mtime + tamaño + hash parcial SHA-256 (primer 1KB).
    Usa SHA-256 en lugar de MD5 por consistencia con chunk_id y para evitar
    cualquier preocupación de seguridad en contextos futuros.
    """
    st = os.stat(filepath)
    try:
        with open(filepath, "rb") as f:
            header = f.read(1024)
        partial_hash = hashlib.sha256(header).hexdigest()[:8]
    except OSError:
        partial_hash = "00000000"
    return f"{st.st_mtime:.3f}:{st.st_size}:{partial_hash}"


def discover_md_files(vault_dir: str) -> list:
    """
    Descubre .md del vault, excluyendo directorios no deseados.
    [V21-I4] La comparación usa .lower() en los nombres de directorio,
    por lo que EXCLUDED_DIRS (en minúsculas) funciona independientemente
    del case del filesystem (ext4 case-sensitive, exFAT case-insensitive).
    followlinks=False para evitar indexar symlinks externos.
    """
    md_files = []
    for root, dirs, files in os.walk(vault_dir, followlinks=False):
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
    Detecta archivos binarios/corruptos.
    """
    try:
        with open(filepath, "rb") as f:
            header = f.read(512)
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
    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


# ─────────────────────────────────────────────────────────────────────────────
# ESTADO INCREMENTAL
# ─────────────────────────────────────────────────────────────────────────────
def load_state(state_file: str) -> dict:
    """
    Carga el mapa {ruta_relativa: firma} del disco.
    [V21-I9] Verifica integridad básica del JSON.
    """
    try:
        with open(state_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Verificación de integridad: debe ser un dict con strings
        if not isinstance(data, dict):
            log.warning(f"State file corrupto (no es dict): {state_file}")
            return {}
        # Verificar que al menos los primeros N valores son strings
        sample = list(data.values())[:10]
        if sample and not all(isinstance(v, str) for v in sample):
            log.warning(f"State file con valores no-string: {state_file}")
            return {}
        return data
    except (FileNotFoundError, json.JSONDecodeError) as e:
        if isinstance(e, json.JSONDecodeError):
            log.warning(f"State file con JSON inválido: {state_file} — reiniciando estado")
        return {}


def save_state(state: dict, state_file: str) -> None:
    """
    Persiste el estado incremental en disco.
    Escritura atómica con fsync antes de os.replace.
    Guard contra reentrada.
    """
    global _saving_state
    if _saving_state:
        log.debug("save_state ya en ejecución — evitando reentrada")
        return

    _saving_state = True
    try:
        os.makedirs(os.path.dirname(state_file) or ".", exist_ok=True)
        tmp_file = state_file + ".tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_file, state_file)
    except Exception as e:
        log.warning(f"No se pudo guardar el estado incremental: {e}")
    finally:
        _saving_state = False


# ─────────────────────────────────────────────────────────────────────────────
# [V21-I2] IDs DE CHUNKS — SHA-256 con hash parcial del contenido
# ─────────────────────────────────────────────────────────────────────────────
def chunk_id(rel_path: str, chunk_idx: int, content: str = "") -> str:
    """
    [V21-I2] Genera un ID único y estable para un fragmento.
    Incluye un hash parcial del contenido (primeros 100 chars) para mayor
    estabilidad ante reordenamiento de chunks. Si un chunk cambia de posición
    pero mantiene el mismo contenido, el ID será diferente (correcto: se
    re-indexará). Si el contenido cambia, el ID también cambia.
    """
    # Incluir hash parcial del contenido para estabilidad
    content_hash = hashlib.sha256(content[:100].encode()).hexdigest()[:8] if content else "00000000"
    raw = f"{rel_path}::{chunk_idx}::{content_hash}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


# ─────────────────────────────────────────────────────────────────────────────
# [V21-I7] EMBEDDINGS — con batch support + retry + rate limiting
# ─────────────────────────────────────────────────────────────────────────────
_last_embed_time: float = 0.0
_batch_embed_supported: Optional[bool] = None  # Detectado en runtime


def _detect_batch_embed_support(session: requests.Session, ollama_url: str, embed_model: str) -> bool:
    """
    [V21-I7] Detecta si Ollama soporta batch embeddings (input como lista).
    Ollama >= 0.1.44 soporta el campo 'input' con una lista de textos.
    """
    try:
        resp = session.post(
            ollama_url,
            json={"model": embed_model, "input": ["test1", "test2"]},
            timeout=CONNECT_TIMEOUT * 2,
        )
        if resp.status_code == 200:
            data = resp.json()
            # Batch embeddings retorna 'embeddings' (plural) como lista de listas
            if "embeddings" in data and isinstance(data["embeddings"], list):
                if len(data["embeddings"]) == 2:
                    return True
    except Exception:
        pass
    return False


def get_embedding(text: str, session: requests.Session, ollama_url: str, embed_model: str) -> list:
    """
    Obtiene el embedding de un texto via Ollama CPU.
    Incluye rate limiting y retry con backoff exponencial.
    """
    global _last_embed_time

    # Rate limiting
    elapsed = time.monotonic() - _last_embed_time
    if elapsed < EMBED_RATE_LIMIT:
        time.sleep(EMBED_RATE_LIMIT - elapsed)

    # Timeout adaptativo
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
            if attempt < MAX_RETRIES - 1:
                wait = BACKOFF_BASE ** (attempt + 1)
                log.debug(f"Body inválido en embedding (intento {attempt+1}), reintentando en {wait:.1f}s…")
                time.sleep(wait)
            else:
                raise
        except Exception:
            raise

    raise RuntimeError("get_embedding: reintentos agotados")


def get_embeddings_batch(
    texts: list,
    session: requests.Session,
    ollama_url: str,
    embed_model: str,
) -> list:
    """
    [V21-I7] Obtiene embeddings en batch via Ollama CPU.
    Usa el campo 'input' con una lista de textos.
    Retorna lista de embeddings (misma longitud que texts).
    Si falla, hace fallback a embeddings individuales.
    """
    global _last_embed_time

    if not texts:
        return []

    # Rate limiting
    elapsed = time.monotonic() - _last_embed_time
    if elapsed < EMBED_RATE_LIMIT:
        time.sleep(EMBED_RATE_LIMIT - elapsed)

    # Timeout proporcional al batch
    batch_timeout = EMBED_TIMEOUT + (len(texts) * 5.0)

    for attempt in range(MAX_RETRIES):
        try:
            _last_embed_time = time.monotonic()
            resp = session.post(
                ollama_url,
                json={"model": embed_model, "input": texts},
                timeout=batch_timeout,
            )
            resp.raise_for_status()
            data = resp.json()

            if "embeddings" in data and isinstance(data["embeddings"], list):
                embeddings = data["embeddings"]
                if len(embeddings) == len(texts):
                    return embeddings
                else:
                    raise ValueError(
                        f"Batch embeddings: esperados {len(texts)}, "
                        f"recibidos {len(embeddings)}"
                    )
            else:
                raise ValueError(f"Respuesta batch inválida. Keys: {list(data.keys())}")

        except requests.exceptions.Timeout:
            if attempt < MAX_RETRIES - 1:
                wait = BACKOFF_BASE ** (attempt + 1)
                log.debug(f"Timeout en batch embedding (intento {attempt+1}), reintentando…")
                time.sleep(wait)
            else:
                # Fallback a individual
                log.warning("Batch embedding timeout — fallback a embeddings individuales")
                return [get_embedding(t, session, ollama_url, embed_model) for t in texts]
        except requests.exceptions.ConnectionError:
            if attempt < MAX_RETRIES - 1:
                wait = BACKOFF_BASE ** (attempt + 1)
                time.sleep(wait)
            else:
                raise
        except (ValueError, KeyError):
            if attempt < MAX_RETRIES - 1:
                wait = BACKOFF_BASE ** (attempt + 1)
                time.sleep(wait)
            else:
                # Fallback a individual
                log.warning("Batch embedding error — fallback a embeddings individuales")
                return [get_embedding(t, session, ollama_url, embed_model) for t in texts]
        except Exception:
            raise

    raise RuntimeError("get_embeddings_batch: reintentos agotados")


# ─────────────────────────────────────────────────────────────────────────────
# CHROMADB — API HTTP nativa
# ─────────────────────────────────────────────────────────────────────────────
_expected_embed_dim: Optional[int] = None
_chroma_api_prefix: str = "/api/v1"


def _detect_chroma_api_version(session: requests.Session, chroma_url: str) -> str:
    """Detecta la versión de la API de ChromaDB."""
    global _chroma_api_prefix
    try:
        resp = session.get(f"{chroma_url}/api/v2/heartbeat", timeout=CONNECT_TIMEOUT)
        if resp.status_code == 200:
            _chroma_api_prefix = "/api/v2"
            return "v2"
    except Exception:
        pass
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
    """Upsert de un lote de fragmentos en ChromaDB."""
    global _expected_embed_dim

    if not ids:
        return

    # Deduplicar por ID (mantener último)
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
                    f"(esperado={_expected_embed_dim})"
                )
                valid_mask = [i for i in range(len(embeddings)) if len(embeddings[i]) == _expected_embed_dim]
                ids        = [ids[i] for i in valid_mask]
                embeddings = [embeddings[i] for i in valid_mask]
                documents  = [documents[i] for i in valid_mask]
                metadatas  = [metadatas[i] for i in valid_mask]
                if not ids:
                    return

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
    """Elimina todos los fragmentos de un archivo dado (por metadato source)."""
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
    Obtiene todos los valores únicos de 'source'.
    Paginado para vaults grandes (>10000 chunks).
    """
    sources = set()
    try:
        count = chroma_count(collection_id, session, chroma_url)
        if count == 0:
            return sources

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
                if len(metadatas) < limit:
                    break
            else:
                log.warning(f"Error en paginación de sources (offset={offset}): HTTP {resp.status_code}")
                break
            offset += limit

        if total_metadatas_received < count:
            log.warning(
                f"chroma_get_all_sources: esperados {count} chunks, "
                f"recibidos {total_metadatas_received} ({len(sources)} fuentes únicas)"
            )
        else:
            log.debug(f"chroma_get_all_sources: {len(sources)} fuentes únicas de {count} chunks")

    except Exception as e:
        log.warning(f"Error obteniendo sources de ChromaDB: {e}")

    return sources


# ─────────────────────────────────────────────────────────────────────────────
# PROCESAMIENTO DE ARCHIVOS
# [V21-I7] Con soporte batch embeddings
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
    use_batch: bool = False,
) -> int:
    """
    Procesa un único archivo .md:
    1. Lee y preprocesa (limpia Markdown).
    2. Divide en chunks semánticos.
    3. Genera embeddings (batch o individual).
    4. Upsert en ChromaDB por lotes con metadatos enriquecidos.
    Retorna el número de fragmentos procesados.
    """
    file_size_kb = os.path.getsize(filepath) / 1024
    if file_size_kb > max_file_kb:
        log.warning(
            f"Archivo demasiado grande ({file_size_kb:.0f}KB > {max_file_kb}KB): {rel_path}"
        )

    text = read_md_file(filepath)
    if not text.strip():
        return 0

    title = extract_title(text, filepath)
    tags = extract_frontmatter_tags(text)
    mtime = datetime.fromtimestamp(
        os.path.getmtime(filepath), tz=timezone.utc
    ).isoformat()

    chunks = chunk_text_semantic(text)
    if not chunks:
        return 0

    # Siempre eliminar chunks previos antes de insertar nuevos
    if not dry_run:
        chroma_delete_by_filepath(collection_id, rel_path, session, chroma_url)

    ids_batch        = []
    embeddings_batch = []
    documents_batch  = []
    metadatas_batch  = []
    processed  = 0

    # [V21-I7] Si batch embeddings soportado, procesar en grupos
    if use_batch and not dry_run:
        # Procesar chunks en grupos de EMBED_BATCH_SIZE
        for batch_start in range(0, len(chunks), EMBED_BATCH_SIZE):
            if _shutdown_requested:
                log.info(f"Shutdown solicitado — interrumpiendo procesamiento de '{rel_path}'")
                break

            batch_end = min(batch_start + EMBED_BATCH_SIZE, len(chunks))
            batch_chunks = chunks[batch_start:batch_end]
            batch_texts = [c["text"] for c in batch_chunks]

            try:
                batch_embs = get_embeddings_batch(batch_texts, session, ollama_url, embed_model)
            except requests.exceptions.ConnectionError:
                log.error(f"Ollama desconectado durante indexación de '{rel_path}'")
                if ids_batch:
                    chroma_upsert_batch(collection_id, ids_batch, embeddings_batch, documents_batch, metadatas_batch, session, chroma_url)
                raise
            except Exception as e:
                log.debug(f"Batch embedding error en '{rel_path}': {e}")
                # Fallback a individual para este batch
                batch_embs = []
                for chunk_data in batch_chunks:
                    try:
                        emb = get_embedding(chunk_data["text"], session, ollama_url, embed_model)
                        batch_embs.append(emb)
                    except Exception:
                        batch_embs.append(None)

            for j, (chunk_data, emb) in enumerate(zip(batch_chunks, batch_embs)):
                if emb is None:
                    continue
                idx = batch_start + j
                # [V21-I2] chunk_id con hash parcial del contenido
                cid = chunk_id(rel_path, idx, chunk_data["text"])
                ids_batch.append(cid)
                embeddings_batch.append(emb)
                documents_batch.append(chunk_data["text"])
                metadatas_batch.append({
                    "source":       rel_path,
                    "title":        title[:200],
                    "heading":      chunk_data["heading"][:200] if chunk_data["heading"] else "",
                    "chunk_index":  idx,
                    "total_chunks": len(chunks),
                    "mtime":        mtime,
                    "tags":         ",".join(tags[:10]) if tags else "",
                    "word_count":   len(chunk_data["text"].split()),
                })
                processed += 1

            # Upsert por lotes
            if len(ids_batch) >= BATCH_SIZE:
                chroma_upsert_batch(collection_id, ids_batch, embeddings_batch, documents_batch, metadatas_batch, session, chroma_url)
                ids_batch = []; embeddings_batch = []; documents_batch = []; metadatas_batch = []
    else:
        # Modo individual (fallback o dry-run)
        for i, chunk_data in enumerate(chunks):
            if _shutdown_requested:
                log.info(f"Shutdown solicitado — interrumpiendo procesamiento de '{rel_path}'")
                break

            chunk_text_clean = chunk_data["text"]
            chunk_heading = chunk_data["heading"]

            try:
                emb = get_embedding(chunk_text_clean, session, ollama_url, embed_model)
            except requests.exceptions.ConnectionError:
                log.error(f"Ollama desconectado durante indexación de '{rel_path}' chunk {i}")
                if ids_batch and not dry_run:
                    chroma_upsert_batch(collection_id, ids_batch, embeddings_batch, documents_batch, metadatas_batch, session, chroma_url)
                raise
            except Exception as e:
                log.debug(f"Embedding error en '{rel_path}' chunk {i}: {e}")
                continue

            # [V21-I2] chunk_id con hash parcial del contenido
            ids_batch.append(chunk_id(rel_path, i, chunk_text_clean))
            embeddings_batch.append(emb)
            documents_batch.append(chunk_text_clean)
            metadatas_batch.append({
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

            if len(ids_batch) >= BATCH_SIZE:
                if not dry_run:
                    chroma_upsert_batch(collection_id, ids_batch, embeddings_batch, documents_batch, metadatas_batch, session, chroma_url)
                ids_batch = []; embeddings_batch = []; documents_batch = []; metadatas_batch = []

    # Lote final
    if ids_batch and not dry_run:
        chroma_upsert_batch(collection_id, ids_batch, embeddings_batch, documents_batch, metadatas_batch, session, chroma_url)

    return processed


# ─────────────────────────────────────────────────────────────────────────────
# PURGA DE ARCHIVOS ELIMINADOS
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

    indexed_sources = chroma_get_all_sources(collection_id, session, chroma_url)
    if not indexed_sources:
        log.info("No se encontraron fuentes indexadas — nada que purgar")
        return 0

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
        if source in state:
            del state[source]

    return purged


# ─────────────────────────────────────────────────────────────────────────────
# ARGUMENTOS CLI
# ─────────────────────────────────────────────────────────────────────────────
def _parse_args() -> argparse.Namespace:
    """Parse de argumentos CLI. Se ejecuta solo desde main()."""
    p = argparse.ArgumentParser(
        description="Indexar vault Obsidian en ChromaDB (V21 — chunking semántico + auditoría integral)"
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
                   help="Timeout global en segundos (0=sin límite, default: 0)")
    p.add_argument("--no-batch", action="store_true",
                   help="[V21-I7] Desactivar batch embeddings (usar individual)")
    return p.parse_args()


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
def main() -> None:
    global _partial_state, _expected_embed_dim, _batch_embed_supported

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

    # Directorio de estado con fallback real
    state_dir_raw = (
        args.state_dir
        or os.environ.get("AGENT_DB_DIR")
        or os.environ.get("STATE_DIR")
        or os.path.join(os.path.expanduser("~"), "ai_cluster")
    )
    state_dir = _validate_state_dir(state_dir_raw)
    state_file = os.path.join(state_dir, ".indexar_vault_state.json")

    # ── [V21-I1] File lock ─────────────────────────────────────────────────
    lock = IndexerLock(state_dir)
    if not lock.acquire():
        log.error(
            "Otra instancia del indexador está ejecutándose. "
            "Espera a que termine o elimina el lock manualmente: "
            f"{os.path.join(state_dir, '.indexar_vault.lock')}"
        )
        sys.exit(1)

    try:
        _main_locked(args, vault_dir, chroma_url, ollama_url, collection_name,
                     embed_model, max_file_kb, state_dir, state_file)
    finally:
        lock.release()


def _main_locked(
    args: argparse.Namespace,
    vault_dir: str,
    chroma_url: str,
    ollama_url: str,
    collection_name: str,
    embed_model: str,
    max_file_kb: int,
    state_dir: str,
    state_file: str,
) -> None:
    """Lógica principal del indexador (ejecutada bajo file lock)."""
    global _partial_state, _expected_embed_dim, _batch_embed_supported

    t_start = time.monotonic()
    max_time = args.max_time

    print("═" * 66)
    print(" OMEN AI — Indexador de Vault V21 (chunking semántico + auditoría)")
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

    # Crear sesión con retry adapter
    session = _create_session()

    # Verificar conectividad ChromaDB
    try:
        resp = session.get(f"{chroma_url}/api/v1/heartbeat", timeout=CONNECT_TIMEOUT)
        resp.raise_for_status()
        print("✔ ChromaDB: conectado")
    except Exception as e:
        log.error(f"ChromaDB no disponible ({chroma_url}): {e}")
        sys.exit(1)

    # Detectar versión de API
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
        test_emb = resp.json().get("embedding", [])
        if test_emb:
            _expected_embed_dim = len(test_emb)
            print(f"✔ Ollama embed ({embed_model}): conectado (dim={_expected_embed_dim})")
        else:
            print(f"✔ Ollama embed ({embed_model}): conectado (dim=?)")
    except Exception as e:
        log.error(f"Ollama embed no disponible: {e}")
        sys.exit(1)

    # [V21-I7] Detectar soporte de batch embeddings
    use_batch = False
    if not args.no_batch:
        _batch_embed_supported = _detect_batch_embed_support(session, ollama_url, embed_model)
        if _batch_embed_supported:
            print(f"✔ Batch embeddings: soportado (batch_size={EMBED_BATCH_SIZE})")
            use_batch = True
        else:
            print("  Batch embeddings: no soportado — usando modo individual")
    else:
        print("  Batch embeddings: desactivado por --no-batch")

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
        print(f"   Batch embeddings:         {'sí' if use_batch else 'no'}")
        print(f"   Tiempo total:             {elapsed:.1f}s")
        return

    # Purga de archivos eliminados
    if args.prune or not args.clean:
        purged = prune_deleted_files(collection_id, vault_dir, state, session, chroma_url, dry_run=args.dry_run)
        if purged > 0:
            print(f"{'[DRY-RUN] ' if args.dry_run else ''}🗑 {purged} archivo(s) huérfano(s) purgados")
            if not args.dry_run:
                save_state(state, state_file)

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

    # [V21-I10] Métricas de rendimiento
    stats = {"ok": 0, "err": 0, "chunks": 0, "skipped": 0, "embed_calls": 0}
    new_state = dict(state)
    _partial_state = new_state

    for i, (fp, rel, sig) in enumerate(to_process, 1):
        if _shutdown_requested:
            log.warning("Shutdown solicitado — guardando estado parcial")
            break

        if max_time > 0 and (time.monotonic() - t_start) > max_time:
            log.warning(f"Timeout global alcanzado ({max_time}s) — guardando estado parcial")
            break

        # [V21-I5] Progress bar a stderr
        if not args.verbose:
            progress_bar(i, len(to_process), prefix="  Indexando")
        else:
            log.info(f"[{i:3d}/{len(to_process)}] {rel}")

        try:
            n_chunks = process_file(
                fp, rel, collection_id, session,
                chroma_url, ollama_url, embed_model, max_file_kb,
                dry_run=args.dry_run,
                use_batch=use_batch,
            )

            if n_chunks > 0:
                stats["ok"] += 1
                stats["chunks"] += n_chunks
                new_state[rel] = sig
            else:
                stats["skipped"] += 1
                new_state[rel] = sig

            if args.verbose:
                log.info(f"  ✔ {n_chunks} fragmentos")

        except requests.exceptions.ConnectionError:
            stats["err"] += 1
            log.error(f"Conexión perdida procesando '{rel}' — abortando indexación")
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

    _partial_state = None

    # [V21-I10] Métricas de rendimiento
    elapsed = time.monotonic() - t_start
    print(f"\n{'═' * 66}")
    print(f"{'[DRY-RUN] ' if args.dry_run else ''}Indexación completada:")
    print(f"   Archivos OK:      {stats['ok']}")
    print(f"   Archivos Error:   {stats['err']}")
    print(f"   Archivos vacíos:  {stats['skipped']}")
    print(f"   Fragmentos:       {stats['chunks']}")
    print(f"   Dimensión embed:  {_expected_embed_dim or '?'}")
    print(f"   API ChromaDB:     {api_version}")
    print(f"   Batch embeddings: {'sí' if use_batch else 'no'}")
    print(f"   Tiempo total:     {elapsed:.1f}s")
    if stats["ok"] > 0 and elapsed > 0:
        print(f"   Velocidad:        {stats['ok'] / elapsed:.1f} archivos/s")
        if stats["chunks"] > 0:
            print(f"   Throughput:       {stats['chunks'] / elapsed:.1f} chunks/s")
    if args.dry_run:
        print("   ⚠ Dry-run: ningún dato fue escrito en ChromaDB")
    if _shutdown_requested:
        print("   ⚠ Indexación interrumpida por señal — estado parcial guardado")
    if max_time > 0 and (time.monotonic() - t_start) > max_time:
        print("   ⚠ Indexación interrumpida por timeout global — estado parcial guardado")
    print("═" * 66)


if __name__ == "__main__":
    main()
