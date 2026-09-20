from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from appian_sentinel.mcp_server import cache
from appian_sentinel.models.appian_objects import AppianObject, ObjectType
from appian_sentinel.models.object_registry import OBJECT_CAPABILITIES, ObjectCapability
from appian_sentinel.parser.codebase_map import parse_export_log
from appian_sentinel.services.export_mutations import (
    MutationError,
    create_typed_object,
    delete_typed_object,
    get_typed_object,
    update_typed_object,
)

REAL_EXPORT = Path(__file__).parents[1] / "appian_export"
EXPECTED_REAL_OBJECTS = 2624


def _copy_real_export(tmp_path: Path) -> Path:
    export_dir = tmp_path / "real_export"
    shutil.copytree(
        REAL_EXPORT,
        export_dir,
        ignore=shutil.ignore_patterns(".history"),
    )
    cache._MEM_CACHE.clear()
    codebase = cache.get_codebase(export_dir)
    assert codebase.scanned_files == EXPECTED_REAL_OBJECTS
    assert not codebase.parse_failures
    return export_dir


def _matches(actual: ObjectType, expected: ObjectType) -> bool:
    return actual is expected or (
        expected is ObjectType.DOCUMENT_FOLDER and actual is ObjectType.FOLDER
    )


def _template_for(
    objects: dict[str, AppianObject],
    capability: ObjectCapability,
) -> AppianObject | None:
    return next(
        (
            obj
            for obj in objects.values()
            if _matches(obj.object_type, capability.object_type) and obj.file_path
        ),
        None,
    )


def _record(
    results: dict[str, dict[str, str]],
    slug: str,
    operation: str,
    status: str,
    error: str = "",
) -> None:
    results[slug][operation] = status if not error else f"{status}: {error}"


def _print_results(results: dict[str, dict[str, str]]) -> None:
    print("\nREAL EXPORT TYPED CRUD RESULTS")
    print("type|create|get|update|delete")
    for capability in OBJECT_CAPABILITIES:
        row = results[capability.mcp_slug]
        print(
            f"{capability.object_type.value}|{row['create']}|{row['get']}|"
            f"{row['update']}|{row['delete']}"
        )


def _crud_name(capability: ObjectCapability, suffix: str = "") -> str:
    if capability.object_type is ObjectType.DATA_TYPE:
        return f"SentinelCrudDataType{suffix}"
    return f"Sentinel CRUD {capability.mcp_slug}{suffix}"


@pytest.mark.skipif(not REAL_EXPORT.exists(), reason="real Appian export is not available")
def test_every_typed_crud_operation_against_real_export(tmp_path: Path) -> None:
    export_dir = _copy_real_export(tmp_path)
    original_objects = dict(cache.get_codebase(export_dir).objects)
    results = {
        capability.mcp_slug: {
            "create": "NOT_APPLICABLE",
            "get": "NOT_APPLICABLE",
            "update": "NOT_APPLICABLE",
            "delete": "NOT_APPLICABLE",
        }
        for capability in OBJECT_CAPABILITIES
    }
    failures: list[str] = []

    for capability in OBJECT_CAPABILITIES:
        slug = capability.mcp_slug
        template = _template_for(original_objects, capability)
        if template is None:
            try:
                create_typed_object(
                    export_dir,
                    capability.object_type,
                    name=_crud_name(capability),
                )
            except MutationError as exc:
                if exc.reason == "template_required":
                    _record(results, slug, "create", "TEMPLATE_REQUIRED")
                else:
                    message = f"{exc.reason}: {exc.details}"
                    _record(results, slug, "create", "FAIL", message)
                    failures.append(f"{slug}.create: {message}")
            else:
                _record(results, slug, "create", "FAIL", "created without a template")
                failures.append(f"{slug}.create: created without a template")
            continue

        created_uuid = ""
        created_name = _crud_name(capability)
        updated_name = _crud_name(capability, "Updated")
        try:
            created = create_typed_object(
                export_dir,
                capability.object_type,
                name=created_name,
                template_uuid=template.uuid,
            )
            created_uuid = str(created["uuid"])
            assert parse_export_log(export_dir / "META-INF" / "export.log").get(
                created_uuid
            ) == created_name
            _record(results, slug, "create", "PASS")
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            _record(results, slug, "create", "FAIL", message)
            failures.append(f"{slug}.create: {message}")
            continue

        try:
            updated = update_typed_object(
                export_dir,
                capability.object_type,
                created_uuid,
                {"name": updated_name},
            )
            created_uuid = str(updated["uuid"])
            assert parse_export_log(export_dir / "META-INF" / "export.log").get(
                created_uuid
            ) == updated_name
            _record(results, slug, "update", "PASS")
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            _record(results, slug, "update", "FAIL", message)
            failures.append(f"{slug}.update: {message}")

        try:
            fetched = get_typed_object(
                export_dir,
                capability.object_type,
                created_uuid,
            )
            assert fetched["name"] == updated_name
            _record(results, slug, "get", "PASS")
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            _record(results, slug, "get", "FAIL", message)
            failures.append(f"{slug}.get: {message}")

        try:
            deleted = delete_typed_object(
                export_dir,
                capability.object_type,
                created_uuid,
                force=True,
            )
            assert deleted["status"] == "deleted"
            assert created_uuid not in parse_export_log(
                export_dir / "META-INF" / "export.log"
            )
            assert cache.get_codebase(export_dir).get_object(created_uuid) is None
            _record(results, slug, "delete", "PASS")
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            _record(results, slug, "delete", "FAIL", message)
            failures.append(f"{slug}.delete: {message}")

    _print_results(results)
    assert not failures, "\n".join(failures)


