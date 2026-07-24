"""Single-file and explicit-filelist orchestration for the vNext pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from pathlib import Path
import shutil
from typing import Iterable

from .mapping_vnext import MappingVNext, NameFactory, build_mapping_vnext
from .metrics_vnext import MetricsVNext, MetricsVNextError, build_metrics_vnext
from .rate_execution_vnext import (
    RateExecutionVNextError,
    RateRewriteExecutionVNext,
    write_rate_selected_gate_vnext,
)
from .rate_metrics_vnext import (
    RateMetricsVNext,
    RateMetricsVNextError,
    build_rate_metrics_vnext,
)
from .rate_vnext import RateSelectionVNext, RateVNextError, build_rate_selection_vnext
from .rewrite_policy import RewritePolicyError, build_rewrite_policy
from .rewrite_vnext import (
    CompileEvidence,
    MappingExecutionVNext,
    RestoreResult,
    RewriteExecution,
    RewriteVNextError,
    build_mapping_execution_vnext,
    restore_gate_vnext,
    write_gate_vnext,
)
from .source_catalog import SourceCatalogError, build_source_catalog
from .source_set import SourceSet
from .symbol_graph import SymbolGraphError, build_symbol_graph
from .systemverilog_names import secure_name_factory


_ABSOLUTE_PATH = re.compile(r"^(?:/|[A-Za-z]:[\\/])")
_PRIVATE_PATH_KEYS = frozenset(
    {"source_root", "gate_dir", "restore_dir", "output_dir", "temporary_directory"}
)


class OrchestrationVNextError(ValueError):
    """Stable fail-closed error for the orchestration service."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def _fail(code: str, message: str) -> None:
    raise OrchestrationVNextError(code, message)


def _portable_report(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: _portable_report(item)
            for key, item in value.items()
            if key not in _PRIVATE_PATH_KEYS
        }
    if isinstance(value, list):
        return [_portable_report(item) for item in value]
    return value


