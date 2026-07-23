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

from rtl_obfuscator import rewrite as legacy_rewrite
from rtl_obfuscator import rewrite_vnext as rewrite_vnext_module
from rtl_obfuscator import symbol_graph as symbol_graph_module
from rtl_obfuscator.mapping_vnext import MappingVNext, build_mapping_vnext
from rtl_obfuscator.rate_execution_vnext import (
    RateExecutionVNextError,
    build_rate_selected_mapping_vnext,
    restore_rate_selected_gate_vnext,
    write_rate_selected_gate_vnext,
)
from rtl_obfuscator.rate_vnext import build_rate_selection_vnext
from rtl_obfuscator.rewrite_policy import build_rewrite_policy
from rtl_obfuscator.source_catalog import build_source_catalog
from rtl_obfuscator.source_set import from_filelist, from_single_file
from rtl_obfuscator.symbol_graph import build_symbol_graph


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "refactor_symbol_graph_parameters"


def _deterministic_factory(symbol_id: str, name_length: int, unavailable: frozenset[str]) -> str:
    del unavailable
    return "n" + hashlib.sha256(symbol_id.encode("utf-8")).hexdigest()[: name_length - 1]


class RateExecutionVNextTests(unittest.TestCase):
    def _mapping(
        self,
        filelist: Path,
        *,
        top: str | None = None,
        categories=("signals", "parameters", "genvars"),
        abi_categories=(),
        single_file: bool = False,
    ) -> MappingVNext:
        if single_file:
            source_set = from_single_file(
                source_file=FIXTURE_ROOT / "single.sv",
                source_root=FIXTURE_ROOT,
                top=top,
            )
        else:
            source_set = from_filelist(
                filelist=filelist,
                source_root=FIXTURE_ROOT,
                top=top,
            )
        graph = build_symbol_graph(build_source_catalog(source_set))
        policy = build_rewrite_policy(
            graph,
            categories=categories,
            abi_categories=abi_categories,
        )
        return build_mapping_vnext(
            policy,
            name_length=16,
            name_factory=_deterministic_factory,
        )

    @staticmethod
    def _selection(mapping: MappingVNext):
        return build_rate_selection_vnext(mapping, "0.35")

    @staticmethod
    def _physical_files(mapping: MappingVNext) -> tuple[str, ...]:
        source_set = mapping.rewrite_policy.symbol_graph.source_catalog.source_set
        return tuple(dict.fromkeys((*source_set.ordered_source_files, *source_set.included_files)))

    @staticmethod
    def _assert_code(callable_obj, code: str) -> None:
        with unittest.TestCase().assertRaises(RateExecutionVNextError) as raised:
            callable_obj()
        unittest.TestCase().assertEqual(raised.exception.code, code)
        unittest.TestCase().assertTrue(str(raised.exception).startswith(f"{code}: "))

    @staticmethod
    def _run_formal(gate_dir: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                "scripts/formal_equivalence.py",
                "--gold-filelist",
                "tests/fixtures/refactor_symbol_graph_parameters/design.f",
                "--gold-root",
                "tests/fixtures/refactor_symbol_graph_parameters",
                "--gate-filelist",
                str(gate_dir / "design.f"),
                "--gate-root",
                str(gate_dir),
                "--top",
                "parameter_top",
                "--seq",
                "5",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=180,
        )

    def test_selected_mapping_preserves_complete_records_and_equations(self):
        mapping = self._mapping(
            FIXTURE_ROOT / "design.f",
            top="parameter_top",
            abi_categories=("parameters",),
        )
        selection = self._selection(mapping)
        materialized = build_rate_selected_mapping_vnext(mapping, selection)
        selected_ids = {
            candidate.symbol_id for candidate in selection.candidates if candidate.selected
        }
        original_by_id = {record.symbol_id: record for record in mapping.records}
        materialized_by_id = {record.symbol_id: record for record in materialized.records}
        self.assertEqual(tuple(materialized_by_id), tuple(original_by_id))
        self.assertIs(materialized.rewrite_policy.symbol_graph, mapping.rewrite_policy.symbol_graph)
        self.assertIs(materialized.rewrite_policy.symbol_graph.source_catalog, mapping.rewrite_policy.symbol_graph.source_catalog)
        self.assertEqual(materialized.input_manifest, mapping.input_manifest)
        for original, actual in zip(mapping.records, materialized.records):
            self.assertEqual(actual.symbol_id, original.symbol_id)
            self.assertEqual(actual.category, original.category)
            self.assertEqual(actual.owner_module, original.owner_module)
            self.assertEqual(actual.declaration, original.declaration)
            self.assertEqual(actual.occurrences, original.occurrences)
            self.assertEqual(actual.impact, original.impact)
            self.assertEqual(actual.abi, original.abi)
            if original.action == "rename" and original.symbol_id in selected_ids:
                self.assertEqual(actual.action, "rename")
                self.assertEqual(actual.renamed_name, original.renamed_name)
            elif original.action == "rename":
                self.assertEqual(actual.action, "preserve")
                self.assertEqual(actual.reason, "rate_unselected")
                self.assertIsNone(actual.renamed_name)
            else:
                self.assertEqual(actual.action, original.action)
                self.assertEqual(actual.reason, original.reason)
                self.assertEqual(actual.renamed_name, original.renamed_name)
        for original, actual, decision in zip(
            mapping.records,
            materialized.records,
            materialized.rewrite_policy.decisions,
        ):
            self.assertEqual(decision.symbol_id, actual.symbol_id)
            self.assertEqual(decision.action, actual.action)
            self.assertEqual(decision.reason, actual.reason)
            if original.action == "rename" and original.symbol_id not in selected_ids:
                self.assertEqual(decision.reason, "rate_unselected")

        report = selection.to_report()
        self.assertEqual(report["target"], 0.35)
        self.assertGreaterEqual(report["selected_lines"], report["target_lines"])
        self.assertEqual(
            report["selected_entries"],
            sum(candidate.selected for candidate in selection.candidates),
        )

    def test_selected_gate_reuses_one_pass_engine_and_restores_all_files(self):
        mapping = self._mapping(
            FIXTURE_ROOT / "design.f",
            top="parameter_top",
            abi_categories=("parameters",),
        )
        selection = self._selection(mapping)
        gold = {file: (FIXTURE_ROOT / file).read_bytes() for file in self._physical_files(mapping)}
        selected_ids = {
            candidate.symbol_id for candidate in selection.candidates if candidate.selected
        }
        expected_edit_count = sum(
            1 + len(record.occurrences)
            for record in mapping.records
            if record.action == "rename" and record.symbol_id in selected_ids
        )
        with tempfile.TemporaryDirectory() as temp:
            gate_dir = Path(temp) / "gate"
            restore_dir = Path(temp) / "restored"
            execution = write_rate_selected_gate_vnext(mapping, selection, gate_dir)
            self.assertEqual(len(execution.rewrite_execution.edits), expected_edit_count)
            self.assertEqual(
                execution.rewrite_execution.compile_evidence.catalog_parse_errors,
                0,
            )
            self.assertEqual(
                execution.rewrite_execution.compile_evidence.catalog_semantic_errors,
                0,
            )
            self.assertEqual(execution.rewrite_execution.compile_evidence.top_overlay_parse_errors, 0)
            self.assertEqual(execution.rewrite_execution.compile_evidence.top_overlay_semantic_errors, 0)
            self.assertTrue(
                any((gate_dir / file).read_bytes() != gold[file] for file in gold)
            )
            self.assertEqual(
                [item.file for item in execution.rewrite_execution.gate_manifest],
                list(self._physical_files(mapping)),
            )
            self.assertTrue(
                all(edit.symbol_id in selected_ids for edit in execution.rewrite_execution.edits)
            )
            report = execution.to_report()
            self.assertEqual(
                list(report),
                [
                    "format",
                    "schema_version",
                    "state",
                    "rate_selection",
                    "rewrite_execution",
                    "summary",
                ],
            )
            self.assertEqual(report["format"], "rtl-obfuscation.rate-rewrite-execution-vnext")
            self.assertTrue(report["summary"]["strict_compile_passed"])
            self.assertEqual(report["summary"]["mapping_records"], len(mapping.records))
            self.assertEqual(report["summary"]["selected_renamed_records"], len(selected_ids))
            self.assertEqual(
                report["summary"]["rate_unselected_records"],
                sum(
                    record.action == "rename" and record.symbol_id not in selected_ids
                    for record in mapping.records
                ),
            )
            serialized = json.dumps(report, ensure_ascii=False)
            self.assertNotIn(str(FIXTURE_ROOT.resolve()), serialized)
            self.assertNotIn("source_root", serialized)

            restored = restore_rate_selected_gate_vnext(execution, gate_dir, restore_dir)
            self.assertEqual(restored.restored_manifest, mapping.input_manifest)
            self.assertEqual(
                {file: (restore_dir / file).read_bytes() for file in gold},
                gold,
            )

    def test_single_file_and_filelist_selected_execution_are_normalized(self):
        filelist_mapping = self._mapping(
            FIXTURE_ROOT / "single.f",
            categories=("signals", "parameters"),
        )
        single_mapping = self._mapping(
            FIXTURE_ROOT / "single.f",
            categories=("signals", "parameters"),
            single_file=True,
        )
        with tempfile.TemporaryDirectory() as temp:
            filelist_execution = write_rate_selected_gate_vnext(
                filelist_mapping,
                self._selection(filelist_mapping),
                Path(temp) / "filelist-gate",
            )
            single_execution = write_rate_selected_gate_vnext(
                single_mapping,
                self._selection(single_mapping),
                Path(temp) / "single-gate",
            )
            self.assertEqual(
                (Path(temp) / "filelist-gate/single.sv").read_bytes(),
                (Path(temp) / "single-gate/single.sv").read_bytes(),
            )
            self.assertEqual(
                json.dumps(filelist_execution.to_report(), sort_keys=True, separators=(",", ":")),
                json.dumps(single_execution.to_report(), sort_keys=True, separators=(",", ":")),
            )

    def test_invalid_identity_mapping_manifest_range_and_output_fail_closed(self):
        mapping = self._mapping(
            FIXTURE_ROOT / "design.f",
            top="parameter_top",
            abi_categories=("parameters",),
        )
        selection = self._selection(mapping)
        other_mapping = self._mapping(
            FIXTURE_ROOT / "design.f",
            top="parameter_top",
            abi_categories=("parameters",),
        )
        self._assert_code(
            lambda: build_rate_selected_mapping_vnext(other_mapping, selection),
            "RATE_EXECUTION_INVALID",
        )
        self._assert_code(
            lambda: build_rate_selected_mapping_vnext(
                mapping,
                replace(selection, schema_version=2),
            ),
            "RATE_EXECUTION_INVALID",
        )
        bad_manifest = replace(
            mapping,
            input_manifest=(replace(mapping.input_manifest[0], sha256="0" * 64),)
            + mapping.input_manifest[1:],
        )
        self._assert_code(
            lambda: build_rate_selected_mapping_vnext(bad_manifest, selection),
            "RATE_EXECUTION_INVALID",
        )
        with tempfile.TemporaryDirectory() as temp:
            existing = Path(temp) / "existing"
            existing.mkdir()
            self._assert_code(
                lambda: write_rate_selected_gate_vnext(mapping, selection, existing),
                "RATE_OUTPUT_INVALID",
            )
            self.assertEqual(list(Path(temp).iterdir()), [existing])

            gate_dir = Path(temp) / "gate"
            execution = write_rate_selected_gate_vnext(mapping, selection, gate_dir)
            first = execution.rewrite_execution.edits[0]
            gate_file = gate_dir / first.gate_range.file
            gate_bytes = gate_file.read_bytes()
            gate_file.write_bytes(
                gate_bytes[: first.gate_range.start]
                + b"X"
                + gate_bytes[first.gate_range.end :]
            )
            self._assert_code(
                lambda: restore_rate_selected_gate_vnext(
                    execution,
                    gate_dir,
                    Path(temp) / "bad-restore",
                ),
                "RATE_RESTORE_INVALID",
            )
            self.assertFalse((Path(temp) / "bad-restore").exists())

    def test_selected_execution_blocks_rebuild_and_legacy_paths(self):
        mapping = self._mapping(
            FIXTURE_ROOT / "design.f",
            top="parameter_top",
            abi_categories=("parameters",),
        )
        selection = self._selection(mapping)
        with tempfile.TemporaryDirectory() as temp:
            with (
                mock.patch.object(symbol_graph_module, "build_symbol_graph", side_effect=AssertionError("graph rebuild")),
                mock.patch.object(rewrite_vnext_module, "build_rewrite_policy", side_effect=AssertionError("policy rebuild")),
                mock.patch.object(legacy_rewrite, "_encrypt_project", side_effect=AssertionError("legacy rewrite")),
                mock.patch.object(legacy_rewrite, "_encrypt_filelist_manual_v4", side_effect=AssertionError("legacy rewrite")),
                mock.patch.object(legacy_rewrite, "decrypt_project", side_effect=AssertionError("legacy decrypt"), create=True),
            ):
                execution = write_rate_selected_gate_vnext(
                    mapping,
                    selection,
                    Path(temp) / "gate",
                )
            self.assertTrue(execution.to_report()["summary"]["strict_compile_passed"])

    def test_actual_selected_gate_formal_positive_and_one_byte_negative(self):
        mapping = self._mapping(
            FIXTURE_ROOT / "design.f",
            top="parameter_top",
            abi_categories=("parameters",),
        )
        selection = self._selection(mapping)
        with tempfile.TemporaryDirectory() as temp:
            gate_dir = Path(temp) / "gate"
            execution = write_rate_selected_gate_vnext(mapping, selection, gate_dir)
            self.assertTrue(execution.to_report()["summary"]["strict_compile_passed"])
            positive = self._run_formal(gate_dir)
            self.assertEqual(positive.returncode, 0, positive.stdout + positive.stderr)
            positive_payload = json.loads(positive.stdout.strip().splitlines()[-1])
            self.assertEqual(positive_payload["formal_equivalence"], "pass")
            self.assertEqual(positive_payload["seq"], 5)
            self.assertEqual(positive_payload["top"], "parameter_top")

            negative_dir = Path(temp) / "negative"
            shutil.copytree(gate_dir, negative_dir)
            child = negative_dir / "rtl/child.sv"
            original = child.read_bytes()
            needle = b"assign data_o = "
            self.assertEqual(original.count(needle), 1)
            position = original.index(needle) + len(needle)
            child.write_bytes(original[:position] + b"~" + original[position:])
            negative_source_set = replace(
                mapping.rewrite_policy.symbol_graph.source_catalog.source_set,
                source_root=negative_dir.resolve(),
            )
            negative_compile = build_source_catalog(negative_source_set).to_report()["compile"]
            self.assertEqual(
                negative_compile,
                {
                    "catalog": {"parse_errors": 0, "semantic_errors": 0},
                    "top_overlay": {"parse_errors": 0, "semantic_errors": 0},
                },
            )
            negative = self._run_formal(negative_dir)
            combined = (negative.stdout + negative.stderr).lower()
            self.assertNotEqual(negative.returncode, 0)
            self.assertIn("unproven", combined)
            self.assertIn("equiv_status -assert", combined)


if __name__ == "__main__":
    unittest.main()
