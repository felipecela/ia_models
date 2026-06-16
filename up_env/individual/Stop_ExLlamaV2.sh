#!/bin/bash
# ===== Archivo: Stop_ExLlamaV2.sh =====

docker stop exllamav2-api 2>/dev/null && echo "✔ Contenedor ExLlamaV2 detenido."