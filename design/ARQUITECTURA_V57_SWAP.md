# Arquitectura V57 — Modo `--swap` con llama-swap

Clúster OMEN · HP OMEN · Intel Ultra 7 255 · 32 GB RAM · RTX 4070 8 GB VRAM · SSD exFAT compartido

---

## Veredicto sobre los dos ficheros anteriores

### `openclaw.json` — DESCARTADO definitivamente

No vale la pena rescatarlo. Desde la V56 (y se mantiene en V57), la configuración de OpenClaw se **genera dinámicamente dentro del contenedor** en el arranque, con los valores correctos de red, puertos y credenciales del clúster (LiteLLM en `:4000` con su master key). Mantener un `openclaw.json` estático en paralelo crearía dos fuentes de verdad que se desincronizarían con cada cambio de versión, que es exactamente la clase de deriva que causó varios de los bugs corregidos entre V55 y V56. La inyección dinámica lo sustituye por completo.

### `llama-swap_config.yaml` — RESCATADO y elevado a pieza central

Este fichero sí mejora la configuración actual, y de forma decisiva. Es la base del nuevo **modo `--swap`** del V57, porque resuelve de raíz las dos limitaciones estructurales del clúster:

1. **VRAM (8 GB)**: TabbyAPI y SGLang no pueden convivir en la GPU. Hasta ahora había que elegir motor en el arranque (`--exl2` o `--sglang`). Con llama-swap, el motor se elige **por petición**: al pedir un modelo, llama-swap detiene el contenedor activo y arranca el del modelo solicitado, siempre con los 8 GB completos.
2. **Alias `codigo` inalcanzable**: en V56, el alias `codigo` apuntaba a Qwen2.5-Coder en `:5000`, pero TabbyAPI solo carga **un** modelo por instancia (Llama). El alias existía pero nunca respondía con Qwen. Con llama-swap, pedir `codigo` arranca el contenedor de Qwen bajo demanda.

Encaja además con el criterio rector del clúster: **se penaliza el tiempo (el swap de motor tarda 1–3 minutos en frío), nunca el razonamiento** (cada modelo corre con la VRAM íntegra y contexto ampliado).

---

## Qué es el modo `--swap`

```
Cliente / OpenClaw (:8080)
        │
        ▼
LiteLLM Router (:4000)  ── alias: instantaneo / codigo / agil ──┐
        │                                                        │
        │  orquestador / embeddings                              ▼
        ▼                                              llama-swap (:9090)
Ollama CPU (:11435)                                    arranca/detiene bajo demanda:
  · phi4-mini (orquestador)                             · swap-tabby-llama  (:5000)
  · nomic-embed-text (embeddings)                       · swap-tabby-qwen   (:5000)
                                                        · swap-sglang-awq   (:30000)
```

