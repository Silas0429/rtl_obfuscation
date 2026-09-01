from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from rtl_obfuscator.source_catalog import build_source_catalog
from rtl_obfuscator.source_set import SourceSetError, from_filelist, from_project_root


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "t033_impact_category"


class ProjectRootInspectTests(unittest.TestCase):
    def test_project_root_discovers_only_top_closure_in_compile_order(self):
        source_set = from_project_root(project_root=FIXTURE, top="t033_top")
        self.assertEqual(source_set.origin, "project-root")
        self.assertEqual(source_set.top, "t033_top")
        self.assertEqual(source_set.ordered_source_files, (
            "bus_if.sv", "shared.sv", "child.sv", "top.sv",
        ))
        self.assertNotIn("decoy.sv", source_set.ordered_source_files)
        catalog = build_source_catalog(source_set)
        self.assertEqual(catalog.to_report()["compile"], {
            "catalog": {"parse_errors": 0, "semantic_errors": 0},
            "top_overlay": {"parse_errors": 0, "semantic_errors": 0},
        })

    def test_equivalent_closure_filelist_preserves_source_contract(self):
        project_set = from_project_root(project_root=FIXTURE, top="t033_top")
        with tempfile.TemporaryDirectory(prefix="t056-inspect-") as temporary:
            filelist = Path(temporary) / "closure.f"
            filelist.write_text("bus_if.sv\nshared.sv\nchild.sv\ntop.sv\n", encoding="utf-8")
            filelist_set = from_filelist(filelist=filelist, source_root=FIXTURE, top="t033_top")
        self.assertEqual(project_set.ordered_source_files, filelist_set.ordered_source_files)
        self.assertEqual(filelist_set.top_closure_files, ())
        self.assertEqual(project_set.compile_order, filelist_set.compile_order)

    def test_invalid_project_root_top_fails_closed(self):
        with self.assertRaises(SourceSetError) as raised:
            from_project_root(project_root=FIXTURE, top="not_a_module")
        self.assertEqual(raised.exception.code, "SOURCESET_TOP_NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
