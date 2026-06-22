#!/bin/bash
# ==============================================================================
# Script: listar_modelos.sh
# Descripción: Escanea y muestra todos los modelos de IA instalados en el cluster
#              Funciona tanto con Docker encendido (API) como apagado (Disco).
# ==============================================================================

# Ruta unificada según tu última estructura
MODELS_DIR="/home/fcela-ga/sgoinfre/ai_core/models"
OLLAMA_GPU_DIR="$MODELS_DIR/ollama"
OLLAMA_CPU_DIR="$MODELS_DIR/ollama-cpu"

# Colores
GREEN='\033[1;32m'
BLUE='\033[1;34m'
YELLOW='\033[1;33m'
CYAN='\033[1;36m'
NC='\033[0m'

echo -e "${CYAN}=================================================================${NC}"
echo -e "${CYAN}🧠 INVENTARIO TOTAL DE MODELOS (OMEN AI CLUSTER)${NC}"
echo -e "${CYAN}=================================================================${NC}"

# Función para escanear Ollama de forma inteligente (Online o Offline)
escanear_ollama() {
    local container_name=$1
    local disk_dir=$2
    local label=$3

    echo -e "\n${label}"
    
    # Intento 1: A través de Docker (Si está encendido, nos da tamaños exactos más rápido)
    if docker ps -q -f name="$container_name" >/dev/null 2>&1; then
        docker exec "$container_name" ollama list | awk 'NR>1 {printf "  ✔ %-35s | Tamaño: %s\n", $1, $2}'
    else
        # Intento 2: Escáner offline directo al disco duro (Bypass de Docker)
        echo -e "  ${YELLOW}[Contenedor apagado - Leyendo manifiestos del disco]${NC}"
        local manifests_dir="$disk_dir/manifests/registry.ollama.ai/library"
        
        if [ -d "$manifests_dir" ]; then
            local found=0
            # Iterar sobre las carpetas de modelos
            for model_dir in "$manifests_dir"/*; do
                [ -d "$model_dir" ] || continue
                local model_name=$(basename "$model_dir")
                
                # Iterar sobre los tags (latest, 14b, etc.)
                for tag_file in "$model_dir"/*; do
                    [ -f "$tag_file" ] || continue
                    local tag_name=$(basename "$tag_file")
                    printf "  ✔ %-35s | Estado: En disco\n" "${model_name}:${tag_name}"
                    found=1
                done
            done
            if [ $found -eq 0 ]; then
                echo "  [!] No hay modelos en el registro."
            fi
        else
            echo "  [!] Directorio de manifiestos no encontrado: $manifests_dir"
        fi
    fi
}

# 1. Escanear Ollama GPU
escanear_ollama "ollama-gpu-main" "$OLLAMA_GPU_DIR" "${GREEN}🟢 MOTOR: OLLAMA (GPU - Principal / Puerto 11434):${NC}"

# 2. Escanear Ollama CPU
escanear_ollama "ollama-cpu-router" "$OLLAMA_CPU_DIR" "${BLUE}🔵 MOTOR: OLLAMA (CPU - Clasificadores / Puerto 11435):${NC}"

# 3. Escanear Modelos Nativos (TabbAPI / SGLang)
echo -e "\n${YELLOW}⚡ MOTORES NATIVOS (ExLlamaV2 y SGLang / Descargas directas):${NC}"
if [ -d "$MODELS_DIR" ]; then
    local_found=0
    for d in "$MODELS_DIR"/*/; do
        [ -d "$d" ] || continue
        DIR_NAME=$(basename "$d")
        
        # Ignorar las carpetas de Ollama (ya procesadas) y directorios ocultos
        if [[ "$DIR_NAME" == "ollama" || "$DIR_NAME" == "ollama-cpu" || "$DIR_NAME" == .* ]]; then
            continue
        fi
        
        # Clasificar el motor según el formato
        if [[ "$DIR_NAME" == *"exl2"* || "$DIR_NAME" == *"exllamav2"* ]]; then
            MOTOR="TabbAPI (ExLlamaV2)"
        elif [[ "$DIR_NAME" == *"awq"* ]]; then
            MOTOR="SGLang (AWQ)"
        else
            MOTOR="Autodetectar"
        fi
        
        # Calcular tamaño real en disco
        SIZE=$(du -sh "$d" 2>/dev/null | cut -f1)
        printf "  ✔ %-35s | Motor: %-19s | Tamaño: %s\n" "$DIR_NAME" "$MOTOR" "$SIZE"
        local_found=1
    done
    
    if [ $local_found -eq 0 ]; then
        echo "  [!] No se encontraron modelos nativos (EXL2/AWQ) en $MODELS_DIR"
    fi
else
    echo "  [!] Error: No se encontró la ruta maestra: $MODELS_DIR"
fi

echo -e "\n${CYAN}=================================================================${NC}"