"""Rewrite and restore selected SystemVerilog identifiers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

import pyslang

from rtl_obfuscator import inventory


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

    return {
        "affected_lines": {
            "changed": len(changed_lines),
            "total": len(effective_lines),
            "rate": len(changed_lines) / len(effective_lines),
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


def _summary(mapping_entries: int, modified_tokens: int) -> dict[str, int]:
    return {
        "files": 1,
        "mapping_entries": mapping_entries,
        "modified_tokens": modified_tokens,
    }


def _encrypt(args: argparse.Namespace) -> dict[str, int]:
    mapping = inventory._build_inventory(
        args.input_file,
        args.name_length,
        args.category,
        include_ranges=True,
    )
    entries = mapping["entries"]
    source = args.input_file.read_bytes()
    edits: list[tuple[dict[str, Any], str, str]] = []
    for entry in entries:
        edits.extend(
            (record, entry["original_name"], entry["renamed_name"])
            for record in _entry_ranges(entry)
        )
    gate = _apply_edits(source, edits)
    modified_tokens = len(edits)

    _write_bytes(args.output_file, gate)
    _write_json(args.map_file, mapping)
    _write_json(args.metrics_file, _metrics(source, gate, entries))
    return _summary(len(entries), modified_tokens)


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
    if not isinstance(entries, list) or not entries:
        raise ValueError("mapping must contain at least one entry")

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

    return {
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


def _write_project_file_maps(
    mapping: dict[str, Any], file_map_dir: Path
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


def _encrypt_project(args: argparse.Namespace) -> dict[str, int]:
    mapping = inventory._build_project_inventory(
        args.filelist,
        args.source_root,
        args.name_length,
        args.category,
        args.top,
    )
    entries = mapping["entries"]
    relative_files = mapping["files"]

    edits_by_file: dict[str, list[tuple[dict[str, Any], str, str]]] = {}
    for entry in entries:
        for record in _entry_ranges(entry):
            edits_by_file.setdefault(record["file"], []).append(
                (record, entry["original_name"], entry["renamed_name"])
            )

    for rel_file in relative_files:
        source = (args.source_root / rel_file).read_bytes()
        file_edits = edits_by_file.get(rel_file, [])
        gate = _apply_edits(source, file_edits)
        output_path = args.output_dir / rel_file
        _write_bytes(output_path, gate)

    # Copy filelist to output directory
    filelist_name = args.filelist.name
    filelist_content = args.filelist.read_text(encoding="utf-8")
    _write_bytes(args.output_dir / filelist_name, filelist_content.encode("utf-8"))

    modified_tokens = sum(len(edits) for edits in edits_by_file.values())

    _write_json(args.map_file, mapping)
    _write_json(args.metrics_file, _project_metrics(
        args.source_root, args.output_dir, relative_files, entries
    ))
    if args.file_map_dir is not None:
        _write_project_file_maps(mapping, args.file_map_dir)
    return {
        "files": len(relative_files),
        "mapping_entries": len(entries),
        "modified_tokens": modified_tokens,
    }


def _debug_encrypt_project(args: argparse.Namespace) -> dict[str, Any]:
    runs: list[dict[str, Any]] = []
    for category in inventory._SUPPORTED_CATEGORIES:
        category_root = args.debug_dir / category
        summary = _encrypt_project(
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
    if not isinstance(entries, list) or not entries:
        raise ValueError("project mapping must contain at least one entry")

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


def _decrypt_project(args: argparse.Namespace) -> dict[str, int]:
    with args.map_file.open(encoding="utf-8") as stream:
        mapping = json.load(stream)
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
    normal_options = {
        "--output-dir": args.output_dir,
        "--map": args.map_file,
        "--metrics": args.metrics_file,
        "--category": args.category,
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
        "--category",
        required=False,
        help="One category for normal mode; do not combine with --debug.",
        choices=(
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
    encrypt_project.add_argument("--filelist", required=True, type=Path, dest="filelist")
    encrypt_project.add_argument("--source-root", required=True, type=Path, dest="source_root")
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
        "--debug",
        required=False,
        type=Path,
        dest="debug_dir",
        help="Run all 19 project categories independently under this directory.",
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
            "modules",
            "ports",
            "interfaces",
            "interface_instances",
            "interface_ports",
            "modports",
            "all",
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
    decrypt_project.add_argument("--source-root", required=True, type=Path, dest="source_root")
    decrypt_project.add_argument("--map", required=True, type=Path, dest="map_file")
    decrypt_project.add_argument("--output-dir", required=True, type=Path, dest="output_dir")

    decrypt = operations.add_parser("decrypt")
    decrypt.add_argument("--input", required=True, type=Path, dest="input_file")
    decrypt.add_argument("--output", required=True, type=Path, dest="output_file")
    decrypt.add_argument("--map", required=True, type=Path, dest="map_file")
    return parser


def main() -> int:
    parser = _create_argument_parser()
    args = parser.parse_args()
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
        else:
            summary = _decrypt_project(args)
    except (OSError, RuntimeError, ValueError) as error:
        parser.exit(1, f"error: {error}\n")

    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
