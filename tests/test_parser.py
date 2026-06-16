"""Pruebas del parser de decisiones del LLM."""

from __future__ import annotations

from src.agents.orchestrator.parser import parse_decision


def test_parse_clean_json() -> None:
    raw = '{"thought": "diagnostico", "action": "final", "final_answer": "ok", "confidence": 0.95}'
    decision = parse_decision(raw)
    assert decision.action == "final"
    assert decision.final_answer == "ok"
    assert decision.confidence == 0.95


def test_parse_json_with_surrounding_text() -> None:
    raw = 'Claro, aqui va: {"thought": "t", "action": "tool", "tool_name": "x"} fin.'
    decision = parse_decision(raw)
    assert decision.action == "tool"
    assert decision.tool_name == "x"


def test_parse_invalid_falls_back_to_final() -> None:
    decision = parse_decision("texto sin json")
    assert decision.action == "final"
    assert decision.confidence == 0.0


def test_parse_fenced_json_block() -> None:
    raw = '```json\n{"thought": "t", "action": "tool", "tool_name": "x"}\n```'
    decision = parse_decision(raw)
    assert decision.action == "tool"
    assert decision.tool_name == "x"


def test_parse_multiple_blocks_takes_first_decision() -> None:
    # Devin a veces emite un primer bloque (tool) + prosa + un segundo bloque.
    raw = (
        '```json\n{"thought": "t1", "action": "tool", "tool_name": "telemetry"}\n```\n'
        "Nota: no tengo acceso real.\n"
        '```json\n{"thought": "t2", "action": "escalate", "final_answer": "esc"}\n```'
    )
    decision = parse_decision(raw)
    assert decision.action == "tool"
    assert decision.tool_name == "telemetry"


def test_parse_tool_input_as_list() -> None:
    raw = (
        '{"thought": "t", "action": "tool", "tool_name": "telemetry", '
        '"tool_input": [{"component_name": "a"}, {"component_name": "b"}]}'
    )
    decision = parse_decision(raw)
    assert decision.action == "tool"
    inputs = decision.tool_inputs()
    assert [i["component_name"] for i in inputs] == ["a", "b"]


def test_parse_tool_input_as_dict_normalizes_to_list() -> None:
    raw = (
        '{"thought": "t", "action": "tool", "tool_name": "telemetry", '
        '"tool_input": {"component_name": "a"}}'
    )
    decision = parse_decision(raw)
    assert decision.tool_inputs() == [{"component_name": "a"}]


def test_parse_ignores_braces_inside_strings() -> None:
    raw = '{"thought": "usa {llaves} aqui", "action": "final", "final_answer": "ok"}'
    decision = parse_decision(raw)
    assert decision.action == "final"
    assert decision.final_answer == "ok"
