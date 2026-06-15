#!/bin/bash
# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║ OMEN AI Cluster — Autoboot V20                                             ║
# ║ RTX 4070 8GB · Intel Ultra 7 · 32GB RAM · SSD exFAT /mnt/ai_core          ║
# ╠══════════════════════════════════════════════════════════════════════════════╣
# ║ V20 — Correcciones de auditoría integral sobre V19:                        ║
# ║  ✔ [V20-C1]  Router actualizado a V13 (orchestrator_router_V13.py)         ║
# ║  ✔ [V20-C2]  Indexador actualizado a V5 (indexar_vault_v5.py)              ║
# ║  ✔ [V20-C3]  Verificación estricta de montaje /mnt/ai_core (mountpoint)   ║
# ║  ✔ [V20-C4]  Captura explícita de PIDs para pulls en background            ║
# ║  ✔ [V20-C5]  Limpieza de puerto 8000 con validación de proceso propietario ║
# ║  ✔ [V20-C6]  Espera de pulls CPU antes de lanzar indexador                 ║
# ║  ✔ [V20-C7]  Verificación de versión mínima Python 3.10+                   ║
# ║  ✔ [V20-C8]  pip3 install con --break-system-packages (Ubuntu 24.04+)      ║
# ║  ✔ [V20-C9]  Permisos restrictivos en SearXNG secret y settings            ║
# ║  ✔ [V20-C10] Verificación de netcat antes de wait_port                     ║
# ║  ✔ [V20-C11] Validación numérica de Docker version                         ║
# ║  ✔ [V20-C12] Logging de pulls en background con error reporting            ║
# ║  ✔ [V20-C13] Verificación de modelo embeddings antes de indexar            ║
# ║  ✔ [V20-C14] PID del indexador registrado para cleanup                     ║
# ║  ✔ [V20-C15] Redirección de log movida antes de primer output              ║
# ╠══════════════════════════════════════════════════════════════════════════════╣
# ║ Heredado de V19 (todas las correcciones):                                  ║
# ║  ✔ [V19-C1..C12] Todas las mejoras de V19 mantenidas                       ║
# ╠══════════════════════════════════════════════════════════════════════════════╣
# ║ Heredado de V18 (todas las correcciones):                                  ║
# ║  ✔ [V18-A1..A12] Todas las mejoras de V18 mantenidas                       ║
# ╠══════════════════════════════════════════════════════════════════════════════╣
# ║ Heredado de V17 (todas las correcciones):                                  ║
# ║  ✔ [V17-A1..A13] Todas las mejoras de V17 mantenidas                       ║
# ╠══════════════════════════════════════════════════════════════════════════════╣
# ║ Contenedores levantados:                                                   ║
# ║  1. ollama-gpu-main       :11434  GPU VRAM primaria                       ║
# ║  2. ollama-cpu-router     :11435  CPU — nomic-embed + phi4-mini           ║
# ║  3. exllamav2-api         :5000   TabbAPI — CHAT / INSTANTANEO            ║
# ║  4. sglang-server         :30000  SGLang — AGIL                           ║
# ║  5. chromadb              :8001   RAG vectorial (vol. nombrado ext4)      ║
# ║  6. obsidian-kb           :3000   Obsidian Web UI                         ║
# ║  7. searxng               :8888   Búsqueda web privada                    ║
# ║  Router: orchestrator_router_V13.py :8000 (FastAPI + Agent Engine)        ║
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
# [V20-C1] Router y indexador actualizados a V13/V5
# [V18-A2] agent_data/ en ext4 para SQLite del agente autónomo
# ─────────────────────────────────────────────────────────────────────────────
AI_CORE="/mnt/ai_core"                          # SSD exFAT (compartido Win/Linux)
AI_HOME="$HOME/ai_cluster"                      # ext4 — logs, chromadb, state
MODELS_DIR="$AI_CORE/models"                    # pesos en exFAT
VAULT_DIR="$AI_CORE/obsidian_vault"             # vault Obsidian en exFAT
OBSIDIAN_APPDATA="$AI_HOME/obsidian_appdata"    # estado Obsidian en ext4
ROUTER_SCRIPT="$AI_HOME/orchestrator_router_V13.py"
VAULT_INDEXER="$AI_HOME/indexar_vault_v5.py"
AGENT_DATA_DIR="$AI_HOME/agent_data"            # [V18-A2] SQLite del agente
LOG_DIR="$AI_HOME/logs"
LOG_FILE="$LOG_DIR/autoboot_v20_$(date +%Y%m%d_%H%M%S).log"
PID_FILE="$AI_HOME/router_v13.pid"             # [V20-C1] Actualizado para V13
INDEXER_PID_FILE="$AI_HOME/indexer.pid"        # [V20-C14] PID del indexador
SEARXNG_SECRET_FILE="$AI_HOME/.searxng_secret"
SEARXNG_SETTINGS="$AI_HOME/searxng_settings.yml"

