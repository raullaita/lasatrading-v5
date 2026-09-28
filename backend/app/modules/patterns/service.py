"""Orquestacion del escaneo de patrones: carga de datos, plan y persistencia.

Clon de ``FeatureService`` en estructura y estilos, con tres diferencias
deliberadas:

* Las features se cargan con **una** consulta en formato largo y se pivotan en
  memoria, en lugar de una consulta por indicador.
* La escritura usa ``on_conflict_do_update`` sobre la PK compuesta, de modo que
  reejecutar un job es idempotente.
* El progreso se reporta por etapa (carga, cada scanner, escritura) en lugar de
  por vela: una deteccion vectorizada no tiene progreso incremental que
  ofrecer, e inventarlo seria mentirle al WebSocket.
"""

import math
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.database import SessionLocal
from app.modules.data.candles import load_candles
from app.modules.patterns import pattern_catalog as catalog
from app.modules.patterns.models import (
    LogLevel,
    PatternOccurrence,
    PatternScanJob,
    PatternScanJobStatus,
    PatternScanLog,
)
from app.modules.patterns.scanner import SCANNER_METHODS, PatternScanner
from app.modules.patterns.schemas import PatternScanConfig, PatternSelection

#: Filas por lote al insertar, igual que en ``FeatureService._save_features``.
OCCURRENCE_BATCH_SIZE = 5000

#: Por debajo de esta cobertura de velas el escaneo se sigue ejecutando, pero se
#: avisa en el log: casi siempre significa que las features se calcularon sobre
#: un rango mas corto que el pedido.
COVERAGE_WARN_RATIO = 0.5

#: Estados desde los que ya no tiene sentido relanzar un job.
#:
#: ``FAILED`` **no** esta aqui a proposito. El fallo mas habitual del modulo es
#: ``MissingFeaturesError``; el usuario calcula lo que falta y vuelve a pulsar
#: "reintentar" sobre el mismo job. Si ``failed`` fuera terminal, ese boton
#: devolveria 400 justo en el caso para el que existe, obligando a crear un job
#: nuevo desde cero y perdiendo la trazabilidad de que fallo el primero.
NON_REQUEUEABLE_STATUSES = frozenset(
    {
        PatternScanJobStatus.COMPLETED.value,
        PatternScanJobStatus.CANCELLED.value,
    }
)


class ScanCancelled(Exception):
    pass


class MissingFeaturesError(Exception):
    """Faltan features precalculadas para los patrones solicitados.

    V1 exige que existan (Tarea 3). El mensaje es el que pide el documento de
    la tarea, para que el usuario sepa a donde ir.
    """

    def __init__(self, missing: Sequence[str]) -> None:
        self.missing = list(missing)
        super().__init__(
            f"Faltan features: {', '.join(self.missing)}. "
            "Por favor, ejecuta un cálculo de indicadores primero."
        )


@dataclass(frozen=True, slots=True)
class ScanStep:
    """Una llamada al scanner, con los codigos de patron que debe cubrir.

    Se agrupan los patrones que comparten scanner, features y parametros, de
    modo que requesting MACD alcista y MACD bajista no calcula dos veces lo
    mismo, pero requesting MACD 12/26/9 y MACD 5/35/5 si genera dos pasos
    distintos porque necesitan columnas distintas.
    """

    scanner: str
    params: Mapping[str, int | float]
    features: tuple[str, ...]
    codes: tuple[str, ...]


#: Tope de velas que se envuelven en la respuesta de un grafico. Un ano de 1h
#: son 8.760 velas, y por cada una hay una fila por indicador en ``features``.
#: Es un tope de **payload**, no de datos: el paso de muestreo es entero, asi que
#: la escala temporal no se sesga.
DEFAULT_CHART_MAX_POINTS = 1_500

#: Tope duro del parametro de la API. Por encima la respuesta deja de ser comoda
#: de pintar aunque el navegador la aguante.
CHART_MAX_POINTS_LIMIT = 5_000


