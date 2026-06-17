#!/bin/bash
# ===== Archivo: Autoboot_Cluster_V10.sh =====

echo "================================================================="
echo "=== INICIANDO CLÚSTER DE IA AUTÓNOMO Y ADAPTATIVO (OPENCLAW) ==="
echo "================================================================="

DIR="$(pwd)"

# ─────────────────────────────────────────────────────────────────────────────
#  CONFIGURACIÓN DE RUTAS DE MODELOS (Estructura Unificada)
# ─────────────────────────────────────────────────────────────────────────────
MODELS_ROOT="/home/fcela-ga/sgoinfre/ai_core/models"
OLLAMA_MODELS_DIR="$MODELS_ROOT/ollama"
OLLAMA_CPU_MODELS_DIR="$MODELS_ROOT/ollama-cpu"
EXLLAMA_MODELS_DIR="$MODELS_ROOT"
SGLANG_MODELS_DIR="$MODELS_ROOT"

echo "[1/9] Limpiando procesos y contenedores anteriores..."
pkill -f orchestrator_router 2>/dev/null
docker stop openclaw-server ollama-cpu-router exllamav2-api sglang-server 2>/dev/null
docker rm openclaw-server ollama-cpu-router exllamav2-api sglang-server 2>/dev/null
sudo systemctl stop ollama 2>/dev/null

echo "[2/9] Configurando Ollama GPU (Nativo)..."
sudo mkdir -p /etc/systemd/system/ollama.service.d
sudo bash -c "cat > /etc/systemd/system/ollama.service.d/override.conf" << OVERRIDE_EOF
[Service]
Environment="OLLAMA_MODELS=$OLLAMA_MODELS_DIR"
Environment="OLLAMA_HOST=0.0.0.0:11434"
OVERRIDE_EOF
sudo systemctl daemon-reload 2>/dev/null || true
sudo systemctl start ollama

echo "[3/9] Levantando Ollama CPU-only (Router/Embeddings)..."
docker run -d \
  --name ollama-cpu-router \
  --restart unless-stopped \
  --gpus "" \
  -p 11435:11434 \
  -e OLLAMA_MODELS=/models \
  -v "${OLLAMA_CPU_MODELS_DIR}":/models \
  ollama/ollama

echo "[4/9] Preparando ExLlamaV2 (Standby)..."
docker create \
  --gpus all \
  --name exllamav2-api \
  -p 5000:5000 \
  -v "${EXLLAMA_MODELS_DIR}":/models \
  berot3/tabbyapi:latest

echo "[5/9] Preparando SGLang (Standby)..."
docker create \
  --gpus all \
  --name sglang-server \
  --ipc=host \
  -p 30000:30000 \
  -v "${SGLANG_MODELS_DIR}":/models \
  lmsysorg/sglang:latest \
  python3 -m sglang.launch_server \
    --model-path /models/llama-3.1-8b-awq \
    --port 30000 \
    --host 0.0.0.0

echo "[6/9] Lanzando Ruteador Semántico (Microsoft Phi-4 por CPU)..."
PYTHON_SCRIPT="orchestrator_router_v4.py"
if [ ! -f "$DIR/$PYTHON_SCRIPT" ]; then
    echo "[ERROR] No encuentro el archivo $PYTHON_SCRIPT en $DIR"
    exit 1
fi
python3 "$DIR/$PYTHON_SCRIPT" > "$DIR/router_boot.log" 2>&1 &

echo "[7/9] Preparando Disco Nativo de Docker (Bypass de Permisos)..."
# Usamos un volumen administrado por Docker para evitar conflictos de usuario
docker volume create openclaw_data_final >/dev/null

echo "[8/9] Levantando contenedor de OpenClaw (Sin bloqueo Nginx)..."
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

echo "[9/9] Inyectando Parches Maestros de Red en caliente..."
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