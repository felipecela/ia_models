#!/bin/bash
# ===== Archivo: TensorRT-LLM.sh =====
docker run -it --gpus all \
  --name tensorrt-compiler \
  --ipc=host \
  -v /home/fcela-ga/sgoinfre/ai_core/tensorrt_storage:/workspace \
  nvidia/cuda:12.4.1-devel-ubuntu22.04 bash