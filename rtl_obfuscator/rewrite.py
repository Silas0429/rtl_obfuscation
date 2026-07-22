"""Rewrite and restore selected SystemVerilog identifiers."""

from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation, ROUND_CEILING
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile
from typing import Any

import pyslang

from rtl_obfuscator import category_profile, formal_view, inventory, project


_PROJECT_ROOT_GROUPS = tuple(
    (category, (category,))
    for category in category_profile.CANONICAL_CATEGORIES
)
_PROJECT_ROOT_GROUPS = _PROJECT_ROOT_GROUPS + tuple(
    (alias, categories) for alias, categories in category_profile.ALIASES.items()
)
_PROJECT_ROOT_GROUP_NAMES = tuple(group for group, _ in _PROJECT_ROOT_GROUPS)
_PROJECT_ROOT_PARAMETER_GROUP = ("parameters", ("parameters",))
_PROJECT_ROOT_SELECTION_GROUPS = _PROJECT_ROOT_GROUPS + (
    _PROJECT_ROOT_PARAMETER_GROUP,
)
_PROJECT_ROOT_SELECTION_GROUP_NAMES = tuple(
    group for group, _ in _PROJECT_ROOT_SELECTION_GROUPS
)
_PROJECT_ROOT_DEFAULT_GROUP_NAMES = tuple(category_profile.DEFAULT_CATEGORIES)
_PROJECT_ROOT_CATEGORIES = tuple(
    category
    for _, categories in _PROJECT_ROOT_SELECTION_GROUPS
    for category in categories
)


