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

from rtl_obfuscator import orchestration_vnext as orchestration_module
from rtl_obfuscator import rewrite as legacy_rewrite
from rtl_obfuscator import source_catalog as source_catalog_module
from rtl_obfuscator import symbol_graph as symbol_graph_module
from rtl_obfuscator.mapping_vnext import MappingVNext
from rtl_obfuscator.rate_metrics_vnext import RateMetricsVNext
from rtl_obfuscator.rewrite_vnext import RewriteVNextError
from rtl_obfuscator.source_catalog import build_source_catalog
from rtl_obfuscator.source_set import SourceSet, from_filelist, from_single_file


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "refactor_symbol_graph_parameters"
_CATEGORIES = ("signals", "parameters", "genvars")
_ABI_CATEGORIES = ("parameters",)


def _deterministic_factory(symbol_id: str, name_length: int, unavailable: frozenset[str]) -> str:
    del unavailable
    return "n" + hashlib.sha256(symbol_id.encode("utf-8")).hexdigest()[: name_length - 1]


class OrchestrationVNextTests(unittest.TestCase):
    @staticmethod
    def _source_set(*, filelist: bool = True, single_file: bool = False) -> SourceSet:
        if single_file:
            return from_single_file(
                source_file=FIXTURE_ROOT / "single.sv",
                source_root=FIXTURE_ROOT,
            )
        if filelist:
            return from_filelist(
                filelist=FIXTURE_ROOT / "design.f",
                source_root=FIXTURE_ROOT,
                top="parameter_top",
            )
        raise AssertionError("unsupported source-set helper mode")

    @staticmethod
    def _run(
        source_set: SourceSet,
        root: Path,
        *,
        encryption_rate: str | None,
        abi_categories: tuple[str, ...] = _ABI_CATEGORIES,
    ) -> orchestration_module.OrchestrationVNext:
        root.mkdir(parents=True, exist_ok=True)
        return orchestration_module.run_vnext(
            source_set,
            categories=_CATEGORIES,
            abi_categories=abi_categories,
            name_length=16,
            name_factory=_deterministic_factory,
            encryption_rate=encryption_rate,
            gate_dir=root / "gate",
            restore_dir=root / "restore",
        )

    @staticmethod
    def _assert_code(callable_obj, code: str) -> None:
        with unittest.TestCase().assertRaises(orchestration_module.OrchestrationVNextError) as raised:
            callable_obj()
        unittest.TestCase().assertEqual(raised.exception.code, code)
        unittest.TestCase().assertTrue(str(raised.exception).startswith(f"{code}: "))

    @staticmethod
    def _formal(gate_dir: Path) -> subprocess.CompletedProcess[str]:
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

    @staticmethod
    def _physical_files(source_set: SourceSet) -> tuple[str, ...]:
        return tuple(dict.fromkeys((*source_set.ordered_source_files, *source_set.included_files)))

    @staticmethod
    def _portable_json(report: dict[str, object]) -> str:
        normalized = json.loads(json.dumps(report, ensure_ascii=False))
        normalized["source_set"].pop("origin", None)
        normalized["summary"].pop("origin", None)
        return json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))

    def test_no_rate_actual_gate_restore_metrics_identity_and_report(self):
        source_set = self._source_set()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = self._run(source_set, root, encryption_rate=None)
            report = result.to_report()
            self.assertEqual(
                list(report),
                [
                    "format",
                    "schema_version",
                    "state",
                    "source_set",
                    "mapping",
                    "mapping_execution",
                    "metrics",
                    "rate_metrics",
                    "summary",
                ],
            )
            self.assertEqual(report["format"], "rtl-obfuscation.orchestration-vnext")
            self.assertEqual(report["state"], "restored")
            self.assertIs(result.mapping_vnext, result.effective_mapping_vnext)
            self.assertIs(result.metrics.mapping_execution, result.mapping_execution)
            self.assertIs(
                result.mapping_vnext.rewrite_policy.symbol_graph.source_catalog.source_set,
                source_set,
            )
            self.assertTrue(report["summary"]["strict_compile_passed"])
            self.assertTrue(report["summary"]["restored_byte_identical"])
            self.assertEqual(report["summary"]["files"], 4)
            self.assertEqual(report["summary"]["mapping_records"], 20)
            self.assertEqual(report["summary"]["effective_mapping_records"], 20)
            self.assertEqual(report["summary"]["modified_tokens"], 41)
            self.assertIsNone(result.rate_metrics)
            self.assertEqual(report["metrics"]["symbols"]["coverage"], 1.0)
            self.assertEqual(report["metrics"]["occurrences"]["coverage"], 1.0)
            self.assertEqual(report["metrics"]["plaintext_leakage_rate"], 0.0)
            self.assertEqual(report["metrics"]["effective_coverage"], 1.0)
            serialized = json.dumps(report, ensure_ascii=False, separators=(",", ":"))
            self.assertNotIn(str(FIXTURE_ROOT.resolve()), serialized)
            self.assertNotIn("source_root", serialized)
            self.assertNotIn("gate_dir", serialized)
            gold = {
                file: (FIXTURE_ROOT / file).read_bytes()
                for file in self._physical_files(source_set)
            }
            self.assertEqual(
                {file: (root / "restore" / file).read_bytes() for file in gold},
                gold,
            )

    def test_rate_actual_selected_gate_restore_rate_metrics_identity_and_report(self):
        source_set = self._source_set()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = self._run(source_set, root, encryption_rate="0.35")
            report = result.to_report()
            self.assertIsInstance(result.rate_metrics, RateMetricsVNext)
            self.assertIs(result.rate_metrics.mapping_execution, result.mapping_execution)
            self.assertIs(result.rate_metrics.metrics, result.metrics)
            self.assertIs(
                result.rate_metrics.rate_execution.rate_selection.mapping_vnext,
                result.mapping_vnext,
            )
            self.assertIs(
                result.effective_mapping_vnext,
                result.rate_metrics.rate_execution.rewrite_execution.mapping_vnext,
            )
            self.assertTrue(report["summary"]["rate_enabled"])
            self.assertEqual(report["summary"]["mapping_records"], 20)
            self.assertEqual(report["summary"]["effective_mapping_records"], 20)
            self.assertTrue(report["summary"]["strict_compile_passed"])
            self.assertTrue(report["summary"]["restored_byte_identical"])
            self.assertEqual(report["rate_metrics"]["state"], "restored")
            self.assertEqual(report["metrics"]["state"], "verified")
            self.assertEqual(report["metrics"]["plaintext_leakage_rate"], 0.0)
            self.assertEqual(report["metrics"]["effective_coverage"], 1.0)

            positive = self._formal(root / "gate")
            self.assertEqual(positive.returncode, 0, positive.stdout + positive.stderr)
            positive_payload = json.loads(positive.stdout.strip().splitlines()[-1])
            self.assertEqual(positive_payload["formal_equivalence"], "pass")
            self.assertEqual(positive_payload["top"], "parameter_top")
            self.assertEqual(positive_payload["seq"], 5)

            negative_dir = root / "negative"
            shutil.copytree(root / "gate", negative_dir)
            child = negative_dir / "rtl/child.sv"
            content = child.read_bytes()
            needle = b"assign data_o = "
            self.assertEqual(content.count(needle), 1)
            position = content.index(needle) + len(needle)
            child.write_bytes(content[:position] + b"~" + content[position:])
            negative_source_set = replace(source_set, source_root=negative_dir.resolve())
            self.assertEqual(
                build_source_catalog(negative_source_set).to_report()["compile"],
                {
                    "catalog": {"parse_errors": 0, "semantic_errors": 0},
                    "top_overlay": {"parse_errors": 0, "semantic_errors": 0},
                },
            )
            negative = self._formal(negative_dir)
            combined = (negative.stdout + negative.stderr).lower()
            self.assertNotEqual(negative.returncode, 0)
            self.assertIn("unproven", combined)
            self.assertIn("equiv_status -assert", combined)

    def test_single_file_and_filelist_reports_are_normalized_and_deterministic(self):
        filelist_source_set = from_filelist(
            filelist=FIXTURE_ROOT / "single.f",
            source_root=FIXTURE_ROOT,
        )
        single_source_set = from_single_file(
            source_file=FIXTURE_ROOT / "single.sv",
            source_root=FIXTURE_ROOT,
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            filelist_result = self._run(
                filelist_source_set,
                root / "filelist",
                encryption_rate="0.35",
                abi_categories=(),
            )
            single_result = self._run(
                single_source_set,
                root / "single",
                encryption_rate="0.35",
                abi_categories=(),
            )
            filelist_json = self._portable_json(filelist_result.to_report())
            single_json = self._portable_json(single_result.to_report())
            self.assertEqual(filelist_json, single_json)
            self.assertEqual(filelist_json, self._portable_json(filelist_result.to_report()))

    def test_input_rate_output_manifest_and_restore_fail_closed(self):
        source_set = self._source_set()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project_root = replace(source_set, origin="project-root")
            self._assert_code(
                lambda: self._run(project_root, root / "project", encryption_rate=None),
                "ORCHESTRATION_INPUT_INVALID",
            )
            self._assert_code(
                lambda: self._run(source_set, root / "bad-rate", encryption_rate=""),
                "ORCHESTRATION_RATE_INVALID",
            )
            existing = root / "existing"
            existing.mkdir()
            self._assert_code(
                lambda: orchestration_module.run_vnext(
                    source_set,
                    categories=_CATEGORIES,
                    abi_categories=_ABI_CATEGORIES,
                    name_factory=_deterministic_factory,
                    gate_dir=existing,
                    restore_dir=root / "restore-existing",
                ),
                "ORCHESTRATION_INPUT_INVALID",
            )
            with mock.patch.object(
                orchestration_module,
                "restore_gate_vnext",
                side_effect=RewriteVNextError("RESTORE_IO_ERROR", "forced restore failure"),
            ):
                self._assert_code(
                    lambda: self._run(source_set, root / "restore-failure", encryption_rate=None),
                    "ORCHESTRATION_EXECUTION_INVALID",
                )
            self.assertFalse((root / "restore-failure" / "gate").exists())
            self.assertFalse((root / "restore-failure" / "restore").exists())

    def test_pipeline_builders_are_single_pass_and_legacy_paths_are_blocked(self):
        source_set = self._source_set()
        real_catalog = orchestration_module.build_source_catalog
        real_graph = orchestration_module.build_symbol_graph
        real_policy = orchestration_module.build_rewrite_policy
        real_mapping = orchestration_module.build_mapping_vnext
        with tempfile.TemporaryDirectory() as temp:
            with (
                mock.patch.object(orchestration_module, "build_source_catalog", wraps=real_catalog) as catalog,
                mock.patch.object(orchestration_module, "build_symbol_graph", wraps=real_graph) as graph,
                mock.patch.object(orchestration_module, "build_rewrite_policy", wraps=real_policy) as policy,
                mock.patch.object(orchestration_module, "build_mapping_vnext", wraps=real_mapping) as mapping,
                mock.patch.object(legacy_rewrite, "_encrypt_project", side_effect=AssertionError("legacy rewrite")),
                mock.patch.object(legacy_rewrite, "_encrypt_filelist_manual_v4", side_effect=AssertionError("legacy rewrite")),
                mock.patch.object(legacy_rewrite, "decrypt_project", side_effect=AssertionError("legacy decrypt"), create=True),
            ):
                result = self._run(source_set, Path(temp) / "run", encryption_rate="0.35")
            self.assertEqual(catalog.call_count, 1)
            self.assertEqual(graph.call_count, 1)
            self.assertEqual(policy.call_count, 1)
            self.assertEqual(mapping.call_count, 1)
            self.assertIs(result.mapping_vnext.rewrite_policy.symbol_graph.source_catalog.source_set, source_set)
            self.assertTrue(result.to_report()["summary"]["strict_compile_passed"])

    def test_rate_restore_adapter_failure_is_audit_error_without_artifacts(self):
        source_set = self._source_set()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "rate-failure"
            with mock.patch.object(
                orchestration_module,
                "build_rate_metrics_vnext",
                side_effect=orchestration_module.RateMetricsVNextError(
                    "RATE_METRICS_RESTORE_INVALID", "forced restore failure"
                ),
            ):
                self._assert_code(
                    lambda: self._run(source_set, root, encryption_rate="0.35"),
                    "ORCHESTRATION_AUDIT_INVALID",
                )
            self.assertFalse((root / "gate").exists())
            self.assertFalse((root / "restore").exists())


if __name__ == "__main__":
    unittest.main()
