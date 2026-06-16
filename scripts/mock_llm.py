"""Mock LLM OpenAI-compatible para validación local del orquestador.

Expone POST /v1/chat/completions y devuelve una decisión ReAct en JSON según
el contenido del prompt:
- Si el prompt menciona "falla" o "rollback" -> propone execute_pipeline_action
  (dispara el flujo Human-in-the-loop).
- En cualquier otro caso -> respuesta final con alta certidumbre.

Uso:
    python -m uvicorn scripts.mock_llm:app --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI

app = FastAPI(title="Mock LLM")


def _decision_for(prompt: str) -> dict[str, Any]:
    text = prompt.lower()
    if "falla" in text or "rollback" in text:
        return {
            "thought": "Detecto una falla; propongo rollback en PRE.",
            "action": "tool",
            "tool_name": "execute_pipeline_action",
            "tool_input": {
                "component_name": "bus-pagos",
                "environment": "pre",
                "action": "rollback",
                "branch": "main",
                "idempotency_key": "mock-key-001",
            },
            "confidence": 0.95,
        }
    return {
        "thought": "Consulta informativa; respondo directamente.",
        "action": "final",
        "final_answer": "Diagnóstico completado: el componente opera con normalidad.",
        "confidence": 0.96,
    }


@app.post("/v1/chat/completions")
async def chat_completions(body: dict[str, Any]) -> dict[str, Any]:
    messages = body.get("messages", [])
    prompt = messages[-1].get("content", "") if messages else ""
    decision = _decision_for(prompt)
    return {
        "id": "mock-cmpl-1",
        "object": "chat.completion",
        "model": body.get("model", "mock"),
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": json.dumps(decision)},
                "finish_reason": "stop",
            }
        ],
    }
