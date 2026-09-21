from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from lxml import etree

from appian_sentinel.agent.orchestrator import Orchestrator
from appian_sentinel.agent.state import AgentState
from appian_sentinel.config import settings
from appian_sentinel.mcp_server import cache, tools
from appian_sentinel.mcp_server.models import (
    CreateTypedObjectRequest,
    DeleteTypedObjectRequest,
    TypedObjectRequest,
    UpdateTypedObjectRequest,
)
from appian_sentinel.models.appian_objects import ObjectType
from appian_sentinel.packager.zip_builder import build_appian_zip
from appian_sentinel.parser.codebase_map import parse_export_log
from appian_sentinel.services import export_mutations
from appian_sentinel.services.export_mutations import (
    MutationError,
    create_typed_object,
    delete_typed_object,
    get_typed_object,
)
from appian_sentinel.services.mutation_transaction import MutationTransaction
from appian_sentinel.services.workspace import WorkspaceHistoryService
from appian_sentinel.web.routes import _sessions

RULE_UUID = "_a-11111111-1111-8000-1111-111111111111_100001"
CONSTANT_UUID = "_a-11111111-1111-8000-1111-111111111111_100002"
SITE_UUID = "site-template-1"


def _export(root: Path) -> Path:
    application = root / "application"
    content = root / "content"
    site = root / "site"
    meta = root / "META-INF"
    application.mkdir(parents=True)
    content.mkdir(parents=True)
    site.mkdir()
    meta.mkdir()
    (content / f"{RULE_UUID}.xml").write_text(
        (
            "<contentHaul><versionUuid>version</versionUuid><rule>"
            f"<name>APP_Rule</name><uuid>{RULE_UUID}</uuid>"
            "<definition>1</definition></rule></contentHaul>"
        ),
        encoding="utf-8",
    )
    (content / f"{CONSTANT_UUID}.xml").write_text(
        (
            "<contentHaul><versionUuid>version</versionUuid><constant>"
            f"<name>APP_Constant</name><uuid>{CONSTANT_UUID}</uuid>"
            "<typedValue><type><name>Integer</name></type><value>1</value>"
            "</typedValue></constant></contentHaul>"
        ),
        encoding="utf-8",
    )
    (site / f"{SITE_UUID}.xml").write_text(
        f'<siteHaul><versionUuid>v1</versionUuid><site uuid="{SITE_UUID}" name="APP_Site"/></siteHaul>',
        encoding="utf-8",
    )
    (meta / "MANIFEST.MF").write_text("Manifest-Version: 1.0\n", encoding="utf-8")
    (meta / "export.log").write_text(
        (
            "Success (3):\n"
            f'rule 1 {RULE_UUID} "APP_Rule"\n'
            f'constant 2 {CONSTANT_UUID} "APP_Constant"\n'
            f'site 2 {SITE_UUID} "APP_Site"\n'
        ),
        encoding="utf-8",
    )
    (application / "app.xml").write_text(
        (
            "<applicationHaul><application><associatedObjects><globalIdMap>"
            f"<item><type>content</type><uuids><uuid>{RULE_UUID}</uuid>"
            f"<uuid>{CONSTANT_UUID}</uuid></uuids></item>"
            f"<item><type>site</type><uuids><uuid>{SITE_UUID}</uuid></uuids></item>"
            "</globalIdMap></associatedObjects></application></applicationHaul>"
        ),
        encoding="utf-8",
    )
    WorkspaceHistoryService(root).create_baseline(
        actor="system",
        requirement="",
        message="baseline",
    )
    return root


@pytest.fixture
def export_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(settings, "sentinel_workspace", tmp_path)
    cache._MEM_CACHE.clear()
    return _export(tmp_path / "export")


