"""Build new Appian XML objects without cloning exported templates."""

from __future__ import annotations

from collections.abc import Callable

from lxml import etree

from appian_sentinel.models.appian_objects import ObjectType

APPIAN_NS = "http://www.appian.com/ae/types/2009"
XSD_NS = "http://www.w3.org/2001/XMLSchema"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"

_A = f"{{{APPIAN_NS}}}"
_XSI = f"{{{XSI_NS}}}"


def _field(
    fields: dict[str, object],
    *names: str,
    default: object = "",
) -> object:
    for name in names:
        if name in fields:
            return fields[name]
    return default


def _text_value(
    fields: dict[str, object],
    *names: str,
    default: str = "",
) -> str:
    value = _field(fields, *names, default=default)
    if value is None:
        return ""
    if not isinstance(value, (str, int, float, bool)):
        raise ValueError(f"{names[0]} must be a scalar value")
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


def _bool_value(
    fields: dict[str, object],
    *names: str,
    default: bool = False,
) -> str:
    value = _field(fields, *names, default=default)
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, str) and value.lower() in {"true", "false"}:
        return value.lower()
    raise ValueError(f"{names[0]} must be a boolean")


def _add_text(parent: etree._Element, tag: str, value: str) -> etree._Element:
    element = etree.SubElement(parent, tag)
    element.text = value
    return element


def _version_uuid(fields: dict[str, object], object_uuid: str) -> str:
    return _text_value(fields, "version_uuid", "versionUuid", default=object_uuid)


def _add_visibility(parent: etree._Element) -> None:
    visibility = etree.SubElement(parent, "visibility")
    values = (
        ("advertise", "false"),
        ("hierarchy", "true"),
        ("indexable", "true"),
        ("quota", "false"),
        ("searchable", "true"),
        ("system", "false"),
        ("unlogged", "false"),
    )
    for tag, value in values:
        _add_text(visibility, tag, value)


def _add_standard_role_map(
    root: etree._Element,
    *,
    inherited_roles: bool = True,
) -> None:
    role_map = etree.SubElement(root, "roleMap", public="true")
    for role_name, inherit in (
        ("readers", str(inherited_roles).lower()),
        ("authors", str(inherited_roles).lower()),
        ("administrators", str(inherited_roles).lower()),
        ("denyReaders", "false"),
        ("denyAuthors", "false"),
        ("denyAdministrators", "false"),
    ):
        role = etree.SubElement(
            role_map,
            "role",
            inherit=inherit,
            allowForAll="false",
            name=role_name,
        )
        etree.SubElement(role, "users")
        etree.SubElement(role, "groups")


def _add_rule_inputs(parent: etree._Element, fields: dict[str, object]) -> None:
    raw_inputs = _field(fields, "rule_inputs", "ruleInputs", default=[])
    if raw_inputs is None:
        return
    if not isinstance(raw_inputs, list):
        raise ValueError("rule_inputs must be a list")
    for raw_input in raw_inputs:
        if not isinstance(raw_input, dict):
            raise ValueError("each rule input must be a dictionary")
        input_name = raw_input.get("name")
        if not isinstance(input_name, str) or not input_name:
            raise ValueError("each rule input requires a non-empty name")
        named_value = etree.SubElement(parent, "namedTypedValue")
        _add_text(named_value, "name", input_name)
        description = raw_input.get("description")
        if isinstance(description, str) and description:
            _add_text(named_value, "description", description)
        type_element = etree.SubElement(named_value, "type")
        type_name = raw_input.get("type_name", raw_input.get("typeName", "string"))
        if not isinstance(type_name, str):
            raise ValueError("rule input type_name must be a string")
        if raw_input.get("is_list", raw_input.get("isList", False)):
            type_name = f"{type_name}?list"
        _add_text(type_element, "name", type_name)
        namespace = raw_input.get(
            "type_namespace",
            raw_input.get("typeNamespace", XSD_NS),
        )
        if not isinstance(namespace, str):
            raise ValueError("rule input type_namespace must be a string")
        _add_text(type_element, "namespace", namespace)


