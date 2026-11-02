# Фаза 4: заметки, аудит и журнал решений

Файл заметок `ТЗ Фаза 4 (единое).md` (§0.5). Общие разделы ведёт поток C; в разделах потоков
пишет только сам поток. Ссылки: `Т-§`, `Д-§`, `П-`, `Ф3-§`, `P3N` — как в §0.1 ТЗ.

## Сводка для владельца

Состояние на 2026-11-02 (WP0, поток C).

- «Чистый старт» (WP0 п.2) подтверждён владельцем 2026-11-02 (раздел «Вход»).
- `D-C-101` и `D-C-106` подтверждены владельцем 2026-11-02 (передано потоком B).
- **Нужны значения:** `terms_version`, `auth_success_redirect_url` (`D-C-105`).
- `main` `9ef6e3e` зелёный (раздел «Вход»).
- \[ПРОВЕРИТЬ\] WP0 п.3а закрыт: фильтр внутри векторного индекса работает на Neo4j
  2026.10.1 Community (раздел «Вход»).

## Вход

Проверка §1.3 (поток C, 2026-11-02).

- `main` — `9ef6e3e` (#70, ТЗ Фазы 4 с поправками) поверх `958d42a` (#69). Фаза 3 (#66) и
  решения владельца (#67) влиты.
- Интеграционная ветка `phase-4` уже есть в `origin` и совпадает с `main` `9ef6e3e`; там же
  `phase-4-a`, `phase-4-b`, `phase-4-c` на том же коммите (рабочие ветки — `D-C-101`).
- Инфраструктура тестов — по `backend/README.md`: `quack-test-pg` (Postgres 16, :55432),
  `quack-test-neo4j` (:57687, **Neo4j 2026.06.0** — README и compose называют 2026.10,
  `D-A-017`; локальный контейнер старше, на итог прогона не влияет), `quack-test-redis`
  (Redis 7, :56379; compose — 8.2). Docker 29.8.1, uv 0.12.23.
- **Чистый старт (WP0 п.2): подтверждён владельцем в чате 2026-11-02** — событий настоящих учеников нет ни в одном окружении; локальные стенды `quack-*` и `quack-test-*` тестовые. Дословно (передано потоком B): «у нас пока никаких данных учеников нет. остальные решения если за мной какие есть - сверься с тз и тз доком, дай решение».

Прогон на `main` `9ef6e3e`:

| Где | Команда | Итог |
| :-- | :-- | :-- |
| `backend/` | `uv run ruff check .` | All checks passed |
| `backend/` | `uv run ruff format --check .` | 260 files already formatted |
| `backend/` | `uv run pyright` | 0 errors |
| `backend/` | `QUACK_TEST_REQUIRE_INFRA=1 uv run pytest -q` | 774 passed, 351 warnings, 631 s |
| `compute/` | `uv run ruff check .` / `ruff format --check .` | passed / 7 files already formatted |
| `compute/` | `uv run pyright --pythonplatform Linux` | 0 errors |
| `compute/` | `docker run --rm -v "<compute>:/src:ro" ghcr.io/astral-sh/uv:python3.12-bookworm-slim sh -c "cp -r /src /app && cd /app && rm -rf .venv && uv sync -q --frozen && uv run pytest -q"` | 5 passed (три прогона подряд). Первый прогон, параллельно с `pytest` backend, — 2 failed (`test_equation_roots_and_matrix` и ещё один), см. «Вопросы к команде» Q-C-1 |

### \[ПРОВЕРИТЬ\] WP0 п.3

| Пункт | Поток | Скрипт | Итог |
| :-- | :-: | :-- | :-- |
| а) `SEARCH … VECTOR INDEX … WHERE learnerId = $id AND searchable = true` (`Т-§3.4.6`, `Т-§1.10`) | C | `scripts/checks/vector_search_filter.py` | **Работает** на `neo4j:2026.10-community` (агент `Neo4j/2026.10.1`, community): индекс с `WITH [c.learnerId, c.searchable]`, запрос `CYPHER 25 MATCH … SEARCH c IN (VECTOR INDEX … FOR $q WHERE … LIMIT 30) SCORE AS score` вернул ровно узлы ученика с `searchable = true`. Запасной путь WP20.4 не нужен |
| б) составной range-индекс `(learnerId, retDueAtMs)` на `Skill` (`Т-§3.4.8`) | A | `scripts/checks/skill_due_index.py` | **Работает** на `neo4j:2026.10-community` (2026.10.1): `CREATE RANGE INDEX … FOR (s:Skill) ON (s.learnerId, s.retDueAtMs)` → `ONLINE`; запрос WP17.1 (`learnerId = $id AND retDueAtMs > 0 AND retDueAtMs <= $now`) идёт через `NodeIndexSeek` по составному индексу. Запасной путь (одиночные индексы) не нужен |
| в) параметры `py-fsrs` (`Т-§8.3`) | A | `scripts/checks/fsrs_params.py` | `py-fsrs` **6.3.2** (закрепляется в WP4): `Scheduler(parameters, desired_retention, learning_steps, relearning_steps, maximum_interval, enable_fuzzing)` — все четыре имени `Т-§8.3` совпадают; по умолчанию 21 вес (FSRS-6); при `enable_fuzzing=False`, пустых шагах и явном UTC-времени два прогона дают одинаковые сроки; первый `Good` сразу даёт `Review`. `uv run --with fsrs==6.3.2 python scripts/checks/fsrs_params.py` → код 0 |
| г) `antlr4-python3-runtime` для SymPy, `parse_latex(…, strict=True)` (`Т-§6.5`) | B | `scripts/checks/wp0_3g_antlr.py` | SymPy 1.14.0 требует **4.11.x**; `strict` есть; с 4.11.1 строгий разбор работает. В `compute` рантайма пока нет — закрепляется в WP11.5. Подробно — ниже, «Поток B: подробности п.3г, п.3д» |
| д) Meta Model API: `sam-3.1`, `muse-voice-transcribe-1.0` (`Т-§1.3`) | B | — (только документация: вызов запрещён п.3д, скрипту нечего проверять) | `sam-3.1` — `POST /v1/responses`, ответ спецтокенами; голос — `POST /v1/asr/transcribe`, `multipart/form-data`, WAV. Подробно — ниже, «Поток B: подробности п.3г, п.3д» |
| е) `READ`-сессия Neo4j отклоняет запись (`Д-§14.2`, `T-A9b`) | C (перенос) | `tests/test_neo4j_read_session.py` | **Подтверждено**: 3 passed на Neo4j 2026.06.0 (полный прогон) и на 2026.10.1 (`QUACK_TEST_NEO4J_URI=bolt://127.0.0.1:57688`) |

#### Поток B: подробности п.3г, п.3д

**г) ANTLR для SymPy (`Т-§6.5`).** SymPy закреплена 1.14.0 (`compute/uv.lock`). Она требует
`antlr4-python3-runtime` **4.11.x**: проверка `version('antlr4-python3-runtime').startswith('4.11')` в
`sympy/parsing/latex/_parse_latex_antlr.py`. `parse_latex` принимает `backend` и `strict`. С 4.11.1
строгий разбор `\frac{x^{2}}{2} + \sin(2x)` даёт `x**2/2 + sin(2*x)`, незакрытая дробь отклоняется.
Сейчас рантайма в `compute` нет — разбор LaTeX падает `ImportError`. Закрепить
`antlr4-python3-runtime==4.11.1` в `compute/pyproject.toml` — в WP11.5 (B, §4.6).
Скрипт: `backend/scripts/checks/wp0_3g_antlr.py`.
`uv run --project compute --with "antlr4-python3-runtime==4.11.*" python backend/scripts/checks/wp0_3g_antlr.py`
→ код 0; без `--with` → код 1.

**д) `sam-3.1` и `muse-voice-transcribe-1.0` (`Т-§1.3`).** Только по документации Meta, без вызовов
(`dev.meta.ai/docs/models`, `/docs/media-segmentation`, `/docs/sam/segmenting`,
`/docs/sam/reading-segmentation`, `/docs/speech-to-text`, `/docs/api-reference/voice/transcribe`;
прочитано 2 нояб. 2026). Живая проверка — DoD п.6a.

- `sam-3.1` — `POST /v1/responses`, `model: "sam-3.1"`. `input` — одно сообщение `role: user`:
  `input_text` (короткое имя предмета **или** токены рамки/точки, не вместе; рамка:
  `<0f>1<|box;x1=..;y1=..;x2=..;y2=..;w=..;h=..|>`) и `input_image` (`image_url`: публичный URL или
  `data:image/png;base64,…`). `stream` необязателен. `metadata` (строки): `mask_encoding`
  (`lossless` по умолчанию / `one_bit`), `include_confidence` (`"true"`/`"false"`).
  Ответ — текст спецтокенов в `output_text`: строка на кадр `<Nf>`, записи «id, рамка, маска»:
  `<|box;x1;y1;x2;y2;w;h[;c]|>` в абсолютных пикселях, `<|mask;x=0;y=0[;c];data=H,W,<~|!>base85|>`.
  Пусто — совпадений нет. До 16 объектов на запрос. Лимиты размера и форматов изображения документация
  не называет.
- `muse-voice-transcribe-1.0` (срез `Т-§22.8` — отрезками, файловый путь) — `POST /v1/asr/transcribe`,
  **не** через `/responses`. `multipart/form-data`: часть `request` (JSON: `model`,
  `audioEncoding: "WAV"`, `mode`: `PUSH_TO_TALK` по умолчанию / `ENDPOINTING` / `DIARIZATION`,
  необязательные `languageBias`, `keywords`) и часть `audio` (WAV: моно, 16-бит PCM, 16 или 24 кГц).
  До 10 мин, тело до 32 МБ, `?sessionId=` — необязательный id корреляции. Ответ JSON
  `TranscribeResponse`: `sessionId`, `transcript`, `audioDurationMs`, `turns[]` {`turnId`, `startMs`,
  `endMs`, `transcript`, `speaker`}; в `PUSH_TO_TALK` `turns` пусты. Ошибки: 400, 406, 413, 429
  (лимит одновременных или часовых сессий), 500.

Следствия: адаптеры WP10.1 — `sam-3.1` через тот же `/responses` с разбором спецтокенов, голос — отдельный
HTTP-адаптер шлюза (допуск, учёт, трасса, размыкатель — общие). Для C (WP21.6): звук из браузера нужно
привести к WAV моно 16-бит 16/24 кГц; время отрезка для привязки к строкам (`Т-§15.6`) даёт клиент —
в `PUSH_TO_TALK` внутренних отметок нет.

## Статус

