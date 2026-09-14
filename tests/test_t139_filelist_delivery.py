"""T139 black-box contract: preserve filelist text and replace only paths."""

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


class T139FilelistPathOnlyViewsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix="t139-filelist-views-"))
        cls.addClassCleanup(shutil.rmtree, cls.root, ignore_errors=True)
        cls.project = cls.root / "project"
        for relative in ("include", "include2", "lists", "rtl"):
            (cls.project / relative).mkdir(parents=True, exist_ok=True)
        (cls.project / "include" / "defs.svh").write_text(
            "`define T139_WIDTH 4\n", encoding="utf-8"
        )
        (cls.project / "include2" / "feature.svh").write_text(
            "`define T139_FEATURE_BIT 1'b0\n", encoding="utf-8"
        )
        (cls.project / "rtl" / "vendor.sv").write_text(
            "module t139_vendor(input logic a, output logic y);\n"
            "  assign y = a;\n"
            "endmodule\n",
            encoding="utf-8",
        )
        (cls.project / "rtl" / "helper.sv").write_text(
            "module t139_helper(input logic a, output logic y);\n"
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
            "module t139_top(\n"
            "  input logic clk,\n"
            "  input logic [`T139_WIDTH-1:0] data_i,\n"
            "  output logic [`T139_WIDTH-1:0] data_o\n"
            ");\n"
            "  logic local_signal;\n"
            "  logic helper_signal;\n"
            "  logic vendor_signal;\n"
            "  t139_helper u_helper(.a(data_i[0]), .y(helper_signal));\n"
            "  t139_vendor u_vendor(.a(data_i[1]), .y(vendor_signal));\n"
            "  always_ff @(posedge clk) local_signal <= helper_signal;\n"
            "`ifdef T139_FEATURE\n"
            "  assign data_o = data_i ^ {4{local_signal ^ vendor_signal ^ `T139_FEATURE_BIT}};\n"
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
            b"+define+T139_FEATURE=1\n"
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
                "t139_top",
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
            + b"+define+T139_FEATURE=1\n"
            + f"{gate}/rtl/top.sv\n".encode()
            + f"{gate}/rtl/params.vic\n".encode()
        )
        expected_export = (
            b"# top filelist comment\n"
            b"-v $OUT/rtl/vendor.sv\n"
            b"\n"
            b"+incdir+$OUT/include+$OUT/include2\n"
            + f"-f $OUT/{export_nested.relative_to(self.gate).as_posix()}\n".encode()
            + b"+define+T139_FEATURE=1\n"
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
            "t139_top",
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
        self.assertGreater(self.report["summary"]["modified_tokens"], 0)
        self.assertNotEqual((self.gate / "rtl/top.sv").read_bytes(), (self.project / "rtl/top.sv").read_bytes())
        print("T139_FORMAL " + json.dumps({
            "design_positive": json.loads(design.stdout),
            "export_positive": json.loads(exported.stdout),
            "negative_gate": str(negative), "negative_exit": failed.returncode,
            "unproven": True, "equiv_status_assert": True}, sort_keys=True))

    def _decrypt_rejected(self, suffix):
        output = self.root / ("rejected-" + suffix)
        result = subprocess.run((sys.executable, str(DECRYPT), "--map", str(self.gate / "mapping.json"),
                                 "--gate-dir", str(self.gate), "--output-dir", str(output)),
                                cwd=ROOT, capture_output=True, text=True, timeout=180)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("RESTORE_VNEXT_GATE_INVALID", result.stderr)
        self.assertFalse(output.exists())

    def test_export_nested_symlink_escape_is_rejected(self):
        nested = self.gate / INTERNAL / "export/lists/nested.f"
        original = nested.read_bytes()
        outside = self.root / "outside-export.f"
        outside.write_bytes(original)
        nested.unlink()
        nested.symlink_to(outside)
        try:
            self._decrypt_rejected("export-symlink")
        finally:
            nested.unlink()
            nested.write_bytes(original)

    def test_unreferenced_nested_file_is_rejected(self):
        extra = self.gate / INTERNAL / "export/lists/unused.f"
        extra.write_bytes(b"// unreferenced delivery file\n")
        try:
            self._decrypt_rejected("unreferenced")
        finally:
            extra.unlink()

    def test_incomplete_three_view_set_is_rejected(self):
        path = self.gate / "export_design.f"
        original = path.read_bytes()
        path.unlink()
        try:
            self._decrypt_rejected("incomplete")
        finally:
            path.write_bytes(original)


class T139DeliveryBoundariesTests(unittest.TestCase):
    def _run(self, script, *arguments, env=None):
        return subprocess.run([sys.executable, str(script), *map(str, arguments)], cwd=ROOT,
                              env=env, capture_output=True, text=True, timeout=180)

    def test_recursive_views_keep_crlf_and_non_path_bytes(self):
        with tempfile.TemporaryDirectory(prefix="t139-crlf-") as temp:
            base = Path(temp)
            project = base / "project"
            (project / "lists/deeper").mkdir(parents=True)
            (project / "top.sv").write_text(
                "module t139_crlf(input logic a, output logic y);\n"
                "logic internal_value; assign internal_value = a; assign y = internal_value; endmodule\n")
            original = "// 原始注释\r\n\r\n  -f lists/a.f  \r\n".encode()
            (project / "input.f").write_bytes(original)
            (project / "lists/a.f").write_bytes(b"// nested\r\n-f deeper/b.f\r\n")
            (project / "lists/deeper/b.f").write_bytes(b"  -v ../../top.sv\r\n")
            gate = base / "gate"
            result = self._run(ENCRYPT, "--filelist", project / "input.f", "--top", "t139_crlf",
                               "--category", "signals", "--output-dir", gate)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((gate / "original_design.f").read_bytes(), original)
            self.assertEqual((gate / "export_design.f").read_bytes(),
                             "// 原始注释\r\n\r\n  -f $OUT/.rtl_obfuscation/filelists/export/lists/a.f  \r\n".encode())
            self.assertEqual((gate / INTERNAL / "export/lists/a.f").read_bytes(),
                             b"// nested\r\n-f $OUT/.rtl_obfuscation/filelists/export/lists/deeper/b.f\r\n")
            self.assertEqual((gate / INTERNAL / "export/lists/deeper/b.f").read_bytes(), b"  -v $OUT/top.sv\r\n")
            restored = self._run(DECRYPT, "--map", gate / "mapping.json", "--gate-dir", gate,
                                 "--output-dir", base / "restored")
            self.assertEqual(restored.returncode, 0, restored.stderr)
            self.assertEqual((base / "restored/top.sv").read_bytes(), (project / "top.sv").read_bytes())

    def test_cli_only_context_stays_out_of_explicit_filelist_views(self):
        with tempfile.TemporaryDirectory(prefix="t139-cli-context-") as temp:
            base = Path(temp)
            project = base / "project"
            (project / "include").mkdir(parents=True)
            (project / "include/defs.svh").write_text("`define T139_WIDTH 4\n")
            (project / "top.sv").write_text(
                '`include "defs.svh"\n'
                'module t139_cli(input logic [`T139_WIDTH-1:0] a, output logic [`T139_WIDTH-1:0] y);\n'
                'logic [`T139_WIDTH-1:0] internal_value; assign internal_value = a; assign y = internal_value; endmodule\n')
            filelist = project / "input.f"
            filelist.write_bytes(b"top.sv\n")
            gate = base / "gate"
            result = self._run(ENCRYPT, "--filelist", filelist, "--top", "t139_cli", "--category", "signals",
                               "--include-dir", project / "include", "--define", "T139_CLI_ONLY=1", "--output-dir", gate)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((gate / "original_design.f").read_bytes(), b"top.sv\n")
            for name in ("design.f", "export_design.f", "original_design.f"):
                self.assertNotIn("+incdir+", (gate / name).read_text())
                self.assertNotIn("+define+", (gate / name).read_text())
            result = self._run(DECRYPT, "--map", gate / "mapping.json", "--gate-dir", gate, "--output-dir", base / "restored")
            self.assertEqual(result.returncode, 0, result.stderr)
            for name in ("top.sv", "include/defs.svh"):
                self.assertEqual((base / "restored" / name).read_bytes(), (project / name).read_bytes())

    def test_non_filelist_modes_use_canonical_three_views(self):
        with tempfile.TemporaryDirectory(prefix="t139-canonical-") as temp:
            base = Path(temp)
            project = base / "project"
            project.mkdir()
            source = project / "top.sv"
            source.write_text("module t139_canonical(input logic a, output logic y);\n"
                              "logic value; assign value = a; assign y = value; endmodule\n")
            for mode, inputs in (("single", ("--input", source)),
                                 ("project", ("--source-root", project, "--top", "t139_canonical"))):
                with self.subTest(mode=mode):
                    gate = base / (mode + "-gate")
                    result = self._run(ENCRYPT, *inputs, "--category", "signals", "--output-dir", gate)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    report = json.loads((gate / "mapping.json").read_text())
                    files = report["source_set"]["compile_order"]
                    self.assertEqual(len(files), 1)
                    self.assertEqual((gate / "design.f").read_text().splitlines(),
                                     [(gate / path).resolve().as_posix() for path in files])
                    self.assertEqual((gate / "export_design.f").read_text().splitlines(), ["$OUT/" + files[0]])
                    self.assertEqual((gate / "original_design.f").read_text().splitlines(), [source.resolve().as_posix()])
                    result = self._run(DECRYPT, "--map", gate / "mapping.json", "--gate-dir", gate,
                                       "--output-dir", base / (mode + "-restored"))
                    self.assertEqual(result.returncode, 0, result.stderr)

    def test_ambiguous_expanded_incdir_whitespace_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="t139-whitespace-") as temp:
            base = Path(temp)
            project = base / "project"
            (project / "include space").mkdir(parents=True)
            (project / "top.sv").write_text("module t139_space; endmodule\n")
            (project / "input.f").write_text("+incdir+$T139_INCLUDE\ntop.sv\n")
            env = dict(os.environ, T139_INCLUDE=str(project / "include space"))
            gate = base / "gate"
            result = self._run(ENCRYPT, "--filelist", project / "input.f", "--category", "signals", "--output-dir", gate, env=env)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("SOURCESET_UNSUPPORTED_FILELIST_DIRECTIVE", result.stderr)
            self.assertFalse(gate.exists())

    def test_output_root_whitespace_is_rejected_without_publication(self):
        with tempfile.TemporaryDirectory(prefix="t139-output-space-") as temp:
            base = Path(temp)
            project = base / "project"
            project.mkdir()
            (project / "top.sv").write_text("module t139_output_space(input logic a, output logic y);\n"
                                          "logic value; assign value = a; assign y = value; endmodule\n")
            (project / "input.f").write_text("top.sv\n")
            gate = base / "gate with space"
            result = self._run(ENCRYPT, "--filelist", project / "input.f", "--category", "signals", "--output-dir", gate)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("CLI_VNEXT_OUTPUT_INVALID", result.stderr)
            self.assertFalse(gate.exists())

    def test_custom_report_paths_with_whitespace_remain_supported(self):
        with tempfile.TemporaryDirectory(prefix="t139-report-space-") as temp:
            base = Path(temp)
            project = base / "project"
            project.mkdir()
            source = project / "top.sv"
            source.write_text("module t139_report_space(input logic a, output logic y);\n"
                              "logic value; assign value = a; assign y = value; endmodule\n")
            (project / "input.f").write_text("top.sv\n")
            gate = base / "gate"
            mapping = base / "mapping with space.json"
            metrics = base / "metrics with space.json"
            result = self._run(ENCRYPT, "--filelist", project / "input.f", "--category", "signals",
                               "--output-dir", gate, "--map", mapping, "--metrics", metrics)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(mapping.is_file())
            self.assertTrue(metrics.is_file())
            result = self._run(DECRYPT, "--map", mapping, "--gate-dir", gate, "--output-dir", base / "restored")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((base / "restored/top.sv").read_bytes(), source.read_bytes())


if __name__ == "__main__":
    unittest.main()
