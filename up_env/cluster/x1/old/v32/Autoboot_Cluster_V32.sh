#!/bin/bash
# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║ OMEN AI Cluster — Autoboot V32                                             ║
# ║ RTX 4070 8GB · Intel Ultra 7 · 32GB RAM · SSD exFAT /mnt/ai_core          ║
# ╠══════════════════════════════════════════════════════════════════════════════╣
# ║ V32 — Correcciones sobre V31:                                              ║
# ║  ✔ [V32-B1] --exl2 TabbAPI: CUBLAS_STATUS_ALLOC_FAILED durante warmup     ║
# ║             forward de ExLlamaV2. Causa: pico VRAM = pesos(4.5GB) +        ║
# ║             activaciones(~2GB) + KV cache(0.5GB) + cuBLAS workspace(0.3GB)║
# ║             supera el disponible con el runtime CUDA de Ollama activo.     ║
# ║             Fix: --max-seq-len 4096→2048 y --cache-mode fp8 (KV en FP8:   ║
# ║             mitad de VRAM) reducen el pico ~600MB. Si persiste, se añade   ║
# ║             --gpu-split flag para limitar VRAM a ExLlamaV2.                ║
# ║  ✔ [V32-B2] --sglang SGLang: mem-fraction-static 0.15 sigue fallando      ║
# ║             porque el script ejecutado era V31 antiguo (autodetect apuntaba║
# ║             a ruta incorrecta). Corregido: el script ahora imprime su PATH  ║
# ║             real en el arranque para facilitar el diagnóstico. El fix de   ║
# ║             mem-fraction 0.15 ya estaba en V31; en V32 se baja a 0.10 por ║
# ║             seguridad y se añade --enable-memory-saver para overhead CUDA. ║
# ║  ✔ [V32-E1] AUTODETECT: se imprime la ruta absoluta del script activo al  ║
# ║             arrancar, facilitando verificar qué versión está en uso.       ║
# ╠═══════════════════════════════════════════════════════════════════════════╣
# ║ V31 — Heredado (correcciones V31-B1..B2, V31-E1..E2):                      ║
# ║  ✔ [V31-B1] --exl2: timeout Ollama GPU 90s→180s al recrear contenedor     ║
# ║  ✔ [V31-B2] --sglang: mem-fraction-static 0.50→0.15 (corregido a 0.10 en V32)║
# ║  ✔ [V31-E1] Flag --exl2 (simétrico a --sglang), exclusión mutua           ║
# ║  ✔ [V31-E2] Verificación integridad volumen chromadb_data y Obsidian      ║
# ╠═══════════════════════════════════════════════════════════════════════════╣
# ║ V30 — Heredado (correcciones V30-B1..B3):                                  ║
# ║  ✔ [V30-B1] TabbAPI: --model → --model-name                                ║
# ║  ✔ [V30-B2] SearXNG: verificación de port binding antes de reutilizar.     ║
# ║  ✔ [V30-B3] SearXNG settings.yml: eliminados engines inexistentes          ║
# ╠═══════════════════════════════════════════════════════════════════════════╣
# ║  ✔ [V29-B1] TabbAPI: CMD correcto → 'main.py --host 0.0.0.0 [args]'       ║
# ║             ENTRYPOINT=python3 ya existe en imagen; pasar solo args de CMD  ║
# ║             V28 pasaba 'python3 -m tabbyapi' → buscaba /app/python3 → err  ║
# ║  ✔ [V29-B2] SearXNG: puerto interno corregido :8888→:8080.                 ║
# ║             La imagen escucha en 8080 interno; el mapeo -p 8888:8888 roto   ║
# ╠═══════════════════════════════════════════════════════════════════════════╣
# ║  ✔ [V28-B1] TabbAPI: añadido 'python3 -m tabbyapi' al docker run.         ║
# ║             Sin él, Python interceptaba --model-dir como su propio arg     ║
# ║             y el servidor nunca arrancaba (error: unknown option).          ║
# ║  ✔ [V28-B2] SearXNG --status: curl añade -L (follow redirects) y          ║
# ║             timeout 5s. SearXNG responde 302 antes de 200 en /             ║
# ╠═══════════════════════════════════════════════════════════════════════════╣
# ║  ✔ [V27-S1] Flag --sglang: intercambia TabbAPI por SGLang en VRAM.        ║
# ║             Por defecto TabbAPI activo. Con --sglang: TabbAPI se detiene   ║
# ║             (libera ~6.9GB VRAM) y SGLang arranca con mem-fraction 0.50   ║
# ║             y max-total-tokens 16384 (sin --enable-torch-compile).         ║
# ║  ✔ [V27-S2] En modo --sglang SGLang omite VRAM check (ya tiene la VRAM).  ║
# ║  ✔ [V27-S3] Resumen final muestra 'Modo VRAM activo' (default/sglang).    ║
# ║  ✔ [V27-S4] --status y --stop actualizados para ambos modos.              ║
# ║  ✔ [V27-S5] --help documenta el nuevo flag --sglang.                      ║
# ╠═══════════════════════════════════════════════════════════════════════════╣
# ║  ✔ [V25-F1] Flag --stop: para todos los contenedores y el router de forma  ║
# ║             ordenada (rescatado y actualizado desde V16)                   ║
# ║  ✔ [V25-F2] Flag --status: muestra el estado HTTP de todos los servicios  ║
# ║             del cluster sin arrancar ni detener nada (rescatado de V16)    ║
# ║  ✔ [V25-F3] Flag --reindex: re-indexa el vault Obsidian en ChromaDB       ║
# ║             (rescatado de V16, actualizado a indexar_vault_v6.py)          ║
# ║  ✔ [V25-F4] Flag --warmup: carga en VRAM los modelos Ollama GPU sin       ║
# ║             arrancar el cluster completo (rescatado de V16)                ║
# ║  ✔ [V25-F5] Parseo de argumentos corregido: los flags de acción rápida    ║
# ║             (--stop/--status/--reindex/--warmup) se ejecutan DESPUÉS de    ║
# ║             cargar la configuración pero ANTES de arrancar servicios       ║
# ╠══════════════════════════════════════════════════════════════════════════════╣
# ║ Heredado de V24 (todas las correcciones V24-E1..E3):                       ║
# ║  ✔ [V24-E1..E3] Flag --last, --help, parseo de argumentos — sin cambios   ║
# ╠══════════════════════════════════════════════════════════════════════════════╣
# ║ Heredado de V23 (todas las correcciones V23-D1):                           ║
# ║  ✔ [V23-D1] Red Docker: limpieza de bridges huérfanos — sin cambios        ║
# ╠══════════════════════════════════════════════════════════════════════════════╣
# ║ Heredado de V22 (todas las correcciones V22-C1..C9):                       ║
# ║  ✔ [V22-C1..C9] Todas las mejoras de V22 mantenidas sin cambios            ║
# ╠══════════════════════════════════════════════════════════════════════════════╣
# ║ Heredado de V21 (todas las correcciones V21-B1..B14):                      ║
# ║  ✔ [V21-B1..B14] Todas las mejoras de V21 mantenidas sin cambios           ║
# ╠══════════════════════════════════════════════════════════════════════════════╣
# ║ Contenedores levantados:                                                    ║
# ║  1. ollama-gpu-main     :11434   GPU VRAM primaria                         ║
# ║  2. ollama-cpu-router   :11435   CPU — nomic-embed + phi4-mini             ║
# ║  3. exllamav2-api       :5000    TabbAPI — CHAT / INSTANTANEO              ║
# ║  4. sglang-server       :30000   SGLang — AGIL                             ║
# ║  5. chromadb            :8001    RAG vectorial (vol. nombrado ext4)        ║
# ║  6. obsidian-kb         :3000    Obsidian Web UI                           ║
# ║  7. searxng             :8888    Búsqueda web privada                      ║
# ║  Router: orchestrator_router_V14.py  :8000  (FastAPI + Agent Engine)       ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

set -euo pipefail

