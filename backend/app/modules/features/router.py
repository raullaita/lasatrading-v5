import asyncio
import contextlib
import uuid
from typing import Literal

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
)
from sqlalchemy import Text, cast, delete, func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.features import tasks
from app.modules.features.models import FeatureJob, FeatureJobStatus, FeatureLog
from app.modules.features.schemas import (
    BatchDeleteBody,
    FeatureJobConfig,
    FeatureJobListItem,
    FeatureJobListOut,
    FeatureJobResponse,
    FeatureLogOut,
    FeaturePreviewOut,
    IndicatorAvailabilityListOut,
    IndicatorAvailabilityOut,
)
from app.modules.features.service import FeatureService

router = APIRouter(prefix="/api/v1/features", tags=["features"])

TERMINAL_STATUSES = {
    FeatureJobStatus.COMPLETED.value,
    FeatureJobStatus.FAILED.value,
    FeatureJobStatus.CANCELLED.value,
}

SORTABLE_COLUMNS = {
    "created_at": FeatureJob.created_at,
    "status": FeatureJob.status,
    "symbol": FeatureJob.symbol,
    "timeframe": FeatureJob.timeframe,
    "processed_candles": FeatureJob.processed_candles,
    "date_from": FeatureJob.date_from,
    "date_to": FeatureJob.date_to,
    "finished_at": FeatureJob.finished_at,
}

FEATURES_PAGE_SIZE = 20


