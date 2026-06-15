El informe de auditoría está completo. El análisis exhaustivo detectó **21 issues** distribuidos en tres niveles de severidad. Aquí el resumen ejecutivo de los hallazgos más críticos:

***

### 🔴 Bloqueantes (el sistema no arranca tal como está)

Hay **4 bugs de sintaxis Python** en el router que impiden cualquier inicio:
- `logging.basicConfig()` sin paréntesis de cierre → `SyntaxError` fatal
- `_INCOMPATIBLES`, `_TIMEOUT_FALLBACK` y `_AGENT_TO_NIVEL` definidos **dentro** del dict `RUTAS` en lugar de después de él
- `_metricas` y `_estado` sin llave `}` de cierre
- El Autoboot referencia `orchestrator_router_V6.py` pero el archivo se llama `V8.py` — el PASO 10 falla

### 🔴 JSON malformados (funcionalidades core rotas)

Los tres heredocs que inyectan configuración en OpenClaw tienen el mismo problema: **les falta la llave raíz `{`** de apertura y cierre. Consecuencia directa: OpenClaw arranca sin modelos del router, sin agentes, y sin RAG. Es un detalle de un solo carácter que invalida todo el PASO 9.

### 🟠 RAG silenciosamente desactivado

Incluso con el JSON corregido, el RAG tiene un problema de fondo: la función `_rag_inject` hace queries a ChromaDB usando el **nombre** de la colección (`obsidian_vault`) en la URL, pero la API REST de ChromaDB requiere el **UUID interno**. El resultado es un `404` silencioso en cada request, y `_rag_disponible` además es una variable estática que no se actualiza si ChromaDB arranca después del router.

### 🟠 Seguridad y operaciones

El `GATEWAY_TOKEN` de OpenClaw está hardcodeado en texto plano en el script — reemplazable con una sola línea usando `openssl rand`.

El informe incluye el **código exacto de corrección** para cada issue y un checklist ordenado por fase para aplicar los fixes de forma sistemática.


---


# Auditoría técnica V14 — OMEN AI Cluster
### Revisión de `Autoboot_Cluster_V14.sh` + `orchestrator_router_V8.py`

***

## Resumen ejecutivo

El análisis de ambos archivos revela **7 bugs críticos** (que impiden el arranque o la funcionalidad core), **9 issues importantes** (degradación silenciosa de funcionalidades clave como RAG) y **5 oportunidades de optimización**. La arquitectura diseñada es correcta y bien pensada; los problemas son de implementación: errores de sintaxis Python, JSON malformados en los heredocs de Bash, y una discrepancia en el nombre de archivo del router. Una vez corregidos, el sistema funcionará exactamente como se concibió.

***

## 1. Bugs críticos — impiden el arranque o rompen funcionalidad core

### [C1] `logging.basicConfig()` sin cierre de paréntesis — SyntaxError fatal

**Archivo**: `orchestrator_router_V8.py`
**Impacto**: El router **no arranca**. Python lanza `SyntaxError` al importar el módulo.

El bloque de configuración de logging no tiene el paréntesis de cierre `)`:

```python
# ❌ INCORRECTO (como está ahora):
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
# ← falta el paréntesis de cierre aquí

log = logging.getLogger("router-v6")

# ✅ CORRECTO:
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler()],
)

log = logging.getLogger("router-v6")
```

***

### [C2] `_INCOMPATIBLES`, `_TIMEOUT_FALLBACK` y `_AGENT_TO_NIVEL` dentro del dict `RUTAS` — SyntaxError

**Archivo**: `orchestrator_router_V8.py`
**Impacto**: `RUTAS` no se cierra correctamente. Python interpreta los tres dicts como pares clave-valor anidados dentro de `RUTAS`, generando un `SyntaxError` o un dict con estructura completamente incorrecta.

