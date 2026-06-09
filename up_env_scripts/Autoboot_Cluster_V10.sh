#!/bin/bash
# ===== Archivo: Autoboot_Cluster_V10.sh =====

echo "================================================================="
echo "=== INICIANDO CLÚSTER DE IA AUTÓNOMO Y ADAPTATIVO (OPENCLAW) ==="
echo "================================================================="

DIR="$(pwd)"

echo "[1/5] Limpiando procesos y contenedores anteriores..."
pkill -f orchestrator_router 2>/dev/null
docker stop openclaw-server 2>/dev/null && docker rm openclaw-server 2>/dev/null

echo "[2/5] Lanzando Ruteador Semántico (Microsoft Phi-4 por CPU)..."
PYTHON_SCRIPT="orchestrator_router_v4.py"
if [ ! -f "$DIR/$PYTHON_SCRIPT" ]; then
    echo "[ERROR] No encuentro el archivo $PYTHON_SCRIPT en $DIR"
    exit 1
fi
python3 "$DIR/$PYTHON_SCRIPT" > "$DIR/router_boot.log" 2>&1 &

echo "[3/5] Preparando Disco Nativo de Docker (Bypass de Permisos)..."
# Usamos un volumen administrado por Docker para evitar conflictos de usuario
docker volume create openclaw_data_final >/dev/null

echo "[4/5] Levantando contenedor de OpenClaw (Sin bloqueo Nginx)..."
docker run -d \
  --name openclaw-server \
  --restart unless-stopped \
  -p 8080:8080 \
  -p 18789:18789 \
  --add-host host.docker.internal:host-gateway \
  --add-host browser:127.0.0.1 \
  -e OPENCLAW_GATEWAY_TOKEN=7c9b84a2f1e63d5c8a4b29f7e0d1c4a5b6e7f8d9c0a1b2c3d4e5f6a7b8c9d0e1 \
  -e OPENAI_API_KEY=sk-router-local \
  -e OPENAI_BASE_URL=http://host.docker.internal:8000/v1 \
  -e OLLAMA_BASE_URL=http://host.docker.internal:11434 \
  -v openclaw_data_final:/data \
  coollabsio/openclaw:latest

echo "Esperando 15 segundos a que el contenedor inicialice su motor..."
sleep 15

echo "[5/5] Inyectando Parches Maestros de Red en caliente..."
docker exec openclaw-server sh -c 'mkdir -p /data/.openclaw'

# Inyección del parche CORS y LAN directo al sistema de archivos del contenedor
docker exec openclaw-server sh -c 'cat <<EOF > /data/.openclaw/openclaw.json
{
  "gateway": {
    "bind": "lan",
    "controlUi": {
      "allowedOrigins": [
        "http://localhost:8080",
        "http://127.0.0.1:8080"
      ]
    }
  }
}
EOF'

# Inyección de los proveedores
docker exec openclaw-server sh -c 'cat <<EOF > /data/initial_providers.json
{
  "providers": [
    {
      "id": "openai_proxy",
      "name": "Ruteador Semántico Local",
      "baseUrl": "http://host.docker.internal:8000/v1",
      "apiKey": "sk-router-local",
      "models": ["llama-3.1-8b-awq", "deepseek-r1:14b", "qwen2.5:32b"],
      "enabled": true
    }
  ]
}
EOF'

echo "Reiniciando contenedor para asimilar la configuración..."
docker restart openclaw-server >/dev/null

echo "================================================================="
echo "¡ENTORNO DE AGENTES ABIERTO Y CONFIGURADO!"
echo "Entra directamente a: http://localhost:8080"
echo "================================================================="