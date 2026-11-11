FROM ghcr.io/astral-sh/uv:0.13.7 AS uv
FROM python:3.13-slim
COPY --from=uv /uv /uvx /bin/
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONPATH=/app/src:/app/api_src \
    PATH="/app/.venv/bin:$PATH"
COPY apps/api/pyproject.toml apps/api/uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY apps/worker/src ./src
COPY apps/api/src ./api_src
CMD ["celery", "-A", "store_operator_worker.celery_app:celery_app", "worker", "--loglevel=INFO", "--beat"]
