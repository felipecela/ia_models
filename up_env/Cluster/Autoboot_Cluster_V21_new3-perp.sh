#!/bin/bash
# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║ OMEN AI Cluster — Autoboot V21                                             ║
# ║ RTX 4070 8GB · Intel Ultra 7 · 32GB RAM · SSD exFAT /mnt/ai_core          ║
# ╠══════════════════════════════════════════════════════════════════════════════╣
# ║ V21 — Correcciones de auditoría integral sobre V20:                        ║
# ║  ✔ [V21-B1]  Router actualizado a V14 (orchestrator_router_V14.py)         ║
# ║  ✔ [V21-B2]  Indexador actualizado a V6 (indexar_vault_v6.py)              ║
# ║  ✔ [V21-B3]  Timeout configurable para SGLang (H-05) — default 240s       ║
# ║  ✔ [V21-B4]  Verificación de puertos antes de arrancar servicios (H-08)   ║
# ║  ✔ [V21-B5]  Check de espacio en disco antes de arrancar (H-11)           ║
# ║  ✔ [V21-B6]  Docker restart policy ya en V20 (H-13) — verificado          ║
# ║  ✔ [V21-B7]  Distinguir ESRCH vs EPERM en cleanup PIDs (H-16)            ║
# ║  ✔ [V21-B8]  Rotación de logs del Autoboot (H-19)                         ║
# ║  ✔ [V21-B9]  Verificación de modelo SGLang en ruta (H-26)                 ║
# ║  ✔ [V21-B10] Configuración separada en sección delimitada (H-30)          ║
# ║  ✔ [V21-B11] Verificación de integridad de scripts (H-36)                 ║
# ║  ✔ [V21-B12] Watchdog post-arranque opcional (H-40)                        ║
# ║  ✔ [V21-B13] numpy añadido a dependencias Python                           ║
# ║  ✔ [V21-B14] Soporte para omen_router_modules/ (paquete modular)          ║
# ╠══════════════════════════════════════════════════════════════════════════════╣
# ║ Heredado de V20 (todas las correcciones V20-C1..C15):                      ║
# ║  ✔ [V20-C1..C15] Todas las mejoras de V20 mantenidas                       ║
# ╠══════════════════════════════════════════════════════════════════════════════╣
# ║ Contenedores levantados:                                                   ║
# ║  1. ollama-gpu-main       :11434  GPU VRAM primaria                       ║
# ║  2. ollama-cpu-router     :11435  CPU — nomic-embed + phi4-mini           ║
# ║  3. exllamav2-api         :5000   TabbAPI — CHAT / INSTANTANEO            ║
# ║  4. sglang-server         :30000  SGLang — AGIL                           ║
# ║  5. chromadb              :8001   RAG vectorial (vol. nombrado ext4)      ║
# ║  6. obsidian-kb           :3000   Obsidian Web UI                         ║
# ║  7. searxng               :8888   Búsqueda web privada                    ║
# ║  Router: orchestrator_router_V14.py :8000 (FastAPI + Agent Engine)        ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

set -euo pipefail

# ═══════════════════════════════════════════════════════════════════════════════
# [V21-B10] CONFIGURACIÓN — Sección separada y documentada
# ═══════════════════════════════════════════════════════════════════════════════

# ─── Rutas principales ────────────────────────────────────────────────────────
AI_CORE="${AI_CORE:-/home/fcela-ga/sgoinfre/ai_core}"   # SSD exFAT (compartido Win/Linux)
AI_HOME="$HOME/ai_cluster"                              # ext4 — logs, chromadb, state
MODELS_DIR="$AI_CORE/models"                            # pesos en exFAT
VAULT_DIR="$AI_CORE/obsidian_vault"                     # vault Obsidian en exFAT
OBSIDIAN_APPDATA="$AI_HOME/obsidian_appdata"            # estado Obsidian en ext4

# ─── Scripts (V21) ───────────────────────────────────────────────────────────
ROUTER_SCRIPT="$AI_HOME/orchestrator_router_V14.py"
ROUTER_MODULES_DIR="$AI_HOME/omen_router_modules"       # [V21-B14] Paquete modular
VAULT_INDEXER="$AI_HOME/indexar_vault_v6.py"

# ─── Directorios de estado ───────────────────────────────────────────────────
AGENT_DATA_DIR="$AI_HOME/agent_data"                    # SQLite del agente (ext4)
LOG_DIR="$AI_HOME/logs"
LOG_FILE="$LOG_DIR/autoboot_v21_$(date +%Y%m%d_%H%M%S).log"
PID_FILE="$AI_HOME/router_v14.pid"
INDEXER_PID_FILE="$AI_HOME/indexer.pid"
SEARXNG_SECRET_FILE="$AI_HOME/.searxng_secret"
SEARXNG_SETTINGS="$AI_HOME/searxng_settings.yml"

# ─── Red Docker ──────────────────────────────────────────────────────────────
DOCKER_NET="ai_net"
DOCKER_NET_SUBNET="172.28.0.0/16"

# ─── Puertos ─────────────────────────────────────────────────────────────────
PORT_OLLAMA_GPU=11434
PORT_OLLAMA_CPU=11435
PORT_TABBYAPI=5000
PORT_SGLANG=30000
PORT_CHROMADB=8001
PORT_OBSIDIAN=3000
PORT_SEARXNG=8888
PORT_ROUTER=8000

# ─── Timeouts (segundos) ─────────────────────────────────────────────────────
TIMEOUT_OLLAMA=90
TIMEOUT_TABBYAPI=120
TIMEOUT_SGLANG=240                                      # [V21-B3] Aumentado de 120 a 240 para primera carga
TIMEOUT_CHROMADB=60
TIMEOUT_OBSIDIAN=60
TIMEOUT_SEARXNG=60
TIMEOUT_ROUTER_HEALTH=60

# ─── Espacio mínimo (MB) ─────────────────────────────────────────────────────
MIN_DISK_EXT4_MB=2048                                   # [V21-B5] 2GB mínimo en ext4
MIN_DISK_EXFAT_MB=5120                                  # 5GB mínimo en exFAT para pulls

# ─── Modelos ─────────────────────────────────────────────────────────────────
OLLAMA_GPU_MODELS=("deepseek-r1:14b" "phi4-reasoning:plus" "phi4-reasoning:14b-q4_K_M" "qwen2.5:32b")
OLLAMA_CPU_MODELS=("nomic-embed-text" "phi4-mini")

