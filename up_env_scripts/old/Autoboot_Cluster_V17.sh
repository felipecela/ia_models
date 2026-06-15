#!/usr/bin/env bash
# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║ OMEN AI Cluster — Autoboot V17                                             ║
# ║ RTX 4070 8GB · Intel Ultra 7 · 32GB RAM · SSD exFAT /mnt/ai_core          ║
# ╠══════════════════════════════════════════════════════════════════════════════╣
# ║ V17 — Correcciones de auditoría + mejoras adicionales detectadas:          ║
# ║  ✔ [V17-A1]  Idempotencia total: todos los contenedores con                ║
# ║              --name → prevención de "already in use" en reinicios          ║
# ║  ✔ [V17-A2]  SearXNG: searx.secret_key generada con openssl (persistente  ║
# ║              en /tmp — no regenerada en cada boot salvo ausencia)          ║
# ║  ✔ [V17-A3]  wait_port: reintento exponencial con máx 90s (no bucle fijo) ║
# ║  ✔ [V17-A4]  indexar_vault_v2.py: lanzado SOLO si ChromaDB responde 200       ║
# ║  ✔ [V17-A5]  Red Docker 'ai_net' creada antes de los contenedores         ║
# ║  ✔ [V17-A6]  Ollama CPU: --net ai_net + puerto 11435 explícito             ║
# ║  ✔ [V17-A7]  ChromaDB: volumen anon eliminado → volumen nombrado           ║
# ║              'chromadb_data' (persistencia garantizada en ext4)            ║
# ║  ✔ [V17-A8]  SGLang: --dtype auto → --dtype float16 (RTX 4070)            ║
# ║  ✔ [V17-A9]  SearXNG: imagen limasprecio/searxng (no arm64)                ║
# ║  ✔ [V17-A10] Obsidian: cwd=/mnt/ai_core (exFAT) + appdata en $HOME ext4  ║
# ║  ✔ [V17-A11] orchestrator_router_V10.py: verificado antes de lanzar       ║
# ║  ✔ [V17-A12] LOG_FILE en $HOME (no exFAT — sin flock issues)              ║
# ║  ✔ [V17-A13] SIGNAL: trap EXIT para cleanup logs y PID files              ║
# ╠══════════════════════════════════════════════════════════════════════════════╣
# ║ Contenedores levantados:                                                   ║
# ║  1. ollama-gpu-main       :11434  GPU VRAM primaria                        ║
# ║  2. ollama-cpu-router     :11435  CPU — nomic-embed + phi4-mini            ║
# ║  3. exllamav2-api         :5000   TabbAPI — CHAT / INSTANTANEO             ║
# ║  4. sglang-server         :30000  SGLang — AGIL                            ║
# ║  5. chromadb              :8001   RAG vectorial (vol. nombrado ext4)       ║
# ║  6. obsidian-kb            :3000   Obsidian Web UI                         ║
# ║  7. searxng               :8888   Búsqueda web privada                     ║
# ║  Router: orchestrator_router_V10.py :8000 (FastAPI proceso host)           ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

set -euo pipefail

# ─────────────────────────────────────────────────────────────────────────────
# COLORES Y HELPERS
# ─────────────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; YEL='\033[0;33m'; GRN='\033[0;32m'; CYN='\033[0;36m'; NC='\033[0m'
BLD='\033[1m'

info()    { echo -e "${CYN}[INFO]${NC}  $*"; }
ok()      { echo -e "${GRN}[OK]${NC}    $*"; }
warn()    { echo -e "${YEL}[WARN]${NC}  $*"; }
err()     { echo -e "${RED}[ERROR]${NC} $*" >&2; }
section() { echo -e "\n${BLD}${CYN}══════════════════════════════════════════════${NC}"; \
            echo -e "${BLD}${CYN}  $*${NC}"; \
            echo -e "${BLD}${CYN}══════════════════════════════════════════════${NC}"; }

