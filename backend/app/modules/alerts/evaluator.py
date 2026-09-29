"""El evaluador: ¿ha pasado algo ahora que deba avisar?

Este es el bloque con más riesgo de la Tarea 6, y el riesgo tiene un nombre
concreto: **las features de la ruta al vuelo pueden no ser las mismas que las del
job**, y si no lo son la alerta dispara sobre datos que el backtest nunca vio.

## El problema, medido y no supuesto

`FeatureService._calculate_indicator` calcula EMA y RSI con `ewm(adjust=False)`,
que es **recursivo**: el valor de hoy depende de todos los anteriores. Calcularlo
sobre una ventana de 300 velas da un número distinto del que daría sobre 3.000,
porque la recursión no ha salido del estado inicial. Medido sobre BTCUSDT 1h,
comparando las 50 últimas velas —que es donde se decide si avisa—:

| Warmup | Diferencia máxima en RSI_14 |
| --- | --- |
| 200 velas | 2,5e-4 |
| 500 velas | ~1e-14, imprecisa en coma flotante |
| 1.000 velas | **0, exactamente** |

Con 200 de warmup la diferencia es de dos centésimas de punto de RSI, y eso basta
para que un cruce aparezca o desaparezca. Por eso `WARMUP_VELAS` son 1.000 y no
«las justas»: están medidas, no elegidas por gusto.

## Las dos rutas

- **Caché**: si el job de features más reciente para ese símbolo cubre las
  últimas velas, se leen de ahí. Son exactamente las filas que escribió el job, y
  por tanto exactamente las que el backtest vio.
- **Vuelo**: si no, se calculan sobre la ventana con warmup. Es la ruta correcta
  pero más cara, y se usa cuando la buena no existe.

Se prefiere la buena y se anota cuál se usó en `last_evaluation_note`. Un
evaluador que no dice por qué ruta fue no permite auditar por qué un aviso salió,
y sobre todo por qué **no** salió.

## Por qué se reutiliza el servicio de patrones

La detección se hace con `PatternService._build_plan` y `_run_step`, los mismos
métodos que usa un job de escaneo. No se llama al scanner a mano ni se
reimplementa la construcción del paso: la garantía de que la alerta vigila lo
mismo que el escaneo se sostiene en que **es el mismo código**, y esa es una
garantía que se pierde en cuanto hay dos llamadas al scanner en el repositorio.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.data.candles import load_candles
from app.modules.data_import.models import Candle
from app.modules.features.models import Feature
from app.modules.features.service import FeatureService
from app.modules.patterns import pattern_catalog as catalog
from app.modules.patterns.schemas import PatternSelection
from app.modules.patterns.service import PatternScanService

#: Velas de warmup. Medido, no elegido: es el mínimo con el que el RSI calculado
#: al vuelo coincide **bit a bit** con el calculado sobre el rango completo. Ver la
#: tabla del docstring del módulo.
WARMUP_VELAS = 1000

#: Mínimo de velas recientes, y el suelo de la fórmula de abajo.
#:
#: Dos son las justas para no perder nada en el caso normal, pero no bastan
#: siempre, y ese "no siempre" es el motivo de existir de esta constante.
VELAS_RECIENTES_MINIMO = 2

#: Margen sobre el que la caché se acepta como «fresca». Dos velas de 1h es una
#: hora, y el evaluador corre cada 5 minutos, así que una caché con dos velas de
#: retraso sigue siendo la buena ruta.
CACHE_TOLERANCIA_VELAS = 2


@dataclass(frozen=True, slots=True)
class Deteccion:
    """Un patrón detectado en vivo."""

    timestamp: pd.Timestamp
    pattern_name: str
    #: Cierre de la vela de la señal. **No es el precio de entrada**: la entrada es
    #: la apertura de T+1, que en el momento del aviso no ha ocurrido.
    reference_price: float
    ruta: str


def velas_recientes(timeframe: str, intervalo_s: float) -> int:
    """Cuántas velas hay que mirar para no perder nada entre dos evaluaciones.

    ## El problema que esto resuelve

    Una detección vive en la vela que la contiene. Si el evaluador corre cada 15
    minutos y la vela es de 1 minuto, un cruce de las 10:00 ya ha salido de la
    ventana cuando el evaluador mira a las 10:15, y **el aviso no se envía
    nunca**. No hay ningún error: simplemente no pasa nada, y un sistema de
    avisos callado parece uno que no tiene nada que decir.

    ## La fórmula

    Entre dos evaluaciones pueden haber cerrado ``intervalo / duracion_vela``
    velas como mucho, así que hay que mirar esa-many más una, y nunca menos de
    dos. Importa que sea ``floor`` y no ``ceil``: si el evaluador pasa más
    frecuentemente de lo que dura la vela —el caso normal, 5 minutos con velas
    de 1 hora— solo puede cerrarse **una** vela entre medias, y multiplicar por
    veinte es trabajo que no compra nada.

    Mirar de más no cuesta casi nada: el warmup de 1.000 velas se carga igual, y
    los duplicados los para el indice único de ``alerts``. Mirar de menos sí
    cuesta, porque son avisos que no llegan.
    """
    minutos = _minutos_de_vela(timeframe)
    cerradas = int(intervalo_s // 60) // minutos
    return max(VELAS_RECIENTES_MINIMO, cerradas + 1)


@dataclass(frozen=True, slots=True)
class Evaluacion:
    """Lo que el evaluador ha hecho con una regla.

    ``detections`` viene **siempre** con ``motivo`` y ``ruta``. Una regla que no
    ha saltado y una que no se ha mirado se ven igual en la base si no se
    distingue, y esa confusión es la que hace que un sistema de avisos parezca
    muerto cuando solo se ha quedado sin datos.
    """

    regla_id: object
    detections: tuple[Deteccion, ...]
    ruta: str
    motivo: str
    velas: int


def _minutos_de_vela(timeframe: str) -> int:
    from app.modules.data_import.service import TIMEFRAME_MS

    if timeframe not in TIMEFRAME_MS:
        raise ValueError(f"Timeframe no soportado: {timeframe}")
    return TIMEFRAME_MS[timeframe] // 60_000


def _ultima_vela(db: Session, symbol: str, timeframe: str) -> pd.Timestamp | None:
    fila = db.scalar(
        select(func.max(Candle.timestamp)).where(
            Candle.symbol == symbol,
            Candle.timeframe == timeframe,
        )
    )
    return pd.Timestamp(fila) if fila is not None else None


def _params_por_defecto(codigo: str) -> dict:
    """Los parámetros con los que el catálogo resuelve este patrón sin pedir nada.

    Es lo que hace un job de escaneo cuando el usuario no toca los parámetros, y
    es lo que tiene que hacer la alerta: si la alerta usara otros parámetros que
    los del escaneo, estaría vigilando un patrón que el catálogo no define.
    """
    from app.modules.features.service import INDICATOR_PARAM_DEFAULTS

    definicion = catalog.get_definition(codigo)
    if definicion is None:
        return {}
    return dict(INDICATOR_PARAM_DEFAULTS)


def _requeridas(codigo: str) -> tuple[str, ...]:
    return catalog.required_features_for(
        [codigo], {codigo: _params_por_defecto(codigo)}
    )


#: Familia de indicador → parámetros que toma. Es la **misma** convención de
#: nombres que usa ``FeatureService._calculate_indicator`` para volver a emitir
#: las columnas, y la tabla se mantiene a mano porque los indicadores del módulo
#: de features son un conjunto cerrado.
_FAMILIA = ("SMA", "EMA", "RSI", "ATR")


def _indicador_de(nombre: str) -> tuple[str, dict]:
    """``RSI_14`` → ``("RSI", {"length": 14})``. Inverso, no recorte.

    ## Por qué no basta con cortar por el guion bajo

    La primera versión hacía ``nombre.split("_")[0]`` y funcionaba con ``RSI_14``,
    y rompía con ``MACDs_12_26_9``: la familia es ``MACD`` y de ahí salen **tres**
    columnas (``MACD_``, ``MACDs_``, ``MACDh_``) con **tres** parámetros. Un
    ``"MACDs"`` no existe como indicador y el cálculo devolvía una columna
    vacía, el scanner no detectaba nada, y el sistema de alertas se quedaba
    callado sin decir por qué. Lo encontró el test de igualdad, no una revisión.

    ## Por qué falla en vez de adivinar

    Un nombre que no se sabe interpretar lanza. Un nombre mal interpretado
    devuelve una feature **calculada con otros parámetros** y el detector avisaría
    de una señal que el backtest nunca vio: el peor fallo posible aquí, porque
    es invisible. Ante la duda, callar es mejor que avisar de algo inventado.
    """
    partes = nombre.split("_")

    # `VOLUME_SMA_20` no corta en "VOLUME": el indicador se llama `VOLUME_SMA`
    # y su longitud va al final. Se prueba el nombre compuesto **antes** de
    # partir, porque partir primero y luego recomponer es el mismo error en la
    # otra dirección.
    if nombre.startswith("VOLUME_SMA_") and len(partes) == 3:
        return "VOLUME_SMA", {"length": int(partes[2])}

    raiz = partes[0]

    if raiz in ("MACD", "MACDs", "MACDh") and len(partes) == 4:
        return "MACD", {
            "fast": int(partes[1]),
            "slow": int(partes[2]),
            "signal": int(partes[3]),
        }

    if raiz in ("BBU", "BBM", "BBL") and len(partes) == 3:
        return "BBANDS", {"length": int(partes[1]), "std": float(partes[2])}

    if raiz in _FAMILIA and len(partes) == 2:
        return raiz, {"length": int(partes[1])}

    raise ValueError(
        f"No sé qué indicador produce la feature '{nombre}'. El evaluador "
        "prefiere callarse a calcularla con parámetros inventados: una feature "
        "mal calculada produce detecciones que el backtest nunca vio, y eso no "
        "se ve en ningún sitio."
    )


def _marco_con_cache(
    db: Session,
    candles: pd.DataFrame,
    nombres: tuple[str, ...],
    symbol: str,
    timeframe: str,
) -> pd.DataFrame | None:
    """Features desde la tabla, si las hay para todas las requeridas.

    Devuelve ``None`` si falta alguna, y quien llama cae a la ruta de vuelo. Es
    preferible calcular de más que avisar con una columna a medias: una feature
    ausente deja el scanner devolviendo cero detecciones, y un sistema de avisos
    que no avisa parece roto sin que nada diga por qué.
    """
    if not nombres:
        return None
    indice = candles.index
    columnas: dict[str, pd.Series] = {}
    for nombre in nombres:
        filas = db.execute(
            select(Feature.timestamp, Feature.value)
            .where(
                Feature.indicator_name == nombre,
                Feature.symbol == symbol,
                Feature.timeframe == timeframe,
                Feature.timestamp >= indice[0].to_pydatetime(),
                Feature.timestamp <= indice[-1].to_pydatetime(),
            )
            .order_by(Feature.timestamp)
        ).all()
        if not filas:
            return None
        serie = pd.Series(
            [float(v) for _, v in filas],
            index=pd.DatetimeIndex([t for t, _ in filas], name="timestamp"),
            dtype="float64",
        )
        # Se reindexa al marco completo: sin esto, un hueco de la tabla de
        # features se convierte en un hueco de filas del marco y el scanner deja
        # de mirar velas que sí existen.
        columnas[nombre] = serie.reindex(indice)
    marco = candles.join(pd.DataFrame(columnas), how="left")
    # `list(nombres)` y no `nombres`: pandas trata una **tupla** como una clave
    # sola, no como una lista de columnas, y `marco[nombres]` falla con un
    # `KeyError` que lleva dentro la tupla entera. Solo lo detectó la ejecución
    # con datos reales, porque los tests sintéticos nunca llegaron a la ruta de
    # caché: no había features en la base.
    if marco[list(nombres)].isna().all(axis=None):
        return None
    return marco


def _marco_con_vuelo(candles: pd.DataFrame, nombres: tuple[str, ...]) -> pd.DataFrame:
    """Features calculadas aquí, con el **mismo** método que usa el job.

    La identidad de la función es la garantía. Si algún día se reimplementa el
    cálculo dentro de alertas, este módulo pasa a avisar sobre datos que el
    backtest nunca vio, y no hay ningún test que lo detecte salvo el de igualdad.
    """
    servicio = FeatureService()
    marco = candles
    for nombre in nombres:
        indicador, params = _indicador_de(nombre)
        calculadas = servicio._calculate_indicator(marco, indicador, params)
        for clave, serie in calculadas.items():
            if clave == nombre:
                marco = marco.assign(**{clave: serie})
    return marco


def _ruta_para(
    db: Session,
    symbol: str,
    timeframe: str,
    fin: pd.Timestamp,
    patron: str,
) -> tuple[pd.DataFrame, str]:
    minutos = _minutos_de_vela(timeframe)
    inicio = fin - pd.Timedelta(minutes=minutos * WARMUP_VELAS)
    velas = load_candles(
        symbol,
        timeframe,
        inicio.to_pydatetime(),
        (fin + pd.Timedelta(minutes=minutos)).to_pydatetime(),
    )
    if velas.empty:
        raise ValueError(f"No hay velas de {symbol} {timeframe}")

    requeridas = _requeridas(patron)
    marco_cache = _marco_con_cache(db, velas, requeridas, symbol, timeframe)
    if marco_cache is not None:
        return marco_cache, "cache"
    return _marco_con_vuelo(velas, requeridas), "vuelo"


def evaluar_regla(db: Session, regla, intervalo_s: float = 300.0) -> Evaluacion:
    """Detecta el patrón de la regla en las velas más recientes.

    La detección se hace con ``PatternService._run_step``, el mismo método que
    usa un job de escaneo, para que «lo que la alerta vigila» y «lo que el escaneo
    encuentra» sean literalmente la misma cuenta.

    ``intervalo_s`` es cada cuánto se llama, y determina cuántas velas hay que
    mirar. Ver ``velas_recientes`` para por qué no es un detalle.
    """
    ultima = _ultima_vela(db, regla.symbol, regla.timeframe)
    if ultima is None:
        return Evaluacion(
            regla_id=regla.id,
            detections=(),
            ruta="ninguna",
            motivo=f"No hay velas de {regla.symbol} {regla.timeframe}",
            velas=0,
        )

    minutos = _minutos_de_vela(regla.timeframe)
    try:
        marco, ruta = _ruta_para(
            db, regla.symbol, regla.timeframe, ultima, regla.pattern_name
        )
    except Exception as exc:  # noqa: BLE001 - se anota, no se propaga
        return Evaluacion(
            regla_id=regla.id,
            detections=(),
            ruta="error",
            motivo=f"No se pudo construir el marco: {exc}",
            velas=0,
        )

    definicion = catalog.get_definition(regla.pattern_name)
    if definicion is None:
        return Evaluacion(
            regla_id=regla.id,
            detections=(),
            ruta=ruta,
            motivo=f"Patrón fuera del catálogo: {regla.pattern_name}",
            velas=len(marco),
        )

    marco.attrs["symbol"] = regla.symbol
    marco.attrs["timeframe"] = regla.timeframe

    servicio_patrones = PatternScanService()
    paso = servicio_patrones._build_plan(
        [PatternSelection(code=regla.pattern_name, params={})]
    )
    if not paso:
        return Evaluacion(
            regla_id=regla.id,
            detections=(),
            ruta=ruta,
            motivo=f"El catálogo no sabe construir un paso para {regla.pattern_name}",
            velas=len(marco),
        )

    faltan = [f for f in paso[0].features if f not in marco.columns]
    if faltan:
        return Evaluacion(
            regla_id=regla.id,
            detections=(),
            ruta=ruta,
            motivo=f"Faltan features en el marco: {', '.join(faltan)}",
            velas=len(marco),
        )

    try:
        deteccion = servicio_patrones._run_step(marco, paso[0])
    except Exception as exc:  # noqa: BLE001
        return Evaluacion(
            regla_id=regla.id,
            detections=(),
            ruta=ruta,
            motivo=f"El scanner falló: {exc}",
            velas=len(marco),
        )

    if deteccion is None or deteccion.empty:
        return Evaluacion(
            regla_id=regla.id,
            detections=(),
            ruta=ruta,
            motivo="Sin detecciones en las velas recientes",
            velas=len(marco),
        )

    ventana = velas_recientes(regla.timeframe, intervalo_s)
    desde = ultima - pd.Timedelta(minutes=minutos * ventana)
    recientes = deteccion[deteccion["timestamp"] >= desde]
    cierres = marco["close"]
    detecciones = tuple(
        Deteccion(
            timestamp=pd.Timestamp(fila["timestamp"]),
            pattern_name=str(fila["pattern_name"]),
            reference_price=float(cierres.asof(pd.Timestamp(fila["timestamp"]))),
            ruta=ruta,
        )
        for _, fila in recientes.iterrows()
    )
    return Evaluacion(
        regla_id=regla.id,
        detections=detecciones,
        ruta=ruta,
        motivo=(
            f"{len(detecciones)} detección(es) en las últimas {ventana} velas"
            if detecciones
            else "Sin detecciones en las velas recientes"
        ),
        velas=len(marco),
    )
