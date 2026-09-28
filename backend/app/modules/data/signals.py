"""Carga de señales de un escaneo como DataFrame indexado por ``timestamp``.

Vive aqui, y no dentro de un servicio, por el mismo motivo que
``data/candles.py``: el motor de backtesting y el de walk-forward necesitan
**exactamente la misma** consulta, con el mismo filtro y la misma trampa de la
dirección. Con dos copias, la primera vez que alguien cambie el formato del
``metadata`` tendrá un módulo que funciona y otro que no, y el que no funciona
dará direcciones vacías en silencio.

Convención de salida (la consume ``engine.run_backtest``):

* Columna ``timestamp`` en **UTC**.
* Columnas ``pattern_name`` y ``direction``, con ``direction`` ya como texto
  plano (``"bullish"`` / ``"bearish"``), nunca como el JSON serializado.
"""

from __future__ import annotations

import pandas as pd
from sqlalchemy import Text, cast, func, select
from sqlalchemy.orm import Session

from app.modules.patterns.models import PatternOccurrence


def direction_column() -> Text:
    """La columna JSONB de dirección de ``pattern_occurrences``, como texto.

    Dos trampas, las dos ya pisadas al escribir esto:

    1. Va por ``__table__`` (Core) y **no** por la clase ORM a propósito: la
       clase declarativa expone esa columna como ``details``, porque ``metadata``
       está reservado en SQLAlchemy, así que ``PatternOccurrence.metadata``
       resuelve al ``MetaData`` de la clase y subscriptarlo revienta con
       ``'MetaData' object is not subscriptable``.

    2. Se usa ``jsonb_extract_path_text`` (``->>``) y no un ``cast`` sobre
       ``c.metadata["direction"]``. En Core ese subscripto genera ``->``, y
       castear a texto el resultado de ``->`` deja el valor **tal cual lo
       serializa JSON**, es decir ``'"bullish"'`` con las comillas dentro. Al
       compararlo contra ``"bullish"`` no cuadra y el motor acaba viendo
       direcciones que no reconoce.
    """
    columna = PatternOccurrence.__table__.c.metadata
    return cast(func.jsonb_extract_path_text(columna, "direction"), Text)


def load_signals(
    db: Session,
    scan_job_id,
    patterns: tuple[str, ...] | None = None,
    directions: tuple[str, ...] | None = None,
) -> pd.DataFrame:
    """Señales de un escaneo, en el formato que espera el motor.

    El filtro se aplica **en SQL** y no después: traer 2.812 filas para descartar
    1.700 en Python sería tirar la mayor parte del trabajo de la base de datos.

    El ``ORDER BY`` no es decorativo, por el mismo motivo que en las velas: las
    ocurrencias se reparten entre chunks y sin orden explícito el motor recibe
    señales desordenadas.
    """
    direction_col = direction_column()
    stmt = select(
        PatternOccurrence.timestamp,
        PatternOccurrence.pattern_name,
        direction_col.label("direction"),
    ).where(PatternOccurrence.scan_job_id == scan_job_id)
    if patterns:
        stmt = stmt.where(PatternOccurrence.pattern_name.in_(patterns))
    if directions:
        stmt = stmt.where(direction_col.in_(directions))
    stmt = stmt.order_by(PatternOccurrence.timestamp)

    rows = db.execute(stmt).mappings().all()
    frame = pd.DataFrame(rows, columns=["timestamp", "pattern_name", "direction"])
    if frame.empty:
        return frame
    # ``pd.to_datetime(..., utc=True)`` y no ``pd.DatetimeIndex(...).dt``: el
    # accesor ``.dt`` es de ``Series``, ``DatetimeIndex`` no lo tiene. El
    # ``utc=True`` además normaliza a UTC lo que venga sin zona horaria, en vez
    # de asumir que ya es UTC.
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    return frame.sort_values("timestamp", kind="stable").reset_index(drop=True)
