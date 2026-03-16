from __future__ import annotations
import concurrent.futures
import os
import re
import threading
import xml.etree.ElementTree as ET
from pathlib import Path
from rlm_tools_bsl.format_detector import parse_bsl_path, BslFileInfo, FormatInfo, METADATA_CATEGORIES
from rlm_tools_bsl.bsl_knowledge import BSL_PATTERNS
from rlm_tools_bsl.cache import load_index, save_index


# Namespace maps for 1C metadata XML
# CF format (Platform Export / Конфигуратор)
_NS_CF = {
    "md": "http://v8.1c.ru/8.3/MDClasses",
    "v8": "http://v8.1c.ru/8.1/data/core",
    "xr": "http://v8.1c.ru/8.3/xcf/readable",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
    "cfg": "http://v8.1c.ru/8.1/data/enterprise/current-config",
}

# MDO format (EDT / 1C:DT)
_NS_MDO = {
    "mdclass": "http://g5.1c.ru/v8/dt/metadata/mdclass",
    "mdext": "http://g5.1c.ru/v8/dt/metadata/mdclass/extension",
    "core": "http://g5.1c.ru/v8/dt/mcore",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
}

_MDO_NS_URI = "http://g5.1c.ru/v8/dt/metadata/mdclass"
_CF_NS_URI = "http://v8.1c.ru/8.3/MDClasses"

# Aliases for metadata categories: singular -> plural, Russian -> English
_CATEGORY_ALIASES: dict[str, str] = {
    # English singular -> plural
    "informationregister": "informationregisters",
    "accumulationregister": "accumulationregisters",
    "accountingregister": "accountingregisters",
    "calculationregister": "calculationregisters",
    "document": "documents",
    "catalog": "catalogs",
    "report": "reports",
    "dataprocessor": "dataprocessors",
    "commonmodule": "commonmodules",
    "constant": "constants",
    # Russian aliases
    "регистрсведений": "informationregisters",
    "регистрнакопления": "accumulationregisters",
    "регистрбухгалтерии": "accountingregisters",
    "регистррасчета": "calculationregisters",
    "документ": "documents",
    "справочник": "catalogs",
    "отчет": "reports",
    "обработка": "dataprocessors",
    "общиймодуль": "commonmodules",
    "константа": "constants",
}


def _normalize_category(meta_type: str) -> str:
    """Normalize a metadata category name to the canonical folder form."""
    key = meta_type.lower().replace(" ", "").replace("_", "")
    resolved = _CATEGORY_ALIASES.get(key)
    if resolved:
        return resolved
    # Fallback: if it doesn't end with 's', try adding 's'
    if not key.endswith("s"):
        candidate = key + "s"
        if candidate in {c.lower() for c in METADATA_CATEGORIES}:
            return candidate
    return key


def _xml_find_text(element, tag: str, ns: dict) -> str:
    """Find text of a child element, return '' if not found."""
    el = element.find(tag, ns)
    return el.text.strip() if el is not None and el.text else ""


def _xml_direct_text(element, child_name: str) -> str:
    """Find direct child by local name, return text."""
    for ch in element:
        local = ch.tag.split("}")[-1] if "}" in ch.tag else ch.tag
        if local == child_name:
            return ch.text.strip() if ch.text else ""
    return ""


# --- CF format helpers ---

def _cf_find_synonym(props, ns: dict = _NS_CF) -> str:
    """Extract ru synonym from CF Properties element."""
    syn = props.find("md:Synonym", ns)
    if syn is None:
        return ""
    for item in syn.findall("v8:item", ns):
        lang = _xml_find_text(item, "v8:lang", ns)
        if lang == "ru":
            return _xml_find_text(item, "v8:content", ns)
    return ""


def _cf_parse_type(props, ns: dict = _NS_CF) -> str:
    """Extract type string from CF <Type> element."""
    type_el = props.find("md:Type", ns)
    if type_el is None:
        return ""
    types = []
    for t in type_el.findall("v8:Type", ns):
        if t.text:
            types.append(t.text.strip())
    return ", ".join(types)


def _cf_parse_attributes(parent, ns: dict = _NS_CF) -> list[dict]:
    """Parse CF <Attribute> elements under parent."""
    attrs = []
    for attr_el in parent.findall("md:Attribute", ns):
        props = attr_el.find("md:Properties", ns)
        if props is None:
            continue
        attrs.append({
            "name": _xml_find_text(props, "md:Name", ns),
            "synonym": _cf_find_synonym(props, ns),
            "type": _cf_parse_type(props, ns),
        })
    return attrs


def _parse_cf_xml(root) -> dict:
    """Parse CF-format metadata XML (Platform Export / Конфигуратор)."""
    ns = _NS_CF

    meta_el = None
    for child in root:
        if child.find("md:Properties", ns) is not None:
            meta_el = child
            break
        if child.find("{http://v8.1c.ru/8.3/MDClasses}Properties") is not None:
            meta_el = child
            break
    if meta_el is None:
        for child in root:
            for sub in child:
                sub_tag = sub.tag.split("}")[-1] if "}" in sub.tag else sub.tag
                if sub_tag == "Properties":
                    meta_el = child
                    break
            if meta_el is not None:
                break

    if meta_el is None:
        return {"error": "Could not find metadata object in XML"}

    meta_tag = meta_el.tag.split("}")[-1] if "}" in meta_el.tag else meta_el.tag

    props = meta_el.find("md:Properties", ns)
    if props is None:
        for ch in meta_el:
            if ch.tag.endswith("Properties"):
                props = ch
                break

    result: dict = {
        "object_type": meta_tag,
        "name": _xml_find_text(props, "md:Name", ns) if props is not None else "",
        "synonym": _cf_find_synonym(props, ns) if props is not None else "",
    }

    # In CF format, Attribute/TabularSection/Dimension/Resource elements
    # can be either direct children of meta_el OR inside <ChildObjects>.
    child_objects = meta_el.find("md:ChildObjects", ns)
    search_el = child_objects if child_objects is not None else meta_el

    attributes = _cf_parse_attributes(search_el, ns)
    if attributes:
        result["attributes"] = attributes

    tab_sections = []
    for ts_el in search_el.findall("md:TabularSection", ns):
        ts_props = ts_el.find("md:Properties", ns)
        ts_name = _xml_find_text(ts_props, "md:Name", ns) if ts_props is not None else ""
        ts_synonym = _cf_find_synonym(ts_props, ns) if ts_props is not None else ""
        ts_attrs = _cf_parse_attributes(ts_el, ns)
        tab_sections.append({"name": ts_name, "synonym": ts_synonym, "attributes": ts_attrs})
    if tab_sections:
        result["tabular_sections"] = tab_sections

    dimensions = []
    for dim_el in search_el.findall("md:Dimension", ns):
        dim_props = dim_el.find("md:Properties", ns)
        if dim_props is not None:
            dimensions.append({
                "name": _xml_find_text(dim_props, "md:Name", ns),
                "synonym": _cf_find_synonym(dim_props, ns),
                "type": _cf_parse_type(dim_props, ns),
            })
    if dimensions:
        result["dimensions"] = dimensions

    resources = []
    for res_el in search_el.findall("md:Resource", ns):
        res_props = res_el.find("md:Properties", ns)
        if res_props is not None:
            resources.append({
                "name": _xml_find_text(res_props, "md:Name", ns),
                "synonym": _cf_find_synonym(res_props, ns),
                "type": _cf_parse_type(res_props, ns),
            })
    if resources:
        result["resources"] = resources

    if props is not None:
        content_el = props.find("md:Content", ns)
        if content_el is not None:
            items = []
            for item in content_el.findall("xr:Item", ns):
                if item.text:
                    items.append(item.text.strip())
            if items:
                result["content"] = items

    return result


# --- MDO format helpers ---

def _mdo_find_synonym(element) -> str:
    """Extract ru synonym from MDO element. MDO uses <synonym><key>ru</key><value>...</value></synonym>."""
    for syn in element:
        local = syn.tag.split("}")[-1] if "}" in syn.tag else syn.tag
        if local != "synonym":
            continue
        key = ""
        value = ""
        for ch in syn:
            ch_local = ch.tag.split("}")[-1] if "}" in ch.tag else ch.tag
            if ch_local == "key" and ch.text:
                key = ch.text.strip()
            elif ch_local == "value" and ch.text:
                value = ch.text.strip()
        if key == "ru":
            return value
    return ""


def _mdo_parse_type(element) -> str:
    """Extract type string from MDO element. MDO uses <type><types>...</types></type>."""
    for ch in element:
        local = ch.tag.split("}")[-1] if "}" in ch.tag else ch.tag
        if local != "type":
            continue
        types = []
        for t in ch:
            t_local = t.tag.split("}")[-1] if "}" in t.tag else t.tag
            if t_local == "types" and t.text:
                types.append(t.text.strip())
        if types:
            return ", ".join(types)
    return ""


def _mdo_parse_attributes(parent) -> list[dict]:
    """Parse MDO <attributes> elements under parent."""
    ns_uri = _MDO_NS_URI
    attrs = []
    for ch in parent:
        local = ch.tag.split("}")[-1] if "}" in ch.tag else ch.tag
        if local != "attributes":
            continue
        attrs.append({
            "name": _xml_direct_text(ch, "name"),
            "synonym": _mdo_find_synonym(ch),
            "type": _mdo_parse_type(ch),
        })
    return attrs


