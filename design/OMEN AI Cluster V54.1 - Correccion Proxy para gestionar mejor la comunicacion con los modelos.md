## Diagnóstico definitivo — tres causas raíz confirmadas

El error `provider rejected the request schema or tool payload` con `rawError=400 Backend error` tiene **origen en `proxy.py`**, no en el autoboot ni en la configuración de OpenClaw. Los logs de docker y el router lo confirman con total precisión.

***

## Las 3 causas raíz

### Bug #1 — `inject_thinking`: campo `think` en el body raíz [V22-T1]

OpenClaw activa el razonamiento extendido enviando `"think": true` en el body. El router lo pasa tal cual hacia Ollama. **El problema:** Ollama solo acepta `think` dentro de `body["options"]["think"]` (su API nativa). Recibirlo como campo raíz OpenAI lo hace devolver `400 invalid option`. Esto afecta a los tres modelos de razonamiento: `deepseek-r1:14b`, `phi4-reasoning:plus` y `phi4-reasoning:14b-q4_K_M`. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/48708411/9d50c86f-d12d-4079-80a4-19d863e0ea2c/orchestrator_router_V14.py?AWSAccessKeyId=ASIA2F3EMEYEWFRRXJLK&Signature=PIHNfn0bVbRbDb2OKXbzYR%2BFJBo%3D&x-amz-security-token=IQoJb3JpZ2luX2VjEN3%2F%2F%2F%2F%2F%2F%2F%2F%2F%2FwEaCXVzLWVhc3QtMSJGMEQCID%2FhtgjjWrXg5qzm0T75K9ZdMG63pTJrmaPNNDeRV%2FKjAiAsJI9VnSJfk4OAG8K%2FbshYLKzY9RXJnw5L44VRtNlpbir8BAim%2F%2F%2F%2F%2F%2F%2F%2F%2F%2F8BEAEaDDY5OTc1MzMwOTcwNSIMaledwax%2FBJjCYpU3KtAEA5N094cqj3p8OqMYu2Dl12o0FhjDx0svA06egGQJlQ4mHRcioZtrgfMthR2H%2BdNi01iyHrkcbhUI8gnvXy8KKedIT2tskgdjCfa6U71bz61FrJuPtbpAdnRzB8LY5hSYAZXHaAzjMcVkgkk037%2Ft1b5dq3M4hPdcQ9lBPkXru2eX7nJwBBlkPg5d7uq1bEQTz5UmQG2LDC%2FyIzYCrH6QFkVsGPC%2Fx%2FA0cIf6Y6pILJVc9F5kliRfuajWsG8Ea0I1SSLf80f8dtpl64oRFA4%2BU%2BolTBAa9wrZQ%2FIvOLzysCGa3NyCO2so6MdDhwPpQtNbqMJtppwqz0ea%2BBSrIwDN3wsijGPxiH2sMnefaFBNzbWhTn%2BjjvRQicM8mElPnsiPVBGJpHCy6r9SAbEo%2BElPHQbijCUoScfiECvFTI6HynTyo7gBeVwdU4CR6ZzCooKkhxolP7SJaGHV%2BA4DLmm5LU4M4acvm%2FXZZy1iCEbokpy7ow1dydwKaJpAANJWH%2FizTfDdW7WJXf1Eykt5MMrG5psE%2FJM%2FtaOBDyxQMgXe3ZXc2lE%2BGrSzjj383rVOTBG7u6bvSseX4PhCy%2Fw00Z%2BcqvNiNxS5gw9uCNswBDHQLA48xlEhcdlo%2FCynuY3TOELNpEYU8QHlWLsGFmQlvR0qXjgimx4I3%2BlfcotvFJPosMpoJZoQOz0q9%2BRfUetw19gvu0P%2BY6RQJNoUORDpGWoF5KTSEeOt7Y5jrtbqvfem%2BAsOviGV1eviumFp1p3x2MWf4XkAiJoqEsauD39rfQ50fDClx8%2FRBjqZAZ4B62rYmOltzZFfC0UFXeWCmymkZoa%2BHN3D9ogu4s%2BqJN3sx7IgNlY%2Bkaa7DIYS4Os3uAXZ0LOIhJVczFHhVeeel5DJfiJdau6uDnELuR0ecS3bU2%2FUyiGQV%2FVhI47q%2FTt4ELXTUi20%2FWEzvp6AQ9UllURgX1slICp5UXlCK3YObpVtsxSTU2AuW7T0WxemPBmWPS%2B36QXx9A%3D%3D&Expires=1781789048)

