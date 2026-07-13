"""Black-box round-trip test for the T003 variable rewrite CLI."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


class VariableRewriteCliTest(unittest.TestCase):
    def test_encrypt_decrypt_round_trip(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        relative_gold = Path("rtl_samples/01_continuous_assign.sv")
        gold_bytes = (repository / relative_gold).read_bytes()

        with TemporaryDirectory() as temporary_directory:
            output_directory = Path(temporary_directory) / "nested" / "t003"
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
                    "variables",
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
                {"files": 1, "mapping_entries": 1, "modified_tokens": 3},
            )

            mapping = json.loads(mapping_file.read_text(encoding="utf-8"))
            self.assertEqual(mapping["version"], 1)
            self.assertEqual(mapping["name_length"], 8)
            self.assertEqual(len(mapping["entries"]), 1)
            entry = mapping["entries"][0]
            self.assertEqual(entry["original_name"], "and_result")
            self.assertEqual(
                entry["declaration"],
                {"file": str(relative_gold), "start": 202, "end": 212},
            )
            self.assertEqual(
                entry["references"],
                [
                    {"file": str(relative_gold), "start": 226, "end": 236},
                    {"file": str(relative_gold), "start": 280, "end": 290},
                ],
            )

            renamed_name = entry["renamed_name"].encode("utf-8")
            self.assertEqual(
                gate.read_bytes(), gold_bytes.replace(b"and_result", renamed_name)
            )
            self.assertEqual(gate.read_bytes().count(renamed_name), 3)
            self.assertNotIn(b"and_result", gate.read_bytes())

            self.assertEqual(
                json.loads(metrics_file.read_text(encoding="utf-8")),
                {
                    "affected_lines": {
                        "changed": 3,
                        "total": 9,
                        "rate": 0.3333333333333333,
                    },
                    "symbols": {"renamed": 1, "eligible": 1, "coverage": 1.0},
                    "occurrences": {
                        "renamed": 3,
                        "eligible": 3,
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
                {"files": 1, "mapping_entries": 1, "modified_tokens": 3},
            )
            self.assertEqual(restored.read_bytes(), gold_bytes)


if __name__ == "__main__":
    unittest.main()
