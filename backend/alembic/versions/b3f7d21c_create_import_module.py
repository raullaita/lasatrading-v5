import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "b3f7d21c"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")

    op.create_table(
        "import_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column(
            "source_type", sa.String(32), nullable=False, server_default="binance_api"
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("symbols", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "timeframes", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("date_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("date_to", sa.DateTime(timezone=True), nullable=False),
        sa.Column("import_mode", sa.String(16), nullable=False, server_default="merge"),
        sa.Column(
            "total_combinations", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column(
            "completed_combinations",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "failed_combinations", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column(
            "total_candles_downloaded",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "total_candles_inserted",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "total_candles_updated", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column(
            "error_summary",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_table(
        "import_job_combinations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("import_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("timeframe", sa.String(8), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "candles_downloaded", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column(
            "candles_inserted", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column(
            "candles_updated", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column("first_candle_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_candle_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.UniqueConstraint(
            "job_id", "symbol", "timeframe", name="uq_import_job_combinations"
        ),
    )
    op.create_index(
        "ix_import_job_combinations_job_id",
        "import_job_combinations",
        ["job_id"],
    )

    op.create_table(
        "import_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("import_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "combination_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("import_job_combinations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("level", sa.String(10), nullable=False, server_default="info"),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("progress", sa.BigInteger(), nullable=True),
    )
    op.create_index(
        "ix_import_logs_job_timestamp", "import_logs", ["job_id", "timestamp"]
    )

    op.create_table(
        "candles",
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("timeframe", sa.String(8), nullable=False),
        sa.Column("open", sa.Numeric(20, 8), nullable=False),
        sa.Column("high", sa.Numeric(20, 8), nullable=False),
        sa.Column("low", sa.Numeric(20, 8), nullable=False),
        sa.Column("close", sa.Numeric(20, 8), nullable=False),
        sa.Column("volume", sa.Numeric(20, 8), nullable=False),
        sa.Column("import_job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.PrimaryKeyConstraint("timestamp", "symbol", "timeframe"),
    )

    op.execute("SELECT create_hypertable('candles', 'timestamp')")

    op.create_foreign_key(
        "fk_candles_import_job",
        "candles",
        "import_jobs",
        ["import_job_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_index(
        "idx_candles_symbol_timeframe",
        "candles",
        ["symbol", "timeframe", sa.text("timestamp DESC")],
    )


def downgrade() -> None:
    op.drop_table("candles")
    op.drop_table("import_logs")
    op.drop_table("import_job_combinations")
    op.drop_table("import_jobs")
