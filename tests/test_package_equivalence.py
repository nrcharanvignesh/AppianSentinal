from __future__ import annotations

import hashlib
import os
import shutil
import zipfile
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from appian_sentinel.models.appian_objects import AppianObject, ExpressionRule, Interface
from appian_sentinel.packager.zip_builder import build_appian_zip
from appian_sentinel.parser import xml_parser
from appian_sentinel.parser.codebase_map import build_codebase_map
from appian_sentinel.parser.sail_diagnostics import analyze_sail
from appian_sentinel.testing.synthetic_export import generate_synthetic_export

REPOSITORY_ROOT = Path(__file__).parents[1]
SLIM_FIXTURE = REPOSITORY_ROOT / "tests" / "fixtures" / "reference_export"
CORPUS_PATH = REPOSITORY_ROOT / "appian_export"
METADATA_PATHS = ("META-INF/MANIFEST.MF", "META-INF/export.log")
SYNTHETIC_SCALE_OBJECTS = 300


def _file_inventory(root: Path) -> set[str]:
    return {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    }


def _file_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _payload_hashes(root: Path, objects: dict[str, Any]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for obj in objects.values():
        object_path = root / obj.file_path
        payload_dir = object_path.with_suffix("")
        if not payload_dir.is_dir():
            continue
        for payload in payload_dir.rglob("*"):
            if payload.is_file():
                relative_path = payload.relative_to(root).as_posix()
                hashes[relative_path] = hashlib.sha256(payload.read_bytes()).hexdigest()
    return hashes


def _assert_package_equivalence(source: Path, tmp_path: Path) -> dict[str, Any]:
    original = build_codebase_map(source)
    output_zip = tmp_path / "rebuilt.zip"
    rebuilt_dir = tmp_path / "rebuilt"

    build_appian_zip(source, output_zip, [])
    with zipfile.ZipFile(output_zip) as archive:
        archive.extractall(rebuilt_dir)
    rebuilt = build_codebase_map(rebuilt_dir)

    original_types = Counter(obj.object_type.value for obj in original.objects.values())
    rebuilt_types = Counter(obj.object_type.value for obj in rebuilt.objects.values())
    original_files = _file_inventory(source)
    rebuilt_files = _file_inventory(rebuilt_dir)
    original_payloads = _payload_hashes(source, original.objects)
    rebuilt_payloads = _payload_hashes(rebuilt_dir, rebuilt.objects)

    assert len(rebuilt.objects) == len(original.objects)
    assert rebuilt_types == original_types
    assert set(rebuilt.objects) == set(original.objects)
    assert len(rebuilt_files) == len(original_files)
    assert rebuilt_files == original_files
    for relative_path in METADATA_PATHS:
        assert (rebuilt_dir / relative_path).read_bytes() == (source / relative_path).read_bytes()
    assert rebuilt_payloads == original_payloads

    return {
        "objects": len(original.objects),
        "types": dict(sorted(original_types.items())),
        "files": len(original_files),
        "document_payloads": len(original_payloads),
    }


def _prepared_slim_fixture(tmp_path: Path) -> Path:
    source = tmp_path / "slim_source"
    shutil.copytree(SLIM_FIXTURE, source)
    meta = source / "META-INF"
    meta.mkdir()
    (meta / "MANIFEST.MF").write_bytes(
        b"Manifest-Version: 1.0\r\nAppian-Version: 26.6.0\r\n\r\n"
    )
    (meta / "export.log").write_bytes(b"Success (0):\r\n")
    return source


def _counting_reference_method(
    original: Callable[[AppianObject], set[str]],
    counter: list[int],
) -> Callable[[AppianObject], set[str]]:
    def counted(obj: AppianObject) -> set[str]:
        counter[0] += 1
        return original(obj)

    return counted


def _counting_xml_parser(
    original: Callable[[Path], Any],
    counter: list[int],
) -> Callable[[Path], Any]:
    def counted(path: Path) -> Any:
        counter[0] += 1
        return original(path)

    return counted


def test_slim_export_rebuild_is_equivalent(tmp_path: Path) -> None:
    metrics = _assert_package_equivalence(_prepared_slim_fixture(tmp_path), tmp_path)
    assert metrics["objects"] == 7


def test_synthetic_export_is_deterministic(tmp_path: Path) -> None:
    first = generate_synthetic_export(tmp_path / "first", 55, seed=23)
    second = generate_synthetic_export(tmp_path / "second", 55, seed=23)

    assert first.type_counts == second.type_counts
    assert _file_bytes(first.root) == _file_bytes(second.root)


def test_synthetic_scale_inventory_dependencies_and_sail(tmp_path: Path) -> None:
    generated = generate_synthetic_export(
        tmp_path / "synthetic",
        SYNTHETIC_SCALE_OBJECTS,
        seed=29,
    )
    codebase = build_codebase_map(generated.root)
    parsed_types = Counter(obj.object_type.value for obj in codebase.objects.values())
    known_uuids = set(codebase.objects) | set(codebase.uuid_to_name)

    assert codebase.scanned_files == SYNTHETIC_SCALE_OBJECTS
    assert not codebase.parse_failures
    assert len(codebase.objects) == SYNTHETIC_SCALE_OBJECTS
    assert dict(sorted(parsed_types.items())) == generated.type_counts
    assert sum(len(refs) for refs in codebase.dependencies.values()) >= 150
    assert any(len(dependents) > 1 for dependents in codebase.reverse_dependencies.values())
    for obj in codebase.objects.values():
        if isinstance(obj, (ExpressionRule, Interface)):
            assert analyze_sail(obj.definition, known_uuids=known_uuids).errors == []


def test_synthetic_scale_work_is_linear(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file_reads = [0]
    node_visits = [0]
    original_xml_parser = xml_parser._parse_xml_file
    monkeypatch.setattr(
        xml_parser,
        "_parse_xml_file",
        _counting_xml_parser(original_xml_parser, file_reads),
    )
    for object_class in AppianObject.__subclasses__():
        original_method = object_class.get_uuid_references
        monkeypatch.setattr(
            object_class,
            "get_uuid_references",
            _counting_reference_method(original_method, node_visits),
        )

    measurements: list[tuple[int, int]] = []
    for object_count in (150, 300):
        file_reads[0] = 0
        node_visits[0] = 0
        generated = generate_synthetic_export(
            tmp_path / f"synthetic_{object_count}",
            object_count,
            seed=31,
        )
        build_codebase_map(generated.root)
        measurements.append((file_reads[0], node_visits[0]))

    assert measurements == [(150, 150), (300, 300)]
    small_work = sum(measurements[0])
    large_work = sum(measurements[1])
    # ponytail: counts top-level file and graph-node visits; add parser-level
    # counters if one object ever contains enough nested data to dominate work.
    assert large_work <= small_work * 2.05


def test_synthetic_scale_export_rebuild_is_equivalent(tmp_path: Path) -> None:
    generated = generate_synthetic_export(
        tmp_path / "synthetic_roundtrip",
        SYNTHETIC_SCALE_OBJECTS,
        seed=37,
    )
    metrics = _assert_package_equivalence(generated.root, tmp_path / "roundtrip")

    assert metrics["objects"] == SYNTHETIC_SCALE_OBJECTS
    assert metrics["types"] == generated.type_counts
    assert metrics["document_payloads"] > 0


@pytest.mark.skipif(
    os.environ.get("RUN_APPIAN_CORPUS") != "1",
    reason="set RUN_APPIAN_CORPUS=1 to run the large export gate",
)
def test_full_export_rebuild_is_equivalent(tmp_path: Path) -> None:
    if not CORPUS_PATH.is_dir():
        pytest.fail(f"Appian corpus not found: {CORPUS_PATH}")
    metrics = _assert_package_equivalence(CORPUS_PATH, tmp_path)
    print(metrics)
    assert metrics["objects"] == 2624
    assert metrics["document_payloads"] > 0
