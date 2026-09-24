from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.modules.data_import.models import ImportMode, ImportStatus


class BatchDeleteBody(BaseModel):
    job_ids: list[UUID]


class ImportConfig(BaseModel):
    symbols: list[str] = Field(min_length=1)
    timeframes: list[str] = Field(min_length=1)
    date_from: datetime
    date_to: datetime
    import_mode: ImportMode = ImportMode.MERGE

    @model_validator(mode="after")
    def check_date_range(self) -> "ImportConfig":
        if self.date_from >= self.date_to:
            raise ValueError("date_from debe ser anterior a date_to")
        return self


class BinanceSymbolOut(BaseModel):
    symbol: str
    status: str
    base_asset: str
    quote_asset: str


class CandleRaw(BaseModel):
    open_time_ms: int
    close_time_ms: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    quote_volume: Decimal
    num_trades: int


class StartImportOut(BaseModel):
    job_id: UUID


class CombinationOut(BaseModel):
    id: UUID
    symbol: str
    timeframe: str
    status: ImportStatus
    started_at: datetime | None = None
    finished_at: datetime | None = None
    candles_downloaded: int = 0
    candles_inserted: int = 0
    candles_updated: int = 0
    candles_skipped: int = 0
    first_candle_at: datetime | None = None
    last_candle_at: datetime | None = None
    error_message: str | None = None
    model_config = {"from_attributes": True}


class JobStatusOut(BaseModel):
    id: UUID
    status: ImportStatus
    source_type: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    symbols: list[str]
    timeframes: list[str]
    date_from: datetime
    date_to: datetime
    import_mode: ImportMode
    total_combinations: int = 0
    completed_combinations: int = 0
    failed_combinations: int = 0
    total_candles_downloaded: int = 0
    total_candles_inserted: int = 0
    total_candles_updated: int = 0
    total_candles_skipped: int = 0
    error_summary: dict = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    combinations: list[CombinationOut] = Field(default_factory=list)
    model_config = {"from_attributes": True}


class LogOut(BaseModel):
    id: UUID
    timestamp: datetime
    level: str
    message: str
    progress: int | None = None
    model_config = {"from_attributes": True}


class JobListItem(BaseModel):
    id: UUID
    status: ImportStatus
    symbols: list[str]
    timeframes: list[str]
    date_from: datetime
    date_to: datetime
    import_mode: ImportMode
    total_combinations: int = 0
    completed_combinations: int = 0
    failed_combinations: int = 0
    total_candles_downloaded: int = 0
    total_candles_inserted: int = 0
    total_candles_updated: int = 0
    total_candles_skipped: int = 0
    created_at: datetime
    finished_at: datetime | None = None
    model_config = {"from_attributes": True}


class JobListOut(BaseModel):
    jobs: list[JobListItem]
    total: int


class PreviewRow(BaseModel):
    timestamp: datetime
    symbol: str
    timeframe: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    model_config = {"from_attributes": True}


class PreviewOut(BaseModel):
    job_id: UUID
    symbol: str | None = None
    timeframe: str | None = None
    rows: list[PreviewRow]


class QualityStats(BaseModel):
    discarded_candles: int = 0
    error_kinds: dict = Field(default_factory=dict)


class StatsOut(BaseModel):
    job_id: UUID
    total_candles_downloaded: int = 0
    total_candles_inserted: int = 0
    total_candles_updated: int = 0
    total_candles_skipped: int = 0
    combinations_completed: int = 0
    combinations_failed: int = 0
    quality: QualityStats = Field(default_factory=QualityStats)
    gaps: list[dict] = Field(default_factory=list)
