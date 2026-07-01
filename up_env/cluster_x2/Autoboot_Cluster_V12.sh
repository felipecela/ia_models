#!/usr/bin/env bash
# ============================================================================
# Autoboot_Cluster_V12.sh — Arranque declarativo del clúster OMEN (stack moderno)
# Stack:  OpenClaw -> LiteLLM -> llama-swap -> (llama.cpp / TabbyAPI)
# Sustituye al V11 (router Python + conmutación manual de VRAM por docker stop/start).
#
# Hardware: HP OMEN · Intel Ultra 7 255H · RTX 4070 Laptop 8 GB · 32 GB RAM
# SSD compartido exFAT (Windows/Linux): GGUF/EXL se leen bien; Ollama NO va en exFAT.
#
# Uso:   ./Autoboot_Cluster_V12.sh up      # levanta todo
#        ./Autoboot_Cluster_V12.sh down    # para todo
#        ./Autoboot_Cluster_V12.sh status  # estado + health checks
# ============================================================================
set -Eeuo pipefail

# ---------------------------------------------------------------------------
# 0) Variables
# ---------------------------------------------------------------------------
AI_CORE="/home/fcela-ga/sgoinfre/ai_core"     # raíz en el SSD exFAT
CONF_DIR="${AI_CORE}/conf"                      # YAMLs de litellm y llama-swap
OPENCLAW_DATA="${AI_CORE}/openclaw_storage"     # bind mount real (NO symlink)

LITELLM_PORT=4000
LLAMASWAP_PORT=9292
OPENCLAW_PORT=8080

# Credenciales OpenClaw (¡cámbialas!)
OPENCLAW_USER="admin"
OPENCLAW_PASS="cambia-esta-clave"
LITELLM_MASTER_KEY="sk-omen-local"

