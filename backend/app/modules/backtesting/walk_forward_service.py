"""Servicio de walk-forward: el puente entre el motor puro y la base de datos.

El motor (``walk_forward.py``) es una funcion pura: velas, señales y configuracion
dentro, informe fuera. Este modulo es lo unico que sabe de SQL, de Celery y de
estado, y su trabajo se puede resumir en una regla:

**Ni una simulacion se persiste.** Se ejecutan ``ventanas x combinaciones`` y se
guardan las ventanas y los candidatos. Las 1.200 simulaciones intermedias se
regeneran desde ``config`` y ``grid`` congelados. Esa es la diferencia entre un
informe que se puede auditar y una tabla de un millon de filas que no dice nada.

El estado del run vive en la base y no en el hilo, porque Celery ejecuta la tarea
en otro proceso: cancelar no es lanzar una excepcion, es escribir ``cancelled`` y
que el worker lo compruebe entre ventanas. Por eso ``execute_run`` comprueba la
cancelacion en la frontera de cada ventana y no dentro del motor: el motor es puro
y no tiene por que saber que existe un boton de cancelar.
"""

from __future__ import annotations

import math
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.modules.backtesting.analysis import SweepGrid
from app.modules.backtesting.models import (
    WalkForwardCandidate,
    WalkForwardEquityPoint,
    WalkForwardLog,
    WalkForwardRun,
    WalkForwardRunStatus,
    WalkForwardWindow,
)
from app.modules.backtesting.schemas import (
    WalkForwardCreateIn,
    WalkForwardEquitySeriesOut,
    WalkForwardReportOut,
    WalkForwardRunListOut,
    WalkForwardRunOut,
)

# Se importa del servicio de backtest y no se redefine: dos constantes magicas
# para el mismo lote divergen en cuanto alguien cambia una, y entonces un modulo
# escribe series de un tamaño y el otro de otro sin que nada falle.
from app.modules.backtesting.service import EQUITY_BATCH_SIZE
from app.modules.backtesting.walk_forward import (
    CandidateReport,
    WalkForwardCancelled,
    WalkForwardError,
    WalkForwardReport,
    WindowOutcome,
    WindowSpec,
    base_strategy,
    build_windows,
    run_walk_forward,
)
from app.modules.data.candles import load_candles
from app.modules.data.signals import load_signals
from app.modules.data_import.models import Candle
from app.modules.data_import.service import TIMEFRAME_MS
from app.modules.patterns.models import PatternScanJob, PatternScanJobStatus

#: Estados en los que un run ya no va a cambiar solo. El WebSocket los usa para
#: dejar de sondear, y ``_mark_run`` para no resucitar un run terminado.
TERMINAL_STATUSES = {
    WalkForwardRunStatus.COMPLETED.value,
    WalkForwardRunStatus.FAILED.value,
    WalkForwardRunStatus.CANCELLED.value,
}


class WalkForwardRunNotFound(Exception):
    pass


class WalkForwardScanNotReady(Exception):
    """El escaneo de origen no admite un walk-forward todavia."""


class WalkForwardRunNotFinished(Exception):
    """El run existe pero su informe todavia no se puede leer.

    Distinto de ``WalkForwardRunNotFound`` a proposito, y no por un capricho: son 404
    y 409. Un run en curso **existe**, y responder "no encontrado" llevaria al
    usuario a buscar un informe que si esta ahi, solo que todavia no ha
    terminado. Es el mismo motivo por el que ``BacktestService`` separa
    ``RunNotFound`` de ``RunNotFinished``.
    """


class TooManySimulations(Exception):
    """Las simulaciones que haria este run superan el tope pedido.

    Se comprueba en el servicio y no solo en el schema porque el numero de
    ventanas depende del rango real de las velas, que el cliente no conoce. El
    schema solo puede validar la rejilla; el total, aqui.
    """


