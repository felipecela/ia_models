#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║ indexar_vault.py — Indexador Vault Obsidian → ChromaDB                     ║
║ OMEN AI Cluster V17                                                         ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ V17 — Correcciones de auditoría:                                            ║
║  ✔ [V17-I1]  SyntaxError: delimitadores de string y paréntesis corregidos  ║
║  ✔ [V17-I2]  argparse: --vault-dir, --chroma-url, --ollama-embed-url        ║
║              aceptados desde CLI (compatibilidad con Autoboot V17)          ║
║  ✔ [V17-I3]  discover_md_files: dirs[:] correcto (no dirs = [...])         ║
║  ✔ [V17-I4]  EXCLUDED_DIRS definido como set[str] completo (cierra con }   ║
║  ✔ [V17-I5]  Manejo de UnicodeDecodeError por ficheros .md con encoding     ║
║              no-UTF-8 (intenta latin-1 antes de ignorar)                   ║
║  ✔ [V17-I6]  --dry-run: imprime resumen sin tocar ChromaDB                 ║
║  ✔ [V17-I7]  save_state: crea directorio padre si no existe                ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ Características:                                                            ║
║  • Indexación INCREMENTAL — solo procesa archivos modificados               ║
║  • API HTTP nativa — sin dependencia de la librería 'chromadb'             ║
║  • Compatible con ChromaDB ≥ 0.4 (usa UUID en todas las llamadas)          ║
║  • Upserts por lotes — reduce llamadas HTTP al mínimo                      ║
║  • Exclusión automática de .obsidian/, templates/, .trash/, etc.           ║
║  • Modos: incremental (def.), --clean, --stats, --dry-run, --verbose       ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ Dependencias: pip3 install requests                                         ║
║ Uso:                                                                        ║
║   python3 indexar_vault.py                          # Incremental          ║
║   python3 indexar_vault.py --clean                  # Reindexar todo       ║
║   python3 indexar_vault.py --stats                  # Estadísticas         ║
║   python3 indexar_vault.py --dry-run                # Simulación           ║
║   python3 indexar_vault.py --verbose                # Logging detallado    ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import argparse
import hashlib
import json
import os
import sys
import time
import traceback
from pathlib import Path

try:
    import requests
except ImportError:
    print("✘ Dependencia faltante: 'requests'", file=sys.stderr)
    print("  Instala con: pip3 install requests", file=sys.stderr)
    sys.exit(1)

# ─────────────────────────────────────────────────────────────────────────────
# ARGUMENTOS CLI — [V17-I2] sobreescribibles vía argparse (Autoboot V17)
# ─────────────────────────────────────────────────────────────────────────────
def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Indexar vault Obsidian en ChromaDB")
    p.add_argument("--vault-dir",       default=None, help="Ruta al vault Obsidian")
    p.add_argument("--chroma-url",      default=None, help="URL de ChromaDB (ej. http://localhost:8001)")
    p.add_argument("--ollama-embed-url",default=None, help="URL embeddings Ollama CPU")
    p.add_argument("--clean",   action="store_true", help="Borra todo y reindexar desde cero")
    p.add_argument("--stats",   action="store_true", help="Mostrar estadísticas de la colección")
    p.add_argument("--dry-run", action="store_true", help="Simular sin escribir en ChromaDB")
    p.add_argument("--verbose", action="store_true", help="Logging por archivo")
    return p.parse_args()

_ARGS = _parse_args()

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURACIÓN — argparse > env vars > defaults
# [V17-I1] Todos los strings con delimitadores de cierre correctos
# ─────────────────────────────────────────────────────────────────────────────
VAULT_DIR = (
    _ARGS.vault_dir
    or os.environ.get("VAULT_DIR", "/home/fcela-ga/sgoinfre/ai_core/obsidian_vault")
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
EMBED_MODEL     = os.environ.get("EMBED_MODEL",     "nomic-embed-text")

# Parámetros de chunking
CHUNK_SIZE    = 512
CHUNK_OVERLAP = 64
MIN_CHUNK_LEN = 50

# Parámetros de red
BATCH_SIZE      = 32
EMBED_TIMEOUT   = 30.0
CHROMA_TIMEOUT  = 20.0
CONNECT_TIMEOUT = 5.0

# Archivo de estado incremental — en ext4 junto al script
STATE_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    ".indexar_vault_state.json",
)

# [V17-I4] EXCLUDED_DIRS con llaves de cierre correctas
EXCLUDED_DIRS: set = {
    ".obsidian", "templates", "_templates", ".git",
    ".trash", "trash", "archive", "_archive",
    "attachments",
}

VERBOSE = _ARGS.verbose

# ─────────────────────────────────────────────────────────────────────────────
# UTILIDADES
# ─────────────────────────────────────────────────────────────────────────────

