from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest import mock

import pyslang

from rtl_obfuscator.source_catalog import SourceCatalogError, build_source_catalog
from rtl_obfuscator.source_set import FilelistEntry, SourceSetError, from_filelist, from_project_root, from_single_file


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "t124_filelist_inventory_and_provenance"


class T124FilelistInventoryAndProvenanceTests(unittest.TestCase):
    def test_authoritative_filelist_is_structural_and_preserves_flattened_provenance(self):
        design = (FIXTURE / "design.f").resolve().as_posix()
        nested = (FIXTURE / "nested" / "child.f").resolve().as_posix()

        def fail(*_args, **_kwargs):
            raise AssertionError("authoritative filelist must not compile with PySlang")

        with mock.patch(
            "rtl_obfuscator.project_discovery.compile_pyslang_source_set", fail
        ), mock.patch.object(pyslang.syntax.SyntaxTree, "fromFiles", fail):
            source_set = from_filelist(
                filelist=FIXTURE / "design.f",
                source_root=FIXTURE,
                top="t124_top",
            )

        self.assertEqual(
            source_set.ordered_source_files,
            ("rtl/library.v", "rtl/child.sv", "rtl/top.sv"),
        )
        self.assertEqual(
            source_set.compile_order,
            (
                "include/context.svh",
                "include/context.vh",
                "include/context.h",
                "include/context.vic",
                "rtl/library.v",
                "rtl/child.sv",
                "rtl/top.sv",
            ),
        )
        self.assertEqual(
            source_set.included_files,
            (
                "include/context.svh",
                "include/context.vh",
                "include/context.h",
                "include/context.vic",
                "include/extra.svh",
            ),
        )
        self.assertEqual(source_set.include_dirs, ("include", "rtl"))
        self.assertEqual(
            source_set.defines,
            (
                ("NESTED_VALUE", "2"),
                ("ROOT_FLAG", "1"),
                ("ROOT_VALUE", "1"),
            ),
        )
        self.assertEqual(source_set.top_closure_files, ())
        self.assertTrue(all(isinstance(item, FilelistEntry) for item in source_set.filelist_entries))
        self.assertEqual(
            [
                (item.kind, item.value, item.filelist, item.line)
                for item in source_set.filelist_entries
            ],
            [
                ("include_dir", "include", design, 1),
                ("include_dir", "rtl", design, 1),
                ("define", "ROOT_VALUE=1", design, 2),
                ("define", "ROOT_FLAG", design, 2),
                ("library_source", "rtl/library.v", nested, 1),
                ("source", "rtl/child.sv", nested, 2),
                ("include_dir", "include", nested, 3),
                ("define", "NESTED_VALUE=2", nested, 4),
                ("source", "rtl/top.sv", design, 4),
                ("context_file", "include/context.svh", design, 5),
                ("context_file", "include/context.vh", design, 6),
                ("context_file", "include/context.h", design, 7),
                ("context_file", "include/context.vic", design, 8),
            ],
        )
        with self.assertRaises((AttributeError, TypeError)):
            source_set.filelist_entries = ()
        with self.assertRaises((AttributeError, TypeError)):
            source_set.filelist_entries[0].kind = "source"
        self.assertNotIn("filelist_entries", source_set.to_report())

    def test_large_authoritative_filelist_keeps_compilation_boundary(self):
        def fail(*_args, **_kwargs):
            raise AssertionError("large filelist must not create a PySlang compilation")

        with tempfile.TemporaryDirectory(prefix="t124-large-") as temporary:
            root = Path(temporary)
            entries = []
            for index in range(128):
                relative = Path("rtl") / f"unit_{index:03d}.sv"
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    f"module t124_unit_{index:03d}; endmodule\n",
                    encoding="utf-8",
                )
                entries.append(relative.as_posix())
            filelist = root / "design.f"
            filelist.write_text("".join(f"{item}\n" for item in entries), encoding="utf-8")

            with mock.patch(
                "rtl_obfuscator.project_discovery.compile_pyslang_source_set", fail
            ), mock.patch.object(pyslang.syntax.SyntaxTree, "fromFiles", fail):
                source_set = from_filelist(filelist=filelist, source_root=root)

        self.assertEqual(source_set.ordered_source_files, tuple(entries))
        self.assertEqual(len(source_set.filelist_entries), len(entries))
        self.assertEqual(source_set.top_closure_files, ())

    def test_structural_errors_remain_source_set_failures_and_semantic_errors_are_deferred(self):
        with tempfile.TemporaryDirectory(prefix="t124-errors-") as temporary:
            root = Path(temporary)
            missing = root / "missing.f"
            missing.write_text("rtl/does_not_exist.sv\n", encoding="utf-8")
            with self.assertRaises(SourceSetError) as raised:
                from_filelist(filelist=missing, source_root=root)
            self.assertEqual(raised.exception.code, "SOURCESET_FILE_NOT_FOUND")

            valid = root / "valid.f"
            valid.write_text("top.sv\n", encoding="utf-8")
            (root / "top.sv").write_text(
                "module t124_valid; endmodule\n", encoding="utf-8"
            )
            source_set = from_filelist(filelist=valid, source_root=root, top="missing_top")
            self.assertEqual(source_set.top_closure_files, ())
            with self.assertRaises(SourceCatalogError) as deferred:
                build_source_catalog(source_set)
            self.assertEqual(deferred.exception.code, "CATALOG_TOP_MISMATCH")

            invalid = root / "invalid.f"
            invalid.write_text("invalid.sv\n", encoding="utf-8")
            (root / "invalid.sv").write_text(
                "module t124_invalid( ; endmodule\n", encoding="utf-8"
            )
            invalid_set = from_filelist(filelist=invalid, source_root=root)
            with self.assertRaises(SourceCatalogError) as parse_failure:
                build_source_catalog(invalid_set)
            self.assertEqual(parse_failure.exception.code, "CATALOG_PARSE_FAILED")

    def test_non_filelist_adapters_keep_empty_provenance(self):
        single = from_single_file(
            source_file=ROOT / "tests" / "fixtures" / "refactor_source_set" / "rtl" / "standalone.sv",
            source_root=ROOT / "tests" / "fixtures" / "refactor_source_set",
        )
        project = from_project_root(
            project_root=ROOT / "tests" / "fixtures" / "refactor_source_set",
            top="top",
        )
        self.assertEqual(single.filelist_entries, ())
        self.assertEqual(project.filelist_entries, ())


if __name__ == "__main__":
    unittest.main()
