# Build context: repository root.  docker build -f services/control-centre/Dockerfile .
# Plain Kubernetes/OpenShift: non-root, arbitrary-UID safe (group 0 permissions).
FROM ghcr.io/astral-sh/uv:0.11.32 AS uv

FROM python:3.12-slim AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
COPY shared ./shared
COPY services ./services
RUN uv sync --frozen --no-dev --no-editable --package govhub-control-centre

FROM python:3.12-slim
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
# Fictional demo tenants and users, and the sign-in role mapping; no other data.
COPY data/demo/tenants.toml ./data/demo/tenants.toml
COPY data/demo/users.toml ./data/demo/users.toml
COPY data/config/oidc-roles.toml ./data/config/oidc-roles.toml
# /keys: mount point for the development keys volume (Compose); real keys come from secrets.
RUN mkdir -p /keys && chgrp -R 0 /app /keys && chmod -R g=u /app /keys
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER 1001
EXPOSE 8000
CMD ["control-centre", "serve", "--host", "0.0.0.0", "--port", "8000"]
