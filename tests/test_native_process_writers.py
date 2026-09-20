from __future__ import annotations

import os
import tempfile
from pathlib import Path
from uuid import UUID

import pytest
from lxml import etree

from appian_sentinel.generator.native_process_writers import (
    APPIAN_NS,
    build_native_process_xml,
)
from appian_sentinel.models.appian_objects import ObjectType
from appian_sentinel.models.object_registry import CAPABILITY_BY_TYPE
from appian_sentinel.parser.xml_parser import parse_appian_xml

OBJECT_UUID = "11111111-1111-4111-8111-111111111111"
FOLDER_UUID = "22222222-2222-4222-8222-222222222222"
PARENT_FOLDER_UUID = "33333333-3333-4333-8333-333333333333"

# Only these two types have a proven native shape in the real export corpus.
PROVEN_TYPES = (
    ObjectType.PROCESS_MODEL,
    ObjectType.PROCESS_MODEL_FOLDER,
)

UNPROVEN_TYPES = (
    ObjectType.BUSINESS_PROCESS,
    ObjectType.PROCESS_REPORT,
    ObjectType.ROBOTIC_TASK,
    ObjectType.ROBOT_POOL,
)


# ---------------------------------------------------------------------------
# Real corpus access
# ---------------------------------------------------------------------------

def _child_names(element: etree._Element) -> tuple[str, ...]:
    """Return the ordered local names of the element children, skipping comments."""
    return tuple(
        etree.QName(child).localname
        for child in element
        if isinstance(child.tag, str)
    )


def _local_name(element: etree._Element) -> str:
    return etree.QName(element).localname


def _find_local(parent: etree._Element, name: str) -> etree._Element | None:
    found = parent.xpath(f"*[local-name()='{name}']")
    return found[0] if found else None


def _require_local(parent: etree._Element, name: str) -> etree._Element:
    element = _find_local(parent, name)
    assert element is not None, f"missing <{name}> in <{_local_name(parent)}>"
    return element


def _node_by_gui_id(pm: etree._Element, gui_id: str) -> etree._Element:
    nodes = _require_local(pm, "nodes")
    for node in nodes.xpath("*[local-name()='node']"):
        if (_require_local(node, "guiId").text or "").strip() == gui_id:
            return node
    raise AssertionError(f"no <node> with guiId {gui_id}")


@pytest.fixture(scope="session")
def corpus_dir() -> Path:
    override = os.environ.get("APPIAN_SENTINEL_NATIVE_SPEC")
    base = (
        Path(override)
        if override
        else Path(tempfile.gettempdir()) / "AppianSentinel-native-spec"
    )
    if not base.is_dir():
        pytest.skip(f"[WARN] real corpus not available at {base}")
    return base


@pytest.fixture(scope="session")
def reference_model(corpus_dir: Path) -> etree._Element:
    """Return a real processModel root whose model holds only Start/End nodes.

    That is exactly the shape the builder emits, so child order can be compared
    element for element instead of approximately. Smallest file first keeps the
    reference the most minimal real model available.
    """
    paths = sorted(
        (corpus_dir / "processModel").glob("*.xml"),
        key=lambda item: (item.stat().st_size, item.name),
    )
    for path in paths:
        root = etree.parse(str(path)).getroot()
        pm_list = root.xpath("//*[local-name()='pm']")
        if not pm_list:
            continue
        nodes = _find_local(pm_list[0], "nodes")
        if nodes is None:
            continue
        names = [
            (_require_local(node, "ac").xpath("string(*[local-name()='name'])"))
            for node in nodes.xpath("*[local-name()='node']")
        ]
        if names == ["Start Node", "End Node"]:
            return root
    pytest.skip("[WARN] no two-node reference process model in corpus")


@pytest.fixture(scope="session")
def reference_lane_shapes(corpus_dir: Path) -> set[tuple[str, ...]]:
    """Return every real <lane> child-name sequence present in the corpus.

    Lane content varies with assignment settings, so the generated lane must
    match a shape that actually occurs rather than one arbitrary file.
    """
    shapes: set[tuple[str, ...]] = set()
    for path in sorted((corpus_dir / "processModel").glob("*.xml")):
        root = etree.parse(str(path)).getroot()
        for lane in root.xpath("//*[local-name()='lanes']/*[local-name()='lane']"):
            shapes.add(_child_names(lane))
    if not shapes:
        pytest.skip("[WARN] no populated <lanes> in corpus")
    return shapes


