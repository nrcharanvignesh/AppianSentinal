"""Codebase caching for the MCP server.

MCP tool calls are stateless, so we cache each built :class:`CodebaseMap`
both in-memory (per process) and on disk (JSON under the workspace) keyed by
the export directory, so ``analyze_appian_zip`` followed by ``get_object`` /
``search_objects`` / ``generate_patch_zip`` don't re-parse thousands of files.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from appian_sentinel.config import settings
from appian_sentinel.models.codebase import CodebaseMap
from appian_sentinel.parser import codebase_map as codebase_map_mod
from appian_sentinel.parser import zip_handler

logger = logging.getLogger(__name__)

_MEM_CACHE: dict[str, CodebaseMap] = {}


def _cache_dir() -> Path:
    d = settings.sentinel_workspace.resolve() / ".mcp_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cache_file(export_dir: Path) -> Path:
    key = hashlib.sha1(str(export_dir.resolve()).encode("utf-8")).hexdigest()[:16]
    return _cache_dir() / f"codebase_{key}.json"


def get_codebase(export_dir: Path, *, rebuild: bool = False) -> CodebaseMap:
    """Return the CodebaseMap for *export_dir*, building/caching as needed."""
    export_dir = Path(export_dir).resolve()
    key = str(export_dir)

    if not rebuild and key in _MEM_CACHE:
        return _MEM_CACHE[key]

    cache_file = _cache_file(export_dir)
    if not rebuild and cache_file.exists():
        try:
            cb = CodebaseMap.from_json(cache_file.read_text(encoding="utf-8"))
            _MEM_CACHE[key] = cb
            logger.info("Loaded cached codebase map for %s", export_dir)
            return cb
        except Exception:
            logger.warning("Failed to load cached map; rebuilding", exc_info=True)

    cb = codebase_map_mod.build_codebase_map(export_dir)
    _MEM_CACHE[key] = cb
    try:
        cache_file.write_text(cb.to_json(), encoding="utf-8")
    except Exception:
        logger.warning("Failed to persist codebase cache", exc_info=True)
    return cb


def analyze_zip(zip_path: Path) -> tuple[Path, CodebaseMap]:
    """Extract a ZIP into the workspace and build (and cache) its CodebaseMap.

    Returns ``(export_dir, codebase)``.
    """
    zip_path = Path(zip_path)
    workspace = settings.sentinel_workspace.resolve()
    workspace.mkdir(parents=True, exist_ok=True)

    target = workspace / f"mcp_export_{zip_path.stem}"
    export_dir = zip_handler.extract_appian_zip(zip_path, target)
    cb = get_codebase(export_dir, rebuild=True)
    return export_dir, cb
