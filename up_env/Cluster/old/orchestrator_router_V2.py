# ===== Archivo: orchestrator_router.py =====
import docker
import requests
import os
import sys

# Inicializar el cliente de Docker nativo de tu Ubuntu
try:
    client = docker.from_env()
except Exception as e:
    print(f"[ERROR] No se pudo conectar al socket de Docker: {e}")
    sys.exit(1)

def clasificar_prompt_con_phi4(prompt):
    """
    Utiliza el modelo Phi-4 de Microsoft alojado en Ollama para analizar 
    semánticamente la intención del usuario y decidir el destino.
    """
    url_ollama = "http://localhost:11434/api/generate"
    
    # Prompt de sistema ultra-estricto para asegurar que Phi-4 solo responda una palabra
    system_instructions = (
        "Actúa como un ruteador de infraestructura de IA rígido. "
        "Analiza la petición del usuario. "
        "Si la petición requiere: análisis profundo de código, razonamiento lógico complejo, "
        "matemáticas avanzadas, depuración de memory leaks en C/C++ o lógica pesada, "
        "responde ÚNICAMENTE con la palabra: PROFUNDO. "
        "Si la petición requiere: chat general, traducción, resúmenes de texto o procesamiento "
        "ágil de documentos, responde ÚNICAMENTE con la palabra: AGIL. "
        "No añadas introducciones, explicaciones ni signos de puntuación. Solo una palabra."
    )
    
    payload = {
        "model": "phi4",  # <--- Aquí está configurado explícitamente tu modelo de Microsoft
        "prompt": f"{system_instructions}\n\nPetición del usuario: {prompt}\nRespuesta:",
        "stream": False,
        "options": {
            "temperature": 0.0,  # Temperatura 0 para evitar variaciones en la decisión
            "num_predict": 5     # Limitamos los tokens de salida para que responda instantáneamente
        }
    }
    
    try:
        # Nota: Si SGLang está corriendo, Ollama procesará esto usando tus 32GB de RAM de forma híbrida
        response = requests.post(url_ollama, json=payload, timeout=10)
        decision = response.json()["response"].strip().upper()
        # Limpieza de cualquier residuo de texto
        if "PROFUNDO" in decision:
            return "PROFUNDO"
        return "AGIL"
    except Exception as e:
        print(f"[ERROR OLLAMA] No se pudo comunicar con Phi-4: {e}")
        return "AGIL" # Por seguridad, enviamos al entorno ágil si falla el ruteador

def orquestar_entorno(prompt_usuario):
    print("==================================================")
    print(f"[ORQUESTADOR] Evaluando petición con Microsoft Phi-4...")
    
    # 1. El modelo Phi-4 toma la decisión arquitectónica
    entorno_destino = clasificar_prompt_con_phi4(prompt_usuario)
    print(f"[ORQUESTADOR] Phi-4 determinó que el flujo óptimo es: {entorno_destino}")
    
    # 2. Orquestación caliente de contenedores Docker mediante exclusión mutua
    if entorno_destino == "PROFUNDO":
        print("[HARDWARE] Modo profundo detectado. Liberando VRAM al 100%...")
        try:
            # Apagamos SGLang para dejar los 8GB de VRAM limpios para Ollama
            container = client.containers.get("sglang-server")
            if container.status == "running":
                print("[DOCKER] Deteniendo sglang-server (Llama-3.1-AWQ)...")
                container.stop()
                print("[HARDWARE] ✔ VRAM Liberada con éxito.")
        except docker.errors.NotFound:
            pass  # El contenedor no estaba creado, no hay problema
        except Exception as e:
            print(f"[ALERTA] No se pudo detener SGLang: {e}")
            
        # Aseguramos que el servicio del sistema Ollama esté activo
        os.system("sudo systemctl start ollama")
        
        # Retornamos el endpoint de Ollama para que OpenClaw envíe la pregunta a DeepSeek-R1 o Qwen-32B
        return "http://localhost:11434/v1"
        
    else:
        print("[HARDWARE] Modo ágil detectado. Asegurando entorno SGLang...")
        try:
            # Verificamos el estado de SGLang
            container = client.containers.get("sglang-server")
            if container.status != "running":
                print("[DOCKER] Arrancando sglang-server en la GPU (RTX 4070)...")
                container.start()
                print("[HARDWARE] ✔ SGLang cargado y adueñado de la VRAM.")
        except docker.errors.NotFound:
            print("[ALERTA] El contenedor 'sglang-server' no existe. Ejecuta primero Run_SGLang.sh")
            return "http://localhost:11434/v1" # Contingencia a Ollama
            
        # Retornamos el endpoint de SGLang para procesamiento masivo y veloz
        return "http://localhost:30000/v1"

# Ejemplo de uso interno para la API de OpenClaw
if __name__ == "__main__":
    test_prompt = "Necesito que revises este código en C++ porque tengo un fallo de segmentación (Segmentation Fault) en los sockets"
    endpoint_final = orquestar_entorno(test_prompt)
    print(f"[PROV] OpenClaw redirigirá el payload hacia: {endpoint_final}")