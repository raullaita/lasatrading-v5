"""Tests del motor de backtesting.

El motor es pandas/numpy puro, asi que todo esto corre sin PostgreSQL ni
Celery. Los bloques van en orden de importancia:

1. **Salidas**: TP, SL, timeout, conflicto TP/SL y truncado. Cada uno con el
   indice de salida y el precio exactos calculados a mano. Un test que solo
   compruebe que no revienta no distingue un SL bien implementado de uno que
   cierra en cualquier sitio.
2. **Sin lookahead**: que la entrada sea el open de T+1 y no el close de T. Es
   el error que mas dinero cuesta en un backtest, porque produce estrategias
  oldenosas que se rompen en vivo sin dar ningun sintoma.
3. **Microestructura**: comisiones por lado, MAE/MFE, posicion corta, una sola
   posicion abierta.
4. **Metricas**: que ``end_of_data`` no contamine win rate ni profit factor.
5. **Invariantes**: validacion de configuracion, determinismo y la prohibicion
   explicita de iterar filas de pandas en el modulo.
"""

from __future__ import annotations

import ast
import time
from collections.abc import Sequence
from pathlib import Path

import app.modules.backtesting.engine as engine_module
import numpy as np
import pandas as pd
import pytest
from app.modules.backtesting.engine import (
    END_OF_DATA,
    STOP_LOSS,
    TAKE_PROFIT,
    TIMEOUT,
    BacktestResult,
    StrategyConfig,
    StrategyError,
    run_backtest,
)

pytestmark = pytest.mark.filterwarnings("error::RuntimeWarning")

START = "2024-01-01T00:00:00Z"
OHLC = tuple[float, float, float, float]


def candles_from(rows: Sequence[OHLC], start: str = START) -> pd.DataFrame:
    """DataFrame de velas con la convencion de ``app.modules.data.candles``."""
    index = pd.date_range(
        start, periods=len(rows), freq="h", tz="UTC", name="timestamp"
    )
    return pd.DataFrame(
        list(rows), columns=["open", "high", "low", "close"], index=index
    ).astype(float)


def flat(n: int, price: float = 100.0) -> pd.DataFrame:
    """``n`` velas planas: ni TP ni SL se tocan nunca."""
    return candles_from([(price, price, price, price)] * n)


def signals_from(*rows: tuple[int, str, str]) -> pd.DataFrame:
    """``(indice_de_vela, patron, direccion)`` -> DataFrame de senales."""
    # El indice debe cubrir el offset mayor, no el numero de senales: un
    # patron como (0, "A"), (8, "B") sigue siendo de dos filas.
    periods = max((o for o, _, _ in rows), default=-1) + 1
    index = pd.date_range(START, periods=periods, freq="h", tz="UTC")
    return pd.DataFrame(
        {
            "timestamp": index[[offset for offset, _, _ in rows]],
            "pattern_name": [pattern for _, pattern, _ in rows],
            "direction": [direction for _, _, direction in rows],
        }
    )


def only(result: BacktestResult):
    """Unica operacion del resultado, con un mensaje de fallo util si no hay una."""
    assert len(result.trades) == 1, f"se esperaba 1 trade, hay {len(result.trades)}"
    return result.trades[0]


# ---------------------------------------------------------------------------
# 1. Salidas
# ---------------------------------------------------------------------------
def test_take_profit_cierra_en_el_nivel_configurado() -> None:
    # Entrada en la vela 1 a 100. La vela 2 llega a 101.5, cruza el TP de 101.
    candles = candles_from(
        [
            (100, 100, 100, 100),
            (100, 100.5, 99.5, 100),
            (100, 101.5, 99.5, 101),
        ]
    )
    config = StrategyConfig(take_profit_pct=1.0, stop_loss_pct=50.0, max_hold=10)

    trade = only(
        run_backtest(
            candles, signals_from((0, "MACD_CROSS_BULLISH", "bullish")), config
        )
    )

    assert trade.exit_reason == TAKE_PROFIT
    assert trade.exit_price == pytest.approx(101.0), (
        "sale al nivel, no al maximo de la vela"
    )
    assert trade.exit_timestamp == candles.index[2]
    assert trade.bars_held == 2
    assert trade.net_pnl > 0


