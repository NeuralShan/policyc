"""Layer 2: SopIR table and PAUSED run status.

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, Sequence[str], None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sop_irs",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("run_id", sa.String(32), nullable=False),
        sa.Column("document_ids", sa.JSON(), nullable=False),
        sa.Column("review_status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("ir", sa.JSON(), nullable=False),
        sa.Column("stats", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["compile_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sop_irs_run_id", "sop_irs", ["run_id"])
    op.create_index("ix_sop_irs_run_id_created", "sop_irs", ["run_id", "created_at"])
    # "paused" is a new valid value for compile_runs.status; no schema change needed
    # (SQLite uses TEXT for all string columns).


def downgrade() -> None:
    op.drop_index("ix_sop_irs_run_id_created", table_name="sop_irs")
    op.drop_index("ix_sop_irs_run_id", table_name="sop_irs")
    op.drop_table("sop_irs")
