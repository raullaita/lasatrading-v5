"""Deteccion vectorizada de patrones sobre un DataFrame de velas y features.

Reglas de este modulo (no negociables):

* Prohibido ``iterrows()``, ``itertuples()`` y cualquier ``for`` sobre el
  DataFrame. Las detecciones se expresan con ``shift()``, comparaciones
  booleanas y ``&``/``|``.
* ``details`` (JSONB) se construye recorriendo *columnas* en paralelo con
  ``zip``, nunca filas, y solo sobre las filas que han superado la mascara.
* Cada metodo devuelve ``timestamp``, ``symbol``, ``timeframe``,
  ``pattern_name`` y ``details``. ``pattern_name`` es siempre un codigo del
  catalogo con la direccion ya resuelta, para que el servicio pueda filtrar
  por los codigos solicitados sin un paso de mapeo adicional.

Convencion de entrada: el DataFrame va indexado por ``timestamp`` y lleva
``symbol`` y ``timeframe`` en ``df.attrs`` (pandas los propaga a traves de
``assign`` y ``loc``, asi que los metodos pueden derivar columnas libremente).
El servicio es quien los fija.
"""

from collections.abc import Mapping
from typing import Any

import pandas as pd

# Columnas auxiliares derivadas. El prefijo evita colisionar con nombres de
# feature o con las columnas OHLCV.
_DIFF = "_pattern_diff"
_PREV_OPEN = "_pattern_prev_open"
_PREV_CLOSE = "_pattern_prev_close"

RESULT_COLUMNS = ["timestamp", "symbol", "timeframe", "pattern_name", "details"]

# Codigos de patron emitidos por los scanners. Deben coincidir exactamente con
# los de ``pattern_catalog``; ``test_patterns.py`` lo verifica.
MACD_CROSS_BULLISH = "MACD_CROSS_BULLISH"
MACD_CROSS_BEARISH = "MACD_CROSS_BEARISH"
RSI_EXIT_OVERBOUGHT = "RSI_EXIT_OVERBOUGHT"
RSI_EXIT_OVERSOLD = "RSI_EXIT_OVERSOLD"
BB_BREAKOUT_UPPER = "BB_BREAKOUT_UPPER"
BB_BREAKOUT_LOWER = "BB_BREAKOUT_LOWER"
MA_CROSS_BULLISH = "MA_CROSS_BULLISH"
MA_CROSS_BEARISH = "MA_CROSS_BEARISH"
ENGULFING_BULLISH = "ENGULFING_BULLISH"
ENGULFING_BEARISH = "ENGULFING_BEARISH"


def _empty_result() -> pd.DataFrame:
    """DataFrame vacio con las columnas y dtypes del contrato de salida."""
    return pd.DataFrame(
        {
            "timestamp": pd.Series(dtype="datetime64[ns, UTC]"),
            "symbol": pd.Series(dtype="object"),
            "timeframe": pd.Series(dtype="object"),
            "pattern_name": pd.Series(dtype="object"),
            "details": pd.Series(dtype="object"),
        }
    )


