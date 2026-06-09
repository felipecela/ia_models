#!/bin/bash
# ===== Archivo: Stop_Ollama.sh =====

sudo systemctl stop ollama 2>/dev/null && echo "✔ Servicio Ollama nativo detenido."