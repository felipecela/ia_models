# OMEN AI Cluster V12 — Análisis Exhaustivo y Plan de Mejora
### HP OMEN 255 · Intel Ultra 7 · RTX 4070 8GB VRAM · 32GB RAM · SSD exFAT

***

## Resumen ejecutivo

El clúster implementado en V11 representa una arquitectura sólida y bien estructurada: Phi-4 como clasificador CPU-only, cinco niveles de razonamiento (INSTANTANEO/AGIL/PROFUNDO/MASIVO/CODIGO), gestión de exclusión mutua de VRAM y una integración correcta con OpenClaw. Sin embargo, la investigación identifica **ocho áreas de mejora prioritarias** que pueden transformarlo en una infraestructura más rápida, flexible, robusta y capaz de funcionar verdaderamente como un sistema multi-agente, en lugar de un router de prompts unidireccional.

***

## 1. Inventario actual y valoración del estado V11

### Estado de los modelos descargados

| Motor | Directorio | Modelo | Tamaño | Rol V11 | Valoración |
|-------|-----------|--------|--------|---------|-----------|
| ExLlamaV2/TabbAPI | `exllamav2_storage/qwen2.5-coder-7b-exl2` | Qwen2.5 Coder 7B | 6.95 GB | INSTANTANEO | ✅ Óptimo para código rápido |
| ExLlamaV2/TabbAPI | `exllamav2_storage/llama-3.1-8b-exl2` | Llama 3.1 8B | 6.71 GB | No asignado | ⚠️ Infrautilizado — sin nivel propio |
| SGLang | `sglang_storage/llama-3.1-8b-awq` | Llama 3.1 8B AWQ | 5.74 GB | AGIL | ✅ Correcto para agentes |
| Ollama GPU | `ollama_storage` | DeepSeek R1 14B | 9.0 GB | PROFUNDO | ⚠️ Candidato a actualización (ver sección 4) |
| Ollama GPU | `ollama_storage` | DeepSeek Coder V2 | ~8 GB | CODIGO | ⚠️ Superado por Qwen2.5-Coder que ya está descargado |
| Ollama GPU | `ollama_storage` | Qwen2.5 32B | 19 GB | MASIVO | ✅ Mejor modelo disponible para análisis masivo |
| Ollama CPU | `ollama_storage` | Phi-4 | 9.1 GB | Clasificador | ⚠️ Sobredimensionado para clasificación — ver alternativas |

### Fortalezas de V11

- **Exclusión mutua de VRAM**: correctamente implementada; evita OOM con 8 GB.[^1]
- **Phi-4 CPU-only en puerto 11435**: elimina la colisión de VRAM con los backends de inferencia, problema crítico de V10.[^1]
- **Cinco niveles de routing**: aprovecha todos los motores y modelos descargados de forma racional.[^1]
- **Health checks con polling activo**: el router espera hasta 62.5 s antes de enviar requests a un backend recién arrancado.[^1]
- **Caché LRU de 256 entradas**: prompts idénticos no re-invocan Phi-4.[^1]
- **Configuración correcta de OpenClaw** (`openclaw.json` con `models.providers`): corrige el bug crítico de V10 donde `initial_providers.json` era ignorado silenciosamente.[^2][^1]

### Limitaciones identificadas

1. **Phi-4 (9.1 GB) es excesivo como clasificador puro**: tarda 2-5 s en CPU para una clasificación de texto simple.[^1]
2. **Nivel CODIGO duplica responsabilidades** con INSTANTANEO (ambos sirven código) sin diferenciación clara de complejidad.[^1]
3. **Llama 3.1 8B EXL2 no tiene nivel asignado** y queda infrautilizado.[^1]
4. **OpenClaw opera como cliente pasivo**: no explota las capacidades de multi-agente y subagentes que ofrece OpenClaw.[^3][^4]
5. **Routing unidireccional**: Phi-4 clasifica *una sola vez* por request. No hay retroalimentación ni re-routing si el primer backend falla por complejidad del prompt.
6. **DeepSeek R1 14B no es la versión más capaz disponible**: existe DeepSeek R1-0528 con mejoras sustanciales y la variante `DeepSeek-R1-0528-Qwen3-8B` que en pruebas supera a Qwen3-235B-thinking en AIME 2024.[^5]

***

## 2. Análisis del clasificador Phi-4: el cuello de botella

El mayor punto de mejora en V11 es el clasificador Phi-4, que con 9.1 GB en CPU tarda entre 2 y 5 segundos por clasificación, añadiendo latencia visible en cada petición auto-ruteada.

### Opción A: Phi-4-mini (recomendada como mejora inmediata)

Phi-4-mini cuenta con 3.8B parámetros frente a los 14B de Phi-4-full, soporta 128K tokens de contexto y su rendimiento en tareas de razonamiento e instrucción es comparable a modelos del rango 7B-9B. Con licencia MIT y cuantización Q4 en GGUF, su huella en disco sería de ~2.5 GB, frente a los 9.1 GB actuales. En CPU la diferencia de velocidad puede ser de 3-4x en favor de Phi-4-mini, reduciendo la latencia de clasificación a ~0.5-1.5 s.[^6]

```bash
# Instalar en la instancia CPU (puerto 11435)
docker exec ollama-cpu-router ollama pull phi4-mini
# Actualizar PHI4_MODEL en orchestrator_router_V5.py:
# PHI4_MODEL = "phi4-mini"
```

### Opción B: Router semántico con embeddings (recomendada para V12)

