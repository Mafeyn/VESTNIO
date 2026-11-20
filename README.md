# VESTNIO — Telegram Mini App с новостями

Агрегатор реальных новостей из трёх категорий: **игры**, **мир** и **технологии**. Работает внутри Telegram на Android, iOS и Desktop, а также в обычном браузере.

- хронологическая лента с картинками, заголовками, временем, источником и коротким описанием;
- полнотекстовый поиск по заголовкам и описаниям (с префиксами: «nintend» находит «Nintendo»);
- фильтры по категориям и источникам, сортировка, бесконечная прокрутка;
- закладки без регистрации (хранятся на устройстве);
- экран статьи со ссылкой на оригинал (`Telegram.WebApp.openLink`);
- тёмная и светлая темы следуют теме Telegram.

Здесь нет AI-функций, рекомендаций, комментариев, монетизации и аккаунтов.

---

## Структура

```
backend/                 Python 3.12 · FastAPI · SQLAlchemy · Alembic · PostgreSQL
  sources.yaml           реестр источников (проверенные реальные ленты)
  vestnio/
    source_manager.py    Source Manager: загрузка реестра, статусы, backoff
    fetcher.py           Feed Fetcher: таймауты, ретраи, robots.txt, ETag/Last-Modified
    adapters/            Parser Adapters: rss (RSS/Atom/RDF), api (Hacker News, Guardian), html (CSS-селекторы)
    normalizer.py        News Normalizer: UTC, очистка HTML, язык оригинала
    dedup.py             Duplicate Filter: GUID → канонический URL → «отпечаток» заголовка
    db/                  модели и все SQL-запросы
    ingestion.py         конвейер для одного источника (сбои изолированы)
    worker.py            отдельный воркер APScheduler
    api/                 REST API
    telegram_auth.py     проверка подписи initData
    bot.py               бот aiogram
  migrations/            Alembic
  tests/                 pytest (парсеры, дедупликация, ингестия, API, initData, бот)
webapp/                  React 19 · TypeScript · Vite · Tailwind CSS 4 · TanStack Query
  Caddyfile              HTTPS + статика + прокси /api
docker-compose.yml       db, migrate, api, worker, bot, web
```

## Источники

Список лежит в `backend/sources.yaml`. У каждого источника своя категория, URL, тип получения и интервал опроса (по умолчанию 15 минут). Статус и время последнего успешного обновления хранятся в БД и видны в API (`/api/v1/sources`) и на экране «Источники».

Включены русскоязычные источники:

| Категория | Источники |
|---|---|
| Мир | BBC Русская служба, DW на русском, Euronews, Интерфакс, РБК, ТАСС |
| Технологии | 3DNews, iXBT.com, Хабр, CNews, 4PDA |
| Игры | StopGame, DTF, Shazoo, GoHa.Ru, GameMAG |

В реестре также лежат проверенные англоязычные источники (`enabled: false`): BBC, Al Jazeera, NPR, The Guardian (RSS и официальный API), DW, Ars Technica, The Verge, TechCrunch, Hacker News (официальный API), Techmeme (HTML-парсер), Polygon, Eurogamer, Rock Paper Shotgun, PC Gamer, GameSpot. Выключенные источники не опрашиваются и не показываются в ленте.

Проверены и отклонены: lenta.ru (запрещено в robots.txt), Игромания (лента отвечает капчей), kanobu.ru и vgtimes.ru (битые ленты).

Аватарка бота: `python scripts/make_avatar.py`, затем `python scripts/set_bot_avatar.py`.

### Картинки

Если в RSS нет картинки, воркер берёт обложку из `og:image` или `twitter:image` на странице статьи. Это те же метаданные, из которых строятся превью ссылок. Делается один запрос на статью, только для новых статей, не больше 25 за опрос, с соблюдением robots.txt; текст статьи не читается. Отключить для источника можно опцией `options: {enrich_images: false}`. Для уже собранных статей есть команда `python -m vestnio.cli backfill-images`. Часть сайтов (ТАСС, CNews, 4PDA) отказывает автоматическим клиентам, и эта защита не обходится. Их статьи без картинок показываются текстовыми карточками.

