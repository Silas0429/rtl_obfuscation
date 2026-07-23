from dataclasses import fields
import json
from pathlib import Path
import unittest
from unittest import mock

from rtl_obfuscator import inventory, source_catalog
from rtl_obfuscator.source_catalog import build_source_catalog
from rtl_obfuscator.source_set import from_filelist, from_project_root, from_single_file
from rtl_obfuscator.symbol_graph import SymbolGraphError, build_symbol_graph


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "refactor_symbol_graph_genvars"
INVALID_ROOT = Path(__file__).parent / "fixtures" / "refactor_symbol_graph_genvars_invalid"


class SymbolGraphGenvarTests(unittest.TestCase):
    def _graph(self, filelist: Path, *, top: str | None = None):
        source_set = from_filelist(
            filelist=filelist,
            source_root=FIXTURE_ROOT,
            top=top,
        )
        return build_symbol_graph(build_source_catalog(source_set))

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
    def _genvars(graph):
        return [symbol for symbol in graph.symbols if symbol.category == "genvars"]

    def test_design_without_top_has_three_genvars_and_full_audit(self):
        graph = self._graph(FIXTURE_ROOT / "design.f")
        genvars = self._genvars(graph)
        self.assertEqual(len(genvars), 3)
        self.assertEqual(sum(len(symbol.occurrences) for symbol in genvars), 16)
        self.assertEqual(
            graph.to_report()["range_audit"],
            {"symbols": 7, "declarations": 7, "occurrences": 16, "total_ranges": 23},
        )

    def test_top_does_not_change_genvar_payload_or_remove_unreachable_owner(self):
        without_top = self._graph(FIXTURE_ROOT / "design.f")
        with_top = self._graph(FIXTURE_ROOT / "design.f", top="genvar_top")
        self.assertEqual(
            without_top.to_report()["symbols"], with_top.to_report()["symbols"]
        )
        self.assertEqual(
            len(
                [
                    symbol
                    for symbol in with_top.symbols
                    if symbol.category == "genvars"
                    and symbol.name == "k"
                    and symbol.declaration.file == "rtl/unreachable.sv"
                ]
            ),
            1,
        )

    def test_project_root_matches_closure_filelist_after_origin_normalization(self):
        project_graph = build_symbol_graph(
            build_source_catalog(
                from_project_root(project_root=FIXTURE_ROOT, top="genvar_top")
            )
        )
        filelist_graph = self._graph(FIXTURE_ROOT / "closure.f", top="genvar_top")
        self.assertEqual(
            self._without_origin(project_graph.to_report()),
            self._without_origin(filelist_graph.to_report()),
        )
        self.assertEqual(
            project_graph.to_report()["range_audit"],
            {"symbols": 5, "declarations": 5, "occurrences": 13, "total_ranges": 18},
        )
        self.assertEqual(
            filelist_graph.to_report()["range_audit"],
            {"symbols": 5, "declarations": 5, "occurrences": 13, "total_ranges": 18},
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
            {"symbols": 2, "declarations": 2, "occurrences": 3, "total_ranges": 5},
        )
        self.assertEqual(
            filelist_graph.to_report()["range_audit"],
            {"symbols": 2, "declarations": 2, "occurrences": 3, "total_ranges": 5},
        )

    def test_independent_genvar_reuse_has_one_source_symbol_and_ten_occurrences(self):
        graph = self._graph(FIXTURE_ROOT / "design.f")
        genvars = [symbol for symbol in self._genvars(graph) if symbol.name == "j"]
        self.assertEqual(len(genvars), 1)
        self.assertEqual(len(genvars[0].occurrences), 10)

    def test_inline_genvar_is_separate_from_same_named_module_parameter(self):
        graph = self._graph(FIXTURE_ROOT / "design.f")
        genvars = [
            symbol
            for symbol in self._genvars(graph)
            if symbol.name == "k" and symbol.declaration.file == "rtl/design.sv"
        ]
        self.assertEqual(len(genvars), 1)
        symbol = genvars[0]
        source = (FIXTURE_ROOT / symbol.declaration.file).read_bytes()
        self.assertEqual(
            source[symbol.declaration.start : symbol.declaration.end], b"k"
        )
        self.assertEqual(len(symbol.occurrences), 3)

    def test_same_named_genvars_have_distinct_declarations_and_owners(self):
        graph = self._graph(FIXTURE_ROOT / "design.f")
        genvars = [symbol for symbol in self._genvars(graph) if symbol.name == "k"]
        self.assertEqual(len(genvars), 2)
        self.assertEqual(
            len({symbol.symbol_id for symbol in genvars}), 2
        )
        self.assertEqual(
            len({symbol.owner_module for symbol in genvars}), 2
        )
        self.assertEqual(
            {symbol.declaration.file for symbol in genvars},
            {"rtl/design.sv", "rtl/unreachable.sv"},
        )

    def test_genvar_ranges_provenance_sorting_deduplication_and_audit(self):
        graph = self._graph(FIXTURE_ROOT / "design.f")
        all_ranges = []
        for symbol in graph.symbols:
            if symbol.category != "genvars":
                continue
            self.assertEqual(symbol.impact, "local")
            self.assertEqual(symbol.abi, "internal")
            self.assertEqual(symbol.support, "eligible")
            self.assertIsNone(symbol.reason)
            self.assertEqual(symbol.owner_module, symbol.semantic_owner)
            all_ranges.append((symbol, symbol.declaration))
            previous = None
            for occurrence in symbol.occurrences:
                self.assertEqual(occurrence.provenance, "generate_syntax")
                current = (
                    occurrence.source_range.file,
                    occurrence.source_range.start,
                    occurrence.source_range.end,
                    occurrence.provenance,
                )
                if previous is not None:
                    self.assertLessEqual(previous, current)
                previous = current
                all_ranges.append((symbol, occurrence.source_range))
        self.assertEqual(len(all_ranges), 19)
        self.assertEqual(
            len({(item.file, item.start, item.end) for _, item in all_ranges}),
            len(all_ranges),
        )
        for symbol, source_range in all_ranges:
            source = (FIXTURE_ROOT / source_range.file).read_bytes()
            self.assertGreaterEqual(source_range.start, 0)
            self.assertLess(source_range.start, source_range.end)
            self.assertLessEqual(source_range.end, len(source))
            self.assertEqual(
                source[source_range.start : source_range.end],
                symbol.name.encode("utf-8"),
            )

    def test_categories_schema_and_canonical_json_are_stable(self):
        graph = self._graph(FIXTURE_ROOT / "design.f")
        first = json.dumps(graph.to_report(), sort_keys=True, separators=(",", ":"))
        second = json.dumps(graph.to_report(), sort_keys=True, separators=(",", ":"))
        self.assertEqual(first, second)
        self.assertEqual(graph.to_report()["categories"], ["signals", "genvars"])
        self.assertEqual(graph.to_report()["schema_version"], 1)
        self.assertEqual(
            [field.name for field in fields(graph)],
            ["schema_version", "source_catalog", "symbols"],
        )

    def test_graph_reuses_catalog_and_does_not_call_legacy_genvar_paths(self):
        source_set = from_filelist(
            filelist=FIXTURE_ROOT / "design.f",
            source_root=FIXTURE_ROOT,
        )
        catalog = build_source_catalog(source_set)
        with (
            mock.patch.object(
                source_catalog,
                "_compile_view",
                side_effect=AssertionError("catalog recompilation"),
            ),
            mock.patch.object(
                inventory,
                "_collect_genvars",
                side_effect=AssertionError("legacy genvar collector"),
            ),
            mock.patch.object(
                inventory,
                "_genvar_reference_tokens",
                side_effect=AssertionError("legacy genvar range helper"),
            ),
        ):
            graph = build_symbol_graph(catalog)
        self.assertEqual(len(self._genvars(graph)), 3)

    def test_macro_genvar_declaration_fails_closed(self):
        catalog = build_source_catalog(
            from_filelist(
                filelist=INVALID_ROOT / "macro.f",
                source_root=INVALID_ROOT,
            )
        )
        with self.assertRaises(SymbolGraphError) as raised:
            build_symbol_graph(catalog)
        self.assertEqual(raised.exception.code, "SYMBOL_GRAPH_UNSUPPORTED_SOURCE")

    def test_macro_genvar_reference_fails_closed(self):
        catalog = build_source_catalog(
            from_filelist(
                filelist=INVALID_ROOT / "macro_reference.f",
                source_root=INVALID_ROOT,
            )
        )
        with self.assertRaises(SymbolGraphError) as raised:
            build_symbol_graph(catalog)
        self.assertEqual(raised.exception.code, "SYMBOL_GRAPH_UNSUPPORTED_SOURCE")

    def test_nested_same_named_genvars_fail_closed(self):
        catalog = build_source_catalog(
            from_filelist(
                filelist=INVALID_ROOT / "nested.f",
                source_root=INVALID_ROOT,
            )
        )
        with self.assertRaises(SymbolGraphError) as raised:
            build_symbol_graph(catalog)
        self.assertEqual(raised.exception.code, "SYMBOL_GRAPH_UNSUPPORTED_REFERENCE")


if __name__ == "__main__":
    unittest.main()
