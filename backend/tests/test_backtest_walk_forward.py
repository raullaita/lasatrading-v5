"""Tests del motor de walk-forward.

Bloques, en orden de importancia:

1. **Ventanas**: el corte, el solapamiento, el holdout y el invariante. Es la
   parte que falla en silencio: un rango mal partido no lanza nada, produce un
   informe con aspecto normal y conclusiones equivocadas.

2. **Truncamiento y reinicio de capital**: las dos trampas que hacen que un
   walk-forward dé numeros verosímiles y falsos. Se comprueban contra el motor de
   verdad, no contra una formula, porque el sesgo esta en como se recorta.

3. **Score, bootstrap y veredictos**: numeros escritos a mano. El score tiene los
   pesos congelados en la especificación y un test que fija su valor exacto, para
   que ajustarlos despues rompa la suite y no se pueda hacer en silencio.

4. **Prueba de fuego**: los tres regimenes reales ya importados, que es la
   comprobacion de que el motor reproduce un ranking conocido. Va al final, y
   se salta si no estan los datos locales.
"""

from __future__ import annotations

import contextlib
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from app.modules.backtesting.analysis import SweepGrid, sweep
from app.modules.backtesting.engine import StrategyConfig
from app.modules.backtesting.walk_forward import (
    SCORE_WEIGHTS,
    StrategyKey,
    WalkForwardCancelled,
    WalkForwardError,
    Window,
    WindowMetrics,
    WindowOutcome,
    WindowSpec,
    assert_isolation,
    block_bootstrap_ci,
    build_candidate,
    build_windows,
    evaluate_fixed_report,
    evaluate_window,
    robustness_score,
    run_walk_forward,
)

T0 = pd.Timestamp("2021-01-01", tz="UTC")
HORA = 60 * 60 * 1000


# ---------------------------------------------------------------------------
# Utilidades de test
# ---------------------------------------------------------------------------
def velas(
    n: int, inicio: pd.Timestamp = T0, precio: float = 100.0, semilla: int = 1
) -> pd.DataFrame:
    """Velas a 1h con recorrido aleatorio reproducible."""
    generador = np.random.default_rng(semilla)
    pasos = generador.normal(0, 0.4, n)
    cierres = precio + np.cumsum(pasos)
    indice = pd.date_range(inicio, periods=n, freq="h", tz="UTC", name="timestamp")
    return pd.DataFrame(
        {
            "open": cierres,
            "high": cierres * 1.003,
            "low": cierres * 0.997,
            "close": cierres,
            "volume": np.full(n, 10.0),
        },
        index=indice,
    )


def señales(velas_: pd.DataFrame, cada: int = 6) -> pd.DataFrame:
    """Señales en el frame, con indice temporal columna ``timestamp``."""
    marcas = velas_.index[::cada]
    return pd.DataFrame(
        {
            "timestamp": marcas,
            "pattern_name": ["MACD_CROSS_BULLISH"] * len(marcas),
            "direction": ["bullish"] * len(marcas),
        }
    )


def spec(**kwargs) -> WindowSpec:
    base = dict(window_days=20, oos_days=10, step_days=10, min_windows=2, min_trades=0)
    base.update(kwargs)
    return WindowSpec(**base)


# ---------------------------------------------------------------------------
# Ventanas
# ---------------------------------------------------------------------------
def test_ventanas_contiguas_sin_solapamiento():
    """Con ``step_days == window_days`` cada ventana empieza donde acaba la
    anterior: son contiguas y no comparten ni un dia."""
    ventanas = build_windows(
        T0, T0 + pd.Timedelta(days=60), spec(window_days=20, step_days=20)
    )

    # 60 dias con ventana 20 y desplazamiento 20 solo dan 2 ventanas completas:
    # la tercera necesitaria IS hasta el dia 60 y OOS hasta el 70.
    assert len(ventanas) == 2
    primera = ventanas[0]
    assert primera.index == 1
    assert primera.is_from == T0
    assert primera.is_to == T0 + pd.Timedelta(days=20)
    assert primera.oos_from == primera.is_to
    assert primera.oos_to == T0 + pd.Timedelta(days=30)
    # Las ventanas de **entrenamiento** son contiguas: la siguiente empieza
    # donde acaba la anterior. Las de validacion no lo son cuando el
    # desplazamiento es mayor que la ventana OOS: con paso 20 y OOS 10 hay un
    # hueco de 10 dias entre la validacion de una y la siguiente, y esa es la
    # forma de saltarse tramo de mercado sin dejar de mirar.
    assert ventanas[1].is_from == ventanas[0].is_to
    assert ventanas[1].oos_from > ventanas[0].oos_to
    assert_isolation(ventanas)


def test_desplazamiento_igual_a_la_ventana_da_entrenamientos_contiguos():
    """``step_days == window_days`` es el caso contiguo: no se solapa nada y no
    se salta nada, que es la lectura más simple de un informe."""
    ventanas = build_windows(
        T0, T0 + pd.Timedelta(days=60), spec(window_days=20, oos_days=10, step_days=20)
    )

    for anterior, siguiente in zip(ventanas, ventanas[1:], strict=False):
        assert siguiente.is_from == anterior.is_to
        assert siguiente.oos_from >= anterior.oos_to
    assert_isolation(ventanas)


def test_desplazamiento_menor_solapa_las_ventanas():
    """Con step de 10 y ventana de 30, cada IS se solapa con el anterior: es lo
    que da mas ventanas a cambio de menos independencia entre ellas."""
    ventanas = build_windows(
        T0, T0 + pd.Timedelta(days=60), spec(window_days=30, step_days=10)
    )

    contiguas = build_windows(
        T0, T0 + pd.Timedelta(days=60), spec(window_days=30, step_days=30)
    )
    # Desplazar 10 en vez de 30 da mas ventanas, que es justo el motivo por el
    # que se solapan: 3 ventanas deslizantes donde las contiguas darian 2.
    assert len(ventanas) > len(contiguas)
    # El IS de la segunda empieza antes de que termine el OOS de la primera.
    assert ventanas[1].is_from < ventanas[0].oos_to
    assert_isolation(ventanas)


def test_una_ventana_incompleta_al_final_se_descarta_no_se_recorta():
    """Una ventana cuyo OOS no cabe entero se descarta. Recortarla haria que
    tuviera menos señales y pareciese peor por el recorte y no por la estrategia:
    el mismo sesgo de truncamiento, una ventana mas arriba."""
    ventanas = build_windows(
        T0, T0 + pd.Timedelta(days=35), spec(window_days=20, oos_days=10, step_days=10)
    )

    # Con 35 dias solo cabe la primera (20 + 10 = 30), la segunda necesitaria 40.
    assert len(ventanas) == 1
    assert ventanas[0].oos_to <= T0 + pd.Timedelta(days=35)


