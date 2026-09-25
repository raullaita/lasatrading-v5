from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.modules.features.models import FeatureJobStatus


class IndicatorConfig(BaseModel):
    name: str
    params: dict = Field(default_factory=dict)


class FeatureJobConfig(BaseModel):
    symbol: str
    timeframe: str
    date_from: datetime
    date_to: datetime
    indicators: list[IndicatorConfig]


class FeatureJobListItem(BaseModel):
    id: UUID
    status: FeatureJobStatus
    symbol: str
    timeframe: str
    date_from: datetime
    date_to: datetime
    indicators_config: list[IndicatorConfig]
    total_candles: int
    processed_candles: int
    created_at: datetime
    finished_at: datetime | None = None
    model_config = {"from_attributes": True}


class FeatureJobListOut(BaseModel):
    jobs: list[FeatureJobListItem]
    total: int


class FeatureJobResponse(BaseModel):
    id: UUID
    status: FeatureJobStatus
    symbol: str
    timeframe: str
    date_from: datetime
    date_to: datetime
    indicators_config: list[IndicatorConfig]
    started_at: datetime | None = None
    finished_at: datetime | None = None
    total_candles: int
    processed_candles: int
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class FeaturePreviewRow(BaseModel):
    timestamp: datetime
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    volume: float | None = None
    indicators: dict[str, float]
    model_config = {"from_attributes": True}


class FeaturePreviewOut(BaseModel):
    job_id: UUID
    symbol: str
    timeframe: str
    rows: list[FeaturePreviewRow]


class BatchDeleteBody(BaseModel):
    job_ids: list[UUID]


class FeatureLogOut(BaseModel):
    id: UUID
    timestamp: datetime
    level: str
    message: str
    progress: int | None = None
    model_config = {"from_attributes": True}
