"""Tests del cableado HTTP y de la tarea de Celery.

No repiten la logica del service, que ya esta cubierta en
``test_backtest_service.py``. Lo que se comprueba aqui es que cada endpoint
llama al metodo que existe, con los argumentos que espera, y que la tarea se
registra con el nombre por el que se encola.

Eso no es un detalle menor: durante la implementacion, un endpoint llamaba a
``get_summary`` cuando el metodo se llamaba ``get_run_summary``, y la tarea se
registraba como ``backtesting.run_backtest`` cuando el nombre acordado era
``backtest.run_backtest``. Los dos fallos eran invisibles para la suite entera,
porque ninguna prueba cruzaba el router con el service ni la tarea con su
nombre. Estos tests son los que los habrian parado.
"""

import inspect
import uuid
from unittest.mock import patch

import pytest
from app.core.database import get_db
from app.modules.backtesting import tasks
from app.modules.backtesting.models import BacktestRun, BacktestRunStatus
from app.modules.backtesting.router import router
from app.modules.backtesting.schemas import (
    BacktestCreateIn,
    BacktestRunListOut,
    BacktestStrategyIn,
)
from app.modules.backtesting.service import BacktestService
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

#: Prefijo del router, tal y como lo monta ``app/main.py``.
PREFIX = "/api/v1/backtests"


@pytest.fixture
def client(db, scan_job):
    """Cliente HTTP con la sesion real de la base de test.

    Se usa la sesion de verdad en lugar de un doble porque los endpoints leen el
    run de la base (resumen, equity, operaciones) y un ``MagicMock`` devolveria
    objetos que no existen: pasaria aqui y reventaria en el broker de verdad.
    """
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as cliente:
        yield cliente


@pytest.fixture
def sin_celery():
    """Impide que los endpoints encolen de verdad.

    El broker no esta disponible en los tests, y sin esto ``.delay`` falla al
    conectar. Ademas lo que se prueba es que se encole, no que el worker lo
    reciba, que es cosa de la integracion contra ``.110``.
    """
    with patch.object(tasks.run_backtest_task, "delay") as delay:
        yield delay


@pytest.fixture
def service():
    return BacktestService()


def crear(service, db, scan_job, **estrategia):
    """Crea un run directamente contra la sesion, sin pasar por HTTP."""
    return service.create_run(
        db,
        BacktestCreateIn(
            scan_job_id=scan_job.id,
            strategy=BacktestStrategyIn(**estrategia or {"max_hold": 6}),
        ),
    )


# ---------------------------------------------------------------------------
# Superficie de la API
# ---------------------------------------------------------------------------
def test_los_endpoints_esperados_estan_montados(client):
    """Si se olvida el ``@router`` de un endpoint, la UI recibe un 404 que no se
    ve hasta que alguien abre esa pantalla en el navegador."""
    spec = client.get("/openapi.json").json()

    esperadas = {
        (f"{PREFIX}", "get"),
        (f"{PREFIX}", "post"),
        (f"{PREFIX}", "delete"),
        (f"{PREFIX}/available-scans", "get"),
        (f"{PREFIX}/{{run_id}}", "get"),
        (f"{PREFIX}/{{run_id}}", "delete"),
        (f"{PREFIX}/{{run_id}}/summary", "get"),
        (f"{PREFIX}/{{run_id}}/equity", "get"),
        (f"{PREFIX}/{{run_id}}/trades", "get"),
        (f"{PREFIX}/{{run_id}}/trades/by-pattern", "get"),
        (f"{PREFIX}/{{run_id}}/cancel", "post"),
        (f"{PREFIX}/{{run_id}}/requeue", "post"),
        (f"{PREFIX}/{{run_id}}/analysis", "get"),
        (f"{PREFIX}/{{run_id}}/sweep", "post"),
    }
    montadas = {
        (ruta, metodo)
        for ruta, operaciones in spec["paths"].items()
        for metodo in operaciones
    }

    assert esperadas - montadas == set(), "faltan endpoints en el router"


# ---------------------------------------------------------------------------
# Crear un run
# ---------------------------------------------------------------------------
def test_crear_un_run_lo_encola(client, scan_job, sin_celery):
    respuesta = client.post(
        f"{PREFIX}",
        json={"scan_job_id": str(scan_job.id), "strategy": {"max_hold": 12}},
    )

    assert respuesta.status_code == 201, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["status"] == BacktestRunStatus.PENDING.value
    assert cuerpo["scan_job_id"] == str(scan_job.id)
    sin_celery.assert_called_once_with(str(cuerpo["id"]))