class WalkForwardService:
    # ------------------------------------------------------------------ logs

    @staticmethod
    def _log(
        db: Session,
        run_id: uuid.UUID,
        level: str,
        message: str,
        progress: int | None = None,
    ) -> None:
        db.add(
            WalkForwardLog(
                run_id=run_id, level=level, message=message, progress=progress
            )
        )
        db.flush()

    def _log_committed(
        self,
        run_id: uuid.UUID,
        level: str,
        message: str,
        progress: int | None = None,
    ) -> None:
        with SessionLocal() as db:
            try:
                self._log(db, run_id, level, message, progress)
                db.commit()
            except IntegrityError:
                # Sin run no hay logs: lo prohib la FK. Este camino se alcanza
                # sobre todo desde el manejador de errores de ``execute_run``, y
                # tragarse la excepcion aqui evita que un fallo al registrar el
                # fallo tape el fallo original y deje al worker sin traza util.
                db.rollback()

    # --------------------------------------------------------------- helpers

    @staticmethod
    def _minutes_per_candle(timeframe: str) -> int:
        """Minutos de una vela, para la cola de ``max_hold``.

        Sale de ``TIMEFRAME_MS`` y no de un ``if`` por timeframe: un solo sitio
        donde anadir un timeframe nuevo, y un timeframe desconocido falla en vez
        de devolver 60 y resolver la cola con el valor equivocado en silencio.
        """
        if timeframe not in TIMEFRAME_MS:
            raise WalkForwardError(f"Timeframe no soportado: {timeframe}")
        return TIMEFRAME_MS[timeframe] // 60_000

    @staticmethod
    def _spec(config: WalkForwardCreateIn) -> WindowSpec:
        return WindowSpec(
            window_days=config.window_days,
            oos_days=config.oos_days,
            step_days=config.step_days,
            min_windows=config.min_windows,
            min_trades=config.min_trades,
            holdout_days=config.holdout_days,
            beats_market_ratio=config.beats_market_ratio,
            regimes_declared=config.regimes_declared,
            max_simulations=config.max_simulations,
        )

    @staticmethod
    def _grid(config: WalkForwardCreateIn) -> SweepGrid:
        return SweepGrid(
            take_profit_pcts=tuple(config.grid.take_profit_pcts),
            stop_loss_pcts=tuple(config.grid.stop_loss_pcts),
            max_holds=tuple(config.grid.max_holds),
        )

    @staticmethod
    def _count_windows(db: Session, scan: PatternScanJob, spec: WindowSpec) -> int:
        """Cuantas ventanas haria este run, sin cargar las velas.

        Se cuentan sobre el primer y el ultimo timestamp **real** de las velas,
        no sobre el rango declarado del escaneo, y esa distincion es la que hace
        que el 422 sea exacto. Un escaneo puede declarar un rango que no cubre
        entero, y contar ventanas sobre fechas que no existen daria un numero
        distinto al que el motor va a construir, con lo que el 422 pasaria o
        fallaria donde no toca.

        Son dos ``min``/``max`` sobre una hypertable con indice, no un ``load``.
        """
        fila = db.execute(
            select(func.min(Candle.timestamp), func.max(Candle.timestamp))
            .where(Candle.symbol == scan.symbol)
            .where(Candle.timeframe == scan.timeframe)
            .where(Candle.timestamp >= scan.date_from)
            .where(Candle.timestamp <= scan.date_to)
        ).one()
        if fila[0] is None or fila[1] is None:
            return 0
        return len(
            build_windows(
                pd.Timestamp(fila[0]),
                pd.Timestamp(fila[1]),
                spec,
            )
        )

    # -------------------------------------------------------------- gestion

    def create_run(self, db: Session, config: WalkForwardCreateIn) -> WalkForwardRun:
        """Crea el run con la configuracion resuelta y congelada.

        Se exige que el escaneo este completado, por el mismo motivo que en el
        backtest: uno en curso tiene solo parte de sus ocurrencias, y un
        walk-forward sobre un subconjunto daria un informe que luego no se
        reproduce al terminar el escaneo.

        El tope de simulaciones se comprueba **aqui** y no en el worker. Es la
        ultima vez que se puede cheaply: construir ventanas necesita el rango de
        las velas, y para eso hace falta el escaneo, y para eso hace falta que
        este endpoint se haya llamado. Un trabajo que muere a los cinco minutos
        con "son 4.300 simulaciones y el tope es 2.000" le hace perder al usuario
        cinco minutos para aprender algo que se sabia antes de empezar.
        """
        scan = db.get(PatternScanJob, config.scan_job_id)
        if scan is None:
            raise WalkForwardRunNotFound("El escaneo de origen no existe")
        if scan.status != PatternScanJobStatus.COMPLETED.value:
            raise WalkForwardScanNotReady(
                f"El escaneo {str(scan.id)[:8]} está en estado '{scan.status}'. "
                "Solo se pueden lanzar walk-forwards sobre escaneos completados."
            )

        spec = self._spec(config)
        grid = self._grid(config)
        minutos = self._minutes_per_candle(scan.timeframe)

        ventanas = self._count_windows(db, scan, spec)
        if ventanas == 0:
            raise WalkForwardScanNotReady(
                f"No hay velas de {scan.symbol} {scan.timeframe} en el rango del "
                "escaneo, así que no hay ni una ventana que construir"
            )
        combinaciones = grid.combinations()
        simulaciones = ventanas * combinaciones
        if simulaciones > config.max_simulations:
            raise TooManySimulations(
                f"Son {simulaciones} simulaciones ({ventanas} ventanas x "
                f"{combinaciones} combinaciones) y el tope es "
                f"{config.max_simulations}: reduce la rejilla, agranda las "
                "ventanas o sube el tope"
            )

        run = WalkForwardRun(
            scan_job_id=scan.id,
            status=WalkForwardRunStatus.PENDING.value,
            config={
                "window_days": config.window_days,
                "oos_days": config.oos_days,
                "step_days": config.step_days,
                "min_windows": config.min_windows,
                "min_trades": config.min_trades,
                "holdout_days": config.holdout_days,
                "beats_market_ratio": config.beats_market_ratio,
                "regimes_declared": config.regimes_declared,
                "max_simulations": config.max_simulations,
                "minutes_per_candle": minutos,
                "symbols": scan.symbol,
                "timeframe": scan.timeframe,
            },
            grid={
                "take_profit_pcts": list(config.grid.take_profit_pcts),
                "stop_loss_pcts": list(config.grid.stop_loss_pcts),
                "max_holds": list(config.grid.max_holds),
                "combinations": combinaciones,
            },
            initial_capital=Decimal("1000"),
            windows=ventanas,
            simulations=simulaciones,
        )
        db.add(run)
        db.flush()
        self._log(
            db,
            run.id,
            "info",
            f"Walk-forward creado sobre {scan.symbol} {scan.timeframe}: "
            f"{ventanas} ventanas x {combinaciones} combinaciones = "
            f"{simulaciones} simulaciones",
        )
        db.commit()
        db.refresh(run)
        return run

    def cancel_run(self, run_id: uuid.UUID) -> bool:
        """Pide cancelar. El motor lo comprueba entre ventanas.

        Devuelve ``False`` si el run no existe o ya estaba en estado terminal: no
        se puede cancelar un informe que ya termino, y avisar de eso con un
        409 es mas util que devolver un exito que no cambio nada.
        """
        with SessionLocal() as db:
            run = db.get(WalkForwardRun, run_id)
            if run is None:
                return False
            if run.status in TERMINAL_STATUSES:
                return False
            run.status = WalkForwardRunStatus.CANCELLED.value
            run.finished_at = datetime.now(timezone.utc)
            self._log(db, run_id, "info", "Cancelación solicitada")
            db.commit()
            return True

    def _mark_run(
        self,
        run_id: uuid.UUID,
        status: str,
        started_at: bool = False,
        finished_at: bool = False,
    ) -> None:
        with SessionLocal() as db:
            run = db.get(WalkForwardRun, run_id)
            if run is None:
                return
            # Un run cancelado se queda cancelado. Sin este corte, cancelar
            # entre que Celery encola la tarea y la tarea arranca no serviria de
            # nada: ``execute_run`` marcaria "en curso" por encima del
            # "cancelado" del usuario y el ``is_cancelled`` posterior ya no
            # encontraria nada, asi que el walk-forward entero se ejecutaria
            # como si nadie lo hubiera parado. La carrera es real porque
            # encolar y arrancar no son el mismo instante.
            if (
                run.status == WalkForwardRunStatus.CANCELLED.value
                and status != WalkForwardRunStatus.CANCELLED.value
            ):
                return
            run.status = status
            if started_at:
                run.error_message = None
                if run.started_at is None:
                    run.started_at = datetime.now(timezone.utc)
            if finished_at and run.finished_at is None:
                run.finished_at = datetime.now(timezone.utc)
            db.commit()

    @staticmethod
    def is_cancelled(run_id: uuid.UUID) -> bool:
        with SessionLocal() as db:
            run = db.get(WalkForwardRun, run_id)
            return (
                run is not None and run.status == WalkForwardRunStatus.CANCELLED.value
            )

    # ------------------------------------------------------------- ejecucion

    def execute_run(self, run_id: uuid.UUID) -> None:
        """Punto de entrada de Celery. Envoltorio de excepcion.

        El fallo de un run de walk-forward **deja informe**: o se escribe lo que
        se pudo o se escribe el motivo, y nunca se deja el run en ``processing``
        para siempre. Un informe colgado no es un informe a medias, es un informe
        que miente sobre si existe.
        """
        try:
            self._mark_run(
                run_id, WalkForwardRunStatus.PROCESSING.value, started_at=True
            )
            if self.is_cancelled(run_id):
                return
            self._run(run_id)
        except WalkForwardCancelled:
            # Cancelar no es fallar. El motor levanta esta excepcion para no
            # devolver un informe a medias, y aqui solo se confirma que el run
            # se queda en `cancelled` con su `finished_at`. Sin este brazo, el
            # `except Exception` de abajo marcaria el run como `failed` con un
            # error que no es un error, y el usuario veria un fallo donde solo
            # habia pulsado cancelar.
            self._mark_run(
                run_id, WalkForwardRunStatus.CANCELLED.value, finished_at=True
            )
        except Exception as exc:
            self._mark_run(run_id, WalkForwardRunStatus.FAILED.value, finished_at=True)
            self._log_committed(run_id, "error", f"Error en walk-forward: {exc}")
            with SessionLocal() as db:
                run = db.get(WalkForwardRun, run_id)
                if run:
                    run.error_message = str(exc)[:500]
                    db.commit()

    def _run(self, run_id: uuid.UUID) -> None:
        with SessionLocal() as db:
            run = db.get(WalkForwardRun, run_id)
            if run is None:
                raise WalkForwardRunNotFound("El run no existe")
            scan = db.get(PatternScanJob, run.scan_job_id)
            if scan is None:
                raise WalkForwardRunNotFound("El escaneo de origen ya no existe")
            symbol, timeframe = scan.symbol, scan.timeframe
            date_from, date_to = scan.date_from, scan.date_to
            config = dict(run.config)
            grid = dict(run.grid)

        minutos = int(config["minutes_per_candle"])
        spec = WindowSpec(
            window_days=int(config["window_days"]),
            oos_days=int(config["oos_days"]),
            step_days=int(config["step_days"]),
            min_windows=int(config["min_windows"]),
            min_trades=int(config["min_trades"]),
            holdout_days=int(config["holdout_days"]),
            beats_market_ratio=float(config["beats_market_ratio"]),
            regimes_declared=int(config["regimes_declared"]),
            max_simulations=int(config["max_simulations"]),
        )
        rejilla = SweepGrid(
            take_profit_pcts=tuple(grid["take_profit_pcts"]),
            stop_loss_pcts=tuple(grid["stop_loss_pcts"]),
            max_holds=tuple(grid["max_holds"]),
        )

        self._log_committed(run_id, "info", f"Cargando velas de {symbol} {timeframe}")
        candles = load_candles(symbol, timeframe, date_from, date_to)
        if candles.empty:
            raise WalkForwardError(
                f"No hay velas de {symbol} {timeframe} en el rango del escaneo"
            )
        with SessionLocal() as db:
            signals = load_signals(db, run.scan_job_id)
        self._log_committed(
            run_id, "info", f"{len(candles)} velas y {len(signals)} señales cargadas"
        )

        if self.is_cancelled(run_id):
            self._log_committed(run_id, "info", "Cancelado antes de empezar")
            return

        # El motor es puro y no sabe que existe un boton de cancelar, asi que el
        # corte va aqui: un ``on_progress`` que devuelve ``False`` es la senal de
        # "el usuario pidio parar", y el motor abandona en la frontera de la
        # ventana, que es donde se puede abandonar sin dejar el informe a medias
        # sin querer.
        # El base sale de la primera celda valida de la rejilla y no de valores
        # inventados: TP, SL y max_hold los sobrescriben siempre, pero si algo se
        # escapara, simularia una combinacion que el usuario pidio.
        base = base_strategy(rejilla, float(run.initial_capital))

        # El reloj empieza **antes** de cargar velas. Medir solo el motor
        # compararía el trabajo del motor con lo que cuesta traerlo, y el
        # usuario ve un tiempo en el que no esta esperando el motor sino la
        # base de datos. Los dos son tiempo suyo.
        started = time.perf_counter()
        informe = run_walk_forward(
            candles,
            signals,
            base,
            rejilla,
            spec,
            minutos_por_vela=minutos,
            on_progress=self._progreso(run_id, spec),
        )

        if self.is_cancelled(run_id):
            self._log_committed(run_id, "info", "Cancelado antes de escribir")
            return

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        self._guardar(run_id, informe, base.initial_capital, elapsed_ms)
        self._log_committed(
            run_id,
            "info",
            f"Informe guardado: {len(informe.windows)} ventanas, "
            f"{len(informe.candidates)} candidatos, "
            f"{informe.simulations} simulaciones",
            100,
        )
        self._mark_run(run_id, WalkForwardRunStatus.COMPLETED.value, finished_at=True)

    def _progreso(self, run_id: uuid.UUID, spec: WindowSpec):
        """Devuelve el callback de progreso que usa el motor.

        Se construye una vez y se pasa a ``run_walk_forward``. Cada llamada es un
        commit contra la base, y por eso van espaciadas: el motor reporta por
        **ventana**, no por simulacion, y una simulacion dura 60 ms y no produce
        ningun dato que contar.
        """

        def on_progress(hechas: int, total: int, etiqueta: str) -> bool:
            if self.is_cancelled(run_id):
                self._log_committed(
                    run_id, "info", f"Cancelado en la ventana {hechas}/{total}"
                )
                return False
            porcentaje = int(hechas * 100 / total) if total else 100
            self._log_committed(run_id, "info", etiqueta, porcentaje)
            return True

        return on_progress

    # ------------------------------------------------------------ persistencia

    def _guardar(
        self,
        run_id: uuid.UUID,
        informe: WalkForwardReport,
        capital: float,
        elapsed_ms: int | None = None,
    ) -> None:
        """Escribe ventanas, candidatos y curva. Idempotente por ``run_id``.

        Se borra lo anterior antes de escribir, en vez de hacer upsert. Un
        requeue relanza el motor entero y produce un informe nuevo; lo que
        importa es que la tabla refleje **el ultimo** intento, no la union de los
        dos, porque un informe que mezcla dos ejecuciones con distinta
        ``seed`` de bootstrap no es reproducible.
        """
        with SessionLocal() as db:
            run = db.get(WalkForwardRun, run_id)
            if run is None:
                return
            db.query(WalkForwardWindow).filter(
                WalkForwardWindow.run_id == run_id
            ).delete()
            db.query(WalkForwardCandidate).filter(
                WalkForwardCandidate.run_id == run_id
            ).delete()
            db.query(WalkForwardEquityPoint).filter(
                WalkForwardEquityPoint.run_id == run_id
            ).delete()

            for outcome in informe.windows:
                db.add(self._window_row(run_id, outcome))
            for rank, cand in enumerate(informe.candidates, start=1):
                db.add(self._candidate_row(run_id, rank, cand))
            self._equity_rows(db, run_id, informe)

            run.windows = len(informe.windows)
            run.windows_without_selection = informe.windows_without_selection
            run.simulations = informe.simulations
            if elapsed_ms is not None:
                run.elapsed_ms = elapsed_ms
            curva = informe.oos_equity
            if curva is not None and not curva.empty:
                run.equity_final = Decimal(str(float(curva["equity"].iloc[-1])))
                run.oos_return_pct = Decimal(
                    str(float(curva["equity"].iloc[-1] / capital - 1) * 100)
                )
                run.market_return_pct = Decimal(
                    str(float(curva["market_equity"].iloc[-1] / capital - 1) * 100)
                )
                run.max_drawdown_pct = Decimal(str(float(curva["drawdown_pct"].max())))
            db.commit()

    @staticmethod
    def _window_row(run_id: uuid.UUID, outcome: WindowOutcome) -> WalkForwardWindow:
        w = outcome.window
        o = outcome.oos
        s = outcome.selected
        return WalkForwardWindow(
            run_id=run_id,
            index=w.index,
            is_from=w.is_from.to_pydatetime(),
            is_to=w.is_to.to_pydatetime(),
            oos_from=w.oos_from.to_pydatetime(),
            oos_to=w.oos_to.to_pydatetime(),
            selected_strategy={
                "take_profit_pct": s.take_profit_pct,
                "stop_loss_pct": s.stop_loss_pct,
                "max_hold": s.max_hold,
            },
            is_sharpe=Decimal(str(outcome.is_sharpe)),
            oos_trades=o.trades,
            oos_evaluated=o.evaluated,
            oos_return_pct=Decimal(str(o.return_pct)),
            oos_net_pnl=Decimal(str(o.net_pnl)),
            oos_equity_final=Decimal(str(o.equity_final)),
            oos_win_rate=(Decimal(str(o.win_rate)) if o.win_rate is not None else None),
            oos_sharpe=Decimal(str(o.sharpe)) if o.sharpe is not None else None,
            oos_max_drawdown_pct=Decimal(str(o.max_drawdown_pct)),
            market_return_pct=Decimal(str(o.market_return_pct)),
            market_max_drawdown_pct=Decimal(str(o.market_max_drawdown_pct)),
            exits=dict(o.exits),
        )

    @staticmethod
    def _candidate_row(
        run_id: uuid.UUID, rank: int, cand: CandidateReport
    ) -> WalkForwardCandidate:
        s = cand.strategy
        return WalkForwardCandidate(
            run_id=run_id,
            rank=rank,
            take_profit_pct=(
                Decimal(str(s.take_profit_pct))
                if s.take_profit_pct is not None
                else None
            ),
            stop_loss_pct=(
                Decimal(str(s.stop_loss_pct)) if s.stop_loss_pct is not None else None
            ),
            max_hold=s.max_hold,
            windows=cand.windows,
            trades=cand.trades,
            beats_market_windows=cand.beats_market_windows,
            profitable_windows=cand.profitable_windows,
            oos_return_pct=Decimal(str(cand.oos_return_pct)),
            market_return_pct=Decimal(str(cand.market_return_pct)),
            win_rate_mean=Decimal(str(cand.win_rate_mean)),
            sharpe_mean=Decimal(str(cand.sharpe_mean)),
            sharpe_dispersion=Decimal(str(cand.sharpe_dispersion)),
            max_drawdown_worst=Decimal(str(cand.max_drawdown_worst)),
            consistency=Decimal(str(cand.consistency)),
            score=Decimal(str(cand.score)),
            # El veredicto del motor es un ``Literal`` de texto, no un enum: se
            # guarda tal cual. Con ``.value`` aqui fallaba al ejecutar, y solo lo
            # detecta un test de extremo a extremo, porque los dataclasses del
            # motor no pasan por pydantic.
            verdict=str(cand.verdict),
            ci95_low=(Decimal(str(cand.ci95[0])) if cand.ci95 is not None else None),
            ci95_high=(Decimal(str(cand.ci95[1])) if cand.ci95 is not None else None),
            rejections=list(cand.rejections),
            notes=list(cand.notes),
        )

    def _equity_rows(
        self, db: Session, run_id: uuid.UUID, informe: WalkForwardReport
    ) -> int:
        curva = informe.oos_equity
        if curva is None or curva.empty:
            return 0
        # La ventana de cada tramo se reconstruye aqui porque el motor devuelve
        # una curva continua y sin esa columna no se puede contrastar un tramo
        # del grafico con su fila de ``walk_forward_windows``.
        filas = []
        ventana_actual = 0
        # ``informe.windows`` son ``WindowOutcome``, no ``Window``: el indice
        # cuelga de ``outcome.window``. Con ``w.index`` esto reventaba al
        # escribir la curva, y solo lo ve un test de extremo a extremo.
        rango_ventanas = [
            (
                outcome.window.index,
                outcome.window.oos_from.to_pydatetime(),
                outcome.window.oos_to.to_pydatetime(),
            )
            for outcome in informe.windows
        ]
        for marca, fila in curva.iterrows():
            ts = marca.to_pydatetime()
            while (
                ventana_actual + 1 < len(rango_ventanas)
                and ts > rango_ventanas[ventana_actual][2]
            ):
                ventana_actual += 1
            filas.append(
                {
                    "run_id": run_id,
                    "timestamp": ts,
                    "equity": Decimal(str(float(fila["equity"]))),
                    "market_equity": Decimal(str(float(fila["market_equity"]))),
                    "drawdown_pct": Decimal(str(float(fila["drawdown_pct"]))),
                    "window_index": rango_ventanas[ventana_actual][0]
                    if rango_ventanas
                    else 0,
                }
            )
        # A lotes, y por el mismo motivo que ``_save_equity`` del backtest: un
        # rango de cinco anos a 1h son unas 44.000 velas, y un solo INSERT con
        # seis parametros por fila son 264.000 parametros en un unico statement.
        # Eso no es un problema de memoria, es un statement que la libreria de
        # postgres no sabe enviar, y el fallo aparece en produccion y no en el
        # test con una serie corta.
        tabla = WalkForwardEquityPoint.__table__
        for inicio in range(0, len(filas), EQUITY_BATCH_SIZE):
            db.execute(pg_insert(tabla), filas[inicio : inicio + EQUITY_BATCH_SIZE])
        return len(filas)

    # ------------------------------------------------------------- lectura

    def get_run(self, db: Session, run_id: uuid.UUID) -> WalkForwardRun:
        run = db.get(WalkForwardRun, run_id)
        if run is None:
            raise WalkForwardRunNotFound("Walk-forward no encontrado")
        return run

    def get_report(self, db: Session, run_id: uuid.UUID) -> WalkForwardReportOut:
        """El informe completo: cabecera, ventanas y candidatos.

        Se exige ``completed``. Un informe a medias no es un informe con menos
        filas, es un informe cuyo veredicto no se puede leer: las candidatas que
        faltan son justo las que no han pasado las guardas.
        """
        run = self.get_run(db, run_id)
        if run.status != WalkForwardRunStatus.COMPLETED.value:
            raise WalkForwardRunNotFinished(
                f"El walk-forward está en estado '{run.status}': no hay informe "
                "que leer todavía"
            )
        return WalkForwardReportOut(
            run=WalkForwardRunOut.model_validate(run),
            windows=list(run.window_rows),
            candidates=list(run.candidate_rows),
        )

    def get_equity(
        self, db: Session, run_id: uuid.UUID, max_points: int | None = None
    ) -> WalkForwardEquitySeriesOut:
        """Curva OOS encadenada y benchmark, submuestreada si es larga.

        Submuestreo por paso constante, igual que el del backtest: no conserva la
        forma con fidelidad estadistica, pero conserva extremos y picos. El
        ``max_drawdown_pct`` sale del run y no de la serie submuestreada, porque
        el maximo real puede caer entre dos puntos seguidas y recalcularlo aqui
        daria un valor distinto al de la cabecera.
        """
        run = self.get_run(db, run_id)
        total = (
            db.scalar(
                select(func.count())
                .select_from(WalkForwardEquityPoint)
                .where(WalkForwardEquityPoint.run_id == run_id)
            )
            or 0
        )
        stmt = select(WalkForwardEquityPoint).where(
            WalkForwardEquityPoint.run_id == run_id
        )
        if max_points and total > max_points:
            step = math.ceil(total / max_points)
            numerada = (
                select(
                    WalkForwardEquityPoint.timestamp.label("timestamp"),
                    func.row_number()
                    .over(order_by=WalkForwardEquityPoint.timestamp)
                    .label("rn"),
                )
                .where(WalkForwardEquityPoint.run_id == run_id)
                .subquery()
            )
            # Se conserva tambien la ultima fila a proposito: con
            # ``(rn - 1) % step == 0`` solo el primer punto se conserva siempre,
            # y una curva que no llega al cierre no enseña el ``equity_final``
            # que dice la cabecera.
            stmt = stmt.where(
                WalkForwardEquityPoint.timestamp.in_(
                    select(numerada.c.timestamp).where(
                        ((numerada.c.rn - 1) % step == 0) | (numerada.c.rn == total)
                    )
                )
            )
        puntos = db.scalars(stmt.order_by(WalkForwardEquityPoint.timestamp)).all()
        return WalkForwardEquitySeriesOut(
            points=puntos,
            total_points=total,
            returned=len(puntos),
            max_drawdown_pct=run.max_drawdown_pct,
        )

    def list_runs(
        self, db: Session, limit: int = 50, offset: int = 0
    ) -> WalkForwardRunListOut:
        total = db.scalar(select(func.count()).select_from(WalkForwardRun)) or 0
        runs = db.scalars(
            select(WalkForwardRun)
            .order_by(WalkForwardRun.created_at.desc())
            .limit(limit)
            .offset(offset)
        ).all()
        return WalkForwardRunListOut(
            runs=[WalkForwardRunOut.model_validate(r) for r in runs], total=total
        )
