"""Black-box test for the T001 variable inventory CLI."""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys
import unittest

import pyslang


class VariableInventoryCliTest(unittest.TestCase):
    def test_fixed_sample_contains_only_internal_variable(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        input_file = repository / "rtl_samples" / "01_continuous_assign.sv"
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "rtl_obfuscator.inventory",
                "--input",
                "rtl_samples/01_continuous_assign.sv",
                "--category",
                "signals",
                "--name-length",
                "8",
            ],
            cwd=repository,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["version"], 1)
        self.assertEqual(payload["name_length"], 8)
        self.assertEqual(len(payload["entries"]), 1)

        entry = payload["entries"][0]
        self.assertEqual(entry["category"], "signals")
        self.assertEqual(entry["scope"], "sample01_continuous_assign")
        self.assertEqual(entry["original_name"], "and_result")
        self.assertRegex(entry["renamed_name"], r"^[A-Za-z][A-Za-z0-9_]{7}$")

        input_identifiers = set(
            re.findall(r"[A-Za-z_][A-Za-z0-9_$]*", input_file.read_text())
        )
        self.assertNotIn(entry["renamed_name"], input_identifiers)

        identifier_probe = pyslang.syntax.SyntaxTree.fromText(
            f"module identifier_probe; logic {entry['renamed_name']}; endmodule"
        )
        probe_compilation = pyslang.ast.Compilation()
        probe_compilation.addSyntaxTree(identifier_probe)
        self.assertFalse(
            any(
                diagnostic.isError()
                for diagnostic in probe_compilation.getAllDiagnostics()
            )
        )

        original_names = {item["original_name"] for item in payload["entries"]}
        self.assertTrue(
            {"input_a", "input_b", "output_y"}.isdisjoint(original_names)
        )


if __name__ == "__main__":
    unittest.main()
