"""Tests for integration metadata parsers (HTTP, SOAP, XDTO, ExchangePlan)."""

from rlm_tools_bsl.bsl_xml_parsers import (
    parse_http_service_xml,
    parse_web_service_xml,
    parse_xdto_package_xml,
    parse_xdto_types,
    parse_exchange_plan_content,
)


# ── HTTP service test data ──────────────────────────────────

_HTTP_CF_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses"
                xmlns:v8="http://v8.1c.ru/8.1/data/core"
                xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <HTTPService>
    <Properties>
      <Name>ПередачаДанных</Name>
      <RootURL>dt</RootURL>
    </Properties>
    <ChildObjects>
      <URLTemplate>
        <Properties>
          <Name>ХранилищеИИдентификатор</Name>
          <Template>/storage/{Storage}/{ID}</Template>
        </Properties>
        <ChildObjects>
          <Method>
            <Properties>
              <Name>GET</Name>
              <HTTPMethod>GET</HTTPMethod>
              <Handler>ХранилищеGETЗапрос</Handler>
            </Properties>
          </Method>
          <Method>
            <Properties>
              <Name>POST</Name>
              <HTTPMethod>POST</HTTPMethod>
              <Handler>ХранилищеPOSTЗапрос</Handler>
            </Properties>
          </Method>
        </ChildObjects>
      </URLTemplate>
    </ChildObjects>
  </HTTPService>
</MetaDataObject>
"""

_HTTP_EDT_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<mdclass:HTTPService xmlns:mdclass="http://g5.1c.ru/v8/dt/metadata/mdclass"
                     name="ПередачаДанных" rootURL="dt">
  <name>ПередачаДанных</name>
  <rootURL>dt</rootURL>
  <urlTemplates>
    <name>ХранилищеИИдентификатор</name>
    <template>/storage/{Storage}/{ID}</template>
    <methods>
      <name>GET</name>
      <httpMethod>GET</httpMethod>
      <handler>ХранилищеGETЗапрос</handler>
    </methods>
    <methods>
      <name>POST</name>
      <httpMethod>POST</httpMethod>
      <handler>ХранилищеPOSTЗапрос</handler>
    </methods>
  </urlTemplates>
</mdclass:HTTPService>
"""


# ── Web service test data ───────────────────────────────────

_WS_CF_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses"
                xmlns:v8="http://v8.1c.ru/8.1/data/core">
  <WebService>
    <Properties>
      <Name>Exchange</Name>
      <Namespace>http://www.1c.ru/SSL/Exchange</Namespace>
    </Properties>
    <ChildObjects>
      <Operation>
        <Properties>
          <Name>Upload</Name>
          <XDTOReturningValueType>xs:string</XDTOReturningValueType>
          <ProcedureName>ВыполнитьВыгрузку</ProcedureName>
        </Properties>
        <ChildObjects>
          <Parameter>
            <Properties>
              <Name>ExchangePlanName</Name>
            </Properties>
          </Parameter>
          <Parameter>
            <Properties>
              <Name>NodeCode</Name>
            </Properties>
          </Parameter>
        </ChildObjects>
      </Operation>
    </ChildObjects>
  </WebService>
</MetaDataObject>
"""

_WS_EDT_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<mdclass:WebService xmlns:mdclass="http://g5.1c.ru/v8/dt/metadata/mdclass"
                    name="Exchange">
  <name>Exchange</name>
  <namespace>http://www.1c.ru/SSL/Exchange</namespace>
  <operations>
    <name>Upload</name>
    <xdtoReturningValueType>
      <name>string</name>
      <nsUri>http://www.w3.org/2001/XMLSchema</nsUri>
    </xdtoReturningValueType>
    <procedureName>ВыполнитьВыгрузку</procedureName>
    <parameters>
      <name>ExchangePlanName</name>
    </parameters>
    <parameters>
      <name>NodeCode</name>
    </parameters>
  </operations>
</mdclass:WebService>
"""


# ── XDTO package test data ─────────────────────────────────

_XDTO_CF_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses">
  <XDTOPackage>
    <Properties>
      <Name>AgentScripts</Name>
      <Namespace>http://v8.1c.ru/agent/scripts/1.0</Namespace>
    </Properties>
  </XDTOPackage>
</MetaDataObject>
"""

_XDTO_EDT_MDO = """\
<?xml version="1.0" encoding="UTF-8"?>
<mdclass:XDTOPackage xmlns:mdclass="http://g5.1c.ru/v8/dt/metadata/mdclass"
                     name="AgentScripts">
  <name>AgentScripts</name>
  <namespace>http://v8.1c.ru/agent/scripts/1.0</namespace>
