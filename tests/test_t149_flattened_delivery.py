"""Black-box contract for compile-oriented flattened filelist delivery."""

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
FORMAL = ROOT / "scripts/formal_equivalence.py"


class T149FlattenedDeliveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix="t149-flat-"))
        cls.addClassCleanup(shutil.rmtree, cls.root, ignore_errors=True)
        cls.project = cls.root / "project"
        for relative in ("rtl", "include", "lists"):
            (cls.project / relative).mkdir(parents=True, exist_ok=True)
        (cls.project / "include/defs.svh").write_text("`define T149_BIT 1'b1\n")
        (cls.project / "rtl/vendor.v").write_text(
            "module t149_vendor(input logic a, output logic y); assign y = a; endmodule\n"
        )
        (cls.project / "rtl/helper.sv").write_text(
            '`include "defs.svh"\n'
            "module t149_helper(input logic a, output logic y);\n"
            "  assign y = a ^ `T149_BIT;\n"
            "endmodule\n"
        )
        (cls.project / "rtl/top.sv").write_text(
            "module t149_top(input logic a, output logic y);\n"
            "  logic local_signal;\n"
            "  t149_helper u_helper(.a(a), .y(local_signal));\n"
            "  t149_vendor u_vendor(.a(local_signal), .y(y));\n"
            "endmodule\n"
        )
        (cls.project / "lists/context.f").write_text(
            "// nested context\n"
            "-v ${COMM_HDL_PATH}/rtl/vendor.v\n"
            "+incdir+${COMM_HDL_PATH}/include\n"
            "+define+T149_ACTIVE=1\n"
            f"{cls.project / 'rtl/helper.sv'}\n"
        )
        (cls.project / "input.f").write_text(
            "# top context\n"
            "-f ${COMM_HDL_PATH}/lists/context.f\n"
            f"{cls.project / 'rtl/top.sv'}\n"
        )
        cls.environment = os.environ.copy()
        cls.environment["COMM_HDL_PATH"] = str(cls.project)
        cls.gate = cls._encrypt(cls.root / "gate")

    @classmethod
    def _encrypt(cls, gate: Path) -> Path:
        result = subprocess.run(
            (
                sys.executable, str(ENCRYPT), "--filelist", str(cls.project / "input.f"),
                "--top", "t149_top", "--category", "signals", "--output-dir", str(gate),
            ),
            cwd=ROOT, env=cls.environment, capture_output=True, text=True,
            timeout=180, check=False,
        )
        if result.returncode != 0:
            raise AssertionError(result.stdout + result.stderr)
        return gate

    def test_flat_files_order_context_log_and_actual_gate_formal(self):
        flat = self.gate / "src_flattened"
        self.assertEqual(
            sorted(path.name for path in flat.iterdir()),
            ["helper.sv", "top.sv", "vendor.v"],
        )
        for relative in ("rtl/vendor.v", "rtl/helper.sv", "rtl/top.sv"):
            self.assertEqual(
                (flat / Path(relative).name).read_bytes(),
                (self.gate / relative).read_bytes(),
            )
        self.assertNotEqual(
            (flat / "top.sv").read_bytes(),
            (self.project / "rtl/top.sv").read_bytes(),
        )
        entries = [
            line.strip() for line in (self.gate / "design_flattened.f").read_text().splitlines()
            if line.strip() and not line.lstrip().startswith(("#", "//"))
        ]
        self.assertEqual(entries, [
            "-v $OUT_FLAT/vendor.v",
            "+incdir+$OUT/include",
            "+define+T149_ACTIVE=1",
            "$OUT_FLAT/helper.sv",
            "$OUT_FLAT/top.sv",
        ])
        self.assertFalse(any(line.startswith("-f") for line in entries))
        log = json.loads((self.gate / "src_flattened_log").read_text())
        self.assertEqual(log["format"], "rtl-obfuscation.src-flattened-log")
        self.assertEqual(log["schema_version"], 1)
        self.assertIs(log["compile_ready"], True)
        self.assertTrue(any(
            item["source"] == "rtl/helper.sv"
            and item["include"] == "defs.svh"
            and item["original_target"] == "include/defs.svh"
            and item["flattened_target"] == "include/defs.svh"
            and item["status"] == "same"
            for item in log["includes"]
        ))
        gold = self.root / "gold.f"
        gold.write_text(
            f"-v {self.project / 'rtl/vendor.v'}\n"
            f"+incdir+{self.project / 'include'}\n"
            "+define+T149_ACTIVE=1\n"
            f"{self.project / 'rtl/helper.sv'}\n"
            f"{self.project / 'rtl/top.sv'}\n"
        )
        environment = self.environment.copy()
        environment["OUT"] = str(self.gate)
        environment["OUT_FLAT"] = str(flat)
        formal = subprocess.run(
            (
                sys.executable, str(FORMAL), "--gold-filelist", str(gold),
                "--gold-root", str(self.project),
                "--gate-filelist", str(self.gate / "design_flattened.f"),
                "--gate-root", str(self.gate), "--top", "t149_top", "--seq", "5",
            ),
            cwd=ROOT, env=environment, capture_output=True, text=True,
            timeout=180, check=False,
        )
        self.assertEqual(formal.returncode, 0, formal.stdout + formal.stderr)
        self.assertEqual(json.loads(formal.stdout)["formal_equivalence"], "pass")
        restored = self.root / "restored"
        decrypt = subprocess.run(
            (
                sys.executable, str(DECRYPT), "--map", str(self.gate / "mapping.json"),
                "--gate-dir", str(self.gate), "--output-dir", str(restored),
            ),
            cwd=ROOT, capture_output=True, text=True, timeout=180, check=False,
        )
        self.assertEqual(decrypt.returncode, 0, decrypt.stdout + decrypt.stderr)
        for relative in ("rtl/vendor.v", "rtl/helper.sv", "rtl/top.sv", "include/defs.svh"):
            self.assertEqual((restored / relative).read_bytes(), (self.project / relative).read_bytes())
        print("T149_FORMAL " + json.dumps(json.loads(formal.stdout), sort_keys=True))

    def test_local_include_change_is_logged_without_rewriting_copy(self):
        project = self.root / "local-include"
        (project / "rtl").mkdir(parents=True)
        (project / "rtl/local.svh").write_text("`define T149_LOCAL 1'b1\n")
        source = project / "rtl/unsafe.sv"
        source.write_text(
            '`include "local.svh"\n'
            "module t149_unsafe(input logic a, output logic y); assign y = a ^ `T149_LOCAL; endmodule\n"
        )
        (project / "input.f").write_text(f"{source}\n")
        gate = self.root / "local-gate"
        result = subprocess.run(
            (
                sys.executable, str(ENCRYPT), "--filelist", str(project / "input.f"),
                "--top", "t149_unsafe", "--category", "signals", "--output-dir", str(gate),
            ),
            cwd=ROOT, capture_output=True, text=True, timeout=180, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            (gate / "src_flattened/unsafe.sv").read_bytes(),
            (gate / "rtl/unsafe.sv").read_bytes(),
        )
        log = json.loads((gate / "src_flattened_log").read_text())
        self.assertIs(log["compile_ready"], False)
        self.assertTrue(any(
            item["source"] == "rtl/unsafe.sv"
            and item["include"] == "local.svh"
            and item["original_target"] == "rtl/local.svh"
            and item["flattened_target"] is None
            and item["status"] == "missing"
            for item in log["includes"]
        ))
        restored = self.root / "local-restored"
        decrypt = subprocess.run(
            (
                sys.executable, str(DECRYPT), "--map", str(gate / "mapping.json"),
                "--gate-dir", str(gate), "--output-dir", str(restored),
            ),
            cwd=ROOT, capture_output=True, text=True, timeout=180, check=False,
        )
        self.assertEqual(decrypt.returncode, 0, decrypt.stdout + decrypt.stderr)

    def test_flat_delivery_tamper_is_rejected(self):
        for name in ("src_flattened/top.sv", "design_flattened.f", "src_flattened_log"):
            with self.subTest(name=name):
                gate = self._encrypt(self.root / ("tamper-" + name.replace("/", "-")))
                path = gate / name
                path.write_bytes(path.read_bytes() + b"\n# tampered\n")
                restored = self.root / ("bad-" + name.replace("/", "-"))
                decrypt = subprocess.run(
                    (
                        sys.executable, str(DECRYPT), "--map", str(gate / "mapping.json"),
                        "--gate-dir", str(gate), "--output-dir", str(restored),
                    ),
                    cwd=ROOT, capture_output=True, text=True, timeout=180, check=False,
                )
                self.assertNotEqual(decrypt.returncode, 0)
                self.assertIn("RESTORE_VNEXT_GATE_INVALID", decrypt.stderr)
                self.assertIn("flattened", decrypt.stderr)

    def test_basename_collision_refuses_atomic_publication(self):
        project = self.root / "collision"
        for relative in ("a", "b"):
            (project / relative).mkdir(parents=True)
        (project / "a/same.sv").write_text("module t149_a; endmodule\n")
        (project / "b/same.sv").write_text("module t149_b; endmodule\n")
        (project / "input.f").write_text(
            f"{project / 'a/same.sv'}\n{project / 'b/same.sv'}\n"
        )
        gate = self.root / "collision-gate"
        result = subprocess.run(
            (
                sys.executable, str(ENCRYPT), "--filelist", str(project / "input.f"),
                "--category", "signals", "--output-dir", str(gate),
            ),
            cwd=ROOT, capture_output=True, text=True, timeout=180, check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("flattened basename collision", result.stderr)
        self.assertFalse(gate.exists())


if __name__ == "__main__":
    unittest.main()
