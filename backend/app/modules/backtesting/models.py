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


# ---------------------------------------------------------------------------
# Walk-forward
# ---------------------------------------------------------------------------
class WalkForwardRunStatus(str, Enum):
    """Igual que ``BacktestRunStatus`` y por el mismo motivo.

    Se repite en vez de reutilizarse porque el estado de un ``walk_forward_runs``
    no es el estado de un ``backtest_runs``: un backtest que falla se puede
    reencolar y volver a simular sin perder nada, mientras que un walk-forward
    que falla a la mitad tiene un informe que ya no se puede recuperar. La
    enumeracion compartida invitaria a ese error.
    """

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WalkForwardVerdict(str, Enum):
    """Los tres grados de la §5.2. El orden es intencionado y se usa para
    ordenar: ``sostenida`` antes que ``prometedora`` antes que ``descartada``."""

    SOSTENIDA = "sostenida"
    PROMETEDORA = "prometedora"
    DESCARTADA = "descartada"


class WalkForwardRun(Base):
    """Un walk-forward: la unidad de configuracion congelada y de informe.

    Lo que se guarda, y lo que no, esta decidido antes de escribir la primera
    linea:

    - **La configuracion completa** (rejilla, ventanas, guardas, estrategia
      base) congelada en dos JSONB, ``config`` y ``grid``. Sin ellas el informe
      no se puede ni auditar ni reproducir, y un informe que no se puede
      auditar es una opinion con formato de tabla.
    - **El numero de simulaciones** en su propia columna, y no deducido. Es lo
      que exige la regla 4 del Contrato Estadistico, y ademas es la unica forma
      de que el usuario vea por que un run tardo lo que tardo: el coste crece
      con el producto de combinaciones y ventanas, y sin el numero nadie puede
      distinguir "estuvo dos minutos" de "estuvo dos minutos probando 1.200
      cosas".
    - **Ni una simulacion individual.** Las 1.200 son reproducibles desde
      ``config`` + ``grid``, y guardarlas convierte la base en un vertedero. La
      regla 5 pide archivar resultados negativos, y aqui se cumple guardando
      tambien los candidatos **descartados**, con su motivo en ``rejections``:
      un informe que solo guardara los ganadores no podria cumplirla ni ser
      auditable.
    - **La curva OOS encadenada** en ``walk_forward_equity_points``, con el
      benchmark al lado. Ver la nota de esa tabla sobre por que la §6 decia tres
      tablas y son cuatro.
    """

    __tablename__ = "walk_forward_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    scan_job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("pattern_scan_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(20), default=WalkForwardRunStatus.PENDING.value
    )

    #: Ventanas, guardas, capital inicial y estrategia base, congelados.
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    #: Los tres ejes de la rejilla, congelados.
    grid: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    initial_capital: Mapped[float] = mapped_column(
        Numeric(20, 8), nullable=False, default=1000
    )
    #: Regla 4 del Contrato Estadistico: el numero de combinaciones evaluadas se
    #: registra y se publica. Es ``ventanas x combinaciones`` y no el numero de
    #: filas guardadas, que son solo las candidatas.
    simulations: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: Ventanas que el motor construyo. Va en su propia columna, y no se deduce de
    #: ``walk_forward_windows``, para que una ventana que se perdio al guardar
    #: siga siendo visible en vez de desaparecer en silencio.
    windows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: Ventanas en las que no hubo eleccion posible (IS sin senales o sin
    #: Sharpe). Se publica porque un hueco es informacion: sin este contador, un
    #: informe con 6 ventanas utiles de 10 seria indistinguible de uno completo.
    windows_without_selection: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )

    equity_final: Mapped[float | None] = mapped_column(Numeric(20, 8), nullable=True)
    #: Retorno OOS compuesto de la curva encadenada, y el del benchmark
    #: encadenado. Los candidatos tienen los suyos, por combinacion; estos son los
    #: del informe entero, que es lo unico comparable con el grafico.
    oos_return_pct: Mapped[float | None] = mapped_column(Numeric(12, 6), nullable=True)
    market_return_pct: Mapped[float | None] = mapped_column(
        Numeric(12, 6), nullable=True
    )
    max_drawdown_pct: Mapped[float | None] = mapped_column(
        Numeric(12, 6), nullable=True
    )
    elapsed_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

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

    window_rows: Mapped[list["WalkForwardWindow"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="WalkForwardWindow.index",
    )
    candidate_rows: Mapped[list["WalkForwardCandidate"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="WalkForwardCandidate.rank",
    )
    equity_points: Mapped[list["WalkForwardEquityPoint"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    logs: Mapped[list["WalkForwardLog"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class WalkForwardWindow(Base):
    """Una ventana IS/OOS: que se eligio dentro y que rindio fuera.

    Se guarda **una fila por ventana**, no una por combinacion simulada. Y no se
    guardan los ``trade_pnls`` de cada ventana, que son la entrada cruda del
    bootstrap: son decenas de miles de filas que se regeneran y que no se leen
    nunca, porque el IC95% ya esta calculado y congelado en el candidato.
    """

    __tablename__ = "walk_forward_windows"

    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("walk_forward_runs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    index: Mapped[int] = mapped_column(Integer, primary_key=True)

    is_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_to: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    oos_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    oos_to: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    #: La combinacion que gano el IS, tal y como la eligio el motor. JSONB y no
    #: tres columnas porque ``take_profit_pct`` puede ser ``None`` y ``None`` en
    #: JSONB sobrevive el viaje a la base, mientras que un ``0.0`` seria un take
    #: profit del 0 %.
    selected_strategy: Mapped[dict] = mapped_column(JSONB, nullable=False)
    #: Sharpe de la combinacion elegida **en el IS**. Se guarda para poder ver si
    #: la seleccion fue buena o solo Ayatno; el score del candidato no lo usa,
    #: porque usa solo el OOS.
    is_sharpe: Mapped[float | None] = mapped_column(Numeric(12, 6), nullable=True)

    oos_trades: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    oos_evaluated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    oos_return_pct: Mapped[float] = mapped_column(
        Numeric(12, 6), nullable=False, default=0
    )
    oos_net_pnl: Mapped[float] = mapped_column(
        Numeric(20, 8), nullable=False, default=0
    )
    oos_equity_final: Mapped[float] = mapped_column(
        Numeric(20, 8), nullable=False, default=1000
    )
    oos_win_rate: Mapped[float | None] = mapped_column(Numeric(12, 6), nullable=True)
    oos_sharpe: Mapped[float | None] = mapped_column(Numeric(12, 6), nullable=True)
    oos_max_drawdown_pct: Mapped[float] = mapped_column(
        Numeric(12, 6), nullable=False, default=0
    )
    market_return_pct: Mapped[float] = mapped_column(
        Numeric(12, 6), nullable=False, default=0
    )
    market_max_drawdown_pct: Mapped[float] = mapped_column(
        Numeric(12, 6), nullable=False, default=0
    )
    #: Reparto de motivos de cierre, con ``end_of_data`` incluido y no separado:
    #: aqui no se calcula el win rate, asi que no hay por que excluirlo. Se
    #: guarda tal cual para poder detectar una ventana a la que le faltan velas
    #: al final.
    exits: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    run: Mapped["WalkForwardRun"] = relationship(back_populates="window_rows")


class WalkForwardCandidate(Base):
    """Una combinacion que el motor evaluo, y su veredicto.

    Guarda **también las descartadas**, con ``rejections`` y ``notes``. Es lo que
    hace que el informe sea auditable: una tabla de dieciseis filas donde
    faltan las dos que no pasaron es indistinguible de un motor que nunca las
    probo, y esa es precisamente la duda que un usuario tiene al leer un
    veredicto.
    """

    __tablename__ = "walk_forward_candidates"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("walk_forward_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    #: Posicion en el informe, ya ordenada por veredicto y score. Se guarda
    #: para que la tabla salga igual sin tener que re-ordenar en cada lectura, y
    #: para que dos clicks den dos informes con el mismo orden.
    rank: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    take_profit_pct: Mapped[float | None] = mapped_column(Numeric(12, 6), nullable=True)
    stop_loss_pct: Mapped[float | None] = mapped_column(Numeric(12, 6), nullable=True)
    max_hold: Mapped[int] = mapped_column(Integer, nullable=False)

    windows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    trades: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    beats_market_windows: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    profitable_windows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    oos_return_pct: Mapped[float] = mapped_column(
        Numeric(12, 6), nullable=False, default=0
    )
    market_return_pct: Mapped[float] = mapped_column(
        Numeric(12, 6), nullable=False, default=0
    )
    win_rate_mean: Mapped[float] = mapped_column(
        Numeric(12, 6), nullable=False, default=0
    )
    sharpe_mean: Mapped[float] = mapped_column(
        Numeric(12, 6), nullable=False, default=0
    )
    sharpe_dispersion: Mapped[float] = mapped_column(
        Numeric(12, 6), nullable=False, default=0
    )
    max_drawdown_worst: Mapped[float] = mapped_column(
        Numeric(12, 6), nullable=False, default=0
    )
    consistency: Mapped[float] = mapped_column(
        Numeric(12, 6), nullable=False, default=0
    )
    score: Mapped[float] = mapped_column(Numeric(12, 6), nullable=False, default=0)
    verdict: Mapped[str] = mapped_column(
        String(20), default=WalkForwardVerdict.DESCARTADA.value
    )

    #: IC95% del retorno OOS compuesto. ``NULL`` para una candidata descartada
    #: por no llegar al minimo de operaciones: un intervalo de confianza de una
    #: muestra que no existe invites a creerselo.
    ci95_low: Mapped[float | None] = mapped_column(Numeric(12, 6), nullable=True)
    ci95_high: Mapped[float | None] = mapped_column(Numeric(12, 6), nullable=True)
    #: Motivos de descarte y notas legibles, en el idioma del veredicto. Se
    #: guardan porque un veredicto sin motivo obliga a volver a ejecutar el run
    #: para entender por que salio asi.
    rejections: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    notes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    run: Mapped["WalkForwardRun"] = relationship(back_populates="candidate_rows")


class WalkForwardEquityPoint(Base):
    """Curva OOS encadenada, una fila por vela, con el benchmark encadenado.

    **Esta tabla no estaba en la §6 de la spec, que decia tres.** Se anade
    porque el endpoint ``GET /runs/{id}/equity`` de la §8 promete una fila por
    vela, y ni ``walk_forward_windows`` ni ``walk_forward_candidates`` tienen
    datos por vela: guardan agregados por ventana y por combinacion. Las dos
    salidas sin esta tabla son: recalcular la curva reejecutando el walk-forward
    entero (uno o dos minutos para pintar un grafico) o devolver una aproximacion
    por ventana, que no seria la curva y por tanto no se podria dibujar.

    Se declara hypertable por lo mismo que ``backtest_equity_points``: es una
    serie temporal y crece con el rango, no con el numero de combinaciones.
    Guardar el benchmark en la misma fila y no en otra tabla es lo que permite
    dibujar las dos curvas del informe con un solo barrido.
    """

    __tablename__ = "walk_forward_equity_points"

    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("walk_forward_runs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True
    )
    equity: Mapped[float] = mapped_column(Numeric(20, 8), nullable=False)
    #: Buy and hold sobre la misma concatenacion de ventanas OOS, con el capital
    #: rebasado en cada frontera igual que la estrategia. Comparar la estrategia
    #: encadenada contra un mercado que no esta encadenado daria una diferencia
    #: que no existe.
    market_equity: Mapped[float] = mapped_column(Numeric(20, 8), nullable=False)
    drawdown_pct: Mapped[float] = mapped_column(Numeric(12, 6), nullable=False)
    #: Que ventana estaba abierta en esta vela. Sin esto no se puede saber a que
    #: tramo del grafico corresponde cada fila de ``walk_forward_windows``, y sin
    #: eso la tabla por ventanas no se puede contrastar con la curva.
    window_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    run: Mapped["WalkForwardRun"] = relationship(back_populates="equity_points")


class WalkForwardLog(Base):
    """Linea de progreso o de diagnostico de un run de walk-forward.

     Quinta tabla, y la spec solo decia tres. La reason es que el progreso por
     ventana no tiene donde vivir si no: el WebSocket del backtest sondea
     ``backtest_logs`` con paginacion por offset y cierra cuando el run llega a un
     estado terminal, y ``backtest_logs`` tiene clave foranea a ``backtest_runs``.
     Un walk-forward **no** es un backtest: no se puede escribir en la tabla de
     logs de otro y un run que no es suyo, y meterlo ahi seria
    mezclar dos tipos de informe en la misma lista.

     Se podria meter el progreso en una columna JSONB del run, y se descarto: el
     WebSocket avanza por offset porque las lineas son inmutables y llegan en
     orden, y una fila que se sobrescribe rompe ese patron ademas de hacer que el
     historial de un run no se pueda leer despues.
    """

    __tablename__ = "walk_forward_logs"
    __table_args__ = (
        Index("ix_walk_forward_logs_run_timestamp", "run_id", "timestamp"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("walk_forward_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    level: Mapped[str] = mapped_column(String(10), default="info")
    message: Mapped[str] = mapped_column(Text, nullable=False)
    #: Ventanas terminadas. Va en [0, 100] para que el front pueda pintar una
    #: barra sin tener que saber cuantas ventanas hay, que ademas no se conoce
    #: hasta que el motor construye el rango.
    progress: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    run: Mapped["WalkForwardRun"] = relationship(back_populates="logs")
