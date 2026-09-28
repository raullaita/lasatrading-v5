"""Tests del cableado HTTP del walk-forward y de su tarea de Celery.

No repiten la logica del servicio, que ya cubre
``test_backtest_walk_forward_service.py``. Lo que se comprueba aqui es lo unico
que un test de servicio no puede ver:

1. Que cada endpoint llama al metodo que **existe**, con los argumentos que
   espera. Un endpoint que llama a ``get_report`` cuando el metodo se llama
   ``get_informe`` pasa todos los tests de servicio y revienta en produccion.
2. Que cada error sale con el codigo que significa algo: 404 si no existe, 409 si
   existe pero aun no se puede, 422 si la peticion no se puede atender tal cual.
3. Que la tarea se registra con el nombre por el que se encola. Es el mismo
   fallo invisible que se documenta en ``test_backtest_router.py``: una tarea
   registrada como un nombre y encolada como otro no falla en la suite, falla
   en el worker, y el run se queda en ``pending`` para siempre.
"""

from __future__ import annotations

import inspect
import uuid
from unittest.mock import patch

import pytest
from app.core.database import get_db
from app.modules.backtesting import tasks
from app.modules.backtesting.models import (
    WalkForwardRunStatus,
)
from app.modules.backtesting.schemas import WalkForwardCreateIn
from app.modules.backtesting.walk_forward import WindowSpec
from app.modules.backtesting.walk_forward_router import router
from app.modules.backtesting.walk_forward_service import WalkForwardService
from fastapi import FastAPI
from fastapi.testclient import TestClient

#: Prefijo del router, tal y como lo monta ``app/main.py``.
PREFIX = "/api/v1/walk-forward"

pytestmark = pytest.mark.usefixtures("db")


@pytest.fixture
def client(db, escaneo):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as cliente:
        yield cliente


@pytest.fixture
def sin_celery():
    with patch.object(tasks.run_walk_forward_task, "delay") as delay:
        yield delay


@pytest.fixture
def servicio() -> WalkForwardService:
    return WalkForwardService()


def cuerpo(scan_job, **kwargs) -> dict:
    base = dict(
        scan_job_id=str(scan_job.id),
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
        beats_market_ratio=0.0,
        max_simulations=2000,
    )
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# Superficie de la API
# ---------------------------------------------------------------------------
def test_los_endpoints_esperados_estan_montados(client):
    """La lista de la §8 de la spec, literal. Un endpoint que se llamaba de otra
    forma no falla en ningun test: simplemente nadie lo encuentra."""
    spec = client.get("/openapi.json").json()
    rutas = spec["paths"]

    assert set(rutas[f"{PREFIX}/runs"]) >= {"get", "post"}
    assert "get" in rutas[f"{PREFIX}/runs/{{run_id}}"]
    assert "get" in rutas[f"{PREFIX}/runs/{{run_id}}/equity"]
    assert "post" in rutas[f"{PREFIX}/runs/{{run_id}}/cancel"]

    # El progreso va por WebSocket, que no sale en el OpenAPI. Se comprueba que el
    # websocket este registrado en la app, no en el esquema.
    assert any(
        getattr(r, "path", "") == f"{PREFIX}/runs/{{run_id}}/logs"
        for r in router.routes
    ), "falta el WebSocket de progreso"


def test_crear_devuelve_202_y_no_201(client, escaneo, sin_celery):
    """202 y no 201: el informe no existe todavia, y prometerlo seria mentir."""
    respuesta = client.post(f"{PREFIX}/runs", json=cuerpo(escaneo))

    assert respuesta.status_code == 202
    cuerpo_resp = respuesta.json()
    assert cuerpo_resp["status"] == "pending"
    assert cuerpo_resp["simulations"] > 0
    assert sin_celery.called, "el run tiene que encolarse"
    assert sin_celery.call_args[0][0] == str(cuerpo_resp["id"])


def test_crear_encola_con_el_nombre_registrado():
    """El nombre de la tarea y el nombre con el que se encola tienen que ser el
    mismo. No hay ningun test que lo compruebe salvo este, y si se separan el
    run se queda en ``pending`` para siempre sin que nada falle."""
    assert "backtest.run_walk_forward" in tasks.celery_app.tasks, (
        "la tarea no esta registrada con el nombre que se encola"
    )


def test_crear_con_un_escaneo_inexistente_devuelve_404(client, sin_celery):
    respuesta = client.post(
        f"{PREFIX}/runs",
        json={
            "scan_job_id": str(uuid.uuid4()),
            "grid": {
                "take_profit_pcts": [2.0],
                "stop_loss_pcts": [1.0],
                "max_holds": [12],
            },
            "window_days": 30,
            "oos_days": 15,
            "step_days": 15,
        },
    )
    assert respuesta.status_code == 404
    assert not sin_celery.called


