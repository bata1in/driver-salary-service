from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Optional

from fastapi.templating import Jinja2Templates


def _to_decimal(value: Any) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value).replace(",", "."))
    except (InvalidOperation, ValueError):
        return None


def _grouped_decimal(value: Any, digits: int) -> str:
    number = _to_decimal(value)
    if number is None:
        return ""
    quant = Decimal("1") if digits == 0 else Decimal("1").scaleb(-digits)
    rounded = number.quantize(quant, rounding=ROUND_HALF_UP)
    return f"{rounded:,.{digits}f}".replace(",", " ")


def format_number(value: Any) -> str:
    return _grouped_decimal(value, 0)


def format_money(value: Any) -> str:
    return _grouped_decimal(value, 0)


def format_weight(value: Any) -> str:
    return _grouped_decimal(value, 3)


def _parse_date(value: Any) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d.%m.%Y"):
        try:
            return datetime.strptime(text[: len(fmt)], fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _parse_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M"):
        try:
            return datetime.strptime(text[: len(fmt)], fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def format_date_ru(value: Any) -> str:
    parsed = _parse_date(value)
    return parsed.strftime("%d.%m.%Y") if parsed else ""


def format_detail_time(value: Any, route_date: Any = None) -> str:
    parsed = _parse_datetime(value)
    if parsed is None:
        return ""
    parsed_route_date = _parse_date(route_date)
    if parsed_route_date is not None and parsed.date() == parsed_route_date:
        return parsed.strftime("%H:%M")
    return parsed.strftime("%d.%m.%Y %H:%M")


def register_template_filters(templates: Jinja2Templates) -> None:
    templates.env.filters["number"] = format_number
    templates.env.filters["money"] = format_money
    templates.env.filters["weight"] = format_weight
    templates.env.filters["date_ru"] = format_date_ru
    templates.env.filters["detail_time"] = format_detail_time
