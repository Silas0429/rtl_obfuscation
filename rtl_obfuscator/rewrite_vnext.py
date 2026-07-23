"""One-pass gate generation and restore for the mapping vNext execution envelope."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
from typing import Any

from .mapping_vnext import (
    InputFileDigest,
    MappingRecord,
    MappingVNext,
)
from .rewrite_policy import RewritePolicy, build_rewrite_policy
from .source_catalog import SourceCatalog, SourceRange, build_source_catalog
from .source_set import SourceSet
from .symbol_graph import SourceSymbol, SymbolGraph, SymbolOccurrence
from .systemverilog_names import is_plain_identifier


@dataclass(frozen=True)
class AppliedEdit:
    symbol_id: str
    provenance: str
    original_name: str
    renamed_name: str
    source_range: SourceRange
    gate_range: SourceRange


@dataclass(frozen=True)
class CompileEvidence:
    catalog_parse_errors: int
    catalog_semantic_errors: int
    top_overlay_parse_errors: int | None
    top_overlay_semantic_errors: int | None


@dataclass(frozen=True)
class RewriteExecution:
    schema_version: int
    mapping_vnext: MappingVNext = field(repr=False, compare=False)
    filelist: str
    gate_manifest: tuple[InputFileDigest, ...]
    edits: tuple[AppliedEdit, ...]
    compile_evidence: CompileEvidence

    def to_report(self) -> dict[str, object]:
        renamed_records = sum(
            record.action == "rename"
            for record in self.mapping_vnext.records
        )
        return {
            "format": "rtl-obfuscation.rewrite-execution",
            "schema_version": self.schema_version,
            "state": "gate-verified",
            "mapping": self.mapping_vnext.to_report(),
            "filelist": self.filelist,
            "gate_manifest": [
                {"file": item.file, "sha256": item.sha256}
                for item in self.gate_manifest
            ],
            "edits": [_edit_report(edit) for edit in self.edits],
            "compile": {
                "catalog_parse_errors": self.compile_evidence.catalog_parse_errors,
                "catalog_semantic_errors": self.compile_evidence.catalog_semantic_errors,
                "top_overlay_parse_errors": self.compile_evidence.top_overlay_parse_errors,
                "top_overlay_semantic_errors": self.compile_evidence.top_overlay_semantic_errors,
            },
            "summary": {
                "files": len(self.gate_manifest),
                "mapping_records": len(self.mapping_vnext.records),
                "renamed_records": renamed_records,
                "modified_tokens": len(self.edits),
            },
        }


@dataclass(frozen=True)
class RestoreResult:
    schema_version: int
    rewrite_execution: RewriteExecution = field(repr=False, compare=False)
    restored_manifest: tuple[InputFileDigest, ...]

    def to_report(self) -> dict[str, object]:
        return {
            "format": "rtl-obfuscation.restore-result",
            "schema_version": self.schema_version,
            "state": "restored",
            "restored_manifest": [
                {"file": item.file, "sha256": item.sha256}
                for item in self.restored_manifest
            ],
            "summary": {
                "files": len(self.restored_manifest),
                "modified_tokens": len(self.rewrite_execution.edits),
                "byte_identical": True,
            },
        }


@dataclass(frozen=True)
class MappingExecutionVNext:
    schema_version: int
    rewrite_execution: RewriteExecution = field(repr=False, compare=False)
    restore_result: RestoreResult = field(repr=False, compare=False)

    def to_report(self) -> dict[str, object]:
        mapping, files, per_file_mapping = _validate_mapping_execution(self)
        gate_manifest = self.rewrite_execution.gate_manifest
        restored_manifest = self.restore_result.restored_manifest
        input_manifest = mapping.input_manifest
        renamed_records = sum(record.action == "rename" for record in mapping.records)
        modified_tokens = len(self.rewrite_execution.edits)
        return {
            "format": "rtl-obfuscation.mapping-execution-vnext",
            "schema_version": self.schema_version,
            "state": "restored",
            "mapping": mapping.to_report(),
            "filelist": "design.f",
            "input_manifest": [_digest_report(item) for item in input_manifest],
            "gate_manifest": [_digest_report(item) for item in gate_manifest],
            "restored_manifest": [_digest_report(item) for item in restored_manifest],
            "per_file_mapping": per_file_mapping,
            "summary": {
                "files": len(files),
                "mapping_records": len(mapping.records),
                "renamed_records": renamed_records,
                "modified_tokens": modified_tokens,
                "per_file_records": sum(
                    len(file_entry["records"]) for file_entry in per_file_mapping
                ),
                "input_gate_manifest_equal": input_manifest == gate_manifest,
                "restored_input_manifest_equal": restored_manifest == input_manifest,
                "restored_byte_identical": restored_manifest == input_manifest,
            },
        }


class RewriteVNextError(ValueError):
    """Stable fail-closed error for rewrite vNext execution."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


_LEXICAL_IDENTIFIER = re.compile(rb"[A-Za-z][A-Za-z0-9_]*")


def _fail(code: str, message: str) -> None:
    raise RewriteVNextError(code, message)


def _is_schema_one(value: object) -> bool:
    return type(value) is int and value == 1


def _range_report(source_range: SourceRange) -> dict[str, object]:
    return {
        "file": source_range.file,
        "start": source_range.start,
        "end": source_range.end,
    }


