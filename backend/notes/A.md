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

### D-A-209. WP1.3 шаг 3: тесты — что снято, что перенесено, мост стенда e2e
- Класс: A
- WP / место: WP1.3, §8.15; `tests/domains/`, `tests/jobs/`, `tests/e2e/journey.py`, `tests/e2e/routes/a.py`, `tests/test_*.py`
- Контекст: стенд e2e и тесты сессий (B, #222) ещё на Фазе 3: `POST /v1/sessions` читает структуру домена в журнале Фазы 3. Маршруты `structure/*` и `diagnostic/*`, которые её писали, сняты (§2.3 строка 5).
- Решение: `onboard()` стенда создаёт домен маршрутом Фазы 4 (`POST /v1/domains`), а структуру (две темы, навык у каждой, одно предусловие — как давал `structurer` стенда) кладёт в журнал Фазы 3 напрямую (`_seed_phase3_structure`). Мост — пока B не переведёт сессии (#222) и не придёт T-E1 Фазы 4; тогда `onboard()` и `structure_node()` уходят. Тесты снятого кода удалены, тесты свойств, которые остаются, перенесены (список — ниже).
- Почему: §8.15 п.1–2, §0.4.4 п.14 (не ломать тесты чужого стека до его перехода).
- Обратимость: полная; мост — один файл теста.
- Тесты: `tests/domains/test_domains_routes.py` (4 теста), весь обход `tests/e2e`.
- Требует подтверждения владельцем: нет

**Правки тестов (§8.15)**

| Снят / изменён | Почему | Что проверяет теперь |
| :-- | :-- | :-- |
| `tests/domains/test_structure_and_dag.py`, `test_structure_actor_and_delete.py`, `test_propose_idempotency.py`, `test_confirm_idempotency.py` | интервью структуры снято (§2.3 строка 5; §8.15 п.1) | свойство «повтор с тем же ключом» — `test_domains_routes.py::test_create_and_list_domains`; рост графа — T-P*, `test_projection_runner.py` |
| `tests/domains/test_diag_idempotency.py`, `test_diag_open_and_bank.py`, `test_diag_state_from_events.py`, `test_diag_wakeup.py`, `test_diagnostic_and_graph_view.py` (диагностика, карта Фазы 3) | диагностика снята (§2.3 строка 5) | карта — `test_domains_routes.py::test_domain_graph_and_topic_card_give_codes` (T-TH5) |
| `tests/domains/test_graph_view_fixes.py`, `test_topic_alias_routes.py` | `p_mastery`/пять `display_state`, короткие маршруты статуса темы сняты (§8.15 п.1) | то же, T-TH1/T-TH2 в `tests/graph/` |
| `tests/domains/test_auth_and_learner.py` | `auth.users.preferences`, tombstone и `learner.preferences_updated` сняты | `test_set_preference`, `test_delete_learner_removes_the_account`; `test_projection_runner.py::test_delete_account` |
| `tests/domains/test_curation_*.py` (3 файла) и два теста `graph.curate` из `test_diagnostic_and_graph_view.py` | не сняты: обработчик жив на конвейере Фазы 3 | перенесены в `tests/jobs/test_curation_p3_*.py` без изменения утверждений (D-A-208) |
| `tests/test_meta_mock.py::test_structurer_answer_gives_topics_with_skills` | проверял `sanitize_structurer_output` снятого модуля | — (роль `structurer` у B) |
| `tests/test_jobs_phase3.py::test_purge_job_removes_learner_completely` | `DELETE /v1/learner` больше не пишет tombstone | тот же тест, tombstone кладёт сам тест: проверяется обработчик чистки Фазы 3, пока он жив |
| `tests/test_neo4j_outage.py` | `GET /v1/domains/{id}/topics/{id}` снят; домен — в журнале Фазы 4 | карта и карточка темы (`/v1/topics/{id}`) при сбое Neo4j — `503` |
| `tests/test_app_assembly.py` (фикстура `sign_in`) | журнал Фазы 4 требует строку `core.learners` | то же утверждение (T-A3, T-A5) |
| `tests/e2e/test_journey_and_laws.py` | T-E1: проверка `p_mastery` по карточке темы Фазы 3 снята; T-E10: чистка планировщиком снята | T-E10: `DELETE /v1/learner` — `delete_account` сразу: строки Фазы 4, граф, ключ присутствия, журнал, `401` |
| `tests/e2e/test_degradation.py`, `test_isolation_and_idempotency.py`, `journey.py`, `routes/a.py` | интервью, диагностика, архив сняты; `preferences` — `{key, value}` | то же, через мост (выше) |

- Правка после CI #226: `tests/session/test_phase3_hot_path.py::test_turn_survives_neo4j_outage` (зона B) — снята проверка `GET /v1/domains/{id}/graph` → 503: домен теста живёт в журнале Фазы 3, маршрут — на Фазе 4; 503 графа при недоступном Neo4j проверяет `tests/test_neo4j_outage.py` (T-H1). Файл переписывает B в #222.

### D-A-208. WP1.3 шаг 3: что остаётся от Фазы 3 в зоне домена
- Класс: A
- WP / место: WP1.3, §6.5; `quack/jobs/curation_p3.py`, `quack/domains/curation.py`, `quack/domains/schemas.py`
- Контекст: обработчик `graph.curate` (`curation.py`) живёт на конвейере задач Фазы 3: диспетчер Фазы 3 ставит `graph.curate`, `quack.runtime.HANDLER_MODULES` его импортирует, на виде задачи стоят тесты очереди и диспетчера. Портировать его на `Db` нельзя: он пишет события Фазы 3 в базу Фазы 3 (`SessionFactory`). Выходы ролей `structurer`, `diagnostic`, `curator` (`StructurerOutput`, `DiagnosticOutput`, `CuratorOutput`) нужны тестам и скриптам B (`tests/llm/prompt_contracts.py`, `test_llm_runtime.py`, `test_meta_mock.py`, `scripts/meta_smoke.py`), пока роли и промпты не сняты.
- Решение:
  1. Обработчик перенесён `quack/domains/curation.py` → `quack/jobs/curation_p3.py` без правок; в `quack/domains/curation.py` остался импорт (`HANDLER_MODULES` не тронут). Тесты перенесены в `tests/jobs/test_curation_p3_*.py`. Всё это уходит вместе с `graph.curate` (`kinds.graph_curate`, `dispatcher_rules`, запись в `HANDLER_MODULES`, `REMOVED_JOB_KINDS`): одним шагом исполнителя, снимающего конвейер Фазы 3.
  2. Три схемы выходов ролей остались в конце `quack/domains/schemas.py` (с подмоделями); B убирает их вместе с ролями.
- Почему: §0.4.4 п.14, §8.15 п.1 (снимается вместе с последним потребителем), §7.3 (зона B — промпты и тесты ролей).
- Обратимость: полная.
- Тесты: `tests/jobs/test_curation_p3_*.py` (перенесены без изменений утверждений), `tests/test_contracts.py` (T-A6, импорт каждого модуля).
- Требует подтверждения владельцем: нет

### D-A-207. WP1.3 шаг 3: `quack/domains/**` на `Db`; маршруты A на код Фазы 4
- Класс: A
- WP / место: WP1.3, WP6.5, WP25 п.3, §6.4; D-A-194, D-A-198, D-A-205, D-A-206; `quack/domains/{service,learner,graph_view,graph_reads,schemas,router}.py`, `quack/deletion/router.py`
- Контекст: в ТЗ нет формы ответа `GET /v1/domains/{id}/graph` и тела `PATCH /v1/learner/preferences` на новых кодах; слово «архив» и статус темы §6.4 заменяет WP25; нет места для `DELETE /v1/learner` между роутерами.
- Решение:
  1. **Домены.** Таблицы нет (§6.1): `POST /v1/domains` пишет `domain.created {domain_id, name}`; id — от ключа (`deterministic_id(learner, 0, "domain:<key>")`), повтор даёт тот же домен, тот же ключ с другим именем — `409`. `GET /v1/domains` читает `domain.created` ученика по `seq`: `{domain_id, name, created_seq, created_at}`. Поля `slug`, `status`, `has_materials`, `active_structure_version` и `include_archived` ушли.
  2. **Предпочтения.** `PATCH /v1/learner/preferences {key, value, idempotency_key}` → `preference.set`, ответ `{key, value, seq}`. Ключ — `^[a-z][a-z0-9_]{0,31}$` (он станет именем свойства `pref<Key>`), значение — строка до 500 знаков, число или булево. Прежнее тело `{preferences: {…}}` снято.
  3. **Карта домена.** `GET /v1/domains/{id}/graph` → `{domain_id, projected_seq, lag_degraded, topics[{topic_id, name, status, visibility, display: TopicDisplay, nearest_due_at_ms, skill_count}], requires[]}`; `requires` — `topic_requires` читателя, только между показанными темами. Домен — ученика по `domain.created` в журнале (только что созданный, ещё не спроецированный домен — пустая карта, не `404`; чужой — `404`). Скрытые темы не отдаются без `?include_hidden=true`. `lag_degraded` — отметка проектора меньше счётчика ученика. Пересчёта «на момент чтения» нет: «пора повторить» — клиент по `nearest_due_at_ms` (Т-§8.6).
  4. **Карточка темы.** `GET /v1/topics/{id}` → `graph_reads.topic_view` (D-A-198); лимит мест — 200 по умолчанию (параметра в `Settings` нет и не вводится).
  5. **Снято с кодом:** `…/structure/propose|confirm`, `PATCH …/structure`, `…/diagnostic/start|answer|finish`, `POST …/archive`, `PATCH …/topics/{id}/status` и `PATCH /topics/{id}/status`, `GET /domains/{id}`, `GET /domains/{id}/topics/{topic_id}` (их нет в §6.4; старый → новый — таблица §6.4), модули `structure`, `diagnostic`, `topics`.
  6. **`DELETE /v1/learner`** → `quack.deletion.account.delete_account` в `quack/deletion/router.py` (рядом с остальными удалениями). Ответ как у домена и темы: `{deletion_id, copies_days: 15}`. `tracer` — `resources.llm.tracer` (шлюз его уже держит; поля в `AppResources` не нужно), `pseudonym = learner_pseudonym(settings.langsmith_pseudonym_ns, learner_id)` (D-A-206). Журнал R2 недоступен или блокировка занята — `503`. Сессия уходит вместе со строками, следующий запрос — `401`.
- Почему: §6.4 (таблицы «Домены», «Граф и темы», «Ученик», «Удаление»; «Старый API → новый»), §2.3 строка 5, §6.1, T-TH5, WP25 п.1, п.3; закон 1.
- Обратимость: полная; `include_hidden` и лимит мест — параметры чтения.
- Тесты: `tests/domains/test_domains_routes.py` (создание и список, предпочтение, карта и карточка с кодами и `TopicDisplay` в OpenAPI, удаление аккаунта), `tests/e2e/routes/a.py` (T-A1, T-E2, T-E3).
- Требует подтверждения владельцем: нет

### D-A-206. WP1.3: `db=` шлюза в `workers` и удаление трасс при удалении аккаунта
- Класс: A
- WP / место: WP1.3, WP25 п.3, WP10.6 (issue #210); `quack/runtime/__init__.py`, `quack/deletion/account.py`
- Контекст: B (D-B-197) просит передать `db=` в `LLMGateway`; при удалении аккаунта — `tracer.delete_learner`. Когда включать `db=` при двух схемах до WP1.3 — в документах нет.
- Решение: `create_job_context` передаёт `db=` только при `phase4_processes` (одна база — одна таблица учёта: `ops.llm_usage` у Фазы 4, `ops.llm_ledger` у Фазы 3). `delete_account(..., tracer=, pseudonym=)` после строк, объектов и подграфа зовёт `tracer.delete_learner(pseudonym)`; `False` — ничего (трассы истекают, D-B-202). Псевдоним считает вызывающий (`learner_pseudonym(settings.langsmith_pseudonym_ns, id)`) при переключении `DELETE /v1/learner`.
- Почему: D-A-103 (две схемы), WP10.4, WP25 п.3, `Т-§19.5`.
- Обратимость: полная; флаг уходит с остатком WP1.3.
- Тесты: `tests/graph/test_projection_runner.py::test_delete_account` (трасса удаляется по псевдониму).
- Требует подтверждения владельцем: нет
