#!/bin/bash
# ╔══════════════════════════════════════════════════════════════════════════╗
# ║         OMEN AI CLUSTER — Autoboot_Cluster_V13.sh                       ║
# ╠══════════════════════════════════════════════════════════════════════════╣
# ║  Novedades V13 sobre V12:                                                ║
# ║  ✔ [V13-A] phi4-reasoning:plus  → nivel PRECISO (Phi Mayor Precisión)   ║
# ║  ✔ [V13-A] phi4-reasoning:14b-q4_K_M → nivel PRECISO_OPT (Optimizada)  ║
# ║  ✔ [V13-B] Obsidian Docker (puerto 3000) — base de conocimiento         ║
# ║  ✔ [V13-C] ChromaDB (puerto 8001) — motor RAG para el vault Obsidian    ║
# ║  ✔ [V13-D] SearXNG (puerto 8888) — búsqueda web privada, sin API keys   ║
# ║  ✔ [V13-E] OpenClaw V13 con agentes @coder @analyst @reasoner @researcher║
# ║             + plugins SearXNG + MCP knowledge-base ChromaDB              ║
# ╚══════════════════════════════════════════════════════════════════════════╝
#
# USO:
#   ./Autoboot_Cluster_V13.sh             # Arranque completo
#   ./Autoboot_Cluster_V13.sh --stop      # Parar todo
#   ./Autoboot_Cluster_V13.sh --status    # Estado de todos los servicios
#   ./Autoboot_Cluster_V13.sh --reindex   # Re-indexar vault Obsidian en ChromaDB
#
set -uo pipefail

# ─────────────────────────────────────────────────────────────────────────────
#  CONFIGURACIÓN — ajusta AI_CORE si tu punto de montaje exFAT difiere
# ─────────────────────────────────────────────────────────────────────────────
AI_CORE="${AI_CORE:-/home/fcela-ga/sgoinfre/ai_core}"
OLLAMA_MODELS_DIR="$AI_CORE/ollama_storage"
EXLLAMA_MODELS_DIR="$AI_CORE/exllamav2_storage"
SGLANG_MODELS_DIR="$AI_CORE/sglang_storage"
OBSIDIAN_VAULT_DIR="$AI_CORE/obsidian_vault"    # En exFAT (accesible desde Windows)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROUTER_SCRIPT="$SCRIPT_DIR/orchestrator_router_V6.py"
INDEXER_SCRIPT="$SCRIPT_DIR/indexar_vault.py"
TABBYAPI_CONFIG="$SCRIPT_DIR/config_tabbyapi_v13.yml"
CHROMA_DATA_DIR="$SCRIPT_DIR/chroma_data"       # En ext4 (SQLite necesita permisos Unix)
SEARXNG_CONFIG_DIR="$SCRIPT_DIR/searxng_config" # En ext4
OBSIDIAN_CONFIG_DIR="$SCRIPT_DIR/obsidian_config" # En ext4
ROUTER_LOG="$SCRIPT_DIR/router_v13.log"
ROUTER_PID_FILE="$SCRIPT_DIR/router_v13.pid"
OLLAMA_TMPDIR="${OLLAMA_TMPDIR:-/tmp/ollama_tmp}"

# ─────────────────────────────────────────────────────────────────────────────
#  COLORES Y LOGGING
# ─────────────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
TS()    { date '+%H:%M:%S'; }
info()  { echo -e "[$(TS)] ${BLUE}ℹ  $*${NC}"; }
ok()    { echo -e "[$(TS)] ${GREEN}${BOLD}✔  $*${NC}"; }
warn()  { echo -e "[$(TS)] ${YELLOW}⚠  $*${NC}"; }
error() { echo -e "[$(TS)] ${RED}${BOLD}✘  $*${NC}"; }
step()  { echo -e "\n[$(TS)] ${CYAN}${BOLD}──── $* ────${NC}"; }

wait_http() {
    local url="$1" timeout="${2:-60}" label="${3:-servicio}"
    local elapsed=0
    info "Esperando '$label' en $url (max ${timeout}s)…"
    while ! curl -sf --max-time 3 "$url" >/dev/null 2>&1; do
        sleep 3; elapsed=$((elapsed + 3))
        [ $elapsed -ge $timeout ] && { warn "Timeout (${timeout}s) '$label'"; return 1; }
        printf "."
    done
    echo ""; ok "$label listo (${elapsed}s)"
}