def chunk_text(text: str) -> list:
    """Divide texto en fragmentos con solapamiento."""
    chunks = []
    start = 0
    while start < len(text):
        end   = min(start + CHUNK_SIZE, len(text))
        chunk = text[start:end]
        if len(chunk.strip()) >= MIN_CHUNK_LEN:
            chunks.append(chunk)
        start += CHUNK_SIZE - CHUNK_OVERLAP
    return chunks


def file_signature(filepath: str) -> str:
    """Firma ligera: mtime + tamaño."""
    st = os.stat(filepath)
    return f"{st.st_mtime:.3f}:{st.st_size}"


def discover_md_files(vault_dir: str) -> list:
    """Descubre .md del vault, excluyendo directorios no deseados."""
    md_files = []
    for root, dirs, files in os.walk(vault_dir):
        # [V17-I3] Modificación in-place de dirs para que os.walk no entre en excluidos
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
    """
    for enc in ("utf-8", "latin-1", "utf-8-sig"):
        try:
            with open(filepath, "r", encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    # último recurso
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
    """Persiste el estado incremental en disco."""
    try:
        # [V17-I7] Crear directorio padre si no existe
        os.makedirs(os.path.dirname(STATE_FILE) or ".", exist_ok=True)
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"\n⚠ No se pudo guardar el estado incremental: {e}", file=sys.stderr)

# ─────────────────────────────────────────────────────────────────────────────
# EMBEDDINGS — Ollama CPU HTTP API
# ─────────────────────────────────────────────────────────────────────────────

def get_embedding(text: str, session: requests.Session) -> list:
    """Obtiene el embedding de un texto via Ollama CPU."""
    resp = session.post(
        OLLAMA_EMBED_URL,
        json={"model": EMBED_MODEL, "prompt": text},
        timeout=EMBED_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    if "embedding" not in data:
        raise ValueError(f"Ollama no devolvió 'embedding'. Respuesta: {data}")
    return data["embedding"]

# ─────────────────────────────────────────────────────────────────────────────
# CHROMADB — API HTTP nativa (sin librería chromadb)
# Compatible con ChromaDB ≥ 0.4
# ─────────────────────────────────────────────────────────────────────────────

def chroma_get_or_create_collection(session: requests.Session) -> str:
    """Obtiene o crea la colección. Retorna UUID interno."""
    resp = session.post(
        f"{CHROMA_URL}/api/v1/collections",
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
        f"{CHROMA_URL}/api/v1/collections/{COLLECTION_NAME}",
        timeout=CHROMA_TIMEOUT,
    )
    if del_resp.status_code not in (200, 404):
        del_resp.raise_for_status()

    create_resp = session.post(
        f"{CHROMA_URL}/api/v1/collections",
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
        f"{CHROMA_URL}/api/v1/collections/{collection_id}/count",
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
    """Upsert de un lote de fragmentos en ChromaDB."""
    resp = session.post(
        f"{CHROMA_URL}/api/v1/collections/{collection_id}/upsert",
        json={
            "ids":        ids,
            "embeddings": embeddings,
            "documents":  documents,
            "metadatas":  metadatas,
        },
        timeout=CHROMA_TIMEOUT,
    )
    resp.raise_for_status()


def chroma_delete_by_filepath(
    collection_id: str,
    rel_path: str,
    session: requests.Session,
) -> None:
    """Elimina todos los fragmentos de un archivo dado (por metadato source)."""
    resp = session.post(
        f"{CHROMA_URL}/api/v1/collections/{collection_id}/delete",
        json={"where": {"source": rel_path}},
        timeout=CHROMA_TIMEOUT,
    )
    if resp.status_code != 200:
        # 404 = no existían → aceptable
        pass

# ─────────────────────────────────────────────────────────────────────────────
# PROCESAMIENTO DE ARCHIVOS
# ─────────────────────────────────────────────────────────────────────────────

def chunk_id(rel_path: str, chunk_idx: int) -> str:
    """Genera un ID único y estable para un fragmento."""
    raw = f"{rel_path}:{chunk_idx}"
    return hashlib.md5(raw.encode()).hexdigest()


def process_file(
    filepath: str,
    rel_path: str,
    collection_id: str,
    session: requests.Session,
    dry_run: bool = False,
) -> int:
    """
    Procesa un único archivo .md:
    1. Lee, divide en chunks.
    2. Genera embeddings.
    3. Upsert en ChromaDB por lotes.
    Retorna el número de fragmentos procesados.
    """
    text = read_md_file(filepath)
    chunks = chunk_text(text)
    if not chunks:
        return 0

    ids        = []
    embeddings = []
    documents  = []
    metadatas  = []

    for i, chunk in enumerate(chunks):
        try:
            emb = get_embedding(chunk, session)
        except Exception as e:
            print(f"  ⚠ Embedding error en '{rel_path}' chunk {i}: {e}", file=sys.stderr)
            continue

        ids.append(chunk_id(rel_path, i))
        embeddings.append(emb)
        documents.append(chunk)
        metadatas.append({
            "source":      rel_path,
            "chunk_index": i,
            "total_chunks": len(chunks),
        })

        # Upsert por lotes
        if len(ids) >= BATCH_SIZE:
            if not dry_run:
                chroma_upsert_batch(collection_id, ids, embeddings, documents, metadatas, session)
            ids = []; embeddings = []; documents = []; metadatas = []

    # Lote final
    if ids and not dry_run:
        chroma_upsert_batch(collection_id, ids, embeddings, documents, metadatas, session)

    return len(chunks)

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    args = _ARGS
    t_start = time.monotonic()

    print("═" * 66)
    print(f" OMEN AI — Indexador de Vault V17")
    print(f" Vault:   {VAULT_DIR}")
    print(f" Chroma:  {CHROMA_URL}")
    print(f" Embed:   {OLLAMA_EMBED_URL}")
    print(f" Modo:    {'DRY-RUN' if args.dry_run else ('CLEAN' if args.clean else 'INCREMENTAL')}")
    print("═" * 66)

    # Verificar que el vault existe
    if not os.path.isdir(VAULT_DIR):
        print(f"✘ El vault no existe: {VAULT_DIR}", file=sys.stderr)
        sys.exit(1)

    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})

    # Verificar conectividad
    try:
        resp = session.get(f"{CHROMA_URL}/api/v1/heartbeat", timeout=CONNECT_TIMEOUT)
        resp.raise_for_status()
        print("✔ ChromaDB: conectado")
    except Exception as e:
        print(f"✘ ChromaDB no disponible ({CHROMA_URL}): {e}", file=sys.stderr)
        sys.exit(1)

    try:
        resp = session.post(
            OLLAMA_EMBED_URL,
            json={"model": EMBED_MODEL, "prompt": "test"},
            timeout=CONNECT_TIMEOUT,
        )
        resp.raise_for_status()
        print(f"✔ Ollama embed ({EMBED_MODEL}): conectado")
    except Exception as e:
        print(f"✘ Ollama embed no disponible: {e}", file=sys.stderr)
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
        elapsed  = time.monotonic() - t_start
        print(f"\n📊 Estadísticas del vault:")
        print(f"   Fragmentos en ChromaDB:   {count}")
        print(f"   Archivos .md en el vault: {len(md_files)}")
        print(f"   Archivos indexados:       {len(state)}")
        print(f"   Archivos pendientes:      {len(md_files) - len(state)}")
        print(f"   Tiempo total:             {elapsed:.1f}s")
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
          f"{'(dry-run)' if args.dry_run else ''}")

    if not to_process:
        print("✔ Vault ya actualizado — nada que indexar")
        return

    # Procesar
    stats = {"ok": 0, "err": 0, "chunks": 0}
    new_state = dict(state)

    for i, (fp, rel, sig) in enumerate(to_process, 1):
        prefix = f"  [{i:3d}/{len(to_process)}]"
        if VERBOSE:
            print(f"{prefix} {rel}")
        try:
            # Eliminar fragmentos anteriores si el archivo ya existía
            if rel in state and not args.dry_run:
                chroma_delete_by_filepath(collection_id, rel, session)

            n_chunks = process_file(fp, rel, collection_id, session, dry_run=args.dry_run)
            stats["ok"]     += 1
            stats["chunks"] += n_chunks
            new_state[rel]   = sig

            if VERBOSE:
                print(f"{prefix} ✔ {n_chunks} fragmentos")

        except Exception as e:
            stats["err"] += 1
            print(f"{prefix} ✘ {rel}: {e}", file=sys.stderr)
            if VERBOSE:
                traceback.print_exc()

        # Guardar estado incremental cada 50 archivos
        if not args.dry_run and i % 50 == 0:
            save_state(new_state)

    # Guardar estado final
    if not args.dry_run:
        save_state(new_state)

    elapsed = time.monotonic() - t_start
    print(f"\n{'═'*66}")
    print(f"{'[DRY-RUN] ' if args.dry_run else ''}Indexación completada:")
    print(f"   Archivos OK:    {stats['ok']}")
    print(f"   Archivos Error: {stats['err']}")
    print(f"   Fragmentos:     {stats['chunks']}")
    print(f"   Tiempo total:   {elapsed:.1f}s")
    if args.dry_run:
        print("   ⚠ Dry-run: ningún dato fue escrito en ChromaDB")
    print("═" * 66)


if __name__ == "__main__":
    main()
