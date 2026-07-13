"""Black-box tests for one-pass rewriting of all supported categories."""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


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


class AllCategoryRewriteCliTest(unittest.TestCase):
    def _round_trip(
        self,
        repository: Path,
        gold: Path,
        output_directory: Path,
        expected_summary: dict[str, int],
    ) -> tuple[list[dict[str, object]], dict[str, object]]:
        gate = output_directory / "gate.sv"
        restored = output_directory / "restored.sv"
        mapping_file = output_directory / "mapping.json"
        metrics_file = output_directory / "metrics.json"
        gold_bytes = (repository / gold).read_bytes()

        encrypt = subprocess.run(
            [
                sys.executable,
                "-m",
                "rtl_obfuscator.rewrite",
                "encrypt",
                "--input",
                str(gold),
                "--output",
                str(gate),
                "--map",
                str(mapping_file),
                "--metrics",
                str(metrics_file),
                "--category",
                "all",
                "--name-length",
                "8",
            ],
            cwd=repository,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(encrypt.returncode, 0, encrypt.stderr)
        self.assertEqual(json.loads(encrypt.stdout), expected_summary)

        mapping = json.loads(mapping_file.read_text(encoding="utf-8"))
        self.assertEqual(mapping["version"], 1)
        self.assertEqual(mapping["name_length"], 8)
        entries = mapping["entries"]
        self.assertEqual(len(entries), expected_summary["mapping_entries"])
        self.assertEqual(
            sum(1 + len(entry["references"]) for entry in entries),
            expected_summary["modified_tokens"],
        )
        for entry in entries:
            self.assertNotEqual(entry["category"], "all")
            for record in [entry["declaration"], *entry["references"]]:
                self.assertEqual(
                    gold_bytes[record["start"] : record["end"]],
                    entry["original_name"].encode("utf-8"),
                )
        self.assertEqual(gate.read_bytes(), _expected_gate(gold_bytes, entries))

        decrypt = subprocess.run(
            [
                sys.executable,
                "-m",
                "rtl_obfuscator.rewrite",
                "decrypt",
                "--input",
                str(gate),
                "--output",
                str(restored),
                "--map",
                str(mapping_file),
            ],
            cwd=repository,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(decrypt.returncode, 0, decrypt.stderr)
        self.assertEqual(json.loads(decrypt.stdout), expected_summary)
        self.assertEqual(restored.read_bytes(), gold_bytes)
        return entries, json.loads(metrics_file.read_text(encoding="utf-8"))

    def test_demo_all_categories_one_pass(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        gold = Path("rtl_samples/11_supported_obfuscation.sv")
        expected_groups = [
            (
                "signals",
                [
                    "generated_data",
                    "function_result",
                    "selected_data",
                    "transformed_data",
                    "observed_data",
                    "width_enabled",
                    "current_state",
                ],
            ),
            ("parameters", ["WIDTH", "XOR_MASK", "ACTIVE_BITS", "RESET_VALUE"]),
            ("enum_values", ["STATE_IDLE", "STATE_MASK", "STATE_PASS"]),
            ("genvars", ["bit_index"]),
            ("functions", ["apply_mask"]),
            ("tasks", ["select_value"]),
            (
                "arguments",
                ["function_data", "task_data", "task_mode", "task_result"],
            ),
            ("generate_blocks", ["generate_input"]),
            ("typedefs", ["state_t"]),
        ]

        with TemporaryDirectory() as temporary_directory:
            entries, metrics = self._round_trip(
                repository,
                gold,
                Path(temporary_directory) / "demo",
                {"files": 1, "mapping_entries": 23, "modified_tokens": 63},
            )

        expected_categories = [
            category for category, names in expected_groups for _ in names
        ]
        expected_names = [name for _, names in expected_groups for name in names]
        self.assertEqual(
            [entry["category"] for entry in entries], expected_categories
        )
        self.assertEqual(
            [entry["original_name"] for entry in entries], expected_names
        )
        renamed_names = [entry["renamed_name"] for entry in entries]
        self.assertEqual(len(set(renamed_names)), 23)
        self.assertTrue(
            all(
                re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{7}", name)
                for name in renamed_names
            )
        )
        input_identifiers = set(
            re.findall(
                rb"[A-Za-z_][A-Za-z0-9_$]*", (repository / gold).read_bytes()
            )
        )
        self.assertTrue(
            input_identifiers.isdisjoint(
                name.encode("utf-8") for name in renamed_names
            )
        )
        self.assertEqual(
            metrics,
            {
                "affected_lines": {
                    "changed": 41,
                    "total": 61,
                    "rate": 0.6721311475409836,
                },
                "symbols": {"renamed": 23, "eligible": 23, "coverage": 1.0},
                "occurrences": {
                    "renamed": 63,
                    "eligible": 63,
                    "coverage": 1.0,
                },
                "plaintext_leakage_rate": 0.0,
                "effective_coverage": 1.0,
            },
        )

    def test_function_return_variable_owned_only_by_function(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        with TemporaryDirectory() as temporary_directory:
            entries, _ = self._round_trip(
                repository,
                Path("tests/fixtures/t009_function_argument.sv"),
                Path(temporary_directory) / "function",
                {"files": 1, "mapping_entries": 2, "modified_tokens": 5},
            )

        self.assertEqual(
            [
                (
                    entry["category"],
                    entry["original_name"],
                    1 + len(entry["references"]),
                )
                for entry in entries
            ],
            [
                ("functions", "transform_value", 3),
                ("arguments", "function_data", 2),
            ],
        )
        self.assertFalse(
            any(
                entry["category"] == "signals"
                and entry["original_name"] == "transform_value"
                for entry in entries
            )
        )


if __name__ == "__main__":
    unittest.main()
