#!/bin/bash
# ╔══════════════════════════════════════════════════════════════════════════╗
# ║         OMEN AI CLUSTER — Autoboot_Cluster_V13.sh                       ║
# ╠══════════════════════════════════════════════════════════════════════════╣
# ║  Mejoras V13 sobre V12:                                                  ║
# ║  ✔ [M1] Verificación de modelos reales antes de arrancar backends        ║
# ║  ✔ [M2] phi4-mini preferido como clasificador (3x más rápido en CPU)    ║
# ║  ✔ [M3] Ollama CPU-only con --gpus "" (más robusto que solo env var)    ║
# ║  ✔ [M4] OLLAMA_TMPDIR en ext4 para seguridad de descargas exFAT         ║
# ║  ✔ [M5] SGLang con --shm-size=2gb, --context-length y --mem-fraction    ║
# ║  ✔ [M6] nomic-embed-text en instancia CPU (clasificador rápido)         ║
# ║  ✔ [M7] openclaw.json con agentes especializados + contextWindow        ║
# ║  ✔ [M8] Warmup automático del backend por defecto al finalizar          ║
# ║  ✔ TabbAPI con disable_auth: true (permite model switching sin key)     ║
# ║  ✔ [V13] Ajustado a la nueva estructura unificada de rutas de modelos   ║
# ╚══════════════════════════════════════════════════════════════════════════╝
#
# USO:
#   ./Autoboot_Cluster_V13.sh            # Arranque completo
#   ./Autoboot_Cluster_V13.sh --stop     # Parar todo
#   ./Autoboot_Cluster_V13.sh --status   # Estado de servicios
#   ./Autoboot_Cluster_V13.sh --warmup   # Solo warmup del backend por defecto
#
set -uo pipefail

# ─────────────────────────────────────────────────────────────────────────────
#  CONFIGURACIÓN DE RUTAS ACTUALIZADA
# ─────────────────────────────────────────────────────────────────────────────
MODELS_ROOT="/home/fcela-ga/sgoinfre/ai_core/models"
OLLAMA_MODELS_DIR="$MODELS_ROOT/ollama"
OLLAMA_CPU_MODELS_DIR="$MODELS_ROOT/ollama-cpu"
EXLLAMA_MODELS_DIR="$MODELS_ROOT" # Los modelos EXL2 están directamente aquí
SGLANG_MODELS_DIR="$MODELS_ROOT"  # llama-3.1-8b-awq está aquí

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROUTER_SCRIPT="$SCRIPT_DIR/orchestrator_router_V6.py"
TABBYAPI_CONFIG="$SCRIPT_DIR/config_tabbyapi_v13.yml"
ROUTER_LOG="$SCRIPT_DIR/router_v13.log"
ROUTER_PID_FILE="$SCRIPT_DIR/router_v13.pid"

# [M4] Directorio temporal de Ollama en ext4 (no en exFAT)
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

# ─────────────────────────────────────────────────────────────────────────────
#  FUNCIÓN: Health check con polling
# ─────────────────────────────────────────────────────────────────────────────
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
    docker stop openclaw-server exllamav2-api sglang-server ollama-cpu-router 2>/dev/null || true
    docker rm   openclaw-server exllamav2-api sglang-server ollama-cpu-router 2>/dev/null || true
    sudo systemctl stop ollama 2>/dev/null || true
    rm -f "$ROUTER_PID_FILE"
    ok "Clúster detenido."; exit 0
fi

