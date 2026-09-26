"""Catalogo de patrones de trading soportados por el motor de escaneo.

Vive en memoria (no requiere tabla en base de datos) y no importa SQLAlchemy,
de modo que el router puede consumirlo para validar peticiones y para
serializar el catalogo que consume el frontend.

Los resolvers de ``required_features`` replican exactamente los f-strings de
``FeatureService._calculate_indicator``: si cambia el criterio de nombrado de
una feature, hay que cambiar el resolver correspondiente en este archivo.
"""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

PatternDirection = Literal["bullish", "bearish"]
ParamKind = Literal["int", "float"]

ParamValue = int | float
FeatureResolver = Callable[[Mapping[str, ParamValue]], tuple[str, ...]]


def _no_features(_params: Mapping[str, ParamValue]) -> tuple[str, ...]:
    return ()


@dataclass(frozen=True, slots=True)
class ParamSpec:
    """Parametro configurable de un patron.

    El frontend genera los inputs a partir de esta spec, de modo que anadir un
    parametro al catalogo no obliga a tocar la interfaz.
    """

    key: str
    label: str
    kind: ParamKind
    default: ParamValue
    minimum: ParamValue
    maximum: ParamValue
    step: ParamValue = 1
    help: str = ""


@dataclass(frozen=True, slots=True)
class PatternDefinition:
    """Definicion de un patron direccional (una entrada del catalogo)."""

    code: str
    group: str
    scanner: str
    name: str
    description: str
    direction: PatternDirection
    short_label: str
    param_spec: tuple[ParamSpec, ...] = ()
    feature_resolver: FeatureResolver = _no_features

    @property
    def default_params(self) -> Mapping[str, ParamValue]:
        return MappingProxyType({spec.key: spec.default for spec in self.param_spec})

    def resolve_params(
        self, overrides: Mapping[str, ParamValue] | None = None
    ) -> dict[str, ParamValue]:
        """Fusiona defaults y overrides, coaccionando al tipo y acotando al rango.

        Acotar es deliberado: un ``fast_length`` fuera de rango generaria un
        nombre de feature que no existe en la tabla ``features`` y el job
        fallaria mas tarde con un error poco claro.
        """
        resolved: dict[str, ParamValue] = {}
        for spec in self.param_spec:
            try:
                value: ParamValue = float((overrides or {}).get(spec.key, spec.default))
            except (TypeError, ValueError):
                value = spec.default
            if spec.kind == "int":
                value = int(value)
            resolved[spec.key] = max(spec.minimum, min(spec.maximum, value))
        return resolved

    def required_features(
        self, params: Mapping[str, ParamValue] | None = None
    ) -> tuple[str, ...]:
        """Features que este patron necesita, segun los parametros del job."""
        return tuple(self.feature_resolver(self.resolve_params(params)))


def _as_int(params: Mapping[str, ParamValue], key: str, default: int) -> int:
    return int(float(params.get(key, default)))


def _as_float(params: Mapping[str, ParamValue], key: str, default: float) -> float:
    return float(params.get(key, default))


def _macd_features(params: Mapping[str, ParamValue]) -> tuple[str, ...]:
    suffix = (
        f"{_as_int(params, 'fast', 12)}"
        f"_{_as_int(params, 'slow', 26)}"
        f"_{_as_int(params, 'signal', 9)}"
    )
    return (f"MACD_{suffix}", f"MACDs_{suffix}")


def _rsi_features(params: Mapping[str, ParamValue]) -> tuple[str, ...]:
    return (f"RSI_{_as_int(params, 'length', 14)}",)


def _bbands_features(params: Mapping[str, ParamValue]) -> tuple[str, ...]:
    length = _as_int(params, "length", 20)
    std = _as_float(params, "std", 2.0)
    return (f"BBU_{length}_{std}", f"BBL_{length}_{std}")


def _ema_crossover_features(params: Mapping[str, ParamValue]) -> tuple[str, ...]:
    return (
        f"EMA_{_as_int(params, 'fast_length', 20)}",
        f"EMA_{_as_int(params, 'slow_length', 50)}",
    )


