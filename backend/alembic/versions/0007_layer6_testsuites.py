"""Layer 6: test_suites table.

Revision ID: 0007
Revises: 0006
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, Sequence[str], None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "test_suites",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(32),
            sa.ForeignKey("compile_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("suite", sa.JSON, nullable=False),
        sa.Column("stats", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_test_suites_run_id_created", "test_suites", ["run_id", "created_at"])
    op.create_index("ix_test_suites_run_id", "test_suites", ["run_id"])


def downgrade() -> None:
    op.drop_table("test_suites")