def test_stop_loss_cierra_en_el_nivel_configurado() -> None:
    candles = candles_from(
        [
            (100, 100, 100, 100),
            (100, 100.5, 99.5, 100),
            (100, 100.5, 98.5, 99),
        ]
    )
    config = StrategyConfig(take_profit_pct=1.0, stop_loss_pct=1.0, max_hold=10)

    trade = only(
        run_backtest(candles, signals_from((0, "RSI_EXIT_OVERSOLD", "bullish")), config)
    )

    assert trade.exit_reason == STOP_LOSS
    assert trade.exit_price == pytest.approx(99.0), (
        "sale al nivel, no al minimo de la vela"
    )
    assert trade.net_pnl < 0


def test_timeout_cierra_en_el_cierre_de_la_ultima_vela_permitida() -> None:
    candles = flat(10)
    config = StrategyConfig(take_profit_pct=1.0, stop_loss_pct=1.0, max_hold=3)

    trade = only(
        run_backtest(candles, signals_from((0, "MA_CROSS_BULLISH", "bullish")), config)
    )

    # Entra en la vela 1, agenda 3 velas (1, 2, 3) y sale al cierre de la 3.
    assert trade.exit_reason == TIMEOUT
    assert trade.exit_timestamp == candles.index[3]
    assert trade.bars_held == 3


def test_max_hold_de_uno_cierra_en_la_propia_vela_de_entrada() -> None:
    candles = flat(5)
    config = StrategyConfig(take_profit_pct=1.0, stop_loss_pct=1.0, max_hold=1)

    trade = only(run_backtest(candles, signals_from((0, "X", "bullish")), config))

    assert trade.bars_held == 1
    assert trade.exit_timestamp == candles.index[1]


def test_conflicto_take_profit_y_stop_loss_en_la_misma_vela_asume_stop_loss() -> None:
    # La vela 2 barre de 98.5 a 101.5: toca los dos niveles. Sin datos
    # intrabar es indeterminable cual fue primero, y asumir el mejor daria un
    # backtest que miente sobre si mismo.
    candles = candles_from(
        [
            (100, 100, 100, 100),
            (100, 100.5, 99.5, 100),
            (100, 101.5, 98.5, 100),
        ]
    )
    config = StrategyConfig(take_profit_pct=1.0, stop_loss_pct=1.0, max_hold=10)

    trade = only(
        run_backtest(candles, signals_from((0, "ENGULFING_BULLISH", "bullish")), config)
    )

    assert trade.exit_reason == STOP_LOSS, "ante la ambiguedad gana el peor caso"
    assert trade.exit_price == pytest.approx(99.0)
    assert trade.net_pnl < 0


def test_senal_sin_vela_posterior_se_cuenta_como_truncada() -> None:
    # La senal cae en la ultima vela: no existe T+1, luego no hay operacion.
    candles = flat(3)
    config = StrategyConfig(take_profit_pct=1.0, stop_loss_pct=1.0, max_hold=10)

    result = run_backtest(candles, signals_from((2, "X", "bullish")), config)

    assert result.trades == []
    assert result.truncated_signals == 1
    assert result.skipped_signals == 0


def test_trade_truncado_por_falta_de_velas_se_cierra_como_end_of_data() -> None:
    # 4 velas, la senal en la 0 entra en la 1 y solo le quedan 3 velas por
    # delante cuando la agenda era de 10.
    candles = flat(4)
    config = StrategyConfig(take_profit_pct=1.0, stop_loss_pct=1.0, max_hold=10)

    trade = only(run_backtest(candles, signals_from((0, "X", "bullish")), config))

    assert trade.exit_reason == END_OF_DATA
    assert trade.exit_timestamp == candles.index[3], (
        "cierra en la ultima vela disponible"
    )
    assert trade.bars_held == 3


