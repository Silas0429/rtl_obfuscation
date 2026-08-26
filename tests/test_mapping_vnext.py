from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import unittest

from rtl_obfuscator.mapping_vnext import MappingVNextError, _validate_ranges, build_mapping_vnext
from rtl_obfuscator.rename_index import SymbolOccurrence, build_rename_index
from rtl_obfuscator.source_catalog import SourceRange, build_source_catalog
from rtl_obfuscator.source_set import from_filelist
from rtl_obfuscator.systemverilog_names import secure_name_factory


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "t108_pyslang_rename_index"


class MappingVNextTests(unittest.TestCase):
    def _mapping(self, categories):
        source_set = from_filelist(filelist=FIXTURE / "design.f", top="top")
        catalog = build_source_catalog(source_set)
        index = build_rename_index(catalog, categories=categories)
        return index, build_mapping_vnext(
            index, name_length=20, name_factory=secure_name_factory
        )

    def test_schema_two_contains_four_core_records_and_outcomes(self):
        index, mapping = self._mapping(("all",))
        report = mapping.to_report()
        self.assertEqual(mapping.format, "rtl-obfuscation.mapping")
        self.assertEqual(mapping.schema_version, 2)
        self.assertEqual(index.schema_version, 2)
        self.assertEqual(
            report["selection"]["selected_categories"],
            ["signals", "ports", "interface", "struct"],
        )
        self.assertEqual(
            [item["category"] for item in report["category_outcomes"]],
            ["signals", "ports", "interface", "struct"],
        )
        self.assertTrue(
            all(record["record_id"] == record["symbol_id"] for record in report["records"])
        )
        self.assertTrue(
            all("kind" in record and "semantic_kind" in record for record in report["records"])
        )
        self.assertTrue(
            all(record["action"] in {"rename", "preserve", "unsupported"} for record in report["records"])
        )
        self.assertGreater(
            sum(record["action"] == "rename" for record in report["records"]), 0
        )

    def test_selected_category_isolation_and_ranges_are_physical(self):
        index, mapping = self._mapping(("struct",))
        self.assertEqual(index.selected_categories, ("struct",))
        self.assertTrue(all(symbol.category == "struct" for symbol in index.symbols))
        report = mapping.to_report()
        ranges = []
        for record in report["records"]:
            self.assertEqual(record["category"], "struct")
            for item in [
                record["declaration"],
                *[entry["source_range"] for entry in record["occurrences"]],
            ]:
                data = (FIXTURE / item["file"]).read_bytes()
                self.assertEqual(
                    data[item["start"] : item["end"]],
                    record["original_name"].encode(),
                )
                ranges.append((item["file"], item["start"], item["end"]))
        self.assertEqual(len(ranges), len(set(ranges)))
        encoded = json.dumps(report, ensure_ascii=False, sort_keys=True)
        self.assertNotIn("symbol_graph", encoded)
        self.assertNotIn("rewrite_policy", encoded)

    def test_name_factory_collision_and_invalid_name_are_rejected(self):
        index, _mapping = self._mapping(("signals",))
        source_name = next(symbol.name for symbol in index.symbols if len(symbol.name) >= 4)

        with self.assertRaises(MappingVNextError) as collision:
            build_mapping_vnext(
                index,
                name_length=len(source_name),
                name_factory=lambda _symbol_id, _length, _unavailable: source_name,
            )
        self.assertEqual(collision.exception.code, "MAPPING_NAME_COLLISION")

        with self.assertRaises(MappingVNextError) as invalid:
            build_mapping_vnext(
                index,
                name_length=8,
                name_factory=lambda _symbol_id, _length, _unavailable: "9" * 8,
            )
        self.assertEqual(invalid.exception.code, "MAPPING_NAME_INVALID")

    def test_duplicate_and_overlap_ranges_fail_closed_before_mapping(self):
        _index, mapping = self._mapping(("signals",))
        symbols = mapping.rename_index.symbols
        symbol = symbols[0]
        duplicate = replace(
            symbol,
            occurrences=(
                SymbolOccurrence(symbol.declaration, "synthetic_duplicate"),
            ),
        )
        duplicate_index = replace(
            mapping.rename_index,
            symbols=(duplicate,),
            decisions=(replace(mapping.rename_index.decisions[0]),),
        )
        duplicate_file = symbol.declaration.file
        duplicate_sources = {
            file: (FIXTURE / file).read_bytes()
            for file in dict.fromkeys(
                (
                    *mapping.rename_index.source_catalog.source_set.ordered_source_files,
                    *mapping.rename_index.source_catalog.source_set.included_files,
                )
            )
        }
        with self.assertRaises(MappingVNextError) as exact:
            _validate_ranges(duplicate_index, (duplicate_file,), {duplicate_file: duplicate_sources[duplicate_file]})
        self.assertEqual(exact.exception.code, "MAPPING_RANGE_OVERLAP")

        overlap_symbol = replace(
            symbol,
            name="aaa",
            declaration=SourceRange("design.sv", 0, 3),
            occurrences=(
                SymbolOccurrence(SourceRange("design.sv", 2, 5), "synthetic_overlap"),
            ),
        )
        overlap_index = replace(
            mapping.rename_index,
            symbols=(overlap_symbol,),
            decisions=(replace(mapping.rename_index.decisions[0]),),
        )
        with self.assertRaises(MappingVNextError) as overlap:
            _validate_ranges(overlap_index, ("design.sv",), {"design.sv": b"aaaaa"})
        self.assertEqual(overlap.exception.code, "MAPPING_RANGE_OVERLAP")
