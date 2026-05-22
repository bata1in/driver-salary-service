from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.web.formatting import format_date_ru, format_detail_time, format_money, format_number, format_weight


def test_number_and_money_formatters_group_thousands_without_cents():
    assert format_number(52000) == "52 000"
    assert format_money(Decimal("52300.00")) == "52 300"
    assert format_money(None) == ""


def test_weight_formatter_keeps_three_decimals():
    assert format_weight(Decimal("1234.5")) == "1 234.500"


def test_detail_time_shows_only_time_for_same_route_date():
    assert format_detail_time("2026-05-22 18:15:00", date(2026, 5, 22)) == "18:15"
    assert format_detail_time("2026-05-23 00:15:00", date(2026, 5, 22)) == "23.05.2026 00:15"
    assert format_detail_time(None, date(2026, 5, 22)) == ""


def test_date_formatter_accepts_iso_strings():
    assert format_date_ru("2026-05-22") == "22.05.2026"
