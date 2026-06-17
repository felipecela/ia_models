# ===== Archivo: orchestrator_router_v4.py =====
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
import docker
import requests
import os
import uvicorn
import sys

app = FastAPI()

try:
    docker_client = docker.from_env()
except Exception as e:
    print(f"[ERROR] No se pudo conectar a Docker: {e}")
    sys.exit(1)

def conmutar_hardware(destino: str):
    """
    Controlador de Exclusión Mutua para la RTX 4070 (8GB VRAM)
    destino: "AGIL" (SGLang) o "PROFUNDO" (Ollama)
    """
    if destino == "PROFUNDO":
        try:
            container = docker_client.containers.get("sglang-server")
            if container.status == "running":
                print("[DOCKER] Liberando VRAM: Deteniendo sglang-server (5.7GB)...")
                container.stop()
        except Exception: pass
        
        # Despierta Ollama (por si acaso estuviera dormido)
        os.system("sudo systemctl start ollama")
        return "http://host.docker.internal:11434/v1/chat/completions"
        
    elif destino == "AGIL":
        try:
            container = docker_client.containers.get("sglang-server")
            if container.status != "running":
                print("[DOCKER] Confiscando VRAM: Arrancando sglang-server (Llama 3.1)...")
                container.start()
        except Exception: pass
        
        return "http://host.docker.internal:30000/v1/chat/completions"


def clasificar_con_phi4(prompt: str) -> str:
    """Phi-4 (CPU) decide el destino basándose en análisis semántico"""
    url_ollama = "http://host.docker.internal:11434/api/generate"
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
        res = requests.post(url_ollama, json=payload, timeout=15)
        decision = res.json()["response"].strip().upper()
        return "PROFUNDO" if "PROFUNDO" in decision else "AGIL"
    except Exception as e:
        print(f"[ALERTA] Phi-4 no respondió: {e}. Fallback a AGIL.")
        return "AGIL"

@app.post("/v1/chat/completions")
async def proxy_chat_completions(request: Request):
    body = await request.json()
    
    # Extraer el modelo seleccionado por el usuario en la interfaz
    modelo_solicitado = body.get("model", "ruteador-automatico")
    mensajes = body.get("messages", [])
    ultimo_prompt = mensajes[-1].get("content", "") if mensajes else ""
    
    print("\n-----------------------------------------------------")
    print(f"[REPETICIÓN ENTRANTE] Modelo solicitado: {modelo_solicitado}")
    
    # ==========================================
    # LÓGICA DE CONTROL (MANUAL VS AUTOMÁTICA)
    # ==========================================
    target_url = ""
    modelo_final = ""

    if modelo_solicitado == "ruteador-automatico":
        print("[MODO: AUTO] Solicitando evaluación semántica a Microsoft Phi-4...")
        decision_phi4 = clasificar_con_phi4(ultimo_prompt)
        print(f"[MODO: AUTO] Phi-4 determinó que la tarea es: {decision_phi4}")
        
        target_url = conmutar_hardware(decision_phi4)
        
        # Le decimos al backend final qué modelo cargar basándonos en la decisión de Phi-4
        if decision_phi4 == "PROFUNDO":
            modelo_final = "deepseek-r1:14b"
        else:
            modelo_final = "deepseek-ai/DeepSeek-R1-Distill-Qwen-14B" # SGLang suele ignorar esto y usar su modelo cargado, pero es bueno enviarlo
            
    elif modelo_solicitado == "llama-3.1-8b-awq":
        print("[MODO: MANUAL] Over-ride usuario: Forzando ruta ÁGIL (SGLang)")
        target_url = conmutar_hardware("AGIL")
        modelo_final = "llama-3.1-8b-awq"
        
    elif modelo_solicitado == "deepseek-r1:14b":
        print("[MODO: MANUAL] Over-ride usuario: Forzando ruta PROFUNDA (Ollama)")
        target_url = conmutar_hardware("PROFUNDO")
        modelo_final = "deepseek-r1:14b"
        
    else:
        # Fallback de seguridad
        target_url = conmutar_hardware("AGIL")
        modelo_final = modelo_solicitado

    # Reemplazamos el modelo en el cuerpo para que Ollama/SGLang no se confundan
    body["model"] = modelo_final

    print(f"[PROXY] Redirigiendo Payload ({modelo_final}) hacia -> {target_url}")
    print("-----------------------------------------------------\n")
    
    # Reenviar cabeceras (limpiando el Host para evitar conflictos HTTP)
    headers = {k: v for k, v in request.headers.items() if k.lower() != "host"}
    
    # Función generadora para mantener el Streaming de texto en vivo en OpenClaw
    def stream_response():
        try:
            with requests.post(target_url, json=body, headers=headers, stream=True) as r:
                r.raise_for_status()
                for chunk in r.iter_content(chunk_size=4096):
                    if chunk:
                        yield chunk
        except Exception as e:
            yield f"data: {{\"error\": \"Fallo en la comunicación con el motor local: {str(e)}\"}}\n\n".encode('utf-8')

    return StreamingResponse(stream_response(), media_type="text/event-stream")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)