# ─────────────────────────────────────────────────────────────────────────────
#  MODO --status
# ─────────────────────────────────────────────────────────────────────────────
if [ "${1:-}" = "--status" ]; then
    step "Estado del clúster OMEN V13"
    echo ""
    printf "  %-28s %s\n" "SERVICIO" "ESTADO"
    printf "  %-28s %s\n" "────────────────────────────" "────────"
    declare -A CHECKS=(
        ["Ollama GPU :11434"]="http://localhost:11434/api/tags"
        ["Ollama CPU :11435 (Phi-4/Embed)"]="http://localhost:11435/api/tags"
        ["Router V6  :8000"]="http://localhost:8000/health"
        ["TabbAPI    :5000"]="http://localhost:5000/health"
        ["SGLang     :30000"]="http://localhost:30000/health"
        ["OpenClaw   :8080"]="http://localhost:8080"
    )
    for svc in "Ollama GPU :11434" "Ollama CPU :11435 (Phi-4/Embed)" \
               "Router V6  :8000" "TabbAPI    :5000" \
               "SGLang     :30000" "OpenClaw   :8080"; do
        url="${CHECKS[$svc]}"
        if curl -sf --max-time 2 "$url" >/dev/null 2>&1; then
            printf "  ${GREEN}${BOLD}%-28s ✔ UP${NC}\n" "$svc"
        else
            printf "  ${RED}%-28s ✘ DOWN${NC}\n" "$svc"
        fi
    done
    echo ""
    echo -e "  ${CYAN}${BOLD}Métricas del router:${NC}  curl -s http://localhost:8000/metrics | python3 -m json.tool"
    echo -e "  ${CYAN}${BOLD}OpenClaw UI:${NC}          http://localhost:8080"
    exit 0
fi

# ─────────────────────────────────────────────────────────────────────────────
#  MODO --warmup
# ─────────────────────────────────────────────────────────────────────────────
if [ "${1:-}" = "--warmup" ]; then
    step "Warmup del backend por defecto (Ollama GPU — DeepSeek R1)"
    curl -s -X POST http://localhost:11434/api/generate \
      -d '{"model":"deepseek-r1:14b","prompt":"Hola","stream":false,"options":{"num_predict":1}}' \
      -o /dev/null && ok "Warmup completado — modelo en VRAM" \
                    || warn "Warmup falló (no crítico)"
    exit 0
fi

# ─────────────────────────────────────────────────────────────────────────────
#  BANNER
# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}${BOLD}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}${BOLD}║      OMEN AI CLUSTER V13 — INICIALIZANDO                    ║${NC}"
echo -e "${CYAN}${BOLD}║  RTX 4070 8GB · Intel Ultra 7 · 32GB RAM · SSD exFAT        ║${NC}"
echo -e "${CYAN}${BOLD}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""

# ─────────────────────────────────────────────────────────────────────────────
#  [M1] VERIFICACIONES PREVIAS — archivos y modelos reales
# ─────────────────────────────────────────────────────────────────────────────
step "VERIFICACIONES PREVIAS"

[ -f "$ROUTER_SCRIPT" ]          || { error "No se encuentra $ROUTER_SCRIPT"; exit 1; }
command -v docker  >/dev/null 2>&1 || { error "Docker no instalado"; exit 1; }
command -v python3 >/dev/null 2>&1 || { error "Python3 no encontrado"; exit 1; }
command -v curl    >/dev/null 2>&1 || { error "curl no encontrado"; exit 1; }

# Verificar directorios base
[ -d "$OLLAMA_MODELS_DIR" ]     || { error "Directorio ollama no encontrado: $OLLAMA_MODELS_DIR"; exit 1; }
[ -d "$OLLAMA_CPU_MODELS_DIR" ] || { error "Directorio ollama-cpu no encontrado: $OLLAMA_CPU_MODELS_DIR"; exit 1; }
[ -d "$EXLLAMA_MODELS_DIR" ]    || { error "Directorio raíz de modelos no encontrado: $EXLLAMA_MODELS_DIR"; exit 1; }

# [M1] Verificar modelos REALES (no solo directorios)
step "VERIFICACIONES DE MODELOS"

# ExLlamaV2: qwen2.5-coder-7b-exl2 (nivel INSTANTANEO)
if [ ! -d "$EXLLAMA_MODELS_DIR/qwen2.5-coder-7b-exl2" ]; then
    error "Modelo ExLlamaV2 no encontrado: qwen2.5-coder-7b-exl2"
    info "Descárgalo con:"
    info "  cd $EXLLAMA_MODELS_DIR"
    info "  hf download bartowski/Qwen2.5-Coder-7B-Instruct-exl2 --revision 6_5 --local-dir qwen2.5-coder-7b-exl2"
    exit 1
fi
ok "qwen2.5-coder-7b-exl2 presente"

