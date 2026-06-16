"""Parser robusto de la salida JSON del LLM en el bucle ReAct."""

from __future__ import annotations

import json
from typing import Any, Iterator

from pydantic import BaseModel, Field, ValidationError

# Claves que identifican un objeto JSON como una decisión del agente.
_DECISION_KEYS = {"action", "thought", "final_answer", "tool_name"}


class LLMDecision(BaseModel):
    """Decisión estructurada emitida por el modelo en un ciclo ReAct."""

    thought: str = ""
    action: str = "final"
    tool_name: str | None = None
    # Devin puede emitir una sola entrada (dict) o varias en paralelo (lista).
    tool_input: dict[str, Any] | list[dict[str, Any]] = Field(default_factory=dict)
    final_answer: str = ""
    confidence: float = 1.0

    def tool_inputs(self) -> list[dict[str, Any]]:
        """Normaliza ``tool_input`` a una lista de dicts para ejecución."""

        if isinstance(self.tool_input, list):
            return [item for item in self.tool_input if isinstance(item, dict)]
        if isinstance(self.tool_input, dict) and self.tool_input:
            return [self.tool_input]
        return []


def _iter_json_objects(text: str) -> Iterator[str]:
    """Itera subcadenas de objetos JSON de nivel superior (llaves balanceadas).

    Recorre el texto contabilizando llaves para extraer cada objeto ``{...}``
    completo en orden de aparición, ignorando llaves dentro de cadenas.
    """

    depth = 0
    start: int | None = None
    in_string = False
    escape = False
    for i, ch in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start is not None:
                yield text[start : i + 1]
                start = None


def _first_decision_obj(text: str) -> dict[str, Any] | None:
    """Devuelve el primer objeto JSON válido que parece una decisión.

    Tolera prosa alrededor y múltiples bloques JSON (toma el primero válido
    con claves de decisión). Si ninguno tiene esas claves, usa el primer
    objeto JSON válido encontrado.
    """

    first_valid: dict[str, Any] | None = None
    for candidate in _iter_json_objects(text):
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        if first_valid is None:
            first_valid = data
        if _DECISION_KEYS & data.keys():
            return data
    return first_valid


def parse_decision(raw_text: str) -> LLMDecision:
    """Extrae y valida la decisión JSON desde la salida cruda del modelo.

    Tolera texto adicional alrededor del JSON y respuestas con múltiples
    bloques (toma el primer objeto de decisión válido). Si no logra parsear,
    devuelve una decisión `final` con el texto crudo como respuesta.
    """

    data = _first_decision_obj(raw_text or "")
    if data is None:
        return LLMDecision(action="final", final_answer=raw_text or "", confidence=0.0)

    try:
        return LLMDecision.model_validate(data)
    except ValidationError:
        return LLMDecision(action="final", final_answer=raw_text or "", confidence=0.0)
