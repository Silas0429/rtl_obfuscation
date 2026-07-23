"""MappingVNext-only greedy unique-line rate selection."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from decimal import Decimal, InvalidOperation, ROUND_CEILING
import hashlib
from pathlib import Path
from typing import Iterable

from .mapping_vnext import InputFileDigest, MappingRecord, MappingVNext
from .rewrite_policy import RewritePolicy
from .source_catalog import SourceCatalog, SourceRange
from .source_set import SourceSet
from .symbol_graph import SourceSymbol, SymbolGraph, SymbolOccurrence


_ALGORITHM = "greedy_unique_line_v1"


@dataclass(frozen=True)
class RateCandidateVNext:
    symbol_id: str
    category: str
    owner_module: str
    original_name: str
    declaration: SourceRange
    affected_lines: tuple[tuple[str, int], ...]
    selected: bool


@dataclass(frozen=True)
class RateSelectionVNext:
    schema_version: int
    mapping_vnext: MappingVNext = field(repr=False, compare=False)
    algorithm: str
    target: Decimal
    total_lines: int
    target_lines: int
    candidate_lines: int
    selected_lines: int
    actual_rate: float
    overshoot_lines: int
    maximum_rate: float
    target_unreachable: bool
    selection_mode: str
    candidates: tuple[RateCandidateVNext, ...]

    def to_report(self) -> dict[str, object]:
        context = _mapping_context(self.mapping_vnext)
        candidates, _candidate_lines = _build_candidates(context)
        total_lines = sum(
            _effective_line_count(context.source_data[file]) for file in context.files
        )
        expected = _validate_selection(self, context, candidates, total_lines)
        return {
            "format": "rtl-obfuscation.rate-selection-vnext",
            "schema_version": self.schema_version,
            "state": "planned",
            "mapping_format": "rtl-obfuscation.mapping-vnext",
            "algorithm": self.algorithm,
            "target": float(self.target),
            "total_lines": self.total_lines,
            "target_lines": self.target_lines,
            "candidate_lines": self.candidate_lines,
            "selected_lines": self.selected_lines,
            "actual_rate": self.actual_rate,
            "overshoot_lines": self.overshoot_lines,
            "maximum_rate": self.maximum_rate,
            "target_unreachable": self.target_unreachable,
            "selection_mode": self.selection_mode,
            "candidate_entries": len(self.candidates),
            "selected_entries": sum(candidate.selected for candidate in self.candidates),
            "candidates": [_candidate_report(candidate) for candidate in expected],
        }


class RateVNextError(ValueError):
    """Stable fail-closed error for rate selection vNext."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class _MappingContext:
    mapping: MappingVNext
    source_set: SourceSet
    files: tuple[str, ...]
    source_data: dict[str, bytes]


def _fail(code: str, message: str) -> None:
    raise RateVNextError(code, message)


def _is_schema_one(value: object) -> bool:
    return type(value) is int and value == 1


def _portable_file(value: object) -> bool:
    if not isinstance(value, str) or not value or value.startswith("/") or "\\" in value:
        return False
    return all(part not in {"", ".", ".."} for part in value.split("/"))