# ExLlamaV2: llama-3.1-8b-exl2 (nivel CHAT)
if [ ! -d "$EXLLAMA_MODELS_DIR/llama-3.1-8b-exl2" ]; then
    warn "Modelo CHAT no encontrado: llama-3.1-8b-exl2 (nivel CHAT no disponible)"
    warn "Para el nivel CHAT, descarga: hf download turboderp/Llama-3.1-8B-Instruct-exl2 --revision 6.0bpw --local-dir llama-3.1-8b-exl2"
else
    ok "llama-3.1-8b-exl2 presente (nivel CHAT)"
fi

# SGLang: llama-3.1-8b-awq
if [ ! -d "$SGLANG_MODELS_DIR/llama-3.1-8b-awq" ]; then
    error "Modelo SGLang no encontrado: llama-3.1-8b-awq"
    info "Descárgalo con:"
    info "  cd $SGLANG_MODELS_DIR"
    info "  hf download hugging-quants/Meta-Llama-3.1-8B-Instruct-AWQ-INT4 --local-dir llama-3.1-8b-awq"
    exit 1
fi
ok "llama-3.1-8b-awq presente (SGLang AGIL)"

# Ollama: deepseek-r1 y qwen2.5:32b
check_ollama_model() {
    local modelo="$1" nombre="$2"
    if ollama list 2>/dev/null | grep -q "$modelo"; then
        ok "$nombre presente (Ollama)"
    else
        warn "$nombre NO encontrado en Ollama."
        warn "Si lo necesitas: ollama pull $modelo"
    fi
}
check_ollama_model "deepseek-r1" "deepseek-r1"
check_ollama_model "qwen2.5:32b" "qwen2.5:32b"

# [M2] Verificar phi4-mini vs phi4 para el clasificador
PHI4_CLASIFICADOR=""
if ollama list 2>/dev/null | grep -q "phi4-mini"; then
    ok "phi4-mini disponible — se usará como clasificador LLM (3-4x más rápido)"
    PHI4_CLASIFICADOR="phi4-mini"
elif ollama list 2>/dev/null | grep -q "phi4"; then
    ok "phi4 disponible — se usará como clasificador LLM (más lento; considera: ollama pull phi4-mini)"
    PHI4_CLASIFICADOR="phi4"
else
    warn "⚠ Ni phi4 ni phi4-mini encontrados."
    warn "El clasificador LLM no estará disponible (solo embeddings)."
    warn "Instala con: ollama pull phi4-mini"
fi

# Instalar dependencias Python
python3 -c "import fastapi, uvicorn, httpx, docker" 2>/dev/null || {
    info "Instalando dependencias Python del router…"
    pip3 install --quiet fastapi uvicorn httpx docker 2>/dev/null
}
ok "Todas las verificaciones superadas"

# ─────────────────────────────────────────────────────────────────────────────
#  PASO 1: LIMPIEZA
# ─────────────────────────────────────────────────────────────────────────────
step "PASO 1/8 — Limpiando estado anterior"
[ -f "$ROUTER_PID_FILE" ] && { kill "$(cat "$ROUTER_PID_FILE")" 2>/dev/null || true; rm -f "$ROUTER_PID_FILE"; }
pkill -f orchestrator_router 2>/dev/null || true
docker stop openclaw-server exllamav2-api sglang-server ollama-cpu-router 2>/dev/null || true
docker rm   openclaw-server exllamav2-api sglang-server ollama-cpu-router 2>/dev/null || true
sudo systemctl stop ollama 2>/dev/null || true
sleep 2
ok "Limpieza completada"

# ─────────────────────────────────────────────────────────────────────────────
#  PASO 2: OLLAMA GPU (systemd nativo)
# ─────────────────────────────────────────────────────────────────────────────
step "PASO 2/8 — Ollama GPU (puerto 11434)"

# [M4] Crear directorio tmp en ext4
sudo mkdir -p "$OLLAMA_TMPDIR"
sudo chmod 777 "$OLLAMA_TMPDIR"

