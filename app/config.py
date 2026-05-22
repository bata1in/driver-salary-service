from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _bool_env(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    return int(value)


def _csv_env(name: str, default: str) -> List[str]:
    value = os.environ.get(name, default)
    return [part.strip() for part in value.split(",") if part.strip()]


@dataclass(frozen=True)
class Settings:
    app_name: str
    database_url: str
    echo_sql: bool
    app_host: str
    app_port: int
    auth_username: Optional[str]
    auth_password: Optional[str]
    odata_base_url: Optional[str]
    odata_username: Optional[str]
    odata_password: Optional[str]
    odata_verify_tls: bool
    odata_route_sheet_entity: str
    odata_delivery_request_entity: str
    odata_employee_entity: str
    odata_counterparty_entity: str
    odata_route_requests_field: str
    odata_delivery_request_key_fields: List[str]
    odata_ref_key_fields: List[str]
    odata_route_number_fields: List[str]
    odata_route_date_fields: List[str]
    odata_route_weight_fields: List[str]
    odata_driver_fields: List[str]
    odata_employee_name_fields: List[str]
    odata_counterparty_fields: List[str]
    odata_counterparty_name_fields: List[str]
    odata_address_fields: List[str]
    odata_pickup_fields: List[str]
    odata_delivered_at_fields: List[str]

    @property
    def odata_configured(self) -> bool:
        return bool(self.odata_base_url)


def get_settings() -> Settings:
    _load_dotenv(Path(".env"))
    return Settings(
        app_name=os.environ.get("APP_NAME", "Расчет ЗП водителей"),
        database_url=os.environ.get("DATABASE_URL", "sqlite:///./data/app.db"),
        echo_sql=_bool_env("ECHO_SQL", False),
        app_host=os.environ.get("APP_HOST", "127.0.0.1"),
        app_port=_int_env("APP_PORT", 8000),
        auth_username=os.environ.get("APP_USERNAME") or None,
        auth_password=os.environ.get("APP_PASSWORD") or None,
        odata_base_url=os.environ.get("ODATA_BASE_URL") or None,
        odata_username=os.environ.get("ODATA_USERNAME") or None,
        odata_password=os.environ.get("ODATA_PASSWORD") or None,
        odata_verify_tls=_bool_env("ODATA_VERIFY_TLS", True),
        odata_route_sheet_entity=os.environ.get(
            "ODATA_ROUTE_SHEET_ENTITY", "Document_МаршрутныйЛист"
        ),
        odata_delivery_request_entity=os.environ.get(
            "ODATA_DELIVERY_REQUEST_ENTITY", "Document_ЗаявкаНаДоставку"
        ),
        odata_employee_entity=os.environ.get("ODATA_EMPLOYEE_ENTITY", "Catalog_Сотрудники"),
        odata_counterparty_entity=os.environ.get("ODATA_COUNTERPARTY_ENTITY", "Catalog_Контрагенты"),
        odata_route_requests_field=os.environ.get("ODATA_ROUTE_REQUESTS_FIELD", "Заявки"),
        odata_delivery_request_key_fields=_csv_env(
            "ODATA_DELIVERY_REQUEST_KEY_FIELDS", "Заявка_Key,DeliveryRequest_Key"
        ),
        odata_ref_key_fields=_csv_env("ODATA_REF_KEY_FIELDS", "Ref_Key,RefKey"),
        odata_route_number_fields=_csv_env("ODATA_ROUTE_NUMBER_FIELDS", "Number,Номер"),
        odata_route_date_fields=_csv_env(
            "ODATA_ROUTE_DATE_FIELDS", "ДатаДоставки,DeliveryDate,Date,Дата"
        ),
        odata_route_weight_fields=_csv_env("ODATA_ROUTE_WEIGHT_FIELDS", "Вес,Weight,WeightKg"),
        odata_driver_fields=_csv_env(
            "ODATA_DRIVER_FIELDS", "Водитель_Key,Driver_Key,Сотрудник_Key,Driver"
        ),
        odata_employee_name_fields=_csv_env(
            "ODATA_EMPLOYEE_NAME_FIELDS", "Description,Наименование,Name"
        ),
        odata_counterparty_fields=_csv_env(
            "ODATA_COUNTERPARTY_FIELDS", "Контрагент,Контрагент_Key,Counterparty,Customer"
        ),
        odata_counterparty_name_fields=_csv_env(
            "ODATA_COUNTERPARTY_NAME_FIELDS", "НаименованиеПолное,FullName,Description,Наименование,Name"
        ),
        odata_address_fields=_csv_env(
            "ODATA_ADDRESS_FIELDS", "АдресДоставки,Адрес,Address,DeliveryAddress"
        ),
        odata_pickup_fields=_csv_env("ODATA_PICKUP_FIELDS", "ЭтоЗабор,Забор,IsPickup"),
        odata_delivered_at_fields=_csv_env(
            "ODATA_DELIVERED_AT_FIELDS", "ДатаВремяАвтоматическогоПосещения"
        ),
    )
