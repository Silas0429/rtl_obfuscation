from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from rtl_obfuscator.source_set import (
    SourceSetError,
    from_filelist,
    from_project_root,
    from_single_file,
    infer_filelist_root,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "t120_explicit_vic_include"
CHILD = FIXTURE / "rtl" / "child.v"
PUBLIC_ENCRYPT = ROOT / "rtl_encrypt.py"
PUBLIC_DECRYPT = ROOT / "rtl_decrypt.py"
FORMAL = ROOT / "scripts" / "formal_equivalence.py"
VIC_NAME = "dmac_parameters_64bit.vic"


class T120ExplicitVicIncludeReferenceTests(unittest.TestCase):
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
    def _write_vic(path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "/* Arbitration modes */\n"
            "parameter T120_SIMPLE_RR = 2'b00;\n"
            "parameter T120_WIDTH = 8;\n",
            encoding="utf-8",
        )

    @staticmethod
    def _write_top(
        path: Path,
        *,
        top: str,
        include_name: str,
        compilation_unit_include: bool = False,
        instantiate_child: bool = False,
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        prefix = f'`include "{include_name}"\n' if compilation_unit_include else ""
        body_include = (
            "" if compilation_unit_include else f'    `include "{include_name}"\n'
        )
        child = (
            "    t120_child #(.WIDTH(T120_WIDTH)) u_child "
            "(.i(in_data), .o(child_data));\n"
            if instantiate_child
            else "    assign child_data = in_data;\n"
        )
        path.write_text(
            prefix
            + f"module {top} (\n"
            "    input  logic [7:0] in_data,\n"
            "    output logic [7:0] out_data\n"
            ");\n"
            + body_include
            + "    logic [T120_WIDTH-1:0] child_data;\n"
            "    logic [T120_WIDTH-1:0] top_signal;\n"
            + child
            + "    assign top_signal = child_data ^ "
            "{{(T120_WIDTH-1){1'b0}}, T120_SIMPLE_RR[0]};\n"
            "    assign out_data = top_signal;\n"
            "endmodule\n",
            encoding="utf-8",
        )

    @staticmethod
    def _root_relative(path: Path) -> str:
        return path.resolve().relative_to(Path("/")).as_posix()

    def test_exact_explicit_match_direct_incdir_nested_and_indirect(self):
        with tempfile.TemporaryDirectory(prefix="t120-positive-") as temporary:
            root = Path(temporary)

            local = root / "local"
            vic = local / VIC_NAME
            top = local / "top.sv"
            self._write_vic(vic)
            self._write_top(
                top,
                top="t120_local_top",
                include_name=VIC_NAME,
            )
            local_filelist = root / "local.f"
            local_filelist.write_text(
                f"{vic.relative_to(root).as_posix()}\n"
                f"{top.relative_to(root).as_posix()}\n",
                encoding="utf-8",
            )
            local_set = from_filelist(
                filelist=local_filelist,
                source_root=root,
                top="t120_local_top",
            )
            self.assertEqual(
                local_set.included_files,
                ("local/dmac_parameters_64bit.vic",),
            )
            self.assertEqual(
                local_set.compile_order,
                ("local/dmac_parameters_64bit.vic", "local/top.sv"),
            )

            unit_top = local / "unit_top.sv"
            self._write_top(
                unit_top,
                top="t120_unit_top",
                include_name=VIC_NAME,
                compilation_unit_include=True,
            )
            unit_filelist = root / "unit.f"
            unit_filelist.write_text(
                "local/dmac_parameters_64bit.vic\nlocal/unit_top.sv\n",
                encoding="utf-8",
            )
            unit_set = from_filelist(
                filelist=unit_filelist,
                source_root=root,
                top="t120_unit_top",
            )
            self.assertEqual(
                unit_set.compile_order,
                ("local/dmac_parameters_64bit.vic", "local/unit_top.sv"),
            )

            incdir = root / "incdir"
            incdir_vic = incdir / VIC_NAME
            self._write_vic(incdir_vic)
            incdir_top = root / "incdir_top.sv"
            self._write_top(
                incdir_top,
                top="t120_incdir_top",
                include_name=VIC_NAME,
            )
            incdir_filelist = root / "incdir.f"
            incdir_filelist.write_text(
                "+incdir+incdir\nincdir/dmac_parameters_64bit.vic\n"
                "incdir_top.sv\n",
                encoding="utf-8",
            )
            incdir_set = from_filelist(
                filelist=incdir_filelist,
                source_root=root,
                top="t120_incdir_top",
            )
            self.assertEqual(
                incdir_set.compile_order,
                ("incdir/dmac_parameters_64bit.vic", "incdir_top.sv"),
            )

            nested_top = local / "nested_top.sv"
            self._write_top(
                nested_top,
                top="t120_nested_top",
                include_name=VIC_NAME,
            )
            nested_filelist = root / "nested" / "child.f"
            nested_filelist.parent.mkdir()
            nested_filelist.write_text("$T120_VIC\n$T120_TOP\n", encoding="utf-8")
            master = root / "master.f"
            master.write_text("-f $T120_NESTED\n", encoding="utf-8")
            with mock.patch.dict(
                os.environ,
                {
                    "T120_NESTED": str(nested_filelist),
                    "T120_VIC": str(vic),
                    "T120_TOP": str(nested_top),
                },
                clear=False,
            ):
                nested_set = from_filelist(
                    filelist=master,
                    top="t120_nested_top",
                )
            self.assertEqual(
                nested_set.compile_order,
                ("local/dmac_parameters_64bit.vic", "local/nested_top.sv"),
            )

            indirect = root / "indirect"
            indirect_vic = indirect / VIC_NAME
            self._write_vic(indirect_vic)
            bridge = indirect / "bridge.h"
            bridge.write_text(f'`include "{VIC_NAME}"\n', encoding="utf-8")
            indirect_top = indirect / "top.sv"
            self._write_top(
                indirect_top,
                top="t120_indirect_top",
                include_name="bridge.h",
            )
            indirect_filelist = root / "indirect.f"
            indirect_filelist.write_text(
                "indirect/dmac_parameters_64bit.vic\nindirect/top.sv\n",
                encoding="utf-8",
            )
            indirect_set = from_filelist(
                filelist=indirect_filelist,
                source_root=root,
                top="t120_indirect_top",
            )
            self.assertEqual(
                indirect_set.included_files,
                ("indirect/dmac_parameters_64bit.vic", "indirect/bridge.h"),
            )
            self.assertEqual(
                indirect_set.compile_order,
                ("indirect/dmac_parameters_64bit.vic", "indirect/top.sv"),
            )

            for suffix, explicit_header in (("svh", True), ("vh", False)):
                header_root = root / f"indirect-{suffix}"
                header_vic = header_root / VIC_NAME
                self._write_vic(header_vic)
                header = header_root / f"bridge.{suffix}"
                header.write_text(f'`include "{VIC_NAME}"\n', encoding="utf-8")
                header_top = header_root / "top.sv"
                self._write_top(
                    header_top,
                    top=f"t120_indirect_{suffix}_top",
                    include_name=f"bridge.{suffix}",
                )
                entries = [
                    f"indirect-{suffix}/{VIC_NAME}",
                    *(
                        [f"indirect-{suffix}/bridge.{suffix}"]
                        if explicit_header
                        else []
                    ),
                    f"indirect-{suffix}/top.sv",
                ]
                header_filelist = root / f"indirect-{suffix}.f"
                header_filelist.write_text(
                    "".join(f"{entry}\n" for entry in entries),
                    encoding="utf-8",
                )
                header_set = from_filelist(
                    filelist=header_filelist,
                    source_root=root,
                    top=f"t120_indirect_{suffix}_top",
                )
                self.assertEqual(
                    header_set.included_files,
                    (
                        f"indirect-{suffix}/{VIC_NAME}",
                        f"indirect-{suffix}/bridge.{suffix}",
                    ),
                )
                expected_compile_order = tuple(
                    entries if explicit_header else (entries[0], entries[-1])
                )
                self.assertEqual(header_set.compile_order, expected_compile_order)

    def test_include_only_and_same_basename_fail_closed(self):
        with tempfile.TemporaryDirectory(prefix="t120-negative-") as temporary:
            root = Path(temporary)

            local = root / "local"
            local_vic = local / VIC_NAME
            local_top = local / "top.sv"
            self._write_vic(local_vic)
            self._write_top(
                local_top,
                top="t120_include_only_local",
                include_name=VIC_NAME,
            )
            local_filelist = root / "local.f"
            local_filelist.write_text("local/top.sv\n", encoding="utf-8")

            incdir = root / "incdir"
            incdir_vic = incdir / VIC_NAME
            self._write_vic(incdir_vic)
            incdir_top = root / "incdir_top.sv"
            self._write_top(
                incdir_top,
                top="t120_include_only_incdir",
                include_name=VIC_NAME,
            )
            incdir_filelist = root / "incdir.f"
            incdir_filelist.write_text(
                "+incdir+incdir\nincdir_top.sv\n", encoding="utf-8"
            )

            listed = root / "listed" / VIC_NAME
            same_name = root / "consumer" / VIC_NAME
            same_name_top = root / "consumer" / "top.sv"
            self._write_vic(listed)
            self._write_vic(same_name)
            self._write_top(
                same_name_top,
                top="t120_same_basename",
                include_name=VIC_NAME,
            )
            same_name_filelist = root / "same-name.f"
            same_name_filelist.write_text(
                "listed/dmac_parameters_64bit.vic\nconsumer/top.sv\n",
                encoding="utf-8",
            )

            cases = (
                (
                    local_filelist,
                    "t120_include_only_local",
                    "local/dmac_parameters_64bit.vic",
                ),
                (
                    incdir_filelist,
                    "t120_include_only_incdir",
                    "incdir/dmac_parameters_64bit.vic",
                ),
                (
                    same_name_filelist,
                    "t120_same_basename",
                    "consumer/dmac_parameters_64bit.vic",
                ),
            )
            for filelist, top_name, expected_path in cases:
                with self.subTest(top=top_name):
                    with self.assertRaises(SourceSetError) as raised:
                        from_filelist(
                            filelist=filelist,
                            source_root=root,
                            top=top_name,
                        )
                    self.assertEqual(raised.exception.code, "SOURCESET_UNSUPPORTED_FILE")
                    self.assertEqual(raised.exception.path, expected_path)
                    self.assertEqual(
                        raised.exception.message,
                        ".vic parameter context must be listed explicitly in the filelist",
                    )

    def test_t118_vic_boundaries_remain_closed(self):
        with tempfile.TemporaryDirectory(prefix="t120-boundaries-") as temporary:
            root = Path(temporary)
            rtl = root / "rtl"
            rtl.mkdir()
            vic = rtl / VIC_NAME
            self._write_vic(vic)
            top = rtl / "top.sv"
            self._write_top(
                top,
                top="t120_boundary_top",
                include_name=VIC_NAME,
            )
            uppercase = rtl / "dmac_parameters_64bit.VIC"
            uppercase.write_bytes(vic.read_bytes())

            cases = (
                (
                    "rtl/dmac_parameters_64bit.VIC\nrtl/top.sv\n",
                    "SOURCESET_UNSUPPORTED_FILE",
                ),
                (
                    "rtl/dmac_parameters_64bit.vic\n"
                    "rtl/dmac_parameters_64bit.vic\nrtl/top.sv\n",
                    "SOURCESET_DUPLICATE_FILE",
                ),
                (
                    "-v rtl/dmac_parameters_64bit.vic\nrtl/top.sv\n",
                    "SOURCESET_UNSUPPORTED_FILE",
                ),
            )
            for index, (contents, expected_code) in enumerate(cases):
                filelist = root / f"case-{index}.f"
                filelist.write_text(contents, encoding="utf-8")
                with self.subTest(contents=contents):
                    with self.assertRaises(SourceSetError) as raised:
                        from_filelist(filelist=filelist, source_root=root)
                    self.assertEqual(raised.exception.code, expected_code)

            with self.assertRaises(SourceSetError) as single:
                from_single_file(source_file=vic, source_root=root)
            self.assertEqual(single.exception.code, "SOURCESET_UNSUPPORTED_FILE")

            project = root / "project"
            project.mkdir()
            project_vic = project / VIC_NAME
            self._write_vic(project_vic)
            project_top = project / "top.sv"
            self._write_top(
                project_top,
                top="t120_project_top",
                include_name=VIC_NAME,
            )
            with self.assertRaises(SourceSetError) as project_error:
                from_project_root(project_root=project, top="t120_project_top")
            self.assertEqual(project_error.exception.code, "SOURCESET_FILE_NOT_FOUND")

    def test_non_vic_include_candidate_behavior_is_unchanged(self):
        with tempfile.TemporaryDirectory(prefix="t120-non-vic-") as temporary:
            root = Path(temporary)
            project = root / "project"
            project.mkdir()
            outside = root / "outside.txt"
            outside.write_text(
                "parameter T120_SIMPLE_RR = 2'b00;\n"
                "parameter T120_WIDTH = 8;\n",
                encoding="utf-8",
            )
            (project / "outside.txt").symlink_to(outside)
            top = project / "top.sv"
            self._write_top(
                top,
                top="t120_non_vic_top",
                include_name="outside.txt",
            )
            filelist = project / "design.f"
            filelist.write_text("top.sv\n", encoding="utf-8")

            source_set = from_filelist(
                filelist=filelist,
                source_root=project,
                top="t120_non_vic_top",
            )
            self.assertEqual(source_set.included_files, ())
            self.assertEqual(source_set.compile_order, ("top.sv",))

    def test_combined_public_gate_restore_and_formal_positive_negative(self):
        with tempfile.TemporaryDirectory(prefix="t120-formal-") as temporary:
            root = Path(temporary)
            vic = root / VIC_NAME
            top = root / "top.sv"
            self._write_vic(vic)
            self._write_top(
                top,
                top="t120_top",
                include_name=VIC_NAME,
                instantiate_child=True,
            )
            input_filelist = root / "input.f"
            input_filelist.write_text(
                f"{vic.resolve()}\n-v {CHILD.resolve()}\n{top.resolve()}\n",
                encoding="utf-8",
            )
            self.assertEqual(infer_filelist_root(filelist=input_filelist), Path("/"))

            files = (
                self._root_relative(vic),
                self._root_relative(CHILD),
                self._root_relative(top),
            )
            originals = {relative: (Path("/") / relative).read_bytes() for relative in files}
            gold_filelist = root / "gold.f"
            gold_filelist.write_text(
                "".join(f"{relative}\n" for relative in files),
                encoding="utf-8",
            )

            gate = root / "gate"
            encrypted = self._run(
                PUBLIC_ENCRYPT,
                "--filelist",
                str(input_filelist),
                "--top",
                "t120_top",
                "--category",
                "all",
                "--output-dir",
                str(gate),
            )
            self.assertEqual(encrypted.returncode, 0, encrypted.stderr)
            payload = json.loads(encrypted.stdout)
            self.assertEqual(payload["schema_version"], 2)
            self.assertGreater(payload["summary"]["rename"], 0)
            self.assertGreater(payload["summary"]["modified_tokens"], 0)
            self.assertTrue(payload["summary"]["strict_compile_passed"])
            self.assertTrue(payload["summary"]["restored_byte_identical"])

            self.assertEqual(
                (gate / "design.f").read_text(encoding="utf-8"),
                "".join(f"{relative}\n" for relative in files),
            )
            self.assertEqual((gate / files[0]).read_bytes(), originals[files[0]])
            self.assertNotEqual((gate / files[1]).read_bytes(), originals[files[1]])
            self.assertNotEqual((gate / files[2]).read_bytes(), originals[files[2]])
            self.assertIn(
                f'`include "{VIC_NAME}"'.encode(),
                (gate / files[2]).read_bytes(),
            )

            mapping = json.loads((gate / "mapping.json").read_text(encoding="utf-8"))
            source_set = mapping["source_set"]
            self.assertEqual(source_set["origin"], "filelist")
            self.assertEqual(source_set["included_files"], [files[0]])
            self.assertEqual(source_set["compile_order"], list(files))
            self.assertEqual(
                mapping["mapping_execution"]["input_manifest"],
                mapping["mapping_execution"]["restored_manifest"],
            )
            self.assertEqual(
                {entry["file"] for entry in mapping["mapping_execution"]["gate_manifest"]},
                set(files),
            )
            vic_records = [
                record
                for record in mapping["mapping"]["records"]
                if record["declaration"]["file"] == files[0]
                or any(
                    occurrence["source_range"]["file"] == files[0]
                    for occurrence in record["occurrences"]
                )
            ]
            self.assertEqual(vic_records, [])

            restored = root / "restored"
            decrypted = self._run(
                PUBLIC_DECRYPT,
                "--map",
                str(gate / "mapping.json"),
                "--gate-dir",
                str(gate),
                "--output-dir",
                str(restored),
            )
            self.assertEqual(decrypted.returncode, 0, decrypted.stderr)
            for relative in files:
                self.assertEqual((restored / relative).read_bytes(), originals[relative])

            formal_arguments = (
                "--gold-filelist",
                str(gold_filelist),
                "--gold-root",
                "/",
                "--gate-filelist",
                str(gate / "design.f"),
                "--gate-root",
                str(gate),
                "--top",
                "t120_top",
                "--seq",
                "5",
            )
            positive = self._run(FORMAL, *formal_arguments)
            self.assertEqual(positive.returncode, 0, positive.stdout + positive.stderr)
            positive_json = json.loads(positive.stdout.strip().splitlines()[-1])
            self.assertEqual(positive_json["formal_equivalence"], "pass")
            self.assertEqual(positive_json["top"], "t120_top")
            self.assertEqual(positive_json["seq"], 5)
            print(
                "T120_FORMAL_POSITIVE "
                + json.dumps(
                    {
                        "gold_filelist": str(gold_filelist),
                        "gold_root": "/",
                        "gate_filelist": str(gate / "design.f"),
                        "gate_root": str(gate),
                        "top": "t120_top",
                        "seq": 5,
                        "exit": positive.returncode,
                        "json": positive_json,
                    },
                    sort_keys=True,
                )
            )

            negative = root / "negative"
            shutil.copytree(gate, negative)
            target = negative / files[1]
            original_gate = target.read_bytes()
            self.assertEqual(original_gate.count(b" ^ "), 1)
            target.write_bytes(original_gate.replace(b" ^ ", b" | ", 1))

            negative_set = from_filelist(
                filelist=negative / "design.f",
                top="t120_top",
            )
            strict = subprocess.run(
                [
                    "iverilog",
                    "-g2012",
                    "-t",
                    "null",
                    "-s",
                    "t120_top",
                    "-I",
                    str((negative / files[2]).parent),
                    *[
                        str(negative / relative)
                        for relative in negative_set.compile_order
                    ],
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
            self.assertEqual(strict.returncode, 0, strict.stdout + strict.stderr)
            failed = self._run(
                FORMAL,
                "--gold-filelist",
                str(gold_filelist),
                "--gold-root",
                "/",
                "--gate-filelist",
                str(negative / "design.f"),
                "--gate-root",
                str(negative),
                "--top",
                "t120_top",
                "--seq",
                "5",
            )
            self.assertNotEqual(failed.returncode, 0)
            evidence = (failed.stdout + failed.stderr).lower()
            self.assertIn("unproven", evidence)
            self.assertIn("equiv_status -assert", evidence)
            print(
                "T120_FORMAL_NEGATIVE "
                + json.dumps(
                    {
                        "gold_filelist": str(gold_filelist),
                        "gold_root": "/",
                        "gate_filelist": str(negative / "design.f"),
                        "gate_root": str(negative),
                        "top": "t120_top",
                        "seq": 5,
                        "strict_compile_exit": strict.returncode,
                        "formal_exit": failed.returncode,
                        "mutation": "XOR -> OR in actual gate child.v",
                        "evidence": "unproven; equiv_status -assert",
                    },
                    sort_keys=True,
                )
            )


if __name__ == "__main__":
    unittest.main()
