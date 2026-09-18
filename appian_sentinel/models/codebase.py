"""Pydantic models for the full codebase map and its serialisable summary."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from appian_sentinel.models.appian_objects import AppianObject, ObjectType


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
    objects: dict[str, AppianObject] = Field(default_factory=dict)

    # --- Lookup indices ------------------------------------------------------
    uuid_to_name: dict[str, str] = Field(default_factory=dict)
    name_to_uuid: dict[str, str] = Field(default_factory=dict)

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
        """Return an object by UUID, or *None*."""
        return self.objects.get(uuid)

    def get_objects_by_type(self, object_type: ObjectType) -> list[AppianObject]:
        """Return all objects of a given type."""
        uuids = self.by_type.get(object_type.value, [])
        return [self.objects[u] for u in uuids if u in self.objects]

    def resolve_name(self, uuid: str) -> str:
        """Resolve a UUID to its display name, falling back to the UUID itself."""
        return self.uuid_to_name.get(uuid, uuid)

    def resolve_uuid(self, name: str) -> str | None:
        """Resolve a display name to its UUID."""
        return self.name_to_uuid.get(name)

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
        return CodebaseSummary(
            app_name=self.app_name,
            app_uuid=self.app_uuid,
            app_prefix=self.app_prefix,
            appian_version=self.appian_version,
            export_timestamp=self.export_timestamp,
            total_objects=len(self.objects),
            counts_by_type=counts,
            plugin_count=len(self.plugins),
            plugins=[p.name for p in self.plugins],
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
