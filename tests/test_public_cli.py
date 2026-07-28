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
SINGLE_ROOT = ROOT / "rtl_samples"
FIFO_ROOT = SINGLE_ROOT / "example_fifo"
FORMAL_ROOT = ROOT / "tests" / "fixtures" / "refactor_symbol_graph_parameters"
PUBLIC_SCRIPTS = {
    "rtl_encrypt": ROOT / "rtl_encrypt.py",
    "rtl_decrypt": ROOT / "rtl_decrypt.py",
}
FULL_PROJECT_SELECTION = (
    "--category",
    "all",
    "--category",
    "modules",
    "--category",
    "ports",
    "--category",
    "interface",
    "--abi-category",
    "parameters",
    "--abi-category",
    "typedefs",
    "--abi-category",
    "struct_types",
    "--abi-category",
    "struct_fields",
    "--abi-category",
    "union_fields",
    "--abi-category",
    "modules",
    "--abi-category",
    "ports",
    "--abi-category",
    "interfaces",
    "--abi-category",
    "interface_instances",
    "--abi-category",
    "interface_ports",
    "--abi-category",
    "modports",
)


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
    ) -> tuple[Path, Path, dict[str, object]]:
        root.mkdir()
        gate = root / "gate"
        mapping = root / "mapping.json"
        metrics = root / "metrics.json"
        result = self._run_public(
            "rtl_encrypt",
            *mode_arguments,
            "--output-dir",
            str(gate),
            "--map",
            str(mapping),
            "--metrics",
            str(metrics),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        stdout = json.loads(result.stdout)
        report = json.loads(mapping.read_text(encoding="utf-8"))
        self.assertEqual(stdout["format"], "rtl-obfuscation.cli-vnext")
        self.assertEqual(stdout["summary"], report["summary"])
        self.assertTrue(report["summary"]["strict_compile_passed"])
        self.assertTrue(report["summary"]["restored_byte_identical"])
        self.assertTrue(gate.is_dir())
        self.assertTrue(metrics.is_file())
        return gate, mapping, report

    def test_root_scripts_are_thin_wrappers_and_help_hides_internal_operations(self):
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
            self.assertTrue(result.stdout.startswith(f"usage: {command} "), result.stdout)
            self.assertNotIn("encrypt-vnext", result.stdout)
            self.assertNotIn("decrypt-vnext", result.stdout)
            self.assertNotIn("vnext", result.stdout.lower())

        decrypt_help = self._run_public("rtl_decrypt", "--help").stdout
        self.assertIn("--report REPORT", decrypt_help)

    def test_guided_readme_orders_modes_before_examples(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        renaming_table = (
            ROOT / "docs" / "systemverilog_renaming_table.md"
        ).read_text(encoding="utf-8")
        headings = (
            "## 先选择输入模式",
            "## 单文件加密",
            "## Filelist 多文件加密",
            "## Project-root 项目加密",
            "## 解密",
            "## `rtl_encrypt.py` 完整选项",
        )
        positions = tuple(readme.index(heading) for heading in headings)
        self.assertEqual(positions, tuple(sorted(positions)))
        self.assertNotIn("## 安装", readme)
        self.assertNotIn("pip install", readme)
        self.assertNotIn("encrypt-vnext", readme)
        self.assertNotIn("decrypt-vnext", readme)
        self.assertNotIn("python -m rtl_obfuscator.rewrite", readme)

        for start, end in zip(positions[1:4], positions[2:5], strict=True):
            section = readme[start:end]
            subsection_headings = (
                "### 基础命令格式",
                "### 必填参数",
                "### 项目示例",
                "### 示例架构",
                "### 运行示例",
            )
            subsection_positions = tuple(
                section.index(heading) for heading in subsection_headings
            )
            self.assertEqual(
                subsection_positions,
                tuple(sorted(subsection_positions)),
            )

        for sample in (
            "rtl_samples/11_supported_obfuscation.sv",
            "rtl_samples/example_fifo/design.f",
            "rtl_samples/example_fifo",
        ):
            self.assertIn(sample, readme)
        self.assertIn("python rtl_encrypt.py --help", readme)
        self.assertIn("python rtl_decrypt.py --help", readme)
        self.assertGreaterEqual(readme.count("python rtl_encrypt.py \\"), 6)
        self.assertGreaterEqual(readme.count("python rtl_decrypt.py \\"), 2)
        self.assertIn("--filelist` 支持可选 `--top`", readme)
        self.assertIn("所有 physical files", readme)
        self.assertIn("`fifo_bus`", readme)
        self.assertIn("`selected_top_boundary`", readme)
        self.assertIn("--abi-category interface_instances", readme)
        for boundary_text in (
            "`interface_instances`",
            "`fifo_bus`",
            "`selected_top_boundary`",
            "即使同时选择 category 和 ABI category 也仍会保留",
        ):
            self.assertIn(boundary_text, readme)
            self.assertIn(boundary_text, renaming_table)

        single_section = readme[positions[1] : positions[2]]
        filelist_section = readme[positions[2] : positions[3]]
        project_section = readme[positions[3] : positions[4]]
        self.assertNotIn("\n  --category", single_section)
        self.assertNotIn("\n  --category", filelist_section)
        for argument in (
            "--category all",
            "--category modules",
            "--category ports",
            "--category interface",
            "--abi-category parameters",
            "--abi-category interface_instances",
            "--abi-category modports",
        ):
            self.assertIn(argument, project_section)

    def test_public_single_filelist_project_root_and_decrypt(self):
        with tempfile.TemporaryDirectory(prefix="t059-public-modes-") as temporary:
            root = Path(temporary)
            _single_gate, _single_map, single_report = self._encrypt(
                root / "single",
                "--input",
                "11_supported_obfuscation.sv",
                "--source-root",
                str(SINGLE_ROOT),
            )
            self.assertEqual(single_report["source_set"]["origin"], "single-file")
            self.assertEqual(
                self._physical_files(single_report),
                ("11_supported_obfuscation.sv",),
            )

            _filelist_gate, _filelist_map, filelist_report = self._encrypt(
                root / "filelist",
                "--filelist",
                "design.f",
                "--source-root",
                str(FIFO_ROOT),
                "--top",
                "fifo_top",
            )
            self.assertEqual(filelist_report["source_set"]["origin"], "filelist")
            self.assertEqual(filelist_report["source_set"]["top"], "fifo_top")
            self.assertEqual(len(self._physical_files(filelist_report)), 4)

            project_gate, project_map, project_report = self._encrypt(
                root / "project",
                "--project-root",
                str(FIFO_ROOT),
                "--top",
                "fifo_top",
                *FULL_PROJECT_SELECTION,
            )
            self.assertEqual(project_report["source_set"]["origin"], "project-root")
            self.assertEqual(project_report["source_set"]["top"], "fifo_top")
            self.assertEqual(project_report["summary"]["modified_tokens"], 268)
            project_files = self._physical_files(project_report)
            self.assertEqual(len(project_files), 4)

            records = project_report["mapping"]["records"]
            renamed = {
                (record["category"], record["original_name"])
                for record in records
                if record["action"] == "rename" and record["abi"] == "module_abi"
            }
            self.assertIn(("interfaces", "fifo_if"), renamed)
            self.assertTrue(
                any(category == "interface_ports" for category, _name in renamed)
            )
            self.assertTrue(any(category == "modports" for category, _name in renamed))
            self.assertIn(("modules", "fifo_ctrl"), renamed)
            self.assertTrue(any(category == "ports" for category, _name in renamed))
            fifo_bus = [
                record
                for record in records
                if record["original_name"] == "fifo_bus"
            ]
            self.assertEqual(len(fifo_bus), 1)
            self.assertEqual(fifo_bus[0]["category"], "interface_instances")
            self.assertEqual(fifo_bus[0]["action"], "preserve")
            self.assertEqual(fifo_bus[0]["reason"], "selected_top_boundary")

            restored = root / "restored"
            restore_report = root / "restore.json"
            decrypted = self._run_public(
                "rtl_decrypt",
                "--map",
                str(project_map),
                "--gate-dir",
                str(project_gate),
                "--source-root",
                str(FIFO_ROOT),
                "--output-dir",
                str(restored),
                "--report",
                str(restore_report),
            )
            self.assertEqual(decrypted.returncode, 0, decrypted.stderr)
            stdout = json.loads(decrypted.stdout)
            persisted_restore = json.loads(restore_report.read_text(encoding="utf-8"))
            self.assertEqual(stdout["format"], "rtl-obfuscation.restore-vnext-cli")
            self.assertTrue(persisted_restore["summary"]["restored_byte_identical"])
            for relative_file in project_files:
                self.assertEqual(
                    (restored / relative_file).read_bytes(),
                    (FIFO_ROOT / relative_file).read_bytes(),
                )

    def test_public_missing_required_arguments_leave_no_partial_output(self):
        with tempfile.TemporaryDirectory(prefix="t059-public-invalid-") as temporary:
            root = Path(temporary)
            gate = root / "gate"
            mapping = root / "mapping.json"
            metrics = root / "metrics.json"
            missing_metrics = self._run_public(
                "rtl_encrypt",
                "--input",
                "11_supported_obfuscation.sv",
                "--source-root",
                str(SINGLE_ROOT),
                "--output-dir",
                str(gate),
                "--map",
                str(mapping),
            )
            self.assertNotEqual(missing_metrics.returncode, 0)
            self.assertNotIn("Traceback", missing_metrics.stderr)
            self.assertFalse(gate.exists())
            self.assertFalse(mapping.exists())
            self.assertFalse(metrics.exists())

            missing_report = self._run_public(
                "rtl_decrypt",
                "--map",
                str(root / "missing-map.json"),
                "--gate-dir",
                str(root / "missing-gate"),
                "--source-root",
                str(SINGLE_ROOT),
                "--output-dir",
                str(root / "restore"),
            )
            self.assertNotEqual(missing_report.returncode, 0)
            self.assertNotIn("Traceback", missing_report.stderr)
            self.assertFalse((root / "restore").exists())
            self.assertFalse((root / "restore.json").exists())

            internal_operation = self._run_public("rtl_encrypt", "encrypt-vnext")
            self.assertNotEqual(internal_operation.returncode, 0)
            self.assertNotIn("Traceback", internal_operation.stderr)

    def test_public_filelist_actual_gate_formal_and_functional_negative(self):
        with tempfile.TemporaryDirectory(prefix="t059-public-formal-") as temporary:
            root = Path(temporary)
            gate, _mapping, report = self._encrypt(
                root / "encrypt",
                "--filelist",
                "design.f",
                "--source-root",
                str(FORMAL_ROOT),
                "--top",
                "parameter_top",
                "--category",
                "signals",
                "--category",
                "parameters",
                "--category",
                "genvars",
                "--abi-category",
                "parameters",
                "--encryption-rate",
                "0.35",
                "--name-length",
                "16",
            )
            self.assertTrue(report["summary"]["rate_enabled"])

            positive = self._formal(gate)
            self.assertEqual(positive.returncode, 0, positive.stdout + positive.stderr)
            positive_json = json.loads(positive.stdout.strip().splitlines()[-1])
            self.assertEqual(positive_json["formal_equivalence"], "pass")
            self.assertEqual(positive_json["top"], "parameter_top")
            self.assertEqual(positive_json["seq"], 5)

            negative = root / "negative"
            shutil.copytree(gate, negative)
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
