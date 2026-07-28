from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from rtl_obfuscator import restore_vnext
from rtl_obfuscator.category_registry_vnext import (
    CANONICAL_CATEGORIES,
    DEFAULT_CATEGORIES,
    MODULE_ABI_CATEGORIES,
)
from rtl_obfuscator.source_catalog import build_source_catalog
from rtl_obfuscator.source_set import from_filelist


ROOT = Path(__file__).resolve().parents[1]
SINGLE_ROOT = ROOT / "rtl_samples"
FIFO_ROOT = SINGLE_ROOT / "example_fifo"
FORMAL_ROOT = ROOT / "tests" / "fixtures" / "refactor_symbol_graph_parameters"
PUBLIC_SCRIPTS = {
    "rtl_encrypt": ROOT / "rtl_encrypt.py",
    "rtl_decrypt": ROOT / "rtl_decrypt.py",
}


class PublicCliTests(unittest.TestCase):
    @staticmethod
    def _run_public(command: str, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(PUBLIC_SCRIPTS[command]), *arguments],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )

    @staticmethod
    def _run_internal(*arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "rtl_obfuscator.rewrite", *arguments],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )

    @staticmethod
    def _formal(gate_dir: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                "scripts/formal_equivalence.py",
                "--gold-filelist",
                "tests/fixtures/refactor_symbol_graph_parameters/design.f",
                "--gold-root",
                "tests/fixtures/refactor_symbol_graph_parameters",
                "--gate-filelist",
                str(gate_dir / "design.f"),
                "--gate-root",
                str(gate_dir),
                "--top",
                "parameter_top",
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
    def _physical_files(report: dict[str, object]) -> tuple[str, ...]:
        source_set = report["source_set"]
        assert isinstance(source_set, dict)
        return tuple(
            dict.fromkeys(
                (*source_set["ordered_source_files"], *source_set["included_files"])
            )
        )

    def _encrypt(
        self,
        root: Path,
        *mode_arguments: str,
        map_location: str = "default",
        metrics_location: str = "default",
    ) -> tuple[Path, Path, Path, dict[str, object]]:
        root.mkdir(parents=True)
        gate = root / "gate"
        arguments = [*mode_arguments, "--output-dir", str(gate)]
        if map_location == "explicit":
            mapping = root / "mapping-explicit.json"
            arguments.extend(("--map", str(mapping)))
        else:
            self.assertEqual(map_location, "default")
            mapping = gate / "mapping.json"
        if metrics_location == "explicit":
            metrics = root / "metrics-explicit.json"
            arguments.extend(("--metrics", str(metrics)))
        else:
            self.assertEqual(metrics_location, "default")
            metrics = gate / "metrics.json"
        result = self._run_public("rtl_encrypt", *arguments)
        self.assertEqual(result.returncode, 0, result.stderr)
        stdout = json.loads(result.stdout)
        report = json.loads(mapping.read_text(encoding="utf-8"))
        metrics_report = json.loads(metrics.read_text(encoding="utf-8"))
        self.assertEqual(stdout["format"], "rtl-obfuscation.cli-vnext")
        self.assertEqual(stdout["summary"], report["summary"])
        self.assertEqual(metrics_report, report["metrics"])
        self.assertTrue(report["summary"]["strict_compile_passed"])
        self.assertTrue(report["summary"]["restored_byte_identical"])
        self.assertTrue(gate.is_dir())
        self.assertEqual((gate / "mapping.json").exists(), map_location == "default")
        self.assertEqual(
            (gate / "metrics.json").exists(), metrics_location == "default"
        )
        return gate, mapping, metrics, report

    def test_root_scripts_are_thin_and_public_help_is_simple(self):
        expected = {
            "rtl_encrypt": (
                "#!/usr/bin/env python3\n\n"
                "from rtl_obfuscator.rewrite import rtl_encrypt_main\n\n\n"
                'if __name__ == "__main__":\n'
                "    raise SystemExit(rtl_encrypt_main())\n"
            ),
            "rtl_decrypt": (
                "#!/usr/bin/env python3\n\n"
                "from rtl_obfuscator.rewrite import rtl_decrypt_main\n\n\n"
                'if __name__ == "__main__":\n'
                "    raise SystemExit(rtl_decrypt_main())\n"
            ),
        }
        for command, script in PUBLIC_SCRIPTS.items():
            self.assertEqual(script.read_text(encoding="utf-8"), expected[command])
            result = self._run_public(command, "--help")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(result.stdout.startswith(f"usage: {command} "))
            self.assertNotIn("vnext", result.stdout.lower())

        encrypt_help = self._run_public("rtl_encrypt", "--help").stdout
        self.assertIn("[--map MAP_FILE]", encrypt_help)
        self.assertIn("[--metrics METRICS_FILE]", encrypt_help)
        self.assertIn("--encryption-rate ENCRYPTION_RATE", encrypt_help)
        self.assertNotIn("--abi-category", encrypt_help)
        self.assertIn("--report REPORT", self._run_public("rtl_decrypt", "--help").stdout)

    def test_default_categories_follow_single_filelist_and_project_modes(self):
        with tempfile.TemporaryDirectory(prefix="t060-public-modes-") as temporary:
            root = Path(temporary)
            single_gate, _single_map, _single_metrics, single = self._encrypt(
                root / "single",
                "--input",
                "11_supported_obfuscation.sv",
                "--source-root",
                str(SINGLE_ROOT),
            )
            self.assertEqual(
                single["mapping"]["selection"]["selected_categories"],
                list(DEFAULT_CATEGORIES),
            )
            self.assertEqual(single["mapping"]["selection"]["abi_categories"], [])
            self.assertTrue((single_gate / "mapping.json").is_file())
            self.assertTrue((single_gate / "metrics.json").is_file())

            _plain_gate, _plain_map, _plain_metrics, plain_filelist = self._encrypt(
                root / "plain-filelist",
                "--filelist",
                "design.f",
                "--source-root",
                str(FIFO_ROOT),
            )
            self.assertEqual(
                plain_filelist["mapping"]["selection"]["selected_categories"],
                list(DEFAULT_CATEGORIES),
            )
            self.assertEqual(
                plain_filelist["mapping"]["selection"]["abi_categories"], []
            )

            _top_gate, _top_map, _top_metrics, top_filelist = self._encrypt(
                root / "top-filelist",
                "--filelist",
                "design.f",
                "--source-root",
                str(FIFO_ROOT),
                "--top",
                "fifo_top",
            )
            self.assertEqual(
                top_filelist["mapping"]["selection"]["selected_categories"],
                list(CANONICAL_CATEGORIES),
            )
            self.assertEqual(
                top_filelist["mapping"]["selection"]["abi_categories"],
                list(MODULE_ABI_CATEGORIES),
            )
            expected_filelist = from_filelist(
                filelist=FIFO_ROOT / "design.f",
                source_root=FIFO_ROOT,
                top="fifo_top",
            )
            self.assertEqual(
                self._physical_files(top_filelist),
                tuple(expected_filelist.compile_order),
            )

            _project_gate, _project_map, _project_metrics, project = self._encrypt(
                root / "project",
                "--project-root",
                str(FIFO_ROOT),
                "--top",
                "fifo_top",
            )
            self.assertEqual(
                project["mapping"]["selection"]["selected_categories"],
                list(CANONICAL_CATEGORIES),
            )
            self.assertEqual(
                project["mapping"]["selection"]["abi_categories"],
                list(MODULE_ABI_CATEGORIES),
            )
            records = project["mapping"]["records"]
            renamed = {
                (record["category"], record["original_name"])
                for record in records
                if record["action"] == "rename"
            }
            self.assertIn(("modules", "fifo_ctrl"), renamed)
            self.assertIn(("interfaces", "fifo_if"), renamed)
            self.assertTrue(any(category == "ports" for category, _ in renamed))
            self.assertTrue(
                any(category == "interface_ports" for category, _ in renamed)
            )
            self.assertFalse(
                any(
                    record["action"] == "rename"
                    and record["original_name"] == "fifo_top"
                    for record in records
                )
            )
            top_ports = [
                record
                for record in records
                if record["category"] == "ports"
                and record["reason"] == "selected_top_boundary"
            ]
            self.assertTrue(top_ports)
            self.assertTrue(all(record["action"] == "preserve" for record in top_ports))
            fifo_bus = [
                record for record in records if record["original_name"] == "fifo_bus"
            ]
            self.assertEqual(len(fifo_bus), 1)
            self.assertEqual(fifo_bus[0]["category"], "interface_instances")
            self.assertEqual(fifo_bus[0]["action"], "preserve")
            self.assertEqual(fifo_bus[0]["reason"], "selected_top_boundary")

    def test_manual_categories_and_public_all_do_not_append_hidden_choices(self):
        with tempfile.TemporaryDirectory(prefix="t060-public-categories-") as temporary:
            root = Path(temporary)
            _gate, _mapping, _metrics, selected = self._encrypt(
                root / "selected",
                "--project-root",
                str(FIFO_ROOT),
                "--top",
                "fifo_top",
                "--category",
                "signals",
                "--category",
                "ports",
            )
            self.assertEqual(
                selected["mapping"]["selection"]["selected_categories"],
                ["signals", "ports"],
            )
            self.assertEqual(
                selected["mapping"]["selection"]["abi_categories"], ["ports"]
            )
            self.assertTrue(
                any(
                    record["category"] == "ports" and record["action"] == "rename"
                    for record in selected["mapping"]["records"]
                )
            )
            self.assertFalse(
                any(
                    record["category"] not in {"signals", "ports"}
                    and record["action"] == "rename"
                    for record in selected["mapping"]["records"]
                )
            )

            _all_gate, _all_map, _all_metrics, all_report = self._encrypt(
                root / "all",
                "--input",
                "11_supported_obfuscation.sv",
                "--source-root",
                str(SINGLE_ROOT),
                "--category",
                "all",
            )
            self.assertEqual(
                all_report["mapping"]["selection"]["selected_categories"],
                list(CANONICAL_CATEGORIES),
            )
            self.assertEqual(all_report["mapping"]["selection"]["abi_categories"], [])

    def test_default_explicit_and_mixed_report_publication(self):
        with tempfile.TemporaryDirectory(prefix="t060-public-reports-") as temporary:
            root = Path(temporary)
            for map_location, metrics_location in (
                ("default", "default"),
                ("explicit", "explicit"),
                ("default", "explicit"),
                ("explicit", "default"),
            ):
                gate, mapping, metrics, _report = self._encrypt(
                    root / f"{map_location}-{metrics_location}",
                    "--input",
                    "11_supported_obfuscation.sv",
                    "--source-root",
                    str(SINGLE_ROOT),
                    map_location=map_location,
                    metrics_location=metrics_location,
                )
                expected = {
                    "11_supported_obfuscation.sv",
                    "design.f",
                    *({"mapping.json"} if map_location == "default" else set()),
                    *({"metrics.json"} if metrics_location == "default" else set()),
                }
                self.assertEqual(
                    {
                        path.relative_to(gate).as_posix()
                        for path in gate.rglob("*")
                        if path.is_file()
                    },
                    expected,
                )
                self.assertTrue(mapping.is_file())
                self.assertTrue(metrics.is_file())

            failure_root = root / "failure"
            failure_root.mkdir()
            existing_map = failure_root / "existing.json"
            existing_map.write_text("{}", encoding="utf-8")
            gate = failure_root / "gate"
            result = self._run_public(
                "rtl_encrypt",
                "--input",
                "11_supported_obfuscation.sv",
                "--source-root",
                str(SINGLE_ROOT),
                "--output-dir",
                str(gate),
                "--map",
                str(existing_map),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("Traceback", result.stderr)
            self.assertFalse(gate.exists())
            self.assertEqual(existing_map.read_text(encoding="utf-8"), "{}")

    def test_default_reports_restore_and_gate_audit_fail_closed(self):
        with tempfile.TemporaryDirectory(prefix="t060-public-restore-") as temporary:
            root = Path(temporary)
            gate, mapping, _metrics, report = self._encrypt(
                root / "encrypt",
                "--filelist",
                "design.f",
                "--source-root",
                str(FIFO_ROOT),
                "--top",
                "fifo_top",
            )
            restored = root / "restored"
            restore_report = root / "restore.json"
            result = self._run_public(
                "rtl_decrypt",
                "--map",
                str(mapping),
                "--gate-dir",
                str(gate),
                "--source-root",
                str(FIFO_ROOT),
                "--output-dir",
                str(restored),
                "--report",
                str(restore_report),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            audit = restore_vnext.audit_orchestration_gate_vnext(
                mapping,
                gate_dir=gate,
            )
            self.assertEqual(len(audit.gate_manifest), 4)
            for relative in self._physical_files(report):
                self.assertEqual(
                    (restored / relative).read_bytes(),
                    (FIFO_ROOT / relative).read_bytes(),
                )

            mismatched = root / "mismatched"
            shutil.copytree(gate, mismatched)
            metrics_value = json.loads(
                (mismatched / "metrics.json").read_text(encoding="utf-8")
            )
            metrics_value["effective_coverage"] = 0.0
            (mismatched / "metrics.json").write_text(
                json.dumps(metrics_value), encoding="utf-8"
            )
            result = self._run_public(
                "rtl_decrypt",
                "--map",
                str(mismatched / "mapping.json"),
                "--gate-dir",
                str(mismatched),
                "--source-root",
                str(FIFO_ROOT),
                "--output-dir",
                str(root / "mismatched-restore"),
                "--report",
                str(root / "mismatched-restore.json"),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(
                result.stderr.startswith("error: RESTORE_VNEXT_REPORT_INVALID")
            )
            self.assertFalse((root / "mismatched-restore").exists())

            unknown = root / "unknown"
            shutil.copytree(gate, unknown)
            (unknown / "unexpected.json").write_text("{}", encoding="utf-8")
            result = self._run_public(
                "rtl_decrypt",
                "--map",
                str(unknown / "mapping.json"),
                "--gate-dir",
                str(unknown),
                "--source-root",
                str(FIFO_ROOT),
                "--output-dir",
                str(root / "unknown-restore"),
                "--report",
                str(root / "unknown-restore.json"),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(
                result.stderr.startswith("error: RESTORE_VNEXT_GATE_INVALID")
            )
            self.assertFalse((root / "unknown-restore").exists())

    def test_encryption_rate_report_and_invalid_values(self):
        with tempfile.TemporaryDirectory(prefix="t060-public-rate-") as temporary:
            root = Path(temporary)
            _gate, _mapping, _metrics, report = self._encrypt(
                root / "valid",
                "--filelist",
                "design.f",
                "--source-root",
                str(FORMAL_ROOT),
                "--top",
                "parameter_top",
                "--encryption-rate",
                "0.35",
            )
            self.assertTrue(report["summary"]["rate_enabled"])
            rate_selection = report["rate_metrics"]["rate_selection"]
            self.assertEqual(rate_selection["target"], 0.35)
            self.assertGreater(rate_selection["selected_entries"], 0)

            for index, value in enumerate(("0", "1.01", "nan")):
                gate = root / f"invalid-gate-{index}"
                result = self._run_public(
                    "rtl_encrypt",
                    "--input",
                    "11_supported_obfuscation.sv",
                    "--source-root",
                    str(SINGLE_ROOT),
                    "--output-dir",
                    str(gate),
                    "--encryption-rate",
                    value,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stderr, "error: CLI_VNEXT_RATE_INVALID\n")
                self.assertFalse(gate.exists())

    def test_internal_operation_keeps_required_reports_abi_and_old_all(self):
        internal_help = self._run_internal("encrypt-vnext", "--help")
        self.assertEqual(internal_help.returncode, 0, internal_help.stderr)
        self.assertIn("--abi-category ABI_CATEGORY", internal_help.stdout)
        self.assertNotIn("[--map MAP_FILE]", internal_help.stdout)
        self.assertNotIn("[--metrics METRICS_FILE]", internal_help.stdout)

        with tempfile.TemporaryDirectory(prefix="t060-internal-compat-") as temporary:
            root = Path(temporary)
            missing = self._run_internal(
                "encrypt-vnext",
                "--input",
                str(SINGLE_ROOT / "11_supported_obfuscation.sv"),
                "--source-root",
                str(SINGLE_ROOT),
                "--output-dir",
                str(root / "missing-gate"),
            )
            self.assertNotEqual(missing.returncode, 0)
            self.assertFalse((root / "missing-gate").exists())

            mapping = root / "mapping.json"
            metrics = root / "metrics.json"
            result = self._run_internal(
                "encrypt-vnext",
                "--filelist",
                str(FORMAL_ROOT / "design.f"),
                "--source-root",
                str(FORMAL_ROOT),
                "--top",
                "parameter_top",
                "--category",
                "all",
                "--abi-category",
                "parameters",
                "--output-dir",
                str(root / "gate"),
                "--map",
                str(mapping),
                "--metrics",
                str(metrics),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(mapping.read_text(encoding="utf-8"))
            self.assertEqual(
                report["mapping"]["selection"]["selected_categories"],
                list(DEFAULT_CATEGORIES),
            )
            self.assertEqual(
                report["mapping"]["selection"]["abi_categories"], ["parameters"]
            )

    def test_readme_and_type_table_are_user_facing_and_consistent(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        table = (
            ROOT / "docs" / "systemverilog_renaming_table.md"
        ).read_text(encoding="utf-8")
        headings = (
            "## 加密模式",
            "## 输出文件和加密率",
            "## 单文件加密",
            "## Filelist 多文件加密",
            "## Project-root 项目加密",
            "## 解密",
            "## 常用可选参数",
        )
        positions = tuple(readme.index(heading) for heading in headings)
        self.assertEqual(positions, tuple(sorted(positions)))
        forbidden = (
            "ABI",
            "vNext",
            "physical files",
            "top closure",
            "selected_top_boundary",
            "semantic",
            "mapping pipeline",
            "--abi-category",
        )
        for term in forbidden:
            self.assertNotIn(term.lower(), readme.lower())
            self.assertNotIn(term.lower(), table.lower())
        for start, end in zip(positions[2:5], positions[3:6], strict=True):
            section = readme[start:end]
            self.assertIn("### 基础命令", section)
            self.assertIn("### 示例与架构", section)
            basic = section[
                section.index("### 基础命令") : section.index("### 示例与架构")
            ]
            self.assertNotIn("--map", basic)
            self.assertNotIn("--metrics", basic)
            self.assertNotIn("### 必填参数", section)
            self.assertNotIn("### 项目示例", section)
            self.assertNotIn("### 示例架构", section)
        self.assertIn("<output-dir>/mapping.json", readme)
        self.assertIn("<output-dir>/metrics.json", readme)
        self.assertIn("rtl_samples/11_supported_obfuscation.sv", readme)
        self.assertIn("rtl_samples/example_fifo/design.f", readme)
        self.assertIn("rtl_samples/example_fifo", readme)
        self.assertIn("--encryption-rate 0.35", readme)
        self.assertIn("不是标识符数量的精确比例", readme)
        self.assertIn("当前版本会保留 top module 内部直接声明的 interface 实例名", readme)
        for category in CANONICAL_CATEGORIES:
            self.assertIn(f"`{category}`", table)
        self.assertEqual(table.count("| 是 |"), len(DEFAULT_CATEGORIES))
        self.assertIn("`struct`", table)
        self.assertIn("`interface`", table)
        self.assertIn("`all`", table)
        self.assertGreaterEqual(table.count("--category"), 3)

    def test_public_filelist_top_rate_actual_gate_formal_and_negative(self):
        with tempfile.TemporaryDirectory(prefix="t060-public-formal-") as temporary:
            root = Path(temporary)
            gate, _mapping, _metrics, report = self._encrypt(
                root / "encrypt",
                "--filelist",
                "design.f",
                "--source-root",
                str(FORMAL_ROOT),
                "--top",
                "parameter_top",
                "--encryption-rate",
                "0.35",
                "--name-length",
                "16",
            )
            self.assertTrue(report["summary"]["rate_enabled"])
            self.assertEqual(
                report["mapping"]["selection"]["selected_categories"],
                list(CANONICAL_CATEGORIES),
            )
            self.assertEqual(
                report["mapping"]["selection"]["abi_categories"],
                list(MODULE_ABI_CATEGORIES),
            )

            positive = self._formal(gate)
            self.assertEqual(positive.returncode, 0, positive.stdout + positive.stderr)
            positive_json = json.loads(positive.stdout.strip().splitlines()[-1])
            self.assertEqual(positive_json["formal_equivalence"], "pass")
            self.assertEqual(positive_json["top"], "parameter_top")
            self.assertEqual(positive_json["seq"], 5)

            negative = root / "negative"
            shutil.copytree(gate, negative)
            self.assertTrue((negative / "mapping.json").is_file())
            self.assertTrue((negative / "metrics.json").is_file())
            child = negative / "rtl/child.sv"
            original = child.read_bytes()
            needle = b"assign data_o = "
            self.assertEqual(original.count(needle), 1)
            position = original.index(needle) + len(needle)
            child.write_bytes(original[:position] + b"~" + original[position:])
            self.assertEqual(child.read_bytes().count(b"~"), original.count(b"~") + 1)

            negative_source_set = from_filelist(
                filelist=negative / "design.f",
                source_root=negative,
                top="parameter_top",
            )
            self.assertEqual(
                build_source_catalog(negative_source_set).to_report()["compile"],
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
