from dataclasses import fields, replace
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

import pyslang

from rtl_obfuscator import inventory, project, source_catalog
from rtl_obfuscator.source_catalog import build_source_catalog
from rtl_obfuscator.source_set import from_filelist, from_project_root, from_single_file
from rtl_obfuscator.symbol_graph import SourceSymbol, SymbolGraphError, build_symbol_graph


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "refactor_symbol_graph_signals"
INVALID_ROOT = Path(__file__).parent / "fixtures" / "refactor_symbol_graph_signals_invalid"


class SymbolGraphSignalsTests(unittest.TestCase):
    def _graph(self, filelist: Path, *, top: str | None = None):
        source_set = from_filelist(
            filelist=filelist,
            source_root=FIXTURE_ROOT,
            top=top,
        )
        return build_symbol_graph(build_source_catalog(source_set))

    @staticmethod
    def _symbol_payload(graph):
        return graph.to_report()["symbols"]

    @staticmethod
    def _without_origin(report: dict) -> dict:
        result = dict(report)
        source_catalog_report = dict(result["source_catalog"])
        source_set_report = dict(source_catalog_report["source_set"])
        source_set_report.pop("origin")
        source_catalog_report["source_set"] = source_set_report
        result["source_catalog"] = source_catalog_report
        return result

    def test_design_without_top_has_six_internal_signals(self):
        graph = self._graph(FIXTURE_ROOT / "design.f")
        self.assertEqual(
            [symbol.name for symbol in graph.symbols],
            ["state", "state_net", "state", "state", "child_o", "hidden"],
        )
        self.assertEqual({symbol.category for symbol in graph.symbols}, {"signals"})
        self.assertEqual(
            {symbol.name for symbol in graph.symbols},
            {"state", "state_net", "child_o", "hidden"},
        )
        self.assertFalse(any(symbol.name in {"in_i", "out_o"} for symbol in graph.symbols))

    def test_top_does_not_change_signal_payload_and_keeps_closure_external_signals(self):
        without_top = self._graph(FIXTURE_ROOT / "design.f")
        with_top = self._graph(FIXTURE_ROOT / "design.f", top="top")
        self.assertEqual(self._symbol_payload(without_top), self._symbol_payload(with_top))
        self.assertIn("hidden", {symbol.name for symbol in with_top.symbols})
        self.assertEqual(
            sum(symbol.name == "state" for symbol in with_top.symbols), 3
        )

    def test_repeated_child_instances_share_source_symbols_and_occurrences(self):
        graph = self._graph(FIXTURE_ROOT / "design.f", top="top")
        child_symbols = [
            symbol
            for symbol in graph.symbols
            if symbol.owner_module.startswith("module:rtl/child.sv:")
        ]
        self.assertEqual(
            {symbol.name for symbol in child_symbols}, {"state", "state_net"}
        )
        self.assertEqual(
            {len(symbol.occurrences) for symbol in child_symbols}, {2}
        )

    def test_same_names_are_separated_by_declaration_and_owner(self):
        graph = self._graph(FIXTURE_ROOT / "design.f")
        states = [symbol for symbol in graph.symbols if symbol.name == "state"]
        self.assertEqual(len(states), 3)
        self.assertEqual(
            len({symbol.symbol_id for symbol in states}), 3
        )
        self.assertEqual(
            len({symbol.owner_module for symbol in states}), 3
        )

    def test_ranges_references_provenance_sorting_and_audit(self):
        graph = self._graph(FIXTURE_ROOT / "design.f")
        all_ranges = []
        for symbol in graph.symbols:
            self.assertEqual(symbol.impact, "local")
            self.assertEqual(symbol.abi, "internal")
            self.assertEqual(symbol.support, "eligible")
            self.assertIsNone(symbol.reason)
            self.assertEqual(symbol.owner_module, symbol.semantic_owner)
            all_ranges.append((symbol, symbol.declaration))
            previous = None
            for occurrence in symbol.occurrences:
                self.assertEqual(occurrence.provenance, "semantic_expression")
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
        self.assertEqual(len(graph.symbols), 6)
        self.assertEqual(sum(len(symbol.occurrences) for symbol in graph.symbols), 12)
        self.assertEqual(graph.to_report()["range_audit"], {
            "symbols": 6,
            "declarations": 6,
            "occurrences": 12,
            "total_ranges": 18,
        })
        self.assertEqual(
            len({
                (source_range.file, source_range.start, source_range.end)
                for _, source_range in all_ranges
            }),
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

    def test_project_root_matches_equivalent_closure_filelist(self):
        project_graph = build_symbol_graph(
            build_source_catalog(
                from_project_root(project_root=FIXTURE_ROOT, top="top")
            )
        )
        filelist_graph = self._graph(FIXTURE_ROOT / "closure.f", top="top")
        self.assertEqual(
            self._without_origin(project_graph.to_report()),
            self._without_origin(filelist_graph.to_report()),
        )

    def test_single_file_matches_equivalent_single_filelist(self):
        single_graph = build_symbol_graph(
            build_source_catalog(
                from_single_file(
                    source_file=FIXTURE_ROOT / "rtl" / "standalone.sv",
                    source_root=FIXTURE_ROOT,
                )
            )
        )
        filelist_graph = self._graph(FIXTURE_ROOT / "single.f")
        self.assertEqual(
            self._without_origin(single_graph.to_report()),
            self._without_origin(filelist_graph.to_report()),
        )

    def test_report_schema_and_canonical_json(self):
        graph = self._graph(FIXTURE_ROOT / "design.f", top="top")
        first = json.dumps(graph.to_report(), sort_keys=True, separators=(",", ":"))
        second = json.dumps(graph.to_report(), sort_keys=True, separators=(",", ":"))
        self.assertEqual(first, second)
        self.assertEqual(graph.to_report()["categories"], ["signals"])
        self.assertEqual(graph.to_report()["source_catalog"], graph.source_catalog.to_report())
        source_catalog_field = next(
            field for field in fields(graph) if field.name == "source_catalog"
        )
        self.assertFalse(source_catalog_field.repr)
        self.assertFalse(source_catalog_field.compare)
        self.assertNotIsInstance(graph.to_report(), SourceSymbol)

    def test_graph_reuses_catalog_and_legacy_paths_are_not_called(self):
        source_set = from_filelist(
            filelist=FIXTURE_ROOT / "design.f",
            source_root=FIXTURE_ROOT,
            top="top",
        )
        catalog = build_source_catalog(source_set)
        with (
            mock.patch.object(
                source_catalog,
                "_compile_view",
                side_effect=AssertionError("catalog recompilation"),
            ),
            mock.patch.object(
                source_catalog,
                "build_source_catalog",
                side_effect=AssertionError("catalog rebuild"),
            ),
            mock.patch.object(
                project, "analyze_project", side_effect=AssertionError("legacy path")
            ),
            mock.patch.object(
                inventory,
                "build_top_project_inventory",
                side_effect=AssertionError("inventory path"),
            ),
        ):
            graph = build_symbol_graph(catalog)
        self.assertEqual(len(graph.symbols), 6)

    def test_hierarchical_signal_reference_fails_closed(self):
        source_set = from_filelist(
            filelist=INVALID_ROOT / "hierarchical.f",
            source_root=INVALID_ROOT,
        )
        catalog = build_source_catalog(source_set)
        with self.assertRaises(SymbolGraphError) as raised:
            build_symbol_graph(catalog)
        self.assertEqual(raised.exception.code, "SYMBOL_GRAPH_UNSUPPORTED_REFERENCE")
        self.assertTrue(
            str(raised.exception).startswith("SYMBOL_GRAPH_UNSUPPORTED_REFERENCE: ")
        )

    def test_uninstantiated_definition_fails_closed(self):
        catalog = build_source_catalog(
            from_filelist(
                filelist=INVALID_ROOT / "uninstantiated.f",
                source_root=INVALID_ROOT,
            )
        )
        self.assertEqual(
            catalog.to_report()["compile"]["catalog"],
            {"parse_errors": 0, "semantic_errors": 0},
        )
        nodes = []
        catalog.catalog_root.visit(nodes.append)
        self.assertTrue(
            any(isinstance(node, pyslang.ast.UninstantiatedDefSymbol) for node in nodes)
        )
        with self.assertRaises(SymbolGraphError) as raised:
            build_symbol_graph(catalog)
        self.assertEqual(raised.exception.code, "SYMBOL_GRAPH_UNSUPPORTED_REFERENCE")

    def test_macro_signal_declaration_fails_closed(self):
        catalog = build_source_catalog(
            from_filelist(
                filelist=INVALID_ROOT / "macro_declaration.f",
                source_root=INVALID_ROOT,
            )
        )
        self.assertEqual(
            catalog.to_report()["compile"]["catalog"],
            {"parse_errors": 0, "semantic_errors": 0},
        )
        with self.assertRaises(SymbolGraphError) as raised:
            build_symbol_graph(catalog)
        self.assertEqual(raised.exception.code, "SYMBOL_GRAPH_UNSUPPORTED_SOURCE")

    def test_macro_signal_reference_fails_closed(self):
        catalog = build_source_catalog(
            from_filelist(
                filelist=INVALID_ROOT / "macro_reference.f",
                source_root=INVALID_ROOT,
            )
        )
        self.assertEqual(
            catalog.to_report()["compile"]["catalog"],
            {"parse_errors": 0, "semantic_errors": 0},
        )
        with self.assertRaises(SymbolGraphError) as raised:
            build_symbol_graph(catalog)
        self.assertEqual(raised.exception.code, "SYMBOL_GRAPH_UNSUPPORTED_SOURCE")

    def test_signal_bytes_changed_after_catalog_fail_with_range_invalid(self):
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
            child_file.write_text(
                child_file.read_text(encoding="utf-8").replace(
                    "logic state;", "logic stete;", 1
                ),
                encoding="utf-8",
            )
            with self.assertRaises(SymbolGraphError) as raised:
                build_symbol_graph(catalog)
        self.assertEqual(raised.exception.code, "SYMBOL_GRAPH_RANGE_INVALID")

    def test_missing_owner_registry_fails_closed(self):
        catalog = build_source_catalog(
            from_filelist(
                filelist=FIXTURE_ROOT / "design.f",
                source_root=FIXTURE_ROOT,
            )
        )
        with self.assertRaises(SymbolGraphError) as raised:
            build_symbol_graph(replace(catalog, modules=()))
        self.assertEqual(raised.exception.code, "SYMBOL_GRAPH_OWNER_MISMATCH")


if __name__ == "__main__":
    unittest.main()
