from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from rtl_obfuscator.project_discovery import compile_pyslang_source_set
from rtl_obfuscator.source_catalog import build_source_catalog
from rtl_obfuscator.source_set import SourceSetError, from_filelist


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "t133_include_physical_closure"
PUBLIC_ENCRYPT = ROOT / "rtl_encrypt.py"
PUBLIC_DECRYPT = ROOT / "rtl_decrypt.py"
FORMAL = ROOT / "scripts" / "formal_equivalence.py"
TOP = "t133_top"
SOURCES = (
    "external/vendor_a.v",
    "external/vendor_b.v",
    "project/top.sv",
)
INCLUDE = "external/vendor_function.inc"
PHYSICAL_FILES = (*SOURCES, INCLUDE)


class T133IncludePhysicalClosureTests(unittest.TestCase):
    @staticmethod
    def _run(script: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(script), *arguments],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )

    def test_public_inc_roundtrip(self):
        with tempfile.TemporaryDirectory(prefix="t133-public-") as temporary:
            root = Path(temporary)
            gate = root / "gate"
            encrypted = self._run(
                PUBLIC_ENCRYPT,
                "--filelist", str(FIXTURE / "design.f"),
                "--top", TOP,
                "--rewrite-root", str(FIXTURE / "project"),
                "--category", "all",
                "--output-dir", str(gate),
            )
            self.assertEqual(encrypted.returncode, 0, encrypted.stderr)

            source_set = from_filelist(
                filelist=FIXTURE / "design.f",
                source_root=FIXTURE,
                top=TOP,
                rewrite_roots=(FIXTURE / "project",),
            )
            self.assertEqual(source_set.included_files, (INCLUDE,))
            self.assertEqual(source_set.ordered_source_files, SOURCES)
            self.assertEqual(source_set.compile_order, SOURCES)
            self.assertNotIn(INCLUDE, source_set.compile_order)
            view = compile_pyslang_source_set(
                root=FIXTURE,
                compilation_files=source_set.compile_order,
                include_files=source_set.included_files,
                include_dirs=source_set.include_dirs,
                defines=dict(source_set.defines),
                top=TOP,
            )
            self.assertEqual(view.parse_errors, ())
            self.assertEqual(view.semantic_errors, ())
            include_buffers = {
                Path(view.source_manager.getFullPath(buffer)).resolve().as_posix()
                for buffer in view.source_manager.getAllBuffers()
                if str(view.source_manager.getBufferKind(buffer))
                == "BufferKind.IncludeFile"
            }
            self.assertEqual(include_buffers, {(FIXTURE / INCLUDE).resolve().as_posix()})
            catalog = build_source_catalog(source_set)
            self.assertEqual(catalog.readonly_include_files, (INCLUDE,))
            payload = json.loads(encrypted.stdout)
            report = json.loads((gate / "mapping.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["format"], "rtl-obfuscation.cli-vnext")
            self.assertEqual(payload["schema_version"], 2)
            self.assertTrue(payload["summary"]["strict_compile_passed"])
            self.assertTrue(payload["summary"]["restored_byte_identical"])
            self.assertGreater(payload["action_counts"]["rename"], 0)
            self.assertEqual(
                report["source_set"]["included_files"], [INCLUDE]
            )
            self.assertEqual(
                (gate / "design.f").read_text(encoding="utf-8"),
                "".join(f"{path}\n" for path in SOURCES),
            )

            manifest = report["mapping_execution"]
            input_manifest = {item["file"] for item in manifest["input_manifest"]}
            gate_manifest = {item["file"] for item in manifest["gate_manifest"]}
            self.assertEqual(input_manifest, set(PHYSICAL_FILES))
            self.assertEqual(gate_manifest, input_manifest)
            per_file = {
                item["file"]: item for item in manifest["per_file_mapping"]
            }
            for relative in ("external/vendor_a.v", "external/vendor_b.v", INCLUDE):
                self.assertEqual(
                    per_file[relative]["input_sha256"],
                    per_file[relative]["gate_sha256"],
                )
                self.assertEqual(
                    (gate / relative).read_bytes(), (FIXTURE / relative).read_bytes()
                )
                self.assertFalse(
                    any(
                        record["action"] == "rename"
                        for record in per_file[relative]["records"]
                    )
                )
            self.assertNotEqual(
                (gate / "project/top.sv").read_bytes(),
                (FIXTURE / "project/top.sv").read_bytes(),
            )

            restored = root / "restored"
            decrypted = self._run(
                PUBLIC_DECRYPT,
                "--map", str(gate / "mapping.json"),
                "--gate-dir", str(gate),
                "--output-dir", str(restored),
            )
            self.assertEqual(decrypted.returncode, 0, decrypted.stderr)
            for relative in PHYSICAL_FILES:
                self.assertEqual(
                    (restored / relative).read_bytes(), (FIXTURE / relative).read_bytes()
                )

            # The public gate remains the source of truth for rewritten RTL.  The
            # frozen formal filelist/define file are copied only as a
            # Formal-only harness; no encrypted design file is regenerated.
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
            formal_json = json.loads(formal.stdout.strip().splitlines()[-1])
            self.assertEqual(formal_json["formal_equivalence"], "pass")
            print(
                "T133_FORMAL_POSITIVE "
                + json.dumps(
                    {
                        "gold_filelist": str(FIXTURE / "formal.f"),
                        "gate_filelist": str(gate / "formal.f"),
                        "gate_root": str(gate),
                        "top": TOP,
                        "seq": 5,
                        "exit": formal.returncode,
                        "result": formal_json,
                    },
                    sort_keys=True,
                )
            )

            negative = root / "negative"
            shutil.copytree(gate, negative)
            top = negative / "project/top.sv"
            contents = top.read_bytes()
            marker = contents.rfind(b" ^ ")
            self.assertGreater(marker, 0)
            top.write_bytes(contents[:marker] + b" | " + contents[marker + 3:])
            negative_formal = self._run(
                FORMAL,
                "--gold-filelist", str(FIXTURE / "formal.f"),
                "--gold-root", str(FIXTURE),
                "--gate-filelist", str(negative / "formal.f"),
                "--gate-root", str(negative),
                "--top", TOP,
                "--seq", "5",
            )
            self.assertNotEqual(negative_formal.returncode, 0)
            negative_output = (
                negative_formal.stdout + negative_formal.stderr
            ).lower()
            self.assertIn("unproven", negative_output)
            self.assertIn("equiv_status -assert", negative_output)
            print(
                "T133_FORMAL_NEGATIVE "
                + json.dumps(
                    {
                        "gate_filelist": str(negative / "formal.f"),
                        "gate_root": str(negative),
                        "top": TOP,
                        "seq": 5,
                        "exit": negative_formal.returncode,
                        "contains_unproven": "unproven" in negative_output,
                        "contains_equiv_status_assert": "equiv_status -assert"
                        in negative_output,
                    },
                    sort_keys=True,
                )
            )

    def test_dynamic_macro_include_is_rejected_before_catalog_inventory(self):
        with tempfile.TemporaryDirectory(prefix="t133-dynamic-") as temporary:
            root = Path(temporary)
            (root / "external").mkdir()
            (root / "external" / "dynamic.inc").write_text(
                "wire dynamic_value;\n", encoding="utf-8"
            )
            (root / "top.sv").write_text(
                "`define T133_INCLUDE(x) `include x\n"
                "module t133_dynamic(input logic in_data, output logic out_data);\n"
                "    `T133_INCLUDE(\"external/dynamic.inc\")\n"
                "    assign out_data = in_data ^ dynamic_value;\n"
                "endmodule\n",
                encoding="utf-8",
            )
            (root / "design.f").write_text("top.sv\n", encoding="utf-8")
            source_set = from_filelist(
                filelist=root / "design.f", source_root=root, top="t133_dynamic"
            )
            self.assertEqual(source_set.included_files, ())
            self.assertEqual(source_set.compile_order, ("top.sv",))
            output = root.parent / "t133-dynamic-output"
            result = self._run(
                PUBLIC_ENCRYPT,
                "--filelist", str(root / "design.f"),
                "--top", "t133_dynamic",
                "--category", "all",
                "--output-dir", str(output),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("CLI_VNEXT_ORCHESTRATION_INVALID", result.stderr)
            self.assertIn("dynamic.inc", result.stderr)
            self.assertNotIn("[compile.catalog_inventory]", result.stderr)
            self.assertNotIn("SourceCatalog 建立物理模块清单", result.stderr)
            self.assertFalse(output.exists())

    def test_literal_arbitrary_suffix_closure_is_bounded_and_fail_closed(self):
        with tempfile.TemporaryDirectory(prefix="t133-closure-") as temporary:
            root = Path(temporary)
            (root / "project").mkdir()
            (root / "headers").mkdir()
            (root / "project" / "top.sv").write_text(
                '`include "first.custom"\nmodule t133_closure; endmodule\n',
                encoding="utf-8",
            )
            (root / "headers" / "first.custom").write_text(
                '`include "nested.second"\n', encoding="utf-8"
            )
            (root / "headers" / "nested.second").write_text(
                "wire nested_value;\n", encoding="utf-8"
            )
            filelist = root / "design.f"
            filelist.write_text(
                "+incdir+headers\nproject/top.sv\n", encoding="utf-8"
            )
            source_set = from_filelist(
                filelist=filelist, source_root=root, top="t133_closure"
            )
            self.assertEqual(
                source_set.included_files,
                ("headers/first.custom", "headers/nested.second"),
            )
            self.assertEqual(source_set.compile_order, ("project/top.sv",))

            missing = root / "missing.f"
            (root / "project" / "missing.sv").write_text(
                '`include "missing.custom"\nmodule t133_missing; endmodule\n',
                encoding="utf-8",
            )
            missing.write_text("project/missing.sv\n", encoding="utf-8")
            with self.assertRaises(SourceSetError) as missing_error:
                from_filelist(filelist=missing, source_root=root)
            self.assertEqual(missing_error.exception.code, "SOURCESET_FILE_NOT_FOUND")
            self.assertEqual(missing_error.exception.path, "missing.custom")

            (root / "project" / "ambiguous.sv").write_text(
                '`include "same.custom"\nmodule t133_ambiguous; endmodule\n',
                encoding="utf-8",
            )
            (root / "project" / "same.custom").write_text(
                "wire project_value;\n", encoding="utf-8"
            )
            (root / "headers" / "same.custom").write_text(
                "wire header_value;\n", encoding="utf-8"
            )
            ambiguous = root / "ambiguous.f"
            ambiguous.write_text(
                "+incdir+headers\nproject/ambiguous.sv\n", encoding="utf-8"
            )
            with self.assertRaises(SourceSetError) as ambiguous_error:
                from_filelist(filelist=ambiguous, source_root=root)
            self.assertEqual(
                ambiguous_error.exception.code, "SOURCESET_INCLUDE_AMBIGUOUS"
            )
            self.assertEqual(
                [item["path"] for item in ambiguous_error.exception.details],
                ["project/same.custom", "headers/same.custom"],
            )

            bare = root / "bare.f"
            bare.write_text("headers/first.custom\n", encoding="utf-8")
            with self.assertRaises(SourceSetError) as bare_error:
                from_filelist(filelist=bare, source_root=root)
            self.assertEqual(bare_error.exception.code, "SOURCESET_UNSUPPORTED_FILE")


if __name__ == "__main__":
    unittest.main()