def test_template_create_commits_parseable_export_log(export_dir: Path) -> None:
    created = create_typed_object(
        export_dir,
        ObjectType.EXPRESSION_RULE,
        name="APP_Created",
        fields={"definition": "1"},
    )
    uuid = created["uuid"]
    assert created["source"] == "native_writer"
    assert created["template_uuid"] == ""
    log = parse_export_log(export_dir / "META-INF" / "export.log")
    assert log[uuid] == "APP_Created"
    history = WorkspaceHistoryService(export_dir)
    assert history.working_changes() == []
    head = history.head()
    assert head is not None
    parent = next(item.parent for item in history.log() if item.hash == head)
    changed = {item.path for item in history.diff(parent, head)}
    assert f"content/{uuid}.xml" in changed
    assert "application/app.xml" in changed
    assert "META-INF/export.log" in changed
    application = etree.parse(str(export_dir / "application" / "app.xml"))
    assert application.xpath(
        "boolean(.//*[local-name()='item'][*[local-name()='type' and text()='content']]"
        f"/*[local-name()='uuids']/*[local-name()='uuid' and text()='{uuid}'])"
    )


def test_template_create_rolls_back_object_and_metadata(
    export_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before_log = (export_dir / "META-INF" / "export.log").read_bytes()
    before_application = (export_dir / "application" / "app.xml").read_bytes()
    calls = 0

    def transaction(root: Path) -> MutationTransaction:
        def fail_second_write(path: Path) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError(f"injected failure at {path.name}")

        return MutationTransaction(root, on_applied=fail_second_write)

    monkeypatch.setattr(export_mutations, "MutationTransaction", transaction)
    with pytest.raises(MutationError) as error:
        create_typed_object(
            export_dir,
            ObjectType.EXPRESSION_RULE,
            name="APP_Rollback",
            fields={"uuid": "rollback-rule", "definition": "1"},
        )

    assert error.value.reason == "transaction_failed"
    assert not (export_dir / "content" / "rollback-rule.xml").exists()
    assert (export_dir / "META-INF" / "export.log").read_bytes() == before_log
    assert (export_dir / "application" / "app.xml").read_bytes() == before_application


def test_unproven_create_requires_same_type_template(export_dir: Path) -> None:
    with pytest.raises(MutationError) as template_error:
        create_typed_object(export_dir, ObjectType.AI_AGENT, name="APP_AI")
    assert template_error.value.reason == "template_required"
    assert template_error.value.details["requirement"] == "real_export_template"

    with pytest.raises(MutationError) as event_error:
        create_typed_object(
            export_dir,
            ObjectType.EVENT_CONSUMER,
            name="APP_Event",
        )
    assert event_error.value.reason == "template_required"
    assert event_error.value.details["requirement"] == "real_export_template"


def test_native_create_without_same_type_template(export_dir: Path) -> None:
    (export_dir / "site" / f"{SITE_UUID}.xml").unlink()
    cache.get_codebase(export_dir, rebuild=True)

    created = create_typed_object(
        export_dir,
        ObjectType.SITE,
        name="APP_NativeSite",
    )

    assert created["source"] == "native_writer"
    assert created["template_uuid"] == ""
    assert Path(created["file_path"]).exists()
    assert get_typed_object(
        export_dir, ObjectType.SITE, created["uuid"]
    )["name"] == "APP_NativeSite"


def test_native_create_reports_missing_required_fields(export_dir: Path) -> None:
    with pytest.raises(MutationError) as process_error:
        create_typed_object(
            export_dir,
            ObjectType.PROCESS_MODEL,
            name="APP_Process",
        )
    assert process_error.value.reason == "invalid_fields"
    assert "folder_uuid" in process_error.value.details["message"]


def test_create_clones_same_type_template(export_dir: Path) -> None:
    created = create_typed_object(
        export_dir,
        ObjectType.SITE,
        name="APP_ClonedSite",
        template_uuid=SITE_UUID,
    )
    path = Path(created["file_path"])
    root = etree.parse(str(path)).getroot()
    site = root.find("site")
    assert site is not None
    assert site.xpath("string(@*[local-name()='uuid'])") == created["uuid"]
    assert site.get("name") == "APP_ClonedSite"
    assert created["uuid"] != SITE_UUID
    assert parse_export_log(export_dir / "META-INF" / "export.log")[created["uuid"]] == "APP_ClonedSite"


def test_delete_is_blocked_by_missing_force_when_parented(export_dir: Path) -> None:
    child_uuid = "_a-22222222-2222-8000-2222-222222222222_100002"
    (export_dir / "content" / f"{child_uuid}.xml").write_text(
        (
            "<contentHaul><rule>"
            f"<name>APP_Child</name><uuid>{child_uuid}</uuid>"
            f"<parentUuid>{RULE_UUID}</parentUuid><definition>1</definition>"
            "</rule></contentHaul>"
        ),
        encoding="utf-8",
    )
    cache.get_codebase(export_dir, rebuild=True)
    with pytest.raises(MutationError) as blocked:
        delete_typed_object(export_dir, ObjectType.EXPRESSION_RULE, RULE_UUID)
    assert blocked.value.reason == "dependency_blocked"


def test_packaging_keeps_created_export_log_line(export_dir: Path, tmp_path: Path) -> None:
    created = create_typed_object(
        export_dir,
        ObjectType.CONSTANT,
        name="APP_Limit",
        fields={"definition": "50"},
    )
    zip_path = tmp_path / "rebuilt.zip"
    build_appian_zip(export_dir, zip_path, [])
    import zipfile

    with zipfile.ZipFile(zip_path) as archive:
        log = archive.read("META-INF/export.log").decode("utf-8")
    assert f'content 1 {created["uuid"]} "APP_Limit"' in log


def test_mcp_typed_crud_roundtrip(export_dir: Path) -> None:
    created = tools.create_typed(
        ObjectType.EXPRESSION_RULE,
        CreateTypedObjectRequest(
            export_dir=str(export_dir),
            name="APP_Mcp",
            fields={"definition": "1"},
        ),
    )
    assert created.status == "created"
    fetched = tools.get_typed(
        ObjectType.EXPRESSION_RULE,
        TypedObjectRequest(export_dir=str(export_dir), object_uuid=created.uuid),
    )
    assert fetched.status == "ok"
    assert fetched.object is not None
    assert fetched.object["name"] == "APP_Mcp"
    renamed = tools.update_typed(
        ObjectType.SITE,
        UpdateTypedObjectRequest(
            export_dir=str(export_dir),
            object_uuid=SITE_UUID,
            fields={"name": "APP_SiteRenamed"},
        ),
    )
    assert renamed.status == "updated"
    assert parse_export_log(export_dir / "META-INF" / "export.log")[SITE_UUID] == "APP_SiteRenamed"
    deleted = tools.delete_typed(
        ObjectType.EXPRESSION_RULE,
        DeleteTypedObjectRequest(
            export_dir=str(export_dir),
            object_uuid=created.uuid,
            preview=False,
        ),
    )
    assert deleted.status == "deleted"
    assert created.uuid not in parse_export_log(export_dir / "META-INF" / "export.log")


def test_rest_typed_routes(export_dir: Path) -> None:
    _sessions.clear()
    state = AgentState()
    state.export_dir = str(export_dir)
    state.codebase_map = {"objects": {}}
    _sessions["typed"] = {
        "state": state,
        "orchestrator": Orchestrator(state),
        "run_task": None,
    }
    from appian_sentinel.main import app

    client = TestClient(app)
    created = client.post(
        "/api/typed-objects/expression_rule?session_id=typed",
        json={"name": "APP_Rest", "fields": {"definition": "1"}},
    )
    assert created.status_code == 200
    uuid = created.json()["uuid"]
    fetched = client.get(f"/api/typed-objects/expression_rule/{uuid}?session_id=typed")
    assert fetched.status_code == 200
    assert fetched.json()["name"] == "APP_Rest"
    preview = client.delete(
        f"/api/typed-objects/expression_rule/{uuid}?session_id=typed"
    )
    assert preview.json()["status"] == "preview"
    deleted = client.delete(
        f"/api/typed-objects/expression_rule/{uuid}?session_id=typed&preview=false"
    )
    assert deleted.json()["status"] == "deleted"


def test_get_typed_object_rejects_type_mismatch(export_dir: Path) -> None:
    with pytest.raises(MutationError) as mismatch:
        get_typed_object(export_dir, ObjectType.INTERFACE, RULE_UUID)
    assert mismatch.value.reason == "type_mismatch"
