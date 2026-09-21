"""Atomic create, update, and delete for Appian export objects."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote

from lxml import etree

from appian_sentinel.generator.object_writer import build_native_object_artifacts
from appian_sentinel.mcp_server import cache
from appian_sentinel.models.appian_objects import ObjectType
from appian_sentinel.models.object_registry import CAPABILITY_BY_TYPE, ObjectCapability
from appian_sentinel.parser.codebase_map import parse_export_log
from appian_sentinel.services.export_metadata import (
    ExportMetadataError,
    build_object_metadata_updates,
    metadata_tags,
    update_application_membership,
    update_export_log,
)
from appian_sentinel.services.mutation_transaction import MutationTransaction
from appian_sentinel.services.workspace import WorkspaceHistoryService


class MutationError(ValueError):
    def __init__(self, reason: str, **details: Any) -> None:
        self.reason = reason
        self.details = details
        super().__init__(reason)


def get_typed_object(export_dir: Path, object_type: ObjectType, object_uuid: str) -> dict[str, Any]:
    cb = cache.get_codebase(export_dir)
    obj = cb.get_object(object_uuid)
    if obj is None:
        raise MutationError("not_found", object_uuid=object_uuid)
    if not _type_matches(obj.object_type, object_type):
        raise MutationError(
            "type_mismatch",
            object_uuid=object_uuid,
            actual=obj.object_type.value,
            expected=object_type.value,
        )
    payload = obj.model_dump(mode="json")
    if object_type is ObjectType.DATA_TYPE:
        log_names = parse_export_log(export_dir / "META-INF" / "export.log")
        payload["name"] = log_names.get(object_uuid, obj.name)
    payload["direct_dependencies"] = sorted(cb.get_direct_dependencies(object_uuid))
    payload["direct_dependents"] = sorted(cb.get_direct_dependents(object_uuid))
    return payload


def create_typed_object(
    export_dir: Path,
    object_type: ObjectType,
    *,
    name: str,
    template_uuid: str = "",
    fields: dict[str, Any] | None = None,
    preview: bool = False,
) -> dict[str, Any]:
    capability = _capability(object_type)
    fields = dict(fields or {})
    if not template_uuid and capability.native_write:
        return _create_native_object(
            export_dir, object_type, name=name, fields=fields, preview=preview
        )
    template = _template_object(export_dir, object_type, template_uuid)
    if template is None:
        raise MutationError(
            "template_required",
            object_type=object_type.value,
            requirement="real_export_template",
        )
    requested_uuid = str(fields.pop("uuid", "")).strip()
    new_uuid = _new_object_uuid(object_type, template, name, requested_uuid)
    if preview:
        return {
            "status": "preview",
            "uuid": new_uuid,
            "name": name,
            "template_uuid": template.uuid,
            "action": "create",
        }
    source = _object_path(export_dir, template)
    dest = _object_destination(source, object_type, new_uuid)
    if dest.exists():
        raise MutationError("already_exists", object_uuid=new_uuid)
    writes = {
        dest: _rewrite_identity_bytes(
            source.read_bytes(),
            new_uuid,
            name,
            old_uuid=template.uuid,
            old_name=template.name,
        )
    }
    payload_src = source.with_suffix("")
    if payload_src.is_dir():
        for payload in payload_src.rglob("*"):
            if payload.is_file():
                writes[dest.with_suffix("") / payload.relative_to(payload_src)] = (
                    payload.read_bytes()
                )
    try:
        writes.update(
            build_object_metadata_updates(
                export_dir, object_type, new_uuid, name, add=True
            )
        )
    except ExportMetadataError as exc:
        raise MutationError("metadata_invalid", message=str(exc)) from exc
    changed = _apply_mutation(export_dir, writes, [], f"Create {name}")
    _commit_paths(export_dir, changed, f"Create {name}")
    cache.get_codebase(export_dir, rebuild=True)
    return {"status": "created", "uuid": new_uuid, "name": name, "file_path": str(dest), "template_uuid": template.uuid}


def update_typed_object(
    export_dir: Path,
    object_type: ObjectType,
    object_uuid: str,
    fields: dict[str, Any],
    *,
    preview: bool = False,
) -> dict[str, Any]:
    capability = _capability(object_type)
    cb = cache.get_codebase(export_dir)
    obj = cb.get_object(object_uuid)
    if obj is None:
        raise MutationError("not_found", object_uuid=object_uuid)
    if not _type_matches(obj.object_type, object_type):
        raise MutationError("type_mismatch", object_uuid=object_uuid)
    if capability.sensitive and any(
        key in fields for key in ("pat", "password", "secret", "api_key", "properties")
    ):
        raise MutationError("operation_not_safe_offline", object_type=object_type.value)
    if preview:
        return {"status": "preview", "uuid": object_uuid, "action": "update", "fields": list(fields)}
    new_name = str(fields.get("name", obj.name))
    path = _object_path(export_dir, obj)
    writes: dict[Path, bytes] = {}
    deletes: list[Path] = []
    updated_uuid = object_uuid
    if capability.native_write and set(fields) - {"name"}:
        from appian_sentinel.generator.object_writer import build_native_object_artifacts

        native_fields = obj.model_dump(mode="python")
        native_fields.update(fields)
        for key in ("object_type", "uuid", "name", "file_path"):
            native_fields.pop(key, None)
        try:
            primary, artifacts = build_native_object_artifacts(
                object_type, object_uuid, new_name, native_fields
            )
        except ValueError as exc:
            raise MutationError(
                "schema_required",
                object_type=object_type.value,
                message=str(exc),
            ) from exc
        expected_primary = (export_dir / primary).resolve()
        for relative_path, content in artifacts.items():
            target = (export_dir / relative_path).resolve()
            writes[path if target == expected_primary else target] = content
    else:
        content = path.read_bytes()
        if "name" in fields:
            updated_uuid = _new_object_uuid(
                object_type,
                obj,
                new_name,
                object_uuid,
            )
            content = _rewrite_identity_bytes(
                content,
                updated_uuid,
                new_name,
                old_uuid=object_uuid,
                old_name=obj.name,
            )
        definition = fields.get("definition", fields.get("sail_code"))
        if definition is not None:
            content = _rewrite_first_text_bytes(content, "definition", str(definition))
        updated_path = _object_destination(path, object_type, updated_uuid)
        if updated_path != path:
            if updated_path.exists():
                raise MutationError("already_exists", object_uuid=updated_uuid)
            deletes.append(path)
        path = updated_path
        writes[path] = content
    if "name" in fields:
        try:
            if updated_uuid == object_uuid:
                writes.update(
                    build_object_metadata_updates(
                        export_dir, object_type, object_uuid, new_name, add=True
                    )
                )
            else:
                writes.update(
                    _rename_metadata_updates(
                        export_dir,
                        object_type,
                        object_uuid,
                        updated_uuid,
                        new_name,
                    )
                )
        except ExportMetadataError as exc:
            raise MutationError("metadata_invalid", message=str(exc)) from exc
    changed = _apply_mutation(export_dir, writes, deletes, f"Update {obj.name}")
    _commit_paths(export_dir, changed, f"Update {obj.name}")
    cache.get_codebase(export_dir, rebuild=True)
    return {"status": "updated", "uuid": updated_uuid, "file_path": str(path)}


def delete_typed_object(
    export_dir: Path,
    object_type: ObjectType,
    object_uuid: str,
    *,
    force: bool = False,
    preview: bool = False,
) -> dict[str, Any]:
    cb = cache.get_codebase(export_dir)
    obj = cb.get_object(object_uuid)
    if obj is None:
        raise MutationError("not_found", object_uuid=object_uuid)
    if not _type_matches(obj.object_type, object_type):
        raise MutationError("type_mismatch", object_uuid=object_uuid)
    dependents = sorted(cb.get_direct_dependents(object_uuid))
    children = sorted(
        child.uuid for child in cb.objects.values() if child.parent_uuid == object_uuid
    )
    blocked = dependents or children
    if blocked and not force:
        raise MutationError(
            "dependency_blocked",
            object_uuid=object_uuid,
            dependents=dependents,
            children=children,
        )
    path = _object_path(export_dir, obj)
    payload = {
        "status": "preview" if preview else "deleted",
        "uuid": object_uuid,
        "file_path": str(path),
        "dependents": dependents,
        "children": children,
        "forced": force and bool(blocked),
    }
    if preview:
        return payload
    payload_dir = path.with_suffix("")
    deletes = [path]
    if payload_dir.is_dir():
        deletes.append(payload_dir)
    try:
        metadata = build_object_metadata_updates(
            export_dir, object_type, object_uuid, obj.name, add=False
        )
    except ExportMetadataError as exc:
        raise MutationError("metadata_invalid", message=str(exc)) from exc
    changed = _apply_mutation(
        export_dir, metadata, deletes, f"Delete {obj.name}"
    )
    _commit_paths(export_dir, changed, f"Delete {obj.name}")
    cache.get_codebase(export_dir, rebuild=True)
    return payload


def _capability(object_type: ObjectType) -> ObjectCapability:
    capability = CAPABILITY_BY_TYPE.get(object_type)
    if capability is None:
        raise MutationError("unsupported_type", object_type=object_type.value)
    return capability


def _type_matches(actual: ObjectType, expected: ObjectType) -> bool:
    if actual is expected:
        return True
    aliases = {
        ObjectType.DOCUMENT_FOLDER: {ObjectType.FOLDER},
        ObjectType.OUTBOUND_INTEGRATION: {ObjectType.OUTBOUND_INTEGRATION},
        ObjectType.RULES_FOLDER: {ObjectType.RULES_FOLDER},
    }
    return actual in aliases.get(expected, set())


def _create_native_object(
    export_dir: Path,
    object_type: ObjectType,
    *,
    name: str,
    fields: dict[str, Any],
    preview: bool,
) -> dict[str, Any]:
    """Create an object from its native writer, with no same-type template present."""
    fields = dict(fields)
    requested_uuid = str(fields.pop("uuid", "")).strip()
    if object_type is ObjectType.DATA_TYPE:
        namespace = str(fields.get("namespace", "")).strip()
        if not namespace:
            raise MutationError(
                "namespace_required",
                object_type=object_type.value,
                message="Data Type creation without a template needs a namespace",
            )
        if not name or any(character.isspace() for character in name):
            raise MutationError(
                "invalid_name",
                object_type=object_type.value,
                message="Data Type names must be one non-empty token",
            )
        new_uuid = requested_uuid or f"{{{namespace}}}{name}"
    else:
        new_uuid = requested_uuid or str(uuid.uuid4())

    if preview:
        return {
            "status": "preview",
            "uuid": new_uuid,
            "name": name,
            "template_uuid": "",
            "action": "create",
            "source": "native_writer",
        }

    try:
        relative_primary, artifacts = build_native_object_artifacts(
            object_type, new_uuid, name, fields
        )
    except ValueError as exc:
        raise MutationError(
            "invalid_fields",
            object_type=object_type.value,
            message=str(exc),
        ) from exc

    dest = export_dir / relative_primary
    if dest.exists():
        raise MutationError("already_exists", object_uuid=new_uuid)
    writes = {export_dir / path: content for path, content in artifacts.items()}
    try:
        writes.update(
            build_object_metadata_updates(
                export_dir, object_type, new_uuid, name, add=True
            )
        )
    except ExportMetadataError as exc:
        raise MutationError("metadata_invalid", message=str(exc)) from exc
    changed = _apply_mutation(export_dir, writes, [], f"Create {name}")
    _commit_paths(export_dir, changed, f"Create {name}")
    cache.get_codebase(export_dir, rebuild=True)
    return {
        "status": "created",
        "uuid": new_uuid,
        "name": name,
        "file_path": str(dest),
        "template_uuid": "",
        "source": "native_writer",
    }


def _template_object(export_dir: Path, object_type: ObjectType, template_uuid: str) -> Any:
    cb = cache.get_codebase(export_dir)
    if template_uuid:
        obj = cb.get_object(template_uuid)
        if obj is not None and _type_matches(obj.object_type, object_type):
            return obj
        return None
    for obj in cb.objects.values():
        if _type_matches(obj.object_type, object_type) and obj.file_path:
            return obj
    return None


def _object_path(export_dir: Path, obj: Any) -> Path:
    path = Path(str(getattr(obj, "file_path", "") or ""))
    if not path.is_absolute():
        path = export_dir / path
    return path.resolve()


def _new_object_uuid(
    object_type: ObjectType,
    template: Any,
    name: str,
    requested_uuid: str,
) -> str:
    if object_type is not ObjectType.DATA_TYPE:
        return requested_uuid or str(uuid.uuid4())
    if not name or any(character.isspace() for character in name):
        raise MutationError(
            "invalid_name",
            object_type=object_type.value,
            message="Data Type names must be one non-empty token",
        )
    namespace = str(getattr(template, "namespace", "")).strip()
    if not namespace:
        raise MutationError("invalid_template", object_type=object_type.value)
    return f"{{{namespace}}}{name}"


def _object_destination(
    source: Path,
    object_type: ObjectType,
    object_uuid: str,
) -> Path:
    if object_type is not ObjectType.DATA_TYPE:
        return source.parent / f"{object_uuid}{source.suffix}"
    return source.parent / f"{quote(object_uuid, safe='')}{source.suffix}"


def _rename_metadata_updates(
    export_dir: Path,
    object_type: ObjectType,
    old_uuid: str,
    new_uuid: str,
    name: str,
) -> dict[Path, bytes]:
    export_tag, application_tag = metadata_tags(object_type)
    application_paths = sorted(export_dir.glob("application/*.xml"))
    if len(application_paths) != 1:
        raise ExportMetadataError(
            "export must contain exactly one application XML file"
        )
    application_path = application_paths[0]
    log_path = export_dir / "META-INF" / "export.log"
    application = update_application_membership(
        application_path.read_bytes(),
        application_tag,
        old_uuid,
        add=False,
    )
    application = update_application_membership(
        application,
        application_tag,
        new_uuid,
        add=True,
    )
    export_log = update_export_log(
        log_path.read_bytes(),
        export_tag,
        old_uuid,
        name,
        add=False,
    )
    export_log = update_export_log(
        export_log,
        export_tag,
        new_uuid,
        name,
        add=True,
    )
    return {application_path: application, log_path: export_log}


def _rewrite_identity_bytes(
    content: bytes,
    object_uuid: str,
    name: str,
    *,
    old_uuid: str = "",
    old_name: str = "",
) -> bytes:
    parser = etree.XMLParser(remove_blank_text=False, resolve_entities=False, no_network=True)
    root = etree.fromstring(content, parser)
    uuid_replaced = _replace_identity_value(root, "uuid", old_uuid, object_uuid)
    name_replaced = _replace_identity_value(root, "name", old_name, name)
    if not uuid_replaced:
        _set_first_named(root, "uuid", object_uuid)
    if not name_replaced:
        _set_first_named(root, "name", name)
    return etree.tostring(
        root.getroottree(),
        encoding="utf-8",
        xml_declaration=content.lstrip().startswith(b"<?xml"),
    )


def _replace_identity_value(
    root: etree._Element,
    local_name: str,
    old_value: str,
    new_value: str,
) -> bool:
    if not old_value:
        return False
    replaced = False
    for node in root.xpath(f".//*[local-name()='{local_name}']"):
        if (node.text or "") == old_value:
            node.text = new_value
            replaced = True
    if local_name == "name":
        for node in root.iter():
            if node.text == old_value:
                node.text = new_value
                replaced = True
    for node in root.xpath(f".//*[@*[local-name()='{local_name}']]"):
        for attr in list(node.attrib):
            if (
                (attr == local_name or attr.endswith(f"}}{local_name}"))
                and node.attrib[attr] == old_value
            ):
                node.attrib[attr] = new_value
                replaced = True
    return replaced


def _rewrite_first_text_bytes(content: bytes, local_name: str, value: str) -> bytes:
    parser = etree.XMLParser(remove_blank_text=False, resolve_entities=False, no_network=True)
    root = etree.fromstring(content, parser)
    _set_first_named(root, local_name, value)
    return etree.tostring(
        root.getroottree(),
        encoding="utf-8",
        xml_declaration=content.lstrip().startswith(b"<?xml"),
    )


def _set_first_named(root: etree._Element, local_name: str, value: str) -> None:
    for node in root.xpath(f".//*[local-name()='{local_name}']"):
        node.text = value
        return
    for node in root.xpath(f".//*[@*[local-name()='{local_name}']]"):
        for attr in list(node.attrib):
            if attr == local_name or attr.endswith(f"}}{local_name}"):
                node.attrib[attr] = value
                return


def _apply_mutation(
    export_dir: Path,
    writes: dict[Path, bytes],
    deletes: list[Path],
    message: str,
) -> list[Path]:
    del message
    transaction = MutationTransaction(export_dir)
    try:
        for path, content in writes.items():
            transaction.write(path, content)
        for path in deletes:
            transaction.delete(path)
        return transaction.commit()
    except Exception as exc:
        if isinstance(exc, MutationError):
            raise
        raise MutationError("transaction_failed", message=str(exc)) from exc


def _commit_paths(export_dir: Path, paths: list[Path], message: str) -> None:
    history = WorkspaceHistoryService(export_dir)
    if history.head() is None:
        history.create_baseline(actor="system", requirement="", message="baseline")
    for path in paths:
        try:
            history.stage(path.relative_to(export_dir).as_posix())
        except Exception:
            continue
    if history.staged_changes():
        history.commit(actor="mcp", requirement="", message=message)
