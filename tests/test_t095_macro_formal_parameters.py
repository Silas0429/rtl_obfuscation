from __future__ import annotations

from pathlib import Path
import unittest

from rtl_obfuscator.project_discovery import _ProjectContext
from rtl_obfuscator.source_set import SourceSetError, from_filelist


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "t095_macro_formal_parameters"


class MacroFormalParameterTests(unittest.TestCase):
    def test_multiline_formals_defaults_conditions_and_token_paste(self):
        result = from_filelist(
            filelist=FIXTURE_ROOT / "design.f",
            top="t095_top",
        )
        self.assertEqual(result.ordered_source_files, ("rtl/top.sv",))
        self.assertEqual(
            result.included_files,
            ("rtl/asserts.h", "rtl/defaults.h"),
        )
        self.assertEqual(result.top_closure_files, ("rtl/top.sv",))
        self.assertEqual(result.compile_order, ("rtl/top.sv",))

        context = _ProjectContext(
            FIXTURE_ROOT,
            "t095_top",
            [],
            {"T095_USE_ALT": "1"},
            [],
            candidate_files=("rtl/asserts.h", "rtl/defaults.h", "rtl/top.sv"),
        )
        closure = {"rtl/asserts.h", "rtl/top.sv"}
        context.add_preprocessor_dependencies(closure)
        edge_names = {edge.name for edge in context.macro_edges}
        self.assertIn("ASSERT_DEFAULT_RST", edge_names)
        self.assertIn("ASSERT_DEFAULT_CLK", edge_names)
        self.assertIn("ASSERT_FINAL", edge_names)
        self.assertNotIn("__name", edge_names)
        self.assertNotIn("__prop", edge_names)
        self.assertNotIn("__rst", edge_names)
        self.assertNotIn("__clk", edge_names)
        self.assertNotIn("KnownEnable", edge_names)

    def test_formal_parameter_names_are_not_global_providers(self):
        context = _ProjectContext(
            FIXTURE_ROOT,
            "t095_top",
            [],
            {"T095_USE_ALT": "1"},
            [],
            candidate_files=("rtl/asserts.h", "rtl/defaults.h", "rtl/top.sv"),
        )
        self.assertNotIn("__name", context.global_macro_providers)
        self.assertNotIn("__prop", context.global_macro_providers)
        self.assertNotIn("KnownEnable", context.global_macro_providers)

    def test_outside_formal_parameter_reference_fails_closed(self):
        with self.assertRaises(SourceSetError) as raised:
            from_filelist(
                filelist=FIXTURE_ROOT / "unknown.f",
                top="t095_unknown",
            )
        error = raised.exception
        self.assertEqual(error.code, "SOURCESET_DISCOVERY_FAILED")
        self.assertEqual(error.path, "rtl/unknown.sv")
        self.assertEqual(error.message, "macro has no provider: __name")
        self.assertEqual(error.details, [])


if __name__ == "__main__":
    unittest.main()
