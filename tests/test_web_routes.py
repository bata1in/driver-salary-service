from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_session
from app.models import DeliveryRequest, Driver, RouteSheet, TariffVersion
from app.salary.engine import normalize_address
from app.salary.service import recalculate_salary_days
from app.security import require_auth
from app.web.routes import router


def build_test_client():
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    session = Session()

    app = FastAPI()
    app.mount("/static", StaticFiles(directory="app/web/static"), name="static")
    app.include_router(router)

    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[require_auth] = lambda: None
    return TestClient(app), session


def seed_calculated_day(session):
    driver = Driver(ref_key="driver-1", name="Иванов")
    route = RouteSheet(
        ref_key="route-1",
        number="1",
        delivery_date=date(2026, 5, 1),
        weight_kg=Decimal("52000"),
        driver=driver,
        payload={},
    )
    request = DeliveryRequest(
        ref_key="request-1",
        source_line_key="1",
        route_sheet=route,
        driver=driver,
        delivery_date=date(2026, 5, 1),
        counterparty_ref_key="counterparty-1",
        counterparty_name="ООО Ромашка",
        address_raw="Москва, ул. Ленина, 1",
        address_normalized=normalize_address("Москва, ул. Ленина, 1"),
        is_pickup=True,
        payload={},
    )
    tariff = TariffVersion(
        effective_from=date(1900, 1, 1),
        base_daily_rate=Decimal("4000"),
        overtime_hourly_rate=Decimal("0"),
    )
    session.add_all([driver, route, request, tariff])
    session.commit()
    recalculate_salary_days(session, date(2026, 5, 1), date(2026, 5, 1))
    session.commit()
    return driver


def test_salary_page_has_no_sync_button_and_uses_modal_target():
    client, session = build_test_client()
    seed_calculated_day(session)

    response = client.get("/salary?start=2026-05-01&end=2026-05-01")

    assert response.status_code == 200
    assert "Синхронизировать 1С" not in response.text
    assert 'hx-dialog="#driver-dialog"' in response.text
    assert "52 000.000" in response.text


def test_driver_days_detail_contains_counterparty_and_pickup_row():
    client, session = build_test_client()
    driver = seed_calculated_day(session)

    response = client.get(f"/salary/drivers/{driver.id}?start=2026-05-01&end=2026-05-01")

    assert response.status_code == 200
    assert "ООО Ромашка" in response.text
    assert "pickup-row" in response.text
    assert "<th>Тип</th>" not in response.text


def test_syncs_page_contains_sync_form():
    client, _session = build_test_client()

    response = client.get("/syncs")

    assert response.status_code == 200
    assert 'action="/syncs/run"' in response.text
    assert "Синхронизировать 1С" in response.text


def test_settings_page_locks_tariff_with_loaded_dates():
    client, session = build_test_client()
    seed_calculated_day(session)

    response = client.get("/settings")

    assert response.status_code == 200
    assert "Только просмотр" in response.text
    assert "Есть загруженные даты" in response.text