```python
# ❌ INCORRECTO: _INCOMPATIBLES está DENTRO del literal de RUTAS
RUTAS: dict[str, dict] = {
    "MASIVO": { ... },
    # ← aquí falta cerrar RUTAS con } antes de definir _INCOMPATIBLES
    _INCOMPATIBLES: dict[str, list[str]] = {   # ← ERROR: dentro de RUTAS
        "CHAT": ["sglang-server"],
        ...
    }
}

# ✅ CORRECTO: cerrar RUTAS primero, luego definir las constantes:
RUTAS: dict[str, dict] = {
    "CHAT": { ... },
    ...
    "MASIVO": { ... },
}   # ← cierre de RUTAS

_INCOMPATIBLES: dict[str, list[str]] = {
    "CHAT": ["sglang-server"],
    ...
}

_TIMEOUT_FALLBACK: dict[str, str] = {
    "MASIVO": "PROFUNDO",
    ...
}

_AGENT_TO_NIVEL: dict[str, str] = {
    "coder": "INSTANTANEO",
    ...
}
```

***

### [C3] Clave duplicada en `ALIAS_A_NIVEL`

**Archivo**: `orchestrator_router_V8.py`
**Impacto**: Python acepta el dict sin error pero usa silenciosamente el último valor, haciendo que el alias sea impredecible.

```python
# ❌ INCORRECTO (clave repetida):
ALIAS_A_NIVEL: dict[str, Optional[str]] = {
    ...
    "phi4-reasoning:14b-q4_k_m": "PRECISO_OPT",
    "phi4-reasoning:14b-q4_k_m": "PRECISO_OPT",  # ← DUPLICADO
    ...
}

# ✅ CORRECTO (una sola entrada, con ambas variantes de casing):
    "phi4-reasoning:14b-q4_k_m": "PRECISO_OPT",
    "phi4-reasoning:14b-q4_K_M": "PRECISO_OPT",  # mayúsculas originales
```

***

### [C4] Dicts `_metricas` y `_estado` sin cierre de llave

**Archivo**: `orchestrator_router_V8.py`
**Impacto**: `SyntaxError` al parsear el módulo — el router no arranca.

```python
# ❌ INCORRECTO:
_metricas = {
    "requests_por_nivel": Counter(),
    "errores_por_nivel": Counter(),
    "fallbacks": Counter(),
    "latencia_total_ms": Counter(),
    "clasificador_capas": Counter(),
    "rag_inyecciones": 0,
    "cambios_vram": 0,
# ← falta }

# ✅ CORRECTO:
_metricas = {
    "requests_por_nivel": Counter(),
    "errores_por_nivel": Counter(),
    "fallbacks": Counter(),
    "latencia_total_ms": Counter(),
    "clasificador_capas": Counter(),
    "rag_inyecciones": 0,
    "cambios_vram": 0,
}

_estado = {
    "ruta_activa": None,
    "tabbyapi_modelo": None,
    "tabbyapi_cargando": False,
}
```

***

### [C5] `openclaw.json` inyectado sin llave `{` raíz — JSON inválido

**Archivo**: `Autoboot_Cluster_V14.sh`
**Impacto**: OpenClaw carga JSON malformado y arranca con configuración por defecto (sin agentes, sin modelos del router, sin RAG). Todo el PASO 9 queda sin efecto.

El heredoc que inyecta `openclaw.json` empieza directamente en `"gateway":` sin la llave de apertura `{`, y tampoco tiene la llave de cierre `}` al final:

```bash
# ❌ INCORRECTO:
docker exec openclaw-server bash -c 'cat > /data/.openclaw/openclaw.json' << 'OPENCLAW_V14'
"gateway": {
    "bind": "lan",
...
OPENCLAW_V14

# ✅ CORRECTO:
docker exec openclaw-server bash -c 'cat > /data/.openclaw/openclaw.json' << 'OPENCLAW_V14'
{
  "gateway": {
    "bind": "lan",
    ...
  },
  "models": { ... },
  "agents": { ... },
  "plugins": { ... }
}
OPENCLAW_V14
```

***

### [C6] `mcp.json` inyectado sin llave `{` raíz — JSON inválido

**Archivo**: `Autoboot_Cluster_V14.sh`
**Impacto**: El MCP server de ChromaDB no se registra en OpenClaw. La herramienta `search_knowledge_base` no existe para los agentes. **El RAG completo queda no funcional** desde OpenClaw.

