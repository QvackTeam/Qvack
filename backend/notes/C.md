# Журнал решений потока C — Фаза 4 (с 2026-11-03)

Новые решения потока C пишутся **сюда**, сверху, в момент решения (ТЗ Ф4 §0.4.5). Общий
`backend/PHASE4_NOTES.md` — архив до 2026-11-03: новые записи туда не добавляются, это убирает
конфликты слияния. Сводка всех решений — `documentation/Фаза 4 — решения (единое).md`: добавь туда
строку о решении в той же волне.

Формат записи (как в архиве):

```
### D-C-NNN. <суть>
- Класс: A | B | C (§0.4.5)
- WP / место: …; файлы
- Контекст: чего нет в документах
- Решение: …
- Почему: Т-§ / Д-§ / ТЗ
- Обратимость: …
- Тесты: …
- Требует подтверждения владельцем: да / нет
```

Номера продолжают архив: следующий свободный номер — по `grep -h "^### D-C-" backend/PHASE4_NOTES.md backend/notes/C.md`.

<!-- записи ниже, новые сверху -->

### D-C-160. WP1.3 шаг 2 / WP9: стенд на dbmate - `ops migrate` = `dbmate up`, `PHASE4_PROCESSES=true`, чистый старт
- Класс: C (инфраструктура зоны C; схема и миграции A не менялись)
- WP / место: WP1.3 шаг 2, WP9.1, WP9.2, WP9.4, issue #223 (план #215); `quack/ops/commands.py::migrate`, `quack/cli.py`, `backend/Dockerfile`, `compose.yaml`, `deploy/deploy.sh`, `deploy/README.md`
- Контекст: ТЗ WP1.1 говорит «`ops migrate` запускает `dbmate up` с ролью `quack_migrator`»; D-A-103 держит две схемы до WP1.3; в образе `quack-backend` бинарника dbmate не было (STATUS называл WP9.2 влитым с `dbmate`); как быть со стендом, где уже лежит схема Alembic, и с ролью миграций, документы не говорят.
- Решение:
  1. `ops migrate` запускает бинарник `dbmate --migrations-dir <backend>/db/migrations --no-dump-schema up`; DSN идёт в `DATABASE_URL` (не в аргументы), к нему добавляется `sslmode=disable`, если режима нет (lib/pq по умолчанию требует TLS, сеть `backend` без TLS). Каталог миграций - `/app/db/migrations` в образе.
  2. Образ: бинарник dbmate `v2.36.0` с проверкой sha256 (те же версия и сумма, что в `ci.yml` и `ct.sh`; тест сверяет три места), `COPY db ./db`; `alembic.ini` и `migrations/` из образа убраны.
  3. compose: `PHASE4_PROCESSES: "true"` у `api`, `projector`, `workers` (общий `x-db-env`); сервис `migrate` идёт первым, остальные ждут `service_completed_successfully` (так и было).
  4. `deploy.sh`: список миграций образа читается из `/app/db/migrations`; у образа Фазы 3 каталога нет, список пуст, любой файл нового образа считается новым - миграция запустится. Порядок шагов не менялся: роли, дамп, `migrate`, затем `projector`, `compute`+`workers`, `api`.
  5. Чистый старт (ТЗ Ф4 §2.3 строка 1): если в базе есть `public.alembic_version`, `ops migrate` завершается кодом 1 с пояснением и ничего не меняет, выкатка останавливается до запуска сервисов, старая версия остаётся. Базу стенда с данными Фаз 1-3 пересоздают вручную (том `postgres-data`).
  6. Роли `quack_app`/`quack_migrator` не переводятся: DSN сервисов остаются под `quack` (deploy/README, «что пока не готово»). Перевод - когда A снимет SQLAlchemy (шаг 5).
  7. Не закрыто этим шагом: `ops status` (проверка выкатки, `Д-§6.1` шаг 8), `can-rollback`, `restore-check`, `seed-learners`, `alerts` читают таблицы Фазы 3 (`core.learner_seq`, `ops.dlq`, `ops.llm_ledger`); на схеме Фазы 4 `ops status` вернёт код 2. Их перенос на `Db` - шаг 3 C (`quack/ops/*`, #215).
- Почему: ТЗ Ф4 WP1.1, WP9, §2.3; D-A-103, D-A-200; Д-§5.1, Д-§6.1, Д-§7.
- Обратимость: код и compose - откатом коммита; пересозданная база стенда - нет.
- Тесты: `tests/test_stand_dbmate.py` (compose, образ, порядок в `deploy.sh`, `ops migrate`), `test_compose_contract`, `test_deploy_env`, `test_ci_layers`.
- Требует подтверждения владельцем: нет (пересоздание базы стенда - действие владельца стенда)
