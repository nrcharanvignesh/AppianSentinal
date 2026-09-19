from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import shutil
import zipfile
from difflib import unified_diff
from pathlib import Path
from typing import Any

import aiofiles
from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile, WebSocket
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from appian_sentinel.agent.orchestrator import Orchestrator
from appian_sentinel.agent.progress import ProgressResult
from appian_sentinel.agent.state import AgentState
from appian_sentinel.analyzer import pdf_extractor
from appian_sentinel.config import settings
from appian_sentinel.generator import xml_writer
from appian_sentinel.generator.object_writer import write_object
from appian_sentinel.integrations import ado_client
from appian_sentinel.models.workspace import Revision
from appian_sentinel.packager import patch_builder, zip_builder
from appian_sentinel.parser import codebase_map as codebase_map_mod
from appian_sentinel.parser.sail_diagnostics import analyze_sail
from appian_sentinel.parser.xml_parser import parse_appian_xml
from appian_sentinel.security import mask_secret, mask_secrets
from appian_sentinel.services.object_tests import (
    UnsupportedTestCaseError,
    clone_test_nodes,
    extract_test_cases,
)
from appian_sentinel.services.workspace import (
    RevisionNotFoundError,
    WorkspaceHistoryService,
)
from appian_sentinel.web.websocket import ChatWebSocket

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


class ObjectUpdate(BaseModel):
    definition: str | None = None


class HistoryCommitBody(BaseModel):
    message: str = Field(min_length=1)
    actor: str = "desktop"
    requirement_id: str = ""


class HistoryRestoreBody(BaseModel):
    revision: str = Field(min_length=1)


class BulkTestCaseBody(BaseModel):
    name: str = Field(min_length=1)
    description: str = ""
    inputs: dict[str, Any] = Field(default_factory=dict)
    expected: Any


class BulkTestsBody(BaseModel):
    object_uuids: list[str] = Field(min_length=1)
    tests: list[BulkTestCaseBody] = Field(min_length=1)
    preview: bool = False


@router.get("/health")
async def health() -> JSONResponse:
    """Liveness probe used by the Electron shell to know the sidecar is up."""
    return JSONResponse({
        "status": "ok",
        "ownership_id": os.environ.get("SENTINEL_DESKTOP_OWNERSHIP_ID") or None,
    })


# ---------------------------------------------------------------------------
# In-memory session store.  For a production deployment this would be backed
# by Redis or a database; for the single-user Sentinel scenario keeping it
# in-process is fine.
# ---------------------------------------------------------------------------
_sessions: dict[str, dict[str, Any]] = {}


async def _emit_route_progress(
    orchestrator: Orchestrator,
    *,
    phase: str,
    current: int,
    total: int,
    detail: str,
    result: ProgressResult | None = None,
) -> None:
    await orchestrator.emit_progress(
        phase=phase,
        current=current,
        total=total,
        detail=detail,
        result=result,
    )


def _get_session(request: Request) -> dict[str, Any]:
    """Return (or create) the session dict for the current user.

    The session id is carried as a query param or header so that the
    WebSocket and REST endpoints share the same session.
    """
    sid = (
        request.query_params.get("session_id")
        or request.headers.get("X-Session-Id")
        or "default"
    )
    if sid not in _sessions:
        state = AgentState(max_iterations=settings.sentinel_max_agent_iterations)
        orchestrator = Orchestrator(state)
        _sessions[sid] = {
            "state": state,
            "orchestrator": orchestrator,
            "run_task": None,
        }
    return _sessions[sid]


# ------------------------------------------------------------------
# File upload endpoints
# ------------------------------------------------------------------


