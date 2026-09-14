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
    def test_source_root_include_dir_survives_delivery_restore_and_formal(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        with TemporaryDirectory(prefix="t136-root-include-") as temporary:
            base = Path(temporary)
            project = base / "project"
            project.mkdir()
            (project / "defs.svh").write_text(
                "`define T136_ROOT_WIDTH 4\n", encoding="utf-8"
            )
            (project / "top.sv").write_text(
                "`include \"defs.svh\"\n"
                "module t136_root_top (\n"
                "    input logic clk,\n"
                "    input logic [`T136_ROOT_WIDTH-1:0] data_i,\n"
                "    output logic [`T136_ROOT_WIDTH-1:0] data_o\n"
                ");\n"
                "    logic [`T136_ROOT_WIDTH-1:0] stored_value;\n"
                "    always_ff @(posedge clk) stored_value <= data_i;\n"
                "`ifdef T136_ROOT_FEATURE\n"
                "    assign data_o = stored_value ^ data_i;\n"
                "`else\n"
                "    assign data_o = stored_value;\n"
                "`endif\n"
                "endmodule\n",
                encoding="utf-8",
            )
            filelist = project / "input.f"
            filelist.write_text(
                "+incdir+.\n+define+T136_ROOT_FEATURE=1\ntop.sv\n",
                encoding="utf-8",
            )
            gate = base / "gate"
            encrypt = subprocess.run(
                [
                    sys.executable,
                    str(repository / "rtl_encrypt.py"),
                    "--filelist",
                    str(filelist),
                    "--top",
                    "t136_root_top",
                    "--include-dir",
                    str(project),
                    "--category",
                    "signals",
                    "--output-dir",
                    str(gate),
                ],
                cwd=repository,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(encrypt.returncode, 0, encrypt.stderr)
            report = json.loads((gate / "mapping.json").read_text(encoding="utf-8"))
            self.assertEqual(report["source_set"]["include_dirs"], ["."])
            self.assertTrue(
                any(record["action"] == "rename" for record in report["mapping"]["records"])
            )
            self.assertEqual(
                (gate / "design.f").read_text(encoding="utf-8").splitlines(),
                [
                    f"+incdir+{gate.resolve().as_posix()}",
                    "+define+T136_ROOT_FEATURE=1",
                    (gate / "top.sv").resolve().as_posix(),
                ],
            )
            self.assertEqual(
                (gate / "export_design.f").read_text(encoding="utf-8").splitlines(),
                [
                    "+incdir+$OUT",
                    "+define+T136_ROOT_FEATURE=1",
                    "$OUT/top.sv",
                ],
            )
            self.assertEqual(
                (gate / "original_design.f").read_bytes(),
                filelist.read_bytes(),
            )
            self.assertNotIn(
                "defs.svh", (gate / "design.f").read_text(encoding="utf-8")
            )
            self.assertTrue((gate / "defs.svh").is_file())

            restored = base / "restored"
            decrypt = subprocess.run(
                [
                    sys.executable,
                    str(repository / "rtl_decrypt.py"),
                    "--map",
                    str(gate / "mapping.json"),
                    "--gate-dir",
                    str(gate),
                    "--output-dir",
                    str(restored),
                ],
                cwd=repository,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(decrypt.returncode, 0, decrypt.stderr)
            for name in ("top.sv", "defs.svh"):
                self.assertEqual(
                    (restored / name).read_bytes(), (project / name).read_bytes()
                )

            formal = subprocess.run(
                [
                    sys.executable,
                    str(repository / "scripts" / "formal_equivalence.py"),
                    "--gold-filelist",
                    str(gate / "original_design.f"),
                    "--gold-root",
                    str(project),
                    "--gate-filelist",
                    str(gate / "design.f"),
                    "--gate-root",
                    str(gate),
                    "--top",
                    "t136_root_top",
                    "--seq",
                    "5",
                ],
                cwd=repository,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(formal.returncode, 0, formal.stdout + formal.stderr)
            self.assertEqual(json.loads(formal.stdout)["formal_equivalence"], "pass")

    def test_actual_vnext_gate_positive_and_functional_negative(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        source_root = repository / "tests" / "fixtures" / "refactor_symbol_graph_parameters"
        with TemporaryDirectory(prefix="t056-formal-") as temporary:
            base = Path(temporary)
            gate = base / "gate"
            mapping = base / "mapping.json"
            metrics = base / "metrics.json"
            # The starting-HEAD regression still named removed parameter/genvar
            # categories and --abi-category.  Exercise the same renamed-gate
            # positive/negative flow with the current canonical signals group;
            # this does not claim parameter or genvar renaming coverage.
            encrypt = subprocess.run(
                [
                    sys.executable, "-m", "rtl_obfuscator.rewrite", "encrypt-vnext",
                    "--filelist", str(source_root / "design.f"),
                    "--source-root", str(source_root), "--top", "parameter_top",
                    "--category", "signals", "--encryption-rate", "0.35",
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
            negative_design = negative_gate / "design.f"
            negative_design.write_text(
                negative_design.read_text(encoding="utf-8").replace(
                    gate.resolve().as_posix(), negative_gate.resolve().as_posix()
                ),
                encoding="utf-8",
            )
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
                    "--gate-filelist", str(negative_design),
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
