#!/bin/bash
# ===== Archivo: Autoboot_Cluster_V3.sh =====

echo "================================================================="
echo "=== INICIANDO CLÚSTER DE IA AUTÓNOMO Y ADAPTATIVO (OPENCLAW) ==="
echo "================================================================="

# Directorio de trabajo actual (donde estás ejecutando este script)
DIR="$(pwd)"
STORAGE_DIR="/home/fcela-ga/sgoinfre/ai_core/openclaw_storage"
mkdir -p "$STORAGE_DIR"

# 1. Detener instancias previas
echo "[1/4] Limpiando procesos y contenedores anteriores..."
pkill -f orchestrator_router 2>/dev/null
docker stop openclaw-server 2>/dev/null && docker rm openclaw-server 2>/dev/null

# 2. Arrancar el Proxy Ruteador Semántico
echo "[2/4] Buscando script de orquestación en $DIR..."
# ¡Ojo! Asegúrate de que el archivo Python se llame así en esta misma carpeta:
PYTHON_SCRIPT="orchestrator_router_v3.py"

if [ ! -f "$DIR/$PYTHON_SCRIPT" ]; then
    echo "[ERROR CRÍTICO] No encuentro el archivo $PYTHON_SCRIPT en $DIR"
    echo "Por favor, asegúrate de haber creado el script de Python aquí antes de arrancar."
    exit 1
fi

echo "Lanzando Ruteador Semántico (Microsoft Phi-4 por CPU)..."
python3 "$DIR/$PYTHON_SCRIPT" > "$STORAGE_DIR/router_boot.log" 2>&1 &

echo "Esperando que el puerto 8000 esté listo..."
sleep 3

# 3. Inyección de Base de Datos para OpenClaw (Usando host.docker.internal)
echo "[3/4] Inyectando credenciales usando el puente interno de Docker..."
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

# 4. Lanzar el contenedor con el mapeo de puertos estándar y el puente host-gateway
echo "[4/4] Levantando contenedor de OpenClaw con autonomía total..."
docker run -d \
  --name openclaw-server \
  --restart unless-stopped \
  -p 8080:8080 \
  --add-host host.docker.internal:host-gateway \
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
echo "El ecosistema está corriendo de forma autónoma en segundo plano."
echo "Puedes acceder directamente a: http://localhost:8080"
echo "================================================================="