```bash
# ❌ INCORRECTO:
docker exec openclaw-server bash -c 'cat > /data/.openclaw/mcp.json' << 'MCP_V14'
"mcpServers": {
    "knowledge-base": {
...
MCP_V14

# ✅ CORRECTO:
docker exec openclaw-server bash -c 'cat > /data/.openclaw/mcp.json' << 'MCP_V14'
{
  "mcpServers": {
    "knowledge-base": {
      "command": "npx",
      "args": ["-y", "@clawrag/mcp-server"],
      "env": {
        "CHROMA_URL": "http://host.docker.internal:8001",
        "COLLECTION_NAME": "obsidian_vault",
        "EMBED_MODEL": "nomic-embed-text",
        "OLLAMA_URL": "http://host.docker.internal:11435",
        "TOP_K": "6",
        "SIMILARITY_THRESHOLD": "0.70"
      }
    }
  }
}
MCP_V14
```

***

### [C7] Objetos de agentes en `openclaw.json` sin llaves de objeto `{` y `}`

**Archivo**: `Autoboot_Cluster_V14.sh`
**Impacto**: JSON inválido — los agentes `@coder`, `@analyst`, `@reasoner` y `@researcher` no se registran. OpenClaw no reconoce los agentes especializados.

En el array `"list"`, cada agente debe ser un objeto JSON envuelto en `{ }`. En el heredoc actual, las propiedades del agente aparecen directamente sin envoltura:

```json
// ❌ INCORRECTO (en el heredoc):
"list": [
  "id": "coder",
  "name": "🖥️ Agente Coder",
  ...

// ✅ CORRECTO:
"list": [
  {
    "id": "coder",
    "name": "🖥️ Agente Coder",
    "model": {
      "primary": "local_router/instantaneo",
      "fallbacks": ["local_router/profundo"]
    }
  },
  {
    "id": "analyst",
    "name": "📊 Agente Analyst",
    "model": {
      "primary": "local_router/masivo",
      "fallbacks": ["local_router/profundo"]
    }
  },
  {
    "id": "reasoner",
    "name": "🧠 Agente Reasoner",
    "model": {
      "primary": "local_router/phi-mayor-precision",
      "fallbacks": ["local_router/profundo"]
    }
  },
  {
    "id": "researcher",
    "name": "🔍 Agente Researcher",
    "model": {
      "primary": "local_router/agil",
      "fallbacks": ["local_router/profundo"]
    },
    "systemPromptSuffix": "Eres un agente especializado en investigación. SIEMPRE usa search_knowledge_base Y la búsqueda web. Cita todas las fuentes."
  }
]
```

***

## 2. Issues importantes — degradación silenciosa de funcionalidades

### [I1 + I2] ChromaDB RAG: URL de query usa nombre en lugar de UUID

**Archivo**: `orchestrator_router_V8.py`
**Impacto**: El endpoint `/api/v1/collections/{nombre}/query` **requiere el UUID** de la colección, no su nombre. En ChromaDB ≥ 0.4, las queries por nombre pueden retornar 404 silencioso, dejando `_rag_inject` sin efecto.

```python
# ❌ INCORRECTO: usa el nombre directamente
r_chroma = await c.post(
    f"{CHROMA_URL}/api/v1/collections/{CHROMA_COLLECTION}/query",
    ...
)

# ✅ CORRECTO: resolver UUID en startup y cachear
# En _startup(), añadir:
async with httpx.AsyncClient(timeout=6.0) as c:
    r = await c.get(f"{CHROMA_URL}/api/v1/collections/{CHROMA_COLLECTION}")
    if r.status_code == 200:
        _chroma_collection_id = r.json().get("id", CHROMA_COLLECTION)
        log.info(f"[RAG] Collection UUID: {_chroma_collection_id}")

# En _rag_inject, usar _chroma_collection_id:
r_chroma = await c.post(
    f"{CHROMA_URL}/api/v1/collections/{_chroma_collection_id}/query",
    ...
)
```

***

### [I3] `_rag_disponible` no se actualiza después del startup

**Archivo**: `orchestrator_router_V8.py`
**Impacto**: Si ChromaDB arranca después del router (lo cual es común en el primer boot), `_rag_disponible` queda en `False` permanentemente hasta el próximo restart del router.