def _content_root(
    tag: str,
    object_uuid: str,
    name: str,
    fields: dict[str, object],
) -> tuple[etree._Element, etree._Element]:
    root = etree.Element("contentHaul", nsmap={"a": APPIAN_NS})
    _add_text(root, "versionUuid", _version_uuid(fields, object_uuid))
    content = etree.SubElement(root, tag)
    _add_text(content, "name", name)
    _add_text(content, "uuid", object_uuid)
    _add_text(content, "description", _text_value(fields, "description"))
    parent_uuid = _text_value(fields, "parent_uuid", "parentUuid")
    if parent_uuid:
        _add_text(content, "parentUuid", parent_uuid)
    _add_visibility(content)
    return root, content


def _build_rule_like(
    tag: str,
    object_uuid: str,
    name: str,
    fields: dict[str, object],
) -> etree._Element:
    root, content = _content_root(tag, object_uuid, name, fields)
    _add_text(content, "definition", _text_value(fields, "definition", "sail_code"))
    _add_rule_inputs(content, fields)
    default_editor = "interface" if tag == "interface" else "legacy"
    _add_text(
        content,
        "preferredEditor",
        _text_value(fields, "preferred_editor", "preferredEditor", default=default_editor),
    )
    _add_text(
        content,
        "offlineEnabled",
        _bool_value(fields, "offline_enabled", "offlineEnabled"),
    )
    if tag == "interface":
        _add_text(content, "isCustom", _bool_value(fields, "is_custom", "isCustom"))
    _add_standard_role_map(root)
    return root


def _build_constant(
    object_uuid: str,
    name: str,
    fields: dict[str, object],
) -> etree._Element:
    root, content = _content_root("constant", object_uuid, name, fields)
    typed_value = etree.SubElement(content, "typedValue")
    type_element = etree.SubElement(typed_value, "type")
    _add_text(
        type_element,
        "name",
        _text_value(fields, "value_type", "valueType", default="string"),
    )
    _add_text(
        type_element,
        "namespace",
        _text_value(
            fields,
            "value_type_namespace",
            "valueTypeNamespace",
            default=XSD_NS,
        ),
    )
    _add_text(typed_value, "value", _text_value(fields, "value"))
    _add_text(
        content,
        "isEnvironmentSpecific",
        _bool_value(
            fields,
            "is_environment_specific",
            "isEnvironmentSpecific",
        ),
    )
    _add_standard_role_map(root)
    return root


def _build_decision(
    object_uuid: str,
    name: str,
    fields: dict[str, object],
) -> etree._Element:
    root = _build_rule_like("decision", object_uuid, name, fields)
    decision = root.find("decision")
    if decision is None:
        raise ValueError("decision element was not created")
    raw_outputs = _field(fields, "output_metadata", "outputMetadata", default=[])
    if not isinstance(raw_outputs, list):
        raise ValueError("output_metadata must be a list")
    if raw_outputs:
        output_list = etree.SubElement(decision, "outputMetadataList")
        for raw_output in raw_outputs:
            if not isinstance(raw_output, dict):
                raise ValueError("each output metadata item must be a dictionary")
            output = etree.SubElement(output_list, "outputMetadata")
            _add_text(output, "outputId", str(raw_output.get("output_id", raw_output.get("outputId", ""))))
            _add_text(output, "nameRef", str(raw_output.get("name_ref", raw_output.get("nameRef", ""))))
            _add_text(output, "typeName", str(raw_output.get("type_name", raw_output.get("typeName", ""))))
    _add_text(decision, "hitPolicy", _text_value(fields, "hit_policy", "hitPolicy", default="UNIQUE"))
    return root


def _dictionary(parent: etree._Element) -> etree._Element:
    return etree.SubElement(
        parent,
        f"{_A}Dictionary",
        nsmap={"xsd": XSD_NS, "xsi": XSI_NS},
    )


def _typed_dictionary_value(
    dictionary: etree._Element,
    tag: str,
    value: str,
    xsi_type: str,
) -> None:
    element = etree.SubElement(dictionary, tag)
    element.set(f"{_XSI}type", xsi_type)
    if value:
        element.text = value


