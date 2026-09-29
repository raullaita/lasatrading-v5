"""Cliente de Telegram para las alertas de la Tarea 6.

Síncrono a propósito. El módulo de alertas vive en el mismo contexto que el
resto del pipeline (``execute_scan``, ``execute_run``): Celery con una tarea
sincrónica y SQLAlchemy bloqueante. Envolver un cliente síncrono en asyncio para
usarlo desde un hilo sin evento obliga a propagar el await por toda la cadena, y
en este proyecto ya se payó el coste de esa decisión una vez.

Dos decisiones de diseño que conviene que se lean antes que el código:

1. **El apagado no es un return vacío.** ``TELEGRAM_ENABLED = false`` devuelve un
   resultado con ``skipped`` y su motivo, y el servicio lo persiste como alerta
   no entregada. Un silencio que no deja rastro es indistinguible de "no ha
   pasado nada", y en un sistema de avisos esa es la peor forma de callar.

2. **El token nunca aparece en un log ni en un error.** Los mensajes de error
   llevan el status y el cuerpo de Telegram, y el cuerpo nunca lleva el token
   porque la API no lo devuelve. La URL, en cambio, sí lo lleva, y por eso los
   errores que las incluyen la sustituyen por ``bot<token>`` antes de
   formatear.
"""

from __future__ import annotations

import html
import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from app.config import Settings, get_settings

TELEGRAM_API = "https://api.telegram.org"


class TelegramError(Exception):
    """Fallo de configuración o de transporte que impide ni intentar enviar.

    Se distingue de un ``TelegramResult(ok=False)`` porque este ultimo es un
    resultado **legítimo**: la alerta existe, se registró, y lo que falló fue
    entregar un mensaje. Este es un fallo de la maquinaria.
    """


@dataclass(frozen=True, slots=True)
class TelegramResult:
    """Qué pasó al intentar entregar un mensaje.

    ``skipped`` y ``ok=False`` son estados distintos a propósito: lo primero es
    "no se intentó porque el interruptor está apagado", lo segundo es "se
    intentó y no llegó". El servicio los escribe distinto, porque la pregunta que
    responde cada uno es distinta.
    """

    ok: bool
    skipped: bool
    message_id: int | None
    attempts: int
    error: str | None
    #: Cuerpo crudo de Telegram, para la auditoria de la entrega.
    response_body: str | None = None


def escapar(texto: str) -> str:
    """Escapa lo minimo que exige ``parse_mode=HTML``.

    Solo tres caracteres, y es una decision: se usa HTML y no ``MarkdownV2``,
    que obliga a escapar 18 (``_ * [ ] ( ) ~ > # + - = | { } . !``). Con
    MarkdownV2 un ``1.5`` sin escapar rompe el mensaje entero, y los numeros de
    este mensaje son casi todos decimales. HTML con tres escapes no se rompe.
    """
    return html.escape(texto, quote=False)


def truncar(texto: str, maximo: int) -> str:
    """Recorta al limite de Telegram marcando el corte.

    El ``…`` del final no es cosmetico: un mensaje cortado en mitad de un numero
    es peor que no enviado, porque el numero cortado se puede leer como otro
    numero. Cutarlo aqui, con la marca, es peor pero no engañoso.
    """
    if len(texto) <= maximo:
        return texto
    # Se deja sitio al "…" y se intenta cortar en un salto de linea o un punto y
    # coma, para que no parta una frase por la mitad sin avisar.
    margen = maximo - 1
    corte = texto.rfind("\n", 0, margen)
    if corte < margen * 0.6:
        corte = texto.rfind("; ", 0, margen)
    if corte < margen * 0.6:
        corte = margen
    return texto[:corte].rstrip() + "…"