@pytest.fixture(scope="session")
def reference_folders(corpus_dir: Path) -> list[etree._Element]:
    roots = [
        etree.parse(str(path)).getroot()
        for path in sorted((corpus_dir / "processModelFolder").glob("*.xml"))
    ]
    if not roots:
        pytest.skip("[WARN] no processModelFolder files in corpus")
    return roots


# ---------------------------------------------------------------------------
# Generated output helpers
# ---------------------------------------------------------------------------

def _build_model(**overrides: object) -> etree._Element:
    fields: dict[str, object] = {"folder_uuid": FOLDER_UUID}
    fields.update(overrides)
    return etree.fromstring(
        build_native_process_xml(
            ObjectType.PROCESS_MODEL,
            OBJECT_UUID,
            "Order Review",
            fields,
        )
    )


def _parse_generated(
    tmp_path: Path,
    object_type: ObjectType,
    xml: bytes,
) -> object:
    directory = tmp_path / CAPABILITY_BY_TYPE[object_type].export_dir
    directory.mkdir()
    path = directory / f"{OBJECT_UUID}.xml"
    path.write_bytes(xml)
    parsed = parse_appian_xml(path)
    assert parsed is not None
    return parsed


# ---------------------------------------------------------------------------
# Round trip through the real parser
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("object_type", PROVEN_TYPES)
def test_proven_builder_round_trips_identity_and_name(
    tmp_path: Path,
    object_type: ObjectType,
) -> None:
    xml = build_native_process_xml(
        object_type,
        OBJECT_UUID,
        "Order <Review>",
        {"description": "Generated & parsed", "folder_uuid": FOLDER_UUID},
    )

    etree.fromstring(xml)
    parsed = _parse_generated(tmp_path, object_type, xml)

    assert parsed.object_type is object_type
    assert parsed.uuid == OBJECT_UUID
    assert parsed.name == "Order <Review>"
    assert parsed.description == "Generated & parsed"
    assert [role.role_name for role in parsed.security_roles] == [
        "ADMIN_OWNER",
        "EDITOR",
        "EXPLICIT_NONMEMBER",
        "VIEWER",
        "MANAGER",
        "INITIATOR",
    ]


def test_process_model_parses_with_real_node_names(tmp_path: Path) -> None:
    xml = build_native_process_xml(
        ObjectType.PROCESS_MODEL,
        OBJECT_UUID,
        "Order Review",
        {"folder_uuid": FOLDER_UUID},
    )
    parsed = _parse_generated(tmp_path, ObjectType.PROCESS_MODEL, xml)

    assert [node.name for node in parsed.nodes] == ["Start Node", "End Node"]
    assert [node.node_type for node in parsed.nodes] == ["core.0", "core.1"]
    assert [node.lane_index for node in parsed.nodes] == [0, 0]
    assert [lane.name for lane in parsed.swimlanes] == ["System"]
    assert parsed.edges[0].source_uuid == parsed.nodes[0].uuid
    assert parsed.edges[0].target_uuid == parsed.nodes[1].uuid


# ---------------------------------------------------------------------------
# Structural fidelity against the real corpus
# ---------------------------------------------------------------------------

def test_process_model_root_matches_corpus_skeleton(
    reference_model: etree._Element,
) -> None:
    generated = _build_model()

    assert _local_name(generated) == _local_name(reference_model)
    # Real root carries no namespace at all, default or prefixed.
    assert generated.tag == reference_model.tag == "processModelHaul"
    assert generated.nsmap == reference_model.nsmap == {}
    assert _child_names(generated) == _child_names(reference_model)


def test_process_model_port_matches_corpus_namespaces(
    reference_model: etree._Element,
) -> None:
    generated_port = _require_local(_build_model(), "process_model_port")
    reference_port = _require_local(reference_model, "process_model_port")

    assert generated_port.tag == reference_port.tag
    assert generated_port.tag == f"{{{APPIAN_NS}}}process_model_port"
    assert generated_port.get("schemaVersion") == reference_port.get("schemaVersion")
    assert generated_port.nsmap == reference_port.nsmap
    assert _child_names(generated_port) == _child_names(reference_port) == ("pm",)


def test_process_model_pm_and_meta_match_corpus_order(
    reference_model: etree._Element,
) -> None:
    generated_pm = _require_local(
        _require_local(_build_model(), "process_model_port"), "pm"
    )
    reference_pm = _require_local(
        _require_local(reference_model, "process_model_port"), "pm"
    )

    assert _child_names(generated_pm) == _child_names(reference_pm)
    assert _child_names(_require_local(generated_pm, "meta")) == _child_names(
        _require_local(reference_pm, "meta")
    )
    assert len(_require_local(generated_pm, "pvs")) == 0


