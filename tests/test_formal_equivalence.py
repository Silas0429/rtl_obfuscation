from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from rtl_obfuscator.source_catalog import build_source_catalog
from rtl_obfuscator.source_set import from_filelist


class FormalEquivalenceRegressionTest(unittest.TestCase):
    def test_actual_vnext_gate_positive_and_functional_negative(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        source_root = repository / "tests" / "fixtures" / "refactor_symbol_graph_parameters"
        with TemporaryDirectory(prefix="t056-formal-") as temporary:
            base = Path(temporary)
            gate = base / "gate"
            mapping = base / "mapping.json"
            metrics = base / "metrics.json"
            encrypt = subprocess.run(
                [
                    sys.executable, "-m", "rtl_obfuscator.rewrite", "encrypt-vnext",
                    "--filelist", str(source_root / "design.f"),
                    "--source-root", str(source_root), "--top", "parameter_top",
                    "--category", "signals", "--category", "parameters", "--category", "genvars",
                    "--abi-category", "parameters", "--encryption-rate", "0.35",
                    "--name-length", "16", "--output-dir", str(gate),
                    "--map", str(mapping), "--metrics", str(metrics),
                ],
                cwd=repository, capture_output=True, text=True, check=False,
            )
            self.assertEqual(encrypt.returncode, 0, encrypt.stderr)
            report = json.loads(mapping.read_text(encoding="utf-8"))
            self.assertTrue(report["summary"]["strict_compile_passed"])

            formal_args = [
                "--gold-filelist", "tests/fixtures/refactor_symbol_graph_parameters/design.f",
                "--gold-root", "tests/fixtures/refactor_symbol_graph_parameters",
                "--gate-filelist", str(gate / "design.f"), "--gate-root", str(gate),
                "--top", "parameter_top", "--seq", "5",
            ]
            positive = subprocess.run(
                [sys.executable, "scripts/formal_equivalence.py", *formal_args],
                cwd=repository, capture_output=True, text=True, check=False,
            )
            self.assertEqual(positive.returncode, 0, positive.stdout + positive.stderr)
            self.assertEqual(json.loads(positive.stdout.strip().splitlines()[-1])["formal_equivalence"], "pass")

            negative_gate = base / "negative"
            shutil.copytree(gate, negative_gate)
            child = negative_gate / "rtl/child.sv"
            original = child.read_bytes()
            needle = b"assign data_o = "
            self.assertEqual(original.count(needle), 1)
            position = original.index(needle) + len(needle)
            child.write_bytes(original[:position] + b"~" + original[position:])
            negative_set = from_filelist(
                filelist=negative_gate / "design.f", source_root=negative_gate, top="parameter_top"
            )
            self.assertEqual(build_source_catalog(negative_set).to_report()["compile"], {
                "catalog": {"parse_errors": 0, "semantic_errors": 0},
                "top_overlay": {"parse_errors": 0, "semantic_errors": 0},
            })
            negative = subprocess.run(
                [
                    sys.executable, "scripts/formal_equivalence.py",
                    "--gold-filelist", "tests/fixtures/refactor_symbol_graph_parameters/design.f",
                    "--gold-root", "tests/fixtures/refactor_symbol_graph_parameters",
                    "--gate-filelist", str(negative_gate / "design.f"),
                    "--gate-root", str(negative_gate), "--top", "parameter_top", "--seq", "5",
                ],
                cwd=repository, capture_output=True, text=True, check=False,
            )
            combined = (negative.stdout + negative.stderr).lower()
            self.assertNotEqual(negative.returncode, 0)
            self.assertIn("unproven", combined)
            self.assertIn("equiv_status -assert", combined)


if __name__ == "__main__":
    unittest.main()
