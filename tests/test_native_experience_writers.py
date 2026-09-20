from __future__ import annotations

import os
import tempfile
from pathlib import Path
from uuid import UUID

import pytest
from lxml import etree

from appian_sentinel.generator.native_experience_writers import (
    APPIAN_NS,
    CONTENT_ROLE_NAMES,
    PORTAL_ROLE_NAMES,
    SITE_ROLE_NAMES,
    TEMPO_REPORT_ROLE_NAMES,
    XSI_NS,
    build_native_experience_xml,
)
from appian_sentinel.models.appian_objects import ObjectType
from appian_sentinel.models.object_registry import CAPABILITY_BY_TYPE
from appian_sentinel.parser.xml_parser import parse_appian_xml

OBJECT_UUID = "44444444-4444-4444-8444-444444444444"
SERVICE_ACCOUNT_UUID = "sv.portal"

# Only these four types have a proven native shape in the real export corpus.
PROVEN_TYPES = (
    ObjectType.SITE,
    ObjectType.PORTAL,
    ObjectType.REPORT,
    ObjectType.TEMPO_REPORT,
)

UNPROVEN_TYPES = (
    ObjectType.DASHBOARD,
    ObjectType.CONTROL_PANEL,
    ObjectType.CONTROL_PANEL_HIERARCHY_ITEM,
)


# ---------------------------------------------------------------------------
# Element helpers
# ---------------------------------------------------------------------------

def _child_names(element: etree._Element) -> tuple[str, ...]:
    """Return the ordered local names of the element children, skipping comments."""
    return tuple(
        etree.QName(child).localname
        for child in element
        if isinstance(child.tag, str)
    )


def _find_local(parent: etree._Element, name: str) -> etree._Element | None:
    found = parent.xpath(f"*[local-name()='{name}']")
    return found[0] if found else None


def _require_local(parent: etree._Element, name: str) -> etree._Element:
    element = _find_local(parent, name)
    assert element is not None, (
        f"missing <{name}> in <{etree.QName(parent).localname}>"
    )
    return element


def _assert_ordered_subset(
    generated: tuple[str, ...],
    reference: tuple[str, ...],
) -> None:
    """Assert the generated children keep the real export order.

    Generated objects carry a subset of the fields a real object holds, so the
    names must appear in the reference and in the same relative order.
    """
    missing = [name for name in generated if name not in reference]
    assert not missing, f"[ERROR] {missing} never appear in the real export"
    positions = [reference.index(name) for name in generated]
    assert positions == sorted(positions), (
        f"[ERROR] generated order {generated} contradicts real order {reference}"
    )


# ---------------------------------------------------------------------------
# Real corpus access
# ---------------------------------------------------------------------------

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


def _roots(directory: Path) -> list[etree._Element]:
    return [
        etree.parse(str(path)).getroot()
        for path in sorted(directory.glob("*.xml"))
    ]


@pytest.fixture(scope="session")
def reference_sites(corpus_dir: Path) -> list[etree._Element]:
    roots = _roots(corpus_dir / "site")
    if not roots:
        pytest.skip("[WARN] no site files in corpus")
    return roots


@pytest.fixture(scope="session")
def reference_site(reference_sites: list[etree._Element]) -> etree._Element:
    """Return a real site whose roleMap holds every role the builder emits."""
    for root in reference_sites:
        names = tuple(
            role.get("name") for role in _require_local(root, "roleMap")
        )
        if names == SITE_ROLE_NAMES:
            return root
    pytest.skip("[WARN] no site in corpus uses both site roles")


@pytest.fixture(scope="session")
def reference_portal(corpus_dir: Path) -> etree._Element:
    roots = _roots(corpus_dir / "portal")
    if not roots:
        pytest.skip("[WARN] no portal files in corpus")
    return roots[0]


@pytest.fixture(scope="session")
def reference_tempo_report(corpus_dir: Path) -> etree._Element:
    roots = _roots(corpus_dir / "tempoReport")
    if not roots:
        pytest.skip("[WARN] no tempoReport files in corpus")
    return roots[0]


@pytest.fixture(scope="session")
def reference_report(corpus_dir: Path) -> etree._Element:
    """Return the real contentHaul whose subtype element is <report>.

    The content directory holds thousands of files, so the discriminator is
    matched on a bounded head read before any file is parsed.
    """
    for path in sorted((corpus_dir / "content").glob("*.xml")):
        with path.open("rb") as handle:
            head = handle.read(4096)
        if b"<report>" not in head:
            continue
        root = etree.parse(str(path)).getroot()
        if _find_local(root, "report") is not None:
            return root
    pytest.skip("[WARN] no content report in corpus")


# ---------------------------------------------------------------------------
# Generated output helpers
# ---------------------------------------------------------------------------