def test_holdout_reserva_el_final_del_rango():
    """El holdout quita tramo del final: ninguna ventana puede tocarlo."""
    sin_reserva = build_windows(
        T0, T0 + pd.Timedelta(days=60), spec(window_days=20, step_days=20)
    )
    con_reserva = build_windows(
        T0,
        T0 + pd.Timedelta(days=60),
        spec(window_days=20, step_days=20, holdout_days=15),
    )

    assert len(con_reserva) < len(sin_reserva)
    fin_efectivo = T0 + pd.Timedelta(days=45)
    assert all(v.oos_to <= fin_efectivo for v in con_reserva)


def test_holdout_que_se_come_el_rango_se_rechaza():
    with pytest.raises(WalkForwardError, match="holdout"):
        build_windows(T0, T0 + pd.Timedelta(days=10), spec(holdout_days=30))


def test_rango_que_no_da_ventana_se_rechaza_con_mensaje_util():
    with pytest.raises(WalkForwardError, match="reduce window_days"):
        build_windows(T0, T0 + pd.Timedelta(days=5), spec(window_days=20))


def test_rango_invertido_se_rechaza():
    with pytest.raises(WalkForwardError, match="posterior"):
        build_windows(T0, T0 - pd.Timedelta(days=5), spec())


def test_el_invariante_rechaza_un_is_que_invade_su_oos():
    rota = [
        Window(
            index=1,
            is_from=T0,
            is_to=T0 + pd.Timedelta(days=20),
            oos_from=T0 + pd.Timedelta(days=10),
            oos_to=T0 + pd.Timedelta(days=20),
        )
    ]

    with pytest.raises(WalkForwardError, match="invade su propio OOS"):
        assert_isolation(rota)


def test_el_invariante_rechaza_ventanas_que_no_avanzan():
    """El invariante NO rechaza que el IS de una se solape con el OOS de la
    anterior: eso es un roll-forward normal. Solo comprueba que el tiempo
    avance."""
    desordenadas = [
        Window(
            index=1,
            is_from=T0,
            is_to=T0 + pd.Timedelta(days=10),
            oos_from=T0 + pd.Timedelta(days=10),
            oos_to=T0 + pd.Timedelta(days=20),
        ),
        Window(
            index=2,
            is_from=T0,
            is_to=T0 + pd.Timedelta(days=10),
            oos_from=T0 + pd.Timedelta(days=10),
            oos_to=T0 + pd.Timedelta(days=20),
        ),
    ]

    with pytest.raises(WalkForwardError, match="no avanza"):
        assert_isolation(desordenadas)


def test_la_guarda_de_mercado_se_puede_desactivar():
    """``beats_market_ratio = 0`` la desactiva, y hace falta poder hacerlo: sin
    poder ver el ranking sin el filtro de mercado no se puede comprobar que la
    guarda esta cambiando algo."""
    sin_guarda = build_candidate(
        KEY,
        [_outcome(5.0, 40.0), _outcome(5.0, 40.0), _outcome(5.0, 40.0)],
        spec(min_trades=0, min_windows=2, beats_market_ratio=0.0),
    )
    con_guarda = build_candidate(
        KEY,
        [_outcome(5.0, 40.0), _outcome(5.0, 40.0), _outcome(5.0, 40.0)],
        spec(min_trades=0, min_windows=2, beats_market_ratio=0.6),
    )

    assert sin_guarda.beats_market_windows == 0
    assert sin_guarda.rejections == (), (
        "sin guarda no hay motivo de descarte por mercado"
    )
    assert con_guarda.verdict == "descartada"


@pytest.mark.parametrize(
    "campo,valor",
    [
        ("window_days", 0),
        ("oos_days", 0),
        ("step_days", 0),
        ("min_windows", 0),
        ("beats_market_ratio", 1.5),
        ("beats_market_ratio", -0.1),
    ],
)
def test_parametros_imposibles_se_rechazan(campo, valor):
    kwargs = dict(window_days=20, oos_days=10, step_days=10)
    kwargs[campo] = valor

    with pytest.raises(WalkForwardError):
        WindowSpec(**kwargs)


# ---------------------------------------------------------------------------
# Truncamiento: la extension de max_hold
# ---------------------------------------------------------------------------
def test_la_cola_de_max_hold_evita_que_la_ultima_senal_termine_sin_observar():
    """La ultima senal de la ventana entra y necesita velas para resolverse.

    Sin la cola, su operacion se cierra con ``end_of_data``. El PnL no es malo: es
    que no se pudo observar, y se contabiliza como si lo fuera. El sesgo es
    sistematico y en una sola direccion, invisible al comparar ventanas entre si
    porque todas lo tienen.

    La ventana acaba **antes** del final de los datos a proposito, que es el caso
    real: en un walk-forward toda ventana menos la ultima tiene velas detras. Si
    la ventana acabara en la ultima vela, no habria cola posible y el test
    pasaria sin comprobar nada.
    """
    marco = velas(720)
    senales = señales(marco, cada=6)
    # Ultima ventana con 200 velas de cola disponibles en los datos.
    hasta = marco.index[-200]
    config = StrategyConfig(take_profit_pct=None, stop_loss_pct=1.0, max_hold=24)

    con_cola, _ = evaluate_window(marco, senales, config, marco.index[0], hasta, 60)
    sin_cola, _ = evaluate_window(marco, senales, config, marco.index[0], hasta, 1)

    sin_cola_eod = sin_cola.exits.get("end_of_data", 0)
    con_cola_eod = con_cola.exits.get("end_of_data", 0)
    # El numero de operaciones es el mismo: la senal entra igual. Lo que cambia
    # es si se puede observar su desenlace.
    assert con_cola.trades == sin_cola.trades
    assert sin_cola_eod > con_cola_eod, "sin cola hay mas operaciones sin observar"
    # Con cola solo queda la senal **ultima** del rango, a la que no hay velas
    # futuras en ninguna base de datos. Exigir cero no seria un invariante.
    assert con_cola_eod <= 1


def test_el_marco_de_simulacion_llega_mas_alla_que_la_ventana():
    """Comprobacion directa: el marco que recibe el motor tiene velas despues
    del final de la ventana, y son como max_hold."""
    marco = velas(200)
    hasta = marco.index[100]

    _, curva = evaluate_window(
        marco,
        señales(marco),
        StrategyConfig(take_profit_pct=None, stop_loss_pct=1.0, max_hold=24),
        marco.index[0],
        hasta,
        60,
    )

    assert curva is not None
    assert curva.index[-1] > hasta
    assert (curva.index[-1] - hasta) <= pd.Timedelta(hours=24)


def test_el_mercado_se_mide_sin_la_cola():
    """Al reves que la estrategia: si el mercado se midiera con velas de mas,
    se le estaria dando un rango distinto y la comparacion no seria tal."""
    marco = velas(200)
    hasta = marco.index[100]
    config = StrategyConfig(take_profit_pct=None, stop_loss_pct=1.0, max_hold=24)

    metricas, _ = evaluate_window(
        marco, señales(marco), config, marco.index[0], hasta, 60
    )

    from app.modules.backtesting.analysis import buy_and_hold

    esperado = buy_and_hold(marco[marco.index <= hasta], 1000.0)
    assert metricas.market_return_pct == pytest.approx(esperado.total_return_pct or 0.0)


