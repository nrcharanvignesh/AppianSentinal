"""Manage Appian-compatible UUIDs for new objects.

Appian UUID format (observed from exports):
    _a-XXXXXXXX-XXXX-8000-XXXX-XXXXXXXXXXXX_NNNNNN

The hex segments are random; the trailing ``_NNNNNN`` is a numeric
discriminator that Appian uses internally to version or sequence objects.
"""

from __future__ import annotations

import logging
import random
import re
import threading
import uuid as _uuid

logger = logging.getLogger(__name__)
_SAFE_EXPORT_ID = re.compile(r"^[A-Za-z0-9_.{}:-]+$")


class UuidManager:
    """Generate, register, and resolve Appian-style UUIDs.

    Thread-safe: all mutations are protected by a lock.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # uuid -> (name, obj_type)
        self._registry: dict[str, tuple[str, str]] = {}
        # name -> uuid  (reverse index)
        self._name_index: dict[str, str] = {}
        # monotonic counter for the trailing numeric suffix
        self._counter: int = random.randint(100_000, 999_999)

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------

    def generate_uuid(self) -> str:
        """Return a new UUID in Appian export format.

        Format: ``_a-XXXXXXXX-XXXX-8000-XXXX-XXXXXXXXXXXX_NNNNNN``
        """
        with self._lock:
            self._counter += 1
            suffix = self._counter

        hex_id = _uuid.uuid4().hex  # 32 hex chars
        seg1 = hex_id[0:8]
        seg2 = hex_id[8:12]
        # The third segment always starts with '8' in Appian exports
        seg3 = "8000"
        seg4 = hex_id[16:20]
        seg5 = hex_id[20:32]
        return f"_a-{seg1}-{seg2}-{seg3}-{seg4}-{seg5}_{suffix}"

    def generate_version_uuid(self) -> str:
        """Return a version UUID (same format, fresh discriminator)."""
        return self.generate_uuid()

    # ------------------------------------------------------------------
    # Registry
    # ------------------------------------------------------------------

    def register_uuid(self, uuid_str: str, name: str, obj_type: str) -> None:
        """Track a UUID -> (name, type) mapping.

        If *uuid_str* is already registered the entry is updated silently.
        """
        if not uuid_str or not name or not obj_type:
            raise ValueError("UUID, name, and object type are required")
        if not _SAFE_EXPORT_ID.fullmatch(uuid_str):
            raise ValueError(f"Unsafe Appian UUID: {uuid_str!r}")
        with self._lock:
            previous = self._registry.get(uuid_str)
            if previous is not None and previous != (name, obj_type):
                raise ValueError(f"UUID {uuid_str!r} is already registered")
            self._registry[uuid_str] = (name, obj_type)
            self._name_index[name] = uuid_str
        logger.debug("Registered UUID %s -> %s (%s)", uuid_str, name, obj_type)

    def get_name(self, uuid_str: str) -> str | None:
        """Resolve a UUID to its registered name, or *None*."""
        with self._lock:
            entry = self._registry.get(uuid_str)
        return entry[0] if entry else None

    def get_uuid(self, name: str) -> str | None:
        """Resolve a name to its UUID, or *None*."""
        with self._lock:
            return self._name_index.get(name)

    def get_obj_type(self, uuid_str: str) -> str | None:
        """Return the object type registered for *uuid_str*, or *None*."""
        with self._lock:
            entry = self._registry.get(uuid_str)
        return entry[1] if entry else None

    def export_filename(self, uuid_str: str, suffix: str = ".xml") -> str:
        """Return the UUID-backed filename used by Appian exports."""
        with self._lock:
            if uuid_str not in self._registry:
                raise KeyError(f"UUID {uuid_str!r} is not registered")
        if suffix not in {".xml", ".xsd"}:
            raise ValueError("Export suffix must be .xml or .xsd")
        return f"{uuid_str}{suffix}"

    @property
    def all_uuids(self) -> set[str]:
        """Return the set of all registered UUIDs (snapshot)."""
        with self._lock:
            return set(self._registry.keys())

    # ------------------------------------------------------------------
    # Bulk loading (e.g. from an existing export scan)
    # ------------------------------------------------------------------

    def load_from_map(self, mapping: dict[str, tuple[str, str]]) -> None:
        """Bulk-load ``{uuid: (name, obj_type)}`` entries."""
        with self._lock:
            for uid, (name, obj_type) in mapping.items():
                self._registry[uid] = (name, obj_type)
                self._name_index[name] = uid
        logger.info("Bulk-loaded %d UUID entries", len(mapping))
