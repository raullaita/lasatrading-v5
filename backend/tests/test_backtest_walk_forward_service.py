"""Tests del servicio de walk-forward: lo que el motor puro no puede comprobar.

El motor ya tiene 60 tests propios. Aqui se prueba lo otro: que la
configuracion se congele, que el 422 del tope de simulaciones salga antes de
encolar nada, que **no** se persistan las simulaciones, que un fallo deje
informe del fallo en vez de un run colgado, y que cancelar pare el motor entre
ventanas.

Todos estos tests tocan PostgreSQL de verdad, y por eso apuntan a ``lasa_test``
(ver ``conftest.py``). No es que se pueda evitar: lo que se prueba es la
persistencia, y la persistencia es contra una base de datos.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from app.modules.backtesting.models import (
    WalkForwardCandidate,
    WalkForwardEquityPoint,
    WalkForwardLog,
    WalkForwardRun,
    WalkForwardRunStatus,
    WalkForwardWindow,
)
from app.modules.backtesting.schemas import WalkForwardCreateIn
from app.modules.backtesting.walk_forward_service import (
    TooManySimulations,
    WalkForwardRunNotFinished,
    WalkForwardRunNotFound,
    WalkForwardScanNotReady,
    WalkForwardService,
)

pytestmark = pytest.mark.usefixtures("db")

INICIO = datetime(2023, 1, 1, tzinfo=timezone.utc)
DIAS = 150
VECES = 24


@pytest.fixture
def peticion(escaneo):
    """Peticion valida y pequena: dos combinaciones, ventanas de 30/15 dias."""

    def _make(**kwargs) -> WalkForwardCreateIn:
        base = dict(
            scan_job_id=escaneo.id,
            grid={
                "take_profit_pcts": [2.0],
                "stop_loss_pcts": [1.0, 1.5],
                "max_holds": [12],
            },
            window_days=30,
            oos_days=15,
            step_days=15,
            min_windows=1,
            min_trades=0,
            holdout_days=0,
            beats_market_ratio=0.0,
            regimes_declared=1,
            max_simulations=2000,
        )
        base.update(kwargs)
        return WalkForwardCreateIn(**base)

    return _make


@pytest.fixture
def servicio() -> WalkForwardService:
    return WalkForwardService()


# ---------------------------------------------------------------------------
# Creacion
# ---------------------------------------------------------------------------
def test_crear_congela_configuracion_y_rejilla(db, servicio, peticion):
    run = servicio.create_run(db, peticion())

    assert run.status == WalkForwardRunStatus.PENDING.value
    assert run.config["window_days"] == 30
    assert run.config["minutes_per_candle"] == 60
    assert run.grid["combinations"] == 2


def test_crear_cuenta_las_simulaciones_de_verdad(db, servicio, peticion):
    """``simulations`` es el total real, y por eso se calcula sobre las ventanas
    que se van a construir y no sobre una estimacion del rango declarado."""
    run = servicio.create_run(db, peticion())

    assert run.windows >= 2, "150 dias con ventanas de 30/15 deben dar varias"
    assert run.simulations == run.windows * 2
    assert run.simulations > run.windows, "si fuera igual, no estaria barriendo"


def test_el_tope_de_simulaciones_rechaza_antes_de_encolar(db, servicio, peticion):
    """El 422 que la §8 promete, con el numero de simulaciones que serian.

    Y con la fila ya creada pero sin logica: lo que se comprueba aqui es que el
    rechazo ocurre **antes** de que el worker pueda empezar, no que el motor
    reviente mas tarde.
    """
    with pytest.raises(TooManySimulations) as exc:
        servicio.create_run(db, peticion(max_simulations=3))

    mensaje = str(exc.value)
    assert "3" in mensaje, "el mensaje tiene que decir el tope, no solo que se paso"
    assert "simulaciones" in mensaje
    assert db.query(WalkForwardRun).count() == 0


def test_escaneo_no_completado_no_se_lanza(db, servicio, escaneo, peticion):
    escaneo.status = "processing"
    db.commit()

    with pytest.raises(WalkForwardScanNotReady) as exc:
        servicio.create_run(db, peticion())
    assert "processing" in str(exc.value)


def test_escaneo_inexistente_da_404(db, servicio):
    with pytest.raises(WalkForwardRunNotFound):
        servicio.create_run(
            db,
            WalkForwardCreateIn(
                scan_job_id=uuid.uuid4(),
                grid={
                    "take_profit_pcts": [2.0],
                    "stop_loss_pcts": [1.0],
                    "max_holds": [12],
                },
                window_days=30,
                oos_days=15,
                step_days=15,
            ),
        )


# ---------------------------------------------------------------------------
# Ejecucion y persistencia
# ---------------------------------------------------------------------------
def test_el_run_terminado_persiste_ventanas_candidatas_y_curva(db, servicio, peticion):
    run = servicio.create_run(db, peticion())
    servicio.execute_run(run.id)

    db.expire_all()
    guardado = db.get(WalkForwardRun, run.id)
    assert guardado.status == WalkForwardRunStatus.COMPLETED.value, (
        f"el run fallo: {guardado.error_message}"
    )
    assert guardado.finished_at is not None
    assert guardado.error_message is None

    ventanas = db.query(WalkForwardWindow).filter_by(run_id=run.id).count()
    candidatos = db.query(WalkForwardCandidate).filter_by(run_id=run.id).count()
    puntos = db.query(WalkForwardEquityPoint).filter_by(run_id=run.id).count()

    assert ventanas > 0
    assert candidatos > 0
    assert puntos > 0, "sin curva no se puede pintar el informe"
    assert guardado.simulations == ventanas * 2


def test_no_se_persisten_las_simulaciones_individuales(db, servicio, peticion):
    """El contrato del modulo: un informe, no un vertedero.

    Con varias ventanas y varias combinaciones, lo guardado tiene que ser del
    orden de las ventanas y los candidatos, y **no** del orden del producto. Es
    el test que detecta que alguien ha empezado a persistir cada simulacion.
    """
    run = servicio.create_run(db, peticion(window_days=30, oos_days=15, step_days=15))
    servicio.execute_run(run.id)

    db.expire_all()
    ventanas = db.query(WalkForwardWindow).filter_by(run_id=run.id).count()
    candidatos = db.query(WalkForwardCandidate).filter_by(run_id=run.id).count()
    simulaciones = db.get(WalkForwardRun, run.id).simulations

    assert simulaciones > 10
    assert ventanas + candidatos < simulaciones, (
        f"han escrito {ventanas + candidatos} filas para {simulaciones} "
        "simulaciones: se estan guardando las simulaciones"
    )


def test_las_descartadas_se_guardan_con_su_motivo(db, servicio, peticion):
    """Regla 5 del Contrato Estadistico: los resultados negativos se archivan.

    Se sube ``min_trades`` para que alguna combinacion no llegue, y se comprueba
    que sigue en la tabla y con el motivo escrito. Un informe que solo guardara
    los ganadores no podria cumplir esto.
    """
    run = servicio.create_run(
        db, peticion(min_trades=10_000, min_windows=1, beats_market_ratio=0.0)
    )
    servicio.execute_run(run.id)

    db.expire_all()
    candidatos = db.query(WalkForwardCandidate).filter_by(run_id=run.id).all()
    assert candidatos, "aunque no pase nada tiene que haber candidata que explicar"
    assert all(c.verdict == "descartada" for c in candidatos)
    assert all(c.rejections for c in candidatos), (
        "una candidata descartada sin motivo obliga a reejecutar el run para "
        "entender por que salio asi"
    )


def test_la_curva_lleva_el_benchmark_y_la_ventana_de_cada_tramo(db, servicio, peticion):
    run = servicio.create_run(db, peticion())
    servicio.execute_run(run.id)

    db.expire_all()
    puntos = (
        db.query(WalkForwardEquityPoint)
        .filter_by(run_id=run.id)
        .order_by(WalkForwardEquityPoint.timestamp)
        .all()
    )
    assert len(puntos) > 1
    assert all(p.market_equity is not None for p in puntos)
    assert all(p.window_index >= 1 for p in puntos), (
        "sin el indice de ventana no se puede contrastar un tramo del grafico con "
        "su fila de la tabla de ventanas"
    )
    indices = [p.window_index for p in puntos]
    assert indices == sorted(indices), "la ventana de la curva no puede ir atras"


def test_repetir_el_run_no_deja_filas_duplicadas(db, servicio, peticion):
    """Requeue relanza el motor entero. Lo que se guarda es **el ultimo**
    intento, no la union de los dos: un informe que mezcla dos ejecuciones con
    distinta semilla de bootstrap no es reproducible."""
    run = servicio.create_run(db, peticion())
    servicio.execute_run(run.id)
    antes = db.query(WalkForwardWindow).filter_by(run_id=run.id).count()
    antes_c = db.query(WalkForwardCandidate).filter_by(run_id=run.id).count()

    servicio._mark_run(run.id, WalkForwardRunStatus.PROCESSING.value)
    servicio.execute_run(run.id)

    db.expire_all()
    assert db.query(WalkForwardWindow).filter_by(run_id=run.id).count() == antes
    assert db.query(WalkForwardCandidate).filter_by(run_id=run.id).count() == antes_c


# ---------------------------------------------------------------------------
# Fallos y cancelacion
# ---------------------------------------------------------------------------
def test_un_fallo_deja_el_run_en_failed_con_el_motivo(
    db, servicio, peticion, monkeypatch
):
    """Un informe colgado no es un informe a medias: es un informe que miente
    sobre si existe."""
    run = servicio.create_run(db, peticion())

    def revienta(run_id):
        raise RuntimeError("el worker se quedó sin memoria a mitad")

    monkeypatch.setattr(servicio, "_run", revienta)
    servicio.execute_run(run.id)

    db.expire_all()
    guardado = db.get(WalkForwardRun, run.id)
    assert guardado.status == WalkForwardRunStatus.FAILED.value
    assert guardado.finished_at is not None
    assert "sin memoria" in (guardado.error_message or "")

    logs = db.query(WalkForwardLog).filter_by(run_id=run.id, level="error").all()
    assert logs, "el motivo tiene que estar tambien en el log que ve el usuario"


def test_cancelar_pare_el_motor_entre_ventanas_y_no_es_un_fallo(db, servicio, peticion):
    """El boton de cancelar tiene que hacer algo, y no tiene que parecerse a un
    error: un run cancelado que acaba en ``failed`` enseña al usuario un fallo
    donde solo pulso un boton."""
    run = servicio.create_run(db, peticion())
    servicio._mark_run(run.id, WalkForwardRunStatus.PROCESSING.value, started_at=True)
    servicio.cancel_run(run.id)

    servicio.execute_run(run.id)

    db.expire_all()
    guardado = db.get(WalkForwardRun, run.id)
    assert guardado.status == WalkForwardRunStatus.CANCELLED.value
    assert not guardado.error_message, "cancelar no es fallar"
    assert db.query(WalkForwardWindow).filter_by(run_id=run.id).count() == 0


def test_cancelar_entre_ventanas_durante_la_ejecucion(
    db, servicio, peticion, monkeypatch
):
    """El caso real: el worker ya esta corriendo y el usuario cancela.

    Se comprueba que el motor se detiene en la frontera de una ventana, que el
    run queda ``cancelled`` y que **no** queda un informe parcial con veredictos.
    """
    run = servicio.create_run(db, peticion())
    servicio._mark_run(run.id, WalkForwardRunStatus.PROCESSING.value, started_at=True)

    visits = 0

    def cancela_en_la_segunda(hechas: int, total: int, etiqueta: str) -> bool:
        nonlocal visits
        visits += 1
        if visits == 2:
            servicio.cancel_run(run.id)
        return True  # el primer is_cancelled decide

    monkeypatch.setattr(
        servicio, "_progreso", lambda run_id, spec: cancela_en_la_segunda
    )
    servicio.execute_run(run.id)

    db.expire_all()
    guardado = db.get(WalkForwardRun, run.id)
    assert guardado.status == WalkForwardRunStatus.CANCELLED.value
    assert not guardado.error_message
    assert db.query(WalkForwardCandidate).filter_by(run_id=run.id).count() == 0, (
        "no debe quedar ningun candidato de un run que se cancelo a mitad"
    )


def test_cancelar_un_run_terminado_no_hace_nada(db, servicio, peticion):
    run = servicio.create_run(db, peticion())
    servicio.execute_run(run.id)

    assert servicio.cancel_run(run.id) is False
    db.expire_all()
    assert db.get(WalkForwardRun, run.id).status == (
        WalkForwardRunStatus.COMPLETED.value
    )


# ---------------------------------------------------------------------------
# Lectura
# ---------------------------------------------------------------------------
def test_el_informe_no_se_lee_mientras_el_run_no_termina(db, servicio, peticion):
    """Un informe a medias no es un informe con menos filas: es un informe cuyo
    veredicto no se puede leer, porque las candidatas que faltan son justo las
    que no han pasado las guardas."""
    run = servicio.create_run(db, peticion())

    with pytest.raises(WalkForwardRunNotFinished) as exc:
        servicio.get_report(db, run.id)
    assert "pending" in str(exc.value)


def test_el_informe_trae_ventanas_y_candidatas_ordenadas(db, servicio, peticion):
    run = servicio.create_run(db, peticion())
    servicio.execute_run(run.id)

    db.expire_all()
    informe = servicio.get_report(db, run.id)

    assert informe.windows, "el informe sin ventanas no explica nada"
    assert [w.index for w in informe.windows] == sorted(
        w.index for w in informe.windows
    )
    assert [c.rank for c in informe.candidates] == list(
        range(1, len(informe.candidates) + 1)
    )
    assert informe.run.simulations == informe.run.windows * 2

    orden = {"sostenida": 0, "prometedora": 1, "descartada": 2}
    posiciones = [orden[c.verdict] for c in informe.candidates]
    assert posiciones == sorted(posiciones), (
        "ninguna descartada puede salir por delante de una que no lo esta"
    )


def test_la_curva_se_submuestrea_conservando_el_ultimo_punto(db, servicio, peticion):
    """La curva que no llega al cierre no enseña el ``equity_final`` que dice la
    cabecera, y esa es justo la cifra que el usuario va a comparar."""
    run = servicio.create_run(db, peticion())
    servicio.execute_run(run.id)

    db.expire_all()
    completa = servicio.get_equity(db, run.id)
    if completa.total_points < 40:
        pytest.skip("el rango del fixture no da una serie larga")

    corta = servicio.get_equity(db, run.id, max_points=10)
    assert corta.total_points == completa.total_points
    assert corta.returned < completa.total_points
    assert len(corta.points) == corta.returned
    assert corta.points[-1].timestamp == completa.points[-1].timestamp
    assert corta.points[-1].equity == completa.points[-1].equity


def test_los_logs_avanzan_por_ventana_y_no_por_simulacion(db, servicio, peticion):
    """El progreso se reporta por ventana. Si se reportara por simulacion, un
    informe de 2.000 simulaciones tendria 2.000 lineas de log y el usuario leeria
    lo mismo que con 10."""
    run = servicio.create_run(db, peticion())
    servicio.execute_run(run.id)

    db.expire_all()
    logs = (
        db.query(WalkForwardLog)
        .filter_by(run_id=run.id)
        .order_by(WalkForwardLog.timestamp)
        .all()
    )
    con_progreso = [log for log in logs if log.progress is not None]
    assert con_progreso
    assert con_progreso[-1].progress == 100
    assert len(con_progreso) < db.get(WalkForwardRun, run.id).simulations, (
        "una linea por ventana, no una por simulacion"
    )
