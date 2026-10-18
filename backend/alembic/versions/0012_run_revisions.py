"""Runs can auto-approve the extraction review and link to the revision they were derived from.

Revision ID: 0012
Revises: 0011
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: Union[str, Sequence[str], None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Plain ADD COLUMN: SQLite does it in place. batch_alter_table would rebuild the table and
    # ON DELETE CASCADE would silently delete every child row (IR, diagnostics, findings...).
    op.add_column(
        "compile_runs",
        sa.Column("auto_approve", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("compile_runs", sa.Column("base_run_id", sa.String(32), nullable=True))
    op.add_column("compile_runs", sa.Column("note", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("compile_runs", "note")
    op.drop_column("compile_runs", "base_run_id")
    op.drop_column("compile_runs", "auto_approve")
