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

### D-A-226. WP8.2: `split_topic` и `topic_split` — правка v1 перечней; задача `agent.topic_split`; порядок пачки (по #245 B)
- Класс: C (схема события после G1, красная линия 2 — по прецеденту D-A-196/D-A-121: значения перечней v1, событий Фазы 4 в проде нет)
- WP / место: WP8.2 «Разделить (фразой в чат)»; `quack/events/records.py` (`TurnIntent`, `AgentKind`), `quack/jobs/rules_p4.py`
- Контекст: строка контракта WP8.2 требует: учитель размечает намерение → сверка предлагает распределение → `topic.split`. В перечнях `TurnIntent` и `AgentKind` для этого значений нет; B не может писать ход с таким намерением (`TurnHeadRecord` отвергает весь ход).
- Решение: `TurnIntent` += `split_topic`; `AgentKind` += `topic_split`; `JOB_KIND_SPECS` += `agent.topic_split` (P2, видимая, роль `builder`), `AGENT_JOB_KINDS["topic_split"] = "agent.topic_split"`. Правило `agent.requested`: без `params.topic_id` задач нет; иначе граф-задача под замком `domain:{domain_id}` с `topic_id` в нагрузке. Версия схем остаётся 1. Порядок событий в одной пачке для темы с одним навыком: сначала `topic.split` (создаёт части), затем `skill.split` (его части ложатся в созданные темы); обратный порядок теряет часть (`_skill_split` пропускает часть, чьей темы нет) — тест это фиксирует.
- Почему: ТЗ Ф4 WP8.2, §6.3 (`topic.split`, `skill.split`), D-A-131, D-A-196; патч B из #245.
- Обратимость: полная до первых событий в проде (значения перечней можно убрать).
- Тесты: `tests/jobs/test_rules_p4.py::test_topic_split_request_is_a_graph_job_of_the_domain`, `tests/graph/test_projection_rules3.py::test_split_of_a_one_skill_topic_in_one_batch_needs_the_topics_first`; счётчик видов в `test_every_kind_of_the_spec…` 24 → 25 (+5 периодических).
- Требует подтверждения владельцем: да (класс C, действует до ответа)

### D-A-225. WP1.3 шаг 5, часть 1: что из кода Фазы 3 остаётся до части 2
- Класс: A
- WP / место: WP1.3, §7.3, §8.15; `quack/graph/worker.py`, `quack/jobs/dispatcher.py`, `quack/jobs/dispatcher_rules.py`, `quack/graph/projector.py`
- Контекст: задание шага 5 велит удалять модули, которые «никто не импортирует». Проверка `grep quack.<модуль> quack tests` показала, что проектор и диспетчер Фазы 3 ещё держат тесты зоны C: `tests/artifacts/conftest.py` (`Seeder.project` — `ProjectorWorker`), `tests/support/dispatch.py` → `tests/artifacts/test_artifacts_search_export.py` (`dispatch`: правило `session.digest_created → artifact.refresh_cheatsheet` живёт только в `dispatcher_rules.py`; в правилах Фазы 4 такого вида нет) и стенд `tests/e2e/system.py`. Перевести их — значит менять утверждения тестов артефактов C (красная линия 5), это шаг 3 C.
- Решение: остаются до части 2 (после шага 3 C): `graph/worker.py`, `jobs/dispatcher.py` (`supervise` берёт `runtime/phase4.py`), `jobs/dispatcher_rules.py`, `graph/projector.py` (`project_events` нужен `graph/overlay.py`; `run_projector_batch`/`project_in_memory` — тестам), `graph/projector_rows.py` (таблица `ROWS` нужна тестам `rules@3`), `test_dispatcher.py`. Из `dispatcher_rules.py` убрано правило `graph.curate` (вида нет). Стенд e2e по-прежнему запускает проектор, диспетчер и `JobRunner` Фазы 3 на базе Фазы 3 (тесты `tests/e2e` зелёные без перевода на процессы Фазы 4); снят только планировщик. Модули списка «не удалять» после п.1–2 имеют импортёров в `quack/`, ни один не осиротел.
- Почему: §7.3 (чужие тесты правит их владелец), красная линия 5, §8.15 п.1 (код снимается вместе с последним потребителем).
- Обратимость: полная (перечень).
- Тесты: нет новых.
- Требует подтверждения владельцем: нет

