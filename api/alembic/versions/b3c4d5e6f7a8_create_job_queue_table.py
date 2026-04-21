"""create_job_queue_table

Revision ID: b3c4d5e6f7a8
Revises: 84accba9dc2c
Create Date: 2026-04-02 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b3c4d5e6f7a8"
down_revision: Union[str, Sequence[str], None] = "84accba9dc2c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the job_queue table for DB-backed job dispatch."""
    op.create_table(
        "job_queue",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("experiment_id", sa.String(), nullable=False),
        sa.Column("team_id", sa.String(), nullable=False),
        sa.Column("queue_type", sa.String(), nullable=False),  # e.g. "REMOTE"
        sa.Column("status", sa.String(), nullable=False),  # "PENDING", "DISPATCHED", "FAILED"
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_job_queue_status_type", "job_queue", ["status", "queue_type"], unique=False)
    op.create_index("idx_job_queue_job_id", "job_queue", ["job_id"], unique=False)


def downgrade() -> None:
    """Drop the job_queue table."""
    op.drop_index("idx_job_queue_job_id", table_name="job_queue")
    op.drop_index("idx_job_queue_status_type", table_name="job_queue")
    op.drop_table("job_queue")
