"""Persistent T053 report hydration and vNext restore auditing."""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal, ROUND_CEILING
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any

from .mapping_vnext import InputFileDigest, MappingRecord, MappingVNext
from .metrics_vnext import MetricsVNext, MetricsVNextError, build_metrics_vnext
from .rewrite_policy import RewriteDecision, RewritePolicy, build_rewrite_policy
from .rewrite_vnext import (
    AppliedEdit,
    CompileEvidence,
    MappingExecutionVNext,
    RestoreResult,
    RewriteExecution,
    RewriteVNextError,
    _expected_edits,
    build_mapping_execution_vnext,
    restore_gate_vnext,
)
from .source_catalog import SourceCatalogError, SourceRange, build_source_catalog
from .source_set import SourceSet
from .symbol_graph import SourceSymbol, SymbolGraphError, SymbolOccurrence, build_symbol_graph


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_PRIVATE_KEYS = frozenset({"source_root", "gate_dir", "restore_dir", "output_dir"})


class RestoreVNextError(ValueError):
    """Stable fail-closed error for persistent vNext restore."""

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
        for key, item in value.items():
            if key in _PRIVATE_KEYS or key == "TemporaryDirectory":
                return False
            if not _portable_value(item):
                return False
        return True
    if isinstance(value, list):
        return all(_portable_value(item) for item in value)
    if isinstance(value, float) and not math.isfinite(value):
        return False
    if isinstance(value, str):
        return not value.startswith("/") and re.match(r"^[A-Za-z]:[\\/]", value) is None
    return True


def _report_source_set(source_set: SourceSet) -> dict[str, object]:
    return {
        "schema_version": source_set.schema_version,
        "origin": source_set.origin,
        "ordered_source_files": list(source_set.ordered_source_files),
        "included_files": list(source_set.included_files),
        "include_dirs": list(source_set.include_dirs),
        "defines": [
            {"name": name, "value": value} for name, value in source_set.defines
        ],
        "top": source_set.top,
        "top_closure_files": list(source_set.top_closure_files),
        "compile_order": list(source_set.compile_order),
    }


def _mapping_source_set(source_set: SourceSet) -> dict[str, object]:
    report = _report_source_set(source_set)
    report.pop("origin")
    return report


def _read_json(path: Path) -> dict[str, object]:
    try:
        with path.open(encoding="utf-8") as stream:
            value = json.load(stream)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        _fail("RESTORE_VNEXT_IO_ERROR", str(error))
    if not isinstance(value, dict):
        _fail("RESTORE_VNEXT_REPORT_INVALID", "report root is not an object")
    if not _portable_value(value):
        _fail("RESTORE_VNEXT_REPORT_INVALID", "report contains a private or absolute path")
    return value


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


def _validate_paths(
    map_file: Path,
    gate_dir: Path,
    source_root: Path,
    output_dir: Path,
    report_file: Path | None = None,
) -> tuple[Path, Path, Path, Path, Path | None]:
    map_path = _resolve(map_file, "RESTORE_VNEXT_INPUT_INVALID")
    gate_path = _resolve(gate_dir, "RESTORE_VNEXT_GATE_INVALID")
    source_path = _resolve(source_root, "RESTORE_VNEXT_INPUT_INVALID")
    output_path = _resolve(output_dir, "RESTORE_VNEXT_OUTPUT_INVALID")
    report_path = None if report_file is None else _resolve(report_file, "RESTORE_VNEXT_OUTPUT_INVALID")
    if not map_path.is_file():
        _fail("RESTORE_VNEXT_INPUT_INVALID", "map is not a regular file")
    if not source_path.is_dir():
        _fail("RESTORE_VNEXT_INPUT_INVALID", "source-root is not a directory")
    if not gate_path.is_dir():
        _fail("RESTORE_VNEXT_GATE_INVALID", "gate-dir is not a directory")
    for path, label in ((output_path, "output-dir"), *(([(report_path, "report")] if report_path else []))):
        if path.exists() or path.is_symlink() or not path.parent.is_dir():
            _fail("RESTORE_VNEXT_OUTPUT_INVALID", label)
    protected = (source_path, gate_path, map_path)
    targets = (output_path,) if report_path is None else (output_path, report_path)
    for target in targets:
        if any(_overlap(target, protected_path) for protected_path in protected):
            _fail("RESTORE_VNEXT_OUTPUT_INVALID", "output overlaps an input")
    if report_path is not None and _overlap(output_path, report_path):
        _fail("RESTORE_VNEXT_OUTPUT_INVALID", "output and report overlap")
    return map_path, gate_path, source_path, output_path, report_path


def validate_direct_restore_paths_vnext(
    map_file: Path,
    gate_dir: Path,
    output_dir: Path,
    report_file: Path | None = None,
) -> tuple[Path, Path, Path, Path | None]:
    """Validate public restore paths without requiring the original source tree."""
    map_path = _resolve(map_file, "RESTORE_VNEXT_INPUT_INVALID")
    gate_path = _resolve(gate_dir, "RESTORE_VNEXT_GATE_INVALID")
    output_path = _resolve(output_dir, "RESTORE_VNEXT_OUTPUT_INVALID")
    report_path = (
        None
        if report_file is None
        else _resolve(report_file, "RESTORE_VNEXT_OUTPUT_INVALID")
    )
    if not map_path.is_file():
        _fail("RESTORE_VNEXT_INPUT_INVALID", "map is not a regular file")
    if not gate_path.is_dir():
        _fail("RESTORE_VNEXT_GATE_INVALID", "gate-dir is not a directory")
    targets = (output_path,) if report_path is None else (output_path, report_path)
    for path, label in (
        (output_path, "output-dir"),
        *(([(report_path, "report")] if report_path else [])),
    ):
        if path.exists() or path.is_symlink() or not path.parent.is_dir():
            _fail("RESTORE_VNEXT_OUTPUT_INVALID", label)
    for target in targets:
        if _overlap(target, gate_path) or _overlap(target, map_path):
            _fail("RESTORE_VNEXT_OUTPUT_INVALID", "output overlaps an input")
    if report_path is not None and _overlap(output_path, report_path):
        _fail("RESTORE_VNEXT_OUTPUT_INVALID", "output and report overlap")
    return map_path, gate_path, output_path, report_path


