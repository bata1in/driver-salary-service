from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal

from app.salary.engine import BonusBracket, DeliveryRow, TariffConfig, calculate_daily_salary


def tariff(
    effective_from=date(1900, 1, 1),
    base="4000",
    point_amounts=None,
    weight_amounts=None,
    overtime="200",
):
    point_amounts = point_amounts or [
        BonusBracket(Decimal("1"), Decimal("1"), Decimal("0")),
        BonusBracket(Decimal("2"), Decimal("2"), Decimal("100")),
        BonusBracket(Decimal("3"), None, Decimal("300")),
    ]
    weight_amounts = weight_amounts or [
        BonusBracket(Decimal("0"), Decimal("499.999"), Decimal("0")),
        BonusBracket(Decimal("500"), Decimal("999.999"), Decimal("200")),
        BonusBracket(Decimal("1000"), None, Decimal("500")),
    ]
    return TariffConfig(
        effective_from=effective_from,
        base_daily_rate=Decimal(base),
        shift_end_time=time(18, 0),
        overtime_hourly_rate=Decimal(overtime),
        point_brackets=tuple(point_amounts),
        weight_brackets=tuple(weight_amounts),
        tariff_id=1,
    )


def row(
    row_key,
    route_key="route-1",
    delivery_date=date(2026, 5, 1),
    driver_key="driver-1",
    address="Москва, ул. Ленина, 1",
    pickup=False,
    route_weight="100",
    delivered_at=None,
):
    return DeliveryRow(
        row_key=row_key,
        route_key=route_key,
        delivery_date=delivery_date,
        driver_key=driver_key,
        driver_name="Иванов",
        address_raw=address,
        is_pickup=pickup,
        route_weight_kg=Decimal(route_weight) if route_weight is not None else None,
        delivered_at=delivered_at,
    )


def test_one_driver_one_day_one_route():
    result = calculate_daily_salary([row("1")], [tariff()])[0]

    assert result.request_count == 1
    assert result.route_keys == ("route-1",)
    assert result.point_count == 1
    assert result.weight_kg == Decimal("100.000")
    assert result.total_amount == Decimal("4000.00")


def test_multiple_routes_in_one_day_sum_unique_route_weights():
    rows = [
        row("1", route_key="route-1", address="А", route_weight="300"),
        row("2", route_key="route-2", address="Б", route_weight="250"),
    ]

    result = calculate_daily_salary(rows, [tariff()])[0]

    assert result.route_keys == ("route-1", "route-2")
    assert result.point_count == 2
    assert result.weight_kg == Decimal("550.000")
    assert result.point_bonus == Decimal("100.00")
    assert result.weight_bonus == Decimal("200.00")
    assert result.total_amount == Decimal("4300.00")


def test_multiple_requests_to_same_address_count_as_one_point():
    rows = [
        row("1", address="Москва, ул. Ленина, 1"),
        row("2", address="москва ул ленина 1"),
    ]

    result = calculate_daily_salary(rows, [tariff()])[0]

    assert result.request_count == 2
    assert result.point_count == 1
    assert result.total_amount == Decimal("4000.00")


def test_pickup_is_shown_but_not_counted_as_bonus_point():
    rows = [
        row("1", address="Доставка"),
        row("2", address="Забор", pickup=True),
    ]

    result = calculate_daily_salary(rows, [tariff()])[0]

    assert result.request_count == 2
    assert result.pickup_count == 1
    assert result.point_count == 1
    assert result.details[1]["is_pickup"] is True


def test_tariff_version_boundary_uses_latest_effective_version():
    old = tariff(effective_from=date(2026, 1, 1), base="4000")
    new = tariff(effective_from=date(2026, 5, 10), base="4500")
    rows = [
        row("1", delivery_date=date(2026, 5, 9), address="А"),
        row("2", delivery_date=date(2026, 5, 10), address="А"),
    ]

    results = calculate_daily_salary(rows, [old, new])

    assert [result.total_amount for result in results] == [Decimal("4000.00"), Decimal("4500.00")]
    assert [result.tariff.effective_from for result in results] == [date(2026, 1, 1), date(2026, 5, 10)]


def test_base_rate_change_from_effective_date():
    results = calculate_daily_salary(
        [
            row("1", delivery_date=date(2026, 5, 1)),
            row("2", delivery_date=date(2026, 5, 2)),
        ],
        [
            tariff(effective_from=date(2026, 5, 1), base="4000"),
            tariff(effective_from=date(2026, 5, 2), base="5000"),
        ],
    )

    assert [result.base_amount for result in results] == [Decimal("4000.00"), Decimal("5000.00")]


def test_point_and_weight_brackets_change_from_effective_date():
    old = tariff(
        effective_from=date(2026, 5, 1),
        point_amounts=[BonusBracket(Decimal("2"), None, Decimal("100"))],
        weight_amounts=[BonusBracket(Decimal("500"), None, Decimal("200"))],
    )
    new = tariff(
        effective_from=date(2026, 5, 2),
        point_amounts=[BonusBracket(Decimal("2"), None, Decimal("700"))],
        weight_amounts=[BonusBracket(Decimal("500"), None, Decimal("900"))],
    )
    rows = [
        row("1", delivery_date=date(2026, 5, 1), route_key="a", address="А", route_weight="300"),
        row("2", delivery_date=date(2026, 5, 1), route_key="b", address="Б", route_weight="300"),
        row("3", delivery_date=date(2026, 5, 2), route_key="c", address="А", route_weight="300"),
        row("4", delivery_date=date(2026, 5, 2), route_key="d", address="Б", route_weight="300"),
    ]

    results = calculate_daily_salary(rows, [old, new])

    assert [result.point_bonus for result in results] == [Decimal("100.00"), Decimal("700.00")]
    assert [result.weight_bonus for result in results] == [Decimal("200.00"), Decimal("900.00")]


def test_open_ended_threshold_brackets_use_highest_matching_minimum():
    result = calculate_daily_salary(
        [
            row("1", route_key="a", address="А", route_weight="400"),
            row("2", route_key="b", address="Б", route_weight="400"),
            row("3", route_key="c", address="В", route_weight="400"),
        ],
        [
            tariff(
                point_amounts=[
                    BonusBracket(Decimal("0"), None, Decimal("0")),
                    BonusBracket(Decimal("2"), None, Decimal("500")),
                    BonusBracket(Decimal("3"), None, Decimal("900")),
                ],
                weight_amounts=[
                    BonusBracket(Decimal("0"), None, Decimal("0")),
                    BonusBracket(Decimal("700"), None, Decimal("1000")),
                    BonusBracket(Decimal("1200"), None, Decimal("1800")),
                ],
            )
        ],
    )[0]

    assert result.point_bonus == Decimal("900.00")
    assert result.weight_bonus == Decimal("1800.00")


def test_overtime_is_calculated_after_shift_end():
    result = calculate_daily_salary(
        [row("1", delivered_at=datetime(2026, 5, 1, 19, 30))],
        [tariff(overtime="200")],
    )[0]

    assert result.overtime_amount == Decimal("300.00")
    assert result.total_amount == Decimal("4300.00")
