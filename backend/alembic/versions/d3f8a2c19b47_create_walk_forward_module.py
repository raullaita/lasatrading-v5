"""Crea las cinco tablas del walk-forward.

Revision ID: d3f8a2c19b47
Revises: c7e4a91b83d2

Cinco tablas y no las tres que decia la §6 de la spec, y las dos desviaciones
tienen su motivo escrito en el docstring del modelo correspondiente, que es donde
se buscara cuando alguien se pregunte por que sobran dos:

- ``walk_forward_equity_points``: el endpoint de equity promete una fila por vela
  y ninguna de las otras la tiene. Sin ella, dibujar el grafico del informe
  obligaria a reejecutar el walk-forward entero.
- ``walk_forward_logs``: el progreso por ventana viaja por un WebSocket que
  sondea una tabla de logs, y la del backtest tiene FK a `backtest_runs`.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "d3f8a2c19b47"
down_revision = "c7e4a91b83d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------ runs
    op.create_table(
        "walk_forward_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("scan_job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("config", postgresql.JSONB, nullable=False),
        sa.Column("grid", postgresql.JSONB, nullable=False),
        sa.Column(
            "initial_capital",
            sa.Numeric(20, 8),
            nullable=False,
            server_default="1000",
        ),
        # Regla 4 del Contrato Estadistico: el numero de combinaciones evaluadas
        # se registra y se publica, no se deduce de las candidatas guardadas.
        sa.Column("simulations", sa.Integer, nullable=False, server_default="0"),
        sa.Column("windows", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "windows_without_selection",
            sa.Integer,
            nullable=False,
            server_default="0",
        ),
        sa.Column("equity_final", sa.Numeric(20, 8), nullable=True),
        sa.Column("oos_return_pct", sa.Numeric(12, 6), nullable=True),
        sa.Column("market_return_pct", sa.Numeric(12, 6), nullable=True),
        sa.Column("max_drawdown_pct", sa.Numeric(12, 6), nullable=True),
        sa.Column("elapsed_ms", sa.Integer, nullable=True),
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
        "fk_walk_forward_runs_scan_job",
        "walk_forward_runs",
        "pattern_scan_jobs",
        ["scan_job_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_walk_forward_runs_scan_job", "walk_forward_runs", ["scan_job_id"]
    )
    op.create_index("ix_walk_forward_runs_status", "walk_forward_runs", ["status"])
    op.create_index("ix_walk_forward_runs_created", "walk_forward_runs", ["created_at"])

    # --------------------------------------------------------------- windows
    # PK compuesta (run_id, index): una ventana por run, sin id propio, porque
    # el indice de la ventana ES su identidad dentro del run.
    op.create_table(
        "walk_forward_windows",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("index", sa.Integer, nullable=False),
        sa.Column("is_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_to", sa.DateTime(timezone=True), nullable=False),
        sa.Column("oos_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("oos_to", sa.DateTime(timezone=True), nullable=False),
        sa.Column("selected_strategy", postgresql.JSONB, nullable=False),
        sa.Column("is_sharpe", sa.Numeric(12, 6), nullable=True),
        sa.Column("oos_trades", sa.Integer, nullable=False, server_default="0"),
        sa.Column("oos_evaluated", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "oos_return_pct", sa.Numeric(12, 6), nullable=False, server_default="0"
        ),
        sa.Column("oos_net_pnl", sa.Numeric(20, 8), nullable=False, server_default="0"),
        sa.Column(
            "oos_equity_final",
            sa.Numeric(20, 8),
            nullable=False,
            server_default="1000",
        ),
        sa.Column("oos_win_rate", sa.Numeric(12, 6), nullable=True),
        sa.Column("oos_sharpe", sa.Numeric(12, 6), nullable=True),
        sa.Column(
            "oos_max_drawdown_pct",
            sa.Numeric(12, 6),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "market_return_pct", sa.Numeric(12, 6), nullable=False, server_default="0"
        ),
        sa.Column(
            "market_max_drawdown_pct",
            sa.Numeric(12, 6),
            nullable=False,
            server_default="0",
        ),
        sa.Column("exits", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.PrimaryKeyConstraint("run_id", "index", name="pk_walk_forward_windows"),
    )
    op.create_foreign_key(
        "fk_walk_forward_windows_run",
        "walk_forward_windows",
        "walk_forward_runs",
        ["run_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_walk_forward_windows_run", "walk_forward_windows", ["run_id"])

    # ------------------------------------------------------------ candidates
    op.create_table(
        "walk_forward_candidates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rank", sa.Integer, nullable=False, server_default="0"),
        # `take_profit_pct` y `stop_loss_pct` pueden ser NULL a proposito:
        # "sin take profit" no es "take profit del 0%". Por eso la clave natural
        # va en un indice UNIQUE con NULLS NOT DISTINCT (Postgres 15) y no en la
        # PK, donde un NULL no puede estar.
        sa.Column("take_profit_pct", sa.Numeric(12, 6), nullable=True),
        sa.Column("stop_loss_pct", sa.Numeric(12, 6), nullable=True),
        sa.Column("max_hold", sa.Integer, nullable=False),
        sa.Column("windows", sa.Integer, nullable=False, server_default="0"),
        sa.Column("trades", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "beats_market_windows", sa.Integer, nullable=False, server_default="0"
        ),
        sa.Column("profitable_windows", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "oos_return_pct", sa.Numeric(12, 6), nullable=False, server_default="0"
        ),
        sa.Column(
            "market_return_pct", sa.Numeric(12, 6), nullable=False, server_default="0"
        ),
        sa.Column(
            "win_rate_mean", sa.Numeric(12, 6), nullable=False, server_default="0"
        ),
        sa.Column("sharpe_mean", sa.Numeric(12, 6), nullable=False, server_default="0"),
        sa.Column(
            "sharpe_dispersion", sa.Numeric(12, 6), nullable=False, server_default="0"
        ),
        sa.Column(
            "max_drawdown_worst", sa.Numeric(12, 6), nullable=False, server_default="0"
        ),
        sa.Column("consistency", sa.Numeric(12, 6), nullable=False, server_default="0"),
        sa.Column("score", sa.Numeric(12, 6), nullable=False, server_default="0"),
        sa.Column(
            "verdict", sa.String(20), nullable=False, server_default="descartada"
        ),
        sa.Column("ci95_low", sa.Numeric(12, 6), nullable=True),
        sa.Column("ci95_high", sa.Numeric(12, 6), nullable=True),
        sa.Column("rejections", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("notes", postgresql.JSONB, nullable=False, server_default="[]"),
    )
    op.create_foreign_key(
        "fk_walk_forward_candidates_run",
        "walk_forward_candidates",
        "walk_forward_runs",
        ["run_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_walk_forward_candidates_run", "walk_forward_candidates", ["run_id"]
    )
    # La unicidad de la clave natural por run, con NULLS NOT DISTINCT para que
    # "sin TP" y "sin TP" colisionen de verdad. Sin esto, un requeue podria
    # dejar dos filas para la misma combinacion y la tabla del informe
    # mostraria duplicados sin motivo aparente.
    op.create_index(
        "uq_walk_forward_candidates_strategy",
        "walk_forward_candidates",
        ["run_id", "take_profit_pct", "stop_loss_pct", "max_hold"],
        unique=True,
        postgresql_nulls_not_distinct=True,
    )

    # ---------------------------------------------------------------- equity
    # La hypertable se crea despues de la tabla y antes de su FK, igual que en
    # `backtest_equity_points`: TimescaleDB no admite FKs sobre hypertables y
    # necesita que la tabla ya este particionada.
    op.create_table(
        "walk_forward_equity_points",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("equity", sa.Numeric(20, 8), nullable=False),
        sa.Column("market_equity", sa.Numeric(20, 8), nullable=False),
        sa.Column("drawdown_pct", sa.Numeric(12, 6), nullable=False),
        sa.Column("window_index", sa.Integer, nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint(
            "run_id", "timestamp", name="pk_walk_forward_equity_points"
        ),
    )
    op.execute("SELECT create_hypertable('walk_forward_equity_points', 'timestamp')")
    op.create_foreign_key(
        "fk_walk_forward_equity_run",
        "walk_forward_equity_points",
        "walk_forward_runs",
        ["run_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # ------------------------------------------------------------------ logs
    # Quinta tabla, y la segunda desviacion de la §6 de la spec. El motivo esta
    # en el docstring de ``WalkForwardLog``: el WebSocket del progreso por
    # ventana sondea una tabla de logs con paginacion por offset, y la del
    # backtest tiene clave foranea a `backtest_runs`. Un walk-forward no es un
    # backtest y no puede escribir en la tabla de otro.
    op.create_table(
        "walk_forward_logs",
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
        "fk_walk_forward_logs_run",
        "walk_forward_logs",
        "walk_forward_runs",
        ["run_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_walk_forward_logs_run_timestamp",
        "walk_forward_logs",
        ["run_id", "timestamp"],
    )


def downgrade() -> None:
    op.drop_table("walk_forward_logs")
    op.drop_table("walk_forward_equity_points")
    op.drop_table("walk_forward_candidates")
    op.drop_table("walk_forward_windows")
    op.drop_table("walk_forward_runs")
