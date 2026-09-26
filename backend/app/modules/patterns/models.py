import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class PatternScanJobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class LogLevel(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class PatternScanJob(Base):
    __tablename__ = "pattern_scan_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    status: Mapped[str] = mapped_column(
        String(20), default=PatternScanJobStatus.PENDING.value
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    date_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    date_to: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    patterns_config: Mapped[list] = mapped_column(JSONB, default=list)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    total_candles: Mapped[int] = mapped_column(BigInteger, default=0)
    processed_candles: Mapped[int] = mapped_column(BigInteger, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    logs: Mapped[list["PatternScanLog"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    occurrences: Mapped[list["PatternOccurrence"]] = relationship(
        back_populates="scan_job", cascade="all, delete-orphan"
    )


class PatternScanLog(Base):
    __tablename__ = "pattern_scan_logs"
    __table_args__ = (
        Index("ix_pattern_scan_logs_job_timestamp", "job_id", "timestamp"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("pattern_scan_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    level: Mapped[str] = mapped_column(String(10), default=LogLevel.INFO.value)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    progress: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    job: Mapped["PatternScanJob"] = relationship(back_populates="logs")


class PatternOccurrence(Base):
    __tablename__ = "pattern_occurrences"
    __table_args__ = (
        Index(
            "ix_pattern_occurrences_symbol_timeframe",
            "symbol",
            "timeframe",
            "timestamp",
        ),
        Index("ix_pattern_occurrences_job_id", "scan_job_id"),
        Index("ix_pattern_occurrences_pattern", "pattern_name", "timestamp"),
    )

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True
    )
    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    timeframe: Mapped[str] = mapped_column(String(8), primary_key=True)
    pattern_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    scan_job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("pattern_scan_jobs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    # El atributo se llama `details` porque `metadata` esta reservado en las
    # clases declarativas de SQLAlchemy (Base.metadata). La columna en base de
    # datos si se llama "metadata".
    details: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )

    scan_job: Mapped["PatternScanJob"] = relationship(back_populates="occurrences")
