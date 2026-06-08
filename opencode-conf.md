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


---



Es totalmente correcto. Las versiones recientes de la extensión **Continue.dev** para VS Code migraron su arquitectura de configuración de `config.json` hacia **`config.yaml`** para permitir comentarios y una estructura mucho más limpia.

Además, aprovechando este cambio, vamos a **actualizar los nombres exactos de los modelos que sí tienes descargados al 100%** (sustituyendo el viejo `deepseek-coder-exl2` por tu nuevo `qwen2.5-coder-7b-exl2`, e incluyendo tus otros modelos de Ollama como `phi4` y `qwen2.5:32b` para que puedas alternar entre ellos en el panel de chat).

Aquí tienes la adaptación completa y corregida a formato YAML:

### 1. Nueva Configuración de OpenCode (`~/.continue/config.yaml`)

Abre tu archivo de configuración en `~/.continue/config.yaml` (o haz clic en el engranaje de la extensión Continue dentro de VS Code) y reemplaza su contenido por el siguiente bloque:

```yaml
models:
  - title: "DeepSeek R1 Architect (14B)"
    provider: "ollama"
    model: "deepseek-r1:14b"
    systemMessage: "Eres un ingeniero de software experto. Proporciona respuestas concisas y técnicas. Tu especialidad es el desarrollo de bajo nivel en C, C++ (estándares C++98 y C++11) y Python. Al analizar sistemas de control distribuido, sockets, o gestión de memoria, prioriza la eficiencia, la seguridad de concurrencia y la detección de leaks. Escribe código limpio y comenta solo la lógica compleja."

  - title: "Qwen 2.5 (32B Analista Masivo)"
    provider: "ollama"
    model: "qwen2.5:32b"

  - title: "Phi-4 (Lógica y Matemáticas)"
    provider: "ollama"
    model: "phi4"

tabAutocompleteModel:
  title: "Qwen 2.5 Coder (7B EXL2)"
  provider: "openai"
  model: "qwen2.5-coder-7b-exl2"
  apiBase: "http://localhost:5000/v1"
  apiKey: "empty"

tabAutocompleteOptions:
  useCopyBuffer: true
  maxPromptTokens: 2048

allowAnonymousTelemetry: false

```

---

### Explicación de los Cambios en el formato YAML:

1. **Estructura de Listas (`models`):** En lugar de los corchetes `[]` de JSON, YAML utiliza guiones `-` para definir cada modelo disponible en tu panel de chat lateral de VS Code. Ahora tienes mapeados tus tres gigantes de Ollama (`deepseek-r1:14b`, `qwen2.5:32b` y el recién llegado `phi4`).
2. **Actualización del Autocompletado (`tabAutocompleteModel`):** Se eliminó el parámetro antiguo y se configuró apuntando al puerto `5000` (servidor de ExLlamaV2) leyendo de forma nativa tu modelo real: `qwen2.5-coder-7b-exl2`.
3. **Mapeo de Cadenas Largas:** El prompt del sistema (`systemMessage`) ya no requiere escapar comillas tipográficas ni saltos de línea complejos gracias al tratamiento de cadenas nativo de YAML.

### 2. Recordatorio para OpenClaw (Endpoints del Asistente)

Para que tu documentación de conexiones en OpenClaw quede coordinada con lo que realmente tienes en las carpetas, la **Conexión A** debe apuntar al modelo AWQ exacto que se completó en tu almacenamiento de SGLang:

* **API Base URL:** `http://localhost:30000/v1`
* **API Key:** `sk-local`
* **Model ID:** `llama-3.1-8b-awq` *(Cambiado para reflejar exactamente el nombre de la carpeta que revisamos en tu comando `ls`)*.

Con este fichero `.yaml` guardado, reinicia la ventana de VS Code (`Ctrl + Shift + P` -> `Developer: Reload Window`) y Continue levantará tu nuevo ecosistema local de forma inmediata. ¿Hacemos la prueba de fuego levantando el servicio de autocompletado para verificar la velocidad de respuesta?