</mdclass:XDTOPackage>
"""

_XDTO_PACKAGE_XDTO = """\
<?xml version="1.0" encoding="UTF-8"?>
<package targetNamespace="http://v8.1c.ru/agent/scripts/1.0"
         xmlns="http://v8.1c.ru/8.1/xdto">
  <objectType name="ClusterAdministrationInfo">
    <property name="AgentConnectionString" type="xs:string"/>
    <property name="ClusterName" type="xs:string"/>
  </objectType>
  <valueType name="StatusCode">
    <property name="Code" type="xs:int"/>
  </valueType>
</package>
"""


# ── Exchange plan content test data ─────────────────────────

_EP_CF_CONTENT_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<ExchangePlanContent xmlns="http://v8.1c.ru/8.3/xcf/extrnprops">
  <Item>
    <Metadata>Catalog.Склады</Metadata>
    <AutoRecord>Deny</AutoRecord>
  </Item>
  <Item>
    <Metadata>Constant.ИспользоватьУпаковкиНоменклатуры</Metadata>
    <AutoRecord>Allow</AutoRecord>
  </Item>
</ExchangePlanContent>
"""

_EP_EDT_MDO = """\
<?xml version="1.0" encoding="UTF-8"?>
<mdclass:ExchangePlan xmlns:mdclass="http://g5.1c.ru/v8/dt/metadata/mdclass"
                      name="ОбменУправлениеПредприятием">
  <name>ОбменУправлениеПредприятием</name>
  <content>
    <mdObject>Catalog.Склады</mdObject>
    <autoRecord>Deny</autoRecord>
  </content>
  <content>
    <mdObject>Constant.ИспользоватьУпаковкиНоменклатуры</mdObject>
    <autoRecord>Allow</autoRecord>
  </content>
</mdclass:ExchangePlan>
"""


# ═══════════════════════════════════════════════════════════
# HTTP service tests
# ═══════════════════════════════════════════════════════════


def test_parse_http_service_cf():
    result = parse_http_service_xml(_HTTP_CF_XML)
    assert result is not None
    assert result["name"] == "ПередачаДанных"
    assert result["root_url"] == "dt"
    assert len(result["templates"]) == 1
    tmpl = result["templates"][0]
    assert tmpl["name"] == "ХранилищеИИдентификатор"
    assert tmpl["template"] == "/storage/{Storage}/{ID}"
    assert len(tmpl["methods"]) == 2
    assert tmpl["methods"][0]["http_method"] == "GET"
    assert tmpl["methods"][1]["handler"] == "ХранилищеPOSTЗапрос"


def test_parse_http_service_edt():
    result = parse_http_service_xml(_HTTP_EDT_XML)
    assert result is not None
    assert result["name"] == "ПередачаДанных"
    assert result["root_url"] == "dt"
    assert len(result["templates"]) == 1
    tmpl = result["templates"][0]
    assert tmpl["template"] == "/storage/{Storage}/{ID}"
    assert len(tmpl["methods"]) == 2
    assert tmpl["methods"][0]["http_method"] == "GET"


def test_parse_http_service_empty():
    assert parse_http_service_xml("") is None
    assert parse_http_service_xml("<root/>") is None
    assert parse_http_service_xml("not xml at all") is None


def test_parse_http_service_autodetect():
    """CF and EDT both parsed correctly via autodetect."""
    cf = parse_http_service_xml(_HTTP_CF_XML)
    edt = parse_http_service_xml(_HTTP_EDT_XML)
    assert cf["name"] == edt["name"]
    assert cf["root_url"] == edt["root_url"]
    assert len(cf["templates"]) == len(edt["templates"])
    assert len(cf["templates"][0]["methods"]) == len(edt["templates"][0]["methods"])


# ═══════════════════════════════════════════════════════════
# Web service tests
# ═══════════════════════════════════════════════════════════


def test_parse_web_service_cf():
    result = parse_web_service_xml(_WS_CF_XML)
    assert result is not None
    assert result["name"] == "Exchange"
    assert result["namespace"] == "http://www.1c.ru/SSL/Exchange"
    assert len(result["operations"]) == 1
    op = result["operations"][0]
    assert op["name"] == "Upload"
    assert op["return_type"] == "xs:string"
    assert op["procedure_name"] == "ВыполнитьВыгрузку"
    assert op["params"] == ["ExchangePlanName", "NodeCode"]