def _validate_gate_file_set(
    report_path: Path,
    gate_path: Path,
    report: dict[str, object],
    files: tuple[str, ...],
) -> None:
    expected = {*files, "design.f"}
    default_map = gate_path / "mapping.json"
    if default_map.exists() or default_map.is_symlink():
        if (
            default_map.is_symlink()
            or not default_map.is_file()
            or report_path != default_map.resolve()
        ):
            _fail("RESTORE_VNEXT_GATE_INVALID", "default mapping report is invalid")
        expected.add("mapping.json")
    default_metrics = gate_path / "metrics.json"
    if default_metrics.exists() or default_metrics.is_symlink():
        if default_metrics.is_symlink() or not default_metrics.is_file():
            _fail("RESTORE_VNEXT_GATE_INVALID", "default metrics report is invalid")
        if _read_json(default_metrics) != report.get("metrics"):
            _fail(
                "RESTORE_VNEXT_REPORT_INVALID",
                "default metrics differ from the mapping report",
            )
        expected.add("metrics.json")
    for derived_name in ("mapping_table.csv", "encryption_summary.txt"):
        derived_path = gate_path / derived_name
        if derived_path.exists() or derived_path.is_symlink():
            if derived_path.is_symlink() or not derived_path.is_file():
                _fail("RESTORE_VNEXT_GATE_INVALID", f"derived artifact is invalid: {derived_name}")
            expected.add(derived_name)
    actual = {
        path.relative_to(gate_path).as_posix()
        for path in gate_path.rglob("*")
        if path.is_file() or path.is_symlink()
    }
    if actual != expected:
        _fail("RESTORE_VNEXT_GATE_INVALID", "actual gate file set is invalid")


def _parse_source_set(value: object, source_root: Path) -> SourceSet:
    if not isinstance(value, dict):
        _fail("RESTORE_VNEXT_INPUT_INVALID", "source_set is not an object")
    expected_keys = {
        "schema_version",
        "origin",
        "ordered_source_files",
        "included_files",
        "include_dirs",
        "defines",
        "top",
        "top_closure_files",
        "compile_order",
    }
    if set(value) != expected_keys:
        _fail("RESTORE_VNEXT_INPUT_INVALID", "source_set schema is invalid")
    if value["schema_version"] != 1 or value["origin"] not in {"single-file", "filelist", "project-root"}:
        _fail("RESTORE_VNEXT_INPUT_INVALID", "source_set schema or origin is invalid")
    sequences = [
        value["ordered_source_files"],
        value["included_files"],
        value["include_dirs"],
        value["top_closure_files"],
        value["compile_order"],
    ]
    if any(not isinstance(sequence, list) or not all(isinstance(item, str) for item in sequence) for sequence in sequences):
        _fail("RESTORE_VNEXT_INPUT_INVALID", "source_set sequence is invalid")
    if any(not _portable_file(item) for item in (*value["ordered_source_files"], *value["included_files"], *value["include_dirs"], *value["top_closure_files"], *value["compile_order"])):
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
    if value["origin"] == "project-root" and not isinstance(top, str):
        _fail("RESTORE_VNEXT_INPUT_INVALID", "project-root source_set requires top")
    return SourceSet(
        schema_version=1,
        origin=value["origin"],
        source_root=source_root,
        ordered_source_files=tuple(value["ordered_source_files"]),
        included_files=tuple(value["included_files"]),
        include_dirs=tuple(value["include_dirs"]),
        defines=tuple(defines),
        top=top,
        top_closure_files=tuple(value["top_closure_files"]),
        compile_order=tuple(value["compile_order"]),
    )


def _parse_range(value: object, *, label: str) -> SourceRange:
    if not isinstance(value, dict) or set(value) != {"file", "start", "end"}:
        _fail("RESTORE_VNEXT_REPORT_INVALID", f"{label} schema is invalid")
    if not _portable_file(value["file"]) or type(value["start"]) is not int or type(value["end"]) is not int or value["start"] < 0 or value["start"] >= value["end"]:
        _fail("RESTORE_VNEXT_REPORT_INVALID", f"{label} range is invalid")
    return SourceRange(value["file"], value["start"], value["end"])


def _parse_manifest(value: object, files: tuple[str, ...], *, label: str) -> tuple[InputFileDigest, ...]:
    if not isinstance(value, list) or len(value) != len(files):
        _fail("RESTORE_VNEXT_REPORT_INVALID", f"{label} shape is invalid")
    result: list[InputFileDigest] = []
    for item, file in zip(value, files):
        if not isinstance(item, dict) or set(item) != {"file", "sha256"} or item["file"] != file or not isinstance(item["sha256"], str) or _SHA256.fullmatch(item["sha256"]) is None:
            _fail("RESTORE_VNEXT_REPORT_INVALID", f"{label} order or hash is invalid")
        result.append(InputFileDigest(file=file, sha256=item["sha256"]))
    return tuple(result)


def _parse_occurrences(value: object, symbol: SourceSymbol) -> tuple[SymbolOccurrence, ...]:
    if not isinstance(value, list) or len(value) != len(symbol.occurrences):
        _fail("RESTORE_VNEXT_REPORT_INVALID", "occurrences shape is invalid")
    result: list[SymbolOccurrence] = []
    for item, expected in zip(value, symbol.occurrences):
        if not isinstance(item, dict) or set(item) != {"source_range", "provenance"} or not isinstance(item["provenance"], str):
            _fail("RESTORE_VNEXT_REPORT_INVALID", "occurrence schema is invalid")
        source_range = _parse_range(item["source_range"], label="occurrence")
        actual = SymbolOccurrence(source_range=source_range, provenance=item["provenance"])
        if actual != expected:
            _fail("RESTORE_VNEXT_REPORT_INVALID", "occurrence differs from rebuilt graph")
        result.append(actual)
    return tuple(result)


