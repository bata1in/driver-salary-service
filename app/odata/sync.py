from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import DeliveryRequest, Driver, RouteSheet, SyncRun
from app.odata.client import ODataClient
from app.salary.engine import normalize_address
from app.salary.service import recalculate_salary_days


def _first_present(payload: Dict[str, Any], field_names: Iterable[str]) -> Any:
    for field in field_names:
        if field in payload and payload[field] not in (None, ""):
            return payload[field]
    return None


def _is_empty_ref(value: Any) -> bool:
    if value is None:
        return True
    return str(value).strip().lower() in {
        "",
        "00000000-0000-0000-0000-000000000000",
    }


def _first_key(payload: Dict[str, Any], field_names: Iterable[str]) -> Optional[str]:
    value = _first_present(payload, field_names)
    if isinstance(value, dict):
        value = value.get("Ref_Key") or value.get("RefKey") or value.get("Key") or value.get("Description")
    if _is_empty_ref(value):
        return None
    return str(value)


def _parse_decimal(value: Any) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value).replace(",", "."))
    except (InvalidOperation, ValueError):
        return None


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "да", "истина"}


def _parse_date(value: Any) -> Optional[date]:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%d.%m.%Y", "%d.%m.%Y %H:%M:%S"):
        try:
            parsed = datetime.strptime(text[: len(fmt)], fmt).date()
            return parsed if parsed.year > 1901 else None
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        return parsed if parsed.year > 1901 else None
    except ValueError:
        return None


def _parse_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
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


def _best_delivery_time(
    payload: Dict[str, Any],
    field_names: Iterable[str],
    delivery_date: date,
) -> Optional[datetime]:
    same_day_times = []
    for field in field_names:
        dt = _parse_datetime(payload.get(field))
        if dt is not None and dt.date() == delivery_date:
            same_day_times.append(dt)
    return max(same_day_times, default=None)


def _upsert_driver(session: Session, ref_key: str, name: str, external_code: Optional[str] = None) -> Tuple[Driver, bool]:
    driver = session.scalar(select(Driver).where(Driver.ref_key == ref_key))
    created = driver is None
    if created:
        driver = Driver(ref_key=ref_key, name=name or ref_key, external_code=external_code)
        session.add(driver)
    else:
        if name and name != ref_key:
            driver.name = name
        driver.external_code = external_code or driver.external_code
    session.flush()
    return driver, created


def _synthetic_driver(session: Session, ref_key: Optional[str]) -> Driver:
    key = ref_key or "unknown-driver"
    existing = session.scalar(select(Driver).where(Driver.ref_key == key))
    if existing is not None:
        return existing
    name = key if key != "unknown-driver" else "Неизвестный водитель"
    driver, _created = _upsert_driver(session, key, name)
    return driver


def _upsert_route_sheet(
    session: Session,
    payload: Dict[str, Any],
    settings: Settings,
    driver: Optional[Driver],
) -> Tuple[Optional[RouteSheet], bool, Optional[str]]:
    ref_key = _first_key(payload, settings.odata_ref_key_fields)
    delivery_date = _parse_date(_first_present(payload, settings.odata_route_date_fields))
    if not ref_key or delivery_date is None:
        return None, False, "Маршрутный лист без Ref_Key или даты доставки"

    route = session.scalar(select(RouteSheet).where(RouteSheet.ref_key == ref_key))
    created = route is None
    if created:
        route = RouteSheet(ref_key=ref_key, delivery_date=delivery_date)
        session.add(route)

    route.number = str(_first_present(payload, settings.odata_route_number_fields) or "")
    route.delivery_date = delivery_date
    route.driver = driver
    route.weight_kg = _parse_decimal(_first_present(payload, settings.odata_route_weight_fields))
    route.payload = payload
    session.flush()
    return route, created, None