def _parse_mdo_xml(root) -> dict:
    """Parse MDO-format metadata XML (EDT / 1C:DT)."""
    meta_tag = root.tag.split("}")[-1] if "}" in root.tag else root.tag

    result: dict = {
        "object_type": meta_tag,
        "name": _xml_direct_text(root, "name"),
        "synonym": _mdo_find_synonym(root),
    }

    attributes = _mdo_parse_attributes(root)
    if attributes:
        result["attributes"] = attributes

    # Tabular sections: <tabularSections>
    tab_sections = []
    for ch in root:
        local = ch.tag.split("}")[-1] if "}" in ch.tag else ch.tag
        if local != "tabularSections":
            continue
        ts_attrs = _mdo_parse_attributes(ch)
        tab_sections.append({
            "name": _xml_direct_text(ch, "name"),
            "synonym": _mdo_find_synonym(ch),
            "attributes": ts_attrs,
        })
    if tab_sections:
        result["tabular_sections"] = tab_sections

    # Dimensions: <dimensions>
    dimensions = []
    for ch in root:
        local = ch.tag.split("}")[-1] if "}" in ch.tag else ch.tag
        if local != "dimensions":
            continue
        dimensions.append({
            "name": _xml_direct_text(ch, "name"),
            "synonym": _mdo_find_synonym(ch),
            "type": _mdo_parse_type(ch),
        })
    if dimensions:
        result["dimensions"] = dimensions

    # Resources: <resources>
    resources = []
    for ch in root:
        local = ch.tag.split("}")[-1] if "}" in ch.tag else ch.tag
        if local != "resources":
            continue
        resources.append({
            "name": _xml_direct_text(ch, "name"),
            "synonym": _mdo_find_synonym(ch),
            "type": _mdo_parse_type(ch),
        })
    if resources:
        result["resources"] = resources

    # Subsystem content: <content> direct children with text
    content_items = []
    for ch in root:
        local = ch.tag.split("}")[-1] if "}" in ch.tag else ch.tag
        if local == "content" and ch.text:
            content_items.append(ch.text.strip())
    if content_items:
        result["content"] = content_items

    # Forms, commands, templates — list names
    forms = []
    commands = []
    templates = []
    for ch in root:
        local = ch.tag.split("}")[-1] if "}" in ch.tag else ch.tag
        if local == "forms" and ch.text:
            forms.append(ch.text.strip())
        elif local == "commands" and ch.text:
            commands.append(ch.text.strip())
        elif local == "templates" and ch.text:
            templates.append(ch.text.strip())
    if forms:
        result["forms"] = forms
    if commands:
        result["commands"] = commands
    if templates:
        result["templates"] = templates

    return result


def parse_metadata_xml(xml_content: str) -> dict:
    """Parse 1C metadata XML and extract structure: name, synonym, attributes,
    tabular sections, subsystem content, dimensions, resources, etc.
    Auto-detects format: CF (Platform Export) or MDO (EDT/1C:DT)."""
    root = ET.fromstring(xml_content)

    # Detect format by root tag namespace
    root_ns = ""
    if "}" in root.tag:
        root_ns = root.tag.split("}")[0].lstrip("{")

    if root_ns == _MDO_NS_URI or _MDO_NS_URI in root_ns:
        # MDO format — root IS the metadata object
        return _parse_mdo_xml(root)
    else:
        # CF format — root is <MetaDataObject> wrapper
        return _parse_cf_xml(root)


# --- EventSubscription XML parsers ---

def _parse_cf_event_subscription(xml_content: str) -> dict | None:
    """Parse CF-format EventSubscription XML."""
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError:
        return None

    ns = _NS_CF
    sub_el = root.find("md:EventSubscription", ns)
    if sub_el is None:
        # Try without namespace
        for child in root:
            tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if tag == "EventSubscription":
                sub_el = child
                break
    if sub_el is None:
        return None

    props = sub_el.find("md:Properties", ns)
    if props is None:
        for ch in sub_el:
            if ch.tag.endswith("Properties"):
                props = ch
                break
    if props is None:
        return None

    name = _xml_find_text(props, "md:Name", ns)
    synonym = _cf_find_synonym(props, ns)
    event = _xml_find_text(props, "md:Event", ns)
    handler = _xml_find_text(props, "md:Handler", ns)

    # Source types: <Source><v8:Type>cfg:DocumentObject.Name</v8:Type>...</Source>
    source_types: list[str] = []
    source_el = props.find("md:Source", ns)
    if source_el is not None:
        for type_el in source_el.findall("v8:Type", ns):
            if type_el.text:
                raw = type_el.text.strip()
                # Strip cfg: prefix
                if raw.startswith("cfg:"):
                    raw = raw[4:]
                source_types.append(raw)

    return {
        "name": name,
        "synonym": synonym,
        "source_types": source_types,
        "event": event,
        "handler": handler,
    }


def _parse_mdo_event_subscription(xml_content: str) -> dict | None:
    """Parse EDT/MDO-format EventSubscription XML."""
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError:
        return None

    root_tag = root.tag.split("}")[-1] if "}" in root.tag else root.tag
    if root_tag != "EventSubscription":
        return None

    name = _xml_direct_text(root, "name")
    synonym = _mdo_find_synonym(root)
    event = _xml_direct_text(root, "event")
    handler = _xml_direct_text(root, "handler")

    # Source types: <source><types>DocumentObject.Name</types>...</source>
    source_types: list[str] = []
    for ch in root:
        local = ch.tag.split("}")[-1] if "}" in ch.tag else ch.tag
        if local == "source":
            for t in ch:
                t_local = t.tag.split("}")[-1] if "}" in t.tag else t.tag
                if t_local == "types" and t.text:
                    source_types.append(t.text.strip())
            break

    return {
        "name": name,
        "synonym": synonym,
        "source_types": source_types,
        "event": event,
        "handler": handler,
    }


def parse_event_subscription_xml(xml_content: str) -> dict | None:
    """Parse EventSubscription XML, auto-detecting CF or EDT format."""
    if _MDO_NS_URI in xml_content:
        return _parse_mdo_event_subscription(xml_content)
    return _parse_cf_event_subscription(xml_content)


# --- ScheduledJob XML parsers ---

def _parse_cf_scheduled_job(xml_content: str) -> dict | None:
    """Parse CF-format ScheduledJob XML."""
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError:
        return None

    ns = _NS_CF
    job_el = root.find("md:ScheduledJob", ns)
    if job_el is None:
        for child in root:
            tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if tag == "ScheduledJob":
                job_el = child
                break
    if job_el is None:
        return None

    props = job_el.find("md:Properties", ns)
    if props is None:
        for ch in job_el:
            if ch.tag.endswith("Properties"):
                props = ch
                break
    if props is None:
        return None

    name = _xml_find_text(props, "md:Name", ns)
    synonym = _cf_find_synonym(props, ns)
    method_name = _xml_find_text(props, "md:MethodName", ns)
    use_text = _xml_find_text(props, "md:Use", ns)
    predefined_text = _xml_find_text(props, "md:Predefined", ns)
    restart_count = _xml_find_text(props, "md:RestartCountOnFailure", ns)
    restart_interval = _xml_find_text(props, "md:RestartIntervalOnFailure", ns)

    return {
        "name": name,
        "synonym": synonym,
        "method_name": method_name,
        "use": use_text.lower() == "true" if use_text else True,
        "predefined": predefined_text.lower() == "true" if predefined_text else False,
        "restart_on_failure": {
            "count": int(restart_count) if restart_count else 0,
            "interval": int(restart_interval) if restart_interval else 0,
        },
    }


def _parse_mdo_scheduled_job(xml_content: str) -> dict | None:
    """Parse EDT/MDO-format ScheduledJob XML."""
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError:
        return None

    root_tag = root.tag.split("}")[-1] if "}" in root.tag else root.tag
    if root_tag != "ScheduledJob":
        return None

    name = _xml_direct_text(root, "name")
    synonym = _mdo_find_synonym(root)
    method_name = _xml_direct_text(root, "methodName")
    predefined_text = _xml_direct_text(root, "predefined")
    restart_count = _xml_direct_text(root, "restartCountOnFailure")
    restart_interval = _xml_direct_text(root, "restartIntervalOnFailure")

    return {
        "name": name,
        "synonym": synonym,
        "method_name": method_name,
        "use": True,  # EDT format doesn't have explicit <use> — defaults to true
        "predefined": predefined_text.lower() == "true" if predefined_text else False,
        "restart_on_failure": {
            "count": int(restart_count) if restart_count else 0,
            "interval": int(restart_interval) if restart_interval else 0,
        },
    }


def parse_scheduled_job_xml(xml_content: str) -> dict | None:
    """Parse ScheduledJob XML, auto-detecting CF or EDT format."""
    if _MDO_NS_URI in xml_content:
        return _parse_mdo_scheduled_job(xml_content)
    return _parse_cf_scheduled_job(xml_content)


# --- Enum XML parsers ---

def _parse_cf_enum(xml_content: str) -> dict | None:
    """Parse CF-format Enum XML."""
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError:
        return None

    ns = _NS_CF
    enum_el = root.find("md:Enum", ns)
    if enum_el is None:
        for child in root:
            tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if tag == "Enum":
                enum_el = child
                break
    if enum_el is None:
        return None

    props = enum_el.find("md:Properties", ns)
    if props is None:
        for ch in enum_el:
            if ch.tag.endswith("Properties"):
                props = ch
                break
    if props is None:
        return None

    name = _xml_find_text(props, "md:Name", ns)
    synonym = _cf_find_synonym(props, ns)

    # Enum values live in ChildObjects
    child_objects = enum_el.find("md:ChildObjects", ns)
    search_el = child_objects if child_objects is not None else enum_el

    values: list[dict] = []
    for ev_el in search_el.findall("md:EnumValue", ns):
        ev_props = ev_el.find("md:Properties", ns)
        if ev_props is None:
            for ch in ev_el:
                if ch.tag.endswith("Properties"):
                    ev_props = ch
                    break
        if ev_props is None:
            continue
        values.append({
            "name": _xml_find_text(ev_props, "md:Name", ns),
            "synonym": _cf_find_synonym(ev_props, ns),
        })

    return {"name": name, "synonym": synonym, "values": values}


