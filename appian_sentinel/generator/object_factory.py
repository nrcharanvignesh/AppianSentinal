"""Factory for creating new Appian design objects.

Every ``create_*`` method returns a dict that is ready to hand to
:mod:`appian_sentinel.generator.xml_writer` for serialization.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from appian_sentinel.generator.uuid_manager import UuidManager

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Naming convention helpers
# ---------------------------------------------------------------------------

_PREFIX_PATTERN = re.compile(r"^[A-Z]+_")


def _validate_name(name: str, obj_type: str) -> list[str]:
    """Return a list of warnings about naming-convention violations."""
    warnings: list[str] = []

    if not name:
        warnings.append(f"{obj_type}: name must not be empty")
        return warnings

    # Check for application prefix (e.g. MYAPP_)
    if not _PREFIX_PATTERN.match(name):
        warnings.append(
            f"{obj_type} '{name}': missing application prefix (e.g. 'MYAPP_')"
        )

    # After the prefix, the remainder should be camelCase or PascalCase
    match = _PREFIX_PATTERN.search(name)
    if match:
        remainder = name[match.end():]
        if remainder and not remainder[0].isupper():
            warnings.append(
                f"{obj_type} '{name}': part after prefix should start "
                f"with an uppercase letter (PascalCase)"
            )

    # No spaces or special chars (underscores after prefix are fine but uncommon)
    bare = _PREFIX_PATTERN.sub("", name)
    if re.search(r"[^a-zA-Z0-9]", bare):
        warnings.append(
            f"{obj_type} '{name}': body contains non-alphanumeric characters"
        )

    return warnings


# ---------------------------------------------------------------------------
# ObjectFactory
# ---------------------------------------------------------------------------

class ObjectFactory:
    """Create fully-populated dicts for Appian design objects.

    Each ``create_*`` method generates new UUIDs via :class:`UuidManager`,
    validates naming conventions, and returns a dict ready for the
    XML writer.
    """

    def __init__(self, uuid_manager: UuidManager | None = None) -> None:
        self._uuid_mgr = uuid_manager or UuidManager()

    @property
    def uuid_manager(self) -> UuidManager:
        return self._uuid_mgr

    # ------------------------------------------------------------------
    # Expression rule
    # ------------------------------------------------------------------

    def create_expression_rule(
        self,
        name: str,
        description: str,
        definition: str,
        rule_inputs: list[dict[str, Any]] | None = None,
        parent_uuid: str = "",
    ) -> dict[str, Any]:
        """Create an expression-rule object dict.

        Parameters
        ----------
        name:
            Object name, should follow ``PREFIX_PascalCase``.
        description:
            Human-readable description.
        definition:
            SAIL expression body.
        rule_inputs:
            List of ``{name, type_name, type_namespace?}`` dicts.
        parent_uuid:
            UUID of the parent folder / application.

        Returns
        -------
        dict
            Ready for :func:`xml_writer.write_content_xml` with
            ``obj_subtype="rule"``.
        """
        warnings = _validate_name(name, "ExpressionRule")
        for w in warnings:
            logger.warning(w)

        obj_uuid = self._uuid_mgr.generate_uuid()
        ver_uuid = self._uuid_mgr.generate_version_uuid()
        self._uuid_mgr.register_uuid(obj_uuid, name, "expressionRule")

        return {
            "name": name,
            "uuid": obj_uuid,
            "versionUuid": ver_uuid,
            "description": description,
            "parentUuid": parent_uuid,
            "definition": definition,
            "rule_inputs": rule_inputs or [],
            "preferredEditor": "legacy",
            "offlineEnabled": False,
            "_naming_warnings": warnings,
            "_obj_subtype": "rule",
        }

    # ------------------------------------------------------------------
    # Interface
    # ------------------------------------------------------------------

    def create_interface(
        self,
        name: str,
        description: str,
        definition: str,
        rule_inputs: list[dict[str, Any]] | None = None,
        parent_uuid: str = "",
    ) -> dict[str, Any]:
        """Create an interface object dict.

        Same shape as :meth:`create_expression_rule` but
        ``_obj_subtype`` is ``"interface"``.
        """
        warnings = _validate_name(name, "Interface")
        for w in warnings:
            logger.warning(w)

        obj_uuid = self._uuid_mgr.generate_uuid()
        ver_uuid = self._uuid_mgr.generate_version_uuid()
        self._uuid_mgr.register_uuid(obj_uuid, name, "interface")

        return {
            "name": name,
            "uuid": obj_uuid,
            "versionUuid": ver_uuid,
            "description": description,
            "parentUuid": parent_uuid,
            "definition": definition,
            "rule_inputs": rule_inputs or [],
            "preferredEditor": "legacy",
            "offlineEnabled": False,
            "_naming_warnings": warnings,
            "_obj_subtype": "interface",
        }

    # ------------------------------------------------------------------
    # Constant
    # ------------------------------------------------------------------

    def create_constant(
        self,
        name: str,
        description: str,
        value: str,
        value_type: str = "Text",
        parent_uuid: str = "",
    ) -> dict[str, Any]:
        """Create an application constant object dict.

        The ``definition`` is set to the literal *value* so the
        XML writer can embed it in ``<definition>``.
        """
        warnings = _validate_name(name, "Constant")
        for w in warnings:
            logger.warning(w)

        obj_uuid = self._uuid_mgr.generate_uuid()
        ver_uuid = self._uuid_mgr.generate_version_uuid()
        self._uuid_mgr.register_uuid(obj_uuid, name, "constant")

        return {
            "name": name,
            "uuid": obj_uuid,
            "versionUuid": ver_uuid,
            "description": description,
            "parentUuid": parent_uuid,
            "definition": value,
            "rule_inputs": [],
            "value_type": value_type,
            "preferredEditor": "legacy",
            "offlineEnabled": False,
            "_naming_warnings": warnings,
            "_obj_subtype": "constant",
        }

    # ------------------------------------------------------------------
    # Decision
    # ------------------------------------------------------------------

    def create_decision(
        self,
        name: str,
        description: str,
        definition: str,
        parent_uuid: str = "",
    ) -> dict[str, Any]:
        """Create a decision object dict."""
        warnings = _validate_name(name, "Decision")
        for w in warnings:
            logger.warning(w)

        obj_uuid = self._uuid_mgr.generate_uuid()
        ver_uuid = self._uuid_mgr.generate_version_uuid()
        self._uuid_mgr.register_uuid(obj_uuid, name, "decision")

        return {
            "name": name,
            "uuid": obj_uuid,
            "versionUuid": ver_uuid,
            "description": description,
            "parentUuid": parent_uuid,
            "definition": definition,
            "rule_inputs": [],
            "preferredEditor": "legacy",
            "offlineEnabled": False,
            "_naming_warnings": warnings,
            "_obj_subtype": "decision",
        }
