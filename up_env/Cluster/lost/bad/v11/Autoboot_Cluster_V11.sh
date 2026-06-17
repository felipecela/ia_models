#!/bin/bash
# ╔══════════════════════════════════════════════════════════════════════════╗
# ║         OMEN AI CLUSTER — Autoboot_Cluster_V11_Actualizado.sh           ║
# ║         Hardware: RTX 4070 8GB · Intel Ultra 7 · 32GB RAM               ║
# ╠══════════════════════════════════════════════════════════════════════════╣
# ║  Mejoras sobre V10 + Sincronización con V36:                             ║
# ║  ✔ Rutas de modelos unificadas hacia $AI_CORE/models (Sinc. V36)         ║
# ║  ✔ Aislamiento de registros Ollama GPU/CPU para evitar colisiones        ║
# ║  ✔ TabbAPI usa imagen oficial ghcr.io/theroyallab/tabbyapi:latest        ║
# ║  ✔ Phi-4 en Ollama CPU-only (puerto 11435) — sin contención de VRAM      ║
# ║  ✔ OpenClaw config en formato correcto openclaw.json                     ║
# ╚══════════════════════════════════════════════════════════════════════════╝
#
# USO:
#   ./Autoboot_Cluster_V11_Actualizado.sh           # Arranque completo
#   ./Autoboot_Cluster_V11_Actualizado.sh --stop    # Parar todo el clúster
#   ./Autoboot_Cluster_V11_Actualizado.sh --status  # Estado de todos los servicios
#
set -uo pipefail

# ─────────────────────────────────────────────────────────────────────────────
#  CONFIGURACIÓN DE RUTAS (Actualizado a estructura V36)
# ─────────────────────────────────────────────────────────────────────────────
AI_CORE="${AI_CORE:-/home/fcela-ga/sgoinfre/ai_core}"
MODELS_DIR="$AI_CORE/models"
OLLAMA_GPU_MODELS_DIR="$MODELS_DIR/ollama"
OLLAMA_CPU_MODELS_DIR="$MODELS_DIR/ollama-cpu"
EXLLAMA_MODELS_DIR="$MODELS_DIR"
SGLANG_MODELS_DIR="$MODELS_DIR"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROUTER_SCRIPT="$SCRIPT_DIR/orchestrator_router_V5.py"
TABBYAPI_CONFIG="$SCRIPT_DIR/config_tabbyapi.yml"
ROUTER_LOG="$SCRIPT_DIR/router_v11.log"
ROUTER_PID_FILE="$SCRIPT_DIR/router.pid"

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

# ─────────────────────────────────────────────────────────────────────────────
#  FUNCIÓN: Health check con polling
# ─────────────────────────────────────────────────────────────────────────────
wait_http() {
    local url="$1"
    local timeout="${2:-60}"
    local label="${3:-servicio}"
    local elapsed=0

    info "Esperando que '$label' responda en $url (max ${timeout}s)…"
    while ! curl -sf --max-time 2 "$url" >/dev/null 2>&1; do
        sleep 3
        elapsed=$((elapsed + 3))
        if [ $elapsed -ge $timeout ]; then
            warn "Timeout (${timeout}s) esperando '$label'"
            return 1
        fi
        printf "."
    done
    echo ""
    ok "$label listo (${elapsed}s)"
    return 0
}

# ─────────────────────────────────────────────────────────────────────────────
#  MODO --stop
# ─────────────────────────────────────────────────────────────────────────────
if [ "${1:-}" = "--stop" ]; then
    step "Deteniendo clúster OMEN AI…"
    [ -f "$ROUTER_PID_FILE" ] && kill "$(cat "$ROUTER_PID_FILE")" 2>/dev/null || true
    docker stop openclaw-server exllamav2-api sglang-server ollama-cpu-router 2>/dev/null || true
    docker rm   openclaw-server exllamav2-api sglang-server ollama-cpu-router 2>/dev/null || true
    sudo systemctl stop ollama 2>/dev/null || true
    rm -f "$ROUTER_PID_FILE"
    ok "Clúster detenido."
    exit 0
fi

