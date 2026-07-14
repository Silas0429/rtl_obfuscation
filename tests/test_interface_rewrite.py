"""Black-box tests for T017 interface definition renaming."""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


class InterfaceRewriteCliTest(unittest.TestCase):
    def test_interface_encrypt_decrypt_round_trip(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        filelist = Path("tests/fixtures/t017_interface/design.f")
        source_root = Path("tests/fixtures/t017_interface")

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
                    "t017_top",
                    "--category",
                    "interfaces",
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
                {"files": 3, "mapping_entries": 1, "modified_tokens": 3},
            )

            mapping = json.loads(mapping_file.read_text(encoding="utf-8"))
            self.assertEqual(mapping["version"], 2)
            self.assertEqual(mapping["name_length"], 8)
            self.assertEqual(mapping["files"], ["bus_if.sv", "child.sv", "top.sv"])
            self.assertEqual(mapping["top"], "t017_top")
            entries = mapping["entries"]
            self.assertEqual(len(entries), 1)

            entry = entries[0]
            self.assertEqual(entry["category"], "interfaces")
            self.assertEqual(entry["scope"], "t017_bus_if")
            self.assertEqual(entry["original_name"], "t017_bus_if")
            self.assertTrue(re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{7}", entry["renamed_name"]))
            self.assertEqual(entry["declaration"], {
                "file": "bus_if.sv", "start": 10, "end": 21,
            })
            self.assertEqual(entry["references"], [
                {"file": "child.sv", "start": 24, "end": 35},
                {"file": "top.sv", "start": 138, "end": 149},
            ])

            # Verify all source slices match original names
            for record in [entry["declaration"], *entry["references"]]:
                source_bytes = (source_root / record["file"]).read_bytes()
                self.assertEqual(
                    source_bytes[record["start"]:record["end"]],
                    b"t017_bus_if",
                )

            # Verify gate files: original name gone
            for f in mapping["files"]:
                gate_bytes = (gate_dir / f).read_bytes()
                self.assertNotIn(b"t017_bus_if", gate_bytes)

            # Verify metrics hard constraints
            metrics = json.loads(metrics_file.read_text(encoding="utf-8"))
            self.assertEqual(metrics["symbols"], {
                "renamed": 1, "eligible": 1, "coverage": 1.0,
            })
            self.assertEqual(metrics["occurrences"], {
                "renamed": 3, "eligible": 3, "coverage": 1.0,
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
                {"files": 3, "mapping_entries": 1, "modified_tokens": 3},
            )

            # Verify restored files match gold
            for f in mapping["files"]:
                gold_bytes = (source_root / f).read_bytes()
                restored_bytes = (restored_dir / f).read_bytes()
                self.assertEqual(restored_bytes, gold_bytes)

    def test_interface_is_not_implicit_in_project_all(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        filelist = Path("tests/fixtures/t017_interface/design.f")
        source_root = Path("tests/fixtures/t017_interface")

        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
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
                    str(tmp_path / "gate"),
                    "--map",
                    str(tmp_path / "mapping.json"),
                    "--metrics",
                    str(tmp_path / "metrics.json"),
                    "--top",
                    "t017_top",
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
                {"files": 3, "mapping_entries": 1, "modified_tokens": 1},
            )
            mapping = json.loads((tmp_path / "mapping.json").read_text(encoding="utf-8"))
            self.assertEqual(
                [entry["category"] for entry in mapping["entries"]],
                ["instances"],
            )


if __name__ == "__main__":
    unittest.main()
