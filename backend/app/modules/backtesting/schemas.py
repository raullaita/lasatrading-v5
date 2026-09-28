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

from app.modules.backtesting.analysis import MAX_SWEEP_COMBINATIONS
from app.modules.backtesting.engine import StrategyConfig, StrategyError
from app.modules.backtesting.models import (
    BacktestRunStatus,
    ExitReason,
    TradeDirection,
    WalkForwardRunStatus,
    WalkForwardVerdict,
)


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
    #: Lo que habria dado no operar. Sin esta cifra, las metricas de la run
    #: no son interpretables: dependen de como se movio el mercado.
    benchmark: BacktestBenchmarkOut | None = None


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


# ---------------------------------------------------------------------------
# Analisis y calibracion
#
# Todo lo que sigue se deriva de las columnas que ya existen (``mae`` y ``mfe``)
# y de una re-simulacion en memoria: no hay tablas nuevas y no hay migracion.
# Los porcentajes van en ``Decimal`` por el mismo motivo que el resto del
# modulo, aunque no sean dinero: son la misma magnitud que ``return_pct``, y
# mezclar ``float`` con ``Decimal`` en la misma respuesta obligaria al frontend
# a distinguir dos tipos de numero para el mismo concepto.
# ---------------------------------------------------------------------------
class ExcursionBucketOut(BaseModel):
    """Caja del histograma de una excursion."""

    lower: Decimal
    upper: Decimal
    count: int


class ExcursionStatsOut(BaseModel):
    """Distribucion de MAE o MFE: percentiles, extremos e histograma.

    ``capped_at_pct`` viaja con la distribucion, no como nota aparte, porque es
    parte del dato: sin el, un percentil 90 clavado en el take profit del run se
    lee como una oportunidad de mercado cuando en realidad es el techo que el
    propio run se puso. ``is_capped`` ya viene resuelto para que la UI solo tenga
    que pintar la advertencia.
    """

    count: int
    p10: Decimal | None = None
    p25: Decimal | None = None
    p50: Decimal | None = None
    p75: Decimal | None = None
    p90: Decimal | None = None
    minimum: Decimal | None = None
    maximum: Decimal | None = None
    mean: Decimal | None = None
    buckets: list[ExcursionBucketOut] = Field(default_factory=list)
    capped_at_pct: Decimal | None = None
    is_capped: bool = False


class PatternCalibrationOut(BaseModel):
    """Calibracion de un patron en una direccion."""

    pattern_name: str
    direction: TradeDirection
    trades: int
    wins: int
    losses: int
    #: Operaciones cuyo cierre no lo decidio ningun nivel del run. De ahi salen
    #: las sugerencias: son las unicas sin techo puesto por el TP o el SL.
    free_trades: int
    winner_mfe: ExcursionStatsOut
    loser_mae: ExcursionStatsOut
    free_mfe: ExcursionStatsOut
    free_mae: ExcursionStatsOut
    suggested_take_profit_pct: Decimal | None = None
    suggested_stop_loss_pct: Decimal | None = None
    findings: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class BacktestBenchmarkOut(BaseModel):
    """Comprar y mantener durante el rango del escaneo.

    Viaja en el resumen y en el barrido, no en un endpoint aparte, por una
    razon de la propia naturaleza del dato: es **el mismo numero** para el
    run, para cada patron y para cada fila de la rejilla, porque el rango de
    velas lo fija el escaneo de origen. Pedirlo aparte seria hacer tres
    peticiones para devolver siempre lo mismo, con el riesgo de que cada copia
    difiera un dia y las tres acaben en pantalla a la vez.

    Con ``candles == 0`` todos los valores vienen a ``null`` y no hay nada que
    comparar: la UI lo dice en vez de enseñar un 0% que parece un mercado plano.
    """

    candles: int
    initial_capital: Decimal
    entry_price: Decimal | None = None
    final_price: Decimal | None = None
    equity_final: Decimal | None = None
    net_pnl: Decimal | None = None
    total_return_pct: Decimal | None = None
    max_drawdown_pct: Decimal | None = None
    sharpe_ratio: Decimal | None = None

    @property
    def available(self) -> bool:
        return self.candles > 0 and self.total_return_pct is not None