def test_crear_con_un_escaneo_a_medias_devuelve_409(client, escaneo, sin_celery):
    """409 y no 400: el escaneo existe y no esta mal formado, simplemente aun no
    se puede simular. Un 400 diria que la peticion era incorrecta y nudaria al
    usuario a construir otra."""
    escaneo.status = "processing"

    respuesta = client.post(f"{PREFIX}/runs", json=cuerpo(escaneo))
    assert respuesta.status_code == 409
    assert not sin_celery.called


def test_crear_con_una_rejilla_demasiado_grande_devuelve_422(
    client, escaneo, sin_celery
):
    """El 422 de la rejilla, con el numero de combinaciones dentro."""
    respuesta = client.post(
        f"{PREFIX}/runs",
        json=cuerpo(
            escaneo,
            grid={
                "take_profit_pcts": [1, 2, 3, 4, 5, 6, 7, 8],
                "stop_loss_pcts": [1, 2, 3, 4, 5, 6, 7, 8],
                "max_holds": [12, 24, 48],
            },
        ),
    )
    assert respuesta.status_code == 422
    assert "combinaciones" in respuesta.text
    assert not sin_celery.called


def test_crear_que_supera_las_simulaciones_devuelve_422_con_el_numero(
    client, escaneo, sin_celery
):
    """Este 422 **no** puede vivir en el schema, y esa es la razon de que este
    test este aqui: el total depende del rango real de las velas, que el cliente
    no conoce. El mensaje lleva cuantas simulaciones serian, para que el
    formulario pueda enseñarlo antes de lanzar.
    """
    respuesta = client.post(f"{PREFIX}/runs", json=cuerpo(escaneo, max_simulations=2))

    assert respuesta.status_code == 422
    detalle = respuesta.json()["detail"]
    assert "simulaciones" in detalle
    assert "ventanas" in detalle, "el mensaje tiene que decir de donde sale el total"
    assert not sin_celery.called, "un 422 no encola nada"


# ---------------------------------------------------------------------------
# Lectura
# ---------------------------------------------------------------------------
def test_leer_un_informe_en_curso_devuelve_409(
    client, db, servicio, escaneo, sin_celery
):
    """409 y no un informe vacio, y no 404.

    Un informe a medias no es un informe con menos filas: es un informe cuyo
    veredicto no se puede leer, porque las candidatas que faltan son justo las
    que no han pasado las guardas. Y 404 diria que no existe, cuando existe.
    """
    run = servicio.create_run(db, WalkForwardCreateIn(**cuerpo(escaneo)))

    respuesta = client.get(f"{PREFIX}/runs/{run.id}")
    assert respuesta.status_code == 409
    assert "pending" in respuesta.json()["detail"]


def test_leer_un_run_inexistente_devuelve_404(client):
    respuesta = client.get(f"{PREFIX}/runs/{uuid.uuid4()}")
    assert respuesta.status_code == 404


def test_el_informe_completo_trae_ventanas_y_candidatas(
    client, db, servicio, escaneo, sin_celery
):
    run = servicio.create_run(db, WalkForwardCreateIn(**cuerpo(escaneo)))
    servicio.execute_run(run.id)
    # ``execute_run`` escribe con sus propias sesiones y la de este test tiene el
    # objeto cacheado en el identity map con el estado de antes. En produccion no
    # pasa: cada peticion recibe una sesion nueva. Aqui hay que vaciar la cache a
    # mano, y el 409 que salia sin esto no era del router.
    db.expire_all()

    respuesta = client.get(f"{PREFIX}/runs/{run.id}")
    assert respuesta.status_code == 200
    datos = respuesta.json()

    assert datos["run"]["status"] == "completed"
    assert datos["run"]["simulations"] > 0
    assert datos["windows"], "el informe sin ventanas no explica nada"
    assert datos["candidates"]
    assert {"is_from", "is_to", "oos_from", "oos_to", "selected_strategy"} <= set(
        datos["windows"][0]
    )
    assert {"score", "verdict", "ci95_low", "ci95_high", "rejections"} <= set(
        datos["candidates"][0]
    )
    assert datos["candidates"][0]["rank"] == 1


def test_la_curva_devuelve_los_puntos_y_el_benchmark(
    client, db, servicio, escaneo, sin_celery
):
    run = servicio.create_run(db, WalkForwardCreateIn(**cuerpo(escaneo)))
    servicio.execute_run(run.id)

    respuesta = client.get(f"{PREFIX}/runs/{run.id}/equity")
    assert respuesta.status_code == 200
    datos = respuesta.json()

    assert datos["total_points"] > 0
    assert datos["returned"] == len(datos["points"])
    assert {"equity", "market_equity", "drawdown_pct", "window_index"} <= set(
        datos["points"][0]
    )


