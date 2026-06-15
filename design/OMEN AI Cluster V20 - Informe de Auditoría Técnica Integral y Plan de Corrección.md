# Informe de Auditoría Técnica Integral y Plan de Corrección
**OMEN AI Cluster V19 → V20**

## 1. Resumen Ejecutivo

Se ha realizado una auditoría técnica exhaustiva de los tres componentes principales del clúster de IA local (Autoboot, Orquestador Router e Indexador del Vault). El análisis crítico ha revelado que, si bien la arquitectura base es sólida y presenta múltiples implementaciones de alta calidad (como la serialización de VRAM, graceful shutdown y escritura atómica), existen vulnerabilidades significativas en la gestión de concurrencia, manejo de recursos y consistencia entre componentes.

Se han identificado **32 hallazgos**, desglosados en:
* **Críticos / Alta gravedad (5)**: Condiciones de carrera en semáforos, bloqueos potenciales, resource leaks en SQLite.
* **Gravedad Media (15)**: Fallos en el manejo de errores HTTP, inconsistencias en la detección de filesystem, timeouts no controlados, y vulnerabilidades de denegación de servicio (DoS) por falta de límites.
* **Gravedad Baja (12)**: Problemas de mantenibilidad, edge cases en parsing JSON, y optimizaciones de rendimiento.

## 2. Hallazgos Principales por Componente

### 2.1. Autoboot_Cluster (Script de Arranque)
El script de inicialización presenta debilidades en la sincronización de procesos en background y el manejo de dependencias.

* **[AB-01] Condición de carrera en sincronización de pulls (ALTA)**: El uso de `wait 2>/dev/null || true` tras lanzar los pulls de modelos Ollama en background espera a *todos* los procesos del shell, lo que puede causar bloqueos si hay otros procesos no relacionados.
* **[AB-02] Riesgo de escritura en filesystem raíz (ALTA)**: Falta de verificación estricta del montaje de `/mnt/ai_core`. Si el SSD exFAT no está montado, el script creará la estructura en la partición del sistema operativo.
* **[AB-04] Eliminación indiscriminada de procesos (MEDIA-ALTA)**: `fuser -k 8000/tcp` mata cualquier proceso en el puerto 8000 sin verificar que realmente pertenezca al router.
* **[AB-07] Desincronización en arranque del indexador (MEDIA)**: El indexador se lanza antes de confirmar que el modelo de embeddings `nomic-embed-text` ha terminado de descargarse.

### 2.2. Orchestrator Router (Enrutamiento Semántico)
El núcleo del sistema presenta vulnerabilidades críticas de concurrencia y fugas de recursos en su interacción con la base de datos.

* **[RT-01] Doble liberación de semáforo en concurrencia (ALTA)**: En `_agent_llm_call`, un fallo de timeout con fallback exitoso libera el semáforo, pero el bloque `finally` intenta liberarlo nuevamente, lo que puede corromper el estado de concurrencia de otros workers.
* **[RT-02] Fuga de conexiones SQLite (MEDIA-ALTA)**: Las conexiones a la base de datos en `_run_task` no utilizan context managers. Una excepción durante la ejecución dejará la conexión abierta, causando bloqueos de WAL (Write-Ahead Logging).
* **[RT-04] Falta de validación de entrada en endpoints (MEDIA-ALTA)**: `/v1/chat/completions` asume la estructura del payload sin validación previa, lo que expone el sistema a excepciones no controladas por payloads malformados.
* **[RT-10] Vulnerabilidad DoS en creación de tareas (MEDIA)**: No existe límite para la cantidad de tareas concurrentes que el agente puede aceptar, lo que permite la saturación de recursos (CPU/VRAM).

### 2.3. Indexador del Vault (ChromaDB RAG)
El indexador semántico requiere mejoras en la robustez del manejo de señales y coherencia arquitectónica.

* **[IX-01] Reentrada insegura en manejador de señales (MEDIA-ALTA)**: `_signal_handler` invoca `save_state`, la cual realiza operaciones de I/O. Si la señal interrumpe una escritura en curso, se corromperá el estado incremental.
* **[IX-12] Inconsistencia en políticas de filesystem (MEDIA)**: A diferencia del router que implementa un fallback real si detecta exFAT para SQLite, el indexador solo emite un warning pero continúa escribiendo el estado en el filesystem inseguro.
* **[IX-04] Paginación frágil en recuperación de fuentes (MEDIA)**: `chroma_get_all_sources` utiliza `offset/limit`, lo cual es propenso a omisiones si la colección muta durante la paginación.

## 3. Plan de Acción y Correcciones (Fase 2)

Se procederá a la generación de las nuevas versiones incrementales aplicando las siguientes correcciones arquitectónicas:

### Fase 2.1: Generación de Autoboot_Cluster_V20.sh
1. Implementar captura explícita de PIDs para los procesos en background y usar `wait $PID` específico.
2. Añadir verificación estricta de punto de montaje (`mountpoint -q`) antes de operar sobre `/mnt/ai_core`.
3. Refinar la lógica de limpieza de puertos utilizando `lsof` y validando el nombre del proceso (`python`).
4. Introducir bloqueos de espera (wait loops) para asegurar que Ollama CPU esté plenamente operativo antes de invocar al indexador.

### Fase 2.2: Generación de orchestrator_router_V13.py
1. Refactorizar `_agent_llm_call` implementando un flag de estado `_released` para garantizar una única liberación del semáforo.
2. Migrar todas las interacciones con SQLite al uso de `contextlib.closing` o bloques `try/finally` estrictos.
3. Optimizar `_task_log` para aceptar conexiones reutilizables, reduciendo el overhead de I/O.
4. Implementar validación estricta de payloads entrantes y un límite de concurrencia global (`MAX_ACTIVE_TASKS`) con respuesta HTTP 429.

### Fase 2.3: Generación de indexar_vault_v5.py
1. Modificar el signal handler para únicamente establecer un flag (`_shutdown_requested = True`), delegando el guardado de estado al hilo principal.
2. Homogeneizar la validación de filesystem importando la lógica de fallback del router (redirección automática a ext4/tmpfs si se detecta exFAT).
3. Añadir retries configurados a nivel de sesión HTTP para las interacciones con ChromaDB.
4. Mejorar la firma de archivos combinando `st_mtime` con tamaño exacto para mitigar la baja resolución temporal de exFAT.

La ejecución de este plan garantizará la consolidación del sistema hacia un estado de alta disponibilidad, resolviendo las inconsistencias lógicas y vulnerabilidades de concurrencia detectadas.
