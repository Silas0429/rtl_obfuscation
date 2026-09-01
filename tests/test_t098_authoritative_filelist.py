from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from rtl_obfuscator.project_discovery import _ProjectContext
from rtl_obfuscator.source_catalog import SourceCatalogError, build_source_catalog
from rtl_obfuscator.source_set import SourceSetError, from_filelist


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "t098_authoritative_filelist"
PUBLIC_ENCRYPT = ROOT / "rtl_encrypt.py"


class T098AuthoritativeFilelistTests(unittest.TestCase):
    def test_filelist_preserves_all_sources_and_defers_semantic_top_closure(self):
        all_sources = from_filelist(filelist=FIXTURE_ROOT / "design.f")
        expected_sources = (
            "rtl/t098_top.sv",
            "rtl/t098_child.sv",
            "rtl/t098_pkg.sv",
            "rtl/t098_if.sv",
            "rtl/t098_unused.sv",
        )
        self.assertEqual(all_sources.ordered_source_files, expected_sources)
        self.assertEqual(
            all_sources.compile_order,
            ("include/t098_macros.h",) + expected_sources,
        )
        self.assertEqual(all_sources.top_closure_files, ())
        self.assertEqual(all_sources.included_files, ("include/t098_macros.h",))

        selected = from_filelist(
            filelist=FIXTURE_ROOT / "design.f", top="t098_top"
        )
        self.assertEqual(selected.ordered_source_files, expected_sources)
        self.assertEqual(
            selected.compile_order,
            ("include/t098_macros.h",) + expected_sources,
        )
        self.assertEqual(selected.top_closure_files, ())
        catalog = build_source_catalog(selected)
        self.assertEqual(
            {module.name for module in catalog.modules if module.in_top_closure},
            {"t098_top", "t098_child"},
        )

    def test_h_context_is_shared_by_sourceset_and_catalog(self):
        source_set = from_filelist(
            filelist=FIXTURE_ROOT / "design.f", top="t098_top"
        )
        catalog = build_source_catalog(source_set)
        self.assertEqual(catalog.source_set.included_files, ("include/t098_macros.h",))
        self.assertEqual(catalog.top_closure_owner_ids, tuple(
            module.owner_id
            for module in catalog.modules
            if module.in_top_closure
        ))
        self.assertEqual(
            {module.name for module in catalog.modules if module.in_top_closure},
            {"t098_top", "t098_child"},
        )
        report = catalog.to_report()
        self.assertEqual(report["compile"]["catalog"], {"parse_errors": 0, "semantic_errors": 0})
        self.assertEqual(report["compile"]["top_overlay"], {"parse_errors": 0, "semantic_errors": 0})

    def test_missing_top_is_rejected_by_catalog_after_structural_sourceset(self):
        source_set = from_filelist(
            filelist=FIXTURE_ROOT / "design.f",
            top="DefinitelyMissingTop",
        )
        self.assertEqual(source_set.top_closure_files, ())
        with self.assertRaises(SourceCatalogError) as raised:
            build_source_catalog(source_set)
        self.assertEqual(raised.exception.code, "CATALOG_TOP_MISMATCH")

    def test_native_top_definition_cardinality_keeps_top_errors(self):
        ambiguous_set = from_filelist(
            filelist=FIXTURE_ROOT / "duplicate_top.f",
            top="t098_duplicate_top",
        )
        with self.assertRaises(SourceCatalogError) as ambiguous:
            build_source_catalog(ambiguous_set)
        self.assertEqual(ambiguous.exception.code, "CATALOG_DUPLICATE_MODULE")

        interface_set = from_filelist(
            filelist=FIXTURE_ROOT / "interface_only.f",
            top="t098_interface_only",
        )
        with self.assertRaises(SourceCatalogError) as interface_only:
            build_source_catalog(interface_set)
        self.assertEqual(interface_only.exception.code, "CATALOG_TOP_MISMATCH")

    def test_filelist_does_not_call_project_provider_discovery(self):
        def fail(*_args, **_kwargs):
            raise AssertionError("authoritative filelist called project provider discovery")

        with mock.patch.object(_ProjectContext, "add_preprocessor_dependencies", fail), \
                mock.patch.object(_ProjectContext, "add_type_dependencies", fail), \
                mock.patch.object(_ProjectContext, "expand_hierarchy", fail):
            for top in (None, "t098_top"):
                result = from_filelist(filelist=FIXTURE_ROOT / "design.f", top=top)
                self.assertEqual(len(result.ordered_source_files), 5)

    def test_missing_listed_dependency_is_pyslang_semantic_failure(self):
        source_set = from_filelist(
            filelist=FIXTURE_ROOT / "missing.f", top="t098_missing_top"
        )
        with self.assertRaises(SourceCatalogError) as raised:
            build_source_catalog(source_set)
        error = raised.exception
        self.assertEqual(error.code, "CATALOG_SEMANTIC_FAILED")

        with tempfile.TemporaryDirectory(prefix="t098-public-") as temporary:
            output = Path(temporary) / "gate"
            result = subprocess.run(
                [
                    sys.executable,
                    str(PUBLIC_ENCRYPT),
                    "--filelist",
                    str(FIXTURE_ROOT / "missing.f"),
                    "--top",
                    "t098_missing_top",
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
            self.assertIn("ORCHESTRATION_MAPPING_INVALID", result.stderr)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
