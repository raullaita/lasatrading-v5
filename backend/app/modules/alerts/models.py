"""Modelos del modulo de alertas.

Un ``alert_rule`` es la decision del usuario de vigilar un patron con una
configuracion concreta, y ``alert`` es cada aviso que esa regla produjo. Las
tres ideas que gobiernan el esquema:

1. **La evidencia se copia en la regla, no se lee del informe.** El veredicto y
   el IC95% se congelan en el momento de crear la regla, con su fecha. El
   informe es un artefacto historico y la regla es una decision presente: si se
   recalculara, el IC cambiaria bajo una regla ya creada y la evidencia de esa
   regla dejaria de ser la que el usuario miro al crearla. Copiarlo con la fecha
   lo hace auditable, y ``backing_created_at`` permite ensenar cuantos meses
   tiene el respaldo, que es la parte que caduca.

2. **Una regla solo nace de un respaldo no descartado.** No es una validacion
   del servicio ni de la API: es una invariante del dominio, y lo que la
   sostiene es que ``backing_verdict`` esta en la misma fila. Se puede leer sin
   joins, y un informe de alertas dice por que se creo cada regla sin tener que
   reconstruirlo.

3. **La deduplicacion es un indice unico, no logica de servicio.**
   ``(rule_id, signal_timestamp)`` garantiza que la misma vela no genera dos
   avisos de la misma regla aunque dos evaluaciones se solapen. Una garantia que
   depende de que nadie se equivoque no es una garantia: la reejecucion de una
   tarea, dos workers, o un relanzamiento manual producen el mismo par y solo el
   indice lo detiene.
"""

import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class AlertChannel(str, Enum):
    """Canales de entrega.

    Solo ``TELEGRAM`` existe. ``EMAIL`` estuvo en el diseno y se descarto: un
    aviso que llega mientras alguien mira un grafico se lee en segundos, y un
    email se lee en minutos, en una bandeja con filtros. Se deja el enum para
    que anadir un canal sea un valor mas y no una migracion.
    """

    TELEGRAM = "telegram"


class AlertVerdict(str, Enum):
    """El estado de validacion de una regla.

    Deliberadamente **no** es el mismo tipo que
    ``walk_forward.WalkForwardVerdict``: aquel describe el resultado de un
    analisis, y este describe el estado de una regla. Un dia el walk-forward
    anada un veredicto y esta tabla tendria que migrar, cuando lo correcto es
    que la regla acepte el nuevo como un valor mas.

    ## Por que `DESCARTADA` y `SIN_EVALUAR` son reglas y no un rechazo

    Una version anterior de este modulo rechazaba la creacion de la regla con un
    409 si el veredicto era `descartada`, y tambien si el informe no habia
    evaluado ese patron. Era la postura correcta en teoria y **equivocada en la
    practica**: con 389 dias de datos, un walk-forward rara vez da `sostenida` con
    una rejilla grande, asi que el sistema habria sido inservible y la reaccion
    natural habria sido buscar la manera de saltarse el filtro.

    Ahora la herramienta **informa y el usuario decide**. La consecuencia es que
    la seguridad ya no esta en el rechazo, sino en que el estado sea
    **imposible de no ver**: va en el mensaje de Telegram con su icono, en la
    columna principal de la lista, y `pattern_coverage` avisa por separado de
    que la configuracion no se probo con ese patron. Un sistema que esconde la
    informacion para proteger al usuario no lo protege: solo lo aleja de ella.
    """

    SOSTENIDA = "sostenida"
    PROMETEDORA = "prometedora"
    DESCARTADA = "descartada"
    #: La regla existe y no hay ningun informe que diga nada de ella. Es el estado
    #: mas frecuente al principio, y el que mas claramente dice «esto es una
    #: intuicion, no un resultado».
    SIN_EVALUAR = "sin_evaluar"

    @property
    def validada(self) -> bool:
        """Si hay un veredicto que no sea un descarte.

        `descartada` **no** es validada, aunque el veredicto exista: el optimizador
        ya lo rechazo. `sin_evaluar` tampoco, por definicion.
        """
        return self in (AlertVerdict.SOSTENIDA, AlertVerdict.PROMETEDORA)


class AlertPatternCoverage(str, Enum):
    """Si el informe de respaldo evaluo el patron de la regla.

    Se lleva por separado del veredicto porque son dos preguntas distintas y
    confundirlas es el error mas caro del modulo:

    - El **veredicto** responde «cuando se simulo sobre los datos que el
      informe vio, ¿como rindio?».
    - La **cobertura** responde «¿llego siquiera a simular este patron?».

    Un informe sobre un escaneo de cuatro patrones puede dar `sostenida` y
    seguir sin haber mirado jamas el patron del que alerta la regla. Un veredicto
    alto con cobertura `fuera_de_filtro` no es evidencia de nada sobre ese
    patron, y esconder esa distincion detras de un numero bonito es como se
    acaban mandando avisos de combinaciones que nadie simulo.
    """

    SIN_INFORME = "sin_informe"
    CUBIERTO = "cubierto"
    FUERA_DE_FILTRO = "fuera_de_filtro"


