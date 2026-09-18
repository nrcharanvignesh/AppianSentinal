"""Azure DevOps work-item client (PAT over REST).

Self-contained, offline-configurable path for pulling a work item's title,
description, and acceptance criteria so the Sentinel workflow can turn a real
ADO user story into a structured :class:`UserStory`.

The alternative source — an ADO **MCP** server — is driven from the desktop
app's agent side; this module is the always-available default.
"""

from __future__ import annotations

import base64
import html
import logging
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_API_VERSION = "7.1"

# Work-item field names.
_F_TITLE = "System.Title"
_F_DESCRIPTION = "System.Description"
_F_ACCEPTANCE = "Microsoft.VSTS.Common.AcceptanceCriteria"
_F_TYPE = "System.WorkItemType"
_F_STATE = "System.State"


def _org_base_url(organization: str) -> str:
    """Return the org base URL. Accepts a bare org name or a full URL."""
    org = organization.strip().rstrip("/")
    if org.startswith("http://") or org.startswith("https://"):
        return org
    return f"https://dev.azure.com/{org}"


def _auth_header(pat: str) -> dict[str, str]:
    """Basic auth with an empty username and the PAT as the password."""
    token = base64.b64encode(f":{pat}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def html_to_text(raw: str | None) -> str:
    """Best-effort HTML → plain text (ADO stores rich text as HTML)."""
    if not raw:
        return ""
    text = raw
    # Turn block/line breaks into newlines before stripping tags.
    text = re.sub(r"(?i)<\s*br\s*/?\s*>", "\n", text)
    text = re.sub(r"(?i)</\s*(p|div|li|tr|h[1-6])\s*>", "\n", text)
    text = re.sub(r"(?i)<\s*li[^>]*>", "• ", text)
    text = re.sub(r"<[^>]+>", "", text)          # drop remaining tags
    text = html.unescape(text)                    # &amp; → &, &nbsp; → space
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


async def get_work_item(
    organization: str,
    project: str,
    work_item_id: int | str,
    pat: str,
    *,
    timeout: float = 20.0,
) -> dict[str, Any]:
    """Fetch a single ADO work item and return its normalized content.

    Returns a dict with ``id``, ``title``, ``description``,
    ``acceptance_criteria``, ``work_item_type``, ``state``, ``url``, and
    ``combined_text`` (title + description + acceptance criteria, ready to feed
    ``pdf_extractor.extract_user_story_from_text``).

    Raises ``httpx.HTTPStatusError`` on a non-2xx response and
    ``ValueError`` for missing credentials.
    """
    if not pat:
        raise ValueError("An Azure DevOps Personal Access Token (PAT) is required.")
    if not organization or not project:
        raise ValueError("Both an organization and a project are required.")

    base = _org_base_url(organization)
    url = f"{base}/{project.strip()}/_apis/wit/workitems/{work_item_id}"
    params = {"api-version": _API_VERSION, "$expand": "fields"}

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(url, params=params, headers=_auth_header(pat))
        resp.raise_for_status()
        data = resp.json()

    fields: dict[str, Any] = data.get("fields", {})
    title = fields.get(_F_TITLE, "")
    description = html_to_text(fields.get(_F_DESCRIPTION, ""))
    acceptance = html_to_text(fields.get(_F_ACCEPTANCE, ""))

    combined_parts = [f"# {title}".strip()]
    if description:
        combined_parts.append(f"\n## Description\n{description}")
    if acceptance:
        combined_parts.append(f"\n## Acceptance Criteria\n{acceptance}")
    combined_text = "\n".join(p for p in combined_parts if p).strip()

    logger.info("Fetched ADO work item %s: %s", work_item_id, title)

    return {
        "id": data.get("id", work_item_id),
        "title": title,
        "description": description,
        "acceptance_criteria": acceptance,
        "work_item_type": fields.get(_F_TYPE, ""),
        "state": fields.get(_F_STATE, ""),
        "url": data.get("url", url),
        "combined_text": combined_text,
    }
