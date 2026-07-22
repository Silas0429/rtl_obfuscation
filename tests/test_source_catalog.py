from dataclasses import fields, replace
import json
from pathlib import Path
import unittest
from unittest import mock

from rtl_obfuscator import inventory, project
from rtl_obfuscator.source_catalog import (
    SourceCatalogError,
    build_source_catalog,
)
from rtl_obfuscator.source_set import from_filelist, from_project_root, from_single_file


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "refactor_source_catalog"
INVALID_ROOT = Path(__file__).parent / "fixtures" / "refactor_source_catalog_invalid"


class SourceCatalogTests(unittest.TestCase):
    def _catalog(self, filelist: Path, *, top: str | None = None):
        source_set = from_filelist(
            filelist=filelist,
            source_root=FIXTURE_ROOT,
            top=top,
        )
        return build_source_catalog(source_set)

    @staticmethod
    def _without_origin(report: dict) -> dict:
        result = dict(report)
        source_set = dict(result["source_set"])
        source_set.pop("origin")
        result["source_set"] = source_set
        return result

    def test_catalog_without_top_contains_all_physical_modules(self):
        catalog = self._catalog(FIXTURE_ROOT / "design.f")
        self.assertEqual(
            [module.name for module in catalog.modules],
            ["child", "colocated_unused", "standalone", "top", "unreachable"],
        )
        self.assertEqual(catalog.top_closure_owner_ids, ())
        self.assertIsNone(catalog.top_compilation)
        self.assertIsNone(catalog.top_root)
        self.assertIsNone(catalog.top_source_manager)
        self.assertTrue(
            all(
                not module.in_top_closure and not module.is_selected_top
                for module in catalog.modules
            )
        )

    def test_filelist_top_catalogs_all_modules_but_closes_top_and_child(self):
        catalog = self._catalog(FIXTURE_ROOT / "design.f", top="top")
        self.assertEqual(len(catalog.modules), 5)
        closure = {
            module.name
            for module in catalog.modules
            if module.in_top_closure
        }
        self.assertEqual(closure, {"top", "child"})
        self.assertEqual(
            [module.name for module in catalog.modules if module.is_selected_top],
            ["top"],
        )
        self.assertEqual(
            catalog.top_closure_owner_ids,
            tuple(
                module.owner_id
                for module in catalog.modules
                if module.in_top_closure
            ),
        )

    def test_repeated_child_instances_share_one_owner(self):
        catalog = self._catalog(FIXTURE_ROOT / "design.f", top="top")
        children = [module for module in catalog.modules if module.name == "child"]
        self.assertEqual(len(children), 1)
        self.assertIn(children[0].owner_id, catalog.top_closure_owner_ids)

    def test_colocated_uninstantiated_module_is_not_in_top_closure(self):
        catalog = self._catalog(FIXTURE_ROOT / "design.f", top="top")
        colocated = next(
            module for module in catalog.modules if module.name == "colocated_unused"
        )
        self.assertFalse(colocated.in_top_closure)
        self.assertFalse(colocated.is_selected_top)

    def test_project_root_matches_equivalent_closure_filelist(self):
        project_catalog = build_source_catalog(
            from_project_root(project_root=FIXTURE_ROOT, top="top")
        )
        filelist_catalog = self._catalog(FIXTURE_ROOT / "closure.f", top="top")
        self.assertEqual(
            self._without_origin(project_catalog.to_report()),
            self._without_origin(filelist_catalog.to_report()),
        )

    def test_single_file_matches_equivalent_single_filelist(self):
        single_catalog = build_source_catalog(
            from_single_file(
                source_file=FIXTURE_ROOT / "rtl" / "standalone.sv",
                source_root=FIXTURE_ROOT,
            )
        )
        filelist_catalog = self._catalog(FIXTURE_ROOT / "single.f")
        self.assertEqual(
            self._without_origin(single_catalog.to_report()),
            self._without_origin(filelist_catalog.to_report()),
        )

    def test_owner_ranges_bytes_sorting_and_uniqueness(self):
        catalog = self._catalog(FIXTURE_ROOT / "design.f", top="top")
        declarations = [
            (
                module.declaration.file,
                module.declaration.start,
                module.declaration.end,
                module.name,
            )
            for module in catalog.modules
        ]
        self.assertEqual(declarations, sorted(declarations))
        self.assertEqual(
            len({module.owner_id for module in catalog.modules}), len(catalog.modules)
        )
        self.assertEqual(
            len({
                (
                    module.declaration.file,
                    module.declaration.start,
                    module.declaration.end,
                )
                for module in catalog.modules
            }),
            len(catalog.modules),
        )
        for module in catalog.modules:
            source = (FIXTURE_ROOT / module.declaration.file).read_bytes()
            source_range = module.declaration
            self.assertGreaterEqual(source_range.start, 0)
            self.assertLess(source_range.start, source_range.end)
            self.assertLessEqual(source_range.end, len(source))
            self.assertEqual(
                source[source_range.start : source_range.end],
                module.name.encode("utf-8"),
            )
            self.assertEqual(
                module.owner_id,
                f"module:{source_range.file}:{source_range.start}:{source_range.end}",
            )

    def test_report_is_canonical_and_py_sl_data_is_not_reported(self):
        catalog = self._catalog(FIXTURE_ROOT / "design.f", top="top")
        first = json.dumps(catalog.to_report(), sort_keys=True, separators=(",", ":"))
        second = json.dumps(catalog.to_report(), sort_keys=True, separators=(",", ":"))
        self.assertEqual(first, second)
        report = catalog.to_report()
        self.assertEqual(report["source_set"], catalog.source_set.to_report())
        for field in fields(catalog):
            if field.name in {
                "catalog_compilation",
                "catalog_root",
                "catalog_source_manager",
                "top_compilation",
                "top_root",
                "top_source_manager",
            }:
                self.assertFalse(field.repr)
                self.assertFalse(field.compare)
                self.assertNotIn(field.name, report)

    def test_duplicate_module_fails_stably(self):
        source_set = from_filelist(
            filelist=INVALID_ROOT / "duplicate.f",
            source_root=INVALID_ROOT,
        )
        with self.assertRaises(SourceCatalogError) as raised:
            build_source_catalog(source_set)
        self.assertEqual(raised.exception.code, "CATALOG_DUPLICATE_MODULE")
        self.assertTrue(str(raised.exception).startswith("CATALOG_DUPLICATE_MODULE: "))

    def test_missing_selected_top_fails_before_overlay_semantic_error(self):
        source_set = from_filelist(
            filelist=FIXTURE_ROOT / "design.f",
            source_root=FIXTURE_ROOT,
        )
        missing_top_source_set = replace(source_set, top="not_present")
        with self.assertRaises(SourceCatalogError) as raised:
            build_source_catalog(missing_top_source_set)
        self.assertEqual(raised.exception.code, "CATALOG_TOP_MISMATCH")

    def test_catalog_does_not_call_legacy_inventory_paths(self):
        source_set = from_filelist(
            filelist=FIXTURE_ROOT / "design.f",
            source_root=FIXTURE_ROOT,
            top="top",
        )
        with (
            mock.patch.object(
                project, "analyze_project", side_effect=AssertionError("legacy path")
            ),
            mock.patch.object(
                project,
                "analyze_project_context",
                side_effect=AssertionError("legacy path"),
            ),
            mock.patch.object(
                project,
                "analyze_filelist_context",
                side_effect=AssertionError("legacy path"),
            ),
            mock.patch.object(
                inventory,
                "build_top_project_inventory",
                side_effect=AssertionError("inventory path"),
            ),
        ):
            build_source_catalog(source_set)


if __name__ == "__main__":
    unittest.main()
