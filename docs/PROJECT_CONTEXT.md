# Контекст проекта

Обновлено: 2026-05-22

Этот файл стоит читать первым при продолжении работы над сервисом. Здесь собраны архитектура, карта файлов, состояние деплоя и последние решения, чтобы не перечитывать всю папку заново.

## Назначение

FastAPI-сервис для расчета зарплаты водителей по данным доставок из 1С OData.

Зарплата за день считается по паре `дата доставки + водитель`:

```text
базовая ставка + доплата за точки + доплата за вес + переработка
```

Формула расчета в последних изменениях не менялась.

## Пользовательский Поток

- `/salary` показывает сводную таблицу водителей на всю ширину.
- Кнопка синхронизации убрана со страницы `/salary`; там остались период и `Пересчитать`.
- Детализация водителя открывается кнопкой `Дни` в native `<dialog>` примерно на 80% окна.
- `/syncs` содержит форму периода и кнопку `Синхронизировать 1С`.
- `/settings` управляет версиями тарифов и пороговыми корзинами.
- На сервере включена HTTP Basic Auth через серверный `.env`.

## Карта Файлов

- `app/main.py` - FastAPI-приложение, подключение роутов и статики.
- `app/config.py` - загрузка `.env` и runtime-настройки, включая имена полей OData.
- `app/db.py` - SQLAlchemy engine/session.
- `app/models.py` - SQLAlchemy-модели.
- `app/odata/client.py` - небольшой HTTP/OData-клиент.
- `app/odata/sync.py` - синхронизация 1С, upsert данных, получение контрагентов, парсинг OData payload.
- `app/salary/engine.py` - чистая логика расчета зарплаты.
- `app/salary/service.py` - сервисы расчета, сохранения и пересчета.
- `app/web/routes.py` - web-роуты FastAPI для зарплаты, синхронизаций и настроек.
- `app/web/formatting.py` - Jinja-фильтры для чисел, денег, дат и веса.
- `app/web/templates/` - Jinja-шаблоны.
- `app/web/static/htmx-lite.js` - легкая подгрузка `hx-get`, модалка и динамические строки настроек.
- `app/web/static/styles.css` - стили интерфейса.
- `migrations/versions/` - Alembic-миграции.
- `tests/` - тесты.

## Модель Данных

В `DeliveryRequest` добавлены поля:

- `counterparty_ref_key`
- `counterparty_name`

Миграция:

```text
migrations/versions/0002_counterparty_fields.py
```

В UI нужно показывать организацию, а не основной контакт. Для существующих и будущих синхронизаций:

- основной вариант: `counterparty_name`;
- fallback: `address_raw`;
- не использовать `КонтактноеЛицо` как видимое значение колонки `Контрагент`.

Контрагенты подтягиваются из каталога 1С `Catalog_Контрагенты`. Предпочтительные поля имени:

```text
НаименованиеПолное, FullName, Description, Наименование, Name
```

Нормализация имени сейчас делает:

- `Индивидуальный предприниматель ...` -> `ИП ...`;
- `... ООО` -> `ООО "..."`.

Некоторые значения каталога валидно не начинаются с `ООО` или `ИП`, например `Розничный покупатель`.

## Настройки OData

Важные поля `.env.example`:

```text
ODATA_COUNTERPARTY_ENTITY=Catalog_Контрагенты
ODATA_COUNTERPARTY_FIELDS=Контрагент,Контрагент_Key,Counterparty,Customer
ODATA_COUNTERPARTY_NAME_FIELDS=НаименованиеПолное,FullName,Description,Наименование,Name
```

Секреты, пароли Basic Auth и OData-пароли должны оставаться только в `.env`. В документацию их не добавлять.

## Реализованные UI-Решения

Страница зарплаты:

- сводная таблица занимает всю ширину;
- детализация открывается в модалке;
- деньги показываются целыми рублями с пробелами тысяч;
- вес показывается с 3 знаками и пробелами тысяч.

Детализация водителя:

