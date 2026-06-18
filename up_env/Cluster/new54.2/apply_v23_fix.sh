#!/bin/bash
# apply_v23_fix.sh — Aplica el fix V23 y reinicia solo el router
# Uso: bash apply_v23_fix.sh

set -e
cd ~/ai_cluster

echo "═══════════════════════════════════════════════"
echo "  Fix V23 — sanitize_for_ollama"
echo "═══════════════════════════════════════════════"

# 1. Aplicar parche a proxy.py
echo ""
echo "[1/3] Parcheando proxy.py (build V22 → V23)..."
python3 omen_router_modules/proxy_v23_patch.py

# 2. Aplicar parche a orchestrator_router_V14.py
echo ""
echo "[2/3] Parcheando orchestrator_router_V14.py (build V21 → V22)..."
python3 orchestrator_v22_patch.py

# 3. Validar sintaxis Python
echo ""
echo "[3/3] Validando sintaxis..."
python3 -m py_compile omen_router_modules/proxy.py \
  && echo "[OK] proxy.py — sintaxis OK"
python3 -m py_compile orchestrator_router_V14.py \
  && echo "[OK] orchestrator_router_V14.py — sintaxis OK"

# 4. Reiniciar solo el router (sin tocar Docker)
echo ""
echo "[RESTART] Reiniciando router V14..."
kill $(cat router_v14.pid) 2>/dev/null || true
sleep 2
nohup python3 orchestrator_router_V14.py \
  >> logs/router_v14.log 2>&1 &
echo $! > router_v14.pid
sleep 4

# 5. Verificar arranque
echo ""
tail -6 logs/router_v14.log | grep -E "build|Niveles|startup complete|ERROR"

echo ""
echo "═══════════════════════════════════════════════"
echo "  Router reiniciado. Ahora ve a OpenClaw y"
echo "  envía 'hola' con cualquier modelo."
echo "  Verifica con:"
echo "    grep -E '400|V23-S1|PROXY' logs/router_v14.log | tail -10"
echo "═══════════════════════════════════════════════"