def _hydrate_mapping(
    report: object,
    *,
    source_set: SourceSet,
    graph: object,
    policy: RewritePolicy,
    source_data: dict[str, bytes],
    require_policy_action: bool,
) -> tuple[MappingVNext, tuple[RewriteDecision, ...]]:
    if not isinstance(report, dict) or report.get("format") != "rtl-obfuscation.mapping-vnext" or report.get("schema_version") != 1 or report.get("state") != "planned":
        _fail("RESTORE_VNEXT_REPORT_INVALID", "mapping report format, schema, or state is invalid")
    if report.get("source_set") != _mapping_source_set(source_set):
        _fail("RESTORE_VNEXT_REPORT_INVALID", "mapping source_set differs from input source_set")
    selection = report.get("selection")
    if not isinstance(selection, dict) or set(selection) != {"selected_categories", "abi_categories", "preserve_top_boundary"} or selection["preserve_top_boundary"] is not True or selection["selected_categories"] != list(policy.selected_categories) or selection["abi_categories"] != list(policy.abi_categories):
        _fail("RESTORE_VNEXT_REPORT_INVALID", "mapping selection differs from rebuilt policy")
    if type(report.get("name_length")) is not int or report["name_length"] < 4:
        _fail("RESTORE_VNEXT_REPORT_INVALID", "mapping name_length is invalid")
    files = tuple(dict.fromkeys((*source_set.ordered_source_files, *source_set.included_files)))
    input_manifest = _parse_manifest(report.get("input_manifest"), files, label="mapping input_manifest")
    actual_manifest = tuple(
        InputFileDigest(file=file, sha256=hashlib.sha256(source_data[file]).hexdigest())
        for file in files
    )
    if input_manifest != actual_manifest:
        _fail("RESTORE_VNEXT_REPORT_INVALID", "source bytes differ from mapping input manifest")
    if not isinstance(graph, type(policy.symbol_graph)) or not isinstance(report.get("records"), list) or len(report["records"]) != len(graph.symbols):
        _fail("RESTORE_VNEXT_REPORT_INVALID", "mapping records are invalid")
    records: list[MappingRecord] = []
    decisions: list[RewriteDecision] = []
    for item, symbol, canonical_decision in zip(report["records"], graph.symbols, policy.decisions):
        if not isinstance(item, dict) or set(item) != {
            "symbol_id", "category", "action", "reason", "original_name", "renamed_name",
            "owner_module", "semantic_owner", "declaration", "occurrences", "impact", "abi",
        }:
            _fail("RESTORE_VNEXT_REPORT_INVALID", "mapping record schema is invalid")
        declaration = _parse_range(item["declaration"], label="declaration")
        occurrences = _parse_occurrences(item["occurrences"], symbol)
        if (
            item["symbol_id"] != symbol.symbol_id
            or item["category"] != symbol.category
            or item["original_name"] != symbol.name
            or item["owner_module"] != symbol.owner_module
            or item["semantic_owner"] != symbol.semantic_owner
            or declaration != symbol.declaration
            or item["impact"] != symbol.impact
            or item["abi"] != symbol.abi
        ):
            _fail("RESTORE_VNEXT_REPORT_INVALID", "mapping record differs from rebuilt graph")
        action = item["action"]
        reason = item["reason"]
        renamed_name = item["renamed_name"]
        if action not in {"rename", "preserve", "unsupported"} or (action == "rename" and (not isinstance(renamed_name, str) or not renamed_name)) or (action != "rename" and renamed_name is not None):
            _fail("RESTORE_VNEXT_REPORT_INVALID", "mapping record action or name is invalid")
        if require_policy_action and (action != canonical_decision.action or reason != canonical_decision.reason):
            _fail("RESTORE_VNEXT_REPORT_INVALID", "mapping record differs from canonical policy")
        if action != "rename" and reason is not None and not isinstance(reason, str):
            _fail("RESTORE_VNEXT_REPORT_INVALID", "mapping record reason is invalid")
        records.append(
            MappingRecord(
                symbol_id=symbol.symbol_id,
                category=symbol.category,
                action=action,
                reason=reason,
                original_name=symbol.name,
                renamed_name=renamed_name,
                owner_module=symbol.owner_module,
                semantic_owner=symbol.semantic_owner,
                declaration=declaration,
                occurrences=occurrences,
                impact=symbol.impact,
                abi=symbol.abi,
            )
        )
        decisions.append(replace(canonical_decision, action=action, reason=reason))
    hydrated_policy = replace(policy, decisions=tuple(decisions))
    mapping = MappingVNext(
        format="rtl-obfuscation.mapping-vnext",
        schema_version=1,
        rewrite_policy=hydrated_policy,
        name_length=report["name_length"],
        input_manifest=input_manifest,
        records=tuple(records),
    )
    try:
        if mapping.to_report() != report:
            _fail("RESTORE_VNEXT_REPORT_INVALID", "mapping report canonical projection differs")
    except RestoreVNextError:
        raise
    except Exception as error:
        _fail("RESTORE_VNEXT_REPORT_INVALID", str(error))
    return mapping, tuple(decisions)


def _validate_effective_mapping(original: MappingVNext, effective: MappingVNext, rate_enabled: bool) -> None:
    if len(original.records) != len(effective.records):
        _fail("RESTORE_VNEXT_REPORT_INVALID", "effective mapping record count differs")
    for original_record, effective_record in zip(original.records, effective.records):
        if (
            original_record.symbol_id != effective_record.symbol_id
            or original_record.declaration != effective_record.declaration
            or original_record.occurrences != effective_record.occurrences
            or original_record.owner_module != effective_record.owner_module
            or original_record.semantic_owner != effective_record.semantic_owner
        ):
            _fail("RESTORE_VNEXT_REPORT_INVALID", "effective mapping range or owner differs")
        if not rate_enabled:
            if effective_record != original_record:
                _fail("RESTORE_VNEXT_REPORT_INVALID", "no-rate effective mapping differs")
        elif original_record.action == "rename":
            if effective_record.action == "rename":
                if effective_record.renamed_name != original_record.renamed_name or effective_record.reason is not None:
                    _fail("RESTORE_VNEXT_REPORT_INVALID", "selected mapping differs from original rename")
            elif effective_record.action == "preserve" and effective_record.reason == "rate_unselected" and effective_record.renamed_name is None:
                continue
            else:
                _fail("RESTORE_VNEXT_REPORT_INVALID", "rate-unselected mapping is invalid")
        elif effective_record != original_record:
            _fail("RESTORE_VNEXT_REPORT_INVALID", "preserve or unsupported mapping changed")


def _range_lines(source_range: SourceRange, content: bytes) -> tuple[tuple[str, int], ...]:
    if not 0 <= source_range.start < source_range.end <= len(content):
        _fail("RESTORE_VNEXT_REPORT_INVALID", "rate candidate range is outside source bytes")
    lines: set[tuple[str, int]] = set()
    offset = 0
    for line_number, line in enumerate(content.splitlines(keepends=True), start=1):
        end = offset + len(line)
        if source_range.start < end and source_range.end > offset:
            lines.add((source_range.file, line_number))
        offset = end
    if not lines:
        _fail("RESTORE_VNEXT_REPORT_INVALID", "rate candidate range has no physical line")
    return tuple(sorted(lines, key=lambda item: (item[0], item[1])))


def _candidate_lines(record: MappingRecord, source_data: dict[str, bytes]) -> tuple[tuple[str, int], ...]:
    lines: set[tuple[str, int]] = set()
    for source_range in (record.declaration, *(occurrence.source_range for occurrence in record.occurrences)):
        lines.update(_range_lines(source_range, source_data[source_range.file]))
    return tuple(sorted(lines, key=lambda item: (item[0], item[1])))


