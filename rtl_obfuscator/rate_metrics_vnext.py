"""Audit bridge from a T050 rate execution to T047 and T048 envelopes."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import metrics_vnext, rate_execution_vnext
from .rate_vnext import RateSelectionVNext
from .rewrite_vnext import MappingExecutionVNext, RewriteVNextError, build_mapping_execution_vnext


@dataclass(frozen=True)
class RateMetricsVNext:
    schema_version: int
    rate_execution: rate_execution_vnext.RateRewriteExecutionVNext = field(
        repr=False,
        compare=False,
    )
    mapping_execution: MappingExecutionVNext = field(repr=False, compare=False)
    metrics: metrics_vnext.MetricsVNext = field(repr=False, compare=False)

    def to_report(self) -> dict[str, object]:
        rate_execution = _validate_rate_metrics(self)
        rate_selection_report = rate_execution.rate_selection.to_report()
        mapping_report = _portable_report(self.mapping_execution.to_report())
        metrics_report = self.metrics.to_report()
        mapping = rate_execution.rewrite_execution.mapping_vnext
        evidence = rate_execution.rewrite_execution.compile_evidence
        mapping_summary = mapping_report.get("summary")
        if not isinstance(mapping_summary, dict):
            _fail("RATE_METRICS_ENVELOPE_INVALID", "T047 summary is invalid")
        if metrics_report.get("state") != "verified":
            _fail("RATE_METRICS_INVALID", "T048 metrics are not verified")
        return {
            "format": "rtl-obfuscation.rate-metrics-vnext",
            "schema_version": self.schema_version,
            "state": "restored",
            "rate_selection": rate_selection_report,
            "mapping_execution": mapping_report,
            "metrics": metrics_report,
            "summary": {
                "files": len(self.mapping_execution.rewrite_execution.gate_manifest),
                "mapping_records": len(mapping.records),
                "selected_renamed_records": sum(record.action == "rename" for record in mapping.records),
                "rate_unselected_records": sum(
                    record.action == "preserve" and record.reason == "rate_unselected"
                    for record in mapping.records
                ),
                "modified_tokens": len(self.mapping_execution.rewrite_execution.edits),
                "strict_compile_passed": _strict_compile_passed(evidence),
                "restored_byte_identical": mapping_summary.get("restored_byte_identical") is True,
                "effective_line_total": self.metrics.effective_line_total,
                "affected_line_count": self.metrics.affected_line_count,
                "symbol_coverage": metrics_report["symbols"]["coverage"],
                "occurrence_coverage": metrics_report["occurrences"]["coverage"],
                "plaintext_leakage_rate": metrics_report["plaintext_leakage_rate"],
                "effective_coverage": metrics_report["effective_coverage"],
            },
        }


class RateMetricsVNextError(ValueError):
    """Stable fail-closed error for the rate metrics adapter."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def _fail(code: str, message: str) -> None:
    raise RateMetricsVNextError(code, message)


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


def _strict_compile_passed(evidence: object) -> bool:
    return (
        isinstance(evidence, rate_execution_vnext.rewrite_vnext.CompileEvidence)
        and evidence.catalog_parse_errors == 0
        and evidence.catalog_semantic_errors == 0
        and evidence.top_overlay_parse_errors in (None, 0)
        and evidence.top_overlay_semantic_errors in (None, 0)
    )


def _validate_rate_execution_input(
    rate_execution: object,
) -> rate_execution_vnext.RateRewriteExecutionVNext:
    if not isinstance(rate_execution, rate_execution_vnext.RateRewriteExecutionVNext):
        _fail("RATE_METRICS_EXECUTION_INVALID", "input is not RateRewriteExecutionVNext")
    if type(rate_execution.schema_version) is not int or rate_execution.schema_version != 1:
        _fail("RATE_METRICS_EXECUTION_INVALID", "rate execution schema is invalid")
    if not isinstance(rate_execution.rate_selection, RateSelectionVNext):
        _fail("RATE_METRICS_EXECUTION_INVALID", "rate selection is invalid")
    if not isinstance(rate_execution.rewrite_execution, rate_execution_vnext.rewrite_vnext.RewriteExecution):
        _fail("RATE_METRICS_EXECUTION_INVALID", "rewrite execution is invalid")
    selected_mapping = rate_execution.rewrite_execution.mapping_vnext
    selection_mapping = rate_execution.rate_selection.mapping_vnext
    if (
        selected_mapping.rewrite_policy.symbol_graph
        is not selection_mapping.rewrite_policy.symbol_graph
    ):
        _fail("RATE_METRICS_EXECUTION_INVALID", "T050 selection and selected mapping graph identity differs")
    try:
        rate_execution.to_report()
    except rate_execution_vnext.RateExecutionVNextError as error:
        _fail("RATE_METRICS_EXECUTION_INVALID", f"T050 execution is invalid: {error.message}")
    return rate_execution