class BacktestAnalysisOut(BaseModel):
    """Analisis completo de un run.

    ``strategy`` es la del propio run, para que la UI pueda contraponer "lo que
    usaste" contra "lo que dicen los datos" sin tener que pedir el run aparte.
    """

    run_id: UUID
    strategy: BacktestRunOut
    trades: int
    #: Operaciones del run entero que ningun nivel corto. Es la poblacion de la
    #: que salen las propuestas globales: puede ser mayor que la suma de las de
    #: los grupos solo en apariencia, porque cada grupo necesita llegar al minimo
    #: por su cuenta.
    free_trades: int = 0
    pooled_mfe: ExcursionStatsOut = Field(default_factory=ExcursionStatsOut)
    pooled_mae: ExcursionStatsOut = Field(default_factory=ExcursionStatsOut)
    groups: list[PatternCalibrationOut] = Field(default_factory=list)
    suggested_take_profit_pct: Decimal | None = None
    suggested_stop_loss_pct: Decimal | None = None
    findings: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class SweepGridIn(BaseModel):
    """Rejilla de TP, SL y ``max_hold`` a simular.

    Un ``null`` en la lista de TP o de SL es "sin ese nivel", que es una
    combinacion legitima (operar solo con tiempo limite, por ejemplo). El tope de
    combinaciones se comprueba aqui y no en el servicio, para que el rechazo sea
    un 422 con el detalle de cuantos eran, y no un 500 a mitad de la simulacion.
    """

    take_profit_pcts: list[float | None] = Field(min_length=1, max_length=8)
    stop_loss_pcts: list[float | None] = Field(min_length=1, max_length=8)
    max_holds: list[int] = Field(
        min_length=1, max_length=8, default_factory=lambda: [24]
    )

    @model_validator(mode="after")
    def _validate_grid(self) -> SweepGridIn:
        for value in [*self.take_profit_pcts, *self.stop_loss_pcts]:
            if value is not None and value <= 0:
                raise ValueError("Los niveles del barrido deben ser > 0 o null")
        if any(hold < 1 for hold in self.max_holds):
            raise ValueError("max_hold debe ser >= 1")
        combinaciones = (
            len(self.take_profit_pcts) * len(self.stop_loss_pcts) * len(self.max_holds)
        )
        if combinaciones > MAX_SWEEP_COMBINATIONS:
            raise ValueError(
                f"La rejilla tiene {combinaciones} combinaciones y el tope es "
                f"{MAX_SWEEP_COMBINATIONS}: reduce los valores de TP, SL o max_hold"
            )
        return self


class SweepPointOut(BaseModel):
    """Fila de la tabla comparativa del barrido. Nada de esto se persiste."""

    take_profit_pct: Decimal | None = None
    stop_loss_pct: Decimal | None = None
    max_hold: int
    total_trades: int
    skipped_signals: int
    net_pnl: Decimal
    total_return_pct: Decimal
    win_rate: Decimal | None = None
    profit_factor: Decimal | None = None
    max_drawdown_pct: Decimal
    sharpe_ratio: Decimal | None = None
    avg_bars_held: Decimal | None = None
    #: Reparto de motivos de cierre. Es la columna que explica *por que* cambia
    #: el resultado al mover un nivel: subir el TP convierte salidas por take
    #: profit en timeouts, y eso se ve aqui y no en un agregado.
    exits: dict[str, int] = Field(default_factory=dict)
    is_baseline: bool = False


class BacktestSweepOut(BaseModel):
    """Resultado del barrido, ordenado de mejor a peor por PnL neto."""

    run_id: UUID
    strategy: BacktestRunOut
    #: Constante de la fila, no de cada combinacion: la rejilla no cambia de
    #: rango, asi que todas las filas se miden contra el mismo mercado.
    benchmark: BacktestBenchmarkOut | None = None
    points: list[SweepPointOut] = Field(default_factory=list)
    #: Combinaciones pedidas y simuladas. Difieren cuando alguna celda de la
    #: rejilla era invalida (los dos niveles a null, por ejemplo) y se explicita
    #: para que la UI no finja que se simularon todas.
    requested: int
    simulated: int
    elapsed_ms: int


# ---------------------------------------------------------------------------
# Walk-forward
# ---------------------------------------------------------------------------
#: Tope duro de combinaciones de la rejilla. Mismo numero y mismo motivo que
#: ``MAX_SWEEP_COMBINATIONS``, y se comparte a proposito: el walk-forward barre la
#: rejilla una vez **por ventana**, asi que un tope que aqui fuera mas alto
#: multiplicaria el coste de barrido por el numero de ventanas sin avisar. El
#: limite real de simulaciones se comprueba aparte, con ``max_simulations``.
MAX_WALK_FORWARD_COMBINATIONS = MAX_SWEEP_COMBINATIONS