def _edit_report(edit: AppliedEdit) -> dict[str, object]:
    return {
        "symbol_id": edit.symbol_id,
        "provenance": edit.provenance,
        "original_name": edit.original_name,
        "renamed_name": edit.renamed_name,
        "source_range": _range_report(edit.source_range),
        "gate_range": _range_report(edit.gate_range),
    }


_SHA256 = re.compile(r"[0-9a-f]{64}")


def _digest_report(item: InputFileDigest) -> dict[str, object]:
    return {"file": item.file, "sha256": item.sha256}


def _portable_file(file: object) -> bool:
    if not isinstance(file, str) or not file or "\\" in file or file.startswith("/"):
        return False
    parts = file.split("/")
    return all(part not in {"", ".", ".."} for part in parts)


def _mapping_execution_context(
    mapping: object,
) -> tuple[MappingVNext, SourceSet, tuple[str, ...]]:
    if not isinstance(mapping, MappingVNext):
        _fail("MAPPING_EXECUTION_INVALID", "execution mapping is not MappingVNext")
    if mapping.format != "rtl-obfuscation.mapping-vnext" or not _is_schema_one(mapping.schema_version):
        _fail("MAPPING_EXECUTION_INVALID", "execution mapping format or schema is invalid")
    policy = mapping.rewrite_policy
    if not isinstance(policy, RewritePolicy):
        _fail("MAPPING_EXECUTION_INVALID", "execution mapping policy is invalid")
    graph = policy.symbol_graph
    if not isinstance(graph, SymbolGraph) or not _is_schema_one(graph.schema_version):
        _fail("MAPPING_EXECUTION_INVALID", "execution mapping graph is invalid")
    catalog = graph.source_catalog
    if not isinstance(catalog, SourceCatalog) or not _is_schema_one(catalog.schema_version):
        _fail("MAPPING_EXECUTION_INVALID", "execution mapping catalog is invalid")
    source_set = catalog.source_set
    if not isinstance(source_set, SourceSet) or not _is_schema_one(source_set.schema_version):
        _fail("MAPPING_EXECUTION_INVALID", "execution mapping SourceSet is invalid")
    if not isinstance(source_set.ordered_source_files, tuple) or not isinstance(source_set.included_files, tuple):
        _fail("MAPPING_MANIFEST_INVALID", "SourceSet physical file sequence is not canonical")
    files: list[str] = []
    for file in (*source_set.ordered_source_files, *source_set.included_files):
        if not _portable_file(file):
            _fail("MAPPING_MANIFEST_INVALID", "physical file path is not portable")
        if file not in files:
            files.append(file)
    if not files:
        _fail("MAPPING_MANIFEST_INVALID", "SourceSet has no physical files")
    return mapping, source_set, tuple(files)


def _validate_manifest(
    manifest: object,
    files: tuple[str, ...],
    *,
    label: str,
) -> tuple[InputFileDigest, ...]:
    if not isinstance(manifest, tuple) or len(manifest) != len(files):
        _fail("MAPPING_MANIFEST_INVALID", f"{label} shape is invalid")
    for item, file in zip(manifest, files):
        if (
            not isinstance(item, InputFileDigest)
            or item.file != file
            or not isinstance(item.sha256, str)
            or _SHA256.fullmatch(item.sha256) is None
        ):
            _fail("MAPPING_MANIFEST_INVALID", f"{label} order, file, or hash is invalid")
    return manifest


def _validate_source_range(value: object, files: tuple[str, ...], *, label: str) -> SourceRange:
    if not isinstance(value, SourceRange) or value.file not in files or not _portable_file(value.file):
        _fail("MAPPING_PER_FILE_INVALID", f"{label} is not a physical portable range")
    if type(value.start) is not int or type(value.end) is not int or not 0 <= value.start < value.end:
        _fail("MAPPING_PER_FILE_INVALID", f"{label} bounds are invalid")
    return value


