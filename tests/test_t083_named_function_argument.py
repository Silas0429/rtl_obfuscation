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

from rtl_obfuscator import source_catalog as source_catalog_module
from rtl_obfuscator import symbol_graph as symbol_graph_module
from rtl_obfuscator.mapping_vnext import build_mapping_vnext
from rtl_obfuscator.rewrite_policy import build_rewrite_policy
from rtl_obfuscator.rewrite_vnext import RewriteVNextError, write_gate_vnext
from rtl_obfuscator.source_catalog import (
    SourceCatalogError,
    SourceRange,
    build_source_catalog,
)
from rtl_obfuscator.source_set import SourceSetError, from_filelist
from rtl_obfuscator.symbol_graph import (
    SourceSymbol,
    SymbolGraph,
    SymbolGraphError,
    build_symbol_graph,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "t083_named_function_argument"
FILELIST = FIXTURE_ROOT / "design.f"
PUBLIC_DEFINE = "T083_NAMED_ARGUMENT"
EXPECTED_FIXTURE = {
    "design.f": (
        10,
        "2bd824b8fab1c3ebc159191ce9f58bbaadd30a5ddbea38fa8a4fcfc4b94d1aea",
    ),
    "design.sv": (
        351,
        "64a6a7fa56e53a0e65da21530b0a367cd5929051b8de4198acd4f998d5063db0",
    ),
}


def _deterministic_factory(
    symbol_id: str, name_length: int, unavailable: frozenset[str]
) -> str:
    candidate = ("a" + hashlib.sha256(symbol_id.encode("utf-8")).hexdigest())[
        :name_length
    ]
    if candidate in unavailable:
        raise AssertionError("test factory collision")
    return candidate


class T083NamedFunctionArgumentTests(unittest.TestCase):
    @staticmethod
    def _source_set(
        root: Path = FIXTURE_ROOT,
        top: str = "t083_top",
        *,
        defines: tuple[str, ...] = (PUBLIC_DEFINE,),
    ):
        return from_filelist(
            filelist=root / "design.f",
            source_root=root,
            top=top,
            defines=defines,
        )

    @classmethod
    def _catalog_graph(cls):
        source_set = cls._source_set()
        catalog = build_source_catalog(source_set)
        return source_set, catalog, build_symbol_graph(catalog)

    @staticmethod
    def _mapping_for(graph):
        policy = build_rewrite_policy(
            graph,
            categories=("arguments",),
            abi_categories=(),
        )
        return build_mapping_vnext(
            policy,
            name_length=16,
            name_factory=_deterministic_factory,
        )

    @classmethod
    def _mapping(cls):
        _source_set, _catalog, graph = cls._catalog_graph()
        return cls._mapping_for(graph)

    @staticmethod
    def _argument(graph, name: str):
        return next(
            symbol
            for symbol in graph.symbols
            if symbol.category == "arguments" and symbol.name == name
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
            "t083_top",
            "--define",
            PUBLIC_DEFINE,
            "--category",
            "arguments",
            "--output-dir",
            str(gate),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        mapping_path = gate / "mapping.json"
        report = json.loads(mapping_path.read_text(encoding="utf-8"))
        self.assertEqual(json.loads(result.stdout)["summary"], report["summary"])
        return gate, mapping_path, report

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
            "t083_top",
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

    @classmethod
    def _temporary_source_set(
        cls,
        root: Path,
        source: bytes,
        top: str,
        *,
        defines: tuple[str, ...] = (),
    ):
        root.mkdir(parents=True, exist_ok=True)
        (root / "design.sv").write_bytes(source)
        (root / "design.f").write_bytes(b"design.sv\n")
        return cls._source_set(root, top, defines=defines)

    def test_fixture_typed_identity_and_exact_graph_occurrences(self):
        for file, (expected_size, expected_sha256) in EXPECTED_FIXTURE.items():
            source = (FIXTURE_ROOT / file).read_bytes()
            self.assertEqual(len(source), expected_size, file)
            self.assertEqual(
                hashlib.sha256(source).hexdigest(), expected_sha256, file
            )

        source_set = self._source_set()
        catalog = build_source_catalog(source_set)
        nodes = []
        catalog.catalog_root.visit(nodes.append)
        call = next(
            node
            for node in nodes
            if type(node).__name__ == "CallExpression"
            and str(getattr(getattr(node, "subroutine", None), "name", ""))
            == "choose"
        )
        self.assertEqual(type(call.syntax).__name__, "InvocationExpressionSyntax")
        self.assertEqual(
            type(call.subroutine.syntax).__name__,
            "FunctionDeclarationSyntax",
        )
        self.assertEqual(
            [
                (
                    type(formal).__name__,
                    str(formal.name),
                    int(formal.location.offset),
                )
                for formal in call.subroutine.arguments
            ],
            [
                ("FormalArgumentSymbol", "lhs", 112),
                ("FormalArgumentSymbol", "rhs", 129),
            ],
        )
        parameters = call.syntax.arguments.parameters
        self.assertIs(type(parameters), list)
        self.assertEqual(
            [type(parameter).__name__ for parameter in parameters],
            ["NamedArgumentSyntax", "Token", "NamedArgumentSyntax"],
        )
        self.assertEqual(
            [
                (
                    str(parameter.name.rawText),
                    int(parameter.name.location.offset),
                )
                for parameter in parameters
                if type(parameter).__name__ == "NamedArgumentSyntax"
            ],
            [("rhs", 266), ("lhs", 278)],
        )

        with mock.patch.object(
            source_catalog_module,
            "_compile_view",
            side_effect=AssertionError("T083 graph rebuilt semantic view"),
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
                "symbols": 7,
                "declarations": 7,
                "occurrences": 10,
                "total_ranges": 17,
            },
        )
        lhs = self._argument(graph, "lhs")
        rhs = self._argument(graph, "rhs")
        self.assertEqual(
            [
                (
                    occurrence.source_range.start,
                    occurrence.source_range.end,
                    occurrence.provenance,
                )
                for occurrence in lhs.occurrences
            ],
            [
                (148, 151, "semantic_reference"),
                (278, 281, "semantic_named_argument"),
            ],
        )
        self.assertEqual(
            [
                (
                    occurrence.source_range.start,
                    occurrence.source_range.end,
                    occurrence.provenance,
                )
                for occurrence in rhs.occurrences
            ],
            [
                (154, 157, "semantic_reference"),
                (266, 269, "semantic_named_argument"),
            ],
        )
        base = next(
            symbol
            for symbol in graph.symbols
            if symbol.category == "signals" and symbol.name == "base"
        )
        self.assertIn(
            (270, 274, "semantic_expression"),
            [
                (
                    occurrence.source_range.start,
                    occurrence.source_range.end,
                    occurrence.provenance,
                )
                for occurrence in base.occurrences
            ],
        )

    def test_pre_fix_missing_labels_fail_atomically(self):
        _source_set, _catalog, graph = self._catalog_graph()
        pre_fix_graph = SymbolGraph(
            schema_version=graph.schema_version,
            source_catalog=graph.source_catalog,
            symbols=tuple(
                replace(
                    symbol,
                    occurrences=tuple(
                        occurrence
                        for occurrence in symbol.occurrences
                        if occurrence.provenance != "semantic_named_argument"
                    ),
                )
                for symbol in graph.symbols
            ),
        )
        self.assertEqual(
            pre_fix_graph.to_report()["range_audit"],
            {
                "symbols": 7,
                "declarations": 7,
                "occurrences": 8,
                "total_ranges": 15,
            },
        )
        mapping = self._mapping_for(pre_fix_graph)
        self.assertEqual(
            mapping.to_report()["summary"],
            {"total": 7, "rename": 2, "preserve": 5, "unsupported": 0},
        )
        self.assertEqual(
            sum(
                1 + len(record.occurrences)
                for record in mapping.records
                if record.action == "rename"
            ),
            4,
        )
        with tempfile.TemporaryDirectory(prefix="t083-pre-fix-") as temporary:
            gate = Path(temporary) / "gate"
            with self.assertRaises(RewriteVNextError) as raised:
                write_gate_vnext(mapping, output_dir=gate)
            self.assertEqual(raised.exception.code, "REWRITE_GATE_COMPILE_FAILED")
            self.assertIn("CATALOG_SEMANTIC_FAILED", raised.exception.message)
            self.assertFalse(gate.exists())

    def test_mapping_and_execution_bind_labels_by_formal_identity(self):
        mapping = self._mapping()
        self.assertEqual(
            mapping.to_report()["summary"],
            {"total": 7, "rename": 2, "preserve": 5, "unsupported": 0},
        )
        self.assertEqual(
            sum(
                1 + len(record.occurrences)
                for record in mapping.records
                if record.action == "rename"
            ),
            6,
        )
        records = {
            record.original_name: record
            for record in mapping.records
            if record.category == "arguments"
        }
        with tempfile.TemporaryDirectory(prefix="t083-execution-") as temporary:
            execution = write_gate_vnext(
                mapping,
                output_dir=Path(temporary) / "gate",
            )
            self.assertEqual(len(execution.edits), 6)
            expected = {
                "lhs": {
                    (112, 115, "declaration"),
                    (148, 151, "semantic_reference"),
                    (278, 281, "semantic_named_argument"),
                },
                "rhs": {
                    (129, 132, "declaration"),
                    (154, 157, "semantic_reference"),
                    (266, 269, "semantic_named_argument"),
                },
            }
            for name, ranges in expected.items():
                record = records[name]
                edits = [
                    edit
                    for edit in execution.edits
                    if edit.symbol_id == record.symbol_id
                ]
                self.assertEqual(len(edits), 3)
                self.assertEqual(
                    {
                        (
                            edit.source_range.start,
                            edit.source_range.end,
                            edit.provenance,
                        )
                        for edit in edits
                    },
                    ranges,
                )
                self.assertEqual(
                    {edit.renamed_name for edit in edits},
                    {record.renamed_name},
                )

    def test_public_gate_strict_and_source_free_restore(self):
        with tempfile.TemporaryDirectory(prefix="t083-public-") as temporary:
            root = Path(temporary)
            gate, mapping_path, report = self._encrypt(root / "encrypt")
            self.assertEqual(
                (
                    report["summary"]["files"],
                    report["summary"]["mapping_records"],
                    report["summary"]["modified_tokens"],
                    report["summary"]["strict_compile_passed"],
                    report["summary"]["restored_byte_identical"],
                ),
                (1, 7, 6, True, True),
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
            for original in (
                b"input logic lhs",
                b"input logic rhs",
                b"choose = lhs ^ rhs;",
                b".rhs(base)",
                b".lhs(1'b0)",
            ):
                self.assertNotIn(original, gate_source)

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

    def test_actual_public_gate_formal_without_named_define(self):
        with tempfile.TemporaryDirectory(
            prefix="t083-formal-positive-"
        ) as temporary:
            gate, _mapping, report = self._encrypt(Path(temporary) / "encrypt")
            records = {
                record["original_name"]: record
                for record in report["mapping"]["records"]
                if record["category"] == "arguments"
            }
            gate_source = (gate / "design.sv").read_bytes()
            for name in ("lhs", "rhs"):
                renamed = records[name]["renamed_name"].encode("ascii")
                self.assertNotEqual(renamed, name.encode("ascii"))
                self.assertEqual(gate_source.count(renamed), 3)
            formal, command = self._formal(gate)
            print(f"T083_FORMAL_COMMAND {shlex.join(command)}")
            print(f"T083_FORMAL_EXIT {formal.returncode}")
            print(f"T083_FORMAL_JSON {formal.stdout.strip()}")
        self.assertEqual(formal.returncode, 0, formal.stderr)
        self.assertEqual(
            json.loads(formal.stdout),
            {
                "formal_equivalence": "pass",
                "gate": str(gate),
                "gold": str(FIXTURE_ROOT),
                "seq": 5,
                "top": "t083_top",
            },
        )

    def test_fixed_macro_outside_negative_strict_and_formal_failure(self):
        with tempfile.TemporaryDirectory(
            prefix="t083-formal-negative-"
        ) as temporary:
            root = Path(temporary)
            gate, _mapping, _report = self._encrypt(root / "encrypt")
            negative = root / "negative"
            shutil.copytree(gate, negative)
            design = negative / "design.sv"
            source = design.read_bytes()
            marker = b"assign base = data_i;"
            self.assertEqual(source.count(marker), 1)
            design.write_bytes(
                source.replace(marker, b"assign base = ~data_i;", 1)
            )
            negative_catalog = build_source_catalog(self._source_set(negative))
            self.assertEqual(
                negative_catalog.to_report()["compile"],
                {
                    "catalog": {"parse_errors": 0, "semantic_errors": 0},
                    "top_overlay": {"parse_errors": 0, "semantic_errors": 0},
                },
            )
            formal, command = self._formal(negative)
            print(f"T083_FORMAL_NEGATIVE_COMMAND {shlex.join(command)}")
            print(f"T083_FORMAL_NEGATIVE_EXIT {formal.returncode}")
        self.assertNotEqual(formal.returncode, 0)
        combined = formal.stdout + formal.stderr
        negative_summary = "\n".join(
            line
            for line in combined.splitlines()
            if "unproven" in line or "equiv_status -assert" in line
        )
        print(f"T083_FORMAL_NEGATIVE_OUTPUT {negative_summary}")
        self.assertIn("unproven", combined)
        self.assertIn("equiv_status -assert", combined)

    def test_ordered_task_method_and_system_calls_add_no_named_occurrence(self):
        ordered_graph = build_symbol_graph(
            build_source_catalog(self._source_set(defines=()))
        )
        self.assertFalse(
            any(
                occurrence.provenance == "semantic_named_argument"
                for symbol in ordered_graph.symbols
                for occurrence in symbol.occurrences
            )
        )

        source = b"""module t083_task_top (
  input logic data_i,
  output logic data_o
);
  task automatic pulse(input logic value);
  endtask
  always_comb begin
    pulse(.value(data_i));
    data_o = $unsigned(data_i);
  end
endmodule
"""
        with tempfile.TemporaryDirectory(prefix="t083-task-") as temporary:
            root = Path(temporary)
            graph = build_symbol_graph(
                build_source_catalog(
                    self._temporary_source_set(root, source, "t083_task_top")
                )
            )
            task_argument = self._argument(graph, "value")
            self.assertNotIn(
                "semantic_named_argument",
                [item.provenance for item in task_argument.occurrences],
            )
            self.assertFalse(
                any(
                    occurrence.provenance == "semantic_named_argument"
                    for symbol in graph.symbols
                    for occurrence in symbol.occurrences
                )
            )

        method_source = b"""class t083_helper;
  static function logic pick(input logic value);
    pick = value;
  endfunction
endclass
module t083_method_top (input logic data_i, output logic data_o);
  assign data_o = t083_helper::pick(.value(data_i));
endmodule
"""
        with tempfile.TemporaryDirectory(prefix="t083-method-") as temporary:
            root = Path(temporary)
            source_set = self._temporary_source_set(
                root, method_source, "t083_method_top"
            )
            try:
                method_graph = build_symbol_graph(
                    build_source_catalog(source_set)
                )
            except SourceCatalogError as error:
                self.assertEqual(error.code, "CATALOG_RANGE_INVALID")
            else:
                self.assertFalse(
                    any(
                        occurrence.provenance == "semantic_named_argument"
                        for symbol in method_graph.symbols
                        for occurrence in symbol.occurrences
                    )
                )

    def test_repeated_elaboration_deduplicates_and_macro_label_has_no_edit(self):
        repeated_source = b"""module t083_repeat_child (input logic data_i, output logic data_o);
  function automatic logic choose(input logic value);
    choose = value;
  endfunction
  assign data_o = choose(.value(data_i));
endmodule
module t083_repeat_top (input logic data_i, output logic data_o);
  logic a_o;
  logic b_o;
  t083_repeat_child u_a (.data_i(data_i), .data_o(a_o));
  t083_repeat_child u_b (.data_i(data_i), .data_o(b_o));
  assign data_o = a_o ^ b_o;
endmodule
"""
        with tempfile.TemporaryDirectory(prefix="t083-repeat-") as temporary:
            root = Path(temporary)
            source_set = self._temporary_source_set(
                root, repeated_source, "t083_repeat_top"
            )
            graph = build_symbol_graph(build_source_catalog(source_set))
            value = self._argument(graph, "value")
            labels = [
                item
                for item in value.occurrences
                if item.provenance == "semantic_named_argument"
            ]
            self.assertEqual(len(labels), 1)

        macro_source = b"""`define T083_CALL(FUNC, VALUE) FUNC(.value(VALUE))
module t083_macro (input logic data_i, output logic data_o);
  function automatic logic helper(input logic value);
    helper = value;
  endfunction
  assign data_o = `T083_CALL(helper, data_i);
endmodule
"""
        with tempfile.TemporaryDirectory(prefix="t083-macro-") as temporary:
            temporary_root = Path(temporary)
            source_root = temporary_root / "source"
            source_set = self._temporary_source_set(
                source_root, macro_source, "t083_macro"
            )
            graph = build_symbol_graph(build_source_catalog(source_set))
            value = self._argument(graph, "value")
            self.assertNotIn(
                "semantic_named_argument",
                [item.provenance for item in value.occurrences],
            )
            mapping = self._mapping_for(graph)
            record = next(
                record
                for record in mapping.records
                if record.symbol_id == value.symbol_id
            )
            self.assertEqual(record.action, "unsupported")
            execution = write_gate_vnext(
                mapping,
                output_dir=temporary_root / "gate",
            )
            self.assertFalse(
                any(edit.symbol_id == value.symbol_id for edit in execution.edits)
            )

    def test_mismatch_invalid_formal_and_range_conflicts_fail_closed(self):
        source_set = self._source_set()
        catalog = build_source_catalog(source_set)
        original_token_range = symbol_graph_module._token_source_range

        def mismatch(source_catalog, token, name):
            if int(getattr(getattr(token, "location", None), "offset", -1)) == 266:
                return original_token_range(
                    source_catalog,
                    token,
                    name + "_mismatch",
                )
            return original_token_range(source_catalog, token, name)

        with mock.patch.object(
            symbol_graph_module,
            "_token_source_range",
            side_effect=mismatch,
        ):
            with self.assertRaises(SymbolGraphError) as raised:
                build_symbol_graph(catalog)
        self.assertEqual(raised.exception.code, "SYMBOL_GRAPH_SOURCE_INVALID")

        invalid_sources = {
            "missing": b"""module t083_missing;
  function logic f(input logic value); f = value; endfunction
  logic x;
  assign x = f(.(1'b0));
endmodule
""",
            "no_match": b"""module t083_no_match;
  function logic f(input logic value); f = value; endfunction
  logic x;
  assign x = f(.bogus(1'b0));
endmodule
""",
        }
        for name, source in invalid_sources.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory(
                prefix=f"t083-{name}-"
            ) as temporary:
                root = Path(temporary)
                root.mkdir(parents=True, exist_ok=True)
                (root / "design.sv").write_bytes(source)
                (root / "design.f").write_bytes(b"design.sv\n")
                with self.assertRaises(SourceSetError) as invalid:
                    self._source_set(root, f"t083_{name}", defines=())
                self.assertEqual(
                    invalid.exception.code,
                    "SOURCESET_DISCOVERY_FAILED",
                )

        duplicate_source = b"""module t083_duplicate_formal;
  function logic f(input logic value, input logic value); f = value; endfunction
  logic x;
  assign x = f(.value(1'b0));
endmodule
"""
        with tempfile.TemporaryDirectory(
            prefix="t083-duplicate-formal-"
        ) as temporary:
            root = Path(temporary)
            duplicate_catalog = build_source_catalog(
                self._temporary_source_set(
                    root,
                    duplicate_source,
                    "t083_duplicate_formal",
                )
            )
            with self.assertRaises(SymbolGraphError) as duplicate:
                build_symbol_graph(duplicate_catalog)
            self.assertEqual(
                duplicate.exception.code,
                "SYMBOL_GRAPH_OWNER_MISMATCH",
            )

        occupied_ranges = (
            SourceSymbol(
                symbol_id="symbol:test:occupied-label",
                category="signals",
                name="rhs",
                declaration=SourceRange("design.sv", 266, 269),
                owner_module="module:test",
                semantic_owner="module:test",
                occurrences=(),
                impact="local",
                abi="internal",
                support="eligible",
                reason=None,
            ),
            SourceSymbol(
                symbol_id="symbol:test:partial-label",
                category="signals",
                name="rhs",
                declaration=SourceRange("design.sv", 266, 268),
                owner_module="module:test",
                semantic_owner="module:test",
                occurrences=(),
                impact="local",
                abi="internal",
                support="eligible",
                reason=None,
            ),
            SourceSymbol(
                symbol_id="symbol:test:wrong-formal-owner",
                category="signals",
                name="lhs",
                declaration=SourceRange("design.sv", 112, 115),
                owner_module="module:other",
                semantic_owner="module:other",
                occurrences=(),
                impact="local",
                abi="internal",
                support="eligible",
                reason=None,
            ),
        )
        for occupied in occupied_ranges:
            with self.subTest(symbol_id=occupied.symbol_id):
                with self.assertRaises(SymbolGraphError) as raised:
                    symbol_graph_module._collect_extended_symbols(
                        catalog,
                        [occupied],
                    )
                self.assertEqual(
                    raised.exception.code,
                    "SYMBOL_GRAPH_RANGE_CONFLICT",
                )


if __name__ == "__main__":
    unittest.main()
