# FLOW ENGINEERING Y BUCLES AGÉNTICOS — CLÚSTER OMEN V58

Documento de análisis, decisión e implementación de la capa agéntica del clúster.
Acompaña a `Autoboot_Cluster_V58.sh` y a los dos informes de investigación
(`investigacion_aider` e `investigacion_crewai`).

---

## 1. Objetivo de la V58

Pasar de "prompts sueltos" a **bucles de razonamiento** (Flow Engineering):

1. **Programar con bucles (Aider)**: un agente de código que edita ficheros reales
   de un repositorio git, ejecuta, observa el resultado y vuelve a iterar,
   conectado al proxy LiteLLM del clúster.
2. **Debatir con Obsidian (CrewAI)**: dos agentes locales — un *lector* que
   consulta la base de conocimientos del vault y un *crítico* que cuestiona sus
   conclusiones — que iteran varias rondas hasta consensuar una nota final, que
   se guarda en el propio vault y se reincorpora a ChromaDB.

Requisito rector (invariable desde el inicio del proyecto): **maximizar el
razonamiento**, aceptando penalización de carga y de tiempos de espera.
Requisito de la V58: **no eliminar nada de la V57** — solo añadir.

---

## 2. Investigación: bucles de programación

### 2.1 Veredicto: Aider es la mejor opción

| Criterio | Aider | OpenHands | Goose | Plandex | Continue | gptme |
|---|---|---|---|---|---|---|
| Integración LiteLLM/OpenAI-compatible | Nativa (usa LiteLLM internamente) | Sí, pero requiere Docker | Sí | Sí | Sí | Sí |
| Funciona con modelos 7-8B | **Sí (edit-format `whole`)** | No (recomienda 35B+) | No (depende de tool-calling) | Regular | Parcial (IDE-first) | Sí (muy básico) |
| Sin contenedor adicional | Sí (CLI en host) | No | Sí | No | No (extensión IDE) | Sí |
| Edición real de repos git + auto-commit | Sí | Sí | Parcial | Sí | Parcial | Parcial |
| Madurez / comunidad | Muy alta | Alta | Media | Media | Alta | Baja |

Claves de la decisión:

