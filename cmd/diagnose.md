Ejecuta en la máquina real estas comprobaciones:

docker ps --filter name=chromadb --format '{{.Names}} {{.Ports}}'
docker logs chromadb --tail 50
curl -Is http://127.0.0.1:8001/api/v2/heartbeat
docker exec chromadb curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/api/v2/heartbeat





curl -v http://127.0.0.1:8001/api/v2/heartbeat || true
docker exec chromadb python3 -c "import urllib.request; \
print(urllib.request.urlopen('http://127.0.0.1:8000/api/v2/heartbeat', timeout=3).getcode())" 2>/dev/null || \
docker exec chromadb python -c "import urllib.request; \
print(urllib.request.urlopen('http://127.0.0.1:8000/api/v2/heartbeat', timeout=3).getcode())" 2>/dev/null || echo INTERNAL_CHECK_FAILED




docker ps --filter name=chromadb --format '{{.Names}} {{.Ports}}'
docker logs chromadb --tail 200
curl -v http://127.0.0.1:8001/api/v2/heartbeat || true
docker run --rm --network ai_net curlimages/curl:latest -v --connect-timeout 5 --ipv4 http://chromadb:8000/api/v2/heartbeat || true





Se ha agregado una tarea pendiente

Diagnóstico rápido: ChromaDB responde correctamente en la red Docker (http://chromadb:8000 → 200) pero las conexiones al puerto publicado en el host 127.0.0.1:8001 se reinician (connection reset). Eso confirma que el servicio en el contenedor está OK y que el problema es el forwarding/puente en el host (docker-proxy, firewall o reglas NAT).

Por favor ejecuta estos comandos y pega las salidas (ayudará a identificar el responsable):

1) Ver quién escucha el puerto y qué proceso lo gestiona:
```bash
ss -tlnp | grep ':8001 ' || true
sudo lsof -nP -iTCP:8001 -sTCP:LISTEN || true
ps aux | grep -E 'docker-proxy|docker-proxy' || true
```

2) Inspeccionar la inspección del contenedor y puertos Docker:
```bash
docker ps --filter name=chromadb --format '{{.Names}} {{.Ports}}'
docker inspect chromadb --format '{{json .NetworkSettings}}' | jq . || docker inspect chromadb
```

3) Revisar logs del motor Docker y de docker-proxy (necesita sudo):
```bash
sudo journalctl -u docker.service --no-pager -n 200 | sed -n '1,200p'
sudo journalctl --no-pager | grep -i docker-proxy -n || true
```

4) Verificar reglas NAT / firewall:
```bash
sudo iptables -t nat -L -n -v | sed -n '1,200p'
sudo iptables -L -n -v | sed -n '1,200p'
sudo nft list ruleset 2>/dev/null || true
```

5) Prueba alternativa rápida (desde host y desde Docker net, ya la hiciste — repite si quieres):
```bash
curl -v http://127.0.0.1:8001/api/v2/heartbeat || true
docker run --rm --network ai_net curlimages/curl:latest -v --connect-timeout 5 --ipv4 http://chromadb:8000/api/v2/heartbeat || true
```

Sugerencias inmediatas según resultados:

- Si `ss` / `lsof` muestra `docker-proxy` o un PID extraño que no responde, pega el PID y haré los siguientes pasos (ver logs de ese PID).
- Si `journalctl` muestra errores de docker-proxy o fallos de bind, puede que haya un fallo del binario docker-proxy; reiniciar Docker (`sudo systemctl restart docker`) puede arreglarlo temporalmente.
- Si las reglas NAT/iptables mencionan REMAP a 8001 pero la conexión se resetea, revisa si hay algún servicio local (fail2ban, nftables) que esté bloqueando.
- Mitigación temporal para restaurar servicio rápido: ejecutar ChromaDB con `--network host` y ajustar la URL a `http://localhost:8000` para pruebas (no recomendado en producción). Puedo darte el comando si quieres probarlo.

Dime si quieres que te indique exactamente qué líneas mirar en las salidas o si quieres que prepare un comando único que recolecte todo en un archivo que pegues aquí.


---


