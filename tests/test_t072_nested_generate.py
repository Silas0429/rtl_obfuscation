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

from rtl_obfuscator.category_registry_vnext import CANONICAL_CATEGORIES, MODULE_ABI_CATEGORIES
from rtl_obfuscator.mapping_vnext import build_mapping_vnext
from rtl_obfuscator.rewrite_policy import build_rewrite_policy
from rtl_obfuscator.rewrite_vnext import restore_gate_vnext, write_gate_vnext
from rtl_obfuscator.source_catalog import build_source_catalog
from rtl_obfuscator.source_set import from_filelist
from rtl_obfuscator.symbol_graph import build_symbol_graph


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "t072_nested_generate"


def _deterministic_factory(
    symbol_id: str, name_length: int, unavailable: frozenset[str]
) -> str:
    del unavailable
    return "n" + hashlib.sha256(symbol_id.encode("utf-8")).hexdigest()[: name_length - 1]


class T072NestedGenerateTests(unittest.TestCase):
    @staticmethod
    def _source_set():
        return from_filelist(
            filelist=FIXTURE_ROOT / "design.f",
            source_root=FIXTURE_ROOT,
            top="t072_top",
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
            "tests/fixtures/t072_nested_generate/design.f",
            "--gold-root",
            "tests/fixtures/t072_nested_generate",
            "--gate-filelist",
            str(gate_dir / "design.f"),
            "--gate-root",
            str(gate_dir),
            "--top",
            "t072_top",
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
            "rtl_obfuscator.source_catalog._compile_view",
            side_effect=AssertionError("T072 graph rebuilt a semantic view"),
        ):
            graph = build_symbol_graph(catalog)
        self.assertIs(graph.source_catalog, catalog)

    def test_graph_has_frozen_counts(self):
        _source_set, _catalog, graph = self._catalog_graph()
        self.assertEqual(
            graph.to_report()["range_audit"],
            {"symbols": 26, "declarations": 26, "occurrences": 33, "total_ranges": 59},
        )

    def test_nested_span_quarantines_symbols_and_preserves_genvar_identity(self):
        _source_set, _catalog, graph = self._catalog_graph()
        nested = [
            symbol
            for symbol in graph.symbols
            if symbol.reason == "owner_contains_nested_generate"
        ]
        self.assertEqual(len(nested), 9)
        self.assertTrue(all(symbol.support == "unsupported" for symbol in nested))
        self.assertEqual(
            {(symbol.category, symbol.name) for symbol in nested},
            {
                ("modules", "t072_nested_owner"),
                ("ports", "data_i"),
                ("ports", "data_o"),
                ("signals", "owner_passthrough"),
                ("signals", "lane_nested"),
                ("genvars", "i"),
                ("generate_blocks", "g_outer"),
                ("generate_blocks", "g_inner"),
            },
        )
        genvars = [symbol for symbol in nested if symbol.category == "genvars"]
        self.assertEqual(len(genvars), 2)
        self.assertEqual(len({symbol.symbol_id for symbol in genvars}), 2)
        self.assertEqual(
            {(symbol.declaration.file, symbol.declaration.start, symbol.declaration.end)
             for symbol in genvars},
            {
                ("rtl/nested_and_same.sv", 125, 126),
                ("rtl/nested_and_same.sv", 180, 181),
            },
        )
        self.assertTrue(all(not symbol.occurrences for symbol in genvars))
        blocks = [symbol for symbol in nested if symbol.category == "generate_blocks"]
        self.assertEqual({symbol.name for symbol in blocks}, {"g_outer", "g_inner"})
        self.assertTrue(all(
            symbol.reason == "owner_contains_nested_generate" for symbol in blocks
        ))

    def test_siblings_and_selected_top_keep_existing_classification(self):
        _source_set, catalog, graph = self._catalog_graph()
        owners = {module.name: module.owner_id for module in catalog.modules}
        for module_name in ("t072_same_file_sibling", "t072_other_sibling"):
            symbols = [
                symbol for symbol in graph.symbols
                if symbol.owner_module == owners[module_name]
            ]
            self.assertEqual(len(symbols), 4)
            self.assertTrue(all(symbol.support == "eligible" for symbol in symbols))
            self.assertTrue(all(symbol.reason is None for symbol in symbols))
        top_symbols = [symbol for symbol in graph.symbols if symbol.owner_module == owners["t072_top"]]
        self.assertEqual(len(top_symbols), 9)
        top_boundary = [symbol for symbol in top_symbols if symbol.abi == "top_boundary"]
        self.assertEqual({symbol.category for symbol in top_boundary}, {"modules", "ports"})
        self.assertTrue(all(
            symbol.support == "preserved" and symbol.reason == "selected_top_boundary"
            for symbol in top_boundary
        ))
        self.assertTrue(all(
            symbol.support == "eligible"
            for symbol in top_symbols if symbol not in top_boundary
        ))

    def test_mapping_and_actual_edits_are_symbol_id_auditable(self):
        mapping = self._mapping()
        self.assertEqual(
            mapping.to_report()["summary"],
            {"total": 26, "rename": 14, "preserve": 3, "unsupported": 9},
        )
        graph = mapping.rewrite_policy.symbol_graph
        symbols = {symbol.symbol_id: symbol for symbol in graph.symbols}
        with tempfile.TemporaryDirectory(prefix="t072-edits-") as temporary:
            execution = write_gate_vnext(mapping, output_dir=Path(temporary) / "gate")
            self.assertEqual(len(execution.edits), 34)
            counts = {"nested": 0, "same": 0, "other": 0, "top": 0}
            owners = {
                module.name: module.owner_id
                for module in graph.source_catalog.modules
            }
            for edit in execution.edits:
                symbol = symbols[edit.symbol_id]
                if symbol.reason == "owner_contains_nested_generate":
                    counts["nested"] += 1
                elif symbol.owner_module == owners["t072_same_file_sibling"]:
                    counts["same"] += 1
                elif symbol.owner_module == owners["t072_other_sibling"]:
                    counts["other"] += 1
                elif symbol.owner_module == owners["t072_top"]:
                    counts["top"] += 1
                else:
                    self.fail(f"unclassified actual edit: {edit.symbol_id}")
            self.assertEqual(counts, {"nested": 0, "same": 11, "other": 11, "top": 12})

    def test_actual_gate_strict_compile_and_restore_are_byte_identical(self):
        mapping = self._mapping()
        source_set = mapping.rewrite_policy.symbol_graph.source_catalog.source_set
        physical_files = self._physical_files(source_set)
        gold = {file: (FIXTURE_ROOT / file).read_bytes() for file in physical_files}
        with tempfile.TemporaryDirectory(prefix="t072-gate-") as temporary:
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
        with tempfile.TemporaryDirectory(prefix="t072-formal-positive-") as temporary:
            gate_dir = Path(temporary) / "gate"
            execution = write_gate_vnext(mapping, output_dir=gate_dir)
            self.assertEqual(len(execution.edits), 34)
            result, command = self._formal(gate_dir)
            print(f"T072_FORMAL_GATE {gate_dir}")
            print(f"T072_FORMAL_COMMAND {shlex.join(command)}")
            print(f"T072_FORMAL_EXIT {result.returncode}")
            print(f"T072_FORMAL_JSON {result.stdout.strip()}")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(
                json.loads(result.stdout.strip().splitlines()[-1])["formal_equivalence"],
                "pass",
            )

    def test_unique_functional_negative_marker_strict_compiles_and_formal_fails(self):
        mapping = self._mapping()
        source_set = mapping.rewrite_policy.symbol_graph.source_catalog.source_set
        with tempfile.TemporaryDirectory(prefix="t072-formal-negative-") as temporary:
            root = Path(temporary)
            gate_dir = root / "gate"
            write_gate_vnext(mapping, output_dir=gate_dir)
            negative_dir = root / "negative"
            shutil.copytree(gate_dir, negative_dir)
            top = negative_dir / "rtl/top.sv"
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
            key_output = "\n".join(
                line
                for line in combined_output.splitlines()
                if "unproven" in line.lower() or "equiv_status -assert" in line.lower()
            )
            print(f"T072_FORMAL_NEGATIVE_GATE {negative_dir}")
            print(f"T072_FORMAL_NEGATIVE_COMMAND {shlex.join(command)}")
            print(f"T072_FORMAL_NEGATIVE_EXIT {result.returncode}")
            print(
                "T072_FORMAL_NEGATIVE_COMPILE "
                + json.dumps(
                    build_source_catalog(negative_set).to_report()["compile"],
                    sort_keys=True,
                )
            )
            print(f"T072_FORMAL_NEGATIVE_OUTPUT {key_output}")
            combined = combined_output.lower()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unproven", combined)
            self.assertIn("equiv_status -assert", combined)


if __name__ == "__main__":
    unittest.main()
