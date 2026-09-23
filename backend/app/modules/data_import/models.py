import uuid
from datetime import datetime
from decimal import Decimal
from enum import Enum

import sqlalchemy as sa
from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class ImportStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ImportMode(str, Enum):
    MERGE = "merge"
    APPEND = "append"
    OVERWRITE = "overwrite"


class SourceType(str, Enum):
    BINANCE_API = "binance_api"


class LogLevel(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class ImportJob(Base):
    __tablename__ = "import_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    status: Mapped[str] = mapped_column(String(20), default=ImportStatus.PENDING.value)
    source_type: Mapped[str] = mapped_column(
        String(32), default=SourceType.BINANCE_API.value
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    symbols: Mapped[list] = mapped_column(JSONB, default=list)
    timeframes: Mapped[list] = mapped_column(JSONB, default=list)
    date_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    date_to: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    import_mode: Mapped[str] = mapped_column(String(16), default=ImportMode.MERGE.value)
    total_combinations: Mapped[int] = mapped_column(BigInteger, default=0)
    completed_combinations: Mapped[int] = mapped_column(BigInteger, default=0)
    failed_combinations: Mapped[int] = mapped_column(BigInteger, default=0)
    total_candles_downloaded: Mapped[int] = mapped_column(BigInteger, default=0)
    total_candles_inserted: Mapped[int] = mapped_column(BigInteger, default=0)
    total_candles_updated: Mapped[int] = mapped_column(BigInteger, default=0)
    total_candles_skipped: Mapped[int] = mapped_column(BigInteger, default=0)
    error_summary: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    combinations: Mapped[list["ImportJobCombination"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    logs: Mapped[list["ImportLog"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class ImportJobCombination(Base):
    __tablename__ = "import_job_combinations"
    __table_args__ = (
        UniqueConstraint(
            "job_id", "symbol", "timeframe", name="uq_import_job_combinations"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("import_jobs.id", ondelete="CASCADE"), index=True
    )
    symbol: Mapped[str] = mapped_column(String(32))
    timeframe: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(20), default=ImportStatus.PENDING.value)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    candles_downloaded: Mapped[int] = mapped_column(BigInteger, default=0)
    candles_inserted: Mapped[int] = mapped_column(BigInteger, default=0)
    candles_updated: Mapped[int] = mapped_column(BigInteger, default=0)
    candles_skipped: Mapped[int] = mapped_column(BigInteger, default=0)
    first_candle_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_candle_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    job: Mapped["ImportJob"] = relationship(back_populates="combinations")
    logs: Mapped[list["ImportLog"]] = relationship(
        back_populates="combination", cascade="all, delete-orphan"
    )


class ImportLog(Base):
    __tablename__ = "import_logs"
    __table_args__ = (Index("ix_import_logs_job_timestamp", "job_id", "timestamp"),)

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("import_jobs.id", ondelete="CASCADE")
    )
    combination_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("import_job_combinations.id", ondelete="SET NULL"),
        nullable=True,
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    level: Mapped[str] = mapped_column(String(10), default=LogLevel.INFO.value)
    message: Mapped[str] = mapped_column(Text)
    progress: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    job: Mapped["ImportJob"] = relationship(back_populates="logs")
    combination: Mapped["ImportJobCombination | None"] = relationship(
        back_populates="logs"
    )


class Candle(Base):
    __tablename__ = "candles"
    __table_args__ = (
        Index(
            "idx_candles_symbol_timeframe",
            "symbol",
            "timeframe",
            sa.text("timestamp DESC"),
        ),
    )

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True
    )
    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    timeframe: Mapped[str] = mapped_column(String(8), primary_key=True)
    open: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    high: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    low: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    close: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    volume: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    import_job_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("import_jobs.id", ondelete="SET NULL"),
        nullable=True,
    )
