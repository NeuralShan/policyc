"""Layer 5: execution_traces table.

Revision ID: 0006
Revises: 0005
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, Sequence[str], None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "execution_traces",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(32),
            sa.ForeignKey("compile_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scenario_id", sa.String(64), nullable=False),
        sa.Column("process_id", sa.String(64), nullable=False),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("trace", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index(
        "ix_execution_traces_run_id_created", "execution_traces", ["run_id", "created_at"]
    )
    op.create_index("ix_execution_traces_run_id", "execution_traces", ["run_id"])


def downgrade() -> None:
    op.drop_table("execution_traces")
