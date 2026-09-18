from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable, TypeVar

from pydantic import ValidationError

from appian_sentinel.agent.progress import ProgressResult, emit_progress
from appian_sentinel.agent.state import (
    STEP_NAMES,
    AgentState,
    AgentStatus,
    ChatMessage,
    MessageType,
)
from appian_sentinel.analyzer import llm_client, pdf_extractor
from appian_sentinel.analyzer.story_analyzer import StoryAnalyzer
from appian_sentinel.config import settings
from appian_sentinel.generator.object_writer import write_object
from appian_sentinel.models.test_case import (
    CoverageReport,
    TestCaseResult,
    TestCaseStatus,
    TestExecutionScope,
    TestRunResult,
    TestSuite,
)
from appian_sentinel.models.user_story import QuestionPriority, UserStory
from appian_sentinel.packager.patch_builder import build_patch_zip
from appian_sentinel.packager.zip_builder import build_appian_zip, validate_zip_structure
from appian_sentinel.parser import codebase_map as codebase_map_builder
from appian_sentinel.security import mask_secrets
from appian_sentinel.services.workspace import WorkspaceHistoryService

# ---------------------------------------------------------------------------
# Sibling modules built by other agents -- imported by name so the
# orchestrator compiles even before those packages are populated.
# At runtime they are expected to be available.
# ---------------------------------------------------------------------------
from appian_sentinel.tester import test_generator, test_runner

logger = logging.getLogger(__name__)

# Type alias for the optional callback the web layer can register to receive
# every message the orchestrator produces in real time.
StatusCallback = Callable[[ChatMessage], Awaitable[None]]
T = TypeVar("T")

# Fallback acceptance-criteria ID scanner, used when the parsed user story
# carries no structured criteria.
_AC_ID_PATTERN = re.compile(r"\bAC[-_ ]?(\d{1,3})\b", re.IGNORECASE)


