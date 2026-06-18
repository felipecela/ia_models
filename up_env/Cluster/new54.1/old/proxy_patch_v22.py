"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  PARCHE V22 para omen_router_modules/proxy.py                              ║
║                                                                              ║
║  Corrige 3 causas raíz del error:                                           ║
║    "provider rejected the request schema or tool payload" (400)             ║
║                                                                              ║
║  Bug #1 [V22-T1] — inject_thinking: campo "think" en body raíz             ║
║    Ollama NO acepta "think" como campo top-level OpenAI.                    ║
║    Debe ir en body["options"]["think"] = True (API nativa Ollama).          ║
║                                                                              ║
║  Bug #2 [V22-T2] — check_tools: modelos sin soporte de tools               ║
║    deepseek-r1:14b y phi4-reasoning:* no tienen chat-template con tools.    ║
║    Si el body lleva "tools", Ollama devuelve 400.                           ║
║    Solución: eliminar tools/tool_choice del body para esos modelos          ║
║    e inyectar el schema de tools como texto plano en el system prompt.      ║
║                                                                              ║
║  Bug #3 [V22-C1] — inject_opciones_extra: num_ctx no llega a Ollama        ║
║    El ctx del catálogo de modelos se define en RUTAS pero                   ║
║    inject_opciones_extra debe garantizar que options.num_ctx >= 16384       ║
║    para todos los backends GPU (PROFUNDO, PRECISO, PRECISO_OPT, MASIVO).   ║
╚══════════════════════════════════════════════════════════════════════════════╝

INSTRUCCIONES DE APLICACIÓN:
  Abre ~/ai_cluster/omen_router_modules/proxy.py y aplica los tres cambios
  marcados con [V22-T1], [V22-T2] y [V22-C1] según las secciones siguientes.
  Después reinicia el router: kill $(cat ~/ai_cluster/router_v14.pid) && 
  python3 ~/ai_cluster/orchestrator_router_V14.py &
