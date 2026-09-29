"""La evidencia de una regla: que se sabe de ella, y que no.

Este módulo **no rechaza** reglas. Decide, y escribe.

## Del rechazo al aviso: por qué cambió

La primera versión rechazaba la creación con un 409 cuando el veredicto era
`descartada` o cuando el informe no había evaluado ese patrón. La postura era
correcta en la teoría —una alerta debe apoyarse en algo— y **equivocada en la
práctica**: con 389 días de datos, un walk-forward rara vez da `sostenida` con
una rejilla grande, así que el sistema habría sido inservible. Y la reacción
natural de un usuario con una herramienta inservible no es entender el motivo, es
buscar la manera de saltarse el filtro.

Ahora la regla nace siempre, y lo que cambia es que el estado es **imposible de
no ver**:

- El veredicto va en el mensaje de Telegram con su icono, no en un enlace.
- `pattern_coverage` avisa **por separado** de que la configuración no se probó
  con ese patrón, porque es una pregunta distinta del veredicto y es la que más
  se confunde con él.
- `validation_note` lo compone el código, no quien crea la regla.

La herramienta informa y el usuario decide. Eso es más defendible que un
bloqueo, y además es lo que el usuario pidió con sus palabras: «le damos la
información, no le impedimos actuar».

## Lo que sigue igual

Dos cosas no se mueven, y conviene decir por qué:

- **`symbol` y `timeframe` no se piden.** Se toman del escaneo que respaldó el
  informe. Admitirlos permitiría vigilar BTCUSDT con el respaldo de un informe
  de ETHUSDT, que es un aviso con la evidencia de otro mercado.
- **Los niveles no se piden.** La configuración se copia del informe. Si el
  endpoint los admitiera, podría decir «respaldada por el informe 3a9c1f2e» y
  guardar otros: el aviso llevaría las credenciales de un experimento y los
  números de otro.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.alerts.models import (
    AlertPatternCoverage,
    AlertRule,
    AlertVerdict,
)
from app.modules.backtesting.models import (
    WalkForwardCandidate,
    WalkForwardRun,
    WalkForwardRunStatus,
)
from app.modules.patterns.models import PatternScanJob

#: El descargo del mensaje. Vive aqui y no en la peticion por el mismo motivo que
#: `validation_note`: si lo escribiera quien crea la regla, podría decir que es
#: una recomendación de compra, y el modulo entero habria descargado su contrato
#: en una columna.
DESCARGO = (
    "No es una recomendación. Es una configuración que, sobre datos que ya "
    "viste, rindió esto. El intervalo no dice qué va a pasar mañana."
)

#: Iconos del mensaje. El estado tiene que distinguirse **de un vistazo** en la
#: pantalla del móvil, antes de que el usuario lea una sola palabra.
ICONO = {
    AlertVerdict.SOSTENIDA.value: "✅",
    AlertVerdict.PROMETEDORA.value: "🟡",
    AlertVerdict.DESCARTADA.value: "🔴",
    AlertVerdict.SIN_EVALUAR.value: "⚪",
}

TITULO = {
    AlertVerdict.SOSTENIDA.value: "OPERACIÓN CANDIDATA · CONFIGURACIÓN VALIDADA",
    AlertVerdict.PROMETEDORA.value: "OPERACIÓN CANDIDATA · SIN EVIDENCIA FUERTE",
    AlertVerdict.DESCARTADA.value: "SEÑAL · ESTA CONFIGURACIÓN DESCARTÓ",
    AlertVerdict.SIN_EVALUAR.value: "SEÑAL · SIN RESPALDO DE BACKTESTING",
}


class RespaldoNoAceptable(Exception):
    """Solo para lo que sigue siendo un error de verdad.

    Con el enfoque de avisar, casi nada es un error: un veredicto `descartada` o
    un patrón sin cobertura crean la regla con su etiqueta. Lo que queda aquí es
    lo que **no** se puede permitir ni avisando:

    - una dirección que contradice al catálogo (el aviso iría al revés),
    - un patrón que no existe,
    - un nombre vacío.
    """


@dataclass(frozen=True, slots=True)
class Respaldo:
    """Lo que se sabe de una regla, y con qué nivel de confianza."""

    status: str
    note: str
    coverage: str
    config: dict[str, Any]
    ci95: tuple[float, float] | None
    oos_return_pct: float | None
    market_return_pct: float | None
    windows: int | None
    candidate_rank: int | None
    walk_forward_run_id: uuid.UUID | None
    scan_job_id: uuid.UUID | None
    symbol: str | None
    timeframe: str | None

    @property
    def validada(self) -> bool:
        return self.status in (
            AlertVerdict.SOSTENIDA.value,
            AlertVerdict.PROMETEDORA.value,
        )

    @property
    def icono(self) -> str:
        return ICONO.get(self.status, "⚪")


SIN_RESPALDO = Respaldo(
    status=AlertVerdict.SIN_EVALUAR.value,
    note=(
        "Ningún backtest ha evaluado esta configuración. Es una intuición, no "
        "un resultado."
    ),
    coverage=AlertPatternCoverage.SIN_INFORME.value,
    config={"base_known": False},
    ci95=None,
    oos_return_pct=None,
    market_return_pct=None,
    windows=None,
    candidate_rank=None,
    walk_forward_run_id=None,
    scan_job_id=None,
    symbol=None,
    timeframe=None,
)


def _patrones_del_escaneo(scan: PatternScanJob) -> set[str] | None:
    """Los patrones que el escaneo calculó, o ``None`` si calculó todos.

    ``None`` significa «sin filtro» e incluye cualquier patrón. Un conjunto
    vacío se trata como filtro explícito vacío, que no puede respaldar nada: si
    un escaneo no calculó nada, no hay evidencia de nada.
    """
    seleccion = scan.patterns_config or []
    if not seleccion:
        return None
    codigos = {
        item.get("code") if isinstance(item, dict) else getattr(item, "code", None)
        for item in seleccion
    }
    return {c for c in codigos if c}


def _direccion_de_catalogo(codigo: str) -> str | None:
    """La dirección que el catálogo declara, o ``None`` si no conoce el patrón.

    Se consulta en caliente y no se copia a la regla: el catálogo puede crecer y
    corregir una dirección, y una regla que guardara el valor de hoy vigilando el
    código de mañana hereda el error sin avisar.
    """
    from app.modules.patterns.pattern_catalog import PATTERN_CATALOG

    definicion = PATTERN_CATALOG.get(codigo)
    return definicion.direction if definicion is not None else None


def comprobar_direccion(patron: str, direccion: str) -> None:
    """Sigue siendo un error, no un aviso.

    Un endpoint que acepta la dirección que le manden permite crear la alerta
    opuesta a lo que el patrón significa, con el mensaje al revés. Esto no es una
    cuestión de confianza en el usuario: es que la dirección **significa** algo
    y el significado no lo elige quien llama.
    """
    from app.modules.patterns.pattern_catalog import PATTERN_CATALOG

    if patron not in PATTERN_CATALOG:
        raise RespaldoNoAceptable(
            f"'{patron}' no es un patrón del catálogo. Sin él no se puede ni "
            "vigilar ni avisar."
        )
    declarada = _direccion_de_catalogo(patron)
    if declarada is not None and declarada != direccion:
        raise RespaldoNoAceptable(
            f"{patron} es un patrón {declarada}, no {direccion}. La dirección la "
            "declara el catálogo, no la petición."
        )


def _nota_de_veredicto(candidata: WalkForwardCandidate) -> str:
    """La frase que va al mensaje, escrita con el motivo del propio informe.

    Los ``rejections`` de la candidata son la explicación de por qué el
    optimizador la descartó, y repetirlos aquí evita que el usuario tenga que ir
    a buscar el informe para entender la línea roja de su móvil.
    """
    if candidata.verdict == AlertVerdict.SOSTENIDA.value:
        return (
            "El intervalo de confianza excluye el cero y se evaluó en tres "
            "regímenes o más."
        )
    if candidata.verdict == AlertVerdict.PROMETEDORA.value:
        return (
            "Pasa las guardas, pero el intervalo incluye el cero: el resultado "
            "es compatible con haber sido azar."
        )
    motivos = "; ".join(candidata.rejections) or "sin detalle"
    return f"El optimizador la descartó: {motivos}."


def _nota_de_cobertura(cubierto: bool, patron: str, evaluados: set[str] | None) -> str:
    if cubierto:
        return ""
    if evaluados is None:
        return ""
    return (
        f"Atención: el informe de respaldo no evaluó {patron} "
        f"(solo {[sorted(evaluados)]}), así que estos niveles nunca se simularon "
        "con ese patrón."
    )


def _config_de_la_candidata(
    candidata: WalkForwardCandidate, run: WalkForwardRun
) -> dict[str, Any]:
    """La configuración, copiada del informe.

    Los tres niveles optimizados salen de la fila de la candidata. El resto sale de
    la estrategia base que el run congeló en su `config`.

    Si el run **no** tiene `base_strategy` —los anteriores a que se persistiera—
    se marca `base_known = False` en vez de rellenarlo con los defaults de hoy.
    Rellenarlo sería la trampa más difícil de detectar del módulo: el aviso
    diría «4 bps de comisión» para un experimento que se corrió con otra cosa, y
    no habría forma de notarlo.
    """
    config: dict[str, Any] = {
        "take_profit_pct": (
            float(candidata.take_profit_pct)
            if candidata.take_profit_pct is not None
            else None
        ),
        "stop_loss_pct": (
            float(candidata.stop_loss_pct)
            if candidata.stop_loss_pct is not None
            else None
        ),
        "max_hold": int(candidata.max_hold),
    }
    base = (run.config or {}).get("base_strategy") or {}
    if base:
        for campo in (
            "fee_bps",
            "use_fraction",
            "allow_short",
            "entry_offset",
            "initial_capital",
        ):
            if campo in base:
                config[campo] = base[campo]
        config["base_known"] = True
    else:
        config["base_known"] = False
    return config


def resolver_respaldo(
    db: Session,
    walk_forward_run_id: uuid.UUID | None,
    candidate_rank: int | None,
    patron: str,
    direccion: str,
) -> Respaldo:
    """Reúne lo que se sabe de la regla. **Nunca lanza por un veredicto.**

    Devuelve `SIN_RESPALDO` si no hay informe, y una etiqueta concreta si lo hay
    pero su veredicto es `descartada` o su filtro no incluía el patrón. El
    llamante crea la regla igual: la diferencia entre un estado y otro tiene que
    verse en el mensaje, no impedir la existencia del aviso.
    """
    if walk_forward_run_id is None or candidate_rank is None:
        return SIN_RESPALDO

    run = db.get(WalkForwardRun, walk_forward_run_id)
    if run is None or run.status != WalkForwardRunStatus.COMPLETED.value:
        return SIN_RESPALDO

    candidata = db.scalars(
        select(WalkForwardCandidate).where(
            WalkForwardCandidate.run_id == run.id,
            WalkForwardCandidate.rank == candidate_rank,
        )
    ).first()
    if candidata is None:
        return SIN_RESPALDO

    scan = db.get(PatternScanJob, run.scan_job_id)
    evaluados = _patrones_del_escaneo(scan) if scan is not None else None
    if evaluados is None:
        # Escaneo sin filtro o escaneo que ya no existe. En el primer caso
        # cualquier patrón está cubierto; en el segundo no se puede afirmar nada
        # y se trata como no cubierto, que es lo prudente.
        if scan is None:
            cobertura = AlertPatternCoverage.SIN_INFORME.value
            nota_cobertura = "El escaneo del informe ya no existe."
        else:
            cobertura = AlertPatternCoverage.CUBIERTO.value
            nota_cobertura = ""
    elif patron in evaluados:
        cobertura = AlertPatternCoverage.CUBIERTO.value
        nota_cobertura = ""
    else:
        cobertura = AlertPatternCoverage.FUERA_DE_FILTRO.value
        nota_cobertura = _nota_de_cobertura(False, patron, evaluados)

    nota = _nota_de_veredicto(candidata)
    if nota_cobertura:
        nota = f"{nota} {nota_cobertura}" if nota else nota_cobertura

    return Respaldo(
        status=candidata.verdict,
        note=nota,
        coverage=cobertura,
        config=_config_de_la_candidata(candidata, run),
        ci95=(
            (float(candidata.ci95_low), float(candidata.ci95_high))
            if candidata.ci95_low is not None and candidata.ci95_high is not None
            else None
        ),
        oos_return_pct=(
            float(candidata.oos_return_pct)
            if candidata.oos_return_pct is not None
            else None
        ),
        market_return_pct=(
            float(candidata.market_return_pct)
            if candidata.market_return_pct is not None
            else None
        ),
        windows=int(candidata.windows),
        candidate_rank=int(candidata.rank),
        walk_forward_run_id=run.id,
        scan_job_id=run.scan_job_id,
        symbol=scan.symbol if scan is not None else None,
        timeframe=scan.timeframe if scan is not None else None,
    )


def crear_regla(
    db: Session,
    *,
    name: str,
    patron: str,
    direccion: str,
    symbol: str | None = None,
    timeframe: str | None = None,
    walk_forward_run_id: uuid.UUID | None = None,
    candidate_rank: int | None = None,
    cooldown_minutes: int = 60,
    canal: str = "telegram",
) -> AlertRule:
    """Crea la regla con su estado visible, o falla con el motivo.

    ``symbol`` y ``timeframe`` son opcionales **solo** para el caso `sin_evaluar`,
    donde no hay escaneo de donde sacarlos. Si hay informe, se toman de su
    escaneo y lo que venga en la petición se ignora: admitir un símbolo con un
    informe de otro sería un aviso con la evidencia de otro mercado.
    """
    if not name.strip():
        raise RespaldoNoAceptable("La regla necesita un nombre.")
    if cooldown_minutes < 0:
        raise RespaldoNoAceptable("El enfriamiento no puede ser negativo.")
    comprobar_direccion(patron, direccion)

    evidencia = resolver_respaldo(
        db, walk_forward_run_id, candidate_rank, patron, direccion
    )

    if evidencia.symbol and evidencia.timeframe:
        simbolo, marco = evidencia.symbol, evidencia.timeframe
    elif symbol and timeframe:
        simbolo, marco = symbol, timeframe
    else:
        raise RespaldoNoAceptable(
            "Sin informe de respaldo hay que indicar símbolo y timeframe: no "
            "hay escaneo del que deducirlos."
        )

    regla = AlertRule(
        name=name.strip(),
        symbol=simbolo,
        timeframe=marco,
        pattern_name=patron,
        direction=direccion,
        config=evidencia.config,
        backtest_run_id=None,
        walk_forward_run_id=evidencia.walk_forward_run_id,
        candidate_rank=evidencia.candidate_rank,
        validation_status=evidencia.status,
        validation_note=evidencia.note,
        pattern_coverage=evidencia.coverage,
        backing_created_at=datetime.now(timezone.utc),
        backing_oi_low=(Decimal(str(evidencia.ci95[0])) if evidencia.ci95 else None),
        backing_oi_high=(Decimal(str(evidencia.ci95[1])) if evidencia.ci95 else None),
        backing_oos_return_pct=(
            Decimal(str(evidencia.oos_return_pct))
            if evidencia.oos_return_pct is not None
            else None
        ),
        backing_market_return_pct=(
            Decimal(str(evidencia.market_return_pct))
            if evidencia.market_return_pct is not None
            else None
        ),
        backing_windows=evidencia.windows,
        channel=canal,
        cooldown_minutes=cooldown_minutes,
    )
    # Se anade y se vacia el búfer, pero **no** se confirma: el commit es del
    # servicio, que puede querer escribir el log en la misma transaccion. Sin el
    # flush la regla existe en memoria con el `id` a None y el llamante se lleva
    # un objeto que no esta en la base.
    db.add(regla)
    db.flush()
    return regla
