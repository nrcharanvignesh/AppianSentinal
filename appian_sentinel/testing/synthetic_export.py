"""Generate deterministic, client-free Appian exports for scale tests."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from lxml import etree

APPIAN_NS = "http://www.appian.com/ae/types/2009"
XSD_NS = "http://www.w3.org/2001/XMLSchema"

# ponytail: fixed type mix; add weighted profiles if multiple workload shapes matter.
_OBJECT_KINDS = (
    ("constant",) * 10
    + ("interface",) * 9
    + ("expression_rule",) * 9
    + ("process_model",) * 3
    + ("record_type",) * 3
    + ("document",) * 2
    + ("folder",) * 2
    + (
        "decision",
        "rules_folder",
        "outbound_integration",
        "data_type",
        "web_api",
        "connected_system",
        "site",
        "group",
        "data_store",
        "translation_set",
        "translation_string",
        "portal",
        "process_model_folder",
        "tempo_report",
    )
)

_DIRECTORIES = {
    "connected_system": "connectedSystem",
    "constant": "content",
    "data_store": "dataStore",
    "data_type": "datatype",
    "decision": "content",
    "document": "content",
    "expression_rule": "content",
    "folder": "content",
    "group": "group",
    "interface": "content",
    "outbound_integration": "content",
    "portal": "portal",
    "process_model": "processModel",
    "process_model_folder": "processModelFolder",
    "record_type": "recordType",
    "rules_folder": "content",
    "site": "site",
    "tempo_report": "tempoReport",
    "translation_set": "translationSet",
    "translation_string": "translationString",
    "web_api": "webApi",
}

_EXPORT_TYPES = {
    kind: directory if directory != "content" else kind
    for kind, directory in _DIRECTORIES.items()
}


@dataclass(frozen=True)
class SyntheticExport:
    """Summary of a generated export tree."""

    root: Path
    object_count: int
    type_counts: dict[str, int]


def expected_type_counts(object_count: int) -> dict[str, int]:
    """Return the deterministic parsed-type inventory for *object_count*."""
    _validate_object_count(object_count)
    counts = Counter(_kind_at(index) for index in range(object_count))
    return dict(sorted(counts.items()))


def generate_synthetic_export(
    output_dir: Path,
    object_count: int,
    *,
    seed: int | str = 0,
) -> SyntheticExport:
    """Write a deterministic modern-Haul export without retaining object trees."""
    _validate_object_count(object_count)
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    for directory in sorted(set(_DIRECTORIES.values()) | {"META-INF", "application"}):
        (root / directory).mkdir(parents=True, exist_ok=True)

    seed_text = str(seed)
    _write_metadata(root, object_count, seed_text)
    _write_application(root, seed_text)

    type_counts: Counter[str] = Counter()
    with (root / "META-INF" / "export.log").open("w", encoding="utf-8", newline="\n") as export_log:
        export_log.write(f"Success ({object_count}):\n")
        for index in range(object_count):
            kind = _kind_at(index)
            object_uuid = _object_uuid(seed_text, kind, index)
            dependency_index = index - 2 if index > 1 and index % 2 == 0 else index - 1
            previous_uuid = (
                _object_uuid(
                    seed_text,
                    _kind_at(dependency_index),
                    dependency_index,
                )
                if index
                else ""
            )
            name = _object_name(kind, index)
            suffix, content = _render_object(
                kind,
                name,
                object_uuid,
                _version_uuid(seed_text, index),
                previous_uuid,
                index,
            )
            object_path = root / _DIRECTORIES[kind] / f"synthetic_{index:06d}.{suffix}"
            object_path.write_text(content, encoding="utf-8", newline="\n")
            if kind == "document":
                payload_dir = object_path.with_suffix("")
                payload_dir.mkdir()
                (payload_dir / "payload.txt").write_text(
                    f"Synthetic document payload {index}\n",
                    encoding="ascii",
                    newline="\n",
                )
            export_log.write(
                f'{_EXPORT_TYPES[kind]} {index + 1} {object_uuid} "{name}"\n'
            )
            type_counts[kind] += 1

    return SyntheticExport(
        root=root,
        object_count=object_count,
        type_counts=dict(sorted(type_counts.items())),
    )


def _validate_object_count(object_count: int) -> None:
    if isinstance(object_count, bool) or object_count < 1:
        raise ValueError("object_count must be a positive integer")


def _kind_at(index: int) -> str:
    return _OBJECT_KINDS[index % len(_OBJECT_KINDS)]


def _namespace(seed: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"appian-sentinel-synthetic:{seed}")


def _object_uuid(seed: str, kind: str, index: int) -> str:
    if kind == "data_type":
        return f"{{urn:synthetic:{seed}}}SyntheticType{index:06d}"
    return str(uuid5(_namespace(seed), f"object:{index}:{kind}"))


def _version_uuid(seed: str, index: int) -> str:
    return str(uuid5(_namespace(seed), f"version:{index}"))


def _object_name(kind: str, index: int) -> str:
    return f"SYN_{kind.upper()}_{index:06d}"


def _write_metadata(root: Path, object_count: int, seed: str) -> None:
    manifest = (
        "Manifest-Version: 1.0\n"
        "Appian-Version: 26.6.0\n"
        "Created-On: 2026-01-01T00:00:00Z\n"
        f"Synthetic-Seed: {seed}\n"
        f"Synthetic-Object-Count: {object_count}\n"
    )
    (root / "META-INF" / "MANIFEST.MF").write_text(
        manifest,
        encoding="ascii",
        newline="\n",
    )


def _write_application(root: Path, seed: str) -> None:
    app_uuid = str(uuid5(_namespace(seed), "application"))
    content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<applicationHaul xmlns="{APPIAN_NS}">\n'
        "  <application>\n"
        "    <name>Synthetic Scale Application</name>\n"
        f"    <uuid>{app_uuid}</uuid>\n"
        "    <prefix>SYN</prefix>\n"
        "    <description>Deterministic client-free scale fixture</description>\n"
        "  </application>\n"
        "</applicationHaul>\n"
    )
    (root / "application" / "synthetic_application.xml").write_text(
        content,
        encoding="utf-8",
        newline="\n",
    )


def _sail(previous_uuid: str) -> str:
    if previous_uuid:
        return f'a!localVariables(local!dependency: #"{previous_uuid}"(), local!dependency)'
    return "a!localVariables(local!value: 1, local!value)"


def _render_object(
    kind: str,
    name: str,
    object_uuid: str,
    version_uuid: str,
    previous_uuid: str,
    index: int,
) -> tuple[str, str]:
    if kind in {
        "constant",
        "decision",
        "document",
        "expression_rule",
        "folder",
        "interface",
        "outbound_integration",
        "rules_folder",
    }:
        return "xml", _render_content(
            kind,
            name,
            object_uuid,
            version_uuid,
            previous_uuid,
            index,
        )
    if kind == "process_model":
        return "xml", _render_process_model(
            name, object_uuid, version_uuid, previous_uuid, index
        )
    if kind == "record_type":
        return "xml", _render_record_type(
            name, object_uuid, version_uuid, previous_uuid, index
        )
    if kind == "data_type":
        return "xsd", _render_data_type(name, object_uuid, version_uuid, index)
    return "xml", _render_top_level(
        kind,
        name,
        object_uuid,
        version_uuid,
        previous_uuid,
        index,
    )


def _render_content(
    kind: str,
    name: str,
    object_uuid: str,
    version_uuid: str,
    previous_uuid: str,
    index: int,
) -> str:
    tags = {
        "expression_rule": "rule",
        "interface": "interface",
        "constant": "constant",
        "decision": "decision",
        "document": "document",
        "folder": "folder",
        "rules_folder": "rulesFolder",
        "outbound_integration": "outboundIntegration",
    }
    tag = tags[kind]
    values = [
        f"<name>{name}</name>",
        f"<uuid>{object_uuid}</uuid>",
        f"<description>Synthetic {kind} {index}</description>",
    ]
    if kind == "constant":
        values.append(
            "<typedValue><type><name>Text</name>"
            f"<namespace>{XSD_NS}</namespace></type><value>synthetic</value></typedValue>"
        )
    elif kind not in {"document", "folder", "rules_folder"}:
        values.append(f"<definition><![CDATA[{_sail(previous_uuid)}]]></definition>")
    if kind == "outbound_integration":
        values.extend(
            (
                f"<connectedSystemUuid>{previous_uuid}</connectedSystemUuid>",
                "<integrationType>synthetic</integrationType>",
            )
        )
    if kind not in {"constant", "document", "folder", "rules_folder"}:
        values.extend(("<preferredEditor>legacy</preferredEditor>", "<offlineEnabled>false</offlineEnabled>"))
    file_node = f"<file>{name}.txt</file>" if kind == "document" else ""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<contentHaul xmlns:a="{APPIAN_NS}">\n'
        f"  <versionUuid>{version_uuid}</versionUuid>\n"
        f"  <{tag}>{''.join(values)}</{tag}>\n"
        f"  {file_node}\n"
        "</contentHaul>\n"
    )


def _render_process_model(
    name: str,
    object_uuid: str,
    version_uuid: str,
    previous_uuid: str,
    index: int,
) -> str:
    expression = _sail(previous_uuid)
    return (
        f'<processModelHaul xmlns="{APPIAN_NS}">'
        f"<versionUuid>{version_uuid}</versionUuid>"
        "<process_model_port><pm><meta>"
        f"<uuid>{object_uuid}</uuid>"
        "<name><string-map><pair><locale country=\"US\" lang=\"en\"/>"
        f"<value>{name}</value></pair></string-map></name>"
        "</meta><nodes>"
        f'<node uuid="node-{index}-start"><guiId>0</guiId>'
        "<fname><string-map><pair><locale country=\"US\" lang=\"en\"/>"
        "<value>Start</value></pair></string-map></fname>"
        f"<expression><![CDATA[{expression}]]></expression>"
        "<connections><connection><to>1</to></connection></connections></node>"
        f'<node uuid="node-{index}-end"><guiId>1</guiId>'
        "<fname><string-map><pair><locale country=\"US\" lang=\"en\"/>"
        "<value>End</value></pair></string-map></fname><connections/></node>"
        "</nodes></pm></process_model_port></processModelHaul>\n"
    )


def _render_record_type(
    name: str,
    object_uuid: str,
    version_uuid: str,
    previous_uuid: str,
    index: int,
) -> str:
    return (
        f'<recordTypeHaul xmlns:a="{APPIAN_NS}">'
        f"<versionUuid>{version_uuid}</versionUuid>"
        f'<recordType a:uuid="{object_uuid}" name="{name}">'
        f'<a:relatedActionCfg a:uuid="action-{index}">'
        f'<a:target a:uuid="{previous_uuid}"/>'
        "<a:staticTitleString>Run</a:staticTitleString>"
        "</a:relatedActionCfg>"
        f"<a:titleExpr><![CDATA[{_sail(previous_uuid)}]]></a:titleExpr>"
        "</recordType></recordTypeHaul>\n"
    )


def _render_data_type(
    name: str,
    object_uuid: str,
    version_uuid: str,
    index: int,
) -> str:
    namespace, _, qualified_name = object_uuid[1:].partition("}")
    type_name = f"SyntheticType{index:06d}"
    if qualified_name != type_name:
        raise ValueError(f"Invalid synthetic data type UUID: {object_uuid}")
    return (
        f'<xsd:schema xmlns:xsd="{XSD_NS}" xmlns:a="{APPIAN_NS}" '
        f'targetNamespace="{namespace}">'
        f'<xsd:complexType name="{type_name}">'
        f'<xsd:annotation><xsd:appinfo source="{APPIAN_NS}">'
        f"<a:versionUuid>{version_uuid}</a:versionUuid>"
        "</xsd:appinfo></xsd:annotation>"
        "<xsd:sequence><xsd:element name=\"id\" type=\"xsd:int\"/></xsd:sequence>"
        f"</xsd:complexType><!-- {name} --></xsd:schema>\n"
    )


def _render_top_level(
    kind: str,
    name: str,
    object_uuid: str,
    version_uuid: str,
    previous_uuid: str,
    index: int,
) -> str:
    expression = _sail(previous_uuid)
    if kind == "web_api":
        body = (
            f'<webApi xmlns:a="{APPIAN_NS}" a:uuid="{object_uuid}" name="{name}">'
            f"<description>Synthetic web API {index}</description><httpMethod>GET</httpMethod>"
            f"<urlAlias>synthetic-{index}</urlAlias><expression><![CDATA[{expression}]]></expression>"
            "</webApi>"
        )
    elif kind == "connected_system":
        body = (
            f"<connectedSystem><uuid>{object_uuid}</uuid><name>{name}</name>"
            "<integrationType>synthetic</integrationType>"
            "<sharedConfigParameters><baseUrl>https://example.invalid</baseUrl>"
            "<authType>none</authType></sharedConfigParameters></connectedSystem>"
        )
    elif kind == "site":
        body = (
            f'<site xmlns:a="{APPIAN_NS}" a:uuid="{object_uuid}" name="{name}">'
            f"<page a:uuid=\"page-{index}\"><nameExpr>Home</nameExpr>"
            f'<uiObject a:uuid="{previous_uuid}"/><visibilityExpr>true</visibilityExpr></page>'
            "</site>"
        )
    elif kind == "group":
        body = (
            f"<group><uuid>{object_uuid}</uuid><name>{name}</name>"
            "<memberPolicy>ADMIN</memberPolicy><viewingPolicy>ALL</viewingPolicy></group>"
        )
    elif kind == "data_store":
        body = (
            f"<dataStore><uuid>{object_uuid}</uuid><name>{name}</name>"
            "<dataSourceKey>jdbc/Synthetic</dataSourceKey></dataStore>"
        )
    elif kind == "translation_set":
        body = (
            f'<translationSet xmlns:a="{APPIAN_NS}" a:uuid="{object_uuid}" name="{name}">'
            "<a:enabledLocales><a:localeLanguageTag>en-US</a:localeLanguageTag>"
            "</a:enabledLocales><a:defaultLocale>"
            "<a:localeLanguageTag>en-US</a:localeLanguageTag></a:defaultLocale>"
            "</translationSet>"
        )
    elif kind == "translation_string":
        body = (
            f'<translationString xmlns:a="{APPIAN_NS}" a:uuid="{object_uuid}" name="{name}">'
            f"<a:translationSetUuid>{previous_uuid}</a:translationSetUuid>"
            "<translationTexts><translatedText><a:translationLocale>"
            "<a:localeLanguageTag>en-US</a:localeLanguageTag></a:translationLocale>"
            "<a:translatedText>Synthetic text</a:translatedText>"
            "</translatedText></translationTexts></translationString>"
        )
    elif kind == "portal":
        body = (
            f'<portal xmlns:a="{APPIAN_NS}" a:uuid="{object_uuid}" name="{name}">'
            f'<serviceAccountUser a:uuid="{previous_uuid}"/>'
            f'<navigationNode a:uuid="page-{index}"><staticName>Home</staticName>'
            f'<uiObject a:uuid="{previous_uuid}"/><visibilityExpr>true</visibilityExpr>'
            "</navigationNode></portal>"
        )
    elif kind == "process_model_folder":
        body = (
            f"<processModelFolder><uuid>{object_uuid}</uuid><name>{name}</name>"
            "</processModelFolder>"
        )
    elif kind == "tempo_report":
        body = (
            f'<tempoReport xmlns:a="{APPIAN_NS}" a:uuid="{object_uuid}" name="{name}">'
            f"<a:uiExpr><![CDATA[{expression}]]></a:uiExpr>"
            f"<a:urlStub>synthetic-{index}</a:urlStub></tempoReport>"
        )
    else:
        raise ValueError(f"Unsupported synthetic object kind: {kind}")
    root_tag = f"{_DIRECTORIES[kind]}Haul"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f"<{root_tag}><versionUuid>{version_uuid}</versionUuid>{body}</{root_tag}>\n"
    )


def validate_generated_xml(export_dir: Path) -> None:
    """Raise if any generated XML or XSD file is malformed."""
    for path in Path(export_dir).rglob("*"):
        if path.suffix in {".xml", ".xsd"}:
            etree.parse(str(path))
