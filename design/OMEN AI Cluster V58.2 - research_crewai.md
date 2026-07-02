# Frameworks Multi-Agente para un Debate/Crítica Loop Local: CrewAI y Alternativas

**Fecha:** julio 2026  
**Caso de uso:** loop debate/crítica sobre una base de conocimiento Obsidian, corriendo completamente local con modelos 7–8B (Llama 3.1 8B, Qwen2.5-Coder 7B, phi4-mini) servidos via proxy LiteLLM en `http://localhost:4000`, con ChromaDB + `nomic-embed-text` para RAG.

---

## 1. Tabla Comparativa de Frameworks

| Criterio | **CrewAI** | **LangGraph** | **AutoGen / AG2** | **smolagents** | **Letta** |
|---|---|---|---|---|---|
| **Versión actual (jul 2026)** | 1.14.7 ([changelog](https://docs.crewai.com/en/changelog)) | 1.1.10 ([futureagi](https://futureagi.com/blog/oss-agent-frameworks-2026/)) | AG2 0.11.2 (fork comunitario) / AutoGen 0.7.5 en **modo mantenimiento** ([agenticwire.news](https://www.agenticwire.news/article/ai-agent-framework-status-2026)) | 1.24.0 ([dev.to](https://dev.to/ultraduneai/eval-004-ai-agent-frameworks-langgraph-vs-crewai-vs-autogen-vs-smolagents-vs-openai-agents-sdk-190l)) | Activo, enfocado en memoria persistente |
| **Python** | ≥3.10, <3.14 ([checklist.day](https://checklist.day/registry/crewai)) | ≥3.9 | ≥3.9 | ≥3.9 | ≥3.10 |
| **Proxy OpenAI-compatible** | ✅ Nativo con `openai/` prefix + `base_url` ([docs.crewai.com](https://docs.crewai.com/v1.14.1/en/learn/llm-connections)) | ✅ Via `ChatOpenAI(base_url=...)` | ✅ Via OpenAI SDK | ✅ Via LiteLLM integration | ✅ |
| **Tool-calling con 7–8B** | ⚠️ Inconsistente con qwen2.5-7B; mejor con qwen3:8b ([community.crewai.com](https://community.crewai.com/t/local-llms-tools-calling/5004)) | ⚠️ Depende del modelo; qwen2.5 recomendado ([YouTube LangGraph local](https://www.youtube.com/watch?v=4oC1ZKa9-Hs)) | ⚠️ Similar a LangGraph | ✅ **Mejor** — usa generación de código Python en vez de JSON tool-calls ([github.com/huggingface/smolagents](https://github.com/huggingface/smolagents)) | ⚠️ Requiere tool-calling fiable |
| **YAML role/task definition** | ✅ `agents.yaml` + `tasks.yaml` nativos ([devshelfhub.com](https://www.devshelfhub.com/cheatsheets/crewai/)) | ❌ Solo código Python | ❌ Solo código Python | ❌ Solo código Python | ❌ Solo código Python |
| **Loop iterativo (debate/crítica)** | ✅ Sequential + context chaining; Hierarchical con manager-agent | ✅ Ciclos explícitos con grafo | ✅ ConversableAgent loop | ⚠️ Manual en Python | ⚠️ Stateful pero sin loop multi-agente integrado |
| **RAG / ChromaDB nativo** | ✅ **Nativo**: ChromaDB como backend por defecto, embedder configurable vía Ollama ([docs.crewai.com/knowledge](https://docs.crewai.com/v1.14.7/en/concepts/knowledge)) | ✅ Via LangChain integrations | ⚠️ Manual | ⚠️ Manual | ⚠️ RAG vía tools externas |
| **Mantenimiento (jul 2026)** | ✅ Activo (~51k ⭐, releases semanales) | ✅ Activo (~31k ⭐) | ⚠️ AutoGen en **modo mantenimiento** desde oct 2025; AG2 fork comunitario activo ([agentmarketcap.ai](https://agentmarketcap.ai/blog/2026/04/13/microsoft-autogen-maintenance-mode-agent-framework-sunset-2026)) | ✅ Activo (~27k ⭐) | ✅ Activo (enfocado en memoria) |
| **Huella de recursos** | Media (depende de deps) | Media-alta | Media | **Baja** (~1000 líneas de código) | Alta (requiere Postgres) |
| **Docker** | ✅ Bien documentado ([github.com/vin67/crewai_docker](https://github.com/vin67/crewai_docker)) | ✅ Genérico Python | ✅ Genérico Python | ✅ Genérico Python | ✅ Imagen oficial |
| **Curva de aprendizaje** | Baja | Alta | Media | Muy baja | Media |

---

## 2. Respuestas Detalladas

### 2.1 ¿Es CrewAI la mejor opción?

**Respuesta corta: Para este caso específico (dos agentes, debate/crítica, RAG Obsidian, YAML, Docker), CrewAI es la opción más conveniente *si los modelos cooperan*, pero tiene riesgos reales con tool-calling en 7–8B.**

**Ventajas de CrewAI sobre las alternativas:**
- YAML nativo para `agents.yaml`/`tasks.yaml`: ningún otro framework lo tiene
- ChromaDB + `nomic-embed-text` ya integrados como backend knowledge
- Loop critique-refine expresable con `Process.sequential` + `context=[task_anterior]`
- Proxy LiteLLM apuntable directamente con `model="openai/<alias>"` + `base_url`

**Riesgos reales:**
- Tool-calling con modelos 7B es inconsistente; se documenta en issues que qwen2.5-7B falla frecuentemente ([reddit.com/r/LocalLLaMA](https://www.reddit.com/r/LocalLLaMA/comments/18v527r/crewai_agent_framework_with_local_models/))
- El paquete `litellm` fue cuarentenado en PyPI en 2026; CrewAI publicó una guía para **no usar litellm** y usar el prefijo `openai/` nativo ([docs.crewai.com/litellm-removal-guide](https://docs.crewai.com/v1.14.7/en/learn/litellm-removal-guide))
- Process.hierarchical requiere un manager LLM; si el manager es un modelo 7B, la delegación suele fallar

**Alternativas honestas:**

| Framework | ¿Cuándo es mejor que CrewAI para este caso? |
|---|---|
| **LangGraph** | Si necesitas control explícito del loop, retries, checkpoints de estado. Más verboso, pero loops de critique-refine son grafos naturales. Requiere más código. |
| **smolagents** | **Para el loop debate simple sin herramientas externas**: produce código Python en vez de JSON tool-calls → 30% menos pasos, más fiable con modelos pequeños. Pero no tiene YAML ni RAG nativo. |
| **AG2** | Para conversación multi-agente sin necesidad de YAML; ConversableAgent es simple. Pero está en fork comunitario sin roadmap claro. |
| **Loop Python puro** | Si el caso es realmente simple (leer Obsidian → agente A → agente B critica → loop N veces), un script de 100 líneas con `openai` SDK es más fiable que cualquier framework con modelos 7B. |

---

### 2.2 Detalles CrewAI

#### Versión y Python
- **Versión estable actual (julio 2026):** `1.14.6` / `1.14.7a1` pre-release ([agentupdate.ai](https://www.agentupdate.ai/releases/crewai/), [piwheels.org](https://www.piwheels.org/project/crewai/))
- **Python requerido:** `>=3.10,<3.14` (recomendado 3.11 o 3.12)
- **Instalación:** `pip install "crewai[openai]"` (sin LiteLLM) o `pip install "crewai[tools]"`

#### Apuntar CrewAI al proxy LiteLLM (`http://localhost:4000`)

El proxy LiteLLM expone una API OpenAI-compatible. Con CrewAI ≥1.0 **NO hace falta instalar `litellm`**; basta con el prefijo `openai/` y `base_url`:

```python
# crew.py
from crewai import LLM, Agent, Crew, Task, Process

# Alias configurados en LiteLLM: "instantaneo", "codigo", "agil", "orquestador"
llm_lector = LLM(
    model="openai/instantaneo",       # Llama 3.1 8B
    base_url="http://localhost:4000",
    api_key="sk-MASTER_KEY_AQUI",     # master key de LiteLLM
    temperature=0.3,
)

llm_critico = LLM(
    model="openai/agil",              # phi4-mini
    base_url="http://localhost:4000",
    api_key="sk-MASTER_KEY_AQUI",
    temperature=0.5,
)
```

> **Nota importante (2026):** `litellm` fue cuarentenado en PyPI. CrewAI recomienda **NO usar `crewai[litellm]`** y en su lugar usar `model="openai/<alias>"` + `base_url` apuntando al servidor que sea (Ollama, LiteLLM, vLLM). Esto funciona perfectamente para un proxy LiteLLM. ([Guía oficial](https://docs.crewai.com/v1.14.7/en/learn/litellm-removal-guide))

#### Estructura `agents.yaml` y `tasks.yaml`

```yaml
# config/agents.yaml
lector_obsidian:
  role: >
    Lector y Sintetizador de Notas
  goal: >
    Leer las notas de Obsidian sobre {tema} y producir un resumen estructurado
    con los puntos clave, basándote SOLO en la información recuperada.
  backstory: >
    Eres un analista experto en síntesis de información de bases de conocimiento
    personal. No inventas información: solo reportas lo que encuentras.
  llm: openai/instantaneo     # alias LiteLLM → Llama 3.1 8B
  verbose: true
  allow_delegation: false
  max_iter: 3

critico_debatidor:
  role: >
    Crítico y Debatidor
  goal: >
    Revisar críticamente el resumen de {tema} producido por el Lector,
    señalar lagunas, contradicciones o conclusiones débiles, y proponer
    una versión refinada o una perspectiva alternativa.
  backstory: >
    Eres un crítico constructivo que busca mejorar la calidad del análisis.
    Tu objetivo es desafiar afirmaciones sin suficiente evidencia y sugerir
    puntos de vista alternativos o información faltante.
  llm: openai/agil            # alias LiteLLM → phi4-mini
  verbose: true
  allow_delegation: false
  max_iter: 3
```

```yaml
# config/tasks.yaml
tarea_lectura:
  description: >
    Busca en la base de conocimiento Obsidian toda la información relacionada
    con {tema}. Produce un resumen estructurado de máximo 400 palabras con:
    1. Puntos principales encontrados
    2. Fuentes (nombres de archivos)
    3. Lagunas de información detectadas
  expected_output: >
    Un resumen estructurado en markdown con secciones: Puntos Clave,
    Fuentes Consultadas, Lagunas Identificadas.
  agent: lector_obsidian

tarea_critica:
  description: >
    Revisa el siguiente resumen sobre {tema}:
    
    {tarea_lectura}
    
    Identifica: (1) afirmaciones sin suficiente evidencia, (2) perspectivas
    faltantes importantes, (3) posibles contradicciones. Luego propón
    una versión refinada o complementada del análisis.
  expected_output: >
    Un análisis crítico con secciones: Debilidades del Resumen Original,
    Perspectivas Faltantes, Versión Refinada del Análisis.
  agent: critico_debatidor
  context:
    - tarea_lectura    # recibe el output de la tarea anterior
```

#### Sequential vs Hierarchical

| Proceso | Descripción | Cuándo usarlo |
|---|---|---|
| `Process.sequential` | Las tareas se ejecutan en orden, pasando outputs via `context`. Control total y predecible. | **Recomendado para este caso**: debate A→B→refinado |
| `Process.hierarchical` | Un manager LLM asigna tareas dinámicamente a los agentes. Requiere `manager_llm` o `manager_agent`. | Solo si la delegación es dinámica. **Problemático con 7B**: el manager puede fallar al delegar correctamente. |

> **Recomendación:** Usar `Process.sequential` para el loop debate/crítica. Si quieres N iteraciones, llama a `crew.kickoff()` en un loop Python externo o usa CrewAI Flows.

#### Loop Critique-Refine

**Opción A: Sequential con 2 agentes (simple)**

```python
# crew.py
from crewai import Agent, Crew, Task, Process
from crewai.project import CrewBase, agent, crew, task

@CrewBase
class DebateCrew:
    agents_config = 'config/agents.yaml'
    tasks_config = 'config/tasks.yaml'

    @agent
    def lector_obsidian(self) -> Agent:
        return Agent(config=self.agents_config['lector_obsidian'], llm=llm_lector)

    @agent
    def critico_debatidor(self) -> Agent:
        return Agent(config=self.agents_config['critico_debatidor'], llm=llm_critico)

    @task
    def tarea_lectura(self) -> Task:
        return Task(config=self.tasks_config['tarea_lectura'])

    @task
    def tarea_critica(self) -> Task:
        return Task(config=self.tasks_config['tarea_critica'])

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=True,
        )
```

**Opción B: N iteraciones vía loop externo**

```python
# main.py
from debate_crew import DebateCrew

MAX_RONDAS = 3
tema = "procesamiento del lenguaje natural"
resultado_anterior = ""

for ronda in range(MAX_RONDAS):
    resultado = DebateCrew().crew().kickoff(inputs={
        "tema": tema,
        "contexto_previo": resultado_anterior,
    })
    resultado_anterior = resultado.raw
    print(f"\n=== RONDA {ronda+1} completada ===\n")
```

#### RAG / Knowledge Sources con ChromaDB y `nomic-embed-text`

CrewAI usa ChromaDB como backend de knowledge **por defecto**. Para apuntar el embedder a Ollama (`nomic-embed-text`):

```python
from crewai import Crew, Process
from crewai.knowledge.source.text_file_knowledge_source import TextFileKnowledgeSource
import glob, os

# Cargar todos los .md del vault de Obsidian
vault_path = "/vault"  # montado read-only en Docker
md_files = glob.glob(f"{vault_path}/**/*.md", recursive=True)
# Rutas relativas al CREWAI_STORAGE_DIR
os.environ["CREWAI_STORAGE_DIR"] = "/app/storage"

obsidian_source = TextFileKnowledgeSource(
    file_paths=md_files,
    metadata={"source": "obsidian_vault"}
)

crew = Crew(
    agents=[lector, critico],
    tasks=[tarea_lectura, tarea_critica],
    process=Process.sequential,
    knowledge_sources=[obsidian_source],
    embedder={
        "provider": "ollama",
        "config": {
            "model": "nomic-embed-text",
            "host": "http://host.docker.internal:11434"  # Ollama en el host
        }
    },
    verbose=True,
)
```

> **Si ChromaDB ya está pre-indexado externamente**, se puede conectar usando `KnowledgeStorage` con `collection_name` personalizado y `CREWAI_STORAGE_DIR` apuntando al directorio existente. ([community.crewai.com](https://community.crewai.com/t/unable-to-save-the-vector-db-of-crewai-docling-knowledge/5292))

---

### 2.3 Problemas Conocidos con Modelos 7–8B y Workarounds

#### Problemas documentados

| Problema | Causa | Modelos afectados |
|---|---|---|
| Tool-call como texto plano | El modelo describe la acción en vez de emitir JSON estructurado | qwen2.5-7B, llama3-8B ([dev.to](https://dev.to/kuroko1t/what-happens-when-local-llms-fail-at-tool-calling-testing-7-models-with-a-rust-coding-agent-cep)) |
| Loop infinito en tool retry | El modelo repite la misma llamada fallida | qwen2.5:7b frecuentemente |
| Parámetros incorrectos en tools | Confunde nombres de parámetros o tipos | Todos los 7B |
| `None` response | Ollama plain `/api/generate` no soporta function defs; LiteLLM los elimina | xLAM, modelos sin chat template de tools ([community.crewai.com](https://community.crewai.com/t/recommendations-for-running-custom-tools-with-local-ollama-models-having-function-calling-capabilities/5777)) |

#### Workarounds (orden de efectividad)

1. **Usar modelos qwen3:8b en vez de qwen2.5:7B** — La familia qwen3 mejoró significativamente tool-calling. `qwen3:8b` pasa pruebas donde `qwen2.5:7b` falla ([dev.to kuroko1t](https://dev.to/kuroko1t/what-happens-when-local-llms-fail-at-tool-calling-testing-7-models-with-a-rust-coding-agent-cep)).

2. **Reducir herramientas al mínimo o a cero** — Para el loop debate/crítica, los agentes **no necesitan tools externas**: leen del knowledge source automáticamente. Deshabilitar tools elimina el problema de tool-calling.
   ```python
   agent = Agent(
       role="...",
       tools=[],          # sin tools = sin JSON tool-calls
       allow_delegation=False,
   )
   ```

3. **Añadir instrucción explícita anti-retry al backstory/goal:**
   ```
   "NEVER repeat the same tool call more than once. If it fails, change your approach."
   ```

4. **Bajar temperatura** — `temperature=0.1`–`0.3` mejora la adherencia al formato de salida esperado ([community.crewai.com](https://community.crewai.com/t/how-to-embed-knowledge-source-with-ollama2/2184)).

5. **Usar `max_iter`** — Limita las iteraciones del agente y evita loops infinitos:
   ```yaml
   # agents.yaml
   lector_obsidian:
     max_iter: 3
   ```

6. **Usar `ollama_chat/` en vez de `ollama/`** — El prefijo `ollama_chat/` usa el endpoint `/api/chat` que sí incluye function calling; `ollama/` usa `/api/generate` que no lo soporta:
   ```python
   # Si usas LiteLLM proxy, el alias ya define el backend correcto.
   # Si conectas Ollama directamente (sin LiteLLM), usa:
   llm = LLM(model="openai/qwen3:8b", base_url="http://localhost:11434/v1", api_key="ollama")
   ```

---

### 2.4 Deployment Docker

#### Dockerfile para CrewAI con vault Obsidian montado

```dockerfile
# Dockerfile
FROM python:3.11-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Usuario no-root
RUN groupadd --system crew && useradd --system --gid crew --create-home crew

WORKDIR /app

# Dependencias — sin litellm, con soporte OpenAI nativo
COPY --chown=crew:crew requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Código de la aplicación
COPY --chown=crew:crew src/ ./src/
COPY --chown=crew:crew config/ ./config/

# Directorio para storage de ChromaDB (persistente via volumen)
RUN mkdir -p /app/storage && chown crew:crew /app/storage

USER crew

# El vault se monta read-only en /vault
# El storage de ChromaDB se monta en /app/storage
CMD ["python", "src/main.py"]
```

```
# requirements.txt (versiones fijadas)
crewai[openai]==1.14.6
crewai-tools==0.17.0
chromadb==0.5.23
python-dotenv==1.0.1
```

#### `docker-compose.yml` (recomendado para desarrollo)

```yaml
# docker-compose.yml
version: "3.9"

services:
  crew:
    build: .
    environment:
      # Proxy LiteLLM en el host
      LITELLM_BASE_URL: "http://host.docker.internal:4000"
      LITELLM_API_KEY: "sk-MASTER_KEY_AQUI"
      # Ollama en el host (para embeddings nomic-embed-text)
      OLLAMA_HOST: "http://host.docker.internal:11434"
      # Storage de CrewAI (ChromaDB knowledge)
      CREWAI_STORAGE_DIR: "/app/storage"
      # Evitar OPENAI_API_KEY no configurado
      OPENAI_API_KEY: "dummy"  # no se usa, solo evita error de validación
    volumes:
      # Vault Obsidian: read-only
      - /ruta/a/tu/obsidian/vault:/vault:ro
      # Storage ChromaDB: persistente
      - crewai_storage:/app/storage
    extra_hosts:
      - "host.docker.internal:host-gateway"  # Linux

volumes:
  crewai_storage:
```

#### Ejecutar

```bash
# Build y run
docker compose up --build

# O con Docker puro
docker build -t debate-crew .
docker run --rm \
  -v /ruta/vault:/vault:ro \
  -v crewai_data:/app/storage \
  --add-host host.docker.internal:host-gateway \
  -e LITELLM_BASE_URL="http://host.docker.internal:4000" \
  -e LITELLM_API_KEY="sk-MASTER_KEY" \
  debate-crew
```

---

### 2.5 Alternativa más Ligera: Loop Python Puro (para debate simple)

Si el caso de uso es **exactamente** dos agentes (lector + crítico) sin herramientas externas, un script de ~80 líneas es **más fiable** que cualquier framework con modelos 7–8B:

```python
"""
debate_loop.py — Loop debate/crítica sin framework, solo openai SDK
Funciona contra proxy LiteLLM con aliases: instantaneo, agil
"""
import os
from openai import OpenAI
import chromadb
from chromadb.utils import embedding_functions

# --- Config ---
LITELLM_BASE_URL = os.getenv("LITELLM_BASE_URL", "http://localhost:4000")
LITELLM_API_KEY = os.getenv("LITELLM_API_KEY", "sk-key")
VAULT_PATH = os.getenv("VAULT_PATH", "/vault")
MAX_RONDAS = 3

client = OpenAI(base_url=LITELLM_BASE_URL, api_key=LITELLM_API_KEY)

# --- RAG: conectar ChromaDB pre-indexado ---
ollama_ef = embedding_functions.OllamaEmbeddingFunction(
    url="http://localhost:11434/api/embeddings",
    model_name="nomic-embed-text",
)
chroma_client = chromadb.PersistentClient(path="/app/chroma_db")
collection = chroma_client.get_or_create_collection("obsidian_vault", embedding_function=ollama_ef)

def recuperar_contexto(pregunta: str, n_results: int = 5) -> str:
    resultados = collection.query(query_texts=[pregunta], n_results=n_results)
    fragmentos = resultados["documents"][0]
    return "\n\n---\n\n".join(fragmentos)

def llamar_lector(tema: str, contexto_vault: str) -> str:
    resp = client.chat.completions.create(
        model="instantaneo",   # alias LiteLLM → Llama 3.1 8B
        temperature=0.2,
        messages=[
            {"role": "system", "content": (
                "Eres un sintetizador de notas. Responde SOLO con información "
                "del contexto proporcionado. No inventes datos."
            )},
            {"role": "user", "content": (
                f"Tema: {tema}\n\n"
                f"Contexto del vault Obsidian:\n{contexto_vault}\n\n"
                "Produce un resumen estructurado con: Puntos Clave, Fuentes, Lagunas."
            )},
        ],
        max_tokens=800,
    )
    return resp.choices[0].message.content

def llamar_critico(tema: str, resumen_anterior: str) -> str:
    resp = client.chat.completions.create(
        model="agil",          # alias LiteLLM → phi4-mini
        temperature=0.4,
        messages=[
            {"role": "system", "content": (
                "Eres un crítico constructivo. Tu rol es mejorar análisis señalando "
                "afirmaciones sin evidencia, perspectivas faltantes y contradicciones."
            )},
            {"role": "user", "content": (
                f"Tema: {tema}\n\n"
                f"Análisis a revisar:\n{resumen_anterior}\n\n"
                "Identifica debilidades y propón una versión refinada."
            )},
        ],
        max_tokens=800,
    )
    return resp.choices[0].message.content

# --- Loop principal ---
if __name__ == "__main__":
    tema = input("Tema a investigar: ")
    
    # Recuperar contexto del vault
    contexto = recuperar_contexto(tema)
    print(f"\n[RAG] Recuperados {len(contexto.split())} palabras de contexto\n")
    
    analisis = llamar_lector(tema, contexto)
    print(f"=== LECTOR (ronda 1) ===\n{analisis}\n")
    
    for ronda in range(MAX_RONDAS):
        critica = llamar_critico(tema, analisis)
        print(f"=== CRÍTICO (ronda {ronda+1}) ===\n{critica}\n")
        
        # El lector refina con la crítica
        analisis = llamar_lector(tema, contexto + "\n\n### Crítica previa:\n" + critica)
        print(f"=== LECTOR REFINADO (ronda {ronda+1}) ===\n{analisis}\n")
    
    print("=== RESULTADO FINAL ===")
    print(analisis)
```

**Ventajas del loop puro:**
- Cero dependencias de framework → cero bugs de framework
- Sin JSON tool-calls → más fiable con modelos 7–8B
- Fácil de debuggear y modificar
- RAG con ChromaDB exactamente como está pre-indexado

**Desventajas:**
- Sin YAML (todo hardcoded o via env vars)
- Sin logging estructurado de CrewAI
- Sin reintentos automáticos

---

## 3. Veredicto Final

### ¿Cuál usar?

```
SI necesitas YAML + RAG nativo + logging estructurado + Docker:
  → CrewAI 1.14.x con Process.sequential
  → Pero limita o elimina tools para evitar JSON tool-call failures
  → Usa qwen3:8b en vez de qwen2.5:7b si necesitas tools

SI el loop es simple (A lee → B critica → A refina × N):
  → Loop Python puro (ver sección 2.5) — más fiable con 7-8B
  → O smolagents con ToolCallingAgent (sin tools externas = CodeAgent mode)

NO usar:
  → AutoGen (modo mantenimiento, sin nuevas features desde oct 2025)
  → Hierarchical process en CrewAI con 7B models (manager falla)
  → LangGraph para un caso tan simple (overkill y verboso)
  → Letta (enfocado en memoria persistente de largo plazo, no en debate loops)
```

### Configuración recomendada CrewAI + LiteLLM Proxy

```python
# Configuración completa para el caso de uso descrito
from crewai import LLM

# Todos los alias apuntan al proxy LiteLLM en localhost:4000
LLM_LECTOR = LLM(
    model="openai/instantaneo",
    base_url="http://localhost:4000",   # LiteLLM proxy
    api_key="sk-MASTER_KEY",            # LiteLLM master key
    temperature=0.2,
    max_tokens=1000,
)

LLM_CRITICO = LLM(
    model="openai/agil",                # phi4-mini via LiteLLM
    base_url="http://localhost:4000",
    api_key="sk-MASTER_KEY",
    temperature=0.4,
    max_tokens=1000,
)

# Para el manager en Process.hierarchical (si se usa):
LLM_ORQUESTADOR = LLM(
    model="openai/orquestador",         # el modelo más capaz del grupo
    base_url="http://localhost:4000",
    api_key="sk-MASTER_KEY",
    temperature=0.1,
)
```

### Resumen de Compatibilidad con Modelos del Setup

| Modelo (alias LiteLLM) | Tool-calling | Como agente sin tools | Recomendado para |
|---|---|---|---|
| Llama 3.1 8B (`instantaneo`) | ⚠️ Inconsistente | ✅ Bien | Lector/sintetizador sin tools |
| Qwen2.5-Coder 7B (`codigo`) | ⚠️ Inconsistente en chains | ✅ Bien para texto | Revisor de código; sin tools |
| phi4-mini (`agil`) | ⚠️ No fiable en 7B | ✅ Bueno para crítica | Crítico/debatidor sin tools |
| Qwen3:8b (si se añade al proxy) | ✅ Fiable | ✅ Excelente | Todo, incluyendo tools |

> **Consejo práctico:** Si el debate loop no requiere tool-calling (solo leer del knowledge source integrado de CrewAI), estos modelos funcionan bien. El knowledge source de CrewAI **NO usa function-calling**: hace retrieval en ChromaDB antes del prompt, inyectando el contexto directamente. El riesgo de tool-calling solo aparece si se añaden `crewai_tools` como `SerperDevTool`, `FileReadTool`, etc.

---

## 4. Fuentes Principales

- [CrewAI Docs — LLM Connections](https://docs.crewai.com/v1.14.1/en/learn/llm-connections)
- [CrewAI Docs — Knowledge Sources](https://docs.crewai.com/v1.14.7/en/concepts/knowledge)
- [CrewAI — Guía sin LiteLLM](https://docs.crewai.com/v1.14.7/en/learn/litellm-removal-guide)
- [CrewAI Changelog](https://docs.crewai.com/en/changelog)
- [CrewAI Cheatsheet (DevShelfHub)](https://www.devshelfhub.com/cheatsheets/crewai/)
- [FutureAGI — OSS Frameworks 2026](https://futureagi.com/blog/oss-agent-frameworks-2026/)
- [Dev.to — Benchmarks locales LangGraph vs CrewAI vs smolagents 2026](https://dev.to/pooyagolchian/ai-agents-in-2026-langgraph-vs-crewai-vs-smolagents-with-real-benchmarks-on-local-llms-4ma1)
- [Dev.to — Tool calling con modelos locales 7 modelos](https://dev.to/kuroko1t/what-happens-when-local-llms-fail-at-tool-calling-testing-7-models-with-a-rust-coding-agent-cep)
- [AgenticWire — Estado de frameworks 2026](https://www.agenticwire.news/article/ai-agent-framework-status-2026)
- [AgentMarketCap — AutoGen modo mantenimiento](https://agentmarketcap.ai/blog/2026/04/13/microsoft-autogen-maintenance-mode-agent-framework-sunset-2026)
- [GitHub smolagents](https://github.com/huggingface/smolagents)
- [ZenML — smolagents vs LangGraph](https://www.zenml.io/blog/smolagents-vs-langgraph)
- [CrewAI Community — Tool calling local models](https://community.crewai.com/t/local-llms-tools-calling/5004)
- [CrewAI Community — Ollama knowledge embeddings](https://community.crewai.com/t/how-to-embed-knowledge-source-with-ollama2/2184)
- [Reddit r/LocalLLaMA — CrewAI con modelos locales](https://www.reddit.com/r/LocalLLaMA/comments/18v527r/crewai_agent_framework_with_local_models/)
- [GitHub crewai_docker template](https://github.com/vin67/crewai_docker)
- [RapidClaw — CrewAI Kubernetes 2026 (Docker pattern)](https://rapidclaw.dev/blog/deploy-crewai-production-tutorial-2026)
- [Letta AI Stack blog](https://www.letta.com/blog/ai-agents-stack/)
- [n8n Community — Tool calling con 7B](https://community.n8n.io/t/tool-calling-chain-with-local-ollama-models-7b-14b-2nd-tool-never-executed/280320)
