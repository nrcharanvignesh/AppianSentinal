"""AI-powered SAIL code generation and modification.

Uses the LLM client (OpenAI SDK -> LiteLLM proxy) to produce valid SAIL
code.  Every generation request includes the *SAIL Output Contract* as a
system prompt to prevent the most common LLM errors (wrong operators,
hallucinated functions, etc.).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from openai import AsyncOpenAI

from appian_sentinel.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class GeneratedSail:
    """Result of a SAIL generation or modification request."""

    code: str
    confidence: float = 0.0
    notes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# SAIL Output Contract -- embedded into every generation prompt
# ---------------------------------------------------------------------------

SAIL_OUTPUT_CONTRACT = """\
You are an Appian SAIL code generator. You MUST follow these rules exactly:

## SAIL Syntax Rules
- Equality uses `=`, not-equal uses `<>`.
- Logical operators: `and()`, `or()`, `not()` -- NEVER `&&`, `||`, `!`.
- Lists are `{1, 2, 3}` and arrays are 1-indexed.
- Use `a!localVariables(local!x: ..., <final expression>)` -- NEVER `with()`.
- NO semicolons `;` anywhere.
- Comments ONLY as `/* ... */` -- NEVER `//`.
- Text literals use double quotes `"..."` only.
- String concatenation uses `&` or `concat()`.

## Forbidden Patterns
- NEVER use `==`, `!=`, `&&`, `||`, `;`.
- NEVER invent functions. The following DO NOT EXIST in SAIL:
  `a!filter`, `a!forEachItem`, `a!reduce`, `a!if`, `a!concat`, `a!split`,
  `a!length`, `a!append`, `a!remove`, `a!contains`, `a!index`.
- Use the REAL equivalents:
  - Filtering: `where()` or `a!forEach()` with `if()`
  - Iteration: `a!forEach()`
  - Conditional: `if()` or `a!match()`
  - String concat: `&` or `concat()`
  - String split: `split()`
  - List length: `length()`
  - Append: `append()`
  - Contains: `contains()`
  - Index: `index()`

## UUID References
- Cross-object references use the format `#"<uuid>"(args)`.
- Never fabricate UUIDs; use the ones provided in context.

## Output Format
Return ONLY a JSON object with these keys:
- "code": the SAIL expression body (string)
- "confidence": a float 0.0-1.0 representing your confidence
- "notes": list of strings with design notes
- "warnings": list of strings with any caveats or risks
"""


# ---------------------------------------------------------------------------
# SailGenerator
# ---------------------------------------------------------------------------

class SailGenerator:
    """Generate and modify SAIL code via LLM with contract enforcement.

    The constructor accepts an optional ``AsyncOpenAI`` client.  When
    omitted, one is created from the global :data:`settings`.
    """

    def __init__(self, client: AsyncOpenAI | None = None) -> None:
        self._client = client or AsyncOpenAI(
            base_url=settings.litellm_base_url,
            api_key=settings.litellm_api_key or "not-needed",
        )
        self._primary_model = settings.sentinel_primary_model
        self._fast_model = settings.sentinel_fast_model

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _chat(
        self,
        system: str,
        user: str,
        *,
        model: str | None = None,
        temperature: float = 0.2,
    ) -> GeneratedSail:
        """Send a chat completion and parse the structured response."""
        model = model or self._primary_model
        logger.debug("SAIL generation request -> model=%s", model)

        response = await self._client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
            max_tokens=settings.sentinel_max_tokens,
        )

        raw = response.choices[0].message.content or ""
        return self._parse_response(raw)

    @staticmethod
    def _parse_response(raw: str) -> GeneratedSail:
        """Extract a :class:`GeneratedSail` from the LLM response text.

        The LLM is asked to return JSON, but we handle best-effort parsing
        for robustness (e.g. markdown fences, plain SAIL text).
        """
        # Strip markdown code fences if present
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            # Remove opening fence
            first_nl = cleaned.index("\n")
            cleaned = cleaned[first_nl + 1:]
            if cleaned.endswith("```"):
                cleaned = cleaned[: -3].strip()

        # Attempt JSON parse
        try:
            data = json.loads(cleaned)
            if isinstance(data, dict) and "code" in data:
                return GeneratedSail(
                    code=data["code"],
                    confidence=float(data.get("confidence", 0.5)),
                    notes=data.get("notes", []),
                    warnings=data.get("warnings", []),
                )
        except (json.JSONDecodeError, ValueError):
            pass

        # Fallback: treat entire output as SAIL code
        logger.warning("LLM response was not valid JSON; treating as raw SAIL code")
        return GeneratedSail(
            code=cleaned,
            confidence=0.3,
            notes=["Response was not in structured JSON format"],
            warnings=["Confidence is low because the output could not be parsed as JSON"],
        )

    @staticmethod
    def _format_rule_inputs(rule_inputs: list[dict[str, Any]]) -> str:
        """Format rule inputs for inclusion in the prompt."""
        if not rule_inputs:
            return "None"
        lines = []
        for ri in rule_inputs:
            type_name = ri.get("type_name", "Text")
            lines.append(f"  - ri!{ri['name']} ({type_name})")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Public generation methods
    # ------------------------------------------------------------------

    async def generate_rule(
        self,
        name: str,
        description: str,
        rule_inputs: list[dict[str, Any]],
        requirements: str,
        codebase_context: str = "",
    ) -> GeneratedSail:
        """Generate SAIL code for an expression rule."""
        user_prompt = f"""\
