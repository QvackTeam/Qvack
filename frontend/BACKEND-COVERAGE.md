# Фронт и бэк: что подключено

Состояние на 2026-11-04 (ветка `front-for-vercel`, поддержка Фазы 3 и готовность к Фазе 4).

## Как запустить

Фронт работает в одном из двух режимов. Режим выбирается при сборке переменной окружения в `frontend/.env.local`:

- `NEXT_PUBLIC_QUACK_API=1` — данные идут с бэка;
- без неё — моки из `lib/mock/`, как раньше. Это удобно для работы над дизайном.

Шаблон лежит в `.env.example`. После изменения `.env.local` dev-сервер надо перезапустить.

Бэк берётся из `main` (Фаза 3 влита) либо из ветки `phase-4` (Фаза 4). Удобнее всего поднять его через compose из корня репозитория.

1. Рядом с `compose.yaml` создай `.env`. Имена переменных — в `backend/.env.example`, обязательны `POSTGRES_PASSWORD`, `NEO4J_PASSWORD` и `JWT_SECRET`.
2. **Без живого ключа** — подменный сервер Meta (`meta-mock`). Он отвечает по схемам и отдаёт предмет из трёх тем с навыками, так что работает весь путь: структура, граф, практика, сессия. Добавь в `.env`:

   ```bash
   META_API_KEY=stand
   META_API_BASE_URL=http://meta-mock:8080
   META_MOCK_LATENCY=zero
   ```

   `META_MOCK_LATENCY=zero` убирает задержку ответа. По умолчанию задержка как у живой модели, у учителя это около 14 с.
3. Запуск:

   ```bash
   docker compose --profile loadtest up -d --build
   ```

   `compose.override.yaml` открывает API на `127.0.0.1:8000`. Миграции, проектор и воркеры поднимаются сами. Воркеры обязательны: они строят граф, шпаргалки и итоги сессий.

   **С живым ключом** профиль `loadtest` не нужен: `META_API_KEY` — настоящий ключ, `META_API_BASE_URL` не задавай.
4. Фронт:

   ```bash
   npm run dev
   ```

Браузер обращается только к фронту. Next.js проксирует `/api/*` на `QUACK_API_URL` (по умолчанию `http://localhost:8000`, см. `next.config.ts`), поэтому CORS на бэке не нужен.

Без `META_API_KEY` бэк работает в упрощённом режиме. Предложение тем даёт по одной теме на каждый пункт фокуса, без навыков, поэтому практика по ним не открывается. Учитель отвечает заглушкой.

## Как устроено во фронте

- `lib/api/client.ts` — запросы, токен (`localStorage`, ключ `quack.token`), сессионная cookie (`credentials: "include"`), ошибки, SSE через `fetch`. `post`, `patch`, `del` и `sse` типизированы по контракту. Предусмотрены хелперы Фазы 4: `fetchMe` (`/v1/me` с фоллбэком на `/v1/auth/me`), `sendMagicLink`, `verifyMagicLink`, `logoutApi`.
- `lib/api/schema.d.ts` — типы, сгенерированные из `lib/api/openapi.json`.
- `lib/api/adapters.ts` — переводит ответы бэка в типы интерфейса (`lib/mock/types.ts`) и адаптирует ответы графа в `GraphModel` (`graphModelFromApi`) для нового графа `LayeredGraph` с индикаторами.
- `lib/api/data.tsx` — `DataProvider`: проверка входа, профиль и настройки, список предметов, графы, активная сессия, история сессий, живые обновления (`appliedSeq`). В `DataContext` экспортируются сырые графы и история сессий для сборки `GraphModel`.
- `lib/graph/use-graph-model.ts` — хук графа: на моках возвращает моковую модель, в `API_MODE` собирает живую `GraphModel` через `graphModelFromApi`.
- `components/quack/graph/layered-graph.tsx` — новый слоёный DAG-граф с индикаторами («Новые», «Актуальные», «Дедлайн», «Слабые места», «Повторение»), историей посещений и связью с карточками «Сегодня».
- `components/quack/live/use-start-session.ts` — запуск сессии по теме: карточка темы, страница главы, «Сегодня».
- `components/quack/live/*` — экраны на данных бэка. Маршруты выбирают живой экран или моковый по `API_MODE`.

## Что подключено

