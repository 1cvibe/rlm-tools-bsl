from __future__ import annotations

from dataclasses import dataclass


BSL_PATTERNS = {
    "procedure_def": r"(Процедура|Функция)\s+(\w+)\s*\(([^)]*)\)\s*(Экспорт)?",
    "procedure_end": r"^\s*(КонецПроцедуры|КонецФункции)",
    "export_marker": r"\)\s*Экспорт\s*$",
    "module_call": r"(\w+)\.(\w+)\s*\(",
    "region_start": r"#Область\s+(\w+)",
    "region_end": r"#КонецОбласти",
    "preprocessor_if": r"#Если\s+.+\s+Тогда",
    "preprocessor_endif": r"#КонецЕсли",
    "new_structure": r"Новый\s+Структура\(",
    "structure_insert": r'\.Вставить\(\s*"(\w+)"',
}


@dataclass
class EffortConfig:
    max_execute_calls: int
    max_llm_calls: int
    safe_grep_max_files: int
    guidance: str


EFFORT_LEVELS = {
    "low":    EffortConfig(10,  5,   5,  "Quick lookup. Find target module, extract what's needed, stop. Target: 3-5 rlm_execute calls."),
    "medium": EffortConfig(25,  15,  10, "Standard analysis. Find modules, trace 1-2 levels of calls, summarize. Target: 10-15 calls."),
    "high":   EffortConfig(50,  30,  20, "Deep analysis. Multi-module trace (3-4 levels), data flow, complete picture. Target: 20-30 calls. Build mermaid diagram."),
    "max":    EffortConfig(100, 50,  50, "Exhaustive mapping. All modules, all call chains, all data flows. Use llm_query() for semantic analysis. Target: 40-50+ calls."),
}

