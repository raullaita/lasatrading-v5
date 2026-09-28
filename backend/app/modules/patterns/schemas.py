from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.modules.patterns import pattern_catalog as catalog
from app.modules.patterns.models import LogLevel, PatternScanJobStatus


class PatternParamSpecOut(BaseModel):
    """Parametro configurable de un patron, tal y como lo consume el frontend.

    Se serializa desde ``ParamSpec`` con ``from_attributes``, de modo que el
    ``PatternSelector`` puede generar sus inputs sin conocer el catalogo.
    """

    key: str
    label: str
    kind: str
    default: int | float
    minimum: int | float
    maximum: int | float
    step: int | float
    help: str = ""
    model_config = {"from_attributes": True}


class PatternDefinitionOut(BaseModel):
    """Entrada del catalogo expuesta en ``GET /api/v1/patterns/catalog``."""

    code: str
    group: str
    scanner: str
    name: str
    description: str
    direction: str
    short_label: str
    params: list[PatternParamSpecOut]
    required_features: list[str]

    @classmethod
    def from_definition(
        cls, definition: catalog.PatternDefinition
    ) -> "PatternDefinitionOut":
        return cls(
            code=definition.code,
            group=definition.group,
            scanner=definition.scanner,
            name=definition.name,
            description=definition.description,
            direction=definition.direction,
            short_label=definition.short_label,
            params=[
                PatternParamSpecOut.model_validate(spec)
                for spec in definition.param_spec
            ],
            required_features=list(definition.required_features()),
        )


class PatternCatalogOut(BaseModel):
    patterns: list[PatternDefinitionOut]


class PatternSelection(BaseModel):
    """Un patron elegido por el usuario, con sus parametros ya resueltos.

    Se usa en los tres sentidos: entrada de ``POST /scans``, contenido de la
    columna JSONB ``pattern_scan_jobs.patterns_config`` y salida de los jobs.
    """

    code: str
    params: dict[str, int | float] = Field(default_factory=dict)


class PatternScanConfig(BaseModel):
    symbol: str
    timeframe: str
    date_from: datetime
    date_to: datetime
    patterns: list[PatternSelection]

    @model_validator(mode="after")
    def _validate_patterns(self) -> "PatternScanConfig":
        if not self.patterns:
            raise ValueError("Debes seleccionar al menos un patron")

        codes = [p.code for p in self.patterns]
        duplicates = sorted({c for c in codes if codes.count(c) > 1})
        if duplicates:
            raise ValueError(f"Patrones duplicados: {', '.join(duplicates)}")

        unknown = catalog.unknown_codes(codes)
        if unknown:
            raise ValueError(f"Patrones desconocidos: {', '.join(unknown)}")
        return self


class ChartCandleOut(BaseModel):
    """Vela del grafico. A diferencia de ``DataCandleOut``, los OHLCV son
    ``float`` y no ``Decimal``: lightweight-charts los quiere como numero y el
    cliente no deberia estar convertiendo para pintar."""

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


class ChartIndicatorPointOut(BaseModel):
    timestamp: datetime
    value: float


class ChartMarkerOut(BaseModel):
    """Marker ya resuelto al formato de la libreria.

    ``position`` y ``shape`` son los literales que espera lightweight-charts, y
    los decide **el backend**: bullish -> ``belowBar`` + ``arrowUp`` en verde.
    Duplicar ese mapeo en el frontend haria que un cambio de color se aplicase
    a la mitad de las pantallas.
    """

    timestamp: datetime
    pattern_name: str
    position: Literal["aboveBar", "belowBar"]
    shape: Literal["arrowUp", "arrowDown"]
    color: str
    text: str
    details: dict


