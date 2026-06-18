#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║ orchestrator_router_V14.py — OMEN AI Router V14 (build V23)               ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  ÚNICO CAMBIO RESPECTO A BUILD V22:                                         ║
║                                                                             ║
║  [V23-ORDER] En el endpoint POST /v1/chat/completions,                      ║
║  sanitize_for_ollama() se invoca ANTES de inject_opciones_extra(),          ║
║  inject_thinking() y check_tools(), NO después.                             ║
║                                                                             ║
║  Problema V22: sanitize se llamaba al final → check_tools() podía          ║
║  recibir el campo "tools" intacto (bien) pero inject_opciones_extra()      ║
║  recibía stream_options/max_completion_tokens y los propagaba.             ║
║  Además, check_tools() y inject_thinking() operaban sobre un body          ║
║  que aún contenía campos inválidos para Ollama.                            ║
║                                                                             ║
║  Solución V23: el orden correcto es:                                        ║
║    1. sanitize_for_ollama()   ← limpia campos OpenAI incompatibles         ║
║    2. inject_opciones_extra() ← añade num_ctx, temperature, etc.           ║
║    3. inject_thinking()       ← activa think=True si aplica               ║
║    4. check_tools()           ← gestiona tools/tool_choice                 ║
╚══════════════════════════════════════════════════════════════════════════════╝

INSTRUCCIÓN DE APLICACIÓN:
─────────────────────────────────────────────────────────────────────────────
Localiza en orchestrator_router_V14.py el bloque "Ajustes del body" dentro
del endpoint chat() y reemplaza EXACTAMENTE estas 4 líneas:

  ANTES (build V22):
    body = inject_opciones_extra(body, nivel, body["model"])   # [V23-O1]
    body = inject_thinking(body, nivel, body["model"])
    body = check_tools(body, nivel, body["model"])             # [V23-C1]
    body = sanitize_for_ollama(body, nivel, body["model"])     # [V22-O2]

  DESPUÉS (build V23):
    body = sanitize_for_ollama(body, nivel, body["model"])     # [V23-S1] PRIMERO
    body = inject_opciones_extra(body, nivel, body["model"])   # [V23-O1]
    body = inject_thinking(body, nivel, body["model"])         # [V23-T1]
    body = check_tools(body, nivel, body["model"])             # [V23-C1]

─────────────────────────────────────────────────────────────────────────────
El resto del archivo permanece IDÉNTICO al build V22.
─────────────────────────────────────────────────────────────────────────────

BLOQUE COMPLETO CORREGIDO DEL ENDPOINT chat() — sección "Ajustes del body":
"""

# ── Ajustes del body ────────────────────────────────────────────────────
body = sanitize_for_ollama(body, nivel, body["model"])     # [V23-S1] PRIMERO — body limpio
body = inject_opciones_extra(body, nivel, body["model"])   # [V23-O1] num_ctx, temperature…
body = inject_thinking(body, nivel, body["model"])         # [V23-T1] think=True si aplica
body = check_tools(body, nivel, body["model"])             # [V23-C1] tools → texto plano si sin soporte
