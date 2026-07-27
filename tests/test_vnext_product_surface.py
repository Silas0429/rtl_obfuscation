from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from rtl_obfuscator import rewrite


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "refactor_symbol_graph_parameters"


class VNextProductSurfaceTests(unittest.TestCase):
    def test_parser_has_only_two_product_operations(self):
        parser = rewrite._create_argument_parser()
        actions = [action for action in parser._actions if action.dest == "operation"]
        self.assertEqual(len(actions), 1)
        self.assertEqual(set(actions[0].choices), {"encrypt-vnext", "decrypt-vnext"})

    def test_legacy_operations_fail_without_traceback_or_fallback_output(self):
        for operation in (
            "encrypt", "decrypt", "encrypt-project", "decrypt-project",
            "inspect-project", "formal-view", "formal-align",
        ):
            result = subprocess.run(
                [sys.executable, "-m", "rtl_obfuscator.rewrite", operation],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0, operation)
            self.assertNotIn("Traceback", result.stderr, operation)

    def test_product_import_does_not_load_legacy_modules(self):
        code = (
            "import sys; import rtl_obfuscator.rewrite; "
            "print(any(name in sys.modules for name in "
            "('rtl_obfuscator.inventory','rtl_obfuscator.project',"
            "'rtl_obfuscator.formal_view','rtl_obfuscator.category_profile')))"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "False")

    def test_discovery_has_one_source_of_truth(self):
        code = (
            "import inspect; import rtl_obfuscator.project as p; "
            "import rtl_obfuscator.project_discovery as d; "
            "assert p._discover_files is d._discover_files; "
            "assert p._discover_sourceset is d._discover_sourceset; "
            "assert 'def _discover_files' not in inspect.getsource(p); "
            "assert 'def _discover_sourceset' not in inspect.getsource(p); "
            "print('unique')"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "unique")

    def test_legacy_mapping_is_rejected_without_output(self):
        with tempfile.TemporaryDirectory(prefix="t056-legacy-map-") as temporary:
            root = Path(temporary)
            gate = root / "gate"
            gate.mkdir()
            for version in (1, 2, 3, 4):
                legacy_map = root / f"legacy-{version}.json"
                legacy_map.write_text(
                    json.dumps({"version": version, "entries": []}),
                    encoding="utf-8",
                )
                result = subprocess.run(
                    [
                        sys.executable, "-m", "rtl_obfuscator.rewrite", "decrypt-vnext",
                        "--map", str(legacy_map), "--gate-dir", str(gate),
                        "--source-root", str(FIXTURE), "--output-dir", str(root / f"restore-{version}"),
                        "--report", str(root / f"restore-{version}.json"),
                    ],
                    cwd=ROOT, capture_output=True, text=True, check=False,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("Traceback", result.stderr)
                self.assertTrue(result.stderr.startswith("error: RESTORE_VNEXT_REPORT_INVALID"), result.stderr)
                self.assertFalse((root / f"restore-{version}").exists())
                self.assertFalse((root / f"restore-{version}.json").exists())

    def test_actual_vnext_cli_report_is_portable_and_deterministic(self):
        with tempfile.TemporaryDirectory(prefix="t056-cli-") as temporary:
            root = Path(temporary)
            outputs = []
            raw_names = []
            for suffix in ("one", "two"):
                result = subprocess.run(
                    [
                        sys.executable, "-m", "rtl_obfuscator.rewrite", "encrypt-vnext",
                        "--filelist", str(FIXTURE / "design.f"),
                        "--source-root", str(FIXTURE), "--top", "parameter_top",
                        "--category", "signals", "--category", "parameters",
                        "--category", "genvars", "--abi-category", "parameters",
                        "--encryption-rate", "0.35", "--name-length", "16",
                        "--output-dir", str(root / f"gate-{suffix}"),
                        "--map", str(root / f"map-{suffix}.json"),
                        "--metrics", str(root / f"metrics-{suffix}.json"),
                    ],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                report = json.loads((root / f"map-{suffix}.json").read_text(encoding="utf-8"))
                metrics = json.loads((root / f"metrics-{suffix}.json").read_text(encoding="utf-8"))
                raw_names.append(
                    tuple(
                        item.get("renamed_name")
                        for item in report["mapping"]["records"]
                        if item.get("renamed_name") is not None
                    )
                )
                outputs.append((self._normalize(report), self._normalize(metrics)))
            self.assertEqual(outputs[0], outputs[1])
            self.assertNotEqual(raw_names[0], raw_names[1])
            self.assertNotIn(str(FIXTURE.resolve()), json.dumps(outputs[0]))

    @staticmethod
    def _normalize(value: object) -> object:
        if isinstance(value, dict):
            return {
                key: VNextProductSurfaceTests._normalize(item)
                for key, item in value.items()
                if key != "renamed_name" and not key.endswith("sha256")
            }
        if isinstance(value, list):
            return [VNextProductSurfaceTests._normalize(item) for item in value]
        return value


if __name__ == "__main__":
    unittest.main()