- колонка `Маршрут` заменена на `Дата`;
- колонка `Адрес` заменена на `Контрагент`;
- колонка `Тип` удалена;
- старая колонка времени называется `Время по приложению`;
- добавлена колонка `Время отметки`;
- `Время отметки` берется из payload-поля `ДатаВремяОтметкиДоставки`;
- если дата события совпадает с датой маршрутного листа, показывается только `HH:MM`;
- если дата отличается, показывается `dd.mm.yyyy HH:MM`;
- пустое время остается пустым;
- строки заборов подсвечиваются мягким серым фоном;
- блоки метрик сгруппированы парами:
  - под `Точки` сразу доплата за точки;
  - под `Вес` сразу доплата за вес.

Настройки:

- тариф нельзя редактировать, если есть загруженные `DeliveryRequest.delivery_date >= tariff.effective_from`;
- будущие или незадействованные тарифы редактируемые;
- корзины точек и веса теперь задаются порогами, не textarea:
  - точки: `от N точек` + `надбавка, руб`;
  - вес: `от N кг` + `надбавка, руб`;
- backend сохраняет пороги как открытые brackets с `max_value = null`;
- выбор бонуса уже работает по правилу "самый высокий подходящий min-порог".

## Локальные Команды

Установка и тесты:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip wheel
python -m pip install -e ".[test,postgres]"
python3 -m pytest
```

Запуск с SQLite:

```bash
cp .env.example .env
uvicorn app.main:app --reload
```

Запуск локально через Docker/Postgres:

```bash
docker compose -p driver_salary up -d --build
docker compose -p driver_salary ps
docker compose -p driver_salary logs --tail=120 app
```

Используй явное имя compose-проекта `driver_salary`: локальная папка содержит кириллицу, и авто-имя проекта Docker Compose может быть неудобным.

## Git Workflow

Локальный репозиторий уже инициализирован. Текущие удаленные репозитории:

```text
origin: https://github.com/bata1in/driver-salary-service.git
server: codex@81.177.141.63:/home/codex/repos/driver-salary-service.git
branch: main
tag: deploy-2026-05-22
```

`origin` - основной репозиторий на GitHub. `server` - bare-репозиторий на production-сервере, доступный по SSH; он оставлен как резервная копия истории.

Локально для этого проекта настроен отдельный SSH-ключ:

```text
~/.ssh/driver_salary_git_ed25519
```

Ключ не хранить в репозитории. Он нужен для remote `server`. Для `origin` нужна обычная GitHub-аутентификация через HTTPS token, Git Credential Manager, GitHub CLI или SSH-remote.

Обычный рабочий цикл:

```bash
git status
git switch main
git pull --ff-only
git switch -c codex/<short-task-name>

# изменения, затем проверки
python3 -m pytest

