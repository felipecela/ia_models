#!/bin/bash

# 1. Backup
cp ~/ai_cluster/orchestrator_router_V14.py \
   ~/ai_cluster/orchestrator_router_V14.py.bak_v22

# 2. Edición quirúrgica con sed (dos líneas)
sed -i \
  's/body = inject_opciones_extra(body, nivel)$/body = inject_opciones_extra(body, nivel, body["model"])  # [V23-O1]/' \
  ~/ai_cluster/orchestrator_router_V14.py

sed -i \
  's/check_tools(body, nivel, body\["model"\])$/body = check_tools(body, nivel, body["model"])  # [V23-C1]/' \
  ~/ai_cluster/orchestrator_router_V14.py

# 3. Verificar que los cambios se aplicaron
grep -n "inject_opciones_extra\|check_tools" ~/ai_cluster/orchestrator_router_V14.py | grep -v "^.*#.*import\|from "

# 4. Reiniciar solo el router (sin necesidad de bajar el cluster entero)
kill $(cat ~/ai_cluster/router_v14.pid) && sleep 2
nohup python3 ~/ai_cluster/orchestrator_router_V14.py \
  >> ~/ai_cluster/logs/router_v14.log 2>&1 &
echo $! > ~/ai_cluster/router_v14.pid

# 5. Confirmar que el router arrancó limpio
sleep 3 && tail -5 ~/ai_cluster/logs/router_v14.log
