"""Projects get a nullable owner_uid (Firebase uid); NULL means public/demo.

Revision ID: 0011
Revises: 0010
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: Union[str, Sequence[str], None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Plain ADD COLUMN (in place on SQLite). batch_alter_table would rebuild `projects` and the
    # ON DELETE CASCADE foreign keys would delete documents, runs and every artefact.
    op.add_column("projects", sa.Column("owner_uid", sa.String(128), nullable=True))
    op.create_index("ix_projects_owner_uid", "projects", ["owner_uid"])


def downgrade() -> None:
    op.drop_index("ix_projects_owner_uid", table_name="projects")
    op.drop_column("projects", "owner_uid")