def _validate_mapping_records(
    mapping: MappingVNext,
    files: tuple[str, ...],
) -> tuple[dict[tuple[str, str, SourceRange], SourceRange], ...]:
    policy = mapping.rewrite_policy
    graph = policy.symbol_graph
    if not isinstance(mapping.records, tuple) or not isinstance(graph.symbols, tuple) or not isinstance(policy.decisions, tuple):
        _fail("MAPPING_PER_FILE_INVALID", "mapping record, graph, or policy sequence is invalid")
    if len(mapping.records) != len(graph.symbols) or len(mapping.records) != len(policy.decisions):
        _fail("MAPPING_PER_FILE_INVALID", "mapping record projection is not one-to-one")

    range_keys: list[dict[tuple[str, str, SourceRange], SourceRange]] = []
    for record, symbol, decision in zip(mapping.records, graph.symbols, policy.decisions):
        if not isinstance(record, MappingRecord) or not isinstance(symbol, SourceSymbol):
            _fail("MAPPING_PER_FILE_INVALID", "mapping record or graph symbol is invalid")
        expected_fields = (
            (record.symbol_id, symbol.symbol_id),
            (record.category, getattr(decision, "category", None)),
            (record.action, getattr(decision, "action", None)),
            (record.reason, getattr(decision, "reason", None)),
            (record.original_name, symbol.name),
            (record.owner_module, symbol.owner_module),
            (record.semantic_owner, symbol.semantic_owner),
            (record.declaration, symbol.declaration),
            (record.occurrences, symbol.occurrences),
            (record.impact, symbol.impact),
            (record.abi, symbol.abi),
        )
        if any(actual != expected for actual, expected in expected_fields):
            _fail("MAPPING_PER_FILE_INVALID", "mapping record does not match established execution inputs")
        if record.action not in {"rename", "preserve", "unsupported"}:
            _fail("MAPPING_PER_FILE_INVALID", "mapping record action is invalid")
        if not isinstance(record.original_name, str) or not record.original_name:
            _fail("MAPPING_PER_FILE_INVALID", "mapping record original_name is invalid")
        if record.action == "rename":
            if not isinstance(record.renamed_name, str) or not record.renamed_name:
                _fail("MAPPING_PER_FILE_INVALID", "rename record renamed_name is invalid")
        elif record.renamed_name is not None:
            _fail("MAPPING_PER_FILE_INVALID", "preserve record renamed_name is invalid")
        if not isinstance(record.occurrences, tuple):
            _fail("MAPPING_PER_FILE_INVALID", "mapping record occurrences are not canonical")

        record_ranges: dict[tuple[str, str, SourceRange], SourceRange] = {}
        declaration = _validate_source_range(record.declaration, files, label="declaration")
        declaration_key = (record.symbol_id, "declaration", declaration)
        record_ranges[declaration_key] = declaration
        for occurrence in record.occurrences:
            if not isinstance(occurrence, SymbolOccurrence) or not isinstance(occurrence.provenance, str) or not occurrence.provenance:
                _fail("MAPPING_PER_FILE_INVALID", "mapping occurrence is invalid")
            source_range = _validate_source_range(occurrence.source_range, files, label="occurrence")
            key = (record.symbol_id, occurrence.provenance, source_range)
            if key in record_ranges:
                _fail("MAPPING_PER_FILE_INVALID", "mapping occurrence is duplicated")
            record_ranges[key] = source_range
        range_keys.append(record_ranges)
    return tuple(range_keys)


def _validate_mapping_execution(
    mapping_execution: MappingExecutionVNext,
) -> tuple[MappingVNext, tuple[str, ...], list[dict[str, object]]]:
    if not isinstance(mapping_execution, MappingExecutionVNext) or not _is_schema_one(mapping_execution.schema_version):
        _fail("MAPPING_EXECUTION_INVALID", "mapping execution schema is invalid")
    execution = mapping_execution.rewrite_execution
    restore = mapping_execution.restore_result
    if not isinstance(execution, RewriteExecution) or not _is_schema_one(execution.schema_version):
        _fail("MAPPING_EXECUTION_INVALID", "rewrite execution schema is invalid")
    if not isinstance(restore, RestoreResult) or not _is_schema_one(restore.schema_version):
        _fail("MAPPING_EXECUTION_INVALID", "restore result schema is invalid")
    if restore.rewrite_execution is not execution:
        _fail("MAPPING_EXECUTION_INVALID", "restore result does not reference the execution")
    mapping, _source_set, files = _mapping_execution_context(execution.mapping_vnext)
    if execution.filelist != "design.f":
        _fail("MAPPING_EXECUTION_INVALID", "rewrite execution filelist is invalid")
    if not isinstance(execution.edits, tuple) or not isinstance(execution.compile_evidence, CompileEvidence):
        _fail("MAPPING_EXECUTION_INVALID", "rewrite execution fields are invalid")
    if execution.mapping_vnext is not restore.rewrite_execution.mapping_vnext:
        _fail("MAPPING_EXECUTION_INVALID", "restore mapping identity does not match execution")
    input_manifest = _validate_manifest(mapping.input_manifest, files, label="input_manifest")
    gate_manifest = _validate_manifest(execution.gate_manifest, files, label="gate_manifest")
    restored_manifest = _validate_manifest(restore.restored_manifest, files, label="restored_manifest")
    if restored_manifest != input_manifest:
        _fail("MAPPING_MANIFEST_INVALID", "restored_manifest does not equal input_manifest")

    record_ranges = _validate_mapping_records(mapping, files)
    expected_edits: list[tuple[str, str, str, str, SourceRange]] = []
    for record in mapping.records:
        if record.action != "rename":
            continue
        expected_edits.append((record.symbol_id, "declaration", record.original_name, record.renamed_name or "", record.declaration))
        expected_edits.extend(
            (record.symbol_id, occurrence.provenance, record.original_name, record.renamed_name or "", occurrence.source_range)
            for occurrence in record.occurrences
        )
    if len(execution.edits) != len(expected_edits):
        _fail("MAPPING_PER_FILE_INVALID", "AppliedEdit count does not cover mapping rename ranges")
    deltas: dict[str, list[tuple[int, int, int]]] = {}
    for _symbol_id, _provenance, original_name, renamed_name, source_range in expected_edits:
        deltas.setdefault(source_range.file, []).append(
            (
                source_range.start,
                source_range.end,
                len(renamed_name.encode("utf-8")) - len(original_name.encode("utf-8")),
            )
        )
    edits_by_key: dict[tuple[str, str, SourceRange], AppliedEdit] = {}
    for edit, expected in zip(execution.edits, expected_edits):
        if not isinstance(edit, AppliedEdit):
            _fail("MAPPING_PER_FILE_INVALID", "AppliedEdit sequence contains an invalid item")
        symbol_id, provenance, original_name, renamed_name, source_range = expected
        if (
            edit.symbol_id != symbol_id
            or edit.provenance != provenance
            or edit.original_name != original_name
            or edit.renamed_name != renamed_name
            or edit.source_range != source_range
        ):
            _fail("MAPPING_PER_FILE_INVALID", "AppliedEdit does not match mapping range order")
        gate_range = _validate_source_range(edit.gate_range, files, label="gate range")
        if gate_range.file != source_range.file:
            _fail("MAPPING_PER_FILE_INVALID", "AppliedEdit gate range file differs from source range")
        earlier_delta = sum(
            delta
            for start, _end, delta in deltas[source_range.file]
            if start < source_range.start
        )
        expected_gate_range = SourceRange(
            source_range.file,
            source_range.start + earlier_delta,
            source_range.start + earlier_delta + len(renamed_name.encode("utf-8")),
        )
        if gate_range != expected_gate_range:
            _fail("MAPPING_PER_FILE_INVALID", "AppliedEdit gate range is not canonical")
        key = (edit.symbol_id, edit.provenance, edit.source_range)
        if key in edits_by_key:
            _fail("MAPPING_PER_FILE_INVALID", "AppliedEdit is duplicated")
        edits_by_key[key] = edit

    input_by_file = {item.file: item.sha256 for item in input_manifest}
    gate_by_file = {item.file: item.sha256 for item in gate_manifest}
    per_file: list[dict[str, object]] = []
    for file in files:
        projected_records: list[dict[str, object]] = []
        for record, ranges in zip(mapping.records, record_ranges):
            projected_ranges: list[dict[str, object]] = []
            ordered_ranges = [
                ("declaration", record.declaration),
                *[(occurrence.provenance, occurrence.source_range) for occurrence in record.occurrences],
            ]
            for provenance, source_range in ordered_ranges:
                if source_range.file != file:
                    continue
                key = (record.symbol_id, provenance, source_range)
                if record.action == "rename":
                    edit = edits_by_key.get(key)
                    if edit is None:
                        _fail("MAPPING_PER_FILE_INVALID", "rename range has no AppliedEdit")
                    gate_range = edit.gate_range
                else:
                    gate_range = source_range
                projected_ranges.append(
                    {
                        "provenance": provenance,
                        "source_range": _range_report(source_range),
                        "gate_range": _range_report(gate_range),
                    }
                )
            if projected_ranges:
                projected_records.append(
                    {
                        "symbol_id": record.symbol_id,
                        "category": record.category,
                        "action": record.action,
                        "reason": record.reason,
                        "original_name": record.original_name,
                        "renamed_name": record.renamed_name,
                        "owner_module": record.owner_module,
                        "semantic_owner": record.semantic_owner,
                        "impact": record.impact,
                        "abi": record.abi,
                        "ranges": projected_ranges,
                    }
                )
        per_file.append(
            {
                "file": file,
                "input_sha256": input_by_file[file],
                "gate_sha256": gate_by_file[file],
                "records": projected_records,
            }
        )
    return mapping, files, per_file


