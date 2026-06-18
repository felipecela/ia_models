# 1. Backup del original
cp ~/ai_cluster/omen_router_modules/proxy.py \
   ~/ai_cluster/omen_router_modules/proxy.py.bak_v21

# 2. Sustituir por la versión V22
cp ~/Downloads/proxy_v22.py \
   ~/ai_cluster/omen_router_modules/proxy.py

# 3. Verificar sintaxis
python3 -m py_compile ~/ai_cluster/omen_router_modules/proxy.py \
  && echo "OK" || echo "ERROR"

# 4. Reiniciar el router
kill $(cat ~/ai_cluster/router_v14.pid)
sleep 2
nohup python3 ~/ai_cluster/orchestrator_router_V14.py \
  >> ~/ai_cluster/logs/router_v14.log 2>&1 &
