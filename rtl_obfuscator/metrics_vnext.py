"""Effective-line, coverage, and leakage metrics over a T047 envelope."""

from __future__ import annotations

from dataclasses import dataclass, field
from bisect import bisect_left, bisect_right
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any

from .mapping_vnext import MappingRecord
from .file_scope_vnext import FileScopeVNext, metric_scope
from .rewrite_vnext import (
    AppliedEdit,
    MappingExecutionVNext,
    RewriteVNextError,
)
from .source_catalog import SourceRange


@dataclass(frozen=True)
class MetricsVNext:
    schema_version: int
    mapping_execution: MappingExecutionVNext = field(repr=False, compare=False)
    effective_line_total: int
    affected_line_count: int
    symbol_count: int
    occurrence_count: int
    plaintext_leakage_count: int
    _report: dict[str, object] | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def to_report(self) -> dict[str, object]:
        if self._report is not None:
            return deepcopy(self._report)
        context = _metrics_context(self.mapping_execution)
        source_data, _input_manifest = _read_source_bytes(context)
        line_indexes = {
            file: _line_index(source_data[file]) for file in context.scope.files
        }
        effective_by_file, effective_total = _effective_line_metrics(
            context.scope.files,
            source_data,
            line_indexes=line_indexes,
        )
        affected_by_file, affected_total = _affected_line_metrics(
            context.scope.files,
            source_data,
            context.execution.edits,
            line_indexes=line_indexes,
        )
        coverage_counts = _coverage_counts(context)
        _validate_metrics_equations(
            self,
            context,
            effective_total=effective_total,
            affected_total=affected_total,
            coverage_counts=coverage_counts,
        )
        report = _metrics_report(
            self,
            context.scope,
            effective_by_file,
            effective_total,
            affected_by_file,
            affected_total,
            coverage_counts,
        )
        object.__setattr__(self, "_report", report)
        return deepcopy(report)


