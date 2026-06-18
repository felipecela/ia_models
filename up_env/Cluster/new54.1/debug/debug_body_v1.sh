#!/bin/bash
# debug_body_v1.sh — Añade log temporal del body completo al router
# Uso: bash debug_body_v1.sh
# Revierte con: bash debug_body_v1.sh --revert

ORQUESTADOR="$HOME/ai_cluster/orchestrator_router_V14.py"
BACKUP="${ORQUESTADOR}.bak_debug"

if [[ "$1" == "--revert" ]]; then
    if [[ -f "$BACKUP" ]]; then
        cp "$BACKUP" "$ORQUESTADOR"
        echo "[OK] Revertido — debug log eliminado"
        kill $(cat ~/ai_cluster/router_v14.pid) && sleep 1
        nohup python3 "$ORQUESTADOR" >> ~/ai_cluster/logs/router_v14.log 2>&1 &
        echo $! > ~/ai_cluster/router_v14.pid
        echo "[OK] Router reiniciado sin debug"
    else
        echo "[WARN] No hay backup — nada que revertir"
    fi
    exit 0
fi

# Backup
cp "$ORQUESTADOR" "$BACKUP"

# Insertar línea de debug justo después de "body = await request.json()"
# La línea siguiente en el orquestador es "except Exception:"
python3 - << 'PYEOF'
import re

path = "/root/ai_cluster/orchestrator_router_V14.py"
import os
path = os.path.expanduser("~/ai_cluster/orchestrator_router_V14.py")

with open(path) as f:
    src = f.read()

OLD = '        body = await request.json()\n'
NEW = ('        body = await request.json()\n'
       '        import json as _json\n'
       '        log.warning(f"[V23-DEBUG] BODY_KEYS={list(body.keys())} | '
       'FULL={_json.dumps({k:v for k,v in body.items() if k != \"messages\"})[:1500]}")\n')

if OLD in src:
    src = src.replace(OLD, NEW, 1)
    with open(path, "w") as f:
        f.write(src)
    print("[OK] Debug log inyectado en orchestrator_router_V14.py")
else:
    print("[WARN] No se encontró el anchor — busca manualmente")
    import subprocess
    lines = subprocess.check_output(["grep", "-n", "body = await request.json", path]).decode()
    print(lines)
PYEOF

# Reiniciar router con debug activo
kill $(cat ~/ai_cluster/router_v14.pid) 2>/dev/null; sleep 1
nohup python3 "$ORQUESTADOR" >> ~/ai_cluster/logs/router_v14.log 2>&1 &
echo $! > ~/ai_cluster/router_v14.pid
echo "[OK] Router reiniciado con debug — PID=$!"
echo ""
echo "Ahora envía UN mensaje desde OpenClaw y ejecuta:"
echo "  grep 'V23-DEBUG' ~/ai_cluster/logs/router_v14.log | tail -3"
