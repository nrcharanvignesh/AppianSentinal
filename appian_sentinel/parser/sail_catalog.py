"""Normalized, version-aware Appian callable catalog."""

from __future__ import annotations

from dataclasses import dataclass

from appian_sentinel.knowledge.skill_loader import get_valid_callables
from appian_sentinel.parser.sail_functions import (
    ALL_VALID_IDENTIFIERS,
    HALLUCINATED_FUNCTIONS,
)

Version = tuple[int, int]


def parse_version(value: str | None) -> Version | None:
    """Parse an Appian release such as ``26.6`` or ``26.6.205.0``."""
    if value is None:
        return None
    parts = value.strip().split(".")
    if not 1 <= len(parts) <= 4 or any(not part.isdigit() for part in parts):
        raise ValueError(f"Invalid Appian version: {value!r}")
    return int(parts[0]), int(parts[1]) if len(parts) >= 2 else 0


@dataclass(frozen=True)
class CallableEvidence:
    """Catalog evidence for one normalized callable."""

    name: str
    introduced: Version | None = None
    removed: Version | None = None

    def supports(self, version: Version) -> bool:
        """Return whether this evidence supports the target version."""
        return (
            (self.introduced is None or version >= self.introduced)
            and (self.removed is None or version < self.removed)
        )


@dataclass(frozen=True)
class CallableDecision:
    """Result of a catalog lookup."""

    status: str
    normalized_name: str
    reason: str


class SailCallableCatalog:
    """Case-normalized catalog with disjoint valid and rejected entries."""

    def __init__(
        self,
        valid: dict[str, CallableEvidence],
        rejected: frozenset[str],
    ) -> None:
        self.valid = {name.casefold(): evidence for name, evidence in valid.items()}
        self.rejected = frozenset(name.casefold() for name in rejected)
        overlap = self.valid.keys() & self.rejected
        if overlap:
            raise ValueError(f"Valid and rejected callables overlap: {sorted(overlap)}")

    def classify(
        self,
        name: str,
        target_version: str | None = None,
    ) -> CallableDecision:
        """Classify a callable without treating missing evidence as invalid."""
        normalized = name.casefold()
        evidence = self.valid.get(normalized)
        if evidence is not None:
            version = parse_version(target_version)
            if version is not None and not evidence.supports(version):
                return CallableDecision(
                    "invalid",
                    normalized,
                    f"'{name}' is not available in Appian {target_version}",
                )
            return CallableDecision("valid", normalized, "Catalog match")
        if normalized in self.rejected:
            return CallableDecision(
                "invalid",
                normalized,
                f"'{name}' is a known invalid SAIL callable",
            )
        return CallableDecision(
            "unknown",
            normalized,
            f"No catalog evidence is available for '{name}'",
        )


def build_default_sail_catalog() -> SailCallableCatalog:
    """Build the default catalog from the skill, with an explicit fallback."""
    skill_valid = get_valid_callables()
    if skill_valid is None:
        valid_names = ALL_VALID_IDENTIFIERS
    else:
        # ponytail: retain the 80 local-only names to avoid false positives;
        # remove them only after an Appian runtime check proves each one invalid.
        valid_names = skill_valid | ALL_VALID_IDENTIFIERS
    valid = {
        name: CallableEvidence(name=name)
        for name in valid_names
    }
    rejected = frozenset(
        name
        for name in HALLUCINATED_FUNCTIONS
        if name.casefold() not in {valid_name.casefold() for valid_name in valid}
    )
    return SailCallableCatalog(valid, rejected)


def get_residual_valid_identifiers() -> frozenset[str]:
    """Return local valid names absent from the Appian 26.5 skill allowlist."""
    skill_valid = get_valid_callables()
    if skill_valid is None:
        return frozenset()
    return frozenset(
        name.casefold() for name in ALL_VALID_IDENTIFIERS
    ) - skill_valid


DEFAULT_SAIL_CATALOG = build_default_sail_catalog()

assert not (DEFAULT_SAIL_CATALOG.valid.keys() & DEFAULT_SAIL_CATALOG.rejected)