def _contains_absolute_path(value: object) -> bool:
    if isinstance(value, dict):
        return any(_contains_absolute_path(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_absolute_path(item) for item in value)
    return isinstance(value, str) and _ABSOLUTE_PATH.match(value) is not None


def _source_set_report(source_set: SourceSet) -> dict[str, object]:
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


def _strict_compile_passed(evidence: object) -> bool:
    return (
        isinstance(evidence, CompileEvidence)
        and evidence.catalog_parse_errors == 0
        and evidence.catalog_semantic_errors == 0
        and evidence.top_overlay_parse_errors in (None, 0)
        and evidence.top_overlay_semantic_errors in (None, 0)
    )


def _validate_source_set(source_set: object) -> SourceSet:
    if not isinstance(source_set, SourceSet):
        _fail("ORCHESTRATION_INPUT_INVALID", "input is not SourceSet")
    if type(source_set.schema_version) is not int or source_set.schema_version != 1:
        _fail("ORCHESTRATION_INPUT_INVALID", "SourceSet schema is invalid")
    if source_set.origin not in {"single-file", "filelist", "project-root"}:
        _fail("ORCHESTRATION_INPUT_INVALID", "only single-file, filelist, and project-root origins are supported")
    if source_set.origin == "project-root" and not isinstance(source_set.top, str):
        _fail("ORCHESTRATION_INPUT_INVALID", "project-root SourceSet requires top")
    try:
        source_root = Path(source_set.source_root).expanduser().resolve()
    except (OSError, RuntimeError, TypeError) as error:
        _fail("ORCHESTRATION_INPUT_INVALID", f"SourceSet source_root is invalid: {error}")
    if not source_root.is_dir():
        _fail("ORCHESTRATION_INPUT_INVALID", "SourceSet source_root is not a directory")
    if not isinstance(source_set.compile_order, tuple) or not source_set.compile_order:
        _fail("ORCHESTRATION_INPUT_INVALID", "SourceSet compile_order is invalid")
    return source_set


def _resolve_output(path: object, *, label: str) -> Path:
    try:
        resolved = Path(path).expanduser().resolve()
    except (OSError, RuntimeError, TypeError) as error:
        _fail("ORCHESTRATION_INPUT_INVALID", f"{label} is invalid: {error}")
    if resolved.exists() or not resolved.parent.is_dir():
        _fail("ORCHESTRATION_INPUT_INVALID", f"{label} must not exist and its parent must exist")
    return resolved


def _paths_overlap(left: Path, right: Path) -> bool:
    try:
        left.relative_to(right)
        return True
    except ValueError:
        pass
    try:
        right.relative_to(left)
        return True
    except ValueError:
        return False


def _validate_outputs(source_set: SourceSet, gate_dir: object, restore_dir: object) -> tuple[Path, Path]:
    gate_path = _resolve_output(gate_dir, label="gate_dir")
    restore_path = _resolve_output(restore_dir, label="restore_dir")
    source_root = Path(source_set.source_root).expanduser().resolve()
    if _paths_overlap(gate_path, restore_path) or _paths_overlap(gate_path, source_root) or _paths_overlap(restore_path, source_root):
        _fail("ORCHESTRATION_INPUT_INVALID", "output path overlaps a protected path")
    return gate_path, restore_path


def _cleanup_created(paths: Iterable[Path]) -> None:
    for path in paths:
        try:
            if path.exists() and path.is_dir():
                shutil.rmtree(path)
        except OSError:
            pass


def _build_mapping(
    source_set: SourceSet,
    *,
    categories: Iterable[str],
    abi_categories: Iterable[str],
    name_length: int,
    name_factory: NameFactory,
) -> MappingVNext:
    try:
        catalog = build_source_catalog(source_set)
        graph = build_symbol_graph(catalog)
        policy = build_rewrite_policy(
            graph,
            categories=categories,
            abi_categories=abi_categories,
        )
        return build_mapping_vnext(
            policy,
            name_length=name_length,
            name_factory=name_factory,
        )
    except (SourceCatalogError, SymbolGraphError, RewritePolicyError) as error:
        _fail("ORCHESTRATION_MAPPING_INVALID", str(error).split(": ", 1)[-1])
    except Exception as error:
        _fail("ORCHESTRATION_MAPPING_INVALID", str(error))
    raise AssertionError("unreachable")


def _validate_pipeline_identity(
    source_set: SourceSet,
    mapping: MappingVNext,
    effective_mapping: MappingVNext,
    mapping_execution: MappingExecutionVNext,
    metrics: MetricsVNext,
    rate_metrics: RateMetricsVNext | None,
) -> None:
    if not isinstance(mapping, MappingVNext):
        _fail("ORCHESTRATION_AUDIT_INVALID", "mapping is not MappingVNext")
    if not isinstance(effective_mapping, MappingVNext):
        _fail("ORCHESTRATION_AUDIT_INVALID", "effective mapping is not MappingVNext")
    if not isinstance(mapping_execution, MappingExecutionVNext):
        _fail("ORCHESTRATION_AUDIT_INVALID", "mapping execution is not MappingExecutionVNext")
    if not isinstance(metrics, MetricsVNext):
        _fail("ORCHESTRATION_AUDIT_INVALID", "metrics is not MetricsVNext")
    if rate_metrics is not None and not isinstance(rate_metrics, RateMetricsVNext):
        _fail("ORCHESTRATION_AUDIT_INVALID", "rate metrics is not RateMetricsVNext")
    try:
        mapping_source_set = mapping.rewrite_policy.symbol_graph.source_catalog.source_set
    except AttributeError as error:
        _fail("ORCHESTRATION_AUDIT_INVALID", f"mapping source identity is unavailable: {error}")
    if mapping_source_set is not source_set:
        _fail("ORCHESTRATION_AUDIT_INVALID", "MappingVNext does not retain SourceSet identity")
    if mapping_execution.rewrite_execution.mapping_vnext is not effective_mapping:
        _fail("ORCHESTRATION_AUDIT_INVALID", "effective mapping identity differs from T047 execution")
    if metrics.mapping_execution is not mapping_execution:
        _fail("ORCHESTRATION_AUDIT_INVALID", "MetricsVNext identity differs from T047 envelope")
    evidence = mapping_execution.rewrite_execution.compile_evidence
    if not _strict_compile_passed(evidence):
        _fail("ORCHESTRATION_EXECUTION_INVALID", "strict compile evidence is not clean")
    if rate_metrics is None:
        if effective_mapping is not mapping:
            _fail("ORCHESTRATION_AUDIT_INVALID", "no-rate effective mapping is not original mapping")
        return
    if rate_metrics.mapping_execution is not mapping_execution or rate_metrics.metrics is not metrics:
        _fail("ORCHESTRATION_AUDIT_INVALID", "T051 identity is not retained")
    if rate_metrics.rate_execution.rate_selection.mapping_vnext is not mapping:
        _fail("ORCHESTRATION_AUDIT_INVALID", "T049 selection does not retain original mapping")
    if rate_metrics.rate_execution.rewrite_execution.mapping_vnext is not effective_mapping:
        _fail("ORCHESTRATION_AUDIT_INVALID", "T050 selected mapping identity is not retained")


@dataclass(frozen=True)
class OrchestrationVNext:
    schema_version: int
    source_set: SourceSet = field(repr=False, compare=False)
    mapping_vnext: MappingVNext = field(repr=False, compare=False)
    effective_mapping_vnext: MappingVNext = field(repr=False, compare=False)
    mapping_execution: MappingExecutionVNext = field(repr=False, compare=False)
    metrics: MetricsVNext = field(repr=False, compare=False)
    rate_metrics: RateMetricsVNext | None = field(repr=False, compare=False)

    def to_report(self) -> dict[str, object]:
        _validate_source_set(self.source_set)
        if type(self.schema_version) is not int or self.schema_version != 1:
            _fail("ORCHESTRATION_AUDIT_INVALID", "orchestration schema is invalid")
        _validate_pipeline_identity(
            self.source_set,
            self.mapping_vnext,
            self.effective_mapping_vnext,
            self.mapping_execution,
            self.metrics,
            self.rate_metrics,
        )
        try:
            mapping_report = _portable_report(self.mapping_vnext.to_report())
            execution_report = _portable_report(self.mapping_execution.to_report())
            metrics_report = _portable_report(self.metrics.to_report())
            rate_report = (
                None
                if self.rate_metrics is None
                else _portable_report(self.rate_metrics.to_report())
            )
        except (RewriteVNextError, MetricsVNextError, RateMetricsVNextError) as error:
            _fail("ORCHESTRATION_AUDIT_INVALID", str(error).split(": ", 1)[-1])
        except Exception as error:
            _fail("ORCHESTRATION_AUDIT_INVALID", str(error))
        if not isinstance(mapping_report, dict) or not isinstance(execution_report, dict) or not isinstance(metrics_report, dict):
            _fail("ORCHESTRATION_AUDIT_INVALID", "nested report is not an object")
        if execution_report.get("state") != "restored" or metrics_report.get("state") != "verified":
            _fail("ORCHESTRATION_AUDIT_INVALID", "nested report state is not verified")
        if rate_report is not None and (not isinstance(rate_report, dict) or rate_report.get("state") != "restored"):
            _fail("ORCHESTRATION_AUDIT_INVALID", "rate metrics report state is not restored")
        report = {
            "format": "rtl-obfuscation.orchestration-vnext",
            "schema_version": self.schema_version,
            "state": "restored",
            "source_set": _source_set_report(self.source_set),
            "mapping": mapping_report,
            "mapping_execution": execution_report,
            "metrics": metrics_report,
            "rate_metrics": rate_report,
            "summary": {
                "origin": self.source_set.origin,
                "top": self.source_set.top,
                "rate_enabled": self.rate_metrics is not None,
                "files": len(self.mapping_execution.rewrite_execution.gate_manifest),
                "mapping_records": len(self.mapping_vnext.records),
                "effective_mapping_records": len(self.effective_mapping_vnext.records),
                "modified_tokens": len(self.mapping_execution.rewrite_execution.edits),
                "strict_compile_passed": _strict_compile_passed(
                    self.mapping_execution.rewrite_execution.compile_evidence
                ),
                "restored_byte_identical": execution_report["summary"]["restored_byte_identical"],
                "effective_line_total": self.metrics.effective_line_total,
                "affected_line_count": self.metrics.affected_line_count,
                "symbol_coverage": metrics_report["symbols"]["coverage"],
                "occurrence_coverage": metrics_report["occurrences"]["coverage"],
                "plaintext_leakage_rate": metrics_report["plaintext_leakage_rate"],
                "effective_coverage": metrics_report["effective_coverage"],
            },
        }
        if _contains_absolute_path(report):
            _fail("ORCHESTRATION_AUDIT_INVALID", "report contains an absolute path")
        return report


def _run_no_rate(
    mapping: MappingVNext,
    *,
    gate_dir: Path,
    restore_dir: Path,
) -> tuple[MappingVNext, MappingExecutionVNext, MetricsVNext, None]:
    try:
        execution = write_gate_vnext(mapping, output_dir=gate_dir)
        restore_result = restore_gate_vnext(
            execution,
            gate_dir=gate_dir,
            output_dir=restore_dir,
        )
    except RewriteVNextError as error:
        _fail("ORCHESTRATION_EXECUTION_INVALID", error.message)
    try:
        mapping_execution = build_mapping_execution_vnext(execution, restore_result)
        metrics = build_metrics_vnext(mapping_execution, gate_dir=gate_dir)
    except (RewriteVNextError, MetricsVNextError) as error:
        _fail("ORCHESTRATION_AUDIT_INVALID", str(error).split(": ", 1)[-1])
    return mapping, mapping_execution, metrics, None


def _run_rate(
    mapping: MappingVNext,
    *,
    encryption_rate: str,
    gate_dir: Path,
    restore_dir: Path,
) -> tuple[MappingVNext, MappingExecutionVNext, MetricsVNext, RateMetricsVNext]:
    try:
        selection = build_rate_selection_vnext(mapping, encryption_rate)
        rate_execution = write_rate_selected_gate_vnext(mapping, selection, gate_dir)
    except (RateVNextError, RateExecutionVNextError) as error:
        _fail("ORCHESTRATION_RATE_INVALID", error.message)
    try:
        rate_metrics = build_rate_metrics_vnext(
            rate_execution,
            gate_dir=gate_dir,
            restore_dir=restore_dir,
        )
    except RateMetricsVNextError as error:
        _fail("ORCHESTRATION_AUDIT_INVALID", error.message)
    effective_mapping = rate_execution.rewrite_execution.mapping_vnext
    return effective_mapping, rate_metrics.mapping_execution, rate_metrics.metrics, rate_metrics


def run_vnext(
    source_set: SourceSet,
    *,
    categories: Iterable[str],
    abi_categories: Iterable[str] = (),
    name_length: int = 20,
    name_factory: NameFactory = secure_name_factory,
    encryption_rate: str | None = None,
    gate_dir: Path,
    restore_dir: Path,
) -> OrchestrationVNext:
    """Build, execute, restore, and audit one vNext SourceSet pipeline."""

    source_set = _validate_source_set(source_set)
    gate_path, restore_path = _validate_outputs(source_set, gate_dir, restore_dir)
    created_paths: list[Path] = []
    try:
        mapping = _build_mapping(
            source_set,
            categories=categories,
            abi_categories=abi_categories,
            name_length=name_length,
            name_factory=name_factory,
        )
        if encryption_rate is None:
            effective_mapping, mapping_execution, metrics, rate_metrics = _run_no_rate(
                mapping,
                gate_dir=gate_path,
                restore_dir=restore_path,
            )
        elif isinstance(encryption_rate, str):
            effective_mapping, mapping_execution, metrics, rate_metrics = _run_rate(
                mapping,
                encryption_rate=encryption_rate,
                gate_dir=gate_path,
                restore_dir=restore_path,
            )
        else:
            _fail("ORCHESTRATION_RATE_INVALID", "encryption_rate must be string or None")
        created_paths.extend((gate_path, restore_path))
        _validate_pipeline_identity(
            source_set,
            mapping,
            effective_mapping,
            mapping_execution,
            metrics,
            rate_metrics,
        )
        result = OrchestrationVNext(
            schema_version=1,
            source_set=source_set,
            mapping_vnext=mapping,
            effective_mapping_vnext=effective_mapping,
            mapping_execution=mapping_execution,
            metrics=metrics,
            rate_metrics=rate_metrics,
        )
        result.to_report()
        return result
    except OrchestrationVNextError:
        created_paths.extend(
            path for path in (gate_path, restore_path) if path not in created_paths and path.exists()
        )
        _cleanup_created(created_paths)
        raise
    except Exception as error:
        created_paths.extend(
            path for path in (gate_path, restore_path) if path not in created_paths and path.exists()
        )
        _cleanup_created(created_paths)
        _fail("ORCHESTRATION_AUDIT_INVALID", str(error))