Compacted conversationVoy a actualizar la lista de tareas y proponer pasos concretos para rastrear por qué docker-proxy está reiniciando la conexión. Luego te doy los comandos a ejecutar.

Lista de tareas pendientes actualizada

Progreso: marco “Diagnosticar host port forwarding” como in-progress y anoto siguientes pasos para el diagnóstico.

Pasos recomendados (en orden) — ejecútalos y pega los resultados:

1) Capturar tráfico TCP para ver quién envía RST (captura en loopback y en la bridge Docker)
```bash
sudo tcpdump -n -s 0 -i lo tcp port 8001 -w /tmp/port8001-lo.pcap &
sudo tcpdump -n -s 0 -i br-7a7a1e350686 tcp port 8001 -w /tmp/port8001-br.pcap &
# reproduce el curl que falla
curl -v http://127.0.0.1:8001/api/v2/heartbeat || true
# detener capturas
sudo pkill -f "tcpdump -n -s 0 -i lo tcp port 8001" || true
sudo pkill -f "tcpdump -n -s 0 -i br-7a7a1e350686 tcp port 8001" || true
# inspección rápida (muestra paquetes con RST)
sudo tcpdump -nn -r /tmp/port8001-lo.pcap 'tcp[tcpflags] & (tcp-rst) != 0' -c 20
sudo tcpdump -nn -r /tmp/port8001-br.pcap 'tcp[tcpflags] & (tcp-rst) != 0' -c 20
```

2) Hacer strace a docker-proxy (ver qué hace al aceptar/reenviar)
```bash
# reemplaza PID por el que tengas (382941 y 382948)
sudo strace -ff -p 382941 -s 200 -o /tmp/docker-proxy-strace.log &
# reproduce el curl que falla
curl -v http://127.0.0.1:8001/api/v2/heartbeat || true
# parar strace
sudo pkill -f "strace -ff -p 382941" || true
# luego revisa /tmp/docker-proxy-strace.log*
```

3) Revisar estado conntrack y conexiones TCP activas
```bash
sudo conntrack -L | grep 8001 || true
ss -tnp state all '( sport = :8001 or dport = :8001 )' || ss -tnp | grep 8001 || true
```

4) Comprobar si el RST viene del host o del contenedor (captura específica de RST)
```bash
sudo tcpdump -nn -i any 'tcp port 8001 and tcp[tcpflags] & (tcp-rst) != 0' -c 10 -w /tmp/rst.pcap
# reproduce curl una vez
curl -v http://127.0.0.1:8001/api/v2/heartbeat || true
sudo tcpdump -nn -r /tmp/rst.pcap -vv
```

5) Recopilar diagnósticos mínimos ya vistos (si no los pegaste aún)
```bash
ps -ef | grep docker-proxy
sudo lsof -nP -iTCP:8001 -sTCP:LISTEN
docker inspect chromadb --format '{{json .NetworkSettings}}' | jq .
sudo iptables -t nat -L DOCKER -n -v
sudo nft list ruleset
sudo journalctl -u docker.service --since "5 minutes ago" | tail -n 200
dmesg | tail -n 50
```

6) Prueba temporal de workaround (si quieres confirmar): ejecutar Chroma con host networking (evita docker-proxy)
- Si puedes parar el servicio y lanzar temporalmente, úsalo para confirmar que el servicio responde desde host:
```bash
# parar contenedor actual (opcional, haz backup)
docker stop chromadb
# lanzar temporal con network host (asegúrate de usar la imagen correcta y volúmenes)
docker run --rm -e CHROMA_SERVER_HOST=0.0.0.0 -v chroma_data:/data --network host ghcr.io/chroma-core/chroma:latest
# luego desde host:
curl -v http://127.0.0.1:8000/api/v2/heartbeat
```
(si esto funciona, confirma que el problema es del docker-proxy/forwarding)

7) Si prefieres intentar una reparación breve (después de recolectar logs): reinicia Docker y vuelve a probar
```bash
sudo systemctl restart docker
# después esperar 5s y probar
curl -v http://127.0.0.1:8001/api/v2/heartbeat || true
```
(reiniciar Docker afectará otros contenedores; hazlo cuando sea aceptable)