| Экран | Эндпоинты |
|---|---|
| Вход, регистрация, выход | `POST /v1/auth/login`, `POST /v1/auth/register`, `GET /v1/auth/me` (Фаза 3); `POST /auth/link`, `POST /auth/link/verify`, `GET /v1/me`, `POST /auth/logout` (Фаза 4) |
| Левая панель, вкладка «Предметы» в настройках | `GET /v1/domains` |
| Граф предмета (LayeredGraph + индикаторы) | `GET /v1/domains/{id}/graph` |
| Новый предмет | `POST /v1/domains`, `POST …/structure/propose` |
| Темы предмета: пропустить, добавить, подтвердить, архив | `POST …/structure/confirm`, `PATCH …/structure`, `PATCH …/topics/{id}/status`, `POST …/archive` |
| Диагностика | `POST …/diagnostic/start`, `…/answer`, `…/finish` |
| Страница темы: навыки, заблуждения, заметки, шпаргалка | `GET /v1/topics/{id}`, `GET /v1/artifacts?topic_id=`, `GET /v1/topics/{id}/cheatsheet`, `POST …/cheatsheet/refresh` (тело `{domain_id}`) |
| Сессия: история, ответ учителя потоком, «учитель думает» (`status`), задачи, присутствие, конец | `POST /v1/sessions`, `GET /v1/sessions/{id}`, `POST …/actions` с фоллбэком на `POST …/turns` (SSE), `POST …/heartbeat`, `POST …/finish`, `GET /v1/sessions/active` |
| Итог сессии | данные из `finish` |
| Практика | `POST /v1/sessions` (practice), `POST …/tasks/next`, `…/hint`, `…/submit` |
| Заметки и шпаргалки, поиск, выгрузка | `GET /v1/artifacts`, `GET /v1/artifacts/search`, `GET /v1/domains/{id}/export` |
| Заметка | `POST /v1/artifacts/notes`, `PATCH …/{id}`, `DELETE …/{id}` |
| Удаление аккаунта | `DELETE /v1/learner` (без тела) |
| Настройки «Общие» и «Язык»: имя, обращение, курс, язык ответов | `PATCH /v1/learner/preferences`, чтение из `GET /v1/auth/me` / `GET /v1/me` |
| Панель сессий справа: все сессии предмета, новые сверху | `GET /v1/sessions` |
| Карточка темы на графе: «Изучать», «Повторять»; поле ввода на странице темы | `POST /v1/sessions` с `topic_id` и `mode` |
| Страница главы: «Изучать всё», «Практика», «Повторение», «Вперемешку» | `POST /v1/sessions`, экран практики |
| «Сегодня» под графом: до трёх тем, у которых срок повторения (`nearest_review_at` / `nearest_due_at_ms`) до конца дня; клик открывает повторение, наведение подсвечивает узел на графе | `GET /v1/domains/{id}/graph`, `POST /v1/sessions` (review) |
| Плашка «граф догоняет» при `lag_degraded`; граф перечитывается каждые 5 с, пока бэк не догонит | `GET /v1/domains/{id}/graph` |
| Живые обновления: список предметов, графы на экране, история сессий, страница темы | `GET /v1/learner/stream` (SSE `projection_advanced`, данные — обычными GET) |

## Готовность к Фазе 4 (Phase 4 Readiness)

1. **Ходы и действия сессии (`actions` vs `turns`)**:
   `SessionLive` настроен на двойной протокол: отправляет `POST /v1/sessions/{id}/actions` с телом `{ kind: "message", text, ... }`. В случае 404/405 автоматически откатывается на Phase 3 `POST /v1/sessions/{id}/turns`. Поддерживаются SSE фреймы обоих стандартов (`token` с `text` или `delta`, `action_recorded` и `turn_started`, `verdict` и `task_evaluated`, `turn_committed` и `turn_completed`).
2. **Сессионные cookie и аутентификация**:
   Все запросы `api` и `sse` выполняются с `credentials: "include"`, поэтому cookie `quack_session` передаётся прозрачно. Хелпер `fetchMe` пробует `GET /v1/me` и откатывается на `GET /v1/auth/me`. Добавлены функции для входа по magic link (`/auth/link`, `/auth/link/verify`) и логаута (`/auth/logout`).
3. **Граф и схема связей**:
   Адаптер `graphModelFromApi` умеет читать как структуру Phase 3 (`prereqs: [{from_topic_id, to_topic_id}]`, `display_state`), так и структуру Phase 4 (`requires: [{topic_id, requires_topic_id}]`, `display`, `nearest_due_at_ms`, `hubs`).
