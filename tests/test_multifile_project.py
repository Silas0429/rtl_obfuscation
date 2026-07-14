"""Black-box tests for T015 multi-file project infrastructure."""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


class MultifileProjectCliTest(unittest.TestCase):
    def test_encrypt_decrypt_project_round_trip(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        filelist = Path("tests/fixtures/t015_multi_file/design.f")
        source_root = Path("tests/fixtures/t015_multi_file")

        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            gate_dir = tmp_path / "gate"
            restored_dir = tmp_path / "restored"
            mapping_file = tmp_path / "mapping.json"
            metrics_file = tmp_path / "metrics.json"

            encrypt = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "rtl_obfuscator.rewrite",
                    "encrypt-project",
                    "--filelist",
                    str(filelist),
                    "--source-root",
                    str(source_root),
                    "--output-dir",
                    str(gate_dir),
                    "--map",
                    str(mapping_file),
                    "--metrics",
                    str(metrics_file),
                    "--top",
                    "t015_top",
                    "--category",
                    "all",
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
                {"files": 2, "mapping_entries": 4, "modified_tokens": 10},
            )

            mapping = json.loads(mapping_file.read_text(encoding="utf-8"))
            self.assertEqual(mapping["version"], 2)
            self.assertEqual(mapping["name_length"], 8)
            self.assertEqual(mapping["files"], ["child.sv", "top.sv"])
            entries = mapping["entries"]
            self.assertEqual(len(entries), 4)

            # Verify declarations match expected offsets
            expected_decls = {
                ("signals", "stored_value"): ("child.sv", 131, 143),
                ("signals", "temp_value"): ("child.sv", 156, 166),
                ("typedefs", "byte_t"): ("child.sv", 111, 117),
                ("instances", "u_child"): ("top.sv", 100, 107),
            }
            for entry in entries:
                key = (entry["category"], entry["original_name"])
                self.assertIn(key, expected_decls)
                exp_file, exp_start, exp_end = expected_decls[key]
                self.assertEqual(entry["declaration"]["file"], exp_file)
                self.assertEqual(entry["declaration"]["start"], exp_start)
                self.assertEqual(entry["declaration"]["end"], exp_end)
                self.assertTrue(
                    re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{7}", entry["renamed_name"])
                )

            # Verify all source slices match original names
            for entry in entries:
                rel_file = entry["declaration"]["file"]
                source_bytes = (source_root / rel_file).read_bytes()
                for record in [entry["declaration"], *entry["references"]]:
                    self.assertEqual(
                        source_bytes[record["start"]:record["end"]],
                        entry["original_name"].encode("utf-8"),
                    )

            # Verify gate files exist and original names are gone
            for rel_file in mapping["files"]:
                gate_file = gate_dir / rel_file
                self.assertTrue(gate_file.exists())
                gate_bytes = gate_file.read_bytes()
                for entry in entries:
                    if entry["declaration"]["file"] == rel_file:
                        self.assertNotIn(
                            entry["original_name"].encode("utf-8"), gate_bytes
                        )

            # Verify metrics hard constraints
            metrics = json.loads(metrics_file.read_text(encoding="utf-8"))
            self.assertEqual(metrics["symbols"], {
                "renamed": 4, "eligible": 4, "coverage": 1.0,
            })
            self.assertEqual(metrics["occurrences"], {
                "renamed": 10, "eligible": 10, "coverage": 1.0,
            })
            self.assertEqual(metrics["plaintext_leakage_rate"], 0.0)
            self.assertEqual(metrics["effective_coverage"], 1.0)

            # Decrypt
            decrypt = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "rtl_obfuscator.rewrite",
                    "decrypt-project",
                    "--gate-dir",
                    str(gate_dir),
                    "--source-root",
                    str(source_root),
                    "--map",
                    str(mapping_file),
                    "--output-dir",
                    str(restored_dir),
                ],
                cwd=repository,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(decrypt.returncode, 0, decrypt.stderr)
            self.assertEqual(
                json.loads(decrypt.stdout),
                {"files": 2, "mapping_entries": 4, "modified_tokens": 10},
            )

            # Verify restored files match gold
            for rel_file in mapping["files"]:
                gold_bytes = (source_root / rel_file).read_bytes()
                restored_bytes = (restored_dir / rel_file).read_bytes()
                self.assertEqual(restored_bytes, gold_bytes)


if __name__ == "__main__":
    unittest.main()
