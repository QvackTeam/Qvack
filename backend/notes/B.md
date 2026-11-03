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

### D-B-188. `model_for_role` читает строку `llm_roles` (WP10.1 п.1)
- Класс: A (исправление ошибки)
- WP / место: WP10.1 п.1; `quack/config.py::Settings.model_for_role`, `quack/llm/gateway.py`
- Контекст: метод брал `llm_role_models` или `llm_default_model` (Spark) и не читал таблицу ролей D-B-101: `verdict_proof`, `second_opinion`, `analyst_deep`, `task_arbiter`, `viz_builder`, `release_judge` шли на Spark вместо Wonder, нетекстовые роли — тоже на Spark
- Решение: порядок — явная запись `llm_role_models` (переопределение окружения) → модель строки `llm_roles` → `llm_default_model`; `hard_model` как прежде. Обходной `_media_model` D-B-187 снят
- Почему: Т-§11.1 (модель роли — по таблице), ТЗ Ф4 WP10.1 п.1 «ровно таблицы»
- Обратимость: одна функция
- Тесты: `tests/test_settings_meta_api.py::test_default_models_are_the_live_ids`
- Требует подтверждения владельцем: нет

### D-B-187. Адаптеры нетекстовых ролей шлюза: `segmenter`, `voice`, `illustrator` (WP10.1)
- Класс: B
- WP / место: WP10.1 третий пункт; `quack/llm/media.py`, `gateway.py` (`segment`, `transcribe`, `illustrate`), `responses_client.py`, `provider.py`; `tests/llm/test_phase4_media_roles.py`
- Контекст: по WP0 п.3д форма `sam-3.1` и голоса известна (документация Meta, без вызова); для `muse-image-1.0` документов нет; формат спецтокенов описан не полностью (запись «id, рамка, маска», w/h рамки, префикс base85, `|>` внутри данных)
- Решение: (1) три публичных метода шлюза возвращают `LLMResult[Segmentation | Transcription | Illustration]`; путь вызова общий с текстовыми ролями (бюджеты, слот модели, повторы, 429 и флаг давления, 400, размыкатель, строка учёта на попытку). Без аутбокса и без промпта: версия 0, `prompt_hash` — хеш `роль@media`; повтор вызова — повторная плата. (2) `segmenter` — `POST /responses`, `input_text` (имя предмета ИЛИ `<0f>1<|box;x1=..;y1=..;x2=..;y2=..;w=..;h=..|>`) + `input_image` (data URL), `metadata.mask_encoding`/`include_confidence`, без `text.format`; ответ разбирает `parse_segmentation` (рамка начинает объект, маска за ней — его; до 16; маску не декодируем: `data` — base85 как пришло, `marker` `~`/`!`). (3) `voice` — `POST {base}/asr/transcribe`, multipart `request`+`audio`; токенов нет, длительность в `audio_duration_ms`. (4) `illustrator` — `POST {base}/images/generations`, `response_format=b64_json`, байты или `url`. (5) модель нетекстовой роли — `llm_role_models[role]`, иначе строка `llm_roles` (`model_for_role` для них вернул бы Spark)
- Почему: Т-§1.3, Т-§11.1, WP0 п.3д; ближайшее правило — OpenAI-совместимые пути
- Обратимость: вся форма запросов изолирована в трёх методах `ResponsesClient`
- Тесты: `tests/llm/test_phase4_media_roles.py` (по одному на роль: тело запроса, разбор, строка `ops.llm_ledger`)
- Требует подтверждения владельцем: нет. [ПРОВЕРИТЬ на стенде]: путь и тело `muse-image-1.0`; значения `w`/`h` рамки; формат записей и префикс маски `sam-3.1`; нужен ли голосу учёт в долларах по секундам (в WP10.4 строка `llm_usage` без токенов)