def sampling_plan(total_points: int, max_points: int | None) -> tuple[int, list[int]]:
    """Paso de muestreo y posiciones de vela a conservar.

    Devuelve ``(paso, indices)`` con ``paso == 1`` cuando no hace falta muestrear.

    Vive fuera de la clase, y aparte de la consulta, por dos motivos: se puede
    probar sin base de datos ni pandas, y su fallo es **silencioso**. Un paso mal
    calculado no lanza nada, solo enseña otro rango del que el usuario pidio, y
    eso no se ve hasta que alguien cuenta las velas.
    """
    if total_points <= 0:
        return 1, []
    if not max_points or max_points <= 0 or total_points <= max_points:
        return 1, list(range(total_points))
    if max_points < 2:
        # El tope solo puede honrarse hasta dos velas, porque conservar la
        # primera y la ultima son innegociables. El router exige ``ge=100``, asi
        # que esto es defensa para un llamador interno, no un caso de API.
        return total_points, [0, total_points - 1]

    # El paso se calcula sobre ``max_points - 1`` y no sobre ``max_points``,
    # porque la última vela se añade aparte y con el calculo ingenuo el tope se
    # incumple: 10 velas con tope 3 dan paso 4, que son [0, 4, 8], y al añadir la
    # ultima quedan 4 velas, una mas de las pedidas. Un parametro que se llama
    # ``max_points`` y a veces devuelve mas es exactamente la clase de mentira
    # que los cuatro campos del muestreo existen para evitar.
    paso = math.ceil(total_points / (max_points - 1))
    indices = [i for i in range(total_points) if i % paso == 0]
    if indices[-1] != total_points - 1:
        # La ultima vela se conserva siempre. Es el mismo descuido que se corrigio
        # en la curva de equity del backtesting: al muestrear por paso constante
        # el final cae dentro del hueco del ultimo paso, y un grafico que no
        # llega al cierre no esta mostrando el cierre. Aqui se nota menos, pero
        # el principe es el mismo.
        indices.append(total_points - 1)
    return paso, indices


def _candle_rows(candles: pd.DataFrame, indices: Sequence[int]) -> list[dict]:
    """Filas de vela de las posiciones indicadas, en dicts planos.

    Las columnas se convierten a numpy **una vez**, fuera del bucle. Leer
    ``candles["open"]`` por posicion reconstruye la Serie entera en cada vuelta:
    con 1.500 velas serian 6.000 reconstrucciones en vez de cinco conversiones,
    y el coste crece con el rango hasta que la pantalla tarda en abrir.
    """
    opens = candles["open"].to_numpy(dtype=float)
    highs = candles["high"].to_numpy(dtype=float)
    lows = candles["low"].to_numpy(dtype=float)
    closes = candles["close"].to_numpy(dtype=float)
    volumes = candles["volume"].to_numpy(dtype=float)
    return [
        {
            "timestamp": candles.index[position].to_pydatetime(),
            "open": float(opens[position]),
            "high": float(highs[position]),
            "low": float(lows[position]),
            "close": float(closes[position]),
            "volume": float(volumes[position]),
        }
        for position in indices
    ]


