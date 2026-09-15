"""Main-Agent frozen performance and fail-closed oracles for T140."""

from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import rtl_obfuscator.source_catalog as catalog_module
from rtl_obfuscator.source_catalog import SourceCatalogError, SourceRange, build_source_catalog
from rtl_obfuscator.source_set import from_filelist


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/t125_single_view_rewrite_root_catalog"
TOP_TEXT = "module t140_top(input logic a, output logic y); assign y = a; endmodule\n"


class T140CatalogMetadataIndexTests(unittest.TestCase):
    def test_one_complete_membership_set_per_build_in_all_three_branches(self):
        rows = []
        for top, scoped in ((None, False), ("t125_top", False), ("t125_top", True)):
            with self.subTest(top=top, scoped=scoped):
                source = from_filelist(filelist=FIXTURE / "design.f", top=top,
                    rewrite_roots=(FIXTURE / "owned",) if scoped else ())
                real = catalog_module._known_physical_files
                with patch.object(catalog_module, "_known_physical_files", wraps=real) as known:
                    first = build_source_catalog(source)
                    first_calls = known.call_count
                    second = build_source_catalog(source)
                self.assertEqual(first.to_report(), second.to_report())
                self.assertEqual(first.semantic_owner_ids, second.semantic_owner_ids)
                self.assertEqual(first_calls, 1)
                self.assertEqual(known.call_count, 2)
                self.assertEqual(real(source), frozenset((*source.compile_order, *source.included_files)))
                rows.append({"top": top, "scoped": scoped, "membership_builds": first_calls})
        print("T140_MEMBERSHIP_JSON=" + json.dumps(rows, sort_keys=True))

    def test_top_closure_matching_is_not_quadratic(self):
        rows = []
        for count in (16, 64):
            with self.subTest(leaves=count), tempfile.TemporaryDirectory(prefix="t140-index-") as temp:
                root = Path(temp)
                leaves = "".join(f"module leaf_{i}(); endmodule\n" for i in range(count))
                instances = "".join(f"leaf_{i} u{i}();\n" for i in range(count))
                (root / "design.sv").write_text(leaves + "module t140_top();\n" + instances + "endmodule\n")
                (root / "design.f").write_text("design.sv\n")
                source = from_filelist(filelist=root / "design.f", top="t140_top", rewrite_roots=(root,))
                active = False
                comparisons = 0
                original_equal = SourceRange.__eq__

                def observe(stage, phase):
                    nonlocal active
                    active = stage == "compile.top_closure" and phase == "begin"

                def equal(left, right):
                    nonlocal comparisons
                    if active:
                        comparisons += 1
                    return original_equal(left, right)

                with patch.object(SourceRange, "__eq__", new=equal):
                    catalog = build_source_catalog(source, stage_observer=observe)
                self.assertEqual(len(catalog.modules), count + 1)
                self.assertEqual(len(catalog.top_closure_owner_ids), count + 1)
                self.assertLessEqual(comparisons, 3 * (count + 1))
                rows.append({"physical_modules": count + 1, "range_comparisons": comparisons})
        print("T140_LOOKUP_JSON=" + json.dumps(rows, sort_keys=True))

    def test_repeated_access_revalidates_live_file_and_token(self):
        for change in ("delete", "directory", "same_size_bytes", "symlink_escape"):
            with self.subTest(change=change), tempfile.TemporaryDirectory(prefix="t140-live-") as temp:
                base = Path(temp)
                root = base / "project"
                root.mkdir()
                target = root / "design.sv"
                target.write_text(TOP_TEXT)
                (root / "design.f").write_text("design.sv\n")
                external = base / "outside.sv"
                external.write_text(TOP_TEXT)
                source = from_filelist(filelist=root / "design.f", top="t140_top", rewrite_roots=(root,))
                real = catalog_module._read_physical_token
                reads = 0

                def read(*args, **kwargs):
                    nonlocal reads
                    result = real(*args, **kwargs)
                    reads += 1
                    if reads == 1:
                        if change == "same_size_bytes":
                            target.write_text(TOP_TEXT.replace("t140_top", "x140_top"))
                        else:
                            target.unlink()
                            if change == "directory":
                                target.mkdir()
                            elif change == "symlink_escape":
                                target.symlink_to(external)
                    return result

                with patch.object(catalog_module, "_read_physical_token", new=read):
                    with self.assertRaises(SourceCatalogError) as raised:
                        build_source_catalog(source)
                self.assertEqual(raised.exception.code, "CATALOG_RANGE_INVALID")

    def test_index_miss_still_fails_closed(self):
        source = from_filelist(filelist=FIXTURE / "design.f", top="t125_top",
                               rewrite_roots=(FIXTURE / "owned",))
        real = catalog_module._physical_module_declarations

        def omit_top(*args, **kwargs):
            return tuple(item for item in real(*args, **kwargs) if item.name != "t125_top")

        with patch.object(catalog_module, "_physical_module_declarations", new=omit_top):
            with self.assertRaises(SourceCatalogError) as raised:
                build_source_catalog(source)
        self.assertEqual(raised.exception.code, "CATALOG_TOP_MISMATCH")

    def test_source_set_replacement_does_not_reuse_membership(self):
        source = from_filelist(filelist=FIXTURE / "design.f", top="t125_top",
                               rewrite_roots=(FIXTURE / "owned",))
        rebuilt = replace(source, rewrite_roots=())
        self.assertEqual(source, rebuilt)  # compare=False is not a cache key.
        real = catalog_module._known_physical_files
        with patch.object(catalog_module, "_known_physical_files", wraps=real) as known:
            first = build_source_catalog(source)
            second = build_source_catalog(rebuilt)
        self.assertEqual(known.call_count, 2)
        self.assertIs(first.catalog_root, first.top_root)
        self.assertIsNot(second.catalog_root, second.top_root)


if __name__ == "__main__":
    unittest.main()