class AlertDeliveryStatus(str, Enum):
    """Donde esta un aviso. Distingue tres cosas que en la base se verian igual.

    ``SKIPPED`` existe por el interruptor global: una alerta con el canal apagado
    **no es** una alerta fallida, es una alerta que no se intento entregar. Sin
    esa distincion, apagar el sistema y tener un fallo de red producen el mismo
    estado, y no se puede responder a la unica pregunta que importa en una
    auditoria: ``llego?``.
    """

    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"


class AlertRule(Base):
    """La configuracion vigilada: patron, direccion y niveles ya validados."""

    __tablename__ = "alert_rules"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    pattern_name: Mapped[str] = mapped_column(String(64), nullable=False)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)

    #: Configuracion congelada, copiada del run que respalda: TP, SL, max_hold,
    #: comisiones, fraccion y si se permite vender. **No se edita** desde el
    #: PATCH. Una configuracion elegida con los datos que ya se han visto no se
    #: puede reajustar con los que vienen: seria dejar de ser fuera de muestra,
    #: y ademas el cambio no quedaria en ninguna parte si se permitiera.
    config: Mapped[dict] = mapped_column(JSONB, nullable=False)

    #: El respaldo, y su evidencia congelada. Ver los tres puntos del modulo.
    #:
    #: El respaldo **obligatorio** es `walk_forward_run_id` + `candidate_rank`,
    #: porque es lo unico que lleva un veredicto. Un `backtest_runs` no lleva
    #: ninguno: que su simulacion terminara no dice nada sobre si la
    #: configuracion funciona, que es justo lo que la 5.5 demostro midiendo.
    #:
    #: `backtest_run_id` es por eso **opcional**, y apunta a un backtest que
    #: tambien evaluo esa configuracion en un rango mas largo. Es evidencia
    #: adicional que el usuario puede anadir, no un requisito: exigirlo
    #: obligaria a tener un segundo experimento para poder vigilar la primera
    #: conclusion, y la conclusion ya esta.
    backtest_run_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("backtest_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    #: ``SET NULL`` y no ``CASCADE`` a proposito: el respaldo es evidencia
    #: acumulada, y que el usuario borre un informe no debe dejarle la regla sin
    #: la conclusion en la que se baso. Se queda con el veredicto copiado y la
    #: pantalla avisa de que el informe ya no esta.
    walk_forward_run_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("walk_forward_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    candidate_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: Estado de validacion, con `sin_evaluar` como estado de primera clase y no
    #: como `NULL`. Un `NULL` no se puede filtrar en la lista sin tratarlo como un
    #: caso especial, y un caso especial en la columna que decide si el aviso
    #: lleva candil verde o rojo es donde se cuela un aviso sin mirar.
    validation_status: Mapped[str] = mapped_column(
        String(20), default=AlertVerdict.SIN_EVALUAR.value
    )
    #: Aviso que se escribe en el mensaje de Telegram. Lo compone el codigo y no
    #: el cliente, por el mismo motivo que el descargo: si lo escribiera quien
    #: crea la regla, podria decir cualquier cosa.
    validation_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Si el informe de respaldo llego a simular este patron. Vive aparte del
    #: veredicto y se muestra aparte, porque son dos preguntas distintas y
    #: confundirlas es como se avisa de combinaciones que nadie simulo.
    pattern_coverage: Mapped[str] = mapped_column(
        String(20), default=AlertPatternCoverage.SIN_INFORME.value
    )
    #: IC95% en la creación. Fraccion en [0, 1] o porcentaje, lo que se congele;
    #: se copia tal cual y se muestra sin reinterpretar, porque un numero de
    #: evidencia no se reinterpreta al guardarlo.
    backing_oi_low: Mapped[float | None] = mapped_column(Numeric(14, 6), nullable=True)
    backing_oi_high: Mapped[float | None] = mapped_column(Numeric(14, 6), nullable=True)
    backing_created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    #: Lo que rindio el respaldo, en la misma linea y por el mismo motivo que el
    #: veredicto. El mensaje lo enseña: un aviso que obliga a abrir otra pantalla
    #: para saber si fiarse de el, se lee sin comprobar.
    backing_oos_return_pct: Mapped[float | None] = mapped_column(
        Numeric(12, 6), nullable=True
    )
    backing_market_return_pct: Mapped[float | None] = mapped_column(
        Numeric(12, 6), nullable=True
    )
    backing_windows: Mapped[int | None] = mapped_column(Integer, nullable=True)

    channel: Mapped[str] = mapped_column(
        String(20), default=AlertChannel.TELEGRAM.value
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    #: Antiguedad minima entre avisos de esta regla. Un patron puede disparar
    #: cada pocas velas y Telegram admite 1 mensaje por segundo y por chat; sin
    #: este numero el usuario recibe decenas por hora, lo apaga, y no vuelve a
    #: encenderlo. Un sistema de avisos que se apaga no es un sistema de avisos.
    cooldown_minutes: Mapped[int] = mapped_column(Integer, default=60)
    #: **Nunca se rellena**, y el campo existe para que el motivo quede escrito
    #: al lado. Los detectores son booleanos: `scan_macd_crossover` devuelve la
    #: vela donde la linea cruza, sin ninguna probabilidad asociada. No hay un
    #: numero de confianza del patron, y un filtro sobre una constante inventada
    #: da la sensacion de filtrar sin filtrar nada. Si el catalogo expone una
    #: confianza real algum dia, se implementa aqui.
    min_confidence: Mapped[float | None] = mapped_column(Numeric(12, 6), nullable=True)
    last_alerted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: Ultimo resultado de evaluar la regla, para que "no ha saltado" se pueda
    #: distinguir de "no se ha mirado". Sin esto, una regla que no dispara nunca
    #: y una regla que el evaluador no ha corrido se ven igual en la pantalla.
    last_evaluated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_evaluation_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    alerts: Mapped[list["Alert"]] = relationship(
        back_populates="rule",
        cascade="all, delete-orphan",
        order_by="Alert.signal_timestamp",
    )

    __table_args__ = (
        Index("ix_alert_rules_symbol", "symbol", "timeframe"),
        Index("ix_alert_rules_enabled", "enabled"),
    )


class Alert(Base):
    """Un aviso disparado. Es un registro historico, y por eso lleva copia de lo
    que detecto, aunque la regla se edite despues.

    Redundar ``pattern_name``, ``direction``, ``symbol`` y ``timeframe`` es
    deliberado: la alerta dice lo que ocurrio y lo que se aviso, no lo que la
    regla dice hoy.
    """

    __tablename__ = "alerts"
    __table_args__ = (
        # La deduplicacion. Ver el punto 3 del modulo.
        UniqueConstraint("rule_id", "signal_timestamp", name="uq_alerts_rule_signal"),
        Index("ix_alerts_rule_status", "rule_id", "status"),
        Index("ix_alerts_detected", "detected_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    rule_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("alert_rules.id", ondelete="CASCADE"),
        nullable=False,
    )

    signal_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    pattern_name: Mapped[str] = mapped_column(String(64), nullable=False)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)

    #: Cierre de la vela de la señal. **No es el precio de entrada**: la regla de
    #: entrada del motor es la apertura de T+1, que en el momento del aviso aun no
    #: ha ocurrido. Es la referencia sobre la que el usuario puede calcular los
    #: niveles, y el mensaje lo llama asi.
    reference_price: Mapped[float] = mapped_column(Numeric(20, 8), nullable=False)

    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    status: Mapped[str] = mapped_column(
        String(20), default=AlertDeliveryStatus.PENDING.value
    )
    #: Lo que devuelve la API de Telegram. Es lo unico que prueba que el mensaje
    #: existio; sin el, "entregado" es una intencion.
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    delivery_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: El texto exacto enviado, congelado. Telegram deja editar mensajes y el
    #: contenido puede cambiar; lo que se audito es lo que salio ese dia.
    message_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    rule: Mapped["AlertRule"] = relationship(back_populates="alerts")
    deliveries: Mapped[list["AlertDelivery"]] = relationship(
        back_populates="alert",
        cascade="all, delete-orphan",
        order_by="AlertDelivery.attempt",
    )


class AlertDelivery(Base):
    """Un intento de entrega, con lo que la API respondio.

    No es una tabla decorativa: es la que responde ``llego?`` cuando alguien
    pregunte. Sin ella, una alerta fallida y una alerta nunca intentada se ven
    igual en la base, porque ambas son filas que no estan en Telegram.
    """

    __tablename__ = "alert_deliveries"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    alert_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("alerts.id", ondelete="CASCADE"),
        nullable=False,
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: Cuerpo crudo de la API, **redactado**: el cliente sustituye el token por
    #: `bot<token>` antes de devolverlo, porque este texto se escribe en la base
    #: y acaba en un log.
    response_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    ok: Mapped[bool] = mapped_column(Boolean, default=False)
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    alert: Mapped["Alert"] = relationship(back_populates="deliveries")
