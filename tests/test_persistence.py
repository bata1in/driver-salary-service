from __future__ import annotations

import os
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.db import Base, build_engine
from app.models import CalculatedDay, DeliveryRequest, Driver, RouteSheet, SyncRun, TariffVersion
from app.odata.sync import ODataSyncService, _best_delivery_time, normalize_counterparty_name
from app.salary.engine import normalize_address
from app.salary.service import recalculate_salary_days, salary_summary


@pytest.fixture()
def sqlite_session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    with Session() as session:
        yield session


def seed_salary_day(session):
    driver = Driver(ref_key="driver-1", name="Иванов")
    route = RouteSheet(
        ref_key="route-1",
        number="1",
        delivery_date=date(2026, 5, 1),
        weight_kg=Decimal("100"),
        driver=driver,
        payload={},
    )
    request = DeliveryRequest(
        ref_key="request-1",
        source_line_key="1",
        route_sheet=route,
        driver=driver,
        delivery_date=date(2026, 5, 1),
        address_raw="Москва, ул. Ленина, 1",
        address_normalized=normalize_address("Москва, ул. Ленина, 1"),
        is_pickup=False,
        payload={},
    )
    tariff = TariffVersion(
        effective_from=date(1900, 1, 1),
        base_daily_rate=Decimal("4000"),
        overtime_hourly_rate=Decimal("0"),
    )
    session.add_all([driver, route, request, tariff])
    session.commit()


def test_recalculation_is_idempotent_on_sqlite(sqlite_session):
    seed_salary_day(sqlite_session)

    recalculate_salary_days(sqlite_session, date(2026, 5, 1), date(2026, 5, 1))
    recalculate_salary_days(sqlite_session, date(2026, 5, 1), date(2026, 5, 1))
    sqlite_session.commit()

    summary = salary_summary(sqlite_session, date(2026, 5, 1), date(2026, 5, 1))
    assert len(summary) == 1
    assert summary[0]["total_amount"] == Decimal("4000.00")


class FakeODataClient:
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_exc_info):
        return None

    def iter_entities(self, entity, params=None):
        if entity == "employees":
            return iter([{"Ref_Key": "driver-1", "Description": "Иванов"}])
        return iter(
            [
                {
                    "Ref_Key": "route-1",
                    "Number": "1",
                    "Date": "2026-05-01",
                    "Weight": "100",
                    "Driver_Key": "driver-1",
                    "Rows": [
                        {
                            "Ref_Key": "request-1",
                            "LineNumber": 1,
                            "Address": "Москва, ул. Ленина, 1",
                            "IsPickup": False,
                        }
                    ],
                }
            ]
        )


class FakeCounterpartyODataClient:
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_exc_info):
        return None

    def iter_entities(self, entity, params=None):
        if entity == "employees":
            return iter([{"Ref_Key": "driver-1", "Description": "Иванов"}])
        return iter(
            [
                {
                    "Ref_Key": "route-1",
                    "Number": "1",
                    "Date": "2026-05-01",
                    "Weight": "100",
                    "Driver_Key": "driver-1",
                    "Rows": [
                        {
                            "LineNumber": 1,
                            "Address": "Москва, ул. Ленина, 1",
                            "Контрагент": "counterparty-1",
                            "КонтактноеЛицо": "Контакт Фолбэк",
                            "IsPickup": False,
                        }
                    ],
                }
            ]
        )

    def get(self, path, params=None):
        if "counterparty-1" in path:
            return {"Ref_Key": "counterparty-1", "Description": "ООО Ромашка"}
        return {}