@router.post("/upload")
async def upload_zip(request: Request, file: UploadFile = File(...)) -> JSONResponse:
    """Upload an Appian export ZIP, extract it, and build the codebase map."""
    session = _get_session(request)
    state: AgentState = session["state"]
    orchestrator: Orchestrator = session["orchestrator"]

    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Please upload a .zip file.")

    workspace = settings.sentinel_workspace.resolve()
    workspace.mkdir(parents=True, exist_ok=True)

    async def _push_progress(
        phase: str,
        current: int,
        total: int,
        detail: str,
        result: ProgressResult | None = None,
    ) -> None:
        await _emit_route_progress(
            orchestrator,
            phase=phase,
            current=current,
            total=total,
            detail=detail,
            result=result,
        )

    await _push_progress("upload", 0, 1, f"Saving {file.filename}.")

    # Save uploaded file
    zip_path = workspace / file.filename
    try:
        async with aiofiles.open(zip_path, "wb") as f:
            content = await file.read()
            await f.write(content)
    except Exception as exc:
        await _push_progress("upload", 1, 1, f"Upload failed: {exc}", "failed")
        raise
    await _push_progress("upload", 1, 1, f"Saved {file.filename}.", "ok")

    # Extract
    await _push_progress("extract", 0, 1, "Extracting ZIP archive.")
    try:
        export_dir = workspace / f"export_{state.session_id}"
        if export_dir.exists():
            shutil.rmtree(export_dir)
        export_dir.mkdir(parents=True)

        await asyncio.to_thread(_extract_zip, zip_path, export_dir)
    except zipfile.BadZipFile:
        await _push_progress("extract", 1, 1, "ZIP extraction failed: invalid ZIP.", "failed")
        raise HTTPException(status_code=400, detail="Uploaded file is not a valid ZIP.")
    except Exception as exc:
        await _push_progress("extract", 1, 1, f"ZIP extraction failed: {exc}", "failed")
        raise

    await _push_progress("extract", 1, 1, "ZIP extracted successfully.", "ok")

    # Build codebase map with progress reporting
    loop = asyncio.get_event_loop()

    def _sync_progress(phase: str, current: int, total: int, detail: str) -> None:
        asyncio.run_coroutine_threadsafe(
            _push_progress(
                phase,
                current,
                total,
                detail,
                "ok" if phase == "complete" else None,
            ),
            loop,
        )

    try:
        codebase = await asyncio.to_thread(
            codebase_map_mod.build_codebase_map, export_dir, _sync_progress
        )
    except Exception as exc:
        logger.exception("Failed to build codebase map")
        await _push_progress("complete", 1, 1, f"Codebase parsing failed: {exc}", "failed")
        raise HTTPException(status_code=500, detail=f"Codebase parsing failed: {exc}")

    codebase_dict = codebase.model_dump(mode="json") if hasattr(codebase, "model_dump") else codebase
    state.codebase_map = codebase_dict
    state.export_dir = str(export_dir)
    orchestrator._export_dir = export_dir

    history = WorkspaceHistoryService(export_dir)
    if history.head() is None:
        history.create_baseline(
            actor="system",
            requirement="",
            message="Uploaded export baseline",
        )

    state.add_system_message(f"Codebase loaded: {file.filename}")

    return JSONResponse({
        "status": "ok",
        "session_id": state.session_id,
        "objects": len(codebase_dict.get("objects", {})),
        "export_dir": str(export_dir),
    })


@router.post("/story")
async def upload_story(request: Request, file: UploadFile = File(...)) -> JSONResponse:
    """Upload a user-story PDF and parse it."""
    session = _get_session(request)
    state: AgentState = session["state"]
    orchestrator: Orchestrator = session["orchestrator"]

    workspace = settings.sentinel_workspace.resolve()
    workspace.mkdir(parents=True, exist_ok=True)

    story_path = workspace / (file.filename or "story.pdf")
    await _emit_route_progress(
        orchestrator,
        phase="story.upload",
        current=0,
        total=1,
        detail="Story upload started.",
    )
    try:
        async with aiofiles.open(story_path, "wb") as f:
            content = await file.read()
            await f.write(content)
    except Exception as exc:
        await _emit_route_progress(
            orchestrator,
            phase="story.upload",
            current=1,
            total=1,
            detail=f"Story upload failed: {exc}",
            result="failed",
        )
        raise
    await _emit_route_progress(
        orchestrator,
        phase="story.upload",
        current=1,
        total=1,
        detail="Story upload completed.",
        result="ok",
    )

    model = settings.sentinel_fast_model
    await _emit_route_progress(
        orchestrator,
        phase="llm.story_parse",
        current=0,
        total=1,
        detail=f"Story parsing LLM call started: model {model}.",
    )
    try:
        story = await pdf_extractor.extract_user_story(story_path)
        state.user_story = story.model_dump() if hasattr(story, "model_dump") else dict(story)
        state.story_path = str(story_path)
    except Exception as exc:
        safe_error = _mask_secrets(str(exc))
        logger.error("Story parsing failed: %s", safe_error)
        await _emit_route_progress(
            orchestrator,
            phase="llm.story_parse",
            current=1,
            total=1,
            detail=f"Story parsing LLM call failed: model {model}: {safe_error}",
            result="failed",
        )
        raise HTTPException(status_code=500, detail=f"Story parsing failed: {safe_error}")
    await _emit_route_progress(
        orchestrator,
        phase="llm.story_parse",
        current=1,
        total=1,
        detail=f"Story parsing LLM call completed: model {model}.",
        result="ok",
    )

    state.add_system_message(f"User story loaded: {file.filename}")

    # If the codebase is already loaded, kick off the workflow automatically.
    if state.codebase_map and session["run_task"] is None:
        session["run_task"] = asyncio.create_task(
            orchestrator.run(Path(state.export_dir), story_path)
        )

    return JSONResponse({
        "status": "ok",
        "story": state.user_story,
    })


# ------------------------------------------------------------------
# Chat (non-WebSocket fallback)
# ------------------------------------------------------------------


@router.post("/chat")
async def chat(request: Request) -> JSONResponse:
    """Send a chat message and receive the response synchronously.

    This is a fallback for clients that cannot use WebSockets.  The
    response is not streamed.
    """
    session = _get_session(request)
    orchestrator: Orchestrator = session["orchestrator"]

    body = await request.json()
    message = body.get("message", "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Empty message.")

    responses: list[dict[str, Any]] = []
    async for msg in orchestrator.process_user_message(message):
        responses.append(msg.model_dump())

    return JSONResponse({"messages": responses})


# ------------------------------------------------------------------
# Status & data endpoints
# ------------------------------------------------------------------


@router.get("/status")
async def get_status(request: Request) -> JSONResponse:
    session = _get_session(request)
    state: AgentState = session["state"]
    return JSONResponse(state.to_summary())