_BASE_STRATEGY = """\
You are exploring a 1C BSL codebase via Python sandbox.
Write Python code in rlm_execute. Use print() to output results.
Call help() for task-specific recipes, or help('keyword') for a specific recipe.

CRITICAL: Large configs have 23,000+ files. grep/grep_read on broad paths
(path='.' or path='CommonModules') WILL timeout. ALWAYS:
  1. find_module('name_fragment') -> get file paths
  2. read_file(path) or grep(pattern, path=exact_file)

CUSTOM PREFIXES: rlm_start returns "detected_custom_prefixes" — a list of non-standard
name prefixes auto-detected from the codebase (e.g. ["abc", "xyz"]). Use these prefixes
when filtering for custom/non-standard objects, subscriptions, roles, procedures, etc.
Do NOT hardcode prefixes — always use the detected ones from the session response.
find_custom_modifications() uses them automatically when custom_prefixes=None.

RECIPES (pick the one matching your task and paste into rlm_execute code):

  FIND EXPORTS of a module:
    modules = find_module('ModuleName')
    path = modules[0]['path']
    exports = find_exports(path)
    for e in exports:
        print(e['name'], 'line:', e['line'], 'export:', e['is_export'])

  BUILD CALL GRAPH:
    exports = find_exports('path/to/Module.bsl')
    for e in exports:
        data = find_callers_context(e['name'], 'ModuleHint', 0, 20)
        for c in data['callers']:
            print(e['name'], '<-', c['caller_name'], c['file'])
        if data['_meta']['has_more']:
            print('  ... more callers, increase offset')

  READ METADATA (attributes, tabular sections, dimensions):
    meta = parse_object_xml('Catalogs/Name/Ext/Catalog.xml')
    for key in meta:
        print(key, ':', meta[key])

  SEARCH FOR CODE PATTERN:
    results = safe_grep('PatternToFind', 'ModuleHint', max_files=20)
    for r in results:
        print(r['file'], 'line:', r['line'], r['text'])

RETURN FORMATS:
  find_module(name) -> [{"path", "category", "object_name", "module_type", "form_name"}]
  find_exports(path) -> [{"name", "line", "is_export", "type", "params"}]
  find_callers_context(proc, hint, offset, limit) -> {"callers": [{"file", "caller_name", "caller_is_export", "line", "context", "category", "object_name"}], "_meta": {"total_files", "scanned_files", "has_more"}}
  find_callers(proc, hint, max_files) -> [{"file", "line", "text"}]
  extract_procedures(path) -> [{"name", "type", "line", "end_line", "is_export", "params"}]
  find_by_type(category, name) -> same as find_module. Categories: CommonModules, Documents, Catalogs, InformationRegisters, AccumulationRegisters, Reports, DataProcessors
  safe_grep(pattern, hint, max_files) -> [{"file", "line", "text"}]
  parse_object_xml(path) -> {"name", "synonym", "attributes", "tabular_sections", "dimensions", "resources", ...}
  find_event_subscriptions(object_name) -> [{"name", "synonym", "source_count", "event", "handler", "handler_module", "handler_procedure", "file"}]
  find_scheduled_jobs(name) -> [{"name", "synonym", "method_name", "handler_module", "handler_procedure", "use", "file"}]
  find_register_movements(doc_name) -> {"document", "code_registers": [{"name", "lines", "file"}], "modules_scanned", "erp_mechanisms", "manager_tables", "adapted_registers"}
  find_register_writers(reg_name) -> {"register", "writers": [{"document", "file", "lines"}], "total_writers"}
  analyze_document_flow(doc_name) -> {"document", "metadata", "event_subscriptions", "register_movements", "related_scheduled_jobs"}
  find_based_on_documents(doc_name) -> {"document", "can_create_from_here": [{"document", "file"}], "can_be_created_from": [{"type", "file"}]}
  find_print_forms(object_name) -> {"object", "print_forms": [{"name", "presentation", "file"}]}
  find_functional_options(object_name) -> {"object", "xml_options": [{"name", "synonym", "location", "content", "file"}], "code_options": [{"option_name", "file", "line"}]}
  find_roles(object_name) -> {"object", "roles": [{"role_name", "object", "rights", "file"}]}
  find_enum_values(enum_name) -> {"name", "synonym", "values": [{"name", "synonym"}], "file"}

BSL HELPERS available in sandbox:
  help(task)                  -- get recipe for your task, e.g. help('find exports')
  find_module(name)           -- find BSL modules by name fragment
  find_by_type(category, name) -- find by metadata category (accepts singular/Russian names)
  extract_procedures(path)    -- list all procedures in a file
  find_exports(path)          -- list exported procedures
  safe_grep(pattern, hint)    -- timeout-safe grep across files
  read_procedure(path, name)  -- extract single procedure body
  find_callers(proc, hint)    -- find who calls this procedure (flat grep)
  find_callers_context(proc, hint, offset, limit)
                              -- find callers with context and pagination
  parse_object_xml(path)      -- parse 1C metadata XML
  analyze_subsystem(name)     -- find subsystem, parse composition, classify custom/standard objects
  find_custom_modifications(object_name, custom_prefixes=None)
                              -- find custom code in object modules (procedures, regions, XML attributes)
  analyze_object(name)        -- full object profile (XML metadata + all modules + procedures + exports)
  find_event_subscriptions(object_name) -- event subscriptions for object (what fires on write/post)
  find_scheduled_jobs(name)   -- scheduled (background) jobs
  find_register_movements(doc_name) -- which registers a document writes to (Движения.X + ERP framework)
  find_register_writers(reg_name)   -- which documents write to a register
  analyze_document_flow(doc_name)   -- full document lifecycle (metadata + subscriptions + movements)
  find_based_on_documents(doc_name) -- what documents can be created from/to this one
  find_print_forms(object_name)     -- print forms registered for object
  find_functional_options(object_name) -- functional options referencing object + code usage
  find_roles(object_name)           -- roles with granted rights to object
  find_enum_values(enum_name)       -- enum values with synonyms

FILE PATHS depend on format:
  CF:  CommonModules/Name/Ext/Module.bsl
  EDT: CommonModules/Name/Module.bsl

LLM_QUERY TIPS (when llm_query is available):
  llm_query(prompt, context='')        -- ask LLM to explain/summarize/analyze code
  llm_query_batched(prompts, context)  -- run multiple prompts in one call
  - Extract only relevant procedures first, then pass to llm_query — avoid raw full-file dumps
  - Keep context per call under ~3000 chars; for larger code split into multiple llm_query calls
  - If llm_query returns empty string, the context was too large — split and retry\
"""


def get_strategy(effort: str, format_info, detected_prefixes: list[str] | None = None, extension_context=None) -> str:
    config = EFFORT_LEVELS.get(effort, EFFORT_LEVELS["medium"])

    # --- Table of contents (always first) ---
    toc_items = ["CRITICAL WARNINGS", "EFFORT & LIMITS"]
    has_extensions = (
        extension_context is not None
        and extension_context.current.role.value != "unknown"
        and (extension_context.current.role.value == "extension"
             or extension_context.nearby_extensions)
    )
    if has_extensions:
        toc_items.insert(0, "EXTENSION ALERT")
    if detected_prefixes:
        toc_items.append("CUSTOM PREFIXES")
    toc_items.extend(["FORMAT & PATHS", "RECIPES", "RETURN FORMATS", "HELPERS LIST"])

    toc = "STRATEGY SECTIONS: " + " > ".join(toc_items)
    parts = [toc]

    # --- Extension alert (BEFORE everything else if present) ---
    if has_extensions:
        parts.append(_extension_strategy(extension_context))

    # --- Base strategy (critical warnings, recipes, helpers) ---
    parts.append(_BASE_STRATEGY)

    # --- Custom prefixes ---
    if detected_prefixes:
        parts.append(
            f"\nDETECTED CUSTOM PREFIXES: {detected_prefixes}\n"
            "These are non-standard name prefixes found in this codebase.\n"
            "Use them to identify custom objects, procedures, subscriptions, roles, etc.\n"
            "find_custom_modifications() uses them automatically."
        )

    # --- Effort & limits ---
    parts.append(f"\nEFFORT LEVEL: {effort}")
    parts.append(config.guidance)
    parts.append(
        f"Limits: max_execute_calls={config.max_execute_calls}, "
        f"max_llm_calls={config.max_llm_calls}, "
        f"safe_grep_max_files={config.safe_grep_max_files}"
    )

    # --- Format & paths ---
    if format_info is not None:
        fmt = getattr(format_info, "format_label", None)
        if fmt == "cf":
            parts.append(
                "\nFORMAT: CF detected.\n"
                "Example paths:\n"
                "  CommonModules/MyModule/Ext/Module.bsl\n"
                "  Documents/MyDoc/Ext/DocObject.bsl"
            )
        elif fmt == "edt":
            parts.append(
                "\nFORMAT: EDT detected.\n"
                "Example paths:\n"
                "  CommonModules/MyModule/Module.bsl\n"
                "  Documents/MyDoc/DocObject.bsl"
            )

    return "\n".join(parts)