class TelegramClient:
    """Envío de mensajes de texto a un chat de Telegram.

    El transporte se puede inyectar, que es lo que permite probar el cliente
    entero —incluidos los 429 y los reintentos— sin hacer una sola llamada de
    red. Un test que solo verifica la URL correcta searia un test que no
    comprueba lo unico que puede fallar de verdad.
    """

    def __init__(
        self,
        transport: httpx.BaseTransport | None = None,
        ahora: Callable[[], float] = time.monotonic,
        dormir: Callable[[float], None] = time.sleep,
        settings: Settings | None = None,
    ) -> None:
        #: La configuracion se **inyecta** y no se pide dentro. `get_settings()`
        #: construye una instancia nueva en cada llamada, asi que un test que
        #: parchee el resultado de su propia llamada no cambia lo que ve el
        #: cliente; y un cliente que lee un global es un cliente cuyos tests
        #: dependen del entorno de quien los ejecuta.
        self.settings = settings or get_settings()
        self._ahora = ahora
        self._dormir = dormir
        self._ultimo_envio: float | None = None
        self._client = httpx.Client(
            base_url=TELEGRAM_API,
            timeout=httpx.Timeout(15.0, connect=5.0),
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> TelegramClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------- interno

    def _url(self, metodo: str) -> str:
        token = self.settings.TELEGRAM_BOT_TOKEN
        if not token:
            raise TelegramError(
                "TELEGRAM_BOT_TOKEN no está configurado. Habla con @BotFather para "
                "crear el bot y pega el token en el .env."
            )
        return f"/bot{token}/{metodo}"

    def _redactar(self, texto: str) -> str:
        """Quita el token de cualquier texto antes de mostrarlo o guardarlo."""
        token = self.settings.TELEGRAM_BOT_TOKEN
        return texto.replace(token, "bot<token>") if token else texto

    def _esperar_turno(self) -> None:
        """Respeta el intervalo minimo entre mensajes al mismo chat.

        No es un detalle de cortesia: Telegram admite 1 mensaje por segundo y por
        chat, y pasarse devuelve 429. Gastar la cuota de la API para descubrirlo
        en produccion, con la primera alerta de un lote, es pagarlo con el
        aviso mas importante.
        """
        minimo = self.settings.TELEGRAM_MIN_INTERVAL_SECONDS
        if self._ultimo_envio is not None and minimo > 0:
            faltan = minimo - (self._ahora() - self._ultimo_envio)
            if faltan > 0:
                self._dormir(faltan)
        self._ultimo_envio = self._ahora()

    @staticmethod
    def _retry_after(cuerpo: dict, por_defecto: float) -> float:
        """El ``retry_after`` de la API, si lo manda.

        Es la API diciendo "vuelve en estos segundos", y es mas fiable que
        cualquier retroceso propio. Si viene, se usa; si no, el retroceso.
        """
        parametros = cuerpo.get("parameters") or {}
        valor = parametros.get("retry_after")
        if isinstance(valor, (int, float)) and valor > 0:
            return float(valor)
        return por_defecto

    def _retroceso(self, intento: int) -> float:
        return float(min(2.0 ** (intento - 1), 30.0))

    # -------------------------------------------------------------- publico

    def enviar(self, texto: str, chat_id: str | None = None) -> TelegramResult:
        """Envia un mensaje de texto. Nunca lanza por un fallo de entrega.

        Devolver el fallo en vez de levantarlo es lo que permite que el servicio
        registre la alerta y su intento de entrega, en vez de que un 400 de
        Telegram se lleve por delante la escritura de la alerta que si se
        produjo. Un aviso que no llego es un dato; un aviso que no se registro es
        un agujero.
        """
        destino = chat_id or self.settings.TELEGRAM_CHAT_ID
        if not self.settings.TELEGRAM_ENABLED:
            return TelegramResult(
                ok=False,
                skipped=True,
                message_id=None,
                attempts=0,
                error="TELEGRAM_ENABLED está apagado: no se intentó enviar",
            )
        if not destino:
            raise TelegramError(
                "TELEGRAM_CHAT_ID no está configurado. Un bot no puede escribir a "
                "alguien que no le haya escrito primero: mándale /start al bot y "
                "copia el chat.id de getUpdates al .env."
            )

        cuerpo = truncar(texto, self.settings.TELEGRAM_MAX_MESSAGE_CHARS)
        max_intentos = max(1, self.settings.TELEGRAM_MAX_ATTEMPTS)
        ultimo_error: str | None = None
        cuerpo_respuesta: str | None = None

        for intento in range(1, max_intentos + 1):
            self._esperar_turno()
            try:
                respuesta = self._client.post(
                    self._url("sendMessage"),
                    json={
                        "chat_id": destino,
                        "text": cuerpo,
                        "parse_mode": "HTML",
                        # Sin esto Telegram corta el mensaje largo por su cuenta,
                        # sin avisar, y el corte cae donde cae.
                        "disable_web_page_preview": True,
                    },
                )
            except httpx.TimeoutException as exc:
                ultimo_error = self._redactar(f"Timeout esperando a Telegram: {exc}")
            except httpx.TransportError as exc:
                # El mensaje de `httpx` incluye la URL pedida, y la URL lleva el
                # token. Sin `_redactar` aqui, un simple "no hay red" escribe el
                # token del bot en ``alerts.delivery_error`` y en el log, y un
                # token filtrado hay que revocarlo con @BotFather. Lo que
                # `_redactar` solo cubria era el cuerpo de la respuesta.
                ultimo_error = self._redactar(f"Error de red con Telegram: {exc}")
            else:
                cuerpo_respuesta = self._redactar(respuesta.text)
                if respuesta.status_code == 429:
                    # No cuenta como fallo de entrega: es la API pidiendo turno.
                    try:
                        parsed = respuesta.json()
                    except ValueError:
                        parsed = {}
                    ultimo_error = "Telegram respondió 429: límite de mensajes"
                    self._dormir(self._retry_after(parsed, self._retroceso(intento)))
                    continue
                if respuesta.status_code >= 500:
                    # Server error: se reintenta, casi siempre es transitorio.
                    ultimo_error = (
                        f"Telegram respondió {respuesta.status_code}: "
                        f"{cuerpo_respuesta[:200]}"
                    )
                    self._dormir(self._retroceso(intento))
                    continue
                if respuesta.status_code == 200:
                    try:
                        message_id = (
                            respuesta.json().get("result", {}).get("message_id")
                        )
                    except ValueError:
                        message_id = None
                    return TelegramResult(
                        ok=True,
                        skipped=False,
                        message_id=message_id,
                        attempts=intento,
                        error=None,
                        response_body=cuerpo_respuesta,
                    )
                # 4xx que no es 429: sonOur fault, no reintentar. Un 400 por HTML
                # mal formado o un 403 por bot bloqueado reintentar cinco veces
                # solo retrasa el error y multiplica el rate limit.
                ultimo_error = (
                    f"Telegram rechazó el mensaje ({respuesta.status_code}): "
                    f"{cuerpo_respuesta[:300]}"
                )
                return TelegramResult(
                    ok=False,
                    skipped=False,
                    message_id=None,
                    attempts=intento,
                    error=ultimo_error,
                    response_body=cuerpo_respuesta,
                )

            if intento < max_intentos:
                self._dormir(self._retroceso(intento))

        return TelegramResult(
            ok=False,
            skipped=False,
            message_id=None,
            attempts=max_intentos,
            error=ultimo_error,
            response_body=cuerpo_respuesta,
        )

    def verificar(self) -> TelegramResult:
        """Comprueba token y ``chat_id`` sin enviar una alerta.

        Es el endpoint de prueba de la §7, y existe por una razon concreta: la
        causa numero uno de "las alertas no me llegan" es de configuracion, y
        descubrirlo esperando una deteccion real del mercado es esperar horas
        para descubrir un ``/start`` que no se mando. Este metodo dice si el
        canal funciona ahora.
        """
        return self.enviar("Prueba de LaSaTrading: el canal de alertas funciona.")
