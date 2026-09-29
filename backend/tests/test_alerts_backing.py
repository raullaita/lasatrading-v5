"""Tests de la regla «una alerta solo nace de un respaldo aceptado».

Estos tests son **la** barrera que impide que el sistema de alertas distribute
señales que el optimizador ya demostró que pierden, así que se prueban las cuatro
condiciones por separado y no solo el camino feliz.

La cuarta —que el respaldo evaluara ese patrón— es la que más daño hace cuando
falta, y la que más fácil es olvidar: un walk-forward sobre un escaneo filtrado
a un patrón solo valida **ese** patrón, y una regla de otro está prometiendo una
validación que no existe.

La quinta condición, que no está en el módulo pero debería estarlo en algún
sitio, se comprueba aquí: el descargo del mensaje no lo escribe el cliente.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from app.modules.alerts.backing import (
    DESCARGO,
    ICONO,
    TITULO,
    RespaldoNoAceptable,
    crear_regla,
)
from app.modules.alerts.models import AlertPatternCoverage, AlertRule, AlertVerdict
from app.modules.backtesting.models import (
    WalkForwardCandidate,
    WalkForwardRun,
    WalkForwardRunStatus,
)
from app.modules.patterns.models import (
    PatternScanJob,
    PatternScanJobStatus,
)

pytestmark = pytest.mark.usefixtures("db")


def _scan(db, *, patrones: list[dict] | None = None) -> PatternScanJob:
    job = PatternScanJob(
        symbol="TESTUSDT",
        timeframe="1h",
        date_from=datetime(2022, 1, 1, tzinfo=timezone.utc),
        date_to=datetime(2022, 6, 30, tzinfo=timezone.utc),
        status=PatternScanJobStatus.COMPLETED.value,
        total_candles=4344,
        processed_candles=4344,
        patterns_config=patrones or [],
    )
    db.add(job)
    db.flush()
    return job


def _informe(db, scan, *, veredicto="prometedora", rank=1) -> tuple:
    """Un informe con una candidata, sin pasar por el motor.

    Se construye a mano porque lo que se prueba es la **puerta**, y el motor ya
    tiene 70 tests suyos. Un informe real aquí sería más lento y probaría el
    motor otra vez.
    """
    run = WalkForwardRun(
        scan_job_id=scan.id,
        status=WalkForwardRunStatus.COMPLETED.value,
        config={
            "window_days": 45,
            "oos_days": 15,
            "step_days": 15,
            "symbol": scan.symbol,
            "timeframe": scan.timeframe,
            "base_strategy": {
                "fee_bps": 4.0,
                "use_fraction": 1.0,
                "allow_short": True,
                "entry_offset": 1,
                "initial_capital": 1000.0,
            },
        },
        grid={"combinations": 18},
        simulations=162,
        windows=9,
    )
    db.add(run)
    db.flush()
    reasons = ["sin operaciones suficientes"] if veredicto == "descartada" else []
    candidata = WalkForwardCandidate(
        run_id=run.id,
        rank=rank,
        take_profit_pct=None,
        stop_loss_pct=1.5,
        max_hold=24,
        windows=9,
        trades=180,
        beats_market_windows=6,
        profitable_windows=6,
        oos_return_pct=48.07,
        market_return_pct=-12.4,
        win_rate_mean=0.52,
        sharpe_mean=1.31,
        sharpe_dispersion=0.44,
        max_drawdown_worst=11.2,
        consistency=0.66,
        score=41.8,
        verdict=veredicto,
        ci95_low=1.7 if veredicto != "descartada" else None,
        ci95_high=173.3 if veredicto != "descartada" else None,
        rejections=reasons,
        notes=[],
    )
    db.add(candidata)
    db.commit()
    return run, candidata


# ---------------------------------------------------------------------------
# El enfoque: avisar, no rechazar
# ---------------------------------------------------------------------------
def test_sin_informe_nace_la_regla_sin_evaluar(db):
    """El caso por defecto de la V1: no hay informe y la regla existe.

    Es el estado mas frecuente al principio, y el mas honesto de todos: no dice
    nada, y dice que no dice nada. Un `NULL` ahi seria un caso especial en la
    columna que decide si el aviso lleva candil verde o rojo.
    """
    regla = crear_regla(
        db,
        name="intuición",
        patron="MACD_CROSS_BULLISH",
        direccion="bullish",
        symbol="TESTUSDT",
        timeframe="1h",
    )
    db.commit()

    assert regla.validation_status == AlertVerdict.SIN_EVALUAR.value
    assert regla.pattern_coverage == AlertPatternCoverage.SIN_INFORME.value
    assert "intuición" in regla.validation_note
    assert ICONO[regla.validation_status] == "⚪"


def test_un_informe_inexistente_no_impide_crear_la_regla(db):
    """Un informe borrado deja la regla en `sin_evaluar`, no impide crearla.

    Es lo coherente con `SET NULL`: la evidencia es lo que se puede perder, no el
    deseo de vigilar el patron.
    """
    regla = crear_regla(
        db,
        name="informe borrado",
        patron="MACD_CROSS_BULLISH",
        direccion="bullish",
        walk_forward_run_id=uuid.uuid4(),
        candidate_rank=1,
        symbol="TESTUSDT",
        timeframe="1h",
    )
    db.commit()
    assert regla.validation_status == AlertVerdict.SIN_EVALUAR.value
    assert regla.id is not None


def test_un_informe_en_curso_no_impide_crear_la_regla(db):
    scan = _scan(db)
    run, _ = _informe(db, scan)
    run.status = WalkForwardRunStatus.PROCESSING.value
    db.commit()

    regla = crear_regla(
        db,
        name="en curso",
        patron="MACD_CROSS_BULLISH",
        direccion="bullish",
        walk_forward_run_id=run.id,
        candidate_rank=1,
        symbol="TESTUSDT",
        timeframe="1h",
    )
    assert regla.validation_status == AlertVerdict.SIN_EVALUAR.value
    assert regla.walk_forward_run_id is None, (
        "un informe sin veredicto no se guarda como respaldo: se guardaria y "
        "diría que hay evidencia donde no la hay"
    )


def test_una_descartada_nace_la_regla_con_el_motivo_del_informe(db):
    """El cambio de enfoque, en su caso central.

    Antes esto era un 409. Ahora la regla existe, y el motivo por el que el
    optimizador la descartó va **dentro** del mensaje. Es la diferencia entre
    tapar una puerta y dejar el cartel con el motivo escrito al lado.
    """
    scan = _scan(db)
    run, _ = _informe(db, scan, veredicto="descartada")

    regla = crear_regla(
        db,
        name="descartada pero vigilada",
        patron="MACD_CROSS_BULLISH",
        direccion="bullish",
        walk_forward_run_id=run.id,
        candidate_rank=1,
    )
    db.commit()

    assert regla.validation_status == AlertVerdict.DESCARTADA.value
    assert "sin operaciones suficientes" in regla.validation_note, (
        "el motivo es el del informe, no uno genérico"
    )
    assert ICONO[regla.validation_status] == "🔴"
    assert "DESCARTÓ" in TITULO[regla.validation_status]


def test_un_patron_fuera_del_filtro_avisa_pero_no_impide(db):
    """La cobertura va **aparte** del veredicto y no bloquea.

    Es la información más importante del módulo y la que se confunde con el
    veredicto: un informe puede dar `sostenida` sobre cuatro patrones y no haber
    mirado jamás el de esta regla. Se crea la regla y se dice, porque quien
    decide necesita el dato, no un muro.
    """
    scan = _scan(db, patrones=[{"code": "RSI_EXIT_OVERSOLD", "params": {}}])
    run, _ = _informe(db, scan, veredicto="sostenida")

    regla = crear_regla(
        db,
        name="fuera de filtro",
        patron="MACD_CROSS_BULLISH",
        direccion="bullish",
        walk_forward_run_id=run.id,
        candidate_rank=1,
    )
    db.commit()

    assert regla.validation_status == AlertVerdict.SOSTENIDA.value
    assert regla.pattern_coverage == AlertPatternCoverage.FUERA_DE_FILTRO.value
    assert "nunca se simularon" in regla.validation_note
    assert "RSI_EXIT_OVERSOLD" in regla.validation_note, (
        "el aviso tiene que decir qué patrones sí se simularon, no solo que este no"
    )


def test_un_patron_dentro_del_filtro_no_avisa_de_cobertura(db):
    scan = _scan(db, patrones=[{"code": "RSI_EXIT_OVERSOLD", "params": {}}])
    run, _ = _informe(db, scan, veredicto="sostenida")

    regla = crear_regla(
        db,
        name="dentro",
        patron="RSI_EXIT_OVERSOLD",
        direccion="bullish",
        walk_forward_run_id=run.id,
        candidate_rank=1,
    )
    assert regla.pattern_coverage == AlertPatternCoverage.CUBIERTO.value
    assert "nunca se simularon" not in regla.validation_note


def test_un_escaneo_sin_filtro_cubre_todo(db):
    scan = _scan(db, patrones=[])
    run, _ = _informe(db, scan, veredicto="sostenida")

    regla = crear_regla(
        db,
        name="completo",
        patron="MACD_CROSS_BULLISH",
        direccion="bullish",
        walk_forward_run_id=run.id,
        candidate_rank=1,
    )
    assert regla.pattern_coverage == AlertPatternCoverage.CUBIERTO.value


def test_cada_estado_tiene_icono_y_titulo_propio():
    """La distinción tiene que sobrevivir a una pantalla de móvil leída de un
    vistazo. Un aviso cuyo estado se distinguiera solo por el texto obligaría a
    leerlo entero para decidir si fiarse."""
    assert len(set(ICONO.values())) == len(ICONO), "dos estados con el mismo icono"
    assert len(set(TITULO.values())) == len(TITULO), "dos estados con el mismo título"
    assert ICONO[AlertVerdict.SOSTENIDA.value] == "✅"
    assert ICONO[AlertVerdict.SIN_EVALUAR.value] == "⚪"


# ---------------------------------------------------------------------------
# Lo que sigue siendo un error, no un aviso
# ---------------------------------------------------------------------------
def test_la_direccion_no_puede_contradecir_al_catalogo(db):
    """Sigue siendo un 409, no una etiqueta.

    Un endpoint que acepta la dirección que le manden permite crear la alerta
    opuesta a lo que el patrón significa, con el mensaje al revés. No es una
    cuestión de confianza en el usuario: la dirección **significa** algo.
    """
    scan = _scan(db)
    run, _ = _informe(db, scan)

    with pytest.raises(RespaldoNoAceptable) as exc:
        crear_regla(
            db,
            name="dirección invertida",
            patron="MACD_CROSS_BULLISH",
            direccion="bearish",
            walk_forward_run_id=run.id,
            candidate_rank=1,
        )
    assert "bullish" in str(exc.value)


def test_un_patron_inexistente_se_rechaza(db):
    """Un código que no está en el catálogo no se puede vigilar: no hay scanner,
    no hay dirección declarada y no hay a qué comparar nada."""
    with pytest.raises(RespaldoNoAceptable) as exc:
        crear_regla(
            db,
            name="inventado",
            patron="NO_EXISTE_NADA",
            direccion="bullish",
            symbol="TESTUSDT",
            timeframe="1h",
        )
    assert "catálogo" in str(exc.value)


def test_sin_informe_hacen_falta_simbolo_y_timeframe(db):
    """Sin informe no hay escaneo de donde deducirlos, y adivinar el símbolo en
    una alerta sería avisar del mercado que saliera."""
    with pytest.raises(RespaldoNoAceptable) as exc:
        crear_regla(
            db,
            name="sin nada",
            patron="MACD_CROSS_BULLISH",
            direccion="bullish",
        )
    assert "símbolo" in str(exc.value)


def test_la_api_no_acepta_niveles_para_la_regla(db):
    """La condición 4, comprobada por lo que la función **acepta** y no por lo
    que hace.

    Si el endpoint admitiera `take_profit_pct` y `stop_loss_pct`, podría decir
    «respaldada por el informe 3a9c1f2e» y guardar otros: el aviso llevaría las
    credenciales de un experimento y los números de otro. La garantía no es que el
    servicio los ignore, es que **no hay por dónde pasarlos**.
    """
    import inspect

    parametros = set(inspect.signature(crear_regla).parameters)
    for prohibido in (
        "take_profit_pct",
        "stop_loss_pct",
        "max_hold",
        "config",
        "validation_status",
        "validation_note",
        "backing_oi_low",
    ):
        assert prohibido not in parametros, (
            f"crear_regla acepta {prohibido}: quien llame podría suplantar el "
            "respaldo con números propios"
        )

    scan = _scan(db)
    run, _ = _informe(db, scan)
    regla = crear_regla(
        db,
        name="firmada",
        patron="MACD_CROSS_BULLISH",
        direccion="bullish",
        walk_forward_run_id=run.id,
        candidate_rank=1,
    )
    assert regla.config["stop_loss_pct"] == 1.5
    assert regla.config["max_hold"] == 24


def test_el_simbolo_con_informe_no_viene_de_la_peticion(db):
    """Vigilar BTCUSDT con el respaldo de un informe de otro mercado es un aviso
    con la evidencia de otro. Con informe, manda el escaneo."""
    import inspect

    scan = _scan(db)
    run, _ = _informe(db, scan)
    regla = crear_regla(
        db,
        name="del escaneo",
        patron="MACD_CROSS_BULLISH",
        direccion="bullish",
        symbol="OTROUSDT",
        timeframe="4h",
        walk_forward_run_id=run.id,
        candidate_rank=1,
    )
    assert regla.symbol == scan.symbol
    assert regla.timeframe == scan.timeframe
    assert "symbol" in inspect.signature(crear_regla).parameters, (
        "se acepta por el camino sin informe, que es donde hace falta"
    )


# ---------------------------------------------------------------------------
# Lo demás
# ---------------------------------------------------------------------------
def test_el_nombre_vacio_se_rechaza(db):
    scan = _scan(db)
    run, _ = _informe(db, scan)

    with pytest.raises(RespaldoNoAceptable) as exc:
        crear_regla(
            db,
            name="   ",
            patron="MACD_CROSS_BULLISH",
            direccion="bullish",
            walk_forward_run_id=run.id,
            candidate_rank=1,
        )
    assert "nombre" in str(exc.value)


def test_un_enfriamiento_negativo_se_rechaza(db):
    scan = _scan(db)
    run, _ = _informe(db, scan)

    with pytest.raises(RespaldoNoAceptable) as exc:
        crear_regla(
            db,
            name="válida",
            patron="MACD_CROSS_BULLISH",
            direccion="bullish",
            walk_forward_run_id=run.id,
            candidate_rank=1,
            cooldown_minutes=-1,
        )
    assert "enfriamiento" in str(exc.value)


def test_el_descargo_no_lo_escribe_el_cliente():
    """El descargo vive en el código, no en la petición.

    Si lo escribiera el usuario, podría decir cualquier cosa, incluido que es
    una recomendación de compra, y el módulo entero se habría descargado el
    contrato en una columna.
    """
    assert "No es una recomendación" in DESCARGO
    assert "intervalo" in DESCARGO


def test_la_regla_congelada_sobrevive_a_borrar_el_informe(db):
    """``SET NULL`` y no ``CASCADE``: el respaldo es evidencia acumulada, y que el
    usuario borre un informe no debe dejarle la regla sin su conclusión."""
    scan = _scan(db)
    run, _ = _informe(db, scan)
    regla = crear_regla(
        db,
        name="sobrevive",
        patron="MACD_CROSS_BULLISH",
        direccion="bullish",
        walk_forward_run_id=run.id,
        candidate_rank=1,
    )
    db.commit()
    regla_id = regla.id

    db.delete(run)
    db.commit()
    db.expire_all()

    superviviente = db.get(AlertRule, regla_id)
    assert superviviente is not None
    assert superviviente.walk_forward_run_id is None
    assert superviviente.validation_status == "prometedora", (
        "el veredicto está copiado en la regla y no depende del informe"
    )