"""

# ─────────────────────────────────────────────────────────────────────────────
# MODELOS CON SOPORTE NATIVO DE TOOLS EN OLLAMA
# Estos modelos tienen chat-template con <tool_call> → aceptan "tools" en body
# ─────────────────────────────────────────────────────────────────────────────
TOOLS_SUPPORTED_MODELS = {
    "qwen2.5:32b",
    "qwen2.5:7b",
    "qwen2.5-coder:7b",
    "llama3.1:8b",
    "llama3.2:3b",
    "mistral:7b",
    "mistral-nemo",
    # Añadir aquí otros modelos con soporte tools verificado
}

# Modelos que requieren "think" en options (no en body raíz)
THINK_MODELS = {
    "deepseek-r1:14b",
    "phi4-reasoning:plus",
    "phi4-reasoning:14b-q4_K_M",
}

# Contexto mínimo garantizado para backends GPU (en tokens)
MIN_CTX_GPU = 16384


# ─────────────────────────────────────────────────────────────────────────────
# [V22-C1] inject_opciones_extra — Garantizar num_ctx >= MIN_CTX_GPU
# REEMPLAZA la función inject_opciones_extra existente en proxy.py
# ─────────────────────────────────────────────────────────────────────────────
def inject_opciones_extra(body: dict, nivel: str, modelo: str = "") -> dict:
    """
    [V22-C1] Inyecta opciones Ollama en body["options"].
    Garantiza num_ctx >= 16384 para todos los niveles GPU.
    """
    opts = body.get("options", {})
    if not isinstance(opts, dict):
        opts = {}

    # Niveles que van a la GPU y necesitan contexto extendido
    GPU_NIVELES = {"PROFUNDO", "PRECISO", "PRECISO_OPT", "MASIVO", "AGIL"}

    if nivel in GPU_NIVELES:
        ctx_actual = opts.get("num_ctx", 0)
        if ctx_actual < MIN_CTX_GPU:
            opts["num_ctx"] = MIN_CTX_GPU

    # Preservar num_predict si ya viene en el body raíz como max_tokens
    if "max_tokens" in body and "num_predict" not in opts:
        opts["num_predict"] = body["max_tokens"]

    if opts:
        body["options"] = opts
    return body


# ─────────────────────────────────────────────────────────────────────────────
# [V22-T1] inject_thinking — Mover "think" a body["options"]["think"]
# REEMPLAZA la función inject_thinking existente en proxy.py
# ─────────────────────────────────────────────────────────────────────────────
def inject_thinking(body: dict, nivel: str, modelo: str = "") -> dict:
    """
    [V22-T1] Inyecta el parámetro de razonamiento extendido.

    Ollama acepta "think" ÚNICAMENTE dentro de body["options"]["think"].
    Ponerlo en el body raíz (como campo OpenAI estándar) genera 400.
    Los modelos phi4-reasoning y deepseek-r1 necesitan think=True.
    """
    modelo_lower = modelo.lower()

    # Eliminar "think" del body raíz si OpenClaw o versiones anteriores lo pusieron ahí
    body.pop("think", None)

    if modelo_lower in THINK_MODELS or nivel in {"PROFUNDO", "PRECISO", "PRECISO_OPT"}:
        opts = body.get("options", {})
        if not isinstance(opts, dict):
            opts = {}
        opts["think"] = True
        body["options"] = opts

    return body


# ─────────────────────────────────────────────────────────────────────────────
# [V22-T2] check_tools — Eliminar tools para modelos sin soporte
# REEMPLAZA la función check_tools existente en proxy.py
# ─────────────────────────────────────────────────────────────────────────────
def check_tools(body: dict, nivel: str, modelo: str = "") -> dict:
    """
    [V22-T2] Gestión de tools según capacidad del modelo destino.

    Si el body contiene "tools" (enviado por OpenClaw para que el agente
    use herramientas), pero el modelo destino NO soporta la API de tools
    de Ollama, se eliminan tools/tool_choice del body y se convierte el
    schema de tools en texto plano que se inyecta al system prompt.
    Así el modelo puede seguir razonando sobre las herramientas disponibles
    sin que Ollama rechace la request con 400.
    """
    modelo_lower = modelo.lower()
    tools = body.get("tools")

    if not tools:
        return body  # Sin tools → nada que hacer

    # Modelo con soporte nativo → dejar pasar sin modificar
    if any(m in modelo_lower for m in TOOLS_SUPPORTED_MODELS):
        return body

    # ── Modelo SIN soporte de tools: convertir a texto plano ─────────────────
    # Serializar el schema de tools como JSON legible para el LLM
    import json
    tools_text = (
        "\n\n[AVAILABLE TOOLS]\n"
        "The following tools are available. To use a tool, reply with a JSON block "
        "in the format: {\"tool\": \"<name>\", \"arguments\": {<args>}}\n\n"
    )
    for t in tools:
        func = t.get("function", t)
        name = func.get("name", "unknown")
        desc = func.get("description", "")
        params = func.get("parameters", {})
        tools_text += f"- {name}: {desc}\n"
        if params.get("properties"):
            for p, pdef in params["properties"].items():
                req = "required" if p in params.get("required", []) else "optional"
                tools_text += f"    • {p} ({req}): {pdef.get('description', '')}\n"
    tools_text += "[END TOOLS]\n"

    # Inyectar en el system prompt (primer mensaje con role=system)
    messages = body.get("messages", [])
    injected = False
    for msg in messages:
        if isinstance(msg, dict) and msg.get("role") == "system":
            content = msg.get("content", "")
            if isinstance(content, str):
                msg["content"] = content + tools_text
            injected = True
            break

    if not injected and messages:
        # No hay system prompt → crear uno
        messages.insert(0, {"role": "system", "content": tools_text.strip()})

    # Eliminar tools y tool_choice del body (Ollama los rechaza para estos modelos)
    body.pop("tools", None)
    body.pop("tool_choice", None)
    body["messages"] = messages

    return body


# ─────────────────────────────────────────────────────────────────────────────
# ORDEN CORRECTO DE LLAMADA en orchestrator_router_V14.py (ya está correcto):
#   body = inject_opciones_extra(body, nivel)    ← [V22-C1] num_ctx
#   body = inject_thinking(body, nivel, model)   ← [V22-T1] think en options
#   body = check_tools(body, nivel, model)       ← [V22-T2] tools → text
# ─────────────────────────────────────────────────────────────────────────────
