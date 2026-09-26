import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "5b1d92fa4c73"
down_revision = "9c2e5f71a8d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")

    op.create_table(
        "pattern_scan_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("timeframe", sa.String(8), nullable=False),
        sa.Column("date_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("date_to", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "patterns_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
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
        "pattern_scan_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("pattern_scan_jobs.id", ondelete="CASCADE"),
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
        "ix_pattern_scan_logs_job_timestamp",
        "pattern_scan_logs",
        ["job_id", "timestamp"],
    )

    # El nombre de la columna es "metadata" en la base de datos, igual que en
    # la Tarea 3. Es un nombre corriente en PostgreSQL (no es palabra reservada),
    # asi que no necesita comillas, y SQLAlchemy lo escapa solo cuando hace
    # falta. El atributo Python se llama `details` para no chocar con
    # `Base.metadata` de la clase declarativa.
    op.create_table(
        "pattern_occurrences",
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("timeframe", sa.String(8), nullable=False),
        sa.Column("pattern_name", sa.String(64), nullable=False),
        # `scan_job_id` forma parte de la PK *y* es la FK. Al estar en la PK no
        # puede ser nullable ni llevar ON DELETE SET NULL (features si lo lleva
        # porque ahi `feature_job_id` queda fuera de la PK).
        sa.Column("scan_job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.PrimaryKeyConstraint(
            "timestamp", "symbol", "timeframe", "pattern_name", "scan_job_id"
        ),
    )

    # FK anadida despues de crear la hypertable, igual que en la migracion de
    # features: TimescaleDB intercepta la creacion de FKs sobre hypertables y
    # necesita que la tabla ya este particionada.
    op.execute("SELECT create_hypertable('pattern_occurrences', 'timestamp')")

    op.create_foreign_key(
        "fk_pattern_occurrences_job",
        "pattern_occurrences",
        "pattern_scan_jobs",
        ["scan_job_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.create_index(
        "ix_pattern_occurrences_symbol_timeframe",
        "pattern_occurrences",
        ["symbol", "timeframe", "timestamp"],
    )
    op.create_index(
        "ix_pattern_occurrences_job_id", "pattern_occurrences", ["scan_job_id"]
    )
    op.create_index(
        "ix_pattern_occurrences_pattern",
        "pattern_occurrences",
        ["pattern_name", "timestamp"],
    )


def downgrade() -> None:
    op.drop_table("pattern_occurrences")
    op.drop_table("pattern_scan_logs")
    op.drop_table("pattern_scan_jobs")
