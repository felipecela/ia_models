# Investigación: Aider y herramientas de codificación agéntica con modelos locales pequeños

> **Contexto**: Evaluación de herramientas open-source para "flow engineering" / bucles agénticos de programación con modelos locales pequeños (7-8B parámetros: Llama 3.1 8B, Qwen2.5-Coder 7B) servidos via proxy LiteLLM (API compatible con OpenAI en `http://localhost:4000`, con master key y alias como `codigo`, `instantaneo`).
>
> **Fecha de investigación**: Julio 2026

---

## 1. Comparativa de herramientas agénticas open-source

### Tabla comparativa

| Herramienta | Modelos 7-8B | Endpoint OpenAI-compat. | Interfaz | Contenedor Docker necesario | Estado mantenimiento (mid-2026) | Footprint | CLI usable |
|---|---|---|---|---|---|---|---|
| **Aider** | ✅ Funciona (con `whole` format) | ✅ Nativo (`openai/` prefix) | CLI puro | ❌ No necesario | ✅ Muy activo (~45k ⭐, releases frecuentes) | Ligero (pip) | ✅ Excelente |
| **OpenHands** | ⚠️ Limitado (recomienda 35B+) | ✅ Vía config | Web UI + Docker | ✅ Requiere Docker | ✅ Muy activo (~75k ⭐, v1.8 mayo 2026) | Pesado (Docker) | ⚠️ Web-first |
| **Plandex** | ⚠️ Funciona con Ollama pero diseñado para modelos grandes | ✅ Custom models config | CLI | ⚠️ Docker para modo local | ⚠️ Activo (v2.2.1 jul 2025, cloud cerrando) | Medio (Docker servidor) | ✅ Bueno |
| **Continue.dev** | ✅ Explícitamente recomienda 7B | ✅ Nativo (cualquier endpoint OpenAI) | Extensión IDE (VS Code/JetBrains) + CLI | ❌ No necesario | ✅ Muy activo (~33k ⭐) | Ligero | ⚠️ IDE-first |
| **Goose (Block/AAIF)** | ⚠️ Funciona pero falla en tool-calling con <14B | ✅ Generic OpenAI-compat declarativo | CLI + Desktop | ❌ No necesario | ✅ Muy activo (~49k ⭐, v1.38 jun 2026) | Ligero (Rust) | ✅ Bueno |
| **gptme** | ✅ Funciona vía llama.cpp/OpenAI-compat | ✅ `OPENAI_BASE_URL` + `local/<model>` | CLI puro | ❌ No necesario | ✅ Activo (v0.31 dic 2025, PyPI jun 2026) | Ligero (pip) | ✅ Minimalista |

---

### Análisis detallado

#### Aider (aider-chat)