def _extension_strategy(ext_context) -> str:
    """Build strategy text for extension context."""
    from rlm_tools_bsl.extension_detector import ConfigRole

    current = ext_context.current
    lines: list[str] = []

    if current.role == ConfigRole.MAIN and ext_context.nearby_extensions:
        ext_names = ", ".join(
            f"{e.name or '?'} (prefix: {e.name_prefix or '—'})"
            for e in ext_context.nearby_extensions
        )
        lines.append(
            f"\nCRITICAL — EXTENSIONS DETECTED: {ext_names}\n"
            "Extensions can OVERRIDE methods in this config via annotations:\n"
            "  &Перед (Before), &После (After), &Вместо (Instead), &ИзменениеИКонтроль (ChangeAndValidate)\n"
            "YOUR ANALYSIS MAY BE INCOMPLETE without checking extensions.\n"
            "YOU MUST:\n"
            "  1. When analyzing any object/module, call find_ext_overrides(ext_path, 'ObjectName')\n"
            "     to check if extensions override its methods.\n"
            "  2. In your final response, ALWAYS mention which methods are overridden by extensions.\n"
            "  3. If the user did not ask about extensions, still note: 'Extensions exist that may\n"
            "     modify this behavior' with the list of overridden methods.\n"
            "Extension paths (use with find_ext_overrides):"
        )
        for e in ext_context.nearby_extensions:
            lines.append(
                f"  - '{e.path}' ({e.name}, {e.purpose or '?'})"
            )

    elif current.role == ConfigRole.EXTENSION:
        name_label = current.name or "?"
        purpose_label = current.purpose or "unknown"
        prefix_label = current.name_prefix or "—"
        lines.append(
            f"\nCRITICAL — THIS IS AN EXTENSION, NOT A MAIN CONFIG.\n"
            f"Extension: '{name_label}' (purpose: {purpose_label}, prefix: {prefix_label})\n"
            "Objects with ObjectBelonging=Adopted are borrowed from the main config.\n"
            "Annotations &Перед/&После/&Вместо/&ИзменениеИКонтроль intercept main config methods.\n"
            "YOUR ANALYSIS IS INCOMPLETE without the main configuration.\n"
            "YOU MUST:\n"
            "  1. In your final response, clearly state that this is an EXTENSION, not the main config.\n"
            "  2. Warn the user that analysis of extension code alone may be misleading.\n"
            "  3. Call find_ext_overrides('', '') to list all intercepted methods in this extension."
        )
        if ext_context.nearby_main:
            lines.append(
                f"  Main config found nearby: {ext_context.nearby_main.name or '?'} "
                f"at {ext_context.nearby_main.path}"
            )

    return "\n".join(lines)


RLM_START_DESCRIPTION = (
    "Start a BSL code exploration session on a 1C codebase.\n"
    "Returns session_id, detected config format, BSL helper functions, and exploration strategy.\n"
    "IMPORTANT: For large 1C configs (23K+ files), NEVER grep on broad paths -- use find_module() first."
)

RLM_EXECUTE_DESCRIPTION = (
    "Execute Python code in the BSL sandbox. The 'code' parameter is Python code.\n"
    "Call helper functions and use print() to see results. Variables persist between calls.\n"
    "Example: code=\"modules = find_module('MyModule')\\nfor m in modules:\\n    print(m['path'])\"\n"
    "BSL helpers: help, find_module, find_by_type, extract_procedures, find_exports,\n"
    "safe_grep, read_procedure, find_callers, find_callers_context, parse_object_xml.\n"
    "Composite: analyze_object, analyze_subsystem, find_custom_modifications,\n"
    "find_event_subscriptions, find_scheduled_jobs, find_register_movements,\n"
    "find_register_writers, analyze_document_flow, find_based_on_documents,\n"
    "find_print_forms, find_functional_options, find_roles, find_enum_values.\n"
    "Standard: read_file, read_files, grep, grep_summary, grep_read, glob_files, tree.\n"
    "CRITICAL: grep on path='.' ALWAYS times out on large 1C configs. Use find_module() first."
)
