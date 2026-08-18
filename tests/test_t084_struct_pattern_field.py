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
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "t084_struct_pattern_field"
FILELIST = FIXTURE_ROOT / "design.f"
PUBLIC_DEFINE = "T084_NAMED_PATTERN"
EXPECTED_FIXTURE = {
    "design.f": (
        10,
        "2bd824b8fab1c3ebc159191ce9f58bbaadd30a5ddbea38fa8a4fcfc4b94d1aea",
    ),
    "design.sv": (
        323,
        "9ea0f0f0b107aa9fdaeff67c537bc1c015aef3e885d7b72403a826e4334290a9",
    ),
}


def _deterministic_factory(
    symbol_id: str, name_length: int, unavailable: frozenset[str]
) -> str:
    candidate = ("s" + hashlib.sha256(symbol_id.encode("utf-8")).hexdigest())[
        :name_length
    ]
    if candidate in unavailable:
        raise AssertionError("test factory collision")
    return candidate


class T084StructPatternFieldTests(unittest.TestCase):
    @staticmethod
    def _source_set(
        root: Path = FIXTURE_ROOT,
        top: str = "t084_top",
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
            categories=("struct_fields",),
            abi_categories=("struct_fields",),
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
    def _field(graph, name: str):
        return next(
            symbol
            for symbol in graph.symbols
            if symbol.category == "struct_fields" and symbol.name == name
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
            "t084_top",
            "--define",
            PUBLIC_DEFINE,
            "--category",
            "struct_fields",
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
            "t084_top",
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
        pattern = next(
            node
            for node in nodes
            if type(node).__name__ == "StructuredAssignmentPatternExpression"
        )
        self.assertEqual(type(pattern.syntax).__name__, "AssignmentPatternExpressionSyntax")
        self.assertEqual(
            type(pattern.syntax.pattern).__name__,
            "StructuredAssignmentPatternSyntax",
        )
        self.assertEqual(type(pattern.type).__name__, "TypeAliasType")
        self.assertEqual(str(pattern.type.name), "pair_t")
        self.assertEqual(type(pattern.type.canonicalType).__name__, "PackedStructType")
        self.assertTrue(pattern.type.canonicalType.isStruct)
        self.assertFalse(pattern.type.canonicalType.isPackedUnion)
        self.assertEqual(int(pattern.type.location.offset), 126)
        self.assertEqual(
            [type(item).__name__ for item in pattern.syntax.pattern.items],
            ["AssignmentPatternItemSyntax", "Token", "AssignmentPatternItemSyntax"],
        )
        self.assertEqual(
            [
                (
                    str(item.key.identifier.rawText),
                    int(item.key.identifier.location.offset),
                )
                for item in pattern.syntax.pattern.items
                if type(item).__name__ == "AssignmentPatternItemSyntax"
            ],
            [("rhs", 199), ("lhs", 212)],
        )

        with mock.patch.object(
            source_catalog_module,
            "_compile_view",
            side_effect=AssertionError("T084 graph rebuilt semantic view"),
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
        expected = {
            "lhs": (
                (102, 105),
                [
                    (212, 215, "semantic_struct_pattern_key"),
                    (297, 300, "semantic_member"),
                ],
            ),
            "rhs": (
                (117, 120),
                [
                    (199, 202, "semantic_struct_pattern_key"),
                    (308, 311, "semantic_member"),
                ],
            ),
        }
        for name, (declaration, occurrences) in expected.items():
            field = self._field(graph, name)
            self.assertEqual(
                (field.declaration.start, field.declaration.end), declaration
            )
            self.assertEqual(field.semantic_owner, "type:design.sv:126:132")
            self.assertEqual(
                [
                    (
                        item.source_range.start,
                        item.source_range.end,
                        item.provenance,
                    )
                    for item in field.occurrences
                ],
                occurrences,
            )

    def test_pre_fix_missing_keys_fail_atomically(self):
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
                        if occurrence.provenance != "semantic_struct_pattern_key"
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
        with tempfile.TemporaryDirectory(prefix="t084-pre-fix-") as temporary:
            gate = Path(temporary) / "gate"
            with self.assertRaises(RewriteVNextError) as raised:
                write_gate_vnext(mapping, output_dir=gate)
            self.assertEqual(raised.exception.code, "REWRITE_GATE_COMPILE_FAILED")
            self.assertIn("CATALOG_SEMANTIC_FAILED", raised.exception.message)
            self.assertFalse(gate.exists())

    def test_mapping_and_execution_bind_keys_by_alias_owner_and_name(self):
        mapping = self._mapping()
        self.assertEqual(
            mapping.to_report()["summary"],
            {"total": 7, "rename": 2, "preserve": 5, "unsupported": 0},
        )
        records = {
            record.original_name: record
            for record in mapping.records
            if record.category == "struct_fields"
        }
        with tempfile.TemporaryDirectory(prefix="t084-execution-") as temporary:
            execution = write_gate_vnext(
                mapping,
                output_dir=Path(temporary) / "gate",
            )
            self.assertEqual(len(execution.edits), 6)
            expected = {
                "lhs": {
                    (102, 105, "declaration"),
                    (212, 215, "semantic_struct_pattern_key"),
                    (297, 300, "semantic_member"),
                },
                "rhs": {
                    (117, 120, "declaration"),
                    (199, 202, "semantic_struct_pattern_key"),
                    (308, 311, "semantic_member"),
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

    def test_t079_key_skip_and_value_expression_behavior_are_unchanged(self):
        catalog = build_source_catalog(self._source_set())
        with mock.patch.object(
            symbol_graph_module,
            "_scope_lookup_target",
            side_effect=AssertionError("T084 key used lexical parameter lookup"),
        ):
            graph = build_symbol_graph(catalog)
        data_i = next(
            symbol
            for symbol in graph.symbols
            if symbol.category == "ports" and symbol.name == "data_i"
        )
        self.assertIn(
            (204, 210, "semantic_reference"),
            [
                (
                    item.source_range.start,
                    item.source_range.end,
                    item.provenance,
                )
                for item in data_i.occurrences
            ],
        )

    def test_repeated_elaboration_deduplicates_and_same_names_keep_alias_owners(self):
        repeated_source = b"""module t084_repeat_top (input logic data_i, output logic data_o);
  typedef struct packed { logic lhs; logic rhs; } pair_t;
  pair_t pair [0:1];
  for (genvar i = 0; i < 2; i++) begin : g_pair
    always_comb pair[i] = '{rhs: data_i, lhs: 1'b0};
  end
  assign data_o = pair[0].lhs ^ pair[1].rhs;
endmodule
"""
        with tempfile.TemporaryDirectory(prefix="t084-repeat-") as temporary:
            root = Path(temporary)
            graph = build_symbol_graph(
                build_source_catalog(
                    self._temporary_source_set(
                        root, repeated_source, "t084_repeat_top"
                    )
                )
            )
            fields = [
                symbol
                for symbol in graph.symbols
                if symbol.category == "struct_fields"
            ]
            self.assertEqual({field.name for field in fields}, {"lhs", "rhs"})
            for field in fields:
                keys = [
                    item
                    for item in field.occurrences
                    if item.provenance == "semantic_struct_pattern_key"
                ]
                self.assertEqual(len(keys), 1)

        owner_source = b"""module t084_owner_top (input logic data_i, output logic data_o);
  typedef struct packed { logic value; } first_t;
  typedef struct packed { logic value; } second_t;
  first_t first;
  second_t second;
  always_comb first = '{value: data_i};
  always_comb second = '{value: ~data_i};
  assign data_o = first.value ^ second.value;
endmodule
"""
        with tempfile.TemporaryDirectory(prefix="t084-owner-") as temporary:
            root = Path(temporary)
            graph = build_symbol_graph(
                build_source_catalog(
                    self._temporary_source_set(
                        root, owner_source, "t084_owner_top"
                    )
                )
            )
            fields = [
                symbol
                for symbol in graph.symbols
                if symbol.category == "struct_fields" and symbol.name == "value"
            ]
            self.assertEqual(len(fields), 2)
            self.assertEqual(len({field.semantic_owner for field in fields}), 2)
            self.assertEqual(
                [
                    len(
                        [
                            item
                            for item in field.occurrences
                            if item.provenance == "semantic_struct_pattern_key"
                        ]
                    )
                    for field in fields
                ],
                [1, 1],
            )

    def test_union_array_scalar_positional_default_literal_and_type_are_no_go(self):
        sources = {
            "t084_union_top": b"""module t084_union_top (input logic data_i, output logic data_o);
  typedef union packed { logic lhs; logic rhs; } pair_u;
  pair_u pair;
  always_comb pair = '{lhs: data_i};
  assign data_o = pair.lhs;
endmodule
""",
            "t084_array_top": b"""module t084_array_top (input logic data_i, output logic data_o);
  logic pair [0:1];
  always_comb pair = '{0: data_i, default: 1'b0};
  assign data_o = pair[0];
endmodule
""",
            "t084_positional_top": b"""module t084_positional_top (input logic data_i, output logic data_o);
  typedef struct packed { logic lhs; logic rhs; } pair_t;
  pair_t pair;
  always_comb pair = '{data_i, 1'b0};
  assign data_o = pair.lhs ^ pair.rhs;
endmodule
""",
            "t084_default_top": b"""module t084_default_top (input logic data_i, output logic data_o);
  typedef struct packed { logic lhs; logic rhs; } pair_t;
  pair_t pair;
  always_comb pair = '{default: data_i};
  assign data_o = pair.lhs ^ pair.rhs;
endmodule
""",
            "t084_type_top": b"""module t084_type_top (input logic data_i, output logic data_o);
  typedef struct packed { logic lhs; logic rhs; } pair_t;
  pair_t pair;
  always_comb pair = '{logic: data_i};
  assign data_o = pair.lhs ^ pair.rhs;
endmodule
""",
            "t084_scalar_top": b"""module t084_scalar_top (input logic data_i, output logic data_o);
  logic value;
  always_comb value = '{data_i};
  assign data_o = value;
endmodule
""",
        }
        discovery_no_go = {"t084_union_top", "t084_scalar_top"}
        for top, source in sources.items():
            with self.subTest(top=top), tempfile.TemporaryDirectory(
                prefix=f"{top}-"
            ) as temporary:
                root = Path(temporary)
                if top in discovery_no_go:
                    with self.assertRaises(SourceSetError) as raised:
                        self._temporary_source_set(root, source, top)
                    self.assertEqual(
                        raised.exception.code, "SOURCESET_DISCOVERY_FAILED"
                    )
                    continue
                graph = build_symbol_graph(
                    build_source_catalog(
                        self._temporary_source_set(root, source, top)
                    )
                )
                self.assertFalse(
                    any(
                        item.provenance == "semantic_struct_pattern_key"
                        for symbol in graph.symbols
                        for item in symbol.occurrences
                    )
                )

    def test_macro_key_has_no_physical_occurrence_or_edit(self):
        source = b"""`define T084_FIELD lhs
module t084_macro_top (input logic data_i, output logic data_o);
  typedef struct packed { logic lhs; logic rhs; } pair_t;
  pair_t pair;
  always_comb pair = '{`T084_FIELD: data_i, rhs: 1'b0};
  assign data_o = pair.lhs ^ pair.rhs;
endmodule
"""
        with tempfile.TemporaryDirectory(prefix="t084-macro-") as temporary:
            root = Path(temporary)
            source_root = root / "source"
            graph = build_symbol_graph(
                build_source_catalog(
                    self._temporary_source_set(
                        source_root, source, "t084_macro_top"
                    )
                )
            )
            lhs = self._field(graph, "lhs")
            self.assertNotIn(
                "semantic_struct_pattern_key",
                [item.provenance for item in lhs.occurrences],
            )
            mapping = self._mapping_for(graph)
            lhs_record = next(
                record
                for record in mapping.records
                if record.symbol_id == lhs.symbol_id
            )
            if lhs_record.action == "unsupported":
                execution = write_gate_vnext(
                    mapping,
                    output_dir=root / "gate",
                )
                self.assertFalse(
                    any(
                        edit.symbol_id == lhs.symbol_id
                        for edit in execution.edits
                    )
                )
            else:
                with self.assertRaises(RewriteVNextError):
                    write_gate_vnext(mapping, output_dir=root / "gate")
                self.assertFalse((root / "gate").exists())

    def test_mismatch_alias_no_field_and_range_conflicts_fail_closed(self):
        source_set = self._source_set()
        catalog = build_source_catalog(source_set)
        original_token_range = symbol_graph_module._token_source_range

        def mismatch(source_catalog, token, name):
            if int(getattr(getattr(token, "location", None), "offset", -1)) == 199:
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

        nodes = []
        catalog.catalog_root.visit(nodes.append)
        alias = next(
            node.type
            for node in nodes
            if type(node).__name__ == "StructuredAssignmentPatternExpression"
        )
        original_record_range = symbol_graph_module._record_range
        alias_calls = 0

        def wrong_alias(source_catalog, node, name=None):
            nonlocal alias_calls
            result = original_record_range(source_catalog, node, name)
            if node is alias:
                alias_calls += 1
                if alias_calls == 3:
                    return SourceRange(
                        result.file,
                        result.start,
                        result.end - 1,
                    )
            return result

        with mock.patch.object(
            symbol_graph_module,
            "_record_range",
            side_effect=wrong_alias,
        ):
            with self.assertRaises(SymbolGraphError) as raised:
                build_symbol_graph(catalog)
        self.assertEqual(raised.exception.code, "SYMBOL_GRAPH_OWNER_MISMATCH")

        fake = SourceSymbol(
            symbol_id="symbol:signals:design.sv:199:202",
            category="signals",
            name="rhs",
            declaration=SourceRange("design.sv", 199, 202),
            owner_module="module:wrong",
            semantic_owner="wrong-owner",
            occurrences=(),
            impact="local",
            abi="internal",
            support="eligible",
            reason=None,
        )
        with self.assertRaises(SymbolGraphError) as raised:
            symbol_graph_module._collect_extended_symbols(catalog, [fake])
        self.assertEqual(raised.exception.code, "SYMBOL_GRAPH_RANGE_CONFLICT")

        partial = replace(
            fake,
            symbol_id="symbol:signals:design.sv:200:202",
            declaration=SourceRange("design.sv", 200, 202),
        )
        with self.assertRaises(SymbolGraphError) as raised:
            symbol_graph_module._collect_extended_symbols(catalog, [partial])
        self.assertEqual(raised.exception.code, "SYMBOL_GRAPH_RANGE_CONFLICT")

        invalid_sources = {
            "missing": (FIXTURE_ROOT / "design.sv").read_bytes().replace(
                b"'{rhs: data_i, lhs: 1'b0}",
                b"'{: data_i, lhs: 1'b0}",
            ),
            "no_field": (FIXTURE_ROOT / "design.sv").read_bytes().replace(
                b"'{rhs: data_i, lhs: 1'b0}",
                b"'{bogus: data_i, lhs: 1'b0}",
            ),
        }
        for name, source in invalid_sources.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory(
                prefix=f"t084-{name}-"
            ) as temporary:
                root = Path(temporary)
                with self.assertRaises((SourceSetError, SourceCatalogError)):
                    build_source_catalog(
                        self._temporary_source_set(
                            root,
                            source,
                            "t084_top",
                            defines=(PUBLIC_DEFINE,),
                        )
                    )

    def test_public_gate_strict_source_free_restore_and_actual_gate_formal(self):
        with tempfile.TemporaryDirectory(prefix="t084-public-") as temporary:
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
            records = {
                record["original_name"]: record
                for record in report["mapping"]["records"]
                if record["category"] == "struct_fields"
            }
            gate_source = (gate / "design.sv").read_bytes()
            for name in ("lhs", "rhs"):
                renamed = records[name]["renamed_name"].encode("ascii")
                self.assertNotEqual(renamed, name.encode("ascii"))
                self.assertEqual(gate_source.count(renamed), 3)
            gate_catalog = build_source_catalog(self._source_set(gate))
            self.assertEqual(
                gate_catalog.to_report()["compile"],
                {
                    "catalog": {"parse_errors": 0, "semantic_errors": 0},
                    "top_overlay": {"parse_errors": 0, "semantic_errors": 0},
                },
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

            formal, command = self._formal(gate)
            print(f"T084_FORMAL_COMMAND {shlex.join(command)}")
            print(f"T084_FORMAL_EXIT {formal.returncode}")
            print(f"T084_FORMAL_JSON {formal.stdout.strip()}")
        self.assertEqual(formal.returncode, 0, formal.stderr)
        self.assertEqual(
            json.loads(formal.stdout),
            {
                "formal_equivalence": "pass",
                "gate": str(gate),
                "gold": str(FIXTURE_ROOT),
                "seq": 5,
                "top": "t084_top",
            },
        )

    def test_fixed_macro_outside_negative_strict_and_formal_failure(self):
        with tempfile.TemporaryDirectory(
            prefix="t084-formal-negative-"
        ) as temporary:
            root = Path(temporary)
            gate, _mapping_path, report = self._encrypt(root / "encrypt")
            records = {
                record["original_name"]: record
                for record in report["mapping"]["records"]
                if record["category"] == "struct_fields"
            }
            renamed_lhs = records["lhs"]["renamed_name"].encode("ascii")
            renamed_rhs = records["rhs"]["renamed_name"].encode("ascii")
            negative = root / "negative"
            shutil.copytree(gate, negative)
            design = negative / "design.sv"
            source = design.read_bytes()
            marker = (
                b"assign data_o = pair."
                + renamed_lhs
                + b" ^ pair."
                + renamed_rhs
                + b";"
            )
            replacement = (
                b"assign data_o = ~(pair."
                + renamed_lhs
                + b" ^ pair."
                + renamed_rhs
                + b");"
            )
            self.assertEqual(source.count(marker), 1)
            design.write_bytes(source.replace(marker, replacement, 1))
            negative_catalog = build_source_catalog(self._source_set(negative))
            self.assertEqual(
                negative_catalog.to_report()["compile"],
                {
                    "catalog": {"parse_errors": 0, "semantic_errors": 0},
                    "top_overlay": {"parse_errors": 0, "semantic_errors": 0},
                },
            )
            formal, command = self._formal(negative)
            print(f"T084_FORMAL_NEGATIVE_COMMAND {shlex.join(command)}")
            print(f"T084_FORMAL_NEGATIVE_EXIT {formal.returncode}")
        self.assertNotEqual(formal.returncode, 0)
        combined = formal.stdout + formal.stderr
        negative_summary = "\n".join(
            line
            for line in combined.splitlines()
            if "unproven" in line or "equiv_status -assert" in line
        )
        print(f"T084_FORMAL_NEGATIVE_OUTPUT {negative_summary}")
        self.assertIn("unproven", combined)
        self.assertIn("equiv_status -assert", combined)
