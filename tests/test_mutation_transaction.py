from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from appian_sentinel.services.mutation_transaction import (
    MutationTransaction,
    TransactionError,
)


def _export(root: Path) -> Path:
    export = root / "export"
    (export / "META-INF").mkdir(parents=True)
    (export / "content").mkdir()
    payload = export / "content" / "rule-1"
    (payload / "nested").mkdir(parents=True)
    (export / "content" / "rule-1.xml").write_bytes(b"<rule><name>APP_Rule</name></rule>")
    (payload / "body.txt").write_bytes(b"payload body\r\nline two\n")
    (payload / "nested" / "blob.bin").write_bytes(bytes(range(256)))
    (export / "META-INF" / "export.log").write_bytes(b'Success (1):\nrule 1 rule-1 "APP_Rule"\n')
    return export


def _snapshot(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _temp_siblings(root: Path) -> list[Path]:
    return [path for path in root.parent.iterdir() if path.name.startswith(f".{root.name}.txn-")]


def _fail_after(limit: int):
    calls: list[Path] = []

    def hook(path: Path) -> None:
        calls.append(path)
        if len(calls) >= limit:
            raise RuntimeError("injected failure")

    return hook


def test_commit_applies_writes_and_recursive_delete(tmp_path: Path) -> None:
    export = _export(tmp_path)
    xml = export / "content" / "rule-1.xml"
    payload = export / "content" / "rule-1"
    log = export / "META-INF" / "export.log"

    transaction = MutationTransaction(export)
    transaction.write(xml, b"<rule><name>APP_Renamed</name></rule>")
    transaction.delete(payload)
    transaction.write(log, b'Success (1):\nrule 1 rule-1 "APP_Renamed"\n')
    changed = transaction.commit()

    assert changed == [xml.resolve(), payload.resolve(), log.resolve()]
    assert xml.read_bytes() == b"<rule><name>APP_Renamed</name></rule>"
    assert not payload.exists()
    assert log.read_bytes() == b'Success (1):\nrule 1 rule-1 "APP_Renamed"\n'
    assert _temp_siblings(export) == []


def test_failure_after_file_replacement_restores_bytes(tmp_path: Path) -> None:
    export = _export(tmp_path)
    before = _snapshot(export)

    transaction = MutationTransaction(export, on_applied=_fail_after(1))
    transaction.write(export / "content" / "rule-1.xml", b"corrupted")
    transaction.write(export / "META-INF" / "export.log", b"corrupted log")

    with pytest.raises(RuntimeError, match="injected failure"):
        transaction.commit()

    assert _snapshot(export) == before
    assert transaction.changed_paths == []
    assert _temp_siblings(export) == []


def test_failure_after_directory_deletion_restores_tree(tmp_path: Path) -> None:
    export = _export(tmp_path)
    before = _snapshot(export)
    payload = export / "content" / "rule-1"

    transaction = MutationTransaction(export, on_applied=_fail_after(2))
    transaction.write(export / "content" / "rule-1.xml", b"<rule><name>Gone</name></rule>")
    transaction.delete(payload)
    transaction.write(export / "META-INF" / "export.log", b"never applied")

    with pytest.raises(RuntimeError, match="injected failure"):
        transaction.commit()

    assert _snapshot(export) == before
    assert (payload / "nested" / "blob.bin").read_bytes() == bytes(range(256))
    assert _temp_siblings(export) == []


def test_rollback_removes_created_file_and_parent_dirs(tmp_path: Path) -> None:
    export = _export(tmp_path)
    before = _snapshot(export)
    new_file = export / "site" / "pages" / "site-1.xml"

    transaction = MutationTransaction(export, on_applied=_fail_after(1))
    transaction.write(new_file, b"<site/>")

    with pytest.raises(RuntimeError, match="injected failure"):
        transaction.commit()

    assert _snapshot(export) == before
    assert not (export / "site").exists()
    assert _temp_siblings(export) == []


def test_context_manager_rolls_back_on_error(tmp_path: Path) -> None:
    export = _export(tmp_path)
    before = _snapshot(export)

    with pytest.raises(ValueError):
        with MutationTransaction(export) as transaction:
            transaction.write(export / "content" / "rule-1.xml", b"partial")
            transaction.delete(export / "content" / "rule-1")
            raise ValueError("caller aborted")

    assert _snapshot(export) == before
    assert _temp_siblings(export) == []


def test_rejects_escaping_paths_and_missing_delete(tmp_path: Path) -> None:
    export = _export(tmp_path)

    transaction = MutationTransaction(export)
    with pytest.raises(TransactionError):
        transaction.write(tmp_path / "outside.xml", b"x")

    transaction.delete(export / "content" / "absent.xml")
    with pytest.raises(TransactionError):
        transaction.commit()
    assert _temp_siblings(export) == []