class MetricsVNextError(ValueError):
    """Stable fail-closed error for metrics vNext."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class _MetricsContext:
    mapping_execution: MappingExecutionVNext
    execution: Any
    mapping: Any
    files: tuple[str, ...]
    file_set: frozenset[str]
    input_manifest: tuple[dict[str, str], ...]
    gate_manifest: tuple[dict[str, str], ...]
    source_root: Path
    scope: FileScopeVNext


@dataclass(frozen=True)
class _LineIndex:
    starts: tuple[int, ...]
    ends: tuple[int, ...]


def _fail(code: str, message: str) -> None:
    raise MetricsVNextError(code, message)


def _is_schema_one(value: object) -> bool:
    return type(value) is int and value == 1


def _portable_file(value: object) -> bool:
    if not isinstance(value, str) or not value or value.startswith("/") or "\\" in value:
        return False
    return all(part not in {"", ".", ".."} for part in value.split("/"))


def _metrics_context(mapping_execution: object) -> _MetricsContext:
    if not isinstance(mapping_execution, MappingExecutionVNext):
        _fail("METRICS_EXECUTION_INVALID", "input is not MappingExecutionVNext")
    if type(mapping_execution.schema_version) is not int or mapping_execution.schema_version != 2:
        _fail("METRICS_EXECUTION_INVALID", "mapping execution schema is invalid")
    try:
        report = mapping_execution.to_report()
    except RewriteVNextError as error:
        if error.code == "MAPPING_MANIFEST_INVALID":
            _fail("METRICS_MANIFEST_INVALID", f"T047 manifest is invalid: {error}")
        if error.code == "MAPPING_PER_FILE_INVALID":
            _fail("METRICS_AUDIT_INVALID", f"T047 per-file audit is invalid: {error}")
        _fail("METRICS_EXECUTION_INVALID", f"T047 envelope is invalid: {error}")
    except Exception as error:
        _fail("METRICS_EXECUTION_INVALID", f"T047 envelope cannot be audited: {error}")
    if (
        not isinstance(report, dict)
        or report.get("format") != "rtl-obfuscation.mapping-execution-vnext"
        or report.get("schema_version") != 2
        or report.get("state") != "restored"
        or report.get("filelist") != "design.f"
    ):
        _fail("METRICS_EXECUTION_INVALID", "mapping execution report format, schema, or state is invalid")
    summary = report.get("summary")
    if (
        not isinstance(summary, dict)
        or summary.get("restored_input_manifest_equal") is not True
        or summary.get("restored_byte_identical") is not True
    ):
        _fail("METRICS_EXECUTION_INVALID", "mapping execution restore state is not verified")

    execution = mapping_execution.rewrite_execution
    mapping = execution.mapping_vnext
    input_manifest = report.get("input_manifest")
    gate_manifest = report.get("gate_manifest")
    if not isinstance(input_manifest, list) or not isinstance(gate_manifest, list):
        _fail("METRICS_MANIFEST_INVALID", "T047 manifests are not lists")
    if len(input_manifest) != len(gate_manifest):
        _fail("METRICS_MANIFEST_INVALID", "input and gate manifest lengths differ")
    files: list[str] = []
    seen_files: set[str] = set()
    normalized_input: list[dict[str, str]] = []
    normalized_gate: list[dict[str, str]] = []
    for input_item, gate_item in zip(input_manifest, gate_manifest):
        if (
            not isinstance(input_item, dict)
            or not isinstance(gate_item, dict)
            or set(input_item) != {"file", "sha256"}
            or set(gate_item) != {"file", "sha256"}
            or input_item["file"] != gate_item["file"]
            or not _portable_file(input_item["file"])
            or not _valid_sha256(input_item["sha256"])
            or not _valid_sha256(gate_item["sha256"])
        ):
            _fail("METRICS_MANIFEST_INVALID", "T047 manifest order, file, or hash is invalid")
        file = input_item["file"]
        if file in seen_files:
            _fail("METRICS_MANIFEST_INVALID", "T047 manifest contains duplicate files")
        seen_files.add(file)
        files.append(file)
        normalized_input.append({"file": file, "sha256": input_item["sha256"]})
        normalized_gate.append({"file": file, "sha256": gate_item["sha256"]})
    if not files:
        _fail("METRICS_MANIFEST_INVALID", "T047 manifest is empty")

    source_set = mapping.rename_index.source_catalog.source_set
    try:
        source_root = Path(source_set.source_root).expanduser().resolve()
    except (OSError, RuntimeError, TypeError) as error:
        _fail("METRICS_MANIFEST_INVALID", f"source_root is invalid: {error}")
    if not source_root.is_dir():
        _fail("METRICS_MANIFEST_INVALID", "source_root is not a directory")
    if tuple(item["file"] for item in report["input_manifest"]) != tuple(files):
        _fail("METRICS_MANIFEST_INVALID", "input manifest order is not canonical")
    return _MetricsContext(
        mapping_execution=mapping_execution,
        execution=execution,
        mapping=mapping,
        files=tuple(files),
        file_set=frozenset(seen_files),
        input_manifest=tuple(normalized_input),
        gate_manifest=tuple(normalized_gate),
        source_root=source_root,
        scope=metric_scope(source_set),
    )


def _valid_sha256(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    return all(char in "0123456789abcdef" for char in value)


def _read_source_bytes(
    context: _MetricsContext,
) -> tuple[dict[str, bytes], tuple[dict[str, str], ...]]:
    data: dict[str, bytes] = {}
    for item in context.input_manifest:
        file = item["file"]
        path = (context.source_root / file).resolve()
        try:
            path.relative_to(context.source_root)
            content = path.read_bytes()
        except (OSError, ValueError) as error:
            _fail("METRICS_MANIFEST_INVALID", f"source file is unavailable: {file}: {error}")
        if hashlib.sha256(content).hexdigest() != item["sha256"]:
            _fail("METRICS_MANIFEST_INVALID", f"source manifest hash differs: {file}")
        data[file] = content
    return data, context.input_manifest


def _read_gate_bytes(
    context: _MetricsContext,
    gate_dir: Path,
) -> dict[str, bytes]:
    try:
        gate_root = Path(gate_dir).expanduser().resolve()
    except (OSError, RuntimeError, TypeError) as error:
        _fail("METRICS_MANIFEST_INVALID", f"gate_dir is invalid: {error}")
    if not gate_root.is_dir():
        _fail("METRICS_MANIFEST_INVALID", "gate_dir is not a directory")
    data: dict[str, bytes] = {}
    for item in context.gate_manifest:
        file = item["file"]
        path = (gate_root / file).resolve()
        try:
            path.relative_to(gate_root)
            content = path.read_bytes()
        except (OSError, ValueError) as error:
            _fail("METRICS_MANIFEST_INVALID", f"gate file is unavailable: {file}: {error}")
        if hashlib.sha256(content).hexdigest() != item["sha256"]:
            _fail("METRICS_MANIFEST_INVALID", f"gate manifest hash differs: {file}")
        data[file] = content
    return data


def _line_spans(content: bytes) -> tuple[tuple[int, int, bytes], ...]:
    spans: list[tuple[int, int, bytes]] = []
    offset = 0
    for line in content.splitlines(keepends=True):
        end = offset + len(line)
        spans.append((offset, end, line))
        offset = end
    return tuple(spans)


def _line_index(content: bytes) -> _LineIndex:
    spans = _line_spans(content)
    return _LineIndex(
        starts=tuple(item[0] for item in spans),
        ends=tuple(item[1] for item in spans),
    )


def _metrics_report(
    metrics: MetricsVNext,
    scope: FileScopeVNext,
    effective_by_file: list[dict[str, object]],
    effective_total: int,
    affected_by_file: list[dict[str, object]],
    affected_total: int,
    coverage_counts: tuple[int, int, int, int],
) -> dict[str, object]:
    renamed_symbols, eligible_symbols, renamed_occurrences, eligible_occurrences = coverage_counts
    symbol_coverage = _coverage(renamed_symbols, eligible_symbols)
    occurrence_coverage = _coverage(renamed_occurrences, eligible_occurrences)
    return {
        "format": "rtl-obfuscation.metrics-vnext",
        "schema_version": metrics.schema_version,
        "state": "verified",
        "mapping_execution_format": "rtl-obfuscation.mapping-execution-vnext",
        "filelist": "design.f",
        "scope": scope.to_report(),
        "effective_lines": {
            "total": effective_total,
            "by_file": effective_by_file,
        },
        "affected_lines": {
            "changed": affected_total,
            "total": effective_total,
            "rate": _rate(affected_total, effective_total),
            "by_file": affected_by_file,
        },
        "symbols": {
            "renamed": renamed_symbols,
            "eligible": eligible_symbols,
            "coverage": symbol_coverage,
        },
        "occurrences": {
            "renamed": renamed_occurrences,
            "eligible": eligible_occurrences,
            "coverage": occurrence_coverage,
        },
        "plaintext_leakage_rate": _rate(
            metrics.plaintext_leakage_count,
            eligible_occurrences,
        ),
        "effective_coverage": math.sqrt(symbol_coverage * occurrence_coverage),
    }


def _effective_line_metrics(
    files: tuple[str, ...],
    source_data: dict[str, bytes],
    *,
    line_indexes: dict[str, _LineIndex] | None = None,
) -> tuple[list[dict[str, object]], int]:
    by_file: list[dict[str, object]] = []
    total = 0
    for file in files:
        index = line_indexes[file] if line_indexes is not None else _line_index(source_data[file])
        effective = 0
        content = source_data[file]
        for start, end in zip(index.starts, index.ends):
            line = content[start:end].strip()
            effective += line != b"" and not line.startswith(b"//")
        by_file.append({"file": file, "lines": effective})
        total += effective
    return by_file, total


def _lines_for_range(
    source_range: SourceRange,
    content: bytes,
    *,
    line_spans: _LineIndex | tuple[tuple[int, int, bytes], ...] | None = None,
) -> set[int]:
    if (
        not isinstance(source_range, SourceRange)
        or type(source_range.start) is not int
        or type(source_range.end) is not int
        or not 0 <= source_range.start < source_range.end <= len(content)
    ):
        _fail("METRICS_AUDIT_INVALID", "AppliedEdit source range is outside source bytes")
    if line_spans is None:
        index = _line_index(content)
    elif isinstance(line_spans, _LineIndex):
        index = line_spans
    else:
        # Keep the private helper tolerant for existing internal callers while
        # the production path passes the precomputed direct index above.
        spans = tuple(line_spans)
        index = _LineIndex(
            starts=tuple(item[0] for item in spans),
            ends=tuple(item[1] for item in spans),
        )
    first = bisect_right(index.ends, source_range.start)
    last = bisect_left(index.starts, source_range.end)
    if first >= last:
        _fail("METRICS_AUDIT_INVALID", "AppliedEdit source range has no physical line")
    return set(range(first + 1, last + 1))


def _affected_line_metrics(
    files: tuple[str, ...],
    source_data: dict[str, bytes],
    edits: tuple[AppliedEdit, ...],
    *,
    line_indexes: dict[str, _LineIndex] | None = None,
) -> tuple[list[dict[str, object]], int]:
    changed: dict[str, set[int]] = {file: set() for file in files}
    for edit in edits:
        if not isinstance(edit, AppliedEdit) or edit.source_range.file not in changed:
            _fail("METRICS_AUDIT_INVALID", "AppliedEdit is not a physical source edit")
        changed[edit.source_range.file].update(
            _lines_for_range(
                edit.source_range,
                source_data[edit.source_range.file],
                line_spans=None if line_indexes is None else line_indexes[edit.source_range.file],
            )
        )
    by_file = [
        {"file": file, "lines": len(changed[file])}
        for file in files
    ]
    return by_file, sum(len(changed[file]) for file in files)


def _coverage_counts(context: _MetricsContext) -> tuple[int, int, int, int]:
    records = context.mapping.records
    eligible_records = [record for record in records if record.action == "rename"]
    eligible_ids = {record.symbol_id for record in eligible_records}
    if len(eligible_ids) != len(eligible_records):
        _fail("METRICS_AUDIT_INVALID", "rename symbol ids are not unique")
    report = context.mapping_execution.to_report()
    actual_ids: set[str] = set()
    per_file = report.get("per_file_mapping")
    if not isinstance(per_file, list):
        _fail("METRICS_AUDIT_INVALID", "per-file mapping is not a list")
    for file_entry in per_file:
        if not isinstance(file_entry, dict) or file_entry.get("file") not in context.file_set:
            _fail("METRICS_AUDIT_INVALID", "per-file mapping does not cover the manifest")
        records_for_file = file_entry.get("records")
        if not isinstance(records_for_file, list):
            _fail("METRICS_AUDIT_INVALID", "per-file records are not a list")
        for record in records_for_file:
            if not isinstance(record, dict) or record.get("action") == "rename":
                if not isinstance(record, dict):
                    _fail("METRICS_AUDIT_INVALID", "per-file record is invalid")
                actual_ids.add(record.get("symbol_id"))
    if actual_ids != eligible_ids:
        _fail("METRICS_AUDIT_INVALID", "per-file renamed symbols differ from eligible symbols")
    eligible_occurrences = sum(1 + len(record.occurrences) for record in eligible_records)
    expected_keys = {
        (record.symbol_id, "declaration", record.declaration)
        for record in eligible_records
    }
    expected_keys.update(
        (record.symbol_id, occurrence.provenance, occurrence.source_range)
        for record in eligible_records
        for occurrence in record.occurrences
    )
    actual_keys = {
        (edit.symbol_id, edit.provenance, edit.source_range)
        for edit in context.execution.edits
    }
    if actual_keys != expected_keys or len(actual_keys) != len(context.execution.edits):
        _fail("METRICS_AUDIT_INVALID", "AppliedEdit occurrence coverage differs from eligible occurrences")
    return len(actual_ids), len(eligible_records), len(actual_keys), eligible_occurrences


def _coverage(renamed: int, eligible: int) -> float:
    return 1.0 if eligible == 0 else renamed / eligible


def _rate(numerator: int, denominator: int) -> float:
    return 0.0 if denominator == 0 else numerator / denominator


def _validate_metrics_equations(
    metrics: MetricsVNext,
    context: _MetricsContext,
    *,
    effective_total: int,
    affected_total: int,
    coverage_counts: tuple[int, int, int, int] | None = None,
) -> None:
    if not isinstance(metrics, MetricsVNext) or type(metrics.schema_version) is not int or metrics.schema_version != 2:
        _fail("METRICS_EXECUTION_INVALID", "metrics schema is invalid")
    for value, label in (
        (metrics.effective_line_total, "effective_line_total"),
        (metrics.affected_line_count, "affected_line_count"),
        (metrics.symbol_count, "symbol_count"),
        (metrics.occurrence_count, "occurrence_count"),
        (metrics.plaintext_leakage_count, "plaintext_leakage_count"),
    ):
        if type(value) is not int or value < 0:
            _fail("METRICS_AUDIT_INVALID", f"{label} is invalid")
    if metrics.mapping_execution is not context.mapping_execution:
        _fail("METRICS_EXECUTION_INVALID", "metrics envelope identity differs")
    if metrics.effective_line_total != effective_total or metrics.affected_line_count != affected_total:
        _fail("METRICS_AUDIT_INVALID", "effective or affected line equation differs from source bytes")
    if coverage_counts is None:
        coverage_counts = _coverage_counts(context)
    _renamed_symbols, eligible_symbols, _renamed_occurrences, eligible_occurrences = coverage_counts
    if metrics.symbol_count != eligible_symbols or metrics.occurrence_count != eligible_occurrences:
        _fail("METRICS_AUDIT_INVALID", "symbol or occurrence denominator differs from mapping")
    if metrics.affected_line_count > metrics.effective_line_total:
        _fail("METRICS_AUDIT_INVALID", "affected lines exceed effective lines")
    if metrics.plaintext_leakage_count > eligible_occurrences:
        _fail("METRICS_AUDIT_INVALID", "plaintext leakage exceeds eligible occurrences")


def _validate_gate_edits(
    context: _MetricsContext,
    source_data: dict[str, bytes],
    gate_data: dict[str, bytes],
) -> int:
    leakage = 0
    for edit in context.execution.edits:
        source_range = edit.source_range
        gate_range = edit.gate_range
        source_content = source_data.get(source_range.file)
        gate_content = gate_data.get(gate_range.file)
        if source_content is None or gate_content is None:
            _fail("METRICS_MANIFEST_INVALID", "AppliedEdit range file is not in the manifests")
        original = edit.original_name.encode("utf-8")
        renamed = edit.renamed_name.encode("utf-8")
        if not 0 <= source_range.start < source_range.end <= len(source_content):
            _fail("METRICS_MANIFEST_INVALID", "source edit range is invalid")
        if source_content[source_range.start : source_range.end] != original:
            _fail("METRICS_MANIFEST_INVALID", "source edit range does not match original identifier")
        if not 0 <= gate_range.start < gate_range.end <= len(gate_content):
            _fail("METRICS_MANIFEST_INVALID", "gate edit range is invalid")
        gate_slice = gate_content[gate_range.start : gate_range.end]
        if gate_slice == original:
            leakage += 1
        elif gate_slice != renamed:
            _fail("METRICS_MANIFEST_INVALID", "gate edit range does not match renamed or leaked identifier")
    return leakage


def build_metrics_vnext(
    mapping_execution: MappingExecutionVNext,
    *,
    gate_dir: Path,
) -> MetricsVNext:
    """Compute metrics from one established T047 envelope and actual bytes."""

    context = _metrics_context(mapping_execution)
    source_data, _input_manifest = _read_source_bytes(context)
    gate_data = _read_gate_bytes(context, gate_dir)
    leakage = _validate_gate_edits(context, source_data, gate_data)
    line_indexes = {
        file: _line_index(source_data[file]) for file in context.scope.files
    }
    effective_by_file, effective_total = _effective_line_metrics(
        context.scope.files,
        source_data,
        line_indexes=line_indexes,
    )
    affected_by_file, affected_total = _affected_line_metrics(
        context.scope.files,
        source_data,
        context.execution.edits,
        line_indexes=line_indexes,
    )
    coverage_counts = _coverage_counts(context)
    _renamed_symbols, eligible_symbols, _renamed_occurrences, eligible_occurrences = coverage_counts
    metrics = MetricsVNext(
        schema_version=2,
        mapping_execution=mapping_execution,
        effective_line_total=effective_total,
        affected_line_count=affected_total,
        symbol_count=eligible_symbols,
        occurrence_count=eligible_occurrences,
        plaintext_leakage_count=leakage,
    )
    _validate_metrics_equations(
        metrics,
        context,
        effective_total=effective_total,
        affected_total=affected_total,
        coverage_counts=coverage_counts,
    )
    object.__setattr__(metrics, "_report", _metrics_report(
        metrics,
        context.scope,
        effective_by_file,
        effective_total,
        affected_by_file,
        affected_total,
        coverage_counts,
    ))
    return metrics


def _validate_output_path(output_file: Path) -> Path:
    try:
        path = Path(output_file).expanduser().resolve()
    except (OSError, RuntimeError, TypeError) as error:
        _fail("METRICS_OUTPUT_INVALID", f"output path is invalid: {error}")
    if path.exists() or not path.parent.is_dir():
        _fail("METRICS_OUTPUT_INVALID", "output_file must not exist and its parent must be a directory")
    return path


def _validate_output_protection(path: Path, context: _MetricsContext) -> None:
    try:
        path.relative_to(context.source_root)
    except ValueError:
        pass
    else:
        _fail("METRICS_OUTPUT_INVALID", "output_file overlaps source_root or a physical source file")

    for candidate in (path.parent, *path.parent.parents):
        if not candidate.is_dir() or not (candidate / "design.f").is_file():
            continue
        matches_gate = True
        for item in context.gate_manifest:
            gate_file = (candidate / item["file"]).resolve()
            try:
                gate_file.relative_to(candidate)
                if not gate_file.is_file() or hashlib.sha256(gate_file.read_bytes()).hexdigest() != item["sha256"]:
                    matches_gate = False
                    break
            except (OSError, ValueError):
                matches_gate = False
                break
        if matches_gate:
            _fail("METRICS_OUTPUT_INVALID", "output_file overlaps the actual gate directory")


def write_metrics_vnext(
    metrics: MetricsVNext,
    *,
    output_file: Path,
) -> None:
    """Write one canonical metrics report atomically without overwriting output."""

    destination = _validate_output_path(output_file)
    context = _metrics_context(metrics.mapping_execution if isinstance(metrics, MetricsVNext) else None)
    _validate_output_protection(destination, context)
    try:
        report = metrics.to_report()
        payload = json.dumps(
            report,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except MetricsVNextError:
        raise
    except (TypeError, ValueError, UnicodeError) as error:
        _fail("METRICS_IO_ERROR", f"cannot serialize metrics: {error}")

    staging: Path | None = None
    descriptor: int | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".metrics-vnext-",
            suffix=".tmp",
            dir=str(destination.parent),
        )
        staging = Path(temporary_name)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = None
            handle.write(payload)
            handle.flush()
        if staging.read_bytes() != payload:
            _fail("METRICS_IO_ERROR", "staged JSON readback differs from serialized bytes")
        if json.loads(payload.decode("utf-8")) != report:
            _fail("METRICS_IO_ERROR", "staged JSON readback differs from report")
        staging.rename(destination)
    except MetricsVNextError:
        raise
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        _fail("METRICS_IO_ERROR", f"cannot write metrics atomically: {error}")
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if staging is not None and staging.exists():
            try:
                staging.unlink()
            except OSError:
                pass
