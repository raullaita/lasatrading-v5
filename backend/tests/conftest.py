"""Fixtures compartidas de los tests del backend.

Dos bloques con propositos distintos:

1. **Tests puros** (scanner, candles, motor de backtesting): ni base de datos,
   ni Celery, ni red. Corren en segundos sin tocar PostgreSQL, que es la ventaja
   de haber dejado la deteccion y la simulacion como funciones puras que
   reciben un DataFrame y devuelven otro.

2. **Tests de servicio** (backtesting): necesitan PostgreSQL de verdad, porque
   lo que se prueba es precisamente la persistencia, la cascada y los
   agregados en SQL. Apuntan a una base **aparte** (``lasa_test``) creada al
   vuelo: nunca a la de desarrollo, cuyos datos son los del scan de referencia.
   Si no hay PostgreSQL alcanzable, estos tests se marcan como ``skip`` en vez de
   fallar, para que ``pytest`` siga siendo ejecutable sin base de datos.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import numpy as np
import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Base de datos de test: se prepara ANTES de importar nada de ``app``.
#
# ``app.core.database`` crea su engine en el momento de importarse, leyendo
# ``DATABASE_URL`` de ``get_settings()``. Pydantic da prioridad a las variables de
# entorno sobre el fichero ``.env``, asi que fijando ``DATABASE_URL`` aqui se
# cambia el motor de todos los modulos que se importen despues. Por eso esto va
# antes que el import de ``app.modules.patterns.scanner``.
# ---------------------------------------------------------------------------
TEST_DB_NAME = "lasa_test"


def _configured_database_url() -> str | None:
    """URL de la base de desarrollo, tal y como esta en ``.env``."""
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return os.environ.get("DATABASE_URL")
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("DATABASE_URL="):
            return line.split("=", 1)[1].strip().strip("'\"")
    return os.environ.get("DATABASE_URL")


def _with_db_name(url: str, name: str) -> str:
    parts = urlsplit(url)
    return urlunsplit(parts._replace(path=f"/{name}"))


def _prepare_test_database() -> bool:
    """Crea ``lasa_test`` si no existe y apunta ``DATABASE_URL`` a ella.

    Devuelve ``False`` si no se puede conectar, para que los tests de base de
    datos se salten en vez de reventar la sesion entera.
    """
    base_url = _configured_database_url()
    if not base_url:
        return False
    test_url = _with_db_name(base_url, TEST_DB_NAME)
    try:
        from sqlalchemy import create_engine

        # AUTOCOMMIT es obligatorio: ``CREATE DATABASE`` no puede correr dentro
        # de una transaccion y SQLAlchemy abre una en cuanto se ejecuta algo.
        # Sin esto el error es "CREATE DATABASE cannot run inside a transaction
        # block" y la base de test no llega a existir nunca.
        admin = create_engine(
            _with_db_name(base_url, "postgres"), isolation_level="AUTOCOMMIT"
        ).raw_connection()
        try:
            with admin.cursor() as cursor:
                cursor.execute(
                    "SELECT 1 FROM pg_database WHERE datname = %s", (TEST_DB_NAME,)
                )
                if cursor.fetchone() is None:
                    cursor.execute(f'CREATE DATABASE "{TEST_DB_NAME}"')
        finally:
            admin.close()
        engine = create_engine(test_url)
        engine.connect().close()
    except Exception:  # noqa: BLE001 - sin base de datos, se salta el bloque
        return False
    os.environ["DATABASE_URL"] = test_url
    return True


DB_AVAILABLE = _prepare_test_database()

# ``RESULT_COLUMNS`` se importa siempre, tenga o no PostgreSQL. Es una constante
# pura de pandas del modulo scanner, que no toca la base de datos, asi que
# sustituirla por ``[]`` cuando falta la base rompia todos los tests de
# scanners: ``_check`` compara las columnas del resultado contra esa lista
# vacia y fallaba en el primero. Sin base de datos lo que debe caerse son los
# fixtures de BD, no las pruebas de codigo puro.
from app.modules.patterns.scanner import RESULT_COLUMNS  # noqa: E402

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


# ---------------------------------------------------------------------------
# Fixtures de base de datos, para los tests de servicio
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def db_schema():
    """Crea el esquema completo una vez por sesion.

    Se usa ``metadata.create_all`` en vez de ``alembic upgrade head`` porque los
    tests necesitan una base vacia y reproducible, no el historial de
    migraciones. Lo que si se prueba con migraciones de verdad es el despliegue,
    no el servicio.
    """
    if not DB_AVAILABLE:
        pytest.skip("PostgreSQL no disponible")
    from app.core.database import Base, engine

    # Los modelos se importan aqui, no arriba, para que ``Base.metadata`` los
    # conozca sin que el conftest dependa de cada modulo.
    from app.modules.backtesting import models as backtesting_models  # noqa: F401
    from app.modules.data_import import models as data_import_models  # noqa: F401
    from app.modules.features import models as features_models  # noqa: F401
    from app.modules.patterns import models as patterns_models  # noqa: F401

    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)


@pytest.fixture
def db(db_schema):
    """Sesion limpia por test. Vacia las tablas al terminar, no al empezar.

    La lista de tablas sale de ``Base.metadata.sorted_tables`` en vez de estar
    escrita a mano. Una lista fija se queda obsoleta en cuanto se anade un modulo
    y el truncate falla con "relation does not exist" en un test que no tiene
    nada que ver con el cambio.
    """
    from app.core.database import Base, SessionLocal

    with SessionLocal() as session:
        yield session
    # ``sorted_tables`` va de padres a hijos; al reves, los hijos se vacian
    # antes que los padres. ``CASCADE`` lo resolveria igual, pero el orden lo
    # hace innecesario depender de el.
    tablas = ", ".join(tabla.name for tabla in reversed(Base.metadata.sorted_tables))
    with db_schema.begin() as connection:
        connection.exec_driver_sql(f"TRUNCATE {tablas} RESTART IDENTITY CASCADE")


@pytest.fixture
def service():
    from app.modules.backtesting.service import BacktestService

    return BacktestService()


#: Hora 0 del rango de los tests. Todas las velas de los fixtures caen en la
#: misma hora, con lo que un desfase de un dia se ve enseguida.
T0 = "2024-01-01T00:00:00Z"


@pytest.fixture
def scan_job(db):
    """Escaneo completado y listo para simular, con velas y ocurrencias.

    Es el equivalente en miniatura de ``02a2412a``: 60 velas, 4 patrones y
    senales en las horas 5, 15, 25 y 35, separadas 10 horas para que la primera
    operacion se cierre antes de que llegue la siguiente.
    """
    from datetime import datetime, timedelta, timezone

    from app.modules.data_import.models import Candle
    from app.modules.patterns.models import (
        PatternOccurrence,
        PatternScanJob,
        PatternScanJobStatus,
    )

    inicio = datetime(2024, 1, 1, tzinfo=timezone.utc)
    fin = inicio + timedelta(hours=59)
    job = PatternScanJob(
        symbol="TESTUSDT",
        timeframe="1h",
        date_from=inicio,
        date_to=fin,
        status=PatternScanJobStatus.COMPLETED.value,
        total_candles=60,
        processed_candles=60,
    )
    db.add(job)
    db.flush()

    # Velas en gently ramp para que haya highs y lows con recorrido. Se
    # necesitan lows/altos que no toquen los niveles del stop, asi que el
    # recorrido es pequeno frente al 1%.
    for offset in range(60):
        base = 100.0 + offset * 0.05
        db.add(
            Candle(
                timestamp=inicio + timedelta(hours=offset),
                symbol="TESTUSDT",
                timeframe="1h",
                open=base,
                high=base + 0.3,
                low=base - 0.3,
                close=base + 0.1,
                volume=10.0,
            )
        )

    senales = [
        (5, "MACD_CROSS_BULLISH", "bullish"),
        (15, "ENGULFING_BEARISH", "bearish"),
        (25, "RSI_EXIT_OVERSOLD", "bullish"),
        (35, "MA_CROSS_BEARISH", "bearish"),
    ]
    for hora, nombre, direccion in senales:
        db.add(
            PatternOccurrence(
                timestamp=inicio + timedelta(hours=hora),
                symbol="TESTUSDT",
                timeframe="1h",
                pattern_name=nombre,
                scan_job_id=job.id,
                # ``details``, no ``metadata``: la columna en base de datos se
                # llama "metadata" pero el atributo mapeado se renombra porque
                # ``metadata`` esta reservado en las clases declarativas. Pasar
                # ``metadata=`` no falla, se guarda como atributo suelto de
                # Python y la columna se queda con su ``{}`` por defecto, lo
                # que deja las señales sin dirección y sin avisar.
                details={"direction": direccion},
            )
        )
    db.commit()
    return job
