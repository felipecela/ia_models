#!/bin/bash
# ===== Archivo: Run_ExLlamaV2.sh =====

echo "=== ACTIVANDO ENTORNO: EXLLAMAV2 (TABBYAPI - AUTOCOMPLETADO) ==="

# 1. Bloque de Exclusión Mutua
echo "Liberando VRAM: Deteniendo servicios competitivos..."
sudo systemctl stop ollama 2>/dev/null && echo "✔ Servicio Ollama nativo detenido."
docker stop sglang-server 2>/dev/null && echo "✔ Contenedor SGLang detenido."

# 2. Lanzamiento o reinicio del contenedor ExLlamaV2
if [ "$(docker ps -aq -f name=exllamav2-api)" ]; then
    echo "Reiniciando contenedor existente..."
    docker start exllamav2-api
else
    echo "Creando y lanzando nuevo contenedor..."
    docker run -d --gpus all \
      --name exllamav2-api \
      --restart unless-stopped \
      -v /home/fcela-ga/sgoinfre/ai_core/exllamav2_storage:/models \
      -p 5000:5000 \
      berot3/tabbyapi:latest
fi

echo "------------------------------------------------"
echo "ExLlamaV2 operativo en http://localhost:5000"
echo "Modelos EXL2 listos para el autocompletado de Continue.dev."