def _add_connected_system_auth_details(
    dictionary: etree._Element,
    fields: dict[str, object],
    auth_type: str,
) -> None:
    if auth_type == "None":
        etree.SubElement(dictionary, "authDetails").set(f"{_XSI}type", "xsd:string")
        return
    if auth_type == "API Key":
        details = etree.SubElement(dictionary, "authDetails")
        details.set(f"{_XSI}type", "a:Dictionary")
        _typed_dictionary_value(
            details,
            "apiKeyName",
            _text_value(fields, "api_key_name", "apiKeyName"),
            "xsd:string",
        )
        _typed_dictionary_value(details, "apiKeyValue", "", "a:EncryptedText")
        _typed_dictionary_value(
            details,
            "sendAsHeader",
            _bool_value(fields, "send_as_header", "sendAsHeader", default=True),
            "xsd:boolean",
        )
        return
    if auth_type == "OAuth Client Credentials Grant":
        details = etree.SubElement(dictionary, "authDetails")
        details.set(f"{_XSI}type", "a:Dictionary")
        _typed_dictionary_value(details, "clientSecret", "", "a:EncryptedText")
        _typed_dictionary_value(
            details,
            "clientId",
            _text_value(fields, "client_id", "clientId"),
            "xsd:string",
        )
        _typed_dictionary_value(
            details,
            "tokenUrl",
            _text_value(fields, "token_url", "tokenUrl"),
            "xsd:string",
        )
        _typed_dictionary_value(
            details,
            "scope",
            _text_value(fields, "scope"),
            "xsd:string",
        )
        _typed_dictionary_value(
            details,
            "includeScope",
            _bool_value(fields, "include_scope", "includeScope", default=True),
            "xsd:boolean",
        )
        return
    raise ValueError(
        f"Unproven connected_system authType {auth_type!r}: "
        "corpus proves None, API Key, and OAuth Client Credentials Grant"
    )


def _build_integration(
    object_uuid: str,
    name: str,
    fields: dict[str, object],
) -> etree._Element:
    root, content = _content_root("outboundIntegration", object_uuid, name, fields)
    _add_text(content, "definition", _text_value(fields, "definition", "sail_code"))
    _add_rule_inputs(content, fields)
    _add_text(content, "metadataExpr", _text_value(fields, "metadata_expression", "metadataExpr"))
    _add_text(
        content,
        "preferredEditor",
        _text_value(fields, "preferred_editor", "preferredEditor", default="legacy"),
    )
    _add_text(content, "offlineEnabled", _bool_value(fields, "offline_enabled", "offlineEnabled"))
    shared = etree.SubElement(content, "sharedConfigParameters")
    shared_dictionary = _dictionary(shared)
    _typed_dictionary_value(
        shared_dictionary,
        "isInheritedUrlOptionSelected",
        _bool_value(
            fields,
            "is_inherited_url",
            "isInheritedUrlOptionSelected",
            default=False,
        ),
        "xsd:boolean",
    )
    _typed_dictionary_value(
        shared_dictionary,
        "authType",
        _text_value(fields, "auth_type", "authType", default="None"),
        "xsd:string",
    )
    config = etree.SubElement(content, "configParameters")
    config_dictionary = _dictionary(config)
    _typed_dictionary_value(
        config_dictionary,
        "contentType",
        _text_value(fields, "content_type", "contentType"),
        "xsd:string",
    )
    _typed_dictionary_value(config_dictionary, "automaticallyConvert", "true", "xsd:boolean")
    _typed_dictionary_value(
        config_dictionary, "removeNullOrEmptyJsonFields", "true", "xsd:boolean"
    )
    _typed_dictionary_value(
        config_dictionary,
        "method",
        _text_value(fields, "http_method", "httpMethod", default="GET"),
        "xsd:string",
    )
    _typed_dictionary_value(config_dictionary, "headers", "", "a:NameValue?list")
    _typed_dictionary_value(config_dictionary, "excludeNullHeaders", "true", "xsd:boolean")
    _typed_dictionary_value(config_dictionary, "excludeNullParams", "true", "xsd:boolean")
    _typed_dictionary_value(config_dictionary, "parameters", "", "a:NameValue?list")
    _typed_dictionary_value(config_dictionary, "featureVersion", "1", "xsd:int")
    _typed_dictionary_value(
        config_dictionary,
        "timeout",
        _text_value(fields, "timeout", default="10"),
        "xsd:int",
    )
    body = etree.SubElement(config_dictionary, "body")
    body.set(f"{_XSI}nil", "true")
    body.set(f"{_XSI}type", "a:Expression")
    _add_text(content, "isWrite", _bool_value(fields, "is_write", "isWrite"))
    _add_text(
        content,
        "integrationType",
        _text_value(fields, "integration_type", "integrationType", default="system.http"),
    )
    _add_text(
        content,
        "connectedSystemUuid",
        _text_value(fields, "connected_system_uuid", "connectedSystemUuid"),
    )
    _add_text(
        content,
        "isConnectedSystemConnectionOptionSelected",
        _bool_value(
            fields,
            "use_connected_system",
            "isConnectedSystemConnectionOptionSelected",
            default=False,
        ),
    )
    integration_outputs = etree.SubElement(content, "integrationOutputs")
    output_dictionary = _dictionary(integration_outputs)
    _typed_dictionary_value(
        output_dictionary, "outputs", "", "a:IntegrationOutput?list"
    )
    _add_text(
        content,
        "isRequestResponseLoggingEnabled",
        _bool_value(
            fields,
            "request_response_logging",
            "isRequestResponseLoggingEnabled",
        ),
    )
    _add_standard_role_map(root)
    return root