log()  { printf '\033[1;36m[OMEN]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[WARN]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[ERR ]\033[0m %s\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# 1) Guardas de entorno (fallar pronto y claro)
# ---------------------------------------------------------------------------
preflight() {
  command -v docker >/dev/null || die "Docker no está instalado."
  command -v nvidia-smi >/dev/null || warn "nvidia-smi no encontrado: ¿drivers NVIDIA + nvidia-container-toolkit?"
  [[ -d "$AI_CORE" ]] || die "No existe AI_CORE: $AI_CORE"
  [[ -f "${CONF_DIR}/litellm_config.yaml" ]]   || die "Falta ${CONF_DIR}/litellm_config.yaml"
  [[ -f "${CONF_DIR}/llama-swap_config.yaml" ]] || die "Falta ${CONF_DIR}/llama-swap_config.yaml"

  # --- Guarda exFAT: avisa si AI_CORE está en exFAT (afecta a Ollama) -------
  local fstype
  fstype="$(stat -f -c %T "$AI_CORE" 2>/dev/null || echo desconocido)"
  if [[ "$fstype" == *exfat* || "$fstype" == *msdos* ]]; then
    warn "AI_CORE está en exFAT ($fstype): GGUF/EXL OK; NO uses el store de Ollama aquí."
    warn "  -> Usa una imagen ext4 en loopback para Ollama o abandónalo (ver análisis §5)."
  fi

  mkdir -p "$OPENCLAW_DATA"
}

# ---------------------------------------------------------------------------
# 2) Espera activa de health checks (sin sleeps a ciegas)
# ---------------------------------------------------------------------------
wait_http() {  # $1=url  $2=nombre  $3=timeout_s
  local url="$1" name="$2" t="${3:-90}" i=0
  log "Esperando a $name ($url) ..."
  until curl -fsS "$url" >/dev/null 2>&1; do
    ((i++)); (( i > t )) && die "$name no respondió en ${t}s."
    sleep 1
  done
  log "$name OK."
}

# ---------------------------------------------------------------------------
# 3) Levantar servicios (orden: llama-swap -> litellm -> openclaw)
# ---------------------------------------------------------------------------
up() {
  preflight

  # 3a) llama-swap (front door de inferencia, carga bajo demanda + TTL)
  log "Arrancando llama-swap..."
  docker rm -f omen-llamaswap >/dev/null 2>&1 || true
  docker run -d --name omen-llamaswap --restart unless-stopped \
    --gpus all \
    -p ${LLAMASWAP_PORT}:8080 \
    -v "${AI_CORE}:/models:ro" \
    -v "${CONF_DIR}/llama-swap_config.yaml:/app/config.yaml:ro" \
    ghcr.io/mostlygeek/llama-swap:cuda
  wait_http "http://127.0.0.1:${LLAMASWAP_PORT}/v1/models" "llama-swap" 60

  # 3b) LiteLLM (alias, fallbacks, routing) — instalado vía pip o Docker
  log "Arrancando LiteLLM..."
  docker rm -f omen-litellm >/dev/null 2>&1 || true
  docker run -d --name omen-litellm --restart unless-stopped \
    --add-host=host.docker.internal:host-gateway \
    -p ${LITELLM_PORT}:4000 \
    -v "${CONF_DIR}/litellm_config.yaml:/app/config.yaml:ro" \
    -e LITELLM_MASTER_KEY="${LITELLM_MASTER_KEY}" \
    ghcr.io/berriai/litellm:main-latest \
    --config /app/config.yaml --port 4000
  wait_http "http://127.0.0.1:${LITELLM_PORT}/health/liveliness" "LiteLLM" 60

  # 3c) OpenClaw (gateway/UI). CORREGIDO frente al V11:
  #     - AUTH_USERNAME/AUTH_PASSWORD (auth básica de la UI)
  #     - OPENCLAW_ALLOWED_ORIGINS (OBLIGATORIO para la UI de control / CORS)
  #     - /data por bind mount real (exFAT no admite symlinks)
  log "Arrancando OpenClaw..."
  docker rm -f omen-openclaw >/dev/null 2>&1 || true
  docker run -d --name omen-openclaw --restart unless-stopped \
    --add-host=host.docker.internal:host-gateway \
    -p ${OPENCLAW_PORT}:8080 \
    -v "${OPENCLAW_DATA}:/data" \
    -e AUTH_USERNAME="${OPENCLAW_USER}" \
    -e AUTH_PASSWORD="${OPENCLAW_PASS}" \
    -e OPENCLAW_ALLOWED_ORIGINS="http://localhost:${OPENCLAW_PORT},http://127.0.0.1:${OPENCLAW_PORT}" \
    coollabsio/openclaw:latest
  wait_http "http://127.0.0.1:${OPENCLAW_PORT}/" "OpenClaw" 90

  log "Clúster OMEN arriba:"
  log "  OpenClaw  -> http://localhost:${OPENCLAW_PORT}  (user: ${OPENCLAW_USER})"
  log "  LiteLLM   -> http://localhost:${LITELLM_PORT}/ui"
  log "  llama-swap-> http://localhost:${LLAMASWAP_PORT}/v1/models"
}

# ---------------------------------------------------------------------------
# 4) Parar / estado
# ---------------------------------------------------------------------------
down() {
  log "Parando clúster OMEN..."
  docker rm -f omen-openclaw omen-litellm omen-llamaswap >/dev/null 2>&1 || true
  log "Hecho."
}

status() {
  docker ps --filter "name=omen-" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" || true
  echo "---"
  curl -fsS "http://127.0.0.1:${LLAMASWAP_PORT}/v1/models" 2>/dev/null && echo "  <- llama-swap OK" || warn "llama-swap no responde"
  curl -fsS "http://127.0.0.1:${LITELLM_PORT}/health/liveliness" 2>/dev/null && echo "  <- LiteLLM OK" || warn "LiteLLM no responde"
  curl -fsS "http://127.0.0.1:${OPENCLAW_PORT}/" >/dev/null 2>&1 && echo "OpenClaw OK" || warn "OpenClaw no responde"
  echo "--- VRAM ---"
  nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader 2>/dev/null || true
}

case "${1:-up}" in
  up)     up ;;
  down)   down ;;
  status) status ;;
  *) die "Uso: $0 {up|down|status}" ;;
esac
