from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from rtl_obfuscator import rewrite_vnext as rewrite_vnext_module
from rtl_obfuscator.mapping_vnext import build_mapping_vnext
from rtl_obfuscator.rewrite_policy import build_rewrite_policy
from rtl_obfuscator.source_catalog import SourceRange, build_source_catalog
from rtl_obfuscator.source_set import from_filelist, from_single_file
from rtl_obfuscator.symbol_graph import build_symbol_graph
from rtl_obfuscator.rewrite_vnext import (
    RewriteVNextError,
    build_mapping_execution_vnext,
    restore_gate_vnext,
    write_gate_vnext,
    write_mapping_execution_vnext,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "refactor_symbol_graph_parameters"


def _deterministic_factory(symbol_id: str, name_length: int, unavailable: frozenset[str]) -> str:
    del unavailable
    return "n" + hashlib.sha256(symbol_id.encode("utf-8")).hexdigest()[: name_length - 1]


class MappingExecutionVNextTests(unittest.TestCase):
    def _mapping(
        self,
        filelist: Path,
        *,
        top: str | None = None,
        categories=("signals", "parameters", "genvars"),
        abi_categories=(),
        single_file: bool = False,
    ):
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
    def _assert_code(callable_obj, code: str) -> None:
        with unittest.TestCase().assertRaises(RewriteVNextError) as raised:
            callable_obj()
        unittest.TestCase().assertEqual(raised.exception.code, code)
        unittest.TestCase().assertTrue(str(raised.exception).startswith(f"{code}: "))

    def _envelope(self, temp: str, mapping, label: str = "run"):
        root = Path(temp) / label
        root.mkdir()
        gate_dir = root / "gate"
        restored_dir = root / "restored"
        execution = write_gate_vnext(mapping, output_dir=gate_dir)
        restored = restore_gate_vnext(
            execution,
            gate_dir=gate_dir,
            output_dir=restored_dir,
        )
        return build_mapping_execution_vnext(execution, restored)

    def test_full_top_envelope_projects_manifests_per_file_and_ranges(self):
        mapping = self._mapping(
            FIXTURE_ROOT / "design.f",
            top="parameter_top",
            abi_categories=("parameters",),
        )
        with tempfile.TemporaryDirectory() as temp:
            envelope = self._envelope(temp, mapping)
            report = envelope.to_report()
            self.assertEqual(
                list(report),
                [
                    "format",
                    "schema_version",
                    "state",
                    "mapping",
                    "filelist",
                    "input_manifest",
                    "gate_manifest",
                    "restored_manifest",
                    "per_file_mapping",
                    "summary",
                ],
            )
            self.assertEqual(report["format"], "rtl-obfuscation.mapping-execution-vnext")
            self.assertEqual(report["filelist"], "design.f")
            self.assertEqual(
                report["summary"]["files"],
                4,
            )
            self.assertEqual(report["summary"]["mapping_records"], 20)
            self.assertEqual(report["summary"]["renamed_records"], 16)
            self.assertEqual(report["summary"]["modified_tokens"], 41)
            self.assertFalse(report["summary"]["input_gate_manifest_equal"])
            self.assertTrue(report["summary"]["restored_input_manifest_equal"])
            self.assertTrue(report["summary"]["restored_byte_identical"])
            self.assertEqual(
                [item["file"] for item in report["input_manifest"]],
                ["rtl/child.sv", "rtl/shadow.sv", "rtl/top.sv", "rtl/unreachable.sv"],
            )
            self.assertEqual(
                [item["sha256"] for item in report["input_manifest"]],
                [
                    "5912234069b2b4cba33e365361c5974929886390ae9fda123d558102c6ce4777",
                    "51d9644e72641311d705ffef098d7836de8a1eaa4dd01a2421bfccc346f82aa8",
                    "a59967267facc37cc1fa468daa2d4f2372080ad2f38cf9143e9bd93da225c65a",
                    "2a120aa7a316a474980c31909d19f8c35d359b9761dc40fd771ea7ecbfb663aa",
                ],
            )
            self.assertEqual(report["restored_manifest"], report["input_manifest"])
            self.assertEqual(
                report["gate_manifest"],
                [
                    {"file": item.file, "sha256": item.sha256}
                    for item in envelope.rewrite_execution.gate_manifest
                ],
            )
            self.assertEqual(
                [entry["file"] for entry in report["per_file_mapping"]],
                [item["file"] for item in report["input_manifest"]],
            )
            self.assertEqual(
                report["summary"]["per_file_records"],
                sum(len(entry["records"]) for entry in report["per_file_mapping"]),
            )
            range_projection = [
                projected_range
                for file_entry in report["per_file_mapping"]
                for record in file_entry["records"]
                for projected_range in record["ranges"]
            ]
            self.assertEqual(
                sum(record["action"] == "rename" for entry in report["per_file_mapping"] for record in entry["records"] for _ in record["ranges"]),
                41,
            )
            self.assertEqual(
                sum(record["action"] != "rename" for entry in report["per_file_mapping"] for record in entry["records"] for _ in record["ranges"]),
                12,
            )
            self.assertEqual(len(range_projection), 53)
            for value in (str(FIXTURE_ROOT.resolve()), "source_root", "gate_dir", "output_dir", "TemporaryDirectory"):
                self.assertNotIn(value, json.dumps(report, ensure_ascii=False))

    def test_single_filelist_and_single_file_envelopes_are_normalized(self):
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
            filelist_report = self._envelope(temp, filelist_mapping, "filelist").to_report()
            single_report = self._envelope(temp, single_mapping, "single").to_report()
        self.assertEqual(
            json.dumps(filelist_report, ensure_ascii=False, separators=(",", ":")),
            json.dumps(single_report, ensure_ascii=False, separators=(",", ":")),
        )
        self.assertEqual(filelist_report["summary"]["files"], 1)
        self.assertEqual(filelist_report["summary"]["mapping_records"], 3)
        self.assertEqual(filelist_report["summary"]["renamed_records"], 2)

    def test_deterministic_report_and_atomic_json_are_byte_identical(self):
        mapping = self._mapping(FIXTURE_ROOT / "design.f", top="parameter_top", abi_categories=("parameters",))
        with tempfile.TemporaryDirectory() as temp:
            envelope = self._envelope(temp, mapping)
            first = json.dumps(envelope.to_report(), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            second = json.dumps(envelope.to_report(), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self.assertEqual(first, second)
            first_path = Path(temp) / "first.json"
            second_path = Path(temp) / "second.json"
            write_mapping_execution_vnext(envelope, output_file=first_path)
            write_mapping_execution_vnext(envelope, output_file=second_path)
            self.assertEqual(first_path.read_bytes(), second_path.read_bytes())
            self.assertEqual(json.loads(first_path.read_text(encoding="utf-8")), envelope.to_report())
            self.assertEqual(list(Path(temp).glob(".mapping-execution-vnext-*.tmp")), [])

    def test_execution_restore_identity_and_manifest_fail_closed(self):
        mapping = self._mapping(FIXTURE_ROOT / "design.f", top="parameter_top", abi_categories=("parameters",))
        with tempfile.TemporaryDirectory() as temp:
            gate_dir = Path(temp) / "gate"
            restore_dir = Path(temp) / "restore"
            execution = write_gate_vnext(mapping, output_dir=gate_dir)
            restored = restore_gate_vnext(execution, gate_dir=gate_dir, output_dir=restore_dir)
            self._assert_code(
                lambda: build_mapping_execution_vnext(replace(execution, schema_version=2), restored),
                "MAPPING_EXECUTION_INVALID",
            )
            self._assert_code(
                lambda: build_mapping_execution_vnext(execution, replace(restored, schema_version=2)),
                "MAPPING_EXECUTION_INVALID",
            )
            reversed_gate = replace(execution, gate_manifest=tuple(reversed(execution.gate_manifest)))
            reversed_restore = replace(restored, rewrite_execution=reversed_gate)
            self._assert_code(
                lambda: build_mapping_execution_vnext(reversed_gate, reversed_restore),
                "MAPPING_MANIFEST_INVALID",
            )
            altered_restore = replace(
                restored,
                restored_manifest=(replace(restored.restored_manifest[0], sha256="0" * 64),) + restored.restored_manifest[1:],
            )
            self._assert_code(
                lambda: build_mapping_execution_vnext(execution, altered_restore),
                "MAPPING_MANIFEST_INVALID",
            )

    def test_applied_edit_projection_missing_duplicate_and_gate_range_fail_closed(self):
        mapping = self._mapping(FIXTURE_ROOT / "design.f", top="parameter_top", abi_categories=("parameters",))
        with tempfile.TemporaryDirectory() as temp:
            gate_dir = Path(temp) / "gate"
            restore_dir = Path(temp) / "restore"
            execution = write_gate_vnext(mapping, output_dir=gate_dir)
            restored = restore_gate_vnext(execution, gate_dir=gate_dir, output_dir=restore_dir)
            missing = replace(execution, edits=execution.edits[:-1])
            self._assert_code(
                lambda: build_mapping_execution_vnext(missing, replace(restored, rewrite_execution=missing)),
                "MAPPING_PER_FILE_INVALID",
            )
            duplicate = replace(execution, edits=execution.edits[:-1] + (execution.edits[0],))
            self._assert_code(
                lambda: build_mapping_execution_vnext(duplicate, replace(restored, rewrite_execution=duplicate)),
                "MAPPING_PER_FILE_INVALID",
            )
            first_edit = execution.edits[0]
            forged_range = SourceRange(
                first_edit.gate_range.file,
                first_edit.gate_range.start + 1,
                first_edit.gate_range.end + 1,
            )
            forged = replace(execution, edits=(replace(first_edit, gate_range=forged_range),) + execution.edits[1:])
            self._assert_code(
                lambda: build_mapping_execution_vnext(forged, replace(restored, rewrite_execution=forged)),
                "MAPPING_PER_FILE_INVALID",
            )

    def test_output_path_and_atomic_io_fail_without_artifacts(self):
        mapping = self._mapping(FIXTURE_ROOT / "design.f", top="parameter_top", abi_categories=("parameters",))
        with tempfile.TemporaryDirectory() as temp:
            envelope = self._envelope(temp, mapping)
            existing = Path(temp) / "existing.json"
            existing.write_text("keep", encoding="utf-8")
            self._assert_code(
                lambda: write_mapping_execution_vnext(envelope, output_file=existing),
                "MAPPING_OUTPUT_INVALID",
            )
            self._assert_code(
                lambda: write_mapping_execution_vnext(envelope, output_file=Path(temp) / "missing" / "out.json"),
                "MAPPING_OUTPUT_INVALID",
            )
            inside_source = FIXTURE_ROOT / "mapping-execution-vnext-test.json"
            self._assert_code(
                lambda: write_mapping_execution_vnext(envelope, output_file=inside_source),
                "MAPPING_OUTPUT_INVALID",
            )
            atomic_failure = Path(temp) / "atomic-failure.json"
            with mock.patch.object(Path, "rename", side_effect=OSError("rename")):
                self._assert_code(
                    lambda: write_mapping_execution_vnext(envelope, output_file=atomic_failure),
                    "MAPPING_IO_ERROR",
                )
            self.assertFalse(atomic_failure.exists())
            self.assertEqual(list(Path(temp).glob(".mapping-execution-vnext-*.tmp")), [])
            self.assertEqual(existing.read_text(encoding="utf-8"), "keep")

    def test_envelope_does_not_rebuild_sources_graph_mapping_or_legacy_paths(self):
        mapping = self._mapping(FIXTURE_ROOT / "design.f", top="parameter_top", abi_categories=("parameters",))
        with tempfile.TemporaryDirectory() as temp:
            envelope = self._envelope(temp, mapping)
            with (
                mock.patch.object(rewrite_vnext_module, "_source_set_from_mapping", side_effect=AssertionError("rebuild")),
                mock.patch.object(rewrite_vnext_module, "build_source_catalog", side_effect=AssertionError("catalog")),
                mock.patch.object(rewrite_vnext_module, "build_rewrite_policy", side_effect=AssertionError("policy")),
                mock.patch.object(rewrite_vnext_module, "_check_regular_source_files", side_effect=AssertionError("gold")),
            ):
                rebuilt_blocked = build_mapping_execution_vnext(
                    envelope.rewrite_execution,
                    envelope.restore_result,
                )
                output = Path(temp) / "envelope.json"
                write_mapping_execution_vnext(rebuilt_blocked, output_file=output)
            self.assertTrue(output.exists())


if __name__ == "__main__":
    unittest.main()
