import json
import os
from pathlib import Path
import unittest
from unittest import mock

from rtl_obfuscator.source_set import SourceSetError, from_filelist


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "t090_filelist_context"


class T090FilelistContextTests(unittest.TestCase):
    def _from_filelist(self, filelist="design.f", **options):
        with mock.patch.dict(
            os.environ, {"T090_PROJ": str(FIXTURE_ROOT)}, clear=False
        ):
            return from_filelist(
                filelist=FIXTURE_ROOT / filelist,
                source_root=FIXTURE_ROOT,
                **options,
            )

    def test_nested_context_is_normalized_in_source_order(self):
        result = self._from_filelist(
            include_dirs=[FIXTURE_ROOT / "rtl"],
            defines=["FEATURE=cli", "CLI_ONLY"],
            top="top",
        )

        self.assertEqual(result.ordered_source_files, ("rtl/top.v", "rtl/child.sv"))
        self.assertEqual(result.compile_order, result.ordered_source_files)
        self.assertEqual(result.included_files, ("include/feature.vh",))
        self.assertEqual(result.include_dirs, ("rtl", "include"))
        self.assertEqual(
            result.defines,
            (
                ("CHILD", "1"),
                ("CLI_ONLY", "1"),
                ("FEATURE", "cli"),
            ),
        )
        self.assertEqual(result.top_closure_files, ("rtl/top.v", "rtl/child.sv"))

        report_text = json.dumps(result.to_report(), sort_keys=True)
        self.assertNotIn("$T090_PROJ", report_text)
        self.assertNotIn("+incdir+", report_text)
        self.assertNotIn("+define+", report_text)

    def test_filelist_context_error_codes_are_stable(self):
        cases = (
            ("undefined_include.f", "SOURCESET_ENV_UNDEFINED"),
            ("missing_include.f", "SOURCESET_FILE_NOT_FOUND"),
            ("outside_include.f", "SOURCESET_PATH_OUTSIDE_ROOT"),
            ("unsupported_context.f", "SOURCESET_UNSUPPORTED_FILELIST_DIRECTIVE"),
        )
        with mock.patch.dict(
            os.environ, {"T090_PROJ": str(FIXTURE_ROOT)}, clear=False
        ):
            os.environ.pop("T090_MISSING", None)
            for relative_filelist, expected_code in cases:
                with self.subTest(relative_filelist=relative_filelist):
                    with self.assertRaises(SourceSetError) as raised:
                        from_filelist(
                            filelist=FIXTURE_ROOT / relative_filelist,
                            source_root=FIXTURE_ROOT,
                        )
                    self.assertEqual(raised.exception.code, expected_code)
                    self.assertTrue(
                        str(raised.exception).startswith(f"{expected_code}: ")
                    )


if __name__ == "__main__":
    unittest.main()