@router.get("/codebase")
async def get_codebase(request: Request) -> JSONResponse:
    session = _get_session(request)
    state: AgentState = session["state"]
    if state.codebase_map is None:
        raise HTTPException(status_code=404, detail="Codebase not loaded yet.")
    cm = state.codebase_map
    return JSONResponse({
        "app_name": cm.get("app_name", ""),
        "app_uuid": cm.get("app_uuid", ""),
        "app_prefix": cm.get("app_prefix", ""),
        "appian_version": cm.get("appian_version", ""),
        "by_type": cm.get("by_type", {}),
        "uuid_to_name": cm.get("uuid_to_name", {}),
    })


@router.get("/objects/{uuid}")
async def get_object(request: Request, uuid: str) -> JSONResponse:
    session = _get_session(request)
    state: AgentState = session["state"]
    if state.codebase_map is None:
        raise HTTPException(status_code=404, detail="Codebase not loaded yet.")

    objects = state.codebase_map.get("objects", {})
    obj = objects.get(uuid)
    if obj is None:
        raise HTTPException(status_code=404, detail=f"Object {uuid} not found.")
    return JSONResponse(obj)


@router.put("/objects/{uuid}")
async def save_object(
    request: Request,
    uuid: str,
    body: ObjectUpdate,
) -> JSONResponse:
    """Update one definition and refresh its parsed session object."""
    session = _get_session(request)
    state: AgentState = session["state"]
    obj, export_dir, path = _session_object(state, uuid)
    if body.definition is None:
        raise HTTPException(
            status_code=400,
            detail={"reason": "definition_required"},
        )
    history = WorkspaceHistoryService(export_dir)
    if history.head() is None:
        history.create_baseline(
            actor="system",
            requirement=_session_requirement_id(state),
            message="baseline",
        )
    before = path.read_bytes()
    index_path = export_dir / ".history" / "index.json"
    index_backup = index_path.read_bytes()
    try:
        output = write_object(
            export_dir,
            {
                "type": obj.get("object_type", ""),
                "name": obj.get("name", ""),
                "uuid": uuid,
                "action": "modify",
                "definition": body.definition,
            },
        )
        if output is not None:
            history.stage(output.relative_to(export_dir).as_posix())
            history.commit(
                actor="desktop",
                requirement=_session_requirement_id(state),
                message=f"Saved object {obj.get('name', uuid)}",
            )
    except Exception:
        xml_writer._atomic_write_xml(path, before)
        index_path.write_bytes(index_backup)
        raise
    if output is None:
        raise HTTPException(
            status_code=400,
            detail={"reason": "object_definition_not_writable"},
        )
    parsed = parse_appian_xml(path)
    if parsed is None:
        raise HTTPException(status_code=500, detail="Saved object could not be parsed.")
    parsed_dict = parsed.model_dump(mode="json")
    state.codebase_map["objects"][uuid] = parsed_dict
    return JSONResponse(parsed_dict)


@router.get("/objects/{uuid}/diagnostics")
async def get_object_diagnostics(request: Request, uuid: str) -> JSONResponse:
    """Analyze the loaded object's SAIL definition."""
    session = _get_session(request)
    state: AgentState = session["state"]
    obj, _, _ = _session_object(state, uuid)
    definition = obj.get("definition")
    if not isinstance(definition, str):
        raise HTTPException(
            status_code=400,
            detail={"reason": "object_has_no_sail_definition"},
        )
    codebase = state.codebase_map or {}
    analysis = analyze_sail(
        definition,
        target_version=codebase.get("appian_version") or None,
        known_uuids=set(codebase.get("objects", {})),
        declared_inputs=[
            item["name"]
            for item in obj.get("rule_inputs", [])
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        ],
    )
    return JSONResponse({
        "is_valid": analysis.is_valid,
        "diagnostics": [
            {
                "code": item.code,
                "message": item.message,
                "severity": item.severity.value,
                "line": item.line,
                "column": item.column,
                "end_line": item.end_line,
                "end_column": item.end_column,
            }
            for item in analysis.diagnostics
        ],
    })


@router.get("/objects/{uuid}/tests")
async def get_object_tests(request: Request, uuid: str) -> JSONResponse:
    """Extract embedded test cases from the source XML."""
    session = _get_session(request)
    state: AgentState = session["state"]
    _, _, path = _session_object(state, uuid)
    return JSONResponse({"object_uuid": uuid, "tests": extract_test_cases(path)})


