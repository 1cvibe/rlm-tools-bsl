"""
Бенчмарк rlm-tools-bsl на синтетической конфигурации 1С.

Запуск:
    uv run python benchmarks/run_benchmark.py

Измеряет время выполнения ключевых операций хелперов на минимальной
публичной фикстуре (benchmarks/fixture/).
"""

import os
import sys
import time

# Определяем путь к фикстуре относительно скрипта
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FIXTURE_DIR = os.path.join(SCRIPT_DIR, "fixture")

# Убеждаемся, что фикстура существует
if not os.path.isdir(FIXTURE_DIR):
    print(f"ОШИБКА: каталог фикстуры не найден: {FIXTURE_DIR}")
    sys.exit(1)

from rlm_tools_bsl.helpers import make_helpers
from rlm_tools_bsl.format_detector import detect_format
from rlm_tools_bsl.bsl_helpers import make_bsl_helpers, parse_metadata_xml


def setup_helpers(base_path):
    """Инициализация хелперов для фикстуры."""
    helpers, resolve_safe = make_helpers(base_path)
    format_info = detect_format(base_path)
    bsl = make_bsl_helpers(
        base_path=base_path,
        resolve_safe=resolve_safe,
        read_file_fn=helpers["read_file"],
        grep_fn=helpers["grep"],
        glob_files_fn=helpers["glob_files"],
        format_info=format_info,
    )
    return helpers, bsl


def timed(name, func, *args, **kwargs):
    """Выполняет функцию с замером времени, возвращает (результат, время_мс)."""
    start = time.perf_counter()
    result = func(*args, **kwargs)
    elapsed_ms = (time.perf_counter() - start) * 1000
    return result, elapsed_ms


