#!/bin/bash
# ===== Archivo: Run_SGLang.sh =====

echo "=== ACTIVANDO ENTORNO: SGLANG (OPENCLAW AGENTES) ==="

# 1. Bloque de Exclusión Mutua
echo "Liberando VRAM: Deteniendo servicios competitivos..."
sudo systemctl stop ollama 2>/dev/null && echo "✔ Servicio Ollama nativo detenido."
docker stop exllamav2-api 2>/dev/null && echo "✔ Contenedor ExLlamaV2 detenido."

# 2. Lanzamiento o reinicio del contenedor SGLang apuntando al modelo real
if [ "$(docker ps -aq -f name=sglang-server)" ]; then
    echo "Reiniciando contenedor existente..."
    docker start sglang-server
else
    echo "Creando y lanzando nuevo contenedor con Llama-3.1-8B-AWQ..."
    docker run -d --gpus all \
      --name sglang-server \
      --restart unless-stopped \
      --ipc=host \
      -v /home/fcela-ga/sgoinfre/ai_core/sglang_storage:/models \
      -p 30000:30000 \
      lmsysorg/sglang:latest \
      python3 -m sglang.launch_server \
        --model-path /models/llama-3.1-8b-awq \
        --port 30000 \
        --host 0.0.0.0
fi

echo "------------------------------------------------"
echo "SGLang operativo en http://localhost:30000"
echo "Endpoint listo para conectar con el panel de OpenClaw."