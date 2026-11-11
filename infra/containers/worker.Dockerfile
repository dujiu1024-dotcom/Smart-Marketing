FROM ghcr.io/astral-sh/uv:0.13.7 AS uv
FROM python:3.13-slim
COPY --from=uv /uv /uvx /bin/
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONPATH=/app/src \
    PATH="/app/.venv/bin:$PATH"
COPY apps/worker/pyproject.toml apps/worker/uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY apps/worker/src ./src
CMD ["celery", "-A", "store_operator_worker.celery_app:celery_app", "worker", "--loglevel=INFO"]
