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

from rtl_obfuscator import category_profile, inventory, rewrite
from rtl_obfuscator import rewrite_vnext as rewrite_vnext_module
from rtl_obfuscator import symbol_graph as symbol_graph_module
from rtl_obfuscator.mapping_vnext import MappingVNext, build_mapping_vnext
from rtl_obfuscator.rewrite_policy import build_rewrite_policy
from rtl_obfuscator.rewrite_vnext import (
    AppliedEdit,
    RewriteExecution,
    RewriteVNextError,
    restore_gate_vnext,
    write_gate_vnext,
)
from rtl_obfuscator.source_catalog import SourceRange, build_source_catalog
from rtl_obfuscator.source_set import from_filelist, from_single_file
from rtl_obfuscator.symbol_graph import build_symbol_graph
from rtl_obfuscator.systemverilog_names import (
    is_plain_identifier,
    secure_name_factory,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "refactor_symbol_graph_parameters"


def _deterministic_factory(symbol_id: str, name_length: int, unavailable: frozenset[str]) -> str:
    del unavailable
    return "n" + hashlib.sha256(symbol_id.encode("utf-8")).hexdigest()[: name_length - 1]


class RewriteVNextTests(unittest.TestCase):
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
    def _physical_files(mapping: MappingVNext) -> tuple[str, ...]:
        source_set = mapping.rewrite_policy.symbol_graph.source_catalog.source_set
        return tuple(dict.fromkeys((*source_set.ordered_source_files, *source_set.included_files)))

    @staticmethod
    def _assert_code(callable_obj, code: str) -> None:
        with unittest.TestCase().assertRaises(RewriteVNextError) as raised:
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

    def test_secure_factory_validates_retries_exhaustion_and_preserves_input(self):
        unavailable = frozenset({"abbbbbbbbbbbbbbb"})
        original = unavailable
        choices = list("a" + "b" * 15 + "c" + "d" * 15)
        with mock.patch("rtl_obfuscator.systemverilog_names.secrets.choice", side_effect=choices):
            candidate = secure_name_factory("symbol", 16, unavailable)
        self.assertEqual(candidate, "cddddddddddddddd")
        self.assertTrue(is_plain_identifier(candidate))
        self.assertEqual(len(candidate), 16)
        self.assertEqual(unavailable, original)
        with mock.patch("rtl_obfuscator.systemverilog_names.secrets.choice", return_value="a"):
            with self.assertRaises(RuntimeError):
                secure_name_factory("symbol", 16, frozenset({"a" * 16}))

    def test_full_top_writes_atomic_gate_and_manifest_summary(self):
        mapping = self._mapping(
            FIXTURE_ROOT / "design.f",
            top="parameter_top",
            abi_categories=("parameters",),
        )
        gold = {file: (FIXTURE_ROOT / file).read_bytes() for file in self._physical_files(mapping)}
        with tempfile.TemporaryDirectory() as temp:
            gate_dir = Path(temp) / "gate"
            execution = write_gate_vnext(mapping, output_dir=gate_dir)
            report = execution.to_report()
            self.assertEqual(report["summary"], {"files": 4, "mapping_records": 20, "renamed_records": 16, "modified_tokens": 41})
            self.assertEqual(len(execution.edits), 41)
            self.assertEqual([item.file for item in execution.gate_manifest], list(self._physical_files(mapping)))
            self.assertEqual(
                execution.compile_evidence,
                rewrite_vnext_module.CompileEvidence(0, 0, 0, 0),
            )
            self.assertTrue(all((gate_dir / file).read_bytes() != gold[file] for file in gold))
            self.assertEqual(
                (gate_dir / "design.f").read_text(),
                "".join(f"{file}\n" for file in mapping.rewrite_policy.symbol_graph.source_catalog.source_set.compile_order),
            )

    def test_edits_are_canonical_delta_ranged_and_gold_is_unchanged(self):
        mapping = self._mapping(FIXTURE_ROOT / "design.f", top="parameter_top", abi_categories=("parameters",))
        gold = {file: (FIXTURE_ROOT / file).read_bytes() for file in self._physical_files(mapping)}
        with tempfile.TemporaryDirectory() as temp:
            execution = write_gate_vnext(mapping, output_dir=Path(temp) / "gate")
            self.assertEqual(len(execution.edits), 41)
            record_edits = []
            for record in mapping.records:
                if record.action == "rename":
                    record_edits.extend(
                        [(record.symbol_id, "declaration", record.declaration)]
                        + [(record.symbol_id, occurrence.provenance, occurrence.source_range) for occurrence in record.occurrences]
                    )
            self.assertEqual(
                [(edit.symbol_id, edit.provenance, edit.source_range) for edit in execution.edits],
                record_edits,
            )
            for edit in execution.edits:
                earlier = sum(
                    len(other.renamed_name.encode()) - len(other.original_name.encode())
                    for other in execution.edits
                    if other.source_range.file == edit.source_range.file
                    and other.source_range.start < edit.source_range.start
                )
                self.assertEqual(edit.gate_range.start, edit.source_range.start + earlier)
                self.assertEqual(
                    edit.gate_range.end,
                    edit.gate_range.start + len(edit.renamed_name.encode()),
                )
            self.assertEqual(gold, {file: (FIXTURE_ROOT / file).read_bytes() for file in gold})

    def test_strict_compile_uses_same_context_without_graph_or_legacy_rebuild(self):
        mapping = self._mapping(FIXTURE_ROOT / "design.f", top="parameter_top", abi_categories=("parameters",))
        with tempfile.TemporaryDirectory() as temp:
            with (
                mock.patch.object(symbol_graph_module, "build_symbol_graph", side_effect=AssertionError("graph rebuild")),
                mock.patch.object(inventory, "build_top_project_inventory", side_effect=AssertionError("legacy inventory")),
                mock.patch.object(inventory, "build_filelist_default_inventory", side_effect=AssertionError("legacy inventory")),
                mock.patch.object(rewrite, "_encrypt_project", side_effect=AssertionError("legacy rewrite")),
                mock.patch.object(rewrite, "_encrypt_filelist_manual_v4", side_effect=AssertionError("legacy rewrite")),
                mock.patch.object(category_profile, "resolve", side_effect=AssertionError("legacy profile")),
                mock.patch.object(category_profile, "expand", side_effect=AssertionError("legacy profile")),
            ):
                execution = write_gate_vnext(mapping, output_dir=Path(temp) / "gate")
            self.assertEqual(execution.compile_evidence.catalog_parse_errors, 0)
            self.assertEqual(execution.compile_evidence.catalog_semantic_errors, 0)
            self.assertEqual(execution.compile_evidence.top_overlay_parse_errors, 0)
            self.assertEqual(execution.compile_evidence.top_overlay_semantic_errors, 0)

    def test_restore_uses_execution_and_gate_only_and_is_byte_identical(self):
        mapping = self._mapping(FIXTURE_ROOT / "design.f", top="parameter_top", abi_categories=("parameters",))
        gold = {file: (FIXTURE_ROOT / file).read_bytes() for file in self._physical_files(mapping)}
        with tempfile.TemporaryDirectory() as temp:
            gate_dir = Path(temp) / "gate"
            restored_dir = Path(temp) / "restored"
            execution = write_gate_vnext(mapping, output_dir=gate_dir)
            with mock.patch.object(rewrite_vnext_module, "_source_root", side_effect=AssertionError("gold read")):
                result = restore_gate_vnext(execution, gate_dir=gate_dir, output_dir=restored_dir)
            self.assertEqual(result.to_report()["summary"], {"files": 4, "modified_tokens": 41, "byte_identical": True})
            self.assertEqual(result.restored_manifest, mapping.input_manifest)
            self.assertEqual(gold, {file: (restored_dir / file).read_bytes() for file in gold})

    def test_single_file_and_filelist_share_gate_and_restore_engine(self):
        filelist_mapping = self._mapping(FIXTURE_ROOT / "single.f", categories=("signals", "parameters"))
        single_mapping = self._mapping(FIXTURE_ROOT / "single.f", categories=("signals", "parameters"), single_file=True)
        with tempfile.TemporaryDirectory() as temp:
            filelist_gate = Path(temp) / "filelist-gate"
            single_gate = Path(temp) / "single-gate"
            filelist_execution = write_gate_vnext(filelist_mapping, output_dir=filelist_gate)
            single_execution = write_gate_vnext(single_mapping, output_dir=single_gate)
            self.assertEqual((filelist_gate / "single.sv").read_bytes(), (single_gate / "single.sv").read_bytes())
            self.assertEqual(
                json.dumps(filelist_execution.to_report(), sort_keys=True, separators=(",", ":")),
                json.dumps(single_execution.to_report(), sort_keys=True, separators=(",", ":")),
            )
            filelist_restored = restore_gate_vnext(filelist_execution, gate_dir=filelist_gate, output_dir=Path(temp) / "filelist-restored")
            single_restored = restore_gate_vnext(single_execution, gate_dir=single_gate, output_dir=Path(temp) / "single-restored")
            self.assertEqual(filelist_restored.to_report(), single_restored.to_report())
            self.assertEqual(filelist_restored.restored_manifest, filelist_mapping.input_manifest)

    def test_no_top_preserves_module_abi_and_restores_after_strict_gate(self):
        mapping = self._mapping(FIXTURE_ROOT / "design.f")
        self.assertTrue(all(record.action == "preserve" for record in mapping.records if record.abi == "module_abi"))
        with tempfile.TemporaryDirectory() as temp:
            gate_dir = Path(temp) / "gate"
            execution = write_gate_vnext(mapping, output_dir=gate_dir)
            self.assertIsNone(execution.compile_evidence.top_overlay_parse_errors)
            self.assertEqual(execution.to_report()["summary"], {"files": 4, "mapping_records": 20, "renamed_records": 13, "modified_tokens": 24})
            restored = restore_gate_vnext(execution, gate_dir=gate_dir, output_dir=Path(temp) / "restored")
            self.assertTrue(restored.to_report()["summary"]["byte_identical"])

    def test_malformed_mapping_source_manifest_and_ranges_fail_closed_without_output(self):
        mapping = self._mapping(FIXTURE_ROOT / "design.f", top="parameter_top", abi_categories=("parameters",))
        with tempfile.TemporaryDirectory() as temp:
            cases = (
                (replace(mapping, format="wrong"), "REWRITE_MAPPING_INVALID"),
                (replace(mapping, records=mapping.records[:-1]), "REWRITE_MAPPING_INVALID"),
                (replace(mapping, input_manifest=(replace(mapping.input_manifest[0], sha256="0" * 64),) + mapping.input_manifest[1:]), "REWRITE_SOURCE_CHANGED"),
            )
            for index, (malformed, code) in enumerate(cases):
                with self.subTest(index=index):
                    output = Path(temp) / f"bad-{index}"
                    self._assert_code(lambda malformed=malformed, output=output: write_gate_vnext(malformed, output_dir=output), code)
                    self.assertFalse(output.exists())

            first, second = mapping.rewrite_policy.symbol_graph.symbols[:2]
            malformed_symbol = replace(first, name=second.name, declaration=second.declaration, occurrences=())
            malformed_graph = replace(mapping.rewrite_policy.symbol_graph, symbols=(malformed_symbol,) + mapping.rewrite_policy.symbol_graph.symbols[1:])
            malformed_policy = build_rewrite_policy(
                malformed_graph,
                categories=mapping.rewrite_policy.selected_categories,
                abi_categories=mapping.rewrite_policy.abi_categories,
            )
            malformed_record = replace(mapping.records[0], original_name=second.name, declaration=second.declaration, occurrences=())
            malformed_mapping = replace(
                mapping,
                rewrite_policy=malformed_policy,
                records=(malformed_record,) + mapping.records[1:],
            )
            output = Path(temp) / "bad-range"
            self._assert_code(lambda: write_gate_vnext(malformed_mapping, output_dir=output), "REWRITE_EDIT_INVALID")
            self.assertFalse(output.exists())

    def test_output_io_and_strict_compile_fail_atomically(self):
        mapping = self._mapping(FIXTURE_ROOT / "design.f", top="parameter_top", abi_categories=("parameters",))
        with tempfile.TemporaryDirectory() as temp:
            existing = Path(temp) / "existing"
            existing.mkdir()
            self._assert_code(lambda: write_gate_vnext(mapping, output_dir=existing), "REWRITE_OUTPUT_INVALID")
            self._assert_code(lambda: write_gate_vnext(mapping, output_dir=FIXTURE_ROOT / "inside-gate"), "REWRITE_OUTPUT_INVALID")
            with mock.patch.object(rewrite_vnext_module.tempfile, "mkdtemp", side_effect=OSError("staging")):
                self._assert_code(lambda: write_gate_vnext(mapping, output_dir=Path(temp) / "io-failure"), "REWRITE_IO_ERROR")
            with mock.patch.object(rewrite_vnext_module, "build_source_catalog", side_effect=RuntimeError("strict")):
                output = Path(temp) / "compile-failure"
                self._assert_code(lambda: write_gate_vnext(mapping, output_dir=output), "REWRITE_GATE_COMPILE_FAILED")
                self.assertFalse(output.exists())

    def test_malformed_execution_gate_manifest_and_range_fail_closed(self):
        mapping = self._mapping(FIXTURE_ROOT / "design.f", top="parameter_top", abi_categories=("parameters",))
        with tempfile.TemporaryDirectory() as temp:
            gate_dir = Path(temp) / "gate"
            execution = write_gate_vnext(mapping, output_dir=gate_dir)
            self._assert_code(lambda: restore_gate_vnext(replace(execution, schema_version=2), gate_dir=gate_dir, output_dir=Path(temp) / "bad-schema"), "RESTORE_EXECUTION_INVALID")

            (gate_dir / "design.f").write_text("wrong\n")
            self._assert_code(lambda: restore_gate_vnext(execution, gate_dir=gate_dir, output_dir=Path(temp) / "bad-filelist"), "RESTORE_GATE_INVALID")
            (gate_dir / "design.f").write_text("".join(f"{file}\n" for file in mapping.rewrite_policy.symbol_graph.source_catalog.source_set.compile_order))

            child = gate_dir / "rtl/child.sv"
            child_bytes = child.read_bytes()
            edit = next(edit for edit in execution.edits if edit.source_range.file == "rtl/child.sv")
            child.write_bytes(child_bytes[:edit.gate_range.start] + b"X" + child_bytes[edit.gate_range.end:])
            forged_manifest = tuple(
                replace(item, sha256=hashlib.sha256((gate_dir / item.file).read_bytes()).hexdigest())
                if item.file == "rtl/child.sv" else item
                for item in execution.gate_manifest
            )
            forged_execution = replace(execution, gate_manifest=forged_manifest)
            self._assert_code(lambda: restore_gate_vnext(forged_execution, gate_dir=gate_dir, output_dir=Path(temp) / "bad-range"), "RESTORE_RANGE_INVALID")

            gate_dir = Path(temp) / "gate2"
            execution = write_gate_vnext(mapping, output_dir=gate_dir)
            bad_input = replace(mapping.input_manifest[0], sha256="f" * 64)
            bad_mapping = replace(mapping, input_manifest=(bad_input,) + mapping.input_manifest[1:])
            bad_execution = replace(execution, mapping_vnext=bad_mapping)
            self._assert_code(lambda: restore_gate_vnext(bad_execution, gate_dir=gate_dir, output_dir=Path(temp) / "bad-hash"), "RESTORE_BYTES_MISMATCH")

    def test_actual_renamed_gate_passes_compact_formal(self):
        mapping = self._mapping(FIXTURE_ROOT / "design.f", top="parameter_top", abi_categories=("parameters",))
        with tempfile.TemporaryDirectory() as temp:
            gate_dir = Path(temp) / "gate"
            execution = write_gate_vnext(mapping, output_dir=gate_dir)
            self.assertEqual(len(execution.edits), 41)
            self.assertTrue(any((gate_dir / file).read_bytes() != (FIXTURE_ROOT / file).read_bytes() for file in self._physical_files(mapping)))
            result = self._run_formal(gate_dir)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            payload = json.loads(result.stdout.strip().splitlines()[-1])
            self.assertEqual(payload["formal_equivalence"], "pass")
            self.assertEqual(payload["seq"], 5)
            self.assertEqual(payload["top"], "parameter_top")

    def test_one_byte_tilde_gate_strict_compiles_and_fails_formal(self):
        mapping = self._mapping(FIXTURE_ROOT / "design.f", top="parameter_top", abi_categories=("parameters",))
        with tempfile.TemporaryDirectory() as temp:
            gate_dir = Path(temp) / "gate"
            write_gate_vnext(mapping, output_dir=gate_dir)
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
            negative_catalog = build_source_catalog(negative_source_set)
            compile_report = negative_catalog.to_report()["compile"]
            self.assertEqual(compile_report, {"catalog": {"parse_errors": 0, "semantic_errors": 0}, "top_overlay": {"parse_errors": 0, "semantic_errors": 0}})
            result = self._run_formal(negative_dir)
            combined = (result.stdout + result.stderr).lower()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unproven", combined)
            self.assertIn("equiv_status -assert", combined)


if __name__ == "__main__":
    unittest.main()