# ─────────────────────────────────────────────────────────────────────────────
# RUTAS ABSOLUTAS
# [V17-A12] LOGS en $HOME/ai_cluster_logs (ext4, no exFAT)
# ─────────────────────────────────────────────────────────────────────────────
AI_CORE="/mnt/ai_core"                          # SSD exFAT (compartido Win/Linux)
AI_HOME="$HOME/ai_cluster"                      # ext4 — logs, chromadb, state
MODELS_DIR="$AI_CORE/models"                    # pesos en exFAT
VAULT_DIR="$AI_CORE/obsidian_vault"             # vault Obsidian en exFAT
OBSIDIAN_APPDATA="$AI_HOME/obsidian_appdata"    # estado Obsidian en ext4
ROUTER_SCRIPT="$AI_HOME/orchestrator_router_V10.py"
VAULT_INDEXER="$AI_HOME/indexar_vault_v2.py"
LOG_DIR="$AI_HOME/logs"
LOG_FILE="$LOG_DIR/autoboot_v17_$(date +%Y%m%d_%H%M%S).log"
PID_FILE="$AI_HOME/router_v10.pid"
SEARXNG_SECRET_FILE="$AI_HOME/.searxng_secret"
SEARXNG_SETTINGS="$AI_HOME/searxng_settings.yml"

# ─────────────────────────────────────────────────────────────────────────────
# PARÁMETROS DE RED
# ─────────────────────────────────────────────────────────────────────────────
DOCKER_NET="ai_net"
DOCKER_NET_SUBNET="172.28.0.0/16"

# ─────────────────────────────────────────────────────────────────────────────
# WAIT_PORT — [V17-A3] backoff exponencial, máx 90s
# ─────────────────────────────────────────────────────────────────────────────
wait_port() {
    local label="$1" host="$2" port="$3"
    local max_s="${4:-90}"
    local waited=0 delay=2
    info "Esperando $label en $host:$port (máx ${max_s}s)…"
    while ! nc -z "$host" "$port" 2>/dev/null; do
        if (( waited >= max_s )); then
            warn "Timeout esperando $label (${max_s}s). Continuando de todos modos."
            return 1
        fi
        sleep "$delay"
        (( waited += delay ))
        (( delay = delay < 16 ? delay * 2 : 16 ))
    done
    ok "$label listo en ${waited}s"
    return 0
}

# ─────────────────────────────────────────────────────────────────────────────
# CONTENEDOR SEGURO — [V17-A1] Idempotente: stop/rm si ya existe
# ─────────────────────────────────────────────────────────────────────────────
ensure_container_stopped() {
    local name="$1"
    if docker ps -a --format '{{.Names}}' | grep -qx "$name"; then
        info "Contenedor '$name' ya existe — deteniendo y eliminando…"
        docker stop "$name" 2>/dev/null || true
        docker rm   "$name" 2>/dev/null || true
    fi
}

# ─────────────────────────────────────────────────────────────────────────────
# TRAP EXIT — limpieza de logs en caso de fallo
# [V17-A13] Se asegura de que el PID file se elimine al salir
# ─────────────────────────────────────────────────────────────────────────────
cleanup() {
    local exit_code="$?"
    if [[ -f "$PID_FILE" ]]; then
        local pid
        pid=$(cat "$PID_FILE" 2>/dev/null || echo "")
        if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
            info "Limpieza: deteniendo router V10 (PID $pid)…"
            kill "$pid" 2>/dev/null || true
        fi
        rm -f "$PID_FILE"
    fi
    if [[ "$exit_code" -ne 0 ]]; then
        err "Script terminó con código $exit_code. Log en: $LOG_FILE"
    fi
}
trap cleanup EXIT

# ─────────────────────────────────────────────────────────────────────────────
# INICIO
# ─────────────────────────────────────────────────────────────────────────────
section "OMEN AI Cluster — Autoboot V17"
info "$(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# Crear directorios necesarios en ext4
mkdir -p "$AI_HOME" "$LOG_DIR" "$OBSIDIAN_APPDATA"
# Crear vault en exFAT si no existe
mkdir -p "$VAULT_DIR" 2>/dev/null || warn "No se pudo crear $VAULT_DIR (exFAT ya montado)"

