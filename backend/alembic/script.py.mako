"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

Checklist for every migration (docs/data-model.md):
* New tables get app_user's base grants automatically (ALTER DEFAULT PRIVILEGES in 0001).
* An insert-only table must be in app.core.db_grants.INSERT_ONLY_TABLES and must run
  op.execute(make_insert_only_sql("<table>")) right after it is created.
* downgrade() must undo everything upgrade() does.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
${imports if imports else ""}

revision: str = ${repr(up_revision)}
down_revision: str | None = ${repr(down_revision)}
branch_labels: str | Sequence[str] | None = ${repr(branch_labels)}
depends_on: str | Sequence[str] | None = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
