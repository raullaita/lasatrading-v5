import asyncio
import uuid

from app.core.celery_app import celery_app
from app.modules.features.service import FeatureService


@celery_app.task(name="features.run_feature_job")
def run_feature_job(job_id: str) -> None:
    asyncio.run(FeatureService().execute_job(uuid.UUID(job_id)))