### D-A-224. WP1.3 шаг 5, часть 1: код Фазы 3 снят — планировщик, пересборка, `graph.curate`, `account.purge_deleted`, `ops/registry.py`
- Класс: A
- WP / место: WP1.3, §8.15 п.1; D-A-208, D-A-212, D-A-206; файлы ниже
- Контекст: C согласился (#215), что в шаге 5 A снимает `ops/purge_job.py`, `ops/registry.py`, `account.purge_deleted`, код Фазы 3 зоны A и ветки флага в `cli.py`. `DELETE /v1/learner` удаляет сразу (D-A-207), тело `purge_deleted` не нужно.
- Решение: удалены `quack/jobs/periodic.py`, `quack/graph/rebuild.py`, `quack/jobs/curation_p3.py`, `quack/domains/curation.py`, `quack/ops/purge_job.py`, `quack/ops/registry.py`. Из `quack/jobs/kinds.py` — `graph_curate`, `account_purge_deleted`, виды `graph.curate` и `account.purge_deleted` в `JOB_KINDS` и `KIND_LLM_ROLES`; из `HANDLER_MODULES` — две строки; из `Settings` — `purge_deleted_interval_s`; `REMOVED_JOB_KINDS` в `rules_p4.py` остаётся (это список снятых видов). Схемы `CuratorPromotion`, `CuratorMerge`, `CuratorOutput` переехали из `curation_p3.py` в конец `quack/domains/schemas.py`: их используют тесты и скрипт B (`prompt_contracts`, `test_llm_runtime`, `meta_smoke`) до снятия роли `curator` (D-A-208 п.2). Реестр событий `cli.py` берёт из `quack.runtime.event_registry` (с #237). `ProjectorContext`, `create_projector_context`, `close_projector_context` в `runtime/__init__.py` удалены (никто не вызывает).
- Почему: §8.15 п.1, WP1.3 шаг 5, согласие C в #215.
- Обратимость: полная (git).
- Тесты: `tests/jobs/test_queue_p4.py`, `test_rules_p4.py` (виды `graph.curate`/`account.purge_deleted` в `REMOVED_JOB_KINDS`), `test_ops_p4_registry.py`.
- Правки тестов (§8.15):
  | Файл | Что | Куда ушло |
  | :-- | :-- | :-- |
  | `tests/jobs/test_curation_p3_{graph,keys_and_actor,slice_and_pool,thresholds}.py` (4 файла) | удалены вместе с обработчиком `graph.curate` Фазы 3 | гигиена графа — `agents/test_hygiene.py` (`T-AG4`) |
  | `tests/fixtures/event_registry.json` | удалён | реестр Фазы 4 — `test_ops_p4_registry.py` |
  | `tests/test_ops_phase3.py` | удалены `test_event_registry_and_can_rollback_of_phase3`, `test_event_registry_has_handlers_and_rules` (библиотека `ops/registry.py`); `graph_curate` → `artifact_refresh_cheatsheet` в `test_ops_status_report` | `test_ops_p4_registry.py` (`can-rollback`), новый `test_every_catalog_type_has_a_handler_and_a_rule` (`registry_gaps` Фазы 4, T-O6) |
  | `tests/test_jobs_phase3.py` | удалены `test_periodic_scheduler_runs_once_per_bucket`, `test_purge_job_removes_learner_completely`; `graph.curate`/`account.purge_deleted` как «любой вид» очереди заменены на `artifact.refresh_cheatsheet` (утверждения те же) | периодика Фазы 4 — `jobs/test_queue_p4.py::test_periodic_keys`; удаление аккаунта — `domains/test_domains_routes.py` (T-E10) |
  | `tests/test_worker_and_ops.py` | удалены `test_rules_mismatch_skips_until_rebuild`, `test_chunked_rebuild_respects_presence` (`graph/rebuild.py`) | `graph/test_projection_runner.py::test_rules3_stale_rebuild`, новый `::test_chunked_rebuild_respects_presence` на `rebuild_learner` Фазы 4 |
  | `tests/test_dispatcher.py` | из `_expected`, `required_seq` и пропуска неизвестного события убран `graph.curate` | — |
  | `tests/test_jobs_and_llm_gateway.py` | из `test_job_kind_catalog` убран блок `graph_curate`; в `test_priority_then_age_ordering` низкий приоритет — `session.sweep_inactive` | — |
  | `tests/test_contracts.py` | из `NEO4J_WRITERS` убран `quack.graph.rebuild` | — |
  | `tests/test_ops_p4_registry.py` (зона C, правка с её согласия в #215: `cli.py`) | флаг снят: `_settings(phase4_processes=True)` → `_settings()`, удалён `test_rebuild_without_the_flag_stays_on_phase3`, подмена `rebuild_learner` Фазы 3 | — |
  | `tests/e2e/system.py` (зона C) | из стенда снят `PeriodicScheduler` вместе с `SystemClock`, `System.clock`, `advance_time` (никто не вызывает после T-E10) | — |
- Требует подтверждения владельцем: нет

### D-A-223. WP1.3 шаг 5, часть 1: флаг `phase4_processes` снят — процессы всегда на Фазе 4
- Класс: A
- WP / место: WP1.3 шаг 5; D-A-200, D-A-206, D-C-160; `quack/config.py`, `quack/cli.py`, `quack/runtime/__init__.py`
- Контекст: стенд и compose уже на dbmate и `PHASE4_PROCESSES=true` (C, #239); C согласился (#215), что `cli.py` меняет A.
- Решение: `Settings.phase4_processes` удалена. `projector`/`workers`/`worker` всегда зовут `runtime.phase4.projector_process`/`workers_process`; `ops rebuild` всегда на `graph.projection.rebuild.rebuild_learner` (`_rebuild_p4` стала `_rebuild`); ветки Фазы 3 и импорты `ProjectorWorker`, `Dispatcher`, `PeriodicScheduler`, `JobRunner`, `graph.rebuild`, `find_learners_with_rules` из `cli.py` убраны. `create_job_context` всегда передаёт `db=` шлюзу (одна схема — одна таблица учёта `ops.llm_usage`). Переменная `PHASE4_PROCESSES` в compose теперь ничего не читает (`Settings` — `extra="ignore"`): её, README и проверку `tests/test_stand_dbmate.py` снимает C.
- Почему: D-A-200 («флаг уходит с остатком WP1.3»).
- Обратимость: полная.
- Тесты: `tests/test_ops_p4_registry.py` (`ops rebuild`), `tests/graph/test_projection_runner.py` (процесс `projector`).
- Требует подтверждения владельцем: нет

### D-A-222. WP7.4: `skipped_budget` по лимиту режима пула (D-B-211, #236)
- Класс: A
- WP / место: WP7.4 (T-D7); `quack/jobs/queue_p4.py::_over_budget`
- Контекст: решение владельца D-B-211 (#234): лимит сессии зависит от остатка пула моделей — `normal` → `session_agent_budget_usd`, `tight` → `tight_session_agent_budget_usd`. Очередь снимала задачи только по обычному лимиту.
- Решение: `_over_budget` берёт `budgets_for(settings, await access_mode(db, settings)).session_usd` (`quack.llm.access`, ядро; сумма пула кэшируется на `llm_pool_cache_s`). Без пула (`llm_pool_budget_usd = 0`) — режим `normal`, поведение прежнее. `judges_only` — тот же лимит, что `tight` (`budgets_for`); запрет вызовов не-судьям держит шлюз.
- Почему: D-B-211, `Т-§13.2`, WP7.4.
- Обратимость: полная.
- Тесты: `tests/jobs/test_queue_p4.py::test_budget_follows_the_pool_mode`; T-D7 без изменений.
- Требует подтверждения владельцем: нет (решение владельца D-B-211)

### D-A-221. WP7.5: веса видов свидетельств — предложения нет, пока в документах нет правила пересчёта
- Класс: A
- WP / место: WP7.5, `calibration.weekly`; `quack/jobs/calibration_p4.py`
- Контекст: Т-§18.5 велит пересчитывать «веса видов свидетельств (§7.4) и вероятности §18.2»; Т-§7.11: «вес вида, который систематически не подтверждается, снижается в конфиге». Порога, шага снижения и способа отнести исход попытки к виду свидетельства (у попытки нет «своего» вида — состояние складывается из многих свидетельств) в документах нет.
- Решение: задача предлагает только `p_*`; в журнале `evidence_weights: null` с причиной. Правило пересчёта весов не выдумывается: его даст владелец вместе с решением по Т-§7.11 (калибровка по эталону).
- Почему: Т-§7.4, Т-§7.11, Т-§18.5; закон 8 (не выдумывать)
- Обратимость: полная; поле `evidence_weights` в предложении уже есть
- Тесты: `tests/jobs/test_calibration_p4.py`
- Требует подтверждения владельцем: да (нужно правило пересчёта весов)

### D-A-220. WP7.5: вероятность по правилу Т-§18.2, оценка Брайера и предложение `p_*`
- Класс: A
- WP / место: WP7.5; `quack/jobs/calibration_p4.py`
- Контекст: ТЗ: «предложение новых весов в журнал/лог». Как считать предложение для правил `p × R(сейчас)`, в документах нет.
- Решение: попытка Т1 — вердикт `verification = code`, исход correct/incorrect (как у метрики `next_attempt_brier`, D-B-194). Состояние — `state_at(answer_seq − 1)`; каждая пара (навык, уровень) задачи — одно наблюдение одного правила: proven+direct → `p_proven × R`, proven+transfer и implied → `p_derived × R`, unstable, failed, unknown (нет уровня или not_tested) — константы. Если нужной `R` нет — наблюдение пропускается и считается. По каждому правилу: оценка Брайера, кривая (корзины `round(p, 1)`: доля успехов и число), доля успехов и **предложение** `p = Σ исход / Σ R` (для константы `R = 1` — просто доля успехов), в [0, 1]; меньше `calibration_min_reports` наблюдений — предложения нет (`null`). Окно — ISO-неделя перед периодом задачи (`calibration:2026-46` → 2026-11-02…11-09 UTC), детерминированно при повторе; не больше `metrics_brier_max_attempts` последних попыток. Обработчик пишет `log.info("calibration_proposal", …)`; `Settings`, база, события не меняются (красная линия 2: нового типа события нет).
- Почему: Т-§18.2, Т-§18.5, ТЗ Ф4 WP7.5
- Обратимость: полная
- Тесты: `tests/jobs/test_calibration_p4.py` (два ученика, ручной счёт, ничего не записано)
- Требует подтверждения владельцем: нет

### D-A-219. WP7.5: вид `calibration.weekly` в `JOB_KINDS`, SQL по всем ученикам
- Класс: A
- WP / место: WP7.5; `quack/jobs/kinds.py`, `quack/runtime/__init__.py` (`HANDLER_MODULES`), `tests/db/test_sql_static.py`
- Контекст: ключ периода `calibration:{год-неделя}` уже планирует `periodic_p4`; вида в `kinds.JOB_KINDS` и обработчика не было (проверка полноты обработчиков при старте `workers`, T-Q7).
- Решение: `calibration.weekly` добавлен в `JOB_KINDS` и `KIND_LLM_ROLES` (ролей моделей нет) рядом с `exports.cleanup`; обработчик — в новом модуле `quack/jobs/calibration_p4.py`, он в `HANDLER_MODULES`. Выборка попыток всех учеников `_ATTEMPTS` — в `CROSS_LEARNER_ALLOWED` («еженедельная калибровка по всем ученикам»).
- Почему: Т-§13.1, Т-§18.5
- Обратимость: полная
- Тесты: `tests/db/test_sql_static.py`, `tests/test_jobs_phase3.py`
- Требует подтверждения владельцем: нет

### D-A-218. WP2.4: реестр событий образа Фазы 4 — `quack/runtime/event_registry.py`
- Класс: A
- WP / место: WP2.4 (хвост), WP1.3; `quack/runtime/event_registry.py`
- Контекст: `/app/event_registry.json`, `ops event-registry` и проверка отката (`Д-§6.3`) собираются из каталога и rules@2 Фазы 3 (`quack/ops/registry.py`, зона C, на SQLAlchemy). Шаг CI «реестр событий» (`Д-§5.2` п.6) делает C в WP9.3 — ему нужна функция Фазы 4. Как диспетчер «обслуживает» тип с отметкой в колонке «Диспетчер» §6.3, документ не перечисляет по механизмам.
- Решение: тело ops-команд (§7.3, пересечение 5) — в `quack/runtime/event_registry.py` (слой сборки: видит и проектор, и диспетчер без циклов): `event_registry()` (пары каталога Фазы 4 + `rules@3`), `write_event_registry`, `seen_pairs(db)`, `can_rollback`, `registry_gaps()`. Колонка «Диспетчер» закрыта, если тип есть в строках WP7.1, в эпизодах (`EPISODE_TYPES`, «эпизод»), в фактах структуры (`STRUCTURE_TYPES`) или в маске `*` эмбеддингов (`EMBEDDED_TYPES` по §6.3 «эмбеддинг»: `topic.proposed`, `topic.created`, `skill.created`, `material.parsed`). Регистрацию в `cli.py`/`ops` и шаг CI делает C (#232).
- Почему: `Д-§5.1`, `Д-§5.2` п.6, `Д-§6.3`, ТЗ §6.3, §7.3 п.5, WP2.4.
- Обратимость: полная; `EMBEDDED_TYPES` переезжает в строку `*` WP7.1, когда она реализуется.
- Тесты: `tests/events/test_catalog.py::test_image_registry_has_no_gaps_and_tracks_rollback` (T-EV5).
- Требует подтверждения владельцем: нет

### D-A-217. WP8.3: маршрут `GET /v1/sessions/{id}/summary` объявляет A; тело — в `quack/graph/read/summary.py`
- Класс: A
- WP / место: WP8.3; `quack/session/router.py` (объявление), `quack/graph/read/summary.py`, `tests/e2e/routes/a.py`
- Контекст: D-A-214 отдало объявление B (#228), но ТЗ §7.3, пересечение 3 прямо называет `summary` и `jobs` эндпоинтами A в `quack/session/router.py`. Тело в `quack/review/` нарушает таблицу слоёв §4.1 (T-A6): продуктовый `session` не импортирует продуктовый `review`.
- Решение: A объявляет маршрут в роутере B (только объявление); тело `session_summary` перенесено в ядро `quack/graph/read/summary.py` (зависит только от `db`, `events`, `graph.read`). Чужая или несуществующая сессия — 404. Маршрут — в `other_routes` A (T-A1, T-E3). D-A-214 заменено этим решением.
- Почему: ТЗ §7.3 п.3, §4.1 (T-A6), WP8.3.
- Обратимость: полная.
- Тесты: `tests/review/test_session_summary.py`, `tests/domains/test_edits.py` (T-ED5), T-A1, T-E3.
- Требует подтверждения владельцем: нет

### D-A-216. WP1.3, подготовка шага 5: типы задачи — в `quack/jobs/types.py`
- Класс: A
- WP / место: WP1.3; `quack/jobs/types.py`, `quack/jobs/queue.py`
- Контекст: `ClaimedJob`, `JobSpec`, `JobDeferred`, `JobFailedPermanently` объявлены в очереди Фазы 3 (`jobs/queue.py` на SQLAlchemy), а их импортируют ~20 обработчиков всех потоков (D-A-212). Файл удаляется в шаге 5.
- Решение: типы перенесены в `quack/jobs/types.py` без изменений; `jobs/queue.py` их реэкспортирует до шага 5. Импорты в зоне A уже идут из `types`. Импорты B и C переводятся в шаге 5 одной заменой строки (разрешённое пересечение 1, §7.3), либо потоками раньше.
- Почему: ТЗ WP1.3 (снятие SQLAlchemy без потери обработчиков), §7.3.
- Обратимость: полная.
- Тесты: без новых; `tests/jobs`, `test_jobs_phase3`, `test_dispatcher`, контрактные — зелёные.
- Требует подтверждения владельцем: нет

### D-A-215. WP7.5: обработчик `exports.cleanup`
- Класс: A
- WP / место: WP7.5; `quack/jobs/cleanup_p4.py`, `quack/jobs/kinds.py`
- Контекст: ТЗ §6 (таблица периодических) — «правило жизненного цикла префикса экспорта, если хранилище его не поддерживает» (`Д-§8.4`: на Contabo правило задаётся только API/CLI). Статусов `content.exports` и того, что делать со строкой, в документах нет; `export.data` ещё не написан.
- Решение: раз в сутки — строки с `expires_at < now` и `object_key` не NULL: сначала `delete_keys` объектов, затем строка `status = 'expired'`, `object_key = NULL` (строка остаётся: по ней видно, что ссылка была и истекла). Повтор безопасен; сбой между шагами оставляет строку следующему проходу. Работает и при настроенном правиле хранилища (удаление отсутствующего ключа — не ошибка).
- Почему: `Д-§8.4`, `Т-§19.6` (`export_link_ttl_hours`), WP7.5.
- Обратимость: полная.
- Тесты: `tests/graph/test_projection_runner.py::test_exports_cleanup_deletes_only_expired_archives`.
- Требует подтверждения владельцем: нет

### D-A-214. WP8.3: маршрут `GET /v1/sessions/{id}/summary` — код объявления для B
- Класс: A
- WP / место: WP8.3, §6.4; `quack/session/router.py` (зона B, черновик #222)
- Контекст: функция готова (D-A-213), маршрут лежит в зоне B и не объявлен.
- Решение: B добавляет в `quack/session/router.py` (импорты `create_graph_reader`, `SessionNotFoundError`, `SessionSummary`, `session_summary`):
  ```python
  @router.get("/sessions/{session_id}/summary", response_model=SessionSummary)
  async def get_session_summary(
      session_id: UUID, learner_id: LearnerId, resources: Resources
  ) -> SessionSummary:
      reader = create_graph_reader(
          resources.neo4j, resources.settings, learner_id=learner_id, db=resources.db
      )
      try:
          return await session_summary(resources.db, reader, learner_id, session_id)
      except SessionNotFoundError as exc:
          raise ApiError("NOT_FOUND", str(exc), status_code=404) from exc
  ```
  Ответ — `SessionSummary` (200); чужая или несуществующая сессия — `404 NOT_FOUND`. Читатель обязан получить `db=` (без него `state_at` падает, D-A-191). Нужно также: строка в `EXPECTED_ROUTES` (T-A1), пересборка `openapi.json`; сам T-E13 — в e2e B.
- Почему: ТЗ WP8.3, зона B; ресурсов хватает: `AppResources` уже даёт `db`, `neo4j`, `settings`.
- Обратимость: полная.
- Тесты: нет (маршрута нет).
- Требует подтверждения владельцем: нет

### D-A-213. WP8.3: `session_summary` — «до» и «после» сессии в кодах
- Класс: A
- WP / место: WP8.3, §2.3 строка 12, `П-4.10`, `Т-§2.6`; `quack/review/session_summary.py`
- Контекст: в ТЗ нет правила, какие навыки «затронуты сессией», откуда `seq_n` при возврате в сессию и как отличить чужую сессию.
- Решение: `session_summary(db, reader, learner_id, session_id) -> SessionSummary`. События сессии — `core.events` по `learner_id` и `session_id`. Нет `session.started` — `SessionNotFoundError` (чужая сессия выглядит так же: закон 1). `seq_n` = `seq` первого `session.started` минус 1 (возврат `resumed: true` его не сдвигает). «До» — `reader.state_at(learner, seq_n, навыки)`; «после» — `reader.slice_for_turn(learner, session, SliceFocus(skill_ids))` (текущая проекция, ждёт хвост журнала). Затронутые навыки: `skill.created` сессии; `exposures` и `tests` задач хода (`turn.committed`); `elements[].skill_id` и `root_cause.skill_id` (`observation.extracted`); `root_cause_skill_id` (`observation.diagnosed`); `tests` (и `parts[].tests`) задач, на которые в сессии были ответ, подсказка, закрытие или показ, — по `task.created` с последней поправкой `corrected_markup` проверки. Код, не текст: на навык — уровни (`status`, `basis`), `gap_type`, `consolidation_flag`, без имён, весов и времени; `before = None` — навыка до сессии не было; `changed` — коды различаются. Навык, названный событием, но которого нет в графе, пропускается. «Что сделано» — по задаче: число ответов, наибольший шаг подсказки, исход последнего вердикта, как закрыта (`None` — открыта). Слитый после N навык виден под разными id «до» и «после» (известное ограничение: псевдонимы не склеиваются).
- Почему: WP8.3, `Т-§2.6` (проигрывание, не свёртка по `seq ≤ N`), `П-4.10`.
- Обратимость: полная.
- Тесты: `tests/domains/test_edits.py::test_state_at_n_with_late_dispute` (T-ED5); `tests/review/test_session_summary.py::test_summary_before_and_after_differ_for_solved_task` (часть T-E13), `::test_a_session_of_another_learner_is_not_found`.
- Требует подтверждения владельцем: нет

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
