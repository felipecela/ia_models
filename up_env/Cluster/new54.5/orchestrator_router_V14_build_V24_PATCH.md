El análisis externo era completamente correcto y ha identificado dos bugs reales que **no** estaban cubiertos por V23. Aquí tienes el build V24 con todo resuelto. 

## Qué se ha corregido en V24

### [V24-P1] — Doble generación en streaming (impacto crítico en MASIVO)

Este era el problema de rendimiento más serio. El código anterior hacía **dos llamadas HTTP completas** a Ollama por cada request en streaming: 

```python
# ❌ V21/V22/V23 — Ollama generaba la respuesta ENTERA dos veces
resp_check = await http_client.post(target_url, json=body, stream=True)  # 1ª generación completa, descartada
async with http_client.stream("POST", target_url, ...) as resp:           # 2ª generación completa
```

El fix usa una sola conexión `stream()`. El status HTTP llega **con las cabeceras**, antes de consumir el body, así que el error 400/5xx se puede detectar sin disparar ninguna generación de tokens: 

```python
# ✅ V24 — una sola conexión, cero generación duplicada
async with http_client.stream("POST", target_url, json=body, ...) as resp:
    if resp.status_code >= 400:
        error_text = await resp.aread()  # Solo lee el error, sin generar tokens
        return JSONResponse(...)
    async for chunk in resp.aiter_bytes():  # Stream directo al cliente
        yield chunk
```

En `qwen2.5:32b` con respuestas largas esto puede reducir el tiempo de respuesta **a la mitad**.

### [V24-D1] — Log DEBUG restaurado en `sanitize_for_ollama()`

En V22 se eliminó el log de campos que llegaban en el body (el `[DBG] CAMPOS=...` del V21). Ahora está de vuelta como `log.debug()`, silencioso en producción pero visible con `--log-level debug`: 

```python
log.debug(f"[V24-D1] body_campos={campos} | non_msg={...}")
```

### [V24-VS] — Version strings sincronizadas

Las 5 ocurrencias donde el código seguía diciendo `V21`/`14.21.0` quedan actualizadas a `14.24.0` en todos los puntos: banner de lifespan, `FastAPI(version=...)`, `raiz()`, `/health`. 

## Despliegue

```bash
# Reemplazar los dos archivos
cp orchestrator_router_V14.py ~/ai_cluster/orchestrator_router_V14.py
cp proxy_v24.py ~/ai_cluster/omen_router_modules/proxy.py

# Reiniciar router
kill $(cat ~/ai_cluster/router_v14.pid)
cd ~/ai_cluster && python3 orchestrator_router_V14.py &

# Verificar build
curl -s http://localhost:8000/ | python3 -m json.tool | grep -E "build|version"
# Esperado: "build": "V24", "version": "14.24.0"

# Test con tools de agente (la prueba real)
curl -s http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"masivo","stream":true,"messages":[{"role":"user","content":"test"}],"tools":[{"function":{"name":"test_fn","description":"test"}}],"stream_options":{"include_usage":true}}'
# No debe aparecer ningún HTTP 400 en logs
```
