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
from rtl_obfuscator.rewrite_vnext import RewriteVNextError, write_gate_vnext
from rtl_obfuscator.source_catalog import build_source_catalog
from rtl_obfuscator.source_set import from_filelist
from rtl_obfuscator.symbol_graph import SymbolGraphError, build_symbol_graph


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "t080_expression_sized_cast"
FILELIST = FIXTURE_ROOT / "design.f"
EXPECTED_FIXTURE = {
    "design.f": (
        10,
        "2bd824b8fab1c3ebc159191ce9f58bbaadd30a5ddbea38fa8a4fcfc4b94d1aea",
    ),
    "design.sv": (
        199,
        "0e5bd165bc458e231220e6f1e6bce0f031a604ff59cf2eb11cfc19fea9204cb0",
    ),
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


class T080ExpressionSizedCastParameterTests(unittest.TestCase):
    @staticmethod
    def _source_set(
        root: Path = FIXTURE_ROOT,
        top: str = "t080_expression_sized_cast",
    ):
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

    @classmethod
    def _mapping(cls):
        _source_set, _catalog, graph = cls._catalog_graph()
        policy = build_rewrite_policy(
            graph,
            categories=("parameters",),
            abi_categories=("parameters",),
        )
        return build_mapping_vnext(
            policy,
            name_length=16,
            name_factory=_deterministic_factory,
        )

    @staticmethod
    def _parameter(graph, file: str, start: int):
        return next(
            symbol
            for symbol in graph.symbols
            if symbol.category == "parameters"
            and symbol.declaration.file == file
            and symbol.declaration.start == start
        )

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
            str(FIXTURE_ROOT / "design.f"),
            "--top",
            "t080_expression_sized_cast",
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
            "t080_expression_sized_cast",
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
    def _temporary_graph(root: Path, source: bytes, top: str):
        (root / "design.sv").write_bytes(source)
        (root / "design.f").write_bytes(b"design.sv\n")
        source_set = T080ExpressionSizedCastParameterTests._source_set(root, top)
        catalog = build_source_catalog(source_set)
        return source_set, catalog, build_symbol_graph(catalog)

    @staticmethod
    def _mapping_for(graph):
        policy = build_rewrite_policy(
            graph,
            categories=("parameters",),
            abi_categories=("parameters",),
        )
        return build_mapping_vnext(
            policy,
            name_length=16,
            name_factory=_deterministic_factory,
        )

    def test_fixture_typed_path_graph_and_exact_occurrences(self):
        for file, (expected_size, expected_sha256) in EXPECTED_FIXTURE.items():
            source = (FIXTURE_ROOT / file).read_bytes()
            self.assertEqual(len(source), expected_size, file)
            self.assertEqual(hashlib.sha256(source).hexdigest(), expected_sha256, file)

        source_set = self._source_set()
        catalog = build_source_catalog(source_set)
        nodes = []
        catalog.catalog_root.visit(nodes.append)
        conversions = [
            node
            for node in nodes
            if type(node).__name__ == "ConversionExpression"
            and type(getattr(node, "syntax", None)).__name__
            == "CastExpressionSyntax"
        ]
        self.assertEqual(len(conversions), 1)
        conversion = conversions[0]
        cast = conversion.syntax
        invocation = cast.left
        self.assertEqual(type(invocation).__name__, "InvocationExpressionSyntax")
        self.assertEqual(type(invocation.left).__name__, "SystemNameSyntax")
        self.assertEqual(invocation.left.systemIdentifier.rawText, "$clog2")
        self.assertEqual(type(invocation.arguments).__name__, "ArgumentListSyntax")
        self.assertEqual(type(invocation.arguments.parameters).__name__, "list")
        self.assertEqual(len(invocation.arguments.parameters), 1)
        argument = invocation.arguments.parameters[0]
        self.assertEqual(type(argument).__name__, "OrderedArgumentSyntax")
        self.assertEqual(type(argument.expr).__name__, "SimplePropertyExprSyntax")
        sequence = argument.expr.expr
        self.assertEqual(type(sequence).__name__, "SimpleSequenceExprSyntax")
        self.assertIsNone(sequence.repetition)
        identifier = sequence.expr
        self.assertEqual(type(identifier).__name__, "IdentifierNameSyntax")
        self.assertEqual(
            (
                str(identifier.identifier.rawText),
                int(identifier.identifier.location.offset),
            ),
            ("RomSize", 169),
        )
        self.assertEqual(type(cast.right).__name__, "ParenthesizedExpressionSyntax")
        self.assertEqual(type(conversion.operand).__name__, "NamedValueExpression")
        self.assertEqual(conversion.operand.symbol.name, "RomSize")
        self.assertEqual(int(conversion.operand.symbol.location.offset), 121)
        self.assertIsNone(conversion.getSymbolReference())

        with mock.patch.object(
            source_catalog_module,
            "_compile_view",
            side_effect=AssertionError("T080 graph rebuilt semantic view"),
        ):
            graph = build_symbol_graph(catalog)
        self.assertIs(graph.source_catalog, catalog)
        self.assertEqual(
            catalog.to_report()["compile"],
            {
                "catalog": {"parse_errors": 0, "semantic_errors": 0},
                "top_overlay": {"parse_errors": 0, "semantic_errors": 0},
            },
        )
        self.assertEqual(
            graph.to_report()["range_audit"],
            {
                "symbols": 4,
                "declarations": 4,
                "occurrences": 4,
                "total_ranges": 8,
            },
        )
        rom_size = self._parameter(graph, "design.sv", 121)
        self.assertEqual(
            [
                (
                    occurrence.source_range.file,
                    occurrence.source_range.start,
                    occurrence.source_range.end,
                    occurrence.provenance,
                )
                for occurrence in rom_size.occurrences
            ],
            [
                ("design.sv", 169, 176, "expression_sized_cast_type"),
                ("design.sv", 179, 186, "semantic_expression"),
            ],
        )

    def test_mapping_has_exact_cast_edit_identity_and_frozen_summary(self):
        mapping = self._mapping()
        self.assertEqual(
            mapping.to_report()["summary"],
            {"total": 4, "rename": 1, "preserve": 3, "unsupported": 0},
        )
        self.assertEqual(
            mapping.to_report()["range_audit"],
            {"declarations": 4, "occurrences": 4, "total_ranges": 8},
        )
        self.assertEqual(
            sum(
                1 + len(record.occurrences)
                for record in mapping.records
                if record.action == "rename"
            ),
            3,
        )
        record = next(
            record
            for record in mapping.records
            if record.category == "parameters"
            and record.declaration.file == "design.sv"
            and record.declaration.start == 121
        )
        self.assertEqual(record.action, "rename")
        expression_casts = [
            occurrence
            for occurrence in record.occurrences
            if occurrence.provenance == "expression_sized_cast_type"
        ]
        self.assertEqual(len(expression_casts), 1)
        self.assertEqual(
            (
                expression_casts[0].source_range.file,
                expression_casts[0].source_range.start,
                expression_casts[0].source_range.end,
            ),
            ("design.sv", 169, 176),
        )

    def test_public_gate_strict_and_source_free_restore(self):
        with tempfile.TemporaryDirectory(prefix="t080-public-") as temporary:
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
                (1, 4, 3, True, True),
            )
            records = report["mapping"]["records"]
            rom_size = next(
                record
                for record in records
                if record["category"] == "parameters"
                and record["declaration"]
                == {"file": "design.sv", "start": 121, "end": 128}
            )
            self.assertEqual(
                [
                    occurrence
                    for occurrence in rom_size["occurrences"]
                    if occurrence["provenance"]
                    == "expression_sized_cast_type"
                ],
                [
                    {
                        "source_range": {
                            "file": "design.sv",
                            "start": 169,
                            "end": 176,
                        },
                        "provenance": "expression_sized_cast_type",
                    }
                ],
            )
            gate_catalog = build_source_catalog(self._source_set(gate))
            self.assertEqual(
                gate_catalog.to_report()["compile"],
                {
                    "catalog": {"parse_errors": 0, "semantic_errors": 0},
                    "top_overlay": {"parse_errors": 0, "semantic_errors": 0},
                },
            )
            gate_source = (gate / "design.sv").read_bytes()
            self.assertNotIn(b"RomSize", gate_source)
            self.assertEqual(
                gate_source.count(rom_size["renamed_name"].encode("ascii")),
                3,
            )

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
                {
                    path.relative_to(restore).as_posix()
                    for path in restore.rglob("*")
                    if path.is_file()
                },
                {"design.sv"},
            )
            self.assertEqual(
                (restore / "design.sv").read_bytes(),
                (FIXTURE_ROOT / "design.sv").read_bytes(),
            )
            self.assertFalse((restore / "design.f").exists())

    def test_actual_public_renamed_gate_formal_positive(self):
        with tempfile.TemporaryDirectory(
            prefix="t080-formal-positive-"
        ) as temporary:
            gate, _mapping, _report = self._encrypt(Path(temporary) / "encrypt")
            formal, command = self._formal(gate)
            print(f"T080_FORMAL_COMMAND {shlex.join(command)}")
            print(f"T080_FORMAL_EXIT {formal.returncode}")
            print(f"T080_FORMAL_JSON {formal.stdout.strip()}")
        self.assertEqual(formal.returncode, 0, formal.stderr)
        payload = json.loads(formal.stdout)
        self.assertEqual(
            payload,
            {
                "formal_equivalence": "pass",
                "gate": str(gate),
                "gold": str(FIXTURE_ROOT),
                "seq": 5,
                "top": "t080_expression_sized_cast",
            },
        )

    def test_fixed_tilde_negative_strict_and_formal_failure(self):
        with tempfile.TemporaryDirectory(
            prefix="t080-formal-negative-"
        ) as temporary:
            root = Path(temporary)
            gate, _mapping, _report = self._encrypt(root / "encrypt")
            negative = root / "negative"
            shutil.copytree(gate, negative)
            design = negative / "design.sv"
            source = design.read_bytes()
            marker = b"assign hit_o = "
            self.assertEqual(source.count(marker), 1)
            design.write_bytes(source.replace(marker, b"assign hit_o = ~", 1))
            negative_catalog = build_source_catalog(self._source_set(negative))
            self.assertEqual(
                negative_catalog.to_report()["compile"],
                {
                    "catalog": {"parse_errors": 0, "semantic_errors": 0},
                    "top_overlay": {"parse_errors": 0, "semantic_errors": 0},
                },
            )
            formal, command = self._formal(negative)
            print(f"T080_FORMAL_NEGATIVE_COMMAND {shlex.join(command)}")
            print(f"T080_FORMAL_NEGATIVE_EXIT {formal.returncode}")
            print(f"T080_FORMAL_NEGATIVE_STDOUT {formal.stdout.strip()}")
        self.assertNotEqual(formal.returncode, 0)
        combined = formal.stdout + formal.stderr
        self.assertIn("unproven", combined)
        self.assertIn("equiv_status -assert", combined)

    def test_no_go_system_function_and_compound_argument_fail_atomically(self):
        cases = (
            (
                "t080_no_go_bits",
                b"$bits(P)'(P)",
            ),
            (
                "t080_no_go_compound",
                b"$clog2(P + 1)'(P)",
            ),
        )
        for top, cast in cases:
            with self.subTest(top=top), tempfile.TemporaryDirectory(
                prefix=f"{top}-"
            ) as temporary:
                root = Path(temporary)
                source_root = root / "source"
                source_root.mkdir()
                source = (
                    f"module {top} (input logic [5:0] data_i, output logic hit_o);\n"
                    "  localparam int P = 20;\n"
                    f"  assign hit_o = data_i < {cast.decode('ascii')};\n"
                    "endmodule\n"
                ).encode("ascii")
                _source_set, catalog, graph = self._temporary_graph(
                    source_root, source, top
                )
                self.assertEqual(
                    [
                        occurrence
                        for symbol in graph.symbols
                        if symbol.category == "parameters"
                        for occurrence in symbol.occurrences
                        if occurrence.provenance
                        == "expression_sized_cast_type"
                    ],
                    [],
                )
                self.assertEqual(
                    catalog.to_report()["compile"],
                    {
                        "catalog": {"parse_errors": 0, "semantic_errors": 0},
                        "top_overlay": {"parse_errors": 0, "semantic_errors": 0},
                    },
                )
                mapping = self._mapping_for(graph)
                gate = root / "gate"
                with self.assertRaises(RewriteVNextError) as raised:
                    write_gate_vnext(mapping, output_dir=gate)
                self.assertEqual(
                    raised.exception.code,
                    "REWRITE_GATE_COMPILE_FAILED",
                )
                self.assertFalse(gate.exists())

    def test_shadowed_fixed_casts_bind_distinct_parameter_declarations(self):
        with tempfile.TemporaryDirectory(prefix="t080-shadow-") as temporary:
            root = Path(temporary)
            source = b"""module t080_shadow #(
  parameter int P = 8
) (
  input  logic [5:0] data_i,
  output logic [5:0] data_o
);
  logic [5:0] inner_o;
  if (1) begin : g
    localparam int P = 4;
    always_comb begin
      inner_o = $clog2(P)'(data_i);
    end
  end
  assign data_o = inner_o ^ $clog2(P)'(data_i);
endmodule
"""
            _source_set, _catalog, graph = self._temporary_graph(
                root, source, "t080_shadow"
            )
            outer_declaration = source.index(b"P = 8")
            inner_declaration = source.index(b"P = 4")
            inner_cast = source.index(b"$clog2(P)") + len(b"$clog2(")
            outer_cast = source.rindex(b"$clog2(P)") + len(b"$clog2(")
            outer = self._parameter(graph, "design.sv", outer_declaration)
            inner = self._parameter(graph, "design.sv", inner_declaration)
            self.assertEqual(
                {
                    occurrence.source_range.start
                    for occurrence in outer.occurrences
                    if occurrence.provenance
                    == "expression_sized_cast_type"
                },
                {outer_cast},
            )
            self.assertEqual(
                {
                    occurrence.source_range.start
                    for occurrence in inner.occurrences
                    if occurrence.provenance
                    == "expression_sized_cast_type"
                },
                {inner_cast},
            )

    def test_overridden_parameter_default_uses_exact_fixed_path_and_provenance(self):
        with tempfile.TemporaryDirectory(
            prefix="t080-default-fixed-path-"
        ) as temporary:
            root = Path(temporary)
            source = b"""module t080_default_child #(
  parameter int P = 8,
  parameter int Q = $clog2(P)'(P)
) (output logic [5:0] data_o);
  assign data_o = Q;
endmodule
module t080_default_top(output logic [5:0] data_o);
  t080_default_child #(.Q(3)) u_child(.data_o(data_o));
endmodule
"""
            _source_set, _catalog, graph = self._temporary_graph(
                root, source, "t080_default_top"
            )
            declaration = source.index(b"P = 8")
            cast_left = source.index(b"$clog2(P)") + len(b"$clog2(")
            cast_right = source.index(b"'(P)") + len(b"'(")
            parameter = self._parameter(graph, "design.sv", declaration)
            matching = [
                (
                    occurrence.source_range.start,
                    occurrence.source_range.end,
                    occurrence.provenance,
                )
                for occurrence in parameter.occurrences
                if occurrence.source_range.start in {cast_left, cast_right}
            ]
            self.assertEqual(
                matching,
                [
                    (
                        cast_left,
                        cast_left + 1,
                        "expression_sized_cast_type",
                    ),
                    (cast_right, cast_right + 1, "parameter_default"),
                ],
            )

    def test_macro_fixed_path_adds_no_occurrence_or_parameter_edit(self):
        with tempfile.TemporaryDirectory(prefix="t080-macro-") as temporary:
            root = Path(temporary)
            source_root = root / "source"
            source_root.mkdir()
            source = b"""`define T080_EXPR_CAST(P) $clog2(P)'(P)
module t080_macro #(
  parameter int P = 8
) (
  output logic [5:0] data_o
);
  assign data_o = `T080_EXPR_CAST(P);
endmodule
"""
            _source_set, _catalog, graph = self._temporary_graph(
                source_root, source, "t080_macro"
            )
            self.assertFalse(
                any(
                    occurrence.provenance == "expression_sized_cast_type"
                    for symbol in graph.symbols
                    for occurrence in symbol.occurrences
                )
            )
            mapping = self._mapping_for(graph)
            parameter = next(
                record
                for record in mapping.records
                if record.category == "parameters"
                and record.original_name == "P"
            )
            self.assertNotEqual(parameter.action, "rename")
            self.assertFalse(
                any(
                    edit.symbol_id == parameter.symbol_id
                    for edit in write_gate_vnext(
                        mapping, output_dir=root / "gate"
                    ).edits
                )
            )

    def test_other_target_same_range_remains_atomic_conflict(self):
        with tempfile.TemporaryDirectory(prefix="t080-range-conflict-") as temporary:
            root = Path(temporary)
            source = b"""module t080_conflict_child #(
  parameter int P = 8,
  parameter int Q = 4
) (output logic hit_o);
  assign hit_o = $clog2(P)'(P);
endmodule
module t080_conflict_top(output logic hit_o);
  logic first_o;
  logic second_o;
  t080_conflict_child first(.hit_o(first_o));
  t080_conflict_child second(.hit_o(second_o));
  assign hit_o = first_o ^ second_o;
endmodule
"""
            (root / "design.sv").write_bytes(source)
            (root / "design.f").write_bytes(b"design.sv\n")
            catalog = build_source_catalog(
                self._source_set(root, "t080_conflict_top")
            )
            nodes = []
            catalog.catalog_root.visit(nodes.append)
            p_start = source.index(b"P = 8")
            q_start = source.index(b"Q = 4")
            token_start = source.index(b"$clog2(P)") + len(b"$clog2(")
            p_target = next(
                node
                for node in nodes
                if getattr(node, "kind", None) == pyslang.ast.SymbolKind.Parameter
                and str(getattr(node, "name", "")) == "P"
                and int(node.location.offset) == p_start
            )
            q_target = next(
                node
                for node in nodes
                if getattr(node, "kind", None) == pyslang.ast.SymbolKind.Parameter
                and str(getattr(node, "name", "")) == "Q"
                and int(node.location.offset) == q_start
            )
            original = symbol_graph_module._sized_cast_target_from_scopes
            hits = 0

            def conflicting_target(source_catalog, semantic_nodes, token):
                nonlocal hits
                if int(getattr(token.location, "offset", -1)) == token_start:
                    hits += 1
                    return p_target if hits == 1 else q_target
                return original(source_catalog, semantic_nodes, token)

            with mock.patch.object(
                symbol_graph_module,
                "_sized_cast_target_from_scopes",
                side_effect=conflicting_target,
            ), self.assertRaises(SymbolGraphError) as raised:
                build_symbol_graph(catalog)
            self.assertGreaterEqual(hits, 2)
            self.assertEqual(raised.exception.code, "SYMBOL_GRAPH_RANGE_CONFLICT")
            self.assertEqual(
                (raised.exception.file, raised.exception.start),
                ("design.sv", token_start),
            )


if __name__ == "__main__":
    unittest.main()
