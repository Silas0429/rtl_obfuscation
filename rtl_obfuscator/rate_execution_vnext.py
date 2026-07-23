"""Materialize a T049 selection and execute it through the T046 gate engine."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

from . import rewrite_vnext
from .mapping_vnext import MappingRecord, MappingVNext
from .rate_vnext import RateCandidateVNext, RateSelectionVNext, RateVNextError
from .rewrite_policy import RewriteDecision, RewritePolicy


@dataclass(frozen=True)
class RateRewriteExecutionVNext:
    schema_version: int
    rate_selection: RateSelectionVNext = field(repr=False, compare=False)
    rewrite_execution: rewrite_vnext.RewriteExecution = field(repr=False, compare=False)

    def to_report(self) -> dict[str, object]:
        _validate_rate_execution(self)
        execution_report = _portable_report(self.rewrite_execution.to_report())
        selection_report = self.rate_selection.to_report()
        mapping = self.rewrite_execution.mapping_vnext
        evidence = self.rewrite_execution.compile_evidence
        return {
            "format": "rtl-obfuscation.rate-rewrite-execution-vnext",
            "schema_version": self.schema_version,
            "state": "gate-verified",
            "rate_selection": selection_report,
            "rewrite_execution": execution_report,
            "summary": {
                "files": len(self.rewrite_execution.gate_manifest),
                "mapping_records": len(mapping.records),
                "selected_renamed_records": sum(record.action == "rename" for record in mapping.records),
                "rate_unselected_records": sum(
                    record.action == "preserve" and record.reason == "rate_unselected"
                    for record in mapping.records
                ),
                "modified_tokens": len(self.rewrite_execution.edits),
                "strict_compile_passed": _strict_compile_passed(evidence),
                "restored_byte_identical": True,
            },
        }


class RateExecutionVNextError(ValueError):
    """Stable fail-closed error for rate-selected execution."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def _fail(code: str, message: str) -> None:
    raise RateExecutionVNextError(code, message)


def _portable_report(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: _portable_report(item)
            for key, item in value.items()
            if key != "source_root"
        }
    if isinstance(value, list):
        return [_portable_report(item) for item in value]
    return value


def _strict_compile_passed(evidence: rewrite_vnext.CompileEvidence) -> bool:
    return (
        evidence.catalog_parse_errors == 0
        and evidence.catalog_semantic_errors == 0
        and evidence.top_overlay_parse_errors in (None, 0)
        and evidence.top_overlay_semantic_errors in (None, 0)
    )


def _selection_candidates(
    mapping_vnext: object,
    rate_selection: object,
) -> tuple[MappingVNext, RateSelectionVNext, tuple[RateCandidateVNext, ...], set[str]]:
    if not isinstance(mapping_vnext, MappingVNext) or not isinstance(rate_selection, RateSelectionVNext):
        _fail("RATE_EXECUTION_INVALID", "inputs are not MappingVNext and RateSelectionVNext")
    if rate_selection.mapping_vnext is not mapping_vnext:
        _fail("RATE_EXECUTION_INVALID", "rate selection mapping identity differs")
    if type(rate_selection.schema_version) is not int or rate_selection.schema_version != 1:
        _fail("RATE_EXECUTION_INVALID", "rate selection schema is invalid")
    try:
        rate_selection.to_report()
    except RateVNextError as error:
        _fail("RATE_EXECUTION_INVALID", f"rate selection is invalid: {error.message}")
    candidates = rate_selection.candidates
    if not isinstance(candidates, tuple):
        _fail("RATE_EXECUTION_INVALID", "rate selection candidates are not canonical")
    candidate_ids: set[str] = set()
    mapping_by_id = {record.symbol_id: record for record in mapping_vnext.records}
    for candidate in candidates:
        if not isinstance(candidate, RateCandidateVNext) or type(candidate.selected) is not bool:
            _fail("RATE_EXECUTION_INVALID", "rate selection candidate is invalid")
        if candidate.symbol_id in candidate_ids:
            _fail("RATE_EXECUTION_INVALID", "rate selection has duplicate symbol_id")
        candidate_ids.add(candidate.symbol_id)
        record = mapping_by_id.get(candidate.symbol_id)
        if record is None or record.action != "rename":
            _fail("RATE_EXECUTION_INVALID", "rate selection candidate is not a rename record")
        if (
            candidate.category != record.category
            or candidate.owner_module != record.owner_module
            or candidate.original_name != record.original_name
            or candidate.declaration != record.declaration
        ):
            _fail("RATE_EXECUTION_INVALID", "rate selection candidate identity differs")
    rename_ids = {record.symbol_id for record in mapping_vnext.records if record.action == "rename"}
    if candidate_ids != rename_ids:
        _fail("RATE_EXECUTION_INVALID", "rate selection does not cover all rename records")
    selected_ids = {candidate.symbol_id for candidate in candidates if candidate.selected}
    return mapping_vnext, rate_selection, candidates, selected_ids


