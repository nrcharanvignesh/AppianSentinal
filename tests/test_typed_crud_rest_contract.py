from __future__ import annotations

import inspect
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from appian_sentinel.agent.orchestrator import Orchestrator
from appian_sentinel.agent.state import AgentState
from appian_sentinel.mcp_server import cache
from appian_sentinel.mcp_server.models import DeleteTypedObjectRequest
from appian_sentinel.models.appian_objects import ObjectType
from appian_sentinel.models.object_registry import CAPABILITY_BY_TYPE
from appian_sentinel.web.routes import _sessions, delete_typed_object_route

REAL_EXPORT = Path(__file__).parents[1] / "appian_export"
SESSION_ID = "typed-rest-contract"


@pytest.mark.skipif(not REAL_EXPORT.exists(), reason="real Appian export is not available")
def test_typed_crud_rest_contract_against_real_export(tmp_path: Path) -> None:
    export_dir = tmp_path / "real_export"
    shutil.copytree(REAL_EXPORT, export_dir, ignore=shutil.ignore_patterns(".history"))
    cache._MEM_CACHE.clear()
    codebase = cache.get_codebase(export_dir)
    assert len(codebase.objects) == 2624
    assert not codebase.parse_failures

    state = AgentState()
    state.export_dir = str(export_dir)
    state.codebase_map = codebase.model_dump(mode="json")
    _sessions.clear()
    _sessions[SESSION_ID] = {
        "state": state,
        "orchestrator": Orchestrator(state),
        "run_task": None,
    }

    from appian_sentinel.main import app

    client = TestClient(app)
    query = f"?session_id={SESSION_ID}"

    created = client.post(
        f"/api/typed-objects/expression_rule{query}",
        json={"name": "Sentinel REST Contract", "fields": {"definition": "1"}},
    )
    assert created.status_code == 200, created.text
    assert created.json()["status"] == "created"
    created_uuid = created.json()["uuid"]

    fetched = client.get(
        f"/api/typed-objects/expression_rule/{created_uuid}{query}"
    )
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["name"] == "Sentinel REST Contract"

    updated = client.put(
        f"/api/typed-objects/expression_rule/{created_uuid}{query}",
        json={"fields": {"name": "Sentinel REST Contract Updated"}},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["status"] == "updated"

    unknown_slug = client.get(f"/api/typed-objects/not_a_type/{created_uuid}{query}")
    assert unknown_slug.status_code == 404
    assert unknown_slug.json()["detail"] == "Unknown object type: not_a_type"

    unknown_uuid = client.get(
        f"/api/typed-objects/expression_rule/not-a-real-uuid{query}"
    )
    assert unknown_uuid.status_code == 400
    assert unknown_uuid.json()["detail"] == {
        "reason": "not_found",
        "object_uuid": "not-a-real-uuid",
    }

    blocked_target = next(
        obj
        for obj in codebase.objects.values()
        if obj.object_type is ObjectType.EXPRESSION_RULE
        and codebase.get_direct_dependents(obj.uuid)
    )
    blocked = client.delete(
        f"/api/typed-objects/expression_rule/{blocked_target.uuid}{query}&preview=false"
    )
    assert blocked.status_code == 400
    assert blocked.json()["detail"]["reason"] == "dependency_blocked"
    assert blocked.json()["detail"]["dependents"]

    gated = client.post(
        f"/api/typed-objects/business_process{query}",
        json={"name": "Sentinel Requires Template"},
    )
    assert gated.status_code == 400
    assert gated.json()["detail"] == {
        "reason": "template_required",
        "object_type": "business_process",
        "requirement": "real_export_template",
    }

    deleted = client.delete(
        f"/api/typed-objects/expression_rule/{created_uuid}{query}&preview=false"
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["status"] == "deleted"


def test_delete_contract_has_no_interactive_approval() -> None:
    assert set(DeleteTypedObjectRequest.model_fields) == {
        "export_dir",
        "object_uuid",
        "force",
        "preview",
    }
    assert "approval" not in inspect.signature(delete_typed_object_route).parameters
    assert all(
        "approval" not in capability.delete_tool
        for capability in CAPABILITY_BY_TYPE.values()
    )