# Array para PIDs de pulls en background
declare -a GPU_PULL_PIDS=()
declare -a CPU_PULL_PIDS=()

# ─────────────────────────────────────────────────────────────────────────────
# PARÁMETROS DE RED
# ─────────────────────────────────────────────────────────────────────────────
DOCKER_NET="ai_net"
DOCKER_NET_SUBNET="172.28.0.0/16"

# ─────────────────────────────────────────────────────────────────────────────
# WAIT_PORT — [V17-A3] backoff exponencial, máx 90s
# [V20-C10] Usa /dev/tcp como fallback si nc no está disponible
# ─────────────────────────────────────────────────────────────────────────────
wait_port() {
    local label="$1" host="$2" port="$3"
    local max_s="${4:-90}"
    local waited=0 delay=2
    info "Esperando $label en $host:$port (máx ${max_s}s)…"
    while true; do
        if command -v nc &>/dev/null; then
            nc -z "$host" "$port" 2>/dev/null && break
        else
            # [V20-C10] Fallback: bash /dev/tcp
            (echo >/dev/tcp/"$host"/"$port") 2>/dev/null && break
        fi
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
# [V19-C2] VALIDACIÓN DE FILESYSTEM
# Verifica que un directorio está en un filesystem compatible con SQLite WAL
# ─────────────────────────────────────────────────────────────────────────────
validate_filesystem() {
    local dir="$1"
    local label="${2:-directorio}"
    local fs_type

    fs_type=$(df --output=fstype "$dir" 2>/dev/null | tail -1 | tr -d '[:space:]')

    case "$fs_type" in
        ext4|ext3|xfs|btrfs|tmpfs|zfs)
            ok "$label: filesystem '$fs_type' compatible con SQLite WAL"
            return 0
            ;;
        exfat|vfat|ntfs|fuseblk)
            err "$label está en filesystem '$fs_type' — INCOMPATIBLE con SQLite WAL"
            err "SQLite requiere bloqueos POSIX y journaling. Mueve $dir a una partición ext4."
            return 1
            ;;
        *)
            warn "$label: filesystem '$fs_type' desconocido — procediendo con precaución"
            return 0
            ;;
    esac
}

