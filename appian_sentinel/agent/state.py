from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class AgentStatus(str, Enum):
    """Possible statuses for the agent loop."""

    IDLE = "idle"
    ANALYZING = "analyzing"
    DESIGNING = "designing"
    IMPLEMENTING = "implementing"
    TESTING = "testing"
    FIXING = "fixing"
    COMPLETE = "complete"
    ERROR = "error"
    WAITING_FOR_USER = "waiting_for_user"


class MessageType(str, Enum):
    """Types of chat messages exchanged between user and agent."""

    TEXT = "text"
    QUESTION = "question"
    CODE = "code"
    DIFF = "diff"
    STATUS = "status"
    ERROR = "error"
    TOOL = "tool"


STEP_NAMES: dict[int, str] = {
    1: "Requirement Analysis",
    2: "Codebase Analysis",
    3: "Design",
    4: "Implementation",
    5: "Dependency Check",
    6: "Performance Check",
    7: "Code Quality Check",
    8: "Test Case Generation",
    9: "Final Packaging",
}


class ChatMessage(BaseModel):
    """A single message in the conversation history."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    role: str  # "user", "assistant", "system"
    content: str
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    step: int | None = None
    message_type: MessageType = MessageType.TEXT
    metadata: dict[str, Any] = Field(default_factory=dict)


class PendingQuestion(BaseModel):
    """A clarifying question the agent needs answered before proceeding."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    question: str
    options: list[str] = Field(default_factory=list)
    step: int
    answered: bool = False
    answer: str | None = None


class AgentState(BaseModel):
    """Full state of one agent session, persisted across interactions."""

    session_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    status: AgentStatus = AgentStatus.IDLE
    current_step: int = 0
    step_name: str = ""
    iteration: int = 0
    max_iterations: int = 20

    # Conversation history
    messages: list[ChatMessage] = Field(default_factory=list)

    # Artefacts produced by each step
    codebase_map: dict[str, Any] | None = None
    user_story: dict[str, Any] | None = None
    requirement_analysis: dict[str, Any] | None = None
    solution_design: dict[str, Any] | None = None
    generated_objects: list[dict[str, Any]] = Field(default_factory=list)
    test_suite: dict[str, Any] | None = None
    test_results: dict[str, Any] | None = None
    validation_errors: list[dict[str, Any]] = Field(default_factory=list)

    # User interaction
    pending_questions: list[PendingQuestion] = Field(default_factory=list)

    # File tracking
    export_dir: str | None = None
    story_path: str | None = None
    created_files: list[str] = Field(default_factory=list)
    modified_files: list[str] = Field(default_factory=list)
    output_zip_path: str | None = None
    patch_zip_path: str | None = None

    # Timestamps
    started_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: str | None = None

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def add_message(
        self,
        role: str,
        content: str,
        *,
        message_type: MessageType = MessageType.TEXT,
        step: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ChatMessage:
        """Append a message to the conversation and return it."""
        msg = ChatMessage(
            role=role,
            content=content,
            message_type=message_type,
            step=step or self.current_step,
            metadata=metadata or {},
        )
        self.messages.append(msg)
        return msg

    def add_user_message(self, content: str) -> ChatMessage:
        return self.add_message("user", content)

    def add_assistant_message(
        self,
        content: str,
        *,
        message_type: MessageType = MessageType.TEXT,
        metadata: dict[str, Any] | None = None,
    ) -> ChatMessage:
        return self.add_message(
            "assistant",
            content,
            message_type=message_type,
            metadata=metadata,
        )

    def add_system_message(self, content: str) -> ChatMessage:
        return self.add_message("system", content, message_type=MessageType.STATUS)

    def set_step(self, step: int) -> None:
        """Advance to a workflow step (1-9)."""
        self.current_step = step
        self.step_name = STEP_NAMES.get(step, f"Step {step}")

    def set_status(self, status: AgentStatus) -> None:
        self.status = status
        if status == AgentStatus.COMPLETE:
            self.completed_at = datetime.now(timezone.utc).isoformat()

    def add_question(self, question: str, *, options: list[str] | None = None) -> PendingQuestion:
        """Register a clarifying question and pause execution."""
        pq = PendingQuestion(
            question=question,
            options=options or [],
            step=self.current_step,
        )
        self.pending_questions.append(pq)
        self.set_status(AgentStatus.WAITING_FOR_USER)
        return pq

    def answer_question(self, question_id: str, answer: str) -> bool:
        """Record the user's answer to a pending question. Returns True on success."""
        for pq in self.pending_questions:
            if pq.id == question_id and not pq.answered:
                pq.answered = True
                pq.answer = answer
                return True
        return False

    def has_unanswered_questions(self) -> bool:
        return any(not q.answered for q in self.pending_questions)

    def unanswered_questions(self) -> list[PendingQuestion]:
        return [q for q in self.pending_questions if not q.answered]

    def to_summary(self) -> dict[str, Any]:
        """Lightweight summary suitable for the status panel."""
        return {
            "session_id": self.session_id,
            "status": self.status.value,
            "current_step": self.current_step,
            "step_name": self.step_name,
            "iteration": self.iteration,
            "max_iterations": self.max_iterations,
            "total_messages": len(self.messages),
            "created_files": len(self.created_files),
            "modified_files": len(self.modified_files),
            "validation_errors": len(self.validation_errors),
            "has_output_zip": self.output_zip_path is not None,
            "has_patch_zip": self.patch_zip_path is not None,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }
