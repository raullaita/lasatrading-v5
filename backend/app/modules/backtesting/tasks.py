import uuid

from app.core.celery_app import celery_app
from app.modules.backtesting.service import BacktestService
from app.modules.backtesting.walk_forward_service import WalkForwardService


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


@celery_app.task(name="backtest.run_walk_forward")
def run_walk_forward_task(run_id: str) -> None:
    """Ejecuta el walk-forward de un run.

    Sin ``asyncio.run``, igual que ``run_backtest_task``, y por el mismo motivo
    exacto: ``execute_run`` es sincrona a proposito (SQLAlchemy bloqueante mas
    pandas), y envolverla haria que la simulacion se completara y la tarea
    fallara despues con ``TypeError: a coroutine was expected``, dejando el
    informe ``completed`` en la base y la tarea Celery en ``FAILURE``.

    Y sin ``soft_time_limit``: el motor no lleva reloj. Un limite de tiempo
    mataria la tarea a mitad de la otra ventana y dejaria un informe sin
    candidato, que es peor que un informe que tarda. Cancelar es una decision
    del usuario, y va por el estado del run, no por un reloj.
    """
    WalkForwardService().execute_run(uuid.UUID(run_id))
