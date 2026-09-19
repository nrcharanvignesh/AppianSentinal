"""R20: the agent must create objects on all three Appian tiers.

The suite previously proved generation on the content tier only, so a writer
that emitted unreadable record types and process models went unnoticed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from appian_sentinel.agent.orchestrator import Orchestrator
from appian_sentinel.agent.state import AgentState
from appian_sentinel.parser.codebase_map import build_codebase_map

INTERFACE_UUID = "_a-55555555-5555-8000-5555-555555555555_100005"
RECORD_UUID = "66666666-6666-4666-8666-666666666666"
PROCESS_UUID = "77777777-7777-4777-8777-777777777777"
VERSION_UUID = "_a-88888888-8888-8000-8888-888888888888_100008"

GENERATED_OBJECTS: list[dict[str, Any]] = [
    {
        "type": "interface",
        "name": "APP_RequestView",
        "uuid": INTERFACE_UUID,
        "versionUuid": VERSION_UUID,
        "action": "create",
        "sail_code": 'a!localVariables(local!x: "ok", a!textField(label: local!x))',
        "rule_inputs": [],
    },
    {
        "type": "record_type",
        "name": "APP_Request",
        "uuid": RECORD_UUID,
        "versionUuid": VERSION_UUID,
        "action": "create",
        "fields": [{"name": "status", "type": "Text"}],
    },
    {
        "type": "process_model",
        "name": "APP_Request_Approval",
        "uuid": PROCESS_UUID,
        "versionUuid": VERSION_UUID,
        "action": "create",
        "processVariables": [{"name": "requestId", "type": "Text"}],
    },
]


async def _fake_llm(_messages: list[dict[str, str]], **_kwargs: Any) -> str:
    return json.dumps(GENERATED_OBJECTS)


def _state() -> AgentState:
    state = AgentState(max_iterations=1)
    state.user_story = {
        "title": "Request approval",
        "acceptance_criteria": [{"id": "AC-1", "description": "Requests are stored."}],
    }
    return state


@pytest.mark.asyncio
async def test_agent_creates_objects_on_all_three_tiers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = Orchestrator(_state())
    agent._workspace = tmp_path
    agent._export_dir = tmp_path
    monkeypatch.setattr(
        "appian_sentinel.agent.orchestrator.llm_client.llm.chat",
        _fake_llm,
    )

    written = await agent.step_4_implementation({"raw": "design"})

    assert len(written) == 3
    assert len(agent.state.created_files) == 3

    # Every tier must survive a real re-parse, not just land on disk.
    codebase = build_codebase_map(tmp_path)
    for uuid, name in (
        (INTERFACE_UUID, "APP_RequestView"),
        (RECORD_UUID, "APP_Request"),
        (PROCESS_UUID, "APP_Request_Approval"),
    ):
        parsed = codebase.get_object(uuid)
        assert parsed is not None, f"agent-generated {uuid} did not parse back"
        assert parsed.name == name
        assert codebase.resolve_uuid(name) == uuid
