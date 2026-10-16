"""Layer 9: findings_reports table.

Revision ID: 0010
Revises: 0009
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: Union[str, Sequence[str], None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "findings_reports",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(32),
            sa.ForeignKey("compile_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("report", sa.JSON, nullable=False),
        sa.Column("stats", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index(
        "ix_findings_reports_run_id_created", "findings_reports", ["run_id", "created_at"]
    )
    op.create_index("ix_findings_reports_run_id", "findings_reports", ["run_id"])


def downgrade() -> None:
    op.drop_table("findings_reports")