La alternativa más avanzada es reemplazar el clasificador LLM por un **router semántico basado en embeddings**. En lugar de invocar un LLM para clasificar, se calculan vectores de embeddings para el prompt entrante y se compara por similitud coseno contra vectores de referencia precalculados para cada nivel (INSTANTANEO, AGIL, PROFUNDO, MASIVO, CODIGO).[^7][^8]

**Ventajas medidas experimentalmente**:[^9]
- Latencia de clasificación: **~26 ms** frente a **3,431 ms** con LLM (~132x más rápido)
- 0% de hallucination rate en clasificación estructurada
- No consume VRAM ni CPU intensivo en producción

**Modelo de embeddings recomendado**: `nomic-embed-text` vía Ollama (~274 MB). Ya está disponible como `ollama pull nomic-embed-text` y puede correr en la misma instancia CPU sin competir con Phi-4-mini.[^7]

```python
# Fragmento conceptual para orchestrator_router_V6.py
import ollama
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np

ROUTE_DESCRIPTIONS = {
    "INSTANTANEO": "saludos, preguntas sencillas, traducciones cortas, conversación ligera, autocompletado",
    "AGIL": "resúmenes de documentos, agentes multi-paso, análisis de archivos, conversaciones largas con contexto",
    "PROFUNDO": "razonamiento matemático, debugging de errores complejos, lógica avanzada, problemas que requieren pensar",
    "MASIVO": "análisis de libros, documentos muy largos, logs con cientos de líneas, revisión de codebases completas",
    "CODIGO": "escritura de código C/C++/Python/Bash, refactorización, completado de funciones, análisis de algoritmos",
}

async def _precalcular_vectores_ruta():
    """Precalcula los embeddings de referencia al arrancar el router."""
    vectores = {}
    for nivel, desc in ROUTE_DESCRIPTIONS.items():
        resp = ollama.embeddings(model="nomic-embed-text", prompt=desc)
        vectores[nivel] = np.array(resp["embedding"])
    return vectores

async def _clasificar_con_embeddings(prompt: str, vectores_ruta: dict) -> str:
    resp = ollama.embeddings(model="nomic-embed-text", prompt=prompt[:300])
    v_query = np.array(resp["embedding"]).reshape(1, -1)
    scores = {
        nivel: cosine_similarity(v_query, v.reshape(1, -1))
        for nivel, v in vectores_ruta.items()
    }
    return max(scores, key=scores.get)
```

Esta estrategia híbrida puede mantenerse junto a Phi-4-mini: usar embeddings para la mayoría de casos simples y Phi-4-mini solo cuando el score máximo de similitud sea bajo (ambigüedad alta), logrando el mejor balance velocidad/precisión.

***

## 3. Optimización del pipeline de OpenClaw: de cliente a orquestador

OpenClaw no es solo una interfaz web: posee un sistema completo de **agentes, subagentes y routing basado en canales**. La configuración V11 solo explota una pequeña fracción de estas capacidades.[^10][^3]

### 3.1 Arquitectura multi-agente nativa de OpenClaw

El fichero `openclaw.json` soporta definir múltiples agentes con identidades, workspaces y modelos diferenciados. Cada agente puede:[^4][^10]
- Tener un **modelo primario y fallbacks** independientes.
- Estar configurado con **subagentes paralelos** para tareas delegadas.[^4]
- Recibir tráfico de canales específicos (Telegram, WhatsApp, etc.).[^10]
- Tener su propio directorio de workspace con `AGENTS.md` para instrucciones de sistema.[^10]

### 3.2 Configuración V12 de openclaw.json: agentes especializados

La propuesta es pasar de un único agente genérico (`ruteador-auto`) a **cuatro agentes especializados** con diferentes configuraciones de modelo:

```jsonc
// ~/.openclaw/openclaw.json (dentro del contenedor: /data/.openclaw/openclaw.json)
{
  "models": {
    "mode": "merge",
    "providers": {
      "local_router": {
        "baseUrl": "http://host.docker.internal:8000/v1",
        "apiKey": "sk-router-local",
        "api": "openai-completions",
        "models": [
          { "id": "ruteador-auto", "name": "🤖 Auto — Phi-4 elige el nivel",
            "contextWindow": 32768, "maxTokens": 4096 },
          { "id": "instantaneo",   "name": "⚡ Instantáneo (ExLlamaV2)",
            "contextWindow": 4096,  "maxTokens": 2048 },
          { "id": "agil",          "name": "🚀 Ágil (SGLang · agentes)",
            "contextWindow": 32768, "maxTokens": 8192 },
          { "id": "profundo",      "name": "🧠 Profundo (DeepSeek R1 14B)",
            "contextWindow": 16384, "maxTokens": 8192 },
          { "id": "masivo",        "name": "🔬 Masivo (Qwen2.5 32B)",
            "contextWindow": 32768, "maxTokens": 16384 },
          { "id": "codigo",        "name": "💻 Código (DeepSeek Coder V2)",
            "contextWindow": 16384, "maxTokens": 8192 },
          { "id": "phi4",          "name": "🔷 Phi-4 CPU (router directo)",
            "contextWindow": 16384, "maxTokens": 4096 }
        ]
      }
    }
  },
  "agents": {
    "defaults": {
      "model": {
        "primary": "local_router/ruteador-auto",
        "fallbacks": ["local_router/agil", "local_router/profundo"]
      },
      "subagents": {
        "model": "local_router/agil",
        "maxConcurrent": 2,
        "runTimeoutSeconds": 300
      },
      "thinkingDefault": "low",
      "maxConcurrent": 2,
      "timeoutSeconds": 600,
      "contextTokens": 32768
    },
    "list": [
      {
        "id": "coder",
        "name": "🖥️ Agente Coder",
        "model": {
          "primary":   "local_router/codigo",
          "fallbacks": ["local_router/profundo"]
        }
      },
      {
        "id": "analyst",
        "name": "📊 Agente Analyst",
        "model": {
          "primary":   "local_router/masivo",
          "fallbacks": ["local_router/profundo"]
        }
      },
      {
        "id": "reasoner",
        "name": "🧠 Agente Reasoner",
        "model": {
          "primary":   "local_router/profundo",
          "fallbacks": ["local_router/agil"]
        }
      }
    ]
  }
}
```

