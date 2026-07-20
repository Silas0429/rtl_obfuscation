"""Black-box tests for T018 interface instance/member/modport renaming."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


class InterfaceMemberRewriteCliTest(unittest.TestCase):
    def test_interface_member_categories_require_project_root(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        filelist = Path("tests/fixtures/t018_interface_member/design.f")
        source_root = Path("tests/fixtures/t018_interface_member")

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
                    "t018_top",
                    "--category",
                    "interface_instances",
                    "--category",
                    "interface_ports",
                    "--category",
                    "modports",
                    "--name-length",
                    "8",
                ],
                cwd=repository,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(encrypt.returncode, 2)
            self.assertIn("CATEGORY_REQUIRES_PROJECT_ROOT", encrypt.stderr)
            self.assertEqual(encrypt.stdout, "")
            self.assertFalse(gate_dir.exists())
            self.assertFalse(mapping_file.exists())
            self.assertFalse(metrics_file.exists())


if __name__ == "__main__":
    unittest.main()