def test_crear_un_run_con_estrategia_invalida_devuelve_422(
    client, scan_job, sin_celery
):
    """Una estrategia sin TP ni SL no se puede simular, y el error tiene que
    verse al crear el run, no dos minutos despues cuando el worker falla."""
    respuesta = client.post(
        f"{PREFIX}",
        json={
            "scan_job_id": str(scan_job.id),
            "strategy": {"take_profit_pct": None, "stop_loss_pct": None},
        },
    )

    assert respuesta.status_code == 422
    sin_celery.assert_not_called(), "no se debe encolar una peticion invalida"


def test_crear_un_run_de_un_escaneo_inexistente_devuelve_404(client, sin_celery):
    respuesta = client.post(
        f"{PREFIX}",
        json={"scan_job_id": str(uuid.uuid4()), "strategy": {"max_hold": 12}},
    )

    assert respuesta.status_code == 404
    sin_celery.assert_not_called()


def test_crear_un_run_de_un_escaneo_sin_terminar_devuelve_409(db, scan_job, sin_celery):
    """El escaneo existe y no esta mal formado, simplemente aun no se puede
    simular. 409 y no 400: un 400 diria que la peticion era incorrecta."""
    scan_job.status = "running"
    db.commit()

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as cliente:
        respuesta = cliente.post(
            f"{PREFIX}",
            json={"scan_job_id": str(scan_job.id), "strategy": {"max_hold": 12}},
        )

    assert respuesta.status_code == 409, respuesta.text
    sin_celery.assert_not_called()


# ---------------------------------------------------------------------------
# Lectura
# ---------------------------------------------------------------------------
def test_listar_runs_responde_con_la_envolturia_esperada(client, service, db, scan_job):
    crear(service, db, scan_job)

    respuesta = client.get(f"{PREFIX}")
    cuerpo = respuesta.json()

    assert respuesta.status_code == 200
    # Si la envolturia cambia de forma, la respuesta deja de validar aqui.
    valida = BacktestRunListOut.model_validate(cuerpo)
    assert valida.total == 1
    assert valida.runs[0].status == BacktestRunStatus.PENDING.value


def test_escaneos_disponibles_solo_los_completados(client, scan_job):
    respuesta = client.get(f"{PREFIX}/available-scans")
    cuerpo = respuesta.json()

    assert respuesta.status_code == 200
    assert [e["id"] for e in cuerpo["scans"]] == [str(scan_job.id)]
    assert cuerpo["scans"][0]["total_occurrences"] == 4


def test_run_inexistente_devuelve_404(client):
    assert client.get(f"{PREFIX}/{uuid.uuid4()}").status_code == 404


def test_el_detalle_devuelve_el_escaneo_de_origen(client, service, db, scan_job):
    run = crear(service, db, scan_job)

    respuesta = client.get(f"{PREFIX}/{run.id}")

    assert respuesta.status_code == 200
    assert respuesta.json()["scan_job_id"] == str(scan_job.id)


def test_resumen_equity_y_operaciones_de_un_run_ejecutado(
    client, service, db, scan_job
):
    run = crear(service, db, scan_job, max_hold=6)
    service.execute_run(run.id)
    # ``execute_run`` confirma en su propia sesion; la de estos tests tiene el
    # run cacheado sin las metricas que acaba de escribir el service.
    db.expire_all()

    resumen = client.get(f"{PREFIX}/{run.id}/summary")
    equity = client.get(f"{PREFIX}/{run.id}/equity")
    trades = client.get(f"{PREFIX}/{run.id}/trades")
    por_patron = client.get(f"{PREFIX}/{run.id}/trades/by-pattern")

    for respuesta in (resumen, equity, trades, por_patron):
        assert respuesta.status_code == 200, respuesta.text

    assert resumen.json()["run"]["total_trades"] == 4
    assert resumen.json()["total_signals"] == 4
    assert equity.json()["total_points"] == 60
    assert trades.json()["total"] == 4
    assert len(por_patron.json()) == 4


def test_filtrar_operaciones_por_patron(client, service, db, scan_job):
    run = crear(service, db, scan_job, max_hold=6)
    service.execute_run(run.id)
    db.expire_all()

    # El parametro es ``pattern`` en singular y se repite para varios:
    # ``?pattern=A&pattern=B``. No ``patterns``.
    respuesta = client.get(
        f"{PREFIX}/{run.id}/trades", params={"pattern": "MACD_CROSS_BULLISH"}
    )
    cuerpo = respuesta.json()

    assert respuesta.status_code == 200
    assert cuerpo["total"] == 1
    assert {t["pattern_name"] for t in cuerpo["trades"]} == {"MACD_CROSS_BULLISH"}