# ─────────────────────────────────────────────────────────────────────────────
#  MODO --status
# ─────────────────────────────────────────────────────────────────────────────
if [ "${1:-}" = "--status" ]; then
    step "Estado del clúster OMEN AI V11"
    echo ""
    printf "  %-22s %s\n" "SERVICIO" "ESTADO"
    printf "  %-22s %s\n" "──────────────────────" "────────"
    for svc in "Ollama GPU:11434/api/tags" "Ollama CPU:11435/api/tags" \
               "Router V5:8000/health" "TabbAPI:5000/health" \
               "SGLang:30000/health" "OpenClaw:8080"; do
        name="${svc%%:*}"; url="${svc#*:}"
        if curl -sf --max-time 2 "http://localhost/$url" >/dev/null 2>&1; then
            printf "  ${GREEN}${BOLD}%-22s ✔ UP${NC}\n" "$name"
        else
            printf "  ${RED}%-22s ✘ DOWN${NC}\n" "$name"
        fi
    done
    echo ""
    if docker ps --format "{{.Names}}" 2>/dev/null | grep -q "openclaw"; then
        echo -e "  ${CYAN}OpenClaw UI:${NC} http://localhost:8080"
    fi
    exit 0
fi

# ─────────────────────────────────────────────────────────────────────────────
#  BANNER DE ARRANQUE
# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}${BOLD}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}${BOLD}║         OMEN AI CLUSTER V11 (Rutas V36) — INICIALIZANDO     ║${NC}"
echo -e "${CYAN}${BOLD}║  RTX 4070 8GB · Intel Ultra 7 · 32GB RAM · SSD exFAT        ║${NC}"
echo -e "${CYAN}${BOLD}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""

# ─────────────────────────────────────────────────────────────────────────────
#  VERIFICACIONES PREVIAS
# ─────────────────────────────────────────────────────────────────────────────
step "VERIFICACIONES PREVIAS"

[ -f "$ROUTER_SCRIPT" ] || { error "No se encuentra $ROUTER_SCRIPT"; exit 1; }
[ -d "$MODELS_DIR" ] || { error "No se encuentra el directorio raíz de modelos: $MODELS_DIR"; exit 1; }

command -v docker >/dev/null 2>&1 || { error "Docker no instalado"; exit 1; }
command -v python3 >/dev/null 2>&1 || { error "Python3 no encontrado"; exit 1; }

# Instalar dependencias Python si faltan
python3 -c "import fastapi, uvicorn, httpx, docker" 2>/dev/null || {
    info "Instalando dependencias Python del router…"
    pip3 install --quiet fastapi uvicorn httpx docker 2>/dev/null
    ok "Dependencias instaladas"
}

ok "Verificaciones OK"

# ─────────────────────────────────────────────────────────────────────────────
#  PASO 1: LIMPIEZA DE ESTADO ANTERIOR
# ─────────────────────────────────────────────────────────────────────────────
step "PASO 1/7 — Limpiando estado anterior"

[ -f "$ROUTER_PID_FILE" ] && {
    kill "$(cat "$ROUTER_PID_FILE")" 2>/dev/null || true
    rm -f "$ROUTER_PID_FILE"
}
pkill -f orchestrator_router 2>/dev/null || true

docker stop openclaw-server exllamav2-api sglang-server ollama-cpu-router 2>/dev/null || true
docker rm   openclaw-server exllamav2-api sglang-server ollama-cpu-router 2>/dev/null || true
sudo systemctl stop ollama 2>/dev/null || true

sleep 2
ok "Limpieza completada"

# ─────────────────────────────────────────────────────────────────────────────
#  PASO 2: OLLAMA GPU (servicio nativo systemd)
# ─────────────────────────────────────────────────────────────────────────────
step "PASO 2/7 — Ollama GPU (puerto 11434)"

mkdir -p "$OLLAMA_GPU_MODELS_DIR" 2>/dev/null || true

# Asegurarse de que el override de systemd usa el directorio correcto de GPU
sudo bash -c "cat > /etc/systemd/system/ollama.service.d/override.conf" << OVERRIDE_EOF 2>/dev/null || true
[Service]
Environment="OLLAMA_MODELS=$OLLAMA_GPU_MODELS_DIR"
Environment="OLLAMA_HOST=0.0.0.0:11434"
OVERRIDE_EOF

sudo systemctl daemon-reload 2>/dev/null || true
sudo systemctl start ollama

