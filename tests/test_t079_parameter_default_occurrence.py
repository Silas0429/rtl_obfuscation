from __future__ import annotations

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

import pyslang

from rtl_obfuscator import source_catalog as source_catalog_module
from rtl_obfuscator import symbol_graph as symbol_graph_module
from rtl_obfuscator.mapping_vnext import build_mapping_vnext
from rtl_obfuscator.rewrite_policy import build_rewrite_policy
from rtl_obfuscator.rewrite_vnext import write_gate_vnext
from rtl_obfuscator.source_catalog import build_source_catalog
from rtl_obfuscator.source_set import from_filelist
from rtl_obfuscator.symbol_graph import SymbolGraphError, build_symbol_graph


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "t079_parameter_default"
FILELIST = FIXTURE_ROOT / "design.f"
EXPECTED_FIXTURE = {
    "design.f": (27, "796843c56770f7b6789520664a253bf596bb245fd5dbda892f6f4203b2d3235d"),
    "child.sv": (328, "aa4809295ed11349ab623972a8cd2f91f08b7c3527e1b5c08c47902d45a37c57"),
    "sibling.sv": (206, "455edeaf904f105dfab2324da490ec9080430bc96e9696e08d8f8ec72794a365"),
    "top.sv": (387, "45f019baa145c94fb143be389f4853d6c1873499c239d75fd191eb9c45de936f"),
}


def _deterministic_factory(
    symbol_id: str, name_length: int, unavailable: frozenset[str]
) -> str:
    candidate = ("p" + hashlib.sha256(symbol_id.encode("utf-8")).hexdigest())[
        :name_length
    ]
    if candidate in unavailable:
        raise AssertionError("test factory collision")
    return candidate