def _job_or_404(db: Session, job_id: uuid.UUID) -> FeatureJob:
    job = db.get(FeatureJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job no encontrado")
    return job


@router.post("/jobs", response_model=FeatureJobResponse, status_code=201)
def create_job(config: FeatureJobConfig, db: Session = Depends(get_db)):
    service = FeatureService()
    job = service.create_job(db, config)
    tasks.run_feature_job.delay(str(job.id))
    return job


@router.get("/jobs", response_model=FeatureJobListOut)
def list_jobs(
    db: Session = Depends(get_db),
    status: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
    timeframe: str | None = Query(default=None),
    sort_by: str = Query(default="created_at"),
    sort_order: Literal["asc", "desc"] = Query(default="desc"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=FEATURES_PAGE_SIZE, ge=1, le=100),
):
    filters = []
    if status:
        filters.append(FeatureJob.status == status)
    if symbol:
        target = symbol.strip().upper()
        filters.append(func.upper(cast(FeatureJob.symbol, Text)).contains(target))
    if timeframe:
        filters.append(FeatureJob.timeframe == timeframe)
    column = SORTABLE_COLUMNS.get(sort_by)
    if column is None:
        raise HTTPException(
            status_code=400, detail=f"Columna de ordenación inválida: {sort_by}"
        )
    order = (
        column.asc().nulls_last() if sort_order == "asc" else column.desc().nulls_last()
    )
    total = db.scalar(select(func.count()).select_from(FeatureJob).where(*filters)) or 0
    offset = (page - 1) * page_size
    jobs = db.scalars(
        select(FeatureJob)
        .where(*filters)
        .order_by(order)
        .offset(offset)
        .limit(page_size)
    ).all()
    return FeatureJobListOut(
        jobs=[FeatureJobListItem.model_validate(j) for j in jobs],
        total=total,
    )


@router.delete("/jobs/batch")
def delete_jobs_batch(body: BatchDeleteBody, db: Session = Depends(get_db)):
    if not body.job_ids:
        raise HTTPException(status_code=400, detail="job_ids vacío")
    result = db.execute(delete(FeatureJob).where(FeatureJob.id.in_(body.job_ids)))
    db.commit()
    return {"deleted_count": result.rowcount or 0}


@router.get("/data/available")
def available_data(db: Session = Depends(get_db)):
    data = FeatureService().get_available_data()
    return data


@router.get("/data/indicators", response_model=IndicatorAvailabilityListOut)
def available_indicators(
    symbol: str = Query(..., min_length=1),
    timeframe: str = Query(..., min_length=1),
):
    """Indicadores ya calculados para un par, con su rango real.

    Es lo que alimenta el selector del explorador de datos. La lista sale de lo
    que hay en la base y de nada mas: el explorador **no calcula indicadores**,
    muestra los que existen y avisa de los que faltan. Un indicador en pantalla
    sin un job que lo haya producido rompe la trazabilidad desde el primer
    eslabon.
    """
    return IndicatorAvailabilityListOut(
        symbol=symbol.strip().upper(),
        timeframe=timeframe.strip(),
        indicators=[
            IndicatorAvailabilityOut(**row)
            for row in FeatureService().get_indicator_coverage(
                symbol.strip().upper(), timeframe.strip()
            )
        ],
    )


@router.get("/jobs/{job_id}/preview", response_model=FeaturePreviewOut)
def preview_job(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    limit: int = Query(default=100, ge=1, le=1000),
):
    job = _job_or_404(db, job_id)
    rows = FeatureService().get_preview(job_id, limit=limit)
    return FeaturePreviewOut(
        job_id=job_id, symbol=job.symbol, timeframe=job.timeframe, rows=rows
    )


@router.post("/jobs/{job_id}/cancel", response_model=FeatureJobResponse)
def cancel_job(job_id: uuid.UUID, db: Session = Depends(get_db)):
    job = _job_or_404(db, job_id)
    if job.status in TERMINAL_STATUSES:
        raise HTTPException(status_code=400, detail="El job ya está en estado terminal")
    service = FeatureService()
    if not service.cancel_job(job_id):
        raise HTTPException(status_code=400, detail="No se pudo cancelar el job")
    db.refresh(job)
    return job


@router.post("/jobs/{job_id}/requeue", response_model=FeatureJobResponse)
def requeue_job(job_id: uuid.UUID, db: Session = Depends(get_db)):
    job = _job_or_404(db, job_id)
    if job.status in TERMINAL_STATUSES:
        raise HTTPException(
            status_code=400,
            detail="El job está en estado terminal; usa otro método para reintentar",
        )
    service = FeatureService()
    if not service.requeue_job(job_id):
        raise HTTPException(status_code=400, detail="No se pudo reenviar el job")
    tasks.run_feature_job.delay(str(job_id))
    db.refresh(job)
    return job


@router.delete("/jobs/{job_id}/logs")
def delete_job_logs(job_id: uuid.UUID, db: Session = Depends(get_db)):
    _job_or_404(db, job_id)
    deleted = db.execute(delete(FeatureLog).where(FeatureLog.job_id == job_id))
    db.commit()
    return {"deleted": deleted.rowcount or 0}


@router.delete("/jobs/{job_id}")
def delete_job(job_id: uuid.UUID, db: Session = Depends(get_db)):
    service = FeatureService()
    if not service.delete_job(job_id):
        raise HTTPException(status_code=404, detail="Job no encontrado")
    return {"deleted": True, "job_id": str(job_id)}


@router.get("/jobs/{job_id}", response_model=FeatureJobResponse)
def get_job(job_id: uuid.UUID, db: Session = Depends(get_db)):
    return _job_or_404(db, job_id)


@router.websocket("/jobs/{job_id}/logs")
async def ws_logs(
    websocket: WebSocket, job_id: uuid.UUID, db: Session = Depends(get_db)
):
    await websocket.accept()
    offset = 0
    closed = False
    try:
        while True:
            db.expire_all()
            job = db.get(FeatureJob, job_id)
            if job is None:
                await websocket.send_json({"error": "job not found"})
                break
            logs = db.scalars(
                select(FeatureLog)
                .where(FeatureLog.job_id == job_id)
                .order_by(FeatureLog.timestamp, FeatureLog.id)
                .offset(offset)
                .limit(200)
            ).all()
            for log in logs:
                await websocket.send_text(
                    FeatureLogOut.model_validate(log).model_dump_json()
                )
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
