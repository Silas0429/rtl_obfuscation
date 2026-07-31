from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from rtl_obfuscator.category_registry_vnext import CANONICAL_CATEGORIES, MODULE_ABI_CATEGORIES
from rtl_obfuscator.mapping_vnext import build_mapping_vnext
from rtl_obfuscator.rewrite_policy import build_rewrite_policy
from rtl_obfuscator.rewrite_vnext import restore_gate_vnext, write_gate_vnext
from rtl_obfuscator.source_catalog import SourceCatalogError, build_source_catalog
from rtl_obfuscator.source_set import from_filelist
from rtl_obfuscator.symbol_graph import SymbolGraphError, build_symbol_graph


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "t073_macro_owner"


def _deterministic_factory(
    symbol_id: str, name_length: int, unavailable: frozenset[str]
) -> str:
    del unavailable
    return "n" + hashlib.sha256(symbol_id.encode("utf-8")).hexdigest()[: name_length - 1]


class T073MacroOwnerTests(unittest.TestCase):
    @staticmethod
    def _source_set():
        return from_filelist(
            filelist=FIXTURE_ROOT / "design.f",
            source_root=FIXTURE_ROOT,
            top="t073_top",
        )

    @classmethod
    def _catalog_graph(cls):
        source_set = cls._source_set()
        catalog = build_source_catalog(source_set)
        return source_set, catalog, build_symbol_graph(catalog)

    @classmethod
    def _mapping(cls):
        source_set, catalog, graph = cls._catalog_graph()
        del source_set, catalog
        policy = build_rewrite_policy(
            graph,
            categories=CANONICAL_CATEGORIES,
            abi_categories=MODULE_ABI_CATEGORIES,
        )
        return build_mapping_vnext(
            policy,
            name_length=16,
            name_factory=_deterministic_factory,
        )

    @staticmethod
    def _physical_files(source_set):
        return tuple(dict.fromkeys((*source_set.ordered_source_files, *source_set.included_files)))

    @staticmethod
    def _formal(gate_dir):
        command = [
            sys.executable,
            "scripts/formal_equivalence.py",
            "--gold-filelist",
            "tests/fixtures/t073_macro_owner/design.f",
            "--gold-root",
            "tests/fixtures/t073_macro_owner",
            "--gate-filelist",
            str(gate_dir / "design.f"),
            "--gate-root",
            str(gate_dir),
            "--top",
            "t073_top",
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

    def test_catalog_top_overlay_and_graph_reuses_semantic_view(self):
        source_set = self._source_set()
        catalog = build_source_catalog(source_set)
        self.assertEqual(
            catalog.to_report()["compile"],
            {
                "catalog": {"parse_errors": 0, "semantic_errors": 0},
                "top_overlay": {"parse_errors": 0, "semantic_errors": 0},
            },
        )
        with mock.patch(
            "rtl_obfuscator.symbol_graph._collect_extended_symbols",
            side_effect=SymbolGraphError(
                "SYMBOL_GRAPH_UNSUPPORTED_SOURCE",
                "forced T073 context-reset failure",
            ),
        ):
            with self.assertRaises(SymbolGraphError):
                build_symbol_graph(catalog)
        with mock.patch(
            "rtl_obfuscator.source_catalog._compile_view",
            side_effect=AssertionError("T073 graph rebuilt a semantic view"),
        ):
            graph = build_symbol_graph(catalog)
        self.assertIs(graph.source_catalog, catalog)

    def test_graph_has_frozen_macro_quarantine_and_absent_macro_ranges(self):
        _source_set, catalog, graph = self._catalog_graph()
        self.assertEqual(
            graph.to_report()["range_audit"],
            {"symbols": 31, "declarations": 31, "occurrences": 41, "total_ranges": 72},
        )
        owners = {module.name: module.owner_id for module in catalog.modules}
        expected = {
            "t073_macro_target": 4,
            "t073_macro_owner": 8,
            "t073_macro_statement_owner": 5,
        }
        for name, count in expected.items():
            symbols = [symbol for symbol in graph.symbols if symbol.owner_module == owners[name]]
            self.assertEqual(len(symbols), count)
            self.assertTrue(all(
                symbol.support == "unsupported"
                and symbol.reason == "owner_contains_macro_source"
                for symbol in symbols
            ))
        self.assertNotIn("macro_state", {symbol.name for symbol in graph.symbols})
        self.assertTrue(all(
            occurrence.provenance != "semantic_hierarchy"
            or symbol.owner_module != owners["t073_macro_target"]
            for symbol in graph.symbols
            for occurrence in symbol.occurrences
        ))
        macro_lines = [
            index
            for index, line in enumerate(
                (FIXTURE_ROOT / "rtl" / "macro_design.sv").read_text().splitlines()
            )
            if "`T073_" in line
        ]
        self.assertEqual(len(macro_lines), 7)

    def test_statement_owner_and_macro_type_target_are_atomically_preserved(self):
        _source_set, catalog, graph = self._catalog_graph()
        owners = {module.name: module.owner_id for module in catalog.modules}
        for name in ("t073_macro_owner", "t073_macro_statement_owner", "t073_macro_target"):
            symbols = [symbol for symbol in graph.symbols if symbol.owner_module == owners[name]]
            self.assertTrue(symbols)
            self.assertTrue(all(symbol.reason == "owner_contains_macro_source" for symbol in symbols))
        instance = next(
            symbol
            for symbol in graph.symbols
            if symbol.owner_module == owners["t073_macro_owner"]
            and symbol.category == "instances"
            and symbol.name == "u_target"
        )
        self.assertEqual(instance.support, "unsupported")
        self.assertEqual(instance.reason, "owner_contains_macro_source")
        invalid_set = from_filelist(
            filelist=FIXTURE_ROOT / "invalid_module_name.f",
            source_root=FIXTURE_ROOT,
        )
        with self.assertRaises(SourceCatalogError) as raised:
            build_source_catalog(invalid_set)
        self.assertEqual(raised.exception.code, "CATALOG_RANGE_INVALID")
        self.assertIn("declaration is outside the SourceSet root", str(raised.exception))

    def test_sibling_and_top_classification_remains_unchanged(self):
        _source_set, catalog, graph = self._catalog_graph()
        owners = {module.name: module.owner_id for module in catalog.modules}
        sibling = [symbol for symbol in graph.symbols if symbol.owner_module == owners["t073_sibling"]]
        self.assertEqual(len(sibling), 4)
        self.assertTrue(all(symbol.support == "eligible" and symbol.reason is None for symbol in sibling))
        top = [symbol for symbol in graph.symbols if symbol.owner_module == owners["t073_top"]]
        self.assertEqual(len(top), 10)
        boundary = [symbol for symbol in top if symbol.abi == "top_boundary"]
        self.assertEqual({symbol.category for symbol in boundary}, {"modules", "ports"})
        self.assertTrue(all(symbol.support == "preserved" for symbol in boundary))
        internal = [symbol for symbol in top if symbol.abi == "internal"]
        self.assertEqual(len(internal), 6)
        self.assertTrue(all(symbol.support == "eligible" and symbol.reason is None for symbol in internal))

    def test_mapping_and_actual_edits_are_symbol_id_auditable(self):
        mapping = self._mapping()
        self.assertEqual(
            mapping.to_report()["summary"],
            {"total": 31, "rename": 10, "preserve": 4, "unsupported": 17},
        )
        graph = mapping.rewrite_policy.symbol_graph
        symbols = {symbol.symbol_id: symbol for symbol in graph.symbols}
        owners = {
            module.name: module.owner_id
            for module in graph.source_catalog.modules
        }
        with tempfile.TemporaryDirectory(prefix="t073-edits-") as temporary:
            execution = write_gate_vnext(mapping, output_dir=Path(temporary) / "gate")
            self.assertEqual(len(execution.edits), 23)
            counts = {"protected": 0, "sibling": 0, "top": 0}
            for edit in execution.edits:
                symbol = symbols[edit.symbol_id]
                self.assertNotEqual(symbol.reason, "owner_contains_macro_source")
                if symbol.owner_module == owners["t073_sibling"]:
                    counts["sibling"] += 1
                elif symbol.owner_module == owners["t073_top"]:
                    counts["top"] += 1
                else:
                    self.fail(f"unclassified actual edit: {edit.symbol_id}")
            self.assertEqual(counts, {"protected": 0, "sibling": 11, "top": 12})

    def test_actual_gate_strict_compile_and_restore_are_byte_identical(self):
        mapping = self._mapping()
        source_set = mapping.rewrite_policy.symbol_graph.source_catalog.source_set
        physical_files = self._physical_files(source_set)
        gold = {file: (FIXTURE_ROOT / file).read_bytes() for file in physical_files}
        with tempfile.TemporaryDirectory(prefix="t073-gate-") as temporary:
            root = Path(temporary)
            gate_dir = root / "gate"
            restore_dir = root / "restore"
            execution = write_gate_vnext(mapping, output_dir=gate_dir)
            self.assertEqual(
                execution.compile_evidence.catalog_parse_errors,
                0,
            )
            self.assertEqual(execution.compile_evidence.catalog_semantic_errors, 0)
            self.assertEqual(execution.compile_evidence.top_overlay_parse_errors, 0)
            self.assertEqual(execution.compile_evidence.top_overlay_semantic_errors, 0)
            restored = restore_gate_vnext(
                execution,
                gate_dir=gate_dir,
                output_dir=restore_dir,
            )
            self.assertTrue(restored.to_report()["summary"]["byte_identical"])
            self.assertEqual(
                {file: (restore_dir / file).read_bytes() for file in physical_files},
                gold,
            )

    def test_actual_renamed_gate_formal_positive(self):
        mapping = self._mapping()
        with tempfile.TemporaryDirectory(prefix="t073-formal-positive-") as temporary:
            gate_dir = Path(temporary) / "gate"
            execution = write_gate_vnext(mapping, output_dir=gate_dir)
            self.assertEqual(len(execution.edits), 23)
            result, command = self._formal(gate_dir)
            print(f"T073_FORMAL_GATE {gate_dir}")
            print(f"T073_FORMAL_COMMAND {' '.join(command)}")
            print(f"T073_FORMAL_EXIT {result.returncode}")
            print(f"T073_FORMAL_JSON {result.stdout.strip()}")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(
                json.loads(result.stdout.strip().splitlines()[-1])["formal_equivalence"],
                "pass",
            )

    def test_unique_functional_negative_marker_strict_compiles_and_formal_fails(self):
        mapping = self._mapping()
        source_set = mapping.rewrite_policy.symbol_graph.source_catalog.source_set
        with tempfile.TemporaryDirectory(prefix="t073-formal-negative-") as temporary:
            root = Path(temporary)
            gate_dir = root / "gate"
            write_gate_vnext(mapping, output_dir=gate_dir)
            negative_dir = root / "negative"
            shutil.copytree(gate_dir, negative_dir)
            top = negative_dir / "rtl" / "top.sv"
            original = top.read_bytes()
            marker = b"assign data_o = "
            self.assertEqual(original.count(marker), 1)
            position = original.index(marker) + len(marker)
            top.write_bytes(original[:position] + b"~" + original[position:])
            negative_set = replace(source_set, source_root=negative_dir.resolve())
            self.assertEqual(
                build_source_catalog(negative_set).to_report()["compile"],
                {
                    "catalog": {"parse_errors": 0, "semantic_errors": 0},
                    "top_overlay": {"parse_errors": 0, "semantic_errors": 0},
                },
            )
            result, command = self._formal(negative_dir)
            combined_output = result.stdout + result.stderr
            combined = combined_output.lower()
            print(f"T073_FORMAL_NEGATIVE_GATE {negative_dir}")
            print(f"T073_FORMAL_NEGATIVE_COMMAND {' '.join(command)}")
            print(f"T073_FORMAL_NEGATIVE_EXIT {result.returncode}")
            print(
                "T073_FORMAL_NEGATIVE_COMPILE "
                + json.dumps(build_source_catalog(negative_set).to_report()["compile"], sort_keys=True)
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unproven", combined)
            self.assertIn("equiv_status -assert", combined)


if __name__ == "__main__":
    unittest.main()