def _validate_mapping_output_path(output_file: Path) -> Path:
    try:
        path = Path(output_file).expanduser().resolve()
    except (OSError, RuntimeError, TypeError) as error:
        _fail("MAPPING_OUTPUT_INVALID", f"output path is invalid: {error}")
    if path.exists() or not path.parent.is_dir():
        _fail("MAPPING_OUTPUT_INVALID", "output_file must not exist and its parent must be a directory")
    return path


def _validate_mapping_output_protection(output_file: Path, source_set: SourceSet) -> None:
    try:
        source_root = Path(source_set.source_root).expanduser().resolve()
        output_file.relative_to(source_root)
    except ValueError:
        return
    except (OSError, RuntimeError, TypeError) as error:
        _fail("MAPPING_OUTPUT_INVALID", f"source_root is invalid: {error}")
    _fail("MAPPING_OUTPUT_INVALID", "output_file overlaps source_root or a physical source file")


def build_mapping_execution_vnext(
    rewrite_execution: RewriteExecution,
    restore_result: RestoreResult,
) -> MappingExecutionVNext:
    """Project an established T046 execution/restore pair without rebuilding inputs."""

    if not isinstance(rewrite_execution, RewriteExecution) or not isinstance(restore_result, RestoreResult):
        _fail("MAPPING_EXECUTION_INVALID", "inputs are not RewriteExecution and RestoreResult")
    envelope = MappingExecutionVNext(
        schema_version=1,
        rewrite_execution=rewrite_execution,
        restore_result=restore_result,
    )
    _validate_mapping_execution(envelope)
    return envelope


def write_mapping_execution_vnext(
    mapping_execution: MappingExecutionVNext,
    *,
    output_file: Path,
) -> None:
    """Write the validated envelope as one canonical, atomic JSON file."""

    destination = _validate_mapping_output_path(output_file)
    mapping, _files, _per_file_mapping = _validate_mapping_execution(mapping_execution)
    source_set = mapping.rewrite_policy.symbol_graph.source_catalog.source_set
    _validate_mapping_output_protection(destination, source_set)
    try:
        report = mapping_execution.to_report()
        payload = json.dumps(report, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except RewriteVNextError:
        raise
    except (TypeError, ValueError, UnicodeError) as error:
        _fail("MAPPING_IO_ERROR", f"cannot serialize mapping execution: {error}")

    staging: Path | None = None
    descriptor: int | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".mapping-execution-vnext-",
            suffix=".tmp",
            dir=str(destination.parent),
        )
        staging = Path(temporary_name)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = None
            handle.write(payload)
            handle.flush()
        if staging.read_bytes() != payload:
            _fail("MAPPING_IO_ERROR", "staged JSON readback differs from serialized bytes")
        if json.loads(payload.decode("utf-8")) != report:
            _fail("MAPPING_IO_ERROR", "staged JSON readback differs from report")
        staging.rename(destination)
    except RewriteVNextError:
        raise
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        _fail("MAPPING_IO_ERROR", f"cannot write mapping execution atomically: {error}")
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


