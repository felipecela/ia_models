# OMEN AI Cluster V13 — Obsidian + RAG Local + Web Search para OpenClaw
### Expansión del clúster: base de conocimiento persistente y búsqueda web privada

***

## Resumen ejecutivo

Esta expansión añade **tres nuevos contenedores** al clúster OMEN V11: Obsidian (base de conocimiento en Markdown), ChromaDB (motor de búsqueda vectorial/RAG), y SearXNG (búsqueda web privada sin API keys). La arquitectura resultante permite que los modelos locales consulten notas personales, documentos y el estado actual de internet en cada prompt, convirtiendo a OpenClaw en un agente verdaderamente informado. Todo el sistema es 100% local y offline-capable, sin enviar datos a ningún servicio externo.

***

## 1. Arquitectura final ampliada

```
┌──────────────────────────────────────────────────────────────────────┐
│         USUARIO / OpenClaw UI :8080                                   │
└──────────────┬───────────────────────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────────────────────┐
│         Orchestrator Router V6  :8000                                 │
│  (Phi-4 classifier + embeddings router + VRAM manager)               │
└──┬───────┬──────────┬──────────┬──────────────────────────────────┬──┘
   │       │          │          │                                  │
   ▼       ▼          ▼          ▼                                  ▼
INSTANT  AGIL      PROFUNDO   PRECISO / MASIVO / CODIGO        HERRAMIENTAS
TabbAPI  SGLang    Ollama      Ollama                           │
                                                               ├─ ChromaDB :8001
                                                               │  (RAG — Obsidian vault)
                                                               ├─ SearXNG :8888
                                                               │  (web search privado)
                                                               └─ Obsidian :3000
                                                                  (editor vault)
```

Los tres servicios de herramientas se conectan a OpenClaw vía:
- **ChromaDB** → MCP server (`mcp.json`) para RAG sobre el vault[^1][^2]
- **SearXNG** → Plugin OpenClaw para búsqueda web[^3][^4]
- **Obsidian** → Directorio compartido con el vault (volumen Docker)[^5][^6]

***

## 2. Contenedor Obsidian: base de conocimiento en Markdown

### Por qué Obsidian y no otra herramienta

Obsidian almacena todo en **archivos Markdown planos** en el sistema de archivos local. Esta propiedad es clave: el vault entero es legible directamente por el pipeline RAG sin conversión ni APIs intermedias. Cada nota que se escribe en Obsidian es inmediatamente indexable por ChromaDB. Las notas, además, pueden tener frontmatter YAML para metadata estructurada (tags, fecha, proyecto), lo que permite filtrado por categoría en las búsquedas.[^6][^7][^8]

### Imagen Docker recomendada

Existen dos imágenes consolidadas para Obsidian en Docker:[^9][^5]

| Imagen | Puerto | Acceso | Notas |
|--------|--------|--------|-------|
| `ghcr.io/sytone/obsidian-remote:latest` | 8080 | Navegador web (noVNC) | Más compatible, más usada[^5][^6] |
| `lscr.io/linuxserver/obsidian:latest` | 3000/3001 | Navegador web (KasmVNC) | Más ligera, LinuxServer.io[^9] |

**Recomendada para este clúster**: `lscr.io/linuxserver/obsidian:latest` en puerto **3000** (evita colisión con OpenClaw en 8080).[^9]

### Integración con el SSD exFAT

El vault de Obsidian se monta **directamente desde el SSD exFAT** compartido entre Windows y Linux. Así las notas son accesibles desde ambos sistemas operativos — puedes escribir en Obsidian nativo de Windows y el clúster Linux lee el mismo vault sin sincronización:

```bash
# El vault vive en el SSD exFAT, accesible desde ambos OS:
VAULT_DIR="/home/fcela-ga/sgoinfre/ai_core/obsidian_vault"
mkdir -p "$VAULT_DIR"
```

### Comando de arranque (a añadir en Autoboot_Cluster_V13.sh)

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

> **Nota exFAT**: El vault en exFAT funciona correctamente porque Obsidian solo necesita leer/escribir archivos Markdown planos — no usa symlinks, sockets Unix ni atributos extendidos. El contenedor accede como root (UID 0), que siempre tiene permisos de lectura/escritura en exFAT.[^6]

***

## 3. ChromaDB + MCP: pipeline RAG para OpenClaw

### Arquitectura del RAG