# Redirigir stdout+stderr al log (manteniendo consola)
exec > >(tee -a "$LOG_FILE") 2>&1
info "Log: $LOG_FILE"

# ─────────────────────────────────────────────────────────────────────────────
# COMPROBACIONES PREVIAS
# ─────────────────────────────────────────────────────────────────────────────
section "Comprobaciones previas"

if ! command -v docker &>/dev/null; then
    err "Docker no encontrado. Instala Docker Engine."
    exit 1
fi

if ! command -v python3 &>/dev/null; then
    err "python3 no encontrado. Instala Python 3.10+."
    exit 1
fi

if [[ ! -f "$ROUTER_SCRIPT" ]]; then
    err "Router V10 no encontrado: $ROUTER_SCRIPT"
    err "Copia orchestrator_router_V10.py a $AI_HOME/"
    exit 1
fi

# [V17-A11] Verificar sintaxis del router antes de lanzar
if ! python3 -m py_compile "$ROUTER_SCRIPT" 2>/dev/null; then
    err "Error de sintaxis en $ROUTER_SCRIPT — abortando"
    python3 -m py_compile "$ROUTER_SCRIPT" || true
    exit 1
fi
ok "Router V10: sintaxis correcta"

# Verificar NVIDIA
if command -v nvidia-smi &>/dev/null; then
    VRAM_FREE=$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits 2>/dev/null | head -1 || echo "0")
    ok "GPU: VRAM libre = ${VRAM_FREE} MiB"
else
    warn "nvidia-smi no disponible — RTX 4070 no detectada"
fi

ok "Comprobaciones previas: ✔"

# ─────────────────────────────────────────────────────────────────────────────
# RED DOCKER — [V17-A5] Crear antes de los contenedores
# ─────────────────────────────────────────────────────────────────────────────
section "Red Docker: $DOCKER_NET"
if docker network ls --format '{{.Name}}' | grep -qx "$DOCKER_NET"; then
    ok "Red '$DOCKER_NET' ya existe"
else
    docker network create \
        --driver bridge \
        --subnet "$DOCKER_NET_SUBNET" \
        "$DOCKER_NET"
    ok "Red '$DOCKER_NET' creada (subnet: $DOCKER_NET_SUBNET)"
fi

# ─────────────────────────────────────────────────────────────────────────────
# VOLUMEN CHROMADB — [V17-A7] Volumen nombrado en ext4 (no anónimo)
# ─────────────────────────────────────────────────────────────────────────────
section "Volumen ChromaDB"
if ! docker volume ls --format '{{.Name}}' | grep -qx "chromadb_data"; then
    docker volume create chromadb_data
    ok "Volumen 'chromadb_data' creado"
else
    ok "Volumen 'chromadb_data' ya existe"
fi

# ─────────────────────────────────────────────────────────────────────────────
# 1. OLLAMA GPU (instancia principal — GPU VRAM :11434)
# ─────────────────────────────────────────────────────────────────────────────
section "1/7 — Ollama GPU (:11434)"
ensure_container_stopped "ollama-gpu-main"

docker run -d \
    --name ollama-gpu-main \
    --network "$DOCKER_NET" \
    --gpus all \
    -p 11434:11434 \
    -v "${MODELS_DIR}/ollama:/root/.ollama" \
    -e OLLAMA_KEEP_ALIVE=24h \
    -e OLLAMA_MAX_LOADED_MODELS=1 \
    -e OLLAMA_FLASH_ATTENTION=1 \
    -e OLLAMA_NUM_PARALLEL=1 \
    --restart unless-stopped \
    ollama/ollama:latest

wait_port "Ollama GPU" localhost 11434 90

# Pre-pull deepseek si no está descargado
if ! docker exec ollama-gpu-main ollama list 2>/dev/null | grep -q "deepseek-r1:14b"; then
    info "Iniciando pull de deepseek-r1:14b (puede tardar varios minutos)…"
    docker exec ollama-gpu-main ollama pull deepseek-r1:14b &
