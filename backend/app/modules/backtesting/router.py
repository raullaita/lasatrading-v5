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
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.backtesting import tasks
from app.modules.backtesting.models import BacktestLog, BacktestRun, BacktestRunStatus
from app.modules.backtesting.schemas import (
    BacktestAvailableScansOut,
    BacktestCreateIn,
    BacktestEquitySeriesOut,
    BacktestLogOut,
    BacktestRunListItem,
    BacktestRunListOut,
    BacktestRunOut,
    BacktestSummaryOut,
    BacktestTradeListOut,
    BacktestTradeOut,
    BatchDeleteBody,
)
from app.modules.backtesting.service import (
    SORTABLE_TRADE_COLUMNS,
    BacktestService,
    RunFilters,
    RunNotFound,
    ScanNotReady,
)

router = APIRouter(prefix="/api/v1/backtests", tags=["backtesting"])

BACKTESTS_PAGE_SIZE = 50

TERMINAL_STATUSES = {
    BacktestRunStatus.COMPLETED.value,
    BacktestRunStatus.FAILED.value,
    BacktestRunStatus.CANCELLED.value,
}

#: Estados a los que se puede devolver un run con ``POST /requeue``. ``failed``
#: se incluye a proposito: si fallo porque el escaneo origen no estaba completo,
#: el usuario termina el escaneo y relanza *ese* run. Bloquearlo devolveria 400
#: justo en el escenario para el que existe el boton.
REQUEUEABLE_STATUSES = {
    BacktestRunStatus.PENDING.value,
    BacktestRunStatus.PROCESSING.value,
    BacktestRunStatus.FAILED.value,
}

SORTABLE_RUN_COLUMNS = {
    "created_at": BacktestRun.created_at,
    "equity_final": BacktestRun.equity_final,
    "net_pnl": BacktestRun.net_pnl,
    "total_return_pct": BacktestRun.total_return_pct,
    "total_trades": BacktestRun.total_trades,
    "max_drawdown_pct": BacktestRun.max_drawdown_pct,
}


