#!/bin/bash
# ===== Archivo: ExLlamaV2.sh =====
docker run -d --gpus all \
  --name exllamav2-api \
  --restart unless-stopped \
  -v /home/fcela-ga/sgoinfre/ai_core/exllamav2_storage:/models \
  -p 5000:5000 \
  berot3/tabbyapi:latest