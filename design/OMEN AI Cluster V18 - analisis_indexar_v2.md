# Análisis Exhaustivo: indexar_vault_v2.py

## Hallazgos Críticos

### 1. Chunking por caracteres (no semántico)
- `chunk_text()` divide por posición fija (512 chars con 64 overlap)
- No respeta límites de párrafo, encabezados ni bloques de código
- Resultado: chunks que cortan frases a mitad, degradando calidad de embeddings
- **Solución V3**: Chunking semántico por párrafos/secciones con fallback a tamaño

### 2. Sin limpieza de contenido Markdown
- El texto se indexa con toda la sintaxis Markdown cruda (###, **, [[]], etc.)
- Los links internos de Obsidian (`[[nota]]`) no se resuelven ni limpian
- Los bloques de código, YAML frontmatter y tags se indexan como texto plano
- **Solución V3**: Preprocesamiento que elimina frontmatter, limpia sintaxis, extrae texto limpio

### 3. Sin rate limiting para embeddings
- `get_embedding()` se llama secuencialmente sin ningún throttle
- Si el vault tiene miles de archivos, puede saturar Ollama CPU
- No hay retry con backoff exponencial ante errores transitorios
- **Solución V3**: Rate limiter + retry con backoff exponencial

### 4. Metadatos insuficientes
- Solo se almacena: source, chunk_index, total_chunks
- No se almacena: título del documento, encabezado de sección, fecha de modificación, tags
- Esto limita la capacidad de filtrado en queries RAG
- **Solución V3**: Metadatos enriquecidos (title, heading, mtime, tags, word_count)

### 5. Sin detección de archivos eliminados
- El modo incremental detecta archivos nuevos/modificados pero NO archivos borrados
- Los fragmentos de archivos eliminados persisten indefinidamente en ChromaDB
- **Solución V3**: Detección de archivos eliminados y purga automática

### 6. STATE_FILE en directorio del script (potencialmente exFAT)
- Si el script está en `/mnt/ai_core` (exFAT), el state file puede tener problemas
- Debería usar AGENT_DB_DIR o AI_HOME para garantizar ext4
- **Solución V3**: Variable de entorno para state dir, fallback a $HOME/ai_cluster

### 7. Sin paralelismo en embeddings
- Cada embedding es una llamada HTTP secuencial
- Con 1000 archivos × 10 chunks = 10000 llamadas secuenciales
- **Solución V3**: Batch embeddings (Ollama soporta múltiples prompts)

### 8. chunk_id usa MD5 (colisiones teóricas)
- MD5 no es resistente a colisiones (aunque para IDs internos es aceptable)
- **Solución V3**: Usar SHA-256 truncado para mayor robustez

### 9. Sin progreso visual para operaciones largas
- Solo imprime con --verbose, sin barra de progreso
- **Solución V3**: Barra de progreso simple (sin dependencias externas)

### 10. Sin validación de dimensionalidad de embeddings
- No verifica que todos los embeddings tengan la misma dimensión
- Un embedding corrupto podría causar errores silenciosos en ChromaDB
- **Solución V3**: Validación de dimensión antes de upsert

### 11. Manejo de errores en chroma_delete_by_filepath
- El `pass` silencioso en errores != 200 oculta problemas
- **Solución V3**: Log de warnings para errores no-404

### 12. Sin soporte para archivos grandes
- Archivos muy grandes (>100KB) generan cientos de chunks
- No hay límite ni advertencia
- **Solución V3**: Límite configurable con advertencia

### 13. EMBED_TIMEOUT de 30s puede ser insuficiente
- Para chunks largos en CPU, 30s puede no ser suficiente
- **Solución V3**: Timeout adaptativo basado en longitud del chunk
