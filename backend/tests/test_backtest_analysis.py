"""Tests del analisis y el barrido de parametros.

Dos bloques con propositos distintos:

1. **Tests puros** (percentiles, histograma, sugerencias, rejilla): no tocan
   PostgreSQL ni el motor de verdad, asi que se puede comprobar un percentil
   contra un numero calculado a mano. Es lo que hace falta, porque un
   ``percentile_cont`` mal interpretado tambien devuelve un numero: lo que hay
   que fijar es **que** percentil y con que convencion.

2. **Tests de servicio** (analisis de un run real, barrido sin escritura): si
   necesitan base de datos, se saltan cuando no la hay, como el resto del
   modulo.

El numero que se repite en los tests es ``2,0``: el take profit por defecto. Es
el techo que recorta a las ganadoras, y casi todos los errores de este modulo
son de confundir ese techo con una oportunidad de mercado.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from app.modules.backtesting.analysis import (
    MAX_SWEEP_COMBINATIONS,
    MIN_SAMPLES_FOR_SUGGESTION,
    AnalysisError,
    SweepGrid,
    TradeSample,
    calibrate_pattern,
    calibrate_run,
    histogram,
    stop_loss_overshoot,
    suggest_take_profit,
    summarize,
    sweep,
)
from app.modules.backtesting.engine import (
    END_OF_DATA,
    STOP_LOSS,
    TAKE_PROFIT,
    TIMEOUT,
    StrategyConfig,
    run_backtest,
)


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def trade(
    *,
    mfe: float | None,
    mae: float | None,
    net: float,
    reason: str = TIMEOUT,
    pattern: str = "MACD_CROSS_BULLISH",
    direction: str = "long",
) -> TradeSample:
    return TradeSample(
        pattern_name=pattern,
        direction=direction,
        exit_reason=reason,
        net_pnl=net,
        mfe=mfe,
        mae=mae,
    )


def libres(
    n: int, *, mfe: float = 1.5, mae: float = -0.8, net: float | None = None
) -> list[TradeSample]:
    """``n`` operaciones sin recorte, con excursion fija y PnL derivado.

    La magnitud de la excursion adverse entra **negada**, como la guarda el
    motor, para que un test que la escriba al reves falle aqui y no en produccion.
    """
    return [
        trade(
            mfe=mfe,
            mae=mae,
            net=net if net is not None else mfe + mae,
            reason=TIMEOUT,
        )
        for _ in range(n)
    ]


# ---------------------------------------------------------------------------
# Percentiles
# ---------------------------------------------------------------------------
def test_percentiles_lineales_sobre_una_poblacion_conocida():
    """Cuatro valores, interpolacion lineal: los percentiles salen a mano.

    Con 1, 2, 3 y 4 el p50 es la media de 2 y 3 = 2,5; el p25 interpola entre
    1 y 2 = 1,25. Con el metodo "lower" daria 2 y 1, y con "midpoint" 2,5 y
    1,5: son tres respuestas distintas para los mismos datos, y por eso el
    metodo se fija explicitamente en el codigo y aqui.
    """
    stats = summarize([1.0, 2.0, 3.0, 4.0])

    assert stats.count == 4
    assert stats.p50 == 2.5
    assert stats.p25 == 1.75
    assert stats.p75 == 3.25
    assert stats.minimum == 1.0
    assert stats.maximum == 4.0
    assert stats.mean == 2.5


def test_percentiles_coinciden_con_numpy():
    datos = [0.4, 1.1, -0.3, 2.7, 0.9, 1.8, -1.2, 0.05]
    stats = summarize(datos)

    for percentil, atributo in (
        (10, "p10"),
        (25, "p25"),
        (50, "p50"),
        (75, "p75"),
        (90, "p90"),
    ):
        esperado = np.percentile(datos, percentil, method="linear")
        assert getattr(stats, atributo) == pytest.approx(esperado, abs=1e-4)


def test_poblacion_vacia_no_inventa_percentiles():
    stats = summarize([])

    assert stats.count == 0
    assert stats.p50 is None
    assert stats.maximum is None
    assert stats.buckets == ()


def test_poblacion_de_un_solo_valor():
    stats = summarize([1.75])

    assert stats.count == 1
    assert stats.p50 == 1.75
    assert stats.p10 == stats.p90 == 1.75
    assert stats.buckets[0].count == 1


def test_los_none_no_cuentan_como_cero():
    """Una excursion ausente es "no lo sé", no cero.

    Si un ``None`` se convirtiera en 0, el percentil 50 de una poblacion a la
    que le faltan la mitad de los MFE caeria artificialmente hacia cero y la
    sugerencia de TP se hundiria sin que nadie pueda explicar por que.
    """
    stats = summarize([2.0, None, 4.0, None, 6.0])

    assert stats.count == 3
    assert stats.p50 == 4.0


def test_los_nan_se_descartan():
    stats = summarize([1.0, float("nan"), 3.0, float("inf")])

    assert stats.count == 2
    assert stats.p50 == 2.0


def test_los_percentiles_van_redondeados_a_cuatro_decimales():
    stats = summarize([1.0 / 3.0, 2.0 / 3.0, 1.0])

    # Se comprueba la propiedad (como maximo cuatro decimales, porque se
    # redondeo explicitamente) y no un valor, que aqui seria una fraccion.
    for valor in (stats.p50, stats.p90, stats.mean):
        assert valor == round(valor, 4)


# ---------------------------------------------------------------------------
# Histograma
# ---------------------------------------------------------------------------
def test_el_histograma_cuenta_todas_las_observaciones():
    datos = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0])

    cajas = histogram(datos)

    assert sum(caja.count for caja in cajas) == datos.size


def test_las_cajas_estan_en_orden_y_sin_huecos_de_valor():
    datos = np.linspace(0.0, 1.0, 50)
    cajas = histogram(datos)

    assert [caja.lower for caja in cajas] == sorted(caja.lower for caja in cajas)
    for anterior, siguiente in zip(cajas, cajas[1:], strict=False):
        assert anterior.upper <= siguiente.lower


def test_histograma_de_valores_iguales_no_divide_por_cero():
    """Repartir un rango de anchura cero entre doce cajas revienta con un
    ``divide by zero`` de numpy. El caso real es un patron que siempre sale en el
    mismo punto, que no es raro en datos sinteticos."""
    cajas = histogram(np.array([2.0, 2.0, 2.0, 2.0]))

    assert len(cajas) == 1
    assert cajas[0].count == 4
    assert cajas[0].lower == cajas[0].upper == 2.0


def test_histograma_vacio():
    assert histogram(np.array([])) == ()


# ---------------------------------------------------------------------------
# Recorte: la idea central del modulo
# ---------------------------------------------------------------------------
def test_el_techo_de_las_ganadoras_es_el_take_profit_del_run():
    """El percentil 90 de las ganadoras no puede pasar del TP.

    Es el punto que hace que este modulo no sea un generador de fantasias: sin el
    techo, un p90 de 2,0% con un TP de 2,0% se lee como "el 90% de las
    ganadoras llego al 2%" y parece una llamada a subir el objetivo, cuando lo
    unico que dice es que el objetivo estaba ahi.
    """
    ganadoras = [
        trade(mfe=1.5, mae=-0.3, net=1.2, reason=TAKE_PROFIT),
        trade(mfe=2.0, mae=-0.4, net=1.6, reason=TAKE_PROFIT),
        trade(mfe=2.0, mae=-0.2, net=1.7, reason=TAKE_PROFIT),
    ]

    grupo = calibrate_pattern(ganadoras, take_profit_pct=2.0, stop_loss_pct=1.0)

    assert grupo.winner_mfe.maximum == 2.0
    assert grupo.winner_mfe.capped_at_pct == 2.0
    assert grupo.winner_mfe.is_capped is True


def test_sin_techo_alcanzado_no_se_marca_como_recortado():
    """El techo viaja siempre, pero ``is_capped`` solo se activa si los datos
    llegaron a el: si el maximo es 1,2 con un TP de 2,0, la distribucion es
    real y no hay nada que avisar."""
    ganadoras = [trade(mfe=1.2, mae=-0.3, net=0.9, reason=TAKE_PROFIT)]

    grupo = calibrate_pattern(ganadoras, take_profit_pct=2.0, stop_loss_pct=1.0)

    assert grupo.winner_mfe.capped_at_pct == 2.0
    assert grupo.winner_mfe.is_capped is False


def test_la_excursion_adversa_se_toma_en_valor_absoluto():
    """El motor guarda la MAE negativa; aqui viaja positiva, porque "se fue un
    1,2%" se lee mejor que "su MAE es -0,012" y evita que la UI tenga que
    accordarse del signo al pintar."""
    perdedoras = [
        trade(mfe=0.2, mae=-1.1, net=-0.9, reason=STOP_LOSS),
        trade(mfe=0.1, mae=-0.9, net=-0.8, reason=STOP_LOSS),
    ]

    grupo = calibrate_pattern(perdedoras, take_profit_pct=2.0, stop_loss_pct=1.0)

    assert grupo.loser_mae.p50 == 1.0
    assert grupo.loser_mae.minimum == 0.9
    assert grupo.loser_mae.maximum == 1.1


def test_las_operaciones_libres_no_llevan_techo():
    """Lo que no corto ningun nivel no lo recorta nada, y por eso es la unica
    poblacion de la que se puede sacar una propuesta."""
    grupo = calibrate_pattern(libres(30), take_profit_pct=2.0, stop_loss_pct=1.0)

    assert grupo.free_mfe.capped_at_pct is None
    assert grupo.free_mfe.is_capped is False
    assert grupo.free_trades == 30


def test_las_libres_son_las_de_timeout_y_fin_de_datos():
    mezcladas = [
        trade(mfe=2.0, mae=-1.0, net=1.0, reason=TAKE_PROFIT),
        trade(mfe=0.5, mae=-2.0, net=-1.5, reason=STOP_LOSS),
        trade(mfe=3.0, mae=-0.4, net=2.6, reason=TIMEOUT),
        trade(mfe=2.5, mae=-0.2, net=2.3, reason=END_OF_DATA),
    ]

    grupo = calibrate_pattern(mezcladas, take_profit_pct=2.0, stop_loss_pct=1.0)

    assert grupo.trades == 4
    assert grupo.wins == 3
    assert grupo.losses == 1
    assert grupo.free_trades == 2
    assert grupo.free_mfe.count == 2
    assert grupo.free_mfe.maximum == 3.0


# ---------------------------------------------------------------------------
# Sugerencias
# ---------------------------------------------------------------------------
def test_no_se_sugiere_nada_con_muestra_pequena():
    """Cinco operaciones dan un percentil que es la mediana de cinco numeros.
    Proponer un TP con esa base seria escribir una recomendacion de negocio
    sobre ruido, asi que se devuelve ``None`` y el aviso lo explica."""
    grupo = calibrate_pattern(
        libres(MIN_SAMPLES_FOR_SUGGESTION - 1),
        take_profit_pct=9.0,
        stop_loss_pct=9.0,
    )

    assert grupo.suggested_take_profit_pct is None
    assert any("sin recortes" in aviso for aviso in grupo.warnings)


def test_el_tp_sugerido_es_la_mediana_de_las_libres():
    grupo = calibrate_pattern(
        libres(40, mfe=1.25, mae=-0.75),
        take_profit_pct=5.0,
        stop_loss_pct=5.0,
    )

    assert grupo.suggested_take_profit_pct == 1.25
    assert grupo.free_mfe.p50 == 1.25


def test_el_stop_no_se_propone_desde_los_percentiles():
    """El sesgo de supervivencia, comprobado con numeros.

    Las operaciones libres son las que **no** tocaron el stop, asi que su MAE
    tiende a cero por construccion: cualquier percentil de esa poblacion sale por
    debajo del nivel que el run ya usa, y "calibrar" con el daria siempre un stop
    mas apretado.

    La primera corrida real lo mostró de la forma más cruel posible: con el
    stop al 1,00% proponía 0,83%, y el barrido de verdad dio -25,98 con 0,83%
    frente a +257,24 con 2,00%. Apretar más era justo lo contrario de lo que
    hacía falta, y el modulo no tenía forma de saberlo sin simular.
    """
    grupo = calibrate_pattern(
        libres(40, mfe=1.25, mae=-0.75), take_profit_pct=5.0, stop_loss_pct=1.0
    )

    assert grupo.suggested_stop_loss_pct is None
    assert grupo.suggested_take_profit_pct == 1.25, "el take profit si es calibrable"


def test_la_mecha_del_stop_se_avisa_con_puntos_ya_en_proporcion():
    """Lo que si se puede leer del stop: cuanto se lleva la vela por encima del
    nivel. Un stop al 1% cuya mediana de MAE es del 1,2% no es un stop al 1%."""
    perdedoras = [
        trade(mfe=0.2, mae=-1.2, net=-1.0, reason=STOP_LOSS) for _ in range(30)
    ]

    grupo = calibrate_pattern(perdedoras, take_profit_pct=2.0, stop_loss_pct=1.0)

    assert any("mecha" in aviso and "20%" in aviso for aviso in grupo.warnings)


def test_sin_mecha_no_se_avisa():
    """Si las perdedoras mueren justo en el nivel, el stop se esta cumpliendo y
    el modulo no tiene nada que añadir."""
    perdedoras = [
        trade(mfe=0.2, mae=-0.99, net=-0.8, reason=STOP_LOSS) for _ in range(30)
    ]

    grupo = calibrate_pattern(perdedoras, take_profit_pct=2.0, stop_loss_pct=1.0)

    assert not any("mecha" in aviso for aviso in grupo.warnings)


def test_la_mecha_necesita_stop_configurado():
    """Sin stop no hay mecha que medir, y el ``None`` del peticionado tiene que
    llegar hasta aqui sin reventar."""
    poblacion = summarize([1.0] * 30)
    assert stop_loss_overshoot(poblacion, current_stop_loss_pct=None) is None
    assert stop_loss_overshoot(poblacion, current_stop_loss_pct=0.0) is None
    assert stop_loss_overshoot(summarize([]), current_stop_loss_pct=1.0) is None


def test_la_mecha_devuelve_puntos_ya_en_proporcion():
    resultado = stop_loss_overshoot(summarize([1.4] * 30), current_stop_loss_pct=1.0)

    assert resultado == (pytest.approx(0.4), pytest.approx(0.4))


def test_sugerencias_aisladas_sobre_poblaciones_vacias():
    vacia = summarize([])
    assert suggest_take_profit(vacia, 2.0) is None
    assert stop_loss_overshoot(vacia, 1.0) is None


# ---------------------------------------------------------------------------
# Lecturas y avisos
# ---------------------------------------------------------------------------
def test_avisa_de_que_los_percentiles_estan_recortados():
    """Cada techo se avisa por separado, y solo si hay poblacion a la que le
    aplique: sin perdedoras no hay MAE que avisar, aunque el run tenga stop."""
    grupo = calibrate_pattern(
        [trade(mfe=2.0, mae=-0.4, net=1.5, reason=TAKE_PROFIT)] * 30,
        take_profit_pct=2.0,
        stop_loss_pct=1.0,
    )

    assert any("2.00%" in aviso for aviso in grupo.warnings)
    assert not any("stop loss del run" in aviso for aviso in grupo.warnings)

    con_perdedoras = calibrate_pattern(
        [trade(mfe=2.0, mae=-0.4, net=1.5, reason=TAKE_PROFIT)] * 30
        + [trade(mfe=0.1, mae=-1.0, net=-0.9, reason=STOP_LOSS)] * 10,
        take_profit_pct=2.0,
        stop_loss_pct=1.0,
    )

    assert any("stop loss del run" in aviso for aviso in con_perdedoras.warnings)


def test_avisa_cuando_las_perdedoras_van_mas_lejos_que_las_ganadoras():
    """Es la lectura que responde a la pregunta mas comun del modulo: si la
    excursion adversa tipica iguala a la favorable, la estrategia no tiene
    ventaja con comisiones por medio."""
    grupo = calibrate_pattern(
        [trade(mfe=1.0, mae=-0.3, net=0.6)] * 30
        + [trade(mfe=0.2, mae=-1.5, net=-1.3)] * 10,
        take_profit_pct=2.0,
        stop_loss_pct=2.0,
    )

    assert any("acertar más de la mitad" in aviso for aviso in grupo.warnings)


def test_no_avisa_del_techo_del_tp_sin_ganadoras():
    """Un grupo de solo timeouts perdedores no tiene ninguna ganadora cuyo
    recorrido esté recortado, asi que de ese techo no se dice nada. El aviso del
    stop si sale, porque las perdedoras si las recortan."""
    solo_perdedoras = [
        trade(mfe=0.4, mae=-0.9, net=-0.5, reason=TIMEOUT) for _ in range(30)
    ]
    grupo = calibrate_pattern(solo_perdedoras, take_profit_pct=2.0, stop_loss_pct=1.0)

    assert grupo.winner_mfe.count == 0
    assert not any("recorrido favorable" in aviso for aviso in grupo.warnings)
    assert any("stop loss del run" in aviso for aviso in grupo.warnings)


def test_sin_operaciones_no_hay_grupo():
    run = calibrate_run([], 2.0, 1.0)

    assert run.trades == 0
    assert run.groups == ()
    assert run.suggested_take_profit_pct is None


# ---------------------------------------------------------------------------
# Agregacion por patron
# ---------------------------------------------------------------------------
def test_agrupa_por_patron_y_direccion():
    muestras = [
        trade(mfe=1.5, mae=-0.5, net=1.0, pattern="MACD", direction="long"),
        trade(mfe=1.4, mae=-0.6, net=0.8, pattern="MACD", direction="long"),
        trade(mfe=0.3, mae=-0.9, net=-0.6, pattern="MACD", direction="short"),
        trade(mfe=2.0, mae=-0.4, net=1.6, pattern="RSI", direction="long"),
    ]

    run = calibrate_run(muestras, 2.0, 1.0)

    assert [(g.pattern_name, g.direction) for g in run.groups] == [
        ("MACD", "long"),
        ("MACD", "short"),
        ("RSI", "long"),
    ]
    assert [g.trades for g in run.groups] == [2, 1, 1]


def test_la_propuesta_global_sale_de_la_poblacion_libre_agrupada():
    """La propuesta global es el percentil de **todas** las operaciones libres
    juntas, no una media de los grupos.

    No es un detalle: la media de medias ponderada por el tamaño da un numero
    distinto al percentil del conjunto, y con poblaciones desiguales la media
    responde a los grupos pequenos con la misma fuerza que a los grandes. El
    percentil conjunto responde a la pregunta que se le hace, que es "si entro
    con estas señales, ¿cuanto lejos llega el precio en la mitad de las veces?".
    """
    muestras = [trade(mfe=1.0, mae=-0.5, net=0.5, pattern="CHICO")] * 20 + [
        trade(mfe=3.0, mae=-0.5, net=2.5, pattern="GRANDE")
    ] * 40

    run = calibrate_run(muestras, 9.0, 9.0)

    # 20 valores a 1,0 y 40 a 3,0: la mediana de los 60 es 3,0, porque el
    # grupo grande ocupa mas de la mitad de la poblacion.
    assert run.free_trades == 60
    assert run.suggested_take_profit_pct == 3.0
    assert run.pooled_mfe.count == 60


def test_la_propuesta_global_sale_aunque_ningun_grupo_llegue_al_minimo():
    """El caso que dio la primera corrida real: cuatro grupos con 2, 5 y 14
    operaciones libres, ninguno por encima del minimo de 20, pero 23 en total.

    Antes de agregar la poblacion, el modulo contestaba "no hay propuesta" con
    veintitres operaciones sin mirar. El run es el que tiene muestra suficiente:
    los grupos son los que se quedan sin respuesta, y el aviso de heterogeneidad
    avisa de que ese valor global es una media de distintos patrones.
    """
    muestras = (
        [trade(mfe=1.5, mae=-0.8, net=0.7, pattern="A")] * 5
        + [trade(mfe=1.2, mae=-0.6, net=0.6, pattern="B")] * 14
        + [trade(mfe=0.9, mae=-0.7, net=0.2, pattern="C")] * 2
        + [trade(mfe=1.1, mae=-0.9, net=0.2, pattern="D")] * 2
    )

    run = calibrate_run(muestras, 9.0, 9.0)

    assert all(g.suggested_take_profit_pct is None for g in run.groups)
    assert run.suggested_stop_loss_pct is None
    assert run.free_trades == 23
    # La mediana de los 23 valores cae en el bloque de 1,2, que es el segundo
    # mas numeroso: 23 no da 1,1 ni 1,5 aunque haya dos operaciones en 1,1.
    assert run.suggested_take_profit_pct is not None
    assert run.suggested_take_profit_pct == 1.2
    assert any("media que no le venga bien a ninguno" in a for a in run.warnings)


def test_una_minoria_no_arrastra_la_propuesta_global():
    """Un patron con cinco señales no mueve el TP de uno con doscientas: entra
    en la poblacion conjunta con su peso real, que es el suyo."""
    muchas = [trade(mfe=1.0, mae=-0.5, net=0.5, pattern="GRANDE")] * 45
    pocas = [trade(mfe=9.0, mae=-0.5, net=8.5, pattern="MINORITARIO")] * 5

    run = calibrate_run(muchas + pocas, 9.0, 9.0)

    assert run.suggested_take_profit_pct == 1.0


def test_sugerencia_global_none_sin_operaciones_libres():
    """Si el TP y el SL decidieron todas las operaciones no hay nada que
    propose, y el modulo lo dice en vez de devolver la media de los grupos."""
    muestras = [trade(mfe=2.0, mae=-0.5, net=1.5, reason=TAKE_PROFIT)] * 30

    run = calibrate_run(muestras, 2.0, 1.0)

    assert run.suggested_take_profit_pct is None
    assert any("barrido de parámetros" in aviso for aviso in run.warnings)


def test_avisa_de_cuantos_grupos_hay():
    muestras = [
        trade(mfe=1.0, mae=-0.5, net=0.5, pattern="A", direction="long"),
        trade(mfe=1.0, mae=-0.5, net=0.5, pattern="B", direction="long"),
    ]

    run = calibrate_run(muestras, 2.0, 1.0)

    assert any("2 combinaciones" in aviso for aviso in run.warnings)


def test_grupo_vacio_no_se_calibra():
    with pytest.raises(AnalysisError):
        calibrate_pattern([], 2.0, 1.0)


# ---------------------------------------------------------------------------
# Rejilla
# ---------------------------------------------------------------------------
def test_la_rejilla_genera_el_producto_de_los_tres_ejes():
    grid = SweepGrid(
        take_profit_pcts=(1.0, 1.5, 2.0),
        stop_loss_pcts=(0.5, 1.0),
        max_holds=(12, 24),
    )
    base = StrategyConfig(take_profit_pct=2.0, stop_loss_pct=1.0, max_hold=24)

    configs = grid.configs(base)

    assert grid.combinations() == 12
    assert len(configs) == 12
    assert {c.take_profit_pct for c in configs} == {1.0, 1.5, 2.0}
    assert {c.stop_loss_pct for c in configs} == {0.5, 1.0}
    assert {c.max_hold for c in configs} == {12, 24}


def test_la_rejilla_no_toca_los_parametros_fuera_de_los_tres_ejes():
    """Comision, capital, fraccion y cortos vienen del run y no se tocan: el
    barrido es sobre niveles, no sobre el resto de la estrategia."""
    grid = SweepGrid(take_profit_pcts=(1.0,), stop_loss_pcts=(1.0,), max_holds=(10,))
    base = StrategyConfig(
        take_profit_pct=2.0,
        stop_loss_pct=1.0,
        max_hold=24,
        fee_bps=8.0,
        initial_capital=500.0,
        use_fraction=0.5,
        allow_short=False,
    )

    config = grid.configs(base)[0]

    assert config.fee_bps == 8.0
    assert config.initial_capital == 500.0
    assert config.use_fraction == 0.5
    assert config.allow_short is False
    assert config.max_hold == 10


def test_la_rejilla_admite_niveles_ausentes():
    grid = SweepGrid(
        take_profit_pcts=(1.0, None), stop_loss_pcts=(1.0,), max_holds=(24,)
    )
    base = StrategyConfig()

    assert [c.take_profit_pct for c in grid.configs(base)] == [1.0, None]


def test_una_celda_sin_ningun_nivel_se_salta_y_las_demas_siguen():
    """Sin TP ni SL no hay forma de cerrar antes de ``max_hold``. Es una celda
    imposible, no un motivo para tirar la rejilla entera."""
    grid = SweepGrid(
        take_profit_pcts=(1.0, None), stop_loss_pcts=(1.0, None), max_holds=(24,)
    )
    base = StrategyConfig()

    configs = grid.configs(base)

    assert len(configs) == 3
    assert all(
        c.take_profit_pct is not None or c.stop_loss_pct is not None for c in configs
    )


def test_una_rejilla_entera_invalida_se_rechaza():
    grid = SweepGrid(take_profit_pcts=(None,), stop_loss_pcts=(None,), max_holds=(24,))

    with pytest.raises(AnalysisError, match="estrategia valida"):
        grid.configs(StrategyConfig(take_profit_pct=2.0, stop_loss_pct=1.0))


def test_rejilla_demasiado_grande():
    grid = SweepGrid(
        take_profit_pcts=tuple([1.0] * 8),
        stop_loss_pcts=tuple([1.0] * 8),
        max_holds=tuple(range(1, 8)),
    )

    assert grid.combinations() > MAX_SWEEP_COMBINATIONS
    with pytest.raises(AnalysisError, match="tope"):
        grid.configs(StrategyConfig())


def test_rejilla_vacia_en_alguno_de_los_ejes():
    with pytest.raises(AnalysisError, match="al menos un valor"):
        SweepGrid(take_profit_pcts=(), stop_loss_pcts=(1.0,), max_holds=(24,)).configs(
            StrategyConfig()
        )


# ---------------------------------------------------------------------------
# Barrido sobre el motor de verdad
# ---------------------------------------------------------------------------
def _mercado_y_senales() -> tuple[pd.DataFrame, pd.DataFrame]:
    """60 velas en zigzag y cuatro señales, el mismo perfil que los fixtures.

    El zigzag importa: con velas planas ningún nivel se toca y todas las
    operaciones salen por tiempo límite, y un barrido donde todo sale igual no
    compara nada.
    """
    index = pd.date_range(
        "2024-01-01", periods=60, freq="h", tz="UTC", name="timestamp"
    )
    precios = [100.0 + (2.0 if hora % 2 else -2.0) for hora in range(60)]
    velas = pd.DataFrame(
        {
            "open": precios,
            "high": [p + 0.4 for p in precios],
            "low": [p - 0.4 for p in precios],
            "close": [p + 0.1 for p in precios],
        },
        index=index,
    )
    senales = pd.DataFrame(
        {
            "timestamp": [index[5], index[15], index[25], index[35]],
            "pattern_name": [
                "MACD_CROSS_BULLISH",
                "ENGULFING_BEARISH",
                "RSI_EXIT_OVERSOLD",
                "MACD_CROSS_BULLISH",
            ],
            "direction": ["bullish", "bearish", "bullish", "bullish"],
        }
    )
    return velas, senales


def test_el_barrido_no_escribe_nada_y_devuelve_una_fila_por_combinacion(monkeypatch):
    """Lo unico que se comprueba de verdad aqui es que ``run_backtest`` se llama
    una vez por celda y que el modulo no abre ninguna sesion de base de datos.

    Se rompe el motor con un doble que cuenta llamadas: si algun dia el barrido
    decide "persistamos el mejor", este test falla al reventar, en vez de
    Llenando la base con 120 runs que el usuario tendria que borrar a mano.
    """
    velas, senales = _mercado_y_senales()
    base = StrategyConfig(take_profit_pct=2.0, stop_loss_pct=1.0, max_hold=24)
    grid = SweepGrid(
        take_profit_pcts=(1.0, 2.0), stop_loss_pcts=(0.5, 1.0), max_holds=(12,)
    )

    llamadas: list[StrategyConfig] = []

    def falso(velas_, senales_, config):
        llamadas.append(config)
        return run_backtest(velas_, senales_, config)

    monkeypatch.setattr("app.modules.backtesting.analysis.run_backtest", falso)

    puntos = sweep(velas, senales, base, grid)

    assert len(llamadas) == 4
    assert len(puntos) == 4


def test_el_barrido_ordena_de_mejor_a_peor_y_marca_la_estrategia_del_run():
    velas, senales = _mercado_y_senales()
    base = StrategyConfig(take_profit_pct=2.0, stop_loss_pct=1.0, max_hold=24)
    grid = SweepGrid(
        take_profit_pcts=(0.5, 2.0), stop_loss_pcts=(1.0,), max_holds=(24,)
    )

    puntos = sweep(velas, senales, base, grid)

    pnls = [p.net_pnl for p in puntos]
    assert pnls == sorted(pnls, reverse=True)
    assert sum(p.is_baseline for p in puntos) == 1
    base_ = next(p for p in puntos if p.is_baseline)
    assert base_.take_profit_pct == 2.0
    assert base_.stop_loss_pct == 1.0
    assert base_.max_hold == 24


def test_el_barrido_devuelve_las_mismas_metricas_que_el_motor():
    """La fila del barrido con los parametros del run tiene que coincidir con
    una simulacion suelta del motor. Si no, la tabla comparativa estaria
    mentiendo sobre su propia primera fila."""
    velas, senales = _mercado_y_senales()
    base = StrategyConfig(take_profit_pct=2.0, stop_loss_pct=1.0, max_hold=24)
    grid = SweepGrid(take_profit_pcts=(2.0,), stop_loss_pcts=(1.0,), max_holds=(24,))

    punto = sweep(velas, senales, base, grid)[0]
    directo = run_backtest(velas, senales, base)

    assert punto.total_trades == directo.metrics["total_trades"]
    assert punto.net_pnl == pytest.approx(directo.metrics["net_pnl"], abs=1e-6)
    assert punto.total_return_pct == pytest.approx(
        directo.metrics["total_return_pct"], abs=1e-4
    )
    assert punto.win_rate == pytest.approx(directo.metrics["win_rate"], abs=1e-6)
    assert punto.is_baseline is True


def test_el_barrido_cuenta_los_motivos_de_salida():
    """El reparto de salidas es lo que explica *por que* cambia el resultado al
    mover un nivel, asi que va en la fila y no solo las metricas agregadas."""
    velas, senales = _mercado_y_senales()
    base = StrategyConfig(take_profit_pct=0.3, stop_loss_pct=0.3, max_hold=4)
    grid = SweepGrid(take_profit_pcts=(0.3,), stop_loss_pcts=(0.3,), max_holds=(4,))

    punto = sweep(velas, senales, base, grid)[0]

    assert punto.exits
    assert set(punto.exits) <= {
        "take_profit",
        "stop_loss",
        "timeout",
        "end_of_data",
    }
    assert sum(punto.exits.values()) == punto.total_trades


def test_mover_el_take_profit_cambia_el_reparto_de_salidas():
    """Un TP mas cercano convierte timeouts en take profits. Si las dos filas
    tuvieran el mismo reparto, habria un bug en como el motor guarda el motivo
    de cierre."""
    velas, senales = _mercado_y_senales()
    base = StrategyConfig(take_profit_pct=0.3, stop_loss_pct=0.5, max_hold=6)
    grid = SweepGrid(take_profit_pcts=(0.3, 2.0), stop_loss_pcts=(0.5,), max_holds=(6,))

    puntos = {p.take_profit_pct: p for p in sweep(velas, senales, base, grid)}

    cercano = puntos[0.3]
    lejano = puntos[2.0]
    assert cercano.exits.get("take_profit", 0) > lejano.exits.get("take_profit", 0)


def test_el_barrido_es_determinista():
    """Misma rejilla, mismo resultado: si no, dos clicks seguidos darian dos
    informes distintos y no habria forma de saber cual era el bueno."""
    velas, senales = _mercado_y_senales()
    base = StrategyConfig()
    grid = SweepGrid(
        take_profit_pcts=(1.0, 2.0), stop_loss_pcts=(0.5, 1.0), max_holds=(6, 12)
    )

    primero = sweep(velas, senales, base, grid)
    segundo = sweep(velas, senales, base, grid)

    assert primero == segundo