Generate an Appian expression rule with the following specification:

**Name:** {name}
**Description:** {description}
**Rule Inputs:**
{self._format_rule_inputs(rule_inputs)}

**Requirements:**
{requirements}

**Codebase Context (existing objects for reference):**
{codebase_context or "No additional context provided."}

Return the SAIL expression body that goes inside the <definition> element.
Remember to use a!localVariables() for any local state.
"""
        return await self._chat(SAIL_OUTPUT_CONTRACT, user_prompt)

    async def generate_interface(
        self,
        name: str,
        description: str,
        rule_inputs: list[dict[str, Any]],
        requirements: str,
        codebase_context: str = "",
    ) -> GeneratedSail:
        """Generate SAIL code for an interface (form / report)."""
        user_prompt = f"""\
Generate an Appian SAIL interface with the following specification:

**Name:** {name}
**Description:** {description}
**Rule Inputs:**
{self._format_rule_inputs(rule_inputs)}

**Requirements:**
{requirements}

**Codebase Context (existing objects for reference):**
{codebase_context or "No additional context provided."}

Return the SAIL interface body that goes inside the <definition> element.
The interface should use appropriate layout and component functions
(e.g. a!formLayout, a!columnsLayout, a!textField, a!dropdownField, etc.).
Use a!localVariables() for any local state.
"""
        return await self._chat(SAIL_OUTPUT_CONTRACT, user_prompt)

    async def modify_rule(
        self,
        existing_sail: str,
        change_description: str,
        codebase_context: str = "",
    ) -> GeneratedSail:
        """Modify an existing expression rule's SAIL code."""
        user_prompt = f"""\
Modify the following existing Appian SAIL expression rule code according
to the change description below.

**Existing SAIL Code:**
```
{existing_sail}
```

**Change Description:**
{change_description}

**Codebase Context:**
{codebase_context or "No additional context provided."}

Return the COMPLETE modified SAIL expression body (not just the diff).
Preserve existing functionality unless the change description explicitly
requires removing it.
"""
        return await self._chat(SAIL_OUTPUT_CONTRACT, user_prompt)

    async def modify_interface(
        self,
        existing_sail: str,
        change_description: str,
        codebase_context: str = "",
    ) -> GeneratedSail:
        """Modify an existing interface's SAIL code."""
        user_prompt = f"""\
Modify the following existing Appian SAIL interface code according
to the change description below.

**Existing SAIL Interface Code:**
```
{existing_sail}
```

**Change Description:**
{change_description}

**Codebase Context:**
{codebase_context or "No additional context provided."}

Return the COMPLETE modified SAIL interface body (not just the diff).
Preserve existing layout and functionality unless the change description
explicitly requires removing it.
"""
        return await self._chat(SAIL_OUTPUT_CONTRACT, user_prompt)
