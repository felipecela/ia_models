#!/bin/bash
# ===== Archivo: Autoboot_OpenClaw_V11.sh =====
# Sincronizado con OMEN AI Cluster V36 y Router V14

echo "================================================================="
echo "=== INICIANDO CLÚSTER DE AGENTES (OPENCLAW) SINC. CON V36 ==="
echo "================================================================="

# Rutas alineadas con V36
AI_HOME="$HOME/ai_cluster"
ROUTER_SCRIPT="orchestrator_router_V4.py"

echo "[1/5] Limpiando contenedores anteriores de OpenClaw..."
docker stop openclaw-server 2>/dev/null && docker rm openclaw-server 2>/dev/null

echo "[2/5] Verificando Ruteador Semántico V14..."
if pgrep -f "$ROUTER_SCRIPT" >/dev/null; then
    echo "[INFO] El Router V14 ya está activo (gestionado por V36). Reutilizando conexión..."
else
    echo "[INFO] Router V14 no detectado. Lanzándolo de forma autónoma..."
    if [ ! -f "$AI_HOME/$ROUTER_SCRIPT" ]; then
        echo "[ERROR] No encuentro el archivo $ROUTER_SCRIPT en $AI_HOME"
        exit 1
    fi
    export AGENT_DB_DIR="$AI_HOME/agent_data"
    export ROUTER_PORT=8000
    mkdir -p "$AGENT_DB_DIR" "$AI_HOME/logs"
    python3 "$AI_HOME/$ROUTER_SCRIPT" > "$AI_HOME/logs/openclaw_router_boot.log" 2>&1 &
    sleep 5 # Dar tiempo a que levante FastAPI
fi

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
  -e OPENAI_API_KEY=empty \
  -e OPENAI_BASE_URL=http://host.docker.internal:8000/v1 \
  -e OLLAMA_BASE_URL=http://host.docker.internal:11434 \
  -v openclaw_data_final:/data \
  coollabsio/openclaw:latest

echo "Esperando 15 segundos a que el contenedor inicialice su motor..."
sleep 15

echo "[5/5] Inyectando Parches Maestros de Red y Catálogo V36 en caliente..."
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

# Inyección de los proveedores (ACTUALIZADO AL ROUTER V14)
docker exec openclaw-server sh -c 'cat <<EOF > /data/initial_providers.json
{
  "providers": [
    {
      "id": "openai_proxy",
      "name": "OMEN AI Cluster (Router V14)",
      "baseUrl": "http://host.docker.internal:8000/v1",
      "apiKey": "empty",
      "models": [
        "ruteador-auto",
        "chat",
        "instantaneo",
        "agil",
        "profundo",
        "masivo",
        "codigo"
      ],
      "enabled": true
    }
  ]
}
EOF'

echo "Reiniciando contenedor para asimilar la configuración..."
docker restart openclaw-server >/dev/null

echo "================================================================="
echo "¡ENTORNO DE AGENTES ABIERTO Y SINCRONIZADO CON V36!"
echo "Entra directamente a: http://localhost:8080"
echo "================================================================="
