
# ═══════════════════════════════════════════════════════════════════════════════
#  PATCH orchestrator_router_V14-3.py — Cambios respecto a V14-2.py (V24 → V25)
#
#  [V25-HB] Interceptación de heartbeat poll de OpenClaw antes de clasificar.
#           OpenClaw envía periódicamente un mensaje de heartbeat para verificar
#           que el backend LLM responde. Este mensaje se clasifica como PROFUNDO
#           (default) y lanza deepseek-r1:14b en GPU sin necesidad, además de
#           producir el error "stream has been closed" cuando el router se
#           reinicia mientras el heartbeat está en vuelo.
#           La respuesta canned (un "." seguido de stop) es suficiente para
#           satisfacer al cliente OpenClaw sin tocar la GPU.
#
#  VALIDACIÓN del análisis del ayudante externo:
#    ✓ Causa raíz P0 (content array → Ollama 400): CORRECTA y CONFIRMADA.
#    ✓ Causa raíz P1 (heartbeat → PROFUNDO): CORRECTA y CONFIRMADA en log.
#    ✓ Fix P0 en sanitize_for_ollama: CORRECTO. El bucle es seguro y completo.
#    ✓ Fix P1 canned-response: CORRECTO. No hay riesgo de romper el protocolo
#      SSE porque OpenClaw solo comprueba que recibe datos, no el contenido.
#    ✓ Afirmación "el bug era latente desde V21/V22/V23": CORRECTA. La primera
#      aparición en log es 161646 (ayer) con MASIVO, que coincide con cuando
#      OpenClaw comenzó a usar el agente con tools activos.
#
#  Sin discrepancias sustanciales con el análisis del ayudante. Mi único añadido
#  es la advertencia sobre el orden sanitize→check_tools (ya correcto en V23-S1).
# ═══════════════════════════════════════════════════════════════════════════════

# ─── LOCALIZACIÓN EN orchestrator_router_V14.py ─────────────────────────────
# Endpoint: POST /v1/chat/completions
# Insertar el bloque [V25-HB] DESPUÉS de extraer `prompt` y `streaming`,
# ANTES de resolver el nivel (bloque "Resolver nivel").
#
# Contexto actual (líneas ~556-560 aprox.):
#   prompt = last_msg.get("content", "") if isinstance(last_msg.get("content"), str) else ""
#   streaming = body.get("stream", False)
#   agentid = ...
#   log.info(...)
#   << INSERTAR AQUÍ el bloque V25-HB >>
#   nivel = ALIAS_A_NIVEL.get(modelo_lower)
#   ...

import uuid  # ya importado en el fichero original

# Prefijos que identifican un heartbeat de OpenClaw (case-insensitive)
_HEARTBEAT_PREFIXES = (
    "openclaw heartbeat",
    "heartbeat poll",
    "openclaw poll",
    "[openclaw heartbeat",
    "[heartbeat poll]",
)

# ── [V25-HB] Bloque a insertar en /v1/chat/completions ──────────────────────
# (después de definir `prompt` y `streaming`, antes de resolver el nivel)

    # [V25-HB] Interceptar heartbeat de OpenClaw — respuesta canned sin GPU
    _prompt_lower = prompt.strip().lower()
    if any(_prompt_lower.startswith(hb) or hb in _prompt_lower
           for hb in _HEARTBEAT_PREFIXES):
        log.debug("[HB] Heartbeat poll detectado — respuesta canned (sin GPU)")
        _hb_id = "hb-" + str(uuid.uuid4())[:8]
        _hb_chunk = json.dumps({
            "id": _hb_id,
            "object": "chat.completion.chunk",
            "model": modelo_raw,
            "choices": [{
                "index": 0,
                "delta": {"role": "assistant", "content": "."},
                "finish_reason": None,
            }],
        })
        _hb_done = json.dumps({
            "id": _hb_id,
            "object": "chat.completion.chunk",
            "model": modelo_raw,
            "choices": [{
                "index": 0,
                "delta": {},
                "finish_reason": "stop",
            }],
        })

        async def _hb_gen():
            yield f"data: {_hb_chunk}\n\n".encode()
            yield f"data: {_hb_done}\n\n".encode()
            yield b"data: [DONE]\n\n"

        return StreamingResponse(
            _hb_gen(),
            media_type="text/event-stream",
            headers={
                "X-Omen-Model-Used": "heartbeat-canned",
                "X-Omen-Nivel": "none",
            },
        )
    # ── fin [V25-HB] ────────────────────────────────────────────────────────