def _hydrate_execution(
    execution_report: object,
    *,
    effective_mapping: MappingVNext,
    orchestration_summary: object,
) -> MappingExecutionVNext:
    if not isinstance(execution_report, dict) or set(execution_report) != {
        "format", "schema_version", "state", "mapping", "filelist", "input_manifest",
        "gate_manifest", "restored_manifest", "per_file_mapping", "summary",
    } or execution_report.get("format") != "rtl-obfuscation.mapping-execution-vnext" or execution_report.get("schema_version") != 1 or execution_report.get("state") != "restored" or execution_report.get("filelist") != "design.f":
        _fail("RESTORE_VNEXT_REPORT_INVALID", "mapping execution report schema is invalid")
    if not isinstance(orchestration_summary, dict) or orchestration_summary.get("strict_compile_passed") is not True:
        _fail("RESTORE_VNEXT_REPORT_INVALID", "strict compile evidence is not verified")
    files = tuple(dict.fromkeys((*effective_mapping.rewrite_policy.symbol_graph.source_catalog.source_set.ordered_source_files, *effective_mapping.rewrite_policy.symbol_graph.source_catalog.source_set.included_files)))
    input_manifest = _parse_manifest(execution_report["input_manifest"], files, label="execution input_manifest")
    gate_manifest = _parse_manifest(execution_report["gate_manifest"], files, label="execution gate_manifest")
    restored_manifest = _parse_manifest(execution_report["restored_manifest"], files, label="execution restored_manifest")
    if input_manifest != effective_mapping.input_manifest or restored_manifest != input_manifest:
        _fail("RESTORE_VNEXT_REPORT_INVALID", "execution manifest does not match mapping")
    edits = _expected_edits(effective_mapping, validate_canonical_policy=False)
    execution = RewriteExecution(
        schema_version=1,
        mapping_vnext=effective_mapping,
        filelist="design.f",
        gate_manifest=gate_manifest,
        edits=edits,
        compile_evidence=CompileEvidence(0, 0, 0, 0),
    )
    restore_result = RestoreResult(
        schema_version=1,
        rewrite_execution=execution,
        restored_manifest=restored_manifest,
    )
    try:
        mapping_execution = build_mapping_execution_vnext(execution, restore_result)
    except RewriteVNextError as error:
        _fail("RESTORE_VNEXT_REPORT_INVALID", error.message)
    try:
        if mapping_execution.to_report() != execution_report:
            _fail("RESTORE_VNEXT_REPORT_INVALID", "execution report canonical projection differs")
    except RestoreVNextError:
        raise
    except Exception as error:
        _fail("RESTORE_VNEXT_REPORT_INVALID", str(error))
    return mapping_execution


def _validate_rate_report(
    rate_report: object,
    *,
    original: MappingVNext,
    effective: MappingVNext,
    execution_report: dict[str, object],
    metrics_report: dict[str, object],
    source_data: dict[str, bytes],
) -> None:
    if not isinstance(rate_report, dict) or set(rate_report) != {"format", "schema_version", "state", "rate_selection", "mapping_execution", "metrics", "summary"} or rate_report.get("format") != "rtl-obfuscation.rate-metrics-vnext" or rate_report.get("schema_version") != 1 or rate_report.get("state") != "restored":
        _fail("RESTORE_VNEXT_REPORT_INVALID", "rate_metrics report schema is invalid")
    if rate_report["mapping_execution"] != execution_report or rate_report["metrics"] != metrics_report:
        _fail("RESTORE_VNEXT_REPORT_INVALID", "rate_metrics nested report differs")
    selection = rate_report["rate_selection"]
    if not isinstance(selection, dict) or selection.get("format") != "rtl-obfuscation.rate-selection-vnext" or selection.get("schema_version") != 1 or selection.get("state") != "planned" or selection.get("algorithm") != "greedy_unique_line_v1":
        _fail("RESTORE_VNEXT_REPORT_INVALID", "rate selection report is invalid")
    candidates = selection.get("candidates")
    rename_records = [record for record in original.records if record.action == "rename"]
    rename_records.sort(
        key=lambda record: (
            record.declaration.file,
            record.declaration.start,
            record.category,
            record.owner_module,
            record.original_name,
            record.symbol_id,
        )
    )
    if not isinstance(candidates, list) or selection.get("candidate_entries") != len(candidates) or len(candidates) != len(rename_records):
        _fail("RESTORE_VNEXT_REPORT_INVALID", "rate candidates do not cover original renames")
    effective_by_id = {record.symbol_id: record for record in effective.records}
    selected_line_union: set[tuple[str, int]] = set()
    candidate_line_union: set[tuple[str, int]] = set()
    for candidate, record in zip(candidates, rename_records):
        if not isinstance(candidate, dict) or set(candidate) != {
            "symbol_id", "category", "owner_module", "original_name", "declaration",
            "affected_lines", "affected_line_count", "selected",
        }:
            _fail("RESTORE_VNEXT_REPORT_INVALID", "rate candidate is invalid")
        if (
            candidate["symbol_id"] != record.symbol_id
            or candidate["category"] != record.category
            or candidate["owner_module"] != record.owner_module
            or candidate["original_name"] != record.original_name
            or _parse_range(candidate["declaration"], label="rate candidate") != record.declaration
            or type(candidate["selected"]) is not bool
        ):
            _fail("RESTORE_VNEXT_REPORT_INVALID", "rate candidate identity differs from mapping")
        expected_lines = _candidate_lines(record, source_data)
        actual_lines = candidate["affected_lines"]
        if not isinstance(actual_lines, list) or any(
            not isinstance(item, dict) or set(item) != {"file", "line"}
            or not _portable_file(item["file"])
            or type(item["line"]) is not int
            or item["line"] < 1
            for item in actual_lines
        ):
            _fail("RESTORE_VNEXT_REPORT_INVALID", "rate candidate affected_lines are invalid")
        parsed_lines = tuple((item["file"], item["line"]) for item in actual_lines)
        if parsed_lines != expected_lines or candidate["affected_line_count"] != len(expected_lines):
            _fail("RESTORE_VNEXT_REPORT_INVALID", "rate candidate affected_lines differ from source ranges")
        candidate_line_union.update(expected_lines)
        if candidate["selected"]:
            selected_line_union.update(expected_lines)
        expected_selected = effective_by_id[candidate["symbol_id"]].action == "rename"
        if candidate.get("selected") is not expected_selected:
            _fail("RESTORE_VNEXT_REPORT_INVALID", "rate candidate selection differs from effective mapping")
    total_lines = 0
    for content in source_data.values():
        total_lines += sum(
            line.strip() != b"" and not line.strip().startswith(b"//")
            for line in content.splitlines()
        )
    target = selection.get("target")
    if type(target) not in (int, float) or not math.isfinite(float(target)) or not 0 < float(target) <= 1:
        _fail("RESTORE_VNEXT_REPORT_INVALID", "rate target is invalid")
    target_lines = int((Decimal(str(target)) * Decimal(total_lines)).to_integral_value(rounding=ROUND_CEILING))
    candidate_lines = len(candidate_line_union)
    selected_lines = len(selected_line_union)
    target_unreachable = total_lines == 0 or candidate_lines == 0 or target_lines > candidate_lines
    selection_mode = "all_candidates" if target_unreachable else "greedy"
    if (
        selection.get("total_lines") != total_lines
        or selection.get("target_lines") != target_lines
        or selection.get("candidate_lines") != candidate_lines
        or selection.get("selected_lines") != selected_lines
        or selection.get("selected_entries") != sum(bool(item["selected"]) for item in candidates)
        or selection.get("target_unreachable") is not target_unreachable
        or selection.get("selection_mode") != selection_mode
        or selection.get("overshoot_lines") != max(0, selected_lines - target_lines)
        or selection.get("actual_rate") != (0.0 if total_lines == 0 else selected_lines / total_lines)
        or selection.get("maximum_rate") != (0.0 if total_lines == 0 else candidate_lines / total_lines)
    ):
        _fail("RESTORE_VNEXT_REPORT_INVALID", "rate selection equations are inconsistent")
    if target_unreachable and not all(item["selected"] for item in candidates):
        _fail("RESTORE_VNEXT_REPORT_INVALID", "unreachable rate target does not select all candidates")
    if not target_unreachable and selected_lines < target_lines:
        _fail("RESTORE_VNEXT_REPORT_INVALID", "rate target is not met")
    effective_records = effective.records
    summary = rate_report.get("summary")
    if not isinstance(summary, dict) or summary.get("files") != len(execution_report["gate_manifest"]) or summary.get("mapping_records") != len(effective_records) or summary.get("selected_renamed_records") != sum(record.action == "rename" for record in effective_records) or summary.get("rate_unselected_records") != sum(record.action == "preserve" and record.reason == "rate_unselected" for record in effective_records) or summary.get("modified_tokens") != len(_expected_edits(effective, validate_canonical_policy=False)) or summary.get("strict_compile_passed") is not True or summary.get("restored_byte_identical") is not True:
        _fail("RESTORE_VNEXT_REPORT_INVALID", "rate metrics summary is inconsistent")