# ─────────────────────────────────────────────────────────────────────────────
#  MODO --stop
# ─────────────────────────────────────────────────────────────────────────────
if [ "${1:-}" = "--stop" ]; then
    step "Deteniendo clúster OMEN V13…"
    [ -f "$ROUTER_PID_FILE" ] && kill "$(cat "$ROUTER_PID_FILE")" 2>/dev/null || true
    pkill -f orchestrator_router 2>/dev/null || true
    docker stop openclaw-server exllamav2-api sglang-server \
                ollama-cpu-router obsidian-kb chromadb searxng 2>/dev/null || true
    docker rm   openclaw-server exllamav2-api sglang-server \
                ollama-cpu-router obsidian-kb chromadb searxng 2>/dev/null || true
    sudo systemctl stop ollama 2>/dev/null || true
    rm -f "$ROUTER_PID_FILE"
    ok "Clúster V13 detenido."; exit 0
fi

# ─────────────────────────────────────────────────────────────────────────────
#  MODO --status
# ─────────────────────────────────────────────────────────────────────────────
if [ "${1:-}" = "--status" ]; then
    step "Estado del clúster OMEN V13"
    echo ""
    declare -A CHK=(
        ["Router V6   :8000"]="http://localhost:8000/health"
        ["Ollama GPU  :11434"]="http://localhost:11434/api/tags"
        ["Ollama CPU  :11435"]="http://localhost:11435/api/tags"
        ["TabbAPI     :5000"]="http://localhost:5000/health"
        ["SGLang      :30000"]="http://localhost:30000/health"
        ["OpenClaw UI :8080"]="http://localhost:8080"
        ["ChromaDB    :8001"]="http://localhost:8001/api/v1/heartbeat"
        ["SearXNG     :8888"]="http://localhost:8888/search?q=test&format=json"
        ["Obsidian    :3000"]="http://localhost:3000"
    )
    for svc in "Router V6   :8000" "Ollama GPU  :11434" "Ollama CPU  :11435" \
               "TabbAPI     :5000" "SGLang      :30000" "OpenClaw UI :8080" \
               "ChromaDB    :8001" "SearXNG     :8888" "Obsidian    :3000"; do
        url="${CHK[$svc]}"
        if curl -sf --max-time 2 "$url" >/dev/null 2>&1; then
            printf "  ${GREEN}${BOLD}%-28s ✔ UP${NC}\n" "$svc"
        else
            printf "  ${RED}%-28s ✘ DOWN${NC}\n" "$svc"
        fi
    done
    echo ""
    info "Métricas:  curl -s http://localhost:8000/metrics | python3 -m json.tool"
    info "Modelos:   curl -s http://localhost:8000/v1/models | python3 -m json.tool"
    info "Vault:     http://localhost:3000  (Obsidian)"
    info "Búsqueda:  http://localhost:8888  (SearXNG)"
    exit 0
fi

# ─────────────────────────────────────────────────────────────────────────────
#  MODO --reindex
# ─────────────────────────────────────────────────────────────────────────────
if [ "${1:-}" = "--reindex" ]; then
    step "Re-indexando vault Obsidian en ChromaDB…"
    [ -f "$INDEXER_SCRIPT" ] || { error "No se encuentra $INDEXER_SCRIPT"; exit 1; }
    python3 "$INDEXER_SCRIPT" && ok "Re-indexación completada" || warn "Error en re-indexación"
    exit 0
fi

# ─────────────────────────────────────────────────────────────────────────────
#  BANNER
# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}${BOLD}╔══════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}${BOLD}║    OMEN AI CLUSTER V13 — INICIALIZANDO                          ║${NC}"
echo -e "${CYAN}${BOLD}║    RTX 4070 8GB · Ultra 7 · 32GB RAM · SSD exFAT                ║${NC}"
echo -e "${CYAN}${BOLD}║    + Obsidian RAG · SearXNG Web · Phi-4-reasoning                ║${NC}"
echo -e "${CYAN}${BOLD}╚══════════════════════════════════════════════════════════════════╝${NC}"
echo ""