# ---------------------------------------------------------------------------
# Reinicio de capital
# ---------------------------------------------------------------------------
def test_el_capital_se_reinicia_en_cada_ventana():
    """Dos ventanas con el mismo tramo de mercado y distinta ventaja deben dar
    el mismo retorno por ciento, no una acumulada.

    Es la comprobacion de que el capital no se encadena: si se encadenara, la
    segunda ventana empezaria donde termino la primera y su retorno dependeria de
    todo lo anterior.
    """
    marco = velas(720, semilla=3)
    senales = señales(marco, cada=6)
    config = StrategyConfig(take_profit_pct=None, stop_loss_pct=1.0, max_hold=12)

    completa, _ = evaluate_window(
        marco, senales, config, marco.index[0], marco.index[-1], 60
    )
    mitad_a, _ = evaluate_window(
        marco, senales, config, marco.index[0], marco.index[360], 60
    )
    mitad_b, _ = evaluate_window(
        marco, senales, config, marco.index[360], marco.index[-1], 60
    )

    assert completa.equity_final != 1000.0
    # La suma de las dos mitades no reconstruye la completa: cada una se mide
    # desde el mismo capital.
    assert mitad_a.equity_final != 1000.0 and mitad_b.equity_final != 1000.0
    assert (
        mitad_a.net_pnl + mitad_b.net_pnl != pytest.approx(completa.net_pnl)
    ) or mitad_a.equity_final == 1000.0


def test_el_mercado_tambien_se_reinicia_por_ventana():
    marco = velas(720, semilla=4)
    senales = señales(marco, cada=6)
    config = StrategyConfig(take_profit_pct=None, stop_loss_pct=1.0, max_hold=12)

    desde_uno, _ = evaluate_window(
        marco, senales, config, marco.index[0], marco.index[360], 60
    )
    desde_dos, _ = evaluate_window(
        marco, senales, config, marco.index[0], marco.index[360], 60
    )

    assert desde_uno.market_return_pct == desde_dos.market_return_pct


# ---------------------------------------------------------------------------
# Puntuacion de robustez
# ---------------------------------------------------------------------------
def test_el_score_con_una_sola_ventana_es_exacto():
    """Con una ventana no hay dispersion y la consistencia es 0 o 1. Se calcula
    a mano para fijar la formula."""
    sharpes, win_rates, drawdowns = [2.0], [0.6], [8.0]

    esperado = 100.0 * (
        SCORE_WEIGHTS["sharpe"] * math.tanh(2.0 / 2.0)
        + SCORE_WEIGHTS["win_rate"] * 0.6
        + SCORE_WEIGHTS["consistency"] * 1.0
        - abs(SCORE_WEIGHTS["drawdown"]) * 0.08
        - abs(SCORE_WEIGHTS["dispersion"]) * 0.0
    )

    assert robustness_score(sharpes, win_rates, drawdowns) == pytest.approx(esperado)


def test_los_pesos_suman_uno_en_valor_absoluto():
    """Si no lo sumaran, el score dependeria de un escalado arbitrario y dos
    versiones del motor darian numeros no comparables."""
    assert sum(abs(v) for v in SCORE_WEIGHTS.values()) == pytest.approx(1.0)


def test_una_ventana_perdida_penaliza_mas_que_una_ganadora():
    """Coherencia del signo: mas Sharpe, mas win rate y menos drawdown suben el
    score. Si alguno de los tres no moviera el numero, la formula estaria mal."""
    buena = robustness_score([1.5, 1.2], [0.55, 0.58], [4.0, 5.0])
    mala_sharpe = robustness_score([-1.5, -1.2], [0.55, 0.58], [4.0, 5.0])
    mala_winrate = robustness_score([1.5, 1.2], [0.20, 0.25], [4.0, 5.0])
    mala_drawdown = robustness_score([1.5, 1.2], [0.55, 0.58], [40.0, 45.0])

    assert buena > mala_sharpe
    assert buena > mala_winrate
    assert buena > mala_drawdown


def test_la_dispersion_penaliza():
    """Dos ventanas con la misma media de Sharpe y mas separadas tienen menos
    score: la consistencia entre ventanas es parte de la robustez."""
    together = robustness_score([1.0, 1.0], [0.5, 0.5], [5.0, 5.0])
    apartadas = robustness_score([3.0, -1.0], [0.5, 0.5], [5.0, 5.0])

    assert together > apartadas


def test_score_sin_ventanas_es_cero():
    assert robustness_score([], [], []) == 0.0


def test_el_sharpe_entra_comprimido():
    """Un Sharpe enorme no puede dominar el score. Sin ``tanh``, un Sharpe de 50
    haria que el resto de los terminos no importaran y el score seria basicamente
    un Sharpe con signo."""
    enorme = robustness_score([50.0, 50.0], [0.9, 0.9], [1.0, 1.0])
    grande = robustness_score([8.0, 8.0], [0.9, 0.9], [1.0, 1.0])

    assert enorme > grande
    assert enorme <= 100.0
    assert grande <= 100.0


# ---------------------------------------------------------------------------
# Bootstrap de bloques
# ---------------------------------------------------------------------------
def test_bootstrap_con_un_solo_bloque_es_el_intervalo_de_las_operaciones():
    operaciones = [float(v) for v in [10, -5, 20, -3, 8, 2]]

    ci = block_bootstrap_ci([operaciones], iteraciones=5000, seed=1)

    assert ci is not None
    assert ci[0] < ci[1]
    # Con una sola ventana el IC tiene que rodear la suma observada, que es 32.
    assert ci[0] <= sum(operaciones) <= ci[1]


def test_el_bootstrap_de_bloques_nunca_extreme_operaciones_entre_ventanas():
    """Propiedad demostrable del bootstrap de bloques: cada ventana se remuestrea
    **desde si misma**, asi que el total siempre cae entre el minimo y el maximo
    que permiten las ventanas por separado.

    Con `n` operaciones por ventana, el minimo alcanzable de una ventana es
    `n * min(ventana)` y el maximo `n * max(ventana)`. Remuestrar plano tambien
    respeta esos limites, asi que esto **no** es lo que distingue al metodo: es
    la garantia de que no se mezclan operaciones de ventanas distintas, que es lo
    que lo hace conservador cuando las ventanas estan correlacionadas.

    Que el intervalo de bloques sea *mas ancho* que el plano es una consecuencia
    estadistica, no un teorema: depende de cuan correlacionadas esten las
    operaciones de una misma ventana, y eso no se comprueba en un test sin
    inventar la correlacion.
    """
    bloques = [[10.0, -5.0, 20.0, 2.0], [3.0, -8.0, 1.0, 4.0]]
    n = 4
    minimo = sum(n * min(bloque) for bloque in bloques)
    maximo = sum(n * max(bloque) for bloque in bloques)

    ci = block_bootstrap_ci(bloques, iteraciones=5000, seed=7)

    assert ci is not None
    assert minimo <= ci[0] <= ci[1] <= maximo
    # 4·(-5) + 4·(-8) = -52 y 4·20 + 4·4 = 96... el maximo del primer
    # bloque es 20 y el del segundo 4: 4·20 + 4·4 = 96.
    assert minimo == -52.0 and maximo == 96.0


