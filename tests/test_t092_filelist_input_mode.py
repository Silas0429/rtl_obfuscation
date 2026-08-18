from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "t091_h_macro_header"
PUBLIC_ENCRYPT = ROOT / "rtl_encrypt.py"
PUBLIC_DECRYPT = ROOT / "rtl_decrypt.py"


class FilelistInputModeTests(unittest.TestCase):
    def _run(self, script: Path, *arguments: str, env: dict[str, str] | None = None):
        return subprocess.run(
            [sys.executable, str(script), *arguments],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )

    @staticmethod
    def _formal_arguments(gate: Path) -> list[str]:
        return [
            "scripts/formal_equivalence.py",
            "--gold-filelist",
            str(FIXTURE_ROOT / "design.f"),
            "--gold-root",
            str(FIXTURE_ROOT),
            "--gate-filelist",
            str(gate / "design.f"),
            "--gate-root",
            str(gate),
            "--top",
            "t091_top",
            "--seq",
            "5",
        ]

    def _make_nested_filelist(self, project: Path) -> Path:
        shutil.copytree(FIXTURE_ROOT, project)
        nested = project / "nested"
        nested.mkdir()
        (nested / "child.f").write_text(
            "$T092_PROJ/rtl/stl_gmacro.h\n../rtl/top.sv\n", encoding="utf-8"
        )
        top = project / "top.f"
        top.write_text(
            "+incdir+$T092_PROJ/rtl\n"
            "+define+T092_FILELIST_CONTEXT=1\n"
            "-f nested/child.f\n",
            encoding="utf-8",
        )
        return top

    def test_public_filelist_autoroot_rejects_source_root_and_restores(self):
        with tempfile.TemporaryDirectory(prefix="t092-filelist-") as temporary:
            root = Path(temporary)
            project = root / "project"
            filelist = self._make_nested_filelist(project)
            env = os.environ.copy()
            env["T092_PROJ"] = str(project)
            gate = root / "gate"

            encrypted = self._run(
                PUBLIC_ENCRYPT,
                "--filelist",
                str(filelist),
                "--top",
                "t091_top",
                "--category",
                "signals",
                "--output-dir",
                str(gate),
                env=env,
            )
            self.assertEqual(encrypted.returncode, 0, encrypted.stderr)
            summary = json.loads(encrypted.stdout)
            self.assertGreater(summary["action_counts"]["rename"], 0)
            report = json.loads((gate / "mapping.json").read_text(encoding="utf-8"))
            source_set = report["source_set"]
            self.assertEqual(source_set["ordered_source_files"], ["rtl/top.sv"])
            self.assertEqual(source_set["compile_order"], ["rtl/top.sv"])
            self.assertEqual(source_set["included_files"], ["rtl/stl_gmacro.h"])
            self.assertTrue(report["summary"]["strict_compile_passed"])
            self.assertTrue(report["summary"]["restored_byte_identical"])
            self.assertEqual(
                (gate / "rtl" / "stl_gmacro.h").read_bytes(),
                (project / "rtl" / "stl_gmacro.h").read_bytes(),
            )

            restored = root / "restored"
            decrypted = self._run(
                PUBLIC_DECRYPT,
                "--map",
                str(gate / "mapping.json"),
                "--gate-dir",
                str(gate),
                "--output-dir",
                str(restored),
            )
            self.assertEqual(decrypted.returncode, 0, decrypted.stderr)
            for relative in ("rtl/top.sv", "rtl/stl_gmacro.h"):
                self.assertEqual(
                    (restored / relative).read_bytes(),
                    (project / relative).read_bytes(),
                )

            illegal_output = root / "illegal"
            illegal = self._run(
                PUBLIC_ENCRYPT,
                "--filelist",
                str(filelist),
                "--source-root",
                str(project),
                "--top",
                "t091_top",
                "--category",
                "signals",
                "--output-dir",
                str(illegal_output),
                env=env,
            )
            self.assertNotEqual(illegal.returncode, 0)
            self.assertEqual(illegal.stdout, "")
            self.assertTrue(illegal.stderr.startswith("error: CLI_VNEXT_INPUT_INVALID\n"))
            self.assertIn("filelist 模式不要提供 --source-root", illegal.stderr)
            self.assertFalse(illegal_output.exists())

            positive = subprocess.run(
                [sys.executable, *self._formal_arguments(gate)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
            self.assertEqual(positive.returncode, 0, positive.stdout + positive.stderr)
            positive_json = json.loads(positive.stdout.strip().splitlines()[-1])
            self.assertEqual(positive_json["formal_equivalence"], "pass")
            self.assertEqual(positive_json["top"], "t091_top")

            negative = root / "negative"
            shutil.copytree(gate, negative)
            top = negative / "rtl" / "top.sv"
            contents = top.read_bytes()
            self.assertEqual(contents.count(b" ^ "), 1)
            top.write_bytes(contents.replace(b" ^ ", b" | ", 1))
            strict = subprocess.run(
                [
                    "iverilog",
                    "-g2012",
                    "-t",
                    "null",
                    "-s",
                    "t091_top",
                    "-I",
                    str(negative / "rtl"),
                    str(negative / "rtl" / "top.sv"),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
            self.assertEqual(strict.returncode, 0, strict.stdout + strict.stderr)
            negative_arguments = self._formal_arguments(negative)
            negative_result = subprocess.run(
                [sys.executable, *negative_arguments],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
            combined = (negative_result.stdout + negative_result.stderr).lower()
            self.assertNotEqual(negative_result.returncode, 0)
            self.assertIn("unproven", combined)
            self.assertIn("equiv_status -assert", combined)


if __name__ == "__main__":
    unittest.main()
