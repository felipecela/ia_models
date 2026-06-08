#!/bin/bash
# ===== Archivo: Autoboot_Cluster.sh =====

echo "================================================================="
echo "=== INICIANDO CLÚSTER DE IA AUTÓNOMO Y ADAPTATIVO (OPENCLAW) ==="
echo "================================================================="

# 1. Rutas del almacenamiento en tu unidad exFAT compartida
STORAGE_DIR="/home/fcela-ga/sgoinfre/ai_core/openclaw_storage"
mkdir -p "$STORAGE_DIR"

# 2. Detener instancias previas para evitar colisiones en los puertos
echo "[1/4] Limpiando procesos y contenedores anteriores..."
pkill -f orchestrator_router.py 2>/dev/null
docker stop openclaw-server 2>/dev/null && docker rm openclaw-server 2>/dev/null

# 3. Arrancar el Proxy Ruteador Semántico (FastAPI + Phi-4) usando la instalación de APT
echo "[2/4] Lanzando Ruteador Semántico (Microsoft Phi-4 por CPU)..."
# Ejecutamos en segundo plano y redirigimos los logs a un archivo local
python3 /home/fcela-ga/sgoinfre/ai_core/orchestrator_router.py > /home/fcela-ga/sgoinfre/ai_core/router_boot.log 2>&1 &

# Esperar unos segundos a que FastAPI inicialice el puerto 8000
echo "Esperando que el puerto 8000 esté listo..."
sleep 3

# 4. PRE-CONFIGURACIÓN (Escribir las conexiones del proxy directamente en el almacenamiento persistente)
echo "[3/4] Inyectando credenciales y endpoints en la base de datos de OpenClaw..."
# Escribimos el archivo de configuración JSON/TOML que OpenClaw lee nativamente al arrancar
cat <<EOF > "$STORAGE_DIR/initial_providers.json"
{
  "providers": [
    {
      "id": "openai_proxy",
      "name": "Ruteador Semántico Local",
      "baseUrl": "http://localhost:8000/v1",
      "apiKey": "sk-router-local",
      "models": ["llama-3.1-8b-awq", "deepseek-r1:14b", "qwen2.5:32b"],
      "enabled": true
    }
  ]
}
EOF

# 5. Lanzar el contenedor de OpenClaw acoplado al entorno inyectado
echo "[4/4] Levantando contenedor de OpenClaw con autonomía total..."
docker run -d \
  --name openclaw-server \
  --restart unless-stopped \
  --network host \
  -e AUTH_USERNAME=admin \
  -e AUTH_PASSWORD=openclaw_secure \
  -e OPENCLAW_PRESET_CONFIG=/data/initial_providers.json \
  -v "$STORAGE_DIR":/data \
  coollabsio/openclaw:latest

echo "================================================================="
echo "¡PROCESO FINALIZADO CON ÉXITO!"
echo "El ecosistema está corriendo de forma autónoma en segundo plano."
echo "Puedes acceder directamente a: http://localhost:8080"
echo "================================================================="