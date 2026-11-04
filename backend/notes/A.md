# Журнал решений потока A — Фаза 4 (с 2026-11-03)

Новые решения потока A пишутся **сюда**, сверху, в момент решения (ТЗ Ф4 §0.4.5). Общий
`backend/PHASE4_NOTES.md` — архив до 2026-11-03: новые записи туда не добавляются, это убирает
конфликты слияния. Сводка всех решений — `documentation/Фаза 4 — решения (единое).md`: добавь туда
строку о решении в той же волне.

Формат записи (как в архиве):

```
### D-A-NNN. <суть>
- Класс: A | B | C (§0.4.5)
- WP / место: …; файлы
- Контекст: чего нет в документах
- Решение: …
- Почему: Т-§ / Д-§ / ТЗ
- Обратимость: …
- Тесты: …
- Требует подтверждения владельцем: да / нет
```

Номера продолжают архив: следующий свободный номер — по `grep -h "^### D-A-" backend/PHASE4_NOTES.md backend/notes/A.md`.

<!-- записи ниже, новые сверху -->

### D-A-212. WP1.3 шаг 3: что остаётся на SQLAlchemy в зоне A после `graph/read/**`
- Класс: A
- WP / место: WP1.3, §7.3, §8.15; `quack/graph`, `quack/events`, `quack/jobs`, `quack/db`, `quack/ops`
- Контекст: шаг 5 удаляет SQLAlchemy целиком; какие модули Фазы 3 удаляются вместе с ним, а какие несут то, что живёт и в Фазе 4, — в документах нет списка.
- Решение: «удаляется в шаге 5 целиком» — `graph/worker.py`, `graph/rebuild.py`, `events/projections.py`, `events/append.py` (замена `events/log.py`), `events/reader.py` (кроме `last_seq` для ещё живых вызывающих в `session`/`artifacts`), `jobs/queue.py` (замена `queue_p4.py`; `ClaimedJob`/`JobSpec`/`JobDeferred`/`JobFailedPermanently` ещё нужны обработчикам до их перевода), `jobs/dispatcher.py`, `jobs/periodic.py`, `db/locks.py` (замена `Db.advisory_lock`), `db/postgres.py` (последним). «Нужно перенести»: `jobs/runner.py` — `JobContext`, `register_job_handler`, `JobHandler`, `JOB_HANDLERS` нужны всем обработчикам Фазы 4 (19 импортов), класс `JobRunner` и поле `session_factory` удаляются; `graph/overlay.py` — `SessionOverlay` читает журнал через `AsyncSession` (функция `load_overlay`), нужна `Db`-версия; `graph/slice.py` — `SliceDeps.session_factory` остаётся до перевода вызывающих (`session`, `artifacts/practice.py`), потом поле удаляется. В `ops/**` — `commands.py`, `registry.py`, `status.py`, `seed.py`, `restore_check.py`, `purge_job.py`, `db_roles.py`: переносит тот, кто ведёт `ops`.
- Почему: §8.15 (удаляется код, который заменяет Фаза 4), WP1.3 шаг 5.
- Обратимость: полная (только перечень).
- Тесты: нет.
- Требует подтверждения владельцем: нет