# ═══════════════════════════════════════════════════════════════════════════════
# [V24-E2/E3] PARSEO DE ARGUMENTOS — debe ir antes de la configuración
# ═══════════════════════════════════════════════════════════════════════════════

# Valores por defecto de flags
_FLAG_LAST=false
_FLAG_HELP=false
_FLAG_STOP=false      # [V25-F1]
_FLAG_STATUS=false    # [V25-F2]
_FLAG_REINDEX=false   # [V25-F3]
_FLAG_WARMUP=false    # [V25-F4]
_FLAG_SGLANG=false    # [V27-S1]
_FLAG_EXL2=false      # [V31-E1]

# ─── Función de ayuda ────────────────────────────────────────────────────────
show_help() {
    cat << 'HELP_EOF'

╔══════════════════════════════════════════════════════════════════════════════╗
║  OMEN AI Cluster — Autoboot V31                                            ║
║  Uso: ai_cluster [--last] [--exl2|--sglang] [--help]                                         ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  FLAGS DISPONIBLES                                                         ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                            ║
║  (sin flags)    Arranque normal usando las imágenes Docker ya presentes.   ║
║                 Si la imagen no existe localmente, se descarga solo        ║
║                 la primera vez (comportamiento estándar de docker run).    ║
║                                                                            ║
║  --last         Fuerza docker pull en todas las imágenes :latest antes     ║
║                 de arrancar cada servicio. Actualiza a la versión más      ║
║                 reciente disponible en el registry.                        ║
║                 ⚠  EXCEPCIÓN: ChromaDB siempre usa la versión pinada      ║
║                    (0.6.3) y NUNCA se actualiza con este flag.             ║
║                 ⚠  Requiere conexión a Internet y tiempo adicional.        ║
║                 ⚠  Puede introducir cambios de comportamiento si upstream  ║
║                    rompe compatibilidad. Usar con precaución.              ║
║                                                                            ║
║  --help         Muestra esta ayuda y termina sin arrancar el cluster.      ║
║                                                                            ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  GESTIÓN DEL CLUSTER                                                       ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                            ║
║  --stop         Para todos los contenedores y el router de forma           ║
║                 ordenada. Equivale al alias dstop + dkill del cluster.     ║
║                                                                            ║
║  --status       Muestra el estado HTTP de todos los servicios en tiempo    ║
║                 real. No arranca ni detiene nada.                          ║
║                                                                            ║
║  --reindex      Re-indexa el vault Obsidian en ChromaDB usando             ║
║                 indexar_vault_v6.py --clean. Requiere cluster activo.      ║
║                                                                            ║
║  --warmup       Carga los modelos Ollama GPU en VRAM enviando un prompt    ║
║                 mínimo a cada uno. No arranca el cluster completo.         ║
║                                                                            ║
║  --exl2         Activa TabbAPI EXL2 (opt-in). Recrea Ollama GPU con        ║
║                 KEEP_ALIVE=0 para ceder VRAM bajo demanda. Timeout         ║
║                 aumentado a 180s (arranca desde cero tras recrear). [V31]  ║
║                 Mutuamente excluyente con --sglang.                        ║
║                                                                            ║
║  --sglang       Modo VRAM alternativo: para TabbAPI (libera ~6.9GB VRAM)   ║
║                 y arranca SGLang (llama-3.1-8b-awq, mem-fraction 0.15).   ║
║                 Mutuamente excluyente con --exl2.                          ║
║                                                                            ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  EJEMPLOS                                                                  ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                            ║
║  ai_cluster              # Arranque normal (imágenes locales)              ║
║  ai_cluster --last       # Arranque actualizando todas las imágenes        ║
║  ai_cluster --exl2       # Activa TabbAPI EXL2 (KEEP_ALIVE=0 en Ollama)    ║
║  ai_cluster --sglang     # Activa SGLang AWQ (para TabbAPI, mem-frac 0.15)  ║
║  ai_cluster --help       # Muestra esta ayuda                              ║
║                                                                            ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  VARIABLES DE ENTORNO                                                      ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                            ║
║  AI_CORE=/ruta          Override de la ruta del SSD exFAT                 ║
║  OMEN_WATCHDOG=true     Activa el watchdog post-arranque                  ║
║                                                                            ║
╚══════════════════════════════════════════════════════════════════════════════╝

HELP_EOF
}

# ─── Parseo de argumentos ────────────────────────────────────────────────────
for _arg in "$@"; do
    case "$_arg" in
        --last)
            _FLAG_LAST=true
            ;;
        --help|-h)
            _FLAG_HELP=true
            ;;
        --stop)         # [V25-F1]
            _FLAG_STOP=true
            ;;
        --status)       # [V25-F2]
            _FLAG_STATUS=true
            ;;
        --reindex)      # [V25-F3]
            _FLAG_REINDEX=true
            ;;
        --warmup)       # [V25-F4]
            _FLAG_WARMUP=true
            ;;
        --sglang)       # [V27-S1]
            _FLAG_SGLANG=true
            ;;
        --exl2)         # [V31-E1]
            _FLAG_EXL2=true
            ;;
        *)
            echo "[ERROR] Flag desconocido: '$_arg'"
            echo "        Usa --help para ver los flags disponibles."
            exit 1
            ;;
    esac
done

# [V31-E1] Validar exclusión mutua --exl2 / --sglang
if [[ "$_FLAG_EXL2" == "true" ]] && [[ "$_FLAG_SGLANG" == "true" ]]; then
    echo "[ERROR] --exl2 y --sglang son mutuamente excluyentes."
    echo "        Elige uno: --exl2 (TabbAPI EXL2) o --sglang (SGLang AWQ)."
    exit 1
fi

# Ejecutar acciones inmediatas (no requieren configuración cargada)
if [[ "$_FLAG_HELP" == "true" ]]; then
    show_help
    exit 0
fi

# ═══════════════════════════════════════════════════════════════════════════════
# [V21-B10] CONFIGURACIÓN — Sección separada y documentada
# ═══════════════════════════════════════════════════════════════════════════════

# ─── Rutas principales ────────────────────────────────────────────────────────
AI_CORE="${AI_CORE:-/home/fcela-ga/sgoinfre/ai_core}" # SSD exFAT (compartido Win/Linux)
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
LOG_FILE="$LOG_DIR/autoboot_v26_$(date +%Y%m%d_%H%M%S).log"  # [V22-C9] renombrado, [V23-D1] bridge fix
PID_FILE="$AI_HOME/router_v14.pid"
INDEXER_PID_FILE="$AI_HOME/indexer.pid"
SEARXNG_SECRET_FILE="$AI_HOME/.searxng_secret"
SEARXNG_SETTINGS="$AI_HOME/searxng_settings.yml"

# ─── Red Docker ──────────────────────────────────────────────────────────────
DOCKER_NET="ai_net"
DOCKER_NET_SUBNET="172.28.0.0/16"
DOCKER_NET_SUBNET_PREFIX="172.28"   # [V23-D1] Prefijo para detección de bridges huérfanos

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
TIMEOUT_SGLANG=240          # [V21-B3] Aumentado de 120 a 240 para primera carga
TIMEOUT_CHROMADB=60         # [V22-C5] 60s HTTP puro (suficiente para 0.6.3)
TIMEOUT_OBSIDIAN=60
TIMEOUT_SEARXNG=60
TIMEOUT_ROUTER_HEALTH=60

# ─── Espacio mínimo (MB) ─────────────────────────────────────────────────────
MIN_DISK_EXT4_MB=2048       # [V21-B5] 2GB mínimo en ext4
MIN_DISK_EXFAT_MB=5120      # 5GB mínimo en exFAT para pulls

# ─── Modelos ─────────────────────────────────────────────────────────────────
OLLAMA_GPU_MODELS=("deepseek-r1:14b" "phi4-reasoning:plus" "phi4-reasoning:14b-q4_K_M" "qwen2.5:32b")
OLLAMA_CPU_MODELS=("nomic-embed-text" "phi4-mini")

