El informe y los tres archivos de código están listos. El análisis cubre todos los aspectos de los dos nuevos modos.

***

### Lo que se ha desarrollado para el build V15

**[V15-A] Auto-Heavy — Phi-4 14B como clasificador y juez**

El razonamiento de tu reflexión es correcto: phi4-mini en CPU es adecuado como *fallback* de clasificación rápida, pero carece de la capacidad evaluativa necesaria para supervisar la calidad de las respuestas generadas. El módulo nuevo añade dos funciones independientes: [arxiv](https://www.arxiv.org/pdf/2502.00674.pdf)

- `_clasificar_phi4_heavy()` — usa `phi4` completo (14B, GPU `:11434`) con un system prompt que pide razonamiento antes de clasificar, no solo reconocimiento de palabras clave
- `_evaluar_calidad_phi4()` — implementa *LLM-as-Judge*: devuelve un `score` 0-10, un flag `sufficient`, la debilidad principal de la respuesta y el nivel al que escalar si no es suficiente. Esta función es **opcional** en el flujo — se puede activar como paso de validación post-respuesta para los niveles PROFUNDO/PRECISO

**[V15-B] Deep Chain Reasoning (DCR)**

La arquitectura está fundamentada en la literatura de 2024-2026: los modelos que actúan como *proposers* secuenciales ven el trabajo del anterior y lo critican explícitamente antes de añadir su perspectiva. El agregador final (Phi-4-reasoning:plus) recibe instrucciones explícitas de identificar convergencias (alta confianza), divergencias (analizar cuál es más sólida) y producir una síntesis consolidada. La cadena es **DeepSeek R1 → Phi4 Q4_K_M → Phi4:plus integrador**, todos en Ollama GPU con swapping automático entre modelos. [openreview](https://openreview.net/pdf?id=ioprnwVrDH)

**Activación en OpenClaw**: seleccionar `⛓ Deep Chain Reasoning` en el desplegable de modelos, o usar los alias `deep-chain`, `dcr`, `hard`, `auto-hard-reasoning` desde cualquier cliente.

---

# OMEN AI Cluster V15 — Orquestación Auto-Heavy y Deep Chain Reasoning

## Resumen Ejecutivo

Este documento especifica e implementa dos nuevas modalidades de orquestación para el OMEN AI Cluster, construidas sobre el router V8/build V14:

- **[V15-A] Auto-Heavy**: sustituye `phi4-mini` por `phi4` completo (14B) como clasificador y añade un módulo de evaluación de calidad *LLM-as-Judge*.
- **[V15-B] Deep Chain Reasoning (DCR)**: pipeline secuencial multi-modelo donde DeepSeek R1 14B y Phi-4-reasoning Q4_K_M actúan como *proposers*, y Phi-4-reasoning:plus integra las respuestas como agregador final.

La arquitectura DCR está respaldada por investigación publicada: *Mixture-of-Agents* (Wang et al., 2024) demostró que múltiples LLMs colaborando en capas superan consistentemente al mejor modelo individual; *Self-MoA-Seq* (OpenReview 2025) validó que la agregación secuencial es tan efectiva como la paralela con contextos cortos; y experimentos con *Ensemble Debates* con LLMs locales reportaron mejoras de +19.4% en profundidad de razonamiento y +34.1% en calidad argumentativa.[^1][^2][^3][^4]

***

## Fundamento Técnico

### Por qué Phi-4-mini es insuficiente como orquestador

Phi-4-mini opera en la CPU Ollama `:11435` con `num_gpu: 0`. Su función en V8 se limita a ser la **Capa 3** del clasificador (fallback cuando los embeddings no superan el threshold 0.63). Para esa tarea específica de clasificación rápida, phi4-mini es adecuado. El problema no es la clasificación per se, sino lo que no existe en V8: **ningún mecanismo supervisa si la respuesta generada por el modelo elegido es de calidad suficiente**. Una vez que el router decide el nivel y el modelo responde, no hay revisión.

Phi-4 14B completo, disponible en la instancia Ollama GPU `:11434`, tiene capacidades muy superiores para razonamiento evaluativo. El reporte técnico de Microsoft sobre Phi-4-reasoning describe el uso de *rubric-based LLM evaluators* para filtrar y puntuar respuestas en pipelines de evaluación, exactamente el patrón que implementa `_evaluar_calidad_phi4()`.[^5][^6]

### Evidencia sobre razonamiento en cadena

La investigación *DASE* (arXiv, mayo 2026) introduce un heurístico de parada adaptativa para ensembles deliberativos, demostrando que el consenso entre múltiples modelos es un indicador estadísticamente sólido de corrección: gap de routing de 24.8 puntos porcentuales entre respuestas con consenso alto vs. bajo. El framework *DiMo* (arXiv 2025) reporta que cuatro agentes especializados debatiendo de forma estructurada mejoran la precisión en benchmarks de matemáticas sobre todos los baselines de modelo único.[^7][^8]

En el contexto del OMEN, con hardware limitado a 8GB VRAM, la cadena secuencial (no paralela) es la única arquitectura viable. *Self-MoA-Seq* demuestra que la agregación secuencial tiene el mismo rendimiento que la paralela cuando el agregador final es suficientemente capaz.[^1]

***

## Arquitectura V15

### Tabla de Modos Disponibles

| Alias             | Nivel Interno  | Clasificador       | Latencia Estimada | Caso de Uso                                      |
|-------------------|----------------|--------------------|-------------------|--------------------------------------------------|
| `ruteador-auto`   | AUTO           | embed + phi4-mini  | ~1–5 s            | Uso general — balance velocidad/calidad          |
| `auto-heavy`      | AUTO_HEAVY     | Phi-4 14B GPU      | ~5–15 s           | Consultas ambiguas que requieren clasificación fina |
| `deep-chain`/`dcr`/`hard` | DEEP_CHAIN | N/A           | ~4–12 min         | Razonamiento complejo, análisis exhaustivos      |
| `profundo`        | PROFUNDO       | directo            | ~1–3 min          | Debugging, diseño, lógica                        |
| `preciso`         | PRECISO        | directo            | ~2–4 min          | STEM, matemáticas, lógica formal                 |
| `masivo`          | MASIVO         | directo            | ~4–8 min          | Documentos extensos, codebases                   |

> **Nota sobre latencia DCR**: la cadena completa implica 3 llamadas secuenciales a modelos de ~7–8 GB. Los tiempos orientativos son: Etapa 1 (DeepSeek R1, ~90–130 s) + Etapa 2 (Phi4 Q4_K_M, ~60–160 s) + Agregador (Phi4:plus, ~100–200 s) = **4–8 minutos totales**. Usar DCR solo para tareas donde la calidad es prioritaria sobre la velocidad.

### [V15-A] Módulo Auto-Heavy

**Clasificador (`_clasificar_phi4_heavy`)**:
- Llama a `phi4` completo (14B) en Ollama GPU `:11434`
- System prompt más sofisticado que phi4-mini: pide razonamiento breve antes de decidir
- Timeout de 60 s (vs 35 s de phi4-mini)
- Fallback conservador a `PROFUNDO` si el modelo no responde

**Evaluador de calidad (`_evaluar_calidad_phi4`)**:
- Implementa el patrón *LLM-as-Judge* documentado en la literatura[^9][^10]
- Devuelve un objeto JSON con: `score` (0–10), `sufficient` (bool), `weakness` (texto), `escalate_to` (nivel superior sugerido)
- Diseñado para uso opcional: se puede activar en el endpoint para validar respuestas antes de devolverlas al usuario

```python
# Uso del evaluador (opcional, añadir tras _proxy en el endpoint):
if nivel in ("PROFUNDO", "PRECISO", "PRECISO_OPT") and not streaming:
    respuesta_texto = result.body  # extraer contenido
    evaluacion = await _evaluar_calidad_phi4(prompt, respuesta_texto)
    if not evaluacion["sufficient"] and evaluacion["escalate_to"] != "NONE":
        nivel_escalado = evaluacion["escalate_to"]
        log.info(f"[JUDGE] Score {evaluacion['score']}/10 — escalando a {nivel_escalado}")
        # re-ejecutar con nivel_escalado
```

### [V15-B] Deep Chain Reasoning (DCR)

La implementación sigue la arquitectura *MoA sequential* con tres roles diferenciados:

```
Prompt
  │
  ▼
[Etapa 1] DeepSeek R1 14B (PROFUNDO)
  │ Respuesta R1 (razonamiento base, chain-of-thought)
  ▼
[Etapa 2] Phi-4-reasoning:14b-q4_K_M (PRECISO_OPT)
  │ Recibe: pregunta original + R1
  │ Respuesta R2 (revisión crítica, refinamiento)
  ▼
[Agregador] Phi-4-reasoning:plus (PRECISO)
  │ Recibe: pregunta original + R1 + R2
  │ Instrucciones: identificar convergencias, resolver divergencias, sintetizar
  ▼
Respuesta final consolidada
```

**Por qué esta cadena específica**:
- DeepSeek R1 14B destaca en razonamiento multi-paso (chain-of-thought nativo) y sirve como base sólida[^6]
- Phi-4-reasoning Q4_K_M (más rápido que :plus) actúa como revisor para detectar errores o lagunas de R1 sin consumir el mismo tiempo que el agregador
- Phi-4-reasoning:plus como integrador final es la elección más precisa disponible en el cluster para análisis evaluativo complejo[^5]

**Gestión de contexto**:
- Tokens por proposer limitados a 2048 (`_DCR_MAX_TOKENS_PROPOSER`) para evitar que el contexto del agregador explote
- Agregador: 4096 tokens (`_DCR_MAX_TOKENS_AGGREGATOR`) para tener espacio suficiente de síntesis
- RAG ChromaDB se inyecta solo en la Etapa 1 (base del razonamiento); las etapas siguientes trabajan sobre ese contexto enriquecido
- Opciones extra de temperatura (0.6 / top_p 0.95 para phi4-reasoning) se aplican automáticamente

**Formato de respuesta**:
El DCR devuelve una respuesta en formato OpenAI-compatible con un campo adicional `_dcr_metadata` que incluye las etapas ejecutadas y la latencia total. Esto permite a OpenClaw y a cualquier cliente registrar el pipeline completo.

**Fallback robusto**:
Si el agregador falla, se devuelve la respuesta más larga de los proposers disponibles. Si todas las etapas fallan, se retorna HTTP 503.

***

## Archivos Generados

### `nuevos_modulos_V9.py`

Módulo autónomo con todas las nuevas funciones: `_clasificar_phi4_heavy`, `_evaluar_calidad_phi4`, `_ejecutar_deep_chain_reasoning` y `ALIAS_NUEVOS`. Validado con `ast.parse` — **sintaxis Python correcta**.

### `integracion_endpoint_V9.py`

Muestra el endpoint `/v1/chat/completions` completo con los nuevos bloques `elif nivel == "DEEP_CHAIN"` y `elif nivel == "AUTO_HEAVY"` integrados en el flujo correcto, preservando toda la lógica existente de V8.

### `openclaw_config_V15.json`

Configuración OpenClaw actualizada con:
- 11 modelos en el catálogo (incluyendo `auto-heavy`, `deep-chain`, `hard`)
- 6 agentes: `coder`, `analyst`, `reasoner`, `researcher`, `deep_reasoner` (usa DCR), `supervisor` (usa auto-heavy)
- 2 herramientas: `search_knowledge_base` (ChromaDB MCP) y `web_search` (SearXNG)

***

## Instrucciones de Integración

### Paso 1: Prerrequisito — descargar phi4 completo

```bash
# En la instancia Ollama GPU (:11434)
ollama pull phi4    # ~8.9 GB — modelo base 14B Q4_K_M
# Verificar disponibilidad:
curl -s http://localhost:11434/api/tags | python3 -c \
  "import sys,json; [print(m['name']) for m in json.load(sys.stdin)['models']]"
```

### Paso 2: Integrar los nuevos módulos en el router

```bash
# Opción A: Añadir al final del archivo V8, antes del bloque if __name__ == "__main__":
cat nuevos_modulos_V9.py >> orchestrator_router_V8.py   # → genera V9

# Opción B (recomendada): Crear V9 como archivo separado
cp orchestrator_router_V8.py orchestrator_router_V9.py
# Luego añadir manualmente las secciones de nuevos_modulos_V9.py
```

### Paso 3: Actualizar ALIAS_A_NIVEL en el router

```python
# Dentro del dict ALIAS_A_NIVEL existente, añadir al final (antes del cierre }):
# [V15-A] Auto-Heavy
"ruteador-heavy":    "AUTO_HEAVY",
"auto-heavy":        "AUTO_HEAVY",
"heavy":             "AUTO_HEAVY",
# [V15-B] Deep Chain Reasoning
"deep-chain":        "DEEP_CHAIN",
"dcr":               "DEEP_CHAIN",
"razonamiento-profundo-auto": "DEEP_CHAIN",
"deep-reasoning-auto":   "DEEP_CHAIN",
"auto-hard-reasoning":   "DEEP_CHAIN",
"hard":              "DEEP_CHAIN",
"chain":             "DEEP_CHAIN",
```

### Paso 4: Modificar el endpoint `/v1/chat/completions`

Añadir los dos bloques `elif` **antes** del bloque `elif nivel is None` (clasificador auto):

```python
# En @app.post("/v1/chat/completions"), después de if nivel == "PHI4_DIRECTO":

elif nivel == "DEEP_CHAIN":
    if streaming:
        log.warning("[DCR] streaming no soportado — forzando no-stream")
    log.info("[MODO] → Deep Chain Reasoning (DCR)")
    return await _ejecutar_deep_chain_reasoning(
        prompt_original     = prompt,
        mensajes_originales = mensajes,
        rutas               = RUTAS,
        conmutar_vram_fn    = _conmutar_vram,
        rag_inject_fn       = _rag_inject,
        inject_opciones_fn  = _inject_opciones_extra,
        metricas            = _metricas,
    )

elif nivel == "AUTO_HEAVY":
    nivel_heavy = await _clasificar_phi4_heavy(prompt)
    log.info(f"[MODO: AUTO-HEAVY] → {nivel_heavy} (Phi-4 14B clasificador)")
    _metricas["clasificador_capas"]["phi4_heavy"] += 1
    nivel = nivel_heavy
    # Continúa al bloque proxy estándar
```

### Paso 5: Ampliar el catálogo `/v1/models`

```python
# Añadir en el array catalog dentro de @app.get("/v1/models"):
{"id": "auto-heavy",  "name": "🏋 Auto-Heavy (Phi-4 14B clasificador)", "ctx": 32768, "max": 16384},
{"id": "deep-chain",  "name": "⛓ Deep Chain Reasoning (3 modelos)", "ctx": 16384, "max": 4096},
{"id": "hard",        "name": "⛓ Hard (alias deep-chain)", "ctx": 16384, "max": 4096},
{"id": "dcr",         "name": "⛓ DCR (alias deep-chain)", "ctx": 16384, "max": 4096},
```

### Paso 6: Actualizar referencia en Autoboot_Cluster_V15.sh

```bash
# En la sección de arranque del router, actualizar el nombre del script:
# De:
python3 /ruta/orchestrator_router_V8.py &
# A:
python3 /ruta/orchestrator_router_V9.py &
```

### Paso 7: Actualizar la configuración de OpenClaw

```bash
# Reemplazar el bloque de configuración de OpenClaw en el Autoboot con el contenido
# de openclaw_config_V15.json — asegurarse de que el GATEWAY_TOKEN sea correcto.
# Si aún está hardcodeado, generar uno nuevo:
export GATEWAY_TOKEN=$(openssl rand -hex 32)
# Y sustituir en el here-doc del Autoboot.
```

***

## Consideraciones de Rendimiento y VRAM

El DCR tiene implicaciones importantes sobre la gestión de VRAM:

1. **Conmutación secuencial**: cada etapa puede requerir una conmutación de VRAM (el lock `_vram_lock` de V14 serializa correctamente las operaciones). Con `exllamav2-api` o `sglang-server` activos, estos se detendrán antes de arrancar los modelos Ollama.

2. **Ollama multimodelo**: DeepSeek R1 14B y Phi-4-reasoning (en ambas variantes) operan todos en la misma instancia Ollama GPU `:11434`. Ollama **descarga el modelo anterior automáticamente** al cargar el siguiente — no hay conflicto de VRAM, pero hay latencia adicional de ~10–30 s por swap.

3. **Modo DCR en paralelo con otras peticiones**: dado que el pipeline tarda varios minutos, OpenClaw puede lanzar otras peticiones mientras DCR procesa. El `_vram_lock` garantiza que las conmutaciones no colisionen, pero la latencia de las peticiones concurrentes aumentará.

4. **Recomendación**: reservar DCR para sesiones de trabajo analítico donde el usuario dedica tiempo a la tarea. No usar DCR para conversación interactiva o iteración rápida.

***

## Matriz de Decisión: ¿Qué Modo Usar?

| Situación                                          | Modo Recomendado        |
|----------------------------------------------------|-------------------------|
| Conversación, preguntas generales                  | `ruteador-auto`         |
| No sabes qué modelo usar, pregunta ambigua         | `auto-heavy`            |
| Código rápido, snippets                            | `instantaneo`           |
| Análisis exhaustivo, filosofía, planificación compleja | `deep-chain` / `hard` |
| Matemáticas, STEM, lógica formal                   | `preciso`               |
| Debugging complejo, arquitectura de software       | `profundo`              |
| Análisis de documentos muy largos                  | `masivo`                |
| Investigación con base de conocimiento + web       | Agente `researcher`     |
| Razonamiento profundo con máxima calidad           | Agente `deep_reasoner`  |

---

## References

1. [Rethinking Mixture-of-Agents: Is Mixing Different](https://www.arxiv.org/pdf/2502.00674.pdf)

2. [Ensemble Debates with Local Large Language Models for AI ... - arXiv](https://arxiv.org/html/2509.00091v1)

3. [RETHINKING MIXTURE-OF-AGENTS: IS MIXING DIF](https://openreview.net/pdf?id=ioprnwVrDH)

4. [What is Mixture of Agents (MoA)? | Ultralytics](https://www.ultralytics.com/glossary/mixture-of-agents-moa) - A Mixture of Agents (MoA) is an advanced artificial intelligence architecture that leverages multipl...

5. [Phi-4-reasoning Technical Report](https://www.microsoft.com/en-us/research/wp-content/uploads/2025/04/phi_4_reasoning.pdf)

6. [Phi-4 vs Gemma 3 vs Llama 3.3 — Enterprise Edge AI [2026]](https://www.meta-intelligence.tech/en/insight-slm-enterprise) - The routing logic can be based on a rule engine for task types, or a smaller classification model (s...

7. [Adaptive Consensus in LLM Ensembles via Sequential Evidence ...](https://papers.cool/arxiv/2605.04236) - Large Language Model ensembles improve reasoning accuracy up to a performance boundary; beyond it, a...

8. [4. Experiment](https://arxiv.org/html/2510.16645v1)

9. [LLM-as-a-Judge](https://langfuse.com/docs/scores/model-based-evals) - Configure, run, and monitor LLM-powered evaluators on traces and dataset experiments.

10. [Run Experiments with LLM as a Judge - Phoenix - Arize AI](https://arize.com/docs/phoenix/datasets-and-experiments/tutorial/run-experiments-with-llm-judge)

