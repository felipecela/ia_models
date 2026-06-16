#!/bin/bash
# ===== Archivo: Autoboot_Cluster_V5.sh =====

echo "================================================================="
echo "=== INICIANDO CLÚSTER DE IA AUTÓNOMO Y ADAPTATIVO (OPENCLAW) ==="
echo "================================================================="

DIR="$(pwd)"
STORAGE_DIR="$HOME/.openclaw_storage"
mkdir -p "$STORAGE_DIR/.openclaw"

echo "[1/4] Limpiando procesos y contenedores anteriores..."
pkill -f orchestrator_router 2>/dev/null
docker stop openclaw-server 2>/dev/null && docker rm openclaw-server 2>/dev/null

echo "[2/4] Buscando script de orquestación en $DIR..."
PYTHON_SCRIPT="orchestrator_router_v3.py"

if [ ! -f "$DIR/$PYTHON_SCRIPT" ]; then
    echo "[ERROR] No encuentro el archivo $PYTHON_SCRIPT en $DIR"
    exit 1
fi

echo "Lanzando Ruteador Semántico (Microsoft Phi-4 por CPU)..."
python3 "$DIR/$PYTHON_SCRIPT" > "$DIR/router_boot.log" 2>&1 &

echo "Esperando que el puerto 8000 esté listo..."
sleep 3

echo "[3/4] Inyectando credenciales y reglas de seguridad CORS (NUEVO)..."

# 1. Archivo de Configuración de Modelos
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

# 2. Archivo de Configuración Interna para autorizar el origen del navegador (CORS)
cat <<EOF > "$STORAGE_DIR/.openclaw/openclaw.json"
{
  "gateway": {
    "controlUi": {
      "allowedOrigins": [
        "http://localhost:8080",
        "http://127.0.0.1:8080"
      ]
    }
  }
}
EOF

echo "[4/4] Levantando contenedor de OpenClaw con puertos de Gateway expuestos..."
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
  -e OPENCLAW_PRESET_CONFIG=/data/initial_providers.json \
  -v "$STORAGE_DIR":/data \
  coollabsio/openclaw:latest

echo "================================================================="
echo "¡PROCESO FINALIZADO CON ÉXITO!"
echo "Puedes acceder directamente a: http://localhost:8080"
echo "================================================================="