def _build(object_type: ObjectType, **fields: object) -> etree._Element:
    return etree.fromstring(
        build_native_experience_xml(
            object_type,
            OBJECT_UUID,
            "Order Review",
            dict(fields),
        )
    )


def _parse_generated(
    tmp_path: Path,
    object_type: ObjectType,
    xml: bytes,
) -> object:
    directory = tmp_path / CAPABILITY_BY_TYPE[object_type].export_dir
    directory.mkdir(parents=True, exist_ok=True)
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
    xml = build_native_experience_xml(
        object_type,
        OBJECT_UUID,
        "Order <Review>",
        {"description": "Generated & parsed"},
    )

    parsed = _parse_generated(tmp_path, object_type, xml)

    assert parsed.object_type is object_type
    assert parsed.uuid == OBJECT_UUID
    assert parsed.name == "Order <Review>"
    assert parsed.description == "Generated & parsed"


@pytest.mark.parametrize(
    ("object_type", "role_names"),
    [
        (ObjectType.SITE, SITE_ROLE_NAMES),
        (ObjectType.PORTAL, PORTAL_ROLE_NAMES),
        (ObjectType.REPORT, CONTENT_ROLE_NAMES),
        (ObjectType.TEMPO_REPORT, TEMPO_REPORT_ROLE_NAMES),
    ],
)
def test_generated_role_map_survives_the_parser(
    tmp_path: Path,
    object_type: ObjectType,
    role_names: tuple[str, ...],
) -> None:
    xml = build_native_experience_xml(object_type, OBJECT_UUID, "Order Review", {})

    parsed = _parse_generated(tmp_path, object_type, xml)

    assert tuple(role.role_name for role in parsed.security_roles) == role_names
    assert all(not role.users and not role.groups for role in parsed.security_roles)


def test_site_and_portal_details_round_trip(tmp_path: Path) -> None:
    site = _parse_generated(
        tmp_path / "site-case",
        ObjectType.SITE,
        build_native_experience_xml(
            ObjectType.SITE,
            OBJECT_UUID,
            "Order Review",
            {"url_stub": "order-review"},
        ),
    )
    portal = _parse_generated(
        tmp_path / "portal-case",
        ObjectType.PORTAL,
        build_native_experience_xml(
            ObjectType.PORTAL,
            OBJECT_UUID,
            "Order Portal",
            {
                "display_name": "Order Portal",
                "url_stub": "order-portal",
                "hostname": "example.appianportals.com",
                "published": True,
                "service_account_uuid": SERVICE_ACCOUNT_UUID,
            },
        ),
    )

    assert site.url_stub == "order-review"
    assert site.description == ""
    assert portal.display_name == "Order Portal"
    assert portal.url_stub == "order-portal"
    assert portal.hostname == "example.appianportals.com"
    assert portal.published is True
    assert portal.service_account_uuid == SERVICE_ACCOUNT_UUID


def test_tempo_report_expression_round_trips(tmp_path: Path) -> None:
    parsed = _parse_generated(
        tmp_path,
        ObjectType.TEMPO_REPORT,
        build_native_experience_xml(
            ObjectType.TEMPO_REPORT,
            OBJECT_UUID,
            "Order Review",
            {"expression": '=#"rule!orderReview"()', "url_stub": "qayg8w"},
        ),
    )

    assert parsed.expression == '=#"rule!orderReview"()'
    assert parsed.url_stub == "qayg8w"


# ---------------------------------------------------------------------------
# Site fidelity against the real corpus
# ---------------------------------------------------------------------------

def test_site_root_matches_corpus_skeleton(reference_site: etree._Element) -> None:
    generated = _build(ObjectType.SITE, url_stub="order-review")

    assert generated.tag == reference_site.tag == "siteHaul"
    # Real root declares the a: and xsi: prefixes, so the builder must too.
    assert generated.nsmap == reference_site.nsmap == {"a": APPIAN_NS, "xsi": XSI_NS}
    assert _child_names(generated) == _child_names(reference_site)


def test_site_body_matches_corpus_order(reference_site: etree._Element) -> None:
    generated = _require_local(
        _build(ObjectType.SITE, url_stub="order-review"), "site"
    )
    reference = _require_local(reference_site, "site")

    assert generated.get(f"{{{APPIAN_NS}}}uuid") == OBJECT_UUID
    assert generated.get("name") == "Order Review"
    assert set(generated.attrib) == set(reference.attrib)
    _assert_ordered_subset(_child_names(generated), _child_names(reference))
    assert _child_names(generated) == ("description", "urlStub", "visibility")
    assert _require_local(generated, "visibility").text == (
        _require_local(reference, "visibility").text
    )