def _build_web_api(
    object_uuid: str,
    name: str,
    fields: dict[str, object],
) -> etree._Element:
    root = etree.Element("webApiHaul", nsmap={"a": APPIAN_NS})
    _add_text(root, "versionUuid", _version_uuid(fields, object_uuid))
    web_api = etree.SubElement(
        root,
        "webApi",
        {f"{_A}uuid": object_uuid, "name": name},
    )
    _add_text(web_api, f"{_A}description", _text_value(fields, "description"))
    _add_text(
        web_api,
        f"{_A}expression",
        _text_value(fields, "definition", "expression", "sail_code"),
    )
    _add_text(
        web_api,
        f"{_A}urlAlias",
        _text_value(fields, "url_alias", "urlAlias"),
    )
    _add_text(
        web_api,
        f"{_A}httpMethod",
        _text_value(fields, "http_method", "httpMethod", default="GET"),
    )
    _add_text(web_api, f"{_A}system", _bool_value(fields, "system"))
    _add_text(
        web_api,
        f"{_A}requestBodyType",
        _text_value(fields, "request_body_type", "requestBodyType", default="NONE"),
    )
    folder_uuid = _text_value(
        fields,
        "receive_documents_folder_uuid",
        "receiveDocumentsFolderUuid",
    )
    if folder_uuid:
        _add_text(web_api, f"{_A}receiveDocumentsFolderUuid", folder_uuid)
    _add_text(
        web_api,
        f"{_A}loggingEnabled",
        _bool_value(fields, "logging_enabled", "loggingEnabled"),
    )
    role_map = etree.SubElement(root, "roleMap")
    for role_name in ("web_api_administrator", "web_api_viewer"):
        role = etree.SubElement(role_map, "role", name=role_name)
        etree.SubElement(role, "users")
        etree.SubElement(role, "groups")
    typed_value = etree.SubElement(root, "typedValue")
    value_type = etree.SubElement(typed_value, "type")
    _add_text(value_type, "name", "WebApiRequest?list")
    _add_text(value_type, "namespace", APPIAN_NS)
    value = etree.SubElement(typed_value, "value")
    item = etree.SubElement(value, "el")
    etree.SubElement(item, f"{_A}path")
    etree.SubElement(item, f"{_A}body")
    return root