def _run_or_404(db: Session, run_id: uuid.UUID) -> BacktestRun:
    run = db.get(BacktestRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run no encontrado")
    return run


# --------------------------------------------------------------------------
# 1-3: ciclo de vida
# --------------------------------------------------------------------------
@router.post("", response_model=BacktestRunOut, status_code=201)
def create_backtest(config: BacktestCreateIn, db: Session = Depends(get_db)):
    """Crea un backtest y lo encola.

    El rango de velas no se pide: se hereda del escaneo. Pedirlo aqui permitiria
    simular señales contra velas que el escaneo nunca vio, y el resultado no
    seria reproducible con el escaneo que dice haberlo producido.
    """
    service = BacktestService()
    try:
        run = service.create_run(db, config)
    except RunNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ScanNotReady as exc:
        # 409 y no 400: el escaneo existe y no esta mal formado, simplemente aun
        # no se puede simular. 400 diria que la peticion era incorrecta y
        # nudaria al usuario a construir otra.
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    tasks.run_backtest_task.delay(str(run.id))
    return run


@router.get("", response_model=BacktestRunListOut)
def list_backtests(
    db: Session = Depends(get_db),
    status: str | None = Query(default=None),
    scan_job_id: uuid.UUID | None = Query(default=None),
    sort_by: str = Query(default="created_at"),
    sort_order: Literal["asc", "desc"] = Query(default="desc"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=BACKTESTS_PAGE_SIZE, ge=1, le=100),
):
    filters = []
    if status:
        filters.append(BacktestRun.status == status)
    if scan_job_id:
        filters.append(BacktestRun.scan_job_id == scan_job_id)
    column = SORTABLE_RUN_COLUMNS.get(sort_by)
    if column is None:
        raise HTTPException(
            status_code=400, detail=f"Columna de ordenación inválida: {sort_by}"
        )
    order = (
        column.asc().nulls_last() if sort_order == "asc" else column.desc().nulls_last()
    )
    total = (
        db.scalar(select(func.count()).select_from(BacktestRun).where(*filters)) or 0
    )
    runs = db.scalars(
        select(BacktestRun)
        .where(*filters)
        .order_by(order)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return BacktestRunListOut(
        runs=[BacktestRunListItem.model_validate(run) for run in runs],
        total=total,
    )


@router.get("/available-scans", response_model=BacktestAvailableScansOut)
def list_available_scans(db: Session = Depends(get_db)):
    """Escaneos completados, para el selector de la pantalla de nuevo run."""
    return BacktestAvailableScansOut(scans=BacktestService().get_available_scans(db))


@router.get("/{run_id}", response_model=BacktestRunOut)
def get_backtest(run_id: uuid.UUID, db: Session = Depends(get_db)):
    return _run_or_404(db, run_id)


# --------------------------------------------------------------------------
# 4-7: resultados
# --------------------------------------------------------------------------
@router.get("/{run_id}/summary", response_model=BacktestSummaryOut)
def get_backtest_summary(run_id: uuid.UUID, db: Session = Depends(get_db)):
    """Tarjeta de resumen: metricas de cabecera mas los dos desgloses.

    Existe separada del detalle porque la UI la pide al cargar y al terminar,
    mientras que el detalle no cambia una vez el run esta cerrado.
    """
    return BacktestService().get_run_summary(db, run_id)


@router.get("/{run_id}/equity", response_model=BacktestEquitySeriesOut)
def get_backtest_equity(
    run_id: uuid.UUID,
    db: Session = Depends(get_db),
    max_points: int | None = Query(default=None, ge=10, le=20000),
):
    """Curva de equity y drawdown, una fila por vela.

    ``max_points`` submuestrea por paso constante cuando el rango es largo. El
    ``max_drawdown_pct`` de la respuesta es el real del run, no el de la serie
    reducida, para que no se contradiga con la tarjeta de resumen.
    """
    return BacktestService().get_run_equity(db, run_id, max_points)


@router.get("/{run_id}/trades", response_model=BacktestTradeListOut)
def get_backtest_trades(
    run_id: uuid.UUID,
    db: Session = Depends(get_db),
    pattern: list[str] | None = Query(default=None),
    direction: list[str] | None = Query(default=None),
    exit_reason: list[str] | None = Query(default=None),
    sort_by: str = Query(default="entry_timestamp"),
    sort_order: Literal["asc", "desc"] = Query(default="desc"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
):
    """Operaciones del run, filtrables por patron, direccion y motivo de salida.

    Los tres filtros aceptan valores repetidos: ``?pattern=A&pattern=B``. La
    respuesta incluye ``total_net_pnl`` de **todo** el subconjunto filtrado, no
    de la pagina, para que la suma cuadre con la tarjeta de resumen.
    """
    if sort_by not in SORTABLE_TRADE_COLUMNS:
        raise HTTPException(
            status_code=400, detail=f"Columna de ordenación inválida: {sort_by}"
        )
    _run_or_404(db, run_id)
    filters = RunFilters(
        patterns=tuple(pattern) if pattern else None,
        directions=tuple(direction) if direction else None,
        exit_reasons=tuple(exit_reason) if exit_reason else None,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    trades, total, total_net = BacktestService().get_run_trades(
        db, run_id, filters, page, page_size
    )
    return BacktestTradeListOut(
        trades=[BacktestTradeOut.model_validate(trade) for trade in trades],
        total=total,
        total_net_pnl=total_net,
    )


@router.get("/{run_id}/trades/by-pattern")
def get_trades_by_pattern(run_id: uuid.UUID, db: Session = Depends(get_db)):
    """Desglose por patron y direccion, ordenado por PnL acumulado."""
    _run_or_404(db, run_id)
    return BacktestService().get_trades_by_pattern(db, run_id)


# --------------------------------------------------------------------------
# 8-10: control
# --------------------------------------------------------------------------
@router.post("/{run_id}/cancel", response_model=BacktestRunOut)
def cancel_backtest(run_id: uuid.UUID, db: Session = Depends(get_db)):
    """Solicita la cancelacion de un run en curso.

    La simulacion dura medio segundo, asi que en la practica casi siempre llegara
    tarde: por eso un run ya terminal responde **409** y no 404, para que la UI
    distinga "no existe" de "se te ha pasado".
    """
    service = BacktestService()
    run = _run_or_404(db, run_id)
    if run.status not in REQUEUEABLE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"El run está en estado '{run.status}' y ya no se puede cancelar",
        )
    service.cancel_run(run_id)
    db.expire_all()
    return _run_or_404(db, run_id)


@router.post("/{run_id}/requeue", response_model=BacktestRunOut)
def requeue_backtest(run_id: uuid.UUID, db: Session = Depends(get_db)):
    run = _run_or_404(db, run_id)
    if run.status not in REQUEUEABLE_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"El run está en estado '{run.status}' y no se puede reenviar",
        )
    if not BacktestService().requeue_run(run_id):
        raise HTTPException(
            status_code=400, detail="El run no se pudo reenviar a la cola"
        )
    tasks.run_backtest_task.delay(str(run_id))
    db.expire_all()
    return _run_or_404(db, run_id)


@router.delete("/{run_id}")
def delete_backtest(run_id: uuid.UUID, db: Session = Depends(get_db)):
    """Borra un run. En cascada se van operaciones, curva y logs con el."""
    if not BacktestService().delete_run(run_id):
        raise HTTPException(status_code=404, detail="Run no encontrado")
    return {"deleted": True, "run_id": str(run_id)}


@router.delete("")
def delete_backtests_batch(body: BatchDeleteBody, db: Session = Depends(get_db)):
    deleted = BacktestService().delete_runs(db, body.run_ids)
    return {"deleted": deleted, "requested": len(body.run_ids)}


# --------------------------------------------------------------------------
# Logs por WebSocket
# --------------------------------------------------------------------------
@router.websocket("/{run_id}/logs")
async def ws_logs(
    websocket: WebSocket, run_id: uuid.UUID, db: Session = Depends(get_db)
):
    """Igual que el de patrones: sondea ``backtest_logs`` y cierra al terminar.

    No se emite progreso por vela porque la simulacion no lo tiene: va por
    etapas, como los logs. Mandar un 0-100 ficticio para rellenar una barra
    seria hacer que el usuario espere algo que no existe.
    """
    await websocket.accept()
    offset = 0
    closed = False
    try:
        while True:
            db.expire_all()
            run = db.get(BacktestRun, run_id)
            if run is None:
                await websocket.send_json({"error": "run not found"})
                break
            logs = db.scalars(
                select(BacktestLog)
                .where(BacktestLog.run_id == run_id)
                .order_by(BacktestLog.timestamp, BacktestLog.id)
                .offset(offset)
                .limit(200)
            ).all()
            for log in logs:
                await websocket.send_text(
                    BacktestLogOut.model_validate(log).model_dump_json()
                )
            offset += len(logs)
            if run.status in TERMINAL_STATUSES:
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
