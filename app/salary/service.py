from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    CalculatedDay,
    DeliveryRequest,
    Driver,
    PointBonusBracket,
    RouteSheet,
    TariffVersion,
    WeightBonusBracket,
)
from app.salary.engine import BonusBracket, DeliveryRow, TariffConfig, calculate_daily_salary


DEFAULT_TARIFF_DATE = date(1900, 1, 1)
DEFAULT_POINT_BRACKETS = (
    (0, 12, Decimal("0")),
    (13, 18, Decimal("500")),
    (19, 24, Decimal("700")),
    (25, 30, Decimal("1500")),
    (31, None, Decimal("1800")),
)
DEFAULT_WEIGHT_BRACKETS = (
    (Decimal("0"), Decimal("500.999"), Decimal("0")),
    (Decimal("501"), Decimal("700.999"), Decimal("500")),
    (Decimal("701"), Decimal("900.999"), Decimal("1000")),
    (Decimal("901"), Decimal("1100.999"), Decimal("1400")),
    (Decimal("1101"), Decimal("1300.999"), Decimal("1700")),
    (Decimal("1301"), Decimal("1600.999"), Decimal("2500")),
    (Decimal("1601"), None, Decimal("3000")),
)
DEFAULT_OVERTIME_HOURLY_RATE = Decimal("3000")


def _payload_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.year > 1901 else None
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M"):
        try:
            parsed = datetime.strptime(text[: len(fmt)], fmt)
            return parsed if parsed.year > 1901 else None
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
        return parsed if parsed.year > 1901 else None
    except ValueError:
        return None


def _seed_default_brackets(tariff: TariffVersion) -> None:
    if not tariff.point_brackets:
        for min_points, max_points, amount in DEFAULT_POINT_BRACKETS:
            tariff.point_brackets.append(
                PointBonusBracket(
                    min_points=min_points,
                    max_points=max_points,
                    amount=amount,
                )
            )
    if not tariff.weight_brackets:
        for min_weight, max_weight, amount in DEFAULT_WEIGHT_BRACKETS:
            tariff.weight_brackets.append(
                WeightBonusBracket(
                    min_weight_kg=min_weight,
                    max_weight_kg=max_weight,
                    amount=amount,
                )
            )


def ensure_default_tariff(session: Session) -> TariffVersion:
    tariff = session.scalar(
        select(TariffVersion)
        .options(
            selectinload(TariffVersion.point_brackets),
            selectinload(TariffVersion.weight_brackets),
        )
        .where(TariffVersion.effective_from == DEFAULT_TARIFF_DATE)
    )
    if tariff is None:
        tariff = TariffVersion(
            effective_from=DEFAULT_TARIFF_DATE,
            base_daily_rate=Decimal("4000"),
            shift_end_time=time(18, 0),
            overtime_hourly_rate=DEFAULT_OVERTIME_HOURLY_RATE,
        )
        session.add(tariff)
    elif Decimal(tariff.overtime_hourly_rate or 0) == Decimal("0"):
        tariff.overtime_hourly_rate = DEFAULT_OVERTIME_HOURLY_RATE
    _seed_default_brackets(tariff)
    session.flush()
    return tariff


def load_tariff_configs(session: Session) -> List[TariffConfig]:
    tariffs = session.scalars(
        select(TariffVersion)
        .options(
            selectinload(TariffVersion.point_brackets),
            selectinload(TariffVersion.weight_brackets),
        )
        .order_by(TariffVersion.effective_from)
    ).all()
    if not tariffs:
        tariffs = [ensure_default_tariff(session)]
    configs = []
    for tariff in tariffs:
        point_brackets = tuple(
            BonusBracket(
                min_value=Decimal(bracket.min_points),
                max_value=Decimal(bracket.max_points) if bracket.max_points is not None else None,
                amount=Decimal(bracket.amount),
            )
            for bracket in tariff.point_brackets
        )
        weight_brackets = tuple(
            BonusBracket(
                min_value=Decimal(bracket.min_weight_kg),
                max_value=Decimal(bracket.max_weight_kg) if bracket.max_weight_kg is not None else None,
                amount=Decimal(bracket.amount),
            )
            for bracket in tariff.weight_brackets
        )
        configs.append(
            TariffConfig(
                tariff_id=tariff.id,
                effective_from=tariff.effective_from,
                base_daily_rate=Decimal(tariff.base_daily_rate),
                shift_end_time=tariff.shift_end_time,
                overtime_hourly_rate=Decimal(tariff.overtime_hourly_rate),
                point_brackets=point_brackets,
                weight_brackets=weight_brackets,
            )
        )
    return configs


def _delivery_rows(session: Session, start: date, end: date) -> List[DeliveryRow]:
    requests = session.scalars(
        select(DeliveryRequest)
        .options(
            selectinload(DeliveryRequest.driver),
            selectinload(DeliveryRequest.route_sheet),
        )
        .where(DeliveryRequest.delivery_date >= start, DeliveryRequest.delivery_date <= end)
        .order_by(DeliveryRequest.delivery_date, DeliveryRequest.driver_id)
    ).all()
    rows = []
    for request in requests:
        route_sheet = request.route_sheet
        counterparty_name = request.counterparty_name or request.address_raw
        rows.append(
            DeliveryRow(
                row_key=request.ref_key,
                route_key=route_sheet.ref_key if route_sheet else request.ref_key,
                delivery_date=request.delivery_date,
                route_date=route_sheet.delivery_date if route_sheet else request.delivery_date,
                driver_key=str(request.driver_id),
                driver_name=request.driver.name,
                address_raw=request.address_raw,
                counterparty_name=counterparty_name,
                is_pickup=request.is_pickup,
                route_weight_kg=Decimal(route_sheet.weight_kg) if route_sheet and route_sheet.weight_kg is not None else None,
                row_weight_kg=Decimal(request.weight_kg) if request.weight_kg is not None else None,
                delivered_at=request.delivered_at,
                marked_at=_payload_datetime(request.payload.get("ДатаВремяОтметкиДоставки")),
                payload=request.payload,
            )
        )
    return rows