wait_http "http://localhost:11434/api/tags" 40 "Ollama GPU" || {
    warn "Ollama GPU no respondió. Intentando reinicio…"
    sudo systemctl restart ollama
    wait_http "http://localhost:11434/api/tags" 30 "Ollama GPU" || {
        error "Ollama GPU no disponible tras reinicio"
        exit 1
    }
}

# ─────────────────────────────────────────────────────────────────────────────
#  PASO 3: OLLAMA CPU-ONLY (Phi-4 clasificador, puerto 11435)
# ─────────────────────────────────────────────────────────────────────────────
step "PASO 3/7 — Ollama CPU-only para Phi-4 (puerto 11435)"

mkdir -p "$OLLAMA_CPU_MODELS_DIR" 2>/dev/null || true

docker run -d \
  --name ollama-cpu-router \
  --restart unless-stopped \
  -p 11435:11434 \
  -e CUDA_VISIBLE_DEVICES="" \
  -e OLLAMA_MODELS=/models \
  -e OLLAMA_HOST=0.0.0.0:11434 \
  -v "${OLLAMA_CPU_MODELS_DIR}:/models" \
  ollama/ollama

wait_http "http://localhost:11435/api/tags" 45 "Ollama CPU Router" || {
    warn "Ollama CPU no respondió — el clasificador Phi-4 puede ser lento en el primer uso"
}

# Confirmar que phi4 es visible en la instancia CPU
info "Verificando phi4 en instancia CPU…"
phi4_check=$(curl -sf http://localhost:11435/api/tags 2>/dev/null \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print('OK' if any('phi4' in m.get('name','') for m in d.get('models',[])) else 'MISSING')" 2>/dev/null || echo "UNKNOWN")

if [ "$phi4_check" = "OK" ]; then
    ok "phi4 disponible en Ollama CPU (puerto 11435)"
else
    warn "phi4 no detectado en instancia CPU. Puede necesitar warm-up en el primer uso."
    info "Si falla, ejecuta manualmente: docker exec ollama-cpu-router ollama pull phi4"
fi

# ─────────────────────────────────────────────────────────────────────────────
#  PASO 4: TABBYAPI / EXLLAMAV2 (STANDBY al arranque)
# ─────────────────────────────────────────────────────────────────────────────
step "PASO 4/7 — TabbAPI / ExLlamaV2 (configurar en STANDBY)"

# Crear config.yml si no existe
if [ ! -f "$TABBYAPI_CONFIG" ]; then
    cat > "$TABBYAPI_CONFIG" << 'TABBY_CONF'
# ─────────────────────────────────────────────────────────────
#  TabbyAPI Configuration — OMEN Cluster V11
# ─────────────────────────────────────────────────────────────
network:
  host: 0.0.0.0
  port: 5000

model:
  model_name: qwen2.5-coder-7b-exl2
  max_seq_len: 4096
  cache_mode: Q4

logging:
  log_prompt: false
  log_generation_params: false
TABBY_CONF
    ok "config_tabbyapi.yml creado en $TABBYAPI_CONFIG"
fi

docker create \
  --gpus all \
  --name exllamav2-api \
  -p 5000:5000 \
  -v "${EXLLAMA_MODELS_DIR}:/models:ro" \
  -v "${TABBYAPI_CONFIG}":/app/config.yml:ro \
  ghcr.io/theroyallab/tabbyapi:latest 2>/dev/null || {
    warn "Contenedor exllamav2-api ya existe (se reutilizará)"
}

ok "TabbAPI configurado en STANDBY (el router lo activa en nivel INSTANTANEO)"

# ─────────────────────────────────────────────────────────────────────────────
#  PASO 5: SGLANG (STANDBY al arranque)
# ─────────────────────────────────────────────────────────────────────────────
step "PASO 5/7 — SGLang (configurar en STANDBY)"

docker create \
  --gpus all \
  --name sglang-server \
  --ipc=host \
  -p 30000:30000 \
  -v "${SGLANG_MODELS_DIR}:/models:ro" \
  lmsysorg/sglang:latest \
  python3 -m sglang.launch_server \
    --model-path /models/llama-3.1-8b-awq \
    --quantization awq \
    --served-model-name llama-3.1-8b-awq \
    --port 30000 \
    --host 0.0.0.0 \
    --enable-cache-report 2>/dev/null || {
    warn "Contenedor sglang-server ya existe (se reutilizará)"
}

ok "SGLang configurado en STANDBY (el router lo activa en nivel AGIL)"

# ─────────────────────────────────────────────────────────────────────────────
#  PASO 6: OPENCLAW
# ─────────────────────────────────────────────────────────────────────────────
step "PASO 6/7 — OpenClaw (puerto 8080)"

docker volume create openclaw_data_v11 >/dev/null 2>&1 || true

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
  -v openclaw_data_v11:/data \
  coollabsio/openclaw:latest

info "Esperando inicialización de OpenClaw (25s)…"
sleep 25

# Inyectar configuración openclaw.json (formato correcto)
info "Inyectando configuración de proveedores locales en openclaw.json…"

docker exec openclaw-server mkdir -p /data/.openclaw

docker exec openclaw-server bash -c 'cat > /data/.openclaw/openclaw.json' << 'OPENCLAW_JSON'
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
          {
            "id": "ruteador-auto",
            "name": "🤖 Auto — Phi-4 elige el nivel"
          },
          {
            "id": "instantaneo",
            "name": "⚡ Instantáneo (ExLlamaV2 · más rápido)"
          },
          {
            "id": "agil",
            "name": "🚀 Ágil (SGLang · agentes y documentos)"
          },
          {
            "id": "profundo",
            "name": "🧠 Profundo (DeepSeek R1 14B · razonamiento)"
          },
          {
            "id": "masivo",
            "name": "🔬 Masivo (Qwen2.5 32B · análisis completo)"
          },
          {
            "id": "codigo",
            "name": "💻 Código (DeepSeek Coder V2)"
          },
          {
            "id": "phi4",
            "name": "🔷 Phi-4 CPU (router directo)"
          }
        ]
      }
    }
  },
  "agents": {
    "defaults": {
      "model": {
        "primary": "local_router/ruteador-auto",
        "fallbacks": ["local_router/agil", "local_router/profundo"]
      }
    }
  }
}
OPENCLAW_JSON