def _parse_mdo_enum(xml_content: str) -> dict | None:
    """Parse EDT/MDO-format Enum XML."""
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError:
        return None

    root_tag = root.tag.split("}")[-1] if "}" in root.tag else root.tag
    if root_tag != "Enum":
        return None

    name = _xml_direct_text(root, "name")
    synonym = _mdo_find_synonym(root)

    values: list[dict] = []
    for ch in root:
        local = ch.tag.split("}")[-1] if "}" in ch.tag else ch.tag
        if local == "enumValues":
            val_name = _xml_direct_text(ch, "name")
            val_synonym = _mdo_find_synonym(ch)
            values.append({"name": val_name, "synonym": val_synonym})

    return {"name": name, "synonym": synonym, "values": values}


def parse_enum_xml(xml_content: str) -> dict | None:
    """Parse Enum XML, auto-detecting CF or EDT format."""
    if _MDO_NS_URI in xml_content:
        return _parse_mdo_enum(xml_content)
    return _parse_cf_enum(xml_content)


# --- FunctionalOption XML parsers ---

def _parse_cf_functional_option(xml_content: str) -> dict | None:
    """Parse CF-format FunctionalOption XML."""
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError:
        return None

    ns = _NS_CF
    fo_el = root.find("md:FunctionalOption", ns)
    if fo_el is None:
        for child in root:
            tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if tag == "FunctionalOption":
                fo_el = child
                break
    if fo_el is None:
        return None

    props = fo_el.find("md:Properties", ns)
    if props is None:
        for ch in fo_el:
            if ch.tag.endswith("Properties"):
                props = ch
                break
    if props is None:
        return None

    name = _xml_find_text(props, "md:Name", ns)
    synonym = _cf_find_synonym(props, ns)
    location = _xml_find_text(props, "md:Location", ns)

    # Content: <Content><xr:Object>...</xr:Object>...</Content>
    content: list[str] = []
    content_el = props.find("md:Content", ns)
    if content_el is not None:
        for obj_el in content_el.findall("xr:Object", ns):
            if obj_el.text:
                content.append(obj_el.text.strip())

    return {"name": name, "synonym": synonym, "location": location, "content": content}


def _parse_mdo_functional_option(xml_content: str) -> dict | None:
    """Parse EDT/MDO-format FunctionalOption XML."""
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError:
        return None

    root_tag = root.tag.split("}")[-1] if "}" in root.tag else root.tag
    if root_tag != "FunctionalOption":
        return None

    name = _xml_direct_text(root, "name")
    synonym = _mdo_find_synonym(root)
    location = _xml_direct_text(root, "location")

    content: list[str] = []
    for ch in root:
        local = ch.tag.split("}")[-1] if "}" in ch.tag else ch.tag
        if local == "content" and ch.text:
            content.append(ch.text.strip())

    return {"name": name, "synonym": synonym, "location": location, "content": content}


def parse_functional_option_xml(xml_content: str) -> dict | None:
    """Parse FunctionalOption XML, auto-detecting CF or EDT format."""
    if _MDO_NS_URI in xml_content:
        return _parse_mdo_functional_option(xml_content)
    return _parse_cf_functional_option(xml_content)


# --- Rights XML parser ---

_NS_RIGHTS = "http://v8.1c.ru/8.2/roles"


def parse_rights_xml(xml_content: str, object_filter: str = "") -> list[dict]:
    """Parse Rights XML (same format for CF and EDT).
    Returns only rights with <value>true</value>.
    Filters by object_filter substring if provided."""
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError:
        return []

    ns = {"r": _NS_RIGHTS}
    results: list[dict] = []

    for obj_el in root.findall("r:object", ns):
        obj_name_el = obj_el.find("r:name", ns)
        if obj_name_el is None or not obj_name_el.text:
            continue
        obj_name = obj_name_el.text.strip()

        if object_filter and object_filter not in obj_name:
            continue

        granted: list[str] = []
        for right_el in obj_el.findall("r:right", ns):
            right_name_el = right_el.find("r:name", ns)
            right_value_el = right_el.find("r:value", ns)
            if right_name_el is None or right_value_el is None:
                continue
            if right_value_el.text and right_value_el.text.strip().lower() == "true":
                granted.append(right_name_el.text.strip())

        if granted:
            results.append({"object": obj_name, "rights": granted})

    return results


