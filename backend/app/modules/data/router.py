from fastapi import APIRouter, Depends, Query
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.data.schemas import (
    DataCandleOut,
    DataDeleteOut,
    DataGroupSummary,
    DataPreviewOut,
    DataSummaryOut,
)
from app.modules.data_import.models import Candle

router = APIRouter(prefix="/api/v1/data", tags=["data"])


@router.get("/summary", response_model=DataSummaryOut)
def data_summary(db: Session = Depends(get_db)):
    rows = db.execute(
        select(
            Candle.symbol,
            Candle.timeframe,
            func.count(Candle.timestamp).label("total_candles"),
            func.min(Candle.timestamp).label("first_timestamp"),
            func.max(Candle.timestamp).label("last_timestamp"),
        )
        .group_by(Candle.symbol, Candle.timeframe)
        .order_by(Candle.symbol, Candle.timeframe)
    ).all()
    groups = []
    for symbol, timeframe, total_candles, first_timestamp, last_timestamp in rows:
        groups.append(
            DataGroupSummary(
                symbol=symbol,
                timeframe=timeframe,
                total_candles=total_candles,
                first_timestamp=first_timestamp,
                last_timestamp=last_timestamp,
            )
        )
    return DataSummaryOut(groups=groups)


@router.get("/preview", response_model=DataPreviewOut)
def data_preview(
    db: Session = Depends(get_db),
    symbol: str = Query(..., min_length=1),
    timeframe: str = Query(..., min_length=1),
    limit: int = Query(default=50, ge=1, le=500),
):
    symbol = symbol.strip().upper()
    timeframe = timeframe.strip()
    rows = db.scalars(
        select(Candle)
        .where(Candle.symbol == symbol, Candle.timeframe == timeframe)
        .order_by(Candle.timestamp.desc())
        .limit(limit)
    ).all()
    return DataPreviewOut(
        symbol=symbol,
        timeframe=timeframe,
        rows=[DataCandleOut.model_validate(row) for row in rows],
    )


@router.delete("/{symbol}/{timeframe}", response_model=DataDeleteOut)
def delete_data(symbol: str, timeframe: str, db: Session = Depends(get_db)):
    symbol = symbol.strip().upper()
    timeframe = timeframe.strip()
    result = db.execute(
        delete(Candle).where(Candle.symbol == symbol, Candle.timeframe == timeframe)
    )
    db.commit()
    return DataDeleteOut(symbol=symbol, timeframe=timeframe, deleted=result.rowcount)
