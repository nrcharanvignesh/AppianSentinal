from __future__ import annotations

import hashlib
import re
import zipfile
from pathlib import Path

import pytest

from appian_sentinel.packager.patch_builder import build_patch_zip
from appian_sentinel.packager.zip_builder import build_appian_zip
from appian_sentinel.parser.codebase_map import parse_export_log
from appian_sentinel.parser.xml_parser import parse_appian_xml

SUPPORTED_FILES = {
    "content": "one.xml",
    "processModel": "two.xml",
    "recordType": "three.xml",
    "datatype": "four.xsd",
    "webApi": "five.xml",
    "connectedSystem": "six.xml",
    "site": "seven.xml",
    "group": "eight.xml",
    "dataStore": "nine.xml",
}
REAL_EXPORT = Path(__file__).parents[1] / "appian_export"
REAL_DOCUMENT_UUID = "_a-0000eb25-1c2c-8000-9bab-011c48011c48_7946"
REAL_DEPENDENT_UUID = "0021b392-9971-4af2-887f-755435c2b72f"
REAL_DOCUMENT_FILE = "content/_a-0000eb25-1c2c-8000-9bab-011c48011c48_7946.xml"
REAL_DEPENDENT_FILE = "content/0021b392-9971-4af2-887f-755435c2b72f.xml"


def _make_export(root: Path) -> list[dict[str, str]]:
    meta = root / "META-INF"
    meta.mkdir(parents=True)
    (meta / "MANIFEST.MF").write_bytes(
        b"Manifest-Version: 1.0\r\nAppian-Version: 24.2.100.0\r\nCustom-Field: keep\r\n\r\n"
    )
    refs: list[dict[str, str]] = []
    log_lines: list[str] = []
    for index, (directory, filename) in enumerate(SUPPORTED_FILES.items(), start=1):
        uuid = f"_a-fixture-{index:02d}"
        path = root / directory / filename
        path.parent.mkdir(parents=True)
        path.write_text(f"<object><uuid>{uuid}</uuid><value>{index}</value></object>", encoding="utf-8")
        refs.append(
            {
                "uuid": uuid,
                "name": f"Object {index}",
                "type": directory,
                "file_path": str(path),
            }
        )
        log_lines.append(f'{directory} {index} {uuid} "Object {index}"')
    (meta / "export.log").write_text(
        "\n".join([f"Success ({len(log_lines)}):", *log_lines, "", "2026-01-01 DEBUG source"]) + "\n",
        encoding="utf-8",
    )
    app = root / "application" / "app.xml"
    app.parent.mkdir()
    app.write_text("<application><name>Fixture</name></application>", encoding="utf-8")
    return refs