# ─────────────────────────────────────────────────────────────────────────────
#  VERIFICACIONES PREVIAS
# ─────────────────────────────────────────────────────────────────────────────
step "VERIFICACIONES PREVIAS"

[ -f "$ROUTER_SCRIPT" ]          || { error "No se encuentra $ROUTER_SCRIPT"; exit 1; }
command -v docker  >/dev/null 2>&1 || { error "Docker no instalado"; exit 1; }
command -v python3 >/dev/null 2>&1 || { error "Python3 no encontrado"; exit 1; }
command -v curl    >/dev/null 2>&1 || { error "curl no encontrado"; exit 1; }
command -v openssl >/dev/null 2>&1 || warn "openssl no encontrado (se usará clave fija en SearXNG)"

# Directorios base
[ -d "$OLLAMA_MODELS_DIR" ]  || { error "ollama_storage no encontrado: $OLLAMA_MODELS_DIR"; exit 1; }
[ -d "$EXLLAMA_MODELS_DIR" ] || { error "exllamav2_storage no encontrado"; exit 1; }
[ -d "$SGLANG_MODELS_DIR" ]  || { error "sglang_storage no encontrado"; exit 1; }

# Modelos ExLlamaV2
[ -d "$EXLLAMA_MODELS_DIR/qwen2.5-coder-7b-exl2" ] || {
    error "Modelo INSTANTANEO no encontrado: qwen2.5-coder-7b-exl2"
    info  "hf download bartowski/Qwen2.5-Coder-7B-Instruct-exl2 --revision 6_5 --local-dir qwen2.5-coder-7b-exl2"
    exit 1
}
ok "qwen2.5-coder-7b-exl2 ✔"

[ -d "$EXLLAMA_MODELS_DIR/llama-3.1-8b-exl2" ] && ok "llama-3.1-8b-exl2 ✔ (nivel CHAT)" \
    || warn "llama-3.1-8b-exl2 no encontrado (nivel CHAT no disponible)"

[ -d "$SGLANG_MODELS_DIR/llama-3.1-8b-awq" ] \
    && ok "llama-3.1-8b-awq ✔ (SGLang AGIL)" \
    || { error "llama-3.1-8b-awq no encontrado en sglang_storage"; exit 1; }

# [V13-A] Verificar modelos Phi-4-reasoning
check_ollama() { ollama list 2>/dev/null | grep -q "$1"; }

if check_ollama "phi4-reasoning:plus"; then
    ok "phi4-reasoning:plus ✔ (nivel PRECISO — Phi Mayor Precisión)"
else
    warn "phi4-reasoning:plus NO instalado"
    info "Instala con: ollama pull phi4-reasoning:plus"
    info "(~11GB — nivel PRECISO no disponible hasta instalarlo)"
fi

if check_ollama "phi4-reasoning:14b-q4_K_M"; then
    ok "phi4-reasoning:14b-q4_K_M ✔ (nivel PRECISO_OPT — Phi Optimizada)"
else
    warn "phi4-reasoning:14b-q4_K_M NO instalado"
    info "Instala con: ollama pull phi4-reasoning:14b-q4_K_M"
fi

check_ollama "deepseek-r1" && ok "deepseek-r1 ✔" || warn "deepseek-r1 no encontrado"
check_ollama "qwen2.5:32b" && ok "qwen2.5:32b ✔" || warn "qwen2.5:32b no encontrado"

# Phi-4-mini / phi4 para el clasificador
PHI4_CLASIFICADOR=""
if check_ollama "phi4-mini"; then PHI4_CLASIFICADOR="phi4-mini"; ok "phi4-mini ✔ (clasificador)"
elif check_ollama "phi4"; then    PHI4_CLASIFICADOR="phi4";      warn "phi4 como clasificador (descarga phi4-mini para mayor velocidad)"
else warn "Sin clasificador LLM (solo embeddings para routing)"; fi

# Instalar dependencias Python del router
python3 -c "import fastapi, uvicorn, httpx, docker" 2>/dev/null || {
    info "Instalando dependencias Python…"
    pip3 install --quiet fastapi uvicorn httpx docker
}
python3 -c "import chromadb" 2>/dev/null || {
    info "Instalando chromadb para el indexador del vault…"
    pip3 install --quiet chromadb
}
ok "Verificaciones completadas"

