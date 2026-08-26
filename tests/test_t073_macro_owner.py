from __future__ import annotations

from pathlib import Path
import unittest

from rtl_obfuscator.mapping_vnext import build_mapping_vnext
from rtl_obfuscator.rename_index import build_rename_index
from rtl_obfuscator.source_catalog import build_source_catalog
from rtl_obfuscator.source_set import from_filelist
from rtl_obfuscator.systemverilog_names import secure_name_factory


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "t073_macro_owner"


class T073MacroOwnerReplacementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source_set = from_filelist(
            filelist=FIXTURE_ROOT / "design.f", top="t073_top"
        )
        cls.catalog = build_source_catalog(cls.source_set)
        cls.index = build_rename_index(cls.catalog, categories=("all",))

    def test_macro_argument_provenance_is_physical_and_source_less_declaration_is_ignored(self):
        self.assertEqual(
            self.catalog.to_report()["compile"],
            {
                "catalog": {"parse_errors": 0, "semantic_errors": 0},
                "top_overlay": {"parse_errors": 0, "semantic_errors": 0},
            },
        )
        argument_occurrences = [
            occurrence
            for symbol in self.index.symbols
            for occurrence in symbol.occurrences
            if occurrence.provenance == "semantic_macro_argument"
        ]
        self.assertTrue(argument_occurrences)
        self.assertNotIn(
            "macro_state",
            {symbol.name for symbol in self.index.symbols},
            "macro-generated declaration has no physical identifier range",
        )
        for occurrence in argument_occurrences:
            data = (FIXTURE_ROOT / occurrence.source_range.file).read_bytes()
            self.assertGreaterEqual(occurrence.source_range.start, 0)
            self.assertEqual(
                data[occurrence.source_range.start : occurrence.source_range.end],
                next(
                    symbol.name.encode()
                    for symbol in self.index.symbols
                    if occurrence in symbol.occurrences
                ),
            )

    def test_macro_owner_confidence_is_symbol_level_and_ranges_are_unique(self):
        macro_symbols = [
            symbol
            for symbol in self.index.symbols
            if symbol.owner_module in {
                "t073_macro_target",
                "t073_macro_owner",
                "t073_macro_statement_owner",
            }
        ]
        self.assertTrue(macro_symbols)
        self.assertFalse(
            any(symbol.reason == "owner_contains_macro_source" for symbol in macro_symbols)
        )
        ranges = []
        for symbol in self.index.symbols:
            ranges.extend(
                [symbol.declaration]
                + [occurrence.source_range for occurrence in symbol.occurrences]
            )
        self.assertEqual(
            len(ranges),
            len({(item.file, item.start, item.end) for item in ranges}),
        )

    def test_schema_two_mapping_keeps_only_proven_ranges_editable(self):
        mapping = build_mapping_vnext(
            self.index, name_length=16, name_factory=secure_name_factory
        )
        self.assertEqual(mapping.schema_version, 2)
        self.assertEqual(mapping.format, "rtl-obfuscation.mapping")
        for record in mapping.records:
            if record.action != "rename":
                continue
            for source_range in (
                record.declaration,
                *(item.source_range for item in record.occurrences),
            ):
                data = (FIXTURE_ROOT / source_range.file).read_bytes()
                self.assertEqual(
                    data[source_range.start : source_range.end],
                    record.original_name.encode(),
                )


if __name__ == "__main__":
    unittest.main()
