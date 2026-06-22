
# ═══════════════════════════════════════════════════════════════════════════════
#  PATCH proxy-5.py — Cambios respecto a proxy-4.py (build V24 → V25)
#
#  [V25-C1] sanitize_for_ollama: normalizar messages[].content array → string
#           El problema: Ollama /api/chat exige content como string plano.
#           OpenClaw (como cualquier cliente OpenAI-compatible con herramientas
#           o modo multimodal) puede enviar content como lista de dicts:
#             [{"type": "text", "text": "hola"}]
#           Ollama responde HTTP 400:
#             json: cannot unmarshal array into Go struct field
#             ChatRequest.messages.content of type string
#
#  NOTA IMPORTANTE sobre el análisis del ayudante externo:
#    El ayudante identifica correctamente la causa raíz (P0) y la solución es
#    acertada. Sin embargo hay un matiz: el bucle de normalización DEBE ejecutarse
#    ANTES de check_tools, porque check_tools itera sobre messages buscando el
#    system message y podría encontrar content como lista, corrompiendo la inyección.
#    El orden correcto en orchestrator ya lo respeta (sanitize → inject → thinking
#    → check_tools), así que el fix en proxy.py es suficiente y seguro.
#
#  [V25-HB] Interceptación de heartbeat de OpenClaw en orchestrator (P1)
#    El ayudante identifica correctamente que el heartbeat se clasifica como
#    PROFUNDO y carga deepseek-r1 innecesariamente.
#    VALIDACIÓN: Confirmado en log:
#      145558 PROMPT Fri 2026-06-19 1255 UTC OpenClaw heartbeat poll → PROFUNDO
#      145759 PROMPT Fri 2026-06-19 1255 UTC OpenClaw heartbeat poll → PROFUNDO
#      145841 ERROR streaming PROFUNDO stream has been closed
#    El fix canned-response es correcto y seguro.
#
#  ISSUE ADICIONAL detectado en mi análisis (no mencionado por el ayudante):
#  [V25-T1] check_tools tampoco maneja el caso en que content es lista cuando
#           busca/inyecta el system message. Si content es array al llegar a
#           check_tools, la línea:
#             content = msg.get("content", ""); msg["content"] = tools_text + content
#           concatenaría tools_text con una lista → TypeError en runtime.
#           Con el fix V25-C1 en sanitize_for_ollama (que se llama PRIMERO),
#           esto queda cubierto automáticamente. No se necesita cambio adicional
#           en check_tools, pero es el motivo por el que el orden de llamadas
#           (sanitize PRIMERO) establecido en V23-S1 es crítico.
#
#  ISSUE ADICIONAL detectado: el log muestra "PROXY Backend retornó 400 en PROFUNDO"
#  también en deepseek-r1:14b (además de MASIVO/qwen2.5:32b y PRECISO_OPT).
#  Esto confirma que el bug afecta a TODOS los backends Ollama cuando OpenClaw
#  envía content como array, independientemente del modelo. El fix es universal.
# ═══════════════════════════════════════════════════════════════════════════════

# ─── LOCALIZACIÓN EN proxy.py ───────────────────────────────────────────────
# Función: sanitize_for_ollama(body, nivel, model)
# Sustituir la función completa por la versión V25 que se muestra a continuación.
# El único bloque nuevo es el marcado [V25-C1]; el resto es idéntico a V24.

OLLAMA_UNSUPPORTED = [
    "stream_options", "max_completion_tokens", "logprobs",
    "top_logprobs", "service_tier", "store",
]

def sanitize_for_ollama(body: dict, nivel: str, model: str) -> dict:
    """
    [V23-S1] Elimina campos OpenAI que Ollama no acepta.
    [V23-S3] Convierte max_completion_tokens -> options.num_predict.
    [V24-D1] Loguea campos eliminados a nivel DEBUG.
    [V25-C1] Normaliza messages[].content array → string.
             Ollama /api/chat requiere content como string plano.
             OpenClaw (y cualquier cliente OpenAI multimodal) puede enviar:
               {"role": "user", "content": [{"type": "text", "text": "hola"}]}
             que Ollama rechaza con HTTP 400.
    """
    removed = []

    # ── [V25-C1] Normalizar content array → string ───────────────────────────
    # Se ejecuta PRIMERO, antes de cualquier otra transformación, porque
    # inject_thinking y check_tools asumen que content ya es string.
    for msg in body.get("messages", []):
        content = msg.get("content")
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, dict):
                    ptype = part.get("type", "")
                    if ptype == "text":
                        parts.append(part.get("text", ""))
                    elif ptype in ("image_url", "image"):
                        # Modelos Ollama no son multimodales en este cluster.
                        # Se omite la imagen con aviso inline para no perder
                        # el hilo de conversación.
                        parts.append("[imagen omitida — modelo sin soporte multimodal]")
                    # Otros tipos (tool_result, etc.) se descartan silenciosamente.
                elif isinstance(part, str):
                    parts.append(part)
            msg["content"] = "\n".join(parts)
            log.debug(
                "[V25-C1] content array→string en role='%s' (%d partes)",
                msg.get("role", "?"), len(content),
            )
    # ─────────────────────────────────────────────────────────────────────────

    # [V23-S3] max_completion_tokens → options.num_predict
    if "max_completion_tokens" in body:
        mct = body.pop("max_completion_tokens")
        removed.append("max_completion_tokens")
        if "max_tokens" not in body:
            opts = body.get("options", {})
            if not isinstance(opts, dict):
                opts = {}
            opts.setdefault("num_predict", mct)
            body["options"] = opts

    # [V23-S1] Eliminar campos OpenAI no soportados por Ollama
    for campo in OLLAMA_UNSUPPORTED:
        if campo == "max_completion_tokens":
            continue  # ya tratado arriba
        if campo in body:
            body.pop(campo)
            removed.append(campo)

    if removed:
        non_msg = {k: v for k, v in body.items() if k != "messages"}
        log.debug(
            "[V24-D1] body_campos=%s non-msg=%s",
            list(body.keys()), json.dumps(non_msg, ensure_ascii=False, default=str)[:400],
        )

    return body