def test_parse_web_service_edt():
    result = parse_web_service_xml(_WS_EDT_XML)
    assert result is not None
    assert result["name"] == "Exchange"
    assert result["namespace"] == "http://www.1c.ru/SSL/Exchange"
    assert len(result["operations"]) == 1
    op = result["operations"][0]
    assert op["name"] == "Upload"
    assert op["return_type"] == "xs:string"
    assert op["procedure_name"] == "ВыполнитьВыгрузку"
    assert op["params"] == ["ExchangePlanName", "NodeCode"]


def test_parse_web_service_empty():
    assert parse_web_service_xml("") is None
    assert parse_web_service_xml("<root/>") is None


def test_parse_web_service_autodetect():
    cf = parse_web_service_xml(_WS_CF_XML)
    edt = parse_web_service_xml(_WS_EDT_XML)
    assert cf["name"] == edt["name"]
    assert cf["namespace"] == edt["namespace"]
    assert len(cf["operations"]) == len(edt["operations"])
    assert cf["operations"][0]["params"] == edt["operations"][0]["params"]


# ═══════════════════════════════════════════════════════════
# XDTO package tests
# ═══════════════════════════════════════════════════════════


def test_parse_xdto_package_cf():
    result = parse_xdto_package_xml(_XDTO_CF_XML)
    assert result is not None
    assert result["name"] == "AgentScripts"
    assert result["namespace"] == "http://v8.1c.ru/agent/scripts/1.0"
    assert result["types"] == []


def test_parse_xdto_package_edt_mdo():
    result = parse_xdto_package_xml(_XDTO_EDT_MDO)
    assert result is not None
    assert result["name"] == "AgentScripts"
    assert result["namespace"] == "http://v8.1c.ru/agent/scripts/1.0"
    assert result["types"] == []


def test_parse_xdto_package_xdto():
    types = parse_xdto_types(_XDTO_PACKAGE_XDTO)
    assert len(types) == 2
    obj_type = types[0]
    assert obj_type["name"] == "ClusterAdministrationInfo"
    assert obj_type["kind"] == "objectType"
    assert len(obj_type["properties"]) == 2
    assert obj_type["properties"][0]["name"] == "AgentConnectionString"
    assert obj_type["properties"][0]["type"] == "xs:string"

    val_type = types[1]
    assert val_type["name"] == "StatusCode"
    assert val_type["kind"] == "valueType"


def test_parse_xdto_package_with_types():
    """parse_xdto_package_xml with xdto_content merges types."""
    result = parse_xdto_package_xml(_XDTO_EDT_MDO, _XDTO_PACKAGE_XDTO)
    assert result is not None
    assert result["name"] == "AgentScripts"
    assert len(result["types"]) == 2


def test_parse_xdto_package_empty():
    assert parse_xdto_package_xml("") is None
    assert parse_xdto_package_xml("<root/>") is None


# ═══════════════════════════════════════════════════════════
# Exchange plan content tests
# ═══════════════════════════════════════════════════════════


def test_parse_exchange_plan_content_cf():
    result = parse_exchange_plan_content(_EP_CF_CONTENT_XML)
    assert len(result) == 2
    assert result[0]["ref"] == "Catalog.Склады"
    assert result[0]["auto_record"] is False
    assert result[1]["ref"] == "Constant.ИспользоватьУпаковкиНоменклатуры"
    assert result[1]["auto_record"] is True


def test_parse_exchange_plan_content_edt():
    result = parse_exchange_plan_content(_EP_EDT_MDO)
    assert len(result) == 2
    assert result[0]["ref"] == "Catalog.Склады"
    assert result[0]["auto_record"] is False
    assert result[1]["auto_record"] is True


def test_parse_exchange_plan_content_empty_cf():
    xml = '<?xml version="1.0"?><ExchangePlanContent xmlns="http://v8.1c.ru/8.3/xcf/extrnprops"/>'
    result = parse_exchange_plan_content(xml)
    assert result == []


def test_parse_exchange_plan_content_empty_edt():
    xml = '<?xml version="1.0"?><mdclass:ExchangePlan xmlns:mdclass="http://g5.1c.ru/v8/dt/metadata/mdclass"><name>Test</name></mdclass:ExchangePlan>'
    result = parse_exchange_plan_content(xml)
    assert result == []


def test_parse_exchange_plan_content_autodetect():
    cf = parse_exchange_plan_content(_EP_CF_CONTENT_XML)
    edt = parse_exchange_plan_content(_EP_EDT_MDO)
    assert len(cf) == len(edt)
    assert cf[0]["ref"] == edt[0]["ref"]
    assert cf[0]["auto_record"] == edt[0]["auto_record"]
