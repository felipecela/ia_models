# ... existing code ...
else
    ok "Todas las dependencias Python disponibles"
fi

# ═══════════════════════════════════════════════════════════════════════════════
# 8/9 — LITELLM (Proxy / Router Inteligente :4000) [V55]
# ═══════════════════════════════════════════════════════════════════════════════
section "8/9 — LiteLLM Gateway (:4000)"

LITELLM_CONFIG="$AI_HOME/litellm_config.yaml"
if [[ ! -f "$LITELLM_CONFIG" ]]; then
    err "Archivo $LITELLM_CONFIG no encontrado. Créalo antes de arrancar."
    exit 1
fi

ensure_container_stopped "litellm-router"
pull_if_last "ghcr.io/berriai/litellm:main-latest" "LiteLLM"

info "[V55] Lanzando LiteLLM como pasarela universal de modelos…"
docker run -d \
    --name litellm-router \
    --network "$DOCKER_NET" \
    -p 4000:4000 \
    -v "$LITELLM_CONFIG:/app/config.yaml:ro" \
    --add-host host.docker.internal:host-gateway \
    --restart unless-stopped \
    ghcr.io/berriai/litellm:main-latest \
    --config /app/config.yaml --port 4000

if wait_port "LiteLLM" localhost 4000 30; then
    ok "LiteLLM ✔ → http://localhost:4000"
else
    warn "LiteLLM no respondió a tiempo. Revisa: docker logs litellm-router"
fi

# ═══════════════════════════════════════════════════════════════════════════════
# 9/9 — OpenClaw Server (:$PORT_OPENCLAW)  [V55]
# ═══════════════════════════════════════════════════════════════════════════════
section "9/9 — OpenClaw Server (:$PORT_OPENCLAW)"

# ─── Limpieza ────────────────────────────────────────────────────────────────
info "[V55] Deteniendo y eliminando contenedor previo 'openclaw-server'…"
docker stop openclaw-server 2>/dev/null || true
# ... existing code ...
ok "Preseed copiado al volumen"

# ─── Purgar Utilidades Nativas (Context Bloat) ──────────────────────────────
info "[V55] Purgando utilidades nativas de OpenClaw (.system)…"
docker run --rm \
    -v openclaw_data_final:/data \
    busybox sh -c "rm -rf /data/.openclaw/agents/main/agent/codex-home/skills/.system" 2>/dev/null || true
ok "Utilidades por defecto eliminadas. Se preservan tus plugins de Obsidian en la raíz de skills."

# ─── Escribir inject_v55.py en el HOST ──────────────────────────────────────
_INJECT_HOST_PATH="/tmp/inject_v55_host.py"
cat > "$_INJECT_HOST_PATH" << 'INJECT_PY_V55_EOF'
import json, sys

CFG_PATH    = "/data/.openclaw/openclaw.json"
MODELS_PATH = "/tmp/oc_models.json"
PROVIDER_ID = "litellm-omen"
ROUTER_URL  = "http://host.docker.internal:4000/v1"
API_KEY     = "sk-litellm-local"

# Leer lista de modelos
try:
    with open(MODELS_PATH) as f:
        models = json.load(f)
except Exception as e:
    print("[V55] ERROR leyendo modelos: " + str(e))
    sys.exit(1)

# Leer config actual
try:
    with open(CFG_PATH) as f:
        cfg = json.load(f)
except Exception as e:
    print("[V55] WARN config no legible (" + str(e) + "), partiendo de vacio")
    cfg = {}

# Asegurar estructura models.providers
if "models" not in cfg or not isinstance(cfg["models"], dict):
    cfg["models"] = {}
if "providers" not in cfg["models"] or not isinstance(cfg["models"]["providers"], dict):
    cfg["models"]["providers"] = {}

# Eliminar providers externos (openai, ollama, omen-router viejo)
for _rm in ("ollama", "openai", "omen-router"):
    removed = cfg["models"]["providers"].pop(_rm, None)
    if removed:
        print("[V55] Provider antiguo eliminado: " + _rm)

# Registrar LiteLLM
cfg["models"]["providers"][PROVIDER_ID] = {
    "api":     "openai-completions",
    "baseUrl": ROUTER_URL,
    "apiKey":  API_KEY,
    "models":  models
}

# Asegurar estructura agents.defaults.model
if "agents" not in cfg or not isinstance(cfg["agents"], dict):
    cfg["agents"] = {}