class WalkForwardCreateIn(BaseModel):
    """Peticion de ``POST /api/v1/walk-forward/runs``.

    El rango de mercado tampoco se pide: se hereda del escaneo, por el mismo
    motivo que en ``BacktestCreateIn``.

    ``max_simulations`` se comprueba **aqui** y no en el worker, y la comprobacion
    es dinamica: el numero de ventanas depende del rango del escaneo, que el
    cliente no conoce, asi que el 422 no puede salir de un ``Field`` estatico.
    Lo que si se puede comprobar sin el rango es que la rejilla no se pase de
    ``MAX_WALK_FORWARD_COMBINATIONS`` combinaciones, y eso si se hace como
    ``Field``. El total real lo verifica el servicio, que ya tiene las velas
    cargadas y por tanto las ventanas construidas.
    """

    scan_job_id: UUID
    grid: SweepGridIn

    #: Ventanas de in-sample y out-of-sample, en dias. ``oos_days`` no tiene
    #: cota superior a proposito: un OOS largo es caro pero no invalido, y es al
    #: usuario a quien le corresponde decidir cuanto sacrifica.
    window_days: int = Field(default=365, ge=7)
    oos_days: int = Field(default=90, ge=7)
    step_days: int = Field(default=90, ge=1)
    #: Ventanas OOS minimas para que una combinacion pueda ser candidata.
    min_windows: int = Field(default=3, ge=1)
    #: Operaciones OOS minimas. Es la guarda que mas descarta, y por eso el
    #: IC95% de una candidata descartada por aqui es ``null``: no se puede
    #: repetir la medicion con la muestra que no hay.
    min_trades: int = Field(default=30, ge=0)
    #: Tramo final reservado que no se toca. Cero significa que no hay
    #: reserva, que es el valor por defecto.
    holdout_days: int = Field(default=0, ge=0)
    #: Fraccion de ventanas OOS en las que hay que superar al mercado. Cero la
    #: desactiva, y por eso el rango es [0, 1] y no (0, 1].
    beats_market_ratio: float = Field(default=0.6, ge=0, le=1)
    #: Regimenes declarados por el usuario. Es una **declaracion**, no una
    #: deteccion: el motor no sabe si los datos que le dan son un lateral, un
    #: bajista o tres cosas pegadas, y fingir que lo sabe seria inventarse el
    #: requisito de tres regimenes de la §5.1. Lo usa para decidir si ``sostenida``
    #: es siquiera alcanzable.
    regimes_declared: int = Field(default=1, ge=1, le=12)
    #: Tope duro de simulaciones, comprobado contra el total real. Es el unico
    #: sitio donde un 422 puede decir cuantas serian, porque es el unico sitio
    #: que ya ha construido las ventanas.
    max_simulations: int = Field(default=2000, ge=1)

    @model_validator(mode="after")
    def _validate_windows(self) -> WalkForwardCreateIn:
        if self.step_days > self.window_days + self.oos_days:
            raise ValueError(
                "step_days no puede ser mayor que la ventana completa: no llegaria "
                "a haber una segunda ventana"
            )
        if self.holdout_days and self.holdout_days < self.oos_days:
            raise ValueError(
                "holdout_days debe ser al menos oos_days: si el tramo reservado es "
                "mas corto que una ventana, no es una reserva"
            )
        # El tope de combinaciones se comprueba con el mismo criterio que el
        # motor usa para no barrenar combinaciones invalidas (los dos niveles a
        # null, que es una combinacion que no se puede simular).
        validas = len(
            [
                (tp, sl)
                for tp in self.grid.take_profit_pcts
                for sl in self.grid.stop_loss_pcts
                if tp is not None or sl is not None
            ]
        ) * len(self.grid.max_holds)
        if validas > MAX_WALK_FORWARD_COMBINATIONS:
            raise ValueError(
                f"La rejilla tiene {validas} combinaciones y el tope es "
                f"{MAX_WALK_FORWARD_COMBINATIONS}: reduce los valores de TP, SL o "
                "max_hold"
            )
        if validas == 0:
            raise ValueError(
                "La rejilla no tiene ninguna combinación simulable: todos los pares "
                "de TP y SL son null"
            )
        return self