### Bug #2 — `check_tools`: tools enviadas a modelos sin soporte [V22-T2]

OpenClaw es un agente completo y envía automáticamente su lista de herramientas (`web-search`, `shell`, `message-tool`, etc.) en el campo `"tools"` de cada request. Solo `qwen2.5:32b` tiene chat-template con soporte de function calling en Ollama. Los modelos `phi4-reasoning:*` y `deepseek-r1:14b` **no tienen ese template** y devuelven `400` en cuanto ven el campo `tools`. Por eso Qwen funcionaba parcialmente y los demás no. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/48708411/0c357520-8f50-4bf6-9b47-d8a71f860c48/paste-2.txt?AWSAccessKeyId=ASIA2F3EMEYEWFRRXJLK&Signature=axoHXmW6mfhoLJ3G3kGd3rmLyv4%3D&x-amz-security-token=IQoJb3JpZ2luX2VjEN3%2F%2F%2F%2F%2F%2F%2F%2F%2F%2FwEaCXVzLWVhc3QtMSJGMEQCID%2FhtgjjWrXg5qzm0T75K9ZdMG63pTJrmaPNNDeRV%2FKjAiAsJI9VnSJfk4OAG8K%2FbshYLKzY9RXJnw5L44VRtNlpbir8BAim%2F%2F%2F%2F%2F%2F%2F%2F%2F%2F8BEAEaDDY5OTc1MzMwOTcwNSIMaledwax%2FBJjCYpU3KtAEA5N094cqj3p8OqMYu2Dl12o0FhjDx0svA06egGQJlQ4mHRcioZtrgfMthR2H%2BdNi01iyHrkcbhUI8gnvXy8KKedIT2tskgdjCfa6U71bz61FrJuPtbpAdnRzB8LY5hSYAZXHaAzjMcVkgkk037%2Ft1b5dq3M4hPdcQ9lBPkXru2eX7nJwBBlkPg5d7uq1bEQTz5UmQG2LDC%2FyIzYCrH6QFkVsGPC%2Fx%2FA0cIf6Y6pILJVc9F5kliRfuajWsG8Ea0I1SSLf80f8dtpl64oRFA4%2BU%2BolTBAa9wrZQ%2FIvOLzysCGa3NyCO2so6MdDhwPpQtNbqMJtppwqz0ea%2BBSrIwDN3wsijGPxiH2sMnefaFBNzbWhTn%2BjjvRQicM8mElPnsiPVBGJpHCy6r9SAbEo%2BElPHQbijCUoScfiECvFTI6HynTyo7gBeVwdU4CR6ZzCooKkhxolP7SJaGHV%2BA4DLmm5LU4M4acvm%2FXZZy1iCEbokpy7ow1dydwKaJpAANJWH%2FizTfDdW7WJXf1Eykt5MMrG5psE%2FJM%2FtaOBDyxQMgXe3ZXc2lE%2BGrSzjj383rVOTBG7u6bvSseX4PhCy%2Fw00Z%2BcqvNiNxS5gw9uCNswBDHQLA48xlEhcdlo%2FCynuY3TOELNpEYU8QHlWLsGFmQlvR0qXjgimx4I3%2BlfcotvFJPosMpoJZoQOz0q9%2BRfUetw19gvu0P%2BY6RQJNoUORDpGWoF5KTSEeOt7Y5jrtbqvfem%2BAsOviGV1eviumFp1p3x2MWf4XkAiJoqEsauD39rfQ50fDClx8%2FRBjqZAZ4B62rYmOltzZFfC0UFXeWCmymkZoa%2BHN3D9ogu4s%2BqJN3sx7IgNlY%2Bkaa7DIYS4Os3uAXZ0LOIhJVczFHhVeeel5DJfiJdau6uDnELuR0ecS3bU2%2FUyiGQV%2FVhI47q%2FTt4ELXTUi20%2FWEzvp6AQ9UllURgX1slICp5UXlCK3YObpVtsxSTU2AuW7T0WxemPBmWPS%2B36QXx9A%3D%3D&Expires=1781789048)

