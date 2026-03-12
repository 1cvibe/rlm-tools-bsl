# Установка и настройка rlm-tools-bsl

## 0. Установить Python и uv

rlm-tools-bsl требует **Python 3.10+** и менеджер пакетов **uv**.

**Python:**

Скачайте и установите с [python.org](https://www.python.org/downloads/). При установке на Windows обязательно отметьте галочку **«Add Python to PATH»**.

Проверьте:
```bash
python --version
# Python 3.12.x (или 3.10+)
```

**uv** (быстрый менеджер пакетов Python):

```bash
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# Linux/macOS
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Проверьте:
```bash
uv --version
```

> **Альтернатива:** если предпочитаете pip, установите его вместе с Python (он идёт в комплекте). Далее в инструкции используется uv, но вместо `uv tool install .` можно использовать `pip install .`

## 1. Клонировать репозиторий

```bash
git clone https://github.com/<your-repo>/rlm-tools-bsl.git
cd rlm-tools-bsl
```

## 2. Установить глобально

```bash
uv tool install . --force
```

Команда `rlm-tools-bsl` станет доступна глобально. `uv tool install` создаёт изолированное окружение и ставит пакет из текущего каталога — версия подхватывается из `pyproject.toml` автоматически.

<details>
<summary>Вариант через pip</summary>

```bash
pip install .
```

</details>

## 3. (Опционально) ANTHROPIC_API_KEY

В песочнице есть хелпер `llm_query(prompt, context)` — он вызывает «маленькую» LLM (по умолчанию Claude Haiku) прямо из `rlm_execute`, не возвращаясь в основной контекст. Это полезно, когда агент нашёл много данных и хочет классифицировать или суммировать их на стороне сервера.

Для работы `llm_query` нужен API-ключ Anthropic:

```bash
# Windows
set ANTHROPIC_API_KEY=sk-ant-api03-...

# Linux/macOS
export ANTHROPIC_API_KEY=sk-ant-api03-...
```

Ключ получается на [console.anthropic.com](https://console.anthropic.com) → API Keys. Вызовы `llm_query` тарифицируются отдельно по ценам Anthropic API.

**Без ключа всё остальное работает нормально** — `find_module`, `grep`, `read_file`, `parse_object_xml` и все прочие хелперы не требуют API-ключа. Просто `llm_query()` будет недоступен.

## 4. Настроить MCP

**Claude Code (глобально):**
```bash
claude mcp add rlm-tools-bsl -- rlm-tools-bsl
```

**Или в `.claude.json` / `mcp.json`:**
```json
{
  "mcpServers": {
    "rlm-tools-bsl": {
      "command": "rlm-tools-bsl"
    }
  }
}
```

**Для разработки (запуск из исходников):**
```json
{
  "mcpServers": {
    "rlm-tools-bsl": {
      "command": "uv",
      "args": ["run", "rlm-tools-bsl"]
    }
  }
}
```

**StreamableHTTP (альтернатива stdio — стабильнее для некоторых клиентов):**

Некоторые клиенты (например, Kilo Code) могут некорректно работать с stdio-транспортом — переподключают сервер при ошибках. StreamableHTTP решает эту проблему.

1. Запустите сервер отдельным процессом:
```bash
rlm-tools-bsl --transport streamable-http
```

2. Укажите URL в конфиге клиента:
```json
{
  "mcpServers": {
    "rlm-tools-bsl": {
      "url": "http://127.0.0.1:9000/mcp"
    }
  }
}
```

Дополнительные параметры: `--host 0.0.0.0` (слушать все интерфейсы), `--port 3000` (другой порт).
Или через переменные окружения: `RLM_TRANSPORT`, `RLM_HOST`, `RLM_PORT`.

> **Результат тестирования StreamableHTTP:** транспорт работает стабильно — 26 вызовов `rlm_execute` подряд (сканирование 23 000+ BSL-файлов, ~350 сек) без единого обрыва. Это именно тот сценарий, где stdio мог бы дать сбой при долгой сессии.

## 5. Проверить

Откройте проект с исходниками 1С в Claude Code и спросите:
```
Используй rlm-tools-bsl: найди все модули справочника "Номенклатура" и покажи экспортные функции
Покажи кто вызывает найденные экспортные функции
```

## Разработка

```bash
git clone https://github.com/<your-repo>/rlm-tools-bsl.git
cd rlm-tools-bsl
uv sync --dev
uv run python -m pytest tests/ -q
```
