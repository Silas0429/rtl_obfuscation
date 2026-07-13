"""Black-box round-trip test for the T004 internal net rewrite."""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


class SignalNetRewriteCliTest(unittest.TestCase):
    def test_internal_net_encrypt_decrypt_round_trip(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        relative_gold = Path("tests/fixtures/t004_internal_net.sv")
        gold_bytes = (repository / relative_gold).read_bytes()

        with TemporaryDirectory() as temporary_directory:
            output_directory = Path(temporary_directory) / "nested" / "t004"
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
                    "signals",
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
            self.assertEqual(len(mapping["entries"]), 1)
            entry = mapping["entries"][0]
            self.assertEqual(entry["category"], "signals")
            self.assertEqual(entry["scope"], "t004_internal_net")
            self.assertEqual(entry["original_name"], "combined_net")
            self.assertRegex(entry["renamed_name"], r"^[A-Za-z][A-Za-z0-9_]{7}$")
            input_identifiers = set(
                re.findall(
                    rb"[A-Za-z_][A-Za-z0-9_$]*",
                    gold_bytes,
                )
            )
            self.assertNotIn(entry["renamed_name"].encode("utf-8"), input_identifiers)
            self.assertEqual(
                entry["declaration"],
                {"file": str(relative_gold), "start": 170, "end": 182},
            )
            self.assertEqual(
                entry["references"],
                [
                    {"file": str(relative_gold), "start": 196, "end": 208},
                    {"file": str(relative_gold), "start": 252, "end": 264},
                ],
            )
            for item in [entry["declaration"], *entry["references"]]:
                self.assertEqual(
                    gold_bytes[item["start"] : item["end"]], b"combined_net"
                )
            self.assertNotIn(
                "output_y",
                {item["original_name"] for item in mapping["entries"]},
            )

            renamed_name = entry["renamed_name"].encode("utf-8")
            expected_gate = gold_bytes.replace(b"combined_net", renamed_name)
            self.assertEqual(gate.read_bytes(), expected_gate)
            self.assertEqual(gate.read_bytes().count(renamed_name), 3)
            self.assertNotIn(b"combined_net", gate.read_bytes())

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
