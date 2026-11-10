FROM python:3.13-slim
WORKDIR /app
COPY apps/worker/pyproject.toml ./pyproject.toml
COPY apps/worker/src ./src
RUN pip install --no-cache-dir .
ENV PYTHONPATH=/app/src
CMD ["celery", "-A", "store_operator_worker.celery_app:celery_app", "worker", "--loglevel=INFO"]