def test_end_of_data_no_gana_por_venir_a_limite_de_vela() -> None:
    # 4 velas con max_hold=3: la agenda se cumple y es timeout, no end_of_data.
    candles = flat(4)
    config = StrategyConfig(take_profit_pct=1.0, stop_loss_pct=1.0, max_hold=3)

    assert (
        only(
            run_backtest(candles, signals_from((0, "X", "bullish")), config)
        ).exit_reason
        == TIMEOUT
    )


# ---------------------------------------------------------------------------
# 2. Sin lookahead
# ---------------------------------------------------------------------------
def test_entrada_es_el_open_de_t1_y_no_el_close_de_t0() -> None:
    # La vela de la senal cierra en 100 y la de T+1 abre en 100.6. Entrar al
    # cierre de T darieria 100; entrar al open de T+1 da 100.6.
    candles = candles_from(
        [
            (100, 100, 100, 100),
            (100.6, 100.6, 100.6, 100.6),
            (100.6, 100.6, 100.6, 100.6),
        ]
    )
    config = StrategyConfig(take_profit_pct=1.0, stop_loss_pct=50.0, max_hold=2)

    trade = only(run_backtest(candles, signals_from((0, "X", "bullish")), config))

    assert trade.entry_timestamp == candles.index[1], "entra en T+1, no en T"
    assert trade.entry_price == pytest.approx(100.6)
    assert trade.signal_timestamp == candles.index[0]


def test_entra_en_el_open_indicado_por_entry_offset() -> None:
    candles = candles_from(
        [
            (100, 100, 100, 100),
            (105, 105, 105, 105),
            (107, 107, 107, 107),
        ]
    )
    config = StrategyConfig(
        take_profit_pct=50.0, stop_loss_pct=50.0, max_hold=1, entry_offset=2
    )

    trade = only(run_backtest(candles, signals_from((0, "X", "bullish")), config))

    assert trade.entry_timestamp == candles.index[2]
    assert trade.entry_price == pytest.approx(107.0)


def test_senal_entre_velas_entra_en_la_primera_vela_posterior() -> None:
    candles = flat(4)
    # Marca temporal que no coincide con ninguna vela: medio camino entre la 0 y la 1.
    signals = pd.DataFrame(
        {
            "timestamp": [pd.Timestamp(START) + pd.Timedelta(minutes=30)],
            "pattern_name": ["X"],
            "direction": ["bullish"],
        }
    )
    config = StrategyConfig(take_profit_pct=1.0, stop_loss_pct=1.0, max_hold=2)

    assert (
        only(run_backtest(candles, signals, config)).entry_timestamp == candles.index[1]
    )


# ---------------------------------------------------------------------------
# 3. Microestructura: comisiones, MAE/MFE, cortos, una posicion
# ---------------------------------------------------------------------------
def test_comision_se_cobra_por_lado() -> None:
    candles = candles_from(
        [
            (100, 100, 100, 100),
            (100, 100.5, 99.5, 100),
            (100, 101.5, 99.5, 101),
        ]
    )
    config = StrategyConfig(take_profit_pct=1.0, stop_loss_pct=50.0, max_hold=10)

    trade = only(run_backtest(candles, signals_from((0, "X", "bullish")), config))

    quantity = 1000.0 / 100.0
    expected_entry_fee = quantity * 100.0 * (4 / 10_000)
    expected_exit_fee = quantity * 101.0 * (4 / 10_000)

    assert trade.quantity == pytest.approx(10.0)
    assert trade.fees == pytest.approx(expected_entry_fee + expected_exit_fee)
    assert trade.gross_pnl == pytest.approx(10.0)
    assert trade.net_pnl == pytest.approx(10.0 - trade.fees)
    assert trade.fees > 0


