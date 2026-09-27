"""Tests del contrato de ``load_candles``.

Este modulo no necesita ni una vela real: lo que se verifica es que la consulta
que construye el DataFrame **exige orden cronologico**, que es la propiedad que
una consulta sin ``ORDER BY`` no tiene y que ``ewm()``/``rolling()`` dan por
supuesta.

El bug que se cubre aqui fue real: la copia de esta carga que vivia en
``features/service.py`` se olvidaba del ``ORDER BY`` y, al no ser ``candles``
una hypertable de TimescaleDB, las filas llegaban repartidas por chunk. Los
indicadores calculados sobre esa serie no tenian relacion con la serie real.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest
from app.core.database import SessionLocal
from app.modules.data.candles import CANDLE_COLUMNS, load_candles
from app.modules.data_import.models import Candle
from sqlalchemy import select

START = datetime(2026, 1, 1, tzinfo=timezone.utc)
END = datetime(2026, 1, 2, tzinfo=timezone.utc)


def _insert(session, rows: list[tuple]) -> None:
    session.execute(
        Candle.__table__.insert(),
        [
            {
                "timestamp": ts,
                "symbol": "CONTRACTUSDT",
                "timeframe": "1h",
                "open": o,
                "high": h,
                "low": low,
                "close": c,
                "volume": v,
            }
            for ts, o, h, low, c, v in rows
        ],
    )


@pytest.fixture
def scrambled_candles():
    """Velas en el DB y en el orden de insercion, deliberadamente desordenado.

    Se insertan en orden inverso al cronologico. Una consulta sin ``ORDER BY``
    devuelve las filas en ese mismo orden de insercion, asi que el test falla si
    alguien quita el ``ORDER BY`` de la consulta.
    """
    rows = [
        (
            pd.Timestamp(f"2026-01-01T{hour:02d}:00:00Z").to_pydatetime(),
            100.0 + hour,
            101.0 + hour,
            99.0 + hour,
            100.5 + hour,
            10.0 + hour,
        )
        for hour in reversed(range(6))
    ]
    with SessionLocal() as session:
        _insert(session, rows)
        session.commit()
    try:
        yield rows
    finally:
        with SessionLocal() as session:
            session.execute(
                Candle.__table__.delete().where(
                    Candle.symbol == "CONTRACTUSDT", Candle.timeframe == "1h"
                )
            )
            session.commit()


def test_devuelve_las_velas_en_orden_cronologico(scrambled_candles):
    """El invariante central: el indice sale monotono creciente.

    Sin esto, ``ewm()``, ``rolling()`` y ``shift()`` operan sobre una serie cuyo
    orden no es el temporal y los resultados no significan nada.
    """
    df = load_candles("CONTRACTUSDT", "1h", START, END)

    assert not df.empty
    assert df.index.is_monotonic_increasing
    assert df.index.is_unique
    assert df.index[0] == pd.Timestamp("2026-01-01T00:00:00Z")
    assert df.index[-1] == pd.Timestamp("2026-01-01T05:00:00Z")


def test_indice_en_utc_y_columnas_contratadas(scrambled_candles):
    """El indice va en UTC y las columnas OHLCV en ``float64``, sin ``timestamp``.

    Un indice naive rompe el ``merge`` con los indicadores, que si se cargan con
    ``utc=True``; y una columna ``timestamp`` sobraria junto al indice.
    """
    df = load_candles("CONTRACTUSDT", "1h", START, END)

    assert str(df.index.tz) == "UTC"
    assert list(df.columns) == list(CANDLE_COLUMNS[1:])
    assert all(pd.api.types.is_float_dtype(df[c]) for c in df.columns)


def test_sin_velas_devuelve_dataframe_vacio(scrambled_candles):
    """Sin datos devuelve un frame vacio, no un frame con filas de NaN."""
    df = load_candles("CONTRACTUSDT", "15m", START, END)

    assert df.empty
    assert len(df.columns) == 0


def test_los_limites_son_inclusivos(scrambled_candles):
    """``date_to`` incluye la vela exacta de ese timestamp.

    Importa para el rango que declara la UI: "hasta el 27 de septiembre" acaba
    a las 00:00, y esa vela de las 00:00 tiene que entrar.
    """
    last = pd.Timestamp("2026-01-01T05:00:00Z").to_pydatetime()
    first = pd.Timestamp("2026-01-01T00:00:00Z").to_pydatetime()

    assert len(load_candles("CONTRACTUSDT", "1h", first, last)) == 6
    sin_ultima = last - pd.Timedelta(hours=1)
    assert len(load_candles("CONTRACTUSDT", "1h", first, sin_ultima)) == 5


def test_la_consulta_ordena_en_la_base_de_datos(scrambled_candles):
    """La garantia de orden viene de la consulta, no de un ``sort_index`` posterior.

    ``sort_index`` en memoria taparia el problema aqui, pero obligaria a traer
    todas las filas al cliente para ordenarlas: el coste de red es justo lo que
    se quiere evitar cuando el rango son miles de velas.
    """
    statement = select(Candle.timestamp).where(
        Candle.symbol == "CONTRACTUSDT", Candle.timeframe == "1h"
    )
    with SessionLocal() as session:
        sin_ordenar = [row[0] for row in session.execute(statement).all()]
        con_orden = [
            row[0]
            for row in session.execute(statement.order_by(Candle.timestamp)).all()
        ]

    assert sin_ordenar != con_orden, (
        "El fixture deberia insertar desordenado; si el Gestor devolvio ya "
        "ordenado, el test dejaria de probar lo que dice probar"
    )
    assert load_candles("CONTRACTUSDT", "1h", START, END).index.is_monotonic_increasing
