"""Add resource_permissions table

Revision ID: b5c6d7e8f9a0
Revises: b3c4d5e6f7a8
Create Date: 2026-04-09 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b5c6d7e8f9a0"
down_revision: Union[str, Sequence[str], None] = "b3c4d5e6f7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()

    def table_exists(table_name: str) -> bool:
        result = connection.execute(
            sa.text("SELECT name FROM sqlite_master WHERE type='table' AND name=:name"),
            {"name": table_name},
        )
        return result.fetchone() is not None

    if not table_exists("resource_permissions"):
        op.create_table(
            "resource_permissions",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("team_id", sa.String(), nullable=False),
            sa.Column("resource_type", sa.String(), nullable=False),
            sa.Column("resource_id", sa.String(), nullable=False),
            sa.Column("actions", sa.JSON(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(),
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "user_id",
                "team_id",
                "resource_type",
                "resource_id",
                name="uq_resource_permission",
            ),
        )
        op.create_index(
            "idx_resource_permissions_user_team",
            "resource_permissions",
            ["user_id", "team_id"],
        )


def downgrade() -> None:
    op.drop_index(
        "idx_resource_permissions_user_team",
        table_name="resource_permissions",
        if_exists=True,
    )
    op.drop_table("resource_permissions", if_exists=True)
