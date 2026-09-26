from datetime import datetime
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
