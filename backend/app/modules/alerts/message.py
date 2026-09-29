"""El mensaje de Telegram de una alerta.

Un mensaje de aviso se lee en el móvil, de pie, en treinta segundos. Todo lo que
este módulo hace está al servicio de eso, y hay tres decisiones que se notan:

1. **El estado de validación va arriba, con icono, antes que cualquier número.**
   Es lo que el usuario mira primero, y lo que decide si fiarse o no. Va en la
   primera línea, no en un campo que se busca.

2. **El precio de referencia no es el precio de entrada.** La regla de entrada
   del motor es la apertura de `T+1`, que cuando se detecta el patrón no ha
   ocurrido. El mensaje da el cierre de la vela de la señal, lo llama
   *referencia*, y da los niveles en porcentaje con la fórmula para calcularlos.
   Un mensaje con un precio de entrada equivocado es peor que uno que no lo da,
   porque alguien opera sobre él.

3. **El descargo va siempre, incluso en una alerta validada.** Un mensaje que se
   puede reenviar a alguien sin contexto tiene que llevarse su propio contexto.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.modules.alerts.backing import DESCARGO, ICONO, TITULO
from app.modules.alerts.evaluator import Deteccion
from app.modules.alerts.models import AlertPatternCoverage, AlertRule, AlertVerdict
from app.modules.alerts.telegram import escapar

#: La hora va **en UTC y con la zona escrita**, y no en hora local. Un timestamp
#: escrito sin zona se lee como local en el servidor y como UTC en el navegador, y
#: las dos cosas difieren: un aviso que dice "10:00" y llega a las 12:00 de tu
#: reloj parece un bug del detector cuando es un bug del formato.
FORMATO_VELA = "%Y-%m-%d %H:%M UTC"


def _es(valor: float, decimales: int = 2, signo: bool = False) -> str:
    """Número en formato español: coma decimal y punto de millar.

    No es un detalle menor: un mensaje con «1,152.6%» lo lee un español como mil
    ciento cincuenta y dos, seis por ciento, en vez de mil ciento cincuenta y dos
    coma seis. En un aviso que se lee de pie y en el móvil, un separador
    equivocado es un número equivocado.
    """
    if valor is None:
        return "—"
    texto = f"{valor:+,.{decimales}f}" if signo else f"{valor:,.{decimales}f}"
    return texto.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def _numero(valor, decimales: int = 2, sufijo: str = "") -> str:
    if valor is None:
        return "—"
    return f"{_es(float(valor), decimales)}{sufijo}"


def _nivel_etiqueta(valor, unidad: str = "%") -> str:
    if valor is None:
        return "sin nivel"
    return f"{float(valor):g} {unidad}"


def _icono_cobertura(cobertura: str) -> str:
    if cobertura == AlertPatternCoverage.FUERA_DE_FILTRO.value:
        return "⚠️"
    if cobertura == AlertPatternCoverage.SIN_INFORME.value:
        return "ℹ️"
    return "✅"


def mensaje_alerta(
    regla: AlertRule,
    deteccion: Deteccion,
    momento: datetime | None = None,
) -> str:
    """El texto que sale a Telegram, con `parse_mode=HTML`.

    Se construye entero y se devuelve entero, sin trocear aquí: el recorte a 4096
    caracteres es del cliente, que ya sabe el límite, y hacerlo en los dos sitios
    es tener dos cifras que algún día no coinciden.
    """
    ahora = momento or datetime.now(timezone.utc)
    desde_catalogo = _nombre_patron(regla.pattern_name)
    estado = regla.validation_status or AlertVerdict.SIN_EVALUAR.value
    icono = ICONO.get(estado, "⚪")

    lineas: list[str] = [
        f"<b>{icono} {escapar(TITULO.get(estado, 'SEÑAL'))}</b>",
        "",
        f"<b>{escapar(desde_catalogo)}</b>",
        f"dirección: <b>{escapar(regla.direction.upper())}</b>",
        f"{escapar(regla.symbol)} · {escapar(regla.timeframe)}",
        "",
        "<b>La vela</b>",
        f"  hora        {deteccion.timestamp.strftime(FORMATO_VELA)}",
        f"  referencia  {escapar(_numero(deteccion.reference_price, 2))}"
        "  (cierre de esa vela)",
    ]

    # Los niveles absolutos NO van: no se pueden calcular hasta que exista el
    # precio de entrada, que es la apertura de la vela siguiente.
    sl = regla.config.get("stop_loss_pct")
    tp = regla.config.get("take_profit_pct")
    hold = regla.config.get("max_hold")
    lineas += [
        "",
        "<b>Configuración vigilada</b>",
        f"  SL          {escapar(_nivel_etiqueta(sl))}",
        f"  TP          {escapar(_nivel_etiqueta(tp))}",
        f"  máx. velas  {escapar(str(hold) if hold is not None else '—')}",
    ]
    if sl is not None or tp is not None:
        entrada = "el precio de entrada"
        calc = []
        if sl is not None:
            signo = "+" if regla.direction == "bearish" else "−"
            calc.append(f"SL {entrada} {signo} {abs(float(sl)):g}%")
        if tp is not None:
            signo = "−" if regla.direction == "bearish" else "+"
            calc.append(f"TP {entrada} {signo} {abs(float(tp)):g}%")
        lineas.append(
            "  entrada     apertura de la vela siguiente, todavía no ha ocurrido"
        )
        if calc:
            lineas.append("  " + " · ".join(escapar(c) for c in calc))

    lineas += ["", f"<b>{_icono_cobertura(regla.pattern_coverage)} Respaldo</b>"]
    if estado == AlertVerdict.SIN_EVALUAR.value:
        lineas.append("  Sin informe de walk-forward que evaluara esto.")
    else:
        lineas.append(f"  Veredicto   {escapar(estado)}")
        if regla.backing_oi_low is not None and regla.backing_oi_high is not None:
            cruza = float(regla.backing_oi_low) <= 0 <= float(regla.backing_oi_high)
            marca = "incluye el cero" if cruza else "excluye el cero"
            lineas.append(
                f"  IC95%       [{_es(float(regla.backing_oi_low), 1, True)} ; "
                f"{_es(float(regla.backing_oi_high), 1, True)}]%"
                f"  <i>({marca})</i>"
            )
        if regla.backing_oos_return_pct is not None:
            extra = ""
            if regla.backing_market_return_pct is not None:
                extra = f"   Mercado {float(regla.backing_market_return_pct):+,.1f}%"
            ventanas = (
                f"   Ventanas {regla.backing_windows}" if regla.backing_windows else ""
            )
            lineas.append(
                f"  Retorno OOS {_es(float(regla.backing_oos_return_pct), 1, True)}%"
                f"{extra}{ventanas}"
            )
        if regla.validation_note:
            lineas.append(f"  {escapar(regla.validation_note)}")
        if regla.walk_forward_run_id:
            linea = f"  Informe     {str(regla.walk_forward_run_id)[:8]}"
            if regla.candidate_rank:
                linea += f" · candidata nº{regla.candidate_rank}"
            linea += f" · {regla.symbol}"
            lineas.append(escapar(linea))

    if (
        not regla.config.get("base_known", False)
        and estado != AlertVerdict.SIN_EVALUAR.value
    ):
        lineas.append(
            "  <i>Este informe es anterior a que se guardara la comisión, así "
            "que no se sabe con qué costes se simuló.</i>"
        )

    lineas += [
        "",
        f"<i>{escapar(_edad_respaldo(regla, ahora))}</i>",
        "",
        f"<i>{escapar(DESCARGO)}</i>",
    ]
    return "\n".join(lineas)


def _edad_respaldo(regla: AlertRule, ahora: datetime) -> str:
    """La edad de la evidencia, porque un respaldo de hace un año no es el mismo.

    No se esconde la antigüedad: el intervalo de confianza es una afirmación
    sobre un rango concreto, y extenderlo a otro rango sin decirlo sería la
    misma mentira que ya corrigió la 5.5.
    """
    if not regla.backing_created_at:
        return "Sin fecha de respaldo conocida."
    referencia = regla.backing_created_at
    if referencia.tzinfo is None:
        referencia = referencia.replace(tzinfo=timezone.utc)
    dias = max(0, (ahora - referencia).days)
    if dias == 0:
        return "Respaldo de hoy."
    if dias < 31:
        return f"Respaldo de hace {dies_placeholder(dias)}."
    meses = dias // 30
    return (
        f"Respaldo de hace {meses} meses ({dias} días). Los mercados han "
        "cambiado desde entonces."
    )


def dies_placeholder(dias: int) -> str:
    return f"{dias} días" if dias != 1 else "1 día"


def _nombre_patron(codigo: str) -> str:
    """El nombre humano del catálogo, y el código si no se conoce.

    En el mensaje va el nombre porque es lo que el usuario reconoce; el código va
    igual después, porque el patrón se identifica por el código y no por el
    nombre, que un día puede cambiar en la traducción.
    """
    from app.modules.patterns.pattern_catalog import get_definition

    definicion = get_definition(codigo)
    nombre = definicion.name if definicion is not None else codigo
    return f"{nombre} ({codigo})"


def mensaje_prueba() -> str:
    """El mensaje del endpoint de prueba.

    Va con el mismo formato y el mismo tono que los avisos de verdad, para que
    probar el canal **enseñe** cómo se lee una alerta. Un mensaje de prueba con
    otro formato deja al usuario sin saber qué esperar de los reales.
    """
    return (
        "<b>✅ PRUEBA DE CANAL · LaSaTrading</b>\n"
        "\n"
        "Este mensaje sale por el mismo camino que las alertas reales.\n"
        "\n"
        "<b>Si lo estás leyendo</b>, el token y el chat funcionan.\n"
        "\n"
        "<i>Una alerta real llega con un icono de estado (✅ 🟡 🔴 ⚪) y el "
        "veredicto del backtesting arriba del todo. El precio que verás es el "
        "cierre de la vela de la señal, no el de entrada: la entrada es la "
        "apertura de la vela siguiente, que cuando se detecta el patrón todavía "
        "no ha ocurrido.</i>"
    )
