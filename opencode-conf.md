Perfecto. Vamos a dejar el corazón de tu entorno de desarrollo y tu asistente completamente funcionales.

Para que los modelos no solo funcionen, sino que entiendan exactamente el nivel de exigencia de tu trabajo (especialmente al depurar memoria o estructurar arquitecturas complejas), vamos a inyectar instrucciones personalizadas (System Prompts) directamente en la configuración.

---

## 1. Configuración de OpenCode (Continue.dev en VS Code)

Continue.dev guarda su configuración en un archivo JSON en tu directorio personal.

1. Abre VS Code.
2. Haz clic en el icono de Continue en la barra lateral, pulsa en el engranaje (Configuración) o abre directamente el archivo ubicado en: `~/.continue/config.json`.
3. Reemplaza el contenido con este JSON. Fíjate cómo hemos separado el autocompletado (ExLlamaV2) del chat arquitectónico (Ollama), y añadido un prompt de sistema ajustado para desarrollo de bajo nivel y sistemas distribuidos:

```json
{
  "models": [
    {
      "title": "DeepSeek R1 Architect (14B)",
      "provider": "ollama",
      "model": "deepseek-r1:14b",
      "apiBase": "http://localhost:11434",
      "systemMessage": "Eres un ingeniero de software experto. Proporciona respuestas concisas y técnicas. Tu especialidad es el desarrollo de bajo nivel en C, C++ (estándares C++98 y C++11) y Python. Al analizar sistemas de control distribuido, sockets, o gestión de memoria, prioriza la eficiencia, la seguridad de concurrencia y la detección de leaks. Escribe código limpio y comenta solo la lógica compleja."
    }
  ],
  "tabAutocompleteModel": {
    "title": "ExLlama Coder (Rápido)",
    "provider": "openai",
    "model": "deepseek-coder-exl2",
    "apiBase": "http://localhost:5000/v1",
    "apiKey": "empty",
    "maxTokens": 256
  },
  "allowAnonymousTelemetry": false,
  "tabAutocompleteOptions": {
    "useCopyBuffer": true,
    "maxPromptTokens": 2048
  }
}

```

**Lo que logramos con esto:**

* **`tabAutocompleteModel`:** Está apuntando al puerto `5000`. Mientras escribes código en C++ o Python, el modelo ExLlamaV2 en tus 8 GB de VRAM generará sugerencias casi instantáneas (hemos limitado `maxTokens` a 256 para que responda en ráfagas hiperrápidas).
* **`models`:** Cuando selecciones una clase o un módulo entero y le preguntes al chat lateral cómo integrarlo, la petición viajará al puerto `11434` (Ollama), usando tus 32 GB de RAM para que DeepSeek-R1 aplique su capa de razonamiento antes de responder.

---

## 2. Configuración de OpenClaw (Endpoints del Asistente)

OpenClaw (y la mayoría de interfaces avanzadas como Open WebUI) gestionan sus conexiones desde el panel de administración gráfico. Vamos a conectar tus dos motores restantes: el cerebro ágil (SGLang) y el analista pesado (Ollama).

1. Abre la interfaz de OpenClaw en tu navegador (suele estar en `http://localhost:3000` o `http://localhost:8080` dependiendo de cómo lo lanzaras).
2. Ve a **Settings (Ajustes)** > **Admin Panel (Panel de Administración)** > **Connections (Conexiones)**.
3. Verás una sección para añadir conexiones a APIs compatibles con OpenAI y otra para Ollama. Configúralas así:

### Conexión A: El Cerebro Ágil (SGLang)

Busca la sección "OpenAI API" o "Custom OpenAI compatible API" y añade un nuevo endpoint:

* **API Base URL:** `http://localhost:30000/v1`
* **API Key:** `sk-local` *(Pon cualquier texto, OpenClaw no te dejará guardar si está vacío, pero SGLang lo ignorará)*.
* **Model ID:** `meta-llama/Llama-4-8B-Instruct-AWQ` *(Debe coincidir exactamente con el nombre de la carpeta/modelo)*.

### Conexión B: El Analista Pesado (Ollama)

Busca la sección nativa de "Ollama API" o añade otra conexión personalizada:

* **API Base URL:** `http://localhost:11434`
* *Nota:* En la sección de Ollama no suele pedir API Key. OpenClaw detectará automáticamente el modelo `qwen2.5:32b` que descargaste antes.

### Ajuste de Parámetros Globales (System Parameters)

En la sección de ajustes de OpenClaw, busca **"Default Workspace Parameters"** o **"Context Length"**:

* Establece el **Context Length** en **8192 tokens**. Al usar SGLang para las tareas diarias, tu gráfica manejará esta cantidad de contexto sin problemas, permitiéndote adjuntar logs largos o varios archivos a la vez en el chat sin que el sistema colapse.

Con esto, la integración de red está terminada. Tus aplicaciones ya saben exactamente a qué puerto "llamar" dependiendo de si necesitas velocidad pura, contexto masivo o razonamiento profundo.

¿Quieres que hagamos una prueba de fuego para confirmar que todo funciona enviando un comando `curl` a ExLlamaV2 para ver cómo reacciona el autocompletado en tiempo real?
