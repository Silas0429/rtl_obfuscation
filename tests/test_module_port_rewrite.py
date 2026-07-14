"""Black-box tests for T016 module and port renaming."""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


class ModulePortRewriteCliTest(unittest.TestCase):
    def test_module_port_encrypt_decrypt_round_trip(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        filelist = Path("tests/fixtures/t016_module_port/design.f")
        source_root = Path("tests/fixtures/t016_module_port")

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
                    "t016_top",
                    "--category",
                    "modules",
                    "--category",
                    "ports",
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
                {"files": 2, "mapping_entries": 3, "modified_tokens": 8},
            )

            mapping = json.loads(mapping_file.read_text(encoding="utf-8"))
            self.assertEqual(mapping["version"], 2)
            self.assertEqual(mapping["name_length"], 8)
            self.assertEqual(mapping["files"], ["child.sv", "top.sv"])
            self.assertEqual(mapping["top"], "t016_top")
            entries = mapping["entries"]
            self.assertEqual(len(entries), 3)

            # Verify declarations match expected offsets
            expected_decls = {
                ("modules", "t016_child"): ("child.sv", 7, 17),
                ("ports", "data_in"): ("child.sv", 43, 50),
                ("ports", "data_out"): ("child.sv", 75, 83),
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
                for record in [entry["declaration"], *entry["references"]]:
                    source_bytes = (source_root / record["file"]).read_bytes()
                    self.assertEqual(
                        source_bytes[record["start"]:record["end"]],
                        entry["original_name"].encode("utf-8"),
                    )

            # Verify gate files: original names gone, top module preserved
            gate_child = (gate_dir / "child.sv").read_bytes()
            gate_top = (gate_dir / "top.sv").read_bytes()
            self.assertNotIn(b"t016_child", gate_child)
            self.assertNotIn(b"t016_child", gate_top)
            self.assertNotIn(b"data_in", gate_child)
            self.assertNotIn(b"data_out", gate_child)
            self.assertIn(b"t016_top", gate_top)
            self.assertIn(b"data_in", gate_top)  # top ports preserved
            self.assertIn(b"data_out", gate_top)  # top ports preserved

            # Verify metrics hard constraints
            metrics = json.loads(metrics_file.read_text(encoding="utf-8"))
            self.assertEqual(metrics["symbols"], {
                "renamed": 3, "eligible": 3, "coverage": 1.0,
            })
            self.assertEqual(metrics["occurrences"], {
                "renamed": 8, "eligible": 8, "coverage": 1.0,
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
                {"files": 2, "mapping_entries": 3, "modified_tokens": 8},
            )

            # Verify restored files match gold
            for rel_file in mapping["files"]:
                gold_bytes = (source_root / rel_file).read_bytes()
                restored_bytes = (restored_dir / rel_file).read_bytes()
                self.assertEqual(restored_bytes, gold_bytes)


if __name__ == "__main__":
    unittest.main()
