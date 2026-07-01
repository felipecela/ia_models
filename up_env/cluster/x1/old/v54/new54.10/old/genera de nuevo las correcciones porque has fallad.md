<img src="https://r2cdn.perplexity.ai/pplx-full-logo-primary-dark%402x.png" style="height:64px;margin-right:32px"/>

# genera de nuevo las correcciones porque has fallado en la ultima etapa de generacion de los ficheros

Los tres ficheros están generados, validados y listos para descargar.

***

## Resumen V27 — Todos los fixes aplicados

### `config_V27_final.py` — 329 líneas

| Fix | Descripción |
| :-- | :-- |
| **V27-C1** 🔴 | `"phi4-mini"` aparecía dos veces en `ALIAS_A_NIVEL` — Python conservaba la última (`PHI4_DIRECTO`). Eliminada la segunda entrada. Ahora mapea únicamente a `CHAT` |
| **V27-C2** 🟠 | `opciones_extra` usaba `max_tokens` en root del body (Ollama lo ignora). Migrado a sub-dict `"options": {"num_predict": N}` en CHAT, INSTANTANEO, AGIL y CODIGO |
| **V27-C3** 🟡 | `LOG_FILE` unificado a `router_v14.log` — antes escribía en `orchestrator_router.log` y el Autoboot capturaba stdout en `router_v14.log`, partiendo los logs en dos ficheros |
| **V27-C4** 🟡 | URLs con `127.0.0.1` explícito — `localhost` resuelve IPv6 (`::1`) primero y la conexión era rechazada |

### `proxy_V27_final.py` — 767 líneas

| Fix | Descripción |
| :-- | :-- |
| **V27-C2** 🟠 | `inject_opciones_extra()` ahora detecta el sub-dict `"options"` y lo mergea correctamente en `body["options"]` en lugar de inyectarlo en root |
| **V27-FB** 🔴 | `_proxy_streaming` ya intenta la cadena de fallback en timeout (PROFUNDO→AGIL, PRECISO→PRECISO_OPT…). Antes emitía error SSE directamente sin fallback |
| **V27-JSON** 🟠 | `_proxy_json` ahora protege `resp.json()` con `try/except` — si Ollama devuelve HTML o texto plano en un error 5xx ya no crashea con `JSONDecodeError` |
| **V27-ORDER** 🟠 | `proxy_request` ejecuta `sanitize_for_ollama` **antes** de `validate_and_truncate_messages` — la estimación de tokens se hace sobre `content` ya normalizado a string |

### `orchestrator_router_V14_V27_final.py` — 935 líneas

| Fix | Descripción |
| :-- | :-- |
| **V27-A1/A3** | Banner y versión actualizados a `build V27` / `14.27.0` |
| **V27-A4** | Guard `request.client or 'unknown'` en los tres mensajes de log de AUTH — evita `NoneType` cuando el cliente se desconecta antes de autenticar |

<span style="display:none">[^1]</span>

<div align="center">⁂</div>

[^1]: paste.txt