def run_benchmarks():
    results = []

    # Инициализация
    (helpers, bsl), init_ms = timed("init", setup_helpers, FIXTURE_DIR)
    results.append(("Инициализация хелперов", f"{init_ms:.1f}", "OK"))

    # tree — дерево файлов
    tree_result, ms = timed("tree", helpers["tree"])
    file_count = tree_result.count("\n")
    results.append(("tree()", f"{ms:.1f}", f"{file_count} строк"))

    # find_module — поиск модуля
    modules, ms = timed("find_module", bsl["find_module"], "ОбщегоНазначения")
    results.append(("find_module('ОбщегоНазначения')", f"{ms:.1f}", f"{len(modules)} результатов"))

    # find_by_type — поиск по типу
    docs, ms = timed("find_by_type", bsl["find_by_type"], "Documents")
    results.append(("find_by_type('Documents')", f"{ms:.1f}", f"{len(docs)} результатов"))

    # extract_procedures — парсинг BSL
    if modules:
        path = modules[0]["path"]
        procs, ms = timed("extract_procedures", bsl["extract_procedures"], path)
        results.append(("extract_procedures(ОбщегоНазначения)", f"{ms:.1f}", f"{len(procs)} процедур"))
    else:
        results.append(("extract_procedures(ОбщегоНазначения)", "-", "SKIP: модуль не найден"))

    # find_exports — экспортные процедуры
    if modules:
        path = modules[0]["path"]
        exports, ms = timed("find_exports", bsl["find_exports"], path)
        results.append(("find_exports(ОбщегоНазначения)", f"{ms:.1f}", f"{len(exports)} экспортов"))
    else:
        results.append(("find_exports(ОбщегоНазначения)", "-", "SKIP: модуль не найден"))

    # find_callers — поиск вызовов
    callers, ms = timed("find_callers", bsl["find_callers"], "ПроверитьЗаполнениеРеквизитов")
    results.append(("find_callers('ПроверитьЗаполнениеРеквизитов')", f"{ms:.1f}", f"{len(callers)} вызовов"))

    # grep — текстовый поиск по всей фикстуре
    grep_result, ms = timed("grep", helpers["grep"], "ОбработкаПроведения", ".")
    results.append(("grep('ОбработкаПроведения', '.')", f"{ms:.1f}", f"{len(grep_result)} совпадений"))

    # glob_files — поиск файлов по паттерну
    bsl_files, ms = timed("glob_files", helpers["glob_files"], "**/*.bsl")
    results.append(("glob_files('**/*.bsl')", f"{ms:.1f}", f"{len(bsl_files)} файлов"))

    # parse_metadata_xml — парсинг метаданных документа
    doc_xml_path = os.path.join("Documents", "ПриходнаяНакладная", "Ext", "ПриходнаяНакладная.xml")
    doc_xml_full = os.path.join(FIXTURE_DIR, doc_xml_path)
    if os.path.exists(doc_xml_full):
        with open(doc_xml_full, encoding="utf-8") as f:
            xml_content = f.read()
        meta, ms = timed("parse_metadata_xml", parse_metadata_xml, xml_content)
        attr_count = len(meta.get("attributes", []))
        ts_count = len(meta.get("tabular_sections", []))
        results.append(("parse_metadata_xml(ПриходнаяНакладная)", f"{ms:.1f}", f"{attr_count} рекв., {ts_count} ТЧ"))
    else:
        results.append(("parse_metadata_xml(ПриходнаяНакладная)", "-", "SKIP: XML не найден"))

    # parse_metadata_xml — регистр накопления
    reg_xml_path = os.path.join("AccumulationRegisters", "ТоварыНаСкладах", "Ext", "ТоварыНаСкладах.xml")
    reg_xml_full = os.path.join(FIXTURE_DIR, reg_xml_path)
    if os.path.exists(reg_xml_full):
        with open(reg_xml_full, encoding="utf-8") as f:
            xml_content = f.read()
        meta, ms = timed("parse_metadata_xml_reg", parse_metadata_xml, xml_content)
        dim_count = len(meta.get("dimensions", []))
        res_count = len(meta.get("resources", []))
        results.append(("parse_metadata_xml(ТоварыНаСкладах)", f"{ms:.1f}", f"{dim_count} изм., {res_count} рес."))
    else:
        results.append(("parse_metadata_xml(ТоварыНаСкладах)", "-", "SKIP: XML не найден"))

    # parse_form — парсинг CF-формы
    form_result, ms = timed("parse_form", bsl["parse_form"], "ПриходнаяНакладная", "ФормаДокумента")
    results.append(("parse_form(ПриходнаяНакладная, ФормаДокумента)", f"{ms:.1f}", f"{len(form_result)} форм"))

    # find_event_subscriptions
    subs, ms = timed("find_event_subscriptions", bsl["find_event_subscriptions"])
    results.append(("find_event_subscriptions()", f"{ms:.1f}", f"{len(subs)} подписок"))

    # find_scheduled_jobs
    jobs, ms = timed("find_scheduled_jobs", bsl["find_scheduled_jobs"])
    results.append(("find_scheduled_jobs()", f"{ms:.1f}", f"{len(jobs)} заданий"))

    # find_register_movements
    movements, ms = timed("find_register_movements", bsl["find_register_movements"], "ПриходнаяНакладная")
    reg_count = len(movements.get("code_registers", []))
    results.append(("find_register_movements('ПриходнаяНакладная')", f"{ms:.1f}", f"{reg_count} регистров"))

    return results


def print_results(results):
    # Определяем ширину колонок
    col1_w = max(len(r[0]) for r in results) + 2
    col2_w = 12
    col3_w = max(len(r[2]) for r in results) + 2

    header = f"{'Операция':<{col1_w}} {'Время (мс)':>{col2_w}} {'Результат':<{col3_w}}"
    separator = "-" * len(header)

    print()
    print("=" * len(header))
    print("  Бенчмарк rlm-tools-bsl")
    print(f"  Фикстура: {FIXTURE_DIR}")
    print("=" * len(header))
    print()
    print(header)
    print(separator)

    total_ms = 0.0
    for name, ms_str, result in results:
        print(f"{name:<{col1_w}} {ms_str:>{col2_w}} {result:<{col3_w}}")
        if ms_str != "-":
            total_ms += float(ms_str)

    print(separator)
    print(f"{'ИТОГО':<{col1_w}} {f'{total_ms:.1f}':>{col2_w}}")
    print()


if __name__ == "__main__":
    results = run_benchmarks()
    print_results(results)