def test_comision_cero_deja_el_pnl_limpio() -> None:
    candles = candles_from(
        [(100, 100, 100, 100), (100, 100.5, 99.5, 100), (100, 101.5, 99.5, 101)]
    )
    config = StrategyConfig(
        take_profit_pct=1.0, stop_loss_pct=50.0, max_hold=10, fee_bps=0.0
    )

    trade = only(run_backtest(candles, signals_from((0, "X", "bullish")), config))

    assert trade.fees == 0.0
    assert trade.net_pnl == pytest.approx(trade.gross_pnl)


def test_comision_doblada_cuesta_el_doble() -> None:
    candles = candles_from(
        [(100, 100, 100, 100), (100, 100.5, 99.5, 100), (100, 101.5, 99.5, 101)]
    )
    signals = signals_from((0, "X", "bullish"))
    base = StrategyConfig(take_profit_pct=1.0, stop_loss_pct=50.0, max_hold=10)

    cheap = only(run_backtest(candles, signals, base))
    pricey = only(
        run_backtest(
            candles,
            signals,
            StrategyConfig(
                take_profit_pct=1.0, stop_loss_pct=50.0, max_hold=10, fee_bps=8.0
            ),
        )
    )

    assert pricey.fees == pytest.approx(cheap.fees * 2)


def test_mae_y_mfe_en_largo() -> None:
    # En las velas de posesion el precio va hasta 97 y luego hasta 101.5.
    candles = candles_from(
        [
            (100, 100, 100, 100),
            (100, 100.5, 97.0, 100),
            (100, 101.5, 99.0, 101),
        ]
    )
    config = StrategyConfig(take_profit_pct=1.0, stop_loss_pct=50.0, max_hold=10)

    trade = only(run_backtest(candles, signals_from((0, "X", "bullish")), config))

    assert trade.mae == pytest.approx(-0.03), "peor excursion: el minimo a 97"
    assert trade.mfe == pytest.approx(0.015), "mejor excursion: el maximo a 101.5"
    assert trade.mae <= 0 <= trade.mfe


def test_mae_y_mfe_en_corto() -> None:
    # En corto la excursion adversa es que suba, y la favorable que baje.
    candles = candles_from(
        [
            (100, 100, 100, 100),
            (100, 100.5, 99.5, 100),  # el minimo a 99.5 aun no toca el TP
            (100, 101.5, 97.0, 99),  # aqui si: TP a 99, con un minimo a 97
        ]
    )
    config = StrategyConfig(take_profit_pct=1.0, stop_loss_pct=50.0, max_hold=10)

    trade = only(run_backtest(candles, signals_from((0, "X", "bearish")), config))

    assert trade.direction == "short"
    assert trade.mfe == pytest.approx(0.03), "el minimo a 97 esprofit para un corto"
    assert trade.mae == pytest.approx(-0.015), "el maximo a 101.5 es lo contrario"


def test_posicion_corta_gana_cuando_el_precio_baja() -> None:
    candles = candles_from(
        [
            (100, 100, 100, 100),
            (100, 100.5, 99.5, 100),
            (100, 100.5, 98.5, 99),
        ]
    )
    config = StrategyConfig(take_profit_pct=1.0, stop_loss_pct=1.0, max_hold=10)

    trade = only(
        run_backtest(candles, signals_from((0, "ENGULFING_BEARISH", "bearish")), config)
    )

    assert trade.exit_reason == TAKE_PROFIT
    assert trade.exit_price == pytest.approx(99.0)
    assert trade.gross_pnl == pytest.approx(10.0), (
        "10 unidades vendidas a 100 y recompradas a 99"
    )
    assert trade.net_pnl > 0


def test_posicion_corta_pierde_cuando_el_precio_sube() -> None:
    candles = candles_from(
        [
            (100, 100, 100, 100),
            (100, 100.5, 99.5, 100),
            (100, 102.0, 99.5, 101),
        ]
    )
    config = StrategyConfig(take_profit_pct=1.0, stop_loss_pct=1.0, max_hold=10)

    trade = only(run_backtest(candles, signals_from((0, "X", "bearish")), config))

    assert trade.exit_reason == STOP_LOSS
    assert trade.exit_price == pytest.approx(101.0)
    assert trade.gross_pnl < 0


