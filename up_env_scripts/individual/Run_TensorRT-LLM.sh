#!/bin/bash
# ===== Archivo: Run_TensorRT-LLM.sh =====

echo "=== ACTIVANDO ENTORNO: TENSORRT-LLM (COMPILACIÓN/DESARROLLO) ==="

# 1. Bloque de Exclusión Mutua Absoluta
echo "Limpiando VRAM al 100%: Deteniendo todos los servicios..."
docker stop exllamav2-api 2>/dev/null && echo "✔ Contenedor ExLlamaV2 detenido."
docker stop sglang-server 2>/dev/null && echo "✔ Contenedor SGLang detenido."
sudo systemctl stop ollama 2>/dev/null && echo "✔ Servicio Ollama nativo detenido."

# 2. Orquestación del contenedor interactivo
echo "Iniciando entorno interactivo CUDA de TensorRT-LLM..."
echo "Tu almacenamiento está mapeado en /workspace dentro del contenedor."
echo "Escribe 'exit' para salir del entorno."
echo "------------------------------------------------"

# Comprobar si el contenedor ya existe para reiniciarlo, si no, lo crea de cero
if [ "$(docker ps -aq -f name=tensorrt-compiler)" ]; then
    docker start -ai tensorrt-compiler
else
    docker run -it --gpus all --ipc=host \
      --name tensorrt-compiler \
      -v /home/fcela-ga/sgoinfre/ai_core/tensorrt_storage:/workspace \
      nvidia/cuda:12.4.1-devel-ubuntu22.04 bash
fi