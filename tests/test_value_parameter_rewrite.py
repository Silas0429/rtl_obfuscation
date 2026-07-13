"""Black-box round-trip test for the T005 value parameter rewrite."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


class ValueParameterRewriteCliTest(unittest.TestCase):
    def test_value_parameter_encrypt_decrypt_round_trip(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        relative_gold = Path("tests/fixtures/t005_value_parameter.sv")
        gold_bytes = (repository / relative_gold).read_bytes()

        with TemporaryDirectory() as temporary_directory:
            output_directory = Path(temporary_directory) / "nested" / "t005"
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
                {"files": 1, "mapping_entries": 1, "modified_tokens": 2},
            )

            mapping = json.loads(mapping_file.read_text(encoding="utf-8"))
            self.assertEqual(len(mapping["entries"]), 1)
            entry = mapping["entries"][0]
            self.assertEqual(entry["category"], "parameters")
            self.assertEqual(entry["scope"], "t005_value_parameter")
            self.assertEqual(entry["original_name"], "INVERT")
            self.assertRegex(entry["renamed_name"], r"^[A-Za-z][A-Za-z0-9_]{7}$")
            self.assertEqual(
                entry["declaration"],
                {"file": str(relative_gold), "start": 111, "end": 117},
            )
            self.assertEqual(
                entry["references"],
                [{"file": str(relative_gold), "start": 250, "end": 256}],
            )
            for item in [entry["declaration"], *entry["references"]]:
                self.assertEqual(gold_bytes[item["start"] : item["end"]], b"INVERT")
            self.assertTrue(
                {"input_a", "output_y", "selected_value"}.isdisjoint(
                    {item["original_name"] for item in mapping["entries"]}
                )
            )

            renamed_name = entry["renamed_name"].encode("utf-8")
            expected_gate = gold_bytes.replace(b"INVERT", renamed_name)
            self.assertEqual(gate.read_bytes(), expected_gate)
            self.assertEqual(gate.read_bytes().count(renamed_name), 2)
            self.assertNotIn(b"INVERT", gate.read_bytes())

            self.assertEqual(
                json.loads(metrics_file.read_text(encoding="utf-8")),
                {
                    "affected_lines": {"changed": 2, "total": 10, "rate": 0.2},
                    "symbols": {"renamed": 1, "eligible": 1, "coverage": 1.0},
                    "occurrences": {
                        "renamed": 2,
                        "eligible": 2,
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
                {"files": 1, "mapping_entries": 1, "modified_tokens": 2},
            )
            self.assertEqual(restored.read_bytes(), gold_bytes)


if __name__ == "__main__":
    unittest.main()
