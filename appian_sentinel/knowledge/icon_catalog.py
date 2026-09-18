"""Load Appian icon catalogs from the bundled documentation archive.

The distilled reference truncates lists. These sets are a partial scrape,
not an allowlist. Positive matches confirm a name; absences do not.
# ponytail: truncated Appian 26.5 scrape; full list needs docs.appian.com
"""

from __future__ import annotations

import re
import warnings
import zipfile
from dataclasses import dataclass
from functools import lru_cache

from appian_sentinel.knowledge import resolve_ground_truth_path

_ARCHIVE_NAME = "appian.skill"
_ARCHIVE_MEMBER = "appian/reference/appian_sail_reference.md"
_RICH_TEXT_HEADING = "### List of all Standard Icons"
_SYSTEM_HEADING_INDICATOR = "### Available icons"
_SYSTEM_HEADING_NEWS = "### Available Icons"
_SYSTEM_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_TRUNCATION_SUFFIX = "..."

# Distilled markdown cuts every long list. Callers must not treat this as complete.
IS_TRUNCATED: bool = True

# Observed in the local 2,624-object reference export. The client export is not
# available at runtime, so keep this sorted snapshot as empirical valid evidence.
# Mixed-case Download is used by richTextIcon. USER-plus appears only on buttons,
# so its family is ambiguous and it is intentionally admitted to both sets.
CORPUS_OBSERVED_RICH_TEXT_ALIASES: frozenset[str] = frozenset(
    {
        "align-justify",
        "angle-double-left-bold",
        "angle-double-right-bold",
        "angle-left-bold",
        "angle-right-bold",
        "arrow-left",
        "asterisk",
        "ban",
        "book-reader",
        "briefcase",
        "building",
        "building-o",
        "calculator",
        "calendar",
        "calendar-o",
        "caret-right",
        "check",
        "check-circle",
        "check-circle-o",
        "check-square-o",
        "chevron-down",
        "chevron-left",
        "chevron-right",
        "circle",
        "clipboard-list",
        "clock-o",
        "close",
        "copy",
        "cutlery",
        "database",
        "Download",
        "download",
        "exclamation",
        "exclamation-triangle",
        "external-link",
        "file",
        "file-o",
        "file-text",
        "filter",
        "globe-alt",
        "handshake-o",
        "info-circle",
        "minus",
        "money",
        "money-wave",
        "pen",
        "pencil-square-o",
        "plane",
        "plus",
        "plus-circle",
        "question",
        "question-circle",
        "refresh",
        "refresh-alt",
        "save",
        "search",
        "stethoscope",
        "thumbs-up",
        "times",
        "times-circle",
        "trash",
        "undo-alt",
        "upload",
        "user",
        "user-circle-o",
        "user-edit",
        "user-friends",
        "user-md",
        "USER-plus",
        "users",
        "warning",
    }
)
CORPUS_OBSERVED_SYSTEM_ICON_KEYS: frozenset[str] = frozenset(
    {
        "FILE",
        "PLUS",
        "REFRESH",
        "TRASH",
        "USER-plus",
    }
)


@dataclass(frozen=True)
class IconCatalog:
    """Partial icon names extracted from the bundled Appian 26.5 reference."""

    rich_text_aliases: frozenset[str]
    system_icon_keys: frozenset[str]
    is_complete: bool
    is_truncated: bool
    rich_text_covered_prefix: str
    rich_text_first: str
    rich_text_last: str
    archive_available: bool
    rich_text_scrape_count: int
    indicator_key_count: int
    news_event_key_count: int


def _section(lines: list[str], start: int) -> list[str]:
    end = next(
        (
            index
            for index in range(start + 1, len(lines))
            if lines[index].startswith("### ")
        ),
        len(lines),
    )
    return lines[start + 1 : end]


def _common_prefix(names: frozenset[str]) -> str:
    if not names:
        return ""
    ordered = sorted(names)
    first = ordered[0]
    last = ordered[-1]
    index = 0
    limit = min(len(first), len(last))
    while index < limit and first[index] == last[index]:
        index += 1
    return first[:index] if index else first[:1]


def _keys_from_section(lines: list[str], start: int) -> frozenset[str]:
    return frozenset(
        cell
        for row in _section(lines, start)
        for cell in (part.strip() for part in row.split("|"))
        if _SYSTEM_KEY_RE.fullmatch(cell)
    )


def _empty_catalog() -> IconCatalog:
    return IconCatalog(
        rich_text_aliases=frozenset(),
        system_icon_keys=frozenset(),
        is_complete=False,
        is_truncated=IS_TRUNCATED,
        rich_text_covered_prefix="",
        rich_text_first="",
        rich_text_last="",
        archive_available=False,
        rich_text_scrape_count=0,
        indicator_key_count=0,
        news_event_key_count=0,
    )


@lru_cache(maxsize=1)
def load_icon_catalog() -> IconCatalog:
    """Parse both icon namespaces once. Empty and permissive if the archive is missing."""
    archive_path = resolve_ground_truth_path(_ARCHIVE_NAME)
    if not archive_path.is_file():
        warnings.warn(
            "appian.skill is missing; icon validation is disabled",
            RuntimeWarning,
            stacklevel=2,
        )
        return _empty_catalog()

    with zipfile.ZipFile(archive_path) as archive:
        lines = archive.read(_ARCHIVE_MEMBER).decode("utf-8").splitlines()

    rich_start = next(
        index for index, line in enumerate(lines) if line == _RICH_TEXT_HEADING
    )
    rich_items: list[str] = []
    scrape_count = 0
    rich_truncated = False
    for line in _section(lines, rich_start):
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        alias = stripped[2:].strip()
        scrape_count += 1
        if alias.endswith(_TRUNCATION_SUFFIX):
            rich_truncated = True
            continue
        rich_items.append(alias)
    scraped_rich_icons = frozenset(rich_items)
    rich_icons = scraped_rich_icons | CORPUS_OBSERVED_RICH_TEXT_ALIASES

    indicator_start = next(
        index for index, line in enumerate(lines) if line == _SYSTEM_HEADING_INDICATOR
    )
    news_start = next(
        index for index, line in enumerate(lines) if line == _SYSTEM_HEADING_NEWS
    )
    indicator_keys = _keys_from_section(lines, indicator_start)
    news_keys = _keys_from_section(lines, news_start)

    ordered = sorted(rich_icons)
    return IconCatalog(
        rich_text_aliases=rich_icons,
        system_icon_keys=(
            indicator_keys | news_keys | CORPUS_OBSERVED_SYSTEM_ICON_KEYS
        ),
        is_complete=False,
        is_truncated=IS_TRUNCATED or rich_truncated,
        rich_text_covered_prefix=_common_prefix(scraped_rich_icons),
        rich_text_first=ordered[0] if ordered else "",
        rich_text_last=ordered[-1] if ordered else "",
        archive_available=True,
        rich_text_scrape_count=scrape_count,
        indicator_key_count=len(indicator_keys),
        news_event_key_count=len(news_keys),
    )


def rich_text_icon_aliases() -> frozenset[str]:
    """Return the partial rich-text alias set (O(1) lookup)."""
    return load_icon_catalog().rich_text_aliases


def system_icon_keys() -> frozenset[str]:
    """Return the partial system icon key set (O(1) lookup)."""
    return load_icon_catalog().system_icon_keys
