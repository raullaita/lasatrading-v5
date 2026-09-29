"""Tests del cliente de Telegram.

Todo con ``httpx.MockTransport``: ni una llamada de red. Lo que se comprueba
aquí es lo que puede fallar de verdad y es fácil que pase desapercibido:

- Un **429** tiene que respetarse con el ``retry_after`` que dice la API, no con
  un retroceso inventado.
- Un **4xx que no es 429** no se reintenta, porque son errores nuestros y
  reintentar cinco veces solo retrasa el error.
- El **token no puede aparecer** ni en un error ni en un log.
- **Apagado no es silencio**: devuelve ``skipped`` y su motivo, para que el
  servicio pueda escribirlo y la diferencia entre "no se intentó" y "no llegó"
  quede en la base.
- Un mensaje **más largo que el límite** se trunca marcando el corte, porque un
  número cortado a la mitad se lee como otro número.
"""

from __future__ import annotations

import json

import httpx
import pytest
from app.config import Settings
from app.modules.alerts.telegram import (
    TelegramClient,
    TelegramError,
    escapar,
    truncar,
)

TOKEN = "123456:ABC-DEFfake-token-para-los-tests"


def ajustes_de_prueba(**extra) -> Settings:
    """``Settings`` con el canal de Telegram listo y sin tocar el entorno real.

    Se construye una instancia propia en vez de parchear la global, porque
    ``get_settings()`` devuelve un objeto **nuevo** en cada llamada: parchear el
    resultado de la llamada del test no cambia lo que lee el cliente, y el test
    pasaria por un motivo equivocado o fallaria sin entender por que.
    """
    base = dict(
        TELEGRAM_ENABLED=True,
        TELEGRAM_BOT_TOKEN=TOKEN,
        TELEGRAM_CHAT_ID="999888777",
        TELEGRAM_MIN_INTERVAL_SECONDS=0.0,
        TELEGRAM_MAX_ATTEMPTS=3,
        TELEGRAM_MAX_MESSAGE_CHARS=100,
    )
    base.update(extra)
    return Settings(**base)


@pytest.fixture
def telegram():
    """Constructor de clientes con reloj bajo control y configuracion de mentira."""

    def construir(handler, **kwargs) -> TelegramClient:
        # La configuracion sale de `pop` y no de un kwarg fijo: un `**kwargs` que
        # llega despues de un `settings=` explicito es "multiple values for
        # keyword argument", y el test que necesita otra configuracion falla al
        # construirse, que es la peor forma de descubrir que hace falta otra.
        ajustes = kwargs.pop("settings", None) or ajustes_de_prueba()
        return TelegramClient(
            transport=httpx.MockTransport(handler),
            ahora=lambda: 0.0,
            settings=ajustes,
            **kwargs,
        )

    return construir


def _ok(message_id: int = 555) -> httpx.Response:
    return httpx.Response(
        200,
        json={"ok": True, "result": {"message_id": message_id, "text": "enviado"}},
    )


# ---------------------------------------------------------------------------
# El camino feliz
# ---------------------------------------------------------------------------
def test_una_alerta_llegada_devuelve_el_message_id(telegram):
    """El ``message_id`` es lo que prueba que el mensaje existió en Telegram, y es
    lo que se guarda en la auditoría. Sin él, "entregado" es una intención."""
    vistos: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        vistos.append(request)
        return _ok(987654)

    with telegram(handler) as cliente:
        resultado = cliente.enviar("hola")

    assert resultado.ok is True
    assert resultado.skipped is False
    assert resultado.message_id == 987654
    assert resultado.attempts == 1
    assert resultado.error is None
    assert len(vistos) == 1


def test_el_va_al_chat_configurado_con_html(telegram):
    """HTML y no MarkdownV2, y con el prefijo ``/bot<token>/``."""
    cuerpos: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        cuerpos.append(json.loads(request.content))
        return _ok()

    with telegram(handler) as cliente:
        cliente.enviar("texto")

    assert cuerpos[0]["chat_id"] == "999888777"
    assert cuerpos[0]["parse_mode"] == "HTML"
    assert cuerpos[0]["text"] == "texto"


