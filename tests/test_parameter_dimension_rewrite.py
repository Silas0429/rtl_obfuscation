"""T020 parameter dimension and named-override regression tests."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

import pyslang


class ParameterDimensionRewriteTest(unittest.TestCase):
    def test_dimension_and_named_override_scope_round_trip(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        source = """module child #(\n    parameter int WIDTH = 8,\n    parameter int DEPTH = 2\n) (\n    input logic [WIDTH-1:0] data,\n    output logic [WIDTH-1:0] q\n);\n    logic [WIDTH-1:0] mem [0:DEPTH-1];\n    assign q = data;\nendmodule\n\nmodule top #(\n    parameter int WIDTH = 8,\n    parameter int DEPTH = 2\n) (\n    input logic [WIDTH-1:0] data,\n    output logic [WIDTH-1:0] q\n);\n    child #(.WIDTH(WIDTH), .DEPTH(DEPTH)) u_named (.data(data), .q(q));\n    child #(16, 4) u_positional (.data(data), .q());\nendmodule\n"""

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "design.sv").write_text(source, encoding="utf-8")
            (root / "design.f").write_text("design.sv\n", encoding="utf-8")
            gate_dir = root / "gate"
            restored_dir = root / "restored"
            mapping_file = root / "mapping.json"
            metrics_file = root / "metrics.json"
            encrypt = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "rtl_obfuscator.rewrite",
                    "encrypt-project",
                    "--filelist",
                    str(root / "design.f"),
                    "--source-root",
                    str(root),
                    "--output-dir",
                    str(gate_dir),
                    "--map",
                    str(mapping_file),
                    "--metrics",
                    str(metrics_file),
                    "--top",
                    "top",
                    "--category",
                    "parameters",
                    "--name-length",
                    "8",
                ],
                cwd=repository,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(encrypt.returncode, 0, encrypt.stderr)
            mapping = json.loads(mapping_file.read_text(encoding="utf-8"))
            self.assertEqual(mapping["version"], 2)
            entries = {(e["scope"], e["original_name"]): e for e in mapping["entries"]}
            self.assertEqual(set(entries), {
                ("child", "WIDTH"),
                ("child", "DEPTH"),
                ("top", "WIDTH"),
                ("top", "DEPTH"),
            })

            # Every mapped source range must contain the semantic original.
            gold = (root / "design.sv").read_bytes()
            for entry in entries.values():
                for record in [entry["declaration"], *entry["references"]]:
                    self.assertEqual(
                        gold[record["start"] : record["end"]],
                        entry["original_name"].encode(),
                    )

            # The named override's left side belongs to child, while the
            # right side is bound to top; positional values add no fake LHS.
            child_width = entries[("child", "WIDTH")]
            top_width = entries[("top", "WIDTH")]
            child_width_ranges = [r["start"] for r in child_width["references"]]
            top_width_ranges = [r["start"] for r in top_width["references"]]
            named_left = source.index(".WIDTH") + 1
            named_right = source.index("(WIDTH)") + 1
            self.assertIn(named_left, child_width_ranges)
            self.assertIn(named_right, top_width_ranges)
            self.assertNotIn(source.index("16"), child_width_ranges)

            decrypt = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "rtl_obfuscator.rewrite",
                    "decrypt-project",
                    "--gate-dir",
                    str(gate_dir),
                    "--source-root",
                    str(root),
                    "--map",
                    str(mapping_file),
                    "--output-dir",
                    str(restored_dir),
                ],
                cwd=repository,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(decrypt.returncode, 0, decrypt.stderr)
            self.assertEqual(
                (restored_dir / "design.sv").read_bytes(),
                (root / "design.sv").read_bytes(),
            )
            metrics = json.loads(metrics_file.read_text(encoding="utf-8"))
            self.assertEqual(metrics["plaintext_leakage_rate"], 0.0)

    def test_generate_local_genvar_shadows_module_parameter(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        source = """module parameter_shadow_observable #(
    parameter int DEPTH = 4
) (
    output logic [3:0] widths
);
    for (genvar DEPTH = 0; DEPTH < 2; DEPTH++) begin : g_depth
        logic [DEPTH:0] local_data;
        assign widths[DEPTH*2 +: 2] = $bits(local_data);
    end
endmodule
"""

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            gold = root / "design.sv"
            filelist = root / "design.f"
            gate_dir = root / "gate"
            mapping_file = root / "mapping.json"
            metrics_file = root / "metrics.json"
            gold.write_text(source, encoding="utf-8")
            filelist.write_text("design.sv\n", encoding="utf-8")

            encrypt = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "rtl_obfuscator.rewrite",
                    "encrypt-project",
                    "--filelist",
                    str(filelist),
                    "--source-root",
                    str(root),
                    "--output-dir",
                    str(gate_dir),
                    "--map",
                    str(mapping_file),
                    "--metrics",
                    str(metrics_file),
                    "--top",
                    "parameter_shadow_observable",
                    "--category",
                    "parameters",
                    "--name-length",
                    "8",
                ],
                cwd=repository,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(encrypt.returncode, 0, encrypt.stderr)
            self.assertEqual(json.loads(encrypt.stdout), {
                "files": 1,
                "mapping_entries": 1,
                "modified_tokens": 1,
            })

            mapping = json.loads(mapping_file.read_text(encoding="utf-8"))
            self.assertEqual(len(mapping["entries"]), 1)
            parameter = mapping["entries"][0]
            self.assertEqual(parameter["original_name"], "DEPTH")
            self.assertEqual(parameter["references"], [])

            gate = gate_dir / "design.sv"
            gate_text = gate.read_text(encoding="utf-8")
            self.assertIn(
                "for (genvar DEPTH = 0; DEPTH < 2; DEPTH++)",
                gate_text,
            )
            self.assertIn("logic [DEPTH:0] local_data;", gate_text)
            self.assertIn(
                "assign widths[DEPTH*2 +: 2] = $bits(local_data);",
                gate_text,
            )
            self.assertNotEqual(parameter["renamed_name"], "DEPTH")
            self.assertIn(
                f"parameter int {parameter['renamed_name']} = 4",
                gate_text,
            )

            compilation = pyslang.ast.Compilation()
            compilation.addSyntaxTree(pyslang.syntax.SyntaxTree.fromFile(str(gate)))
            self.assertFalse(
                any(diagnostic.isError() for diagnostic in compilation.getAllDiagnostics())
            )

            formal = subprocess.run(
                [
                    sys.executable,
                    "scripts/formal_equivalence.py",
                    "--gold",
                    str(gold),
                    "--gate",
                    str(gate),
                    "--top",
                    "parameter_shadow_observable",
                ],
                cwd=repository,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(formal.returncode, 0, formal.stderr)
            self.assertEqual(
                json.loads(formal.stdout)["formal_equivalence"],
                "pass",
            )


if __name__ == "__main__":
    unittest.main()