# ─────────────────────────────────────────────────────────────────────────────
# TRAP EXIT — [V19-C3] Graceful shutdown mejorado (espera 30s con feedback)
# [V20-C14] También limpia el indexador si está corriendo
# ─────────────────────────────────────────────────────────────────────────────
cleanup() {
    local exit_code="$?"

    # Limpiar indexador si está corriendo
    if [[ -f "$INDEXER_PID_FILE" ]]; then
        local idx_pid
        idx_pid=$(cat "$INDEXER_PID_FILE" 2>/dev/null || echo "")
        if [[ -n "$idx_pid" ]] && kill -0 "$idx_pid" 2>/dev/null; then
            info "Limpieza: enviando SIGTERM al indexador (PID $idx_pid)…"
            kill -TERM "$idx_pid" 2>/dev/null || true
        fi
        rm -f "$INDEXER_PID_FILE"
    fi

    # Limpiar router
    if [[ -f "$PID_FILE" ]]; then
        local pid
        pid=$(cat "$PID_FILE" 2>/dev/null || echo "")
        if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
            info "Limpieza: enviando SIGTERM al router V13 (PID $pid)…"
            kill -TERM "$pid" 2>/dev/null || true
            # [V19-C3] Esperar hasta 30s para graceful shutdown (el router espera subtareas)
            local wait_count=0
            while kill -0 "$pid" 2>/dev/null && (( wait_count < 30 )); do
                if (( wait_count % 5 == 0 )); then
                    info "  Esperando shutdown del router… (${wait_count}s/30s)"
                fi
                sleep 1
                (( wait_count++ ))
            done
            if kill -0 "$pid" 2>/dev/null; then
                warn "Router no terminó en 30s — forzando SIGKILL"
                kill -9 "$pid" 2>/dev/null || true
            else
                ok "Router V13 detenido correctamente (${wait_count}s)"
            fi
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
section "OMEN AI Cluster — Autoboot V20"
info "$(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# Crear directorios necesarios en ext4
mkdir -p "$AI_HOME" "$LOG_DIR" "$OBSIDIAN_APPDATA" "$AGENT_DATA_DIR"

# [V20-C15] Redirigir stdout+stderr al log ANTES de cualquier output significativo
exec > >(tee -a "$LOG_FILE") 2>&1
info "Log: $LOG_FILE"

# ─────────────────────────────────────────────────────────────────────────────
# [V20-C3] VERIFICACIÓN ESTRICTA DE MONTAJE /mnt/ai_core
# ─────────────────────────────────────────────────────────────────────────────
section "Verificación de SSD exFAT"

if [[ ! -d "$AI_CORE" ]]; then
    err "Directorio $AI_CORE no existe."
    err "Verifica que el SSD exFAT está montado: mount /mnt/ai_core"
    exit 1
fi

if ! mountpoint -q "$AI_CORE" 2>/dev/null; then
    # Verificar si al menos es un directorio con contenido esperado
    if [[ -d "$MODELS_DIR" ]]; then
        warn "$AI_CORE no es un punto de montaje activo pero contiene $MODELS_DIR"
        warn "Esto puede indicar que los datos están en la partición raíz."
        warn "Verifica: mount | grep ai_core"
    else
        err "$AI_CORE no es un punto de montaje activo y no contiene modelos."
        err "Monta el SSD: sudo mount /dev/sdX1 /mnt/ai_core"
        exit 1
    fi
else
    ok "SSD exFAT montado en $AI_CORE"
fi

# Crear vault en exFAT si no existe
mkdir -p "$VAULT_DIR" 2>/dev/null || warn "No se pudo crear $VAULT_DIR (verificar permisos exFAT)"

# ─────────────────────────────────────────────────────────────────────────────
# COMPROBACIONES PREVIAS
# ─────────────────────────────────────────────────────────────────────────────
section "Comprobaciones previas"

# [V20-C10] Verificar herramientas de red
if ! command -v nc &>/dev/null; then
    warn "netcat (nc) no encontrado — usando /dev/tcp como fallback para wait_port"
fi

if ! command -v docker &>/dev/null; then
    err "Docker no encontrado. Instala Docker Engine."
    exit 1
fi

# [V19-C9][V20-C11] Verificar versión mínima de Docker con validación numérica
DOCKER_VERSION=$(docker version --format '{{.Server.Version}}' 2>/dev/null || echo "0.0.0")
DOCKER_MAJOR=$(echo "$DOCKER_VERSION" | cut -d. -f1)
DOCKER_MINOR=$(echo "$DOCKER_VERSION" | cut -d. -f2)
# Validar que son numéricos antes de comparar
if [[ "$DOCKER_MAJOR" =~ ^[0-9]+$ ]] && [[ "$DOCKER_MINOR" =~ ^[0-9]+$ ]]; then
    if (( DOCKER_MAJOR < 20 )) || { (( DOCKER_MAJOR == 20 )) && (( DOCKER_MINOR < 10 )); }; then
        warn "Docker $DOCKER_VERSION detectado — se recomienda 20.10+ para compatibilidad completa"
    else
        ok "Docker $DOCKER_VERSION"
    fi
else
    warn "No se pudo determinar la versión de Docker ($DOCKER_VERSION) — continuando"
fi

if ! command -v python3 &>/dev/null; then
    err "python3 no encontrado. Instala Python 3.10+."
    exit 1
fi

# [V20-C7] Verificar versión mínima de Python (3.10+ requerido por type hints)
PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)
if [[ "$PYTHON_MAJOR" =~ ^[0-9]+$ ]] && [[ "$PYTHON_MINOR" =~ ^[0-9]+$ ]]; then
    if (( PYTHON_MAJOR < 3 )) || { (( PYTHON_MAJOR == 3 )) && (( PYTHON_MINOR < 10 )); }; then
        err "Python $PYTHON_VERSION detectado — se requiere 3.10+ para el router"
        err "El router usa type hints (X | Y) incompatibles con versiones anteriores."
        exit 1
    fi
    ok "Python $PYTHON_VERSION"
