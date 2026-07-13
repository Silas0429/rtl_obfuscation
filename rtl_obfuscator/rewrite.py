"""Rewrite and restore internal SystemVerilog signal identifiers."""

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
    ranges: list[dict[str, Any]],
    expected: str,
    replacement: str,
) -> bytes:
    expected_bytes = expected.encode("utf-8")
    replacement_bytes = replacement.encode("utf-8")
    positions = sorted((item["start"], item["end"]) for item in ranges)

    if len(positions) != len(set(positions)):
        raise ValueError("duplicate source edits")
    if any(
        current_start < previous_end
        for (_, previous_end), (current_start, _) in zip(
            positions, positions[1:]
        )
    ):
        raise ValueError("overlapping source edits")
    for start, end in positions:
        if source[start:end] != expected_bytes:
            raise ValueError("source edit does not match the expected identifier")

    rewritten = source
    for start, end in reversed(positions):
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
        "plaintext_leakage_rate": leaked_occurrences / occurrence_count,
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
        args.input_file, args.name_length, include_ranges=True
    )
    entries = mapping["entries"]
    source = args.input_file.read_bytes()
    gate = source
    modified_tokens = 0
    for entry in entries:
        ranges = _entry_ranges(entry)
        gate = _apply_edits(
            gate,
            ranges,
            entry["original_name"],
            entry["renamed_name"],
        )
        modified_tokens += len(ranges)

    _write_bytes(args.output_file, gate)
    _write_json(args.map_file, mapping)
    _write_json(args.metrics_file, _metrics(source, gate, entries))
    return _summary(len(entries), modified_tokens)


def _validate_mapping(mapping: Any) -> list[dict[str, Any]]:
    if not isinstance(mapping, dict) or set(mapping) != {
        "version",
        "name_length",
        "entries",
    }:
        raise ValueError("invalid mapping schema")
    if mapping["version"] != 1 or not isinstance(mapping["name_length"], int):
        raise ValueError("unsupported mapping version or name length")
    entries = mapping["entries"]
    if not isinstance(entries, list) or len(entries) != 1:
        raise ValueError("mapping must contain exactly one entry")

    required_entry_fields = {
        "category",
        "scope",
        "original_name",
        "renamed_name",
        "declaration",
        "references",
    }
    entry = entries[0]
    if not isinstance(entry, dict) or set(entry) != required_entry_fields:
        raise ValueError("invalid mapping entry schema")
    if entry["category"] != "signals":
        raise ValueError("unsupported mapping category")
    if not all(
        isinstance(entry[field], str)
        for field in ("scope", "original_name", "renamed_name")
    ):
        raise ValueError("invalid mapping identifier")

    range_records = _entry_ranges(entry)
    if len(range_records) != 3:
        raise ValueError("mapping must contain three identifier ranges")
    for record in range_records:
        if not isinstance(record, dict) or set(record) != {"file", "start", "end"}:
            raise ValueError("invalid mapping range schema")
        if (
            not isinstance(record["file"], str)
            or not isinstance(record["start"], int)
            or not isinstance(record["end"], int)
            or record["start"] >= record["end"]
        ):
            raise ValueError("invalid mapping range")
    return entries


def _gate_ranges(
    input_file: Path, entry: dict[str, Any]
) -> list[dict[str, Any]]:
    syntax_tree = pyslang.syntax.SyntaxTree.fromFile(str(input_file))
    compilation = pyslang.ast.Compilation()
    compilation.addSyntaxTree(syntax_tree)
    if any(diagnostic.isError() for diagnostic in compilation.getAllDiagnostics()):
        raise ValueError("gate contains SystemVerilog errors")

    signals, _ = inventory._collect_signals(compilation)
    matches = [
        signal
        for signal in signals
        if signal.name == entry["renamed_name"]
        and signal.declaringDefinition.name == entry["scope"]
    ]
    if len(matches) != 1:
        raise ValueError("mapped signal was not found uniquely in gate RTL")

    range_entry: dict[str, Any] = {}
    inventory._add_ranges(
        [range_entry], matches, compilation, input_file
    )
    ranges = _entry_ranges(range_entry)
    if len(ranges) != len(_entry_ranges(entry)):
        raise ValueError("gate occurrence count does not match mapping")
    return ranges


def _decrypt(args: argparse.Namespace) -> dict[str, int]:
    with args.map_file.open(encoding="utf-8") as stream:
        mapping = json.load(stream)
    entries = _validate_mapping(mapping)
    gate = args.input_file.read_bytes()
    restored = gate
    modified_tokens = 0
    for entry in entries:
        ranges = _gate_ranges(args.input_file, entry)
        restored = _apply_edits(
            restored,
            ranges,
            entry["renamed_name"],
            entry["original_name"],
        )
        modified_tokens += len(ranges)

    _write_bytes(args.output_file, restored)
    return _summary(len(entries), modified_tokens)


def _create_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Rewrite or restore internal SystemVerilog signals."
    )
    operations = parser.add_subparsers(dest="operation", required=True)

    encrypt = operations.add_parser("encrypt")
    encrypt.add_argument("--input", required=True, type=Path, dest="input_file")
    encrypt.add_argument("--output", required=True, type=Path, dest="output_file")
    encrypt.add_argument("--map", required=True, type=Path, dest="map_file")
    encrypt.add_argument("--metrics", required=True, type=Path, dest="metrics_file")
    encrypt.add_argument("--category", required=True, choices=("signals",))
    encrypt.add_argument(
        "--name-length",
        required=True,
        type=inventory._positive_name_length,
        dest="name_length",
    )

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
            summary = _encrypt(args)
        else:
            summary = _decrypt(args)
    except (OSError, RuntimeError, ValueError) as error:
        parser.exit(1, f"error: {error}\n")

    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
