"""Formal positive/negative regression tests for T020 and existing fixtures."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


class FormalEquivalenceRegressionTest(unittest.TestCase):
    def _run(self, repository: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "scripts/formal_equivalence.py", *args],
            cwd=repository,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_existing_single_file_positive_and_negative(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        positive = self._run(repository, [
            "--gold", "tests/formal/variable_rename/gold.sv",
            "--gate", "tests/formal/variable_rename/gate.sv",
            "--top", "formal_variable_rename",
        ])
        self.assertEqual(positive.returncode, 0, positive.stderr)
        self.assertEqual(json.loads(positive.stdout)["formal_equivalence"], "pass")

        negative = self._run(repository, [
            "--gold", "tests/formal/variable_rename/gold.sv",
            "--gate", "tests/formal/variable_rename/non_equivalent.sv",
            "--top", "formal_variable_rename",
        ])
        self.assertNotEqual(negative.returncode, 0)

    def test_fifo_positive_and_temporary_functional_negative(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        source_root = repository / "rtl_samples" / "example_fifo"
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            gate = base / "gate"
            mapping = base / "mapping.json"
            metrics = base / "metrics.json"
            encrypt = subprocess.run(
                [
                    sys.executable, "-m", "rtl_obfuscator.rewrite", "encrypt-project",
                    "--filelist", str(source_root / "design.f"),
                    "--source-root", str(source_root), "--output-dir", str(gate),
                    "--map", str(mapping), "--metrics", str(metrics), "--top", "fifo_top",
                    "--category", "all", "--category", "modules", "--category", "ports",
                    "--category", "interfaces", "--category", "interface_instances",
                    "--category", "interface_ports", "--category", "modports",
                    "--name-length", "8",
                ],
                cwd=repository, capture_output=True, text=True, check=False,
            )
            self.assertEqual(encrypt.returncode, 0, encrypt.stderr)
            self.assertEqual(json.loads(encrypt.stdout)["modified_tokens"], 299)

            positive = self._run(repository, [
                "--gold-filelist", str(source_root / "design.f"),
                "--gold-root", str(source_root),
                "--gate-filelist", str(gate / "design.f"),
                "--gate-root", str(gate), "--top", "fifo_top",
            ])
            self.assertEqual(positive.returncode, 0, positive.stderr)
            self.assertEqual(json.loads(positive.stdout)["formal_equivalence"], "pass")

            negative_gate = base / "negative"
            shutil.copytree(gate, negative_gate)
            project_mapping = json.loads(mapping.read_text(encoding="utf-8"))
            count_entry = next(
                entry for entry in project_mapping["entries"]
                if entry["category"] == "signals" and entry["original_name"] == "count"
            )
            count_name = count_entry["renamed_name"]
            ctrl = negative_gate / "fifo_ctrl.sv"
            text = ctrl.read_text(encoding="utf-8")
            old = f"{count_name} <= {count_name} + 1'b1;"
            self.assertIn(old, text)
            ctrl.write_text(text.replace(old, f"{count_name} <= {count_name} + 2;", 1), encoding="utf-8")

            negative = self._run(repository, [
                "--gold-filelist", str(source_root / "design.f"),
                "--gold-root", str(source_root),
                "--gate-filelist", str(negative_gate / "design.f"),
                "--gate-root", str(negative_gate), "--top", "fifo_top",
            ])
            self.assertNotEqual(negative.returncode, 0)


if __name__ == "__main__":
    unittest.main()
