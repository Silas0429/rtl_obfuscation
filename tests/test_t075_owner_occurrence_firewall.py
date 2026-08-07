from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from rtl_obfuscator.category_registry_vnext import (
    CANONICAL_CATEGORIES,
    MODULE_ABI_CATEGORIES,
)
from rtl_obfuscator.mapping_vnext import build_mapping_vnext
from rtl_obfuscator.rewrite_policy import build_rewrite_policy
from rtl_obfuscator.rewrite_vnext import restore_gate_vnext, write_gate_vnext
from rtl_obfuscator.source_catalog import SourceRange, build_source_catalog
from rtl_obfuscator.source_set import from_filelist
from rtl_obfuscator.symbol_graph import (
    SourceSymbol,
    SymbolGraphError,
    SymbolOccurrence,
    _NestedModuleSpan,
    _apply_owner_quarantine,
    build_symbol_graph,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "t075_owner_occurrence_firewall"


def _deterministic_factory(
    symbol_id: str, name_length: int, unavailable: frozenset[str]
) -> str:
    del unavailable
    return "n" + hashlib.sha256(symbol_id.encode("utf-8")).hexdigest()[: name_length - 1]


class T075OwnerOccurrenceFirewallTests(unittest.TestCase):
    @staticmethod
    def _source_set(root: Path = FIXTURE_ROOT):
        return from_filelist(
            filelist=root / "design.f",
            source_root=root,
            top="t075_top",
        )

    @classmethod
    def _catalog_graph(cls):
        source_set = cls._source_set()
        catalog = build_source_catalog(source_set)
        return source_set, catalog, build_symbol_graph(catalog)

    @classmethod
    def _mapping(cls):
        _source_set, _catalog, graph = cls._catalog_graph()
        policy = build_rewrite_policy(
            graph,
            categories=CANONICAL_CATEGORIES,
            abi_categories=MODULE_ABI_CATEGORIES,
        )
        return build_mapping_vnext(
            policy,
            name_length=16,
            name_factory=_deterministic_factory,
        )

    @staticmethod
    def _owner_ids(catalog):
        return {module.name: module.owner_id for module in catalog.modules}

    @staticmethod
    def _module_span(catalog, name: str) -> SourceRange:
        nodes = []
        catalog.catalog_root.visit(nodes.append)
        spans = set()
        for node in nodes:
            if type(node).__name__ != "InstanceBodySymbol":
                continue
            definition = getattr(node, "definition", None)
            if str(getattr(definition, "name", "")) != name:
                continue
            syntax_range = getattr(getattr(node, "syntax", None), "sourceRange", None)
            start = getattr(syntax_range, "start", None)
            end = getattr(syntax_range, "end", None)
            if start is None or end is None or start.buffer != end.buffer:
                continue
            absolute = Path(
                catalog.catalog_source_manager.getFullPath(start.buffer)
            ).resolve()
            file = absolute.relative_to(catalog.source_set.source_root).as_posix()
            spans.add((file, int(start.offset), int(end.offset)))
        if len(spans) != 1:
            raise AssertionError(f"{name} did not resolve to one physical module span: {spans}")
        return SourceRange(*next(iter(spans)))

    @staticmethod
    def _is_contained(source_range: SourceRange, span: SourceRange) -> bool:
        return (
            source_range.file == span.file
            and span.start <= source_range.start
            and source_range.end <= span.end
        )

    @staticmethod
    def _physical_files(source_set):
        return tuple(
            dict.fromkeys(
                (*source_set.ordered_source_files, *source_set.included_files)
            )
        )

    @staticmethod
    def _formal(gate_dir: Path):
        command = [
            sys.executable,
            "scripts/formal_equivalence.py",
            "--gold-filelist",
            "tests/fixtures/t075_owner_occurrence_firewall/design.f",
            "--gold-root",
            "tests/fixtures/t075_owner_occurrence_firewall",
            "--gate-filelist",
            str(gate_dir / "design.f"),
            "--gate-root",
            str(gate_dir),
            "--top",
            "t075_top",
            "--seq",
            "5",
        ]
        return subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=180,
        ), command

    def test_catalog_compile_and_graph_reuses_semantic_view(self):
        source_set = self._source_set()
        catalog = build_source_catalog(source_set)
        self.assertEqual(
            catalog.to_report()["compile"],
            {
                "catalog": {"parse_errors": 0, "semantic_errors": 0},
                "top_overlay": {"parse_errors": 0, "semantic_errors": 0},
            },
        )
        with mock.patch(
            "rtl_obfuscator.source_catalog._compile_view",
            side_effect=AssertionError("T075 graph rebuilt a semantic view"),
        ):
            graph = build_symbol_graph(catalog)
        self.assertIs(graph.source_catalog, catalog)
        self.assertEqual(
            tuple(source_set.compile_order),
            (
                "rtl/parameter_target.sv",
                "rtl/child.sv",
                "rtl/defparam_owner.sv",
                "rtl/sibling.sv",
                "rtl/top.sv",
            ),
        )

    def test_graph_firewalls_entire_cross_owner_symbols(self):
        _source_set, catalog, graph = self._catalog_graph()
        owners = self._owner_ids(catalog)
        protected_span = self._module_span(catalog, "t075_defparam_owner")

        for owner_name in ("t075_defparam_owner", "t075_parameter_target"):
            owner_symbols = [
                symbol
                for symbol in graph.symbols
                if symbol.owner_module == owners[owner_name]
            ]
            self.assertTrue(owner_symbols)
            self.assertTrue(all(
                symbol.support == "unsupported"
                and symbol.reason == "defparam_binding_not_renamed"
                for symbol in owner_symbols
            ))
        protected_target = next(
            symbol
            for symbol in graph.symbols
            if symbol.owner_module == owners["t075_parameter_target"]
            and symbol.category == "modules"
        )
        self.assertTrue(any(
            self._is_contained(occurrence.source_range, protected_span)
            for occurrence in protected_target.occurrences
        ))

        child_symbols = [
            symbol
            for symbol in graph.symbols
            if symbol.owner_module == owners["t075_child"]
        ]
        firewall_symbols = [
            symbol
            for symbol in child_symbols
            if (symbol.category, symbol.name)
            in {
                ("modules", "t075_child"),
                ("ports", "data_i"),
                ("ports", "data_o"),
            }
        ]
        self.assertEqual(len(firewall_symbols), 3)
        for symbol in firewall_symbols:
            self.assertEqual(
                (symbol.support, symbol.reason),
                ("unsupported", "occurrence_in_quarantined_owner"),
            )
            self.assertTrue(symbol.occurrences)
            self.assertTrue(any(
                self._is_contained(occurrence.source_range, protected_span)
                for occurrence in symbol.occurrences
            ))
        child_state = next(
            symbol
            for symbol in child_symbols
            if symbol.category == "signals" and symbol.name == "child_state"
        )
        self.assertEqual((child_state.support, child_state.reason), ("eligible", None))

    def test_graph_and_mapping_ranges_are_one_to_one_and_edit_safe(self):
        mapping = self._mapping()
        graph = mapping.rewrite_policy.symbol_graph
        catalog = graph.source_catalog
        owners = self._owner_ids(catalog)
        protected_spans = (
            self._module_span(catalog, "t075_defparam_owner"),
            self._module_span(catalog, "t075_parameter_target"),
        )
        symbols = {symbol.symbol_id: symbol for symbol in graph.symbols}
        records = {record.symbol_id: record for record in mapping.records}
        self.assertEqual(len(symbols), len(graph.symbols))
        self.assertEqual(len(records), len(mapping.records))
        self.assertEqual(set(symbols), set(records))
        for symbol_id, symbol in symbols.items():
            record = records[symbol_id]
            self.assertEqual(record.declaration, symbol.declaration)
            self.assertEqual(record.occurrences, symbol.occurrences)
        self.assertEqual(
            graph.to_report()["range_audit"],
            mapping.to_report()["range_audit"] | {"symbols": len(symbols)},
        )

        seen_ranges = set()
        for symbol in graph.symbols:
            for source_range in (
                symbol.declaration,
                *(occurrence.source_range for occurrence in symbol.occurrences),
            ):
                key = (source_range.file, source_range.start, source_range.end)
                self.assertNotIn(key, seen_ranges)
                seen_ranges.add(key)

        firewall_ids = {
            symbol.symbol_id
            for symbol in graph.symbols
            if symbol.reason == "occurrence_in_quarantined_owner"
        }
        self.assertTrue(firewall_ids)
        self.assertTrue(all(records[symbol_id].action == "unsupported" for symbol_id in firewall_ids))

        with tempfile.TemporaryDirectory(prefix="t075-edits-") as temporary:
            execution = write_gate_vnext(
                mapping,
                output_dir=Path(temporary) / "gate",
            )
        self.assertTrue(execution.edits)
        self.assertTrue(all(edit.symbol_id in symbols for edit in execution.edits))
        self.assertFalse(any(edit.symbol_id in firewall_ids for edit in execution.edits))
        self.assertFalse(any(
            self._is_contained(edit.source_range, span)
            for edit in execution.edits
            for span in protected_spans
        ))

        edited_owners = {
            symbols[edit.symbol_id].owner_module for edit in execution.edits
        }
        self.assertIn(owners["t075_child"], edited_owners)
        self.assertIn(owners["t075_sibling"], edited_owners)
        self.assertIn(owners["t075_top"], edited_owners)
        sibling_actions = {
            (record.category, record.action)
            for record in mapping.records
            if record.owner_module == owners["t075_sibling"]
        }
        self.assertIn(("modules", "rename"), sibling_actions)
        self.assertIn(("ports", "rename"), sibling_actions)
        self.assertIn(("signals", "rename"), sibling_actions)
        child_state = next(
            symbol
            for symbol in graph.symbols
            if symbol.owner_module == owners["t075_child"]
            and symbol.name == "child_state"
        )
        self.assertTrue(any(edit.symbol_id == child_state.symbol_id for edit in execution.edits))

    def test_missing_or_partial_protected_spans_fail_closed(self):
        symbol = SourceSymbol(
            symbol_id="symbol:signals:rtl/design.sv:0:4",
            category="signals",
            name="safe",
            declaration=SourceRange("rtl/design.sv", 0, 4),
            owner_module="safe-owner",
            semantic_owner="safe-owner",
            occurrences=(
                SymbolOccurrence(
                    SourceRange("rtl/design.sv", 8, 12),
                    "semantic_expression",
                ),
            ),
            impact="local",
            abi="internal",
            support="eligible",
            reason=None,
        )
        common = {
            "symbols": [symbol],
            "type_parameter_owner_ids": set(),
            "type_parameter_symbol_ids": set(),
            "defparam_owner_ids": {"protected-owner"},
            "nested_module_spans": (),
            "macro_module_spans": (),
        }
        with self.assertRaises(SymbolGraphError) as missing:
            _apply_owner_quarantine(**common, ordinary_module_spans=())
        self.assertEqual(missing.exception.code, "SYMBOL_GRAPH_OWNER_MISMATCH")

        with self.assertRaises(SymbolGraphError) as partial:
            _apply_owner_quarantine(
                **common,
                ordinary_module_spans=(
                    _NestedModuleSpan(
                        "protected-owner",
                        SourceRange("rtl/design.sv", 10, 20),
                    ),
                ),
            )
        self.assertEqual(partial.exception.code, "SYMBOL_GRAPH_RANGE_CONFLICT")
        self.assertEqual((partial.exception.file, partial.exception.start), ("rtl/design.sv", 8))

    def test_actual_gate_strict_compile_and_restore_are_byte_identical(self):
        mapping = self._mapping()
        source_set = mapping.rewrite_policy.symbol_graph.source_catalog.source_set
        physical_files = self._physical_files(source_set)
        self.assertEqual(len(physical_files), 5)
        gold = {file: (FIXTURE_ROOT / file).read_bytes() for file in physical_files}
        with tempfile.TemporaryDirectory(prefix="t075-gate-") as temporary:
            root = Path(temporary)
            gate_dir = root / "gate"
            restore_dir = root / "restore"
            execution = write_gate_vnext(mapping, output_dir=gate_dir)
            self.assertEqual(
                (
                    execution.compile_evidence.catalog_parse_errors,
                    execution.compile_evidence.catalog_semantic_errors,
                    execution.compile_evidence.top_overlay_parse_errors,
                    execution.compile_evidence.top_overlay_semantic_errors,
                ),
                (0, 0, 0, 0),
            )
            restored = restore_gate_vnext(
                execution,
                gate_dir=gate_dir,
                output_dir=restore_dir,
            )
            self.assertTrue(restored.to_report()["summary"]["byte_identical"])
            self.assertEqual(
                {file: (restore_dir / file).read_bytes() for file in physical_files},
                gold,
            )

    def test_actual_renamed_gate_formal_positive(self):
        mapping = self._mapping()
        with tempfile.TemporaryDirectory(prefix="t075-formal-positive-") as temporary:
            gate_dir = Path(temporary) / "gate"
            execution = write_gate_vnext(mapping, output_dir=gate_dir)
            self.assertTrue(execution.edits)
            result, command = self._formal(gate_dir)
            print(f"T075_FORMAL_GATE {gate_dir}")
            print(f"T075_FORMAL_COMMAND {shlex.join(command)}")
            print(f"T075_FORMAL_EXIT {result.returncode}")
            print(f"T075_FORMAL_JSON {result.stdout.strip()}")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(
                json.loads(result.stdout.strip().splitlines()[-1])["formal_equivalence"],
                "pass",
            )

    def test_fixed_function_negative_strict_compiles_and_formal_fails(self):
        mapping = self._mapping()
        source_set = mapping.rewrite_policy.symbol_graph.source_catalog.source_set
        with tempfile.TemporaryDirectory(prefix="t075-formal-negative-") as temporary:
            root = Path(temporary)
            gate_dir = root / "gate"
            write_gate_vnext(mapping, output_dir=gate_dir)
            negative_dir = root / "negative"
            shutil.copytree(gate_dir, negative_dir)
            top = negative_dir / "rtl/top.sv"
            original = top.read_bytes()
            marker = b"assign data_o = "
            self.assertEqual(original.count(marker), 1)
            top.write_bytes(original.replace(marker, b"assign data_o = ~", 1))
            negative_set = replace(source_set, source_root=negative_dir.resolve())
            negative_compile = build_source_catalog(negative_set).to_report()["compile"]
            self.assertEqual(
                negative_compile,
                {
                    "catalog": {"parse_errors": 0, "semantic_errors": 0},
                    "top_overlay": {"parse_errors": 0, "semantic_errors": 0},
                },
            )
            result, command = self._formal(negative_dir)
            combined_output = result.stdout + result.stderr
            key_output = "\n".join(
                line
                for line in combined_output.splitlines()
                if "unproven" in line.lower()
                or "equiv_status -assert" in line.lower()
            )
            print(f"T075_FORMAL_NEGATIVE_GATE {negative_dir}")
            print(f"T075_FORMAL_NEGATIVE_COMMAND {shlex.join(command)}")
            print(f"T075_FORMAL_NEGATIVE_COMPILE {json.dumps(negative_compile, sort_keys=True)}")
            print(f"T075_FORMAL_NEGATIVE_EXIT {result.returncode}")
            print(f"T075_FORMAL_NEGATIVE_OUTPUT {key_output}")
            combined = combined_output.lower()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unproven", combined)
            self.assertIn("equiv_status -assert", combined)


if __name__ == "__main__":
    unittest.main()
