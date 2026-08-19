from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from rtl_obfuscator.source_catalog import build_source_catalog
from rtl_obfuscator.source_set import from_filelist


ROOT = Path(__file__).resolve().parents[1]
FIFO_ROOT = ROOT / "rtl_samples" / "example_fifo"
SINGLE_FILE = ROOT / "tests" / "fixtures" / "refactor_symbol_graph_parameters" / "single.sv"
PUBLIC_SCRIPT = ROOT / "rtl_encrypt.py"
DECRYPT_SCRIPT = ROOT / "rtl_decrypt.py"
FORMAL_SCRIPT = ROOT / "scripts" / "formal_equivalence.py"


class T096PublicFrontendInputModesTests(unittest.TestCase):
    @staticmethod
    def _run(script: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(script), *arguments],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )

    @staticmethod
    def _formal(gate_root: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(FORMAL_SCRIPT),
                "--gold-filelist",
                str(FIFO_ROOT / "design.f"),
                "--gold-root",
                str(FIFO_ROOT),
                "--gate-filelist",
                str(gate_root / "design.f"),
                "--gate-root",
                str(gate_root),
                "--top",
                "fifo_top",
                "--seq",
                "5",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )

    @staticmethod
    def _report(gate: Path) -> dict[str, object]:
        return json.loads((gate / "mapping.json").read_text(encoding="utf-8"))

    @staticmethod
    def _assert_success(result: subprocess.CompletedProcess[str]) -> dict[str, object]:
        unittest.TestCase().assertEqual(result.returncode, 0, result.stderr)
        unittest.TestCase().assertNotEqual(result.stdout.strip(), "")
        return json.loads(result.stdout)

    def test_three_public_modes_have_frozen_source_set_origins(self):
        with tempfile.TemporaryDirectory(prefix="t096-public-modes-") as temporary:
            root = Path(temporary)
            single = self._run(
                PUBLIC_SCRIPT,
                "--input",
                str(SINGLE_FILE),
                "--category",
                "signals",
                "--output-dir",
                str(root / "single"),
            )
            single_summary = self._assert_success(single)
            single_report = self._report(root / "single")
            self.assertEqual(single_report["source_set"]["origin"], "single-file")
            self.assertIsNone(single_report["source_set"]["top"])
            self.assertEqual(single_summary["summary"]["origin"], "single-file")

            for name, extra in (("filelist", ()), ("filelist-top", ("--top", "fifo_top"))):
                gate = root / name
                result = self._run(
                    PUBLIC_SCRIPT,
                    "--filelist",
                    str(FIFO_ROOT / "design.f"),
                    *extra,
                    "--category",
                    "signals",
                    "--output-dir",
                    str(gate),
                )
                summary = self._assert_success(result)
                report = self._report(gate)
                self.assertEqual(report["source_set"]["origin"], "filelist")
                self.assertEqual(
                    report["source_set"]["top"],
                    "fifo_top" if extra else None,
                )
                self.assertEqual(summary["summary"]["origin"], "filelist")

            project = self._run(
                PUBLIC_SCRIPT,
                "--source-root",
                str(FIFO_ROOT),
                "--top",
                "fifo_top",
                "--category",
                "signals",
                "--output-dir",
                str(root / "project"),
            )
            project_summary = self._assert_success(project)
            project_report = self._report(root / "project")
            self.assertEqual(project_report["source_set"]["origin"], "project-root")
            self.assertEqual(project_report["source_set"]["top"], "fifo_top")
            self.assertEqual(project_summary["summary"]["origin"], "project-root")

    def test_all_public_mode_conflicts_fail_before_output(self):
        with tempfile.TemporaryDirectory(prefix="t096-public-invalid-") as temporary:
            root = Path(temporary)
            input_file = FIFO_ROOT / "fifo_top.sv"
            filelist = FIFO_ROOT / "design.f"
            source_root = FIFO_ROOT
            cases = (
                ("input-source-root", ("--input", str(input_file), "--source-root", str(source_root))),
                ("input-top", ("--input", str(input_file), "--top", "fifo_top")),
                ("input-filelist", ("--input", str(input_file), "--filelist", str(filelist))),
                ("filelist-source-root", ("--filelist", str(filelist), "--source-root", str(source_root))),
                ("filelist-input", ("--filelist", str(filelist), "--input", str(input_file))),
                ("filelist-source-root-top", ("--filelist", str(filelist), "--source-root", str(source_root), "--top", "fifo_top")),
                ("source-root-only", ("--source-root", str(source_root))),
                ("top-only", ("--top", "fifo_top")),
                ("source-root-top-filelist", ("--source-root", str(source_root), "--top", "fifo_top", "--filelist", str(filelist))),
                ("all-selectors", ("--input", str(input_file), "--filelist", str(filelist), "--source-root", str(source_root), "--top", "fifo_top")),
            )
            for index, (name, mode_arguments) in enumerate(cases):
                output = root / f"gate-{index}-{name}"
                result = self._run(
                    PUBLIC_SCRIPT,
                    *mode_arguments,
                    "--output-dir",
                    str(output),
                )
                self.assertNotEqual(result.returncode, 0, name)
                self.assertEqual(result.stdout, "", name)
                self.assertTrue(result.stderr.startswith("error: CLI_VNEXT_INPUT_INVALID\n"), name)
                self.assertIn("detail: CLI_VNEXT_INPUT_MODE_", result.stderr, name)
                self.assertIn("message: ", result.stderr, name)
                self.assertIn("hint: ", result.stderr, name)
                self.assertNotIn("Traceback", result.stderr, name)
                self.assertFalse(output.exists(), name)

    def test_help_and_documents_are_filelist_first(self):
        result = self._run(PUBLIC_SCRIPT, "--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("单文件：--input FILE", result.stdout)
        self.assertIn("filelist：--filelist DESIGN.F [--top TOP]", result.stdout)
        self.assertIn("project-root：--source-root DIR --top TOP", result.stdout)
        self.assertNotIn("单文件：--input FILE --source-root DIR", result.stdout)

        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        formal = (ROOT / "docs" / "formal_verification.md").read_text(encoding="utf-8")
        structure = (ROOT / "docs" / "development" / "project_structure.md").read_text(encoding="utf-8")
        self.assertLess(readme.index("--filelist rtl_samples/example_fifo/design.f"), readme.index("## 三种加密模式"))
        self.assertIn("单文件只提供 `--input`", readme)
        self.assertIn("filelist 只提供 `--filelist`", readme)
        self.assertNotIn("--filelist <原始项目>/design.f \\\n  --source-root", formal)
        self.assertIn("--input <原始目录>/design.sv", formal)
        self.assertNotIn("--input <原始目录>/design.sv \\\n  --source-root", formal)
        self.assertIn("filelist 模式以显式 filelist 为唯一输入", structure)

    def test_filelist_signals_actual_gate_restore_and_formal_positive_negative(self):
        with tempfile.TemporaryDirectory(prefix="t096-public-formal-") as temporary:
            root = Path(temporary)
            gate = root / "gate"
            result = self._run(
                PUBLIC_SCRIPT,
                "--filelist",
                str(FIFO_ROOT / "design.f"),
                "--top",
                "fifo_top",
                "--category",
                "signals",
                "--output-dir",
                str(gate),
            )
            summary = self._assert_success(result)
            report = self._report(gate)
            self.assertGreater(summary["action_counts"]["rename"], 0)
            self.assertTrue(report["summary"]["strict_compile_passed"])
            self.assertTrue(report["summary"]["restored_byte_identical"])

            restored = root / "restored"
            restored_result = self._run(
                DECRYPT_SCRIPT,
                "--map",
                str(gate / "mapping.json"),
                "--gate-dir",
                str(gate),
                "--output-dir",
                str(restored),
            )
            self._assert_success(restored_result)
            for source in FIFO_ROOT.glob("*.sv"):
                restored_candidates = list(restored.rglob(source.name))
                self.assertEqual(len(restored_candidates), 1, source.name)
                self.assertEqual(source.read_bytes(), restored_candidates[0].read_bytes(), source.name)

            positive = self._formal(gate)
            self.assertEqual(positive.returncode, 0, positive.stdout + positive.stderr)
            positive_json = json.loads(positive.stdout.strip().splitlines()[-1])
            self.assertEqual(positive_json["formal_equivalence"], "pass")
            self.assertEqual(positive_json["top"], "fifo_top")

            negative = root / "negative"
            shutil.copytree(gate, negative)
            negative_source = next(negative.rglob("fifo_ctrl.sv"))
            text = negative_source.read_text(encoding="utf-8")
            self.assertIn("DEPTH", text)
            changed = text.replace(" == DEPTH", " != DEPTH", 1)
            self.assertNotEqual(text, changed)
            negative_source.write_text(changed, encoding="utf-8")
            negative_source_set = from_filelist(
                filelist=negative / "design.f",
                source_root=negative,
                top="fifo_top",
            )
            negative_compile = build_source_catalog(negative_source_set).to_report()["compile"]
            self.assertEqual(
                negative_compile,
                {
                    "catalog": {"parse_errors": 0, "semantic_errors": 0},
                    "top_overlay": {"parse_errors": 0, "semantic_errors": 0},
                },
            )
            negative_formal = self._formal(negative)
            combined = (negative_formal.stdout + negative_formal.stderr).lower()
            self.assertNotEqual(negative_formal.returncode, 0)
            self.assertIn("unproven", combined)
            self.assertIn("equiv_status -assert", combined)


if __name__ == "__main__":
    unittest.main()