def _orchestration_summary(
    original: MappingVNext,
    effective: MappingVNext,
    execution: MappingExecutionVNext,
    metrics: MetricsVNext,
    rate_enabled: bool,
) -> dict[str, object]:
    metrics_report = metrics.to_report()
    return {
        "origin": original.rewrite_policy.symbol_graph.source_catalog.source_set.origin,
        "top": original.rewrite_policy.symbol_graph.source_catalog.source_set.top,
        "rate_enabled": rate_enabled,
        "files": len(execution.rewrite_execution.gate_manifest),
        "mapping_records": len(original.records),
        "effective_mapping_records": len(effective.records),
        "modified_tokens": len(execution.rewrite_execution.edits),
        "strict_compile_passed": True,
        "restored_byte_identical": True,
        "effective_line_total": metrics.effective_line_total,
        "affected_line_count": metrics.affected_line_count,
        "symbol_coverage": metrics_report["symbols"]["coverage"],
        "occurrence_coverage": metrics_report["occurrences"]["coverage"],
        "plaintext_leakage_rate": metrics_report["plaintext_leakage_rate"],
        "effective_coverage": metrics_report["effective_coverage"],
    }


@dataclass(frozen=True)
class RestoreVNext:
    schema_version: int
    source_set: SourceSet
    mapping_vnext: MappingVNext
    effective_mapping_vnext: MappingVNext
    mapping_execution: MappingExecutionVNext
    metrics: MetricsVNext
    restore_result: RestoreResult
    rate_enabled: bool
    report: dict[str, object]

    def to_report(self) -> dict[str, object]:
        return self.report


@dataclass(frozen=True)
class OrchestrationGateAuditVNext:
    """The verified, portable part of an orchestration gate report."""

    schema_version: int
    source_set: SourceSet
    effective_records: tuple[MappingRecord, ...]
    input_manifest: tuple[InputFileDigest, ...]
    gate_manifest: tuple[InputFileDigest, ...]


@dataclass(frozen=True)
class _OrchestrationGateInputsVNext:
    report_path: Path
    gate_path: Path
    report: dict[str, object]
    source_set: SourceSet
    files: tuple[str, ...]
    gate_data: dict[str, bytes]
    effective_records: tuple[MappingRecord, ...]
    input_manifest: tuple[InputFileDigest, ...]
    gate_manifest: tuple[InputFileDigest, ...]
    rename_ranges: dict[str, tuple[tuple[int, int, bytes], ...]]


def _unbound_occurrences(value: object) -> tuple[SymbolOccurrence, ...]:
    if not isinstance(value, list):
        _fail("RESTORE_VNEXT_REPORT_INVALID", "effective mapping occurrences are invalid")
    result: list[SymbolOccurrence] = []
    for item in value:
        if not isinstance(item, dict) or set(item) != {"source_range", "provenance"}:
            _fail("RESTORE_VNEXT_REPORT_INVALID", "effective mapping occurrence schema is invalid")
        if not isinstance(item["provenance"], str) or not item["provenance"]:
            _fail("RESTORE_VNEXT_REPORT_INVALID", "effective mapping occurrence provenance is invalid")
        result.append(
            SymbolOccurrence(
                source_range=_parse_range(item["source_range"], label="effective occurrence"),
                provenance=item["provenance"],
            )
        )
    return tuple(result)


def _unbound_effective_records(value: object) -> tuple[MappingRecord, ...]:
    if not isinstance(value, dict) or set(value) != {
        "format", "schema_version", "state", "source_set", "selection",
        "name_length", "input_manifest", "records", "summary", "range_audit",
    }:
        _fail("RESTORE_VNEXT_REPORT_INVALID", "effective mapping report schema is invalid")
    if value.get("format") != "rtl-obfuscation.mapping-vnext" or value.get("schema_version") != 1 or value.get("state") != "planned":
        _fail("RESTORE_VNEXT_REPORT_INVALID", "effective mapping report state is invalid")
    raw_records = value.get("records")
    if not isinstance(raw_records, list):
        _fail("RESTORE_VNEXT_REPORT_INVALID", "effective mapping records are invalid")
    result: list[MappingRecord] = []
    expected_keys = {
        "symbol_id", "category", "action", "reason", "original_name", "renamed_name",
        "owner_module", "semantic_owner", "declaration", "occurrences", "impact", "abi",
    }
    for item in raw_records:
        if not isinstance(item, dict) or set(item) != expected_keys:
            _fail("RESTORE_VNEXT_REPORT_INVALID", "effective mapping record schema is invalid")
        if not all(isinstance(item[key], str) and item[key] for key in ("symbol_id", "category", "original_name", "owner_module", "semantic_owner")):
            _fail("RESTORE_VNEXT_REPORT_INVALID", "effective mapping record identity is invalid")
        action = item["action"]
        if action not in {"rename", "preserve", "unsupported"}:
            _fail("RESTORE_VNEXT_REPORT_INVALID", "effective mapping action is invalid")
        renamed = item["renamed_name"]
        if action == "rename":
            if not isinstance(renamed, str) or not renamed:
                _fail("RESTORE_VNEXT_REPORT_INVALID", "effective rename name is invalid")
        elif renamed is not None:
            _fail("RESTORE_VNEXT_REPORT_INVALID", "non-rename record has a renamed name")
        if item["reason"] is not None and not isinstance(item["reason"], str):
            _fail("RESTORE_VNEXT_REPORT_INVALID", "effective mapping reason is invalid")
        result.append(
            MappingRecord(
                symbol_id=item["symbol_id"],
                category=item["category"],
                action=action,
                reason=item["reason"],
                original_name=item["original_name"],
                renamed_name=renamed,
                owner_module=item["owner_module"],
                semantic_owner=item["semantic_owner"],
                declaration=_parse_range(item["declaration"], label="effective declaration"),
                occurrences=_unbound_occurrences(item["occurrences"]),
                impact=item["impact"],
                abi=item["abi"],
            )
        )
    return tuple(result)