def make_bsl_helpers(
    base_path: str,
    resolve_safe,      # callable: str -> pathlib.Path
    read_file_fn,      # callable: str -> str
    grep_fn,           # callable: (pattern, path) -> list[dict]
    glob_files_fn,     # callable: (pattern) -> list[str]
    format_info: FormatInfo | None = None,
) -> dict:
    """Creates BSL helper functions for sandbox namespace.
    Internal _bsl_index is built lazily on first find_module() call."""

    # Mutable closure state for lazy index
    _index_state: list = []          # list of tuples (relative_path, BslFileInfo)
    _index_built: list[bool] = [False]
    _index_lock = threading.Lock()

    def _ensure_index() -> None:
        if _index_built[0]:
            return
        with _index_lock:
            if _index_built[0]:
                return
            all_bsl = glob_files_fn("**/*.bsl")
            bsl_count = len(all_bsl)

            cached = load_index(base_path, bsl_count, bsl_paths=all_bsl)
            if cached is not None:
                _index_state.extend(cached)
            else:
                for file_path in all_bsl:
                    info = parse_bsl_path(file_path, base_path)
                    _index_state.append((info.relative_path, info))
                save_index(base_path, bsl_count, _index_state)

            _index_built[0] = True

    # --- Auto-detect custom prefixes from object names ---
    _detected_prefixes: list[str] = []
    _prefixes_built: list[bool] = [False]
    _prefixes_lock = threading.Lock()

    def _ensure_prefixes() -> list[str]:
        if _prefixes_built[0]:
            return _detected_prefixes
        with _prefixes_lock:
            if _prefixes_built[0]:
                return _detected_prefixes
            _ensure_index()

            # Collect unique object names from index
            object_names: set[str] = set()
            for _, info in _index_state:
                if info.object_name:
                    object_names.add(info.object_name)

            # Custom objects start with a lowercase letter in 1C conventions.
            # Extract prefix: sequence of lowercase letters (+ optional _) before
            # the first uppercase letter.
            prefix_re = re.compile(r'^([a-zа-яё]+_?)')
            prefix_counts: dict[str, int] = {}
            for name in object_names:
                if not name or not name[0].islower():
                    continue
                m = prefix_re.match(name)
                if m:
                    prefix = m.group(1)
                    # Normalize: strip trailing _ for counting, keep in result
                    key = prefix.rstrip("_").lower()
                    if len(key) >= 2:
                        prefix_counts[key] = prefix_counts.get(key, 0) + 1

            # Keep prefixes that appear 3+ times (not random one-off names)
            frequent = sorted(
                ((k, v) for k, v in prefix_counts.items() if v >= 3),
                key=lambda x: -x[1],
            )
            _detected_prefixes.clear()
            _detected_prefixes.extend(k for k, _ in frequent)

            _prefixes_built[0] = True
            return _detected_prefixes

    # --- Strip 1C metadata type prefixes from object names ---
    # Models often pass "Документ.РеализацияТоваровУслуг" instead of "РеализацияТоваровУслуг"
    _META_TYPE_PREFIXES = (
        "Документ.", "Справочник.", "Перечисление.", "РегистрСведений.",
        "РегистрНакопления.", "РегистрБухгалтерии.", "РегистрРасчета.",
        "Отчет.", "Обработка.", "ПланОбмена.", "ПланСчетов.",
        "ПланВидовХарактеристик.", "ПланВидовРасчета.", "БизнесПроцесс.",
        "Задача.", "Константа.", "ПодпискаНаСобытие.", "РегламентноеЗадание.",
        "Document.", "Catalog.", "Enum.", "InformationRegister.",
        "AccumulationRegister.", "AccountingRegister.", "CalculationRegister.",
        "Report.", "DataProcessor.", "ExchangePlan.", "ChartOfAccounts.",
        "ChartOfCharacteristicTypes.", "ChartOfCalculationTypes.",
        "BusinessProcess.", "Task.", "Constant.",
        "DocumentObject.", "CatalogObject.",
        "DocumentRef.", "CatalogRef.",
        "ДокументОбъект.", "СправочникОбъект.",
        "ДокументСсылка.", "СправочникСсылка.",
    )

    def _strip_meta_prefix(name: str) -> str:
        """Strip 1C metadata type prefix if present: 'Документ.X' -> 'X'."""
        for prefix in _META_TYPE_PREFIXES:
            if name.startswith(prefix):
                return name[len(prefix):]
        return name

    def _info_to_dict(relative_path: str, info: BslFileInfo) -> dict:
        return {
            "path": relative_path,
            "category": info.category,
            "object_name": info.object_name,
            "module_type": info.module_type,
            "form_name": info.form_name,
        }

    def find_module(name: str) -> list[dict]:
        """Find BSL modules by name fragment (case-insensitive).

        Returns: list of dicts {path, category, object_name, module_type, form_name}."""
        name = _strip_meta_prefix(name)
        _ensure_index()
        name_lower = name.lower()
        results = []
        for relative_path, info in _index_state:
            matched = False
            if info.object_name and name_lower in info.object_name.lower():
                matched = True
            if not matched and name_lower in relative_path.lower():
                matched = True
            if matched:
                results.append(_info_to_dict(relative_path, info))
            if len(results) >= 50:
                break
        return results

    def find_by_type(meta_type: str, name: str = "") -> list[dict]:
        """Find BSL modules by metadata category, optionally filtered by object name.

        Accepts plural folder names (InformationRegisters), singular (InformationRegister),
        and Russian names (РегистрСведений).
        Categories: CommonModules, Documents, Catalogs, InformationRegisters,
        AccumulationRegisters, AccountingRegisters, CalculationRegisters,
        Reports, DataProcessors, Constants.

        Returns: list of dicts {path, category, object_name, module_type, form_name}."""
        name = _strip_meta_prefix(name)
        _ensure_index()
        meta_type_lower = _normalize_category(meta_type)
        name_lower = name.lower()
        results = []
        for relative_path, info in _index_state:
            if not info.category or info.category.lower() != meta_type_lower:
                continue
            if name_lower and (not info.object_name or name_lower not in info.object_name.lower()):
                continue
            results.append(_info_to_dict(relative_path, info))
            if len(results) >= 50:
                break
        return results

    _proc_cache: dict[str, list[dict]] = {}
    _prefilter_cache: dict[str, list[tuple[str, BslFileInfo]]] = {}
    _cache_lock = threading.Lock()

    def extract_procedures(path: str) -> list[dict]:
        """Parse BSL file and return list of procedures/functions with metadata.
        Results are memoized per file path within the session.

        Returns: list of dicts {name, type, line, end_line, is_export, params}."""
        with _cache_lock:
            if path in _proc_cache:
                return _proc_cache[path]

        content = read_file_fn(path)
        lines = content.splitlines()

        proc_def_re = re.compile(BSL_PATTERNS["procedure_def"], re.IGNORECASE)
        proc_end_re = re.compile(BSL_PATTERNS["procedure_end"], re.IGNORECASE)

        procedures = []
        current: dict | None = None

        for line_idx, line in enumerate(lines):
            line_number = line_idx + 1  # 1-based

            if current is None:
                m = proc_def_re.search(line)
                if m:
                    proc_type = m.group(1)
                    proc_name = m.group(2)
                    params = m.group(3).strip() if m.group(3) else ""
                    is_export = m.group(4) is not None and m.group(4).strip() != ""
                    current = {
                        "name": proc_name,
                        "type": proc_type,
                        "line": line_number,
                        "is_export": is_export,
                        "end_line": None,
                        "params": params,
                    }
            else:
                m_end = proc_end_re.search(line)
                if m_end:
                    current["end_line"] = line_number
                    procedures.append(current)
                    current = None

        # Handle unclosed procedure at EOF
        if current is not None:
            current["end_line"] = len(lines)
            procedures.append(current)

        with _cache_lock:
            _proc_cache[path] = procedures
        return procedures

    def find_exports(path: str) -> list[dict]:
        """Return only exported procedures/functions from a BSL file.

        Returns: list of dicts {name, type, line, end_line, is_export, params}."""
        return [p for p in extract_procedures(path) if p["is_export"]]

    def safe_grep(pattern: str, name_hint: str = "", max_files: int = 20) -> list[dict]:
        """Timeout-safe grep across BSL files, optionally scoped by module name hint."""
        _ensure_index()

        if name_hint:
            candidates = find_module(name_hint)
            paths = [c["path"] for c in candidates[:max_files]]
        else:
            paths = [relative_path for relative_path, _ in _index_state[:max_files]]

        results = []
        for path in paths:
            try:
                matches = grep_fn(pattern, path)
                if matches:
                    results.extend(matches)
            except Exception:
                pass
        return results

    def read_procedure(path: str, proc_name: str) -> str | None:
        """Extract a single procedure body from a BSL file by name."""
        procedures = extract_procedures(path)
        target = None
        for p in procedures:
            if p["name"].lower() == proc_name.lower():
                target = p
                break
        if target is None:
            return None

        content = read_file_fn(path)
        lines = content.splitlines()

        start = target["line"] - 1  # convert to 0-based
        end = target["end_line"] if target["end_line"] is not None else len(lines)
        # end_line is 1-based and inclusive
        extracted = lines[start:end]
        return "\n".join(extracted)

    def find_callers(proc_name: str, module_hint: str = "", max_files: int = 20) -> list[dict]:
        """Find all callers of a procedure by name across BSL files.
        Delegates to find_callers_context for thorough cross-module search.

        Returns: list of dicts {file, line, text}."""
        result = find_callers_context(proc_name, module_hint, 0, max_files)
        return [
            {"file": c["file"], "line": c["line"], "text": c.get("context", "")}
            for c in result["callers"]
        ]

    # --- Parallel prefilter for find_callers_context ---
    _base = Path(base_path)

    def _parallel_prefilter(
        files: list[tuple[str, BslFileInfo]],
        needle: str,
        base: str,
        max_workers: int = 12,
    ) -> list[tuple[str, BslFileInfo]]:
        """Scan all BSL files for substring in parallel using ThreadPoolExecutor.
        Bypasses sandbox read_file to avoid cache contention between threads.
        All paths come from the trusted index (built from glob inside base_path)."""
        base_p = Path(base)

        def _check(item: tuple[str, BslFileInfo]) -> tuple[str, BslFileInfo] | None:
            rel, info = item
            try:
                full = base_p / rel
                with open(full, "r", encoding="utf-8-sig", errors="replace") as f:
                    content = f.read()
                if needle in content.lower():
                    return (rel, info)
            except Exception:
                pass
            return None

        matched: list[tuple[str, BslFileInfo]] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
            for result in pool.map(_check, files):
                if result is not None:
                    matched.append(result)
        return matched

    # --- Regex for stripping comments and string literals ---
    _re_string_literal = re.compile(r'"[^"\r\n]*"')

    def _strip_code_line(line: str) -> str:
        """Remove comments and string literals from a BSL code line."""
        # Strip comment (// with or without space)
        ci = line.find("//")
        if ci >= 0:
            line = line[:ci]
        # Strip string literals
        line = _re_string_literal.sub("", line)
        return line

    def find_callers_context(
        proc_name: str,
        module_hint: str = "",
        offset: int = 0,
        limit: int = 50,
    ) -> dict:
        """Find callers of a procedure with full context: which procedure
        in which module calls the target. Returns structured result with
        caller_name, caller_is_export, file metadata, and pagination info.

        Unlike find_callers() which is a flat grep, this helper identifies
        the exact calling procedure and filters out comments/strings.

        Args:
            proc_name: Name of the target procedure/function.
            module_hint: Optional module name to determine export scope.
            offset: File offset for pagination (0-based).
            limit: Max files to scan per call (default 50).

        Returns:
            dict with "callers" list and "_meta" pagination info.
        """
        _ensure_index()

        name_esc = re.escape(proc_name)
        # Patterns: direct call, qualified call (Module.Proc)
        call_patterns = [
            re.compile(r"(?<!\w)" + name_esc + r"\s*\(", re.IGNORECASE),
            re.compile(r"\." + name_esc + r"\s*\(", re.IGNORECASE),
            re.compile(r"(?<!\w)" + name_esc + r"(?!\w)", re.IGNORECASE),
        ]

        # --- Step 1: Determine scope based on export status ---
        target_files: list[str] | None = None  # None = search all

        if module_hint:
            hint_modules = find_module(module_hint)
            if hint_modules:
                # Find the target procedure in hint modules
                for hm in hint_modules:
                    try:
                        procs = extract_procedures(hm["path"])
                        for p in procs:
                            if p["name"].lower() == proc_name.lower():
                                if not p["is_export"] or "Form" in (hm.get("module_type") or ""):
                                    # Not exported or form module -> only search same file
                                    target_files = [hm["path"]]
                                break
                    except Exception:
                        pass
                    if target_files is not None:
                        break

        # --- Step 2: Build candidate file list ---
        if target_files is not None:
            # Scoped to specific files (non-export or form)
            candidate_files = [
                (rel, info)
                for rel, info in _index_state
                if rel in target_files
            ]
        else:
            candidate_files = list(_index_state)

        # --- Step 3: Prefilter by substring (parallel scan, cached) ---
        proc_lower = proc_name.lower()

        if target_files is not None:
            # Scoped search — don't use global prefilter cache
            filtered_files: list[tuple[str, BslFileInfo]] = []
            for rel, info in candidate_files:
                try:
                    content = read_file_fn(rel)
                    if proc_lower in content.lower():
                        filtered_files.append((rel, info))
                except Exception:
                    pass
        else:
            with _cache_lock:
                if proc_lower in _prefilter_cache:
                    filtered_files = _prefilter_cache[proc_lower]
                else:
                    filtered_files = None
            if filtered_files is None:
                filtered_files = _parallel_prefilter(
                    candidate_files, proc_lower, base_path,
                )
                with _cache_lock:
                    _prefilter_cache[proc_lower] = filtered_files

        total_files = len(filtered_files)

        # --- Step 4: Apply pagination ---
        page_files = filtered_files[offset:offset + limit]
        scanned_files = len(page_files)

        # --- Step 5: Scan each file for callers ---
        callers: list[dict] = []

        for rel, info in page_files:
            try:
                content = read_file_fn(rel)
                lines = content.splitlines()
                procs = extract_procedures(rel)

                for proc in procs:
                    # Skip the definition line itself
                    body_start = proc["line"]  # 1-based, this is the def line
                    body_end = proc["end_line"] if proc["end_line"] else len(lines)

                    for line_idx in range(body_start, body_end):  # body_start is def line (skip it)
                        if line_idx >= len(lines):
                            break
                        raw_line = lines[line_idx]
                        cleaned = _strip_code_line(raw_line)
                        if not cleaned.strip():
                            continue

                        for pattern in call_patterns:
                            if pattern.search(cleaned):
                                callers.append({
                                    "file": rel,
                                    "caller_name": proc["name"],
                                    "caller_is_export": proc["is_export"],
                                    "line": line_idx + 1,  # 1-based
                                    "context": raw_line.rstrip(),
                                    "object_name": info.object_name,
                                    "category": info.category,
                                    "module_type": info.module_type,
                                })
                                break  # one match per line is enough
            except Exception:
                pass

        return {
            "callers": callers,
            "_meta": {
                "total_files": total_files,
                "scanned_files": scanned_files,
                "has_more": (offset + limit) < total_files,
            },
        }

    def parse_object_xml(path: str) -> dict:
        """Read a 1C metadata XML file and extract its structure:
        name, synonym, attributes, tabular sections, dimensions, resources,
        subsystem content. Works with any metadata XML (catalogs, documents,
        registers, subsystems, etc.).

        Returns: dict with keys like name, synonym, attributes, tabular_sections,
        dimensions, resources (depends on metadata type)."""
        content = read_file_fn(path)
        return parse_metadata_xml(content)

    # ── Composite helpers (wrappers over existing functions) ────────

    def analyze_subsystem(name: str) -> dict:
        """Find a subsystem by name, parse its XML composition,
        classify objects as custom (non-standard prefix) or standard.

        Returns: dict with subsystems_found, subsystems list."""
        name = _strip_meta_prefix(name)
        patterns = [
            f"**/Subsystems/**/*{name}*",
            f"**/Subsystems/*{name}*",
            f"**/*{name}*.mdo",
        ]
        found_files: list[str] = []
        for p in patterns:
            found_files.extend(glob_files_fn(p))

        subsystem_files = list(dict.fromkeys(
            f for f in found_files
            if "Subsystem" in f and (f.endswith(".xml") or f.endswith(".mdo"))
        ))

        if not subsystem_files:
            return {
                "error": f"Подсистема '{name}' не найдена",
                "hint": "Попробуйте glob_files('**/Subsystems/**') для просмотра всех подсистем",
            }

        results = []
        for sf in subsystem_files:
            try:
                meta = parse_object_xml(sf)
            except Exception:
                continue
            if not meta or meta.get("object_type") != "Subsystem":
                continue

            content = meta.get("content", [])
            custom_objects = []
            standard_objects = []
            for item in content:
                parts = item.split(".", 1)
                obj_type = parts[0] if parts else ""
                obj_name = parts[1] if len(parts) > 1 else item
                is_custom = bool(obj_name) and obj_name[0].islower()
                entry = {"type": obj_type, "name": obj_name, "is_custom": is_custom}
                if is_custom:
                    custom_objects.append(entry)
                else:
                    standard_objects.append(entry)

            results.append({
                "file": sf,
                "name": meta.get("name", ""),
                "synonym": meta.get("synonym", ""),
                "total_objects": len(content),
                "custom_objects": custom_objects,
                "standard_objects": standard_objects,
                "raw_content": content,
            })

        return {"subsystems_found": len(results), "subsystems": results}

    def find_custom_modifications(
        object_name: str,
        custom_prefixes: list[str] | None = None,
    ) -> dict:
        """Find all non-standard (custom) modifications in an object's modules:
        procedures with custom prefix, custom #Область regions, custom XML attributes.
        If custom_prefixes is not provided, uses auto-detected prefixes from the codebase.

        Returns: dict with modifications list and custom_attributes."""
        object_name = _strip_meta_prefix(object_name)
        prefixes = custom_prefixes or _ensure_prefixes()
        if not prefixes:
            return {"error": "Нетиповые префиксы не обнаружены. Укажите custom_prefixes вручную."}

        modules = find_module(object_name)
        exact = [m for m in modules if (m.get("object_name") or "").lower() == object_name.lower()]
        if not exact:
            exact = modules
        if not exact:
            return {"error": f"Объект '{object_name}' не найден"}

        def _match_prefix(s: str) -> bool:
            sl = s.lower()
            return any(sl.startswith(p.lower()) for p in prefixes)

        modifications = []
        for mod in exact:
            path = mod["path"]
            try:
                procs = extract_procedures(path)
            except Exception:
                continue

            custom_procs = [p for p in procs if _match_prefix(p["name"])]

            custom_regions: list[dict] = []
            try:
                content = read_file_fn(path)
                for i, line in enumerate(content.splitlines(), 1):
                    stripped = line.strip()
                    if stripped.startswith("#") and "Область" in stripped:
                        region_name = stripped.split("Область", 1)[1].strip()
                        if _match_prefix(region_name):
                            custom_regions.append({"name": region_name, "line": i})
            except Exception:
                pass

            if custom_procs or custom_regions:
                modifications.append({
                    "path": path,
                    "module_type": mod.get("module_type", ""),
                    "form_name": mod.get("form_name"),
                    "total_procedures": len(procs),
                    "custom_procedures": custom_procs,
                    "custom_regions": custom_regions,
                })

        custom_attributes: list[dict] = []
        category = exact[0].get("category", "")
        obj_name = exact[0].get("object_name", "")
        if category and obj_name:
            for xp in [f"{category}/{obj_name}.xml", f"{category}/{obj_name}.mdo", f"{category}/{obj_name}/{obj_name}.mdo"]:
                try:
                    meta = parse_object_xml(xp)
                    for attr in meta.get("attributes", []):
                        if _match_prefix(attr["name"]):
                            custom_attributes.append(attr)
                    for ts in meta.get("tabular_sections", []):
                        if _match_prefix(ts["name"]):
                            custom_attributes.append({
                                "name": ts["name"],
                                "type": "TabularSection",
                                "synonym": ts.get("synonym", ""),
                            })
                    break
                except Exception:
                    continue

        return {
            "object_name": object_name,
            "modules_analyzed": len(exact),
            "modifications": modifications,
            "custom_attributes": custom_attributes,
        }

    def analyze_object(name: str) -> dict:
        """Full object profile in one call: XML metadata + all modules + procedures + exports.

        Returns: dict with name, category, metadata, modules."""
        name = _strip_meta_prefix(name)
        modules = find_module(name)
        exact = [m for m in modules if (m.get("object_name") or "").lower() == name.lower()]
        if not exact:
            exact = modules[:20]
        if not exact:
            return {"error": f"Объект '{name}' не найден"}

        category = exact[0].get("category", "")
        obj_name = exact[0].get("object_name", "")

        metadata: dict = {}
        if category and obj_name:
            for xp in [f"{category}/{obj_name}.xml", f"{category}/{obj_name}.mdo", f"{category}/{obj_name}/{obj_name}.mdo"]:
                try:
                    metadata = parse_object_xml(xp)
                    break
                except Exception:
                    continue

        module_details = []
        for mod in exact:
            path = mod["path"]
            try:
                procs = extract_procedures(path)
                exports = [p for p in procs if p.get("is_export")]
            except Exception:
                procs, exports = [], []

            module_details.append({
                "path": path,
                "module_type": mod.get("module_type", ""),
                "form_name": mod.get("form_name"),
                "procedures_count": len(procs),
                "exports_count": len(exports),
                "procedures": procs,
                "exports": exports,
            })

        return {
            "name": obj_name,
            "category": category,
            "metadata": metadata,
            "modules": module_details,
        }

    # ── Business-process helpers ─────────────────────────────────

    _event_sub_cache: list[dict] = []
    _event_sub_built: list[bool] = [False]

    def _ensure_event_subscriptions() -> list[dict]:
        if _event_sub_built[0]:
            return _event_sub_cache

        files = glob_files_fn("**/EventSubscriptions/**/*.xml")
        files.extend(glob_files_fn("**/EventSubscriptions/**/*.mdo"))
        # Deduplicate
        files = list(dict.fromkeys(files))

        for f in files:
            try:
                content = read_file_fn(f)
            except Exception:
                continue
            parsed = parse_event_subscription_xml(content)
            if parsed is None:
                continue
            # Parse handler into module + procedure
            handler = parsed["handler"]
            parts = handler.rsplit(".", 1)
            handler_procedure = parts[-1] if parts else handler
            # Module: everything before the last dot, but skip "CommonModule." prefix
            handler_module = ""
            if len(parts) > 1:
                module_part = parts[0]
                if module_part.startswith("CommonModule."):
                    module_part = module_part[len("CommonModule."):]
                handler_module = module_part

            _event_sub_cache.append({
                "name": parsed["name"],
                "synonym": parsed["synonym"],
                "source_types": parsed["source_types"],
                "source_count": len(parsed["source_types"]),
                "event": parsed["event"],
                "handler": handler,
                "handler_module": handler_module,
                "handler_procedure": handler_procedure,
                "file": f,
            })

        _event_sub_built[0] = True
        return _event_sub_cache

    def find_event_subscriptions(
        object_name: str = "",
        custom_only: bool = False,
    ) -> list[dict]:
        """Find event subscriptions, optionally filtered by object name.
        Shows what fires when an object is written/posted/deleted.

        Args:
            object_name: Object name to filter by (case-insensitive substring
                         match against source types). Empty = return all.
            custom_only: If True, return only subscriptions whose name starts
                         with a detected custom prefix (auto-detected from codebase).

        Returns: list of dicts with name, synonym, source_count, event,
                 handler, handler_module, handler_procedure, file."""
        if object_name:
            object_name = _strip_meta_prefix(object_name)
        all_subs = _ensure_event_subscriptions()

        if not object_name:
            # Return without source_types to keep output compact
            result = [
                {k: v for k, v in s.items() if k != "source_types"}
                for s in all_subs
            ]
        else:
            name_lower = object_name.lower()
            result = []
            for s in all_subs:
                # Include subscriptions that explicitly list this object in source_types,
                # OR subscriptions with empty source_types (source_count=0) — these apply
                # to all objects of a given type (catch-all subscriptions).
                if not s["source_types"]:
                    matched = True
                else:
                    matched = any(name_lower in t.lower() for t in s["source_types"])
                if matched:
                    result.append(dict(s))  # include source_types for filtered results

        if custom_only:
            prefixes = _ensure_prefixes()
            if prefixes:
                result = [
                    s for s in result
                    if any(s["name"].lower().startswith(p) for p in prefixes)
                ]

        return result

    _sched_job_cache: list[dict] = []
    _sched_job_built: list[bool] = [False]

    def _ensure_scheduled_jobs() -> list[dict]:
        if _sched_job_built[0]:
            return _sched_job_cache

        files = glob_files_fn("**/ScheduledJobs/**/*.xml")
        files.extend(glob_files_fn("**/ScheduledJobs/**/*.mdo"))
        files = list(dict.fromkeys(files))

        for f in files:
            try:
                content = read_file_fn(f)
            except Exception:
                continue
            parsed = parse_scheduled_job_xml(content)
            if parsed is None:
                continue

            method = parsed["method_name"]
            parts = method.rsplit(".", 1)
            handler_procedure = parts[-1] if parts else method
            handler_module = ""
            if len(parts) > 1:
                module_part = parts[0]
                if module_part.startswith("CommonModule."):
                    module_part = module_part[len("CommonModule."):]
                handler_module = module_part

            _sched_job_cache.append({
                "name": parsed["name"],
                "synonym": parsed["synonym"],
                "method_name": method,
                "handler_module": handler_module,
                "handler_procedure": handler_procedure,
                "use": parsed["use"],
                "predefined": parsed["predefined"],
                "restart_on_failure": parsed["restart_on_failure"],
                "file": f,
            })

        _sched_job_built[0] = True
        return _sched_job_cache

    def find_scheduled_jobs(name: str = "") -> list[dict]:
        """Find scheduled (background) jobs, optionally filtered by name.

        Args:
            name: Name substring to filter by (case-insensitive). Empty = all.

        Returns: list of dicts with name, synonym, method_name,
                 handler_module, handler_procedure, use, predefined, file."""
        if name:
            name = _strip_meta_prefix(name)
        all_jobs = _ensure_scheduled_jobs()
        if not name:
            return all_jobs
        name_lower = name.lower()
        return [j for j in all_jobs if name_lower in j["name"].lower()]

    def find_register_movements(document_name: str) -> dict:
        """Find all registers that a document writes to during posting.
        Searches ObjectModule code for 'Движения.RegisterName' pattern.

        Args:
            document_name: Document name (or fragment).

        Returns: dict with document, code_registers, modules_scanned."""
        document_name = _strip_meta_prefix(document_name)
        modules = find_by_type("Documents", document_name)
        obj_modules = [m for m in modules if m.get("module_type") == "ObjectModule"]

        if not obj_modules:
            return {
                "document": document_name,
                "code_registers": [],
                "modules_scanned": [],
                "error": f"ObjectModule для документа '{document_name}' не найден",
            }

        movement_re = re.compile(r"Движения\.(\w+)", re.IGNORECASE)
        code_registers: dict[str, dict] = {}  # name -> {name, lines, file}
        modules_scanned: list[str] = []

        for mod in obj_modules:
            path = mod["path"]
            modules_scanned.append(path)
            try:
                content = read_file_fn(path)
            except Exception:
                continue
            for i, line in enumerate(content.splitlines(), 1):
                for m in movement_re.finditer(line):
                    reg_name = m.group(1)
                    if reg_name not in code_registers:
                        code_registers[reg_name] = {
                            "name": reg_name,
                            "lines": [],
                            "file": path,
                        }
                    if i not in code_registers[reg_name]["lines"]:
                        code_registers[reg_name]["lines"].append(i)

        result = {
            "document": document_name,
            "code_registers": list(code_registers.values()),
            "modules_scanned": modules_scanned,
        }

        # ── ERP framework fallback ──────────────────────────────
        # Look for ManagerModule to find ERP-style movement definitions
        mgr_modules = [m for m in modules if m.get("module_type") == "ManagerModule"]
        erp_mechanisms: list[str] = []
        manager_tables: list[str] = []
        adapted_registers: list[str] = []

        for mod in mgr_modules:
            mgr_path = mod["path"]
            try:
                mgr_content = read_file_fn(mgr_path)
            except Exception:
                continue

            # ЗарегистрироватьУчетныеМеханизмы → МеханизмыДокумента.Добавить("X")
            mech_body = read_procedure(mgr_path, "ЗарегистрироватьУчетныеМеханизмы")
            if mech_body:
                mech_re = re.compile(r'МеханизмыДокумента\.Добавить\("(\w+)"\)', re.IGNORECASE)
                for m in mech_re.finditer(mech_body):
                    if m.group(1) not in erp_mechanisms:
                        erp_mechanisms.append(m.group(1))

            # ТекстЗапросаТаблицаXxx function names
            table_re = re.compile(r'(?:Функция|Процедура)\s+ТекстЗапросаТаблица(\w+)\s*\(', re.IGNORECASE)
            for m in table_re.finditer(mgr_content):
                table_name = m.group(1)
                if table_name not in manager_tables:
                    manager_tables.append(table_name)

            # АдаптированныйТекстЗапросаДвиженийПоРегистру → ИмяРегистра = "X"
            adapted_body = read_procedure(mgr_path, "АдаптированныйТекстЗапросаДвиженийПоРегистру")
            if adapted_body:
                reg_re = re.compile(r'ИмяРегистра\s*=\s*"(\w+)"', re.IGNORECASE)
                for m in reg_re.finditer(adapted_body):
                    if m.group(1) not in adapted_registers:
                        adapted_registers.append(m.group(1))

        result["erp_mechanisms"] = erp_mechanisms
        result["manager_tables"] = manager_tables
        result["adapted_registers"] = adapted_registers

        return result

    def find_register_writers(register_name: str) -> dict:
        """Find all documents that write to a specific register.
        Searches all document ObjectModules for 'Движения.RegisterName'.

        Args:
            register_name: Register name to search for.

        Returns: dict with register, writers, total_documents_scanned, total_writers."""
        register_name = _strip_meta_prefix(register_name)
        _ensure_index()
        # Collect all document ObjectModule files
        doc_modules = [
            (rel, info) for rel, info in _index_state
            if info.category and info.category.lower() == "documents"
            and info.module_type == "ObjectModule"
        ]

        needle = f"движения.{register_name}".lower()
        matched = _parallel_prefilter(doc_modules, needle, base_path)

        movement_re = re.compile(
            r"Движения\." + re.escape(register_name), re.IGNORECASE
        )
        writers: list[dict] = []
        for rel, info in matched:
            try:
                content = read_file_fn(rel)
            except Exception:
                continue
            lines: list[int] = []
            for i, line in enumerate(content.splitlines(), 1):
                if movement_re.search(line):
                    lines.append(i)
            if lines:
                writers.append({
                    "document": info.object_name or "",
                    "file": rel,
                    "lines": lines,
                })

        return {
            "register": register_name,
            "writers": writers,
            "total_documents_scanned": len(doc_modules),
            "total_writers": len(writers),
        }

    def analyze_document_flow(document_name: str) -> dict:
        """Full document lifecycle analysis: metadata, event subscriptions,
        register movements, and related scheduled jobs.

        Args:
            document_name: Document name (or fragment).

        Returns: dict with document, metadata, event_subscriptions,
                 register_movements, related_scheduled_jobs."""
        document_name = _strip_meta_prefix(document_name)
        obj = analyze_object(document_name)
        subs = find_event_subscriptions(document_name)
        movements = find_register_movements(document_name)

        # Find scheduled jobs referencing this document
        all_jobs = find_scheduled_jobs()
        doc_lower = document_name.lower()
        related_jobs = [
            j for j in all_jobs
            if doc_lower in j.get("method_name", "").lower()
            or doc_lower in j.get("name", "").lower()
        ]

        return {
            "document": obj.get("name", document_name),
            "metadata": obj.get("metadata", {}),
            "event_subscriptions": subs,
            "register_movements": movements,
            "related_scheduled_jobs": related_jobs,
        }

    # ── Based-on documents / Print forms helpers ───────────────

    def find_based_on_documents(document_name: str) -> dict:
        """Find what documents can be created FROM this document and what it can be created FROM.

        Parses ДобавитьКомандыСозданияНаОсновании in ManagerModule and
        ОбработкаЗаполнения in ObjectModule.

        Returns: dict with document, can_create_from_here, can_be_created_from."""
        document_name = _strip_meta_prefix(document_name)
        result: dict = {
            "document": document_name,
            "can_create_from_here": [],
            "can_be_created_from": [],
        }

        modules = find_by_type("Documents", document_name)

        # --- ManagerModule: ДобавитьКомандыСозданияНаОсновании ---
        mgr_modules = [m for m in modules if m.get("module_type") == "ManagerModule"]
        for mod in mgr_modules:
            path = mod["path"]
            body = read_procedure(path, "ДобавитьКомандыСозданияНаОсновании")
            if body:
                create_re = re.compile(r"Документы\.(\w+)\.ДобавитьКоманду\w*НаОснован", re.IGNORECASE)
                for m in create_re.finditer(body):
                    result["can_create_from_here"].append({
                        "document": m.group(1),
                        "file": path,
                    })

        # --- ObjectModule: ОбработкаЗаполнения ---
        obj_modules = [m for m in modules if m.get("module_type") == "ObjectModule"]
        for mod in obj_modules:
            path = mod["path"]
            body = read_procedure(path, "ОбработкаЗаполнения")
            if body:
                type_re = re.compile(r'Тип\("(\w+Ссылка\.\w+)"\)', re.IGNORECASE)
                for m in type_re.finditer(body):
                    result["can_be_created_from"].append({
                        "type": m.group(1),
                        "file": path,
                    })

        return result

    def find_print_forms(object_name: str) -> dict:
        """Find print forms registered for an object by parsing ДобавитьКомандыПечати in ManagerModule.

        Returns: dict with object, print_forms list."""
        object_name = _strip_meta_prefix(object_name)
        result: dict = {
            "object": object_name,
            "print_forms": [],
        }

        modules = find_by_type("Documents", object_name)
        mgr_modules = [m for m in modules if m.get("module_type") == "ManagerModule"]
        if not mgr_modules:
            # Try broader search (Catalogs, DataProcessors, etc.)
            modules = find_module(object_name)
            mgr_modules = [m for m in modules if m.get("module_type") == "ManagerModule"]

        for mod in mgr_modules:
            path = mod["path"]
            body = read_procedure(path, "ДобавитьКомандыПечати")
            if body:
                print_re = re.compile(
                    r'ДобавитьКомандуПечати\([^,]+,\s*"(\w+)"(?:,\s*НСтр\("ru\s*=\s*\'([^\']+)\')?',
                    re.IGNORECASE,
                )
                for m in print_re.finditer(body):
                    result["print_forms"].append({
                        "name": m.group(1),
                        "presentation": m.group(2) or "",
                        "file": path,
                    })

        return result

    # ── Enum / FunctionalOption / Roles helpers ──────────────────

    def find_enum_values(enum_name: str) -> dict:
        """Find an enumeration by name and return its values.

        Args:
            enum_name: Enum name (or fragment).

        Returns: dict with name, synonym, values, file — or error."""
        enum_name = _strip_meta_prefix(enum_name)
        patterns = [
            f"**/Enums/**/*{enum_name}*.xml",
            f"**/Enums/**/*{enum_name}*.mdo",
        ]
        found_files: list[str] = []
        for p in patterns:
            found_files.extend(glob_files_fn(p))
        found_files = list(dict.fromkeys(found_files))

        for f in found_files:
            try:
                content = read_file_fn(f)
            except Exception:
                continue
            parsed = parse_enum_xml(content)
            if parsed is None:
                continue
            if enum_name.lower() in parsed["name"].lower():
                parsed["file"] = f
                return parsed

        return {"error": f"Перечисление '{enum_name}' не найдено"}

    _fo_cache: list[dict] = []
    _fo_built: list[bool] = [False]

    def _ensure_functional_options() -> list[dict]:
        if _fo_built[0]:
            return _fo_cache

        files = glob_files_fn("**/FunctionalOptions/**/*.xml")
        files.extend(glob_files_fn("**/FunctionalOptions/**/*.mdo"))
        files.extend(glob_files_fn("**/FunctionalOptions/*.xml"))
        files.extend(glob_files_fn("**/FunctionalOptions/*.mdo"))
        files = list(dict.fromkeys(files))

        for f in files:
            try:
                content = read_file_fn(f)
            except Exception:
                continue
            parsed = parse_functional_option_xml(content)
            if parsed is None:
                continue
            parsed["file"] = f
            _fo_cache.append(parsed)

        _fo_built[0] = True
        return _fo_cache

    def find_functional_options(object_name: str) -> dict:
        """Find functional options that affect a given object.
        Also greps BSL modules for ПолучитьФункциональнуюОпцию("X") pattern.

        Args:
            object_name: Object name to search for in FO content lists.

        Returns: dict with object, xml_options, code_options."""
        object_name = _strip_meta_prefix(object_name)
        all_fo = _ensure_functional_options()

        name_lower = object_name.lower()
        xml_options: list[dict] = []
        for fo in all_fo:
            matched = any(name_lower in c.lower() for c in fo.get("content", []))
            if matched:
                xml_options.append(dict(fo))

        # Grep for ПолучитьФункциональнуюОпцию in BSL code
        code_options: list[dict] = []
        try:
            grep_results = safe_grep("ПолучитьФункциональнуюОпцию", name_hint=object_name)
            for r in grep_results:
                text = r.get("text", "") or r.get("content", "")
                # Extract option name from ПолучитьФункциональнуюОпцию("OptionName")
                m = re.search(r'ПолучитьФункциональнуюОпцию\(\s*"([^"]+)"', text)
                if m:
                    code_options.append({
                        "option_name": m.group(1),
                        "file": r.get("file", ""),
                        "line": r.get("line", 0),
                    })
        except Exception:
            pass

        return {
            "object": object_name,
            "xml_options": xml_options,
            "code_options": code_options,
        }

    def find_roles(object_name: str) -> dict:
        """Find roles that grant rights to a given object.

        Args:
            object_name: Object name substring to filter rights by.

        Returns: dict with object, roles list."""
        object_name = _strip_meta_prefix(object_name)
        patterns = [
            "**/Roles/*/Ext/Rights.xml",
            "**/Roles/*/*.rights",
        ]
        found_files: list[str] = []
        for p in patterns:
            found_files.extend(glob_files_fn(p))
        found_files = list(dict.fromkeys(found_files))

        roles: list[dict] = []
        for f in found_files:
            # Extract role name from path: Roles/RoleName/Ext/Rights.xml
            parts = f.replace("\\", "/").split("/")
            role_name = ""
            for i, part in enumerate(parts):
                if part == "Roles" and i + 1 < len(parts):
                    role_name = parts[i + 1]
                    break

            try:
                content = read_file_fn(f)
            except Exception:
                continue
            rights = parse_rights_xml(content, object_name)
            for r in rights:
                roles.append({
                    "role_name": role_name,
                    "object": r["object"],
                    "rights": r["rights"],
                    "file": f,
                })

        return {"object": object_name, "roles": roles}

    # ── Help recipes ─────────────────────────────────────────────

    _help_recipes: dict[str, dict] = {
        "exports": {
            "keywords": ["export", "экспорт", "find_exports", "процедур", "функци"],
            "text": (
                "FIND EXPORTS:\n"
                "  modules = find_module('Name')  # replace 'Name'\n"
                "  path = modules[0]['path']\n"
                "  exports = find_exports(path)\n"
                "  for e in exports:\n"
                "      print(e['name'], 'line:', e['line'], 'export:', e['is_export'])"
            ),
        },
        "callers": {
            "keywords": ["caller", "call graph", "граф", "вызов", "вызыва",
                         "кто вызывает", "find_callers"],
            "text": (
                "BUILD CALL GRAPH:\n"
                "  exports = find_exports('path/to/Module.bsl')\n"
                "  for e in exports:\n"
                "      data = find_callers_context(e['name'], 'ModuleHint', 0, 20)\n"
                "      for c in data['callers']:\n"
                "          print(e['name'], '<-', c['caller_name'], c['file'], 'line:', c['line'])\n"
                "      if data['_meta']['has_more']:\n"
                "          print('  ... more callers, increase offset')"
            ),
        },
        "metadata": {
            "keywords": ["metadata", "метаданн", "реквизит", "attribute", "dimension",
                         "измерен", "ресурс", "resource", "табличн", "tabular",
                         "xml", "parse_object"],
            "text": (
                "READ METADATA:\n"
                "  # CF XML paths: Catalogs/Name/Ext/Catalog.xml,\n"
                "  #   Documents/Name/Ext/Document.xml,\n"
                "  #   InformationRegisters/Name/Ext/RecordSet.xml\n"
                "  meta = parse_object_xml('path/to/Object.xml')\n"
                "  for key in meta:\n"
                "      print(key, ':', meta[key])"
            ),
        },
        "search": {
            "keywords": ["search", "grep", "поиск", "искать", "найти",
                         "pattern", "шаблон"],
            "text": (
                "SEARCH FOR CODE:\n"
                "  results = safe_grep('SearchPattern', 'ModuleHint', max_files=20)\n"
                "  for r in results:\n"
                "      print(r['file'], 'line:', r['line'], r['text'])\n"
                "  # Or find modules by name:\n"
                "  modules = find_module('PartOfName')\n"
                "  for m in modules:\n"
                "      print(m['path'], m['category'], m['object_name'])"
            ),
        },
        "read": {
            "keywords": ["read", "чтени", "читать", "содержим", "content",
                         "тело", "body"],
            "text": (
                "READ PROCEDURE BODY:\n"
                "  body = read_procedure('path/to/Module.bsl', 'ProcedureName')\n"
                "  print(body)\n"
                "  # Or read full file:\n"
                "  content = read_file('path/to/Module.bsl')\n"
                "  print(content[:2000])"
            ),
        },
        "subsystem": {
            "keywords": ["subsystem", "подсистем", "состав подсистем"],
            "text": (
                "ANALYZE SUBSYSTEM:\n"
                "  result = analyze_subsystem('Спецодежда')\n"
                "  for sub in result.get('subsystems', []):\n"
                "      print(f\"Подсистема: {sub['name']} ({sub['synonym']})\")\n"
                "      print(f\"Нетиповых: {len(sub['custom_objects'])}, типовых: {len(sub['standard_objects'])}\")\n"
                "      for obj in sub['custom_objects']:\n"
                "          print(f\"  [нетип] {obj['type']}.{obj['name']}\")\n"
                "      for obj in sub['standard_objects']:\n"
                "          print(f\"  [типов] {obj['type']}.{obj['name']}\")"
            ),
        },
        "custom": {
            "keywords": ["custom", "нетипов", "доработк", "модификац",
                         "modification"],
            "text": (
                "FIND CUSTOM MODIFICATIONS:\n"
                "  result = find_custom_modifications('ВнутреннееПотребление')\n"
                "  for mod in result.get('modifications', []):\n"
                "      print(f\"Модуль: {mod['path']}\")\n"
                "      for p in mod['custom_procedures']:\n"
                "          print(f\"  {p['type']} {p['name']} (стр.{p['line']})\")\n"
                "      for r in mod['custom_regions']:\n"
                "          print(f\"  #Область {r['name']} (стр.{r['line']})\")\n"
                "  for attr in result.get('custom_attributes', []):\n"
                "      print(f\"Реквизит: {attr['name']} ({attr.get('synonym', '')})\")"
            ),
        },
        "profile": {
            "keywords": ["profile", "профиль", "обзор", "overview",
                         "analyze_object"],
            "text": (
                "OBJECT PROFILE:\n"
                "  result = analyze_object('АвансовыйОтчет')\n"
                "  meta = result.get('metadata', {})\n"
                "  print(f\"Объект: {result['name']} ({meta.get('synonym', '')})\")\n"
                "  print(f\"Реквизитов: {len(meta.get('attributes', []))}\")\n"
                "  for m in result.get('modules', []):\n"
                "      print(f\"  {m['module_type']}: {m['procedures_count']} проц, {m['exports_count']} эксп\")"
            ),
        },
        "subscriptions": {
            "keywords": ["подписк", "subscription", "событи", "event",
                         "BeforeWrite", "OnWrite", "ПриЗаписи", "ПередЗаписью"],
            "text": (
                "FIND EVENT SUBSCRIPTIONS (what fires on document write/post):\n"
                "  subs = find_event_subscriptions('АвансовыйОтчет')\n"
                "  for s in subs:\n"
                "      print(f\"{s['event']}: {s['handler']} ({s['name']})\")"
            ),
        },
        "jobs": {
            "keywords": ["регламент", "schedule", "job", "задани", "фонов",
                         "background"],
            "text": (
                "FIND SCHEDULED JOBS:\n"
                "  jobs = find_scheduled_jobs('Курс')\n"
                "  for j in jobs:\n"
                "      print(f\"{j['name']}: {j['method_name']} (active={j['use']})\")"
            ),
        },
        "movements": {
            "keywords": ["движени", "movement", "регистр", "register",
                         "проведен", "posting"],
            "text": (
                "TRACE DOCUMENT REGISTER MOVEMENTS:\n"
                "  result = find_register_movements('ПриобретениеТоваровУслуг')\n"
                "  for r in result['code_registers']:\n"
                "      print(f\"  Движения.{r['name']} (строки: {r['lines']})\")\n"
                "\n"
                "FIND WHO WRITES TO REGISTER:\n"
                "  result = find_register_writers('ТоварыНаСкладах')\n"
                "  for w in result['writers']:\n"
                "      print(f\"  {w['document']} (строки: {w['lines']})\")"
            ),
        },
        "flow": {
            "keywords": ["lifecycle", "жизненн", "flow", "end-to-end",
                         "полный анализ", "как работает"],
            "text": (
                "FULL DOCUMENT LIFECYCLE:\n"
                "  flow = analyze_document_flow('АвансовыйОтчет')\n"
                "  print('Подписки:', len(flow['event_subscriptions']))\n"
                "  for s in flow['event_subscriptions']:\n"
                "      print(f\"  {s['event']}: {s['handler']}\")\n"
                "  regs = flow['register_movements'].get('code_registers', [])\n"
                "  print('Регистры:', len(regs))\n"
                "  for r in regs:\n"
                "      print(f\"  Движения.{r['name']}\")"
            ),
        },
        "based_on": {
            "keywords": ["основани", "ввод на основании", "создать на основании",
                         "based on", "filling", "заполнени"],
            "text": (
                "FIND BASED-ON DOCUMENTS (ввод на основании):\n"
                "  result = find_based_on_documents('ПриобретениеТоваровУслуг')\n"
                "  print('Можно создать из этого документа:')\n"
                "  for d in result['can_create_from_here']:\n"
                "      print(f\"  -> {d['document']}\")\n"
                "  print('Этот документ создается на основании:')\n"
                "  for d in result['can_be_created_from']:\n"
                "      print(f\"  <- {d['type']}\")"
            ),
        },
        "print": {
            "keywords": ["печат", "print", "макет", "template", "накладн"],
            "text": (
                "FIND PRINT FORMS:\n"
                "  result = find_print_forms('РеализацияТоваровУслуг')\n"
                "  for p in result['print_forms']:\n"
                "      print(f\"  {p['name']}: {p['presentation']}\")"
            ),
        },
        "options": {
            "keywords": ["функциональн", "опци", "functional", "option",
                         "включен", "выключен"],
            "text": (
                "FIND FUNCTIONAL OPTIONS:\n"
                "  result = find_functional_options('РеализацияТоваровУслуг')\n"
                "  for fo in result['xml_options']:\n"
                "      print(f\"  {fo['name']}: {fo['synonym']}\")\n"
                "  for co in result['code_options']:\n"
                "      print(f\"  В коде: {co['option_name']} (стр.{co['line']})\")"
            ),
        },
        "roles": {
            "keywords": ["роль", "role", "прав", "right", "доступ", "access",
                         "разрешен"],
            "text": (
                "FIND ROLES AND RIGHTS:\n"
                "  result = find_roles('ПриобретениеТоваровУслуг')\n"
                "  for r in result['roles']:\n"
                "      print(f\"  {r['role_name']}: {', '.join(r['rights'])}\")"
            ),
        },
        "enum": {
            "keywords": ["перечислен", "enum", "значени перечислени"],
            "text": (
                "FIND ENUM VALUES:\n"
                "  result = find_enum_values('СтатусыЗаказовКлиентов')\n"
                "  print(f\"{result['name']} ({result['synonym']})\")\n"
                "  for v in result['values']:\n"
                "      print(f\"  {v['name']}: {v['synonym']}\")"
            ),
        },
    }

    def bsl_help(task: str = "") -> str:
        """Get a recipe for your task. Call help() to see all recipes,
        or help('find exports') / help('граф вызовов') for a specific one.

        Returns: str with Python code example."""
        task_lower = task.lower()

        if not task_lower:
            lines = ["Available recipes (call help('keyword') for details):\n"]
            for name, recipe in _help_recipes.items():
                first_line = recipe["text"].split("\n")[0]
                lines.append(f"  help('{name}') - {first_line}")
            return "\n".join(lines)

        for name, recipe in _help_recipes.items():
            if name in task_lower:
                return recipe["text"]
            for kw in recipe["keywords"]:
                if kw in task_lower:
                    return recipe["text"]

        # Fallback: show all recipes
        return bsl_help("")

    def detect_extensions() -> dict:
        """Обнаружить расширения рядом и текущую роль конфигурации."""
        from rlm_tools_bsl.extension_detector import detect_extension_context as _det
        ctx = _det(base_path)
        result = {
            "config_role": ctx.current.role.value,
            "config_name": ctx.current.name,
            "config_prefix": ctx.current.name_prefix,
            "warnings": ctx.warnings,
            "nearby_extensions": [
                {"name": e.name, "purpose": e.purpose,
                 "prefix": e.name_prefix, "path": e.path}
                for e in ctx.nearby_extensions
            ],
            "nearby_main": None,
        }
        if ctx.nearby_main:
            result["nearby_main"] = {
                "name": ctx.nearby_main.name, "path": ctx.nearby_main.path,
            }
        return result

    def find_ext_overrides(extension_path: str, object_name: str = "") -> dict:
        """Найти перехваченные методы в расширении.
        extension_path — путь к расширению (из detect_extensions).
        object_name — имя объекта для прицельного поиска ('' = все)."""
        from rlm_tools_bsl.extension_detector import find_extension_overrides as _feo
        overrides = _feo(extension_path, object_name or None)
        return {
            "extension_path": extension_path,
            "object_filter": object_name or "(all)",
            "overrides": overrides[:200],
            "total": len(overrides),
        }

    return {
        "_detected_prefixes": _ensure_prefixes,
        "detect_extensions": detect_extensions,
        "find_ext_overrides": find_ext_overrides,
        "help": bsl_help,
        "find_module": find_module,
        "find_by_type": find_by_type,
        "extract_procedures": extract_procedures,
        "find_exports": find_exports,
        "safe_grep": safe_grep,
        "read_procedure": read_procedure,
        "find_callers": find_callers,
        "find_callers_context": find_callers_context,
        "parse_object_xml": parse_object_xml,
        "analyze_subsystem": analyze_subsystem,
        "find_custom_modifications": find_custom_modifications,
        "analyze_object": analyze_object,
        "find_event_subscriptions": find_event_subscriptions,
        "find_scheduled_jobs": find_scheduled_jobs,
        "find_register_movements": find_register_movements,
        "find_register_writers": find_register_writers,
        "analyze_document_flow": analyze_document_flow,
        "find_based_on_documents": find_based_on_documents,
        "find_print_forms": find_print_forms,
        "find_enum_values": find_enum_values,
        "find_functional_options": find_functional_options,
        "find_roles": find_roles,
    }