def test_allow_short_false_ignora_las_senales_bajistas() -> None:
    candles = candles_from(
        [(100, 100, 100, 100), (100, 100.5, 99.5, 100), (100, 100.5, 98.5, 99)]
    )
    config = StrategyConfig(
        take_profit_pct=1.0, stop_loss_pct=1.0, max_hold=10, allow_short=False
    )

    result = run_backtest(candles, signals_from((0, "X", "bearish")), config)

    assert result.trades == []
    assert result.skipped_signals == 1


def test_una_sola_posicion_abierta_y_las_demas_se_informan_como_saltadas() -> None:
    # La primera senal entra en la vela 1 y dura 5 velas, asi que ocupa hasta la
    # 5. La segunda (entrada en la 3) y la tercera (entrada en la 7) se solapan.
    candles = flat(20)
    config = StrategyConfig(take_profit_pct=1.0, stop_loss_pct=1.0, max_hold=5)
    signals = signals_from(
        (0, "A", "bullish"), (2, "B", "bullish"), (6, "C", "bullish")
    )

    result = run_backtest(candles, signals, config)

    assert [t.pattern_name for t in result.trades] == ["A", "C"]
    assert result.skipped_signals == 1, "B se salto por posicion ocupada"
    assert [t.signal_timestamp for t in result.trades] == [
        candles.index[0],
        candles.index[6],
    ]
    assert result.trades[0].exit_timestamp == candles.index[5]
    assert result.trades[1].entry_timestamp == candles.index[7], (
        "C entra justo tras liberarse"
    )


def test_orden_de_salida_es_indiferente() -> None:
    # Las senales llegan desordenadas: el resultado no debe depender de eso.
    candles = candles_from(
        [
            (100, 100, 100, 100),
            (100, 100.5, 99.5, 100),
            (100, 101.5, 99.5, 101),
            (100, 102.5, 99.5, 102),
        ]
    )
    config = StrategyConfig(take_profit_pct=1.0, stop_loss_pct=50.0, max_hold=10)
    signals = signals_from((2, "B", "bullish"), (0, "A", "bullish"))

    result = run_backtest(candles, signals, config)

    assert [t.pattern_name for t in result.trades] == ["A", "B"]
    assert [t.signal_timestamp for t in result.trades] == [
        candles.index[0],
        candles.index[2],
    ]


def test_stop_loss_en_la_vela_de_entrada_hace_saltar_la_senal() -> None:
    # En corto, la vela de entrada ya barre por encima del stop. Entrar ahi
    # significa perder dinero antes de poder decidir nada, asi que se descarta.
    candles = candles_from(
        [
            (100, 100, 100, 100),
            (100, 101.5, 99.5, 100),
            (100, 100.5, 99.5, 100),
        ]
    )
    config = StrategyConfig(take_profit_pct=1.0, stop_loss_pct=1.0, max_hold=10)

    result = run_backtest(candles, signals_from((0, "X", "bearish")), config)

    assert result.trades == []
    assert result.skipped_signals == 1


# ---------------------------------------------------------------------------
# 4. Metricas
# ---------------------------------------------------------------------------
def test_end_of_data_no_entra_en_win_rate_ni_en_profit_factor() -> None:
    # 20 velas planas. La primera senal gana el TP. La ultima queda truncada y
    # sale con las comisiones perdidas: contarla rebajaria el acierto por un
    # motivo que no dice nada del patron.
    candles = candles_from(
        [
            (100, 100, 100, 100),
            (100, 100.5, 99.5, 100),
            (100, 101.5, 99.5, 101),
        ]
        + [(101, 101, 101, 101)] * 17
    )
    config = StrategyConfig(take_profit_pct=1.0, stop_loss_pct=50.0, max_hold=10)
    signals = signals_from((0, "GANADORA", "bullish"), (17, "TRUNCADA", "bullish"))

    result = run_backtest(candles, signals, config)

    assert len(result.trades) == 2
    assert result.trades[1].exit_reason == END_OF_DATA
    assert result.metrics["trades_evaluated"] == 1, "solo la que llego a cerrar"
    assert result.metrics["win_rate"] == pytest.approx(1.0), "sin la truncada, 1 de 1"
    # Sin perdedoras el factor de beneficio es infinito, y se representa como
    # None. Lo relevante aqui es que la truncada no lo altera.
    assert result.metrics["profit_factor"] is None
    assert result.metrics["total_trades"] == 2, (
        "el total si las incluye, para poder auditar"
    )