@router.post("/tests/bulk")
async def bulk_tests(request: Request, body: BulkTestsBody) -> JSONResponse:
    """Preview or atomically replace tests across loaded content objects."""
    session = _get_session(request)
    state: AgentState = session["state"]
    orchestrator: Orchestrator = session["orchestrator"]
    tests = [item.model_dump(mode="python") for item in body.tests]
    prepared: list[tuple[str, Path, bytes, bytes]] = []
    if not body.preview:
        await _emit_route_progress(
            orchestrator,
            phase="bulk_tests.apply",
            current=0,
            total=len(dict.fromkeys(body.object_uuids)),
            detail="Bulk test apply started.",
        )
    try:
        for uuid in dict.fromkeys(body.object_uuids):
            obj, _, path = _session_object(state, uuid)
            if obj.get("object_type") not in {"expression_rule", "interface"}:
                raise UnsupportedTestCaseError("object_type_has_no_test_case_slot")
            test_nodes = clone_test_nodes(path, tests)
            original = path.read_bytes()
            updated = xml_writer.render_content_nodes(path, test_nodes=test_nodes)
            prepared.append((uuid, path, original, updated))
    except UnsupportedTestCaseError as exc:
        if not body.preview:
            await _emit_route_progress(
                orchestrator,
                phase="bulk_tests.apply",
                current=len(prepared),
                total=len(dict.fromkeys(body.object_uuids)),
                detail=f"Bulk test apply failed: {exc.reason}",
                result="failed",
            )
        raise HTTPException(
            status_code=400,
            detail={"reason": exc.reason},
        ) from exc
    except Exception as exc:
        if not body.preview:
            await _emit_route_progress(
                orchestrator,
                phase="bulk_tests.apply",
                current=len(prepared),
                total=len(dict.fromkeys(body.object_uuids)),
                detail=f"Bulk test apply failed: {exc}",
                result="failed",
            )
        raise

    diffs = {
        uuid: "".join(unified_diff(
            original.decode("utf-8").splitlines(keepends=True),
            updated.decode("utf-8").splitlines(keepends=True),
            fromfile=f"a/{path.name}",
            tofile=f"b/{path.name}",
        ))
        for uuid, path, original, updated in prepared
    }
    if body.preview:
        return JSONResponse({"preview": True, "diff": diffs})

    export_dir = Path(state.export_dir or "").resolve()
    history = WorkspaceHistoryService(export_dir)
    if history.head() is None:
        history.create_baseline(actor="system", requirement="", message="baseline")
    index_path = export_dir / ".history" / "index.json"
    index_backup = index_path.read_bytes() if index_path.exists() else None
    try:
        for _, path, _, updated in prepared:
            xml_writer._atomic_write_xml(path, updated)
        for _, path, _, _ in prepared:
            history.stage(path.relative_to(export_dir).as_posix())
        revision = history.commit(
            actor="desktop",
            requirement=_session_requirement_id(state),
            message="Bulk test case update",
        )
    except Exception as exc:
        for _, path, original, _ in prepared:
            xml_writer._atomic_write_xml(path, original)
        if index_backup is not None:
            index_path.write_bytes(index_backup)
        await _emit_route_progress(
            orchestrator,
            phase="bulk_tests.apply",
            current=len(prepared),
            total=len(prepared),
            detail=f"Bulk test apply failed and was rolled back: {exc}",
            result="failed",
        )
        raise

    for uuid, path, _, _ in prepared:
        parsed = parse_appian_xml(path)
        if parsed is not None and state.codebase_map is not None:
            state.codebase_map["objects"][uuid] = parsed.model_dump(mode="json")
    await _emit_route_progress(
        orchestrator,
        phase="bulk_tests.apply",
        current=len(prepared),
        total=len(prepared),
        detail=f"Bulk test apply completed for {len(prepared)} object(s).",
        result="ok",
    )
    return JSONResponse({
        "preview": False,
        "revision": revision.hash,
        "object_uuids": [item[0] for item in prepared],
    })


@router.get("/history")
async def get_history(request: Request) -> JSONResponse:
    """List newest-first revisions for the loaded export only."""
    service = _session_history(request)
    return JSONResponse([
        {
            "hash": revision.hash,
            "message": revision.message,
            "actor": revision.actor,
            "timestamp": revision.timestamp.isoformat(),
            "requirement_id": revision.requirement,
        }
        for revision in service.log()
    ])


@router.get("/history/diff")
async def get_history_diff(
    request: Request,
    from_revision: str = Query(alias="from"),
    to_revision: str | None = Query(default=None, alias="to"),
) -> JSONResponse:
    """Diff two loaded-export revisions."""
    try:
        changes = _session_history(request).diff(from_revision, to_revision)
    except RevisionNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"reason": "revision_not_found", "revision": exc.revision_hash},
        ) from exc
    return JSONResponse([item.model_dump(mode="json") for item in changes])


@router.post("/history/commit")
async def commit_history(
    request: Request,
    body: HistoryCommitBody,
) -> JSONResponse:
    """Stage all loaded-export changes and commit them."""
    orchestrator: Orchestrator = _get_session(request)["orchestrator"]
    service = _session_history(request)
    await _emit_route_progress(
        orchestrator,
        phase="history.commit",
        current=0,
        total=1,
        detail="History commit started.",
    )
    try:
        service.stage_all()
        revision = service.commit(
            actor=body.actor,
            requirement=body.requirement_id,
            message=body.message,
        )
    except ValueError as exc:
        await _emit_route_progress(
            orchestrator,
            phase="history.commit",
            current=1,
            total=1,
            detail="History commit blocked: nothing to commit.",
            result="blocked",
        )
        raise HTTPException(
            status_code=400,
            detail={"reason": "nothing_to_commit"},
        ) from exc
    except Exception as exc:
        await _emit_route_progress(
            orchestrator,
            phase="history.commit",
            current=1,
            total=1,
            detail=f"History commit failed: {exc}",
            result="failed",
        )
        raise
    await _emit_route_progress(
        orchestrator,
        phase="history.commit",
        current=1,
        total=1,
        detail=f"History commit completed: {revision.hash}.",
        result="ok",
    )
    return JSONResponse(_revision_payload(revision))


