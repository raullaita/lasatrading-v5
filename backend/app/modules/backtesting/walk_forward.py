"""Walk-forward: partir un rango en ventanas, elegir en una y medir en otra.

Modulo **puro**: no importa SQLAlchemy ni toca la base de datos. Recibe velas y
senales de un rango y devuelve un informe. Eso es lo que permite probar el
algoritmo entero contra numeros escritos a mano, que es la unica manera de saber
si un motor de walk-forward esta bien: **sus fallos son silenciosos**. Un rango
mal partido no lanza nada, produce un informe con aspecto normal y conclusiones
equivocadas.

Cinco decisiones que hacen que esto no sea "un backtest con mas ventanas":

* **La frontera de la ventana es la senal, y el marco de velas llega mas alla.**
  Una senal entra a la apertura de T+1 y puede seguir abierta ``max_hold`` velas.
  Si el marco se cortara en la frontera, las ultimas operaciones de cada ventana
  saldrian con motivo ``end_of_data`` y la ventana pareceria peor de lo que es.
  El sesgo es sistematico y en una sola direccion, que es la peor forma de
  sesgo: no se ve comparando ventanas entre si, porque todas lo tienen.

* **El capital se reinicia en cada ventana.** Si no, el equity de la ventana N
  arrastra el de todas las anteriores y las ventanas dejan de ser comparables,
  que es justo lo que el motor existe para medir. Para el grafico, las curvas OOS
  se encadenan rebasando cada ventana en el capital final de la anterior.

* **La eleccion se hace solo con el IS de esa ventana.** Con solapamiento, el OOS
  de una ventana cae dentro del IS de la siguiente, y eso **no es fuga**: es la
  naturaleza de un roll-forward. Lo que no puede pasar es que una metrica de
  validacion entre en una decision, y aqui no entra en ninguna.

* **La Puntuacion de Robustez se calcula solo con ventanas OOS**, y sus pesos
  estan congelados en la especificacion. Ajustarlos contra los resultados seria
  hacer la misma eleccion un nivel mas arriba, y es mas dificil de detectar
  porque parece metodologia.

* **El veredicto tiene tres grados.** Pasar las guardas con el intervalo de
  confianza incluyendo el cero no es lo mismo que excluirlo, y colapsar los dos
  en "estrategia valida" es lo que produce estrategias de papel.

Lo que este modulo **no** hace, por diseno: devolver un ganador. Devuelve
candidatos con su veredicto, y el orden es consecuencia del score.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from typing import Literal

import pandas as pd

from app.modules.backtesting.analysis import SweepGrid, buy_and_hold, sweep
from app.modules.backtesting.engine import StrategyConfig, run_backtest

#: Pesos de la Puntuacion de Robustez. **Congelados** en la especificacion, con
#: test que fija el valor exacto del score. Si se ajustaran contra los
#: resultados, estariamos haciendo la misma eleccion un nivel mas arriba.
SCORE_WEIGHTS: dict[str, float] = {
    "sharpe": 0.35,
    "win_rate": 0.20,
    "consistency": 0.20,
    "drawdown": -0.15,
    "dispersion": -0.10,
}

#: Escala del Sharpe dentro del score. ``tanh`` comprime a [-1, 1] para que un
#: Sharpe de 8 no se coma el resto de la suma: con un escalado lineal, un solo
#: termino decide el score y los demas dejan de importar.
SHARPE_SCALE = 2.0

BOOTSTRAP_ITERATIONS = 20_000

#: Semilla por defecto. Sin ella el IC95% cambia entre dos ejecuciones del mismo
#: informe, y un numero que se mueve solo no se puede comparar con nada. La
#: simulacion es determinista; el bootstrap es un remuestreo.
BOOTSTRAP_SEED = 1234

#: Minutos por vela de los timeframes soportados. Solo se usa para convertir
#: ``max_hold`` (en velas) en una extension temporal del marco de velas.
MINUTES_PER_TIMEFRAME: dict[str, int] = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "2h": 120,
    "4h": 240,
    "1d": 1440,
}

Verdict = Literal["descartada", "prometedora", "sostenida"]


class WalkForwardError(ValueError):
    """Una configuracion de ventanas que no se puede construir."""


class WalkForwardCancelled(WalkForwardError):
    """El motor se detuvo porque quien lo lanzo pidio cancelar.

    Existe como excepcion y no como retorno porque el motor es una funcion pura:
    "cancelado" no es un resultado, es la ausencia de resultado. Si el motor
    devolviera un informe parcial, el servicio no tendria forma de distinguirlo
    de un informe completo con pocas ventanas, y un informe parcial con
    veredictos es exactamente el objeto que no se debe poder leer.

    Hereda de ``WalkForwardError`` a proposito: quien llama al motor y no conoce
    esta clase sigue atrapando el error que ya conocia, y el que la conoce la
    distingue porque cancelar no es fallar.
    """


# ---------------------------------------------------------------------------
# Ventanas
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class WindowSpec:
    """Tamano y desplazamiento de las ventanas, con las guardas del veredicto.

    Los cortes son **inclusivos por arriba**, igual que ``load_candles``: un rango
    descrito como "hasta las 00:00 del dia X" incluye esa vela. Mezclar las
    convenciones seria la fuente clasica de perder una vela en cada frontera.
    """

    window_days: int
    oos_days: int
    step_days: int
    holdout_days: int = 0
    min_windows: int = 3
    min_trades: int = 30
    #: Fraccion de ventanas OOS en las que hay que superar al mercado. El valor
    #: ``0`` **desactiva** la guarda, y existe para diagnostico: sirve para ver
    #: como seria el ranking de candidatos sin el filtro de mercado y comprobar
    #: que el veredicto cambia al activarlo. Un motor cuya guarda no se puede
    #: desactivar es un motor del que no se puede depurar.
    beats_market_ratio: float = 0.6
    #: Regimenes distintos exigidos para el veredicto completo.
    min_regimes: int = 3
    #: Regimenes que el usuario ha declarado tener. Con menos de ``min_regimes``,
    #: el techo del veredicto baja a ``prometedora`` aunque el IC95% excluyera
    #: el cero: una sola serie de precios no demuestra robustez.
    regimes_declared: int = 1
    #: Tope de simulaciones. Se valida antes de empezar, no durante.
    max_simulations: int = 2000

    def __post_init__(self) -> None:
        if self.window_days < 1:
            raise WalkForwardError("window_days debe ser >= 1")
        if self.oos_days < 1:
            raise WalkForwardError("oos_days debe ser >= 1")
        if self.step_days < 1:
            raise WalkForwardError("step_days debe ser >= 1")
        if self.holdout_days < 0:
            raise WalkForwardError("holdout_days no puede ser negativo")
        if self.min_windows < 1:
            raise WalkForwardError("min_windows debe ser >= 1")
        if self.min_trades < 0:
            raise WalkForwardError("min_trades no puede ser negativo")
        if not 0 <= self.beats_market_ratio <= 1:
            raise WalkForwardError("beats_market_ratio debe estar en [0, 1]")

    def estimated_windows(self, start: pd.Timestamp, end: pd.Timestamp) -> int:
        """Cuantas ventanas salen, sin construirlas. Para el contador del formulario."""
        try:
            return len(build_windows(start, end, self))
        except WalkForwardError:
            return 0

    def estimated_simulations(
        self, start: pd.Timestamp, end: pd.Timestamp, combinaciones: int
    ) -> int:
        return self.estimated_windows(start, end) * combinaciones


@dataclass(frozen=True, slots=True)
class Window:
    """Una ventana roll-forward: un IS para elegir y un OOS para medir."""

    index: int
    is_from: pd.Timestamp
    is_to: pd.Timestamp
    oos_from: pd.Timestamp
    oos_to: pd.Timestamp


def build_windows(
    start: pd.Timestamp, end: pd.Timestamp, spec: WindowSpec
) -> list[Window]:
    """Parte ``[start, end]`` en ventanas roll-forward.

    El primer IS empieza en ``start`` y mide ``window_days``; el primer OOS empieza
    donde acaba ese IS. Cada ventana desplaza el IS ``step_days``, de modo que con
    ``step_days == window_days`` las ventanas no se solapan y con un valor menor
    se solapan: mas ventanas y menos independencia entre ellas.

    Una ventana cuyo OOS **no cabe entero** antes del final efectivo (fin del
    rango menos el holdout) se descarta en vez de recortarse. Un OOS truncado
    tendria menos senales que las demas y pareceria peor por el recorte y no por
    la estrategia: es el sesgo de truncamiento de la cabecera, otra vez.
    """
    if end <= start:
        raise WalkForwardError("El rango final debe ser posterior al inicial")
    if spec.holdout_days and spec.holdout_days >= (end - start).days:
        raise WalkForwardError(
            "El holdout se come todo el rango: no queda nada que evaluar"
        )

    effective_end = (
        end - pd.Timedelta(days=spec.holdout_days) if spec.holdout_days else end
    )
    windows: list[Window] = []
    cursor = start + pd.Timedelta(days=spec.window_days)

    while cursor < effective_end:
        oos_from = cursor
        oos_to = oos_from + pd.Timedelta(days=spec.oos_days)
        if oos_to > effective_end:
            break
        windows.append(
            Window(
                index=len(windows) + 1,
                is_from=cursor - pd.Timedelta(days=spec.window_days),
                is_to=cursor,
                oos_from=oos_from,
                oos_to=oos_to,
            )
        )
        cursor = cursor + pd.Timedelta(days=spec.step_days)

    if not windows:
        raise WalkForwardError(
            "El rango no da ni una ventana completa: reduce window_days y oos_days, "
            "o amplía el rango"
        )
    return windows


def assert_continuity(
    candles: pd.DataFrame,
    minutos_por_vela: int,
    multiplicador: int = 4,
) -> None:
    """Rechaza un rango con huecos internos, y dice donde estan.

     ``build_windows`` solo mira el primer y el ultimo timestamp, asi que un
     rango con un agujero en medio produce ventanas **dentro del agujero**:
    icuenta igual, no tienen velas ni señales, y salen como "sin seleccion
     posible" en un informe que parece completo.

     Y el daño no es que falten ventanas: es al reves. Las ventanas vacias se
     cuentan en `windows`, y el numero de ventanas es el tamaño de la muestra
     del bootstrap por bloques. Treinta ventanas de las que veinte no tienen ni
     una vela dan un IC95% estrecho y un veredicto `sostenida` sobre siete
     ventanas reales. Es la confianza inventada mas cara que puede tener este
     modulo, y sale de contar ventanas que no existen.

     El umbral no es "un hueco" sino "un hueco mas grande de lo que un mercado
     abierto deja": cuatro veces la duracion de la vela, con un minimo de un dia
     y medio para que un fin de semana en velas diarias no se confunda con datos
     que faltan.
    """
    if candles.empty or len(candles) < 2:
        return
    umbral = pd.Timedelta(minutes=max(minutos_por_vela * multiplicador, 2_160))
    indice = candles.index
    saltos = indice.to_series().diff()
    huecos = saltos[saltos > umbral]
    if huecos.empty:
        return
    primero = indice[0]
    ultimo = indice[-1]
    detalle = []
    for posicion, salto in huecos.head(5).items():
        desde = indice[indice < posicion][-1]
        detalle.append(f"{desde:%Y-%m-%d} → {posicion:%Y-%m-%d} ({salto.days} días)")
    extra = "" if len(huecos) <= 5 else f" (y {len(huecos) - 5} más)"
    raise WalkForwardError(
        f"El rango no es continuo: {len(huecos)} hueco(s) de más de "
        f"{umbral.days} días, el primero en {detalle[0]}{extra}. El rango va del "
        f"{primero:%Y-%m-%d} al {ultimo:%Y-%m-%d} pero entre medias no hay velas. "
        "Un walk-forward sobre un rango con huecos contaria ventanas vacias, y "
        "esas ventanas cuentan en el intervalo de confianza: dariá un veredicto "
        "sobre siete ventanas reales como si fueran treinta. Usa un rango continuo."
    )


def assert_isolation(windows: Sequence[Window]) -> None:
    """Comprueba lo que un roll-forward **si** garantiza.

    Solo tres cosas, y las tres son estructurales:

    1. Dentro de una ventana, el IS termina antes de que empiece su OOS. Si se
       solaparan, la eleccion de esa ventana habria visto su propia validacion.
    2. Cada intervalo tiene duracion positiva.
    3. Las ventanas avanzan en el tiempo: el OOS de la siguiente empieza despues
       del OOS de la anterior.

    Lo que **no** se comprueba, y no por pereza sino porque es falso con
    solapamiento: que el OOS de una ventana quede fuera del IS de las siguientes.
    Con ventanas de 120 dias y desplazamiento de 60, el OOS de la 1 va de
    2021-12-30 a 2022-02-28 y el IS de la 2 empieza el 2021-10-31: la
    validacion de la primera esta dentro del entrenamiento de la segunda, y eso
    es lo normal.

    No es fuga. La fuga seria que una metrica de validacionJG participara en una
    decision, y aqui la unica decision es ``select_in_sample``, que recibe los
    limites de **su** ventana y no ve ninguna otra. Con ventana 365 y
    desplazamiento 90, ademas, el OOS de la ventana 1 esta casi entero dentro del
    IS de la ventana 2; si eso fuera fuga, el roll-forward no se podria hacer
    nunca con solapamiento, que es el modo de uso con mas ventanas.

    Lo que si tiene un coste, y es estadistico y no de fuga: los OOS no son
    independientes entre si, asi que el numero efectivo de ventanas es menor que
    el de ventanas. De ahi que el IC95% sea un bootstrap de bloques.
    """
    for ventana in windows:
        if ventana.is_from >= ventana.is_to:
            raise WalkForwardError(f"Ventana {ventana.index}: el IS no tiene duración")
        if ventana.oos_from >= ventana.oos_to:
            raise WalkForwardError(f"Ventana {ventana.index}: el OOS no tiene duración")
        if ventana.is_to > ventana.oos_from:
            raise WalkForwardError(
                f"Ventana {ventana.index}: el IS invade su propio OOS"
            )
    for anterior, siguiente in zip(windows, windows[1:], strict=False):
        if siguiente.oos_from <= anterior.oos_from:
            raise WalkForwardError(
                f"Ventana {siguiente.index}: no avanza en el tiempo respecto a la "
                f"anterior; las ventanas tienen que ir hacia delante"
            )


# ---------------------------------------------------------------------------
# Recortes
# ---------------------------------------------------------------------------
def _slice_signals(
    signals: pd.DataFrame, desde: pd.Timestamp, hasta: pd.Timestamp
) -> pd.DataFrame:
    """Senales cuya marca de tiempo cae en ``[desde, hasta]``.

    El corte es por **senal** y no por vela: es la senal la que decide a que
    ventana pertenece una operacion. Un motor que cortara el marco de velas y
    dejara las senales de la frontera en la ventana siguiente contaria esas
    operaciones dos veces.
    """
    if signals.empty:
        return signals
    marcas = signals["timestamp"]
    return signals[(marcas >= desde) & (marcas <= hasta)].reset_index(drop=True)


def _slice_candles(
    candles: pd.DataFrame, desde: pd.Timestamp, hasta: pd.Timestamp
) -> pd.DataFrame:
    """Velas del rango exacto, sin cola.

    Para el **mercado**. Aqui al contrario que en la simulacion: medir el
    mercado con velas de mas y a la estrategia sin ellas seria compararlos sobre
    rangos distintos, y la comparacion dejaria de ser una comparacion.
    """
    if candles.empty:
        return candles
    return candles[(candles.index >= desde) & (candles.index <= hasta)]


def _resolve_candles(
    candles: pd.DataFrame, desde: pd.Timestamp, hasta: pd.Timestamp, extra_minutos: int
) -> pd.DataFrame:
    """Marco de simulacion: su rango **mas** la cola de resolucion.

    La cola son ``max_hold`` velas por encima de la frontera. Sin ellas, la ultima
    senal de la ventana entra, no tiene velas donde seguir y se cierra con
    ``end_of_data``: el PnL no es malo, es que no se pudo observar, y se
    contabiliza como si lo fuera. Restar una fraccion de las operaciones de cada
    ventana es un sesgo **sistematico y en una sola direccion**, invisible al
    comparar ventanas entre si porque todas lo tienen.
    """
    if candles.empty or extra_minutos <= 0:
        return _slice_candles(candles, desde, hasta)
    objetivo = hasta + pd.Timedelta(minutes=extra_minutos)
    return candles[(candles.index >= desde) & (candles.index <= objetivo)]


def _market_window(
    candles: pd.DataFrame, desde: pd.Timestamp, hasta: pd.Timestamp, capital: float
):
    """Benchmark del rango de la ventana, **sin** la cola.

    Aqui al contrario que en la simulacion: el mercado se mide en el rango exacto,
    sin velas de mas. Comparar el retorno del mercado con el de una estrategia a
    la que se le ha dado velas extra le estaria dando al mercado un rango
    distinto del que se le pide a la estrategia, y la comparacion dejaria de ser
    una comparacion.
    """
    return buy_and_hold(_slice_candles(candles, desde, hasta), capital)


# ---------------------------------------------------------------------------
# Metricas de una ventana
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class WindowMetrics:
    """Lo que una ventana mide, en la unidad de esa ventana."""

    trades: int
    evaluated: int
    return_pct: float
    net_pnl: float
    equity_final: float
    win_rate: float | None
    sharpe: float | None
    max_drawdown_pct: float
    market_return_pct: float
    market_max_drawdown_pct: float
    exits: dict[str, int] = field(default_factory=dict)
    trade_pnls: tuple[float, ...] = ()


def _exits_of(result) -> dict[str, int]:
    exits: dict[str, int] = {}
    for trade in result.trades:
        reason = trade.exit_reason or "end_of_data"
        exits[reason] = exits.get(reason, 0) + 1
    return exits


def _empty_metrics(capital: float, mercado: float, mercado_dd: float) -> WindowMetrics:
    return WindowMetrics(
        trades=0,
        evaluated=0,
        return_pct=0.0,
        net_pnl=0.0,
        equity_final=capital,
        win_rate=None,
        sharpe=None,
        max_drawdown_pct=0.0,
        market_return_pct=mercado,
        market_max_drawdown_pct=mercado_dd,
    )


def evaluate_window(
    candles: pd.DataFrame,
    signals: pd.DataFrame,
    config: StrategyConfig,
    desde: pd.Timestamp,
    hasta: pd.Timestamp,
    minutos_por_vela: int,
):
    """Simula una combinacion en una ventana y la mide contra el mercado.

    Devuelve ``(metricas, curva)``. La curva es la que se encadena despues para
    dibujar el OOS conjunto; se devuelve en vez de guardarla aparte para que
    nadie pueda medir el retorno de una ventana con la curva de otra.

    El capital se reinicia a ``config.initial_capital``: es el unico modo de que
    dos ventanas sean comparables. Encadenar el equity dentro de aqui daria a la
    ventana N el resultado acumulado de todas las anteriores.
    """
    capital = config.initial_capital
    mercado = _market_window(candles, desde, hasta, capital)
    marco = _resolve_candles(candles, desde, hasta, config.max_hold * minutos_por_vela)
    senales = _slice_signals(signals, desde, hasta)

    if marco.empty or senales.empty or mercado.candles == 0:
        return (
            _empty_metrics(
                capital,
                mercado.total_return_pct or 0.0,
                mercado.max_drawdown_pct or 0.0,
            ),
            None,
        )

    result = run_backtest(marco, senales, config)
    metricas = result.metrics
    return (
        WindowMetrics(
            trades=int(metricas.get("total_trades") or 0),
            evaluated=int(metricas.get("trades_evaluated") or 0),
            return_pct=float(metricas.get("total_return_pct") or 0.0),
            net_pnl=float(metricas.get("net_pnl") or 0.0),
            equity_final=float(metricas.get("equity_final") or capital),
            win_rate=metricas.get("win_rate"),
            sharpe=metricas.get("sharpe_ratio"),
            max_drawdown_pct=float(metricas.get("max_drawdown_pct") or 0.0),
            market_return_pct=mercado.total_return_pct or 0.0,
            market_max_drawdown_pct=mercado.max_drawdown_pct or 0.0,
            exits=_exits_of(result),
            trade_pnls=tuple(
                float(t.net_pnl) for t in result.trades if t.net_pnl is not None
            ),
        ),
        result.equity,
    )


# ---------------------------------------------------------------------------
# Seleccion
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class StrategyKey:
    """Identidad de una combinacion de la rejilla.

    El motor usa ``None`` para "sin este nivel" y ``0.0`` seria un nivel distinto
    e invalido, asi que la clave conserva la distincion: un ``None`` que pasara
    por JSON y volviera como ``0.0`` seria un take profit del 0%.
    """

    take_profit_pct: float | None
    stop_loss_pct: float | None
    max_hold: int

    @classmethod
    def from_dict(cls, payload: dict) -> StrategyKey:
        return cls(
            take_profit_pct=payload.get("take_profit_pct"),
            stop_loss_pct=payload.get("stop_loss_pct"),
            max_hold=int(payload["max_hold"]),
        )

    def label(self) -> str:
        tp = (
            "sin TP" if self.take_profit_pct is None else f"TP {self.take_profit_pct:g}"
        )
        sl = "sin SL" if self.stop_loss_pct is None else f"SL {self.stop_loss_pct:g}"
        return f"{tp} / {sl} / {self.max_hold}v"

    def apply(self, base: StrategyConfig) -> StrategyConfig:
        return replace(
            base,
            take_profit_pct=self.take_profit_pct,
            stop_loss_pct=self.stop_loss_pct,
            max_hold=self.max_hold,
        )


def select_in_sample(
    candles: pd.DataFrame,
    signals: pd.DataFrame,
    base: StrategyConfig,
    grid: SweepGrid,
    ventana: Window,
    minutos_por_vela: int,
) -> tuple[StrategyKey, float] | None:
    """Elige la combinacion de la rejilla con mejor **Sharpe** en el IS.

    Sharpe y no PnL: el PnL de una ventana depende de su capital y de su ruido, y
    comparar ventanas de distinta duracion por PnL favorece a la mas ruidosa. El
    Sharpe es libre de escala.

    Devuelve ``None`` si el IS no tiene senales o ninguna combinacion produce
    Sharpe, en lugar de devolver la primera: una eleccion sobre un IS vacio no es
    una eleccion, es un azares con forma de decision.

    Reutiliza ``analysis.sweep``, la misma funcion que consume el endpoint de
    barrido del backtest: una sola implementacion de "que pasa si cambio estos
    niveles". El marco incluye la cola de ``max_hold`` por la misma razon que la
    simulacion OOS, y por la misma justificacion.
    """
    marco = _resolve_candles(
        candles,
        ventana.is_from,
        ventana.is_to,
        grid.max_holds[0] * minutos_por_vela if grid.max_holds else 0,
    )
    senales = _slice_signals(signals, ventana.is_from, ventana.is_to)
    if marco.empty or senales.empty:
        return None

    puntos = sweep(marco, senales, base, grid)
    con_sharpe = [p for p in puntos if p.sharpe_ratio is not None]
    if not con_sharpe:
        return None
    mejor = max(con_sharpe, key=lambda p: p.sharpe_ratio or -math.inf)
    return (
        StrategyKey(
            take_profit_pct=mejor.take_profit_pct,
            stop_loss_pct=mejor.stop_loss_pct,
            max_hold=mejor.max_hold,
        ),
        mejor.sharpe_ratio or 0.0,
    )


# ---------------------------------------------------------------------------
# Puntuacion de robustez
# ---------------------------------------------------------------------------
def robustness_score(
    sharpes: Sequence[float],
    win_rates: Sequence[float],
    drawdowns_pct: Sequence[float],
) -> float:
    """Puntuacion de Robustez en escala 0-100 (puede ser negativa).

    Solo con ventanas OOS. Los pesos son ``SCORE_WEIGHTS`` y estan congelados; el
    Sharpe entra comprimido con ``tanh``.

    El score **ordena** candidatos que ya pasaron las guardas: no las sustituye.
    Un candidato con score alto que no supera al mercado no se recomienda, y uno
    que las pasa con score bajo sale ultimo, no descartado.
    """
    if not sharpes:
        return 0.0

    sharpe_medio = sum(sharpes) / len(sharpes)
    win_rate_medio = sum(win_rates) / len(win_rates) if win_rates else 0.0
    drawdown_peor = max(drawdowns_pct) if drawdowns_pct else 0.0

    return 100.0 * (
        SCORE_WEIGHTS["sharpe"] * math.tanh(sharpe_medio / SHARPE_SCALE)
        + SCORE_WEIGHTS["win_rate"] * win_rate_medio
        + SCORE_WEIGHTS["consistency"] * _consistencia(sharpes)
        - abs(SCORE_WEIGHTS["drawdown"]) * (drawdown_peor / 100.0)
        - abs(SCORE_WEIGHTS["dispersion"]) * _desviacion(sharpes)
    )


def _consistencia(sharpes: Sequence[float]) -> float:
    """Fraccion de ventanas favorables, medida con el Sharpe.

    Se mide con el Sharpe y no con el PnL porque es la misma magnitud con la que
    se elige en el IS: medir la consistencia con otro criterio haria que el motor
    dijera dos cosas distintas con dos reglas.
    """
    if not sharpes:
        return 0.0
    return sum(1 for v in sharpes if v > 0) / len(sharpes)


def _desviacion(valores: Sequence[float]) -> float:
    """Desviacion tipica **muestral** (n-1).

    Con dos o tres ventanas, la poblacional divide entre un numero de ventanas
    que todavia no es un numero grande de observaciones, y la penalizacion por
    dispersion parece mayor de lo que es.
    """
    if len(valores) < 2:
        return 0.0
    media = sum(valores) / len(valores)
    return math.sqrt(sum((v - media) ** 2 for v in valores) / (len(valores) - 1))


# ---------------------------------------------------------------------------
# Bootstrap de bloques
# ---------------------------------------------------------------------------
def block_bootstrap_ci(
    bloques: Sequence[Sequence[float]],
    iteraciones: int = BOOTSTRAP_ITERATIONS,
    seed: int = BOOTSTRAP_SEED,
) -> tuple[float, float] | None:
    """IC95% del PnL OOS agregado, por **bootstrap de bloques**.

    Un bloque por ventana. Se remuestrea cada ventana por separado con reemplazo,
    se suma dentro de la ventana y se suman las ventanas.

    Remuestrar plano trataria cada operacion como independiente de todas las
    demas, y con ventanas solapadas no lo son: dos operaciones de ventanas
    distintas pueden ser la misma senal vista desde dos ventanas, y contarlas
    como dos independientes acorta el intervalo por debajo de lo que corresponde.
    El bloque conserva la dependencia interna de la ventana y solo trata a las
    ventanas como la unidad de intercambio.

    Devuelve ``None`` si no hay ninguna operacion: un intervalo de una muestra
    vacia no es un intervalo, y ``0,0`` se leeria como "no hay riesgo".
    """
    utiles = [tuple(b) for b in bloques if b]
    if not utiles:
        return None

    generador = random.Random(seed)
    totales: list[float] = []
    for _ in range(iteraciones):
        suma = 0.0
        for bloque in utiles:
            n = len(bloque)
            suma += sum(bloque[generador.randrange(n)] for _ in range(n))
        totales.append(suma)
    totales.sort()
    return (
        totales[int(0.025 * iteraciones)],
        totales[int(0.975 * iteraciones)],
    )


# ---------------------------------------------------------------------------
# Candidatos y veredicto
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class WindowOutcome:
    """Lo que pasó en una ventana: que se eligio en el IS y que rindio en el OOS."""

    window: Window
    selected: StrategyKey
    is_sharpe: float
    oos: WindowMetrics


@dataclass(frozen=True, slots=True)
class CandidateReport:
    """Veredicto de una combinacion, agregado sobre sus ventanas OOS."""

    strategy: StrategyKey
    windows: int
    trades: int
    #: Retorno OOS **compuesto** entre sus ventanas: el capital se reinicia en cada
    #: una, asi que componer es multiplicar los factores ``(1 + r)``. Es la cifra
    #: que representa al walk-forward entero, y no la suma de los retornos, que
    #: sumaria la misma configuracion tantas veces como saliera elegida.
    oos_return_pct: float
    market_return_pct: float
    win_rate_mean: float
    sharpe_mean: float
    sharpe_dispersion: float
    max_drawdown_worst: float
    consistency: float
    beats_market_windows: int
    profitable_windows: int
    score: float
    verdict: Verdict
    ci95: tuple[float, float] | None
    rejections: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


def _compuesto(retornos: Sequence[float]) -> float:
    """Compone una secuencia de retornos en porcentaje.

    ``prod(1 + r) - 1``. Con una ventana vacia da 0,0 en vez de NaN.
    """
    acumulado = 1.0
    for valor in retornos:
        acumulado *= 1.0 + valor / 100.0
    return (acumulado - 1.0) * 100.0


def build_candidate(
    key: StrategyKey,
    outcomes: Sequence[WindowOutcome],
    spec: WindowSpec,
    iteraciones: int = BOOTSTRAP_ITERATIONS,
    seed: int = BOOTSTRAP_SEED,
) -> CandidateReport:
    """Agrega las ventanas de una configuracion y dicta su veredicto.

    El orden es deliberado: primero las **guardas duras**, que son objetivas y no
    dependen de ninguna constante elegida por nosotros; despues el intervalo, que
    es lo que separa ``prometedora`` de ``sostenida``; y por ultimo el tope por
    numero de regimenes, que es una limitacion de la evidencia disponible y no un
    defecto del candidato.
    """
    sharpes = [o.oos.sharpe or 0.0 for o in outcomes]
    win_rates = [o.oos.win_rate or 0.0 for o in outcomes]
    drawdowns = [o.oos.max_drawdown_pct for o in outcomes]
    total_ventanas = len(outcomes)

    resumen: dict = {
        "windows": total_ventanas,
        "trades": sum(o.oos.trades for o in outcomes),
        "oos_return_pct": _compuesto([o.oos.return_pct for o in outcomes]),
        "market_return_pct": _compuesto([o.oos.market_return_pct for o in outcomes]),
        "win_rate_mean": sum(win_rates) / len(win_rates) if win_rates else 0.0,
        "sharpe_mean": sum(sharpes) / len(sharpes) if sharpes else 0.0,
        "sharpe_dispersion": _desviacion(sharpes),
        "max_drawdown_worst": max(drawdowns) if drawdowns else 0.0,
        "consistency": _consistencia(sharpes),
        "beats_market_windows": sum(
            1 for o in outcomes if o.oos.return_pct > o.oos.market_return_pct
        ),
        "profitable_windows": sum(1 for s in sharpes if s > 0),
    }
    score = robustness_score(sharpes, win_rates, drawdowns)

    rechazos: list[str] = []
    if total_ventanas < spec.min_windows:
        rechazos.append(
            f"sale elegida en {total_ventanas} ventanas y el mínimo son "
            f"{spec.min_windows}"
        )
    if resumen["trades"] < spec.min_trades:
        rechazos.append(
            f"{resumen['trades']} operaciones fuera de muestra y el mínimo son "
            f"{spec.min_trades}"
        )
    if resumen["oos_return_pct"] <= 0:
        rechazos.append("el PnL compuesto fuera de muestra no es positivo")
    necesarias = math.ceil(spec.beats_market_ratio * total_ventanas)
    if necesarias and resumen["beats_market_windows"] < necesarias:
        rechazos.append(
            f"supera al mercado en {resumen['beats_market_windows']} de "
            f"{total_ventanas} ventanas y hacen falta {necesarias}"
        )

    if rechazos:
        # Un intervalo de una configuracion ya descartada no se calcula: no hay
        # muestra con la que calcularlo, y un numero al lado de una guarda que
        # ya la ha tumbado distrae de la guarda.
        return CandidateReport(
            strategy=key,
            score=score,
            verdict="descartada",
            ci95=None,
            rejections=tuple(rechazos),
            **resumen,
        )

    ci95 = block_bootstrap_ci(
        [o.oos.trade_pnls for o in outcomes], iteraciones=iteraciones, seed=seed
    )
    notas: list[str] = []
    if ci95 is None:
        veredicto: Verdict = "descartada"
        rechazos.append(
            "no hay operaciones fuera de muestra con las que sacar intervalo"
        )
    elif ci95[0] <= 0 <= ci95[1]:
        veredicto = "prometedora"
    else:
        veredicto = "sostenida"

    if veredicto == "sostenida" and spec.regimes_declared < spec.min_regimes:
        veredicto = "prometedora"
        notas.append(
            f"el techo del veredicto es «prometedora» porque hay "
            f"{spec.regimes_declared} régimen(es) de mercado declarados y hacen "
            f"falta {spec.min_regimes}: con una sola serie de precios el intervalo "
            f"acredita que el resultado no es ruido en ese tramo, no que vaya a "
            f"repetirse"
        )

    return CandidateReport(
        strategy=key,
        score=score,
        verdict=veredicto,
        ci95=ci95,
        rejections=tuple(rechazos),
        notes=tuple(notas),
        **resumen,
    )


@dataclass(frozen=True, slots=True)
class WalkForwardReport:
    """Todo lo que devuelve un walk-forward."""

    spec: WindowSpec
    windows: list[WindowOutcome]
    candidates: list[CandidateReport]
    #: Curva OOS encadenada: `equity`, `market_equity` y `drawdown_pct`.
    oos_equity: pd.DataFrame
    simulations: int
    #: Ventanas sin seleccion posible (IS sin senales o sin Sharpe). Se reporta en
    #: vez de omitirlas: un hueco es informacion, no un silencio, y sin este
    #: contador un informe con 6 ventanas de 10 seria indistinguible de uno
    #: completo.
    windows_without_selection: int


def _recortar(curva: pd.DataFrame | None, desde: pd.Timestamp, hasta: pd.Timestamp):
    """La curva del motor recortada al rango de la ventana."""
    if curva is None or curva.empty:
        return curva
    return curva[(curva.index >= desde) & (curva.index <= hasta)]


def _encadenar(curvas: Sequence[pd.Series], capital: float) -> pd.Series:
    """Encadena varias curvas rebasando cada tramo en el capital anterior.

    Sin esto, la curva conjunta de dos ventanas tendria un salto del 100% al
    return de la segunda, que no es un movimiento del mercado: es un reinicio de
    capital. El informe tiene que enseñar una sola linea, y esa linea tiene que
    ser comparable con la del mercado encadenada igual.
    """
    partes: list[pd.Series] = []
    actual = capital
    ultimo_ts: pd.Timestamp | None = None
    for serie in curvas:
        if serie is None or serie.empty:
            continue
        serie = serie.astype(float)
        # Con ventanas contiguas la vela de frontera es la ultima de una y la
        # primera de la siguiente. Encadenar las dos duplica ese timestamp, y un
        # indice con repetidos rompe dos cosas a la vez: el drawdown acumulado
        # cuenta esa fila dos veces, y la persistencia con clave
        # ``(run_id, timestamp)`` revienta con un ``UniqueViolation``. Se
        # conserva la fila **anterior**, que es la que ya encadena el capital
        # anterior, y se descarta la de la ventana nueva.
        if ultimo_ts is not None and serie.index[0] <= ultimo_ts:
            serie = serie[serie.index > ultimo_ts]
            if serie.empty:
                continue
        base = float(serie.iloc[0])
        if base <= 0:
            continue
        factor = actual / base
        partes.append(serie * factor)
        ultimo_ts = serie.index[-1]
        actual = float(serie.iloc[-1]) * factor
    if not partes:
        return pd.Series(
            dtype=float, index=pd.DatetimeIndex([], tz="UTC", name="timestamp")
        )
    return pd.concat(partes)


def _chain_equity(
    curvas: Sequence[pd.Series], mercados: Sequence[pd.Series], capital: float
) -> pd.DataFrame:
    """Curva OOS encadenada de la estrategia y del mercado, en un solo frame.

    Las dos series se rebasan por separado y con el **mismo** reparto de
    ventanas, para que sean comparables vela a vela. Encadenar solo la estrategia
    y poner el mercado al lado seria comparar dos cosas medidas sobre rangos
    distintos, que es la forma mas sutil de fabricar una ventaja que no existe.

    Las dos curvas tienen los mismos indices porque salen de las mismas
    ventanas; si alguna no cuadra, se reindexa la del mercado a la de la
    estrategia y se deja un hueco en vez de inventar un punto.
    """
    # ``curvas`` llegan como frames completos de la simulacion y ``mercados``
    # como series sueltas; aqui se reducen las dos a series de equity, que es lo
    # unico que se encadena. Dejar frames donde se esperan series daria una
    # ``Series`` dentro de un ``float()``, que es un fallo de tipos y no de
    # logica, y por eso se normaliza en un solo sitio.
    estrategia = _encadenar(
        [curva["equity"] if curva is not None else None for curva in curvas], capital
    )
    mercado = _encadenar(mercados, capital)
    if estrategia.empty:
        return pd.DataFrame(
            columns=["equity", "market_equity", "drawdown_pct"],
            index=pd.DatetimeIndex([], tz="UTC", name="timestamp"),
        )
    mercado = mercado.reindex(estrategia.index)
    maximo = estrategia.cummax()
    return estrategia.to_frame("equity").assign(
        market_equity=mercado,
        drawdown_pct=((maximo - estrategia) / maximo * 100),
    )


def run_walk_forward(
    candles: pd.DataFrame,
    signals: pd.DataFrame,
    base: StrategyConfig,
    grid: SweepGrid,
    spec: WindowSpec,
    minutos_por_vela: int | None = None,
    on_progress: Callable[[int, int, str], bool | None] | None = None,
    iteraciones: int = BOOTSTRAP_ITERATIONS,
    seed: int = BOOTSTRAP_SEED,
) -> WalkForwardReport:
    """Ejecuta el walk-forward completo y devuelve el informe.

    Por cada ventana: barre la rejilla en el IS, elige por Sharpe, aplica esa
    eleccion al OOS y mide. Al final agrega por configuracion y dicta veredicto.

    ``on_progress`` se llama con ``(ventana_hecha, ventanas_totales, etiqueta)`` y
    reporta por **ventana**, no por simulacion: una simulacion dura 60 ms y no
    produce ningun dato que contar, asi que una barra que sube 1.200 veces en un
    minuto informa de lo mismo que una que sube 10.

    Si devuelve ``False``, el motor levanta ``WalkForwardCancelled`` en la
    frontera de la ventana. Se corta a proposito aqui y no dentro de la
    simulacion, que es donde un corte dejaria operaciones a medias.
    """
    if candles.empty:
        raise WalkForwardError("No hay velas en el rango")
    if minutos_por_vela is None:
        minutos_por_vela = 60
    if minutos_por_vela < 1:
        raise WalkForwardError("minutos_por_vela debe ser >= 1")

    assert_continuity(candles, minutos_por_vela)
    ventanas = build_windows(candles.index[0], candles.index[-1], spec)
    assert_isolation(ventanas)
    combinaciones = _combinaciones_validas(grid)
    if combinaciones * len(ventanas) > spec.max_simulations:
        raise WalkForwardError(
            f"son {combinaciones * len(ventanas)} simulaciones y el tope es "
            f"{spec.max_simulations}: reduce la rejilla o el número de ventanas"
        )

    outcomes: list[WindowOutcome] = []
    curvas: list[pd.DataFrame | None] = []
    mercados: list[pd.Series] = []
    sin_seleccion = 0
    capital = base.initial_capital

    for ventana in ventanas:
        elegido = select_in_sample(
            candles, signals, base, grid, ventana, minutos_por_vela
        )
        if elegido is None:
            sin_seleccion += 1
            _progreso(
                on_progress,
                len(outcomes) + sin_seleccion,
                len(ventanas),
                "sin señales en el IS",
            )
            continue
        key, is_sharpe = elegido
        metricas, curva = evaluate_window(
            candles,
            signals,
            key.apply(base),
            ventana.oos_from,
            ventana.oos_to,
            minutos_por_vela,
        )
        outcomes.append(
            WindowOutcome(
                window=ventana, selected=key, is_sharpe=is_sharpe, oos=metricas
            )
        )
        # La curva se recorta al rango OOS de la ventana **antes** de
        # encadenarla. El motor devuelve la curva con la cola de `max_hold` para
        # poder resolver la ultima operacion, y esa cola se solapa con la ventana
        # siguiente: encadenarla sin recortar duplicaria timestamps y el drawdown
        # de la curva conjunta saldria mal calculado. La simulacion necesita la
        # cola; el grafico no, y son cosas distintas.
        curvas.append(_recortar(curva, ventana.oos_from, ventana.oos_to))
        # Sin operador walrus aqui a proposito: una Serie de pandas en contexto
        # booleano lanza ValueError ("truth value is ambiguous"), y la condicion
        # correcta es "no es None", no "es verdadera".
        curva_mercado = _market_curve(
            candles, ventana.oos_from, ventana.oos_to, capital
        )
        if curva_mercado is not None:
            mercados.append(curva_mercado)
        _progreso(on_progress, ventana.index, len(ventanas), key.label())

    candidatos = _build_candidates(outcomes, spec, iteraciones, seed)
    return WalkForwardReport(
        spec=spec,
        windows=outcomes,
        candidates=candidatos,
        oos_equity=_chain_equity(curvas, mercados, capital),
        simulations=_combinaciones_validas(grid) * len(ventanas),
        windows_without_selection=sin_seleccion,
    )


def _progreso(
    on_progress: Callable[[int, int, str], bool | None] | None,
    hechas: int,
    total: int,
    etiqueta: str,
) -> None:
    """Notifica el avance y aborta si quien escucha dice que pare.

    El corte va **despues** de la ventana, nunca en medio: una ventana que se
    queda a medias deja operaciones sin resolver y una curva sin cerrar, y medio
    informe es peor que ninguno. Cancelar entre ventanas cuesta como mucho una
    ventana entera de trabajo.
    """
    if on_progress is None:
        return
    if on_progress(hechas, total, etiqueta) is False:
        raise WalkForwardCancelled(f"Cancelado tras la ventana {hechas} de {total}")


def _celdas_validas(grid: SweepGrid):
    """Las celdas de la rejilla que producen una estrategia simulable.

    Una celda con TP y SL a ``None`` no se puede simular y ``sweep`` la salta, asi
    que contarla inflaria el numero de simulaciones que se anuncia y se paga.

    Es la **unica** definicion de esa regla en el modulo, y la usan tanto
    ``_combinaciones_validas`` (que cuenta) como ``base_strategy`` (que toma la
    primera). Tenerla en dos sitios es como se cuela un desajuste silencioso: uno
    cuenta 18 celdas donde el otro ve 17, y el informe announce un coste que no
    es el que se paga.
    """
    for max_hold in grid.max_holds:
        for sl in grid.stop_loss_pcts:
            for tp in grid.take_profit_pcts:
                if tp is not None or sl is not None:
                    yield tp, sl, max_hold


def _combinaciones_validas(grid: SweepGrid) -> int:
    return sum(1 for _ in _celdas_validas(grid))


def base_strategy(grid: SweepGrid, initial_capital: float) -> StrategyConfig:
    """La configuracion base de un walk-forward: la **primera celda valida**.

    Existe por un motivo concreto: ``engine.StrategyConfig`` rechaza un
    ``take_profit_pct`` y un ``stop_loss_pct`` a la vez a ``None``, con razon
    (sin niveles no hay salida antes de ``max_hold``), asi que no se puede
    construir un base neutro para que la rejilla lo rellene despues.

    Los tres parametros que el walk-forward varye (TP, SL y ``max_hold``) los
    sobrescriben siempre: ``sweep`` los sustituye por los de cada celda, y la
    combinacion elegida por el IS se aplica con ``StrategyKey.apply``. Del base
    solo se usan el capital, las comisiones, la fraccion y si se permite vender.
    Aun asi se toma una celda **real** de la rejilla y no un valor inventado: si
    algun dia algo se escapara sin sobrescribir, simularia una combinacion que el
    usuario pidio, y no una arbitraria.
    """
    for tp, sl, max_hold in _celdas_validas(grid):
        return StrategyConfig(
            take_profit_pct=tp,
            stop_loss_pct=sl,
            max_hold=max_hold,
            initial_capital=initial_capital,
        )
    raise WalkForwardError(
        "La rejilla no tiene ninguna combinación simulable: todos los pares de "
        "TP y SL son null"
    )


def _market_curve(
    candles: pd.DataFrame, desde: pd.Timestamp, hasta: pd.Timestamp, capital: float
) -> pd.Series | None:
    """Curva del mercado en una ventana, encadenada con la anterior."""
    from app.modules.backtesting.analysis import buy_and_hold as _bah

    recorte = candles[(candles.index >= desde) & (candles.index <= hasta)]
    if recorte.empty:
        return None
    resultado = _bah(recorte, capital)
    if resultado.equity is None or resultado.equity.empty:
        return None
    return resultado.equity["equity"].astype(float)


def _build_candidates(
    outcomes: Sequence[WindowOutcome],
    spec: WindowSpec,
    iteraciones: int,
    seed: int,
) -> list[CandidateReport]:
    """Agrega por configuracion y ordena por veredicto y score.

    El orden de salida es primero por veredicto (sostenida, prometedora,
    descartada) y despues por score. Es una consecuencia, no una recomendacion: el
    informe no dice "usa esta", dice "estas son las que han pasado esto".
    """
    agrupado: dict[StrategyKey, list[WindowOutcome]] = {}
    for outcome in outcomes:
        agrupado.setdefault(outcome.selected, []).append(outcome)

    candidatos = [
        build_candidate(key, ventanas, spec, iteraciones=iteraciones, seed=seed)
        for key, ventanas in agrupado.items()
    ]
    orden = {"sostenida": 0, "prometedora": 1, "descartada": 2}
    return sorted(candidatos, key=lambda c: (orden[c.verdict], -c.score))


def evaluate_fixed(
    candles: pd.DataFrame,
    signals: pd.DataFrame,
    base: StrategyConfig,
    key: StrategyKey,
    spec: WindowSpec,
    minutos_por_vela: int = 60,
) -> list[WindowOutcome]:
    """Mide **una configuracion dada** en el OOS de todas las ventanas.

    No hay eleccion: no barre la rejilla y no elige nada. Es lo que responde a
    "¿como rindio *esta* configuracion en mis datos?", y tiene una segunda razon
    que es la importante: con rangos cortos salen pocas ventanas, y el numero de
    candidatas de un walk-forward esta acotado por el numero de ventanas porque
    solo puede ser candidata lo que fue elegido alguna vez. Sobre un rango de
    cuatro meses, una rejilla de dieciocho combinaciones da dos o tres
    candidatas, y el **ranking** deja de ser comprobable aunque el motor este bien.

    Evaluando la configuracion directamente, si lo es: las mismas dieciocho
    candidatos se pueden medir sobre los tres regimenes y comparar, sin depender
    de que el azar de la eleccion los haya sacado de la bolsa.
    """
    if minutos_por_vela < 1:
        raise WalkForwardError("minutos_por_vela debe ser >= 1")
    ventanas = build_windows(candles.index[0], candles.index[-1], spec)
    assert_isolation(ventanas)
    config = key.apply(base)
    outcomes: list[WindowOutcome] = []
    for ventana in ventanas:
        metricas, _ = evaluate_window(
            candles,
            signals,
            config,
            ventana.oos_from,
            ventana.oos_to,
            minutos_por_vela,
        )
        outcomes.append(
            WindowOutcome(
                window=ventana,
                selected=key,
                is_sharpe=float("nan"),
                oos=metricas,
            )
        )
    return outcomes


def evaluate_fixed_report(
    candles: pd.DataFrame,
    signals: pd.DataFrame,
    base: StrategyConfig,
    key: StrategyKey,
    spec: WindowSpec,
    minutos_por_vela: int = 60,
    iteraciones: int = BOOTSTRAP_ITERATIONS,
    seed: int = BOOTSTRAP_SEED,
) -> CandidateReport:
    """Informe de una configuracion fija, con el mismo veredicto que una candidata."""
    return build_candidate(
        key,
        evaluate_fixed(candles, signals, base, key, spec, minutos_por_vela),
        spec,
        iteraciones=iteraciones,
        seed=seed,
    )
