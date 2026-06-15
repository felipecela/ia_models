# ===== Archivo: orchestrator_router.py =====
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
import docker
import requests
import os
import uvicorn

app = FastAPI()
docker_client = docker.from_env()

def clasificar_con_phi4(prompt: str) -> str:
    """Phi-4 en Ollama decide el entorno analizando el prompt (Corre por CPU RAM)"""
    url_ollama = "http://localhost:11434/api/generate"
    system_prompt = (
        "Responde estrictamente con una sola palabra sin puntuación. "
        "Si la petición requiere: razonamiento profundo, matemáticas, análisis de logs pesados, "
        "o depuración de código bajo nivel (C++, C, memory leaks, sockets), responde: PROFUNDO. "
        "Si es chat general, resúmenes, traducción o análisis documental ágil, responde: AGIL."
    )
    payload = {
        "model": "phi4",
        "prompt": f"{system_prompt}\n\nUsuario: {prompt}\nRespuesta:",
        "stream": False,
        "options": {"temperature": 0.0, "num_predict": 5}
    }
    try:
        res = requests.post(url_ollama, json=payload, timeout=10)
        decision = res.json()["response"].strip().upper()
        return "PROFUNDO" if "PROFUNDO" in decision else "AGIL"
    except Exception:
        return "AGIL" # Contingencia segura

@app.post("/v1/chat/completions")
async def proxy_chat_completions(request: Request):
    """Intercepta la llamada de OpenClaw y conmuta el hardware antes de responder"""
    body = await request.json()
    
    # Extraer el último mensaje del usuario para que Phi-4 lo analice
    mensajes = body.get("messages", [])
    ultimo_prompt = mensajes[-1].get("content", "") if mensajes else ""
    
    # 1. Clasificación Semántica
    decision = clasificar_con_phi4(ultimo_prompt)
    print(f"[RUTEADOR] Microsoft Phi-4 determinó flujo: {decision}")
    
    # 2. Orquestación Caliente de Docker (Exclusión Mutua de VRAM)
    if decision == "PROFUNDO":
        try:
            container = docker_client.containers.get("sglang-server")
            if container.status == "running":
                print("[DOCKER] Deteniendo SGLang para liberar 5.74GB de VRAM...")
                container.stop()
        except Exception: pass
        os.system("sudo systemctl start ollama")
        target_url = "http://localhost:11434/v1/chat/completions"
    else:
        try:
            container = docker_client.containers.get("sglang-server")
            if container.status != "running":
                print("[DOCKER] Encendiendo SGLang (Llama-3.1-AWQ) en GPU...")
                container.start()
        except Exception: pass
        target_url = "http://localhost:30000/v1/chat/completions"

    # 3. Redirección del Payload original al motor elegido
    print(f"[PROXY] Redirigiendo petición a: {target_url}")
    headers = {k: v for k, v in request.headers.items() if k.lower() != "host"}
    
    # Soporte para streaming nativo hacia OpenClaw
    def stream_response():
        with requests.post(target_url, json=body, headers=headers, stream=True) as r:
            for chunk in r.iter_content(chunk_size=4096):
                yield chunk

    return StreamingResponse(stream_response(), media_type="application/json")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)