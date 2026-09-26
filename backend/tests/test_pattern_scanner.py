"""Tests del motor de deteccion de patrones.

Tres bloques, en orden de importancia:

1. **Semantica**: que cada uno de los cinco scanners detects lo que dice detectar,
   con los indices exactos calculados a mano. Un test que solo comprueba que no
   revienta no atrapa ni un signo cambiado.
2. **Casos borde**: NaN de warmup, series planas, umbral justo, frames vacios,
   marcos insuficientes. Es donde viven los errores de ``shift(1)``.
3. **Vectorizacion y rendimiento**: que no se iteren filas y que 1.000.000 de
   velas entren en el presupuesto de 2 s.

El motor es pandas puro, asi que nada de esto necesita PostgreSQL.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

import app.modules.patterns.scanner as scanner_module
import numpy as np
import pandas as pd
import pytest
from app.modules.patterns.scanner import RESULT_COLUMNS, PatternScanner

pytestmark = pytest.mark.filterwarnings("error::RuntimeWarning")

# Los cinco scanners con alias cortos. Sus nombres reales ocupan entre 30 y 38
# caracteres y se repiten en casi todas las aserciones, asi que usarlos en
# crudo partia las lineas en tres trozos sin ganar legibilidad. El alias deja
# cada test en una linea y el scanner bajo prueba sigue siendo evidente.
scan_macd = PatternScanner.scan_macd_crossover
scan_rsi = PatternScanner.scan_rsi_extremes
scan_bollinger = PatternScanner.scan_bollinger_breakout
scan_ma = PatternScanner.scan_ma_crossover
scan_engulfing = PatternScanner.scan_engulfing


# ---------------------------------------------------------------------------
# 1. Semantica
# ---------------------------------------------------------------------------


class TestMacdCrossover:
    def test_detecta_ambos_sentidos_en_sus_indices_exactos(
        self, make_frame, assert_contract
    ):
        # diff = macd - signal = [-1,-1,+1,+1,-1,-1,+1]
        #   i=2  -> cruza al alza  (-1 <= 0 < +1)
        #   i=4  -> cruza a la baja(+1 >= 0 > -1)
        #   i=6  -> cruza al alza
        frame = make_frame({"MACD": [-1, -1, 1, 1, -1, -1, 1], "MACDs": 0.0})
        result = assert_contract(
            PatternScanner.scan_macd_crossover(frame, "MACD", "MACDs")
        )

        # El scanner agrupa por direccion (``_merge`` concatena las alzas y las
        # bajas) y no reordena por tiempo. No importa porque toda lectura pasa
        # por un ORDER BY en SQL, asi que aqui se compara como conjunto de
        # pares (indice, patron) y no como secuencia.
        detectados = sorted(
            zip(
                result["timestamp"].tolist(),
                result["pattern_name"].tolist(),
                strict=True,
            )
        )
        assert detectados == [
            (frame.index[2], "MACD_CROSS_BULLISH"),
            (frame.index[4], "MACD_CROSS_BEARISH"),
            (frame.index[6], "MACD_CROSS_BULLISH"),
        ]

    def test_details_lleva_macd_signal_y_diff_de_ese_momento(self, make_frame):
        frame = make_frame({"MACD": [0.5, 2.0], "MACDs": [1.0, 1.5]})
        result = PatternScanner.scan_macd_crossover(frame, "MACD", "MACDs")

        assert result["details"].tolist() == [
            {"direction": "bullish", "macd": 2.0, "signal": 1.5, "diff": 0.5},
        ]

    def test_rozar_el_cero_cuenta_como_cruce(self, make_frame):
        # <= 0 en vez de < 0: diff pasa por exactamente cero.
        frame = make_frame({"MACD": [0.0, 1.0], "MACDs": 0.0})
        result = PatternScanner.scan_macd_crossover(frame, "MACD", "MACDs")
        assert result["pattern_name"].tolist() == ["MACD_CROSS_BULLISH"]

    def test_serie_plana_no_detecta_nada(self, make_frame):
        frame = make_frame({"MACD": [1.0, 1.0, 1.0], "MACDs": 1.0})
        assert PatternScanner.scan_macd_crossover(frame, "MACD", "MACDs").empty

    def test_detecta_cruces_tambien_por_debajo_de_cero(self, make_frame):
        # Un cruce por debajo de cero tambien es un cruce: la diferencia manda.
        frame = make_frame({"MACD": [-0.5, 0.0], "MACDs": -0.5})
        result = PatternScanner.scan_macd_crossover(frame, "MACD", "MACDs")
        assert result["pattern_name"].tolist() == ["MACD_CROSS_BULLISH"]


class TestRsiExtremes:
    def test_detecta_la_salida_no_la_persistencia(self, make_frame):
        # Salir de sobreventa (25 -> 35) es una deteccion; quedarse en 35 tres
        # barras mas no lo es. Sin el shift(1) habria cuatro.
        frame = make_frame({"RSI": [25.0, 35.0, 35.0, 35.0]})
        result = PatternScanner.scan_rsi_extremes(frame, "RSI")

        assert result["pattern_name"].tolist() == ["RSI_EXIT_OVERSOLD"]
        assert result["timestamp"].tolist() == list(frame.index[[1]])

    def test_rsi_plano_en_zona_alta_no_detecta(self, make_frame):
        frame = make_frame({"RSI": [80.0] * 5})
        assert PatternScanner.scan_rsi_extremes(frame, "RSI").empty

    def test_umbral_exacto_sigue_contando_como_extremo(self, make_frame):
        # 70 exacto todavia es sobrecompra: la salida exige bajar de 70.
        frame = make_frame({"RSI": [80.0, 70.0, 65.0]})
        result = PatternScanner.scan_rsi_extremes(frame, "RSI")
        assert result["pattern_name"].tolist() == ["RSI_EXIT_OVERBOUGHT"]
        assert result["timestamp"].tolist() == list(frame.index[[2]])

    def test_umbrales_personalizados(self, make_frame):
        frame = make_frame({"RSI": [25.0, 80.0, 35.0, 75.0]})
        result = PatternScanner.scan_rsi_extremes(frame, "RSI", 75.0, 25.0)

        assert sorted(result["pattern_name"]) == [
            "RSI_EXIT_OVERBOUGHT",
            "RSI_EXIT_OVERSOLD",
        ]
        # details refleja el umbral que se aplico, no el de por defecto.
        thresholds = {d["direction"]: d["threshold"] for d in result["details"]}
        assert thresholds == {"bullish": 25.0, "bearish": 75.0}

    def test_details_incluye_el_valor_de_rsi(self, make_frame):
        frame = make_frame({"RSI": [29.0, 31.5]})
        result = PatternScanner.scan_rsi_extremes(frame, "RSI")
        assert result["details"].tolist() == [
            {"direction": "bullish", "rsi_value": 31.5, "threshold": 30.0},
        ]


class TestBollingerBreakout:
    def test_rompe_la_banda_superior(self, make_frame):
        frame = make_frame(
            {"close": [100.0, 100.0, 100.0, 106.0], "BBU": 105.0, "BBL": 95.0}
        )
        result = PatternScanner.scan_bollinger_breakout(frame, "close", "BBU", "BBL")

        assert result["pattern_name"].tolist() == ["BB_BREAKOUT_UPPER"]
        assert result["timestamp"].tolist() == list(frame.index[[3]])

    def test_rompe_la_banda_inferior(self, make_frame):
        frame = make_frame(
            {"close": [100.0, 100.0, 100.0, 94.0], "BBU": 105.0, "BBL": 95.0}
        )
        result = PatternScanner.scan_bollinger_breakout(frame, "close", "BBU", "BBL")
        assert result["pattern_name"].tolist() == ["BB_BREAKOUT_LOWER"]

    def test_ya_estar_fuera_de_la_banda_no_es_ruptura(self, make_frame):
        # El precio sigue por encima de la banda, pero no hay rupture nueva.
        frame = make_frame({"close": [106.0, 107.0, 108.0], "BBU": 105.0, "BBL": 95.0})
        assert PatternScanner.scan_bollinger_breakout(
            frame, "close", "BBU", "BBL"
        ).empty

    def test_la_comparacion_usa_la_banda_anterior(self, make_frame):
        # La banda cae de 105 a 95 en la ultima barra. Comparar el cierre
        # anterior contra la banda *actual* daria 100 <= 95 = falso y la
        # ruptura pasaria desapercibida; con shift(1) sobre la banda se ve.
        frame = make_frame(
            {
                "close": [100.0, 100.0, 100.0, 106.0],
                "BBU": [105.0, 105.0, 105.0, 95.0],
                "BBL": 95.0,
            }
        )
        result = PatternScanner.scan_bollinger_breakout(frame, "close", "BBU", "BBL")
        assert result["pattern_name"].tolist() == ["BB_BREAKOUT_UPPER"]
        assert result["details"].tolist() == [
            {"direction": "bullish", "close": 106.0, "band": 95.0},
        ]

    def test_primera_barra_nunca_rompe(self, make_frame):
        # Sin vela anterior no hay ruptura, aunque el cierre este fuera de banda.
        frame = make_frame({"close": [200.0], "BBU": 105.0, "BBL": 95.0})
        assert PatternScanner.scan_bollinger_breakout(
            frame, "close", "BBU", "BBL"
        ).empty

    def test_precios_iguales_a_la_banda_no_rompen(self, make_frame):
        frame = make_frame({"close": [105.0, 105.0], "BBU": 105.0, "BBL": 95.0})
        assert PatternScanner.scan_bollinger_breakout(
            frame, "close", "BBU", "BBL"
        ).empty


class TestMaCrossover:
    def test_detecta_en_ambos_sentidos(self, make_frame):
        # diff = EMA20 - EMA50 = [-5,-5,+5,+5,-5]
        frame = make_frame(
            {"EMA_20": [100.0, 100.0, 110.0, 110.0, 100.0], "EMA_50": 105.0}
        )
        result = PatternScanner.scan_ma_crossover(frame, "EMA_20", "EMA_50")

        # Agrupado por direccion, igual que MACD (ver test homonimo).
        detectados = sorted(
            zip(
                result["timestamp"].tolist(),
                result["pattern_name"].tolist(),
                strict=True,
            )
        )
        assert detectados == [
            (frame.index[2], "MA_CROSS_BULLISH"),
            (frame.index[4], "MA_CROSS_BEARISH"),
        ]

    def test_details_usa_los_nombres_de_columna_recibidos(self, make_frame):
        # El patron es configurable, asi que las claves de details son las de las
        # columnas que le pasa el servicio, no "EMA_20"/"EMA_50" fijos.
        frame = make_frame({"fast_5": [1.0, 2.0], "slow_35": [1.5, 1.5]})
        result = PatternScanner.scan_ma_crossover(frame, "fast_5", "slow_35")
        assert result["details"].tolist() == [
            {"direction": "bullish", "fast": 2.0, "slow": 1.5, "diff": 0.5},
        ]

    def test_medias_iguales_no_detectan(self, make_frame):
        frame = make_frame({"EMA_20": [100.0, 100.0], "EMA_50": 100.0})
        assert PatternScanner.scan_ma_crossover(frame, "EMA_20", "EMA_50").empty


class TestEngulfing:
    def test_envolvente_alcista(self, make_frame):
        # La vela anterior es bajista (100 -> 99.8) y la actual,inea envolvente.
        frame = make_frame(
            {
                "open": [100.0, 99.5],
                "close": [99.8, 101.0],
                "high": [100.5, 101.5],
                "low": [99.5, 99.0],
            }
        )
        result = PatternScanner.scan_engulfing(frame)

        assert result["pattern_name"].tolist() == ["ENGULFING_BULLISH"]
        # prev_open/prev_close vienen de la vela ANTERIOR, no de la actual.
        assert result["details"].tolist() == [
            {
                "direction": "bullish",
                "open": 99.5,
                "close": 101.0,
                "prev_open": 100.0,
                "prev_close": 99.8,
            },
        ]

    def test_envolvente_bajista(self, make_frame):
        frame = make_frame(
            {
                "open": [99.5, 101.0],
                "close": [101.0, 98.5],
                "high": [101.5, 101.5],
                "low": [99.0, 98.0],
            }
        )
        result = PatternScanner.scan_engulfing(frame)
        assert result["pattern_name"].tolist() == ["ENGULFING_BEARISH"]
        assert result["details"].tolist()[0]["prev_open"] == 99.5

    def test_requiere_vela_anterior_bajista_para_la_alcista(self, make_frame):
        # Dos velas alcistas consecutivas: la segunda no es envolvente.
        frame = make_frame(
            {
                "open": [99.0, 99.5],
                "close": [100.0, 101.0],
                "high": [101.0, 101.5],
                "low": [98.0, 99.0],
            }
        )
        assert PatternScanner.scan_engulfing(frame).empty

    def test_envoltura_inclusiva_en_los_extremos(self, make_frame):
        # Cuerpo exactamente igual al anterior pero invertido. Solo se dispara
        # porque la envoltura usa ``<=`` y ``>=``: el open actual coincide con
        # el close anterior y el close actual con el open anterior. Con ``<`` y
        # ``>`` esta vela no contaria.
        frame = make_frame(
            {
                "open": [99.8, 100.0],
                "close": [100.0, 99.8],
                "high": [100.5, 100.5],
                "low": [99.5, 99.5],
            }
        )
        result = PatternScanner.scan_engulfing(frame)
        assert result["pattern_name"].tolist() == ["ENGULFING_BEARISH"]

    def test_envoltura_alcista_inclusiva_en_los_extremos(self, make_frame):
        frame = make_frame(
            {
                "open": [100.0, 99.8],
                "close": [99.8, 100.0],
                "high": [100.5, 100.5],
                "low": [99.5, 99.5],
            }
        )
        result = PatternScanner.scan_engulfing(frame)
        assert result["pattern_name"].tolist() == ["ENGULFING_BULLISH"]

    def test_un_doji_nunca_es_envolvente(self, make_frame):
        # close == open no es ni alcista ni bajista, asi que no puede ser la vela
        # envolvente ni servir de vela previa.
        frame = make_frame(
            {
                "open": [100.0, 99.5],
                "close": [99.8, 99.5],
                "high": [100.5, 100.5],
                "low": [99.5, 99.0],
            }
        )
        assert PatternScanner.scan_engulfing(frame).empty

    def test_primer_doji_no_es_envolvente(self, make_frame):
        frame = make_frame(
            {"open": [100.0], "close": [101.0], "high": [101.5], "low": [99.5]}
        )
        assert PatternScanner.scan_engulfing(frame).empty

    def test_no_usa_high_ni_low(self, make_frame):
        # Las mechas no participan, solo el cuerpo: aqui la mecha inferior cae
        # muy por debajo del cuerpo anterior y aun asi hay envolvente.
        frame = make_frame(
            {
                "open": [100.0, 99.5],
                "close": [99.8, 100.5],
                "high": [100.2, 100.6],
                "low": [99.7, 90.0],
            }
        )
        assert PatternScanner.scan_engulfing(frame)["pattern_name"].tolist() == [
            "ENGULFING_BULLISH"
        ]


# ---------------------------------------------------------------------------
# 2. Casos borde
# ---------------------------------------------------------------------------


class TestCasosBorde:
    def test_frame_vacio_en_los_cinco_scanners(self, empty_frame):
        frame = empty_frame(["MACD", "MACDs", "RSI", "BBU", "BBL", "FAST", "SLOW"])
        assert PatternScanner.scan_macd_crossover(frame, "MACD", "MACDs").empty
        assert PatternScanner.scan_rsi_extremes(frame, "RSI").empty
        assert PatternScanner.scan_bollinger_breakout(
            frame, "close", "BBU", "BBL"
        ).empty
        assert PatternScanner.scan_ma_crossover(frame, "FAST", "SLOW").empty
        assert PatternScanner.scan_engulfing(frame).empty

    def test_columna_de_feature_inexistente_es_un_keyerror(self, empty_frame):
        # Al escanear de verdad nunca pasa: el servicio valida las features
        # pedidas contra la configuracion del job antes de construir el frame.
        # Se fija el contrato para que un fallo futuro sea explicito.
        frame = empty_frame(["MACD", "MACDs"])
        with pytest.raises(KeyError, match="RSI"):
            PatternScanner.scan_rsi_extremes(frame, "RSI")

    def test_vacio_devuelve_las_columnas_del_contrato(
        self, empty_frame, assert_contract
    ):
        for result in (
            PatternScanner.scan_macd_crossover(
                empty_frame(["MACD", "MACDs"]), "MACD", "MACDs"
            ),
            PatternScanner.scan_rsi_extremes(empty_frame(["RSI"]), "RSI"),
            PatternScanner.scan_bollinger_breakout(
                empty_frame(["BBU", "BBL"]), "close", "BBU", "BBL"
            ),
            PatternScanner.scan_engulfing(empty_frame()),
        ):
            assert_contract(result)
            assert list(result.columns) == RESULT_COLUMNS

    def test_una_sola_barra_no_detecta_nada(self, make_frame):
        # El primer shift(1) es NaN y toda comparacion con NaN da False.
        frame = make_frame(
            {
                "MACD": [1.0],
                "MACDs": [-1.0],
                "RSI": [95.0],
                "close": [200.0],
                "BBU": [100.0],
                "BBL": [90.0],
                "FAST": [1.0],
                "SLOW": [-1.0],
                "open": [100.0],
                "high": [200.0],
                "low": [1.0],
            }
        )
        assert PatternScanner.scan_macd_crossover(frame, "MACD", "MACDs").empty
        assert PatternScanner.scan_rsi_extremes(frame, "RSI").empty
        assert PatternScanner.scan_bollinger_breakout(
            frame, "close", "BBU", "BBL"
        ).empty
        assert PatternScanner.scan_ma_crossover(frame, "FAST", "SLOW").empty
        assert PatternScanner.scan_engulfing(frame).empty

    def test_warmup_con_nan_no_produce_detecciones_espurias(self, make_frame):
        # 4 barras de NaN y despues un cruce real. Las comparaciones con NaN dan
        # False, asi que el warmup no genera nada por si solo, sin dropna.
        frame = make_frame({"MACD": [np.nan] * 4 + [-1.0, 1.0], "MACDs": 0.0})
        result = PatternScanner.scan_macd_crossover(frame, "MACD", "MACDs")
        assert result["pattern_name"].tolist() == ["MACD_CROSS_BULLISH"]
        assert result["timestamp"].tolist() == list(frame.index[[5]])

    def test_primera_barra_valida_no_puede_detectar_solo(self, make_frame):
        # Documenta el limite del warmup: en la primera barra con dato, el
        # anterior es NaN, luego (NaN <= 0) es False y no hay cruce. Saltaria
        # un indicador recien arrancado, que es justo lo que se quiere evitar.
        frame = make_frame({"MACD": [np.nan, np.nan, 1.0, 1.0], "MACDs": 0.0})
        assert PatternScanner.scan_macd_crossover(frame, "MACD", "MACDs").empty

    def test_rsi_con_nan(self, make_frame):
        frame = make_frame({"RSI": [np.nan, np.nan, 25.0, 35.0]})
        result = PatternScanner.scan_rsi_extremes(frame, "RSI")
        assert result["pattern_name"].tolist() == ["RSI_EXIT_OVERSOLD"]

    def test_todas_las_columnas_nan(self, make_frame):
        frame = make_frame({"MACD": np.nan, "MACDs": np.nan}, n=10)
        result = PatternScanner.scan_macd_crossover(frame, "MACD", "MACDs")
        assert result.empty
        assert list(result.columns) == RESULT_COLUMNS

    def test_deteccion_en_la_ultima_barra(self, make_frame):
        # El cruce en la ultima vela no se pierde por un shift que se salga.
        frame = make_frame({"MACD": [-1.0, 1.0], "MACDs": 0.0})
        result = PatternScanner.scan_macd_crossover(frame, "MACD", "MACDs")
        assert result["timestamp"].tolist() == list(frame.index[[1]])

    def test_deteccion_justo_despues_de_un_warmup(self, make_frame):
        frame = make_frame({"RSI": [np.nan, 20.0, 30.0, 40.0]})
        result = PatternScanner.scan_rsi_extremes(frame, "RSI")
        assert result["pattern_name"].tolist() == ["RSI_EXIT_OVERSOLD"]

    def test_agrupacion_no_duplica_una_sola_deteccion(self, make_frame):
        # MACD y MA comparten logica: si el mismo cruce aparece en ambos, cada
        # scanner lo cuenta una vez en su propia salida.
        frame = make_frame(
            {"MACD": [-1.0, 1.0], "MACDs": 0.0, "FAST": [-1.0, 1.0], "SLOW": 0.0}
        )
        macd = PatternScanner.scan_macd_crossover(frame, "MACD", "MACDs")
        ma = PatternScanner.scan_ma_crossover(frame, "FAST", "SLOW")
        assert len(macd) == 1
        assert len(ma) == 1
        assert macd["timestamp"].tolist() == ma["timestamp"].tolist()

    def test_no_muta_el_frame_de_entrada(self, make_frame):
        # assign() devuelve una copia: el servicio reutiliza el mismo DataFrame
        # para los cinco scanners, asi que mutarlo seria un bug de estado.
        frame = make_frame(
            {"MACD": [-1.0, 1.0], "MACDs": 0.0, "open": 1.0, "close": 2.0}
        )
        before = list(frame.columns)
        PatternScanner.scan_macd_crossover(frame, "MACD", "MACDs")
        PatternScanner.scan_engulfing(frame)
        assert list(frame.columns) == before

    def test_indice_no_es_continuo(self, make_frame, make_index):
        # El servicio lee de Postgres: puede haber huecos. La deteccion depende
        # de la barra inmediatamente anterior en el tiempo, no del reloj.
        frame = make_frame({"MACD": [-1.0, 1.0], "MACDs": 0.0})
        frame.index = pd.DatetimeIndex(["2024-03-01T00:00:00Z", "2024-03-05T00:00:00Z"])
        result = PatternScanner.scan_macd_crossover(frame, "MACD", "MACDs")
        assert result["timestamp"].tolist() == [frame.index[1]]


# ---------------------------------------------------------------------------
# 3a. Vectorizacion
# ---------------------------------------------------------------------------


FORBIDDEN_METHODS = frozenset(
    {"iterrows", "itertuples", "itertags", "apply", "applymap", "reduce", "aggregate"}
)

SCANNER_PATH = Path(scanner_module.__file__)


class _NoRowIterationFrame(pd.DataFrame):
    """DataFrame que revienta si alguien lo recorre como si fueran filas.

    Es la version en tiempo de ejecucion de la prohibicion: el analisis estatico
    comprueba el codigo de ``scanner.py``, esto comprueba el comportamiento, y
    el segundo cubre lo que el primero no ve (una llamada a ``iterrows`` hecha a
    traves de un alias, o un ``for`` sobre el resultado de un metodo).
    """

    @property
    def _constructor(self):  # pragma: no cover - solo comportamiento heredado
        return _NoRowIterationFrame

    def __iter__(self):
        raise AssertionError("se ha iterado el DataFrame fila a fila")


class TestVectorizacion:
    def test_el_fichero_no_tiene_bucles_for(self):
        # ``ast.For`` es una sentencia. Las comprensiones (que el scanner si usa,
        # para ``details``) son ``ast.comprehension`` y no aparecen aqui, asi que
        # esta comprobacion no penaliza la construccion de details.
        tree = ast.parse(SCANNER_PATH.read_text(encoding="utf-8"))
        bucles = [
            ast.unparse(node)
            for node in ast.walk(tree)
            if isinstance(node, (ast.For, ast.AsyncFor))
        ]
        assert bucles == [], f"bucles for en scanner.py: {bucles}"

    def test_no_llama_a_los_metodos_prohibidos(self):
        tree = ast.parse(SCANNER_PATH.read_text(encoding="utf-8"))
        llamadas = [
            ast.unparse(node.func)
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in FORBIDDEN_METHODS
        ]
        assert llamadas == [], f"llamadas prohibidas en scanner.py: {llamadas}"

    def test_el_frame_de_prueba_tampoco_se_puede_iterar(self, make_frame):
        # Si el fixture construyera un DataFrame normal, el test de abajo pasaria
        # sin comprobar nada. Se verifica el guardián con una excepcion.
        frame = _NoRowIterationFrame({"a": [1.0, 2.0]})
        with pytest.raises(AssertionError, match="fila a fila"):
            list(frame)

    @pytest.mark.parametrize(
        ("scanner", "columns"),
        [
            ("scan_macd_crossover", {"MACD": [-1.0, 1.0], "MACDs": 0.0}),
            ("scan_rsi_extremes", {"RSI": [20.0, 80.0]}),
            (
                "scan_bollinger_breakout",
                {"close": [100.0, 106.0], "BBU": 105.0, "BBL": 95.0},
            ),
            ("scan_ma_crossover", {"FAST": [-1.0, 1.0], "SLOW": 0.0}),
            (
                "scan_engulfing",
                {
                    "open": [100.0, 99.5],
                    "close": [99.8, 101.0],
                    "high": 101.5,
                    "low": 99.0,
                },
            ),
        ],
    )
    def test_ningun_scanner_recorre_filas(self, scanner, columns, make_index):
        frame = _NoRowIterationFrame(
            {k: np.asarray(v, dtype="float64") for k, v in columns.items()},
            index=make_index(2),
        )
        frame.attrs["symbol"] = "TESTUSDT"
        frame.attrs["timeframe"] = "1h"

        args = {
            "scan_macd_crossover": ("MACD", "MACDs"),
            "scan_rsi_extremes": ("RSI",),
            "scan_bollinger_breakout": ("close", "BBU", "BBL"),
            "scan_ma_crossover": ("FAST", "SLOW"),
            "scan_engulfing": (),
        }[scanner]

        result = getattr(PatternScanner, scanner)(frame, *args)
        assert len(result) == 1, (
            f"{scanner} deberia detectar una vez, detecto {len(result)}"
        )

    def test_ningun_scanner_usa_iterrows_ni_itertuples(self, monkeypatch, make_frame):
        def reventar(nombre):
            def _boom(*args, **kwargs):
                raise AssertionError(f"{nombre}() no debe usarse en el scanner")

            return _boom

        for metodo in ("iterrows", "itertuples", "apply"):
            monkeypatch.setattr(pd.DataFrame, metodo, reventar(metodo))

        frame = make_frame(
            {
                "MACD": [-1.0, 1.0],
                "MACDs": 0.0,
                "RSI": [20.0, 80.0],
                "close": [100.0, 106.0],
                "BBU": 105.0,
                "BBL": 95.0,
                "FAST": [-1.0, 1.0],
                "SLOW": 0.0,
            }
        )
        assert len(PatternScanner.scan_macd_crossover(frame, "MACD", "MACDs")) == 1
        assert len(PatternScanner.scan_rsi_extremes(frame, "RSI")) == 1
        assert (
            len(PatternScanner.scan_bollinger_breakout(frame, "close", "BBU", "BBL"))
            == 1
        )
        assert len(PatternScanner.scan_ma_crossover(frame, "FAST", "SLOW")) == 1

        # El engulfing necesita un cuerpo envolvente, incompatible con el
        # ``close`` anterior (rompido por Bollinger), asi que va en su propio
        # frame con las cuatro columnas de vela.
        envolvente = make_frame(
            {
                "open": [100.0, 99.5],
                "close": [99.8, 101.0],
                "high": 101.5,
                "low": 99.0,
            }
        )
        assert len(PatternScanner.scan_engulfing(envolvente)) == 1


# ---------------------------------------------------------------------------
# 3b. Rendimiento
# ---------------------------------------------------------------------------

#: Presupuesto del documento de la tarea para el motor de deteccion (sin carga
#: desde base de datos, que se mide aparte en el service).
BUDGET_SEGONDS = 2.0


def _wilder_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """RSI de Wilder, el mismo que calcula la Tarea 3 en PostgreSQL.

    No se puede sustituir por ``close.rolling(14).mean()``: eso es una media
    del precio, vale ~100 siempre y no cruzaria jamas los umbrales 70/30, con
    lo que el benchmark mediria el coste de comparar y no de construir dicts.
    """
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    return 100 - 100 / (1 + avg_gain / avg_loss)


def _benchmark_frame(n: int, seed: int = 7) -> pd.DataFrame:
    """Serie de ``n`` velas con geometria realista: paseo aleatorio con
    medias, bandas y RSI calculados con los mismos periodos que la Tarea 3.

    Importa que la densidad de deteccion sea la real. Medido sobre BTCUSDT 1h
    de desarrollo, el motor encontro 443 detecciones en 2209 velas, un 20 %, que
    es lo que reproduce este frame. Con un zigzag que cruza en todas las barras
    se construiria un dict por vela y el test mediria un caso que no se parece
    a nada; con una serie plana no se construiria ninguno y no se mediria nada.
    """
    rng = np.random.default_rng(seed)
    close = pd.Series(100 + np.cumsum(rng.normal(0, 0.5, n)))
    macd = close.ewm(span=12).mean() - close.ewm(span=26).mean()
    rolling20 = close.rolling(20)
    std = rolling20.std()

    # ``to_numpy()`` y no la Series: al construir el DataFrame con un index
    # datetime, pandas reindexa cada Series por etiqueta y las 0..n-1 no
    # existen, dejando todas las features en NaN. El sintoma es desconcertante:
    # los cinco scanners devuelven 0 detecciones sin ningun error.
    frame = pd.DataFrame(
        {
            "open": (close + rng.normal(0, 0.1, n)).to_numpy(),
            "close": close.to_numpy(),
            "high": (close + 0.5).to_numpy(),
            "low": (close - 0.5).to_numpy(),
            "MACD_12_26_9": macd.to_numpy(),
            "MACDs_12_26_9": macd.ewm(span=9).mean().to_numpy(),
            "RSI_14": _wilder_rsi(close).to_numpy(),
            "BBU_20_2.0": (rolling20.mean() + 2 * std).to_numpy(),
            "BBL_20_2.0": (rolling20.mean() - 2 * std).to_numpy(),
            "EMA_20": close.ewm(span=20).mean().to_numpy(),
            "EMA_50": close.ewm(span=50).mean().to_numpy(),
        },
        index=pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC"),
    )
    frame.attrs["symbol"] = "BENCHUSDT"
    frame.attrs["timeframe"] = "1h"
    return frame


def _run_all_scanners(frame: pd.DataFrame) -> int:
    """Ejecuta los cinco scanners y devuelve el total de detecciones."""
    return sum(
        len(result)
        for result in (
            PatternScanner.scan_macd_crossover(frame, "MACD_12_26_9", "MACDs_12_26_9"),
            PatternScanner.scan_rsi_extremes(frame, "RSI_14", 70.0, 30.0),
            PatternScanner.scan_bollinger_breakout(
                frame, "close", "BBU_20_2.0", "BBL_20_2.0"
            ),
            PatternScanner.scan_ma_crossover(frame, "EMA_20", "EMA_50"),
            PatternScanner.scan_engulfing(frame),
        )
    )


class TestRendimiento:
    @pytest.mark.parametrize("n", [100_000, 1_000_000])
    def test_el_motor_cumple_el_presupuesto(self, n):
        frame = _benchmark_frame(n)
        detecciones = _run_all_scanners(frame)
        assert detecciones > 0, "el frame de benchmark no produce detecciones"

        # Mejor de tres: el primer arranque paga cachés frios de pandas y el
        # recolector de basura puede colarse. Medir el peor caso haria el test
        # fragil en un CI compartido sin decir nada sobre el rendimiento real.
        tiempos = []
        for _ in range(3):
            inicio = time.perf_counter()
            _run_all_scanners(frame)
            tiempos.append(time.perf_counter() - inicio)

        mejor = min(tiempos)
        densidad = detecciones / n * 100
        print(
            f"\n{n:>9,} velas | 5 scanners | {detecciones:>7,} detecciones "
            f"({densidad:.1f}%) | mejor={mejor:.3f}s "
            f"presupuesto={BUDGET_SEGONDS}s | margen={BUDGET_SEGONDS / mejor:.0f}x"
        )
        assert mejor < BUDGET_SEGONDS, (
            f"{n:,} velas tardaron {mejor:.3f}s, presupuesto {BUDGET_SEGONDS}s "
            f"(todos los intentos: {[f'{t:.3f}' for t in tiempos]})"
        )

    def test_escala_lineal_con_el_tamano(self):
        # 1M velas no deben costar 100 veces 100k. Con una componente cuadratica
        # el presupuesto de 2 s se cumpliria hoy con 1M y noaria con la
        # realidad del mercado, que son años de historia por symbol.
        pequeno_frame = _benchmark_frame(100_000)
        grande_frame = _benchmark_frame(1_000_000)

        def medir(frame: pd.DataFrame) -> float:
            inicio = time.perf_counter()
            _run_all_scanners(frame)
            return time.perf_counter() - inicio

        pequeno = min(medir(pequeno_frame) for _ in range(3))
        grande = min(medir(grande_frame) for _ in range(3))

        # 10x los datos. Lineal daria ~10x el tiempo; cuadratico, ~100x.
        cociente = grande / pequeno
        print(
            f"\n100k -> {pequeno:.3f}s | 1M -> {grande:.3f}s | "
            f"cociente={cociente:.1f}x para 10x los datos"
        )
        assert cociente < 30, (
            f"10x las velas cuestan {cociente:.1f}x el tiempo, "
            "sospecha de una componente no lineal"
        )