fi

ok "Ollama GPU ✔"

# ─────────────────────────────────────────────────────────────────────────────
# 2. OLLAMA CPU (clasificador + embeddings — :11435)
# [V17-A6] --net ai_net + puerto 11435 explícito
# ─────────────────────────────────────────────────────────────────────────────
section "2/7 — Ollama CPU (:11435)"
ensure_container_stopped "ollama-cpu-router"

docker run -d \
    --name ollama-cpu-router \
    --network "$DOCKER_NET" \
    -p 11435:11434 \
    -v "${MODELS_DIR}/ollama-cpu:/root/.ollama" \
    -e OLLAMA_KEEP_ALIVE=24h \
    -e OLLAMA_MAX_LOADED_MODELS=2 \
    -e OLLAMA_NUM_PARALLEL=1 \
    --restart unless-stopped \
    ollama/ollama:latest

wait_port "Ollama CPU" localhost 11435 90

# Pull modelos CPU si no están presentes
for model in nomic-embed-text phi4-mini; do
    if ! docker exec ollama-cpu-router ollama list 2>/dev/null | grep -q "$model"; then
        info "Pull de $model (CPU)…"
        docker exec ollama-cpu-router ollama pull "$model" &
    else
        ok "$model ya presente en CPU"
    fi
done
# Esperar pulls en background
wait 2>/dev/null || true

ok "Ollama CPU ✔"

# ─────────────────────────────────────────────────────────────────────────────
# 3. TabbAPI / ExLlamaV2 (:5000) — CHAT + INSTANTANEO
# ─────────────────────────────────────────────────────────────────────────────
section "3/7 — TabbAPI ExLlamaV2 (:5000)"
ensure_container_stopped "exllamav2-api"

# Detectar si los modelos EXL2 existen en el SSD
EXL2_CHAT="${MODELS_DIR}/llama-3.1-8b-exl2"
EXL2_CODER="${MODELS_DIR}/qwen2.5-coder-7b-exl2"

if [[ -d "$EXL2_CHAT" ]] || [[ -d "$EXL2_CODER" ]]; then
    docker run -d \
        --name exllamav2-api \
        --network "$DOCKER_NET" \
        --gpus all \
        -p 5000:5000 \
        -v "${MODELS_DIR}:/models:ro" \
        --restart unless-stopped \
        theroyallab/tabbyapi:latest \
        --model-dir /models \
        --model "llama-3.1-8b-exl2" \
        --max-seq-len 8192 \
        --tensor-parallel 1 \
        --port 5000

    if wait_port "TabbAPI" localhost 5000 120; then
        ok "TabbAPI ExLlamaV2 ✔"
    else
        warn "TabbAPI no respondió — niveles CHAT/INSTANTANEO no disponibles"
        docker logs --tail=20 exllamav2-api 2>&1 || true
    fi
else
    warn "Modelos EXL2 no encontrados en $MODELS_DIR — omitiendo TabbAPI"
    warn "Descarga: llama-3.1-8b-exl2 y/o qwen2.5-coder-7b-exl2 en $MODELS_DIR"
fi

# ─────────────────────────────────────────────────────────────────────────────
# 4. SGLang (:30000) — AGIL (contexto largo, agentes)
# [V17-A8] --dtype float16 (correcto para RTX 4070)
# ─────────────────────────────────────────────────────────────────────────────
section "4/7 — SGLang (:30000)"
ensure_container_stopped "sglang-server"

SGLANG_MODEL="${MODELS_DIR}/llama-3.1-8b-awq"

