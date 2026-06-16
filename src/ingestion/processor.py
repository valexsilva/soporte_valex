"""Procesamiento de documentos: extracción, chunking y embeddings.

Implementa el workflow de la guía de administrador (doc sección 2.2):
extracción de estructuras -> chunking -> embeddings -> validación. En esta
fase los embeddings se simulan; el modelo de datos sigue KB_* (sección 14.2).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4


@dataclass
class Chunk:
    """Fragmento de texto derivado de un documento."""

    chunk_id: str
    document_id: str
    order: int
    text: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class Embedding:
    """Vector asociado a un chunk (simulado en esta fase)."""

    embedding_id: str
    chunk_id: str
    vector_ref: str
    model_name: str


def chunk_text(text: str, *, max_chars: int = 800) -> list[str]:
    """Divide texto en chunks por límite de caracteres respetando párrafos."""

    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    chunks: list[str] = []
    buffer = ""
    for para in paragraphs:
        if len(buffer) + len(para) + 1 > max_chars and buffer:
            chunks.append(buffer.strip())
            buffer = para
        else:
            buffer = f"{buffer}\n{para}" if buffer else para
    if buffer.strip():
        chunks.append(buffer.strip())
    return chunks


def build_chunks(document_id: str, text: str, *, max_chars: int = 800) -> list[Chunk]:
    """Genera los chunks persistibles para un documento."""

    return [
        Chunk(
            chunk_id=f"chunk_{uuid4().hex[:12]}",
            document_id=document_id,
            order=index,
            text=fragment,
        )
        for index, fragment in enumerate(chunk_text(text, max_chars=max_chars))
    ]


def build_embeddings(chunks: list[Chunk], *, model_name: str = "local-embed") -> list[Embedding]:
    """Genera embeddings simulados (hash determinista como vector_ref)."""

    embeddings: list[Embedding] = []
    for chunk in chunks:
        digest = hashlib.sha256(chunk.text.encode("utf-8")).hexdigest()[:16]
        embeddings.append(
            Embedding(
                embedding_id=f"emb_{uuid4().hex[:12]}",
                chunk_id=chunk.chunk_id,
                vector_ref=f"vec::{digest}",
                model_name=model_name,
            )
        )
    return embeddings