# ─────────────────────────────────────────────────────────────────────────────
#  PASO 1: LIMPIEZA
# ─────────────────────────────────────────────────────────────────────────────
step "PASO 1/11 — Limpiando estado anterior"
[ -f "$ROUTER_PID_FILE" ] && { kill "$(cat "$ROUTER_PID_FILE")" 2>/dev/null || true; rm -f "$ROUTER_PID_FILE"; }
pkill -f orchestrator_router 2>/dev/null || true
docker stop openclaw-server exllamav2-api sglang-server \
            ollama-cpu-router obsidian-kb chromadb searxng 2>/dev/null || true
docker rm   openclaw-server exllamav2-api sglang-server \
            ollama-cpu-router obsidian-kb chromadb searxng 2>/dev/null || true
sudo systemctl stop ollama 2>/dev/null || true
sleep 2; ok "Limpieza OK"

# ─────────────────────────────────────────────────────────────────────────────
#  PASO 2: OLLAMA GPU (systemd nativo)
# ─────────────────────────────────────────────────────────────────────────────
step "PASO 2/11 — Ollama GPU (puerto 11434)"
sudo mkdir -p "$OLLAMA_TMPDIR" && sudo chmod 777 "$OLLAMA_TMPDIR"
sudo mkdir -p /etc/systemd/system/ollama.service.d
sudo bash -c "cat > /etc/systemd/system/ollama.service.d/override.conf" << OVR_EOF
[Service]
Environment="OLLAMA_MODELS=$OLLAMA_MODELS_DIR"
Environment="OLLAMA_HOST=0.0.0.0:11434"
Environment="OLLAMA_TMPDIR=$OLLAMA_TMPDIR"
OVR_EOF
sudo systemctl daemon-reload 2>/dev/null || true
sudo systemctl start ollama
wait_http "http://localhost:11434/api/tags" 45 "Ollama GPU" || {
    sudo systemctl restart ollama
    wait_http "http://localhost:11434/api/tags" 30 "Ollama GPU" || { error "Ollama GPU no disponible"; exit 1; }
}

# ─────────────────────────────────────────────────────────────────────────────
#  PASO 3: OLLAMA CPU-ONLY (phi4-mini + nomic-embed-text)
# ─────────────────────────────────────────────────────────────────────────────
step "PASO 3/11 — Ollama CPU-only: embeddings + clasificador (puerto 11435)"
docker run -d \
  --name ollama-cpu-router \
  --restart unless-stopped \
  --gpus "" \
  -p 11435:11434 \
  -e CUDA_VISIBLE_DEVICES="" \
  -e OLLAMA_MODELS=/models \
  -e OLLAMA_HOST=0.0.0.0:11434 \
  -e OLLAMA_TMPDIR=/tmp \
  -v "${OLLAMA_MODELS_DIR}":/models \
  ollama/ollama

wait_http "http://localhost:11435/api/tags" 50 "Ollama CPU Router" \
    || warn "Ollama CPU no respondió — clasificador y embeddings pueden tardar"

# Verificar nomic-embed-text
info "Verificando nomic-embed-text en instancia CPU…"
if ! docker exec ollama-cpu-router ollama list 2>/dev/null | grep -q "nomic-embed-text"; then
    info "Descargando nomic-embed-text (~274MB)…"
    docker exec ollama-cpu-router ollama pull nomic-embed-text \
        && ok "nomic-embed-text listo" \
        || warn "No se pudo descargar nomic-embed-text"
else
    ok "nomic-embed-text disponible"
fi

# ─────────────────────────────────────────────────────────────────────────────
#  PASO 4: TABBYAPI / EXLLAMAV2 (STANDBY)
# ─────────────────────────────────────────────────────────────────────────────
step "PASO 4/11 — TabbAPI/ExLlamaV2 (STANDBY)"
cat > "$TABBYAPI_CONFIG" << 'TABBY_CONF'
network:
  host: 0.0.0.0
  port: 5000
  disable_auth: true     # Permite /v1/model/load sin admin key
model:
  model_name: qwen2.5-coder-7b-exl2
  max_seq_len: 4096
  cache_mode: Q4
