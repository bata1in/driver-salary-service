from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Driver(Base):
    __tablename__ = "drivers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ref_key: Mapped[Optional[str]] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    external_code: Mapped[Optional[str]] = mapped_column(String(80))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    route_sheets: Mapped[List["RouteSheet"]] = relationship(back_populates="driver")
    delivery_requests: Mapped[List["DeliveryRequest"]] = relationship(back_populates="driver")
    calculated_days: Mapped[List["CalculatedDay"]] = relationship(back_populates="driver")


class RouteSheet(Base):
    __tablename__ = "route_sheets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ref_key: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    number: Mapped[Optional[str]] = mapped_column(String(80), index=True)
    delivery_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    driver_id: Mapped[Optional[int]] = mapped_column(ForeignKey("drivers.id", ondelete="SET NULL"))
    weight_kg: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 3))
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    driver: Mapped[Optional[Driver]] = relationship(back_populates="route_sheets")
    delivery_requests: Mapped[List["DeliveryRequest"]] = relationship(
        back_populates="route_sheet", cascade="all, delete-orphan"
    )


class DeliveryRequest(Base):
    __tablename__ = "delivery_requests"
    __table_args__ = (
        UniqueConstraint("route_sheet_id", "source_line_key", name="uq_request_route_line"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ref_key: Mapped[str] = mapped_column(String(140), unique=True, nullable=False, index=True)
    source_line_key: Mapped[Optional[str]] = mapped_column(String(120), index=True)
    route_sheet_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("route_sheets.id", ondelete="CASCADE"), index=True
    )
    delivery_request_ref_key: Mapped[Optional[str]] = mapped_column(String(80), index=True)
    driver_id: Mapped[int] = mapped_column(ForeignKey("drivers.id", ondelete="RESTRICT"), index=True)
    delivery_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    counterparty_ref_key: Mapped[Optional[str]] = mapped_column(String(80), index=True)
    counterparty_name: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    address_raw: Mapped[str] = mapped_column(Text, nullable=False)
    address_normalized: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    is_pickup: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    weight_kg: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 3))
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    route_sheet: Mapped[Optional[RouteSheet]] = relationship(back_populates="delivery_requests")
    driver: Mapped[Driver] = relationship(back_populates="delivery_requests")


class TariffVersion(Base):
    __tablename__ = "tariff_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    effective_from: Mapped[date] = mapped_column(Date, unique=True, nullable=False, index=True)
    base_daily_rate: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=4000)
    shift_end_time: Mapped[time] = mapped_column(Time, nullable=False, default=time(18, 0))
    overtime_hourly_rate: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())

    point_brackets: Mapped[List["PointBonusBracket"]] = relationship(
        back_populates="tariff_version",
        cascade="all, delete-orphan",
        order_by="PointBonusBracket.min_points",
    )
    weight_brackets: Mapped[List["WeightBonusBracket"]] = relationship(
        back_populates="tariff_version",
        cascade="all, delete-orphan",
        order_by="WeightBonusBracket.min_weight_kg",
    )
    calculated_days: Mapped[List["CalculatedDay"]] = relationship(back_populates="tariff_version")


class PointBonusBracket(Base):
    __tablename__ = "point_bonus_brackets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tariff_version_id: Mapped[int] = mapped_column(
        ForeignKey("tariff_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    min_points: Mapped[int] = mapped_column(Integer, nullable=False)
    max_points: Mapped[Optional[int]] = mapped_column(Integer)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    tariff_version: Mapped[TariffVersion] = relationship(back_populates="point_brackets")


class WeightBonusBracket(Base):
    __tablename__ = "weight_bonus_brackets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tariff_version_id: Mapped[int] = mapped_column(
        ForeignKey("tariff_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    min_weight_kg: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    max_weight_kg: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 3))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    tariff_version: Mapped[TariffVersion] = relationship(back_populates="weight_brackets")


class CalculatedDay(Base):
    __tablename__ = "calculated_days"
    __table_args__ = (
        UniqueConstraint("delivery_date", "driver_id", name="uq_calculated_day_driver"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    delivery_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    driver_id: Mapped[int] = mapped_column(ForeignKey("drivers.id", ondelete="CASCADE"), index=True)
    tariff_version_id: Mapped[int] = mapped_column(ForeignKey("tariff_versions.id", ondelete="RESTRICT"))
    route_count: Mapped[int] = mapped_column(Integer, nullable=False)
    request_count: Mapped[int] = mapped_column(Integer, nullable=False)
    point_count: Mapped[int] = mapped_column(Integer, nullable=False)
    pickup_count: Mapped[int] = mapped_column(Integer, nullable=False)
    weight_kg: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    base_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    point_bonus: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    weight_bonus: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    overtime_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    last_delivery_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    route_keys: Mapped[List[str]] = mapped_column(JSON, nullable=False, default=list)
    details: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    calculated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())

    driver: Mapped[Driver] = relationship(back_populates="calculated_days")
    tariff_version: Mapped[TariffVersion] = relationship(back_populates="calculated_days")


class SyncRun(Base):
    __tablename__ = "sync_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    period_start: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    period_end: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running", index=True)
    added_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    errors: Mapped[List[str]] = mapped_column(JSON, nullable=False, default=list)
