"""Black-box tests for declaration-only hierarchy name rewriting."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


class HierarchyNameRewriteCliTest(unittest.TestCase):
    def _round_trip(
        self,
        gold: Path,
        category: str,
        original_name: str,
        declaration: tuple[int, int],
        expected_metrics: dict[str, object],
    ) -> None:
        repository = Path(__file__).resolve().parents[1]
        gold_bytes = (repository / gold).read_bytes()

        with TemporaryDirectory() as temporary_directory:
            output_directory = Path(temporary_directory) / category
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
                    str(gold),
                    "--output",
                    str(gate),
                    "--map",
                    str(mapping_file),
                    "--metrics",
                    str(metrics_file),
                    "--category",
                    category,
                    "--name-length",
                    "8",
                ],
                cwd=repository,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(encrypt.returncode, 0, encrypt.stderr)
            summary = {"files": 1, "mapping_entries": 1, "modified_tokens": 1}
            self.assertEqual(json.loads(encrypt.stdout), summary)

            mapping = json.loads(mapping_file.read_text(encoding="utf-8"))
            self.assertEqual(len(mapping["entries"]), 1)
            entry = mapping["entries"][0]
            self.assertEqual(entry["category"], category)
            self.assertEqual(entry["original_name"], original_name)
            self.assertEqual(
                (entry["declaration"]["start"], entry["declaration"]["end"]),
                declaration,
            )
            self.assertEqual(entry["declaration"]["file"], str(gold))
            self.assertEqual(entry["references"], [])
            self.assertEqual(len(entry["renamed_name"]), 8)

            start, end = declaration
            expected_gate = (
                gold_bytes[:start]
                + entry["renamed_name"].encode("utf-8")
                + gold_bytes[end:]
            )
            self.assertEqual(gate.read_bytes(), expected_gate)
            self.assertEqual(
                json.loads(metrics_file.read_text(encoding="utf-8")),
                expected_metrics,
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
            self.assertEqual(json.loads(decrypt.stdout), summary)
            self.assertEqual(restored.read_bytes(), gold_bytes)

    def test_module_instance_declaration_only(self) -> None:
        self._round_trip(
            Path("rtl_samples/06_module_instance.sv"),
            "instances",
            "inverter_instance",
            (437, 454),
            {
                "affected_lines": {
                    "changed": 1,
                    "total": 19,
                    "rate": 0.05263157894736842,
                },
                "symbols": {"renamed": 1, "eligible": 1, "coverage": 1.0},
                "occurrences": {"renamed": 1, "eligible": 1, "coverage": 1.0},
                "plaintext_leakage_rate": 0.0,
                "effective_coverage": 1.0,
            },
        )

    def test_generate_block_declaration_only(self) -> None:
        self._round_trip(
            Path("rtl_samples/07_generate_loop.sv"),
            "generate_blocks",
            "generate_mask",
            (371, 384),
            {
                "affected_lines": {
                    "changed": 1,
                    "total": 13,
                    "rate": 0.07692307692307693,
                },
                "symbols": {"renamed": 1, "eligible": 1, "coverage": 1.0},
                "occurrences": {"renamed": 1, "eligible": 1, "coverage": 1.0},
                "plaintext_leakage_rate": 0.0,
                "effective_coverage": 1.0,
            },
        )


if __name__ == "__main__":
    unittest.main()
