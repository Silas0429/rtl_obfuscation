from dataclasses import fields, replace
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from rtl_obfuscator.category_registry_vnext import CANONICAL_CATEGORIES
from rtl_obfuscator.source_catalog import build_source_catalog
from rtl_obfuscator.source_set import from_filelist, from_project_root, from_single_file
from rtl_obfuscator.symbol_graph import SymbolGraphError, build_symbol_graph


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "refactor_symbol_graph_parameters"
INVALID_ROOT = (
    Path(__file__).parent / "fixtures" / "refactor_symbol_graph_parameters_invalid"
)
GENVAR_ROOT = Path(__file__).parent / "fixtures" / "refactor_symbol_graph_genvars"


class SymbolGraphParameterTests(unittest.TestCase):
    def _graph(self, filelist: Path, *, top: str | None = None):
        source_set = from_filelist(
            filelist=filelist,
            source_root=FIXTURE_ROOT,
            top=top,
        )
        return build_symbol_graph(build_source_catalog(source_set))

    @staticmethod
    def _parameters(graph):
        return [symbol for symbol in graph.symbols if symbol.category == "parameters"]

    @staticmethod
    def _genvars(graph):
        return [symbol for symbol in graph.symbols if symbol.category == "genvars"]

    @staticmethod
    def _categories_for(graph):
        return [
            category
            for category in CANONICAL_CATEGORIES
            if any(symbol.category == category for symbol in graph.symbols)
        ]

    @staticmethod
    def _without_origin(report: dict) -> dict:
        result = dict(report)
        source_catalog_report = dict(result["source_catalog"])
        source_set_report = dict(source_catalog_report["source_set"])
        source_set_report.pop("origin")
        source_catalog_report["source_set"] = source_set_report
        result["source_catalog"] = source_catalog_report
        return result

    @staticmethod
    def _parameter_identity(symbol):
        return (
            symbol.symbol_id,
            symbol.name,
            symbol.declaration,
            symbol.owner_module,
            symbol.semantic_owner,
            tuple(
                (
                    occurrence.source_range,
                    occurrence.provenance,
                )
                for occurrence in symbol.occurrences
            ),
        )

    def test_packed_aggregate_member_dimension_uses_alias_lexical_scope(self):
        source = b"""module child_a #(parameter int WIDTH = 8)();
  typedef struct packed {
    logic [WIDTH-1:0] payload;
  } child_a_t;
  child_a_t value_a;
endmodule

module child_b #(parameter int WIDTH = 4)();
  typedef union packed {
    logic [WIDTH-1:0] raw;
  } child_b_t;
  child_b_t value_b;
endmodule

module selected_top();
  child_a a();
  child_b b();
endmodule
"""
        with tempfile.TemporaryDirectory(prefix="t057-parameter-alias-", dir="/private/tmp") as temporary:
            root = Path(temporary)
            (root / "design.sv").write_bytes(source)
            (root / "design.f").write_text("design.sv\n", encoding="utf-8")
            graph = build_symbol_graph(
                build_source_catalog(
                    from_filelist(
                        filelist=root / "design.f",
                        source_root=root,
                        top="selected_top",
                    )
                )
            )
            parameters = [symbol for symbol in graph.symbols if symbol.category == "parameters" and symbol.name == "WIDTH"]
            self.assertEqual(len(parameters), 2)
            module_starts = {
                "child_a": source.index(b"module child_a"),
                "child_b": source.index(b"module child_b"),
            }
            module_ends = {
                "child_a": module_starts["child_b"],
                "child_b": source.index(b"module selected_top"),
            }
            for symbol in parameters:
                owner_name = next(
                    name
                    for name, start in module_starts.items()
                    if start < symbol.declaration.start < module_ends[name]
                )
                dimension_occurrences = [
                    occurrence
                    for occurrence in symbol.occurrences
                    if occurrence.provenance == "declaration_dimension"
                ]
                self.assertEqual(len(dimension_occurrences), 1)
                occurrence = dimension_occurrences[0]
                self.assertNotEqual(occurrence.source_range, symbol.declaration)
                self.assertTrue(
                    module_starts[owner_name]
                    < occurrence.source_range.start
                    < module_ends[owner_name]
                )
                self.assertEqual(
                    source[occurrence.source_range.start : occurrence.source_range.end],
                    b"WIDTH",
                )
                self.assertNotIn(occurrence.source_range, (symbol.declaration,))
            range_audit = graph.to_report()["range_audit"]
            self.assertEqual(
                range_audit["total_ranges"],
                range_audit["declarations"] + range_audit["occurrences"],
            )

    def test_full_without_top_has_parameter_oracle_and_abi_defaults(self):
        graph = self._graph(FIXTURE_ROOT / "design.f")
        parameters = self._parameters(graph)
        self.assertEqual(len(parameters), 12)
        self.assertEqual(sum(len(symbol.occurrences) for symbol in parameters), 27)
        self.assertEqual(graph.to_report()["range_audit"]["symbols"], len(graph.symbols))
        self.assertEqual(
            graph.to_report()["range_audit"]["occurrences"],
            sum(len(symbol.occurrences) for symbol in graph.symbols),
        )
        self.assertEqual(graph.to_report()["categories"], self._categories_for(graph))
        self.assertEqual(
            sum(symbol.abi == "internal" and symbol.support == "eligible" for symbol in parameters),
            5,
        )
        self.assertEqual(
            sum(
                symbol.abi == "module_abi"
                and symbol.support == "preserved"
                and symbol.reason == "module_abi_requires_top"
                for symbol in parameters
            ),
            7,
        )

    def test_full_with_top_has_four_frozen_abi_classes(self):
        graph = self._graph(FIXTURE_ROOT / "design.f", top="parameter_top")
        parameters = self._parameters(graph)
        self.assertEqual(len(parameters), 12)
        self.assertEqual(
            {
                (symbol.abi, symbol.support, symbol.reason)
                for symbol in parameters
                if not symbol.impact == "local"
            },
            {
                ("module_abi", "eligible", None),
                ("top_boundary", "preserved", "selected_top_boundary"),
                ("module_abi", "preserved", "outside_top_closure"),
            },
        )
        self.assertEqual(
            sum(symbol.abi == "top_boundary" for symbol in parameters), 3
        )
        self.assertEqual(
            sum(symbol.abi == "module_abi" and symbol.support == "eligible" for symbol in parameters),
            3,
        )
        self.assertEqual(
            sum(symbol.reason == "outside_top_closure" for symbol in parameters), 1
        )

    def test_top_changes_only_value_parameter_classification(self):
        without_top = self._graph(FIXTURE_ROOT / "design.f")
        with_top = self._graph(FIXTURE_ROOT / "design.f", top="parameter_top")
        self.assertEqual(
            [self._parameter_identity(symbol) for symbol in self._parameters(without_top)],
            [self._parameter_identity(symbol) for symbol in self._parameters(with_top)],
        )
        for no_top, with_top_symbol in zip(
            self._parameters(without_top), self._parameters(with_top), strict=True
        ):
            if no_top.impact == "local":
                self.assertEqual(
                    (no_top.impact, no_top.abi, no_top.support, no_top.reason),
                    (with_top_symbol.impact, with_top_symbol.abi, with_top_symbol.support, with_top_symbol.reason),
                )

    def test_project_root_matches_closure_filelist_after_origin_normalization(self):
        project_graph = build_symbol_graph(
            build_source_catalog(
                from_project_root(project_root=FIXTURE_ROOT, top="parameter_top")
            )
        )
        filelist_graph = self._graph(FIXTURE_ROOT / "closure.f", top="parameter_top")
        self.assertEqual(
            self._without_origin(project_graph.to_report()),
            self._without_origin(filelist_graph.to_report()),
        )
        self.assertEqual(project_graph.to_report()["range_audit"]["symbols"], len(project_graph.symbols))

    def test_single_file_matches_single_filelist_after_origin_normalization(self):
        single_graph = build_symbol_graph(
            build_source_catalog(
                from_single_file(
                    source_file=FIXTURE_ROOT / "single.sv",
                    source_root=FIXTURE_ROOT,
                )
            )
        )
        filelist_graph = self._graph(FIXTURE_ROOT / "single.f")
        self.assertEqual(
            self._without_origin(single_graph.to_report()),
            self._without_origin(filelist_graph.to_report()),
        )
        self.assertEqual(single_graph.to_report()["range_audit"]["symbols"], len(single_graph.symbols))

    def test_provenance_bytes_sorting_deduplication_and_audit(self):
        graph = self._graph(FIXTURE_ROOT / "design.f")
        parameters = self._parameters(graph)
        counts = {
            provenance: sum(
                occurrence.provenance == provenance
                for symbol in parameters
                for occurrence in symbol.occurrences
            )
            for provenance in (
                "semantic_expression",
                "declaration_dimension",
                "generate_syntax",
                "named_override",
            )
        }
        self.assertEqual(counts, {
            "semantic_expression": 10,
            "declaration_dimension": 12,
            "generate_syntax": 2,
            "named_override": 3,
        })
        all_ranges = []
        for symbol in parameters:
            self.assertEqual(symbol.owner_module, symbol.semantic_owner)
            all_ranges.append((symbol.symbol_id, symbol.declaration))
            previous = None
            for occurrence in symbol.occurrences:
                current = (
                    occurrence.source_range.file,
                    occurrence.source_range.start,
                    occurrence.source_range.end,
                    occurrence.provenance,
                )
                if previous is not None:
                    self.assertLessEqual(previous, current)
                previous = current
                all_ranges.append((symbol.symbol_id, occurrence.source_range))
        self.assertEqual(len(all_ranges), 39)
        self.assertEqual(
            len({(item.file, item.start, item.end) for _, item in all_ranges}),
            len(all_ranges),
        )
        for symbol in parameters:
            for source_range in (symbol.declaration,) + tuple(
                occurrence.source_range for occurrence in symbol.occurrences
            ):
                source = (FIXTURE_ROOT / source_range.file).read_bytes()
                self.assertEqual(
                    source[source_range.start : source_range.end],
                    symbol.name.encode("utf-8"),
                )

    def test_named_override_left_and_right_same_name_have_distinct_owners(self):
        graph = self._graph(FIXTURE_ROOT / "design.f", top="parameter_top")
        parameters = self._parameters(graph)
        child_width = next(
            symbol
            for symbol in parameters
            if symbol.name == "WIDTH" and symbol.declaration.file == "rtl/child.sv"
        )
        child_depth = next(
            symbol
            for symbol in parameters
            if symbol.name == "DEPTH" and symbol.declaration.file == "rtl/child.sv"
        )
        shadow_width = next(
            symbol
            for symbol in parameters
            if symbol.name == "WIDTH" and symbol.declaration.file == "rtl/shadow.sv"
        )
        top_width = next(
            symbol
            for symbol in parameters
            if symbol.name == "WIDTH" and symbol.declaration.file == "rtl/top.sv"
        )
        self.assertEqual(
            sum(o.provenance == "named_override" for o in child_width.occurrences), 1
        )
        self.assertEqual(
            sum(o.provenance == "named_override" for o in child_depth.occurrences), 1
        )
        self.assertEqual(
            sum(o.provenance == "named_override" for o in shadow_width.occurrences), 1
        )
        self.assertGreaterEqual(
            sum(
                o.provenance == "semantic_expression"
                and o.source_range.file == "rtl/top.sv"
                for o in top_width.occurrences
            ),
            2,
        )
        self.assertFalse(
            any(o.provenance == "named_override" for o in top_width.occurrences)
        )

    def test_shadowed_localparam_and_module_parameter_keep_dimension_owners(self):
        graph = self._graph(FIXTURE_ROOT / "design.f")
        parameters = [
            symbol
            for symbol in self._parameters(graph)
            if symbol.name == "WIDTH" and symbol.declaration.file == "rtl/shadow.sv"
        ]
        self.assertEqual(len(parameters), 2)
        self.assertEqual(len({symbol.declaration for symbol in parameters}), 2)
        self.assertEqual(
            {
                tuple(
                    occurrence.source_range
                    for occurrence in symbol.occurrences
                    if occurrence.provenance == "declaration_dimension"
                )
                for symbol in parameters
            },
            {
                (next(
                    occurrence.source_range
                    for occurrence in symbol.occurrences
                    if occurrence.provenance == "declaration_dimension"
                ),)
                for symbol in parameters
            },
        )
        source = (FIXTURE_ROOT / "rtl/shadow.sv").read_bytes()
        dimension_bytes = {
            source[occurrence.source_range.start : occurrence.source_range.end]
            for symbol in parameters
            for occurrence in symbol.occurrences
            if occurrence.provenance == "declaration_dimension"
        }
        self.assertEqual(dimension_bytes, {b"WIDTH"})

    def test_t042_genvar_and_iteration_parameter_remain_separate(self):
        source_set = from_filelist(
            filelist=GENVAR_ROOT / "design.f",
            source_root=GENVAR_ROOT,
        )
        graph = build_symbol_graph(build_source_catalog(source_set))
        self.assertEqual(len(self._parameters(graph)), 2)
        self.assertEqual(len(self._genvars(graph)), 3)
        self.assertEqual(
            {symbol.name for symbol in self._parameters(graph)}, {"WIDTH", "k"}
        )
        self.assertFalse(any(symbol.name == "j" for symbol in self._parameters(graph)))
        self.assertEqual(graph.to_report()["range_audit"]["symbols"], len(graph.symbols))
        self.assertEqual(graph.to_report()["categories"], self._categories_for(graph))

    def test_positional_override_has_no_parameter_name_occurrence(self):
        graph = self._graph(FIXTURE_ROOT / "positional.f", top="positional_top")
        parameters = self._parameters(graph)
        self.assertEqual(len(parameters), 1)
        self.assertEqual(len(parameters[0].occurrences), 0)
        self.assertEqual(graph.to_report()["range_audit"]["symbols"], len(graph.symbols))
        self.assertEqual(graph.to_report()["categories"], self._categories_for(graph))

    def test_categories_schema_and_canonical_json_are_stable(self):
        graph = self._graph(FIXTURE_ROOT / "design.f", top="parameter_top")
        first = json.dumps(graph.to_report(), sort_keys=True, separators=(",", ":"))
        second = json.dumps(graph.to_report(), sort_keys=True, separators=(",", ":"))
        self.assertEqual(first, second)
        self.assertEqual(graph.to_report()["categories"], self._categories_for(graph))
        self.assertEqual(graph.to_report()["schema_version"], 1)
        self.assertEqual(
            [field.name for field in fields(graph)],
            ["schema_version", "source_catalog", "symbols"],
        )

    def test_graph_reuses_catalog_for_parameters(self):
        catalog = build_source_catalog(
            from_filelist(filelist=FIXTURE_ROOT / "design.f", source_root=FIXTURE_ROOT)
        )
        graph = build_symbol_graph(catalog)
        self.assertEqual(len(self._parameters(graph)), 12)

    def _assert_invalid(self, filelist: str, code: str):
        catalog = build_source_catalog(
            from_filelist(filelist=INVALID_ROOT / filelist, source_root=INVALID_ROOT)
        )
        with self.assertRaises(SymbolGraphError) as raised:
            build_symbol_graph(catalog)
        self.assertEqual(raised.exception.code, code)

    def test_macro_parameter_declaration_safe_preserve(self):
        catalog = build_source_catalog(
            from_filelist(filelist=INVALID_ROOT / "macro_declaration.f", source_root=INVALID_ROOT)
        )
        graph = build_symbol_graph(catalog)
        self.assertEqual(
            graph.to_report()["range_audit"],
            {"symbols": 3, "declarations": 3, "occurrences": 1, "total_ranges": 4},
        )
        parameter = next(symbol for symbol in graph.symbols if symbol.name == "MACRO_WIDTH")
        self.assertEqual(parameter.support, "eligible")
        self.assertIsNone(parameter.reason)
        source = (INVALID_ROOT / parameter.declaration.file).read_bytes()
        self.assertEqual(source[parameter.declaration.start : parameter.declaration.end], b"MACRO_WIDTH")
        self.assertNotIn("owner_contains_macro_source", {symbol.reason for symbol in graph.symbols})

    def test_macro_parameter_reference_safe_preserve(self):
        catalog = build_source_catalog(
            from_filelist(filelist=INVALID_ROOT / "macro_reference.f", source_root=INVALID_ROOT)
        )
        graph = build_symbol_graph(catalog)
        self.assertEqual(
            graph.to_report()["range_audit"],
            {"symbols": 3, "declarations": 3, "occurrences": 1, "total_ranges": 4},
        )
        parameter = next(symbol for symbol in graph.symbols if symbol.name == "WIDTH")
        self.assertEqual(parameter.support, "preserved")
        self.assertEqual(parameter.reason, "module_abi_requires_top")
        self.assertIn(
            "semantic_macro_argument",
            {occurrence.provenance for occurrence in parameter.occurrences},
        )
        self.assertNotIn("owner_contains_macro_source", {symbol.reason for symbol in graph.symbols})

    def test_type_parameter_safe_preserve(self):
        catalog = build_source_catalog(
            from_filelist(
                filelist=INVALID_ROOT / "type_parameter.f",
                source_root=INVALID_ROOT,
            )
        )
        graph = build_symbol_graph(catalog)
        self.assertEqual(graph.to_report()["range_audit"], {
            "symbols": 3,
            "declarations": 3,
            "occurrences": 0,
            "total_ranges": 3,
        })
        self.assertEqual(
            {(symbol.name, symbol.support, symbol.reason) for symbol in graph.symbols},
            {
                ("T", "unsupported", "type_parameter_not_renamed"),
                ("unsupported_type_parameter", "unsupported", "owner_contains_type_parameter"),
                ("value", "unsupported", "owner_contains_type_parameter"),
            },
        )

    def test_defparam_safe_preserve(self):
        catalog = build_source_catalog(
            from_filelist(
                filelist=INVALID_ROOT / "defparam.f",
                source_root=INVALID_ROOT,
            )
        )
        graph = build_symbol_graph(catalog)
        self.assertEqual(graph.to_report()["range_audit"], {
            "symbols": 4,
            "declarations": 4,
            "occurrences": 2,
            "total_ranges": 6,
        })
        self.assertTrue(
            all(
                symbol.support == "unsupported"
                and symbol.reason == "defparam_binding_not_renamed"
                for symbol in graph.symbols
            )
        )
        width = next(symbol for symbol in graph.symbols if symbol.name == "WIDTH")
        self.assertEqual(
            [(item.source_range.file, item.source_range.start, item.source_range.end, item.provenance)
             for item in width.occurrences],
            [("rtl/defparam.sv", 139, 144, "defparam_binding")],
        )

    def test_parameter_declaration_bytes_changed_after_catalog_fail_with_range_invalid(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary) / "fixture"
            shutil.copytree(FIXTURE_ROOT, temporary_root)
            catalog = build_source_catalog(
                from_filelist(
                    filelist=temporary_root / "design.f",
                    source_root=temporary_root,
                )
            )
            child_file = temporary_root / "rtl" / "child.sv"
            child_file.write_bytes(
                child_file.read_bytes().replace(
                    b"parameter int WIDTH = 2",
                    b"parameter int WIDTQ = 2",
                    1,
                )
            )
            with self.assertRaises(SymbolGraphError) as raised:
                build_symbol_graph(catalog)
        self.assertEqual(raised.exception.code, "SYMBOL_GRAPH_RANGE_INVALID")

    def test_parameter_only_catalog_without_owner_registry_fails_closed(self):
        catalog = build_source_catalog(
            from_filelist(
                filelist=FIXTURE_ROOT / "positional.f",
                source_root=FIXTURE_ROOT,
                top="positional_top",
            )
        )
        with self.assertRaises(SymbolGraphError) as raised:
            build_symbol_graph(replace(catalog, modules=()))
        self.assertEqual(raised.exception.code, "SYMBOL_GRAPH_OWNER_MISMATCH")


if __name__ == "__main__":
    unittest.main()
