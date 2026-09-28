"""Contratos de entrada y salida del modulo de backtesting.

La validacion de la estrategia **no** se reimplementa aqui: ``BacktestStrategyIn``
construye un ``engine.StrategyConfig`` y deja que sea el motor el que rechace lo
que no tiene sentido. Si las reglas vivieran en los dos sitios, la proxima vez
que se anada un limite (un ``max_hold`` maximo, un ``use_fraction`` por debajo
del 10%) el endpoint dejaria de aceptarlo y el motor lo aceptaria, o al reves.
Ahi es donde aparecen los 422 en produccion que nadie sabe explicar.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.modules.backtesting.engine import StrategyConfig, StrategyError
from app.modules.backtesting.models import BacktestRunStatus, ExitReason, TradeDirection


class BacktestStrategyIn(BaseModel):
    """Parametros de la simulacion, en los mismos tipos que usa el motor."""

    take_profit_pct: float | None = Field(default=2.0, gt=0)
    stop_loss_pct: float | None = Field(default=1.0, gt=0)
    max_hold: int = Field(default=24, ge=1)
    fee_bps: float = Field(default=4.0, ge=0)
    initial_capital: float = Field(default=1000.0, gt=0)
    use_fraction: float = Field(default=1.0, gt=0, le=1)
    allow_short: bool = True

    @model_validator(mode="after")
    def _validate_with_engine(self) -> BacktestStrategyIn:
        try:
            StrategyConfig(**self.model_dump())
        except StrategyError as exc:
            # Se relanza como ValueError para que pydantic lo convierta en 422
            # con este texto, en vez de un 500 desde dentro del endpoint.
            raise ValueError(str(exc)) from exc
        return self


class BacktestCreateIn(BaseModel):
    """Peticion de ``POST /api/v1/backtests``.

    El rango de mercado no se pide: se hereda del escaneo, que es quien sabe
    que velas existen. Pedirlo aqui abriria la puerta a simular señales contra
    velas que el escaneo nunca vio.
    """

    scan_job_id: UUID
    strategy: BacktestStrategyIn = Field(default_factory=BacktestStrategyIn)
    #: Filtro opcional de patrones. ``None`` significa todos, que es lo
    #: habitual; una lista vacia no tiene sentido y se rechaza.
    patterns: list[str] | None = None
    directions: list[Literal["bullish", "bearish"]] | None = None

    @model_validator(mode="after")
    def _validate_filters(self) -> BacktestCreateIn:
        if self.patterns is not None:
            if not self.patterns:
                raise ValueError("El filtro de patrones no puede ser una lista vacía")
            if any(not name.strip() for name in self.patterns):
                raise ValueError("El filtro de patrones no admite nombres vacíos")
        if self.directions is not None and not self.directions:
            raise ValueError("El filtro de direcciones no puede ser una lista vacía")
        return self

    def as_strategy(self) -> StrategyConfig:
        return StrategyConfig(**self.strategy.model_dump())


class BacktestRunOut(BaseModel):
    """Run completo, tal y como se guarda."""

    model_config = {"from_attributes": True}

    id: UUID
    scan_job_id: UUID
    status: BacktestRunStatus
    strategy: dict
    initial_capital: Decimal
    equity_final: Decimal | None = None
    total_trades: int
    skipped_signals: int
    truncated_trades: int
    net_pnl: Decimal | None = None
    total_return_pct: Decimal | None = None
    win_rate: Decimal | None = None
    profit_factor: Decimal | None = None
    max_drawdown_pct: Decimal | None = None
    sharpe_ratio: Decimal | None = None
    avg_bars_held: Decimal | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime | None = None


class BacktestRunListItem(BaseModel):
    """Fila de la lista de runs: lo justo para pintar la tabla.

    No incluye ``strategy``: es un JSONB que varia en forma y la lista no lo
    necesita. El detalle viene en ``GET /backtests/{id}``.
    """

    model_config = {"from_attributes": True}

    id: UUID
    scan_job_id: UUID
    status: BacktestRunStatus
    initial_capital: Decimal
    equity_final: Decimal | None = None
    total_trades: int
    net_pnl: Decimal | None = None
    total_return_pct: Decimal | None = None
    win_rate: Decimal | None = None
    max_drawdown_pct: Decimal | None = None
    created_at: datetime


class BacktestRunListOut(BaseModel):
    runs: list[BacktestRunListItem]
    total: int


class BacktestTradeOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    signal_timestamp: datetime
    pattern_name: str
    direction: TradeDirection
    entry_timestamp: datetime
    entry_price: Decimal
    exit_timestamp: datetime | None = None
    exit_price: Decimal | None = None
    exit_reason: ExitReason | None = None
    quantity: Decimal
    gross_pnl: Decimal | None = None
    fees: Decimal
    net_pnl: Decimal | None = None
    return_pct: Decimal | None = None
    bars_held: int
    equity_after: Decimal | None = None
    mae: Decimal | None = None
    mfe: Decimal | None = None


class BacktestTradeListOut(BaseModel):
    trades: list[BacktestTradeOut]
    total: int
    #: Suma de ``net_pnl`` de **todos** los trades que casan con el filtro, no
    #: solo los de esta pagina. Sin esto, filtrar por patron y mirar la ultima
    #: pagina daria un PnL que no cuadra con el de la tarjeta de resumen.
    total_net_pnl: Decimal | None = None


class BacktestEquityPointOut(BaseModel):
    model_config = {"from_attributes": True}

    timestamp: datetime
    equity: Decimal
    drawdown_pct: Decimal


class BacktestEquitySeriesOut(BaseModel):
    """Curva de equity, submuestreada si el rango es largo.

    ``total_points`` es el numero real de velas del rango y ``returned`` el de la
    serie enviada, para que el frontend pueda avisar de que esta mostrando una
    version reducida en lugar de fingir que son todas.
    """

    points: list[BacktestEquityPointOut]
    total_points: int
    returned: int
    max_drawdown_pct: Decimal | None = None


class BacktestPatternBreakdownOut(BaseModel):
    pattern_name: str
    direction: TradeDirection
    trades: int
    wins: int
    losses: int
    net_pnl: Decimal
    avg_return_pct: Decimal | None = None
    win_rate: Decimal | None = None
    avg_bars_held: Decimal | None = None
    avg_mae: Decimal | None = None
    avg_mfe: Decimal | None = None


class BacktestExitReasonOut(BaseModel):
    exit_reason: ExitReason
    trades: int
    net_pnl: Decimal


class BacktestSummaryOut(BaseModel):
    """Tarjeta de resumen: metricas de cabecera mas los dos desgloses."""

    run: BacktestRunOut
    total_signals: int
    by_pattern: list[BacktestPatternBreakdownOut]
    by_exit_reason: list[BacktestExitReasonOut]


class BacktestLogOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    run_id: UUID
    timestamp: datetime
    level: str
    message: str
    progress: int | None = None


class BacktestAvailableScanOut(BaseModel):
    """Escaneos que se pueden simular.

    Solo los completados: uno en curso todavia no tiene todas sus ocurrencias, y
    simular contra un subconjunto daria un resultado que luego no se reproduce.
    """

    id: UUID
    symbol: str
    timeframe: str
    date_from: datetime
    date_to: datetime
    total_candles: int
    total_occurrences: int


class BacktestAvailableScansOut(BaseModel):
    scans: list[BacktestAvailableScanOut]


class BatchDeleteBody(BaseModel):
    run_ids: list[UUID] = Field(min_length=1, max_length=100)
