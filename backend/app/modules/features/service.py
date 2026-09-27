import uuid
from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.database import SessionLocal
from app.modules.data.candles import load_candles
from app.modules.features.models import (
    Feature,
    FeatureJob,
    FeatureJobStatus,
    FeatureLog,
    LogLevel,
)
from app.modules.features.schemas import (
    FeatureJobConfig,
    IndicatorConfig,
)

INDICATOR_PARAM_DEFAULTS = {
    "SMA": {"length": 20},
    "EMA": {"length": 20},
    "RSI": {"length": 14},
    "MACD": {"fast": 12, "slow": 26, "signal": 9},
    "BBANDS": {"length": 20, "std": 2.0},
    "ATR": {"length": 14},
    "VOLUME_SMA": {"length": 20},
}


class CancelRequested(Exception):
    pass


class FeatureService:
    def __init__(self) -> None:
        self.settings = get_settings()

    def _log(
        self,
        db: Session,
        job_id: uuid.UUID,
        level: str,
        message: str,
        progress: int | None = None,
    ) -> None:
        db.add(
            FeatureLog(
                job_id=job_id,
                level=level,
                message=message,
                progress=progress,
            )
        )
        db.flush()

    @staticmethod
    def _is_cancelled(db: Session, job_id: uuid.UUID) -> bool:
        job = db.get(FeatureJob, job_id)
        return job is not None and job.status == FeatureJobStatus.CANCELLED.value

    def _mark_job(
        self,
        job_id: uuid.UUID,
        status: str,
        started_at: bool = False,
        finished_at: bool = False,
    ) -> None:
        with SessionLocal() as db:
            job = db.get(FeatureJob, job_id)
            if job is None:
                return
            job.status = status
            if started_at and job.started_at is None:
                job.started_at = datetime.now(timezone.utc)
            if finished_at and job.finished_at is None:
                job.finished_at = datetime.now(timezone.utc)
            db.commit()

    def create_job(self, db: Session, config: FeatureJobConfig) -> FeatureJob:
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

        indicators = [
            IndicatorConfig.model_validate(ind) if isinstance(ind, dict) else ind
            for ind in config.indicators
        ]

        job = FeatureJob(
            symbol=config.symbol,
            timeframe=config.timeframe,
            date_from=config.date_from,
            date_to=config.date_to,
            indicators_config=[ind.model_dump() for ind in indicators],
        )
        db.add(job)
        db.flush()
        self._log(
            db,
            job.id,
            LogLevel.INFO.value,
            f"Job creado para {job.symbol} {job.timeframe} "
            f"con {len(indicators)} indicadores",
        )
        db.commit()
        db.refresh(job)
        return job

    async def execute_job(self, job_id: uuid.UUID) -> None:
        try:
            self._mark_job(job_id, FeatureJobStatus.PROCESSING.value, started_at=True)
            with SessionLocal() as db:
                job = db.get(FeatureJob, job_id)
                if job is None:
                    return
                config = FeatureJobConfig(
                    symbol=job.symbol,
                    timeframe=job.timeframe,
                    date_from=job.date_from,
                    date_to=job.date_to,
                    indicators=[
                        IndicatorConfig.model_validate(ind)
                        for ind in job.indicators_config
                    ],
                )

            await self._run_calculation(job_id, config)
        except CancelRequested:
            self._mark_job(job_id, FeatureJobStatus.CANCELLED.value, finished_at=True)
            with SessionLocal() as db:
                self._log(
                    db, job_id, LogLevel.INFO.value, "Job cancelado por el usuario"
                )
                db.commit()
        except Exception as exc:
            self._mark_job(job_id, FeatureJobStatus.FAILED.value, finished_at=True)
            with SessionLocal() as db:
                self._log(
                    db,
                    job_id,
                    LogLevel.ERROR.value,
                    f"Error en cálculo: {str(exc)}",
                )
                job = db.get(FeatureJob, job_id)
                if job:
                    job.error_message = str(exc)[:500]
                    db.commit()

    async def _run_calculation(
        self, job_id: uuid.UUID, config: FeatureJobConfig
    ) -> None:
        df = load_candles(
            config.symbol, config.timeframe, config.date_from, config.date_to
        )
        if df.empty:
            raise ValueError("No se pudieron cargar datos de velas")

        total_indicators = len(config.indicators)
        total_candles = len(df)

        with SessionLocal() as db:
            job = db.get(FeatureJob, job_id)
            if job is None:
                return
            job.total_candles = total_candles
            db.commit()

        for idx, indicator_config in enumerate(config.indicators):
            indicator_name = indicator_config.name
            params = indicator_config.params or INDICATOR_PARAM_DEFAULTS.get(
                indicator_name, {}
            )

            with SessionLocal() as db:
                if self._is_cancelled(db, job_id):
                    raise CancelRequested()
                self._log(
                    db,
                    job_id,
                    LogLevel.INFO.value,
                    f"Calculando {indicator_name} con params {params}...",
                )
                db.commit()

            indicator_columns = self._calculate_indicator(df, indicator_name, params)
            if not indicator_columns:
                with SessionLocal() as db:
                    self._log(
                        db,
                        job_id,
                        LogLevel.WARNING.value,
                        f"{indicator_name}: No se generaron columnas",
                    )
                    db.commit()
                continue

            with SessionLocal() as db:
                self._save_features(
                    db, job_id, indicator_columns, indicator_name, params
                )

            progress = int(((idx + 1) / total_indicators) * 100)
            with SessionLocal() as db:
                self._log(
                    db,
                    job_id,
                    LogLevel.INFO.value,
                    f"{indicator_name}: Calculado ({progress}%)",
                    progress=progress,
                )
                db.commit()

        with SessionLocal() as db:
            job = db.get(FeatureJob, job_id)
            if job:
                job.processed_candles = total_candles
                job.status = FeatureJobStatus.COMPLETED.value
                job.finished_at = datetime.now(timezone.utc)
                self._log(
                    db,
                    job_id,
                    LogLevel.INFO.value,
                    f"Job completado: {total_candles} velas procesadas",
                )
                db.commit()

    def _calculate_indicator(
        self, df: pd.DataFrame, indicator_name: str, params: dict
    ) -> dict[str, pd.Series]:
        params = {k: v for k, v in params.items() if k != "on"}
        close = df["close"]
        high = df["high"]
        low = df["low"]
        volume = df["volume"]

        if indicator_name == "SMA":
            length = int(params.get("length", 20))
            return {f"SMA_{length}": close.rolling(window=length).mean()}

        if indicator_name == "EMA":
            length = int(params.get("length", 20))
            return {f"EMA_{length}": close.ewm(span=length, adjust=False).mean()}

        if indicator_name == "RSI":
            length = int(params.get("length", 14))
            delta = close.diff()
            gain = (
                delta.where(delta > 0, 0.0).ewm(alpha=1 / length, adjust=False).mean()
            )
            loss = (
                -delta.where(delta < 0, 0.0).ewm(alpha=1 / length, adjust=False).mean()
            )
            rs = gain / loss.where(loss != 0)
            rsi = 100.0 - (100.0 / (1.0 + rs))
            rsi = rsi.where(loss != 0, 100.0)
            return {f"RSI_{length}": rsi}

        if indicator_name == "MACD":
            fast = int(params.get("fast", 12))
            slow = int(params.get("slow", 26))
            signal = int(params.get("signal", 9))
            ema_fast = close.ewm(span=fast, adjust=False).mean()
            ema_slow = close.ewm(span=slow, adjust=False).mean()
            macd_line = ema_fast - ema_slow
            signal_line = macd_line.ewm(span=signal, adjust=False).mean()
            suffix = f"{fast}_{slow}_{signal}"
            return {
                f"MACD_{suffix}": macd_line,
                f"MACDs_{suffix}": signal_line,
                f"MACDh_{suffix}": macd_line - signal_line,
            }

        if indicator_name == "BBANDS":
            length = int(params.get("length", 20))
            std = float(params.get("std", 2.0))
            sma = close.rolling(window=length).mean()
            rolling_std = close.rolling(window=length).std()
            return {
                f"BBU_{length}_{std}": sma + std * rolling_std,
                f"BBM_{length}_{std}": sma,
                f"BBL_{length}_{std}": sma - std * rolling_std,
            }

        if indicator_name == "ATR":
            length = int(params.get("length", 14))
            prev_close = close.shift(1)
            tr = pd.concat(
                [
                    high - low,
                    (high - prev_close).abs(),
                    (low - prev_close).abs(),
                ],
                axis=1,
            ).max(axis=1)
            return {f"ATR_{length}": tr.rolling(window=length).mean()}

        if indicator_name == "VOLUME_SMA":
            length = int(params.get("length", 20))
            return {f"VOLUME_SMA_{length}": volume.rolling(window=length).mean()}

        return {}

    def _save_features(
        self,
        db: Session,
        job_id: uuid.UUID,
        columns: dict[str, pd.Series],
        indicator_name: str,
        params: dict,
    ) -> None:
        job = db.get(FeatureJob, job_id)
        if job is None:
            return
        symbol = job.symbol
        timeframe = job.timeframe

        total = len(columns)
        discarded_nans = 0
        saved = 0

        rows = []
        for col_name, series in columns.items():
            nan_count = int(series.isna().sum())
            discarded_nans += nan_count
            series_clean = series.dropna()

            for timestamp, value in series_clean.items():
                rows.append(
                    {
                        "timestamp": timestamp,
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "indicator_name": col_name,
                        "indicator_params": params,
                        "value": float(value),
                        "feature_job_id": job_id,
                    }
                )

            saved += len(series_clean)

        if not rows:
            self._log(
                db,
                job_id,
                LogLevel.INFO.value,
                f"{indicator_name}: 0 valores (todos NaN)",
            )
            return

        batch_size = 5000
        for i in range(0, len(rows), batch_size):
            batch = rows[i : i + batch_size]
            stmt = pg_insert(Feature).values(batch)
            stmt = stmt.on_conflict_do_update(
                index_elements=["timestamp", "symbol", "timeframe", "indicator_name"],
                set_={
                    "value": stmt.excluded.value,
                    "indicator_params": stmt.excluded.indicator_params,
                    "feature_job_id": stmt.excluded.feature_job_id,
                },
            )
            db.execute(stmt)
            db.flush()

        self._log(
            db,
            job_id,
            LogLevel.INFO.value,
            f"{indicator_name}: {total} columnas calculadas, "
            f"{discarded_nans} NaNs descartados, {saved} valores guardados",
        )
        db.commit()

    def cancel_job(self, job_id: uuid.UUID) -> bool:
        with SessionLocal() as db:
            job = db.get(FeatureJob, job_id)
            if job is None or job.status in (
                FeatureJobStatus.COMPLETED.value,
                FeatureJobStatus.FAILED.value,
                FeatureJobStatus.CANCELLED.value,
            ):
                return False
            job.status = FeatureJobStatus.CANCELLED.value
            job.finished_at = datetime.now(timezone.utc)
            self._log(
                db,
                job_id,
                LogLevel.INFO.value,
                "Cancelación solicitada",
            )
            db.commit()
            return True

    def delete_job(self, job_id: uuid.UUID) -> bool:
        with SessionLocal() as db:
            job = db.get(FeatureJob, job_id)
            if job is None:
                return False
            db.delete(job)
            db.commit()
            return True

    def requeue_job(self, job_id: uuid.UUID) -> bool:
        with SessionLocal() as db:
            job = db.get(FeatureJob, job_id)
            if job is None:
                return False
            if job.status in (
                FeatureJobStatus.COMPLETED.value,
                FeatureJobStatus.FAILED.value,
                FeatureJobStatus.CANCELLED.value,
            ):
                return False
            job.status = FeatureJobStatus.PENDING.value
            job.started_at = None
            job.finished_at = None
            job.processed_candles = 0
            self._log(
                db,
                job_id,
                LogLevel.INFO.value,
                "Job reenviado a la cola",
            )
            db.commit()
            return True

    def get_preview(self, job_id: uuid.UUID, limit: int = 100) -> list[dict]:
        with SessionLocal() as db:
            from app.modules.data_import.models import Candle

            job = db.get(FeatureJob, job_id)
            if job is None:
                return []

            timestamp_rows = (
                db.execute(
                    select(Feature.timestamp)
                    .where(Feature.feature_job_id == job_id)
                    .group_by(Feature.timestamp)
                    .order_by(Feature.timestamp)
                    .limit(limit)
                )
                .scalars()
                .all()
            )

            if not timestamp_rows:
                return []

            timestamps = list(timestamp_rows)
            feature_rows = db.scalars(
                select(Feature).where(
                    Feature.feature_job_id == job_id,
                    Feature.timestamp.in_(timestamps),
                )
            ).all()

            candles = db.scalars(
                select(Candle)
                .where(Candle.symbol == job.symbol)
                .where(Candle.timeframe == job.timeframe)
                .where(Candle.timestamp.in_(timestamps))
                .order_by(Candle.timestamp)
            ).all()

            candle_map = {c.timestamp: c for c in candles}

            pivoted: dict[datetime, dict[str, float]] = {}
            for fr in feature_rows:
                pivoted.setdefault(fr.timestamp, {})[fr.indicator_name] = float(
                    fr.value
                )

            preview = []
            for ts in timestamps:
                c = candle_map.get(ts)
                preview.append(
                    {
                        "timestamp": ts,
                        "open": float(c.open) if c else None,
                        "high": float(c.high) if c else None,
                        "low": float(c.low) if c else None,
                        "close": float(c.close) if c else None,
                        "volume": float(c.volume) if c else None,
                        "indicators": pivoted.get(ts, {}),
                    }
                )

            return preview

    def get_available_data(self) -> list[dict]:
        with SessionLocal() as db:
            from app.modules.data_import.models import Candle

            rows = db.execute(
                select(Candle.symbol, Candle.timeframe)
                .distinct()
                .order_by(Candle.symbol, Candle.timeframe)
            ).all()
            return [{"symbol": r[0], "timeframe": r[1]} for r in rows]

    def _finalize_job(self, job_id: uuid.UUID) -> None:
        with SessionLocal() as db:
            job = db.get(FeatureJob, job_id)
            if job is None:
                return
            if job.status == FeatureJobStatus.PROCESSING.value:
                job.status = FeatureJobStatus.COMPLETED.value
                job.finished_at = datetime.now(timezone.utc)
                db.commit()