def _valid_sha256(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    return all(char in "0123456789abcdef" for char in value)


def _mapping_context(mapping: object) -> _MappingContext:
    if not isinstance(mapping, MappingVNext):
        _fail("RATE_MAPPING_INVALID", "input is not MappingVNext")
    if mapping.format != "rtl-obfuscation.mapping-vnext" or not _is_schema_one(mapping.schema_version):
        _fail("RATE_MAPPING_INVALID", "mapping format or schema is invalid")
    policy = mapping.rewrite_policy
    if not isinstance(policy, RewritePolicy):
        _fail("RATE_MAPPING_INVALID", "mapping policy is invalid")
    graph = policy.symbol_graph
    if not isinstance(graph, SymbolGraph) or not _is_schema_one(graph.schema_version):
        _fail("RATE_MAPPING_INVALID", "mapping graph is invalid")
    catalog = graph.source_catalog
    if not isinstance(catalog, SourceCatalog) or not _is_schema_one(catalog.schema_version):
        _fail("RATE_MAPPING_INVALID", "mapping catalog is invalid")
    source_set = catalog.source_set
    if not isinstance(source_set, SourceSet) or not _is_schema_one(source_set.schema_version):
        _fail("RATE_MAPPING_INVALID", "mapping SourceSet is invalid")
    if not isinstance(source_set.ordered_source_files, tuple) or not isinstance(source_set.included_files, tuple):
        _fail("RATE_MAPPING_INVALID", "physical file sequence is not canonical")
    files: list[str] = []
    for file in (*source_set.ordered_source_files, *source_set.included_files):
        if not _portable_file(file):
            _fail("RATE_MAPPING_INVALID", "physical file path is not portable")
        if file not in files:
            files.append(file)
    if not files:
        _fail("RATE_MAPPING_INVALID", "mapping has no physical files")
    try:
        source_root = Path(source_set.source_root).expanduser().resolve()
    except (OSError, RuntimeError, TypeError) as error:
        _fail("RATE_MAPPING_INVALID", f"source_root is invalid: {error}")
    if not source_root.is_dir():
        _fail("RATE_MAPPING_INVALID", "source_root is not a directory")

    if not isinstance(mapping.input_manifest, tuple) or len(mapping.input_manifest) != len(files):
        _fail("RATE_MAPPING_INVALID", "input manifest shape is invalid")
    source_data: dict[str, bytes] = {}
    for item, file in zip(mapping.input_manifest, files):
        if (
            not isinstance(item, InputFileDigest)
            or item.file != file
            or not _valid_sha256(item.sha256)
        ):
            _fail("RATE_MAPPING_INVALID", "input manifest order, file, or hash is invalid")
        path = (source_root / file).resolve()
        try:
            path.relative_to(source_root)
            content = path.read_bytes()
        except (OSError, ValueError) as error:
            _fail("RATE_MAPPING_INVALID", f"source file is unavailable: {file}: {error}")
        if hashlib.sha256(content).hexdigest() != item.sha256:
            _fail("RATE_MAPPING_INVALID", f"source manifest hash differs: {file}")
        source_data[file] = content

    _validate_records(mapping, graph, policy, tuple(files), source_data)
    return _MappingContext(mapping, source_set, tuple(files), source_data)


def _validate_records(
    mapping: MappingVNext,
    graph: SymbolGraph,
    policy: RewritePolicy,
    files: tuple[str, ...],
    source_data: dict[str, bytes],
) -> None:
    if not isinstance(mapping.records, tuple) or not isinstance(graph.symbols, tuple) or not isinstance(policy.decisions, tuple):
        _fail("RATE_MAPPING_INVALID", "mapping records, symbols, or decisions are not canonical")
    if len(mapping.records) != len(graph.symbols) or len(mapping.records) != len(policy.decisions):
        _fail("RATE_MAPPING_INVALID", "mapping records are not one-to-one")
    for record, symbol, decision in zip(mapping.records, graph.symbols, policy.decisions):
        if not isinstance(record, MappingRecord) or not isinstance(symbol, SourceSymbol):
            _fail("RATE_MAPPING_INVALID", "mapping record or symbol is invalid")
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
        if any(actual_value != expected_value for actual_value, expected_value in expected_fields):
            _fail("RATE_MAPPING_INVALID", "mapping record identity differs from established graph/policy")
        if record.action not in {"rename", "preserve", "unsupported"}:
            _fail("RATE_MAPPING_INVALID", "mapping record action is invalid")
        if record.action == "rename":
            if not isinstance(record.renamed_name, str) or not record.renamed_name:
                _fail("RATE_MAPPING_INVALID", "rename record name is invalid")
        elif record.renamed_name is not None:
            _fail("RATE_MAPPING_INVALID", "non-rename record has a renamed name")
        if not isinstance(record.occurrences, tuple):
            _fail("RATE_MAPPING_INVALID", "mapping occurrences are not canonical")
        for occurrence in record.occurrences:
            if not isinstance(occurrence, SymbolOccurrence) or not isinstance(occurrence.provenance, str) or not occurrence.provenance:
                _fail("RATE_MAPPING_INVALID", "mapping occurrence is invalid")
        ranges = [(record.declaration, record.original_name)]
        ranges.extend((occurrence.source_range, record.original_name) for occurrence in record.occurrences)
        for source_range, original_name in ranges:
            if not isinstance(source_range, SourceRange) or source_range.file not in files:
                _fail("RATE_MAPPING_INVALID", "mapping range is not physical")
            if type(source_range.start) is not int or type(source_range.end) is not int:
                _fail("RATE_MAPPING_INVALID", "mapping range bounds are invalid")
            content = source_data[source_range.file]
            if not 0 <= source_range.start < source_range.end <= len(content):
                _fail("RATE_MAPPING_INVALID", "mapping range is outside source bytes")
            if content[source_range.start : source_range.end] != original_name.encode("utf-8"):
                _fail("RATE_MAPPING_INVALID", "mapping range bytes do not match original name")


def _line_spans(content: bytes) -> tuple[tuple[int, int], ...]:
    spans: list[tuple[int, int]] = []
    offset = 0
    for line in content.splitlines(keepends=True):
        end = offset + len(line)
        spans.append((offset, end))
        offset = end
    return tuple(spans)


def _effective_line_count(content: bytes) -> int:
    return sum(
        line.strip() != b"" and not line.strip().startswith(b"//")
        for line in content.splitlines()
    )


def _range_lines(source_range: SourceRange, content: bytes) -> set[int]:
    if not 0 <= source_range.start < source_range.end <= len(content):
        _fail("RATE_CANDIDATE_INVALID", "candidate range is outside source bytes")
    lines = {
        line_number
        for line_number, (start, end) in enumerate(_line_spans(content), start=1)
        if source_range.start < end and source_range.end > start
    }
    if not lines:
        _fail("RATE_CANDIDATE_INVALID", "candidate range cannot map to a physical line")
    return lines


def _candidate_key(candidate: RateCandidateVNext) -> tuple[object, ...]:
    declaration = candidate.declaration
    return (
        declaration.file,
        declaration.start,
        candidate.category,
        candidate.owner_module,
        candidate.original_name,
        candidate.symbol_id,
    )


def _build_candidates(context: _MappingContext) -> tuple[tuple[RateCandidateVNext, ...], int]:
    candidates: list[RateCandidateVNext] = []
    candidate_ranges: list[tuple[str, int, int]] = []
    for record in context.mapping.records:
        if record.action != "rename":
            continue
        ranges = [record.declaration, *(occurrence.source_range for occurrence in record.occurrences)]
        affected: set[tuple[str, int]] = set()
        for source_range in ranges:
            affected.update(
                (source_range.file, line)
                for line in _range_lines(source_range, context.source_data[source_range.file])
            )
            candidate_ranges.append((source_range.file, source_range.start, source_range.end))
        candidates.append(
            RateCandidateVNext(
                symbol_id=record.symbol_id,
                category=record.category,
                owner_module=record.owner_module,
                original_name=record.original_name,
                declaration=record.declaration,
                affected_lines=tuple(sorted(affected)),
                selected=False,
            )
        )
    ordered_ranges = sorted(candidate_ranges)
    for previous, current in zip(ordered_ranges, ordered_ranges[1:]):
        if previous[0] == current[0] and previous[2] > current[1]:
            _fail("RATE_CANDIDATE_INVALID", "candidate ranges overlap")
    ordered = tuple(sorted(candidates, key=_candidate_key))
    candidate_lines = len({line for candidate in ordered for line in candidate.affected_lines})
    return ordered, candidate_lines


def _parse_rate(value: str) -> Decimal:
    if not isinstance(value, str):
        _fail("RATE_SELECTION_INVALID", "rate must be a string")
    try:
        rate = Decimal(value)
    except (InvalidOperation, ValueError):
        _fail("RATE_SELECTION_INVALID", "rate is not a Decimal")
    if not rate.is_finite() or rate <= 0 or rate > 1:
        _fail("RATE_SELECTION_INVALID", "rate must be finite and satisfy 0 < rate <= 1")
    return rate


def _ceil_target(rate: Decimal, total_lines: int) -> int:
    try:
        return int((rate * Decimal(total_lines)).to_integral_value(rounding=ROUND_CEILING))
    except (InvalidOperation, ValueError, OverflowError):
        _fail("RATE_SELECTION_INVALID", "target line calculation failed")


def _candidate_union(candidates: Iterable[RateCandidateVNext]) -> set[tuple[str, int]]:
    return {line for candidate in candidates for line in candidate.affected_lines}


def _greedy_select(
    candidates: tuple[RateCandidateVNext, ...],
    target_lines: int,
    total_lines: int,
) -> tuple[set[int], bool, str]:
    candidate_lines_set = _candidate_union(candidates)
    target_unreachable = total_lines == 0 or not candidate_lines_set or target_lines > len(candidate_lines_set)
    if target_unreachable:
        return set(range(len(candidates))), True, "all_candidates"

    selected_indexes: set[int] = set()
    covered: set[tuple[str, int]] = set()
    while len(covered) < target_lines:
        remaining = target_lines - len(covered)
        choices = [
            (index, len(set(candidate.affected_lines) - covered), _candidate_key(candidate))
            for index, candidate in enumerate(candidates)
            if index not in selected_indexes
        ]
        if not choices:
            _fail("RATE_SELECTION_FAILED", "greedy candidate selection exhausted before target")
        reaching = [choice for choice in choices if choice[1] >= remaining]
        if reaching:
            index, _marginal, _key = min(reaching, key=lambda choice: (choice[1], choice[2]))
        else:
            index, _marginal, _key = min(choices, key=lambda choice: (-choice[1], choice[2]))
        selected_indexes.add(index)
        covered.update(candidates[index].affected_lines)

    for index in sorted(selected_indexes, key=lambda item: _candidate_key(candidates[item]), reverse=True):
        trial_indexes = selected_indexes - {index}
        trial_lines = _candidate_union(candidates[item] for item in trial_indexes)
        if len(trial_lines) >= target_lines:
            selected_indexes = trial_indexes
    return selected_indexes, False, "greedy"


def greedy_unique_line_v1(
    candidates: tuple[RateCandidateVNext, ...],
    target_lines: int,
    total_lines: int,
) -> tuple[RateCandidateVNext, ...]:
    """Select complete candidates using deterministic unique-line greedy selection."""

    if not isinstance(candidates, tuple) or type(target_lines) is not int or type(total_lines) is not int:
        _fail("RATE_SELECTION_INVALID", "greedy inputs are invalid")
    selected_indexes, _unreachable, _mode = _greedy_select(candidates, target_lines, total_lines)
    return tuple(
        replace(candidate, selected=index in selected_indexes)
        for index, candidate in enumerate(candidates)
    )


def _candidate_report(candidate: RateCandidateVNext) -> dict[str, object]:
    return {
        "symbol_id": candidate.symbol_id,
        "category": candidate.category,
        "owner_module": candidate.owner_module,
        "original_name": candidate.original_name,
        "declaration": {
            "file": candidate.declaration.file,
            "start": candidate.declaration.start,
            "end": candidate.declaration.end,
        },
        "affected_lines": [
            {"file": file, "line": line}
            for file, line in candidate.affected_lines
        ],
        "affected_line_count": len(candidate.affected_lines),
        "selected": candidate.selected,
    }


def _validate_selection(
    selection: RateSelectionVNext,
    context: _MappingContext,
    expected_candidates: tuple[RateCandidateVNext, ...],
    total_lines: int,
) -> tuple[RateCandidateVNext, ...]:
    if not isinstance(selection, RateSelectionVNext) or not _is_schema_one(selection.schema_version):
        _fail("RATE_MAPPING_INVALID", "selection schema is invalid")
    if selection.mapping_vnext is not context.mapping:
        _fail("RATE_MAPPING_INVALID", "selection mapping identity differs")
    if selection.algorithm != _ALGORITHM:
        _fail("RATE_SELECTION_FAILED", "selection algorithm is not canonical")
    if not isinstance(selection.target, Decimal):
        _fail("RATE_SELECTION_INVALID", "selection target is not a Decimal")
    rate = _parse_rate(str(selection.target))
    target_lines = _ceil_target(rate, total_lines)
    if selection.total_lines != total_lines or selection.target_lines != target_lines:
        _fail("RATE_SELECTION_FAILED", "selection target equation differs")
    if not isinstance(selection.candidates, tuple) or len(selection.candidates) != len(expected_candidates):
        _fail("RATE_CANDIDATE_INVALID", "candidate sequence differs from mapping")
    for actual, expected in zip(selection.candidates, expected_candidates):
        if not isinstance(actual, RateCandidateVNext):
            _fail("RATE_CANDIDATE_INVALID", "candidate is not RateCandidateVNext")
        if replace(actual, selected=False) != replace(expected, selected=False):
            _fail("RATE_CANDIDATE_INVALID", "candidate identity differs from mapping/source bytes")
    candidate_lines = len(_candidate_union(expected_candidates))
    selected_candidates = tuple(selection.candidates[index] for index in range(len(selection.candidates)) if selection.candidates[index].selected)
    selected_lines = len(_candidate_union(selected_candidates))
    target_unreachable = total_lines == 0 or candidate_lines == 0 or target_lines > candidate_lines
    selection_mode = "all_candidates" if target_unreachable else "greedy"
    if target_unreachable and not all(candidate.selected for candidate in selection.candidates):
        _fail("RATE_SELECTION_FAILED", "unreachable target does not select all candidates")
    if not target_unreachable and selected_lines < target_lines:
        _fail("RATE_SELECTION_FAILED", "reachable target is not met")
    if (
        selection.candidate_lines != candidate_lines
        or selection.selected_lines != selected_lines
        or selection.target_unreachable != target_unreachable
        or selection.selection_mode != selection_mode
        or selection.overshoot_lines != max(0, selected_lines - target_lines)
        or selection.maximum_rate != _rate(candidate_lines, total_lines)
        or selection.actual_rate != _rate(selected_lines, total_lines)
    ):
        _fail("RATE_SELECTION_FAILED", "selection report equations differ")
    if selection.target_unreachable and selected_lines != candidate_lines:
        _fail("RATE_SELECTION_FAILED", "unreachable report does not select maximum candidate lines")
    return tuple(selection.candidates)


def _rate(numerator: int, denominator: int) -> float:
    return 0.0 if denominator == 0 else numerator / denominator


def build_rate_selection_vnext(mapping_vnext: MappingVNext, rate: str) -> RateSelectionVNext:
    """Build one deterministic rate-selection plan from an established MappingVNext."""

    target = _parse_rate(rate)
    context = _mapping_context(mapping_vnext)
    candidates, candidate_lines = _build_candidates(context)
    total_lines = sum(_effective_line_count(context.source_data[file]) for file in context.files)
    target_lines = _ceil_target(target, total_lines)
    selected_flags, target_unreachable, selection_mode = _greedy_select(
        candidates,
        target_lines,
        total_lines,
    )
    selected_candidates = tuple(
        replace(candidate, selected=index in selected_flags)
        for index, candidate in enumerate(candidates)
    )
    selected_lines = len(_candidate_union(selected_candidates[index] for index in selected_flags))
    selection = RateSelectionVNext(
        schema_version=1,
        mapping_vnext=mapping_vnext,
        algorithm=_ALGORITHM,
        target=target,
        total_lines=total_lines,
        target_lines=target_lines,
        candidate_lines=candidate_lines,
        selected_lines=selected_lines,
        actual_rate=_rate(selected_lines, total_lines),
        overshoot_lines=max(0, selected_lines - target_lines),
        maximum_rate=_rate(candidate_lines, total_lines),
        target_unreachable=target_unreachable,
        selection_mode=selection_mode,
        candidates=selected_candidates,
    )
    _validate_selection(selection, context, candidates, total_lines)
    return selection