def _crossover_masks(diff: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Mascas de cruce ascendente y descendente a partir de una diferencia.

    Un cruce ascendente en la barra ``i`` exige ``d[i-1] <= 0 < d[i]``, asi que
    basta con la diferencia: no hay que comparar las dos series por separado.

    Las comparaciones con NaN dan False, de modo que el warmup de los
    indicadores no produce detecciones espurias y no hace falta limpiar la
    serie antes. Se usa ``<= 0`` en lugar de ``< 0`` para que rozar el umbral
    cuente como cruce, igual que en la RSI.
    """
    previous = diff.shift(1)
    up = (previous <= 0) & (diff > 0)
    down = (previous >= 0) & (diff < 0)
    return up, down


def _build_details(
    frame: pd.DataFrame,
    fields: Mapping[str, str],
    constants: Mapping[str, Any] | None = None,
) -> pd.Series:
    """Construye la columna JSONB ``details`` a partir de columnas del frame.

    ``fields`` mapea la clave que ira en el JSON al nombre de la columna, lo que
    permite incluir valores derivados (diferencias, velas previas) siempre que
    se hayan materializado como columna antes de llamar a esta funcion.
    ``constants`` anade claves iguales para todas las detecciones.

    Se recorren las columnas en paralelo con ``zip`` en lugar de las filas: es
    varios ordenes de magnitud mas rapido que ``DataFrame.apply(axis=1)`` y no
    crea un ``Series`` por fila. Los valores pasan por ``float()`` porque son
    ``numpy.float64`` y el adaptador JSONB de psycopg no los serializa.
    """
    keys = list(fields)
    columns = [frame[source].to_numpy() for source in fields.values()]
    base = dict(constants or {})
    return pd.Series(
        [
            {
                **base,
                **{key: float(value) for key, value in zip(keys, values, strict=True)},
            }
            for values in zip(*columns, strict=True)
        ],
        index=frame.index,
        dtype=object,
    )


def _result(
    frame: pd.DataFrame,
    mask: pd.Series,
    pattern_name: str,
    fields: Mapping[str, str],
    constants: Mapping[str, Any] | None = None,
) -> pd.DataFrame:
    """Filtra por la mascara y ensambla el DataFrame de salida.

    ``details`` se construye despues de filtrar, de modo que solo se materializa
    un dict por deteccion real y no por vela.
    """
    if not mask.any():
        return _empty_result()

    detected = frame.loc[mask]
    return pd.DataFrame(
        {
            "timestamp": detected.index.to_series(),
            "symbol": frame.attrs["symbol"],
            "timeframe": frame.attrs["timeframe"],
            "pattern_name": pattern_name,
            "details": _build_details(detected, fields, constants),
        },
        index=detected.index,
    )


def _merge(*frames: pd.DataFrame) -> pd.DataFrame:
    parts = [frame for frame in frames if not frame.empty]
    if not parts:
        return _empty_result()
    if len(parts) == 1:
        return parts[0].reset_index(drop=True)
    return pd.concat(parts, ignore_index=True)


class PatternScanner:
    """Deteccion de patrones. Todos los metodos son estaticos y vectorizados."""

    @staticmethod
    def scan_macd_crossover(
        df: pd.DataFrame,
        macd_col: str = "MACD",
        signal_col: str = "MACDs",
    ) -> pd.DataFrame:
        """Cruces de la linea MACD sobre la linea de senal.

        Devuelve un DataFrame con las filas ``MACD_CROSS_BULLISH`` y/o
        ``MACD_CROSS_BEARISH`` detectadas. Al basarse en la diferencia, tambien
        registra los cruces ocurridos por debajo de cero.
        """
        work = df.assign(**{_DIFF: df[macd_col] - df[signal_col]})
        up, down = _crossover_masks(work[_DIFF])

        bullish = _result(
            work,
            up,
            MACD_CROSS_BULLISH,
            fields={"macd": macd_col, "signal": signal_col, "diff": _DIFF},
            constants={"direction": "bullish"},
        )
        bearish = _result(
            work,
            down,
            MACD_CROSS_BEARISH,
            fields={"macd": macd_col, "signal": signal_col, "diff": _DIFF},
            constants={"direction": "bearish"},
        )
        return _merge(bullish, bearish)

    @staticmethod
    def scan_rsi_extremes(
        df: pd.DataFrame,
        rsi_col: str = "RSI",
        threshold_up: float = 70.0,
        threshold_down: float = 30.0,
    ) -> pd.DataFrame:
        """Salidas de sobreventa y sobrecompra.

        No basta con que el RSI sea extremo: se exige el cruce de umbral
        (``rsi[i-1] <= umbral < rsi[i]`` y simetricamente). Sin el ``shift`` un
        RSI que se mantiene sobre 70 generaria una deteccion en cada barra.
        """
        rsi = df[rsi_col]
        previous = rsi.shift(1)

        exit_oversold = (previous <= threshold_down) & (rsi > threshold_down)
        exit_overbought = (previous >= threshold_up) & (rsi < threshold_up)

        bullish = _result(
            df,
            exit_oversold,
            RSI_EXIT_OVERSOLD,
            fields={"rsi_value": rsi_col},
            constants={"threshold": float(threshold_down), "direction": "bullish"},
        )
        bearish = _result(
            df,
            exit_overbought,
            RSI_EXIT_OVERBOUGHT,
            fields={"rsi_value": rsi_col},
            constants={"threshold": float(threshold_up), "direction": "bearish"},
        )
        return _merge(bullish, bearish)

    @staticmethod
    def scan_bollinger_breakout(
        df: pd.DataFrame,
        close_col: str = "close",
        bb_upper_col: str = "BBU",
        bb_lower_col: str = "BBL",
    ) -> pd.DataFrame:
        """Rupturas de las bandas de Bollinger por el cierre.

        Cada banda se compara con su propio ``shift(1)``: comparar el cierre
        actual contra la banda actual ya seria una ruptura por definicion y no
        exigiria la vela anterior.
        """
        close = df[close_col]
        upper = df[bb_upper_col]
        lower = df[bb_lower_col]

        break_up = (close.shift(1) <= upper.shift(1)) & (close > upper)
        break_down = (close.shift(1) >= lower.shift(1)) & (close < lower)

        bullish = _result(
            df,
            break_up,
            BB_BREAKOUT_UPPER,
            fields={"close": close_col, "band": bb_upper_col},
            constants={"direction": "bullish"},
        )
        bearish = _result(
            df,
            break_down,
            BB_BREAKOUT_LOWER,
            fields={"close": close_col, "band": bb_lower_col},
            constants={"direction": "bearish"},
        )
        return _merge(bullish, bearish)

    @staticmethod
    def scan_ma_crossover(
        df: pd.DataFrame,
        fast_col: str,
        slow_col: str,
    ) -> pd.DataFrame:
        """Cruces entre dos medias, en ambos sentidos, de forma generica.

        Los nombres de columna los decide el llamante a partir de los
        parametros del patron, por eso aqui no hay defaults.
        """
        work = df.assign(**{_DIFF: df[fast_col] - df[slow_col]})
        up, down = _crossover_masks(work[_DIFF])

        bullish = _result(
            work,
            up,
            MA_CROSS_BULLISH,
            fields={"fast": fast_col, "slow": slow_col, "diff": _DIFF},
            constants={"direction": "bullish"},
        )
        bearish = _result(
            work,
            down,
            MA_CROSS_BEARISH,
            fields={"fast": fast_col, "slow": slow_col, "diff": _DIFF},
            constants={"direction": "bearish"},
        )
        return _merge(bullish, bearish)

    @staticmethod
    def scan_engulfing(df: pd.DataFrame) -> pd.DataFrame:
        """Velas envolventes. Patron puro de precio: no requiere features.

        Alcista: la vela anterior es bajista y el cuerpo actual la envuelve por
        completo (``open <= prev_close`` y ``close >= prev_open``). La simetrica
        para la bajista. Las comparaciones de envoltura son inclusivas en los
        extremos, que es el criterio habitual: un cuerpo identico se considera
        envolvente.

        Las columnas de la vela anterior se derivan con ``shift`` para que
        ``details`` pueda leerlas como cualquier otra columna.
        """
        work = df.assign(
            **{
                _PREV_OPEN: df["open"].shift(1),
                _PREV_CLOSE: df["close"].shift(1),
            }
        )
        open_ = work["open"]
        close = work["close"]
        prev_open = work[_PREV_OPEN]
        prev_close = work[_PREV_CLOSE]

        bullish = (
            (prev_close < prev_open)
            & (close > open_)
            & (open_ <= prev_close)
            & (close >= prev_open)
        )
        bearish = (
            (prev_open < prev_close)
            & (close < open_)
            & (open_ >= prev_close)
            & (close <= prev_open)
        )

        fields = {
            "open": "open",
            "close": "close",
            "prev_open": _PREV_OPEN,
            "prev_close": _PREV_CLOSE,
        }
        up_result = _result(
            work,
            bullish,
            ENGULFING_BULLISH,
            fields=fields,
            constants={"direction": "bullish"},
        )
        down_result = _result(
            work,
            bearish,
            ENGULFING_BEARISH,
            fields=fields,
            constants={"direction": "bearish"},
        )
        return _merge(up_result, down_result)


#: Metodos de ``PatternScanner`` referenciados por el campo ``scanner`` del
#: catalogo. El servicio despacha por esta tabla en lugar de usar ``getattr``,
#: para que un typo en el catalogo falle de forma explicita y no en silencio.
SCANNER_METHODS: tuple[str, ...] = (
    "scan_macd_crossover",
    "scan_rsi_extremes",
    "scan_bollinger_breakout",
    "scan_ma_crossover",
    "scan_engulfing",
)
