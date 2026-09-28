"""Tests de la capa de grafico: muestreo y cobertura de indicadores.

Dos bloques con proposito distinto:

1. **Tests puros de ``sampling_plan``**: no tocan base de datos ni pandas, y
   comprueban el plan de muestreo vela a vela. Es la parte del grafico que se
   puede probar sin DOM y cuyo fallo es **silencioso**: un paso mal calculado no
   lanza nada, solo enseña otro rango del que el usuario pidió, y eso no se ve
   hasta que alguien cuenta las velas.

2. **Tests de la ruta con PostgreSQL**: comprueban que los indicadores ausentes
   se **declaran** en vez de descartarse, y que los markers de un escaneo no
   incluyen detecciones de otros escaneos del mismo rango.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from app.modules.data_import.models import Candle
from app.modules.features.models import Feature
from app.modules.patterns.models import (
    PatternOccurrence,
    PatternScanJob,
    PatternScanJobStatus,
)
from app.modules.patterns.schemas import ChartDataOut
from app.modules.patterns.service import PatternScanService, sampling_plan

INICIO = datetime(2022, 1, 1, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Muestreo
# ---------------------------------------------------------------------------
def test_sin_tope_no_se_muestrea_nada():
    paso, indices = sampling_plan(10, None)

    assert paso == 1
    assert indices == list(range(10))


def test_tope_mayor_que_el_rango_no_muestrea():
    paso, indices = sampling_plan(10, 100)

    assert paso == 1
    assert len(indices) == 10


def test_el_paso_se_calcula_redondeando_hacia_arriba():
    """4344 velas con tope 1500 dan paso 3, que son 1448 velas, y al añadir la
    ultima 1449: cabe de sobra. Redondear hacia abajo (2) devolveria 2172
    velas, el doble de lo pedido."""
    paso, indices = sampling_plan(4344, 1500)

    assert paso == 3
    assert len(indices) == 1449
    assert len(indices) <= 1500


def test_el_tope_se_cumple_aunque_haya_que_anadir_la_ultima():
    """Regresion: con el calculo ingenuo (paso sobre ``max_points``) este caso
    devolvia 4 velas con un tope de 3, y el parametro que se llama
    ``max_points`` devolvia mas de lo pedido."""
    for total, tope in [(10, 3), (11, 3), (100, 4), (7, 2), (1000, 7)]:
        _, indices = sampling_plan(total, tope)
        assert len(indices) <= tope, (total, tope, len(indices))


def test_la_ultima_vela_se_conserva_siempre():
    """El descuido que ya se corrigio una vez en la curva de equity: al muestrear
    por paso constante, el final cae dentro del hueco del último paso.

    Con 4344 velas y paso 3 los índices conservados son 0, 3, 6 ... 4341. La vela
    4343 **no** sale del filtro, asi que hay que añadirla: sin esto el grafico no
    llegaria al cierre del rango.
    """
    total = 4344
    paso, indices = sampling_plan(total, 1500)

    assert indices[-1] == total - 1, "la ultima vela es la del final del rango"
    assert total - 2 not in indices, "la penultima no entra: el paso la salta"
    assert indices[0] == 0, "la primera vela se conserva siempre"
    # Todos los huecos son del paso menos el último, que es mas corto porque la
    # vela final se añade aparte para no perder el cierre del rango.
    for anterior, siguiente in zip(indices, indices[1:], strict=False):
        assert siguiente - anterior <= paso


def test_la_ultima_no_se_duplica_cuando_cae_en_el_paso():
    """Un rango cuya longitud es multiplo del paso ya termina en el ultimo
    paso. Añadir la última a ciegas metería el mismo índice dos veces y
    lightweight-charts recibiría una serie con velas repetidas."""
    paso, indices = sampling_plan(12, 4)

    # Con paso 3 los indices conservados son 0, 3, 6 y 9: la vela 11 no sale del
    # filtro y se anade al final. Sin paso 4, pasarian 4 velas de las 4 pedidas.
    assert paso == 4
    assert indices == [0, 4, 8, 11]
    assert len(indices) == len(set(indices)), "sin indices repetidos"


def test_rango_vacio():
    paso, indices = sampling_plan(0, 1500)

    assert paso == 1
    assert indices == []


def test_el_invariante_se_cumple_en_todos_los_rangos():
    """El invariante que de verdad importa: nunca mas velas de las pedidas, y
    nunca menos de dos (primera y última)."""
    for total, tope in [(10, 3), (100, 7), (8760, 1500), (200, 200), (5000, 10)]:
        paso, indices = sampling_plan(total, tope)
        assert len(indices) <= max(tope, 2), (total, tope)
        assert indices[0] == 0
        assert indices[-1] == total - 1
        assert paso >= 1


# ---------------------------------------------------------------------------
# Cobertura e indicadores ausentes
# ---------------------------------------------------------------------------
@pytest.fixture
def datos_para_grafico(db):
    """40 velas, dos indicadores calculados y velas de sobra para muestrear.

    Se cubre a proposito el caso que produce la base real: ``EMA_50`` existe
    para BTCUSDT pero solo desde 2026, asi que pedirlo en un rango de 2022
    devuelve una serie vacia. El contrato es que eso se **declare**, no que
    desaparezca.
    """
    for offset in range(40):
        base = 100.0 + offset
        db.add(
            Candle(
                timestamp=INICIO + timedelta(hours=offset),
                symbol="TESTUSDT",
                timeframe="1h",
                open=base,
                high=base + 1,
                low=base - 1,
                close=base + 0.5,
                volume=10.0,
            )
        )

    job = PatternScanJob(
        symbol="TESTUSDT",
        timeframe="1h",
        date_from=INICIO,
        date_to=INICIO + timedelta(hours=39),
        status=PatternScanJobStatus.COMPLETED.value,
        total_candles=40,
        processed_candles=40,
    )
    db.add(job)
    db.flush()

    for nombre, offset in (("EMA_20", 0.1), ("RSI_14", 0.2)):
        for index in range(40):
            db.add(
                Feature(
                    timestamp=INICIO + timedelta(hours=index),
                    symbol="TESTUSDT",
                    timeframe="1h",
                    indicator_name=nombre,
                    indicator_params={"length": 20},
                    value=100 + offset * index,
                )
            )

    for index in range(6):
        db.add(
            PatternOccurrence(
                timestamp=INICIO + timedelta(hours=index * 5),
                symbol="TESTUSDT",
                timeframe="1h",
                pattern_name="MACD_CROSS_BULLISH",
                scan_job_id=job.id,
                details={"direction": "bullish"},
            )
        )
    db.commit()
    return job


def test_los_indicadores_presentes_vienen_como_series(db, datos_para_grafico):
    datos = PatternScanService().get_chart_data(
        symbol="TESTUSDT",
        timeframe="1h",
        date_from=INICIO,
        date_to=INICIO + timedelta(hours=39),
        feature_names=["EMA_20", "RSI_14"],
    )

    assert set(datos["indicators"]) == {"EMA_20", "RSI_14"}
    assert len(datos["indicators"]["EMA_20"]) == 40
    assert datos["missing_indicators"] == []


def test_un_indicador_inexistente_se_declara_y_no_se_inventa(db, datos_para_grafico):
    """El caso que motiva el campo. Sin el, un ``EMA_50`` pedido en 2022
    desapareceria del grafico y el usuario concluiria que no esta implementado,
    cuando lo que pasa es que no se ha calculado para ese rango."""
    datos = PatternScanService().get_chart_data(
        symbol="TESTUSDT",
        timeframe="1h",
        date_from=INICIO,
        date_to=INICIO + timedelta(hours=39),
        feature_names=["EMA_20", "EMA_50"],
    )

    assert "EMA_50" not in datos["indicators"]
    assert "EMA_20" in datos["indicators"], "uno que falta no puede tumbar al otro"
    assert datos["missing_indicators"] == ["EMA_50"]


def test_sin_features_no_hay_ausentes_que_declarar(db, datos_para_grafico):
    """Poder pedir solo velas es un caso real: el explorador sin indicadores
    superpuestos tiene que funcionar, y no debe reportar nada como ausente si no
    se pidió nada."""
    datos = PatternScanService().get_chart_data(
        symbol="TESTUSDT",
        timeframe="1h",
        date_from=INICIO,
        date_to=INICIO + timedelta(hours=39),
    )

    assert datos["indicators"] == {}
    assert datos["missing_indicators"] == []


def test_los_indicadores_siguen_exactamente_las_timestamps_de_las_velas(
    db, datos_para_grafico
):
    """La razon por la que `_load_features_pivot` acepta `only_timestamps`.

    Si los indicadores se filtran aparte del muestreo, el overlay se ancla a
    velas que no estan en pantalla: el grafico parece correcto y no lo esta. Con
    paso 2 sobre 40 velas se pintan 20, y el indicador tiene que traer 20 puntos
    con las mismas 20 marcas de tiempo.
    """
    datos = PatternScanService().get_chart_data(
        symbol="TESTUSDT",
        timeframe="1h",
        date_from=INICIO,
        date_to=INICIO + timedelta(hours=39),
        feature_names=["EMA_20"],
        max_points=20,
    )

    assert datos["sampled"] is True
    assert datos["total_points"] == 40
    assert datos["returned"] == len(datos["candles"])
    assert datos["returned"] < 40, "con tope 20 sobre 40 velas hay que muestrear"
    assert datos["step"] >= 2

    velas = {candle["timestamp"] for candle in datos["candles"]}
    serie = {punto["timestamp"] for punto in datos["indicators"]["EMA_20"]}
    assert serie == velas, "cada punto del indicador cae en una vela mostrada"


def test_sin_scan_no_hay_markers(db, datos_para_grafico):
    """No se puede marcar lo que no se ha escaneado. Y si se marcara el rango
    entero, el grafico de un escaneo contendria detecciones de otros."""
    datos = PatternScanService().get_chart_data(
        symbol="TESTUSDT",
        timeframe="1h",
        date_from=INICIO,
        date_to=INICIO + timedelta(hours=39),
    )

    assert datos["markers"] == []


def test_con_scan_solo_salen_sus_detecciones(db, datos_para_grafico):
    """Regresion del cambio de comportamiento: antes la ruta de escaneo pedia
    ocurrencias por simbolo y rango **sin** filtrar por job, y marcaba en el
    grafico de un escaneo las detecciones de todos los demas del rango. El
    grafico y la tabla de al lado contaban cosas distintas."""
    otro = PatternScanJob(
        symbol="TESTUSDT",
        timeframe="1h",
        date_from=INICIO,
        date_to=INICIO + timedelta(hours=39),
        status=PatternScanJobStatus.COMPLETED.value,
        total_candles=40,
        processed_candles=40,
    )
    db.add(otro)
    db.flush()
    for index in range(3):
        db.add(
            PatternOccurrence(
                timestamp=INICIO + timedelta(hours=index),
                symbol="TESTUSDT",
                timeframe="1h",
                pattern_name="ENGULFING_BULLISH",
                scan_job_id=otro.id,
                details={"direction": "bullish"},
            )
        )
    db.commit()

    del_escaneo = PatternScanService().get_chart_data(
        symbol="TESTUSDT",
        timeframe="1h",
        date_from=INICIO,
        date_to=INICIO + timedelta(hours=39),
        scan_job_id=datos_para_grafico.id,
    )

    assert len(del_escaneo["markers"]) == 6
    assert {m["pattern_name"] for m in del_escaneo["markers"]} == {"MACD_CROSS_BULLISH"}


def test_el_mapeo_de_markers_lo_decide_el_backend(db, datos_para_grafico):
    """Bullish abajo y en verde. Que lo decida el backend y no el cliente es lo
    que hace que cambiar el color se aplique a todas las pantallas: duplicar
    este mapeo en el frontend es la forma de que la mitad cambien y la otra
    mitad no."""
    datos = PatternScanService().get_chart_data(
        symbol="TESTUSDT",
        timeframe="1h",
        date_from=INICIO,
        date_to=INICIO + timedelta(hours=39),
        scan_job_id=datos_para_grafico.id,
    )

    marker = datos["markers"][0]
    assert marker["position"] == "belowBar"
    assert marker["shape"] == "arrowUp"
    assert marker["color"].startswith("#")


def test_pedir_un_indicador_sin_calcular_no_impide_ver_las_detecciones(
    db, datos_para_grafico
):
    """Un escaneo puede existir sin las features de las que dependen sus
    patrones. El grafico tiene que salir: menos lineas, no un error."""
    datos = PatternScanService().get_chart_data(
        symbol="TESTUSDT",
        timeframe="1h",
        date_from=INICIO,
        date_to=INICIO + timedelta(hours=39),
        feature_names=["NO_EXISTE_99"],
        scan_job_id=datos_para_grafico.id,
    )

    assert datos["indicators"] == {}
    assert datos["missing_indicators"] == ["NO_EXISTE_99"]
    assert len(datos["markers"]) == 6


# ---------------------------------------------------------------------------
# Contrato de la respuesta
# ---------------------------------------------------------------------------
def test_la_respuesta_cumple_el_contrato_declarado(db, datos_para_grafico):
    """Lo que devuelve el router tiene que validar contra el modelo, no contra
    lo que el cliente espera. Antes de declarar `response_model` el unico
    contrato era el tipo del frontend, y cualquier clave nueva era invisible
    para quien documenta la API."""
    datos = PatternScanService().get_chart_data(
        symbol="TESTUSDT",
        timeframe="1h",
        date_from=INICIO,
        date_to=INICIO + timedelta(hours=39),
        feature_names=["EMA_20"],
        scan_job_id=datos_para_grafico.id,
    )

    contrato = ChartDataOut(**datos)

    assert contrato.symbol == "TESTUSDT"
    assert contrato.returned == contrato.total_points
    assert contrato.step == 1
    assert contrato.sampled is False
    assert contrato.missing_indicators == []
    assert contrato.markers[0].pattern_name == "MACD_CROSS_BULLISH"


def test_un_rango_sin_velas_devuelve_grafico_vacio_y_no_500(db):
    """Regresion: leer `candles["open"]` sobre un frame sin columnas lanza
    `KeyError`. El explorador pregunta por cualquier ventana, incluida una que no
    este importada, y eso tiene que ser un grafico vacio."""
    datos = PatternScanService().get_chart_data(
        symbol="TESTUSDT",
        timeframe="1h",
        date_from=INICIO + timedelta(days=365),
        date_to=INICIO + timedelta(days=400),
        feature_names=["EMA_20"],
    )

    assert datos["candles"] == []
    assert datos["total_points"] == 0
    assert datos["indicators"] == {}
    assert datos["missing_indicators"] == ["EMA_20"]


def test_escaneo_inexistente_no_inventa_markers(db, datos_para_grafico):
    """Un id de escaneo que no existe no es un error del chart: simplemente no
    hay nada que marcar. La ruta resuelve el 404 antes; aqui se comprueba que el
    servicio no fabrica detecciones."""
    datos = PatternScanService().get_chart_data(
        symbol="TESTUSDT",
        timeframe="1h",
        date_from=INICIO,
        date_to=INICIO + timedelta(hours=39),
        scan_job_id=uuid.uuid4(),
    )

    assert datos["markers"] == []
    assert len(datos["candles"]) == 40
