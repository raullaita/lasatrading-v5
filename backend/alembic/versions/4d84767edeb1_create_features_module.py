import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "4d84767edeb1"
down_revision = "1f3a9e2c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")

    op.create_table(
        "feature_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("timeframe", sa.String(8), nullable=False),
        sa.Column("date_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("date_to", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "indicators_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_candles", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column(
            "processed_candles",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
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
        "feature_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("feature_jobs.id", ondelete="CASCADE"),
            nullable=False,
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
        "ix_feature_logs_job_timestamp", "feature_logs", ["job_id", "timestamp"]
    )

    op.create_table(
        "features",
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("timeframe", sa.String(8), nullable=False),
        sa.Column("indicator_name", sa.String(64), nullable=False),
        sa.Column(
            "indicator_params",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("value", sa.Numeric(20, 8), nullable=False),
        sa.Column(
            "feature_job_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("timestamp", "symbol", "timeframe", "indicator_name"),
    )

    op.execute("SELECT create_hypertable('features', 'timestamp')")

    op.create_foreign_key(
        "fk_features_job",
        "features",
        "feature_jobs",
        ["feature_job_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_index(
        "ix_features_symbol_timeframe",
        "features",
        ["symbol", "timeframe", "timestamp"],
    )
    op.create_index("ix_features_job_id", "features", ["feature_job_id"])


def downgrade() -> None:
    op.drop_table("features")
    op.drop_table("feature_logs")
    op.drop_table("feature_jobs")
