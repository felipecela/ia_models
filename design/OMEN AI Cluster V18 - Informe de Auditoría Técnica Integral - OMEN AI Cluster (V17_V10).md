# Informe de Auditoría Técnica Integral - OMEN AI Cluster (V17/V10)

## 1. Resumen Ejecutivo
El sistema OMEN AI Cluster V17 (Autoboot) y su Orchestrator Router V10 representan una arquitectura robusta de enrutamiento dinámico de LLMs locales en un entorno con recursos limitados (RTX 4070 8GB, 32GB RAM). La solución actual gestiona eficientemente el intercambio de modelos (Hard Reasoning) basándose en una clasificación multicapa (agente, caché, embeddings, fallback a Phi-4). 

Sin embargo, para cumplir con el objetivo evolutivo de integrar un **Autonomous Reasoning Agent** (Agente de Razonamiento Autónomo), la auditoría revela ciertas limitaciones arquitectónicas y oportunidades de mejora, especialmente en la gestión de estado de las tareas complejas, la concurrencia en la capa de razonamiento profundo y la orquestación de subtareas asíncronas.

## 2. Análisis Arquitectónico

### 2.1. Autoboot (Autoboot_Cluster_V17.sh)
- **Aciertos:** Excelente gestión de idempotencia de contenedores, creación explícita de red (`ai_net`), y manejo de almacenamiento persistente mixto (exFAT para modelos/vault, ext4 para ChromaDB/logs). Implementación sólida de mecanismos de reintento (`wait_port`) y limpieza de procesos (`trap EXIT`).
- **Debilidades:** El script es secuencial y asume que el Router (V10) se ejecuta como un proceso host (`python3 ...`). Si el nuevo Agente Autónomo requiere colas de tareas persistentes (ej. Redis/RabbitMQ) o una base de datos para estados de iteración (SQLite/PostgreSQL), el Autoboot actual no las provisiona.

### 2.2. Orquestador (orchestrator_router_V10.py)
- **Aciertos:** Sistema de clasificación de 4 capas muy avanzado. Manejo explícito de locks (`_vram_lock`) para evitar condiciones de carrera al intercambiar contenedores en Docker. Integración nativa de RAG inyectando contexto de Obsidian. Fallbacks de timeout automáticos (ej. de MASIVO a PROFUNDO).
- **Debilidades:** 
  - **Estado efímero:** El orquestador actúa como un proxy pasivo. Recibe un request, lo enruta, espera la respuesta y la devuelve. Un Agente Autónomo requiere mantener un estado (plan, subtareas, iteraciones). El router actual no tiene noción de "tarea de larga duración".
  - **Bloqueo por Timeout:** Las tareas de razonamiento autónomo (planificar, ejecutar, validar) excederán con creces los timeouts HTTP actuales (máximo 320s en MASIVO).
  - **Concurrencia de VRAM:** El `_vram_lock` serializa el acceso a la GPU. Si el Agente Autónomo necesita consultar simultáneamente un modelo `AGIL` (para resumir) y un modelo `PROFUNDO` (para analizar), el lock bloqueará uno de ellos, impidiendo el paralelismo real de subtareas.

### 2.3. Indexador (indexar_vault_v2.py)
- **Aciertos:** Indexación incremental inteligente usando firmas de archivo. Independencia de librerías pesadas (usa HTTP directo a ChromaDB). Manejo robusto de encoding de archivos.
- **Debilidades:** El indexador es un script batch (`cron`-like). El Agente Autónomo podría necesitar indexar o recuperar información *en tiempo real* (ej. guarda el resultado de una iteración en Obsidian y necesita que esté disponible en ChromaDB inmediatamente para el siguiente ciclo).

## 3. Hallazgos y Vulnerabilidades

### 3.1. Problemas de Diseño y Lógica
1. **Ausencia de persistencia de estado para tareas largas:** El orquestador es stateless. Si el Agente Autónomo realiza un ciclo DevOps (plan -> code -> test), un fallo de red o un reinicio del router perderá todo el progreso.
2. **Timeouts rígidos en el proxy:** Las peticiones HTTP largas fallarán si el Agente Autónomo tarda minutos u horas en completar un ciclo iterativo.
3. **Falta de endpoint de Agent/Task API:** La API actual (`/v1/chat/completions`) está diseñada para un flujo síncrono pregunta-respuesta, no para desencadenar tareas autónomas en background.