Qué recoger y pegar aquí:
- Salida de las tcpdump quick-inspections que muestren paquetes RST (los tcpdump -nn -r ... con -vv).
- Fragmentos relevantes de /tmp/docker-proxy-strace.log (errores, accept, read, write, sendto, close).
- Salida de `conntrack -L | grep 8001` y de `ss -tnp` alrededor del intento.
- Resultado de `dmesg | tail` y `journalctl` si aparecen mensajes de kernel o docker.
- Resultado del test con `--network host` si lo pruebas.

Siguiente paso mío cuando pegues esos resultados: interpretar quién envía el RST y propondré la acción definitiva (ajuste iptables/nft, reinicio Docker, parchear docker-proxy o usar workaround estable).


---


docker stop chromadb 2>/dev/null; docker rm chromadb 2>/dev/null
docker rmi ghcr.io/chroma-core/chroma:latest 2>/dev/null; true


---


# 1. Estado real del contenedor
docker ps -a --filter name=chromadb --format "table {{.Names}}\t{{.Status}}\t{{.Image}}"

# 2. Últimos logs (el crash real estará aquí)
docker logs chromadb --tail 50 2>&1

# 3. Cuántas veces ha reiniciado
docker inspect chromadb --format '{{.RestartCount}} reinicios — Estado: {{.State.Status}} — ExitCode: {{.State.ExitCode}}'

# 4. Qué tiene el volumen (posible corrupción)
docker run --rm -v chromadbdata:/data alpine ls -la /data/

# 5. El curl con verbose completo
curl -v --max-time 5 http://127.0.0.1:8001/api/v1/heartbeat 2>&1


---


# IP directa del contenedor (sin docker-proxy)
CHROMA_IP=$(docker inspect chromadb --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}')
echo "IP del contenedor: $CHROMA_IP"
curl -v http://${CHROMA_IP}:8000/api/v1/heartbeat 2>&1


# Ver la regla DNAT exacta para ChromaDB
sudo iptables -t nat -L DOCKER -n -v | grep 8001

# Ver la regla de RAW que mencionaste antes (¡clave!)
sudo iptables -t raw -L PREROUTING -n -v | grep 172.28

# Intentar desde dentro de la red Docker (bypasando todo el NAT del host)
docker run --rm --network ai_net curlimages/curl:latest \
  curl -s http://chromadb:8000/api/v1/heartbeat
  
  
---


# Ver todas las reglas RAW (la causa probable)
sudo iptables -t raw -L -n -v

# Si aparece una regla DROP para 172.28.0.6, elimínala así:
CHROMA_IP=$(docker inspect chromadb --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}')
sudo iptables -t raw -D PREROUTING -d ${CHROMA_IP} ! -i br-7a7a1e350686 -j DROP 2>/dev/null && echo "Regla eliminada" || echo "Regla no encontrada"

# Verificar inmediatamente
sleep 1
curl -s http://127.0.0.1:8001/api/v1/heartbeat


---


# Eliminar TODAS las reglas DROP de iptables raw PREROUTING de una vez
sudo iptables -t raw -F PREROUTING

# Verificar que están limpias
sudo iptables -t raw -L PREROUTING -n -v

# Probar inmediatamente
curl -s http://127.0.0.1:8001/api/v1/heartbeat


---


# Al inicio del script, después de crear la red Docker:
# Limpiar reglas RAW que bloquean el forwarding del docker-proxy
sudo iptables -t raw -F PREROUTING 2>/dev/null || true
info "Reglas iptables RAW limpiadas (compatibilidad docker-proxy)"


---


# Eliminar la regla restante
sudo iptables -t raw -F PREROUTING

# Confirmar que está completamente vacío
sudo iptables -t raw -L PREROUTING -n

# Verificar IP actual del contenedor
docker inspect chromadb --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}'

# Probar con verbose completo
curl -v --max-time 5 http://127.0.0.1:8001/api/v1/heartbeat 2>&1

# Si sigue fallando, probar directamente a la IP del contenedor (sin escapes)
CHOST=$(docker inspect chromadb --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}')
curl -v --max-time 5 http://$CHOST:8000/api/v1/heartbeat 2>&1


---


