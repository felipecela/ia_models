# Informe de Actualización: Indexador Vault V3 (OMEN AI Cluster V18)

## 1. Introducción
Como parte de la evolución del ecosistema **OMEN AI Cluster V18**, se ha realizado una auditoría exhaustiva y refactorización completa del componente de indexación de Obsidian (`indexar_vault_v2.py`). El objetivo principal de esta actualización ha sido mejorar significativamente la calidad de los embeddings almacenados en ChromaDB, garantizando que el sistema de *Retrieval-Augmented Generation* (RAG) proporcione contexto de alta relevancia a la nueva capa de *Autonomous Reasoning Agent*.

## 2. Análisis de Deficiencias en la Versión Anterior (V2)
Durante el análisis profundo del código V2, se identificaron múltiples limitaciones que degradaban el rendimiento del sistema:

| Deficiencia Identificada | Impacto en el Sistema |
| :--- | :--- |
| **Chunking no semántico** | La división estricta por caracteres (512 fijos) cortaba frases por la mitad, destruyendo el contexto semántico necesario para que los modelos de lenguaje comprendieran la información correctamente. |
| **Indexación de sintaxis cruda** | Se indexaba la sintaxis Markdown (`#`, `**`, `[[links]]`, frontmatter YAML), lo que introducía ruido (tokens innecesarios) en los vectores de embedding. |
| **Falta de Rate Limiting** | La invocación secuencial sin pausas hacia Ollama CPU podía saturar el servidor local durante la indexación de vaults grandes, provocando *timeouts* irrecuperables. |
| **Acumulación de huérfanos** | El modo incremental detectaba archivos nuevos o modificados, pero ignoraba los archivos eliminados del vault, dejando "basura" persistente en ChromaDB. |
| **Metadatos insuficientes** | Solo se guardaba la ruta del archivo, limitando drásticamente la capacidad de filtrado avanzado (por fecha, etiquetas o secciones) durante las consultas RAG. |

## 3. Mejoras Implementadas en la Versión V3
La nueva versión `indexar_vault_v3.py` resuelve todas las deficiencias anteriores e introduce capacidades avanzadas de procesamiento de lenguaje natural.

### 3.1. Chunking Semántico Inteligente
Se ha reemplazado la división por longitud fija por un algoritmo de *chunking* semántico. El nuevo sistema analiza la estructura del documento Markdown, dividiéndolo por secciones (basadas en encabezados `H1-H6`) y posteriormente por párrafos completos. Si un párrafo excede el límite máximo (800 caracteres), se divide respetando los límites de las frases (`.`, `!`, `?`). Esto garantiza que cada vector almacenado contenga una idea completa y coherente.

### 3.2. Preprocesamiento y Limpieza de Markdown
Antes de la vectorización, el texto atraviesa un pipeline de limpieza riguroso:
* Eliminación del *frontmatter* YAML (extrayendo previamente los *tags*).
* Resolución de enlaces internos de Obsidian (ej. `[[Nota|Alias]]` se convierte en `Alias`).
* Eliminación de marcadores de formato visual (`**`, `_`, `> [!info]`).
* Reemplazo de bloques de código extensos por marcadores genéricos, evitando que el código sature el espacio vectorial semántico del texto natural.

### 3.3. Metadatos Enriquecidos
Cada fragmento (*chunk*) almacenado en ChromaDB ahora incluye un conjunto ampliado de metadatos:
* `title`: Extraído del primer encabezado `H1` o derivado del nombre del archivo.
* `heading`: El subtítulo de la sección específica a la que pertenece el fragmento.
* `tags`: Etiquetas extraídas del *frontmatter* YAML o del contenido en línea (`#etiqueta`).
* `mtime`: Fecha de última modificación en formato ISO 8601.
* `word_count`: Conteo exacto de palabras útiles en el fragmento.

### 3.4. Resiliencia y Rendimiento de Red
Se ha implementado un sistema de *Rate Limiting* (límite de peticiones) combinado con una estrategia de reintentos mediante *Exponential Backoff* (retroceso exponencial). Si el contenedor de Ollama CPU experimenta latencia o rechaza la conexión, el indexador esperará y reintentará progresivamente (2s, 4s, 8s) hasta 3 veces antes de fallar. Además, el *timeout* de la petición ahora es adaptativo, calculándose dinámicamente en función de la longitud del fragmento de texto.

### 3.5. Purga de Archivos Eliminados (Modo `--prune`)
El indexador ahora es capaz de comparar las fuentes indexadas en ChromaDB con los archivos físicos existentes en el directorio del *vault*. Cualquier fragmento cuyo archivo de origen haya sido eliminado será purgado automáticamente. Esta funcionalidad se ejecuta por defecto en el modo incremental, pero también puede invocarse de forma independiente mediante el nuevo flag `--prune`.

## 4. Integración con Autoboot V18
El script de despliegue principal (`Autoboot_Cluster_V18.sh`) ha sido actualizado en la línea 72 para invocar directamente a `indexar_vault_v3.py`. Además, se ha garantizado la coherencia en la persistencia del estado: el archivo `.indexar_vault_state.json` ahora se almacena de forma segura en la partición `ext4` (utilizando la variable de entorno `AGENT_DB_DIR`), previniendo las corrupciones previamente observadas en el sistema de archivos `exFAT`.
