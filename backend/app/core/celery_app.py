from celery import Celery

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "lasatrading",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["app.modules.data_import.tasks"],
)

celery_app.conf.update(
    timezone="UTC",
    task_track_started=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    broker_connection_retry_on_startup=True,
)
