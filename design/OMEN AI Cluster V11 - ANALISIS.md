# ANÁLISIS EXHAUSTIVO Y PLAN DE MEJORA
# OMEN AI Cluster — Versión 11
## HP OMEN Ultra 7 · RTX 4070 8GB VRAM · 32GB RAM · SSD exFAT

---

## 1. INVENTARIO REAL DEL SISTEMA

### Modelos descargados y su ubicación

| Motor | Directorio | Modelo | Tamaño | Formato |
|-------|-----------|--------|--------|---------|
| ExLlamaV2 | `exllamav2_storage/qwen2.5-coder-7b-exl2` | Qwen2.5 Coder 7B | 6.95 GB | EXL2 6.5 bpw |
| ExLlamaV2 | `exllamav2_storage/llama-3.1-8b-exl2` | Llama 3.1 8B | 6.71 GB | EXL2 6.0 bpw |
| SGLang | `sglang_storage/llama-3.1-8b-awq` | Llama 3.1 8B AWQ | 5.74 GB | AWQ INT4 |
| Ollama | `ollama_storage` | DeepSeek R1 14B | 9.0 GB | GGUF (interno) |
| Ollama | `ollama_storage` | DeepSeek Coder V2 | ~8 GB | GGUF (interno) |
| Ollama | `ollama_storage` | Qwen2.5 32B | 19 GB | GGUF (interno) |
| Ollama | `ollama_storage` | Phi-4 | 9.1 GB | GGUF (interno) |

**Total en disco:** ~65 GB de pesos de modelos

---

## 2. ARQUITECTURA V11 — MAPA COMPLETO

```
┌─────────────────────────────────────────────────────────────────────┐
│                    USUARIO / OpenClaw UI :8080                       │
└──────────────────────────┬──────────────────────────────────────────┘
                           │  HTTP/SSE (OpenAI-compatible)
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│              Orchestrator Router V5  :8000                           │
│  GET  /health      → estado de todos los backends                   │
│  GET  /v1/models   → catálogo completo de modelos                   │
│  POST /v1/chat/completions → proxy inteligente                      │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Clasificador Phi-4 (CPU-only, puerto 11435)                 │   │
│  │  - Caché LRU 256 entradas (evita llamadas repetidas)         │   │
│  │  - num_gpu=0: CERO contención de VRAM con los backends       │   │
│  │  - 5 categorías: INSTANTANEO·AGIL·PROFUNDO·MASIVO·CODIGO     │   │
│  └──────────────────────────────────────────────────────────────┘   │
└───┬─────────┬──────────────────────┬──────────┬───────────────────┬─┘
    │         │                      │          │                   │
    ▼         ▼                      ▼          ▼                   ▼
 INSTANTANEO AGIL                PROFUNDO    MASIVO             CODIGO
 TabbAPI     SGLang              Ollama      Ollama             Ollama
 :5000       :30000              :11434      :11434             :11434
 ExLlamaV2   RadixAttention      DeepSeek    Qwen2.5           DeepSeek
 Qwen2.5     Llama-3.1-AWQ       R1 14B      32B               Coder V2
 Coder 7B    5.74GB VRAM         ~7GB híb.   ~8GB+11GB RAM     ~7.5GB híb.
 6.95GB VRAM
```

### Gestión de VRAM (exclusión mutua automática)

Con solo 8GB de VRAM, el router implementa **exclusión mutua** entre los backends que usan GPU:

| Nivel activo | Contenedores detenidos | VRAM libre para backend |
|-------------|----------------------|------------------------|
| INSTANTANEO | sglang-server | ~8GB (carga 6.95GB) |
| AGIL | exllamav2-api | ~8GB (carga 5.74GB) |
| PROFUNDO | exllamav2-api + sglang-server | ~8GB híbrido + RAM |
| MASIVO | exllamav2-api + sglang-server | ~8GB + 11GB RAM |
| CODIGO | exllamav2-api + sglang-server | ~8GB híbrido + RAM |

---

## 3. BUGS ENCONTRADOS Y CORREGIDOS (V10 → V11)