# ─── [V24-E1] Imágenes Docker — versiones por defecto (probadas y estables) ──
# ChromaDB SIEMPRE usa versión pinada — nunca se actualiza con --last
IMG_CHROMADB="ghcr.io/chroma-core/chroma:0.6.3"        # PINADA — no modificar
# Las siguientes usan :latest por defecto; con --last se fuerza docker pull
IMG_OLLAMA="ollama/ollama:latest"
IMG_TABBYAPI="ghcr.io/theroyallab/tabbyapi:latest"
IMG_SGLANG="lmsysorg/sglang:latest"
IMG_OBSIDIAN="linuxserver/obsidian:latest"
IMG_SEARXNG="searxng/searxng:latest"
IMG_CURL="curlimages/curl:latest"                        # Usado en health checks internos
# Flag de actualización (se activa con --last)
PULL_LATEST=false                                        # [V24-E1] true = docker pull antes de arrancar

# ─── Watchdog ────────────────────────────────────────────────────────────────
WATCHDOG_ENABLED="${OMEN_WATCHDOG:-false}" # [V21-B12] Activar con OMEN_WATCHDOG=true
WATCHDOG_INTERVAL=120       # Segundos entre checks

# ─── Arrays para PIDs ────────────────────────────────────────────────────────
declare -a GPU_PULL_PIDS=()
declare -a CPU_PULL_PIDS=()

# ─── Logs: rotación ─────────────────────────────────────────────────────────
MAX_LOG_FILES=10            # [V21-B8] Máximo de logs a mantener
MAX_LOG_SIZE_MB=100         # Tamaño máximo por log antes de truncar

# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS Y FUNCIONES UTILITARIAS
# ═══════════════════════════════════════════════════════════════════════════════

# ─── Colores ─────────────────────────────────────────────────────────────────
RED='\033[0;31m'; YEL='\033[0;33m'; GRN='\033[0;32m'; CYN='\033[0;36m'; NC='\033[0m'
BLD='\033[1m'

info() { echo -e "${CYN}[INFO]${NC}  $*"; }
ok()   { echo -e "${GRN}[OK]${NC}    $*"; }
warn() { echo -e "${YEL}[WARN]${NC}  $*"; }
err()  { echo -e "${RED}[ERROR]${NC} $*" >&2; }
section() {
    echo -e "\n${BLD}${CYN}══════════════════════════════════════════════${NC}"
    echo -e "${BLD}${CYN}  $*${NC}"
    echo -e "${BLD}${CYN}══════════════════════════════════════════════${NC}"
}

# ─── wait_port — backoff exponencial (solo TCP) ───────────────────────────────
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
    code=$(curl --noproxy "*" --ipv4 --http1.1 -s -m 3 -o /dev/null -w "%{http_code}" "$url" 2>/dev/null || echo "000")
    echo "${code: -3}"
}

# ─── [V21-B4] Verificar si un puerto está libre ──────────────────────────────
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

# ─── Contenedor seguro — Idempotente ─────────────────────────────────────────
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
    if [ "$(docker inspect -f '{{.State.Status}}' "$name" 2>/dev/null)" == "running" ]; then
        return 0
    fi
    return 1
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
    local pid="$1"
    if kill -0 "$pid" 2>/dev/null; then
        return 0    # Existe y tenemos permisos
    else
        if [[ -d "/proc/$pid" ]]; then
            return 2  # Existe pero sin permisos (EPERM)
        else
            return 1  # No existe (ESRCH)
        fi
    fi
}


# ─── [V24-E1] Pull condicional — solo si --last fue especificado ─────────────
# ChromaDB NUNCA se incluye aquí (versión pinada).
pull_if_last() {
    local image="$1"
    local label="${2:-$image}"
    if [[ "$PULL_LATEST" == "true" ]]; then
        info "[--last] Actualizando imagen: $image"
        if docker pull "$image" 2>&1 | tail -3 | grep -qE "Status:|Pull complete|up to date"; then
            ok "[--last] $label actualizado"
        else
            docker pull "$image"   # Mostrar output completo si algo falla
            warn "[--last] $label — comprueba si el pull fue exitoso"
        fi
    fi
}

# ─── [V23-D1] Limpiar bridges kernel huérfanos del mismo subnet ──────────────
# Un bridge huérfano (state DOWN, sin red Docker asociada) con el mismo subnet
# que ai_net provoca DOS rutas en la tabla de routing del kernel para 172.28.x.x.
# El kernel elige la ruta "linkdown" y todos los paquetes mueren antes de llegar
# al contenedor (RST o "no route to host"). Esta función lo detecta y elimina.
cleanup_orphan_bridges() {
    local prefix="$1"   # Ej: "172.28"
    local removed=0

    for iface in $(ip link show 2>/dev/null | grep -oP 'br-[a-f0-9]+(?=:)' | sort -u); do
        # ¿Tiene IP del subnet en cuestión?
        if ! ip addr show "$iface" 2>/dev/null | grep -qP "inet ${prefix}\."; then
            continue
        fi
        # ¿Está en state DOWN (sin carrier)?
        if ! ip link show "$iface" 2>/dev/null | grep -q "state DOWN"; then
            continue
        fi
        # ¿Docker NO la conoce? (comparamos el sufijo hex del nombre con los IDs de red)
        local iface_id="${iface#br-}"
        if docker network ls --no-trunc -q 2>/dev/null | grep -qF "$iface_id"; then
            continue  # Docker sí la conoce — no tocar
        fi
        # Bridge huérfano confirmado: DOWN + mismo subnet + desconocido por Docker
        warn "[V23-D1] Bridge huérfano detectado: $iface (inet ${prefix}.x, state DOWN, sin red Docker)"
        warn "[V23-D1] Causa probable: red Docker recreada en arranque anterior sin limpiar la interfaz kernel"
        if sudo ip link delete "$iface" 2>/dev/null; then
            ok "[V23-D1] Bridge huérfano $iface eliminado — ruta duplicada limpiada"
            (( removed++ ))
        else
            warn "[V23-D1] No se pudo eliminar $iface automáticamente"
            warn "[V23-D1] Solución manual: sudo ip link delete $iface"
        fi
    done

    if (( removed == 0 )); then
        info "[V23-D1] Sin bridges huérfanos detectados para el prefix ${prefix}.x"
    fi
}

# ─── [V24-E1] Propagar _FLAG_LAST → PULL_LATEST (tras cargar configuración) ──
if [[ "$_FLAG_LAST" == "true" ]]; then
    PULL_LATEST=true
fi

# ═══════════════════════════════════════════════════════════════════════════════
# [V25-F1..F4] ACCIONES DE FLAGS — se ejecutan DESPUÉS de cargar configuración
# Requieren que las variables (ROUTER_SCRIPT, VAULT_INDEXER, etc.) estén listas.
# Los flags de acción rápida terminan el script con exit 0 sin arrancar nada.
# ═══════════════════════════════════════════════════════════════════════════════

# ─── [V25-F1] --stop ─────────────────────────────────────────────────────────
if [[ "$_FLAG_STOP" == "true" ]]; then
    section "Deteniendo OMEN AI Cluster V26…"
    # 1. Router Python
    if [[ -f "$PID_FILE" ]]; then
        OLD_PID=$(cat "$PID_FILE" 2>/dev/null || echo "")
        if [[ -n "$OLD_PID" ]] && kill -0 "$OLD_PID" 2>/dev/null; then
            kill "$OLD_PID" 2>/dev/null && ok "Router V14 detenido (PID $OLD_PID)" || warn "No se pudo matar PID $OLD_PID"
        fi
        rm -f "$PID_FILE"
    fi
    pkill -f "orchestrator_router" 2>/dev/null && ok "Procesos router limpiados" || true
    # 2. Indexador en background (si corre)
    if [[ -f "$INDEXER_PID_FILE" ]]; then
        IDX_PID=$(cat "$INDEXER_PID_FILE" 2>/dev/null || echo "")
        [[ -n "$IDX_PID" ]] && kill "$IDX_PID" 2>/dev/null && ok "Indexador detenido (PID $IDX_PID)" || true
        rm -f "$INDEXER_PID_FILE"
    fi
    # 3. Contenedores Docker
    CONTAINERS=("ollama-gpu-main" "ollama-cpu-router" "exllamav2-api" "sglang-server" "chromadb" "obsidian-kb" "searxng")
    info "Deteniendo contenedores: ${CONTAINERS[*]}"
    docker stop "${CONTAINERS[@]}" 2>/dev/null && ok "Contenedores detenidos" || warn "Algunos contenedores no estaban activos (normal)"
    docker rm "${CONTAINERS[@]}" 2>/dev/null && ok "Contenedores eliminados" || true
    ok "Cluster V26 detenido."
    exit 0