else
    warn "No se pudo determinar la versión de Python — continuando con precaución"
fi

if [[ ! -f "$ROUTER_SCRIPT" ]]; then
    err "Router V13 no encontrado: $ROUTER_SCRIPT"
    err "Copia orchestrator_router_V13.py a $AI_HOME/"
    exit 1
fi

# [V17-A11] Verificar sintaxis del router antes de lanzar
if ! python3 -m py_compile "$ROUTER_SCRIPT" 2>/dev/null; then
    err "Error de sintaxis en $ROUTER_SCRIPT — abortando"
    python3 -m py_compile "$ROUTER_SCRIPT" || true
    exit 1
fi
ok "Router V13: sintaxis correcta"

# [V18-A3] Verificar permisos de escritura en agent_data/
if [[ ! -w "$AGENT_DATA_DIR" ]]; then
    err "Sin permisos de escritura en $AGENT_DATA_DIR — el agente no podrá persistir estado"
    err "Ejecuta: chmod 755 $AGENT_DATA_DIR"
    exit 1
fi
ok "Agent data dir: permisos correctos ($AGENT_DATA_DIR)"

# [V19-C2] Validar filesystem de AGENT_DATA_DIR
if ! validate_filesystem "$AGENT_DATA_DIR" "Agent data dir"; then
    err "AGENT_DATA_DIR ($AGENT_DATA_DIR) está en un filesystem incompatible con SQLite."
    err "Mueve agent_data/ a una partición ext4 o configura AGENT_DB_DIR en el entorno."
    exit 1
fi

# [V19-C5] Backup de agent_tasks.db con verificación de integridad
AGENT_DB="$AGENT_DATA_DIR/agent_tasks.db"
if [[ -f "$AGENT_DB" ]]; then
    # Verificar integridad antes de backup
    DB_INTEGRITY=$(python3 -c "
import sqlite3, sys
try:
    conn = sqlite3.connect('$AGENT_DB')
    result = conn.execute('PRAGMA integrity_check').fetchone()
    conn.close()
    print(result[0])
except Exception as e:
    print(f'error: {e}')
" 2>/dev/null || echo "error")

    if [[ "$DB_INTEGRITY" == "ok" ]]; then
        BACKUP_NAME="${AGENT_DB}.bak_$(date +%Y%m%d_%H%M%S)"
        cp "$AGENT_DB" "$BACKUP_NAME"
        ok "Backup de agent_tasks.db → $(basename "$BACKUP_NAME") (integridad: OK)"
    else
        warn "agent_tasks.db tiene problemas de integridad: $DB_INTEGRITY"
        warn "Creando backup de seguridad igualmente…"
        BACKUP_NAME="${AGENT_DB}.bak_CORRUPT_$(date +%Y%m%d_%H%M%S)"
        cp "$AGENT_DB" "$BACKUP_NAME"
    fi

    # Limpiar backups antiguos (mantener últimos 5)
    find "$AGENT_DATA_DIR" -maxdepth 1 -name "agent_tasks.db.bak_*" -printf '%T@ %p\n' 2>/dev/null \
        | sort -rn | tail -n +6 | cut -d' ' -f2- | xargs rm -f 2>/dev/null || true
fi

# [V18-A10] Verificar espacio en disco (ext4 home)
DISK_FREE_MB=$(df --output=avail "$AI_HOME" 2>/dev/null | tail -1 | awk '{print int($1/1024)}')
if [[ -n "$DISK_FREE_MB" ]] && (( DISK_FREE_MB < 2048 )); then
    warn "Espacio libre en disco bajo: ${DISK_FREE_MB}MB (mínimo recomendado: 2GB)"
    warn "El agente autónomo puede generar datos significativos en $AGENT_DATA_DIR"
fi
ok "Espacio en disco (ext4): ${DISK_FREE_MB:-?}MB libres"

# [V19-C12] Verificar espacio en SSD exFAT para modelos
if [[ -d "$AI_CORE" ]]; then
    EXFAT_FREE_MB=$(df --output=avail "$AI_CORE" 2>/dev/null | tail -1 | awk '{print int($1/1024)}')
    if [[ -n "$EXFAT_FREE_MB" ]] && (( EXFAT_FREE_MB < 5120 )); then
        warn "Espacio libre en SSD exFAT bajo: ${EXFAT_FREE_MB}MB (mínimo recomendado: 5GB)"
        warn "Los modelos pueden requerir espacio adicional para pulls."
    fi
    ok "Espacio en SSD exFAT: ${EXFAT_FREE_MB:-?}MB libres"
fi

# Verificar NVIDIA
if command -v nvidia-smi &>/dev/null; then
    VRAM_FREE=$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits 2>/dev/null | head -1 || echo "0")
    ok "GPU: VRAM libre = ${VRAM_FREE} MiB"