def test_win_rate_es_la_proporcion_de_ganadoras_sobre_cerradas() -> None:
    candles = candles_from(
        [
            (100, 100, 100, 100),
            (100, 100.5, 99.5, 100),
            (100, 101.5, 99.5, 101),  # TP largo
            (101, 101.5, 100.5, 101),  # espera
            (101, 101.5, 100.5, 101),
            (101, 101.5, 99.0, 100),  # SL largo
        ]
    )
    config = StrategyConfig(take_profit_pct=1.0, stop_loss_pct=1.0, max_hold=3)
    signals = signals_from((0, "GANA", "bullish"), (4, "PIERDE", "bullish"))

    result = run_backtest(candles, signals, config)

    assert [t.exit_reason for t in result.trades] == [TAKE_PROFIT, STOP_LOSS]
    assert result.metrics["trades_evaluated"] == 2
    assert result.metrics["win_rate"] == pytest.approx(0.5)
    assert result.metrics["profit_factor"] == pytest.approx(
        result.trades[0].net_pnl / abs(result.trades[1].net_pnl)
    )


def test_profit_factor_es_none_solo_sin_perdedoras() -> None:
    """Distinguir "infinito" de "sin datos" importa: la UI los muestra distinto."""
    ganadora = candles_from(
        [
            (100, 100, 100, 100),
            (100, 100.5, 99.5, 100),
            (100, 102.0, 99.5, 102),
        ]
    )
    perdedora = candles_from(
        [
            (100, 100, 100, 100),
            (100, 100.5, 99.5, 100),
            (100, 100.5, 98.0, 99),  # SL a 99
        ]
    )
    config = StrategyConfig(take_profit_pct=2.0, stop_loss_pct=1.0, max_hold=10)

    solo_ganadora = run_backtest(ganadora, signals_from((0, "G", "bullish")), config)
    assert solo_ganadora.metrics["trades_evaluated"] == 1
    assert solo_ganadora.metrics["profit_factor"] is None, "infinito, no indefinido"

    con_perdedora = run_backtest(perdedora, signals_from((0, "P", "bullish")), config)
    assert con_perdedora.metrics["trades_evaluated"] == 1
    assert con_perdedora.metrics["profit_factor"] == pytest.approx(0.0)

    sin_datos = run_backtest(flat(4), signals_from(), config)
    assert sin_datos.metrics["trades_evaluated"] == 0
    assert sin_datos.metrics["profit_factor"] is None, (
        "tambien None, pero por falta de datos"
    )


def test_curva_de_equity_es_mark_to_market_y_no_solo_realizado() -> None:
    # La posicion se va 10% en contra en la vela 2 antes de salir a beneficio.
    # Con equity solo realizada el drawdown no se veria hasta el cierre.
    candles = candles_from(
        [
            (100, 100, 100, 100),
            (100, 100.5, 99.5, 100),
            (100, 100.5, 90.0, 90),  # -10% a mitad de posesion
            (100, 101.5, 99.5, 101),  # TP
        ]
    )
    config = StrategyConfig(take_profit_pct=1.0, stop_loss_pct=50.0, max_hold=10)

    result = run_backtest(candles, signals_from((0, "X", "bullish")), config)
    equity = result.equity

    assert equity is not None
    assert len(equity) == len(candles)
    assert equity["equity"].iloc[0] == pytest.approx(1000.0), (
        "antes de entrar hay capital plano"
    )
    assert equity["equity"].iloc[2] == pytest.approx(1000.0 - 100.0 - 0.4), (
        "mark-to-market en la vela 2"
    )
    assert equity["equity"].iloc[-1] == pytest.approx(result.trades[0].equity_after)
    assert result.metrics["max_drawdown_pct"] == pytest.approx(10.04, abs=1e-6)
    assert result.metrics["net_pnl"] > 0, "la operacion gano pese al drawdown"