def test_site_always_emits_the_description_element(
    reference_sites: list[etree._Element],
) -> None:
    empty_in_corpus = [
        root
        for root in reference_sites
        if _require_local(_require_local(root, "site"), "description").text is None
    ]
    assert empty_in_corpus, "[WARN] corpus no longer proves an empty <description/>"

    generated = _require_local(_build(ObjectType.SITE), "site")
    description = _require_local(generated, "description")

    assert description.text is None
    assert b"<description/>" in build_native_experience_xml(
        ObjectType.SITE, OBJECT_UUID, "Order Review", {}
    )


# ---------------------------------------------------------------------------
# Portal fidelity against the real corpus
# ---------------------------------------------------------------------------

def _generated_portal() -> etree._Element:
    return _build(
        ObjectType.PORTAL,
        display_name="Order Portal",
        url_stub="order-portal",
        hostname="example.appianportals.com",
        published=True,
        service_account_uuid=SERVICE_ACCOUNT_UUID,
    )


def test_portal_root_matches_corpus_skeleton(
    reference_portal: etree._Element,
) -> None:
    generated = _generated_portal()

    assert generated.tag == reference_portal.tag == "portalHaul"
    # Real portal root declares only a:; xsi is declared where it is used.
    assert generated.nsmap == reference_portal.nsmap == {"a": APPIAN_NS}
    assert _child_names(generated) == _child_names(reference_portal)


def test_portal_body_preserves_real_field_order(
    reference_portal: etree._Element,
) -> None:
    generated = _require_local(_generated_portal(), "portal")
    reference = _require_local(reference_portal, "portal")

    _assert_ordered_subset(_child_names(generated), _child_names(reference))
    assert _child_names(generated) == (
        "description",
        "published",
        "displayName",
        "urlStub",
        "serviceAccountUser",
        "hostname",
    )


def test_portal_description_is_empty_like_the_corpus(
    reference_portal: etree._Element,
) -> None:
    reference = _require_local(_require_local(reference_portal, "portal"), "description")
    generated = _require_local(
        _require_local(_generated_portal(), "portal"), "description"
    )

    assert reference.text is None
    assert generated.text is None


def test_portal_service_account_matches_corpus_typing(
    reference_portal: etree._Element,
) -> None:
    reference = _require_local(
        _require_local(reference_portal, "portal"), "serviceAccountUser"
    )
    generated = _require_local(
        _require_local(_generated_portal(), "portal"), "serviceAccountUser"
    )

    assert generated.get(f"{{{XSI_NS}}}type") == reference.get(f"{{{XSI_NS}}}type")
    assert generated.get(f"{{{XSI_NS}}}type") == "a:User"
    assert generated.get(f"{{{APPIAN_NS}}}uuid") == SERVICE_ACCOUNT_UUID
    # xsi is declared on the element itself, exactly as the real export does.
    assert generated.nsmap == reference.nsmap == {"a": APPIAN_NS, "xsi": XSI_NS}
    assert tuple(generated.attrib) == tuple(reference.attrib)


# ---------------------------------------------------------------------------
# Tempo report and content report fidelity against the real corpus
# ---------------------------------------------------------------------------

def test_tempo_report_matches_corpus_shape(
    reference_tempo_report: etree._Element,
) -> None:
    generated = _build(
        ObjectType.TEMPO_REPORT,
        description="Legal information",
        expression='=#"rule!orderReview"()',
        url_stub="qayg8w",
    )
    generated_body = _require_local(generated, "tempoReport")
    reference_body = _require_local(reference_tempo_report, "tempoReport")

    assert generated.nsmap == reference_tempo_report.nsmap == {"a": APPIAN_NS}
    assert _child_names(generated) == _child_names(reference_tempo_report)
    # Body children stay in the Appian namespace, unlike the site and portal.
    assert [child.tag for child in generated_body] == [
        child.tag for child in reference_body
    ]
    assert set(generated_body.attrib) == set(reference_body.attrib)


def test_report_matches_corpus_prefix(reference_report: etree._Element) -> None:
    generated = _build(
        ObjectType.REPORT,
        description="Process task report (Report)",
        parent_uuid="parent-content-uuid",
    )
    generated_body = _require_local(generated, "report")
    reference_body = _require_local(reference_report, "report")

    assert generated.nsmap == reference_report.nsmap == {"a": APPIAN_NS}
    assert _child_names(generated) == _child_names(reference_report)
    generated_names = _child_names(generated_body)
    assert generated_names == _child_names(reference_body)[: len(generated_names)]
    assert generated_names == ("name", "uuid", "description", "parentUuid")