if "defaults" not in cfg["agents"] or not isinstance(cfg["agents"]["defaults"], dict):
    cfg["agents"]["defaults"] = {}
if "model" not in cfg["agents"]["defaults"] or not isinstance(cfg["agents"]["defaults"]["model"], dict):
    cfg["agents"]["defaults"]["model"] = {}
cfg["agents"]["defaults"]["model"]["primary"] = PROVIDER_ID + "/profundo-r1"

# Asegurar estructura plugins.entries
if "plugins" not in cfg or not isinstance(cfg["plugins"], dict):
    cfg["plugins"] = {}
if "entries" not in cfg["plugins"] or not isinstance(cfg["plugins"]["entries"], dict):
    cfg["plugins"]["entries"] = {}
for _rm in ("ollama", "openai", "omen-router"):
    cfg["plugins"]["entries"].pop(_rm, None)
cfg["plugins"]["entries"][PROVIDER_ID] = {"enabled": True}

# Escribir config final
with open(CFG_PATH, "w") as f:
    json.dump(cfg, f, indent=2, ensure_ascii=False)

model_count   = len(models)
providers_now = list(cfg["models"]["providers"].keys())
primary_now   = cfg["agents"]["defaults"]["model"]["primary"]

print("[V55] OK: provider registrado: " + PROVIDER_ID)
print("[V55] OK: " + str(model_count) + " modelos bajo models.providers." + PROVIDER_ID + ".models")
print("[V55] OK: agents.defaults.model.primary = " + primary_now)
print("[V55] Providers en config: " + str(providers_now))
print("litellm-omen")
INJECT_PY_V55_EOF

ok "[V55] inject_v55.py escrito en HOST: $_INJECT_HOST_PATH"

# ─── Lanzar openclaw-server ───────────────────────────────────────────────────
# ... existing code ...
    -e OLLAMA_BASE_URL="http://host.docker.internal:${PORT_OLLAMA_GPU}" \
    -v openclaw_data_final:/data \
    "$IMG_OPENCLAW"

# ─── Esperar gateway arrancado (máx 120s) ────────────────────────────────────
# ... existing code ...
[[ "$_OC_RUNNING" == "false" ]] && warn "[V54] Contenedor NO 'running' — estado: $(docker inspect -f '{{.State.Status}}' openclaw-server 2>/dev/null || echo '?')"
sleep 3

# ─── Construir lista de modelos estática para LiteLLM ────────────────────────
info "[V55] Configurando modelos de LiteLLM en OpenClaw…"

_MODELS_JSON='[
  {"id":"profundo-r1",  "name":"DeepSeek R1 14B (Razonamiento Profundo)", "contextWindow":16384},
  {"id":"masivo-qwen",  "name":"Qwen 2.5 32B (Razonamiento Masivo)",      "contextWindow":32768},
  {"id":"preciso-phi4", "name":"Phi-4 Reasoning (Lógica Precisa)",        "contextWindow":16384},
  {"id":"coder-v2",     "name":"DeepSeek Coder V2 (Programación Pura)",   "contextWindow":32768}
]'
_MODEL_COUNT=4

info "[V55] Modelos a registrar: ${_MODEL_COUNT}"

# ─── Copiar modelos y script al contenedor y ejecutar ─────────────────────────
info "[V55] Inyectando provider LiteLLM en openclaw.json…"
echo "$_MODELS_JSON" > /tmp/oc_models_v55.json

_INJECT_OK=false
for _inj_retry in 1 2 3; do
    docker cp /tmp/oc_models_v55.json openclaw-server:/tmp/oc_models.json  2>/dev/null || true
    docker cp "$_INJECT_HOST_PATH"    openclaw-server:/tmp/inject_v55.py   2>/dev/null || true

    _OC_INJ_LOG="/tmp/oc_inject_v55_try${_inj_retry}.log"
    docker exec openclaw-server python3 /tmp/inject_v55.py > "$_OC_INJ_LOG" 2>&1
    _INJ_EXIT=$?

    if [[ -f "$_OC_INJ_LOG" ]]; then
        while IFS= read -r _il; do
            if echo "$_il" | grep -qi "error\|fail\|traceback\|syntaxerror"; then
                warn "  $_il"
            else
                info "  $_il"
            fi
        done < "$_OC_INJ_LOG"
    fi

    if [[ $_INJ_EXIT -eq 0 ]] && grep -q "litellm-omen" "$_OC_INJ_LOG" 2>/dev/null; then
        _INJECT_OK=true
        ok "[V55] inject_v55.py completado en intento ${_inj_retry}"
        break
    else
        warn "[V55] inject fallido (intento ${_inj_retry}/3, exit=${_INJ_EXIT}) — esperando 5s…"
        sleep 5
    fi
