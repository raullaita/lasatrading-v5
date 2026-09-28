import asyncio
import contextlib
import uuid
from datetime import datetime
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
from app.modules.patterns import pattern_catalog as catalog
from app.modules.patterns import tasks
from app.modules.patterns.models import (
    PatternScanJob,
    PatternScanJobStatus,
    PatternScanLog,
)
from app.modules.patterns.schemas import (
    BatchDeleteBody,
    ChartDataOut,
    PatternAvailableDataListOut,
    PatternCatalogOut,
    PatternDefinitionOut,
    PatternOccurrenceListOut,
    PatternOccurrenceOut,
    PatternOccurrencesSummaryOut,
    PatternScanConfig,
    PatternScanJobListItem,
    PatternScanJobListOut,
    PatternScanJobResponse,
    PatternScanLogOut,
)
from app.modules.patterns.service import (
    CHART_MAX_POINTS_LIMIT,
    DEFAULT_CHART_MAX_POINTS,
    PatternScanService,
)

router = APIRouter(prefix="/api/v1/patterns", tags=["patterns"])

TERMINAL_STATUSES = {
    PatternScanJobStatus.COMPLETED.value,
    PatternScanJobStatus.FAILED.value,
    PatternScanJobStatus.CANCELLED.value,
}

# Estados a los que se puede devolver un job con POST /requeue. `failed` se
# incluye a proposito: si el job fallo por MissingFeaturesError, el usuario
# calcula las features que faltaban y debe poder relanzar *ese* job, no crear
# otro desde cero. Bloquearlo aqui devuelva 400 precisamente en el escenario
# para el que existe el boton.
REQUEUEABLE_STATUSES = {
    PatternScanJobStatus.PENDING.value,
    PatternScanJobStatus.PROCESSING.value,
    PatternScanJobStatus.FAILED.value,
}

# Lista blanca de columnas: sort_by va directo desde el cliente a un ORDER BY,
# y sin esto cualquier texto se cola en la consulta.
SORTABLE_COLUMNS = {
    "created_at": PatternScanJob.created_at,
    "status": PatternScanJob.status,
    "symbol": PatternScanJob.symbol,
    "timeframe": PatternScanJob.timeframe,
    "processed_candles": PatternScanJob.processed_candles,
    "date_from": PatternScanJob.date_from,
    "date_to": PatternScanJob.date_to,
    "finished_at": PatternScanJob.finished_at,
}

PATTERNS_PAGE_SIZE = 20
OCCURRENCES_PAGE_SIZE = 50
MAX_OCCURRENCES_PAGE_SIZE = 500


