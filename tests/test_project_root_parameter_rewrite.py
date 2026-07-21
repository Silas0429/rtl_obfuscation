from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
FIXTURE = REPOSITORY / "tests" / "fixtures" / "t031_project_root_parameters"
FORMAL_FIXTURE = REPOSITORY / "tests" / "formal" / "t032_project_root_parameters"


class ProjectRootParameterRewriteTests(unittest.TestCase):
    def _run(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "rtl_obfuscator.rewrite", *arguments],
            cwd=REPOSITORY,
            capture_output=True,
            text=True,
            check=False,
        )

    def _temporary_root(self) -> Path:
        temporary = tempfile.TemporaryDirectory(prefix="rtl-obfuscation-t032-")
        self.addCleanup(temporary.cleanup)
        return Path(temporary.name)

    def _encrypt(
        self,
        project_root: Path = FIXTURE,
        top: str = "parameter_top",
        groups: tuple[str, ...] = ("parameters",),
        *,
        file_maps: bool = True,
    ) -> tuple[Path, dict, dict]:
        root = self._temporary_root()
        arguments = [
            "encrypt-project",
            "--project-root",
            str(project_root),
            "--top",
            top,
            "--output-dir",
            str(root / "gate"),
            "--map",
            str(root / "mapping.json"),
            "--metrics",
            str(root / "metrics.json"),
            "--name-length",
            "8",
        ]
        if file_maps:
            arguments.extend(("--file-map-dir", str(root / "maps")))
        for group in groups:
            arguments.extend(("--category", group))
        completed = self._run(*arguments)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return (
            root,
            json.loads((root / "mapping.json").read_text()),
            json.loads((root / "metrics.json").read_text()),
        )

    @staticmethod
    def _manifest(root: Path, files: list[str]) -> str:
        content = "".join(
            f"{hashlib.sha256((root / path).read_bytes()).hexdigest()}  {path}\n"
            for path in sorted(files)
        )
        return hashlib.sha256(content.encode()).hexdigest()

    def test_parameter_only_mapping_and_metrics(self) -> None:
        root, mapping, metrics = self._encrypt()
        self.assertEqual(mapping["version"], 3)
        self.assertEqual(mapping["mode"], "project-root")
        self.assertEqual(mapping["top"], "parameter_top")
        self.assertEqual(mapping["selected_groups"], ["parameters"])
        self.assertEqual(mapping["selected_categories"], ["parameters"])
        self.assertEqual(mapping["files"], ["bus_if.sv", "child.sv", "top.sv"])
        self.assertEqual(len(mapping["entries"]), 5)
        self.assertEqual(sum(item["occurrences"] for item in mapping["entries"]), 9)
        self.assertEqual(
            {(item["name"], item["reason"]) for item in mapping["preserved"]},
            {
                ("DATA_WIDTH", "top_parameter"),
                ("LANES", "top_parameter"),
                ("MACRO_LOCAL", "macro_expansion"),
                ("parameter_top", "top_abi"),
                ("bus_inst", "top_interface_instance"),
                ("data_i", "top_port"),
                ("data_o", "top_port"),
            },
        )
        self.assertEqual(mapping["input_manifest_sha256"], self._manifest(FIXTURE, mapping["files"]))
        self.assertEqual(mapping["gate_manifest_sha256"], self._manifest(root / "gate", mapping["files"]))
        self.assertNotEqual(mapping["input_manifest_sha256"], mapping["gate_manifest_sha256"])
        self.assertEqual(metrics["symbols"], {"renamed": 5, "eligible": 5, "coverage": 1.0})
        self.assertEqual(metrics["occurrences"], {"renamed": 9, "eligible": 9, "coverage": 1.0})
        self.assertEqual(metrics["effective_coverage"], 1.0)
        self.assertEqual(metrics["plaintext_leakage_rate"], 0.0)

    def test_gate_reanalysis_per_file_maps_and_decrypt(self) -> None:
        root, mapping, _ = self._encrypt()
        completed = self._run(
            "inspect-project",
            "--project-root",
            str(root / "gate"),
            "--top",
            "parameter_top",
            "--report",
            str(root / "gate-report.json"),
            "--category",
            "parameters",
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        report = json.loads((root / "gate-report.json").read_text())
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["compile"]["parse_errors"], 0)
        self.assertEqual(report["compile"]["semantic_errors"], 0)
        self.assertEqual(report["reachable"]["files"], mapping["files"])
        self.assertEqual(len(report["inventory"]["eligible"]), 5)
        self.assertEqual(sum(item["occurrences"] for item in report["inventory"]["eligible"]), 9)
        self.assertFalse((root / "maps" / "bus_if.json").exists())
        self.assertTrue((root / "maps" / "child.json").is_file())
        self.assertTrue((root / "maps" / "top.json").is_file())

        completed = self._run(
            "decrypt-project",
            "--gate-dir",
            str(root / "gate"),
            "--map",
            str(root / "mapping.json"),
            "--output-dir",
            str(root / "restored"),
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout), {"files": 3, "mapping_entries": 5, "modified_tokens": 9})
        for relative_file in mapping["files"]:
            self.assertEqual(
                (FIXTURE / relative_file).read_bytes(),
                (root / "restored" / relative_file).read_bytes(),
            )

    def test_combined_and_default_profiles(self) -> None:
        root, mapping, _ = self._encrypt(
            groups=("signals", "ports", "instances", "struct", "interface", "parameters")
        )
        self.assertEqual(mapping["version"], 4)
        self.assertEqual(mapping["profile"], "manual")
        self.assertEqual(len(mapping["entries"]), 24)
        self.assertEqual(sum(item["occurrences"] for item in mapping["entries"]), 67)
        self.assertEqual(
            mapping["requested_categories"],
            ["signals", "ports", "instances", "struct", "interface", "parameters"],
        )
        self.assertIn("parameters", mapping["selected_categories"])
        self.assertTrue(any(item["category"] == "parameters" for item in mapping["entries"]))

        default_root = self._temporary_root()
        completed = self._run(
            "encrypt-project",
            "--project-root",
            str(FIXTURE),
            "--top",
            "parameter_top",
            "--output-dir",
            str(default_root / "gate"),
            "--map",
            str(default_root / "mapping.json"),
            "--metrics",
            str(default_root / "metrics.json"),
            "--name-length",
            "8",
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        default_mapping = json.loads((default_root / "mapping.json").read_text())
        self.assertEqual(default_mapping["version"], 3)
        self.assertEqual(
            default_mapping["selected_groups"],
            [
                "signals", "parameters", "enum_values", "genvars", "functions",
                "tasks", "arguments", "instances", "generate_blocks", "typedefs",
                "struct_types", "struct_fields", "union_fields",
            ],
        )
        self.assertIn("parameters", default_mapping["selected_categories"])

    def test_legacy_parameter_workflow_and_project_category_validation(self) -> None:
        root = self._temporary_root()
        gold = REPOSITORY / "tests" / "fixtures" / "t005_value_parameter.sv"
        completed = self._run(
            "encrypt",
            "--input",
            str(gold),
            "--output",
            str(root / "gate.sv"),
            "--map",
            str(root / "mapping.json"),
            "--metrics",
            str(root / "metrics.json"),
            "--category",
            "parameters",
            "--name-length",
            "8",
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        completed = self._run(
            "decrypt",
            "--input",
            str(root / "gate.sv"),
            "--output",
            str(root / "restored.sv"),
            "--map",
            str(root / "mapping.json"),
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(gold.read_bytes(), (root / "restored.sv").read_bytes())

    def test_formal_companion_gate_has_parameter_rewrite(self) -> None:
        root, mapping, _ = self._encrypt(
            FORMAL_FIXTURE,
            "t032_top",
            ("parameters",),
            file_maps=False,
        )
        self.assertEqual(mapping["files"], ["child.sv", "top.sv"])
        self.assertEqual(len(mapping["entries"]), 3)
        self.assertEqual(sum(item["occurrences"] for item in mapping["entries"]), 6)
        completed = subprocess.run(
            [
                "conda",
                "run",
                "-n",
                "rtl_obfuscation",
                "python",
                "scripts/formal_equivalence.py",
                "--gold-filelist",
                str(FORMAL_FIXTURE / "design.f"),
                "--gold-root",
                str(FORMAL_FIXTURE),
                "--gate-filelist",
                str(root / "gate" / "design.f"),
                "--gate-root",
                str(root / "gate"),
                "--top",
                "t032_top",
            ],
            cwd=REPOSITORY,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["formal_equivalence"], "pass")


if __name__ == "__main__":
    unittest.main()