class PatternScanService:
    def __init__(self) -> None:
        self.settings = get_settings()

    # ------------------------------------------------------------------ logs

    def _log(
        self,
        db: Session,
        job_id: uuid.UUID,
        level: str,
        message: str,
        progress: int | None = None,
    ) -> None:
        db.add(
            PatternScanLog(
                job_id=job_id,
                level=level,
                message=message,
                progress=progress,
            )
        )
        db.flush()

    @staticmethod
    def _is_cancelled(db: Session, job_id: uuid.UUID) -> bool:
        job = db.get(PatternScanJob, job_id)
        return job is not None and job.status == PatternScanJobStatus.CANCELLED.value

    def _mark_job(
        self,
        job_id: uuid.UUID,
        status: str,
        started_at: bool = False,
        finished_at: bool = False,
    ) -> None:
        with SessionLocal() as db:
            job = db.get(PatternScanJob, job_id)
            if job is None:
                return
            job.status = status
            if started_at:
                # Al arrancar un reintento se limpia el error anterior: un job
                # completado no debe seguir enseñando el motivo por el que
                # falló la vez anterior.
                job.error_message = None
                if job.started_at is None:
                    job.started_at = datetime.now(timezone.utc)
            if finished_at and job.finished_at is None:
                job.finished_at = datetime.now(timezone.utc)
            db.commit()

    def _log_committed(
        self,
        job_id: uuid.UUID,
        level: str,
        message: str,
        progress: int | None = None,
    ) -> None:
        with SessionLocal() as db:
            self._log(db, job_id, level, message, progress)
            db.commit()

    # ------------------------------------------------------------- gestion

    def create_job(self, db: Session, config: PatternScanConfig) -> PatternScanJob:
        from app.modules.data_import.models import Candle

        candle_count = db.scalar(
            select(func.count())
            .select_from(Candle)
            .where(Candle.symbol == config.symbol)
            .where(Candle.timeframe == config.timeframe)
            .where(Candle.timestamp >= config.date_from)
            .where(Candle.timestamp <= config.date_to)
        )
        if not candle_count:
            raise ValueError(
                f"No hay datos de velas para {config.symbol} {config.timeframe} "
                f"en el rango especificado"
            )

        # Se guardan los parametros ya resueltos y acotados, no los que envio el
        # cliente: asi el job reproduce exactamente lo que se valido, y el
        # required_features que se calcule al ejecutarlo coincide con el del
        # momento de crearlo.
        selections = []
        for selection in config.patterns:
            definition = catalog.get_definition(selection.code)
            if definition is None:
                continue
            selections.append(
                {
                    "code": definition.code,
                    "params": definition.resolve_params(selection.params),
                }
            )

        job = PatternScanJob(
            symbol=config.symbol,
            timeframe=config.timeframe,
            date_from=config.date_from,
            date_to=config.date_to,
            patterns_config=selections,
        )
        db.add(job)
        db.flush()
        self._log(
            db,
            job.id,
            LogLevel.INFO.value,
            f"Job creado para {job.symbol} {job.timeframe} "
            f"con {len(selections)} patrones",
        )
        db.commit()
        db.refresh(job)
        return job

    def cancel_job(self, job_id: uuid.UUID) -> bool:
        with SessionLocal() as db:
            job = db.get(PatternScanJob, job_id)
            if job is None or job.status in (
                PatternScanJobStatus.COMPLETED.value,
                PatternScanJobStatus.FAILED.value,
                PatternScanJobStatus.CANCELLED.value,
            ):
                return False
            job.status = PatternScanJobStatus.CANCELLED.value
            job.finished_at = datetime.now(timezone.utc)
            self._log(db, job_id, LogLevel.INFO.value, "Cancelación solicitada")
            db.commit()
            return True

    def delete_job(self, job_id: uuid.UUID) -> bool:
        with SessionLocal() as db:
            job = db.get(PatternScanJob, job_id)
            if job is None:
                return False
            db.delete(job)
            db.commit()
            return True

    def requeue_job(self, job_id: uuid.UUID) -> bool:
        """Devuelve el job a la cola. Acepta ``failed``; ver
        ``NON_REQUEUEABLE_STATUSES``."""
        with SessionLocal() as db:
            job = db.get(PatternScanJob, job_id)
            if job is None:
                return False
            if job.status in NON_REQUEUEABLE_STATUSES:
                return False
            job.status = PatternScanJobStatus.PENDING.value
            job.started_at = None
            job.finished_at = None
            job.processed_candles = 0
            job.error_message = None
            self._log(db, job_id, LogLevel.INFO.value, "Job reenviado a la cola")
            db.commit()
            return True

    # ------------------------------------------------------------- escaneo

    def execute_scan(self, job_id: uuid.UUID) -> None:
        """Ejecuta el escaneo completo de un job. Punto de entrada de Celery.

        Envoltorio de excepcion, igual que ``FeatureService.execute_job``: deja
        el job en un estado terminal coherente y registra el motivo.
        """
        try:
            self._mark_job(
                job_id, PatternScanJobStatus.PROCESSING.value, started_at=True
            )
            with SessionLocal() as db:
                job = db.get(PatternScanJob, job_id)
                if job is None:
                    return
                symbol, timeframe = job.symbol, job.timeframe
                date_from, date_to = job.date_from, job.date_to
                selections = [
                    PatternSelection.model_validate(item)
                    for item in job.patterns_config
                ]
            config = PatternScanConfig(
                symbol=symbol,
                timeframe=timeframe,
                date_from=date_from,
                date_to=date_to,
                patterns=selections,
            )
            self._run_scan(job_id, config)
        except ScanCancelled:
            self._mark_job(
                job_id, PatternScanJobStatus.CANCELLED.value, finished_at=True
            )
            self._log_committed(
                job_id, LogLevel.INFO.value, "Job cancelado por el usuario"
            )
        except Exception as exc:
            self._mark_job(job_id, PatternScanJobStatus.FAILED.value, finished_at=True)
            self._log_committed(
                job_id, LogLevel.ERROR.value, f"Error en escaneo: {exc}"
            )
            with SessionLocal() as db:
                job = db.get(PatternScanJob, job_id)
                if job:
                    job.error_message = str(exc)[:500]
                    db.commit()

    def _run_scan(self, job_id: uuid.UUID, config: PatternScanConfig) -> None:
        steps = self._build_plan(config.patterns)
        if not steps:
            raise ValueError("El job no contiene patrones válidos")

        required = catalog.required_features_for(
            [code for step in steps for code in step.codes],
            {code: dict(step.params) for step in steps for code in step.codes},
        )

        df = load_candles(
            config.symbol, config.timeframe, config.date_from, config.date_to
        )
        if df.empty:
            raise ValueError("No se pudieron cargar datos de velas")
        total_candles = len(df)

        self._log_committed(
            job_id,
            LogLevel.INFO.value,
            f"Cargadas {total_candles} velas de {config.symbol} {config.timeframe}",
        )
        with SessionLocal() as db:
            job = db.get(PatternScanJob, job_id)
            if job is None:
                return
            job.total_candles = total_candles
            db.commit()

        if self._is_cancelled_in_new_session(job_id):
            raise ScanCancelled()

        features = self._load_features_pivot(
            config.symbol,
            config.timeframe,
            config.date_from,
            config.date_to,
            required,
        )
        missing = [name for name in required if name not in features.columns]
        if missing:
            raise MissingFeaturesError(missing)
        self._log_committed(
            job_id,
            LogLevel.INFO.value,
            f"Cargadas {len(features.columns)} series de features: "
            f"{', '.join(required)}",
        )
        self._warn_low_coverage(job_id, features, required, total_candles)

        if self._is_cancelled_in_new_session(job_id):
            raise ScanCancelled()

        # Left join sobre el indice de tiempo: las velas mandan, y las features
        # que falten en una vela concreta quedan como NaN (y por tanto no
        # generan deteccion en esa barra).
        scan_df = df.join(features, how="left")
        scan_df.attrs["symbol"] = config.symbol
        scan_df.attrs["timeframe"] = config.timeframe

        frames: list[pd.DataFrame] = []
        for index, step in enumerate(steps):
            if self._is_cancelled_in_new_session(job_id):
                raise ScanCancelled()
            result = self._run_step(scan_df, step)
            frames.append(result)
            self._log_committed(
                job_id,
                LogLevel.INFO.value,
                f"{step.scanner}: {len(result)} detecciones ({'/'.join(step.codes)})",
                progress=int(((index + 1) / len(steps)) * 90),
            )

        detections = pd.concat(frames, ignore_index=True) if frames else None
        if detections is None or detections.empty:
            saved = 0
        else:
            saved = self._save_occurrences(
                job_id, config.symbol, config.timeframe, detections
            )
        self._log_committed(
            job_id, LogLevel.INFO.value, f"{saved} ocurrencias almacenadas"
        )

        with SessionLocal() as db:
            job = db.get(PatternScanJob, job_id)
            if job is None:
                return
            job.processed_candles = total_candles
            job.status = PatternScanJobStatus.COMPLETED.value
            job.finished_at = datetime.now(timezone.utc)
            self._log(
                db,
                job_id,
                LogLevel.INFO.value,
                f"Job completado: {total_candles} velas procesadas, "
                f"{saved} ocurrencias",
                progress=100,
            )
            db.commit()

    def _build_plan(self, selections: Sequence[PatternSelection]) -> list[ScanStep]:
        """Agrupa los patrones solicitados en llamadas minimas al scanner."""
        grouped: dict[
            tuple[str, tuple[tuple[str, object], ...], tuple[str, ...]], set[str]
        ] = {}

        for selection in selections:
            definition = catalog.get_definition(selection.code)
            if definition is None:
                continue
            params = definition.resolve_params(selection.params)
            # La clave incluye scanner, parametros y features exigidas, asi que
            # dos patrones caen en el mismo grupo solo si son intercambiables.
            key = (
                definition.scanner,
                tuple(sorted(params.items())),
                definition.required_features(params),
            )
            grouped.setdefault(key, set()).add(definition.code)

        return [
            ScanStep(
                scanner=scanner,
                params=dict(sorted_params),
                features=features,
                codes=tuple(sorted(codes)),
            )
            for (scanner, sorted_params, features), codes in grouped.items()
        ]

    def _run_step(self, df: pd.DataFrame, step: ScanStep) -> pd.DataFrame:
        """Ejecuta un paso del plan y se queda solo con los codos solicitados.

        El scanner devuelve siempre ambos sentidos; filtrar aqui evita que un
        job que solo pide MACD alcista termine con filas bajistas de mas.
        """
        if step.scanner not in SCANNER_METHODS:
            raise ValueError(f"Scanner desconocido en el catálogo: {step.scanner}")

        features = step.features
        params = step.params

        if step.scanner == "scan_macd_crossover":
            result = PatternScanner.scan_macd_crossover(df, features[0], features[1])
        elif step.scanner == "scan_rsi_extremes":
            result = PatternScanner.scan_rsi_extremes(
                df,
                features[0],
                float(params.get("threshold_up", 70)),
                float(params.get("threshold_down", 30)),
            )
        elif step.scanner == "scan_bollinger_breakout":
            result = PatternScanner.scan_bollinger_breakout(
                df, "close", features[0], features[1]
            )
        elif step.scanner == "scan_ma_crossover":
            result = PatternScanner.scan_ma_crossover(df, features[0], features[1])
        else:  # scan_engulfing
            result = PatternScanner.scan_engulfing(df)

        return result[result["pattern_name"].isin(step.codes)].reset_index(drop=True)

    def _warn_low_coverage(
        self,
        job_id: uuid.UUID,
        features: pd.DataFrame,
        required: Sequence[str],
        total_candles: int,
    ) -> None:
        for name in required:
            covered = int(features[name].notna().sum())
            if covered / total_candles < COVERAGE_WARN_RATIO:
                self._log_committed(
                    job_id,
                    LogLevel.WARNING.value,
                    f"La feature {name} solo cubre {covered} de {total_candles} "
                    "velas del rango. Las detecciones pueden salir incompletas.",
                )

    @staticmethod
    def _is_cancelled_in_new_session(job_id: uuid.UUID) -> bool:
        with SessionLocal() as db:
            return PatternScanService._is_cancelled(db, job_id)

    # ------------------------------------------------------------- carga

    def _load_features_pivot(
        self,
        symbol: str,
        timeframe: str,
        date_from: datetime,
        date_to: datetime,
        feature_names: Sequence[str],
        only_timestamps: Sequence[datetime] | None = None,
    ) -> pd.DataFrame:
        """Carga las features en ancho con **una** consulta.

        Se traen en formato largo (timestamp, indicator_name, value) y se
        pivota en memoria: una consulta por indicador seria el clasico N+1 que
        el documento de la tarea prohibe.

        ``only_timestamps`` recorta a un conjunto concreto de instantes, y existe
        por el muestreo de velas: si el grafico pinta 1.500 de 8.760 velas, los
        indicadores se piden **solo en esas 1.500**. Traer los dos por separado y
        dejar que lightweight-charts los una por tiempo produciria un overlay
        correcto en apariencia pero anclado a velas que no estan en pantalla, que
        es la forma de que el grafico parezca bien y no lo este.
        """
        from app.modules.features.models import Feature

        names = sorted(set(feature_names))
        if not names:
            return pd.DataFrame()

        with SessionLocal() as db:
            stmt = (
                select(Feature.timestamp, Feature.indicator_name, Feature.value)
                .where(Feature.symbol == symbol)
                .where(Feature.timeframe == timeframe)
                .where(Feature.timestamp >= date_from)
                .where(Feature.timestamp <= date_to)
                .where(Feature.indicator_name.in_(names))
            )
            if only_timestamps is not None:
                if not only_timestamps:
                    return pd.DataFrame()
                stmt = stmt.where(Feature.timestamp.in_(list(only_timestamps)))
            rows = db.execute(stmt).all()

        if not rows:
            return pd.DataFrame()

        long = pd.DataFrame(rows, columns=["timestamp", "indicator_name", "value"])
        long["timestamp"] = pd.to_datetime(long["timestamp"], utc=True)
        long["value"] = long["value"].astype(float)
        wide = long.pivot(index="timestamp", columns="indicator_name", values="value")
        # Solo se devuelven las columnas que existen de verdad. Reindexar para
        # crear las ausentes como NaN seria comodo, pero impediria detectar
        # despues cuales faltan, que es justo el trabajo de este pivot.
        return wide.reindex(columns=sorted(set(wide.columns) & set(names))).sort_index()

    # ------------------------------------------------------------ escritura

    def _save_occurrences(
        self,
        job_id: uuid.UUID,
        symbol: str,
        timeframe: str,
        detections: pd.DataFrame,
    ) -> int:
        """Inserta las detecciones en lotes, idempotente.

        El upsert es sobre la PK completa, que incluye ``scan_job_id``: relanzar
        el mismo job actualiza sus filas en vez de duplicarlas. Dos jobs
        distintos sobre el mismo rango si generan filas distintas, que es
        justamente lo que permite auditar que encontro cada escaneo.

        El insert se hace contra ``__table__`` (Core) y no contra la clase ORM a
        proposito: la clase declarativa tiene un atributo ``metadata`` heredado
        que es su propio ``MetaData``, asi que el ORM resuelve esa clave del
        diccionario contra el atributo en lugar de contra la columna y falla con
        ``'MetaData' object has no attribute '_bulk_update_tuples'``. Por Core la
        clave ``metadata`` es solo el nombre de la columna.
        """
        timestamps = detections["timestamp"].dt.to_pydatetime().to_numpy()
        names = detections["pattern_name"].to_numpy()
        details = detections["details"].to_numpy()

        rows = [
            {
                "timestamp": timestamp,
                "symbol": symbol,
                "timeframe": timeframe,
                "pattern_name": name,
                "scan_job_id": job_id,
                "metadata": detail,
            }
            for timestamp, name, detail in zip(timestamps, names, details, strict=True)
        ]

        table = PatternOccurrence.__table__
        saved = 0
        with SessionLocal() as db:
            for start in range(0, len(rows), OCCURRENCE_BATCH_SIZE):
                batch = rows[start : start + OCCURRENCE_BATCH_SIZE]
                stmt = pg_insert(table).values(batch)
                stmt = stmt.on_conflict_do_update(
                    index_elements=[
                        "timestamp",
                        "symbol",
                        "timeframe",
                        "pattern_name",
                        "scan_job_id",
                    ],
                    set_={"metadata": stmt.excluded["metadata"]},
                )
                db.execute(stmt)
                db.flush()
                saved += len(batch)
            db.commit()
        return saved

    # ------------------------------------------------------------ consulta

    def get_occurrences(
        self,
        job_id: uuid.UUID | None = None,
        symbol: str | None = None,
        timeframe: str | None = None,
        pattern_names: Sequence[str] | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        """Lista de ocurrencias con el total, para la tabla del frontend."""
        with SessionLocal() as db:
            conditions = []
            if job_id is not None:
                conditions.append(PatternOccurrence.scan_job_id == job_id)
            if symbol is not None:
                conditions.append(PatternOccurrence.symbol == symbol)
            if timeframe is not None:
                conditions.append(PatternOccurrence.timeframe == timeframe)
            if pattern_names:
                conditions.append(
                    PatternOccurrence.pattern_name.in_(list(pattern_names))
                )
            if date_from is not None:
                conditions.append(PatternOccurrence.timestamp >= date_from)
            if date_to is not None:
                conditions.append(PatternOccurrence.timestamp <= date_to)

            total = db.scalar(
                select(func.count()).select_from(PatternOccurrence).where(*conditions)
            )
            rows = (
                db.execute(
                    select(PatternOccurrence)
                    .where(*conditions)
                    .order_by(
                        PatternOccurrence.timestamp.desc(),
                        PatternOccurrence.symbol,
                        PatternOccurrence.timeframe,
                    )
                    .limit(limit)
                    .offset(offset)
                )
                .scalars()
                .all()
            )

            return (
                [
                    {
                        "timestamp": row.timestamp,
                        "symbol": row.symbol,
                        "timeframe": row.timeframe,
                        "pattern_name": row.pattern_name,
                        "scan_job_id": row.scan_job_id,
                        "details": row.details,
                    }
                    for row in rows
                ],
                int(total or 0),
            )

    def get_chart_data(
        self,
        symbol: str,
        timeframe: str,
        date_from: datetime,
        date_to: datetime,
        feature_names: Sequence[str] | None = None,
        pattern_names: Sequence[str] | None = None,
        scan_job_id: uuid.UUID | None = None,
        max_points: int | None = None,
    ) -> dict:
        """Velas + series de indicadores + ocurrencias para pintar el grafico.

        Los markers se calculan aqui (no en el frontend) para que el mapeo al
        formato de lightweight-charts sea una traduccion trivial y el cliente no
        tenga que saber nada de nombres de feature.

        **No necesita un escaneo**: el rango, los indicadores y los patrones se
        reciben aqui y el unico opcional es ``scan_job_id``, que es lo unico que
        la ruta de escaneo aporta. Por eso el explorador de datos puede leer el
        grafico sin haber creado nunca un job.

        Tres decisiones que no son evidentes:

        * **El muestreo de velas no es libre.** Con paso constante se pierde
          precision, pero el precio se mantiene comparable entre velas porque
          todas son del mismo timeframe y solo se saltan algunas. Lo que **no**
          puede hacerse es muestrear los indicadores por separado: se
          desalinearian del eje temporal y el overlay dibujaria sobre velas que
          no son las suyas. Por eso se eligen primero las timestamps de las
          velas y los indicadores se piden solo en esas.

        * **La ultima vela se conserva siempre.** Es el mismo descuido que se
          corrigio en la curva de equity del backtesting, donde el muestreo por
          paso dejaba la serie terminando en el penultimo punto y el
          ``equity_final`` de la tarjeta no se veia nunca en el grafico. Aqui el
          coste es menor, pero el principio es identico: un grafico que no
          llega al final no esta mostrando el final.

        * **Los indicadores que no existen se declaran.** ``features`` tiene una
          cobertura irregular (``EMA_50`` solo existe desde 2026-07 para
          BTCUSDT) y descartarlos en silencio haria que un ``ATR_14`` pedido en
          2022 desapareciera del grafico sin dejar rastro, que se lee como "no
          esta implementado".
        """
        candles = load_candles(symbol, timeframe, date_from, date_to)
        total_points = int(len(candles))

        paso, indices = sampling_plan(total_points, max_points)
        timestamps = (
            [candles.index[position].to_pydatetime() for position in indices]
            if indices
            else None
        )
        if candles.empty:
            # Rango sin velas. Pasa de verdad (el explorador pregunta por
            # cualquier ventana, included una que no este importada) y la
            # respuesta tiene que ser un grafico vacio, no un 500: un
            # ``candles["open"]`` sobre un frame sin columnas lanza ``KeyError``.
            candle_rows: list[dict] = []
        else:
            candle_rows = _candle_rows(candles, indices)

        requested = sorted(set(feature_names)) if feature_names else []
        indicators: dict[str, list[dict]] = {}
        if requested:
            features = self._load_features_pivot(
                symbol,
                timeframe,
                date_from,
                date_to,
                requested,
                only_timestamps=timestamps,
            )
            for name in features.columns:
                series = features[name].dropna()
                if series.empty:
                    continue
                indicators[name] = [
                    {"timestamp": timestamp, "value": float(value)}
                    for timestamp, value in zip(
                        series.index.to_pydatetime(),
                        series.to_numpy(),
                        strict=True,
                    )
                ]
        missing = [name for name in requested if name not in indicators]

        occurrences: list[dict] = []
        markers: list[dict] = []
        if scan_job_id is not None:
            occurrences, _ = self.get_occurrences(
                job_id=scan_job_id,
                pattern_names=pattern_names,
                date_from=date_from,
                date_to=date_to,
                limit=5000,
            )

        for occurrence in occurrences:
            definition = catalog.get_definition(occurrence["pattern_name"])
            if definition is None:
                continue
            bullish = definition.direction == "bullish"
            markers.append(
                {
                    "timestamp": occurrence["timestamp"],
                    "pattern_name": definition.code,
                    "position": "belowBar" if bullish else "aboveBar",
                    "shape": "arrowUp" if bullish else "arrowDown",
                    "color": "#219653" if bullish else "#c0392b",
                    "text": definition.short_label,
                    "details": occurrence["details"],
                }
            )

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "date_from": date_from,
            "date_to": date_to,
            "candles": candle_rows,
            "indicators": indicators,
            "missing_indicators": missing,
            "markers": markers,
            "total_points": total_points,
            "returned": len(candle_rows),
            "step": paso,
            "sampled": paso > 1,
        }

    def get_available_data(self) -> list[dict]:
        """Que pares (simbolo, timeframe) se pueden escanear y con que features.

        Para patterns no basta con listar los pares que tienen velas como en
        ``FeatureService``: un escaneo falla con ``MissingFeaturesError`` si no
        estan precalculadas las features del patron, asi que el frontend
        necesita saber cuales hay para avisar antes de encolar el job.

        Caso habitual que conviene tener presente: los patrones ``MA_CROSS_*``
        necesitan ``EMA_<fast_length>`` y ``EMA_<slow_length>``, y con los
        parametros por defecto eso es ``EMA_20`` y ``EMA_50``. Si un par solo
        tiene ``EMA_20`` no puede escanearse con los valores por defecto, aunque
        tenga velas. No es un fallo del modulo: la feature hay que crearla en
        ``/features/new`` con longitud 50, esperar a que el Feature Job termine
        y recargar. Ajustar ``slow_length`` a un valor que ya exista es
        alternativa, y entonces el patron deja de ser el cruce 20/50 habitual.
        """
        from app.modules.data_import.models import Candle
        from app.modules.features.models import Feature

        with SessionLocal() as db:
            candle_rows = db.execute(
                select(
                    Candle.symbol,
                    Candle.timeframe,
                    func.count(),
                    func.min(Candle.timestamp),
                    func.max(Candle.timestamp),
                ).group_by(Candle.symbol, Candle.timeframe)
            ).all()
            indicator_rows = db.execute(
                select(
                    Feature.symbol,
                    Feature.timeframe,
                    func.array_agg(func.distinct(Feature.indicator_name)),
                ).group_by(Feature.symbol, Feature.timeframe)
            ).all()

        indicators_by_pair = {
            (symbol, timeframe): sorted(names or ())
            for symbol, timeframe, names in indicator_rows
        }

        return [
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "candles": count,
                "first_candle": first,
                "last_candle": last,
                "indicators": indicators_by_pair.get((symbol, timeframe), []),
            }
            for symbol, timeframe, count, first, last in candle_rows
        ]

    def get_occurrences_summary(
        self,
        symbol: str | None = None,
        timeframe: str | None = None,
        pattern_names: Sequence[str] | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> dict:
        """Resumen agregado de las ocurrencias, para las tarjetas del frontend.

        Todo son agregaciones en SQL (no se traen filas a Python): cuatro
        consultas ``GROUP BY`` en vez de un ``fetchall`` sobre la tabla, que es
        justamente lo que no hay que hacer sobre una hypertable.
        """
        conditions = []
        if symbol is not None:
            conditions.append(PatternOccurrence.symbol == symbol)
        if timeframe is not None:
            conditions.append(PatternOccurrence.timeframe == timeframe)
        if pattern_names:
            conditions.append(PatternOccurrence.pattern_name.in_(list(pattern_names)))
        if date_from is not None:
            conditions.append(PatternOccurrence.timestamp >= date_from)
        if date_to is not None:
            conditions.append(PatternOccurrence.timestamp <= date_to)

        with SessionLocal() as db:
            totals = db.execute(
                select(
                    func.count(),
                    func.count(func.distinct(PatternOccurrence.pattern_name)),
                    func.count(func.distinct(PatternOccurrence.symbol)),
                    func.min(PatternOccurrence.timestamp),
                    func.max(PatternOccurrence.timestamp),
                )
                .select_from(PatternOccurrence)
                .where(*conditions)
            ).one()
            by_pattern = db.execute(
                select(PatternOccurrence.pattern_name, func.count())
                .where(*conditions)
                .group_by(PatternOccurrence.pattern_name)
            ).all()
            by_symbol = db.execute(
                select(PatternOccurrence.symbol, func.count())
                .where(*conditions)
                .group_by(PatternOccurrence.symbol)
            ).all()
            by_timeframe = db.execute(
                select(PatternOccurrence.timeframe, func.count())
                .where(*conditions)
                .group_by(PatternOccurrence.timeframe)
            ).all()

        # La direccion se resuelve contra el catalogo en Python: son diez codigos
        # fijos, y traerlos a memoria sale mas barato que un JOIN con una tabla
        # que no existe en la base de datos.
        patterns = []
        bullish = bearish = 0
        for code, count in sorted(by_pattern, key=lambda item: (-item[1], item[0])):
            definition = catalog.get_definition(code)
            direction = definition.direction if definition else "unknown"
            if direction == "bullish":
                bullish += count
            elif direction == "bearish":
                bearish += count
            patterns.append(
                {
                    "pattern_name": code,
                    "count": count,
                    "direction": direction,
                    "group": definition.group if definition else None,
                }
            )

        return {
            "total": int(totals[0] or 0),
            "distinct_patterns": int(totals[1] or 0),
            "distinct_symbols": int(totals[2] or 0),
            "first_occurrence": totals[3],
            "last_occurrence": totals[4],
            "bullish": bullish,
            "bearish": bearish,
            "by_pattern": patterns,
            "by_symbol": [
                {"symbol": sym, "count": count}
                for sym, count in sorted(by_symbol, key=lambda i: (-i[1], i[0]))
            ],
            "by_timeframe": [
                {"timeframe": tf, "count": count}
                for tf, count in sorted(by_timeframe, key=lambda i: (-i[1], i[0]))
            ],
        }