def _audit_gate_ranges(
    execution: dict[str, object],
    *,
    records: tuple[MappingRecord, ...],
    files: tuple[str, ...],
    gate_data: dict[str, bytes],
) -> dict[str, tuple[tuple[int, int, bytes], ...]]:
    per_file = execution.get("per_file_mapping")
    if not isinstance(per_file, list) or len(per_file) != len(files):
        _fail("RESTORE_VNEXT_REPORT_INVALID", "per-file mapping does not cover physical files")
    expected: dict[tuple[str, str, SourceRange], SourceRange] = {}
    for record in records:
        expected[(record.symbol_id, "declaration", record.declaration)] = record.declaration
        for occurrence in record.occurrences:
            key = (record.symbol_id, occurrence.provenance, occurrence.source_range)
            if key in expected:
                _fail("RESTORE_VNEXT_REPORT_INVALID", "effective mapping occurrence is duplicated")
            expected[key] = occurrence.source_range
    seen: set[tuple[str, str, SourceRange]] = set()
    rename_ranges: dict[str, list[tuple[int, int, bytes]]] = {file: [] for file in files}
    by_id = {record.symbol_id: record for record in records}
    for item, file in zip(per_file, files):
        if not isinstance(item, dict) or set(item) != {"file", "input_sha256", "gate_sha256", "records"} or item["file"] != file:
            _fail("RESTORE_VNEXT_REPORT_INVALID", "per-file mapping order is invalid")
        if not isinstance(item["input_sha256"], str) or not isinstance(item["gate_sha256"], str) or not _SHA256.fullmatch(item["input_sha256"]) or not _SHA256.fullmatch(item["gate_sha256"]):
            _fail("RESTORE_VNEXT_REPORT_INVALID", "per-file mapping hash is invalid")
        projected = item["records"]
        if not isinstance(projected, list):
            _fail("RESTORE_VNEXT_REPORT_INVALID", "per-file mapping records are invalid")
        for projected_record in projected:
            if not isinstance(projected_record, dict) or set(projected_record) != {
                "symbol_id", "category", "action", "reason", "original_name", "renamed_name",
                "owner_module", "semantic_owner", "impact", "abi", "ranges",
            }:
                _fail("RESTORE_VNEXT_REPORT_INVALID", "per-file mapping record schema is invalid")
            symbol_id = projected_record["symbol_id"]
            record = by_id.get(symbol_id)
            if record is None:
                _fail("RESTORE_VNEXT_REPORT_INVALID", "per-file mapping references an unknown record")
            for field in ("category", "action", "reason", "original_name", "renamed_name", "owner_module", "semantic_owner", "impact", "abi"):
                if projected_record[field] != getattr(record, field):
                    _fail("RESTORE_VNEXT_REPORT_INVALID", "per-file mapping record differs from effective mapping")
            ranges = projected_record["ranges"]
            if not isinstance(ranges, list):
                _fail("RESTORE_VNEXT_REPORT_INVALID", "per-file mapping ranges are invalid")
            for projected_range in ranges:
                if not isinstance(projected_range, dict) or set(projected_range) != {"provenance", "source_range", "gate_range"}:
                    _fail("RESTORE_VNEXT_REPORT_INVALID", "per-file mapping range schema is invalid")
                provenance = projected_range["provenance"]
                source_range = _parse_range(projected_range["source_range"], label="per-file source range")
                gate_range = _parse_range(projected_range["gate_range"], label="per-file gate range")
                key = (symbol_id, provenance, source_range)
                if key in seen or key not in expected:
                    _fail("RESTORE_VNEXT_REPORT_INVALID", "per-file mapping range coverage is invalid")
                if source_range != expected[key] or source_range.file != file or gate_range.file != file:
                    _fail("RESTORE_VNEXT_REPORT_INVALID", "per-file mapping range differs from effective mapping")
                seen.add(key)
                if record.action == "rename":
                    renamed = record.renamed_name
                    if not isinstance(renamed, str) or gate_range.end - gate_range.start != len(renamed.encode("utf-8")):
                        _fail("RESTORE_VNEXT_REPORT_INVALID", "rename gate range length is invalid")
                    content = gate_data[file]
                    if gate_range.end > len(content) or content[gate_range.start:gate_range.end] != renamed.encode("utf-8"):
                        _fail("RESTORE_VNEXT_GATE_INVALID", "gate bytes do not match effective rename range")
                    if source_range.end - source_range.start != len(record.original_name.encode("utf-8")):
                        _fail("RESTORE_VNEXT_REPORT_INVALID", "rename source range length is invalid")
                    rename_ranges[file].append((gate_range.start, gate_range.end, record.original_name.encode("utf-8")))
    if seen != set(expected):
        _fail("RESTORE_VNEXT_REPORT_INVALID", "per-file mapping does not cover all physical ranges")
    for file, ranges in rename_ranges.items():
        ranges.sort()
        for previous, current in zip(ranges, ranges[1:]):
            if current[0] < previous[1]:
                _fail("RESTORE_VNEXT_GATE_INVALID", "effective rename gate ranges overlap")
    return {file: tuple(ranges) for file, ranges in rename_ranges.items()}


