docker run -d --gpus all \
  --name sglang-server \
  -v /home/fcela-ga/sgoinfre/ai_core/sglang_storage:/root/.cache/huggingface \
  -p 30000:30000 \
  --ipc=host \
  lmsysorg/sglang:latest \
  python3 -m sglang.launch_server --model-path deepseek-ai/DeepSeek-R1-Distill-Qwen-14B --port 30000 --host 0.0.0.0
