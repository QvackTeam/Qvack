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