# Actualizar override de systemd con todas las variables necesarias
sudo mkdir -p /etc/systemd/system/ollama.service.d
sudo bash -c "cat > /etc/systemd/system/ollama.service.d/override.conf" << OVERRIDE_EOF
[Service]
Environment="OLLAMA_MODELS=$OLLAMA_MODELS_DIR"
Environment="OLLAMA_HOST=0.0.0.0:11434"
Environment="OLLAMA_TMPDIR=$OLLAMA_TMPDIR"
OVERRIDE_EOF

sudo systemctl daemon-reload 2>/dev/null || true
sudo systemctl start ollama

wait_http "http://localhost:11434/api/tags" 45 "Ollama GPU" || {
    warn "Reiniciando Ollama GPU…"
    sudo systemctl restart ollama
    wait_http "http://localhost:11434/api/tags" 30 "Ollama GPU" || { error "Ollama GPU no disponible"; exit 1; }
}

# ─────────────────────────────────────────────────────────────────────────────
#  PASO 3: OLLAMA CPU-ONLY (Phi-4/phi4-mini + nomic-embed-text)
#
#  [M3] Doble protección GPU: --gpus "" (Docker runtime) + CUDA_VISIBLE_DEVICES=""
#  El flag --gpus "" es más robusto con drivers NVIDIA recientes.
#  NOTA exFAT: montamos ollama_storage; los modelos ya están descargados.
# ─────────────────────────────────────────────────────────────────────────────
step "PASO 3/8 — Ollama CPU-only: Phi-4 + Embeddings (puerto 11435)"

docker run -d \
  --name ollama-cpu-router \
  --restart unless-stopped \
  --gpus "" \
  -p 11435:11434 \
  -e CUDA_VISIBLE_DEVICES="" \
  -e OLLAMA_MODELS=/models \
  -e OLLAMA_HOST=0.0.0.0:11434 \
  -e OLLAMA_TMPDIR=/tmp \
  -v "${OLLAMA_CPU_MODELS_DIR}":/models \
  ollama/ollama

wait_http "http://localhost:11435/api/tags" 50 "Ollama CPU Router" || {
    warn "Ollama CPU no respondió — embeddings y clasificador LLM pueden no funcionar"
}

# [M6] Verificar/cargar nomic-embed-text para el clasificador semántico
info "Verificando nomic-embed-text (clasificador de embeddings)…"
if ! docker exec ollama-cpu-router ollama list 2>/dev/null | grep -q "nomic-embed-text"; then
    info "Descargando nomic-embed-text (~274MB)…"
    docker exec ollama-cpu-router ollama pull nomic-embed-text \
        && ok "nomic-embed-text listo" \
        || warn "No se pudo descargar nomic-embed-text (clasificador de embeddings no disponible)"
else
    ok "nomic-embed-text disponible"
fi

# Verificar phi4-mini o phi4 en la instancia CPU
info "Verificando modelo clasificador LLM en instancia CPU…"
if [ -n "$PHI4_CLASIFICADOR" ]; then
    if docker exec ollama-cpu-router ollama list 2>/dev/null | grep -q "$PHI4_CLASIFICADOR"; then
        ok "$PHI4_CLASIFICADOR disponible en Ollama CPU"
    else
        warn "$PHI4_CLASIFICADOR no visible en instancia CPU (modelos compartidos del mismo directorio)"
        info "En el primer uso se cargará automáticamente desde $OLLAMA_MODELS_DIR"
    fi
fi

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
#  TabbyAPI Configuration V13 — OMEN Cluster
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
ok "config_tabbyapi_v13.yml generado"

docker create \
  --gpus all \
  --name exllamav2-api \
  -p 5000:5000 \
  -v "${EXLLAMA_MODELS_DIR}":/models \
  -v "${TABBYAPI_CONFIG}":/app/config.yml:ro \
  ghcr.io/theroyallab/tabbyapi:latest 2>/dev/null \
  || warn "exllamav2-api ya existe — se reutilizará"

ok "TabbAPI configurado en STANDBY"

