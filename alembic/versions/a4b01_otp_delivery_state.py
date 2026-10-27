"""Durable OTP delivery reservations.

Existing rows represent completed sends under the previous transaction flow.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a4b01"
down_revision: str | Sequence[str] | None = "d9670763b00d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("auth_challenges") as batch:
        batch.add_column(
            sa.Column("delivery_status", sa.String(16), nullable=False, server_default="accepted")
        )
        batch.create_check_constraint(
            "ck_challenge_delivery_status",
            "delivery_status IN ('pending', 'accepted', 'rejected')",
        )
    op.create_index(
        "uq_challenge_open_pending_mobile", "auth_challenges", ["mobile_digest"],
        unique=True,
        postgresql_where=sa.text("delivery_status = 'pending' AND consumed_at IS NULL"),
        sqlite_where=sa.text("delivery_status = 'pending' AND consumed_at IS NULL"),
    )
    with op.batch_alter_table("auth_challenges") as batch:
        batch.alter_column("delivery_status", server_default="pending")


def downgrade() -> None:
    op.drop_index("uq_challenge_open_pending_mobile", table_name="auth_challenges")
    with op.batch_alter_table("auth_challenges") as batch:
        batch.drop_constraint("ck_challenge_delivery_status", type_="check")
        batch.drop_column("delivery_status")