def test_equity_final_coincide_con_la_suma_de_los_pnl() -> None:
    candles = flat(30)
    config = StrategyConfig(
        take_profit_pct=1.0, stop_loss_pct=1.0, max_hold=2, fee_bps=0.0
    )
    signals = signals_from(
        (0, "A", "bullish"), (6, "B", "bearish"), (12, "C", "bullish")
    )

    result = run_backtest(candles, signals, config)
    suma = sum(t.net_pnl for t in result.trades)

    assert result.metrics["equity_final"] == pytest.approx(1000.0 + suma)


def test_una_sola_operacion_aumenta_el_capital_en_su_proporcion() -> None:
    candles = candles_from(
        [
            (100, 100, 100, 100),
            (100, 100.5, 99.5, 100),
            (100, 102.0, 99.5, 102),  # +2% sin comisiones
        ]
    )
    config = StrategyConfig(
        take_profit_pct=2.0, stop_loss_pct=50.0, max_hold=10, fee_bps=0.0
    )

    result = run_backtest(candles, signals_from((0, "X", "bullish")), config)

    assert result.metrics["equity_final"] == pytest.approx(1020.0)
    assert result.metrics["total_return_pct"] == pytest.approx(2.0)


def test_sin_senales_no_hay_metricas_enganosas() -> None:
    result = run_backtest(flat(10), signals_from(), StrategyConfig())

    assert result.trades == []
    assert result.metrics["win_rate"] is None
    assert result.metrics["profit_factor"] is None
    assert result.metrics["equity_final"] == pytest.approx(1000.0)
    assert result.metrics["max_drawdown_pct"] == pytest.approx(0.0)


def test_velas_vacias_no_revienta() -> None:
    result = run_backtest(
        candles_from([]), signals_from((0, "X", "bullish")), StrategyConfig()
    )

    assert result.trades == []
    assert result.equity is not None
    assert result.equity.empty
    assert result.metrics["equity_final"] == pytest.approx(1000.0)


# ---------------------------------------------------------------------------
# 5. Invariantes
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("kwargs", "motivo"),
    [
        ({"max_hold": 0}, "max_hold"),
        ({"entry_offset": 0}, "lookahead"),
        ({"take_profit_pct": None, "stop_loss_pct": None}, "forma de cerrar"),
        ({"use_fraction": 0.0}, "use_fraction"),
        ({"use_fraction": 1.5}, "use_fraction"),
        ({"initial_capital": 0.0}, "initial_capital"),
        ({"take_profit_pct": 0.0}, "take_profit_pct"),
        ({"stop_loss_pct": -1.0}, "stop_loss_pct"),
        ({"fee_bps": -1.0}, "fee_bps"),
    ],
)
def test_configuracion_invalida_falla_antes_de_simular(
    kwargs: dict, motivo: str
) -> None:
    with pytest.raises(StrategyError, match=motivo):
        StrategyConfig(**kwargs)


def test_la_configuracion_se_serializa_como_json() -> None:
    payload = StrategyConfig(take_profit_pct=1.5, max_hold=12).as_dict()

    assert payload["take_profit_pct"] == 1.5
    assert payload["max_hold"] == 12
    assert set(payload) == {
        "take_profit_pct",
        "stop_loss_pct",
        "max_hold",
        "fee_bps",
        "initial_capital",
        "use_fraction",
        "entry_offset",
        "allow_short",
    }