logging:
  log_prompt: false
  log_generation_params: false
TABBY_CONF

docker create --gpus all --name exllamav2-api -p 5000:5000 \
  -v "${EXLLAMA_MODELS_DIR}":/models \
  -v "${TABBYAPI_CONFIG}":/app/config.yml:ro \
  ghcr.io/theroyallab/tabbyapi:latest 2>/dev/null || warn "exllamav2-api ya existe"
ok "TabbAPI en STANDBY"

# ─────────────────────────────────────────────────────────────────────────────
#  PASO 5: SGLANG (STANDBY)
# ─────────────────────────────────────────────────────────────────────────────
step "PASO 5/11 — SGLang (STANDBY)"
docker create --gpus all --name sglang-server --ipc=host --shm-size=2gb -p 30000:30000 \
  -v "${SGLANG_MODELS_DIR}":/models \
  lmsysorg/sglang:latest \
  python3 -m sglang.launch_server \
    --model-path /models/llama-3.1-8b-awq \
    --quantization awq \
    --served-model-name llama-3.1-8b-awq \
    --port 30000 --host 0.0.0.0 \
    --context-length 32768 \
    --mem-fraction-static 0.85 \
    --enable-cache-report 2>/dev/null || warn "sglang-server ya existe"
ok "SGLang en STANDBY"

# ─────────────────────────────────────────────────────────────────────────────
#  PASO 6: SEARXNG — búsqueda web privada, sin API keys (puerto 8888)
#  [V13-D] Se levanta ANTES de OpenClaw (el plugin de web search lo necesita)
# ─────────────────────────────────────────────────────────────────────────────
step "PASO 6/11 — SearXNG: búsqueda web privada (puerto 8888)"
mkdir -p "$SEARXNG_CONFIG_DIR"

if [ ! -f "$SEARXNG_CONFIG_DIR/settings.yml" ]; then
    SECRET=$(openssl rand -hex 32 2>/dev/null || echo "omen-cluster-searxng-secret-key-v13")
    cat > "$SEARXNG_CONFIG_DIR/settings.yml" << SEARX_CONF
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
SEARX_CONF
    ok "SearXNG settings.yml generado"
fi

docker run -d \
  --name searxng \
  --restart unless-stopped \
  -p 127.0.0.1:8888:8080 \
  -v "${SEARXNG_CONFIG_DIR}/settings.yml":/etc/searxng/settings.yml:ro \
  --memory=384m \
  --cpus=0.5 \
  searxng/searxng:latest

wait_http "http://localhost:8888/search?q=test&format=json" 35 "SearXNG" \
    || warn "SearXNG tardó en arrancar — la búsqueda web puede no estar disponible"
ok "SearXNG disponible en http://localhost:8888"

# ─────────────────────────────────────────────────────────────────────────────
#  PASO 7: CHROMADB — motor RAG vectorial (puerto 8001)
#  [V13-C] Los datos van en ext4 (SQLite necesita permisos Unix para escritura atómica)
# ─────────────────────────────────────────────────────────────────────────────
step "PASO 7/11 — ChromaDB: motor RAG (puerto 8001)"
mkdir -p "$CHROMA_DATA_DIR"

docker run -d \
  --name chromadb \
  --restart unless-stopped \
  -p 8001:8000 \
  -e CHROMA_SERVER_HTTP_PORT=8000 \
  -e ANONYMIZED_TELEMETRY=false \
  -v "${CHROMA_DATA_DIR}":/chroma/chroma \
  chromadb/chroma:latest

wait_http "http://localhost:8001/api/v1/heartbeat" 35 "ChromaDB" \
    || warn "ChromaDB no respondió (puede tardar en el primer arranque)"
ok "ChromaDB disponible en http://localhost:8001"

# ─────────────────────────────────────────────────────────────────────────────
#  PASO 8: OBSIDIAN — base de conocimiento en Markdown (puerto 3000)
#  [V13-B] El vault vive en el SSD exFAT — accesible desde Windows Y Linux
#  Imagen: lscr.io/linuxserver/obsidian:latest (KasmVNC, más ligera que noVNC)
# ─────────────────────────────────────────────────────────────────────────────
step "PASO 8/11 — Obsidian: base de conocimiento (puerto 3000)"
mkdir -p "$OBSIDIAN_VAULT_DIR" "$OBSIDIAN_CONFIG_DIR"

