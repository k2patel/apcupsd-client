# syntax=docker/dockerfile:1.6
# NOTE: The primary build method is now melange + apko (see melange.yaml / apko.yaml).
# This Dockerfile is kept for local dev and Docker Compose backward compatibility.
ARG PYTHON_IMAGE=python:3.14.5-slim@sha256:c845af9399020c7e562969a13689e929074a10fd057acd1b1fad06a2fb068e97
ARG REQUIREMENTS_FILE=requirements.txt
FROM ${PYTHON_IMAGE} AS builder
ARG REQUIREMENTS_FILE

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential gcc \
    && rm -rf /var/lib/apt/lists/*

COPY ${REQUIREMENTS_FILE} requirements.txt
RUN pip install --upgrade pip && pip wheel --require-hashes --wheel-dir /wheels -r requirements.txt


FROM ${PYTHON_IMAGE} AS runtime
ARG REQUIREMENTS_FILE

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    REDIS_URL=redis://redis:6379/0

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends apcupsd curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 appuser \
    && useradd --system --uid 10001 --gid 10001 --home /app --shell /usr/sbin/nologin appuser

COPY --from=builder /wheels /wheels
COPY ${REQUIREMENTS_FILE} requirements.txt
RUN pip install --no-index --find-links=/wheels --require-hashes -r requirements.txt \
    && rm -rf /wheels

COPY app ./app

RUN chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -fsS http://localhost:8000/healthz || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