# ---------------------------------------------------------------------------
# El apagado
# ---------------------------------------------------------------------------
def test_apagado_no_envia_y_lo_dice(telegram):
    """``TELEGRAM_ENABLED = false`` no es un silencio: es un resultado con motivo.

    La diferencia importa porque sin ella un servicio de alertas que esta apagado
    es indistinguible de uno que no ha detectado nada, y en un sistema de avisos
    esa confusion es de las caras.
    """
    llamadas: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        llamadas.append(request)
        return _ok()

    apagado = ajustes_de_prueba(TELEGRAM_ENABLED=False)
    with telegram(handler, settings=apagado) as cliente:
        resultado = cliente.enviar("hola")

    assert resultado.ok is False
    assert resultado.skipped is True
    assert resultado.attempts == 0
    assert "apagado" in (resultado.error or "")
    assert llamadas == [], "apagado significa no tocar la red"


# ---------------------------------------------------------------------------
# Configuración ausente
# ---------------------------------------------------------------------------
def test_sin_token_falla_con_mensaje_util(telegram):
    """Sin token, el error dice como obtenerlo. Un 404 de la API con el cuerpo
    de Telegram no le dice a nadie nada."""
    vacio = ajustes_de_prueba(TELEGRAM_BOT_TOKEN="")
    with (
        TelegramClient(
            transport=httpx.MockTransport(lambda r: _ok()), settings=vacio
        ) as cliente,
        pytest.raises(TelegramError) as exc,
    ):
        cliente.enviar("hola")

    assert "@BotFather" in str(exc.value)


def test_sin_chat_id_explica_el_start(telegram):
    """La causa número uno de "las alertas no me llegan" es no haber mandado
    ``/start`` al bot, y el error tiene que decirlo."""
    vacio = ajustes_de_prueba(TELEGRAM_CHAT_ID="")
    with (
        TelegramClient(
            transport=httpx.MockTransport(lambda r: _ok()), settings=vacio
        ) as cliente,
        pytest.raises(TelegramError) as exc,
    ):
        cliente.enviar("hola")

    mensaje = str(exc.value)
    assert "/start" in mensaje
    assert "getUpdates" in mensaje


# ---------------------------------------------------------------------------
# Reintentos
# ---------------------------------------------------------------------------
def test_un_429_se_espera_el_retry_after_de_la_api(telegram):
    """El ``retry_after`` de Telegram dice cuántos segundos esperar, y es más
    fiable que cualquier retroceso propio. Ignorarlo y reintentar antes de
    tiempo devuelve 429 otra vez, y así hasta agotar los intentos."""
    esperas: list[float] = []
    llamadas = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        llamadas["n"] += 1
        if llamadas["n"] == 1:
            return httpx.Response(
                429,
                json={
                    "ok": False,
                    "error_code": 429,
                    "description": "Too Many Requests: retry after 12",
                    "parameters": {"retry_after": 12},
                },
            )
        return _ok(2468)

    with telegram(handler, dormir=lambda s: esperas.append(s)) as cliente:
        resultado = cliente.enviar("hola")

    assert resultado.ok is True
    assert resultado.message_id == 2468
    assert resultado.attempts == 2
    assert 12.0 in esperas, "se esperaba 12 s porque la API lo pidió, no 1 s"


def test_un_500_se_reintenta(telegram):
    """Server error: casi siempre transitorio, y no avisar por eso sería peor."""
    llamadas = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        llamadas["n"] += 1
        if llamadas["n"] < 3:
            return httpx.Response(503, text="service unavailable")
        return _ok()

    with telegram(handler, dormir=lambda s: None) as cliente:
        resultado = cliente.enviar("hola")

    assert resultado.ok is True
    assert resultado.attempts == 3


def test_un_4xx_que_no_es_429_no_se_reintenta(telegram):
    """Un 400 por HTML mal formado o un 403 por bot bloqueado son errores
    **nuestros**, y reintentar cinco veces solo retrasa el error y multiplica el
    rate limit."""
    llamadas = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        llamadas["n"] += 1
        return httpx.Response(403, json={"ok": False, "description": "bot blocked"})

    with telegram(handler, dormir=lambda s: None) as cliente:
        resultado = cliente.enviar("hola")

    assert resultado.ok is False
    assert resultado.attempts == 1
    assert llamadas["n"] == 1, "un 403 no se reintenta"
    assert "403" in (resultado.error or "")