docker run -d \
  --name obsidian-kb \
  --restart unless-stopped \
  -p 3000:3000 \
  -p 3001:3001 \
  -e PUID=1000 \
  -e PGID=1000 \
  -e TZ=Europe/Madrid \
  -v "${OBSIDIAN_VAULT_DIR}":/config/obsidian_vault \
  -v "${OBSIDIAN_CONFIG_DIR}":/config \
  --security-opt seccomp=unconfined \
  --shm-size=1gb \
  lscr.io/linuxserver/obsidian:latest

wait_http "http://localhost:3000" 55 "Obsidian" \
    || warn "Obsidian tarda en arrancar la primera vez (Docker pull + init)"
ok "Obsidian disponible en http://localhost:3000"

# ─────────────────────────────────────────────────────────────────────────────
#  PASO 9: OPENCLAW — con config V13 completa
#  [V13-E] openclaw.json con: PRECISO, 4 agentes, SearXNG plugin, RAG system prompt
# ─────────────────────────────────────────────────────────────────────────────
step "PASO 9/11 — OpenClaw (puerto 8080)"
docker volume create openclaw_data_v13 >/dev/null 2>&1 || true

docker run -d \
  --name openclaw-server \
  --restart unless-stopped \
  -p 8080:8080 \
  -p 18789:18789 \
  --add-host host.docker.internal:host-gateway \
  -e OPENCLAW_GATEWAY_TOKEN="7c9b84a2f1e63d5c8a4b29f7e0d1c4a5b6e7f8d9c0a1b2c3d4e5f6a7b8c9d0e1" \
  -e OPENAI_API_KEY="sk-router-local" \
  -e OPENAI_BASE_URL="http://host.docker.internal:8000/v1" \
  -e OPENCLAW_PRIMARY_MODEL="local_router/ruteador-auto" \
  -v openclaw_data_v13:/data \
  coollabsio/openclaw:latest

info "Esperando inicialización de OpenClaw (25s)…"
sleep 25
docker exec openclaw-server mkdir -p /data/.openclaw