_MACD_PARAMS = (
    ParamSpec("fast", "EMA rapida", "int", 12, 2, 100),
    ParamSpec("slow", "EMA lenta", "int", 26, 3, 200),
    ParamSpec("signal", "Linea de senal", "int", 9, 2, 100),
)
_RSI_PARAMS = (
    ParamSpec(
        "threshold_up",
        "Umbral de sobrecompra",
        "int",
        70,
        50,
        90,
        help="Se dispara cuando el RSI cruza por debajo de este valor.",
    ),
    ParamSpec(
        "threshold_down",
        "Umbral de sobreventa",
        "int",
        30,
        10,
        50,
        help="Se dispara cuando el RSI cruza por encima de este valor.",
    ),
    ParamSpec("length", "Periodo del RSI", "int", 14, 2, 100),
)
_BBANDS_PARAMS = (
    ParamSpec("length", "Longitud", "int", 20, 5, 200),
    ParamSpec("std", "Desviaciones estandar", "float", 2.0, 0.5, 5.0, 0.1),
)
_MA_PARAMS = (
    ParamSpec("fast_length", "EMA rapida", "int", 20, 2, 200),
    ParamSpec("slow_length", "EMA lenta", "int", 50, 3, 400),
)


PATTERN_CATALOG: dict[str, PatternDefinition] = {
    definition.code: definition
    for definition in (
        PatternDefinition(
            code="MACD_CROSS_BULLISH",
            group="macd_crossover",
            scanner="scan_macd_crossover",
            name="Cruce alcista de MACD",
            description=(
                "La linea MACD cruza por encima de la linea de senal. La deteccion "
                "se hace sobre la diferencia entre ambas lineas, de modo que un cruce "
                "ocurrido por debajo de cero tambien se registra."
            ),
            direction="bullish",
            short_label="MACD Alcista",
            param_spec=_MACD_PARAMS,
            feature_resolver=_macd_features,
        ),
        PatternDefinition(
            code="MACD_CROSS_BEARISH",
            group="macd_crossover",
            scanner="scan_macd_crossover",
            name="Cruce bajista de MACD",
            description=(
                "La linea MACD cruza por debajo de la linea de senal, evaluando la "
                "diferencia entre ambas lineas."
            ),
            direction="bearish",
            short_label="MACD Bajista",
            param_spec=_MACD_PARAMS,
            feature_resolver=_macd_features,
        ),
        PatternDefinition(
            code="RSI_EXIT_OVERBOUGHT",
            group="rsi_extremes",
            scanner="scan_rsi_extremes",
            name="Salida de sobrecompra (RSI)",
            description=(
                "El RSI cruza hacia abajo desde region de sobrecompra, es decir, pasa "
                "de estar por encima del umbral a estar por debajo. No basta con que "
                "el RSI sea alto: se exige un cruce de umbral."
            ),
            direction="bearish",
            short_label="RSI Sobrecompra",
            param_spec=_RSI_PARAMS,
            feature_resolver=_rsi_features,
        ),
        PatternDefinition(
            code="RSI_EXIT_OVERSOLD",
            group="rsi_extremes",
            scanner="scan_rsi_extremes",
            name="Salida de sobreventa (RSI)",
            description=(
                "El RSI cruza hacia arriba desde region de sobreventa, es decir, pasa "
                "de estar por debajo del umbral a estar por encima. No basta con que "
                "el RSI sea bajo: se exige un cruce de umbral."
            ),
            direction="bullish",
            short_label="RSI Sobreventa",
            param_spec=_RSI_PARAMS,
            feature_resolver=_rsi_features,
        ),
        PatternDefinition(
            code="BB_BREAKOUT_UPPER",
            group="bollinger_breakout",
            scanner="scan_bollinger_breakout",
            name="Ruptura de banda superior",
            description=(
                "El cierre de la vela cruza hacia arriba la banda superior de "
                "Bollinger: la vela anterior estaba en o por debajo de la banda y la "
                "actual cierra por encima."
            ),
            direction="bullish",
            short_label="BB Ruptura sup.",
            param_spec=_BBANDS_PARAMS,
            feature_resolver=_bbands_features,
        ),
        PatternDefinition(
            code="BB_BREAKOUT_LOWER",
            group="bollinger_breakout",
            scanner="scan_bollinger_breakout",
            name="Ruptura de banda inferior",
            description=(
                "El cierre de la vela cruza hacia abajo la banda inferior de "
                "Bollinger: la vela anterior estaba en o por encima de la banda y la "
                "actual cierra por debajo."
            ),
            direction="bearish",
            short_label="BB Ruptura inf.",
            param_spec=_BBANDS_PARAMS,
            feature_resolver=_bbands_features,
        ),
        PatternDefinition(
            code="MA_CROSS_BULLISH",
            group="ma_crossover",
            scanner="scan_ma_crossover",
            name="Cruce alcista de medias",
            description=(
                "Una EMA rapida cruza por encima de una EMA lenta. Las longitudes son "
                "configurables y determinan que features se necesitan, por lo que "
                "deben existir features EMA para esos periodos exactos."
            ),
            direction="bullish",
            short_label="Medias Alcista",
            param_spec=_MA_PARAMS,
            feature_resolver=_ema_crossover_features,
        ),
        PatternDefinition(
            code="MA_CROSS_BEARISH",
            group="ma_crossover",
            scanner="scan_ma_crossover",
            name="Cruce bajista de medias",
            description=(
                "Una EMA rapida cruza por debajo de una EMA lenta. Las longitudes son "
                "configurables y determinan que features se necesitan."
            ),
            direction="bearish",
            short_label="Medias Bajista",
            param_spec=_MA_PARAMS,
            feature_resolver=_ema_crossover_features,
        ),
        PatternDefinition(
            code="ENGULFING_BULLISH",
            group="engulfing",
            scanner="scan_engulfing",
            name="Vela envolvente alcista",
            description=(
                "El cuerpo de la vela actual envuelve por completo al cuerpo de la "
                "vela anterior, que era bajista. Es un patron puro de precio: no "
                "requiere ninguna feature."
            ),
            direction="bullish",
            short_label="Envolvente Alcista",
            feature_resolver=_no_features,
        ),
        PatternDefinition(
            code="ENGULFING_BEARISH",
            group="engulfing",
            scanner="scan_engulfing",
            name="Vela envolvente bajista",
            description=(
                "El cuerpo de la vela actual envuelve por completo al cuerpo de la "
                "vela anterior, que era alcista. Es un patron puro de precio: no "
                "requiere ninguna feature."
            ),
            direction="bearish",
            short_label="Envolvente Bajista",
            feature_resolver=_no_features,
        ),
    )
}

