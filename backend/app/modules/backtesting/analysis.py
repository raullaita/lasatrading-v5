"""Analisis y calibracion de una estrategia a partir de MAE/MFE.

Modulo **puro**: no importa SQLAlchemy ni FastAPI, solo ``numpy`` y el motor.
Toda la base de datos se queda en ``service`` y la mayor parte de las pruebas
corren sin PostgreSQL, que es lo que hace falta para poder comprobar un
percentil contra un numero calculado a mano.

Las tres trampas de este modulo, y por que estan resueltas como estan:

* **Unidades.** ``mae`` y ``mfe`` se guardan en **fraccion** (``0.012`` es un
  1,2%), mientras que ``take_profit_pct`` y ``return_pct`` van en **porcentaje**
  (``1.2``). Mezclarlas daria un TP mil veces mas pequeno que el recorrido real
  de la operacion. Por eso aqui se trabaja **siempre en porcentaje** y la
  conversion ocurre una unica vez, en ``service``, al leer la columna.

* **Signo.** El motor define ``mae <= 0`` y ``mfe >= 0`` tanto en largo como en
  corto (``engine.run_backtest``), asi que la excursion adversa se lleva por su
  valor absoluto y la favorable por su valor natural.

* **Recorte, y esta es la importante.** ``mfe`` y ``mae`` se calculan sobre las
  velas *que la posicion estuvo abierta*, y quien decide cuanto tiempo estuvo
  abierta es el propio take profit y el propio stop loss del run. Una ganadora
  que sale por TP tiene ``mfe`` clavado en el TP: por muy arriba que mire su
  percentil, jamas dira si el mercado habria dado mas. Lo mismo con las
  perdedoras y el stop. Un percentil de estos dos numeros **no es una medida de
  oportunidades**, es una medida de los limites que se puesto uno mismo.

  De ahi la division en dos poblaciones: las operaciones **contadas por el
  resultado** (con las que se describe lo que ocurrio) y las **libres** (las que
  salieron por ``timeout`` o ``end_of_data``, que neither el TP ni el SL
  cortaron, y por tanto sionson las unicas que informan de donde habria llegado
  el precio). Las sugerencias seSacan de las libres, y aun asi llevan su
  advertencia escrita, porque ese grupo tiene un sesgo de supervivencia
  inevitable: una operacion que se activate pronto se habria convertido en
  perdedora por stop loss y no estaria aqui. Por eso el analisis dice
  "aproximadamente" y el sweep es la unica forma de medir de verdad.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace

import numpy as np
import pandas as pd

from app.modules.backtesting.engine import (
    END_OF_DATA,
    STOP_LOSS,
    TAKE_PROFIT,
    TIMEOUT,
    StrategyConfig,
    run_backtest,
)

#: Motivos que cuentan como resultado de la estrategia, igual que en el motor.
COUNTED_REASONS = (TAKE_PROFIT, STOP_LOSS, TIMEOUT)

#: Motivos en los que el precio se movio sin que ningun nivel lo cortara. Sus
#: MAE y MFE dicen donde estaba el mercado de verdad, no donde se puso el TP.
FREE_REASONS = (TIMEOUT, END_OF_DATA)

#: Percentiles que se calculan y se envian. El 10 y el 25 no los pidio nadie,
#: pero sin ellos no hay caja de un boxplot, y una caja de percentiles del 50
#: al 90 no es una caja: es dos lineas sueltas.
PERCENTILES: tuple[int, ...] = (10, 25, 50, 75, 90)

#: Cajas del histograma. Doce divisiones dan una silueta legible de la
#: distribucion sin que el JSON crezca: con 30 operaciones son 12 barras de dos
#: o tres operaciones cada una, y con 2.000 operaciones la forma esta clara.
HISTOGRAM_BINS = 12

#: Por debajo de este numero de operaciones libres no se sugiere nada. Con cinco
#: operaciones el percentil 50 es la mediana de cinco numeros y cualquier
#: conclusion escrita al lado seria una categoria de error sobre ruido.
MIN_SAMPLES_FOR_SUGGESTION = 20

#: Tope de combinaciones de un sweep. Cada simulacion son milisegundos, pero
#: ``len(combos) = len(tp) * len(sl) * len(max_hold)`` y tres listas de diez dan
#: mil: un POST que se lleva un minuto sin decir nada en la barra del navegador.
MAX_SWEEP_COMBINATIONS = 120


class AnalysisError(ValueError):
    """Peticion de analisis o de sweep que no tiene sentido."""


@dataclass(frozen=True, slots=True)
class TradeSample:
    """Una operacion, reducida a lo que el analisis necesita.

    Deliberadamente no es la entidad de base de datos: es una foto plana de lo
    que sale de la consulta, para que el modulo de analisis se pueda probar
    escribiendo ocho lineas en vez de montando una base de datos.
    """

    pattern_name: str
    direction: str
    exit_reason: str
    net_pnl: float
    #: Excursion maxima a favor, en **porcentaje** y positiva.
    mfe: float | None = None
    #: Excursion maxima en contra, en **porcentaje** y negativa.
    mae: float | None = None


@dataclass(frozen=True, slots=True)
class Bucket:
    """Caja del histograma, con los bordes en porcentaje."""

    lower: float
    upper: float
    count: int


#: Tolerancia al comparar un maximo con su techo, en puntos porcentuales, para
#: que la vela que se pasa del nivel en 0,1 no cuente como "llego al techo".
CAP_TOLERANCE = 0.1


@dataclass(frozen=True, slots=True)
class ExcursionStats:
    """Distribucion de una magnitud, en percentiles y en cajas.

    ``capped_at_pct`` es el nivel del run que recorta esta poblacion: si esta a
    2,0, ningun ``mfe`` de esta poblacion puede pasar de 2,0 y el percentil 90
    no significa "el 90% llego aqui", sino "el techo es aqui". Viajar en la
    respuesta es lo que permite que la UI avise en vez de pintar una
    distribucion que parece mas ancha de lo que es.
    """

    count: int
    p10: float | None = None
    p25: float | None = None
    p50: float | None = None
    p75: float | None = None
    p90: float | None = None
    minimum: float | None = None
    maximum: float | None = None
    mean: float | None = None
    buckets: tuple[Bucket, ...] = ()
    capped_at_pct: float | None = None

    @property
    def is_capped(self) -> bool:
        """El techo de los datos coincide con el nivel que los recorta."""
        return (
            self.capped_at_pct is not None
            and self.maximum is not None
            and self.maximum >= self.capped_at_pct - CAP_TOLERANCE
        )


@dataclass(frozen=True, slots=True)
class PatternCalibration:
    """Como se comportaron las operaciones de un patron y una direccion."""

    pattern_name: str
    direction: str
    trades: int
    wins: int
    losses: int
    #: Operaciones cuyo cierre no fue decidido por ningun nivel del run.
    free_trades: int
    winner_mfe: ExcursionStats
    loser_mae: ExcursionStats
    free_mfe: ExcursionStats
    free_mae: ExcursionStats
    suggested_take_profit_pct: float | None = None
    suggested_stop_loss_pct: float | None = None
    #: Lecturas en prosa, ya redactadas para la interfaz.
    findings: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RunCalibration:
    """Analisis completo de un run, agrupado por patron y direccion.

    Ademas de los grupos lleva la **poblacion libre agregada** (``pooled_*``).
    Existe por un caso que se dio en la primera corrida real: ningun grupo
    llegaba a las 20 operaciones libres necesarias para proponer un nivel, pero
    el run entero si las tenia. Decirle al usuario "no hay propuesta" cuando el
    run tiene 23 operaciones que no?to el TP ni el SL es dejarle la respuesta en
    la mesa.

    Esa propuesta agregada es una media de distintos patrones, asi que viaja
    siempre junto a su numero de operaciones libres y al aviso de que puede no
    sentarle bien a ninguno: el pooleda por debajo del patron, nunca en su
    lugar.
    """

    trades: int
    groups: tuple[PatternCalibration, ...]
    free_trades: int = 0
    pooled_mfe: ExcursionStats = field(default_factory=lambda: ExcursionStats(count=0))
    pooled_mae: ExcursionStats = field(default_factory=lambda: ExcursionStats(count=0))
    suggested_take_profit_pct: float | None = None
    suggested_stop_loss_pct: float | None = None
    findings: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SweepGrid:
    """Rejilla a simular. Los ``None`` significan "sin ese nivel"."""

    take_profit_pcts: tuple[float | None, ...]
    stop_loss_pcts: tuple[float | None, ...]
    max_holds: tuple[int, ...]

    def combinations(self) -> int:
        return (
            len(self.take_profit_pcts) * len(self.stop_loss_pcts) * len(self.max_holds)
        )

    def configs(self, base: StrategyConfig) -> list[StrategyConfig]:
        """Configuraciones de la rejilla, de forma estatica y determinista.

        El orden es el de las tres listas anidadas y no "el mejor primero": el
        orden final lo decide el PnL en ``sweep``, y ordenar aqui seria tirar la
        comparacion.
        """
        if not self.take_profit_pcts or not self.stop_loss_pcts or not self.max_holds:
            raise AnalysisError("La rejilla necesita al menos un valor en cada eje")
        combos = self.combinations()
        if combos > MAX_SWEEP_COMBINATIONS:
            raise AnalysisError(
                f"La rejilla tiene {combos} combinaciones y el tope es "
                f"{MAX_SWEEP_COMBINATIONS}: reduce los valores de TP, SL o max_hold"
            )
        out: list[StrategyConfig] = []
        for max_hold in self.max_holds:
            for stop_loss in self.stop_loss_pcts:
                for take_profit in self.take_profit_pcts:
                    if take_profit is None and stop_loss is None:
                        # El motor lo rechaza, y con razon: sin niveles no hay
                        # salida antes de ``max_hold``. Aqui se salta la celda en
                        # vez de abortar las otras, que si son validas.
                        continue
                    try:
                        out.append(
                            replace(
                                base,
                                take_profit_pct=take_profit,
                                stop_loss_pct=stop_loss,
                                max_hold=max_hold,
                            )
                        )
                    except ValueError:
                        # Un nivel no positivo en la rejilla no invalida la
                        # simulacion entera: se cae esa celda.
                        continue
        if not out:
            raise AnalysisError(
                "Ninguna combinacion de la rejilla produce una estrategia valida"
            )
        return out


@dataclass(frozen=True, slots=True)
class SweepPoint:
    """Resultado de una simulacion de la rejilla. Nada de esto se persiste."""

    take_profit_pct: float | None
    stop_loss_pct: float | None
    max_hold: int
    total_trades: int
    skipped_signals: int
    net_pnl: float
    total_return_pct: float
    win_rate: float | None
    profit_factor: float | None
    max_drawdown_pct: float
    sharpe_ratio: float | None
    avg_bars_held: float | None
    exits: dict[str, int] = field(default_factory=dict)
    #: ``True`` si esta combinacion es la del propio run, para que la UI la
    #: resalte y el usuario vea cuanto mejora (o empeora) respecto a lo que
    #: tenia guardado.
    is_baseline: bool = False


# ---------------------------------------------------------------------------
# Percentiles
# ---------------------------------------------------------------------------
def _rounded(value: float, digits: int = 4) -> float:
    """Porcentaje redondeado para el JSON.

    Sin redondear, ``0.1 + 0.2`` encoma flotante daria ``0.30000000000000004`` en
    la tabla, y una tabla de calibracion llena de decimales de mas es ruido que
    invita a desconfiar del numero de al lado. Cuatro decimales de porcentaje
    son cuatro centesimas de punto: muy por debajo del ruido de cuatro bps de
    comision.
    """
    return round(float(value), digits)


def summarize(
    values: Sequence[float], capped_at_pct: float | None = None
) -> ExcursionStats:
    """Percentiles e histograma de una poblacion, en porcentaje.

    El metodo de interpolacion es el **lineal** de ``numpy`` (el que usa por
    defecto): con 4 observaciones, ``p50`` es la media de la segunda y la
    tercera. Se deja fijo y documentado a proposito, porque cambiarlo despues
    moveria los numeros de un informe a otro sin que nadie note el cambio.

    Poblacion vacia o de un solo elemento: no inventa percentiles. Con un solo
    dato todos los percentiles valen ese dato, lo cual es cierto pero no
    informativo; aun asi se devuelven para que el que llama decida, y la UI
    puede avisar de la muestra pequeña.
    """
    limpio = [
        float(value) for value in values if value is not None and np.isfinite(value)
    ]
    if not limpio:
        return ExcursionStats(count=0, capped_at_pct=capped_at_pct)

    data = np.asarray(limpio, dtype=float)
    calculados = np.percentile(data, PERCENTILES, method="linear")
    by_percentile = dict(zip(PERCENTILES, calculados, strict=True))
    return ExcursionStats(
        count=int(data.size),
        p10=_rounded(by_percentile[10]),
        p25=_rounded(by_percentile[25]),
        p50=_rounded(by_percentile[50]),
        p75=_rounded(by_percentile[75]),
        p90=_rounded(by_percentile[90]),
        minimum=_rounded(data.min()),
        maximum=_rounded(data.max()),
        mean=_rounded(data.mean()),
        buckets=histogram(data),
        capped_at_pct=capped_at_pct,
    )


def histogram(data: np.ndarray, bins: int = HISTOGRAM_BINS) -> tuple[Bucket, ...]:
    """Cajas de anchura constante entre el minimo y el maximo.

    ``np.histogram`` sobre bordes calculados a mano y no ``np.histogram`` porque
    este devuelve los bordes en la salida y aqui lo que interesa es el JSON:
    el frontend necesita los limites de cada barra para pintarla, no solo el
    conteo. Con un solo valor todos los bordes coinciden y se devuelve una sola
    caja, no doce vacias.
    """
    if data.size == 0:
        return ()
    if data.size == 1:
        return (
            Bucket(
                lower=_rounded(float(data[0])), upper=_rounded(float(data[0])), count=1
            ),
        )

    minimo, maximo = float(data.min()), float(data.max())
    if maximo <= minimo:
        # Todos los valores iguales (o casi): repartir el rango en doce partes
        # daria anchura cero y una division por cero. Una caja delgada es la
        # lectura correcta de "no hay dispersion".
        return (
            Bucket(
                lower=_rounded(minimo), upper=_rounded(maximo), count=int(data.size)
            ),
        )

    edges = np.linspace(minimo, maximo, bins + 1)
    counts, _ = np.histogram(data, bins=edges)
    return tuple(
        Bucket(
            lower=_rounded(float(edges[position])),
            upper=_rounded(float(edges[position + 1])),
            count=int(counts[position]),
        )
        for position in range(bins)
        if counts[position] > 0
    )


# ---------------------------------------------------------------------------
# Analisis por patron
# ---------------------------------------------------------------------------
def _group_key(trade: TradeSample) -> tuple[str, str]:
    return trade.pattern_name, trade.direction


def calibrate_pattern(
    samples: Sequence[TradeSample],
    take_profit_pct: float | None,
    stop_loss_pct: float | None,
) -> PatternCalibration:
    """Calibra un grupo de operaciones del mismo patron y direccion.

    ``take_profit_pct`` y ``stop_loss_pct`` son los del run y no aparecen en las
    operaciones: son los niveles con los que se simulo, y hacen falta para
    saber que parte de cada excursion la decidio el usuario.
    """
    if not samples:
        raise AnalysisError("Un grupo sin operaciones no se calibra")

    winners = [t for t in samples if t.net_pnl > 0]
    losers = [t for t in samples if t.net_pnl < 0]
    libres = [t for t in samples if t.exit_reason in FREE_REASONS]

    # El techo de cada poblacion: el TP recorta a las ganadoras y el SL a las
    # perdedoras. Se pasa el nivel del run, no el maximo observado, para que el
    # aviso salga tambien cuando el techo todavia no se ha tocado.
    winner_mfe = summarize(
        [t.mfe for t in winners if t.mfe is not None], take_profit_pct
    )
    loser_mae = summarize(
        [abs(t.mae) for t in losers if t.mae is not None], stop_loss_pct
    )
    free_mfe = summarize([t.mfe for t in libres if t.mfe is not None])
    free_mae = summarize([abs(t.mae) for t in libres if t.mae is not None])

    pattern_name, direction = _group_key(samples[0])
    tp_sugerido = suggest_take_profit(free_mfe, take_profit_pct)
    # El stop no se propone desde los percentiles, y no por prudencia sino
    # porque la poblacion libre esta sesgada justo en la direccion equivocada:
    # son las operaciones que **no** tocaron el stop, asi que su MAE tiende a
    # cero por construccion y cualquier percentil suyo sale por debajo del
    # nivel que ya se usa. Proponerlo seria apuntar a apretar mas.
    # El barrido de parametros es quien mide el efecto de verdad.

    return PatternCalibration(
        pattern_name=pattern_name,
        direction=direction,
        trades=len(samples),
        wins=len(winners),
        losses=len(losers),
        free_trades=len(libres),
        winner_mfe=winner_mfe,
        loser_mae=loser_mae,
        free_mfe=free_mfe,
        free_mae=free_mae,
        suggested_take_profit_pct=tp_sugerido,
        suggested_stop_loss_pct=None,
        findings=tuple(_findings(winner_mfe, loser_mae, free_mfe, free_mae, direction)),
        warnings=tuple(
            _warnings(
                len(libres), winner_mfe, loser_mae, take_profit_pct, stop_loss_pct
            )
        ),
    )


def suggest_take_profit(
    free_mfe: ExcursionStats, current_take_profit_pct: float | None
) -> float | None:
    """TP teorico a partir de donde llego el precio sin que nada lo cortara.

    Se usa la mediana y no un percentil alto a proposito: un TP en el percentil
    90 solo lo tocaria una de cada diez operaciones, asi que se estaria
    calibrando el motor para el mejor caso. La mediana es "la mitad de las
    operaciones libres habria llegado aqui", que es un objetivo que se puede
    cumplir o no y se puede medir en el siguiente run.
    """
    if free_mfe.count < MIN_SAMPLES_FOR_SUGGESTION or free_mfe.p50 is None:
        return None
    sugerido = round(free_mfe.p50, 2)
    if sugerido <= 0:
        return None
    if (
        current_take_profit_pct is not None
        and abs(sugerido - current_take_profit_pct) < 0.05
    ):
        # A +-0,05 puntos del TP actual la sugerencia es ruido de redondeo y
        # haria que el usuario "cambie" algo que no ha cambiado.
        return None
    return sugerido


def stop_loss_overshoot(
    loser_mae: ExcursionStats, current_stop_loss_pct: float | None
) -> tuple[float, float] | None:
    """Cuanto se lleva la mecha por encima del stop configurado.

    Devuelve ``(puntos, proporcion)``: los puntos porcentuales de mas que toma la
    vela que activa el stop, y esa misma cantidad dividida por el stop. Es el
    unico dato sobre el nivel del stop que **si** se puede leer de la tabla, y
    sale de la poblacion equivocada para lo que se suele buscar: las perdedoras.

    Un SL al 1,00% cuya mediana de MAE es del 1,19% no es un stop al 1%: es un
    stop al 1,19% que ademas se recalienta cada vez que hay mecha. El riesgo real
    por operacion es, por tanto, mayor que el configurado. Se calcula con la
    mediana y no con la media porque un par de operaciones con una mecha del 8%
    no debe decidir el numero que se ensena al usuario.
    """
    if current_stop_loss_pct is None or current_stop_loss_pct <= 0:
        return None
    if loser_mae.count == 0 or loser_mae.p50 is None:
        return None
    if loser_mae.p50 <= current_stop_loss_pct:
        # Sin mecha apreciable: el stop sale por el nivel, no por el extremo de
        # la vela, y no hay nada que decir.
        return None
    puntos = loser_mae.p50 - current_stop_loss_pct
    return puntos, puntos / current_stop_loss_pct


def _findings(
    winner_mfe: ExcursionStats,
    loser_mae: ExcursionStats,
    free_mfe: ExcursionStats,
    free_mae: ExcursionStats,
    direction: str,
) -> Iterable[str]:
    """Lecturas en prosa, derivadas de los numeros, sin adivinar nada.

    Cada frase sale de una comparacion concreta que el usuario puede rehacer con
    los mismos datos. No se emite ninguna cuando la muestra o el dato no dan
    para afirmarlo: una recomendacion sin evidencia es peor que no tenerla.
    """
    ganadoras = winner_mfe.count
    perdedoras = loser_mae.count
    if ganadoras and winner_mfe.p50 is not None and winner_mfe.p90 is not None:
        yield (
            f"En {ganadoras} ganadoras, la mitad llega a +{winner_mfe.p50:.2f}% a "
            f"favor como maximo y el 10% supera +{winner_mfe.p90:.2f}%"
        )
    if perdedoras and loser_mae.p50 is not None and loser_mae.p90 is not None:
        yield (
            f"En {perdedoras} perdedoras, la mitad se fue {loser_mae.p50:.2f}% en "
            f"contra antes de cerrarse, y el 10% llego a {loser_mae.p90:.2f}%"
        )
    libres = free_mfe.count
    if libres and free_mfe.p50 is not None and free_mae.p75 is not None:
        yield (
            f"En las {libres} operaciones que ningún nivel cortó, el precio llegó "
            f"hasta {free_mfe.p50:.2f}% a favor y se fue hasta {free_mae.p75:.2f}% "
            f"en contra"
        )
    recorrido = (free_mfe.p50 or 0) + (free_mae.p75 or 0)
    if libres and free_mae.count and recorrido > 0:
        yield (
            f"El recorrido típico de una operación sin recortes es de "
            f"{recorrido:.2f} puntos: con un TP/SL que sumen menos que eso, la "
            f"comisión se come la operación antes de que llegue a destino"
        )


def _warnings(
    free_count: int,
    winner_mfe: ExcursionStats,
    loser_mae: ExcursionStats,
    take_profit_pct: float | None,
    stop_loss_pct: float | None,
) -> Iterable[str]:
    """Avisos sobre el recorte y el tamaño de la muestra.

    Sin estos avisos los percentiles de las ganadoras y las perdedoras se leen
    como oportunidades de mercado y son ceilings: los puso el propio run.
    """
    if free_count < MIN_SAMPLES_FOR_SUGGESTION:
        yield (
            f"Solo {free_count} operaciones sin recortes: por debajo de "
            f"{MIN_SAMPLES_FOR_SUGGESTION} no se propone ningún nivel, porque el "
            f"percentil sería la mediana de muy pocos números"
        )
    if winner_mfe.count and take_profit_pct is not None:
        yield (
            f"El recorrido favorable de las ganadoras no puede pasar de "
            f"{take_profit_pct:.2f}%, que es el take profit del run: por encima de ese "
            f"nivel no se puede saber qué habría pasado"
        )
    if loser_mae.count and stop_loss_pct is not None:
        yield (
            f"La excursión en contra no puede pasar de {stop_loss_pct:.2f}%, que es el "
            f"stop loss del run: el percentil de las perdedoras dice dónde mueren, no "
            f"cuánto habrían aguantado"
        )
    mecha = stop_loss_overshoot(loser_mae, stop_loss_pct)
    if mecha is not None:
        puntos, proporcion = mecha
        yield (
            f"Las perdedoras mueren en {loser_mae.p50:.2f}% con un stop configurado en "
            f"{stop_loss_pct:.2f}%: la mecha de la vela que lo activa se lleva "
            f"{puntos:.2f} puntos de mas, un {proporcion * 100:.0f}% sobre el nivel "
            f"configurado. El riesgo real por operación es mayor que el que pide la "
            f"estrategia"
        )
    if winner_mfe.count and loser_mae.count:
        mala = loser_mae.p50
        buena = winner_mfe.p50
        if mala is not None and buena is not None and mala >= buena:
            yield (
                f"Las perdedoras se van tan lejos como llegan las ganadoras "
                f"({mala:.2f}% frente a +{buena:.2f}%): con comisión de por medio, "
                f"la estrategia necesita acertar más de la mitad para no perder"
            )


def calibrate_run(
    samples: Sequence[TradeSample],
    take_profit_pct: float | None,
    stop_loss_pct: float | None,
) -> RunCalibration:
    """Calibra el run completo, agrupado por patron y direccion.

    La propuesta global sale de la **poblacion libre agregada** del run, no de
    una media de las propuestas por grupo. La razon es lo que enseno la primera
    corrida real: con TP al 2% y SL al 1% casi todas las operaciones las decide
    un nivel, y los grupos se quedan con cinco o diez operaciones libres cada
    uno, muy por debajo del minimo para proponer nada. Ponderando propuestas que
    no existen, el resultado es "no hay propuesta" con veintitres operaciones sin
    usar. Agregando primero y proponiendo despues, el run entero si responde, y
    el aviso de heterogeneidad sigue ahi para que no se lea como una verdad
    para cada patron.
    """
    if not samples:
        return RunCalibration(trades=0, groups=())

    grouped: dict[tuple[str, str], list[TradeSample]] = {}
    for sample in samples:
        grouped.setdefault(_group_key(sample), []).append(sample)

    groups = tuple(
        calibrate_pattern(group, take_profit_pct, stop_loss_pct)
        for group in grouped.values()
    )
    ordenados = sorted(groups, key=lambda g: (g.pattern_name, g.direction))

    libres = [s for s in samples if s.exit_reason in FREE_REASONS]
    pooled_mfe = summarize([s.mfe for s in libres if s.mfe is not None])
    pooled_mae = summarize([abs(s.mae) for s in libres if s.mae is not None])
    tp_global = suggest_take_profit(pooled_mfe, take_profit_pct)

    return RunCalibration(
        trades=len(samples),
        groups=ordenados,
        free_trades=len(libres),
        pooled_mfe=pooled_mfe,
        pooled_mae=pooled_mae,
        suggested_take_profit_pct=tp_global,
        suggested_stop_loss_pct=None,
        findings=tuple(_run_findings(ordenados, tp_global, stop_loss_pct, len(libres))),
        warnings=tuple(_run_warnings(ordenados, len(libres))),
    )


def _run_findings(
    groups: Sequence[PatternCalibration],
    tp_global: float | None,
    stop_loss_pct: float | None,
    free_total: int,
) -> Iterable[str]:
    if tp_global is not None:
        yield (
            f"En las {free_total} operaciones que ningún nivel cortó, un take "
            f"profit alrededor de {tp_global:.2f}% es el que alcanza la mitad de "
            f"las veces"
        )
    if stop_loss_pct is not None:
        yield (
            "El nivel del stop loss no se puede calibrar con percentiles: toda la "
            "excursion adversa de la tabla esta recortada por el propio stop, y las "
            "unidas sin recortar son las que sobrevivieron porque no lo tocaron. El "
            "barrido de parametros es la unica forma de medirlo"
        )
    if groups:
        mejor = min(groups, key=lambda g: (-_group_net(g), g.pattern_name))
        peor = max(groups, key=lambda g: (-_group_net(g), g.pattern_name))
        yield (
            f"Peor grupo: {peor.pattern_name} {peor.direction}, {peor.trades} "
            f"operaciones y {peor.losses} perdidas. Mejor grupo: {mejor.pattern_name} "
            f"{mejor.direction}, {mejor.trades} operaciones y {mejor.losses} perdidas"
        )
    sin_sugerencia = [g for g in groups if g.suggested_take_profit_pct is None]
    if sin_sugerencia and tp_global is not None:
        nombres = ", ".join(sorted({g.pattern_name for g in sin_sugerencia})[:3])
        yield (
            f"Sin propuesta de TP propia por muestra pequeña: {nombres}. El valor "
            f"global sale de las {free_total} operaciones libres del run, no de "
            f"una media de los grupos"
        )


def _group_net(group: PatternCalibration) -> float:
    """PnL aproximado del grupo, a partir de acierto y excursion.

    No es el PnL real (eso lo trae ``/summary``): es un orden de magnitud para
    nombrar al mejor y al peor grupo sin tener el dinero delante, y se calcula
    con la misma idea que la estrategia: aciertos por su recorrido, fallos por
    el suyo.
    """
    if not group.trades:
        return 0.0
    ganadoras = (group.winner_mfe.p50 or 0) * group.wins
    perdedoras = (group.loser_mae.p50 or 0) * group.losses
    return ganadoras - perdedoras


def _run_warnings(
    groups: Sequence[PatternCalibration], free_total: int
) -> Iterable[str]:
    if free_total == 0:
        yield (
            "Ninguna operación se cerró por tiempo límite: el take profit o el "
            "stop loss decidieron todas. Los percentiles observables están "
            "recortados por esos niveles, así que la calibración real solo se "
            "puede obtener con el barrido de parámetros"
        )
    if len(groups) > 1:
        yield (
            f"{len(groups)} combinaciones de patrón y dirección: un único TP y SL "
            f"pueden ser una media que no le venga bien a ninguno"
        )


# ---------------------------------------------------------------------------
# Barrido de parametros
# ---------------------------------------------------------------------------
def sweep(
    candles: pd.DataFrame,
    signals: pd.DataFrame,
    base: StrategyConfig,
    grid: SweepGrid,
) -> tuple[SweepPoint, ...]:
    """Simula la rejilla completa en memoria y devuelve una tabla comparativa.

    No abre sesion de base de datos, no escribe y no encola nada: es el motor
    puro, invocado N veces. Por eso el sweep se puede repetir tantas veces como
    haga falta y no deja rastro: una calibracion no es un experimento con
    registro, es una pregunta.

    El resultado viene ordenado por PnL neto descendente y, a igualdad de PnL,
    por el menor take profit: entre dos combinaciones que ganan lo mismo, la que
    cierra antes es la que tiene menos riesgo de que se lo lleven. La combinacion
    del propio run queda marcada con ``is_baseline`` para poder compararla.
    """
    puntos: list[SweepPoint] = []
    for config in grid.configs(base):
        result = run_backtest(candles, signals, config)
        metrics = result.metrics
        exits: dict[str, int] = {}
        for trade in result.trades:
            reason = trade.exit_reason or END_OF_DATA
            exits[reason] = exits.get(reason, 0) + 1
        puntos.append(
            SweepPoint(
                take_profit_pct=config.take_profit_pct,
                stop_loss_pct=config.stop_loss_pct,
                max_hold=config.max_hold,
                total_trades=int(metrics.get("total_trades") or 0),
                skipped_signals=int(result.skipped_signals),
                net_pnl=_rounded(metrics.get("net_pnl") or 0.0, 6),
                total_return_pct=_rounded(metrics.get("total_return_pct") or 0.0),
                win_rate=_rounded(metrics["win_rate"], 6)
                if metrics.get("win_rate") is not None
                else None,
                profit_factor=_rounded(metrics["profit_factor"], 6)
                if metrics.get("profit_factor") is not None
                else None,
                max_drawdown_pct=_rounded(metrics.get("max_drawdown_pct") or 0.0),
                sharpe_ratio=_rounded(metrics["sharpe_ratio"], 6)
                if metrics.get("sharpe_ratio") is not None
                else None,
                avg_bars_held=_rounded(metrics["avg_bars_held"], 4)
                if metrics.get("avg_bars_held") is not None
                else None,
                exits=exits,
                is_baseline=(
                    config.take_profit_pct == base.take_profit_pct
                    and config.stop_loss_pct == base.stop_loss_pct
                    and config.max_hold == base.max_hold
                ),
            )
        )
    return tuple(
        sorted(
            puntos,
            key=lambda p: (
                -p.net_pnl,
                p.take_profit_pct if p.take_profit_pct is not None else float("inf"),
                p.stop_loss_pct if p.stop_loss_pct is not None else float("inf"),
                p.max_hold,
            ),
        )
    )