def test_repeated_sync_does_not_create_duplicates(sqlite_session, monkeypatch):
    monkeypatch.setattr("app.odata.sync.ODataClient", FakeODataClient)
    settings = replace(
        get_settings(),
        odata_base_url="http://example.test/odata",
        odata_employee_entity="employees",
        odata_route_sheet_entity="routes",
        odata_route_requests_field="Rows",
    )

    service = ODataSyncService(sqlite_session, settings)
    service.sync_period(date(2026, 5, 1), date(2026, 5, 1))
    service.sync_period(date(2026, 5, 1), date(2026, 5, 1))
    sqlite_session.commit()

    assert len(sqlite_session.scalars(select(Driver)).all()) == 1
    assert len(sqlite_session.scalars(select(RouteSheet)).all()) == 1
    assert len(sqlite_session.scalars(select(DeliveryRequest)).all()) == 1
    assert len(sqlite_session.scalars(select(SyncRun)).all()) == 2


def test_sync_stores_counterparty_name_and_calculated_detail(sqlite_session, monkeypatch):
    monkeypatch.setattr("app.odata.sync.ODataClient", FakeCounterpartyODataClient)
    settings = replace(
        get_settings(),
        odata_base_url="http://example.test/odata",
        odata_employee_entity="employees",
        odata_route_sheet_entity="routes",
        odata_route_requests_field="Rows",
    )

    service = ODataSyncService(sqlite_session, settings)
    sync_run = service.sync_period(date(2026, 5, 1), date(2026, 5, 1))
    sqlite_session.commit()

    request = sqlite_session.scalar(select(DeliveryRequest))
    calculated_day = sqlite_session.scalar(select(CalculatedDay))
    assert sync_run.status == "success"
    assert request.counterparty_ref_key == "counterparty-1"
    assert request.counterparty_name == "ООО Ромашка"
    assert calculated_day.details[0]["counterparty_name"] == "ООО Ромашка"
    assert calculated_day.details[0]["route_date"] == "2026-05-01"


def test_counterparty_name_normalization_keeps_organizations_readable():
    assert normalize_counterparty_name("Индивидуальный предприниматель Иванов Иван") == "ИП Иванов Иван"
    assert normalize_counterparty_name("ИНТЕРМЭН ООО") == 'ООО "ИНТЕРМЭН"'
    assert normalize_counterparty_name('ООО "ЗИНГЕР КАФЕ"') == 'ООО "ЗИНГЕР КАФЕ"'


def test_fact_arrival_is_the_only_overtime_source():
    payload = {
        "ДатаВремяАвтоматическогоПосещения": "2026-05-01T18:10:00",
        "ДатаВремяАвтоматическогоВыбытия": "2026-05-01T19:30:00",
        "ДатаВремяОтметкиДоставки": "2026-05-02T08:00:00",
    }

    result = _best_delivery_time(
        payload,
        ["ДатаВремяАвтоматическогоПосещения"],
        date(2026, 5, 1),
    )

    assert result == datetime(2026, 5, 1, 18, 10)


def test_empty_fact_arrival_disables_overtime_even_when_other_times_exist():
    payload = {
        "ДатаВремяАвтоматическогоПосещения": "0001-01-01T00:00:00",
        "ДатаВремяАвтоматическогоВыбытия": "2026-05-01T19:30:00",
        "ДатаВремяОтметкиДоставки": "2026-05-01T19:45:00",
    }

    result = _best_delivery_time(
        payload,
        ["ДатаВремяАвтоматическогоПосещения"],
        date(2026, 5, 1),
    )

    assert result is None


def test_same_calculation_contract_on_configured_database():
    if os.environ.get("RUN_POSTGRES_CONTRACT") != "1":
        pytest.skip("Set RUN_POSTGRES_CONTRACT=1 and DATABASE_URL to run PostgreSQL contract")

    database_url = os.environ["DATABASE_URL"]
    engine = build_engine(database_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    with Session() as session:
        seed_salary_day(session)
        recalculate_salary_days(session, date(2026, 5, 1), date(2026, 5, 1))
        session.commit()
        summary = salary_summary(session, date(2026, 5, 1), date(2026, 5, 1))
        assert summary[0]["total_amount"] == Decimal("4000.00")
