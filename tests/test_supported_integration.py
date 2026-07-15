"""Integration test for a selected single-file category pipeline."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

import pyslang


def _expected_gate(source: bytes, entries: list[dict[str, object]]) -> bytes:
    edits = [
        (record, entry["renamed_name"].encode("utf-8"))
        for entry in entries
        for record in [entry["declaration"], *entry["references"]]
    ]
    result = source
    for record, replacement in sorted(
        edits, key=lambda item: item[0]["start"], reverse=True
    ):
        result = result[: record["start"]] + replacement + result[record["end"] :]
    return result


class SupportedCategoriesIntegrationTest(unittest.TestCase):
    def test_seven_category_pipeline_and_reverse_restore(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        relative_gold = Path("rtl_samples/11_supported_obfuscation.sv")
        gold = repository / relative_gold
        gold_bytes = gold.read_bytes()
        cases = [
            ("signals", 10, 37, 30, 30 / 86),
            ("parameters", 4, 10, 9, 9 / 86),
            ("enum_values", 3, 8, 8, 8 / 86),
            ("genvars", 1, 5, 2, 2 / 86),
            ("functions", 1, 2, 2, 2 / 86),
            ("tasks", 1, 2, 2, 2 / 86),
            ("arguments", 4, 9, 8, 8 / 86),
        ]

        with TemporaryDirectory() as temporary_directory:
            output_root = Path(temporary_directory)
            direct_output = output_root / "direct_parameters"
            direct_gate = direct_output / "gate.sv"
            direct_mapping_file = direct_output / "mapping.json"
            direct_metrics_file = direct_output / "metrics.json"
            direct_encrypt = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "rtl_obfuscator.rewrite",
                    "encrypt",
                    "--input",
                    str(relative_gold),
                    "--output",
                    str(direct_gate),
                    "--map",
                    str(direct_mapping_file),
                    "--metrics",
                    str(direct_metrics_file),
                    "--category",
                    "parameters",
                    "--name-length",
                    "8",
                ],
                cwd=repository,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(direct_encrypt.returncode, 0, direct_encrypt.stderr)
            self.assertEqual(
                json.loads(direct_encrypt.stdout),
                {"files": 1, "mapping_entries": 4, "modified_tokens": 10},
            )
            direct_mapping = json.loads(
                direct_mapping_file.read_text(encoding="utf-8")
            )
            direct_entries = direct_mapping["entries"]
            self.assertEqual(
                [entry["original_name"] for entry in direct_entries],
                ["WIDTH", "XOR_MASK", "ACTIVE_BITS", "RESET_VALUE"],
            )
            self.assertNotIn(
                "bit_index", [entry["original_name"] for entry in direct_entries]
            )
            expected_ranges = [
                ((59, 64), [(300, 305)]),
                ((96, 104), [(1210, 1218), (2566, 2574)]),
                ((286, 297), [(1886, 1897)]),
                ((334, 345), [(1507, 1518), (2614, 2625)]),
            ]
            for entry, (declaration, references) in zip(
                direct_entries, expected_ranges, strict=True
            ):
                self.assertEqual(
                    (
                        entry["declaration"]["start"],
                        entry["declaration"]["end"],
                    ),
                    declaration,
                )
                self.assertEqual(
                    [
                        (record["start"], record["end"])
                        for record in entry["references"]
                    ],
                    references,
                )

            current = gold
            mappings: dict[str, Path] = {}
            total_entries = 0
            total_tokens = 0

            for category, entry_count, token_count, changed_lines, rate in cases:
                output_directory = output_root / category
                gate = output_directory / "gate.sv"
                mapping_file = output_directory / "mapping.json"
                metrics_file = output_directory / "metrics.json"
                source_bytes = current.read_bytes()
                encrypt = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "rtl_obfuscator.rewrite",
                        "encrypt",
                        "--input",
                        str(current),
                        "--output",
                        str(gate),
                        "--map",
                        str(mapping_file),
                        "--metrics",
                        str(metrics_file),
                        "--category",
                        category,
                        "--name-length",
                        "8",
                    ],
                    cwd=repository,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(encrypt.returncode, 0, encrypt.stderr)
                self.assertEqual(
                    json.loads(encrypt.stdout),
                    {
                        "files": 1,
                        "mapping_entries": entry_count,
                        "modified_tokens": token_count,
                    },
                )

                mapping = json.loads(mapping_file.read_text(encoding="utf-8"))
                entries = mapping["entries"]
                self.assertEqual(len(entries), entry_count)
                self.assertTrue(
                    all(entry["category"] == category for entry in entries)
                )
                self.assertEqual(
                    sum(1 + len(entry["references"]) for entry in entries),
                    token_count,
                )
                for entry in entries:
                    for record in [entry["declaration"], *entry["references"]]:
                        self.assertEqual(
                            source_bytes[record["start"] : record["end"]],
                            entry["original_name"].encode("utf-8"),
                        )
                self.assertEqual(
                    gate.read_bytes(), _expected_gate(source_bytes, entries)
                )

                metrics = json.loads(metrics_file.read_text(encoding="utf-8"))
                self.assertEqual(
                    metrics,
                    {
                        "affected_lines": {
                            "changed": changed_lines,
                            "total": 86,
                            "rate": rate,
                        },
                        "symbols": {
                            "renamed": entry_count,
                            "eligible": entry_count,
                            "coverage": 1.0,
                        },
                        "occurrences": {
                            "renamed": token_count,
                            "eligible": token_count,
                            "coverage": 1.0,
                        },
                        "plaintext_leakage_rate": 0.0,
                        "effective_coverage": 1.0,
                    },
                )

                if category == "parameters":
                    self.assertEqual(
                        [entry["original_name"] for entry in entries],
                        ["WIDTH", "XOR_MASK", "ACTIVE_BITS", "RESET_VALUE"],
                    )
                    self.assertNotIn(
                        "bit_index",
                        [entry["original_name"] for entry in entries],
                    )
                elif category == "genvars":
                    self.assertEqual(
                        [entry["original_name"] for entry in entries], ["bit_index"]
                    )

                mappings[category] = mapping_file
                current = gate
                total_entries += entry_count
                total_tokens += token_count

            self.assertEqual((total_entries, total_tokens), (24, 73))
            final_tree = pyslang.syntax.SyntaxTree.fromFile(str(current))
            final_compilation = pyslang.ast.Compilation()
            final_compilation.addSyntaxTree(final_tree)
            self.assertFalse(
                any(
                    diagnostic.isError()
                    for diagnostic in final_compilation.getAllDiagnostics()
                )
            )

            for category, *_ in reversed(cases):
                restored = output_root / "restored" / f"{category}.sv"
                decrypt = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "rtl_obfuscator.rewrite",
                        "decrypt",
                        "--input",
                        str(current),
                        "--output",
                        str(restored),
                        "--map",
                        str(mappings[category]),
                    ],
                    cwd=repository,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(decrypt.returncode, 0, decrypt.stderr)
                current = restored

            self.assertEqual(current.read_bytes(), gold_bytes)


if __name__ == "__main__":
    unittest.main()
