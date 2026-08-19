from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from rtl_obfuscator.project_discovery import _ProjectContext
from rtl_obfuscator.source_set import SourceSetError, from_filelist


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "t097_local_typedef_scope"
PUBLIC_ENCRYPT = ROOT / "rtl_encrypt.py"


class T097LocalTypedefDiscoveryScopeTests(unittest.TestCase):
    def test_design_scope_typedefs_and_type_parameters_are_not_global_providers(self):
        result = from_filelist(
            filelist=FIXTURE_ROOT / "design.f",
            top="t097_top",
        )
        self.assertEqual(
            result.ordered_source_files,
            (
                "rtl/top.sv",
                "rtl/local_one.sv",
                "rtl/local_two.sv",
                "rtl/local_bus_if.sv",
                "rtl/parameter_type.sv",
            ),
        )
        self.assertEqual(result.compile_order, result.ordered_source_files)
        self.assertEqual(
            result.top_closure_files,
            (
                "rtl/top.sv",
                "rtl/local_one.sv",
                "rtl/local_two.sv",
                "rtl/local_bus_if.sv",
                "rtl/parameter_type.sv",
            ),
        )
        context = _ProjectContext(
            FIXTURE_ROOT,
            "t097_top",
            [],
            {},
            [],
            candidate_files=result.ordered_source_files,
        )
        self.assertNotIn("stsram_dat_bk1_t", context.types_by_name)

    def test_compilation_unit_typedef_provider_is_reachable(self):
        result = from_filelist(
            filelist=FIXTURE_ROOT / "global_design.f",
            top="t097_global_top",
        )
        self.assertEqual(
            result.top_closure_files,
            (
                "rtl/global_top.sv",
                "rtl/global_consumer.sv",
                "rtl/global_provider.sv",
            ),
        )
        self.assertIn("rtl/global_provider.sv", result.top_closure_files)

    def test_compilation_unit_typedef_ambiguity_is_fail_closed_with_details(self):
        result = from_filelist(
            filelist=FIXTURE_ROOT / "ambiguous.f",
            top="t097_ambiguous_top",
        )
        self.assertEqual(
            result.top_closure_files,
            (
                "rtl/ambiguous_top.sv",
                "rtl/ambiguous_consumer.sv",
                "rtl/ambiguous_one.sv",
            ),
        )
        self.assertEqual(
            result.compile_order,
            result.ordered_source_files,
        )

    def test_public_filelist_cli_preserves_structured_typedef_ambiguity(self):
        with tempfile.TemporaryDirectory(prefix="t097-public-diagnostic-") as temporary:
            output = Path(temporary) / "gate"
            result = subprocess.run(
                [
                    sys.executable,
                    str(PUBLIC_ENCRYPT),
                    "--filelist",
                    str(FIXTURE_ROOT / "ambiguous.f"),
                    "--top",
                    "t097_ambiguous_top",
                    "--category",
                    "signals",
                    "--output-dir",
                    str(output),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")
            self.assertIn("error: CLI_VNEXT_ORCHESTRATION_INVALID\n", result.stderr)
            self.assertNotIn("type has multiple providers", result.stderr)
            self.assertNotIn("reachable definition not found", result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
