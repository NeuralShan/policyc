"""Layer 3: linked_irs and cypher_artifacts tables.

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, Sequence[str], None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "linked_irs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(32),
            sa.ForeignKey("compile_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("linked", sa.JSON, nullable=False),
        sa.Column("stats", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_linked_irs_run_id_created", "linked_irs", ["run_id", "created_at"])
    op.create_index("ix_linked_irs_run_id", "linked_irs", ["run_id"])

    op.create_table(
        "cypher_artifacts",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(32),
            sa.ForeignKey("compile_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("cypher_text", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index(
        "ix_cypher_artifacts_run_id_created", "cypher_artifacts", ["run_id", "created_at"]
    )
    op.create_index("ix_cypher_artifacts_run_id", "cypher_artifacts", ["run_id"])


def downgrade() -> None:
    op.drop_table("cypher_artifacts")
    op.drop_table("linked_irs")
