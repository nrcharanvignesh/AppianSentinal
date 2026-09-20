from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

import pdfplumber

from appian_sentinel.analyzer.llm_client import SYSTEM_PROMPT, llm
from appian_sentinel.models.user_story import UserStory

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Raw text extraction
# ---------------------------------------------------------------------------


def extract_pdf_text(pdf_path: Path) -> str:
    """Extract the full text content from a PDF file.

    Uses *pdfplumber* for reliable text extraction that preserves layout
    and table structures better than most alternatives.

    Raises:
        FileNotFoundError: If *pdf_path* does not exist.
        pdfplumber.pdfminer.pdfpage.PDFTextExtractionNotAllowedError:
            If the PDF is encrypted and text extraction is disallowed.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    pages: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                pages.append(text)

    full_text = "\n\n".join(pages)
    logger.info("Extracted %d characters from %d pages of %s", len(full_text), len(pages), pdf_path.name)
    return full_text


# ---------------------------------------------------------------------------
# AI-powered structured extraction
# ---------------------------------------------------------------------------

_EXTRACTION_PROMPT = """\
You are an expert business analyst.  Given the raw text of a user-story document,
extract the structured information listed below.  If a field is not explicitly
present in the text, infer it from context or leave it as an empty string.

Return a JSON object with exactly these fields (no extra keys):

{
  "title": "<short title>",
  "description": "<full narrative description>",
  "as_a": "<role from 'As a ...' clause>",
  "i_want": "<action from 'I want ...' clause>",
  "so_that": "<benefit from 'So that ...' clause>",
  "acceptance_criteria": [
    {
      "id": "AC-1",
      "description": "<plain-language description>",
      "given": "<precondition>",
      "when": "<action/event>",
      "then": "<expected outcome>"
    }
  ],
  "assumptions": ["<assumption 1>", "<assumption 2>"]
}

Rules:
- Acceptance criteria IDs should be sequential: AC-1, AC-2, ...
- If the document uses Given/When/Then already, use those values directly.
- If it does not, convert each acceptance criterion into Given/When/Then.
- Return ONLY valid JSON.  No markdown fences, no commentary outside the JSON.
"""


async def extract_user_story_from_text(
    raw_text: str,
    *,
    source_id: str = "chat",
    source_kind: Literal["chat", "pdf", "files", "ado"] = "chat",
) -> UserStory:
    """Extract a structured :class:`UserStory` from raw text (not a PDF)."""
    if not raw_text.strip():
        return UserStory(
            title="Untitled",
            raw_text="",
            description="(empty input)",
            source_id=source_id,
            source_kind=source_kind,
        )

    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"{_EXTRACTION_PROMPT}\n\n"
                f"--- BEGIN DOCUMENT TEXT ---\n{raw_text}\n--- END DOCUMENT TEXT ---"
            ),
        },
    ]
    story = await llm.chat_structured(messages, response_schema=UserStory, model=llm.fast_model)
    story.raw_text = raw_text
    _set_source(story, source_id, source_kind)
    return story


async def extract_user_story(pdf_path: Path) -> UserStory:
    """Extract a structured :class:`UserStory` from a PDF document.

    1. Extracts the raw text via :func:`extract_pdf_text`.
    2. Sends the text to the LLM with an extraction prompt.
    3. Parses the LLM response into a validated :class:`UserStory`.
    """
    raw_text = extract_pdf_text(pdf_path)

    if not raw_text.strip():
        logger.warning("PDF %s yielded no text; returning minimal UserStory.", pdf_path.name)
        return UserStory(
            title=pdf_path.stem,
            raw_text="",
            description="(empty document)",
            source_id=pdf_path.name,
            source_kind="pdf",
        )

    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"{_EXTRACTION_PROMPT}\n\n"
                f"--- BEGIN DOCUMENT TEXT ---\n{raw_text}\n--- END DOCUMENT TEXT ---"
            ),
        },
    ]

    logger.info("Sending PDF text (%d chars) to LLM for user-story extraction.", len(raw_text))

    # Use the fast model for extraction — it is a structured data task,
    # not a complex reasoning task.
    story = await llm.chat_structured(
        messages,
        response_schema=UserStory,
        model=llm.fast_model,
    )

    # Attach the original raw text so downstream consumers can reference it.
    story.raw_text = raw_text
    _set_source(story, pdf_path.name, "pdf")

    logger.info(
        "Extracted user story '%s' with %d acceptance criteria.",
        story.title,
        len(story.acceptance_criteria),
    )
    return story


def _set_source(
    story: UserStory,
    source_id: str,
    source_kind: Literal["chat", "pdf", "files", "ado"],
) -> None:
    """Apply source metadata to a story and all of its criteria."""
    story.source_id = source_id
    story.source_kind = source_kind
    for criterion in story.acceptance_criteria:
        criterion.source_id = source_id
        criterion.source_kind = source_kind