```python
# Añadir verificación dinámica cada 30 segundos:
async def _background_health():
    global _rag_disponible, _chroma_collection_id
    while True:
        await asyncio.sleep(30)
        try:
            async with httpx.AsyncClient(timeout=4.0) as c:
                r = await c.get(f"{CHROMA_URL}/api/v1/heartbeat")
                _rag_disponible = r.status_code < 400
        except Exception:
            _rag_disponible = False

# En _startup(), lanzar como tarea background:
asyncio.create_task(_background_health())
```

***

### [I4] Campo `modelo_nuevo` en PROFUNDO nunca se usa

**Archivo**: `orchestrator_router_V8.py`
**Impacto**: El campo `"modelo_nuevo": "deepseek-r1:8b-0528-qwen3"` en la ruta PROFUNDO es código muerto que genera confusión en el mantenimiento.

**Recomendación**: Implementar como alias explícito en `ALIAS_A_NIVEL` o eliminar:

```python
# Opción A: alias explícito (recomendado)
ALIAS_A_NIVEL = {
    ...
    "deepseek-r1:8b-0528": "PROFUNDO_NUEVO",  # si se añade nivel experimental
    ...
}

# Opción B: eliminar el campo hasta que se implemente la lógica de selección
"PROFUNDO": {
    "modelo": "deepseek-r1:14b",
    # modelo_nuevo eliminado
    ...
}
```

***

### [I5] `PRECISO_OPT` nunca alcanzable por clasificador automático

**Archivo**: `orchestrator_router_V8.py`
**Impacto**: `phi4-reasoning:14b-q4_K_M` (nivel PRECISO_OPT) solo puede usarse con alias manual. El clasificador automático (embeddings + Phi4) nunca lo selecciona porque ni el prompt de embeddings ni el de Phi4 lo mencionan. El modelo queda instalado pero infrautilizado.

```python
# Implementar selección automática entre PRECISO y PRECISO_OPT según longitud del prompt:
# Si el clasificador devuelve PRECISO:
#   - prompt < 300 chars → PRECISO_OPT (respuesta más rápida, suficiente precisión)
#   - prompt >= 300 chars → PRECISO (plus, mayor razonamiento para problemas complejos)

async def _clasificar(prompt: str, agent_id: str = "") -> tuple[str, str]:
    ...
    nivel, fuente = await _clasificar_embeddings_o_phi4(prompt, agent_id)
    
    # Auto-selección PRECISO vs PRECISO_OPT basada en longitud del prompt
    if nivel == "PRECISO" and len(prompt) < 300:
        return "PRECISO_OPT", fuente + "+opt"
    return nivel, fuente
```

***

### [I6] `_rag_inject` muta el dict `body` sin copia defensiva

**Archivo**: `orchestrator_router_V8.py`
**Impacto**: En el flujo de fallback (`_TIMEOUT_FALLBACK`), el mismo dict `body` ya enriquecido con RAG se pasa al nivel inferior. Esto es correcto funcionalmente pero puede duplicar el bloque RAG si el fallback también llama a `_rag_inject`.

```python
# Añadir copia defensiva al inicio de _rag_inject:
async def _rag_inject(body: dict, prompt: str, nivel: str) -> dict:
    if nivel not in RAG_NIVELES or not _rag_disponible:
        return body
    
    # Copia defensiva para evitar side effects en fallbacks
    body = {**body, "messages": list(body.get("messages", []))}
    ...
```

***

### [I7] `set -uo pipefail` sin `-e` — errores no detienen el script

**Archivo**: `Autoboot_Cluster_V14.sh`
**Impacto**: Si `sudo systemctl start ollama` falla (GPU no disponible, servicio bloqueado), el script continúa levantando todos los demás servicios que dependen de Ollama GPU, generando un estado inconsistente silencioso.

```bash
# ❌ INCORRECTO:
set -uo pipefail

# ✅ CORRECTO:
set -euo pipefail

# Para los comandos que pueden fallar intencionalmente (cleanup), usar || true:
docker stop openclaw-server 2>/dev/null || true
```

***

### [I8] `ROUTER_SCRIPT` apunta a `orchestrator_router_V6.py` — nombre incorrecto

