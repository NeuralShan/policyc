"""Layer 8: case_histories and reality_reports tables.

Revision ID: 0009
Revises: 0008
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, Sequence[str], None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "case_histories",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(32),
            sa.ForeignKey("compile_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_filename", sa.String(255), nullable=False),
        sa.Column("event_log", sa.JSON, nullable=False),
        sa.Column("stats", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_case_histories_run_id_created", "case_histories", ["run_id", "created_at"])
    op.create_index("ix_case_histories_run_id", "case_histories", ["run_id"])

    op.create_table(
        "reality_reports",
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
    op.create_index("ix_reality_reports_run_id_created", "reality_reports", ["run_id", "created_at"])
    op.create_index("ix_reality_reports_run_id", "reality_reports", ["run_id"])


def downgrade() -> None:
    op.drop_table("reality_reports")
    op.drop_table("case_histories")