def _physical_files(source_set: SourceSet) -> tuple[str, ...]:
    files: list[str] = []
    for file in (*source_set.ordered_source_files, *source_set.included_files):
        if not isinstance(file, str) or not file or file in files:
            if not isinstance(file, str) or not file:
                _fail("REWRITE_MAPPING_INVALID", "physical file name is invalid")
            continue
        files.append(file)
    if not files:
        _fail("REWRITE_MAPPING_INVALID", "SourceSet has no physical files")
    return tuple(files)


def _source_root(source_set: SourceSet) -> Path:
    try:
        root = Path(source_set.source_root).resolve()
    except (OSError, RuntimeError, TypeError) as error:
        _fail("REWRITE_MAPPING_INVALID", f"source_root is invalid: {error}")
    if not root.is_dir():
        _fail("REWRITE_MAPPING_INVALID", "source_root is not a directory")
    return root


def _check_regular_source_files(
    source_set: SourceSet,
    physical_files: tuple[str, ...],
    *,
    read: bool,
) -> dict[str, bytes]:
    root = _source_root(source_set)
    result: dict[str, bytes] = {}
    for file in physical_files:
        path = (root / file).resolve()
        try:
            path.relative_to(root)
            if not path.is_file() or not stat.S_ISREG(path.stat().st_mode):
                _fail("REWRITE_MAPPING_INVALID", f"physical file is not regular: {file}")
            if read:
                result[file] = path.read_bytes()
        except RewriteVNextError:
            raise
        except (OSError, ValueError) as error:
            _fail("REWRITE_MAPPING_INVALID", f"physical file is invalid: {file}: {error}")
    return result


def _manifest(data: dict[str, bytes], files: tuple[str, ...]) -> tuple[InputFileDigest, ...]:
    return tuple(
        InputFileDigest(file=file, sha256=hashlib.sha256(data[file]).hexdigest())
        for file in files
    )


def _source_set_from_mapping(
    mapping: MappingVNext,
    *,
    check_source_files: bool = True,
) -> tuple[SourceSet, SourceCatalog, SymbolGraph]:
    if not isinstance(mapping, MappingVNext):
        _fail("REWRITE_MAPPING_INVALID", "input is not MappingVNext")
    if mapping.format != "rtl-obfuscation.mapping-vnext" or not _is_schema_one(mapping.schema_version):
        _fail("REWRITE_MAPPING_INVALID", "mapping format or schema_version is invalid")
    if type(mapping.name_length) is not int or mapping.name_length < 4:
        _fail("REWRITE_MAPPING_INVALID", "mapping name_length is invalid")
    policy = mapping.rewrite_policy
    if not hasattr(policy, "symbol_graph"):
        _fail("REWRITE_MAPPING_INVALID", "mapping policy is invalid")
    graph = policy.symbol_graph
    if not isinstance(graph, SymbolGraph) or not _is_schema_one(graph.schema_version):
        _fail("REWRITE_MAPPING_INVALID", "mapping graph is invalid")
    catalog = graph.source_catalog
    if not isinstance(catalog, SourceCatalog) or not _is_schema_one(catalog.schema_version):
        _fail("REWRITE_MAPPING_INVALID", "mapping catalog is invalid")
    source_set = catalog.source_set
    if not isinstance(source_set, SourceSet) or not _is_schema_one(source_set.schema_version):
        _fail("REWRITE_MAPPING_INVALID", "mapping SourceSet is invalid")
    if not isinstance(policy.selected_categories, tuple) or not isinstance(policy.abi_categories, tuple):
        _fail("REWRITE_MAPPING_INVALID", "mapping policy selections are invalid")
    if not isinstance(policy.decisions, tuple) or not isinstance(graph.symbols, tuple):
        _fail("REWRITE_MAPPING_INVALID", "mapping policy or graph sequence is invalid")
    try:
        expected_policy = build_rewrite_policy(
            graph,
            categories=policy.selected_categories,
            abi_categories=policy.abi_categories,
        )
    except Exception as error:
        _fail("REWRITE_MAPPING_INVALID", f"mapping policy cannot be revalidated: {error}")
    if policy.decisions != expected_policy.decisions:
        _fail("REWRITE_MAPPING_INVALID", "mapping policy decisions are not canonical")
    if not isinstance(mapping.records, tuple):
        _fail("REWRITE_MAPPING_INVALID", "mapping records are not canonical")
    if len(mapping.records) != len(policy.decisions) or len(mapping.records) != len(graph.symbols):
        _fail("REWRITE_MAPPING_INVALID", "mapping record count is not one-to-one")
    for record, symbol, decision in zip(mapping.records, graph.symbols, policy.decisions):
        if not isinstance(record, MappingRecord) or not isinstance(symbol, SourceSymbol):
            _fail("REWRITE_MAPPING_INVALID", "mapping record or graph symbol is invalid")
        expected = MappingRecord(
            symbol_id=symbol.symbol_id,
            category=decision.category,
            action=decision.action,
            reason=decision.reason,
            original_name=symbol.name,
            renamed_name=None,
            owner_module=symbol.owner_module,
            semantic_owner=symbol.semantic_owner,
            declaration=symbol.declaration,
            occurrences=symbol.occurrences,
            impact=symbol.impact,
            abi=symbol.abi,
        )
        if replace(record, renamed_name=None) != expected:
            _fail("REWRITE_MAPPING_INVALID", "mapping record does not match graph or policy")
        if record.action == "rename":
            if (
                not isinstance(record.renamed_name, str)
                or len(record.renamed_name) != mapping.name_length
                or not is_plain_identifier(record.renamed_name)
            ):
                _fail("REWRITE_MAPPING_INVALID", "renamed_name is invalid")
        elif record.renamed_name is not None:
            _fail("REWRITE_MAPPING_INVALID", "preserved record has renamed_name")
        else:
            if record.action not in {"preserve", "unsupported"}:
                _fail("REWRITE_MAPPING_INVALID", "record action is invalid")
    physical_files = _physical_files(source_set)
    if check_source_files:
        _check_regular_source_files(source_set, physical_files, read=False)
    if not isinstance(mapping.input_manifest, tuple) or len(mapping.input_manifest) != len(physical_files):
        _fail("REWRITE_MAPPING_INVALID", "input manifest shape is invalid")
    for item, file in zip(mapping.input_manifest, physical_files):
        if not isinstance(item, InputFileDigest) or item.file != file or not isinstance(item.sha256, str):
            _fail("REWRITE_MAPPING_INVALID", "input manifest does not match physical files")
    if not isinstance(source_set.compile_order, tuple):
        _fail("REWRITE_MAPPING_INVALID", "compile_order is not canonical")
    if any(
        not isinstance(file, str)
        or not file.endswith(".sv")
        or file not in source_set.ordered_source_files
        for file in source_set.compile_order
    ):
        _fail("REWRITE_MAPPING_INVALID", "compile_order is not a source-file sequence")
    if len(set(source_set.compile_order)) != len(source_set.compile_order):
        _fail("REWRITE_MAPPING_INVALID", "compile_order contains duplicates")
    return source_set, catalog, graph