@pytest.mark.skipif(not REAL_EXPORT.exists(), reason="real Appian export is not available")
def test_data_type_and_process_model_round_trip_against_real_export(
    tmp_path: Path,
) -> None:
    export_dir = _copy_real_export(tmp_path)
    original_objects = dict(cache.get_codebase(export_dir).objects)

    for object_type in (ObjectType.DATA_TYPE, ObjectType.PROCESS_MODEL):
        capability = next(
            item for item in OBJECT_CAPABILITIES if item.object_type is object_type
        )
        template = _template_for(original_objects, capability)
        assert template is not None
        created_name = _crud_name(capability, "Focused")
        updated_name = _crud_name(capability, "FocusedUpdated")

        created = create_typed_object(
            export_dir,
            object_type,
            name=created_name,
            template_uuid=template.uuid,
        )
        object_uuid = str(created["uuid"])
        assert get_typed_object(export_dir, object_type, object_uuid)["name"] == created_name

        updated = update_typed_object(
            export_dir,
            object_type,
            object_uuid,
            {"name": updated_name},
        )
        object_uuid = str(updated["uuid"])
        assert get_typed_object(export_dir, object_type, object_uuid)["name"] == updated_name

        deleted = delete_typed_object(
            export_dir,
            object_type,
            object_uuid,
            force=True,
        )
        assert deleted["status"] == "deleted"
        assert cache.get_codebase(export_dir).get_object(object_uuid) is None


@pytest.mark.skipif(not REAL_EXPORT.exists(), reason="real Appian export is not available")
def test_real_export_delete_requires_force_for_reverse_dependency(
    tmp_path: Path,
) -> None:
    export_dir = _copy_real_export(tmp_path)
    codebase = cache.get_codebase(export_dir)
    target = next(
        (
            obj
            for obj in codebase.objects.values()
            if codebase.get_direct_dependents(obj.uuid)
            and any(
                _matches(obj.object_type, capability.object_type)
                for capability in OBJECT_CAPABILITIES
            )
        ),
        None,
    )
    assert target is not None
    object_type = next(
        capability.object_type
        for capability in OBJECT_CAPABILITIES
        if _matches(target.object_type, capability.object_type)
    )

    with pytest.raises(MutationError) as blocked:
        delete_typed_object(export_dir, object_type, target.uuid)
    assert blocked.value.reason == "dependency_blocked"
    assert blocked.value.details["dependents"]

    deleted = delete_typed_object(
        export_dir,
        object_type,
        target.uuid,
        force=True,
    )
    assert deleted["status"] == "deleted"
    assert deleted["forced"] is True
    assert cache.get_codebase(export_dir).get_object(target.uuid) is None
    assert target.uuid not in parse_export_log(export_dir / "META-INF" / "export.log")
