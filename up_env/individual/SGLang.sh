#!/bin/bash
# ===== Archivo: SGLang.sh =====
docker run -d --gpus all \
  --name sglang-server \
  --restart unless-stopped \
  --ipc=host \
  -v /home/fcela-ga/sgoinfre/ai_core/sglang_storage:/models \
  -p 30000:30000 \
  lmsysorg/sglang:latest \
  python3 -m sglang.launch_server \
    --model-path /models/llama-3.1-8b-awq \
    --port 30000 \
    --host 0.0.0.0