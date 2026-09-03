from __future__ import annotations

from contextlib import ExitStack
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from rtl_obfuscator import metrics_vnext, rewrite_vnext
from rtl_obfuscator.orchestration_vnext import run_vnext
from rtl_obfuscator.source_set import from_filelist


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "t130_fast_local_signals"
ENCRYPT = ROOT / "rtl_encrypt.py"
DECRYPT = ROOT / "rtl_decrypt.py"


class T135ScopedExecutionMetricsTests(unittest.TestCase):
    def _run_cli(self, output: Path, *, full: bool) -> subprocess.CompletedProcess[str]:
        command = [
            sys.executable,
            str(ENCRYPT),
            "--filelist",
            str(FIXTURE / "design.f"),
        ]
        if full:
            command.extend(("--top", "t130_top"))
        command.extend(
            (
                "--rewrite-root",
                str(FIXTURE / "owned"),
                "--category",
                "signals",
                "--output-dir",
                str(output),
            )
        )
        return subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )

    def test_fast_and_full_metrics_use_rewrite_scope(self):
        expected_scope = ["owned/leaf_a.sv", "owned/leaf_b.sv", "owned/top.sv"]
        original_external = (FIXTURE / "external" / "context.sv").read_bytes()
        cases = (
            ("fast", False, 12, {"rename": 5, "preserve": 1, "unsupported": 0}, "66.67%"),
            ("full", True, 18, {"rename": 7, "preserve": 2, "unsupported": 0}, "100.00%"),
        )
        with tempfile.TemporaryDirectory(prefix="t135-scope-") as temporary:
            root = Path(temporary)
            for label, full, affected, actions, coverage in cases:
                gate = root / label
                result = self._run_cli(gate, full=full)
                self.assertEqual(result.returncode, 0, result.stderr)
                cli = json.loads(result.stdout.strip().splitlines()[-1])
                report = json.loads((gate / "mapping.json").read_text(encoding="utf-8"))
                metrics = report["metrics"]
                self.assertEqual(report["summary"]["files"], 3)
                self.assertEqual(report["summary"]["physical_files"], 4)
                self.assertEqual(cli["summary"]["files"], 3)
                self.assertEqual(cli["summary"]["physical_files"], 4)
                self.assertEqual(
                    metrics["scope"],
                    {
                        "kind": "rewrite_roots",
                        "files": expected_scope,
                        "physical_files": 4,
                    },
                )
                self.assertEqual(metrics["effective_lines"]["total"], 50)
                self.assertEqual(
                    [item["file"] for item in metrics["effective_lines"]["by_file"]],
                    expected_scope,
                )
                self.assertEqual(metrics["affected_lines"]["changed"], affected)
                self.assertEqual(
                    [item["file"] for item in metrics["affected_lines"]["by_file"]],
                    expected_scope,
                )
                self.assertEqual(cli["action_counts"], actions)
                self.assertEqual(len(report["mapping_execution"]["input_manifest"]), 4)
                self.assertEqual(len(report["mapping_execution"]["gate_manifest"]), 4)
                self.assertEqual(
                    (gate / "external" / "context.sv").read_bytes(), original_external
                )
                self.assertIn("总代码行数                          50", result.stderr)
                self.assertIn("总文件数                             3", result.stderr)
                self.assertIn("交付物理文件数                       4", result.stderr)
                self.assertTrue(
                    any(
                        line.split() == ["文件覆盖率", coverage]
                        for line in result.stderr.splitlines()
                    ),
                    result.stderr,
                )

                restored = root / f"{label}-restored"
                decrypt = subprocess.run(
                    [
                        sys.executable,
                        str(DECRYPT),
                        "--map",
                        str(gate / "mapping.json"),
                        "--gate-dir",
                        str(gate),
                        "--output-dir",
                        str(restored),
                    ],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    timeout=180,
                    check=False,
                )
                self.assertEqual(decrypt.returncode, 0, decrypt.stderr)
                for source in FIXTURE.rglob("*"):
                    if source.is_file() and source.suffix in {".sv", ".v"}:
                        relative = source.relative_to(FIXTURE)
                        self.assertEqual((restored / relative).read_bytes(), source.read_bytes())

    def test_post_restore_stages_are_visible_once_and_ordered(self):
        with tempfile.TemporaryDirectory(prefix="t135-stages-") as temporary:
            result = self._run_cli(Path(temporary) / "gate", full=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        stages = (
            ("逐字节回填校验", None),
            ("构建执行索引", "audit.execution"),
            ("计算加密指标", "audit.metrics"),
            ("组装结果报告", "audit.report"),
            ("原子发布输出", None),
            ("清理临时文件", None),
        )
        positions: list[int] = []
        for label, suffix in stages:
            begin = f"开始 {label}" + (f" [{suffix}]" if suffix else "")
            end = f"完成 {label}" + (f" [{suffix}]" if suffix else "")
            self.assertEqual(result.stderr.count(begin), 1, result.stderr)
            self.assertEqual(result.stderr.count(end), 1, result.stderr)
            positions.extend((result.stderr.index(begin), result.stderr.index(end)))
        self.assertEqual(positions, sorted(positions), result.stderr)

    def test_completed_result_reports_without_rebuilding_execution_or_metrics(self):
        source_set = from_filelist(
            filelist=FIXTURE / "design.f",
            rewrite_roots=(FIXTURE / "owned",),
        )
        with tempfile.TemporaryDirectory(prefix="t135-pure-report-") as temporary:
            root = Path(temporary)
            result = run_vnext(
                source_set,
                categories=("signals",),
                gate_dir=root / "gate",
                restore_dir=root / "restore",
            )
            forbidden = (
                (rewrite_vnext, "_validate_mapping_execution"),
                (metrics_vnext, "_read_source_bytes"),
                (metrics_vnext, "_read_gate_bytes"),
                (metrics_vnext, "_affected_line_metrics"),
                (metrics_vnext, "_coverage_counts"),
            )
            with ExitStack() as stack:
                for module, name in forbidden:
                    if hasattr(module, name):
                        stack.enter_context(
                            mock.patch.object(
                                module,
                                name,
                                side_effect=AssertionError(f"report rebuilt {name}"),
                            )
                        )
                first = result.to_report()
                second = result.to_report()
            self.assertEqual(first, second)
            self.assertEqual(first["summary"]["files"], 3)
            self.assertEqual(first["summary"]["physical_files"], 4)


if __name__ == "__main__":
    unittest.main()
