"""Pydantic models for the full codebase map and its serialisable summary."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, SerializeAsAny

from appian_sentinel.models.appian_objects import AppianObject, ObjectType


class AmbiguousObjectNameError(ValueError):
    """Raised when a display name maps to more than one UUID."""


class AmbiguousObjectUuidError(ValueError):
    """Raised when more than one source object has the same UUID."""


class PluginInfo(BaseModel):
    """Metadata about an Appian plugin installed in the environment."""

    id: str = ""
    name: str = ""
    version: str = ""


class CodebaseSummary(BaseModel):
    """Lightweight summary of a parsed codebase — suitable for quick inspection."""

    app_name: str = ""
    app_uuid: str = ""
    app_prefix: str = ""
    appian_version: str = ""
    export_timestamp: str = ""
    total_objects: int = 0
    counts_by_type: dict[str, int] = Field(default_factory=dict)
    plugin_count: int = 0
    plugins: list[str] = Field(default_factory=list)
    scanned_files: int = 0
    parse_failures: int = 0
    uuid_collision_count: int = 0
    ambiguous_name_count: int = 0


class CodebaseMap(BaseModel):
    """Full codebase map built from an Appian application export.

    This is the central data structure that downstream analysers, generators,
    and agents operate on.  It holds every parsed design object plus the
    dependency graph.

    Serialisation
    ~~~~~~~~~~~~~
    ``CodebaseMap`` is a Pydantic v2 model so it can be round-tripped through
    JSON via ``model_dump_json()`` / ``model_validate_json()``.  For very
    large exports the JSON can be written to disk as a cache so subsequent
    runs skip the XML parsing step.
    """

    # --- Application metadata ------------------------------------------------
    app_name: str = ""
    app_uuid: str = ""
    app_prefix: str = ""
    appian_version: str = ""
    export_timestamp: str = ""

    # --- Plugins -------------------------------------------------------------
    plugins: list[PluginInfo] = Field(default_factory=list)

    # --- Objects (keyed by UUID) --------------------------------------------
    # SerializeAsAny is load-bearing: Pydantic v2 serialises by the declared
    # type, so without it every subclass field (an expression rule's
    # definition, an interface's definition, a constant's value) is silently
    # dropped and the API hands the UI an object with no source at all.
    objects: dict[str, SerializeAsAny[AppianObject]] = Field(default_factory=dict)
    uuid_collisions: dict[str, list[SerializeAsAny[AppianObject]]] = Field(
        default_factory=dict,
    )

    # --- Lookup indices ------------------------------------------------------
    uuid_to_name: dict[str, str] = Field(default_factory=dict)
    name_to_uuid: dict[str, str] = Field(default_factory=dict)
    name_to_uuids: dict[str, list[str]] = Field(default_factory=dict)
    scanned_files: int = 0
    parse_failures: list[str] = Field(default_factory=list)

    # --- Dependency graph ----------------------------------------------------
    #  object UUID -> set of UUIDs it references
    dependencies: dict[str, set[str]] = Field(default_factory=dict)
    #  object UUID -> set of UUIDs that reference it
    reverse_dependencies: dict[str, set[str]] = Field(default_factory=dict)

    # --- Type index ----------------------------------------------------------
    by_type: dict[str, list[str]] = Field(default_factory=dict)
    """Mapping from ``ObjectType.value`` to list of UUIDs."""

    # ---- Pydantic v2 config for set serialisation ---------------------------
    model_config = {"arbitrary_types_allowed": True}

    # -----------------------------------------------------------------------
    # Convenience helpers
    # -----------------------------------------------------------------------

    def get_object(self, uuid: str) -> AppianObject | None:
        """Return a unique object by UUID, or ``None``.

        Raises ``AmbiguousObjectUuidError`` when source files reuse the UUID.
        """
        if uuid in self.uuid_collisions:
            paths = [self.objects[uuid].file_path]
            paths.extend(obj.file_path for obj in self.uuid_collisions[uuid])
            raise AmbiguousObjectUuidError(
                f"Object UUID {uuid!r} is ambiguous across source paths: {', '.join(paths)}"
            )
        return self.objects.get(uuid)

    def get_uuid_candidates(self, uuid: str) -> list[AppianObject]:
        """Return all source objects that use a UUID."""
        primary = self.objects.get(uuid)
        if primary is None:
            return []
        return [primary, *self.uuid_collisions.get(uuid, [])]

    def get_objects_by_type(self, object_type: ObjectType) -> list[AppianObject]:
        """Return all objects of a given type."""
        uuids = self.by_type.get(object_type.value, [])
        return [self.objects[u] for u in uuids if u in self.objects]

    def resolve_name(self, uuid: str) -> str:
        """Resolve a UUID to its display name, falling back to the UUID itself."""
        return self.uuid_to_name.get(uuid, uuid)

    def resolve_uuid(self, name: str) -> str | None:
        """Resolve a unique display name to its UUID.

        Raises ``AmbiguousObjectNameError`` when the name is not unique.
        """
        matches = self.name_to_uuids.get(name, [])
        if len(matches) > 1:
            raise AmbiguousObjectNameError(
                f"Object name {name!r} is ambiguous across UUIDs: {', '.join(matches)}"
            )
        return self.name_to_uuid.get(name)

    def resolve_uuids(self, name: str) -> list[str]:
        """Return every UUID associated with a display name."""
        return list(self.name_to_uuids.get(name, []))

    def get_direct_dependencies(self, uuid: str) -> set[str]:
        """Return UUIDs directly referenced by the given object."""
        return self.dependencies.get(uuid, set())

    def get_direct_dependents(self, uuid: str) -> set[str]:
        """Return UUIDs that directly reference the given object."""
        return self.reverse_dependencies.get(uuid, set())

    def summarise(self) -> CodebaseSummary:
        """Produce a lightweight summary of this codebase map."""
        counts: dict[str, int] = {}
        for type_key, uuid_list in self.by_type.items():
            counts[type_key] = len(uuid_list)
        for collision_objects in self.uuid_collisions.values():
            for obj in collision_objects:
                type_key = obj.object_type.value
                counts[type_key] = counts.get(type_key, 0) + 1
        collision_count = sum(len(items) for items in self.uuid_collisions.values())
        return CodebaseSummary(
            app_name=self.app_name,
            app_uuid=self.app_uuid,
            app_prefix=self.app_prefix,
            appian_version=self.appian_version,
            export_timestamp=self.export_timestamp,
            total_objects=len(self.objects) + collision_count,
            counts_by_type=counts,
            plugin_count=len(self.plugins),
            plugins=[p.name for p in self.plugins],
            scanned_files=self.scanned_files,
            parse_failures=len(self.parse_failures),
            uuid_collision_count=collision_count,
            ambiguous_name_count=sum(1 for values in self.name_to_uuids.values() if len(values) > 1),
        )

    # -----------------------------------------------------------------------
    # Serialisation helpers
    # -----------------------------------------------------------------------

    def to_json(self, **kwargs: Any) -> str:
        """Serialise to a JSON string (sets are converted to lists)."""
        return self.model_dump_json(indent=2, **kwargs)

    @classmethod
    def from_json(cls, json_str: str) -> CodebaseMap:
        """Deserialise from a JSON string."""
        return cls.model_validate_json(json_str)
