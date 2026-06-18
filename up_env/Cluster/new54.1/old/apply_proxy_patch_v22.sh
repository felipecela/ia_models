#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# apply_proxy_patch_v22.sh
# Aplica el parche V22 sobre omen_router_modules/proxy.py de forma segura:
#   1. Hace backup del proxy.py original
#   2. Reemplaza las 3 funciones: inject_opciones_extra, inject_thinking, check_tools
#   3. Añade las constantes TOOLS_SUPPORTED_MODELS, THINK_MODELS, MIN_CTX_GPU
#   4. Reinicia el router
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

PROXY="$HOME/ai_cluster/omen_router_modules/proxy.py"
BACKUP="${PROXY}.bak_v21_$(date +%Y%m%d_%H%M%S)"
ROUTER_PID_FILE="$HOME/ai_cluster/router_v14.pid"

echo "══════════════════════════════════════════════"
echo "  Parche V22 — proxy.py"
echo "══════════════════════════════════════════════"

# 1. Verificar existencia
if [[ ! -f "$PROXY" ]]; then
    echo "[ERROR] No se encuentra: $PROXY"
    exit 1
fi

# 2. Backup
cp "$PROXY" "$BACKUP"
echo "[OK]  Backup: $BACKUP"

# 3. Aplicar con Python (más seguro que sed para código Python)
python3 - "$PROXY" << 'PYEOF'
import sys, re, textwrap

proxy_path = sys.argv[1]
with open(proxy_path, "r") as f:
    src = f.read()

# ── Constantes a insertar tras los imports ──────────────────────────────────
CONSTANTS = '''
# ─────────────────────────────────────────────────────────────────────────────
# [V22] Capacidades por modelo
# ─────────────────────────────────────────────────────────────────────────────
TOOLS_SUPPORTED_MODELS = {
    "qwen2.5:32b", "qwen2.5:7b", "qwen2.5-coder:7b",
    "llama3.1:8b", "llama3.2:3b", "mistral:7b", "mistral-nemo",
}
THINK_MODELS = {
    "deepseek-r1:14b",
    "phi4-reasoning:plus",
    "phi4-reasoning:14b-q4_K_M",
}
MIN_CTX_GPU = 16384
GPU_NIVELES = {"PROFUNDO", "PRECISO", "PRECISO_OPT", "MASIVO", "AGIL"}
'''

# Insertar constantes si no existen
if "TOOLS_SUPPORTED_MODELS" not in src:
    # Insertar después del último import
    last_import = max(
        [m.end() for m in re.finditer(r'^(?:import|from)\s+\S+.*$', src, re.MULTILINE)],
        default=0
    )
    src = src[:last_import] + "\n" + CONSTANTS + src[last_import:]
    print("[V22] Constantes insertadas")
else:
    # Actualizar valores existentes por si han cambiado
    src = re.sub(
        r'MIN_CTX_GPU\s*=\s*\d+',
        'MIN_CTX_GPU = 16384',
        src
    )
    print("[V22] Constantes ya existentes — MIN_CTX_GPU actualizado a 16384")

# ── inject_opciones_extra — Bug #3 num_ctx ───────────────────────────────────
NEW_INJECT_OPTS = '''def inject_opciones_extra(body: dict, nivel: str, modelo: str = "") -> dict:
    """[V22-C1] Garantiza num_ctx >= 16384 para niveles GPU."""
    opts = body.get("options", {})
    if not isinstance(opts, dict):
        opts = {}
    if nivel in GPU_NIVELES:
        if opts.get("num_ctx", 0) < MIN_CTX_GPU:
            opts["num_ctx"] = MIN_CTX_GPU
    if "max_tokens" in body and "num_predict" not in opts:
        opts["num_predict"] = body["max_tokens"]
    if opts:
        body["options"] = opts
    return body
'''

src = re.sub(
    r'def inject_opciones_extra\(.*?\n(?=\ndef |\Z)',
    NEW_INJECT_OPTS + "\n",
    src,
    flags=re.DOTALL
)
print("[V22-C1] inject_opciones_extra reemplazada")

# ── inject_thinking — Bug #1 campo think ─────────────────────────────────────
NEW_INJECT_THINK = '''def inject_thinking(body: dict, nivel: str, modelo: str = "") -> dict:
    """[V22-T1] think va en body['options']['think'], NO en el body raíz."""
    modelo_lower = modelo.lower()
    body.pop("think", None)   # Eliminar si OpenClaw lo puso en el raíz
    if modelo_lower in THINK_MODELS or nivel in {"PROFUNDO", "PRECISO", "PRECISO_OPT"}:
        opts = body.get("options", {})
        if not isinstance(opts, dict):
            opts = {}
        opts["think"] = True
        body["options"] = opts
    return body
'''