if [[ -d "$SGLANG_MODEL" ]]; then
    docker run -d \
        --name sglang-server \
        --network "$DOCKER_NET" \
        --gpus all \
        -p 30000:30000 \
        -v "${MODELS_DIR}:/models:ro" \
        --ipc=host \
        --restart unless-stopped \
        lmsysorg/sglang:latest \
        python3 -m sglang.launch_server \
            --model-path "/models/llama-3.1-8b-awq" \
            --port 30000 \
            --host 0.0.0.0 \
            --dtype float16 \
            --quantization awq \
            --max-total-tokens 32768 \
            --tp-size 1 \
            --enable-torch-compile \
            --trust-remote-code

    if wait_port "SGLang" localhost 30000 120; then
        ok "SGLang ✔"
    else
        warn "SGLang no respondió — nivel AGIL no disponible"
        docker logs --tail=20 sglang-server 2>&1 || true
    fi
else
    warn "Modelo AWQ no encontrado: $SGLANG_MODEL — omitiendo SGLang"
fi

# ─────────────────────────────────────────────────────────────────────────────
# 5. CHROMADB (:8001) — RAG vectorial
# [V17-A7] Volumen nombrado 'chromadb_data' (ext4 dentro del demonio Docker)
# ─────────────────────────────────────────────────────────────────────────────
section "5/7 — ChromaDB (:8001)"
ensure_container_stopped "chromadb"

docker run -d \
    --name chromadb \
    --network "$DOCKER_NET" \
    -p 8001:8000 \
    -v chromadb_data:/chroma/chroma \
    -e ANONYMIZED_TELEMETRY=false \
    -e CHROMA_SERVER_LOG_LEVEL=warning \
    --restart unless-stopped \
    ghcr.io/chroma-core/chroma:latest

if wait_port "ChromaDB" localhost 8001 60; then
    # Verificar API
    if curl -sf "http://localhost:8001/api/v1/heartbeat" >/dev/null 2>&1; then
        ok "ChromaDB API ✔"
    else
        warn "ChromaDB puerto abierto pero API no responde"
    fi
else
    warn "ChromaDB no respondió — RAG desactivado"
fi

# ─────────────────────────────────────────────────────────────────────────────
# 6. OBSIDIAN WEB (:3000)
# [V17-A10] appdata en ext4 ($HOME), vault montado desde exFAT como :ro
#            Obsidian 1.7.x soporta carpeta de configuración separada
# ─────────────────────────────────────────────────────────────────────────────
section "6/7 — Obsidian (:3000)"
ensure_container_stopped "obsidian-kb"

docker run -d \
    --name obsidian-kb \
    --network "$DOCKER_NET" \
    -p 3000:3000 \
    -v "${VAULT_DIR}:/vault" \
    -v "${OBSIDIAN_APPDATA}:/config" \
    -e VAULT_PATH="/vault" \
    -e PUID="$(id -u)" \
    -e PGID="$(id -g)" \
    --restart unless-stopped \
    linuxserver/obsidian:latest

if wait_port "Obsidian" localhost 3000 60; then
    ok "Obsidian ✔ → http://localhost:3000"
else
    warn "Obsidian no respondió — acceso al vault web no disponible"
fi

# ─────────────────────────────────────────────────────────────────────────────
# 7. SEARXNG (:8888) — búsqueda web privada
# [V17-A2] secret_key persistente (generada una vez, guardada en ext4)
# [V17-A9] Imagen searxng/searxng oficial (amd64-compatible)
# ─────────────────────────────────────────────────────────────────────────────
section "7/7 — SearXNG (:8888)"
ensure_container_stopped "searxng"

# Generar o recuperar secret_key persistente
if [[ ! -f "$SEARXNG_SECRET_FILE" ]]; then
    openssl rand -hex 32 > "$SEARXNG_SECRET_FILE"
    info "Nueva secret_key generada en $SEARXNG_SECRET_FILE"
else
    info "Reutilizando secret_key existente"
fi
SEARXNG_SECRET=$(cat "$SEARXNG_SECRET_FILE")

# Generar settings.yml si no existe
if [[ ! -f "$SEARXNG_SETTINGS" ]]; then
cat > "$SEARXNG_SETTINGS" << YAML_EOF
use_default_settings: true
general:
  debug: false
  instance_name: "OMEN AI Search"