| Пакет | Поток | Состояние | Тесты |
| :-- | :-: | :-- | :-- |
| WP0 (зона C) | C | частично: ждёт п.2 (владелец) | — (скрипт п.3а) |
| WP0 (зона A) | A | выполнен: аудит B1–B7, B21; п.3б, п.3в | — (скрипты п.3б, п.3в) |
| WP2 (A) | A | черновик каталога S3 (G0) в `phase-4-a-wp2`: 65 типов §6.3, общие модели B в ядре (Q-A-1 (а)), ключи, пометки обработчиков и правил; заморозка — G1 после Q-A-2, Q-A-3 | `tests/events`: 73 passed |
| WP6.4 (A), S4 | A | сигнатуры, модели ответов и заглушка `FixedGraphReader` в `phase-4-a-s4-s6` (D-A-111); реализация — G2 | `tests/graph/test_read_stub.py`: 9 passed |
| WP7.1 (A), S6 | A | виды задач и таблица правил по событию в `phase-4-a-s4-s6` (D-A-110); строки с данными сверх события и диспетчер — G2 | `tests/jobs/test_rules_p4.py`: 25 passed |
| WP1.1–1.2 (A) | A | выполнен в `phase-4-a-wp1` (шов S2): базовая миграция dbmate, `Db`, `append_events`, параметры §6.7 потока A. WP1.4 (`.squawk.toml`, S16) — к G2; WP1.3 — к G3/G4 | `tests/db`: 19 passed |
| WP0 (зона B) | B | выполнен: аудит, п.3г, п.3д, п.5 | — (скрипт п.3г) |
| Этап I G1 (B: S7, S8, S11, S13) | B | контракты в `phase-4-b`, тесты контрактов зелёные | см. «Красные прогоны» |
| WP10.2–10.3 (B) | B | частично: разбор потока хода и вход шага цикла с инструментами — зелёные (`T-AI2`–`T-AI4`); адаптер `ResponsesClient.stream_structured` и цикл `run_tool_loop` (параллельные инструменты с таймаутом, повтор оборванного с удвоенным лимитом) — зелёные (`T-AI5`, `T-AI6` без строки `ops.llm_usage` — она в WP10.4); встраивание в шлюз (допуск, семафоры, учёт) — с WP13 | 19 passed |
| WP11 (B) | B | частично: `check()` мгновенные типы (WP11.2) — зелёный `T-CH1`, включая «в той же транзакции» (`record_answer`, WP11.4 — ветка `phase-4-b-wp12` поверх S2/S3 A); быстрые — с каркасом compute (S10); медленные — WP11.6 | 11 + 4 passed |
| WP12.1–12.3 (B) | B | частично: `validate_markup` (WP12.3) — зелёный `T-TK2`; `content.tasks` + `task.created` (WP12.1, `quack/practice/task_store.py`) — зелёный `T-TK1` в ветке `phase-4-b-wp12` поверх S2/S3 A (#78, #80); PR — после их слияния | 14 + 4 passed |
| WP10.5 промпты (B) | B | частично: 16 промптов ролей B в `quack/prompts/` (слой 2 по схемам кода), `manifest.json`, `PROMPT_CONTRACTS.md`; `T-M5` на все роли; слой 1 у всех 16 (8 — черновики стенда, D-B-132); стенд на Meta API — §«Промпты», «Стенд B на Meta API»; роли C (`recognizer`, `canvas_diagnoser`, `material_parser`, `artifact_writer`) — слой 2 пишет C | 73 passed (`tests/llm`); весь набор без инфраструктуры — 578 passed, 306 skipped |

## Аудит

Пункты §3, которые подтверждает поток C (`main` `9ef6e3e`, 2026-11-02).

| # | Итог |
| :-- | :-- |
| B11 | Подтверждено: `compute/quack_compute/` — `GET /health/live`, `POST /v1/check/math`; таймаут на `multiprocessing` (`forkserver`), `pebble` нет. Часть WP24 — C, `math/**` — B |
| B14 | Подтверждено: пароль и JWT в `quack/domains/auth.py`, `quack/api/auth.py`, ссылки в `quack/cli.py`, `quack/config.py`. Пакета `quack/auth/` нет |
| B15 | Подтверждено: `quack/artifacts/` — `notes.py`, `cheatsheets.py`, `practice.py`, `search.py`, `store.py`, `router.py` |
| B16 | Подтверждено: `quack/storage/` нет, `aioboto3` в `pyproject.toml` нет |
| B17 | Подтверждено: `quack/materials/`, `quack/embeddings/` нет; `modal` нет |
| B18 | Подтверждено: `quack/canvas/` нет; `msgpack` нет |
| B22 | Подтверждено с уточнением: сеть `backend` и лимиты `Д-§4.1`, `stop_grace_period`, списки `environment:` есть; **сеть `egress` уже есть** (`compose.yaml`: у `api` и `workers`, объявлена в `networks:`) — пункт «сеть `egress`» WP9.1 уже выполнен, проверить значения при WP9. Caddy нет. CI — три job (`backend`, `compute`, `images`), job выкатки нет |
| B23 | Подтверждено: `ops` — `migrate`, `verify-schema`, `rebuild`, `replay-dlq`, `purge-deleted`, `status`, `event-registry`, `can-rollback`, `seed-learners`, `openapi`. Нет `db-roles`, `backup now`, `restore-check`, `replay-deletions`, `orphan-objects`, `alerts`, `resume` |
| B24 | Подтверждено: `AppResources` — `settings`, `engine`, `session_factory`, `neo4j`, `redis`, `llm`, `compute`; новых ресурсов и CORS-списка нет |
| B27 | Подтверждено: `loadtest/meta_mock.py` строит ответ по схеме (`minimal_instance`), без стриминга и инструментов. Часть WP26.2 — C, `meta_smoke.py` — B |

Пункты §3, которые подтверждает поток A (`phase-4` `a087529`, 2026-11-02).

| # | Итог |
| :-- | :-- |
| B1 | Подтверждено: Alembic `migrations/versions/0001_initial_schema.py`, `0002_phase3.py`; таблицы `auth.users`, `core.learner_seq`, `core.events`, `core.sessions`, `core.artifacts`, `core.domains`, `core.task_bank`, `core.llm_outbox`, `ops.jobs`, `ops.dlq`, `ops.llm_ledger`, `ops.deletion_tombstones`, `ops.projector_offsets`, `ops.event_types_seen`, `ops.dispatcher_offsets`, `ops.turn_manifests` |
| B2 | Подтверждено, пересчёт: `sqlalchemy`/`asyncpg` импортируют **41** модуль `quack/` и **61** файл `tests/`; `loadtest/` — 0 |
| B3 | Подтверждено: `quack/events/catalog.py` — 36 типов |
| B4 | Подтверждено: `quack/graph/` — `phase_a.py`, `folds.py`, `topic_display.py`; в коде `p_mastery`, `PART_OF`, `PREREQ_OF`, `DEPENDS_ON`, `appliedSeq`, `rules@2` |
| B5 | Подтверждено: `quack/graph/evidence_weights.py`, `evidence_validation.py` есть |
| B6 | Подтверждено: `quack/jobs/dispatcher.py`, `dispatcher_rules.py` есть |
| B7 | Подтверждено: `quack/jobs/queue.py` — числовой `priority`, `attempt`/`max_attempts`, `run_after`, статусы `queued`/`running`/`done`/`failed`/`cancelled`, `ops.dlq`; нет `visible`, `cancel_requested`, `skipped_budget`, `max_jobs_per_learner` |
| B21 | Подтверждено: `quack/domains/learner.py` пишет `ops.deletion_tombstones` (`pending_purge`); зачистка — `quack/ops/purge_job.py` |

Пункты §3, которые подтверждает поток B (`main` `9ef6e3e`, 2026-11-02).

| # | Итог | Что видно в коде |
| :-- | :-- | :-- |
| B8 | подтверждено | `quack/llm/responses_client.py`: `complete_structured` без `stream` и без `tools`; семафоры, давление, размыкатель, повторы, `teacher_fallback` — в `gateway.py`, `pressure.py`; учёт — `ops.llm_ledger` в токенах |
| B9 | подтверждено | `quack/session/schemas.py`: `TeacherOutput` плоский (`reply_text`, `pedagogical_move`); ход в `turns.py` без LangGraph; гард спойлера по полному тексту (`spoiler_guard.py`) |
| B10 | подтверждено | `quack/practice/evaluation.py` — каскад Фазы 3; `selection.py` — подбор из `core.task_bank` |
| B11 | подтверждено | `compute/quack_compute/app.py`: только `POST /v1/check/math` и `/health/live`; каталога `math/` нет |
| B12 | подтверждено | `quack/session/extraction.py`, `workers.py`: извлечение по ходу, `ExtractorOutputV2` с перечнями `extractor@2` |
| B13 | подтверждено | `quack/domains/structure.py` (интервью структуры), `diagnostic.py` (диагностика), `curation.py` (задача `graph.curate`, роль `curator@1`) — есть. Удаляются по §2.3 строка 5; сверка и гигиена — WP16.3 (B); сами модули `domains` — зона A |
| B20 | подтверждено | `quack/practice/generation.py` (`build_generated_task`), роль `task_gen@1`; `task_checker`/`task_arbiter` нет |
| B25 | подтверждено | `quack/llm/labels.py`: метки `S`/`T`/`K`/`M`, таблица в `ops.turn_manifests` |
| B27 | подтверждено | `backend/scripts/meta_smoke.py` — роли Фазы 3, без стриминга и инструментов |

## Промпты

Поток B, WP0 п.5.

Пакета доктрины владельца (слой 1, §7.6) для ролей Фазы 4 в репозитории нет. В `quack/prompts/` лежат
только промпты Фазы 3: `teacher@1`, `extractor@1`, `extractor@2`, `evaluator@1`, `task_gen@1`,
`curator@1`, `artifacts@1`, `structurer@1`, `diagnostic@1`.

Не хватает доктрины (слой 1) для всех ролей §6.6 / §7.6:

- B вызывает: `teacher@2` (и `teacher_fallback`), `extractor@3`, `verdict_free@1`, `verdict_proof@1`,
  `second_opinion@1`, `task_generator@1`, `task_checker@1`, `task_arbiter@1`, `solution_space@1`,
  `analyst@1` (`analyst_deep`), `builder@1`, `misconception_describer@1`, `today_planner@1`,
  `domain_classifier@1`, `viz_builder@1`, `release_judge@1`;
- C вызывает (слой 2 пишет C, §7.3 п.2): `recognizer@1`, `canvas_diagnoser@1`, `material_parser@1`,
  `artifact_writer@1`;
- не текстовые (`segmenter`, `voice`, `illustrator`) промпта-доктрины не требуют.

Решение владельца (2 нояб.): промпты поток B не пишет; владелец передаёт заготовки, B их только
дорабатывает под схемы (слой 2). Схемы выходов ролей (код, шов S8) B пишет сам. Требования к
промптам — реестр промптов Фазы 4 владельца (в репозитории его нет: `documentation/**` правит только владелец, §2.1). Его открытые
вопросы, которые закрывает B: п.4 (раскладка полей `extractor@3`, `Element`, `planUpdate`, дедлайн,
`params`) — закрыты кодом (D-B-107…D-B-110, имя `new_misconception` взято из реестра); п.6 (выходы
`task_checker`, `task_arbiter`, `today_planner`, `viz_builder`, `release_judge`) — D-B-113; п.3
(видит ли `second_opinion` первичный вердикт) — D-B-114.

Тексты Фазы 3 (`teacher@1`, `extractor@2`, `evaluator@1`, `task_gen@1`) — доктрина под старые
схемы; переносить их в новые роли без решения владельца нельзя (§0.4.4 п.13). Запрос владельцу —
в сигнале потока B. Перечни `intent` и `approach` выхода хода (WP13.3) тоже ждут доктрину:
до неё стоят временные значения (D-B-104).

**Заготовки владельца (2 нояб.).** Владелец передал пакет заготовок стенда (Baseten,
`muse-spark-open-1026`; папка `drive-download-20261102T020137Z-1-001`, вне репозитория) и реестр
промптов `documentation/SYSTEM_PROMPTS_PHASE4_REGISTRY.md` (версия 2 нояб., 792 строки, с таблицей
исправлений §0). Результатам стенда поток B не доверяет: аудит пакета (`AUDIT_REPORT.md` в нём) и
сверка B показали, что схемы Фазы 4 на стенде не проверялись (контракт вырезался или подменялся
схемами Фазы 3), прогоны — по одному разу с `temperature`, holdout частично продублирован в main.
Поэтому из пакета взят только слой 1, а слой 2 написан заново по схемам кода (S8), см. D-B-138.

Решения владельца в чате 2026-11-02 (передано потоком B):

1. Слой 1 `teacher@2` — `teacher/v6.md` пакета как есть: это одобренная доктрина Фазы 3, текст
   совпадает с разделами 1–6 `teacher@1` (отличие только в переводах строк). Черновик стенда
   `teacher/v2.md` (Фаза 4) не берётся: правила подогнаны под сценарии holdout.
2. Заготовки, которые по смыслу годятся, ставятся дословно (слой 1), в слой 2 переносятся только
   правила формата (D-B-143); неточности — вопросами владельцу ниже. Одобрение текста — на ревью PR.
3. Заготовки, противоречащие ТЗ и схемам, не ставятся: роль на заглушке, тест доктрины —
   `xfail(strict=True)` с номером `BLOCKED-B-…` (§0.4.3, §7.6 п.5).

| Промпт | Слой 1 — откуда | Состояние |
| :-- | :-- | :-- |
| `teacher@2` (и `teacher_fallback`) | `teacher/v6.md` = `teacher@1` разд. 1–6 | доктрина владельца |
| `extractor@3` | `extractor/v3.md` до «Layer 2» | заготовка дословно |
| `verdict_free@1` | `verdict_free/v1.md` без разд. 4 (D-B-143) | заготовка |
| `verdict_proof@1` | `verdict_proof/v1.md`, п.9 без правила префикса (D-B-143) | заготовка |
| `second_opinion@1` | `second_opinion/v1.md`, п.5 без правила префикса (D-B-143) | заготовка |
| `task_generator@1` | `task_gen@1` разд. 1–8 (= `task_generator/v3.md` без двух фраз формата, D-B-139) | доктрина владельца |
| `builder@1` | `builder/v1.md` до «Layer 2» | заготовка дословно |
| `analyst@1` (и `analyst_deep`) | `drafts_untested/analyst_v1.md` до «Layer 2» | заготовка дословно, на стенде не гонялась |
| `task_checker@1`, `task_arbiter@1`, `solution_space@1`, `misconception_describer@1`, `today_planner@1`, `domain_classifier@1`, `viz_builder@1`, `release_judge@1` | черновики стенда (пакет `phase4_step1_clean_results/prompts/<role>/v1.md` + `TRACE_v1.md`), написанные по тезисам документа стенда | черновик, D-B-132; до этого — заглушка `BLOCKED-B-101`…`108` |

Вопросы владельцу по поставленным заготовкам (текст слоя 1 не правился):

- `verdict_proof@1` п.1: «authoritative gateway check for … levels 5–6» — по `Т-§7.3` вердикт модели
  проходит ворота только парой; формулировку стоит смягчить.
- `second_opinion@1` п.1: триггеры «confidence < 0.70 … or was explicitly challenged by the learner» —
  в `Т-§7.7` оспаривания учеником среди триггеров нет, порог — параметр `verdict_min_confidence`;
  второе применение (`second_opinion.diagnosis` строки канваса, `Т-§15.4`) заготовкой не покрыто.
- `verdict_free@1` п.2.7 и `verdict_proof@1`/`second_opinion@1`: «set `misconception: null`» —
  в схеме ещё `misconception_hypothesis`; по смыслу оба null, слой 2 это говорит.
- `extractor@3` разд. 2 дублирует таблицу типов пробела общего блока `diagnostics_and_caution`
  (разными словами); в `Т-§7.6` таблица `П-6.4` подаётся ещё и входом (`{{ gap_types }}`).
- `analyst@1` п.5: «affective state (confidence, frustration, fatigue)» — опора манеры в
  `Т-§9.5`/WP5.3 — профиль и выученное; эмоции из динамики сессии там не названы.
- `builder@1` п.4 (циклы `REQUIRES`): выход `builder@1` рёбер не содержит, циклы снимает код
  (`Т-§4.10`); правило безвредно, но не к чему.
- Общий блок `diagnostics_and_caution` (реестр §4.1) есть только в `extractor@3`; у `verdict_*` и
  `second_opinion` — свои формулировки тех же правил.

**Стенд B на Meta API (2 нояб.).** Пакет второго прогона стенда (`workprompt/phase4_step1_clean_results`:
`BENCHMARK_SUMMARY.md`, `PROBE_CALLS_REPORT.md`, 252 лога) перепроверен по сырым логам моделями кода.
Расхождения: сводка ставит PASS всем ролям при 66.7% проверок кода у `teacher`, 50% у
`today_planner` и 6.7% валидных первых ответов у `task_generator`; вывод пробы P1 «модель не может
нарушить strict-схему» неверен — на Baseten есть ответы `assumptions: "real"` и
`neighbor_idea: null` против схемы; сценарии — по 2–5 на роль, у учителя пустой блок инструментов,
у `builder` проверки на несуществующие поля, «спойлер» учителя противоречит доктрине (ученик просит
ответ). Поэтому B собрал свой стенд: вызов как у шлюза (`POST /responses`, одно user-сообщение,
strict-схема `to_strict_json_schema`, без `temperature`, повтор схемы и обрыва как в
`responses_client.py`), модели прода (`muse-spark-1.3`, `muse-wonder-1.0`; ключа Baseten нет),
проверки — модели Pydantic, `validate_markup`, `grammar_ok` и проверки кода из реестра §5.
Сценарии: 117 main/ru и 42 holdout (holdout написан отдельно, до правок; sha256 файлов —
`ff2e4a8f…d691d7`). Прогоны по 3 на сценарий. Стенд, сценарии, логи и отчёт —
`workprompt/phase4_step1_clean_results/stage_b_meta_bench/` (вне репозитория).

Итог на финальных промптах и лимитах (D-B-131…137), 3 прогона на сценарий: main/ru — 411
прогонов, все первые ответы валидны по схеме, 0 обрывов, 404 PASS (98.3%); по сценариям — 126 PASS,
7 FLAKY (по одному сбою из трёх: `teacher` ×3, `teacher_fallback`, `analyst_deep`, `task_checker`,
`task_generator`), 0 FAIL. Holdout (под него промпты не правились) — 35 PASS, 4 FLAKY, 2 FAIL из 42:
FAIL `teacher` h05 — дефект сценария (ждёт знак «?», а учитель спрашивает элементом; ход верный),
`task_checker` h03 — спорно (без слова о возврате модель читает выбор «без возврата» и не отмечает
неоднозначность); FLAKY `viz_builder` ×2 (одно значение параметра вместо трёх в части прогонов),
`task_checker` h02 (назван ли метод в «выборочное стандартное отклонение»), `teacher` h03.
Расход финального main/ru: ~0.88 млн входных и ~0.93 млн выходных токенов.

Открытые вопросы стенда владелец 2026-11-02 поручил решить B по документам: решения D-B-134…137.

Роли, вызываемые кодом C (`recognizer`, `canvas_diagnoser`, `material_parser`, `artifact_writer`):
слой 2 пишет C (§7.3 п.2), B регистрирует схемы и ревьюит PR; заготовки лежат в том же пакете
(`drafts_untested/`, `artifact_writer/v1`–`v4`) и тоже не проверены на схемах Фазы 4.

## Реестр отклонений от основных документов

Как в ТЗ Фазы 4 §2.4 (R4-1…R4-4).

| # | Что | Отступление | Основание | Возврат |
| :-- | :-- | :-- | :-- | :-- |
| R4-C1 | Зависимости backend (§4.6) | Добавлен `python-multipart` — его нет в §4.6, но без него FastAPI не разбирает multipart, который требует WP20.1 | Решение владельца 2026-11-02 («конечно ставь тогда»), D-C-113 п.3 | Внести `python-multipart` в таблицу §4.6 |

## Журнал решений

### Поток A

### D-A-101. Размер пула `Db`
- Класс: B. WP1.2, `quack/config.py`: `pg_pool_min_size` 1, `pg_pool_max_size` 10 на процесс. Размеров нет ни в `Т-§`, ни в `Д-§`; числа в коде запрещены (§0.3). Варианты: (а) 1/10; (б) как в Фазе 3 (10 + 5 сверх). Решение (а) — консервативно (§0.4.3, последний абзац). Обратимость: значения параметров. Тесты: `T-DB5` (работает на пуле). Подтверждение: нет.

### D-A-102. `projector_batch_size` и `rebuild_max_tx_ops` 200 000 — вместе с WP3
- Класс: B. §6.7 требует переименовать `projector_batch_max_events` → `projector_batch_size` и поднять `rebuild_max_tx_ops` до 200 000. Оба читают проектор и пересборка Фазы 3, `quack/cli.py` (C) и тесты Фазы 3 (`test_worker_and_ops.py`, `test_infra.py` проверяет 5000). Варианты: (а) сейчас — правка файлов C и утверждения чужого теста; (б) в WP3, когда старый проектор заменяется и его потребители уходят. Решение (б). Почему: §0.4.3 п.3, п.5; §0.4.4 п.14. Обратимость: имя и значение параметра. Подтверждение: нет.

### D-A-103. Переходный период: две схемы Postgres до WP1.3
- Класс: C
- WP / место: WP1.1–1.3; `backend/db/migrations/`, `quack/db/db.py`, `quack/events/log.py`, `quack/events/registry.py`, `tests/db/fixtures.py`
- Контекст: WP1.1 (чистый старт) создаёт таблицы с теми же именами, что у Фаз 1–3, но с другими колонками (`core.events`, `ops.jobs`, `ops.event_types_seen`, `ops.projector_offsets`, `ops.dispatcher_offsets`, `ops.turn_manifests`), а каталог WP2 убирает 36 типов `С-§5`. WP1.3 при этом оставляет старые модули B и C на SQLAlchemy до G3, и им нужны старые таблицы и старый каталог; `phase-4` должна быть всегда зелёной (§7.4). ТЗ не говорит, как обе схемы живут одновременно.
- Варианты: (1) заменить схему сразу — старый код и ~770 тестов B и C падают, чинить пришлось бы в чужих зонах (§0.4.4 п.14); (2) новые таблицы под временными именами — нарушает контракт §6.1; (3) две схемы до WP1.3: новая — dbmate из `backend/db/migrations/` в отдельной базе (в тестах — `<test db>_p4`, фикстуры `p4_db`, `pg_db`, `create_learner` в `tests/db/fixtures.py`), новый код (`quack.db.Db`, `quack.events.log.append_events`, `quack.events.registry`) — рядом со старым (`quack.db.postgres`, `quack.events.append`, `quack.events.catalog`). Alembic, старый каталог и старые модули удаляются в WP1.3 вместе с последним потребителем; переключение `ops migrate`, compose и CI на dbmate — WP9 (C) в момент перехода.
- Решение: (3).
- Почему: ТЗ само предполагает, что старый код на SQLAlchemy работает до WP1.3: поля `engine` и `session_factory` уходят «вместе с SQLAlchemy (WP1.3)» (§4.2), зависимость `alembic` удаляется в WP1.3, а не в WP1.1, старые модули переносит владелец «когда переписывает» (WP1.3, риск R-W §9), остаток можно урезать с возвратом R2 в реестр (§7.5 п.6), `phase-4` всегда зелёная (§7.4). Со всем этим расходится одна фраза WP1.1 «Alembic-ревизии 0001, 0002 удаляются»: без старой схемы старые модули и их тесты падают в чужих зонах (§0.4.4 п.14). Первоисточники (`Т-§1.2`, `Т-§3.1`) переход не описывают; итог фазы одинаков в обоих вариантах. Критерии §0.4.3: п.1 — ничего не теряется и не ломается; п.3 — интерфейсы швов S2/S3 те же; п.4 — снимается удалением старых модулей и Alembic в WP1.3. Сдвигается только момент удаления ревизий Alembic: из WP1.1 в WP1.3 (вместе с зависимостью `alembic`).
- Обратимость: удалить отдельную базу и фикстуры; схема и код Фазы 4 от этого не меняются.
- Тесты: `T-DB1`, `T-DB5`, `tests/db/fixtures.py`.
- Согласовано: B — да (2026-11-02: новый код B сразу на `Db` и `append_events`, старые модули B переводит и удаляет при переписывании в WP11–WP15, остаток к G3 — A по §7.3 п.1); C — да (2026-11-02, ответ в PR #74, раздел C; dbmate в CI — PR #77).
- Требует подтверждения владельцем: да — **подтверждено** владельцем 2026-11-02 (передано через B, согласие B — PR #76). Решение принято исполнителем A по поручению разработчика потока A после сверки с ТЗ.

### D-A-104. Колонки базовой миграции, которых §6.1 не уточняет
- Класс: B. WP1.1, `backend/db/migrations/20261102000001_baseline.sql`. После G0 добавить `NOT NULL` нельзя (только расширяющие миграции), поэтому `NOT NULL` — у ключей, `learner_id`, времени и статусов, а ссылки, без которых строка осмысленна (`domain_id`, `topic_id`, `hub_id`, `session_id`), — `NULL`. Исключение по сверке B: `content.sessions.domain_id NOT NULL` (`Т-§22.9`: «Сессий без домена нет»). Целые — `BIGINT` (правило squawk `prefer-bigint-over-int`, `Д-§5.2` п.2; тип после G0 не меняется). `core.learners.email` — `NOT NULL`, уникальный, `CHECK` на нижний регистр. `ops.jobs.job_key` — первичный ключ; `ops.jobs.learner_id` — `NULL` только у периодических задач WP7.5. `ops.turn_manifests` — ключ `manifest_id` (ссылка `turn.committed.manifest_id`; `turn_id` в Фазе 4 нет), `reasoning_effort` Фазы 3 → `effort`; `prompt_version` и `renderer_version` — `TEXT` вида `teacher@2`, `renderer@1` (по сверке B: `Т-§11.6` «версия роль@N записывается в манифест», `Т-§10.6`). `ops.llm_usage` — токены `input`, `cached_input`, `output`, `reasoning` (виды таблицы цен §1.3 плюс рассуждение), `cost_usd numeric(12,6)`. `ops.event_types_seen.first_seen_at` и `updated_at` у отметок — как в Фазе 3. Внешних ключей нет (как в Фазе 3; удаление WP25 идёт по `learner_id`). Схема `langgraph` не создаётся (`Т-§22.3`, §2.2). Почему: §0.4.3, «частые случаи», строка 1; п.4. Обратимость: до G0 — правка baseline, после — расширяющая миграция. Тесты: `T-DB1`. Владельцам таблиц B и C — проверить свои до G0. Подтверждение: нет.

### D-A-105. `append_events` не заводит строку ученика
- Класс: B. WP1.2, `quack/events/log.py`. `Т-§2.3`: «блокирует строку ученика (SELECT … FOR UPDATE)»; Фаза 3 заводила `core.learner_seq` лениво. Решение: нет строки `core.learners` → `LearnerNotFoundError`; строку заводит вход (WP18, C), в тестах — `tests.db.fixtures.create_learner`. Почему: §0.4.3 п.2 (буква `Т-§2.3`), `email NOT NULL` (D-A-104). Обратимость: одна ветка функции. Тесты: `test_learner_row_is_required`. Подтверждение: нет.

### D-A-106. Формат `agent:<kind>` в `actor`
- Класс: B. WP2.1, `quack/events/actor.py`: `agent:` и имя в `snake_case` (`^agent:[a-z][a-z0-9_]*$`), как имена ролей; формы `kind` документ не задаёт. Обратимость: одно регулярное выражение. Тесты: `test_actor_versions_and_agents`. Подтверждение: нет.

### D-A-107. Текст `item.flagged_unclear` — в поле `text`
- Класс: B. WP2.1, WP2.3, `quack/events/event_types.py`. §6.3 называет поле `quote`, а WP2.3 включает тип в полнотекстовый поиск, и `Т-§3.1` требует: «все типы событий с текстом для поиска хранят его в поле text». Решение: цитируемый фрагмент — поле `text` (уровень 2 §0.4.1 выше ТЗ). Обратимость: имя поля до G1. Тесты: `test_text_types_have_text_and_match_index`. Подтверждение: нет (B пишет этот тип — сообщено).

### D-A-108. Ключ `check.failed`
- Класс: B. WP2.1, `quack/events/keys.py`: `check_failed:{answer_seq}:{part}` — по образцу `verdict:{answer_seq}:{part}` (одна запись на часть, `Т-§6.1`). Тесты: `test_derived_keys_deterministic`. Подтверждение: нет.

### D-A-109. Черновик каталога S3 (G0) — поля сверх §6.3
- Класс: B
- WP / место: WP2.1, `quack/events/values.py`, `quack/events/records.py`, `quack/events/event_types.py`
- Контекст: §6.3 даёт ключевые поля, остальное — «минимально нужное для правила» (§0.4.3, «частые случаи», строка 1). Q-A-1 (а): модели B одной формы — в ядре, формы с метками — их id-версии в ядре, имена даёт A.
- Решение: `values.py` — `LearnerAnswer`, `AnswerSpec` и части, `Verdict`, `CheckFailed` (теперь модель Pydantic, а не dataclass), `NewSkill`, перечни; `Verdict` и `CheckFailed` — сами нагрузки `verdict.recorded`, `check.failed`. `records.py` — id-формы: поле-метка `x` → `x_id`, `R…` → `request_id`, `C…` → `card_ids`, `P…` → `chunk_id`; `TurnTaskRecord` несёт `task_id` задачи, созданной ходом (WP2.2); `DeadlineRecord.deadline_at_ms` (как в `hub.deadline_set`); `ExtractedElementRecord.at_ms` — время действия, копирует код (`Т-§2.1`); `RootCauseRecord.confidence` — категория модели, число даёт код при проекции (закон 4). Перечни из `Т-§3.4.2`: `origin` темы и навыка (`session`, `material`, `learner`), задача — `source` (`seminar`, `generated`, `material`, `teacher`), `verification` (`unchecked`, `checked`, `disputed`); `edge.added.origin` — `material`, `model`, `learner` (`Т-§4.6`); `hub.created.kind` — WP6.3; `hub.deadline_set.source` — `turn`, `observation`, `syllabus`, `learner` (WP6.3); `deadline_at_ms = null` снимает дедлайн. `from`/`into` → `from_id`/`into_id`. Пометки «обработчик / правило» — по столбцам §6.3 (`SPECS`, T-EV5).
- Почему: §0.4.3, «частые случаи», строка 1; `Т-§0.4` (snake_case в нагрузке).
- Обратимость: до G1 — правка моделей; после — только новой версией схемы (§0.4.4 п.2).
- Тесты: `T-EV1`, `T-EV2`, `T-EV5`, `test_shared_models_are_the_payloads`, `tests/events/samples.py`.
- Требует подтверждения владельцем: нет. Поля типов B и C — подтвердить владельцам типов до G1 (вопросы Q-A-2, Q-A-3).

### D-A-110. S6: виды задач и таблица правил WP7.1 — выборы там, где ТЗ молчит
- Класс: B
- WP / место: WP7.1, §6.5, `quack/jobs/rules_p4.py` (до WP1.3 рядом с `kinds.py`/`dispatcher_rules.py` Фазы 3, D-A-103)
- Контекст: таблица WP7.1 — по описанию владельцев задач (§7.3 п.4). Часть условий в ней словами; в нагрузке событий они выражаются полями, и надо выбрать какими.
- Решение (таблица — ниже; `plan_jobs(event, settings)` — чистая функция события):
  1. «Числа выражением» (B): `answer.kind == "number"` с заполненным `answer.sympy` → `check.symbolic`; просто число — мгновенный вердикт (WP11.2), задачи нет. `expression`, `quantity` — всегда `check.symbolic`.
  2. Ключи. Без склейки: `job_key = {kind}:{learner}:{seq}`; у `check.symbolic` и `check.model` — `{kind}:{learner}:{answer_seq}:{part}`, часть без имени — `main` (D-B-121). Медленный `answer.submitted` и `check.failed` того же ответа дают один ключ `check.model` — вторая вставка ничего не делает (`ON CONFLICT DO NOTHING`). Со склейкой — `{coalesce_key}:{seq}` (ориентир `Т-§13.1`).
  3. `analyst.deep` склеивается по своему ключу `analyst_deep:{learner}`, а не по `analyst:{learner}` из таблицы: при общем ключе `analyst.deep` на `session.ended` склеился бы с `analyst.run` и один из видов пропал бы. `lock_key` общий (`analyst:{learner}`) — как в таблице.
  4. «Проявление заблуждения»: `verdict.recorded` с `misconception_id` или `misconception_hypothesis`; `observation.diagnosed` с тем же в `diagnosis`; `observation.extracted` с элементом, где `misconception_id`, `new_misconception` или `kind = misconception_hypothesis`. Ставит `analyst.run`; `misconception.describe` — только для известного `misconception_id` (`lock_key = misconception:{id}`): у гипотезы словами узла ещё нет. **Вопрос B (WP16.2):** описывать ли гипотезу, когда проектор создаст узел, и по какому событию.
  5. «Неуверенная пометка» диагноза: `diagnosis.kind == "question"` (`Т-§15.4`, WP21.4: неуверенный диагноз → `question` и второе мнение) → `second_opinion.diagnosis`.
  6. «Задачи банка без пространства решения»: `task.created` с `source` ∈ {`seminar`, `generated`, `material`} → `task.solution_space` (P2). Задачи `teacher` (на лету) получают пространство лениво через `agent.requested {kind: solution_space}` (WP12.4).
  7. `agent.requested`: вид `agent.<kind>` для `viz`, `illustration`, `task_generation`, `solution_space`, `artifact`; класс P1, если `needed_in_session`, иначе P2. Вид `known_check` задачи агента не ставит (проверку «я это знаю» ставит `known.claimed` → `check.known_claim`). **Вопрос B:** кто пишет `agent.requested {kind: known_check}` и нужна ли по нему задача?
  8. `photo.pipeline`: `lock_key = canvas:{canvas_id}`; фото вне канваса — `photo:{photo_id}`. `material.parse`: P1 при `session_id`, иначе P2; блокировку шага записи структуры `domain:{id}` ставит обработчик (C) — домена в нагрузке `material.uploaded` нет.
  9. `skill.split`: `extract.episode` с `restrict_skill_ids` = делимый навык и части; `episode.reassigned`: `extract.episode` с `episode_seq` и `topic_id`. Какие эпизоды переизвлечь, находит обработчик WP15.
  10. `visible` (`Т-§13.8`): видимы `check.symbolic`, `check.model`, `task.check`, `photo.pipeline`, `material.parse`, `agent.*`, `check.known_claim`; остальные — нет. \[ПРОВЕРИТЬ\] для `second_opinion.diagnosis`, `canvas.rediagnose`, `today.prepare`, `task.solution_space`, `artifact.*`, `export.data`: документ не называет — сделаны невидимыми.
  11. Роли по видам (`KIND_LLM_ROLES`) — из перечня классов ролей (`Т-§11.3`, ТЗ §5, «Класс приоритета роли»); `check.symbolic` моделей не зовёт (страховка может уйти в `check.model` отдельной задачей). Класс по умолчанию — класс из таблицы WP7.1; периодические — P3.
  12. Строки, читающие данные сверх события (`artifact.topic_refresh` на `session.ended` и `task.closed`, `artifact.cheatsheet`, `embedding.compute`, `graph.hygiene`), перечислены в `RULES` с полем `needs` и реализуются в G2 вместе с диспетчером (WP7.1); `plan_jobs` их пока не планирует.
- Почему: §0.4.3 п.4, п.5; закон 5 (повтор заменяет запись, не дублирует); `Т-§13.1`.
- Обратимость: таблица данных, один модуль.
- Тесты: `tests/jobs/test_rules_p4.py` (25 passed; `T-D1` в части строк по событию, полный — в G2).
- Требует подтверждения владельцем: нет. Вопросы B — п.4, п.7; \[ПРОВЕРИТЬ\] — п.10.

Таблица S6 (G1; «пакет» — исполнитель вида):

| Событие | Вид задачи | Класс | `lock_key` / `coalesce_key` | `required_seq` | Пакет |
| :-- | :-- | :-: | :-- | :-: | :-- |
| `episode.closed`, `has_content` | `extract.episode` | P2 | — / — | seq события | WP15 |
| `task.closed` | `analyst.run` | P2 | `analyst:{learner}` / `analyst:{learner}` | seq | WP16.1 |
| `session.ended` | `analyst.run` + `analyst.deep` | P2 | `analyst:{learner}` / `analyst:{learner}`, `analyst_deep:{learner}` | seq | WP16.1 |
| `verdict.recorded`, `observation.diagnosed`, `observation.extracted` с проявлением | `analyst.run`; `misconception.describe` (с id) | P2; P3 | `analyst:{learner}` / `analyst:{learner}`; `misconception:{id}` / — | seq | WP16.1, WP16.2 |
| `answer.submitted`: `expression`, `quantity`, `number` с `sympy` | `check.symbolic`, `run_at = occurred_at + symbolic_check_delay_ms` | P1 | — / — | — | WP11.3 |
| `answer.submitted`: `proof`, `free_text`, `drawing` | `check.model` | P1 | — / — | — | WP11.6 |
| `check.failed` | `check.model` | P1 | — / — | — | WP11.6 |
| `turn.committed`, `markup.tasks` не пуст | `task.check` | P1 | — / — | — | WP12.5 |
| `observation.diagnosed`, `diagnosis.kind = question` | `second_opinion.diagnosis` | P1 | — / — | seq | WP21.4 |
| `handwriting.corrected` | `canvas.rediagnose` | P1 | — / — | — | WP21.4 |
| `photo.uploaded` | `photo.pipeline` | P1 | `canvas:{id}` / — | — | WP22.3 |
| `material.uploaded` | `material.parse` | P1 при `session_id`, иначе P2 | — / — | — | WP20.2 |
| `task.created`, `source` банка | `task.solution_space` | P2 | — / — | — | WP12.4 |
| `agent.requested` | `agent.<kind>` | P1 при `needed_in_session`, иначе P2 | — / — | — | WP16.6 |
| `today.shown` | `today.prepare` | P2 | `today:{learner}` / `today:{learner}` | seq | WP16.8 |
| `digest.written`, `plan_divergence` | `analyst.deep` | P2 | `analyst:{learner}` / `analyst_deep:{learner}` | seq | WP16.1 |
| `known.claimed` | `check.known_claim` | P2 | — / — | seq | WP8.2 |
| `episode.reassigned`, `skill.split` | `extract.episode` (с ограничением) | P2 | — / — | seq | WP15 |
| G2: `session.ended`, `task.closed`, дедлайн хаба; новые узлы с текстом; `session.ended` / счётчик тем | `artifact.topic_refresh`, `artifact.cheatsheet`; `embedding.compute`; `graph.hygiene` | P2; P2; P3 | `artifact:{topic}`, `artifact:{hub}`; —; `domain:{id}` / `hygiene:{domain}` | — | WP23, WP20.3, WP16.3 |

### D-A-111. S4: `quack.graph.read` — доступ через объект `GraphReader`, заглушка с фиксированными данными
- Класс: B
- WP / место: WP6.4, `quack/graph/read/` (`models.py`, `reader.py`), `tests/support/graph_read.py` (`FixedGraphReader`)
- Контекст: S4 (G1) — сигнатуры, модели ответов и заглушки. §4.2 запрещает модульные переопределения, а набор полей `AppResources`/`JobContext` фиксирован (в нём нет поля для чтения памяти).
- Решение: (1) интерфейс — `Protocol GraphReader` с методами WP6.4 (`slice_for_turn`, `frontier`, `topic_readiness`, `why`, `topic_requires`, `recall_probability`, `review_candidates`, `prep_context`, `skill_history`, `prerequisites`, `similar_mistakes`, `past_solution`, `state_at`); читающий код получает объект аргументом, настоящий читатель (G2) строится из `neo4j` и `settings` ресурсов; `materials_prefetch`/`materials_search` — `quack/graph/read/materials.py` (C), не здесь. (2) Модели — Pydantic, неизменяемые, без лишних полей, только id и факты (`Т-§10.2`, `Т-§7.4`: ни весов, ни ярусов); «не проверялось» — `LevelFact.status = not_tested`, не `failed` (закон 8). (3) Для B (WP11.6): `LevelFact.proven_by_direct` («доказан прямым Т1/Т2») и `last_t1_failed` («последнее Т1 по времени — провал») — входы `needs_second_opinion`; `LevelState` B строится из них одной строкой. (4) Для защитного правила WP13.5 `SkillFact.requires` — связи `REQUIRES` с `confidence` и признаками «есть показ», «есть свидетельство»; `PrerequisiteFact.confidence`. (5) `FixedGraphReader` — один ученик, три навыка (доказан прямым Т1/Т2; последнее Т1 — провал; не проверялся), заблуждение, корень, кандидаты на повторение, `prep_context`, `state_at`; `FixedGraphReader(lag_degraded=True)` — срез с отставанием проектора.
- Почему: §4.1, §4.2, WP6.4, S4.
- Обратимость: сигнатуры замораживаются на G1; до этого — правка моделей.
- Тесты: `tests/graph/test_read_stub.py` (9 passed).
- Требует подтверждения владельцем: нет. Поля, которых документ не называет прямо (`ExposureFact.kind: str`, `MaterialRef.kind`, `ReviewReason`), — \[ПРОВЕРИТЬ\] с B (WP14.2) и C (WP17) до G1.

### D-A-112. Единый ввод `get_current_learner_id` на сессиях — моя часть (ответ на D-C-112)
- Класс: B (пересечение зон, §7.3)
- Решение: согласен с п.1 (имя и подпись `get_current_learner_id` не меняются, код роутеров не меняется), п.2 и п.4. Роутер A один: `quack/domains/router.py`; его тесты на старом входе — `tests/domains/test_diag_idempotency.py`, `test_diag_open_and_bank.py`, `test_diag_state_from_events.py`, `test_diagnostic_and_graph_view.py`, `test_graph_view_fixes.py`, `test_topic_alias_routes.py`. Корневые тесты A, которые выпускают токены, — по `grep` на `ensure_users_hook`/`get_current_learner_id` в `tests/` корневых файлов A нет. C правит их одним PR с моим ревью (§7.3): смена способа входа, утверждения не меняются.
- Требует подтверждения владельцем: нет.

### Ответы потока A (2026-11-02)

- **Состояние #78, #80.** Влиты в `phase-4` (слияние в `fc38d58` по сообщению B). Дальше A работает от `phase-4`.
- **C: `quack.runtime`.** `create_job_context` строит `ComputeClient` через `create_compute_client(settings)` (§7.3 п.6): таймаут задания = `compute_task_timeout_s + compute_timeout_sec`.
- **C: D-A-101 и `Д-§4.1`.** `Д-§4.1` называет соединения по ролям: api 2 × 10, workers 2 × 5, projector 8 (всего около 46 из `max_connections = 100`). `pg_pool_max_size` — одно число на процесс (D-A-101, 10) — это верхняя граница, соединения открываются по мере надобности (`pg_pool_min_size = 1`). Худший случай при общем значении 10: 2 × 10 + 2 × 10 + 10 + служебные ≈ 64 из 100. Чтобы совпасть с `Д-§4.1`, **C ставит `PG_POOL_MAX_SIZE=5` у `workers` и `8` у `projector` в `compose.yaml`** (параметр уже есть, кода не нужно). Отдельной настройки «по роли» не заводим — в документах её нет.
- **C: D-A-103.** Подтверждено владельцем (строка «Требует подтверждения» D-A-103); ответ C принят.
- **C: `CROSS_LEARNER_ALLOWED`.** Две записи для #97 добавлены в `tests/db/test_sql_static.py`: `quack/auth/links.py:_LEARNER_BY_EMAIL`, `quack/auth/sessions.py:_SESSION_BY_TOKEN` (до входа ученик неизвестен, D-C-111).
- **C: срок заглушек `graph.read` (S4).** Готовы: D-A-111, `tests/support/graph_read.py`. Реализация — G2 (WP6.4).
- **B: `Verdict`.** `misconception` разделён на `misconception_id: UUID | None` и `misconception_hypothesis: str | None` (Q-A-2 п.1). `model_verdict` принимает `known_misconceptions` — ids в порядке меток `M1`…; метка в событие не попадает, неизвестная метка отбрасывается.
- **B: `rejected` (Q-A-2 п.3).** `{index, reason, quote}`: `index` — позиция элемента в выходе извлекателя (провенанс, закон 6).
- **B: чтение `core.events` (D-B-122).** Общих функций чтения в `quack.events` A не даёт: WP1.2 помещает SQL в модули пакетов, и три запроса B (событие по ключу идемпотентности, события сессии после N, владение доменом по `domain.created`) B пишет в своих `repo.py`. Условия: параметры только `%(name)s`, фильтр `learner_id` (тест `test_sql_static.py` это проверяет), для горячего пути — на `Db`, не на SQLAlchemy. Запрос по ключу идемпотентности уже есть внутри `append_events` (повтор возвращает записанное событие) — для страховки `check.symbolic` вердикт ищется по `verdict:{answer_seq}:{part}` тем же ключом. Если ни одна из функций не нужна второму потоку, дублирования нет.
- **B: правила S6 для WP11.3.** Таблица выше (D-A-110): `answer.submitted` быстрого типа → `check.symbolic` с `run_at = occurred_at + symbolic_check_delay_ms`; `check.failed` → `check.model`; `episode.closed` → `extract.episode`.
- **Ревью (2026-11-02).** Опубликованы в PR: #97, #98, #99 (открытые; в #99 одна ошибка состояния `StrokeJournal.flush`, до слияния), #93, #94, #96 (влиты до ревью; замечания — следующим PR B и C). `open_db(settings, wait=False)` — для замены блока пула в `create_app_resources` (C).

### Поток B

### D-B-101. Строки таблицы ролей без строки в `Т-§11.1`
- Класс: B
- WP / место: WP10.1, `quack/config.py` (`default_llm_roles`)
- Контекст: `Т-§11.1` не даёт `effort`/`max_output_tokens` для `segmenter`, `voice`, `illustrator`; `Т-§11.3` не называет класс `voice`; `recognizer` (P0 канвас / P1 фото) и `builder` (P2 сверка / P3 гигиена) имеют два класса, а `RoleConfig` — одно поле.
- Варианты: (а) null для нетекстовых, класс роли — по горячему использованию, класс задачи — правилом диспетчера; (б) отдельные роли на каждое использование.
- Решение: (а). `voice` — P1 («ученик ждёт результат», `Т-§11.3`); `recognizer` — P0, `builder` — P2; класс P1/P3 задачи фото и гигиены даёт правило диспетчера (WP10.1: «класс задачи задаёт правило диспетчера»). Таймауты: teacher 45 с, teacher_fallback 30 с (Фаза 3), остальные 60 с (`llm_timeout_sec`).
- Почему: §0.4.3 п.2–3 (буква `Т-§11.1`, без новых ролей).
- Обратимость: значения в `default_llm_roles`.
- Тесты: `T-AI1` (`tests/llm/test_phase4_ai_layer.py`).
- Требует подтверждения владельцем: нет

### D-B-102. `gap_type_min_confidence` = 0.6
- Класс: B. WP14.2. Стартовое значение — из ТЗ Ф4 WP14.2 / §6.7. Тесты: `T-CX2` (WP14). Подтверждение: нет.

### D-B-103. Лимиты инструментов памяти в `Settings.memory_tool_limits`
- Класс: B
- WP / место: WP14.4, `quack/config.py`, `quack/session/tools.py`
- Контекст: `Т-§10.4` даёт лимиты 10/5/2/1/5/10 как ориентир; числа в коде запрещены (§0.3).
- Решение: словарь `memory_tool_limits` по имени инструмента со значениями `Т-§10.4`.
- Почему: §0.3 «пороги только в Settings». Обратимость: значение параметра. Тесты: `T-CX4`. Подтверждение: нет.

### D-B-104. Перечни `intent` и `approach` выхода хода до доктрины
- Класс: C
- WP / место: WP13.3, `quack/session/teacher_output.py`
- Контекст: WP13.3 требует закрытых перечней «по доктрине владельца» к G1; доктрины нет (раздел «Промпты»).
- Варианты: (а) временные перечни из `П-4.4` (выбор хода) и `Т-§9.5`/`П-4.2` (приёмы); (б) открытая строка — нарушает строгий режим `Т-§11.1`.
- Решение: (а). `intent`: clarify_goal, explain, worked_example, practice, retrieval, diagnose, hint, feedback, answer_question, plan, wrap_up. `approach`: example_first, attempt_first, small_steps, prediction_first, faded_example, interleaving, contrast_pair, refutation, explain_in_own_words, visualization, none.
- Почему: §0.4.3 п.2 (ближе к `П-4.4`, `Т-§9.5`).
- Обратимость: два `Literal` в одном файле.
- Тесты: `tests/session/test_phase4_contracts.py`.
- Требует подтверждения владельцем: да

### D-B-105. Пространство имён псевдонима LangSmith
- Класс: B. WP10.6, `langsmith_pseudonym_ns` — фиксированный UUID в `Settings` (§2.3 строка 20 требует «хранится в конфиге», значения нет). Менять после первой трассы нельзя (псевдонимы разойдутся). Тесты: `T-AI8` (G4). Подтверждение: нет.

### D-B-106. `root_cause_confidence_map` = {low: 0.3, medium: 0.6, high: 0.9}
- Класс: B. WP15 п.3. Значений в документах нет; корни на состояние не влияют (`Т-§9.4`), число нужно только для `ROOT_CAUSE {confidence}` и ранжирования. Обратимость: параметр. Тесты: `T-X*` (WP15). Подтверждение: нет.

### D-B-107. Форма `AnswerSpec` и `TaskMarkup`
- Класс: B
- WP / место: WP11.1, WP12.2, `quack/practice/answer_spec.py`, `quack/practice/markup.py`
- Контекст: `Т-§5.2`, `Т-§6`, WP11.1 называют содержимое, но не поля.
- Решение: «короткий точный ответ» `Т-§6.4` — тип `short_text`; верный ответ `value: {latex, sympy}` (`Т-§22.7`), элементы `set`/`vector` — `items`; варианты выбора (id, текст, верный) — в `AnswerSpec.options`, ловушки и «соседняя идея» — в `TaskMarkup.options` по `option_id`; части — `TaskMarkup.parts` со своей `AnswerSpec` и необязательными `tests` (спецификация без рекурсии — строгая схема не выражает рекурсию); рубрика без пространства решения — `key_ideas`; `form_target` — `factored`/`simplified` (примеры `Т-§6.6`); допущения — имена SymPy. Имена полей разметки — как в `Т-§5.2` (`methodNamed`, `variantOf`, `pairTaskId`).
- Почему: §0.4.3 «частые случаи», первая строка; строгий режим `Т-§11.1`.
- Обратимость: модели в двух файлах.
- Тесты: `T-TK2`, `T-CH1`, контрактные тесты.
- Требует подтверждения владельцем: нет

### D-B-108. Новые виды коротких меток
- Класс: B. WP13.3, WP13.7, WP14.4, `quack/llm/labels.py`: хабы `H`, куски `P`, карточки `C`, поручения `R`, свидетельства `E`, строки канваса `L` — модель не видит id (`Т-§4.5`), а дедлайн, ссылки, карточки, отмена поручений и аргументы инструментов на них ссылаются. Без своих лимитов (как `M`). Подтверждение: нет.

### D-B-109. Виды и поля `Element`
- Класс: B. WP13.7, `quack/session/elements.py`: 13 видов `Т-§12.3` — `choice`, `why_choice`, `short_answer`, `task`, `scaffold`, `prediction`, `free_answer`, `pair`, `card_series`, `timed_quiz`, `visualization`, `material_link`, `reference_card`. Элемент несёт только показ; спецификация и разметка задания — в `p3_markup.tasks` с тем же `element_id`. Подтверждение: нет.

### D-B-110. Поля `p2_body`, `agentRequests`, дедлайна из разговора
- Класс: B. WP13.3: блок — `{block_id, text | null, element_id | null}`; параметры поручения — один объект с полями по видам (null, если не применимо: строгий режим без свободных словарей); дедлайн — `{hub_label, new_hub_name, deadline_at (ISO 8601), coverage: метки тем}`. Подтверждение: нет.

### D-B-111. `oneOf` в строгой схеме
- Класс: B. `quack/llm/strict_schema.py`: дискриминированное объединение Pydantic (`oneOf` + `discriminator`) превращается в `anyOf` без `discriminator`; `kind` каждого варианта закреплён `const`. Тесты: `test_role_schemas_are_strict`. Подтверждение: нет.

### D-B-112. Самооценка карточки — да/нет
- Класс: B. `answer.submitted.self_assessment` — `bool` («я помнил», `Т-§14.3`, `Т-§17.5`); уверенность 1–4 — отдельное поле `confidence`. Подтверждение: нет.

### D-B-113. Схемы выходов ролей B
- Класс: B. `quack/practice/role_outputs.py`, `quack/agents/schemas.py`: поля — названные в `Т-§5.5`, `Т-§5.6`, `Т-§6.8`, `Т-§7.6`, `Т-§9.3`, `Т-§13.5`, `Т-§4.3`, `Т-§4.9`, `Т-§13.6`; остальное — минимально нужное читающему коду. Категории вместо чисел силы (закон 4); числовая `confidence` есть только у вердикта модели (порог второго мнения `Т-§7.7`) и у классификатора домена (порог `domain_autolink_confidence`). Подтверждение: нет.

### D-B-114. `second_opinion` не видит первичный вердикт
- Класс: B
- WP / место: WP11.6, вход `second_opinion@1`
- Контекст: `Т-§7.7` не говорит, подаётся ли первый вердикт второму мнению (реестр промптов, вопрос 3).
- Варианты: (а) вход тот же, что у первого (условие, рубрика, ответ), без первого вердикта; (б) с первым вердиктом.
- Решение: (а). Согласие считает код, сравнивая `outcome` двух вердиктов.
- Почему: §0.4.3 п.1 — независимая проверка; с первым вердиктом на входе второе мнение склонно соглашаться, и «согласие» (Т2/Т3, `Т-§7.7`) теряет смысл; закон 10 (модель не строит вывод на прошлом выводе).
- Обратимость: состав входа в одной функции сборки (WP11.6).
- Тесты: `T-CH6`.
- Требует подтверждения владельцем: нет

### D-B-115. Разбор выражения в `validate_markup` — грамматикой токенов на стороне API
- Класс: B
- WP / место: WP12.3, `quack/practice/grammar.py`, `quack/practice/markup.py`
- Контекст: WP12.3 — «выражение разбирается SymPy через compute или локальный разбор грамматики»; в backend SymPy нет, вызов compute на каждой проверке разметки — сеть на горячем пути хода.
- Варианты: (а) локальная грамматика токенов `Т-§6.5` (белый список, баланс скобок); (б) вызов compute; (в) SymPy в backend — зависимость вне §4.6.
- Решение: (а). Полный разбор SymPy — в `check()` через compute; не разобралось там — `check.failed` → модель (`Т-§22.7`).
- Почему: §0.4.3 п.2 (вариант назван в ТЗ), п.5 (без новой зависимости).
- Обратимость: одна функция `grammar_ok`.
- Тесты: `T-TK2` (`test_markup_common_rules`: `x.__class__` → `expression_unparsed`).
- Требует подтверждения владельцем: нет

### D-B-116. Точное совпадение числа — `correct` без порога значащих цифр
- Класс: B
- WP / место: WP11.2, `quack/practice/check.py`
- Контекст: `Т-§6.4`: при допуске по точности ученика нужно не меньше `min_sig_digits` значащих цифр; буквально ответ `5` на эталон `5` давал бы `unclear`.
- Решение: точное совпадение значения — `correct`; порог значащих цифр применяется только к приближённому ответу. Дробь вида `a/b` сравнивается точно.
- Почему: §0.4.3 п.2 — смысл `Т-§6.4` («не засчитать слишком грубый ответ»); точный ответ не грубый.
- Обратимость: одна ветка в `_number`.
- Тесты: `T-CH1` (`1/3` → correct, `0.3` → unclear).
- Требует подтверждения владельцем: нет

### D-B-117. Предел шагов цикла с инструментами
- Класс: B
- WP / место: WP10.3, `quack/llm/tool_loop.py`, `Settings.tool_loop_max_steps`
- Контекст: `Т-§11.5` не ограничивает число шагов «модель ⇄ инструменты»; модель, которая всё время вызывает инструменты, держала бы ход бесконечно.
- Варианты: (а) параметр с консервативным значением, после него — ошибка цикла `ToolLoopLimitError` (ход — как при ошибке модели); (б) без предела.
- Решение: (а), `tool_loop_max_steps = 4` (§0.4.3: «меньший лимит»; шесть инструментов можно вызвать за один шаг параллельно).
- Почему: §0.4.3 п.1 (горячий путь не висит), последний абзац (консервативное значение).
- Обратимость: значение параметра.
- Тесты: `test_tool_loop_step_limit`.
- Требует подтверждения владельцем: нет

### D-B-121. Часть задачи без частей — `main`
- Класс: B. WP11.4, `quack/practice/answers.py` (`DEFAULT_PART`): ключ вердикта `verdict:{answer_seq}:{part}` (`Т-§6.1`) требует часть, а у задачи без частей (`Т-§6.2`) её нет. Значение `main` — одна константа. Тесты: `test_instant_verdict_in_answer_transaction`. Подтверждение: нет.

### D-B-122. Помощь по задаче — запрос B к `core.events` до ответа A
- Класс: B
- WP / место: WP11.2, `quack/practice/answers.py` (`help_in_session`)
- Контекст: WP11.2 — помощь в вердикте вычисляет код по событиям задачи в сессии; общей функции чтения `core.events` в S2 нет (вопрос A в PR #78).
- Варианты: (а) запрос в репозитории B (WP1.2: SQL — в модулях пакетов, [ОРИЕНТИР]); (б) ждать функцию A.
- Решение: (а), параметры только `%(name)s`, фильтр по `learner_id` (`T-DB2`, `T-DB4`). Если A даст общую функцию в `quack.events` — заменить вызов.
- Почему: §7.1 «не ждать гейт»; §0.4.3 п.4 — одна функция.
- Обратимость: одна функция.
- Тесты: `test_help_from_session_events_and_repeat`.
- Требует подтверждения владельцем: нет

### D-B-120. Ядро математики WP11.5 — чистые функции до каркаса compute
- Класс: B
- WP / место: WP11.5, `compute/quack_compute/math/` (`grammar.py`, `equivalence.py`)
- Контекст: каркас compute с пулом и эндпоинтами `/v1/math/check`, `/v1/math/transition` — шов S10 (C, WP24) — ещё не готов; зависимости `pint`, `antlr4-python3-runtime==4.11.1`, `pebble` — в `compute/pyproject.toml` (файл C).
- Решение: ядро без ввода-вывода и без пула: разбор грамматикой-белым списком (`Т-§6.5`, `Т-§22.7`), сравнение в режимах `equal`, `up_to_constant`, `solution_set`, `interval`, `form` (`Т-§6.6`), подсказки `sign`, `coefficient` (`Т-§6.2`). `numeric_points` и бюджет `simplify` приходят параметрами от вызывающего (`Settings`, §6.7). Точность вычислений, диапазон точек и допуск сравнения — константы модуля, как в `checker.py` Фазы 3 (в §6.7 у compute только `compute_workers`, `chromium_idle_close_s`). Переменные вещественные (`Т-§6.6`): точка с невещественным значением — «не определена», кроме выражений с `I`. `form`: структурная проверка есть только для `factored`; для `simplified` — отказ `unsupported` → проверка моделью (`Т-§6.6`). Величины (`pint`), LaTeX (ANTLR strict) и эндпоинты — после S10 и зависимостей.
- Почему: §7.1 «не ждать гейт»: работа в своей зоне без чужих швов.
- Обратимость: новый каталог, старый `checker.py` не тронут.
- Тесты: `compute/tests/math/test_grammar.py` (`T-CH5`), `test_equivalence.py` (`T-CH4`, `T-CH7` без размерности).
- Требует подтверждения владельцем: нет

### D-B-123. Эндпоинты `/v1/math/check`, `/v1/math/transition`
- Класс: B
- WP / место: WP11.5, `compute/quack_compute/math/` (`schemas.py`, `service.py`, `latex.py`, `units.py`), маршруты в `compute/quack_compute/app.py` (объявление B по §7.3 п.3, как просил C в #82)
- Контекст: `Т-§6.5`–`Т-§6.7`, `Т-§15.4` п.1, `Т-§22.7` задают поведение, не форму запроса.
- Решение: выражение — `{latex?, sympy?}`, `sympy` разбирается первым, без него — LaTeX через ANTLR strict; `kind = quantity` — сырой ответ с единицей и `pint` (СИ, запятая → точка, допуск по `Т-§6.4`, иная размерность — `incorrect` + `dimension`); бюджет вызова — `timeout_ms` из запроса (API — `symbolic_inline_timeout_ms`, страховка — `symbolic_background_timeout_ms`), пороги проверки — объект `numeric` и `tolerance` из `Settings` вызывающего (D-B-124); неудача — `status: failed` с `reason` → `check.failed`. Переход строки: уравнение — равенство множеств решений, неравенство — интервалы, иначе — эквивалентность выражений.
- Почему: §0.4.3 п.2 (буква `Т-§`), п.6 (покрыто тестами).
- Обратимость: модели в `math/schemas.py`.
- Тесты: `compute/tests/math/test_service.py`.
- Требует подтверждения владельцем: нет

### D-B-124. Пороги численной проверки WP11.5 — в `Settings`, в compute через `Params`
- Класс: B
- WP / место: WP11.5, `compute/quack_compute/math/equivalence.py` (`Params`), `quack/config.py` (блок B)
- Контекст: ТЗ Ф4 §0.3 — пороги только в `Settings`, числа в коде модулей запрещены (ревью C к #79). `Т-§6.6` называет только `numeric_points` («высокая точность», «случайные точки области» — без чисел); у compute в §6.7 только `compute_workers`, `chromium_idle_close_s`. Отменяет часть D-B-120 про константы модуля.
- Варианты: (1) константы модуля, как в `checker.py` Фазы 3; (2) поля `ComputeSettings` (файл C); (3) `Settings` API (блок B), значения едут в запросе `/v1/math/*` и попадают в `Params`.
- Решение: (3). `math_precision_digits` = 30, `math_sample_low`/`math_sample_high` = −10/10, `math_positive_sample_min` = 1e-3, `math_max_attempts_per_point` = 10, `math_rel_tol` = 1e-9, `math_abs_tol` = 1e-12, `math_simplify_share` = 0.8 — значения Фазы 4 до этого решения, без изменения поведения.
- Почему: §0.3 (буква ТЗ); §0.4.3 п.4 — одно место правки; без правки чужого файла (§7.3).
- Обратимость: параметры в одном блоке `Settings`.
- Тесты: `compute/tests/math/test_params.py` (нет числовых констант в `math/*.py`, состав `Params`, допуск берётся из `Params`); `test_service.py` (`numeric`, `tolerance`, поля `numeric` обязательны — в compute нет значений по умолчанию).
- Требует подтверждения владельцем: нет

### D-B-125. S13: формат `function_call`, событий потока и флагов сбоев для подмен
- Класс: B
- WP / место: WP10.2–10.3, шов S13 (§7.2): интерфейс — `quack/llm/streaming.py` (`StreamingLLMProvider`, `StreamRequest`, `StreamEvent`), разбор SSE — `quack/llm/responses_client.py` (`_stream_event`); подмены — `tests/support/llm.py` (`ScriptedLLMProvider`) и `meta-mock` (C, §8.1, WP26.2)
- Контекст: §8.1 и WP26.2 называют возможности подмен (стриминг, ключи по алфавиту, тело раньше шапки по флагу, `function_call`, иногда два за шаг, `phase: commentary`, сбои Фазы 3), но не формат. Формат задаёт то, что уже читает код B.
- Решение — контракт для C:
  1. **`ScriptedLLMProvider.stream_structured(StreamRequest)`** отдаёт `StreamEvent` по шагам сценария схемы `request.base.schema_name`: `TextDelta` — куски текста ответа (только сообщения без `phase: commentary`); `OutputItemDone(item)` — каждый законченный элемент шага, как есть; последним — всегда `StreamCompleted(status, usage, model, headers)`. В журнал вызовов пишется весь `StreamRequest` (тесты B проверяют `input_items` следующего шага). Ответчик по умолчанию для схемы — один шаг без инструментов, текст — тот же JSON, что у `complete_structured`.
  2. **Элементы шага** (Responses API, Т-§11.5):
     - `{"type": "reasoning", "id": "rs_…", "encrypted_content": "…", "summary": []}`;
     - `{"type": "function_call", "id": "fc_…", "call_id": "call_…", "name": <имя инструмента из quack.session.tools>, "arguments": <JSON-строка аргументов>, "status": "completed"}` — код B берёт `call_id`, а не `id`; два вызова за шаг — два таких элемента подряд;
     - комментарий: `{"type": "message", "id": "msg_…", "role": "assistant", "phase": "commentary", "content": [{"type": "output_text", "text": "…"}]}` — перед `function_call`;
     - ответ: тот же `message` без `phase: commentary`, `content[0].text` — JSON выхода схемы.
     Шаг с `function_call` не содержит ответа; следующий шаг сценария выдаётся, когда во входе есть `function_call_output` на каждый `call_id` прошлого шага (`next_step_input`).
  3. **`meta-mock` (SSE `/responses`, `stream: true`)**: строки `data: {json}`; ключи по алфавиту на корне и во вложенных объектах (WP26.2). На элемент: `response.output_item.added {item}` (у комментария — с `phase: commentary`), для сообщения — `response.output_text.delta {item_id, delta}`, затем `response.output_item.done {item}`. В конце — `response.completed` или `response.incomplete` с `response: {model, status, usage: {input_tokens, input_tokens_details: {cached_tokens}, output_tokens, output_tokens_details: {reasoning_tokens}}}`. Заголовки `x-ratelimit-*` — у HTTP-ответа потока.
  4. **Флаг `body_before_head`** (§8.1): в тексте ответа хода ключ `p2_body` идёт раньше `p1_head`; парсер B буферизует ход целиком (Т-§12.2). Иначе ключи ответа — по алфавиту (`p1_head`, `p2_body`, `p3_markup`).
  5. **Сбои** — те же `ScriptedFailure.kind` Фазы 3, новых видов нет. Для потока: `unavailable`, `rate_limited` (с `retry_after`: секунды, дата HTTP или `None`), `bad_request` — исключение провайдера до первого события; `incomplete` — часть `TextDelta`, затем `StreamCompleted(status="incomplete")` (код B не разбирает, повторяет шаг с удвоенным лимитом); `invalid_json` — текст ответа не JSON, `status="completed"`; `commentary_only` — только элемент-комментарий, без ответа; `ratelimit_headers` — обычный ответ, заголовки — в `StreamCompleted.headers`. В `meta-mock` событие `response.failed` или `error` код B читает как `ProviderUnavailableError`.
- Почему: §0.4.3 п.3 — контракт совпадает с тем, что уже читает код B (`_stream_event`, `next_step_input`, `tool_calls`), шов не меняется; п.7 — сбои те же, что в Фазе 3.
- Обратимость: описание; код B не меняется.
- Тесты: `tests/llm/test_phase4_stream_adapter.py`, `tests/llm/test_phase4_ai_layer.py` (`T-AI2`–`T-AI6`) — на стороне B; тесты подмен — C.
- Требует подтверждения владельцем: нет

### D-B-126. Быстрая проверка WP11.3 в `check()`: что не пишется сейчас и что идёт к модели
- Класс: B
- WP / место: WP11.3, `quack/practice/check.py` (`check`, `_math_request`, `_from_compute`, `NotYet.reason`)
- Контекст: WP11.3 и `Т-§6.1` говорят «успел — вердикт; нет — ничего не пишет; страховка проверяет позже»; не названо: (а) что делать, если compute недоступен; (б) чем страховке отличить таймаут от недоступности; (в) ответ compute `unsupported` (нет структурной проверки вида, `Т-§6.6`); (г) `set`/`vector` не из чисел; (д) ответ без `sympy` и `latex`.
- Варианты: (1) таймаут и недоступность — `CheckFailed` сразу; (2) оба — `NotYet` с причиной, страховка превращает его в `check.failed` с той же причиной; (3) новый аргумент `check()` «режим API / страховка».
- Решение: (2). `NotYet.reason` — `timeout` (ожидание дольше `timeout_ms` с отменой запроса, или 504 compute) или `compute_unavailable`; значения совпадают с `CheckFailedReason` каталога A. `unsupported` → `NeedsModel` (модель, класс model, `Т-§6.6`), а не `check.failed`. `set`/`vector` не из чисел и спецификация без `value` → `CheckFailed("unparsed")` без вызова compute (в compute нет такого режима; `check.failed` → модель, `Т-§22.7`). Ответ ученика без `sympy` и `latex` уходит строкой `sympy`: compute разбирает любую строку грамматикой-белым списком (`Т-§6.5`). Допуск величины: `tol_abs` / `tol_rel` / `sig_digits` спецификации переводятся в `tol_abs` той же функцией, что у чисел (`Т-§6.4`); `min_sig_digits` и пороги численной проверки — из `Settings` (D-B-124).
- Почему: §0.4.3 п.3 — подпись `check()` (шов S7) не меняется, в `NotYet` только поле со значением по умолчанию; п.1 — каталог событий не трогается; п.2 — `Т-§6.6` («нет её — проверка моделью»).
- Обратимость: одна функция `_from_compute` и поле `NotYet.reason`.
- Тесты: `tests/practice/test_check_fast.py` (чистая часть `T-CH2`, `T-CH3`).
- Требует подтверждения владельцем: нет

### D-B-127. Распознанный ответ: порог «неуверенного» прочтения и снижение уверенности вердикта
- Класс: B
- WP / место: WP11.7, `quack/practice/check.py` (`apply_reading`), `quack/config.py` (блок B, `recognition_min_confidence`)
- Контекст: `Т-§6.9`, `Т-§16.3`: «уверенность распознавания понижает уверенность вердикта»; «неуверенное распознавание + отрицательный вердикт → сначала прочтение». Числа порога и способа понижения в документах нет; `mark_min_confidence` (`Т-§15.4`) — о диагнозе строки, не о прочтении.
- Варианты: (1) новый параметр `recognition_min_confidence`, понижение умножением; (2) взять `mark_min_confidence`; (3) понижение минимумом.
- Решение: (1). `recognition_min_confidence` = 0.8 (консервативно: чаще показываем прочтение до отрицательного вердикта; то же число, что у `mark_min_confidence`). Уверенность вердикта кода (её нет) становится уверенностью распознавания; уверенность модели умножается на неё. «Отрицательный» — `incorrect` и `partial` (консервативно: ученик видит прочтение раньше частичного вердикта). Набранный ответ (`recognition_confidence = None`) не меняется.
- Почему: §0.3 и §0.4.3 последний абзац — параметра нет в документах, значение консервативное, в `Settings`; п.4 — одна функция и один параметр.
- Обратимость: `apply_reading` и параметр в блоке B.
- Тесты: `tests/practice/test_check_reading.py` (`T-CH8`).
- Требует подтверждения владельцем: нет

### D-B-128. Второе мнение: что считается «отрицательным», «согласием» и чей вердикт
- Класс: B
- WP / место: WP11.6, `quack/practice/model_check.py` (`model_verdict`, `needs_second_opinion`, `with_second_opinion`)
- Контекст: `Т-§7.7` называет триггеры и результат, но не говорит: (а) входит ли `partial` в «отрицательный» и «положительный»; (б) что такое «согласно»; (в) как одна задача с несколькими уровнями даёт триггер; (г) куда идёт гипотеза заблуждения, пока `Verdict.misconception` одно поле (Q-A-2 п.1 не закрыт).
- Варианты: (а) `partial` — триггер или нет; (б) равенство `outcome` или совпадение пунктов рубрики; (в) любой уровень или все.
- Решение: (а) `partial` — не триггер: спайк `Т-§7.7` прямо отверг «partial на уровне 4 и выше» как новый триггер; (б) согласно — тот же `outcome`; (в) любой проверяемый уровень задачи; (г) `misconception` — метка, иначе гипотеза словами (`WP11.4` «метка или формулировка»), до разделения полей по Q-A-2. Вердикт кода второго мнения не получает (`Т-§7.7`: «только для вердикта модели»), даже с уверенностью распознавания (D-B-127). Ярус по `secondOpinion` ставит код A (WP4.1).
- Почему: §0.4.3 п.2 — буква `Т-§7.7` и его спайка; п.5 — без новых параметров.
- Обратимость: одна функция `needs_second_opinion`.
- Тесты: `tests/practice/test_second_opinion.py` (чистая часть `T-CH6`).
- Требует подтверждения владельцем: нет

### D-B-129. Чистые части WP13: правила шапки и разметки, буфер удержания, уровень рассуждения
- Класс: B
- WP / место: WP13.5 `quack/session/guards.py`; WP13.4 `quack/session/holdback.py`; WP13.8 `quack/session/turn_policy.py` (`teacher_reasoning_effort`)
- Контекст: граф хода (WP13.2) ждёт `Db` (S2), заглушек `graph.read` (S4) и шлюза; правила `Т-§12.4`, этап 3 `Т-§12.2` и таблица `Т-§12.9` от них не зависят. Не названо: (а) что такое «метки существуют» для разметки хода; (б) форма причины возврата модели; (в) когда проверяется спойлер в буфере.
- Решение: (а) метки `targetSkills`, `exposures[].skill` (навыки) и `targetsMisconception` (заблуждения) — из таблицы меток контекста; задания проверяет `validate_markup` (своё правило «каждое задание размечено»). Правило «опора» читает `REQUIRES` (S4) и придёт с ним. (б) Нарушение — `GuardViolation {reason, detail}`; `reason` — закрытый перечень кода, текст для модели собирает граф хода. (в) Спойлер проверяется по всему накопленному тексту при каждом куске и в конце тела; показывается только проверенный префикс без последних `spoiler_holdback_chars`. Уровень рассуждения — флаги `goal_changed`, `builds_plan`, `proof_answer` у функции Фазы 3 («функция Фазы 3 расширяется», WP13.8), по умолчанию `False`, вызовы Фазы 3 не меняются.
- Почему: §0.4.3 п.2 (`Т-§12.4`, `Т-§12.2`, `Т-§12.9`), п.3 (подпись функции Фазы 3 — только расширение), п.5.
- Обратимость: три модуля, по одной функции или классу.
- Тесты: `tests/session/test_head_guards.py` (часть `T-TT4`), `test_holdback.py` (часть `T-TT3`), `test_turn_effort.py` (`T-TT8`).
- Требует подтверждения владельцем: нет

#### Поток B: сверка таблиц B в базовой миграции (шов S2) и ответ на D-A-103

Сверено: `backend/db/migrations/20261102000001_baseline.sql` (ветка `phase-4-a-wp1`) против ТЗ Ф4 §6.1, `Т-§3.1`, `Т-§3.2`, `Т-§11.4`.

| Таблица | Итог |
| :-- | :-- |
| `content.session_plans`, `content.study_plans`, `content.tasks` | совпадает |
| `ops.llm_usage` | совпадает |
| `content.sessions` | **расхождение:** `domain_id UUID NULL`, а сессий без домена нет (`Т-§22.9`, ТЗ Ф4 WP13.10, WP16.4: «Домен выбирается до старта») — нужно `domain_id UUID NOT NULL` — **исправлено A в #78** (`b561aa3`) |
| `ops.turn_manifests` | **расхождение:** `prompt_version INT`, `renderer_version INT`, а в `ops.llm_usage` — `prompt_version TEXT`. Версии по `Т-§11.6`, `Т-§10.6` — `роль@N`, `renderer@N`; `teacher_fallback` идёт с промптом `teacher@2`, и по одному номеру промпт не восстановить для проигрывания (`Т-§3.2`). Предложение: `prompt_version TEXT`, `renderer_version TEXT` (`teacher@2`, `renderer@1`), как в `ops.llm_usage` — **исправлено A в #78** (`b561aa3`) |

Обе правки — до G0: после G0 только расширяющие миграции (§0.4.4 п.4).

**D-A-103 (две схемы до WP1.3):** B согласен с вариантом (3). Новый код B пишется сразу на `quack.db.Db` и `quack.events.log.append_events` (WP1.3); старые модули B (`quack/session/*`, `quack/practice/evaluation.py`, `selection.py`, `generation.py`) переходят на `Db` и удаляются, когда B переписывает их в WP11–WP15, остаток к G3 — PR A по §7.3 п.1.

### D-B-119. PR #75 (объявление `/actions`) вливается вместе с телом WP13.1
- Класс: B
- WP / место: WP13.1, PR #75
- Контекст: объявление маршрута без тела не проходит обход e2e `T-E2`, `T-E3`; исключить маршрут из обхода — сузить вход (§0.4.4 п.5), `xfail` вне §0.4.6 нельзя; `phase-4` должна быть зелёной (§7.4). G1 требует черновик `openapi.json` для фронтенда (§7.2, S11, S14).
- Варианты: (а) держать #75 открытым до тела WP13.1, черновик `openapi.json` к G1 брать из ветки #75; (б) вопрос владельцу.
- Решение: (а). C публикует снимок `openapi.json` из ветки `phase-4-b-actions-route` (коммит `679b8ea` и позже) в §«Для фронтенда» как черновик G1 с пометкой «маршрут `/actions` объявлен, тело — WP13.1»; в `phase-4` маршрут попадает вместе с телом.
- Почему: §0.4.3 п.1 (тесты не ослабляются, `phase-4` зелёная), п.3 (контракт S11 к G1 выдан в OpenAPI).
- Обратимость: влить #75 раньше, если владелец разрешит.
- Тесты: `test_actions_route_in_openapi` (B), T-A1 и тест 2xx (C, в #75), `T-E2`, `T-E3` — без изменений.
- Требует подтверждения владельцем: нет

### D-B-130. Наборы параметров визуализации: формат и как страница их читает (BLOCKED-C-201)
- Класс: B
- WP / место: WP16.5, `quack/agents/schemas.py` (`VizBuilderOutput.parameter_values`) → `RenderSnapshotsRequest.param_sets` (`quack/compute_client/contracts.py`, D-C-107) → страница в Chromium compute (WP24)
- Контекст: `Т-§13.6` п.1–2 — модель пишет страницу «какие параметры», compute делает снимки «при нескольких значениях параметров»; формат значений и способ передачи не названы. Строгая схема не допускает свободных словарей (`Т-§11.1`), поэтому в выходе модели — `list[str]`; в запросе compute — `list[dict]`.
- Варианты: (1) каждая строка — объект JSON, compute кладёт его в глобальную переменную до скриптов страницы; (2) параметры во фрагменте адреса `#…`; (3) отдельные поля «имя — значение» в схеме модели.
- Решение: (1).
  1. **Формат.** Каждый элемент `parameter_values` — строка с объектом JSON: имя параметра → число, строка или `true`/`false` (например `{"a": 2, "phase": 0.5}`). Один элемент — один снимок.
  2. **Перевод в `param_sets`.** Код B (`quack.agents`, WP16.5) делает `json.loads` каждой строки. Не объект или вложенные значения — нарушение разметки, оно идёт в ту же единственную попытку исправления (`Т-§22.10`). Пустой список — один набор `{}`: снимок со значениями по умолчанию.
  3. **Как страница читает.** compute перед загрузкой страницы задаёт `window.QUACK_VIZ_PARAMS = <набор>` (Playwright `add_init_script`, до любого скрипта страницы), затем `set_content(html)` и снимок. Страница берёт значения из `window.QUACK_VIZ_PARAMS`, а при его отсутствии — свои значения по умолчанию. У ученика (`GET /v1/viz/{id}`, iframe `sandbox="allow-scripts"`) переменной нет: страница открывается со значениями по умолчанию и меняет их своими элементами управления.
  4. **Промпт.** Требование «читать `window.QUACK_VIZ_PARAMS`, иначе значения по умолчанию» входит в контракт роли `viz_builder` (`PROMPT_CONTRACTS.md`). Текст промпта ведётся отдельно (заготовки владельца), здесь не пишется.
- Почему: §0.4.3 п.3 — схемы `VizBuilderOutput` и `RenderSnapshotsRequest` (D-C-107) не меняются; п.1 — без сети и без записи в страницу кода модели (CSP и sandbox `Т-§13.6`); п.5 — одна переменная, без нового протокола; страница одна и та же у compute и у ученика.
- Обратимость: имя переменной и одна функция разбора.
- Тесты: при реализации WP16.5 — разбор `parameter_values` (B, `tests/agents/`); снимок с набором, который страница читает из `window.QUACK_VIZ_PARAMS` (C, `compute/tests`).
- Требует подтверждения владельцем: нет

### D-B-138. Слой 2 промптов Фазы 4 — по схемам кода; имена входных блоков
- Класс: B
- WP / место: WP10.5, `quack/prompts/<role>/v<N>.md`, `tests/llm/prompt_contracts.py`
- Контекст: `## Output contract` заготовок стенда описывает схемы, которых нет в коде (поля
  `verdict`, `note`, `decisions`, `pairs.pair`, `verified`, `known_alternatives` и др.); имена
  входных блоков в реестре владельца — \[ОРИЕНТИР\]; сборщиков контекста для ролей Фазы 4 ещё нет
  (WP11.6, WP12.4–12.6, WP13–WP16).
- Варианты: (а) слой 2 заново по схемам S8 (`teacher_output.py`, `role_outputs.py`,
  `agents/schemas.py`), входы — по составу `Т-§`, имена — реестра, где он их даёт; (б) взять
  контракты заготовок и менять схемы.
- Решение: (а). Учитель: слоты `Т-§10.1` по порядку — слой 1 и слой 2 (статично), затем
  `tools_and_elements` (слой 3, шлёт код), `profile`, `domain_and_goals`, `conversation`,
  `session_plan`, `memory_picture`, `materials`, `labels`, `tail`, `guard_feedback`. Остальные
  роли — блоки по `Т-§` (`PROMPT_CONTRACTS.md`). Имена блоков — точка правки до написания
  сборщиков.
- Почему: §0.4.3 п.3 (схемы S8 не меняются), п.2 (состав входа — буква `Т-§`).
- Обратимость: текст промпта до первой выкатки правится на месте (§7.6 п.3).
- Тесты: `T-M5` (`test_prompt_mentions_only_declared_fields`), `test_prompt_contracts_file_is_current`.
- Требует подтверждения владельцем: нет

### D-B-139. Слой 1 `task_generator@1` — текст `task_gen@1`
- Класс: B. Заготовка `task_generator/v3.md` = разделы 1–8 `task_gen@1` плюс две фразы формата
  (значения `catches`, метка в `tests`) — это слой 2; они перенесены в `## Output contract`, слой 1
  остаётся словом в слово `task_gen@1`. Тесты: `T-M5`. Подтверждение: нет.

### D-B-140. `builder@1` — один промпт, две схемы по режиму
- Класс: B. `Т-§4.3` (сверка) и `Т-§4.10` (гигиена) — одна роль и один промпт (§6.6); код
  передаёт `text.format` по режиму: `BuilderOutput` или `HygieneOutput`. В реестре контрактов —
  кортеж схем (`PHASE4_PROMPT_SCHEMAS`), `T-M5` берёт объединение полей. Подтверждение: нет.

### D-B-141. `task_arbiter@1` — та же схема, что у `task_checker@1`
- Класс: B. `Т-§5.6`: при расхождении — арбитраж Wonder, «снова расхождение — задача
  выбрасывается»: арбитр даёт свой ответ и оценку разметки, сравнивает код (`check()`), как у
  проверяющего. Отдельной схемы нет (`TaskCheckOutput`); вход — оба решения и место расхождения.
  Обратимость: одна строка реестра. Подтверждение: нет.

### D-B-142. Пара уровня 5 от генератора — `pairTaskId` ставит код
- Класс: B. WP12.6: у второй задачи пары ещё нет метки `K…`, модель её не знает (`Т-§4.5`);
  генератор пишет обе задачи записями `tasks`, `pairTaskId` = null, связь ставит код до
  `validate_markup` (иначе правило уровня 5 не пройдёт). Тесты — с WP12.6. Подтверждение: нет.

### D-B-143. Правила формата из слоя 1 заготовок — в слой 2
- Класс: C
- WP / место: WP10.5, `verdict_free@1`, `verdict_proof@1`, `second_opinion@1`
- Контекст: в слое 1 заготовок есть правила формата под их контракт: префикс `new: ` в метке
  заблуждения (`verdict_proof` п.9, `second_opinion` п.5), раздел 4 `verdict_free` «System Output
  Note» (поле `note`, которого в схеме нет), служебная HTML-пометка стенда на русском.
- Варианты: (а) убрать их из слоя 1 и выразить в слое 2 (`misconception_hypothesis`); (б) оставить —
  модель получит противоречивые указания формата.
- Решение: (а), остальной текст слоя 1 — дословно.
- Почему: §7.6 п.1 (формат — слой 2, его пишет B); §0.4.3 п.3 (схема S8).
- Обратимость: вернуть фразы из пакета.
- Тесты: `T-M5`.
- Требует подтверждения владельцем: да

### D-B-131. Метки доменов `D`
- Класс: B
- WP / место: WP16.4, `quack/llm/labels.py`
- Контекст: `domain_classifier@1` выбирает домен ученика по метке (`Т-§4.5`, `Т-§4.9`), а в
  `LabelMap` вида «домен» не было; на стенде модель без метки писала имя домена.
- Решение: вид `domain` с префиксом `D` в `LabelMap`, `LabelMap.build(domains=…)`; без лимита (как `M`).
- Обратимость: убрать вид. Тесты: `test_label_map_labels_domains`, `T-M5`.
- Требует подтверждения владельцем: нет

### D-B-132. Слой 1 восьми ролей — черновики стенда
- Класс: C
- WP / место: WP10.5, `task_checker@1`, `task_arbiter@1`, `solution_space@1`,
  `misconception_describer@1`, `today_planner@1`, `domain_classifier@1`, `viz_builder@1`,
  `release_judge@1`; `builder@1` п.6
- Контекст: черновики слоя 1 написаны на стенде по тезисам документа стенда (реестр §5) и
  прогнаны; владелец в чате 2026-11-02 поручил B дорабатывать промпты самому («можешь дорабатывать
  сама все»). Слой 2 стенд не менял. В `builder@1` добавлен п.6 «та же идея в другом домене — свой
  навык со связью» (`Т-§3.4`, `Т-§4.3`): без него `same_idea` не заполнялся (0/3 → 3/3).
- Решение: черновики поставлены, заглушки и `BLOCKED-B-101…108` сняты (`DOCTRINE_PENDING` пуст).
- Обратимость: вернуть заглушки и записи `DOCTRINE_PENDING`.
- Тесты: `test_prompt_has_owner_doctrine`; стенд B (§«Промпты»).
- Требует подтверждения владельцем: да (текст слоя 1 — на ревью PR)

### D-B-133. Уточнения слоя 2 по стенду
- Класс: B
- WP / место: WP10.5, слой 2 промптов
- Контекст: стенд B показал, где модель путает контракт.
- Решение: пункт рубрики — метка (`R1`) без текста (`verdict_*`, `second_opinion`: было 0/12 →
  12/12); `assumptions` — список, `neighbor_idea` — true/false (`teacher@2`, `task_generator@1`);
  домен — метка `D…`, не имя; в `analyst@1` навыки и заблуждения — только метки; `extractor@3` не
  пишет `evidence` по навыку и уровню с вердиктом кода в эпизоде (`code_verdict_exists`);
  `teacher@2` — таблица уровней `Т-§5.3` для заданий и «метки не в тексте»; `builder@1` —
  `topic_hint` у каждого нового навыка, `same_idea` — навык другого домена; `viz_builder@1` —
  наборы параметров по D-B-130 (один JSON-объект на снимок, страница читает
  `window.QUACK_VIZ_PARAMS`, иначе свои значения по умолчанию; маркер в `MARKERS`, стенд — 6/6
  сценариев, 12 прогонов).
- Обратимость: вернуть формулировки. Тесты: `T-M5`, `test_prompt_contracts_file_is_current`.
- Требует подтверждения владельцем: нет

### D-B-134. Лимиты выхода по замеру с уровнем рассуждения
- Класс: B
- WP / место: WP10.1, `quack/config.py` (`default_llm_roles`)
- Контекст: 4096 в `Т-§11.1` обоснованы спайком без указания уровня рассуждения (самый длинный
  выход — 1674 токена). Замер стенда B на Meta API с продовыми `effort` (≈750 вызовов): обрыв
  первого ответа у `analyst` в 100% (медиана выхода 6043), `extractor` 36% (p95 10 182, максимум
  15 538), `solution_space` 29%, `task_generator` 26%, `analyst_deep` 8%; у `verdict_free`, `builder`,
  `task_checker` максимум — у самого лимита. Повтор с удвоенным лимитом спасает ответ, но удваивает
  задержку и расход; для P0/P1 это задержка, которую видит ученик (П-1.4).
- Решение: по `Т-§11.1` «меняются по замеру без правки документа» — около 1.5× p95, не выше
  `max_output_tokens_cap`: `extractor`, `analyst`, `analyst_deep` — 16 384; `verdict_free`,
  `builder`, `task_generator`, `task_checker`, `solution_space`, `teacher_fallback` — 8192.
  Остальные роли B — без изменений (запас есть). Роли C не мерились.
- Обратимость: значения конфига. Тесты: `test_role_table_matches_t111`.
- Требует подтверждения владельцем: нет (поручено решить B)

### D-B-135. Обход в `extractor@3`: просьба решения — не провал
- Класс: B (по поручению владельца решить по документам)
- WP / место: WP10.5, `extractor@3` слой 1, разд. 3 п.3
- Контекст: на стенде «не знаю, покажи решение» записывалось как `evidence` `incorrect`/`no_idea`,
  а пассивное «понял» после показа — уровнем 3 (main m03, holdout h03).
- Решение: две строки доктрины по `П-4.8` («каждый обход — сигнал, а не повод спорить», ученику
  не отказываем), `П-6.9`/`П-6.10` (показанное решение уровень не доказывает, пропущенная проверка —
  уровень неизвестен), `Т-§7` (показанное решение — «свидетельства понимания нет, есть обход»):
  из самой просьбы ничего отрицательного; работа по задаче — один раз с `help = shown_solution`,
  согласие после показа — не выше уровня 1; пропущенная проверка — ничего.
- Обратимость: убрать строки. Тесты: стенд B.
- Требует подтверждения владельцем: нет (поручено)

### D-B-136. `verdict_stance` — только о последнем действии ученика
- Класс: B
- WP / место: WP13.3/13.5, `teacher@2` слой 2; будущая защита «честный вердикт»
- Контекст: ход, открыто поправляющий пересмотренную проверку, ставил `verdict_stance = code`.
  `Т-§6.3`: позиция — «для ответа, на который отвечает»; поправка — отдельный слот контекста и
  поле `correctionsAcknowledged` (`Т-§5.6`, `Т-§10`).
- Решение: позиция относится только к последнему действию ученика (действию, запустившему ход);
  поправка пересмотра отмечается в `correctionsAcknowledged`. Защита WP13.5 сравнивает позицию с
  вердиктом ответа из этого действия.
- Обратимость: формулировка контракта. Тесты: стенд B; защита — при WP13.5.
- Требует подтверждения владельцем: нет

### D-B-137. Режим `interval` до проверки в коде — не в промптах
- Класс: B
- WP / место: WP10.5, `teacher@2`, `task_generator@1` слой 2; `compute` (`Т-§6.5`, `Т-§6.6`)
- Контекст: `Т-§6.6` — режим `interval` «неравенство: множества как интервалы и их объединения».
  В `phase-4` его сравнивает `compute` (`compute/quack_compute/math/equivalence.py`, `_intervals`:
  два неравенства с одной переменной; грамматика compute пускает `<`, `<=`, `>`, `>=`). Отсекает
  локальная грамматика `validate_markup` (`quack/practice/grammar.py`): в ней нет `<`, `>`, поэтому
  ответ-неравенство даёт `expression_unparsed`, и задача выбрасывается. Расширение `grammar.py` —
  отдельная задача B (не WP10.5).
- Решение: в контрактах режим `interval` не предлагается; неравенство — задачей с выбором
  интервалов или с числовым ответом. Реализация режима (имена `Interval`, `Union` в белом списке
  `Т-§6.5`, сравнение множеств) — отдельная задача проверки в коде; после неё режим возвращается в
  контракты.
- Обратимость: вернуть режим в перечень. Тесты: стенд B (`validate_markup`).
- Требует подтверждения владельцем: нет


#### Поток B: ответы на D-C-112 (п.2–3), слой учителя доски (WP21.1) и D-A-110 (п.4, п.7) — 2026-11-02

**D-C-112 п.2 (тестовый вход в `tests/session`).** Согласен. C переводит `tests/session/*` на `tests/support/auth.py: login(client, db, learner_id)` в своём PR вместе с остальными, ревью — B. Меняется только способ входа: утверждения и данные тестов B не меняются (§8.15).

**D-C-112 п.3 (`CONSENT_REQUIRED` на старте сессии).** Функция — C: `quack.auth.require_terms` (WP18.4). Объявление на `POST` старта сессии в `quack/session/router.py` делает B сам, в своём файле, вместе с WP13.1 и WP13.10: «Сессия не начинается без `consent.given {kind: terms}` — `403 CONSENT_REQUIRED`» — строка WP13.1, пакета B. Исключения §7.3 п.3 здесь не нужно. Тесты `T-AU6` (C) и часть `T-TT1` (B) читают одну зависимость. B ставит объявление сразу после слияния PR C с `require_terms`.

**Слой учителя доски (WP21.1).** Схему документа `content.canvas_boards.doc`, в том числе слоя учителя, задаёт C (WP21.1, §7.3: `quack/canvas/**`) и присылает B на ревью. По ТЗ код хода учителя (WP13, WP14) в доску не пишет:
- пометки `error`/`question` и тихие подсказки первой ступени ставит код канваса вместе с быстрым слоем (WP21.5, `Т-§15.5` «Кто исполняет»);
- если подсказки в пространстве решения нет или ученик спросил в чате канваса, отвечает учитель обычным ходом — в чате, не в доске (WP21.5 п.4);
- строки канваса в разговоре учителя берутся из событий `canvas.line_committed` / `canvas.line_erased` / `handwriting.corrected` с номерами (WP14.3, WP21.6), не из документа доски.

Полей пометки и подсказки коду B не нужно. Если появится место, где ход учителя кладёт визуализацию или каркас на доску, это пробел ТЗ (WP21.1 называет «визуализации, каркасы» в слое учителя, но не называет писателя), и B вернёт вопрос, а не решит сам.

**D-A-110 п.4 (описание гипотезы заблуждения).** Отдельного правила не нужно, таблица A верна. `Т-§9.3`: новое заблуждение создаётся как `suspected`; описание (`statement`, `triggers`) пишется «при подтверждении и при каждом новом проявлении подтверждённого»; WP16.2: задача сначала читает статус и завершается, если заблуждение не подтверждено. Гипотеза словами подтверждённой быть не может, поэтому `misconception.describe` по ней всё равно завершилась бы сразу. После того как проектор создаст узел, следующие проявления ссылаются на его id (метка в контексте, `Т-§4.5`). Событие с `misconception_id`, которое переводит заблуждение в подтверждённое, само ставит `misconception.describe` по строке таблицы.

**D-A-110 п.7 (`agent.requested {kind: known_check}`).** Пишет код хода учителя (B, WP13.2, шаг `commit`) из `p3_markup.agentRequests` (`AgentRequestKind` включает `known_check`, WP16.6). Например, ученик сказал в чате «я это уже знаю», и учитель просит проверку темы (`params.topic`). Задача нужна, и это `check.known_claim`: в §6.5 вида `agent.known_check` нет, а `check.known_claim` делает ровно эту работу (1–3 задачи по навыкам темы через `task_generator`, итог — `agent.completed {kind: known_check, task_ids}`, WP8.2). Предлагаемая строка таблицы S6: `agent.requested`, `kind = known_check` → `check.known_claim`, класс P1 при `needed_in_session`, иначе P2 (WP16.6), `lock_key`/`coalesce_key` — как у строки `known.claimed`. Решение класса B для A (таблица S6 — файл A).

### D-B-145. Тело `check.model`: вход ролей вердикта, метки, порядок второго мнения и прочтения
- Класс: B
- WP / место: WP11.6, `quack/practice/model_check.py` (`verdict_role`, `verdict_inputs`, `check_with_model`, `record_verdict`)
- Контекст: `Т-§6.8`, `Т-§7.7`, `Т-§22.7` и контракты `verdict_free@1`, `verdict_proof@1`, `second_opinion@1` (#84) задают роли, блоки входа и выход. Не названо: (а) вид рубрики и списка заблуждений во входе; (б) рубрики нет ни в пространстве решения, ни в спецификации; (в) порядок второго мнения и понижения уверенности распознанного ответа (WP11.7); (г) ключи идемпотентности вызовов.
- Решение: (а) рубрика — `R1. …`, `R2. …` из ключевых шагов пространства решения, иначе из `key_ideas`; заблуждения — `M1. …` в порядке, который даёт вызывающий; `answer_spec` — JSON спецификации без пустых полей; ответ — `value` и рассуждение `text` с новой строки. (б) Пустой список — блок `none`, модель сверяет со спецификацией. (в) Решение о втором мнении — по уверенности самой модели; понижение по распознаванию (D-B-127) применяется последним: неуверенное прочтение лечится показом прочтения, а не второй моделью. (г) `check.model:{answer_seq}:{part}` и `second_opinion:{answer_seq}:{part}` — повтор задачи берёт ответ из исходящих шлюза. Неизвестная метка `R…`/`M…` возвращается модели через `check` шлюза (`Т-§4.5`); что осталось неизвестным после исправления, `model_verdict` отбрасывает. Регистрация обработчика `check.model` — с диспетчером Фазы 4 (A, WP7.1, G2): тело принимает `Db`, шлюз и факты памяти (`LevelFact` → `LevelState`, заблуждения навыков — `KnownMisconception`) от вызывающего.
- Почему: §0.4.3 п.2 (`Т-§6.8`: «рубрика — ключевые шаги … или ключевые идеи»; `Т-§7.7`: «при сомнении» — сомнении вердикта), п.5.
- Обратимость: одна функция входа и порядок двух строк.
- Тесты: `tests/practice/test_check_model.py`.
- Требует подтверждения владельцем: нет
- Открыто: рисунок (`drawing`) идёт в `verdict_free` текстом `value`. Изображения в запросе шлюз пока не передаёт (`Т-§6.8` «Spark с изображением»); нужен вход-изображение в `generate_structured` (B, WP10.2) — до него ответ-рисунок проверяется по описанию. У `MisconceptionFact` (S4) нет формулировки заблуждения — для `KnownMisconception.statement` нужна она (вопрос A).

### D-B-146. Тело страховки `check.symbolic`: чтение `core.events` B и ответ `unsupported`
- Класс: B
- WP / место: WP11.3, `quack/practice/symbolic_job.py` (`insure_symbolic`), `quack/practice/repo.py`
- Контекст: WP11.3 — страховка ищет вердикт по `verdict:{answer_seq}:{part}`, иначе проверяет с `symbolic_background_timeout_ms` и пишет вердикт; «не разобралось или не набралось точек» — `check.failed`. A ответил на D-B-122: чтения `core.events` B пишет в своих модулях. Не названо: что пишет страховка, если compute ответил `unsupported` (нет структурной проверки вида, `Т-§6.6`), — в `CheckFailedReason` каталога такого значения нет.
- Решение: чтения по ключу и по `seq` — `quack/practice/repo.py` (параметры `%(name)s`, фильтр `learner_id`, `T-DB2`, `T-DB4`). `NotYet` (таймаут, compute недоступен, D-B-126) страховка пишет как `check.failed` с той же причиной под `check_failed:{answer_seq}:{part}`. `unsupported` → `NeedsModel`: страховка не пишет ничего, пока в каталоге нет причины, — модель такой ответ сейчас не проверит. **Вопрос A:** добавить `unsupported` в `CheckFailedReason` (`quack/events/values.py`); тогда страховка пишет `check.failed {reason: unsupported}`, и диспетчер ставит `check.model` (`Т-§6.6`: «нет её — проверка моделью»).
- Почему: §0.4.3 п.1 (без изменения каталога в чужом файле), п.3.
- Обратимость: одна ветка в `insure_symbolic`.
- Тесты: `tests/practice/test_check_symbolic_job.py`.
- Требует подтверждения владельцем: нет

### Поток C

### D-C-101. Имена рабочих веток
- Класс: C
- WP / место: §7.4, ветки git
- Контекст: §7.4 задаёт интеграционную ветку `phase-4` и рабочие `phase-4/c-<тема>`. Git не
  может держать ветку `phase-4` и ветки `phase-4/…` одновременно (конфликт ссылок: `phase-4` —
  файл, `phase-4/` — каталог). В `origin` уже есть `phase-4`, `phase-4-a`, `phase-4-b`, `phase-4-c`.
- Варианты: (1) рабочие ветки `phase-4-c-<тема>`, как в Фазе 3 (`phase-3-c-…`);
  (2) переименовать интеграционную ветку; (3) работать только в `phase-4-c`.
- Решение: (1) — `phase-4-<поток>-<тема>`, PR в `phase-4`.
- Почему: §0.4.3 п.3 и п.7 — интеграционная ветка и уже созданные ветки не меняются,
  соглашение Фазы 3.
- Обратимость: имя ветки, ничего в коде.
- Тесты: нет (процесс).
- Согласование потоков (шов, §0.4): B согласен (2026-11-02, работает в `phase-4-b`, PR #72);
  A согласен (2026-11-02, ревью #74).
- Требует подтверждения владельцем: да — **подтверждено** 2026-11-02: владелец поручил B решать по ТЗ и
  техдоку («у нас пока никаких данных учеников нет. остальные решения если за мной какие есть - сверься с тз и тз доком, дай решение»); решение B — в пользу (1). A согласен (ревью #74).

#### Состояние пакетов потока C

| Пакет | Состояние | Тесты |
| :-- | :-- | :-- |
| S1 (зона C), этап I | интерфейсы `ObjectStore`, `EmbeddingClient`, `EmailSender`, `DeletionJournal`; поля `AppResources`; подмены; имена параметров §6.7 потока C. Продовые клиенты — `NotImplementedError` (WP18–WP20, WP25) | `tests/storage/test_s1_resources.py` — 8 passed |
| S10, этап I + пул | `compute`: пул `pebble` (`quack_compute/pool.py`) с жёстким таймаутом — реализован; настройки, схемы и маршруты WP24 — тела `NotImplementedError`; `Renderer` (Chromium) — этап I. `backend`: `ComputeClient` — методы всех эндпоинтов WP24, `create_compute_client`; заглушка — очереди по эндпоинтам | `compute/tests/test_pool_and_contract.py` — 4 passed (`T-CM1` зелёный; в Linux, весь `compute` — 9 passed); `tests/storage/test_compute_client_s10.py` — 4 passed |
| S13 (реализация подмен) | `tests/support/llm.py`: `ScriptedLLMProvider.stream_structured` — шаги с инструментами (`script_tools`, два вызова за шаг, `phase: commentary`), ответ дельтами с ключами по алфавиту, флаг `body_before_head`, сбои Фазы 3 по D-B-125 п.5, журнал `stream_calls`; `loadtest/meta_mock.py`: SSE при `stream: true` (D-B-125 п.3), после `function_call_output` на каждый вызов — ответ. Формат — D-B-125 (B, PR #86) | `tests/test_support_scripted_llm.py` — 21 passed; `tests/test_meta_mock.py` — 59 passed |
| WP18, библиотека | `quack/auth/`: ссылка по почте (128 бит, в базе хэш, одно погашение, `auth_link_ttl_min`), `LinkLimiter` (Redis, без него — локально), сессии (`core.auth_sessions`, хэш, отзыв, срок), параметры cookie, ученик по подтверждённому адресу Google, согласия событиями. `FakeOIDC` в `tests/support/oidc.py`. **Не сделано (этап II, часть 2):** маршруты `/auth/*`, `/v1/me`, `/v1/consents`, `PATCH /v1/learner/settings`; `AuthlibGoogleOIDC`; замена входа Фазы 3 (JWT, `auth.users`) на сессии во всех роутерах; коды `UNAUTHENTICATED`, `CONSENT_REQUIRED`; `T-AU5` | `tests/auth` — 7 passed (Linux, инфраструктура) |
| WP18, маршруты | `quack/auth/router.py`: `POST /auth/link`, `GET /auth/link/verify`, `GET /auth/google/start`, `GET /auth/google/callback`, `POST /auth/logout`, `GET /v1/me` (с параметрами клиента §6.7), `PATCH /v1/learner/settings` (часовой пояс), `POST /v1/consents`, `DELETE /v1/consents/research`; основание API `quack/api/auth.py`: `get_current_session`, `require_terms` (для старта сессии, B), кука `quack_session`; коды `UNAUTHENTICATED`, `CONSENT_REQUIRED`; `EmailUnavailable` → `SERVICE_UNAVAILABLE`. **Не сделано:** перевод `get_current_learner_id` всех роутеров на сессии и удаление `/v1/auth/register|login` (D-C-112, ждёт согласия A на правку `quack/domains/router.py`, `quack/domains/auth.py`); `AuthlibGoogleOIDC` (настоящий Google, нужен клиент Google OIDC — действие владельца) | `tests/auth` — 14 passed (Linux, инфраструктура); `test_app_assembly.py` + `test_contracts.py` — 26 passed |
| WP20.1, WP20.5 (библиотека) | `quack/materials/library.py`: загрузка (тип по содержимому, объект, затем строка `content.materials` и `material.uploaded` одной транзакцией), список материалов домена, карточка с текстом страниц и подписанными ссылками; `quack/materials/search.py`: полнотекстовый поиск по событиям тем же выражением и типами, что индекс WP1.1. **Не сделано:** маршруты (с переводом входа на сессии, D-C-112; загрузка multipart — `python-multipart` добавлен по решению владельца, D-C-113), WP20.2 (ждёт очередь A, `builder` B, слой 2 `material_parser`), WP20.3 (Modal — действия владельца), WP20.4 (ждёт узлы кусков в графе, проектор A) | `tests/materials` — 4 passed (`T-MT5`; Linux, инфраструктура) |
| WP21.2, журнал штрихов | `quack/canvas/strokes.py`: формат куска (MessagePack + zstd, точки разностью, стирание — операция), `StrokeJournal` (пачки в памяти, кусок раз в `stroke_chunk_seconds`, `ack` только после записи, повтор `batch_no` отсекается, хранилище недоступно — `ack` нет). **Не сделано:** WebSocket и Redis pub/sub (с переводом входа на сессии, D-C-112), доска WP21.1, распознавание WP21.3, проверка шагов и пометки WP21.4–21.5, голос и проигрывание WP21.6 | `tests/canvas` — 4 passed (`T-CV1`, `T-CV2`) |
| S1: поле `db` (после #78) | `AppResources.db: Db` (§4.2): `create_app_resources` стала асинхронной и открывает пул `Db` без ожидания Postgres — API стартует и `/health/ready` отвечает 503 без базы (контракт готовности Фазы 3; `open_db` A ждёт пул — это для workers); закрывается последним. `engine` и `session_factory` остаются до WP1.3 (A). `tests/support/resources.build_app_resources(..., db=)`: без `db` — `Db` над закрытым пулом (`PoolClosed` при обращении) | `tests/storage/test_s1_resources.py`, `tests/test_api_llm_provider.py`, `tests/test_app_assembly.py` — 30 passed (Linux, инфраструктура) |
| WP24 | `compute`: `/v1/pdf/pages` (PyMuPDF), `/v1/image/align`, `/v1/image/clean-drawing`, `/v1/image/render-strokes` (OpenCV), `/v1/render/pdf` (Playwright, A4, число страниц); Chromium запускается на первое задание и закрывается после `chromium_idle_close_s` простоя; образ с Chromium, `TMPDIR=/srv/quack/tmp`; шаг Chromium в CI. `/v1/render/snapshots` по D-B-130. **Не сделано:** почасовая чистка `/srv/quack/tmp` (вопрос, см. D-C-110) | `compute` в Linux — 76 passed (`T-CM1`, `T-CM2`, `T-CM3`) |
| WP19 | `quack/storage/keys.py` — ключи `Т-§3.3` с ULID; `quack/storage/uploads.py` — тип по сигнатуре (PDF, PNG, JPEG, WebP), лимит `upload_max_mb`, `UploadRejected` 415/413; `S3ObjectStore` на `aioboto3` (path-style, подписанные ссылки, сбой → `StorageUnavailable`); `UPLOAD_REJECTED` и `StorageUnavailable` → `SERVICE_UNAVAILABLE` в `quack/api/errors.py`; снимок `openapi.json`. Эндпоинты загрузки — WP20 (материалы), WP22 (фото): там же вторая половина `T-ST3` («ход учителя работает») | `tests/storage/test_storage_wp19.py` — 12 passed (`T-ST1`, `T-ST2`, `T-ST3` — часть хранилища) |
| S10: клиент math (WP24, по просьбе B) | `quack/compute_client/math_contracts.py` — копия `compute/quack_compute/math/schemas.py` (B); `ComputeClient.math_check`, `math_transition`, таймаут HTTP — `timeout_ms / 1000 + compute_timeout_sec`; очереди заглушки `/v1/math/check`, `/v1/math/transition`. `/v1/check/math` Фазы 3 остаётся до перевода `quack.practice` (WP11.3, B) | `tests/storage/test_compute_client_math.py` — 6 passed |

### D-C-102. Где живут `EmailSender` и `DeletionJournal`
- Класс: B
- WP / место: S1, S9; `quack/api/email.py`, `quack/storage/deletions.py`
- Контекст: §4.2 называет ресурсы, §4.1 и §6.9 — пакеты, но не место этих двух интерфейсов.
  `AppResources` лежит в основании API и может импортировать только ядро и основание API (§4.1);
  `quack/auth` — продуктовый пакет; `quack/deletion/**` — зона A, а `DeletionJournal` выдаёт C (S9).
- Варианты: (1) `EmailSender` — `quack/api/email.py`, `DeletionJournal` — `quack/storage/deletions.py`;
  (2) новый пакет ядра на каждый клиент; (3) интерфейсы в `quack/auth` и `quack/deletion`.
- Решение: (1). Конструкторы `create_*` — рядом с классами, чтобы `quack/runtime` (A) вызывал их
  для `JobContext` (§7.3 п.6) без импорта `quack.api.resources`.
- Почему: §0.4.3 п.3 и п.5 — слои §4.1 соблюдены, новых пакетов сверх §6.9 нет; `DeletionJournal` —
  тоже S3 API (R2), как `ObjectStore`.
- Обратимость: перенос модуля и импорты.
- Тесты: `T-A6` (`tests/test_contracts.py`), `tests/storage/test_s1_resources.py`.
- Требует подтверждения владельцем: нет. A согласен (2026-11-02, ревью #74).

### D-C-103. Адрес R2 для журнала удалений — параметр `deletions_s3_endpoint`
- Класс: B
- WP / место: S9, `quack/config.py`
- Контекст: `Д-§7` даёт `DELETIONS_S3_ACCESS_KEY`/`SECRET_KEY` для `api`, `workers`, `backup`, но не
  эндпоинт; `BACKUP_S3_ENDPOINT` есть только у `backup`. Контракт `Д-§7`: несекретные адреса — в
  конфиге окружения.
- Варианты: (1) несекретный параметр `deletions_s3_endpoint`; (2) отдать `api`/`workers` секрет
  `BACKUP_S3_ENDPOINT`.
- Решение: (1), значение — из конфига окружения при выкатке (WP9).
- Почему: §0.4.3 п.2 (буква `Д-§7`: адреса — в конфиге) и п.4.
- Обратимость: один параметр.
- Тесты: `test_production_clients_and_doubles_implement_the_interfaces`.
- Требует подтверждения владельцем: нет

### D-C-104. Имена параметров отправителя письма и redirect URI Google
- Класс: B
- WP / место: WP18.1–18.2, `quack/config.py`
- Контекст: значения есть (`login@qvack.online` — `Т-§19.1`, `Д-§3.1`;
  `https://api.qvack.online/auth/google/callback` — `Д-§3.1`), имён параметров в §6.7 нет.
- Решение: `auth_email_from`, `google_oidc_redirect_url` со значениями документов.
- Почему: §0.3 — адреса в `Settings`, не в коде. Обратимость: имя параметра.
- Тесты: WP18 (`T-AU1`, `T-AU3`).
- Требует подтверждения владельцем: нет

### D-C-105. Параметры без значений в документах — `None`
- Класс: B
- WP / место: §6.7, `quack/config.py`
- Контекст: §6.7 называет `auth_success_redirect_url` и `terms_version`, но значений нет ни в
  §6.7, ни в `Т-§21.3`, `Т-§22.11`, `Д-§14.1`.
- Варианты: (1) `None` до значения владельца, потребитель явно отказывает; (2) придумать значения.
- Решение: (1). `terms_version` — версия текста согласия (продукт, владелец); без
  `auth_success_redirect_url` вход не завершает редирект.
- Исправление 2026-11-02 (по поручению владельца решать по ТЗ и техдоку, передал B): `stroke_batch_ms` 300, `line_pause_ms` 1200,
  `capture_still_ms` 700 в документах есть — таблица `Т-§21.3` (строки §15.2, §15.3, §16.2);
  в первой версии записи ошибочно отнесены к пробелам, в `Settings` теперь эти значения.
- Почему: закон 8 «отсутствие — не ноль», §0.4.3 п.2. Обратимость: значение параметра.
- Тесты: WP18 (`T-AU1`, `T-AU6`).
- Требует подтверждения владельцем: да — нужны значения `terms_version`,
  `auth_success_redirect_url`

### D-C-106. Ключ Modal и у `api`
- Класс: C
- WP / место: S1, S12; `_PROD_SECRETS_BY_ROLE` (WP9.2, `T-OPS6`)
- Контекст: `Д-§7` выдаёт `MODAL_TOKEN_ID`/`SECRET` только `workers`. ТЗ §4.2 даёт
  `EmbeddingClient` и `api`; `Д-§3.2` пускает `api` в Modal; `Т-§10.5` и S12: `embed_query` для
  поиска по свободному запросу (инструмент учителя в `api`, `GET /v1/search`).
- Варианты: (1) ключ у `api` и `workers`; (2) `api` ставит поиск задачей в `workers`
  (ход учителя ждал бы фон — закон 9).
- Решение: (1). В этапе I ключи — только поля `Settings`; требование секрета по роли — в WP9.2.
- Почему: §0.4.1 — `Т-§` выше `Д-§`; `Д-§3.2` согласуется; закон 9.
- Обратимость: строка таблицы ролей.
- Тесты: `T-OPS6` (WP9).
- Требует подтверждения владельцем: да — **подтверждено** 2026-11-02, вариант (1): по поручению владельца
  решать по ТЗ и техдоку («у нас пока никаких данных учеников нет. остальные решения если за мной какие есть - сверься с тз и тз доком, дай решение»), решение передал B.

### D-C-107. Контракт эндпоинтов compute WP24 и таймаут задания
- Класс: B
- WP / место: WP24, шов S10; `compute/quack_compute/contracts.py`, `backend/quack/compute_client/contracts.py`, `Settings.compute_task_timeout_s`
- Контекст: WP24 называет эндпоинты и что они делают, но не схемы и не таймаут задания;
  `Д-§3.2`: compute без сети, файл — в теле запроса, результат — в ответе.
- Варианты: (1) JSON с base64 для двоичных данных, одна схема на эндпоинт; (2) сырой двоичный
  запрос и `multipart`-ответ.
- Решение: (1). Схемы — минимальные поля из WP20.2, WP21.3, WP22.3, `Т-§13.6`, `Т-§17.6`:
  `pdf/pages` → страницы (номер, текст, WebP); `image/align` → `aligned` и WebP; `image/clean-drawing`
  (изображение и маска `segmenter`) → WebP; `image/render-strokes` (штрихи в координатах доски,
  размер) → WebP; `render/snapshots` (HTML, наборы параметров) → снимок, ошибки консоли, `blank`;
  `render/pdf` (HTML) → PDF и `page_count`. Таймаут задания — `compute_task_timeout_s` = 60 с в
  compute и backend (документы не называют; консервативно — дольше), задание сверх него убивается,
  ответ 504 → `ComputeJobTimeout`; клиент ждёт `compute_task_timeout_s + compute_timeout_sec`.
  Рендер — в процессе сервиса (`Renderer`, один Chromium с закрытием по простою), не в пуле.
- Почему: §0.4.3 п.5 (одна форма для всех эндпоинтов, без новых зависимостей), п.4.
- Обратимость: схема одного эндпоинта, один параметр.
- Тесты: `T-CM1`, `test_wp24_endpoints_are_declared`, `tests/storage/test_compute_client_s10.py`;
  `T-CM2`, `T-CM3` — с реализацией WP24.
- Требует подтверждения владельцем: нет

### D-C-108. Подмены S13: идентификаторы шагов, размер дельты, журнал
- Класс: B
- WP / место: шов S13, §8.1, WP26.2; `tests/support/llm.py`, `backend/loadtest/meta_mock.py`
- Контекст: D-B-125 задаёт формат элементов, событий и сбоев, но не размер куска текста, не вид идентификаторов в `ScriptedLLMProvider` и не то, как вызов попадает в журнал.
- Решение: (1) текст ответа идёт кусками по `STREAM_DELTA_CHARS` = 16 символов (в обеих подменах; тесты проверяют только, что кусков больше одного и что они склеиваются в ответ); (2) в `ScriptedLLMProvider` идентификаторы детерминированы: `call_{schema}_{шаг}_{n}`, `fc_…`, `rs_…`, `msg_…`. Номер шага считается по входу (сколько шагов сценария закрыты `function_call_output`), а не по порядку вызовов. Поэтому параллельные задачи e2e не мешают друг другу (§8.1, как выбор ответа по `schema_name`). `function_call` из входа без `function_call_output` — `AssertionError`; (3) весь `StreamRequest` пишется в `stream_calls`, его `base` — ещё и в `calls`, чтобы `calls_for` считал все вызовы роли; (4) при `commentary_only` поток содержит только элемент-комментарий, при `incomplete` — только дельты, а на шаге с инструментами — только `StreamCompleted(status="incomplete")` без `function_call`, повтор того же шага отдаёт вызовы; `invalid_json` на шаге с инструментами не берётся и срабатывает на шаге ответа (D-B-125 п.5, замечание B к #87); в остальных шагах первым идёт элемент `reasoning`; (5) `meta-mock` с `tools` отвечает на шаг, где во входе есть `function_call_output` на каждый `function_call`, иначе — шаг с вызовами, как в Фазе 3. Задержка профиля `measured` — целиком до начала потока.
- Почему: §0.4.3 п.5 (без новых зависимостей и параметров `Settings` — это подмены тестов), D-B-125 п.2.
- Обратимость: константы и вспомогательные функции подмен.
- Тесты: `tests/test_support_scripted_llm.py` (`test_stream_*`), `tests/test_meta_mock.py` (`test_stream_*`).
- Требует подтверждения владельцем: нет

### D-C-111. WP18: имя cookie, окно лимитов, ключ согласия, адрес ссылки
- Класс: B
- WP / место: WP18; `quack/auth/links.py`, `quack/auth/sessions.py`, `quack/auth/consents.py`
- Контекст: `Т-§19.1` и WP18 называют флаги и домен cookie, лимиты «в час», события согласия и путь `GET /auth/link/verify`, но не имя cookie, вид окна лимита, ключ идемпотентности согласия и базовый адрес ссылки в письме.
- Решение: (1) cookie `quack_session`; (2) окно лимита — календарный час: счётчики `auth:link:{email|ip}:…:{час}` в Redis с `EXPIRE 3600`, без Redis или при его ошибке — локальные (`Д-§10`); `retry_after` — до конца часа; (3) ключ идемпотентности согласия берётся из запроса (`Idempotency-Key`, как у мутирующих эндпоинтов Фазы 3): согласие, данное снова после отзыва, — новое событие, а ключ из вида и версии его бы схлопнул (закон 5); (4) ссылка в письме — абсолютный адрес `GET /auth/link/verify`, который роутер строит из запроса, без нового параметра; (5) адрес приводится к нижнему регистру (`core.learners.email` с `CHECK (email = lower(email))`). (6) Изоляция (`tests/db/test_sql_static.py`, A): все запросы `quack.auth` берут `%(learner_id)s`, кроме двух запросов до входа, где ученик ещё неизвестен: `quack/auth/links.py:_LEARNER_BY_EMAIL` (ученик по адресу) и `quack/auth/sessions.py:_SESSION_BY_TOKEN` (сессия по хэшу токена). Нужны записи в `CROSS_LEARNER_ALLOWED` — запрос к A. Выход (`revoke_session`) отзывает только сессию своего ученика.
- Почему: §0.4.3 п.5 (без новых параметров), закон 5.
- Обратимость: константа и одна функция.
- Тесты: `tests/auth/test_auth_wp18.py`.
- Требует подтверждения владельцем: нет.

### D-C-112. Перевод входа API с JWT на сессии (WP18.3) — предложение потокам A и B
- Класс: B (пересечение зон, §7.3) — **ждёт ответа A и B**
- WP / место: WP18.3, WP18.4; `quack/api/auth.py` (C), объявления в роутерах A и B
- Контекст: §2.3 строка 3 удаляет пароль, JWT, `auth.users`, `/v1/auth/register|login`; WP18.3 — `learner_id` только из сессии. На входе Фазы 3 (`get_current_learner_id`) сидят роутеры всех потоков: A — `quack/domains/router.py`; B — `quack/session/deps.py`; C — `quack/artifacts/router.py`, `quack/api/learner_stream.py`, `quack/api/ratelimit.py`. Токены JWT выпускают тесты: A — `tests/domains/*` (8 файлов); B — `tests/session/*` (5); корневые `test_app_assembly`, `test_dispatcher`, `test_jobs_phase3`, `test_learner_stream`, `test_loadtest_scenario`, `test_neo4j_outage`, `test_ops_phase3`; C — `tests/artifacts/conftest.py`, `tests/e2e/system.py`, `tests/support/auth.py`.
- Предложение:
  1. `quack.api.auth.get_current_learner_id` сохраняет имя и подпись (возвращает `UUID`), но читает cookie сессии (`quack.auth.sessions.resolve_session`); нет или отозвана — 401 `UNAUTHENTICATED`. **Код роутеров A и B не меняется.**
  2. Тестовый вход: `tests/support/auth.py` получает `login(client, db, learner_id)` — строка `core.auth_sessions` и cookie на клиенте; `ensure_users_hook` и выпуск JWT уходят. Тесты A и B меняют только способ входа (одна строка на клиент). C делает это одним PR с ревью A и B (§7.3); если A или B хотят править свои тесты сами — тот же хелпер, их PR после PR C.
  3. `CONSENT_REQUIRED` на старте сессии (WP18.4): зависимость `quack.auth.require_terms` (C) объявляется на `POST` старта сессии в `quack/session/router.py` (B) — в чужом роутере только объявление (§7.3 п.3).
  4. Удаление `auth.users` и старой миграции — в WP1.3 (A), не здесь.
- Нужно: A — согласие с п.1, п.2 для `tests/domains` и корневых тестов A, п.4; B — согласие с п.2 для `tests/session` и с п.3.
- Требует подтверждения владельцем: нет (решение потоков); значения `terms_version`, `auth_success_redirect_url` — по-прежнему за владельцем (D-C-105).

### D-C-110. WP24: числа обработки изображений, разрешение страниц PDF, чистка временных файлов
- Класс: B
- WP / место: WP24; `compute/quack_compute/work.py`, `compute/quack_compute/renderer.py`, `compute/Dockerfile`
- Контекст: WP24, WP20.2, WP21.3, WP22.3, `Т-§17.6` называют, что делает каждый эндпоинт, но не числа: разрешение страниц PDF, качество WebP, пороги поиска контура листа, толщину линии пера; `Д-§4.2` говорит «чистится по возрасту раз в час», но не называет возраст и не говорит, кто чистит.
- Решение: (1) страница PDF — разрешение PyMuPDF по умолчанию, WebP — качество OpenCV по умолчанию; (2) контур листа — обычный приём OpenCV: размытие 5, Canny 75/200, приближение многоугольником с точностью 0,02 периметра, лист — самый большой четырёхугольник не меньше 0,2 площади снимка; иначе снимок как есть (`aligned = false`). Числа — именованные поля `ComputeSettings` (`align_*`, `stroke_thickness_px`, переменные окружения — их имена заглавными) по ТЗ Ф4 §0.3, по замечанию B к #92; (3) фон рисунка — порог Оцу (без числа), прозрачно всё вне маски `segmenter`; (4) линия пера — 2 px; (5) PDF — формат A4 Chromium; (6) почасовая чистка `/srv/quack/tmp` **не сделана**: удалить профиль работающего Chromium — сломать рендер, а возраст файлов документ не называет. Вопрос владельцу: чистит compute сам или cron хоста (WP9), и какого возраста файлы.
- Почему: §0.4.3 п.5 (значения библиотек по умолчанию, где документ молчит), `Т-§1.2`.
- Обратимость: значения `ComputeSettings`.
- Тесты: `compute/tests/test_wp24_endpoints.py`.
- Снимки визуализаций (по D-B-130): набор задаётся `add_init_script("window.QUACK_VIZ_PARAMS = …")`, но страница открывается не через `set_content` (у Playwright скрипты инициализации выполняются при переходе, а не при `set_content` — проверено тестом), а переходом на внутренний адрес `http://viz.quack.internal/`, который `page.route` отдаёт из памяти — без сети. Для модели и для B ничего не меняется: переменная задана до любого скрипта страницы. Ошибки консоли — сообщения `console.error` и неперехваченные исключения страницы; `blank` — все пиксели снимка одного цвета.
- Требует подтверждения владельцем: да — п.6 (чистка временных файлов). \[ПРОВЕРИТЬ\] п.1–2 на настоящих сканах и фото листов при WP20, WP22.

### D-C-109. WP19: ULID, регион и повторы S3-клиента, код ошибки загрузки
- Класс: B
- WP / место: WP19; `quack/storage/keys.py`, `quack/storage/uploads.py`, `quack/storage/objects.py`, `quack/api/errors.py`
- Контекст: `Т-§3.3` требует случайную часть ключа «например ULID», библиотеки для неё в §4.6 нет; `Д-§8.4` не называет регион бакета и таймауты клиента; ТЗ Ф4 §4.5 даёт `UPLOAD_REJECTED` 415/413 без разбивки.
- Решение: (1) ULID — на стандартной библиотеке (48 бит миллисекунд + 80 случайных, Crockford base32), как Левенштейн в §4.6. ULID стоит в ключах, которые пишутся больше одного раза на id (штрихи, фото, кропы, экспорт, визуализации, миниатюры). `materials/{id}/original.{ext}` и `pages/{n}.webp` — ровно по раскладке `Т-§3.3`: id материала новый на каждую загрузку. (2) Регион, таймауты и повторы клиента — значения botocore по умолчанию: документы их не называют. (3) Неверный тип → 415, сверх `upload_max_mb` → 413. `detect_upload` принимает набор допустимых видов эндпоинта: фото канваса — только WebP (`Т-§22.6`). (4) `put` без условной записи (`If-None-Match`): поддержка на Contabo не проверена, неизменяемость держится на случайной части ключа. (5) Нет ключа при `get` — `KeyError`, как у подмены. Сеть, таймаут, 5xx → `StorageUnavailable` → `SERVICE_UNAVAILABLE` «file storage temporarily unavailable».
- Почему: §0.4.3 п.5 (без новых зависимостей и параметров), `Т-§20.7`.
- Обратимость: одна функция или один аргумент конфигурации клиента.
- Тесты: `tests/storage/test_storage_wp19.py`.
- Требует подтверждения владельцем: нет. \[ПРОВЕРИТЬ\] до первых загрузок (`Д-§8.4` «Проверить»): регион бакета Contabo для подписи, работа подписанных ссылок в path-style. Недоступное хранилище отвечает не сразу: botocore повторяет запрос со своей задержкой (в тесте на Windows — до ~18 с на вызов). Таймаут и число повторов — вопрос владельцу.

### D-C-113. WP20.1, WP20.5: проверка домена, статус материала, multipart, размер выдачи поиска
- Класс: B; п.3 — класс C (зависимость)
- WP / место: WP20.1, WP20.5; `quack/materials/library.py`, `quack/materials/search.py`
- Контекст: WP20.1 называет `POST /v1/domains/{id}/materials` (multipart), строку, событие и одну транзакцию, но не то, как проверить домен, какие значения у `content.materials.status`, и чем разбирать multipart; WP20.5 не называет размер выдачи.
- Решение: (1) домен ученика проверяется по `domain.created` в журнале (закон 1): таблицы доменов в Postgres нет, а `quack.graph.read` (S4) ещё не готов; после S4 — через него. (2) Статус после загрузки — `uploaded`; следующий ставит разбор WP20.2. (3) **Multipart:** FastAPI разбирает формы через `python-multipart`, его нет в §4.6 и в зависимостях. Варианты: добавить `python-multipart` (стандартная зависимость FastAPI для форм) или принимать файл телом запроса с `Content-Type` (отступление от «multipart» в WP20.1). **Решение владельца 2026-11-02:** добавить `python-multipart` («конечно ставь тогда»); отдельный коммит, строка R4-C1 в реестре отклонений. (4) Размер выдачи полнотекстового поиска — аргумент `limit` функции; число задаёт маршрут, и оно будет вопросом при маршрутах — в документах его нет. (5) Маршруты WP20 делаются вместе с переводом входа на сессии (D-C-112), чтобы не писать их на JWT Фазы 3.
- Почему: §0.4.3 п.5, закон 1, §4.6.
- Обратимость: одна функция проверки домена; одно значение статуса.
- Тесты: `tests/materials/test_materials_wp20.py`.
- Требует подтверждения владельцем: п.3 — подтверждено 2026-11-02.

### D-C-114. WP21.2: структура куска штрихов, отсечение повторов, порог переполнения
- Класс: B; п.3 — вопрос владельцу
- WP / место: WP21.2; `quack/canvas/strokes.py`
- Контекст: `Т-§15.1`–`Т-§15.2` и WP21.2 задают формат точек (`dx, dy, dt, нажим`), MessagePack, zstd, кусок раз в `stroke_chunk_seconds` «или при переполнении», `ack` после записи и отсечение повтора по номеру пачки; не названы структура документа куска и порог переполнения.
- Решение: (1) кусок — `{"batches": [{"batch_no", "strokes": [{"stroke_id", "points"}], "erasures": [{"stroke_ids", "at_ms"}]}]}`; первая точка штриха абсолютная, следующие — разностью; номер пачки хранится в куске для проигрывания. (2) Отсечение повторов — множество виденных `batch_no` журнала канваса в процессе API; ключ куска — `canvas_chunk_key` с ULID, поэтому два процесса не перезапишут кусок друг друга. (3) **Порог переполнения** документы не называют: сейчас кусок пишется по времени и при закрытии сокета (`flush`). Вопрос владельцу: нужен ли порог (число точек или байт) и какое значение — тогда это новый параметр `Settings`.
- Почему: §0.4.3 п.5, `Т-§3.3`.
- Обратимость: одна функция кодирования (у куска нет потребителей, кроме проигрывания).
- Тесты: `tests/canvas/test_strokes_wp21.py`.
- Требует подтверждения владельцем: п.3.

### D-C-115. WP18: маршруты входа, слои, ответы
- Класс: B
- WP / место: WP18; `quack/auth/router.py`, `quack/api/auth.py`, `quack/api/app.py`
- Контекст: §6.4 называет маршруты входа, WP18 — их смысл; не названы коды ответов, хранение `state` для Google, поведение без `auth_success_redirect_url` (D-C-105), и как зависимость сессии попадает в роутеры других потоков при запрете импорта между продуктовыми пакетами (§4.1).
- Решение: (1) **Слои.** Зависимости `get_current_session` и `require_terms` и кука `quack_session` — в основании API (`quack/api/auth.py`), функции продукта `quack.auth` (`resolve_session`, `has_current_terms`) подставляет сборка через `app.state`. Поэтому B объявляет `Depends(require_terms)` из `quack.api.auth`, а не из `quack.auth` (импорт `quack.session` → `quack.auth` запрещён §4.1). (2) Ответы — модели (контракт WP8.7: у каждого маршрута один 2xx с телом): `POST /auth/link` → `{"status": "sent"}` для любого адреса; вход → 303 на `auth_success_redirect_url` с кукой, без него — 200 `{learner_id}`; выход → `{"status": "signed_out"}`; согласия → `{kind, version, given}`; настройки → `{settings}`. `GET /auth/google/start` — только редирект 302. (3) `state` Google — 128 бит в своей куке `quack_oidc_state` (те же флаги, срок `auth_link_ttl_min`); неверный `state` или неподтверждённый адрес — 401 `UNAUTHENTICATED`. (4) Лимит ссылок — 429 `RATE_LIMITED` с `Retry-After`; почта недоступна — 503 `SERVICE_UNAVAILABLE` (§4.4). (5) Часовой пояс — проверка IANA (`zoneinfo`), пишется в `core.learners.settings.timezone` без события (WP18.3 называет место — строку ученика). (6) Ключ идемпотентности согласия — в теле, как у мутирующих маршрутов Фазы 3; отзыв `research` берёт `version` из тела. (7) Маршруты на сессиях отвечают `UNAUTHENTICATED`, маршруты Фазы 3 — `UNAUTHORIZED`, пока весь API не перейдёт на сессии (D-C-112).
- Почему: §4.1, §4.5, WP8.7, §0.4.3 п.5.
- Обратимость: модели ответов и один модуль маршрутов.
- Тесты: `tests/auth/test_auth_routes.py`, `tests/test_app_assembly.py`.
- Требует подтверждения владельцем: нет.

### D-C-116. WP20.1, WP20.5: маршруты материалов и поиска на сессиях
- Класс: B
- WP / место: WP20.1, WP20.5; `quack/materials/router.py`, `quack/materials/library.py`, `tests/e2e/endpoints.py`
- Контекст: §6.4 называет `POST/GET /v1/domains/{id}/materials`, `GET /v1/materials/{id}`, `GET /v1/search`; WP20.1 — multipart с необязательным `session_id`. Не названы: ключ идемпотентности загрузки, размер выдачи и минимальная длина запроса поиска (D-C-113 п.4), ответ на список материалов чужого домена.
- Решение: (1) Вход — только кука сессии (`get_current_session`, WP18.3), не JWT Фазы 3 (D-C-113 п.5); без сессии — 401 `UNAUTHENTICATED`. (2) Загрузка — без `idempotency_key`: WP20.1 его не называет, каждая загрузка — новый материал со своим ключом `material.uploaded:{material_id}`; в обходе `T-E2` маршрут — в `NO_IDEMPOTENCY_KEY` с причиной. (3) Поиск берёт параметры полнотекстового поиска Фазы 3: `search_min_query_len`, `search_default_limit`, `search_max_limit` (те же проверки, что у `GET /v1/artifacts/search`, 422 `VALIDATION_ERROR`). (4) Список материалов чужого или неизвестного домена — 404 `NOT_FOUND`, не пустой список (`T-E3`); проверка домена — та же, что у загрузки (D-C-113 п.1). (5) Ответы: материал — `material_id, domain_id, session_id, mime, status, pages_count, created_at`; карточка — материал, `file_url`, страницы `page, text, image_url`; поиск — `hits` из `session_id, seq, type, snippet`.
- Почему: §0.4.3 п.5, §4.5, WP18.3.
- Обратимость: один модуль маршрутов.
- Тесты: `tests/materials/test_materials_routes.py`, `tests/e2e/test_isolation_and_idempotency.py` (`T-E2`, `T-E3`), `tests/test_app_assembly.py`.
- Риск перехода: домен проверяется по `domain.created` в журнале Фазы 4, а домены пока создаёт маршрут A Фазы 3 в старом журнале — загрузить материал через API можно будет, когда создание домена перейдёт на `Db` (R-W, A). Компаньон (`scope = companion`, `T-CP1` → 403) — общей проверкой в WP22, не здесь.
- Требует подтверждения владельцем: нет.

#### Ответ A: таблицы C в базовой миграции и D-A-103 (2026-11-02)

Таблицы C в `backend/db/migrations/20261102000001_baseline.sql` (`phase-4-a-wp1`, `4a75a2c`) сверены
с §6.1 по колонкам: `core.auth_sessions`, `core.auth_links`, `content.canvas_boards`,
`content.materials`, `content.material_pages`, `content.artifacts`, `content.artifact_versions`,
`content.learner_skills`, `content.exports`; плюс колонки C в `core.learners` (`email`, `settings`).
Все колонки §6.1 есть, лишних нет, `learner_id` в каждой таблице; `NULL`/`NOT NULL` по D-A-104
C подходят (`material_pages.text NOT NULL` — для страницы без текста пишется пустая строка).
Правок не нужно.

D-A-103 (две схемы до WP1.3): **C согласен** с вариантом (3). В WP9 при переходе (WP1.3) C
переключает `ops migrate`, образ (`dbmate` в `quack-backend`) и сервис `migrate` в compose на
dbmate. Сейчас нужно только одно: dbmate в CI, иначе `T-DB1`/`T-DB5` падают в job `backend` —
PR #77 (dbmate v2.36.0, sha256).

## Заблокировано

- ~~BLOCKED-B-101…108~~ — сняты 2026-11-02: слой 1 восьми ролей — черновики стенда (D-B-132).

## Красные прогоны

- WP20, маршруты (C, `phase-4-c-api-sessions`, коммит `e2fb068`): в Linux против `quack-test-*` с dbmate `pytest tests/materials/test_materials_routes.py` — 4 failed (маршрутов нет: 404 вместо 201/401/415/200). Зелёный: `tests/materials`, `tests/e2e`, `tests/test_app_assembly.py`, `tests/test_contracts.py`, `tests/db/test_sql_static.py`, `tests/auth` — 66 passed.
- WP18, маршруты (C, `phase-4-c-sessions`): тесты и роутер писались в одной итерации, красный прогон отдельно не снят. Зелёный: в Linux против `quack-test-*` — `tests/auth` 14 passed; локально `test_app_assembly.py` + `test_contracts.py` — 26 passed. `test_sql_static.py` красный до слияния #101 (записи A для двух запросов до входа).
- WP18, этап I (C, `phase-4-c-wp18`): в Linux против `quack-test-*` с `QUACK_TEST_REQUIRE_INFRA=1` и dbmate v2.36.0 `pytest tests/auth` — 7 failed (`NotImplementedError`: `request_link`, `redeem_link`, `LinkLimiter`, `cookie_params`, `learner_for_google`, сессии, согласия). Зелёный (библиотека): 7 passed. `T-AU5` — с маршрутами (весь API на сессиях).
- WP20.1, WP20.5 (C, `phase-4-c-wp20`, коммит `d161aed`): в Linux против `quack-test-*` с dbmate — `tests/materials` 4 failed (`NotImplementedError`). Зелёный: `tests/materials`, `test_contracts.py`, `tests/db/test_sql_static.py` — 15 passed.
- WP21.2, журнал штрихов (C, `phase-4-c-wp21`, коммит `79079de`): `uv run pytest tests/canvas` — 4 failed (`NotImplementedError`). Зелёный: `tests/canvas` + `test_contracts.py` — 11 passed.
- Поле `db` (C, `phase-4-c-db-field`): `uv run pytest tests/storage/test_s1_resources.py` — 3 failed (нет поля `db`; `create_app_resources` не асинхронная). Зелёный — в Linux-контейнере против `quack-test-*` с `QUACK_TEST_REQUIRE_INFRA=1` (на Windows async-psycopg не работает с Proactor-циклом pytest — `PoolTimeout`): `test_s1_resources.py`, `test_api_llm_provider.py`, `test_app_assembly.py` — 30 passed; все пользователи `build_app_resources` (`tests/session`, `tests/domains`, `tests/artifacts`, `tests/e2e`, `test_dispatcher.py`) — 281 passed (в первом прогоне один раз упал `test_mutating_endpoints_are_idempotent`, отдельно и при повторе — зелёный; на чистом `phase-4` тот же набор — 281 passed).
- WP24 (C, `phase-4-c-wp24`, коммит `c98d1b8`): в Linux (контейнер uv python3.12-bookworm-slim + `playwright install --with-deps chromium`) `pytest tests/test_wp24_endpoints.py` — 7 failed (`NotImplementedError`), 1 xfailed. Зелёный: весь `compute` — 74 passed, 1 xfailed (BLOCKED-C-201).
- WP10.5 `viz_builder@1` по D-B-130 (B): `uv run pytest tests/llm/test_labels.py` — 2 failed (`test_prompt_has_its_markers[viz_builder@1]`, устаревший `PROMPT_CONTRACTS.md`), 54 passed, коммит `1d7572d`. Зелёный: `tests/llm` — 76 passed.
- WP19 (C, `phase-4-c-wp19`, коммит `4fb10f3`): `uv run pytest tests/storage/test_storage_wp19.py` — ошибка сборки (нет `quack.storage.keys`, `quack.storage.uploads`). Зелёный: 12 passed; `tests/storage` — 29 passed; с затронутыми (`test_app_assembly.py` — снимок OpenAPI, `test_neo4j_outage.py`, `test_ratelimit.py`, `test_infra.py`, `tests/session/test_degradation_and_workers.py`, `test_contracts.py`) — 27 passed, 42 skipped (без инфраструктуры; их прогонит CI).
- WP2 (A), Этап I–II: схемы нагрузок (Этап I), шаблоны ключей — `NotImplementedError`: `pytest -q tests/events` — 2 failed (`T-EV3`), 71 passed (`T-EV1`, `T-EV2`, `T-EV5` на схемах Этапа I). Зелёный: 73 passed.
- WP1 (A), коммит `8c9fe33` (Этап I–II): `QUACK_TEST_REQUIRE_INFRA=1 python -m pytest -q tests/db` — 13 errors (`NotImplementedError` в `open_db`: все `T-DB5`), 6 passed (`T-DB1` — миграция есть с Этапа I; `T-DB2`, `T-DB4` и их самопроверки; формат `actor`). Зелёный (`phase-4-a-wp1`): 19 passed.
- S13, подмены (C, `phase-4-c-s13`, коммит `dbe6022`): `uv run pytest tests/test_meta_mock.py tests/test_support_scripted_llm.py` — `test_meta_mock.py`: 12 красных (нет SSE), 47 зелёных; `test_support_scripted_llm.py` — ошибка сборки (`ScriptedToolCall` нет). Зелёный: 80 passed; с затронутыми (`tests/llm`, `test_llm_runtime.py`, `tests/session/test_phase3_hot_path.py`) — 166 passed, 32 skipped (без инфраструктуры; их прогонит CI).
- S13, сбои на шаге с инструментами (C, замечание B к #87): `test_stream_incomplete_on_a_tool_step_has_no_calls`, `test_stream_invalid_json_waits_for_the_answer_step` на прежнем `tests/support/llm.py` — 2 красных. Зелёный: `tests/test_support_scripted_llm.py` + `tests/test_meta_mock.py` — 82 passed.
- WP10.5 лимиты (B): `uv run pytest tests/llm/test_phase4_ai_layer.py` — 1 failed (`test_role_table_matches_t111`: новые лимиты D-B-134), 9 passed.
- WP10.5 стенд (B, `phase-4-b-prompts`): `uv run pytest tests/llm/test_labels.py` — 10 failed (`test_label_map_labels_domains` — нет `domains`; `test_prompt_has_owner_doctrine` × 8 — заглушки; устаревший `PROMPT_CONTRACTS.md`), 43 passed. Зелёный: `tests/llm` — 73 passed.
- WP10.5 промпты (B, `phase-4-b-prompts`): `uv run pytest tests/llm/test_labels.py -k prompt` без
  файлов промптов Фазы 4 — 25 failed (`PromptNotFoundError`, устаревший `PROMPT_CONTRACTS.md`),
  16 passed, 8 xfailed. Зелёный: 41 passed, 8 xfailed.

- Этап I G1 (B): `uv run pytest tests/session/test_phase4_contracts.py tests/llm/test_phase4_ai_layer.py tests/practice/test_tasks_markup.py tests/practice/test_check_instant.py tests/test_contracts.py` — 33 красных (`NotImplementedError`: `TurnStreamParser`, `next_step_input`, `validate_markup`, `check`), 26 зелёных (контракты, `T-AI1`, `T-A6`).
- WP10.2–10.3 (адаптер и цикл): `tests/llm/test_phase4_stream_adapter.py` написан до реализации, но красный прогон не снят отдельно (до реализации тесты падали бы на импорте `quack.llm.tool_loop`). Зелёный: 9 passed; с затронутыми старыми (`tests/llm`, `test_llm_runtime.py`, `test_meta_mock.py`, `test_thresholds_in_settings.py`, `test_contracts.py`) — 127 passed.
- WP12.1 (`T-TK1`, `tests/practice/test_tasks_store.py`): красный прогон отдельно не снят — тесты и код в одной итерации, до установки `dbmate` все 4 пропускались. Зелёный: `QUACK_TEST_REQUIRE_INFRA=1` — 4 passed (dbmate 2.37.0, Postgres 16).
- WP11.5 ядро математики (#79, коммит `85e07f9`): один коммит, красный прогон не снят отдельно (замечание C по §7.4). Зелёный: `compute/tests/math` — 40 passed.
- WP11.5, пороги через `Params` (D-B-124): `cd compute && uv run pytest tests/math/test_params.py` — красный на сборке (`TypeError: Params.__init__() got an unexpected keyword argument 'precision_digits'`), коммит `32db37f`. Зелёный: `compute/tests/math` — 43 passed.
- WP11.5, эндпоинты без значений по умолчанию (D-B-124, #83): `cd compute && uv run pytest tests/math/test_service.py` — 11 failed, 4 passed (422 и `ValidationError`: `numeric`, `tolerance` не в схеме). Зелёный: весь `compute` — 67 passed.
- Зелёный прогон (B, `phase-4-b`): те же файлы — 59 passed. Полный прогон набора на итоговом SHA (§0.4.7) — job `backend` CI (`QUACK_TEST_REQUIRE_INFRA=1`); SHA и итог — в описании PR #72.
- WP11.3, быстрая проверка (D-B-126): `cd backend && uv run pytest tests/practice/test_check_fast.py` — 11 failed (`NotImplementedError` в `check()`), коммит `6f32612`. Зелёный: 11 passed; с затронутыми (`tests/practice`, `tests/test_contracts.py`, `tests/storage/test_compute_client_math.py`, `tests/test_thresholds_in_settings.py`) — 67 passed.
- WP11.7 (D-B-127): `cd backend && uv run pytest tests/practice/test_check_reading.py` — 4 failed, 1 passed (набранный ответ не меняется уже сейчас), коммит `883b237`. Зелёный: `tests/practice` — 55 passed.
- WP11.6, чистая часть (D-B-128): `cd backend && uv run pytest tests/practice/test_second_opinion.py` — 14 failed (`NotImplementedError`), коммит `6e3de38`. Зелёный: 14 passed; с затронутыми (`tests/practice`, `tests/test_contracts.py`, `tests/test_thresholds_in_settings.py`) — 81 passed.
- WP13.8 (`T-TT8`): `tests/session/test_turn_effort.py` — 6 failed, 3 passed (`TypeError`: нет флагов), коммит `00cb285`. Зелёный: 9 passed.
- WP13.5 (`T-TT4`, часть): `tests/session/test_head_guards.py` — 15 failed (`NotImplementedError`), коммит `26755dd`. Зелёный: 15 passed.
- WP13.4 (`T-TT3`, часть): `tests/session/test_holdback.py` — 4 failed (`NotImplementedError`), коммит `83675d3`. Зелёный: 5 passed; с затронутыми (`tests/session/test_spoiler_guard.py`, `test_phase3_hot_path.py::test_teacher_reasoning_effort_by_situation`, на инфраструктуре B) — 43 passed.
- S3, модели B из ядра (Q-A-1 вариант (а)): `cd backend && uv run pytest tests/practice/test_core_models.py` — 11 failed (модели `quack.practice` — копии, не объекты `quack.events.values`), 3 passed (поля форм с метками и с id уже совпадают), коммит `ed6188c`. Зелёный: 14 passed; с затронутыми (`tests/practice`, `tests/events`, `tests/session/test_phase4_contracts.py`, `tests/llm/test_phase4_ai_layer.py`, `tests/test_contracts.py`, `tests/test_thresholds_in_settings.py`, инфраструктура B) — 195 passed. `CheckFailed` теперь модель Pydantic ядра — вызовы B с именованными аргументами.

- S3/S4/S6 (A, `phase-4-a-s4-s6`): тесты и код писались в одной итерации, красный прогон отдельно не снят (`Verdict` split, `RejectedElementRecord.index`, `quack.graph.read`, `rules_p4.py`). Зелёный: `tests/graph/test_read_stub.py`, `tests/jobs`, `tests/events/test_rejected_element.py`, `tests/practice/test_second_opinion.py`, `tests/db/test_sql_static.py`, `tests/test_contracts.py` (`T-A6`) — локально без инфраструктуры; тесты с Postgres/dbmate (`tests/db`, `tests/events/test_catalog.py`, `tests/practice/test_answer_transaction.py`, `tests/practice/test_tasks_store.py`) локально не запускались (нет `dbmate`) — их прогонит CI.
- WP11.6, тело `check.model` (D-B-145): `cd backend && uv run pytest tests/practice/test_check_model.py` — 12 failed (`NotImplementedError`), коммит `63ba969`. Зелёный: 12 passed; с затронутыми (`tests/practice`, `tests/llm`, `tests/test_contracts.py`, `tests/test_thresholds_in_settings.py`, инфраструктура B) — 196 passed.
- WP11.3, тело `check.symbolic` (D-B-146): `cd backend && uv run pytest tests/practice/test_check_symbolic_job.py` — 5 failed (`NotImplementedError`), коммит `2ead504`. Зелёный: 5 passed; с `tests/db/test_sql_static.py` — 9 passed.

## Правки тестов

- `tests/session/test_holdback.py` (B, до зелёного): `test_spoiler_found_only_at_the_end` ошибочно ждал спойлер только в `finish`, хотя по WP13.4 весь накопленный текст проверяется на каждом куске. Заменён на `test_spoiler_completed_inside_the_holdback` (спойлер ловится на куске, который его дописал) и `test_finish_checks_the_whole_text`. Проверка не ослаблена: показанный текст по-прежнему пуст.
- `tests/llm/test_phase4_ai_layer.py` (`T111`): `max_output_tokens` десяти ролей — по замеру (D-B-134); `Т-§11.1` разрешает менять конфиг по замеру. Сила проверки не меняется.
- `tests/test_contracts.py` (`T-A6`): в `PRODUCT` добавлен `agents` (ТЗ Ф4 §4.1). Сила проверки не меняется.
- `compute/tests/math/test_equivalence.py`: `PARAMS` берётся из `test_params.py` (у `Params` новые поля, D-B-124). Утверждения не менялись.

## Вопросы к команде

- **Q-A-2 (A → B, к заморозке S3 на G1).** (1) `Verdict.misconception` в событии — id заблуждения или гипотеза словами, метка недопустима (`Т-§4.5`); оставить одно поле `str` или разделить на `misconception_id` и `misconception_hypothesis`? (2) `element.responded` по §6.3 — без `answer`; ответ на элемент-задачу пишется как `answer.submitted` с `element_id` — так? (3) `observation.extracted.rejected` — форма `{reason, quote}` достаточна? (4) `RootCauseRecord.confidence` — категория в событии, число по `root_cause_confidence_map` считает проектор (A) — согласен? (5) `item.flagged_unclear.text` вместо `quote` (D-A-107). (6) `CheckFailed` стал моделью Pydantic — позиционный конструктор dataclass больше не работает.
- **Q-A-3 (A → C, к заморозке S3 на G1).** (1) `observation.diagnosed`: `diagnosis.kind` (`error`, `question`) и `method` (`model`, `symbolic`) — по WP5.1, WP21.4 так? (2) `canvas.line_committed.kind` — пока `str`: дай закрытый перечень видов строки (`Т-§15.3`). (3) `material.parsed` — `{material_id, pages_count}` достаточно? (4) `artifact.updated.kind` — пока `str`: назови значения видов WP23.1. (5) `DeletionRecord.target_id` — UUID, как `ops.deletion_log.target_id` (ревью #74).
- **Q-A-1 (A → B, класс C, шов S3).** Каталог событий живёт в ядре (`quack.events`, §4.1), и импортировать модели B из `quack.practice`, `quack.agents`, `quack.session` он не может (слои §4.1, `T-A6`). Кроме того, разметка `turn.committed` хранит id, а `TurnMarkup` модели — метки. Предложение A: модели нагрузки — в каталоге (`quack.events.registry`, S3), поля — по моделям B (`Verdict`, `CheckFailed`, `ExtractedElement`, `TurnMarkup` с id, `LearnerAnswer`); B импортирует их из ядра вместо своих копий или держит свои модели, а тест-контракт сверяет поля. Нужен выбор B до G1.
- **Q-A-2 (A → B) — ответ B:** (1) `Verdict.misconception` разделить на `misconception_id` и `misconception_hypothesis`; (2) да, ответ на элемент-задание — `answer.submitted` с `element_id`; (3) `rejected` — предложение `{index, reason, quote}` (провенанс, закон 6), решает A; (4) согласен, число корня — при проекции по `root_cause_confidence_map`; (5) согласен с D-A-107; (6) согласен. Подробно — комментарий в PR #80.
- **Q-A-1 (A → B, класс C, шов S3) — ответ B: вариант (а).** Модели нагрузки событий, которые пишет B (`answer.submitted`, `verdict.recorded`, `check.failed`, `observation.extracted`, `turn.committed`, `task.created` и др.), живут в ядре — в `quack.events.registry` (A), с полями по моделям B из PR #72. B импортирует их из ядра. Почему: ядро не может импортировать продукт (§4.1, `T-A6`); WP2.1 требует модель Pydantic на каждый тип в реестре и отказ неверной нагрузки при записи — это возможно только с моделями в ядре; одна реализация вместо двух (§0.4.3, «частые случаи»: два потока сделали по-разному). Раскладка:
  - модели с одинаковой формой в событии и в продукте — `LearnerAnswer`, поля `Verdict`, `CheckFailed`, `AnswerSpec` (внутри разметки `task.created`) — переезжают в ядро; `quack.practice` их переэкспортирует, а не копирует. Переезд делает A при заморозке каталога (S3, G1), B меняет импорты одним PR сразу после;
  - модели выхода моделей с метками (`TaskMarkup`, `TurnMarkup`, `ExtractedElement`) остаются у B; в событии — их форма с id вместо меток, это модели ядра (`TaskMarkupIds` и т. п., имена — A). Перевод «метки → id» — код B (`quack.llm.labels`);
  - тест-контракт B: модели `quack.practice` — те же объекты, что в реестре, и у моделей с метками те же поля, что у формы с id, кроме полей меток.

- **Q-C-1 (C → владелец, к сведению B).** `compute/` на `main`: в первом прогоне в контейнере,
  запущенном одновременно с полным `pytest` backend, упали 2 теста из 5
  (`test_equation_roots_and_matrix` и ещё один); три следующих прогона — 5 passed. Похоже на
  таймаут проверки под нагрузкой (`multiprocessing` с таймаутом). WP24 переводит пул на
  `pebble` — проверить там; до этого не трогаю.

## Для фронтенда

Снимок `backend/openapi.json` и таблица «старый эндпоинт → новый» (§6.4) — на каждом гейте.

### Черновик к G1 (решение владельца 2026-11-02, передано потоком B; D-B-119)

- Снимок: `backend/openapi.json` в ветке `phase-4-b-actions-route`, коммит `679b8ea` или новее
  (PR #75): https://github.com/steppetech1/Quack/blob/679b8ea/backend/openapi.json
- **Маршрут `/actions` объявлен, тело — WP13.1.** `POST /v1/sessions/{session_id}/actions`:
  `200` — `text/event-stream`, событие — `ActionFrame` (кадры §4.7), `Element`; `201` —
  `ActionAccepted`.
- `backend/openapi.json` в `phase-4` до слияния #75 не меняется. Таблица «старый → новый» — §6.4 ТЗ.

## DoD

Таблица §10 — заполняется к G4.