### D-A-211. WP1.3: `session.sweep_inactive` в периодических задачах Фазы 4
- Класс: A
- WP / место: WP7.5, WP1.3 (просьба B, #222/#215); `quack/jobs/periodic_p4.py`, `quack/runtime/phase4.py`
- Контекст: в таблице WP7.5 у `session.sweep_inactive` ключ «—», период `session_sweep_interval_s`; `job_key` обязан быть детерминированным (T-D9).
- Решение: ключ `sweep-inactive:{unix_time // session_sweep_interval_s}` — один ключ на период, тик `workers` каждые `scheduler_tick_s` ставит ровно одну задачу за период. `periodic_plans(now, sweep_interval_s=)` и `schedule_periodic(..., sweep_interval_s=)` принимают период (по умолчанию 60), `periodic_tick` передаёт `settings.session_sweep_interval_s`. Класс P3, `lock_key` = вид (как у соседних): два обхода не идут одновременно. Обработчик остаётся у B (`session/lifecycle.py`); планировщик Фазы 3 (`jobs/periodic.py`) живёт до шага 5.
- Почему: T-D9, WP7.5, `JOB_KIND_SPECS` (`session.sweep_inactive` — `periodic=True`).
- Обратимость: полная.
- Тесты: `tests/jobs/test_queue_p4.py::test_periodic_keys` (пять задач за первый тик; ключи минут).
- Требует подтверждения владельцем: нет

### D-A-210. WP1.3: `Neo4jGraphReader` без `session_factory`, ожидание журнала через `Db`
- Класс: A
- WP / место: WP1.3 шаг 3, WP6.4, WP8.3; `quack/graph/read/neo4j_reader.py`, `neo4j_extras.py`, `reader.py`, `quack/graph/slice.py`
- Контекст: D-A-191 перевёл `state_at` на `db=`, но читатель ещё принимал `session_factory` (ожидание хвоста журнала в `slice_for_turn`, ветка `state_at` Фазы 3).
- Решение: у `Neo4jGraphReader` убран параметр `session_factory`; сборка — `Neo4jGraphReader(neo4j, settings, learner_id=, db=)` / `create_graph_reader(..., db=)`; публичные методы `GraphReader` не менялись. С `db` `slice_for_turn` без оверлея ждёт хвост журнала (`core.learners.seq`), как раньше ждал с `session_factory`; без `db` цель ожидания 0. `state_at` читает только журнал Фазы 4 (без `db` — `RuntimeError`), ветка `project_in_memory` по `StoredEvent` Фазы 3 снята. `SliceDeps` получил `db` (только по имени); `session_factory` в нём `None`-able и уйдёт, когда вызывающие в `session`/`artifacts` перейдут на `db` (D-A-212).
- Почему: WP1.3 шаг 3, D-A-191, T-DB3.
- Обратимость: полная.
- Тесты: `tests/graph/test_projection_runner.py::test_slice_waits_for_the_journal_of_phase_4` (новый); `tests/graph/test_read_neo4j_extras.py::test_state_at_replays_events_up_to_n_not_a_fold_by_seq` — подмена теперь на `LogEvent` Фазы 4.
- Требует подтверждения владельцем: нет

### Правки тестов (D-A-210…212)
- `tests/graph/test_read_neo4j_extras.py`: события подмены `state_at` — `LogEvent` вместо `StoredEvent` Фазы 3 (проверка та же).
- `tests/jobs/test_queue_p4.py::test_periodic_keys`: счётчики 4/0/3 → 5/0/1/4 и ключи минут обхода (добавлена пятая периодическая задача; проверка периодов остальных четырёх не ослаблена).

### D-A-206. WP1.3: `db=` шлюза в `workers` и удаление трасс при удалении аккаунта
- Класс: A
- WP / место: WP1.3, WP25 п.3, WP10.6 (issue #210); `quack/runtime/__init__.py`, `quack/deletion/account.py`
- Контекст: B (D-B-197) просит передать `db=` в `LLMGateway`; при удалении аккаунта — `tracer.delete_learner`. Когда включать `db=` при двух схемах до WP1.3 — в документах нет.
- Решение: `create_job_context` передаёт `db=` только при `phase4_processes` (одна база — одна таблица учёта: `ops.llm_usage` у Фазы 4, `ops.llm_ledger` у Фазы 3). `delete_account(..., tracer=, pseudonym=)` после строк, объектов и подграфа зовёт `tracer.delete_learner(pseudonym)`; `False` — ничего (трассы истекают, D-B-202). Псевдоним считает вызывающий (`learner_pseudonym(settings.langsmith_pseudonym_ns, id)`) при переключении `DELETE /v1/learner`.
- Почему: D-A-103 (две схемы), WP10.4, WP25 п.3, `Т-§19.5`.
- Обратимость: полная; флаг уходит с остатком WP1.3.
- Тесты: `tests/graph/test_projection_runner.py::test_delete_account` (трасса удаляется по псевдониму).
- Требует подтверждения владельцем: нет