El pipeline de RAG (Retrieval-Augmented Generation) funciona así:[^10][^11][^1]

1. **Indexación**: ChromaDB monitoriza el vault de Obsidian y genera embeddings para cada nota/fragmento.
2. **Retrieval**: Cuando OpenClaw recibe un prompt, el MCP server de ChromaDB busca los fragmentos más relevantes del vault por similitud semántica.
3. **Augmentation**: Los fragmentos recuperados se inyectan en el contexto del modelo antes de generar la respuesta.
4. **Generation**: El modelo local responde con acceso a la información del vault, citando las notas fuente.

El modelo de embeddings recomendado es `nomic-embed-text` (ya propuesto en el análisis V13), que corre en la instancia Ollama CPU existente — **sin añadir nuevos modelos ni consumir VRAM**.[^7]

### Contenedor ChromaDB

```bash
# PASO 9/9 — ChromaDB (motor RAG)
step "PASO 9/9 — ChromaDB RAG Engine (puerto 8001)"

CHROMA_DATA_DIR="${SCRIPT_DIR}/chroma_data"  # En ext4, no en exFAT
mkdir -p "$CHROMA_DATA_DIR"

docker run -d \
  --name chromadb \
  --restart unless-stopped \
  -p 8001:8000 \
  -e CHROMA_SERVER_HTTP_PORT=8000 \
  -e ANONYMIZED_TELEMETRY=false \
  -v "${CHROMA_DATA_DIR}":/chroma/chroma \
  chromadb/chroma:latest

wait_http "http://localhost:8001/api/v1/heartbeat" 30 "ChromaDB" || \
  warn "ChromaDB no respondió (puede tardar en el primer arranque)"
ok "ChromaDB disponible en http://localhost:8001"
```

> **Importante**: El directorio de datos de ChromaDB (`chroma_data`) va en **ext4** (home directory), no en exFAT. ChromaDB usa SQLite internamente, que requiere soporte de permisos Unix para escritura atómica.[^1]

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

### Configuración MCP en OpenClaw (mcp.json)

OpenClaw se conecta a ChromaDB como herramienta MCP, lo que permite al agente invocar búsquedas en el vault de forma autónoma:[^12][^13][^1]

```json
// Crear/editar: ~/.openclaw/mcp.json
// Dentro del contenedor: /data/.openclaw/mcp.json
{
  "mcpServers": {
    "knowledge-base": {
      "command": "npx",
      "args": ["-y", "@clawrag/mcp-server"],
      "env": {
        "CHROMA_URL": "http://host.docker.internal:8001",
        "COLLECTION_NAME": "obsidian_vault",
        "EMBED_MODEL": "nomic-embed-text",
        "OLLAMA_URL": "http://host.docker.internal:11435",
        "TOP_K": "8",
        "SIMILARITY_THRESHOLD": "0.70"
      }
    }
  }
}
```

Una vez configurado, OpenClaw tendrá disponible la herramienta `search_knowledge_base` que cualquier agente puede invocar automáticamente cuando el prompt requiera información local.[^11]

### Inyectar mcp.json en el contenedor OpenClaw

Añadir en el Autoboot tras el restart de OpenClaw:

```bash
# Inyectar mcp.json con configuración del knowledge base
docker exec openclaw-server mkdir -p /data/.openclaw

docker exec openclaw-server bash -c 'cat > /data/.openclaw/mcp.json' << 'MCP_JSON'
{
  "mcpServers": {
    "knowledge-base": {
      "command": "npx",
      "args": ["-y", "@clawrag/mcp-server"],
      "env": {
        "CHROMA_URL": "http://host.docker.internal:8001",
        "COLLECTION_NAME": "obsidian_vault",
        "EMBED_MODEL": "nomic-embed-text",
        "OLLAMA_URL": "http://host.docker.internal:11435",
        "TOP_K": "8",
        "SIMILARITY_THRESHOLD": "0.70"
      }
    }
  }
}
MCP_JSON

ok "MCP knowledge base configurado"
```

### System prompt del agente para maximizar uso del RAG

En `openclaw.json`, añadir instrucción al agente para que siempre consulte el vault:

```json
"agents": {
  "defaults": {
    "systemPrompt": "Cuando respondas, SIEMPRE consulta primero la base de conocimiento local usando search_knowledge_base antes de generar tu respuesta. Si encuentras información relevante, cítala indicando el archivo fuente. Si no encuentras información relevante en el vault, indícalo explícitamente antes de responder con tu conocimiento general.",
    ...
  }
}
```