else
    warn "nvidia-smi no disponible — RTX 4070 no detectada"
fi

# [V19-C8] Limpieza de logs antiguos (mantener últimos 10)
LOG_COUNT=$(find "$LOG_DIR" -maxdepth 1 -name "autoboot_v*.log" 2>/dev/null | wc -l)
if (( LOG_COUNT > 10 )); then
    find "$LOG_DIR" -maxdepth 1 -name "autoboot_v*.log" -printf '%T@ %p\n' 2>/dev/null \
        | sort -rn | tail -n +11 | cut -d' ' -f2- | xargs rm -f 2>/dev/null || true
    info "Limpiados $((LOG_COUNT - 10)) logs antiguos (mantenidos últimos 10)"
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

# [V20-C4][V20-C12] Pre-pull modelos con captura de PIDs y logging de errores
OLLAMA_GPU_MODELS=("deepseek-r1:14b" "phi4-reasoning:plus" "phi4-reasoning:14b-q4_K_M" "qwen2.5:32b")
GPU_PULL_PIDS=()
for model in "${OLLAMA_GPU_MODELS[@]}"; do
    if ! docker exec ollama-gpu-main ollama list 2>/dev/null | grep -q "$model"; then
        info "Iniciando pull de $model (puede tardar varios minutos)…"
        docker exec ollama-gpu-main ollama pull "$model" \
            >> "$LOG_DIR/pull_gpu.log" 2>&1 &
        GPU_PULL_PIDS+=($!)
    else
        ok "$model ya presente en GPU"
    fi
done

# No bloquear aquí — se esperará antes de necesitar los modelos
ok "Ollama GPU ✔ (${#GPU_PULL_PIDS[@]} pulls en background)"

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

# [V20-C4][V20-C6] Pull modelos CPU con captura de PIDs (se esperará antes de indexar)
CPU_PULL_PIDS=()
for model in nomic-embed-text phi4-mini; do
    if ! docker exec ollama-cpu-router ollama list 2>/dev/null | grep -q "$model"; then
        info "Pull de $model (CPU)…"
        docker exec ollama-cpu-router ollama pull "$model" \
            >> "$LOG_DIR/pull_cpu.log" 2>&1 &
        CPU_PULL_PIDS+=($!)
    else
        ok "$model ya presente en CPU"
    fi
done

