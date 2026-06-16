"""Worker asíncrono de ingesta en segundo plano (doc sección 2.2 / 11.2).

Procesa documentos sin penalizar el runtime de consultas. Mantiene un
registro en memoria del estado de cada job de ingesta.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from uuid import uuid4

from src.ingestion.processor import build_chunks, build_embeddings


class JobStatus(str, Enum):
    """Estado del job de ingesta."""

    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class IngestionJob:
    """Estado de un job de ingesta documental."""

    job_id: str
    file_name: str
    status: JobStatus = JobStatus.QUEUED
    chunks: int = 0
    embeddings: int = 0
    error: str | None = None


@dataclass
class IngestionManager:
    """Gestiona jobs de ingesta en background."""

    jobs: dict[str, IngestionJob] = field(default_factory=dict)

    def enqueue(self, file_name: str, text: str) -> IngestionJob:
        """Crea y agenda un nuevo job de ingesta."""

        job = IngestionJob(job_id=f"job_{uuid4().hex[:12]}", file_name=file_name)
        self.jobs[job.job_id] = job
        asyncio.create_task(self._process(job, text))
        return job

    def status(self, job_id: str) -> IngestionJob | None:
        """Devuelve el estado de un job."""

        return self.jobs.get(job_id)

    async def _process(self, job: IngestionJob, text: str) -> None:
        try:
            job.status = JobStatus.PROCESSING
            await asyncio.sleep(0)  # cede control (procesamiento aislado)
            chunks = build_chunks(job.job_id, text)
            embeddings = build_embeddings(chunks)
            job.chunks = len(chunks)
            job.embeddings = len(embeddings)
            job.status = JobStatus.COMPLETED
        except Exception as exc:  # noqa: BLE001
            job.status = JobStatus.FAILED
            job.error = str(exc)