# El router arranca solo en ai_net (como ahora)
# Después del arranque, lo conectas también a ai_backend:
docker network connect "${DOCKER_NET_BACKEND}" <router_container_name>

# O si el router corre como proceso Python en el host (no como contenedor),
# el acceso a ai_backend lo consigues con una regla específica y explícita:
sudo ip route add 172.29.0.0/24 via $(docker network inspect ai_backend \
    --format '{{range .IPAM.Config}}{{.Gateway}}{{end}}')
    
    
---


# Crear la red backend
docker network create --driver bridge --subnet 172.29.0.0/24 ai_backend

# Conectar el ChromaDB actual a la nueva red
docker network connect ai_backend chromadb

# Probar desde otro contenedor en la misma red (sin pasar por el host)
docker run --rm --network ai_backend curlimages/curl:latest \
    curl -s http://chromadb:8000/api/v1/heartbeat
# Esperado: {"nanosecond heartbeat": ...}


---


# 1. Ver qué reglas DOCKER tiene iptables para el puerto 8001
sudo iptables -t nat -L DOCKER -n --line-numbers | grep 8001

# 2. Ver si hay paquetes INVALID siendo DROPeados o RSTeados
sudo iptables -t filter -L INPUT -n -v | head -20

# 3. Ver la tabla DOCKER-USER (puede tener reglas que bloqueen)
sudo iptables -t filter -L DOCKER-USER -n -v

# 4. Ver el estado conntrack para el puerto 8001
sudo conntrack -L 2>/dev/null | grep 8001

# 5. Verificar qué proceso tiene abierto el puerto 8001 en el host
ss -tlnp | grep 8001


---


# Fix 1: Limpiar entradas conntrack corruptas del puerto 8001
sudo conntrack -D -p tcp --dport 8001 2>/dev/null || true
sudo conntrack -D -p tcp --sport 8001 2>/dev/null || true

# Fix 2: Añadir regla para DROP (no RST) de paquetes INVALID antes de que lleguen al DNAT
sudo iptables -I INPUT 1 -m conntrack --ctstate INVALID -j DROP

# Fix 3: Verificar que la regla DNAT existe correctamente
sudo iptables -t nat -L DOCKER -n | grep 8001


curl -v http://127.0.0.1:8001/api/v1/heartbeat


---


# 1. Ver las reglas LIBVIRT en FORWARD (aquí está el conflicto)
sudo iptables -t filter -L LIBVIRT_FWD -n -v 2>/dev/null || \
sudo iptables -t filter -L LIBVIRT_FWO -n -v 2>/dev/null

# 2. Ver la cadena FORWARD completa
sudo iptables -t filter -L FORWARD -n -v

# 3. Ver si docker-proxy está activo (userspace proxy)
ps aux | grep docker-proxy | grep 8001

# 4. Verificar la configuración del daemon Docker
cat /etc/docker/daemon.json 2>/dev/null || echo "(no existe daemon.json)"

# 5. Test directo: conectar directamente a la IP del contenedor (sin DNAT)
CHROMA_IP=$(docker inspect -f '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}' chromadb)
echo "IP del contenedor: $CHROMA_IP"
curl -v "http://${CHROMA_IP}:8000/api/v1/heartbeat"


---


# 1. ¿Existe la interfaz bridge de ai_net y está UP?
ip link show | grep -A1 "br-"

# 2. ¿Tiene ruta en la tabla de routing?
ip route show | grep 172.28

# 3. Ver la interfaz concreta de ai_net
docker network inspect ai_net | grep -E '"Interface"|"Subnet"|"Gateway"|"Driver"'

# 4. ¿El bridge tiene IP asignada?
ip addr show | grep -A3 "172.28"

# 5. ¿ip_forward está activo?
cat /proc/sys/net/ipv4/ip_forward


---


# ¿Qué red Docker es br-7a7a1e350686?
docker network ls
docker network inspect $(docker network ls -q) | grep -A5 '"Id"' | grep -E "Name|br-7a7a1e"

# ¿A qué red está conectado chromadb realmente?
docker inspect chromadb | grep -A10 "Networks"


---


docker network ls --no-trunc | grep 3c69ec1252b9

# Eliminar la interfaz huérfana (no toca ai_net ni ningún contenedor)
sudo ip link delete br-3c69ec1252b9