***

## 4. SearXNG: búsqueda web privada sin API keys

### Por qué SearXNG y no Brave/Perplexity API

SearXNG es un metabuscador de código abierto que agrega resultados de más de 70 motores de búsqueda (Google, Bing, DuckDuckGo, etc.) sin cuentas, API keys ni envío de datos personales. Para el clúster OMEN, es la opción natural: todo permanece local, no hay costes por consulta y no hay límites de tasa para uso personal.[^14][^15]

OpenClaw tiene soporte nativo para SearXNG a través del plugin oficial `@ollama/openclaw-web-search` (incluido en Ollama 0.18.1+) y también mediante el plugin de la comunidad `openclaw-search`.[^16][^17][^18][^3]

### Contenedor SearXNG

```bash
# Añadir al Autoboot ANTES del paso 6 (OpenClaw necesita SearXNG ya activo)
step "PASO 6b/9 — SearXNG (búsqueda web privada, puerto 8888)"

SEARXNG_CONFIG_DIR="${SCRIPT_DIR}/searxng_config"
mkdir -p "$SEARXNG_CONFIG_DIR"

# Generar settings.yml si no existe
if [ ! -f "$SEARXNG_CONFIG_DIR/settings.yml" ]; then
  SECRET=$(openssl rand -hex 32)
  cat > "$SEARXNG_CONFIG_DIR/settings.yml" << SEARX_EOF
use_default_settings: true
server:
  secret_key: "${SECRET}"
  bind_address: "0.0.0.0"
  port: 8080
  limiter: false
search:
  safe_search: 0
  formats:
    - html
    - json
outgoing:
  request_timeout: 8.0
  useragent_suffix: ""
SEARX_EOF
  ok "searxng settings.yml generado"
fi

docker run -d \
  --name searxng \
  --restart unless-stopped \
  -p 127.0.0.1:8888:8080 \
  -v "${SEARXNG_CONFIG_DIR}/settings.yml":/etc/searxng/settings.yml:ro \
  --memory=384m \
  --cpus=0.5 \
  searxng/searxng:latest

wait_http "http://localhost:8888/search?q=test&format=json" 30 "SearXNG" || \
  warn "SearXNG tarda en arrancar"
ok "SearXNG disponible en http://localhost:8888"
```

### Instalar el plugin en OpenClaw

```bash
# Opción A: Plugin oficial de Ollama (si usas ollama launch openclaw)
openclaw plugins install @ollama/openclaw-web-search

# Opción B: Plugin SearXNG de la comunidad (para instalación Docker manual)
# Dentro del contenedor:
docker exec openclaw-server sh -c \
  "openclaw plugins install https://github.com/akr-n/openclaw-search.git"
```

### Configurar el plugin en openclaw.json

Añadir al bloque ya existente de `openclaw.json`:[^19][^3]

```json
"plugins": {
  "allow": ["openclaw-search", "@ollama/openclaw-web-search"],
  "entries": {
    "openclaw-search": {
      "enabled": true,
      "config": {
        "baseUrl": "http://host.docker.internal:8888",
        "maxResults": 8,
        "timeoutMs": 10000,
        "categories": ["general", "news", "science"]
      }
    }
  }
}
```

### Verificar que funciona desde el host

```bash
# Test básico de SearXNG:
curl -s "http://localhost:8888/search?q=DeepSeek+R1&format=json" \
  | python3 -c "import json,sys; r=json.load(sys.stdin); print(f'OK: {len(r[\"results\"])} resultados')"
```

***

## 5. Flujo completo de una consulta con RAG + Web Search

Cuando el usuario escribe un prompt en OpenClaw, el agente puede ahora seguir este flujo enriquecido:

```
Usuario: "¿Qué dice mi nota sobre Dijkstra? ¿Ha habido avances recientes en algoritmos de grafos?"
         │
         ▼
OpenClaw recibe el prompt
         │
         ├─► MCP Tool: search_knowledge_base("Dijkstra algoritmo grafos")
         │   → ChromaDB busca en el vault de Obsidian
         │   → Devuelve 8 fragmentos relevantes de tus notas (similitud > 0.70)
         │
         ├─► Plugin Tool: searxng_search("advances graph algorithms 2025 2026")
         │   → SearXNG consulta DuckDuckGo + Bing + Google Scholar
         │   → Devuelve 8 resultados web recientes
         │
         ▼
Router → nivel PROFUNDO (DeepSeek R1 14B) o PRECISO (Phi-4-reasoning)
         │
         ▼
Modelo genera respuesta combinando:
  - Contenido de tus notas de Obsidian (citado por archivo)
  - Información web reciente (citada por URL)
  - Conocimiento parametrizado del modelo
         │
         ▼
OpenClaw muestra respuesta con citas locales y web
```