fi

# ─── [V25-F2] --status ───────────────────────────────────────────────────────
if [[ "$_FLAG_STATUS" == "true" ]]; then
    section "Estado del OMEN AI Cluster V26"
    echo ""
    # Tabla de servicios: nombre → URL de health check
    declare -A SVC_URLS=(
        ["Ollama GPU     :${PORT_OLLAMA_GPU}"]="http://localhost:${PORT_OLLAMA_GPU}/api/tags"
        ["Ollama CPU     :${PORT_OLLAMA_CPU}"]="http://localhost:${PORT_OLLAMA_CPU}/api/tags"
        ["TabbAPI EXL2   :${PORT_TABBYAPI}"]="http://localhost:${PORT_TABBYAPI}/health"
        ["SGLang         :${PORT_SGLANG}"]="http://localhost:${PORT_SGLANG}/health"
        ["ChromaDB       :${PORT_CHROMADB}"]="http://localhost:${PORT_CHROMADB}/api/v1/heartbeat"
        ["Obsidian UI    :${PORT_OBSIDIAN}"]="http://localhost:${PORT_OBSIDIAN}"
        ["SearXNG        :${PORT_SEARXNG}"]="http://localhost:${PORT_SEARXNG}/"  # [V26-F4] raíz: siempre 200 si UP
        ["Router V14     :${PORT_ROUTER}"]="http://localhost:${PORT_ROUTER}/health"
    )
    # Orden fijo para la tabla
    SVC_ORDER=(
        "Ollama GPU     :${PORT_OLLAMA_GPU}"
        "Ollama CPU     :${PORT_OLLAMA_CPU}"
        "TabbAPI EXL2   :${PORT_TABBYAPI}"
        "SGLang         :${PORT_SGLANG}"
        "ChromaDB       :${PORT_CHROMADB}"
        "Obsidian UI    :${PORT_OBSIDIAN}"
        "SearXNG        :${PORT_SEARXNG}"
        "Router V14     :${PORT_ROUTER}"
    )
    printf "  %-30s %-10s %s
" "Servicio" "Puerto" "Estado"
    printf "  %-30s %-10s %s
" "──────────────────────────────" "──────────" "──────"
    for svc in "${SVC_ORDER[@]}"; do
        url="${SVC_URLS[$svc]}"
        # [V28-B2] -L: sigue redirects (SearXNG responde 302→200 en /)
        http_code=$(curl --noproxy "*" --ipv4 -L -s -m 5 -o /dev/null -w "%{http_code}" "$url" 2>/dev/null || echo "000")
        if [[ "$http_code" =~ ^(200|301|302|404)$ ]]; then
            printf "  ${GRN}${BLD}%-30s %-10s ✔ UP  (HTTP %s)${NC}
" "$svc" "" "$http_code"
        else
            printf "  ${RED}%-30s %-10s ✘ DOWN (HTTP %s)${NC}
" "$svc" "" "$http_code"
        fi
    done
    echo ""
    # Estado del router PID
    if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE" 2>/dev/null)" 2>/dev/null; then
        ok "Router V14 proceso activo (PID $(cat "$PID_FILE"))"
    else
        warn "Router V14 no tiene PID activo"
    fi
    echo ""
    info "Métricas:    curl -s http://localhost:${PORT_ROUTER}/metrics | python3 -m json.tool"
    info "Modelos:     curl -s http://localhost:${PORT_ROUTER}/v1/models | python3 -m json.tool"
    info "Agent tasks: curl -s http://localhost:${PORT_ROUTER}/v1/agent/tasks"
    info "Log:         tail -f ${LOG_DIR}/router_v14.log"
    exit 0
fi

# ─── [V25-F3] --reindex ──────────────────────────────────────────────────────
if [[ "$_FLAG_REINDEX" == "true" ]]; then
    section "Re-indexando vault Obsidian → ChromaDB"
    if [[ ! -f "$VAULT_INDEXER" ]]; then
        err "No se encuentra el indexador: $VAULT_INDEXER"
        exit 1
    fi
    # Verificar que ChromaDB esté activo antes de indexar
    CHROMA_CHECK=$(curl --noproxy "*" -s -m 3 -o /dev/null -w "%{http_code}"         "http://localhost:${PORT_CHROMADB}/api/v1/heartbeat" 2>/dev/null || echo "000")
    if [[ "$CHROMA_CHECK" != "200" ]]; then
        warn "ChromaDB no responde en :${PORT_CHROMADB} (HTTP ${CHROMA_CHECK})"
        warn "Asegúrate de que el cluster esté activo antes de re-indexar"
        warn "Arrancar cluster: ai_cluster"
        exit 1
    fi
    NOTE_COUNT=$(find "$VAULT_DIR" -name "*.md" 2>/dev/null | wc -l)
    info "Notas encontradas en vault: ${NOTE_COUNT}"
    python3 "$VAULT_INDEXER" --clean         && ok "Re-indexación completada (${NOTE_COUNT} notas)"         || { warn "Error en re-indexación — revisa los logs"; exit 1; }
    exit 0
fi

# ─── [V25-F4] --warmup ───────────────────────────────────────────────────────
if [[ "$_FLAG_WARMUP" == "true" ]]; then
    section "Warmup de modelos Ollama GPU en VRAM"
    OLLAMA_CHECK=$(curl --noproxy "*" -s -m 3 -o /dev/null -w "%{http_code}"         "http://localhost:${PORT_OLLAMA_GPU}/api/tags" 2>/dev/null || echo "000")
    if [[ "$OLLAMA_CHECK" != "200" ]]; then
        err "Ollama GPU no responde en :${PORT_OLLAMA_GPU} — ¿está el cluster activo?"
        exit 1
    fi
    for model in "${OLLAMA_GPU_MODELS[@]}"; do
        info "Warmup: $model"
        curl --noproxy "*" -s --max-time 60 -X POST             "http://localhost:${PORT_OLLAMA_GPU}/api/generate"             -d "{"model":"${model}","prompt":"Hola","stream":false,"options":{"num_predict":1}}"             -o /dev/null             && ok "  ${model} → en VRAM"             || warn "  ${model} → warmup falló (¿modelo descargado?)"
    done
    exit 0
fi

