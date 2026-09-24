"""T148 black-box contract for original absolute and environment path delivery."""

from __future__ import annotations

import json
import hashlib
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


class T148ExportOriginalPathsTests(unittest.TestCase):
    def _fresh_gate(self, name: str) -> Path:
        gate = self.root / name
        result = subprocess.run(
            (
                sys.executable, str(ENCRYPT), "--filelist", str(self.project / "input.f"),
                "--top", "t148_top", "--category", "signals", "--output-dir", str(gate),
            ),
            cwd=ROOT, env=self.input_env, capture_output=True, text=True, timeout=180,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return gate

    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix="t148-export-paths-"))
        cls.addClassCleanup(shutil.rmtree, cls.root, ignore_errors=True)
        cls.project = cls.root / "project"
        for relative in ("rtl", "include", "lists"):
            (cls.project / relative).mkdir(parents=True, exist_ok=True)
        (cls.project / "include/defs.svh").write_text("`define T148_BIT 1'b1\n")
        (cls.project / "rtl/vendor.sv").write_text(
            "module t148_vendor(input logic a, output logic y); assign y = a; endmodule\n"
        )
        (cls.project / "rtl/top.sv").write_text(
            '`include "defs.svh"\n'
            "module t148_top(input logic a, output logic y);\n"
            "  logic local_signal;\n"
            "  t148_vendor u_vendor(.a(a), .y(local_signal));\n"
            "  assign y = local_signal ^ `T148_BIT;\n"
            "endmodule\n"
        )
        cls.nested_bytes = (
            b"// nested context\n"
            b"-v ${COMM_HDL_PATH}/rtl/vendor.sv\n"
            b"+incdir+${COMM_HDL_PATH}/include\n"
            b"+define+T148_ACTIVE=1\n"
        )
        (cls.project / "lists/nested.f").write_bytes(cls.nested_bytes)
        cls.source = (cls.project / "rtl/top.sv").resolve()
        cls.original_bytes = (
            b"# original top\n"
            b"-f ${COMM_HDL_PATH}/lists/nested.f\n"
            + cls.source.as_posix().encode() + b"\n"
        )
        (cls.project / "input.f").write_bytes(cls.original_bytes)
        cls.gold_formal = cls.root / "gold_formal.f"
        cls.gold_formal.write_text(
            f"-v {cls.project / 'rtl/vendor.sv'}\n"
            f"+incdir+{cls.project / 'include'}\n"
            "+define+T148_ACTIVE=1\n"
            f"{cls.source}\n"
        )
        cls.gate = cls.root / "gate"
        cls.input_env = os.environ.copy()
        cls.input_env["COMM_HDL_PATH"] = str(cls.project)
        result = subprocess.run(
            (
                sys.executable, str(ENCRYPT), "--filelist", str(cls.project / "input.f"),
                "--top", "t148_top", "--category", "signals", "--output-dir", str(cls.gate),
            ),
            cwd=ROOT, env=cls.input_env, capture_output=True, text=True, timeout=180,
            check=False,
        )
        if result.returncode != 0:
            raise AssertionError(result.stderr)
        cls.report = json.loads(result.stdout)

    def test_three_views_preserve_lines_and_original_token_rules(self):
        gate = self.gate.resolve().as_posix()
        source_relative_to_slash = self.source.as_posix().lstrip("/")
        self.assertEqual((self.gate / "original_design.f").read_bytes(), self.original_bytes)
        self.assertEqual(
            (self.gate / "design.f").read_bytes(),
            b"# original top\n"
            + f"-f {gate}/.rtl_obfuscation/filelists/design/lists/nested.f\n".encode()
            + f"{gate}/rtl/top.sv\n".encode(),
        )
        self.assertEqual(
            (self.gate / "export_design.f").read_bytes(),
            b"# original top\n"
            b"-f ${COMM_HDL_PATH}/lists/nested.f\n"
            + f"$OUT/{source_relative_to_slash}\n".encode(),
        )
        self.assertEqual(
            (self.gate / "lists/nested.f").read_bytes(), self.nested_bytes
        )
        original_nested = self.gate / ".rtl_obfuscation/filelists/original/lists/nested.f"
        self.assertEqual(original_nested.read_bytes(), self.nested_bytes)
        manifest = json.loads((self.gate / "mapping.json").read_text())["delivery_filelists"]
        self.assertEqual(
            manifest,
            {"originals": [
                {"path": "original_design.f", "sha256": hashlib.sha256(self.original_bytes).hexdigest()},
                {"path": ".rtl_obfuscation/filelists/original/lists/nested.f", "sha256": hashlib.sha256(self.nested_bytes).hexdigest()},
            ]},
        )
        self.assertEqual(
            (self.gate / source_relative_to_slash).read_bytes(),
            (self.gate / "rtl/top.sv").read_bytes(),
        )
        self.assertNotEqual(
            (self.gate / "rtl/top.sv").read_bytes(), self.source.read_bytes()
        )

    def test_relocated_export_compiles_and_restores(self):
        relocated = self.root / "relocated"
        shutil.copytree(self.gate, relocated)
        environment = self.input_env.copy()
        environment["OUT"] = str(relocated)
        environment["COMM_HDL_PATH"] = str(relocated)
        formal = subprocess.run(
            (
                sys.executable, str(FORMAL),
                "--gold-filelist", str(self.gold_formal),
                "--gold-root", str(self.project),
                "--gate-filelist", str(relocated / "export_design.f"),
                "--gate-root", str(relocated), "--top", "t148_top", "--seq", "5",
            ),
            cwd=ROOT, env=environment, capture_output=True, text=True, timeout=180,
            check=False,
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
        for relative in ("rtl/top.sv", "rtl/vendor.sv", "include/defs.svh"):
            self.assertEqual(
                (restored / relative).read_bytes(), (self.project / relative).read_bytes()
            )
        print("T148_FORMAL " + json.dumps(json.loads(formal.stdout), sort_keys=True))

    def test_tampered_absolute_mirror_is_rejected(self):
        altered = self._fresh_gate("altered")
        mirror = altered / self.source.as_posix().lstrip("/")
        mirror.write_bytes(mirror.read_bytes().replace(b" ^ ", b" | ", 1))
        decrypt = subprocess.run(
            (
                sys.executable, str(DECRYPT), "--map", str(altered / "mapping.json"),
                "--gate-dir", str(altered), "--output-dir", str(self.root / "bad-restore"),
            ),
            cwd=ROOT, capture_output=True, text=True, timeout=180, check=False,
        )
        self.assertNotEqual(decrypt.returncode, 0)
        self.assertIn("RESTORE_VNEXT_GATE_INVALID", decrypt.stderr)
        self.assertIn("delivery alias content differs", decrypt.stderr)

    def test_tandem_nested_environment_token_tamper_is_rejected(self):
        altered = self._fresh_gate("altered-nested-token")
        for relative in (
            ".rtl_obfuscation/filelists/export/lists/nested.f",
            "lists/nested.f",
        ):
            path = altered / relative
            path.write_bytes(path.read_bytes().replace(b"${COMM_HDL_PATH}", b"${OTHER_HDL_PATH}"))
        decrypt = subprocess.run(
            (
                sys.executable, str(DECRYPT), "--map", str(altered / "mapping.json"),
                "--gate-dir", str(altered), "--output-dir", str(self.root / "bad-nested-token-restore"),
            ),
            cwd=ROOT, capture_output=True, text=True, timeout=180, check=False,
        )
        self.assertNotEqual(decrypt.returncode, 0)
        self.assertIn("RESTORE_VNEXT_GATE_INVALID", decrypt.stderr)
        self.assertIn("export path token differs from original token rule", decrypt.stderr)

    def test_tampered_original_nested_snapshot_is_rejected(self):
        altered = self._fresh_gate("altered-original-nested")
        snapshot = altered / ".rtl_obfuscation/filelists/original/lists/nested.f"
        snapshot.write_bytes(snapshot.read_bytes().replace(b"${COMM_HDL_PATH}", b"${OTHER_HDL_PATH}"))
        decrypt = subprocess.run(
            (
                sys.executable, str(DECRYPT), "--map", str(altered / "mapping.json"),
                "--gate-dir", str(altered), "--output-dir", str(self.root / "bad-snapshot-restore"),
            ),
            cwd=ROOT, capture_output=True, text=True, timeout=180, check=False,
        )
        self.assertNotEqual(decrypt.returncode, 0)
        self.assertIn("RESTORE_VNEXT_GATE_INVALID", decrypt.stderr)
        self.assertIn("original filelist snapshot digest differs", decrypt.stderr)


if __name__ == "__main__":
    unittest.main()
