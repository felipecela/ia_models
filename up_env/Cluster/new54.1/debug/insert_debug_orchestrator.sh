#!/bin/bash

# Añadir una línea de debug al orquestador (sin reiniciar el cluster entero)
cd ~/ai_cluster

# 1. Backup
cp orchestrator_router_V14.py orchestrator_router_V14.py.bak_debug

# 2. Insertar log del body completo (excepto messages para no saturar el log)
python3 -c "
import re, os
path = os.path.expanduser('~/ai_cluster/orchestrator_router_V14.py')
with open(path) as f: src = f.read()
OLD = '        body = await request.json()\n'
NEW = ('        body = await request.json()\n'
       '        import json as _j\n'
       '        log.warning(\"[DBG] CAMPOS=\" + str(list(body.keys())) + \" | NON-MSG=\" + _j.dumps({k:v for k,v in body.items() if k!=\"messages\"})[:800])\n')
if OLD in src:
    src = src.replace(OLD, NEW, 1)
    open(path,'w').write(src)
    print('OK - debug insertado')
else:
    print('WARN - anchor no encontrado')
    import subprocess
    print(subprocess.check_output(['grep','-n','body = await request.json',path]).decode())
"

# 3. Reiniciar solo el router
kill $(cat ~/ai_cluster/router_v14.pid) && sleep 2
nohup python3 ~/ai_cluster/orchestrator_router_V14.py \
  >> ~/ai_cluster/logs/router_v14.log 2>&1 &
echo $! > ~/ai_cluster/router_v14.pid && sleep 3

# 4. Confirmar arranque
tail -3 ~/ai_cluster/logs/router_v14.log