def test_orden_invalido_devuelve_422_y_no_pasa_al_sql(client, service, db, scan_job):
    """El nombre de la columna se interpola en la sentencia, asi que tiene que
    salir por la validacion. Si no, esto es una inyeccion."""
    run = crear(service, db, scan_job)

    respuesta = client.get(
        f"{PREFIX}/{run.id}/trades",
        params={"sort_by": "net_pnl; DROP TABLE candles"},
    )

    assert respuesta.status_code == 400
    assert "ordenación" in respuesta.json()["detail"]


# ---------------------------------------------------------------------------
# Ciclo de vida
# ---------------------------------------------------------------------------
def test_cancelar_un_run(client, service, db, scan_job):
    run = crear(service, db, scan_job)
    run.status = BacktestRunStatus.PROCESSING.value
    db.commit()

    respuesta = client.post(f"{PREFIX}/{run.id}/cancel")

    assert respuesta.status_code == 200, respuesta.text
    db.expire_all()
    assert db.get(BacktestRun, run.id).status == BacktestRunStatus.CANCELLED.value


def test_cancelar_un_run_ya_terminado_devuelve_409(client, service, db, scan_job):
    run = crear(service, db, scan_job)
    run.status = BacktestRunStatus.COMPLETED.value
    db.commit()

    assert client.post(f"{PREFIX}/{run.id}/cancel").status_code == 409


def test_reencolar_vuelve_a_la_cola_y_lo_encola(
    client, service, db, scan_job, sin_celery
):
    run = crear(service, db, scan_job)
    run.status = BacktestRunStatus.FAILED.value
    run.error_message = "fallo anterior"
    db.commit()

    respuesta = client.post(f"{PREFIX}/{run.id}/requeue")

    assert respuesta.status_code == 200, respuesta.text
    db.expire_all()
    fila = db.get(BacktestRun, run.id)
    assert fila.status == BacktestRunStatus.PENDING.value
    assert fila.started_at is None
    assert fila.error_message is None
    sin_celery.assert_called_once_with(str(run.id))


def test_reencolar_un_run_cancelado_devuelve_400(
    client, service, db, scan_job, sin_celery
):
    """Un cancelado no se reencola: fue una decision del usuario, y relanzarlo
    por la espalda volveria a lanzar una simulacion que pidio parar."""
    run = crear(service, db, scan_job)
    run.status = BacktestRunStatus.CANCELLED.value
    db.commit()

    respuesta = client.post(f"{PREFIX}/{run.id}/requeue")

    assert respuesta.status_code == 400, respuesta.text
    sin_celery.assert_not_called()


def test_borrar_un_run_lo_elimina(client, service, db, scan_job):
    run = crear(service, db, scan_job)
    # El id se copia antes de borrar. El service borra en su propia sesion, asi
    # que la de aqui se queda con el objeto en el identity map apuntando a una
    # fila que ya no existe: leer cualquier atributo suyo (includedo ``.id``)
    # despues de un ``expire_all`` dispara un refresco y levanta
    # ``ObjectDeletedError`` en vez de devolver ``None``.
    run_id = run.id

    assert client.delete(f"{PREFIX}/{run_id}").status_code == 200

    assert (
        db.scalar(
            select(func.count())
            .select_from(BacktestRun)
            .where(BacktestRun.id == run_id)
        )
        == 0
    )
    assert client.delete(f"{PREFIX}/{run_id}").status_code == 404


def test_borrado_por_lotes(client, service, db, scan_job):
    runs = [crear(service, db, scan_job) for _ in range(3)]

    respuesta = client.request(
        "DELETE", f"{PREFIX}", json={"run_ids": [str(r.id) for r in runs]}
    )

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["deleted"] == 3
    db.expire_all()
    assert db.get(BacktestRun, runs[0].id) is None


# ---------------------------------------------------------------------------
# Tarea de Celery
# ---------------------------------------------------------------------------
def test_la_tarea_esta_registrada_con_el_nombre_acordado():
    """El nombre de la tarea es el contrato con el worker: si el codigo encola
    ``backtest.run_backtest`` y la tarea se registra con otro nombre, Celery
    acepta el mensaje y nadie lo ejecuta nunca, sin error visible."""
    assert tasks.run_backtest_task.name == "backtest.run_backtest"


