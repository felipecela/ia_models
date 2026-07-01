#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  indexar_vault.py — Indexador del vault Obsidian → ChromaDB                ║
║  Parte del OMEN AI Cluster V15                                              ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Características:                                                            ║
║  • Indexación INCREMENTAL — solo procesa archivos modificados              ║
║  • API HTTP nativa — sin dependencia de la librería 'chromadb'             ║
║    Compatible con ChromaDB ≥ 0.4 (usa UUID en todas las llamadas)          ║
║  • Upserts por lotes — reduce llamadas HTTP al mínimo                      ║
║  • Exclusión automática de .obsidian/, templates/, .trash/, etc.           ║
║  • Modos: incremental (def.), --clean, --stats, --dry-run, --verbose       ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Dependencias: pip3 install requests  (solo stdlib + requests)             ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Uso:                                                                        ║
║    python3 indexar_vault.py              # Incremental (solo cambios)      ║
║    python3 indexar_vault.py --clean      # Borra todo y reindexar          ║
║    python3 indexar_vault.py --stats      # Estadísticas de la colección    ║
║    python3 indexar_vault.py --dry-run    # Simula sin escribir             ║
║    python3 indexar_vault.py --verbose    # Logging por archivo             ║
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
#  CONFIGURACIÓN — sobreescribible vía variables de entorno
# ─────────────────────────────────────────────────────────────────────────────
VAULT_DIR = os.environ.get(
    "VAULT_DIR",
    "/home/fcela-ga/sgoinfre/ai_core/obsidian_vault",
)
# ChromaDB (contenedor Docker, puerto 8001)
CHROMA_URL = os.environ.get("CHROMA_URL", "http://localhost:8001")

# Ollama instancia CPU (:11435) — misma que usa el router para embeddings
# Usar la instancia CPU evita bloquear la GPU durante la indexación
OLLAMA_EMBED_URL = os.environ.get(
    "OLLAMA_EMBED_URL",
    "http://localhost:11435/api/embeddings",
)
COLLECTION_NAME = os.environ.get("COLLECTION_NAME", "obsidian_vault")
EMBED_MODEL     = os.environ.get("EMBED_MODEL",     "nomic-embed-text")

# Parámetros de chunking — consistentes con el RAG del router
CHUNK_SIZE    = 512   # caracteres por fragmento
CHUNK_OVERLAP = 64    # solapamiento entre fragmentos consecutivos
MIN_CHUNK_LEN = 50    # fragmentos más cortos se descartan

# Parámetros de red
BATCH_SIZE     = 32    # fragmentos por llamada upsert a ChromaDB
EMBED_TIMEOUT  = 30.0  # segundos por llamada de embedding
CHROMA_TIMEOUT = 20.0  # segundos por llamada a ChromaDB
CONNECT_TIMEOUT = 5.0  # segundos para verificación de conectividad

# Archivo de estado para indexación incremental (en el mismo directorio del script)
STATE_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    ".indexar_vault_state.json",
)

# Directorios ignorados dentro del vault (comparación insensible al case)
EXCLUDED_DIRS: set[str] = {
    ".obsidian", "templates", "_templates", ".git",
    ".trash", "trash", "archive", "_archive",
    "attachments",  # imágenes/PDFs — no son Markdown
}

# ─────────────────────────────────────────────────────────────────────────────
#  UTILIDADES — chunking y firma de archivos
# ─────────────────────────────────────────────────────────────────────────────

def chunk_text(text: str) -> list[str]:
    """
    Divide un texto en fragmentos de CHUNK_SIZE caracteres con
    CHUNK_OVERLAP de solapamiento entre fragmentos consecutivos.
    Descarta fragmentos vacíos o muy cortos.
    """
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + CHUNK_SIZE, len(text))
        chunk = text[start:end]
        if len(chunk.strip()) >= MIN_CHUNK_LEN:
            chunks.append(chunk)
        start += CHUNK_SIZE - CHUNK_OVERLAP
    return chunks


