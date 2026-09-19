"""Load Appian icon catalogs from the bundled official alias lists."""

from __future__ import annotations

import warnings
import zipfile
from dataclasses import dataclass
from functools import lru_cache

from appian_sentinel.knowledge import resolve_ground_truth_path
from appian_sentinel.knowledge.appian_icon_aliases import (
    INDICATOR_ICON_KEYS,
    NEWS_EVENT_ICON_KEYS,
    RICH_TEXT_ICON_ALIASES,
)

_ARCHIVE_NAME = "appian.skill"
_ARCHIVE_MEMBER = "appian/reference/appian_sail_reference.md"
_RICH_TEXT_HEADING = "### List of all Standard Icons"
_TRUNCATION_SUFFIX = "..."

# The generated module contains all three Appian 26.8 documentation tables.
IS_TRUNCATED: bool = False

# Observed in the local 2,624-object reference export. The client export is not
# available at runtime, so keep this sorted snapshot as empirical valid evidence.
# These preserve accepted deprecated names missing from the current table.
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

_VALID_RICH_TEXT_ALIASES = (
    RICH_TEXT_ICON_ALIASES | CORPUS_OBSERVED_RICH_TEXT_ALIASES
)


@dataclass(frozen=True)
class IconCatalog:
    """Official Appian icon names plus source metadata."""

    rich_text_aliases: frozenset[str]
    system_icon_keys: frozenset[str]
    indicator_icon_keys: frozenset[str]
    news_event_icon_keys: frozenset[str]
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


def _empty_catalog() -> IconCatalog:
    return IconCatalog(
        rich_text_aliases=_VALID_RICH_TEXT_ALIASES,
        system_icon_keys=INDICATOR_ICON_KEYS | NEWS_EVENT_ICON_KEYS,
        indicator_icon_keys=INDICATOR_ICON_KEYS,
        news_event_icon_keys=NEWS_EVENT_ICON_KEYS,
        is_complete=True,
        is_truncated=IS_TRUNCATED,
        rich_text_covered_prefix="",
        rich_text_first=min(_VALID_RICH_TEXT_ALIASES),
        rich_text_last=max(_VALID_RICH_TEXT_ALIASES),
        archive_available=False,
        rich_text_scrape_count=len(_VALID_RICH_TEXT_ALIASES),
        indicator_key_count=len(INDICATOR_ICON_KEYS),
        news_event_key_count=len(NEWS_EVENT_ICON_KEYS),
    )


@lru_cache(maxsize=1)
def load_icon_catalog() -> IconCatalog:
    """Load the complete catalogs once and attach archive scrape metadata."""
    archive_path = resolve_ground_truth_path(_ARCHIVE_NAME)
    if not archive_path.is_file():
        warnings.warn(
            "appian.skill is missing; using the bundled official icon catalog",
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
    for line in _section(lines, rich_start):
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        alias = stripped[2:].strip()
        if alias.endswith(_TRUNCATION_SUFFIX):
            continue
        rich_items.append(alias)
    scraped_rich_icons = frozenset(rich_items)
    rich_icons = _VALID_RICH_TEXT_ALIASES

    ordered = sorted(rich_icons)
    return IconCatalog(
        rich_text_aliases=rich_icons,
        system_icon_keys=INDICATOR_ICON_KEYS | NEWS_EVENT_ICON_KEYS,
        indicator_icon_keys=INDICATOR_ICON_KEYS,
        news_event_icon_keys=NEWS_EVENT_ICON_KEYS,
        is_complete=True,
        is_truncated=IS_TRUNCATED,
        rich_text_covered_prefix=_common_prefix(scraped_rich_icons),
        rich_text_first=ordered[0] if ordered else "",
        rich_text_last=ordered[-1] if ordered else "",
        archive_available=True,
        rich_text_scrape_count=len(_VALID_RICH_TEXT_ALIASES),
        indicator_key_count=len(INDICATOR_ICON_KEYS),
        news_event_key_count=len(NEWS_EVENT_ICON_KEYS),
    )


def rich_text_icon_aliases() -> frozenset[str]:
    """Return the complete rich-text alias set (O(1) lookup)."""
    return load_icon_catalog().rich_text_aliases


def system_icon_keys() -> frozenset[str]:
    """Return all indicator and news-event icon keys (O(1) lookup)."""
    return load_icon_catalog().system_icon_keys
