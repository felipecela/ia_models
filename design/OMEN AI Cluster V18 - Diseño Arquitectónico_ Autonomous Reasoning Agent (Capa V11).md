# Diseño Arquitectónico: Autonomous Reasoning Agent (Capa V11)

## 1. Visión General
El **Autonomous Reasoning Agent** es una nueva capa superior integrada dentro del Orchestrator Router V11. Su objetivo principal es dotar al sistema de capacidades de razonamiento a largo plazo. A diferencia del enrutamiento tradicional que procesa peticiones síncronas de entrada y salida, este agente es capaz de recibir tareas complejas, descomponerlas en un plan de acción estructurado, y ejecutar iterativamente cada paso. Durante esta ejecución, el agente delega inteligentemente las cargas de trabajo en los modelos locales adecuados utilizando el enrutamiento existente. Además, incorpora mecanismos de validación de resultados, corrección autónoma de errores y consolidación de la salida final, operando de manera asíncrona en segundo plano.

## 2. Componentes Principales

El diseño del agente se divide en cinco componentes fundamentales que interactúan de manera cíclica para lograr la resolución de tareas complejas. Estos componentes simulan un flujo de trabajo estructurado similar a las metodologías DevOps, garantizando que cada paso sea evaluado antes de avanzar al siguiente.

| Componente | Responsabilidad Principal | Modelo Preferido | Detalles de Implementación |
| :--- | :--- | :--- | :--- |
| **Task Manager** | Administrar el ciclo de vida y estado de las tareas de larga duración. | N/A (Lógica interna) | Utiliza una base de datos SQLite local (`agent_tasks.db`) para persistir el estado de las tareas y subtareas. Expone los endpoints `POST /v1/agent/tasks` y `GET /v1/agent/tasks/{task_id}`. |
| **Planner Module** | Analizar el prompt inicial y generar un plan de ejecución detallado. | `AGIL` o `PROFUNDO` | Recibe la petición del usuario y genera una estructura JSON que define las subtareas necesarias, sus dependencias y el nivel de razonamiento sugerido para cada una. |
| **Execution Engine** | Ejecutar el plan de forma autónoma e iterativa. | Dinámico (según subtarea) | Opera mediante un bucle asíncrono en background. Selecciona subtareas pendientes, invoca la lógica de enrutamiento interno (saltando la capa HTTP para mayor eficiencia) y almacena los resultados parciales. |
| **Validation Loop** | Asegurar la calidad y correctitud del resultado de cada subtarea. | `PRECISO` o `PROFUNDO` | Evalúa el resultado generado por el Execution Engine. Si detecta errores, genera feedback detallado y devuelve la subtarea a la cola de ejecución para un reintento, aplicando un límite máximo de intentos. |
| **Consolidator** | Unir todos los resultados parciales en una respuesta final coherente. | `MASIVO` o `AGIL` | Se activa únicamente cuando todas las subtareas han sido completadas exitosamente. Sintetiza la información y marca la tarea global como finalizada. |

## 3. Integración con el Enrutador Existente (Hard Reasoning)

El nuevo agente no reemplaza la infraestructura de V10, sino que la envuelve y reutiliza sus capacidades fundamentales. La integración mantiene un respeto estricto por las restricciones de memoria de video (VRAM) mediante el uso continuo del mecanismo `_vram_lock`, garantizando que las conmutaciones de contenedores Docker se realicen de manera segura y serializada.

Asimismo, el agente aprovecha la inyección de contexto RAG basada en ChromaDB durante las fases de planificación y ejecución, siempre que el contexto del Vault de Obsidian sea relevante para la tarea en curso. El clasificador multicapa existente (`_clasificar`) se mantiene activo y puede ser invocado opcionalmente por el Planner Module para decidir dinámicamente qué nivel de razonamiento asignar a una subtarea cuando la decisión no sea trivial.

## 4. Metodología DevOps Simulada

El bucle de iteración interno del agente simula un pipeline continuo de integración y despliegue (CI/CD). La fase de ejecución actúa como la etapa de construcción y desarrollo de código o contenido. Posteriormente, la fase de validación funciona como una suite de pruebas automatizadas que evalúa rigurosamente la salida contra los requisitos iniciales de la subtarea. Si la validación es exitosa, el resultado se aprueba y se avanza en el plan. En caso de fallo, el feedback generado actúa como un reporte de error detallado, retroalimentando la fase de ejecución para el siguiente ciclo iterativo.

## 5. Cambios Requeridos en el Código

Para materializar esta arquitectura, se requieren modificaciones específicas en los artefactos principales del clúster. En el archivo `orchestrator_router_V11.py`, será necesario incorporar el manejo de bases de datos mediante SQLite para la persistencia del estado. Se deberán implementar las clases asíncronas correspondientes al Planner, Executor y Validator, e inyectar el bucle de procesamiento en el ciclo de vida de FastAPI. Además, se añadirán los nuevos endpoints bajo la ruta `/v1/agent/`.

Por otro lado, en el script de arranque `Autoboot_Cluster_V18.sh`, se actualizarán las referencias de versión para apuntar a los nuevos archivos. También se implementarán validaciones adicionales para asegurar que el directorio destinado a almacenar la base de datos SQLite cuente con los permisos de escritura adecuados antes de iniciar el servicio del enrutador.