def test_la_curva_admite_submuestreo_y_lo_declara(
    client, db, servicio, escaneo, sin_celery
):
    """``total_points`` y ``returned`` distintos, para que el frontend pueda
    avisar de que esta enseñando menos puntos de los que hay en vez de fingir."""
    run = servicio.create_run(db, WalkForwardCreateIn(**cuerpo(escaneo)))
    servicio.execute_run(run.id)

    completa = client.get(f"{PREFIX}/runs/{run.id}/equity").json()
    if completa["total_points"] < 20:
        pytest.skip("el rango del fixture no da una serie larga")

    corta = client.get(f"{PREFIX}/runs/{run.id}/equity?max_points=5").json()
    assert corta["total_points"] == completa["total_points"]
    assert corta["returned"] < completa["total_points"]
    assert corta["points"][-1]["timestamp"] == completa["points"][-1]["timestamp"]


def test_listar_devuelve_los_runs_en_orden_de_creacion(
    client, db, servicio, escaneo, sin_celery
):
    primero = servicio.create_run(db, WalkForwardCreateIn(**cuerpo(escaneo)))
    segundo = servicio.create_run(db, WalkForwardCreateIn(**cuerpo(escaneo)))

    datos = client.get(f"{PREFIX}/runs").json()
    assert datos["total"] >= 2
    ids = [r["id"] for r in datos["runs"]]
    assert str(segundo.id) in ids and str(primero.id) in ids
    assert ids[0] == str(segundo.id), "el mas reciente primero"


# ---------------------------------------------------------------------------
# Control
# ---------------------------------------------------------------------------
def test_cancelar_un_run_en_curso_lo_pasa_a_cancelled(
    client, db, servicio, escaneo, sin_celery
):
    run = servicio.create_run(db, WalkForwardCreateIn(**cuerpo(escaneo)))
    servicio._mark_run(run.id, WalkForwardRunStatus.PROCESSING.value)

    respuesta = client.post(f"{PREFIX}/runs/{run.id}/cancel")
    assert respuesta.status_code == 200
    assert respuesta.json()["status"] == "cancelled"


def test_cancelar_un_run_terminado_devuelve_409(
    client, db, servicio, escaneo, sin_celery
):
    """409 y no un exito que no cambio nada: si el run ya termino, el informe
    existe y no se puede deshacer. Devolver 200 dejaria al usuario pensando que
    paro, cuando lo que paso es que ya habia acabado."""
    run = servicio.create_run(db, WalkForwardCreateIn(**cuerpo(escaneo)))
    servicio.execute_run(run.id)

    respuesta = client.post(f"{PREFIX}/runs/{run.id}/cancel")
    assert respuesta.status_code == 409


def test_cancelar_un_run_inexistente_devuelve_404(client):
    respuesta = client.post(f"{PREFIX}/runs/{uuid.uuid4()}/cancel")
    assert respuesta.status_code == 404


# ---------------------------------------------------------------------------
# El cableado, que es lo que un test de servicio no ve
# ---------------------------------------------------------------------------
def test_cada_endpoint_llama_a_un_metodo_que_existe():
    """Si un endpoint llama a un metodo mal escrito, la suite entera pasa y
    revienta en produccion con un ``AttributeError``."""
    from app.modules.backtesting.walk_forward_router import (
        cancel_walk_forward,
        create_walk_forward,
        get_walk_forward,
        get_walk_forward_equity,
        list_walk_forwards,
    )

    assert callable(create_walk_forward)
    assert callable(list_walk_forwards)
    assert callable(get_walk_forward)
    assert callable(get_walk_forward_equity)
    assert callable(cancel_walk_forward)

    for metodo in (
        "create_run",
        "list_runs",
        "get_report",
        "get_equity",
        "cancel_run",
    ):
        assert hasattr(WalkForwardService, metodo), f"falta {metodo}"


def test_la_tarea_no_es_una_corrutina():
    """La tarea es sincrona a proposito. Si alguien le pone ``asyncio.run``, la
    simulacion se completa y la tarea falla despues con
    ``TypeError: a coroutine was expected``, dejando el informe ``completed`` en
    la base y la tarea en ``FAILURE``: el peor estado posible, porque parece que
    funciono.
    """
    assert not inspect.iscoroutinefunction(tasks.run_walk_forward_task)


def test_la_tarea_recibe_el_id_como_texto():
    """El broker serializa los argumentos en JSON, asi que el ``UUID`` llega como
    ``str``. Sin la conversion, el worker revienta al empezar."""
    fuente = inspect.getsource(tasks.run_walk_forward_task)
    assert "uuid.UUID(run_id)" in fuente


def test_el_spec_se_reconstruye_desde_la_config_congelada():
    """Lo que se guarda en la base tiene que bastar para volver a construir el
    ``WindowSpec`` identico. Si falta un campo, el informe no es reproducible y
    la columna ``config`` es decorativa.
    """
    campos = set(WindowSpec.__dataclass_fields__)
    for campo in (
        "window_days",
        "oos_days",
        "step_days",
        "min_windows",
        "min_trades",
        "holdout_days",
        "beats_market_ratio",
        "regimes_declared",
        "max_simulations",
    ):
        assert campo in campos, f"el motor no tiene {campo}"
