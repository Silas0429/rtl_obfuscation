from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from rtl_obfuscator.source_set import SourceSetError, from_filelist


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "t134_fast_include_closure"
ENCRYPT = ROOT / "rtl_encrypt.py"
DECRYPT = ROOT / "rtl_decrypt.py"
FORMAL = ROOT / "scripts" / "formal_equivalence.py"
TOP = "t134_top"
SOURCES = (
    "external/vendor_a.v",
    "external/vendor_b.v",
    "project/top.sv",
)
INCLUDE = "external/vendor_function.inc"
PHYSICAL = (*SOURCES, INCLUDE)


class T134FastIncludeClosureTests(unittest.TestCase):
    @staticmethod
    def _run(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(script), *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )

    def test_public_fast_inc_roundtrip(self):
        with tempfile.TemporaryDirectory(prefix="t134-public-") as temporary:
            base = Path(temporary)
            gate = base / "gate"
            encrypted = self._run(
                ENCRYPT,
                "--filelist", str(FIXTURE / "design.f"),
                "--rewrite-root", str(FIXTURE / "project"),
                "--category", "signals",
                "--output-dir", str(gate),
            )
            self.assertEqual(encrypted.returncode, 0, encrypted.stderr)

            source_set = from_filelist(
                filelist=FIXTURE / "design.f",
                source_root=FIXTURE,
                rewrite_roots=(FIXTURE / "project",),
            )
            self.assertEqual(source_set.included_files, (INCLUDE,))
            self.assertEqual(source_set.ordered_source_files, SOURCES)
            self.assertEqual(source_set.compile_order, SOURCES)

            payload = json.loads(encrypted.stdout)
            report = json.loads((gate / "mapping.json").read_text(encoding="utf-8"))
            self.assertTrue(payload["summary"]["strict_compile_passed"])
            self.assertTrue(payload["summary"]["restored_byte_identical"])
            records = {
                item["original_name"]: item
                for item in report["mapping"]["records"]
            }
            self.assertEqual(set(records), {"first_stage", "second_stage"})
            self.assertTrue(all(item["action"] == "rename" for item in records.values()))
            self.assertEqual(report["source_set"]["included_files"], [INCLUDE])
            self.assertEqual(
                (gate / "design.f").read_text(encoding="utf-8").splitlines(),
                [
                    "+define+T134_WIDTH=4",
                    *((gate / item).resolve().as_posix() for item in SOURCES),
                ],
            )
            self.assertEqual(
                (gate / "export_design.f").read_text(encoding="utf-8").splitlines(),
                ["+define+T134_WIDTH=4", *(f"$OUT/{item}" for item in SOURCES)],
            )
            self.assertEqual(
                (gate / "original_design.f").read_bytes(),
                (FIXTURE / "design.f").read_bytes(),
            )

            execution = report["mapping_execution"]
            self.assertEqual(
                {item["file"] for item in execution["input_manifest"]},
                set(PHYSICAL),
            )
            per_file = {
                item["file"]: item
                for item in execution["per_file_mapping"]
            }
            for relative in ("external/vendor_a.v", "external/vendor_b.v", INCLUDE):
                self.assertEqual(
                    per_file[relative]["input_sha256"],
                    per_file[relative]["gate_sha256"],
                )
                self.assertEqual(
                    (gate / relative).read_bytes(),
                    (FIXTURE / relative).read_bytes(),
                )
                self.assertFalse(per_file[relative]["records"])

            restored = base / "restored"
            decrypted = self._run(
                DECRYPT,
                "--map", str(gate / "mapping.json"),
                "--gate-dir", str(gate),
                "--output-dir", str(restored),
            )
            self.assertEqual(decrypted.returncode, 0, decrypted.stderr)
            for relative in PHYSICAL:
                self.assertEqual(
                    (restored / relative).read_bytes(),
                    (FIXTURE / relative).read_bytes(),
                )

            shutil.copy2(FIXTURE / "formal_defs.sv", gate / "formal_defs.sv")
            shutil.copy2(FIXTURE / "formal.f", gate / "formal.f")
            formal = self._run(
                FORMAL,
                "--gold-filelist", str(FIXTURE / "formal.f"),
                "--gold-root", str(FIXTURE),
                "--gate-filelist", str(gate / "formal.f"),
                "--gate-root", str(gate),
                "--top", TOP,
                "--seq", "5",
            )
            self.assertEqual(formal.returncode, 0, formal.stdout + formal.stderr)
            self.assertEqual(
                json.loads(formal.stdout.strip().splitlines()[-1])["formal_equivalence"],
                "pass",
            )

            negative = base / "negative"
            shutil.copytree(gate, negative)
            top = negative / "project" / "top.sv"
            data = top.read_bytes()
            marker = data.rfind(b" ^ ")
            self.assertGreater(marker, 0)
            top.write_bytes(data[:marker] + b" | " + data[marker + 3:])
            failed = self._run(
                FORMAL,
                "--gold-filelist", str(FIXTURE / "formal.f"),
                "--gold-root", str(FIXTURE),
                "--gate-filelist", str(negative / "formal.f"),
                "--gate-root", str(negative),
                "--top", TOP,
                "--seq", "5",
            )
            combined = (failed.stdout + failed.stderr).lower()
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("unproven", combined)
            self.assertIn("equiv_status -assert", combined)

    def test_dynamic_macro_include_fails_before_fast_rename_index(self):
        with tempfile.TemporaryDirectory(prefix="t134-dynamic-") as temporary:
            root = Path(temporary)
            (root / "external").mkdir()
            (root / "external" / "dynamic.inc").write_text(
                "wire dynamic_value;\n", encoding="utf-8"
            )
            (root / "top.sv").write_text(
                "`define T134_INCLUDE(x) `include x\n"
                "module t134_dynamic(input logic in_data, output logic out_data);\n"
                "  logic state;\n"
                "  `T134_INCLUDE(\"external/dynamic.inc\")\n"
                "  assign state = in_data ^ dynamic_value;\n"
                "  assign out_data = state;\n"
                "endmodule\n",
                encoding="utf-8",
            )
            (root / "design.f").write_text("top.sv\n", encoding="utf-8")
            output = root.parent / f"{root.name}-output"
            result = self._run(
                ENCRYPT,
                "--filelist", str(root / "design.f"),
                "--rewrite-root", str(root),
                "--category", "signals",
                "--output-dir", str(output),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("dynamic.inc", result.stderr)
            self.assertNotIn("构建改名索引", result.stderr)
            self.assertFalse(output.exists())

    def test_arbitrary_suffix_closure_is_recursive_and_bounded(self):
        with tempfile.TemporaryDirectory(prefix="t134-closure-") as temporary:
            root = Path(temporary)
            (root / "project").mkdir()
            (root / "headers").mkdir()
            (root / "project" / "top.sv").write_text(
                '`include "first.custom"\nmodule t134_closure; endmodule\n',
                encoding="utf-8",
            )
            (root / "headers" / "first.custom").write_text(
                '`include "nested.second"\n', encoding="utf-8"
            )
            (root / "headers" / "nested.second").write_text(
                "wire nested_value;\n", encoding="utf-8"
            )
            filelist = root / "design.f"
            filelist.write_text("+incdir+headers\nproject/top.sv\n", encoding="utf-8")
            source_set = from_filelist(filelist=filelist, source_root=root)
            self.assertEqual(
                source_set.included_files,
                ("headers/first.custom", "headers/nested.second"),
            )
            self.assertEqual(source_set.compile_order, ("project/top.sv",))

            (root / "project" / "missing.sv").write_text(
                '`include "missing.custom"\nmodule t134_missing; endmodule\n',
                encoding="utf-8",
            )
            (root / "missing.f").write_text("project/missing.sv\n", encoding="utf-8")
            with self.assertRaises(SourceSetError) as missing:
                from_filelist(filelist=root / "missing.f", source_root=root)
            self.assertEqual(missing.exception.code, "SOURCESET_FILE_NOT_FOUND")

            (root / "project" / "ambiguous.sv").write_text(
                '`include "same.custom"\nmodule t134_ambiguous; endmodule\n',
                encoding="utf-8",
            )
            (root / "project" / "same.custom").write_text("wire local_value;\n")
            (root / "headers" / "same.custom").write_text("wire include_value;\n")
            (root / "ambiguous.f").write_text(
                "+incdir+headers\nproject/ambiguous.sv\n", encoding="utf-8"
            )
            with self.assertRaises(SourceSetError) as ambiguous:
                from_filelist(filelist=root / "ambiguous.f", source_root=root)
            self.assertEqual(ambiguous.exception.code, "SOURCESET_INCLUDE_AMBIGUOUS")

            (root / "bare.f").write_text("headers/first.custom\n", encoding="utf-8")
            with self.assertRaises(SourceSetError) as bare:
                from_filelist(filelist=root / "bare.f", source_root=root)
            self.assertEqual(bare.exception.code, "SOURCESET_UNSUPPORTED_FILE")

    def test_unquoted_incdir_whitespace_is_rejected_before_delivery(self):
        with tempfile.TemporaryDirectory(prefix="t137-incdir-space-") as temporary:
            root = Path(temporary)
            (root / "include with space").mkdir()
            (root / "top.sv").write_text(
                "module t137_incdir_space; endmodule\n", encoding="utf-8"
            )
            filelist = root / "design.f"
            filelist.write_text(
                "+incdir+include with space\ntop.sv\n", encoding="utf-8"
            )
            with self.assertRaises(SourceSetError) as rejected:
                from_filelist(filelist=filelist, source_root=root)
            self.assertEqual(
                rejected.exception.code,
                "SOURCESET_UNSUPPORTED_FILELIST_DIRECTIVE",
            )


if __name__ == "__main__":
    unittest.main()
