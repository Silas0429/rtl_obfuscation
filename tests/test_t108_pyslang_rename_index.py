from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from rtl_obfuscator.mapping_vnext import build_mapping_vnext
from rtl_obfuscator.rename_index import (
    SymbolOccurrence,
    _WorkingSymbol,
    _apply_group_binding_issues,
    _claim_occurrence,
    _range_for_token,
    _resolve_range_claims,
    _safe_occurrence_range,
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
        cls.macro_interface_source_set = from_filelist(
            filelist=FIXTURE / "macro_interface.f", top="macro_interface_top"
        )
        cls.macro_interface_catalog = build_source_catalog(
            cls.macro_interface_source_set
        )
        cls.shape_source_set = from_filelist(
            filelist=FIXTURE / "server_shapes.f", top="t108_shape_top"
        )
        cls.shape_catalog = build_source_catalog(cls.shape_source_set)

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

    def test_unknown_struct_shape_is_a_boundary_and_preserves_only_its_own_record(self):
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
        # T111 2.1 policy change, not a relaxation: the macro-generated field
        # shape is still an unknown binding boundary and its own record is still
        # fail-closed, but the blast radius is now one record instead of the
        # whole struct group.  Only `boundary_macro_struct_t` produced the issue,
        # so only it may be preserved; `ordinary_struct_t` and `ordinary_field`
        # are fully proven and must still rename.
        self.assertEqual(macro_struct.support, "preserved")
        self.assertEqual(macro_struct.reason, "source_binding_incomplete")
        self.assertEqual(
            {symbol.name for symbol in structs if symbol.support == "preserved"},
            {"boundary_macro_struct_t"},
        )
        for symbol in ordinary:
            self.assertEqual(symbol.support, "eligible", symbol.name)
            self.assertIsNone(symbol.reason, symbol.name)
        outcome = next(
            item for item in index.category_outcomes if item["category"] == "struct"
        )
        self.assertEqual(outcome["status"], "preserved")
        self.assertEqual(outcome["rename"], len(structs) - 1)
        self.assertEqual(outcome["preserve"], 1)
        self.assertEqual(outcome["unsupported"], 0)
        # Locating information for the unbound shape must survive the narrower
        # scope: both the detailed FieldSymbol diagnostic and the preserved
        # record's own file/start remain reported.
        self.assertTrue(
            any(
                issue["file"] == macro_struct.declaration.file
                and issue["start"] == macro_struct.declaration.start
                and issue["message"] == "source_binding_incomplete"
                for issue in outcome["issues"]
            )
        )
        self.assertTrue(
            any(
                issue["message"] == "source_binding_incomplete"
                and issue.get("semantic_kind") == "FieldSymbol"
                and issue.get("name") == "boundary_field"
                and issue["file"] == "boundary.sv"
                and isinstance(issue.get("detail"), str)
                for issue in outcome["issues"]
            )
        )
        # No issue may point at a record that was never the cause.
        self.assertEqual(
            [
                issue
                for issue in outcome["issues"]
                if issue.get("name") is None
                and issue["start"]
                in {symbol.declaration.start for symbol in ordinary}
            ],
            [],
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

    def test_macro_backed_interface_declaration_and_invalid_typed_token_are_fail_closed(self):
        index = build_rename_index(
            self.macro_interface_catalog, categories=("interface",)
        )
        self.assertTrue(index.symbols)
        self.assertFalse(any(symbol.name == "" for symbol in index.symbols))
        outcome = next(
            item for item in index.category_outcomes if item["category"] == "interface"
        )
        self.assertEqual(outcome["status"], "preserved")
        self.assertGreater(outcome["rename"], 0)
        self.assertEqual(outcome["preserve"], 2)
        self.assertFalse(
            any(issue["message"] == "source_binding_incomplete" for issue in outcome["issues"])
        )
        self.assertEqual(
            {
                symbol.name
                for symbol in index.symbols
                if symbol.support == "eligible"
            },
            {"macro_if", "macro_mp", "value"},
        )
        self.assertEqual(
            {
                symbol.name
                for symbol in index.symbols
                if symbol.support == "preserved"
            },
            {"if0", "if_array"},
        )

        class InvalidToken:
            rawText = b"macro_mp"

            @property
            def location(self):
                raise RuntimeError("invalid typed-token location")

        class InvalidNode:
            syntax = InvalidToken()

        declaration = SourceRange("design.sv", 0, 6)
        record = _WorkingSymbol(
            symbol_id="interface:invalid",
            category="interface",
            kind="interface_member",
            semantic_kind="ModportPortSymbol",
            name="macro_mp",
            declaration=declaration,
            owner_module="interface",
            semantic_owner="interface",
            impact="interface_member",
            abi="internal",
        )
        binding_issues = {}
        source_range = _safe_occurrence_range(
            self.macro_interface_catalog,
            binding_issues,
            record,
            InvalidNode(),
            lambda: _range_for_token(
                self.macro_interface_catalog, InvalidToken(), "macro_mp"
            ),
        )
        self.assertIsNone(source_range)
        self.assertEqual(record.support, "preserved")
        self.assertEqual(record.reason, "source_binding_incomplete")
        self.assertEqual(record.occurrences, {})
        self.assertEqual(binding_issues["interface"][0]["semantic_kind"], "ModportPortSymbol")
        self.assertEqual(binding_issues["interface"][0]["name"], "macro_mp")
        other = _WorkingSymbol(
            symbol_id="interface:other",
            category="interface",
            kind="interface_member",
            semantic_kind="VariableSymbol",
            name="other",
            declaration=SourceRange("design.sv", 7, 12),
            owner_module="interface",
            semantic_owner="interface",
            impact="interface_member",
            abi="internal",
        )
        records = {record.symbol_id: record, other.symbol_id: other}
        _apply_group_binding_issues(records, binding_issues)
        # T111 2.1 policy change, not a relaxation: the record whose typed token
        # could not be bound is still fail-closed, but a sibling record of the
        # same core group that was never implicated keeps its own proven state.
        self.assertEqual(record.support, "preserved")
        self.assertEqual(record.reason, "source_binding_incomplete")
        self.assertEqual(other.support, "eligible")
        self.assertIsNone(other.reason)

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

    def test_ansi_nonansi_ports_interface_aliases_and_fields_have_real_renames(self):
        index = build_rename_index(self.shape_catalog, categories=("all",))
        mapping = build_mapping_vnext(
            index, name_length=20, name_factory=secure_name_factory
        )
        by_category = {category: [] for category in ("ports", "interface", "struct")}
        for item in mapping.records:
            if item.category in by_category:
                by_category[item.category].append(item)
        for category, records in by_category.items():
            self.assertTrue(records, category)
            self.assertTrue(
                any(item.action == "rename" for item in records), category
            )
        self.assertTrue(
            any(
                item.kind == "module_port"
                and item.original_name in {"clk", "data_i", "data_o"}
                and item.action == "rename"
                for item in mapping.records
            )
        )
        self.assertTrue(
            any(
                item.kind == "interface_type"
                and item.original_name == "t108_shape_if"
                and item.action == "rename"
                for item in mapping.records
            )
        )
        shape_interface = next(
            item
            for item in index.symbols
            if item.kind == "interface_type" and item.name == "t108_shape_if"
        )
        self.assertIn(
            "semantic_interface_port_type",
            {item.provenance for item in shape_interface.occurrences},
        )
        self.assertTrue(
            any(
                item.kind == "struct_field"
                and item.original_name == "first"
                and item.action == "rename"
                for item in mapping.records
            )
        )
        self.assertIn(
            "semantic_member",
            {
                occurrence.provenance
                for item in index.symbols
                if item.category == "struct" and item.name == "first"
                for occurrence in item.occurrences
            },
        )
        physical_files = tuple(self.shape_source_set.ordered_source_files)
        gold = {file: (FIXTURE / file).read_bytes() for file in physical_files}
        with tempfile.TemporaryDirectory(prefix="t108-shape-gate-") as temporary:
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