Con esta configuración, en OpenClaw aparecerá un selector de agente en la UI, y el comando `@coder` delegará a DeepSeek Coder V2, `@analyst` a Qwen2.5-32B y `@reasoner` a DeepSeek R1-14B, sin que el usuario tenga que abrir un desplegable de modelos.[^11][^3]

### 3.3 Subagentes en OpenClaw: delegación automática de tareas

OpenClaw soporta configurar `subagents.model` para las tareas delegadas internamente por el agente principal. Esto permite a Phi-4 (agente principal) no solo *clasificar* sino también *delegar subtareas* en subagentes corriendo en paralelo. Por ejemplo, un análisis de múltiples documentos puede dividirse: el agente `masivo` analiza el documento completo, mientras un subagente `codigo` extrae fragmentos de código relevantes simultáneamente. La configuración `maxConcurrent: 2` controla el techo de subagentes paralelos respetando los límites de VRAM.[^4]

***

## 4. Actualización de modelos: oportunidades en 2025-2026

### 4.1 DeepSeek R1-0528-Qwen3-8B: actualización crítica para el nivel PROFUNDO

En mayo de 2025, DeepSeek publicó `DeepSeek-R1-0528-Qwen3-8B`, un destilado del nuevo R1-0528 sobre la base Qwen3-8B. Sus mejoras respecto al `deepseek-r1:14b` actual son significativas:[^5]

| Benchmark | DeepSeek R1 14B (actual) | DeepSeek R1-0528-Qwen3-8B | Ganancia |
|-----------|--------------------------|---------------------------|----------|
| AIME 2024 (Pass@1) | ~61%* | **86.0%** | +25 pts |
| AIME 2025 (Pass@1) | ~50%* | **76.3%** | +26 pts |
| GPQA Diamond | ~55%* | **61.1%** | +6 pts |
| LiveCodeBench | ~55%* | **60.5%** | +5 pts |

*estimado basado en escalado del modelo 14B distill[^5]

Crucialmente, el modelo `deepseek-r1:14b` en Ollama fue **silenciosamente sustituido** por el nuevo `deepseek-r1:8b-0528-qwen3-q4_K_M` en algunos registros. Conviene verificar qué versión exacta está instalada con:[^12]

```bash
ollama show deepseek-r1:14b --verbose
```

Si se está usando el destilado original (enero 2025), considerar migrar al nuevo modelo con:

```bash
ollama pull deepseek-r1:8b-0528-qwen3  # ~5.2 GB — cabe completamente en 8GB VRAM
```

La variante 8B ocupa menos VRAM que el 14B actual, liberando margen para la caché KV y reduciendo el tiempo de carga.

### 4.2 Qwen3-8B: alternativa para el nivel PROFUNDO con modo thinking/non-thinking

Qwen3-8B soporta de forma nativa dos modos en un solo modelo: **modo thinking** (Chain of Thought para problemas complejos) y **modo non-thinking** (respuesta directa para tareas simples). Esto es relevante para el router: el nivel PROFUNDO podría usar Qwen3-8B con `enable_thinking=True` y el nivel AGIL podría usar el mismo modelo con `enable_thinking=False`, eliminando la necesidad de cambiar de backend para ambos niveles y reduciendo drásticamente la latencia de conmutación.[^13]

```bash
ollama pull qwen3:8b   # ~5.2 GB GGUF Q4_K_M
```

El router debería inyectar el flag de thinking en el system prompt:
```python
# Para nivel PROFUNDO con Qwen3:
body["messages"].insert(0, {
    "role": "system",
    "content": "/think"  # activa Chain of Thought en Qwen3
})
# Para nivel AGIL (mismo modelo):
body["messages"].insert(0, {
    "role": "system",
    "content": "/no_think"  # respuesta directa
})
```

### 4.3 Qwen2.5-Coder-7B para el nivel CODIGO: mejor que DeepSeek Coder V2

El modelo `DeepSeek Coder V2` (~8 GB en Ollama) que actualmente ocupa el nivel CODIGO tiene un problema: el modelo `qwen2.5-coder-7b-exl2` que ya está descargado en TabbAPI supera a DeepSeek Coder V2 en benchmarks de autocompletado a velocidad muy superior gracias a ExLlamaV2. La propuesta es:[^14][^1]

- **CODIGO corto** (snippets, funciones): → TabbAPI (ExLlamaV2) con `qwen2.5-coder-7b-exl2` (nivel INSTANTANEO actual)
- **CODIGO profundo** (proyectos completos, debugging, refactoring): → Ollama con `deepseek-r1:14b` (nivel PROFUNDO)