# ─── Watchdog ────────────────────────────────────────────────────────────────
WATCHDOG_ENABLED="${OMEN_WATCHDOG:-false}"              # [V21-B12] Activar con OMEN_WATCHDOG=true
WATCHDOG_INTERVAL=120                                   # Segundos entre checks

# ─── Arrays para PIDs ────────────────────────────────────────────────────────
declare -a GPU_PULL_PIDS=()
declare -a CPU_PULL_PIDS=()

# ─── Logs: rotación ─────────────────────────────────────────────────────────
MAX_LOG_FILES=10                                        # [V21-B8] Máximo de logs a mantener
MAX_LOG_SIZE_MB=100                                     # Tamaño máximo por log antes de truncar

# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS Y FUNCIONES UTILITARIAS
# ═══════════════════════════════════════════════════════════════════════════════

# ─── Colores ─────────────────────────────────────────────────────────────────
RED='\033[0;31m'; YEL='\033[0;33m'; GRN='\033[0;32m'; CYN='\033[0;36m'; NC='\033[0m'
BLD='\033[1m'

info()    { echo -e "${CYN}[INFO]${NC}  $*"; }
ok()      { echo -e "${GRN}[OK]${NC}    $*"; }
warn()    { echo -e "${YEL}[WARN]${NC}  $*"; }
err()     { echo -e "${RED}[ERROR]${NC} $*" >&2; }
section() { echo -e "\n${BLD}${CYN}══════════════════════════════════════════════${NC}"; \
            echo -e "${BLD}${CYN}  $*${NC}"; \
            echo -e "${BLD}${CYN}══════════════════════════════════════════════${NC}"; }

# ─── wait_port — backoff exponencial ─────────────────────────────────────────
wait_port() {
    local label="$1" host="$2" port="$3"
    local max_s="${4:-90}"
    local waited=0 delay=2
    info "Esperando $label en $host:$port (máx ${max_s}s)…"
    while true; do
        if command -v nc &>/dev/null; then
            nc -z "$host" "$port" 2>/dev/null && break
        else
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

# ─── Obtener HTTP Status de forma segura ─────────────────────────────────────
get_http_status() {
    local url="$1"
    local code
    # curl SIN forzar IPv4, SIN PROXY, max 3 segundos.
    code=$(curl --noproxy "*" -s -m 3 -o /dev/null -w "%{http_code}" "$url" 2>/dev/null || echo "000")
    echo "${code: -3}"
}

# ─── [V21-B4] Verificar si un puerto está libre ─────────────────────────────
check_port_free() {
    local port="$1" label="${2:-servicio}"
    if ss -tlnp 2>/dev/null | grep -q ":${port} "; then
        local blocking_pid blocking_cmd
        blocking_pid=$(ss -tlnp 2>/dev/null | grep ":${port} " | grep -oP 'pid=\K[0-9]+' | head -1)
        blocking_cmd=$(ps -p "${blocking_pid:-0}" -o comm= 2>/dev/null || echo "desconocido")
        warn "Puerto $port ocupado por PID=$blocking_pid ($blocking_cmd) — necesario para $label"
        return 1
    fi
    return 0
}

# ─── Contenedor seguro — Idempotente ────────────────────────────────────────
ensure_container_stopped() {
    local name="$1"
    if docker ps -a --format '{{.Names}}' | grep -qx "$name"; then
        info "Contenedor '$name' ya existe — deteniendo y eliminando…"
        docker stop "$name" 2>/dev/null || true
        docker rm   "$name" 2>/dev/null || true
    fi
}

# ─── Comprobar si el contenedor está vivo ────────────────────────────────────
is_container_running() {
    local name="$1"
    # Preguntamos a Docker si el estado exacto es "running"
    if [ "$(docker inspect -f '{{.State.Status}}' "$name" 2>/dev/null)" == "running" ]; then
        return 0 # Verdadero: Está corriendo
    fi
    return 1 # Falso: Está apagado, crasheado o no existe
}

# ─── Validación de filesystem ────────────────────────────────────────────────
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

# ─── [V21-B7] Cleanup con distinción ESRCH vs EPERM ─────────────────────────
safe_kill_check() {
    # Retorna 0 si el proceso existe y es nuestro, 1 si no existe, 2 si existe pero sin permisos
    local pid="$1"
    if kill -0 "$pid" 2>/dev/null; then
        return 0  # Existe y tenemos permisos
    else
        # Distinguir: ESRCH (no existe) vs EPERM (existe pero sin permisos)
        if [[ -d "/proc/$pid" ]]; then
            return 2  # Existe pero sin permisos (EPERM)
        else
            return 1  # No existe (ESRCH)
        fi
    fi
}

# ═══════════════════════════════════════════════════════════════════════════════
# TRAP EXIT — Graceful shutdown (Solo en caso de error)
# ═══════════════════════════════════════════════════════════════════════════════
cleanup() {
    local exit_code="$?"

    # SOLO matar procesos si el script terminó por un ERROR
    if [[ "$exit_code" -ne 0 ]]; then
        warn "Se detectó un error (código $exit_code). Ejecutando limpieza de emergencia..."
        
        # Limpiar watchdog si está corriendo
        if [[ -n "${WATCHDOG_PID:-}" ]] && kill -0 "$WATCHDOG_PID" 2>/dev/null; then
            kill -TERM "$WATCHDOG_PID" 2>/dev/null || true
        fi

        # Limpiar indexador si está corriendo
        if [[ -f "$INDEXER_PID_FILE" ]]; then
            local idx_pid
            idx_pid=$(cat "$INDEXER_PID_FILE" 2>/dev/null || echo "")
            if [[ -n "$idx_pid" ]]; then
                local kill_status=0
                safe_kill_check "$idx_pid" || kill_status=$?
                if (( kill_status == 0 )); then
                    info "Limpieza: enviando SIGTERM al indexador (PID $idx_pid)…"
                    kill -TERM "$idx_pid" 2>/dev/null || true
                fi
            fi
            rm -f "$INDEXER_PID_FILE"
        fi

        # Limpiar router
        if [[ -f "$PID_FILE" ]]; then
            local pid
            pid=$(cat "$PID_FILE" 2>/dev/null || echo "")
            if [[ -n "$pid" ]]; then
                local kill_status=0
                safe_kill_check "$pid" || kill_status=$?
                if (( kill_status == 0 )); then
                    info "Limpieza: enviando SIGTERM al router V14 (PID $pid)…"
                    kill -TERM "$pid" 2>/dev/null || true
                    local wait_count=0
                    while kill -0 "$pid" 2>/dev/null && (( wait_count < 30 )); do
                        sleep 1
                        wait_count=$((wait_count + 1))
                    done
                    if kill -0 "$pid" 2>/dev/null; then
                        kill -9 "$pid" 2>/dev/null || true
                    fi
                fi
            fi
            rm -f "$PID_FILE"
        fi
        err "Script abortado. Log en: $LOG_FILE"
    else
        ok "Autoboot finalizado. Todos los servicios quedan operando en background."
    fi
}
trap cleanup EXIT

# ═══════════════════════════════════════════════════════════════════════════════
# INICIO
# ═══════════════════════════════════════════════════════════════════════════════
section "OMEN AI Cluster — Autoboot V21"
info "$(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# Crear directorios necesarios en ext4
mkdir -p "$AI_HOME" "$LOG_DIR" "$OBSIDIAN_APPDATA" "$AGENT_DATA_DIR"

# Redirigir stdout+stderr al log
exec > >(tee -a "$LOG_FILE") 2>&1
info "Log: $LOG_FILE"

# ─────────────────────────────────────────────────────────────────────────────
# VERIFICACIÓN ESTRICTA DE ACCESO AL SSD (Directorio AI_CORE)
# ─────────────────────────────────────────────────────────────────────────────
section "Verificación de SSD exFAT y Permisos"

# 1. Comprobar que el directorio existe en el espejo del HOME
if [[ ! -d "$AI_CORE" ]]; then
    err "El directorio $AI_CORE no existe."
    err "Verifica que el servicio systemd de BitLocker haya montado la unidad."
    exit 1
fi

# 2. Comprobar permisos de escritura (Vital para que SGLang/Ollama descarguen/lean)
if [[ ! -w "$AI_CORE" ]]; then
    err "El directorio $AI_CORE existe, pero está en solo-lectura (read-only)."
    err "Revisa las banderas uid/gid y fmask/dmask en el script de montaje exFAT."
    exit 1
fi

# Si pasa ambas pruebas, el SSD está montado, mapeado y listo para la inferencia
ok "Directorio de IA ($AI_CORE) operativo, montado y con permisos correctos."

# Crear vault en exFAT si no existe
mkdir -p "$VAULT_DIR" 2>/dev/null || warn "No se pudo crear $VAULT_DIR. Ignorando..."

# ═══════════════════════════════════════════════════════════════════════════════
# COMPROBACIONES PREVIAS
# ═══════════════════════════════════════════════════════════════════════════════
section "Comprobaciones previas"

# Herramientas de red
if ! command -v nc &>/dev/null; then
    warn "netcat (nc) no encontrado — usando /dev/tcp como fallback para wait_port"
fi

# Docker
if ! command -v docker &>/dev/null; then
    err "Docker no encontrado. Instala Docker Engine."
    exit 1
fi

# Versión de Docker
DOCKER_VERSION=$(docker version --format '{{.Server.Version}}' 2>/dev/null || echo "0.0.0")
DOCKER_MAJOR=$(echo "$DOCKER_VERSION" | cut -d. -f1)
DOCKER_MINOR=$(echo "$DOCKER_VERSION" | cut -d. -f2)
if [[ "$DOCKER_MAJOR" =~ ^[0-9]+$ ]] && [[ "$DOCKER_MINOR" =~ ^[0-9]+$ ]]; then
    if (( DOCKER_MAJOR < 20 )) || { (( DOCKER_MAJOR == 20 )) && (( DOCKER_MINOR < 10 )); }; then
        warn "Docker $DOCKER_VERSION detectado — se recomienda 20.10+ para compatibilidad completa"
    else
        ok "Docker $DOCKER_VERSION"
    fi
else
    warn "No se pudo determinar la versión de Docker ($DOCKER_VERSION) — continuando"
fi

# Python
if ! command -v python3 &>/dev/null; then
    err "python3 no encontrado. Instala Python 3.10+."
    exit 1
fi

# Versión de Python (3.10+ requerido)
PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)
if [[ "$PYTHON_MAJOR" =~ ^[0-9]+$ ]] && [[ "$PYTHON_MINOR" =~ ^[0-9]+$ ]]; then
    if (( PYTHON_MAJOR < 3 )) || { (( PYTHON_MAJOR == 3 )) && (( PYTHON_MINOR < 10 )); }; then
        err "Python $PYTHON_VERSION detectado — se requiere 3.10+ para el router"
        exit 1
    fi
    ok "Python $PYTHON_VERSION"