- Aider **usa LiteLLM como librería interna**, por lo que el prefijo
  `openai/<alias>` contra el proxy del clúster funciona sin adaptadores
  ([documentación de modelos avanzados de Aider](https://aider.chat/docs/config/adv-model-settings.html)).
- Con modelos de 7-8B el formato de edición `diff` sale malformado con
  frecuencia; el formato **`whole`** (reescritura completa del fichero) es el
  único fiable a este tamaño. En los benchmarks de Aider, Qwen2.5-Coder-7B
  alcanza aproximadamente un 57,9 % con `whole`, frente a resultados muy
  inferiores con `diff`.
- **OpenHands** (ex-OpenDevin) es el más potente en agencia, pero su propia
  documentación recomienda modelos de 35B o más y exige un contenedor Docker
  con acceso al socket del host: descartado para una RTX 4070 de 8 GB.
- **Goose** (Block) depende de *tool-calling* estructurado, que los modelos
  <14B fallan sistemáticamente. **Plandex** exige servidor propio en Docker.
  **Continue** es IDE-first (VS Code/JetBrains), no CLI. **gptme** queda como
  alternativa ligera de reserva, pero sin la madurez de edición de Aider.

### 2.2 Configuración crítica para 7-8B (aplicada en el script)

- `edit-format: whole` — evita diffs malformados.
- `map-tokens: 0` — el mapa del repositorio confunde a los modelos pequeños y
  consume el contexto real de 8192 tokens servido por llama-swap.
- `auto-commits: false` — el usuario revisa antes de confirmar.
- `show-model-warnings: false` — evita avisos por modelos no catalogados.
- `aider.model.metadata.json` con los 4 alias del clúster (`instantaneo`,
  `codigo`, `agil`, `orquestador`), `max_input_tokens: 8192` (el contexto REAL
  configurado en llama-swap, no el teórico del modelo) y costes a 0.
- Instalación con `pip install aider-install && aider-install`
  ([guía oficial](https://aider.chat/docs/install.html)): crea un entorno
  aislado con `uv` y Python 3.12, sin contaminar el Python del sistema
  (compatible con PEP 668 / `--break-system-packages` detectado en el script).

---

## 3. Investigación: debate multiagente sobre Obsidian

### 3.1 Veredicto: CrewAI es la mejor opción

| Criterio | CrewAI | AutoGen | LangGraph | smolagents |
|---|---|---|---|---|
| Definición de roles en **YAML nativo** | **Sí** | No | No | No |
| RAG/knowledge integrado (ChromaDB) | **Sí, de serie** | Parcial | Manual | No |
| Funciona sin tool-calling (apto 7-8B) | **Sí** (knowledge por inyección) | Depende de function-calling | Configurable pero verboso | Depende de code-agents |
| Proxy OpenAI-compatible (LiteLLM) | Sí (`openai/` + `base_url`) | Sí | Sí | Sí |
| Estado del proyecto | Activo, v1.14.x | **Modo mantenimiento (oct 2025)** | Activo | Activo |

Claves de la decisión:

- CrewAI es el único framework que cumple literalmente la petición: "un
  contenedor que lea un archivo YAML con tus roles y ejecute el bucle de
  razonamiento de forma autónoma". Los roles (`agents.yaml`) y las tareas
  (`tasks.yaml`) son YAML de primera clase.
- Su sistema de **Knowledge Sources** usa ChromaDB internamente y funciona por
  *retrieval* + inyección en el prompt, **sin function-calling**
  ([documentación de Knowledge](https://docs.crewai.com/v1.14.7/en/concepts/knowledge)).
  Esto elimina el mayor riesgo con modelos 7-8B: los agentes llevan `tools=[]`
  y aun así consultan el vault.
- **AutoGen** (Microsoft) entró en modo mantenimiento en octubre de 2025 a
  favor de otro framework; mala apuesta a futuro. **LangGraph** es el más
  flexible pero exige programar el grafo a mano (mucho código, nada de YAML).
  **smolagents** carece de YAML y de RAG integrado.
- Importante (2026): el paquete `litellm` de PyPI está en cuarentena; CrewAI
  publicó una guía oficial para funcionar **sin litellm** usando el driver
  openai nativo, que es exactamente lo que hace la V58
  ([guía de migración](https://docs.crewai.com/v1.14.7/en/learn/litellm-removal-guide)):
  `pip install "crewai[openai]"` y `LLM(model="openai/<alias>", base_url=..., api_key=...)`.

### 3.2 Diseño del debate (aplicado en el script)

- **Dos agentes**: `lector_obsidian` (LLM `instantaneo`, temperatura 0.2, lee
  el vault vía knowledge source) y `critico_debatidor` (LLM `orquestador` =
  phi4-mini en **CPU**, temperatura 0.4). El crítico va en CPU adrede: así
  cada ronda de debate no provoca un swap de modelo en la GPU (el lector
  mantiene su modelo cargado) y ambos razonan en paralelo real.
- **`Process.sequential`**: el modo `hierarchical` requiere un modelo gestor
  con tool-calling fiable, que falla con 7-8B.
- **Bucle de rondas en `main.py`**: la crew se construye una sola vez y se
  hace `kickoff` por ronda (3 por defecto, `MAX_RONDAS=N` para cambiarlo). La
  crítica de la ronda anterior se inyecta como `{critica_previa}` en la
  siguiente lectura: eso es el bucle de consenso.
- **Knowledge**: hasta 300 notas `.md` del vault montadas en solo lectura en
  `/app/knowledge`, con embeddings de `nomic-embed-text` servidos por el
  Ollama CPU del clúster (puerto 11435, activo también en modo `--swap`).
- **Encadenado de conocimiento**: la nota final del debate se guarda con
  frontmatter en `$VAULT_DIR/debates_ia/`; al reindexar el vault entra en
  ChromaDB y queda disponible para debates y consultas futuras.

---

## 4. Integración con el clúster (qué añade la V58)

Nueva sección **9b/9 — Capa agéntica** en el autoboot, controlada por flags:

- `--agents` fuerza reinstalación de Aider y rebuild de la imagen CrewAI.
- `--no-agents` omite la capa en ese arranque.
- Sin flags: instalación **idempotente** (solo crea lo que falta; los YAML de
  roles no se sobrescriben, para que las personalizaciones del usuario
  sobrevivan a los reinicios).

Ficheros generados:

| Fichero | Función |
|---|---|
| `$AI_HOME/agents/aider/aider.conf.yml` | Config Aider apuntando a LiteLLM :4000 |
| `$AI_HOME/agents/aider/aider.model.settings.yml` | `whole`, sin repo-map, para los 4 alias |
| `$AI_HOME/agents/aider/aider.model.metadata.json` | Contexto 8192 y coste 0 por alias |
| `$AI_HOME/bin/aider_omen` | Lanzador: `aider_omen` dentro de un repo git |
| `$AI_HOME/agents/crewai_debate/{Dockerfile,requirements.txt}` | Imagen `crewai-debate:v58` (python:3.11-slim) |
| `$AI_HOME/agents/crewai_debate/config/{agents,tasks}.yaml` | Roles y tareas del debate (editables) |
| `$AI_HOME/agents/crewai_debate/src/main.py` | Bucle de rondas + knowledge + guardado en vault |
| `$AI_HOME/bin/debate_omen` | Lanzador: `debate_omen "tema"` |

Detalles de seguridad y estabilidad del contenedor de debate:

- Se ejecuta **bajo demanda** (`docker run --rm`), no como servicio residente:
  cero consumo de RAM/VRAM cuando no se debate.
- Red `ai_net` + `--add-host host.docker.internal:host-gateway` para alcanzar
  LiteLLM (:4000) y Ollama CPU (:11435) sin exponer puertos nuevos.
- Vault montado en **solo lectura**; única escritura permitida:
  `$VAULT_DIR/debates_ia/`. Corre con el UID/GID del usuario (sin root).
- `--stop` del clúster también para `crewai-debate`; `--status` verifica Aider
  y la imagen CrewAI.

### Qué NO cambia

Nada de la V57 se elimina. El diff V57→V58 solo modifica dos líneas (el número
de versión y la lista de contenedores de `--stop`, que ahora incluye
`crewai-debate`); todo lo demás son adiciones. Siguen intactos: Ollama GPU/CPU,
TabbyAPI, SGLang, llama-swap (`--swap`), ChromaDB, Obsidian, SearXNG, indexador
del vault, LiteLLM con sus 4 alias y fallbacks, y OpenClaw.

---

## 5. Uso

```bash
# Arranque normal (la capa agéntica se instala sola la primera vez)
ai_cluster --swap

# Programar con bucles sobre un repositorio
cd ~/mi_proyecto            # debe ser un repo git
~/ai_cluster/bin/aider_omen           # usa el alias "codigo" (Qwen2.5-Coder)

# Debatir un tema contra la base de conocimientos de Obsidian
~/ai_cluster/bin/debate_omen "estrategia de backups del clúster"
MAX_RONDAS=5 ~/ai_cluster/bin/debate_omen "tema complejo"   # más rondas

# La nota consensuada aparece en el vault:
#   $VAULT_DIR/debates_ia/  → reindexar con: ai_cluster --reindex
```

Personalización: editar `$AI_HOME/agents/crewai_debate/config/agents.yaml`
(roles, temperaturas, alias de modelo) y `tasks.yaml` (instrucciones de cada
fase). Los cambios se aplican en el siguiente `debate_omen` sin rebuild, porque
`config/` se monta en el contenedor en tiempo de ejecución.

---

## 6. Referencias

- Instalación de Aider: https://aider.chat/docs/install.html
- Ajustes avanzados de modelo (Aider): https://aider.chat/docs/config/adv-model-settings.html
- Knowledge Sources de CrewAI: https://docs.crewai.com/v1.14.7/en/concepts/knowledge
- Guía oficial de CrewAI sin litellm: https://docs.crewai.com/v1.14.7/en/learn/litellm-removal-guide
- Informes completos de investigación: `investigacion_aider` e `investigacion_crewai` (adjuntos).