# ── Inyectar openclaw.json V13 (agentes + PRECISO + plugins SearXNG) ────────
info "Inyectando openclaw.json V13…"
docker exec openclaw-server bash -c 'cat > /data/.openclaw/openclaw.json' << 'OPENCLAW_V13'
{
  "gateway": {
    "bind": "lan",
    "controlUi": {
      "allowedOrigins": ["http://localhost:8080", "http://127.0.0.1:8080"]
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
          { "id": "ruteador-auto",       "name": "🤖 Auto — clasificador 3 capas",                       "contextWindow": 32768, "maxTokens": 16384 },
          { "id": "chat",                "name": "💬 Chat (Llama 3.1 8B EXL2)",                           "contextWindow": 8192,  "maxTokens": 4096  },
          { "id": "instantaneo",         "name": "⚡ Instantáneo (Qwen2.5 Coder 7B)",                     "contextWindow": 4096,  "maxTokens": 2048  },
          { "id": "agil",                "name": "🚀 Ágil (SGLang · agentes y documentos)",               "contextWindow": 32768, "maxTokens": 8192  },
          { "id": "profundo",            "name": "🧠 Profundo (DeepSeek R1 14B)",                         "contextWindow": 16384, "maxTokens": 8192  },
          { "id": "phi-mayor-precision", "name": "🎯 Phi Mayor Precisión (phi4-reasoning:plus)",          "contextWindow": 16384, "maxTokens": 4096  },
          { "id": "phi-optimizada",      "name": "⚡ Phi Optimizada (phi4-reasoning:14b-q4_K_M)",         "contextWindow": 16384, "maxTokens": 4096  },
          { "id": "masivo",              "name": "🔬 Masivo (Qwen2.5 32B · análisis extenso)",            "contextWindow": 32768, "maxTokens": 16384 },
          { "id": "codigo",              "name": "💻 Código → Inst. (Qwen Coder 7B)",                     "contextWindow": 4096,  "maxTokens": 2048  },
          { "id": "phi4",                "name": "🔷 Phi-4 CPU (clasificador directo)",                   "contextWindow": 16384, "maxTokens": 4096  }
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
      "systemPrompt": "Cuando respondas, si la pregunta puede estar relacionada con el conocimiento local del usuario, consulta primero la base de conocimiento (search_knowledge_base). Si encuentras información relevante en el vault de Obsidian, cítala indicando el archivo fuente (ejemplo: [Nota: Research/LLM-Benchmarks.md]). Para preguntas sobre eventos recientes o que requieran información actualizada, usa la herramienta de búsqueda web. Siempre indica qué fuentes usaste.",
      "subagents": {
        "model": "local_router/agil",
        "maxConcurrent": 2,
        "runTimeoutSeconds": 300
      },
      "thinkingDefault": "low",
      "maxConcurrent": 2,
      "timeoutSeconds": 600,
      "contextTokens": 32768
    },
    "list": [
      {
        "id": "coder",
        "name": "🖥️ Agente Coder",
        "model": {
          "primary":   "local_router/instantaneo",
          "fallbacks": ["local_router/profundo"]
        }
      },
      {
        "id": "analyst",
        "name": "📊 Agente Analyst",
        "model": {
          "primary":   "local_router/masivo",
          "fallbacks": ["local_router/profundo"]
        }
      },
      {
        "id": "reasoner",
        "name": "🧠 Agente Reasoner",
        "model": {
          "primary":   "local_router/phi-mayor-precision",
          "fallbacks": ["local_router/profundo"]
        }
      },
      {
        "id": "researcher",
        "name": "🔍 Agente Researcher",
        "model": {
          "primary":   "local_router/agil",
          "fallbacks": ["local_router/profundo"]
        },
        "systemPromptSuffix": "Eres un agente especializado en investigación. SIEMPRE usa search_knowledge_base para buscar en el vault local Y la herramienta de búsqueda web para encontrar información reciente. Combina ambas fuentes y cita todas las fuentes claramente."
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
          "timeoutMs": 10000,
          "categories": ["general", "news", "science"]
        }
      }
    }
  }
}
OPENCLAW_V13

# ── Inyectar mcp.json para ChromaDB RAG ─────────────────────────────────────
info "Inyectando mcp.json para ChromaDB knowledge base…"
docker exec openclaw-server bash -c 'cat > /data/.openclaw/mcp.json' << 'MCP_V13'
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
MCP_V13

# Intentar instalar plugin SearXNG si openclaw CLI disponible
docker exec openclaw-server sh -c \
  "openclaw plugins install https://github.com/akr-n/openclaw-search.git" 2>/dev/null \
  && ok "Plugin SearXNG instalado" \
  || info "Plugin SearXNG se activará vía openclaw.json (configuración ya inyectada)"

info "Reiniciando OpenClaw para aplicar configuración V13…"
docker restart openclaw-server >/dev/null; sleep 8
wait_http "http://localhost:8080" 35 "OpenClaw UI" || warn "OpenClaw no responde en :8080"
ok "OpenClaw V13 configurado: @coder @analyst @reasoner @researcher + RAG + web search"

# ─────────────────────────────────────────────────────────────────────────────
#  PASO 10: ROUTER SEMÁNTICO V6 (build V13) — arranca ÚLTIMO
# ─────────────────────────────────────────────────────────────────────────────
step "PASO 10/11 — Router Semántico V6 build V13 (puerto 8000)"
python3 "$ROUTER_SCRIPT" >> "$ROUTER_LOG" 2>&1 &
echo $! > "$ROUTER_PID_FILE"
wait_http "http://localhost:8000/health" 25 "Router V6" \
    || { error "Router no respondió. Revisa: tail -f $ROUTER_LOG"; exit 1; }
ok "Router V6 (build V13) activo (PID: $(cat "$ROUTER_PID_FILE"))"

# ─────────────────────────────────────────────────────────────────────────────
#  PASO 11: WARMUP + INDEXACIÓN INICIAL DEL VAULT
# ─────────────────────────────────────────────────────────────────────────────
step "PASO 11/11 — Warmup y configuración final"

