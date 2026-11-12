import os

from celery import Celery  # type: ignore[import-untyped]

from store_operator_worker.observability import configure_worker_logging

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
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    broker_transport_options={"visibility_timeout": 3600},
    task_default_queue="default",
    worker_hijack_root_logger=False,
    beat_schedule={
        "relay-postgres-outbox-every-second": {
            "task": "jobs.relay_outbox",
            "schedule": 1.0,
        },
        "expire-upload-intents-every-5-minutes": {
            "task": "media.expire_upload_intents",
            "schedule": 300.0,
        },
        "scan-quarantined-media-every-15-seconds": {
            "task": "media.scan_quarantined_assets",
            "schedule": 15.0,
        },
        "recover-expired-job-leases-every-30-seconds": {
            "task": "jobs.recover_expired_leases",
            "schedule": 30.0,
        },
    },
)

configure_worker_logging()

from store_operator_worker import ai_handlers as _ai_handlers  # noqa: F401
from store_operator_worker import ai_image_handlers as _ai_image_handlers  # noqa: F401
from store_operator_worker import tasks as _tasks  # noqa: F401


@celery_app.task(name="system.healthcheck")  # type: ignore[untyped-decorator]
def healthcheck() -> dict[str, str]:
    """Infrastructure smoke task."""
    return {"status": "ok"}