def recalculate_salary_days(session: Session, start: date, end: date) -> List[CalculatedDay]:
    tariffs = load_tariff_configs(session)
    rows = _delivery_rows(session, start, end)
    results = calculate_daily_salary(rows, tariffs)

    session.execute(
        delete(CalculatedDay).where(
            CalculatedDay.delivery_date >= start,
            CalculatedDay.delivery_date <= end,
        )
    )
    session.flush()

    saved = []
    for result in results:
        driver_id = int(result.driver_key)
        calculated = CalculatedDay(
            delivery_date=result.delivery_date,
            driver_id=driver_id,
            tariff_version_id=result.tariff.tariff_id,
            route_count=len(result.route_keys),
            request_count=result.request_count,
            point_count=result.point_count,
            pickup_count=result.pickup_count,
            weight_kg=result.weight_kg,
            base_amount=result.base_amount,
            point_bonus=result.point_bonus,
            weight_bonus=result.weight_bonus,
            overtime_amount=result.overtime_amount,
            total_amount=result.total_amount,
            last_delivery_at=result.last_delivery_at,
            route_keys=list(result.route_keys),
            details=list(result.details),
        )
        session.add(calculated)
        saved.append(calculated)
    session.flush()
    return saved


def salary_summary(session: Session, start: date, end: date) -> List[Dict[str, Any]]:
    rows = session.execute(
        select(
            Driver.id,
            Driver.name,
            func.count(CalculatedDay.id),
            func.sum(CalculatedDay.route_count),
            func.sum(CalculatedDay.request_count),
            func.sum(CalculatedDay.point_count),
            func.sum(CalculatedDay.pickup_count),
            func.sum(CalculatedDay.weight_kg),
            func.sum(CalculatedDay.total_amount),
        )
        .join(CalculatedDay, CalculatedDay.driver_id == Driver.id)
        .where(CalculatedDay.delivery_date >= start, CalculatedDay.delivery_date <= end)
        .group_by(Driver.id, Driver.name)
        .order_by(Driver.name)
    ).all()
    return [
        {
            "driver_id": row[0],
            "driver_name": row[1],
            "day_count": row[2] or 0,
            "route_count": row[3] or 0,
            "request_count": row[4] or 0,
            "point_count": row[5] or 0,
            "pickup_count": row[6] or 0,
            "weight_kg": row[7] or Decimal("0"),
            "total_amount": row[8] or Decimal("0"),
        }
        for row in rows
    ]


def create_tariff_version(
    session: Session,
    effective_from: date,
    base_daily_rate: Decimal,
    shift_end_time: time,
    overtime_hourly_rate: Decimal,
    point_brackets: List[Dict[str, Optional[Decimal]]],
    weight_brackets: List[Dict[str, Optional[Decimal]]],
) -> TariffVersion:
    tariff = TariffVersion(
        effective_from=effective_from,
        base_daily_rate=base_daily_rate,
        shift_end_time=shift_end_time,
        overtime_hourly_rate=overtime_hourly_rate,
    )
    for bracket in point_brackets:
        tariff.point_brackets.append(
            PointBonusBracket(
                min_points=int(bracket["min_value"]),
                max_points=int(bracket["max_value"]) if bracket["max_value"] is not None else None,
                amount=bracket["amount"],
            )
        )
    for bracket in weight_brackets:
        tariff.weight_brackets.append(
            WeightBonusBracket(
                min_weight_kg=bracket["min_value"],
                max_weight_kg=bracket["max_value"],
                amount=bracket["amount"],
            )
        )
    session.add(tariff)
    session.flush()
    return tariff


def update_tariff_version(
    session: Session,
    tariff: TariffVersion,
    effective_from: date,
    base_daily_rate: Decimal,
    shift_end_time: time,
    overtime_hourly_rate: Decimal,
    point_brackets: List[Dict[str, Optional[Decimal]]],
    weight_brackets: List[Dict[str, Optional[Decimal]]],
) -> TariffVersion:
    tariff.effective_from = effective_from
    tariff.base_daily_rate = base_daily_rate
    tariff.shift_end_time = shift_end_time
    tariff.overtime_hourly_rate = overtime_hourly_rate
    tariff.point_brackets.clear()
    tariff.weight_brackets.clear()
    session.flush()
    for bracket in point_brackets:
        tariff.point_brackets.append(
            PointBonusBracket(
                min_points=int(bracket["min_value"]),
                max_points=int(bracket["max_value"]) if bracket["max_value"] is not None else None,
                amount=bracket["amount"],
            )
        )
    for bracket in weight_brackets:
        tariff.weight_brackets.append(
            WeightBonusBracket(
                min_weight_kg=bracket["min_value"],
                max_weight_kg=bracket["max_value"],
                amount=bracket["amount"],
            )
        )
    session.flush()
    return tariff


def delivery_date_bounds(session: Session) -> Optional[Dict[str, date]]:
    row = session.execute(
        select(func.min(DeliveryRequest.delivery_date), func.max(DeliveryRequest.delivery_date))
    ).one()
    if row[0] is None or row[1] is None:
        return None
    return {"start": row[0], "end": row[1]}
