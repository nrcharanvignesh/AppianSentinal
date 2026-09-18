from __future__ import annotations

import asyncio
import logging
import traceback
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable

from appian_sentinel.agent.state import (
    STEP_NAMES,
    AgentState,
    AgentStatus,
    ChatMessage,
    MessageType,
)
from appian_sentinel.analyzer import llm_client, pdf_extractor
from appian_sentinel.config import settings
from appian_sentinel.generator.object_writer import write_object
from appian_sentinel.packager.patch_builder import build_patch_zip
from appian_sentinel.packager.zip_builder import build_appian_zip, validate_zip_structure
from appian_sentinel.parser import codebase_map as codebase_map_builder

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
            codebase = await asyncio.to_thread(
                codebase_map_builder.build_codebase_map, export_dir
            )
            self.state.codebase_map = (
                codebase.model_dump() if hasattr(codebase, "model_dump") else codebase
            )

            # --- Extract the user story ------------------------------------
            story = None
            if story_path:
                self.state.story_path = str(story_path)
                await self._emit_status("Extracting user story from PDF ...")
                story = await pdf_extractor.extract_user_story(story_path)
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
            req_analysis = await self.step_1_requirement_analysis(story)
            await self.step_2_codebase_analysis()
            design = await self.step_3_design(req_analysis)
            await self.step_4_implementation(design)
            await self.step_5_dependency_check()
            await self.step_6_performance_check()
            await self.step_7_code_quality_check()
            await self.step_8_test_generation(design)

            # --- Agentic fix loop ------------------------------------------
            all_passed = await self.run_fix_loop()

            if not all_passed:
                await self._emit_assistant(
                    f"Fix loop exhausted after {self.state.max_iterations} iterations. "
                    "Some tests may still be failing -- review the results.",
                    message_type=MessageType.ERROR,
                )

            # --- Package ---------------------------------------------------
            await self.step_9_final_packaging()

            self.state.set_status(AgentStatus.COMPLETE)
            await self._emit_status("Workflow complete. Download the rebuilt ZIP from the sidebar.")
            return self.state

        except asyncio.CancelledError:
            self.state.set_status(AgentStatus.ERROR)
            self.state.add_system_message("Session cancelled.")
            raise
        except Exception as exc:
            logger.exception("Orchestrator run failed")
            self.state.set_status(AgentStatus.ERROR)
            await self._emit_assistant(
                f"An error occurred: {exc}\n\n```\n{traceback.format_exc()}\n```",
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
            try:
                story = await pdf_extractor.extract_user_story_from_text(message)
                self.state.user_story = story.model_dump() if hasattr(story, "model_dump") else dict(story)
                ack = self.state.add_assistant_message(
                    "User story received and parsed. Starting the workflow ..."
                )
                yield ack
                self._user_reply_event.set()
            except Exception as exc:
                err = self.state.add_assistant_message(
                    f"Could not parse the story: {exc}",
                    message_type=MessageType.ERROR,
                )
                yield err
            return

        # --- Free-form LLM chat (idle or during workflow) -----------------
        try:
            response_text = await llm_client.llm.chat(
                [
                    {"role": m.role, "content": m.content}
                    for m in self.state.messages[-20:]
                ],
                model=settings.sentinel_fast_model,
                max_tokens=2048,
            )
            reply = self.state.add_assistant_message(response_text)
            yield reply
        except Exception as exc:
            err = self.state.add_assistant_message(
                f"LLM error: {exc}",
                message_type=MessageType.ERROR,
            )
            yield err

    # ------------------------------------------------------------------
    # Workflow steps
    # ------------------------------------------------------------------

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
        except Exception as exc:
            logger.warning("TestGenerator.generate_test_suite failed: %s", exc)

        self.state.test_suite = suite
        await self._emit_assistant(result_text)
        return suite

    async def step_9_final_packaging(self) -> Path:
        self.state.set_step(9)
        await self._emit_status("Step 9: Packaging deliverables ...")

        if self._export_dir is None:
            raise RuntimeError("No export directory available for packaging.")

        output_path = self._workspace / f"output_{self.state.session_id}.zip"

        zip_path = await asyncio.to_thread(
            build_appian_zip,
            self._export_dir,
            output_path,
            self.state.generated_objects,
        )

        valid, issues = await asyncio.to_thread(validate_zip_structure, zip_path)
        if not valid:
            await self._emit_assistant(
                "ZIP structure validation warnings:\n" + "\n".join(f"- {i}" for i in issues),
                message_type=MessageType.ERROR,
            )

        self.state.output_zip_path = str(zip_path)

        # --- Patch package: only the objects this story touched --------------
        if self.state.generated_objects:
            patch_path = self._workspace / f"patch_{self.state.session_id}.zip"
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
                    f"Patch package ready: `{Path(result['zip_path']).name}` — "
                    f"{len(result['included'])} object(s), {result['file_count']} file(s)."
                )
                if result["missing"]:
                    summary += f"\n⚠️ {len(result['missing'])} object(s) could not be located."
                if result["dependency_warnings"]:
                    warn_lines = "\n".join(
                        f"- `{w['source']}` references `{w['missing_ref_name']}` (not in patch)"
                        for w in result["dependency_warnings"][:15]
                    )
                    summary += (
                        f"\n⚠️ {len(result['dependency_warnings'])} dependency reference(s) "
                        f"are not included in the patch:\n{warn_lines}"
                    )
                await self._emit_assistant(summary)
            except Exception as exc:
                logger.warning("Patch build failed: %s", exc)
                await self._emit_assistant(
                    f"Full package ready, but patch build failed: {exc}",
                    message_type=MessageType.ERROR,
                )

        await self._emit_assistant(f"Output package ready: `{zip_path.name}`")
        return zip_path

    # ------------------------------------------------------------------
    # Agentic fix loop
    # ------------------------------------------------------------------

    async def run_fix_loop(self) -> bool:
        """Run tests, fix failures, repeat until green or budget exhausted.

        Returns ``True`` when all tests pass.
        """
        self.state.set_status(AgentStatus.TESTING)
        self.state.iteration = 0

        while self.state.iteration < self.state.max_iterations:
            self.state.iteration += 1
            await self._emit_status(
                f"Fix loop iteration {self.state.iteration}/{self.state.max_iterations} -- running tests ..."
            )

            # 1. Run the static SAIL validation / test suite ---------------
            try:
                code_map = {
                    obj.get("name", ""): obj.get("sail_code", "")
                    for obj in self.state.generated_objects
                    if obj.get("sail_code")
                }
                known_uuids = set(
                    (self.state.codebase_map or {}).get("uuid_to_name", {}).keys()
                )
                runner = test_runner.StaticTestRunner(
                    sail_code_map=code_map,
                    known_uuids=known_uuids,
                )
                structured = (self.state.test_suite or {}).get("structured")
                if structured and "test_cases" in structured:
                    from appian_sentinel.models.test_case import TestSuite as TSSuite
                    ts = TSSuite(**structured)
                    run_result = await runner.run_suite(ts)
                    self.state.test_results = (
                        run_result.model_dump()
                        if hasattr(run_result, "model_dump")
                        else {"passed": True, "failures": []}
                    )
                else:
                    self.state.test_results = {"passed": True, "failures": []}
            except Exception as exc:
                logger.warning("StaticTestRunner.run_suite failed: %s", exc)
                self.state.test_results = {"error": str(exc), "passed": False, "failures": []}

            # 2. Check results ---------------------------------------------
            all_passed = self.state.test_results.get("passed", False)
            failures = self.state.test_results.get("failures", [])

            if all_passed and not failures:
                await self._emit_status("All tests passed!")
                return True

            # 3. Emit current failures to the user -------------------------
            failure_summary = "\n".join(
                f"- {f.get('name', 'unknown')}: {f.get('message', '')}"
                for f in failures
            )
            await self._emit_assistant(
                f"**Iteration {self.state.iteration}** -- {len(failures)} test failure(s):\n{failure_summary}",
                message_type=MessageType.ERROR,
            )

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
            fix_text = await self._call_llm(fix_prompt)
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

        return False

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

    async def _call_llm(self, prompt: str) -> str:
        """Call the primary LLM via the shared client."""
        conversation: list[dict[str, str]] = [
            {"role": "system", "content": prompt},
        ]
        # Include recent history for context (capped to avoid token blowout).
        for m in self.state.messages[-10:]:
            conversation.append({"role": m.role, "content": m.content})

        response = await llm_client.llm.chat(
            conversation,
            model=settings.sentinel_primary_model,
            max_tokens=settings.sentinel_max_tokens,
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
        return write_object(self._export_dir, obj)

    def _summarise_codebase(self) -> str:
        """Return a compact string representation of the codebase map."""
        if self.state.codebase_map is None:
            return "(codebase not loaded)"
        cm = self.state.codebase_map
        lines = [f"Objects: {len(cm.get('objects', {}))}"]
        for obj_type, objs in cm.get("by_type", {}).items():
            lines.append(f"  {obj_type}: {len(objs)}")
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