ip route show | grep 172.28
# Debe quedar solo UNA ruta, sin "linkdown"

curl -s http://127.0.0.1:8001/api/v1/heartbeat
# Debe devolver {"nanosecond heartbeat": ...}


---


Antes de tocar nada, necesito ver el estado real de la RAM. Para diagnosticar bien, ejecuta estos dos comandos y pégame la salida:

```bash
free -h && echo "---" && docker stats --no-stream --format "table {{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.CPUPerc}}"
```

```bash
cat /proc/meminfo | grep -E "MemTotal|MemFree|MemAvailable|Cached|Buffers|SwapTotal|SwapFree|Dirty|Writeback|Shmem"
```

Esos dos comandos me darán:
1. **Cuánta RAM total/libre/disponible** tiene el sistema en este momento
2. **Cuánta RAM consume exactamente cada contenedor Docker** (Ollama GPU, Ollama CPU, TabbAPI, ChromaDB, etc.)
3. **Si hay swap activo** y si está siendo usado (señal clara de presión de memoria real)
4. **Cuánta RAM es "cache recuperable"** por el kernel (que aparece como usada pero es liberable)

Con eso podré decirte si el problema es:
- RAM realmente agotada por los modelos cargados
- RAM bloqueada por contenedores de los ciclos de crash anteriores de SGLang
- Cache del kernel inflado y recuperable
- Swap paginando en disco (que explicaría lentitud aunque "haya" RAM)

El hecho de que la VRAM figure en 674 MiB de 7.5 GB libres con Ollama y TabbAPI activos ya me dice que TabbAPI está consumiendo alrededor de 5-6 GB de VRAM, que es coherente con `llama-3.1-8b-exl2`. El problema de RAM del sistema podría ser independiente de eso o consecuencia acumulada de los reinicios fallidos de SGLang, que cargaba pesos en RAM de sistema antes de fallar. Necesito los números reales antes de proponer cualquier corrección.


---


Para poder generar el V28 sin regresiones en TabbAPI necesito saber cómo era exactamente el docker run de TabbyAPI en la versión que te funcionaba. ¿Puedes pasarme el output de:

```bash
docker inspect exllamav2-api --format '{{json .Config.Cmd}}' 2>/dev/null || \
docker run --rm ghcr.io/theroyallab/tabbyapi:latest --help 2>&1 | head -20
```


# 1. Comprueba si el contenedor está vivo
docker ps -f name=exllamav2-api

# 2. Mira los logs del contenedor para ver por qué falla al cargar
docker logs exllamav2-api --tail 50


---


qué subcomandos reales soporta la CLI de tu build y qué config final queda tras el arranque:

bash
docker exec openclaw-server sh -lc 'openclaw --help | sed -n "1,120p"'
bash
docker exec openclaw-server sh -lc 'cat /data/.openclaw/openclaw.json'


---


Necesito ver el Router V14 para aplicarlos correctamente. Ejecuta este comando y pégame la salida:

bash
# Ver qué parámetros usa el Router al llamar a Ollama
grep -n "think\|context\|num_ctx\|options\|max_tokens\|tools" \
  ~/ai_cluster/orchestrator_router_V14.py | head -60
Y también:

bash
# Ver el endpoint /v1/chat/completions del Router
grep -n "def.*chat\|completions\|forward\|backend\|proxy" \
  ~/ai_cluster/orchestrator_router_V14.py | head -40
  
  
Cómo obtener el log del router en tiempo real
Para la próxima vez que quieras pasarme más información:

bash
# Log en tiempo real del router (incluye todos los 400 con detalle):
tail -f ~/ai_cluster/logs/router_v14.log

# Ver los últimos errores específicos de los modelos:
grep -i "400\|error\|think\|tools\|rejected" ~/ai_cluster/logs/router_v14.log | tail -30

# Log del contenedor OpenClaw con los runId y errores de agente:
docker logs openclaw-server --since 10m 2>&1 | grep -E "error|400|rejected|runId"


Para confirmar en tiempo real que el fix está funcionando, puedes observar los logs mientras escribes:

bash
tail -f ~/ai_cluster/logs/router_v14.log


