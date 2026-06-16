#!/bin/bash
# ===== Archivo: Run_OpenClaw.sh =====

echo "=== INSTALANDO Y ACTIVANDO OPENCLAW (INTERFAZ Y AGENTES) ==="

# 1. Crear la carpeta para la memoria persistente de los agentes en tu SSD
echo "Preparando volumen de almacenamiento en ai_core..."
mkdir -p /home/fcela-ga/sgoinfre/ai_core/openclaw_storage

# 2. Descargar y levantar el contenedor todo-en-uno de OpenClaw
if [ "$(docker ps -aq -f name=openclaw-server)" ]; then
    echo "Reiniciando contenedor existente de OpenClaw..."
    docker start openclaw-server
else
    echo "Descargando e instalando OpenClaw vía Docker..."
    docker run -d \
      --name openclaw-server \
      --restart unless-stopped \
      --network host \
      -e AUTH_USERNAME=admin \
      -e AUTH_PASSWORD=openclaw_secure \
      -v /home/fcela-ga/sgoinfre/ai_core/openclaw_storage:/data \
      coollabsio/openclaw:latest
fi

echo "------------------------------------------------"
echo "¡OpenClaw operativo!"
echo "Accede a la interfaz web en: http://localhost:8080"
echo "Usuario: admin | Contraseña: openclaw_secure"