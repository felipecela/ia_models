#!/bin/bash
# ===== Archivo: Autoboot_Cluster_V8.sh =====

echo "================================================================="
echo "=== INICIANDO CLÚSTER DE IA AUTÓNOMO Y ADAPTATIVO (OPENCLAW) ==="
echo "================================================================="

DIR="$(pwd)"
STORAGE_DIR="$HOME/.openclaw_storage"
mkdir -p "$STORAGE_DIR/.openclaw"

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

echo "Esperando que el puerto 8000 esté listo..."
sleep 3

echo "[3/5] Inyectando credenciales y parches de red..."
# 1. Configuración de Modelos
cat <<EOF > "$STORAGE_DIR/initial_providers.json"
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
EOF

# 2. Configuración Core del Gateway
cat <<EOF > "$STORAGE_DIR/.openclaw/openclaw.json"
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
EOF

echo "[4/5] Levantando contenedor de OpenClaw (Sin bloqueo de Nginx)..."
# Hemos removido AUTH_USERNAME y AUTH_PASSWORD para solucionar el bucle infinito
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
  -e OPENCLAW_PRESET_CONFIG=/data/initial_providers.json \
  -v "$STORAGE_DIR":/data \
  coollabsio/openclaw:latest

echo "Esperando 10 segundos a que la estructura asiente..."
sleep 10

echo "[5/5] Aplicando parches en caliente y reiniciando..."
docker restart openclaw-server >/dev/null

echo "================================================================="
echo "¡ENTORNO DE AGENTES ABIERTO Y CONFIGURADO!"
echo "Entra directamente a: http://localhost:8080"
echo "================================================================="