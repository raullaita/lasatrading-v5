import sqlalchemy as sa
from alembic import op

revision = "1f3a9e2c"
down_revision = "b3f7d21c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "import_job_combinations",
        sa.Column("candles_skipped", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.add_column(
        "import_jobs",
        sa.Column("total_candles_skipped", sa.BigInteger(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("import_jobs", "total_candles_skipped")
    op.drop_column("import_job_combinations", "candles_skipped")