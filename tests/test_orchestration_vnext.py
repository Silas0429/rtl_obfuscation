from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from rtl_obfuscator.orchestration_vnext import run_vnext
from rtl_obfuscator.source_set import from_filelist


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "t108_pyslang_rename_index"


class OrchestrationVNextTests(unittest.TestCase):
    def test_all_categories_run_once_through_mapping_gate_restore(self):
        source_set = from_filelist(filelist=FIXTURE / "design.f", top="top")
        with tempfile.TemporaryDirectory(prefix="t108-orchestration-") as temp:
            root = Path(temp)
            result = run_vnext(
                source_set,
                categories=("all",),
                gate_dir=root / "gate",
                restore_dir=root / "restore",
            )
            report = result.to_report()
            self.assertEqual(result.schema_version, 2)
            self.assertEqual(report["schema_version"], 2)
            self.assertTrue(report["summary"]["strict_compile_passed"])
            self.assertTrue(report["summary"]["restored_byte_identical"])
            self.assertEqual(
                report["mapping"]["selection"]["selected_categories"],
                ["signals", "ports", "interface", "struct"],
            )

    def test_pipeline_consumers_retain_source_and_execution_identity(self):
        source_set = from_filelist(filelist=FIXTURE / "design.f", top="top")
        with tempfile.TemporaryDirectory(prefix="t108-orchestration-identity-") as temp:
            root = Path(temp)
            result = run_vnext(
                source_set,
                categories=("all",),
                gate_dir=root / "gate",
                restore_dir=root / "restore",
            )
            self.assertIs(
                result.mapping_vnext.rename_index.source_catalog.source_set,
                source_set,
            )
            self.assertIs(
                result.mapping_execution.rewrite_execution.mapping_vnext,
                result.effective_mapping_vnext,
            )
            self.assertIs(result.metrics.mapping_execution, result.mapping_execution)
            self.assertEqual(
                result.mapping_vnext.rename_index.selected_categories,
                ("signals", "ports", "interface", "struct"),
            )