@router.post("/history/restore")
async def restore_history(
    request: Request,
    body: HistoryRestoreBody,
) -> JSONResponse:
    """Restore one revision and refresh the loaded codebase."""
    session = _get_session(request)
    state: AgentState = session["state"]
    orchestrator: Orchestrator = session["orchestrator"]
    service = _session_history(request)
    await _emit_route_progress(
        orchestrator,
        phase="history.restore",
        current=0,
        total=1,
        detail=f"History restore started: {body.revision}.",
    )
    if service.staged_changes() or service.working_changes():
        await _emit_route_progress(
            orchestrator,
            phase="history.restore",
            current=1,
            total=1,
            detail="History restore blocked: workspace is not clean.",
            result="blocked",
        )
        raise HTTPException(
            status_code=409,
            detail={"reason": "workspace_not_clean"},
        )
    try:
        revision = service.restore(
            body.revision,
            actor="desktop",
            requirement=_session_requirement_id(state),
        )
    except RevisionNotFoundError as exc:
        await _emit_route_progress(
            orchestrator,
            phase="history.restore",
            current=1,
            total=1,
            detail=f"History restore failed: revision {exc.revision_hash} not found.",
            result="failed",
        )
        raise HTTPException(
            status_code=404,
            detail={"reason": "revision_not_found", "revision": exc.revision_hash},
        ) from exc
    except Exception as exc:
        await _emit_route_progress(
            orchestrator,
            phase="history.restore",
            current=1,
            total=1,
            detail=f"History restore failed: {exc}",
            result="failed",
        )
        raise
    try:
        codebase = await asyncio.to_thread(
            codebase_map_mod.build_codebase_map,
            Path(state.export_dir or ""),
        )
    except Exception as exc:
        await _emit_route_progress(
            orchestrator,
            phase="history.restore",
            current=1,
            total=1,
            detail=f"History restore failed while refreshing codebase: {exc}",
            result="failed",
        )
        raise
    state.codebase_map = codebase.model_dump(mode="json")
    await _emit_route_progress(
        orchestrator,
        phase="history.restore",
        current=1,
        total=1,
        detail=f"History restore completed: {revision.hash}.",
        result="ok",
    )
    return JSONResponse(_revision_payload(revision))


@router.get("/diff")
async def get_diff(request: Request) -> JSONResponse:
    session = _get_session(request)
    state: AgentState = session["state"]
    return JSONResponse({
        "created": state.created_files,
        "modified": state.modified_files,
        "generated_objects": state.generated_objects,
    })


@router.get("/test-results")
async def get_test_results(request: Request) -> JSONResponse:
    session = _get_session(request)
    state: AgentState = session["state"]
    if state.test_results is None:
        return JSONResponse({"status": "no_results"})
    return JSONResponse(state.test_results)


@router.post("/package")
async def package_full_zip(request: Request) -> JSONResponse:
    """Rebuild a full Appian ZIP from the loaded export without waiting for the agent."""
    session = _get_session(request)
    state: AgentState = session["state"]
    orchestrator: Orchestrator = session["orchestrator"]
    if not state.export_dir:
        raise HTTPException(status_code=404, detail="No export loaded.")
    workspace = settings.sentinel_workspace.resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    zip_path = workspace / f"rebuild_{state.session_id}.zip"
    await _emit_route_progress(
        orchestrator,
        phase="packaging.full_zip",
        current=0,
        total=1,
        detail="Full ZIP rebuild started.",
    )
    try:
        output = await asyncio.to_thread(
            zip_builder.build_appian_zip,
            Path(state.export_dir),
            zip_path,
            list(state.generated_objects or []),
        )
    except Exception as exc:
        await _emit_route_progress(
            orchestrator,
            phase="packaging.full_zip",
            current=1,
            total=1,
            detail=f"Full ZIP rebuild failed: {exc}",
            result="failed",
        )
        raise HTTPException(status_code=500, detail=f"ZIP rebuild failed: {exc}") from exc
    state.output_zip_path = str(output)
    await _emit_route_progress(
        orchestrator,
        phase="packaging.full_zip",
        current=1,
        total=1,
        detail=f"Full ZIP rebuilt: {output.name}.",
        result="ok",
    )
    return JSONResponse({"status": "ok", "filename": output.name, "has_output_zip": True})


