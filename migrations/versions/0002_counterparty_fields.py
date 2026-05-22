from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0002_counterparty_fields"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("delivery_requests", sa.Column("counterparty_ref_key", sa.String(length=80), nullable=True))
    op.add_column("delivery_requests", sa.Column("counterparty_name", sa.String(length=255), nullable=True))
    op.create_index(
        op.f("ix_delivery_requests_counterparty_ref_key"),
        "delivery_requests",
        ["counterparty_ref_key"],
        unique=False,
    )
    op.create_index(
        op.f("ix_delivery_requests_counterparty_name"),
        "delivery_requests",
        ["counterparty_name"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_delivery_requests_counterparty_name"), table_name="delivery_requests")
    op.drop_index(op.f("ix_delivery_requests_counterparty_ref_key"), table_name="delivery_requests")
    op.drop_column("delivery_requests", "counterparty_name")
    op.drop_column("delivery_requests", "counterparty_ref_key")