@pytest.mark.parametrize("gui_id", ["0", "1"])
def test_process_model_nodes_match_corpus_order(
    reference_model: etree._Element,
    gui_id: str,
) -> None:
    generated_pm = _require_local(
        _require_local(_build_model(), "process_model_port"), "pm"
    )
    reference_pm = _require_local(
        _require_local(reference_model, "process_model_port"), "pm"
    )
    generated_node = _node_by_gui_id(generated_pm, gui_id)
    reference_node = _node_by_gui_id(reference_pm, gui_id)

    assert _child_names(generated_node) == _child_names(reference_node)
    assert _child_names(_require_local(generated_node, "ac")) == _child_names(
        _require_local(reference_node, "ac")
    )
    assert generated_node.xpath(
        "string(*[local-name()='ac']/*[local-name()='name'])"
    ) == reference_node.xpath("string(*[local-name()='ac']/*[local-name()='name'])")
    assert _require_local(generated_node, "icon").get("id") == _require_local(
        reference_node, "icon"
    ).get("id")


def test_process_model_connection_matches_corpus_order(
    reference_model: etree._Element,
) -> None:
    generated_pm = _require_local(
        _require_local(_build_model(), "process_model_port"), "pm"
    )
    reference_pm = _require_local(
        _require_local(reference_model, "process_model_port"), "pm"
    )
    generated = _require_local(
        _require_local(_node_by_gui_id(generated_pm, "0"), "connections"), "connection"
    )
    reference = _require_local(
        _require_local(_node_by_gui_id(reference_pm, "0"), "connections"), "connection"
    )

    assert _child_names(generated) == _child_names(reference)
    assert _require_local(generated, "to").text == _require_local(reference, "to").text


def test_process_model_lane_matches_corpus_order(
    reference_lane_shapes: set[tuple[str, ...]],
) -> None:
    generated_pm = _require_local(
        _require_local(_build_model(), "process_model_port"), "pm"
    )
    generated_lane = _require_local(_require_local(generated_pm, "lanes"), "lane")

    assert _child_names(generated_lane) in reference_lane_shapes


def test_process_model_locale_and_role_map_match_corpus(
    reference_model: etree._Element,
) -> None:
    generated = _build_model()
    generated_meta = _require_local(
        _require_local(_require_local(generated, "process_model_port"), "pm"), "meta"
    )
    reference_meta = _require_local(
        _require_local(_require_local(reference_model, "process_model_port"), "pm"),
        "meta",
    )

    generated_locale = generated_meta.xpath(
        "*[local-name()='name']/*[local-name()='string-map']"
        "/*[local-name()='pair']/*[local-name()='locale']"
    )[0]
    reference_locale = reference_meta.xpath(
        "*[local-name()='name']/*[local-name()='string-map']"
        "/*[local-name()='pair']/*[local-name()='locale'][@lang='en']"
    )[0]
    assert dict(generated_locale.attrib) == dict(reference_locale.attrib)
    assert generated_locale.get("variant") == ""

    generated_roles = _require_local(generated, "roleMap")
    reference_roles = _require_local(reference_model, "roleMap")
    assert [role.get("name") for role in generated_roles] == [
        role.get("name") for role in reference_roles
    ]
    assert _child_names(generated_roles[0]) == _child_names(reference_roles[0])


def test_process_model_trailing_fields_match_corpus(
    reference_model: etree._Element,
) -> None:
    generated = _build_model()
    reference = reference_model

    for name in ("isPublished", "mcpEnabled"):
        assert _require_local(generated, name).text == _require_local(
            reference, name
        ).text
    generated_history = _require_local(
        _require_local(generated, "history"), "historyInfo"
    )
    reference_history = _require_local(
        _require_local(reference, "history"), "historyInfo"
    )
    assert set(generated_history.attrib) == set(reference_history.attrib)
    assert generated_history.get("versionUuid") == generated.xpath(
        "string(*[local-name()='versionUuid'])"
    )


# ---------------------------------------------------------------------------
# Identity freshness and required inputs
# ---------------------------------------------------------------------------