@router.get("/download")
async def download_zip(request: Request) -> FileResponse:
    session = _get_session(request)
    state: AgentState = session["state"]
    orchestrator: Orchestrator = session["orchestrator"]
    if state.output_zip_path is None:
        raise HTTPException(status_code=404, detail="No output ZIP available yet.")

    path = Path(state.output_zip_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Output ZIP file not found on disk.")

    await _emit_route_progress(
        orchestrator,
        phase="download.full_zip",
        current=0,
        total=1,
        detail=f"Full ZIP download started: {path.name}.",
    )
    return FileResponse(
        path,
        media_type="application/zip",
        filename=path.name,
        background=BackgroundTask(
            _emit_route_progress,
            orchestrator,
            phase="download.full_zip",
            current=1,
            total=1,
            detail=f"Full ZIP download completed: {path.name}.",
            result="ok",
        ),
    )


@router.get("/patch")
async def download_patch(request: Request) -> FileResponse:
    """Download the patch ZIP (only the objects this story touched).

    Builds on demand from ``state.generated_objects`` if not already built.
    """
    session = _get_session(request)
    state: AgentState = session["state"]
    orchestrator: Orchestrator = session["orchestrator"]

    # Build on demand if the workflow hasn't packaged yet.
    if state.patch_zip_path is None:
        if not state.generated_objects:
            raise HTTPException(status_code=404, detail="No generated objects to package yet.")
        if not state.export_dir:
            raise HTTPException(status_code=404, detail="No export loaded.")
        workspace = settings.sentinel_workspace.resolve()
        patch_path = workspace / f"patch_{state.session_id}.zip"
        await _emit_route_progress(
            orchestrator,
            phase="packaging.patch_zip_on_demand",
            current=0,
            total=1,
            detail="On-demand patch ZIP packaging started.",
        )
        try:
            result = await asyncio.to_thread(
                patch_builder.build_patch_zip,
                Path(state.export_dir),
                state.generated_objects,
                patch_path,
                codebase=state.codebase_map,
            )
            state.patch_zip_path = result["zip_path"]
        except Exception as exc:
            logger.exception("Patch build failed")
            await _emit_route_progress(
                orchestrator,
                phase="packaging.patch_zip_on_demand",
                current=1,
                total=1,
                detail=f"On-demand patch ZIP packaging failed: {exc}",
                result="failed",
            )
            raise HTTPException(status_code=500, detail=f"Patch build failed: {exc}")
        await _emit_route_progress(
            orchestrator,
            phase="packaging.patch_zip_on_demand",
            current=1,
            total=1,
            detail="On-demand patch ZIP packaging completed.",
            result="ok",
        )

    path = Path(state.patch_zip_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Patch ZIP file not found on disk.")

    await _emit_route_progress(
        orchestrator,
        phase="download.patch_zip",
        current=0,
        total=1,
        detail=f"Patch ZIP download started: {path.name}.",
    )
    return FileResponse(
        path,
        media_type="application/zip",
        filename=path.name,
        background=BackgroundTask(
            _emit_route_progress,
            orchestrator,
            phase="download.patch_zip",
            current=1,
            total=1,
            detail=f"Patch ZIP download completed: {path.name}.",
            result="ok",
        ),
    )


@router.post("/ado/workitem")
async def fetch_ado_work_item(request: Request) -> JSONResponse:
    """Fetch an ADO work item and load it as the session's user story.

    Body: ``{"id": <work_item_id>, "org"?, "project"?, "source"?}``.
    Falls back to persisted settings for org/project/PAT/source.
    """
    session = _get_session(request)
    state: AgentState = session["state"]
    orchestrator: Orchestrator = session["orchestrator"]

    body = await request.json()
    work_item_id = str(body.get("id", "")).strip()
    if not work_item_id:
        raise HTTPException(status_code=400, detail="A work item id is required.")

    source = (body.get("source") or settings.ado_source or "pat").strip().lower()
    org = (body.get("org") or settings.ado_org).strip()
    project = (body.get("project") or settings.ado_project).strip()

    if source == "mcp":
        # The standalone desktop app resolves 'mcp' via its own ADO-MCP bridge;
        # the sidecar cannot reach the client's MCP connection.
        raise HTTPException(
            status_code=501,
            detail=(
                "ADO source is set to 'mcp'. Fetch the work item through the "
                "desktop app's ADO MCP bridge, or switch the source to 'pat'."
            ),
        )

    if not settings.ado_pat:
        raise HTTPException(status_code=400, detail="No ADO PAT configured. Add one in Settings.")

    try:
        work_item = await ado_client.get_work_item(org, project, work_item_id, settings.ado_pat)
    except Exception as exc:
        safe_error = _mask_secrets(str(exc))
        logger.error("ADO work item fetch failed: %s", safe_error)
        raise HTTPException(status_code=502, detail=f"ADO fetch failed: {safe_error}")

    # Parse into a structured user story and load into state.
    model = settings.sentinel_fast_model
    await _emit_route_progress(
        orchestrator,
        phase="llm.ado_story_parse",
        current=0,
        total=1,
        detail=f"ADO story parsing LLM call started: model {model}.",
    )
    try:
        story = await pdf_extractor.extract_user_story_from_text(
            work_item["combined_text"],
            source_id=work_item_id,
            source_kind="ado",
        )
        state.user_story = story.model_dump() if hasattr(story, "model_dump") else dict(story)
    except Exception as exc:
        safe_error = _mask_secrets(str(exc))
        logger.error("Story parse from ADO failed: %s", safe_error)
        await _emit_route_progress(
            orchestrator,
            phase="llm.ado_story_parse",
            current=1,
            total=1,
            detail=f"ADO story parsing LLM call failed: model {model}: {safe_error}",
            result="failed",
        )
        raise HTTPException(status_code=500, detail=f"Story parsing failed: {safe_error}")
    await _emit_route_progress(
        orchestrator,
        phase="llm.ado_story_parse",
        current=1,
        total=1,
        detail=f"ADO story parsing LLM call completed: model {model}.",
        result="ok",
    )

    state.add_system_message(f"Loaded ADO work item #{work_item_id}: {work_item['title']}")

    # Auto-start the workflow if the codebase is already loaded.
    if state.codebase_map and session.get("run_task") is None and state.export_dir:
        session["run_task"] = asyncio.create_task(
            orchestrator.run(Path(state.export_dir), None)
        )

    return JSONResponse({
        "status": "ok",
        "work_item": {
            "id": work_item["id"],
            "title": work_item["title"],
            "work_item_type": work_item["work_item_type"],
            "state": work_item["state"],
        },
        "story": state.user_story,
    })


# ------------------------------------------------------------------
# WebSocket endpoint (mounted at /ws, outside the /api prefix)
# ------------------------------------------------------------------

ws_router = APIRouter()


@ws_router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """Real-time chat via WebSocket."""
    token = os.environ.get("SENTINEL_API_TOKEN")
    supplied = websocket.headers.get("X-Sentinel-Token", "")
    if token and not hmac.compare_digest(supplied, token):
        await websocket.close(code=1008)
        return
    sid = websocket.query_params.get("session_id", "default")
    if sid not in _sessions:
        state = AgentState(max_iterations=settings.sentinel_max_agent_iterations)
        orchestrator = Orchestrator(state)
        _sessions[sid] = {
            "state": state,
            "orchestrator": orchestrator,
            "run_task": None,
        }

    session = _sessions[sid]
    orchestrator: Orchestrator = session["orchestrator"]

    handler = ChatWebSocket(websocket, orchestrator)
    await handler.accept()
    await handler.listen()


# ------------------------------------------------------------------
# Settings endpoints
# ------------------------------------------------------------------

_SETTINGS_FILE = Path(settings.sentinel_workspace) / "settings.json"


def _load_persisted_settings() -> dict[str, str]:
    """Load settings from the workspace JSON file and apply them to the
    global ``settings`` object so that the rest of the app picks them up."""
    if not _SETTINGS_FILE.exists():
        return {}
    try:
        data = json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
        if data.get("base_url"):
            settings.litellm_base_url = data["base_url"]
        if data.get("api_key"):
            settings.litellm_api_key = data["api_key"]
        if data.get("protocol") in {"auto", "openai", "anthropic"}:
            settings.llm_protocol = data["protocol"]
        if data.get("primary_model"):
            settings.sentinel_primary_model = data["primary_model"]
        if data.get("fast_model"):
            settings.sentinel_fast_model = data["fast_model"]
        # Azure DevOps settings
        if data.get("ado_source"):
            settings.ado_source = data["ado_source"]
        if data.get("ado_org"):
            settings.ado_org = data["ado_org"]
        if data.get("ado_project"):
            settings.ado_project = data["ado_project"]
        if data.get("ado_pat"):
            settings.ado_pat = data["ado_pat"]
        return data
    except Exception as exc:
        logger.error("Failed to load persisted settings: %s", _mask_secrets(str(exc)))
        return {}


# Load on import so that the app starts with the saved values.
_load_persisted_settings()


def _mask_key(key: str) -> str:
    """Return a masked version of an API key showing only the last 4 chars."""
    return mask_secret(key)


def _is_masked(value: str) -> bool:
    """True if *value* looks like a masked secret (came back from GET)."""
    return "*" in value


def _mask_secrets(value: str) -> str:
    """Remove configured secrets from an error message."""
    return mask_secrets(value, (settings.litellm_api_key, settings.ado_pat))


@router.get("/settings")
async def get_settings() -> JSONResponse:
    """Return the current LLM + ADO settings with secrets masked."""
    return JSONResponse({
        "base_url": settings.litellm_base_url,
        "api_key": _mask_key(settings.litellm_api_key),
        "protocol": settings.llm_protocol,
        "primary_model": settings.sentinel_primary_model,
        "fast_model": settings.sentinel_fast_model,
        "ado_source": settings.ado_source,
        "ado_org": settings.ado_org,
        "ado_project": settings.ado_project,
        "ado_pat": _mask_key(settings.ado_pat),
    })


@router.post("/settings")
async def update_settings(request: Request) -> JSONResponse:
    """Update LLM settings and persist them to workspace/settings.json."""
    body = await request.json()

    base_url = body.get("base_url", "").strip()
    api_key = body.get("api_key", "").strip()
    protocol = body.get("protocol", "").strip().lower()
    primary_model = body.get("primary_model", "").strip()
    fast_model = body.get("fast_model", "").strip()

    if base_url:
        settings.litellm_base_url = base_url
    if api_key and not _is_masked(api_key):
        settings.litellm_api_key = api_key
    if protocol:
        if protocol not in {"auto", "openai", "anthropic"}:
            raise HTTPException(
                status_code=400,
                detail="Protocol must be one of: auto, openai, anthropic.",
            )
        settings.llm_protocol = protocol
    if primary_model:
        settings.sentinel_primary_model = primary_model
    if fast_model:
        settings.sentinel_fast_model = fast_model

    # Azure DevOps settings (empty string clears; masked value is ignored)
    if "ado_source" in body and body["ado_source"].strip():
        settings.ado_source = body["ado_source"].strip()
    if "ado_org" in body:
        settings.ado_org = body["ado_org"].strip()
    if "ado_project" in body:
        settings.ado_project = body["ado_project"].strip()
    ado_pat = body.get("ado_pat", "").strip()
    if ado_pat and not _is_masked(ado_pat):
        settings.ado_pat = ado_pat

    # Persist to disk
    workspace = settings.sentinel_workspace.resolve()
    workspace.mkdir(parents=True, exist_ok=True)

    persisted: dict[str, str] = {
        "base_url": settings.litellm_base_url,
        "api_key": settings.litellm_api_key,
        "protocol": settings.llm_protocol,
        "primary_model": settings.sentinel_primary_model,
        "fast_model": settings.sentinel_fast_model,
        "ado_source": settings.ado_source,
        "ado_org": settings.ado_org,
        "ado_project": settings.ado_project,
        "ado_pat": settings.ado_pat,
    }
    _SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _SETTINGS_FILE.write_text(json.dumps(persisted, indent=2), encoding="utf-8")

    # Rebuild the LLM client so it uses the new base_url / api_key
    from appian_sentinel.analyzer.llm_client import llm as _llm_singleton
    _llm_singleton.reconfigure()

    return JSONResponse({
        "status": "ok",
        "base_url": settings.litellm_base_url,
        "api_key": _mask_key(settings.litellm_api_key),
        "protocol": settings.llm_protocol,
        "primary_model": settings.sentinel_primary_model,
        "fast_model": settings.sentinel_fast_model,
        "ado_source": settings.ado_source,
        "ado_org": settings.ado_org,
        "ado_project": settings.ado_project,
        "ado_pat": _mask_key(settings.ado_pat),
    })


@router.get("/settings/test")
async def test_settings() -> JSONResponse:
    """Test the LLM connection by making a simple chat completion call."""
    if "default" not in _sessions:
        state = AgentState(max_iterations=settings.sentinel_max_agent_iterations)
        _sessions["default"] = {
            "state": state,
            "orchestrator": Orchestrator(state),
            "run_task": None,
        }
    orchestrator: Orchestrator = _sessions["default"]["orchestrator"]
    model = settings.sentinel_fast_model
    await _emit_route_progress(
        orchestrator,
        phase="settings.test_connection",
        current=0,
        total=1,
        detail=f"Settings connection test started: model {model}.",
    )
    try:
        from appian_sentinel.analyzer.llm_client import llm as _llm_singleton

        content = await _llm_singleton.chat(
            [{"role": "user", "content": "Say hello in one word."}],
            model=model,
            max_tokens=16,
            timeout=15,
        )
        await _emit_route_progress(
            orchestrator,
            phase="settings.test_connection",
            current=1,
            total=1,
            detail=f"Settings connection test completed: model {model}.",
            result="ok",
        )
        return JSONResponse({
            "status": "ok",
            "message": f"Connection successful. Model responded: {content.strip()}",
            "model": model,
        })
    except Exception as exc:
        # Never log the traceback here: provider errors embed the outbound request,
        # including the Authorization header, so exc_info would write the API key to disk.
        logger.error("LLM connection test failed: %s", _mask_secrets(str(exc)))
        await _emit_route_progress(
            orchestrator,
            phase="settings.test_connection",
            current=1,
            total=1,
            detail=f"Settings connection test failed: model {model}: {_mask_secrets(str(exc))}",
            result="failed",
        )
        return JSONResponse(
            status_code=502,
            content={
                "status": "error",
                "message": f"Connection failed: {_mask_secrets(str(exc))}",
            },
        )


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _session_object(
    state: AgentState,
    uuid: str,
) -> tuple[dict[str, Any], Path, Path]:
    if state.codebase_map is None or not state.export_dir:
        raise HTTPException(status_code=404, detail="Codebase not loaded yet.")
    obj = state.codebase_map.get("objects", {}).get(uuid)
    if not isinstance(obj, dict):
        raise HTTPException(status_code=404, detail=f"Object {uuid} not found.")
    export_dir = Path(state.export_dir).resolve()
    raw_path = Path(str(obj.get("file_path", "")))
    path = (raw_path if raw_path.is_absolute() else export_dir / raw_path).resolve()
    if not path.is_file() or not path.is_relative_to(export_dir):
        raise HTTPException(
            status_code=400,
            detail={"reason": "object_file_outside_export"},
        )
    return obj, export_dir, path


def _session_history(request: Request) -> WorkspaceHistoryService:
    state: AgentState = _get_session(request)["state"]
    if not state.export_dir:
        raise HTTPException(status_code=404, detail="Codebase not loaded yet.")
    return WorkspaceHistoryService(Path(state.export_dir))


def _session_requirement_id(state: AgentState) -> str:
    story = state.user_story or {}
    value = story.get("source_id", "") if isinstance(story, dict) else ""
    return str(value)


def _revision_payload(revision: Revision) -> dict[str, Any]:
    return {
        "hash": revision.hash,
        "message": revision.message,
        "actor": revision.actor,
        "timestamp": revision.timestamp.isoformat(),
        "requirement_id": revision.requirement,
    }


def _extract_zip(zip_path: Path, dest: Path) -> None:
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(dest)