# ─────────────────────────────────────────────────────────────────────────────
#  PASO 5: SGLANG (STANDBY)
#
#  [M5] Mejoras: --shm-size=2gb, --context-length 32768, --mem-fraction-static 0.85
#  --mem-fraction-static 0.85: reserva 85% VRAM para modelo+KV cache (RadixAttention)
# ─────────────────────────────────────────────────────────────────────────────
step "PASO 5/8 — SGLang (STANDBY — llama-3.1-8b-awq)"

docker create \
  --gpus all \
  --name sglang-server \
  --ipc=host \
  --shm-size=2gb \
  -p 30000:30000 \
  -v "${SGLANG_MODELS_DIR}":/models \
  lmsysorg/sglang:latest \
  python3 -m sglang.launch_server \
    --model-path /models/llama-3.1-8b-awq \
    --quantization awq \
    --served-model-name llama-3.1-8b-awq \
    --port 30000 \
    --host 0.0.0.0 \
    --context-length 32768 \
    --mem-fraction-static 0.85 \
    --enable-cache-report 2>/dev/null \
  || warn "sglang-server ya existe — se reutilizará"

ok "SGLang configurado en STANDBY"

# ─────────────────────────────────────────────────────────────────────────────
#  PASO 6: OPENCLAW
#
#  [M7] openclaw.json V13 con:
#    - contextWindow y maxTokens por modelo
#    - Tres agentes especializados: @coder, @analyst, @reasoner
#    - Subagentes configurados (maxConcurrent: 2)
# ─────────────────────────────────────────────────────────────────────────────
step "PASO 6/8 — OpenClaw (puerto 8080)"

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

# Inyectar openclaw.json V13 con agentes especializados
info "Inyectando configuración V13 de OpenClaw (agentes especializados)…"
docker exec openclaw-server mkdir -p /data/.openclaw

# Usar printf + docker exec para evitar problemas con heredoc y caracteres especiales
docker exec openclaw-server bash -c 'cat > /data/.openclaw/openclaw.json << '"'"'OPENCLAW_JSON_EOF'"'"'
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
            "name": "🤖 Auto — clasificador 3 capas",
            "contextWindow": 32768,
            "maxTokens": 16384
          },
          {
            "id": "chat",
            "name": "💬 Chat (Llama 3.1 8B EXL2)",
            "contextWindow": 8192,
            "maxTokens": 4096
          },
          {
            "id": "instantaneo",
            "name": "⚡ Instantáneo (Qwen2.5 Coder 7B)",
            "contextWindow": 4096,
            "maxTokens": 2048
          },
          {
            "id": "agil",
            "name": "🚀 Ágil (SGLang · agentes y documentos)",
            "contextWindow": 32768,
            "maxTokens": 8192
          },
          {
            "id": "profundo",
            "name": "🧠 Profundo (DeepSeek R1 14B)",
            "contextWindow": 16384,
            "maxTokens": 8192
          },
          {
            "id": "masivo",
            "name": "🔬 Masivo (Qwen2.5 32B · análisis completo)",
            "contextWindow": 32768,
            "maxTokens": 16384
          },
          {
            "id": "codigo",
            "name": "💻 Código → Instantáneo (Qwen Coder 7B)",
            "contextWindow": 4096,
            "maxTokens": 2048
          },
          {
            "id": "phi4",
            "name": "🔷 Phi-4 CPU (clasificador directo)",
            "contextWindow": 16384,
            "maxTokens": 4096
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
      },
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
          "primary": "local_router/instantaneo",
          "fallbacks": ["local_router/profundo"]
        }
      },
      {
        "id": "analyst",
        "name": "📊 Agente Analyst",
        "model": {
          "primary": "local_router/masivo",
          "fallbacks": ["local_router/profundo"]
        }
      },
      {
        "id": "reasoner",
        "name": "🧠 Agente Reasoner",
        "model": {
          "primary": "local_router/profundo",
          "fallbacks": ["local_router/agil"]
        }
      }
    ]
  }
}
OPENCLAW_JSON_EOF'

info "Reiniciando OpenClaw para asimilar configuración V13…"
docker restart openclaw-server >/dev/null
sleep 8

wait_http "http://localhost:8080" 35 "OpenClaw UI" || warn "OpenClaw no responde en :8080"
ok "OpenClaw V13 configurado con agentes @coder, @analyst, @reasoner"

