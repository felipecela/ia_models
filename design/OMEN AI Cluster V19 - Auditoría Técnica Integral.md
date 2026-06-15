# Auditoría Técnica Integral - OMEN AI Cluster V18

## 1. Introducción

El presente documento detalla los resultados de la auditoría técnica realizada sobre el sistema OMEN AI Cluster V18, el cual incluye los componentes `Autoboot_Cluster_V18.sh`, `orchestrator_router_V11.py` e `indexar_vault_v3.py`. El análisis ha abordado la arquitectura, diseño, flujo de enrutamiento, gestión de recursos, compatibilidad con exFAT y robustez general del sistema.

## 2. Hallazgos Identificados

### 2.1. Errores Lógicos e Inconsistencias Arquitectónicas

1.  **Divergencia en el Nivel PRECISO:** Como indicó el usuario, existe una divergencia crítica en `orchestrator_router_V11.py`. En la descripción de embeddings (`_EMBED_DESCRIPTIONS["PRECISO"]`, línea 275) se omitió "resultado numérico STEM" y otros términos presentes en el prompt del clasificador LLM (`_SYSTEM_PHI4`, línea 303). Esto provoca que la capa 2 (Embeddings) y la capa 3 (LLM) del clasificador utilicen criterios distintos, generando un enrutamiento inconsistente.
2.  **Incompatibilidad con exFAT en SQLite:** El script `Autoboot_Cluster_V18.sh` crea `AGENT_DATA_DIR` en `$AI_HOME` (ext4) y lo exporta como `AGENT_DB_DIR`. Sin embargo, si el router se ejecuta manualmente o el script de inicio falla en exportar la variable, `_AGENT_DB_DIR` en `orchestrator_router_V11.py` hace fallback a `os.path.dirname(os.path.abspath(__file__))`. Si el router se encuentra en la unidad compartida exFAT (como podría ocurrir en entornos de desarrollo híbridos), SQLite fallará irremediablemente al usar WAL y bloqueos concurrentes no soportados por exFAT.
3.  **Dependencias Circulares en el Agente Autónomo:** En `orchestrator_router_V11.py`, el método `_execute_subtask` llama a `_agent_llm_call`, que a su vez llama a `_conmutar_vram`. Esto puede provocar deadlocks si `_conmutar_vram` se bloquea o si hay múltiples subtareas compitiendo por recursos de GPU, especialmente dado que `_agent_semaphore` permite concurrencia de 2 pero la GPU solo puede cargar un modelo pesado a la vez.

### 2.2. Riesgos Operativos y de Rendimiento

4.  **Rate Limiting Deficiente en Indexador:** En `indexar_vault_v3.py`, el timeout adaptativo (`adaptive_timeout = EMBED_TIMEOUT + (len(text) / 100) * 0.01`) añade solo 0.01s por cada 100 caracteres. Para un chunk máximo de 800 caracteres, esto añade apenas 0.08s, lo cual es insuficiente si el modelo de embeddings en CPU se satura bajo carga. Además, el `time.sleep` en el backoff exponencial es bloqueante y no permite procesar otros archivos concurrentemente.
5.  **Timeout en el Proxy Asíncrono:** En `orchestrator_router_V11.py`, el proxy asíncrono (`_proxy`) maneja el fallback si ocurre un `httpx.TimeoutException`. Sin embargo, el cliente original HTTP (OpenWebUI) podría hacer timeout antes de que el router termine de intentar el fallback, dejando un proceso zombi en el router que consume recursos innecesariamente.
6.  **Gestión de Memoria en SQLite:** El motor del agente en `orchestrator_router_V11.py` abre y cierra conexiones a SQLite (`_db_conn()`) repetidamente en bucles (por ejemplo, dentro de `_run_task` para cada subtarea). Aunque usa WAL, esto genera overhead innecesario y aumenta la probabilidad de bloqueos por `busy_timeout` bajo alta concurrencia.

### 2.3. Problemas de Seguridad y Robustez

7.  **Inyección de Prompts en RAG:** En `_rag_inject` (`orchestrator_router_V11.py`), el contexto extraído de ChromaDB se inyecta directamente en el system prompt. Si un documento en el vault contiene instrucciones maliciosas (prompt injection), el modelo podría obedecerlas, comprometiendo el razonamiento del agente.
8.  **Graceful Shutdown Incompleto:** En `Autoboot_Cluster_V18.sh`, la función `cleanup` envía SIGTERM al router, pero si hay subtareas del agente ejecutándose, el router no espera a que terminen ni guarda su estado de manera segura antes de cerrarse, lo que puede corromper el estado de la tarea en la base de datos.
9.  **Falta de Validación de Entradas en el Agente:** El endpoint `/v1/agent/tasks` no valida la longitud máxima del prompt ni sanea caracteres especiales, lo que podría provocar errores en la planificación o desbordamiento de memoria en el LLM.

## 3. Plan de Corrección

1.  **Sincronizar Descripciones del Clasificador:** Actualizar `_EMBED_DESCRIPTIONS["PRECISO"]` para que coincida exactamente con los criterios de `_SYSTEM_PHI4`, incluyendo "resultado exacto numérico STEM".
2.  **Reforzar Fallback de SQLite:** Asegurar que `_AGENT_DB_DIR` siempre apunte a un directorio en ext4, forzando la creación de un directorio temporal en `/tmp` si `$HOME/ai_cluster/agent_data` no está disponible o es exFAT.
3.  **Optimizar Concurrencia y VRAM:** Revisar el uso de `_agent_semaphore` y `_vram_lock` para evitar deadlocks, posiblemente limitando la ejecución concurrente de subtareas que requieran distintos modelos en GPU.
4.  **Mejorar Timeout y Retries:** Ajustar el cálculo de timeout adaptativo en el indexador y usar `asyncio.sleep` en lugar de `time.sleep` si se migra a un enfoque asíncrono, o ajustar los valores para ser más realistas.
5.  **Sanitización y Seguridad:** Implementar delimitadores estrictos en la inyección de RAG y validación de longitud en el endpoint de creación de tareas.
6.  **Optimizar Conexiones SQLite:** Implementar un connection pool o reutilizar la conexión dentro de las funciones principales del agente para reducir el overhead.
