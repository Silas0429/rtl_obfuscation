from dataclasses import fields, replace
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

from rtl_obfuscator import inventory, source_catalog
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

    def test_full_without_top_has_parameter_oracle_and_abi_defaults(self):
        graph = self._graph(FIXTURE_ROOT / "design.f")
        parameters = self._parameters(graph)
        self.assertEqual(len(parameters), 12)
        self.assertEqual(sum(len(symbol.occurrences) for symbol in parameters), 27)
        self.assertEqual(
            graph.to_report()["range_audit"],
            {"symbols": 20, "declarations": 20, "occurrences": 33, "total_ranges": 53},
        )
        self.assertEqual(graph.to_report()["categories"], ["signals", "parameters", "genvars"])
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
        self.assertEqual(
            project_graph.to_report()["range_audit"],
            {"symbols": 17, "declarations": 17, "occurrences": 31, "total_ranges": 48},
        )

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
        self.assertEqual(
            single_graph.to_report()["range_audit"],
            {"symbols": 3, "declarations": 3, "occurrences": 2, "total_ranges": 5},
        )

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
        self.assertEqual(
            graph.to_report()["range_audit"],
            {"symbols": 9, "declarations": 9, "occurrences": 18, "total_ranges": 27},
        )
        self.assertEqual(graph.to_report()["categories"], ["signals", "parameters", "genvars"])

    def test_positional_override_has_no_parameter_name_occurrence(self):
        graph = self._graph(FIXTURE_ROOT / "positional.f", top="positional_top")
        parameters = self._parameters(graph)
        self.assertEqual(len(parameters), 1)
        self.assertEqual(len(parameters[0].occurrences), 0)
        self.assertEqual(
            graph.to_report()["range_audit"],
            {"symbols": 1, "declarations": 1, "occurrences": 0, "total_ranges": 1},
        )
        self.assertEqual(graph.to_report()["categories"], ["parameters"])

    def test_categories_schema_and_canonical_json_are_stable(self):
        graph = self._graph(FIXTURE_ROOT / "design.f", top="parameter_top")
        first = json.dumps(graph.to_report(), sort_keys=True, separators=(",", ":"))
        second = json.dumps(graph.to_report(), sort_keys=True, separators=(",", ":"))
        self.assertEqual(first, second)
        self.assertEqual(graph.to_report()["categories"], ["signals", "parameters", "genvars"])
        self.assertEqual(graph.to_report()["schema_version"], 1)
        self.assertEqual(
            [field.name for field in fields(graph)],
            ["schema_version", "source_catalog", "symbols"],
        )

    def test_graph_reuses_catalog_and_does_not_call_legacy_parameter_paths(self):
        catalog = build_source_catalog(
            from_filelist(filelist=FIXTURE_ROOT / "design.f", source_root=FIXTURE_ROOT)
        )
        legacy_helpers = (
            "_collect_parameters",
            "_parameter_dimension_reference_tokens",
            "_parameter_syntax_dimension_reference_tokens",
            "_parameter_generate_reference_tokens",
            "_named_parameter_override_reference_tokens",
        )
        with (
            mock.patch.object(source_catalog, "_compile_view", side_effect=AssertionError("catalog recompilation")),
            mock.patch.object(inventory, "_collect_parameters", side_effect=AssertionError("legacy parameter collector")),
            mock.patch.object(inventory, "_parameter_dimension_reference_tokens", side_effect=AssertionError("legacy dimension helper")),
            mock.patch.object(inventory, "_parameter_syntax_dimension_reference_tokens", side_effect=AssertionError("legacy syntax dimension helper")),
            mock.patch.object(inventory, "_parameter_generate_reference_tokens", side_effect=AssertionError("legacy generate helper")),
            mock.patch.object(inventory, "_named_parameter_override_reference_tokens", side_effect=AssertionError("legacy override helper")),
        ):
            graph = build_symbol_graph(catalog)
        self.assertEqual(len(self._parameters(graph)), 12)
        self.assertEqual(len(legacy_helpers), 5)

    def _assert_invalid(self, filelist: str, code: str):
        catalog = build_source_catalog(
            from_filelist(filelist=INVALID_ROOT / filelist, source_root=INVALID_ROOT)
        )
        with self.assertRaises(SymbolGraphError) as raised:
            build_symbol_graph(catalog)
        self.assertEqual(raised.exception.code, code)

    def test_macro_parameter_declaration_fails_closed(self):
        self._assert_invalid("macro_declaration.f", "SYMBOL_GRAPH_UNSUPPORTED_SOURCE")

    def test_macro_parameter_reference_fails_closed(self):
        self._assert_invalid("macro_reference.f", "SYMBOL_GRAPH_UNSUPPORTED_SOURCE")

    def test_type_parameter_fails_closed(self):
        self._assert_invalid("type_parameter.f", "SYMBOL_GRAPH_UNSUPPORTED_SOURCE")

    def test_defparam_fails_closed(self):
        self._assert_invalid("defparam.f", "SYMBOL_GRAPH_UNSUPPORTED_REFERENCE")

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
