import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from rtl_obfuscator.source_set import (
    SourceSetError,
    from_filelist,
    from_project_root,
    from_single_file,
)


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "refactor_source_set"
INCLUDE_DIR = FIXTURE_ROOT / "include"
T087_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "t087_filelist_frontend"


class SourceSetTests(unittest.TestCase):
    def _options(self):
        return {"include_dirs": [INCLUDE_DIR], "defines": ["FEATURE", "WIDTH=8"]}

    def _without_origin(self, report):
        result = dict(report)
        result.pop("origin")
        return result

    def test_single_file_matches_equivalent_filelist(self):
        options = self._options()
        single = from_single_file(
            source_file=FIXTURE_ROOT / "rtl" / "standalone.sv",
            source_root=FIXTURE_ROOT,
            **options,
        )
        filelist = from_filelist(
            filelist=FIXTURE_ROOT / "single.f",
            source_root=FIXTURE_ROOT,
            **options,
        )
        self.assertEqual(
            self._without_origin(single.to_report()),
            self._without_origin(filelist.to_report()),
        )

    def test_filelist_preserves_order_and_top_filters_closure_only(self):
        options = self._options()
        all_files = from_filelist(
            filelist=FIXTURE_ROOT / "design.f",
            source_root=FIXTURE_ROOT,
            **options,
        )
        self.assertEqual(
            all_files.ordered_source_files,
            (
                "rtl/z_defs.sv",
                "rtl/a_child.sv",
                "rtl/top.sv",
                "rtl/unused.sv",
            ),
        )
        self.assertEqual(all_files.compile_order, all_files.ordered_source_files)

        selected = from_filelist(
            filelist=FIXTURE_ROOT / "design.f",
            source_root=FIXTURE_ROOT,
            top="top",
            **options,
        )
        self.assertIn("rtl/unused.sv", selected.ordered_source_files)
        self.assertNotIn("rtl/unused.sv", selected.top_closure_files)
        self.assertEqual(
            selected.top_closure_files,
            ("rtl/z_defs.sv", "rtl/a_child.sv", "rtl/top.sv"),
        )

    def test_project_root_keeps_only_top_closure(self):
        result = from_project_root(
            project_root=FIXTURE_ROOT,
            top="top",
            **self._options(),
        )
        self.assertEqual(
            result.ordered_source_files,
            ("rtl/z_defs.sv", "rtl/a_child.sv", "rtl/top.sv"),
        )
        self.assertEqual(result.ordered_source_files, result.compile_order)
        self.assertEqual(result.top_closure_files, result.ordered_source_files)
        self.assertNotIn("rtl/unused.sv", result.ordered_source_files)
        self.assertNotIn("rtl/standalone.sv", result.ordered_source_files)

    def test_project_root_matches_equivalent_closure_filelist(self):
        options = self._options()
        project_root = from_project_root(
            project_root=FIXTURE_ROOT,
            top="top",
            **options,
        )
        filelist = from_filelist(
            filelist=FIXTURE_ROOT / "closure.f",
            source_root=FIXTURE_ROOT,
            top="top",
            **options,
        )
        for field in (
            "include_dirs",
            "defines",
            "top",
            "top_closure_files",
            "compile_order",
        ):
            self.assertEqual(getattr(project_root, field), getattr(filelist, field))

    def test_header_is_only_an_included_file(self):
        result = from_filelist(
            filelist=FIXTURE_ROOT / "design.f",
            source_root=FIXTURE_ROOT,
            include_dirs=[INCLUDE_DIR],
        )
        self.assertEqual(result.included_files, ("include/common.svh",))
        self.assertNotIn("include/common.svh", result.ordered_source_files)
        self.assertNotIn("include/common.svh", result.compile_order)

    def test_stable_error_codes(self):
        with self.assertRaises(SourceSetError) as duplicate:
            from_filelist(
                filelist=FIXTURE_ROOT / "duplicate.f", source_root=FIXTURE_ROOT
            )
        self.assertEqual(duplicate.exception.code, "SOURCESET_DUPLICATE_FILE")
        self.assertTrue(str(duplicate.exception).startswith("SOURCESET_DUPLICATE_FILE: "))

        with self.assertRaises(SourceSetError) as outside:
            from_filelist(
                filelist=FIXTURE_ROOT / "outside.f", source_root=FIXTURE_ROOT
            )
        self.assertEqual(outside.exception.code, "SOURCESET_PATH_OUTSIDE_ROOT")

        with self.assertRaises(SourceSetError) as missing_definition:
            from_project_root(project_root=FIXTURE_ROOT, top="not_present")
        self.assertEqual(missing_definition.exception.code, "SOURCESET_TOP_NOT_FOUND")

        with self.assertRaises(SourceSetError) as missing_top:
            from_project_root(project_root=FIXTURE_ROOT)
        self.assertEqual(missing_top.exception.code, "SOURCESET_TOP_REQUIRED")

    def test_to_report_is_canonical_and_source_set_is_frozen(self):
        result = from_project_root(
            project_root=FIXTURE_ROOT, top="top", **self._options()
        )
        first = json.dumps(result.to_report(), sort_keys=True, separators=(",", ":"))
        second = json.dumps(result.to_report(), sort_keys=True, separators=(",", ":"))
        self.assertEqual(first, second)
        with self.assertRaises((AttributeError, TypeError)):
            result.top = "other"

    def test_adapters_use_project_discovery_source_of_truth(self):
        options = self._options()
        single = from_single_file(
            source_file=FIXTURE_ROOT / "rtl" / "standalone.sv",
            source_root=FIXTURE_ROOT,
            **options,
        )
        filelist = from_filelist(
            filelist=FIXTURE_ROOT / "design.f",
            source_root=FIXTURE_ROOT,
            **options,
        )
        project = from_project_root(project_root=FIXTURE_ROOT, top="top", **options)
        self.assertTrue(single.compile_order)
        self.assertTrue(filelist.compile_order)
        self.assertEqual(project.origin, "project-root")

    def test_t087_expands_environment_comments_and_nested_order(self):
        with mock.patch.dict(
            os.environ, {"T087_PROJ": str(T087_FIXTURE_ROOT)}, clear=False
        ):
            result = from_filelist(
                filelist=T087_FIXTURE_ROOT / "design.f",
                source_root=T087_FIXTURE_ROOT,
                top="top",
            )

        self.assertEqual(
            result.ordered_source_files,
            ("rtl/top.sv", "rtl/child.sv"),
        )
        self.assertEqual(result.compile_order, result.ordered_source_files)
        self.assertEqual(result.included_files, ("include/common.svh",))
        self.assertNotIn("rtl/ignored.sv", result.ordered_source_files)
        self.assertNotIn("$T087_PROJ", json.dumps(result.to_report()))
        self.assertNotIn("child.f", json.dumps(result.to_report()))

    def test_t087_absolute_and_environment_paths_normalize_identically(self):
        with mock.patch.dict(
            os.environ, {"T087_PROJ": str(T087_FIXTURE_ROOT)}, clear=False
        ):
            with tempfile.TemporaryDirectory() as temporary_directory:
                temporary_root = Path(temporary_directory)
                absolute_filelist = temporary_root / "absolute.f"
                variable_filelist = temporary_root / "variable.f"
                absolute_filelist.write_text(
                    f"{T087_FIXTURE_ROOT / 'rtl' / 'top.sv'}\n",
                    encoding="utf-8",
                )
                variable_filelist.write_text(
                    "$T087_PROJ/rtl/top.sv\n", encoding="utf-8"
                )
                absolute = from_filelist(
                    filelist=absolute_filelist, source_root=T087_FIXTURE_ROOT
                )
                variable = from_filelist(
                    filelist=variable_filelist, source_root=T087_FIXTURE_ROOT
                )

        self.assertEqual(absolute.ordered_source_files, ("rtl/top.sv",))
        self.assertEqual(absolute.ordered_source_files, variable.ordered_source_files)
        self.assertEqual(absolute.included_files, variable.included_files)

    def test_t087_nested_relative_entries_stay_source_root_based(self):
        with mock.patch.dict(
            os.environ, {"T087_PROJ": str(T087_FIXTURE_ROOT)}, clear=False
        ):
            with tempfile.TemporaryDirectory() as temporary_directory:
                top_filelist = Path(temporary_directory) / "top.f"
                top_filelist.write_text(
                    "-f $T087_PROJ/nested/relative.f\n", encoding="utf-8"
                )
                result = from_filelist(
                    filelist=top_filelist, source_root=T087_FIXTURE_ROOT
                )

        self.assertEqual(result.ordered_source_files, ("rtl/child.sv",))

    def test_t087_filelist_failures_are_stable_and_leave_no_sourceset(self):
        cases = (
            ("duplicate.f", "SOURCESET_DUPLICATE_FILE"),
            ("nested/cycle_a.f", "SOURCESET_FILELIST_CYCLE"),
            ("undefined_env.f", "SOURCESET_ENV_UNDEFINED"),
            ("outside.f", "SOURCESET_PATH_OUTSIDE_ROOT"),
            (
                "unsupported_directive.f",
                "SOURCESET_UNSUPPORTED_FILELIST_DIRECTIVE",
            ),
            ("missing_f_argument.f", "SOURCESET_INVALID_ARGUMENT"),
            ("missing_nested.f", "SOURCESET_FILE_NOT_FOUND"),
        )

        with mock.patch.dict(
            os.environ, {"T087_PROJ": str(T087_FIXTURE_ROOT)}, clear=False
        ):
            os.environ.pop("T087_MISSING", None)
            for relative_filelist, expected_code in cases:
                with self.subTest(relative_filelist=relative_filelist):
                    with self.assertRaises(SourceSetError) as raised:
                        from_filelist(
                            filelist=T087_FIXTURE_ROOT / relative_filelist,
                            source_root=T087_FIXTURE_ROOT,
                        )
                    self.assertEqual(raised.exception.code, expected_code)
                    self.assertTrue(
                        str(raised.exception).startswith(f"{expected_code}: ")
                    )


if __name__ == "__main__":
    unittest.main()
