"""Modelos del modulo de backtesting.

Un ``backtest_runs`` es una simulacion de una estrategia sobre las ocurrencias
de un ``pattern_scan_jobs``. Las tres ideas que gobiernan el esquema:

1. **El run es la unidad de configuracion y de resultado.** Guarda la
   ``strategy`` tal y como se ejecuto, en JSONB, para que un run sea
   reproducible y auditable aunque el catalogo de estrategias cambie despues.
   Las metricas de cabecera estan desnormalizadas en columnas porque se leen en
   la lista y en la tarjeta de resumen, y recalcularlas en cada ``GET`` de una
   tabla de miles de operaciones seria innecesario.

2. **No hay clave foranea de ``backtest_trades`` a ``pattern_occurrences``.**
   La cadena de borrado ya es suficiente y mas simple:
   ``pattern_scan_jobs`` -> ``backtest_runs`` -> ``backtest_trades``. Una FK
   compuesta de 5 columnas en cada operacion costaria escrituras y, sobre todo,
   dejaria metricas de cabecera obsoletas si una ocurrencia desapareciera por
   una via que no pasara por el run. Las columnas de traza
   (``signal_timestamp``, ``pattern_name``) se guardan igual, para poder situar
   la operacion aunque el escaneo origen ya no exista.

3. **Dinero en ``Numeric``, nunca en ``float``.** Los simbolos van en
   ``Numeric(20, 8)`` porque un PnL acumulado sobre miles de operaciones acumula
   error de coma flotante en la ultima cifra, que es justo la que se compara
   contra cero al cerrar un run.
"""

import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class BacktestRunStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExitReason(str, Enum):
    """Por que se cerro una operacion.

    ``END_OF_DATA`` no es un resultado de la estrategia: es la falta de velas
    posteriores para cerrar. Por eso se excluye de las metricas de acierto; verlo
    mezclado ahi rebajaria el win rate por un motivo que no es del patron.
    """

    TAKE_PROFIT = "take_profit"
    STOP_LOSS = "stop_loss"
    TIMEOUT = "timeout"
    END_OF_DATA = "end_of_data"


class TradeDirection(str, Enum):
    LONG = "long"
    SHORT = "short"