### Telegram-каналы

Публичные каналы подключаются как источники `method: telegram` и читаются через веб-превью, которое Telegram сам отдаёт: `https://t.me/s/<канал>`. Подключено 28 каналов: 13 в «Мире», 10 в «Технологиях», 5 в «Играх» (полный список в `sources.yaml`).

- Каждый пост превращается в статью: первая строка становится заголовком, остальной текст — описанием. Также берутся фото или превью видео и ссылка `t.me/<канал>/<id>`, которая внутри Telegram открывается через `openTelegramLink`.
- Рекламные посты (`erid`, `#реклама`) и подписи каналов («👉 Подписаться», «❤️ PDA») отбрасываются. Посты без текста (только фото) пропускаются.
- Посты, которые повторяются в нескольких каналах (например, у сетки «Топор»), убирает резервное правило дедупликации по заголовку.
- Приватные каналы и ссылки-приглашения (`t.me/+…`) превью не имеют, поэтому подключить их нельзя. Список подписок аккаунта ботам недоступен: каналы добавляются в реестр вручную.

Добавить канал:

```yaml
- {id: tg-mychannel, name: Мой канал, url: "https://t.me/s/mychannel", homepage: "https://t.me/mychannel", category: world, method: telegram}
```

Проверить все источники вживую (без БД):

```powershell
cd backend; .\.venv\Scripts\python -m vestnio.cli check
```

**Правила работы с контентом.** Используются только публичные ленты и официальные API. Сохраняются заголовок, короткий анонс, ссылка на картинку и ссылка на оригинал; полный текст статей никогда не загружается. `robots.txt` соблюдается: например, `text.npr.org` и `lite.cnn.com` его запрещают, поэтому не используются. У Techmeme разрешена главная страница, но запрещены `/*.jpg`, поэтому картинки оттуда не берутся. Поле `show_excerpt: false` скрывает анонс у источника, если издатель его не разрешает.

**Дедупликация** работает в три шага:
1. уникальность `(source_id, GUID)`;
2. уникальность хэша канонического URL (без `utm_*`, `fbclid`, `www.`, `#…`, с отсортированными параметрами) по всем источникам;
3. резервное правило: тот же нормализованный заголовок длиной от 5 слов в окне 72 часов.

---

## Локальная разработка (Windows, без Docker)

Нужны Python 3.12 и Node.js 20+.

> Держите проект в папке с коротким путём (например, `D:\VESTNIO`): на Windows длинные пути ломают `node_modules` и встроенный PostgreSQL.

### 1. Бэкенд

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\pip install -r requirements-dev.txt
.\.venv\Scripts\python scripts\dev_db.py          # локальный PostgreSQL 16 в .pgdata, пишет URL в .env
.\.venv\Scripts\alembic upgrade head
.\.venv\Scripts\python -m vestnio.cli ingest        # один проход сбора новостей
```

Запуск в трёх терминалах:

```powershell
.\.venv\Scripts\python -m uvicorn vestnio.api.app:app --port 8000   # API, документация: /api/docs
.\.venv\Scripts\python -m vestnio.worker                          # воркер по расписанию
.\.venv\Scripts\python -m vestnio.bot                             # бот (нужны токен и HTTPS-URL, см. ниже)
```

Если Docker запущен, вместо `dev_db.py` можно использовать `docker compose up -d db` и прописать `VESTNIO_DATABASE_URL` в `backend/.env` (пример: `backend/.env.example`).

### 2. Mini App

```powershell
cd webapp
npm install
npm run dev        # http://localhost:5173, /api проксируется на :8000
```

В обычном браузере приложение работает полностью; функции Telegram (BackButton, тема, хаптика) просто отключаются.

### 3. Тесты

```powershell
cd backend; .\.venv\Scripts\python -m pytest -q
cd webapp; npm run typecheck
```

Тесты, которым нужна БД, используют `VESTNIO_TEST_DATABASE_URL` (его создаёт `dev_db.py`) и прогоняют настоящие миграции.

---

## Telegram: бот и HTTPS

### Создание бота

1. В [@BotFather](https://t.me/BotFather): `/newbot` → получите токен.
2. Впишите токен в `.env` (`VESTNIO_BOT_TOKEN=…`). Не отправляйте его в чаты и не коммитьте. Токен нужен только сервисам `bot` и `api` и никогда не попадает в браузер.
3. **Main Mini App**: `/mybots` → ваш бот → *Bot Settings* → *Configure Mini App* → *Enable Mini App* → укажите HTTPS-URL приложения. После этого в профиле бота появится кнопка «Открыть», а ссылки вида `https://t.me/<bot>?startapp=article_123` будут открывать нужную статью.
4. Кнопку меню, команды `/start` и `/help` и описание бот настраивает сам при запуске.

