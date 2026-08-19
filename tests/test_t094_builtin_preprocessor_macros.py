from __future__ import annotations

from pathlib import Path
import unittest

from rtl_obfuscator.project_discovery import _ProjectContext
from rtl_obfuscator.source_set import SourceSetError, from_filelist


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "t094_builtin_preprocessor_macros"


class BuiltinPreprocessorMacroTests(unittest.TestCase):
    def test_builtin_macros_are_environment_defined_without_dependencies(self):
        result = from_filelist(
            filelist=FIXTURE_ROOT / "design.f",
            top="t094_top",
        )
        self.assertEqual(result.ordered_source_files, ("rtl/top.sv",))
        self.assertEqual(result.top_closure_files, ("rtl/top.sv",))
        self.assertEqual(result.compile_order, ("rtl/top.sv",))
        self.assertEqual(result.included_files, ())
        report = result.to_report()
        for macro in (
            "__FILE__",
            "__LINE__",
            "__DATE__",
            "__TIME__",
            "__TIMESTAMP__",
        ):
            self.assertNotIn(macro, report)

        context = _ProjectContext(
            FIXTURE_ROOT,
            "t094_top",
            [],
            {},
            [],
            candidate_files=("rtl/top.sv",),
        )
        closure = {"rtl/top.sv"}
        context.add_preprocessor_dependencies(closure)
        self.assertEqual(context.macro_edges, set())

    def test_unknown_macro_still_fails_closed(self):
        with self.assertRaises(SourceSetError) as raised:
            from_filelist(
                filelist=FIXTURE_ROOT / "unknown.f",
                top="t094_unknown",
            )
        error = raised.exception
        self.assertEqual(error.code, "SOURCESET_DISCOVERY_FAILED")
        self.assertEqual(error.path, "rtl/unknown.sv")
        self.assertEqual(
            error.message,
            "filelist PySlang compilation contains parse errors",
        )
        self.assertEqual(
            error.details,
            [
                {
                    "code": "DiagCode(UnknownDirective)",
                    "path": "rtl/unknown.sv",
                    "start": 39,
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
