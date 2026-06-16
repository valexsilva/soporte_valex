"""Excepciones del dominio del sistema multi-agente."""

from __future__ import annotations


class SoporteValexError(Exception):
    """Excepción base del sistema."""


class ProductionMutationBlocked(SoporteValexError):
    """Se intentó una mutación en entorno productivo (PRO Shield)."""


class SchemaValidationError(SoporteValexError):
    """El payload generado por el LLM no cumple el esquema de la tool."""


class ReActCycleLimitReached(SoporteValexError):
    """Se alcanzó el límite de ciclos ReAct sin certidumbre suficiente."""


class LLMProviderError(SoporteValexError):
    """Fallo al invocar un proveedor de inferencia (Devin o local)."""


class SessionNotFound(SoporteValexError):
    """No existe la sesión solicitada para reanudar."""


class IntegrationError(SoporteValexError):
    """Fallo al invocar una integración externa (p. ej. ServiceNow)."""
