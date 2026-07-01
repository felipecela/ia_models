# Consolidación V55 → V56 — OMEN AI Cluster

Análisis de tu `Autoboot_Cluster_V55.sh` + `litellm_config-2.yaml` y consolidación con mi propuesta anterior (V12/LiteLLM), respetando tu inventario real de modelos.

## Inventario real (base de todas las decisiones)

| Modelo | Tamaño | Motor | Puerto |
|---|---|---|---|
| llama-3.1-8b-awq | 5.4G | SGLang (`--sglang`) | 30000 |
| llama-3.1-8b-exl2 | 6.3G | TabbyAPI (`--exl2`) | 5000 |
| qwen2.5-coder-7b-exl2 | 6.5G | TabbyAPI (`--exl2`) | 5000 |

Los contenedores `ollama-gpu-main` y `ollama-cpu-router` **no existen** en tu máquina. Todo lo que dependía de ellos se ha hecho opcional, no eliminado.

## Bugs encontrados en tu V55

1. **Primario inexistente**: se inyectaba `litellm-omen/profundo-r1` en OpenClaw, pero ese id no existe en ningún `model_list` — OpenClaw arrancaba con un modelo primario muerto.
2. **Dependencia fantasma del Router V14**: el precheck **abortaba** si faltaba `orchestrator_router_V14.py`, pero el script ya nunca lo arranca (LiteLLM lo sustituyó). Dependencia obligatoria de un componente muerto.
3. **Lista estática de 11 modelos** registrada en OpenClaw, incluyendo modelos Ollama que no tienes instalados.
4. **`_INJ_EXIT=$?` / `_VERIFY_EXIT=$?` bajo `set -euo pipefail`**: si el `docker exec` fallaba, el script abortaba *antes* de capturar el código — el manejo de errores nunca llegaba a ejecutarse.
5. **Health check TCP de 30 s para LiteLLM**: insuficiente; LiteLLM abre el puerto antes de estar listo y puede tardar más de 30 s en cargar.
6. **Sin `LITELLM_MASTER_KEY`**: OpenClaw enviaba `apiKey: sk-litellm-local` pero LiteLLM no exigía ninguna clave — incoherente.
7. **Versionado mixto**: `SCRIPT_VERSION="V54"` en un archivo llamado V55, con banners V54 y V55 mezclados.
8. **`--status` monitoreaba el Router V14 en :8000** (muerto) en lugar de LiteLLM en :4000.
9. **Arranque por defecto recrearía Ollama** y re-descargaría ~40 GB de modelos que ya eliminaste.

## Cambios aplicados en V56

### Autoboot_Cluster_V56.sh
- **`--no-ollama` [V56-N1]**: nuevo flag que omite por completo las secciones Ollama GPU/CPU (creación, descarga de modelos, resumen y health checks muestran "omitido"). Si no hay otro motor activo, auto-activa `--exl2`. Detiene contenedores Ollama residuales.
- **LiteLLM como router oficial [V56-L1..L3]**: `PORT_LITELLM=4000`, `LITELLM_MASTER_KEY=sk-litellm-local` inyectada al contenedor (coherente con el apiKey de OpenClaw), health check **HTTP real** contra `/health/liveliness` con 90 s de margen.
- **Router V14 degradado a informativo**: su ausencia ya no aborta el arranque; solo informa.
- **Primario dinámico [V56-B1]**: el primario de OpenClaw se lee de `/tmp/oc_primary.txt` con fallback seguro a `litellm-omen/instantaneo` (alias que sí existe), y los fallbacks se calculan a partir de los ids reales.
- **Lista de modelos dinámica**: OpenClaw registra los modelos consultando `http://localhost:4000/v1/models` en vivo — nunca más ids muertos.
- **Fix `set -e` [V56-B2]**: patrón `_EXIT=0; docker exec … || _EXIT=$?` en inyección y verificación.
- **`--status` actualizado [V56-S1]**: monitorea LiteLLM Gateway :4000 (`/health/liveliness`, contenedor `litellm-router`) en lugar del Router V14 :8000.
- **Versionado unificado**: todos los banners usan `${SCRIPT_VERSION}` (= V56).
- Validado con `bash -n`: sin errores de sintaxis.

### litellm_config.yaml consolidado
Fusión de ambas versiones, aprovechando el máximo de las dos:

- **De la tuya**: los 3 endpoints nativos verbatim, `drop_params: true`, y todas tus entradas Ollama/NIM **preservadas comentadas** (num_ctx incluidos) para reactivarlas cuando quieras.
- **De la mía**: alias semánticos estables, reintentos, timeout largo, fallbacks y master key.

| Alias | Backend real | Uso |
|---|---|---|
| `instantaneo` | llama-3.1-8b-exl2 (TabbyAPI) | respuestas generales rápidas |
| `codigo` | qwen2.5-coder-7b-exl2 (TabbyAPI) | programación |
| `agil` | llama-3.1-8b-awq (SGLang) | throughput/batch |
| `orquestador` | llama-3.1-8b-exl2, temp 0.0 | clasificación/planificación |

Fallbacks: `instantaneo→agil`, `codigo→instantaneo`, `agil→instantaneo`, `orquestador→instantaneo`. Los niveles `profundo`/`masivo`/`embeddings` (Ollama) quedan comentados junto a sus modelos.

La ventaja de los alias: OpenClaw solo conoce `litellm-omen/instantaneo`, etc. — puedes cambiar el modelo físico debajo sin tocar OpenClaw.

## Advertencias operativas

- **VRAM**: TabbyAPI y SGLang no conviven con 8 GB salvo en tu modo `--sglang` (mem-frac 0.15). Los fallbacks EXL2↔AWQ solo funcionan si ambos motores están arriba.
- **Contexto EXL2**: tu autoboot lanza TabbyAPI con `--max-seq-len 2048`. Para agentes en OpenClaw es muy poco; considera 8192–16384 si la VRAM lo permite.
- **`nvidia-nim-model`**: placeholder sin servicio real en :8002 — comentado para que no ensucie `/v1/models` ni la lista dinámica de OpenClaw.

## Despliegue

```bash
cp Autoboot_Cluster_V56.sh ~/ai_cluster/ && chmod +x ~/ai_cluster/Autoboot_Cluster_V56.sh
cp litellm_config.yaml ~/ai_cluster/litellm_config.yaml

# Arranque recomendado con tu inventario actual:
ai_cluster --exl2 --no-ollama      # TabbyAPI (llama-8b-exl2 + qwen-coder)
# o bien:
ai_cluster --sglang --no-ollama    # SGLang (llama-8b-awq)

ai_cluster --status                # ahora verifica LiteLLM :4000
```

Prueba rápida del gateway:

```bash
curl -s http://localhost:4000/v1/models -H "Authorization: Bearer sk-litellm-local" | python3 -m json.tool
curl -s http://localhost:4000/v1/chat/completions -H "Authorization: Bearer sk-litellm-local" \
  -H "Content-Type: application/json" \
  -d '{"model":"instantaneo","messages":[{"role":"user","content":"ping"}]}'
```

Referencias: [LiteLLM Proxy](https://docs.litellm.ai/docs/simple_proxy) · [Integración OpenClaw + LiteLLM](https://docs.litellm.ai/docs/tutorials/openclaw_integration) · [Configuración de gateway OpenClaw](https://docs.openclaw.ai/gateway/configuration)