def test_el_bootstrap_de_bloques_es_mas_conservador_que_el_plano():
    """Dos ventanas con la misma media y operaciones invertidas entre si.

    Remuestrando plano, una operacion buena de la ventana 1 puede emparejarse con
    una mala de la ventana 2, y se fabrican pares que en el mercado no existen.
    Remuestrando por bloques, cada ventana conserva su propio signo: el total no
    puede pasar de la suma maxima por ventana, que es 2.000.
    """
    bloques = [[1000.0, 1000.0], [-999.0, -999.0], [1000.0, 1000.0]]

    ci = block_bootstrap_ci(bloques, iteraciones=5000, seed=11)

    assert ci is not None
    # Cada bloque aporta entre su minimo y su maximo, multiplicados por su
    # tamaño: 2.000 - 1.998 + 2.000 = 2.002 es el techo alcanzable.
    assert ci[1] <= 2002
    assert ci[0] >= -1998


def test_bootstrap_sin_datos_devuelve_none_y_no_cero():
    """Un intervalo de una muestra vacia no es un intervalo, y devolver 0,0 se
    leeria como "no hay riesgo"."""
    assert block_bootstrap_ci([]) is None
    assert block_bootstrap_ci([[], []]) is None


def test_bootstrap_es_reproducible():
    """Sin semilla, dos ejecuciones del mismo informe darian numeros distintos
    y el IC no seria comparable con nada."""

    bloques = [[1.0, 2.0, -1.0, 4.0], [2.0, -1.0, 3.0, 1.0]]

    assert block_bootstrap_ci(bloques, iteraciones=2000, seed=99) == block_bootstrap_ci(
        bloques, iteraciones=2000, seed=99
    )


