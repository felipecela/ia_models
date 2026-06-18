# ──────────────────────────────────────────────────────────────────────────────
#  PARCHE proxy_v23_patch.py
#  Aplica sobre: ~/ai_cluster/omen_router_modules/proxy.py  (build V22)
#  Resultado:    build V23
#
#  CORRECCIONES V23:
#  [V23-S1] sanitize_for_ollama(): elimina campos OpenAI que Ollama /api/chat
#           rechaza con 400 en TODOS los modelos:
#             - stream_options      (include_usage — solo OpenAI)
#             - max_completion_tokens (renombra a options.num_predict)
#           Estos campos llegaban de OpenClaw en CADA petición de agente y
#           causaban el 400 independientemente del modelo seleccionado.
#  [V23-S2] check_tools ya gestionaba tools/tool_choice — no se toca.
# ──────────────────────────────────────────────────────────────────────────────

import re, os, sys

PATH = os.path.expanduser("~/ai_cluster/omen_router_modules/proxy.py")
BACKUP = PATH + ".bak_v22"

with open(PATH) as f:
    src = f.read()

# ── 1. Cabecera: V22 → V23 ──────────────────────────────────────────────────
src = src.replace(
    "║  OMEN AI Router V14 (build V22)                                             ║",
    "║  OMEN AI Router V14 (build V23)                                             ║",
    1
)

# ── 2. Añadir bloque de correcciones V23 en la cabecera ─────────────────────
OLD_HDR = "║  [V22-C2] check_tools: corrige bug — la función devolvía None (no dict).   ║"
NEW_HDR = (
    "║  [V22-C2] check_tools: corrige bug — la función devolvía None (no dict).   ║\n"
    "║                                                                              ║\n"
    "║  CORRECCIONES V23:                                                           ║\n"
    "║  [V23-S1] sanitize_for_ollama(): elimina campos OpenAI que Ollama rechaza   ║\n"
    "║           con HTTP 400: stream_options, max_completion_tokens.              ║\n"
    "║           Activos en TODAS las peticiones de agente de OpenClaw v2026.6.8+  ║"
)
src = src.replace(OLD_HDR, NEW_HDR, 1)

# ── 3. Nueva función sanitize_for_ollama() — insertar ANTES de proxy_request ─
# Buscamos la definición de proxy_request para insertar justo antes
ANCHOR_PROXY = "async def proxy_request("

NEW_FUNC = (
    "# [V23-S1] Campos OpenAI incompatibles con Ollama /api/chat\n"
    "_OLLAMA_UNSUPPORTED = {\n"
    "    \"stream_options\",       # include_usage — solo OpenAI\n"
    "    \"max_completion_tokens\", # OpenAI alias de max_tokens; Ollama usa options.num_predict\n"
    "    \"logprobs\",\n"
    "    \"top_logprobs\",\n"
    "    \"service_tier\",\n"
    "    \"store\",\n"
    "}\n"
    "\n"
    "def sanitize_for_ollama(body: dict, nivel: str, model: str) -> dict:\n"
    "    \"\"\"[V23-S1] Elimina campos OpenAI que Ollama /api/chat no acepta.\n"
    "    Actúa sobre TODOS los niveles; no depende de capacidades del modelo.\n"
    "    Convierte además max_completion_tokens → options.num_predict.\n"
    "    \"\"\"\n"
    "    removed = []\n"
    "    # max_completion_tokens → options.num_predict (si no viene ya max_tokens)\n"
    "    if \"max_completion_tokens\" in body:\n"
    "        mct = body.pop(\"max_completion_tokens\")\n"
    "        removed.append(\"max_completion_tokens\")\n"
    "        if \"max_tokens\" not in body:\n"
    "            opts = body.setdefault(\"options\", {})\n"
    "            opts[\"num_predict\"] = mct\n"
    "    # Eliminar resto de campos incompatibles\n"
    "    for campo in (_OLLAMA_UNSUPPORTED - {\"max_completion_tokens\"}):\n"
    "        if campo in body:\n"
    "            body.pop(campo)\n"
    "            removed.append(campo)\n"
    "    if removed:\n"
    "        log.debug(f\"[V23-S1] sanitize_for_ollama [{nivel}] eliminados: {removed}\")\n"
    "    return body\n"
    "\n"
    "\n"
)

if ANCHOR_PROXY in src:
    src = src.replace(ANCHOR_PROXY, NEW_FUNC + ANCHOR_PROXY, 1)
    print("[OK] sanitize_for_ollama() insertada en proxy.py")
else:
    print("[ERROR] No se encontró 'async def proxy_request(' en proxy.py")
    sys.exit(1)

# ── 4. Exportar sanitize_for_ollama en el __all__ / imports del módulo ───────
# Buscamos la línea que exporta check_tools para añadir sanitize_for_ollama
OLD_EXPORT = '"check_tools",'
NEW_EXPORT = '"check_tools",\n    "sanitize_for_ollama",'
if OLD_EXPORT in src:
    src = src.replace(OLD_EXPORT, NEW_EXPORT, 1)
    print("[OK] sanitize_for_ollama exportada en __all__")
else:
    # Si no hay __all__, no pasa nada — la función es importable igual
    print("[INFO] No se encontró __all__ con check_tools — función igualmente importable")

# ── 5. Escribir ──────────────────────────────────────────────────────────────
import shutil
shutil.copy(PATH, BACKUP)
with open(PATH, "w") as f:
    f.write(src)

print(f"[OK] Backup guardado en {BACKUP}")
print(f"[OK] proxy.py actualizado a build V23")
