from celery import Celery

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "lasatrading",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.modules.data_import.tasks",
        "app.modules.features.tasks",
        "app.modules.patterns.tasks",
        "app.modules.backtesting.tasks",
        "app.modules.alerts.tasks",
    ],
)

celery_app.conf.update(
    timezone="UTC",
    task_track_started=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    broker_connection_retry_on_startup=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_soft_time_limit=23 * 3600,
    task_time_limit=24 * 3600,
    # El evaluador de alertas se programa solo, con Celery Beat.
    #
    # El intervalo sale de `ALERTS_EVALUATE_SECONDS` y **no** es una preferencia de
    # eficiencia: el evaluador mira hacia atrás lo que pueda haberse cerrado entre
    # dos pasadas, y con velas de 1 minuto un intervalo largo pierde avisos sin
    # que nada falle. Ver `alerts.evaluator.velas_recientes`.
    beat_schedule={
        "evaluar-reglas-de-alertas": {
            "task": "alerts.evaluate_rules",
            "schedule": float(settings.ALERTS_EVALUATE_SECONDS),
        },
    },
)
