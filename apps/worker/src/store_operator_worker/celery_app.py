import os

from celery import Celery

broker_url = os.environ.get("REDIS_URL")
if not broker_url:
    raise RuntimeError("REDIS_URL is required to start the worker")

celery_app = Celery("store_operator", broker=broker_url, backend=None)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    broker_transport_options={"visibility_timeout": 3600},
    task_default_queue="default",
)


@celery_app.task(name="system.healthcheck")
def healthcheck() -> dict[str, str]:
    """Infrastructure smoke task only; business job persistence is implemented in Issue #9."""
    return {"status": "ok"}
