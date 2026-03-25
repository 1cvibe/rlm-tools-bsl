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

Дай итоговую сводку со всеми цифрами. Сохрани файл с анализом в текущий рабочий каталог своими инструментами (НЕ через rlm_execute)

## ВАЖНЫЕ ПРАВИЛА

1. Каждый rlm_execute должен батчить несколько связанных операций. Плохо: один вызов на один хелпер. Хорошо: несколько хелперов + print() в одном вызове.
2. Переменные сохраняются между вызовами rlm_execute.
3. Используй print() для вывода результатов.
4. В конце ОБЯЗАТЕЛЬНО вызови rlm_end для освобождения ресурсов.
```

---

## What it covers

This prompt exercises all 34 BSL helpers without explicitly naming them. The AI agent discovers the toolset via `help()` and decides which helpers to use. Business questions in the prompt trigger `_BUSINESS_RECIPES` injection via `get_strategy()` (v1.3.5+).

| Area | Expected helpers |
|------|-----------------|
| Navigation | `find_module`, `find_by_type`, `safe_grep`, `search_methods` |
| Code analysis | `extract_procedures`, `find_exports`, `read_procedure`, `extract_queries`, `code_metrics` |
| Call graph | `find_callers`, `find_callers_context` |
| XML parsing | `parse_object_xml`, `find_enum_values` |
| Business analysis | `analyze_object`, `analyze_document_flow`, `analyze_subsystem` |
| Customizations | `find_custom_modifications`, `detect_extensions`, `find_ext_overrides` |
| Infrastructure | `find_register_movements`, `find_register_writers`, `find_based_on_documents`, `find_event_subscriptions`, `find_scheduled_jobs`, `find_print_forms`, `find_functional_options`, `find_roles` |
| Integration (v1.4.0) | `find_http_services`, `find_web_services`, `find_xdto_packages`, `find_exchange_plan_content` |
| Strategy | Step 0 UNDERSTAND + business recipe (проведение/печать/интеграция) via `get_strategy(query=...)` |
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

---

# Integration Analysis Prompt — E2E Test for v1.4.0 Helpers

Use this prompt to verify the new integration metadata helpers added in v1.4.0.
Replace `<path>` with the actual path to your 1C source code (EDT or CF format).

---

## Prompt

```
Мне нужно провести полный анализ интеграционных возможностей конфигурации ERP.
Путь: <путь к каталогу исходников 1С>

Используй ТОЛЬКО MCP-сервер rlm-tools-bsl (rlm_start / rlm_execute / rlm_end).
Не используй встроенные инструменты чтения файлов — всё делай через песочницу.

Мне нужно знать:

1. **HTTP-сервисы (REST API)**:
   - Полный список HTTP-сервисов с корневыми URL
   - Для каждого: шаблоны URL, доступные HTTP-методы (GET/POST/PUT/DELETE), обработчики
   - Какие из них типовые (БСП), какие кастомные
   - Статистика: сколько всего сервисов, шаблонов, методов

2. **Веб-сервисы (SOAP)**:
   - Полный список веб-сервисов с namespace
   - Для каждого: операции, параметры операций, типы возвращаемых значений, процедуры-обработчики
   - Статистика: сколько сервисов, операций

3. **XDTO-пакеты**:
   - Полный список пакетов с namespace
   - Для пакетов с типами: objectType и valueType с их свойствами
   - Какие пакеты относятся к обмену данными, какие к интеграции с внешними системами
   - Статистика: сколько пакетов, сколько из них с типами

4. **Планы обмена**:
   - Список всех планов обмена (через find_by_type)
   - Для основного плана обмена (например, ОбменУправлениеПредприятием): полный состав — какие объекты входят и с каким режимом авторегистрации
   - Регламентные задания, связанные с обменом (фильтр по 'Обмен|Exchange|Синхрониз|Загруз|Выгруз')

