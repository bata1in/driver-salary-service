from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "drivers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ref_key", sa.String(length=80), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("external_code", sa.String(length=80), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(op.f("ix_drivers_name"), "drivers", ["name"])
    op.create_index(op.f("ix_drivers_ref_key"), "drivers", ["ref_key"], unique=True)

    op.create_table(
        "tariff_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("base_daily_rate", sa.Numeric(12, 2), nullable=False),
        sa.Column("shift_end_time", sa.Time(), nullable=False),
        sa.Column("overtime_hourly_rate", sa.Numeric(12, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(op.f("ix_tariff_versions_effective_from"), "tariff_versions", ["effective_from"], unique=True)

    op.create_table(
        "sync_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("started_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("added_count", sa.Integer(), nullable=False),
        sa.Column("updated_count", sa.Integer(), nullable=False),
        sa.Column("error_count", sa.Integer(), nullable=False),
        sa.Column("errors", sa.JSON(), nullable=False),
    )
    op.create_index(op.f("ix_sync_runs_period_end"), "sync_runs", ["period_end"])
    op.create_index(op.f("ix_sync_runs_period_start"), "sync_runs", ["period_start"])
    op.create_index(op.f("ix_sync_runs_status"), "sync_runs", ["status"])

    op.create_table(
        "route_sheets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ref_key", sa.String(length=80), nullable=False),
        sa.Column("number", sa.String(length=80), nullable=True),
        sa.Column("delivery_date", sa.Date(), nullable=False),
        sa.Column("driver_id", sa.Integer(), nullable=True),
        sa.Column("weight_kg", sa.Numeric(12, 3), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["driver_id"], ["drivers.id"], ondelete="SET NULL"),
    )
    op.create_index(op.f("ix_route_sheets_delivery_date"), "route_sheets", ["delivery_date"])
    op.create_index(op.f("ix_route_sheets_number"), "route_sheets", ["number"])
    op.create_index(op.f("ix_route_sheets_ref_key"), "route_sheets", ["ref_key"], unique=True)

    op.create_table(
        "point_bonus_brackets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tariff_version_id", sa.Integer(), nullable=False),
        sa.Column("min_points", sa.Integer(), nullable=False),
        sa.Column("max_points", sa.Integer(), nullable=True),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.ForeignKeyConstraint(["tariff_version_id"], ["tariff_versions.id"], ondelete="CASCADE"),
    )
    op.create_index(op.f("ix_point_bonus_brackets_tariff_version_id"), "point_bonus_brackets", ["tariff_version_id"])

    op.create_table(
        "weight_bonus_brackets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tariff_version_id", sa.Integer(), nullable=False),
        sa.Column("min_weight_kg", sa.Numeric(12, 3), nullable=False),
        sa.Column("max_weight_kg", sa.Numeric(12, 3), nullable=True),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.ForeignKeyConstraint(["tariff_version_id"], ["tariff_versions.id"], ondelete="CASCADE"),
    )
    op.create_index(op.f("ix_weight_bonus_brackets_tariff_version_id"), "weight_bonus_brackets", ["tariff_version_id"])

    op.create_table(
        "delivery_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ref_key", sa.String(length=140), nullable=False),
        sa.Column("source_line_key", sa.String(length=120), nullable=True),
        sa.Column("route_sheet_id", sa.Integer(), nullable=True),
        sa.Column("delivery_request_ref_key", sa.String(length=80), nullable=True),
        sa.Column("driver_id", sa.Integer(), nullable=False),
        sa.Column("delivery_date", sa.Date(), nullable=False),
        sa.Column("address_raw", sa.Text(), nullable=False),
        sa.Column("address_normalized", sa.Text(), nullable=False),
        sa.Column("is_pickup", sa.Boolean(), nullable=False),
        sa.Column("weight_kg", sa.Numeric(12, 3), nullable=True),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["driver_id"], ["drivers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["route_sheet_id"], ["route_sheets.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("route_sheet_id", "source_line_key", name="uq_request_route_line"),
    )
    op.create_index(op.f("ix_delivery_requests_address_normalized"), "delivery_requests", ["address_normalized"])
    op.create_index(op.f("ix_delivery_requests_delivery_date"), "delivery_requests", ["delivery_date"])
    op.create_index(op.f("ix_delivery_requests_delivery_request_ref_key"), "delivery_requests", ["delivery_request_ref_key"])
    op.create_index(op.f("ix_delivery_requests_driver_id"), "delivery_requests", ["driver_id"])
    op.create_index(op.f("ix_delivery_requests_ref_key"), "delivery_requests", ["ref_key"], unique=True)
    op.create_index(op.f("ix_delivery_requests_route_sheet_id"), "delivery_requests", ["route_sheet_id"])
    op.create_index(op.f("ix_delivery_requests_source_line_key"), "delivery_requests", ["source_line_key"])

    op.create_table(
        "calculated_days",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("delivery_date", sa.Date(), nullable=False),
        sa.Column("driver_id", sa.Integer(), nullable=False),
        sa.Column("tariff_version_id", sa.Integer(), nullable=False),
        sa.Column("route_count", sa.Integer(), nullable=False),
        sa.Column("request_count", sa.Integer(), nullable=False),
        sa.Column("point_count", sa.Integer(), nullable=False),
        sa.Column("pickup_count", sa.Integer(), nullable=False),
        sa.Column("weight_kg", sa.Numeric(12, 3), nullable=False),
        sa.Column("base_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("point_bonus", sa.Numeric(12, 2), nullable=False),
        sa.Column("weight_bonus", sa.Numeric(12, 2), nullable=False),
        sa.Column("overtime_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("total_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("last_delivery_at", sa.DateTime(), nullable=True),
        sa.Column("route_keys", sa.JSON(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("calculated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["driver_id"], ["drivers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tariff_version_id"], ["tariff_versions.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("delivery_date", "driver_id", name="uq_calculated_day_driver"),
    )
    op.create_index(op.f("ix_calculated_days_delivery_date"), "calculated_days", ["delivery_date"])
    op.create_index(op.f("ix_calculated_days_driver_id"), "calculated_days", ["driver_id"])


def downgrade() -> None:
    op.drop_table("calculated_days")
    op.drop_table("delivery_requests")
    op.drop_table("weight_bonus_brackets")
    op.drop_table("point_bonus_brackets")
    op.drop_table("route_sheets")
    op.drop_table("sync_runs")
    op.drop_table("tariff_versions")
    op.drop_table("drivers")