class ChartDataOut(BaseModel):
    """Respuesta comun de las dos rutas de grafico.

    Se declara ahora, cuando la ruta de escaneo ya llevaba varias pantallas sin
    un contrato en el servidor: el tipo del frontend era lo unico que fijaba la
    forma de la respuesta, asi que cualquier clave nueva era invisible para
    quien documenta la API.

    Los cuatro campos del muestreo (``total_points``, ``returned``, ``step``,
    ``sampled``) existen por una razon concreta: un grafico que enseña 1.500
    velas de un rango de 8.760, sin decirlo, se lee como el rango completo. Es el
    mismo motivo por el que ``BacktestEquitySeriesOut`` lleva ``total_points`` y
    ``returned``, y por el que una vez se perdio el cierre final de la curva.
    """

    symbol: str
    timeframe: str
    date_from: datetime | None = None
    date_to: datetime | None = None
    candles: list[ChartCandleOut]
    indicators: dict[str, list[ChartIndicatorPointOut]]
    markers: list[ChartMarkerOut]
    #: Indicadores pedidos explicitamente que no tienen ni un punto en el rango.
    #: No se omiten en silencio: la cobertura de ``features`` es irregular y sin
    #: este campo un ``ATR_14`` pedido en 2022 desapareceria sin dejar rastro.
    missing_indicators: list[str] = Field(default_factory=list)
    total_points: int = 0
    returned: int = 0
    #: Velas saltadas entre una pintada y la siguiente. 1 = sin muestrear.
    step: int = 1
    sampled: bool = False


class IndicatorAvailabilityOut(BaseModel):
    """Un indicador que hay en la base, con su cobertura real.

    La cobertura importa mas que la existencia: ``EMA_50`` existe para BTCUSDT
    pero solo desde julio de 2026, y ofrecerla en un rango de 2022 sin decirlo
    es la forma de que el usuario descubra la falta cuando ya esta mirando el
    grafico.
    """

    name: str
    params: dict
    date_from: datetime
    date_to: datetime
    points: int


class IndicatorAvailabilityListOut(BaseModel):
    symbol: str
    timeframe: str
    indicators: list[IndicatorAvailabilityOut] = Field(default_factory=list)


class PatternScanJobListItem(BaseModel):
    id: UUID
    status: PatternScanJobStatus
    symbol: str
    timeframe: str
    date_from: datetime
    date_to: datetime
    patterns_config: list[PatternSelection]
    total_candles: int
    processed_candles: int
    created_at: datetime
    finished_at: datetime | None = None
    model_config = {"from_attributes": True}


class PatternScanJobListOut(BaseModel):
    jobs: list[PatternScanJobListItem]
    total: int


class PatternScanJobResponse(BaseModel):
    id: UUID
    status: PatternScanJobStatus
    symbol: str
    timeframe: str
    date_from: datetime
    date_to: datetime
    patterns_config: list[PatternSelection]
    started_at: datetime | None = None
    finished_at: datetime | None = None
    total_candles: int
    processed_candles: int
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class PatternOccurrenceOut(BaseModel):
    """Una deteccion.

    ``details`` corresponde a la columna JSONB ``metadata`` de la tabla. Se
    llama ``details`` en la API porque ``metadata`` es un nombre reservado en
    las clases declarativas de SQLAlchemy y conviene no propagarlo al contrato.
    El nombre de la columna en base de datos sigue siendo ``metadata``.
    """

    timestamp: datetime
    symbol: str
    timeframe: str
    pattern_name: str
    scan_job_id: UUID
    details: dict = Field(default_factory=dict)
    model_config = {"from_attributes": True}


class PatternOccurrenceListOut(BaseModel):
    occurrences: list[PatternOccurrenceOut]
    total: int


class PatternScanLogOut(BaseModel):
    id: UUID
    timestamp: datetime
    level: LogLevel
    message: str
    progress: int | None = None
    model_config = {"from_attributes": True}


class BatchDeleteBody(BaseModel):
    job_ids: list[UUID]


class PatternAvailableDataOut(BaseModel):
    """Un par (simbolo, timeframe) escaneable, en ``GET /data/available``.

    ``indicators`` lista los nombres de feature ya precalculados para ese par.
    Se expone para que el frontend pueda avisar *antes* de encolar un escaneo
    de que faltan features, en vez de dejar que el job falle con
    ``MissingFeaturesError`` y haya que leer los logs para enterarse.
    """

    symbol: str
    timeframe: str
    candles: int
    first_candle: datetime
    last_candle: datetime
    indicators: list[str]


class PatternAvailableDataListOut(BaseModel):
    data: list[PatternAvailableDataOut]


class PatternOccurrencesSummaryOut(BaseModel):
    """Agregados de ``GET /occurrences/summary``."""

    total: int
    distinct_patterns: int
    distinct_symbols: int
    first_occurrence: datetime | None = None
    last_occurrence: datetime | None = None
    bullish: int
    bearish: int
    by_pattern: list[dict]
    by_symbol: list[dict]
    by_timeframe: list[dict]
