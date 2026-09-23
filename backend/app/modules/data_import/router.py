import asyncio
import contextlib
import uuid
from datetime import datetime, timezone

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.data_import import tasks
from app.modules.data_import.binance_client import BinanceClient, BinanceClientError
from app.modules.data_import.models import (
    Candle,
    ImportJob,
    ImportLog,
    ImportStatus,
    LogLevel,
)
from app.modules.data_import.schemas import (
    BinanceSymbolOut,
    ImportConfig,
    JobListOut,
    JobStatusOut,
    LogOut,
    PreviewOut,
    PreviewRow,
    StartImportOut,
    StatsOut,
)
from app.modules.data_import.service import TIMEFRAME_MS, ImportService

router = APIRouter(prefix="/api/v1/data-import", tags=["data-import"])

TERMINAL_STATUSES = {
    ImportStatus.COMPLETED.value,
    ImportStatus.FAILED.value,
    ImportStatus.CANCELLED.value,
}


def _job_or_404(db: Session, job_id: uuid.UUID) -> ImportJob:
    job = db.get(ImportJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job no encontrado")
    return job


@router.post("/start", response_model=StartImportOut, status_code=201)
def start_import(config: ImportConfig, db: Session = Depends(get_db)):
    job = ImportService().create_job(db, config)
    tasks.run_import_job.delay(str(job.id))
    return StartImportOut(job_id=job.id)


@router.get("/list", response_model=JobListOut)
def list_jobs(
    db: Session = Depends(get_db),
    status: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
    timeframe: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    filters = []
    if status:
        filters.append(ImportJob.status == status)
    if symbol:
        filters.append(ImportJob.symbols.contains([symbol]))
    if timeframe:
        filters.append(ImportJob.timeframes.contains([timeframe]))
    total = db.scalar(select(func.count()).select_from(ImportJob).where(*filters)) or 0
    jobs = db.scalars(
        select(ImportJob)
        .where(*filters)
        .order_by(ImportJob.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return JobListOut(jobs=list(jobs), total=total)


@router.get("/status/{job_id}", response_model=JobStatusOut)
def job_status(job_id: uuid.UUID, db: Session = Depends(get_db)):
    job = _job_or_404(db, job_id)
    return job


@router.get("/symbols", response_model=list[BinanceSymbolOut])
async def list_symbols():
    client = BinanceClient()
    try:
        symbols = await client.get_symbols()
    except BinanceClientError as exc:
        raise HTTPException(
            status_code=502, detail=f"Error consultando Binance: {exc}"
        ) from exc
    finally:
        await client.close()
    return symbols


@router.get("/preview/{job_id}", response_model=PreviewOut)
def preview_job(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    symbol: str | None = None,
    timeframe: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
):
    job = _job_or_404(db, job_id)
    filters = [Candle.import_job_id == job_id]
    if symbol:
        filters.append(Candle.symbol == symbol)
    if timeframe:
        filters.append(Candle.timeframe == timeframe)
    rows = db.scalars(
        select(Candle)
        .where(*filters)
        .order_by(Candle.symbol, Candle.timeframe, Candle.timestamp)
        .limit(limit)
    ).all()
    if not rows:
        filters = [
            Candle.timestamp >= job.date_from,
            Candle.timestamp <= job.date_to,
        ]
        if symbol:
            filters.append(Candle.symbol == symbol)
        else:
            filters.append(Candle.symbol.in_(job.symbols))
        if timeframe:
            filters.append(Candle.timeframe == timeframe)
        else:
            filters.append(Candle.timeframe.in_(job.timeframes))
        rows = db.scalars(
            select(Candle)
            .where(*filters)
            .order_by(Candle.symbol, Candle.timeframe, Candle.timestamp)
            .limit(limit)
        ).all()
    return PreviewOut(
        job_id=job_id,
        symbol=symbol,
        timeframe=timeframe,
        rows=[PreviewRow.model_validate(r) for r in rows],
    )


@router.get("/stats/{job_id}", response_model=StatsOut)
def job_stats(job_id: uuid.UUID, db: Session = Depends(get_db)):
    job = _job_or_404(db, job_id)
    quality = (job.error_summary or {}).get("quality", {})
    rows = db.scalars(
        select(Candle)
        .where(Candle.import_job_id == job_id)
        .order_by(Candle.symbol, Candle.timeframe, Candle.timestamp)
    ).all()

    gaps: list[dict] = []
    last: dict | None = None
    last_tf: str | None = None
    for row in rows:
        if last is not None and row.symbol == last.symbol and row.timeframe == last_tf:
            timeframe_ms = TIMEFRAME_MS.get(row.timeframe)
            if timeframe_ms:
                diff = (row.timestamp - last.timestamp).total_seconds() * 1000
                if diff > 1.5 * timeframe_ms:
                    gaps.append(
                        {
                            "symbol": row.symbol,
                            "timeframe": row.timeframe,
                            "from": last.timestamp,
                            "to": row.timestamp,
                            "missing": round(
                                (row.timestamp - last.timestamp).total_seconds()
                                / (timeframe_ms / 1000)
                            )
                            - 1,
                        }
                    )
        last = row
        last_tf = row.timeframe
    return StatsOut(
        job_id=job_id,
        total_candles_downloaded=job.total_candles_downloaded,
        total_candles_inserted=job.total_candles_inserted,
        total_candles_updated=job.total_candles_updated,
        total_candles_skipped=job.total_candles_skipped,
        combinations_completed=job.completed_combinations,
        combinations_failed=job.failed_combinations,
        quality={
            "discarded_candles": quality.get("discarded_candles", 0),
            "error_kinds": quality.get("errors", {}),
        },
        gaps=gaps[:50],
    )


@router.post("/cancel/{job_id}", response_model=JobStatusOut)
def cancel_job(job_id: uuid.UUID, db: Session = Depends(get_db)):
    job = _job_or_404(db, job_id)
    if job.status in TERMINAL_STATUSES:
        raise HTTPException(status_code=400, detail="El job ya está en estado terminal")
    job.status = ImportStatus.CANCELLED.value
    job.finished_at = datetime.now(timezone.utc)
    db.add(
        ImportLog(
            job_id=job.id, level=LogLevel.INFO.value, message="Cancelación solicitada"
        )
    )
    db.commit()
    db.refresh(job)
    return job


@router.post("/retry/{job_id}", response_model=StartImportOut, status_code=201)
def retry_job(job_id: uuid.UUID, db: Session = Depends(get_db)):
    _job_or_404(db, job_id)
    new_job_id = ImportService().retry_failed(job_id)
    if new_job_id is None:
        raise HTTPException(
            status_code=400,
            detail="No hay combinaciones fallidas o canceladas para reintentar",
        )
    tasks.run_import_job.delay(str(new_job_id))
    return StartImportOut(job_id=new_job_id)


@router.websocket("/logs/{job_id}")
async def ws_logs(
    websocket: WebSocket, job_id: uuid.UUID, db: Session = Depends(get_db)
):
    await websocket.accept()
    offset = 0
    closed = False
    try:
        while True:
            db.expire_all()
            job = db.get(ImportJob, job_id)
            if job is None:
                await websocket.send_json({"error": "job not found"})
                break
            logs = db.scalars(
                select(ImportLog)
                .where(ImportLog.job_id == job_id)
                .order_by(ImportLog.timestamp, ImportLog.id)
                .offset(offset)
                .limit(200)
            ).all()
            for log in logs:
                await websocket.send_text(LogOut.model_validate(log).model_dump_json())
            offset += len(logs)
            if job.status in TERMINAL_STATUSES:
                await websocket.close()
                closed = True
                break
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        closed = True
    finally:
        if not closed:
            with contextlib.suppress(RuntimeError):
                await websocket.close()
