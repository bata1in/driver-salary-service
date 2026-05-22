# Расчет ЗП водителей

Локальный FastAPI-сервис для расчета зарплаты водителей по формальным правилам. Excel из `outputs/` остается только ориентиром для sanity-check; источником данных для V1 является 1С OData.

## Контекст проекта

Перед продолжением разработки прочитайте [`docs/PROJECT_CONTEXT.md`](docs/PROJECT_CONTEXT.md). Там собраны карта файлов, текущая логика, состояние серверного деплоя, HTTPS/DNSSEC и важные команды, чтобы не перечитывать всю папку заново.

## Git

Текущий `origin` настроен на приватный bare-репозиторий на сервере:

```bash
codex@81.177.141.63:/home/codex/repos/driver-salary-service.git
```

Рабочий процесс, ветки, теги деплоя и перенос на будущий GitHub/GitLab описаны в [`docs/PROJECT_CONTEXT.md`](docs/PROJECT_CONTEXT.md#git-workflow).

## Быстрый старт

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip wheel
python -m pip install -e ".[test,postgres]"
cp .env.example .env
uvicorn app.main:app --reload
```

По умолчанию используется `sqlite:///./data/app.db`. Для PostgreSQL задайте `DATABASE_URL`, например:

```bash
DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/driver_salary
```

## Миграции

Локальный запуск сам создаст таблицы через SQLAlchemy metadata. Для серверного режима и контролируемых изменений используйте Alembic:

```bash
alembic upgrade head
```

## Проверки

```bash
pytest
```

PostgreSQL-контракт включается явно:

```bash
RUN_POSTGRES_CONTRACT=1 DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/test_driver_salary pytest
```

## Правило расчета

День агрегируется по паре `дата доставки + водитель`. Зарплата дня:

```text
базовая ставка + бонус за уникальные точки + бонус за вес дня + переработка
```

Точки считаются по уникальным нормализованным адресам. Заявки-заборы показываются в детализации, но не добавляют бонусную точку. Вес считается по уникальным маршрутным листам дня. Для каждого дня применяется последняя тарифная версия с `effective_from <= дата доставки`.
