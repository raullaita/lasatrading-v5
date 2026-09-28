"""Tests del servicio de backtesting: persistencia, cascada y agregados.

A diferencia de ``test_backtest_engine.py``, aqui si hay PostgreSQL de verdad:
lo que se prueba es precisamente lo que solo existe contra una base de datos, la
persistencia de miles de filas, la cascada de borrados, los agregados en SQL y
el filtrado de la vista de detalle. Si no hay base de datos alcanzable, las
fixtures los saltan en vez de fallar.

El escenario base es el equivalente en miniatura del scan real ``02a2412a``:
60 velas, 4 patrones y 4 señales separadas 10 horas, de modo que cada operación
se cierra antes de que llegue la siguiente y no hay solapes.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from app.modules.backtesting.models import BacktestRun, BacktestRunStatus
from app.modules.backtesting.schemas import BacktestCreateIn, BacktestStrategyIn
from app.modules.backtesting.service import (
    RunFilters,
    RunNotFound,
    ScanNotReady,
    strategy_filters,
    strategy_params,
)

pytestmark = pytest.mark.filterwarnings("error::RuntimeWarning")

INICIO = datetime(2024, 1, 1, tzinfo=timezone.utc)


def crear(db, service, scan_job, **overrides) -> BacktestRun:
    payload = {
        "scan_job_id": scan_job.id,
        "strategy": BacktestStrategyIn(),
        "patterns": None,
        "directions": None,
    }
    payload.update(overrides)
    return service.create_run(db, BacktestCreateIn(**payload))


# ---------------------------------------------------------------------------
# Creacion y validacion
# ---------------------------------------------------------------------------
def test_crea_run_con_configuracion_valida(db, service, scan_job):
    run = crear(db, service, scan_job)

    assert run.id is not None
    assert run.status == BacktestRunStatus.PENDING.value
    assert run.scan_job_id == scan_job.id
    assert run.initial_capital == Decimal("1000")
    assert run.total_trades == 0
    assert run.equity_final is None, "un run recien creado no tiene resultados"


def test_congela_la_configuracion_en_la_columna_strategy(db, service, scan_job):
    run = crear(
        db,
        service,
        scan_job,
        strategy=BacktestStrategyIn(
            take_profit_pct=3.0, stop_loss_pct=1.5, max_hold=48
        ),
        patterns=["MACD_CROSS_BULLISH", "ENGULFING_BEARISH"],
    )

    assert run.strategy["take_profit_pct"] == 3.0
    assert run.strategy["max_hold"] == 48
    assert run.strategy["patterns"] == ["MACD_CROSS_BULLISH", "ENGULFING_BEARISH"]


def test_los_filtros_viajan_dentro_de_strategy_y_no_se_pierden(db, service, scan_job):
    """Si los filtros vivieran fuera de ``strategy``, un requeue simularia otro
    conjunto de señales sin avisar y los dos runs no serian comparables."""
    run = crear(
        db, service, scan_job, patterns=["RSI_EXIT_OVERSOLD"], directions=["bullish"]
    )
    db.refresh(run)

    payload = run.strategy
    assert strategy_params(payload) == {
        "take_profit_pct": 2.0,
        "stop_loss_pct": 1.0,
        "max_hold": 24,
        "fee_bps": 4.0,
        "initial_capital": 1000.0,
        "use_fraction": 1.0,
        "entry_offset": 1,
        "allow_short": True,
    }, "los filtros no deben filtrarse dentro de los parametros del motor"
    filtros = strategy_filters(payload)
    assert filtros.patterns == ("RSI_EXIT_OVERSOLD",)
    assert filtros.directions == ("bullish",)


def test_rechaza_escaneo_inexistente(db, service):
    with pytest.raises(RunNotFound, match="no existe"):
        service.create_run(db, BacktestCreateIn(scan_job_id=uuid.uuid4()))


def test_rechaza_escaneo_sin_terminar(db, service, scan_job):
    """Un escaneo en curso tiene solo parte de sus ocurrencias: simular contra
    un subconjunto daria un resultado que luego no se reproduce."""
    scan_job.status = "processing"
    db.commit()

    with pytest.raises(
        ScanNotReady, match="Solo se pueden simular escaneos completados"
    ):
        service.create_run(db, BacktestCreateIn(scan_job_id=scan_job.id))


@pytest.mark.parametrize(
    "strategy",
    [
        {"take_profit_pct": 0},
        {"take_profit_pct": -2},
        {"stop_loss_pct": 0},
        {"max_hold": 0},
        {"max_hold": -5},
        {"use_fraction": 0},
        {"use_fraction": 1.5},
        {"initial_capital": 0},
        {"fee_bps": -1},
    ],
)
def test_rechaza_parametros_de_estrategia_invalidos(strategy):
    with pytest.raises(ValueError):
        BacktestStrategyIn(**strategy)


def test_rechaza_estrategia_sin_forma_de_salir():
    """Sin TP ni SL solo quedan timeouts, que no es una estrategia."""
    with pytest.raises(ValueError, match="forma de cerrar"):
        BacktestStrategyIn(take_profit_pct=None, stop_loss_pct=None)


def test_rechaza_filtro_de_patrones_vacio():
    with pytest.raises(ValueError, match="no puede ser una lista vacía"):
        BacktestCreateIn(scan_job_id=uuid.uuid4(), patterns=[])


def test_rechaza_nombre_de_patron_vacio():
    with pytest.raises(ValueError, match="nombres vacíos"):
        BacktestCreateIn(
            scan_job_id=uuid.uuid4(), patterns=["MACD_CROSS_BULLISH", "  "]
        )


# ---------------------------------------------------------------------------
# Ejecucion
# ---------------------------------------------------------------------------
def test_ejecuta_y_persiste_operaciones_y_equity(db, service, scan_job):
    run = crear(db, service, scan_job, strategy=BacktestStrategyIn(max_hold=6))
    service.execute_run(run.id)

    db.expire_all()
    run = db.get(BacktestRun, run.id)

    assert run.status == BacktestRunStatus.COMPLETED.value
    assert run.total_trades > 0, "con 4 señales separadas deberia haber operaciones"
    assert run.finished_at is not None
    assert run.error_message is None
    assert run.equity_final is not None
    assert run.net_pnl is not None


def test_persiste_mae_y_mfe_de_cada_operacion(db, service, scan_job):
    run = crear(db, service, scan_job, strategy=BacktestStrategyIn(max_hold=6))
    service.execute_run(run.id)

    trades, _, _ = service.get_run_trades(db, run.id)
    assert trades
    for trade in trades:
        assert trade.mae is not None and trade.mae <= 0
        assert trade.mfe is not None and trade.mfe >= 0
        assert trade.signal_timestamp is not None
        assert trade.pattern_name
        assert trade.exit_reason in {
            "take_profit",
            "stop_loss",
            "timeout",
            "end_of_data",
        }


def test_una_fila_de_equity_por_vela(db, service, scan_job):
    run = crear(db, service, scan_job, strategy=BacktestStrategyIn(max_hold=6))
    service.execute_run(run.id)
    db.expire_all()

    serie = service.get_run_equity(db, run.id)

    assert serie.total_points == 60, "una fila por vela del rango"
    assert serie.returned == 60
    assert len(serie.points) == 60
    assert serie.points[0].equity == Decimal("1000.00000000")
    # El max drawdown se lee del run, no de la serie, asi que hace falta
    # refrescar la sesion: ``execute_run`` confirma en la suya y la de aqui
    # sigue con el run recien creado, sin metricas.
    assert serie.max_drawdown_pct is not None
    assert float(serie.max_drawdown_pct) == pytest.approx(
        max(float(p.drawdown_pct) for p in serie.points), abs=1e-6
    )


def test_el_resumen_cuadra_con_las_operaciones_persistidas(db, service, scan_job):
    """El win_rate de la cabecera tiene que ser el mismo que el del desglose.

    Es el contrato entre lo que calcula el motor, lo que se copia a
    ``backtest_runs`` y lo que se re-calcula en SQL para el desglose. Si los
    tres se separan, la tarjeta y la tabla dicen coisas distintas.
    """
    run = crear(db, service, scan_job, strategy=BacktestStrategyIn(max_hold=6))
    service.execute_run(run.id)
    db.expire_all()
    run = db.get(BacktestRun, run.id)

    resumen = service.get_run_summary(db, run.id)
    trades, total, net = service.get_run_trades(db, run.id)

    assert total == run.total_trades
    # La cabecera guarda el PnL en float y lo redondea una vez al escribirlo en
    # ``Numeric(20,8)``; cada operacion se redondea tambien a ``Numeric(18,8)``
    # por separado. Sumar operaciones ya redondeadas no puede dar exactamente
    # el mismo digito que redondear la suma, asi que la diferencia de 1e-8 es
    # esperable. Comparar con igualdad exacta aqui fallaria siempre.
    assert float(net) == pytest.approx(float(run.net_pnl), abs=1e-6)
    assert resumen.total_signals == 4, "4 ocurrencias en el escaneo"
    assert sum(b.trades for b in resumen.by_pattern) == run.total_trades
    # Los ``net_pnl`` del desglose son ``Decimal``: se convierte a float porque
    # ``pytest.approx`` resta y ``float - Decimal`` no existe en Python.
    assert float(sum(b.net_pnl for b in resumen.by_pattern)) == pytest.approx(
        float(run.net_pnl)
    )
    assert resumen.run.win_rate == run.win_rate


def test_el_resumen_trae_las_cuatro_metricas_de_cabecera(db, service, scan_job):
    """win_rate, profit_factor, max_drawdown y sharpe llegan desde el motor hasta
    la respuesta, no se quedan en ``None`` por el camino.

    Cualquiera de las cuatro se puede perder en un ``_finish_run`` que olvide
    copiar un campo, y el sintoma es una tarjeta con un ``-`` en lugar de un
    número, que es difícil de detectar a ojo.
    """
    run = crear(db, service, scan_job, strategy=BacktestStrategyIn(max_hold=6))
    service.execute_run(run.id)
    db.expire_all()

    resumen = service.get_run_summary(db, run.id)

    assert resumen.run.win_rate is not None
    assert 0 <= float(resumen.run.win_rate) <= 1
    assert resumen.run.profit_factor is not None, "hay perdedoras, luego existe"
    assert resumen.run.profit_factor > 0
    assert resumen.run.max_drawdown_pct is not None
    assert float(resumen.run.max_drawdown_pct) > 0
    assert resumen.run.sharpe_ratio is not None
    # El fixture es una rampa siempre al alza, asi que la equity crece y el
    # Sharpe es negativo. Lo que importa es que se haya calculado, no el signo.
    assert float(resumen.run.sharpe_ratio) < 0


def test_win_rate_excluye_las_truncadas_por_fin_de_datos(db, service, scan_job):
    """La ultima señal cae en la vela 35 de un rango de 60 y su operación se
    cierra con ``end_of_data``; esa no cuenta para el acierto.

    El run filtra a un solo patron a proposito. Con las cuatro señales sueltas
    la de la vela 5 abriría posición y, con ``max_hold=48``, seguiría abierta
    hasta la vela 53: las otras tres señales se marcarían como *omitidas por
    posición abierta* y no llegarian a existir como operaciones. Para probar el
    fin de datos hay que dejar que la señal llega a ser la última en entrar.
    """
    run = crear(
        db,
        service,
        scan_job,
        # TP y SL a 50%: el precio del fixture solo recorre un 3% en las 60
        # velas, asi que ninguno se toca y la unica salida posible es el
        # timeout o el fin de datos. No se pueden dejar a None porque una
        # estrategia sin TP ni SL se rechaza antes de llegar aqui.
        strategy=BacktestStrategyIn(
            max_hold=48, take_profit_pct=50.0, stop_loss_pct=50.0
        ),
        patterns=("MA_CROSS_BEARISH",),
    )
    service.execute_run(run.id)
    db.expire_all()
    run = db.get(BacktestRun, run.id)

    trades, _, _ = service.get_run_trades(db, run.id, page_size=100)
    truncadas = [t for t in trades if t.exit_reason == "end_of_data"]
    assert truncadas, "con max_hold=48 la senal de la vela 35 deberia truncarse"
    # ``truncated_trades`` no cuenta esto: cuenta senales que caen sin vela
    # detrás donde entrar, que aqui no son ninguna. Lo que sale por
    # ``end_of_data`` se consulta sobre las operaciones.
    assert run.truncated_trades == 0

    contadas = [t for t in trades if t.exit_reason != "end_of_data"]
    ganadoras = [t for t in contadas if t.net_pnl > 0]
    if contadas:
        assert run.win_rate == pytest.approx(
            Decimal(str(len(ganadoras) / len(contadas))), abs=Decimal("0.000001")
        )


def test_el_escaneo_filtrado_reduce_las_senales(db, service, scan_job):
    run = crear(
        db,
        service,
        scan_job,
        patterns=["MACD_CROSS_BULLISH", "ENGULFING_BEARISH"],
        strategy=BacktestStrategyIn(max_hold=6),
    )
    service.execute_run(run.id)
    db.expire_all()
    run = db.get(BacktestRun, run.id)

    resumen = service.get_run_summary(db, run.id)
    patrones = {b.pattern_name for b in resumen.by_pattern}
    assert patrones <= {"MACD_CROSS_BULLISH", "ENGULFING_BEARISH"}
    assert resumen.total_signals == 2, "solo las señales del filtro, no las 4"
    assert run.total_trades <= 2


def test_marca_el_run_como_fallido_y_guarda_el_motivo(
    db, service, scan_job, monkeypatch
):
    run = crear(db, service, scan_job)

    def reventar(*_args, **_kwargs):
        raise RuntimeError("fallo simulado")

    monkeypatch.setattr("app.modules.backtesting.service.run_backtest", reventar)
    service.execute_run(run.id)

    db.expire_all()
    run = db.get(BacktestRun, run.id)
    assert run.status == BacktestRunStatus.FAILED.value
    assert "fallo simulado" in (run.error_message or "")
    assert run.finished_at is not None


# ---------------------------------------------------------------------------
# Cancelacion
# ---------------------------------------------------------------------------
def test_cancela_un_run_en_processing(db, service, scan_job):
    run = crear(db, service, scan_job)
    run.status = BacktestRunStatus.PROCESSING.value
    db.commit()

    assert service.cancel_run(run.id) is True
    db.expire_all()
    assert db.get(BacktestRun, run.id).status == BacktestRunStatus.CANCELLED.value


def test_no_cancela_un_run_ya_terminado(db, service, scan_job):
    run = crear(db, service, scan_job)
    run.status = BacktestRunStatus.COMPLETED.value
    db.commit()

    assert service.cancel_run(run.id) is False
    db.expire_all()
    assert db.get(BacktestRun, run.id).status == BacktestRunStatus.COMPLETED.value


def test_cancelar_antes_de_que_arranque_la_tarea_no_se_pierde(db, service, scan_job):
    """Cancelado antes de arrancar sigue cancelado cuando la tarea entra.

    Reproduce la carrera real: Celery encola la tarea y el usuario cancela
    mientras sigue en cola. Cuando la tarea entra, ``execute_run`` marca "en
    curso" y sin proteccion eso pisa el "cancelado"; el ``is_cancelled`` de
    despues ya no ve nada y el backtest se ejecuta entero.
    """
    run = crear(db, service, scan_job, strategy=BacktestStrategyIn(max_hold=6))
    assert service.cancel_run(run.id) is True

    service.execute_run(run.id)  # la tarea entra despues de la cancelacion
    db.expire_all()
    run = db.get(BacktestRun, run.id)

    assert run.status == BacktestRunStatus.CANCELLED.value
    assert run.total_trades == 0, "no debe simular nada"
    assert _contar(db, run.id)["trades"] == 0
    assert _contar(db, run.id)["equity"] == 0


def test_no_cancela_un_run_inexistente(service):
    assert service.cancel_run(uuid.uuid4()) is False


def test_requeue_deja_el_run_limpio_para_volver_a_correr(db, service, scan_job):
    """Un run relanzado no debe luzca como si ya tuviera resultados mientras
    corre: los contadores de cabecera se ponen a cero."""
    run = crear(db, service, scan_job, strategy=BacktestStrategyIn(max_hold=6))
    service.execute_run(run.id)
    db.expire_all()
    assert db.get(BacktestRun, run.id).total_trades > 0

    run.status = BacktestRunStatus.FAILED.value
    db.commit()
    assert service.requeue_run(run.id) is True

    db.expire_all()
    run = db.get(BacktestRun, run.id)
    assert run.status == BacktestRunStatus.PENDING.value
    assert run.total_trades == 0
    assert run.equity_final is None
    assert run.net_pnl is None
    assert run.win_rate is None
    assert run.error_message is None
    assert run.strategy["max_hold"] == 6, "la configuracion congelada sobrevive"


def test_requeue_borra_los_resultados_anteriores_y_no_solo_los_contadores(
    db, service, scan_job
):
    """Poner los contadores a cero no basta: las filas tambien se van.

    Si no se borran, al volver a ejecutar el run cada operacion se insertaria
    dos veces (la curva de equity tambien) y el ``total_trades`` de la cabecera
    no cuadraria con la tabla. Y si el reenviado no llegara a ejecutarse, la
    cabecera a cero conviviria con unas operaciones viejas en la tabla.
    """
    run = crear(db, service, scan_job, strategy=BacktestStrategyIn(max_hold=6))
    service.execute_run(run.id)
    db.expire_all()
    assert _contar(db, run.id)["trades"] > 0
    assert _contar(db, run.id)["equity"] > 0

    run.status = BacktestRunStatus.FAILED.value
    db.commit()
    assert service.requeue_run(run.id) is True

    assert _contar(db, run.id) == {
        "runs": 1,
        "trades": 0,
        "equity": 0,
        "logs": 1,  # solo queda el log del propio requeue
    }

    # Y al reejecutar no se duplica nada: cuatro operaciones, no ocho.
    service.execute_run(run.id)
    db.expire_all()
    run = db.get(BacktestRun, run.id)
    assert run.status == BacktestRunStatus.COMPLETED.value
    assert run.total_trades == 4
    assert _contar(db, run.id)["trades"] == 4
    assert _contar(db, run.id)["equity"] == 60


def test_no_hay_requeue_de_un_run_completado(db, service, scan_job):
    run = crear(db, service, scan_job)
    run.status = BacktestRunStatus.COMPLETED.value
    db.commit()

    assert service.requeue_run(run.id) is False


# ---------------------------------------------------------------------------
# Borrado en cascada
# ---------------------------------------------------------------------------
def test_borrar_el_run_arrastra_operaciones_equity_y_logs(db, service, scan_job):
    run = crear(db, service, scan_job, strategy=BacktestStrategyIn(max_hold=6))
    service.execute_run(run.id)
    _contar(db, run.id)
    assert _contar(db, run.id)["trades"] > 0

    assert service.delete_run(run.id) is True

    leftovers = _contar(db, run.id)
    assert leftovers == {"runs": 0, "trades": 0, "equity": 0, "logs": 0}


def test_borrar_el_escaneo_arrastra_sus_runs(db, service, scan_job):
    """La cadena completa: escaneo -> run -> operaciones/equity/logs.

    Es lo que hace el DELETE de un scan de patterns, y por eso el borrado del
    dataset de referencia limpio sus 2.812 ocurrencias y cualquier backtest
    hecho sobre ellas.
    """
    run = crear(db, service, scan_job, strategy=BacktestStrategyIn(max_hold=6))
    service.execute_run(run.id)
    run_id = run.id

    db.delete(scan_job)
    db.commit()
    db.expire_all()

    # Sin ``expire_all``, ``db.get`` devolveria la copia que el ORM tiene
    # cacheada del run y el borrado en cascada pareceria no haber ocurrido:
    # el servicio borra en su propia sesion, asi que la de aqui nunca se
    # entera. ``_contar`` va con SQL directo y por eso si lo ve.
    assert db.get(BacktestRun, run_id) is None
    assert _contar(db, run_id) == {"runs": 0, "trades": 0, "equity": 0, "logs": 0}


def test_borrado_por_lotes(db, service, scan_job):
    runs = [
        crear(db, service, scan_job, strategy=BacktestStrategyIn(max_hold=6))
        for _ in range(3)
    ]
    for run in runs:
        service.execute_run(run.id)

    borrados = service.delete_runs(db, [run.id for run in runs])
    assert borrados == 3
    for run in runs:
        assert _contar(db, run.id)["runs"] == 0


def test_borrar_un_run_inexistente(service):
    assert service.delete_run(uuid.uuid4()) is False


# ---------------------------------------------------------------------------
# Consulta y filtros
# ---------------------------------------------------------------------------
@pytest.fixture
def run_con_operaciones(db, service, scan_job):
    run = crear(db, service, scan_job, strategy=BacktestStrategyIn(max_hold=6))
    service.execute_run(run.id)
    db.expire_all()
    return db.get(BacktestRun, run.id)


def test_filtra_operaciones_por_patron(db, service, run_con_operaciones):
    todos, total, _ = service.get_run_trades(db, run_con_operaciones.id)
    un_patron = sorted({t.pattern_name for t in todos})[0]

    filtrados, total_filtrado, net_filtrado = service.get_run_trades(
        db, run_con_operaciones.id, RunFilters(patterns=(un_patron,))
    )

    assert total_filtrado < total, "el fixture tiene 4 patrones distintos"
    assert {t.pattern_name for t in filtrados} == {un_patron}
    assert net_filtrado is not None


def test_filtra_operaciones_por_direccion(db, service, run_con_operaciones):
    _, _, _ = service.get_run_trades(db, run_con_operaciones.id)
    largos, total_largos, _ = service.get_run_trades(
        db, run_con_operaciones.id, RunFilters(directions=("long",))
    )
    cortos, total_cortos, _ = service.get_run_trades(
        db, run_con_operaciones.id, RunFilters(directions=("short",))
    )

    assert total_largos + total_cortos == run_con_operaciones.total_trades
    assert {t.direction for t in largos} <= {"long"}
    assert {t.direction for t in cortos} <= {"short"}


def test_filtra_operaciones_por_motivo_de_salida(db, service, run_con_operaciones):
    _, _, _ = service.get_run_trades(
        db, run_con_operaciones.id, RunFilters(exit_reasons=("timeout",))
    )
    timeouts, total, _ = service.get_run_trades(
        db, run_con_operaciones.id, RunFilters(exit_reasons=("timeout",))
    )
    todos, _, _ = service.get_run_trades(db, run_con_operaciones.id)

    assert total <= run_con_operaciones.total_trades
    assert {t.exit_reason for t in timeouts} <= {"timeout"}
    assert len(todos) <= 50


def test_el_pnl_del_filtro_cubre_todo_el_subconjunto_no_solo_la_pagina(
    db, service, run_con_operaciones
):
    """Sin esto, filtrar y mirar la ultima pagina daria un PnL que no cuadra
    con la tarjeta de resumen."""
    patron = sorted(
        {t.pattern_name for t in service.get_run_trades(db, run_con_operaciones.id)[0]}
    )[0]

    _, total, net_subconjunto = service.get_run_trades(
        db, run_con_operaciones.id, RunFilters(patterns=(patron,))
    )
    _, _, net_de_la_pagina = service.get_run_trades(
        db,
        run_con_operaciones.id,
        RunFilters(patterns=(patron,)),
        page_size=1,
    )

    assert total == 1, "el fixture usa un patron por operacion"
    assert net_subconjunto is not None
    assert net_de_la_pagina == net_subconjunto, (
        "page_size=1 recorta las filas que devuelve, no la suma del filtro"
    )
    # El PnL filtrado es el de ese patron, no el de la cabecera: la cabecera
    # suma las cuatro operaciones. El desglose por patron tiene que contar la
    # misma historia que la tabla de operaciones.
    del_patron = next(
        b
        for b in service.get_trades_by_pattern(db, run_con_operaciones.id)
        if b.pattern_name == patron
    )
    assert float(net_subconjunto) == pytest.approx(float(del_patron.net_pnl), abs=1e-6)
    assert float(net_subconjunto) < 0, "el fixture pierde dinero"


def test_ordenacion_por_cualquier_columna_permitida(db, service, run_con_operaciones):
    for columna in ("entry_timestamp", "net_pnl", "return_pct", "bars_held", "mae"):
        for orden in ("asc", "desc"):
            trades, _, _ = service.get_run_trades(
                db,
                run_con_operaciones.id,
                RunFilters(sort_by=columna, sort_order=orden),
            )
            assert trades, f"{columna}/{orden} no devolvio nada"


def test_orden_invalido_se_rechaza(db, service, run_con_operaciones):
    with pytest.raises(ValueError, match="ordenación"):
        service.get_run_trades(
            db, run_con_operaciones.id, RunFilters(sort_by="net_pnl; DROP TABLE x")
        )


def test_desglose_por_patron(db, service, run_con_operaciones):
    desglose = service.get_trades_by_pattern(db, run_con_operaciones.id)

    assert desglose
    suma = sum(b.trades for b in desglose)
    assert suma == run_con_operaciones.total_trades
    for bloque in desglose:
        assert bloque.net_pnl is not None
        assert bloque.wins + bloque.losses <= bloque.trades, (
            "las perdedoras contadas no pueden superar el total"
        )
        if bloque.trades:
            assert bloque.win_rate is None or 0 <= bloque.win_rate <= 1


def test_desglose_por_motivo_de_salida(db, service, run_con_operaciones):
    """Se prueba por la via publica: el desglose de motivos es parte del resumen,
    asi que no hace falta llamar al metodo privado."""
    resumen = service.get_run_summary(db, run_con_operaciones.id)

    assert resumen.by_exit_reason
    assert sum(r.trades for r in resumen.by_exit_reason) == (
        run_con_operaciones.total_trades
    )


def test_submuestreo_de_equity_conserva_extremos_y_avisa(db, service, scan_job):
    """La serie se recorta para pintar, pero la respuesta dice cuantos puntos
    reales hay, para que la UI no finja que los enseña todos."""
    run = crear(db, service, scan_job, strategy=BacktestStrategyIn(max_hold=6))
    service.execute_run(run.id)
    db.expire_all()

    serie = service.get_run_equity(db, run.id, max_points=10)

    assert serie.total_points == 60
    assert serie.returned <= 12, "60 velas en 10 puntos serian 6, aqui debe recortar"
    assert serie.points[0].timestamp == INICIO, "el primer punto se conserva"
    assert serie.max_drawdown_pct is not None, "viene del run, no de la serie recortada"
    # El recorte es para pintar, no para decidir: el drawdown sigue siendo el
    # de todos los puntos, no el de los diez que se devuelven.
    assert float(serie.max_drawdown_pct) == pytest.approx(
        max(float(p.drawdown_pct) for p in serie.points), abs=1e-6
    )


def test_equity_de_un_run_inexistente(db, service):
    with pytest.raises(RunNotFound):
        service.get_run_equity(db, uuid.uuid4())


def test_escaneos_disponibles_solo_los_completados(db, service, scan_job):
    disponibles = service.get_available_scans(db)
    assert [s["id"] for s in disponibles] == [scan_job.id]
    assert disponibles[0]["total_occurrences"] == 4
    assert disponibles[0]["total_candles"] == 60

    scan_job.status = "processing"
    db.commit()
    assert service.get_available_scans(db) == []


def _contar(db, run_id: uuid.UUID) -> dict[str, int]:
    """Filas de las cuatro tablas de un run, para comprobar la cascada."""
    from app.modules.backtesting.models import (
        BacktestEquityPoint,
        BacktestLog,
        BacktestTrade,
    )
    from sqlalchemy import func, select

    def cuenta(modelo) -> int:
        return (
            db.scalar(
                select(func.count()).select_from(modelo).where(modelo.run_id == run_id)
            )
            or 0
        )

    return {
        "runs": db.scalar(
            select(func.count())
            .select_from(BacktestRun)
            .where(BacktestRun.id == run_id)
        )
        or 0,
        "trades": cuenta(BacktestTrade),
        "equity": cuenta(BacktestEquityPoint),
        "logs": cuenta(BacktestLog),
    }


# ---------------------------------------------------------------------------
# Bordes de la tarea y de la persistencia
# ---------------------------------------------------------------------------
def test_ejecutar_un_run_inexistente_no_deja_la_tarea_rota(service, db_schema):
    """Un run borrado mientras la tarea esperaba en la cola no debe tumbar al
    worker de Celery.

    Antes, el manejador de errores intentaba registrar el fallo en
    ``backtest_logs`` para un run que ya no existia, la FK lo rechazaba y esa
    excepcion tapaba la original: el worker moria con un error de integridad
    en lugar de "el run no existe".

    Pide ``db_schema`` para tener el esquema delante: sin el, ``execute_run``
    falla antes por una tabla inexistente y el test pasaria sin llegar a
    comprobar lo que dice comprobar.
    """
    service.execute_run(uuid.uuid4())  # no debe levantar


def test_cancelar_a_mitad_de_escribir_deja_el_run_cancelado(db, service, scan_job):
    """Si se cancela mientras se escriben los resultados, no se marca completado.

    Reproduce la ventana real: la equity ya esta escrita, ``_finish_run`` esta
    a punto de cerrar el run y el usuario cancela. Cerrarlo como ``completed``
    diria que la simulacion termino bien cuando en realidad se paro a medias.
    Se cancela desde dentro de ``_save_equity``, que es justo el instante
    anterior a ``_finish_run``.
    """
    run = crear(db, service, scan_job, strategy=BacktestStrategyIn(max_hold=6))
    original = service._save_equity

    def cancelar_antes_de_cerrar(run_id, result):
        puntos = original(run_id, result)
        service.cancel_run(run_id)  # el usuario cancela aqui
        return puntos

    service._save_equity = cancelar_antes_de_cerrar
    try:
        service.execute_run(run.id)
    finally:
        del service._save_equity

    db.expire_all()
    run = db.get(BacktestRun, run.id)

    assert run.status == BacktestRunStatus.CANCELLED.value
    # ``cancel_run`` si fija ``finished_at``: el run dejo de correr a esa hora.
    # Lo que tiene que seguir vacio son las metricas, porque se escriben en
    # ``_finish_run``, que es justo lo que la cancelacion impidio.
    assert run.net_pnl is None, "_finish_run no debio cerrar el run"
    assert run.total_trades == 0
    assert _contar(db, run.id)["equity"] == 60, "la equity ya escrita se conserva"