else
    warn "No se pudo determinar la versión de Python — continuando con precaución"
fi

# [V21-B1] Verificar router V14
if [[ ! -f "$ROUTER_SCRIPT" ]]; then
    err "Router V14 no encontrado: $ROUTER_SCRIPT"
    err "Copia orchestrator_router_V14.py a $AI_HOME/"
    exit 1
fi

# [V21-B14] Verificar paquete de módulos
if [[ ! -d "$ROUTER_MODULES_DIR" ]] || [[ ! -f "$ROUTER_MODULES_DIR/__init__.py" ]]; then
    err "Paquete omen_router_modules/ no encontrado en $AI_HOME/"
    err "Copia el directorio omen_router_modules/ completo a $AI_HOME/"
    exit 1
fi

# Verificar sintaxis del router
if ! python3 -m py_compile "$ROUTER_SCRIPT" 2>/dev/null; then
    err "Error de sintaxis en $ROUTER_SCRIPT — abortando"
    python3 -m py_compile "$ROUTER_SCRIPT" || true
    exit 1
fi
ok "Router V14: sintaxis correcta"

# [V21-B11] Verificar integridad de módulos (compilación)
MODULE_ERRORS=0
for mod_file in "$ROUTER_MODULES_DIR"/*.py; do
    if [[ -f "$mod_file" ]]; then
        if ! python3 -m py_compile "$mod_file" 2>/dev/null; then
            err "Error de sintaxis en módulo: $mod_file"
            (( MODULE_ERRORS++ ))
        fi
    fi
done
if (( MODULE_ERRORS > 0 )); then
    err "$MODULE_ERRORS módulo(s) con errores de sintaxis — abortando"
    exit 1
fi
ok "Módulos del router: sintaxis correcta ($(ls "$ROUTER_MODULES_DIR"/*.py | wc -l) ficheros)"

# Permisos de escritura en agent_data/
if [[ ! -w "$AGENT_DATA_DIR" ]]; then
    err "Sin permisos de escritura en $AGENT_DATA_DIR — el agente no podrá persistir estado"
    exit 1
fi
ok "Agent data dir: permisos correctos ($AGENT_DATA_DIR)"

# Validar filesystem de AGENT_DATA_DIR
if ! validate_filesystem "$AGENT_DATA_DIR" "Agent data dir"; then
    err "AGENT_DATA_DIR ($AGENT_DATA_DIR) está en un filesystem incompatible con SQLite."
    exit 1
fi

# ─── [V21-B5] Check de espacio en disco ─────────────────────────────────────
DISK_FREE_MB=$(df --output=avail "$AI_HOME" 2>/dev/null | tail -1 | awk '{print int($1/1024)}')
if [[ -n "$DISK_FREE_MB" ]] && (( DISK_FREE_MB < MIN_DISK_EXT4_MB )); then
    err "Espacio libre insuficiente en ext4: ${DISK_FREE_MB}MB (mínimo: ${MIN_DISK_EXT4_MB}MB)"
    err "Libera espacio en la partición de $AI_HOME antes de continuar."
    exit 1
fi
ok "Espacio en disco (ext4): ${DISK_FREE_MB:-?}MB libres (mín: ${MIN_DISK_EXT4_MB}MB)"

if [[ -d "$AI_CORE" ]]; then
    EXFAT_FREE_MB=$(df --output=avail "$AI_CORE" 2>/dev/null | tail -1 | awk '{print int($1/1024)}')
    if [[ -n "$EXFAT_FREE_MB" ]] && (( EXFAT_FREE_MB < MIN_DISK_EXFAT_MB )); then
        warn "Espacio libre en SSD exFAT bajo: ${EXFAT_FREE_MB}MB (mínimo recomendado: ${MIN_DISK_EXFAT_MB}MB)"
        warn "Los pulls de modelos pueden requerir espacio adicional."
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

# ─── [V21-B8] Rotación de logs ──────────────────────────────────────────────
LOG_COUNT=$(find "$LOG_DIR" -maxdepth 1 -name "autoboot_v*.log" 2>/dev/null | wc -l)
if (( LOG_COUNT > MAX_LOG_FILES )); then
    find "$LOG_DIR" -maxdepth 1 -name "autoboot_v*.log" -printf '%T@ %p\n' 2>/dev/null \
        | sort -rn | tail -n +$((MAX_LOG_FILES + 1)) | cut -d' ' -f2- | xargs rm -f 2>/dev/null || true
    info "Limpiados $((LOG_COUNT - MAX_LOG_FILES)) logs antiguos (mantenidos últimos $MAX_LOG_FILES)"
fi

# Rotar logs del router también
ROUTER_LOG_COUNT=$(find "$LOG_DIR" -maxdepth 1 -name "router_v*.log" 2>/dev/null | wc -l)
if (( ROUTER_LOG_COUNT > 5 )); then
    find "$LOG_DIR" -maxdepth 1 -name "router_v*.log" -printf '%T@ %p\n' 2>/dev/null \
        | sort -rn | tail -n +6 | cut -d' ' -f2- | xargs rm -f 2>/dev/null || true
    info "Limpiados $((ROUTER_LOG_COUNT - 5)) logs del router antiguos"
fi

# Backup de agent_tasks.db
AGENT_DB="$AGENT_DATA_DIR/agent_tasks.db"
if [[ -f "$AGENT_DB" ]]; then
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
        BACKUP_NAME="${AGENT_DB}.bak_CORRUPT_$(date +%Y%m%d_%H%M%S)"
        cp "$AGENT_DB" "$BACKUP_NAME"
    fi

    # Limpiar backups antiguos (mantener últimos 5)
    find "$AGENT_DATA_DIR" -maxdepth 1 -name "agent_tasks.db.bak_*" -printf '%T@ %p\n' 2>/dev/null \
        | sort -rn | tail -n +6 | cut -d' ' -f2- | xargs rm -f 2>/dev/null || true
fi

# ─── [V21-B4] Verificar puertos críticos antes de arrancar ──────────────────
section "Verificación de puertos"
PORTS_OK=true
for port_var in PORT_OLLAMA_GPU PORT_OLLAMA_CPU PORT_TABBYAPI PORT_SGLANG PORT_CHROMADB PORT_OBSIDIAN PORT_SEARXNG PORT_ROUTER; do
    port_val="${!port_var}"
    if ! check_port_free "$port_val" "$port_var"; then
        PORTS_OK=false
    fi
done

if [[ "$PORTS_OK" == "true" ]]; then
    ok "Todos los puertos necesarios están libres"
else
    warn "Algunos puertos están ocupados — los contenedores existentes serán reemplazados"
fi

ok "Comprobaciones previas: ✔"

# ═══════════════════════════════════════════════════════════════════════════════
# RED DOCKER
# ═══════════════════════════════════════════════════════════════════════════════
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

# ═══════════════════════════════════════════════════════════════════════════════
# VOLUMEN CHROMADB
# ═══════════════════════════════════════════════════════════════════════════════
section "Volumen ChromaDB"
if ! docker volume ls --format '{{.Name}}' | grep -qx "chromadb_data"; then
    docker volume create chromadb_data
    ok "Volumen 'chromadb_data' creado"
else
    ok "Volumen 'chromadb_data' ya existe"
fi

# ═══════════════════════════════════════════════════════════════════════════════
# 1. OLLAMA GPU (:11434)
# ═══════════════════════════════════════════════════════════════════════════════
section "1/7 — Ollama GPU (:$PORT_OLLAMA_GPU)"

# 1. PRE-CREAR el directorio antes para evitar el error 'chown' del demonio de Docker
mkdir -p "${MODELS_DIR}/ollama" 2>/dev/null || true

if is_container_running "ollama-gpu-main"; then
    info "Contenedor 'ollama-gpu-main' en ejecución. Reutilizando (ahorrando VRAM)..."
else
    ensure_container_stopped "ollama-gpu-main"

    # 2. SEPARAR el estado interno (ext4 en Docker) de los pesos (.gguf en exFAT)
    docker run -d \
        --name ollama-gpu-main \
        --network "$DOCKER_NET" \
        --gpus all \
        -p "${PORT_OLLAMA_GPU}:11434" \
        -e OLLAMA_MODELS=/models \
        -v "${MODELS_DIR}/ollama:/models" \
        -v ollama_gpu_data:/root/.ollama \
        -e OLLAMA_KEEP_ALIVE=24h \
        -e OLLAMA_MAX_LOADED_MODELS=1 \
        -e OLLAMA_FLASH_ATTENTION=1 \
        -e OLLAMA_NUM_PARALLEL=1 \
        --restart unless-stopped \
        ollama/ollama:latest
fi

wait_port "Ollama GPU" localhost "$PORT_OLLAMA_GPU" "$TIMEOUT_OLLAMA"

# Pre-pull modelos GPU en background
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

ok "Ollama GPU ✔ (${#GPU_PULL_PIDS[@]} pulls en background)"

# ═══════════════════════════════════════════════════════════════════════════════
# 2. OLLAMA CPU (:11435)
# ═══════════════════════════════════════════════════════════════════════════════
section "2/7 — Ollama CPU (:$PORT_OLLAMA_CPU)"

# 1. PRE-CREAR el directorio
mkdir -p "${MODELS_DIR}/ollama-cpu" 2>/dev/null || true

if is_container_running "ollama-cpu-router"; then
    info "Contenedor 'ollama-cpu-router' en ejecución. Reutilizando estado..."
else
    ensure_container_stopped "ollama-cpu-router"

    # 2. Omitimos la bandera --gpus y usamos CUDA_VISIBLE_DEVICES="" para aislar la VRAM
    docker run -d \
        --name ollama-cpu-router \
        --network "$DOCKER_NET" \
        -p "${PORT_OLLAMA_CPU}:11434" \
        -e CUDA_VISIBLE_DEVICES="" \
        -e OLLAMA_MODELS=/models \
        -v "${MODELS_DIR}/ollama-cpu:/models" \
        -v ollama_cpu_data:/root/.ollama \
        -e OLLAMA_KEEP_ALIVE=24h \
        -e OLLAMA_MAX_LOADED_MODELS=2 \
        -e OLLAMA_NUM_PARALLEL=1 \
        --restart unless-stopped \
        ollama/ollama:latest
fi

wait_port "Ollama CPU" localhost "$PORT_OLLAMA_CPU" "$TIMEOUT_OLLAMA"

# Pull modelos CPU (bloqueante — necesarios para indexador/router)
CPU_PULL_PIDS=()
for model in "${OLLAMA_CPU_MODELS[@]}"; do
    if ! docker exec ollama-cpu-router ollama list 2>/dev/null | grep -q "$model"; then
        info "Pull de $model (CPU)…"
        docker exec ollama-cpu-router ollama pull "$model" \
            >> "$LOG_DIR/pull_cpu.log" 2>&1 &
        CPU_PULL_PIDS+=($!)
    else
        ok "$model ya presente en CPU"
    fi
done

# Esperar pulls de CPU
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

# ═══════════════════════════════════════════════════════════════════════════════
# 3. TabbAPI / ExLlamaV2 (:5000)
# ═══════════════════════════════════════════════════════════════════════════════
section "3/7 — TabbAPI ExLlamaV2 (:$PORT_TABBYAPI)"

EXL2_CHAT="${MODELS_DIR}/llama-3.1-8b-exl2"
EXL2_CODER="${MODELS_DIR}/qwen2.5-coder-7b-exl2"

if [[ -d "$EXL2_CHAT" ]] || [[ -d "$EXL2_CODER" ]]; then
    if is_container_running "exllamav2-api"; then
        info "Contenedor 'exllamav2-api' en ejecución. Reutilizando (ahorrando VRAM)..."
    else
        ensure_container_stopped "exllamav2-api"
        docker run -d \
            --name exllamav2-api \
            --network "$DOCKER_NET" \
            --gpus all \
            -p "${PORT_TABBYAPI}:5000" \
            -v "${MODELS_DIR}:/models:ro" \
            --restart unless-stopped \
            ghcr.io/theroyallab/tabbyapi:latest \
            --model-dir /models \
            --model "llama-3.1-8b-exl2" \
            --max-seq-len 8192 \
            --tensor-parallel 1 \
            --port 5000
    fi

    if wait_port "TabbAPI" localhost "$PORT_TABBYAPI" "$TIMEOUT_TABBYAPI"; then
        ok "TabbAPI ExLlamaV2 ✔"
    else
        warn "TabbAPI no respondió — niveles CHAT/INSTANTANEO no disponibles"
        docker logs --tail=20 exllamav2-api 2>&1 || true
    fi
else
    warn "Modelos EXL2 no encontrados en $MODELS_DIR — omitiendo TabbAPI"
fi

# ═══════════════════════════════════════════════════════════════════════════════
# 4. SGLang (:30000) — [V21-B3] Timeout aumentado, [V21-B9] Verificación de modelo
# ═══════════════════════════════════════════════════════════════════════════════
section "4/7 — SGLang (:$PORT_SGLANG)"

SGLANG_MODEL="${MODELS_DIR}/llama-3.1-8b-awq"

# [V21-B9] Verificar que el modelo existe antes de intentar arrancar
if [[ -d "$SGLANG_MODEL" ]]; then
    # Verificar que contiene ficheros de modelo (al menos config.json o similar)
    if [[ ! -f "$SGLANG_MODEL/config.json" ]] && [[ ! -f "$SGLANG_MODEL/model.safetensors.index.json" ]]; then
        warn "Directorio $SGLANG_MODEL existe pero no contiene ficheros de modelo"
    fi

    if is_container_running "sglang-server"; then
        info "Contenedor 'sglang-server' en ejecución. Reutilizando (ahorrando VRAM)..."
    else
        ensure_container_stopped "sglang-server"
        docker run -d \
            --name sglang-server \
            --network "$DOCKER_NET" \
            --gpus all \
            -p "${PORT_SGLANG}:30000" \
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
    fi

    # [V21-B3] Timeout aumentado a 240s para primera carga
    if wait_port "SGLang" localhost "$PORT_SGLANG" "$TIMEOUT_SGLANG"; then
        ok "SGLang ✔"
    else
        warn "SGLang no respondió en ${TIMEOUT_SGLANG}s — nivel AGIL no disponible"
        docker logs --tail=20 sglang-server 2>&1 || true
    fi
else
    warn "Modelo AWQ no encontrado: $SGLANG_MODEL — omitiendo SGLang"
fi

# ═══════════════════════════════════════════════════════════════════════════════
# 5. CHROMADB (:8001)
# ═══════════════════════════════════════════════════════════════════════════════
section "5/7 — ChromaDB (:$PORT_CHROMADB)"

if is_container_running "chromadb"; then
    info "Contenedor 'chromadb' en ejecución. Reutilizando estado de memoria..."
else
    ensure_container_stopped "chromadb"
    docker run -d \
        --name chromadb \
        --network "$DOCKER_NET" \
        -p "${PORT_CHROMADB}:8000" \
        -v chromadb_data:/chroma/chroma \
        -e IS_PERSISTENT=TRUE \
        -e ANONYMIZED_TELEMETRY=FALSE \
        -e CHROMA_SERVER_HOST=0.0.0.0 \
        -e CHROMA_SERVER_HTTP_PORT=8000 \
        --restart unless-stopped \
        ghcr.io/chroma-core/chroma:0.6.3
fi

CHROMADB_READY=false
MAX_RETRIES=$TIMEOUT_CHROMADB
RETRY_COUNT=0
info "Esperando que ChromaDB inicialice su API HTTP en 127.0.0.1:${PORT_CHROMADB}..."

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    # Usamos la ruta oficial v1 sin comprobaciones internas extrañas
    CHROMA_STATUS=$(get_http_status "http://127.0.0.1:${PORT_CHROMADB}/api/v1/heartbeat")
    
    if [ "$CHROMA_STATUS" = "200" ]; then
        CHROMADB_READY=true
        break
    fi
    
    if ! docker ps --format '{{.Names}}' | grep -qx "chromadb"; then
        err "Contenedor 'chromadb' ya no está en ejecución. Revisa: docker logs chromadb"
        break
    fi

    RETRY_COUNT=$((RETRY_COUNT + 1))
    sleep 1
done

if [ "$CHROMADB_READY" = true ] || [ "$CHROMADB_READY" = "true" ]; then
    ok "ChromaDB ✔ — API lista en ${RETRY_COUNT}s (puerto ${PORT_CHROMADB})"
else
    warn "ChromaDB API no respondió tras ${MAX_RETRIES}s (último estado: ${CHROMA_STATUS:-000})"
    warn "Revisa: docker logs chromadb --tail 30"
fi

# ═══════════════════════════════════════════════════════════════════════════════
# 6. OBSIDIAN WEB (:3000)
# ═══════════════════════════════════════════════════════════════════════════════
section "6/7 — Obsidian (:$PORT_OBSIDIAN)"

if is_container_running "obsidian-kb"; then
    info "Contenedor 'obsidian-kb' en ejecución. Reutilizando estado..."
else
    ensure_container_stopped "obsidian-kb"
    docker run -d \
        --name obsidian-kb \
        --network "$DOCKER_NET" \
        -p "${PORT_OBSIDIAN}:3000" \
        -v "${VAULT_DIR}:/vault" \
        -v "${OBSIDIAN_APPDATA}:/config" \
        -e VAULT_PATH="/vault" \
        -e PUID="$(id -u)" \
        -e PGID="$(id -g)" \
        --restart unless-stopped \
        linuxserver/obsidian:latest
fi

if wait_port "Obsidian" localhost "$PORT_OBSIDIAN" "$TIMEOUT_OBSIDIAN"; then
    ok "Obsidian ✔ → http://localhost:$PORT_OBSIDIAN"
else
    warn "Obsidian no respondió — acceso al vault web no disponible"
fi

# ═══════════════════════════════════════════════════════════════════════════════
# 7. SEARXNG (:8888)
# ═══════════════════════════════════════════════════════════════════════════════
section "7/7 — SearXNG (:$PORT_SEARXNG)"

# Generar o recuperar secret_key persistente
if [[ ! -f "$SEARXNG_SECRET_FILE" ]]; then
    openssl rand -hex 32 > "$SEARXNG_SECRET_FILE"
    chmod 600 "$SEARXNG_SECRET_FILE"
    info "Nueva secret_key generada en $SEARXNG_SECRET_FILE (permisos: 600)"
else
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
    chmod 600 "$SEARXNG_SETTINGS"
    ok "settings.yml generado en $SEARXNG_SETTINGS (permisos: 600)"
fi

if is_container_running "searxng"; then
    info "Contenedor 'searxng' en ejecución. Reutilizando estado..."
else
    ensure_container_stopped "searxng"
    docker run -d \
        --name searxng \
        --network "$DOCKER_NET" \
        -p "${PORT_SEARXNG}:8888" \
        -v "${SEARXNG_SETTINGS}:/etc/searxng/settings.yml:ro" \
        -e SEARXNG_SECRET_KEY="${SEARXNG_SECRET}" \
        --restart unless-stopped \
        searxng/searxng:latest
fi

if wait_port "SearXNG" localhost "$PORT_SEARXNG" "$TIMEOUT_SEARXNG"; then
    ok "SearXNG ✔ → http://localhost:$PORT_SEARXNG"
else
    warn "SearXNG no respondió"
fi

# ═══════════════════════════════════════════════════════════════════════════════
# INDEXACIÓN VAULT — [V21-B2] Actualizado a V6
# ═══════════════════════════════════════════════════════════════════════════════
section "Indexación Vault Obsidian"

if [[ -f "$VAULT_INDEXER" ]]; then
    # Usando el helper blindado (con retry breve)
    OLLAMA_CPU_STATUS="000"
    for _i in $(seq 1 10); do
        OLLAMA_CPU_STATUS=$(get_http_status "http://127.0.0.1:${PORT_OLLAMA_CPU}/")
        [ "$OLLAMA_CPU_STATUS" = "200" ] && break
        sleep 2
    done

    # Limpiar variables nulas por seguridad
    if [[ "$CHROMA_STATUS" != "200" ]]; then CHROMA_STATUS="000"; fi
    if [[ "$OLLAMA_CPU_STATUS" != "200" ]]; then OLLAMA_CPU_STATUS="000"; fi

    if [ "$CHROMA_STATUS" = "200" ] && [ "$OLLAMA_CPU_STATUS" = "200" ]; then
        ok "Motores validados. Iniciando indexación automática de la bóveda..."
        # Le pasamos 127.0.0.1 al script de Python también por si acaso
        python3 "$VAULT_INDEXER" \
            --vault-dir "$VAULT_DIR" \
            --chroma-url "http://127.0.0.1:${PORT_CHROMADB}" \
            --ollama-embed-url "http://127.0.0.1:${PORT_OLLAMA_CPU}/api/embeddings" \
            --state-dir "$AGENT_DATA_DIR" \
            >> "$LOG_DIR/indexar_vault.log" 2>&1 &
        INDEXER_PID=$!
        echo "$INDEXER_PID" > "$INDEXER_PID_FILE"
        info "Indexador en background PID=$INDEXER_PID (log: $LOG_DIR/indexar_vault.log)"
    else
        warn "Condiciones no cumplidas (Chroma: $CHROMA_STATUS | Ollama CPU: $OLLAMA_CPU_STATUS)"
        warn "Ejecuta manualmente: python3 $VAULT_INDEXER"
    fi
else
    warn "indexar_vault_v6.py no encontrado en $AI_HOME — vault no indexado"
fi

# ═══════════════════════════════════════════════════════════════════════════════
# DEPENDENCIAS PYTHON — [V21-B13] numpy añadido
# ═══════════════════════════════════════════════════════════════════════════════
section "Dependencias Python"

REQUIRED_PKGS="fastapi uvicorn httpx numpy"
MISSING_PKGS=""
for pkg in $REQUIRED_PKGS; do
    if ! python3 -c "import ${pkg//-/_}" 2>/dev/null; then
        MISSING_PKGS="$MISSING_PKGS $pkg"
    fi
done

if [[ -n "$MISSING_PKGS" ]]; then
    info "Instalando paquetes faltantes:$MISSING_PKGS"
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

# ═══════════════════════════════════════════════════════════════════════════════
# ROUTER V14 — FastAPI + Agent Engine (:8000)
# ═══════════════════════════════════════════════════════════════════════════════
section "Router V14 (FastAPI + Agent :$PORT_ROUTER)"

# Matar instancia previa si existe (Ahora blindado contra set -e)
if [[ -f "$PID_FILE" ]]; then
    OLD_PID=$(cat "$PID_FILE" 2>/dev/null || echo "")
    if [[ -n "$OLD_PID" ]]; then
        kill_status=0
        safe_kill_check "$OLD_PID" || kill_status=$?
        case $kill_status in
            0)
                info "Deteniendo router anterior (PID $OLD_PID)…"
                kill -TERM "$OLD_PID" 2>/dev/null || true
                sleep 5
                if kill -0 "$OLD_PID" 2>/dev/null; then
                    kill -9 "$OLD_PID" 2>/dev/null || true
                fi
                ;;
            2)
                warn "Router anterior (PID $OLD_PID) pertenece a otro usuario"
                ;;
        esac
    fi
    rm -f "$PID_FILE"
fi

# Asegurar que el puerto está libre
if ss -tlnp 2>/dev/null | grep -q ":${PORT_ROUTER} "; then
    warn "Puerto $PORT_ROUTER ocupado — identificando proceso…"
    BLOCKING_PID=$(ss -tlnp 2>/dev/null | grep ":${PORT_ROUTER} " | grep -oP 'pid=\K[0-9]+' | head -1)
    if [[ -n "$BLOCKING_PID" ]]; then
        BLOCKING_CMD=$(ps -p "$BLOCKING_PID" -o comm= 2>/dev/null || echo "desconocido")
        BLOCKING_USER=$(ps -p "$BLOCKING_PID" -o user= 2>/dev/null || echo "desconocido")
        warn "  PID=$BLOCKING_PID ($BLOCKING_CMD) usuario=$BLOCKING_USER ocupa el puerto $PORT_ROUTER"

        if [[ "$BLOCKING_CMD" == "python3" || "$BLOCKING_CMD" == "python" ]] && \
           [[ "$BLOCKING_USER" == "$(whoami)" ]]; then
            info "Proceso Python propio detectado — terminando…"
            kill -TERM "$BLOCKING_PID" 2>/dev/null || true
            sleep 3
            if kill -0 "$BLOCKING_PID" 2>/dev/null; then
                kill -9 "$BLOCKING_PID" 2>/dev/null || true
            fi
        else
            err "Puerto $PORT_ROUTER ocupado por proceso ajeno ($BLOCKING_CMD, usuario=$BLOCKING_USER)"
            err "Libera el puerto manualmente antes de continuar."
            exit 1
        fi
    else
        warn "No se pudo identificar el PID — intentando fuser…"
        fuser -k "${PORT_ROUTER}/tcp" 2>/dev/null || true
    fi
    sleep 2
fi

# Exportar variables de entorno para el router
export AGENT_DB_DIR="$AGENT_DATA_DIR"
export ROUTER_PORT="$PORT_ROUTER"

# Esperar pulls de GPU si aún están corriendo
if [[ ${#GPU_PULL_PIDS[@]} -gt 0 ]]; then
    info "Verificando pulls de GPU en background…"
    for pid in "${GPU_PULL_PIDS[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
            info "  Pull GPU (PID $pid) aún en progreso — no bloqueante para el router"
        fi
    done
fi

# Lanzar router V14
PYTHONUNBUFFERED=1 AGENT_DB_DIR="$AGENT_DATA_DIR" ROUTER_PORT="$PORT_ROUTER" \
    python3 "$ROUTER_SCRIPT" \
    >> "$LOG_DIR/router_v14.log" 2>&1 &
ROUTER_PID=$!
echo "$ROUTER_PID" > "$PID_FILE"
info "Router V14 lanzado — PID=$ROUTER_PID"

# Health check con reintentos
ROUTER_READY=false
HEALTH_ATTEMPTS=0
for i in $(seq 1 $((TIMEOUT_ROUTER_HEALTH / 2))); do
    HEALTH_ATTEMPTS=$((HEALTH_ATTEMPTS + 1)) # SINTAXIS SEGURA (Evita el crash de set -e)
    if curl -sf "http://localhost:${PORT_ROUTER}/health" >/dev/null 2>&1; then
        ROUTER_READY=true
        break
    fi
    if ! kill -0 "$ROUTER_PID" 2>/dev/null; then
        err "Router V14 terminó inesperadamente. Últimas líneas del log:"
        tail -20 "$LOG_DIR/router_v14.log" 2>/dev/null || true
        break
    fi
    sleep 2
done

if $ROUTER_READY; then
    ok "Router V14 ✔ → http://localhost:$PORT_ROUTER (respondió en intento $HEALTH_ATTEMPTS)"
    AGENT_CHECK=$(curl -sf "http://localhost:${PORT_ROUTER}/v1/agent/tasks?limit=1" 2>/dev/null || echo "")
    if [[ -n "$AGENT_CHECK" ]]; then
        ok "Agent Engine ✔ → /v1/agent/tasks respondiendo"
    else
        warn "Agent Engine no respondió — verificar logs"
    fi
else
    err "Router V14 no respondió en ${TIMEOUT_ROUTER_HEALTH}s"
    if kill -0 "$ROUTER_PID" 2>/dev/null; then
        err "El proceso está vivo pero no responde — posible error de binding"
    fi
    tail -20 "$LOG_DIR/router_v14.log" 2>/dev/null || true
fi

# ═══════════════════════════════════════════════════════════════════════════════
# [V21-B12] WATCHDOG POST-ARRANQUE (opcional)
# ═══════════════════════════════════════════════════════════════════════════════
if [[ "$WATCHDOG_ENABLED" == "true" ]]; then
    section "Watchdog post-arranque"
    info "Watchdog activado (intervalo: ${WATCHDOG_INTERVAL}s)"

    # Función watchdog en background
    watchdog_loop() {
        while true; do
            sleep "$WATCHDOG_INTERVAL"

            # Verificar router
            if [[ -f "$PID_FILE" ]]; then
                local r_pid
                r_pid=$(cat "$PID_FILE" 2>/dev/null || echo "")
                if [[ -n "$r_pid" ]] && ! kill -0 "$r_pid" 2>/dev/null; then
                    echo "[WATCHDOG $(date '+%H:%M:%S')] Router V14 caído — reiniciando…" >> "$LOG_DIR/watchdog.log"
                    PYTHONUNBUFFERED=1 AGENT_DB_DIR="$AGENT_DATA_DIR" ROUTER_PORT="$PORT_ROUTER" \
                        python3 "$ROUTER_SCRIPT" >> "$LOG_DIR/router_v14.log" 2>&1 &
                    echo $! > "$PID_FILE"
                    echo "[WATCHDOG $(date '+%H:%M:%S')] Router reiniciado PID=$!" >> "$LOG_DIR/watchdog.log"
                fi
            fi

            # Verificar contenedores Docker con restart policy
            for container in ollama-gpu-main ollama-cpu-router chromadb; do
                if ! docker ps --format '{{.Names}}' | grep -qx "$container"; then
                    echo "[WATCHDOG $(date '+%H:%M:%S')] Contenedor $container no está running" >> "$LOG_DIR/watchdog.log"
                    docker start "$container" 2>/dev/null || true
                fi
            done
        done
    }

    watchdog_loop &
    WATCHDOG_PID=$!
    ok "Watchdog iniciado (PID=$WATCHDOG_PID)"
fi

# ═══════════════════════════════════════════════════════════════════════════════
# RESUMEN FINAL
# ═══════════════════════════════════════════════════════════════════════════════
section "Resumen del Cluster V21"

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

check_service "Ollama GPU (main)"       localhost "$PORT_OLLAMA_GPU"
check_service "Ollama CPU (router/emb)" localhost "$PORT_OLLAMA_CPU"
if docker ps --format '{{.Names}}' | grep -qx "exllamav2-api"; then
    check_service "TabbAPI ExLlamaV2"       localhost "$PORT_TABBYAPI"
else
    printf "%-30s %-12s %b\n" "TabbAPI ExLlamaV2" ":${PORT_TABBYAPI}" "${YEL}— modelos EXL2 no instalados${NC}"
fi
check_service "SGLang"                  localhost "$PORT_SGLANG"
check_service "ChromaDB"                localhost "$PORT_CHROMADB"
check_service "Obsidian Web UI"         localhost "$PORT_OBSIDIAN"
check_service "SearXNG"                 localhost "$PORT_SEARXNG"
check_service "Router V14 (Agent)"      localhost "$PORT_ROUTER"

echo ""
echo -e "${BLD}Configuración OpenClaw (OpenWebUI):${NC}"
echo "  API URL:    http://localhost:${PORT_ROUTER}/v1"
echo "  Model:      ruteador-auto"
echo "  Agent:      http://localhost:${PORT_ROUTER}/v1/agent/tasks"
echo ""
echo -e "${BLD}Autonomous Reasoning Agent:${NC}"
echo "  Crear tarea:     curl -X POST http://localhost:${PORT_ROUTER}/v1/agent/tasks -H 'Content-Type: application/json' -d '{\"prompt\": \"...\", \"max_iterations\": 3}'"
echo "  Ver estado:      curl http://localhost:${PORT_ROUTER}/v1/agent/tasks/{task_id}"
echo "  Ver resultado:   curl http://localhost:${PORT_ROUTER}/v1/agent/tasks/{task_id}/result"
echo "  Stream progreso: curl http://localhost:${PORT_ROUTER}/v1/agent/tasks/{task_id}/stream"
echo "  Listar tareas:   curl http://localhost:${PORT_ROUTER}/v1/agent/tasks"
echo "  Cancelar:        curl -X DELETE http://localhost:${PORT_ROUTER}/v1/agent/tasks/{task_id}"
echo ""
echo -e "${BLD}Comandos útiles:${NC}"
echo "  Ver logs:         tail -f $LOG_DIR/router_v14.log"
echo "  Indexar vault:    python3 $VAULT_INDEXER"
echo "  Reindexar todo:   python3 $VAULT_INDEXER --clean"
echo "  Métricas router:  curl -s http://localhost:${PORT_ROUTER}/metrics | python3 -m json.tool"
echo "  Health check:     curl -s http://localhost:${PORT_ROUTER}/health | python3 -m json.tool"
echo "  Detener router:   kill \$(cat $PID_FILE)"
echo "  Parar cluster:    docker stop ollama-gpu-main ollama-cpu-router exllamav2-api sglang-server chromadb obsidian-kb searxng"
if [[ "$WATCHDOG_ENABLED" == "true" ]]; then
    echo "  Watchdog:         tail -f $LOG_DIR/watchdog.log"
    echo "  Desactivar:       export OMEN_WATCHDOG=false"
fi
echo ""
echo -e "${GRN}${BLD}OMEN AI Cluster V21 — iniciado${NC}"
echo -e "$(date '+%Y-%m-%d %H:%M:%S')"
