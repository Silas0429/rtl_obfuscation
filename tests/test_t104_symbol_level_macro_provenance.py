import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

from rtl_obfuscator.category_registry_vnext import CANONICAL_CATEGORIES
from rtl_obfuscator.source_catalog import build_source_catalog
from rtl_obfuscator.source_set import from_filelist
from rtl_obfuscator.symbol_graph import (
    SymbolGraphError,
    _exact_original_identifier_range,
    build_symbol_graph,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "t104_symbol_level_macro_provenance"
PUBLIC_ENCRYPT = ROOT / "rtl_encrypt.py"
PUBLIC_DECRYPT = ROOT / "rtl_decrypt.py"
FORMAL_FILES = ("rtl/t104_formal_macros.svh", "rtl/t104_formal.sv")


class T104SymbolLevelMacroProvenanceTests(unittest.TestCase):
    @staticmethod
    def _graph():
        source_set = from_filelist(
            filelist=FIXTURE_ROOT / "design.f",
            source_root=FIXTURE_ROOT,
            top="t104_top",
        )
        catalog = build_source_catalog(source_set)
        return source_set, catalog, build_symbol_graph(
            catalog, categories=CANONICAL_CATEGORIES
        )

    @staticmethod
    def _run_public(*arguments: str):
        return T104SymbolLevelMacroProvenanceTests._run_script(
            PUBLIC_ENCRYPT, *arguments
        )

    @staticmethod
    def _run_script(script: Path, *arguments: str):
        return subprocess.run(
            [sys.executable, str(script), *arguments],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )

    def test_exact_macro_identifier_rejects_all_adjacent_continuations(self):
        continuation = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_$"
        with tempfile.TemporaryDirectory(prefix="t104-exact-boundary-") as temporary:
            root = Path(temporary).resolve()
            source_path = root / "rtl.sv"
            buffer = object()
            source_set = SimpleNamespace(
                source_root=root,
                ordered_source_files=("rtl.sv",),
                included_files=(),
            )
            manager = SimpleNamespace(getFullPath=lambda _buffer: str(source_path))
            catalog = SimpleNamespace(
                source_set=source_set,
                catalog_source_manager=manager,
            )

            for byte in continuation:
                source_path.write_bytes(
                    b"module t; "
                    + bytes((byte,))
                    + b"sig; sig"
                    + bytes((byte,))
                    + b"; endmodule\n"
                )
                data = source_path.read_bytes()
                prefix = data.index(b"sig")
                suffix = data.index(b"sig", prefix + 3)
                self.assertIsNone(
                    _exact_original_identifier_range(
                        catalog,
                        SimpleNamespace(buffer=buffer, offset=prefix),
                        "sig",
                    ),
                    f"preceding continuation accepted: {byte!r}",
                )
                self.assertIsNone(
                    _exact_original_identifier_range(
                        catalog,
                        SimpleNamespace(buffer=buffer, offset=suffix),
                        "sig",
                    ),
                    f"following continuation accepted: {byte!r}",
                )

            source_path.write_bytes(b"module t; (sig); endmodule\n")
            valid = source_path.read_bytes().index(b"sig")
            self.assertIsNotNone(
                _exact_original_identifier_range(
                    catalog,
                    SimpleNamespace(buffer=buffer, offset=valid),
                    "sig",
                )
            )

    def test_compact_graph_maps_macro_arguments_and_keeps_siblings_eligible(self):
        source_set, catalog, graph = self._graph()
        self.assertEqual(
            catalog.to_report()["compile"],
            {
                "catalog": {"parse_errors": 0, "semantic_errors": 0},
                "top_overlay": {"parse_errors": 0, "semantic_errors": 0},
            },
        )
        self.assertEqual(
            tuple(source_set.compile_order),
            tuple(source_set.included_files) + tuple(source_set.ordered_source_files),
        )
        self.assertNotIn(
            "owner_contains_macro_source",
            {symbol.reason for symbol in graph.symbols},
        )
        self.assertNotIn(
            "T104_SIG_DECL",
            {symbol.name for symbol in graph.symbols},
        )

        macro_argument_symbols = {
            symbol.name: symbol
            for symbol in graph.symbols
            if any(
                occurrence.provenance == "semantic_macro_argument"
                for occurrence in symbol.occurrences
            )
        }
        self.assertTrue(
            {"macro_signal", "child_in", "bus", "data", "struct_field"}
            <= set(macro_argument_symbols)
        )
        self.assertTrue(
            all(
                symbol.support in {"eligible", "preserved"}
                for symbol in macro_argument_symbols.values()
            )
        )
        self.assertIn(
            "semantic_macro_body",
            {
                occurrence.provenance
                for symbol in graph.symbols
                for occurrence in symbol.occurrences
            },
        )
        conflict = [
            symbol
            for symbol in graph.symbols
            if symbol.name == "conflict_body_signal"
        ]
        self.assertEqual(len(conflict), 2)
        self.assertTrue(
            all(
                symbol.support == "unsupported"
                and symbol.reason == "macro_origin_conflict"
                for symbol in conflict
            )
        )
        nonexact = next(
            symbol for symbol in graph.symbols if symbol.name == "paste_signal"
        )
        self.assertEqual(nonexact.support, "unsupported")
        self.assertEqual(nonexact.reason, "macro_origin_not_exact")
        self.assertTrue(
            any(
                symbol.name == "clean_signal" and symbol.support == "eligible"
                for symbol in graph.symbols
            )
        )

    def test_generate_named_port_macro_has_provenance_and_local_conflict(self):
        _source_set, _catalog, graph = self._graph()
        generated_argument = [
            symbol
            for symbol in graph.symbols
            if symbol.category == "signals" and symbol.name == "gen_arg_signal"
        ]
        self.assertEqual(len(generated_argument), 1)
        self.assertTrue(
            any(
                occurrence.provenance == "semantic_macro_argument"
                for occurrence in generated_argument[0].occurrences
            )
        )

        generated_conflicts = [
            symbol
            for symbol in graph.symbols
            if symbol.category == "signals" and symbol.name == "gen_body_signal"
        ]
        self.assertEqual(len(generated_conflicts), 2)
        self.assertTrue(
            all(
                symbol.support == "unsupported"
                and symbol.reason == "macro_origin_conflict"
                for symbol in generated_conflicts
            )
        )

    def test_public_core_categories_gate_macro_backed_symbols(self):
        with tempfile.TemporaryDirectory(prefix="t104-core-gate-") as temporary:
            root = Path(temporary)
            gate = root / "gate"
            result = self._run_public(
                "--filelist",
                str(FIXTURE_ROOT / "design.f"),
                "--top",
                "t104_top",
                "--category",
                "signals",
                "--category",
                "ports",
                "--category",
                "interface",
                "--category",
                "struct",
                "--category",
                "union_fields",
                "--output-dir",
                str(gate),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads((gate / "mapping.json").read_text(encoding="utf-8"))
            self.assertEqual(report["summary"]["encryption_result"], "PASS_PARTIAL")
            self.assertTrue(report["summary"]["strict_compile_passed"])
            self.assertTrue(report["summary"]["restored_byte_identical"])
            records = report["mapping"]["records"]
            expected_renames = (
                ("signals", "macro_signal"),
                ("ports", "child_in"),
                ("interface_instances", "bus"),
                ("interface_ports", "data"),
                ("struct_fields", "struct_field"),
                ("union_fields", "union_field"),
            )
            records_by_key = {
                (record["category"], record["original_name"]): record
                for record in records
            }
            for key in expected_renames:
                self.assertEqual(records_by_key[key]["action"], "rename")
            macro_reasons = {
                "macro_origin_conflict",
                "macro_origin_not_exact",
            }
            for record in records:
                if record["category"] in {
                    "interfaces",
                    "modports",
                    "struct_types",
                }:
                    self.assertNotIn(record.get("reason"), macro_reasons)
            self.assertTrue(any(
                record["category"] == "interface_instances"
                and record["original_name"] == "bus"
                and record["action"] == "rename"
                for record in records
            ))
            self.assertTrue(any(
                record["category"] == "struct_fields"
                and record["original_name"] == "struct_field"
                and record["action"] == "rename"
                for record in records
            ))
            self.assertEqual(
                sorted(
                    record["reason"]
                    for record in records
                    if record["action"] == "unsupported"
                ),
                [
                    "macro_origin_conflict",
                    "macro_origin_conflict",
                    "macro_origin_conflict",
                    "macro_origin_conflict",
                    "macro_origin_not_exact",
                ],
            )

            restored = root / "restored"
            decrypt = self._run_script(
                PUBLIC_DECRYPT,
                "--map",
                str(gate / "mapping.json"),
                "--gate-dir",
                str(gate),
                "--output-dir",
                str(restored),
            )
            self.assertEqual(decrypt.returncode, 0, decrypt.stderr)
            for relative in (
                "rtl/t104_macros.svh",
                "rtl/t104_if.sv",
                "rtl/t104_struct.sv",
                "rtl/t104_child.sv",
                "rtl/t104_core.sv",
                "rtl/t104_conflict.sv",
                "rtl/t104_nonexact.sv",
                "rtl/t104_top.sv",
            ):
                self.assertEqual(
                    (restored / relative).read_bytes(),
                    (FIXTURE_ROOT / relative).read_bytes(),
                )

    def test_unmappable_macro_declaration_is_stable_graph_error(self):
        source_set = from_filelist(
            filelist=FIXTURE_ROOT / "unmappable.f",
            source_root=FIXTURE_ROOT,
        )
        catalog = build_source_catalog(source_set)
        with self.assertRaises(SymbolGraphError) as raised:
            build_symbol_graph(catalog, categories=("signals",))
        self.assertEqual(
            raised.exception.code,
            "SYMBOL_GRAPH_MACRO_DECLARATION_UNMAPPABLE",
        )
        self.assertEqual(raised.exception.file, "rtl/t104_unmappable.sv")
        self.assertNotIn(raised.exception.code, raised.exception.message)

    def test_public_unmappable_input_is_atomic_refusal(self):
        with tempfile.TemporaryDirectory(prefix="t104-unmappable-") as temporary:
            output = Path(temporary) / "gate"
            result = self._run_public(
                "--filelist",
                str(FIXTURE_ROOT / "unmappable.f"),
                "--category",
                "signals",
                "--output-dir",
                str(output),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("REFUSED_ATOMIC", result.stderr)
            self.assertFalse(output.exists())

    def test_actual_renamed_gate_formal_positive_and_functional_negative(self):
        with tempfile.TemporaryDirectory(prefix="t104-formal-") as temporary:
            root = Path(temporary)
            gate = root / "gate"
            result = self._run_public(
                "--filelist",
                str(FIXTURE_ROOT / "formal.f"),
                "--top",
                "t104_formal",
                "--category",
                "signals",
                "--output-dir",
                str(gate),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads((gate / "mapping.json").read_text())
            self.assertGreater(report["summary"]["rename"], 0)
            self.assertTrue(report["summary"]["strict_compile_passed"])
            self.assertTrue(report["summary"]["restored_byte_identical"])

            restored = root / "restored"
            decrypt = self._run_script(
                PUBLIC_DECRYPT,
                "--map",
                str(gate / "mapping.json"),
                "--gate-dir",
                str(gate),
                "--output-dir",
                str(restored),
            )
            self.assertEqual(decrypt.returncode, 0, decrypt.stderr)
            for relative in FORMAL_FILES:
                self.assertEqual(
                    (restored / relative).read_bytes(),
                    (FIXTURE_ROOT / relative).read_bytes(),
                )

            formal_command = [
                sys.executable,
                "scripts/formal_equivalence.py",
                "--gold-filelist",
                str(FIXTURE_ROOT / "formal.f"),
                "--gold-root",
                str(FIXTURE_ROOT),
                "--gate-filelist",
                str(gate / "design.f"),
                "--gate-root",
                str(gate),
                "--top",
                "t104_formal",
                "--seq",
                "5",
            ]
            positive = subprocess.run(
                formal_command,
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=180,
            )
            print(f"T104_FORMAL_POSITIVE_EXIT {positive.returncode}")
            print(f"T104_FORMAL_POSITIVE_JSON {positive.stdout.strip()}")
            self.assertEqual(positive.returncode, 0, positive.stdout + positive.stderr)
            self.assertIn('"formal_equivalence": "pass"', positive.stdout)

            negative = root / "negative"
            shutil.copytree(gate, negative)
            negative_source = negative / "rtl" / "t104_formal.sv"
            source = negative_source.read_text()
            self.assertEqual(source.count("<= "), 1)
            negative_source.write_text(source.replace("<= ", "<= ~", 1))
            negative_catalog = build_source_catalog(
                from_filelist(
                    filelist=negative / "design.f",
                    source_root=negative,
                    top="t104_formal",
                )
            )
            self.assertEqual(
                negative_catalog.to_report()["compile"]["catalog"],
                {"parse_errors": 0, "semantic_errors": 0},
            )
            negative_formal = subprocess.run(
                [
                    *formal_command[: formal_command.index("--gate-filelist")],
                    "--gate-filelist",
                    str(negative / "design.f"),
                    "--gate-root",
                    str(negative),
                    "--top",
                    "t104_formal",
                    "--seq",
                    "5",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=180,
            )
            negative_output = negative_formal.stdout + negative_formal.stderr
            print(f"T104_FORMAL_NEGATIVE_EXIT {negative_formal.returncode}")
            print(f"T104_FORMAL_NEGATIVE_OUTPUT {negative_output[-2000:]}")
            self.assertNotEqual(negative_formal.returncode, 0)
            self.assertIn("unproven", negative_output)
            self.assertIn("equiv_status -assert", negative_output)


if __name__ == "__main__":
    unittest.main()