5. **Связи между компонентами**:
   - Какие HTTP-сервисы используют XDTO-пакеты (по namespace)
   - Какие веб-сервисы ссылаются на XDTO-типы
   - Общие модули, связанные с интеграцией (поиск по 'Интеграц|Обмен|Exchange')

Начни с help('http') и help('обмен') чтобы узнать доступные рецепты и инструменты.
Затем используй find_http_services(), find_web_services(), find_xdto_packages(), find_exchange_plan_content() и другие хелперы.

Дай итоговую сводку со всеми цифрами в виде структурированного отчёта. Сохрани файл с анализом в текущий рабочий каталог своими инструментами (НЕ через rlm_execute).

## ВАЖНЫЕ ПРАВИЛА

1. Каждый rlm_execute должен батчить несколько связанных операций. Плохо: один вызов на один хелпер. Хорошо: несколько хелперов + print() в одном вызове.
2. Переменные сохраняются между вызовами rlm_execute.
3. Используй print() для вывода результатов.
4. В конце ОБЯЗАТЕЛЬНО вызови rlm_end для освобождения ресурсов.
```

---

## What it covers

This prompt specifically targets the 4 new integration helpers from v1.4.0 and verifies they work correctly on real 1C configurations. It also tests the integration business recipe and alias routing.

| Area | Expected helpers | What to verify |
|------|-----------------|----------------|
| HTTP services | `find_http_services()` | name, root_url, templates with methods |
| Web services | `find_web_services()` | name, namespace, operations with params |
| XDTO packages | `find_xdto_packages()` | name, namespace, types (EDT only) |
| Exchange plans | `find_exchange_plan_content(name)` | ref, auto_record for each object |
| Exchange plan list | `find_by_type('ExchangePlans')` | BSL modules of exchange plans |
| Related jobs | `find_scheduled_jobs()` + filter | jobs related to exchange/sync |
| Integration recipe | `help('http')`, `help('обмен')` | recipe displayed correctly |
| Strategy injection | `get_strategy(query='интеграция')` | BUSINESS RECIPE injected |
| Index version | `rlm_start` warnings | no version warning with v6 index |

## Expected results on ERP 2.5 (EDT, ~20K BSL modules)

| Metric | Expected range |
|--------|---------------|
| HTTP services | 20–30 |
| Web services | 15–20 |
| XDTO packages | 250–350 |
| XDTO packages with types | 200+ (EDT format) |
| Exchange plans | 5–15 |
| Exchange-related scheduled jobs | 10–30 |

---

# Object Synonyms Prompt — E2E Test for v1.4.1 Helpers

Use this prompt to verify the new object synonym search and index info helpers added in v1.4.1.
Replace `<path>` with the actual path to your 1C source code (EDT or CF format). Requires index v7+ (`rlm-bsl-index index build <path>`).

---

## Prompt

```
Мне нужно проверить возможности поиска объектов по бизнес-именам (синонимам) в конфигурации ERP.
Путь: <путь к каталогу исходников 1С>

Используй ТОЛЬКО MCP-сервер rlm-tools-bsl (rlm_start / rlm_execute / rlm_end).
Не используй встроенные инструменты чтения файлов — всё делай через песочницу.

Мне нужно проверить:

1. **Диагностика индекса**:
   - Вызови get_index_info() и выведи: версию индекса, имя конфигурации, наличие FTS и синонимов
   - Если builder_version < 7 или has_synonyms = False — сообщи, что нужно перестроить индекс

2. **Поиск по бизнес-именам (кириллица)**:
   - search_objects('себестоимость') → какие документы, регистры, модули связаны с себестоимостью
   - search_objects('расчет') → проверка кириллического case-insensitive поиска (должен найти "Расчет...")
   - search_objects('авансовый') → найти документ "Авансовый отчет"
   - search_objects('номенклатура') → справочники и регистры, связанные с номенклатурой

3. **Поиск по категориям**:
   - search_objects('общий модуль') → все CommonModules (через категорийный префикс)
   - search_objects('регистр сведений') → все InformationRegisters
   - search_objects('документ') → должно вернуть много документов

