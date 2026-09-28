"""Exporta los tres regimenes de referencia a ficheros locales para los tests.

Los tres regimenes (BTCUSDT 1h: lateral 2021-09, bajista 2022-01, alcista
2026-07) son **datos de desarrollo**, y los tests nunca deben tocar la base de
desarrollo: el `conftest` crea `lasa_test` precisamente para que las pruebas no
vean los datos del scan de referencia.

Pero la prueba de fuego del walk-forward necesita Markets de verdad, y
sinteticos no sirven: un motor puede pasar todos los tests de codigo y fallar
solo con las velas reales, que es justo lo que se quiere comprobar.

Resolucion: el script exporta a `tests/fixtures/walk_forward/` (fuera de git) y
el test se salta si no encuentra los ficheros. El script se versiona para que la
exportacion sea reproducible; los datos no, porque no son codigo.

    python scripts/export_regime_fixtures.py

Compara con el de `analysis.walk_forward`: el motor trabaja con DataFrames y no
sabe de donde salen.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.modules.data_import.models import Candle  # noqa: E402
from app.modules.patterns.models import (  # noqa: E402
    PatternOccurrence,
    PatternScanJob,
    PatternScanJobStatus,
)
from sqlalchemy import select  # noqa: E402

DESTINO = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "walk_forward"

#: Los tres regimenes, con la etiqueta que usa el walk-forward para el techo del
#: veredicto: hacen falta tres para poder decir «sostenida».
REGIMENES = {
    "lateral_2021": (
        "60911afa",
        "BTCUSDT",
        "1h",
        datetime(2021, 9, 1, tzinfo=timezone.utc),
        datetime(2021, 12, 31, tzinfo=timezone.utc),
    ),
    "bajista_2022": (
        "f6afafd8",
        "BTCUSDT",
        "1h",
        datetime(2022, 1, 1, tzinfo=timezone.utc),
        datetime(2022, 6, 30, tzinfo=timezone.utc),
    ),
    "alcista_2026": (
        "b5126401",
        "BTCUSDT",
        "1h",
        datetime(2026, 7, 1, tzinfo=timezone.utc),
        datetime(2026, 9, 27, tzinfo=timezone.utc),
    ),
}


def exportar() -> int:
    DESTINO.mkdir(parents=True, exist_ok=True)
    escritos = 0
    with SessionLocal() as db:
        for etiqueta, (prefijo, simbolo, timeframe, desde, hasta) in REGIMENES.items():
            job = _buscar_scan(db, prefijo, simbolo, timeframe)
            if job is None:
                print(f"  {etiqueta}: no hay escaneo {prefijo}… en la base; se salta")
                continue
            job_id = job.id
            velas = (
                db.execute(
                    select(Candle)
                    .where(
                        Candle.symbol == simbolo,
                        Candle.timeframe == timeframe,
                        Candle.timestamp >= desde,
                        Candle.timestamp <= hasta,
                    )
                    .order_by(Candle.timestamp)
                )
                .scalars()
                .all()
            )
            marco = pd.DataFrame(
                [
                    {
                        "timestamp": c.timestamp,
                        "open": float(c.open),
                        "high": float(c.high),
                        "low": float(c.low),
                        "close": float(c.close),
                        "volume": float(c.volume),
                    }
                    for c in velas
                ]
            )
            if marco.empty:
                print(f"  {etiqueta}: sin velas en el rango; se salta")
                continue
            marco["timestamp"] = pd.to_datetime(marco["timestamp"], utc=True)
            marco = marco.set_index("timestamp")

            # La direccion de la senal vive en el JSONB `metadata` de la
            # ocurrencia y hay que extraerla con `->>`: leerla del atributo ORM
            # resuelve contra el `MetaData` de la clase y revienta. Es la misma
            # trampa que documenta `backtesting.service._direction_column`.
            from sqlalchemy import Text, cast, func

            columna = PatternOccurrence.__table__.c.metadata
            direccion = cast(func.jsonb_extract_path_text(columna, "direction"), Text)
            con_direccion = db.execute(
                select(
                    PatternOccurrence.timestamp,
                    PatternOccurrence.pattern_name,
                    direccion,
                )
                .where(
                    PatternOccurrence.scan_job_id == job_id,
                    PatternOccurrence.timestamp >= desde,
                    PatternOccurrence.timestamp <= hasta,
                )
                .order_by(PatternOccurrence.timestamp)
            ).all()
            senales = pd.DataFrame(
                con_direccion, columns=["timestamp", "pattern_name", "direction"]
            )
            senales["timestamp"] = pd.to_datetime(senales["timestamp"], utc=True)

            # CSV y no parquet: el venv no trae `pyarrow`, y la diferencia son
            # unos cientos de KB en ficheros que ademas no se versionan.
            marco.to_csv(DESTINO / f"{etiqueta}_candles.csv.gz", compression="gzip")
            senales.to_csv(
                DESTINO / f"{etiqueta}_signals.csv.gz",
                compression="gzip",
                index=False,
            )
            print(
                f"  {etiqueta:14} {len(marco):>6} velas  {len(senales):>5} señales  "
                f"→ {DESTINO.name}/{etiqueta}_*.csv.gz"
            )
            escritos += 1
    return escritos


def _buscar_scan(db, prefijo: str, simbolo: str, timeframe: str):
    for job in db.scalars(
        select(PatternScanJob)
        .where(
            PatternScanJob.symbol == simbolo,
            PatternScanJob.timeframe == timeframe,
            PatternScanJob.status == PatternScanJobStatus.COMPLETED.value,
        )
        .order_by(PatternScanJob.created_at)
    ).all():
        if str(job.id).startswith(prefijo):
            return job
    return None


if __name__ == "__main__":
    total = exportar()
    print(f"\n{total} régimen(es) exportados a {DESTINO}")
    if total == 0:
        print("Sin datos: la prueba de fuego se saltará hasta que se exporten.")