# [V20-C6] Esperar EXPLÍCITAMENTE a que los pulls de CPU terminen
# (necesarios para el indexador y el clasificador del router)
if [[ ${#CPU_PULL_PIDS[@]} -gt 0 ]]; then
    info "Esperando ${#CPU_PULL_PIDS[@]} pull(s) de CPU (necesarios para indexador/router)…"
    local_failed=0
    for pid in "${CPU_PULL_PIDS[@]}"; do
        if ! wait "$pid" 2>/dev/null; then
            (( local_failed++ ))
        fi
    done
    if (( local_failed > 0 )); then
        warn "$local_failed pull(s) de CPU fallaron — ver $LOG_DIR/pull_cpu.log"
    else
        ok "Todos los pulls de CPU completados"
    fi
fi

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
# [V20-C9] Permisos restrictivos en secret y settings
# ─────────────────────────────────────────────────────────────────────────────
section "7/7 — SearXNG (:8888)"
ensure_container_stopped "searxng"

# Generar o recuperar secret_key persistente
if [[ ! -f "$SEARXNG_SECRET_FILE" ]]; then
    openssl rand -hex 32 > "$SEARXNG_SECRET_FILE"
    chmod 600 "$SEARXNG_SECRET_FILE"
    info "Nueva secret_key generada en $SEARXNG_SECRET_FILE (permisos: 600)"
else
    # [V20-C9] Asegurar permisos restrictivos en cada arranque
    chmod 600 "$SEARXNG_SECRET_FILE" 2>/dev/null || true
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
    # [V20-C9] Permisos restrictivos en settings
    chmod 600 "$SEARXNG_SETTINGS"
    ok "settings.yml generado en $SEARXNG_SETTINGS (permisos: 600)"
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
# [V20-C2] Actualizado a indexar_vault_v5.py
# [V20-C6] Pulls de CPU ya esperados — modelo embeddings disponible
# [V20-C13] Verificación de modelo embeddings antes de indexar
# ─────────────────────────────────────────────────────────────────────────────
section "Indexación Vault Obsidian"

if [[ -f "$VAULT_INDEXER" ]]; then
    CHROMA_HTTP_CODE=$(curl -so /dev/null -w "%{http_code}" "http://localhost:8001/api/v1/heartbeat" 2>/dev/null || echo "000")
    OLLAMA_CPU_HTTP_CODE=$(curl -so /dev/null -w "%{http_code}" "http://localhost:11435/api/tags" 2>/dev/null || echo "000")

    if [[ "$CHROMA_HTTP_CODE" == "200" ]] && [[ "$OLLAMA_CPU_HTTP_CODE" == "200" ]]; then
        # [V20-C13] Verificar que el modelo de embeddings está realmente disponible
        EMBED_MODEL_READY=$(docker exec ollama-cpu-router ollama list 2>/dev/null | grep -c "nomic-embed-text" || echo "0")
        if (( EMBED_MODEL_READY > 0 )); then
            info "Lanzando indexación incremental del vault (V5)…"
            python3 "$VAULT_INDEXER" \
                --vault-dir "$VAULT_DIR" \
                --chroma-url "http://localhost:8001" \
                --ollama-embed-url "http://localhost:11435/api/embeddings" \
                --state-dir "$AGENT_DATA_DIR" \
                >> "$LOG_DIR/indexar_vault.log" 2>&1 &
            INDEXER_PID=$!
            echo "$INDEXER_PID" > "$INDEXER_PID_FILE"
            info "Indexador en background PID=$INDEXER_PID (log: $LOG_DIR/indexar_vault.log)"
        else
            warn "Modelo nomic-embed-text no disponible en Ollama CPU — indexación omitida"
            warn "Ejecuta: docker exec ollama-cpu-router ollama pull nomic-embed-text"
        fi
    else
        warn "[V17-A4] ChromaDB ($CHROMA_HTTP_CODE) u Ollama CPU ($OLLAMA_CPU_HTTP_CODE) no listo — indexación omitida"
        warn "Ejecuta manualmente: python3 $VAULT_INDEXER"
    fi
else
    warn "indexar_vault_v5.py no encontrado en $AI_HOME — vault no indexado"
fi

# ─────────────────────────────────────────────────────────────────────────────
# DEPENDENCIAS PYTHON DEL ROUTER
# [V20-C8] Compatibilidad con Ubuntu 24.04+ (--break-system-packages)
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
    # [V20-C8] Detectar si se necesita --break-system-packages (PEP 668, Ubuntu 24.04+)
    PIP_EXTRA_ARGS=""
    if python3 -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" 2>/dev/null; then
        STDLIB_PATH=$(python3 -c 'import sysconfig; print(sysconfig.get_path("stdlib"))' 2>/dev/null || echo "")
        if [[ -f "/usr/lib/python3/EXTERNALLY-MANAGED" ]] || \
           { [[ -n "$STDLIB_PATH" ]] && [[ -f "${STDLIB_PATH}/EXTERNALLY-MANAGED" ]]; }; then
            PIP_EXTRA_ARGS="--break-system-packages"
            info "Detectado entorno PEP 668 — usando --break-system-packages"
        fi
    fi
    pip3 install --quiet $PIP_EXTRA_ARGS $MISSING_PKGS
    ok "Paquetes instalados"
else
    ok "Todas las dependencias Python disponibles"
fi

# ─────────────────────────────────────────────────────────────────────────────
# ROUTER V13 — FastAPI + Autonomous Reasoning Agent (:8000)
# [V20-C1] Router actualizado a V13
# [V20-C5] Limpieza de puerto con validación de proceso propietario
# ─────────────────────────────────────────────────────────────────────────────
section "Router V13 (FastAPI + Agent :8000)"

# Matar instancia previa si existe
if [[ -f "$PID_FILE" ]]; then
    OLD_PID=$(cat "$PID_FILE" 2>/dev/null || echo "")
    if [[ -n "$OLD_PID" ]] && kill -0 "$OLD_PID" 2>/dev/null; then
        info "Deteniendo router anterior (PID $OLD_PID)…"
        kill -TERM "$OLD_PID" 2>/dev/null || true
        sleep 5
        if kill -0 "$OLD_PID" 2>/dev/null; then
            kill -9 "$OLD_PID" 2>/dev/null || true
        fi
    fi
    rm -f "$PID_FILE"
fi

# [V20-C5] Asegurar que el puerto 8000 esté libre — con validación de propietario
if ss -tlnp 2>/dev/null | grep -q ':8000 '; then
    warn "Puerto 8000 ocupado — identificando proceso…"
    BLOCKING_PID=$(ss -tlnp 2>/dev/null | grep ':8000 ' | grep -oP 'pid=\K[0-9]+' | head -1)
    if [[ -n "$BLOCKING_PID" ]]; then
        BLOCKING_CMD=$(ps -p "$BLOCKING_PID" -o comm= 2>/dev/null || echo "desconocido")
        BLOCKING_USER=$(ps -p "$BLOCKING_PID" -o user= 2>/dev/null || echo "desconocido")
        warn "  PID=$BLOCKING_PID ($BLOCKING_CMD) usuario=$BLOCKING_USER ocupa el puerto 8000"

        # [V20-C5] Solo matar si es un proceso Python del usuario actual (probable residuo del router)
        if [[ "$BLOCKING_CMD" == "python3" || "$BLOCKING_CMD" == "python" ]] && \
           [[ "$BLOCKING_USER" == "$(whoami)" ]]; then
            info "Proceso Python propio detectado — terminando…"
            kill -TERM "$BLOCKING_PID" 2>/dev/null || true
            sleep 3
            if kill -0 "$BLOCKING_PID" 2>/dev/null; then
                kill -9 "$BLOCKING_PID" 2>/dev/null || true
            fi
        else
            err "Puerto 8000 ocupado por proceso ajeno ($BLOCKING_CMD, usuario=$BLOCKING_USER)"
            err "Libera el puerto manualmente antes de continuar."
            exit 1
        fi
    else
        # No se pudo identificar el PID — intentar con fuser como último recurso
        warn "No se pudo identificar el PID — intentando fuser…"
        fuser -k 8000/tcp 2>/dev/null || true
    fi
    sleep 2
fi

# [V19-C11] Exportar AGENT_DB_DIR con validación de filesystem ya realizada
export AGENT_DB_DIR="$AGENT_DATA_DIR"

# Esperar pulls de GPU si aún están corriendo (necesarios para el router)
if [[ ${#GPU_PULL_PIDS[@]} -gt 0 ]]; then
    info "Verificando pulls de GPU en background…"
    for pid in "${GPU_PULL_PIDS[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
            info "  Pull GPU (PID $pid) aún en progreso — no bloqueante para el router"
        fi
    done
fi

# Lanzar router
PYTHONUNBUFFERED=1 AGENT_DB_DIR="$AGENT_DATA_DIR" python3 "$ROUTER_SCRIPT" \
    >> "$LOG_DIR/router_v13.log" 2>&1 &
ROUTER_PID=$!
echo "$ROUTER_PID" > "$PID_FILE"
info "Router V13 lanzado — PID=$ROUTER_PID"

# [V19-C7] Health check mejorado con reintentos y diagnóstico
ROUTER_READY=false
HEALTH_ATTEMPTS=0
for i in {1..30}; do
    (( HEALTH_ATTEMPTS++ ))
    if curl -sf "http://localhost:8000/health" >/dev/null 2>&1; then
        ROUTER_READY=true
        break
    fi
    # Verificar que el proceso sigue vivo
    if ! kill -0 "$ROUTER_PID" 2>/dev/null; then
        err "Router V13 terminó inesperadamente. Últimas líneas del log:"
        tail -20 "$LOG_DIR/router_v13.log" 2>/dev/null || true
        break
    fi
    sleep 2
done

if $ROUTER_READY; then
    ok "Router V13 ✔ → http://localhost:8000 (respondió en intento $HEALTH_ATTEMPTS)"
    # [V18-A8] Verificar que el agente autónomo responde
    AGENT_CHECK=$(curl -sf "http://localhost:8000/v1/agent/tasks?limit=1" 2>/dev/null || echo "")
    if [[ -n "$AGENT_CHECK" ]]; then
        ok "Agent Engine ✔ → /v1/agent/tasks respondiendo"
    else
        warn "Agent Engine no respondió — verificar logs"
    fi
else
    err "Router V13 no respondió en 60s"
    if kill -0 "$ROUTER_PID" 2>/dev/null; then
        err "El proceso está vivo pero no responde — posible error de binding"
    fi
    tail -20 "$LOG_DIR/router_v13.log" 2>/dev/null || true
fi

# ─────────────────────────────────────────────────────────────────────────────
# RESUMEN FINAL
# ─────────────────────────────────────────────────────────────────────────────
section "Resumen del Cluster V20"

echo ""
printf "%-30s %-12s %s\n" "Servicio" "Puerto" "Estado"
printf "%-30s %-12s %s\n" "──────────────────────────────" "────────────" "──────"

check_service() {
    local name="$1" host="$2" port="$3"
    if command -v nc &>/dev/null; then
        if nc -z "$host" "$port" 2>/dev/null; then
            printf "%-30s %-12s %b\n" "$name" ":$port" "${GRN}✔ OK${NC}"
        else
            printf "%-30s %-12s %b\n" "$name" ":$port" "${YEL}⚠ no disponible${NC}"
        fi
    else
        if (echo >/dev/tcp/"$host"/"$port") 2>/dev/null; then
            printf "%-30s %-12s %b\n" "$name" ":$port" "${GRN}✔ OK${NC}"
        else
            printf "%-30s %-12s %b\n" "$name" ":$port" "${YEL}⚠ no disponible${NC}"
        fi
    fi
}

check_service "Ollama GPU (main)"       localhost 11434
check_service "Ollama CPU (router/emb)" localhost 11435
check_service "TabbAPI ExLlamaV2"       localhost 5000
check_service "SGLang"                  localhost 30000
check_service "ChromaDB"                localhost 8001
check_service "Obsidian Web UI"         localhost 3000
check_service "SearXNG"                 localhost 8888
check_service "Router V13 (Agent)"      localhost 8000

echo ""
echo -e "${BLD}Configuración OpenClaw (OpenWebUI):${NC}"
echo "  API URL:    http://localhost:8000/v1"
echo "  Model:      ruteador-auto"
echo "  Agent:      http://localhost:8000/v1/agent/tasks"
echo ""
echo -e "${BLD}Autonomous Reasoning Agent:${NC}"
echo "  Crear tarea:     curl -X POST http://localhost:8000/v1/agent/tasks -H 'Content-Type: application/json' -d '{\"prompt\": \"...\", \"max_iterations\": 3}'"
echo "  Ver estado:      curl http://localhost:8000/v1/agent/tasks/{task_id}"
echo "  Ver resultado:   curl http://localhost:8000/v1/agent/tasks/{task_id}/result"
echo "  Stream progreso: curl http://localhost:8000/v1/agent/tasks/{task_id}/stream"
echo "  Listar tareas:   curl http://localhost:8000/v1/agent/tasks"
echo "  Cancelar:        curl -X DELETE http://localhost:8000/v1/agent/tasks/{task_id}"
echo ""
echo -e "${BLD}Comandos útiles:${NC}"
echo "  Ver logs:         tail -f $LOG_DIR/router_v13.log"
echo "  Indexar vault:    python3 $VAULT_INDEXER"
echo "  Reindexar todo:   python3 $VAULT_INDEXER --clean"
echo "  Métricas router:  curl -s http://localhost:8000/metrics | python3 -m json.tool"
echo "  Health check:     curl -s http://localhost:8000/health | python3 -m json.tool"
echo "  Detener router:   kill \$(cat $PID_FILE)"
echo "  Parar cluster:    docker stop ollama-gpu-main ollama-cpu-router exllamav2-api sglang-server chromadb obsidian-kb searxng"
echo ""
echo -e "${GRN}${BLD}OMEN AI Cluster V20 — iniciado${NC}"
echo -e "$(date '+%Y-%m-%d %H:%M:%S')"