def _validate_ranges(
    mapping: MappingVNext,
    source_set: SourceSet,
    graph: SymbolGraph,
    data: dict[str, bytes] | None,
) -> None:
    physical = set(_physical_files(source_set))
    ranges: list[tuple[str, int, int]] = []
    for record, symbol in zip(mapping.records, graph.symbols):
        for source_range in (
            record.declaration,
            *(occurrence.source_range for occurrence in record.occurrences),
        ):
            if not isinstance(source_range, SourceRange) or source_range.file not in physical:
                _fail("REWRITE_EDIT_INVALID", "source range is not physical")
            if type(source_range.start) is not int or type(source_range.end) is not int:
                _fail("REWRITE_EDIT_INVALID", "source range bounds are not integers")
            if data is not None:
                content = data[source_range.file]
                expected = symbol.name.encode("utf-8")
                if not 0 <= source_range.start < source_range.end <= len(content):
                    _fail("REWRITE_EDIT_INVALID", "source range is outside source bytes")
                if content[source_range.start : source_range.end] != expected:
                    _fail("REWRITE_EDIT_INVALID", "source range bytes do not match original_name")
            ranges.append((source_range.file, source_range.start, source_range.end))
    seen: set[tuple[str, int, int]] = set()
    for item in ranges:
        if item in seen:
            _fail("REWRITE_EDIT_INVALID", "source ranges contain a duplicate")
        seen.add(item)
    ordered = sorted(ranges)
    for previous, current in zip(ordered, ordered[1:]):
        if previous[0] == current[0] and previous[2] > current[1]:
            _fail("REWRITE_EDIT_INVALID", "source ranges overlap")


def _validate_input_manifest(
    mapping: MappingVNext,
    source_set: SourceSet,
    data: dict[str, bytes],
) -> None:
    files = _physical_files(source_set)
    current = _manifest(data, files)
    if current != mapping.input_manifest:
        _fail("REWRITE_SOURCE_CHANGED", "input source bytes or manifest changed")


def _validate_renamed_names(mapping: MappingVNext, data: dict[str, bytes], graph: SymbolGraph) -> None:
    unavailable: set[str] = set()
    for content in data.values():
        unavailable.update(item.decode("ascii") for item in _LEXICAL_IDENTIFIER.findall(content))
    unavailable.update(symbol.name for symbol in graph.symbols)
    renamed: set[str] = set()
    for record in mapping.records:
        if record.action != "rename":
            continue
        assert record.renamed_name is not None
        if record.renamed_name in unavailable or record.renamed_name in renamed:
            _fail("REWRITE_MAPPING_INVALID", "renamed_name collides with an input or another name")
        renamed.add(record.renamed_name)


def _validate_mapping_for_write(mapping: MappingVNext) -> tuple[SourceSet, SymbolGraph, dict[str, bytes]]:
    source_set, _catalog, graph = _source_set_from_mapping(mapping)
    physical = _physical_files(source_set)
    data = _check_regular_source_files(source_set, physical, read=True)
    _validate_input_manifest(mapping, source_set, data)
    _validate_ranges(mapping, source_set, graph, data)
    _validate_renamed_names(mapping, data, graph)
    return source_set, graph, data