### 🔴 BUG CRÍTICO #1: Imagen Docker de TabbAPI incorrecta

**V10 (incorrecto):**
```bash
docker run ... berot3/tabbyapi:latest
```

**Problema:** `berot3/tabbyapi` es una imagen comunitaria no oficial, probablemente desactualizada y sin soporte activo. La imagen oficial es de `ghcr.io/theroyallab/tabbyapi`.

**V11 (correcto):**
```bash
docker run ... ghcr.io/theroyallab/tabbyapi:latest
```

**Impacto:** TabbAPI no arrancaba correctamente o usaba una versión obsoleta de ExLlamaV2.

---

### 🔴 BUG CRÍTICO #2: Formato de configuración de OpenClaw incorrecto

**V10 (incorrecto):**
```bash
docker exec openclaw-server sh -c 'cat > /data/initial_providers.json << EOF
{ "providers": [...] }
EOF'
```

**Problema:** OpenClaw NO usa el archivo `initial_providers.json`. El sistema de configuración de OpenClaw utiliza `~/.openclaw/openclaw.json` (dentro del contenedor: `/data/.openclaw/openclaw.json`) con un esquema completamente diferente. El archivo `initial_providers.json` era ignorado silenciosamente, por lo que OpenClaw nunca llegaba a conocer los backends locales.

**V11 (correcto):**
```bash
docker exec openclaw-server bash -c 'cat > /data/.openclaw/openclaw.json' << 'EOF'
{
  "models": {
    "mode": "merge",
    "providers": {
      "local_router": {
        "baseUrl": "http://host.docker.internal:8000/v1",
        "apiKey": "sk-router-local",
        "api": "openai-completions",
        "models": [...]
      }
    }
  },
  "agents": {
    "defaults": {
      "model": {
        "primary": "local_router/ruteador-auto",
        "fallbacks": ["local_router/agil"]
      }
    }
  }
}
EOF'
```

**Impacto:** Los modelos locales no aparecían en OpenClaw. Los usuarios siempre veían solo los proveedores cloud por defecto.

---

### 🔴 BUG CRÍTICO #3: Phi-4 consume VRAM del backend destino

**V10 (problemático):**
```python
url_ollama = "http://host.docker.internal:11434/api/generate"
# Phi-4 (9.1GB) en el mismo Ollama que usa la GPU
```

**Problema:** Phi-4 (9.1GB) no cabe entero en 8GB de VRAM. Ollama lo carga en modo híbrido: ~6-7GB VRAM + 2-3GB RAM. Cuando el router pide a Phi-4 que clasifique y luego activa SGLang (5.74GB VRAM), **no hay suficiente VRAM disponible** (6GB Phi-4 + 5.74GB SGLang > 8GB). SGLang falla al cargar o funciona muy lento con capas en RAM.

**V11 (correcto):**
- Ollama CPU-only en puerto 11435 (`CUDA_VISIBLE_DEVICES=""`)
- Phi-4 se ejecuta 100% en CPU/RAM (sin tocar la VRAM)
- La VRAM de 8GB queda completamente libre para el backend de inferencia

**Impacto:** Colisiones de VRAM en cada request que pasa por el clasificador.

---

### 🟡 BUG IMPORTANTE #4: Biblioteca HTTP bloqueante en FastAPI async

**V10 (incorrecto):**
```python
# requests es síncrono — bloquea el event loop de asyncio
import requests
res = requests.post(url_ollama, json=payload, timeout=15)
```

**Problema:** FastAPI es async. Usar `requests` (síncrona) en handlers async bloquea el event loop durante toda la duración de la llamada HTTP. Si el router recibe dos peticiones simultáneas, la segunda espera hasta que la primera termine completamente — incluyendo el tiempo de generación del LLM.

**V11 (correcto):**
```python
import httpx
async with httpx.AsyncClient(timeout=25.0) as client:
    resp = await client.post(PHI4_CPU_GENERATE_URL, json=payload)
```

**Impacto:** Sin concurrencia real. Degradación severa de rendimiento con múltiples usuarios o peticiones paralelas.

---

### 🟡 BUG IMPORTANTE #5: SGLang sin flags de cuantización y nombre de modelo

