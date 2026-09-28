"""Endpoints del walk-forward.

``GET`` para leer, ``POST`` para lanzar. La misma separacion que en el
backtesting, y por el mismo motivo: reejecutar un walk-forward **es trabajo**,
aunque no escriba simulaciones, y un ``GET`` que tarda dos minutos se cachea, se
precarga y se puede disparar dos veces con una pestana.

Los codigos de error estan elegidos para que cada uno signifique una cosa:

- **404** el run no existe.
- **409** existe pero no se puede atender todavia: el escaneo no ha terminado, o
  el run sigue en curso. Es distinto de 404 a proposito, porque "no encontrado"
  lleva al usuario a buscar un informe que si esta ahi.
- **422** la peticion no se puede atender tal cual, y se dice **cuantas**
  simulaciones serian. Un trabajo que muere a los cinco minutos con "son 4.300
  simulaciones y el tope es 2.000" le hace perder cinco minutos para aprender
  algo que se sabia antes de empezar.
"""

import asyncio
import contextlib
import uuid

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.backtesting import tasks
from app.modules.backtesting.models import WalkForwardLog, WalkForwardRun
from app.modules.backtesting.schemas import (
    WalkForwardCreateIn,
    WalkForwardEquitySeriesOut,
    WalkForwardLogOut,
    WalkForwardReportOut,
    WalkForwardRunListOut,
    WalkForwardRunOut,
)
from app.modules.backtesting.walk_forward_service import (
    TERMINAL_STATUSES,
    TooManySimulations,
    WalkForwardRunNotFinished,
    WalkForwardRunNotFound,
    WalkForwardScanNotReady,
    WalkForwardService,
)

router = APIRouter(prefix="/api/v1/walk-forward", tags=["walk-forward"])

WALK_FORWARD_PAGE_SIZE = 50


# --------------------------------------------------------------------------
# 1-2: crear y listar
# --------------------------------------------------------------------------
@router.post("/runs", response_model=WalkForwardRunOut, status_code=202)
def create_walk_forward(config: WalkForwardCreateIn, db: Session = Depends(get_db)):
    """Crea el walk-forward y lo encola. **202**, no 201.

    202 y no 201 porque el recurso no esta listo: la respuesta lleva el ``id`` del
    informe, y ese informe no existara hasta dentro de uno o dos minutos. Un 201
    prometeria algo que todavia no se puede leer.

    El tope de simulaciones se comprueba aqui, antes de encolar, y el mensaje
    lleva el numero que seria. Es lo que permite que el formulario muestre el
    coste y que un 422 lo impida, en vez de descubrirlo cinco minutos despues.
    """
    service = WalkForwardService()
    try:
        run = service.create_run(db, config)
    except WalkForwardRunNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WalkForwardScanNotReady as exc:
        # 409 y no 400, igual que en el backtesting: el escaneo existe y no esta
        # mal formado, simplemente aun no se puede simular.
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except TooManySimulations as exc:
        # 422 con el numero dentro. Es la unica validacion que no puede vivir en
        # el schema, porque el total depende del rango real de las velas.
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    tasks.run_walk_forward_task.delay(str(run.id))
    return run


@router.get("/runs", response_model=WalkForwardRunListOut)
def list_walk_forwards(
    db: Session = Depends(get_db),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=WALK_FORWARD_PAGE_SIZE, ge=1, le=100),
):
    service = WalkForwardService()
    return service.list_runs(db, limit=page_size, offset=(page - 1) * page_size)


# --------------------------------------------------------------------------
# 3-4: el informe y su curva
# --------------------------------------------------------------------------
@router.get("/runs/{run_id}", response_model=WalkForwardReportOut)
def get_walk_forward(run_id: uuid.UUID, db: Session = Depends(get_db)):
    """Informe completo: cabecera, ventanas y candidatos.

    Devuelve 409 mientras el run no haya terminado, no un informe vacio. Un
    informe a medias no es un informe con menos filas: es un informe cuyo
    veredicto no se puede leer, porque las candidatas que faltan son justo las
    que no han pasado las guardas, y esa es precisamente la duda que el usuario
    tiene al abrir la pantalla.
    """
    try:
        return WalkForwardService().get_report(db, run_id)
    except WalkForwardRunNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WalkForwardRunNotFinished as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/runs/{run_id}/equity", response_model=WalkForwardEquitySeriesOut)
def get_walk_forward_equity(
    run_id: uuid.UUID,
    db: Session = Depends(get_db),
    max_points: int | None = Query(default=None, ge=2, le=20000),
):
    """Curva OOS encadenada y benchmark encadenado, una fila por vela.

    Sin esto, el informe dice que el OOS gano un 12% y no hay forma de ver
    **cuando** ni cuanto peso cada ventana. Y el ``max_points`` va en la propia
    peticion y no como un tope fijo del servidor, porque quien dibuja sabe
    cuantos pixeles tiene.
    """
    try:
        return WalkForwardService().get_equity(db, run_id, max_points)
    except WalkForwardRunNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# --------------------------------------------------------------------------
# 5: control
# --------------------------------------------------------------------------
@router.post("/runs/{run_id}/cancel", response_model=WalkForwardRunOut)
def cancel_walk_forward(run_id: uuid.UUID, db: Session = Depends(get_db)):
    """Pide cancelar. El motor para en la frontera de la ventana siguiente.

    409 si el run ya termino: no se puede cancelar un informe que ya existe, y
    devolver un exito que no cambio nada dejaria al usuario pensando que para,
    cuando lo que paso es que ya habia acabado.
    """
    if db.get(WalkForwardRun, run_id) is None:
        raise HTTPException(status_code=404, detail="Walk-forward no encontrado")
    if not WalkForwardService().cancel_run(run_id):
        raise HTTPException(
            status_code=409,
            detail="El walk-forward ya está terminado y no se puede cancelar",
        )
    db.expire_all()
    return WalkForwardRunOut.model_validate(db.get(WalkForwardRun, run_id))


# --------------------------------------------------------------------------
# 6: progreso en vivo
# --------------------------------------------------------------------------
@router.websocket("/runs/{run_id}/logs")
async def ws_walk_forward_logs(
    websocket: WebSocket, run_id: uuid.UUID, db: Session = Depends(get_db)
):
    """Sondea ``walk_forward_logs`` y cierra al terminar, igual que el backtest.

    No se emite progreso por simulacion porque el motor no lo tiene: va por
    ventana, y una simulacion dura 60 ms y no produce ningun dato que contar. Mandar
    un 0-100 ficticio para rellenar una barra seria hacer que el usuario espere
    algo que no existe.
    """
    await websocket.accept()
    offset = 0
    closed = False
    try:
        while True:
            db.expire_all()
            run = db.get(WalkForwardRun, run_id)
            if run is None:
                await websocket.send_json({"error": "run not found"})
                break
            logs = db.scalars(
                select(WalkForwardLog)
                .where(WalkForwardLog.run_id == run_id)
                .order_by(WalkForwardLog.timestamp, WalkForwardLog.id)
                .offset(offset)
                .limit(200)
            ).all()
            for log in logs:
                await websocket.send_text(
                    WalkForwardLogOut.model_validate(log).model_dump_json()
                )
            offset += len(logs)
            terminal = run.status in TERMINAL_STATUSES
            if terminal:
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