### HTTPS для разработки

Telegram открывает Mini App только по HTTPS. Для разработки поднимите туннель к Vite, например через [cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/):

```powershell
cloudflared tunnel --url http://localhost:5173
```

Полученный адрес `https://….trycloudflare.com/` пропишите в `backend/.env` как `VESTNIO_WEBAPP_URL` и в BotFather (п. 3), затем запустите бота. Vite проксирует `/api` на локальный бэкенд, поэтому достаточно одного туннеля.

### Безопасность

- `initDataUnsafe` используется только для выбора языка интерфейса.
- Всё, что требует личности пользователя (сейчас это админ-эндпоинт `POST /api/v1/admin/sources/{id}/refresh`), принимает заголовок `Authorization: tma <initData>`. Сервер проверяет HMAC-подпись токеном бота и срок `auth_date`, а id пользователя должен быть в `VESTNIO_ADMIN_IDS`.
- Публичные эндпоинты только читают данные и не требуют авторизации.

---

## Бесплатный хостинг: Vercel + Neon + GitHub Actions

Работает круглосуточно, компьютер можно выключать, платить не нужно (условия бесплатных тарифов проверены в ноябре 2026).

| Что | Где | Бесплатно |
|---|---|---|
| Mini App + REST API | **Vercel** (Hobby, некоммерческие проекты) | постоянный адрес `https://<проект>.vercel.app` |
| PostgreSQL | **Neon** (Free) | 1 ГБ, 100 CU-часов в месяц |
| Сбор новостей каждые 15 минут | **GitHub Actions** (`.github/workflows/ingest.yml`) | бесплатно для публичных репозиториев |
| Бот | webhook `POST /api/telegram/webhook` внутри API | процесс держать не нужно |

