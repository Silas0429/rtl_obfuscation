"""Black-box tests for T017 interface definition renaming."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


class InterfaceRewriteCliTest(unittest.TestCase):
    def test_filelist_interface_category_uses_bounded_manual_profile(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        filelist = Path("tests/fixtures/t017_interface/design.f")
        source_root = Path("tests/fixtures/t017_interface")

        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            gate_dir = tmp_path / "gate"
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
            mapping = json.loads(mapping_file.read_text(encoding="utf-8"))
            self.assertEqual(mapping["version"], 4)
            self.assertEqual(mapping["profile"], "manual")
            self.assertTrue(gate_dir.is_dir())

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
