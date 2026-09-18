from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from appian_sentinel.analyzer import story_analyzer
from appian_sentinel.config import settings
from appian_sentinel.generator.sail_generator import SailGenerator
from appian_sentinel.mcp_server import cache, tools
from appian_sentinel.mcp_server.models import (
    GenerateSailRequest,
    GenerateSolutionDesignRequest,
    GenerateTestSuiteRequest,
)
from appian_sentinel.models.appian_objects import Interface
from appian_sentinel.models.codebase import CodebaseMap
from appian_sentinel.models.user_story import (
    AcceptanceCriterion,
    ObjectChange,
    RequirementAnalysis,
    SolutionDesign,
    UserStory,
)
from appian_sentinel.tester.test_generator import TestGenerator as EngineTestGenerator


class FakeOpenAI:
    def __init__(self, code: str) -> None:
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._create),
        )
        self._code = code

    async def _create(self, **kwargs: Any) -> Any:
        del kwargs
        content = json.dumps(
            {
                "code": self._code,
                "confidence": 0.9,
                "notes": ["deterministic"],
                "warnings": [],
            }
        )
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )


class FakeTestLLM:
    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float,
    ) -> str:
        del messages, temperature
        return json.dumps(
            {
                "name": "Generated interface tests",
                "test_cases": [
                    {
                        "id": "TC-001",
                        "name": "Render interface",
                        "type": "functional",
                        "linked_ac": "AC-1",
                        "steps": [{"action": "Open", "expected_output": "Form"}],
                        "expected_result": "Form renders",
                        "priority": "high",
                    }
                ],
                "coverage_map": {"AC-1": ["TC-001"]},
            }
        )


class FakeDesignLLM:
    @property
    def fast_model(self) -> str:
        return "fake"

    async def chat_structured(
        self,
        messages: list[dict[str, Any]],
        response_schema: type[Any],
        *,
        model: str | None = None,
    ) -> Any:
        del messages, model
        if response_schema is RequirementAnalysis:
            return RequirementAnalysis(
                restated_story="Add the requested interface behavior.",
            )
        if response_schema is SolutionDesign:
            return SolutionDesign(
                approach_summary="Modify the existing interface.",
                object_changes=[
                    ObjectChange(
                        object_name="APP_Main",
                        object_type="Interface",
                        action="modify",
                        sail_approach="Add the requested field.",
                    )
                ],
            )
        raise AssertionError(f"Unexpected schema: {response_schema}")


@pytest.fixture
def generation_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, UserStory]:
    export_dir = tmp_path / "export"
    export_dir.mkdir()
    target = Interface(
        uuid="real-interface-uuid",
        name="APP_Main",
        description="Main form",
        definition='a!formLayout(contents: {})',
    )
    codebase = CodebaseMap(
        app_name="APP",
        appian_version="26.2",
        objects={target.uuid: target},
        by_type={"interface": [target.uuid]},
    )
    monkeypatch.setattr(settings, "sentinel_workspace", tmp_path)
    monkeypatch.setattr(settings, "litellm_api_key", "fake-key")
    monkeypatch.setattr(cache, "get_codebase", lambda path, **kwargs: codebase)
    requirement = UserStory(
        title="Add a field",
        description="Add a text field to the form.",
        acceptance_criteria=[
            AcceptanceCriterion(id="AC-1", description="The field is visible")
        ],
    )
    return export_dir, requirement


@pytest.mark.asyncio
async def test_generate_sail_returns_validated_code_for_real_object(
    generation_workspace: tuple[Path, UserStory],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    export_dir, _ = generation_workspace
    fake_generator = SailGenerator(client=FakeOpenAI('a!textField(label: "Name")'))
    monkeypatch.setattr(tools, "SailGenerator", lambda: fake_generator)

    result = await tools.generate_sail(
        GenerateSailRequest(
            export_dir=str(export_dir),
            object_uuid="real-interface-uuid",
            requirements="Add a name field.",
        )
    )

    assert result.object_uuid == "real-interface-uuid"
    assert result.code == 'a!textField(label: "Name")'
    assert result.diagnostics == []


@pytest.mark.asyncio
async def test_generate_sail_rejects_hallucinated_functions(
    generation_workspace: tuple[Path, UserStory],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    export_dir, _ = generation_workspace
    fake_generator = SailGenerator(client=FakeOpenAI("a!inventedFunction()"))
    monkeypatch.setattr(tools, "SailGenerator", lambda: fake_generator)

    with pytest.raises(RuntimeError, match="failed validation"):
        await tools.generate_sail(
            GenerateSailRequest(
                export_dir=str(export_dir),
                object_uuid="real-interface-uuid",
                requirements="Add a field.",
            )
        )


@pytest.mark.asyncio
async def test_generate_test_suite_uses_real_object_identity(
    generation_workspace: tuple[Path, UserStory],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    export_dir, requirement = generation_workspace
    fake_generator = EngineTestGenerator(client=FakeTestLLM())
    monkeypatch.setattr(tools, "TestGenerator", lambda: fake_generator)

    result = await tools.generate_test_suite(
        GenerateTestSuiteRequest(
            export_dir=str(export_dir),
            object_uuid="real-interface-uuid",
            requirement=requirement,
            solution_design="Modify APP_Main.",
        )
    )

    assert result.object_uuid == "real-interface-uuid"
    assert [case.id for case in result.suite.test_cases] == ["TC-001"]


@pytest.mark.asyncio
async def test_generate_solution_design_uses_existing_analyzer(
    generation_workspace: tuple[Path, UserStory],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    export_dir, requirement = generation_workspace
    monkeypatch.setattr(story_analyzer, "llm", FakeDesignLLM())

    result = await tools.generate_solution_design(
        GenerateSolutionDesignRequest(
            export_dir=str(export_dir),
            requirement=requirement,
        )
    )

    assert result.design.approach_summary == "Modify the existing interface."
    assert result.design.object_changes[0].object_name == "APP_Main"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("function_name", "tool_request"),
    [
        (
            "generate_sail",
            GenerateSailRequest(
                export_dir="missing",
                object_uuid="real-interface-uuid",
                requirements="Add a field.",
            ),
        ),
        (
            "generate_test_suite",
            GenerateTestSuiteRequest(
                export_dir="missing",
                object_uuid="real-interface-uuid",
                requirement=UserStory(title="Test"),
                solution_design="Test the object.",
            ),
        ),
        (
            "generate_solution_design",
            GenerateSolutionDesignRequest(
                export_dir="missing",
                requirement=UserStory(title="Design"),
            ),
        ),
    ],
)
async def test_generation_fails_before_network_when_llm_is_not_configured(
    function_name: str,
    tool_request: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "litellm_api_key", "")

    with pytest.raises(RuntimeError, match="Set LITELLM_API_KEY") as exc_info:
        await getattr(tools, function_name)(tool_request)

    assert "secret" not in str(exc_info.value).lower()
