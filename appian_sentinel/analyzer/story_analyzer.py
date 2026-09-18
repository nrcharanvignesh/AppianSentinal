from __future__ import annotations

import logging

from appian_sentinel.analyzer.llm_client import SYSTEM_PROMPT, llm
from appian_sentinel.models.user_story import (
    ClarifyingQuestion,
    RequirementAnalysis,
    SolutionDesign,
    UserStory,
)

logger = logging.getLogger(__name__)


def _story_summary(story: UserStory) -> str:
    """Build a concise text block that summarises the user story for LLM prompts."""
    parts = [f"Title: {story.title}"]
    if story.as_a:
        parts.append(f"As a: {story.as_a}")
    if story.i_want:
        parts.append(f"I want: {story.i_want}")
    if story.so_that:
        parts.append(f"So that: {story.so_that}")
    if story.description:
        parts.append(f"Description: {story.description}")
    if story.acceptance_criteria:
        ac_lines = []
        for ac in story.acceptance_criteria:
            ac_lines.append(
                f"  {ac.id}: {ac.description}"
                + (f"\n    Given: {ac.given}" if ac.given else "")
                + (f"\n    When: {ac.when}" if ac.when else "")
                + (f"\n    Then: {ac.then}" if ac.then else "")
            )
        parts.append("Acceptance Criteria:\n" + "\n".join(ac_lines))
    if story.assumptions:
        parts.append("Assumptions:\n  " + "\n  ".join(story.assumptions))
    return "\n".join(parts)


class StoryAnalyzer:
    """AI-powered analysis of user stories against an Appian codebase."""

    # ------------------------------------------------------------------ #
    # Requirement Analysis
    # ------------------------------------------------------------------ #

    async def analyze_requirements(
        self,
        story: UserStory,
        codebase_summary: str,
    ) -> RequirementAnalysis:
        """Restate the story in Appian terms and identify new/modified objects.

        Parameters
        ----------
        story:
            The parsed user story.
        codebase_summary:
            A textual summary of the existing Appian codebase (object names,
            types, relationships) so the LLM can determine what exists.

        Returns
        -------
        RequirementAnalysis
            Structured analysis including restated story, objects to
            create/modify, ambiguities, and questions.
        """
        prompt = (
            "You are performing **Step 1 -- Requirement Analysis** of the Appian Sentinel workflow.\n\n"
            "Given the user story and the existing codebase summary below, produce a structured "
            "requirement analysis.\n\n"
            "## User Story\n"
            f"{_story_summary(story)}\n\n"
            "## Existing Codebase Summary\n"
            f"{codebase_summary}\n\n"
            "Your analysis must:\n"
            "1. Restate the story in Appian-specific terms (expression rules, interfaces, record types, "
            "process models, CDTs, constants, integrations).\n"
            "2. List every NEW object that needs to be created (name, type, purpose).\n"
            "3. List every EXISTING object that needs modification (uuid if known, name, what changes).\n"
            "4. Identify ambiguities in the story.\n"
            "5. List clarifying questions that should be answered before implementation.\n"
        )

        messages: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

        logger.info("Analyzing requirements for story: %s", story.title)
        analysis = await llm.chat_structured(messages, response_schema=RequirementAnalysis)
        logger.info(
            "Requirement analysis complete: %d new, %d modified objects, %d ambiguities.",
            len(analysis.new_objects),
            len(analysis.modified_objects),
            len(analysis.ambiguities),
        )
        return analysis

    # ------------------------------------------------------------------ #
    # Solution Design
    # ------------------------------------------------------------------ #

    async def design_solution(
        self,
        story: UserStory,
        requirement_analysis: RequirementAnalysis,
        codebase_context: str,
    ) -> SolutionDesign:
        """Propose a minimal-footprint Appian design for the story.

        Parameters
        ----------
        story:
            The parsed user story.
        requirement_analysis:
            The previously-generated requirement analysis.
        codebase_context:
            Relevant codebase excerpts or a summary providing enough context
            for the LLM to reason about dependencies and reuse.

        Returns
        -------
        SolutionDesign
            Approach summary and ordered list of object changes with SAIL approach.
        """
        prompt = (
            "You are performing **Step 3 -- Design** of the Appian Sentinel workflow.\n\n"
            "Given the user story, the requirement analysis, and the codebase context below, "
            "produce a solution design.\n\n"
            "## User Story\n"
            f"{_story_summary(story)}\n\n"
            "## Requirement Analysis\n"
            f"Restated story: {requirement_analysis.restated_story}\n"
            f"New objects: {[o.model_dump() for o in requirement_analysis.new_objects]}\n"
            f"Modified objects: {[o.model_dump() for o in requirement_analysis.modified_objects]}\n"
            f"Ambiguities: {requirement_analysis.ambiguities}\n\n"
            "## Codebase Context\n"
            f"{codebase_context}\n\n"
            "Design requirements:\n"
            "1. Prefer extending/reusing existing expression rules and interfaces over duplicating logic.\n"
            "2. For each object to create or modify, describe the SAIL approach.\n"
            "3. List dependencies for each object change.\n"
            "4. Keep the design minimal-footprint.\n"
        )

        messages: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

        logger.info("Designing solution for story: %s", story.title)
        design = await llm.chat_structured(messages, response_schema=SolutionDesign)
        logger.info(
            "Solution design complete: %d object changes proposed.",
            len(design.object_changes),
        )
        return design

    # ------------------------------------------------------------------ #
    # Clarifying Questions
    # ------------------------------------------------------------------ #

    async def generate_clarifying_questions(
        self,
        story: UserStory,
        codebase_context: str,
    ) -> list[ClarifyingQuestion]:
        """Generate a prioritised list of questions the agent should ask before proceeding.

        Useful to surface ambiguities early so the user can provide answers
        before the agent commits to a design.
        """
        prompt = (
            "You are an Appian expert reviewing a user story before implementation.\n\n"
            "## User Story\n"
            f"{_story_summary(story)}\n\n"
            "## Codebase Context\n"
            f"{codebase_context}\n\n"
            "Identify clarifying questions that MUST be answered before you can "
            "confidently design and implement a solution.  For each question:\n"
            "- Assign a sequential ID (Q-1, Q-2, ...).\n"
            "- Explain the context / why it matters.\n"
            "- If you can suggest possible answers, list them as options.\n"
            "- Set priority: high (blocks implementation), medium (affects design), "
            "low (nice-to-know).\n\n"
            "Return a JSON array of question objects."
        )

        # We wrap the list in a helper model so chat_structured can parse it.
        from pydantic import BaseModel, Field

        class _QuestionList(BaseModel):
            questions: list[ClarifyingQuestion] = Field(default_factory=list)

        messages: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

        logger.info("Generating clarifying questions for story: %s", story.title)
        result = await llm.chat_structured(messages, response_schema=_QuestionList, model=llm.fast_model)
        logger.info("Generated %d clarifying questions.", len(result.questions))
        return result.questions
