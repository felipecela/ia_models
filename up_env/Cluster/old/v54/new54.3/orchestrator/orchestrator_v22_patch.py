# ──────────────────────────────────────────────────────────────────────────────
#  PARCHE orchestrator_v22_patch.py
#  Aplica sobre: ~/ai_cluster/orchestrator_router_V14.py  (build V21/con debug)
#  Resultado:    build V22
#
#  CAMBIOS:
#  [V22-O1] Importa sanitize_for_ollama desde proxy.py
#  [V22-O2] Llama a sanitize_for_ollama() tras check_tools en el endpoint chat
#  [V22-O3] Actualiza banner a build V22
#  [V22-O4] Elimina el log [DBG] de debug temporal si estaba presente
# ──────────────────────────────────────────────────────────────────────────────

import os, sys, re

PATH = os.path.expanduser("~/ai_cluster/orchestrator_router_V14.py")
BACKUP = PATH + ".bak_v21"

with open(PATH) as f:
    src = f.read()

import shutil
shutil.copy(PATH, BACKUP)

# ── 1. Banner V21 → V22 ──────────────────────────────────────────────────────
src = src.replace(
    "OMEN AI Router V14 (build V21)",
    "OMEN AI Router V14 (build V22)",
    1
)

# ── 2. Eliminar línea de debug temporal si existe ────────────────────────────
debug_line_pattern = re.compile(
    r"[ \t]*import json as _j\n"
    r"[ \t]*log\.warning\(f?[\"\']\[DBG\].*?\)\n",
    re.DOTALL
)
src, n_debug = debug_line_pattern.subn("", src)
if n_debug:
    print(f"[OK] Eliminadas {n_debug} líneas de debug temporal [DBG]")

# ── 3. Importar sanitize_for_ollama ──────────────────────────────────────────
OLD_IMPORT = (
    "from omen_router_modules.proxy import (\n"
    "    inject_thinking,\n"
    "    check_tools,\n"
)
NEW_IMPORT = (
    "from omen_router_modules.proxy import (\n"
    "    inject_thinking,\n"
    "    check_tools,\n"
    "    sanitize_for_ollama,   # [V22-O1]\n"
)
if OLD_IMPORT in src:
    src = src.replace(OLD_IMPORT, NEW_IMPORT, 1)
    print("[OK] sanitize_for_ollama importada")
else:
    # Fallback: buscar la línea check_tools en el import y añadir tras ella
    src = src.replace(
        "    check_tools,",
        "    check_tools,\n    sanitize_for_ollama,   # [V22-O1]",
        1
    )
    print("[OK] sanitize_for_ollama importada (fallback)")

# ── 4. Añadir llamada a sanitize_for_ollama tras check_tools ─────────────────
OLD_CALL = "    body = check_tools(body, nivel, body[\"model\"])  # [V23-C1]"
NEW_CALL = (
    "    body = check_tools(body, nivel, body[\"model\"])       # [V23-C1]\n"
    "    body = sanitize_for_ollama(body, nivel, body[\"model\"])  # [V22-O2]"
)
if OLD_CALL in src:
    src = src.replace(OLD_CALL, NEW_CALL, 1)
    print("[OK] sanitize_for_ollama() añadida al pipeline de chat")
else:
    # Variante sin comentario específico
    fallback = "    body = check_tools(body, nivel, body[\"model\"])"
    if fallback in src:
        src = src.replace(
            fallback,
            fallback + "\n    body = sanitize_for_ollama(body, nivel, body[\"model\"])  # [V22-O2]",
            1
        )
        print("[OK] sanitize_for_ollama() añadida (fallback sin comentario)")
    else:
        print("[ERROR] No se encontró la línea check_tools en el endpoint chat")
        sys.exit(1)

with open(PATH, "w") as f:
    f.write(src)

print(f"[OK] Backup guardado en {BACKUP}")
print(f"[OK] orchestrator_router_V14.py actualizado a build V22")
