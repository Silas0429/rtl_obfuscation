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
from rtl_obfuscator.mapping_vnext import MappingVNext, build_mapping_vnext
from rtl_obfuscator.rewrite_policy import build_rewrite_policy
from rtl_obfuscator.rewrite_vnext import restore_gate_vnext, write_gate_vnext
from rtl_obfuscator.source_catalog import build_source_catalog
from rtl_obfuscator.source_set import from_filelist
from rtl_obfuscator.symbol_graph import build_symbol_graph


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "t069_sized_cast"
FILELIST = FIXTURE_ROOT / "design.f"


def _deterministic_factory(
    symbol_id: str, name_length: int, unavailable: frozenset[str]
) -> str:
    del unavailable
    return "n" + hashlib.sha256(symbol_id.encode("utf-8")).hexdigest()[: name_length - 1]


class T069SizedCastParameterTests(unittest.TestCase):
    def _source_set(self, *, source_root: Path = FIXTURE_ROOT):
        return from_filelist(
            filelist=source_root / "design.f",
            source_root=source_root,
            top="t069_sized_cast_top",
        )

    def _catalog(self, *, source_root: Path = FIXTURE_ROOT):
        return build_source_catalog(self._source_set(source_root=source_root))

    def _graph(self):
        return build_symbol_graph(self._catalog())

    def _mapping(self) -> MappingVNext:
        graph = self._graph()
        policy = build_rewrite_policy(
            graph,
            categories=("signals", "parameters", "genvars"),
            abi_categories=("parameters",),
        )
        return build_mapping_vnext(
            policy,
            name_length=16,
            name_factory=_deterministic_factory,
        )

    @staticmethod
    def _parameters(graph):
        return [symbol for symbol in graph.symbols if symbol.category == "parameters"]

    @staticmethod
    def _parameter(graph, file: str, declaration_start: int):
        return next(
            symbol
            for symbol in T069SizedCastParameterTests._parameters(graph)
            if symbol.declaration.file == file
            and symbol.declaration.start == declaration_start
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
                "t069_sized_cast_top",
                "--seq",
                "5",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=180,
        )

    def test_fixture_catalog_and_graph_oracle_without_recompile(self):
        catalog = self._catalog()
        with mock.patch.object(
            source_catalog_module,
            "_compile_view",
            side_effect=AssertionError("T069 graph rebuilt semantic view"),
        ):
            graph = build_symbol_graph(catalog)
        report = graph.to_report()
        self.assertEqual(
            (
                report["range_audit"]["symbols"],
                report["range_audit"]["declarations"],
                report["range_audit"]["occurrences"],
                report["range_audit"]["total_ranges"],
            ),
            (20, 20, 37, 57),
        )
        self.assertEqual(
            catalog.to_report()["compile"],
            {
                "catalog": {"parse_errors": 0, "semantic_errors": 0},
                "top_overlay": {"parse_errors": 0, "semantic_errors": 0},
            },
        )

    def test_five_sized_cast_tokens_have_exact_ranges_and_declarations(self):
        graph = self._graph()
        expected = {
            ("rtl/child.sv", 93): ("WIDTH", "rtl/child.sv", 50),
            ("rtl/child.sv", 301): ("LOCAL_WIDTH", "rtl/child.sv", 202),
            ("rtl/child.sv", 365): ("WIDTH", "rtl/child.sv", 50),
            ("rtl/shadow.sv", 297): ("WIDTH", "rtl/shadow.sv", 192),
            ("rtl/shadow.sv", 354): ("WIDTH", "rtl/shadow.sv", 51),
        }
        for (file, start), (name, declaration_file, declaration_start) in expected.items():
            with self.subTest(file=file, start=start):
                symbol = self._parameter(graph, declaration_file, declaration_start)
                occurrences = [
                    occurrence
                    for occurrence in symbol.occurrences
                    if occurrence.provenance == "sized_cast_type"
                    and occurrence.source_range.file == file
                    and occurrence.source_range.start == start
                ]
                self.assertEqual(len(occurrences), 1)
                occurrence = occurrences[0]
                self.assertEqual(occurrence.source_range.end, start + len(name))
                source = (FIXTURE_ROOT / file).read_bytes()
                self.assertEqual(
                    source[occurrence.source_range.start : occurrence.source_range.end],
                    name.encode("ascii"),
                )
                self.assertEqual(symbol.declaration.file, declaration_file)
                self.assertEqual(symbol.declaration.start, declaration_start)

    def test_overridden_initializer_keeps_width_cast_occurrence(self):
        graph = self._graph()
        width = self._parameter(graph, "rtl/child.sv", 50)
        self.assertIn(
            ("rtl/child.sv", 93, 98, "sized_cast_type"),
            {
                (
                    occurrence.source_range.file,
                    occurrence.source_range.start,
                    occurrence.source_range.end,
                    occurrence.provenance,
                )
                for occurrence in width.occurrences
            },
        )
        reset = next(
            symbol
            for symbol in self._parameters(graph)
            if symbol.declaration.file == "rtl/child.sv"
            and symbol.name == "RESET_VALUE"
        )
        self.assertEqual(reset.name, "RESET_VALUE")

    def test_shadowed_width_casts_use_distinct_lexical_owners(self):
        graph = self._graph()
        inner = self._parameter(graph, "rtl/shadow.sv", 192)
        outer = self._parameter(graph, "rtl/shadow.sv", 51)
        inner_casts = {
            occurrence.source_range.start
            for occurrence in inner.occurrences
            if occurrence.provenance == "sized_cast_type"
        }
        outer_casts = {
            occurrence.source_range.start
            for occurrence in outer.occurrences
            if occurrence.provenance == "sized_cast_type"
        }
        self.assertEqual(inner_casts, {297})
        self.assertEqual(outer_casts, {354})
        self.assertTrue(inner_casts.isdisjoint(outer_casts))

    def test_parameter_occurrences_are_canonical_deduplicated_and_non_overlapping(self):
        graph = self._graph()
        parameters = self._parameters(graph)
        self.assertEqual(sum(len(symbol.occurrences) for symbol in parameters), 16)
        sized = [
            (occurrence.source_range.file, occurrence.source_range.start, occurrence.source_range.end)
            for symbol in parameters
            for occurrence in symbol.occurrences
            if occurrence.provenance == "sized_cast_type"
        ]
        self.assertEqual(
            sorted(sized),
            [
                ("rtl/child.sv", 93, 98),
                ("rtl/child.sv", 301, 312),
                ("rtl/child.sv", 365, 370),
                ("rtl/shadow.sv", 297, 302),
                ("rtl/shadow.sv", 354, 359),
            ],
        )
        all_ranges = [
            (symbol.symbol_id, symbol.declaration)
            for symbol in graph.symbols
        ] + [
            (symbol.symbol_id, occurrence.source_range)
            for symbol in graph.symbols
            for occurrence in symbol.occurrences
        ]
        self.assertEqual(len(all_ranges), len({(symbol_id, source_range) for symbol_id, source_range in all_ranges}))
        by_file = {}
        for symbol_id, source_range in all_ranges:
            by_file.setdefault(source_range.file, []).append((source_range.start, source_range.end, symbol_id))
        for ranges in by_file.values():
            for index, (start, end, symbol_id) in enumerate(ranges):
                for other_start, other_end, other_symbol_id in ranges[index + 1 :]:
                    if start < other_end and other_start < end:
                        self.assertEqual(symbol_id, other_symbol_id)
                        self.assertEqual((start, end), (other_start, other_end))

    def test_mapping_has_five_cast_edits_and_frozen_summary(self):
        mapping = self._mapping()
        report = mapping.to_report()
        self.assertEqual(report["summary"], {"total": 20, "rename": 9, "preserve": 11, "unsupported": 0})
        self.assertEqual(report["range_audit"], {"declarations": 20, "occurrences": 37, "total_ranges": 57})
        self.assertEqual(
            sum(len(record.occurrences) for record in mapping.records if record.category == "parameters"),
            16,
        )
        self.assertTrue(
            all(
                record.action == "rename"
                for record in mapping.records
                if record.category == "parameters"
            )
        )
        self.assertEqual(
            sum(
                1
                for record in mapping.records
                for occurrence in record.occurrences
                if occurrence.provenance == "sized_cast_type"
            ),
            5,
        )

    def test_actual_gate_strict_compile_and_restore_are_byte_identical(self):
        mapping = self._mapping()
        gold = {
            item.file: (FIXTURE_ROOT / item.file).read_bytes()
            for item in mapping.input_manifest
        }
        with tempfile.TemporaryDirectory(prefix="t069-gate-", dir="/private/tmp") as temporary:
            root = Path(temporary)
            gate_dir = root / "gate"
            execution = write_gate_vnext(mapping, output_dir=gate_dir)
            self.assertEqual(len(execution.gate_manifest), 3)
            self.assertEqual(len(execution.edits), 32)
            self.assertEqual(execution.compile_evidence.catalog_parse_errors, 0)
            self.assertEqual(execution.compile_evidence.catalog_semantic_errors, 0)
            self.assertEqual(execution.compile_evidence.top_overlay_parse_errors, 0)
            self.assertEqual(execution.compile_evidence.top_overlay_semantic_errors, 0)
            expected_cast_symbol_ids = {
                (occurrence.source_range.file, occurrence.source_range.start): record.symbol_id
                for record in mapping.records
                if record.category == "parameters"
                for occurrence in record.occurrences
                if occurrence.provenance == "sized_cast_type"
            }
            cast_edits = {
                (edit.source_range.file, edit.source_range.start): edit.symbol_id
                for edit in execution.edits
                if edit.provenance == "sized_cast_type"
            }
            self.assertEqual(
                cast_edits,
                expected_cast_symbol_ids,
            )
            restored_dir = root / "restored"
            restored = restore_gate_vnext(execution, gate_dir=gate_dir, output_dir=restored_dir)
            self.assertEqual(restored.restored_manifest, mapping.input_manifest)
            self.assertTrue(restored.to_report()["summary"]["byte_identical"])
            self.assertEqual(
                gold,
                {item.file: (restored_dir / item.file).read_bytes() for item in mapping.input_manifest},
            )

    def test_actual_renamed_gate_passes_formal(self):
        mapping = self._mapping()
        with tempfile.TemporaryDirectory(prefix="t069-formal-", dir="/private/tmp") as temporary:
            gate_dir = Path(temporary) / "gate"
            write_gate_vnext(mapping, output_dir=gate_dir)
            result = self._formal(gate_dir)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            payload = json.loads(result.stdout.strip().splitlines()[-1])
            self.assertEqual(payload["formal_equivalence"], "pass")
            self.assertEqual(payload["top"], "t069_sized_cast_top")
            self.assertEqual(payload["seq"], 5)
            print(f"T069_FORMAL_POSITIVE_GATE={gate_dir}")
            print(f"T069_FORMAL_POSITIVE_JSON={json.dumps(payload, sort_keys=True)}")

    def test_one_byte_tilde_negative_gate_compiles_and_fails_formal(self):
        mapping = self._mapping()
        with tempfile.TemporaryDirectory(prefix="t069-negative-", dir="/private/tmp") as temporary:
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
            negative_source_set = replace(
                self._source_set(),
                source_root=negative_dir.resolve(),
            )
            compile_report = build_source_catalog(negative_source_set).to_report()["compile"]
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
            print(f"T069_FORMAL_NEGATIVE_GATE={negative_dir}")
            print(f"T069_FORMAL_NEGATIVE_EXIT={result.returncode}")


if __name__ == "__main__":
    unittest.main()
