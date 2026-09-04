"""T136 black-box contract for persisted run evidence and filelist views."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
ENCRYPT = ROOT / "rtl_encrypt.py"
DECRYPT = ROOT / "rtl_decrypt.py"
FORMAL = ROOT / "scripts" / "formal_equivalence.py"
TIMING_LINE = re.compile(r"^\[\s*\d+\.\d{3}s\] (?:开始|完成) .+$")


class T136PersistedRunSummaryAndFilelistsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix="t136-run-record-"))
        cls.addClassCleanup(shutil.rmtree, cls.root, ignore_errors=True)
        cls.project = cls.root / "project"
        (cls.project / "include").mkdir(parents=True)
        (cls.project / "rtl").mkdir()
        (cls.project / "include" / "width.svh").write_text(
            "`define T136_WIDTH 4\n", encoding="utf-8"
        )
        (cls.project / "rtl" / "top.sv").write_text(
            "`include \"width.svh\"\n"
            "module t136_top (\n"
            "    input  logic clk,\n"
            "    input  logic [`T136_WIDTH-1:0] data_in,\n"
            "    output logic [`T136_WIDTH-1:0] data_out\n"
            ");\n"
            "    logic [`T136_WIDTH-1:0] hold_value;\n"
            "    always_ff @(posedge clk) hold_value <= data_in;\n"
            "`ifdef T136_FEATURE\n"
            "    assign data_out = hold_value ^ data_in;\n"
            "`else\n"
            "    assign data_out = hold_value;\n"
            "`endif\n"
            "endmodule\n",
            encoding="utf-8",
        )
        cls.input_filelist = cls.project / "input.f"
        cls.input_filelist.write_text(
            "+incdir+include\n"
            "+define+T136_FEATURE=1\n"
            "rtl/top.sv\n",
            encoding="utf-8",
        )
        cls.gate = cls.root / "gate"
        cls.command = (
            sys.executable,
            str(ENCRYPT),
            "--filelist",
            str(cls.input_filelist),
            "--top",
            "t136_top",
            "--rewrite-root",
            str(cls.project / "rtl"),
            "--category",
            "signals",
            "--output-dir",
            str(cls.gate),
        )
        cls.encrypted = subprocess.run(
            cls.command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        if cls.encrypted.returncode != 0:
            raise AssertionError(cls.encrypted.stderr)
        cls.payload = json.loads(cls.encrypted.stdout)
        cls.summary_text = (cls.gate / "encryption_summary.txt").read_text(
            encoding="utf-8"
        )

    def test_persisted_timing_lines_and_terminal_summary_are_byte_identical(self):
        stderr_timing = [
            line for line in self.encrypted.stderr.splitlines()
            if TIMING_LINE.fullmatch(line)
        ]
        persisted_timing = [
            line for line in self.summary_text.splitlines()
            if TIMING_LINE.fullmatch(line)
        ]
        self.assertGreater(len(stderr_timing), 12)
        self.assertEqual(persisted_timing, stderr_timing)
        self.assertEqual(len(persisted_timing), len(set(persisted_timing)))
        terminal_start = self.encrypted.stderr.index("加密总结\n")
        terminal_summary = self.encrypted.stderr[terminal_start:]
        self.assertTrue(self.summary_text.endswith(terminal_summary))
        self.assertLess(
            self.encrypted.stderr.index("完成 清理临时文件"), terminal_start
        )

    def test_effective_command_is_expanded_and_complete(self):
        command_section = self.summary_text.split("阶段耗时", 1)[0]
        self.assertIn("启动指令", command_section)
        self.assertIn("工作目录", command_section)
        for value in (
            str(self.input_filelist),
            "t136_top",
            str(self.project / "rtl"),
            str(self.gate),
            "signals",
        ):
            self.assertIn(value, command_section)
        for placeholder in ("$FILELIST", "$TOP", "$REWRITE", "$OUT"):
            self.assertNotIn(placeholder, command_section)

    def test_three_filelists_share_context_and_only_change_path_root(self):
        output_root = self.gate.resolve().as_posix()
        source_root = self.project.resolve().as_posix()
        expected = {
            "design.f": [
                f"+incdir+{output_root}/include",
                "+define+T136_FEATURE=1",
                f"{output_root}/rtl/top.sv",
            ],
            "export_design.f": [
                "+incdir+$OUT/include",
                "+define+T136_FEATURE=1",
                "$OUT/rtl/top.sv",
            ],
            "original_design.f": [
                f"+incdir+{source_root}/include",
                "+define+T136_FEATURE=1",
                f"{source_root}/rtl/top.sv",
            ],
        }
        for name, lines in expected.items():
            with self.subTest(name=name):
                self.assertEqual(
                    (self.gate / name).read_text(encoding="utf-8").splitlines(),
                    lines,
                )
        self.assertTrue((self.gate / "include" / "width.svh").is_file())
        self.assertTrue((self.gate / "rtl" / "top.sv").is_file())
        for name in expected:
            self.assertNotIn("width.svh", (self.gate / name).read_text(encoding="utf-8"))

    def test_public_decrypt_restores_all_physical_files(self):
        restored = self.root / "restored"
        result = subprocess.run(
            (
                sys.executable,
                str(DECRYPT),
                "--map",
                str(self.gate / "mapping.json"),
                "--gate-dir",
                str(self.gate),
                "--output-dir",
                str(restored),
            ),
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        for relative in (Path("rtl/top.sv"), Path("include/width.svh")):
            self.assertEqual(
                (restored / relative).read_bytes(),
                (self.project / relative).read_bytes(),
            )

    def test_actual_gate_formal_positive_and_fixed_functional_negative(self):
        arguments = (
            "--gold-filelist",
            str(self.gate / "original_design.f"),
            "--gold-root",
            str(self.project),
            "--gate-filelist",
            str(self.gate / "design.f"),
            "--gate-root",
            str(self.gate),
            "--top",
            "t136_top",
            "--seq",
            "5",
        )
        positive = subprocess.run(
            (sys.executable, str(FORMAL), *arguments),
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        self.assertEqual(positive.returncode, 0, positive.stdout + positive.stderr)
        self.assertEqual(json.loads(positive.stdout)["formal_equivalence"], "pass")

        relocated = self.root / "relocated-gate"
        shutil.copytree(self.gate, relocated)
        export_arguments = list(arguments)
        export_arguments[5] = str(relocated / "export_design.f")
        export_arguments[7] = str(relocated)
        export_environment = os.environ.copy()
        export_environment["OUT"] = str(relocated)
        export_positive = subprocess.run(
            (sys.executable, str(FORMAL), *export_arguments),
            cwd=ROOT,
            env=export_environment,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        self.assertEqual(
            export_positive.returncode,
            0,
            export_positive.stdout + export_positive.stderr,
        )
        self.assertEqual(
            json.loads(export_positive.stdout)["formal_equivalence"], "pass"
        )

        negative = self.root / "negative"
        shutil.copytree(self.gate, negative)
        negative_design = negative / "design.f"
        negative_design.write_text(
            negative_design.read_text(encoding="utf-8").replace(
                self.gate.resolve().as_posix(), negative.resolve().as_posix()
            ),
            encoding="utf-8",
        )
        target = negative / "rtl" / "top.sv"
        mutated = target.read_bytes().replace(b" ^ ", b" | ", 1)
        self.assertNotEqual(mutated, target.read_bytes())
        target.write_bytes(mutated)
        negative_arguments = list(arguments)
        negative_arguments[5] = str(negative_design)
        negative_arguments[7] = str(negative)
        failed = subprocess.run(
            (sys.executable, str(FORMAL), *negative_arguments),
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        self.assertNotEqual(failed.returncode, 0)
        diagnostics = failed.stdout + failed.stderr
        self.assertIn("unproven", diagnostics)
        self.assertIn("equiv_status -assert", diagnostics)

    def test_quiet_still_persists_timing_evidence(self):
        quiet_gate = self.root / "quiet-gate"
        quiet_command = [*self.command]
        quiet_command[quiet_command.index(str(self.gate))] = str(quiet_gate)
        quiet_command.insert(-2, "--quiet")
        quiet = subprocess.run(
            quiet_command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        self.assertEqual(quiet.returncode, 0, quiet.stderr)
        self.assertEqual(quiet.stderr, "")
        persisted = (quiet_gate / "encryption_summary.txt").read_text(encoding="utf-8")
        self.assertGreater(
            len([line for line in persisted.splitlines() if TIMING_LINE.fullmatch(line)]),
            12,
        )


if __name__ == "__main__":
    unittest.main()