class T079ParameterDefaultOccurrenceTests(unittest.TestCase):
    @staticmethod
    def _write_pattern_key_source(root: Path):
        source = b"""module t079_pattern_key;
    typedef struct packed { logic mie; } status_t;
    localparam int WIDTH = 1;
    localparam status_t RESET = '{mie: WIDTH};
    logic sink;
    assign sink = RESET.mie;
endmodule
"""
        (root / "pattern_key.sv").write_bytes(source)
        (root / "design.f").write_bytes(b"pattern_key.sv\n")
        source_set = from_filelist(
            filelist=root / "design.f",
            source_root=root,
            top="t079_pattern_key",
        )
        catalog = build_source_catalog(source_set)
        nodes = []
        catalog.catalog_root.visit(nodes.append)
        reset = next(
            node
            for node in nodes
            if getattr(node, "kind", None) == pyslang.ast.SymbolKind.Parameter
            and str(getattr(node, "name", "")) == "RESET"
        )
        initializer_nodes = []
        reset.syntax.initializer.visit(initializer_nodes.append)
        key = next(
            node
            for node in initializer_nodes
            if type(node).__name__ == "IdentifierNameSyntax"
            and str(node.identifier.rawText) == "mie"
        )
        value = next(
            node
            for node in initializer_nodes
            if type(node).__name__ == "IdentifierNameSyntax"
            and str(node.identifier.rawText) == "WIDTH"
        )
        return source, source_set, catalog, key, value

    @staticmethod
    def _source_set(root: Path = FIXTURE_ROOT, top: str = "t079_top"):
        return from_filelist(
            filelist=root / "design.f",
            source_root=root,
            top=top,
        )

    @classmethod
    def _catalog_graph(cls):
        source_set = cls._source_set()
        catalog = build_source_catalog(source_set)
        return source_set, catalog, build_symbol_graph(catalog)

    @staticmethod
    def _run_public(
        script: str, *arguments: str
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(ROOT / script), *arguments],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )

    def _encrypt(self, root: Path) -> tuple[Path, Path, dict[str, object]]:
        root.mkdir(parents=True, exist_ok=True)
        gate = root / "gate"
        result = self._run_public(
            "rtl_encrypt.py",
            "--filelist",
            "design.f",
            "--source-root",
            str(FIXTURE_ROOT),
            "--top",
            "t079_top",
            "--category",
            "parameters",
            "--output-dir",
            str(gate),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        mapping = gate / "mapping.json"
        report = json.loads(mapping.read_text(encoding="utf-8"))
        self.assertEqual(json.loads(result.stdout)["summary"], report["summary"])
        return gate, mapping, report

    @staticmethod
    def _formal(gate: Path) -> tuple[subprocess.CompletedProcess[str], list[str]]:
        command = [
            sys.executable,
            str(ROOT / "scripts" / "formal_equivalence.py"),
            "--gold-filelist",
            str(FILELIST),
            "--gold-root",
            str(FIXTURE_ROOT),
            "--gate-filelist",
            str(gate / "design.f"),
            "--gate-root",
            str(gate),
            "--top",
            "t079_top",
            "--seq",
            "5",
        ]
        return subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        ), command

    @staticmethod
    def _parameter(graph, file: str, start: int):
        return next(
            symbol
            for symbol in graph.symbols
            if symbol.category == "parameters"
            and symbol.declaration.file == file
            and symbol.declaration.start == start
        )

    def test_fixture_catalog_graph_and_exact_default_occurrence(self):
        for file, (expected_bytes, expected_sha256) in EXPECTED_FIXTURE.items():
            source = (FIXTURE_ROOT / file).read_bytes()
            self.assertEqual(len(source), expected_bytes, file)
            self.assertEqual(hashlib.sha256(source).hexdigest(), expected_sha256, file)

        source_set = self._source_set()
        catalog = build_source_catalog(source_set)
        with mock.patch.object(
            source_catalog_module,
            "_compile_view",
            side_effect=AssertionError("T079 graph rebuilt semantic view"),
        ):
            graph = build_symbol_graph(catalog)
        self.assertIs(graph.source_catalog, catalog)
        self.assertEqual(catalog.to_report()["compile"], {
            "catalog": {"parse_errors": 0, "semantic_errors": 0},
            "top_overlay": {"parse_errors": 0, "semantic_errors": 0},
        })
        self.assertEqual(graph.to_report()["range_audit"], {
            "symbols": 19,
            "declarations": 19,
            "occurrences": 26,
            "total_ranges": 45,
        })

        parameters = [symbol for symbol in graph.symbols if symbol.category == "parameters"]
        self.assertEqual((len(parameters), sum(len(item.occurrences) for item in parameters)), (6, 8))
        recovered = [
            (symbol, occurrence)
            for symbol in parameters
            for occurrence in symbol.occurrences
            if occurrence.provenance == "parameter_default"
        ]
        self.assertEqual(len(recovered), 1)
        symbol, occurrence = recovered[0]
        self.assertEqual((symbol.name, symbol.declaration.file, symbol.declaration.start, symbol.declaration.end), (
            "COMPRESSED", "child.sv", 41, 51
        ))
        self.assertEqual((occurrence.source_range.file, occurrence.source_range.start, occurrence.source_range.end), (
            "child.sv", 88, 98
        ))

        child = (FIXTURE_ROOT / "child.sv").read_bytes()
        sibling = (FIXTURE_ROOT / "sibling.sv").read_bytes()
        for file, source, expression in (
            ("child.sv", child, b"WIDTH * 2"),
            ("sibling.sv", sibling, b"WIDTH + 1"),
        ):
            start = source.index(expression)
            matching = [
                occurrence
                for parameter in parameters
                for occurrence in parameter.occurrences
                if occurrence.source_range.file == file
                and occurrence.source_range.start == start
                and occurrence.source_range.end == start + len(b"WIDTH")
            ]
            self.assertEqual(len(matching), 1)
            self.assertEqual(matching[0].provenance, "semantic_expression")

    def test_mapping_public_encrypt_strict_gate_and_source_free_restore(self):
        source_set, _catalog, graph = self._catalog_graph()
        policy = build_rewrite_policy(
            graph,
            categories=("parameters",),
            abi_categories=("parameters",),
        )
        mapping = build_mapping_vnext(
            policy,
            name_length=16,
            name_factory=_deterministic_factory,
        )
        self.assertEqual(mapping.to_report()["summary"], {
            "total": 19,
            "rename": 6,
            "preserve": 13,
            "unsupported": 0,
        })
        self.assertEqual(
            sum(1 + len(record.occurrences) for record in mapping.records if record.action == "rename"),
            14,
        )
        self.assertEqual(source_set.ordered_source_files, ("child.sv", "sibling.sv", "top.sv"))

        with tempfile.TemporaryDirectory(prefix="t079-public-") as temporary:
            root = Path(temporary)
            gate, mapping_path, report = self._encrypt(root / "encrypt")
            summary = report["summary"]
            self.assertEqual(
                (
                    summary["files"],
                    summary["mapping_records"],
                    summary["modified_tokens"],
                    summary["strict_compile_passed"],
                    summary["restored_byte_identical"],
                ),
                (3, 19, 14, True, True),
            )
            self.assertEqual(report["mapping_execution"]["summary"]["modified_tokens"], 14)
            gate_catalog = build_source_catalog(self._source_set(gate))
            self.assertEqual(gate_catalog.to_report()["compile"], {
                "catalog": {"parse_errors": 0, "semantic_errors": 0},
                "top_overlay": {"parse_errors": 0, "semantic_errors": 0},
            })
            records = report["mapping"]["records"]
            compressed = next(
                record for record in records
                if record["category"] == "parameters"
                and record["original_name"] == "COMPRESSED"
                and record["declaration"] == {"file": "child.sv", "start": 41, "end": 51}
            )
            align = next(
                record for record in records
                if record["category"] == "parameters"
                and record["original_name"] == "ALIGN"
            )
            child_gate = (gate / "child.sv").read_bytes()
            top_gate = (gate / "top.sv").read_bytes()
            self.assertNotIn(b"COMPRESSED", child_gate)
            self.assertNotIn(b"ALIGN", child_gate + top_gate)
            self.assertEqual(child_gate.count(compressed["renamed_name"].encode("ascii")), 3)
            self.assertEqual((child_gate + top_gate).count(align["renamed_name"].encode("ascii")), 3)

            restore = root / "restore"
            result = self._run_public(
                "rtl_decrypt.py",
                "--map",
                str(mapping_path),
                "--gate-dir",
                str(gate),
                "--output-dir",
                str(restore),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                {path.relative_to(restore).as_posix() for path in restore.rglob("*") if path.is_file()},
                {"child.sv", "sibling.sv", "top.sv"},
            )
            for file in ("child.sv", "sibling.sv", "top.sv"):
                self.assertEqual((restore / file).read_bytes(), (FIXTURE_ROOT / file).read_bytes())
            self.assertFalse((restore / "design.f").exists())

    def test_actual_renamed_gate_formal_positive(self):
        with tempfile.TemporaryDirectory(prefix="t079-formal-positive-") as temporary:
            gate, _mapping, _report = self._encrypt(Path(temporary) / "encrypt")
            formal, command = self._formal(gate)
            print(f"T079_FORMAL_COMMAND {shlex.join(command)}")
            print(f"T079_FORMAL_EXIT {formal.returncode}")
            print(f"T079_FORMAL_JSON {formal.stdout.strip()}")
        self.assertEqual(formal.returncode, 0, formal.stderr)
        payload = json.loads(formal.stdout)
        self.assertEqual(payload["formal_equivalence"], "pass")

    def test_fixed_function_negative_gate_strict_compile_and_formal_failure(self):
        with tempfile.TemporaryDirectory(prefix="t079-formal-negative-") as temporary:
            root = Path(temporary)
            gate, _mapping, _report = self._encrypt(root / "encrypt")
            negative = root / "negative"
            shutil.copytree(gate, negative)
            top = negative / "top.sv"
            source = top.read_bytes()
            marker = b"assign data_o = "
            self.assertEqual(source.count(marker), 1)
            top.write_bytes(source.replace(marker, b"assign data_o = ~", 1))
            negative_catalog = build_source_catalog(self._source_set(negative))
            self.assertEqual(negative_catalog.to_report()["compile"], {
                "catalog": {"parse_errors": 0, "semantic_errors": 0},
                "top_overlay": {"parse_errors": 0, "semantic_errors": 0},
            })
            formal, command = self._formal(negative)
            print(f"T079_FORMAL_NEGATIVE_COMMAND {shlex.join(command)}")
            print(f"T079_FORMAL_NEGATIVE_EXIT {formal.returncode}")
            print(f"T079_FORMAL_NEGATIVE_STDOUT {formal.stdout.strip()}")
        self.assertNotEqual(formal.returncode, 0)
        combined = formal.stdout + formal.stderr
        self.assertIn("unproven", combined)
        self.assertIn("equiv_status -assert", combined)

    def test_semantic_non_targets_are_ignored_and_cross_target_range_fails_closed(self):
        with tempfile.TemporaryDirectory(prefix="t079-negative-semantic-") as temporary:
            root = Path(temporary)
            source = b"""module t079_negative #(
    parameter type DATA_T = logic,
    parameter int WIDTH = 2,
    parameter int DEFAULT = WIDTH
) ();
    typedef enum int { ENUM_VALUE = 1 } enum_t;
    localparam int TYPE_BITS = $bits(DATA_T);
    localparam int ENUM_COPY = ENUM_VALUE;
    for (genvar lane = 0; lane < 1; lane++) begin : g
        localparam int LANE_COPY = lane;
    end
endmodule
module t079_negative_top;
    t079_negative #(.DEFAULT(3)) u_negative();
endmodule
"""
            (root / "negative.sv").write_bytes(source)
            (root / "design.f").write_bytes(b"negative.sv\n")
            graph = build_symbol_graph(build_source_catalog(self._source_set(root, "t079_negative_top")))
            recovered = [
                occurrence.source_range
                for symbol in graph.symbols
                if symbol.category == "parameters"
                for occurrence in symbol.occurrences
                if occurrence.provenance == "parameter_default"
            ]
            self.assertTrue(recovered)
            self.assertEqual(
                {source[item.start:item.end] for item in recovered},
                {b"WIDTH"},
            )

        with tempfile.TemporaryDirectory(prefix="t079-range-conflict-") as temporary:
            root = Path(temporary)
            source = b"""module t079_conflict_child #(
    parameter int FIRST = 1,
    parameter int SECOND = 2,
    parameter int VALUE = FIRST
) ();
endmodule
module t079_conflict_top;
    t079_conflict_child a();
    t079_conflict_child b();
endmodule
"""
            (root / "conflict.sv").write_bytes(source)
            (root / "design.f").write_bytes(b"conflict.sv\n")
            catalog = build_source_catalog(self._source_set(root, "t079_conflict_top"))
            nodes = []
            catalog.catalog_root.visit(nodes.append)
            first_offset = source.index(b"FIRST = 1")
            second_offset = source.index(b"SECOND = 2")
            token_offset = source.index(b"VALUE = FIRST") + len(b"VALUE = ")
            first = next(
                node for node in nodes
                if getattr(node, "kind", None) == pyslang.ast.SymbolKind.Parameter
                and str(getattr(node, "name", "")) == "FIRST"
                and int(node.location.offset) == first_offset
            )
            second = next(
                node for node in nodes
                if getattr(node, "kind", None) == pyslang.ast.SymbolKind.Parameter
                and str(getattr(node, "name", "")) == "SECOND"
                and int(node.location.offset) == second_offset
            )
            original = symbol_graph_module._scope_lookup_target
            hits = 0

            def conflicting_lookup(scope, token):
                nonlocal hits
                if (
                    str(getattr(token, "rawText", "")) == "FIRST"
                    and int(getattr(token.location, "offset", -1)) == token_offset
                ):
                    hits += 1
                    return first if hits == 1 else second
                return original(scope, token)

            with mock.patch.object(
                symbol_graph_module,
                "_scope_lookup_target",
                side_effect=conflicting_lookup,
            ), self.assertRaises(SymbolGraphError) as raised:
                build_symbol_graph(catalog)
            self.assertGreaterEqual(hits, 2)
            self.assertEqual(raised.exception.code, "SYMBOL_GRAPH_RANGE_CONFLICT")
            self.assertEqual((raised.exception.file, raised.exception.start), ("conflict.sv", token_offset))

    def test_assignment_pattern_key_skips_lookup_and_value_binding_remains_exact(self):
        with tempfile.TemporaryDirectory(prefix="t079-pattern-key-") as temporary:
            root = Path(temporary)
            source_root = root / "source"
            source_root.mkdir()
            source, _source_set, catalog, key, value = self._write_pattern_key_source(source_root)
            parent = key.parent
            parent_key = parent.key
            self.assertEqual(type(parent).__name__, "AssignmentPatternItemSyntax")
            self.assertEqual(type(parent_key).__name__, "IdentifierNameSyntax")
            self.assertEqual(type(parent.expr).__name__, "IdentifierNameSyntax")
            self.assertEqual(parent.expr.identifier.rawText, "WIDTH")
            self.assertEqual(
                (
                    parent_key.identifier.location.buffer,
                    int(parent_key.identifier.location.offset),
                    str(parent_key.identifier.rawText),
                ),
                (
                    key.identifier.location.buffer,
                    int(key.identifier.location.offset),
                    str(key.identifier.rawText),
                ),
            )
            key_range = (
                "pattern_key.sv",
                int(key.identifier.location.offset),
                int(key.identifier.location.offset) + len(b"mie"),
            )
            value_range = (
                "pattern_key.sv",
                int(value.identifier.location.offset),
                int(value.identifier.location.offset) + len(b"WIDTH"),
            )
            original_lookup = symbol_graph_module._scope_lookup_target
            lookup_tokens = []

            def observed_lookup(scope, token):
                lookup_tokens.append(
                    (
                        str(getattr(token, "rawText", "")),
                        int(getattr(token.location, "offset", -1)),
                    )
                )
                return original_lookup(scope, token)

            with mock.patch.object(
                symbol_graph_module,
                "_scope_lookup_target",
                side_effect=observed_lookup,
            ):
                graph = build_symbol_graph(catalog)
            self.assertNotIn(("mie", key_range[1]), lookup_tokens)
            self.assertIn(("WIDTH", value_range[1]), lookup_tokens)

            parameters = [
                symbol for symbol in graph.symbols
                if symbol.category == "parameters"
            ]
            parameter_ranges = [
                (
                    symbol.declaration.file,
                    symbol.declaration.start,
                    symbol.declaration.end,
                    "declaration",
                )
                for symbol in parameters
            ] + [
                (
                    occurrence.source_range.file,
                    occurrence.source_range.start,
                    occurrence.source_range.end,
                    occurrence.provenance,
                )
                for symbol in parameters
                for occurrence in symbol.occurrences
            ]
            self.assertFalse(any(item[:3] == key_range for item in parameter_ranges))
            value_occurrences = [
                item for item in parameter_ranges if item[:3] == value_range
            ]
            self.assertEqual(value_occurrences, [(*value_range, "semantic_expression")])

            policy = build_rewrite_policy(
                graph,
                categories=("parameters",),
                abi_categories=("parameters",),
            )
            mapping = build_mapping_vnext(
                policy,
                name_length=16,
                name_factory=_deterministic_factory,
            )
            execution = write_gate_vnext(mapping, output_dir=root / "gate")
            self.assertFalse(
                any(
                    (
                        edit.source_range.file,
                        edit.source_range.start,
                        edit.source_range.end,
                    ) == key_range
                    for edit in execution.edits
                )
            )
            self.assertEqual(source[key_range[1]:key_range[2]], b"mie")

    def test_non_key_initializer_lookup_failure_remains_fail_closed(self):
        with tempfile.TemporaryDirectory(prefix="t079-pattern-value-failure-") as temporary:
            root = Path(temporary)
            _source, _source_set, catalog, key, value = self._write_pattern_key_source(root)
            original_lookup = symbol_graph_module._scope_lookup_target

            def unresolved_value(scope, token):
                raw = str(getattr(token, "rawText", ""))
                if raw == "mie":
                    raise AssertionError("assignment-pattern key reached lexical lookup")
                if (
                    raw == "WIDTH"
                    and int(getattr(token.location, "offset", -1))
                    == int(value.identifier.location.offset)
                ):
                    raise SymbolGraphError(
                        "SYMBOL_GRAPH_UNSUPPORTED_REFERENCE",
                        "scope-bound identifier has no semantic target",
                    )
                return original_lookup(scope, token)

            with mock.patch.object(
                symbol_graph_module,
                "_scope_lookup_target",
                side_effect=unresolved_value,
            ), self.assertRaises(SymbolGraphError) as raised:
                build_symbol_graph(catalog)
            self.assertEqual(type(key.parent).__name__, "AssignmentPatternItemSyntax")
            self.assertEqual(raised.exception.code, "SYMBOL_GRAPH_UNSUPPORTED_REFERENCE")
            self.assertEqual(
                raised.exception.message,
                "scope-bound identifier has no semantic target",
            )


if __name__ == "__main__":
    unittest.main()
