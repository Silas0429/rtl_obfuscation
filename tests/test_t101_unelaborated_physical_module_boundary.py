import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import pyslang

from rtl_obfuscator.source_catalog import build_source_catalog
from rtl_obfuscator.source_set import from_filelist
from rtl_obfuscator.symbol_graph import _physical_module_spans, build_symbol_graph


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "t101_unelaborated_physical_module_boundary"
PUBLIC_ENCRYPT = ROOT / "rtl_encrypt.py"
PUBLIC_DECRYPT = ROOT / "rtl_decrypt.py"
COMPILE_ORDER = (
    "rtl/t101_candidate.sv",
    "rtl/t101_chosen.sv",
    "rtl/t101_selector.sv",
    "rtl/t101_macro_owner.sv",
    "rtl/t101_clean.sv",
    "rtl/t101_top.sv",
)
CANDIDATE_FILE = "rtl/t101_candidate.sv"


class T101UnelaboratedPhysicalModuleBoundaryTests(unittest.TestCase):
    @staticmethod
    def _source_set():
        return from_filelist(
            filelist=FIXTURE_ROOT / "design.f",
            source_root=FIXTURE_ROOT,
            top="t101_top",
        )

    @classmethod
    def _catalog_graph(cls):
        source_set = cls._source_set()
        catalog = build_source_catalog(source_set)
        return source_set, catalog, build_symbol_graph(catalog)

    @staticmethod
    def _physical_module_names(catalog):
        names = set()
        for syntax_tree in catalog.catalog_compilation.getSyntaxTrees():
            nodes = []
            syntax_tree.root.visit(nodes.append)
            names.update(
                node.header.name.rawText
                for node in nodes
                if isinstance(node, pyslang.syntax.ModuleDeclarationSyntax)
                and node.header.name.rawText
            )
        return names

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
            "t101_top",
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
            "tests/fixtures/t101_unelaborated_physical_module_boundary/design.f",
            "--gold-root",
            "tests/fixtures/t101_unelaborated_physical_module_boundary",
            "--gate-filelist",
            str(gate_dir / "design.f"),
            "--gate-root",
            str(gate_dir),
            "--top",
            "t101_top",
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

    def test_catalog_and_physical_inventory_have_one_way_boundary(self):
        source_set, catalog, graph = self._catalog_graph()
        self.assertEqual(
            catalog.to_report()["compile"],
            {
                "catalog": {"parse_errors": 0, "semantic_errors": 0},
                "top_overlay": {"parse_errors": 0, "semantic_errors": 0},
            },
        )
        self.assertEqual(tuple(source_set.compile_order), COMPILE_ORDER)
        self.assertEqual(
            self._physical_module_names(catalog),
            {"t101_candidate", "t101_chosen", "t101_selector", "t101_macro_owner", "t101_clean", "t101_top"},
        )
        catalog_names = {module.name for module in catalog.modules}
        self.assertNotIn("t101_candidate", catalog_names)
        self.assertEqual(
            catalog_names,
            {"t101_chosen", "t101_selector", "t101_macro_owner", "t101_clean", "t101_top"},
        )
        spans = _physical_module_spans(catalog)
        self.assertEqual({span.owner_id for span in spans}, {module.owner_id for module in catalog.modules})
        self.assertTrue(graph.symbols)
        self.assertNotIn("t101_candidate", {symbol.name for symbol in graph.symbols})
        graph_declaration_files = {symbol.declaration.file for symbol in graph.symbols}
        graph_occurrence_files = {
            occurrence.source_range.file
            for symbol in graph.symbols
            for occurrence in symbol.occurrences
        }
        self.assertNotIn(CANDIDATE_FILE, graph_declaration_files)
        self.assertNotIn(CANDIDATE_FILE, graph_occurrence_files)

    def test_macro_owner_and_clean_sibling_keep_existing_boundaries(self):
        _source_set, catalog, graph = self._catalog_graph()
        owners = {module.name: module.owner_id for module in catalog.modules}
        macro_symbols = [symbol for symbol in graph.symbols if symbol.owner_module == owners["t101_macro_owner"]]
        self.assertTrue(macro_symbols)
        self.assertTrue(all(symbol.support == "eligible" and symbol.reason is None for symbol in macro_symbols))
        self.assertNotIn("owner_contains_macro_source", {symbol.reason for symbol in graph.symbols})
        clean_symbols = [symbol for symbol in graph.symbols if symbol.owner_module == owners["t101_clean"]]
        self.assertTrue(clean_symbols)
        self.assertTrue(any(symbol.support == "eligible" and symbol.reason is None for symbol in clean_symbols))

    def test_public_gate_preserves_candidate_and_macro_and_renames_clean(self):
        with tempfile.TemporaryDirectory(prefix="t101-public-signals-") as temporary:
            _result, gate_dir, payload, report = self._encrypt_public(Path(temporary) / "gate")
            self.assertGreater(payload["action_counts"]["rename"], 0)
            self.assertTrue(report["summary"]["strict_compile_passed"])
            self.assertTrue(report["summary"]["restored_byte_identical"])
            self.assertEqual(
                (gate_dir / "design.f").read_text(encoding="utf-8"),
                "".join(f"{path}\n" for path in COMPILE_ORDER),
            )
            records = report["mapping"]["records"]
            mapping_declaration_files = {
                record["declaration"]["file"] for record in records
            }
            mapping_occurrence_files = {
                occurrence["source_range"]["file"]
                for record in records
                for occurrence in record["occurrences"]
            }
            self.assertNotIn(CANDIDATE_FILE, mapping_declaration_files)
            self.assertNotIn(CANDIDATE_FILE, mapping_occurrence_files)
            self.assertEqual(
                (gate_dir / "rtl" / "t101_candidate.sv").read_bytes(),
                (FIXTURE_ROOT / "rtl" / "t101_candidate.sv").read_bytes(),
            )
            self.assertNotEqual(
                (gate_dir / "rtl" / "t101_macro_owner.sv").read_bytes(),
                (FIXTURE_ROOT / "rtl" / "t101_macro_owner.sv").read_bytes(),
            )
            self.assertNotEqual(
                (gate_dir / "rtl" / "t101_clean.sv").read_bytes(),
                (FIXTURE_ROOT / "rtl" / "t101_clean.sv").read_bytes(),
            )
            manifest_files = {
                item["file"]
                for item in report["mapping_execution"]["input_manifest"]
            }
            self.assertIn("rtl/t101_candidate.sv", manifest_files)

    def test_public_decrypt_restores_all_six_physical_files(self):
        with tempfile.TemporaryDirectory(prefix="t101-public-restore-") as temporary:
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

    def test_public_actual_gate_formal_positive(self):
        with tempfile.TemporaryDirectory(prefix="t101-public-formal-positive-") as temporary:
            _result, gate_dir, _payload, _report = self._encrypt_public(Path(temporary) / "gate")
            result, command = self._formal(gate_dir)
            print(f"T101_FORMAL_GATE {gate_dir}")
            print(f"T101_FORMAL_COMMAND {' '.join(command)}")
            print(f"T101_FORMAL_EXIT {result.returncode}")
            print(f"T101_FORMAL_JSON {result.stdout.strip()}")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('"formal_equivalence": "pass"', result.stdout)

    def test_public_fixed_function_negative_strict_compiles_and_formal_fails(self):
        with tempfile.TemporaryDirectory(prefix="t101-formal-negative-") as temporary:
            root = Path(temporary)
            _result, positive_dir, _payload, _report = self._encrypt_public(root / "positive")
            negative_dir = root / "negative"
            shutil.copytree(positive_dir, negative_dir)
            top_file = negative_dir / "rtl" / "t101_top.sv"
            source = top_file.read_text()
            marker = "assign data_o = "
            self.assertEqual(source.count(marker), 1)
            top_file.write_text(source.replace(marker, "assign data_o = ~", 1))
            negative_catalog = build_source_catalog(
                from_filelist(filelist=negative_dir / "design.f", top="t101_top")
            )
            self.assertEqual(
                negative_catalog.to_report()["compile"],
                {
                    "catalog": {"parse_errors": 0, "semantic_errors": 0},
                    "top_overlay": {"parse_errors": 0, "semantic_errors": 0},
                },
            )
            result, command = self._formal(negative_dir)
            print(f"T101_FORMAL_NEGATIVE_GATE {negative_dir}")
            print(f"T101_FORMAL_NEGATIVE_COMMAND {' '.join(command)}")
            print(f"T101_FORMAL_NEGATIVE_EXIT {result.returncode}")
            print(f"T101_FORMAL_NEGATIVE_OUTPUT {result.stdout[-2000:]}")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unproven", result.stdout + result.stderr)
            self.assertIn("equiv_status -assert", result.stdout + result.stderr)