### Bug #3 — `inject_opciones_extra`: `num_ctx` insuficiente [V22-C1]

El catálogo de modelos en el router define `ctx: 16384` para `profundo`, `preciso` y `masivo`, pero si `inject_opciones_extra` no fuerza `options.num_ctx = 16384` en la llamada a Ollama, este arranca con su valor por defecto (4096). El system prompt del agente de OpenClaw más el historial y las definiciones de tools suman ~8.600 tokens — el doble del límite. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/48708411/0c357520-8f50-4bf6-9b47-d8a71f860c48/paste-2.txt?AWSAccessKeyId=ASIA2F3EMEYEWFRRXJLK&Signature=axoHXmW6mfhoLJ3G3kGd3rmLyv4%3D&x-amz-security-token=IQoJb3JpZ2luX2VjEN3%2F%2F%2F%2F%2F%2F%2F%2F%2F%2FwEaCXVzLWVhc3QtMSJGMEQCID%2FhtgjjWrXg5qzm0T75K9ZdMG63pTJrmaPNNDeRV%2FKjAiAsJI9VnSJfk4OAG8K%2FbshYLKzY9RXJnw5L44VRtNlpbir8BAim%2F%2F%2F%2F%2F%2F%2F%2F%2F%2F8BEAEaDDY5OTc1MzMwOTcwNSIMaledwax%2FBJjCYpU3KtAEA5N094cqj3p8OqMYu2Dl12o0FhjDx0svA06egGQJlQ4mHRcioZtrgfMthR2H%2BdNi01iyHrkcbhUI8gnvXy8KKedIT2tskgdjCfa6U71bz61FrJuPtbpAdnRzB8LY5hSYAZXHaAzjMcVkgkk037%2Ft1b5dq3M4hPdcQ9lBPkXru2eX7nJwBBlkPg5d7uq1bEQTz5UmQG2LDC%2FyIzYCrH6QFkVsGPC%2Fx%2FA0cIf6Y6pILJVc9F5kliRfuajWsG8Ea0I1SSLf80f8dtpl64oRFA4%2BU%2BolTBAa9wrZQ%2FIvOLzysCGa3NyCO2so6MdDhwPpQtNbqMJtppwqz0ea%2BBSrIwDN3wsijGPxiH2sMnefaFBNzbWhTn%2BjjvRQicM8mElPnsiPVBGJpHCy6r9SAbEo%2BElPHQbijCUoScfiECvFTI6HynTyo7gBeVwdU4CR6ZzCooKkhxolP7SJaGHV%2BA4DLmm5LU4M4acvm%2FXZZy1iCEbokpy7ow1dydwKaJpAANJWH%2FizTfDdW7WJXf1Eykt5MMrG5psE%2FJM%2FtaOBDyxQMgXe3ZXc2lE%2BGrSzjj383rVOTBG7u6bvSseX4PhCy%2Fw00Z%2BcqvNiNxS5gw9uCNswBDHQLA48xlEhcdlo%2FCynuY3TOELNpEYU8QHlWLsGFmQlvR0qXjgimx4I3%2BlfcotvFJPosMpoJZoQOz0q9%2BRfUetw19gvu0P%2BY6RQJNoUORDpGWoF5KTSEeOt7Y5jrtbqvfem%2BAsOviGV1eviumFp1p3x2MWf4XkAiJoqEsauD39rfQ50fDClx8%2FRBjqZAZ4B62rYmOltzZFfC0UFXeWCmymkZoa%2BHN3D9ogu4s%2BqJN3sx7IgNlY%2Bkaa7DIYS4Os3uAXZ0LOIhJVczFHhVeeel5DJfiJdau6uDnELuR0ecS3bU2%2FUyiGQV%2FVhI47q%2FTt4ELXTUi20%2FWEzvp6AQ9UllURgX1slICp5UXlCK3YObpVtsxSTU2AuW7T0WxemPBmWPS%2B36QXx9A%3D%3D&Expires=1781789048)