def _request_rows(route_payload: Dict[str, Any], settings: Settings) -> List[Dict[str, Any]]:
    rows = route_payload.get(settings.odata_route_requests_field)
    if isinstance(rows, dict):
        rows = rows.get("value") or rows.get("results")
    if isinstance(rows, list):
        return [row for row in rows if isinstance(row, dict)]
    return []


def _entity_ref_path(entity: str, ref_key: str) -> str:
    return f"{entity}(guid'{ref_key}')"


def normalize_counterparty_name(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    name = " ".join(str(value).strip().split())
    lower_name = name.lower()
    if lower_name.startswith("индивидуальный предприниматель "):
        return f"ИП {name[len('Индивидуальный предприниматель '):].strip()}"
    if name.endswith(" ООО") and not name.startswith("ООО"):
        return f"ООО \"{name[:-4].strip()}\""
    return name


def _counterparty_name(
    client: ODataClient,
    settings: Settings,
    counterparty_ref_key: Optional[str],
    cache: Dict[str, Optional[str]],
) -> Optional[str]:
    if not counterparty_ref_key:
        return None
    if counterparty_ref_key not in cache:
        payload = client.get(_entity_ref_path(settings.odata_counterparty_entity, counterparty_ref_key))
        name = _first_present(payload, settings.odata_counterparty_name_fields)
        cache[counterparty_ref_key] = normalize_counterparty_name(str(name)) if name else None
    return cache[counterparty_ref_key]


def _upsert_delivery_request(
    session: Session,
    route: RouteSheet,
    row_payload: Dict[str, Any],
    request_payload: Dict[str, Any],
    settings: Settings,
    fallback_driver: Driver,
    row_index: int,
    counterparty_name: Optional[str] = None,
) -> Tuple[Optional[DeliveryRequest], bool, Optional[str]]:
    payload = {**row_payload, **request_payload}
    address = str(_first_present(payload, settings.odata_address_fields) or "").strip()
    if not address:
        return None, False, f"Строка {route.ref_key}:{row_index} без адреса"

    delivery_date = _parse_date(_first_present(payload, settings.odata_route_date_fields)) or route.delivery_date
    delivery_request_ref_key = (
        _first_key(row_payload, settings.odata_delivery_request_key_fields)
        or _first_key(request_payload, settings.odata_ref_key_fields)
    )
    source_line_key = str(row_payload.get("LineNumber") or row_payload.get("НомерСтроки") or row_index)
    ref_key = delivery_request_ref_key or f"{route.ref_key}:{source_line_key}"
    driver_key = _first_key(payload, settings.odata_driver_fields)
    counterparty_ref_key = _first_key(payload, settings.odata_counterparty_fields)
    driver = fallback_driver
    if driver_key and driver_key != fallback_driver.ref_key:
        driver = _synthetic_driver(session, driver_key)

    request = session.scalar(select(DeliveryRequest).where(DeliveryRequest.ref_key == ref_key))
    created = request is None
    if created:
        request = DeliveryRequest(ref_key=ref_key, driver=driver, route_sheet=route, delivery_date=delivery_date)
        session.add(request)

    request.source_line_key = source_line_key
    request.route_sheet = route
    request.delivery_request_ref_key = delivery_request_ref_key
    request.driver = driver
    request.delivery_date = delivery_date
    request.counterparty_ref_key = counterparty_ref_key
    request.counterparty_name = counterparty_name
    request.address_raw = address
    request.address_normalized = normalize_address(address)
    request.is_pickup = _parse_bool(_first_present(payload, settings.odata_pickup_fields))
    request.weight_kg = _parse_decimal(_first_present(payload, settings.odata_route_weight_fields))
    request.delivered_at = _best_delivery_time(payload, settings.odata_delivered_at_fields, delivery_date)
    request.payload = payload
    session.flush()
    return request, created, None


class ODataSyncService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def sync_period(self, start: date, end: date) -> SyncRun:
        sync_run = SyncRun(period_start=start, period_end=end, status="running", errors=[])
        self.session.add(sync_run)
        self.session.flush()

        added = 0
        updated = 0
        errors: List[str] = []

        if not self.settings.odata_configured:
            sync_run.status = "failed"
            sync_run.finished_at = datetime.utcnow()
            sync_run.errors = ["ODATA_BASE_URL не задан"]
            sync_run.error_count = 1
            self.session.flush()
            return sync_run

        try:
            with ODataClient(
                base_url=self.settings.odata_base_url,
                username=self.settings.odata_username,
                password=self.settings.odata_password,
                verify_tls=self.settings.odata_verify_tls,
            ) as client:
                employees = list(client.iter_entities(self.settings.odata_employee_entity))
                for employee in employees:
                    ref_key = _first_key(employee, self.settings.odata_ref_key_fields)
                    if not ref_key:
                        continue
                    name = str(_first_present(employee, self.settings.odata_employee_name_fields) or ref_key)
                    _driver, created = _upsert_driver(self.session, ref_key, name)
                    added += 1 if created else 0
                    updated += 0 if created else 1

                params: Dict[str, Any] = {}
                request_cache: Dict[str, Dict[str, Any]] = {}
                counterparty_cache: Dict[str, Optional[str]] = {}
                for route_payload in client.iter_entities(self.settings.odata_route_sheet_entity, params=params):
                    route_date = _parse_date(_first_present(route_payload, self.settings.odata_route_date_fields))
                    if route_date is not None and not (start <= route_date <= end):
                        continue

                    driver_key = _first_key(route_payload, self.settings.odata_driver_fields)
                    driver = _synthetic_driver(self.session, driver_key)
                    route, created, error = _upsert_route_sheet(self.session, route_payload, self.settings, driver)
                    if error:
                        errors.append(error)
                        continue
                    added += 1 if created else 0
                    updated += 0 if created else 1

                    for row_index, row_payload in enumerate(_request_rows(route_payload, self.settings), start=1):
                        request_ref_key = _first_key(row_payload, self.settings.odata_delivery_request_key_fields)
                        request_payload: Dict[str, Any] = {}
                        if request_ref_key:
                            if request_ref_key not in request_cache:
                                request_cache[request_ref_key] = client.get(
                                    _entity_ref_path(self.settings.odata_delivery_request_entity, request_ref_key)
                                )
                            request_payload = request_cache[request_ref_key]
                        merged_payload = {**row_payload, **request_payload}
                        counterparty_ref_key = _first_key(merged_payload, self.settings.odata_counterparty_fields)
                        counterparty_name = None
                        if counterparty_ref_key:
                            try:
                                counterparty_name = _counterparty_name(
                                    client,
                                    self.settings,
                                    counterparty_ref_key,
                                    counterparty_cache,
                                )
                            except Exception as exc:  # noqa: BLE001 - fallback to contact/address when lookup fails.
                                counterparty_cache[counterparty_ref_key] = None
                                errors.append(f"Контрагент {counterparty_ref_key}: {exc}")
                        _request, row_created, row_error = _upsert_delivery_request(
                            self.session,
                            route,
                            row_payload,
                            request_payload,
                            self.settings,
                            driver,
                            row_index,
                            counterparty_name,
                        )
                        if row_error:
                            errors.append(row_error)
                            continue
                        added += 1 if row_created else 0
                        updated += 0 if row_created else 1

            recalculate_salary_days(self.session, start, end)
            sync_run.status = "success" if not errors else "partial"
        except Exception as exc:  # noqa: BLE001 - sync log should capture any integration failure.
            errors.append(str(exc))
            sync_run.status = "failed"

        sync_run.finished_at = datetime.utcnow()
        sync_run.added_count = added
        sync_run.updated_count = updated
        sync_run.error_count = len(errors)
        sync_run.errors = errors
        self.session.flush()
        return sync_run
