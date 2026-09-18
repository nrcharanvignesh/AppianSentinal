from __future__ import annotations

import logging
from typing import Any

from appian_sentinel.analyzer.llm_client import SYSTEM_PROMPT, llm
from appian_sentinel.models.user_story import (
    BreakingChange,
    CircularReference,
    CompatibilityIssue,
    ImpactReport,
    RiskLevel,
)
from appian_sentinel.security import mask_secrets

logger = logging.getLogger(__name__)


class ImpactAnalyzer:
    """Analyse the impact of proposed changes on an Appian codebase.

    Works with a *codebase_map* -- a dictionary (or similar structure) that
    describes the objects in the Appian application and their relationships.
    The expected shape is flexible, but the canonical form is::

        {
            "objects": {
                "<object_name>": {
                    "uuid": "...",
                    "type": "Expression Rule" | "Interface" | ...,
                    "depends_on": ["<other_object>", ...],
                    "depended_on_by": ["<caller_object>", ...],
                    "source": "<optional SAIL source or summary>"
                },
                ...
            }
        }

    If the map does not contain explicit dependency edges the analyser will
    still attempt best-effort analysis using the LLM.
    """

    # ------------------------------------------------------------------ #
    # Pure-graph analysis (no LLM needed)
    # ------------------------------------------------------------------ #

    @staticmethod
    def _build_forward_deps(
        codebase_map: dict[str, Any],
        changed_objects: list[str],
    ) -> dict[str, list[str]]:
        """Return {changed_object: [objects it depends on]}."""
        objects = codebase_map.get("objects", {})
        forward: dict[str, list[str]] = {}
        for name in changed_objects:
            obj = objects.get(name, {})
            forward[name] = list(obj.get("depends_on", []))
        return forward

    @staticmethod
    def _build_reverse_deps(
        codebase_map: dict[str, Any],
        changed_objects: list[str],
    ) -> dict[str, list[str]]:
        """Return {changed_object: [objects that depend on it]}."""
        objects = codebase_map.get("objects", {})
        reverse: dict[str, list[str]] = {}
        for name in changed_objects:
            obj = objects.get(name, {})
            reverse[name] = list(obj.get("depended_on_by", []))
        return reverse

    @staticmethod
    def _detect_circular_refs(
        codebase_map: dict[str, Any],
        changed_objects: list[str],
    ) -> list[CircularReference]:
        """Detect circular dependency chains involving the changed objects.

        Uses iterative DFS from each changed object to find back-edges.
        """
        objects = codebase_map.get("objects", {})
        cycles: list[list[str]] = []
        seen_cycles: set[tuple[str, ...]] = set()

        for start in changed_objects:
            # Stack entries: (current_node, path_so_far)
            stack: list[tuple[str, list[str]]] = [(start, [start])]
            visited: set[str] = set()

            while stack:
                node, path = stack.pop()
                if node in visited and node != start:
                    continue
                visited.add(node)

                deps = objects.get(node, {}).get("depends_on", [])
                for dep in deps:
                    if dep == start and len(path) > 1:
                        cycle = path + [dep]
                        canonical = tuple(sorted(cycle[:-1]))
                        if canonical not in seen_cycles:
                            seen_cycles.add(canonical)
                            cycles.append(cycle)
                    elif dep not in visited:
                        stack.append((dep, path + [dep]))

        return [CircularReference(chain=c) for c in cycles]

    @staticmethod
    def _compute_risk_level(
        breaking_changes: list[BreakingChange],
        circular_refs: list[CircularReference],
        reverse_deps: dict[str, list[str]],
    ) -> RiskLevel:
        """Heuristic risk score based on the analysis outputs."""
        total_reverse = sum(len(v) for v in reverse_deps.values())

        if any(bc.severity == RiskLevel.CRITICAL for bc in breaking_changes):
            return RiskLevel.CRITICAL
        if len(breaking_changes) > 3 or circular_refs:
            return RiskLevel.HIGH
        if breaking_changes or total_reverse > 10:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW

    # ------------------------------------------------------------------ #
    # LLM-assisted side-effect analysis
    # ------------------------------------------------------------------ #

    async def _detect_breaking_changes_with_llm(
        self,
        codebase_map: dict[str, Any],
        changed_objects: list[str],
        reverse_deps: dict[str, list[str]],
    ) -> list[BreakingChange]:
        """Use the LLM to reason about breaking changes and side-effects.

        When the codebase_map contains source code, the LLM can inspect
        signatures and usage patterns to identify riskier changes.
        """
        objects = codebase_map.get("objects", {})

        # Build a compact context string for the LLM.
        context_parts: list[str] = []
        for name in changed_objects:
            obj = objects.get(name, {})
            callers = reverse_deps.get(name, [])
            part = f"Object: {name} (type: {obj.get('type', 'unknown')})"
            if callers:
                part += f"\n  Callers: {', '.join(callers)}"
            source = obj.get("source", "")
            if source:
                # Truncate very long sources so we don't blow up context.
                if len(source) > 2000:
                    source = source[:2000] + "\n... (truncated)"
                part += f"\n  Source:\n{source}"
            context_parts.append(part)

        if not context_parts:
            return []

        prompt = (
            "You are performing **Step 5 -- Dependency Check** of the Appian Sentinel workflow.\n\n"
            "The following Appian objects are being changed.  For each one the callers "
            "(reverse dependencies) are listed.  Analyse whether any change could break "
            "existing callers.\n\n"
            + "\n\n".join(context_parts)
            + "\n\nFor each potential breaking change, provide:\n"
            "- object_name: the name of the changed object\n"
            "- description: what specifically might break\n"
            "- affected_callers: list of caller names that are at risk\n"
            "- severity: low / medium / high / critical\n"
        )

        from pydantic import BaseModel, Field

        class _BreakingChangeList(BaseModel):
            breaking_changes: list[BreakingChange] = Field(default_factory=list)

        messages: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

        try:
            result = await llm.chat_structured(
                messages,
                response_schema=_BreakingChangeList,
                model=llm.fast_model,
            )
            return result.breaking_changes
        except Exception as exc:
            logger.error(
                "LLM breaking-change analysis failed; falling back to heuristic: %s",
                mask_secrets(str(exc)),
            )
            return self._heuristic_breaking_changes(reverse_deps)

    @staticmethod
    def _heuristic_breaking_changes(
        reverse_deps: dict[str, list[str]],
    ) -> list[BreakingChange]:
        """Simple heuristic: any changed object with >0 callers is a potential break."""
        changes: list[BreakingChange] = []
        for obj_name, callers in reverse_deps.items():
            if callers:
                changes.append(
                    BreakingChange(
                        object_name=obj_name,
                        description=(
                            f"This object has {len(callers)} caller(s) that may be affected by changes."
                        ),
                        affected_callers=callers,
                        severity=RiskLevel.MEDIUM if len(callers) <= 3 else RiskLevel.HIGH,
                    )
                )
        return changes

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    async def analyze_impact(
        self,
        codebase_map: dict[str, Any],
        changed_objects: list[str],
    ) -> ImpactReport:
        """Full impact analysis for a list of changed objects.

        Parameters
        ----------
        codebase_map:
            Dictionary describing the Appian application objects and their
            dependency edges.  See class docstring for the expected shape.
        changed_objects:
            Names of objects that are being created or modified.

        Returns
        -------
        ImpactReport
        """
        logger.info("Starting impact analysis for %d objects: %s", len(changed_objects), changed_objects)

        forward_deps = self._build_forward_deps(codebase_map, changed_objects)
        reverse_deps = self._build_reverse_deps(codebase_map, changed_objects)
        circular_refs = self._detect_circular_refs(codebase_map, changed_objects)

        # Use LLM for deeper breaking-change analysis when source is available.
        has_source = any(
            codebase_map.get("objects", {}).get(n, {}).get("source")
            for n in changed_objects
        )
        if has_source:
            breaking_changes = await self._detect_breaking_changes_with_llm(
                codebase_map, changed_objects, reverse_deps,
            )
        else:
            breaking_changes = self._heuristic_breaking_changes(reverse_deps)

        risk_level = self._compute_risk_level(breaking_changes, circular_refs, reverse_deps)

        report = ImpactReport(
            changed_objects=changed_objects,
            forward_deps=forward_deps,
            reverse_deps=reverse_deps,
            breaking_changes=breaking_changes,
            circular_refs=circular_refs,
            risk_level=risk_level,
        )

        logger.info(
            "Impact analysis complete: risk=%s, %d breaking changes, %d circular refs.",
            risk_level.value,
            len(breaking_changes),
            len(circular_refs),
        )
        return report

    async def check_compatibility(
        self,
        codebase_map: dict[str, Any],
        new_object_def: str,
        existing_callers: list[str],
    ) -> list[CompatibilityIssue]:
        """Check whether a new or modified object definition is compatible with its callers.

        Parameters
        ----------
        codebase_map:
            The codebase map (same structure as :meth:`analyze_impact`).
        new_object_def:
            SAIL source code or description of the new/modified object.
        existing_callers:
            Names of objects that currently invoke the object being changed.

        Returns
        -------
        list[CompatibilityIssue]
        """
        objects = codebase_map.get("objects", {})

        caller_summaries: list[str] = []
        for caller_name in existing_callers:
            caller = objects.get(caller_name, {})
            source = caller.get("source", "")
            if source:
                if len(source) > 1500:
                    source = source[:1500] + "\n... (truncated)"
                caller_summaries.append(f"### {caller_name}\n```\n{source}\n```")
            else:
                caller_summaries.append(f"### {caller_name}\n(source not available)")

        prompt = (
            "You are checking **compatibility** of a changed Appian object against its callers.\n\n"
            "## New / Modified Object Definition\n"
            f"```\n{new_object_def}\n```\n\n"
            "## Existing Callers\n"
            + "\n\n".join(caller_summaries)
            + "\n\n"
            "For each compatibility issue found, provide:\n"
            "- object_uuid: UUID of the affected caller (empty string if unknown)\n"
            "- issue_type: one of 'signature_mismatch', 'missing_input', 'type_change', "
            "'removed_output', 'semantic_change', 'other'\n"
            "- description: what the issue is\n"
            "- severity: 'info', 'warning', or 'error'\n\n"
            "If there are no issues, return an empty list.\n"
        )

        from pydantic import BaseModel, Field

        class _IssueList(BaseModel):
            issues: list[CompatibilityIssue] = Field(default_factory=list)

        messages: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

        logger.info(
            "Checking compatibility of new definition against %d callers.",
            len(existing_callers),
        )

        try:
            result = await llm.chat_structured(
                messages,
                response_schema=_IssueList,
                model=llm.fast_model,
            )
            logger.info("Compatibility check found %d issue(s).", len(result.issues))
            return result.issues
        except Exception as exc:
            logger.error(
                "LLM compatibility check failed; returning empty issue list: %s",
                mask_secrets(str(exc)),
            )
            return []