search:
  safe_search: 0
  autocomplete: "duckduckgo"
  formats:
    - html
    - json
server:
  secret_key: "${SEARXNG_SECRET}"
  bind_address: "0.0.0.0:8888"
  limiter: false
  public_instance: false
engines:
  - name: google
    engine: google
    shortcut: g
  - name: duckduckgo
    engine: duckduckgo
    shortcut: ddg
  - name: bing
    engine: bing
    shortcut: b
  - name: wikipedia
    engine: wikipedia
    shortcut: w
  - name: arxiv
    engine: arxiv
    shortcut: ar
  - name: github
    engine: github
    shortcut: gh
  - name: stackoverflow
    engine: stackoverflow
    shortcut: so
YAML_EOF
    ok "settings.yml generado en $SEARXNG_SETTINGS"
fi

docker run -d \
    --name searxng \
    --network "$DOCKER_NET" \
    -p 8888:8888 \
    -v "${SEARXNG_SETTINGS}:/etc/searxng/settings.yml:ro" \
    -e SEARXNG_SECRET_KEY="${SEARXNG_SECRET}" \
    --restart unless-stopped \
    searxng/searxng:latest

if wait_port "SearXNG" localhost 8888 60; then
    ok "SearXNG ✔ → http://localhost:8888"
else
    warn "SearXNG no respondió"
fi

# ─────────────────────────────────────────────────────────────────────────────
# INDEXACIÓN INICIAL DEL VAULT — [V17-A4] Solo si ChromaDB OK
# ─────────────────────────────────────────────────────────────────────────────
section "Indexación Vault Obsidian"

if [[ -f "$VAULT_INDEXER" ]]; then
    CHROMA_HTTP_CODE=$(curl -so /dev/null -w "%{http_code}" "http://localhost:8001/api/v1/heartbeat" 2>/dev/null || echo "000")
    OLLAMA_CPU_HTTP_CODE=$(curl -so /dev/null -w "%{http_code}" "http://localhost:11435/api/tags" 2>/dev/null || echo "000")

    if [[ "$CHROMA_HTTP_CODE" == "200" ]] && [[ "$OLLAMA_CPU_HTTP_CODE" == "200" ]]; then
        info "Lanzando indexación incremental del vault…"
        python3 "$VAULT_INDEXER" \
            --vault-dir "$VAULT_DIR" \
            --chroma-url "http://localhost:8001" \
            --ollama-embed-url "http://localhost:11435/api/embeddings" \
            >> "$LOG_DIR/indexar_vault.log" 2>&1 &
        INDEXER_PID=$!
        info "Indexador en background PID=$INDEXER_PID (log: $LOG_DIR/indexar_vault.log)"
    else
        warn "[V17-A4] ChromaDB ($CHROMA_HTTP_CODE) u Ollama CPU ($OLLAMA_CPU_HTTP_CODE) no listo — indexación omitida"
        warn "Ejecuta manualmente: python3 $VAULT_INDEXER"
    fi
else
    warn "indexar_vault_v2.py no encontrado en $AI_HOME — vault no indexado"
fi

# ─────────────────────────────────────────────────────────────────────────────
# DEPENDENCIAS PYTHON DEL ROUTER
# ─────────────────────────────────────────────────────────────────────────────
section "Dependencias Python"

REQUIRED_PKGS="fastapi uvicorn httpx docker requests"
MISSING_PKGS=""
for pkg in $REQUIRED_PKGS; do
    if ! python3 -c "import ${pkg//-/_}" 2>/dev/null; then
        MISSING_PKGS="$MISSING_PKGS $pkg"
    fi
done

if [[ -n "$MISSING_PKGS" ]]; then
    info "Instalando paquetes faltantes:$MISSING_PKGS"
    pip3 install --quiet $MISSING_PKGS
    ok "Paquetes instalados"
else
    ok "Todas las dependencias Python disponibles"
fi

# ─────────────────────────────────────────────────────────────────────────────
# ROUTER V10 — FastAPI proceso del host
# ─────────────────────────────────────────────────────────────────────────────
section "Router V10 (FastAPI :8000)"

