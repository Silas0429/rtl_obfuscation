from dataclasses import replace
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from rtl_obfuscator import orchestration_vnext
from rtl_obfuscator import rewrite as rewrite_module
from rtl_obfuscator import rewrite as legacy_rewrite
from rtl_obfuscator.source_catalog import build_source_catalog
from rtl_obfuscator.source_set import from_filelist


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "refactor_symbol_graph_parameters"


class CliVNextEncryptionTests(unittest.TestCase):
    @staticmethod
    def _run_cli(*arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "rtl_obfuscator.rewrite", "encrypt-vnext", *arguments],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=180,
        )

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
    def _assert_cli_error(result: subprocess.CompletedProcess[str], code: str) -> None:
        unittest.TestCase().assertNotEqual(result.returncode, 0)
        unittest.TestCase().assertTrue(result.stderr.startswith(f"error: {code}"), result.stderr)
        unittest.TestCase().assertNotIn(str(FIXTURE_ROOT.resolve()), result.stderr)

    @staticmethod
    def _assert_portable(value: object) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                unittest.TestCase().assertNotIn(
                    key, {"source_root", "gate_dir", "restore_dir", "TemporaryDirectory"}
                )
                CliVNextEncryptionTests._assert_portable(item)
        elif isinstance(value, list):
            for item in value:
                CliVNextEncryptionTests._assert_portable(item)
        elif isinstance(value, str):
            unittest.TestCase().assertFalse(value.startswith("/"), value)

    @staticmethod
    def _normalize(value: object) -> object:
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                if key in {"origin", "renamed_name"} or key.endswith("sha256"):
                    continue
                result[key] = CliVNextEncryptionTests._normalize(item)
            return result
        if isinstance(value, list):
            return [CliVNextEncryptionTests._normalize(item) for item in value]
        return value

    def test_single_file_no_rate_publishes_gate_reports_and_summary(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            gate = root / "gate"
            map_file = root / "orchestration.json"
            metrics_file = root / "metrics.json"
            result = self._run_cli(
                "--input",
                str(FIXTURE_ROOT / "single.sv"),
                "--source-root",
                str(FIXTURE_ROOT),
                "--name-length",
                "16",
                "--output-dir",
                str(gate),
                "--map",
                str(map_file),
                "--metrics",
                str(metrics_file),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            stdout = json.loads(result.stdout)
            report = json.loads(map_file.read_text(encoding="utf-8"))
            metrics = json.loads(metrics_file.read_text(encoding="utf-8"))
            self.assertEqual(stdout["format"], "rtl-obfuscation.cli-vnext")
            self.assertEqual(stdout["state"], "restored")
            self.assertEqual(stdout["summary"], report["summary"])
            self.assertEqual(report["format"], "rtl-obfuscation.orchestration-vnext")
            self.assertEqual(metrics["format"], "rtl-obfuscation.metrics-vnext")
            self.assertEqual(metrics["state"], "verified")
            self.assertEqual(
                json.dumps(report, ensure_ascii=False, separators=(",", ":")),
                map_file.read_text(encoding="utf-8"),
            )
            self.assertEqual(
                json.dumps(metrics, ensure_ascii=False, separators=(",", ":")),
                metrics_file.read_text(encoding="utf-8"),
            )
            self._assert_portable(stdout)
            self._assert_portable(report)
            self._assert_portable(metrics)
            self.assertTrue((gate / "single.sv").is_file())
            self.assertFalse((root / "restore").exists())

    def test_filelist_rate_actual_gate_formal_and_functional_negative(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            gate = root / "gate"
            map_file = root / "orchestration.json"
            metrics_file = root / "metrics.json"
            result = self._run_cli(
                "--filelist",
                str(FIXTURE_ROOT / "design.f"),
                "--source-root",
                str(FIXTURE_ROOT),
                "--top",
                "parameter_top",
                "--category",
                "signals",
                "--category",
                "parameters",
                "--category",
                "genvars",
                "--abi-category",
                "parameters",
                "--encryption-rate",
                "0.35",
                "--name-length",
                "16",
                "--output-dir",
                str(gate),
                "--map",
                str(map_file),
                "--metrics",
                str(metrics_file),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(map_file.read_text(encoding="utf-8"))
            metrics = json.loads(metrics_file.read_text(encoding="utf-8"))
            self.assertTrue(report["summary"]["rate_enabled"])
            self.assertEqual(report["rate_metrics"]["state"], "restored")
            self.assertTrue(report["summary"]["strict_compile_passed"])
            self.assertTrue(report["summary"]["restored_byte_identical"])
            self.assertEqual(metrics["state"], "verified")
            self.assertEqual(metrics["plaintext_leakage_rate"], 0.0)
            self.assertEqual(metrics["effective_coverage"], 1.0)

            positive = self._formal(gate)
            self.assertEqual(positive.returncode, 0, positive.stdout + positive.stderr)
            positive_json = json.loads(positive.stdout.strip().splitlines()[-1])
            self.assertEqual(positive_json["formal_equivalence"], "pass")
            self.assertEqual(positive_json["top"], "parameter_top")
            self.assertEqual(positive_json["seq"], 5)

            negative = root / "negative"
            shutil.copytree(gate, negative)
            child = negative / "rtl/child.sv"
            original = child.read_bytes()
            needle = b"assign data_o = "
            self.assertEqual(original.count(needle), 1)
            position = original.index(needle) + len(needle)
            child.write_bytes(original[:position] + b"~" + original[position:])
            negative_source_set = from_filelist(
                filelist=negative / "design.f",
                source_root=negative,
                top="parameter_top",
            )
            self.assertEqual(
                build_source_catalog(negative_source_set).to_report()["compile"],
                {
                    "catalog": {"parse_errors": 0, "semantic_errors": 0},
                    "top_overlay": {"parse_errors": 0, "semantic_errors": 0},
                },
            )
            negative_formal = self._formal(negative)
            combined = (negative_formal.stdout + negative_formal.stderr).lower()
            self.assertNotEqual(negative_formal.returncode, 0)
            self.assertIn("unproven", combined)
            self.assertIn("equiv_status -assert", combined)

    def test_single_file_and_filelist_outputs_are_normalized_and_deterministic(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            outputs = []
            for mode in ("single", "filelist"):
                mode_root = root / mode
                mode_root.mkdir()
                arguments = (
                    (
                        "--input",
                        str(FIXTURE_ROOT / "single.sv"),
                    )
                    if mode == "single"
                    else (
                        "--filelist",
                        str(FIXTURE_ROOT / "single.f"),
                    )
                )
                result = self._run_cli(
                    *arguments,
                    "--source-root",
                    str(FIXTURE_ROOT),
                    "--category",
                    "signals",
                    "--category",
                    "parameters",
                    "--encryption-rate",
                    "0.35",
                    "--name-length",
                    "16",
                    "--output-dir",
                    str(mode_root / "gate"),
                    "--map",
                    str(mode_root / "map.json"),
                    "--metrics",
                    str(mode_root / "metrics.json"),
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                report = json.loads((mode_root / "map.json").read_text(encoding="utf-8"))
                metrics = json.loads((mode_root / "metrics.json").read_text(encoding="utf-8"))
                outputs.append((self._normalize(report), self._normalize(metrics)))
                self.assertEqual(
                    json.dumps(report, ensure_ascii=False, separators=(",", ":")),
                    (mode_root / "map.json").read_text(encoding="utf-8"),
                )
            self.assertEqual(outputs[0], outputs[1])

    def test_invalid_input_rate_and_outputs_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            common = (
                "--source-root",
                str(FIXTURE_ROOT),
                "--output-dir",
                str(root / "gate"),
                "--map",
                str(root / "map.json"),
                "--metrics",
                str(root / "metrics.json"),
            )
            missing = self._run_cli(*common)
            self._assert_cli_error(missing, "CLI_VNEXT_INPUT_INVALID")
            both = self._run_cli(
                "--input",
                str(FIXTURE_ROOT / "single.sv"),
                "--filelist",
                str(FIXTURE_ROOT / "single.f"),
                *common,
            )
            self._assert_cli_error(both, "CLI_VNEXT_INPUT_INVALID")
            bad_rate = self._run_cli(
                "--input",
                str(FIXTURE_ROOT / "single.sv"),
                "--encryption-rate",
                "2",
                *common,
            )
            self._assert_cli_error(bad_rate, "CLI_VNEXT_RATE_INVALID")
            existing = root / "existing"
            existing.mkdir()
            existing_output = self._run_cli(
                "--input",
                str(FIXTURE_ROOT / "single.sv"),
                "--output-dir",
                str(existing),
                "--map",
                str(root / "existing-map.json"),
                "--metrics",
                str(root / "existing-metrics.json"),
                "--source-root",
                str(FIXTURE_ROOT),
            )
            self._assert_cli_error(existing_output, "CLI_VNEXT_OUTPUT_INVALID")
            self.assertEqual(list(root.iterdir()), [existing])

    def test_t052_json_publish_failures_clean_all_outputs_and_legacy_is_not_called(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            args = type(
                "Args",
                (),
                {
                    "input_file": FIXTURE_ROOT / "single.sv",
                    "filelist": None,
                    "source_root": FIXTURE_ROOT,
                    "include_dirs": [],
                    "defines": [],
                    "top": None,
                    "category": None,
                    "abi_category": None,
                    "encryption_rate": None,
                    "name_length": "16",
                    "output_dir": root / "gate",
                    "map_file": root / "map.json",
                    "metrics_file": root / "metrics.json",
                },
            )()
            with mock.patch.object(
                orchestration_vnext,
                "run_vnext",
                side_effect=orchestration_vnext.OrchestrationVNextError(
                    "ORCHESTRATION_EXECUTION_INVALID", "forced failure"
                ),
            ):
                with self.assertRaises(rewrite_module._CliVNextError) as raised:
                    rewrite_module._encrypt_vnext(args)
            self.assertEqual(raised.exception.code, "CLI_VNEXT_ORCHESTRATION_INVALID")
            self.assertFalse((root / "gate").exists())
            self.assertFalse((root / "map.json").exists())
            self.assertFalse((root / "metrics.json").exists())

            with mock.patch.object(
                rewrite_module,
                "_cli_vnext_write_json_atomic",
                side_effect=rewrite_module._CliVNextError("CLI_VNEXT_IO_ERROR"),
            ):
                with self.assertRaises(rewrite_module._CliVNextError) as raised:
                    rewrite_module._encrypt_vnext(args)
            self.assertEqual(raised.exception.code, "CLI_VNEXT_IO_ERROR")
            self.assertFalse((root / "gate").exists())
            self.assertFalse((root / "map.json").exists())
            self.assertFalse((root / "metrics.json").exists())

            with (
                mock.patch.object(legacy_rewrite, "_encrypt", side_effect=AssertionError("legacy encrypt")),
                mock.patch.object(legacy_rewrite, "_encrypt_project", side_effect=AssertionError("legacy project")),
                mock.patch.object(legacy_rewrite, "_decrypt", side_effect=AssertionError("legacy decrypt")),
                mock.patch.object(legacy_rewrite, "_decrypt_project", side_effect=AssertionError("legacy project decrypt")),
            ):
                summary = rewrite_module._encrypt_vnext(args)
            self.assertEqual(summary["format"], "rtl-obfuscation.cli-vnext")
            self.assertTrue((root / "gate").is_dir())
            self.assertTrue((root / "map.json").is_file())
            self.assertTrue((root / "metrics.json").is_file())


if __name__ == "__main__":
    unittest.main()