def build_rate_selected_mapping_vnext(
    mapping_vnext: MappingVNext,
    rate_selection: RateSelectionVNext,
) -> MappingVNext:
    """Materialize selected rename records without recollecting semantic inputs."""

    mapping_vnext, _selection, _candidates, selected_ids = _selection_candidates(
        mapping_vnext,
        rate_selection,
    )
    policy = mapping_vnext.rewrite_policy
    if not isinstance(policy, RewritePolicy) or not isinstance(policy.decisions, tuple):
        _fail("RATE_MAPPING_INVALID", "mapping policy or decisions are invalid")
    if len(policy.decisions) != len(mapping_vnext.records):
        _fail("RATE_MAPPING_INVALID", "mapping records and decisions are not one-to-one")

    records: list[MappingRecord] = []
    decisions: list[RewriteDecision] = []
    for record, decision in zip(mapping_vnext.records, policy.decisions):
        if not isinstance(record, MappingRecord) or not isinstance(decision, RewriteDecision):
            _fail("RATE_MAPPING_INVALID", "mapping record or decision is invalid")
        if record.action == "rename":
            if record.symbol_id in selected_ids:
                records.append(record)
                decisions.append(replace(decision, action="rename", reason=None))
            else:
                records.append(
                    replace(
                        record,
                        action="preserve",
                        reason="rate_unselected",
                        renamed_name=None,
                    )
                )
                decisions.append(
                    replace(decision, action="preserve", reason="rate_unselected")
                )
        else:
            records.append(record)
            decisions.append(decision)

    materialized_policy = replace(policy, decisions=tuple(decisions))
    return replace(
        mapping_vnext,
        rewrite_policy=materialized_policy,
        records=tuple(records),
    )


def _map_rewrite_error(error: rewrite_vnext.RewriteVNextError, *, restoring: bool) -> None:
    if restoring:
        if error.code in {"RESTORE_OUTPUT_INVALID"}:
            code = "RATE_OUTPUT_INVALID"
        elif error.code == "RESTORE_IO_ERROR":
            code = "RATE_IO_ERROR"
        else:
            code = "RATE_RESTORE_INVALID"
    else:
        if error.code == "REWRITE_OUTPUT_INVALID":
            code = "RATE_OUTPUT_INVALID"
        elif error.code == "REWRITE_IO_ERROR":
            code = "RATE_IO_ERROR"
        elif error.code == "REWRITE_MAPPING_INVALID":
            code = "RATE_MAPPING_INVALID"
        else:
            code = "RATE_GATE_INVALID"
    _fail(code, error.message)


def _validate_rate_execution(rate_execution: object) -> RateRewriteExecutionVNext:
    if not isinstance(rate_execution, RateRewriteExecutionVNext) or type(rate_execution.schema_version) is not int or rate_execution.schema_version != 1:
        _fail("RATE_EXECUTION_INVALID", "rate execution schema is invalid")
    mapping, selection, _candidates, _selected_ids = _selection_candidates(
        rate_execution.rate_selection.mapping_vnext,
        rate_execution.rate_selection,
    )
    if not isinstance(rate_execution.rewrite_execution, rewrite_vnext.RewriteExecution):
        _fail("RATE_EXECUTION_INVALID", "rewrite execution is invalid")
    expected_mapping = build_rate_selected_mapping_vnext(mapping, selection)
    actual_mapping = rate_execution.rewrite_execution.mapping_vnext
    if actual_mapping != expected_mapping or actual_mapping.rewrite_policy.decisions != expected_mapping.rewrite_policy.decisions:
        _fail("RATE_MAPPING_INVALID", "rewrite execution does not reference materialized mapping")
    evidence = rate_execution.rewrite_execution.compile_evidence
    if not isinstance(evidence, rewrite_vnext.CompileEvidence) or not _strict_compile_passed(evidence):
        _fail("RATE_GATE_INVALID", "selected gate strict compile is not clean")
    if rate_execution.rewrite_execution.filelist != "design.f":
        _fail("RATE_EXECUTION_INVALID", "rewrite execution filelist is invalid")
    return rate_execution


def write_rate_selected_gate_vnext(
    mapping_vnext: MappingVNext,
    rate_selection: RateSelectionVNext,
    output_dir: Path,
) -> RateRewriteExecutionVNext:
    """Materialize the selection and invoke the existing one-pass gate engine."""

    selected_mapping = build_rate_selected_mapping_vnext(mapping_vnext, rate_selection)
    try:
        rewrite_execution = rewrite_vnext.write_gate_vnext(
            selected_mapping,
            output_dir=output_dir,
            _validate_canonical_policy=False,
        )
    except rewrite_vnext.RewriteVNextError as error:
        _map_rewrite_error(error, restoring=False)
    execution = RateRewriteExecutionVNext(
        schema_version=1,
        rate_selection=rate_selection,
        rewrite_execution=rewrite_execution,
    )
    _validate_rate_execution(execution)
    return execution


def restore_rate_selected_gate_vnext(
    rate_execution: RateRewriteExecutionVNext,
    gate_dir: Path,
    output_dir: Path,
) -> rewrite_vnext.RestoreResult:
    """Restore a selected gate through the existing T046 restore implementation."""

    _validate_rate_execution(rate_execution)
    try:
        return rewrite_vnext.restore_gate_vnext(
            rate_execution.rewrite_execution,
            gate_dir=gate_dir,
            output_dir=output_dir,
            _validate_canonical_policy=False,
        )
    except rewrite_vnext.RewriteVNextError as error:
        _map_rewrite_error(error, restoring=True)
