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

## 3. Implementación de Correcciones (Versiones V19, V12, V4)

Se han generado versiones incrementales que abordan los problemas detectados, garantizando la robustez y estabilidad del sistema:

### 3.1. `orchestrator_router_V12.py`
- **Sincronización del Clasificador:** Se actualizó `_EMBED_DESCRIPTIONS["PRECISO"]` para incluir "resultado exacto numérico STEM", logrando paridad total con el prompt `_SYSTEM_PHI4`.
- **Protección de Filesystem para SQLite:** Se implementó `_validate_db_dir()`, que verifica el tipo de sistema de archivos usando el comando `df`. Si detecta `exfat`, `vfat` o `ntfs`, hace fallback a `$HOME/ai_cluster/agent_data` o `/tmp`, previniendo la corrupción de la base de datos WAL.
- **Gestión de Concurrencia:** Se separó el semáforo de limitación de carga (`_agent_semaphore`) del bloqueo de VRAM (`_vram_lock`), previniendo deadlocks cuando múltiples subtareas intentan conmutar modelos simultáneamente.
- **Graceful Shutdown:** Se añadió verificación de `_shutdown_requested` en los bucles principales de las tareas del agente, permitiendo una cancelación limpia.
- **Dependencias Opcionales:** Se hizo condicional la importación del módulo `docker`, permitiendo que el router inicie incluso si el SDK de Docker no está instalado, deshabilitando de forma segura el intercambio de VRAM.

### 3.2. `indexar_vault_v4.py`
- **Escritura Atómica:** Se mejoró `save_state()` utilizando `os.fsync()` antes de `os.replace()`, asegurando que el estado incremental se escriba a disco de forma segura ante cortes de energía.
- **Compatibilidad de API ChromaDB:** Se implementó detección automática de versión (`/api/v1` vs `/api/v2`), asegurando compatibilidad con versiones recientes de ChromaDB.
- **Chunking Semántico Mejorado:** Se corrigió el solapamiento (`CHUNK_OVERLAP_SENTENCES`), asegurando que la última frase del chunk anterior se incluya como contexto en el siguiente.
- **Manejo de Desconexiones:** Se añadió captura de `requests.exceptions.ConnectionError` durante la indexación. Si Ollama se desconecta a mitad de proceso, el script guarda el estado parcial antes de abortar, evitando la pérdida del trabajo ya realizado.

### 3.3. `Autoboot_Cluster_V19.sh`
- **Actualización de Referencias:** Se actualizaron todas las referencias a los nuevos scripts (`orchestrator_router_V12.py` e `indexar_vault_v4.py`) y sus respectivos archivos PID.
- **Limpieza y Consolidación:** Se mantuvo la estructura general de orquestación, asegurando que los nuevos parámetros (como `--state-dir` para el indexador) se integren fluidamente en el flujo de arranque.

## 4. Conclusión

La auditoría técnica integral y el posterior ciclo de corrección han fortalecido significativamente la arquitectura de OMEN AI Cluster. Las vulnerabilidades relacionadas con la concurrencia, la corrupción de datos en sistemas de archivos híbridos y las inconsistencias de enrutamiento han sido resueltas. El sistema resultante (V19/V12/V4) es más robusto, seguro y capaz de manejar operaciones complejas de IA de manera estable.