def test_la_simulacion_es_determinista() -> None:
    candles, signals = flat(40), signals_from((0, "A", "bullish"), (8, "B", "bearish"))
    config = StrategyConfig(take_profit_pct=0.5, stop_loss_pct=0.5, max_hold=6)

    primero, segundo = (
        run_backtest(candles, signals, config),
        run_backtest(candles, signals, config),
    )

    assert [t.net_pnl for t in primero.trades] == [t.net_pnl for t in segundo.trades]
    pd.testing.assert_series_equal(primero.equity["equity"], segundo.equity["equity"])


def test_velas_no_ordenadas_se_rechazan() -> None:
    candles = flat(5).iloc[::-1]
    with pytest.raises(StrategyError, match="monotono"):
        run_backtest(candles, signals_from((0, "X", "bullish")), StrategyConfig())


def test_columnas_faltantes_se_rechazan() -> None:
    with pytest.raises(StrategyError, match="Falta la columna"):
        run_backtest(
            flat(3).drop(columns=["high"]),
            signals_from((0, "X", "bullish")),
            StrategyConfig(),
        )

    with pytest.raises(StrategyError, match="Faltan columnas"):
        run_backtest(
            flat(3),
            pd.DataFrame({"timestamp": [pd.Timestamp(START)]}),
            StrategyConfig(),
        )


def test_direcciones_desconocidas_se_rechazan() -> None:
    signals = pd.DataFrame(
        {
            "timestamp": [pd.Timestamp(START)],
            "pattern_name": ["X"],
            "direction": ["sideways"],
        }
    )
    with pytest.raises(StrategyError, match="Direcciones no soportadas"):
        run_backtest(flat(3), signals, StrategyConfig())


def test_el_motor_no_itera_filas_de_pandas() -> None:
    """El requisito de vectorizacion, comprobado sobre el AST y no a ojo."""
    source = Path(engine_module.__file__).read_text(encoding="utf-8")
    prohibido = {"iterrows", "itertuples", "apply", "map"}
    encontrados: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in prohibido:
                # ``.map`` sobre una serie es tan iterativo como ``itertuples``.
                if isinstance(func.value, ast.Name) and func.value.id == "pd":
                    continue
                encontrados.add(func.attr)
    assert not encontrados, f"el motor itera filas con {sorted(encontrados)}"


def test_los_2_812_senales_reales_caben_en_el_presupuesto() -> None:
    """El tamano del dataset de referencia: 8.781 velas y 2.812 senales."""
    rng = np.random.default_rng(20240101)
    closes = 100.0 * np.exp(np.cumsum(rng.normal(0, 0.004, 8_781)))
    index = pd.date_range(START, periods=8_781, freq="h", tz="UTC", name="timestamp")
    opens = np.concatenate([[closes[0]], closes[:-1]])
    spread = rng.uniform(0.001, 0.01, 8_781)
    candles = pd.DataFrame(
        {
            "open": opens,
            "high": np.maximum(opens, closes) * (1 + spread),
            "low": np.minimum(opens, closes) * (1 - spread),
            "close": closes,
        },
        index=index,
    )
    posiciones = rng.choice(8_779, 2_812, replace=False)
    signals = pd.DataFrame(
        {
            "timestamp": index[posiciones],
            "pattern_name": [f"P{i % 8}" for i in range(2_812)],
            "direction": rng.choice(["bullish", "bearish"], 2_812),
        }
    )
    config = StrategyConfig(take_profit_pct=2.0, stop_loss_pct=1.0, max_hold=24)

    inicio = time.perf_counter()
    result = run_backtest(candles, signals, config)
    elapsed = time.perf_counter() - inicio

    assert result.trades, "una corrida de 2.812 senales debe producir operaciones"
    assert elapsed < 5.0, f"tardo {elapsed:.2f}s, el presupuesto es 5s"
    assert result.skipped_signals > 0, "con max_hold=24 tiene que haber solapes"
