# ---- Stage 1: build ----
FROM python:3.11-slim AS builder

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---- Stage 2: runtime ----
FROM python:3.11-slim AS runtime

# Modo Non-Root (UID > 10000) para cumplir políticas OpenShift.
RUN useradd --uid 10001 --create-home --shell /bin/bash appuser

WORKDIR /app
COPY --from=builder /install /usr/local
COPY src ./src
COPY schemas ./schemas
COPY pyproject.toml .

USER 10001

EXPOSE 8080
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8080"]
