"""Black-box round-trip and mapping validation tests for T007-A."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


def _expected_gate(source: bytes, entries: list[dict[str, object]]) -> bytes:
    edits = []
    for entry in entries:
        records = [entry["declaration"], *entry["references"]]
        edits.extend(
            (record["start"], record["end"], entry["renamed_name"].encode("utf-8"))
            for record in records
        )
    result = source
    for start, end, replacement in sorted(edits, reverse=True):
        result = result[:start] + replacement + result[end:]
    return result


class MultiSignalRewriteCliTest(unittest.TestCase):
    def test_multi_signal_encrypt_decrypt_and_mapping_validation(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        relative_gold = Path("tests/fixtures/t007_multi_signal.sv")
        gold_bytes = (repository / relative_gold).read_bytes()

        with TemporaryDirectory() as temporary_directory:
            output_directory = Path(temporary_directory) / "nested" / "signals"
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
                {"files": 1, "mapping_entries": 4, "modified_tokens": 12},
            )

            mapping = json.loads(mapping_file.read_text(encoding="utf-8"))
            entries = mapping["entries"]
            self.assertEqual(
                [entry["original_name"] for entry in entries],
                ["logic_value", "legacy_reg", "wire_value", "tri_value"],
            )
            self.assertTrue(
                {"input_a", "input_b", "output_y"}.isdisjoint(
                    entry["original_name"] for entry in entries
                )
            )
            expected_ranges = {
                "logic_value": ((185, 196), [(373, 384), (419, 430)]),
                "legacy_reg": ((208, 218), [(406, 416), (463, 473)]),
                "wire_value": ((230, 240), [(275, 285), (330, 340)]),
                "tri_value": ((252, 261), [(318, 327), (387, 396)]),
            }
            for entry in entries:
                self.assertEqual(entry["category"], "signals")
                self.assertEqual(entry["scope"], "t007_multi_signal")
                self.assertRegex(entry["renamed_name"], r"^[A-Za-z][A-Za-z0-9_]{7}$")
                declaration, references = expected_ranges[entry["original_name"]]
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
                        "changed": 9,
                        "total": 17,
                        "rate": 0.5294117647058824,
                    },
                    "symbols": {"renamed": 4, "eligible": 4, "coverage": 1.0},
                    "occurrences": {"renamed": 12, "eligible": 12, "coverage": 1.0},
                    "plaintext_leakage_rate": 0.0,
                    "effective_coverage": 1.0,
                },
            )

            decrypt_command = [
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
            ]
            decrypt = subprocess.run(
                decrypt_command,
                cwd=repository,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(decrypt.returncode, 0, decrypt.stderr)
            self.assertEqual(
                json.loads(decrypt.stdout),
                {"files": 1, "mapping_entries": 4, "modified_tokens": 12},
            )
            self.assertEqual(restored.read_bytes(), gold_bytes)

            broken_schema = deepcopy(mapping)
            del broken_schema["entries"][1]["references"]
            mapping_file.write_text(json.dumps(broken_schema), encoding="utf-8")
            invalid_schema = subprocess.run(
                decrypt_command,
                cwd=repository,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(invalid_schema.returncode, 0)

            duplicate_name = deepcopy(mapping)
            duplicate_name["entries"][-1]["renamed_name"] = duplicate_name["entries"][0][
                "renamed_name"
            ]
            mapping_file.write_text(json.dumps(duplicate_name), encoding="utf-8")
            invalid_duplicate = subprocess.run(
                decrypt_command,
                cwd=repository,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(invalid_duplicate.returncode, 0)


if __name__ == "__main__":
    unittest.main()
