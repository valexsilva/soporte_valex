"""Pruebas de inferencia de entorno desde el texto de entrada."""

from __future__ import annotations

import pytest

from src.core.models import Environment
from src.core.request_parsing import infer_environment


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("el componente linea-pf-service en dev está fallando", Environment.DEV),
        ("revisar bus-pagos en desarrollo", Environment.DEV),
        ("problema en pre con los pods", Environment.PRE),
        ("falla en preproducción", Environment.PRE),
        ("incidente en producción crítico", Environment.PRO),
        ("desplegar en prod", Environment.PRO),
        ("hay un problema con el servicio", Environment.PRE),  # default
    ],
)
def test_infer_environment(text: str, expected: Environment) -> None:
    assert infer_environment(text) == expected


def test_infer_environment_picks_first_mention() -> None:
    # 'dev' aparece antes que 'pro' -> gana dev.
    assert infer_environment("comparar dev contra pro") == Environment.DEV


def test_infer_environment_empty_uses_default() -> None:
    assert infer_environment("") == Environment.PRE
    assert infer_environment("", default=Environment.DEV) == Environment.DEV
