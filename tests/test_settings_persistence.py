from __future__ import annotations

import json
import logging
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from _pytest.logging import LogCaptureFixture
from fastapi.testclient import TestClient

from appian_sentinel.config import settings
from appian_sentinel.services import workspace
from appian_sentinel.web import routes


def test_settings_round_trip_masks_secrets_and_stays_out_of_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: LogCaptureFixture,
) -> None:
    settings_file = tmp_path / "settings.json"
    monkeypatch.setattr(settings, "sentinel_workspace", tmp_path)
    monkeypatch.setattr(routes, "_SETTINGS_FILE", settings_file)
    monkeypatch.setattr(
        "appian_sentinel.analyzer.llm_client.llm.reconfigure",
        lambda: None,
    )
    routes._sessions.clear()

    from appian_sentinel.main import app

    client = TestClient(app)
    api_key = "litellm-secret-value"
    ado_pat = "ado-secret-value"
    payload = {
        "base_url": "https://proxy.example.test/v1",
        "api_key": api_key,
        "protocol": "anthropic",
        "primary_model": "primary-model",
        "fast_model": "fast-model",
        "ado_source": "pat",
        "ado_org": "example-org",
        "ado_project": "example-project",
        "ado_pat": ado_pat,
    }

    posted = client.post("/api/settings", json=payload)
    assert posted.status_code == 200
    assert api_key not in posted.text
    assert ado_pat not in posted.text

    persisted = json.loads(settings_file.read_text(encoding="utf-8"))
    settings.litellm_base_url = "changed"
    settings.litellm_api_key = "changed"
    settings.llm_protocol = "auto"
    settings.sentinel_primary_model = "changed"
    settings.sentinel_fast_model = "changed"
    settings.ado_source = "mcp"
    settings.ado_org = "changed"
    settings.ado_project = "changed"
    settings.ado_pat = "changed"

    assert routes._load_persisted_settings() == persisted
    fetched = client.get("/api/settings")
    assert fetched.status_code == 200
    response = fetched.json()
    for key in (
        "base_url",
        "protocol",
        "primary_model",
        "fast_model",
        "ado_source",
        "ado_org",
        "ado_project",
    ):
        assert response[key] == payload[key]
    assert api_key not in fetched.text
    assert ado_pat not in fetched.text
    assert response["api_key"] == routes._mask_key(api_key)
    assert response["ado_pat"] == routes._mask_key(ado_pat)

    error = RuntimeError(f"transport rejected {api_key} and {ado_pat}")
    monkeypatch.setattr(
        "appian_sentinel.analyzer.llm_client.llm.chat",
        AsyncMock(side_effect=error),
    )
    with caplog.at_level(logging.ERROR):
        tested = client.get("/api/settings/test")
    assert tested.status_code == 502
    assert api_key not in tested.text
    assert ado_pat not in tested.text
    assert api_key not in caplog.text
    assert ado_pat not in caplog.text

    assert "settings.json" not in workspace._TRACKED_ROOTS
    history = workspace.WorkspaceHistoryService(tmp_path)
    baseline = history.create_baseline(actor="system", requirement="R14")
    assert "settings.json" not in baseline.files