***

## 6. Gestión de la base de conocimiento en Obsidian

### Estructura de vault recomendada para RAG óptimo

La calidad del RAG depende directamente de cómo se organizan las notas. Para maximizar la relevancia de recuperación:[^20][^21][^8]

```
obsidian_vault/
├── MEMORY.md              ← Hechos clave, contexto personal permanente
├── Projects/              ← Una nota por proyecto activo
│   ├── OMEN-Cluster.md
│   └── ...
├── Research/              ← Investigaciones y análisis
│   ├── LLM-Benchmarks.md
│   └── ...
├── Insights/              ← Conclusiones y aprendizajes propios
├── Reference/             ← Documentación técnica copiada/resumida
└── Daily/                 ← Notas diarias YYYY-MM-DD.md
```

Usar **frontmatter YAML** en cada nota para habilitar filtrado por metadata en las búsquedas:

```markdown
---
tags: [llm, benchmarks, deepseek]
project: OMEN-Cluster
date: 2026-06-11
type: research
---
# DeepSeek R1 Benchmarks

Contenido de la nota...
```

### Re-indexación automática con cron

Añadir al sistema para re-indexar el vault periódicamente cuando se añadan notas:

```bash
# Añadir al crontab: re-indexar cada hora
(crontab -l 2>/dev/null; echo "0 * * * * python3 /home/fcela-ga/ruta/scripts/indexar_vault.py >> /tmp/indexar.log 2>&1") | crontab -

# O manualmente tras escribir notas importantes:
python3 ~/ruta/scripts/indexar_vault.py
```

***

## 7. Actualización del bloque openclaw.json completo (V13)

El `openclaw.json` final, integrando agentes especializados, RAG y web search:

```json
{
  "gateway": {
    "bind": "lan",
    "controlUi": {
      "allowedOrigins": [
        "http://localhost:8080",
        "http://127.0.0.1:8080"
      ]
    }
  },
  "models": {
    "mode": "merge",
    "providers": {
      "local_router": {
        "baseUrl": "http://host.docker.internal:8000/v1",
        "apiKey": "sk-router-local",
        "api": "openai-completions",
        "models": [
          { "id": "ruteador-auto",  "name": "🤖 Auto — Phi-4 elige el nivel",       "contextWindow": 32768 },
          { "id": "instantaneo",   "name": "⚡ Instantáneo (ExLlamaV2)",             "contextWindow": 4096  },
          { "id": "agil",          "name": "🚀 Ágil (SGLang · agentes)",             "contextWindow": 32768 },
          { "id": "profundo",      "name": "🧠 Profundo (DeepSeek R1 14B)",          "contextWindow": 16384 },
          { "id": "preciso",       "name": "🎯 Preciso (Phi-4-reasoning)",           "contextWindow": 16384 },
          { "id": "masivo",        "name": "🔬 Masivo (Qwen2.5 32B)",               "contextWindow": 32768 },
          { "id": "codigo",        "name": "💻 Código (DeepSeek Coder V2)",          "contextWindow": 16384 },
          { "id": "phi4",          "name": "🔷 Phi-4 CPU (router directo)",          "contextWindow": 16384 }
        ]
      }
    }
  },
  "agents": {
    "defaults": {
      "model": {
        "primary": "local_router/ruteador-auto",
        "fallbacks": ["local_router/agil", "local_router/profundo"]
      },
      "systemPrompt": "Cuando respondas, consulta primero la base de conocimiento local (search_knowledge_base) si la pregunta puede estar relacionada con tus notas. Si hay información relevante, cítala indicando el archivo fuente. Para preguntas sobre eventos recientes o información actualizada, usa la herramienta de búsqueda web.",
      "subagents": {
        "model": "local_router/agil",
        "maxConcurrent": 2,
        "runTimeoutSeconds": 300
      },
      "maxConcurrent": 2,
      "timeoutSeconds": 600,
      "contextTokens": 32768
    },
    "list": [
      {
        "id": "coder",
        "name": "🖥️ Agente Coder",
        "model": { "primary": "local_router/codigo", "fallbacks": ["local_router/profundo"] }
      },
      {
        "id": "analyst",
        "name": "📊 Agente Analyst",
        "model": { "primary": "local_router/masivo", "fallbacks": ["local_router/profundo"] }
      },
      {
        "id": "reasoner",
        "name": "🧠 Agente Reasoner",
        "model": { "primary": "local_router/preciso", "fallbacks": ["local_router/profundo"] }
      },
      {
        "id": "researcher",
        "name": "🔍 Agente Researcher",
        "model": { "primary": "local_router/agil", "fallbacks": ["local_router/profundo"] },
        "systemPromptSuffix": "Eres un agente especializado en investigación. Usa SIEMPRE la búsqueda web y la base de conocimiento local para responder. Cita todas las fuentes."
      }
    ]
  },
  "plugins": {
    "allow": ["openclaw-search", "@ollama/openclaw-web-search"],
    "entries": {
      "openclaw-search": {
        "enabled": true,
        "config": {
          "baseUrl": "http://host.docker.internal:8888",
          "maxResults": 8,
          "timeoutMs": 10000
        }
      }
    }
  }
}
```