def test_la_tarea_convierte_el_id_que_le_llega_de_json():
    """El broker serializa los argumentos en JSON, asi que el ``run_id`` llega
    como texto. Sin convertirlo, ``execute_run`` recibe un ``str`` donde espera
    un ``UUID``.

    Se parchea en la clase y no en una instancia porque la tarea construye su
    propio ``BacktestService()`` dentro; parchear una instancia de fuera no la
    tocaria y el test pasaria sin comprobar nada.
    """
    identificador = uuid.uuid4()

    with patch.object(BacktestService, "execute_run") as ejecutar:
        tasks.run_backtest_task(str(identificador))

    ejecutar.assert_called_once_with(identificador)


def test_la_tarea_no_es_async():
    """Declarada ``async``, la simulacion terminaria y la tarea fallaria
    despues con ``TypeError: a coroutine was expected``, dejando el run en
    ``completed`` con la tarea en ``FAILURE``."""
    assert not inspect.iscoroutinefunction(tasks.run_backtest_task.run)


# ---------------------------------------------------------------------------
# Analisis y calibracion
# ---------------------------------------------------------------------------
def test_el_analisis_devuelve_los_grupos_con_sus_percentiles(
    client, service, db, scan_job
):
    run = crear(service, db, scan_job, max_hold=6)
    service.execute_run(run.id)
    # ``execute_run`` confirma en su propia sesion; la de estos tests tiene el
    # run cacheado en ``pending`` y el endpoint leeria un estado que ya no es.
    db.expire_all()

    respuesta = client.get(f"{PREFIX}/{run.id}/analysis")

    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["run_id"] == str(run.id)
    assert cuerpo["trades"] > 0
    assert cuerpo["groups"]
    grupo = cuerpo["groups"][0]
    assert {"p10", "p25", "p50", "p75", "p90"} <= set(grupo["winner_mfe"])
    assert grupo["winner_mfe"]["capped_at_pct"] is not None
    assert grupo["free_mfe"]["capped_at_pct"] is None
    assert "findings" in grupo and "warnings" in grupo


def test_el_analisis_de_un_run_inexistente_devuelve_404(client):
    respuesta = client.get(f"{PREFIX}/{uuid.uuid4()}/analysis")

    assert respuesta.status_code == 404


def test_el_analisis_de_un_run_sin_terminar_devuelve_409(client, service, db, scan_job):
    """409 y no 400: el run existe y no esta mal formado, simplemente aun no se
    puede mirar. La UI distingue "no existe" de "aun no" con el codigo."""
    run = crear(service, db, scan_job, max_hold=6)

    respuesta = client.get(f"{PREFIX}/{run.id}/analysis")

    assert respuesta.status_code == 409
    assert "completado" in respuesta.json()["detail"]


def test_el_barrido_devuelve_la_tabla_comparativa(client, service, db, scan_job):
    run = crear(service, db, scan_job, max_hold=6)
    service.execute_run(run.id)
    # ``execute_run`` confirma en su propia sesion; la de estos tests tiene el
    # run cacheado en ``pending`` y el endpoint leeria un estado que ya no es.
    db.expire_all()

    respuesta = client.post(
        f"{PREFIX}/{run.id}/sweep",
        json={
            # La rejilla incluye los parametros del propio run (TP 2,0, SL 1,0 y
            # max_hold 6), que es lo que hace que una fila venga marcada como
            # base y el usuario tenga contra que comparar el resto.
            "take_profit_pcts": [2.0, 6.0],
            "stop_loss_pcts": [1.0, 2.0],
            "max_holds": [6],
        },
    )

    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["requested"] == 4
    assert cuerpo["simulated"] == 4
    assert len(cuerpo["points"]) == 4
    punto = cuerpo["points"][0]
    assert {
        "take_profit_pct",
        "stop_loss_pct",
        "max_hold",
        "net_pnl",
        "win_rate",
    } <= set(punto)
    assert "exits" in punto
    assert sum(p["is_baseline"] for p in cuerpo["points"]) == 1


def test_el_barrido_no_encola_nada_en_celery(client, service, db, scan_job, sin_celery):
    """El barrido es una lectura cara, no un trabajo: si encolase, cada barrido
    de la UI dejaria un run "en curso" que nadie mira y acabaria en la lista."""
    run = crear(service, db, scan_job, max_hold=6)
    service.execute_run(run.id)
    # ``execute_run`` confirma en su propia sesion; la de estos tests tiene el
    # run cacheado en ``pending`` y el endpoint leeria un estado que ya no es.
    db.expire_all()

    respuesta = client.post(
        f"{PREFIX}/{run.id}/sweep",
        json={"take_profit_pcts": [3.0], "stop_loss_pcts": [2.0], "max_holds": [4]},
    )

    assert respuesta.status_code == 200
    sin_celery.assert_not_called()


