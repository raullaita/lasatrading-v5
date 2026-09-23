import uuid
from collections import Counter
from datetime import datetime, timezone

from sqlalchemy import delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.database import SessionLocal
from app.modules.data_import.binance_client import BinanceClient, BinanceClientError
from app.modules.data_import.models import (
    Candle,
    ImportJob,
    ImportJobCombination,
    ImportLog,
    ImportMode,
    ImportStatus,
    LogLevel,
)
from app.modules.data_import.schemas import CandleRaw, ImportConfig

TIMEFRAME_MS = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
    "6h": 21_600_000,
    "8h": 28_800_000,
    "12h": 43_200_000,
    "1d": 86_400_000,
    "3d": 259_200_000,
    "1w": 604_800_000,
}


class CancelRequested(Exception):
    pass


class ImportService:
    def __init__(self) -> None:
        self.settings = get_settings()

    @staticmethod
    def _ms_to_dt(ms: int) -> datetime:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)

    @staticmethod
    def _log(
        db: Session,
        job_id,
        combination_id,
        level: LogLevel,
        message: str,
        progress: int | None = None,
    ) -> None:
        db.add(
            ImportLog(
                job_id=job_id,
                combination_id=combination_id,
                level=level.value,
                message=message,
                progress=progress,
            )
        )

    def create_job(
        self,
        db: Session,
        config: ImportConfig,
        combinations: list[tuple[str, str]] | None = None,
    ) -> ImportJob:
        if combinations is None:
            combinations = [
                (symbol, timeframe)
                for symbol in config.symbols
                for timeframe in config.timeframes
            ]
        symbols = sorted({symbol for symbol, _ in combinations})
        timeframes = sorted({timeframe for _, timeframe in combinations})
        job = ImportJob(
            symbols=symbols,
            timeframes=timeframes,
            date_from=config.date_from,
            date_to=config.date_to,
            import_mode=config.import_mode.value,
            total_combinations=len(combinations),
        )
        db.add(job)
        db.flush()
        for symbol, timeframe in combinations:
            db.add(
                ImportJobCombination(
                    job_id=job.id,
                    symbol=symbol,
                    timeframe=timeframe,
                )
            )
        self._log(
            db,
            job.id,
            None,
            LogLevel.INFO,
            f"Job creado con {job.total_combinations} combinaciones",
        )
        db.commit()
        db.refresh(job)
        return job

    def retry_failed(self, job_id: uuid.UUID) -> uuid.UUID | None:
        with SessionLocal() as db:
            job = db.get(ImportJob, job_id)
            if job is None:
                return None
            combos = list(
                db.scalars(
                    select(ImportJobCombination).where(
                        ImportJobCombination.job_id == job_id,
                        ImportJobCombination.status.in_(
                            [
                                ImportStatus.FAILED.value,
                                ImportStatus.CANCELLED.value,
                            ]
                        ),
                    )
                ).all()
            )
            pairs = [(c.symbol, c.timeframe) for c in combos]
            if not pairs:
                return None
            config = ImportConfig(
                symbols=[symbol for symbol, _ in pairs],
                timeframes=[timeframe for _, timeframe in pairs],
                date_from=job.date_from,
                date_to=job.date_to,
                import_mode=ImportMode(job.import_mode),
            )
            new_job = self.create_job(db, config, combinations=pairs)
            self._log(
                db,
                new_job.id,
                None,
                LogLevel.INFO,
                f"Job de reintento creado a partir de {str(job_id)[:8]} "
                f"con {len(pairs)} combinaciones",
            )
            db.commit()
            db.refresh(new_job)
            return new_job.id

    async def execute_job(self, job_id: uuid.UUID) -> None:
        client = BinanceClient()
        try:
            self._mark_job(job_id, ImportStatus.PROCESSING, started_at=True)
            combinations = self._fetch_combinations(job_id)
            for combo in combinations:
                try:
                    await self._process_combination(job_id, combo.id, client)
                except CancelRequested:
                    self._mark_combination(
                        combo.id, ImportStatus.CANCELLED, finished_at=True
                    )
                    break
                except BinanceClientError as exc:
                    self._fail_combination(combo.id, str(exc))
                    continue
            self._finalize_job(job_id)
        finally:
            await client.close()

    async def _process_combination(
        self, job_id: uuid.UUID, combination_id: uuid.UUID, client: BinanceClient
    ) -> None:
        with SessionLocal() as db:
            combo = db.get(ImportJobCombination, combination_id)
            job = db.get(ImportJob, job_id)
            if combo is None or job is None:
                return
            symbol = combo.symbol
            timeframe = combo.timeframe
            import_mode = job.import_mode
            start_ms = int(job.date_from.timestamp() * 1000)
            end_ms = int(job.date_to.timestamp() * 1000)
            combo.status = ImportStatus.PROCESSING.value
            combo.started_at = datetime.now(timezone.utc)
            self._log(
                db,
                job_id,
                combination_id,
                LogLevel.INFO,
                f"Procesando {symbol} {timeframe}",
            )
            db.commit()

        timeframe_ms = TIMEFRAME_MS.get(timeframe)
        if timeframe_ms is None:
            raise BinanceClientError(f"Timeout desconocido: {timeframe}")

        chunk_ms = self.settings.BINANCE_KLINES_LIMIT * timeframe_ms
        cursor = start_ms

        downloaded = 0
        inserted = 0
        updated = 0
        skipped = 0
        discarded = 0
        quality_errors: Counter[str] = Counter()
        first_at_ms: int | None = None
        last_at_ms: int | None = None

        while cursor <= end_ms:
            if self._is_cancelled(job_id):
                raise CancelRequested()
            batch_end = min(cursor + chunk_ms, end_ms)
            candles = await client.get_klines(symbol, timeframe, cursor, batch_end)
            if not candles:
                break
            downloaded += len(candles)
            valid, errors = self._validate_candles(candles)
            discarded += len(errors)
            for kind in errors:
                quality_errors[kind] += 1
            if valid:
                for candle in valid:
                    if first_at_ms is None or candle.open_time_ms < first_at_ms:
                        first_at_ms = candle.open_time_ms
                    if last_at_ms is None or candle.open_time_ms > last_at_ms:
                        last_at_ms = candle.open_time_ms
                written = self._write_candles(
                    job_id, combination_id, symbol, timeframe, valid, import_mode
                )
                inserted += written["inserted"]
                updated += written["updated"]
                skipped += written["skipped"]
            with SessionLocal() as db:
                combo = db.get(ImportJobCombination, combination_id)
                if combo is None:
                    raise CancelRequested()
                combo.candles_downloaded = downloaded
                combo.candles_inserted = inserted
                combo.candles_updated = updated
                combo.candles_skipped = skipped
                if first_at_ms is not None:
                    combo.first_candle_at = self._ms_to_dt(first_at_ms)
                    combo.last_candle_at = self._ms_to_dt(last_at_ms)
                self._log(
                    db,
                    job_id,
                    combination_id,
                    LogLevel.INFO,
                    f"Chunk hasta {_ms_dt_str(batch_end)}: {len(candles)} velas "
                    f"(I {inserted} / U {updated} / S {skipped})",
                    progress=downloaded,
                )
                db.commit()
            cursor = (
                last_at_ms + 1
                if last_at_ms is not None and last_at_ms + 1 > cursor
                else cursor + chunk_ms
            )

        with SessionLocal() as db:
            combo = db.get(ImportJobCombination, combination_id)
            if combo is None:
                return
            combo.status = ImportStatus.COMPLETED.value
            combo.finished_at = datetime.now(timezone.utc)
            combo.candles_downloaded = downloaded
            combo.candles_inserted = inserted
            combo.candles_updated = updated
            combo.candles_skipped = skipped
            if first_at_ms is not None:
                combo.first_candle_at = self._ms_to_dt(first_at_ms)
                combo.last_candle_at = self._ms_to_dt(last_at_ms)
            self._log(
                db,
                job_id,
                combination_id,
                LogLevel.INFO,
                f"Completado {symbol} {timeframe}: {inserted} insertadas, "
                f"{updated} actualizadas, {skipped} idénticas omitidas, "
                f"{discarded} descartadas",
            )
            db.commit()
        self._update_job_progress(job_id)

    @staticmethod
    def _validate_candles(
        candles: list[CandleRaw],
    ) -> tuple[list[CandleRaw], list[str]]:
        valid: list[CandleRaw] = []
        errors: list[str] = []
        for candle in candles:
            max_oc = max(candle.open, candle.close)
            min_oc = min(candle.open, candle.close)
            if candle.high < max_oc:
                errors.append("high < max(open, close)")
                continue
            if candle.low > min_oc:
                errors.append("low > min(open, close)")
                continue
            if candle.high < candle.low:
                errors.append("high < low")
                continue
            if candle.volume < 0:
                errors.append("volume < 0")
                continue
            valid.append(candle)
        return valid, errors

    def _write_candles(
        self,
        job_id: uuid.UUID,
        combination_id: uuid.UUID,
        symbol: str,
        timeframe: str,
        candles: list[CandleRaw],
        mode: str,
    ) -> dict:
        rows = [
            {
                "timestamp": self._ms_to_dt(candle.open_time_ms),
                "symbol": symbol,
                "timeframe": timeframe,
                "open": candle.open,
                "high": candle.high,
                "low": candle.low,
                "close": candle.close,
                "volume": candle.volume,
                "import_job_id": job_id,
            }
            for candle in candles
        ]
        with SessionLocal() as db:
            if mode == ImportMode.OVERWRITE.value:
                db.execute(
                    delete(Candle).where(
                        Candle.symbol == symbol,
                        Candle.timeframe == timeframe,
                        Candle.timestamp >= rows[0]["timestamp"],
                        Candle.timestamp <= rows[-1]["timestamp"],
                    )
                )
                db.execute(pg_insert(Candle).values(rows))
                db.commit()
                return {"inserted": len(rows), "updated": 0, "skipped": 0}

            existing_map = {
                ts: (open_, high, low, close, volume)
                for ts, open_, high, low, close, volume in db.execute(
                    select(
                        Candle.timestamp,
                        Candle.open,
                        Candle.high,
                        Candle.low,
                        Candle.close,
                        Candle.volume,
                    ).where(
                        Candle.symbol == symbol,
                        Candle.timeframe == timeframe,
                        Candle.timestamp.in_([r["timestamp"] for r in rows]),
                    )
                )
            }

            new_rows: list[dict] = []
            different_rows: list[dict] = []
            identical_rows: list[dict] = []
            for row in rows:
                values = existing_map.get(row["timestamp"])
                if values is None:
                    new_rows.append(row)
                    continue
                if (
                    row["open"],
                    row["high"],
                    row["low"],
                    row["close"],
                    row["volume"],
                ) == values:
                    identical_rows.append(row)
                else:
                    different_rows.append(row)

            stmt = pg_insert(Candle).values(rows)
            if mode == ImportMode.MERGE.value:
                excluded = stmt.excluded
                stmt = stmt.on_conflict_do_update(
                    index_elements=["timestamp", "symbol", "timeframe"],
                    set_={
                        "open": excluded.open,
                        "high": excluded.high,
                        "low": excluded.low,
                        "close": excluded.close,
                        "volume": excluded.volume,
                        "import_job_id": excluded.import_job_id,
                    },
                    where=or_(
                        Candle.open.is_distinct_from(excluded.open),
                        Candle.high.is_distinct_from(excluded.high),
                        Candle.low.is_distinct_from(excluded.low),
                        Candle.close.is_distinct_from(excluded.close),
                        Candle.volume.is_distinct_from(excluded.volume),
                    ),
                )
                inserted, updated = len(new_rows), len(different_rows)
            else:
                stmt = stmt.on_conflict_do_nothing()
                inserted, updated = len(new_rows), 0
            db.execute(stmt)
            db.commit()
        return {
            "inserted": inserted,
            "updated": updated,
            "skipped": len(identical_rows),
        }

    def _is_cancelled(self, job_id: uuid.UUID) -> bool:
        with SessionLocal() as db:
            job = db.get(ImportJob, job_id)
            return job is not None and job.status == ImportStatus.CANCELLED.value

    def _mark_job(
        self, job_id: uuid.UUID, status: ImportStatus, started_at: bool = False
    ) -> None:
        with SessionLocal() as db:
            job = db.get(ImportJob, job_id)
            if job is None:
                return
            job.status = status.value
            if started_at and job.started_at is None:
                job.started_at = datetime.now(timezone.utc)
            db.commit()

    def _mark_combination(
        self, combination_id: uuid.UUID, status: ImportStatus, finished_at: bool = False
    ) -> None:
        with SessionLocal() as db:
            combo = db.get(ImportJobCombination, combination_id)
            if combo is None:
                return
            combo.status = status.value
            if finished_at:
                combo.finished_at = datetime.now(timezone.utc)
            db.commit()

    def _fail_combination(self, combination_id: uuid.UUID, message: str) -> None:
        with SessionLocal() as db:
            combo = db.get(ImportJobCombination, combination_id)
            if combo is None:
                return
            combo.status = ImportStatus.FAILED.value
            combo.finished_at = datetime.now(timezone.utc)
            combo.error_message = message[:500]
            self._log(
                db, combo.job_id, combination_id, LogLevel.ERROR, f"Fallo: {message}"
            )
            db.commit()
        self._update_job_progress(combo.job_id)

    def _update_job_progress(self, job_id: uuid.UUID) -> None:
        with SessionLocal() as db:
            job = db.get(ImportJob, job_id)
            if job is None:
                return
            job.completed_combinations = (
                db.scalar(
                    select(func.count())
                    .select_from(ImportJobCombination)
                    .where(
                        ImportJobCombination.job_id == job_id,
                        ImportJobCombination.status == ImportStatus.COMPLETED.value,
                    )
                )
                or 0
            )
            job.failed_combinations = (
                db.scalar(
                    select(func.count())
                    .select_from(ImportJobCombination)
                    .where(
                        ImportJobCombination.job_id == job_id,
                        ImportJobCombination.status == ImportStatus.FAILED.value,
                    )
                )
                or 0
            )
            db.commit()

    def _fetch_combinations(self, job_id: uuid.UUID) -> list[ImportJobCombination]:
        with SessionLocal() as db:
            return list(
                db.scalars(
                    select(ImportJobCombination).where(
                        ImportJobCombination.job_id == job_id
                    )
                ).all()
            )

    def _finalize_job(self, job_id: uuid.UUID) -> None:
        with SessionLocal() as db:
            job = db.get(ImportJob, job_id)
            if job is None:
                return
            cancelled = job.status == ImportStatus.CANCELLED.value
            combos = list(
                db.scalars(
                    select(ImportJobCombination).where(
                        ImportJobCombination.job_id == job_id
                    )
                ).all()
            )
            job.total_candles_downloaded = sum(c.candles_downloaded for c in combos)
            job.total_candles_inserted = sum(c.candles_inserted for c in combos)
            job.total_candles_updated = sum(c.candles_updated for c in combos)
            job.total_candles_skipped = sum(c.candles_skipped for c in combos)
            job.completed_combinations = sum(
                1 for c in combos if c.status == ImportStatus.COMPLETED.value
            )
            job.failed_combinations = sum(
                1 for c in combos if c.status == ImportStatus.FAILED.value
            )
            if not cancelled:
                if job.completed_combinations == 0 and job.failed_combinations > 0:
                    job.status = ImportStatus.FAILED.value
                else:
                    job.status = ImportStatus.COMPLETED.value
                failures = [
                    c.error_message
                    for c in combos
                    if c.status == ImportStatus.FAILED.value and c.error_message
                ]
                summary = dict(job.error_summary or {})
                if failures:
                    summary["failed_combinations"] = failures[:20]
                job.error_summary = summary
                job.finished_at = datetime.now(timezone.utc)
                self._log(
                    db,
                    job_id,
                    None,
                    LogLevel.INFO,
                    f"Job finalizado: {job.completed_combinations} ok, "
                    f"{job.failed_combinations} fallidas",
                )
            db.commit()


def _ms_dt_str(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