PATTERN_CODES: tuple[str, ...] = tuple(PATTERN_CATALOG)


def list_catalog() -> tuple[PatternDefinition, ...]:
    return tuple(PATTERN_CATALOG.values())


def get_definition(code: str) -> PatternDefinition | None:
    return PATTERN_CATALOG.get(code)


def unknown_codes(codes: Iterable[str]) -> tuple[str, ...]:
    return tuple(code for code in codes if code not in PATTERN_CATALOG)


def required_features_for(
    codes: Iterable[str],
    params_by_code: Mapping[str, Mapping[str, ParamValue]] | None = None,
) -> tuple[str, ...]:
    """Union, sin repetir y en orden estable, de las features exigidas."""
    features: list[str] = []
    for code in codes:
        definition = get_definition(code)
        if definition is None:
            continue
        params = (params_by_code or {}).get(code)
        for feature in definition.required_features(params):
            if feature not in features:
                features.append(feature)
    return tuple(features)


def scanners_for(codes: Iterable[str]) -> tuple[str, ...]:
    """Metodos de PatternScanner a ejecutar, sin repetir y en orden estable."""
    scanners: list[str] = []
    for code in codes:
        definition = get_definition(code)
        if definition is None or definition.scanner in scanners:
            continue
        scanners.append(definition.scanner)
    return tuple(scanners)