**Archivo**: `Autoboot_Cluster_V14.sh`, línea `ROUTER_SCRIPT=...`
**Impacto**: **El PASO 10 falla** — el script intenta ejecutar `orchestrator_router_V6.py` pero el archivo se llama `orchestrator_router_V8.py`. El router no arranca.

```bash
# ❌ INCORRECTO:
ROUTER_SCRIPT="$SCRIPT_DIR/orchestrator_router_V6.py"

# ✅ CORRECTO:
ROUTER_SCRIPT="$SCRIPT_DIR/orchestrator_router_V8.py"

# Alternativa robusta (detecta automáticamente el más reciente):
ROUTER_SCRIPT=$(ls -t "$SCRIPT_DIR"/orchestrator_router_V*.py 2>/dev/null | head -1)
[ -z "$ROUTER_SCRIPT" ] && { error "No se encontró orchestrator_router_V*.py"; exit 1; }
```

***

### [I9] `OPENCLAW_GATEWAY_TOKEN` hardcoded en texto plano

**Archivo**: `Autoboot_Cluster_V14.sh`
**Impacto**: Riesgo de seguridad si el script se versiona en git o se comparte. El token `7c9b84a2f1e63d5c...` es estático y conocido.

```bash
# ❌ INCORRECTO:
-e OPENCLAW_GATEWAY_TOKEN="7c9b84a2f1e63d5c8a4b29f7e0d1c4a5b6e7f8d9c0a1b2c3d4e5f6a7b8c9d0e1"

# ✅ CORRECTO: leer de env var o generar dinámicamente y persistir
OPENCLAW_TOKEN_FILE="$SCRIPT_DIR/.openclaw_token"
if [ ! -f "$OPENCLAW_TOKEN_FILE" ]; then
    openssl rand -hex 32 > "$OPENCLAW_TOKEN_FILE"
    chmod 600 "$OPENCLAW_TOKEN_FILE"
    ok "Token generado y guardado en $OPENCLAW_TOKEN_FILE"
fi
OPENCLAW_GATEWAY_TOKEN=$(cat "$OPENCLAW_TOKEN_FILE")

# Añadir al .gitignore:
echo ".openclaw_token" >> "$SCRIPT_DIR/.gitignore" 2>/dev/null || true
```

***

## 3. Optimizaciones recomendadas

### [O1] Race condition en `_conmutar_vram` bajo carga concurrente

**Archivo**: `orchestrator_router_V8.py`
**Descripción**: Si dos requests llegan simultáneamente con necesidad de conmutación de VRAM, ambas pueden intentar parar/arrancar contenedores en paralelo, causando estados inconsistentes.

```python
# Añadir lock global para serializar operaciones VRAM:
_vram_lock = asyncio.Lock()

async def _conmutar_vram(nivel: str) -> str:
    async with _vram_lock:
        # Optimización: si el nivel solicitado ya es el activo, retornar inmediatamente
        if _estado["ruta_activa"] == nivel and not RUTAS[nivel].get("tabbyapi_swap"):
            return RUTAS[nivel]["url"]
        
        # ... resto de la lógica existente ...
```

***

### [O2] Inconsistencia `RAG_TOP_K` entre router (4) y `mcp.json` (8)

**Descripción**: El router inyecta 4 fragmentos RAG por request, pero el MCP server configurado con `TOP_K=8` inyectaría 8. Esto crea experiencias inconsistentes según la vía de acceso al RAG.

**Recomendación**: Unificar a `TOP_K=6` en ambos lugares. Es un buen equilibrio: suficiente contexto sin saturar el prompt de los modelos con 16K de contexto.

```python
# En orchestrator_router_V8.py:
RAG_TOP_K = 6

# En mcp.json (via Autoboot):
"TOP_K": "6"
```

***

### [O3] Caché TTL en `/health` para evitar latencia en consultas periódicas de OpenClaw

**Archivo**: `orchestrator_router_V8.py`
**Descripción**: El endpoint `/health` hace health checks síncronos a 9 backends cada vez que se consulta. OpenClaw lo llama periódicamente y puede percibir latencia.

