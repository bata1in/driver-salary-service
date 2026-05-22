from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


MONEY = Decimal("0.01")
WEIGHT = Decimal("0.001")


def decimal_value(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    if value is None:
        return default
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value).replace(",", "."))


def money(value: Any) -> Decimal:
    return decimal_value(value).quantize(MONEY, rounding=ROUND_HALF_UP)


def normalize_address(value: Optional[str]) -> str:
    if not value:
        return ""
    text = value.replace("\xa0", " ").replace("ё", "е").replace("Ё", "е").lower()
    text = re.sub(r"[.,;:()\"'`]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


@dataclass(frozen=True)
class BonusBracket:
    min_value: Decimal
    max_value: Optional[Decimal]
    amount: Decimal

    def contains(self, value: Decimal) -> bool:
        if value < self.min_value:
            return False
        return self.max_value is None or value <= self.max_value


@dataclass(frozen=True)
class TariffConfig:
    effective_from: date
    base_daily_rate: Decimal = Decimal("4000")
    shift_end_time: time = time(18, 0)
    overtime_hourly_rate: Decimal = Decimal("0")
    point_brackets: Tuple[BonusBracket, ...] = ()
    weight_brackets: Tuple[BonusBracket, ...] = ()
    tariff_id: Optional[int] = None


@dataclass(frozen=True)
class DeliveryRow:
    row_key: str
    route_key: str
    delivery_date: date
    driver_key: str
    driver_name: str
    address_raw: str
    route_date: Optional[date] = None
    counterparty_name: Optional[str] = None
    is_pickup: bool = False
    route_weight_kg: Optional[Decimal] = None
    row_weight_kg: Optional[Decimal] = None
    delivered_at: Optional[datetime] = None
    marked_at: Optional[datetime] = None
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SalaryDayResult:
    delivery_date: date
    driver_key: str
    driver_name: str
    tariff: TariffConfig
    route_keys: Tuple[str, ...]
    request_count: int
    point_count: int
    pickup_count: int
    weight_kg: Decimal
    base_amount: Decimal
    point_bonus: Decimal
    weight_bonus: Decimal
    overtime_amount: Decimal
    total_amount: Decimal
    last_delivery_at: Optional[datetime]
    details: Tuple[Dict[str, Any], ...]


def select_tariff_for_day(day: date, tariffs: Sequence[TariffConfig]) -> TariffConfig:
    candidates = [tariff for tariff in tariffs if tariff.effective_from <= day]
    if not candidates:
        raise ValueError(f"No tariff version effective for {day.isoformat()}")
    return max(candidates, key=lambda tariff: tariff.effective_from)


def select_bonus(value: Decimal, brackets: Iterable[BonusBracket]) -> Decimal:
    matches = [bracket for bracket in brackets if bracket.contains(value)]
    if not matches:
        return Decimal("0")
    return money(max(matches, key=lambda bracket: bracket.min_value).amount)


def _route_weight_total(rows: Sequence[DeliveryRow]) -> Decimal:
    route_weights: Dict[str, Decimal] = {}
    for row in rows:
        route_key = row.route_key or f"row:{row.row_key}"
        if row.route_weight_kg is not None:
            route_weights.setdefault(route_key, decimal_value(row.route_weight_kg))
            continue
        route_weights[route_key] = route_weights.get(route_key, Decimal("0")) + decimal_value(
            row.row_weight_kg
        )
    return sum(route_weights.values(), Decimal("0")).quantize(WEIGHT, rounding=ROUND_HALF_UP)


def _overtime_amount(day: date, last_delivery_at: Optional[datetime], tariff: TariffConfig) -> Decimal:
    if last_delivery_at is None or tariff.overtime_hourly_rate <= 0:
        return Decimal("0.00")
    shift_end = datetime.combine(day, tariff.shift_end_time)
    if last_delivery_at <= shift_end:
        return Decimal("0.00")
    seconds = Decimal(str((last_delivery_at - shift_end).total_seconds()))
    return money(seconds * tariff.overtime_hourly_rate / Decimal("3600"))


def calculate_daily_salary(
    rows: Sequence[DeliveryRow], tariffs: Sequence[TariffConfig]
) -> List[SalaryDayResult]:
    grouped: Dict[Tuple[date, str], List[DeliveryRow]] = {}
    for row in rows:
        grouped.setdefault((row.delivery_date, row.driver_key), []).append(row)

    results: List[SalaryDayResult] = []
    for (delivery_date, driver_key), day_rows in grouped.items():
        tariff = select_tariff_for_day(delivery_date, tariffs)
        route_keys = tuple(sorted({row.route_key for row in day_rows if row.route_key}))
        normalized_points = {
            normalize_address(row.address_raw)
            for row in day_rows
            if not row.is_pickup and normalize_address(row.address_raw)
        }
        pickup_count = sum(1 for row in day_rows if row.is_pickup)
        weight_kg = _route_weight_total(day_rows)
        point_count = len(normalized_points)
        point_bonus = select_bonus(Decimal(point_count), tariff.point_brackets)
        weight_bonus = select_bonus(weight_kg, tariff.weight_brackets)
        last_delivery_at = max(
            (row.delivered_at for row in day_rows if row.delivered_at is not None),
            default=None,
        )
        overtime_amount = _overtime_amount(delivery_date, last_delivery_at, tariff)
        base_amount = money(tariff.base_daily_rate)
        total_amount = money(base_amount + point_bonus + weight_bonus + overtime_amount)

        details = []
        for row in sorted(day_rows, key=lambda item: (item.route_key, item.row_key)):
            details.append(
                {
                    "row_key": row.row_key,
                    "route_key": row.route_key,
                    "route_date": (row.route_date or row.delivery_date).isoformat(),
                    "counterparty_name": row.counterparty_name,
                    "address_raw": row.address_raw,
                    "address_normalized": normalize_address(row.address_raw),
                    "is_pickup": row.is_pickup,
                    "route_weight_kg": str(row.route_weight_kg) if row.route_weight_kg is not None else None,
                    "row_weight_kg": str(row.row_weight_kg) if row.row_weight_kg is not None else None,
                    "delivered_at": row.delivered_at.isoformat(sep=" ") if row.delivered_at else None,
                    "marked_at": row.marked_at.isoformat(sep=" ") if row.marked_at else None,
                }
            )

        results.append(
            SalaryDayResult(
                delivery_date=delivery_date,
                driver_key=driver_key,
                driver_name=day_rows[0].driver_name,
                tariff=tariff,
                route_keys=route_keys,
                request_count=len(day_rows),
                point_count=point_count,
                pickup_count=pickup_count,
                weight_kg=weight_kg,
                base_amount=base_amount,
                point_bonus=point_bonus,
                weight_bonus=weight_bonus,
                overtime_amount=overtime_amount,
                total_amount=total_amount,
                last_delivery_at=last_delivery_at,
                details=tuple(details),
            )
        )
    return sorted(results, key=lambda result: (result.delivery_date, result.driver_name))