4. **Дифференциация search_objects от search_methods**:
   - search_objects('Себестоимость') → объекты 1С (документы, регистры, модули)
   - search_methods('Себестоимость') → процедуры/функции в коде
   - Объясни разницу: search_objects = ЧТО за объект, search_methods = ГДЕ в коде

5. **Комбинация с другими хелперами**:
   - Найди через search_objects объект по бизнес-имени
   - Затем используй его техническое имя (object_name) в find_module(), find_by_type(), parse_object_xml()
   - Покажи цепочку: бизнес-имя → техническое имя → структура объекта → код

6. **Статистика**:
   - Общее количество объектов с синонимами (search_objects('') с limit=10000)
   - Распределение по категориям: сколько Documents, Catalogs, CommonModules, InformationRegisters и т.д.
   - Топ-5 самых длинных синонимов

Начни с get_index_info() для проверки доступности, затем help('search_objects') для рецепта.
Обрати внимание на NOTE в WORKFLOW: search_objects = WHAT object? search_methods = WHAT code?

Дай итоговую сводку со всеми цифрами. Сохрани файл с анализом в текущий рабочий каталог своими инструментами (НЕ через rlm_execute).

## ВАЖНЫЕ ПРАВИЛА

1. Каждый rlm_execute должен батчить несколько связанных операций. Плохо: один вызов на один хелпер. Хорошо: несколько хелперов + print() в одном вызове.
2. Переменные сохраняются между вызовами rlm_execute.
3. Используй print() для вывода результатов.
4. В конце ОБЯЗАТЕЛЬНО вызови rlm_end для освобождения ресурсов.
```

---

## What it covers

This prompt verifies the 2 new helpers from v1.4.1 (`search_objects`, `get_index_info`), the Cyrillic case-insensitive UDF, 4-level ranking, category prefix search, and the workflow differentiation between `search_objects` and `search_methods`.

| Area | Expected helpers | What to verify |
|------|-----------------|----------------|
| Index diagnostics | `get_index_info()` | builder_version=7, has_synonyms=True |
| Synonym search | `search_objects(query)` | Finds objects by Russian business name |
| Cyrillic case | `search_objects('расчет')` | Finds "Расчет..." despite case mismatch |
| Category search | `search_objects('общий модуль')` | Returns only CommonModules |
| Empty query | `search_objects('')` | Returns all objects (with limit) |
| Differentiation | `search_objects` vs `search_methods` | Objects vs code methods |
| Chaining | `search_objects` → `find_module` → `parse_object_xml` | Business name → technical name → structure |
| Help recipe | `help('search_objects')` | Recipe displayed correctly |
| WORKFLOW note | Strategy Step 1 | NOTE about search_objects vs search_methods |
| Ranking | Exact name first | `search_objects('АвансовыйОтчет')` → exact match rank 0 |

## Expected results on ERP 2.5

Verified on EDT (ЕРП 2.5.7, 20K modules, 17 218 synonyms) and CF (ЕРП 2.5.14, 23K modules, 13 661 synonyms).

| Metric | EDT (actual) | CF (actual) | Expected range |
|--------|-------------|------------|---------------|
| Total synonyms | 17,218 | 13,661 | 12,000–18,000 |
| CommonModules | 3,301 | 3,909 | 3,000–4,500 |
| InformationRegisters | 1,391 | 1,313 | 1,200–1,800 |
| Enums | 1,434 | 247 | 200–1,500 |
| Reports | 1,052 | 1,098 | 800–1,200 |
| Catalogs | 1,018 | 1,041 | 800–1,200 |
| Documents | 642 | 685 | 600–800 |
| AccumulationRegisters | 221 | 217 | 200–500 |
| Categories covered | 32 | 29 | 29–32 |
| search_objects('себестоимость') hits | 10–30 | 10–30 | 10–30 (across categories) |
| get_index_info().builder_version | 7 | 7 | 7 |
| DB size | 954 MB | 1,124 MB | 950–1,150 MB |
| Build time (full) | ~420s | ~402s | 400–450s |