def file_signature(filepath: str) -> str:
    """
    Firma ligera de un archivo: mtime + tamaño en bytes.
    No lee el contenido — O(1) en tiempo.
    """
    st = os.stat(filepath)
    return f"{st.st_mtime:.3f}:{st.st_size}"


def discover_md_files(vault_dir: str) -> list[str]:
    """
    Descubre todos los .md del vault excluyendo directorios no deseados.
    Retorna lista ordenada de rutas absolutas.
    """
    md_files: list[str] = []
    for root, dirs, files in os.walk(vault_dir):
        # Modificar dirs in-place para que os.walk no entre en excluidos
        dirs[:] = [
            d for d in dirs
            if d.lower() not in EXCLUDED_DIRS and not d.startswith(".")
        ]
        for fname in files:
            if fname.endswith(".md") and not fname.startswith("."):
                md_files.append(os.path.join(root, fname))
    return sorted(md_files)


# ─────────────────────────────────────────────────────────────────────────────
#  ESTADO INCREMENTAL — persiste qué archivos ya están indexados
# ─────────────────────────────────────────────────────────────────────────────

def load_state() -> dict[str, str]:
    """Carga el mapa {ruta_relativa: firma} del disco. Retorna {} si no existe."""
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state: dict[str, str]) -> None:
    """Persiste el estado incremental en disco."""
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"\n⚠  No se pudo guardar el estado incremental: {e}", file=sys.stderr)


# ─────────────────────────────────────────────────────────────────────────────
#  EMBEDDINGS — Ollama CPU HTTP API
# ─────────────────────────────────────────────────────────────────────────────

def get_embedding(text: str, session: requests.Session) -> list[float]:
    """Llama a Ollama CPU para obtener el embedding de un texto."""
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
#  CHROMADB — API HTTP nativa (sin librería chromadb)
#  Compatible con ChromaDB ≥ 0.4: siempre usa UUID interno (no nombre)
# ─────────────────────────────────────────────────────────────────────────────

