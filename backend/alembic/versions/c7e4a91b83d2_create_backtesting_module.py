import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c7e4a91b83d2"
down_revision = "5b1d92fa4c73"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")

    op.create_table(
        "backtest_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("scan_job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("strategy", postgresql.JSONB, nullable=False),
        sa.Column(
            "initial_capital",
            sa.Numeric(20, 8),
            nullable=False,
            server_default="1000",
        ),
        sa.Column("equity_final", sa.Numeric(20, 8), nullable=True),
        sa.Column("total_trades", sa.Integer, nullable=False, server_default="0"),
        sa.Column("skipped_signals", sa.Integer, nullable=False, server_default="0"),
        sa.Column("truncated_trades", sa.Integer, nullable=False, server_default="0"),
        sa.Column("net_pnl", sa.Numeric(20, 8), nullable=True),
        sa.Column("total_return_pct", sa.Numeric(12, 6), nullable=True),
        sa.Column("win_rate", sa.Numeric(12, 6), nullable=True),
        sa.Column("profit_factor", sa.Numeric(12, 6), nullable=True),
        sa.Column("max_drawdown_pct", sa.Numeric(12, 6), nullable=True),
        sa.Column("sharpe_ratio", sa.Numeric(12, 6), nullable=True),
        sa.Column("avg_bars_held", sa.Numeric(12, 6), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_foreign_key(
        "fk_backtest_runs_scan_job",
        "backtest_runs",
        "pattern_scan_jobs",
        ["scan_job_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_backtest_runs_scan_job", "backtest_runs", ["scan_job_id"])
    op.create_index(
        "ix_backtest_runs_status_created",
        "backtest_runs",
        ["status", "created_at"],
    )

    op.create_table(
        "backtest_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("level", sa.String(10), nullable=False, server_default="info"),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("progress", sa.BigInteger, nullable=True),
    )
    op.create_foreign_key(
        "fk_backtest_logs_run",
        "backtest_logs",
        "backtest_runs",
        ["run_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_backtest_logs_run_timestamp",
        "backtest_logs",
        ["run_id", "timestamp"],
    )

    op.create_table(
        "backtest_trades",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("signal_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("pattern_name", sa.String(64), nullable=False),
        sa.Column("direction", sa.String(10), nullable=False),
        sa.Column("entry_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_price", sa.Numeric(20, 8), nullable=False),
        sa.Column("exit_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exit_price", sa.Numeric(20, 8), nullable=True),
        sa.Column("exit_reason", sa.String(16), nullable=True),
        sa.Column("quantity", sa.Numeric(24, 12), nullable=False),
        sa.Column("gross_pnl", sa.Numeric(20, 8), nullable=True),
        sa.Column("fees", sa.Numeric(20, 8), nullable=False, server_default="0"),
        sa.Column("net_pnl", sa.Numeric(20, 8), nullable=True),
        sa.Column("return_pct", sa.Numeric(12, 6), nullable=True),
        sa.Column("bars_held", sa.Integer, nullable=False, server_default="0"),
        sa.Column("equity_after", sa.Numeric(20, 8), nullable=True),
        sa.Column("mae", sa.Numeric(20, 8), nullable=True),
        sa.Column("mfe", sa.Numeric(20, 8), nullable=True),
    )
    op.create_foreign_key(
        "fk_backtest_trades_run",
        "backtest_trades",
        "backtest_runs",
        ["run_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_backtest_trades_run_exit",
        "backtest_trades",
        ["run_id", "exit_timestamp"],
    )
    op.create_index(
        "ix_backtest_trades_run_pattern",
        "backtest_trades",
        ["run_id", "pattern_name"],
    )
    op.create_index(
        "ix_backtest_trades_run_reason",
        "backtest_trades",
        ["run_id", "exit_reason"],
    )

    op.create_table(
        "backtest_equity_points",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("equity", sa.Numeric(20, 8), nullable=False),
        sa.Column("drawdown_pct", sa.Numeric(12, 6), nullable=False),
    )

    # La hypertable se crea despues de la tabla y antes de su FK, igual que en
    # las migraciones de features y patterns: TimescaleDB intercepta la creacion
    # de FKs sobre hypertables y necesita que la tabla ya este particionada.
    op.execute("SELECT create_hypertable('backtest_equity_points', 'timestamp')")

    op.create_foreign_key(
        "fk_backtest_equity_points_run",
        "backtest_equity_points",
        "backtest_runs",
        ["run_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_table("backtest_equity_points")
    op.drop_table("backtest_trades")
    op.drop_table("backtest_logs")
    op.drop_table("backtest_runs")