- **llama-swap** es un binario ligero en Go ([mostlygeek/llama-swap](https://github.com/mostlygeek/llama-swap)) que expone una API compatible OpenAI en `:9090` y gestiona el ciclo de vida de los contenedores Docker de cada modelo.
- El grupo `gpu` con `swap: true` y `exclusive: true` garantiza que **jamás hay dos motores en la GPU a la vez**.
- `ttl: 0` mantiene el modelo cargado indefinidamente: solo se descarga cuando otra petición exige un modelo distinto. Sin recargas por inactividad.
- El puerto es `9090` porque `8080` lo ocupa OpenClaw.

---

## Implementación de las tres advertencias operativas

### 1. VRAM — TabbyAPI y SGLang no conviven en 8 GB

Resuelto por diseño con el grupo exclusivo de llama-swap. Además, al tener cada motor la VRAM en exclusiva, se elevan sus parámetros:

| Parámetro | V56 (convivencia teórica) | V57 (`--swap`, VRAM exclusiva) |
|---|---|---|
| SGLang `--mem-fraction-static` | 0.78 | **0.85** |
| SGLang `--max-total-tokens` | 4096 | **8192** |
| TabbyAPI `--max-seq-len` | 4096 | **8192** |

### 2. Contexto EXL2 — de 2048 a 8192 (y camino a 16384)

`--max-seq-len 8192` en ambos modelos EXL2. Justificación por consumo de KV-cache en FP16:

| Modelo | KV-cache/token | @ 8192 | @ 16384 |
|---|---|---|---|
| Llama 3.1 8B | ≈ 128 KB | ≈ 1 GB | ≈ 2 GB |
| Qwen2.5 7B (GQA) | ≈ 57 KB | ≈ 470 MB | ≈ 940 MB |

Con la VRAM completa, 8192 es viable con margen. Para llegar a **16384** en Llama haría falta cache cuantizada Q4 (`--cache-mode Q4`), que exige una imagen reciente de TabbyAPI (el changelog del V33 registró que la 0.3.2 no lo soportaba). Como el clúster usa `ghcr.io/theroyallab/tabbyapi:latest`, la ampliación es un cambio de una línea en `llama-swap_config.yaml` cuando se quiera probar; se deja 8192 como valor seguro por defecto.

### 3. NVIDIA NIM — eliminado por completo

Sin rastro en el script V57 ni en `litellm_config.yaml`: ni contenedor, ni puerto, ni alias, ni fallback. Descartado por falta de disco, según lo acordado.

---

## Cambios en LiteLLM (`litellm_config.yaml` V57)

- Los alias `instantaneo`, `codigo` y `agil` apuntan ahora a llama-swap (`http://host.docker.internal:9090/v1`) en lugar de a los puertos físicos de cada motor.
- **Los fallbacks entre motores ahora funcionan siempre**: en V56, un fallback `instantaneo → agil` fallaba si TabbyAPI no estaba arrancado; con llama-swap, el motor destino se levanta bajo demanda.
- `orquestador` sigue siendo `phi4-mini` en Ollama CPU (`:11435`), sin consumir VRAM.
- `nomic-embed-text` queda **descomentado** como modelo de embeddings (lo usa el indexador del vault y ChromaDB).
- `request_timeout` y `timeout` por modelo suben de 600 a **1800 s**: el primer prompt tras un swap incluye el arranque en frío del contenedor y la carga de pesos desde el exFAT (criterio rector: ampliar límites de tiempo antes que reducir razonamiento).
- Las entradas físicas directas (`llama-3.1-8b-awq`, `llama-3.1-8b-exl2`, `qwen2.5-coder-7b-exl2`) se conservan para los modos legacy `--exl2`/`--sglang`; como llama-swap publica los mismos puertos (5000/30000), también responden en `--swap` una vez cargado el modelo.
- `master_key` vía `os.environ/LITELLM_MASTER_KEY` (`sk-litellm-local`), inyectada por el script.

---

## Encaje con la arquitectura de conocimiento (OpenClaw ↔ Obsidian)

El modo `--swap` está pensado para no romper la cadena de conocimiento local:

- **Ollama CPU se mantiene activo en `--swap`** (solo se omite Ollama GPU). Así, `nomic-embed-text` (embeddings para ChromaDB y el indexador `indexar_vault_v6.py`) y `phi4-mini` (orquestador) funcionan siempre, sin tocar la VRAM y sin verse afectados por los swaps de motor.
- El **contexto 8192** cuadruplica el espacio disponible para RAG: caben más fragmentos recuperados del vault de Obsidian en cada prompt, lo que mejora el encadenado de conocimiento entre conversaciones e hilos.
- Los adjuntos de prompts y respuestas siguen almacenándose en el vault (`$AI_CORE/obsidian_vault`), y el indexador puede correr en cualquier momento porque sus dependencias (Ollama CPU + ChromaDB `:8001`) no participan en el swap.

---

## Despliegue

1. Copiar los tres ficheros al host:
   ```bash
   cp Autoboot_Cluster_V57.sh ~/  # o donde se prefiera
   cp llama-swap_config.yaml ~/ai_cluster/llama-swap_config.yaml
   cp litellm_config.yaml    ~/ai_cluster/litellm_config.yaml
   ```
2. Arrancar en modo swap:
   ```bash
   bash Autoboot_Cluster_V57.sh --swap
   ```
   La sección 4b/8 descarga el binario de llama-swap (última release de GitHub, `linux_amd64`) en `~/ai_cluster/bin/llama-swap`, lo lanza con `--listen 0.0.0.0:9090` y comprueba salud vía `GET /v1/models`.
3. Verificar:
   ```bash
   bash Autoboot_Cluster_V57.sh --status
   curl -s http://localhost:9090/v1/models          # modelos gestionados por llama-swap
   curl -s http://localhost:4000/v1/models \
        -H "Authorization: Bearer sk-litellm-local" # alias visibles desde LiteLLM
   ```
4. Prueba de swap (arranque en frío del motor bajo demanda):
   ```bash
   curl -s http://localhost:4000/v1/chat/completions \
     -H "Authorization: Bearer sk-litellm-local" -H "Content-Type: application/json" \
     -d '{"model":"codigo","messages":[{"role":"user","content":"hola"}]}'
   ```
5. Parada completa (incluye llama-swap y los contenedores swap-*):
   ```bash
   bash Autoboot_Cluster_V57.sh --stop
   ```

### Compatibilidad de modos

| Modo | GPU | Ollama CPU | Uso |
|---|---|---|---|
| (defecto) | Ollama GPU | sí | legado |
| `--exl2` | TabbyAPI fijo (solo Llama) | sí | legacy |
| `--sglang` | SGLang fijo | sí | legacy |
| `--swap` | llama-swap: los 3 modelos bajo demanda | sí | **recomendado** |

`--swap` es mutuamente excluyente con `--exl2` y `--sglang`.

---

## Referencias

- llama-swap: https://github.com/mostlygeek/llama-swap
- LiteLLM Proxy: https://docs.litellm.ai/docs/simple_proxy
- Integración LiteLLM + OpenClaw: https://docs.litellm.ai/docs/tutorials/openclaw_integration
- Configuración de OpenClaw Gateway: https://docs.openclaw.ai/gateway/configuration
- TabbyAPI (ExLlamaV2): https://github.com/theroyallab/tabbyAPI
