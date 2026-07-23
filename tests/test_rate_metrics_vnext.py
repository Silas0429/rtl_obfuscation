from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from rtl_obfuscator import mapping_vnext as mapping_vnext_module
from rtl_obfuscator import rate_vnext as rate_vnext_module
from rtl_obfuscator import rewrite as legacy_rewrite
from rtl_obfuscator import rewrite_vnext as rewrite_vnext_module
from rtl_obfuscator import symbol_graph as symbol_graph_module
from rtl_obfuscator.mapping_vnext import MappingVNext, build_mapping_vnext
from rtl_obfuscator.metrics_vnext import MetricsVNext
from rtl_obfuscator.rate_execution_vnext import (
    RateExecutionVNextError,
    RateRewriteExecutionVNext,
    write_rate_selected_gate_vnext,
)
from rtl_obfuscator.rate_metrics_vnext import (
    RateMetricsVNext,
    RateMetricsVNextError,
    build_rate_metrics_vnext,
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


class RateMetricsVNextTests(unittest.TestCase):
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
        with unittest.TestCase().assertRaises(RateMetricsVNextError) as raised:
            callable_obj()
        unittest.TestCase().assertEqual(raised.exception.code, code)
        unittest.TestCase().assertTrue(str(raised.exception).startswith(f"{code}: "))

    def _rate_metrics(self, temp: str, mapping: MappingVNext, label: str = "run") -> RateMetricsVNext:
        root = Path(temp) / label
        root.mkdir()
        gate_dir = root / "gate"
        restore_dir = root / "restore"
        selection = build_rate_selection_vnext(mapping, "0.35")
        rate_execution = write_rate_selected_gate_vnext(mapping, selection, gate_dir)
        return build_rate_metrics_vnext(
            rate_execution,
            gate_dir=gate_dir,
            restore_dir=restore_dir,
        )

    def test_actual_selected_gate_adapts_to_t047_t048_with_identity_and_report_oracles(self):
        mapping = self._mapping(
            FIXTURE_ROOT / "design.f",
            top="parameter_top",
            abi_categories=("parameters",),
        )
        with tempfile.TemporaryDirectory() as temp:
            result = self._rate_metrics(temp, mapping)
            report = result.to_report()
            self.assertEqual(
                list(report),
                [
                    "format",
                    "schema_version",
                    "state",
                    "rate_selection",
                    "mapping_execution",
                    "metrics",
                    "summary",
                ],
            )
            self.assertEqual(report["format"], "rtl-obfuscation.rate-metrics-vnext")
            self.assertEqual(report["schema_version"], 1)
            self.assertEqual(report["state"], "restored")
            self.assertIs(result.rate_execution.rate_selection.mapping_vnext, mapping)
            self.assertIs(
                result.mapping_execution.rewrite_execution,
                result.rate_execution.rewrite_execution,
            )
            self.assertIs(result.metrics.mapping_execution, result.mapping_execution)

            selected_mapping = result.rate_execution.rewrite_execution.mapping_vnext
            selected_count = sum(record.action == "rename" for record in selected_mapping.records)
            unselected_count = sum(
                record.action == "preserve" and record.reason == "rate_unselected"
                for record in selected_mapping.records
            )
            self.assertEqual(report["summary"]["mapping_records"], len(mapping.records))
            self.assertEqual(report["summary"]["selected_renamed_records"], selected_count)
            self.assertEqual(report["summary"]["rate_unselected_records"], unselected_count)
            self.assertTrue(report["summary"]["strict_compile_passed"])
            self.assertTrue(report["summary"]["restored_byte_identical"])
            self.assertEqual(
                report["summary"]["effective_line_total"],
                result.metrics.effective_line_total,
            )
            self.assertEqual(
                report["summary"]["affected_line_count"],
                result.metrics.affected_line_count,
            )
            self.assertEqual(report["metrics"]["state"], "verified")
            self.assertEqual(report["mapping_execution"]["state"], "restored")
            self.assertEqual(
                report["mapping_execution"]["summary"]["restored_input_manifest_equal"],
                True,
            )
            self.assertEqual(
                report["mapping_execution"]["summary"]["restored_byte_identical"],
                True,
            )
            self.assertEqual(report["metrics"]["plaintext_leakage_rate"], 0.0)
            self.assertEqual(report["metrics"]["effective_coverage"], 1.0)
            serialized = json.dumps(report, ensure_ascii=False, separators=(",", ":"))
            for forbidden in (
                str(FIXTURE_ROOT.resolve()),
                "source_root",
                "gate_dir",
                "restore_dir",
                "TemporaryDirectory",
            ):
                self.assertNotIn(forbidden, serialized)
            self.assertTrue(
                any(
                    (Path(temp) / "run/gate" / file).read_bytes()
                    != (FIXTURE_ROOT / file).read_bytes()
                    for file in self._physical_files(mapping)
                )
            )
            self.assertEqual(
                {
                    file: (Path(temp) / "run/restore" / file).read_bytes()
                    for file in self._physical_files(mapping)
                },
                {file: (FIXTURE_ROOT / file).read_bytes() for file in self._physical_files(mapping)},
            )

    def test_single_filelist_and_deterministic_reports_are_normalized(self):
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
            filelist_result = self._rate_metrics(temp, filelist_mapping, "filelist")
            single_result = self._rate_metrics(temp, single_mapping, "single")
            filelist_json = json.dumps(
                filelist_result.to_report(),
                ensure_ascii=False,
                separators=(",", ":"),
            )
            single_json = json.dumps(
                single_result.to_report(),
                ensure_ascii=False,
                separators=(",", ":"),
            )
            self.assertEqual(filelist_json, single_json)
            self.assertEqual(filelist_json, json.dumps(filelist_result.to_report(), ensure_ascii=False, separators=(",", ":")))

    def test_invalid_execution_restore_envelope_and_metrics_fail_closed(self):
        mapping = self._mapping(
            FIXTURE_ROOT / "design.f",
            top="parameter_top",
            abi_categories=("parameters",),
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "case"
            root.mkdir()
            gate_dir = root / "gate"
            restore_dir = root / "restore"
            selection = build_rate_selection_vnext(mapping, "0.35")
            rate_execution = write_rate_selected_gate_vnext(mapping, selection, gate_dir)
            self._assert_code(
                lambda: build_rate_metrics_vnext(object(), gate_dir=gate_dir, restore_dir=restore_dir),
                "RATE_METRICS_EXECUTION_INVALID",
            )
            self._assert_code(
                lambda: build_rate_metrics_vnext(
                    replace(rate_execution, schema_version=2),
                    gate_dir=gate_dir,
                    restore_dir=restore_dir,
                ),
                "RATE_METRICS_EXECUTION_INVALID",
            )
            other_mapping = self._mapping(
                FIXTURE_ROOT / "design.f",
                top="parameter_top",
                abi_categories=("parameters",),
            )
            other_selection = build_rate_selection_vnext(other_mapping, "0.35")
            self._assert_code(
                lambda: build_rate_metrics_vnext(
                    replace(rate_execution, rate_selection=other_selection),
                    gate_dir=gate_dir,
                    restore_dir=restore_dir,
                ),
                "RATE_METRICS_EXECUTION_INVALID",
            )

            good = build_rate_metrics_vnext(
                rate_execution,
                gate_dir=gate_dir,
                restore_dir=restore_dir,
            )
            bad_mapping_execution = replace(good.mapping_execution, schema_version=2)
            bad_mapping_metrics = replace(good.metrics, mapping_execution=bad_mapping_execution)
            self._assert_code(
                lambda: replace(
                    good,
                    mapping_execution=bad_mapping_execution,
                    metrics=bad_mapping_metrics,
                ).to_report(),
                "RATE_METRICS_ENVELOPE_INVALID",
            )
            bad_metrics = replace(
                good.metrics,
                effective_line_total=good.metrics.effective_line_total + 1,
            )
            self._assert_code(
                lambda: replace(good, metrics=bad_metrics).to_report(),
                "RATE_METRICS_INVALID",
            )

            gate_file = gate_dir / "rtl/child.sv"
            gate_bytes = gate_file.read_bytes()
            gate_file.write_bytes(gate_bytes + b" ")
            self._assert_code(
                lambda: build_rate_metrics_vnext(
                    rate_execution,
                    gate_dir=gate_dir,
                    restore_dir=root / "bad-restore",
                ),
                "RATE_METRICS_RESTORE_INVALID",
            )
            self.assertFalse((root / "bad-restore").exists())

    def test_adapter_blocks_rebuild_legacy_paths_and_identity_proof(self):
        mapping = self._mapping(
            FIXTURE_ROOT / "design.f",
            top="parameter_top",
            abi_categories=("parameters",),
        )
        selection = build_rate_selection_vnext(mapping, "0.35")
        with tempfile.TemporaryDirectory() as temp:
            gate_dir = Path(temp) / "gate"
            restore_dir = Path(temp) / "restore"
            rate_execution = write_rate_selected_gate_vnext(mapping, selection, gate_dir)
            with (
                mock.patch.object(symbol_graph_module, "build_symbol_graph", side_effect=AssertionError("graph rebuild")),
                mock.patch.object(mapping_vnext_module, "build_mapping_vnext", side_effect=AssertionError("mapping rebuild")),
                mock.patch.object(rewrite_vnext_module, "build_rewrite_policy", side_effect=AssertionError("policy rebuild")),
                mock.patch.object(legacy_rewrite, "_encrypt_project", side_effect=AssertionError("legacy rewrite")),
                mock.patch.object(legacy_rewrite, "_encrypt_filelist_manual_v4", side_effect=AssertionError("legacy rewrite")),
                mock.patch.object(legacy_rewrite, "decrypt_project", side_effect=AssertionError("legacy decrypt"), create=True),
                mock.patch.object(legacy_rewrite, "_rate_selection", side_effect=AssertionError("legacy rate"), create=True),
                mock.patch.object(rate_vnext_module, "_greedy_select", side_effect=AssertionError("rate selector")),
            ):
                result = build_rate_metrics_vnext(
                    rate_execution,
                    gate_dir=gate_dir,
                    restore_dir=restore_dir,
                )
            self.assertIs(result.rate_execution, rate_execution)
            self.assertIs(result.mapping_execution.rewrite_execution, rate_execution.rewrite_execution)
            self.assertIs(result.metrics.mapping_execution, result.mapping_execution)


if __name__ == "__main__":
    unittest.main()