Esto simplifica el catálogo eliminando el nivel CODIGO redundante y libera ~8 GB en disco que puede dedicarse a un modelo más útil.

### 4.4 Llama-3.1-8B EXL2: asignar nivel CHAT rápido

El modelo `llama-3.1-8b-exl2` (6.71 GB) que está descargado pero sin nivel propio debería ser la alternativa de INSTANTANEO para conversación general, mientras `qwen2.5-coder-7b-exl2` se especializa en código. TabbAPI soporta carga dinámica de modelos vía su API `/v1/model/load`:

```bash
# Cargar Llama 3.1 en lugar de Qwen Coder
curl -X POST http://localhost:5000/v1/model/load \
  -H "Content-Type: application/json" \
  -d '{"name": "llama-3.1-8b-exl2"}'
```

El router puede exponer un nivel `CHAT` que Phi-4 asigna a saludos, conversación casual y preguntas generales, mientras INSTANTANEO queda reservado para código.

***

## 5. Mejoras en el script Autoboot_Cluster_V11.sh

### 5.1 Verificación de modelos antes de arrancar backends

El script actual verifica que los **directorios** existen pero no verifica que el **modelo correcto esté presente** dentro. Esto puede causar que TabbAPI arranque pero no encuentre `qwen2.5-coder-7b-exl2`, fallando silenciosamente:

```bash
# Añadir en VERIFICACIONES PREVIAS (antes del paso 1):
step "VERIFICACIONES DE MODELOS"

# Verificar modelo ExLlamaV2
[ -d "$EXLLAMA_MODELS_DIR/qwen2.5-coder-7b-exl2" ] || {
    error "Modelo ExLlamaV2 no encontrado: qwen2.5-coder-7b-exl2"
    info "Descárgalo con: hf download bartowski/Qwen2.5-Coder-7B-Instruct-exl2 --revision 6_5 --local-dir qwen2.5-coder-7b-exl2"
    exit 1
}

# Verificar modelo SGLang
[ -d "$SGLANG_MODELS_DIR/llama-3.1-8b-awq" ] || {
    error "Modelo SGLang no encontrado: llama-3.1-8b-awq"
    exit 1
}

# Verificar phi4 en Ollama (lista de modelos)
phi4_present=$(ollama list 2>/dev/null | grep -c "phi4" || echo "0")
[ "$phi4_present" -gt 0 ] || {
    warn "phi4 no instalado. Instalando..."
    ollama pull phi4
}
ok "Modelos verificados"
```

### 5.2 Parámetro `--context-length` en SGLang para exFAT

El montaje de modelos desde exFAT tiene latencia de I/O superior a ext4 en carga inicial. Para reducir el tiempo de arranque de SGLang, añadir:

```bash
# En la definición del contenedor SGLang (paso 5):
docker create \
  --gpus all \
  --name sglang-server \
  --ipc=host \
  -p 30000:30000 \
  -v "${SGLANG_MODELS_DIR}":/models \
  --shm-size=2gb \
  lmsysorg/sglang:latest \
  python3 -m sglang.launch_server \
    --model-path /models/llama-3.1-8b-awq \
    --quantization awq \
    --served-model-name llama-3.1-8b-awq \
    --port 30000 \
    --host 0.0.0.0 \
    --context-length 32768 \
    --mem-fraction-static 0.85 \
    --enable-cache-report
```

El flag `--mem-fraction-static 0.85` reserva el 85% de la VRAM para el modelo y caché KV, evitando fragmentación dinámica que reduce la velocidad con RadixAttention.[^15]

### 5.3 Warmup automático del modelo más frecuente

Añadir al final del script (tras el paso 7), un warmup que carga el modelo más probable en VRAM antes del primer request real:

```bash
step "PASO OPCIONAL: Warmup del backend por defecto"
info "Enviando prompt de warmup a Ollama GPU (DeepSeek R1 14B)…"
curl -s -X POST http://localhost:11434/api/generate \
  -d '{"model":"deepseek-r1:14b","prompt":"Hola","stream":false,"options":{"num_predict":1}}' \
  -o /dev/null && ok "Warmup completado — modelo en VRAM" || warn "Warmup falló (no crítico)"
```

### 5.4 Modo `--no-gpu` explícito en el contenedor ollama-cpu-router

Actualmente el contenedor usa `CUDA_VISIBLE_DEVICES=""` para forzar CPU, pero en algunos entornos Docker con drivers NVIDIA recientes esta variable puede ser ignorada. Añadir el flag `--gpus ""` (sin GPU) es más robusto:

```bash
# Paso 3: Ollama CPU-only — cambiar:
docker run -d \
  --name ollama-cpu-router \
  --restart unless-stopped \
  -p 11435:11434 \
  --gpus ""   \                  # ← fuerza CPU a nivel Docker runtime
  -e CUDA_VISIBLE_DEVICES="" \   # ← backup a nivel variable de entorno
  -e OLLAMA_MODELS=/models \
  -e OLLAMA_HOST=0.0.0.0:11434 \
  -v "${OLLAMA_MODELS_DIR}":/models \
  ollama/ollama
```

***

## 6. Mejoras en orchestrator_router_V5.py → V6

### 6.1 Re-routing dinámico por timeout

Actualmente si un backend tarda más de 360 segundos se cancela la petición. Una mejora es re-rutear automáticamente a un nivel inferior si el timeout supera un umbral configurable:

```python
_TIMEOUT_FALLBACK: dict[str, str] = {
    "MASIVO":  "PROFUNDO",   # Si Qwen 32B tarda > 120s, caer a DeepSeek R1 14B
    "PROFUNDO": "AGIL",      # Si DeepSeek R1 tarda > 60s, caer a SGLang
    "CODIGO":  "INSTANTANEO", # Si DeepSeek Coder tarda > 30s, usar ExLlamaV2
}

# En _hacer_proxy, añadir timeout por nivel:
_TIMEOUT_POR_NIVEL = {
    "INSTANTANEO": 30.0,
    "AGIL": 60.0,
    "PROFUNDO": 120.0,
    "MASIVO": 300.0,
    "CODIGO": 60.0,
}
```

### 6.2 Endpoint `/v1/chat/completions` con parámetro `agent`

OpenClaw envía el nombre del agente activo en los headers. El router puede leerlo para aplicar pre-routing sin consultar Phi-4:

```python
@app.post("/v1/chat/completions")
async def endpoint_chat(request: Request):
    body = await request.json()
    
    # Leer agente activo desde header X-OpenClaw-Agent (si está presente)
    agent_id = request.headers.get("x-openclaw-agent", "").lower()
    
    _AGENT_TO_NIVEL = {
        "coder":    "CODIGO",
        "analyst":  "MASIVO",
        "reasoner": "PROFUNDO",
    }
    
    if agent_id in _AGENT_TO_NIVEL:
        nivel = _AGENT_TO_NIVEL[agent_id]
        log.info(f"[MODO: AGENTE] '{agent_id}' → {nivel} (sin consultar Phi-4)")
    else:
        # Flujo normal: auto-routing con Phi-4 o alias manual
        ...
```

### 6.3 Métricas de uso por nivel

Añadir contadores Prometheus-compatibles para observar el uso real del clúster:

```python
from collections import Counter
import time

_metricas = {
    "requests_por_nivel": Counter(),
    "tokens_generados": Counter(),
    "errores_por_nivel": Counter(),
    "latencia_total_ms": Counter(),
    "cambios_vram": 0,
}

@app.get("/metrics")
async def endpoint_metricas():
    return {
        "requests_por_nivel": dict(_metricas["requests_por_nivel"]),
        "latencia_promedio_ms": {
            nivel: (
                _metricas["latencia_total_ms"][nivel] / _metricas["requests_por_nivel"][nivel]
                if _metricas["requests_por_nivel"][nivel] > 0 else 0
            )
            for nivel in RUTAS
        },
        "cambios_vram_total": _estado["cambios_vram"],
    }
```

### 6.4 Soporte de tool calling para DeepSeek R1-0528

La versión `deepseek-r1:14b` de enero 2025 no soporta function calling. El modelo DeepSeek R1-0528 añade soporte nativo para JSON output y function calling. El router debe inyectar correctamente el formato de herramientas cuando el body contenga `tools`:[^16]

```python
# Detectar si la petición usa tools y está ruteada a Ollama
if body.get("tools") and nivel in ("PROFUNDO", "MASIVO", "CODIGO"):
    # Verificar que el modelo activo soporta tools
    modelo = RUTAS[nivel]["modelo"]
    if "r1" in modelo and "0528" not in modelo:
        log.warning(f"[TOOLS] Modelo '{modelo}' puede no soportar tools. "
                    f"Considera actualizar a deepseek-r1:14b-0528.")
```

***

## 7. Restricciones exFAT: análisis completo y soluciones

El SSD compartido en formato exFAT impone limitaciones técnicas que el clúster ya maneja parcialmente. Aquí el análisis completo con todas las implicaciones:[^1]

| Limitación exFAT | Motores afectados | Impacto | Solución implementada/propuesta |
|-----------------|------------------|---------|--------------------------------|
| Sin symlinks | SGLang (caché HuggingFace), Ollama (algunos blobs) | SGLang puede fallar al crear symlinks de caché | Docker volumes (ext4) para cachés; solo pesos en exFAT ✅ |
| Sin permisos Unix (chmod/chown) | TabbAPI, SGLang | Contenedores sin acceso root pueden fallar | Ejecutar contenedores como root (UID 0) ✅ |
| Sin sparse files | Todos | Los archivos de modelos ocupan su tamaño real en disco | No crítico; aceptado ✅ |
| Sin sockets Unix | Todos | IPC inter-proceso imposible via socket de archivo | Toda comunicación vía TCP/IP ✅ |
| Sin atributos extendidos (xattr) | TabbAPI (metadata de modelos) | Metadata de carga puede perderse | Almacenar metadata en ext4 (home directory) ⚠️ |
| Límite de tamaño de archivo: 16 EB | Todos | No aplica con modelos actuales | N/A ✅ |
| Sensibilidad a mayúsculas: opcional | HuggingFace CLI | Nombres de modelo case-insensitive pueden resolver mal | Usar `--local-dir` con nombres en minúsculas ✅ |
| Sin journaling | Todos | Corrupción posible si se desconecta durante escritura | Solo leer modelos del SSD; escribir logs en ext4 ✅ |

**Recomendación adicional**: En Ollama, configurar `OLLAMA_TMPDIR` para que los archivos temporales de descarga vayan a ext4 y no a exFAT, evitando corrupción parcial si se interrumpe una descarga:

```bash
# Añadir en el override de systemd de Ollama:
Environment="OLLAMA_TMPDIR=/tmp/ollama_tmp"
```

***

## 8. Propuesta de arquitectura V12: diagrama completo

