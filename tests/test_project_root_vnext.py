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
from rtl_obfuscator.source_catalog import build_source_catalog
from rtl_obfuscator.source_set import from_filelist


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "refactor_symbol_graph_parameters"


class ProjectRootVNextTests(unittest.TestCase):
    @staticmethod
    def _run(operation: str, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "rtl_obfuscator.rewrite", operation, *arguments],
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
                "tests/fixtures/refactor_symbol_graph_parameters/closure.f",
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
    def _encrypt_args(
        *,
        project_root: bool,
        root: Path,
        rate: bool = False,
    ) -> tuple[str, ...]:
        args = [
            "--project-root" if project_root else "--filelist",
            str(FIXTURE_ROOT if project_root else FIXTURE_ROOT / "closure.f"),
            "--top",
            "parameter_top",
        ]
        if not project_root:
            args.extend(("--source-root", str(FIXTURE_ROOT)))
        if rate:
            args.extend(
                (
                    "--category", "signals",
                    "--category", "parameters",
                    "--category", "genvars",
                    "--abi-category", "parameters",
                    "--encryption-rate", "0.35",
                )
            )
        args.extend(
            (
                "--name-length", "16",
                "--output-dir", str(root / "gate"),
                "--map", str(root / "orchestration.json"),
                "--metrics", str(root / "metrics.json"),
            )
        )
        return tuple(args)

    def _encrypt(self, root: Path, *, project_root: bool, rate: bool = False) -> tuple[Path, Path]:
        root.mkdir(parents=True, exist_ok=True)
        result = self._run("encrypt-vnext", *self._encrypt_args(project_root=project_root, root=root, rate=rate))
        self.assertEqual(result.returncode, 0, result.stderr)
        return root / "gate", root / "orchestration.json"

    @staticmethod
    def _normalize(value: object) -> object:
        if isinstance(value, dict):
            return {
                key: ProjectRootVNextTests._normalize(item)
                for key, item in value.items()
                if key not in {"origin", "renamed_name"} and not key.endswith("sha256")
            }
        if isinstance(value, list):
            return [ProjectRootVNextTests._normalize(item) for item in value]
        return value

    @staticmethod
    def _assert_portable(value: object) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                unittest.TestCase().assertNotIn(
                    key, {"source_root", "gate_dir", "restore_dir", "output_dir", "temporary_directory"}
                )
                ProjectRootVNextTests._assert_portable(item)
        elif isinstance(value, list):
            for item in value:
                ProjectRootVNextTests._assert_portable(item)
        elif isinstance(value, str):
            unittest.TestCase().assertFalse(value.startswith("/"), value)

    @staticmethod
    def _physical_files(report: dict[str, object]) -> tuple[str, ...]:
        source_set = report["source_set"]
        assert isinstance(source_set, dict)
        return tuple(dict.fromkeys((*source_set["ordered_source_files"], *source_set["included_files"])))

    def test_project_root_no_rate_matches_equivalent_filelist(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project_gate, project_map = self._encrypt(root / "project", project_root=True)
            filelist_gate, filelist_map = self._encrypt(root / "filelist", project_root=False)
            project_report = json.loads(project_map.read_text(encoding="utf-8"))
            filelist_report = json.loads(filelist_map.read_text(encoding="utf-8"))
            self.assertEqual(project_report["source_set"]["origin"], "project-root")
            self.assertEqual(filelist_report["source_set"]["origin"], "filelist")
            self.assertEqual(self._normalize(project_report), self._normalize(filelist_report))
            self.assertEqual(
                project_report["source_set"]["ordered_source_files"],
                ["rtl/child.sv", "rtl/shadow.sv", "rtl/top.sv"],
            )
            self.assertEqual(
                project_report["source_set"]["top_closure_files"],
                project_report["source_set"]["ordered_source_files"],
            )
            self.assertEqual(
                project_report["source_set"]["compile_order"],
                project_report["source_set"]["ordered_source_files"],
            )
            self.assertTrue(project_report["summary"]["strict_compile_passed"])
            self.assertTrue(project_report["summary"]["restored_byte_identical"])
            self.assertNotIn("rtl/unreachable.sv", self._physical_files(project_report))
            self.assertNotIn("rtl/unreachable.sv", [path.name for path in project_gate.rglob("*")])
            self.assertFalse((project_gate / "rtl/unreachable.sv").exists())
            self.assertFalse((filelist_gate / "rtl/unreachable.sv").exists())
            self._assert_portable(project_report)

    def test_project_root_rate_restore_formal_and_functional_negative(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            gate, mapping = self._encrypt(root / "project", project_root=True, rate=True)
            report = json.loads(mapping.read_text(encoding="utf-8"))
            self.assertEqual(report["source_set"]["origin"], "project-root")
            self.assertTrue(report["summary"]["rate_enabled"])
            self.assertTrue(report["summary"]["strict_compile_passed"])
            self.assertTrue(report["summary"]["restored_byte_identical"])
            self.assertTrue(any(
                record["reason"] == "rate_unselected"
                for record in report["mapping_execution"]["mapping"]["records"]
            ))
            self.assertNotIn("rtl/unreachable.sv", self._physical_files(report))
            self._assert_portable(report)

            restore = root / "restore"
            restore_report_path = root / "restore.json"
            decrypted = self._run(
                "decrypt-vnext",
                "--map", str(mapping),
                "--gate-dir", str(gate),
                "--source-root", str(FIXTURE_ROOT),
                "--output-dir", str(restore),
                "--report", str(restore_report_path),
            )
            self.assertEqual(decrypted.returncode, 0, decrypted.stderr)
            restored_report = json.loads(restore_report_path.read_text(encoding="utf-8"))
            self.assertEqual(restored_report["gate_manifest"], report["mapping_execution"]["gate_manifest"])
            self.assertEqual(restored_report["restored_manifest"], report["mapping_execution"]["input_manifest"])
            self.assertTrue(restored_report["summary"]["restored_byte_identical"])
            self.assertFalse((restore / "design.f").exists())
            for file in self._physical_files(report):
                self.assertEqual((restore / file).read_bytes(), (FIXTURE_ROOT / file).read_bytes())

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

    def test_project_root_fail_closed_and_legacy_paths_are_isolated(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            common = (
                "--project-root", str(FIXTURE_ROOT),
                "--top", "parameter_top",
                "--name-length", "16",
                "--output-dir", str(root / "gate"),
                "--map", str(root / "map.json"),
                "--metrics", str(root / "metrics.json"),
            )
            both = self._run(
                "encrypt-vnext", "--input", str(FIXTURE_ROOT / "single.sv"), *common
            )
            self.assertNotEqual(both.returncode, 0)
            self.assertTrue(both.stderr.startswith("error: CLI_VNEXT_INPUT_INVALID"), both.stderr)
            missing_top = self._run(
                "encrypt-vnext", "--project-root", str(FIXTURE_ROOT),
                "--name-length", "16", "--output-dir", str(root / "missing-gate"),
                "--map", str(root / "missing-map.json"), "--metrics", str(root / "missing-metrics.json"),
            )
            self.assertNotEqual(missing_top.returncode, 0)
            self.assertTrue(missing_top.stderr.startswith("error: CLI_VNEXT_INPUT_INVALID"), missing_top.stderr)
            source_root_conflict = self._run(
                "encrypt-vnext", "--project-root", str(FIXTURE_ROOT), "--source-root", str(FIXTURE_ROOT),
                "--top", "parameter_top", "--name-length", "16", "--output-dir", str(root / "source-gate"),
                "--map", str(root / "source-map.json"), "--metrics", str(root / "source-metrics.json"),
            )
            self.assertNotEqual(source_root_conflict.returncode, 0)
            self.assertTrue(source_root_conflict.stderr.startswith("error: CLI_VNEXT_INPUT_INVALID"), source_root_conflict.stderr)
            overlap = self._run(
                "encrypt-vnext", "--project-root", str(FIXTURE_ROOT), "--top", "parameter_top",
                "--name-length", "16", "--output-dir", str(FIXTURE_ROOT / "vnext-output"),
                "--map", str(root / "overlap-map.json"), "--metrics", str(root / "overlap-metrics.json"),
            )
            self.assertNotEqual(overlap.returncode, 0)
            self.assertTrue(overlap.stderr.startswith("error: CLI_VNEXT_OUTPUT_INVALID"), overlap.stderr)
            self.assertFalse((FIXTURE_ROOT / "vnext-output").exists())

            project_args = type(
                "Args",
                (),
                {
                    "input_file": None,
                    "filelist": None,
                    "project_root": FIXTURE_ROOT,
                    "source_root": None,
                    "include_dirs": [],
                    "defines": [],
                    "top": "parameter_top",
                    "category": None,
                    "abi_category": None,
                    "encryption_rate": None,
                    "name_length": "16",
                    "output_dir": root / "isolated-gate",
                    "map_file": root / "isolated-map.json",
                    "metrics_file": root / "isolated-metrics.json",
                },
            )()
            with mock.patch.object(orchestration_vnext, "run_vnext", wraps=orchestration_vnext.run_vnext) as runner:
                summary = rewrite_module._encrypt_vnext(project_args)
            self.assertEqual(summary["format"], "rtl-obfuscation.cli-vnext")
            self.assertTrue(runner.called)
            self.assertTrue((root / "isolated-gate").is_dir())
            self.assertTrue((root / "isolated-map.json").is_file())
            decrypt_args = type(
                "Args",
                (),
                {
                    "map_file": root / "isolated-map.json",
                    "gate_dir": root / "isolated-gate",
                    "source_root": FIXTURE_ROOT,
                    "output_dir": root / "isolated-restore",
                    "report": root / "isolated-restore.json",
                },
            )()
            restored_summary = rewrite_module._decrypt_vnext(decrypt_args)
            self.assertEqual(restored_summary["format"], "rtl-obfuscation.restore-vnext-cli")
            self.assertTrue((root / "isolated-restore").is_dir())


if __name__ == "__main__":
    unittest.main()
