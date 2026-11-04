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
### D-C-167. `ops extraction-eval`: команда оценки извлечения (S15, WP16.7)
- Класс: C (регистрация функции B, ТЗ §7.3 п.5; формат отчёта и метрики — D-B-209)
- WP / место: WP16.7, S15; `quack/cli.py` (`_extraction_eval`)
- Контекст: B дал `evaluate_extraction`, `load_eval_set`, `compare_reports`, но не имя и аргументы команды.
- Решение: `ops extraction-eval --set EVAL.json --learner UUID [--prompt extractor@N] [--runs N] [--out REPORT.json] [--against OLD_REPORT.json]`. `--learner` обязателен: чей реестр расходов оплачивает вызовы модели (учебный ученик оператора). Отчёт — один JSON на stdout (и в `--out`). `--against` — ворота Т-§18.4: рядом с отчётом печатается `comparison`, код выхода 1, если `regression` не `False` (падение точности/каппы либо «нечего сравнить» — не «пройдено», закон 8). Код 2: нет `META_API_KEY`, набор или прежний отчёт не читается/не `EvalSet`, `ValueError` функции (число прогонов, нет промпта). Шлюз собирается как у `replay-session`.
- Почему: STATUS WP16.7 «регистрация команды оценки извлечения (C, S15)»; docstring `extraction_eval.py` («`compare_reports` — ворота Т-§18.4»); по образцу `replay-session` (D-C-151).
- Обратимость: да (одна команда)
- Тесты: `tests/test_ops_p4_registry.py` (`test_extraction_eval_*`, `test_parser_of_extraction_eval`)
- Требует подтверждения владельцем: нет

### D-C-166. Шаг CI «реестр событий» — шаг `fast`, а не команда `ops registry-gaps` (WP9.3, Д-§5.2 п.6)
- Класс: C
- WP / место: WP9.3, WP2.4; `.github/workflows/ci.yml` (job `fast`)
- Контекст: issue #232 п.2 допускает шаг `uv run python -c …` либо команду `ops registry-gaps` с тем же телом.
- Решение: шаг `Event registry (реестр событий)` в `fast` после `pyright`, тело — строка из issue; команды `ops registry-gaps` нет. Шаг не требует сервисов; `registry_gaps()` чистая, поэтому не нужны `Settings` и роль процесса, которые подняла бы команда `ops`. Любой пробел — код 1, список пробелов в логе шага.
- Почему: Д-§5.2 п.6 говорит о шаге CI; меньше поверхности, чем команда, которой пользуется только CI.
- Обратимость: да
- Тесты: `tests/test_ci_layers.py::test_fast_job_checks_the_event_registry_gaps`
- Требует подтверждения владельцем: нет

### D-C-165. `ops event-registry`, `can-rollback`, `rebuild` на Фазе 4 (WP2.4, WP3.5; issue #232)
- Класс: C (регистрация функций A, ТЗ §7.3 п.5)
- WP / место: WP2.4, WP3.5; `quack/cli.py`
- Контекст: issue допускает переход «при `phase4_processes` или сразу». Реестр образа пишется при сборке (`Dockerfile`, без БД и без флага), поэтому от флага зависеть не может.
- Решение: (1) `event-registry` и `can-rollback` — всегда из `quack.runtime.event_registry` (каталог Фазы 4, `rules@3`); `seen_pairs(db)` берёт `Db` из `open_db`. Образ с `phase4_processes = off` всё равно содержит каталог Фазы 4, откат на образ с `rules@2` честно даёт `rules_changed`. (2) `rebuild` — при `phase4_processes`: `rebuild_learner(db, neo4j, settings, id, redis=redis)` из `graph.projection.rebuild`; `--stale-rules` — `stale_learners(neo4j, RULES_VERSION)`; `--all` — `SELECT learner_id FROM core.learners ORDER BY learner_id`; без флага остаётся код Фазы 3 (`core.learner_seq`, `graph.rebuild`) до шага 2 WP1.3 (#223). Каждый ученик пробуется; код 1, если исход хоть одного не `rebuilt` (`busy`, `active_session`, `failed`); код 2 — цель не указана. `ops/registry.py` не удалён (шаг 5 WP1.3).
- Почему: issue #232; Д-§5.1, Д-§6.3, D-A-189, D-A-218.
- Обратимость: да
- Тесты: `tests/test_ops_p4_registry.py`; `tests/test_ops_phase3.py` (библиотека Фазы 3 без CLI)
- Требует подтверждения владельцем: нет