def test_report_role_map_matches_corpus_roles_without_public_access(
    reference_report: etree._Element,
) -> None:
    generated = _require_local(_build(ObjectType.REPORT), "roleMap")
    reference = _require_local(reference_report, "roleMap")

    assert [dict(role.attrib) for role in generated] == [
        dict(role.attrib) for role in reference
    ]
    assert tuple(role.get("name") for role in generated) == CONTENT_ROLE_NAMES
    # The corpus sample is public; generated reports must not inherit that.
    assert reference.get("public") == "true"
    assert generated.get("public") is None


# ---------------------------------------------------------------------------
# Shared roleMap and history skeletons
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("object_type", "reference_name", "role_names"),
    [
        (ObjectType.SITE, "reference_site", SITE_ROLE_NAMES),
        (ObjectType.PORTAL, "reference_portal", PORTAL_ROLE_NAMES),
        (ObjectType.TEMPO_REPORT, "reference_tempo_report", TEMPO_REPORT_ROLE_NAMES),
    ],
)
def test_role_map_skeleton_matches_corpus_roles(
    request: pytest.FixtureRequest,
    object_type: ObjectType,
    reference_name: str,
    role_names: tuple[str, ...],
) -> None:
    reference = _require_local(request.getfixturevalue(reference_name), "roleMap")
    generated = _require_local(_build(object_type), "roleMap")

    assert tuple(role.get("name") for role in generated) == role_names
    assert tuple(role.get("name") for role in reference) == role_names
    assert _child_names(generated[0]) == _child_names(reference[0]) == (
        "users",
        "groups",
    )
    # Membership belongs to the target environment, so it stays empty.
    assert not generated.xpath(".//*[local-name()='groupUuid']")


@pytest.mark.parametrize(
    ("object_type", "reference_name"),
    [
        (ObjectType.SITE, "reference_site"),
        (ObjectType.PORTAL, "reference_portal"),
        (ObjectType.TEMPO_REPORT, "reference_tempo_report"),
        (ObjectType.REPORT, "reference_report"),
    ],
)
def test_history_matches_corpus_and_current_version(
    request: pytest.FixtureRequest,
    object_type: ObjectType,
    reference_name: str,
) -> None:
    reference = request.getfixturevalue(reference_name)
    generated = _build(object_type)
    generated_entry = _require_local(_require_local(generated, "history"), "historyInfo")
    reference_entry = _require_local(_require_local(reference, "history"), "historyInfo")
    version_uuid = generated.xpath("string(*[local-name()='versionUuid'])")

    assert set(generated_entry.attrib) == set(reference_entry.attrib)
    assert generated_entry.get("versionUuid") == version_uuid
    # The last real history entry is always the current version.
    assert reference.xpath(
        "string(*[local-name()='history']/*[local-name()='historyInfo'][last()]"
        "/@versionUuid)"
    ) == reference.xpath("string(*[local-name()='versionUuid'])")


@pytest.mark.parametrize("object_type", PROVEN_TYPES)
def test_version_uuid_is_fresh_unless_supplied(object_type: ObjectType) -> None:
    first = _build(object_type).xpath("string(*[local-name()='versionUuid'])")
    second = _build(object_type).xpath("string(*[local-name()='versionUuid'])")
    supplied = _build(object_type, version_uuid="supplied-version").xpath(
        "string(*[local-name()='versionUuid'])"
    )

    assert first != second
    assert UUID(first).version == 4
    assert supplied == "supplied-version"


# ---------------------------------------------------------------------------
# Rejected types
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("object_type", UNPROVEN_TYPES)
def test_unproven_types_refuse_to_emit_speculative_xml(
    object_type: ObjectType,
) -> None:
    with pytest.raises(ValueError, match="No Appian export sample available for"):
        build_native_experience_xml(object_type, OBJECT_UUID, "Anything", {})


@pytest.mark.parametrize("object_type", UNPROVEN_TYPES)
def test_unproven_types_have_no_corpus_directory(
    corpus_dir: Path,
    object_type: ObjectType,
) -> None:
    export_dir = corpus_dir / CAPABILITY_BY_TYPE[object_type].export_dir

    assert not export_dir.is_dir(), (
        f"[ERROR] corpus now contains {export_dir.name}/; the native shape is "
        "provable and build_native_experience_xml must stop refusing it"
    )


def test_unsupported_type_raises_value_error() -> None:
    with pytest.raises(ValueError, match="Unsupported native experience type"):
        build_native_experience_xml(
            ObjectType.INTERFACE,
            OBJECT_UUID,
            "Unsupported",
            {},
        )


@pytest.mark.parametrize(("uuid", "name"), [("", "Order Review"), (OBJECT_UUID, "  ")])
def test_identity_is_required(uuid: str, name: str) -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        build_native_experience_xml(ObjectType.SITE, uuid, name, {})
