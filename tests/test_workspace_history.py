from __future__ import annotations

from pathlib import Path

import pytest

from appian_sentinel.models.workspace import FileChangeKind
from appian_sentinel.services.workspace import (
    PathEscapeError,
    RevisionConflictError,
    WorkspaceHistoryService,
)


def _service(tmp_path: Path) -> WorkspaceHistoryService:
    return WorkspaceHistoryService(tmp_path)


def test_commit_records_actor_requirement_timestamp_and_hash(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    baseline = svc.create_baseline(actor="system", requirement="REQ-24")
    (tmp_path / "content").mkdir()
    (tmp_path / "content" / "uuid-1.xml").write_text("rule v1\n", encoding="utf-8")
    staged = svc.stage("content/uuid-1.xml")
    assert staged.kind is FileChangeKind.ADDED

    revision = svc.commit(
        actor="agent",
        requirement="US-1",
        message="add rule",
        expected_revision=baseline.hash,
    )

    assert revision.parent == baseline.hash
    assert revision.actor == "agent"
    assert revision.requirement == "US-1"
    assert revision.timestamp.tzinfo is not None
    assert revision.hash
    assert svc.head() == revision.hash
    assert not svc.staged_changes()
    stored = (tmp_path / ".history" / "revisions" / f"{revision.hash}.json").read_text(encoding="utf-8")
    assert "password" not in stored
    assert "api_key" not in stored
    assert "rule v1" not in stored


def test_expected_revision_conflict(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    baseline = svc.create_baseline(actor="system", requirement="REQ-24")
    (tmp_path / "content").mkdir()
    path = tmp_path / "content" / "a.xml"
    path.write_text("one\n", encoding="utf-8")
    svc.stage("content/a.xml")
    first = svc.commit(actor="a", requirement="r1", message="one", expected_revision=baseline.hash)
    path.write_text("two\n", encoding="utf-8")
    svc.stage("content/a.xml")
    with pytest.raises(RevisionConflictError) as exc:
        svc.commit(actor="b", requirement="r2", message="stale", expected_revision=baseline.hash)
    assert exc.value.expected == baseline.hash
    assert exc.value.actual == first.hash
    assert svc.head() == first.hash


@pytest.mark.parametrize(
    "unsafe",
    [
        "../outside.txt",
        "content/../../outside.txt",
        "..\\outside.txt",
        "/absolute.txt",
        "C:/absolute.txt",
    ],
)
def test_path_escape_rejection(tmp_path: Path, unsafe: str) -> None:
    svc = _service(tmp_path)
    svc.create_baseline(actor="system", requirement="REQ-24")
    with pytest.raises(PathEscapeError, match="Path escapes workspace"):
        svc.stage(unsafe)
    assert not (tmp_path.parent / "outside.txt").exists()


def test_diff_object_and_file(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    baseline = svc.create_baseline(actor="system", requirement="REQ-24")
    obj_dir = tmp_path / "content"
    obj_dir.mkdir()
    (obj_dir / "uuid-1.xml").write_text("before\n", encoding="utf-8")
    (tmp_path / "META-INF").mkdir()
    (tmp_path / "META-INF" / "export.log").write_text("alpha\n", encoding="utf-8")
    svc.stage("content/uuid-1.xml")
    svc.stage("META-INF/export.log")
    rev = svc.commit(actor="agent", requirement="US-2", message="add", expected_revision=baseline.hash)

    diffs = {item.path: item for item in svc.diff(baseline.hash, rev.hash)}
    assert diffs["content/uuid-1.xml"].kind is FileChangeKind.ADDED
    assert diffs["content/uuid-1.xml"].object_id == "uuid-1"
    assert "before" in diffs["content/uuid-1.xml"].unified_diff
    assert diffs["META-INF/export.log"].object_id is None
    assert "alpha" in diffs["META-INF/export.log"].unified_diff

    (obj_dir / "uuid-1.xml").write_text("after\n", encoding="utf-8")
    svc.stage("content/uuid-1.xml")
    rev2 = svc.commit(actor="agent", requirement="US-2", message="edit", expected_revision=rev.hash)
    edit = svc.diff(rev.hash, rev2.hash)[0]
    assert edit.kind is FileChangeKind.MODIFIED
    assert "-before" in edit.unified_diff
    assert "+after" in edit.unified_diff


def test_restore_creates_new_revision_with_exact_bytes(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    baseline = svc.create_baseline(actor="system", requirement="REQ-24")
    payload = b"png\x00\xff\xfe binary"
    (tmp_path / "content").mkdir()
    path = tmp_path / "content" / "asset.bin"
    path.write_bytes(payload)
    svc.stage("content/asset.bin")
    saved = svc.commit(actor="agent", requirement="US-3", message="bin", expected_revision=baseline.hash)

    path.write_bytes(b"changed")
    svc.stage("content/asset.bin")
    dirty = svc.commit(actor="agent", requirement="US-3", message="change", expected_revision=saved.hash)
    assert path.read_bytes() == b"changed"

    restored = svc.restore(
        saved.hash,
        actor="agent",
        requirement="US-3",
        message="rollback",
        expected_revision=dirty.hash,
    )
    assert restored.hash != saved.hash
    assert restored.parent == dirty.hash
    assert restored.tree_hash == saved.tree_hash
    assert path.read_bytes() == payload
    assert svc.head() == restored.hash


def test_baseline_excludes_settings_and_output_artifacts(tmp_path: Path) -> None:
    (tmp_path / "content").mkdir()
    (tmp_path / "content" / "rule.xml").write_text("<rule />", encoding="utf-8")
    (tmp_path / "settings.json").write_text('{"api_key":"secret"}', encoding="utf-8")
    (tmp_path / "output.zip").write_bytes(b"secret output")

    svc = _service(tmp_path)
    baseline = svc.create_baseline(actor="system", requirement="REQ-24")

    assert set(baseline.files) == {"content/rule.xml"}
    blob_bytes = b"".join(
        path.read_bytes()
        for path in (tmp_path / ".history" / "blobs").iterdir()
        if path.is_file()
    )
    assert b"secret" not in blob_bytes
