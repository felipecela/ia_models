cd ~/ai_cluster

# 1. Copiar los tres archivos descargados al directorio
cp ~/Downloads/proxy_v23_patch.py ~/ai_cluster/omen_router_modules/
cp ~/Downloads/orchestrator_v22_patch.py ~/ai_cluster/
cp ~/Downloads/apply_v23_fix.sh ~/ai_cluster/

# 2. Aplicar todo de una vez
bash apply_v23_fix.sh

# 3. Verificar que ya no hay 400
grep -E "400|V23-S1|PROXY" ~/ai_cluster/logs/router_v14.log | tail -10