def test_process_model_has_fresh_nested_identities() -> None:
    first = _build_model()
    second = _build_model()

    first_nested = first.xpath(
        "//*[local-name()='versionUuid']/text() | //*[local-name()='node']/@uuid"
    )
    second_nested = second.xpath(
        "//*[local-name()='versionUuid']/text() | //*[local-name()='node']/@uuid"
    )

    assert len(first_nested) == 3
    assert len(set(first_nested)) == 3
    assert set(first_nested).isdisjoint(second_nested)
    assert all(UUID(value).version == 4 for value in first_nested)
    assert first.xpath("string(*[local-name()='folderUuid'])") == FOLDER_UUID


def test_process_model_requires_folder_uuid() -> None:
    with pytest.raises(ValueError, match="process_model requires folder_uuid"):
        build_native_process_xml(
            ObjectType.PROCESS_MODEL,
            OBJECT_UUID,
            "Order Review",
            {},
        )


# ---------------------------------------------------------------------------
# Process model folder
# ---------------------------------------------------------------------------

def _build_folder(**overrides: object) -> etree._Element:
    fields: dict[str, object] = {"description": "Stores process models"}
    fields.update(overrides)
    return etree.fromstring(
        build_native_process_xml(
            ObjectType.PROCESS_MODEL_FOLDER,
            OBJECT_UUID,
            "Processes",
            fields,
        )
    )


def test_process_model_folder_matches_corpus_skeleton(
    reference_folders: list[etree._Element],
) -> None:
    reference = next(
        root
        for root in reference_folders
        if not root.xpath("//*[local-name()='parentFolderUuid']")
    )
    generated = _build_folder()

    # Real folder root declares the a: prefix only, never a default namespace.
    assert generated.tag == reference.tag == "processModelFolderHaul"
    assert generated.nsmap == reference.nsmap == {"a": APPIAN_NS}
    assert _child_names(generated) == _child_names(reference)
    assert _child_names(_require_local(generated, "processModelFolder")) == _child_names(
        _require_local(reference, "processModelFolder")
    )

    generated_roles = _require_local(generated, "roleMap")
    reference_roles = _require_local(reference, "roleMap")
    assert [role.get("name") for role in generated_roles] == [
        role.get("name") for role in reference_roles
    ]
    assert _child_names(generated_roles[0]) == _child_names(reference_roles[0])


def test_process_model_folder_parent_uuid_matches_corpus_position(
    reference_folders: list[etree._Element],
) -> None:
    reference = next(
        (
            root
            for root in reference_folders
            if root.xpath("//*[local-name()='parentFolderUuid']")
        ),
        None,
    )
    if reference is None:
        pytest.skip("[WARN] no nested processModelFolder in corpus")
    generated = _build_folder(parent_folder_uuid=PARENT_FOLDER_UUID)

    assert _child_names(_require_local(generated, "processModelFolder")) == _child_names(
        _require_local(reference, "processModelFolder")
    )
    assert generated.xpath("string(//*[local-name()='parentFolderUuid'])") == (
        PARENT_FOLDER_UUID
    )


def test_process_model_folder_history_matches_version_uuid() -> None:
    first = _build_folder()
    second = _build_folder()

    first_version = first.xpath("string(*[local-name()='versionUuid'])")
    second_version = second.xpath("string(*[local-name()='versionUuid'])")

    assert UUID(first_version).version == 4
    assert first_version != second_version
    assert first.xpath(
        "string(*[local-name()='history']/*[local-name()='historyInfo']/@versionUuid)"
    ) == first_version


# ---------------------------------------------------------------------------
# Rejected types
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("object_type", UNPROVEN_TYPES)
def test_unproven_types_refuse_to_emit_speculative_xml(
    object_type: ObjectType,
) -> None:
    with pytest.raises(ValueError, match="No Appian export sample available for"):
        build_native_process_xml(object_type, OBJECT_UUID, "Anything", {})


@pytest.mark.parametrize("object_type", UNPROVEN_TYPES)
def test_unproven_types_have_no_corpus_directory(
    corpus_dir: Path,
    object_type: ObjectType,
) -> None:
    export_dir = corpus_dir / CAPABILITY_BY_TYPE[object_type].export_dir
    assert not export_dir.is_dir(), (
        f"[ERROR] corpus now contains {export_dir.name}/; the native shape is "
        "provable and build_native_process_xml must stop refusing it"
    )


def test_unsupported_type_raises_value_error() -> None:
    with pytest.raises(ValueError, match="Unsupported native process object type"):
        build_native_process_xml(
            ObjectType.INTERFACE,
            OBJECT_UUID,
            "Unsupported",
            {},
        )
