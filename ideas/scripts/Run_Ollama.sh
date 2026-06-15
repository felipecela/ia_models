#!/bin/bash
# ===== Archivo: Run_Ollama.sh =====

echo "=== ACTIVANDO ENTORNO: OLLAMA (HÍBRIDO PESADO) ==="

# 1. Bloque de Exclusión Mutua: Detener motores en Docker
echo "Liberando VRAM: Deteniendo contenedores competitivos..."
docker stop exllamav2-api 2>/dev/null && echo "✔ Contenedor ExLlamaV2 detenido."
docker stop sglang-server 2>/dev/null && echo "✔ Contenedor SGLang detenido."

# 2. Levantar el servicio nativo de Ollama
echo "Arrancando el servicio de Ollama en el sistema..."
sudo systemctl start ollama

# 3. Verificación de salida
echo "------------------------------------------------"
echo "Estado del servicio Ollama:"
sudo systemctl status ollama --no-pager | grep "Active:"
echo ""
echo "Modelos disponibles en tu almacenamiento local:"
ollama list
echo "------------------------------------------------"
echo "Entorno listo. Ollama respondiendo en el puerto 11434."