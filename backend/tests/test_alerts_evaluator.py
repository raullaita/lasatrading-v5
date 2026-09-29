"""Tests del evaluador de alertas.

El test que importa es `test_las_dos_rutas_dan_exactamente_lo_mismo`, y es la
razón de que este módulo exista en la forma que tiene.

Un patrón se detecta sobre features. Si la alerta calcula las features por su
cuenta y el job de features las calcula de otra manera —aunque las dos cosas se
llamen RSI— el aviso sale de una cuenta que el backtest nunca corrió, y eso no se
ve en ningún sitio: el aviso llega, el número es plausible, y es falso. Por eso
las dos rutas usan el **mismo** método, y por eso hay un test que lo comprueba
contra el rango completo en vez de contra una fórmula.

El warmup de 1.000 velas no es un número redondo: sale de medir, y el propio
test es el que lo fijaría a la baja si bajara.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest
from app.core.database import SessionLocal
from app.modules.alerts.evaluator import (
    WARMUP_VELAS,
    _requeridas,
    _ruta_para,
    evaluar_regla,
    velas_recientes,
)
from app.modules.alerts.models import AlertPatternCoverage, AlertVerdict
from app.modules.data_import.models import Candle
from app.modules.features.service import FeatureService


@contextmanager
def _sesion():
    with SessionLocal() as db:
        yield db


pytestmark = pytest.mark.usefixtures("db")

INICIO = datetime(2022, 1, 1, tzinfo=timezone.utc)
DIAS = 120
VECES = 24


@pytest.fixture
def mercado(db):
    """Velas de 1h con recorrido, para un símbolo de prueba."""
    generador = np.random.default_rng(11)
    pasos = generador.normal(0, 0.4, DIAS * VECES)
    cierres = 100.0 + np.cumsum(pasos)
    for i in range(DIAS * VECES):
        base = float(cierres[i])
        db.add(
            Candle(
                timestamp=INICIO + timedelta(hours=i),
                symbol="TESTUSDT",
                timeframe="1h",
                open=base,
                high=base * 1.004,
                low=base * 0.996,
                close=base,
                volume=10.0,
            )
        )
    db.commit()
    return INICIO + timedelta(hours=DIAS * VECES - 1)


def _marco_completo(mercado: datetime) -> pd.DataFrame:
    from app.modules.data.candles import load_candles

    return load_candles("TESTUSDT", "1h", INICIO, mercado + timedelta(hours=1))


def _regla(**extra):
    from app.modules.alerts.models import AlertRule

    base = dict(
        name="evaluada",
        symbol="TESTUSDT",
        timeframe="1h",
        pattern_name="MACD_CROSS_BULLISH",
        direction="bullish",
        config={"stop_loss_pct": 1.5, "max_hold": 24, "base_known": False},
        validation_status=AlertVerdict.SIN_EVALUAR.value,
        pattern_coverage=AlertPatternCoverage.SIN_INFORME.value,
        backing_created_at=datetime.now(timezone.utc),
    )
    base.update(extra)
    return AlertRule(**base)


# ---------------------------------------------------------------------------
# La garantía central
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "patron", ["MACD_CROSS_BULLISH", "RSI_EXIT_OVERSOLD", "MA_CROSS_BEARISH"]
)
def test_las_dos_rutas_dan_exactamente_lo_mismo(db, mercado, patron):
    """La ruta al vuelo tiene que dar los **mismos bits** que el rango completo.

    No "casi iguales" ni "iguales con tolerancia": exactamente iguales. La
    diferencia medida con 200 velas de warmup era de 2,5e-4 en el RSI, y eso
    basta para que un cruce aparezca o desaparezca, es decir, para que el sistema
    avise de una señal que no existe o calle una que sí.

    Se compara sobre la ventana reciente, que es donde se decide si avisa. Antes
    de esa zona las diferencias de warmup son grandes por definición —ahí es donde
    la recursión aún no ha salido del estado inicial— y no importan, porque una
    detección antigua ya habría salido en una evaluación anterior.
    """
    patron_definicion = _requeridas(patron)
    assert patron_definicion, "el patrón no exige features y el test no probaría nada"

    completo = _marco_completo(mercado)
    servicio = FeatureService()
    paso_min = 60
    ventana_reciente = velas_recientes("1h", 300.0)
    desde = mercado - pd.Timedelta(minutes=paso_min * ventana_reciente)

    for nombre in patron_definicion:
        indicador, params = _nombre_a_indicador(nombre)
        serie_completa = servicio._calculate_indicator(completo, indicador, params)[
            nombre
        ]
        # La ruta de vuelo: los mismos ultimos WARMUP_VELAS minutos.
        ventana = completo.tail(WARMUP_VELAS + ventana_reciente)
        serie_vuelo = servicio._calculate_indicator(ventana, indicador, params)[nombre]
        reciente_completa = serie_completa.loc[serie_completa.index >= desde]
        reciente_vuelo = serie_vuelo.reindex(reciente_completa.index)
        diferencia = (reciente_completa - reciente_vuelo).abs().max()
        assert diferencia == 0.0, (
            f"{nombre} difiere {diferencia} entre la ruta al vuelo y la completa; "
            f"con {WARMUP_VELAS} de warmup debería dar exactamente lo mismo"
        )


def _nombre_a_indicador(nombre: str) -> tuple[str, dict]:
    from app.modules.alerts.evaluator import _indicador_de

    return _indicador_de(nombre)


def test_el_warmup_esta_justificado_y_no_es_redondeo(db, mercado):
    """Con menos warmup las dos rutas **no** coinciden, y ese es el motivo de que
    el número sea 1.000 y no «unas cuantas».

    Si algún día el cálculo del motor cambia y 1.000 pasa a ser suficiente de
    sobra, este test no falla: sigue dando cero. Lo que falla es el
    intermedio, y por eso se comprueba explícitamente que 200 no basta.
    """
    completo = _marco_completo(mercado)
    servicio = FeatureService()
    nombre = _requeridas("RSI_EXIT_OVERSOLD")[0]
    indicador, params = _nombre_a_indicador(nombre)
    ventana_reciente = velas_recientes("1h", 300.0)
    desde = mercado - pd.Timedelta(minutes=60 * ventana_reciente)

    serie_completa = servicio._calculate_indicator(completo, indicador, params)[nombre]
    reciente_completa = serie_completa.loc[serie_completa.index >= desde]

    corto = completo.tail(200 + ventana_reciente)
    serie_corta = servicio._calculate_indicator(corto, indicador, params)[nombre]
    diferencia = (
        (reciente_completa - serie_corta.reindex(reciente_completa.index)).abs().max()
    )

    assert diferencia > 0, (
        "200 velas de warmup ya dan lo mismo: WARMUP_VELAS está "
        "sobredimensionado y se puede bajar"
    )


def test_la_ruta_de_vuelo_calcula_todas_las_features_requeridas(db, mercado):
    """Si falta una columna, el scanner devuelve cero detecciones y el sistema
    parece roto sin que nada diga por qué. Mejor que falle aquí."""
    with _sesion() as db:
        marco, ruta = _ruta_para(
            db, "TESTUSDT", "1h", pd.Timestamp(mercado), "RSI_EXIT_OVERSOLD"
        )
    assert ruta == "vuelo", "sin job de features la ruta debe ser la de vuelo"
    for nombre in _requeridas("RSI_EXIT_OVERSOLD"):
        assert nombre in marco.columns, f"falta {nombre} en el marco"
        assert not marco[nombre].tail(2).isna().any(), (
            f"{nombre} viene con NaN en las velas recientes: el detector no podría "
            "decidir nada y no avisaría de por qué"
        )


# ---------------------------------------------------------------------------
# El evaluador
# ---------------------------------------------------------------------------
def test_sin_velas_devuelve_motivo_y_no_explota(db):
    evaluacion = evaluar_regla(db, _regla(symbol="NOEXISTE", timeframe="1h"))
    assert evaluacion.detections == ()
    assert "No hay velas" in evaluacion.motivo
    assert evaluacion.velas == 0


def test_un_patron_fuera_del_catalogo_no_revienta(db, mercado):
    evaluacion = evaluar_regla(db, _regla(pattern_name="NO_EXISTE"))
    assert evaluacion.detections == ()
    assert evaluacion.motivo != ""


def test_sin_detecciones_devuelve_el_motivo_no_un_vacio(db, mercado):
    """Una regla que no ha saltado y una que no se ha mirado se ven igual si el
    motivo va vacío. Es la diferencia entre «no ha pasado nada» y «no sé»."""
    evaluacion = evaluar_regla(db, _regla())
    assert evaluacion.detections == ()
    assert evaluacion.motivo, "toda evaluación lleva motivo, aunque no detecte"
    assert evaluacion.velas > WARMUP_VELAS * 0.9, "el marco trae el warmup entero"


def test_la_evaluacion_siempre_devuelve_la_ruta(db, mercado):
    """La ruta tiene que quedar anotada: un aviso que salió de la ruta de
    emergencia es un aviso sobre datos aproximados, y hay que poder verlo."""
    evaluacion = evaluar_regla(db, _regla())
    assert evaluacion.ruta in {"cache", "vuelo", "error", "ninguna"}


# ---------------------------------------------------------------------------
# La deduplicación, que es de la base pero se comprueba desde aquí
# ---------------------------------------------------------------------------
def test_toda_feature_del_catalogo_se_puede_reconstruir():
    """El parser tiene que cubrir **todo** el catálogo, no lo que hoy se usa.

    Si un patrón nuevo trae una feature que el evaluador no sabe reconstruir, el
    evaluador lanza, la regla no detecta nada, y el motivo dice «no se pudo
    construir el marco» sin decir que el problema es una tabla de nombres
    desactualizada. Este test falla el día que se añade el patrón, que es cuando
    es barato.
    """
    from app.modules.alerts.evaluator import _indicador_de, _params_por_defecto
    from app.modules.features.service import FeatureService
    from app.modules.patterns import pattern_catalog as catalog

    incompletos = []
    for codigo in catalog.PATTERN_CATALOG:
        requeridas = catalog.required_features_for(
            [codigo], {codigo: _params_por_defecto(codigo)}
        )
        for nombre in requeridas:
            try:
                indicador, params = _indicador_de(nombre)
            except ValueError:
                incompletos.append(f"{codigo}: {nombre}")
                continue
            # Y que el indicador exista de verdad y emita esa columna.
            marco = pd.DataFrame(
                {
                    "open": [100.0] * 60,
                    "high": [101.0] * 60,
                    "low": [99.0] * 60,
                    "close": [100.0 + i * 0.1 for i in range(60)],
                    "volume": [10.0] * 60,
                }
            )
            salida = FeatureService()._calculate_indicator(marco, indicador, params)
            if nombre not in salida:
                incompletos.append(f"{codigo}: {nombre} (no la emite {indicador})")

    assert not incompletos, (
        "el evaluador no sabe reconstruir estas features del catálogo:\n  "
        + "\n  ".join(incompletos)
    )


# ---------------------------------------------------------------------------
# La ventana reciente, que es lo que decide si se pierde un aviso
# ---------------------------------------------------------------------------
def test_la_ventana_cubre_las_velas_que_pueden_cerrar_entre_pasadas():
    """El motivo de existir de ``velas_recientes``.

    Una detección vive en la vela que la contiene. Si el evaluador corre cada 15
    minutos y la vela es de 1 minuto, un cruce de las 10:00 ya se ha ido de la
    ventana cuando el evaluador mira a las 10:15, y el aviso no se envía nunca.
    No hay ningún error: simplemente no pasa nada, y un sistema de avisos
    callado parece uno que no tiene nada que decir.
    """
    from app.modules.alerts.evaluator import velas_recientes

    # Con velas de 1 minuto y 15 minutos entre pasada, pueden cerrarse 15 velas.
    assert velas_recientes("1m", 900) >= 15
    # Con velas de 1 minuto y 5 minutos, salen 6: 5 cerradas más una de margen.
    assert velas_recientes("1m", 300) == 6


def test_un_poll_mas_rapido_que_la_vela_no_multiplica_la_ventana():
    """Con velas de 1 hora y un evaluador cada 5 minutos solo puede cerrarse
    **una** vela entre medias, aunque entre dos pasadas quepan doce horas.

    Multiplicar por doce sería mirar medio día de velas para encontrar lo mismo,
    y cada poll redundante abriría una transacción que el índice único rechaza.
    """
    from app.modules.alerts.evaluator import velas_recientes

    assert velas_recientes("1h", 300) == 2
    assert velas_recientes("1d", 300) == 2


def test_la_ventana_nunca_baja_de_dos():
    """Dos es el suelo: una sola vela deja fuera el caso de que la detección caiga
    justo en la última, que es donde cae la mitad de las veces."""
    from app.modules.alerts.evaluator import velas_recientes

    for tf in ("1m", "15m", "1h", "4h", "1d"):
        assert velas_recientes(tf, 1) >= 2


def test_un_timeframe_desconocido_no_se_adivina():
    from app.modules.alerts.evaluator import velas_recientes

    with pytest.raises(ValueError):
        velas_recientes("7m", 300)
