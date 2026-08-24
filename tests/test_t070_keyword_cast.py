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

from rtl_obfuscator import source_catalog as source_catalog_module
from rtl_obfuscator.category_registry_vnext import (
    CANONICAL_CATEGORIES,
    MODULE_ABI_CATEGORIES,
)
from rtl_obfuscator.mapping_vnext import MappingVNext, build_mapping_vnext
from rtl_obfuscator.rewrite_policy import build_rewrite_policy
from rtl_obfuscator.rewrite_vnext import restore_gate_vnext, write_gate_vnext
from rtl_obfuscator.source_catalog import build_source_catalog
from rtl_obfuscator.source_set import from_filelist
from rtl_obfuscator.symbol_graph import SymbolGraphError, build_symbol_graph


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "t070_keyword_cast"
FILELIST = FIXTURE_ROOT / "design.f"


def _deterministic_factory(
    symbol_id: str, name_length: int, unavailable: frozenset[str]
) -> str:
    del unavailable
    return "n" + hashlib.sha256(symbol_id.encode("utf-8")).hexdigest()[: name_length - 1]


class T070BuiltinKeywordCastTests(unittest.TestCase):
    def _source_set(self, *, source_root: Path = FIXTURE_ROOT):
        return from_filelist(
            filelist=source_root / "design.f",
            source_root=source_root,
            top="t070_keyword_cast_top",
        )

    def _catalog(self, *, source_root: Path = FIXTURE_ROOT):
        return build_source_catalog(self._source_set(source_root=source_root))

    def _graph(self):
        return build_symbol_graph(self._catalog())

    def _mapping(self) -> MappingVNext:
        graph = self._graph()
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
    def _formal(gate_dir: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                "scripts/formal_equivalence.py",
                "--gold-filelist",
                str(FILELIST),
                "--gold-root",
                str(FIXTURE_ROOT),
                "--gate-filelist",
                str(gate_dir / "design.f"),
                "--gate-root",
                str(gate_dir),
                "--top",
                "t070_keyword_cast_top",
                "--seq",
                "5",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=180,
        )

    def test_catalog_top_overlay_and_graph_reuse_compiled_view(self):
        catalog = self._catalog()
        with mock.patch.object(
            source_catalog_module,
            "_compile_view",
            side_effect=AssertionError("T070 graph rebuilt semantic view"),
        ):
            build_symbol_graph(catalog)
        self.assertEqual(
            catalog.to_report()["compile"],
            {
                "catalog": {"parse_errors": 0, "semantic_errors": 0},
                "top_overlay": {"parse_errors": 0, "semantic_errors": 0},
            },
        )

    def test_graph_counts_and_keyword_ranges_have_no_symbol_owner(self):
        graph = self._graph()
        report = graph.to_report()
        self.assertEqual(
            (
                report["range_audit"]["symbols"],
                report["range_audit"]["declarations"],
                report["range_audit"]["occurrences"],
                report["range_audit"]["total_ranges"],
            ),
            (12, 12, 21, 33),
        )
        keyword_ranges = {
            ("rtl/child.sv", 291, 297),
            ("rtl/child.sv", 338, 346),
        }
        owned_ranges = {
            (source_range.file, source_range.start, source_range.end)
            for symbol in graph.symbols
            for source_range in (symbol.declaration,)
            + tuple(occurrence.source_range for occurrence in symbol.occurrences)
        }
        self.assertTrue(keyword_ranges.isdisjoint(owned_ranges))
        self.assertEqual(
            sum(
                1
                for symbol in graph.symbols
                for occurrence in symbol.occurrences
                if occurrence.source_range.file == "rtl/child.sv"
                and occurrence.source_range.start in {291, 338}
            ),
            0,
        )

    def test_typedef_cast_remains_exactly_bound_to_byte_t(self):
        graph = self._graph()
        byte_t = next(
            symbol
            for symbol in graph.symbols
            if symbol.category == "typedefs" and symbol.name == "byte_t"
        )
        self.assertEqual(
            (byte_t.declaration.file, byte_t.declaration.start, byte_t.declaration.end),
            ("rtl/child.sv", 121, 127),
        )
        occurrences = {
            (
                occurrence.source_range.file,
                occurrence.source_range.start,
                occurrence.source_range.end,
                occurrence.provenance,
            )
            for occurrence in byte_t.occurrences
        }
        self.assertEqual(len(occurrences), 4)
        self.assertEqual(
            {(file, start) for file, start, _end, _provenance in occurrences},
            {
                ("rtl/child.sv", 134),
                ("rtl/child.sv", 158),
                ("rtl/child.sv", 183),
                ("rtl/child.sv", 251),
            },
        )
        self.assertEqual(
            [
                provenance
                for _file, start, _end, provenance in occurrences
                if start == 251
            ],
            ["semantic_cast_type"],
        )

    def test_syntaxless_implicit_typealias_conversion_has_no_source_occurrence(self):
        source_set = from_filelist(
            filelist=FIXTURE_ROOT / "invalid_nonkeyword.f",
            source_root=FIXTURE_ROOT,
            top="t070_invalid_nonkeyword",
        )
        catalog = build_source_catalog(source_set)
        graph = build_symbol_graph(catalog)
        byte_t = next(
            symbol
            for symbol in graph.symbols
            if symbol.category == "typedefs" and symbol.name == "byte_t"
        )
        self.assertNotIn(
            "semantic_cast_type",
            [occurrence.provenance for occurrence in byte_t.occurrences],
        )

    def test_mapping_summary_and_keyword_casts_have_no_edits(self):
        mapping = self._mapping()
        self.assertEqual(
            mapping.to_report()["summary"],
            {"total": 12, "rename": 9, "preserve": 3, "unsupported": 0},
        )
        self.assertEqual(
            len([record for record in mapping.records if record.action == "rename"])
            + sum(
                len(record.occurrences)
                for record in mapping.records
                if record.action == "rename"
            ),
            28,
        )
        self.assertFalse(
            any(
                occurrence.source_range.file == "rtl/child.sv"
                and occurrence.source_range.start in {291, 338}
                for record in mapping.records
                for occurrence in record.occurrences
            )
        )

    def test_actual_gate_strict_compile_and_restore_are_byte_identical(self):
        mapping = self._mapping()
        gold = {
            item.file: (FIXTURE_ROOT / item.file).read_bytes()
            for item in mapping.input_manifest
        }
        with tempfile.TemporaryDirectory(prefix="t070-gate-", dir="/private/tmp") as temporary:
            root = Path(temporary)
            gate_dir = root / "gate"
            execution = write_gate_vnext(mapping, output_dir=gate_dir)
            self.assertEqual(len(execution.gate_manifest), 2)
            self.assertEqual(len(execution.edits), 28)
            self.assertEqual(execution.compile_evidence.catalog_parse_errors, 0)
            self.assertEqual(execution.compile_evidence.catalog_semantic_errors, 0)
            self.assertEqual(execution.compile_evidence.top_overlay_parse_errors, 0)
            self.assertEqual(execution.compile_evidence.top_overlay_semantic_errors, 0)
            self.assertFalse(
                any(
                    edit.source_range.file == "rtl/child.sv"
                    and edit.source_range.start in {291, 338}
                    for edit in execution.edits
                )
            )
            restored = restore_gate_vnext(
                execution,
                gate_dir=gate_dir,
                output_dir=root / "restored",
            )
            self.assertEqual(restored.restored_manifest, mapping.input_manifest)
            self.assertTrue(restored.to_report()["summary"]["byte_identical"])
            self.assertEqual(
                gold,
                {
                    item.file: (root / "restored" / item.file).read_bytes()
                    for item in mapping.input_manifest
                },
            )

    def test_actual_renamed_gate_passes_formal(self):
        mapping = self._mapping()
        with tempfile.TemporaryDirectory(prefix="t070-formal-", dir="/private/tmp") as temporary:
            gate_dir = Path(temporary) / "gate"
            write_gate_vnext(mapping, output_dir=gate_dir)
            result = self._formal(gate_dir)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            payload = json.loads(result.stdout.strip().splitlines()[-1])
            self.assertEqual(payload["formal_equivalence"], "pass")
            self.assertEqual(payload["top"], "t070_keyword_cast_top")
            self.assertEqual(payload["seq"], 5)
            print(f"T070_FORMAL_POSITIVE_JSON={json.dumps(payload, sort_keys=True)}")

    def test_tilde_gate_strict_compile_and_formal_negative(self):
        mapping = self._mapping()
        with tempfile.TemporaryDirectory(prefix="t070-negative-", dir="/private/tmp") as temporary:
            root = Path(temporary)
            gate_dir = root / "gate"
            write_gate_vnext(mapping, output_dir=gate_dir)
            negative_dir = root / "negative"
            shutil.copytree(gate_dir, negative_dir)
            top = negative_dir / "rtl/top.sv"
            original = top.read_bytes()
            needle = b"assign data_o = "
            self.assertEqual(original.count(needle), 1)
            position = original.index(needle) + len(needle)
            top.write_bytes(original[:position] + b"~" + original[position:])
            compile_report = build_source_catalog(
                self._source_set(source_root=negative_dir)
            ).to_report()["compile"]
            self.assertEqual(
                compile_report,
                {
                    "catalog": {"parse_errors": 0, "semantic_errors": 0},
                    "top_overlay": {"parse_errors": 0, "semantic_errors": 0},
                },
            )
            result = self._formal(negative_dir)
            combined = (result.stdout + result.stderr).lower()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unproven", combined)
            self.assertIn("equiv_status -assert", combined)
            print(f"T070_FORMAL_NEGATIVE_GATE={negative_dir}")
            print(f"T070_FORMAL_NEGATIVE_EXIT={result.returncode}")


if __name__ == "__main__":
    unittest.main()