def _load_orchestration_gate_inputs_vnext(
    report_file: Path,
    *,
    gate_dir: Path,
) -> _OrchestrationGateInputsVNext:
    report_path = _resolve(report_file, "RESTORE_VNEXT_INPUT_INVALID")
    gate_path = _resolve(gate_dir, "RESTORE_VNEXT_GATE_INVALID")
    if not report_path.is_file():
        _fail("RESTORE_VNEXT_INPUT_INVALID", "orchestration report is not a regular file")
    if not gate_path.is_dir():
        _fail("RESTORE_VNEXT_GATE_INVALID", "gate-dir is not a directory")
    report = _read_json(report_path)
    expected_outer = {"format", "schema_version", "state", "source_set", "mapping", "mapping_execution", "metrics", "rate_metrics", "summary"}
    if set(report) != expected_outer or report.get("format") != "rtl-obfuscation.orchestration-vnext" or report.get("schema_version") != 1 or report.get("state") != "restored":
        _fail("RESTORE_VNEXT_REPORT_INVALID", "orchestration report format, schema, or state is invalid")
    source_set = _parse_source_set(report["source_set"], gate_path)
    ordered_source_files = tuple(source_set.ordered_source_files)
    included_files = tuple(source_set.included_files)
    if (
        not ordered_source_files
        or len(set(ordered_source_files)) != len(ordered_source_files)
        or len(set(included_files)) != len(included_files)
        or set(ordered_source_files) & set(included_files)
        or tuple(source_set.compile_order) != ordered_source_files
    ):
        _fail("RESTORE_VNEXT_INPUT_INVALID", "source_set physical order is invalid")
    files = (*ordered_source_files, *included_files)
    _validate_gate_file_set(report_path, gate_path, report, files)
    try:
        if (gate_path / "design.f").read_bytes() != "".join(f"{file}\n" for file in source_set.compile_order).encode("utf-8"):
            _fail("RESTORE_VNEXT_GATE_INVALID", "gate design.f differs from compile order")
        gate_data = {file: (gate_path / file).read_bytes() for file in files}
    except OSError as error:
        _fail("RESTORE_VNEXT_GATE_INVALID", str(error))
    execution = report.get("mapping_execution")
    if not isinstance(execution, dict) or execution.get("mapping") is None:
        _fail("RESTORE_VNEXT_REPORT_INVALID", "mapping execution report is invalid")
    outer_input = _parse_manifest(report["mapping"].get("input_manifest") if isinstance(report["mapping"], dict) else None, files, label="outer mapping input_manifest")
    effective_report = execution.get("mapping")
    effective_records = _unbound_effective_records(effective_report)
    effective_input = _parse_manifest(effective_report.get("input_manifest") if isinstance(effective_report, dict) else None, files, label="effective mapping input_manifest")
    execution_input = _parse_manifest(execution.get("input_manifest"), files, label="execution input_manifest")
    restored_input = _parse_manifest(execution.get("restored_manifest"), files, label="execution restored_manifest")
    if not (outer_input == effective_input == execution_input == restored_input):
        _fail("RESTORE_VNEXT_REPORT_INVALID", "input manifest chain differs")
    gate_manifest = _parse_manifest(execution.get("gate_manifest"), files, label="execution gate_manifest")
    actual_gate_manifest = tuple(InputFileDigest(file=file, sha256=hashlib.sha256(gate_data[file]).hexdigest()) for file in files)
    if gate_manifest != actual_gate_manifest:
        _fail("RESTORE_VNEXT_GATE_INVALID", "gate manifest differs from actual gate bytes")
    rename_ranges = _audit_gate_ranges(
        execution,
        records=effective_records,
        files=files,
        gate_data=gate_data,
    )
    return _OrchestrationGateInputsVNext(
        report_path=report_path,
        gate_path=gate_path,
        report=report,
        source_set=source_set,
        files=files,
        gate_data=gate_data,
        effective_records=effective_records,
        input_manifest=outer_input,
        gate_manifest=gate_manifest,
        rename_ranges=rename_ranges,
    )


def _materialize_direct_source_vnext(
    inputs: _OrchestrationGateInputsVNext,
    source_root: Path,
) -> None:
    source_data: dict[str, bytes] = {}
    for file in inputs.files:
        content = inputs.gate_data[file]
        for start, end, replacement in sorted(
            inputs.rename_ranges[file],
            reverse=True,
        ):
            content = content[:start] + replacement + content[end:]
        source_data[file] = content
    restored_manifest = tuple(
        InputFileDigest(file=file, sha256=hashlib.sha256(source_data[file]).hexdigest())
        for file in inputs.files
    )
    if restored_manifest != inputs.input_manifest:
        _fail(
            "RESTORE_VNEXT_REPORT_INVALID",
            "direct restore differs from the input manifest",
        )
    try:
        source_root.mkdir()
        for file in inputs.files:
            destination = source_root / file
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source_data[file])
    except OSError as error:
        _fail("RESTORE_VNEXT_IO_ERROR", str(error))


def _hydrate_orchestration_gate_vnext(
    inputs: _OrchestrationGateInputsVNext,
    *,
    output_dir: Path,
) -> RestoreVNext:
    with tempfile.TemporaryDirectory(prefix=".restore-vnext-direct-") as temporary:
        container = Path(temporary)
        source_root = container / "source"
        _materialize_direct_source_vnext(inputs, source_root)
        try:
            return load_restore_vnext(
                inputs.report_path,
                gate_dir=inputs.gate_path,
                source_root=source_root,
                output_dir=output_dir,
            )
        except RestoreVNextError:
            raise
        except (OSError, RuntimeError, ValueError) as error:
            _fail("RESTORE_VNEXT_REPORT_INVALID", str(error))


def audit_orchestration_gate_vnext(
    report_file: Path,
    *,
    gate_dir: Path,
) -> OrchestrationGateAuditVNext:
    """Audit one persisted orchestration report against its actual gate bytes."""
    inputs = _load_orchestration_gate_inputs_vnext(
        report_file,
        gate_dir=gate_dir,
    )
    with tempfile.TemporaryDirectory(prefix=".restore-vnext-audit-") as temporary:
        hydrated = _hydrate_orchestration_gate_vnext(
            inputs,
            output_dir=Path(temporary) / "restored",
        )
    projected_source_set = replace(
        hydrated.source_set,
        source_root=inputs.gate_path,
    )
    return OrchestrationGateAuditVNext(
        schema_version=1,
        source_set=projected_source_set,
        effective_records=hydrated.effective_mapping_vnext.records,
        input_manifest=hydrated.mapping_vnext.input_manifest,
        gate_manifest=hydrated.mapping_execution.rewrite_execution.gate_manifest,
    )


def load_direct_restore_vnext(
    map_file: Path,
    *,
    gate_dir: Path,
    output_dir: Path,
) -> RestoreVNext:
    """Restore from a persisted mapping and actual gate without original RTL."""
    map_path, gate_path, output_path, _ = validate_direct_restore_paths_vnext(
        map_file,
        gate_dir,
        output_dir,
    )
    inputs = _load_orchestration_gate_inputs_vnext(
        map_path,
        gate_dir=gate_path,
    )
    return _hydrate_orchestration_gate_vnext(inputs, output_dir=output_path)