done

if [[ "$_INJECT_OK" == "false" ]]; then
    warn "[V55] ATENCIÓN: inject no pudo completar. Revisa los logs."
fi

# ─── SIGHUP para reload del config ───────────────────────────────────────────
# ... existing code ...
    ok "[V54] SIGHUP enviado al contenedor"
fi
sleep 4

# ─── Verificar HTTP ───────────────────────────────────────────────────────────
# ... existing code ...
    sleep 2
done
[[ ! "$OPENCLAW_HTTP" =~ ^(200|301|302)$ ]] && warn "OpenClaw HTTP respondió ${OPENCLAW_HTTP}"

# ─── Verificación final inline (sin backslashes en f-strings) ────────────────
info "[V55] Verificando config final…"
_OC_VERIFY_LOG="/tmp/oc_verify_v55.log"
docker exec openclaw-server python3 -c "
import json, sys
try:
    with open('/data/.openclaw/openclaw.json') as f:
        d = json.load(f)
    providers    = d.get('models', {}).get('providers', {})
    primary_val  = d.get('agents', {}).get('defaults', {}).get('model', {}).get('primary', '?')
    provider_keys = list(providers.keys())
    print('[V55] Providers registrados: ' + str(provider_keys))
    print('[V55] Modelo primario: ' + primary_val)
    for pid in provider_keys:
        pdata  = providers[pid]
        mcount = len(pdata.get('models', []))
        base   = pdata.get('baseUrl', '?')
        print('[V55]   ' + pid + ' -> ' + base + '  (' + str(mcount) + ' modelos)')
    if 'litellm-omen' in providers:
        mc = len(providers['litellm-omen'].get('models', []))
        print('[V55] STATUS: OK litellm-omen registrado correctamente (' + str(mc) + ' modelos)')
    else:
        print('[V55] STATUS: FALLO litellm-omen NO encontrado en providers')
        sys.exit(2)
except Exception as e:
    print('[V55] ERROR verificando config: ' + str(e))
    sys.exit(1)
" > "$_OC_VERIFY_LOG" 2>&1
_VERIFY_EXIT=$?

if [[ -f "$_OC_VERIFY_LOG" ]]; then
    while IFS= read -r _vl; do
        if echo "$_vl" | grep -q "STATUS: OK"; then
            ok "  $_vl"
        elif echo "$_vl" | grep -qi "FALLO\|ERROR\|STATUS.*NO"; then
            warn "  $_vl"
        else
            ok "  $_vl"
        fi
    done < "$_OC_VERIFY_LOG"
fi

# ... existing code ...
# RESUMEN FINAL
# ═══════════════════════════════════════════════════════════════════════════════
section "Resumen del Cluster V55"

echo ""
# ... existing code ...
check_service "SearXNG"                  localhost    "$PORT_SEARXNG"
check_service "LiteLLM Gateway"          localhost    4000
check_service "OpenClaw Server"          localhost    "$PORT_OPENCLAW"

echo ""
echo -e "${BLD}OpenClaw Server:${NC}"
echo "  WebUI (auto-login):  http://localhost:${PORT_OPENCLAW}/#token=${OPENCLAW_TOKEN}"
# ... existing code ...
echo -e "${BLD}Comandos útiles:${NC}"
echo "  Ver logs LiteLLM: docker logs -f litellm-router"
echo "  Indexar vault:    python3 $VAULT_INDEXER"
echo "  Reindexar todo:   python3 $VAULT_INDEXER --clean"
echo "  Parar cluster:    ai_cluster --stop"
echo "  Heartbeat chroma: curl -s http://127.0.0.1:${PORT_CHROMADB}/api/v1/heartbeat"
echo ""
# ... existing code ...
echo -e "${GRN}${BLD}OMEN AI Cluster V55 — iniciado${NC}"
echo -e "$(date '+%Y-%m-%d %H:%M:%S')"