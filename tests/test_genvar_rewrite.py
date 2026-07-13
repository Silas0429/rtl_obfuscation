"""Black-box round-trip test for the T008 genvar rewrite."""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


def _expected_gate(source: bytes, entry: dict[str, object]) -> bytes:
    records = [entry["declaration"], *entry["references"]]
    replacement = entry["renamed_name"].encode("utf-8")
    result = source
    for record in sorted(records, key=lambda item: item["start"], reverse=True):
        result = result[: record["start"]] + replacement + result[record["end"] :]
    return result


class GenvarRewriteCliTest(unittest.TestCase):
    def test_genvar_encrypt_decrypt_round_trip(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        relative_gold = Path("rtl_samples/07_generate_loop.sv")
        gold_bytes = (repository / relative_gold).read_bytes()

        with TemporaryDirectory() as temporary_directory:
            output_directory = Path(temporary_directory) / "nested" / "t008"
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
                    "genvars",
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
                {"files": 1, "mapping_entries": 1, "modified_tokens": 5},
            )

            mapping = json.loads(mapping_file.read_text(encoding="utf-8"))
            self.assertEqual(len(mapping["entries"]), 1)
            entry = mapping["entries"][0]
            self.assertEqual(entry["category"], "genvars")
            self.assertEqual(entry["scope"], "sample07_generate_loop")
            self.assertEqual(entry["original_name"], "bit_index")
            self.assertRegex(entry["renamed_name"], r"^[A-Za-z][A-Za-z0-9_]{7}$")
            input_identifiers = set(
                re.findall(rb"[A-Za-z_][A-Za-z0-9_$]*", gold_bytes)
            )
            self.assertNotIn(entry["renamed_name"].encode("utf-8"), input_identifiers)
            self.assertEqual(
                entry["declaration"],
                {"file": str(relative_gold), "start": 316, "end": 325},
            )
            self.assertEqual(
                entry["references"],
                [
                    {"file": str(relative_gold), "start": 331, "end": 340},
                    {"file": str(relative_gold), "start": 350, "end": 359},
                    {"file": str(relative_gold), "start": 412, "end": 421},
                    {"file": str(relative_gold), "start": 436, "end": 445},
                ],
            )
            for record in [entry["declaration"], *entry["references"]]:
                self.assertEqual(
                    gold_bytes[record["start"] : record["end"]], b"bit_index"
                )
            self.assertTrue(
                {
                    "WIDTH",
                    "generate_mask",
                    "masked_data",
                    "input_data",
                    "mask_enable",
                    "output_data",
                }.isdisjoint(item["original_name"] for item in mapping["entries"])
            )

            renamed_name = entry["renamed_name"].encode("utf-8")
            self.assertEqual(gate.read_bytes(), _expected_gate(gold_bytes, entry))
            self.assertEqual(gate.read_bytes().count(renamed_name), 5)
            self.assertNotIn(b"bit_index", gate.read_bytes())
            self.assertEqual(
                json.loads(metrics_file.read_text(encoding="utf-8")),
                {
                    "affected_lines": {
                        "changed": 2,
                        "total": 13,
                        "rate": 0.15384615384615385,
                    },
                    "symbols": {"renamed": 1, "eligible": 1, "coverage": 1.0},
                    "occurrences": {
                        "renamed": 5,
                        "eligible": 5,
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
                {"files": 1, "mapping_entries": 1, "modified_tokens": 5},
            )
            self.assertEqual(restored.read_bytes(), gold_bytes)


if __name__ == "__main__":
    unittest.main()