***

## 8. Resumen de puertos y servicios V13

| Servicio | Puerto | Acceso | Estado al arrancar |
|---------|--------|--------|-------------------|
| OpenClaw UI | 8080 | http://localhost:8080 | ✅ Activo |
| Router V6 | 8000 | http://localhost:8000 | ✅ Activo |
| Ollama GPU | 11434 | interno | ✅ Activo |
| Ollama CPU (Phi-4) | 11435 | interno | ✅ Activo |
| TabbAPI/ExLlamaV2 | 5000 | interno | ⏸ Standby |
| SGLang | 30000 | interno | ⏸ Standby |
| **Obsidian** | **3000** | **http://localhost:3000** | **✅ Activo (nuevo)** |
| **ChromaDB** | **8001** | **http://localhost:8001** | **✅ Activo (nuevo)** |
| **SearXNG** | **8888** | **http://localhost:8888** | **✅ Activo (nuevo)** |

***

## 9. Verificación del sistema completo

```bash
# Verificar todos los servicios V13
./Autoboot_Cluster_V13.sh --status

# Test RAG: buscar en el vault
python3 - << 'EOF'
import chromadb, ollama

client = chromadb.HttpClient(host="localhost", port=8001)
collection = client.get_collection("obsidian_vault")
print(f"Fragmentos indexados: {collection.count()}")

# Búsqueda de prueba
query = "modelos LLM razonamiento"
resp = ollama.embeddings(model="nomic-embed-text", prompt=query)
results = collection.query(query_embeddings=[resp["embedding"]], n_results=3)
for i, (doc, meta) in enumerate(zip(results["documents"], results["metadatas"])):
    print(f"\n[{i+1}] Fuente: {meta['source']}")
    print(f"    {doc[:200]}...")
EOF

# Test web search
curl -s "http://localhost:8888/search?q=phi4+reasoning+benchmark&format=json" \
  | python3 -c "import json,sys; r=json.load(sys.stdin); \
    [print(f'  - {x[\"title\"]}') for x in r['results'][:3]]"
```

---

## References

