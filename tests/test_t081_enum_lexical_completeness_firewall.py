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
from rtl_obfuscator.rewrite_vnext import write_gate_vnext
from rtl_obfuscator.source_catalog import build_source_catalog
from rtl_obfuscator.source_set import from_filelist
from rtl_obfuscator.symbol_graph import (
    SourceSymbol,
    SymbolGraphError,
    build_symbol_graph,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "t081_enum_lexical_firewall"
FILELIST = FIXTURE_ROOT / "design.f"
EXPECTED_FIXTURE = {
    "design.f": (
        10,
        "2bd824b8fab1c3ebc159191ce9f58bbaadd30a5ddbea38fa8a4fcfc4b94d1aea",
    ),
    "design.sv": (
        491,
        "baeb01b058156ecb707dab0aee2c86526632f15cfb487a3788bfff7984a90c81",
    ),
}


def _deterministic_factory(
    symbol_id: str, name_length: int, unavailable: frozenset[str]
) -> str:
    candidate = ("e" + hashlib.sha256(symbol_id.encode("utf-8")).hexdigest())[
        :name_length
    ]
    if candidate in unavailable:
        raise AssertionError("test factory collision")
    return candidate


class T081EnumLexicalCompletenessFirewallTests(unittest.TestCase):
    @staticmethod
    def _source_set(
        root: Path = FIXTURE_ROOT,
        top: str = "t081_top",
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

    @staticmethod
    def _mapping_for(graph):
        policy = build_rewrite_policy(
            graph,
            categories=("enum_values",),
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
    def _enum(graph, name: str, declaration_start: int | None = None):
        matches = [
            symbol
            for symbol in graph.symbols
            if symbol.category == "enum_values"
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
            str(FIXTURE_ROOT / "design.f"),
            "--top",
            "t081_top",
            "--category",
            "enum_values",
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
            "t081_top",
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
        root.mkdir(parents=True, exist_ok=True)
        (root / "design.sv").write_bytes(source)
        (root / "design.f").write_bytes(b"design.sv\n")
        source_set = T081EnumLexicalCompletenessFirewallTests._source_set(
            root, top
        )
        catalog = build_source_catalog(source_set)
        return source_set, catalog, build_symbol_graph(catalog)

    def test_fixture_graph_ranges_and_record_level_firewall(self):
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
            side_effect=AssertionError("T081 graph rebuilt semantic view"),
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
                "symbols": 11,
                "declarations": 11,
                "occurrences": 12,
                "total_ranges": 23,
            },
        )

        mode_safe = self._enum(graph, "MODE_SAFE", 95)
        self.assertEqual((mode_safe.support, mode_safe.reason), ("eligible", None))
        self.assertEqual(
            [
                (
                    occurrence.source_range.file,
                    occurrence.source_range.start,
                    occurrence.source_range.end,
                    occurrence.provenance,
                )
                for occurrence in mode_safe.occurrences
            ],
            [("design.sv", 286, 295, "semantic_reference")],
        )
        mode_gap = self._enum(graph, "MODE_GAP", 110)
        self.assertEqual(
            (mode_gap.support, mode_gap.reason, mode_gap.occurrences),
            (
                "unsupported",
                "enum_lexical_coverage_incomplete",
                (),
            ),
        )
        source = (source_set.source_root / "design.sv").read_bytes()
        self.assertEqual(
            [index for index in range(len(source)) if source.startswith(b"MODE_GAP", index)],
            [110, 156, 181],
        )
        for symbol in graph.symbols:
            for source_range in (
                symbol.declaration,
                *(item.source_range for item in symbol.occurrences),
            ):
                physical = (source_set.source_root / source_range.file).read_bytes()
                self.assertEqual(
                    physical[source_range.start : source_range.end],
                    symbol.name.encode("utf-8"),
                )

    def test_mapping_keeps_complete_enum_rename_and_gap_zero_edit(self):
        mapping = self._mapping()
        self.assertEqual(
            mapping.to_report()["summary"],
            {"total": 11, "rename": 1, "preserve": 9, "unsupported": 1},
        )
        enums = {
            record.original_name: record
            for record in mapping.records
            if record.category == "enum_values"
        }
        self.assertEqual((enums["MODE_SAFE"].action, enums["MODE_SAFE"].reason), ("rename", None))
        self.assertEqual(
            (enums["MODE_GAP"].action, enums["MODE_GAP"].reason),
            ("unsupported", "enum_lexical_coverage_incomplete"),
        )
        self.assertEqual(
            enums["MODE_GAP"].symbol_id,
            "symbol:enum_values:design.sv:110:118",
        )
        self.assertEqual(
            sum(
                1 + len(record.occurrences)
                for record in mapping.records
                if record.action == "rename"
            ),
            2,
        )
        with tempfile.TemporaryDirectory(prefix="t081-execution-") as temporary:
            execution = write_gate_vnext(
                mapping, output_dir=Path(temporary) / "gate"
            )
            self.assertEqual(len(execution.edits), 2)
            self.assertEqual(
                [
                    edit
                    for edit in execution.edits
                    if edit.symbol_id == enums["MODE_GAP"].symbol_id
                ],
                [],
            )

    def test_public_gate_strict_zero_gap_edits_and_source_free_restore(self):
        with tempfile.TemporaryDirectory(prefix="t081-public-") as temporary:
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
                (1, 11, 2, True, True),
            )
            mode_gap = next(
                record
                for record in report["mapping"]["records"]
                if record["category"] == "enum_values"
                and record["original_name"] == "MODE_GAP"
            )
            self.assertEqual(
                (
                    mode_gap["action"],
                    mode_gap["reason"],
                    mode_gap["renamed_name"],
                    mode_gap["occurrences"],
                ),
                (
                    "unsupported",
                    "enum_lexical_coverage_incomplete",
                    None,
                    [],
                ),
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
            self.assertEqual(gate_source.count(b"MODE_GAP"), 3)
            self.assertNotIn(b"MODE_SAFE", gate_source)

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
            prefix="t081-formal-positive-"
        ) as temporary:
            gate, _mapping, _report = self._encrypt(Path(temporary) / "encrypt")
            formal, command = self._formal(gate)
            print(f"T081_FORMAL_COMMAND {shlex.join(command)}")
            print(f"T081_FORMAL_EXIT {formal.returncode}")
            print(f"T081_FORMAL_JSON {formal.stdout.strip()}")
        self.assertEqual(formal.returncode, 0, formal.stderr)
        self.assertEqual(
            json.loads(formal.stdout),
            {
                "formal_equivalence": "pass",
                "gate": str(gate),
                "gold": str(FIXTURE_ROOT),
                "seq": 5,
                "top": "t081_top",
            },
        )

    def test_fixed_tilde_negative_strict_and_formal_failure(self):
        with tempfile.TemporaryDirectory(
            prefix="t081-formal-negative-"
        ) as temporary:
            root = Path(temporary)
            gate, _mapping, _report = self._encrypt(root / "encrypt")
            negative = root / "negative"
            shutil.copytree(gate, negative)
            design = negative / "design.sv"
            source = design.read_bytes()
            marker = b"assign data_o = ("
            self.assertEqual(source.count(marker), 1)
            design.write_bytes(source.replace(marker, b"assign data_o = ~(", 1))
            negative_catalog = build_source_catalog(self._source_set(negative))
            self.assertEqual(
                negative_catalog.to_report()["compile"],
                {
                    "catalog": {"parse_errors": 0, "semantic_errors": 0},
                    "top_overlay": {"parse_errors": 0, "semantic_errors": 0},
                },
            )
            formal, command = self._formal(negative)
            print(f"T081_FORMAL_NEGATIVE_COMMAND {shlex.join(command)}")
            print(f"T081_FORMAL_NEGATIVE_EXIT {formal.returncode}")
            print(f"T081_FORMAL_NEGATIVE_STDOUT {formal.stdout.strip()}")
        self.assertNotEqual(formal.returncode, 0)
        combined = formal.stdout + formal.stderr
        self.assertIn("unproven", combined)
        self.assertIn("equiv_status -assert", combined)

    def test_comments_strings_and_macro_text_each_quarantine(self):
        extras = {
            "comment": "  // TOKEN\n",
            "string": '  localparam string NOTE = "TOKEN";\n',
            "macro": "`define T081_UNUSED TOKEN\n",
        }
        for label, extra in extras.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory(
                prefix=f"t081-{label}-"
            ) as temporary:
                root = Path(temporary)
                source = (
                    "module t081_text (input logic data_i, output logic data_o);\n"
                    f"{extra}"
                    "  typedef enum logic { TOKEN } text_e;\n"
                    "  text_e state;\n"
                    "  always_comb state = TOKEN;\n"
                    "  assign data_o = (state == TOKEN) && data_i;\n"
                    "endmodule\n"
                ).encode("ascii")
                _source_set, _catalog, graph = self._temporary_graph(
                    root, source, "t081_text"
                )
                token = self._enum(graph, "TOKEN")
                self.assertEqual(
                    (token.support, token.reason),
                    ("unsupported", "enum_lexical_coverage_incomplete"),
                )
                record = next(
                    record
                    for record in self._mapping_for(graph).records
                    if record.symbol_id == token.symbol_id
                )
                self.assertEqual(
                    (record.action, record.reason),
                    ("unsupported", "enum_lexical_coverage_incomplete"),
                )

    def test_same_name_in_two_scopes_is_not_name_only_merged(self):
        source = b"""module t081_scope_a (input logic data_i, output logic data_o);
  typedef enum logic { DUP } a_e;
  a_e state;
  always_comb state = DUP;
  assign data_o = (state == DUP) && data_i;
endmodule

module t081_scope_b (input logic data_i, output logic data_o);
  typedef enum logic { DUP } b_e;
  b_e state;
  always_comb state = DUP;
  assign data_o = (state == DUP) && data_i;
endmodule

module t081_scope_top (input logic data_i, output logic data_o);
  logic a_o;
  logic b_o;
  t081_scope_a u_a (.data_i(data_i), .data_o(a_o));
  t081_scope_b u_b (.data_i(data_i), .data_o(b_o));
  assign data_o = a_o ^ b_o;
endmodule
"""
        with tempfile.TemporaryDirectory(prefix="t081-scopes-") as temporary:
            root = Path(temporary)
            _source_set, _catalog, graph = self._temporary_graph(
                root, source, "t081_scope_top"
            )
            records = [
                symbol
                for symbol in graph.symbols
                if symbol.category == "enum_values" and symbol.name == "DUP"
            ]
            self.assertEqual(len(records), 2)
            self.assertEqual(len({record.owner_module for record in records}), 2)
            self.assertTrue(
                all(
                    record.support == "unsupported"
                    and record.reason == "enum_lexical_coverage_incomplete"
                    for record in records
                )
            )
            decisions = {
                record.symbol_id: record
                for record in self._mapping_for(graph).records
                if record.category == "enum_values"
            }
            self.assertEqual(set(decisions), {record.symbol_id for record in records})
            self.assertTrue(
                all(record.action == "unsupported" for record in decisions.values())
            )

    def test_non_enum_record_is_unchanged_and_duplicate_audit_remains(self):
        _fixture_source_set, fixture_catalog, fixture_graph = self._catalog_graph()
        gap = self._enum(fixture_graph, "MODE_GAP", 110)
        preserved = replace(
            gap,
            support="preserved",
            reason="existing_preserved_reason",
        )
        unsupported = replace(
            gap,
            support="unsupported",
            reason="existing_unsupported_reason",
        )
        self.assertEqual(
            symbol_graph_module._apply_enum_lexical_completeness_firewall(
                fixture_catalog, [preserved]
            ),
            [preserved],
        )
        self.assertEqual(
            symbol_graph_module._apply_enum_lexical_completeness_firewall(
                fixture_catalog, [unsupported]
            ),
            [unsupported],
        )

        source = b"""module t081_non_enum (input logic data_i, output logic data_o);
  logic TOKEN;
  // TOKEN
  typedef enum logic { VALUE_OK } value_e;
  value_e state;
  always_comb begin
    TOKEN = data_i;
    state = VALUE_OK;
  end
  assign data_o = TOKEN && (state == VALUE_OK);
endmodule
"""
        with tempfile.TemporaryDirectory(prefix="t081-non-enum-") as temporary:
            root = Path(temporary)
            _source_set, catalog, graph = self._temporary_graph(
                root, source, "t081_non_enum"
            )
            token = next(
                symbol
                for symbol in graph.symbols
                if symbol.category == "signals" and symbol.name == "TOKEN"
            )
            self.assertEqual((token.support, token.reason), ("eligible", None))
            self.assertEqual(
                symbol_graph_module._apply_enum_lexical_completeness_firewall(
                    catalog, [token]
                ),
                [token],
            )
            duplicate = replace(token, symbol_id="symbol:test:duplicate")
            with self.assertRaises(SymbolGraphError) as raised:
                symbol_graph_module._collect_extended_symbols(
                    catalog, [token, duplicate]
                )
            self.assertEqual(raised.exception.code, "SYMBOL_GRAPH_RANGE_CONFLICT")


if __name__ == "__main__":
    unittest.main()
