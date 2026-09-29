"""Endpoints de alertas.

Los códigos significan una cosa cada uno, y esa es la parte difícil:

- **200** la regla existe y se ha creado o modificado.
- **404** no existe la regla o la alerta.
- **409** solo para lo que no se puede permitir ni avisando: una dirección que
  contradice al catálogo, un patrón inexistente, un nombre vacío. Un veredicto
  `descartada` **no** es 409 desde la V1: la regla nace con su etiqueta y el aviso
  sale con su icono. Bloquearlo dejaba el sistema inservible con los datos
  actuales, y la reacción a un filtro inservible es buscar cómo saltarlo.
"""

import asyncio
import contextlib
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
)
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.alerts.backing import RespaldoNoAceptable
from app.modules.alerts.models import (
    AlertDeliveryStatus,
    AlertPatternCoverage,
    AlertRule,
    AlertVerdict,
)
from app.modules.alerts.service import (
    AlertNotFound,
    AlertNotReenviable,
    AlertService,
)
from app.modules.alerts.telegram import TelegramError

router = APIRouter(prefix="/api/v1/alerts", tags=["alerts"])

PAGE_SIZE = 50

# El orden de las rutas importa y por un motivo concreto: ``/rules`` se declara
# **antes** que ``/{alert_id}``, y si se invirtiera FastGPT intentaria leer
# "rules" como un UUID y devolvería 422 en vez de la lista de reglas. El tipo
# ``uuid.UUID`` protege las reglas, pero protege **después** de que el emparejador
# haya elegido la ruta, y eso no se puede cambiar desde el esquema.


class AlertRuleCreateIn(BaseModel):
    """Petición de `POST /api/v1/alerts/rules`.

    **No acepta TP, SL ni `max_hold`.** Es deliberado: si los admitiera, podría
    decir «respaldada por el informe X» y guardar otros niveles, y el aviso
    llevaría las credenciales de un experimento y los números de otro. La
    configuración sale del informe, o no hay informe y no hay niveles.
    """

    name: str = Field(min_length=1, max_length=80)
    pattern_name: str
    direction: Literal["bullish", "bearish"]
    #: Solo hacen falta sin informe de respaldo, que es cuando no hay escaneo de
    #: donde deducirlos. Con informe, mandan los de su escaneo.
    symbol: str | None = None
    timeframe: str | None = None
    walk_forward_run_id: uuid.UUID | None = None
    candidate_rank: int | None = Field(default=None, ge=1)
    cooldown_minutes: int = Field(default=60, ge=0, le=10080)


class AlertRulePatchIn(BaseModel):
    """Activar o desactivar. **No** toca la configuración.

    Cambiar los niveles de una regla es crear otra. Si se permitiera aquí, la
    configuración se habría elegido con los datos que ya se han visto y no
    quedaría rastro de cuándo: es el estado en el que una alerta deja de ser
    fuera de muestra.
    """

    enabled: bool


class AlertStrategyOut(BaseModel):
    take_profit_pct: float | None = None
    stop_loss_pct: float | None = None
    max_hold: int | None = None
    #: ``False`` en los informes anteriores a que se guardara la comisión. Se
    #: declara desconocido en vez de rellenarlo con el default de hoy.
    base_known: bool = True


class AlertRuleOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    symbol: str
    timeframe: str
    pattern_name: str
    direction: str
    config: AlertStrategyOut
    validation_status: AlertVerdict
    validation_note: str | None = None
    pattern_coverage: AlertPatternCoverage
    enabled: bool
    cooldown_minutes: int
    walk_forward_run_id: uuid.UUID | None = None
    candidate_rank: int | None = None
    backing_oi_low: float | None = None
    backing_oi_high: float | None = None
    backing_oos_return_pct: float | None = None
    backing_market_return_pct: float | None = None
    backing_windows: int | None = None
    backing_created_at: datetime
    last_alerted_at: datetime | None = None
    last_evaluated_at: datetime | None = None
    last_evaluation_note: str | None = None
    created_at: datetime


class AlertOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    rule_id: uuid.UUID
    signal_timestamp: datetime
    pattern_name: str
    direction: str
    symbol: str
    timeframe: str
    reference_price: float
    status: AlertDeliveryStatus
    telegram_message_id: int | None = None
    delivery_error: str | None = None
    attempts: int
    sent_at: datetime | None = None
    message_text: str | None = None
    detected_at: datetime


class AlertListOut(BaseModel):
    alerts: list[AlertOut]
    total: int


class TelegramProbeOut(BaseModel):
    ok: bool
    skipped: bool
    message_id: int | None = None
    error: str | None = None
    """El mismo texto que haría falta para arreglar un canal que no funciona."""
    pista: str | None = None


PISTAS = {
    "skipped": "TELEGRAM_ENABLED está apagado. Ponlo en true en el .env.",
    "chat": "Mándale /start al bot y copia el chat.id de getUpdates al .env.",
    "token": (
        "Revisa TELEGRAM_BOT_TOKEN en el .env; si se filtró, revócalo en @BotFather."
    ),
}


def _regla_out(regla: AlertRule) -> AlertRuleOut:
    salida = AlertRuleOut.model_validate(regla)
    salida.config = AlertStrategyOut(
        take_profit_pct=regla.config.get("take_profit_pct"),
        stop_loss_pct=regla.config.get("stop_loss_pct"),
        max_hold=regla.config.get("max_hold"),
        base_known=bool(regla.config.get("base_known", True)),
    )
    return salida


@router.get("/rules", response_model=list[AlertRuleOut])
def list_rules(
    db: Session = Depends(get_db),
    solo_activas: bool = Query(default=False),
):
    """Las reglas con su estado de validación.

    El estado va en la lista, no en un detalle al que hay que ir a mirar: es lo
    que el usuario consulta antes de decidir fiarse de un aviso, y si hay que
    pinchar para verlo, se acaba viendo la lista y no los estados.
    """
    reglas = AlertService().listar_reglas(db, solo_activas=solo_activas)
    return [_regla_out(r) for r in reglas]


@router.post("/rules", response_model=AlertRuleOut, status_code=201)
def create_rule(cuerpo: AlertRuleCreateIn, db: Session = Depends(get_db)):
    """Crea una regla. Nunca falla por el veredicto del respaldo.

    Lo que sí devuelve 409 es lo que no tiene arreglo avisando: una dirección
    opuesta a la que declara el catálogo, un patrón que no existe, un nombre
    vacío. El motivo va en el detalle para que se sepa qué corregir.
    """
    try:
        regla = AlertService().crear_regla(
            db,
            name=cuerpo.name,
            patron=cuerpo.pattern_name,
            direccion=cuerpo.direction,
            symbol=cuerpo.symbol,
            timeframe=cuerpo.timeframe,
            walk_forward_run_id=cuerpo.walk_forward_run_id,
            candidate_rank=cuerpo.candidate_rank,
            cooldown_minutes=cuerpo.cooldown_minutes,
        )
    except RespaldoNoAceptable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _regla_out(regla)


@router.patch("/rules/{rule_id}", response_model=AlertRuleOut)
def patch_rule(
    rule_id: uuid.UUID, cuerpo: AlertRulePatchIn, db: Session = Depends(get_db)
):
    try:
        regla = AlertService().activar(db, rule_id, cuerpo.enabled)
    except AlertNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _regla_out(regla)


@router.delete("/rules/{rule_id}", status_code=204)
def delete_rule(rule_id: uuid.UUID, db: Session = Depends(get_db)):
    if not AlertService().borrar_regla(db, rule_id):
        raise HTTPException(status_code=404, detail="La regla no existe")


