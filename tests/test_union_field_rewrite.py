"""Black-box tests for union_fields category rewriting."""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


class UnionFieldRewriteCliTest(unittest.TestCase):
    def test_union_field_encrypt_decrypt_round_trip(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        gold = Path("tests/fixtures/t014_union_field.sv")
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
                    "union_fields",
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
                {"files": 1, "mapping_entries": 2, "modified_tokens": 4},
            )

            mapping = json.loads(mapping_file.read_text(encoding="utf-8"))
            self.assertEqual(mapping["version"], 1)
            self.assertEqual(mapping["name_length"], 8)
            entries = mapping["entries"]
            self.assertEqual(len(entries), 2)

            expected = [
                ("word", 143, 147, [(282, 286)]),
                ("reversed", 170, 178, [(362, 370)]),
            ]

            for entry, (name, decl_start, decl_end, refs) in zip(entries, expected):
                self.assertEqual(entry["category"], "union_fields")
                self.assertEqual(entry["scope"], "t014_union_field")
                self.assertEqual(entry["original_name"], name)
                self.assertTrue(re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{7}", entry["renamed_name"]))
                self.assertNotIn(entry["renamed_name"].encode(), gold_bytes)
                self.assertEqual(entry["declaration"], {
                    "file": "tests/fixtures/t014_union_field.sv",
                    "start": decl_start,
                    "end": decl_end,
                })
                self.assertEqual(entry["references"], [
                    {"file": "tests/fixtures/t014_union_field.sv", "start": s, "end": e}
                    for s, e in refs
                ])
                for record in [entry["declaration"], *entry["references"]]:
                    self.assertEqual(
                        gold_bytes[record["start"]:record["end"]],
                        name.encode(),
                    )

            gate_bytes = gate.read_bytes()
            for entry in entries:
                self.assertNotIn(entry["original_name"].encode(), gate_bytes)
                self.assertEqual(
                    gate_bytes.count(entry["renamed_name"].encode()),
                    1 + len(entry["references"]),
                )

            metrics = json.loads(metrics_file.read_text(encoding="utf-8"))
            self.assertEqual(metrics["affected_lines"], {
                "changed": 4, "total": 16, "rate": 0.25,
            })
            self.assertEqual(metrics["symbols"], {
                "renamed": 2, "eligible": 2, "coverage": 1.0,
            })
            self.assertEqual(metrics["occurrences"], {
                "renamed": 4, "eligible": 4, "coverage": 1.0,
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
                {"files": 1, "mapping_entries": 2, "modified_tokens": 4},
            )
            self.assertEqual(restored.read_bytes(), gold_bytes)


if __name__ == "__main__":
    unittest.main()