def chroma_get_or_create_collection(session: requests.Session) -> str:
    """
    Obtiene la colección por nombre o la crea si no existe.
    Retorna el UUID interno que ChromaDB ≥ 0.4 requiere en todas las operaciones.
    """
    resp = session.post(
        f"{CHROMA_URL}/api/v1/collections",
        json={
            "name":         COLLECTION_NAME,
            "metadata":     {"hnsw:space": "cosine"},
            "get_or_create": True,
        },
        timeout=CHROMA_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()["id"]


def chroma_recreate_collection(session: requests.Session) -> str:
    """
    Borra la colección y la recrea vacía (modo --clean).
    Retorna el UUID de la colección nueva.
    """
    del_resp = session.delete(
        f"{CHROMA_URL}/api/v1/collections/{COLLECTION_NAME}",
        timeout=CHROMA_TIMEOUT,
    )
    # 404 = no existía todavía → aceptable
    if del_resp.status_code not in (200, 404):
        del_resp.raise_for_status()

    create_resp = session.post(
        f"{CHROMA_URL}/api/v1/collections",
        json={
            "name":     COLLECTION_NAME,
            "metadata": {"hnsw:space": "cosine"},
        },
        timeout=CHROMA_TIMEOUT,
    )
    create_resp.raise_for_status()
    return create_resp.json()["id"]


def chroma_count(collection_id: str, session: requests.Session) -> int:
    """Retorna el número total de fragmentos en la colección."""
    resp = session.get(
        f"{CHROMA_URL}/api/v1/collections/{collection_id}/count",
        timeout=CHROMA_TIMEOUT,
    )
    resp.raise_for_status()
    # ChromaDB retorna un entero JSON directamente
    return int(resp.json())


def chroma_upsert_batch(
    collection_id: str,
    ids:        list[str],
    embeddings: list[list[float]],
    documents:  list[str],
    metadatas:  list[dict],
    session:    requests.Session,
) -> None:
    """Inserta o actualiza un lote de fragmentos en ChromaDB."""
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


def chroma_delete_by_source(
    collection_id: str, source: str, session: requests.Session
) -> None:
    """
    Borra TODOS los fragmentos de un archivo fuente específico.
    Necesario cuando un archivo cambia: número de chunks puede variar
    y chroma_upsert no elimina los IDs huérfanos del batch anterior.
    """
    resp = session.post(
        f"{CHROMA_URL}/api/v1/collections/{collection_id}/delete",
        json={"where": {"source": {"$eq": source}}},
        timeout=CHROMA_TIMEOUT,
    )
    # 200 OK o 404 (no había fragmentos de esa fuente) son ambos correctos
    if resp.status_code not in (200, 404):
        resp.raise_for_status()


def chroma_get_sample_sources(
    collection_id: str, session: requests.Session, limit: int = 20
) -> set[str]:
    """Recupera una muestra de metadatos para mostrar en --stats."""
    resp = session.post(
        f"{CHROMA_URL}/api/v1/collections/{collection_id}/get",
        json={"limit": limit, "include": ["metadatas"]},
        timeout=CHROMA_TIMEOUT,
    )
    resp.raise_for_status()
    metas = resp.json().get("metadatas") or []
    return {m.get("source", "?") for m in metas if m}


# ─────────────────────────────────────────────────────────────────────────────
#  INDEXACIÓN DE UN ARCHIVO
# ─────────────────────────────────────────────────────────────────────────────

def index_file(
    filepath:      str,
    collection_id: str,
    vault_dir:     str,
    embed_session:  requests.Session,
    chroma_session: requests.Session,
) -> int:
    """
    Lee, chunkea, embede y sube al ChromaDB los fragmentos de un archivo .md.
    Primero borra los chunks anteriores del mismo archivo (update limpio).
    Retorna el número de fragmentos procesados.
    """
    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    rel_path = os.path.relpath(filepath, vault_dir)
    chunks   = chunk_text(content)

    if not chunks:
        return 0  # Archivo vacío o solo metadatos YAML

    # Borrar versión anterior de este archivo antes de reinsertar
    # (si el archivo creció/redujo el número de chunks, evita huérfanos)
    chroma_delete_by_source(collection_id, rel_path, chroma_session)

    # Procesar y enviar por batches
    batch_ids:    list[str]             = []
    batch_embs:   list[list[float]]     = []
    batch_docs:   list[str]             = []
    batch_metas:  list[dict]            = []

    for i, chunk in enumerate(chunks):
        # ID determinista: misma fuente + mismo índice + mismo inicio de texto
        chunk_id = hashlib.md5(
            f"{rel_path}:{i}:{chunk[:50]}".encode("utf-8")
        ).hexdigest()

        embedding = get_embedding(chunk, embed_session)

        batch_ids.append(chunk_id)
        batch_embs.append(embedding)
        batch_docs.append(chunk)
        batch_metas.append({
            "source": rel_path,
            "chunk":  i,
            "file":   os.path.basename(filepath),
        })

        # Enviar batch cuando está lleno
        if len(batch_ids) >= BATCH_SIZE:
            chroma_upsert_batch(
                collection_id, batch_ids, batch_embs,
                batch_docs, batch_metas, chroma_session,
            )
            batch_ids.clear(); batch_embs.clear()
            batch_docs.clear(); batch_metas.clear()

    # Enviar el lote final (puede ser < BATCH_SIZE)
    if batch_ids:
        chroma_upsert_batch(
            collection_id, batch_ids, batch_embs,
            batch_docs, batch_metas, chroma_session,
        )

    return len(chunks)


# ─────────────────────────────────────────────────────────────────────────────
#  COMANDO --stats
# ─────────────────────────────────────────────────────────────────────────────

def cmd_stats() -> None:
    """Muestra estadísticas detalladas de la colección ChromaDB."""
    print("\n📊 Estadísticas de la colección ChromaDB")
    print("─" * 50)

    with requests.Session() as s:
        s.headers.update({"Content-Type": "application/json"})

        try:
            s.get(f"{CHROMA_URL}/api/v1/heartbeat", timeout=CONNECT_TIMEOUT).raise_for_status()
        except Exception as e:
            print(f"✘ ChromaDB no disponible en {CHROMA_URL}: {e}")
            sys.exit(1)

        try:
            collection_id = chroma_get_or_create_collection(s)
        except Exception as e:
            print(f"✘ No se pudo obtener la colección '{COLLECTION_NAME}': {e}")
            sys.exit(1)

        count   = chroma_count(collection_id, s)
        sources = chroma_get_sample_sources(s, collection_id=collection_id, limit=30)  # type: ignore[call-arg]

        # Workaround: chroma_get_sample_sources firma no coincide — rehacemos inline
        try:
            resp = s.post(
                f"{CHROMA_URL}/api/v1/collections/{collection_id}/get",
                json={"limit": 200, "include": ["metadatas"]},
                timeout=CHROMA_TIMEOUT,
            )
            metas   = resp.json().get("metadatas") or [] if resp.ok else []
            sources = sorted({m.get("source", "?") for m in metas if m})
        except Exception:
            sources = []

    state = load_state()

    print(f"  ChromaDB:        {CHROMA_URL}")
    print(f"  Colección:       {COLLECTION_NAME}")
    print(f"  UUID:            {collection_id}")
    print(f"  Total fragmentos:{count:>8,}")
    print(f"  Modelo embed:    {EMBED_MODEL}")
    print(f"  Vault dir:       {VAULT_DIR}")
    print(f"  Estado local:    {len(state)} archivos registrados")
    print(f"  Archivo estado:  {STATE_FILE}")

    if sources:
        print(f"\n  Archivos en muestra ({len(sources)}):")
        for src in sources[:25]:
            print(f"    • {src}")
        if len(sources) > 25:
            print(f"    … y {len(sources) - 25} más")

    print("")


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Indexa el vault de Obsidian en ChromaDB (incremental por defecto).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  python3 indexar_vault.py                 # Solo archivos nuevos o modificados
  python3 indexar_vault.py --clean         # Vaciar colección y reindexar todo
  python3 indexar_vault.py --stats         # Ver colección sin modificar nada
  python3 indexar_vault.py --dry-run -v    # Ver qué se procesaría
  VAULT_DIR=/otro/path python3 indexar_vault.py  # Vault alternativo
        """,
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Borra la colección completa y reindexar desde cero",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Muestra estadísticas de la colección y sale (no modifica nada)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Muestra qué se procesaría sin escribir nada en ChromaDB",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Logging detallado (nombre de archivo + número de fragmentos)",
    )
    args = parser.parse_args()

    # ── Modo stats ──────────────────────────────────────────────────────────
    if args.stats:
        # Reimplementación inline para evitar el bug de firma de función
        print("\n📊 Estadísticas de la colección ChromaDB")
        print("─" * 50)
        with requests.Session() as s:
            s.headers.update({"Content-Type": "application/json"})
            try:
                s.get(
                    f"{CHROMA_URL}/api/v1/heartbeat", timeout=CONNECT_TIMEOUT
                ).raise_for_status()
            except Exception as e:
                print(f"✘ ChromaDB no disponible en {CHROMA_URL}: {e}")
                sys.exit(1)
            cid = chroma_get_or_create_collection(s)
            cnt = chroma_count(cid, s)
            resp = s.post(
                f"{CHROMA_URL}/api/v1/collections/{cid}/get",
                json={"limit": 200, "include": ["metadatas"]},
                timeout=CHROMA_TIMEOUT,
            )
            metas   = (resp.json().get("metadatas") or []) if resp.ok else []
            sources = sorted({m.get("source", "?") for m in metas if m})
        state = load_state()
        print(f"  ChromaDB:         {CHROMA_URL}")
        print(f"  Colección:        {COLLECTION_NAME}")
        print(f"  UUID:             {cid}")
        print(f"  Total fragmentos: {cnt:,}")
        print(f"  Modelo embed:     {EMBED_MODEL}")
        print(f"  Vault dir:        {VAULT_DIR}")
        print(f"  Estado local:     {len(state)} archivos registrados")
        if sources:
            print(f"\n  Muestra de archivos indexados ({len(sources)}):")
            for src in sources[:25]:
                print(f"    • {src}")
            if len(sources) > 25:
                print(f"    … ({len(sources) - 25} más en la colección)")
        print("")
        return

    # ── Verificar vault ─────────────────────────────────────────────────────
    if not os.path.isdir(VAULT_DIR):
        print(f"✘ Vault no encontrado: {VAULT_DIR}", file=sys.stderr)
        print(
            "  Define la ruta con: export VAULT_DIR=/ruta/a/tu/vault",
            file=sys.stderr,
        )
        sys.exit(1)

    # ── Cabecera ─────────────────────────────────────────────────────────────
    t_start = time.monotonic()
    print(f"\n🗂  Vault:       {VAULT_DIR}")
    print(f"📡 ChromaDB:    {CHROMA_URL}")
    print(f"🔷 Ollama CPU:  {OLLAMA_EMBED_URL}")
    print(f"📦 Colección:   {COLLECTION_NAME}  (embed: {EMBED_MODEL})")
    if args.clean:    print("⚠️  Modo --clean: la colección se vaciará y se reconstruirá")
    if args.dry_run:  print("ℹ️  Modo --dry-run: no se escribirá nada en ChromaDB")
    print("")

    # ── Sesiones HTTP (separadas para embed y chroma) ─────────────────────
    embed_session  = requests.Session()
    embed_session.headers.update({"Content-Type": "application/json"})
    chroma_session = requests.Session()
    chroma_session.headers.update({"Content-Type": "application/json"})

    # ── Verificar conectividad ───────────────────────────────────────────────
    try:
        chroma_session.get(
            f"{CHROMA_URL}/api/v1/heartbeat", timeout=CONNECT_TIMEOUT
        ).raise_for_status()
        print("  ✔ ChromaDB disponible")
    except Exception as e:
        print(f"  ✘ ChromaDB no disponible ({CHROMA_URL}): {e}", file=sys.stderr)
        print(
            "    ¿Está corriendo el contenedor chromadb? Comprueba con:\n"
            "    docker ps | grep chromadb",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        embed_session.get(
            OLLAMA_EMBED_URL.replace("/api/embeddings", "/api/tags"),
            timeout=CONNECT_TIMEOUT,
        ).raise_for_status()
        print("  ✔ Ollama CPU disponible")
    except Exception as e:
        print(f"  ✘ Ollama CPU no disponible ({OLLAMA_EMBED_URL}): {e}", file=sys.stderr)
        print(
            "    ¿Está corriendo el contenedor ollama-cpu-router?\n"
            "    docker ps | grep ollama-cpu-router",
            file=sys.stderr,
        )
        sys.exit(1)

    # Verificar que el modelo de embedding está disponible
    try:
        test_resp = embed_session.post(
            OLLAMA_EMBED_URL,
            json={"model": EMBED_MODEL, "prompt": "test"},
            timeout=EMBED_TIMEOUT,
        )
        if test_resp.status_code != 200:
            print(
                f"  ⚠ Modelo '{EMBED_MODEL}' puede no estar disponible "
                f"(HTTP {test_resp.status_code}). "
                f"Descarga con: docker exec ollama-cpu-router ollama pull {EMBED_MODEL}",
                file=sys.stderr,
            )
    except Exception as e:
        print(f"  ⚠ No se pudo probar el modelo de embedding: {e}", file=sys.stderr)

    print("")

    # ── Obtener / recrear colección ─────────────────────────────────────────
    if args.clean and not args.dry_run:
        print("🗑  Borrando colección existente…")
        collection_id = chroma_recreate_collection(chroma_session)
        save_state({})
        print(f"  ✔ Colección recreada — UUID: {collection_id}")
    else:
        collection_id = chroma_get_or_create_collection(chroma_session)
        print(f"  ✔ Colección: {COLLECTION_NAME} (UUID: {collection_id[:8]}…)")

    # ── Descubrir archivos en el vault ──────────────────────────────────────
    md_files = discover_md_files(VAULT_DIR)
    print(f"\n📋 {len(md_files)} archivos .md encontrados en el vault")

    # ── Filtrar archivos sin cambios (indexación incremental) ───────────────
    state = {} if args.clean else load_state()

    if not args.clean:
        to_process: list[str] = []
        skipped = 0
        for fp in md_files:
            rel = os.path.relpath(fp, VAULT_DIR)
            if state.get(rel) == file_signature(fp):
                skipped += 1
            else:
                to_process.append(fp)
        if skipped:
            print(f"  ⏭  {skipped} archivo{'s' if skipped != 1 else ''} sin cambios — omitidos")
    else:
        to_process = md_files

    print(f"  ⚙️  {len(to_process)} archivo{'s' if len(to_process) != 1 else ''} a procesar\n")

    if not to_process:
        total = chroma_count(collection_id, chroma_session)
        print(f"✔ Vault al día — {total:,} fragmentos en la colección.\n")
        return

    # ── Bucle de indexación ─────────────────────────────────────────────────
    total_chunks = 0
    errors       = 0
    BAR_WIDTH    = 38

    for i, filepath in enumerate(to_process, 1):
        rel = os.path.relpath(filepath, VAULT_DIR)
        try:
            if args.dry_run:
                # Contar sin escribir
                with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                n_chunks = len(chunk_text(content))
            else:
                n_chunks = index_file(
                    filepath, collection_id, VAULT_DIR,
                    embed_session, chroma_session,
                )

            total_chunks += n_chunks

            if not args.dry_run:
                state[rel] = file_signature(filepath)

            if args.verbose:
                print(f"  [{i:3d}/{len(to_process)}] {rel}  →  {n_chunks} fragmento{'s' if n_chunks != 1 else ''}")
            else:
                # Barra de progreso compacta (sobreescribe la línea)
                done = int(BAR_WIDTH * i / len(to_process))
                bar  = "█" * done + "░" * (BAR_WIDTH - done)
                pct  = int(100 * i / len(to_process))
                label = rel[-35:] if len(rel) > 35 else rel
                print(
                    f"\r  [{bar}] {pct:3d}%  {label:<35}",
                    end="",
                    flush=True,
                )

        except KeyboardInterrupt:
            print("\n\n⚠  Interrumpido por el usuario")
            # Guardar el estado parcial antes de salir
            if not args.dry_run:
                save_state(state)
                print(f"  Estado parcial guardado ({len(state)} archivos)")
            sys.exit(130)

        except Exception as exc:
            errors += 1
            print(f"\n  ✘ Error en '{rel}': {exc}")
            if args.verbose:
                traceback.print_exc()

    # Fin de barra de progreso
    if not args.verbose:
        print("")

    # ── Persistir estado incremental ────────────────────────────────────────
    if not args.dry_run:
        save_state(state)

    # ── Resumen final ────────────────────────────────────────────────────────
    elapsed = time.monotonic() - t_start

    if not args.dry_run:
        total_db = chroma_count(collection_id, chroma_session)
    else:
        total_db = None

    print("")
    print("─" * 50)
    if args.dry_run:
        print(f"  [dry-run] Se procesarían: {len(to_process)} archivos")
        print(f"  [dry-run] Fragmentos que se generarían: {total_chunks:,}")
    else:
        ok_count = len(to_process) - errors
        print(f"  ✔ Indexación completada en {elapsed:.1f}s")
        print(f"  Archivos procesados:   {ok_count:,}")
        print(f"  Fragmentos indexados:  {total_chunks:,}")
        print(f"  Total en colección:    {total_db:,}")
        if errors:
            print(f"  ⚠  Errores:           {errors}")
            print(f"     (re-ejecuta con --verbose para detalles)")
    print("")


if __name__ == "__main__":
    main()