class BacktestRun(Base):
    __tablename__ = "backtest_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    scan_job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("pattern_scan_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(20), default=BacktestRunStatus.PENDING.value
    )
    #: Configuracion congelada de la simulacion. Ver ``strategies.py``.
    strategy: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    initial_capital: Mapped[float] = mapped_column(
        Numeric(20, 8), nullable=False, default=1000
    )
    equity_final: Mapped[float | None] = mapped_column(Numeric(20, 8), nullable=True)

    total_trades: Mapped[int] = mapped_column(Integer, default=0)
    #: Senales que llegaron con una posicion ya abierta. No son errores: son el
    #: precio de usar una sola posicion a la vez, y se exponen para que el
    #: resultado se pueda interpretar sin suponerlo.
    skipped_signals: Mapped[int] = mapped_column(Integer, default=0)
    #: Senales que caen en las ultimas velas, sin ninguna posterior donde
    #: entrar. **No** son operaciones cortadas: no llega a haber ninguna. El
    #: nombre viene de que la senal queda truncada por el borde de los datos.
    #: Las operaciones que si se abrieron pero no pudieron cerrarse por falta de
    #: velas son las de ``exit_reason = 'end_of_data'``, que se consultan sobre
    #: ``backtest_trades`` y no se guardan aqui porque dependen de cada operacion
    #: y no del run entero.
    truncated_trades: Mapped[int] = mapped_column(Integer, default=0)

    net_pnl: Mapped[float | None] = mapped_column(Numeric(20, 8), nullable=True)
    total_return_pct: Mapped[float | None] = mapped_column(
        Numeric(12, 6), nullable=True
    )
    #: Fraccion en [0, 1], no porcentaje. La columna se llama ``_pct`` por
    #: costumbre del resto del proyecto, pero aqui se documenta explicitamente
    #: para que nadie lo lea como 0-100.
    win_rate: Mapped[float | None] = mapped_column(Numeric(12, 6), nullable=True)
    profit_factor: Mapped[float | None] = mapped_column(Numeric(12, 6), nullable=True)
    max_drawdown_pct: Mapped[float | None] = mapped_column(
        Numeric(12, 6), nullable=True
    )
    sharpe_ratio: Mapped[float | None] = mapped_column(Numeric(12, 6), nullable=True)
    avg_bars_held: Mapped[float | None] = mapped_column(Numeric(12, 6), nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    logs: Mapped[list["BacktestLog"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    trades: Mapped[list["BacktestTrade"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    equity_points: Mapped[list["BacktestEquityPoint"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class BacktestLog(Base):
    __tablename__ = "backtest_logs"
    __table_args__ = (Index("ix_backtest_logs_run_timestamp", "run_id", "timestamp"),)

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("backtest_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    level: Mapped[str] = mapped_column(String(10), default="info")
    message: Mapped[str] = mapped_column(Text, nullable=False)
    progress: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    run: Mapped["BacktestRun"] = relationship(back_populates="logs")


class BacktestTrade(Base):
    __tablename__ = "backtest_trades"
    __table_args__ = (
        Index("ix_backtest_trades_run_exit", "run_id", "exit_timestamp"),
        Index("ix_backtest_trades_run_pattern", "run_id", "pattern_name"),
        Index("ix_backtest_trades_run_reason", "run_id", "exit_reason"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("backtest_runs.id", ondelete="CASCADE"),
        nullable=False,
    )

    #: Traza de la señal que origino la operacion. Sin FK a proposito: ver la
    #: nota 2 del docstring del modulo.
    signal_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    pattern_name: Mapped[str] = mapped_column(String(64), nullable=False)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)

    entry_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    entry_price: Mapped[float] = mapped_column(Numeric(20, 8), nullable=False)
    exit_timestamp: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    exit_price: Mapped[float | None] = mapped_column(Numeric(20, 8), nullable=True)
    exit_reason: Mapped[str | None] = mapped_column(String(16), nullable=True)

    quantity: Mapped[float] = mapped_column(Numeric(24, 12), nullable=False)
    gross_pnl: Mapped[float | None] = mapped_column(Numeric(20, 8), nullable=True)
    fees: Mapped[float] = mapped_column(Numeric(20, 8), nullable=False, default=0)
    net_pnl: Mapped[float | None] = mapped_column(Numeric(20, 8), nullable=True)
    return_pct: Mapped[float | None] = mapped_column(Numeric(12, 6), nullable=True)
    bars_held: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    equity_after: Mapped[float | None] = mapped_column(Numeric(20, 8), nullable=True)

    #: Excursiones maxima adversa y favorable mientras la operacion estaba
    #: abierta. No son metricas de resultado: son el instrumento para calibrar
    #: ``take_profit`` y ``stop_loss`` con datos en vez de a ojo, asi que se
    #: guardan aunque no se muestren en la primera version de la interfaz.
    mae: Mapped[float | None] = mapped_column(Numeric(20, 8), nullable=True)
    mfe: Mapped[float | None] = mapped_column(Numeric(20, 8), nullable=True)

    run: Mapped["BacktestRun"] = relationship(back_populates="trades")


class BacktestEquityPoint(Base):
    """Curva de equity, una fila por vela del rango simulado.

    Es una desnormalizacion a proposito: derivarla en cada lectura obligaria a
    recorrer todas las operaciones y a recomputar el drawdown en el servidor
    para pintarla. Se declara hypertable, como ``candles`` y
    ``pattern_occurrences``, porque es una serie temporal y crece con el rango
    simulado, no con el numero de operaciones.
    """

    __tablename__ = "backtest_equity_points"

    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("backtest_runs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True
    )
    equity: Mapped[float] = mapped_column(Numeric(20, 8), nullable=False)
    #: Drawdown respecto al maximo de equity hasta esa vela, en [0, 100].
    drawdown_pct: Mapped[float] = mapped_column(Numeric(12, 6), nullable=False)

    run: Mapped["BacktestRun"] = relationship(back_populates="equity_points")
