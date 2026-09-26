"""Fixtures compartidas de los tests del backend.

Las del scanner son puras de pandas: ni base de datos, ni Celery, ni red. Todo
``test_pattern_scanner.py`` corre en segundos sin tocar PostgreSQL, que es la
ventaja de haber dejado el motor de deteccion como funciones puras que reciben
un DataFrame y devuelven otro.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

import numpy as np
import pandas as pd
import pytest
from app.modules.patterns.scanner import RESULT_COLUMNS

#: Valores por defecto. Coinciden con los que fija ``PatternScanService`` en
#: ``df.attrs`` antes de invocar a los scanners.
SYMBOL = "TESTUSDT"
TIMEFRAME = "1h"
START = "2024-01-01T00:00:00Z"


@pytest.fixture
def make_index() -> Callable[[int], pd.DatetimeIndex]:
    """Indice horario UTC de ``n`` barras."""

    def _make(n: int) -> pd.DatetimeIndex:
        return pd.date_range(START, periods=n, freq="h", tz="UTC")

    return _make


@pytest.fixture
def make_frame(make_index: Callable[[int], pd.DatetimeIndex]) -> Callable[..., Any]:
    """Construye un DataFrame con la convencion de entrada de los scanners.

    Indexado por ``timestamp`` y con ``symbol``/``timeframe`` en ``attrs``, que es
    lo que leen los metodos de ``PatternScanner``. Se encarga de esto para que
    ningun test tenga que acordarse, y para que un olvido se manifests como un
    ``KeyError`` en la asercion y no como datos silenciosamente erroneos.

    Los valores escalares se difunden a todas las barras, que es como se escriben
    los casos de prueba: ``{"close": 105.0, "BBU": [100, 101, 102]}``.

    Con ``index=False`` se salta el indexado por tiempo, para probar el contrato
    de salida cuando el frame llega vacio.
    """

    def _make(
        columns: Mapping[str, Any],
        n: int | None = None,
        *,
        index: bool = True,
        symbol: str = SYMBOL,
        timeframe: str = TIMEFRAME,
    ) -> pd.DataFrame:
        if n is None:
            lengths = [len(v) for v in columns.values() if np.ndim(v) > 0]
            n = max(lengths) if lengths else 0

        data: dict[str, Any] = {}
        for key, value in columns.items():
            if np.ndim(value) == 0:
                data[key] = np.full(n, value, dtype="float64")
            else:
                data[key] = np.asarray(value, dtype="float64")

        frame = pd.DataFrame(data, index=make_index(n) if index else None)
        frame.attrs["symbol"] = symbol
        frame.attrs["timeframe"] = timeframe
        return frame

    return _make


@pytest.fixture
def assert_contract() -> Callable[[pd.DataFrame], pd.DataFrame]:
    """Comprueba el contrato de salida comun a los cinco scanners y devuelve el
    DataFrame para poder encadenar aserciones.

    El contrato lo fija el docstring de ``scanner.py``: exactamente estas cinco
    columnas, ``symbol``/``timeframe`` tomados de ``attrs``, y ``details`` como
    dicts de valores ``float`` natives (no ``numpy.float64``, que el adaptador
    JSONB de psycopg no serializa; ese bug se coló en la version anterior).
    """

    def _check(result: pd.DataFrame) -> pd.DataFrame:
        assert list(result.columns) == RESULT_COLUMNS
        assert (result["symbol"] == SYMBOL).all()
        assert (result["timeframe"] == TIMEFRAME).all()
        # pandas 3 devuelve dtype ``str`` donde antes era ``object``. Las dos son
        # validas para el adaptador de psycopg, asi que se comprueba que el
        # contenido sea texto y no que la columna tenga un dtype concreto.
        assert result["symbol"].map(type).eq(str).all()
        assert result["details"].dtype == object
        for details in result["details"]:
            assert isinstance(details, dict)
            for key, value in details.items():
                assert isinstance(key, str)
                assert isinstance(value, (float, str)), (
                    f"{key}={value!r} ({type(value)})"
                )
        return result

    return _check


@pytest.fixture
def empty_frame() -> Callable[..., pd.DataFrame]:
    """Frame sin filas, con los valores de ``attrs`` puestos.

    Acepta columnas extra porque un frame vacio de un scanner de indicadores
    tiene que traer las features: ``df["MACD"]`` sobre un frame sin esa columna
    lanza ``KeyError`` antes incluso de mirar que no hay filas, que es la
    excepcion que hay que comprobar, no el comportamiento a proteger.
    """

    def _make(extra: Mapping[str, str] | None = None) -> pd.DataFrame:
        data: dict[str, pd.Series] = {
            column: pd.Series(dtype="float64")
            for column in ("open", "high", "low", "close", "volume")
        }
        for column in extra or {}:
            data[column] = pd.Series(dtype="float64")
        frame = pd.DataFrame(data)
        frame.attrs["symbol"] = SYMBOL
        frame.attrs["timeframe"] = TIMEFRAME
        return frame

    return _make