```
┌──────────────────────────────────────────────────────────────────────┐
│          USUARIO / OpenClaw UI :8080                                  │
│  Agentes: @auto · @coder · @analyst · @reasoner                      │
└─────────────────────────┬────────────────────────────────────────────┘
                          │  HTTP/SSE (OpenAI-compatible)
                          ▼
┌──────────────────────────────────────────────────────────────────────┐
│           Orchestrator Router V6  :8000                               │
│                                                                       │
│  ┌───────────────────────────────────────────────────────────────┐   │
│  │  Clasificador V6 (dos capas)                                   │   │
│  │  1ª: Router semántico con nomic-embed-text (~26ms)            │   │
│  │  2ª: Phi-4-mini (CPU) solo si score < umbral (~0.7s)          │   │
│  │  3ª: Override por agente OpenClaw (sin LLM, 0ms)              │   │
│  └───────────────────────────────────────────────────────────────┘   │
│                                                                       │
│  Fallback dinámico por timeout: MASIVO→PROFUNDO→AGIL                │
│  Métricas: GET /metrics                                               │
└──┬──────┬──────────────────────────┬──────────┬──────────────────────┘
   │      │                          │          │
   ▼      ▼                          ▼          ▼
CHAT    INSTANTANEO       AGIL    PROFUNDO    MASIVO
TabbAPI TabbAPI           SGLang  Ollama GPU  Ollama GPU
:5000   :5000             :30000  :11434      :11434
Llama   Qwen2.5           Llama   DeepSeek    Qwen2.5
3.1 8B  Coder 7B          3.1 AWQ R1-0528 8B  32B
6.71GB  6.95GB VRAM       5.74GB  ~5GB VRAM   8GB+11GBRAM
```

***

## 9. Plan de implementación por fases

### Fase 1 — Quick Wins (sin cambios de modelos, ~2 horas)

1. **Sustituir Phi-4 por Phi-4-mini** como clasificador: `ollama pull phi4-mini`, actualizar `PHI4_MODEL` en el router.
2. **Añadir verificaciones de modelos** al script antes del arranque (sección 5.1).
3. **Añadir flag `--gpus ""`** al contenedor ollama-cpu-router (sección 5.4).
4. **Configurar agentes en openclaw.json**: `@coder`, `@analyst`, `@reasoner` (sección 3.2).
5. **Añadir endpoint `/metrics`** al router (sección 6.3).

### Fase 2 — Actualización de modelos (~4 horas)

1. Verificar versión exacta de `deepseek-r1:14b` instalada.
2. Evaluar migración a `deepseek-r1:8b-0528-qwen3-q4_K_M` (mejor rendimiento, menor VRAM).
3. Descargar `qwen3:8b` como candidato para modo dual thinking/non-thinking.
4. Asignar nivel `CHAT` a `llama-3.1-8b-exl2` en TabbAPI.

### Fase 3 — Router semántico con embeddings (~8 horas)

1. Instalar `nomic-embed-text` en la instancia Ollama CPU.
2. Implementar `_clasificar_con_embeddings()` en el router (sección 2, Opción B).
3. Configurar sistema híbrido: embeddings primero, Phi-4-mini como fallback.
4. Medir latencia de clasificación y ajustar umbral de confianza.

### Fase 4 — Mejoras avanzadas (~1 día)

1. Implementar re-routing dinámico por timeout (sección 6.1).
2. Añadir lectura de header `x-openclaw-agent` para pre-routing (sección 6.2).
3. Configurar `OLLAMA_TMPDIR` en ext4 para descargas (sección 7).
4. Explorar TensorRT-LLM para Llama-3.1-8B (velocidad 2-3x sobre SGLang).

***

## 10. Comparativa de rendimiento esperado V11 vs V12

| Métrica | V11 actual | V12 propuesto | Mejora |
|---------|-----------|---------------|--------|
| Latencia de clasificación (auto) | 2-5 s (Phi-4 CPU) | ~26 ms (embeddings) + 0.7s fallback | ~10-100x |
| Tiempo de warmup backend (SGLang) | ~20-45 s | ~15-30 s (con --mem-fraction-static) | ~30% |
| Capacidad de código rápido | INSTANTANEO: Qwen Coder 7B | CHAT: Llama 3.1 + INSTANTANEO: Qwen Coder | +1 nivel |
| Razonamiento nivel PROFUNDO | DeepSeek R1 14B (ene 2025) | DeepSeek R1-0528-Qwen3-8B | +25 pts AIME |
| Orchestration OpenClaw | 1 agente genérico | 4 agentes especializados + subagentes | Multi-agente real |
| Observabilidad | Solo logs | Logs + métricas por nivel (`/metrics`) | +Métricas |
| Robustez ante fallos | Fallback AGIL hardcoded | Fallback dinámico por timeout y nivel | Adaptativo |

***

## 11. Referencia de comandos de verificación

```bash
# Estado completo del clúster
./Autoboot_Cluster_V11.sh --status

# Health check del router con detalle de todos los backends
curl -s http://localhost:8000/health | python3 -m json.tool

# Catálogo de modelos disponibles en OpenClaw
curl -s http://localhost:8000/v1/models | python3 -m json.tool

# Test de clasificación con Phi-4-mini (tras actualizar)
curl -s -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"ruteador-auto","messages":[{"role":"user","content":"Debuguea este memory leak en C++"}],"stream":false}' \
  | python3 -m json.tool

# Verificar qué versión de DeepSeek R1 está instalada
ollama show deepseek-r1:14b --modelfile | head -5

# Verificar uso de VRAM en tiempo real
nvidia-smi --query-gpu=memory.used,memory.free --format=csv -l 2

# Logs del router en tiempo real
tail -f ~/ruta/scripts/router_v11.log | grep -E "(MODO|PHI4|PROXY|VRAM)"
```

