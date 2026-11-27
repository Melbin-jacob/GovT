# Build context: repository root.  docker build -f services/rulebook/Dockerfile .
# Runs on plain Kubernetes/OpenShift: no cloud-specific services, non-root,
# works under an arbitrary UID (group 0 permissions), no runtime network calls.
FROM ghcr.io/astral-sh/uv:0.11.32 AS uv

FROM python:3.12-slim AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
COPY shared ./shared
COPY services/rulebook ./services/rulebook
RUN uv sync --frozen --no-dev --no-editable --package govhub-rulebook

FROM python:3.12-slim
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY data ./data
COPY schemas ./schemas
# /checkpoints: mount point for the approval-log checkpoint volume (separate from the DB).
RUN mkdir -p /checkpoints && chgrp -R 0 /app /checkpoints && chmod -R g=u /app /checkpoints
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER 1001
EXPOSE 8000
# --migrate applies Alembic migrations at start-up (idempotent). On Kubernetes you may prefer
# a separate `rulebook migrate` Job and drop the flag.
CMD ["rulebook", "serve", "--migrate", "--host", "0.0.0.0", "--port", "8000"]
