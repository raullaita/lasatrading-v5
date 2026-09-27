"""Carga de velas OHLCV como DataFrame indexado por ``timestamp``.

Vive aqui, y no dentro de un servicio, porque tres modulos necesitan exactamente
la misma consulta: ``features`` para calcular indicadores, ``patterns`` para
detectar patrones y ``backtesting`` para simular operaciones. Cada uno tenia su
propia copia y las copias divergieron, que es como se colaron los dos bugs que
documenta el resto del modulo.

Convencion de salida (no negociable, la consumen los calculos vectorizados):

* Indice ``DatetimeIndex`` en **UTC**, monotono creciente.
* Columnas ``open``, ``high``, ``low``, ``close``, ``volume`` en ``float64``.
* Sin columna ``timestamp``: el timestamp es el indice.

El orden no es un detalle. ``ewm()``, ``rolling()`` y ``shift()`` son
operadores posicionales: aplicadas sobre una serie desordenada producen
numeros sin relacion con la serie real. Una consulta sin ``ORDER BY`` no
garantiza orden, y sobre una hypertable de TimescaleDB las filas salen
repartidas entre chunks, asi que el orden real es el del almacenamiento y no el
cronologico.
"""

from datetime import datetime

import pandas as pd
from sqlalchemy import select

from app.core.database import SessionLocal
from app.modules.data_import.models import Candle

#: Columnas OHLCV en el orden en que se seleccionan de la base de datos. Es la
#: unica fuente de verdad del contrato: anadir una columna aqui la propaga a
#: los tres modulos consumidores.
CANDLE_COLUMNS = ("timestamp", "open", "high", "low", "close", "volume")


def load_candles(
    symbol: str,
    timeframe: str,
    date_from: datetime,
    date_to: datetime,
) -> pd.DataFrame:
    """Carga las velas OHLCV de un par y rango, indexadas por timestamp.

    Los limites ``date_from`` y ``date_to`` son **inclusivos** en ambos
    extremos, igual que la consulta de disponibilidad de datos, de modo que un
    rango descrito como "hasta las 00:00 del dia X" incluye esa vela.

    El ``ORDER BY`` no es opcional ni decorativo. ``candles`` es una hypertable
    de TimescaleDB repartida en chunks por tiempo; sin orden explicito
    PostgreSQL devuelve las filas en el orden en que las recorre el
    almacenamiento, que mezcla chunks. Se observaron 8780 velas de ETHUSDT 1h
    devueltas empezando por 2026-09-23 23:00 y terminando por 2026-09-24 00:00.

    Como ``ewm()``, ``rolling()`` y ``shift()`` son posicionales, calcular
    sobre esa serie produce indicadores sin relacion con la serie real. El
    ``RSI_14`` almacenado de BTCUSDT 1h en 2026-03-27 10:00 era 10.79 cuando el
    valor correcto sobre la serie ordenada es 15.97: 5 puntos de error, que
    desplazan cruces de los umbrales 30/70 y, con ellos, las detecciones de
    patron que dependen de ese indicador.

    Devuelve un DataFrame vacio (sin columnas) si no hay velas, para que el
    llamante distinga "sin datos" de un error con ``df.empty``.
    """
    with SessionLocal() as db:
        rows = db.execute(
            select(*(getattr(Candle, column) for column in CANDLE_COLUMNS))
            .where(Candle.symbol == symbol)
            .where(Candle.timeframe == timeframe)
            .where(Candle.timestamp >= date_from)
            .where(Candle.timestamp <= date_to)
            .order_by(Candle.timestamp)
        ).all()

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows, columns=list(CANDLE_COLUMNS))
    for column in CANDLE_COLUMNS[1:]:
        df[column] = df[column].astype(float)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df.set_index("timestamp").sort_index()