```python
_health_cache: dict = {"data": None, "ts": 0.0}
_HEALTH_TTL = 15.0  # segundos

@app.get("/health")
async def health():
    now = time.monotonic()
    if _health_cache["data"] and (now - _health_cache["ts"]) < _HEALTH_TTL:
        return _health_cache["data"]
    
    # ... lógica de health checks existente ...
    result = { ... }
    _health_cache.update({"data": result, "ts": now})
    return result
```

***

### [O4] Logging del router escribe a archivo pero no rota — crecimiento ilimitado

**Archivo**: `Autoboot_Cluster_V14.sh`
**Descripción**: El router se lanza con `>> router_V14.log` sin rotación. En uso intensivo, el log puede crecer a varios GB.

```bash
# Solución A: usar logrotate
cat > /etc/logrotate.d/omen-router << 'LR'
/home/fcela-ga/sgoinfre/ai_core/router_V14.log {
    daily
    rotate 7
    compress
    missingok
    notifempty
}
LR

# Solución B: lanzar router con rotación integrada en Python
# En orchestrator_router_V8.py, reemplazar StreamHandler por RotatingFileHandler:
from logging.handlers import RotatingFileHandler
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        RotatingFileHandler("router_V14.log", maxBytes=50*1024*1024, backupCount=3)
    ],
)
```

***

### [O5] Verificación de JSON en tiempo de construcción del Autoboot

**Archivo**: `Autoboot_Cluster_V14.sh`
**Descripción**: Los heredocs que generan `openclaw.json` y `mcp.json` no se validan antes de inyectarlos. Un error de sintaxis queda silencioso hasta que OpenClaw falla.

```bash
# Añadir validación tras cada inyección:
# Tras inyectar openclaw.json:
docker exec openclaw-server python3 -c \
    "import json; json.load(open('/data/.openclaw/openclaw.json')); print('✔ openclaw.json válido')" \
    || { error "openclaw.json inválido — revisa la sintaxis JSON"; exit 1; }

# Tras inyectar mcp.json:
docker exec openclaw-server python3 -c \
    "import json; json.load(open('/data/.openclaw/mcp.json')); print('✔ mcp.json válido')" \
    || { error "mcp.json inválido — revisa la sintaxis JSON"; exit 1; }
```

***

## 4. Tabla resumen de todos los issues

| ID | Archivo | Severidad | Área | Estado | Descripción resumida |
|----|---------|-----------|------|--------|---------------------|
| C1 | router_V8.py | 🔴 Crítico | Python | Bloquea arranque | `logging.basicConfig()` sin `)` de cierre |
| C2 | router_V8.py | 🔴 Crítico | Python | Bloquea arranque | `_INCOMPATIBLES` etc. dentro de `RUTAS` |
| C3 | router_V8.py | 🔴 Crítico | Python | Bug silencioso | Clave duplicada en `ALIAS_A_NIVEL` |
| C4 | router_V8.py | 🔴 Crítico | Python | Bloquea arranque | `_metricas`/`_estado` sin cierre `}` |
| C5 | Autoboot.sh | 🔴 Crítico | Bash/JSON | OpenClaw sin config | `openclaw.json` sin `{` ni `}` raíz |
| C6 | Autoboot.sh | 🔴 Crítico | Bash/JSON | RAG no funcional | `mcp.json` sin `{` ni `}` raíz |
| C7 | Autoboot.sh | 🔴 Crítico | Bash/JSON | Agentes no registrados | Objetos agentes sin `{` `}` en JSON |
| I1+I2 | router_V8.py | 🟠 Importante | RAG | RAG falla silencioso | ChromaDB query necesita UUID, no nombre |
| I3 | router_V8.py | 🟠 Importante | RAG | RAG siempre OFF | `_rag_disponible` no se actualiza dinámicamente |
| I4 | router_V8.py | 🟠 Importante | Mantenimiento | Código muerto | `modelo_nuevo` en PROFUNDO sin usar |
| I5 | router_V8.py | 🟠 Importante | Routing | PRECISO_OPT inactivo | Clasificador nunca elige PRECISO_OPT |
| I6 | router_V8.py | 🟠 Importante | Python | Mutabilidad | `body` mutado sin copia defensiva |
| I7 | Autoboot.sh | 🟠 Importante | Bash | Errores silenciosos | `set -uo` sin `-e` |
| I8 | Autoboot.sh | 🟠 Importante | Bash | Bloquea PASO 10 | Nombre del router incorrecto (V7 vs V8) |
| I9 | Autoboot.sh | 🟠 Importante | Seguridad | Token expuesto | `GATEWAY_TOKEN` hardcoded en script |
| O1 | router_V8.py | 🟡 Optimización | Concurrencia | Race condition | Sin lock en `_conmutar_vram` |
| O2 | Ambos | 🟡 Optimización | RAG | Inconsistencia | `RAG_TOP_K` 4 vs 8 en mcp.json |
| O3 | router_V8.py | 🟡 Optimización | Performance | Latencia /health | Sin caché TTL en endpoint /health |
| O4 | Autoboot.sh | 🟡 Optimización | Operaciones | Log ilimitado | Log sin rotación |
| O5 | Autoboot.sh | 🟡 Optimización | Calidad | Fallo silencioso | JSON no validado tras inyección |

