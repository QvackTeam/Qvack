# Журнал решений потока B — Фаза 4 (с 2026-11-03)

Новые решения потока B пишутся **сюда**, сверху, в момент решения (ТЗ Ф4 §0.4.5). Общий
`backend/PHASE4_NOTES.md` — архив до 2026-11-03: новые записи туда не добавляются, это убирает
конфликты слияния. Сводка всех решений — `documentation/Фаза 4 — решения (единое).md`: добавь туда
строку о решении в той же волне.

Формат записи (как в архиве):

```
### D-B-NNN. <суть>
- Класс: A | B | C (§0.4.5)
- WP / место: …; файлы
- Контекст: чего нет в документах
- Решение: …
- Почему: Т-§ / Д-§ / ТЗ
- Обратимость: …
- Тесты: …
- Требует подтверждения владельцем: да / нет
```

Номера продолжают архив: следующий свободный номер — по `grep -h "^### D-B-" backend/PHASE4_NOTES.md backend/notes/B.md`.

<!-- записи ниже, новые сверху -->

### D-B-193. «Я это уже знаю»: уровень, число задач, ключ ответа (WP8.2, WP16.6)
- Класс: B
- WP / место: `check.known_claim`; `quack/agents/task_generation.py`, `Settings.known_check_max_tasks`
- Контекст: ТЗ WP8.2 — «1–3 задачи по навыкам темы на целевых уровнях»; какой уровень и как набрать три — не сказано.
- Решение: по одной задаче на навык темы (первая сохранённая из вызова), в порядке навыков, не больше `known_check_max_tasks = 3`; уровень — рубеж навыка (`frontier`) среди уровней, которые требуют хабы темы (иначе 1–6); навык с доказанными целевыми уровнями пропускается. Ответ `agent.completed {kind: known_check, task_ids}` — по `request_id`, для `known.claimed` — по `job_key = check.known_claim:{learner}:{seq}` (собирается по правилу WP7.1, у `ClaimedJob` Ф3 поля `job_key` нет). `ok: false`, если проверить было что, но ни одна задача не прошла проверку, или темы нет в памяти.
- Почему: ТЗ Ф4 WP8.2, WP12.6, Т-§13.9
- Обратимость: да
- Тесты: `tests/agents/test_task_agents.py`
- Требует подтверждения владельцем: нет

### D-B-192. Тип ответа и цель поручения `agent.task_generation` (WP12.6, WP16.6)
- Класс: B
- WP / место: `quack/agents/task_generation.py`
- Контекст: `agent.requested` не несёт тип ответа и цель (практика/ретест), а `generate_tasks` требует `kind` и `purpose`.
- Решение: тип ответа по уровню — 1 `choice`, 2 `short_text`, 3–5 `number`, 6 `proof`; есть `params.task_id` — это исходная задача, цель `retest` (варианты в её семье, Т-§5.4, Т-§5.7), иначе `practice`; `params.description` идёт в контекст курса, `misconception_id` сужает известные заблуждения. Нет `skill_id`/`level` — `JobFailedPermanently`; ни один вариант не прошёл проверку — `agent.completed {ok: false}`. `task_arbiter` отдельного обработчика не имеет: арбитр внутри `generate_tasks` (WP12.5).
- Почему: ТЗ Ф4 WP12.6, WP16.6; Т-§5.5, Т-§13.9
- Обратимость: да
- Тесты: `tests/agents/test_task_agents.py`
- Требует подтверждения владельцем: нет

### D-B-191. Обработчики `task.solution_space`, `agent.solution_space`, `agent.task_generation`, `check.known_claim` (WP16.6)
- Класс: B
- WP / место: `quack/agents/{delivery,solution_space,task_generation}.py`; регистрация (б) #173 в `kinds.py`, `runtime/__init__.py`
- Контекст: образец — `agents/viz.py`; исчерпавшую попытки задачу закрывает очередь (`agent.completed {ok:false}`, WP7.4), обработчик пишет только исход по существу.
- Решение: `agent.completed` пишется ключом `agent.completed:{request_id | job_key}` с проверкой существующего (повтор не дублирует); пространство решения читает заблуждения навыков задачи из памяти (`slice_for_turn` с пустой сессией `NO_SESSION`), `agent.solution_space` возвращает `task_ids=[task]`, чужая задача — `ok:false task_not_found`; новый параметр `known_check_max_tasks`; в `practice/repo.py` — `agent_request`.
- Почему: ТЗ Ф4 WP12.4, WP16.6, Т-§13.9, закон 5
- Обратимость: да
- Тесты: `tests/agents/test_task_agents.py`
- Требует подтверждения владельцем: нет

