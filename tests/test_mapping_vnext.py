from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from rtl_obfuscator.mapping_vnext import MappingVNextError, _validate_ranges, build_mapping_vnext
from rtl_obfuscator.rename_index import SymbolOccurrence, build_rename_index
from rtl_obfuscator.source_catalog import (
    ReadonlyDuplicate,
    SourceRange,
    build_source_catalog,
)
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

    def test_readonly_duplicate_inventory_is_exact_and_preserve_records(self):
        with tempfile.TemporaryDirectory(prefix="mapping-readonly-duplicate-") as temporary:
            root = Path(temporary)
            (root / "owned").mkdir()
            (root / "external").mkdir()
            (root / "owned/top.sv").write_text(
                "module tmap_top(); endmodule\n", encoding="utf-8"
            )
            duplicate = "module tmap_duplicate(); logic duplicate_signal; endmodule\n"
            (root / "external/lib_a.sv").write_text(duplicate, encoding="utf-8")
            (root / "external/lib_b.sv").write_text(duplicate, encoding="utf-8")
            other_duplicate = "module tmap_other(); logic other_signal; endmodule\n"
            (root / "external/lib_c.sv").write_text(other_duplicate, encoding="utf-8")
            (root / "external/lib_d.sv").write_text(other_duplicate, encoding="utf-8")
            filelist = root / "design.f"
            filelist.write_text(
                "owned/top.sv\n-v external/lib_a.sv\n-v external/lib_b.sv\n"
                "-v external/lib_c.sv\n-v external/lib_d.sv\n",
                encoding="utf-8",
            )
            source_set = from_filelist(
                filelist=filelist,
                source_root=root,
                top="tmap_top",
                rewrite_roots=(root / "owned",),
            )
            catalog = build_source_catalog(source_set)
            index = build_rename_index(catalog, categories=("all",))
            mapping = build_mapping_vnext(
                index, name_length=20, name_factory=secure_name_factory
            )
            self.assertEqual(len(mapping.records), len(mapping.rename_index.symbols))
            self.assertTrue(all(record.action == "preserve" for record in mapping.records))
            self.assertTrue(all(record.renamed_name is None for record in mapping.records))
            report = mapping.to_report()
            self.assertEqual(
                report["category_outcomes"],
                [dict(item) for item in index.category_outcomes],
            )
            self.assertEqual(report["summary"]["rename"], 0)
            self.assertEqual(report["summary"]["preserve"], len(mapping.records))
            duplicate_entry = catalog.readonly_duplicate_inventory[0]
            self.assertEqual(
                tuple(item.file for item in duplicate_entry.declarations),
                ("external/lib_a.sv", "external/lib_b.sv"),
            )

            def assert_invalid(mutated_catalog):
                with self.assertRaises(MappingVNextError) as raised:
                    build_mapping_vnext(
                        replace(index, source_catalog=mutated_catalog),
                        name_length=20,
                        name_factory=secure_name_factory,
                    )
                self.assertEqual(raised.exception.code, "MAPPING_SOURCE_INVALID")

            def assert_invalid_index(mutated_index):
                with self.assertRaises(MappingVNextError) as raised:
                    build_mapping_vnext(
                        mutated_index,
                        name_length=20,
                        name_factory=secure_name_factory,
                    )
                self.assertEqual(raised.exception.code, "MAPPING_SOURCE_INVALID")
                self.assertIn("readonly duplicate", str(raised.exception).lower())

            assert_invalid(replace(catalog, readonly_duplicate_inventory=()))
            assert_invalid(
                replace(
                    catalog,
                    readonly_duplicate_inventory=(
                        *catalog.readonly_duplicate_inventory,
                        ReadonlyDuplicate(
                            "tmap_extra",
                            duplicate_entry.declarations,
                        ),
                    ),
                )
            )
            assert_invalid(
                replace(
                    catalog,
                    readonly_duplicate_inventory=(
                        ReadonlyDuplicate(
                            duplicate_entry.name,
                            (
                                duplicate_entry.declarations[0],
                                SourceRange("external/lib_b.sv", 0, 1),
                            ),
                        ),
                    ),
                )
            )
            duplicate_modules = [
                module
                for module in catalog.modules
                if module.name == duplicate_entry.name
            ]
            forged_modules = tuple(
                replace(module, in_top_closure=True)
                if module is duplicate_modules[0]
                else module
                for module in catalog.modules
            )
            assert_invalid(replace(catalog, modules=forged_modules))
            assert_invalid(
                replace(
                    catalog,
                    readonly_duplicate_inventory=tuple(
                        reversed(catalog.readonly_duplicate_inventory)
                    ),
                )
            )

            external_index = next(
                position
                for position, symbol in enumerate(index.symbols)
                if symbol.declaration.file.startswith("external/")
            )
            decisions = list(index.decisions)
            decisions[external_index] = replace(
                decisions[external_index], action="rename", reason=None
            )
            assert_invalid_index(replace(index, decisions=tuple(decisions)))
            symbols = list(index.symbols)
            symbols[external_index] = replace(symbols[external_index], support="eligible")
            assert_invalid_index(replace(index, symbols=tuple(symbols)))