1. [Building Internal Knowledge Search with OpenClaw: RAG-Powered ...](https://www.oflight.co.jp/en/columns/openclaw-rag-knowledge-base-setup) - Learn how to build a high-accuracy internal knowledge search system using OpenClaw and RAG (Retrieva...

2. [MCP RAG with ChromaDB - Multi-Format Document Support - GitHub](https://github.com/CyprianFusi/MCP-rag-with-Chromadb) - A powerful MCP (Model Context Protocol) server that provides RAG (Retrieval-Augmented Generation) ca...

3. [Search - OpenClaw Plugin](https://openclawdir.com/plugins/search-f0qfer) - Self-hosted private web search plugin for OpenClaw using SearXNG

4. [SearXNG + OpenClaw Integration - 48nauts](https://48nauts.com/blog/searxng-openclaw-integration) - One human. A team of agents. Building in public. Experimental AI agency building real products with ...

5. [Self hosted Docker instance - Share & showcase](https://forum.obsidian.md/t/self-hosted-docker-instance/3788) - Would it be possible to deploy Obsidian inside a docker which could then be self-hosted behind a rev...

6. [Access Obsidian from anywhere using a browser by self-hosting it](https://www.xda-developers.com/i-self-hosted-obsidian-so-i-can-access-it-in-web-browser-anywhere/) - You no longer need the app

7. [qmd - OpenClaw Skills](https://openclawskills.best/skills/anshumanbh/anshumanbh-qmd/) - Search markdown knowledge bases efficiently using qmd. Use this when searching Obsidian vaults or ma...

8. [Mastering Knowledge Management in OpenClaw: The Local ...](https://dev.to/aloycwl/mastering-knowledge-management-in-openclaw-the-local-storage-skill-explained-33p3) - Introduction to OpenClaw Knowledge Management For power users of the OpenClaw ecosystem,...

9. [[Docker] Self-hosted Obsidian 설치 및 짧은 사용기 - Poki's World](https://poki.tistory.com/entry/Docker-Self-hosted-Obsidian-%EC%84%A4%EC%B9%98%EB%B0%A9%EB%B2%95) - 안녕하세요.오늘은 Self-hosted용으로 구축이 가능한 Obsidian을 설치하는 방법을 알려드리겠습니다. Obsidian?메모 앱을 사용해 보셨던 사용자라면 Obsidian을...

10. [Building a RAG-Enabled Internal Knowledge Base AI with Qwen3.5 ...](https://www.oflight.co.jp/en/columns/qwen35-9b-openclaw-rag-knowledge-base-agent) - Learn how to build a RAG-enabled internal knowledge base AI using Qwen3.5-9B and OpenClaw. This guid...

11. [RAG Tutorial: OpenClaw Knowledge Base Setup | ClawHosters](https://clawhosters.com/blog/posts/openclaw-rag-knowledge-base-tutorial) - Set up RAG in OpenClaw to search your own documents with source citations. Step-by-step knowledge ba...

12. [Show HN: Self-hosted RAG with MCP support for OpenClaw](https://news.ycombinator.com/item?id=46847406)

13. [How to Add MCP Servers on OpenClaw (My Setup for 12 Servers)](https://openclawvps.io/blog/add-mcp-openclaw) - Step-by-step guide to add MCP servers on OpenClaw. My exact openclaw.json config for 12 servers, per...

14. [Internet Search - OpenClaw Plugin](https://openclawdir.com/plugins/internet-search-zwziox) - SearXNG-backed internet search plugin for OpenClaw

15. [Plugin Searxng - OpenClaw Directory](https://openclawdir.com/plugins/plugin-searxng-6afdyf) - SearXNG web search plugin for OpenClaw - privacy-preserving search via self-hosted SearXNG

16. [Ollama 0.18.1: Your Local LLM Now Browses the Web - CraftRigs](https://craftrigs.com/guides/ollama-0-18-1-web-search-setup/) - Ollama 0.18.1 ships web search and web fetch as baked-in tools via the OpenClaw agent framework. No ...

17. [Ollama just gave your local AI web search - AI for Automation](https://aiforautomation.io/news/2026-03-19-ollama-openclaw-local-ai-web-search-private) - Ollama v0.18.1 adds web search to OpenClaw, its local AI assistant. Now your AI can search the inter...

18. [ollama on X: "Ollama 0.18.1 is here! 🌐 Web search and fetch in OpenClaw Ollama now ships with web search and web fetch plugin for OpenClaw. This allows Ollama's models (local or cloud) to search the web for the latest content and news. This also allows OpenClaw with Ollama to be able to https://t.co/WfDSxlYyNK" / X](https://x.com/ollama/status/2033993519459889505)

19. [Searxng - OpenClaw Plugin](https://openclawdir.com/plugins/searxng-vuzxc7) - SearXNG web search plugin for OpenClaw — use your self-hosted SearXNG instance as an agent search to...

20. [Private AI Agent Knowledge Base with OpenClaw: Self-Hosted RAG ...](https://openclawdashboard.com/blog/self-hosted-ai-agent-knowledge-base-openclaw-2026) - Build a self-hosted AI agent knowledge base with OpenClaw, local files, privacy controls, citations,...

21. [openclaw-memories skill - playbooks](https://playbooks.com/skills/openclaw/skills/openclaw-memories) - This skill helps you manage agent memories with offline ALMA design exploration, offline indexing of...