def _write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _write_json(path: Path, content: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        json.dump(content, stream, indent=2)
        stream.write("\n")


def _entry_ranges(entry: dict[str, Any]) -> list[dict[str, Any]]:
    return [entry["declaration"], *entry["references"]]


_ENCRYPTION_RATE_ALGORITHM = "greedy_unique_line_v1"


def _parse_encryption_rate(value: str) -> Decimal:
    try:
        rate = Decimal(value)
    except (InvalidOperation, ValueError):
        raise ValueError("ENCRYPTION_RATE_INVALID") from None
    if not rate.is_finite() or rate <= 0 or rate > 1:
        raise ValueError("ENCRYPTION_RATE_INVALID")
    return rate


def _effective_line_count(source: bytes) -> int:
    return sum(
        1
        for line in source.decode("utf-8").splitlines()
        if line.strip() and not line.strip().startswith("//")
    )


def _rate_entry_key(entry: dict[str, Any]) -> tuple[Any, ...]:
    declaration = entry["declaration"]
    if not isinstance(declaration, dict):
        raise ValueError("ENCRYPTION_RATE_INVALID_CANDIDATE")
    return (
        declaration["file"],
        declaration["start"],
        entry["category"],
        entry["scope"],
        entry["original_name"],
    )


def _rate_source_for_record(
    record: dict[str, Any],
    source_files: dict[str, bytes],
    fallback_source: bytes | None,
) -> bytes:
    source = source_files.get(record["file"])
    if source is not None:
        return source
    if fallback_source is not None:
        return fallback_source
    raise ValueError("ENCRYPTION_RATE_INVALID_CANDIDATE")


def _rate_selection(
    entries: list[dict[str, Any]],
    *,
    source_files: dict[str, bytes],
    total_sources: list[bytes],
    rate_value: str,
    fallback_source: bytes | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rate = _parse_encryption_rate(rate_value)
    total_lines = sum(_effective_line_count(source) for source in total_sources)
    ordered_entries = sorted(entries, key=_rate_entry_key)
    candidates: list[tuple[dict[str, Any], frozenset[tuple[str, int]]]] = []
    for entry in ordered_entries:
        affected_lines = frozenset(
            (
                record["file"],
                _rate_source_for_record(record, source_files, fallback_source)[
                    : record["start"]
                ].count(b"\n")
                + 1,
            )
            for record in _entry_ranges(entry)
        )
        candidates.append((entry, affected_lines))

    candidate_lines_set = frozenset(
        line for _, affected_lines in candidates for line in affected_lines
    )
    candidate_lines = len(candidate_lines_set)
    target_lines = int(
        (rate * Decimal(total_lines)).to_integral_value(rounding=ROUND_CEILING)
    )
    selected_indexes: set[int] = set()
    target_unreachable = total_lines == 0 or not candidate_lines_set or target_lines > candidate_lines
    if target_unreachable:
        selected_indexes = set(range(len(candidates)))
        selection_mode = "all_candidates"
    else:
        covered: set[tuple[str, int]] = set()
        while len(covered) < target_lines:
            remaining = target_lines - len(covered)
            choices = [
                (
                    index,
                    len(affected_lines - covered),
                    _rate_entry_key(entry),
                )
                for index, (entry, affected_lines) in enumerate(candidates)
                if index not in selected_indexes
            ]
            if not choices:
                raise ValueError("ENCRYPTION_RATE_SELECTION_FAILED")
            reaching = [choice for choice in choices if choice[1] >= remaining]
            if reaching:
                index, _, _ = min(reaching, key=lambda choice: (choice[1], choice[2]))
            else:
                index, _, _ = min(choices, key=lambda choice: (-choice[1], choice[2]))
            selected_indexes.add(index)
            covered.update(candidates[index][1])

        for index in sorted(selected_indexes, key=lambda item: _rate_entry_key(candidates[item][0]), reverse=True):
            trial_indexes = selected_indexes - {index}
            trial_lines = {
                line
                for trial_index in trial_indexes
                for line in candidates[trial_index][1]
            }
            if len(trial_lines) >= target_lines:
                selected_indexes = trial_indexes
        selection_mode = "greedy"

    selected_lines_set = {
        line
        for index in selected_indexes
        for line in candidates[index][1]
    }
    selected_lines = len(selected_lines_set)
    actual_rate = selected_lines / total_lines if total_lines else 0.0
    maximum_rate = candidate_lines / total_lines if total_lines else 0.0
    target_number = float(rate)
    rate_info = {
        "algorithm": _ENCRYPTION_RATE_ALGORITHM,
        "target": target_number,
        "total_lines": total_lines,
        "target_lines": target_lines,
        "candidate_lines": candidate_lines,
        "selected_lines": selected_lines,
        "actual_rate": actual_rate,
        "overshoot_lines": max(0, selected_lines - target_lines),
        "maximum_rate": maximum_rate,
        "target_unreachable": target_unreachable,
        "selection_mode": selection_mode,
        "candidate_entries": len(candidates),
        "selected_entries": len(selected_indexes),
        "candidates": [
            {
                "category": entry["category"],
                "scope": entry["scope"],
                "original_name": entry["original_name"],
                "declaration": entry["declaration"],
                "affected_lines": [
                    {"file": file, "line": line}
                    for file, line in sorted(affected_lines)
                ],
                "affected_line_count": len(affected_lines),
                "selected": index in selected_indexes,
            }
            for index, (entry, affected_lines) in enumerate(candidates)
        ],
    }
    return (
        [entry for index, (entry, _) in enumerate(candidates) if index in selected_indexes],
        rate_info,
    )


def _rate_stdout_summary(rate_info: dict[str, Any]) -> dict[str, Any]:
    return {
        "target": rate_info["target"],
        "total_lines": rate_info["total_lines"],
        "encrypted_lines": rate_info["selected_lines"],
        "actual_rate": rate_info["actual_rate"],
        "overshoot_lines": rate_info["overshoot_lines"],
        "maximum_rate": rate_info["maximum_rate"],
        "target_unreachable": rate_info["target_unreachable"],
    }


def _rate_select_project_entries(
    entries: list[dict[str, Any]],
    *,
    source_root: Path,
    files: list[str],
    rate_value: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    source_files = {
        relative_file: (source_root / relative_file).read_bytes()
        for relative_file in files
    }
    return _rate_selection(
        entries,
        source_files=source_files,
        total_sources=list(source_files.values()),
        rate_value=rate_value,
    )


def _apply_edits(
    source: bytes,
    edits: list[tuple[dict[str, Any], str, str]],
) -> bytes:
    ordered_edits = sorted(edits, key=lambda edit: (edit[0]["start"], edit[0]["end"]))
    positions = [
        (record["start"], record["end"])
        for record, _, _ in ordered_edits
    ]

    if len(positions) != len(set(positions)):
        raise ValueError("duplicate source edits")
    if any(
        current_start < previous_end
        for (_, previous_end), (current_start, _) in zip(
            positions, positions[1:]
        )
    ):
        raise ValueError("overlapping source edits")
    for record, expected, _ in ordered_edits:
        start = record["start"]
        end = record["end"]
        expected_bytes = expected.encode("utf-8")
        if source[start:end] != expected_bytes:
            raise ValueError("source edit does not match the expected identifier")

    rewritten = source
    for record, _, replacement in reversed(ordered_edits):
        start = record["start"]
        end = record["end"]
        replacement_bytes = replacement.encode("utf-8")
        rewritten = rewritten[:start] + replacement_bytes + rewritten[end:]
    return rewritten


def _metrics(
    source: bytes,
    gate: bytes,
    entries: list[dict[str, Any]],
    encryption_rate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ranges = [item for entry in entries for item in _entry_ranges(entry)]
    changed_lines = {
        source[: item["start"]].count(b"\n") + 1 for item in ranges
    }
    effective_lines = [
        line
        for line in source.decode("utf-8").splitlines()
        if line.strip() and not line.strip().startswith("//")
    ]
    symbol_count = len(entries)
    occurrence_count = len(ranges)
    leaked_occurrences = sum(
        gate.count(entry["original_name"].encode("utf-8")) for entry in entries
    )
    symbol_coverage = symbol_count / symbol_count if symbol_count else 0.0
    occurrence_coverage = (
        occurrence_count / occurrence_count if occurrence_count else 0.0
    )

    metrics = {
        "affected_lines": {
            "changed": len(changed_lines),
            "total": len(effective_lines),
            "rate": len(changed_lines) / len(effective_lines)
            if effective_lines
            else 0.0,
        },
        "symbols": {
            "renamed": symbol_count,
            "eligible": symbol_count,
            "coverage": symbol_coverage,
        },
        "occurrences": {
            "renamed": occurrence_count,
            "eligible": occurrence_count,
            "coverage": occurrence_coverage,
        },
        "plaintext_leakage_rate": (
            leaked_occurrences / occurrence_count if occurrence_count else 0.0
        ),
        "effective_coverage": (symbol_coverage * occurrence_coverage) ** 0.5,
    }
    if encryption_rate is not None:
        metrics["encryption_rate"] = encryption_rate
    return metrics


def _summary(
    mapping_entries: int,
    modified_tokens: int,
    encryption_rate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "files": 1,
        "mapping_entries": mapping_entries,
        "modified_tokens": modified_tokens,
    }
    if encryption_rate is not None:
        summary["encryption_rate"] = _rate_stdout_summary(encryption_rate)
    return summary


def _encrypt(args: argparse.Namespace) -> dict[str, Any]:
    mapping = inventory._build_inventory(
        args.input_file,
        args.name_length,
        args.category,
        include_ranges=True,
    )
    entries = mapping["entries"]
    source = args.input_file.read_bytes()
    rate_info: dict[str, Any] | None = None
    rate_value = getattr(args, "encryption_rate", None)
    if rate_value is not None:
        entries, rate_info = _rate_selection(
            entries,
            source_files={},
            total_sources=[source],
            fallback_source=source,
            rate_value=rate_value,
        )
        mapping = dict(mapping)
        mapping["entries"] = entries
    edits: list[tuple[dict[str, Any], str, str]] = []
    for entry in entries:
        edits.extend(
            (record, entry["original_name"], entry["renamed_name"])
            for record in _entry_ranges(entry)
        )
    gate = _apply_edits(source, edits)
    modified_tokens = len(edits)

    metrics = _metrics(source, gate, entries, rate_info)
    if rate_info is None:
        _write_bytes(args.output_file, gate)
        _write_json(args.map_file, mapping)
        _write_json(args.metrics_file, metrics)
    else:
        with tempfile.TemporaryDirectory(prefix="rtl-obfuscation-t036-") as temporary:
            staging = Path(temporary)
            staging_gate = staging / "gate.sv"
            staging_mapping = staging / "mapping.json"
            staging_metrics = staging / "metrics.json"
            _write_bytes(staging_gate, gate)
            project._write_json_atomic(staging_mapping, mapping)
            project._write_json_atomic(staging_metrics, metrics)
            _publish_project_root_artifacts(
                [
                    (staging_gate, args.output_file),
                    (staging_mapping, args.map_file),
                    (staging_metrics, args.metrics_file),
                ]
            )
    return _summary(len(entries), modified_tokens, rate_info)


def _debug_encrypt(args: argparse.Namespace) -> dict[str, Any]:
    runs: list[dict[str, Any]] = []
    for category in inventory._ALL_CATEGORIES:
        category_root = args.debug_dir / category
        summary = _encrypt(
            argparse.Namespace(
                input_file=args.input_file,
                output_file=category_root / "gate.sv",
                map_file=category_root / "mapping.json",
                metrics_file=category_root / "metrics.json",
                category=category,
                name_length=args.name_length,
            )
        )
        runs.append({"category": category, **summary})
    return {
        "debug": True,
        "mode": "single-file",
        "category_count": len(runs),
        "runs": runs,
    }


def _validate_mapping(mapping: Any) -> list[dict[str, Any]]:
    if not isinstance(mapping, dict) or set(mapping) != {
        "version",
        "name_length",
        "entries",
    }:
        raise ValueError("invalid mapping schema")
    if (
        not isinstance(mapping["version"], int)
        or isinstance(mapping["version"], bool)
        or mapping["version"] != 1
        or not isinstance(mapping["name_length"], int)
        or isinstance(mapping["name_length"], bool)
        or mapping["name_length"] < 4
    ):
        raise ValueError("unsupported mapping version or name length")
    entries = mapping["entries"]
    if not isinstance(entries, list):
        raise ValueError("mapping entries must be a list")

    required_entry_fields = {
        "category",
        "scope",
        "original_name",
        "renamed_name",
        "declaration",
        "references",
    }
    renamed_names: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != required_entry_fields:
            raise ValueError("invalid mapping entry schema")
        if entry["category"] not in (
            "signals",
            "parameters",
            "enum_values",
            "genvars",
            "functions",
            "tasks",
            "arguments",
            "instances",
            "generate_blocks",
            "typedefs",
            "struct_types",
            "struct_fields",
            "union_fields",
        ):
            raise ValueError("unsupported mapping category")
        if not all(
            isinstance(entry[field], str)
            for field in ("scope", "original_name", "renamed_name")
        ):
            raise ValueError("invalid mapping identifier")

        renamed_name = entry["renamed_name"]
        if (
            not renamed_name
            or len(renamed_name) != mapping["name_length"]
            or not renamed_name[0].isalpha()
            or not all(
                character.isascii()
                and (character.isalpha() or character.isdigit() or character == "_")
                for character in renamed_name[1:]
            )
            or not renamed_name[0].isascii()
            or renamed_name in inventory._SYSTEMVERILOG_KEYWORDS
        ):
            raise ValueError("invalid renamed identifier")
        if renamed_name in renamed_names:
            raise ValueError("duplicate renamed identifier")
        renamed_names.add(renamed_name)

        if not isinstance(entry["declaration"], dict):
            raise ValueError("invalid mapping declaration")
        if not isinstance(entry["references"], list):
            raise ValueError("mapping references must be a list")
        range_records = _entry_ranges(entry)
        for record in range_records:
            if not isinstance(record, dict) or set(record) != {"file", "start", "end"}:
                raise ValueError("invalid mapping range schema")
            if (
                not isinstance(record["file"], str)
                or not isinstance(record["start"], int)
                or isinstance(record["start"], bool)
                or not isinstance(record["end"], int)
                or isinstance(record["end"], bool)
                or record["start"] < 0
                or record["start"] >= record["end"]
            ):
                raise ValueError("invalid mapping range")
    return entries


def _gate_ranges(
    input_file: Path, entries: list[dict[str, Any]]
) -> list[list[dict[str, Any]]]:
    syntax_tree = pyslang.syntax.SyntaxTree.fromFile(str(input_file))
    compilation = pyslang.ast.Compilation()
    compilation.addSyntaxTree(syntax_tree)
    if any(diagnostic.isError() for diagnostic in compilation.getAllDiagnostics()):
        raise ValueError("gate contains SystemVerilog errors")

    targets_by_category: dict[str, list[Any]] = {}
    matches = []
    for entry in entries:
        targets = targets_by_category.get(entry["category"])
        if targets is None:
            targets, _ = inventory._collect_targets(compilation, entry["category"])
            targets_by_category[entry["category"]] = targets
        entry_matches = [
            target
            for target in targets
            if target.name == entry["renamed_name"]
            and target.declaringDefinition.name == entry["scope"]
        ]
        if len(entry_matches) != 1:
            raise ValueError("mapped target was not found uniquely in gate RTL")
        matches.append(entry_matches[0])

    range_entries: list[dict[str, Any]] = [{} for _ in entries]
    inventory._add_ranges(
        range_entries,
        matches,
        [entry["category"] for entry in entries],
        compilation,
        input_file,
    )
    all_ranges = [_entry_ranges(range_entry) for range_entry in range_entries]
    for entry, ranges in zip(entries, all_ranges, strict=True):
        if len(ranges) != len(_entry_ranges(entry)):
            raise ValueError("gate occurrence count does not match mapping")
    return all_ranges


def _decrypt(args: argparse.Namespace) -> dict[str, int]:
    with args.map_file.open(encoding="utf-8") as stream:
        mapping = json.load(stream)
    entries = _validate_mapping(mapping)
    gate = args.input_file.read_bytes()
    all_ranges = _gate_ranges(args.input_file, entries)
    edits = [
        (record, entry["renamed_name"], entry["original_name"])
        for entry, ranges in zip(entries, all_ranges, strict=True)
        for record in ranges
    ]
    restored = _apply_edits(gate, edits)
    modified_tokens = len(edits)

    _write_bytes(args.output_file, restored)
    return _summary(len(entries), modified_tokens)




def _project_metrics(
    source_root: Path,
    output_dir: Path,
    relative_files: list[str],
    entries: list[dict[str, Any]],
    encryption_rate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    all_ranges = [item for entry in entries for item in _entry_ranges(entry)]
    changed_lines: set[tuple[str, int]] = set()
    total_effective_lines = 0
    total_changed = 0

    for rel_file in relative_files:
        source = (source_root / rel_file).read_bytes()
        gate = (output_dir / rel_file).read_bytes()
        file_ranges = [
            item for item in all_ranges if item["file"] == rel_file
        ]
        file_changed = {
            source[: item["start"]].count(b"\n") + 1 for item in file_ranges
        }
        effective_lines = [
            line
            for line in source.decode("utf-8").splitlines()
            if line.strip() and not line.strip().startswith("//")
        ]
        total_effective_lines += len(effective_lines)
        total_changed += len(file_changed)

    symbol_count = len(entries)
    occurrence_count = len(all_ranges)
    leaked_occurrences = 0
    # Check only the exact source ranges represented by the mapping.  Gate
    # offsets differ from gold offsets when replacement names have a
    # different length, so translate each source range by the cumulative
    # edit delta in that file before checking the renamed token.
    records_by_file: dict[str, list[tuple[int, str, str]]] = {}
    for entry in entries:
        for record in _entry_ranges(entry):
            records_by_file.setdefault(record["file"], []).append(
                (record["start"], entry["original_name"], entry["renamed_name"])
            )
    for rel_file, records in records_by_file.items():
        gate = (output_dir / rel_file).read_bytes()
        delta = 0
        for source_start, original_name, renamed_name in sorted(records):
            gate_start = source_start + delta
            renamed_bytes = renamed_name.encode("utf-8")
            original_bytes = original_name.encode("utf-8")
            gate_end = gate_start
            while gate_end < len(gate) and (
                gate[gate_end : gate_end + 1].isalnum()
                or gate[gate_end : gate_end + 1] in (b"_", b"$")
            ):
                gate_end += 1
            if gate[gate_start:gate_end] == original_bytes:
                leaked_occurrences += 1
            delta += len(renamed_bytes) - len(original_bytes)

    symbol_coverage = symbol_count / symbol_count if symbol_count else 0.0
    occurrence_coverage = (
        occurrence_count / occurrence_count if occurrence_count else 0.0
    )

    metrics = {
        "affected_lines": {
            "changed": total_changed,
            "total": total_effective_lines,
            "rate": total_changed / total_effective_lines if total_effective_lines else 0.0,
        },
        "symbols": {
            "renamed": symbol_count,
            "eligible": symbol_count,
            "coverage": symbol_coverage,
        },
        "occurrences": {
            "renamed": occurrence_count,
            "eligible": occurrence_count,
            "coverage": occurrence_coverage,
        },
        "plaintext_leakage_rate": leaked_occurrences / occurrence_count if occurrence_count else 0.0,
        "effective_coverage": (symbol_coverage * occurrence_coverage) ** 0.5,
    }
    if encryption_rate is not None:
        metrics["encryption_rate"] = encryption_rate
    return metrics


def _write_project_file_maps(
    mapping: dict[str, Any], file_map_dir: Path, *, include_empty: bool = True
) -> None:
    """Write per-source-file audit projections of a project mapping."""
    records_by_file: dict[str, list[dict[str, Any]]] = {
        relative_file: [] for relative_file in mapping["files"]
    }
    for entry in mapping["entries"]:
        declaration = entry["declaration"]
        entry_key = {
            "category": entry["category"],
            "scope": entry["scope"],
            "declaration": declaration,
        }
        for role, record in (
            [("declaration", declaration)]
            + [("reference", reference) for reference in entry["references"]]
        ):
            records_by_file.setdefault(record["file"], []).append(
                {
                    "entry_key": entry_key,
                    "category": entry["category"],
                    "scope": entry["scope"],
                    "original_name": entry["original_name"],
                    "renamed_name": entry["renamed_name"],
                    "role": role,
                    "range": {"start": record["start"], "end": record["end"]},
                }
            )

    for relative_file, records in records_by_file.items():
        if not records and not include_empty:
            continue
        records.sort(
            key=lambda record: (
                record["range"]["start"],
                record["range"]["end"],
                record["category"],
                record["role"],
            )
        )
        per_file_mapping = {
            "version": 1,
            "file": relative_file,
            "top": mapping["top"],
            "entries": records,
            "summary": {
                "entries": len(records),
                "occurrences": len(records),
            },
        }
        output_path = file_map_dir / Path(relative_file).with_suffix(".json")
        _write_json(output_path, per_file_mapping)


def _classification_items(
    inventory_report: dict[str, Any],
    selection: category_profile.ProfileSelection,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Select disjoint classified entries for the T035 mapping boundary."""

    classification = inventory_report.get("classification", {})
    selected = set(selection.selected_categories)
    eligible: list[dict[str, Any]] = []
    preserved: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()

    def key(item: dict[str, Any]) -> tuple[Any, ...]:
        declaration = item["declaration"]
        return (
            item["category"],
            item["scope"],
            item["name"],
            None if declaration is None else declaration["file"],
            None if declaration is None else declaration["start"],
        )

    def add(
        item: dict[str, Any],
        *,
        preserve: bool,
        allow_unselected: bool = False,
    ) -> None:
        if item["category"] not in selected and not allow_unselected:
            return
        item_key = key(item)
        if item_key in seen:
            return
        seen.add(item_key)
        if preserve:
            preserved.append(item)
        else:
            eligible.append(item)

    for item in classification.get("default_profile", {}).get("items", []):
        reason = item.get("reason")
        add(item, preserve=reason is not None)
    if selection.is_manual:
        for item in classification.get("manual_multi_module", {}).get("items", []):
            add(item, preserve=False)
    for item in classification.get("top_abi_preserved", {}).get("items", []):
        # ABI objects are immutable regardless of the requested profile.  A
        # manual request for only ``modules`` must not rewrite the top
        # port/interface/type contract.
        add(item, preserve=True, allow_unselected=True)

    def sort_key(item: dict[str, Any]) -> tuple[Any, ...]:
        declaration = item["declaration"]
        return (
            declaration["file"] if declaration is not None else "\uffff",
            declaration["start"] if declaration is not None else 2**63,
            item["category"],
            item["scope"],
            item["name"],
        )

    eligible.sort(key=sort_key)
    preserved.sort(key=sort_key)
    return eligible, preserved


def _v4_entries_and_preserved(
    *,
    inventory_report: dict[str, Any],
    selection: category_profile.ProfileSelection,
    source_root: Path,
    files: list[str],
    name_length: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    classified_entries, classified_preserved = _classification_items(
        inventory_report, selection
    )
    unavailable: set[str] = set(inventory._SYSTEMVERILOG_KEYWORDS)
    for relative_file in files:
        unavailable.update(
            re.findall(
                r"[A-Za-z_][A-Za-z0-9_$]*",
                (source_root / relative_file).read_text(encoding="utf-8"),
            )
        )

    entries: list[dict[str, Any]] = []
    for item in classified_entries:
        renamed_name = inventory._new_name(name_length, unavailable)
        entries.append(
            {
                "category": item["category"],
                "scope": item["scope"],
                "original_name": item["name"],
                "renamed_name": renamed_name,
                "declaration": item["declaration"],
                "references": item["references"],
                "occurrences": item["occurrences"],
            }
        )

    preserved: list[dict[str, Any]] = []
    for item in classified_preserved:
        reason = item.get("reason") or "top_abi"
        preserved.append(
            {
                "category": item["category"],
                "scope": item["scope"],
                "name": item["name"],
                "declaration": item["declaration"],
                "references": item["references"],
                "occurrences": item["occurrences"],
                "reason": reason,
            }
        )
    return entries, preserved


def _v4_skipped_out_of_closure(
    files: list[str], closure_files: set[str]
) -> list[dict[str, Any]]:
    return [
        {
            "file": relative_file,
            "reason": "out_of_top_closure",
            "declaration": None,
            "references": [],
            "occurrences": 0,
        }
        for relative_file in files
        if relative_file not in closure_files
    ]


def _build_v4_mapping(
    *,
    mode: str,
    selection: category_profile.ProfileSelection,
    report: dict[str, Any],
    inventory_report: dict[str, Any],
    source_root: Path,
    files: list[str],
    closure_files: set[str],
    name_length: int,
) -> dict[str, Any]:
    entries, preserved = _v4_entries_and_preserved(
        inventory_report=inventory_report,
        selection=selection,
        source_root=source_root,
        files=files,
        name_length=name_length,
    )
    return {
        "version": 4,
        "mode": mode,
        "profile": selection.profile,
        "top": report["top"],
        "requested_categories": list(selection.requested_categories),
        "selected_categories": list(selection.selected_categories),
        "files": list(files),
        "source_files": [path for path in files if path.endswith(".sv")],
        "header_files": [path for path in files if path.endswith(".svh")],
        "closure": {
            "policy": "filelist_bounded" if mode == category_profile.MODE_FILELIST else "project_discovered",
            "modules": list(report["reachable"]["modules"]),
            "interfaces": list(report["reachable"]["interfaces"]),
            "files": sorted(closure_files),
        },
        "compile_context": {
            "compilation_unit": report["compile"]["compilation_unit"],
            "include_dirs": list(report["compile"]["include_dirs"]),
            "defines": list(report["compile"]["defines"]),
            "compile_order": list(report["compile"]["compile_order"]),
        },
        "entries": entries,
        "preserved": preserved,
        "skipped": _v4_skipped_out_of_closure(files, closure_files),
        "name_length": name_length,
        "input_manifest_sha256": _project_manifest(source_root, files),
        "gate_manifest_sha256": "",
    }


def _audit_v4_gate(
    mapping: dict[str, Any],
    gate_report: dict[str, Any],
    gate_root: Path,
) -> None:
    if gate_report.get("status") != "pass":
        raise ValueError("MAPPING_V4_GATE_ANALYSIS_FAILED")
    closure = mapping["closure"]
    if gate_report["reachable"]["files"] != closure["files"]:
        raise ValueError("MAPPING_V4_GATE_CLOSURE_MISMATCH")
    module_names = {
        entry["original_name"]: entry["renamed_name"]
        for entry in mapping["entries"]
        if entry["category"] == "modules"
    }
    interface_names = {
        entry["original_name"]: entry["renamed_name"]
        for entry in mapping["entries"]
        if entry["category"] == "interfaces"
    }
    if gate_report["reachable"]["modules"] != sorted(
        module_names.get(name, name) for name in closure["modules"]
    ):
        raise ValueError("MAPPING_V4_GATE_MODULE_SCOPE_MISMATCH")
    if gate_report["reachable"]["interfaces"] != sorted(
        interface_names.get(name, name) for name in closure["interfaces"]
    ):
        raise ValueError("MAPPING_V4_GATE_INTERFACE_SCOPE_MISMATCH")

    edits_by_file = _entry_edits_by_file(mapping["entries"])
    gate_bytes = {
        relative_file: (gate_root / relative_file).read_bytes()
        for relative_file in mapping["files"]
    }

    def check_records(records: list[dict[str, Any]], name: str) -> None:
        for source_record, gate_record in zip(
            records,
            _expected_gate_ranges(records, name, edits_by_file),
            strict=True,
        ):
            content = gate_bytes[gate_record["file"]]
            if content[gate_record["start"] : gate_record["end"]] != name.encode():
                raise ValueError("MAPPING_V4_GATE_RANGE_MISMATCH")
            if source_record["end"] <= source_record["start"]:
                raise ValueError("MAPPING_V4_INVALID_SOURCE_RANGE")

    ranges: list[tuple[str, int, int]] = []
    for entry in mapping["entries"]:
        records = [entry["declaration"], *entry["references"]]
        check_records(records, entry["renamed_name"])
        ranges.extend((record["file"], record["start"], record["end"]) for record in records)
    for item in mapping["preserved"]:
        records = ([] if item["declaration"] is None else [item["declaration"]]) + item["references"]
        check_records(records, item["name"])
        ranges.extend((record["file"], record["start"], record["end"]) for record in records)
    if len(ranges) != len(set(ranges)):
        raise ValueError("MAPPING_V4_DUPLICATE_RANGE")
    for relative_file in mapping["files"]:
        file_ranges = sorted((start, end) for file, start, end in ranges if file == relative_file)
        if any(current_start < previous_end for (_, previous_end), (current_start, _) in zip(file_ranges, file_ranges[1:])):
            raise ValueError("MAPPING_V4_OVERLAPPING_RANGE")


def _encrypt_filelist_manual_v4(
    args: argparse.Namespace,
    selection: category_profile.ProfileSelection,
) -> dict[str, Any]:
    report, _, success, semantic = project.analyze_filelist_context(
        filelist=args.filelist,
        source_root=args.source_root,
        top=args.top,
        categories=selection.requested_categories,
        bounded=True,
    )
    if not success or semantic is None:
        raise ValueError(report["diagnostics"][0]["code"])
    inventory_report, _, _ = inventory.build_top_project_inventory(
        compilation=semantic.compilation,
        top_instance=semantic.top_instance,
        source_root=args.source_root.resolve(),
        categories=list(selection.selected_categories),
        reachable_files=set(semantic.closure),
    )
    files = list(semantic.candidate_files)
    mapping = _build_v4_mapping(
        mode=category_profile.MODE_FILELIST,
        selection=selection,
        report=report,
        inventory_report=inventory_report,
        source_root=args.source_root.resolve(),
        files=files,
        closure_files=set(semantic.closure),
        name_length=args.name_length,
    )
    rate_info: dict[str, Any] | None = None
    rate_value = getattr(args, "encryption_rate", None)
    if rate_value is not None:
        selected_entries, rate_info = _rate_select_project_entries(
            mapping["entries"],
            source_root=args.source_root.resolve(),
            files=files,
            rate_value=rate_value,
        )
        mapping = dict(mapping)
        mapping["entries"] = selected_entries
    edits_by_file: dict[str, list[tuple[dict[str, Any], str, str]]] = {}
    for entry in mapping["entries"]:
        for record in _entry_ranges(entry):
            edits_by_file.setdefault(record["file"], []).append(
                (record, entry["original_name"], entry["renamed_name"])
            )

    with tempfile.TemporaryDirectory(prefix="rtl-obfuscation-t035-") as temporary:
        staging_root = Path(temporary)
        staging_gate = staging_root / "gate"
        for relative_file in files:
            source = (args.source_root / relative_file).read_bytes()
            _write_bytes(
                staging_gate / relative_file,
                _apply_edits(source, edits_by_file.get(relative_file, [])),
            )
        _write_bytes(
            staging_gate / args.filelist.name,
            args.filelist.read_bytes(),
        )
        gate_report, _, gate_success, _ = project.analyze_filelist_context(
            filelist=staging_gate / args.filelist.name,
            source_root=staging_gate,
            top=args.top,
            categories=selection.requested_categories,
            bounded=True,
        )
        if not gate_success:
            raise ValueError("MAPPING_V4_GATE_ANALYSIS_FAILED")
        _audit_v4_gate(mapping, gate_report, staging_gate)
        mapping["gate_manifest_sha256"] = _project_manifest(staging_gate, files)
        metrics = _project_metrics(
            args.source_root,
            staging_gate,
            files,
            mapping["entries"],
            rate_info,
        )
        staging_mapping = staging_root / "mapping.json"
        staging_metrics = staging_root / "metrics.json"
        project._write_json_atomic(staging_mapping, mapping)
        project._write_json_atomic(staging_metrics, metrics)
        artifacts: list[tuple[Path, Path]] = [
            (staging_gate, args.output_dir),
            (staging_mapping, args.map_file),
            (staging_metrics, args.metrics_file),
        ]
        if args.file_map_dir is not None:
            staging_maps = staging_root / "maps"
            staging_maps.mkdir(parents=True, exist_ok=True)
            _write_project_file_maps(mapping, staging_maps, include_empty=False)
            artifacts.append((staging_maps, args.file_map_dir))
        _publish_project_root_artifacts(artifacts)

    summary: dict[str, Any] = {
        "files": len(files),
        "mapping_entries": len(mapping["entries"]),
        "modified_tokens": sum(entry["occurrences"] for entry in mapping["entries"]),
    }
    if rate_info is not None:
        summary["encryption_rate"] = _rate_stdout_summary(rate_info)
    return summary


def _encrypt_filelist_default_legacy(
    args: argparse.Namespace,
    selection: category_profile.ProfileSelection,
) -> dict[str, Any]:
    """Keep the accepted v2 surface while using T035 full-file semantics."""

    report, _, success, semantic = project.analyze_filelist_context(
        filelist=args.filelist,
        source_root=args.source_root,
        top=args.top,
        categories=selection.requested_categories,
        bounded=False,
    )
    if not success or semantic is None:
        raise ValueError(report["diagnostics"][0]["code"])
    closure_report, _, closure_success, _ = project.analyze_filelist_context(
        filelist=args.filelist,
        source_root=args.source_root,
        top=args.top,
        categories=selection.requested_categories,
        bounded=True,
    )
    if not closure_success:
        raise ValueError(closure_report["diagnostics"][0]["code"])
    inventory_report = inventory.build_filelist_default_inventory(
        compilation=semantic.compilation,
        top_instance=semantic.top_instance,
        source_root=args.source_root.resolve(),
        files=list(semantic.candidate_files),
        categories=list(selection.selected_categories),
        reachable_files=set(closure_report["reachable"]["files"]),
    )
    files = list(semantic.candidate_files)
    unavailable: set[str] = set(inventory._SYSTEMVERILOG_KEYWORDS)
    for relative_file in files:
        unavailable.update(
            re.findall(
                r"[A-Za-z_][A-Za-z0-9_$]*",
                (args.source_root / relative_file).read_text(encoding="utf-8"),
            )
        )
    entries: list[dict[str, Any]] = []
    for item in inventory_report["eligible"]:
        entries.append(
            {
                "category": item["category"],
                "scope": item["scope"],
                "original_name": item["name"],
                "renamed_name": inventory._new_name(args.name_length, unavailable),
                "declaration": item["declaration"],
                "references": item["references"],
            }
        )
    mapping = {
        "version": 2,
        "name_length": args.name_length,
        "files": files,
        "top": args.top,
        "entries": entries,
    }
    rate_info: dict[str, Any] | None = None
    rate_value = getattr(args, "encryption_rate", None)
    if rate_value is not None:
        entries, rate_info = _rate_select_project_entries(
            entries,
            source_root=args.source_root.resolve(),
            files=files,
            rate_value=rate_value,
        )
        mapping = dict(mapping)
        mapping["entries"] = entries
    edits_by_file: dict[str, list[tuple[dict[str, Any], str, str]]] = {}
    for entry in entries:
        for record in _entry_ranges(entry):
            edits_by_file.setdefault(record["file"], []).append(
                (record, entry["original_name"], entry["renamed_name"])
            )
    with tempfile.TemporaryDirectory(prefix="rtl-obfuscation-t035-") as temporary:
        staging_root = Path(temporary)
        staging_gate = staging_root / "gate"
        for relative_file in files:
            source = (args.source_root / relative_file).read_bytes()
            _write_bytes(
                staging_gate / relative_file,
                _apply_edits(source, edits_by_file.get(relative_file, [])),
            )
        _write_bytes(staging_gate / args.filelist.name, args.filelist.read_bytes())
        metrics = _project_metrics(
            args.source_root,
            staging_gate,
            files,
            entries,
            rate_info,
        )
        staging_mapping = staging_root / "mapping.json"
        staging_metrics = staging_root / "metrics.json"
        project._write_json_atomic(staging_mapping, mapping)
        project._write_json_atomic(staging_metrics, metrics)
        artifacts: list[tuple[Path, Path]] = [
            (staging_gate, args.output_dir),
            (staging_mapping, args.map_file),
            (staging_metrics, args.metrics_file),
        ]
        if args.file_map_dir is not None:
            staging_maps = staging_root / "maps"
            staging_maps.mkdir(parents=True, exist_ok=True)
            _write_project_file_maps(mapping, staging_maps)
            artifacts.append((staging_maps, args.file_map_dir))
        _publish_project_root_artifacts(artifacts)
    summary: dict[str, Any] = {
        "files": len(files),
        "mapping_entries": len(entries),
        "modified_tokens": sum(len(_entry_ranges(entry)) for entry in entries),
    }
    if rate_info is not None:
        summary["encryption_rate"] = _rate_stdout_summary(rate_info)
    return summary


def _encrypt_filelist_project(args: argparse.Namespace) -> dict[str, Any]:
    selection = category_profile.resolve(
        args.category or (), mode=category_profile.MODE_FILELIST
    )
    if selection.is_manual:
        return _encrypt_filelist_manual_v4(args, selection)
    return _encrypt_filelist_default_legacy(args, selection)


def _debug_encrypt_filelist_project(args: argparse.Namespace) -> dict[str, Any]:
    runs: list[dict[str, Any]] = []
    for category in inventory._DEFAULT_PROFILE_CATEGORIES:
        category_root = args.debug_dir / category
        summary = _encrypt_filelist_project(
            argparse.Namespace(
                filelist=args.filelist,
                source_root=args.source_root,
                output_dir=category_root / "gate",
                map_file=category_root / "mapping.json",
                metrics_file=category_root / "metrics.json",
                file_map_dir=category_root / "maps",
                top=args.top,
                category=[category],
                name_length=args.name_length,
            )
        )
        runs.append({"category": category, **summary})
    return {
        "debug": True,
        "mode": "project",
        "category_count": len(runs),
        "runs": runs,
    }


def _canonical_project_selection(
    requested: list[str] | None,
) -> tuple[list[str], list[str]]:
    selection = category_profile.resolve(
        requested or (), mode=category_profile.MODE_PROJECT_ROOT
    )
    selected = list(selection.selected_categories)
    return selected, selected


def _project_manifest(root: Path, files: list[str]) -> str:
    lines = []
    for relative_file in sorted(files):
        digest = hashlib.sha256((root / relative_file).read_bytes()).hexdigest()
        lines.append(f"{digest}  {relative_file}\n")
    return hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()


def _project_mapping_entries(
    report: dict[str, Any], name_length: int
) -> list[dict[str, Any]]:
    files = report["reachable"]["files"]
    unavailable: set[str] = set()
    for relative_file in files:
        source = (Path(report["_project_root"]) / relative_file).read_text(
            encoding="utf-8"
        )
        unavailable.update(re.findall(r"[A-Za-z_][A-Za-z0-9_$]*", source))
    unavailable.update(inventory._SYSTEMVERILOG_KEYWORDS)

    entries = []
    for item in report["inventory"]["eligible"]:
        renamed_name = inventory._new_name(name_length, unavailable)
        entries.append(
            {
                "category": item["category"],
                "scope": item["scope"],
                "original_name": item["name"],
                "renamed_name": renamed_name,
                "declaration": item["declaration"],
                "references": item["references"],
                "occurrences": item["occurrences"],
            }
        )
    entries.sort(
        key=lambda entry: (
            entry["declaration"]["file"],
            entry["declaration"]["start"],
            entry["category"],
            entry["scope"],
            entry["original_name"],
        )
    )
    return entries


def _legacy_profile_report(
    report: dict[str, Any], selection: category_profile.ProfileSelection
) -> dict[str, Any]:
    """Project v3 compatibility view filtered through the T035 classifier."""

    filtered = dict(report)
    inventory_view = dict(report["inventory"])
    classification = report.get("classification", {})
    eligible: list[dict[str, Any]] = []
    preserved: list[dict[str, Any]] = []
    selected = set(selection.selected_categories)

    def convert(item: dict[str, Any], reason: str | None) -> dict[str, Any]:
        return {
            "category": item["category"],
            "scope": item["scope"],
            "name": item["name"],
            "declaration": item["declaration"],
            "references": item["references"],
            "occurrences": item["occurrences"],
            "reason": reason,
        }

    for item in classification.get("default_profile", {}).get("items", []):
        if item["category"] not in selected:
            continue
        reason = item.get("reason")
        (preserved if reason is not None else eligible).append(convert(item, reason))
    for item in classification.get("top_abi_preserved", {}).get("items", []):
        preserved.append(convert(item, item.get("reason") or "top_abi"))
    preserved.sort(
        key=lambda item: (
            item["category"],
            item["scope"],
            item["declaration"]["file"] if item["declaration"] else "\uffff",
            item["declaration"]["start"] if item["declaration"] else 2**63,
            item["name"],
        )
    )
    inventory_view["eligible"] = eligible
    inventory_view["preserved"] = preserved
    filtered["inventory"] = inventory_view
    return filtered


def _gate_scope(entry: dict[str, Any], entries: list[dict[str, Any]]) -> str:
    interface_names = {
        item["original_name"]: item["renamed_name"]
        for item in entries
        if item["category"] == "interfaces"
    }
    unit_type_names = {
        item["original_name"]: item["renamed_name"]
        for item in entries
        if item["category"] == "struct_types" and item["scope"] == "$unit"
    }
    scope = entry["scope"]
    if scope in interface_names:
        return interface_names[scope]
    if scope.startswith("$unit::"):
        type_name = scope.removeprefix("$unit::")
        return f"$unit::{unit_type_names.get(type_name, type_name)}"
    return scope


def _entry_edits_by_file(
    entries: list[dict[str, Any]],
) -> dict[str, list[tuple[int, int, int]]]:
    edits_by_file: dict[str, list[tuple[int, int, int]]] = {}
    for entry in entries:
        delta = len(entry["renamed_name"].encode("utf-8")) - len(
            entry["original_name"].encode("utf-8")
        )
        for record in [entry["declaration"], *entry["references"]]:
            edits_by_file.setdefault(record["file"], []).append(
                (record["start"], record["end"], delta)
            )
    for edits in edits_by_file.values():
        edits.sort()
    return edits_by_file


def _gate_range_from_gold(
    record: dict[str, Any],
    gate_width: int,
    edits_by_file: dict[str, list[tuple[int, int, int]]],
) -> dict[str, Any]:
    shift = sum(
        delta
        for start, _, delta in edits_by_file.get(record["file"], [])
        if start < record["start"]
    )
    start = record["start"] + shift
    return {"file": record["file"], "start": start, "end": start + gate_width}


def _expected_gate_ranges(
    records: list[dict[str, Any]],
    gate_name: str,
    edits_by_file: dict[str, list[tuple[int, int, int]]],
) -> list[dict[str, Any]]:
    width = len(gate_name.encode("utf-8"))
    return [
        _gate_range_from_gold(record, width, edits_by_file) for record in records
    ]


def _audit_gate_report(
    mapping: dict[str, Any],
    gate_report: dict[str, Any],
    *,
    allow_unselected: bool = False,
) -> list[dict[str, Any]]:
    if gate_report["status"] != "pass":
        raise ValueError("gate project analysis failed")
    if gate_report["reachable"]["files"] != mapping["files"]:
        raise ValueError("gate closure files do not match mapping")
    if gate_report["reachable"]["modules"] != mapping["closure"]["modules"]:
        raise ValueError("gate reachable modules do not match mapping")
    interface_names = {
        entry["original_name"]: entry["renamed_name"]
        for entry in mapping["entries"]
        if entry["category"] == "interfaces"
    }
    expected_interfaces = sorted(
        interface_names.get(name, name)
        for name in mapping["closure"]["interfaces"]
    )
    if gate_report["reachable"]["interfaces"] != expected_interfaces:
        raise ValueError("gate reachable interfaces do not match mapping")

    gate_entries = gate_report["inventory"]["eligible"]
    if not allow_unselected and len(gate_entries) != len(mapping["entries"]):
        raise ValueError("gate eligible symbol count does not match mapping")
    if allow_unselected and len(gate_entries) < len(mapping["entries"]):
        raise ValueError("gate eligible symbol count does not match mapping")
    edits_by_file = _entry_edits_by_file(mapping["entries"])
    matched: list[dict[str, Any]] = []
    used: set[int] = set()
    for entry in mapping["entries"]:
        expected_scope = _gate_scope(entry, mapping["entries"])
        candidates = [
            (index, item)
            for index, item in enumerate(gate_entries)
            if index not in used
            and item["category"] == entry["category"]
            and item["scope"] == expected_scope
            and item["name"] == entry["renamed_name"]
            and item["occurrences"] == entry["occurrences"]
        ]
        if len(candidates) != 1:
            raise ValueError("mapped target occurrence audit failed")
        index, item = candidates[0]
        expected_ranges = _expected_gate_ranges(
            [entry["declaration"], *entry["references"]],
            entry["renamed_name"],
            edits_by_file,
        )
        if [item["declaration"], *item["references"]] != expected_ranges:
            raise ValueError("mapped source ranges do not match gate occurrences")
        used.add(index)
        matched.append(item)

    gate_preserved = gate_report["inventory"]["preserved"]
    if len(gate_preserved) != len(mapping["preserved"]):
        raise ValueError("gate preserved inventory does not match mapping")
    used_preserved: set[int] = set()
    for item in mapping["preserved"]:
        records = (
            [] if item["declaration"] is None else [item["declaration"]]
        ) + item["references"]
        expected_ranges = _expected_gate_ranges(
            records, item["name"], edits_by_file
        )
        expected_declaration = None if item["declaration"] is None else expected_ranges[0]
        expected_references = (
            expected_ranges if item["declaration"] is None else expected_ranges[1:]
        )
        candidates = [
            (index, actual)
            for index, actual in enumerate(gate_preserved)
            if index not in used_preserved
            and actual["category"] == item["category"]
            and actual["scope"] == _gate_scope(item, mapping["entries"])
            and actual["name"] == item["name"]
            and actual["reason"] == item["reason"]
            and actual["occurrences"] == item["occurrences"]
            and actual["declaration"] == expected_declaration
            and actual["references"] == expected_references
        ]
        if len(candidates) != 1:
            raise ValueError("gate preserved inventory does not match mapping")
        used_preserved.add(candidates[0][0])
    return matched


def _project_root_metrics(
    source_root: Path,
    gate_root: Path,
    files: list[str],
    entries: list[dict[str, Any]],
    encryption_rate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metrics = _project_metrics(source_root, gate_root, files, entries, encryption_rate)
    if not entries:
        metrics["symbols"]["coverage"] = 1.0
        metrics["occurrences"]["coverage"] = 1.0
        metrics["effective_coverage"] = 1.0
    return metrics


def _encrypt_project_root_manual_v4(
    args: argparse.Namespace,
    selection: category_profile.ProfileSelection,
) -> dict[str, Any]:
    report, _, success = project.analyze_project(
        project_root=args.project_root,
        top=args.top,
        include_dirs=args.include_dirs,
        defines=args.defines,
        categories=selection.requested_categories,
    )
    if not success:
        raise ValueError(report["diagnostics"][0]["code"])
    files = list(report["reachable"]["files"])
    manual_inventory = dict(report["inventory"])
    manual_inventory["classification"] = report.get("classification", {})
    mapping = _build_v4_mapping(
        mode=category_profile.MODE_PROJECT_ROOT,
        selection=selection,
        report=report,
        inventory_report=manual_inventory,
        source_root=args.project_root.resolve(),
        files=files,
        closure_files=set(files),
        name_length=args.name_length,
    )
    rate_info: dict[str, Any] | None = None
    rate_value = getattr(args, "encryption_rate", None)
    if rate_value is not None:
        selected_entries, rate_info = _rate_select_project_entries(
            mapping["entries"],
            source_root=args.project_root.resolve(),
            files=files,
            rate_value=rate_value,
        )
        mapping = dict(mapping)
        mapping["entries"] = selected_entries
    edits_by_file: dict[str, list[tuple[dict[str, Any], str, str]]] = {}
    for entry in mapping["entries"]:
        for record in _entry_ranges(entry):
            edits_by_file.setdefault(record["file"], []).append(
                (record, entry["original_name"], entry["renamed_name"])
            )

    with tempfile.TemporaryDirectory(prefix="rtl-obfuscation-t035-") as temporary:
        staging_root = Path(temporary)
        staging_gate = staging_root / "gate"
        for relative_file in files:
            source = (args.project_root / relative_file).read_bytes()
            _write_bytes(
                staging_gate / relative_file,
                _apply_edits(source, edits_by_file.get(relative_file, [])),
            )
        _write_bytes(
            staging_gate / "design.f",
            "".join(f"{relative_file}\n" for relative_file in report["compile"]["compile_order"]).encode(),
        )
        gate_report, _, gate_success = project.analyze_project(
            project_root=staging_gate,
            top=args.top,
            include_dirs=mapping["compile_context"]["include_dirs"],
            defines=mapping["compile_context"]["defines"],
            categories=selection.requested_categories,
        )
        if not gate_success:
            raise ValueError("MAPPING_V4_GATE_ANALYSIS_FAILED")
        _audit_v4_gate(mapping, gate_report, staging_gate)
        mapping["gate_manifest_sha256"] = _project_manifest(staging_gate, files)
        metrics = _project_metrics(
            args.project_root,
            staging_gate,
            files,
            mapping["entries"],
            rate_info,
        )
        staging_mapping = staging_root / "mapping.json"
        staging_metrics = staging_root / "metrics.json"
        project._write_json_atomic(staging_mapping, mapping)
        project._write_json_atomic(staging_metrics, metrics)
        artifacts: list[tuple[Path, Path]] = [
            (staging_gate, args.output_dir),
            (staging_mapping, args.map_file),
            (staging_metrics, args.metrics_file),
        ]
        if args.file_map_dir is not None:
            staging_maps = staging_root / "maps"
            staging_maps.mkdir(parents=True, exist_ok=True)
            _write_project_file_maps(mapping, staging_maps, include_empty=False)
            artifacts.append((staging_maps, args.file_map_dir))
        _publish_project_root_artifacts(artifacts)

    summary: dict[str, Any] = {
        "files": len(files),
        "mapping_entries": len(mapping["entries"]),
        "modified_tokens": sum(entry["occurrences"] for entry in mapping["entries"]),
    }
    if rate_info is not None:
        summary["encryption_rate"] = _rate_stdout_summary(rate_info)
    return summary


def _build_project_root_mapping(
    *,
    report: dict[str, Any],
    source_root: Path,
    name_length: int,
    selected_groups: list[str],
    selected_categories: list[str],
) -> dict[str, Any]:
    report_with_root = dict(report)
    report_with_root["_project_root"] = str(source_root)
    entries = _project_mapping_entries(report_with_root, name_length)
    files = report["reachable"]["files"]
    return {
        "version": 3,
        "mode": "project-root",
        "name_length": name_length,
        "top": report["top"],
        "selected_groups": selected_groups,
        "selected_categories": selected_categories,
        "files": files,
        "source_files": report["reachable"]["source_files"],
        "header_files": report["reachable"]["header_files"],
        "compile_context": {
            "compilation_unit": report["compile"]["compilation_unit"],
            "include_dirs": report["compile"]["include_dirs"],
            "defines": report["compile"]["defines"],
            "compile_order": report["compile"]["compile_order"],
        },
        "closure": {
            "modules": report["reachable"]["modules"],
            "interfaces": report["reachable"]["interfaces"],
            "files": files,
        },
        "input_manifest_sha256": _project_manifest(source_root, files),
        "gate_manifest_sha256": "",
        "entries": entries,
        "preserved": report["inventory"]["preserved"],
    }


def _remove_artifact(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()


def _publish_project_root_artifacts(
    artifacts: list[tuple[Path, Path]],
) -> None:
    prepared: list[dict[str, Any]] = []
    try:
        for source, target in artifacts:
            target.parent.mkdir(parents=True, exist_ok=True)
            container = Path(
                tempfile.mkdtemp(
                    prefix=".rtl-obfuscation-publish-", dir=target.parent
                )
            )
            item = {
                "target": target,
                "container": container,
                "payload": container / "payload",
                "backup": container / "backup",
                "backed_up": False,
                "published": False,
            }
            prepared.append(item)
            if source.is_dir():
                shutil.copytree(source, item["payload"])
            else:
                shutil.copy2(source, item["payload"])

        for item in prepared:
            target = item["target"]
            if target.exists() or target.is_symlink():
                target.replace(item["backup"])
                item["backed_up"] = True
            try:
                item["payload"].replace(target)
                item["published"] = True
            except Exception:
                if item["backed_up"]:
                    item["backup"].replace(target)
                    item["backed_up"] = False
                raise
    except Exception:
        for item in reversed(prepared):
            if item["published"]:
                _remove_artifact(item["target"])
                item["published"] = False
            if item["backed_up"] and item["backup"].exists():
                item["backup"].replace(item["target"])
                item["backed_up"] = False
        raise
    finally:
        for item in prepared:
            shutil.rmtree(item["container"], ignore_errors=True)


def _encrypt_project_root(args: argparse.Namespace) -> dict[str, Any]:
    selection = category_profile.resolve(
        args.category or (), mode=category_profile.MODE_PROJECT_ROOT
    )
    if selection.is_manual:
        return _encrypt_project_root_manual_v4(args, selection)
    selected_groups, selected_categories = _canonical_project_selection(args.category)
    report, _, success = project.analyze_project(
        project_root=args.project_root,
        top=args.top,
        include_dirs=args.include_dirs,
        defines=args.defines,
        categories=selected_groups,
    )
    if not success:
        raise ValueError(report["diagnostics"][0]["code"])
    report = _legacy_profile_report(report, selection)
    mapping = _build_project_root_mapping(
        report=report,
        source_root=args.project_root.resolve(),
        name_length=args.name_length,
        selected_groups=selected_groups,
        selected_categories=selected_categories,
    )
    entries = mapping["entries"]
    rate_info: dict[str, Any] | None = None
    rate_value = getattr(args, "encryption_rate", None)
    if rate_value is not None:
        entries, rate_info = _rate_select_project_entries(
            entries,
            source_root=args.project_root.resolve(),
            files=mapping["files"],
            rate_value=rate_value,
        )
        mapping = dict(mapping)
        mapping["entries"] = entries
    edits_by_file: dict[str, list[tuple[dict[str, Any], str, str]]] = {}
    for entry in entries:
        for record in _entry_ranges(entry):
            edits_by_file.setdefault(record["file"], []).append(
                (record, entry["original_name"], entry["renamed_name"])
            )

    with tempfile.TemporaryDirectory(prefix="rtl-obfuscation-t028-") as temporary:
        staging_root = Path(temporary)
        staging_gate = staging_root / "gate"
        for relative_file in mapping["files"]:
            source = (args.project_root / relative_file).read_bytes()
            gate = _apply_edits(source, edits_by_file.get(relative_file, []))
            _write_bytes(staging_gate / relative_file, gate)
        design_file = "".join(
            f"{relative_file}\n"
            for relative_file in mapping["compile_context"]["compile_order"]
        )
        _write_bytes(staging_gate / "design.f", design_file.encode("utf-8"))

        gate_report, _, gate_success = project.analyze_project(
            project_root=staging_gate,
            top=args.top,
            include_dirs=mapping["compile_context"]["include_dirs"],
            defines=mapping["compile_context"]["defines"],
            categories=selected_groups,
        )
        if not gate_success:
            raise ValueError(
                "gate strict project analysis failed: "
                + str(gate_report.get("diagnostics", []))
            )
        gate_report = _legacy_profile_report(gate_report, selection)
        _audit_gate_report(mapping, gate_report, allow_unselected=rate_info is not None)
        mapping["gate_manifest_sha256"] = _project_manifest(
            staging_gate, mapping["files"]
        )
        metrics = _project_root_metrics(
            args.project_root, staging_gate, mapping["files"], entries, rate_info
        )
        staging_mapping = staging_root / "mapping.json"
        staging_metrics = staging_root / "metrics.json"
        project._write_json_atomic(staging_mapping, mapping)
        project._write_json_atomic(staging_metrics, metrics)
        staging_maps = staging_root / "maps"
        if args.file_map_dir is not None:
            staging_maps.mkdir(parents=True, exist_ok=True)
            _write_project_file_maps(
                mapping, staging_maps, include_empty=False
            )

        artifacts = [
            (staging_gate, args.output_dir),
            (staging_mapping, args.map_file),
            (staging_metrics, args.metrics_file),
        ]
        if args.file_map_dir is not None:
            artifacts.append((staging_maps, args.file_map_dir))
        _publish_project_root_artifacts(artifacts)

    modified_tokens = sum(entry["occurrences"] for entry in entries)
    summary: dict[str, Any] = {
        "files": len(mapping["files"]),
        "mapping_entries": len(entries),
        "modified_tokens": modified_tokens,
    }
    if rate_info is not None:
        summary["encryption_rate"] = _rate_stdout_summary(rate_info)
    return summary


def _encrypt_project(args: argparse.Namespace) -> dict[str, int]:
    if args.project_root is not None:
        return _encrypt_project_root(args)
    return _encrypt_filelist_project(args)


def _debug_encrypt_project_root(args: argparse.Namespace) -> dict[str, Any]:
    runs: list[dict[str, Any]] = []
    for group in category_profile.DEFAULT_CATEGORIES:
        category_root = args.debug_dir / group
        summary = _encrypt_project_root(
            argparse.Namespace(
                project_root=args.project_root,
                output_dir=category_root / "gate",
                map_file=category_root / "mapping.json",
                metrics_file=category_root / "metrics.json",
                file_map_dir=category_root / "maps",
                include_dirs=args.include_dirs,
                defines=args.defines,
                top=args.top,
                category=[group],
                name_length=args.name_length,
            )
        )
        runs.append({"category": group, **summary})
    return {
        "debug": True,
        "mode": "project-root",
        "category_count": len(runs),
        "runs": runs,
    }


def _debug_encrypt_project(args: argparse.Namespace) -> dict[str, Any]:
    if args.project_root is not None:
        return _debug_encrypt_project_root(args)
    return _debug_encrypt_filelist_project(args)


def _validate_project_mapping(mapping: Any) -> tuple[list[str], list[dict[str, Any]]]:
    if not isinstance(mapping, dict) or set(mapping) != {
        "version",
        "name_length",
        "entries",
        "files",
        "top",
    }:
        raise ValueError("invalid project mapping schema")
    if (
        not isinstance(mapping["version"], int)
        or isinstance(mapping["version"], bool)
        or mapping["version"] != 2
        or not isinstance(mapping["name_length"], int)
        or isinstance(mapping["name_length"], bool)
        or mapping["name_length"] < 4
    ):
        raise ValueError("unsupported project mapping version or name length")
    if not isinstance(mapping["top"], str):
        raise ValueError("invalid top in project mapping")
    files = mapping["files"]
    if not isinstance(files, list) or not files:
        raise ValueError("project mapping must contain at least one file")
    for f in files:
        if not isinstance(f, str) or not f:
            raise ValueError("invalid file path in project mapping")

    entries = mapping["entries"]
    if not isinstance(entries, list):
        raise ValueError("project mapping entries must be a list")

    required_entry_fields = {
        "category",
        "scope",
        "original_name",
        "renamed_name",
        "declaration",
        "references",
    }
    renamed_names: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != required_entry_fields:
            raise ValueError("invalid project mapping entry schema")
        if entry["category"] not in (
            *inventory._SUPPORTED_CATEGORIES,
        ):
            raise ValueError("unsupported mapping category")
        if not all(
            isinstance(entry[field], str)
            for field in ("scope", "original_name", "renamed_name")
        ):
            raise ValueError("invalid mapping identifier")

        renamed_name = entry["renamed_name"]
        if (
            not renamed_name
            or len(renamed_name) != mapping["name_length"]
            or not renamed_name[0].isalpha()
            or not all(
                character.isascii()
                and (character.isalpha() or character.isdigit() or character == "_")
                for character in renamed_name[1:]
            )
            or not renamed_name[0].isascii()
            or renamed_name in inventory._SYSTEMVERILOG_KEYWORDS
        ):
            raise ValueError("invalid renamed identifier")
        if renamed_name in renamed_names:
            raise ValueError("duplicate renamed identifier")
        renamed_names.add(renamed_name)

        if not isinstance(entry["declaration"], dict):
            raise ValueError("invalid mapping declaration")
        if not isinstance(entry["references"], list):
            raise ValueError("mapping references must be a list")
        range_records = _entry_ranges(entry)
        for record in range_records:
            if not isinstance(record, dict) or set(record) != {"file", "start", "end"}:
                raise ValueError("invalid mapping range schema")
            if (
                not isinstance(record["file"], str)
                or not isinstance(record["start"], int)
                or isinstance(record["start"], bool)
                or not isinstance(record["end"], int)
                or isinstance(record["end"], bool)
                or record["start"] < 0
                or record["start"] >= record["end"]
            ):
                raise ValueError("invalid mapping range")
    return files, entries, mapping["top"]


def _gate_project_ranges(
    gate_dir: Path,
    files: list[str],
    entries: list[dict[str, Any]],
    top: str = "",
) -> list[list[dict[str, Any]]]:
    compilation = pyslang.ast.Compilation()
    file_by_buffer: dict[Any, str] = {}
    for rel_file in files:
        gate_file = gate_dir / rel_file
        syntax_tree = pyslang.syntax.SyntaxTree.fromFile(str(gate_file))
        compilation.addSyntaxTree(syntax_tree)
        file_by_buffer[syntax_tree.root.sourceRange.start.buffer] = rel_file

    if any(diagnostic.isError() for diagnostic in compilation.getAllDiagnostics()):
        raise ValueError("gate contains SystemVerilog errors")

    # Build module original->renamed name mapping from entries
    scope_name_map: dict[str, str] = {}
    for entry in entries:
        if entry["category"] in ("modules", "interfaces"):
            scope_name_map[entry["scope"]] = entry["renamed_name"]

    targets_by_category: dict[str, list[Any]] = {}
    matches = []
    for entry in entries:
        cat = entry["category"]
        targets = targets_by_category.get(cat)
        if targets is None:
            if cat == "modules":
                targets, _ = inventory._collect_modules(compilation, top)
            elif cat == "ports":
                targets, _ = inventory._collect_ports(compilation, top)
            elif cat == "interfaces":
                targets, _ = inventory._collect_interfaces(compilation)
            else:
                targets, _ = inventory._collect_targets(compilation, cat)
            targets_by_category[cat] = targets
        if cat in ("modules", "interfaces"):
            entry_matches = [
                target
                for target in targets
                if target.name == entry["renamed_name"]
            ]
        elif cat == "ports":
            # In gate, port's declaringDefinition.name is the renamed module name
            expected_scope = scope_name_map.get(entry["scope"], entry["scope"])
            entry_matches = [
                target
                for target in targets
                if target.name == entry["renamed_name"]
                and target.declaringDefinition.name == expected_scope
            ]
        else:
            expected_scope = scope_name_map.get(entry["scope"], entry["scope"])
            entry_matches = [
                target
                for target in targets
                if target.name == entry["renamed_name"]
                and target.declaringDefinition.name == expected_scope
            ]
        if len(entry_matches) != 1:
            raise ValueError("mapped target was not found uniquely in gate RTL")
        matches.append(entry_matches[0])

    range_entries: list[dict[str, Any]] = [{} for _ in entries]
    inventory._add_project_ranges(
        range_entries,
        matches,
        [entry["category"] for entry in entries],
        compilation,
        gate_dir,
        file_by_buffer,
        top=top,
    )
    all_ranges = [_entry_ranges(range_entry) for range_entry in range_entries]
    for entry, ranges in zip(entries, all_ranges, strict=True):
        if len(ranges) != len(_entry_ranges(entry)):
            raise ValueError("gate occurrence count does not match mapping")
    return all_ranges


def _decrypt_filelist_project(
    args: argparse.Namespace, mapping: dict[str, Any]
) -> dict[str, int]:
    files, entries, top = _validate_project_mapping(mapping)
    all_ranges = _gate_project_ranges(args.gate_dir, files, entries, top)

    edits_by_file: dict[str, list[tuple[dict[str, Any], str, str]]] = {}
    for entry, ranges in zip(entries, all_ranges, strict=True):
        for record in ranges:
            edits_by_file.setdefault(record["file"], []).append(
                (record, entry["renamed_name"], entry["original_name"])
            )

    modified_tokens = 0
    for rel_file in files:
        gate = (args.gate_dir / rel_file).read_bytes()
        file_edits = edits_by_file.get(rel_file, [])
        restored = _apply_edits(gate, file_edits)
        output_path = args.output_dir / rel_file
        _write_bytes(output_path, restored)
        modified_tokens += len(file_edits)

    return {
        "files": len(files),
        "mapping_entries": len(entries),
        "modified_tokens": modified_tokens,
    }


def _validate_range_record(record: Any, files: set[str]) -> None:
    if not isinstance(record, dict) or set(record) != {"file", "start", "end"}:
        raise ValueError("invalid mapping v3 range schema")
    if (
        not isinstance(record["file"], str)
        or record["file"] not in files
        or not isinstance(record["start"], int)
        or isinstance(record["start"], bool)
        or not isinstance(record["end"], int)
        or isinstance(record["end"], bool)
        or record["start"] < 0
        or record["start"] >= record["end"]
    ):
        raise ValueError("invalid mapping v3 range")


def _validate_occurrence_count(value: Any, expected: int, label: str) -> None:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
        or value != expected
    ):
        raise ValueError(f"{label} occurrence count mismatch")


def _validate_project_root_mapping(mapping: Any) -> dict[str, Any]:
    required_fields = {
        "version",
        "mode",
        "name_length",
        "top",
        "selected_groups",
        "selected_categories",
        "files",
        "source_files",
        "header_files",
        "compile_context",
        "closure",
        "input_manifest_sha256",
        "gate_manifest_sha256",
        "entries",
        "preserved",
    }
    if not isinstance(mapping, dict) or set(mapping) != required_fields:
        raise ValueError("invalid mapping v3 schema")
    if mapping["version"] != 3 or mapping["mode"] != "project-root":
        raise ValueError("unsupported project-root mapping version")
    name_length = mapping["name_length"]
    if (
        not isinstance(name_length, int)
        or isinstance(name_length, bool)
        or name_length < 4
    ):
        raise ValueError("invalid mapping v3 name length")
    if not isinstance(mapping["top"], str) or not mapping["top"]:
        raise ValueError("invalid mapping v3 top")

    selected_groups, selected_categories = _canonical_project_selection(
        mapping["selected_groups"]
        if isinstance(mapping["selected_groups"], list)
        else []
    )
    if mapping["selected_groups"] != selected_groups:
        raise ValueError("mapping v3 groups are not canonical")
    if mapping["selected_categories"] != selected_categories:
        raise ValueError("mapping v3 categories do not match groups")

    files = mapping["files"]
    source_files = mapping["source_files"]
    header_files = mapping["header_files"]
    if (
        not isinstance(files, list)
        or not files
        or files != sorted(set(files))
        or not all(
            isinstance(path, str)
            and path
            and not Path(path).is_absolute()
            and ".." not in Path(path).parts
            and Path(path).as_posix() == path
            for path in files
        )
        or not isinstance(source_files, list)
        or source_files != sorted(path for path in files if path.endswith(".sv"))
        or not isinstance(header_files, list)
        or header_files != sorted(path for path in files if path.endswith(".svh"))
    ):
        raise ValueError("invalid mapping v3 file lists")
    file_set = set(files)

    compile_context = mapping["compile_context"]
    if not isinstance(compile_context, dict) or set(compile_context) != {
        "compilation_unit",
        "include_dirs",
        "defines",
        "compile_order",
    }:
        raise ValueError("invalid mapping v3 compile context")
    if (
        compile_context["compilation_unit"] != "single"
        or not isinstance(compile_context["include_dirs"], list)
        or not all(isinstance(item, str) for item in compile_context["include_dirs"])
        or not isinstance(compile_context["defines"], list)
        or not all(isinstance(item, str) for item in compile_context["defines"])
        or not isinstance(compile_context["compile_order"], list)
        or compile_context["compile_order"] != [
            path for path in compile_context["compile_order"] if path in source_files
        ]
        or len(compile_context["compile_order"]) != len(source_files)
        or set(compile_context["compile_order"]) != set(source_files)
    ):
        raise ValueError("invalid mapping v3 compile context values")

    closure = mapping["closure"]
    if not isinstance(closure, dict) or set(closure) != {
        "modules",
        "interfaces",
        "files",
    }:
        raise ValueError("invalid mapping v3 closure")
    if (
        closure["files"] != files
        or not isinstance(closure["modules"], list)
        or closure["modules"] != sorted(set(closure["modules"]))
        or not isinstance(closure["interfaces"], list)
        or closure["interfaces"] != sorted(set(closure["interfaces"]))
    ):
        raise ValueError("invalid mapping v3 closure values")
    for field in ("input_manifest_sha256", "gate_manifest_sha256"):
        if not isinstance(mapping[field], str) or re.fullmatch(
            r"[0-9a-f]{64}", mapping[field]
        ) is None:
            raise ValueError("invalid mapping v3 manifest hash")

    entries = mapping["entries"]
    if not isinstance(entries, list):
        raise ValueError("invalid mapping v3 entries")
    renamed_names: set[str] = set()
    original_names: set[str] = set()
    entry_ranges: set[tuple[str, int, int]] = set()
    ranges_by_file: dict[str, list[tuple[int, int]]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {
            "category",
            "scope",
            "original_name",
            "renamed_name",
            "declaration",
            "references",
            "occurrences",
        }:
            raise ValueError("invalid mapping v3 entry schema")
        if entry["category"] not in selected_categories:
            raise ValueError("mapping v3 entry category was not selected")
        if not all(
            isinstance(entry[field], str) and entry[field]
            for field in ("scope", "original_name", "renamed_name")
        ):
            raise ValueError("invalid mapping v3 identifier")
        renamed = entry["renamed_name"]
        if (
            len(renamed) != name_length
            or re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", renamed) is None
            or renamed in inventory._SYSTEMVERILOG_KEYWORDS
            or renamed in renamed_names
        ):
            raise ValueError("invalid or duplicate mapping v3 renamed name")
        renamed_names.add(renamed)
        original_names.add(entry["original_name"])
        if not isinstance(entry["references"], list):
            raise ValueError("invalid mapping v3 references")
        ranges = [entry["declaration"], *entry["references"]]
        _validate_occurrence_count(
            entry["occurrences"], len(ranges), "mapping v3"
        )
        original_width = len(entry["original_name"].encode("utf-8"))
        for record in ranges:
            _validate_range_record(record, file_set)
            if record["end"] - record["start"] != original_width:
                raise ValueError("mapping v3 range width mismatch")
            key = (record["file"], record["start"], record["end"])
            if key in entry_ranges:
                raise ValueError("duplicate mapping v3 occurrence")
            entry_ranges.add(key)
            ranges_by_file.setdefault(record["file"], []).append(
                (record["start"], record["end"])
            )
    if renamed_names & original_names:
        raise ValueError("mapping v3 renamed name collides with an original name")
    for ranges in ranges_by_file.values():
        ordered_ranges = sorted(ranges)
        if any(
            current_start < previous_end
            for (_, previous_end), (current_start, _) in zip(
                ordered_ranges, ordered_ranges[1:]
            )
        ):
            raise ValueError("overlapping mapping v3 occurrences")
    expected_entry_order = sorted(
        entries,
        key=lambda entry: (
            entry["declaration"]["file"],
            entry["declaration"]["start"],
            entry["category"],
            entry["scope"],
            entry["original_name"],
        ),
    )
    if entries != expected_entry_order:
        raise ValueError("mapping v3 entries are not sorted")

    preserved = mapping["preserved"]
    if not isinstance(preserved, list):
        raise ValueError("invalid mapping v3 preserved inventory")
    for item in preserved:
        if not isinstance(item, dict) or set(item) != {
            "category",
            "scope",
            "name",
            "declaration",
            "references",
            "occurrences",
            "reason",
        }:
            raise ValueError("invalid mapping v3 preserved entry")
        if item["category"] not in selected_categories and not (
            isinstance(item.get("reason"), str)
            and item["reason"].startswith("top_")
        ):
            raise ValueError("preserved category was not selected")
        if not isinstance(item["references"], list) or not isinstance(
            item["reason"], str
        ):
            raise ValueError("invalid mapping v3 preserved value")
        ranges = ([] if item["declaration"] is None else [item["declaration"]]) + item[
            "references"
        ]
        _validate_occurrence_count(
            item["occurrences"], len(ranges), "preserved"
        )
        preserved_width = len(item["name"].encode("utf-8"))
        for record in ranges:
            _validate_range_record(record, file_set)
            if record["end"] - record["start"] != preserved_width:
                raise ValueError("preserved range width mismatch")
    def preserved_key(item: dict[str, Any]) -> tuple[Any, ...]:
        declaration = item["declaration"]
        return (
            item["category"],
            item["scope"],
            declaration["file"] if declaration is not None else "\uffff",
            declaration["start"] if declaration is not None else 2**63,
            item["name"],
        )

    if preserved != sorted(preserved, key=preserved_key):
        raise ValueError("mapping v3 preserved entries are not sorted")
    return mapping


def _validate_mapping_ranges_against_gate(
    mapping: dict[str, Any], gate_root: Path
) -> None:
    edits_by_file = _entry_edits_by_file(mapping["entries"])
    gate_bytes = {
        relative_file: (gate_root / relative_file).read_bytes()
        for relative_file in mapping["files"]
    }
    gold_sizes = {
        relative_file: len(content)
        - sum(delta for _, _, delta in edits_by_file.get(relative_file, []))
        for relative_file, content in gate_bytes.items()
    }
    if any(size < 0 for size in gold_sizes.values()):
        raise ValueError("mapping v3 ranges imply an invalid source file size")

    def validate_records(records: list[dict[str, Any]], gate_name: str) -> None:
        expected_gate_ranges = _expected_gate_ranges(
            records, gate_name, edits_by_file
        )
        expected_bytes = gate_name.encode("utf-8")
        for source_record, gate_record in zip(
            records, expected_gate_ranges, strict=True
        ):
            if source_record["end"] > gold_sizes[source_record["file"]]:
                raise ValueError("mapping v3 range exceeds source file bounds")
            content = gate_bytes[gate_record["file"]]
            if (
                gate_record["start"] < 0
                or gate_record["end"] > len(content)
                or content[gate_record["start"] : gate_record["end"]]
                != expected_bytes
            ):
                raise ValueError("mapping v3 range does not identify the gate token")

    for entry in mapping["entries"]:
        validate_records(
            [entry["declaration"], *entry["references"]],
            entry["renamed_name"],
        )
    for item in mapping["preserved"]:
        validate_records(
            ([] if item["declaration"] is None else [item["declaration"]])
            + item["references"],
            item["name"],
        )


def _decrypt_project_root(
    args: argparse.Namespace, mapping: dict[str, Any]
) -> dict[str, int]:
    mapping, gate_report = _validate_project_gate(mapping, args.gate_dir)
    files = mapping["files"]
    gate_entries = _audit_gate_report(
        mapping,
        gate_report,
        allow_unselected=(
            len(gate_report["inventory"]["eligible"]) > len(mapping["entries"])
        ),
    )

    edits_by_file: dict[str, list[tuple[dict[str, Any], str, str]]] = {}
    for entry, gate_entry in zip(mapping["entries"], gate_entries, strict=True):
        for record in [gate_entry["declaration"], *gate_entry["references"]]:
            edits_by_file.setdefault(record["file"], []).append(
                (record, entry["renamed_name"], entry["original_name"])
            )

    with tempfile.TemporaryDirectory(prefix="rtl-obfuscation-t028-decrypt-") as temporary:
        staging = Path(temporary) / "restored"
        for relative_file in files:
            gate = (args.gate_dir / relative_file).read_bytes()
            restored = _apply_edits(gate, edits_by_file.get(relative_file, []))
            _write_bytes(staging / relative_file, restored)
        if _project_manifest(staging, files) != mapping["input_manifest_sha256"]:
            raise ValueError("restored manifest does not match gold manifest")
        _publish_project_root_artifacts([(staging, args.output_dir)])

    return {
        "files": len(files),
        "mapping_entries": len(mapping["entries"]),
        "modified_tokens": sum(
            entry["occurrences"] for entry in mapping["entries"]
        ),
    }


def _validate_mapping_v4(mapping: Any) -> dict[str, Any]:
    required = {
        "version",
        "mode",
        "profile",
        "top",
        "requested_categories",
        "selected_categories",
        "files",
        "source_files",
        "header_files",
        "closure",
        "compile_context",
        "entries",
        "preserved",
        "skipped",
        "name_length",
        "input_manifest_sha256",
        "gate_manifest_sha256",
    }
    if not isinstance(mapping, dict) or set(mapping) != required:
        raise ValueError("invalid mapping v4 schema")
    if mapping["version"] != 4 or mapping["mode"] not in {
        category_profile.MODE_FILELIST,
        category_profile.MODE_PROJECT_ROOT,
    }:
        raise ValueError("unsupported mapping v4 version or mode")
    if mapping["profile"] not in {
        category_profile.PROFILE_SINGLE_MODULE,
        category_profile.PROFILE_MANUAL,
    }:
        raise ValueError("invalid mapping v4 profile")
    if not isinstance(mapping["top"], str) or not mapping["top"]:
        raise ValueError("invalid mapping v4 top")
    if not isinstance(mapping["requested_categories"], list) or not all(
        isinstance(item, str) for item in mapping["requested_categories"]
    ):
        raise ValueError("invalid mapping v4 requested categories")
    try:
        selection = category_profile.resolve(
            mapping["requested_categories"], mode=mapping["mode"]
        )
    except category_profile.ProfileResolutionError as error:
        raise ValueError(str(error)) from error
    if mapping["selected_categories"] != list(selection.selected_categories):
        raise ValueError("mapping v4 categories are not canonical")
    if mapping["profile"] != selection.profile:
        raise ValueError("mapping v4 profile does not match categories")

    name_length = mapping["name_length"]
    if not isinstance(name_length, int) or isinstance(name_length, bool) or name_length < 4:
        raise ValueError("invalid mapping v4 name length")
    files = mapping["files"]
    if not isinstance(files, list) or not files or len(files) != len(set(files)):
        raise ValueError("invalid mapping v4 files")
    if not all(
        isinstance(path, str)
        and path
        and not Path(path).is_absolute()
        and ".." not in Path(path).parts
        and Path(path).as_posix() == path
        for path in files
    ):
        raise ValueError("invalid mapping v4 file path")
    if mapping["source_files"] != [path for path in files if path.endswith(".sv")]:
        raise ValueError("invalid mapping v4 source files")
    if mapping["header_files"] != [path for path in files if path.endswith(".svh")]:
        raise ValueError("invalid mapping v4 header files")
    closure = mapping["closure"]
    if not isinstance(closure, dict) or set(closure) != {
        "policy", "modules", "interfaces", "files"
    }:
        raise ValueError("invalid mapping v4 closure")
    expected_policy = "filelist_bounded" if mapping["mode"] == category_profile.MODE_FILELIST else "project_discovered"
    if closure["policy"] != expected_policy:
        raise ValueError("invalid mapping v4 closure policy")
    if not isinstance(closure["files"], list) or closure["files"] != sorted(set(closure["files"])):
        raise ValueError("invalid mapping v4 closure files")
    if not set(closure["files"]).issubset(set(files)):
        raise ValueError("mapping v4 closure is outside files")
    if mapping["mode"] == category_profile.MODE_PROJECT_ROOT and closure["files"] != sorted(files):
        raise ValueError("project-root mapping v4 closure must cover files")
    if not isinstance(closure["modules"], list) or closure["modules"] != sorted(set(closure["modules"])):
        raise ValueError("invalid mapping v4 closure modules")
    if not isinstance(closure["interfaces"], list) or closure["interfaces"] != sorted(set(closure["interfaces"])):
        raise ValueError("invalid mapping v4 closure interfaces")
    compile_context = mapping["compile_context"]
    if not isinstance(compile_context, dict) or set(compile_context) != {
        "compilation_unit", "include_dirs", "defines", "compile_order"
    }:
        raise ValueError("invalid mapping v4 compile context")
    if not isinstance(compile_context["include_dirs"], list) or not isinstance(compile_context["defines"], list) or not isinstance(compile_context["compile_order"], list):
        raise ValueError("invalid mapping v4 compile context values")
    for field in ("input_manifest_sha256", "gate_manifest_sha256"):
        if not isinstance(mapping[field], str) or re.fullmatch(r"[0-9a-f]{64}", mapping[field]) is None:
            raise ValueError("invalid mapping v4 manifest hash")

    entry_ranges: set[tuple[str, int, int]] = set()
    ranges_by_file: dict[str, list[tuple[int, int]]] = {}
    renamed_names: set[str] = set()
    original_names: set[str] = set()

    def validate_item(item: Any, *, entry: bool) -> None:
        fields = (
            {"category", "scope", "original_name", "renamed_name", "declaration", "references", "occurrences"}
            if entry
            else {"category", "scope", "name", "declaration", "references", "occurrences", "reason"}
        )
        if not isinstance(item, dict) or set(item) != fields:
            raise ValueError("invalid mapping v4 entry")
        name = item["original_name"] if entry else item["name"]
        if (
            (
                item["category"] not in selection.selected_categories
                and not (
                    not entry
                    and isinstance(item.get("reason"), str)
                    and item["reason"].startswith("top_")
                )
            )
            or not isinstance(item["scope"], str)
            or not isinstance(name, str)
        ):
            raise ValueError("invalid mapping v4 item identity")
        if (
            not isinstance(item["references"], list)
            or not isinstance(item["occurrences"], int)
            or isinstance(item["occurrences"], bool)
            or item["occurrences"] < 0
        ):
            raise ValueError("invalid mapping v4 item occurrences")
        declaration = item["declaration"]
        records = ([] if declaration is None else [declaration]) + item["references"]
        if item["occurrences"] != len(records):
            raise ValueError("mapping v4 occurrence count mismatch")
        width = len(name.encode())
        for record in records:
            _validate_range_record(record, set(files))
            if record["end"] - record["start"] != width:
                raise ValueError("mapping v4 range width mismatch")
            key = (record["file"], record["start"], record["end"])
            if key in entry_ranges:
                raise ValueError("MAPPING_V4_DUPLICATE_RANGE")
            entry_ranges.add(key)
            ranges_by_file.setdefault(record["file"], []).append((record["start"], record["end"]))
        if entry:
            renamed = item["renamed_name"]
            if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", renamed) is None or len(renamed) != name_length or renamed in renamed_names or renamed in inventory._SYSTEMVERILOG_KEYWORDS:
                raise ValueError("invalid mapping v4 renamed identifier")
            renamed_names.add(renamed)
            original_names.add(name)
        else:
            if not isinstance(item["reason"], str) or not item["reason"]:
                raise ValueError("invalid mapping v4 preserved reason")

    for item in mapping["entries"]:
        validate_item(item, entry=True)
    for item in mapping["preserved"]:
        validate_item(item, entry=False)
    if renamed_names & original_names:
        raise ValueError("mapping v4 renamed name collides with original name")
    for ranges in ranges_by_file.values():
        ordered = sorted(ranges)
        if any(current_start < previous_end for (_, previous_end), (current_start, _) in zip(ordered, ordered[1:])):
            raise ValueError("MAPPING_V4_OVERLAPPING_RANGE")
    if mapping["entries"] != sorted(
        mapping["entries"],
        key=lambda item: (item["declaration"]["file"], item["declaration"]["start"], item["category"], item["scope"], item["original_name"]),
    ):
        raise ValueError("mapping v4 entries are not sorted")
    if mapping["preserved"] != sorted(
        mapping["preserved"],
        key=lambda item: (item["declaration"]["file"] if item["declaration"] else "\uffff", item["declaration"]["start"] if item["declaration"] else 2**63, item["category"], item["scope"], item["name"]),
    ):
        raise ValueError("mapping v4 preserved entries are not sorted")
    skipped = mapping["skipped"]
    if not isinstance(skipped, list):
        raise ValueError("invalid mapping v4 skipped inventory")
    skipped_files = set(mapping["files"])
    for item in skipped:
        if not isinstance(item, dict) or set(item) != {
            "file", "reason", "declaration", "references", "occurrences"
        }:
            raise ValueError("invalid mapping v4 skipped entry")
        if (
            not isinstance(item["file"], str)
            or item["file"] not in skipped_files
            or not isinstance(item["reason"], str)
            or not item["reason"]
            or item["declaration"] is not None
            or item["references"] != []
            or item["occurrences"] != 0
        ):
            raise ValueError("invalid mapping v4 skipped entry")
    if skipped != sorted(skipped, key=lambda item: (item["file"], item["reason"])):
        raise ValueError("mapping v4 skipped entries are not sorted")
    return mapping


def _decrypt_project_v4(
    args: argparse.Namespace, mapping: dict[str, Any]
) -> dict[str, int]:
    mapping = _validate_mapping_v4(mapping)
    if _project_manifest(args.gate_dir, mapping["files"]) != mapping["gate_manifest_sha256"]:
        raise ValueError("mapping v4 gate manifest does not match gate")
    _validate_mapping_ranges_against_gate(mapping, args.gate_dir)
    edits_by_file: dict[str, list[tuple[dict[str, Any], str, str]]] = {}
    for entry in mapping["entries"]:
        source_records = [entry["declaration"], *entry["references"]]
        gate_records = _expected_gate_ranges(source_records, entry["renamed_name"], _entry_edits_by_file(mapping["entries"]))
        for record in gate_records:
            edits_by_file.setdefault(record["file"], []).append((record, entry["renamed_name"], entry["original_name"]))

    with tempfile.TemporaryDirectory(prefix="rtl-obfuscation-t035-decrypt-") as temporary:
        staging = Path(temporary) / "restored"
        for relative_file in mapping["files"]:
            gate = (args.gate_dir / relative_file).read_bytes()
            _write_bytes(staging / relative_file, _apply_edits(gate, edits_by_file.get(relative_file, [])))
        if args.source_root is not None and _project_manifest(args.source_root, mapping["files"]) != mapping["input_manifest_sha256"]:
            raise ValueError("mapping v4 input manifest does not match source root")
        if args.source_root is not None and _project_manifest(staging, mapping["files"]) != _project_manifest(args.source_root, mapping["files"]):
            raise ValueError("mapping v4 restored manifest does not match source root")
        _publish_project_root_artifacts([(staging, args.output_dir)])
    return {
        "files": len(mapping["files"]),
        "mapping_entries": len(mapping["entries"]),
        "modified_tokens": sum(entry["occurrences"] for entry in mapping["entries"]),
    }


def _validate_project_gate(
    mapping: dict[str, Any], gate_dir: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    if isinstance(mapping, dict) and mapping.get("version") == 4:
        mapping = _validate_mapping_v4(mapping)
        files = mapping["files"]
        if _project_manifest(gate_dir, files) != mapping["gate_manifest_sha256"]:
            raise ValueError("mapping v4 gate manifest does not match gate")
        _validate_mapping_ranges_against_gate(mapping, gate_dir)
        gate_report, _, success = project.analyze_project(
            project_root=gate_dir,
            top=mapping["top"],
            include_dirs=mapping["compile_context"]["include_dirs"],
            defines=mapping["compile_context"]["defines"],
            categories=mapping["requested_categories"],
        )
        if not success:
            raise ValueError("gate strict project analysis failed")
        _audit_v4_gate(mapping, gate_report, gate_dir)
        return mapping, gate_report

    mapping = _validate_project_root_mapping(mapping)
    files = mapping["files"]
    if _project_manifest(gate_dir, files) != mapping["gate_manifest_sha256"]:
        raise ValueError("gate manifest does not match mapping")
    _validate_mapping_ranges_against_gate(mapping, gate_dir)
    gate_report, _, success = project.analyze_project(
        project_root=gate_dir,
        top=mapping["top"],
        include_dirs=mapping["compile_context"]["include_dirs"],
        defines=mapping["compile_context"]["defines"],
        categories=mapping["selected_groups"],
    )
    if not success:
        raise ValueError("gate strict project analysis failed")
    selection = category_profile.resolve(
        mapping["selected_groups"], mode=category_profile.MODE_PROJECT_ROOT
    )
    gate_report = _legacy_profile_report(gate_report, selection)
    # A rate-limited mapping intentionally leaves unselected eligible symbols
    # at their gold spelling.  The selected entries and all preserved ranges
    # still require the full range/AST audit.
    _audit_gate_report(
        mapping,
        gate_report,
        allow_unselected=(
            len(gate_report["inventory"]["eligible"]) > len(mapping["entries"])
        ),
    )
    return mapping, gate_report


def _formal_align(args: argparse.Namespace) -> dict[str, Any]:
    try:
        with args.map_file.open(encoding="utf-8") as stream:
            raw_mapping = json.load(stream)
    except (OSError, ValueError) as error:
        raise ValueError("invalid formal-align mapping JSON") from error
    mapping, _ = _validate_project_gate(raw_mapping, args.gate_dir)
    return formal_view.align_formal_view(
        gate_dir=args.gate_dir,
        gate_view_dir=args.gate_view_dir,
        gate_view_manifest_path=args.gate_view_manifest,
        mapping_path=args.map_file,
        mapping=mapping,
        output_dir=args.output_dir,
        manifest_path=args.manifest,
    )


def _decrypt_project(args: argparse.Namespace) -> dict[str, int]:
    with args.map_file.open(encoding="utf-8") as stream:
        mapping = json.load(stream)
    if isinstance(mapping, dict) and mapping.get("version") == 4:
        return _decrypt_project_v4(args, mapping)
    if isinstance(mapping, dict) and mapping.get("version") == 3:
        return _decrypt_project_root(args, mapping)
    return _decrypt_filelist_project(args, mapping)


def _validate_encrypt_mode(args: argparse.Namespace) -> None:
    normal_options = {
        "--output": args.output_file,
        "--map": args.map_file,
        "--metrics": args.metrics_file,
        "--category": args.category,
    }
    if args.debug_dir is not None:
        conflicts = [
            name for name, value in normal_options.items() if value is not None
        ]
        if conflicts:
            raise ValueError(
                "--debug cannot be combined with " + ", ".join(conflicts)
            )
        return
    missing = [name for name, value in normal_options.items() if value is None]
    if missing:
        raise ValueError(
            "encrypt requires --debug or all normal options: " + ", ".join(missing)
        )


def _validate_encrypt_project_mode(args: argparse.Namespace) -> None:
    if args.project_root is not None:
        normal_options = {
            "--output-dir": args.output_dir,
            "--map": args.map_file,
            "--metrics": args.metrics_file,
        }
        if args.debug_dir is not None:
            return
        missing = [name for name, value in normal_options.items() if value is None]
        if missing:
            raise ValueError(
                "encrypt-project requires --debug or all normal options: "
                + ", ".join(missing)
            )
        return
    normal_options = {
        "--output-dir": args.output_dir,
        "--map": args.map_file,
        "--metrics": args.metrics_file,
    }
    if args.debug_dir is not None:
        conflicts = [
            name for name, value in normal_options.items() if value is not None
        ]
        if args.file_map_dir is not None:
            conflicts.append("--file-map-dir")
        if conflicts:
            raise ValueError(
                "--debug cannot be combined with " + ", ".join(conflicts)
            )
        return
    missing = [name for name, value in normal_options.items() if value is None]
    if missing:
        raise ValueError(
            "encrypt-project requires --debug or all normal options: "
            + ", ".join(missing)
        )


def _path_is_within(path: Path, directory: Path) -> bool:
    try:
        path.resolve().relative_to(directory.resolve())
        return True
    except ValueError:
        return False


def _require_empty_or_missing(path: Path, option: str) -> None:
    if path.exists() and (not path.is_dir() or any(path.iterdir())):
        raise ValueError(f"{option} must be absent or an empty directory")
    ancestor = path.parent
    while not ancestor.exists():
        if ancestor.is_symlink() or ancestor == ancestor.parent:
            break
        ancestor = ancestor.parent
    if not ancestor.is_dir():
        raise ValueError(f"{option} parent must be a directory")


def _require_file_output_path(path: Path, option: str) -> None:
    if path.exists() and not path.is_file():
        raise ValueError(f"{option} must be absent or a regular file")
    ancestor = path.parent
    while not ancestor.exists():
        if ancestor.is_symlink() or ancestor == ancestor.parent:
            break
        ancestor = ancestor.parent
    if not ancestor.is_dir():
        raise ValueError(f"{option} parent must be a directory")


def _validate_project_root_paths(args: argparse.Namespace) -> None:
    root = args.project_root.resolve()
    if not root.is_dir():
        raise ValueError("--project-root must be an existing directory")
    directory_outputs = [
        ("--output-dir", args.output_dir),
        ("--debug", args.debug_dir),
        ("--file-map-dir", args.file_map_dir),
    ]
    for option, path in directory_outputs:
        if path is None:
            continue
        if _path_is_within(path, root):
            raise ValueError(f"{option} must be outside --project-root")
        _require_empty_or_missing(path, option)
    input_rtl = {
        (root / relative).resolve() for relative in project._discover_files(root)
    }
    for option, path in (("--map", args.map_file), ("--metrics", args.metrics_file)):
        if path is None:
            continue
        _require_file_output_path(path, option)
        if path.resolve() in input_rtl:
            raise ValueError(f"{option} cannot overwrite input RTL")

    paths = [
        (name, path.resolve())
        for name, path in (
            ("--output-dir", args.output_dir),
            ("--debug", args.debug_dir),
            ("--file-map-dir", args.file_map_dir),
            ("--map", args.map_file),
            ("--metrics", args.metrics_file),
        )
        if path is not None
    ]
    for index, (first_name, first) in enumerate(paths):
        for second_name, second in paths[index + 1 :]:
            if first == second:
                raise ValueError(f"{first_name} conflicts with {second_name}")
            if _path_is_within(second, first) or _path_is_within(first, second):
                raise ValueError(f"{first_name} conflicts with {second_name}")


def _validate_decrypt_project_paths(args: argparse.Namespace) -> None:
    if not args.gate_dir.is_dir():
        raise ValueError("--gate-dir must be an existing directory")
    if not args.map_file.is_file():
        raise ValueError("--map must be an existing file")
    if _path_is_within(args.output_dir, args.gate_dir) or _path_is_within(
        args.gate_dir, args.output_dir
    ):
        raise ValueError("--output-dir conflicts with --gate-dir")
    if _path_is_within(args.map_file, args.output_dir):
        raise ValueError("--output-dir conflicts with --map")
    _require_empty_or_missing(args.output_dir, "--output-dir")


def _validate_mode_invocation(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    encryption_rate = getattr(args, "encryption_rate", None)
    if encryption_rate is not None:
        if getattr(args, "debug_dir", None) is not None:
            parser.error("ENCRYPTION_RATE_DEBUG_UNSUPPORTED")
        try:
            _parse_encryption_rate(encryption_rate)
        except ValueError as error:
            parser.error(str(error))
    if args.operation == "encrypt-project":
        has_filelist = args.filelist is not None
        has_project_root = args.project_root is not None
        if has_filelist == has_project_root:
            parser.error("exactly one of --filelist and --project-root is required")
        if has_project_root:
            if args.source_root is not None:
                parser.error("--source-root cannot be used with --project-root")
            try:
                category_profile.resolve(
                    args.category or (), mode=category_profile.MODE_PROJECT_ROOT
                )
            except category_profile.ProfileResolutionError as error:
                parser.error(str(error))
            conflicts = []
            if args.debug_dir is not None:
                for option, value in (
                    ("--category", args.category),
                    ("--output-dir", args.output_dir),
                    ("--map", args.map_file),
                    ("--metrics", args.metrics_file),
                    ("--file-map-dir", args.file_map_dir),
                ):
                    if value is not None:
                        conflicts.append(option)
            if conflicts:
                parser.error("--debug cannot be combined with " + ", ".join(conflicts))
            if args.debug_dir is None and any(
                value is None
                for value in (args.output_dir, args.map_file, args.metrics_file)
            ):
                parser.error(
                    "project-root mode requires --debug or --output-dir, --map, and --metrics"
                )
            try:
                _validate_project_root_paths(args)
            except ValueError as error:
                parser.error(str(error))
        else:
            if args.debug_dir is None:
                try:
                    category_profile.resolve(
                        args.category or (), mode=category_profile.MODE_FILELIST
                    )
                except category_profile.ProfileResolutionError as error:
                    parser.error(str(error))
                except ValueError as error:
                    parser.error(str(error))
            if args.source_root is None:
                parser.error("--source-root is required with --filelist")
            if args.include_dirs or args.defines:
                parser.error("--include-dir and --define require --project-root")
    elif args.operation == "encrypt":
        if args.debug_dir is None:
            try:
                category_profile.resolve(
                    args.category or (), mode=category_profile.MODE_SINGLE_FILE
                )
            except (ValueError, category_profile.ProfileResolutionError) as error:
                parser.error(str(error))
    elif args.operation == "decrypt-project":
        try:
            _validate_decrypt_project_paths(args)
        except ValueError as error:
            parser.error(str(error))
        if args.source_root is None:
            try:
                with args.map_file.open(encoding="utf-8") as stream:
                    version = json.load(stream).get("version")
            except (OSError, ValueError, AttributeError):
                version = None
            if version not in (3, 4):
                parser.error("--source-root is required for mapping v2")
    elif args.operation == "formal-view":
        try:
            formal_view._validate_paths(
                args.project_root, args.output_dir, args.manifest
            )
        except ValueError as error:
            parser.error(str(error))
    elif args.operation == "formal-align":
        try:
            formal_view._validate_alignment_paths(
                gate_dir=args.gate_dir,
                gate_view_dir=args.gate_view_dir,
                gate_view_manifest=args.gate_view_manifest,
                mapping_path=args.map_file,
                output_dir=args.output_dir,
                manifest_path=args.manifest,
            )
        except ValueError as error:
            parser.error(str(error))


def _create_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Rewrite or restore selected SystemVerilog identifiers."
    )
    operations = parser.add_subparsers(dest="operation", required=True)

    encrypt = operations.add_parser("encrypt")
    encrypt.add_argument("--input", required=True, type=Path, dest="input_file")
    encrypt.add_argument(
        "--output",
        required=False,
        type=Path,
        dest="output_file",
        help="Gate file; required unless --debug is used.",
    )
    encrypt.add_argument(
        "--map",
        required=False,
        type=Path,
        dest="map_file",
        help="Mapping file; required unless --debug is used.",
    )
    encrypt.add_argument(
        "--metrics",
        required=False,
        type=Path,
        dest="metrics_file",
        help="Metrics file; required unless --debug is used.",
    )
    encrypt.add_argument(
        "--debug",
        required=False,
        type=Path,
        dest="debug_dir",
        help="Run all 13 single-file categories independently under this directory.",
    )
    encrypt.add_argument(
        "--encryption-rate",
        required=False,
        dest="encryption_rate",
        help="Target unique physical-line encryption rate in (0, 1].",
    )
    encrypt.add_argument(
        "--category",
        required=False,
        action="append",
        help="One category for normal mode; do not combine with --debug.",
        choices=(
            *inventory._SUPPORTED_CATEGORIES,
            "struct",
            "interface",
            "all",
        ),
    )
    encrypt.add_argument(
        "--name-length",
        required=True,
        type=inventory._positive_name_length,
        dest="name_length",
    )


    encrypt_project = operations.add_parser("encrypt-project")
    encrypt_project.add_argument("--filelist", required=False, type=Path, dest="filelist")
    encrypt_project.add_argument("--source-root", required=False, type=Path, dest="source_root")
    encrypt_project.add_argument(
        "--project-root", required=False, type=Path, dest="project_root"
    )
    encrypt_project.add_argument(
        "--include-dir", action="append", default=[], dest="include_dirs"
    )
    encrypt_project.add_argument(
        "--define", action="append", default=[], dest="defines"
    )
    encrypt_project.add_argument(
        "--output-dir",
        required=False,
        type=Path,
        dest="output_dir",
        help="Gate directory; required unless --debug is used.",
    )
    encrypt_project.add_argument(
        "--map",
        required=False,
        type=Path,
        dest="map_file",
        help="Global mapping file; required unless --debug is used.",
    )
    encrypt_project.add_argument(
        "--metrics",
        required=False,
        type=Path,
        dest="metrics_file",
        help="Metrics file; required unless --debug is used.",
    )
    encrypt_project.add_argument(
        "--encryption-rate",
        required=False,
        dest="encryption_rate",
        help="Target unique physical-line encryption rate in (0, 1].",
    )
    encrypt_project.add_argument(
        "--debug",
        required=False,
        type=Path,
        dest="debug_dir",
        help="Run all categories for the selected project input mode.",
    )
    encrypt_project.add_argument(
        "--file-map-dir", required=False, type=Path, dest="file_map_dir"
    )
    encrypt_project.add_argument("--top", required=True, type=str, dest="top")
    encrypt_project.add_argument(
        "--category",
        required=False,
        action="append",
        dest="category",
        help="Repeatable categories for normal mode; do not combine with --debug.",
        choices=(
            *inventory._SUPPORTED_CATEGORIES,
            "all",
            "struct",
            "interface",
        ),
    )
    encrypt_project.add_argument(
        "--name-length",
        required=True,
        type=inventory._positive_name_length,
        dest="name_length",
    )

    decrypt_project = operations.add_parser("decrypt-project")
    decrypt_project.add_argument("--gate-dir", required=True, type=Path, dest="gate_dir")
    decrypt_project.add_argument("--source-root", required=False, type=Path, dest="source_root")
    decrypt_project.add_argument("--map", required=True, type=Path, dest="map_file")
    decrypt_project.add_argument("--output-dir", required=True, type=Path, dest="output_dir")

    decrypt = operations.add_parser("decrypt")
    decrypt.add_argument("--input", required=True, type=Path, dest="input_file")
    decrypt.add_argument("--output", required=True, type=Path, dest="output_file")
    decrypt.add_argument("--map", required=True, type=Path, dest="map_file")

    inspect_project = operations.add_parser("inspect-project")
    inspect_project.add_argument(
        "--project-root", required=True, type=Path, dest="project_root"
    )
    inspect_project.add_argument("--top", required=True)
    inspect_project.add_argument("--report", required=True, type=Path, dest="report")
    inspect_project.add_argument(
        "--include-dir", action="append", default=[], dest="include_dirs"
    )
    inspect_project.add_argument(
        "--define", action="append", default=[], dest="defines"
    )
    inspect_project.add_argument(
        "--category",
        action="append",
        default=[],
        choices=(
            *category_profile.CANONICAL_CATEGORIES,
            *category_profile.ALIASES,
            "all",
        ),
        dest="categories",
    )

    formal = operations.add_parser("formal-view")
    formal.add_argument(
        "--project-root", required=True, type=Path, dest="project_root"
    )
    formal.add_argument("--top", required=True)
    formal.add_argument(
        "--output-dir", required=True, type=Path, dest="output_dir"
    )
    formal.add_argument("--manifest", required=True, type=Path)
    formal.add_argument(
        "--include-dir", action="append", default=[], dest="include_dirs"
    )
    formal.add_argument("--define", action="append", default=[], dest="defines")

    align = operations.add_parser("formal-align")
    align.add_argument("--gate-dir", required=True, type=Path, dest="gate_dir")
    align.add_argument(
        "--gate-view-dir", required=True, type=Path, dest="gate_view_dir"
    )
    align.add_argument(
        "--gate-view-manifest",
        required=True,
        type=Path,
        dest="gate_view_manifest",
    )
    align.add_argument("--map", required=True, type=Path, dest="map_file")
    align.add_argument(
        "--output-dir", required=True, type=Path, dest="output_dir"
    )
    align.add_argument("--manifest", required=True, type=Path)
    return parser


def main() -> int:
    parser = _create_argument_parser()
    args = parser.parse_args()
    if args.operation == "inspect-project":
        try:
            _, summary, success = project.inspect_project(
                project_root=args.project_root,
                top=args.top,
                report_path=args.report,
                include_dirs=args.include_dirs,
                defines=args.defines,
                categories=args.categories,
            )
        except ValueError as error:
            parser.error(str(error))
        print(json.dumps(summary, separators=(",", ":")))
        return 0 if success else 1
    _validate_mode_invocation(parser, args)
    try:
        if args.operation == "encrypt":
            _validate_encrypt_mode(args)
            summary = (
                _debug_encrypt(args) if args.debug_dir is not None else _encrypt(args)
            )
        elif args.operation == "decrypt":
            summary = _decrypt(args)
        elif args.operation == "encrypt-project":
            _validate_encrypt_project_mode(args)
            summary = (
                _debug_encrypt_project(args)
                if args.debug_dir is not None
                else _encrypt_project(args)
            )
        elif args.operation == "formal-view":
            summary = formal_view.build_formal_view(
                project_root=args.project_root,
                top=args.top,
                output_dir=args.output_dir,
                manifest_path=args.manifest,
                include_dirs=args.include_dirs,
                defines=args.defines,
            )
        elif args.operation == "formal-align":
            summary = _formal_align(args)
        else:
            summary = _decrypt_project(args)
    except (OSError, RuntimeError, ValueError) as error:
        parser.exit(1, f"error: {error}\n")

    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
