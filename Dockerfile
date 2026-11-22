# syntax=docker/dockerfile:1.7

FROM node:24-bookworm-slim AS frontend-build
WORKDIR /build/frontend
RUN corepack enable
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/index.html frontend/tsconfig.json frontend/vite.config.ts ./
COPY frontend/src ./src
COPY docs/openapi.json /build/docs/openapi.json
RUN pnpm build

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    TOKENIZERS_PARALLELISM=false \
    T2T_DB=/app/state/text2task.db \
    T2T_ENTITY_MODEL=/app/models/entity \
    T2T_RELATION_MODEL=/app/models/relation \
    T2T_FRONTEND_DIST=/app/frontend/dist \
    T2T_RESULTS_DIR=/app/results \
    T2T_TZ=UTC

WORKDIR /app
RUN groupadd --system --gid 10001 text2task \
    && useradd --system --uid 10001 --gid text2task --home-dir /app text2task

COPY requirements.runtime.txt ./
# Install the CPU-only wheel explicitly. The default PyPI wheel can pull CUDA
# runtime packages into Linux images even though this inference service does not
# use CUDA (and Docker Desktop on Apple Silicon cannot expose MPS to containers).
RUN python -m pip install --no-cache-dir \
        --index-url https://download.pytorch.org/whl/cpu \
        "torch==2.15.0+cpu" \
    && python -m pip install --no-cache-dir -r requirements.runtime.txt

COPY src ./src
COPY configs ./configs
COPY results ./results
COPY --from=frontend-build /build/frontend/dist ./frontend/dist
COPY --chown=text2task:text2task docker/model_bundle/entity ./models/entity
COPY --chown=text2task:text2task docker/model_bundle/relation ./models/relation
COPY --chown=text2task:text2task docker/model_bundle/manifest.json ./models/manifest.json

RUN mkdir -p /app/state \
    && chown -R text2task:text2task /app/state
USER text2task

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/system/health', timeout=3)"]

CMD ["python", "-m", "uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
