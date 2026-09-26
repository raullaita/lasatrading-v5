"""Normaliza los nombres de las features a su forma canónica.

Antes de esta migración, ``FeatureService._save_features`` prefijaba el nombre
de la columna con el nombre del indicador cuando la columna no empezaba por él.
Eso producía nombres inconsistentes:

* ``MACD``        -> ``MACD_12_26_9``        (ya empezaba por "MACD": se quedaba corto)
* ``MACD_signal`` -> ``MACDs_12_26_9``
* ``MACD_hist``   -> ``MACDh_12_26_9``
* ``BBU_20_2.0``  -> ``BBANDS_BBU_20_2.0``  (se le anteponía "BBANDS_")
* ``BBL_20_2.0``  -> ``BBANDS_BBL_20_2.0``

El motor de detección de patrones (Tarea 4) depende de los nombres canónicos,
por lo que aquí se renombran las filas ya calculadas.

``features`` es una hipertabla de TimescaleDB y las restricciones de UPDATE
varían entre versiones, así que el renombrado se hace sobre una tabla auxiliar:
se copia, se renombra allí y se reinsertan solo las filas afectadas.

Las migraciones de Alembic son instantáneas inmutables del esquema: no se importa
código de ``app/`` porque podría cambiar y romper la reproducibilidad del
upgrade. Por eso las constantes están replicadas aquí a propósito.
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "9c2e5f71a8d4"
down_revision = "4d84767edeb1"
branch_labels = None
depends_on = None


# Nombres MACD heredados -> prefijo canónico (línea, señal, histograma).
MACD_LEGACY_PREFIXES = {
    "MACD": "MACD",
    "MACD_signal": "MACDs",
    "MACD_hist": "MACDh",
}
MACD_DEFAULTS = {"fast": 12, "slow": 26, "signal": 9}

BBANDS_LEGACY_PREFIX = "BBANDS_"
BBANDS_CANONICAL_PREFIXES = ("BBU_", "BBM_", "BBL_")

FEATURE_COLUMNS = (
    "timestamp",
    "symbol",
    "timeframe",
    "indicator_name",
    "indicator_params",
    "value",
    "feature_job_id",
)
PRIMARY_KEY = ("timestamp", "symbol", "timeframe", "indicator_name")

STAGING_TABLE = "features_rename_staging"

MACD_CANONICAL_REGEX = r"^MACD(s|h)?_[0-9]+_[0-9]+_[0-9]+$"
BBANDS_CANONICAL_REGEX = r"^BB[UML]_[0-9]+_"

# `left()` en lugar de `LIKE 'BBANDS_BB%'` porque en LIKE el guion bajo es un
# comodín de un solo carácter.
LEGACY_PREDICATE = (
    "indicator_name = ANY(:macd_names) OR left(indicator_name, 9) = 'BBANDS_BB'"
)
CANONICAL_PREDICATE = "indicator_name ~ :macd_regex OR indicator_name ~ :bbands_regex"


def _predicate_params() -> dict:
    """Parámetros de enlace de ambos predicados (SQL los ignora si no aparecen)."""
    return {
        "macd_names": list(MACD_LEGACY_PREFIXES),
        "macd_regex": MACD_CANONICAL_REGEX,
        "bbands_regex": BBANDS_CANONICAL_REGEX,
    }


def _as_int(value, default: int) -> int:
    """Convierte a int tolerando 12, 12.0, "12" y "12.0"."""
    if value is None or value == "":
        return default
    return int(float(value))


def _canonical_name(old_name: str, params: dict | None) -> str:
    """Nombre canónico a partir de un nombre heredado y sus parámetros."""
    if old_name in MACD_LEGACY_PREFIXES:
        values = params or {}
        return (
            f"{MACD_LEGACY_PREFIXES[old_name]}"
            f"_{_as_int(values.get('fast'), MACD_DEFAULTS['fast'])}"
            f"_{_as_int(values.get('slow'), MACD_DEFAULTS['slow'])}"
            f"_{_as_int(values.get('signal'), MACD_DEFAULTS['signal'])}"
        )
    if old_name.startswith(BBANDS_LEGACY_PREFIX):
        return old_name[len(BBANDS_LEGACY_PREFIX) :]
    return old_name


def _legacy_name(canonical_name: str) -> str:
    """Inversa de _canonical_name para un nombre canónico conocido."""
    for legacy, prefix in MACD_LEGACY_PREFIXES.items():
        if canonical_name.startswith(f"{prefix}_"):
            return legacy
    for prefix in BBANDS_CANONICAL_PREFIXES:
        if canonical_name.startswith(prefix):
            return f"{BBANDS_LEGACY_PREFIX}{canonical_name}"
    return canonical_name


def _distinct_variants(bind, predicate: str) -> list[tuple[str, dict]]:
    """Pares (indicator_name, indicator_params) distintos a renombrar.

    Se itera sobre variantes de nombre —como máximo una por ejecución de job— y
    nunca sobre filas, para resolver cada nombre en Python con la misma
    semántica que usa el cálculo de indicadores.
    """
    rows = bind.execute(
        sa.text(
            "SELECT DISTINCT indicator_name, indicator_params "
            f"FROM features WHERE {predicate}"
        ),
        _predicate_params(),
    ).all()
    return [(row[0], row[1] or {}) for row in rows]


def _migrate(bind, select_predicate: str, resolve) -> None:
    total = bind.execute(sa.text("SELECT count(*) FROM features")).scalar() or 0
    if total == 0:
        return

    bind.execute(sa.text(f"DROP TABLE IF EXISTS {STAGING_TABLE}"))
    bind.execute(
        sa.text(f"CREATE TABLE {STAGING_TABLE} (LIKE features INCLUDING DEFAULTS)")
    )
    bind.execute(sa.text(f"INSERT INTO {STAGING_TABLE} SELECT * FROM features"))

    # El renombrado se acota por (indicator_name, indicator_params) y no solo por
    # el nombre: el sufijo canónico depende de los parámetros, así que dos
    # símbolos con MACD 12/26/9 y 5/35/5 comparten nombre heredado y destino
    # distinto. La igualdad de jsonb es semántica (independiente del orden de
    # claves y 12 == 12.0), por lo que el round-trip read/compare/rewrite es
    # seguro.
    #
    # Los conjuntos de origen y destino se llevan por separado porque un mismo
    # nombre heredado puede renombrarse a varios destinos distintos según sus
    # parámetros: un mapa nombre->nombre aplastaría esas variantes y perdería
    # filas al reinsertar.
    old_names: set[str] = set()
    new_names: set[str] = set()
    renamed_rows = 0
    for old_name, params in _distinct_variants(bind, select_predicate):
        new_name = resolve(old_name, params)
        if new_name == old_name:
            continue
        result = bind.execute(
            sa.text(
                f"UPDATE {STAGING_TABLE} SET indicator_name = :new_name "
                "WHERE indicator_name = :old_name "
                "AND indicator_params = CAST(:params AS jsonb)"
            ),
            {
                "new_name": new_name,
                "old_name": old_name,
                "params": json.dumps(params),
            },
        )
        renamed_rows += result.rowcount or 0
        old_names.add(old_name)
        new_names.add(new_name)

    if renamed_rows == 0:
        bind.execute(sa.text(f"DROP TABLE {STAGING_TABLE}"))
        return

    insert_params = _predicate_params() | {"names": sorted(new_names)}

    # 1. Se borran las filas de origen: sus nombres heredados quedan huérfanos.
    bind.execute(
        sa.text("DELETE FROM features WHERE indicator_name = ANY(:names)"),
        {"names": sorted(old_names)},
    )

    # 2. Se reinsertan las renombradas. DISTINCT ON evita repetir fila si dos
    #    nombres distintos convergían en el mismo destino, y ON CONFLICT resuelve
    #    la colisión con una fila canónica preexistente (misma clave primaria,
    #    así que es un duplicado por definición y prevalece la tabla auxiliar).
    columns = ", ".join(FEATURE_COLUMNS)
    order_by = ", ".join(PRIMARY_KEY)
    bind.execute(
        sa.text(
            f"INSERT INTO features ({columns}) "
            f"SELECT DISTINCT ON ({order_by}) {columns} FROM {STAGING_TABLE} "
            "WHERE indicator_name = ANY(:names) "
            f"ORDER BY {order_by} "
            "ON CONFLICT (timestamp, symbol, timeframe, indicator_name) "
            "DO UPDATE SET indicator_params = EXCLUDED.indicator_params, "
            "value = EXCLUDED.value, "
            "feature_job_id = EXCLUDED.feature_job_id"
        ),
        insert_params,
    )

    bind.execute(sa.text(f"DROP TABLE {STAGING_TABLE}"))


def upgrade() -> None:
    _migrate(op.get_bind(), LEGACY_PREDICATE, _canonical_name)


def downgrade() -> None:
    # El nombre heredado no depende de los parámetros, así que se descartan.
    _migrate(
        op.get_bind(), CANONICAL_PREDICATE, lambda name, _params: _legacy_name(name)
    )
