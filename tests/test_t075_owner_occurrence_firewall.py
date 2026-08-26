from __future__ import annotations

from pathlib import Path
import unittest

from rtl_obfuscator.mapping_vnext import build_mapping_vnext
from rtl_obfuscator.rename_index import build_rename_index
from rtl_obfuscator.source_catalog import build_source_catalog
from rtl_obfuscator.source_set import from_filelist
from rtl_obfuscator.systemverilog_names import secure_name_factory


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "t075_owner_occurrence_firewall"


class T075OwnerOccurrenceReplacementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source_set = from_filelist(
            filelist=FIXTURE_ROOT / "design.f", top="t075_top"
        )
        cls.catalog = build_source_catalog(cls.source_set)
        cls.index = build_rename_index(cls.catalog, categories=("all",))

    def test_one_catalog_semantic_view_drives_all_core_groups(self):
        self.assertEqual(
            self.catalog.to_report()["compile"],
            {
                "catalog": {"parse_errors": 0, "semantic_errors": 0},
                "top_overlay": {"parse_errors": 0, "semantic_errors": 0},
            },
        )
        self.assertIs(self.index.source_catalog, self.catalog)
        self.assertEqual(
            set(symbol.category for symbol in self.index.symbols),
            {"signals", "ports"},
        )
        self.assertEqual(
            tuple(self.source_set.compile_order),
            (
                "rtl/parameter_target.sv",
                "rtl/child.sv",
                "rtl/defparam_owner.sv",
                "rtl/sibling.sv",
                "rtl/top.sv",
            ),
        )

    def test_top_boundary_is_preserved_without_quarantining_other_owners(self):
        top_ports = [
            symbol
            for symbol in self.index.symbols
            if symbol.owner_module == "t075_top" and symbol.category == "ports"
        ]
        self.assertTrue(top_ports)
        self.assertTrue(
            all(
                symbol.support == "preserved"
                and symbol.reason == "selected_top_boundary"
                for symbol in top_ports
            )
        )
        child_state = next(
            symbol
            for symbol in self.index.symbols
            if symbol.owner_module == "t075_child"
            and symbol.category == "signals"
            and symbol.name == "child_state"
        )
        self.assertEqual((child_state.support, child_state.reason), ("eligible", None))
        self.assertFalse(
            any(symbol.reason == "occurrence_in_quarantined_owner" for symbol in self.index.symbols)
        )

    def test_mapping_ranges_are_unique_and_match_their_semantic_owner(self):
        mapping = build_mapping_vnext(
            self.index, name_length=16, name_factory=secure_name_factory
        )
        ranges = []
        for record in mapping.records:
            ranges.extend(
                [record.declaration]
                + [item.source_range for item in record.occurrences]
            )
            for source_range in (
                record.declaration,
                *(item.source_range for item in record.occurrences),
            ):
                data = (FIXTURE_ROOT / source_range.file).read_bytes()
                self.assertEqual(
                    data[source_range.start : source_range.end],
                    record.original_name.encode(),
                )
        self.assertEqual(
            len(ranges),
            len({(item.file, item.start, item.end) for item in ranges}),
        )


if __name__ == "__main__":
    unittest.main()
