"""Main-Agent frozen tests: shared metrics and successful-run evidence, no FAST."""

from contextlib import ExitStack, redirect_stderr
from dataclasses import replace
import io
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from rtl_obfuscator import metrics_vnext, rewrite, rewrite_vnext
from rtl_obfuscator.orchestration_vnext import run_vnext
from rtl_obfuscator.source_set import from_filelist


ROOT = Path(__file__).resolve().parents[1]
TIMING = re.compile(r"^\[\s*\d+\.\d{3}s\] (?:开始|完成) .+$")
TOP_TEXT = (
    "module t138_top(input logic clk, input logic [3:0] a, b, output logic [3:0] y);\n"
    "  logic [3:0] saved;\n"
    "  logic [3:0] mixed;\n"
    "  always_ff @(posedge clk) saved <= a;\n"
    "  assign mixed = saved ^ b;\n"
    "  assign y = mixed;\n"
    "endmodule\n"
)


class T138SharedRunObservabilityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="t138-main-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.project = self.root / "project"
        (self.project / "owned").mkdir(parents=True)
        (self.project / "external").mkdir()
        (self.project / "owned/top.sv").write_text(TOP_TEXT, encoding="utf-8")
        (self.project / "owned/unregistered.sv").write_text("not RTL\n", encoding="utf-8")
        (self.project / "external/helper.sv").write_text(
            "module t138_helper(input logic a, output logic y);\n"
            "  logic untouched;\n  assign untouched = a;\n"
            "  assign y = untouched;\nendmodule\n", encoding="utf-8"
        )
        self.filelist = self.project / "design.f"
        self.filelist.write_text("owned/top.sv\nexternal/helper.sv\n", encoding="utf-8")

    def arguments(self, gate, *, scoped=True, rate=None, quiet=False):
        result = ["--filelist", str(self.filelist), "--top", "t138_top",
                  "--category", "signals", "--output-dir", str(gate)]
        if scoped:
            result += ["--rewrite-root", str(self.project / "owned")]
        if rate is not None:
            result += ["--encryption-rate", rate]
        if quiet:
            result += ["--quiet"]
        return result

    def cli(self, gate, **options):
        command = [sys.executable, str(ROOT / "rtl_encrypt.py"), *self.arguments(gate, **options)]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=180)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result, command

    def test_scoped_and_rate_metrics_keep_complete_delivery_and_restore(self):
        for label, rate in (("whole", None), ("rate", "0.5")):
            with self.subTest(label=label):
                gate = self.root / label
                result, _ = self.cli(gate, rate=rate)
                summary = json.loads(result.stdout)["summary"]
                report = json.loads((gate / "mapping.json").read_text())
                metrics = report["metrics"]
                self.assertEqual(metrics["scope"], {
                    "kind": "rewrite_roots", "files": ["owned/top.sv"], "physical_files": 2})
                self.assertEqual(summary["files"], 1)
                self.assertEqual(summary["physical_files"], 2)
                self.assertEqual(summary["effective_line_total"], 7)
                self.assertTrue(summary["strict_compile_passed"])
                self.assertTrue(summary["restored_byte_identical"])
                self.assertEqual([x["file"] for x in metrics["effective_lines"]["by_file"]], ["owned/top.sv"])
                self.assertEqual([x["file"] for x in metrics["affected_lines"]["by_file"]], ["owned/top.sv"])
                self.assertEqual(len(report["mapping_execution"]["input_manifest"]), 2)
                self.assertEqual(len(report["mapping_execution"]["gate_manifest"]), 2)
                self.assertEqual(len(report["mapping_execution"]["per_file_mapping"]), 2)
                self.assertFalse((gate / "owned/unregistered.sv").exists())
                self.assertEqual((gate / "external/helper.sv").read_bytes(),
                                 (self.project / "external/helper.sv").read_bytes())
                self.assertIn("交付物理文件数", result.stderr)
                restored = self.root / (label + "-restore")
                decrypted = subprocess.run([
                    sys.executable, str(ROOT / "rtl_decrypt.py"), "--map", str(gate / "mapping.json"),
                    "--gate-dir", str(gate), "--output-dir", str(restored)],
                    cwd=ROOT, capture_output=True, text=True, timeout=180)
                self.assertEqual(decrypted.returncode, 0, decrypted.stderr)
                for name in ("owned/top.sv", "external/helper.sv"):
                    self.assertEqual((restored / name).read_bytes(), (self.project / name).read_bytes())

    def test_without_rewrite_roots_all_registered_physical_files_are_counted(self):
        gate = self.root / "all"
        result, _ = self.cli(gate, scoped=False)
        report = json.loads((gate / "mapping.json").read_text())
        self.assertEqual(report["metrics"]["scope"], {
            "kind": "all_physical", "files": ["owned/top.sv", "external/helper.sv"], "physical_files": 2})
        self.assertEqual(json.loads(result.stdout)["summary"]["files"], 2)

    def test_completed_reports_are_cached_and_defensively_copied(self):
        source = from_filelist(filelist=self.filelist, top="t138_top", rewrite_roots=(self.project / "owned",))
        result = run_vnext(source, categories=("signals",), gate_dir=self.root / "gate", restore_dir=self.root / "restore")
        envelopes = (result, result.metrics, result.mapping_execution)
        expected = [item.to_report() for item in envelopes]
        with ExitStack() as stack:
            for module, name in ((rewrite_vnext, "_validate_mapping_execution"),
                                 (metrics_vnext, "_read_source_bytes"), (metrics_vnext, "_read_gate_bytes"),
                                 (metrics_vnext, "_affected_line_metrics"), (metrics_vnext, "_coverage_counts")):
                stack.enter_context(mock.patch.object(module, name, side_effect=AssertionError("report rebuilt " + name)))
            for item, original in zip(envelopes, expected):
                self.assertEqual(item.to_report(), original)
                changed = item.to_report()
                changed.clear()
                self.assertEqual(item.to_report(), original)
            changed = result.to_report()
            changed["metrics"]["scope"]["files"].clear()
            self.assertEqual(result.to_report(), expected[0])

    def test_run_record_exactly_reuses_progress_command_and_final_summary(self):
        gate = self.root / "record"
        result, command = self.cli(gate)
        saved = (gate / "encryption_summary.txt").read_text(encoding="utf-8")
        observed = [line for line in result.stderr.splitlines() if TIMING.fullmatch(line)]
        self.assertEqual([line for line in saved.splitlines() if TIMING.fullmatch(line)], observed)
        self.assertGreater(len(observed), 12)
        final = result.stderr[result.stderr.index("加密总结\n"):]
        self.assertTrue(saved.endswith(final))
        command_line = next(line for line in saved.splitlines() if line.strip().startswith("启动指令"))
        actual = shlex.split(command_line.strip().split(None, 1)[1])
        command[0] = str(Path(command[0]).resolve())
        self.assertEqual(actual, command)
        self.assertIn(str(ROOT), saved.split("阶段耗时", 1)[0])
        labels = ("逐字节回填校验", "构建执行索引 [audit.execution]", "计算加密指标 [audit.metrics]",
                  "组装结果报告 [audit.report]", "原子发布输出", "清理临时文件")
        positions = []
        for label in labels:
            for phase in ("开始", "完成"):
                needle = phase + " " + label
                self.assertEqual(result.stderr.count(needle), 1, result.stderr)
                positions.append(result.stderr.index(needle))
        self.assertEqual(positions, sorted(positions))
        self.assertLess(positions[-1], result.stderr.index("加密总结\n"))

    def test_replaced_envelopes_do_not_inherit_verified_cache(self):
        source = from_filelist(filelist=self.filelist, top="t138_top", rewrite_roots=(self.project / "owned",))
        result = run_vnext(source, categories=("signals",), gate_dir=self.root / "gate", restore_dir=self.root / "restore")
        result.to_report()
        with self.assertRaises(metrics_vnext.MetricsVNextError):
            replace(result.metrics, effective_line_total=result.metrics.effective_line_total + 1).to_report()
        with self.assertRaises(rewrite_vnext.RewriteVNextError):
            replace(result.mapping_execution, restore_result=None).to_report()

    def test_quiet_keeps_persisted_record(self):
        gate = self.root / "quiet"
        result, _ = self.cli(gate, quiet=True)
        self.assertEqual(result.stderr, "")
        saved = (gate / "encryption_summary.txt").read_text(encoding="utf-8")
        self.assertIn("启动指令", saved)
        self.assertIn("加密总结", saved)
        self.assertGreater(len([line for line in saved.splitlines() if TIMING.fullmatch(line)]), 12)

    def test_rate_run_has_real_post_restore_audit_events(self):
        result, _ = self.cli(self.root / "rate-progress", rate="0.5")
        labels = ("逐字节回填校验", "构建执行索引 [audit.execution]", "计算加密指标 [audit.metrics]",
                  "组装结果报告 [audit.report]", "原子发布输出", "清理临时文件")
        positions = []
        for label in labels:
            for phase in ("开始", "完成"):
                needle = phase + " " + label
                self.assertEqual(result.stderr.count(needle), 1, result.stderr)
                positions.append(result.stderr.index(needle))
        self.assertEqual(positions, sorted(positions))

    def test_publish_completion_follows_actual_target_installation(self):
        gate = self.root / "published"
        stage = rewrite._CliVNextProgress.stage
        events = []
        def observe(progress, name, phase):
            if name == "publish" and phase == "end":
                self.assertTrue((gate / "owned/top.sv").is_file(), "publish end preceded final target installation")
                self.assertTrue((gate / "mapping.json").is_file())
                events.append((name, phase))
            return stage(progress, name, phase)
        arguments = self.arguments(gate)
        with mock.patch.object(rewrite._CliVNextProgress, "stage", observe), redirect_stderr(io.StringIO()), \
                mock.patch.object(sys, "argv", [str(ROOT / "rtl_encrypt.py"), *arguments]):
            rewrite._encrypt_vnext(rewrite._create_encrypt_argument_parser().parse_args(arguments))
        self.assertEqual(events, [("publish", "end")])

    def test_summary_write_failure_rolls_back_delivery(self):
        gate = self.root / "failed"
        original = rewrite._cli_vnext_write_text_atomic
        def fail_summary(path, text):
            if path.name == "encryption_summary.txt":
                raise OSError("t138 injected summary write failure")
            return original(path, text)
        with mock.patch.object(rewrite, "_cli_vnext_write_text_atomic", fail_summary), redirect_stderr(io.StringIO()):
            with self.assertRaises((OSError, rewrite._CliVNextError)):
                rewrite._encrypt_vnext(rewrite._create_encrypt_argument_parser().parse_args(self.arguments(gate)))
        self.assertFalse(gate.exists())
        self.assertEqual(list(self.root.glob(".rtl-obfuscation-cli-vnext-*")), [])

    def test_publish_late_collision_preserves_existing_user_file_and_rolls_back(self):
        source = self.project / "owned/top.sv"
        gate = self.root / "first-artifact"
        existing = self.root / "existing"
        existing.write_bytes(b"user-owned")
        with self.assertRaises(rewrite._CliVNextError):
            rewrite._cli_vnext_publish([(source, gate), (source, existing)])
        self.assertFalse(gate.exists())
        self.assertEqual(existing.read_bytes(), b"user-owned")

    def test_actual_gate_formal_and_fixed_functional_negative(self):
        gate = self.root / "formal-gate"
        result, _ = self.cli(gate)
        self.assertGreater(json.loads(result.stdout)["summary"]["modified_tokens"], 0)
        gold = self.project / "owned/top.sv"
        target = gate / "owned/top.sv"
        self.assertNotEqual(target.read_bytes(), gold.read_bytes())
        command = [sys.executable, str(ROOT / "scripts/formal_equivalence.py"),
                   "--gold", str(gold), "--gate", str(target), "--top", "t138_top", "--seq", "5"]
        positive = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=180)
        self.assertEqual(positive.returncode, 0, positive.stdout + positive.stderr)
        self.assertEqual(json.loads(positive.stdout)["formal_equivalence"], "pass")
        negative = self.root / "negative.sv"
        data = target.read_bytes()
        mutated = data.replace(b" ^ ", b" | ", 1)
        self.assertNotEqual(data, mutated)
        negative.write_bytes(mutated)
        command[command.index("--gate") + 1] = str(negative)
        failed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=180)
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("unproven", failed.stdout + failed.stderr)
        self.assertIn("equiv_status -assert", failed.stdout + failed.stderr)
        print("T138_FORMAL " + json.dumps({"positive": json.loads(positive.stdout),
              "negative_gate": str(negative), "negative_exit": failed.returncode,
              "unproven": True, "equiv_status_assert": True}, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
