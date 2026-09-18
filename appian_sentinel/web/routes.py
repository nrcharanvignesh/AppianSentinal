from __future__ import annotations

import asyncio
import json
import logging
import shutil
import zipfile
from pathlib import Path
from typing import Any

import aiofiles
from fastapi import APIRouter, File, HTTPException, Request, UploadFile, WebSocket
from fastapi.responses import FileResponse, JSONResponse

from appian_sentinel.agent.orchestrator import Orchestrator
from appian_sentinel.agent.state import AgentState, ChatMessage, MessageType
from appian_sentinel.analyzer import pdf_extractor
from appian_sentinel.config import settings
from appian_sentinel.integrations import ado_client
from appian_sentinel.packager import patch_builder
from appian_sentinel.parser import codebase_map as codebase_map_mod
from appian_sentinel.web.websocket import ChatWebSocket

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


@router.get("/health")
async def health() -> JSONResponse:
    """Liveness probe used by the Electron shell to know the sidecar is up."""
    return JSONResponse({"status": "ok"})


# ---------------------------------------------------------------------------
# In-memory session store.  For a production deployment this would be backed
# by Redis or a database; for the single-user Sentinel scenario keeping it
# in-process is fine.
# ---------------------------------------------------------------------------
_sessions: dict[str, dict[str, Any]] = {}


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

    # Helper: push a progress event to the client via WebSocket
    async def _push_progress(phase: str, current: int, total: int, detail: str) -> None:
        ws_callback = getattr(orchestrator, "_on_message", None)
        if ws_callback is not None:
            msg = ChatMessage(
                role="system",
                content=detail,
                message_type=MessageType.STATUS,
                metadata={"progress": True, "phase": phase, "current": current, "total": total},
            )
            try:
                await ws_callback(msg)
            except Exception:
                pass

    await _push_progress("upload", 0, 1, f"Saving {file.filename}…")

    # Save uploaded file
    zip_path = workspace / file.filename
    async with aiofiles.open(zip_path, "wb") as f:
        content = await file.read()
        await f.write(content)

    # Extract
    await _push_progress("extract", 0, 1, "Extracting ZIP archive…")
    try:
        export_dir = workspace / f"export_{state.session_id}"
        if export_dir.exists():
            shutil.rmtree(export_dir)
        export_dir.mkdir(parents=True)

        await asyncio.to_thread(_extract_zip, zip_path, export_dir)
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="Uploaded file is not a valid ZIP.")

    await _push_progress("extract", 1, 1, "ZIP extracted successfully.")

    # Build codebase map with progress reporting
    loop = asyncio.get_event_loop()

    def _sync_progress(phase: str, current: int, total: int, detail: str) -> None:
        asyncio.run_coroutine_threadsafe(
            _push_progress(phase, current, total, detail), loop
        )

    try:
        codebase = await asyncio.to_thread(
            codebase_map_mod.build_codebase_map, export_dir, _sync_progress
        )
    except Exception as exc:
        logger.exception("Failed to build codebase map")
        raise HTTPException(status_code=500, detail=f"Codebase parsing failed: {exc}")

    codebase_dict = codebase.model_dump(mode="json") if hasattr(codebase, "model_dump") else codebase
    state.codebase_map = codebase_dict
    state.export_dir = str(export_dir)
    orchestrator._export_dir = export_dir

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
    async with aiofiles.open(story_path, "wb") as f:
        content = await file.read()
        await f.write(content)

    try:
        story = await pdf_extractor.extract_user_story(story_path)
        state.user_story = story.model_dump() if hasattr(story, "model_dump") else dict(story)
        state.story_path = str(story_path)
    except Exception as exc:
        logger.exception("Story parsing failed")
        raise HTTPException(status_code=500, detail=f"Story parsing failed: {exc}")

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


@router.get("/download")
async def download_zip(request: Request) -> FileResponse:
    session = _get_session(request)
    state: AgentState = session["state"]
    if state.output_zip_path is None:
        raise HTTPException(status_code=404, detail="No output ZIP available yet.")

    path = Path(state.output_zip_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Output ZIP file not found on disk.")

    return FileResponse(
        path,
        media_type="application/zip",
        filename=path.name,
    )


@router.get("/patch")
async def download_patch(request: Request) -> FileResponse:
    """Download the patch ZIP (only the objects this story touched).

    Builds on demand from ``state.generated_objects`` if not already built.
    """
    session = _get_session(request)
    state: AgentState = session["state"]

    # Build on demand if the workflow hasn't packaged yet.
    if state.patch_zip_path is None:
        if not state.generated_objects:
            raise HTTPException(status_code=404, detail="No generated objects to package yet.")
        if not state.export_dir:
            raise HTTPException(status_code=404, detail="No export loaded.")
        workspace = settings.sentinel_workspace.resolve()
        patch_path = workspace / f"patch_{state.session_id}.zip"
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
            raise HTTPException(status_code=500, detail=f"Patch build failed: {exc}")

    path = Path(state.patch_zip_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Patch ZIP file not found on disk.")

    return FileResponse(path, media_type="application/zip", filename=path.name)


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
        logger.exception("ADO work item fetch failed")
        raise HTTPException(status_code=502, detail=f"ADO fetch failed: {exc}")

    # Parse into a structured user story and load into state.
    try:
        story = await pdf_extractor.extract_user_story_from_text(work_item["combined_text"])
        state.user_story = story.model_dump() if hasattr(story, "model_dump") else dict(story)
    except Exception as exc:
        logger.exception("Story parse from ADO failed")
        raise HTTPException(status_code=500, detail=f"Story parsing failed: {exc}")

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
    except Exception:
        logger.exception("Failed to load persisted settings")
        return {}


# Load on import so that the app starts with the saved values.
_load_persisted_settings()


def _mask_key(key: str) -> str:
    """Return a masked version of an API key showing only the last 4 chars."""
    if not key or len(key) <= 4:
        return key
    return "*" * (len(key) - 4) + key[-4:]


def _is_masked(value: str) -> bool:
    """True if *value* looks like a masked secret (came back from GET)."""
    return "*" in value


@router.get("/settings")
async def get_settings() -> JSONResponse:
    """Return the current LLM + ADO settings with secrets masked."""
    return JSONResponse({
        "base_url": settings.litellm_base_url,
        "api_key": _mask_key(settings.litellm_api_key),
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
    primary_model = body.get("primary_model", "").strip()
    fast_model = body.get("fast_model", "").strip()

    if base_url:
        settings.litellm_base_url = base_url
    if api_key:
        settings.litellm_api_key = api_key
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
    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            base_url=settings.litellm_base_url,
            api_key=settings.litellm_api_key or "sk-placeholder",
        )
        response = await client.chat.completions.create(
            model=settings.sentinel_fast_model,
            messages=[{"role": "user", "content": "Say hello in one word."}],
            max_tokens=16,
            timeout=15,
        )
        content = response.choices[0].message.content or ""
        return JSONResponse({
            "status": "ok",
            "message": f"Connection successful. Model responded: {content.strip()}",
            "model": settings.sentinel_fast_model,
        })
    except Exception as exc:
        logger.exception("LLM connection test failed")
        return JSONResponse(
            status_code=502,
            content={
                "status": "error",
                "message": f"Connection failed: {exc}",
            },
        )


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _extract_zip(zip_path: Path, dest: Path) -> None:
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(dest)