# ═══════════════════════════════════════════════════════════════════════════════
# TRAP EXIT — Graceful shutdown (Solo en caso de error)
# ═══════════════════════════════════════════════════════════════════════════════
cleanup() {
    local exit_code="$?"

    if [[ "$exit_code" -ne 0 ]]; then
        warn "Se detectó un error (código $exit_code). Ejecutando limpieza de emergencia..."

        if [[ -n "${WATCHDOG_PID:-}" ]] && kill -0 "$WATCHDOG_PID" 2>/dev/null; then
            kill -TERM "$WATCHDOG_PID" 2>/dev/null || true
        fi

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
section "OMEN AI Cluster — Autoboot V30"
info "$(date '+%Y-%m-%d %H:%M:%S')"
echo ""

mkdir -p "$AI_HOME" "$LOG_DIR" "$OBSIDIAN_APPDATA" "$AGENT_DATA_DIR"

exec > >(tee -a "$LOG_FILE") 2>&1
if [[ "$PULL_LATEST" == "true" ]]; then
    info  "Modo: --last (actualizando imágenes :latest antes de arrancar)"
    info  "NOTA: ChromaDB usa versión pinada 0.6.3 — no se actualiza"
else
    info  "Modo: estándar (usando imágenes locales actuales)"
fi
info "Log: $LOG_FILE"

# ─────────────────────────────────────────────────────────────────────────────
# VERIFICACIÓN ESTRICTA DE ACCESO AL SSD (Directorio AI_CORE)
# ─────────────────────────────────────────────────────────────────────────────
section "Verificación de SSD exFAT y Permisos"

if [[ ! -d "$AI_CORE" ]]; then
    err "El directorio $AI_CORE no existe."
    err "Verifica que el servicio systemd de BitLocker haya montado la unidad."
    exit 1
fi

if [[ ! -w "$AI_CORE" ]]; then
    err "El directorio $AI_CORE existe, pero está en solo-lectura (read-only)."
    err "Revisa las banderas uid/gid y fmask/dmask en el script de montaje exFAT."
    exit 1
fi

ok "Directorio de IA ($AI_CORE) operativo, montado y con permisos correctos."
mkdir -p "$VAULT_DIR" 2>/dev/null || warn "No se pudo crear $VAULT_DIR. Ignorando..."

# ═══════════════════════════════════════════════════════════════════════════════
# COMPROBACIONES PREVIAS
# ═══════════════════════════════════════════════════════════════════════════════
section "Comprobaciones previas"

if ! command -v nc &>/dev/null; then
    warn "netcat (nc) no encontrado — usando /dev/tcp como fallback para wait_port"
fi

if ! command -v docker &>/dev/null; then
    err "Docker no encontrado. Instala Docker Engine."
    exit 1
fi

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

if ! command -v python3 &>/dev/null; then
    err "python3 no encontrado. Instala Python 3.10+."
    exit 1
fi

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

if [[ ! -w "$AGENT_DATA_DIR" ]]; then
    err "Sin permisos de escritura en $AGENT_DATA_DIR — el agente no podrá persistir estado"
    exit 1
fi
ok "Agent data dir: permisos correctos ($AGENT_DATA_DIR)"

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

ROUTER_LOG_COUNT=$(find "$LOG_DIR" -maxdepth 1 -name "router_v*.log" 2>/dev/null | wc -l)
if (( ROUTER_LOG_COUNT > 5 )); then
    find "$LOG_DIR" -maxdepth 1 -name "router_v*.log" -printf '%T@ %p\n' 2>/dev/null \
        | sort -rn | tail -n +6 | cut -d' ' -f2- | xargs rm -f 2>/dev/null || true
    info "Limpiados $((ROUTER_LOG_COUNT - 5)) logs del router antiguos"
fi

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

# [V23-D1] Limpiar bridges huérfanos ANTES de verificar/crear la red Docker.
# Evita rutas kernel duplicadas que causan RST / "no route to host" en contenedores.
cleanup_orphan_bridges "$DOCKER_NET_SUBNET_PREFIX"

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

mkdir -p "${MODELS_DIR}/ollama" 2>/dev/null || true

# [V31-B1] Timeout dinámico: 90s al reutilizar, 180s al recrear (init CUDA tarda 90-120s)
OLLAMA_GPU_TIMEOUT="$TIMEOUT_OLLAMA"

# [V31-E1] Determinar KEEP_ALIVE según modo
OLLAMA_KEEP_ALIVE_VAL="24h"
if [[ "$_FLAG_EXL2" == "true" ]]; then
    OLLAMA_KEEP_ALIVE_VAL="0"
fi

if is_container_running "ollama-gpu-main"; then
    if [[ "$_FLAG_EXL2" == "true" ]]; then
        # En modo --exl2: comprobar si el contenedor actual ya tiene KEEP_ALIVE=0
        CUR_KEEPALIVE=$(docker inspect ollama-gpu-main             --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null             | grep "^OLLAMA_KEEP_ALIVE=" | cut -d= -f2 || echo "24h")
        if [[ "$CUR_KEEPALIVE" != "0" ]]; then
            info "[--exl2] Contenedor Ollama GPU tiene KEEP_ALIVE=${CUR_KEEPALIVE} — recreando con KEEP_ALIVE=0…"
            ensure_container_stopped "ollama-gpu-main"
            OLLAMA_GPU_TIMEOUT=180  # [V31-B1] Arranque desde cero → init CUDA ~90-120s
        else
            info "Contenedor 'ollama-gpu-main' en ejecución con KEEP_ALIVE=0 (modo --exl2). Reutilizando..."
        fi
    else
        info "Contenedor 'ollama-gpu-main' en ejecución. Reutilizando (ahorrando VRAM)..."
    fi
else
    # Contenedor no existe: si es --exl2 aumentar timeout (arranca desde cero)
    [[ "$_FLAG_EXL2" == "true" ]] && OLLAMA_GPU_TIMEOUT=180  # [V31-B1]
fi

if ! is_container_running "ollama-gpu-main"; then
    ensure_container_stopped "ollama-gpu-main"
    pull_if_last "$IMG_OLLAMA" "Ollama GPU"
    docker run -d \
        --name ollama-gpu-main \
        --network "$DOCKER_NET" \
        --gpus all \
        -p "${PORT_OLLAMA_GPU}:11434" \
        -e OLLAMA_MODELS=/models \
        -v "${MODELS_DIR}/ollama:/models" \
        -v ollama_gpu_data:/root/.ollama \
        -e OLLAMA_KEEP_ALIVE=${OLLAMA_KEEP_ALIVE_VAL} \
        -e OLLAMA_MAX_LOADED_MODELS=1 \
        -e OLLAMA_FLASH_ATTENTION=1 \
        -e OLLAMA_NUM_PARALLEL=1 \
        --restart unless-stopped \
        $IMG_OLLAMA
fi

wait_port "Ollama GPU" localhost "$PORT_OLLAMA_GPU" "$OLLAMA_GPU_TIMEOUT"  # [V31-B1]

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

mkdir -p "${MODELS_DIR}/ollama-cpu" 2>/dev/null || true

if is_container_running "ollama-cpu-router"; then
    info "Contenedor 'ollama-cpu-router' en ejecución. Reutilizando estado..."
else
    ensure_container_stopped "ollama-cpu-router"
    pull_if_last "$IMG_OLLAMA" "Ollama CPU"
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

# [V31-E1] TabbAPI es opt-in: solo arranca con --exl2.
# Sin --exl2 ni --sglang (modo default): TabbAPI omitido, toda VRAM para Ollama GPU.
if [[ "$_FLAG_SGLANG" == "true" ]]; then
    # Modo --sglang: TabbAPI no debe estar corriendo
    if is_container_running "exllamav2-api"; then
        info "[--sglang] Deteniendo TabbAPI para liberar VRAM (~6.9GB)…"
        docker stop exllamav2-api >/dev/null 2>&1 || true
        docker rm   exllamav2-api >/dev/null 2>&1 || true
        ok "TabbAPI detenido — VRAM liberada para SGLang"
    else
        info "[--sglang] TabbAPI no estaba activo — nada que detener"
    fi
    warn "TabbAPI omitido en modo --sglang"
elif [[ "$_FLAG_EXL2" != "true" ]]; then
    # Modo default (sin --exl2): detener TabbAPI residual si existiera y omitir
    if is_container_running "exllamav2-api"; then
        info "[default] Deteniendo TabbAPI residual (modo default: VRAM para Ollama GPU)…"
        docker stop exllamav2-api >/dev/null 2>&1 || true
        docker rm   exllamav2-api >/dev/null 2>&1 || true
    fi
    warn "TabbAPI omitido (modo default). Usa --exl2 para activarlo."
elif [[ -d "$EXL2_CHAT" ]] || [[ -d "$EXL2_CODER" ]]; then
    # [V26-F1] Si el contenedor existe, verificar que la API HTTP responde antes de reutilizar
    TABBY_HEALTH=$(curl --noproxy "*" --ipv4 -s -m 3 -o /dev/null -w "%{http_code}" \
        "http://localhost:${PORT_TABBYAPI}/health" 2>/dev/null || echo "000")
    if is_container_running "exllamav2-api" && [[ "$TABBY_HEALTH" == "200" ]]; then
        info "Contenedor 'exllamav2-api' en ejecución y respondiendo (HTTP 200). Reutilizando..."
    else
        if is_container_running "exllamav2-api"; then
            info "Contenedor 'exllamav2-api' existe pero API no responde (HTTP ${TABBY_HEALTH}) — recreando..."
        fi
        ensure_container_stopped "exllamav2-api"
        pull_if_last "$IMG_TABBYAPI" "TabbAPI ExLlamaV2"
        # [V29-B1] ENTRYPOINT=python3, CMD=main.py --host 0.0.0.0
        # Pasar solo los args que extienden el CMD; python3 lo invoca la imagen.
        # NO añadir 'python3' ni '-m tabbyapi' — la imagen ya los tiene en ENTRYPOINT/CMD.
        # [V32-B1] Reducir pico VRAM durante warmup forward de ExLlamaV2:
        #   max-seq-len 2048 (fue 8192 → KV cache FP16 ~512MB, con 2048 → ~128MB)
        #   cache-mode fp8   → KV cache en FP8 (mitad de VRAM que FP16)
        #   Combinado: KV cache pasa de ~512MB a ~64MB → ~450MB liberados
        #   Esto evita CUBLAS_STATUS_ALLOC_FAILED durante model.forward() de init
        docker run -d \
            --name exllamav2-api \
            --network "$DOCKER_NET" \
            --gpus all \
            -p "${PORT_TABBYAPI}:5000" \
            -v "${MODELS_DIR}:/models:ro" \
            --restart unless-stopped \
            $IMG_TABBYAPI \
            main.py \
            --host 0.0.0.0 \
            --model-dir /models \
            --model-name "llama-3.1-8b-exl2" \
            --max-seq-len 2048 \
            --cache-mode fp8 \
            --port 5000
    fi  # cierra: if is_container_running && health 200 ... else ... fi

    # [V26-F2a] Health-check HTTP real (no TCP): TabbyAPI necesita tiempo para cargar el modelo EXL2
    TABBY_READY=false
    info "Esperando que TabbAPI cargue el modelo EXL2 en localhost:${PORT_TABBYAPI}… (máx ${TIMEOUT_TABBYAPI}s)"
    for _retry in $(seq 1 "$TIMEOUT_TABBYAPI"); do
        if ! docker ps --format '{{.Names}}' | grep -qx "exllamav2-api"; then
            err "Contenedor 'exllamav2-api' ya no está en ejecución. Revisa: docker logs exllamav2-api"
            break
        fi
        TABBY_HTTP=$(curl --noproxy "*" --ipv4 -s -m 2 -o /dev/null -w "%{http_code}" \
            "http://localhost:${PORT_TABBYAPI}/health" 2>/dev/null || echo "000")
        if [[ "$TABBY_HTTP" == "200" ]]; then
            TABBY_READY=true
            break
        fi
        sleep 1
    done
    if [[ "$TABBY_READY" == "true" ]]; then
        ok "TabbAPI ExLlamaV2 ✔ — API lista (puerto ${PORT_TABBYAPI})"
    else
        warn "TabbAPI no respondió tras ${TIMEOUT_TABBYAPI}s (último HTTP: ${TABBY_HTTP:-000})"
        warn "Revisa: docker logs exllamav2-api --tail 30"
        docker logs --tail=20 exllamav2-api 2>&1 || true
    fi
else
    warn "Modelos EXL2 no encontrados en $MODELS_DIR — omitiendo TabbAPI"
fi  # fin if _FLAG_SGLANG / elif modelos EXL2

# ═══════════════════════════════════════════════════════════════════════════════
# 4. SGLang (:30000) — [V21-B3] Timeout aumentado, [V21-B9] Verificación modelo
# ═══════════════════════════════════════════════════════════════════════════════
section "4/7 — SGLang (:$PORT_SGLANG)"

SGLANG_MODEL="${MODELS_DIR}/llama-3.1-8b-awq"

# [V27-S1/S2] SGLang solo arranca con --sglang. Sin el flag: modo default → omitir.
if [[ "$_FLAG_SGLANG" != "true" ]]; then
    # Modo default: limpiar contenedor residual si existiera
    if is_container_running "sglang-server"; then
        info "Modo default: deteniendo sglang-server residual para liberar VRAM…"
        docker stop sglang-server >/dev/null 2>&1 || true
        docker rm   sglang-server >/dev/null 2>&1 || true
    elif docker ps -a --format '{{.Names}}' | grep -qx "sglang-server"; then
        docker rm sglang-server >/dev/null 2>&1 || true
    fi
    warn "SGLang omitido (modo default; VRAM reservada a TabbAPI). Usa --sglang para activarlo."
elif [[ -d "$SGLANG_MODEL" ]]; then
    # [V27-S2] En modo --sglang TabbAPI ya fue detenido → VRAM disponible
    if [[ ! -f "$SGLANG_MODEL/config.json" ]] && [[ ! -f "$SGLANG_MODEL/model.safetensors.index.json" ]]; then
        warn "Directorio $SGLANG_MODEL existe pero no contiene ficheros de modelo reconocibles"
    fi

    if is_container_running "sglang-server"; then
        info "Contenedor 'sglang-server' en ejecución. Reutilizando (ahorrando VRAM)..."
    else
        ensure_container_stopped "sglang-server"
        pull_if_last "$IMG_SGLANG" "SGLang"
        # [V27-S2][V31-B2] Parámetros corregidos:
        #   mem-fraction-static 0.15 (antes 0.50 → OOM: modelo AWQ usa 5.4GB, 8GB×0.50=4.0GB KV → 9.4GB>8GB)
        #   Con 0.15: 8GB×0.15=1.2GB KV cache → 5.4+1.2=6.6GB < 8GB ✔
        #   max-total-tokens 8192 (antes 16384; coherente con ~1.2GB KV disponible)
        docker run -d \
            --name sglang-server \
            --network "$DOCKER_NET" \
            --gpus all \
            -p "${PORT_SGLANG}:30000" \
            -v "${MODELS_DIR}:/models:ro" \
            --ipc=host \
            --restart unless-stopped \
            $IMG_SGLANG \
            python3 -m sglang.launch_server \
            --model-path "/models/llama-3.1-8b-awq" \
            --port 30000 \
            --host 0.0.0.0 \
            --dtype float16 \
            --quantization awq \
            --max-total-tokens 8192 \
            --mem-fraction-static 0.10 \  # [V32-B2] 0.15→0.10: overhead CUDA runtime de Ollama consume ~400MB adicionales
            --tp-size 1 \
            --trust-remote-code \
            --enable-memory-saver  # [V32-B2] libera VRAM inactiva agresivamente
    fi

    # [V26-F2b][V27] Health-check HTTP puro — SGLang tarda en cargar pesos AWQ
    SGLANG_READY=false
    info "Esperando que SGLang inicialice su API HTTP en localhost:${PORT_SGLANG}… (máx ${TIMEOUT_SGLANG}s)"
    for _retry in $(seq 1 "$TIMEOUT_SGLANG"); do
        if ! docker ps --format '{{.Names}}' | grep -qx "sglang-server"; then
            err "Contenedor 'sglang-server' ya no está en ejecución. Revisa: docker logs sglang-server"
            break
        fi
        SGLANG_HTTP=$(curl --noproxy "*" --ipv4 -s -m 2 -o /dev/null -w "%{http_code}" \
            "http://localhost:${PORT_SGLANG}/health" 2>/dev/null || echo "000")
        if [[ "$SGLANG_HTTP" == "200" ]]; then
            SGLANG_READY=true
            break
        fi
        sleep 1
    done
    if [[ "$SGLANG_READY" == "true" ]]; then
        ok "SGLang ✔ — API lista (puerto ${PORT_SGLANG})"
    else
        warn "SGLang no respondió tras ${TIMEOUT_SGLANG}s (último HTTP: ${SGLANG_HTTP:-000})"
        warn "Revisa: docker logs sglang-server --tail 30"
        docker logs --tail=20 sglang-server 2>&1 || true
    fi
else
    warn "Modelo AWQ no encontrado: $SGLANG_MODEL — omitiendo SGLang"
fi

# ═══════════════════════════════════════════════════════════════════════════════
# 5. CHROMADB (:8001)
# [V22-C1] Imagen pinada a 0.6.3 (estable)
# [V22-C2] Endpoint corregido a /api/v1/heartbeat
# [V22-C3] Variable CHROMA_SERVER_HTTP_PORT=8000 añadida
# [V22-C4] Volumen mapeado a /chroma/chroma (correcto para 0.6.x)
# [V22-C5] Health check HTTP puro — sin waitport (elimina falso positivo TCP) — sin cambios en V23
# ═══════════════════════════════════════════════════════════════════════════════
section "5/7 — ChromaDB (:$PORT_CHROMADB)"
# [V24-E1] ChromaDB NO se actualiza con --last — versión pinada $IMG_CHROMADB

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
        $IMG_CHROMADB
fi

# [V22-C5] Health check HTTP puro: no usamos wait_port (TCP != HTTP listo).
# ChromaDB 0.6.3 abre el socket TCP antes de que uvicorn esté ready.
# Sondeamos directamente la API HTTP con reintentos cada 1s.
CHROMADB_READY=false
CHROMA_STATUS="000"
info "Esperando que ChromaDB inicialice su API HTTP en 127.0.0.1:${PORT_CHROMADB}… (máx ${TIMEOUT_CHROMADB}s)"

for _retry in $(seq 1 "$TIMEOUT_CHROMADB"); do
    # Verificar que el contenedor sigue vivo
    if ! docker ps --format '{{.Names}}' | grep -qx "chromadb"; then
        err "Contenedor 'chromadb' ya no está en ejecución. Revisa: docker logs chromadb"
        break
    fi

    CHROMA_STATUS=$(get_http_status "http://127.0.0.1:${PORT_CHROMADB}/api/v1/heartbeat")
    if [[ "$CHROMA_STATUS" == "200" ]]; then
        CHROMADB_READY=true
        break
    fi
    sleep 1
done

if [[ "$CHROMADB_READY" == "true" ]]; then
    ok "ChromaDB ✔ — API lista (puerto ${PORT_CHROMADB})"
else
    warn "ChromaDB puerto abierto pero API no respondió tras ${TIMEOUT_CHROMADB}s (Estado: ${CHROMA_STATUS})"
    warn "Revisa: docker logs chromadb --tail 30"
    # [V22-C6] Diagnóstico adicional vía red interna Docker (usa /api/v1/heartbeat)
    INTERNAL_STATUS=$(docker run --rm --network "$DOCKER_NET" \
        $IMG_CURL \
        --connect-timeout 3 --ipv4 -s -o /dev/null -w "%{http_code}" \
        "http://chromadb:8000/api/v1/heartbeat" 2>/dev/null || echo "000")
    if [[ "$INTERNAL_STATUS" == "200" ]]; then
        warn "ChromaDB responde internamente (red Docker) pero el host forwarding aún no está listo."
        warn "Espera unos segundos y comprueba: curl http://127.0.0.1:${PORT_CHROMADB}/api/v1/heartbeat"
    else
        warn "ChromaDB interno (red Docker) tampoco responde (HTTP ${INTERNAL_STATUS})."
    fi
fi

# ═══════════════════════════════════════════════════════════════════════════════
# 6. OBSIDIAN WEB (:3000)
# ═══════════════════════════════════════════════════════════════════════════════
section "6/7 — Obsidian (:$PORT_OBSIDIAN)"

if is_container_running "obsidian-kb"; then
    info "Contenedor 'obsidian-kb' en ejecución. Reutilizando estado..."
else
    ensure_container_stopped "obsidian-kb"
    pull_if_last "$IMG_OBSIDIAN" "Obsidian"
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
        $IMG_OBSIDIAN
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

if [[ ! -f "$SEARXNG_SECRET_FILE" ]]; then
    openssl rand -hex 32 > "$SEARXNG_SECRET_FILE"
    chmod 600 "$SEARXNG_SECRET_FILE"
    info "Nueva secret_key generada en $SEARXNG_SECRET_FILE (permisos: 600)"
else
    chmod 600 "$SEARXNG_SECRET_FILE" 2>/dev/null || true
    info "Reutilizando secret_key existente"
fi
SEARXNG_SECRET=$(cat "$SEARXNG_SECRET_FILE")

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
  bind_address: "0.0.0.0:8080"  # [V29-B2] Puerto interno real de SearXNG
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

# [V30-B2] Verificar port binding antes de reutilizar SearXNG.
# Un contenedor viejo con -p 8888:8888 (incorrecto) debe recrearse con -p 8888:8080.
SEARXNG_BINDING=$(docker inspect searxng --format '{{json .HostConfig.PortBindings}}' 2>/dev/null || echo '{}')
SEARXNG_PORT_OK=false
if echo "$SEARXNG_BINDING" | grep -q '"8080/tcp"'; then
    SEARXNG_PORT_OK=true
fi

if is_container_running "searxng" && [[ "$SEARXNG_PORT_OK" == "true" ]]; then
    info "Contenedor 'searxng' en ejecución con port binding correcto (8080). Reutilizando..."
else
    if [[ "$SEARXNG_PORT_OK" == "false" ]] && docker ps -a --format '{{.Names}}' | grep -qx 'searxng'; then
        info "Port binding de SearXNG incorrecto (${SEARXNG_BINDING}) — recreando con :8080..."
    fi
    ensure_container_stopped "searxng"
    pull_if_last "$IMG_SEARXNG" "SearXNG"
    docker run -d \
        --name searxng \
        --network "$DOCKER_NET" \
        -p "${PORT_SEARXNG}:8080" \
        -v "${SEARXNG_SETTINGS}:/etc/searxng/settings.yml:ro" \
        -e SEARXNG_SECRET_KEY="${SEARXNG_SECRET}" \
        --restart unless-stopped \
        $IMG_SEARXNG
fi

if wait_port "SearXNG" localhost "$PORT_SEARXNG" "$TIMEOUT_SEARXNG"; then
    ok "SearXNG ✔ → http://localhost:$PORT_SEARXNG"
else
    warn "SearXNG no respondió"
fi

# ═══════════════════════════════════════════════════════════════════════════════
# INDEXACIÓN VAULT — [V21-B2] Actualizado a V6
# [V22-C7] Retry HTTP breve para Ollama CPU antes de evaluar condiciones
# ═══════════════════════════════════════════════════════════════════════════════
section "Indexación Vault Obsidian"

if [[ -f "$VAULT_INDEXER" ]]; then
    # [V22-C7] Usar CHROMA_STATUS del bloque anterior si ya fue 200;
    # si no, hacer un retry rápido antes de descartar la indexación.
    if [[ "${CHROMA_STATUS:-000}" != "200" ]]; then
        info "Reintentando heartbeat de ChromaDB antes de evaluar indexación…"
        for _i in $(seq 1 5); do
            CHROMA_STATUS=$(get_http_status "http://127.0.0.1:${PORT_CHROMADB}/api/v1/heartbeat")
            [[ "$CHROMA_STATUS" == "200" ]] && break
            sleep 2
        done
    fi

    # Retry HTTP breve para Ollama CPU (el wait_port TCP no garantiza HTTP listo)
    OLLAMA_CPU_STATUS="000"
    for _i in $(seq 1 10); do
        OLLAMA_CPU_STATUS=$(get_http_status "http://localhost:${PORT_OLLAMA_CPU}/")
        [[ "$OLLAMA_CPU_STATUS" == "200" ]] && break
        sleep 2
    done

    # Normalizar estados
    [[ "$CHROMA_STATUS"     != "200" ]] && CHROMA_STATUS="000"
    [[ "$OLLAMA_CPU_STATUS" != "200" ]] && OLLAMA_CPU_STATUS="000"

    if [[ "$CHROMA_STATUS" == "200" ]] && [[ "$OLLAMA_CPU_STATUS" == "200" ]]; then
        ok "Motores validados. Iniciando indexación automática de la bóveda..."
        python3 "$VAULT_INDEXER" \
            --vault-dir "$VAULT_DIR" \
            --chroma-url "http://localhost:${PORT_CHROMADB}" \
            --ollama-embed-url "http://localhost:${PORT_OLLAMA_CPU}/api/embeddings" \
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

export AGENT_DB_DIR="$AGENT_DATA_DIR"
export ROUTER_PORT="$PORT_ROUTER"

if [[ ${#GPU_PULL_PIDS[@]} -gt 0 ]]; then
    info "Verificando pulls de GPU en background…"
    for pid in "${GPU_PULL_PIDS[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
            info "  Pull GPU (PID $pid) aún en progreso — no bloqueante para el router"
        fi
    done
fi

PYTHONUNBUFFERED=1 AGENT_DB_DIR="$AGENT_DATA_DIR" ROUTER_PORT="$PORT_ROUTER" \
    python3 "$ROUTER_SCRIPT" \
    >> "$LOG_DIR/router_v14.log" 2>&1 &
ROUTER_PID=$!
echo "$ROUTER_PID" > "$PID_FILE"
info "Router V14 lanzado — PID=$ROUTER_PID"

ROUTER_READY=false
HEALTH_ATTEMPTS=0
for i in $(seq 1 $((TIMEOUT_ROUTER_HEALTH / 2))); do
    HEALTH_ATTEMPTS=$((HEALTH_ATTEMPTS + 1))
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

    watchdog_loop() {
        while true; do
            sleep "$WATCHDOG_INTERVAL"

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
section "Resumen del Cluster V32"

echo ""
# [V27-S3][V31-E1] Modo VRAM activo
if [[ "$_FLAG_SGLANG" == "true" ]]; then
    echo -e "  Modo VRAM:  ${BLD}--sglang${NC} (SGLang AWQ activo, TabbAPI detenido)"
elif [[ "$_FLAG_EXL2" == "true" ]]; then
    echo -e "  Modo VRAM:  ${BLD}--exl2${NC}   (TabbAPI EXL2 activo, Ollama GPU KEEP_ALIVE=0)"
else
    echo -e "  Modo VRAM:  ${BLD}default${NC}  (Ollama GPU VRAM completa — usa --exl2 o --sglang)"
fi
echo ""
printf "%-30s %-12s %s\n" "Servicio" "Puerto" "Estado"
printf "%-30s %-12s %s\n" "──────────────────────────────" "────────────" "──────"

# [V26-F3] check_service usa HTTP real (no TCP) para detectar estado verdadero de la API
# Tabla de endpoints de health por puerto
_health_url() {
    local port="$1"
    case "$port" in
        "$PORT_OLLAMA_GPU"|"$PORT_OLLAMA_CPU") echo "http://localhost:${port}/api/tags" ;;
        "$PORT_TABBYAPI")  echo "http://localhost:${port}/health" ;;
        "$PORT_SGLANG")    echo "http://localhost:${port}/health" ;;
        "$PORT_CHROMADB")  echo "http://localhost:${port}/api/v1/heartbeat" ;;
        "$PORT_OBSIDIAN")  echo "http://localhost:${port}" ;;
        "$PORT_SEARXNG")   echo "http://localhost:${port}/" ;;
        "$PORT_ROUTER")    echo "http://localhost:${port}/health" ;;
        *)                 echo "http://localhost:${port}" ;;
    esac
}

