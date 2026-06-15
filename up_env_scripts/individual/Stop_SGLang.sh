#!/bin/bash
# ===== Archivo: Stop_SGLang.sh =====

docker stop sglang-server 2>/dev/null && echo "✔ Contenedor SGLang detenido."