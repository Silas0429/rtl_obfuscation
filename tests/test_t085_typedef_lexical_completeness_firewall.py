from __future__ import annotations

from contextlib import redirect_stderr
from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from rtl_obfuscator import rewrite
from rtl_obfuscator import source_catalog as source_catalog_module
from rtl_obfuscator import symbol_graph as symbol_graph_module
from rtl_obfuscator.mapping_vnext import build_mapping_vnext
from rtl_obfuscator.rewrite_policy import build_rewrite_policy
from rtl_obfuscator.rewrite_vnext import RewriteVNextError, write_gate_vnext
from rtl_obfuscator.source_catalog import SourceRange, build_source_catalog
from rtl_obfuscator.source_set import from_filelist
from rtl_obfuscator.symbol_graph import (
    SourceSymbol,
    SymbolGraph,
    SymbolGraphError,
    build_symbol_graph,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "t085_typedef_lexical_firewall"
FILELIST = FIXTURE_ROOT / "design.f"
PUBLIC_DEFINE = "T085_TYPEDEF_QUERY"
T081_ROOT = ROOT / "tests" / "fixtures" / "t081_enum_lexical_firewall"
EXPECTED_FIXTURE = {
    "design.f": (
        10,
        "2bd824b8fab1c3ebc159191ce9f58bbaadd30a5ddbea38fa8a4fcfc4b94d1aea",
    ),
    "design.sv": (
        522,
        "80695d0a8ef7325fe00c046db6b20c7df514ab966559016545f7d1ea0eb64eff",
    ),
}


def _deterministic_factory(
    symbol_id: str, name_length: int, unavailable: frozenset[str]
) -> str:
    candidate = ("t" + hashlib.sha256(symbol_id.encode("utf-8")).hexdigest())[
        :name_length
    ]
    if candidate in unavailable:
        raise AssertionError("test factory collision")
    return candidate


class T085TypedefLexicalCompletenessFirewallTests(unittest.TestCase):
    @staticmethod
    def _source_set(
        root: Path = FIXTURE_ROOT,
        top: str = "t085_top",
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
            categories=("typedefs",),
            abi_categories=("typedefs",),
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
    def _typedef(graph, name: str, declaration_start: int | None = None):
        matches = [
            symbol
            for symbol in graph.symbols
            if symbol.category == "typedefs"
            and symbol.name == name
            and (
                declaration_start is None
                or symbol.declaration.start == declaration_start
            )
        ]
        if len(matches) != 1:
            raise AssertionError((name, declaration_start, matches))
        return matches[0]

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
            "t085_top",
            "--define",
            PUBLIC_DEFINE,
            "--category",
            "typedefs",
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
            "t085_top",
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
    def _temporary_graph(cls, root: Path, source: bytes, top: str):
        root.mkdir(parents=True, exist_ok=True)
        (root / "design.sv").write_bytes(source)
        (root / "design.f").write_bytes(b"design.sv\n")
        source_set = cls._source_set(root, top, defines=())
        catalog = build_source_catalog(source_set)
        return source_set, catalog, build_symbol_graph(catalog)

    def test_fixture_graph_raw_sets_and_record_level_firewall(self):
        for file, (expected_size, expected_sha256) in EXPECTED_FIXTURE.items():
            source = (FIXTURE_ROOT / file).read_bytes()
            self.assertEqual(len(source), expected_size, file)
            self.assertEqual(
                hashlib.sha256(source).hexdigest(), expected_sha256, file
            )

        source_set = self._source_set()
        catalog = build_source_catalog(source_set)
        with mock.patch.object(
            source_catalog_module,
            "_compile_view",
            side_effect=AssertionError("T085 graph rebuilt semantic view"),
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
                "symbols": 12,
                "declarations": 12,
                "occurrences": 15,
                "total_ranges": 27,
            },
        )
        word_t = self._typedef(graph, "word_t", 59)
        self.assertEqual(
            (word_t.support, word_t.reason),
            ("unsupported", "typedef_lexical_coverage_incomplete"),
        )
        self.assertEqual(
            [
                (
                    item.source_range.file,
                    item.source_range.start,
                    item.source_range.end,
                    item.provenance,
                )
                for item in word_t.occurrences
            ],
            [("design.sv", 265, 271, "semantic_type")],
        )
        safe_t = self._typedef(graph, "safe_t", 186)
        self.assertEqual((safe_t.support, safe_t.reason), ("eligible", None))
        self.assertEqual(
            [
                (
                    item.source_range.file,
                    item.source_range.start,
                    item.source_range.end,
                    item.provenance,
                )
                for item in safe_t.occurrences
            ],
            [("design.sv", 196, 202, "semantic_type")],
        )
        source = (source_set.source_root / "design.sv").read_bytes()
        self.assertEqual(
            [index for index in range(len(source)) if source.startswith(b"word_t", index)],
            [59, 265, 301],
        )
        self.assertEqual(
            [index for index in range(len(source)) if source.startswith(b"safe_t", index)],
            [186, 196],
        )

    def test_pre_fix_graph_mapping_and_public_cli_fail_atomically(self):
        catalog = build_source_catalog(self._source_set())
        with mock.patch.object(
            symbol_graph_module,
            "_apply_typedef_lexical_completeness_firewall",
            side_effect=lambda _catalog, symbols, _inventory: symbols,
        ):
            pre_fix_graph = build_symbol_graph(catalog)
        self.assertEqual(
            pre_fix_graph.to_report()["range_audit"],
            {
                "symbols": 12,
                "declarations": 12,
                "occurrences": 15,
                "total_ranges": 27,
            },
        )
        mapping = self._mapping_for(pre_fix_graph)
        self.assertEqual(
            mapping.to_report()["summary"],
            {"total": 12, "rename": 2, "preserve": 10, "unsupported": 0},
        )
        self.assertEqual(
            sum(
                1 + len(record.occurrences)
                for record in mapping.records
                if record.action == "rename"
            ),
            4,
        )
        with tempfile.TemporaryDirectory(prefix="t085-pre-fix-") as temporary:
            root = Path(temporary)
            gate = root / "gate"
            with self.assertRaises(RewriteVNextError) as raised:
                write_gate_vnext(mapping, output_dir=gate)
            self.assertEqual(raised.exception.code, "REWRITE_GATE_COMPILE_FAILED")
            self.assertIn("CATALOG_SEMANTIC_FAILED", raised.exception.message)
            self.assertFalse(gate.exists())

            stderr = io.StringIO()
            argv = [
                "rtl_encrypt",
                "--filelist",
                "design.f",
                "--source-root",
                str(FIXTURE_ROOT),
                "--top",
                "t085_top",
                "--define",
                PUBLIC_DEFINE,
                "--category",
                "typedefs",
                "--output-dir",
                str(root / "public-gate"),
            ]
            with mock.patch.object(
                symbol_graph_module,
                "_apply_typedef_lexical_completeness_firewall",
                side_effect=lambda _catalog, symbols, _inventory: symbols,
            ), mock.patch.object(sys, "argv", argv), redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as exited:
                    rewrite.rtl_encrypt_main()
            self.assertEqual(exited.exception.code, 1)
            self.assertIn("CLI_VNEXT_ORCHESTRATION_INVALID", stderr.getvalue())
            self.assertFalse((root / "public-gate").exists())

    def test_mapping_keeps_safe_rename_and_word_zero_edit(self):
        mapping = self._mapping()
        self.assertEqual(
            mapping.to_report()["summary"],
            {"total": 12, "rename": 1, "preserve": 10, "unsupported": 1},
        )
        typedefs = {
            record.original_name: record
            for record in mapping.records
            if record.category == "typedefs"
        }
        self.assertEqual(
            (typedefs["word_t"].action, typedefs["word_t"].reason),
            ("unsupported", "typedef_lexical_coverage_incomplete"),
        )
        self.assertIsNone(typedefs["word_t"].renamed_name)
        self.assertEqual(
            typedefs["word_t"].symbol_id,
            "symbol:typedefs:design.sv:59:65",
        )
        self.assertEqual(
            (typedefs["safe_t"].action, typedefs["safe_t"].reason),
            ("rename", None),
        )
        with tempfile.TemporaryDirectory(prefix="t085-execution-") as temporary:
            execution = write_gate_vnext(
                mapping, output_dir=Path(temporary) / "gate"
            )
            self.assertEqual(len(execution.edits), 2)
            self.assertEqual(
                [
                    edit
                    for edit in execution.edits
                    if edit.symbol_id == typedefs["word_t"].symbol_id
                ],
                [],
            )
            safe_edits = [
                edit
                for edit in execution.edits
                if edit.symbol_id == typedefs["safe_t"].symbol_id
            ]
            self.assertEqual(
                {
                    (
                        edit.source_range.start,
                        edit.source_range.end,
                        edit.provenance,
                    )
                    for edit in safe_edits
                },
                {(186, 192, "declaration"), (196, 202, "semantic_type")},
            )
            self.assertEqual(
                {edit.renamed_name for edit in safe_edits},
                {typedefs["safe_t"].renamed_name},
            )

    def test_comments_strings_macro_and_same_name_scopes_quarantine(self):
        extras = {
            "comment": "  // TOKEN_T\n",
            "string": '  localparam string NOTE = "TOKEN_T";\n',
            "macro": "`define T085_UNUSED TOKEN_T\n",
        }
        for label, extra in extras.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory(
                prefix=f"t085-{label}-"
            ) as temporary:
                root = Path(temporary)
                source = (
                    "module t085_text (input logic data_i, output logic data_o);\n"
                    f"{extra}"
                    "  typedef logic TOKEN_T;\n"
                    "  TOKEN_T value;\n"
                    "  assign value = data_i;\n"
                    "  assign data_o = value;\n"
                    "endmodule\n"
                ).encode("ascii")
                _source_set, _catalog, graph = self._temporary_graph(
                    root, source, "t085_text"
                )
                token = self._typedef(graph, "TOKEN_T")
                self.assertEqual(
                    (token.support, token.reason),
                    ("unsupported", "typedef_lexical_coverage_incomplete"),
                )
                record = next(
                    record
                    for record in self._mapping_for(graph).records
                    if record.symbol_id == token.symbol_id
                )
                self.assertEqual(
                    (record.action, record.reason, record.renamed_name),
                    (
                        "unsupported",
                        "typedef_lexical_coverage_incomplete",
                        None,
                    ),
                )

        scopes = b"""module t085_scope_a (input logic data_i, output logic data_o);
  typedef logic DUP_T;
  DUP_T value;
  assign value = data_i;
  assign data_o = value;
endmodule
module t085_scope_b (input logic data_i, output logic data_o);
  typedef logic DUP_T;
  DUP_T value;
  assign value = data_i;
  assign data_o = value;
endmodule
module t085_scope_top (input logic data_i, output logic data_o);
  logic a_o;
  logic b_o;
  t085_scope_a u_a (.data_i(data_i), .data_o(a_o));
  t085_scope_b u_b (.data_i(data_i), .data_o(b_o));
  assign data_o = a_o ^ b_o;
endmodule
"""
        with tempfile.TemporaryDirectory(prefix="t085-scopes-") as temporary:
            root = Path(temporary)
            _source_set, _catalog, graph = self._temporary_graph(
                root, scopes, "t085_scope_top"
            )
            records = [
                symbol
                for symbol in graph.symbols
                if symbol.category == "typedefs" and symbol.name == "DUP_T"
            ]
            self.assertEqual(len(records), 2)
            self.assertEqual(len({record.semantic_owner for record in records}), 2)
            self.assertTrue(
                all(
                    record.support == "unsupported"
                    and record.reason == "typedef_lexical_coverage_incomplete"
                    for record in records
                )
            )
            mapping = self._mapping_for(graph)
            decisions = {
                record.symbol_id: record
                for record in mapping.records
                if record.category == "typedefs"
            }
            self.assertEqual(set(decisions), {record.symbol_id for record in records})
            self.assertTrue(
                all(record.action == "unsupported" for record in decisions.values())
            )
            with tempfile.TemporaryDirectory(prefix="t085-scope-gate-") as gate_root:
                execution = write_gate_vnext(
                    mapping, output_dir=Path(gate_root) / "gate"
                )
                self.assertFalse(
                    any(edit.symbol_id in decisions for edit in execution.edits)
                )

    def test_existing_support_non_typedef_and_ranges_remain_identical(self):
        _source_set, catalog, graph = self._catalog_graph()
        word_t = self._typedef(graph, "word_t", 59)
        safe_t = self._typedef(graph, "safe_t", 186)
        preserved = replace(
            word_t,
            support="preserved",
            reason="existing_preserved_reason",
        )
        unsupported = replace(
            word_t,
            support="unsupported",
            reason="existing_unsupported_reason",
        )
        self.assertEqual(
            symbol_graph_module._apply_typedef_lexical_completeness_firewall(
                catalog, [preserved]
            ),
            [preserved],
        )
        self.assertEqual(
            symbol_graph_module._apply_typedef_lexical_completeness_firewall(
                catalog, [unsupported]
            ),
            [unsupported],
        )
        self.assertEqual(
            symbol_graph_module._apply_typedef_lexical_completeness_firewall(
                catalog, [safe_t]
            ),
            [safe_t],
        )
        non_typedefs = [
            symbol for symbol in graph.symbols if symbol.category != "typedefs"
        ]
        self.assertEqual(
            symbol_graph_module._apply_typedef_lexical_completeness_firewall(
                catalog, non_typedefs
            ),
            non_typedefs,
        )

    def test_t081_enum_firewall_actions_reasons_ranges_and_edits_are_unchanged(self):
        source_set = from_filelist(
            filelist=T081_ROOT / "design.f",
            source_root=T081_ROOT,
            top="t081_top",
        )
        catalog = build_source_catalog(source_set)
        graph = build_symbol_graph(catalog)
        self.assertEqual(
            graph.to_report()["range_audit"],
            {
                "symbols": 11,
                "declarations": 11,
                "occurrences": 12,
                "total_ranges": 23,
            },
        )
        enums = {
            symbol.name: symbol
            for symbol in graph.symbols
            if symbol.category == "enum_values"
        }
        self.assertEqual(
            (enums["MODE_SAFE"].support, enums["MODE_SAFE"].reason),
            ("eligible", None),
        )
        self.assertEqual(
            [
                (
                    occurrence.source_range.start,
                    occurrence.source_range.end,
                    occurrence.provenance,
                )
                for occurrence in enums["MODE_SAFE"].occurrences
            ],
            [(286, 295, "semantic_reference")],
        )
        self.assertEqual(
            (
                enums["MODE_GAP"].support,
                enums["MODE_GAP"].reason,
                enums["MODE_GAP"].occurrences,
            ),
            (
                "unsupported",
                "enum_lexical_coverage_incomplete",
                (),
            ),
        )
        mapping = build_mapping_vnext(
            build_rewrite_policy(
                graph,
                categories=("enum_values",),
                abi_categories=(),
            ),
            name_length=16,
            name_factory=_deterministic_factory,
        )
        self.assertEqual(
            mapping.to_report()["summary"],
            {"total": 11, "rename": 1, "preserve": 9, "unsupported": 1},
        )
        gap_record = next(
            record
            for record in mapping.records
            if record.symbol_id == enums["MODE_GAP"].symbol_id
        )
        self.assertEqual(
            (gap_record.action, gap_record.reason, gap_record.renamed_name),
            ("unsupported", "enum_lexical_coverage_incomplete", None),
        )
        with tempfile.TemporaryDirectory(prefix="t085-t081-identity-") as temporary:
            execution = write_gate_vnext(
                mapping, output_dir=Path(temporary) / "gate"
            )
            self.assertEqual(len(execution.edits), 2)
            self.assertFalse(
                any(
                    edit.symbol_id == enums["MODE_GAP"].symbol_id
                    for edit in execution.edits
                )
            )

    def test_duplicate_overlapping_and_nonphysical_evidence_stays_fail_closed(self):
        _source_set, catalog, graph = self._catalog_graph()
        safe_t = self._typedef(graph, "safe_t", 186)
        duplicate = replace(safe_t, symbol_id="symbol:test:duplicate")
        with self.assertRaises(SymbolGraphError) as raised:
            symbol_graph_module._audit_ranges((safe_t, duplicate))
        self.assertEqual(raised.exception.code, "SYMBOL_GRAPH_RANGE_CONFLICT")

        overlapping = replace(
            safe_t,
            symbol_id="symbol:test:overlap",
            declaration=SourceRange(
                safe_t.declaration.file,
                safe_t.declaration.start + 1,
                safe_t.declaration.end + 1,
            ),
            occurrences=(),
        )
        with self.assertRaises(SymbolGraphError) as raised:
            symbol_graph_module._audit_ranges((safe_t, overlapping))
        self.assertEqual(raised.exception.code, "SYMBOL_GRAPH_RANGE_CONFLICT")

        nonphysical = replace(
            safe_t,
            symbol_id="symbol:test:nonphysical",
            declaration=SourceRange("missing.sv", 0, 6),
            occurrences=(),
        )
        nonphysical_result = (
            symbol_graph_module._apply_typedef_lexical_completeness_firewall(
                catalog, [nonphysical]
            )[0]
        )
        self.assertEqual(
            (nonphysical_result.support, nonphysical_result.reason),
            ("unsupported", "typedef_lexical_coverage_incomplete"),
        )
        self.assertEqual(nonphysical_result.declaration, nonphysical.declaration)

    def test_public_gate_strict_source_free_restore_and_actual_gate_formal(self):
        with tempfile.TemporaryDirectory(prefix="t085-public-") as temporary:
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
                (1, 12, 2, True, True),
            )
            typedefs = {
                record["original_name"]: record
                for record in report["mapping"]["records"]
                if record["category"] == "typedefs"
            }
            self.assertEqual(
                (
                    typedefs["word_t"]["action"],
                    typedefs["word_t"]["reason"],
                    typedefs["word_t"]["renamed_name"],
                ),
                (
                    "unsupported",
                    "typedef_lexical_coverage_incomplete",
                    None,
                ),
            )
            self.assertEqual(typedefs["safe_t"]["action"], "rename")
            gate_catalog = build_source_catalog(self._source_set(gate))
            self.assertEqual(
                gate_catalog.to_report()["compile"],
                {
                    "catalog": {"parse_errors": 0, "semantic_errors": 0},
                    "top_overlay": {"parse_errors": 0, "semantic_errors": 0},
                },
            )
            gate_source = (gate / "design.sv").read_bytes()
            self.assertEqual(gate_source.count(b"word_t"), 3)
            self.assertNotIn(b"safe_t", gate_source)
            safe_renamed = typedefs["safe_t"]["renamed_name"].encode("ascii")
            self.assertEqual(gate_source.count(safe_renamed), 2)

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
            print(f"T085_FORMAL_COMMAND {shlex.join(command)}")
            print(f"T085_FORMAL_EXIT {formal.returncode}")
            print(f"T085_FORMAL_JSON {formal.stdout.strip()}")
        self.assertEqual(formal.returncode, 0, formal.stderr)
        self.assertEqual(
            json.loads(formal.stdout),
            {
                "formal_equivalence": "pass",
                "gate": str(gate),
                "gold": str(FIXTURE_ROOT),
                "seq": 5,
                "top": "t085_top",
            },
        )

    def test_fixed_macro_outside_negative_strict_and_formal_failure(self):
        with tempfile.TemporaryDirectory(
            prefix="t085-formal-negative-"
        ) as temporary:
            root = Path(temporary)
            gate, _mapping, _report = self._encrypt(root / "encrypt")
            negative = root / "negative"
            shutil.copytree(gate, negative)
            design = negative / "design.sv"
            source = design.read_bytes()
            marker = b"assign data_o = (safe_value == SafeOne);"
            replacement = b"assign data_o = ~(safe_value == SafeOne);"
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
            print(f"T085_FORMAL_NEGATIVE_COMMAND {shlex.join(command)}")
            print(f"T085_FORMAL_NEGATIVE_EXIT {formal.returncode}")
        self.assertNotEqual(formal.returncode, 0)
        combined = formal.stdout + formal.stderr
        negative_summary = "\n".join(
            line
            for line in combined.splitlines()
            if "unproven" in line or "equiv_status -assert" in line
        )
        print(f"T085_FORMAL_NEGATIVE_OUTPUT {negative_summary}")
        self.assertIn("unproven", combined)
        self.assertIn("equiv_status -assert", combined)
