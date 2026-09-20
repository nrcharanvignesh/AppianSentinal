"""Safe adapter between FastMCP tools and OpenAI chat tool schemas.

Exposes object CRUD and analysis tools to chat. The host controls the session
directory, typed creates and updates apply directly, and typed deletes are
always previews that require a separate desktop confirmation.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from appian_sentinel.mcp_server import server
from appian_sentinel.models.object_registry import OBJECT_CAPABILITIES
from appian_sentinel.security import mask_secrets

MAX_RESULT_CHARS = 20_000

# Safe analysis and inspection tools.
READ_ONLY_TOOLS: frozenset[str] = frozenset(
    {
        "get_codebase",
        "get_dependency_graph",
        "get_object",
        "get_object_tests",
        "history_diff",
        "history_log",
        "inspect_sail",
        "list_objects",
        "resolve_object",
        "run_object_static_test",
        "run_static_tests",
        "search_objects",
        "validate_object",
        "validate_sail",
        "validate_test_coverage",
        "validate_workspace",
        "workspace_status",
    }
)
TYPED_GET_TOOLS: frozenset[str] = frozenset(
    capability.get_tool for capability in OBJECT_CAPABILITIES
)
TYPED_CREATE_TOOLS: frozenset[str] = frozenset(
    capability.create_tool for capability in OBJECT_CAPABILITIES
)
TYPED_UPDATE_TOOLS: frozenset[str] = frozenset(
    capability.update_tool for capability in OBJECT_CAPABILITIES
)
TYPED_DELETE_TOOLS: frozenset[str] = frozenset(
    capability.delete_tool for capability in OBJECT_CAPABILITIES
)

# These bounded workspace mutations are useful in chat and do not package,
# restore history, commit arbitrary paths, or access external services.
GENERAL_WRITE_TOOLS: frozenset[str] = frozenset(
    {
        "apply_object_change",
        "apply_sail_edit",
        "bulk_add_tests",
        "bulk_replace_tests",
    }
)

ALLOWED_CHAT_TOOLS: frozenset[str] = (
    READ_ONLY_TOOLS
    | TYPED_GET_TOOLS
    | TYPED_CREATE_TOOLS
    | TYPED_UPDATE_TOOLS
    | TYPED_DELETE_TOOLS
    | GENERAL_WRITE_TOOLS
)

# Model-supplied filesystem paths are never trusted; the host injects the real
# export directory instead.
_PATH_KEYS: frozenset[str] = frozenset(
    {
        "export_dir",
        "file_path",
        "file_paths",
        "output_path",
        "path",
        "paths",
        "staged_paths",
        "zip_path",
    }
)


def is_allowed_chat_tool(name: str) -> bool:
    """Report whether a tool name is exposed to the chat model."""
    return name in ALLOWED_CHAT_TOOLS


async def list_chat_tools() -> list[dict[str, object]]:
    """Convert allowlisted MCP tools into OpenAI chat tool definitions."""
    chat_tools: list[dict[str, object]] = []
    for tool in await server.mcp.list_tools():
        if not is_allowed_chat_tool(tool.name):
            continue
        chat_tools.append(
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": _chat_description(
                        tool.name, (tool.description or "").strip()
                    ),
                    "parameters": _strip_schema_keyword(tool.inputSchema),
                },
            }
        )
    return chat_tools


def _chat_description(name: str, description: str) -> str:
    if name in TYPED_DELETE_TOOLS:
        return (
            f"{description} In chat this always returns a non-mutating preview; "
            "the desktop must confirm before deletion."
        )
    return description


def normalize_tool_arguments(
    schema: Mapping[str, object] | None,
    arguments: object,
) -> dict[str, object]:
    """Parse model tool arguments and wrap flat keys under ``request``."""
    parsed = _parse_arguments(arguments)
    properties = _properties(schema)
    if set(properties) == {"request"} and "request" not in parsed:
        return {"request": parsed}
    return parsed


async def invoke_chat_tool(
    name: str,
    arguments: object,
    export_dir: str,
) -> dict[str, object]:
    """Run one allowlisted MCP tool with host-controlled session context."""
    if not is_allowed_chat_tool(name):
        return _error(name, "not_allowed", f"tool {name} is not available in chat")
    schema = await _input_schema(name)
    if schema is None:
        return _error(name, "unknown_tool", f"tool {name} is not registered")
    try:
        payload = normalize_tool_arguments(schema, arguments)
    except ValueError as exc:
        return _error(name, "invalid_arguments", str(exc))
    payload = _inject_context(schema, payload, export_dir)
    if name in TYPED_CREATE_TOOLS or name in TYPED_UPDATE_TOOLS:
        _set_request_values(payload, preview=False)
    if name in TYPED_DELETE_TOOLS:
        return await _preview_chat_delete(name, payload)
    try:
        raw = await server.mcp.call_tool(name, payload)
    except Exception as exc:  # FastMCP raises ToolError and validation errors.
        return _error(name, "tool_error", f"{type(exc).__name__}: {exc}")
    return _bounded_result(name, raw)


def _set_request_values(
    payload: dict[str, object],
    **values: object,
) -> None:
    request = payload.get("request")
    target = request if isinstance(request, dict) else payload
    target.update(values)


async def _preview_chat_delete(
    name: str,
    payload: dict[str, object],
) -> dict[str, object]:
    """Return a non-mutating typed delete preview plus confirmation metadata."""
    request = payload.get("request")
    if not isinstance(request, Mapping):
        return _error(name, "invalid_arguments", "typed delete requires a request object")
    export_dir = request.get("export_dir")
    object_uuid = request.get("object_uuid")
    if not isinstance(export_dir, str) or not isinstance(object_uuid, str):
        return _error(
            name,
            "invalid_arguments",
            "typed delete requires export_dir and object_uuid",
        )

    get_name = name.replace("delete_", "get_", 1)
    get_payload = {
        "request": {"export_dir": export_dir, "object_uuid": object_uuid}
    }
    _set_request_values(payload, preview=True, force=True)
    try:
        object_raw = await server.mcp.call_tool(get_name, get_payload)
        preview_raw = await server.mcp.call_tool(name, payload)
    except Exception as exc:
        return _error(name, "tool_error", f"{type(exc).__name__}: {exc}")

    object_result = _result_mapping(object_raw)
    preview_result = _result_mapping(preview_raw)
    object_detail = object_result.get("object")
    if not isinstance(object_detail, Mapping):
        object_detail = {}
    dependents = object_detail.get(
        "direct_dependents", preview_result.get("dependents", [])
    )
    children = preview_result.get("children", [])
    slug = name.removeprefix("delete_")
    pending = {
        "status": "pending_deletion",
        "pending_deletion": True,
        "applied": False,
        "tool": name,
        "object": {
            "uuid": object_uuid,
            "name": str(object_result.get("name") or object_detail.get("name") or ""),
            "type": str(object_detail.get("object_type") or slug),
        },
        "reverse_dependencies": dependents if isinstance(dependents, list) else [],
        "children": children if isinstance(children, list) else [],
        "confirmation": {
            "required": True,
            "action": "delete_typed_object",
            "slug": slug,
            "object_uuid": object_uuid,
            "preview": False,
            "force_required": bool(dependents or children),
        },
    }
    return _bounded_result(name, pending)


def _result_mapping(raw: object) -> dict[str, object]:
    safe = _json_safe(_unwrap(raw))
    return safe if isinstance(safe, dict) else {}


async def _input_schema(name: str) -> Mapping[str, object] | None:
    for tool in await server.mcp.list_tools():
        if tool.name == name:
            return tool.inputSchema
    return None


def _strip_schema_keyword(value: object) -> Any:
    """Copy a JSON schema without ``$schema``, keeping ``$defs`` and ``$ref``."""
    if isinstance(value, Mapping):
        return {
            str(key): _strip_schema_keyword(item)
            for key, item in value.items()
            if key != "$schema"
        }
    if isinstance(value, list):
        return [_strip_schema_keyword(item) for item in value]
    return value


def _parse_arguments(arguments: object) -> dict[str, object]:
    value = arguments
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8", "replace")
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"tool arguments are not valid JSON: {exc.msg}") from exc
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError("tool arguments must be a JSON object")
    return {str(key): item for key, item in value.items()}


def _properties(schema: Mapping[str, object] | None) -> dict[str, object]:
    if not isinstance(schema, Mapping):
        return {}
    properties = schema.get("properties")
    if not isinstance(properties, Mapping):
        return {}
    return {str(key): value for key, value in properties.items()}


def _required(schema: Mapping[str, object] | None) -> frozenset[str]:
    if not isinstance(schema, Mapping):
        return frozenset()
    required = schema.get("required")
    if not isinstance(required, Sequence) or isinstance(required, (str, bytes)):
        return frozenset()
    return frozenset(str(item) for item in required)


def _resolve_ref(
    root: Mapping[str, object],
    node: object,
) -> Mapping[str, object] | None:
    if not isinstance(node, Mapping):
        return None
    ref = node.get("$ref")
    if not isinstance(ref, str) or not ref.startswith("#/$defs/"):
        return node
    definitions = root.get("$defs")
    if not isinstance(definitions, Mapping):
        return None
    target = definitions.get(ref.removeprefix("#/$defs/"))
    return target if isinstance(target, Mapping) else None


def _inject_context(
    schema: Mapping[str, object],
    arguments: dict[str, object],
    export_dir: str,
) -> dict[str, object]:
    properties = _properties(schema)
    payload = _apply_context(properties, _required(schema), arguments, export_dir)
    request = payload.get("request")
    if set(properties) == {"request"} and isinstance(request, Mapping):
        target = _resolve_ref(schema, properties["request"])
        payload["request"] = _apply_context(
            _properties(target),
            _required(target),
            {str(key): value for key, value in request.items()},
            export_dir,
        )
    return payload


def _apply_context(
    properties: Mapping[str, object],
    required: frozenset[str],
    arguments: Mapping[str, object],
    export_dir: str,
) -> dict[str, object]:
    # An optional export_dir is only injected when the model asked for workspace
    # access, because some requests reject it without a companion object_uuid.
    wants_workspace = "export_dir" in arguments
    payload = {
        str(key): value for key, value in arguments.items() if key not in _PATH_KEYS
    }
    if "export_dir" in properties and (wants_workspace or "export_dir" in required):
        payload["export_dir"] = export_dir
    return payload


def _unwrap(raw: object) -> object:
    # Some FastMCP versions return (content_blocks, structured_result).
    if isinstance(raw, tuple) and len(raw) == 2 and isinstance(raw[1], Mapping):
        return raw[1]
    return raw


def _json_safe(value: object) -> Any:
    if isinstance(value, str):
        return mask_secrets(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return _json_safe(dump(mode="json"))
    if isinstance(value, (bytes, bytearray)):
        return mask_secrets(value.decode("utf-8", "replace"))
    if isinstance(value, Sequence):
        return [_json_safe(item) for item in value]
    return mask_secrets(str(value))


def _bounded_result(name: str, raw: object) -> dict[str, object]:
    safe = _json_safe(_unwrap(raw))
    text = json.dumps(safe, ensure_ascii=True, default=str)
    if len(text) > MAX_RESULT_CHARS:
        return {
            "ok": True,
            "tool": name,
            "truncated": True,
            "result": text[:MAX_RESULT_CHARS],
        }
    return {"ok": True, "tool": name, "truncated": False, "result": safe}


def _error(name: str, code: str, message: str) -> dict[str, object]:
    return {
        "ok": False,
        "tool": name,
        "error": {"code": code, "message": mask_secrets(message)},
    }
