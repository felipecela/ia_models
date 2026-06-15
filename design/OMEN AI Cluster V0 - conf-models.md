He analizado el 100% de nuestra arquitectura: tienes un **Ubuntu** con la unidad **SSD exFAT compartida** perfectamente montada mediante tu script, aislando los datos en `ai_core`, con **32 GB de RAM** y una **RTX 4070 de 8 GB de VRAM**. Además, hemos establecido un sistema de apagado seguro para no corromper los discos.

Ha llegado el momento de darle vida a este hardware. Para no duplicar gigabytes absurdamente, vamos a aplicar la estrategia de "Especialización de Motores".

Aquí tienes la hoja de ruta definitiva para descargar los modelos exactos y enlazar todo con **OpenClaw** y **OpenCode**.

---

## FASE 1: La Matriz de Descarga de Modelos

Vamos a asignar un modelo específico, en su formato óptimo, para cada motor. De esta forma, aprovechas tus 8 GB de VRAM al máximo sin solapamientos.

### 1. El Motor Diario y de Lógica: Ollama

* **Directorio:** `~/sgoinfre/ai_core/ollama_storage`
* **Formato:** `.gguf`
* **Modelo a descargar:** **Qwen-3.5-14B (Q4_K_M)**
* **¿Por qué?:** Es el modelo de razonamiento. Al ser de 14B, ocupará unos 9 GB. Ollama meterá 6 GB en tu RTX 4070 y desbordará 3 GB a tu RAM de forma automática. Es perfecto para cuando necesites que la IA resuelva problemas de lógica complejos sin prisa.
* **Comando:** `ollama pull qwen3.5:14b`

### 2. El Motor de Agentes (OpenClaw): SGLang

* **Directorio:** `~/sgoinfre/ai_core/sglang_storage`
* **Formato:** `AWQ` (Cuantización nativa de alta velocidad).
* **Modelo a descargar:** **Llama-4-8B-Instruct-AWQ**
* **¿Por qué?:** SGLang es el rey del manejo de contexto largo. Este modelo de 8B cabe íntegramente en tu gráfica (ocupará unos 5 GB). Será instantáneo y perfecto para que OpenClaw lea documentos, gestione correos y automatice tareas en tu sistema.
* **Cómo descargar:** Usando la herramienta de HuggingFace.
```bash
pip install -U "huggingface_hub[cli]"
huggingface-cli download meta-llama/Llama-4-8B-Instruct-AWQ --local-dir ~/sgoinfre/ai_core/sglang_storage/llama4-8b-awq

```



### 3. El Motor de Código (OpenCode): ExLlamaV2 (vía TabbyAPI)

* **Directorio:** `~/sgoinfre/ai_core/exllamav2_storage`
* **Formato:** `.exl2` (Exclusivo para exprimir tu NVIDIA).
* **Modelo a descargar:** **DeepSeek-Coder-V3-8B (EXL2 a 6.0 bpw)**
* **¿Por qué?:** Necesitas que el autocompletado vuele mientras picas código. Este formato está hiper-optimizado. ExLlamaV2 lo servirá a más de 100 tokens/segundo.
* **Cómo descargar:**
```bash
huggingface-cli download turboderp/DeepSeek-Coder-V3-8B-exl2-6.0bpw --local-dir ~/sgoinfre/ai_core/exllamav2_storage/deepseek-coder-exl2


```



*(Nota: TensorRT-LLM lo dejaremos vacío por ahora, ya que compilar un `.engine` es un proyecto de laboratorio para cuando domines los otros tres).*

---

## FASE 2: Configuración de las Aplicaciones

Tanto OpenClaw como OpenCode, al igual que casi todas las apps modernas de IA, se comunican con los motores a través de una "API compatible con OpenAI". El truco está en apuntar cada app al puerto correcto (localhost).

### A. Integración con OpenClaw (Conectado a SGLang)

OpenClaw necesita un modelo rápido que entienda instrucciones precisas (System 1) y maneje un historial largo. SGLang es su motor.

1. Abre la configuración de OpenClaw (usualmente en la interfaz web o en su archivo `config.json`).
2. Busca la sección de **"Providers"** o **"LLM Configuration"**.
3. Establece los siguientes parámetros:
* **API Base URL / Endpoint:** `http://localhost:30000/v1` *(El puerto de tu contenedor Docker de SGLang)*.
* **API Key:** `sk-1234` *(SGLang a nivel local no requiere clave real, pero la mayoría de apps exigen que el campo no esté vacío)*.
* **Model Name:** `meta-llama/Llama-4-8B-Instruct-AWQ` *(El nombre exacto de la carpeta que descargaste)*.


4. **Context Length:** Ponlo en `8192`. Tu 4070 de 8GB lo manejará sin pestañear gracias a SGLang.

### B. Integración con OpenCode / Continue.dev

Para el desarrollo de software, especialmente cuando estás depurando memoria, diseñando sistemas de control distribuido o estructurando módulos en C++98, necesitas dos niveles de inteligencia. En VS Code (usando la extensión Continue.dev o el CLI de OpenCode), abre el archivo `config.json` y configura dos perfiles distintos:

**1. Para el Autocompletado (El "Copilot" rápido):**
Este perfil escribirá el código mientras tecleas. Apuntaremos a **ExLlamaV2**.

```json
"tabAutocompleteModel": {
  "title": "DeepSeek Coder (ExLlamaV2)",
  "provider": "openai",
  "model": "deepseek-coder-exl2",
  "apiBase": "http://localhost:5000/v1",
  "apiKey": "empty"
}

```

**2. Para el Chat y Refactorización Arquitectónica:**
Cuando seleccionas un bloque grande de un proyecto complejo (como un servidor Webserv o contenedores) y pulsas `Ctrl+L` para preguntar "¿Por qué falla este socket?", necesitas razonamiento profundo. Apuntaremos a **Ollama**.

```json
"models": [
  {
    "title": "Qwen Lógica (Ollama)",
    "provider": "ollama",
    "model": "qwen3.5:14b",
    "apiBase": "http://localhost:11434"
  }
]

```

---

## Flujo de Trabajo Operativo Recomendado

Tu sistema está blindado, pero recuerda la regla de oro: **la VRAM es finita**.

Para tu día a día, este es el protocolo de arranque que te recomiendo:

1. **Si vas a programar:** Ejecuta `docker start exllamav2-api` y `sudo systemctl start ollama`. Tendrás el DeepSeek de 8B (vía ExLlama) en tu VRAM para escribir rapidísimo, y el Qwen 14B (vía Ollama) durmiendo en tu RAM, despertando solo cuando le hagas una pregunta arquitectónica difícil en el chat lateral.
2. **Si vas a usar asistentes/agentes:** Asegúrate de apagar los demás (`sudo systemctl stop ollama` y `docker stop exllamav2-api`) y levanta SGLang: `docker start sglang-server`. Así OpenClaw tendrá los 8 GB de VRAM enteros para él, procesando cientos de archivos en segundos.

Con estas descargas y esta configuración de red local, tienes un clúster de IA privada de grado profesional. ¿Te gustaría que hagamos una prueba de "ping" o conexión a través de `curl` a alguno de los puertos (`30000` o `5000`) para verificar que los contenedores están sirviendo los modelos correctamente antes de abrir las aplicaciones?