def test_un_timeout_reintenta_y_al_final_falla(telegram):
    """Agotar los intentos devuelve un resultado fallido, nunca una excepción sin
    contexto: el servicio tiene que poder escribir la alerta y su error."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("no hay red")

    with telegram(handler, dormir=lambda s: None) as cliente:
        resultado = cliente.enviar("hola")

    assert resultado.ok is False
    assert resultado.skipped is False
    assert resultado.attempts == 3
    assert "red" in (resultado.error or "").lower() or "Timeout" in (
        resultado.error or ""
    )


# ---------------------------------------------------------------------------
# El token no se filtra
# ---------------------------------------------------------------------------
def test_el_token_no_aparece_en_el_error(telegram):
    """La URL de Telegram lleva el token, así que un error de red que la
    incluya lo escribiría en el log y en la base. Se redacta."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"no se pudo conectar con {request.url}")

    with telegram(handler, dormir=lambda s: None) as cliente:
        resultado = cliente.enviar("hola")

    assert TOKEN not in (resultado.error or "")
    assert TOKEN not in (resultado.response_body or "")
    assert "bot<token>" in (resultado.error or "")


def test_el_token_no_aparece_en_el_cuerpo_auditado(telegram):
    """El cuerpo que se guarda en ``alert_deliveries`` tampoco, por si Telegram
    lo devolviera en algún error."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=f"ok {request.url} {TOKEN}")

    with telegram(handler) as cliente:
        resultado = cliente.enviar("hola")

    assert TOKEN not in (resultado.response_body or "")


# ---------------------------------------------------------------------------
# Formato del mensaje
# ---------------------------------------------------------------------------
def test_escapar_solo_toca_los_tres_caracteres_de_html():
    """Si ``escapar`` tocara mas, los decimales de los precios saldrian con
    entidades y el mensaje seria ilegible en un movil."""
    assert escapar("SL 1.5% · TP 2.0%") == "SL 1.5% · TP 2.0%"
    assert escapar("a < b > c & d") == "a &lt; b &gt; c &amp; d"


def test_truncar_marca_el_corte():
    """El ``…`` del final no es cosmético: sin él, un número cortado se lee como
    otro número."""
    largo = "linea\n" * 100
    corto = truncar(largo, 100)

    assert len(corto) <= 100
    assert corto.endswith("…")


def test_truncar_no_toca_lo_que_cabe():
    assert truncar("corto", 100) == "corto"


def test_un_mensaje_largo_llega_truncado_a_telegram(telegram):
    """El recorte se hace **antes** de enviar, no se deja que Telegram corte por
    su cuenta: su corte cae donde cae y no avisa."""
    cuerpos: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        cuerpos.append(json.loads(request.content))
        return _ok()

    with telegram(handler) as cliente:
        cliente.enviar("x" * 500)

    assert len(cuerpos[0]["text"]) <= 100
    assert cuerpos[0]["text"].endswith("…")


# ---------------------------------------------------------------------------
# El ritmo
# ---------------------------------------------------------------------------
def test_se_respeta_el_intervalo_entre_mensajes():
    """Telegram admite 1 mensaje por segundo y por chat. Pasarse devuelve 429, y
    descubrirlo en producción con la primera alerta de un lote es pagarlo con el
    aviso más importante."""
    ajustes = ajustes_de_prueba(TELEGRAM_MIN_INTERVAL_SECONDS=1.0)

    esperas: list[float] = []
    reloj = {"t": 0.0}

    def ahora() -> float:
        return reloj["t"]

    def dormir(segundos: float) -> None:
        esperas.append(segundos)
        reloj["t"] += segundos

    cliente = TelegramClient(
        transport=httpx.MockTransport(lambda r: _ok()),
        ahora=ahora,
        dormir=dormir,
        settings=ajustes,
    )
    with cliente:
        cliente.enviar("uno")
        cliente.enviar("dos")
        cliente.enviar("tres")

    assert len(esperas) == 2, "dos esperas entre tres mensajes, no tres"
    assert all(s == 1.0 for s in esperas)


# ---------------------------------------------------------------------------
# La prueba de canal
# ---------------------------------------------------------------------------
def test_verificar_envia_un_mensaje_de_prueba(telegram):
    """El endpoint de prueba existe por una razón concreta: la causa número uno
    de "las alertas no me llegan" es de configuración, y descubrirlo esperando
    una detección real del mercado es esperar horas para descubrir un ``/start``
    que no se mandó."""
    cuerpos: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        cuerpos.append(json.loads(request.content))
        return _ok(4242)

    with telegram(handler) as cliente:
        resultado = cliente.verificar()

    assert resultado.ok is True
    assert resultado.message_id == 4242
    assert "funciona" in cuerpos[0]["text"]