Aider es la herramienta más madura para edición iterativa de código con integración git nativa. Funciona internamente sobre LiteLLM, lo que le da soporte nativo a cualquier endpoint compatible con OpenAI. Para modelos 7-8B, el punto clave es usar el formato `whole` (archivo completo) en lugar de `diff`, ya que los modelos pequeños frecuentemente generan diff malformados. En el [leaderboard de Aider](https://aider.chat/docs/leaderboards/edit.html), Qwen2.5-Coder 7B obtiene ~57.9% con formato `whole`, que es usable pero no espectacular. La herramienta es la más fácil de configurar con un proxy LiteLLM y la única con documentación explícita de ese flujo.

**Veredicto para modelos 7-8B locales**: Mejor opción CLI, con la configuración correcta.

#### OpenHands (antes OpenDevin)

OpenHands es un agente autónomo que ejecuta código en un sandbox Docker, navega la web y completa tareas de desarrollo end-to-end. [Su documentación oficial](https://docs.openhands.dev/openhands/usage/llms/local-llms) reconoce soporte para modelos locales pero **desaconseja explícitamente modelos bajo 35B** para un uso funcional:

> "Models under 7B emit malformed calls regardless of which agent wraps them."

El modelo mínimo recomendado a partir de mayo 2026 es **Qwen3.6-35B-A3B**. Para 7-8B, el agente tendería a fallar en llamadas a herramientas. Además, requiere Docker, lo que aumenta el footprint significativamente.

**Veredicto para modelos 7-8B**: No recomendado. El overhead de Docker y la dependencia de tool-calling lo hacen inadecuado.

#### Plandex

Plandex es una herramienta de CLI orientada a proyectos grandes (hasta 2M tokens de contexto, 20M+ con tree-sitter). Tiene soporte para modelos locales via Ollama. Sin embargo, la arquitectura cliente-servidor (incluso en modo local) requiere Docker para el servidor. [El repo de GitHub](https://github.com/plandex-ai/plandex) indica que Plandex Cloud está cerrando (octubre 2025), lo que empuja al modo self-hosted.

La herramienta está diseñada para flujos multi-modelo complejos (planner + editor) y su valor real emerge con modelos grandes. Con modelos 7-8B la calidad de planificación sería deficiente.

**Veredicto para modelos 7-8B**: No ideal. Requiere Docker y no está optimizado para modelos pequeños.

#### Continue.dev

Continue.dev es principalmente una extensión para IDE (VS Code, JetBrains) con soporte para modelos locales como ciudadano de primera clase. [Sus propias recomendaciones](https://docs.continue.dev/ide-extensions/agent/model-setup) incluyen Qwen2.5-Coder 7B explícitamente para autocomplete. Sin embargo, **no es una herramienta CLI-first** — el modo agente está diseñado para correr dentro del IDE. Tiene una CLI pero el caso de uso principal es el editor.

**Veredicto para modelos 7-8B**: Excelente para uso en IDE. No es una alternativa CLI a Aider.

#### Goose (Block → AAIF)

[Goose](https://goose-docs.ai) es un agente general (no solo código) basado en MCP, con backend en Rust, que soporta cualquier endpoint OpenAI-compatible. Fue transferido a la Linux Foundation AAIF en abril 2026. Soporta Ollama nativamente y cualquier endpoint OpenAI genérico. El problema con modelos 7-8B es el mismo que OpenHands: Goose depende de tool-calling estructurado, y los modelos pequeños emiten llamadas de herramienta malformadas. [Una revisión de junio 2026](https://aicoderscope.com/blog/goose-ai-agent-review-2026/) confirma: "small local models (7–14B) handle tool-calling far less reliably than frontier cloud models."

**Veredicto para modelos 7-8B**: Funciona pero unreliable. El agente se interrumpe en tool calls malformados con 7-8B.

#### gptme

[gptme](https://github.com/gptme/gptme) es un agente CLI minimalista (Python, MIT) que puede ejecutar shell, Python, editar archivos y navegar la web. Soporta cualquier endpoint OpenAI-compatible via `OPENAI_BASE_URL`. El CLI es simple: `gptme -m local/<model>`. Es mucho más minimalista que Aider, sin integración git nativa, y el modo agente es más de tipo "asistente supervisado" que editor iterativo. Active development (v0.31 dic 2025, releases en PyPI jun 2026).

**Veredicto para modelos 7-8B**: Viable para tareas simples. Menos capacidades que Aider para edición de código. Buena opción como fallback ligero.

---

### Veredicto final

**Para el caso de uso descrito (CLI, modelos 7-8B, proxy LiteLLM, sin Docker), Aider es la mejor opción**. Las razones:

1. **Integración LiteLLM nativa**: Aider usa LiteLLM internamente, lo que significa que el proxy es un ciudadano de primera clase, no un workaround.
2. **Formato `whole` para modelos débiles**: La opción de usar archivo completo en lugar de diff es crítica para modelos 7-8B y está bien documentada.
3. **No requiere Docker**.
4. **Integración git nativa**: commits automáticos (o desactivables), historial de cambios limpio.
5. **Configurabilidad**: `.aider.conf.yml`, `.aider.model.settings.yml`, `.aider.model.metadata.json` permiten ajuste fino para modelos desconocidos.
6. **Estado activo**: el proyecto tiene ~45k stars y releases frecuentes a mediados de 2026.

gptme es un buen segundo si se necesita algo más ligero o se quiere scripting de agente sin la complejidad git.

---

## 2. Configuración exacta de Aider con proxy LiteLLM

### Métodos de conexión (dos enfoques)

Aider soporta dos formas de conectar con un proxy LiteLLM:

**Método A: prefijo `openai/` (recomendado para proxy OpenAI-compatible)**

```bash
export OPENAI_API_BASE="http://localhost:4000"
export OPENAI_API_KEY="<tu-master-key>"

aider --model openai/codigo
```

LiteLLM en Aider usará el driver OpenAI y enviará la request al alias `codigo` en tu proxy. El prefijo `openai/` le indica a LiteLLM que use el driver OpenAI (y por tanto tu `OPENAI_API_BASE`). El proxy recibirá la petición con `model=codigo` (sin prefijo).

**Método B: prefijo `litellm_proxy/` (más explícito)**

```bash
export LITELLM_PROXY_API_BASE="http://localhost:4000"
export LITELLM_PROXY_API_KEY="<tu-master-key>"

aider --model litellm_proxy/codigo
```

Este método usa el driver litellm_proxy nativo. Fuentes: [issue #3218 de Aider](https://github.com/Aider-AI/aider/issues/3218), [issue #949](https://github.com/Aider-AI/aider/issues/949).

---

### Archivo `.aider.conf.yml` recomendado

Crear en el directorio raíz del proyecto o en `~/.aider.conf.yml`:

```yaml
##########################################################
# .aider.conf.yml — Configuración para proxy LiteLLM local
# Modelos 7-8B: Llama 3.1 8B, Qwen2.5-Coder 7B
##########################################################

# === Endpoint del proxy LiteLLM ===
openai-api-base: http://localhost:4000
openai-api-key: <tu-master-key>

# === Modelo principal ===
# El prefijo openai/ indica a litellm que use driver OpenAI
# El alias 'codigo' debe existir en tu LiteLLM config
model: openai/codigo

# === Modelo débil (commits, resúmenes) ===
# Usar el mismo alias rápido o uno específico para tareas simples
# Si tienes un alias 'instantaneo' para modelos más rápidos:
weak-model: openai/instantaneo
# Alternativa: desactivar completamente el weak model:
# weak-model: null

# === Formato de edición ===
# CRÍTICO para modelos 7-8B: usar 'whole' en lugar de 'diff'
# Los modelos pequeños generan diff malformados con frecuencia
edit-format: whole

# === Repo map ===
# Modelos débiles se confunden con el repo map; reducir o desactivar
# 0 = desactivado, 512-1024 = proyectos pequeños
map-tokens: 512

# === Commits automáticos ===
# Recomendado desactivar para verificar la salida de modelos locales
auto-commits: false

# === Advertencias de modelo desconocido ===
# Silenciar warnings sobre context window desconocido (normal con aliases LiteLLM)
show-model-warnings: false

# === Archivos de configuración avanzada ===
model-settings-file: .aider.model.settings.yml
model-metadata-file: .aider.model.metadata.json

# === Timeout ===
# Modelos locales pueden ser lentos; aumentar timeout
timeout: 300

# === Otras opciones útiles ===
# No verificar actualizaciones (opcional)
check-update: false
# Modo oscuro en terminal
dark-mode: true
```

---

### Archivo `.aider.model.settings.yml`

Este archivo define comportamiento específico para los modelos de tu proxy. Crear en el directorio del proyecto o en `~/.aider.model.settings.yml`:

```yaml
# Configuración de comportamiento para modelos locales via LiteLLM proxy
# Fuente: https://aider.chat/docs/config/adv-model-settings.html

# Configuración global: parámetros extra para TODOS los modelos
- name: aider/extra_params
  extra_params:
    max_tokens: 8192
    # Si el proxy no soporta bien el streaming (opcional):
    # stream: false

# Configuración específica para el alias 'codigo' (modelo principal)
- name: openai/codigo
  edit_format: whole           # Formato completo: más fiable con modelos 7-8B
  weak_model_name: openai/instantaneo  # Modelo para commits y resúmenes
  use_repo_map: false          # Desactivar repo map para modelos débiles
  # Alternativa: use_repo_map: true con map_tokens reducido
  use_system_prompt: true
  use_temperature: true
  streaming: true              # Cambiar a false si hay problemas de streaming
  send_undo_reply: false
  examples_as_sys_msg: true    # Incluir ejemplos en system message (mejor para modelos pequeños)
  reminder: user               # Recordatorio del formato en mensajes user
  caches_by_default: false
  cache_control: false

# Configuración para el alias 'instantaneo' (modelo rápido para weak tasks)
- name: openai/instantaneo
  edit_format: whole
  weak_model_name: openai/instantaneo  # Apuntarse a sí mismo
  use_repo_map: false
  use_system_prompt: true
  use_temperature: true
  streaming: true
  examples_as_sys_msg: true
  reminder: user
```

**Nota**: La configuración `weak_model_name: openai/instantaneo` hace que el modelo rápido se use para commits y resúmenes de historial, evitando el overhead del modelo principal en tareas simples.

---

### Archivo `.aider.model.metadata.json`

Informa a Aider sobre el context window y costos de modelos desconocidos (los aliases del proxy no están en la base de datos de LiteLLM):

```json
{
  "openai/codigo": {
    "max_tokens": 8192,
    "max_input_tokens": 131072,
    "max_output_tokens": 8192,
    "input_cost_per_token": 0.0,
    "output_cost_per_token": 0.0,
    "litellm_provider": "openai",
    "mode": "chat"
  },
  "openai/instantaneo": {
    "max_tokens": 8192,
    "max_input_tokens": 131072,
    "max_output_tokens": 8192,
    "input_cost_per_token": 0.0,
    "output_cost_per_token": 0.0,
    "litellm_provider": "openai",
    "mode": "chat"
  }
}
```

**Notas**:
- `max_input_tokens: 131072` es para Llama 3.1 8B (128k context). Para Qwen2.5-Coder 7B usar 32768.
- Costos en 0.0 porque el proxy local no tiene coste por token.
- El campo `litellm_provider: "openai"` es lo que le dice a Aider que use el driver OpenAI (y por tanto tu `OPENAI_API_BASE`). Fuente: [docs avanzados de Aider](https://aider.chat/docs/config/adv-model-settings.html).

---

### Comando de invocación rápida

```bash
# Variables de entorno (o en .env en el directorio del proyecto)
export OPENAI_API_BASE="http://localhost:4000"
export OPENAI_API_KEY="<tu-master-key>"

# Ejecutar aider en un proyecto git
cd /path/to/proyecto
aider --no-show-model-warnings archivo1.py archivo2.py

# Con flags explícitos (si no usas .aider.conf.yml):
aider \
  --model openai/codigo \
  --weak-model openai/instantaneo \
  --edit-format whole \
  --map-tokens 0 \
  --no-auto-commits \
  --no-show-model-warnings \
  --timeout 300 \
  archivo1.py
```

---

### Alternativa: prefijo `litellm_proxy/`

Si prefieres el prefijo `litellm_proxy/` (más explícito sobre el origen de los modelos):

```yaml
# En .aider.conf.yml
model: litellm_proxy/codigo
weak-model: litellm_proxy/instantaneo
set-env:
  - LITELLM_PROXY_API_BASE=http://localhost:4000
  - LITELLM_PROXY_API_KEY=<tu-master-key>
```

Y en `.aider.model.metadata.json` usar `"litellm_proxy/codigo"` como clave con `"litellm_provider": "litellm_proxy"`.

---

## 3. Instalación de Aider: mejores prácticas 2025/2026

### Métodos recomendados (de más a menos preferido)

#### Método 1: `aider-install` via uv (RECOMENDADO)

```bash
pip install aider-install
aider-install
```

Este es el método canónico recomendado desde enero 2025 ([blog oficial](https://aider.chat/2025/01/15/uv.html)). Internamente:
- Instala `uv` como dependencia
- Ejecuta `uv tool install --python python3.12 aider-chat`
- Instala Aider en un entorno aislado con Python 3.12
- Actualiza el PATH automáticamente

**Ventajas**: entorno completamente aislado, no contamina el Python del sistema, muy rápido, instala Python 3.12 automáticamente si es necesario.

#### Método 2: Script de instalación (una sola línea)

```bash
curl -LsSf https://aider.chat/install.sh | sh
```

Equivalente al método 1 pero sin requerir Python previo. Instala uv y luego Aider. Válido para macOS y Linux.

#### Método 3: uv directamente

```bash
pip install uv
uv tool install --force --python python3.12 --with pip aider-chat@latest
```

#### Método 4: pipx

```bash
pip install pipx
pipx install aider-chat
```

Compatible con Python 3.9–3.12. **Importante**: no usar Python 3.13, que no es compatible con Aider a mediados de 2026 (dependencias como numpy no compilaban). Fuente: [issue #4340](https://github.com/aider-ai/aider/issues/4340).

#### Método 5: pip directo (menos recomendado)

```bash
pip install -U --upgrade-strategy only-if-needed aider-chat
```

Riesgo de conflictos de dependencias con el entorno Python existente. Usar solo en virtualenv dedicado.

### Resumen de compatibilidad Python

| Python | pip | pipx | uv/aider-install |
|---|---|---|---|
| 3.8 | Solo para instalar aider-install | ❌ | ✅ (bootstrap) |
| 3.9–3.12 | ✅ | ✅ | ✅ |
| 3.12 | ✅ (recomendado) | ✅ | ✅ (target) |
| 3.13 | ❌ | ❌ | ✅ (instala 3.12) |

**El paquete canonical es `aider-chat`**. El paquete `aider-install` es solo el instalador que usa uv internamente. Fuentes: [docs de instalación de Aider](https://aider.chat/docs/install.html), [PyPI aider-install](https://pypi.org/project/aider-install/).

---

## 4. Problemas conocidos: Aider + proxy LiteLLM

### 4.1. Advertencias de modelo desconocido ("Unknown context window")

**Síntoma**: Al arrancar Aider con un alias personalizado (ej. `openai/codigo`), aparece:
```
Model openai/codigo: Unknown context window size and costs, using sane defaults.
```

**Causa**: El alias no está en la base de datos de LiteLLM (`model_prices_and_context_window.json`).

**Soluciones**:
1. Crear `.aider.model.metadata.json` con la metadata del modelo (recomendado)
2. Pasar `--no-show-model-warnings` para silenciar el warning
3. El warning es inofensivo si no se necesita tracking de costos preciso

Fuente: [docs de warnings de Aider](https://aider.chat/docs/troubleshooting/warnings.html), [issue #3323](https://github.com/Aider-AI/aider/issues/3323).

---

### 4.2. Errores de tracking de costos

**Síntoma**: Aider puede mostrar costos incorrectos o errores al calcular el costo de las peticiones a modelos locales.

**Causa**: Los modelos locales no tienen precio en la base de datos de LiteLLM. Aider usará $0 por defecto si el modelo está configurado en `.aider.model.metadata.json` con `input_cost_per_token: 0.0`.

**Solución**: Definir los modelos en `.aider.model.metadata.json` con costos en 0. Esto elimina el error de "unknown costs" sin afectar la funcionalidad.

---

### 4.3. Problemas de streaming

**Síntoma 1**: `litellm.APIConnectionError: argument of type 'NoneType' is not iterable` en streaming.

**Causa**: Bug histórico de LiteLLM con proxies que reenvían respuestas Anthropic con campos `null` en usage. Corregido en Aider v1.73.6-stable. Fuente: [issue #4382](https://github.com/aider-ai/aider/issues/4382).

**Síntoma 2**: Timeouts o respuestas incompletas con streaming en proxies locales.

**Causa**: El proxy LiteLLM puede tener timeouts de gateway para peticiones largas sin streaming. Streaming mantiene la conexión activa y evita el problema.

**Solución general**: Mantener streaming activado (por defecto en Aider). Si hay problemas, agregar en `.aider.model.settings.yml`:
```yaml
- name: aider/extra_params
  extra_params:
    stream: false  # Solo como último recurso
```

O via CLI: `aider --no-stream`

---

### 4.4. Repo map y modelos débiles

**Síntoma**: El modelo emite ediciones en el contenido del repo map en lugar de en los archivos reales.

**Causa**: Los modelos 7-8B frecuentemente se confunden con la información del repo map e intentan "editar" el mapa en lugar del código real. Fuente: [FAQ de Aider](https://aider.chat/docs/faq.html).

**Solución**: Desactivar o reducir el repo map con `--map-tokens 0` o `map-tokens: 0` en `.aider.conf.yml`. Para proyectos pequeños, `map-tokens: 256` puede ser un compromiso útil.

---

### 4.5. Formato de edición `diff` fallando silenciosamente

**Síntoma**: Aider reporta que aplica cambios pero el archivo no se modifica, o los bloques SEARCH/REPLACE no coinciden.

**Causa**: Los modelos 7-8B con cuantización generan bloques `diff` con marcadores incorrectos. Aider falla silenciosamente al aplicar el diff. Fuente: [issue #2371](https://github.com/Aider-AI/aider/issues/2371), [modelfit.io tier list](https://modelfit.io/tools/aider/).

**Solución**: Usar siempre `--edit-format whole` con modelos locales pequeños. El formato `whole` devuelve el archivo completo y es más robusto aunque menos eficiente en tokens.

---

### 4.6. Context window insuficiente (proxy vs modelo real)

**Síntoma**: Errores de contexto excedido o respuestas truncadas.

**Causa**: Si el proxy LiteLLM tiene configurado un `max_tokens` o `max_context` diferente al modelo real, Aider puede enviar prompts más grandes de lo que el backend puede manejar.

**Solución**: Definir explícitamente `max_input_tokens` en `.aider.model.metadata.json` basado en la capacidad real del modelo servido:
- Llama 3.1 8B: 131072 tokens de contexto
- Qwen2.5-Coder 7B: 32768 tokens (32k context)

Para proyectos grandes con contexto limitado, usar `--map-tokens 0` y añadir solo los archivos estrictamente necesarios al chat.

---

## Configuración completa recomendada (resumen ejecutivo)

### Estructura de archivos

```
~/
├── .aider.conf.yml              # Config principal (o en raíz del repo)
├── .aider.model.settings.yml   # Comportamiento del modelo
└── .aider.model.metadata.json  # Metadata de context window y costos

.env (en raíz del proyecto git):
  OPENAI_API_BASE=http://localhost:4000
  OPENAI_API_KEY=<master-key>
```

### `.aider.conf.yml` mínimo funcional

```yaml
openai-api-base: http://localhost:4000
openai-api-key: <tu-master-key>
model: openai/codigo
weak-model: openai/instantaneo
edit-format: whole
map-tokens: 0
auto-commits: false
show-model-warnings: false
timeout: 300
model-settings-file: .aider.model.settings.yml
model-metadata-file: .aider.model.metadata.json
```

### `.aider.model.settings.yml` mínimo funcional

```yaml
- name: openai/codigo
  edit_format: whole
  weak_model_name: openai/instantaneo
  use_repo_map: false
  use_system_prompt: true
  use_temperature: true
  streaming: true
  examples_as_sys_msg: true
  reminder: user

- name: openai/instantaneo
  edit_format: whole
  weak_model_name: openai/instantaneo
  use_repo_map: false
  use_system_prompt: true
  use_temperature: true
  streaming: true
  examples_as_sys_msg: true
  reminder: user
```

### `.aider.model.metadata.json` para ambos alias

```json
{
  "openai/codigo": {
    "max_tokens": 8192,
    "max_input_tokens": 32768,
    "max_output_tokens": 8192,
    "input_cost_per_token": 0.0,
    "output_cost_per_token": 0.0,
    "litellm_provider": "openai",
    "mode": "chat"
  },
  "openai/instantaneo": {
    "max_tokens": 4096,
    "max_input_tokens": 32768,
    "max_output_tokens": 4096,
    "input_cost_per_token": 0.0,
    "output_cost_per_token": 0.0,
    "litellm_provider": "openai",
    "mode": "chat"
  }
}
```

> **Nota sobre `max_input_tokens`**: Ajustar según el modelo real servido en cada alias. Qwen2.5-Coder 7B tiene contexto nativo de 32768 tokens. Llama 3.1 8B tiene 131072. Si el proxy limita el contexto, usar el valor más restrictivo.

---

## Referencias

- [Documentación de instalación de Aider](https://aider.chat/docs/install.html)
- [Opciones de referencia de Aider (CLI flags)](https://aider.chat/docs/config/options.html)
- [Configuración YAML de Aider](https://aider.chat/docs/config/aider_conf.html)
- [Configuración avanzada de modelos en Aider](https://aider.chat/docs/config/adv-model-settings.html)
- [Formatos de edición en Aider](https://aider.chat/docs/more/edit-formats.html)
- [Advertencias de modelo en Aider](https://aider.chat/docs/troubleshooting/warnings.html)
- [LiteLLM: proveedor litellm_proxy](https://docs.litellm.ai/docs/providers/litellm_proxy)
- [Issue #3218: Configuración de LiteLLM proxy en Aider](https://github.com/Aider-AI/aider/issues/3218)
- [Issue #3323: Aliasing de modelos con LiteLLM en Aider](https://github.com/Aider-AI/aider/issues/3323)
- [Issue #2371: Formato diff con modelos locales Qwen](https://github.com/Aider-AI/aider/issues/2371)
- [Issue #4382: Bug de streaming LiteLLM con proxy Anthropic](https://github.com/aider-ai/aider/issues/4382)
- [aider.chat/2025/01/15/uv.html — uv como instalador](https://aider.chat/2025/01/15/uv.html)
- [PyPI: aider-install](https://pypi.org/project/aider-install/)
- [Leaderboard de edición de Aider](https://aider.chat/docs/leaderboards/edit.html)
- [OpenHands: modelos locales](https://docs.openhands.dev/openhands/usage/llms/local-llms)
- [GitHub: OpenHands](https://github.com/OpenHands/openhands)
- [GitHub: Plandex](https://github.com/plandex-ai/plandex)
- [GitHub: gptme](https://github.com/gptme/gptme)
- [Goose docs](https://goose-docs.ai)
- [Goose + Ollama (guía jun 2026)](https://localaimaster.com/blog/goose-ollama-local-agent)
- [modelfit.io: Best Local LLMs for Aider 2026](https://modelfit.io/tools/aider/)
- [failingfast.io: Local AI Models for Coding 2026](https://failingfast.io/local-coding-ai-models/)
- [Continue.dev: Model Setup for Agent Mode](https://docs.continue.dev/ide-extensions/agent/model-setup)
- [Comparativa CLI agents open-source mid-2026 (pinggy.io)](https://pinggy.io/blog/best_open_source_cli_coding_agents/)
- [UnoRouter: Aider Setup Guide (openai/ prefix)](https://unorouter.com/en/docs/aider)