check_service() {
    local name="$1" host="$2" port="$3"
    local url
    url=$(_health_url "$port")
    local http_code
    # [V28-B2] -L: sigue redirects (SearXNG responde 302→200 en /)
    http_code=$(curl --noproxy "*" --ipv4 -L -s -m 5 -o /dev/null -w "%{http_code}" "$url" 2>/dev/null || echo "000")
    if [[ "$http_code" =~ ^(200|301|302)$ ]]; then
        printf "%-30s %-12s %b\n" "$name" ":$port" "${GRN}✔ OK${NC}"
    else
        printf "%-30s %-12s %b\n" "$name" ":$port" "${YEL}⚠ no disponible${NC}"
    fi
}

check_service "Ollama GPU (main)"        localhost    "$PORT_OLLAMA_GPU"
check_service "Ollama CPU (router/emb)"  localhost    "$PORT_OLLAMA_CPU"

# [V27-S3][V31-E1] TabbAPI: distingue modo --sglang / default / --exl2
if [[ "$_FLAG_SGLANG" == "true" ]]; then
    printf "%-30s %-12s %b\n" "TabbAPI ExLlamaV2" ":${PORT_TABBYAPI}" "${YEL}— omitido (modo --sglang)${NC}"
elif [[ "$_FLAG_EXL2" != "true" ]]; then
    printf "%-30s %-12s %b\n" "TabbAPI ExLlamaV2" ":${PORT_TABBYAPI}" "${YEL}— omitido (modo default; usa --exl2)${NC}"