**V10 (incorrecto):**
```bash
docker run ... lmsysorg/sglang:latest \
  python3 -m sglang.launch_server \
    --model-path /models/llama-3.1-8b-awq \
    --port 30000 \
    --host 0.0.0.0
```

**Problema A:** Sin `--quantization awq`, SGLang puede intentar cargar el modelo como si fuera FP16, fallando o usando más VRAM de la necesaria.

**Problema B:** Sin `--served-model-name llama-3.1-8b-awq`, el nombre del modelo expuesto en la API puede ser el path completo `/models/llama-3.1-8b-awq`, lo que hace que el router deba adivinar el nombre correcto.

**V11 (correcto):**
```bash
python3 -m sglang.launch_server \
  --model-path /models/llama-3.1-8b-awq \
  --quantization awq \
  --served-model-name llama-3.1-8b-awq \
  --port 30000 \
  --host 0.0.0.0
```

---

### 🟡 BUG IMPORTANTE #6: Sin health checks — routing ciego

**V10:** El router enviaba peticiones al backend sin verificar si estaba activo.

**V11:**
```python
async def _esperar_backend(url, intentos=25, pausa=2.5):
    for i in range(intentos):
        if await _health_check(url):
            return True
        await asyncio.sleep(pausa)
    return False
```

Después de arrancar un contenedor, el router espera hasta 62.5 segundos (25 intentos × 2.5s) a que el backend esté listo antes de enviar el primer request.

---

### 🟡 BUG IMPORTANTE #7: Routing binario (solo AGIL/PROFUNDO)

**V10:** Solo dos niveles de razonamiento.

**V11:** Cinco niveles, aprovechando todos los modelos descargados:
- `INSTANTANEO`: ExLlamaV2 — máxima velocidad para tareas simples
- `AGIL`: SGLang RadixAttention — agentes y documentos
- `PROFUNDO`: DeepSeek R1 14B — razonamiento profundo
- `MASIVO`: Qwen2.5 32B — análisis masivo
- `CODIGO`: DeepSeek Coder V2 — generación de código especializada

**Impacto en uso de recursos:** En V10, tareas simples como "traduce esta frase" activaban DeepSeek R1 14B. En V11, van a ExLlamaV2 y responden en <1 segundo.

---

### 🟢 MEJORA #8: TabbAPI sin config.yml

**V10:** TabbAPI se lanzaba sin config.yml, usando valores por defecto que no especificaban el modelo a cargar.

**V11:** Se genera automáticamente `config_tabbyapi.yml` con:
- Modelo por defecto: `qwen2.5-coder-7b-exl2`
- Cache mode: Q4 (reduce VRAM ~30%)
- Max seq len: 4096

---

### 🟢 MEJORA #9: ExLlamaV2 no estaba en el pipeline del router

**V10:** TabbAPI existía como servicio separado pero el router (`orchestrator_router_V4.py`) nunca lo usaba. Solo ruteaba entre SGLang y Ollama.

**V11:** TabbAPI es el nivel `INSTANTANEO`, completamente integrado en el pipeline de routing.

---

### 🟢 MEJORA #10: Caché LRU de decisiones Phi-4

**V11:** Las primeras 256 decisiones de Phi-4 se cachean por prefijo del prompt. Si el usuario hace preguntas similares, Phi-4 no se re-invoca — la respuesta sale de la caché en <1ms en lugar de los 2-5s de inferencia CPU.

---

## 4. RESTRICCIONES exFAT Y ADAPTACIONES

El SSD compartido entre Windows y Ubuntu está en formato exFAT. Estas son las limitaciones relevantes y cómo V11 las maneja:

| Limitación exFAT | Impacto | Solución implementada |
|-----------------|---------|----------------------|
| Sin symlinks | Algunos toolkits crean symlinks para archivos de caché | Usar Docker volumes para datos internos de cada motor; montar exFAT solo para pesos |
| Sin permisos Unix | `chmod` no funciona en archivos exFAT | Los contenedores Docker acceden como root (UID 0), que siempre tiene acceso en exFAT |
| Sin hard links | Algunos gestores de paquetes los usan | No afecta a la inferencia de modelos; solo afecta a pip/npm en el SSD |
| Sin sparse files | Archivos grandes siempre ocupan su tamaño real | No crítico para inferencia |
| Sin sockets Unix | Imposible usar IPC por socket de fichero | Toda comunicación inter-servicios via TCP/IP (ya implementado) |
| Max nombre fichero: 255 chars | Modelos con rutas largas de HuggingFace | Usar `--local-dir` con nombre corto (ya se hace en las descargas) |

**Configuración específica para exFAT:**
- Ollama: `OLLAMA_MODELS` apunta al SSD exFAT. Ollama almacena los blobs (pesos) ahí. El directorio de estado interno (`~/.ollama`) sigue en ext4.
- SGLang/TabbAPI: El directorio de modelos en exFAT se monta como volumen Docker. Los archivos de caché y temporales van a Docker volumes (ext4).
- El router Python corre en ext4 (home directory) sin tocar el exFAT.

---

## 5. GUÍA DE USO

### 5.1 Arranque completo del clúster
```bash
cd ~/ruta/a/scripts/
chmod +x Autoboot_Cluster_V11.sh
./Autoboot_Cluster_V11.sh
```

### 5.2 Estado del clúster
```bash
./Autoboot_Cluster_V11.sh --status

# O directamente:
curl -s http://localhost:8000/health | python3 -m json.tool
```

### 5.3 Parar el clúster
```bash
./Autoboot_Cluster_V11.sh --stop
```

### 5.4 Ver qué modelos están disponibles
```bash
curl -s http://localhost:8000/v1/models | python3 -m json.tool
```

### 5.5 Probar el router directamente (sin OpenClaw)
```bash
# Auto-routing (Phi-4 decide):
curl -s http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "ruteador-auto",
    "messages": [{"role": "user", "content": "¿Cuánto es 2+2?"}],
    "stream": false
  }' | python3 -m json.tool

# Forzar nivel MASIVO (Qwen2.5 32B):
curl -s http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "masivo",
    "messages": [{"role": "user", "content": "Analiza este log..."}],
    "stream": false
  }'
```

### 5.6 Activar manualmente un backend en standby
```bash
# Arrancar ExLlamaV2 (libera VRAM de SGLang si está activo):
docker start exllamav2-api

# Arrancar SGLang (libera VRAM de ExLlamaV2 si está activo):
docker stop exllamav2-api
docker start sglang-server
```

### 5.7 Ver logs del router en tiempo real
```bash
tail -f ~/ruta/a/scripts/router_v11.log
```

---

## 6. DIAGRAMA DE FLUJO DE UNA PETICIÓN

```
Usuario escribe en OpenClaw:
"Explícame el algoritmo de Dijkstra y escríbeme la implementación en C++"
         │
         ▼
OpenClaw envía POST /v1/chat/completions
con model="ruteador-auto" → Router V5 (puerto 8000)
         │
         ▼
¿Es "ruteador-auto"? → SÍ
         │
         ▼
¿Está en caché LRU? → NO (primer vez con este prompt)
         │
         ▼
Phi-4 CPU (puerto 11435) clasifica el prompt:
"algoritmo + implementación en C++" → responde "CODIGO"
         │
         ▼
Router llama a _conmutar_vram("CODIGO"):
  - Para exllamav2-api (si estaba corriendo)
  - Para sglang-server (si estaba corriendo)
  - Ollama ya está corriendo (nativo)
         │
         ▼
Router redirige a http://localhost:11434/v1/chat/completions
con model="deepseek-coder-v2"
         │
         ▼
Ollama carga deepseek-coder-v2 (si no estaba ya en memoria)
Genera la respuesta en modo híbrido GPU+RAM
         │
         ▼
Router hace streaming SSE de la respuesta hacia OpenClaw
         │
         ▼
OpenClaw muestra la respuesta al usuario en tiempo real
```

---

## 7. SELECCIÓN MANUAL DE MODELO EN OPENCLAW

En el desplegable de modelos de OpenClaw aparecerán todos estos nombres:

| Nombre en UI | Alias técnico | Backend | Mejor para |
|-------------|--------------|---------|-----------|
| 🤖 Auto — Phi-4 elige el nivel | `ruteador-auto` | Dinámico | Uso general |
| ⚡ Instantáneo (ExLlamaV2) | `instantaneo` | TabbAPI | Chat rápido, autocompletado |
| 🚀 Ágil (SGLang · agentes) | `agil` | SGLang | Agentes, documentos largos |
| 🧠 Profundo (DeepSeek R1 14B) | `profundo` | Ollama | Matemáticas, debugging |
| 🔬 Masivo (Qwen2.5 32B) | `masivo` | Ollama | Documentos >10 páginas |
| 💻 Código (DeepSeek Coder V2) | `codigo` | Ollama | Generación de código |
| 🔷 Phi-4 CPU (router directo) | `phi4` | Ollama CPU | Lógica, razonamiento rápido |

---

## 8. ADVERTENCIA: TIEMPO DE CAMBIO DE BACKEND

Cuando el router necesita cambiar de backend (p.ej., de Ollama a SGLang), el proceso implica:
1. Detener el contenedor anterior (~2-5 segundos)
2. Arrancar el nuevo contenedor (~10-20 segundos)
3. Cargar el modelo en VRAM (~15-45 segundos dependiendo del modelo)

**Total: 30-70 segundos de latencia en el primer request de cada sesión cuando hay cambio de backend.**

Los requests subsiguientes al mismo backend son rápidos (el modelo ya está en VRAM).

**Estrategia recomendada:** Si sabes que vas a trabajar intensivamente con código, selecciona manualmente `codigo` en OpenClaw en lugar de dejar el auto-routing. Esto evita el overhead de clasificación y los posibles cambios de backend durante la sesión.

---

## 9. MEJORAS FUTURAS SUGERIDAS

### 9.1 Modelo de routing más ligero
Phi-4 (9.1GB) es demasiado grande para ser solo un clasificador. Alternativas:
- **Phi-3.5-mini** (3.8B, ~2.5GB): Más rápido en CPU, casi igual de preciso para clasificación
- **Qwen2.5-0.5B** (0.5GB): Ultra-rápido, menos preciso
- Reglas heurísticas simples basadas en longitud del prompt y palabras clave (sin LLM)

### 9.2 Warmup automático del backend preferido
Al arrancar, detectar el tipo de tarea más frecuente del usuario y pre-cargar ese modelo en VRAM para eliminar la latencia inicial.

### 9.3 Modelo de embeddings para routing semántico
En lugar de usar Phi-4 para clasificar con texto, usar un modelo de embeddings ligero (como `nomic-embed-text`, 274MB) y clasificar por similitud coseno con vectores de ejemplo de cada categoría. Sería 10x más rápido que Phi-4 para clasificar.

### 9.4 Qwen2.5-Coder como nivel INSTANTANEO más capaz
El modelo `qwen2.5-coder-7b-exl2` en TabbAPI es excelente para código. Considerar:
- Usarlo como nivel INSTANTANEO para código simple
- Redirigir CODIGO → TabbAPI para snippets cortos, y CODIGO → Ollama DeepSeek para proyectos completos

### 9.5 Integración de TensorRT-LLM
El entorno TensorRT-LLM ya está configurado en el clúster pero no integrado en el router. Compilar el modelo Llama-3.1-8B en TensorRT daría velocidades 2-3x superiores a SGLang para batch inference.

---

## 10. RESUMEN DE ARCHIVOS ENTREGADOS

| Archivo | Descripción |
|---------|-------------|
| `Autoboot_Cluster_V11.sh` | Script principal de arranque del clúster (reemplaza V10) |
| `orchestrator_router_V5.py` | Router semántico mejorado (reemplaza V4) |
| `ANALISIS_V11.md` | Este documento |

Los tres archivos van en el mismo directorio donde estaba el cluster anterior.
La ruta `AI_CORE` se puede personalizar via variable de entorno antes de ejecutar:
```bash
AI_CORE=/ruta/custom ./Autoboot_Cluster_V11.sh
```
