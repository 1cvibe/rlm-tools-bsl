# Full Analysis Prompt — E2E Test for All Helpers

Use this prompt to run a comprehensive analysis of a 1C document using all available helpers.
Replace `РеализацияТоваровУслуг` with your target object name, and `<path>` with the actual path to your 1C source code.

---

## Prompt

```
Мне нужно провести полный анализ документа РеализацияТоваровУслуг в конфигурации ERP.
Путь: <путь к каталогу исходников 1С>

Используй ТОЛЬКО MCP-сервер rlm-tools-bsl (rlm_start / rlm_execute / rlm_end).
Не используй встроенные инструменты чтения файлов — всё делай через песочницу.

Мне нужно знать:
- Структура документа: реквизиты, табличные части, формы, модули
- Процедуры и экспортные функции в модулях объекта и менеджера
- Кто вызывает ключевые процедуры (проведение, установка статуса)
- По каким регистрам делает движения
- Какие документы являются основанием и какие создаются на основании
- Подписки на события, регламентные задания, печатные формы
- Функциональные опции, роли и права доступа
- Значения связанных перечислений (статусы)
- В какие подсистемы входит
- Нетиповые доработки (кастомизации)
- Есть ли расширения и какие перехваты делают
- Метрики сложности кода
- Запросы в модуле менеджера
- Бизнес-логика проведения: как именно проводится документ, какие регистры затрагиваются и почему, цепочка вызовов от ОбработкаПроведения до записи в регистры
- Печатные формы: какие печатные формы доступны, через какие модули формируются

Начни с help() чтобы узнать доступные инструменты, затем используй их по своему усмотрению.
Обрати внимание на Step 0 — UNDERSTAND в стратегии и бизнес-рецепт, если он был предложен.

Дай итоговую сводку со всеми цифрами. Файл с анализом сохрани в текущий рабочий каталог

## ВАЖНЫЕ ПРАВИЛА

1. Каждый rlm_execute должен батчить несколько связанных операций. Плохо: один вызов на один хелпер. Хорошо: несколько хелперов + print() в одном вызове.
2. Переменные сохраняются между вызовами rlm_execute.
3. Используй print() для вывода результатов.
4. В конце ОБЯЗАТЕЛЬНО вызови rlm_end для освобождения ресурсов.
```

---

## What it covers

This prompt exercises all 28 BSL helpers without explicitly naming them. The AI agent discovers the toolset via `help()` and decides which helpers to use. Business questions in the prompt trigger `_BUSINESS_RECIPES` injection via `get_strategy()` (v1.3.5+).

| Area | Expected helpers |
|------|-----------------|
| Navigation | `find_module`, `find_by_type`, `safe_grep`, `search_methods` |
| Code analysis | `extract_procedures`, `find_exports`, `read_procedure`, `extract_queries`, `code_metrics` |
| Call graph | `find_callers`, `find_callers_context` |
| XML parsing | `parse_object_xml`, `find_enum_values` |
| Business analysis | `analyze_object`, `analyze_document_flow`, `analyze_subsystem` |
| Customizations | `find_custom_modifications`, `detect_extensions`, `find_ext_overrides` |
| Infrastructure | `find_register_movements`, `find_register_writers`, `find_based_on_documents`, `find_event_subscriptions`, `find_scheduled_jobs`, `find_print_forms`, `find_functional_options`, `find_roles` |
| Strategy | Step 0 UNDERSTAND + business recipe (проведение/печать) via `get_strategy(query=...)` |
| Help | `help` |

## Recommended settings

- **effort**: `high` (default since v1.1.0) — gives 50 execute calls, enough for full coverage
- **max_output_chars**: `30000` — large modules produce verbose output
- **execution_timeout_seconds**: `120` — composite helpers on large configs need time

## Test results (v1.2.0, ERP 23K+ files, 617K methods index)

### Without index

| Client | Model | rlm_execute | Sections | Notes |
|--------|-------|------------|----------|-------|
| Claude Code | Sonnet 4.6 | 52 | 16 | Reference quality, ~14.6 min |
| Cursor | Sonnet 4.6 | 24 | 15 | Near-reference quality, dense batching |
| Kilo Code | Minimax m2.5 | 19 | 14 | Gaps: wrong enum, no callers, timeouts |

### With index

| Client | Model | rlm_execute | Sections | Notes |
|--------|-------|------------|----------|-------|
| Claude Code | Sonnet 4.6 | 35 | 15 | 33% fewer calls, ~11 min, FTS used |
| Kilo Code | Minimax m2.5 | 10 | 14 | Huge improvement: clean report, correct data |