def _expected_edits(mapping: MappingVNext) -> tuple[AppliedEdit, ...]:
    _source_set, _catalog, graph = _source_set_from_mapping(
        mapping,
        check_source_files=False,
    )
    deltas: dict[str, list[tuple[int, int, int]]] = {}
    specifications: list[tuple[str, str, str, str, SourceRange]] = []
    for record, symbol in zip(mapping.records, graph.symbols):
        if record.action != "rename":
            continue
        assert record.renamed_name is not None
        ranges = [
            ("declaration", record.declaration),
            *[(occurrence.provenance, occurrence.source_range) for occurrence in record.occurrences],
        ]
        for provenance, source_range in ranges:
            specifications.append(
                (
                    record.symbol_id,
                    provenance,
                    record.original_name,
                    record.renamed_name,
                    source_range,
                )
            )
            delta = len(record.renamed_name.encode("utf-8")) - len(record.original_name.encode("utf-8"))
            deltas.setdefault(source_range.file, []).append(
                (source_range.start, source_range.end, delta)
            )
    edits: list[AppliedEdit] = []
    for symbol_id, provenance, original_name, renamed_name, source_range in specifications:
        earlier_delta = sum(
            delta
            for start, _end, delta in deltas.get(source_range.file, [])
            if start < source_range.start
        )
        gate_start = source_range.start + earlier_delta
        gate_end = gate_start + len(renamed_name.encode("utf-8"))
        edits.append(
            AppliedEdit(
                symbol_id=symbol_id,
                provenance=provenance,
                original_name=original_name,
                renamed_name=renamed_name,
                source_range=source_range,
                gate_range=SourceRange(source_range.file, gate_start, gate_end),
            )
        )
    if len(set(edit.source_range for edit in edits)) != len(edits):
        _fail("REWRITE_EDIT_INVALID", "edit source ranges are not unique")
    return tuple(edits)


def _validate_output_path(output_dir: Path, *, source_root: Path | None = None, gate_dir: Path | None = None, code: str) -> Path:
    try:
        path = Path(output_dir).expanduser().resolve()
    except (OSError, RuntimeError, TypeError) as error:
        _fail(code, f"output path is invalid: {error}")
    if path.exists() or not path.parent.is_dir():
        _fail(code, "output path must not exist and its parent must exist")
    for other in (source_root, gate_dir):
        if other is None:
            continue
        try:
            path.relative_to(other)
        except ValueError:
            continue
        _fail(code, "output path overlaps a protected directory")
    return path


