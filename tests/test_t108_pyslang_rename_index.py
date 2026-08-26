from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from rtl_obfuscator.mapping_vnext import build_mapping_vnext
from rtl_obfuscator.rename_index import (
    SymbolOccurrence,
    _WorkingSymbol,
    _claim_occurrence,
    _resolve_range_claims,
    build_rename_index,
)
from rtl_obfuscator.rewrite_vnext import restore_gate_vnext, write_gate_vnext
from rtl_obfuscator.source_catalog import SourceRange, build_source_catalog
from rtl_obfuscator.source_set import from_filelist
from rtl_obfuscator.systemverilog_names import secure_name_factory


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "t108_pyslang_rename_index"


class T108RenameIndexTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source_set = from_filelist(filelist=FIXTURE / "design.f", top="top")
        cls.catalog = build_source_catalog(cls.source_set)
        cls.boundary_source_set = from_filelist(
            filelist=FIXTURE / "boundary.f", top="boundary_top"
        )
        cls.boundary_catalog = build_source_catalog(cls.boundary_source_set)

    def test_modport_ports_are_alias_occurrences_of_interface_members(self):
        index = build_rename_index(self.catalog, categories=("interface",))
        records = {(item.kind, item.name): item for item in index.symbols}
        self.assertNotIn(("modport_member", "valid"), records)
        self.assertNotIn(("modport_member", "ready"), records)
        valid = records[("interface_member", "valid")]
        ready = records[("interface_member", "ready")]
        self.assertIn(
            "semantic_modport_member",
            {item.provenance for item in valid.occurrences},
        )
        self.assertIn(
            "semantic_modport_member",
            {item.provenance for item in ready.occurrences},
        )
        for record in (valid, ready):
            for occurrence in record.occurrences:
                data = (FIXTURE / occurrence.source_range.file).read_bytes()
                self.assertEqual(
                    data[occurrence.source_range.start : occurrence.source_range.end],
                    record.name.encode(),
                )

    def test_struct_member_reference_uses_direct_field_symbol_location(self):
        index = build_rename_index(self.catalog, categories=("struct",))
        flag = next(
            item
            for item in index.symbols
            if item.name == "flag" and item.owner_module == "$unit"
        )
        self.assertEqual(flag.kind, "struct_field")
        self.assertEqual(flag.semantic_kind, "FieldSymbol")
        self.assertTrue(flag.occurrences)
        self.assertTrue(
            any(item.provenance == "semantic_member" for item in flag.occurrences)
        )
        for occurrence in flag.occurrences:
            data = (FIXTURE / occurrence.source_range.file).read_bytes()
            self.assertEqual(
                data[occurrence.source_range.start : occurrence.source_range.end],
                b"flag",
            )

    def test_macro_typedef_and_conversion_shapes_are_semantically_scoped(self):
        index = build_rename_index(self.catalog, categories=("all",))
        macro_argument = [
            occurrence
            for symbol in index.symbols
            for occurrence in symbol.occurrences
            if occurrence.provenance == "semantic_macro_argument"
        ]
        macro_body = [
            occurrence
            for symbol in index.symbols
            for occurrence in symbol.occurrences
            if occurrence.provenance == "semantic_macro_body"
        ]
        self.assertTrue(macro_argument)
        self.assertTrue(macro_body)
        conflict = [
            symbol
            for symbol in index.symbols
            if symbol.name == "t108_shared_body"
        ]
        self.assertEqual(len(conflict), 2)
        self.assertTrue(
            all(
                symbol.support == "unsupported"
                and symbol.reason == "macro_origin_conflict"
                for symbol in conflict
            )
        )
        signals_outcome = next(
            item for item in index.category_outcomes if item["category"] == "signals"
        )
        macro_issues = [
            item
            for item in signals_outcome["issues"]
            if item["message"] == "macro_origin_conflict"
        ]
        self.assertIn(
            {"file": "macros.svh", "start": 84, "end": 100, "message": "macro_origin_conflict"},
            macro_issues,
        )
        self.assertEqual(
            {
                item["start"]
                for item in macro_issues
                if item["file"] == "design.sv"
            },
            {symbol.declaration.start for symbol in conflict},
        )
        self.assertFalse(
            any(
                occurrence.source_range == SourceRange("macros.svh", 84, 100)
                for symbol in conflict
                for occurrence in symbol.occurrences
            )
        )
        payload_aliases = [
            symbol
            for symbol in index.symbols
            if symbol.category == "struct"
            and symbol.kind == "struct_type"
            and symbol.name == "payload_t"
        ]
        self.assertEqual(len(payload_aliases), 2)
        self.assertNotIn(
            "payload_parameter_t",
            {symbol.name for symbol in index.symbols},
        )
        self.assertTrue(
            any(
                occurrence.provenance == "semantic_cast"
                for symbol in payload_aliases
                for occurrence in symbol.occurrences
            )
        )

    def test_unknown_struct_shape_is_a_boundary_and_preserves_the_struct_group(self):
        index = build_rename_index(self.boundary_catalog, categories=("all",))
        structs = [symbol for symbol in index.symbols if symbol.category == "struct"]
        self.assertGreaterEqual(len(structs), 3)
        self.assertTrue(
            any(symbol.name == "boundary_macro_struct_t" for symbol in structs)
        )
        macro_struct = next(
            symbol
            for symbol in structs
            if symbol.name == "boundary_macro_struct_t"
        )
        self.assertNotIn("boundary_field", {symbol.name for symbol in structs})
        ordinary = [
            symbol
            for symbol in structs
            if symbol.name in {"ordinary_struct_t", "ordinary_field"}
        ]
        self.assertEqual(
            {symbol.name for symbol in ordinary},
            {"ordinary_struct_t", "ordinary_field"},
        )
        boundary_bytes = (FIXTURE / "boundary.sv").read_bytes()
        for symbol in ordinary:
            self.assertEqual(
                boundary_bytes[symbol.declaration.start : symbol.declaration.end],
                symbol.name.encode(),
            )
        self.assertIn(b"`T108_FIELD(boundary_field);", boundary_bytes)
        self.assertTrue(
            all(
                symbol.semantic_kind == "FieldSymbol"
                or symbol.name == "ordinary_struct_t"
                for symbol in ordinary
            )
        )
        self.assertTrue(
            all(
                symbol.support == "preserved"
                and symbol.reason == "source_binding_incomplete"
                for symbol in structs
            )
        )
        outcome = next(
            item for item in index.category_outcomes if item["category"] == "struct"
        )
        self.assertEqual(outcome["status"], "preserved")
        self.assertEqual(outcome["rename"], 0)
        self.assertEqual(outcome["preserve"], len(structs))
        self.assertTrue(
            any(
                issue["file"] == macro_struct.declaration.file
                and issue["start"] == macro_struct.declaration.start
                and issue["message"] == "source_binding_incomplete"
                for issue in outcome["issues"]
            )
        )

    def test_unknown_cross_record_claim_preserves_the_entire_core_group(self):
        shared = SourceRange("design.sv", 0, 6)
        records = {
            symbol_id: _WorkingSymbol(
                symbol_id=symbol_id,
                category="signals",
                kind="signal",
                semantic_kind="VariableSymbol",
                name="shared",
                declaration=SourceRange("design.sv", offset, offset + 6),
                owner_module=symbol_id,
                semantic_owner=symbol_id,
                impact="internal_signal",
                abi="internal",
            )
            for symbol_id, offset in (("signals:a", 0), ("signals:b", 7), ("signals:c", 14))
        }
        claims = {}
        _claim_occurrence(records["signals:a"], SymbolOccurrence(shared, "semantic_reference"), claims)
        _claim_occurrence(records["signals:a"], SymbolOccurrence(shared, "semantic_reference_duplicate"), claims)
        self.assertEqual(len(records["signals:a"].occurrences), 0)
        _claim_occurrence(records["signals:b"], SymbolOccurrence(shared, "semantic_reference"), claims)
        issues = _resolve_range_claims(records, claims)
        self.assertEqual(
            issues,
            {
                "signals": (
                    {
                        "file": "design.sv",
                        "start": 0,
                        "end": 6,
                        "message": "cross_record_range_conflict",
                    },
                )
            },
        )
        self.assertTrue(all(not record.occurrences for record in records.values()))
        self.assertTrue(
            all(
                record.support == "preserved"
                and record.reason == "cross_record_range_conflict"
                for record in records.values()
            )
        )

    def test_same_record_declaration_range_keeps_only_the_declaration(self):
        declaration = SourceRange("design.sv", 0, 6)
        record = _WorkingSymbol(
            symbol_id="signals:one",
            category="signals",
            kind="signal",
            semantic_kind="VariableSymbol",
            name="shared",
            declaration=declaration,
            owner_module="one",
            semantic_owner="one",
            impact="internal_signal",
            abi="internal",
        )
        claims = {}

        _claim_occurrence(
            record,
            SymbolOccurrence(declaration, "semantic_declaration_reference"),
            claims,
        )

        self.assertEqual(record.occurrences, {})
        self.assertEqual(
            claims,
            {
                ("design.sv", 0, 6): {
                    "signals:one": {"semantic_declaration_reference"}
                }
            },
        )

    def test_interface_arrays_are_root_aliases_without_anonymous_element_records(self):
        index = build_rename_index(self.catalog, categories=("interface",))
        arrays = {
            symbol.name
            for symbol in index.symbols
            if symbol.kind == "interface_instance_array"
        }
        self.assertEqual(arrays, {"if_arr", "if_matrix"})
        self.assertFalse(any(symbol.name == "" for symbol in index.symbols))
        self.assertEqual(
            sum(symbol.kind == "interface_instance_array" for symbol in index.symbols),
            2,
        )

    def test_all_four_groups_have_real_candidates_and_compile_safe_mapping(self):
        index = build_rename_index(self.catalog, categories=("all",))
        mapping = build_mapping_vnext(
            index, name_length=20, name_factory=secure_name_factory
        )
        by_category = {category: [] for category in ("signals", "ports", "interface", "struct")}
        for record in mapping.records:
            by_category[record.category].append(record)
        for category, records in by_category.items():
            self.assertTrue(records, category)
            self.assertTrue(any(item.action == "rename" for item in records), category)
        self.assertTrue(any(item.action == "preserve" for item in mapping.records))

    def test_actual_compact_gate_strict_compiles_and_restores_direct_bytes(self):
        index = build_rename_index(self.catalog, categories=("all",))
        mapping = build_mapping_vnext(
            index, name_length=20, name_factory=secure_name_factory
        )
        physical_files = tuple(
            dict.fromkeys(
                (*self.source_set.ordered_source_files, *self.source_set.included_files)
            )
        )
        gold = {
            file: (FIXTURE / file).read_bytes()
            for file in physical_files
        }
        with tempfile.TemporaryDirectory(prefix="t108-compact-gate-") as temporary:
            root = Path(temporary)
            execution = write_gate_vnext(mapping, output_dir=root / "gate")
            evidence = execution.compile_evidence
            self.assertEqual(
                (
                    evidence.catalog_parse_errors,
                    evidence.catalog_semantic_errors,
                    evidence.top_overlay_parse_errors,
                    evidence.top_overlay_semantic_errors,
                ),
                (0, 0, 0, 0),
            )
            restored = restore_gate_vnext(
                execution, gate_dir=root / "gate", output_dir=root / "restore"
            )
            self.assertTrue(restored.to_report()["summary"]["byte_identical"])
            self.assertEqual(
                {
                    file: (root / "restore" / file).read_bytes()
                    for file in physical_files
                },
                gold,
            )
