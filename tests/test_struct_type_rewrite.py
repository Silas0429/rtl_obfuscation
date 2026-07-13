"""Black-box tests for struct_types category rewriting."""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


class StructTypeRewriteCliTest(unittest.TestCase):
    def test_struct_type_encrypt_decrypt_round_trip(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        gold = Path("tests/fixtures/t013_struct_type.sv")
        gold_bytes = gold.read_bytes()

        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            gate = tmp_path / "gate.sv"
            restored = tmp_path / "restored.sv"
            mapping_file = tmp_path / "mapping.json"
            metrics_file = tmp_path / "metrics.json"

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
                    "struct_types",
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
            entries = mapping["entries"]
            self.assertEqual(len(entries), 1)

            entry = entries[0]
            self.assertEqual(entry["category"], "struct_types")
            self.assertEqual(entry["scope"], "t013_struct_type")
            self.assertEqual(entry["original_name"], "header_t")
            self.assertEqual(entry["declaration"], {
                "file": "tests/fixtures/t013_struct_type.sv",
                "start": 192,
                "end": 200,
            })
            self.assertEqual(len(entry["references"]), 2)
            self.assertEqual(entry["references"][0], {
                "file": "tests/fixtures/t013_struct_type.sv",
                "start": 207,
                "end": 215,
            })
            self.assertEqual(entry["references"][1], {
                "file": "tests/fixtures/t013_struct_type.sv",
                "start": 235,
                "end": 243,
            })

            renamed = entry["renamed_name"]
            self.assertTrue(re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{7}", renamed))
            self.assertNotIn(renamed.encode(), gold_bytes)

            for record in [entry["declaration"], *entry["references"]]:
                self.assertEqual(
                    gold_bytes[record["start"]:record["end"]],
                    b"header_t",
                )

            gate_bytes = gate.read_bytes()
            self.assertNotIn(b"header_t", gate_bytes)
            self.assertIn(renamed.encode(), gate_bytes)

            metrics = json.loads(metrics_file.read_text(encoding="utf-8"))
            self.assertEqual(metrics["symbols"], {
                "renamed": 1, "eligible": 1, "coverage": 1.0,
            })
            self.assertEqual(metrics["occurrences"], {
                "renamed": 3, "eligible": 3, "coverage": 1.0,
            })
            self.assertEqual(metrics["plaintext_leakage_rate"], 0.0)
            self.assertEqual(metrics["effective_coverage"], 1.0)

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