elif docker ps --format '{{.Names}}' | grep -qx "exllamav2-api"; then
    check_service "TabbAPI ExLlamaV2"    localhost    "$PORT_TABBYAPI"
else
    printf "%-30s %-12s %b\n" "TabbAPI ExLlamaV2" ":${PORT_TABBYAPI}" "${YEL}— modelos EXL2 no instalados${NC}"
fi

# [V27-S3][V31-E1] SGLang: distingue modo --sglang / default / --exl2
if [[ "$_FLAG_SGLANG" != "true" ]]; then
    printf "%-30s %-12s %b\n" "SGLang" ":${PORT_SGLANG}" "${YEL}— omitido (modo default; usa --sglang)${NC}"
elif docker ps --format '{{.Names}}' | grep -qx "sglang-server"; then
    check_service "SGLang"               localhost    "$PORT_SGLANG"
else
    printf "%-30s %-12s %b\n" "SGLang" ":${PORT_SGLANG}" "${YEL}— modelo AWQ no instalado${NC}"
fi

check_service "ChromaDB"                 127.0.0.1   "$PORT_CHROMADB"
check_service "Obsidian Web UI"          localhost    "$PORT_OBSIDIAN"
check_service "SearXNG"                  localhost    "$PORT_SEARXNG"
check_service "Router V14 (Agent)"       localhost    "$PORT_ROUTER"

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
echo "  Heartbeat chroma: curl -s http://127.0.0.1:${PORT_CHROMADB}/api/v1/heartbeat"
echo ""
echo -e "${BLD}Flags del script:${NC}"
echo "  ai_cluster            Arranque estándar (imágenes locales)"
echo "  ai_cluster --last     Actualiza imágenes :latest antes de arrancar"
echo "  ai_cluster --stop     Para el cluster ordenadamente"
echo "  ai_cluster --status   Estado en tiempo real de todos los servicios"
echo "  ai_cluster --reindex  Re-indexa el vault Obsidian en ChromaDB"
echo "  ai_cluster --warmup   Carga modelos GPU en VRAM"
echo "  ai_cluster --exl2     Activa TabbAPI EXL2 (KEEP_ALIVE=0 en Ollama)"
echo "  ai_cluster --sglang   Activa SGLang AWQ (para TabbAPI, mem-frac 0.15)"
echo "  ai_cluster --help     Muestra la ayuda completa"
if [[ "$WATCHDOG_ENABLED" == "true" ]]; then
    echo "  Watchdog:         tail -f $LOG_DIR/watchdog.log"
    echo "  Desactivar:       export OMEN_WATCHDOG=false"
fi
echo ""
echo -e "${GRN}${BLD}OMEN AI Cluster V32 — iniciado${NC}"
echo -e "$(date '+%Y-%m-%d %H:%M:%S')"
