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
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "t077_multiple_quarantine"


def _deterministic_factory(
    symbol_id: str, name_length: int, unavailable: frozenset[str]
) -> str:
    del unavailable
    return "n" + hashlib.sha256(symbol_id.encode("utf-8")).hexdigest()[
        : name_length - 1
    ]


def _unit_symbol(
    symbol_id: str,
    *,
    owner: str,
    declaration: SourceRange,
    occurrences: tuple[SymbolOccurrence, ...] = (),
) -> SourceSymbol:
    return SourceSymbol(
        symbol_id=symbol_id,
        category="signals",
        name=symbol_id,
        declaration=declaration,
        owner_module=owner,
        semantic_owner=owner,
        occurrences=occurrences,
        impact="local",
        abi="internal",
        support="eligible",
        reason=None,
    )


class T077MultipleQuarantineReasonMergeTests(unittest.TestCase):
    @staticmethod
    def _source_set(root: Path = FIXTURE_ROOT):
        return from_filelist(
            filelist=root / "design.f",
            source_root=root,
            top="t077_top",
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
            file = absolute.relative_to(
                catalog.source_set.source_root
            ).as_posix()
            spans.add((file, int(start.offset), int(end.offset)))
        if len(spans) != 1:
            raise AssertionError(
                f"{name} did not resolve to one physical module span: {spans}"
            )
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
            "tests/fixtures/t077_multiple_quarantine/design.f",
            "--gold-root",
            "tests/fixtures/t077_multiple_quarantine",
            "--gate-filelist",
            str(gate_dir / "design.f"),
            "--gate-root",
            str(gate_dir),
            "--top",
            "t077_top",
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

    def test_catalog_graph_reuses_semantic_view_and_records_prefixed_conflict(self):
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
            side_effect=AssertionError("T077 graph rebuilt a semantic view"),
        ):
            graph = build_symbol_graph(catalog)
        self.assertIs(graph.source_catalog, catalog)
        self.assertEqual(
            tuple(source_set.compile_order),
            (
                "rtl/parameter_target.sv",
                "rtl/combined_owner.sv",
                "rtl/sibling.sv",
                "rtl/top.sv",
            ),
        )
        task = (
            ROOT / "docs/tasks/T077_multiple_quarantine_reason_merge.md"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'pre_fix_characterization: PASS；冻结 fixture catalog/top overlay 为 0/0 + 0/0；未改产品代码时 `build_symbol_graph()` 精确抛 `SymbolGraphError(code="SYMBOL_GRAPH_RANGE_CONFLICT")`，文本 `SYMBOL_GRAPH_RANGE_CONFLICT: physical module owner has conflicting quarantine reasons`',
            task,
        )

    def test_combined_owner_span_is_atomically_quarantined(self):
        _source_set, catalog, graph = self._catalog_graph()
        owners = self._owner_ids(catalog)
        combined_span = self._module_span(catalog, "t077_combined_owner")
        combined_symbols = [
            symbol
            for symbol in graph.symbols
            if self._is_contained(symbol.declaration, combined_span)
        ]
        self.assertEqual(len(combined_symbols), 11)
        self.assertEqual(
            {(symbol.support, symbol.reason) for symbol in combined_symbols},
            {
                (
                    "unsupported",
                    "owner_contains_multiple_unsupported_constructs",
                )
            },
        )
        self.assertEqual(
            {
                (symbol.category, symbol.name)
                for symbol in combined_symbols
                if symbol.category in {"modules", "genvars", "generate_blocks"}
            },
            {
                ("modules", "t077_combined_owner"),
                ("genvars", "outer"),
                ("genvars", "inner"),
                ("generate_blocks", "g_outer"),
                ("generate_blocks", "g_inner"),
            },
        )
        target_symbols = [
            symbol
            for symbol in graph.symbols
            if symbol.owner_module == owners["t077_parameter_target"]
        ]
        self.assertEqual(len(target_symbols), 5)
        self.assertEqual(
            {(symbol.support, symbol.reason) for symbol in target_symbols},
            {("unsupported", "defparam_binding_not_renamed")},
        )
        self.assertTrue(any(
            occurrence.provenance == "defparam_binding"
            for symbol in target_symbols
            for occurrence in symbol.occurrences
        ))

    def test_exact_span_merge_and_ambiguous_span_inputs_fail_closed(self):
        span = SourceRange("rtl/design.sv", 0, 100)
        protected = _unit_symbol(
            "protected",
            owner="owner",
            declaration=SourceRange("rtl/design.sv", 10, 19),
        )
        generate_owned = _unit_symbol(
            "generate-owned",
            owner="generate-owner",
            declaration=SourceRange("rtl/design.sv", 30, 44),
        )
        external = _unit_symbol(
            "external",
            owner="external-owner",
            declaration=SourceRange("rtl/external.sv", 1, 9),
            occurrences=(
                SymbolOccurrence(
                    SourceRange("rtl/design.sv", 50, 58),
                    "semantic_expression",
                ),
            ),
        )
        merged = _apply_owner_quarantine(
            [protected, generate_owned, external],
            type_parameter_owner_ids=set(),
            type_parameter_symbol_ids=set(),
            defparam_owner_ids={"owner"},
            nested_module_spans=(_NestedModuleSpan("owner", span),),
            macro_module_spans=(),
            ordinary_module_spans=(_NestedModuleSpan("owner", span),),
        )
        self.assertEqual(
            [(symbol.support, symbol.reason) for symbol in merged],
            [
                (
                    "unsupported",
                    "owner_contains_multiple_unsupported_constructs",
                ),
                (
                    "unsupported",
                    "owner_contains_multiple_unsupported_constructs",
                ),
                ("unsupported", "occurrence_in_quarantined_owner"),
            ],
        )

        with self.assertRaises(SymbolGraphError) as different_span:
            _apply_owner_quarantine(
                [],
                type_parameter_owner_ids=set(),
                type_parameter_symbol_ids=set(),
                defparam_owner_ids=set(),
                nested_module_spans=(_NestedModuleSpan("owner", span),),
                macro_module_spans=(
                    _NestedModuleSpan(
                        "owner", SourceRange("rtl/design.sv", 0, 99)
                    ),
                ),
                ordinary_module_spans=(_NestedModuleSpan("owner", span),),
            )
        self.assertEqual(
            different_span.exception.code, "SYMBOL_GRAPH_OWNER_MISMATCH"
        )

        with self.assertRaises(SymbolGraphError) as missing_span:
            _apply_owner_quarantine(
                [],
                type_parameter_owner_ids=set(),
                type_parameter_symbol_ids=set(),
                defparam_owner_ids={"owner"},
                nested_module_spans=(),
                macro_module_spans=(),
                ordinary_module_spans=(),
            )
        self.assertEqual(
            missing_span.exception.code, "SYMBOL_GRAPH_OWNER_MISMATCH"
        )

        with self.assertRaises(SymbolGraphError) as overlap:
            _apply_owner_quarantine(
                [],
                type_parameter_owner_ids=set(),
                type_parameter_symbol_ids=set(),
                defparam_owner_ids={"left", "right"},
                nested_module_spans=(),
                macro_module_spans=(),
                ordinary_module_spans=(
                    _NestedModuleSpan(
                        "left", SourceRange("rtl/design.sv", 0, 20)
                    ),
                    _NestedModuleSpan(
                        "right", SourceRange("rtl/design.sv", 10, 30)
                    ),
                ),
            )
        self.assertEqual(overlap.exception.code, "SYMBOL_GRAPH_RANGE_CONFLICT")

    def test_mapping_ranges_actions_and_edits_are_auditable(self):
        mapping = self._mapping()
        graph = mapping.rewrite_policy.symbol_graph
        catalog = graph.source_catalog
        owners = self._owner_ids(catalog)
        combined_span = self._module_span(catalog, "t077_combined_owner")
        target_span = self._module_span(catalog, "t077_parameter_target")
        symbols = {symbol.symbol_id: symbol for symbol in graph.symbols}
        records = {record.symbol_id: record for record in mapping.records}
        self.assertEqual(set(symbols), set(records))
        self.assertEqual(
            graph.to_report()["range_audit"],
            {
                "symbols": 27,
                "declarations": 27,
                "occurrences": 35,
                "total_ranges": 62,
            },
        )
        self.assertEqual(
            mapping.to_report()["summary"],
            {"rename": 8, "preserve": 3, "unsupported": 16, "total": 27},
        )
        seen_ranges = set()
        combined_ids = set()
        for symbol in graph.symbols:
            record = records[symbol.symbol_id]
            self.assertEqual(record.declaration, symbol.declaration)
            self.assertEqual(record.occurrences, symbol.occurrences)
            if self._is_contained(symbol.declaration, combined_span):
                combined_ids.add(symbol.symbol_id)
                self.assertEqual(record.action, "unsupported")
            for source_range in (
                symbol.declaration,
                *(occurrence.source_range for occurrence in symbol.occurrences),
            ):
                key = (source_range.file, source_range.start, source_range.end)
                self.assertNotIn(key, seen_ranges)
                seen_ranges.add(key)

        with tempfile.TemporaryDirectory(prefix="t077-edits-") as temporary:
            execution = write_gate_vnext(
                mapping,
                output_dir=Path(temporary) / "gate",
            )
        self.assertEqual(len(execution.edits), 19)
        self.assertTrue(all(edit.symbol_id in symbols for edit in execution.edits))
        self.assertFalse(any(
            edit.symbol_id in combined_ids for edit in execution.edits
        ))
        self.assertFalse(any(
            self._is_contained(edit.source_range, span)
            for edit in execution.edits
            for span in (combined_span, target_span)
        ))
        edited_owners = {
            symbols[edit.symbol_id].owner_module for edit in execution.edits
        }
        self.assertIn(owners["t077_sibling"], edited_owners)
        self.assertIn(owners["t077_top"], edited_owners)
        sibling_actions = {
            (record.category, record.action)
            for record in mapping.records
            if record.owner_module == owners["t077_sibling"]
        }
        self.assertIn(("modules", "rename"), sibling_actions)
        self.assertIn(("ports", "rename"), sibling_actions)
        self.assertIn(("signals", "rename"), sibling_actions)
        self.assertTrue(any(
            records[edit.symbol_id].owner_module == owners["t077_top"]
            and records[edit.symbol_id].category in {"signals", "instances"}
            for edit in execution.edits
        ))

    def test_actual_gate_strict_compile_and_restore_are_byte_identical(self):
        mapping = self._mapping()
        source_set = mapping.rewrite_policy.symbol_graph.source_catalog.source_set
        physical_files = self._physical_files(source_set)
        self.assertEqual(len(physical_files), 4)
        gold = {file: (FIXTURE_ROOT / file).read_bytes() for file in physical_files}
        with tempfile.TemporaryDirectory(prefix="t077-gate-") as temporary:
            root = Path(temporary)
            gate_dir = root / "gate"
            restore_dir = root / "restore"
            execution = write_gate_vnext(mapping, output_dir=gate_dir)
            self.assertEqual(len(execution.edits), 19)
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
                {
                    file: (restore_dir / file).read_bytes()
                    for file in physical_files
                },
                gold,
            )

    def test_actual_renamed_gate_formal_positive(self):
        mapping = self._mapping()
        with tempfile.TemporaryDirectory(
            prefix="t077-formal-positive-"
        ) as temporary:
            gate_dir = Path(temporary) / "gate"
            execution = write_gate_vnext(mapping, output_dir=gate_dir)
            self.assertEqual(len(execution.edits), 19)
            result, command = self._formal(gate_dir)
            print(f"T077_FORMAL_GATE {gate_dir}")
            print(f"T077_FORMAL_COMMAND {shlex.join(command)}")
            print(f"T077_FORMAL_EXIT {result.returncode}")
            print(f"T077_FORMAL_JSON {result.stdout.strip()}")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            payload = json.loads(result.stdout.strip().splitlines()[-1])
            self.assertEqual(
                payload,
                {
                    "formal_equivalence": "pass",
                    "gate": str(gate_dir),
                    "gold": "tests/fixtures/t077_multiple_quarantine",
                    "seq": 5,
                    "top": "t077_top",
                },
            )

    def test_fixed_function_negative_strict_compiles_and_formal_fails(self):
        mapping = self._mapping()
        source_set = mapping.rewrite_policy.symbol_graph.source_catalog.source_set
        with tempfile.TemporaryDirectory(
            prefix="t077-formal-negative-"
        ) as temporary:
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
            negative_compile = build_source_catalog(negative_set).to_report()[
                "compile"
            ]
            self.assertEqual(
                negative_compile,
                {
                    "catalog": {"parse_errors": 0, "semantic_errors": 0},
                    "top_overlay": {
                        "parse_errors": 0,
                        "semantic_errors": 0,
                    },
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
            print(f"T077_FORMAL_NEGATIVE_GATE {negative_dir}")
            print(f"T077_FORMAL_NEGATIVE_COMMAND {shlex.join(command)}")
            print(
                "T077_FORMAL_NEGATIVE_COMPILE "
                + json.dumps(negative_compile, sort_keys=True)
            )
            print(f"T077_FORMAL_NEGATIVE_EXIT {result.returncode}")
            print(f"T077_FORMAL_NEGATIVE_OUTPUT {key_output}")
            combined = combined_output.lower()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unproven", combined)
            self.assertIn("equiv_status -assert", combined)

    def test_future_work_records_t077_and_retains_unresolved_boundaries(self):
        future_work = (
            ROOT / "docs/development/future_work.md"
        ).read_text(encoding="utf-8")
        self.assertIn("T077 已对同一 ordinary owner", future_work)
        self.assertIn(
            "owner_contains_multiple_unsupported_constructs", future_work
        )
        self.assertIn("owner/span 证据不一致和未知 reason 仍 fail-closed", future_work)
        for phrase in (
            "expression-sized cast",
            "package-qualified enum/member",
            "syntax-less implicit typedef conversion",
            "工程输入与验证",
        ):
            self.assertIn(phrase, future_work)


if __name__ == "__main__":
    unittest.main()
