import docker
import requests
import os

client = docker.from_env()

def clasificar_prompt(prompt):
    # Llama al modelo ruteador rápido en Ollama
    payload = {
        "model": "qwen2.5:1.5b", # O el modelo ultra-ligero que elijas
        "prompt": f"Analiza la siguiente petición de usuario. Si requiere análisis profundo de código, razonamiento lógico complejo, matemáticas avanzadas o depuración profunda de errores, responde ÚNICAMENTE con la palabra 'PROFUNDO'. Si es una consulta general, resumen documental o chat rápido, responde ÚNICAMENTE con la palabra 'AGIL'. Petición: {prompt}",
        "stream": False
    }
    response = requests.post("http://localhost:11434/api/generate", json=payload)
    return response.json()["response"].strip().upper()

def enrutar_peticion(prompt):
    decision = clasificar_prompt(prompt)
    print(f"[RUTEADOR] Decisión semántica tomada: Entorno {decision}")
    
    if "PROFUNDO" in decision:
        # Liberar la GPU deteniendo SGLang
        try:
            container = client.containers.get("sglang-server")
            if container.status == "running":
                print("[HARDWARE] Deteniendo SGLang para liberar VRAM...")
                container.stop()
        except Exception:
            pass
        
        # Asegurar que Ollama está activo
        os.system("sudo systemctl start ollama")
        return "http://localhost:11434/v1" # Retorna el endpoint de Ollama
        
    else:
        # Asegurar que SGLang está activo
        try:
            container = client.containers.get("sglang-server")
            if container.status != "running":
                print("[HARDWARE] Levantando SGLang e iniciando Llama-3.1-AWQ...")
                container.start()
        except Exception:
            # Si no existe el contenedor, se corre el comando run aquí
            pass
            
        return "http://localhost:30000/v1" # Retorna el endpoint de SGLang