def _validate_rate_metrics(rate_metrics: object) -> RateRewriteExecutionVNext:
    if not isinstance(rate_metrics, RateMetricsVNext) or type(rate_metrics.schema_version) is not int or rate_metrics.schema_version != 1:
        _fail("RATE_METRICS_EXECUTION_INVALID", "rate metrics schema is invalid")
    rate_execution = _validate_rate_execution_input(rate_metrics.rate_execution)
    if not isinstance(rate_metrics.mapping_execution, MappingExecutionVNext):
        _fail("RATE_METRICS_ENVELOPE_INVALID", "mapping execution is invalid")
    if rate_metrics.mapping_execution.rewrite_execution is not rate_execution.rewrite_execution:
        _fail("RATE_METRICS_ENVELOPE_INVALID", "mapping execution identity differs from T050 execution")
    try:
        mapping_report = rate_metrics.mapping_execution.to_report()
    except RewriteVNextError as error:
        _fail("RATE_METRICS_ENVELOPE_INVALID", f"T047 envelope is invalid: {error.message}")
    mapping_summary = mapping_report.get("summary")
    if (
        not isinstance(mapping_summary, dict)
        or mapping_report.get("state") != "restored"
        or mapping_summary.get("restored_input_manifest_equal") is not True
        or mapping_summary.get("restored_byte_identical") is not True
    ):
        _fail("RATE_METRICS_ENVELOPE_INVALID", "T047 restore state is not verified")
    if not isinstance(rate_metrics.metrics, metrics_vnext.MetricsVNext):
        _fail("RATE_METRICS_INVALID", "metrics object is invalid")
    if rate_metrics.metrics.mapping_execution is not rate_metrics.mapping_execution:
        _fail("RATE_METRICS_INVALID", "metrics identity differs from T047 envelope")
    try:
        metrics_report = rate_metrics.metrics.to_report()
    except metrics_vnext.MetricsVNextError as error:
        _fail("RATE_METRICS_INVALID", f"T048 metrics are invalid: {error.message}")
    if metrics_report.get("state") != "verified":
        _fail("RATE_METRICS_INVALID", "T048 metrics state is not verified")
    return rate_execution


def build_rate_metrics_vnext(
    rate_execution: rate_execution_vnext.RateRewriteExecutionVNext,
    *,
    gate_dir: Path,
    restore_dir: Path,
) -> RateMetricsVNext:
    """Restore and audit one established T050 actual selected gate."""

    rate_execution = _validate_rate_execution_input(rate_execution)
    try:
        restore_result = rate_execution_vnext.restore_rate_selected_gate_vnext(
            rate_execution,
            gate_dir,
            restore_dir,
        )
    except rate_execution_vnext.RateExecutionVNextError as error:
        _fail("RATE_METRICS_RESTORE_INVALID", f"T050 restore failed: {error.message}")
    if not isinstance(restore_result, rate_execution_vnext.rewrite_vnext.RestoreResult):
        _fail("RATE_METRICS_RESTORE_INVALID", "T050 restore result is invalid")
    try:
        mapping_execution = build_mapping_execution_vnext(
            rate_execution.rewrite_execution,
            restore_result,
        )
    except RewriteVNextError as error:
        _fail("RATE_METRICS_ENVELOPE_INVALID", f"T047 envelope failed: {error.message}")
    if not isinstance(mapping_execution, MappingExecutionVNext):
        _fail("RATE_METRICS_ENVELOPE_INVALID", "T047 mapping execution is invalid")
    try:
        metrics = metrics_vnext.build_metrics_vnext(
            mapping_execution,
            gate_dir=gate_dir,
        )
    except metrics_vnext.MetricsVNextError as error:
        _fail("RATE_METRICS_INVALID", f"T048 metrics failed: {error.message}")
    if not isinstance(metrics, metrics_vnext.MetricsVNext):
        _fail("RATE_METRICS_INVALID", "T048 metrics object is invalid")
    if mapping_execution.rewrite_execution is not rate_execution.rewrite_execution:
        _fail("RATE_METRICS_ENVELOPE_INVALID", "T047 execution identity was not preserved")
    if metrics.mapping_execution is not mapping_execution:
        _fail("RATE_METRICS_INVALID", "T048 metrics identity was not preserved")
    result = RateMetricsVNext(
        schema_version=1,
        rate_execution=rate_execution,
        mapping_execution=mapping_execution,
        metrics=metrics,
    )
    _validate_rate_metrics(result)
    return result