def _snapshot(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_full_zip_excludes_internal_workspace_history(tmp_path: Path) -> None:
    """The .history store lives inside the export dir but is not Appian content."""
    source = tmp_path / "source"
    refs = _make_export(source)
    history_blob = source / ".history" / "blobs" / "deadbeef"
    history_blob.parent.mkdir(parents=True)
    history_blob.write_bytes(b"internal snapshot")
    (source / ".history" / "index.json").write_text("{}", encoding="utf-8")

    output = tmp_path / "full.zip"
    build_appian_zip(source, output, list(refs[:1]))

    with zipfile.ZipFile(output) as archive:
        names = archive.namelist()
    assert not [name for name in names if name.startswith(".history")], names
    # Real export content is still packaged.
    assert "META-INF/export.log" in names
    assert "content/one.xml" in names


def test_full_zip_is_pure_and_preserves_manifest_bytes(tmp_path: Path) -> None:
    source = tmp_path / "source"
    refs = _make_export(source)
    before = _snapshot(source)
    output = tmp_path / "full.zip"
    new_uuid = "_a-created-10"

    build_appian_zip(
        source,
        output,
        [*refs[:1], {"uuid": new_uuid, "name": "Created", "type": "rule", "action": "create"}],
    )

    assert _snapshot(source) == before
    with zipfile.ZipFile(output) as archive:
        assert archive.read("META-INF/MANIFEST.MF") == (source / "META-INF" / "MANIFEST.MF").read_bytes()
        log = archive.read("META-INF/export.log").decode()
    lines = log.splitlines()
    assert lines[0] == "Success (10):"
    assert any(re.fullmatch(rf"rule 0 {re.escape(new_uuid)} \"Created\"", line) for line in lines)


def test_patch_supports_all_directories_and_document_payload(tmp_path: Path) -> None:
    source = tmp_path / "source"
    refs = _make_export(source)
    document = refs[0]
    document["type"] = "document"
    payload = Path(document["file_path"]).with_suffix("") / "payload.bin"
    payload.parent.mkdir()
    payload.write_bytes(b"\x00Appian document\xff")
    output = tmp_path / "patch.zip"

    result = build_patch_zip(source, refs, output, dependency_mode="warn")

    assert result["missing"] == []
    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
        for directory, filename in SUPPORTED_FILES.items():
            assert f"{directory}/{filename}" in names
        assert "content/one/payload.bin" in names
        assert archive.read("content/one/payload.bin") == payload.read_bytes()
        assert archive.read("META-INF/MANIFEST.MF") == (source / "META-INF" / "MANIFEST.MF").read_bytes()
        assert archive.read("META-INF/export.log").decode().startswith("Success (9):\n")


def test_patch_warn_strict_and_dependency_closure_modes(tmp_path: Path) -> None:
    source = tmp_path / "source"
    refs = _make_export(source)
    selected, dependency = refs[:2]
    codebase = {
        "objects": {
            selected["uuid"]: selected,
            dependency["uuid"]: dependency,
        },
        "dependencies": {selected["uuid"]: {dependency["uuid"]}},
        "uuid_to_name": {
            selected["uuid"]: selected["name"],
            dependency["uuid"]: dependency["name"],
        },
    }

    warned = build_patch_zip(
        source,
        [selected],
        tmp_path / "warn.zip",
        codebase=codebase,
        dependency_mode="warn",
    )
    assert len(warned["dependency_warnings"]) == 1

    with pytest.raises(ValueError, match="Patch is incomplete"):
        build_patch_zip(
            source,
            [selected],
            tmp_path / "strict.zip",
            codebase=codebase,
            dependency_mode="strict",
        )
    assert not (tmp_path / "strict.zip").exists()

    closed = build_patch_zip(
        source,
        [selected],
        tmp_path / "closed.zip",
        codebase=codebase,
        dependency_mode="dependency-closure",
    )
    assert {item["uuid"] for item in closed["included"]} == {selected["uuid"], dependency["uuid"]}
    assert closed["dependency_warnings"] == []


def test_patch_registers_new_uuid_backed_object(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _make_export(source)
    uuid = "_a-new-object"
    path = source / "content" / f"{uuid}.xml"
    path.write_text(f"<contentHaul><rule><uuid>{uuid}</uuid></rule></contentHaul>", encoding="utf-8")

    build_patch_zip(
        source,
        [{"uuid": uuid, "name": "APP_New", "type": "rule", "file_path": str(path)}],
        tmp_path / "new.zip",
        dependency_mode="warn",
    )

    with zipfile.ZipFile(tmp_path / "new.zip") as archive:
        log = archive.read("META-INF/export.log").decode()
    assert log == f'Success (1):\nrule 0 {uuid} "APP_New"\n'


@pytest.mark.skipif(
    not REAL_EXPORT.is_dir(),
    reason="real Appian reference export is not available",
)
def test_patch_contains_exact_real_change_set_and_warns_for_dependencies(
    tmp_path: Path,
) -> None:
    uuid_to_name = parse_export_log(REAL_EXPORT / "META-INF" / "export.log")
    dependent_path = REAL_EXPORT / REAL_DEPENDENT_FILE
    dependent = parse_appian_xml(dependent_path)
    assert dependent is not None
    dependency_uuids = {
        uuid
        for uuid in dependent.get_uuid_references()
        if uuid in uuid_to_name
    }
    assert dependency_uuids

    refs = [
        {
            "uuid": REAL_DOCUMENT_UUID,
            "name": uuid_to_name[REAL_DOCUMENT_UUID],
            "type": "document",
            "file_path": str(REAL_EXPORT / REAL_DOCUMENT_FILE),
        },
        {
            "uuid": REAL_DEPENDENT_UUID,
            "name": uuid_to_name[REAL_DEPENDENT_UUID],
            "type": "expression_rule",
            "file_path": str(dependent_path),
        },
    ]
    codebase = {
        "objects": {},
        "dependencies": {REAL_DEPENDENT_UUID: dependency_uuids},
        "uuid_to_name": uuid_to_name,
    }
    output = tmp_path / "real-change-set.zip"
    result = build_patch_zip(
        REAL_EXPORT,
        refs,
        output,
        codebase=codebase,
        dependency_mode="warn",
        reindex_if_needed=False,
    )

    expected = {
        path.relative_to(REAL_EXPORT).as_posix()
        for path in (REAL_EXPORT / "META-INF").iterdir()
        if path.is_file()
    }
    expected.update(
        path.relative_to(REAL_EXPORT).as_posix()
        for path in (REAL_EXPORT / "application").glob("*.xml")
    )
    expected.update({REAL_DOCUMENT_FILE, REAL_DEPENDENT_FILE})
    document_payload_dir = (REAL_EXPORT / REAL_DOCUMENT_FILE).with_suffix("")
    expected.update(
        path.relative_to(REAL_EXPORT).as_posix()
        for path in document_payload_dir.rglob("*")
        if path.is_file()
    )

    assert result["missing"] == []
    assert {
        warning["missing_ref"]
        for warning in result["dependency_warnings"]
    } == dependency_uuids
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist()) == expected
