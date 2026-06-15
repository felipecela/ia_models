A partir de la versión 13 se incluyen unos scripts de Python al final, uno de ellos es el siguiente y resulta que estos scripts se han perdido y no se tienen actualmente.

Necesito que me ayudes a analizando y revisando en profundidad tanto la aplicación del orquestador como también la aplicación del Autoboot Cluster que hemos desarrollado porque he detectado, sobre todo para la parte del Autoboot Cluster, que en las últimas modificaciones se ha perdido parte del código de algunos de los scripts más pequeños que se utilizaban dentro de este .SH y que estaban conformados por medio de un heredoc, pero finalmente se han dejado fuera del fichero dichos scripts, aunque se continuan teniendo en cuenta por medio de una variable local encontrandose declarados en el codigo; y entonces necesito que revises, por lo tanto, si es que estos scripts ya no son necesarios y por lo tanto se puede eliminar dicha variable o vale la pena rescatarlos porque fuera algo que se hubiese perdido. Determínalo, por favor, revisando de manera detallada y consciente el código para saber si es algo útil y además, que no se encuentre implementado de otra manera dentro de la aplicación actual que se ha constituido.

scripts perdidos, ya que se declaran en el orquestador pero no se cuenta con su codigo:
INDEXER_SCRIPT="$SCRIPT_DIR/indexar_vault.py"
TABBYAPI_CONFIG="$SCRIPT_DIR/config_tabbyapi_v15.yml"
CHROMA_DATA_DIR="$SCRIPT_DIR/chroma_data"       # En ext4 (SQLite necesita permisos Unix)
SEARXNG_CONFIG_DIR="$SCRIPT_DIR/searxng_config"
OBSIDIAN_CONFIG_DIR="$SCRIPT_DIR/obsidian_config"

MATERIAL RESCATADO:

### Script de indexación del vault (indexar_vault.py)

Este script se ejecuta manualmente o vía cron para mantener el índice actualizado cuando se añaden notas:

```python
#!/usr/bin/env python3
"""
indexar_vault.py — Indexa el vault de Obsidian en ChromaDB usando nomic-embed-text
Ejecutar tras añadir/modificar notas: python3 indexar_vault.py
"""
import os
import glob
import hashlib
import chromadb
import ollama

VAULT_DIR = "/home/fcela-ga/sgoinfre/ai_core/obsidian_vault"
CHROMA_URL = "http://localhost:8001"
COLLECTION_NAME = "obsidian_vault"
EMBED_MODEL = "nomic-embed-text"
CHUNK_SIZE = 512   # caracteres por fragmento
CHUNK_OVERLAP = 64

def chunk_text(text: str) -> list[str]:
    chunks = []
    start = 0
    while start < len(text):
        end = start + CHUNK_SIZE
        chunks.append(text[start:end])
        start += CHUNK_SIZE - CHUNK_OVERLAP
    return [c for c in chunks if len(c.strip()) > 50]

def get_embedding(text: str) -> list[float]:
    resp = ollama.embeddings(model=EMBED_MODEL, prompt=text)
    return resp["embedding"]

client = chromadb.HttpClient(host="localhost", port=8001)
collection = client.get_or_create_collection(
    name=COLLECTION_NAME,
    metadata={"hnsw:space": "cosine"}
)

md_files = glob.glob(f"{VAULT_DIR}/**/*.md", recursive=True)
print(f"Indexando {len(md_files)} archivos Markdown...")

for filepath in md_files:
    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    rel_path = os.path.relpath(filepath, VAULT_DIR)
    chunks = chunk_text(content)

    for i, chunk in enumerate(chunks):
        chunk_id = hashlib.md5(f"{rel_path}:{i}:{chunk[:50]}".encode()).hexdigest()
        embedding = get_embedding(chunk)
        collection.upsert(
            ids=[chunk_id],
            embeddings=[embedding],
            documents=[chunk],
            metadatas=[{
                "source": rel_path,
                "chunk": i,
                "file": os.path.basename(filepath)
            }]
        )

print(f"✔ Indexación completa. Colección '{COLLECTION_NAME}': {collection.count()} fragmentos")
```


### Comando de arranque (a añadir en Autoboot_Cluster_V15.sh)

```bash
# PASO 8/9 — Obsidian (base de conocimiento)
step "PASO 8/9 — Obsidian Knowledge Base (puerto 3000)"

VAULT_DIR="${AI_CORE}/obsidian_vault"
OBSIDIAN_CONFIG_DIR="${SCRIPT_DIR}/obsidian_config"
mkdir -p "$VAULT_DIR" "$OBSIDIAN_CONFIG_DIR"

docker run -d \
  --name obsidian-kb \
  --restart unless-stopped \
  -p 3000:3000 \
  -p 3001:3001 \
  -e PUID=1000 \
  -e PGID=1000 \
  -e TZ=Europe/Madrid \
  -v "${VAULT_DIR}":/config/obsidian_vault \
  -v "${OBSIDIAN_CONFIG_DIR}":/config \
  --security-opt seccomp=unconfined \
  --shm-size="1gb" \
  lscr.io/linuxserver/obsidian:latest

wait_http "http://localhost:3000" 45 "Obsidian" || warn "Obsidian tarda en arrancar la primera vez"
ok "Obsidian disponible en http://localhost:3000"
```


# ─────────────────────────────────────────────────────────────────────────────
#  PASO 4: TABBYAPI / EXLLAMAV2 (STANDBY)
#
#  Generamos config con disable_auth: true para permitir /v1/model/load
#  sin necesidad de admin key (entorno local y privado).
#
#  IMAGEN OFICIAL: ghcr.io/theroyallab/tabbyapi:latest
# ─────────────────────────────────────────────────────────────────────────────
step "PASO 4/8 — TabbAPI/ExLlamaV2 (STANDBY — modelo: qwen2.5-coder-7b-exl2)"

cat > "$TABBYAPI_CONFIG" << 'TABBY_CONF'
# ───────────────────────────────────────────────────────────────
#  TabbyAPI Configuration V15 — OMEN Cluster
#  Documentación: https://github.com/theroyallab/tabbyAPI/wiki
# ───────────────────────────────────────────────────────────────

network:
  host: 0.0.0.0
  port: 5000
  # disable_auth: true permite /v1/model/load sin admin key
  # Necesario para el switching dinámico CHAT↔INSTANTANEO del router
  disable_auth: true

model:
  # Modelo por defecto al arrancar TabbAPI
  # El router carga dinámicamente el modelo correcto según el nivel
  model_name: qwen2.5-coder-7b-exl2

  # Contexto máximo — reducir a 2048 si aparecen errores de VRAM
  max_seq_len: 4096

  # Caché Q4: reduce VRAM ~30% con mínima pérdida de calidad
  cache_mode: Q4

logging:
  log_prompt: false
  log_generation_params: false
TABBY_CONF
ok "config_tabbyapi_v15.yml generado"



