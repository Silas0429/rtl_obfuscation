"""Black-box round-trip tests for the T009 subroutine batch."""

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


class SubroutineRewriteCliTest(unittest.TestCase):
    def test_subroutine_batch_encrypt_decrypt_round_trip(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        cases = [
            {
                "label": "functions",
                "gold": Path("tests/fixtures/t009_function_argument.sv"),
                "category": "functions",
                "entries": [
                    (
                        "t009_function_argument",
                        "transform_value",
                        (141, 156),
                        [(213, 228), (295, 310)],
                    )
                ],
                "tokens": 3,
                "preserved": ["function_data", "input_data", "output_data"],
                "metrics": (3, 11, 0.2727272727272727, 1, 3),
            },
            {
                "label": "function_arguments",
                "gold": Path("tests/fixtures/t009_function_argument.sv"),
                "category": "arguments",
                "entries": [
                    (
                        "t009_function_argument",
                        "function_data",
                        (184, 197),
                        [(231, 244)],
                    )
                ],
                "tokens": 2,
                "preserved": ["transform_value", "input_data", "output_data"],
                "metrics": (2, 11, 0.18181818181818182, 1, 2),
            },
            {
                "label": "tasks",
                "gold": Path("tests/fixtures/t009_task_argument.sv"),
                "category": "tasks",
                "entries": [
                    (
                        "t009_task_argument",
                        "drive_value",
                        (121, 132),
                        [(301, 312)],
                    )
                ],
                "tokens": 2,
                "preserved": [
                    "task_data",
                    "task_result",
                    "input_data",
                    "output_data",
                ],
                "metrics": (2, 14, 0.14285714285714285, 1, 2),
            },
            {
                "label": "task_arguments",
                "gold": Path("tests/fixtures/t009_task_argument.sv"),
                "category": "arguments",
                "entries": [
                    (
                        "t009_task_argument",
                        "task_data",
                        (161, 170),
                        [(240, 249)],
                    ),
                    (
                        "t009_task_argument",
                        "task_result",
                        (199, 210),
                        [(226, 237)],
                    ),
                ],
                "tokens": 4,
                "preserved": ["drive_value", "input_data", "output_data"],
                "metrics": (3, 14, 0.21428571428571427, 2, 4),
            },
        ]

        with TemporaryDirectory() as temporary_directory:
            for case in cases:
                with self.subTest(path=case["label"]):
                    output_directory = Path(temporary_directory) / case["label"]
                    gate = output_directory / "gate.sv"
                    restored = output_directory / "restored.sv"
                    mapping_file = output_directory / "mapping.json"
                    metrics_file = output_directory / "metrics.json"
                    gold = case["gold"]
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
                            case["category"],
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
                            "mapping_entries": len(case["entries"]),
                            "modified_tokens": case["tokens"],
                        },
                    )

                    mapping = json.loads(mapping_file.read_text(encoding="utf-8"))
                    self.assertEqual(len(mapping["entries"]), len(case["entries"]))
                    input_identifiers = set(
                        re.findall(rb"[A-Za-z_][A-Za-z0-9_$]*", gold_bytes)
                    )
                    for entry, expected in zip(
                        mapping["entries"], case["entries"], strict=True
                    ):
                        scope, original_name, declaration, references = expected
                        self.assertEqual(entry["category"], case["category"])
                        self.assertEqual(entry["scope"], scope)
                        self.assertEqual(entry["original_name"], original_name)
                        self.assertRegex(
                            entry["renamed_name"], r"^[A-Za-z][A-Za-z0-9_]{7}$"
                        )
                        self.assertNotIn(
                            entry["renamed_name"].encode("utf-8"), input_identifiers
                        )
                        self.assertEqual(
                            entry["declaration"],
                            {
                                "file": str(gold),
                                "start": declaration[0],
                                "end": declaration[1],
                            },
                        )
                        self.assertEqual(
                            entry["references"],
                            [
                                {"file": str(gold), "start": start, "end": end}
                                for start, end in references
                            ],
                        )
                        for record in [entry["declaration"], *entry["references"]]:
                            self.assertEqual(
                                gold_bytes[record["start"] : record["end"]],
                                original_name.encode("utf-8"),
                            )

                    gate_bytes = gate.read_bytes()
                    self.assertEqual(
                        gate_bytes, _expected_gate(gold_bytes, mapping["entries"])
                    )
                    for entry in mapping["entries"]:
                        self.assertNotIn(
                            entry["original_name"].encode("utf-8"), gate_bytes
                        )
                        self.assertEqual(
                            gate_bytes.count(entry["renamed_name"].encode("utf-8")),
                            1 + len(entry["references"]),
                        )
                    for preserved in case["preserved"]:
                        self.assertIn(preserved.encode("utf-8"), gate_bytes)

                    changed, total, rate, symbols, occurrences = case["metrics"]
                    self.assertEqual(
                        json.loads(metrics_file.read_text(encoding="utf-8")),
                        {
                            "affected_lines": {
                                "changed": changed,
                                "total": total,
                                "rate": rate,
                            },
                            "symbols": {
                                "renamed": symbols,
                                "eligible": symbols,
                                "coverage": 1.0,
                            },
                            "occurrences": {
                                "renamed": occurrences,
                                "eligible": occurrences,
                                "coverage": 1.0,
                            },
                            "plaintext_leakage_rate": 0.0,
                            "effective_coverage": 1.0,
                        },
                    )

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
                    self.assertEqual(
                        json.loads(decrypt.stdout),
                        {
                            "files": 1,
                            "mapping_entries": len(case["entries"]),
                            "modified_tokens": case["tokens"],
                        },
                    )
                    self.assertEqual(restored.read_bytes(), gold_bytes)


if __name__ == "__main__":
    unittest.main()
