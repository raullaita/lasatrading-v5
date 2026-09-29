"""El servicio de alertas: crear reglas, evaluarlas y entregarlas.

El orden importa aquí también. `crear_regla` es la puerta de la spec y ya vive en
`backing.py`; este módulo es la orquestación que la rodea.

## Las tres cosas que este módulo no puede equivocar

1. **No avisar dos veces de la misma vela.** La deduplicación es un índice único
   en la base, y aquí se apoya en él en vez de comprobarlo antes. Una comprobación
   previa es una carrera: dos evaluaciones simultáneas, o una tarea reejecutada,
   pasan las dos y escriben dos filas. La clave primaria es lo único que no
   depende de que nadie mire antes.

2. **No convertir «el canal está apagado» en silencio.** Con el interruptor
   apagado la alerta **se escribe** con estado `skipped` y su motivo. Un sistema
   de avisos que se apaga no avisa, y no se puede saber después si no avisó
   porque no pasó nada o porque estaba apagado. La diferencia entre esas dos cosas
   es la única pregunta que la auditoría hace.

3. **No mandar un aviso dentro del enfriamiento de la regla.** Un MACD sobre 1h
   puede disparar cada pocas velas y Telegram admite un mensaje por segundo y
   por chat. Quien recibe cuarenta mensajes en una hora apaga el sistema y no
   vuelve a encenderlo.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.modules.alerts.backing import crear_regla as _crear_regla_con_respaldo
from app.modules.alerts.evaluator import Deteccion, Evaluacion, evaluar_regla
from app.modules.alerts.message import mensaje_alerta
from app.modules.alerts.models import (
    Alert,
    AlertDelivery,
    AlertDeliveryStatus,
    AlertRule,
)
from app.modules.alerts.telegram import TelegramClient, TelegramResult


@dataclass(frozen=True, slots=True)
class ResumenEvaluacion:
    """Lo que pasó en una pasada completa, para el log y para la respuesta."""

    evaluadas: int
    detecciones: int
    avisadas: int
    omitidas_enfriamiento: int
    duplicadas: int
    errores: int
    notas: tuple[str, ...]


class AlertService:
    # --------------------------------------------------------------- reglas

    def crear_regla(self, db: Session, **campos) -> AlertRule:
        """Crea la regla. No hay 409 por veredicto: el estado va en la regla.

        Lo que sí lanza es lo que no se puede permitir ni avisando: una dirección
        que contradice al catálogo, un patrón inexistente, un nombre vacío. Eso
        está en `backing.py` y el motivo explica por qué.
        """
        regla = _crear_regla_con_respaldo(db, **campos)
        db.commit()
        db.refresh(regla)
        return regla

    def listar_reglas(self, db: Session, solo_activas: bool = False) -> list[AlertRule]:
        stmt = select(AlertRule)
        if solo_activas:
            stmt = stmt.where(AlertRule.enabled.is_(True))
        return list(db.scalars(stmt.order_by(AlertRule.created_at.desc())).all())

    def obtener_regla(self, db: Session, regla_id: uuid.UUID) -> AlertRule:
        regla = db.get(AlertRule, regla_id)
        if regla is None:
            raise AlertNotFound("La regla no existe")
        return regla

    def activar(self, db: Session, regla_id: uuid.UUID, enabled: bool) -> AlertRule:
        """Activa o desactiva. **No** toca la configuración.

        Cambiar los niveles de una regla es crear otra. Si se permitiera editar
        aquí, la configuración se habría elegido con los datos que ya se han
        visto y quedaría sin rastro de cuándo, que es exactamente el estado en el
        que una alerta deja de ser fuera de muestra.
        """
        regla = self.obtener_regla(db, regla_id)
        regla.enabled = enabled
        db.commit()
        db.refresh(regla)
        return regla

    def borrar_regla(self, db: Session, regla_id: uuid.UUID) -> bool:
        regla = db.get(AlertRule, regla_id)
        if regla is None:
            return False
        db.delete(regla)
        db.commit()
        return True

    # ---------------------------------------------------------- evaluacion

    def evaluar_todas(
        self,
        db: Session,
        cliente: TelegramClient | None = None,
        intervalo_s: float = 300.0,
    ) -> ResumenEvaluacion:
        """Una pasada por todas las reglas activas.

        El cliente se puede pasar para los tests y para el envío en lote; si no se
        pasa se abre uno aquí y se cierra. Cada regla se evalúa con su propia
        sesión de base de datos para que una excepción en una no se lleve por
        delante las demás: una regla con un patrón roto no puede impedir que las
        otras avisen.
        """
        notas: list[str] = []
        evaluadas = detecciones = avisadas = omitidas = duplicadas = errores = 0

        with SessionLocal() as db:
            ids = [
                r.id
                for r in db.scalars(
                    select(AlertRule).where(AlertRule.enabled.is_(True))
                ).all()
            ]

        propio = cliente is None
        cliente_telegram = cliente or TelegramClient()
        try:
            for regla_id in ids:
                with SessionLocal() as db:
                    regla = db.get(AlertRule, regla_id)
                    if regla is None or not regla.enabled:
                        continue
                    evaluadas += 1
                    evaluacion = evaluar_regla(db, regla, intervalo_s)
                    regla.last_evaluated_at = datetime.now(timezone.utc)
                    regla.last_evaluation_note = (
                        f"[{evaluacion.ruta}] {evaluacion.motivo}"
                    )
                    db.commit()

                if evaluacion.ruta in {"error", "ninguna"}:
                    errores += 1
                    notas.append(f"{regla_id}: {evaluacion.motivo}")
                    continue

                for deteccion in evaluacion.detections:
                    detecciones += 1
                    resultado = self._disparar(
                        cliente_telegram, regla, deteccion, evaluacion
                    )
                    if resultado == "entregada":
                        avisadas += 1
                    elif resultado == "enfriamiento":
                        omitidas += 1
                    elif resultado == "duplicada":
                        duplicadas += 1
                    else:
                        errores += 1
                        notas.append(f"{regla_id}: {resultado}")
        finally:
            if propio:
                cliente_telegram.close()

        return ResumenEvaluacion(
            evaluadas=evaluadas,
            detecciones=detecciones,
            avisadas=avisadas,
            omitidas_enfriamiento=omitidas,
            duplicadas=duplicadas,
            errores=errores,
            notas=tuple(notas[:10]),
        )

    def _disparar(
        self,
        cliente: TelegramClient,
        regla: AlertRule,
        deteccion: Deteccion,
        evaluacion: Evaluacion,
    ) -> str:
        """Escribe el aviso, lo entrega y anota el resultado.

        El orden es deliberado: **se escribe antes de entregar**. Si la entrega
        falla, el aviso existe con su error y se puede reintentar; si se entregara
        primero y la escritura fallara, el mensaje saldría y no habría registro de
        él, que es un aviso sin auditoría.
        """
        if not self._fuera_de_enfriamiento(regla):
            return "enfriamiento"

        with SessionLocal() as db:
            # Pre-comprobación **además** del índice único, no en vez de él. Con
            # velas de 1 hora y un evaluador cada 5 minutos, la misma vela está
            # en la ventana 12 veces y las 12 intentarían insertar; sin esta
            # comprobación cada una abre una transacción que acaba en
            # IntegrityError y rollback. El índice sigue siendo la garantía real
            # —esto solo evita el ruido en el caso normal, que no es el de
            # carrera—.
            ya_avisada = db.scalar(
                select(Alert.id)
                .where(
                    Alert.rule_id == regla.id,
                    Alert.signal_timestamp == deteccion.timestamp.to_pydatetime(),
                )
                .limit(1)
            )
            if ya_avisada is not None:
                return "duplicada"
            aviso = Alert(
                rule_id=regla.id,
                signal_timestamp=deteccion.timestamp.to_pydatetime(),
                pattern_name=deteccion.pattern_name,
                direction=regla.direction,
                symbol=regla.symbol,
                timeframe=regla.timeframe,
                reference_price=deteccion.reference_price,
                status=AlertDeliveryStatus.PENDING.value,
            )
            db.add(aviso)
            try:
                db.commit()
            except IntegrityError:
                # La clave unica `(rule_id, signal_timestamp)` ha hecho su
                # trabajo. Es la garantia real: una comprobacion previa seria
                # una carrera entre dos evaluaciones.
                db.rollback()
                return "duplicada"
            db.refresh(aviso)
            aviso_id = aviso.id
            texto = mensaje_alerta(regla, deteccion)

        resultado = cliente.enviar(texto)

        with SessionLocal() as db:
            aviso = db.get(Alert, aviso_id)
            if aviso is None:
                return "desaparecida"
            aviso.attempts = resultado.attempts
            aviso.message_text = texto
            if resultado.skipped:
                aviso.status = AlertDeliveryStatus.SKIPPED.value
                aviso.delivery_error = resultado.error
            elif resultado.ok:
                aviso.status = AlertDeliveryStatus.SENT.value
                aviso.telegram_message_id = resultado.message_id
                aviso.sent_at = datetime.now(timezone.utc)
            else:
                aviso.status = AlertDeliveryStatus.FAILED.value
                aviso.delivery_error = resultado.error
            db.add(
                AlertDelivery(
                    alert_id=aviso.id,
                    attempt=resultado.attempts,
                    ok=resultado.ok,
                    response_body=resultado.response_body,
                )
            )
            db.commit()

        if resultado.ok:
            with SessionLocal() as db:
                regla = db.get(AlertRule, regla.id)
                if regla is not None:
                    regla.last_alerted_at = datetime.now(timezone.utc)
                    db.commit()
        return "entregada" if resultado.ok else (resultado.error or "fallo")

    @staticmethod
    def _fuera_de_enfriamiento(regla: AlertRule) -> bool:
        if regla.last_alerted_at is None or regla.cooldown_minutes <= 0:
            return True
        referencia = regla.last_alerted_at
        if referencia.tzinfo is None:
            referencia = referencia.replace(tzinfo=timezone.utc)
        limite = datetime.now(timezone.utc) - timedelta(minutes=regla.cooldown_minutes)
        return referencia <= limite

    # -------------------------------------------------------------- entrega

    def probar_canal(self, cliente: TelegramClient | None = None) -> TelegramResult:
        """Envía un mensaje de prueba.

        Existe por una razón concreta: la causa número uno de «las alertas no me
        llegan» es de configuración —un `/start` que no se mandó, un token mal
        pegado— y descubrirlo esperando una detección real del mercado es esperar
        horas para enterarse de un dedo que no se movió.
        """
        from app.modules.alerts.message import mensaje_prueba

        propio = cliente is None
        c = cliente or TelegramClient()
        try:
            return c.enviar(mensaje_prueba())
        finally:
            if propio:
                c.close()

    # -------------------------------------------------------------- lectura

    def listar_alertas(
        self,
        db: Session,
        limite: int = 50,
        offset: int = 0,
        solo_pendientes: bool = False,
    ) -> tuple[list[Alert], int]:
        total = db.scalar(select(func.count()).select_from(Alert)) or 0
        stmt = select(Alert)
        if solo_pendientes:
            stmt = stmt.where(Alert.status == AlertDeliveryStatus.FAILED.value)
        alertas = db.scalars(
            stmt.order_by(Alert.detected_at.desc()).limit(limite).offset(offset)
        ).all()
        return list(alertas), total

    def obtener_alerta(self, db: Session, alert_id: uuid.UUID) -> Alert:
        alerta = db.get(Alert, alert_id)
        if alerta is None:
            raise AlertNotFound("La alerta no existe")
        return alerta

    def reintentar(self, db: Session, alert_id: uuid.UUID) -> Alert:
        """Reenvía una alerta fallida.

        No reabre la de `sent` ni la de `skipped`: la primera ya llegó y la
        segunda nunca se intentó porque el canal estaba apagado, y reenviar la
        segunda sin querer convertiría «no podía avisar» en «avisó dos veces».
        """
        from app.modules.alerts.telegram import TelegramClient

        alerta = self.obtener_alerta(db, alert_id)
        if alerta.status != AlertDeliveryStatus.FAILED.value:
            raise AlertNotReenviable(
                f"Solo se reenvían las alertas fallidas; esta está '{alerta.status}'."
            )
        regla = db.get(AlertRule, alerta.rule_id)
        texto = alerta.message_text
        if texto is None and regla is not None:
            texto = mensaje_alerta(
                regla,
                Deteccion(
                    timestamp=pd.Timestamp(alerta.signal_timestamp),
                    pattern_name=alerta.pattern_name,
                    reference_price=float(alerta.reference_price),
                    ruta="reenvio",
                ),
            )
        with TelegramClient() as cliente:
            resultado = cliente.enviar(texto or "")
        if resultado.ok:
            alerta.status = AlertDeliveryStatus.SENT.value
            alerta.telegram_message_id = resultado.message_id
            alerta.sent_at = datetime.now(timezone.utc)
            alerta.delivery_error = None
        else:
            alerta.attempts += resultado.attempts
            alerta.delivery_error = resultado.error
        db.add(
            AlertDelivery(
                alert_id=alerta.id,
                attempt=alerta.attempts,
                ok=resultado.ok,
                response_body=resultado.response_body,
            )
        )
        db.commit()
        db.refresh(alerta)
        return alerta


class AlertNotFound(Exception):
    pass


class AlertNotReenviable(Exception):
    pass