class WalkForwardRunOut(BaseModel):
    """Cabecera del run, tal y como se guarda.

    No incluye ventanas ni candidatas: para eso esta ``WalkForwardReportOut``.
    Mezclarlas en un solo esquema obligaria a la lista de runs a traer el
    informe entero, y la lista no lo necesita.
    """

    model_config = {"from_attributes": True}

    id: UUID
    scan_job_id: UUID
    status: WalkForwardRunStatus
    config: dict
    grid: dict
    initial_capital: Decimal
    simulations: int
    windows: int
    windows_without_selection: int
    equity_final: Decimal | None = None
    oos_return_pct: Decimal | None = None
    market_return_pct: Decimal | None = None
    max_drawdown_pct: Decimal | None = None
    elapsed_ms: int | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class WalkForwardStrategyOut(BaseModel):
    """Una combinacion de la rejilla, con ``None`` donde no hay nivel.

    Se declara en vez de reusar ``StrategyKey``, que vive en el motor puro y no
    depende de pydantic: los schemas son el contrato de la API y el motor es una
    funcion sin dependencias. Que coincidan ahora es una cuestion de revisin, no
    una garantia del compilador, asi que el contrato se declara aqui.
    """

    take_profit_pct: Decimal | None = None
    stop_loss_pct: Decimal | None = None
    max_hold: int

    @property
    def label(self) -> str:
        tp = (
            "sin TP" if self.take_profit_pct is None else f"TP {self.take_profit_pct:g}"
        )
        sl = "sin SL" if self.stop_loss_pct is None else f"SL {self.stop_loss_pct:g}"
        return f"{tp} / {sl} / {self.max_hold}v"


class WalkForwardWindowOut(BaseModel):
    """Una ventana: que se eligio en el IS y que rindio en el OOS."""

    model_config = {"from_attributes": True}

    index: int
    is_from: datetime
    is_to: datetime
    oos_from: datetime
    oos_to: datetime
    selected_strategy: dict
    is_sharpe: Decimal | None = None
    oos_trades: int
    oos_evaluated: int
    oos_return_pct: Decimal
    oos_net_pnl: Decimal
    oos_equity_final: Decimal
    oos_win_rate: Decimal | None = None
    oos_sharpe: Decimal | None = None
    oos_max_drawdown_pct: Decimal
    market_return_pct: Decimal
    market_max_drawdown_pct: Decimal
    exits: dict = Field(default_factory=dict)

    #: Diferencia contra el mercado en esa ventana. Se calcula al servir y no se
    #: guarda: es una resta de dos columnas que ya estan, y duplicarla seria una
    #: tercera fuente de verdad para el mismo numero.
    @property
    def edge_pct(self) -> Decimal | None:
        return self.oos_return_pct - self.market_return_pct


class WalkForwardCandidateOut(BaseModel):
    """Un candidato con su veredicto. Incluye **los descartados**.

    ``ci95`` es ``None`` para una candidata descartada por no llegar al minimo
    de operaciones: un intervalo de confianza de una muestra que no existe
    invites a creerselo.
    """

    model_config = {"from_attributes": True}

    rank: int
    take_profit_pct: Decimal | None = None
    stop_loss_pct: Decimal | None = None
    max_hold: int
    windows: int
    trades: int
    oos_return_pct: Decimal
    market_return_pct: Decimal
    win_rate_mean: Decimal
    sharpe_mean: Decimal
    sharpe_dispersion: Decimal
    max_drawdown_worst: Decimal
    consistency: Decimal
    beats_market_windows: int
    profitable_windows: int
    score: Decimal
    verdict: WalkForwardVerdict
    ci95_low: Decimal | None = None
    ci95_high: Decimal | None = None
    rejections: list = Field(default_factory=list)
    notes: list = Field(default_factory=list)

    @property
    def strategy(self) -> WalkForwardStrategyOut:
        return WalkForwardStrategyOut(
            take_profit_pct=self.take_profit_pct,
            stop_loss_pct=self.stop_loss_pct,
            max_hold=self.max_hold,
        )


class WalkForwardReportOut(BaseModel):
    """El informe completo: cabecera, ventanas y candidatos."""

    run: WalkForwardRunOut
    windows: list[WalkForwardWindowOut] = Field(default_factory=list)
    candidates: list[WalkForwardCandidateOut] = Field(default_factory=list)


class WalkForwardEquityPointOut(BaseModel):
    model_config = {"from_attributes": True}

    timestamp: datetime
    equity: Decimal
    market_equity: Decimal
    drawdown_pct: Decimal
    #: Que ventana estaba abierta en esta vela, para poder contrastar cada tramo
    #: del grafico con la tabla de ventanas.
    window_index: int


class WalkForwardEquitySeriesOut(BaseModel):
    """Curva OOS encadenada y benchmark encadenado, submuestreada si es larga.

    Mismo contrato que ``BacktestEquitySeriesOut``: ``total_points`` es el numero
    real de velas y ``returned`` el de la serie enviada, para que el frontend
    pueda decir que esta enseñando una version reducida en vez de fingir que son
    todas.
    """

    points: list[WalkForwardEquityPointOut]
    total_points: int
    returned: int
    max_drawdown_pct: Decimal | None = None


class WalkForwardLogOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    run_id: UUID
    timestamp: datetime
    level: str
    message: str
    progress: int | None = None


class WalkForwardRunListOut(BaseModel):
    runs: list[WalkForwardRunOut]
    total: int