def load_restore_vnext(
    map_file: Path,
    *,
    gate_dir: Path,
    source_root: Path,
    output_dir: Path,
) -> RestoreVNext:
    map_path, gate_path, source_path, output_path, _ = _validate_paths(
        map_file, gate_dir, source_root, output_dir
    )
    report = _read_json(map_path)
    expected_keys = {"format", "schema_version", "state", "source_set", "mapping", "mapping_execution", "metrics", "rate_metrics", "summary"}
    if set(report) != expected_keys or report.get("format") != "rtl-obfuscation.orchestration-vnext" or report.get("schema_version") != 1 or report.get("state") != "restored":
        _fail("RESTORE_VNEXT_REPORT_INVALID", "orchestration report format, schema, or state is invalid")
    source_set = _parse_source_set(report["source_set"], source_path)
    files = tuple(dict.fromkeys((*source_set.ordered_source_files, *source_set.included_files)))
    if not files:
        _fail("RESTORE_VNEXT_INPUT_INVALID", "source_set has no physical files")
    _validate_gate_file_set(map_path, gate_path, report, files)
    try:
        source_data = {file: (source_path / file).read_bytes() for file in files}
        catalog = build_source_catalog(source_set)
        graph = build_symbol_graph(catalog)
    except (OSError, ValueError, RuntimeError, SourceCatalogError, SymbolGraphError) as error:
        _fail("RESTORE_VNEXT_INPUT_INVALID", str(error))
    original_report = report["mapping"]
    if not isinstance(original_report, dict) or not isinstance(original_report.get("selection"), dict):
        _fail("RESTORE_VNEXT_REPORT_INVALID", "original mapping report is invalid")
    selection = original_report["selection"]
    try:
        policy = build_rewrite_policy(
            graph,
            categories=selection.get("selected_categories"),
            abi_categories=selection.get("abi_categories"),
        )
    except Exception as error:
        _fail("RESTORE_VNEXT_INPUT_INVALID", str(error))
    original_mapping, original_decisions = _hydrate_mapping(
        original_report,
        source_set=source_set,
        graph=graph,
        policy=policy,
        source_data=source_data,
        require_policy_action=True,
    )
    execution_report = report["mapping_execution"]
    if not isinstance(execution_report, dict) or not isinstance(execution_report.get("mapping"), dict):
        _fail("RESTORE_VNEXT_REPORT_INVALID", "effective mapping report is invalid")
    effective_mapping, effective_decisions = _hydrate_mapping(
        execution_report["mapping"],
        source_set=source_set,
        graph=graph,
        policy=policy,
        source_data=source_data,
        require_policy_action=False,
    )
    _validate_effective_mapping(original_mapping, effective_mapping, report["rate_metrics"] is not None)
    mapping_execution = _hydrate_execution(
        execution_report,
        effective_mapping=effective_mapping,
        orchestration_summary=report.get("summary"),
    )
    try:
        metrics = build_metrics_vnext(mapping_execution, gate_dir=gate_path)
    except MetricsVNextError as error:
        code = (
            "RESTORE_VNEXT_GATE_INVALID"
            if error.code == "METRICS_MANIFEST_INVALID"
            else "RESTORE_VNEXT_REPORT_INVALID"
        )
        _fail(code, error.message)
    metrics_report = metrics.to_report()
    if report.get("metrics") != metrics_report:
        _fail("RESTORE_VNEXT_REPORT_INVALID", "persisted metrics differ from actual gate audit")
    rate_enabled = report["rate_metrics"] is not None
    if rate_enabled:
        _validate_rate_report(
            report["rate_metrics"],
            original=original_mapping,
            effective=effective_mapping,
            execution_report=execution_report,
            metrics_report=metrics_report,
            source_data=source_data,
        )
    elif report.get("rate_metrics") is not None:
        _fail("RESTORE_VNEXT_REPORT_INVALID", "no-rate report contains rate metrics")
    expected_summary = _orchestration_summary(
        original_mapping,
        effective_mapping,
        mapping_execution,
        metrics,
        rate_enabled,
    )
    if report.get("summary") != expected_summary:
        _fail("RESTORE_VNEXT_REPORT_INVALID", "orchestration summary differs from hydrated execution")
    try:
        restore_result = restore_gate_vnext(
            mapping_execution.rewrite_execution,
            gate_dir=gate_path,
            output_dir=output_path,
            _validate_canonical_policy=False,
        )
    except RewriteVNextError as error:
        _fail("RESTORE_VNEXT_GATE_INVALID", error.message)
    restore_report = {
        "format": "rtl-obfuscation.restore-vnext",
        "schema_version": 1,
        "state": "restored",
        "source_set": {
            "schema_version": source_set.schema_version,
            "origin": source_set.origin,
            "ordered_source_files": list(source_set.ordered_source_files),
            "included_files": list(source_set.included_files),
            "include_dirs": list(source_set.include_dirs),
            "defines": [
                {"name": name, "value": value} for name, value in source_set.defines
            ],
            "top": source_set.top,
            "top_closure_files": list(source_set.top_closure_files),
            "compile_order": list(source_set.compile_order),
        },
        "gate_manifest": [
            {"file": item.file, "sha256": item.sha256}
            for item in mapping_execution.rewrite_execution.gate_manifest
        ],
        "restored_manifest": [
            {"file": item.file, "sha256": item.sha256}
            for item in restore_result.restored_manifest
        ],
        "summary": {
            "files": len(restore_result.restored_manifest),
            "restored_input_manifest_equal": restore_result.restored_manifest == effective_mapping.input_manifest,
            "restored_byte_identical": restore_result.restored_manifest == effective_mapping.input_manifest,
            "rate_enabled": rate_enabled,
        },
    }
    if not _portable_value(restore_report):
        _fail("RESTORE_VNEXT_REPORT_INVALID", "restore report is not portable")
    return RestoreVNext(
        schema_version=1,
        source_set=source_set,
        mapping_vnext=original_mapping,
        effective_mapping_vnext=effective_mapping,
        mapping_execution=mapping_execution,
        metrics=metrics,
        restore_result=restore_result,
        rate_enabled=rate_enabled,
        report=restore_report,
    )


def write_restore_report_vnext(restore: RestoreVNext, output_file: Path) -> None:
    path = _resolve(output_file, "RESTORE_VNEXT_OUTPUT_INVALID")
    if path.exists() or path.is_symlink() or not path.parent.is_dir():
        _fail("RESTORE_VNEXT_OUTPUT_INVALID", "report output is invalid")
    report = restore.to_report()
    try:
        payload = json.dumps(report, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                descriptor = -1
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            if temporary.read_bytes() != payload or json.loads(payload.decode("utf-8")) != report:
                _fail("RESTORE_VNEXT_IO_ERROR", "report readback differs")
            temporary.replace(path)
        except RestoreVNextError:
            if descriptor >= 0:
                os.close(descriptor)
            temporary.unlink(missing_ok=True)
            raise
        except BaseException:
            if descriptor >= 0:
                os.close(descriptor)
            temporary.unlink(missing_ok=True)
            raise
    except RestoreVNextError:
        raise
    except (OSError, TypeError, ValueError, UnicodeError, json.JSONDecodeError) as error:
        _fail("RESTORE_VNEXT_IO_ERROR", str(error))


def publish_restore_vnext(artifacts: list[tuple[Path, Path]]) -> None:
    prepared: list[tuple[Path, Path, bool]] = []
    success = False
    try:
        for source, target in artifacts:
            container = Path(tempfile.mkdtemp(prefix=".restore-vnext-publish-", dir=target.parent))
            prepared.append((container, target, False))
            payload = container / "payload"
            if source.is_dir():
                shutil.copytree(source, payload)
            else:
                shutil.copy2(source, payload)
        for index, (container, target, _published) in enumerate(prepared):
            if target.exists() or target.is_symlink():
                _fail("RESTORE_VNEXT_OUTPUT_INVALID", "output target appeared during publish")
            (container / "payload").replace(target)
            prepared[index] = (container, target, True)
        success = True
    except RestoreVNextError:
        raise
    except (OSError, shutil.Error) as error:
        _fail("RESTORE_VNEXT_OUTPUT_INVALID", str(error))
    finally:
        for container, target, published in reversed(prepared):
            if published and not success:
                try:
                    if target.is_dir() and not target.is_symlink():
                        shutil.rmtree(target)
                    elif target.exists() or target.is_symlink():
                        target.unlink()
                except OSError:
                    pass
            shutil.rmtree(container, ignore_errors=True)