### 3.2. Gestión de Recursos y Concurrencia
1. **Cuello de botella en `_vram_lock`:** Si múltiples agentes o hilos del Agente Autónomo intentan acceder a modelos incompatibles, se producirá un thrashing continuo de contenedores Docker (arrancar/parar), degradando severamente el rendimiento y desgastando el SSD.
2. **Dependencia síncrona de RAG:** La inyección de RAG ocurre en el hilo principal del request proxy. Para un Agente Autónomo que genera múltiples prompts internamente, esto añade latencia acumulativa.

### 3.3. Estabilidad y Tolerancia a Fallos
1. **Falta de checkpointing:** El razonamiento "Hard" actual fusiona respuestas al final. Si una subtarea falla, no hay mecanismo para reanudar desde el último punto válido.
2. **Gestión de dependencias del Agente:** El agente autónomo necesitará ejecutar código o validar resultados. Actualmente no hay un entorno aislado (sandbox) o herramienta de validación de código para que el agente pruebe sus soluciones de forma segura.

## 4. Recomendaciones Prioritarias para V18 / V11

1. **Evolución del API del Router (V11):**
   - Añadir un sistema de colas asíncronas (ej. `asyncio.Queue` o SQLite) para gestionar "Jobs" de larga duración.
   - Crear nuevos endpoints: `POST /v1/agent/tasks` (para iniciar un plan autónomo) y `GET /v1/agent/tasks/{id}` (para consultar el estado/progreso).

2. **Implementación de la Capa de Agente Autónomo:**
   - Diseñar un módulo interno en el Router V11 que implemente el bucle del agente (Planificar -> Ejecutar -> Validar -> Iterar).
   - El agente debe poder hacer llamadas internas a `_clasificar` y `_proxy` sin pasar por la capa HTTP pública, utilizando el modelo adecuado para cada subtarea (ej. `INSTANTANEO` para generar código, `PROFUNDO` para validar lógica).

3. **Mejoras en el Autoboot (V18):**
   - Provisionar una base de datos ligera (SQLite persistida en `$AI_HOME`) para guardar el estado de las tareas del Agente.
   - Asegurar que el entorno de ejecución del Router V11 tenga acceso a herramientas básicas si el agente necesita validar código (o usar contenedores efímeros de Docker para pruebas).

4. **Optimización de Conmutación de VRAM:**
   - Implementar un mecanismo de "batching" o "affinity" donde el Agente Autónomo agrupe las tareas que requieren el mismo modelo para minimizar los cambios de contexto en la GPU.

## 5. Diseño Arquitectónico Propuesto: Autonomous Reasoning Agent

El nuevo Agente actuará como un "Meta-Orquestador" que reside dentro del Router V11. 

**Flujo de Ejecución:**
1. **Recepción (Task Ingestion):** El usuario envía un prompt complejo al nuevo endpoint `/v1/agent/tasks`.
2. **Planificación (AGIL/PROFUNDO):** El Agente usa un modelo de alto contexto para descomponer la tarea en un JSON estructurado con subtareas (Plan).
3. **Bucle de Iteración (DevOps Loop):**
   - Por cada subtarea, el Agente determina el nivel necesario (ej. `INSTANTANEO` para código).
   - Ejecuta la generación.
   - Llama a una fase de **Validación** (usando `PRECISO` o `PROFUNDO`) para verificar la salida.
   - Si la validación falla, el Agente re-planifica o re-intenta la subtarea con el feedback del error.
4. **Consolidación (MASIVO/AGIL):** Una vez todas las subtareas pasan la validación, el Agente fusiona los resultados en un entregable final.
5. **Persistencia Continua:** En cada paso, el estado de la tarea se guarda en SQLite. El usuario puede hacer polling del progreso.

---
*Fin de la Auditoría Inicial. Procediendo al diseño e implementación detallada de la Fase 2.*
