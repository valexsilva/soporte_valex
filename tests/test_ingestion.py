"""Pruebas de ingesta de conocimiento (doc sección 11.2)."""

from __future__ import annotations

import asyncio

import pytest

from src.ingestion.background import IngestionManager, JobStatus
from src.ingestion.processor import build_chunks, build_embeddings


def test_chunking_and_embeddings() -> None:
    text = "\n".join(f"parrafo {i} con contenido tecnico" for i in range(20))
    chunks = build_chunks("doc1", text, max_chars=120)
    embeddings = build_embeddings(chunks)
    assert len(chunks) > 1
    assert len(embeddings) == len(chunks)


@pytest.mark.asyncio
async def test_ingestion_job_completes() -> None:
    manager = IngestionManager()
    job = manager.enqueue("manual.txt", "linea 1\nlinea 2\nlinea 3")
    # Esperar a que el task en background finalice.
    for _ in range(10):
        await asyncio.sleep(0.01)
        if manager.status(job.job_id).status == JobStatus.COMPLETED:
            break
    assert manager.status(job.job_id).status == JobStatus.COMPLETED
