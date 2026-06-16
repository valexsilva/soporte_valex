"""Endpoints de ingesta de conocimiento (upload / status)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile

from src.api.deps import get_ingestion_manager
from src.ingestion.background import IngestionManager

router = APIRouter(prefix="/api/ingestion", tags=["ingestion"])


@router.post("/upload")
async def upload_document(
    file: UploadFile,
    manager: IngestionManager = Depends(get_ingestion_manager),
) -> dict[str, Any]:
    """Carga un documento y agenda su procesamiento en background."""

    raw = await file.read()
    try:
        text = raw.decode("utf-8", errors="ignore")
    except Exception:  # noqa: BLE001
        text = ""
    job = manager.enqueue(file.filename or "documento", text)
    return {"job_id": job.job_id, "status": job.status.value}


@router.get("/status/{job_id}")
async def ingestion_status(
    job_id: str,
    manager: IngestionManager = Depends(get_ingestion_manager),
) -> dict[str, Any]:
    """Consulta el estado de un job de ingesta."""

    job = manager.status(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job no encontrado")
    return {
        "job_id": job.job_id,
        "file_name": job.file_name,
        "status": job.status.value,
        "chunks": job.chunks,
        "embeddings": job.embeddings,
        "error": job.error,
    }