def _build_connected_system(
    object_uuid: str,
    name: str,
    fields: dict[str, object],
) -> etree._Element:
    root = etree.Element("connectedSystemHaul", nsmap={"a": APPIAN_NS})
    _add_text(root, "versionUuid", _version_uuid(fields, object_uuid))
    connected_system = etree.SubElement(root, "connectedSystem")
    _add_text(connected_system, "name", name)
    _add_text(connected_system, "uuid", object_uuid)
    _add_text(connected_system, "description", _text_value(fields, "description"))
    _add_visibility(connected_system)
    shared = etree.SubElement(connected_system, "sharedConfigParameters")
    dictionary = _dictionary(shared)
    _typed_dictionary_value(dictionary, "configurationDescriptor", "", "xsd:string")
    _typed_dictionary_value(dictionary, "url", "", "xsd:string")
    _typed_dictionary_value(
        dictionary,
        "isInheritedUrlOptionSelected",
        _bool_value(
            fields,
            "is_inherited_url",
            "isInheritedUrlOptionSelected",
        ),
        "xsd:boolean",
    )
    _typed_dictionary_value(
        dictionary,
        "baseUrl",
        _text_value(fields, "base_url", "baseUrl"),
        "xsd:string",
    )
    auth_type = _text_value(fields, "auth_type", "authType", default="None")
    _typed_dictionary_value(dictionary, "authType", auth_type, "xsd:string")
    _add_connected_system_auth_details(dictionary, fields, auth_type)
    _add_text(connected_system, "logoChoice", "")
    _add_text(
        connected_system,
        "integrationType",
        _text_value(fields, "system_type", "integration_type", "integrationType", default="system.http"),
    )
    _add_text(
        connected_system,
        "enableRtdShortcut",
        _bool_value(fields, "enable_rtd_shortcut", "enableRtdShortcut"),
    )
    _add_text(connected_system, "rtdShortcutDisplayName", "")
    vault = etree.SubElement(connected_system, "vaultFieldMetadata")
    _dictionary(vault)
    _add_standard_role_map(root, inherited_roles=False)
    return root


def _build_event_consumer(
    object_uuid: str,
    name: str,
    fields: dict[str, object],
) -> etree._Element:
    raise ValueError(
        "No Appian export sample available for event_consumer; "
        "create it in Appian and import the export to enable this operation."
    )


def _add_history(root: etree._Element) -> None:
    version_uuid = root.xpath("string(*[local-name()='versionUuid'])")
    history = etree.SubElement(root, "history")
    etree.SubElement(history, "historyInfo", versionUuid=version_uuid)


_BUILDERS: dict[
    ObjectType,
    Callable[[str, str, dict[str, object]], etree._Element],
] = {
    ObjectType.EXPRESSION_RULE: lambda uuid, name, fields: _build_rule_like(
        "rule", uuid, name, fields
    ),
    ObjectType.INTERFACE: lambda uuid, name, fields: _build_rule_like(
        "interface", uuid, name, fields
    ),
    ObjectType.CONSTANT: _build_constant,
    ObjectType.DECISION: _build_decision,
    ObjectType.OUTBOUND_INTEGRATION: _build_integration,
    ObjectType.WEB_API: _build_web_api,
    ObjectType.EVENT_CONSUMER: _build_event_consumer,
    ObjectType.CONNECTED_SYSTEM: _build_connected_system,
}


def build_native_content_xml(
    object_type: ObjectType,
    uuid: str,
    name: str,
    fields: dict[str, object],
) -> bytes:
    """Return native export XML for one supported Appian object."""
    if not isinstance(object_type, ObjectType) or object_type not in _BUILDERS:
        raise ValueError(f"Unsupported native object type: {object_type}")
    if not isinstance(uuid, str) or not uuid:
        raise ValueError("uuid must be a non-empty string")
    if not isinstance(name, str) or not name:
        raise ValueError("name must be a non-empty string")
    if not isinstance(fields, dict):
        raise ValueError("fields must be a dictionary")
    root = _BUILDERS[object_type](uuid, name, fields)
    if object_type == ObjectType.EXPRESSION_RULE:
        _add_text(root, "mcpEnabled", "false")
    _add_history(root)
    return etree.tostring(
        root,
        encoding="UTF-8",
        xml_declaration=True,
        standalone=True,
        pretty_print=True,
    )