1. **Neon**: создайте проект на [neon.com](https://neon.com) и скопируйте *connection string* (прямое подключение, не `-pooler`).
2. **GitHub**: отправьте репозиторий в GitHub (публичный). В *Settings → Secrets and variables → Actions* добавьте секрет `DATABASE_URL` со строкой подключения Neon. Запустите *Actions → Collect news → Run workflow*: он применит миграции и соберёт первые новости.
3. **Vercel**: в [vercel.com](https://vercel.com) войдите через GitHub, *Add New → Project*, импортируйте репозиторий. В *Environment Variables* задайте:
   - `DATABASE_URL` — строка Neon;
   - `VESTNIO_BOT_TOKEN` — токен бота;
   - `VESTNIO_WEBHOOK_SECRET` — любая длинная случайная строка;
   - `VESTNIO_WEBAPP_URL` — `https://<проект>.vercel.app/`.

   Нажмите *Deploy*. Сборка Mini App и упаковка API настроены в `vercel.json` и `pyproject.toml`.
4. **Бот**: впишите тот же `VESTNIO_WEBHOOK_SECRET` в `backend/.env` и выполните:
   ```powershell
   cd backend; .\.venv\Scripts\python scripts\setup_telegram.py https://<проект>.vercel.app
   ```
   Скрипт назначит webhook, кнопку меню и команды. В @BotFather (*Configure Mini App*) укажите тот же адрес.

После этого локальный бот (`python -m vestnio.bot`) не нужен. Он откажется запускаться, пока назначен webhook, чтобы случайно его не сбросить. Вернуть локальный режим можно командой `python scripts/setup_telegram.py --polling`.

**Ограничения бесплатного варианта:**
- GitHub может запускать расписание с опозданием на несколько минут.
- GitHub отключает расписание в публичном репозитории, если в нём 60 дней не было коммитов. Включить его снова можно кнопкой *Enable workflow* на вкладке Actions.
- Поиск и лента работают как обычно. Первый запрос после простоя может быть на 1–2 секунды медленнее, пока просыпается база Neon.

## Продакшен: Docker Compose

Нужны сервер с Docker и домен, A-запись которого указывает на этот сервер (открыты порты 80 и 443).

```powershell
copy .env.example .env      # заполните VESTNIO_DOMAIN, POSTGRES_PASSWORD, VESTNIO_BOT_TOKEN
docker compose up -d --build
docker compose logs -f worker
```

| Сервис | Назначение |
|---|---|
| `db` | PostgreSQL 16 с томом `pgdata` |
| `migrate` | `alembic upgrade head`, запускается один раз перед остальными |
| `api` | FastAPI (uvicorn) |
| `worker` | сбор новостей по расписанию (APScheduler) |
| `bot` | бот aiogram (long polling), `VESTNIO_WEBAPP_URL = https://<VESTNIO_DOMAIN>/` |
| `web` | Caddy: автоматический сертификат Let's Encrypt, статика Mini App, `/api/*` → `api`, заголовки безопасности (CSP разрешает встраивание только в `web.telegram.org`) |

После запуска укажите `https://<VESTNIO_DOMAIN>/` в BotFather (Configure Mini App) и откройте бота.

**Проверка после деплоя:**

```powershell
curl https://<VESTNIO_DOMAIN>/api/v1/health      # "status": "ok", растущее число статей
curl https://<VESTNIO_DOMAIN>/api/v1/sources     # статусы источников
```

`status: degraded` означает, что ни одного успешного сбора не было больше 3 часов или нет ни одного здорового источника. Подробности смотрите в `docker compose logs worker`.

---

## REST API

Единый формат ответа: `{"data": …, "meta": {…}}`, ошибки возвращаются как `{"error": {"code", "message", "details"}}`. Время всегда в UTC (`2026-11-20T08:15:00Z`). Документация OpenAPI доступна по адресу `/api/docs`.

| Эндпоинт | Параметры |
|---|---|
| `GET /api/v1/articles` | `category` (`gaming`/`world`/`technology`), `source` (id; можно повторять или перечислить через запятую), `q` (полнотекстовый поиск), `sort` (`newest`/`oldest`/`relevance`), `since`, `until` (ISO 8601 с зоной), `has_image`, `cursor`, `limit` (1–50, по умолчанию 20) |
| `GET /api/v1/articles/{id}` | статья целиком, включая `canonical_url` и `fetched_at` |
| `GET /api/v1/categories` | число статей всего и за сутки, число источников, время последней публикации |
| `GET /api/v1/sources` | `category`; статус, время последнего успешного обновления, последняя ошибка, число статей |
| `GET /api/v1/health` | состояние БД и свежесть сбора; 503, если БД недоступна |

Пагинация курсорная: `meta.next_cursor` передаётся в следующий запрос. Курсор привязан к сортировке. Коды ошибок: `422 validation_error`, `400 invalid_cursor`, `404 not_found`, `503 database_unavailable`.

## Добавление источника

1. Добавьте запись в `backend/sources.yaml` (формат описан в начале файла).
2. Проверьте её: `python -m vestnio.cli check <id>`.
3. Воркер перечитывает реестр каждые 5 минут, перезапуск не нужен.

Для HTML-источника сначала убедитесь, что `robots.txt` сайта разрешает доступ (сборщик всё равно проверяет это перед каждым запросом), и опишите CSS-селекторы в `options`.