@router.get("", response_model=AlertListOut)
def list_alerts(
    db: Session = Depends(get_db),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=PAGE_SIZE, ge=1, le=100),
    solo_fallidas: bool = Query(default=False),
):
    alertas, total = AlertService().listar_alertas(
        db,
        limite=page_size,
        offset=(page - 1) * page_size,
        solo_pendientes=solo_fallidas,
    )
    return AlertListOut(
        alerts=[AlertOut.model_validate(a) for a in alertas], total=total
    )


@router.get("/{alert_id}", response_model=AlertOut)
def get_alert(alert_id: uuid.UUID, db: Session = Depends(get_db)):
    try:
        return AlertOut.model_validate(AlertService().obtener_alerta(db, alert_id))
    except AlertNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{alert_id}/retry", response_model=AlertOut)
def retry_alert(alert_id: uuid.UUID, db: Session = Depends(get_db)):
    """Reenvía una alerta **fallida**.

    No reabre una `sent` —ya llegó— ni una `skipped` —nunca se intentó porque el
    canal estaba apagado—, y esa distinción es la que permite responder a la
    única pregunta que importa: ¿llegó?
    """
    try:
        return AlertOut.model_validate(AlertService().reintentar(db, alert_id))
    except AlertNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AlertNotReenviable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/telegram/probe", response_model=TelegramProbeOut)
def probe_telegram():
    """Prueba el canal y **dice cómo arreglarlo** si no funciona.

    La causa número uno de «las alertas no me llegan» es de configuración: un
    `/start` que no se mandó, un token mal pegado. Descubrirlo esperando una
    detección real es esperar horas para enterarse de un dedo que no se movió.
    """
    try:
        resultado = AlertService().probar_canal()
    except TelegramError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    pista = None
    if resultado.skipped:
        pista = PISTAS["skipped"]
    elif not resultado.ok:
        error = (resultado.error or "").lower()
        if "chat" in error or "not found" in error or "chat_id" in error:
            pista = PISTAS["chat"]
        elif "401" in error or "unauthorized" in error or "token" in error:
            pista = PISTAS["token"]
    return TelegramProbeOut(
        ok=resultado.ok,
        skipped=resultado.skipped,
        message_id=resultado.message_id,
        error=resultado.error,
        pista=pista,
    )


# --------------------------------------------------------------------------
# Avisos en vivo
# --------------------------------------------------------------------------
@router.websocket("/stream")
async def ws_alerts(websocket: WebSocket, db: Session = Depends(get_db)):
    """Alertas nuevas, en el momento en que se registran.

    A diferencia del WebSocket de los backtests, este **no** es un historial de
    líneas de log sino el aviso entero, ya con su estado de entrega. La razón es
    que la pregunta de esta pantalla es «¿se ha avisado de algo?», y para
    contestarla hace falta el estado: una alerta detectada que no llegó es
    información distinta de una que sí, y un log que dice «detectada» no
    distingue las dos.

    Emite por **identificador**, no reenvía la fila entera, y el cliente pide lo
    que le falte por HTTP. Mandar la fila entera por el socket significaría que
    el mensaje que se ve en pantalla y el que hay en la base pueden divergir si
    uno se actualiza entre los dos, que es justo lo que se quiere evitar.
    """
    from app.modules.alerts.models import Alert

    await websocket.accept()
    ultimo = datetime.now(timezone.utc)
    vistos: set[uuid.UUID] = set()
    try:
        while True:
            db.expire_all()
            nuevos = db.scalars(
                select(Alert.id)
                .where(Alert.detected_at > ultimo)
                .order_by(Alert.detected_at)
                .limit(50)
            ).all()
            for identificador in nuevos:
                if identificador in vistos:
                    continue
                vistos.add(identificador)
                await websocket.send_json({"alert_id": str(identificador)})
                ultimo = datetime.now(timezone.utc)
            if len(vistos) > 500:
                # El conjunto se acota: sin esto, una sesion larga acumularia
                # identificadores para siempre en un cliente abierto todo el dia.
                vistos = {v for v in list(vistos)[-200:]}
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        return
    finally:
        with contextlib.suppress(RuntimeError):
            await websocket.close()
