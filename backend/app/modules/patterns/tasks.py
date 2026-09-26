import uuid

from app.core.celery_app import celery_app
from app.modules.patterns.service import PatternScanService


@celery_app.task(name="patterns.run_pattern_scan")
def run_pattern_scan(job_id: str) -> None:
    """Ejecuta el escaneo de un job de patrones.

    A diferencia de ``features.run_feature_job``, aqui NO se envuelve en
    ``asyncio.run``: ``FeatureService.execute_job`` es ``async def`` y lo
    necesita, pero ``PatternScanService.execute_scan`` es sincrona a proposito
    (su cuerpo es SQLAlchemy bloqueante mas pandas, sin un solo ``await``).

    ``asyncio.run`` exige una corrutina. Si se usara aqui, la expresion
    ``PatternScanService().execute_scan(...)`` se evaluaria antes de llamar a
    ``asyncio.run``, o sea que el escaneo se completaria de todos modos y
    justo despues fallaria con
    ``TypeError: An asyncio.Future, a coroutine or an awaitable is required``:
    el job quedaria ``completed`` en la base de datos con la tarea Celery en
    ``FAILURE``, que es peor que no tener tarea.

    El ``job_id`` llega como ``str`` porque el broker serializa los argumentos
    en JSON.
    """
    PatternScanService().execute_scan(uuid.UUID(job_id))
