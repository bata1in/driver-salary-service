from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.db import get_session
from app.models import CalculatedDay, DeliveryRequest, SyncRun, TariffVersion
from app.odata.sync import ODataSyncService
from app.salary.service import (
    create_tariff_version,
    delivery_date_bounds,
    ensure_default_tariff,
    recalculate_salary_days,
    salary_summary,
    update_tariff_version,
)
from app.security import require_auth
from app.web.formatting import register_template_filters


router = APIRouter(dependencies=[Depends(require_auth)])
templates = Jinja2Templates(directory="app/web/templates")
register_template_filters(templates)


def _default_period(session: Session) -> Dict[str, date]:
    bounds = delivery_date_bounds(session)
    if bounds:
        return bounds
    today = date.today()
    return {"start": today.replace(day=1), "end": today}


def _parse_date_param(value: Optional[str], fallback: date) -> date:
    if not value:
        return fallback
    return datetime.strptime(value, "%Y-%m-%d").date()


def _redirect(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=303)


def _period_redirect(path: str, start: date, end: date, **params: str) -> RedirectResponse:
    query = {"start": start.isoformat(), "end": end.isoformat(), **params}
    return _redirect(f"{path}?{urlencode(query)}")


def _notice_redirect(path: str, **params: str) -> RedirectResponse:
    return _redirect(f"{path}?{urlencode(params)}")


def _template(request: Request, name: str, context: Dict[str, object]) -> HTMLResponse:
    context = {"request": request, **context}
    return templates.TemplateResponse(request=request, name=name, context=context)


def _sync_period(session: Session, start_date: date, end_date: date) -> Dict[str, str]:
    sync_run = ODataSyncService(session, get_settings()).sync_period(start_date, end_date)
    status = sync_run.status
    errors = list(sync_run.errors or [])
    session.commit()
    if status == "failed":
        detail = "; ".join(errors[:3]) or "неизвестная ошибка"
        return {"error": f"Синхронизация не выполнена: {detail}"}
    if status == "partial":
        detail = "; ".join(errors[:3])
        return {"message": f"Синхронизация выполнена частично: {detail}"}
    return {"message": "Синхронизация выполнена"}


def _has_loaded_dates_from(session: Session, effective_from: date) -> bool:
    return (
        session.scalar(
            select(DeliveryRequest.id)
            .where(DeliveryRequest.delivery_date >= effective_from)
            .limit(1)
        )
        is not None
    )


def _tariff_rows(session: Session, tariffs: List[TariffVersion]) -> List[Dict[str, object]]:
    rows = []
    for tariff in tariffs:
        locked = _has_loaded_dates_from(session, tariff.effective_from)
        rows.append(
            {
                "tariff": tariff,
                "can_edit": not locked,
                "lock_reason": "Есть загруженные даты с этой даты или позже" if locked else "",
            }
        )
    return rows


@router.get("/", response_class=HTMLResponse)
def index() -> RedirectResponse:
    return _redirect("/salary")