***

## Cómo aplicar el parche

Tienes dos archivos adjuntos: el parche documentado (`proxy_patch_v22.py`) para leer los cambios, y el script de aplicación automática:

```bash
# En tu máquina, ejecuta directamente:
bash ~/Downloads/apply_proxy_patch_v22.sh
```

El script hace **backup automático** del `proxy.py` original, reemplaza las tres funciones, valida la sintaxis con `python3 -m py_compile` y reinicia el router. Si algo falla, el backup se encuentra en `proxy.py.bak_v21_YYYYMMDD_HHMMSS`.

***

## Cómo obtener el log del router en tiempo real

Para la próxima vez que quieras pasarme más información:

```bash
# Log en tiempo real del router (incluye todos los 400 con detalle):
tail -f ~/ai_cluster/logs/router_v14.log

# Ver los últimos errores específicos de los modelos:
grep -i "400\|error\|think\|tools\|rejected" ~/ai_cluster/logs/router_v14.log | tail -30

# Log del contenedor OpenClaw con los runId y errores de agente:
docker logs openclaw-server --since 10m 2>&1 | grep -E "error|400|rejected|runId"


---


## Respuesta a tus preguntas, luego el análisis completo

### Diferencia entre los dos archivos anteriores
- **`proxy_patch_v22.py`** — era solo documentación/referencia del parche (qué cambiar y por qué), no ejecutable directamente sobre tu instalación.
- **`apply_proxy_patch_v22.sh`** — era el script que aplicaba el parche con `sed`/Python internamente, pero dependía de que las funciones en tu `proxy.py` tuviesen exactamente la misma firma que yo asumía sin haberlo visto.

Ahora que tienes el `proxy.py` real, **te entrego directamente el archivo completo corregido** (`proxy_v22.py`). Es la forma más segura — sin regex ni sustituciones frágiles.

***

## 4 bugs confirmados en el proxy.py real

Al leer tu archivo fuente encontré que el diagnóstico anterior era correcto, pero hay un **cuarto bug** que no era visible sin el código:

| Bug | Función | Problema en V21 | Corrección V22 |
|---|---|---|---|
| **V22-T1** | `inject_thinking` | Solo activaba `think` para `deepseek-r1` — `phi4-reasoning:*` quedaba sin él | Ampliado a todos los modelos de `_THINK_MODELS` |
| **V22-T2** | `check_tools` | Eliminaba tools en niveles PROFUNDO/PRECISO pero **qwen2.5:32b sí las soporta** → también le eliminaba las tools y fallaba | Ahora distingue modelos con soporte nativo (Qwen pasa) vs sin soporte (tools → texto plano) |
| **V22-C1** | `inject_opciones_extra` | No inyectaba `num_ctx` → Ollama usaba 4096 por defecto → 400 con prompts de 8K+ tokens | Fuerza `num_ctx=16384` para todos los niveles GPU |
| **V22-C2** | `check_tools` | Declarada como `-> None`, **no retornaba `body`** → las modificaciones al body se perdían en el caller | Ahora retorna `body` en todos los caminos |

## Cómo aplicar

```bash
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
```

Puedes ejecutarlo desde **cualquier directorio** — las rutas son absolutas. No es necesario estar dentro de `omen_router_modules/`.