***

## 5. Checklist de corrección por orden de prioridad

Aplicar en este orden para restaurar el funcionamiento completo:

**Fase 1 — Correcciones que bloquean el arranque (hacer primero):**
- [ ] [C1] Cerrar paréntesis en `logging.basicConfig()`
- [ ] [C2] Mover `_INCOMPATIBLES`, `_TIMEOUT_FALLBACK`, `_AGENT_TO_NIVEL` fuera de `RUTAS`
- [ ] [C4] Cerrar llaves de `_metricas` y `_estado`
- [ ] [I8] Cambiar `orchestrator_router_V6.py` → `orchestrator_router_V8.py` en Autoboot

**Fase 2 — Correcciones de JSON que rompen funcionalidades core:**
- [ ] [C5] Añadir `{` y `}` al heredoc de `openclaw.json`
- [ ] [C6] Añadir `{` y `}` al heredoc de `mcp.json`
- [ ] [C7] Envolver cada agente en `{ }` en el array `"list"`

**Fase 3 — Correcciones de degradación silenciosa:**
- [ ] [C3] Eliminar clave duplicada en `ALIAS_A_NIVEL`
- [ ] [I1+I2] Resolver UUID de ChromaDB en startup
- [ ] [I3] Añadir background task de health check para `_rag_disponible`
- [ ] [I7] Cambiar `set -uo pipefail` → `set -euo pipefail`
- [ ] [I9] Leer `GATEWAY_TOKEN` de archivo persistente generado con `openssl rand`

**Fase 4 — Optimizaciones de robustez:**
- [ ] [O1] Añadir `asyncio.Lock()` para serializar `_conmutar_vram`
- [ ] [O2] Unificar `RAG_TOP_K=6` en router y mcp.json
- [ ] [O3] Añadir caché TTL en `/health`
- [ ] [O4] Añadir `RotatingFileHandler` al router
- [ ] [O5] Añadir validación JSON tras inyección de configs
- [ ] [I5] Implementar selección automática PRECISO vs PRECISO_OPT por longitud de prompt

***

## 6. Verificación rápida del estado tras correcciones

Una vez aplicados todos los fixes, usar este script para verificar que todo arranca correctamente:

```bash
# 1. Verificar sintaxis Python antes de lanzar:
python3 -m py_compile orchestrator_router_V8.py && echo "✔ Sintaxis Python OK"

# 2. Arrancar el clúster:
./Autoboot_Cluster_V14.sh

# 3. Verificar estado completo:
./Autoboot_Cluster_V14.sh --status

# 4. Verificar JSON de OpenClaw:
docker exec openclaw-server python3 -c \
  "import json; cfg=json.load(open('/data/.openclaw/openclaw.json')); \
   print(f'✔ openclaw.json: {len(cfg[\"agents\"][\"list\"])} agentes, {len(cfg[\"models\"][\"providers\"][\"local_router\"][\"models\"])} modelos')"

# 5. Verificar RAG funcional:
curl -s "http://localhost:8001/api/v1/collections" | python3 -c \
  "import json,sys; cols=json.load(sys.stdin); \
   print(f'✔ ChromaDB: {len(cols)} colecciones: {[c[\"name\"] for c in cols]}')"

# 6. Test completo del router:
curl -s http://localhost:8000/health | python3 -m json.tool
```
