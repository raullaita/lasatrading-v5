"""Orquestacion del backtesting: entrada del motor, persistencia y consulta.

Clon de ``PatternScanService`` en estructura y estilos, con las diferencias que
impone el dominio:

* El trabajo pesado (simular) son milisegundos, no minutos. El recorrido de
  velas ya lo hace el motor vectorizado, asi que **no se reporta progreso por
  vela**: un run de 0.5 s no tiene nada que contar y un progreso inventado seria
  mentira. Los logs son por etapa.

* La cancelacion se comprueba **entre lotes de escritura**, no durante la
  simulacion. Interrumpir un ``numpy`` a mitad no es posible sin cooperation en
  el propio motor, y para un trabajo de medio segundo no merece la pena
  ensuciarlo. Cancelar un run ya terminado devuelve ``False`` y el endpoint
  responde 409, para que la UI pueda explicar que llego tarde.

* Los filtros de patrones y direcciones **viajan dentro de la columna
  ``strategy``**, no aparte. Un run sobre 3 de los 8 patrones es un run
  distinto al de los 8, asi que el filtro forma parte de su identidad: si solo
 viviera en la peticion, un requeue lo simularia sobre otro conjunto de señales
  sin avisar, y los dos runs comparados en la tabla no harian lo mismo.

* Las metricas de cabecera se **copian del resultado del motor** a
  ``backtest_runs`` en vez de recalcularse en cada lectura. Son las que se leen
  en la lista y en la tarjeta, y derivarlas de miles de operaciones en cada
  ``GET`` de una tabla paginada seria tirar CPU para pintar 20 filas.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

import pandas as pd
from sqlalchemy import Integer, Text, cast, delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.modules.backtesting.engine import (
    BacktestResult,
    StrategyConfig,
    TradeResult,
    run_backtest,
)
from app.modules.backtesting.models import (
    BacktestEquityPoint,
    BacktestLog,
    BacktestRun,
    BacktestRunStatus,
    BacktestTrade,
)
from app.modules.backtesting.schemas import (
    BacktestCreateIn,
    BacktestEquitySeriesOut,
    BacktestExitReasonOut,
    BacktestPatternBreakdownOut,
    BacktestSummaryOut,
)
from app.modules.data.candles import load_candles
from app.modules.patterns.models import (
    PatternOccurrence,
    PatternScanJob,
    PatternScanJobStatus,
)

#: Filas por lote al insertar, igual que en ``PatternScanService``.
TRADE_BATCH_SIZE = 2000
EQUITY_BATCH_SIZE = 5000

#: Estados desde los que todavia tiene sentido relanzar un run. ``failed`` **no**
#: esta aqui: el fallo habitual es un escaneo origen que no estaba completo, el
#: usuario lo termina y relanza *ese* run. Ver ``NON_REQUEUEABLE_STATUSES`` en
#: ``patterns.service``, que razona igual.
NON_REQUEUEABLE_STATUSES = frozenset(
    {
        BacktestRunStatus.COMPLETED.value,
        BacktestRunStatus.CANCELLED.value,
    }
)

#: Columnas de las metricas de cabecera que un requeue pone a cero.
RESET_ON_REQUEUE = (
    "equity_final",
    "net_pnl",
    "total_return_pct",
    "win_rate",
    "profit_factor",
    "max_drawdown_pct",
    "sharpe_ratio",
    "avg_bars_held",
)

#: Motivos que cuentan como resultado de la estrategia. Coincide con el motor;
#: se replica aqui porque el desglose se agrega en SQL, y en SQL no se importa
#: el modulo del motor. Si se separaran, el ``win_rate`` de la tarjeta y el del
#: desglose por patron darian numeros distintos.
COUNTED_EXIT_REASONS = ("take_profit", "stop_loss", "timeout")

#: Columnas por las que se puede ordenar, en lista blanca. Sin ella el nombre
#: llega del cliente a un ``ORDER BY`` y a un ``getattr`` sobre la clase ORM.
SORTABLE_TRADE_COLUMNS = {
    "entry_timestamp": BacktestTrade.entry_timestamp,
    "exit_timestamp": BacktestTrade.exit_timestamp,
    "net_pnl": BacktestTrade.net_pnl,
    "return_pct": BacktestTrade.return_pct,
    "bars_held": BacktestTrade.bars_held,
    "mae": BacktestTrade.mae,
    "mfe": BacktestTrade.mfe,
}


class RunNotFound(Exception):
    pass


class ScanNotReady(Exception):
    """El escaneo de origen no admite una simulacion todavia."""


def _direction_column() -> Text:
    """La columna JSONB de direccion de ``pattern_occurrences``, como texto.

    Dos trampas, las dos ya pisadas al escribir esto:

    1. Va por ``__table__`` (Core) y **no** por la clase ORM a proposito: la
       clase declarativa expone esa columna como ``details``, porque
       ``metadata`` esta reservado en SQLAlchemy, asi que
       ``PatternOccurrence.metadata`` resuelve al ``MetaData`` de la clase y
       subscriptarlo revienta con ``'MetaData' object is not subscriptable``. Es
       el mismo motivo por el que ``PatternScanService._save_occurrences``
       inserta contra ``__table__``.

    2. Se usa ``jsonb_extract_path_text`` (``->>``) y no un ``cast`` sobre
       ``c.metadata["direction"]``. En Core ese subscripto genera ``->``, y
       castear a texto el resultado de ``->`` deja el valor **tal cual lo
       serializa JSON**, es decir ``'"bullish"'`` con las comillas dentro. Al
       compararlo contra ``"bullish"`` no cuadra y el motor acaba viendo
       direcciones que no reconoce. ``->>`` devuelve el texto sin comillas.
    """
    columna = PatternOccurrence.__table__.c.metadata
    return cast(func.jsonb_extract_path_text(columna, "direction"), Text)


@dataclass(frozen=True, slots=True)
class RunFilters:
    """Filtros de la consulta de operaciones, ya normalizados."""

    patterns: tuple[str, ...] | None = None
    directions: tuple[str, ...] | None = None
    exit_reasons: tuple[str, ...] | None = None
    sort_by: str = "entry_timestamp"
    sort_order: str = "desc"


class BacktestService:
    # ------------------------------------------------------------------ logs

    def _log(
        self,
        db: Session,
        run_id: uuid.UUID,
        level: str,
        message: str,
        progress: int | None = None,
    ) -> None:
        db.add(
            BacktestLog(run_id=run_id, level=level, message=message, progress=progress)
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
                # Sin run no hay logs: la FK de ``backtest_logs`` lo prohibe. Este
                # camino se alcanza sobre todo desde el manejador de errores de
                # ``execute_run``, asi que tragarse la excepcion aqui evita que
                # un fallo al registrar el fallo tape el fallo original y deje
                # al worker de Celery sin ninguna traza util.
                db.rollback()

    # -------------------------------------------------------------- gestion

    def create_run(self, db: Session, config: BacktestCreateIn) -> BacktestRun:
        """Crea el run con la configuracion resuelta y congelada.

        Se exige que el escaneo este completado: uno en curso tiene solo parte
        de sus ocurrencias, y simular contra un subconjunto daria un resultado
        que luego no se reproduce al terminar el escaneo.
        """
        scan = db.get(PatternScanJob, config.scan_job_id)
        if scan is None:
            raise RunNotFound("El escaneo de origen no existe")
        if scan.status != PatternScanJobStatus.COMPLETED.value:
            raise ScanNotReady(
                f"El escaneo {str(scan.id)[:8]} está en estado '{scan.status}'. "
                "Solo se pueden simular escaneos completados."
            )

        strategy: StrategyConfig = config.as_strategy()
        run = BacktestRun(
            scan_job_id=scan.id,
            status=BacktestRunStatus.PENDING.value,
            strategy=frozen_strategy(strategy, config),
            initial_capital=Decimal(str(strategy.initial_capital)),
        )
        db.add(run)
        db.flush()
        self._log(
            db,
            run.id,
            "info",
            f"Run creado sobre el escaneo {str(scan.id)[:8]} "
            f"({scan.symbol} {scan.timeframe})",
        )
        db.commit()
        db.refresh(run)
        return run

    def cancel_run(self, run_id: uuid.UUID) -> bool:
        with SessionLocal() as db:
            run = db.get(BacktestRun, run_id)
            if run is None:
                return False
            if run.status in (
                BacktestRunStatus.COMPLETED.value,
                BacktestRunStatus.FAILED.value,
                BacktestRunStatus.CANCELLED.value,
            ):
                return False
            run.status = BacktestRunStatus.CANCELLED.value
            run.finished_at = datetime.now(timezone.utc)
            self._log(db, run_id, "info", "Cancelación solicitada")
            db.commit()
            return True

    def delete_run(self, run_id: uuid.UUID) -> bool:
        with SessionLocal() as db:
            run = db.get(BacktestRun, run_id)
            if run is None:
                return False
            db.delete(run)
            db.commit()
            return True

    def requeue_run(self, run_id: uuid.UUID) -> bool:
        """Devuelve el run a la cola conservando su configuracion congelada."""
        with SessionLocal() as db:
            run = db.get(BacktestRun, run_id)
            if run is None or run.status in NON_REQUEUEABLE_STATUSES:
                return False
            run.status = BacktestRunStatus.PENDING.value
            run.started_at = None
            run.finished_at = None
            run.error_message = None
            run.total_trades = 0
            run.skipped_signals = 0
            run.truncated_trades = 0
            # Un run relanzado no debe luzca como si ya tuviera resultados
            # mientras corre: los contadores de la cabecera salen de las
            # operaciones, que se reescriben, y dejarlos puestos haria que la
            # lista ensenara un PnL viejo junto al estado "en curso".
            for column in RESET_ON_REQUEUE:
                setattr(run, column, None)
            # Y hay que borrar las filas de verdad, no solo poner los contadores a
            # cero. Si un run fallido dejo operaciones a medias y se reenvia,
            # ``_save_trades`` volveria a insertar encima y el run tendria cada
            # operacion duplicada; la curva de equity se dibujaria doble. Y si
            # el reenviado no llegara a ejecutarse, las operaciones viejas
            # seguirian en la tabla contradiciendo una cabecera a cero.
            borrados = self._clear_artifacts(db, run_id)
            self._log(
                db,
                run_id,
                "info",
                f"Run reenviado a la cola, {borrados} resultados previos descartados",
            )
            db.commit()
            return True

    def _clear_artifacts(self, db: Session, run_id: uuid.UUID) -> int:
        """Borra operaciones, curva de equity y logs de un run. Devuelve el total.

        El run en si se conserva: solo desaparecen los resultados, que es lo que
        un requeue necesita limpiar. Va por DELETE explícito y no por la cascada
        porque la cascada solo funciona borrando el padre.
        """
        borrados = 0
        for modelo in (BacktestTrade, BacktestEquityPoint, BacktestLog):
            borrados += db.execute(
                delete(modelo).where(modelo.run_id == run_id)
            ).rowcount
        return borrados

    def _mark_run(
        self,
        run_id: uuid.UUID,
        status: str,
        started_at: bool = False,
        finished_at: bool = False,
    ) -> None:
        with SessionLocal() as db:
            run = db.get(BacktestRun, run_id)
            if run is None:
                return
            # Un run cancelado se queda cancelado. Sin este corte, cancelar
            # entre que Celery encola la tarea y la tarea arranca no servia de
            # nada: ``execute_run`` marcaba "en curso" por encima del
            # "cancelado" del usuario y el ``is_cancelled`` posterior ya no
            # encontraba nada, asi que el backtest se ejecutaba entero, como si
            # nadie lo hubiera parado. La carrera es real porque encolar y
            # arrancar no son el mismo instante.
            if (
                run.status == BacktestRunStatus.CANCELLED.value
                and status != BacktestRunStatus.CANCELLED.value
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
            run = db.get(BacktestRun, run_id)
            return run is not None and run.status == BacktestRunStatus.CANCELLED.value

    # ------------------------------------------------------------- ejecucion

    def execute_run(self, run_id: uuid.UUID) -> None:
        """Punto de entrada de Celery. Envoltorio de excepcion."""
        try:
            self._mark_run(run_id, BacktestRunStatus.PROCESSING.value, started_at=True)
            if self.is_cancelled(run_id):
                return
            self._simulate(run_id)
        except Exception as exc:
            self._mark_run(run_id, BacktestRunStatus.FAILED.value, finished_at=True)
            self._log_committed(run_id, "error", f"Error en backtest: {exc}")
            with SessionLocal() as db:
                run = db.get(BacktestRun, run_id)
                if run:
                    run.error_message = str(exc)[:500]
                    db.commit()

    def _simulate(self, run_id: uuid.UUID) -> None:
        with SessionLocal() as db:
            run = db.get(BacktestRun, run_id)
            if run is None:
                raise RunNotFound("El run no existe")
            scan = db.get(PatternScanJob, run.scan_job_id)
            if scan is None:
                raise RunNotFound("El escaneo de origen ya no existe")
            symbol, timeframe = scan.symbol, scan.timeframe
            date_from, date_to = scan.date_from, scan.date_to
            filters = strategy_filters(run.strategy)
            strategy = StrategyConfig(**strategy_params(run.strategy))

        self._log_committed(run_id, "info", f"Cargando velas de {symbol} {timeframe}")
        candles = load_candles(symbol, timeframe, date_from, date_to)
        if candles.empty:
            raise ValueError(
                f"No hay velas de {symbol} {timeframe} en el rango del escaneo"
            )

        with SessionLocal() as db:
            signals = self._load_signals(db, run_id, filters)
        self._log_committed(
            run_id, "info", f"{len(candles)} velas y {len(signals)} señales cargadas"
        )

        result = run_backtest(candles, signals, strategy)

        if self.is_cancelled(run_id):
            self._log_committed(run_id, "info", "Run cancelado antes de escribir")
            return

        saved = self._save_trades(run_id, result.trades)
        self._log_committed(run_id, "info", f"{saved} operaciones almacenadas")

        if self.is_cancelled(run_id):
            self._log_committed(
                run_id, "info", "Run cancelado tras escribir las operaciones"
            )
            return

        points = self._save_equity(run_id, result)
        self._log_committed(run_id, "info", f"{points} puntos de equity almacenados")
        self._finish_run(run_id, result)

    def _load_signals(
        self, db: Session, run_id: uuid.UUID, filters: RunFilters
    ) -> pd.DataFrame:
        """Señales del escaneo de origen, en el formato que espera el motor.

        La direccion vive dentro del JSONB ``metadata``, asi que se extrae con
        un cast a texto. El filtro se aplica **en SQL** y no despues: la vista de
        detalle filtra por patron, y traer 2.812 filas para descartar 1.700 en
        Python seria tirar la mayor parte del trabajo de la base de datos.
        """
        run = db.get(BacktestRun, run_id)
        if run is None:
            raise RunNotFound("El run no existe")

        direction_col = _direction_column()
        stmt = select(
            PatternOccurrence.timestamp,
            PatternOccurrence.pattern_name,
            direction_col.label("direction"),
        ).where(PatternOccurrence.scan_job_id == run.scan_job_id)
        if filters.patterns:
            stmt = stmt.where(PatternOccurrence.pattern_name.in_(filters.patterns))
        if filters.directions:
            stmt = stmt.where(direction_col.in_(filters.directions))
        stmt = stmt.order_by(PatternOccurrence.timestamp)

        rows = db.execute(stmt).mappings().all()
        frame = pd.DataFrame(rows, columns=["timestamp", "pattern_name", "direction"])
        if frame.empty:
            return frame
        # ``pd.to_datetime(..., utc=True)`` y no ``pd.DatetimeIndex(...).dt``: el
        # accesor ``.dt`` es de ``Series``, ``DatetimeIndex`` no lo tiene. El
        # ``utc=True`` ademas normaliza a UTC lo que venga sin zona horaria, en
        # vez de asumir que ya es UTC.
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
        return frame.sort_values("timestamp", kind="stable").reset_index(drop=True)

    def _save_trades(self, run_id: uuid.UUID, trades: Sequence[TradeResult]) -> int:
        if not trades:
            return 0
        rows = [
            {
                "run_id": run_id,
                "signal_timestamp": trade.signal_timestamp.to_pydatetime(),
                "pattern_name": trade.pattern_name,
                "direction": trade.direction,
                "entry_timestamp": trade.entry_timestamp.to_pydatetime(),
                "entry_price": trade.entry_price,
                "exit_timestamp": (
                    trade.exit_timestamp.to_pydatetime()
                    if trade.exit_timestamp is not None
                    else None
                ),
                "exit_price": trade.exit_price,
                "exit_reason": trade.exit_reason,
                "quantity": trade.quantity,
                "gross_pnl": trade.gross_pnl,
                "fees": trade.fees,
                "net_pnl": trade.net_pnl,
                "return_pct": trade.return_pct,
                "bars_held": trade.bars_held,
                "equity_after": trade.equity_after,
                "mae": trade.mae,
                "mfe": trade.mfe,
            }
            for trade in trades
        ]
        table = BacktestTrade.__table__
        saved = 0
        with SessionLocal() as db:
            for start in range(0, len(rows), TRADE_BATCH_SIZE):
                # La cancelacion se mira en cada lote, no solo entre etapas: un
                # run largo de miles de operaciones tardaria demasiado en
                # escribirlo entero si el usuario cancela a mitad.
                if self.is_cancelled(run_id):
                    break
                lote = rows[start : start + TRADE_BATCH_SIZE]
                db.execute(pg_insert(table), lote)
                saved += len(lote)
            db.commit()
        return saved

    def _save_equity(self, run_id: uuid.UUID, result: BacktestResult) -> int:
        equity = result.equity
        if equity is None or equity.empty:
            return 0
        index = equity.index
        rows = [
            {
                "run_id": run_id,
                "timestamp": index[position].to_pydatetime(),
                "equity": float(equity["equity"].iloc[position]),
                "drawdown_pct": float(equity["drawdown_pct"].iloc[position]),
            }
            for position in range(len(equity))
        ]
        table = BacktestEquityPoint.__table__
        saved = 0
        with SessionLocal() as db:
            for start in range(0, len(rows), EQUITY_BATCH_SIZE):
                if self.is_cancelled(run_id):
                    break
                lote = rows[start : start + EQUITY_BATCH_SIZE]
                db.execute(pg_insert(table), lote)
                saved += len(lote)
            db.commit()
        return saved

    def _finish_run(self, run_id: uuid.UUID, result: BacktestResult) -> None:
        """Vuelca las metricas del motor en el run y lo cierra.

        El motor calcula en coma flotante por rendimiento, pero lo que se
        persiste es dinero y tiene que ser exacto al releerlo, asi que de aqui
        en adelante todo pasa por ``Decimal``.
        """
        metrics = result.metrics
        with SessionLocal() as db:
            run = db.get(BacktestRun, run_id)
            if run is None:
                return
            # Mismo corte que en ``_mark_run``: si el usuario cancela entre la
            # escritura de la equity y este punto, marcar el run como completado
            # diria que la simulacion termino bien cuando en realidad se paro a
            # medias. Se queda cancelado, con lo que se haya escrito.
            if run.status == BacktestRunStatus.CANCELLED.value:
                self._log(
                    db,
                    run_id,
                    "info",
                    "Cancelado justo antes de cerrar el run; no se marca completado",
                )
                db.commit()
                return
            run.equity_final = _decimal(metrics.get("equity_final"))
            run.net_pnl = _decimal(metrics.get("net_pnl"))
            run.total_return_pct = _decimal(metrics.get("total_return_pct"))
            run.win_rate = _decimal(metrics.get("win_rate"))
            run.profit_factor = _decimal(metrics.get("profit_factor"))
            run.max_drawdown_pct = _decimal(metrics.get("max_drawdown_pct"))
            run.sharpe_ratio = _decimal(metrics.get("sharpe_ratio"))
            run.avg_bars_held = _decimal(metrics.get("avg_bars_held"))
            run.total_trades = int(metrics.get("total_trades", 0))
            run.skipped_signals = result.skipped_signals
            run.truncated_trades = result.truncated_signals
            run.status = BacktestRunStatus.COMPLETED.value
            if run.finished_at is None:
                run.finished_at = datetime.now(timezone.utc)
            self._log(
                db,
                run_id,
                "info",
                f"Run completado: {run.total_trades} operaciones, "
                f"{result.skipped_signals} señales saltadas, "
                f"capital final {metrics.get('equity_final'):.2f}",
                progress=100,
            )
            db.commit()

    # -------------------------------------------------------------- consulta

    def get_run(self, db: Session, run_id: uuid.UUID) -> BacktestRun:
        run = db.get(BacktestRun, run_id)
        if run is None:
            raise RunNotFound("Run no encontrado")
        return run

    def get_run_trades(
        self,
        db: Session,
        run_id: uuid.UUID,
        filters: RunFilters | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[BacktestTrade], int, Decimal | None]:
        """Operaciones filtradas, con el total y la suma del filtro completo.

        La suma se calcula sobre **todo** el subconjunto, no sobre la pagina: si
        no, filtrar por patron y mirar la ultima pagina dari un PnL que no cuadra
        con el de la tarjeta, y el usuario lo leeria como un bug de paginacion.
        """
        filters = filters or RunFilters()
        conditions = [BacktestTrade.run_id == run_id]
        if filters.patterns:
            conditions.append(BacktestTrade.pattern_name.in_(filters.patterns))
        if filters.directions:
            conditions.append(BacktestTrade.direction.in_(filters.directions))
        if filters.exit_reasons:
            conditions.append(BacktestTrade.exit_reason.in_(filters.exit_reasons))

        total = (
            db.scalar(
                select(func.count()).select_from(BacktestTrade).where(*conditions)
            )
            or 0
        )
        total_net = db.scalar(
            select(func.sum(BacktestTrade.net_pnl)).where(*conditions)
        )

        column = SORTABLE_TRADE_COLUMNS.get(filters.sort_by)
        if column is None:
            raise ValueError(f"Columna de ordenación inválida: {filters.sort_by}")
        order = (
            column.asc().nulls_last()
            if filters.sort_order == "asc"
            else column.desc().nulls_last()
        )
        trades = db.scalars(
            select(BacktestTrade)
            .where(*conditions)
            .order_by(order)
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        return trades, total, _decimal(total_net)

    def get_run_equity(
        self, db: Session, run_id: uuid.UUID, max_points: int | None = None
    ) -> BacktestEquitySeriesOut:
        """Curva de equity, submuestreada uniformemente si es larga.

        El submuestreo es por paso constante: no conserva la forma con fidelidad
        estadistica, pero conserva los extremos y los picos, que es lo que hace
        un grafico util. El ``max_drawdown_pct`` se toma del run y **no** de la
        serie submuestreada, porque el maximo real puede caer entre dos puntos
        seguidas y recalcularlo aqui dari un valor distinto al de la tarjeta.
        """
        run = self.get_run(db, run_id)
        total = (
            db.scalar(
                select(func.count())
                .select_from(BacktestEquityPoint)
                .where(BacktestEquityPoint.run_id == run_id)
            )
            or 0
        )

        stmt = select(BacktestEquityPoint).where(BacktestEquityPoint.run_id == run_id)
        if max_points and total > max_points:
            step = math.ceil(total / max_points)
            numbered = (
                select(
                    BacktestEquityPoint.timestamp.label("timestamp"),
                    func.row_number()
                    .over(order_by=BacktestEquityPoint.timestamp)
                    .label("rn"),
                )
                .where(BacktestEquityPoint.run_id == run_id)
                .subquery()
            )
            # Se numeran las velas en SQL y se queda una de cada ``step``: traer
            # los timestamps a Python para muestrear en memoria seria descargar
            # la serie entera de la hypertable para descartar el 95%.
            #
            # Se conserva también la última fila a propósito. Con
            # ``(rn - 1) % step == 0`` solo el primer punto se conserva siempre:
            # la última cae dentro del hueco del último paso, y una curva que no
            # llega al cierre final no enseña el ``equity_final`` que dice la
            # tarjeta. ``rn == total`` fuerza el extremo final.
            stmt = stmt.where(
                BacktestEquityPoint.timestamp.in_(
                    select(numbered.c.timestamp).where(
                        ((numbered.c.rn - 1) % step == 0) | (numbered.c.rn == total)
                    )
                )
            )
        points = db.scalars(stmt.order_by(BacktestEquityPoint.timestamp)).all()

        return BacktestEquitySeriesOut(
            points=points,
            total_points=total,
            returned=len(points),
            max_drawdown_pct=run.max_drawdown_pct,
        )

    def get_run_summary(self, db: Session, run_id: uuid.UUID) -> BacktestSummaryOut:
        run = self.get_run(db, run_id)
        return BacktestSummaryOut(
            run=run,
            total_signals=self._count_signals(db, run, strategy_filters(run.strategy)),
            by_pattern=self.get_trades_by_pattern(db, run_id),
            by_exit_reason=self._get_by_exit_reason(db, run_id),
        )

    def _count_signals(self, db: Session, run: BacktestRun, filters: RunFilters) -> int:
        """Señales que alimentaron el run, ya filtradas como el propio run.

        Sin el filtro seria el total del escaneo y, en un run sobre 3 patrones,
        la tarjeta diria "2.812 señales, 40 operaciones" sin explicar que 1.700
        señales ni siquiera se consideraron.
        """
        direction_col = _direction_column()
        stmt = (
            select(func.count())
            .select_from(PatternOccurrence)
            .where(PatternOccurrence.scan_job_id == run.scan_job_id)
        )
        if filters.patterns:
            stmt = stmt.where(PatternOccurrence.pattern_name.in_(filters.patterns))
        if filters.directions:
            stmt = stmt.where(direction_col.in_(filters.directions))
        return db.scalar(stmt) or 0

    def get_trades_by_pattern(
        self, db: Session, run_id: uuid.UUID
    ) -> list[BacktestPatternBreakdownOut]:
        """Desglose por patron y direccion, con metricas de acierto.

        Se agrega en SQL y no trayendo las operaciones a Python: son miles de
        filas y la base de datos las suma en una sola pasada indexada. El
        ``win_rate`` excluye ``end_of_data`` con un ``FILTER`` explicito, igual
        que en el motor; por eso ``evaluated`` se cuenta aparte de ``trades``.
        """
        counted = BacktestTrade.exit_reason.in_(COUNTED_EXIT_REASONS)
        evaluated = func.sum(func.cast(counted, Integer))
        rows = (
            db.execute(
                select(
                    BacktestTrade.pattern_name,
                    BacktestTrade.direction,
                    func.count().label("trades"),
                    evaluated.label("evaluated"),
                    func.sum(
                        func.cast(counted & (BacktestTrade.net_pnl > 0), Integer)
                    ).label("wins"),
                    func.sum(
                        func.cast(counted & (BacktestTrade.net_pnl < 0), Integer)
                    ).label("losses"),
                    func.sum(BacktestTrade.net_pnl).label("net_pnl"),
                    func.avg(BacktestTrade.return_pct).label("avg_return_pct"),
                    func.avg(BacktestTrade.bars_held).label("avg_bars_held"),
                    func.avg(BacktestTrade.mae).label("avg_mae"),
                    func.avg(BacktestTrade.mfe).label("avg_mfe"),
                )
                .where(BacktestTrade.run_id == run_id)
                .group_by(BacktestTrade.pattern_name, BacktestTrade.direction)
                .order_by(func.sum(BacktestTrade.net_pnl).desc())
            )
            .mappings()
            .all()
        )

        breakdown = []
        for row in rows:
            evaluated_count = int(row["evaluated"] or 0)
            wins = int(row["wins"] or 0)
            breakdown.append(
                BacktestPatternBreakdownOut(
                    pattern_name=row["pattern_name"],
                    direction=row["direction"],
                    trades=int(row["trades"]),
                    wins=wins,
                    losses=int(row["losses"] or 0),
                    net_pnl=_decimal(row["net_pnl"]) or Decimal(0),
                    avg_return_pct=_decimal(row["avg_return_pct"]),
                    win_rate=(wins / evaluated_count) if evaluated_count else None,
                    avg_bars_held=_decimal(row["avg_bars_held"]),
                    avg_mae=_decimal(row["avg_mae"]),
                    avg_mfe=_decimal(row["avg_mfe"]),
                )
            )
        return breakdown

    def _get_by_exit_reason(
        self, db: Session, run_id: uuid.UUID
    ) -> list[BacktestExitReasonOut]:
        rows = (
            db.execute(
                select(
                    BacktestTrade.exit_reason,
                    func.count().label("trades"),
                    func.sum(BacktestTrade.net_pnl).label("net_pnl"),
                )
                .where(BacktestTrade.run_id == run_id)
                .group_by(BacktestTrade.exit_reason)
                .order_by(func.count().desc())
            )
            .mappings()
            .all()
        )
        return [
            BacktestExitReasonOut(
                exit_reason=row["exit_reason"],
                trades=int(row["trades"]),
                net_pnl=_decimal(row["net_pnl"]) or Decimal(0),
            )
            for row in rows
            if row["exit_reason"]
        ]

    def get_available_scans(self, db: Session) -> list[dict]:
        """Escaneos completados con su conteo de ocurrencias, para el selector."""
        rows = (
            db.execute(
                select(
                    PatternScanJob.id,
                    PatternScanJob.symbol,
                    PatternScanJob.timeframe,
                    PatternScanJob.date_from,
                    PatternScanJob.date_to,
                    PatternScanJob.total_candles,
                    func.count(PatternOccurrence.timestamp).label("total_occurrences"),
                )
                .join(
                    PatternOccurrence,
                    PatternOccurrence.scan_job_id == PatternScanJob.id,
                    isouter=True,
                )
                .where(PatternScanJob.status == PatternScanJobStatus.COMPLETED.value)
                .group_by(PatternScanJob.id)
                .order_by(PatternScanJob.created_at.desc())
            )
            .mappings()
            .all()
        )
        return [dict(row) for row in rows]

    def delete_runs(self, db: Session, run_ids: Sequence[uuid.UUID]) -> int:
        deleted = db.execute(delete(BacktestRun).where(BacktestRun.id.in_(run_ids)))
        db.commit()
        return deleted.rowcount or 0


# --------------------------------------------------------------------------
# Helpers de la columna strategy
# --------------------------------------------------------------------------
def frozen_strategy(strategy: StrategyConfig, config: BacktestCreateIn) -> dict:
    """Configuracion del run tal y como se ejecutara, filtros incluidos.

    Los filtros se guardan **dentro** de ``strategy`` y no en una columna aparte
    porque forman parte de la identidad del run: uno sobre 3 de los 8 patrones no
    es el mismo experimento que uno sobre los 8.
    """
    payload = strategy.as_dict()
    payload["patterns"] = list(config.patterns) if config.patterns else None
    payload["directions"] = list(config.directions) if config.directions else None
    return payload


def strategy_params(payload: dict) -> dict:
    """Solo los campos de ``StrategyConfig``, sin los filtros.

    Se filtra por nombre de campo en vez de por lista fija para que anadir un
    parametro al motor no obligue a tocar aqui: se recoge solo.
    """
    known = StrategyConfig.__dataclass_fields__
    return {key: value for key, value in payload.items() if key in known}


def strategy_filters(payload: dict) -> RunFilters:
    patterns = payload.get("patterns")
    directions = payload.get("directions")
    return RunFilters(
        patterns=tuple(patterns) if patterns else None,
        directions=tuple(directions) if directions else None,
    )


def _decimal(value) -> Decimal | None:
    """``Decimal`` desde un ``float`` del motor, o ``None`` si no hay valor.

    Va por ``str`` y no por ``float``: ``Decimal(0.1)`` guarda el error binario
    de ``0.1`` en un numero que el usuario va a leer como dinero, mientras que
    ``Decimal("0.1")`` guarda el decimal que se quiso escribir.
    """
    if value is None:
        return None
    return Decimal(str(value))
