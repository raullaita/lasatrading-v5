import uuid

from app.core.celery_app import celery_app
from app.modules.backtesting.service import BacktestService


@celery_app.task(name="backtest.run_backtest")
def run_backtest_task(run_id: str) -> None:
    """Ejecuta la simulacion de un run.

    Sin ``asyncio.run``, igual que ``patterns.run_pattern_scan``:
    ``execute_run`` es sincrona a proposito (SQLAlchemy bloqueante mas pandas),
    y envolverla haria que la simulacion se completara y la tarea fallara
    despues con ``TypeError: a coroutine was expected``, dejando el run
    ``completed`` en la base con la tarea Celery en ``FAILURE``.

    El ``run_id`` llega como ``str`` porque el broker serializa los argumentos
    en JSON.
    """
    BacktestService().execute_run(uuid.UUID(run_id))
