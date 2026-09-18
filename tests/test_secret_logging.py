from __future__ import annotations

import logging
from unittest.mock import AsyncMock

import pytest
from _pytest.logging import LogCaptureFixture
from fastapi.testclient import TestClient

from appian_sentinel.analyzer.impact_analyzer import ImpactAnalyzer
from appian_sentinel.config import settings
from appian_sentinel.web import routes

FAKE_KEY = "sk-SENTINELTESTKEY123"


async def test_llm_provider_error_is_redacted_from_logs(
    monkeypatch: pytest.MonkeyPatch,
    caplog: LogCaptureFixture,
) -> None:
    error = RuntimeError(f"Authorization: Bearer {FAKE_KEY}")
    monkeypatch.setattr(
        "appian_sentinel.analyzer.impact_analyzer.llm.chat_structured",
        AsyncMock(side_effect=error),
    )

    with caplog.at_level(logging.ERROR):
        result = await ImpactAnalyzer()._detect_breaking_changes_with_llm(
            {"objects": {"APP_Test": {"source": "1"}}},
            ["APP_Test"],
            {"APP_Test": []},
        )

    assert result == []
    assert FAKE_KEY not in caplog.text


def test_ado_client_error_is_redacted_from_logs(
    monkeypatch: pytest.MonkeyPatch,
    caplog: LogCaptureFixture,
) -> None:
    monkeypatch.setattr(settings, "ado_pat", FAKE_KEY)
    monkeypatch.setattr(settings, "ado_org", "org")
    monkeypatch.setattr(settings, "ado_project", "project")
    monkeypatch.setattr(settings, "ado_source", "pat")
    monkeypatch.setattr(
        "appian_sentinel.web.routes.ado_client.get_work_item",
        AsyncMock(side_effect=RuntimeError(f"Authorization: Basic {FAKE_KEY}")),
    )
    routes._sessions.clear()
    from appian_sentinel.main import app

    with caplog.at_level(logging.ERROR):
        response = TestClient(app).post("/api/ado/workitem", json={"id": "24"})

    assert response.status_code == 502
    assert FAKE_KEY not in response.text
    assert FAKE_KEY not in caplog.text
