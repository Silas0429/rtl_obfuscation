import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from rtl_obfuscator.source_catalog import build_source_catalog
from rtl_obfuscator.source_set import from_filelist
from rtl_obfuscator.symbol_graph import build_symbol_graph


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "t100_macro_readonly_module_preserve"
PUBLIC_ENCRYPT = ROOT / "rtl_encrypt.py"
PUBLIC_DECRYPT = ROOT / "rtl_decrypt.py"
COMPILE_ORDER = (
    "rtl/t100_cell.sv",
    "rtl/t100_macro_owner.sv",
    "rtl/t100_clean.sv",
    "rtl/t100_context.sv",
    "rtl/t100_top.sv",
)
MACRO_NAMES = {
    "T100_MAKE_CELL",
    "CELL_NAME",
    "DATA_W",
    "DEPTH",
    "BE_W",
    "CELL_OUT",
    "T100_CONTEXT_PARAM",
    "T100_CONTEXT_LIMIT",
}


class T100MacroReadonlyModulePreserveTests(unittest.TestCase):
    @staticmethod
    def _source_set():
        return from_filelist(
            filelist=FIXTURE_ROOT / "design.f",
            source_root=FIXTURE_ROOT,
            top="t100_top",
        )

    @classmethod
    def _catalog_graph(cls):
        source_set = cls._source_set()
        catalog = build_source_catalog(source_set)
        return source_set, catalog, build_symbol_graph(catalog)

    @staticmethod
    def _run_public(script: Path, *arguments: str):
        return subprocess.run(
            [sys.executable, str(script), *arguments],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )

    def _encrypt_public(self, gate_dir: Path):
        result = self._run_public(
            PUBLIC_ENCRYPT,
            "--filelist",
            str(FIXTURE_ROOT / "design.f"),
            "--top",
            "t100_top",
            "--category",
            "signals",
            "--output-dir",
            str(gate_dir),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        report = json.loads((gate_dir / "mapping.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["summary"], report["summary"])
        return result, gate_dir, payload, report

    @staticmethod
    def _formal(gate_dir: Path):
        command = [
            sys.executable,
            "scripts/formal_equivalence.py",
            "--gold-filelist",
            "tests/fixtures/t100_macro_readonly_module_preserve/design.f",
            "--gold-root",
            "tests/fixtures/t100_macro_readonly_module_preserve",
            "--gate-filelist",
            str(gate_dir / "design.f"),
            "--gate-root",
            str(gate_dir),
            "--top",
            "t100_top",
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

    def test_catalog_graph_and_macro_readonly_boundary(self):
        source_set, catalog, graph = self._catalog_graph()
        self.assertEqual(
            catalog.to_report()["compile"],
            {
                "catalog": {"parse_errors": 0, "semantic_errors": 0},
                "top_overlay": {"parse_errors": 0, "semantic_errors": 0},
            },
        )
        self.assertEqual(tuple(source_set.compile_order), tuple(source_set.ordered_source_files))
        names = {symbol.name for symbol in graph.symbols}
        for macro_name in (
            *MACRO_NAMES,
        ):
            self.assertNotIn(macro_name, names)
        self.assertIs(graph.source_catalog, catalog)

    def test_macro_owner_is_atomically_preserved_and_sibling_is_eligible(self):
        _source_set, catalog, graph = self._catalog_graph()
        owners = {module.name: module.owner_id for module in catalog.modules}
        macro_symbols = [
            symbol
            for symbol in graph.symbols
            if symbol.owner_module == owners["t100_macro_owner"]
        ]
        self.assertTrue(macro_symbols)
        self.assertTrue(all(symbol.support == "eligible" and symbol.reason is None for symbol in macro_symbols))
        target_symbols = [
            symbol
            for symbol in graph.symbols
            if symbol.owner_module == owners["t100_cell"]
        ]
        self.assertTrue(target_symbols)
        self.assertTrue(all(symbol.support == "eligible" and symbol.reason is None for symbol in target_symbols))
        clean_symbols = [
            symbol
            for symbol in graph.symbols
            if symbol.owner_module == owners["t100_clean"]
        ]
        self.assertTrue(clean_symbols)
        self.assertTrue(any(
            symbol.support == "eligible" and symbol.reason is None
            for symbol in clean_symbols
        ))
        macro_source = (FIXTURE_ROOT / "rtl" / "t100_macro_owner.sv").read_bytes()
        call_start = macro_source.index(b"`T100_MAKE_CELL")
        argument_start = macro_source.index(b"cell_data", call_start)
        cell_data = next(symbol for symbol in graph.symbols if symbol.name == "cell_data")
        self.assertTrue(any(
            occurrence.provenance == "semantic_macro_argument"
            and occurrence.source_range.file == "rtl/t100_macro_owner.sv"
            and occurrence.source_range.start <= argument_start < occurrence.source_range.end
            for occurrence in cell_data.occurrences
        ))
        self.assertNotIn("owner_contains_macro_source", {symbol.reason for symbol in graph.symbols})

    def test_public_signals_gate_preserves_macro_and_renames_clean(self):
        with tempfile.TemporaryDirectory(prefix="t100-public-signals-") as temporary:
            _result, gate_dir, payload, report = self._encrypt_public(Path(temporary) / "gate")
            self.assertGreater(payload["action_counts"]["rename"], 0)
            self.assertTrue(report["summary"]["strict_compile_passed"])
            self.assertTrue(report["summary"]["restored_byte_identical"])
            self.assertEqual(
                (gate_dir / "design.f").read_text(encoding="utf-8"),
                "".join(f"{path}\n" for path in COMPILE_ORDER),
            )
            records = report["mapping"]["records"]
            mapping_names = {
                name
                for record in records
                for name in (record["original_name"], record["renamed_name"])
                if name is not None
            }
            self.assertTrue(mapping_names.isdisjoint(MACRO_NAMES))
            self.assertNotEqual(
                (gate_dir / "rtl" / "t100_macro_owner.sv").read_bytes(),
                (FIXTURE_ROOT / "rtl" / "t100_macro_owner.sv").read_bytes(),
            )
            for relative in COMPILE_ORDER:
                gold_text = (FIXTURE_ROOT / relative).read_text(encoding="utf-8")
                gate_text = (gate_dir / relative).read_text(encoding="utf-8")
                for macro_name in MACRO_NAMES:
                    if macro_name in gold_text:
                        self.assertIn(macro_name, gate_text)
            self.assertNotEqual(
                (gate_dir / "rtl" / "t100_clean.sv").read_bytes(),
                (FIXTURE_ROOT / "rtl" / "t100_clean.sv").read_bytes(),
            )

    def test_public_gate_restore_is_byte_identical(self):
        with tempfile.TemporaryDirectory(prefix="t100-public-restore-") as temporary:
            root = Path(temporary)
            _result, gate_dir, _payload, _report = self._encrypt_public(root / "gate")
            restored = root / "restored"
            result = self._run_public(
                PUBLIC_DECRYPT,
                "--map",
                str(gate_dir / "mapping.json"),
                "--gate-dir",
                str(gate_dir),
                "--output-dir",
                str(restored),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            for relative in COMPILE_ORDER:
                self.assertEqual(
                    (restored / relative).read_bytes(),
                    (FIXTURE_ROOT / relative).read_bytes(),
                )

    def test_public_signals_actual_gate_formal_positive(self):
        with tempfile.TemporaryDirectory(prefix="t100-public-formal-positive-") as temporary:
            _result, gate_dir, _payload, _report = self._encrypt_public(Path(temporary) / "gate")
            result, command = self._formal(gate_dir)
            print(f"T100_FORMAL_GATE {gate_dir}")
            print(f"T100_FORMAL_COMMAND {' '.join(command)}")
            print(f"T100_FORMAL_EXIT {result.returncode}")
            print(f"T100_FORMAL_JSON {result.stdout.strip()}")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('"formal_equivalence": "pass"', result.stdout)

    def test_public_signals_fixed_function_negative_strict_compiles_and_formal_fails(self):
        with tempfile.TemporaryDirectory(prefix="t100-formal-negative-") as temporary:
            root = Path(temporary)
            _result, positive_dir, _payload, _report = self._encrypt_public(root / "positive")
            negative_dir = root / "negative"
            shutil.copytree(positive_dir, negative_dir)
            top_file = negative_dir / "rtl" / "t100_top.sv"
            source = top_file.read_text()
            marker = "assign data_o = "
            self.assertEqual(source.count(marker), 1)
            top_file.write_text(source.replace(marker, "assign data_o = ~", 1))
            negative_execution = build_source_catalog(
                from_filelist(
                    filelist=negative_dir / "design.f",
                    top="t100_top",
                )
            )
            self.assertEqual(
                negative_execution.to_report()["compile"],
                {
                    "catalog": {"parse_errors": 0, "semantic_errors": 0},
                    "top_overlay": {"parse_errors": 0, "semantic_errors": 0},
                },
            )
            result, command = self._formal(negative_dir)
            print(f"T100_FORMAL_NEGATIVE_GATE {negative_dir}")
            print(f"T100_FORMAL_NEGATIVE_COMMAND {' '.join(command)}")
            print(f"T100_FORMAL_NEGATIVE_EXIT {result.returncode}")
            print(f"T100_FORMAL_NEGATIVE_OUTPUT {result.stdout[-2000:]}")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unproven", result.stdout + result.stderr)
            self.assertIn("equiv_status -assert", result.stdout + result.stderr)
