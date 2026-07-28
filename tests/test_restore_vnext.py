import argparse
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
from rtl_obfuscator import restore_vnext


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "refactor_symbol_graph_parameters"


class RestoreVNextTests(unittest.TestCase):
    @staticmethod
    def _run(operation: str, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "rtl_obfuscator.rewrite", operation, *arguments],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=180,
        )

    def _encrypt(
        self,
        root: Path,
        *,
        filelist: bool,
        rate: bool = False,
        source_root: Path = FIXTURE_ROOT,
    ) -> tuple[Path, Path]:
        root.mkdir(parents=True, exist_ok=True)
        gate = root / "gate"
        mapping = root / "orchestration.json"
        metrics = root / "metrics.json"
        arguments = [
            "--filelist" if filelist else "--input",
            str(source_root / ("design.f" if filelist else "single.sv")),
            "--source-root",
            str(source_root),
        ]
        if filelist:
            arguments.extend(("--top", "parameter_top"))
        if rate:
            arguments.extend(
                (
                    "--category", "signals",
                    "--category", "parameters",
                    "--category", "genvars",
                    "--abi-category", "parameters",
                    "--encryption-rate", "0.35",
                )
            )
        arguments.extend(
            (
                "--name-length", "16",
                "--output-dir", str(gate),
                "--map", str(mapping),
                "--metrics", str(metrics),
            )
        )
        result = self._run("encrypt-vnext", *arguments)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(gate.is_dir())
        self.assertTrue(mapping.is_file())
        self.assertTrue(metrics.is_file())
        return gate, mapping

    def _decrypt(
        self,
        gate: Path,
        mapping: Path,
        source_root: Path,
        output: Path,
        report: Path,
    ) -> subprocess.CompletedProcess[str]:
        return self._run(
            "decrypt-vnext",
            "--map", str(mapping),
            "--gate-dir", str(gate),
            "--source-root", str(source_root),
            "--output-dir", str(output),
            "--report", str(report),
        )

    @staticmethod
    def _physical_files(report: dict[str, object]) -> tuple[str, ...]:
        source_set = report["source_set"]
        assert isinstance(source_set, dict)
        return tuple(dict.fromkeys((*source_set["ordered_source_files"], *source_set["included_files"])))

    @staticmethod
    def _assert_portable(value: object) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                unittest.TestCase().assertNotIn(
                    key, {"source_root", "gate_dir", "restore_dir", "output_dir", "TemporaryDirectory"}
                )
                RestoreVNextTests._assert_portable(item)
        elif isinstance(value, list):
            for item in value:
                RestoreVNextTests._assert_portable(item)
        elif isinstance(value, str):
            unittest.TestCase().assertFalse(value.startswith("/"), value)

    def test_single_no_rate_cross_process_restore_and_determinism(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            gate, mapping = self._encrypt(root / "encrypt", filelist=False)
            first_output = root / "restore-one"
            first_report = root / "restore-one.json"
            first = self._decrypt(gate, mapping, FIXTURE_ROOT, first_output, first_report)
            self.assertEqual(first.returncode, 0, first.stderr)
            second_output = root / "restore-two"
            second_report = root / "restore-two.json"
            second = self._decrypt(gate, mapping, FIXTURE_ROOT, second_output, second_report)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(first_report.read_bytes(), second_report.read_bytes())
            persisted = json.loads(mapping.read_text(encoding="utf-8"))
            restored = json.loads(first_report.read_text(encoding="utf-8"))
            stdout = json.loads(first.stdout)
            self.assertEqual(restored["format"], "rtl-obfuscation.restore-vnext")
            self.assertEqual(restored["state"], "restored")
            self.assertEqual(stdout["format"], "rtl-obfuscation.restore-vnext-cli")
            self.assertEqual(stdout["summary"], restored["summary"])
            self.assertFalse(restored["summary"]["rate_enabled"])
            self.assertEqual(
                restored["gate_manifest"], persisted["mapping_execution"]["gate_manifest"]
            )
            self.assertEqual(
                restored["restored_manifest"], persisted["mapping_execution"]["input_manifest"]
            )
            for file in self._physical_files(persisted):
                self.assertEqual((first_output / file).read_bytes(), (FIXTURE_ROOT / file).read_bytes())
                self.assertEqual((second_output / file).read_bytes(), (FIXTURE_ROOT / file).read_bytes())
            self.assertFalse((first_output / "design.f").exists())
            self._assert_portable(restored)
            self._assert_portable(stdout)

    def test_filelist_rate_cross_process_restore_and_effective_mapping(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            gate, mapping = self._encrypt(root / "encrypt", filelist=True, rate=True)
            output = root / "restore"
            report = root / "restore.json"
            result = self._decrypt(gate, mapping, FIXTURE_ROOT, output, report)
            self.assertEqual(result.returncode, 0, result.stderr)
            persisted = json.loads(mapping.read_text(encoding="utf-8"))
            restored = json.loads(report.read_text(encoding="utf-8"))
            effective_records = persisted["mapping_execution"]["mapping"]["records"]
            self.assertTrue(persisted["summary"]["rate_enabled"])
            self.assertTrue(any(record["reason"] == "rate_unselected" for record in effective_records))
            self.assertEqual(restored["gate_manifest"], persisted["mapping_execution"]["gate_manifest"])
            self.assertEqual(restored["restored_manifest"], persisted["mapping_execution"]["input_manifest"])
            self.assertTrue(restored["summary"]["rate_enabled"])
            for file in self._physical_files(persisted):
                self.assertEqual((output / file).read_bytes(), (FIXTURE_ROOT / file).read_bytes())
            self._assert_portable(restored)

    def test_direct_restore_api_reuses_gate_audit_without_original_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            gate, mapping = self._encrypt(
                root / "encrypt",
                filelist=True,
                rate=True,
            )
            output = root / "direct-restore"
            with mock.patch.object(
                orchestration_vnext,
                "run_vnext",
                side_effect=AssertionError("regenerate orchestration"),
            ):
                restored = restore_vnext.load_direct_restore_vnext(
                    mapping,
                    gate_dir=gate,
                    output_dir=output,
                )
            self.assertTrue(restored.rate_enabled)
            self.assertEqual(
                restored.restore_result.restored_manifest,
                restored.mapping_vnext.input_manifest,
            )
            persisted = json.loads(mapping.read_text(encoding="utf-8"))
            for file in self._physical_files(persisted):
                self.assertEqual(
                    (output / file).read_bytes(),
                    (FIXTURE_ROOT / file).read_bytes(),
                )
            self.assertFalse((output / "design.f").exists())

            public_args = argparse.Namespace(
                public_cli=True,
                map_file=mapping,
                gate_dir=gate,
                output_dir=root / "public-restore",
                report=root / "public-restore.json",
            )
            with mock.patch.object(
                restore_vnext,
                "write_restore_report_vnext",
                side_effect=restore_vnext.RestoreVNextError(
                    "RESTORE_VNEXT_IO_ERROR"
                ),
            ):
                with self.assertRaises(restore_vnext.RestoreVNextError):
                    rewrite_module._decrypt_vnext(public_args)
            self.assertFalse(public_args.output_dir.exists())
            self.assertFalse(public_args.report.exists())

    def test_report_gate_source_and_malformed_inputs_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            shutil.copytree(FIXTURE_ROOT, source)
            gate, mapping = self._encrypt(root / "encrypt", filelist=True, source_root=source)

            tampered_report = root / "tampered-map.json"
            tampered = json.loads(mapping.read_text(encoding="utf-8"))
            tampered["mapping_execution"]["mapping"]["records"][0]["declaration"]["start"] += 1
            tampered_report.write_text(json.dumps(tampered), encoding="utf-8")
            result = self._decrypt(gate, tampered_report, source, root / "bad-report-output", root / "bad-report.json")
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(result.stderr.startswith("error: RESTORE_VNEXT_REPORT_INVALID"), result.stderr)
            self.assertFalse((root / "bad-report-output").exists())
            self.assertFalse((root / "bad-report.json").exists())

            tampered_gate = root / "tampered-gate"
            shutil.copytree(gate, tampered_gate)
            physical = tampered["source_set"]["ordered_source_files"][0]
            gate_file = tampered_gate / physical
            gate_file.write_bytes(gate_file.read_bytes() + b" ")
            result = self._decrypt(gate=tampered_gate, mapping=mapping, source_root=source, output=root / "bad-gate-output", report=root / "bad-gate.json")
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(result.stderr.startswith("error: RESTORE_VNEXT_GATE_INVALID"), result.stderr)
            self.assertFalse((root / "bad-gate-output").exists())
            self.assertFalse((root / "bad-gate.json").exists())

            source_file = source / physical
            source_file.write_bytes(source_file.read_bytes() + b" ")
            result = self._decrypt(gate, mapping, source, root / "bad-source-output", root / "bad-source.json")
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(result.stderr.startswith("error: RESTORE_VNEXT_REPORT_INVALID"), result.stderr)
            self.assertFalse((root / "bad-source-output").exists())
            self.assertFalse((root / "bad-source.json").exists())

            malformed = root / "malformed.json"
            malformed.write_text("{", encoding="utf-8")
            result = self._decrypt(gate, malformed, source, root / "bad-json-output", root / "bad-json.json")
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(result.stderr.startswith("error: RESTORE_VNEXT_IO_ERROR"), result.stderr)
            self.assertFalse((root / "bad-json-output").exists())
            self.assertFalse((root / "bad-json.json").exists())

    def test_path_conflicts_missing_inputs_and_publish_failure_are_clean(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            gate, mapping = self._encrypt(root / "encrypt", filelist=False)
            existing = root / "existing"
            existing.mkdir()
            result = self._decrypt(gate, mapping, FIXTURE_ROOT, existing, root / "existing.json")
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(result.stderr.startswith("error: RESTORE_VNEXT_OUTPUT_INVALID"), result.stderr)
            result = self._decrypt(gate, mapping, FIXTURE_ROOT, FIXTURE_ROOT, root / "overlap.json")
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(result.stderr.startswith("error: RESTORE_VNEXT_OUTPUT_INVALID"), result.stderr)
            missing_gate = root / "missing-gate"
            result = self._decrypt(missing_gate, mapping, FIXTURE_ROOT, root / "missing-output", root / "missing.json")
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(result.stderr.startswith("error: RESTORE_VNEXT_GATE_INVALID"), result.stderr)
            self.assertFalse((root / "missing-output").exists())
            self.assertFalse((root / "missing.json").exists())

            missing_report = self._run(
                "decrypt-vnext",
                "--map", str(mapping),
                "--gate-dir", str(gate),
                "--source-root", str(FIXTURE_ROOT),
                "--output-dir", str(root / "missing-report-output"),
            )
            self.assertNotEqual(missing_report.returncode, 0)
            self.assertEqual(missing_report.stderr, "error: RESTORE_VNEXT_OUTPUT_INVALID\n")
            self.assertNotIn("Traceback", missing_report.stderr)
            self.assertFalse((root / "missing-report-output").exists())

            args = argparse.Namespace(
                map_file=mapping,
                gate_dir=gate,
                source_root=FIXTURE_ROOT,
                output_dir=root / "forced-output",
                report=root / "forced.json",
            )
            with mock.patch.object(
                restore_vnext,
                "write_restore_report_vnext",
                side_effect=restore_vnext.RestoreVNextError("RESTORE_VNEXT_IO_ERROR"),
            ):
                with self.assertRaises(restore_vnext.RestoreVNextError):
                    rewrite_module._decrypt_vnext(args)
            self.assertFalse(args.output_dir.exists())
            self.assertFalse(args.report.exists())
            self.assertEqual(list(root.glob(".restore-vnext-publish-*")), [])

            publish_source = root / "publish-source"
            publish_source.mkdir()
            (publish_source / "a.sv").write_bytes(b"module a; endmodule\n")
            with self.assertRaises(restore_vnext.RestoreVNextError) as raised:
                restore_vnext.publish_restore_vnext(
                    [
                        (publish_source, root / "published-gate"),
                        (root / "missing-report.json", root / "published-report.json"),
                    ]
                )
            self.assertEqual(raised.exception.code, "RESTORE_VNEXT_OUTPUT_INVALID")
            self.assertFalse((root / "published-gate").exists())
            self.assertFalse((root / "published-report.json").exists())
            self.assertEqual(list(root.glob(".restore-vnext-publish-*")), [])

    def test_decrypt_vnext_blocks_legacy_and_regeneration_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            gate, mapping = self._encrypt(root / "encrypt", filelist=False)
            args = argparse.Namespace(
                map_file=mapping,
                gate_dir=gate,
                source_root=FIXTURE_ROOT,
                output_dir=root / "restore",
                report=root / "restore.json",
            )
            with mock.patch.object(orchestration_vnext, "run_vnext", side_effect=AssertionError("regenerate orchestration")):
                summary = rewrite_module._decrypt_vnext(args)
            self.assertEqual(summary["format"], "rtl-obfuscation.restore-vnext-cli")
            self.assertTrue(args.output_dir.is_dir())
            self.assertTrue(args.report.is_file())


if __name__ == "__main__":
    unittest.main()
