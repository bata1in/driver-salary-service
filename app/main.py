from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.db import SessionLocal, init_db
from app.salary.service import ensure_default_tariff
from app.web.routes import router


def create_app() -> FastAPI:
    app = FastAPI(title="Расчет ЗП водителей")
    app.mount("/static", StaticFiles(directory="app/web/static"), name="static")
    app.include_router(router)

    @app.on_event("startup")
    def _startup() -> None:
        init_db()
        with SessionLocal() as session:
            ensure_default_tariff(session)
            session.commit()

    return app


app = create_app()