@router.get("/salary", response_class=HTMLResponse)
def salary_page(
    request: Request,
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    period = _default_period(session)
    start_date = _parse_date_param(start, period["start"])
    end_date = _parse_date_param(end, period["end"])
    summary = salary_summary(session, start_date, end_date)
    return _template(
        request,
        "salary.html",
        {
            "start": start_date,
            "end": end_date,
            "summary": summary,
            "message": request.query_params.get("message"),
            "error": request.query_params.get("error"),
        },
    )


@router.post("/salary/recalculate")
def recalculate_salary(
    start: str = Form(...),
    end: str = Form(...),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    start_date = _parse_date_param(start, date.today())
    end_date = _parse_date_param(end, start_date)
    recalculate_salary_days(session, start_date, end_date)
    session.commit()
    return _period_redirect("/salary", start_date, end_date, message="Пересчет выполнен")


@router.post("/salary/sync")
def sync_salary(
    start: str = Form(...),
    end: str = Form(...),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    start_date = _parse_date_param(start, date.today())
    end_date = _parse_date_param(end, start_date)
    return _period_redirect("/salary", start_date, end_date, **_sync_period(session, start_date, end_date))


@router.get("/salary/drivers/{driver_id}", response_class=HTMLResponse)
def driver_days(
    request: Request,
    driver_id: int,
    start: str = Query(...),
    end: str = Query(...),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    start_date = _parse_date_param(start, date.today())
    end_date = _parse_date_param(end, start_date)
    days = session.scalars(
        select(CalculatedDay)
        .where(
            CalculatedDay.driver_id == driver_id,
            CalculatedDay.delivery_date >= start_date,
            CalculatedDay.delivery_date <= end_date,
        )
        .options(selectinload(CalculatedDay.driver), selectinload(CalculatedDay.tariff_version))
        .order_by(CalculatedDay.delivery_date)
    ).all()
    if not days:
        raise HTTPException(status_code=404, detail="Нет расчетных дней")
    return _template(request, "_driver_days.html", {"days": days, "start": start_date, "end": end_date})


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    ensure_default_tariff(session)
    session.commit()
    tariffs = session.scalars(
        select(TariffVersion)
        .options(
            selectinload(TariffVersion.point_brackets),
            selectinload(TariffVersion.weight_brackets),
        )
        .order_by(TariffVersion.effective_from.desc())
    ).all()
    return _template(
        request,
        "settings.html",
        {
            "tariff_rows": _tariff_rows(session, tariffs),
            "latest_tariff": tariffs[0] if tariffs else None,
            "message": request.query_params.get("message"),
            "error": request.query_params.get("error"),
        },
    )


def _parse_decimal(raw_value: str, value_kind: str) -> Decimal:
    try:
        return Decimal(raw_value.replace(",", "."))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{value_kind}: нечисловое значение «{raw_value}»") from exc


def _parse_threshold_brackets(
    min_values: List[str],
    amounts: List[str],
    value_kind: str,
    integer_min: bool = False,
) -> List[Dict[str, Optional[Decimal]]]:
    if len(min_values) != len(amounts):
        raise ValueError(f"{value_kind}: количество порогов и сумм не совпадает")
    brackets = []
    seen = set()
    for line_no, (min_raw, amount_raw) in enumerate(zip(min_values, amounts), start=1):
        min_text = min_raw.strip()
        amount_text = amount_raw.strip()
        if not min_text and not amount_text:
            continue
        if not min_text or not amount_text:
            raise ValueError(f"{value_kind}: строка {line_no} должна содержать порог и надбавку")
        min_value = _parse_decimal(min_text, value_kind)
        amount = _parse_decimal(amount_text, value_kind)
        if min_value < 0:
            raise ValueError(f"{value_kind}: строка {line_no} содержит отрицательный порог")
        if integer_min and min_value != min_value.to_integral_value():
            raise ValueError(f"{value_kind}: строка {line_no} должна содержать целое число точек")
        if min_value in seen:
            raise ValueError(f"{value_kind}: порог {min_text} повторяется")
        seen.add(min_value)
        max_value = None
        brackets.append({"min_value": min_value, "max_value": max_value, "amount": amount})
    return sorted(brackets, key=lambda bracket: bracket["min_value"] or Decimal("0"))


@router.post("/settings/tariffs")
def create_tariff(
    effective_from: str = Form(...),
    base_daily_rate: str = Form(...),
    shift_end_time: str = Form("18:00"),
    overtime_hourly_rate: str = Form("0"),
    point_min_values: List[str] = Form([]),
    point_amounts: List[str] = Form([]),
    weight_min_values: List[str] = Form([]),
    weight_amounts: List[str] = Form([]),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    try:
        tariff_date = _parse_date_param(effective_from, date.today())
        shift_end = time.fromisoformat(shift_end_time)
        tariff = create_tariff_version(
            session,
            effective_from=tariff_date,
            base_daily_rate=Decimal(base_daily_rate.replace(",", ".")),
            shift_end_time=shift_end,
            overtime_hourly_rate=Decimal(overtime_hourly_rate.replace(",", ".")),
            point_brackets=_parse_threshold_brackets(point_min_values, point_amounts, "Точки", True),
            weight_brackets=_parse_threshold_brackets(weight_min_values, weight_amounts, "Вес"),
        )
        bounds = delivery_date_bounds(session)
        if bounds:
            recalculate_salary_days(session, max(tariff.effective_from, bounds["start"]), bounds["end"])
        session.commit()
        return _redirect("/settings?message=Тарифная версия создана")
    except Exception as exc:  # noqa: BLE001 - show validation/import errors in UI.
        session.rollback()
        return _redirect(f"/settings?error={str(exc)}")


@router.post("/settings/tariffs/{tariff_id}")
def save_tariff(
    tariff_id: int,
    effective_from: str = Form(...),
    base_daily_rate: str = Form(...),
    shift_end_time: str = Form("18:00"),
    overtime_hourly_rate: str = Form("0"),
    point_min_values: List[str] = Form([]),
    point_amounts: List[str] = Form([]),
    weight_min_values: List[str] = Form([]),
    weight_amounts: List[str] = Form([]),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    tariff = session.scalar(
        select(TariffVersion)
        .options(
            selectinload(TariffVersion.point_brackets),
            selectinload(TariffVersion.weight_brackets),
        )
        .where(TariffVersion.id == tariff_id)
    )
    if tariff is None:
        raise HTTPException(status_code=404, detail="Тариф не найден")
    try:
        if _has_loaded_dates_from(session, tariff.effective_from):
            raise ValueError("Тариф нельзя редактировать: есть загруженные даты с этой даты или позже")
        tariff_date = _parse_date_param(effective_from, tariff.effective_from)
        if _has_loaded_dates_from(session, tariff_date):
            raise ValueError("Дата действия попадает в уже загруженный период")
        update_tariff_version(
            session,
            tariff,
            effective_from=tariff_date,
            base_daily_rate=Decimal(base_daily_rate.replace(",", ".")),
            shift_end_time=time.fromisoformat(shift_end_time),
            overtime_hourly_rate=Decimal(overtime_hourly_rate.replace(",", ".")),
            point_brackets=_parse_threshold_brackets(point_min_values, point_amounts, "Точки", True),
            weight_brackets=_parse_threshold_brackets(weight_min_values, weight_amounts, "Вес"),
        )
        session.commit()
        return _redirect("/settings?message=Тарифная версия сохранена")
    except Exception as exc:  # noqa: BLE001 - show validation/import errors in UI.
        session.rollback()
        return _redirect(f"/settings?error={str(exc)}")


@router.get("/syncs", response_class=HTMLResponse)
def syncs_page(
    request: Request,
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    period = _default_period(session)
    start_date = _parse_date_param(start, period["start"])
    end_date = _parse_date_param(end, period["end"])
    syncs = session.scalars(select(SyncRun).order_by(SyncRun.started_at.desc()).limit(100)).all()
    return _template(
        request,
        "syncs.html",
        {
            "syncs": syncs,
            "start": start_date,
            "end": end_date,
            "message": request.query_params.get("message"),
            "error": request.query_params.get("error"),
        },
    )


@router.post("/syncs/run")
def run_sync(
    start: str = Form(...),
    end: str = Form(...),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    start_date = _parse_date_param(start, date.today())
    end_date = _parse_date_param(end, start_date)
    return _period_redirect("/syncs", start_date, end_date, **_sync_period(session, start_date, end_date))
