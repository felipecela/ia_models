#!/bin/bash
# ===== Archivo: Autoboot_Cluster_V7.sh =====

echo "================================================================="
echo "=== INICIANDO CLÚSTER DE IA AUTÓNOMO Y ADAPTATIVO (OPENCLAW) ==="
echo "================================================================="

DIR="$(pwd)"

echo "[1/5] Limpiando procesos y contenedores anteriores..."
pkill -f orchestrator_router 2>/dev/null
docker stop openclaw-server 2>/dev/null && docker rm openclaw-server 2>/dev/null

echo "[2/5] Lanzando Ruteador Semántico (Microsoft Phi-4 por CPU)..."
PYTHON_SCRIPT="orchestrator_router_v3.py"
if [ ! -f "$DIR/$PYTHON_SCRIPT" ]; then
    echo "[ERROR] No encuentro el archivo $PYTHON_SCRIPT en $DIR"
    exit 1
fi
python3 "$DIR/$PYTHON_SCRIPT" > "$DIR/router_boot.log" 2>&1 &

# CREAMOS UN VOLUMEN NATIVO (Bypass absoluto a exFAT y NFS)
echo "[3/5] Preparando Disco Nativo de Docker..."
docker volume create openclaw_data_v2 >/dev/null

echo "[4/5] Levantando contenedor de OpenClaw..."
docker run -d \
  --name openclaw-server \
  --restart unless-stopped \
  -p 8080:8080 \
  -p 18789:18789 \
  --add-host host.docker.internal:host-gateway \
  --add-host browser:127.0.0.1 \
  -e AUTH_USERNAME=admin \
  -e AUTH_PASSWORD=openclaw_secure \
  -e OPENCLAW_GATEWAY_TOKEN=7c9b84a2f1e63d5c8a4b29f7e0d1c4a5b6e7f8d9c0a1b2c3d4e5f6a7b8c9d0e1 \
  -e OPENAI_API_KEY=sk-router-local \
  -e OPENAI_BASE_URL=http://host.docker.internal:8000/v1 \
  -e OLLAMA_BASE_URL=http://host.docker.internal:11434 \
  -v openclaw_data_v2:/data \
  coollabsio/openclaw:latest

echo "Esperando 10 segundos a que el contenedor cree su estructura interna..."
sleep 10

echo "[5/5] Inyectando Parches de Seguridad CORS y WebSocket..."
# Forzamos la configuración de red y puertos directamente en las entrañas del contenedor
docker exec openclaw-server sh -c 'mkdir -p /data/.openclaw'

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

echo "Reiniciando contenedor para aplicar las reglas maestras..."
docker restart openclaw-server >/dev/null

echo "================================================================="
echo "¡SISTEMA COMPLETAMENTE OPERATIVO!"
echo "Accede a: http://localhost:8080"
echo "================================================================="