src = re.sub(
    r'def inject_thinking\(.*?\n(?=\ndef |\Z)',
    NEW_INJECT_THINK + "\n",
    src,
    flags=re.DOTALL
)
print("[V22-T1] inject_thinking reemplazada")

# ── check_tools — Bug #2 tools sin soporte ────────────────────────────────────
NEW_CHECK_TOOLS = r'''def check_tools(body: dict, nivel: str, modelo: str = "") -> dict:
    """[V22-T2] Elimina tools para modelos sin soporte; convierte a texto plano."""
    import json as _json
    modelo_lower = modelo.lower()
    tools = body.get("tools")
    if not tools:
        return body
    if any(m in modelo_lower for m in TOOLS_SUPPORTED_MODELS):
        return body  # Soporte nativo → sin cambios
    # Sin soporte nativo: serializar tools como texto en system prompt
    tools_text = (
        "\n\n[AVAILABLE TOOLS — respond with JSON: "
        "{\"tool\":\"<name>\",\"arguments\":{<args>}}]\n"
    )
    for t in tools:
        func = t.get("function", t)
        name = func.get("name", "unknown")
        desc = func.get("description", "")
        params = func.get("parameters", {}).get("properties", {})
        req_list = func.get("parameters", {}).get("required", [])
        tools_text += f"- {name}: {desc}\n"
        for p, pdef in params.items():
            req = "required" if p in req_list else "optional"
            tools_text += f"    * {p} ({req}): {pdef.get('description','')}\n"
    tools_text += "[END TOOLS]\n"
    messages = body.get("messages", [])
    injected = False
    for msg in messages:
        if isinstance(msg, dict) and msg.get("role") == "system":
            c = msg.get("content", "")
            msg["content"] = (c if isinstance(c, str) else "") + tools_text
            injected = True
            break
    if not injected:
        messages.insert(0, {"role": "system", "content": tools_text.strip()})
    body.pop("tools", None)
    body.pop("tool_choice", None)
    body["messages"] = messages
    return body
'''

src = re.sub(
    r'def check_tools\(.*?\n(?=\ndef |\Z)',
    NEW_CHECK_TOOLS + "\n",
    src,
    flags=re.DOTALL
)
print("[V22-T2] check_tools reemplazada")

with open(proxy_path, "w") as f:
    f.write(src)

print("[OK]  proxy.py actualizado correctamente")
PYEOF

echo ""
echo "[OK]  Parche aplicado. Verificando sintaxis…"
python3 -m py_compile "$PROXY" && echo "[OK]  Sintaxis correcta" || echo "[ERROR] Sintaxis incorrecta — restaurar backup: cp '$BACKUP' '$PROXY'"

# 4. Reiniciar el router
echo ""
echo "══════════════════════════════════════════════"
echo "  Reiniciando Router V14…"
echo "══════════════════════════════════════════════"

if [[ -f "$ROUTER_PID_FILE" ]]; then
    OLD_PID=$(cat "$ROUTER_PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        kill "$OLD_PID"
        echo "[OK]  Router anterior (PID $OLD_PID) detenido"
        sleep 2
    fi
fi

LOG_DIR="$HOME/ai_cluster/logs"
ROUTER_SCRIPT="$HOME/ai_cluster/orchestrator_router_V14.py"

nohup python3 "$ROUTER_SCRIPT" \
    >> "$LOG_DIR/router_v14.log" 2>&1 &
NEW_PID=$!
echo "$NEW_PID" > "$ROUTER_PID_FILE"
echo "[OK]  Router V14 relanzado (PID $NEW_PID)"

echo ""
echo "  Esperando respuesta en :8000 (máx 30s)…"
for i in $(seq 1 15); do
    sleep 2
    if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
        echo "[OK]  Router V14 activo ✔"
        echo ""
        echo "  Verifica con:"
        echo "  curl -s http://localhost:8000/health | python3 -m json.tool"
        exit 0
    fi
    echo "  intento $i/15…"
done

echo "[WARN] El router aún no responde — revisa:"
echo "  tail -50 $LOG_DIR/router_v14.log"