info "Reiniciando OpenClaw para asimilar configuración…"
docker restart openclaw-server >/dev/null
sleep 8

wait_http "http://localhost:8080" 30 "OpenClaw UI" || warn "OpenClaw no responde en 8080 (continúa en 18789)"
ok "OpenClaw configurado"

# ─────────────────────────────────────────────────────────────────────────────
#  PASO 7: ROUTER SEMÁNTICO V5
# ─────────────────────────────────────────────────────────────────────────────
step "PASO 7/7 — Router Semántico V5 (puerto 8000)"

python3 "$ROUTER_SCRIPT" >> "$ROUTER_LOG" 2>&1 &
ROUTER_PID=$!
echo "$ROUTER_PID" > "$ROUTER_PID_FILE"

wait_http "http://localhost:8000/health" 20 "Router V5" || {
    error "El router no respondió. Revisa $ROUTER_LOG"
    exit 1
}

ok "Router V5 activo (PID: $ROUTER_PID)"

# ─────────────────────────────────────────────────────────────────────────────
#  RESUMEN FINAL
# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}${BOLD}║          ✔ CLÚSTER OMEN V11 OPERATIVO                       ║${NC}"
echo -e "${GREEN}${BOLD}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${CYAN}${BOLD}📊 OpenClaw UI:${NC}      http://localhost:8080"
echo -e "  ${CYAN}${BOLD}🔀 Router API:${NC}       http://localhost:8000/v1"
echo -e "  ${CYAN}${BOLD}🏥 Health check:${NC}     http://localhost:8000/health"
echo -e "  ${CYAN}${BOLD}📋 Modelos:${NC}          http://localhost:8000/v1/models"
echo ""
echo -e "  ${YELLOW}Backends en STANDBY (activan bajo demanda del router):${NC}"
echo -e "    ⚡  ExLlamaV2/TabbAPI  →  http://localhost:5000"
echo -e "    🚀  SGLang             →  http://localhost:30000"
echo ""
echo -e "  ${YELLOW}Backends activos ahora:${NC}"
echo -e "    🔷  Ollama GPU         →  http://localhost:11434"
echo -e "    🔲  Ollama CPU (Phi-4) →  http://localhost:11435"
echo ""
echo -e "  ${YELLOW}📝 Logs del router:${NC}  $ROUTER_LOG"
echo -e "  ${YELLOW}⏹  Para detener:${NC}     $0 --stop"
echo -e "  ${YELLOW}📈 Para estado:${NC}      $0 --status"
echo ""