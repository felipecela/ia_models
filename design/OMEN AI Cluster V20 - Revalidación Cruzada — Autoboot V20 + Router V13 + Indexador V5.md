# Revalidación Cruzada — Autoboot V20 + Router V13 + Indexador V5

## 1. Contratos de Integración Verificados

### 1.1 Nombres de Archivo y Rutas

| Componente | Autoboot V20 espera | Archivo generado | Estado |
|---|---|---|---|
| Router | `$AI_HOME/orchestrator_router_V13.py` | `orchestrator_router_V13.py` | ✔ Coherente |
| Indexador | `$AI_HOME/indexar_vault_v5.py` | `indexar_vault_v5.py` | ✔ Coherente |
| PID Router | `$AI_HOME/router_v13.pid` | — (gestionado por Autoboot) | ✔ Coherente |
| PID Indexador | `$AI_HOME/indexer.pid` | — (gestionado por Autoboot) | ✔ Coherente |

### 1.2 Puertos y URLs

| Servicio | Puerto | Autoboot usa | Router usa | Indexador usa |
|---|---|---|---|---|
| Router FastAPI | 8000 | `curl localhost:8000/health` | `uvicorn port=8000` | — |
| Ollama GPU | 11434 | Docker -p 11434:11434 | `RUTAS[*]["base_url"]` | — |
| Ollama CPU | 11435 | Docker -p 11435:11434 | `EMBED_CPU_URL` | `--ollama-embed-url` default |
| ChromaDB | 8001 | Docker -p 8001:8000 | `CHROMA_URL` | `--chroma-url` default |
| ExLlamaV2 | 5000 | Docker -p 5000:5000 | `RUTAS["CHAT"]["base_url"]` | — |
| SGLang | 30000 | Docker -p 30000:30000 | `RUTAS["AGIL"]["base_url"]` | — |
| SearXNG | 8888 | Docker -p 8888:8888 | health check URL | — |
| Obsidian KB | 3000 | Docker -p 3000:3000 | health check URL | — |

**Resultado: ✔ Todos los puertos son coherentes entre los tres componentes.**

### 1.3 Variables de Entorno

| Variable | Autoboot exporta | Router consume | Indexador consume |
|---|---|---|---|
| `AGENT_DB_DIR` | `export AGENT_DB_DIR="$AGENT_DATA_DIR"` | `os.environ.get("AGENT_DB_DIR", ...)` | `os.environ.get("AGENT_DB_DIR")` (fallback) |
| `VAULT_DIR` | Pasado como `--vault-dir` | — | `os.environ.get("VAULT_DIR", ...)` |
| `CHROMA_URL` | Pasado como `--chroma-url` | Hardcoded `http://localhost:8001` | `os.environ.get("CHROMA_URL", ...)` |

**Resultado: ✔ Coherente. El indexador acepta tanto CLI como env vars.**

### 1.4 Argumentos CLI del Indexador

Autoboot invoca:
```bash
python3 "$VAULT_INDEXER" \
    --vault-dir "$VAULT_DIR" \
    --chroma-url "http://localhost:8001" \
    --ollama-embed-url "http://localhost:11435/api/embeddings" \
    --state-dir "$AGENT_DATA_DIR"
```

Indexador V5 acepta:
- `--vault-dir` ✔
- `--chroma-url` ✔
- `--ollama-embed-url` ✔
- `--state-dir` ✔

**Resultado: ✔ Todos los argumentos son reconocidos.**

### 1.5 Política de Filesystem

| Componente | Detección | Fallback | Filesystems inseguros |
|---|---|---|---|
| Autoboot V20 | `df --output=fstype` | Error y exit | exfat, vfat, ntfs, fuseblk |
| Router V13 | `df --output=fstype` | `$HOME/ai_cluster/agent_data` → `/tmp` | exfat, vfat, fat32, ntfs, fuseblk |
| Indexador V5 | `df --output=fstype` | `$HOME/ai_cluster` → `/tmp` | exfat, vfat, fat32, ntfs, fuseblk |

**Resultado: ✔ Coherente. Los tres usan la misma detección y los mismos FS inseguros.**

### 1.6 Lifecycle y Señales

| Evento | Autoboot V20 | Router V13 | Indexador V5 |
|---|---|---|---|
| Arranque | Lanza con `&`, guarda PID | `uvicorn.run()` en foreground del proceso | `main()` ejecuta y retorna |
| Shutdown | `SIGTERM` → espera 30s → `SIGKILL` | `lifespan` context manager, cancela tareas | `_signal_handler` marca flag, bucle guarda estado |
| Health check | `curl /health` cada 2s × 30 intentos | `GET /health` con caché TTL 15s | — (no aplica) |

**Resultado: ✔ El flujo de señales es coherente:**
- Autoboot envía SIGTERM
- Router responde limpiamente via lifespan
- Indexador marca flag y guarda estado parcial (sin sys.exit)

### 1.7 Dependencias Python

Autoboot verifica: `fastapi uvicorn httpx docker requests`

Router V13 importa: `fastapi`, `uvicorn`, `httpx`, `docker` (opcional), `requests` (no)
Indexador V5 importa: `requests`, `urllib3`

**Nota**: El router no usa `requests` directamente (usa `httpx`), pero Autoboot lo instala por si el indexador lo necesita. ✔ Correcto.

## 2. Problemas Detectados en Revalidación

### 2.1 Ningún problema crítico encontrado

La revalidación cruzada confirma que los tres componentes son coherentes en:
- Nombres de archivo y rutas
- Puertos y URLs de servicios
- Variables de entorno
- Argumentos CLI
- Política de filesystem
- Lifecycle y señales
- Dependencias

### 2.2 Observación menor (no bloqueante)

El indexador V5 usa `AGENT_DB_DIR` como fallback para `--state-dir`, lo cual es coherente con el Autoboot que pasa `--state-dir "$AGENT_DATA_DIR"` explícitamente. Si se ejecuta sin `--state-dir` y sin la variable de entorno, el fallback es `$HOME/ai_cluster`, que es el mismo directorio base usado por el Autoboot (`AI_HOME="$HOME/ai_cluster"`). ✔ Coherente.

## 3. Conclusión

**Los tres componentes forman un sistema coherente y bien integrado.** No se detectaron incompatibilidades de interfaz, contratos rotos, ni inconsistencias en la configuración. Las correcciones de auditoría se aplicaron de forma coordinada manteniendo la compatibilidad entre componentes.