def _write_file(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def write_gate_vnext(
    mapping_vnext: MappingVNext,
    *,
    output_dir: Path,
) -> RewriteExecution:
    """Apply all mapping edits once, compile the gate, and publish atomically."""

    source_set, graph, data = _validate_mapping_for_write(mapping_vnext)
    source_root = _source_root(source_set)
    destination = _validate_output_path(output_dir, source_root=source_root, code="REWRITE_OUTPUT_INVALID")
    edits = _expected_edits(mapping_vnext)
    by_file: dict[str, list[AppliedEdit]] = {}
    for edit in edits:
        by_file.setdefault(edit.source_range.file, []).append(edit)

    try:
        staging = Path(tempfile.mkdtemp(prefix=".rewrite-vnext-", dir=str(destination.parent)))
    except OSError as error:
        _fail("REWRITE_IO_ERROR", f"cannot create staging directory: {error}")
    try:
        gate_data: dict[str, bytes] = {}
        for file in _physical_files(source_set):
            content = data[file]
            mutable = bytearray(content)
            for edit in sorted(by_file.get(file, ()), key=lambda item: item.source_range.start, reverse=True):
                start, end = edit.source_range.start, edit.source_range.end
                if bytes(mutable[start:end]) != edit.original_name.encode("utf-8"):
                    _fail("REWRITE_GATE_AUDIT_FAILED", "source token changed before edit application")
                mutable[start:end] = edit.renamed_name.encode("utf-8")
            gate_data[file] = bytes(mutable)
            for edit in by_file.get(file, ()):
                start, end = edit.gate_range.start, edit.gate_range.end
                if gate_data[file][start:end] != edit.renamed_name.encode("utf-8"):
                    _fail("REWRITE_GATE_AUDIT_FAILED", "gate range does not match renamed_name")
            _write_file(staging / file, gate_data[file])
        filelist = "".join(f"{file}\n" for file in source_set.compile_order)
        _write_file(staging / "design.f", filelist.encode("utf-8"))
        gate_manifest = _manifest(gate_data, _physical_files(source_set))

        gate_source_set = replace(source_set, source_root=staging.resolve())
        try:
            gate_catalog = build_source_catalog(gate_source_set)
        except Exception as error:
            _fail("REWRITE_GATE_COMPILE_FAILED", f"strict gate compilation failed: {error}")
        compile_report = gate_catalog.to_report()["compile"]
        catalog_compile = compile_report["catalog"]
        top_compile = compile_report["top_overlay"]
        evidence = CompileEvidence(
            catalog_parse_errors=int(catalog_compile["parse_errors"]),
            catalog_semantic_errors=int(catalog_compile["semantic_errors"]),
            top_overlay_parse_errors=None if top_compile is None else int(top_compile["parse_errors"]),
            top_overlay_semantic_errors=None if top_compile is None else int(top_compile["semantic_errors"]),
        )
        if (
            evidence.catalog_parse_errors != 0
            or evidence.catalog_semantic_errors != 0
            or (evidence.top_overlay_parse_errors not in (None, 0))
            or (evidence.top_overlay_semantic_errors not in (None, 0))
        ):
            _fail("REWRITE_GATE_COMPILE_FAILED", "strict gate compilation has diagnostics")
        execution = RewriteExecution(
            schema_version=1,
            mapping_vnext=mapping_vnext,
            filelist="design.f",
            gate_manifest=gate_manifest,
            edits=edits,
            compile_evidence=evidence,
        )
        try:
            staging.rename(destination)
        except OSError as error:
            _fail("REWRITE_IO_ERROR", f"cannot publish gate atomically: {error}")
        return execution
    except RewriteVNextError:
        raise
    except OSError as error:
        _fail("REWRITE_IO_ERROR", str(error))
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def _validate_execution(execution: RewriteExecution) -> tuple[SourceSet, SymbolGraph, tuple[AppliedEdit, ...]]:
    if not isinstance(execution, RewriteExecution) or not _is_schema_one(execution.schema_version):
        _fail("RESTORE_EXECUTION_INVALID", "rewrite execution schema is invalid")
    if execution.filelist != "design.f" or not isinstance(execution.gate_manifest, tuple):
        _fail("RESTORE_EXECUTION_INVALID", "rewrite execution filelist or manifest is invalid")
    source_set, _catalog, graph = _source_set_from_mapping(
        execution.mapping_vnext,
        check_source_files=False,
    )
    edits = _expected_edits(execution.mapping_vnext)
    if not isinstance(execution.edits, tuple) or execution.edits != edits:
        _fail("RESTORE_EXECUTION_INVALID", "rewrite execution edits are not canonical")
    files = _physical_files(source_set)
    if len(execution.gate_manifest) != len(files):
        _fail("RESTORE_EXECUTION_INVALID", "gate manifest count is invalid")
    if any(
        not isinstance(item, InputFileDigest) or item.file != file or not isinstance(item.sha256, str)
        for item, file in zip(execution.gate_manifest, files)
    ):
        _fail("RESTORE_EXECUTION_INVALID", "gate manifest shape is invalid")
    evidence = execution.compile_evidence
    if not isinstance(evidence, CompileEvidence):
        _fail("RESTORE_EXECUTION_INVALID", "compile evidence is invalid")
    return source_set, graph, edits


def restore_gate_vnext(
    rewrite_execution: RewriteExecution,
    *,
    gate_dir: Path,
    output_dir: Path,
) -> RestoreResult:
    """Restore original bytes using only execution metadata and gate bytes."""

    try:
        gate_path = Path(gate_dir).expanduser().resolve()
    except (OSError, RuntimeError, TypeError) as error:
        _fail("RESTORE_GATE_INVALID", f"gate path is invalid: {error}")
    destination = _validate_output_path(output_dir, gate_dir=gate_path, code="RESTORE_OUTPUT_INVALID")
    if not gate_path.is_dir():
        _fail("RESTORE_GATE_INVALID", "gate directory does not exist")
    source_set, _graph, edits = _validate_execution(rewrite_execution)
    files = _physical_files(source_set)
    try:
        filelist_bytes = (gate_path / rewrite_execution.filelist).read_bytes()
    except OSError as error:
        _fail("RESTORE_GATE_INVALID", f"canonical design.f is unavailable: {error}")
    expected_filelist = "".join(f"{file}\n" for file in source_set.compile_order).encode("utf-8")
    if filelist_bytes != expected_filelist:
        _fail("RESTORE_GATE_INVALID", "canonical design.f does not match compile_order")
    gate_data: dict[str, bytes] = {}
    for file in files:
        try:
            gate_data[file] = (gate_path / file).read_bytes()
        except OSError as error:
            _fail("RESTORE_GATE_INVALID", f"gate physical file is unavailable: {file}: {error}")
    current_manifest = _manifest(gate_data, files)
    if current_manifest != rewrite_execution.gate_manifest:
        _fail("RESTORE_GATE_INVALID", "gate manifest changed")
    for edit in edits:
        if gate_data[edit.gate_range.file][edit.gate_range.start : edit.gate_range.end] != edit.renamed_name.encode("utf-8"):
            _fail("RESTORE_RANGE_INVALID", "gate range does not match renamed_name")

    restored_data: dict[str, bytes] = dict(gate_data)
    by_file: dict[str, list[AppliedEdit]] = {}
    for edit in edits:
        by_file.setdefault(edit.gate_range.file, []).append(edit)
    for file, file_edits in by_file.items():
        mutable = bytearray(restored_data[file])
        for edit in sorted(file_edits, key=lambda item: item.gate_range.start, reverse=True):
            start, end = edit.gate_range.start, edit.gate_range.end
            mutable[start:end] = edit.original_name.encode("utf-8")
        restored_data[file] = bytes(mutable)
    expected_manifest = rewrite_execution.mapping_vnext.input_manifest
    restored_manifest = _manifest(restored_data, files)
    if restored_manifest != expected_manifest:
        _fail("RESTORE_BYTES_MISMATCH", "restored manifest differs from mapping input manifest")

    try:
        staging = Path(tempfile.mkdtemp(prefix=".restore-vnext-", dir=str(destination.parent)))
    except OSError as error:
        _fail("RESTORE_IO_ERROR", f"cannot create restore staging directory: {error}")
    try:
        for file in files:
            _write_file(staging / file, restored_data[file])
        staging.rename(destination)
    except RewriteVNextError:
        raise
    except OSError as error:
        _fail("RESTORE_IO_ERROR", f"cannot publish restored files: {error}")
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
    return RestoreResult(schema_version=1, rewrite_execution=rewrite_execution, restored_manifest=restored_manifest)
