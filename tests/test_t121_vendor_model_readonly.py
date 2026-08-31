from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from rtl_obfuscator.project_discovery import (
    _ifnone_at,
    compile_pyslang_source_set,
)
from rtl_obfuscator.rename_index import build_rename_index
from rtl_obfuscator.source_catalog import build_source_catalog
from rtl_obfuscator.source_set import (
    SourceSetError,
    from_filelist,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "t121_vendor_model_readonly"
PUBLIC_ENCRYPT = ROOT / "rtl_encrypt.py"
PUBLIC_DECRYPT = ROOT / "rtl_decrypt.py"
FORMAL = ROOT / "scripts" / "formal_equivalence.py"
TOP = "t121_top"
PHYSICAL_FILES = (
    "project/diagnostic_inside.v",
    "project/child.v",
    "external/provider.v",
    "external/clean_wrapper.v",
    "project/top.sv",
    "external/vcs/provider_body.v",
)


class T121VendorModelReadonlyTests(unittest.TestCase):
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

    @staticmethod
    def _source_set(filelist: str = "design.f"):
        return from_filelist(
            filelist=FIXTURE / filelist,
            source_root=FIXTURE,
            top=TOP,
            rewrite_roots=(FIXTURE / "project",),
        )

    @staticmethod
    def _write_case(root: Path, contents: str) -> Path:
        source = root / "case.v"
        source.write_text(contents, encoding="utf-8")
        filelist = root / "case.f"
        filelist.write_text("case.v\n", encoding="utf-8")
        return filelist

    @staticmethod
    def _root_relative(path: Path) -> str:
        return path.resolve().relative_to(Path("/")).as_posix()

    def test_exact_diagnostics_are_nonblocking_and_catalog_tracks_physical_file(self):
        source_set = self._source_set()
        self.assertEqual(source_set.rewrite_roots, ("project",))
        self.assertEqual(
            source_set.included_files,
            ("external/vcs/provider_body.v",),
        )
        self.assertNotIn("external/vcs/provider_body.v", source_set.compile_order)
        view = compile_pyslang_source_set(
            root=FIXTURE,
            compilation_files=source_set.compile_order,
            include_files=source_set.included_files,
            include_dirs=source_set.include_dirs,
            defines=dict(source_set.defines),
            top=source_set.top,
        )
        self.assertEqual(view.parse_errors, ())
        self.assertEqual(view.semantic_errors, ())
        vendor_codes = [str(item.code) for item in view.vendor_compatibility_errors]
        self.assertEqual(vendor_codes.count("DiagCode(UnknownDirective)"), 8)
        self.assertEqual(vendor_codes.count("DiagCode(IfNoneEdgeSensitive)"), 1)
        self.assertEqual(view.vendor_compatibility_files, ("project/diagnostic_inside.v",))
        nonblocking_codes = [str(item.code) for item in view.nonblocking_errors]
        self.assertIn("DiagCode(MissingTimeScale)", nonblocking_codes)
        self.assertNotIn(
            "DiagCode(MissingTimeScale)",
            vendor_codes,
        )
        self.assertEqual(
            len(view.raw_errors),
            len(view.nonblocking_errors),
        )

        catalog = build_source_catalog(source_set)
        self.assertEqual(catalog.readonly_vendor_files, ("project/diagnostic_inside.v",))
        self.assertEqual(catalog.readonly_include_files, ("external/vcs/provider_body.v",))
        self.assertEqual(catalog.to_report()["compile"]["catalog"], {
            "parse_errors": 0,
            "semantic_errors": 0,
        })

    def test_diagnostic_whitelist_fails_closed(self):
        cases = {
            "ordinary": "`SOME_UNKNOWN_MACRO\nmodule m; endmodule\n",
            "argument": "`protect(1)\nmodule m; endmodule\n",
            "extra_token": "`suppress_faults extra\nmodule m; endmodule\n",
            "unpaired": "`protect\nmodule m; endmodule\n",
            "reverse": "`endprotect\nmodule m; endmodule\n",
            "nested": "`protect\n`protect\n`endprotect\n`endprotect\nmodule m; endmodule\n",
            "parse": "module m; wire broken = ; endmodule\n",
            "semantic": "module m; missing_module u(); endmodule\n",
            "macro_virtual": "`define T121_VENDOR `protect\n`T121_VENDOR\nmodule m; endmodule\n",
        }
        with tempfile.TemporaryDirectory(prefix="t121-diagnostics-") as temporary:
            base = Path(temporary)
            for name, contents in cases.items():
                root = base / name
                root.mkdir()
                filelist = self._write_case(root, contents)
                with self.subTest(name=name):
                    with self.assertRaises(SourceSetError) as raised:
                        from_filelist(filelist=filelist, source_root=root)
                    self.assertEqual(raised.exception.code, "SOURCESET_DISCOVERY_FAILED")

            output = base / "must-not-publish"
            result = self._run(
                PUBLIC_ENCRYPT,
                "--filelist", str(base / "ordinary" / "case.f"),
                "--category", "all",
                "--output-dir", str(output),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("CLI_VNEXT_INPUT_INVALID", result.stderr)
            self.assertFalse(output.exists())

        self.assertTrue(_ifnone_at(b"ifnone (posedge A)", 0))
        self.assertFalse(_ifnone_at(b"xifnone (posedge A)", 1))
        self.assertFalse(_ifnone_at(b"ifnone_suffix", 0))

    def test_rewrite_roots_are_canonical_unioned_and_mode_bounded(self):
        bare = self._source_set("design.f")
        library = self._source_set("design_v.f")
        self.assertEqual(bare.to_report(), library.to_report())
        self.assertEqual(bare.rewrite_roots, library.rewrite_roots)

        unioned = from_filelist(
            filelist=FIXTURE / "design.f",
            source_root=FIXTURE,
            top=TOP,
            rewrite_roots=(
                FIXTURE / "project",
                FIXTURE / "external",
                FIXTURE / "project",
            ),
        )
        self.assertEqual(unioned.rewrite_roots, ("project", "external"))

        relative = from_filelist(
            filelist=FIXTURE / "design.f",
            source_root=FIXTURE,
            top=TOP,
            rewrite_roots=(Path("tests/fixtures/t121_vendor_model_readonly/project"),),
        )
        self.assertEqual(relative.rewrite_roots, ("project",))

        with tempfile.TemporaryDirectory(prefix="t121-roots-") as temporary:
            root = Path(temporary)
            (root / "owned" / "nested").mkdir(parents=True)
            (root / "owned-neighbor").mkdir()
            (root / "headers").mkdir()
            (root / "owned" / "top.v").write_text("module top; endmodule\n", encoding="utf-8")
            (root / "owned" / "nested" / "child.v").write_text("module child; endmodule\n", encoding="utf-8")
            (root / "owned-neighbor" / "other.v").write_text("module other; endmodule\n", encoding="utf-8")
            (root / "headers" / "defs.svh").write_text("`define X 1\n", encoding="utf-8")
            filelist = root / "all.f"
            filelist.write_text(
                "headers/defs.svh\nowned/top.v\nowned/nested/child.v\nowned-neighbor/other.v\n",
                encoding="utf-8",
            )
            nested = from_filelist(
                filelist=filelist,
                source_root=root,
                rewrite_roots=(root / "owned", root / "owned" / "nested"),
            )
            self.assertEqual(nested.rewrite_roots, ("owned", "owned/nested"))

            invalid = (
                root / "missing",
                root.parent,
                root / "headers",
            )
            for rewrite_root in invalid:
                with self.subTest(rewrite_root=rewrite_root):
                    with self.assertRaises(SourceSetError) as raised:
                        from_filelist(
                            filelist=filelist,
                            source_root=root,
                            rewrite_roots=(rewrite_root,),
                        )
                    self.assertIn(
                        raised.exception.code,
                        {"SOURCESET_REWRITE_ROOT_INVALID", "SOURCESET_PATH_OUTSIDE_ROOT"},
                    )

            neighbor_filelist = root / "neighbor.f"
            neighbor_filelist.write_text("owned-neighbor/other.v\n", encoding="utf-8")
            with self.assertRaises(SourceSetError) as raised:
                from_filelist(
                    filelist=neighbor_filelist,
                    source_root=root,
                    rewrite_roots=(root / "owned",),
                )
            self.assertEqual(raised.exception.code, "SOURCESET_REWRITE_ROOT_INVALID")

            single_output = root / "single-output"
            single = self._run(
                PUBLIC_ENCRYPT,
                "--input", str(root / "owned" / "top.v"),
                "--rewrite-root", str(root / "owned"),
                "--category", "all",
                "--output-dir", str(single_output),
            )
            self.assertNotEqual(single.returncode, 0)
            self.assertIn("CLI_VNEXT_INPUT_INVALID", single.stderr)
            self.assertFalse(single_output.exists())

            project_output = root / "project-output"
            project = self._run(
                PUBLIC_ENCRYPT,
                "--source-root", str(root / "owned"),
                "--top", "top",
                "--rewrite-root", str(root / "owned"),
                "--category", "all",
                "--output-dir", str(project_output),
            )
            self.assertNotEqual(project.returncode, 0)
            self.assertIn("CLI_VNEXT_INPUT_INVALID", project.stderr)
            self.assertFalse(project_output.exists())

            decrypt_output = root / "decrypt-output"
            decrypt = self._run(
                PUBLIC_DECRYPT,
                "--map", str(root / "missing-map.json"),
                "--gate-dir", str(root / "missing-gate"),
                "--output-dir", str(decrypt_output),
                "--rewrite-root", str(root / "owned"),
            )
            self.assertNotEqual(decrypt.returncode, 0)
            self.assertIn("CLI_VNEXT_INPUT_INVALID", decrypt.stderr)
            self.assertFalse(decrypt_output.exists())

    def test_readonly_firewall_is_per_record_and_v_is_only_syntax(self):
        indexes = []
        for filelist in ("design.f", "design_v.f"):
            catalog = build_source_catalog(self._source_set(filelist))
            indexes.append(build_rename_index(catalog, categories=("signals", "ports")))
        reports = [index.to_report() for index in indexes]
        self.assertEqual(reports[0], reports[1])
        symbols = indexes[0].symbols
        by_name_file = {
            (item.declaration.file, item.name): item
            for item in symbols
        }
        self.assertEqual(
            by_name_file[("project/diagnostic_inside.v", "diagnostic_signal")].reason,
            "readonly_vendor_model",
        )
        self.assertEqual(
            by_name_file[("external/clean_wrapper.v", "wrapper_signal")].reason,
            "outside_rewrite_root",
        )
        provider_port = by_name_file[("external/provider.v", "data_i")]
        self.assertEqual(provider_port.reason, "outside_rewrite_root")
        self.assertIn(
            "external/vcs/provider_body.v",
            {item.source_range.file for item in provider_port.occurrences},
        )
        self.assertEqual(
            by_name_file[("external/vcs/provider_body.v", "provider_hidden")].reason,
            "outside_rewrite_root",
        )
        self.assertEqual(
            by_name_file[("project/child.v", "child_signal")].support,
            "eligible",
        )
        self.assertEqual(
            by_name_file[("project/top.sv", "project_signal")].support,
            "eligible",
        )

    def test_source_suffix_include_missing_and_ambiguity_fail_closed(self):
        with tempfile.TemporaryDirectory(prefix="t121-includes-") as temporary:
            root = Path(temporary)
            (root / "rtl" / "vcs").mkdir(parents=True)
            (root / "inc" / "vcs").mkdir(parents=True)
            top = root / "rtl" / "top.v"
            top.write_text(
                "module include_top;\n`include \"vcs/body.v\"\nendmodule\n",
                encoding="utf-8",
            )
            filelist = root / "design.f"
            filelist.write_text("rtl/top.v\n", encoding="utf-8")
            with self.assertRaises(SourceSetError) as missing:
                from_filelist(filelist=filelist, source_root=root)
            self.assertEqual(missing.exception.code, "SOURCESET_FILE_NOT_FOUND")

            local = root / "rtl" / "vcs" / "body.v"
            local.write_text("wire local_body;\n", encoding="utf-8")
            unique = from_filelist(filelist=filelist, source_root=root)
            self.assertEqual(unique.included_files, ("rtl/vcs/body.v",))
            self.assertEqual(unique.compile_order, ("rtl/top.v",))

            other = root / "inc" / "vcs" / "body.v"
            other.write_text("wire inc_body;\n", encoding="utf-8")
            filelist.write_text("+incdir+inc\nrtl/top.v\n", encoding="utf-8")
            with self.assertRaises(SourceSetError) as ambiguous:
                from_filelist(filelist=filelist, source_root=root)
            self.assertEqual(ambiguous.exception.code, "SOURCESET_INCLUDE_AMBIGUOUS")
            self.assertEqual(
                [item["path"] for item in ambiguous.exception.details],
                ["rtl/vcs/body.v", "inc/vcs/body.v"],
            )

    def test_public_gate_restore_v_equivalence_and_formal_positive_negative(self):
        with tempfile.TemporaryDirectory(prefix="t121-formal-") as temporary:
            root = Path(temporary)
            gates = []
            payloads = []
            for name, filelist in (("bare", "design.f"), ("library", "design_v.f")):
                gate = root / f"gate-{name}"
                encrypted = self._run(
                    PUBLIC_ENCRYPT,
                    "--filelist", str(FIXTURE / filelist),
                    "--top", TOP,
                    "--category", "all",
                    "--rewrite-root", str(FIXTURE / "project"),
                    "--output-dir", str(gate),
                )
                self.assertEqual(encrypted.returncode, 0, encrypted.stderr)
                payload = json.loads((gate / "mapping.json").read_text(encoding="utf-8"))
                self.assertEqual(payload["source_set"]["schema_version"], 1)
                self.assertEqual(payload["mapping"]["schema_version"], 2)
                self.assertEqual(payload["mapping_execution"]["schema_version"], 2)
                self.assertNotIn("rewrite_roots", payload["source_set"])
                self.assertTrue(payload["summary"]["strict_compile_passed"])
                self.assertTrue(payload["summary"]["restored_byte_identical"])
                self.assertGreater(payload["summary"]["rename"], 0)
                self.assertGreater(payload["summary"]["modified_tokens"], 0)
                gates.append(gate)
                payloads.append(payload)

            self.assertEqual(payloads[0]["source_set"], payloads[1]["source_set"])
            def normalized_actions(payload):
                return [
                    {
                        "file": item["file"],
                        "records": [
                            {
                                "symbol_id": record["symbol_id"],
                                "category": record["category"],
                                "action": record["action"],
                                "reason": record["reason"],
                                "ranges": [
                                    {
                                        "provenance": value["provenance"],
                                        "source_range": value["source_range"],
                                    }
                                    for value in record["ranges"]
                                ],
                            }
                            for record in item["records"]
                        ],
                    }
                    for item in payload["mapping_execution"]["per_file_mapping"]
                ]

            self.assertEqual(normalized_actions(payloads[0]), normalized_actions(payloads[1]))

            gate = gates[0]
            per_file = {
                item["file"]: item
                for item in payloads[0]["mapping_execution"]["per_file_mapping"]
            }
            for item in per_file.values():
                for record in item["records"]:
                    if record["action"] != "rename":
                        continue
                    for value in record["ranges"]:
                        self.assertTrue(value["source_range"]["file"].startswith("project/"))
            for file in (
                "project/diagnostic_inside.v",
                "external/provider.v",
                "external/clean_wrapper.v",
                "external/vcs/provider_body.v",
            ):
                self.assertEqual(per_file[file]["input_sha256"], per_file[file]["gate_sha256"])
                self.assertEqual((gate / file).read_bytes(), (FIXTURE / file).read_bytes())
            design_order = (gate / "design.f").read_text(encoding="utf-8").splitlines()
            self.assertNotIn("external/vcs/provider_body.v", design_order)
            self.assertTrue((gate / "external/vcs/provider_body.v").is_file())

            restored = root / "restored"
            decrypted = self._run(
                PUBLIC_DECRYPT,
                "--map", str(gate / "mapping.json"),
                "--gate-dir", str(gate),
                "--output-dir", str(restored),
            )
            self.assertEqual(decrypted.returncode, 0, decrypted.stderr)
            for file in PHYSICAL_FILES:
                self.assertEqual((restored / file).read_bytes(), (FIXTURE / file).read_bytes())

            formal_arguments = (
                "--gold-filelist", str(FIXTURE / "design.f"),
                "--gold-root", str(FIXTURE),
                "--gate-filelist", str(gate / "design.f"),
                "--gate-root", str(gate),
                "--top", TOP,
                "--seq", "5",
            )
            positive = self._run(FORMAL, *formal_arguments)
            self.assertEqual(positive.returncode, 0, positive.stdout + positive.stderr)
            positive_json = json.loads(positive.stdout.strip().splitlines()[-1])
            self.assertEqual(positive_json["formal_equivalence"], "pass")
            print("T121_FORMAL_POSITIVE " + json.dumps({
                "gold": str(FIXTURE),
                "gate": str(gate),
                "top": TOP,
                "exit": positive.returncode,
                "json": positive_json,
            }, sort_keys=True))

            negative = root / "negative"
            shutil.copytree(gate, negative)
            target = negative / "project" / "top.sv"
            original = target.read_bytes()
            position = original.rfind(b" ^ ")
            self.assertGreater(position, 0)
            mutated = original[:position] + b" | " + original[position + 3:]
            self.assertNotEqual(mutated, original)
            target.write_bytes(mutated)

            negative_set = from_filelist(
                filelist=negative / "design.f",
                source_root=negative,
                top=TOP,
            )
            negative_view = compile_pyslang_source_set(
                root=negative,
                compilation_files=negative_set.compile_order,
                include_files=negative_set.included_files,
                include_dirs=negative_set.include_dirs,
                defines=dict(negative_set.defines),
                top=TOP,
            )
            self.assertEqual(negative_view.parse_errors, ())
            self.assertEqual(negative_view.semantic_errors, ())
            strict = subprocess.run(
                [
                    "iverilog", "-g2012", "-t", "null", "-s", TOP,
                    "-I", str(negative / "external"),
                    *[str(negative / file) for file in negative_set.compile_order],
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
            self.assertEqual(strict.returncode, 0, strict.stdout + strict.stderr)
            negative_result = self._run(
                FORMAL,
                "--gold-filelist", str(FIXTURE / "design.f"),
                "--gold-root", str(FIXTURE),
                "--gate-filelist", str(negative / "design.f"),
                "--gate-root", str(negative),
                "--top", TOP,
                "--seq", "5",
            )
            self.assertNotEqual(negative_result.returncode, 0)
            combined = (negative_result.stdout + negative_result.stderr).lower()
            self.assertIn("unproven", combined)
            self.assertIn("equiv_status -assert", combined)
            print("T121_FORMAL_NEGATIVE " + json.dumps({
                "gold": str(FIXTURE),
                "gate": str(negative),
                "top": TOP,
                "strict_compile_exit": strict.returncode,
                "exit": negative_result.returncode,
                "mutation": "XOR -> OR in actual gate project/top.sv",
                "evidence": "unproven; equiv_status -assert",
            }, sort_keys=True))

    def test_public_multi_root_rewrite_allowlist_with_global_sourceset_root(self):
        with tempfile.TemporaryDirectory(prefix="t121-global-root-") as temporary:
            root = Path(temporary)
            extra = root / "extra_global.v"
            extra.write_text(
                "module t121_extra_global;\n"
                "    wire extra_signal;\n"
                "    assign extra_signal = 1'b0;\n"
                "endmodule\n",
                encoding="utf-8",
            )
            explicit = (
                FIXTURE / "project/diagnostic_inside.v",
                FIXTURE / "project/child.v",
                FIXTURE / "external/provider.v",
                FIXTURE / "external/clean_wrapper.v",
                FIXTURE / "project/top.sv",
                extra,
            )
            filelist = root / "wrapper.f"
            filelist.write_text(
                "".join(f"{path.resolve()}\n" for path in explicit),
                encoding="utf-8",
            )
            source_set = from_filelist(
                filelist=filelist,
                top=TOP,
                rewrite_roots=(FIXTURE / "project",),
            )
            self.assertEqual(source_set.source_root, Path("/"))
            self.assertEqual(
                source_set.rewrite_roots,
                (self._root_relative(FIXTURE / "project"),),
            )
            expected_order = tuple(self._root_relative(path) for path in explicit)
            included = self._root_relative(FIXTURE / "external/vcs/provider_body.v")
            self.assertEqual(source_set.compile_order, expected_order)
            self.assertEqual(source_set.included_files, (included,))

            original = {
                file: (Path("/") / file).read_bytes()
                for file in (*expected_order, included)
            }
            gate = root / "gate-global"
            encrypted = self._run(
                PUBLIC_ENCRYPT,
                "--filelist", str(filelist),
                "--top", TOP,
                "--rewrite-root", str(FIXTURE / "project"),
                "--category", "all",
                "--output-dir", str(gate),
            )
            self.assertEqual(encrypted.returncode, 0, encrypted.stderr)
            self.assertTrue(gate.is_dir())
            payload = json.loads((gate / "mapping.json").read_text(encoding="utf-8"))
            self.assertTrue(payload["summary"]["strict_compile_passed"])
            self.assertTrue(payload["summary"]["restored_byte_identical"])
            self.assertGreater(payload["summary"]["modified_tokens"], 0)
            self.assertEqual(
                (gate / "design.f").read_text(encoding="utf-8"),
                "".join(f"{file}\n" for file in expected_order),
            )

            manifest_files = {
                item["file"]
                for item in payload["mapping_execution"]["input_manifest"]
            }
            self.assertEqual(manifest_files, {*expected_order, included})
            self.assertEqual(
                manifest_files,
                {
                    item["file"]
                    for item in payload["mapping_execution"]["gate_manifest"]
                },
            )
            self.assertNotIn(included, payload["source_set"]["compile_order"])
            self.assertTrue((gate / included).is_file())

            project_root = (FIXTURE / "project").resolve()
            landed = []
            per_file = {
                item["file"]: item
                for item in payload["mapping_execution"]["per_file_mapping"]
            }
            for item in per_file.values():
                for record in item["records"]:
                    if record["action"] != "rename":
                        continue
                    for value in record["ranges"]:
                        physical = (Path("/") / value["source_range"]["file"]).resolve()
                        physical.relative_to(project_root)
                        landed.append(physical)
            self.assertTrue(landed)

            readonly = (
                self._root_relative(FIXTURE / "project/diagnostic_inside.v"),
                self._root_relative(FIXTURE / "external/provider.v"),
                self._root_relative(FIXTURE / "external/clean_wrapper.v"),
                included,
                self._root_relative(extra),
            )
            for file in readonly:
                self.assertEqual(per_file[file]["input_sha256"], per_file[file]["gate_sha256"])
                self.assertEqual((gate / file).read_bytes(), original[file])

            restored = root / "restored-global"
            decrypted = self._run(
                PUBLIC_DECRYPT,
                "--map", str(gate / "mapping.json"),
                "--gate-dir", str(gate),
                "--output-dir", str(restored),
            )
            self.assertEqual(decrypted.returncode, 0, decrypted.stderr)
            for file, data in original.items():
                self.assertEqual((restored / file).read_bytes(), data)


if __name__ == "__main__":
    unittest.main()