---

## References

1. [ANALISIS_V11.md](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/48708411/922ccb73-cc4d-4a0f-9263-cc39926fc7d1/ANALISIS_V11.md?AWSAccessKeyId=ASIA2F3EMEYEVJK7EHRF&Signature=H35DFV8nFAMUpuGqdPNrsPr05E0%3D&x-amz-security-token=IQoJb3JpZ2luX2VjEDgaCXVzLWVhc3QtMSJIMEYCIQCSmqngKJ9G%2BWb1P8r7aiGg%2FPWzqHQ8Lo7gw%2BlEwLCAvAIhAM8HZ8b0vl%2B6v%2Fwg%2BWNzgHIsLokOC6H56J1WN3iNgC%2FTKvMECAEQARoMNjk5NzUzMzA5NzA1IgwQhgl9aOYuOI9IQBgq0AS3l3Hys6aakdvQtZId720zFGgcxm3IjDUMnlTaj8YxYt4ZyGypj2CAURS7oWJ2ZOEORagWPP4a5gaMHeDuEBFDdvlEwPmjvKqsw0Ooap9LBvww%2BRRnGNEfCwn%2B2oMVrAxkR2a1rCcgFWnpFVipzxvTer4m1Ht%2BiWZj2bk5IIvPWcSFy5btsBi6emVrMADQw4RESsnUapN0TS0h%2B7AHxrk7eR6De4mjHAekkJ3YBwDZSgSpSbx7ai8EydHJ8LYAWN50dxt4TRGG%2FWEV6VkBPB%2B5Xy8fINmnBqWoZuBTpNvLSkxvj05ZgCikazPXqE2bi8zVl19crb%2FThjzLNJN4mkO3HGW940YrAkvo6Ai0zzVGwOXlrsr6M9KoFWDA4rQ8AdyG7Bpe5t9Lfua1RKbZIi7XR3oXGGSrC8MKZVDB1qrbsyj9%2FzL9VuvoDmXacqs0YbKIUGehQtLNlgL%2BAEjyTz7AbwchrBddv8jdouWKxm4Op48shAjnsob5BlKRKBvY0I5c7sX6J7WDZFjB%2B9rfc2nHqPQ6VAmrLgRF9NC5Jint%2BjehkGVOQknYGQ4buVLTmwJwG6keqIaaO1aVRd6Ilx3%2BDr9bQMnCtnFUBYXarsPRijhpzCaLQMYgUZEIdFb6GuXbSQtDBpFUTHuLtVZY%2FeBttBPaJI8%2FABZ0OGz3eG3TqB1oRbgArKebeewBXOFn6eM%2FZYgC2F3S6rNpF3LmCL96%2BGwLRW5NxZAsDWbR6iB1O58JLHFi6E66KPYDSPDbGEE8IXNlzugraXTckDPPdxCnMPGsq9EGOpcBTXUFn6x4WqRjjJdgvIBNqUnZsNpXyDmCR06utPeaKfUgfb307GAzggjN0w%2BN3IHpipuAaRW05%2Fb49%2F4dj0xM2kqief3O5wRS%2BLKOJtl7jVWn5wfAQUZuzSfDL%2F0oN3aYUVYMOqeWuZ3mt2qnYwNUOhKRWy3AFQBZOLBXhRidNaS9GY0ceCrFGu94HPzb23JS2pFfgM3ZpQ%3D%3D&Expires=1781195844) - # ANÁLISIS EXHAUSTIVO Y PLAN DE MEJORA
# OMEN AI Cluster — Versión 11
## HP OMEN Ultra 7 · RTX 4070 ...