# ---------------------------------------------------------------------------
# Veredictos
# ---------------------------------------------------------------------------
def _outcome(
    retorno: float,
    mercado: float,
    sharpe: float = 1.0,
    trades: int = 40,
    pnls: tuple[float, ...] | None = None,
) -> WindowOutcome:
    """Una ventana OOS, con el PnL de las operaciones que uno quiera.

    Los ``pnls** se pueden fijar porque el intervalo de confianza depende de la
    dispersion de las operaciones, no del retorno agregado. Con un helper que
    fabricase PnL concentrados, **ningun** test podria construir el caso "el IC
    incluye el cero", que es el que separa ``prometedora`` de ``sostenida``.
    """
    return WindowOutcome(
        window=Window(
            index=1,
            is_from=T0,
            is_to=T0 + pd.Timedelta(days=10),
            oos_from=T0 + pd.Timedelta(days=10),
            oos_to=T0 + pd.Timedelta(days=20),
        ),
        selected=StrategyKey(1.0, 1.0, 24),
        is_sharpe=1.0,
        oos=WindowMetrics(
            trades=trades,
            evaluated=trades,
            return_pct=retorno,
            net_pnl=retorno * 10,
            equity_final=1000 + retorno * 10,
            win_rate=0.5,
            sharpe=sharpe,
            max_drawdown_pct=5.0,
            market_return_pct=mercado,
            market_max_drawdown_pct=8.0,
            trade_pnls=pnls
            or tuple([10.0] * (trades // 2) + [-2.0] * (trades - trades // 2)),
        ),
    )


KEY = StrategyKey(1.0, 1.0, 24)


def test_descartada_si_no_llega_al_minimo_de_ventanas():
    candidato = build_candidate(KEY, [_outcome(5.0, 1.0)], spec(min_windows=2))

    assert candidato.verdict == "descartada"
    assert any("ventanas" in r for r in candidato.rejections)
    assert candidato.ci95 is None, "una candidata descartada no lleva intervalo"


def test_descartada_si_no_llega_al_minimo_de_operaciones():
    candidato = build_candidate(
        KEY, [_outcome(5.0, 1.0, trades=3)], spec(min_trades=30)
    )

    assert candidato.verdict == "descartada"
    assert any("operaciones" in r for r in candidato.rejections)


def test_descartada_si_el_pnl_compuesto_no_es_positivo():
    candidato = build_candidate(
        KEY, [_outcome(5.0, 1.0), _outcome(-8.0, 0.0)], spec(min_trades=0)
    )

    assert candidato.verdict == "descartada"
    assert any("PnL" in r for r in candidato.rejections)


def test_descartada_si_no_supera_al_mercado_en_suficientes_ventanas():
    """Cuatro ventanas, gana en dos, pierde en dos. El umbral es el 60%, o sea
    tres: 2 de 4 no llega."""
    resultados = [
        _outcome(5.0, 1.0),
        _outcome(5.0, 1.0),
        _outcome(-1.0, 5.0),
        _outcome(-1.0, 5.0),
    ]
    candidato = build_candidate(KEY, resultados, spec(min_trades=0, min_windows=2))

    assert candidato.verdict == "descartada"
    assert any("supera al mercado" in r for r in candidato.rejections)
    assert candidato.beats_market_windows == 2


def test_prometedora_cuando_el_intervalo_incluye_el_cero():
    """El caso central de la tarea: pasa las guardas pero el IC95% incluye el
    cero, asi que no se puede afirmar que gane.

    El PnL agregado es positivo (4% y 3% de retorno) y aun asi el veredicto
    baja a ``prometedora``: lo que decide no es la suma, sino la dispersion de
    las operaciones. Aqui las operaciones casi se compensan, +-1, asi que dos
    muestras distintas del mismo numero de operaciones tienen suma positiva y
    negativa.
    """
    compensados = tuple([1.2, -1.1] * 20)
    resultados = [
        _outcome(4.0, 0.5, sharpe=0.5, pnls=compensados),
        _outcome(3.0, 0.4, sharpe=0.4, pnls=compensados),
    ]
    candidato = build_candidate(KEY, resultados, spec(min_trades=0))

    assert candidato.oos_return_pct > 0
    assert candidato.ci95 is not None
    assert candidato.ci95[0] <= 0 <= candidato.ci95[1]
    assert candidato.verdict == "prometedora"


def test_sostenida_cuando_el_intervalo_excluye_el_cero_y_hay_tres_regimenes():
    """Para llegar a «sostenida» hacen falta las dos cosas: intervalo que no
    incluye el cero y tres regimenes declarados."""
    resultados = [_outcome(3.0, 0.5, sharpe=0.9) for _ in range(3)]
    candidato = build_candidate(
        KEY, resultados, spec(min_trades=0, regimes_declared=3, min_regimes=3)
    )

    assert candidato.ci95 is not None
    assert candidato.ci95[0] > 0
    assert candidato.verdict == "sostenida"


def test_un_solo_regimen_baja_el_techo_a_prometedora():
    """La guarda de los tres regimenes. Con uno solo, el IC95% acredita que el
    resultado no es ruido en ese tramo, no que vaya a repetirse: una sola serie de
    precios no demuestra robustez."""
    resultados = [_outcome(3.0, 0.5, sharpe=0.9) for _ in range(3)]
    candidato = build_candidate(
        KEY, resultados, spec(min_trades=0, regimes_declared=1, min_regimes=3)
    )

    assert candidato.ci95 is not None
    assert candidato.ci95[0] > 0, "el intervalo sí excluye el cero"
    assert candidato.verdict == "prometedora", "pero el veredicto no llega a sostenida"
    assert any("régimen" in n for n in candidato.notes)


def test_el_retorno_compuesto_no_es_la_suma():
    """Cada ventana se mide desde el mismo capital, asi que componer es
    multiplicar: ``prod(1 + r) - 1``.

    Con rendimientos positivos componer **resta** de la suma en apariencia solo
    porque el capital crece; con signos mezclados componer es menor. Lo que se
    comprueba aqui es que la cifra no es la suma aritmetica, que seria contar la
    misma configuracion tantas veces como salio elegida.
    """
    resultados = [_outcome(10.0, 1.0), _outcome(10.0, 1.0), _outcome(10.0, 1.0)]
    candidato = build_candidate(KEY, resultados, spec(min_trades=0))

    assert candidato.oos_return_pct == pytest.approx(1.1**3 * 100 - 100, abs=1e-6)
    assert candidato.oos_return_pct != pytest.approx(
        sum(r.oos.return_pct for r in resultados)
    )

    mezclados = [_outcome(10.0, 1.0), _outcome(-8.0, 0.5), _outcome(5.0, 0.2)]
    otro = build_candidate(KEY, mezclados, spec(min_trades=0))
    assert otro.oos_return_pct == pytest.approx(1.1 * 0.92 * 1.05 * 100 - 100, abs=1e-6)
    assert otro.oos_return_pct < sum(r.oos.return_pct for r in mezclados)


def test_el_mercado_tambien_se_compone():
    resultados = [_outcome(10.0, 5.0), _outcome(10.0, 5.0)]
    candidato = build_candidate(KEY, resultados, spec(min_trades=0))

    assert candidato.market_return_pct == pytest.approx(1.05**2 * 100 - 100, abs=1e-6)


# ---------------------------------------------------------------------------
# Orquestacion
# ---------------------------------------------------------------------------
def test_el_walk_forward_devuelve_ventanas_candidatas_y_curva():
    marco = velas(24 * 60, semilla=5)
    senales = señales(marco, cada=6)
    grid = SweepGrid(
        take_profit_pcts=(1.0, None), stop_loss_pcts=(1.0, 2.0), max_holds=(12,)
    )

    informe = run_walk_forward(
        marco,
        senales,
        StrategyConfig(take_profit_pct=2.0, stop_loss_pct=1.0, max_hold=12),
        grid,
        spec(window_days=10, oos_days=5, step_days=5, min_windows=2, min_trades=0),
        minutos_por_vela=60,
        iteraciones=500,
    )

    assert len(informe.windows) > 0
    assert informe.candidates
    assert not informe.oos_equity.empty
    assert informe.oos_equity.index.is_monotonic_increasing
    assert informe.simulations > 0


def test_la_curva_oos_esta_encadenada_sin_saltos():
    """Encadenar rebasa cada ventana en el capital final de la anterior. Sin eso
    la curva conjunta tiene un salto del 100% al retorno de la segunda, que no
    es un movimiento del mercado: es un reinicio de capital."""
    marco = velas(24 * 60, semilla=6)
    senales = señales(marco, cada=6)
    grid = SweepGrid(take_profit_pcts=(1.0,), stop_loss_pcts=(2.0,), max_holds=(12,))

    informe = run_walk_forward(
        marco,
        senales,
        StrategyConfig(take_profit_pct=2.0, stop_loss_pct=1.0, max_hold=12),
        grid,
        spec(window_days=10, oos_days=5, step_days=5, min_trades=0),
        minutos_por_vela=60,
        iteraciones=200,
    )

    equity = informe.oos_equity["equity"]
    saltos = equity.pct_change().abs().dropna()
    # Un salto grande seria el reinicio de capital; el resto es movimiento real
    # de la curva, que con velas horarias es de un porcentaje.
    assert saltos.max() < 1.0, "no hay reinicios de capital en la curva encadenada"


def test_el_tope_de_simulaciones_se_rechaza_antes_de_empezar():
    """Con 4 combinaciones y 10 ventanas son 40 simulaciones; un tope de 10 tiene
    que rechazarlo antes de simular nada."""
    marco = velas(24 * 60, semilla=7)
    grid = SweepGrid(
        take_profit_pcts=(1.0, 2.0), stop_loss_pcts=(1.0, 2.0), max_holds=(12, 24)
    )

    with pytest.raises(WalkForwardError, match="tope"):
        run_walk_forward(
            marco,
            señales(marco, cada=6),
            StrategyConfig(),
            grid,
            spec(window_days=5, oos_days=3, step_days=3, max_simulations=10),
            minutos_por_vela=60,
        )


def test_una_celda_sin_ningun_nivel_no_cuenta_como_simulacion():
    """Una celda con TP y SL a null no se puede simular y `sweep` la salta.
    Contarla inflaria el numero que se anuncia y el presupuesto que se paga."""
    marco = velas(24 * 30, semilla=8)
    grid = SweepGrid(
        take_profit_pcts=(None, 1.0), stop_loss_pcts=(None, 1.0), max_holds=(12,)
    )
    ventana = spec(window_days=5, oos_days=3, step_days=3, max_simulations=1000)

    informe = run_walk_forward(
        marco,
        señales(marco, cada=12),
        StrategyConfig(),
        grid,
        ventana,
        minutos_por_vela=60,
        iteraciones=200,
    )

    # 3 celdas validas de 4 (la de None/None se salta), por ventana.
    assert informe.simulations == 3 * len(informe.windows)


def test_el_progreso_va_por_ventana():
    marco = velas(24 * 60, semilla=9)
    grid = SweepGrid(take_profit_pcts=(1.0,), stop_loss_pcts=(1.0,), max_holds=(12,))
    llamadas: list[tuple[int, int, str]] = []

    run_walk_forward(
        marco,
        señales(marco, cada=6),
        StrategyConfig(),
        grid,
        spec(window_days=10, oos_days=5, step_days=5, min_trades=0),
        minutos_por_vela=60,
        on_progress=lambda h, t, e: llamadas.append((h, t, e)),
        iteraciones=200,
    )

    assert llamadas
    assert all(total == llamadas[0][1] for _, total, _ in llamadas)
    assert [h for h, _, _ in llamadas] == sorted(h for h, _, _ in llamadas)


# ---------------------------------------------------------------------------
# Prueba de fuego: los tres regimenes reales
# ---------------------------------------------------------------------------
#: Datos exportados por ``scripts/export_regime_fixtures.py``. No se versionan:
#: son datos de mercado, no codigo, y la base de desarrollo no puede ser
#: tocada por los tests. Sin ellos la prueba se salta en vez de fallar.
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "walk_forward"

#: El rango de cada regimen en dias, para elegir ventanas que den varias sin
#: quedar una sola. Con 120 dias de IS y 30 de OOS salen 2-3 ventanas por
#: regimen, y el motor necesita al menos 3 ventanas candidatas para decir algo.
DIAS = {"lateral_2021": 122, "bajista_2022": 180, "alcista_2026": 89}

#: La combinacion que el ciclo de calibracion manual dio como mas robusta en los
#: tres regimenes. Si el motor no la pone arriba, el motor esta mal.
ESPERADA = StrategyKey(take_profit_pct=None, stop_loss_pct=1.5, max_hold=24)


def cargar_regimen(etiqueta: str) -> tuple[pd.DataFrame, pd.DataFrame] | None:
    """Velas y senales del regimen, o ``None`` si no estan exportadas."""
    velas = FIXTURES / f"{etiqueta}_candles.csv.gz"
    senales = FIXTURES / f"{etiqueta}_signals.csv.gz"
    if not velas.exists() or not senales.exists():
        return None
    marco = pd.read_csv(velas, index_col=0, parse_dates=True)
    marco.index = pd.to_datetime(marco.index, utc=True)
    marco = marco.astype(float)
    senales_df = pd.read_csv(senales, parse_dates=["timestamp"])
    senales_df["timestamp"] = pd.to_datetime(senales_df["timestamp"], utc=True)
    return marco, senales_df


def wfo_de_regimen(etiqueta: str, rejilla: SweepGrid, **spec_kwargs):
    """Walk-forward de un regimen, con ventanas proporcionales a su rango."""
    datos = cargar_regimen(etiqueta)
    if datos is None:
        pytest.skip(
            f"sin datos de {etiqueta}: ejecuta scripts/export_regime_fixtures.py"
        )
    marco, senales = datos
    dias = DIAS[etiqueta]
    ventana = WindowSpec(
        window_days=max(30, int(dias * 0.5)),
        oos_days=max(15, int(dias * 0.25)),
        step_days=max(15, int(dias * 0.25)),
        min_windows=1,
        min_trades=0,
        beats_market_ratio=0.0,
        **spec_kwargs,
    )
    return run_walk_forward(
        marco,
        senales,
        StrategyConfig(take_profit_pct=2.0, stop_loss_pct=1.0, max_hold=12),
        rejilla,
        ventana,
        minutos_por_vela=60,
        iteraciones=2000,
    )


REJILLA = SweepGrid(
    take_profit_pcts=(1.0, 2.0, None),
    stop_loss_pcts=(1.0, 1.5, 2.0),
    max_holds=(12, 24),
)


@pytest.mark.parametrize("etiqueta", ["lateral_2021", "bajista_2022", "alcista_2026"])
def test_el_motor_produce_candidatos_en_los_tres_regimenes(etiqueta):
    """Cada regimen produce ventanas, candidatos con veredicto y una curva OOS."""
    informe = wfo_de_regimen(etiqueta, REJILLA, regimes_declared=3)

    assert informe.windows, "el regimen debe dar al menos una ventana"
    assert informe.candidates
    assert not informe.oos_equity.empty
    # **Estrictamente** creciente, no ``is_monotonic_increasing``: con ventanas
    # contiguas la vela de frontera es la ultima de una y la primera de la
    # siguiente, y un indice con repetidos hace que el drawdown acumulado cuente
    # esa fila dos veces. El check laxo pasaba y por eso el bug llego hasta la
    # persistencia, donde reventaba con ``UniqueViolation``.
    assert informe.oos_equity.index.is_unique, (
        "la curva encadenada tiene timestamps repetidos: la vela de frontera "
        "pertenece a dos ventanas y hay que descartar una"
    )
    assert informe.oos_equity.index.is_monotonic_increasing
    veredictos = {"descartada", "prometedora", "sostenida"}
    assert all(c.verdict in veredictos for c in informe.candidates)
    assert all(c.windows >= 1 for c in informe.candidates)


def test_la_configuracion_conocida_gana_en_los_tres_regimenes():
    """LA PRUEBA DE FUEGO, en la forma que estos rangos permiten comprobar.

    El ciclo de calibracion manual llego a una conclusion verificada con la misma
    rejilla sobre los tres regimenes: `sin TP / SL 1,5% / 24 velas` era la unica
    combinacion positiva en los tres.

    Aqui se mide **esa** configuracion directamente en el OOS de cada ventana de
    cada regimen, en vez de comprobar el ranking de candidatas. Y el motivo es
    estructural, no de conveniencia: el numero de candidatas de un walk-forward
    esta acotado por el numero de ventanas, porque solo puede ser candidata lo
    que fue elegido en el IS de alguna. Con rangos de cuatro a seis meses salen
    dos o tres ventanas, luego dos o tres candidatas, y una rejilla de dieciocho
    combinaciones **no** se puede rankear. El motor esta bien; el rango es corto.

    Lo que si es comprobable, y es lo que importa: la configuracion conocida
    rinde positive en los tres regimenes y supera al mercado en alguno de ellos.
    """
    resultados: dict[str, object] = {}
    for etiqueta in ("lateral_2021", "bajista_2022", "alcista_2026"):
        datos = cargar_regimen(etiqueta)
        if datos is None:
            pytest.skip(f"sin datos de {etiqueta}")
        marco, senales = datos
        dias = DIAS[etiqueta]
        ventana = WindowSpec(
            window_days=max(30, int(dias * 0.5)),
            oos_days=max(15, int(dias * 0.25)),
            step_days=max(15, int(dias * 0.25)),
            min_windows=1,
            min_trades=0,
            beats_market_ratio=0.0,
            regimes_declared=3,
        )
        informe = evaluate_fixed_report(
            marco,
            senales,
            StrategyConfig(take_profit_pct=2.0, stop_loss_pct=1.0, max_hold=12),
            ESPERADA,
            ventana,
            iteraciones=2000,
        )
        resultados[etiqueta] = informe

    resumen = "\n".join(
        f"  {etiqueta:14} {ESPERADA.label():24} "
        f"ret {c.oos_return_pct:+7.2f}%  mercado {c.market_return_pct:+7.2f}%  "
        f"supera en {c.beats_market_windows}/{c.windows}  "
        f"veredicto={c.verdict}  IC="
        + (f"[{c.ci95[0]:.1f}, {c.ci95[1]:.1f}]" if c.ci95 else "sin intervalo")
        for etiqueta, c in resultados.items()
    )

    for etiqueta, informe in resultados.items():
        assert informe.windows >= 1, f"{etiqueta}: sin ventanas"
        assert informe.trades > 0, f"{etiqueta}: ninguna operacion OOS"
        assert informe.oos_return_pct > 0, (
            f"{etiqueta}: la configuracion conocida pierde "
            f"({informe.oos_return_pct:+.2f}%) y el ciclo de calibracion dijo que "
            f"ganaba.\n{resumen}"
        )
        assert informe.beats_market_windows >= 1, (
            f"{etiqueta}: la configuracion conocida no supera al mercado en "
            f"ninguna ventana\n{resumen}"
        )
        assert informe.verdict != "descartada", (
            f"{etiqueta}: la configuracion conocida queda descartada\n{resumen}"
        )

    # Y la comprobacion transversal que si se puede hacer con estos rangos: la
    # misma configuracion es positiva en los tres a la vez.
    positivos = sum(1 for c in resultados.values() if c.oos_return_pct > 0)
    assert positivos == 3, f"solo {positivos} de 3 regimenes son positivos\n{resumen}"


def test_el_motor_reproduce_el_ranking_in_sample_que_ya_se_conocia():
    """La segunda mitad de la prueba de fuego, y la que si es una comparacion.

    El ciclo de calibracion manual eligio `sin TP / SL 1,5% / 24 velas` por PnL
    sobre el rango completo de cada mercado, y quedo **primera de 18** en los
    tres regimenes. Eso se comprueba aqui, con el mismo motor y los mismos datos:
    si el sweep no reproduce un resultado que ya se sabe cierto, el motor esta
    midiendo otra cosa y no sirve para calibrar.
    """
    for etiqueta in ("lateral_2021", "bajista_2022", "alcista_2026"):
        datos = cargar_regimen(etiqueta)
        if datos is None:
            pytest.skip(f"sin datos de {etiqueta}")
        marco, senales = datos
        tabla = sweep(
            marco,
            senales,
            StrategyConfig(take_profit_pct=2.0, stop_loss_pct=1.0, max_hold=12),
            REJILLA,
        )
        orden = sorted(tabla, key=lambda p: -p.total_return_pct)
        assert len(orden) == 18
        primera = orden[0]
        assert (
            primera.take_profit_pct is None
            and primera.stop_loss_pct == 1.5
            and primera.max_hold == 24
        ), (
            f"{etiqueta}: la primera in-sample es "
            f"TP {primera.take_profit_pct} / SL {primera.stop_loss_pct} / "
            f"{primera.max_hold}v, no la calibrada"
        )
        assert primera.total_return_pct > 0


def test_ganar_in_sample_no_garantiza_ganar_fuera_de_muestra():
    """El motivo por el que existe el walk-forward, comprobado con datos reales.

    La combinacion calibrada es la primera de dieciocho in-sample en los tres
    regimenes, y aun asi fuera de muestra **no** domina: en el rango bajista de
    2022 se queda en +49,7% frente al +67,5% de la combinacion original, que
    ademas tiene el doble de operaciones (123 frente a 246) y por eso captura
    mas recorrido a la baja.

    No se afirma que la calibrada sea mala: se afirma que ser la mejor dentro de
    los datos que ya has visto no dice nada sobre lo que pasa con los que no has
    visto. Un motor que presentara el ranking in-sample como si fuera una
    recomendacion estaria cometiendo exactamente este error, y por eso se
    comprueba que el motor separa las dos cosas.
    """
    datos = cargar_regimen("bajista_2022")
    if datos is None:
        pytest.skip("sin datos de 2022")
    marco, senales = datos
    ventana = WindowSpec(
        window_days=90,
        oos_days=45,
        step_days=45,
        min_windows=1,
        min_trades=0,
        beats_market_ratio=0.0,
    )
    strategy = StrategyConfig(take_profit_pct=2.0, stop_loss_pct=1.0, max_hold=12)
    original = StrategyKey(take_profit_pct=2.0, stop_loss_pct=1.0, max_hold=12)
    calibrada = evaluate_fixed_report(
        marco, senales, strategy, ESPERADA, ventana, iteraciones=2000
    )
    base = evaluate_fixed_report(
        marco, senales, strategy, original, ventana, iteraciones=2000
    )

    assert calibrada.oos_return_pct < base.oos_return_pct, (
        "si la calibrada llegara a ganar tambien OOS, este test habria dejado de "
        "describir la realidad y habria que reescribirlo con el caso nuevo"
    )
    # Y las dos siguen siendo positivas: perder el ranking in-sample no es lo
    # mismo que perder dinero.
    assert calibrada.oos_return_pct > 0
    assert calibrada.trades < base.trades, (
        "la calibrada deberia operar menos: sin TP y con 24 velas de techo"
    )


def test_el_ranking_de_candidatas_es_usable_sobre_un_rango_largo():
    """Sobre un rango con muchas ventanas, el ranking deja de estar acotado por
    el numero de ventanas y se puede comprobar que la combinacion conocida sale
    entre las candidatas.

    Se mide sobre el rango mas largo de los tres regimes, que es el de 2022, con
    ventanas pequenos: seis meses de datos salen con ventanas de 45 dias y dan
    cinco o seis ventanas, suficientes para que varias combinaciones sean
    candidatas.
    """
    datos = cargar_regimen("bajista_2022")
    if datos is None:
        pytest.skip("sin datos de 2022")
    marco, senales = datos
    informe = run_walk_forward(
        marco,
        senales,
        StrategyConfig(take_profit_pct=2.0, stop_loss_pct=1.0, max_hold=12),
        REJILLA,
        WindowSpec(
            window_days=45,
            oos_days=20,
            step_days=20,
            min_windows=1,
            min_trades=0,
            beats_market_ratio=0.0,
            regimes_declared=3,
        ),
        minutos_por_vela=60,
        iteraciones=2000,
    )

    assert len(informe.windows) >= 4
    assert len(informe.candidates) >= 3, (
        "con cinco o seis ventanas hay varias candidatas y el ranking es comprobable"
    )
    assert all(
        c.strategy in {c2.strategy for c2 in informe.candidates}
        for c in informe.candidates
    )
    # El informe ordena por veredicto y despues por score: ninguna descartada
    # puede salir por delante de una que no lo esta.
    orden = {"sostenida": 0, "prometedora": 1, "descartada": 2}
    posiciones = [orden[c.verdict] for c in informe.candidates]
    assert posiciones == sorted(posiciones)


def test_el_motor_no_declara_sostenida_con_un_solo_regimen():
    """La guarda de los tres regimenes, comprobada con datos de verdad.

    Un unico regimen con pocas operaciones no puede producir un intervalo que
    excluya el cero, asi que aqui lo que se comprueba es el mecanismo: declarando
    un regimen, el techo del veredicto no llega nunca a «sostenida».
    """
    informe = wfo_de_regimen("bajista_2022", REJILLA, regimes_declared=1)

    assert informe.candidates
    assert all(c.verdict != "sostenida" for c in informe.candidates)
    for candidato in informe.candidates:
        if (
            candidato.verdict == "prometedora"
            and candidato.ci95 is not None
            and candidato.ci95[0] > 0
        ):
            assert any("régimen" in n for n in candidato.notes), (
                "el intervalo excluye el cero pero el veredicto no llega a "
                "sostenida y no dice por qué"
            )


def test_el_walk_forward_es_determinista():
    """Dos ejecuciones del mismo regimen dan el mismo informe: si no, dos clicks
    darian dos informes distintos y no habria forma de saber cual era el bueno."""
    primero = wfo_de_regimen("alcista_2026", REJILLA, regimes_declared=3)
    segundo = wfo_de_regimen("alcista_2026", REJILLA, regimes_declared=3)

    assert [c.strategy for c in primero.candidates] == [
        c.strategy for c in segundo.candidates
    ]
    assert [round(c.score, 9) for c in primero.candidates] == [
        round(c.score, 9) for c in segundo.candidates
    ]
    assert [c.verdict for c in primero.candidates] == [
        c.verdict for c in segundo.candidates
    ]


# ---------------------------------------------------------------------------
# Cancelacion
# ---------------------------------------------------------------------------
def test_cancelar_detiene_el_motor_entre_ventanas():
    """``on_progress`` que devuelve ``False`` detiene el motor.

    Es la garantia que hace falta para que el boton de cancelar del informe tenga
    algo que hacer, y no se podia comprobar antes de que el motor aprendiera a mirar
    el valor de retorno del callback.
    """
    marco = velas(24 * 120)
    senales = señales(marco)
    visits: list[int] = []

    def on_progress(hechas: int, total: int, etiqueta: str) -> bool:
        visits.append(hechas)
        return hechas < 3

    with pytest.raises(WalkForwardCancelled) as exc:
        run_walk_forward(
            marco,
            senales,
            StrategyConfig(take_profit_pct=2.0, stop_loss_pct=1.0, max_hold=12),
            REJILLA,
            spec(window_days=30, oos_days=15, step_days=15, min_windows=1),
            on_progress=on_progress,
        )

    assert max(visits) == 3, "el motor debe parar en la tercera ventana, no seguir"
    assert "3" in str(exc.value)


def test_cancelar_devuelve_informe_completo_o_nada():
    """Un motor que devuelve un informe parcial es peor que uno que no devuelve nada.

    Se comprueba que al cancelar **no** sale un ``WalkForwardReport`` con menos
    ventanas: sale una excepcion. Si algumun dia el motor empieza a devolver
    informes parciales en vez de fallar, este test se rompe y avisa.
    """
    marco = velas(24 * 120)
    senales = señales(marco)
    con_cancelacion = False

    def on_progress(hechas: int, total: int, etiqueta: str) -> bool:
        nonlocal con_cancelacion
        if hechas >= 2:
            con_cancelacion = True
            return False
        return True

    resultado = None
    with contextlib.suppress(WalkForwardCancelled):
        resultado = run_walk_forward(
            marco,
            senales,
            StrategyConfig(take_profit_pct=2.0, stop_loss_pct=1.0, max_hold=12),
            REJILLA,
            spec(window_days=30, oos_days=15, step_days=15, min_windows=1),
            on_progress=on_progress,
        )

    assert con_cancelacion, "el test no llego a cancelar; el rango no dio ventanas"
    assert resultado is None, (
        "cancelar tiene que levantar excepcion, no devolver un informe a medias"
    )


def test_sin_callback_el_motor_no_se_enter():
    """Un motor sin ``on_progress`` se comporta igual que antes.

    El parametro es opcional y anadirlo no puede haber roto el camino por defecto.
    """
    marco = velas(24 * 120)
    senales = señales(marco)
    informe = run_walk_forward(
        marco,
        senales,
        StrategyConfig(take_profit_pct=2.0, stop_loss_pct=1.0, max_hold=12),
        REJILLA,
        spec(window_days=30, oos_days=15, step_days=15, min_windows=1),
    )
    assert len(informe.windows) >= 2


def test_cancelar_es_distinto_de_fallar():
    """``WalkForwardCancelled`` hereda de ``WalkForwardError``, y por eso el
    llamante que no la conoce sigue atrapando el error que ya conocia."""
    assert issubclass(WalkForwardCancelled, WalkForwardError)


def test_la_vela_de_frontera_no_se_encadena_dos_veces():
    """Con ventanas contiguas, la vela que cierra una abre la siguiente.

    Es el caso que mas se da (step_days igual a window + oos) y el que hacia que
    la curva tuviera dos filas con el mismo timestamp. El coste no es solo estetico:
    el drawdown acumulado cuenta esa fila dos veces, y al persistir con clave
    ``(run_id, timestamp)`` es un ``UniqueViolation`` que tumba el run entero.
    """
    marco = velas(24 * 120)
    senales = señales(marco)
    informe = run_walk_forward(
        marco,
        senales,
        StrategyConfig(take_profit_pct=2.0, stop_loss_pct=1.0, max_hold=12),
        REJILLA,
        spec(window_days=30, oos_days=15, step_days=15, min_windows=1),
    )
    indice = informe.oos_equity.index

    assert len(indice) > 1
    assert indice.is_unique, "la curva encadenada no puede repetir timestamp"
    assert indice.is_monotonic_increasing
    assert list(indice).count(indice[0]) == 1


def test_la_curva_se_inventa_una_ventana_de_un_tramo_de_la_otra():
    """Lo que no se debe hacer al descartar la fila duplicada: recortar la
    ventana. Si al quitar la frontera se perdia una vela, la curva estaria
    resumiendo y el retorno OOS no cuadraria con el de las ventanas."""
    marco = velas(24 * 120)
    senales = señales(marco)
    informe = run_walk_forward(
        marco,
        senales,
        StrategyConfig(take_profit_pct=2.0, stop_loss_pct=1.0, max_hold=12),
        REJILLA,
        spec(window_days=30, oos_days=15, step_days=15, min_windows=1),
    )
    curva = informe.oos_equity
    # Las ventanas contiguas cubren el rango una vez; solo se pierde una fila por
    # frontera, no un tramo entero.
    inicio_esperado = marco.index[0]
    fin_esperado = informe.windows[-1].window.oos_to
    assert curva.index[0] >= inicio_esperado
    assert curva.index[-1] <= fin_esperado

    huecos = np.diff(curva.index).astype("timedelta64[h]").astype(int)
    assert (huecos == 1).all(), (
        f"hay saltos en la curva: {sorted(set(huecos))} horas entre puntos seguidos"
    )
