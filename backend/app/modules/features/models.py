import uuid
from datetime import datetime
from decimal import Decimal
from enum import Enum

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class FeatureJobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class LogLevel(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class FeatureJob(Base):
    __tablename__ = "feature_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    status: Mapped[str] = mapped_column(
        String(20), default=FeatureJobStatus.PENDING.value
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    date_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    date_to: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    indicators_config: Mapped[dict] = mapped_column(JSONB, default=dict)
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

    logs: Mapped[list["FeatureLog"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    features: Mapped[list["Feature"]] = relationship(
        back_populates="feature_job", cascade="save-update, merge"
    )


class FeatureLog(Base):
    __tablename__ = "feature_logs"
    __table_args__ = (Index("ix_feature_logs_job_timestamp", "job_id", "timestamp"),)

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("feature_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    level: Mapped[str] = mapped_column(String(10), default=LogLevel.INFO.value)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    progress: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    job: Mapped["FeatureJob"] = relationship(back_populates="logs")


class Feature(Base):
    __tablename__ = "features"
    __table_args__ = (
        Index("ix_features_symbol_timeframe", "symbol", "timeframe", "timestamp"),
        Index("ix_features_job_id", "feature_job_id"),
    )

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True
    )
    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    timeframe: Mapped[str] = mapped_column(String(8), primary_key=True)
    indicator_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    indicator_params: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    value: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    feature_job_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("feature_jobs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    feature_job: Mapped["FeatureJob | None"] = relationship(back_populates="features")
