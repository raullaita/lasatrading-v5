"""Crea las tres tablas de alertas.

Revision ID: 8e4c1b7d92a0
Revises: d3f8a2c19b47

Las tres en una migracion porque son inseparables: una regla sin alertas es
configuracion, y un aviso sin regla es ruido. Dejarlas en revisiones sueltas
solo buy una migration mas para el estado intermedio que no le sirve a nadie.

Lo de esta migracion que conviene no perder de vista:

- El indice unico ``(rule_id, signal_timestamp)`` es la deduplicacion. Sin el, la
  misma vela puede generar dos avisos de la misma regla cada vez que dos
  evaluaciones se solapen, y se comprueba en §4.3 de la spec.
- ``walk_forward_runs`` es ``SET NULL`` y no ``CASCADE`` a proposito: el respaldo
  de una regla es evidencia acumulada, y que el usuario borre un informe no
  debe dejarle la regla sin la conclusion en la que se baso.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "8e4c1b7d92a0"
down_revision = "d3f8a2c19b47"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------------------------------------------------------------- reglas
    op.create_table(
        "alert_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("timeframe", sa.String(8), nullable=False),
        sa.Column("pattern_name", sa.String(64), nullable=False),
        sa.Column("direction", sa.String(10), nullable=False),
        sa.Column("config", postgresql.JSONB, nullable=False),
        # Nullable: el veredicto vive en el walk-forward, no en un backtest. Ver
        # el docstring de `AlertRule.backtest_run_id`.
        sa.Column("backtest_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("walk_forward_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("candidate_rank", sa.Integer, nullable=True),
        # El estado de validacion va en su propia columna y `sin_evaluar` es un
        # valor de primera clase, no un NULL: es la columna que decide si el aviso
        # lleva candil verde o rojo, y un NULL ahi es un caso especial esperando a
        # que alguien lo olvide.
        sa.Column(
            "validation_status",
            sa.String(20),
            nullable=False,
            server_default="sin_evaluar",
        ),
        sa.Column("validation_note", sa.Text, nullable=True),
        sa.Column(
            "pattern_coverage",
            sa.String(20),
            nullable=False,
            server_default="sin_informe",
        ),
        sa.Column("backing_oi_low", sa.Numeric(14, 6), nullable=True),
        sa.Column("backing_oi_high", sa.Numeric(14, 6), nullable=True),
        sa.Column("backing_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("backing_oos_return_pct", sa.Numeric(12, 6), nullable=True),
        sa.Column("backing_market_return_pct", sa.Numeric(12, 6), nullable=True),
        sa.Column("backing_windows", sa.Integer, nullable=True),
        sa.Column("channel", sa.String(20), nullable=False, server_default="telegram"),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("cooldown_minutes", sa.Integer, nullable=False, server_default="60"),
        # Existe y nunca se rellena. Los detectores son booleanos y no hay un
        # numero de confianza del patron; el campo esta para que el motivo quede
        # al lado y nadie lo rellene con un numero inventado.
        sa.Column("min_confidence", sa.Numeric(12, 6), nullable=True),
        sa.Column("last_alerted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_evaluated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_evaluation_note", sa.Text, nullable=True),
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
    # `SET NULL`: un backtest es evidencia opcional que el usuario puede borrar
    # sin que la regla pierda su veredicto, que esta en la misma fila.
    op.create_foreign_key(
        "fk_alert_rules_backtest_run",
        "alert_rules",
        "backtest_runs",
        ["backtest_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # `SET NULL`: borrar el informe de walk-forward no debe borrar la regla. La
    # evidencia ya esta copiada en la fila (verdict + IC + fecha).
    op.create_foreign_key(
        "fk_alert_rules_walk_forward_run",
        "alert_rules",
        "walk_forward_runs",
        ["walk_forward_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_alert_rules_symbol", "alert_rules", ["symbol", "timeframe"])
    op.create_index("ix_alert_rules_enabled", "alert_rules", ["enabled"])

    # --------------------------------------------------------------- alertas
    op.create_table(
        "alerts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("rule_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("signal_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("pattern_name", sa.String(64), nullable=False),
        sa.Column("direction", sa.String(10), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("timeframe", sa.String(8), nullable=False),
        # Cierre de la vela de la señal. NO es el precio de entrada: la entrada es
        # la apertura de T+1, que en el momento del aviso aun no ha ocurrido.
        sa.Column("reference_price", sa.Numeric(20, 8), nullable=False),
        sa.Column(
            "detected_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("telegram_message_id", sa.BigInteger, nullable=True),
        sa.Column("delivery_error", sa.Text, nullable=True),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("message_text", sa.Text, nullable=True),
    )
    op.create_foreign_key(
        "fk_alerts_rule",
        "alerts",
        "alert_rules",
        ["rule_id"],
        ["id"],
        ondelete="CASCADE",
    )
    # La deduplicacion. Un indice unico y no logica de servicio, porque una
    # garantia que depende de que nadie se equivoque no es una garantia: la
    # reejecucion de una tarea o dos workers producen el mismo par.
    op.create_unique_constraint(
        "uq_alerts_rule_signal", "alerts", ["rule_id", "signal_timestamp"]
    )
    op.create_index("ix_alerts_rule_status", "alerts", ["rule_id", "status"])
    op.create_index("ix_alerts_detected", "alerts", ["detected_at"])

    # ------------------------------------------------------------ deliveries
    op.create_table(
        "alert_deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("alert_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attempt", sa.Integer, nullable=False),
        sa.Column("http_status", sa.Integer, nullable=True),
        sa.Column("response_body", sa.Text, nullable=True),
        sa.Column("ok", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column(
            "attempted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_foreign_key(
        "fk_alert_deliveries_alert",
        "alert_deliveries",
        "alerts",
        ["alert_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_alert_deliveries_alert", "alert_deliveries", ["alert_id", "attempt"]
    )


def downgrade() -> None:
    op.drop_table("alert_deliveries")
    op.drop_table("alerts")
    op.drop_table("alert_rules")