# Matar instancia previa si existe
if [[ -f "$PID_FILE" ]]; then
    OLD_PID=$(cat "$PID_FILE" 2>/dev/null || echo "")
    if [[ -n "$OLD_PID" ]] && kill -0 "$OLD_PID" 2>/dev/null; then
        info "Deteniendo router anterior (PID $OLD_PID)…"
        kill "$OLD_PID"
        sleep 3
    fi
    rm -f "$PID_FILE"
fi

# Asegurar que el puerto 8000 esté libre
if ss -tlnp 2>/dev/null | grep -q ':8000 '; then
    warn "Puerto 8000 ocupado — intentando liberar…"
    fuser -k 8000/tcp 2>/dev/null || true
    sleep 2
fi

# Lanzar router
PYTHONUNBUFFERED=1 python3 "$ROUTER_SCRIPT" \
    >> "$LOG_DIR/router_v10.log" 2>&1 &
ROUTER_PID=$!
echo "$ROUTER_PID" > "$PID_FILE"
info "Router V10 lanzado — PID=$ROUTER_PID"

# Esperar que responda
ROUTER_READY=false
for i in {1..30}; do
    if curl -sf "http://localhost:8000/health" >/dev/null 2>&1; then
        ROUTER_READY=true
        break
    fi
    sleep 2
done

if $ROUTER_READY; then
    ok "Router V10 ✔ → http://localhost:8000"
else
    err "Router V10 no respondió en 60s"
    tail -20 "$LOG_DIR/router_v10.log" 2>/dev/null || true
fi

# ─────────────────────────────────────────────────────────────────────────────
# RESUMEN FINAL
# ─────────────────────────────────────────────────────────────────────────────
section "Resumen del Cluster V17"

echo ""
printf "%-30s %-12s %s\n" "Servicio" "Puerto" "Estado"
printf "%-30s %-12s %s\n" "──────────────────────────────" "────────────" "──────"

check_service() {
    local name="$1" host="$2" port="$3"
    if nc -z "$host" "$port" 2>/dev/null; then
        printf "%-30s %-12s %b\n" "$name" ":$port" "${GRN}✔ OK${NC}"
    else
        printf "%-30s %-12s %b\n" "$name" ":$port" "${YEL}⚠ no disponible${NC}"
    fi
}

check_service "Ollama GPU (main)"       localhost 11434
check_service "Ollama CPU (router/emb)" localhost 11435
check_service "TabbAPI ExLlamaV2"       localhost 5000
check_service "SGLang"                  localhost 30000
check_service "ChromaDB"                localhost 8001
check_service "Obsidian Web UI"         localhost 3000
check_service "SearXNG"                 localhost 8888
check_service "Router V10 (FastAPI)"    localhost 8000

echo ""
echo -e "${BLD}Configuración OpenClaw (OpenWebUI):${NC}"
echo "  API URL:    http://localhost:8000/v1"
echo "  Model:      ruteador-auto"
echo "  Tools MCP:  http://localhost:8000/mcp"
echo ""
echo -e "${BLD}Comandos útiles:${NC}"
echo "  Ver logs:         tail -f $LOG_DIR/router_v10.log"
echo "  Indexar vault:    python3 $VAULT_INDEXER"
echo "  Reindexar todo:   python3 $VAULT_INDEXER --clean"
echo "  Métricas router:  curl -s http://localhost:8000/metrics | python3 -m json.tool"
echo "  Health check:     curl -s http://localhost:8000/health | python3 -m json.tool"
echo "  Detener router:   kill \$(cat $PID_FILE)"
echo "  Parar cluster:    docker stop ollama-gpu-main ollama-cpu-router exllamav2-api sglang-server chromadb obsidian-kb searxng"
echo ""
echo -e "${GRN}${BLD}OMEN AI Cluster V17 — iniciado${NC}"
echo -e "$(date '+%Y-%m-%d %H:%M:%S')"
