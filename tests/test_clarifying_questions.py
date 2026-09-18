from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel

from appian_sentinel.agent.orchestrator import Orchestrator
from appian_sentinel.agent.state import AgentState
from appian_sentinel.models.user_story import (
    ClarifyingQuestion,
    QuestionPriority,
    UserStory,
)

AMBIGUOUS_CASES = (
    (
        UserStory(title="Create a dashboard", description="Show recent requests."),
        "Which Appian record type stores requests?",
    ),
    (
        UserStory(title="Add a priority filter", description="Filter by the priority field."),
        "Which field is the priority field?",
    ),
    (
        UserStory(title="Approve requests", description="Approve requests when they qualify."),
        "What business rule defines qualification?",
    ),
    (
        UserStory(title="Update Request Summary", description="Modify Request Summary."),
        "Which Request Summary object should be modified?",
    ),
)


def _question_for_prompt(prompt: str) -> str | None:
    if "Show recent requests." in prompt:
        return AMBIGUOUS_CASES[0][1]
    if "Filter by the priority field." in prompt:
        return AMBIGUOUS_CASES[1][1]
    if "when they qualify." in prompt:
        return AMBIGUOUS_CASES[2][1]
    if "request-summary-1" in prompt and "request-summary-2" in prompt:
        return AMBIGUOUS_CASES[3][1]
    return None


async def _fake_structured_transport(
    messages: list[dict[str, str]],
    *,
    response_schema: type[BaseModel],
    model: str,
) -> BaseModel:
    del model
    prompt = messages[-1]["content"]
    question = _question_for_prompt(prompt)
    questions = (
        [
            ClarifyingQuestion(
                id="Q-1",
                question=question,
                priority=QuestionPriority.HIGH,
            )
        ]
        if question is not None
        else []
    )
    return response_schema(questions=questions)


@pytest.mark.parametrize(("story", "expected_question"), AMBIGUOUS_CASES)
async def test_ambiguous_requirements_pause_before_generation(
    story: UserStory,
    expected_question: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = AgentState()
    state.set_step(3)
    state.codebase_map = {
        "objects": {
            "request-summary-1": {"name": "Request Summary"},
            "request-summary-2": {"name": "Request Summary"},
        },
        "by_type": {"interface": ["request-summary-1", "request-summary-2"]},
    }
    orchestrator = Orchestrator(state)
    ask_user = AsyncMock()
    monkeypatch.setattr(
        "appian_sentinel.analyzer.story_analyzer.llm.chat_structured",
        _fake_structured_transport,
    )
    monkeypatch.setattr(orchestrator, "ask_user", ask_user)

    await orchestrator._pause_for_high_priority_questions(story)

    ask_user.assert_awaited_once_with([expected_question])
    assert state.current_step == 3
    assert state.generated_objects == []


async def test_unambiguous_requirement_does_not_pause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = AgentState()
    state.set_step(3)
    orchestrator = Orchestrator(state)
    ask_user = AsyncMock()
    monkeypatch.setattr(
        "appian_sentinel.analyzer.story_analyzer.llm.chat_structured",
        _fake_structured_transport,
    )
    monkeypatch.setattr(orchestrator, "ask_user", ask_user)
    story = UserStory(
        title="Update APP_RequestDashboard",
        description=(
            "On APP_RequestDashboard, show APP_Request.status using "
            "rule!APP_isRequestVisible. Approved means status = 2."
        ),
    )

    await orchestrator._pause_for_high_priority_questions(story)

    ask_user.assert_not_awaited()
    assert state.current_step == 3