def _job_or_404(db: Session, job_id: uuid.UUID) -> PatternScanJob:
    job = db.get(PatternScanJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job no encontrado")
    return job


def _split_csv(value: str | None) -> list[str] | None:
    """``"MACD_CROSS_BULLISH,RSI_EXIT_OVERSOLD"`` -> lista de dos elementos.

    Los codigos desconocidos se descartan en vez de propagarse a la consulta,
    para que un patron retirado del catalogo no provoque un error de base de
    datos ni exponga codigos inexistentes. Se toleran porque el filtro del
    frontend es un multiselect que puede quedarse con un valor viejo.

    Pero si *no* queda ningun codigo valido, se rechaza con 400 en lugar de
    devolver la tabla sin filtrar: pedir "solo patrones que no existen" y
    recibir 14.441 ocurrencias de todos los patrones es una respuesta que
    miente, y es justo el fallo que cuesta más tiempo de diagnosticar.
    """
    if not value:
        return None
    requested = [item.strip() for item in value.split(",") if item.strip()]
    if not requested:
        return None
    valid = [code for code in requested if catalog.get_definition(code) is not None]
    if not valid:
        raise HTTPException(
            status_code=400,
            detail=(
                "Ninguno de los patrones indicados existe en el catálogo: "
                f"{', '.join(requested)}"
            ),
        )
    return valid


def _parse_features(value: str | None) -> list[str] | None:
    """Parametro ``features``: nombres de indicadores separados por comas.

    Aqui **no** se valida contra el catalogo de patrones, porque no son
    patrones: son nombres de indicadores, y ese vocabulario vive en la tabla
    ``features``, no en el codigo. Un nombre desconocido se ignora en
    ``_load_features_pivot`` y simplemente no aporta serie, que es el
    comportamiento correcto para un filtro de overlay.
    """
    if not value:
        return None
    requested = [item.strip() for item in value.split(",") if item.strip()]
    if not requested:
        return None
    # dict.fromkeys quita duplicados conservando el orden.
    return list(dict.fromkeys(requested))


# ---------------------------------------------------------------------------
# Coleccion. Ojo con el orden: /scans/batch tiene que declararse antes que
# /scans/{job_id} o FastAPI lo captura como si job_id fuera "batch".
# ---------------------------------------------------------------------------


@router.post("/scans", response_model=PatternScanJobResponse, status_code=201)
def create_scan(config: PatternScanConfig, db: Session = Depends(get_db)):
    """Crea un escaneo y lo encola. Los patrones y sus parametros ya viene
    validados por ``PatternScanConfig``: codigo desconocido, duplicado o lista
    vacia se rechazan con 422 antes de tocar la base de datos."""
    service = PatternScanService()
    try:
        job = service.create_job(db, config)
    except ValueError as exc:
        # create_job lanza ValueError si no hay velas en el rango pedido. Es un
        # error de negocio con respuesta clara, no un 500.
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    tasks.run_pattern_scan.delay(str(job.id))
    return job


@router.get("/scans", response_model=PatternScanJobListOut)
def list_scans(
    db: Session = Depends(get_db),
    status: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
    timeframe: str | None = Query(default=None),
    sort_by: str = Query(default="created_at"),
    sort_order: Literal["asc", "desc"] = Query(default="desc"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=PATTERNS_PAGE_SIZE, ge=1, le=100),
):
    filters = []
    if status:
        filters.append(PatternScanJob.status == status)
    if symbol:
        target = symbol.strip().upper()
        filters.append(func.upper(cast(PatternScanJob.symbol, Text)).contains(target))
    if timeframe:
        filters.append(PatternScanJob.timeframe == timeframe)
    column = SORTABLE_COLUMNS.get(sort_by)
    if column is None:
        raise HTTPException(
            status_code=400, detail=f"Columna de ordenación inválida: {sort_by}"
        )
    order = (
        column.asc().nulls_last() if sort_order == "asc" else column.desc().nulls_last()
    )
    total = (
        db.scalar(select(func.count()).select_from(PatternScanJob).where(*filters)) or 0
    )
    jobs = db.scalars(
        select(PatternScanJob)
        .where(*filters)
        .order_by(order)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return PatternScanJobListOut(
        jobs=[PatternScanJobListItem.model_validate(job) for job in jobs],
        total=total,
    )


@router.delete("/scans/batch")
def delete_scans_batch(body: BatchDeleteBody, db: Session = Depends(get_db)):
    if not body.job_ids:
        raise HTTPException(status_code=400, detail="job_ids vacío")
    # El borrado de las ocurrencias y los logs lo hace ON DELETE CASCADE de la
    # base de datos, tambien sobre los chunks de la hypertable.
    result = db.execute(
        delete(PatternScanJob).where(PatternScanJob.id.in_(body.job_ids))
    )
    db.commit()
    return {"deleted_count": result.rowcount or 0}


@router.get("/catalog", response_model=PatternCatalogOut)
def get_catalog():
    """Catalogo de los diez patrones, con sus parametros y features exigidas,
    para que el frontend genere el selector sin duplicar la definicion."""
    return PatternCatalogOut(
        patterns=[
            PatternDefinitionOut.from_definition(definition)
            for definition in catalog.list_catalog()
        ]
    )


@router.get("/data/available", response_model=PatternAvailableDataListOut)
def available_data():
    """Pares (simbolo, timeframe) escaneables y features ya precalculadas.

    Un par con velas pero sin las features del patron elegido no es escaneable:
    encolar el job asi devuelve 400 por ``MissingFeaturesError``. Lo tipico es
    ``MA_CROSS_*``, que por defecto exige ``EMA_20`` y ``EMA_50``: si el par solo
    tiene ``EMA_20``, hay que crear la EMA de longitud 50 en ``/features/new``,
    esperar al Feature Job y recargar este endpoint.
    """
    return PatternAvailableDataListOut(data=PatternScanService().get_available_data())


# ---------------------------------------------------------------------------
# Ocurrencias. /occurrences/summary antes que cualquier ruta parametrizada.
# ---------------------------------------------------------------------------


@router.get("/occurrences/summary", response_model=PatternOccurrencesSummaryOut)
def occurrences_summary(
    symbol: str | None = Query(default=None),
    timeframe: str | None = Query(default=None),
    patterns: str | None = Query(
        default=None, description="Lista separada por comas de codigos de patron"
    ),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
):
    return PatternScanService().get_occurrences_summary(
        symbol=symbol,
        timeframe=timeframe,
        pattern_names=_split_csv(patterns),
        date_from=date_from,
        date_to=date_to,
    )


@router.get("/occurrences", response_model=PatternOccurrenceListOut)
def list_occurrences(
    job_id: uuid.UUID | None = Query(default=None),
    symbol: str | None = Query(default=None),
    timeframe: str | None = Query(default=None),
    patterns: str | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(
        default=OCCURRENCES_PAGE_SIZE, ge=1, le=MAX_OCCURRENCES_PAGE_SIZE
    ),
):
    """Tabla maestra de ocurrencias de todos los jobs."""
    rows, total = PatternScanService().get_occurrences(
        job_id=job_id,
        symbol=symbol,
        timeframe=timeframe,
        pattern_names=_split_csv(patterns),
        date_from=date_from,
        date_to=date_to,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    return PatternOccurrenceListOut(
        occurrences=[PatternOccurrenceOut.model_validate(row) for row in rows],
        total=total,
    )


# ---------------------------------------------------------------------------
# Un job concreto.
# ---------------------------------------------------------------------------


@router.get("/scans/{job_id}/occurrences", response_model=PatternOccurrenceListOut)
def job_occurrences(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(
        default=OCCURRENCES_PAGE_SIZE, ge=1, le=MAX_OCCURRENCES_PAGE_SIZE
    ),
):
    _job_or_404(db, job_id)
    rows, total = PatternScanService().get_occurrences(
        job_id=job_id,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    return PatternOccurrenceListOut(
        occurrences=[PatternOccurrenceOut.model_validate(row) for row in rows],
        total=total,
    )


def _chart_response(
    symbol: str,
    timeframe: str,
    date_from: datetime,
    date_to: datetime,
    features: str | None,
    patterns: str | None,
    scan: uuid.UUID | None,
    max_points: int | None,
) -> ChartDataOut:
    """Ensamblado comun de las dos rutas de grafico.

    Las dos hacen exactamente la misma consulta con distinto punto de partida,
    asi que la.shared_ queda aqui en vez de duplicada: cuando el formato cambie
    (y cambiara, al anadir el muestreo) solo hay un sitio que tocar.
    """
    return PatternScanService().get_chart_data(
        symbol=symbol,
        timeframe=timeframe,
        date_from=date_from,
        date_to=date_to,
        feature_names=_parse_features(features),
        pattern_names=_split_csv(patterns),
        scan_job_id=scan,
        max_points=max_points,
    )


@router.get("/chart", response_model=ChartDataOut)
def chart_data(
    db: Session = Depends(get_db),
    symbol: str = Query(..., min_length=1, description="Símbolo a graficar"),
    timeframe: str = Query(..., min_length=1),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    features: str | None = Query(
        default=None, description="Features a superponer, separadas por comas"
    ),
    patterns: str | None = Query(
        default=None, description="Patrones a marcar, separados por comas"
    ),
    scan: uuid.UUID | None = Query(
        default=None, description="Escaneo cuyas detecciones se marcan"
    ),
    max_points: int | None = Query(
        default=DEFAULT_CHART_MAX_POINTS,
        ge=100,
        le=CHART_MAX_POINTS_LIMIT,
    ),
):
    """Velas + indicadores + detecciones, **sin necesidad de un escaneo**.

    Es lo que consume el explorador de datos: se elige símbolo, timeframe y
    rango y sale el grafico, aunque no se haya creado nunca un job de features
    ni un escaneo. Los indicadores que se superponen son los que ya estan
    calculados en la base; este endpoint no calcula ninguno.

    Sin ``scan`` la lista de markers viene vacia a proposito: no se puede marcar
    lo que no se ha escaneado, y marcarlo ademas de otro escaneo del mismo
    rango haria que el grafico de un escaneo pareciera contener detecciones
    ajenas.

    ``max_points`` limita el numero de velas de la respuesta por paso constante,
    conservando la ultima. Los indicadores se piden solo en las timestamps de
    las velas que se envian, para que el overlay no quede desalineado. La
    respuesta dice cuantas velas hay en el rango y cuantas se envian.
    """
    if date_from is None or date_to is None:
        raise HTTPException(
            status_code=422,
            detail="Se necesita date_from y date_to: sin un rango explícito el "
            "explorador no puede saber qué ventana está mirando el usuario",
        )
    if date_from >= date_to:
        raise HTTPException(
            status_code=422, detail="date_from debe ser anterior a date_to"
        )
    return _chart_response(
        symbol.strip().upper(),
        timeframe.strip(),
        date_from,
        date_to,
        features,
        patterns,
        scan,
        max_points,
    )


@router.get("/scans/{job_id}/chart", response_model=ChartDataOut)
def job_chart(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    symbol: str | None = Query(default=None),
    timeframe: str | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    features: str | None = Query(
        default=None, description="Features a superponer, separadas por comas"
    ),
    patterns: str | None = Query(
        default=None, description="Patrones a marcar, separados por comas"
    ),
    max_points: int | None = Query(
        default=DEFAULT_CHART_MAX_POINTS, ge=100, le=CHART_MAX_POINTS_LIMIT
    ),
):
    """Grafico de un escaneo concreto, con los parametros del job por defecto.

    Simbolo, timeframe y rango caen en los del propio job, que es lo que se
    quiere al abrir un escaneo. Se pueden sobrescribir para ampliar el rango o
    superponer otros indicadores.

    **Cambio de comportamiento:** los markers ahora salen **solo de este
    escaneo**. Antes se pedian por simbolo, timeframe y rango sin filtrar por
    ``scan_job_id``, de modo que el grafico de un escaneo marcaba tambien las
    detecciones de otros escaneos del mismo rango: lo que veias en el grafico no
    era lo que ponia en la tabla de ocurrencias de al lado.
    """
    job = _job_or_404(db, job_id)
    return _chart_response(
        symbol or job.symbol,
        timeframe or job.timeframe,
        date_from or job.date_from,
        date_to or job.date_to,
        features,
        patterns,
        job.id,
        max_points,
    )


@router.post("/scans/{job_id}/cancel", response_model=PatternScanJobResponse)
def cancel_scan(job_id: uuid.UUID, db: Session = Depends(get_db)):
    job = _job_or_404(db, job_id)
    if job.status in TERMINAL_STATUSES:
        raise HTTPException(status_code=400, detail="El job ya está en estado terminal")
    if not PatternScanService().cancel_job(job_id):
        raise HTTPException(status_code=400, detail="No se pudo cancelar el job")
    db.refresh(job)
    return job


@router.post("/scans/{job_id}/requeue", response_model=PatternScanJobResponse)
def requeue_scan(job_id: uuid.UUID, db: Session = Depends(get_db)):
    """Relanza un job. Acepta ``pending``, ``processing`` y ``failed``."""
    job = _job_or_404(db, job_id)
    if job.status not in REQUEUEABLE_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Un job en estado '{job.status}' no se puede reintentar; "
                "solo pending, processing o failed"
            ),
        )
    if not PatternScanService().requeue_job(job_id):
        raise HTTPException(status_code=400, detail="No se pudo reenviar el job")
    tasks.run_pattern_scan.delay(str(job_id))
    db.refresh(job)
    return job


@router.delete("/scans/{job_id}/logs")
def delete_scan_logs(job_id: uuid.UUID, db: Session = Depends(get_db)):
    _job_or_404(db, job_id)
    deleted = db.execute(delete(PatternScanLog).where(PatternScanLog.job_id == job_id))
    db.commit()
    return {"deleted": deleted.rowcount or 0}


@router.websocket("/scans/{job_id}/logs")
async def ws_logs(
    websocket: WebSocket, job_id: uuid.UUID, db: Session = Depends(get_db)
):
    await websocket.accept()
    offset = 0
    closed = False
    try:
        while True:
            db.expire_all()
            job = db.get(PatternScanJob, job_id)
            if job is None:
                await websocket.send_json({"error": "job not found"})
                break
            logs = db.scalars(
                select(PatternScanLog)
                .where(PatternScanLog.job_id == job_id)
                .order_by(PatternScanLog.timestamp, PatternScanLog.id)
                .offset(offset)
                .limit(200)
            ).all()
            for log in logs:
                await websocket.send_text(
                    PatternScanLogOut.model_validate(log).model_dump_json()
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


@router.delete("/scans/{job_id}")
def delete_scan(job_id: uuid.UUID, db: Session = Depends(get_db)):
    if not PatternScanService().delete_job(job_id):
        raise HTTPException(status_code=404, detail="Job no encontrado")
    return {"deleted": True, "job_id": str(job_id)}


@router.get("/scans/{job_id}", response_model=PatternScanJobResponse)
def get_scan(job_id: uuid.UUID, db: Session = Depends(get_db)):
    return _job_or_404(db, job_id)
