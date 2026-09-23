import asyncio
import uuid

from app.core.celery_app import celery_app


@celery_app.task(name="data_import.run_import_job", bind=True)
def run_import_job(self, job_id: str) -> None:
    from app.modules.data_import.service import ImportService

    asyncio.run(ImportService().execute_job(uuid.UUID(job_id)))
