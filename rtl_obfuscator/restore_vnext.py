"""Schema-2 persistence and byte-audited restore.

Restore consumes only the source evidence recorded by the PySlang RenameIndex
mapping.  It never rebuilds a SymbolGraph or performs semantic name lookup.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import posixpath
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any

from .mapping_vnext import InputFileDigest, MappingRecord
from .rename_index import SymbolOccurrence
from .rtl_files import is_source_file
from .source_catalog import SourceRange
from .source_set import SourceSet


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_ENVIRONMENT_VARIABLE = re.compile(
    r"\$(?:\{[A-Za-z_][A-Za-z0-9_]*\}|[A-Za-z_][A-Za-z0-9_]*)"
)


def _is_export_environment_token(raw: str) -> bool:
    return raw != "$OUT" and not raw.startswith("$OUT/") and bool(
        _ENVIRONMENT_VARIABLE.search(raw)
    )
_PRIVATE_KEYS = frozenset({"source_root", "gate_dir", "restore_dir", "output_dir"})
_CATEGORIES = frozenset({"signals", "ports", "interface", "struct"})
_MAPPING_KEYS = {
    "format", "schema_version", "state", "source_set", "selection",
    "name_length", "input_manifest", "records", "category_outcomes",
    "summary", "range_audit",
}


class RestoreVNextError(ValueError):
    """Stable fail-closed error for persistent schema-2 restore."""

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}" if message else code)


def _fail(code: str, message: str = "") -> None:
    raise RestoreVNextError(code, message)


def _portable_file(value: object) -> bool:
    if not isinstance(value, str) or not value or value.startswith("/") or "\\" in value:
        return False
    return all(part not in {"", ".", ".."} for part in value.split("/"))


def _portable_value(value: object) -> bool:
    if isinstance(value, dict):
        return all(key not in _PRIVATE_KEYS and _portable_value(item) for key, item in value.items())
    if isinstance(value, list):
        return all(_portable_value(item) for item in value)
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, str):
        return not value.startswith("/") and re.match(r"^[A-Za-z]:[\\/]", value) is None
    return True


def _resolve(path: object, code: str) -> Path:
    try:
        return Path(path).expanduser().resolve()
    except (OSError, RuntimeError, TypeError) as error:
        _fail(code, str(error))


def _overlap(first: Path, second: Path) -> bool:
    try:
        first.relative_to(second)
        return True
    except ValueError:
        pass
    try:
        second.relative_to(first)
        return True
    except ValueError:
        return False


def _validate_paths(map_file: Path, gate_dir: Path, source_root: Path, output_dir: Path, report_file: Path | None = None) -> tuple[Path, Path, Path, Path, Path | None]:
    map_path = _resolve(map_file, "RESTORE_VNEXT_INPUT_INVALID")
    gate_path = _resolve(gate_dir, "RESTORE_VNEXT_GATE_INVALID")
    source_path = _resolve(source_root, "RESTORE_VNEXT_INPUT_INVALID")
    output_path = _resolve(output_dir, "RESTORE_VNEXT_OUTPUT_INVALID")
    report_path = None if report_file is None else _resolve(report_file, "RESTORE_VNEXT_OUTPUT_INVALID")
    if not map_path.is_file() or not gate_path.is_dir() or not source_path.is_dir():
        _fail("RESTORE_VNEXT_INPUT_INVALID", "map, gate-dir, and source-root must exist")
    targets = (output_path, *((report_path,) if report_path is not None else ()))
    for path in targets:
        if path.exists() or path.is_symlink() or not path.parent.is_dir():
            _fail("RESTORE_VNEXT_OUTPUT_INVALID", "output path must not exist")
    protected = (source_path, gate_path, map_path)
    if any(_overlap(target, item) for target in targets for item in protected):
        _fail("RESTORE_VNEXT_OUTPUT_INVALID", "output overlaps an input")
    if report_path is not None and _overlap(output_path, report_path):
        _fail("RESTORE_VNEXT_OUTPUT_INVALID", "output and report overlap")
    return map_path, gate_path, source_path, output_path, report_path


def validate_direct_restore_paths_vnext(map_file: Path, gate_dir: Path, output_dir: Path, report_file: Path | None = None) -> tuple[Path, Path, Path, Path | None]:
    map_path = _resolve(map_file, "RESTORE_VNEXT_INPUT_INVALID")
    gate_path = _resolve(gate_dir, "RESTORE_VNEXT_GATE_INVALID")
    output_path = _resolve(output_dir, "RESTORE_VNEXT_OUTPUT_INVALID")
    report_path = None if report_file is None else _resolve(report_file, "RESTORE_VNEXT_OUTPUT_INVALID")
    if not map_path.is_file():
        _fail("RESTORE_VNEXT_INPUT_INVALID", "map is not a regular file")
    if not gate_path.is_dir():
        _fail("RESTORE_VNEXT_GATE_INVALID", "gate-dir is not a directory")
    targets = (output_path, *((report_path,) if report_path is not None else ()))
    for path in targets:
        if path.exists() or path.is_symlink() or not path.parent.is_dir():
            _fail("RESTORE_VNEXT_OUTPUT_INVALID", "output path must not exist")
    if any(_overlap(target, item) for target in targets for item in (gate_path, map_path)):
        _fail("RESTORE_VNEXT_OUTPUT_INVALID", "output overlaps an input")
    if report_path is not None and _overlap(output_path, report_path):
        _fail("RESTORE_VNEXT_OUTPUT_INVALID", "output and report overlap")
    return map_path, gate_path, output_path, report_path


def _read_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        _fail("RESTORE_VNEXT_IO_ERROR", str(error))
    if not isinstance(value, dict) or not _portable_value(value):
        _fail("RESTORE_VNEXT_REPORT_INVALID", "report is not a portable object")
    return value


def _source_set_report(source_set: SourceSet) -> dict[str, object]:
    return {
        "schema_version": source_set.schema_version,
        "origin": source_set.origin,
        "ordered_source_files": list(source_set.ordered_source_files),
        "included_files": list(source_set.included_files),
        "include_dirs": list(source_set.include_dirs),
        "defines": [{"name": name, "value": value} for name, value in source_set.defines],
        "top": source_set.top,
        "top_closure_files": list(source_set.top_closure_files),
        "compile_order": list(source_set.compile_order),
    }


def _mapping_source_set(source_set: SourceSet) -> dict[str, object]:
    report = _source_set_report(source_set)
    report.pop("origin")
    return report


def _parse_source_set(value: object, root: Path) -> SourceSet:
    if not isinstance(value, dict):
        _fail("RESTORE_VNEXT_INPUT_INVALID", "source_set is not an object")
    expected = {"schema_version", "origin", "ordered_source_files", "included_files", "include_dirs", "defines", "top", "top_closure_files", "compile_order"}
    if set(value) != expected or value["schema_version"] != 1:
        _fail("RESTORE_VNEXT_INPUT_INVALID", "source_set schema is invalid")
    sequence_keys = ("ordered_source_files", "included_files", "include_dirs", "top_closure_files", "compile_order")
    if any(not isinstance(value[key], list) or not all(isinstance(item, str) for item in value[key]) for key in sequence_keys):
        _fail("RESTORE_VNEXT_INPUT_INVALID", "source_set sequence is invalid")
    for key in sequence_keys:
        if any(
            not _portable_file(item) and not (key == "include_dirs" and item == ".")
            for item in value[key]
        ):
            _fail("RESTORE_VNEXT_INPUT_INVALID", "source_set path is not portable")
    if not isinstance(value["defines"], list):
        _fail("RESTORE_VNEXT_INPUT_INVALID", "source_set defines are invalid")
    defines: list[tuple[str, str]] = []
    for item in value["defines"]:
        if not isinstance(item, dict) or set(item) != {"name", "value"} or not all(isinstance(item[key], str) for key in ("name", "value")):
            _fail("RESTORE_VNEXT_INPUT_INVALID", "source_set define is invalid")
        defines.append((item["name"], item["value"]))
    top = value["top"]
    if top is not None and not isinstance(top, str):
        _fail("RESTORE_VNEXT_INPUT_INVALID", "source_set top is invalid")
    return SourceSet(
        schema_version=1, origin=value["origin"], source_root=root,
        ordered_source_files=tuple(value["ordered_source_files"]),
        included_files=tuple(value["included_files"]), include_dirs=tuple(value["include_dirs"]),
        defines=tuple(defines), top=top, top_closure_files=tuple(value["top_closure_files"]),
        compile_order=tuple(value["compile_order"]),
    )


def _files(source_set: SourceSet) -> tuple[str, ...]:
    result: list[str] = []
    for file in (*source_set.ordered_source_files, *source_set.included_files):
        if file not in result:
            result.append(file)
    if not result or any(not _portable_file(file) for file in result):
        _fail("RESTORE_VNEXT_INPUT_INVALID", "source_set physical files are invalid")
    return tuple(result)


def _parse_range(value: object, *, label: str) -> SourceRange:
    if not isinstance(value, dict) or set(value) != {"file", "start", "end"}:
        _fail("RESTORE_VNEXT_REPORT_INVALID", f"{label} schema is invalid")
    if not _portable_file(value["file"]) or type(value["start"]) is not int or type(value["end"]) is not int or not 0 <= value["start"] < value["end"]:
        _fail("RESTORE_VNEXT_REPORT_INVALID", f"{label} range is invalid")
    return SourceRange(value["file"], value["start"], value["end"])


def _parse_manifest(value: object, files: tuple[str, ...], *, label: str) -> tuple[InputFileDigest, ...]:
    if not isinstance(value, list) or len(value) != len(files):
        _fail("RESTORE_VNEXT_REPORT_INVALID", f"{label} shape is invalid")
    result: list[InputFileDigest] = []
    for item, file in zip(value, files):
        if not isinstance(item, dict) or set(item) != {"file", "sha256"} or item["file"] != file or not isinstance(item["sha256"], str) or _SHA256.fullmatch(item["sha256"]) is None:
            _fail("RESTORE_VNEXT_REPORT_INVALID", f"{label} order or hash is invalid")
        result.append(InputFileDigest(file, item["sha256"]))
    return tuple(result)


def _parse_occurrences(value: object) -> tuple[SymbolOccurrence, ...]:
    if not isinstance(value, list):
        _fail("RESTORE_VNEXT_REPORT_INVALID", "occurrences are invalid")
    result: list[SymbolOccurrence] = []
    for item in value:
        if not isinstance(item, dict) or set(item) != {"source_range", "provenance"} or not isinstance(item["provenance"], str) or not item["provenance"]:
            _fail("RESTORE_VNEXT_REPORT_INVALID", "occurrence schema is invalid")
        result.append(SymbolOccurrence(_parse_range(item["source_range"], label="occurrence"), item["provenance"]))
    return tuple(result)


def _parse_mapping_report(value: object, *, source_set: SourceSet, source_data: dict[str, bytes] | None) -> tuple[MappingRecord, ...]:
    if not isinstance(value, dict) or set(value) != _MAPPING_KEYS or value.get("format") != "rtl-obfuscation.mapping" or value.get("schema_version") != 2 or value.get("state") != "planned":
        if isinstance(value, dict) and value.get("schema_version") == 1:
            _fail("RESTORE_MAPPING_VERSION_UNSUPPORTED", "schema 1 mappings are not supported")
        _fail("RESTORE_VNEXT_REPORT_INVALID", "mapping report format, schema, or state is invalid")
    if value.get("source_set") != _mapping_source_set(source_set):
        _fail("RESTORE_VNEXT_REPORT_INVALID", "mapping source_set differs from orchestration source_set")
    selection = value.get("selection")
    if not isinstance(selection, dict) or set(selection) != {"selected_categories", "abi_categories", "preserve_top_boundary"} or selection["preserve_top_boundary"] is not True or selection["abi_categories"] != []:
        _fail("RESTORE_VNEXT_REPORT_INVALID", "mapping selection is invalid")
    categories = selection.get("selected_categories")
    if not isinstance(categories, list) or not categories or any(item not in _CATEGORIES for item in categories):
        _fail("RESTORE_VNEXT_REPORT_INVALID", "mapping categories are invalid")
    if type(value.get("name_length")) is not int or value["name_length"] < 4:
        _fail("RESTORE_VNEXT_REPORT_INVALID", "mapping name_length is invalid")
    files = _files(source_set)
    manifest = _parse_manifest(value.get("input_manifest"), files, label="mapping input_manifest")
    if source_data is not None and manifest != _manifest(source_data, files):
        _fail("RESTORE_VNEXT_REPORT_INVALID", "source bytes differ from mapping manifest")
    raw_records = value.get("records")
    if not isinstance(raw_records, list):
        _fail("RESTORE_VNEXT_REPORT_INVALID", "mapping records are invalid")
    expected_keys = {"record_id", "symbol_id", "category", "kind", "semantic_kind", "action", "reason", "original_name", "renamed_name", "owner_module", "semantic_owner", "declaration", "occurrences", "impact", "abi"}
    result: list[MappingRecord] = []
    ranges: list[tuple[str, int, int]] = []
    for item in raw_records:
        if not isinstance(item, dict) or set(item) != expected_keys:
            _fail("RESTORE_VNEXT_REPORT_INVALID", "mapping record schema is invalid")
        if item["record_id"] != item["symbol_id"] or not all(isinstance(item[key], str) and item[key] for key in ("symbol_id", "category", "kind", "semantic_kind", "original_name", "owner_module", "semantic_owner", "impact", "abi")):
            _fail("RESTORE_VNEXT_REPORT_INVALID", "mapping record identity is invalid")
        if item["category"] not in _CATEGORIES or item["action"] not in {"rename", "preserve", "unsupported"}:
            _fail("RESTORE_VNEXT_REPORT_INVALID", "mapping record category or action is invalid")
        renamed = item["renamed_name"]
        if item["action"] == "rename" and (not isinstance(renamed, str) or not renamed):
            _fail("RESTORE_VNEXT_REPORT_INVALID", "rename record name is invalid")
        if item["action"] != "rename" and renamed is not None:
            _fail("RESTORE_VNEXT_REPORT_INVALID", "non-rename record has a renamed name")
        if item["reason"] is not None and not isinstance(item["reason"], str):
            _fail("RESTORE_VNEXT_REPORT_INVALID", "mapping reason is invalid")
        declaration = _parse_range(item["declaration"], label="declaration")
        occurrences = _parse_occurrences(item["occurrences"])
        for source_range in (declaration, *(occurrence.source_range for occurrence in occurrences)):
            if source_range.file not in files:
                _fail("RESTORE_VNEXT_REPORT_INVALID", "mapping range is not physical")
            if source_data is not None and (source_range.end > len(source_data[source_range.file]) or source_data[source_range.file][source_range.start:source_range.end] != item["original_name"].encode()):
                _fail("RESTORE_VNEXT_REPORT_INVALID", "mapping range bytes do not match original name")
            ranges.append((source_range.file, source_range.start, source_range.end))
        result.append(MappingRecord(
            symbol_id=item["symbol_id"], category=item["category"], kind=item["kind"], semantic_kind=item["semantic_kind"],
            action=item["action"], reason=item["reason"], original_name=item["original_name"], renamed_name=renamed,
            owner_module=item["owner_module"], semantic_owner=item["semantic_owner"], declaration=declaration,
            occurrences=occurrences, impact=item["impact"], abi=item["abi"],
        ))
    ordered = sorted(ranges)
    if len(set(ranges)) != len(ranges) or any(previous[0] == current[0] and previous[2] > current[1] for previous, current in zip(ordered, ordered[1:])):
        _fail("RESTORE_VNEXT_REPORT_INVALID", "mapping ranges overlap or duplicate")
    return tuple(result)


def _read_files(root: Path, files: tuple[str, ...]) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    for file in files:
        path = (root / file).resolve()
        try:
            path.relative_to(root.resolve())
            result[file] = path.read_bytes()
        except (OSError, ValueError) as error:
            _fail("RESTORE_VNEXT_GATE_INVALID", f"physical file is unavailable: {file}: {error}")
    return result


def _manifest(data: dict[str, bytes], files: tuple[str, ...]) -> tuple[InputFileDigest, ...]:
    return tuple(InputFileDigest(file, hashlib.sha256(data[file]).hexdigest()) for file in files)


def _validate_gate_files(
    gate: Path,
    files: tuple[str, ...],
    report_path: Path,
    nested_filelists: tuple[str, ...] = (),
) -> None:
    expected = set(files) | {"design.f"}
    delivery_views = {"export_design.f", "original_design.f"}
    present_views = {name for name in delivery_views if (gate / name).is_file()}
    if present_views and present_views != delivery_views:
        _fail("RESTORE_VNEXT_GATE_INVALID", "gate filelist views are incomplete")
    expected.update(present_views)
    expected.update(nested_filelists)
    for name in ("mapping.json", "metrics.json", "mapping_table.csv", "encryption_summary.txt"):
        path = gate / name
        if path.exists():
            expected.add(name)
    actual = {path.relative_to(gate).as_posix() for path in gate.rglob("*") if path.is_file() or path.is_symlink()}
    if actual != expected:
        _fail("RESTORE_VNEXT_GATE_INVALID", "gate file set is invalid")
    if (gate / "mapping.json").exists() and (gate / "mapping.json").resolve() != report_path.resolve():
        _fail("RESTORE_VNEXT_GATE_INVALID", "gate mapping.json differs from requested report")


def _validate_delivery_filelists_manifest(
    gate: Path,
    value: object,
    expected_paths: tuple[str, ...],
) -> tuple[str, ...]:
    if not isinstance(value, dict) or set(value) != {"originals"}:
        _fail("RESTORE_VNEXT_GATE_INVALID", "delivery filelist manifest is invalid")
    originals = value["originals"]
    if not isinstance(originals, list) or len(originals) != len(expected_paths):
        _fail("RESTORE_VNEXT_GATE_INVALID", "delivery filelist manifest members are invalid")
    for item, expected_path in zip(originals, expected_paths):
        if not isinstance(item, dict) or set(item) != {"path", "sha256"}:
            _fail("RESTORE_VNEXT_GATE_INVALID", "delivery filelist manifest entry is invalid")
        path = item["path"]
        digest = item["sha256"]
        if path != expected_path or not _portable_file(path):
            _fail("RESTORE_VNEXT_GATE_INVALID", "delivery filelist manifest path order is invalid")
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            _fail("RESTORE_VNEXT_GATE_INVALID", "delivery filelist manifest digest is invalid")
        candidate = gate / path
        current = gate.resolve()
        for part in Path(path).parts:
            current = current / part
            if current.is_symlink():
                _fail("RESTORE_VNEXT_GATE_INVALID", "original filelist snapshot must be physical")
        try:
            candidate.resolve().relative_to(gate.resolve())
        except (OSError, RuntimeError, ValueError) as error:
            _fail("RESTORE_VNEXT_GATE_INVALID", f"original filelist snapshot escapes gate: {error}")
        if not candidate.is_file():
            _fail("RESTORE_VNEXT_GATE_INVALID", f"original filelist snapshot is missing: {path}")
        try:
            actual = hashlib.sha256(candidate.read_bytes()).hexdigest()
        except OSError as error:
            _fail("RESTORE_VNEXT_GATE_INVALID", str(error))
        if actual != digest:
            _fail("RESTORE_VNEXT_GATE_INVALID", f"original filelist snapshot digest differs: {path}")
    return expected_paths[1:]


def _context_filelist_lines(
    source_set: SourceSet,
    *,
    root: Path | None = None,
    environment_root: str | None = None,
) -> tuple[str, ...]:
    if (root is None) == (environment_root is None):
        _fail("RESTORE_VNEXT_GATE_INVALID", "filelist root is invalid")

    def path(entry: str) -> str:
        if environment_root is not None:
            if entry == ".":
                return environment_root
            return f"{environment_root}/{entry}"
        assert root is not None
        return (root / entry).resolve().as_posix()

    return (
        *(f"+incdir+{path(item)}" for item in source_set.include_dirs),
        *(f"+define+{name}={value}" for name, value in source_set.defines),
        *(path(item) for item in source_set.compile_order),
    )


def _read_filelist_lines(path: Path) -> tuple[str, ...]:
    try:
        return tuple(
            line for line in path.read_text(encoding="utf-8").splitlines() if line
        )
    except (OSError, UnicodeError) as error:
        _fail("RESTORE_VNEXT_GATE_INVALID", str(error))


def _root_before_suffix(value: str, suffix: str) -> Path:
    path = Path(value)
    if suffix == ".":
        if not path.is_absolute():
            _fail("RESTORE_VNEXT_GATE_INVALID", "original filelist path is invalid")
        return path
    suffix_parts = Path(suffix).parts
    path_parts = path.parts
    if (
        not path.is_absolute()
        or not suffix_parts
        or len(path_parts) <= len(suffix_parts)
        or path_parts[-len(suffix_parts) :] != suffix_parts
    ):
        _fail("RESTORE_VNEXT_GATE_INVALID", "original filelist path is invalid")
    return Path(*path_parts[: -len(suffix_parts)])


def _validate_original_filelist(
    lines: tuple[str, ...], source_set: SourceSet
) -> None:
    include_count = len(source_set.include_dirs)
    define_count = len(source_set.defines)
    if len(lines) != include_count + define_count + len(source_set.compile_order):
        _fail("RESTORE_VNEXT_GATE_INVALID", "original filelist shape is invalid")
    roots: list[Path] = []
    for line, item in zip(lines[:include_count], source_set.include_dirs):
        if not line.startswith("+incdir+"):
            _fail("RESTORE_VNEXT_GATE_INVALID", "original include directory is invalid")
        roots.append(_root_before_suffix(line[len("+incdir+") :], item))
    define_lines = lines[include_count : include_count + define_count]
    expected_defines = tuple(
        f"+define+{name}={value}" for name, value in source_set.defines
    )
    if define_lines != expected_defines:
        _fail("RESTORE_VNEXT_GATE_INVALID", "original defines differ from SourceSet")
    compile_lines = lines[include_count + define_count :]
    for line, item in zip(compile_lines, source_set.compile_order):
        roots.append(_root_before_suffix(line, item))
    if not roots or any(root != roots[0] for root in roots[1:]):
        _fail("RESTORE_VNEXT_GATE_INVALID", "original filelist roots are inconsistent")


@dataclass(frozen=True)
class _DeliveryFilelistView:
    physical_files: tuple[str | None, ...]
    include_dirs: tuple[str | None, ...]
    structures: tuple[tuple[str, bytes], ...]
    nested_files: tuple[str, ...]
    references: tuple["_DeliveryPathReference", ...]


@dataclass(frozen=True)
class _DeliveryPathReference:
    kind: str
    raw: str
    relative: str | None
    owner: str


def _delivery_filelist_view(
    filelist: Path,
    *,
    gate_path: Path,
    mode: str,
    recurse: bool = True,
    paired_nested_files: tuple[str, ...] = (),
) -> _DeliveryFilelistView:
    if mode not in {"design", "export", "original"}:
        _fail("RESTORE_VNEXT_GATE_INVALID", "filelist view mode is invalid")
    physical_files: list[str | None] = []
    include_dirs: list[str | None] = []
    structures: dict[str, bytes] = {}
    nested_files: list[str] = []
    references: list[_DeliveryPathReference] = []
    active: tuple[Path, ...] = ()
    def replace_token(line: str, token_index: int, replacement: str) -> str:
        matches = tuple(re.finditer(r"\S+", line))
        if token_index >= len(matches):
            _fail("RESTORE_VNEXT_GATE_INVALID", "filelist path token is unavailable")
        match = matches[token_index]
        return f"{line[:match.start()]}{replacement}{line[match.end():]}"

    def delivery_relative(raw: str, *, directory: bool = False) -> str | None:
        if mode == "original":
            return None
        if mode == "export":
            if _is_export_environment_token(raw):
                return None
            if raw == "$OUT":
                relative = "."
            elif raw.startswith("$OUT/"):
                relative = posixpath.normpath(raw[len("$OUT/") :])
                if relative == ".." or relative.startswith("../"):
                    _fail("RESTORE_VNEXT_GATE_INVALID", "export filelist path escapes gate")
            else:
                _fail("RESTORE_VNEXT_GATE_INVALID", "export filelist path is invalid")
        else:
            path = Path(raw)
            if not path.is_absolute():
                _fail("RESTORE_VNEXT_GATE_INVALID", "design filelist path is invalid")
            try:
                relative = path.resolve().relative_to(gate_path).as_posix() or "."
            except (OSError, RuntimeError, ValueError) as error:
                _fail("RESTORE_VNEXT_GATE_INVALID", f"design filelist path is invalid: {error}")
        if relative != "." and not _portable_file(relative):
            _fail("RESTORE_VNEXT_GATE_INVALID", "delivery filelist path is invalid")
        if not directory and relative == ".":
            _fail("RESTORE_VNEXT_GATE_INVALID", "delivery source path is invalid")
        return relative

    def visit(current: Path, key: str, ancestors: tuple[Path, ...]) -> None:
        try:
            canonical = current.resolve()
        except (OSError, RuntimeError) as error:
            _fail("RESTORE_VNEXT_GATE_INVALID", str(error))
        if canonical in ancestors:
            _fail("RESTORE_VNEXT_GATE_INVALID", "delivery filelist cycle is invalid")
        if key in structures:
            return
        if not canonical.is_file():
            _fail("RESTORE_VNEXT_GATE_INVALID", "delivery filelist tree is invalid")
        try:
            decoded = canonical.read_bytes().decode("utf-8")
        except (OSError, UnicodeError) as error:
            _fail("RESTORE_VNEXT_GATE_INVALID", str(error))
        next_active = (*ancestors, canonical)
        rendered: list[str] = []
        for raw_line in decoded.splitlines(keepends=True):
            ending = ""
            content = raw_line
            for candidate in ("\r\n", "\n", "\r"):
                if raw_line.endswith(candidate):
                    content = raw_line[: -len(candidate)]
                    ending = candidate
                    break
            text = content.strip()
            if not text or text.startswith("#") or text.startswith("//"):
                rendered.append(content + ending)
                continue
            tokens = text.split()
            if tokens[0] == "-f":
                if len(tokens) != 2:
                    _fail("RESTORE_VNEXT_GATE_INVALID", "nested filelist entry is invalid")
                rendered.append(replace_token(content, 1, "<FILELIST>") + ending)
                relative = delivery_relative(tokens[1])
                references.append(
                    _DeliveryPathReference("filelist", tokens[1], relative, key)
                )
                if mode == "original" or not recurse:
                    continue
                if mode == "design":
                    prefix = ".rtl_obfuscation/filelists/design/"
                    if relative is None or not relative.startswith(prefix):
                        _fail("RESTORE_VNEXT_GATE_INVALID", "nested filelist path is invalid")
                    child_key = relative[len(prefix) :]
                    if not _portable_file(child_key):
                        _fail("RESTORE_VNEXT_GATE_INVALID", "nested filelist path is invalid")
                    nested_relative = relative
                else:
                    nested_index = len(nested_files)
                    if nested_index >= len(paired_nested_files):
                        _fail("RESTORE_VNEXT_GATE_INVALID", "nested filelist pairing is invalid")
                    design_relative = paired_nested_files[nested_index]
                    design_prefix = ".rtl_obfuscation/filelists/design/"
                    if not design_relative.startswith(design_prefix):
                        _fail("RESTORE_VNEXT_GATE_INVALID", "nested filelist pairing is invalid")
                    child_key = design_relative[len(design_prefix) :]
                    if not _portable_file(child_key):
                        _fail("RESTORE_VNEXT_GATE_INVALID", "nested filelist pairing is invalid")
                    nested_relative = f".rtl_obfuscation/filelists/export/{child_key}"
                nested_files.append(nested_relative)
                visit(gate_path / nested_relative, child_key, next_active)
                continue
            if tokens[0] == "-v":
                if len(tokens) != 2:
                    _fail("RESTORE_VNEXT_GATE_INVALID", "library source entry is invalid")
                relative = delivery_relative(tokens[1])
                physical_files.append(relative)
                references.append(
                    _DeliveryPathReference("physical", tokens[1], relative, key)
                )
                rendered.append(replace_token(content, 1, "<PATH>") + ending)
                continue
            if text.startswith("+incdir+"):
                values = text[len("+incdir+") :].split("+")
                if not values or any(not value for value in values):
                    _fail("RESTORE_VNEXT_GATE_INVALID", "include directory entry is invalid")
                for value in values:
                    relative = delivery_relative(value, directory=True)
                    include_dirs.append(relative)
                    references.append(
                        _DeliveryPathReference("directory", value, relative, key)
                    )
                replacement = "+incdir+" + "+".join("<PATH>" for _ in values)
                rendered.append(replace_token(content, 0, replacement) + ending)
                continue
            if text.startswith("+define+"):
                rendered.append(content + ending)
                continue
            if len(tokens) != 1 or text.startswith(("+", "-")):
                _fail("RESTORE_VNEXT_GATE_INVALID", "filelist entry is invalid")
            relative = delivery_relative(tokens[0])
            physical_files.append(relative)
            references.append(
                _DeliveryPathReference("physical", tokens[0], relative, key)
            )
            rendered.append(replace_token(content, 0, "<PATH>") + ending)
        structures[key] = "".join(rendered).encode("utf-8")

    visit(filelist, ".", active)
    return _DeliveryFilelistView(
        physical_files=tuple(physical_files),
        include_dirs=tuple(include_dirs),
        structures=tuple(structures.items()),
        nested_files=tuple(nested_files),
        references=tuple(references),
    )


def _validate_gate_filelists(
    gate_path: Path,
    source_set: SourceSet,
    delivery_filelists: object = None,
    *,
    manifest_present: bool = False,
) -> tuple[str, ...]:
    design = _read_filelist_lines(gate_path / "design.f")
    export_path = gate_path / "export_design.f"
    original_path = gate_path / "original_design.f"
    if manifest_present and source_set.origin != "filelist":
        _fail("RESTORE_VNEXT_GATE_INVALID", "delivery filelist manifest requires filelist origin")
    if manifest_present and not (export_path.is_file() and original_path.is_file()):
        _fail("RESTORE_VNEXT_GATE_INVALID", "delivery filelist views are incomplete")
    if not export_path.exists() and not original_path.exists():
        if design != tuple(source_set.compile_order):
            _fail("RESTORE_VNEXT_GATE_INVALID", "gate design.f differs from compile order")
        return ()
    if source_set.origin == "filelist":
        design_view = _delivery_filelist_view(
            gate_path / "design.f", gate_path=gate_path, mode="design"
        )
        export_view = _delivery_filelist_view(
            export_path,
            gate_path=gate_path,
            mode="export",
            paired_nested_files=design_view.nested_files,
        )
        original_view = _delivery_filelist_view(
            original_path,
            gate_path=gate_path,
            mode="original",
            recurse=False,
        )
        if design_view.structures != export_view.structures:
            _fail("RESTORE_VNEXT_GATE_INVALID", "delivery filelist structures differ")
        design_structures = dict(design_view.structures)
        original_structures = dict(original_view.structures)
        if original_structures.get(".") != design_structures.get("."):
            _fail("RESTORE_VNEXT_GATE_INVALID", "original filelist structure differs")
        if len(export_view.physical_files) != len(design_view.physical_files):
            _fail("RESTORE_VNEXT_GATE_INVALID", "delivery filelist paths differ")
        expected_physical = tuple(source_set.compile_order)
        if (
            len(design_view.physical_files) != len(expected_physical)
            or len(set(design_view.physical_files)) != len(design_view.physical_files)
            or set(design_view.physical_files) != set(expected_physical)
        ):
            _fail("RESTORE_VNEXT_GATE_INVALID", "delivery filelist membership differs")
        if tuple(
            item for item in design_view.physical_files if is_source_file(item)
        ) != tuple(source_set.ordered_source_files):
            _fail("RESTORE_VNEXT_GATE_INVALID", "delivery source order differs")
        if any(item not in source_set.include_dirs for item in design_view.include_dirs):
            _fail("RESTORE_VNEXT_GATE_INVALID", "delivery include directories differ")
        if design_view.nested_files != tuple(
            item.replace(
                ".rtl_obfuscation/filelists/export/",
                ".rtl_obfuscation/filelists/design/",
                1,
            )
            for item in export_view.nested_files
        ):
            _fail("RESTORE_VNEXT_GATE_INVALID", "delivery nested filelists differ")
        if len(design_view.references) != len(export_view.references) or any(
            (design.kind, design.owner) != (export.kind, export.owner)
            for design, export in zip(design_view.references, export_view.references)
        ):
            _fail("RESTORE_VNEXT_GATE_INVALID", "delivery path references differ")

        file_aliases: dict[str, str] = {}
        directory_aliases: dict[str, str] = {}

        def add_alias(aliases: dict[str, str], alias: str, target: str) -> None:
            if alias == target or alias == ".":
                return
            if not _portable_file(alias):
                _fail("RESTORE_VNEXT_GATE_INVALID", "delivery alias path is invalid")
            previous = aliases.get(alias)
            if previous is not None and previous != target:
                _fail("RESTORE_VNEXT_GATE_INVALID", "delivery alias targets conflict")
            aliases[alias] = target

        def design_child(relative: str | None) -> tuple[str, str]:
            prefix = ".rtl_obfuscation/filelists/design/"
            if relative is None or not relative.startswith(prefix):
                _fail("RESTORE_VNEXT_GATE_INVALID", "nested filelist path is invalid")
            child_key = relative[len(prefix) :]
            if not _portable_file(child_key):
                _fail("RESTORE_VNEXT_GATE_INVALID", "nested filelist path is invalid")
            return child_key, f".rtl_obfuscation/filelists/export/{child_key}"

        def nested_snapshot_order() -> tuple[str, ...]:
            children: dict[str, list[str]] = {}
            for reference in design_view.references:
                if reference.kind != "filelist":
                    continue
                child_key, _nested_relative = design_child(reference.relative)
                children.setdefault(reference.owner, []).append(child_key)
            ordered: list[str] = []
            seen: set[str] = set()

            def visit(owner: str) -> None:
                for child_key in children.get(owner, ()):
                    if child_key in seen:
                        continue
                    seen.add(child_key)
                    ordered.append(
                        f".rtl_obfuscation/filelists/original/{child_key}"
                    )
                    visit(child_key)

            visit(".")
            return tuple(ordered)

        snapshot_root = gate_path / ".rtl_obfuscation/filelists/original"
        snapshots_present = snapshot_root.exists() or snapshot_root.is_symlink()
        if snapshots_present and not manifest_present:
            _fail("RESTORE_VNEXT_GATE_INVALID", "original filelist snapshots require a manifest")
        snapshot_paths: tuple[str, ...] = ()
        if manifest_present:
            expected_manifest_paths = (
                "original_design.f",
                *nested_snapshot_order(),
            )
            snapshot_paths = _validate_delivery_filelists_manifest(
                gate_path,
                delivery_filelists,
                expected_manifest_paths,
            )

        def absolute_export_relative(raw: str) -> str:
            if not raw.startswith("/"):
                _fail("RESTORE_VNEXT_GATE_INVALID", "original absolute path is invalid")
            relative = posixpath.normpath(raw.lstrip("/"))
            if relative == ".." or relative.startswith("../"):
                _fail("RESTORE_VNEXT_GATE_INVALID", "original absolute path escapes gate")
            return relative or "."

        if manifest_present:
            original_references_by_owner: dict[
                str, tuple[_DeliveryPathReference, ...]
            ] = {
                ".": tuple(original_view.references),
            }
            original_structures_by_owner: dict[str, bytes] = {
                ".": dict(original_view.structures)["."],
            }
            snapshot_prefix = ".rtl_obfuscation/filelists/original/"
            for snapshot_relative in snapshot_paths:
                owner = snapshot_relative[len(snapshot_prefix) :]
                snapshot_view = _delivery_filelist_view(
                    gate_path / snapshot_relative,
                    gate_path=gate_path,
                    mode="original",
                    recurse=False,
                )
                original_references_by_owner[owner] = tuple(
                    snapshot_view.references
                )
                original_structures_by_owner[owner] = dict(
                    snapshot_view.structures
                )["."]
            design_by_owner: dict[str, list[_DeliveryPathReference]] = {}
            export_by_owner: dict[str, list[_DeliveryPathReference]] = {}
            for reference in design_view.references:
                design_by_owner.setdefault(reference.owner, []).append(reference)
            for reference in export_view.references:
                export_by_owner.setdefault(reference.owner, []).append(reference)
            if set(original_references_by_owner) != set(design_structures):
                _fail("RESTORE_VNEXT_GATE_INVALID", "original nested filelist inventory differs")
            export_structures = dict(export_view.structures)
            for owner, original_references in original_references_by_owner.items():
                design_references = design_by_owner.get(owner, [])
                export_references = export_by_owner.get(owner, [])
                if not (
                    len(original_references)
                    == len(design_references)
                    == len(export_references)
                ):
                    _fail("RESTORE_VNEXT_GATE_INVALID", "original filelist path references differ")
                if (
                    original_structures_by_owner[owner] != design_structures.get(owner)
                    or original_structures_by_owner[owner] != export_structures.get(owner)
                ):
                    _fail("RESTORE_VNEXT_GATE_INVALID", "original nested filelist structure differs")
                for original, design, exported in zip(
                    original_references, design_references, export_references
                ):
                    if not (original.kind == design.kind == exported.kind):
                        _fail("RESTORE_VNEXT_GATE_INVALID", "original filelist path kinds differ")
                    if _ENVIRONMENT_VARIABLE.search(original.raw):
                        expected = original.raw
                    elif Path(original.raw).is_absolute():
                        suffix = original.raw.lstrip("/")
                        expected = "$OUT" if not suffix else f"$OUT/{suffix}"
                    elif original.kind == "filelist":
                        _child_key, expected_relative = design_child(design.relative)
                        expected = f"$OUT/{expected_relative}"
                    else:
                        if design.relative is None:
                            _fail("RESTORE_VNEXT_GATE_INVALID", "design path reference is invalid")
                        expected = "$OUT" if design.relative == "." else f"$OUT/{design.relative}"
                    if exported.raw != expected:
                        _fail("RESTORE_VNEXT_GATE_INVALID", "export path token differs from original token rule")
        else:
            # Older schema-2 reports have no raw nested snapshots. Preserve their
            # existing validation behavior while applying the same top-level
            # token check used before T148's delivery manifest.
            original_references = tuple(original_view.references)
            export_top_references = tuple(
                reference for reference in export_view.references if reference.owner == "."
            )
            design_top_references = tuple(
                reference for reference in design_view.references if reference.owner == "."
            )
            if not (
                len(original_references)
                == len(export_top_references)
                == len(design_top_references)
            ):
                _fail("RESTORE_VNEXT_GATE_INVALID", "top-level path references differ")
            for original, design, exported in zip(
                original_references, design_top_references, export_top_references
            ):
                if _ENVIRONMENT_VARIABLE.search(original.raw):
                    expected = original.raw
                elif Path(original.raw).is_absolute():
                    suffix = original.raw.lstrip("/")
                    expected = "$OUT" if not suffix else f"$OUT/{suffix}"
                elif original.kind == "filelist":
                    _child_key, expected_relative = design_child(design.relative)
                    expected = f"$OUT/{expected_relative}"
                else:
                    if design.relative is None:
                        _fail("RESTORE_VNEXT_GATE_INVALID", "design path reference is invalid")
                    expected = "$OUT" if design.relative == "." else f"$OUT/{design.relative}"
                if exported.raw != expected:
                    _fail("RESTORE_VNEXT_GATE_INVALID", "export path token differs from input rule")

        for design, exported in zip(design_view.references, export_view.references):
            if design.relative is None:
                _fail("RESTORE_VNEXT_GATE_INVALID", "design path reference is invalid")
            if exported.kind == "filelist":
                child_key, expected_nested = design_child(design.relative)
                if _is_export_environment_token(exported.raw):
                    add_alias(file_aliases, child_key, expected_nested)
                elif exported.relative is not None and exported.relative != expected_nested:
                    add_alias(file_aliases, exported.relative, expected_nested)
                elif exported.relative is None:
                    _fail("RESTORE_VNEXT_GATE_INVALID", "export nested filelist path is invalid")
                continue
            if exported.relative is None:
                if not _is_export_environment_token(exported.raw):
                    _fail("RESTORE_VNEXT_GATE_INVALID", "export path reference is invalid")
                continue
            if exported.relative == design.relative:
                continue
            if exported.kind == "directory":
                add_alias(directory_aliases, exported.relative, design.relative)
            else:
                add_alias(file_aliases, exported.relative, design.relative)

        physical_files = _files(source_set)
        for alias, source in directory_aliases.items():
            for physical in physical_files:
                if source == ".":
                    suffix = physical
                elif physical.startswith(f"{source}/"):
                    suffix = physical[len(source) + 1 :]
                else:
                    continue
                add_alias(file_aliases, f"{alias}/{suffix}" if suffix else alias, physical)

        nested = (
            *design_view.nested_files,
            *export_view.nested_files,
            *snapshot_paths,
        )
        known_sources = set(physical_files) | set(nested)

        def gate_regular_file(relative: str) -> Path:
            if not _portable_file(relative):
                _fail("RESTORE_VNEXT_GATE_INVALID", "delivery alias path is invalid")
            candidate = gate_path / relative
            current = gate_path.resolve()
            try:
                candidate.resolve().relative_to(current)
            except (OSError, RuntimeError, ValueError) as error:
                _fail("RESTORE_VNEXT_GATE_INVALID", f"delivery alias escapes gate: {error}")
            parts = Path(relative).parts
            for part in parts:
                current = current / part
                if current.is_symlink():
                    _fail("RESTORE_VNEXT_GATE_INVALID", "delivery alias must be a regular physical file")
            if not candidate.is_file():
                _fail("RESTORE_VNEXT_GATE_INVALID", f"delivery alias file is missing: {relative}")
            return candidate

        for alias, source in file_aliases.items():
            if source not in known_sources:
                _fail("RESTORE_VNEXT_GATE_INVALID", "delivery alias source is outside gate inventory")
            alias_path = gate_regular_file(alias)
            source_path = gate_regular_file(source)
            try:
                if alias_path.read_bytes() != source_path.read_bytes():
                    _fail("RESTORE_VNEXT_GATE_INVALID", "delivery alias content differs")
            except OSError as error:
                _fail("RESTORE_VNEXT_GATE_INVALID", str(error))

        for alias in directory_aliases:
            if alias == ".":
                continue
            directory = gate_path / alias
            try:
                directory.resolve().relative_to(gate_path.resolve())
            except (OSError, RuntimeError, ValueError) as error:
                _fail("RESTORE_VNEXT_GATE_INVALID", f"delivery directory alias escapes gate: {error}")
            current = gate_path.resolve()
            for part in Path(alias).parts:
                current = current / part
                if current.is_symlink():
                    _fail("RESTORE_VNEXT_GATE_INVALID", "delivery directory alias must be physical")
            if not directory.is_dir():
                _fail("RESTORE_VNEXT_GATE_INVALID", "delivery directory alias is missing")

        return (*nested, *file_aliases.keys())
    if design != _context_filelist_lines(source_set, root=gate_path):
        _fail("RESTORE_VNEXT_GATE_INVALID", "gate design.f differs from delivery context")
    if _read_filelist_lines(export_path) != _context_filelist_lines(
        source_set, environment_root="$OUT"
    ):
        _fail("RESTORE_VNEXT_GATE_INVALID", "export filelist differs from delivery context")
    _validate_original_filelist(_read_filelist_lines(original_path), source_set)
    return ()


def _validate_per_file(execution: dict[str, object], records: tuple[MappingRecord, ...], files: tuple[str, ...], gate_data: dict[str, bytes]) -> dict[str, list[tuple[int, int, bytes]]]:
    per_file = execution.get("per_file_mapping")
    if not isinstance(per_file, list) or len(per_file) != len(files):
        _fail("RESTORE_VNEXT_REPORT_INVALID", "per-file mapping is invalid")
    by_id = {record.symbol_id: record for record in records}
    expected: set[tuple[str, str, SourceRange]] = set()
    for record in records:
        expected.add((record.symbol_id, "declaration", record.declaration))
        expected.update((record.symbol_id, item.provenance, item.source_range) for item in record.occurrences)
    seen: set[tuple[str, str, SourceRange]] = set()
    ranges: dict[str, list[tuple[int, int, bytes]]] = {file: [] for file in files}
    for item, file in zip(per_file, files):
        if not isinstance(item, dict) or set(item) != {"file", "input_sha256", "gate_sha256", "records"} or item["file"] != file:
            _fail("RESTORE_VNEXT_REPORT_INVALID", "per-file mapping order is invalid")
        if not isinstance(item["records"], list):
            _fail("RESTORE_VNEXT_REPORT_INVALID", "per-file records are invalid")
        for projected in item["records"]:
            if not isinstance(projected, dict) or set(projected) != {"symbol_id", "category", "action", "reason", "original_name", "renamed_name", "owner_module", "semantic_owner", "impact", "abi", "ranges"}:
                _fail("RESTORE_VNEXT_REPORT_INVALID", "per-file record schema is invalid")
            record = by_id.get(projected["symbol_id"])
            if record is None:
                _fail("RESTORE_VNEXT_REPORT_INVALID", "per-file record references unknown symbol")
            for key in ("category", "action", "reason", "original_name", "renamed_name", "owner_module", "semantic_owner", "impact", "abi"):
                if projected[key] != getattr(record, key):
                    _fail("RESTORE_VNEXT_REPORT_INVALID", "per-file record differs from mapping")
            if not isinstance(projected["ranges"], list):
                _fail("RESTORE_VNEXT_REPORT_INVALID", "per-file ranges are invalid")
            for item_range in projected["ranges"]:
                if not isinstance(item_range, dict) or set(item_range) != {"provenance", "source_range", "gate_range"}:
                    _fail("RESTORE_VNEXT_REPORT_INVALID", "per-file range schema is invalid")
                provenance = item_range["provenance"]
                source_range = _parse_range(item_range["source_range"], label="per-file source range")
                gate_range = _parse_range(item_range["gate_range"], label="per-file gate range")
                key = (record.symbol_id, provenance, source_range)
                if key in seen or key not in expected or source_range.file != file or gate_range.file != file:
                    _fail("RESTORE_VNEXT_REPORT_INVALID", "per-file range coverage is invalid")
                seen.add(key)
                if record.action == "rename":
                    renamed = record.renamed_name
                    if not isinstance(renamed, str) or gate_range.end - gate_range.start != len(renamed.encode()) or gate_data[file][gate_range.start:gate_range.end] != renamed.encode():
                        _fail("RESTORE_VNEXT_GATE_INVALID", "gate bytes do not match rename range")
                    ranges[file].append((gate_range.start, gate_range.end, record.original_name.encode()))
    if seen != expected:
        _fail("RESTORE_VNEXT_REPORT_INVALID", "per-file mapping does not cover all ranges")
    for file, values in ranges.items():
        values.sort()
        if any(previous[1] > current[0] for previous, current in zip(values, values[1:])):
            _fail("RESTORE_VNEXT_GATE_INVALID", f"gate rename ranges overlap in {file}")
    return ranges


def _restore_data(gate_data: dict[str, bytes], records: tuple[MappingRecord, ...], ranges: dict[str, list[tuple[int, int, bytes]]]) -> dict[str, bytes]:
    result = dict(gate_data)
    for file, file_ranges in ranges.items():
        mutable = bytearray(result[file])
        for start, end, replacement in sorted(file_ranges, reverse=True):
            mutable[start:end] = replacement
        result[file] = bytes(mutable)
    return result


def _load_inputs(report_path: Path, gate_path: Path) -> tuple[dict[str, object], SourceSet, tuple[str, ...], dict[str, bytes], tuple[MappingRecord, ...], dict[str, list[tuple[int, int, bytes]]]]:
    report = _read_json(report_path)
    expected_outer = {"format", "schema_version", "state", "source_set", "mapping", "mapping_execution", "metrics", "rate_metrics", "summary"}
    manifest_present = "delivery_filelists" in report
    if (
        set(report) != expected_outer | ({"delivery_filelists"} if manifest_present else set())
        or report.get("format") != "rtl-obfuscation.orchestration-vnext"
        or report.get("schema_version") != 2
        or report.get("state") != "restored"
    ):
        if report.get("schema_version") == 1:
            _fail("RESTORE_MAPPING_VERSION_UNSUPPORTED", "schema 1 orchestration reports are not supported")
        _fail("RESTORE_VNEXT_REPORT_INVALID", "orchestration report format, schema, or state is invalid")
    source_set = _parse_source_set(report["source_set"], gate_path)
    files = _files(source_set)
    nested_filelists = _validate_gate_filelists(
        gate_path,
        source_set,
        report.get("delivery_filelists"),
        manifest_present=manifest_present,
    )
    _validate_gate_files(gate_path, files, report_path, nested_filelists)
    gate_data = _read_files(gate_path, files)
    original_records = _parse_mapping_report(report["mapping"], source_set=source_set, source_data=None)
    execution = report.get("mapping_execution")
    if not isinstance(execution, dict) or not isinstance(execution.get("mapping"), dict):
        _fail("RESTORE_VNEXT_REPORT_INVALID", "mapping execution report is invalid")
    # Original mapping ranges are source coordinates.  The gate mapping carries
    # the same source evidence, so parse both against the gate bytes only after
    # validating the actual gate ranges in the execution projection.
    effective_records = _parse_mapping_report(execution["mapping"], source_set=source_set, source_data=None)
    gate_manifest = _parse_manifest(execution.get("gate_manifest"), files, label="gate_manifest")
    if gate_manifest != _manifest(gate_data, files):
        _fail("RESTORE_VNEXT_GATE_INVALID", "gate manifest differs from gate bytes")
    ranges = _validate_per_file(execution, effective_records, files, gate_data)
    restored_data = _restore_data(gate_data, effective_records, ranges)
    input_manifest = _parse_manifest(report["mapping"].get("input_manifest"), files, label="mapping input_manifest")
    if _manifest(restored_data, files) != input_manifest:
        _fail("RESTORE_VNEXT_REPORT_INVALID", "restored bytes differ from input manifest")
    return report, source_set, files, gate_data, effective_records, ranges


@dataclass(frozen=True)
class RestoreVNext:
    schema_version: int
    source_set: SourceSet
    mapping_vnext: Any
    effective_mapping_vnext: Any
    mapping_execution: Any
    metrics: Any
    restore_result: Any
    rate_enabled: bool
    report: dict[str, object]

    def to_report(self) -> dict[str, object]:
        return self.report


@dataclass(frozen=True)
class OrchestrationGateAuditVNext:
    schema_version: int
    source_set: SourceSet
    effective_records: tuple[MappingRecord, ...]
    input_manifest: tuple[InputFileDigest, ...]
    gate_manifest: tuple[InputFileDigest, ...]


def _restore_report(source_set: SourceSet, files: tuple[str, ...], gate_data: dict[str, bytes], restored_data: dict[str, bytes], rate_enabled: bool) -> dict[str, object]:
    return {
        "format": "rtl-obfuscation.restore-vnext", "schema_version": 2, "state": "restored",
        "source_set": _source_set_report(source_set),
        "gate_manifest": [{"file": item.file, "sha256": item.sha256} for item in _manifest(gate_data, files)],
        "restored_manifest": [{"file": item.file, "sha256": item.sha256} for item in _manifest(restored_data, files)],
        "summary": {"files": len(files), "restored_input_manifest_equal": True, "restored_byte_identical": True, "rate_enabled": rate_enabled},
    }


def _materialize(report_path: Path, gate_path: Path, output_path: Path) -> RestoreVNext:
    report, source_set, files, gate_data, records, ranges = _load_inputs(report_path, gate_path)
    restored_data = _restore_data(gate_data, records, ranges)
    try:
        staging = Path(tempfile.mkdtemp(prefix=".restore-vnext-", dir=str(output_path.parent)))
        for file in files:
            destination = staging / file
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(restored_data[file])
        staging.rename(output_path)
    except OSError as error:
        if "staging" in locals() and staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        _fail("RESTORE_VNEXT_IO_ERROR", str(error))
    restore_report = _restore_report(source_set, files, gate_data, restored_data, report.get("rate_metrics") is not None)
    return RestoreVNext(2, source_set, None, None, None, None, None, report.get("rate_metrics") is not None, restore_report)


def load_direct_restore_vnext(map_file: Path, *, gate_dir: Path, output_dir: Path) -> RestoreVNext:
    map_path, gate_path, output_path, _ = validate_direct_restore_paths_vnext(map_file, gate_dir, output_dir)
    return _materialize(map_path, gate_path, output_path)


def load_restore_vnext(map_file: Path, *, gate_dir: Path, source_root: Path, output_dir: Path) -> RestoreVNext:
    map_path, gate_path, source_path, output_path, _ = _validate_paths(map_file, gate_dir, source_root, output_dir)
    result = _materialize(map_path, gate_path, output_path)
    files = _files(result.source_set)
    original = _read_files(source_path, files)
    expected = _parse_manifest(result.report["restored_manifest"], files, label="restored_manifest")
    if expected != _manifest(original, files):
        _fail("RESTORE_VNEXT_INPUT_INVALID", "source-root bytes differ from mapping input manifest")
    return result


def audit_orchestration_gate_vnext(report_file: Path, *, gate_dir: Path) -> OrchestrationGateAuditVNext:
    report_path = _resolve(report_file, "RESTORE_VNEXT_INPUT_INVALID")
    gate_path = _resolve(gate_dir, "RESTORE_VNEXT_GATE_INVALID")
    report, source_set, files, gate_data, records, _ranges = _load_inputs(report_path, gate_path)
    input_manifest = _parse_manifest(report["mapping"].get("input_manifest"), files, label="mapping input_manifest")
    execution = report["mapping_execution"]
    assert isinstance(execution, dict)
    gate_manifest = _parse_manifest(execution.get("gate_manifest"), files, label="gate_manifest")
    return OrchestrationGateAuditVNext(2, source_set, records, input_manifest, gate_manifest)


def write_restore_report_vnext(restore: RestoreVNext, output_file: Path) -> None:
    path = _resolve(output_file, "RESTORE_VNEXT_OUTPUT_INVALID")
    if path.exists() or path.is_symlink() or not path.parent.is_dir():
        _fail("RESTORE_VNEXT_OUTPUT_INVALID", "report output is invalid")
    try:
        path.write_text(json.dumps(restore.to_report(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, TypeError, ValueError) as error:
        _fail("RESTORE_VNEXT_IO_ERROR", str(error))


def publish_restore_vnext(artifacts: list[tuple[Path, Path]]) -> None:
    prepared: list[tuple[Path, Path]] = []
    try:
        for source, target_value in artifacts:
            target = _resolve(target_value, "RESTORE_VNEXT_OUTPUT_INVALID")
            if target.exists() or target.is_symlink() or not target.parent.is_dir():
                _fail("RESTORE_VNEXT_OUTPUT_INVALID", "publish target is invalid")
            container = Path(tempfile.mkdtemp(prefix=".restore-publish-", dir=str(target.parent)))
            payload = container / "payload"
            if source.is_dir():
                shutil.copytree(source, payload)
            else:
                shutil.copy2(source, payload)
            prepared.append((container, target))
        for container, target in prepared:
            (container / "payload").replace(target)
    except RestoreVNextError:
        raise
    except (OSError, shutil.Error) as error:
        _fail("RESTORE_VNEXT_IO_ERROR", str(error))
    finally:
        for container, _target in prepared:
            shutil.rmtree(container, ignore_errors=True)


__all__ = [
    "OrchestrationGateAuditVNext", "RestoreVNext", "RestoreVNextError",
    "audit_orchestration_gate_vnext", "load_direct_restore_vnext", "load_restore_vnext",
    "publish_restore_vnext", "validate_direct_restore_paths_vnext", "write_restore_report_vnext",
]
