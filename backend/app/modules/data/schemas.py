from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class DataGroupSummary(BaseModel):
    symbol: str
    timeframe: str
    total_candles: int
    first_timestamp: datetime
    last_timestamp: datetime


class DataSummaryOut(BaseModel):
    groups: list[DataGroupSummary]


class DataCandleOut(BaseModel):
    timestamp: datetime
    symbol: str
    timeframe: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    model_config = {"from_attributes": True}


class DataPreviewOut(BaseModel):
    symbol: str
    timeframe: str
    rows: list[DataCandleOut]


class DataDeleteOut(BaseModel):
    symbol: str
    timeframe: str
    deleted: int