2. [Secure self-hosted OpenClaw + Ollama + Open WebUI ... - GitHub](https://github.com/deepmehtait/openclaw-docker-secure) - Secure self-hosted OpenClaw + Ollama + Open WebUI behind Gluetun VPN. Docker Compose, HTTPS, kill-sw...

3. [Agents - OpenClaw Docs](https://docs.openclaw.ai/cli/agents) - CLI reference for `openclaw agents` (list/add/delete/bindings/bind/unbind/set identity)

4. [OpenClaw Config Generator - AI Agent Setup Tool - Dervity](https://dervity.com/tools/config-generator) - Generate ready-to-use OpenClaw configuration files. Pick a preset profile, customize models, copy or...

5. [deepseek-ai/DeepSeek-R1-0528-Qwen3-8B - Hugging Face](https://huggingface.co/deepseek-ai/DeepSeek-R1-0528-Qwen3-8B) - We’re on a journey to advance and democratize artificial intelligence through open source and open s...

6. [The Best Open-Source Small Language Models (SLMs) in 2026](https://www.bentoml.com/blog/the-best-open-source-small-language-models) - Phi-4-mini-instruct supports over 20 languages, making it suitable for global products that requires...

7. [Edge-First LLM Semantic Routing on a 4GB Jetson Nano](https://blog.labs.purplemaia.org/edge-first-llm-semantic-routing-on-a-4gb-jetson-nano-2/) - People: David Pickett Idea: Testing whether a 4GB NVIDIA Jetson Nano can act as an autonomous routin...

8. [semantic-router/README.md at main · aurelio-labs/semantic-router](https://github.com/aurelio-labs/semantic-router/blob/main/README.md) - Superfast AI decision making and intelligent processing of multi-modal data. - aurelio-labs/semantic...

9. [Josh Phillips' Post - LinkedIn](https://www.linkedin.com/posts/joshaphillips_side-projects-and-halloween-candy-have-me-activity-7388414127892795392-4noh) - Side Projects and Halloween Candy have me buzzing (and not sleeping at 11:39ET on a Sunday 🎃) Shippe...

10. [shenhao-stu/openclaw-agents: 🐾 One-command multi- ...](https://github.com/shenhao-stu/openclaw-agents) - 🐾 One-command multi-agent setup for OpenClaw — 9 specialized AI agents, group routing, safe config m...

11. [OpenClaw Configuration Guide | Complete Setup](https://openclaw-ai.online/configuration/) - Complete configuration guide for OpenClaw. Configure models, workspace, security, and channels.

12. [deepseek-ai/DeepSeek-R1-0528](https://simonwillison.net/2025/May/31/deepseek-aideepseek-r1-0528/) - Sadly the trend for terrible naming of models has infested the Chinese AI labs as well. DeepSeek-R1-...

13. [Qwen/Qwen3-8B-GGUF - Hugging Face](https://huggingface.co/Qwen/Qwen3-8B-GGUF) - We’re on a journey to advance and democratize artificial intelligence through open source and open s...

14. [all.txt](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/48708411/306d2684-d0fc-45c4-91b7-6502f26fd8e7/all.txt?AWSAccessKeyId=ASIA2F3EMEYEVJK7EHRF&Signature=M6rpq57w5v0Vm60JTaJRs39xSyE%3D&x-amz-security-token=IQoJb3JpZ2luX2VjEDgaCXVzLWVhc3QtMSJIMEYCIQCSmqngKJ9G%2BWb1P8r7aiGg%2FPWzqHQ8Lo7gw%2BlEwLCAvAIhAM8HZ8b0vl%2B6v%2Fwg%2BWNzgHIsLokOC6H56J1WN3iNgC%2FTKvMECAEQARoMNjk5NzUzMzA5NzA1IgwQhgl9aOYuOI9IQBgq0AS3l3Hys6aakdvQtZId720zFGgcxm3IjDUMnlTaj8YxYt4ZyGypj2CAURS7oWJ2ZOEORagWPP4a5gaMHeDuEBFDdvlEwPmjvKqsw0Ooap9LBvww%2BRRnGNEfCwn%2B2oMVrAxkR2a1rCcgFWnpFVipzxvTer4m1Ht%2BiWZj2bk5IIvPWcSFy5btsBi6emVrMADQw4RESsnUapN0TS0h%2B7AHxrk7eR6De4mjHAekkJ3YBwDZSgSpSbx7ai8EydHJ8LYAWN50dxt4TRGG%2FWEV6VkBPB%2B5Xy8fINmnBqWoZuBTpNvLSkxvj05ZgCikazPXqE2bi8zVl19crb%2FThjzLNJN4mkO3HGW940YrAkvo6Ai0zzVGwOXlrsr6M9KoFWDA4rQ8AdyG7Bpe5t9Lfua1RKbZIi7XR3oXGGSrC8MKZVDB1qrbsyj9%2FzL9VuvoDmXacqs0YbKIUGehQtLNlgL%2BAEjyTz7AbwchrBddv8jdouWKxm4Op48shAjnsob5BlKRKBvY0I5c7sX6J7WDZFjB%2B9rfc2nHqPQ6VAmrLgRF9NC5Jint%2BjehkGVOQknYGQ4buVLTmwJwG6keqIaaO1aVRd6Ilx3%2BDr9bQMnCtnFUBYXarsPRijhpzCaLQMYgUZEIdFb6GuXbSQtDBpFUTHuLtVZY%2FeBttBPaJI8%2FABZ0OGz3eG3TqB1oRbgArKebeewBXOFn6eM%2FZYgC2F3S6rNpF3LmCL96%2BGwLRW5NxZAsDWbR6iB1O58JLHFi6E66KPYDSPDbGEE8IXNlzugraXTckDPPdxCnMPGsq9EGOpcBTXUFn6x4WqRjjJdgvIBNqUnZsNpXyDmCR06utPeaKfUgfb307GAzggjN0w%2BN3IHpipuAaRW05%2Fb49%2F4dj0xM2kqief3O5wRS%2BLKOJtl7jVWn5wfAQUZuzSfDL%2F0oN3aYUVYMOqeWuZ3mt2qnYwNUOhKRWy3AFQBZOLBXhRidNaS9GY0ceCrFGu94HPzb23JS2pFfgM3ZpQ%3D%3D&Expires=1781195844) - ANALISIS DEL PROCESO DE DEFINICION DE LOS ENTORNOS DE IA LOCAL:

===== Archivo: ANALISIS.txt =====

...

15. [Ollama Alternative: vLLM, SGLang & Co. im Vergleich (2026)](https://www.biteno.com/ollama-alternative/) - Ollama Alternative für den Produktivbetrieb: vLLM, SGLang und Nvidia Dynamo im Vergleich. Welche pas...

16. [DeepSeek-R1 0528 models missing tool calling updates in Ollama registry · Issue #10935 · ollama/ollama](https://github.com/ollama/ollama/issues/10935) - DeepSeek-R1 models missing 0528 tool calling updates in Ollama registry Summary DeepSeek-R1 models i...