def test_una_rejilla_demasiado_grande_devuelve_422(client, service, db, scan_job):
    """El tope se comprueba en el contrato, no en el servicio, para que el
    rechazo llegue con el detalle de cuantas combinaciones eran."""
    run = crear(service, db, scan_job, max_hold=6)
    service.execute_run(run.id)
    # ``execute_run`` confirma en su propia sesion; la de estos tests tiene el
    # run cacheado en ``pending`` y el endpoint leeria un estado que ya no es.
    db.expire_all()

    respuesta = client.post(
        f"{PREFIX}/{run.id}/sweep",
        json={
            "take_profit_pcts": [1.0] * 8,
            "stop_loss_pcts": [1.0] * 8,
            "max_holds": [1, 2, 3, 4],
        },
    )

    assert respuesta.status_code == 422
    assert "tope" in respuesta.text


def test_una_rejilla_vacia_devuelve_422(client, service, db, scan_job):
    run = crear(service, db, scan_job, max_hold=6)
    service.execute_run(run.id)
    # ``execute_run`` confirma en su propia sesion; la de estos tests tiene el
    # run cacheado en ``pending`` y el endpoint leeria un estado que ya no es.
    db.expire_all()

    respuesta = client.post(
        f"{PREFIX}/{run.id}/sweep",
        json={"take_profit_pcts": [], "stop_loss_pcts": [1.0], "max_holds": [4]},
    )

    assert respuesta.status_code == 422


def test_el_barrido_de_un_run_sin_terminar_devuelve_409(client, service, db, scan_job):
    run = crear(service, db, scan_job, max_hold=6)

    respuesta = client.post(
        f"{PREFIX}/{run.id}/sweep",
        json={"take_profit_pcts": [1.0], "stop_loss_pcts": [1.0], "max_holds": [4]},
    )

    assert respuesta.status_code == 409


def test_una_rejilla_sin_la_estrategia_del_run_no_marca_ninguna_fila(
    client, service, db, scan_job
):
    """``is_baseline`` dice "esta fila es la que ya tienes guardada", asi que
    marcar la mejor de la rejilla como base seria mentir. Si los parametros del
    run no estan en la rejilla, no hay fila base y la tabla lo dice con cero
    marcadas en vez de inventar una."""
    run = crear(service, db, scan_job, max_hold=6)
    service.execute_run(run.id)
    db.expire_all()

    respuesta = client.post(
        f"{PREFIX}/{run.id}/sweep",
        json={"take_profit_pcts": [6.0], "stop_loss_pcts": [4.0], "max_holds": [3]},
    )

    assert respuesta.status_code == 200, respuesta.text
    assert sum(p["is_baseline"] for p in respuesta.json()["points"]) == 0


def test_el_resumen_trae_el_benchmark_de_mercado(client, service, db, scan_job):
    """Sin esta cifra, la tarjeta de metricas no es interpretable: los mismos
    numeros significan cosas distintas en un mercado que subio y en uno que bajo.
    Va dentro del resumen para no añadir una cuarta peticion al cargar la pagina."""
    run = crear(service, db, scan_job, max_hold=6)
    service.execute_run(run.id)
    db.expire_all()

    cuerpo = client.get(f"{PREFIX}/{run.id}/summary").json()

    assert cuerpo["benchmark"] is not None
    assert cuerpo["benchmark"]["candles"] == 60
    assert float(cuerpo["benchmark"]["total_return_pct"]) > 0
    assert cuerpo["benchmark"]["initial_capital"] is not None


def test_el_barrido_trae_el_benchmark_para_comparar_las_filas(
    client, service, db, scan_job
):
    """Todas las filas de la rejilla compiten contra el mismo mercado, asi que
    el benchmark viaja una vez en la respuesta y la tabla lo pinta como
    referencia, no repetido en cada celda."""
    run = crear(service, db, scan_job, max_hold=6)
    service.execute_run(run.id)
    db.expire_all()

    cuerpo = client.post(
        f"{PREFIX}/{run.id}/sweep",
        json={"take_profit_pcts": [3.0], "stop_loss_pcts": [3.0], "max_holds": [6]},
    ).json()

    assert cuerpo["benchmark"] is not None
    assert "total_return_pct" in cuerpo["benchmark"]
    assert "max_drawdown_pct" in cuerpo["benchmark"]