# Warmup del backend por defecto (DeepSeek R1 en VRAM)
info "Warmup Ollama GPU (DeepSeek R1)…"
curl -s --max-time 30 -X POST http://localhost:11434/api/generate \
  -d '{"model":"deepseek-r1:14b","prompt":"Hola","stream":false,"options":{"num_predict":1}}' \
  -o /dev/null && ok "DeepSeek R1 en VRAM (warmup OK)" \
               || warn "Warmup falló (no crítico)"

# Indexación inicial del vault si hay notas y el indexador existe
if [ -f "$INDEXER_SCRIPT" ] && [ -d "$OBSIDIAN_VAULT_DIR" ]; then
    note_count=$(find "$OBSIDIAN_VAULT_DIR" -name "*.md" 2>/dev/null | wc -l)
    if [ "$note_count" -gt 0 ]; then
        info "Indexando $note_count notas Markdown en ChromaDB…"
        python3 "$INDEXER_SCRIPT" && ok "Vault indexado ($note_count notas)" \
                                  || warn "Error en indexación inicial (ejecuta: $0 --reindex)"
    else
        info "Vault vacío — añade notas Markdown en Obsidian y ejecuta: $0 --reindex"
    fi
fi

# Configurar cron para re-indexación automática cada hora
if command -v crontab >/dev/null 2>&1; then
    CRON_CMD="0 * * * * python3 $INDEXER_SCRIPT >> /tmp/indexar_vault.log 2>&1"
    (crontab -l 2>/dev/null | grep -v "indexar_vault"; echo "$CRON_CMD") | crontab - \
        && info "Cron configurado: re-indexación del vault cada hora" \
        || warn "No se pudo configurar el cron"
fi

# ─────────────────────────────────────────────────────────────────────────────
#  RESUMEN FINAL
# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}╔══════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}${BOLD}║          ✔ CLÚSTER OMEN V13 COMPLETAMENTE OPERATIVO             ║${NC}"
echo -e "${GREEN}${BOLD}╚══════════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${CYAN}${BOLD}Interfaces de usuario:${NC}"
echo -e "    📊 OpenClaw UI:       http://localhost:8080"
echo -e "    📝 Obsidian Vault:    http://localhost:3000"
echo -e "    🔍 SearXNG Search:    http://localhost:8888"
echo ""
echo -e "  ${CYAN}${BOLD}API del router:${NC}"
echo -e "    🔀 Router:            http://localhost:8000/v1"
echo -e "    🏥 Health:            http://localhost:8000/health"
echo -e "    📈 Métricas:          http://localhost:8000/metrics"
echo -e "    📋 Modelos:           http://localhost:8000/v1/models"
echo ""
echo -e "  ${CYAN}${BOLD}[V13-A] Modelos de razonamiento Phi-4:${NC}"
echo -e "    🎯 Phi Mayor Precisión: phi-mayor-precision  → phi4-reasoning:plus"
echo -e "    ⚡ Phi Optimizada:      phi-optimizada       → phi4-reasoning:14b-q4_K_M"
echo ""
echo -e "  ${CYAN}${BOLD}[V13-B/C/D] Herramientas de conocimiento:${NC}"
echo -e "    📚 ChromaDB RAG:      http://localhost:8001"
echo -e "    🌐 SearXNG Web:       http://localhost:8888"
echo ""
echo -e "  ${CYAN}${BOLD}Agentes OpenClaw:${NC}"
echo -e "    @coder     → ⚡ Instantáneo (Qwen Coder 7B)"
echo -e "    @analyst   → 🔬 Masivo (Qwen2.5 32B)"
echo -e "    @reasoner  → 🎯 Phi Mayor Precisión (phi4-reasoning:plus)"
echo -e "    @researcher→ 🚀 Ágil + RAG + Web Search"
echo ""
echo -e "  ${CYAN}${BOLD}Comandos útiles:${NC}"
echo -e "    Estado:    $0 --status"
echo -e "    Detener:   $0 --stop"
echo -e "    Re-indexar vault: $0 --reindex"
echo -e "    Logs router: tail -f $ROUTER_LOG"
echo ""
[ -z "$PHI4_CLASIFICADOR" ] && echo -e "  ${YELLOW}💡 Instala el clasificador LLM: ollama pull phi4-mini${NC}" && echo ""
