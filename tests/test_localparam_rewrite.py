"""Black-box round-trip test for T007-B module localparams."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


def _expected_gate(source: bytes, entries: list[dict[str, object]]) -> bytes:
    edits = [
        (record["start"], record["end"], entry["renamed_name"].encode("utf-8"))
        for entry in entries
        for record in [entry["declaration"], *entry["references"]]
    ]
    result = source
    for start, end, replacement in sorted(edits, reverse=True):
        result = result[:start] + replacement + result[end:]
    return result


class LocalparamRewriteCliTest(unittest.TestCase):
    def test_localparams_encrypt_decrypt_round_trip(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        relative_gold = Path("rtl_samples/05_case_statement.sv")
        gold_bytes = (repository / relative_gold).read_bytes()

        with TemporaryDirectory() as temporary_directory:
            output_directory = Path(temporary_directory) / "nested" / "localparams"
            gate = output_directory / "gate.sv"
            restored = output_directory / "restored.sv"
            mapping_file = output_directory / "mapping.json"
            metrics_file = output_directory / "metrics.json"
            encrypt = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "rtl_obfuscator.rewrite",
                    "encrypt",
                    "--input",
                    str(relative_gold),
                    "--output",
                    str(gate),
                    "--map",
                    str(mapping_file),
                    "--metrics",
                    str(metrics_file),
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
            self.assertEqual(encrypt.returncode, 0, encrypt.stderr)
            self.assertEqual(
                json.loads(encrypt.stdout),
                {"files": 1, "mapping_entries": 4, "modified_tokens": 8},
            )

            mapping = json.loads(mapping_file.read_text(encoding="utf-8"))
            entries = mapping["entries"]
            self.assertEqual(
                [entry["original_name"] for entry in entries],
                ["OP_ADD", "OP_SUB", "OP_AND", "OP_OR"],
            )
            expected_ranges = [
                ((264, 270), [(499, 505)]),
                ((307, 313), [(557, 563)]),
                ((350, 356), [(615, 621)]),
                ((393, 398), [(673, 678)]),
            ]
            for entry, (declaration, references) in zip(
                entries, expected_ranges, strict=True
            ):
                self.assertEqual(entry["category"], "parameters")
                self.assertEqual(entry["scope"], "sample05_case_statement")
                self.assertEqual(
                    (entry["declaration"]["start"], entry["declaration"]["end"]),
                    declaration,
                )
                self.assertEqual(
                    [(record["start"], record["end"]) for record in entry["references"]],
                    references,
                )

            self.assertEqual(gate.read_bytes(), _expected_gate(gold_bytes, entries))
            self.assertEqual(
                json.loads(metrics_file.read_text(encoding="utf-8")),
                {
                    "affected_lines": {
                        "changed": 8,
                        "total": 22,
                        "rate": 0.36363636363636365,
                    },
                    "symbols": {"renamed": 4, "eligible": 4, "coverage": 1.0},
                    "occurrences": {"renamed": 8, "eligible": 8, "coverage": 1.0},
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
                {"files": 1, "mapping_entries": 4, "modified_tokens": 8},
            )
            self.assertEqual(restored.read_bytes(), gold_bytes)


if __name__ == "__main__":
    unittest.main()
