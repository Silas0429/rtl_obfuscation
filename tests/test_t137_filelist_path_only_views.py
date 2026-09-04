"""T137 black-box contract: preserve filelist text and replace only paths."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
ENCRYPT = ROOT / "rtl_encrypt.py"
DECRYPT = ROOT / "rtl_decrypt.py"
FORMAL = ROOT / "scripts" / "formal_equivalence.py"
INTERNAL = Path(".rtl_obfuscation/filelists")


class T137FilelistPathOnlyViewsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix="t137-filelist-views-"))
        cls.addClassCleanup(shutil.rmtree, cls.root, ignore_errors=True)
        cls.project = cls.root / "project"
        for relative in ("include", "include2", "lists", "rtl"):
            (cls.project / relative).mkdir(parents=True, exist_ok=True)
        (cls.project / "include" / "defs.svh").write_text(
            "`define T137_WIDTH 4\n", encoding="utf-8"
        )
        (cls.project / "include2" / "feature.svh").write_text(
            "`define T137_FEATURE_BIT 1'b0\n", encoding="utf-8"
        )
        (cls.project / "rtl" / "vendor.sv").write_text(
            "module t137_vendor(input logic a, output logic y);\n"
            "  assign y = a;\n"
            "endmodule\n",
            encoding="utf-8",
        )
        (cls.project / "rtl" / "helper.sv").write_text(
            "module t137_helper(input logic a, output logic y);\n"
            "  assign y = ~a;\n"
            "endmodule\n",
            encoding="utf-8",
        )
        (cls.project / "rtl" / "params.vic").write_text(
            "// explicit context intentionally listed after source units\n",
            encoding="utf-8",
        )
        (cls.project / "rtl" / "top.sv").write_text(
            "`include \"defs.svh\"\n"
            "`include \"feature.svh\"\n"
            "module t137_top(\n"
            "  input logic clk,\n"
            "  input logic [`T137_WIDTH-1:0] data_i,\n"
            "  output logic [`T137_WIDTH-1:0] data_o\n"
            ");\n"
            "  logic local_signal;\n"
            "  logic helper_signal;\n"
            "  logic vendor_signal;\n"
            "  t137_helper u_helper(.a(data_i[0]), .y(helper_signal));\n"
            "  t137_vendor u_vendor(.a(data_i[1]), .y(vendor_signal));\n"
            "  always_ff @(posedge clk) local_signal <= helper_signal;\n"
            "`ifdef T137_FEATURE\n"
            "  assign data_o = data_i ^ {4{local_signal ^ vendor_signal ^ `T137_FEATURE_BIT}};\n"
            "`else\n"
            "  assign data_o = data_i;\n"
            "`endif\n"
            "endmodule\n",
            encoding="utf-8",
        )
        cls.nested = cls.project / "lists" / "nested.f"
        cls.nested_bytes = (
            b"// nested filelist comment\n"
            b"\n"
            b"../rtl/helper.sv\n"
        )
        cls.nested.write_bytes(cls.nested_bytes)
        cls.filelist = cls.project / "input.f"
        cls.original_bytes = (
            b"# top filelist comment\n"
            b"-v rtl/vendor.sv\n"
            b"\n"
            b"+incdir+include+include2\n"
            b"-f lists/nested.f\n"
            b"+define+T137_FEATURE=1\n"
            b"rtl/top.sv\n"
            b"rtl/params.vic\n"
        )
        cls.filelist.write_bytes(cls.original_bytes)
        cls.gate = cls.root / "gate"
        cls.encrypted = subprocess.run(
            (
                sys.executable,
                str(ENCRYPT),
                "--filelist",
                str(cls.filelist),
                "--top",
                "t137_top",
                "--rewrite-root",
                str(cls.project / "rtl"),
                "--category",
                "signals",
                "--output-dir",
                str(cls.gate),
            ),
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        if cls.encrypted.returncode != 0:
            raise AssertionError(cls.encrypted.stderr)
        cls.report = json.loads(cls.encrypted.stdout)

    def test_original_design_is_byte_identical(self):
        self.assertEqual(
            (self.gate / "original_design.f").read_bytes(), self.original_bytes
        )

    def test_design_and_export_replace_only_path_tokens(self):
        gate = self.gate.resolve().as_posix()
        design_nested = (self.gate / INTERNAL / "design/lists/nested.f").resolve()
        export_nested = self.gate / INTERNAL / "export/lists/nested.f"
        expected_design = (
            b"# top filelist comment\n"
            + f"-v {gate}/rtl/vendor.sv\n".encode()
            + b"\n"
            + f"+incdir+{gate}/include+{gate}/include2\n".encode()
            + f"-f {design_nested.as_posix()}\n".encode()
            + b"+define+T137_FEATURE=1\n"
            + f"{gate}/rtl/top.sv\n".encode()
            + f"{gate}/rtl/params.vic\n".encode()
        )
        expected_export = (
            b"# top filelist comment\n"
            b"-v $OUT/rtl/vendor.sv\n"
            b"\n"
            b"+incdir+$OUT/include+$OUT/include2\n"
            + f"-f $OUT/{export_nested.relative_to(self.gate).as_posix()}\n".encode()
            + b"+define+T137_FEATURE=1\n"
            b"$OUT/rtl/top.sv\n"
            b"$OUT/rtl/params.vic\n"
        )
        self.assertEqual((self.gate / "design.f").read_bytes(), expected_design)
        self.assertEqual(
            (self.gate / "export_design.f").read_bytes(), expected_export
        )

    def test_nested_filelists_preserve_structure_and_order(self):
        gate = self.gate.resolve().as_posix()
        design_nested = self.gate / INTERNAL / "design/lists/nested.f"
        export_nested = self.gate / INTERNAL / "export/lists/nested.f"
        self.assertEqual(
            design_nested.read_bytes(),
            b"// nested filelist comment\n\n"
            + f"{gate}/rtl/helper.sv\n".encode(),
        )
        self.assertEqual(
            export_nested.read_bytes(),
            b"// nested filelist comment\n\n$OUT/rtl/helper.sv\n",
        )
        self.assertTrue((self.gate / "include/defs.svh").is_file())
        self.assertTrue((self.gate / "include2/feature.svh").is_file())
        for path in (
            self.gate / "design.f",
            self.gate / "export_design.f",
            design_nested,
            export_nested,
        ):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("defs.svh", text)
            self.assertNotIn("feature.svh", text)

    def test_public_decrypt_restores_only_physical_inputs(self):
        restored = self.root / "restored"
        result = subprocess.run(
            (
                sys.executable,
                str(DECRYPT),
                "--map",
                str(self.gate / "mapping.json"),
                "--gate-dir",
                str(self.gate),
                "--output-dir",
                str(restored),
            ),
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        for relative in (
            "include/defs.svh",
            "include2/feature.svh",
            "rtl/vendor.sv",
            "rtl/helper.sv",
            "rtl/top.sv",
            "rtl/params.vic",
        ):
            self.assertEqual(
                (restored / relative).read_bytes(),
                (self.project / relative).read_bytes(),
            )

    def test_public_decrypt_rejects_nested_filelist_symlink_escape(self):
        nested = self.gate / INTERNAL / "design/lists/nested.f"
        original = nested.read_bytes()
        external = self.root / "external-design-nested.f"
        external.write_bytes(original)
        nested.unlink()
        nested.symlink_to(external)
        try:
            result = subprocess.run(
                (
                    sys.executable,
                    str(DECRYPT),
                    "--map",
                    str(self.gate / "mapping.json"),
                    "--gate-dir",
                    str(self.gate),
                    "--output-dir",
                    str(self.root / "restored-symlink-escape"),
                ),
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
        finally:
            nested.unlink()
            nested.write_bytes(original)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("RESTORE_VNEXT_GATE_INVALID", result.stderr)

    def test_actual_gate_and_relocated_export_formal_with_negative(self):
        common = (
            "--gold-filelist",
            str(self.gate / "original_design.f"),
            "--gold-root",
            str(self.project),
            "--top",
            "t137_top",
            "--seq",
            "5",
        )

        def run(gate: Path, filelist: Path, *, out: Path | None = None):
            environment = os.environ.copy()
            if out is not None:
                environment["OUT"] = str(out)
            return subprocess.run(
                (
                    sys.executable,
                    str(FORMAL),
                    *common,
                    "--gate-filelist",
                    str(filelist),
                    "--gate-root",
                    str(gate),
                ),
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )

        design = run(self.gate, self.gate / "design.f")
        self.assertEqual(design.returncode, 0, design.stdout + design.stderr)
        self.assertEqual(json.loads(design.stdout)["formal_equivalence"], "pass")

        relocated = self.root / "relocated"
        shutil.copytree(self.gate, relocated)
        exported = run(
            relocated, relocated / "export_design.f", out=relocated
        )
        self.assertEqual(exported.returncode, 0, exported.stdout + exported.stderr)
        self.assertEqual(json.loads(exported.stdout)["formal_equivalence"], "pass")

        negative = self.root / "negative"
        shutil.copytree(self.gate, negative)
        target = negative / "rtl/top.sv"
        changed = target.read_bytes().replace(b" ^ ", b" | ", 1)
        self.assertNotEqual(changed, target.read_bytes())
        target.write_bytes(changed)
        failed = run(negative, negative / "export_design.f", out=negative)
        self.assertNotEqual(failed.returncode, 0)
        diagnostics = failed.stdout + failed.stderr
        self.assertIn("unproven", diagnostics)
        self.assertIn("equiv_status -assert", diagnostics)


if __name__ == "__main__":
    unittest.main()
