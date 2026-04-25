# Карта модулей

## Группы модулей

### Точки входа
- **`__init__.py`** — пакет, публичный API (`__version__`)
- **`__main__.py`** — `python -m rlm_tools_bsl` → запуск MCP-сервера
- **`cli.py`** — CLI `rlm-bsl-index` (build / update / info / drop) → `bsl_index`, `cache`, `extension_detector`, `_config`, `_paths`
- **`server.py`** — MCP-сервер (5 тулов: rlm_projects, rlm_index, rlm_start, rlm_execute, rlm_end) → `session`, `sandbox`, `llm_bridge`, `format_detector`, `extension_detector`, `bsl_knowledge`, `bsl_index`, `cache`, `projects`, `service`, `helpers`, `_config`, `_paths`

### Сессии и песочница
- **`session.py`** — SessionManager, двухуровневый TTL (idle/active), `build_session_manager_from_env()` → _(нет внутренних зависимостей)_
- **`sandbox.py`** — Sandbox (exec Python в изолированном окружении с хелперами) → `helpers`, `bsl_helpers`, `_format`

### BSL-логика
- **`bsl_helpers.py`** — 43 хелпер-функции для анализа BSL/1С (регистрируются через `_reg()`), включая `find_references_to_object`, `find_defined_types` (v1.9.0) → `format_detector`, `bsl_knowledge`, `cache`, `bsl_xml_parsers`, `extension_detector`, `_format`
- **`bsl_knowledge.py`** — стратегия анализа, 9 бизнес-рецептов (себестоимость, проведение, распределение, печать, права, интеграция, события формы, ссылки, тип реквизита), WORKFLOW, INDEX TIPS → `extension_detector`
- **`bsl_index.py`** — SQLite-индекс v12 (26 таблиц + FTS5: core×4, metadata×17, navigation×1, references×4 — `metadata_references`, `exchange_plan_content`, `defined_types`, `characteristic_types`), IndexBuilder, IndexReader, **git fast path с pointwise incremental refresh** (v1.9.3: per-object DELETE+INSERT для Catalogs/Documents/IRегистры/AРегистры/АOрегистры/CoA/EventSubscriptions/ScheduledJobs/XDTOPackages вместо category-wide rescan; soft thresholds + bulk fallback для остального) → `bsl_knowledge`, `cache`, `format_detector`, `bsl_xml_parsers`, `extension_detector`
- **`bsl_xml_parsers.py`** — парсеры XML-метаданных 1С (CF и EDT форматы): `parse_metadata_xml` (с полем `references` для reverse-index), `canonicalize_type_ref`, `parse_defined_type`, `parse_pvh_characteristics`, `parse_command_parameter_type`, `parse_event_subscription_xml`, `parse_scheduled_job_xml`, `parse_xdto_package_xml` → `format_detector`

### Детектирование формата
- **`format_detector.py`** — определение CF/EDT, парсинг путей BSL-файлов (`parse_bsl_path`, `METADATA_CATEGORIES`) → _(нет внутренних зависимостей)_
- **`extension_detector.py`** — обнаружение расширений 1С и переопределений методов → `format_detector`, `helpers`

### Инфраструктура
- **`helpers.py`** — общие утилиты (smart_truncate, normalize_path, format_table) → _(нет внутренних зависимостей)_
- **`cache.py`** — дисковый кеш BSL-файлов (root зависит от `RLM_INDEX_DIR`/`RLM_CONFIG_FILE`/`~/.cache`, см. `docs/INDEXING.md`) → `format_detector`, `extension_detector`, `projects`, `_paths`
- **`llm_bridge.py`** — OpenAI-совместимый LLM-клиент (батчинг, retry) → _(нет внутренних зависимостей)_
- **`projects.py`** — реестр проектов (name → path, `projects.json`) → `_config`, `extension_detector`, `_paths`
- **`_config.py`** — загрузка конфигурации, поиск `.env` и `service.json` → _(нет внутренних зависимостей)_
- **`_format.py`** — форматирование вывода (presentation layer) → _(нет внутренних зависимостей)_
- **`_paths.py`** — общая каноникализация файловых путей (используется `server.py`, `projects.py`, `cache.py`, `cli.py`) → _(нет внутренних зависимостей)_

### Сервис
- **`service.py`** — управление сервисом (install / start / stop / status) → `_service_win` (Windows), `_service_linux` (Linux)
- **`_service_win.py`** — реализация Windows-сервиса через pywin32 → `service`
- **`_service_linux.py`** — реализация Linux systemd `--user` юнита → `service`

## Граф зависимостей

```mermaid
graph TD
    server --> session
    server --> sandbox
    server --> llm_bridge
    server --> format_detector
    server --> extension_detector
    server --> bsl_knowledge
    server --> bsl_index
    server --> cache
    server --> projects
    server --> service
    server --> helpers
    server --> _config
    server --> _paths

    sandbox --> helpers
    sandbox --> bsl_helpers
    sandbox --> _format

    bsl_helpers --> format_detector
    bsl_helpers --> bsl_knowledge
    bsl_helpers --> cache
    bsl_helpers --> bsl_xml_parsers
    bsl_helpers --> extension_detector
    bsl_helpers --> _format

    bsl_index --> bsl_knowledge
    bsl_index --> cache
    bsl_index --> format_detector
    bsl_index --> bsl_xml_parsers
    bsl_index --> extension_detector

    bsl_knowledge --> extension_detector

    bsl_xml_parsers --> format_detector

    cache --> format_detector
    cache --> extension_detector
    cache --> projects
    cache --> _paths

    extension_detector --> format_detector
    extension_detector --> helpers

    cli --> bsl_index
    cli --> cache
    cli --> extension_detector
    cli --> _config
    cli --> _paths

    projects --> _config
    projects --> extension_detector
    projects --> _paths

    service --> _service_win
    service --> _service_linux
```
