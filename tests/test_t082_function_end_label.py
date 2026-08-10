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
from rtl_obfuscator.source_catalog import SourceRange, build_source_catalog
from rtl_obfuscator.source_set import SourceSetError, from_filelist
from rtl_obfuscator.symbol_graph import (
    SourceSymbol,
    SymbolGraph,
    SymbolGraphError,
    build_symbol_graph,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "t082_function_end_label"
FILELIST = FIXTURE_ROOT / "design.f"
PUBLIC_DEFINE = "T082_LABEL_CLOSURE"
EXPECTED_FIXTURE = {
    "design.f": (
        10,
        "2bd824b8fab1c3ebc159191ce9f58bbaadd30a5ddbea38fa8a4fcfc4b94d1aea",
    ),
    "design.sv": (
        421,
        "decd2aaf72d4a15abf49b677aee82b26c016b4d8a4001505714ee53a98537eaf",
    ),
}


def _deterministic_factory(
    symbol_id: str, name_length: int, unavailable: frozenset[str]
) -> str:
    candidate = ("f" + hashlib.sha256(symbol_id.encode("utf-8")).hexdigest())[
        :name_length
    ]
    if candidate in unavailable:
        raise AssertionError("test factory collision")
    return candidate


class T082FunctionEndLabelTests(unittest.TestCase):
    @staticmethod
    def _source_set(
        root: Path = FIXTURE_ROOT,
        top: str = "t082_top",
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
            categories=("functions",),
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
    def _function(graph, name: str):
        return next(
            symbol
            for symbol in graph.symbols
            if symbol.category == "functions" and symbol.name == name
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
            "design.f",
            "--source-root",
            str(FIXTURE_ROOT),
            "--top",
            "t082_top",
            "--define",
            PUBLIC_DEFINE,
            "--category",
            "functions",
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
            "t082_top",
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
    def _temporary_source_set(
        root: Path,
        source: bytes,
        top: str,
        *,
        defines: tuple[str, ...] = (),
    ):
        root.mkdir(parents=True, exist_ok=True)
        (root / "design.sv").write_bytes(source)
        (root / "design.f").write_bytes(b"design.sv\n")
        return T082FunctionEndLabelTests._source_set(
            root, top, defines=defines
        )

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
        subroutines = {
            str(node.name): node
            for node in nodes
            if type(node).__name__ == "SubroutineSymbol"
        }
        self.assertEqual(
            type(subroutines["invert"].syntax).__name__,
            "FunctionDeclarationSyntax",
        )
        end_name = subroutines["invert"].syntax.endBlockName
        self.assertEqual(type(end_name).__name__, "NamedBlockClauseSyntax")
        self.assertEqual(
            (str(end_name.name.rawText), int(end_name.name.location.offset)),
            ("invert", 334),
        )
        self.assertIsNone(subroutines["passthrough"].syntax.endBlockName)

        with mock.patch.object(
            source_catalog_module,
            "_compile_view",
            side_effect=AssertionError("T082 graph rebuilt semantic view"),
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
                "symbols": 8,
                "declarations": 8,
                "occurrences": 11,
                "total_ranges": 19,
            },
        )
        invert = self._function(graph, "invert")
        self.assertEqual((invert.declaration.start, invert.declaration.end), (270, 276))
        self.assertEqual(
            [
                (
                    occurrence.source_range.start,
                    occurrence.source_range.end,
                    occurrence.provenance,
                )
                for occurrence in invert.occurrences
            ],
            [
                (301, 307, "semantic_reference"),
                (334, 340, "semantic_function_end_label"),
                (359, 365, "semantic_call"),
            ],
        )
        passthrough = self._function(graph, "passthrough")
        self.assertEqual(
            [occurrence.provenance for occurrence in passthrough.occurrences],
            ["semantic_reference", "semantic_call"],
        )
        self.assertNotIn(
            "semantic_function_end_label",
            [occurrence.provenance for occurrence in passthrough.occurrences],
        )

    def test_pre_fix_missing_label_characterization_fails_atomically(self):
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
                        if occurrence.provenance
                        != "semantic_function_end_label"
                    ),
                )
                for symbol in graph.symbols
            ),
        )
        self.assertEqual(
            pre_fix_graph.to_report()["range_audit"],
            {
                "symbols": 8,
                "declarations": 8,
                "occurrences": 10,
                "total_ranges": 18,
            },
        )
        mapping = self._mapping_for(pre_fix_graph)
        self.assertEqual(
            mapping.to_report()["summary"],
            {"total": 8, "rename": 2, "preserve": 6, "unsupported": 0},
        )
        self.assertEqual(
            sum(
                1 + len(record.occurrences)
                for record in mapping.records
                if record.action == "rename"
            ),
            6,
        )
        with tempfile.TemporaryDirectory(prefix="t082-pre-fix-") as temporary:
            gate = Path(temporary) / "gate"
            with self.assertRaises(RewriteVNextError) as raised:
                write_gate_vnext(mapping, output_dir=gate)
            self.assertEqual(
                raised.exception.code,
                "REWRITE_GATE_COMPILE_FAILED",
            )
            self.assertFalse(gate.exists())

    def test_mapping_and_execution_use_one_name_for_all_function_ranges(self):
        mapping = self._mapping()
        self.assertEqual(
            mapping.to_report()["summary"],
            {"total": 8, "rename": 2, "preserve": 6, "unsupported": 0},
        )
        self.assertEqual(
            sum(
                1 + len(record.occurrences)
                for record in mapping.records
                if record.action == "rename"
            ),
            7,
        )
        records = {
            record.original_name: record
            for record in mapping.records
            if record.category == "functions"
        }
        invert = records["invert"]
        self.assertEqual(invert.action, "rename")
        self.assertEqual(
            [item.provenance for item in invert.occurrences],
            [
                "semantic_reference",
                "semantic_function_end_label",
                "semantic_call",
            ],
        )
        self.assertNotIn(
            "semantic_function_end_label",
            [item.provenance for item in records["passthrough"].occurrences],
        )
        with tempfile.TemporaryDirectory(prefix="t082-execution-") as temporary:
            gate = Path(temporary) / "gate"
            execution = write_gate_vnext(mapping, output_dir=gate)
            self.assertEqual(len(execution.edits), 7)
            invert_edits = [
                edit for edit in execution.edits if edit.symbol_id == invert.symbol_id
            ]
            self.assertEqual(len(invert_edits), 4)
            self.assertEqual(
                {
                    (edit.source_range.start, edit.source_range.end, edit.provenance)
                    for edit in invert_edits
                },
                {
                    (270, 276, "declaration"),
                    (301, 307, "semantic_reference"),
                    (334, 340, "semantic_function_end_label"),
                    (359, 365, "semantic_call"),
                },
            )
            self.assertEqual(
                {edit.renamed_name for edit in invert_edits},
                {invert.renamed_name},
            )

    def test_public_gate_strict_and_source_free_restore(self):
        with tempfile.TemporaryDirectory(prefix="t082-public-") as temporary:
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
                (1, 8, 7, True, True),
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
            self.assertNotIn(b"passthrough", gate_source)
            self.assertNotIn(b"invert", gate_source)

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

    def test_actual_public_gate_formal_without_label_define(self):
        with tempfile.TemporaryDirectory(
            prefix="t082-formal-positive-"
        ) as temporary:
            gate, _mapping, report = self._encrypt(Path(temporary) / "encrypt")
            records = report["mapping"]["records"]
            passthrough = next(
                record
                for record in records
                if record["category"] == "functions"
                and record["original_name"] == "passthrough"
            )
            gate_source = (gate / "design.sv").read_bytes()
            renamed = passthrough["renamed_name"].encode("ascii")
            self.assertNotIn(b"passthrough", gate_source)
            self.assertEqual(gate_source.count(renamed), 3)
            formal, command = self._formal(gate)
            print(f"T082_FORMAL_COMMAND {shlex.join(command)}")
            print(f"T082_FORMAL_EXIT {formal.returncode}")
            print(f"T082_FORMAL_JSON {formal.stdout.strip()}")
        self.assertEqual(formal.returncode, 0, formal.stderr)
        self.assertEqual(
            json.loads(formal.stdout),
            {
                "formal_equivalence": "pass",
                "gate": str(gate),
                "gold": str(FIXTURE_ROOT),
                "seq": 5,
                "top": "t082_top",
            },
        )

    def test_fixed_macro_outside_negative_strict_and_formal_failure(self):
        with tempfile.TemporaryDirectory(
            prefix="t082-formal-negative-"
        ) as temporary:
            root = Path(temporary)
            gate, _mapping, report = self._encrypt(root / "encrypt")
            passthrough = next(
                record
                for record in report["mapping"]["records"]
                if record["category"] == "functions"
                and record["original_name"] == "passthrough"
            )
            negative = root / "negative"
            shutil.copytree(gate, negative)
            design = negative / "design.sv"
            source = design.read_bytes()
            renamed = passthrough["renamed_name"].encode("ascii")
            marker = b"assign base = " + renamed + b"(data_i);"
            self.assertEqual(source.count(marker), 1)
            design.write_bytes(
                source.replace(
                    marker,
                    b"assign base = ~" + renamed + b"(data_i);",
                    1,
                )
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
            print(f"T082_FORMAL_NEGATIVE_COMMAND {shlex.join(command)}")
            print(f"T082_FORMAL_NEGATIVE_EXIT {formal.returncode}")
            print(f"T082_FORMAL_NEGATIVE_STDOUT {formal.stdout.strip()}")
        self.assertNotEqual(formal.returncode, 0)
        combined = formal.stdout + formal.stderr
        negative_summary = "\n".join(
            line
            for line in combined.splitlines()
            if "unproven" in line or "equiv_status -assert" in line
        )
        print(f"T082_FORMAL_NEGATIVE_OUTPUT {negative_summary}")
        self.assertIn("unproven", combined)
        self.assertIn("equiv_status -assert", combined)

    def test_task_closing_label_is_not_a_function_occurrence(self):
        source = b"""module t082_task (input logic data_i, output logic data_o);
  task automatic pulse(input logic value);
  endtask : pulse
  assign data_o = data_i;
endmodule
"""
        with tempfile.TemporaryDirectory(prefix="t082-task-") as temporary:
            root = Path(temporary)
            source_set = self._temporary_source_set(root, source, "t082_task")
            graph = build_symbol_graph(build_source_catalog(source_set))
            self.assertFalse(
                any(
                    symbol.category == "functions" and symbol.name == "pulse"
                    for symbol in graph.symbols
                )
            )
            task = next(
                symbol
                for symbol in graph.symbols
                if symbol.category == "tasks" and symbol.name == "pulse"
            )
            self.assertNotIn(
                "semantic_function_end_label",
                [item.provenance for item in task.occurrences],
            )
            record = next(
                record
                for record in self._mapping_for(graph).records
                if record.symbol_id == task.symbol_id
            )
            self.assertEqual(
                (record.action, record.reason),
                ("preserve", "category_not_selected"),
            )

    def test_repeated_elaboration_deduplicates_and_macro_label_has_no_edit(self):
        repeated_source = b"""module t082_repeat_child (input logic data_i, output logic data_o);
  function automatic logic flip(input logic value);
    flip = ~value;
  endfunction : flip
  assign data_o = flip(data_i);
endmodule
module t082_repeat_top (input logic data_i, output logic data_o);
  logic a_o;
  logic b_o;
  t082_repeat_child u_a (.data_i(data_i), .data_o(a_o));
  t082_repeat_child u_b (.data_i(data_i), .data_o(b_o));
  assign data_o = a_o ^ b_o;
endmodule
"""
        with tempfile.TemporaryDirectory(prefix="t082-repeat-") as temporary:
            root = Path(temporary)
            source_set = self._temporary_source_set(
                root, repeated_source, "t082_repeat_top"
            )
            graph = build_symbol_graph(build_source_catalog(source_set))
            functions = [
                symbol
                for symbol in graph.symbols
                if symbol.category == "functions" and symbol.name == "flip"
            ]
            self.assertEqual(len(functions), 1)
            labels = [
                item
                for item in functions[0].occurrences
                if item.provenance == "semantic_function_end_label"
            ]
            self.assertEqual(len(labels), 1)

        macro_source = b"""`define T082_END(NAME) endfunction : NAME
module t082_macro (input logic data_i, output logic data_o);
  function automatic logic helper(input logic value);
    helper = value;
  `T082_END(helper)
  assign data_o = helper(data_i);
endmodule
        """
        with tempfile.TemporaryDirectory(prefix="t082-macro-") as temporary:
            root = Path(temporary) / "source"
            source_set = self._temporary_source_set(
                root, macro_source, "t082_macro"
            )
            graph = build_symbol_graph(build_source_catalog(source_set))
            helper = self._function(graph, "helper")
            self.assertNotIn(
                "semantic_function_end_label",
                [item.provenance for item in helper.occurrences],
            )
            mapping = self._mapping_for(graph)
            record = next(
                record
                for record in mapping.records
                if record.symbol_id == helper.symbol_id
            )
            self.assertEqual(record.action, "unsupported")
            gate = Path(temporary) / "gate"
            execution = write_gate_vnext(mapping, output_dir=gate)
            self.assertFalse(
                any(edit.symbol_id == helper.symbol_id for edit in execution.edits)
            )

    def test_mismatch_missing_and_occupied_ranges_fail_closed(self):
        source_set = self._source_set()
        catalog = build_source_catalog(source_set)
        original_token_range = symbol_graph_module._token_source_range

        def mismatch(source_catalog, token, name):
            if int(getattr(getattr(token, "location", None), "offset", -1)) == 334:
                return original_token_range(source_catalog, token, name + "_mismatch")
            return original_token_range(source_catalog, token, name)

        with mock.patch.object(
            symbol_graph_module,
            "_token_source_range",
            side_effect=mismatch,
        ):
            with self.assertRaises(SymbolGraphError) as raised:
                build_symbol_graph(catalog)
        self.assertEqual(raised.exception.code, "SYMBOL_GRAPH_SOURCE_INVALID")

        label = SourceRange("design.sv", 334, 340)
        fake = SourceSymbol(
            symbol_id="symbol:test:occupied-label",
            category="signals",
            name="invert",
            declaration=label,
            owner_module="module:test",
            semantic_owner="module:test",
            occurrences=(),
            impact="local",
            abi="internal",
            support="eligible",
            reason=None,
        )
        for occupied in (
            fake,
            SourceSymbol(
                **{
                    **fake.__dict__,
                    "symbol_id": "symbol:test:partial-label",
                    "declaration": SourceRange("design.sv", 334, 339),
                }
            ),
        ):
            with self.subTest(symbol_id=occupied.symbol_id):
                with self.assertRaises(SymbolGraphError) as raised:
                    symbol_graph_module._collect_extended_symbols(
                        catalog, [occupied]
                    )
                self.assertEqual(
                    raised.exception.code,
                    "SYMBOL_GRAPH_RANGE_CONFLICT",
                )

        invalid_source = b"""module t082_missing;
  function automatic logic bad(input logic value);
    bad = value;
  endfunction :
endmodule
"""
        with tempfile.TemporaryDirectory(prefix="t082-missing-") as temporary:
            root = Path(temporary)
            root.mkdir(parents=True, exist_ok=True)
            (root / "design.sv").write_bytes(invalid_source)
            (root / "design.f").write_bytes(b"design.sv\n")
            with self.assertRaises(SourceSetError) as missing:
                from_filelist(
                    filelist=root / "design.f",
                    source_root=root,
                    top="t082_missing",
                )
        self.assertEqual(missing.exception.code, "SOURCESET_DISCOVERY_FAILED")


if __name__ == "__main__":
    unittest.main()