# Verificar build
curl -s http://localhost:8000/ | python3 -m json.tool | grep -E "build|version"
# Esperado: "build": "V24", "version": "14.24.0"

# Test con tools de agente (la prueba real)
curl -s http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"masivo","stream":true,"messages":[{"role":"user","content":"test"}],"tools":[{"function":{"name":"test_fn","description":"test"}}],"stream_options":{"include_usage":true}}'
# No debe aparecer ningún HTTP 400 en logs


---


## Comandos que te pediría ejecutar ahora

Si quieres, con estas salidas te digo exactamente qué parche aplicar.

### 1) Ver si OpenClaw sigue arrancando con providers no deseados

```bash
docker exec openclaw-server sh -lc 'env | egrep "OPENAI|OLLAMA|OPENCLAW" | sort'
```

### 2) Ver la config real que OpenClaw está usando tras el inject

```bash
docker exec openclaw-server python3 - <<'PY'
import json
p="/data/.openclaw/openclaw.json"
with open(p) as f:
    d=json.load(f)
print("providers =", list(d.get("models", {}).get("providers", {}).keys()))
print("primary   =", d.get("agents", {}).get("defaults", {}).get("model", {}).get("primary"))
for k,v in d.get("models", {}).get("providers", {}).items():
    print(k, "baseUrl=", v.get("baseUrl"), "models=", len(v.get("models", [])))
PY
```

### 3) Confirmar el patrón de timeout en vivo

```bash
tail -n 120 /home/fcela-ga/ai_cluster/logs/router_v14.log
```

### 4) Ver métricas del router después de reproducir el fallo una vez

```bash
curl -s http://localhost:8000/metrics | python3 -m json.tool
```

### 5) Hacer una prueba mínima directa al router, sin pasar por OpenClaw

```bash
curl -s http://localhost:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model":"masivo",
    "stream":false,
    "messages":[{"role":"user","content":"hola"}]
  }' | python3 -m json.tool
```

Si esta prueba directa funciona y desde OpenClaw falla, quedará prácticamente confirmado que **el inflado lo introduce OpenClaw**.

### 6) Ver logs recientes de OpenClaw

```bash
docker logs --tail 200 openclaw-server
```


---


Nueva evidencia clave: `masivo` falla también con `curl` directo

Este comando directo:

```bash
curl -s http://localhost:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model":"masivo",
    "stream":false,
    "messages":[{"role":"user","content":"hola"}]
  }' | python3 -m json.tool
```


### A. Probar Ollama directo con `qwen2.5:32b`, 1 token, contexto pequeño

```bash
time curl --max-time 60 -s http://127.0.0.1:11434/api/chat \
  -H 'Content-Type: application/json' \
  -d '{
    "model":"qwen2.5:32b",
    "stream":false,
    "messages":[{"role":"user","content":"hola"}],
    "options":{"num_predict":1,"num_ctx":2048}
  }'
```

Si esto tarda mucho o no responde, `MASIVO` queda confirmado como no viable para chat interactivo.

### B. Probar una ruta ligera del router

```bash
time curl --max-time 60 -s http://localhost:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model":"chat",
    "stream":false,
    "messages":[{"role":"user","content":"hola"}],
    "max_tokens":64
  }'
```

Si `chat` responde y `masivo` no, el router funciona y el problema está concentrado en la ruta pesada.


Mientras corre la prueba de `masivo`:

```bash
watch -n 1 'nvidia-smi; echo; docker logs --tail 30 ollama-gpu-main'
```

Si ves VRAM llena, offload, carga prolongada o ausencia de tokens, ya tenemos la raíz operativa.


---


Comprueba:

```bash
docker exec openclaw-server sh -lc 'env | egrep "OPENAI|OLLAMA|OPENCLAW" | sort'
```

Esperado:

```text
OPENCLAW_GATEWAY_TOKEN=...
```

Idealmente ya **sin** `OLLAMA_BASE_URL`.

Luego:

```bash
docker logs --tail 80 openclaw-server
```

Ya no debería arrancar como:

```text
agent model: ollama/llama3.3
```

Y finalmente:

```bash
curl -s http://localhost:8000/metrics | python3 -m json.tool
```