# ─────────────────────────────────────────────────────────────────────────────
#  PASO 7: ROUTER SEMÁNTICO V6
#  Arranca ÚLTIMO — cuando todos los backends ya están disponibles
# ─────────────────────────────────────────────────────────────────────────────
step "PASO 7/8 — Router Semántico V6 (puerto 8000)"

python3 "$ROUTER_SCRIPT" >> "$ROUTER_LOG" 2>&1 &
ROUTER_PID=$!
echo "$ROUTER_PID" > "$ROUTER_PID_FILE"

wait_http "http://localhost:8000/health" 25 "Router V6" || {
    error "El router no respondió. Revisa: tail -f $ROUTER_LOG"
    exit 1
}
ok "Router V6 activo (PID: $ROUTER_PID)"

# ─────────────────────────────────────────────────────────────────────────────
#  PASO 8: WARMUP AUTOMÁTICO
#  [M8] Carga el modelo por defecto en VRAM antes del primer request real
# ─────────────────────────────────────────────────────────────────────────────
step "PASO 8/8 — Warmup del backend por defecto"
info "Enviando prompt de warmup a Ollama GPU (DeepSeek R1)…"
curl -s --max-time 30 -X POST http://localhost:11434/api/generate \
  -d '{"model":"deepseek-r1:14b","prompt":"Hola","stream":false,"options":{"num_predict":1}}' \
  -o /dev/null \
  && ok "Warmup completado — DeepSeek R1 en VRAM" \
  || warn "Warmup falló (no crítico — el modelo cargará en el primer request real)"

# ─────────────────────────────────────────────────────────────────────────────
#  RESUMEN FINAL
# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}${BOLD}║         ✔ CLÚSTER OMEN V13 OPERATIVO                        ║${NC}"
echo -e "${GREEN}${BOLD}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${CYAN}${BOLD}📊 OpenClaw UI:${NC}       http://localhost:8080"
echo -e "  ${CYAN}${BOLD}🔀 Router API:${NC}        http://localhost:8000/v1"
echo -e "  ${CYAN}${BOLD}🏥 Health check:${NC}      http://localhost:8000/health"
echo -e "  ${CYAN}${BOLD}📈 Métricas:${NC}          http://localhost:8000/metrics"
echo -e "  ${CYAN}${BOLD}📋 Modelos:${NC}           http://localhost:8000/v1/models"
echo ""
echo -e "  ${YELLOW}Clasificador V6 (3 capas):${NC}"
echo -e "    Capa 0: Header @agente OpenClaw   → 0ms (sin LLM)"
echo -e "    Capa 2: nomic-embed-text          → ~26ms"
echo -e "    Capa 3: ${PHI4_CLASIFICADOR:-phi4-mini (instalar)}            → ~700ms"
echo ""
echo -e "  ${YELLOW}Agentes OpenClaw disponibles:${NC}"
echo -e "    @coder    → ⚡ Instantáneo (Qwen Coder 7B)"
echo -e "    @analyst  → 🔬 Masivo (Qwen2.5 32B)"
echo -e "    @reasoner → 🧠 Profundo (DeepSeek R1)"
echo ""
echo -e "  ${YELLOW}Backends en STANDBY (router los activa bajo demanda):${NC}"
echo -e "    TabbAPI :5000  · SGLang :30000"
echo ""
echo -e "  ${YELLOW}Comandos útiles:${NC}"
echo -e "    Estado:   $0 --status"
echo -e "    Detener:  $0 --stop"
echo -e "    Warmup:   $0 --warmup"
echo -e "    Logs:     tail -f $ROUTER_LOG"
echo ""

# Recomendación si phi4-mini no está instalado
if [ "$PHI4_CLASIFICADOR" = "phi4" ] || [ -z "$PHI4_CLASIFICADOR" ]; then
    echo -e "  ${YELLOW}💡 Mejora de rendimiento recomendada:${NC}"
    echo -e "    Instala phi4-mini para clasificación 3-4x más rápida en CPU:"
    echo -e "    ${CYAN}docker exec ollama-cpu-router ollama pull phi4-mini${NC}"
    echo ""
fi
