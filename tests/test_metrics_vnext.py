from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from rtl_obfuscator import rewrite_vnext as rewrite_vnext_module
from rtl_obfuscator.mapping_vnext import build_mapping_vnext
from rtl_obfuscator.metrics_vnext import (
    MetricsVNextError,
    build_metrics_vnext,
    write_metrics_vnext,
)
from rtl_obfuscator.rewrite_policy import build_rewrite_policy
from rtl_obfuscator.rewrite_vnext import (
    build_mapping_execution_vnext,
    restore_gate_vnext,
    write_gate_vnext,
)
from rtl_obfuscator.source_catalog import build_source_catalog
from rtl_obfuscator.source_set import from_filelist, from_single_file
from rtl_obfuscator.symbol_graph import build_symbol_graph


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "refactor_symbol_graph_parameters"


def _deterministic_factory(symbol_id: str, name_length: int, unavailable: frozenset[str]) -> str:
    del unavailable
    return "n" + hashlib.sha256(symbol_id.encode("utf-8")).hexdigest()[: name_length - 1]


class MetricsVNextTests(unittest.TestCase):
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
        with unittest.TestCase().assertRaises(MetricsVNextError) as raised:
            callable_obj()
        unittest.TestCase().assertEqual(raised.exception.code, code)
        unittest.TestCase().assertTrue(str(raised.exception).startswith(f"{code}: "))

    def _metrics(self, temp: str, mapping, label: str = "run"):
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
        envelope = build_mapping_execution_vnext(execution, restored)
        return build_metrics_vnext(envelope, gate_dir=gate_dir), gate_dir

    def test_full_top_metrics_schema_effective_lines_coverage_and_leakage(self):
        mapping = self._mapping(
            FIXTURE_ROOT / "design.f",
            top="parameter_top",
            abi_categories=("parameters",),
        )
        with tempfile.TemporaryDirectory() as temp:
            metrics, gate_dir = self._metrics(temp, mapping)
            report = metrics.to_report()
            self.assertEqual(
                list(report),
                [
                    "format",
                    "schema_version",
                    "state",
                    "mapping_execution_format",
                    "filelist",
                    "effective_lines",
                    "affected_lines",
                    "symbols",
                    "occurrences",
                    "plaintext_leakage_rate",
                    "effective_coverage",
                ],
            )
            self.assertEqual(report["format"], "rtl-obfuscation.metrics-vnext")
            self.assertEqual(report["schema_version"], 1)
            self.assertEqual(report["state"], "verified")
            self.assertEqual(report["mapping_execution_format"], "rtl-obfuscation.mapping-execution-vnext")
            self.assertEqual(report["filelist"], "design.f")
            self.assertEqual(report["symbols"], {"renamed": 16, "eligible": 16, "coverage": 1.0})
            self.assertEqual(report["occurrences"], {"renamed": 41, "eligible": 41, "coverage": 1.0})
            self.assertEqual(report["plaintext_leakage_rate"], 0.0)
            self.assertEqual(report["effective_coverage"], 1.0)
            self.assertGreater(report["effective_lines"]["total"], 0)
            self.assertEqual(report["affected_lines"]["total"], report["effective_lines"]["total"])
            self.assertGreater(report["affected_lines"]["changed"], 0)
            self.assertGreater(report["affected_lines"]["rate"], 0.0)
            self.assertLessEqual(report["affected_lines"]["rate"], 1.0)
            self.assertEqual(
                [item["file"] for item in report["effective_lines"]["by_file"]],
                ["rtl/child.sv", "rtl/shadow.sv", "rtl/top.sv", "rtl/unreachable.sv"],
            )
            source_root = FIXTURE_ROOT
            expected_effective = 0
            for item in report["effective_lines"]["by_file"]:
                content = (source_root / item["file"]).read_bytes()
                expected = sum(
                    line.strip() != b"" and not line.strip().startswith(b"//")
                    for line in content.splitlines()
                )
                self.assertEqual(item["lines"], expected)
                expected_effective += expected
            self.assertEqual(report["effective_lines"]["total"], expected_effective)
            for value in (str(FIXTURE_ROOT.resolve()), "source_root", "gate_dir", "output_dir", "TemporaryDirectory"):
                self.assertNotIn(value, json.dumps(report, ensure_ascii=False))

    def test_affected_lines_are_unique_source_line_pairs(self):
        mapping = self._mapping(
            FIXTURE_ROOT / "design.f",
            top="parameter_top",
            abi_categories=("parameters",),
        )
        with tempfile.TemporaryDirectory() as temp:
            metrics, gate_dir = self._metrics(temp, mapping)
            report = metrics.to_report()
            expected: set[tuple[str, int]] = set()
            for edit in metrics.mapping_execution.rewrite_execution.edits:
                content = (FIXTURE_ROOT / edit.source_range.file).read_bytes()
                offset = 0
                for line_number, line in enumerate(content.splitlines(keepends=True), start=1):
                    end = offset + len(line)
                    if edit.source_range.start < end and edit.source_range.end > offset:
                        expected.add((edit.source_range.file, line_number))
                    offset = end
            actual_count = sum(item["lines"] for item in report["affected_lines"]["by_file"])
            self.assertEqual(actual_count, len(expected))
            self.assertEqual(actual_count, report["affected_lines"]["changed"])

    def test_single_filelist_and_single_file_metrics_are_normalized(self):
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
            filelist_metrics, _ = self._metrics(temp, filelist_mapping, "filelist")
            single_metrics, _ = self._metrics(temp, single_mapping, "single")
            filelist_json = json.dumps(filelist_metrics.to_report(), separators=(",", ":"), ensure_ascii=False)
            single_json = json.dumps(single_metrics.to_report(), separators=(",", ":"), ensure_ascii=False)
        self.assertEqual(filelist_json, single_json)

    def test_deterministic_json_is_byte_identical_and_atomic_output_is_clean(self):
        mapping = self._mapping(
            FIXTURE_ROOT / "design.f",
            top="parameter_top",
            abi_categories=("parameters",),
        )
        with tempfile.TemporaryDirectory() as temp:
            metrics, _gate_dir = self._metrics(temp, mapping)
            first = json.dumps(metrics.to_report(), separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            second = json.dumps(metrics.to_report(), separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            self.assertEqual(first, second)
            first_path = Path(temp) / "first.json"
            second_path = Path(temp) / "second.json"
            write_metrics_vnext(metrics, output_file=first_path)
            write_metrics_vnext(metrics, output_file=second_path)
            self.assertEqual(first_path.read_bytes(), second_path.read_bytes())
            self.assertEqual(json.loads(first_path.read_text(encoding="utf-8")), metrics.to_report())
            self.assertEqual(list(Path(temp).glob(".metrics-vnext-*.tmp")), [])

    def test_envelope_manifest_gate_bytes_and_equations_fail_closed(self):
        mapping = self._mapping(
            FIXTURE_ROOT / "design.f",
            top="parameter_top",
            abi_categories=("parameters",),
        )
        with tempfile.TemporaryDirectory() as temp:
            metrics, gate_dir = self._metrics(temp, mapping)
            envelope = metrics.mapping_execution
            self._assert_code(
                lambda: build_metrics_vnext(replace(envelope, schema_version=2), gate_dir=gate_dir),
                "METRICS_EXECUTION_INVALID",
            )
            bad_metrics = replace(metrics, effective_line_total=metrics.effective_line_total + 1)
            self._assert_code(lambda: bad_metrics.to_report(), "METRICS_AUDIT_INVALID")
            gate_file = gate_dir / "rtl/child.sv"
            gate_file.write_bytes(gate_file.read_bytes() + b" ")
            self._assert_code(
                lambda: build_metrics_vnext(envelope, gate_dir=gate_dir),
                "METRICS_MANIFEST_INVALID",
            )

    def test_output_and_atomic_failures_leave_no_output_or_temp_file(self):
        mapping = self._mapping(
            FIXTURE_ROOT / "design.f",
            top="parameter_top",
            abi_categories=("parameters",),
        )
        with tempfile.TemporaryDirectory() as temp:
            metrics, gate_dir = self._metrics(temp, mapping)
            existing = Path(temp) / "existing.json"
            existing.write_text("keep", encoding="utf-8")
            self._assert_code(
                lambda: write_metrics_vnext(metrics, output_file=existing),
                "METRICS_OUTPUT_INVALID",
            )
            self._assert_code(
                lambda: write_metrics_vnext(metrics, output_file=Path(temp) / "missing" / "metrics.json"),
                "METRICS_OUTPUT_INVALID",
            )
            source_output = FIXTURE_ROOT / "metrics-vnext-test.json"
            self._assert_code(
                lambda: write_metrics_vnext(metrics, output_file=source_output),
                "METRICS_OUTPUT_INVALID",
            )
            self._assert_code(
                lambda: write_metrics_vnext(metrics, output_file=gate_dir / "metrics.json"),
                "METRICS_OUTPUT_INVALID",
            )
            atomic_output = Path(temp) / "atomic-failure.json"
            with mock.patch.object(Path, "rename", side_effect=OSError("rename")):
                self._assert_code(
                    lambda: write_metrics_vnext(metrics, output_file=atomic_output),
                    "METRICS_IO_ERROR",
                )
            self.assertFalse(atomic_output.exists())
            self.assertEqual(list(Path(temp).glob(".metrics-vnext-*.tmp")), [])
            self.assertEqual(existing.read_text(encoding="utf-8"), "keep")

    def test_metrics_does_not_rebuild_semantic_inputs_or_legacy_paths(self):
        mapping = self._mapping(
            FIXTURE_ROOT / "design.f",
            top="parameter_top",
            abi_categories=("parameters",),
        )
        with tempfile.TemporaryDirectory() as temp:
            metrics, _gate_dir = self._metrics(temp, mapping)
            with (
                mock.patch.object(rewrite_vnext_module, "_source_set_from_mapping", side_effect=AssertionError("rebuild")),
                mock.patch.object(rewrite_vnext_module, "build_source_catalog", side_effect=AssertionError("catalog")),
                mock.patch.object(rewrite_vnext_module, "build_rewrite_policy", side_effect=AssertionError("policy")),
            ):
                report = metrics.to_report()
            self.assertEqual(report["symbols"]["coverage"], 1.0)
            self.assertEqual(report["occurrences"]["coverage"], 1.0)


if __name__ == "__main__":
    unittest.main()