class Orchestrator:
    """Drives the 9-step Sentinel workflow with an agentic fix loop.

    The orchestrator is designed to be paired with a single ``AgentState``
    instance.  The web layer creates one orchestrator per session and keeps it
    alive across WebSocket reconnections.
    """

    def __init__(
        self,
        state: AgentState,
        *,
        on_message: StatusCallback | None = None,
    ) -> None:
        self.state = state
        self._on_message = on_message

        # Will be populated when the user uploads the Appian export ZIP.
        self._export_dir: Path | None = None
        self._workspace = settings.sentinel_workspace
        self._step_result_overrides: dict[int, ProgressResult] = {}

        # asyncio.Event that the fix-loop / step methods wait on when
        # they need clarifying answers from the user.
        self._user_reply_event = asyncio.Event()

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    async def run(
        self,
        export_dir: Path,
        story_path: Path | None = None,
    ) -> AgentState:
        """Full autonomous run: load codebase, process story, execute all steps.

        Parameters
        ----------
        export_dir:
            Path to the extracted Appian export directory.
        story_path:
            Optional path to a user-story PDF.  If ``None`` the agent waits
            for the user to paste or upload the story via chat.
        """
        self._export_dir = export_dir
        self.state.export_dir = str(export_dir)
        self.state.set_status(AgentStatus.ANALYZING)

        try:
            # --- Parse the codebase ----------------------------------------
            await self._emit_status("Loading and parsing the Appian export ...")
            await self.emit_progress(
                phase="parsing.codebase",
                current=0,
                total=1,
                detail="Codebase parsing started.",
            )
            try:
                codebase = await asyncio.to_thread(
                    codebase_map_builder.build_codebase_map, export_dir
                )
            except Exception as exc:
                await self.emit_progress(
                    phase="parsing.codebase",
                    current=1,
                    total=1,
                    detail=f"Codebase parsing failed: {exc}",
                    result="failed",
                )
                raise
            await self.emit_progress(
                phase="parsing.codebase",
                current=1,
                total=1,
                detail="Codebase parsing completed.",
                result="ok",
            )
            self.state.codebase_map = (
                codebase.model_dump() if hasattr(codebase, "model_dump") else codebase
            )

            # --- Extract the user story ------------------------------------
            story = None
            if story_path:
                self.state.story_path = str(story_path)
                await self._emit_status("Extracting user story from PDF ...")
                model = settings.sentinel_fast_model
                await self.emit_progress(
                    phase="llm.story_extract",
                    current=0,
                    total=1,
                    detail=f"Story extraction LLM call started: model {model}.",
                )
                try:
                    story = await pdf_extractor.extract_user_story(story_path)
                except Exception as exc:
                    await self.emit_progress(
                        phase="llm.story_extract",
                        current=1,
                        total=1,
                        detail=f"Story extraction LLM call failed: model {model}: {exc}",
                        result="failed",
                    )
                    raise
                await self.emit_progress(
                    phase="llm.story_extract",
                    current=1,
                    total=1,
                    detail=f"Story extraction LLM call completed: model {model}.",
                    result="ok",
                )
                self.state.user_story = story.model_dump() if hasattr(story, "model_dump") else dict(story)

            if story is None:
                # Pause and wait for the user to provide a story.
                await self._ask_user(
                    "Please provide a user story (paste text, upload a PDF, or type your requirements)."
                )
                # After resume, `state.user_story` should be populated by
                # `process_user_message`.
                if self.state.user_story is None:
                    raise RuntimeError("No user story provided after resume.")
                story = self.state.user_story

            # --- Execute the 9-step workflow --------------------------------
            req_analysis = await self._run_workflow_step(
                1, self.step_1_requirement_analysis(story)
            )
            await self._run_workflow_step(2, self.step_2_codebase_analysis())
            design = await self._run_workflow_step(
                3, self.step_3_design(req_analysis)
            )
            await self._pause_for_high_priority_questions(story)
            await self._run_workflow_step(4, self.step_4_implementation(design))
            await self._run_workflow_step(5, self.step_5_dependency_check())
            await self._run_workflow_step(6, self.step_6_performance_check())
            await self._run_workflow_step(7, self.step_7_code_quality_check())
            await self._run_workflow_step(8, self.step_8_test_generation(design))

            # --- Agentic fix loop ------------------------------------------
            all_passed = await self.run_fix_loop()

            if not all_passed:
                await self._emit_assistant(
                    f"Fix loop exhausted after {self.state.max_iterations} iterations. "
                    "Some tests may still be failing -- review the results.",
                    message_type=MessageType.ERROR,
                )

            # --- Package ---------------------------------------------------
            await self._run_workflow_step(9, self.step_9_final_packaging())

            self.state.set_status(AgentStatus.COMPLETE)
            await self._emit_status("Workflow complete. Download the rebuilt ZIP from the sidebar.")
            return self.state

        except asyncio.CancelledError:
            self.state.set_status(AgentStatus.ERROR)
            self.state.add_system_message("Session cancelled.")
            raise
        except Exception as exc:
            safe_error = mask_secrets(str(exc))
            logger.error("Orchestrator run failed: %s", safe_error)
            self.state.set_status(AgentStatus.ERROR)
            await self._emit_assistant(
                f"An error occurred: {safe_error}",
                message_type=MessageType.ERROR,
            )
            return self.state

    async def process_user_message(self, message: str) -> AsyncIterator[ChatMessage]:
        """Handle an incoming user message and yield response messages.

        This is the primary interface for the WebSocket handler.  It covers:
        * Providing a user story when the agent is waiting for one.
        * Answering clarifying questions.
        * Free-form chat while idle.
        """
        user_msg = self.state.add_user_message(message)
        yield user_msg

        # --- Answer pending questions ------------------------------------
        if self.state.has_unanswered_questions():
            questions = self.state.unanswered_questions()
            for q in questions:
                self.state.answer_question(q.id, message)
            self.state.set_status(AgentStatus.ANALYZING)
            self._user_reply_event.set()
            ack = self.state.add_assistant_message("Got it -- resuming the workflow.")
            yield ack
            return

        # --- Accept a user story when idle --------------------------------
        if self.state.status in (AgentStatus.IDLE, AgentStatus.WAITING_FOR_USER) and self.state.user_story is None:
            await self._emit_status("Parsing your requirements ...")
            model = settings.sentinel_fast_model
            await self.emit_progress(
                phase="llm.requirements_parse",
                current=0,
                total=1,
                detail=f"Requirements parsing LLM call started: model {model}.",
            )
            try:
                story = await pdf_extractor.extract_user_story_from_text(message)
                self.state.user_story = story.model_dump() if hasattr(story, "model_dump") else dict(story)
                await self.emit_progress(
                    phase="llm.requirements_parse",
                    current=1,
                    total=1,
                    detail=f"Requirements parsing LLM call completed: model {model}.",
                    result="ok",
                )
                ack = self.state.add_assistant_message(
                    "User story received and parsed. Starting the workflow ..."
                )
                yield ack
                self._user_reply_event.set()
            except Exception as exc:
                await self.emit_progress(
                    phase="llm.requirements_parse",
                    current=1,
                    total=1,
                    detail=f"Requirements parsing LLM call failed: model {model}: {exc}",
                    result="failed",
                )
                err = self.state.add_assistant_message(
                    f"Could not parse the story: {exc}",
                    message_type=MessageType.ERROR,
                )
                yield err
            return

        # --- Free-form LLM chat (idle or during workflow) -----------------
        model = settings.sentinel_fast_model
        await self.emit_progress(
            phase="llm.chat",
            current=0,
            total=1,
            detail=f"LLM call started: model {model}.",
        )
        try:
            response_text = await llm_client.llm.chat(
                [
                    {"role": m.role, "content": m.content}
                    for m in self.state.messages[-20:]
                ],
                model=model,
                max_tokens=2048,
            )
            await self.emit_progress(
                phase="llm.chat",
                current=1,
                total=1,
                detail=f"LLM call completed: model {model}.",
                result="ok",
            )
            reply = self.state.add_assistant_message(response_text)
            yield reply
        except Exception as exc:
            await self.emit_progress(
                phase="llm.chat",
                current=1,
                total=1,
                detail=f"LLM call failed: model {model}: {exc}",
                result="failed",
            )
            err = self.state.add_assistant_message(
                f"LLM error: {exc}",
                message_type=MessageType.ERROR,
            )
            yield err

    # ------------------------------------------------------------------
    # Workflow steps
    # ------------------------------------------------------------------

    async def _run_workflow_step(
        self,
        step: int,
        operation: Awaitable[T],
    ) -> T:
        """Run one workflow step with structured start and terminal events."""
        self.state.set_step(step)
        phase = f"workflow.step_{step}"
        name = STEP_NAMES[step]
        await self.emit_progress(
            phase=phase,
            current=step,
            total=9,
            detail=f"Step {step}/9 started: {name}.",
        )
        try:
            value = await operation
        except asyncio.CancelledError:
            await self.emit_progress(
                phase=phase,
                current=step,
                total=9,
                detail=f"Step {step}/9 blocked: {name}: session cancelled.",
                result="blocked",
            )
            raise
        except Exception as exc:
            await self.emit_progress(
                phase=phase,
                current=step,
                total=9,
                detail=f"Step {step}/9 failed: {name}: {exc}",
                result="failed",
            )
            raise

        result = self._step_result_overrides.pop(step, "ok")
        await self.emit_progress(
            phase=phase,
            current=step,
            total=9,
            detail=f"Step {step}/9 ended: {name}: {result}.",
            result=result,
        )
        return value

    async def step_1_requirement_analysis(self, story: Any) -> dict[str, Any]:
        self.state.set_step(1)
        self.state.set_status(AgentStatus.ANALYZING)
        await self._emit_status("Step 1: Analysing requirements ...")

        prompt = self._build_step_prompt(
            1,
            "You are an expert Appian analyst. "
            "Restate the user story, extract every acceptance criterion, "
            "and list the Appian objects that need to be created or modified.",
            story=story,
        )

        result_text = await self._call_llm(prompt)
        analysis = {"raw": result_text, "story": story}
        self.state.requirement_analysis = analysis

        await self._emit_assistant(result_text)
        return analysis

    async def step_2_codebase_analysis(self) -> dict[str, Any]:
        self.state.set_step(2)
        self.state.set_status(AgentStatus.ANALYZING)
        await self._emit_status("Step 2: Analysing codebase ...")

        codebase_summary = self._summarise_codebase()

        prompt = self._build_step_prompt(
            2,
            "You are an expert Appian developer reviewing an existing codebase. "
            "Map the touched objects, build a dependency tree, and identify "
            "any issues or risks.",
            codebase=codebase_summary,
            requirement_analysis=self.state.requirement_analysis,
        )

        result_text = await self._call_llm(prompt)
        analysis = {"raw": result_text, "codebase_summary": codebase_summary}

        await self._emit_assistant(result_text)
        return analysis

    async def step_3_design(self, req_analysis: dict[str, Any]) -> dict[str, Any]:
        self.state.set_step(3)
        self.state.set_status(AgentStatus.DESIGNING)
        await self._emit_status("Step 3: Designing solution ...")

        prompt = self._build_step_prompt(
            3,
            "You are an expert Appian architect. "
            "Propose a minimal-footprint design that prefers extending "
            "existing objects over duplicating. List every object to create "
            "or modify with rationale.",
            requirement_analysis=req_analysis,
            codebase=self._summarise_codebase(),
        )

        result_text = await self._call_llm(prompt)
        design = {"raw": result_text, "requirement_analysis": req_analysis}
        self.state.solution_design = design

        await self._emit_assistant(result_text)
        return design

    async def step_4_implementation(self, design: dict[str, Any]) -> list[dict[str, Any]]:
        self.state.set_step(4)
        self.state.set_status(AgentStatus.IMPLEMENTING)
        await self._emit_status("Step 4: Generating / modifying SAIL code ...")

        prompt = self._build_step_prompt(
            4,
            "You are an expert Appian SAIL developer. "
            "Generate or modify SAIL code for each object described in the design. "
            "Show before/after diffs where modifying existing objects. "
            "Return a JSON array of objects with keys: uuid, name, type, action "
            "(create|modify), sail_code.",
            design=design,
            codebase=self._summarise_codebase(),
        )

        result_text = await self._call_llm(prompt)

        # Attempt to parse structured object list from LLM output
        objects = self._parse_generated_objects(result_text)

        # Write generated / modified XML to disk
        if self._export_dir:
            for obj in objects:
                try:
                    out_path = self._write_object_xml(obj)
                    if out_path:
                        if obj.get("action") == "create":
                            self.state.created_files.append(str(out_path))
                        else:
                            self.state.modified_files.append(str(out_path))
                except Exception as exc:
                    logger.warning("Failed to write object %s: %s", obj.get("name"), exc)
                    self._step_result_overrides[4] = "failed"

        self.state.generated_objects = objects
        await self._emit_assistant(result_text, message_type=MessageType.CODE)
        return objects

    async def step_5_dependency_check(self) -> dict[str, Any]:
        self.state.set_step(5)
        await self._emit_status("Step 5: Checking dependencies ...")

        prompt = self._build_step_prompt(
            5,
            "You are an Appian dependency analyst. "
            "Report new dependencies, breaking changes, and compatibility "
            "concerns for the objects generated so far.",
            generated_objects=self.state.generated_objects,
            codebase=self._summarise_codebase(),
        )

        result_text = await self._call_llm(prompt)
        result = {"raw": result_text}
        await self._emit_assistant(result_text)
        return result

    async def step_6_performance_check(self) -> dict[str, Any]:
        self.state.set_step(6)
        await self._emit_status("Step 6: Performance review ...")

        prompt = self._build_step_prompt(
            6,
            "You are an Appian performance engineer. "
            "Evaluate queries for N+1 patterns, interface load cost, "
            "and expensive operations.",
            generated_objects=self.state.generated_objects,
        )

        result_text = await self._call_llm(prompt)
        result = {"raw": result_text}
        await self._emit_assistant(result_text)
        return result

    async def step_7_code_quality_check(self) -> dict[str, Any]:
        self.state.set_step(7)
        await self._emit_status("Step 7: Code quality review ...")

        prompt = self._build_step_prompt(
            7,
            "You are an Appian code-quality reviewer. "
            "Check for typed inputs, hard-coded values, correct use of "
            "a!localVariables, dead code, and naming conventions.",
            generated_objects=self.state.generated_objects,
        )

        result_text = await self._call_llm(prompt)
        result = {"raw": result_text}
        await self._emit_assistant(result_text)
        return result

    async def step_8_test_generation(self, design: dict[str, Any]) -> dict[str, Any]:
        self.state.set_step(8)
        self.state.set_status(AgentStatus.TESTING)
        await self._emit_status("Step 8: Generating test cases ...")

        prompt = self._build_step_prompt(
            8,
            "You are an Appian QA engineer. "
            "Generate functional, negative, edge-case, and non-functional "
            "test cases for the implemented objects. Return structured JSON.",
            design=design,
            generated_objects=self.state.generated_objects,
        )

        result_text = await self._call_llm(prompt)
        suite = {"raw": result_text}

        # Use the tester module to build a formal test suite
        model = llm_client.llm.default_model
        await self.emit_progress(
            phase="llm.test_suite",
            current=0,
            total=1,
            detail=f"Test suite LLM call started: model {model}.",
        )
        try:
            tg = test_generator.TestGenerator()
            story_text = str(self.state.user_story) if self.state.user_story else ""
            design_text = str(self.state.solution_design) if self.state.solution_design else ""
            generated_suite = await tg.generate_test_suite(
                story_text, design_text, self._summarise_codebase(),
            )
            suite["structured"] = (
                generated_suite.model_dump()
                if hasattr(generated_suite, "model_dump")
                else dict(generated_suite)
            )
            await self.emit_progress(
                phase="llm.test_suite",
                current=1,
                total=1,
                detail=f"Test suite LLM call completed: model {model}.",
                result="ok",
            )
        except Exception as exc:
            logger.warning(
                "TestGenerator.generate_test_suite failed: %s",
                mask_secrets(str(exc)),
            )
            self._step_result_overrides[8] = "failed"
            await self.emit_progress(
                phase="llm.test_suite",
                current=1,
                total=1,
                detail=f"Test suite LLM call failed: model {model}: {exc}",
                result="failed",
            )

        self.state.test_suite = suite

        # Deterministic acceptance-criteria coverage check (no LLM involved).
        coverage = self.evaluate_coverage()
        suite["coverage"] = coverage.model_dump(mode="json")
        await self._emit_assistant(result_text)
        if coverage.is_complete:
            await self._emit_status(f"Coverage check: {coverage.summary}")
        else:
            self._step_result_overrides[8] = "failed"
            await self._emit_assistant(
                f"Coverage check failed: {coverage.summary}",
                message_type=MessageType.ERROR,
            )
        return suite

    async def step_9_final_packaging(self) -> Path:
        self.state.set_step(9)
        await self._emit_status("Step 9: Packaging deliverables ...")

        if self._export_dir is None:
            raise RuntimeError("No export directory available for packaging.")

        output_path = self._workspace / f"output_{self.state.session_id}.zip"
        await self.emit_progress(
            phase="packaging.full_zip",
            current=0,
            total=1,
            detail="Full ZIP packaging started.",
        )
        try:
            zip_path = await asyncio.to_thread(
                build_appian_zip,
                self._export_dir,
                output_path,
                self.state.generated_objects,
            )
            valid, issues = await asyncio.to_thread(validate_zip_structure, zip_path)
        except Exception as exc:
            self._step_result_overrides[9] = "failed"
            await self.emit_progress(
                phase="packaging.full_zip",
                current=1,
                total=1,
                detail=f"Full ZIP packaging failed: {exc}",
                result="failed",
            )
            raise
        if not valid:
            self._step_result_overrides[9] = "failed"
            await self._emit_assistant(
                "ZIP structure validation warnings:\n" + "\n".join(f"- {i}" for i in issues),
                message_type=MessageType.ERROR,
            )
        await self.emit_progress(
            phase="packaging.full_zip",
            current=1,
            total=1,
            detail=(
                "Full ZIP packaging completed."
                if valid
                else f"Full ZIP packaging failed validation with {len(issues)} issue(s)."
            ),
            result="ok" if valid else "failed",
        )

        self.state.output_zip_path = str(zip_path)

        # --- Patch package: only the objects this story touched --------------
        if self.state.generated_objects:
            patch_path = self._workspace / f"patch_{self.state.session_id}.zip"
            await self.emit_progress(
                phase="packaging.patch_zip",
                current=0,
                total=1,
                detail="Patch ZIP packaging started.",
            )
            try:
                result = await asyncio.to_thread(
                    build_patch_zip,
                    self._export_dir,
                    self.state.generated_objects,
                    patch_path,
                    codebase=self.state.codebase_map,
                )
                self.state.patch_zip_path = result["zip_path"]
                summary = (
                    f"Patch package ready: `{Path(result['zip_path']).name}` -- "
                    f"{len(result['included'])} object(s), {result['file_count']} file(s)."
                )
                if result["missing"]:
                    summary += f"\n[WARN] {len(result['missing'])} object(s) could not be located."
                if result["dependency_warnings"]:
                    warn_lines = "\n".join(
                        f"- `{w['source']}` references `{w['missing_ref_name']}` (not in patch)"
                        for w in result["dependency_warnings"][:15]
                    )
                    summary += (
                        f"\n[WARN] {len(result['dependency_warnings'])} dependency reference(s) "
                        f"are not included in the patch:\n{warn_lines}"
                    )
                await self._emit_assistant(summary)
                await self.emit_progress(
                    phase="packaging.patch_zip",
                    current=1,
                    total=1,
                    detail=(
                        f"Patch ZIP packaging completed: "
                        f"{result['file_count']} file(s)."
                    ),
                    result="ok",
                )
            except Exception as exc:
                self._step_result_overrides[9] = "failed"
                logger.warning("Patch build failed: %s", exc)
                await self.emit_progress(
                    phase="packaging.patch_zip",
                    current=1,
                    total=1,
                    detail=f"Patch ZIP packaging failed: {exc}",
                    result="failed",
                )
                await self._emit_assistant(
                    f"Full package ready, but patch build failed: {exc}",
                    message_type=MessageType.ERROR,
                )
        else:
            await self.emit_progress(
                phase="packaging.patch_zip",
                current=1,
                total=1,
                detail="Patch ZIP packaging deferred: no generated objects.",
                result="deferred",
            )

        await self._emit_assistant(f"Output package ready: `{zip_path.name}`")
        return zip_path

    # ------------------------------------------------------------------
    # Agentic fix loop
    # ------------------------------------------------------------------

    async def run_fix_loop(self) -> bool:
        """Run tests, fix failures, repeat until green or budget exhausted.

        Returns ``True`` only when the run proves every counted test case
        passed.  An empty suite, a skipped-only suite, and a suite whose tests
        all need a live Appian environment never return ``True``.
        """
        self.state.set_status(AgentStatus.TESTING)
        self.state.iteration = 0

        while self.state.iteration < self.state.max_iterations:
            self.state.iteration += 1
            iteration_phase = f"fix_loop.iteration_{self.state.iteration}"
            await self.emit_progress(
                phase=iteration_phase,
                current=self.state.iteration,
                total=self.state.max_iterations,
                detail=(
                    f"Fix loop iteration {self.state.iteration}/"
                    f"{self.state.max_iterations} started."
                ),
            )
            await self._emit_status(
                f"Fix loop iteration {self.state.iteration}/{self.state.max_iterations} -- running tests ..."
            )

            # 1. Run the static SAIL validation / test suite ---------------
            run_result = await self.run_tests()
            self.state.test_results = self._test_results_payload(run_result)

            # 2. Check results ---------------------------------------------
            if run_result.success:
                result: ProgressResult = (
                    "deferred" if run_result.deferred else "ok"
                )
                await self.emit_progress(
                    phase=iteration_phase,
                    current=self.state.iteration,
                    total=self.state.max_iterations,
                    detail=f"Fix loop iteration ended: {run_result.verdict_reason}.",
                    result=result,
                )
                await self._emit_status(f"All tests passed: {run_result.verdict_reason}")
                return True

            # 3. Emit current problems to the user -------------------------
            problems = run_result.failures + run_result.unverified
            if not problems:
                # Nothing the LLM can act on: empty suite, or every test needs
                # a live Appian environment.
                result = "deferred" if run_result.deferred else "blocked"
                await self.emit_progress(
                    phase=iteration_phase,
                    current=self.state.iteration,
                    total=self.state.max_iterations,
                    detail=f"Fix loop iteration ended: {run_result.verdict_reason}.",
                    result=result,
                )
                await self._emit_assistant(
                    "Tests are not green and there is nothing to fix automatically: "
                    f"{run_result.verdict_reason}.",
                    message_type=MessageType.ERROR,
                )
                return False

            problem_summary = "\n".join(
                f"- [{p.status.value}] {p.name or p.test_id}: {p.message}"
                for p in problems
            )
            deferred_note = (
                f"\n{run_result.deferred} test(s) need a live Appian environment "
                "and were not executed."
                if run_result.deferred
                else ""
            )
            await self._emit_assistant(
                f"**Iteration {self.state.iteration}** -- {len(run_result.failures)} failure(s), "
                f"{len(run_result.unverified)} unverified test(s):\n"
                f"{problem_summary}{deferred_note}",
                message_type=MessageType.ERROR,
            )
            failures = [p.model_dump(mode="json") for p in problems]

            # 4. Ask the LLM to fix ----------------------------------------
            self.state.set_status(AgentStatus.FIXING)
            await self._emit_status("Analysing failures and generating fixes ...")

            fix_prompt = self._build_step_prompt(
                4,  # re-use the implementation context
                "You are an expert Appian SAIL developer fixing test failures. "
                "Analyse the failures below and return corrected SAIL code. "
                "Return a JSON array with keys: uuid, name, type, action, sail_code.",
                failures=failures,
                generated_objects=self.state.generated_objects,
                design=self.state.solution_design,
            )
            try:
                fix_text = await self._call_llm(fix_prompt)
            except Exception as exc:
                await self.emit_progress(
                    phase=iteration_phase,
                    current=self.state.iteration,
                    total=self.state.max_iterations,
                    detail=f"Fix loop iteration failed: {exc}",
                    result="failed",
                )
                raise
            fixed_objects = self._parse_generated_objects(fix_text)

            # 5. Apply fixes -----------------------------------------------
            if self._export_dir and fixed_objects:
                for obj in fixed_objects:
                    self._write_object_xml(obj)

                # Merge into the master list
                existing_uuids = {o["uuid"] for o in self.state.generated_objects if "uuid" in o}
                for obj in fixed_objects:
                    if obj.get("uuid") in existing_uuids:
                        self.state.generated_objects = [
                            obj if o.get("uuid") == obj.get("uuid") else o
                            for o in self.state.generated_objects
                        ]
                    else:
                        self.state.generated_objects.append(obj)

            await self._emit_assistant(fix_text, message_type=MessageType.CODE)
            self.state.set_status(AgentStatus.TESTING)
            await self.emit_progress(
                phase=iteration_phase,
                current=self.state.iteration,
                total=self.state.max_iterations,
                detail="Fix loop iteration ended with unresolved test failures.",
                result="failed",
            )

        return False

    # ------------------------------------------------------------------
    # Test execution and coverage
    # ------------------------------------------------------------------

    async def run_tests(self) -> TestRunResult:
        """Execute the stored test suite with the static SAIL runner."""
        phase = f"tests.run_{max(self.state.iteration, 1)}"
        await self.emit_progress(
            phase=phase,
            current=0,
            total=1,
            detail="Static test run started.",
        )
        suite = self.build_test_suite()
        if suite is None or not suite.test_cases:
            logger.warning("No test case available; the run cannot be green.")
            run_result = TestRunResult()
            await self._emit_test_run_result(phase, run_result, "blocked")
            return run_result

        code_map = {
            obj.get("name", ""): obj.get("sail_code", "")
            for obj in self.state.generated_objects
            if obj.get("sail_code")
        }
        known_uuids = set(
            (self.state.codebase_map or {}).get("uuid_to_name", {}).keys()
        )
        try:
            runner = test_runner.StaticTestRunner(
                sail_code_map=code_map,
                known_uuids=known_uuids,
            )
            run_result = await runner.run_suite(suite)
        except Exception as exc:
            logger.exception("StaticTestRunner.run_suite failed")
            run_result = TestRunResult(
                errors=1,
                results=[TestCaseResult(
                    test_id="static-test-runner",
                    name="static test runner",
                    status=TestCaseStatus.ERROR,
                    message=f"Static test runner failed: {exc}",
                )],
            )
            await self._emit_test_run_result(phase, run_result, "failed")
            return run_result
        run_result = self._annotate_static_run(suite, run_result)
        if run_result.failed or run_result.errors or run_result.skipped:
            result: ProgressResult = "failed"
        elif run_result.deferred:
            result = "deferred"
        elif run_result.success:
            result = "ok"
        else:
            result = "blocked"
        await self._emit_test_run_result(phase, run_result, result)
        return run_result

    async def _emit_test_run_result(
        self,
        phase: str,
        run_result: TestRunResult,
        result: ProgressResult,
    ) -> None:
        """Emit terminal counts for one static test run."""
        await self.emit_progress(
            phase=phase,
            current=1,
            total=1,
            detail=(
                "Static test run ended: "
                f"{run_result.passed} passed, {run_result.failed} failed, "
                f"{run_result.errors} errored, {run_result.skipped} skipped, "
                f"{run_result.deferred} deferred."
            ),
            result=result,
        )

    def build_test_suite(self) -> TestSuite | None:
        """Rebuild the structured :class:`TestSuite` held in the session state."""
        structured = (self.state.test_suite or {}).get("structured")
        if not isinstance(structured, dict) or "test_cases" not in structured:
            return None
        try:
            return TestSuite(**structured)
        except ValidationError as exc:
            logger.warning("Stored test suite is not a valid TestSuite: %s", exc)
            return None

    def acceptance_criteria_ids(self) -> list[str]:
        """Collect the acceptance-criteria IDs for the current story.

        Prefers the structured criteria of the parsed user story and falls
        back to scanning the requirement analysis for ``AC-<n>`` tokens.
        """
        ids: list[str] = []
        seen: set[str] = set()

        def add(ac_id: str) -> None:
            key = ac_id.strip().upper()
            if key and key not in seen:
                seen.add(key)
                ids.append(ac_id.strip())

        story = self.state.user_story if isinstance(self.state.user_story, dict) else {}
        criteria = story.get("acceptance_criteria")
        if isinstance(criteria, list):
            for index, item in enumerate(criteria, start=1):
                raw = str(item.get("id", "") or "").strip() if isinstance(item, dict) else ""
                add(raw or f"AC-{index}")
        if ids:
            return ids

        analysis = self.state.requirement_analysis or {}
        text = " ".join([
            str(analysis.get("raw", "")),
            str(story.get("raw_text", "")),
            str(story.get("description", "")),
        ])
        for match in _AC_ID_PATTERN.finditer(text):
            add(f"AC-{int(match.group(1))}")
        return ids

    def evaluate_coverage(self) -> CoverageReport:
        """Validate acceptance-criteria coverage of the stored suite."""
        suite = self.build_test_suite() or TestSuite(name="(no suite)")
        return suite.validate_coverage(self.acceptance_criteria_ids())

    @staticmethod
    def _annotate_static_run(suite: TestSuite, run_result: TestRunResult) -> TestRunResult:
        """Mark scopes, defer live-Appian tests, and flag unreported cases.

        The static runner only proves structure, so its verdict on a test that
        needs a running Appian environment is not evidence of a pass.
        """
        cases = {case.id: case for case in suite.test_cases}
        for result in run_result.results:
            case = cases.get(result.test_id)
            if case is None:
                continue
            result.name = result.name or case.name
            result.execution_scope = case.execution_scope
            if case.execution_scope is TestExecutionScope.LIVE_APPIAN and result.status in (
                TestCaseStatus.PASS,
                TestCaseStatus.SKIPPED,
            ):
                result.status = TestCaseStatus.DEFERRED
                result.message = (
                    "Needs a live Appian environment; not executed by the static runner."
                )

        reported = {result.test_id for result in run_result.results}
        for case in suite.test_cases:
            if case.id not in reported:
                run_result.results.append(TestCaseResult(
                    test_id=case.id,
                    name=case.name,
                    status=TestCaseStatus.ERROR,
                    message="The test runner reported no result for this test case.",
                    execution_scope=case.execution_scope,
                ))

        run_result.recount()
        return run_result

    @staticmethod
    def _test_results_payload(run_result: TestRunResult) -> dict[str, Any]:
        """Serialise a run for ``state.test_results``.

        The web UI reads ``passed`` as a boolean verdict, so the verdict
        shadows the pass count, which stays available as ``passed_count``.
        """
        payload = run_result.model_dump(mode="json")
        payload["passed_count"] = run_result.passed
        payload["passed"] = run_result.success
        return payload

    # ------------------------------------------------------------------
    # User interaction helpers
    # ------------------------------------------------------------------

    async def ask_user(self, questions: list[str]) -> None:
        """Pause the workflow and present clarifying questions to the user."""
        for q_text in questions:
            self.state.add_question(q_text)
            await self._emit_assistant(q_text, message_type=MessageType.QUESTION)

        # Wait until the web layer (via process_user_message) sets the event.
        self._user_reply_event.clear()
        await self._user_reply_event.wait()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _ask_user(self, question: str) -> None:
        """Convenience wrapper for a single question."""
        await self.ask_user([question])

    async def _pause_for_high_priority_questions(self, story: Any) -> None:
        """Block generation until all high-priority questions are answered."""
        parsed_story = (
            story
            if isinstance(story, UserStory)
            else UserStory.model_validate(story)
        )
        model = llm_client.llm.fast_model
        await self.emit_progress(
            phase="llm.clarifying_questions",
            current=0,
            total=1,
            detail=f"Clarifying-question LLM call started: model {model}.",
        )
        try:
            questions = await StoryAnalyzer().generate_clarifying_questions(
                parsed_story,
                self._summarise_codebase(parsed_story),
            )
        except Exception as exc:
            await self.emit_progress(
                phase="llm.clarifying_questions",
                current=1,
                total=1,
                detail=f"Clarifying-question LLM call failed: model {model}: {exc}",
                result="failed",
            )
            raise
        await self.emit_progress(
            phase="llm.clarifying_questions",
            current=1,
            total=1,
            detail=f"Clarifying-question LLM call completed: model {model}.",
            result="ok",
        )
        blocking = [
            question.question
            for question in questions
            if question.priority is QuestionPriority.HIGH
        ]
        if blocking:
            await self.ask_user(blocking)

    async def _call_llm(self, prompt: str) -> str:
        """Call the primary LLM via the shared client."""
        conversation: list[dict[str, str]] = [
            {"role": "system", "content": prompt},
        ]
        # Include recent history for context (capped to avoid token blowout).
        for m in self.state.messages[-10:]:
            conversation.append({"role": m.role, "content": m.content})

        model = settings.sentinel_primary_model
        phase = (
            f"llm.fix_{self.state.iteration}"
            if self.state.status is AgentStatus.FIXING
            else f"llm.step_{self.state.current_step}"
        )
        await self.emit_progress(
            phase=phase,
            current=0,
            total=1,
            detail=f"LLM call started: model {model}.",
        )
        try:
            response = await llm_client.llm.chat(
                conversation,
                model=model,
                max_tokens=settings.sentinel_max_tokens,
            )
        except Exception as exc:
            await self.emit_progress(
                phase=phase,
                current=1,
                total=1,
                detail=f"LLM call failed: model {model}: {exc}",
                result="failed",
            )
            raise
        await self.emit_progress(
            phase=phase,
            current=1,
            total=1,
            detail=f"LLM call completed: model {model}.",
            result="ok",
        )
        return response

    def _build_step_prompt(self, step: int, instruction: str, **context: Any) -> str:
        """Assemble a rich prompt for the given step."""
        parts = [
            f"# Sentinel Workflow -- Step {step}: {STEP_NAMES.get(step, '')}",
            "",
            instruction,
            "",
        ]
        for key, value in context.items():
            parts.append(f"## {key.replace('_', ' ').title()}")
            parts.append(str(value)[:12000])  # hard cap per section
            parts.append("")
        return "\n".join(parts)

    def _write_object_xml(self, obj: dict[str, Any]) -> Path | None:
        """Write a generated/modified object to the export directory.

        Delegates to the shared :func:`object_writer.write_object` so the
        orchestrator and the MCP server share one implementation.
        """
        if not self._export_dir:
            return None
        history = WorkspaceHistoryService(self._export_dir)
        if history.head() is None:
            history.create_baseline(
                actor="system",
                requirement=self._requirement_id(),
                message="baseline",
            )
        output = write_object(self._export_dir, obj)
        if output is None:
            return None
        history.stage(output.relative_to(self._export_dir).as_posix())
        if history.staged_changes():
            history.commit(
                actor="agent",
                requirement=self._requirement_id(),
                message=f"Agent wrote object {obj.get('name', obj.get('uuid', ''))}",
            )
        return output

    def _requirement_id(self) -> str:
        """Return the story identity responsible for agent mutations."""
        story = self.state.user_story
        if isinstance(story, dict):
            return str(story.get("source_id") or story.get("title") or "")
        return str(
            getattr(story, "source_id", "")
            or getattr(story, "title", "")
        )

    def _summarise_codebase(self, requirement: Any | None = None) -> str:
        """Return a bounded, requirement-relevant codebase identity summary."""
        if self.state.codebase_map is None:
            return "(codebase not loaded)"
        cm = self.state.codebase_map
        objects = cm.get("objects", {})
        lines = [f"Objects: {len(objects)}"]
        for obj_type, objs in cm.get("by_type", {}).items():
            lines.append(f"  {obj_type}: {len(objs)}")

        story = requirement or self.state.user_story or {}
        if hasattr(story, "model_dump"):
            story = story.model_dump()
        story_text = str(story)
        terms = {
            term.lower()
            for term in re.findall(r"[A-Za-z0-9_]+", story_text)
            if len(term) >= 2
        }
        type_by_uuid = {
            str(uuid): str(obj_type)
            for obj_type, uuids in cm.get("by_type", {}).items()
            for uuid in uuids
        }
        identities: list[tuple[int, str, str, str]] = []
        names: dict[str, list[str]] = {}
        for key, raw_obj in objects.items():
            obj = raw_obj if isinstance(raw_obj, dict) else {}
            uuid = str(obj.get("uuid") or key)
            name = str(obj.get("name") or cm.get("uuid_to_name", {}).get(uuid) or "")
            obj_type = str(
                obj.get("object_type")
                or obj.get("type")
                or type_by_uuid.get(uuid)
                or "unknown"
            )
            name_terms = {
                term.lower()
                for term in re.findall(r"[A-Za-z0-9_]+", name)
                if len(term) >= 2
            }
            score = len(terms & name_terms)
            if name and name.lower() in story_text.lower():
                score += 10
            names.setdefault(name.lower(), []).append(uuid)
            if score:
                identities.append((score, name, uuid, obj_type))

        duplicate_names = {
            name: uuids
            for name, uuids in names.items()
            if name and len(uuids) > 1 and any(
                item_name.lower() == name for _, item_name, _, _ in identities
            )
        }
        identities.sort(key=lambda item: (-item[0], item[1].lower(), item[2]))
        selected: list[tuple[int, str, str, str]] = []
        identity_lines: list[str] = []
        identity_chars = 0
        for identity in identities:
            _, name, uuid, obj_type = identity
            line = f"- {name} | {uuid} | {obj_type}"
            if len(selected) >= 80 or identity_chars + len(line) > 8500:
                break
            selected.append(identity)
            identity_lines.append(line)
            identity_chars += len(line) + 1
        lines.extend(["", "Relevant object identities (name | UUID | type):"])
        lines.extend(identity_lines)
        if duplicate_names:
            lines.extend(["", "Ambiguous names with multiple matching UUIDs:"])
            for name, uuids in sorted(duplicate_names.items()):
                line = f"- {name}: {', '.join(sorted(uuids))}"
                if sum(map(len, lines)) + len(line) > 10500:
                    break
                lines.append(line)

        omitted = len(objects) - len(selected)
        lines.extend([
            "",
            (
                "TRUNCATION NOTE: This is a partial, relevance-selected object list. "
                f"{len(selected)} of {len(objects)} objects are shown; {omitted} are omitted. "
                "Do not treat this list as exhaustive."
            ),
        ])
        return "\n".join(lines)

    @staticmethod
    def _parse_generated_objects(llm_output: str) -> list[dict[str, Any]]:
        """Best-effort extraction of a JSON array from LLM output."""
        import json

        # Try to find a JSON array in the output
        text = llm_output.strip()

        # Look for ```json ... ``` fences first
        start = text.find("```json")
        if start != -1:
            start = text.index("\n", start) + 1
            end = text.find("```", start)
            if end != -1:
                text = text[start:end].strip()

        # Try direct parse
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return parsed
            if isinstance(parsed, dict):
                return [parsed]
        except json.JSONDecodeError:
            pass

        # Fallback: look for [ ... ] anywhere
        bracket_start = text.find("[")
        bracket_end = text.rfind("]")
        if bracket_start != -1 and bracket_end != -1 and bracket_end > bracket_start:
            try:
                parsed = json.loads(text[bracket_start : bracket_end + 1])
                if isinstance(parsed, list):
                    return parsed
            except json.JSONDecodeError:
                pass

        logger.warning("Could not parse generated objects from LLM output.")
        return []

    async def _emit_assistant(
        self,
        content: str,
        *,
        message_type: MessageType = MessageType.TEXT,
        metadata: dict[str, Any] | None = None,
    ) -> ChatMessage:
        msg = self.state.add_assistant_message(
            content, message_type=message_type, metadata=metadata
        )
        if self._on_message:
            await self._on_message(msg)
        return msg

    async def _emit_status(self, content: str) -> ChatMessage:
        msg = self.state.add_system_message(content)
        if self._on_message:
            await self._on_message(msg)
        return msg

    async def emit_progress(
        self,
        *,
        phase: str,
        current: int,
        total: int,
        detail: str,
        result: ProgressResult | None = None,
    ) -> ChatMessage:
        """Publish one event using the shared progress contract."""
        return await emit_progress(
            self.state,
            self._on_message,
            phase=phase,
            current=current,
            total=total,
            detail=detail,
            result=result,
        )