git add <files>
git commit -m "Короткое описание изменения"
git push -u origin codex/<short-task-name>
```

Для небольших срочных правок можно коммитить прямо в `main`, но перед этим проверить `git status`, запустить тесты и сделать `git pull --ff-only`.

После успешного деплоя фиксируй точку тегом:

```bash
git tag deploy-YYYY-MM-DD
git push origin main --tags
git push server main --tags
```

Если GitHub-аутентификация на локальной машине еще не настроена, `origin` будет доступен только на чтение. Серверный remote при этом продолжит работать по локально настроенному SSH-ключу:

```bash
git push server main --tags
```

## Деплой

Production-сервер:

```text
host: 81.177.141.63
ssh user: codex
app dir: /home/codex/driver-salary
compose project: driver_salary
```

Пароль от сервера не хранить в документации и не коммитить.

Контейнеры на сервере:

- `driver_salary-app-1`;
- `driver_salary-postgres-1`;
- `driver_salary-caddy-1`.

Полезные команды на сервере:

```bash
cd /home/codex/driver-salary
docker compose -p driver_salary ps
docker compose -p driver_salary logs --tail=120 app
docker compose -p driver_salary logs --tail=120 caddy
docker compose -p driver_salary exec -T app alembic current
docker compose -p driver_salary exec -T postgres psql -U driver_salary -d driver_salary
```

При замене кода на сервере обязательно сохранить:

- `/home/codex/driver-salary/.env`;
- Docker volume `driver_salary_postgres-data`;
- Docker volumes `driver_salary_caddy-data` и `driver_salary_caddy-config`.

Backup последнего деплоя:

```text
/home/codex/driver-salary-backup-20260522-141556.tgz
```

## Состояние Серверной Базы На 2026-05-22

После деплоя и backfill контрагентов:

```text
delivery_requests: 2576
calculated_days: 172
delivery date range: 2026-04-01 .. 2026-05-21
alembic current: 0002_counterparty_fields
org-like counterparty names: 2546 / 2576
```

Оставшиеся значения каталога не в формате `ООО`/`ИП`:

```text
ЧДОУ "ДЕТСКИЙ САД "МИР НА ЛАДОШКЕ"
Розничный покупатель
Розничный покупатель (Ахматов)
Розничный покупатель (Логиненков)
```

## HTTPS И DNS

Целевой домен:

```text
driver.lim-lim.ru
```

На сервере уже сделано:

- добавлен Caddy;
- открыты порты `80` и `443`;
- Caddy проксирует домен на приложение.

Серверный `Caddyfile`:

```caddyfile
driver.lim-lim.ru {
    encode gzip
    reverse_proxy app:8000
}
```

На 2026-05-22 DNS в Jino для `driver.lim-lim.ru` имеет корректные A-записи:

```text
driver.lim-lim.ru -> 81.177.141.63
*.driver.lim-lim.ru -> 81.177.141.63
```

Блокером был DNSSEC родительского домена `lim-lim.ru`. DNSSEC был отключен вручную в Jino. Jino показал:

```text
DNSSEC отключён. Изменения вступят в силу в течение 6 часов.
```

Пока DS-запись `.ru` и кеши рекурсивных DNS не протухли, Let's Encrypt может продолжать падать с:

```text
DNSSEC: Bogus: validation failure
```

Не форсировать частые перевыпуски сертификата, пока DS еще видна. Сначала проверить:

```bash
dig +short @1.1.1.1 lim-lim.ru DS
dig +short @8.8.8.8 lim-lim.ru DS
dig +short @77.88.8.8 lim-lim.ru DS
dig +dnssec +multi @1.1.1.1 driver.lim-lim.ru A
```

Когда DS исчезнет и DNSSEC-валидация перестанет ломаться:

```bash
ssh codex@81.177.141.63
cd /home/codex/driver-salary
docker compose -p driver_salary restart caddy
docker compose -p driver_salary logs --tail=120 caddy
curl -I https://driver.lim-lim.ru
```

После того как `https://driver.lim-lim.ru/salary` заработает с Basic Auth, закрыть прямой публичный доступ к `8000`. Для этого на сервере поменять в `docker-compose.yml` у `app`:

```yaml
ports:
  - "8000:8000"
```

на:

```yaml
ports:
  - "127.0.0.1:8000:8000"
```

и применить:

```bash
docker compose -p driver_salary up -d
```

Ожидаемое финальное состояние:

- публичный HTTPS: `https://driver.lim-lim.ru`;
- HTTP редиректит на HTTPS;
- прямой `http://81.177.141.63:8000` закрыт;
- приложение доступно Caddy через docker network или локальный bind.

## Известные Нюансы

- Локальный `docker-compose.yml` пока dev-oriented и может не совпадать с серверным Caddy-состоянием.
- Серверный `.env` содержит реальные OData и Basic Auth credentials; его нельзя перетирать при деплое.
- На сервере включена HTTP Basic Auth. `401` без credentials - нормальный результат.
- Если в базе уже есть таблицы, но нет `alembic_version`, нельзя слепо запускать `alembic upgrade head`; сначала проверить схему. На сервере это уже случилось один раз и было исправлено через `alembic stamp 0001`, затем `alembic upgrade head`.
- Полная синхронизация может быть тяжелой: маршрутные листы фильтруются по дате уже после получения из OData. Для разовых backfill контрагентов быстрее извлекать GUID из сохраненного `DeliveryRequest.payload`, а не гонять полный sync.

## Тесты

Последний локальный результат перед деплоем:

```text
23 passed, 1 skipped
```

Покрытые области:

- форматирование чисел, денег и веса;
- выбор пороговых корзин;
- web routes/UI behavior;
- блокировка редактирования тарифов;
- синхронизация и нормализация контрагентов.
