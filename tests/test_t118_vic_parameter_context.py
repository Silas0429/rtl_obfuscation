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
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "t118_vic_parameter_context"
PUBLIC_ENCRYPT = ROOT / "rtl_encrypt.py"
PUBLIC_DECRYPT = ROOT / "rtl_decrypt.py"
FORMAL = ROOT / "scripts" / "formal_equivalence.py"
VIC = "rtl/dmac_parameters_64bit.vic"
TOP = "rtl/top.sv"


class T118VicParameterContextTests(unittest.TestCase):
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

    def _source_set(self, filelist: Path = FIXTURE / "design.f"):
        return from_filelist(
            filelist=filelist,
            source_root=FIXTURE,
            top="t118_top",
        )

    def test_explicit_vic_is_parameter_context_prelude(self):
        source_set = self._source_set()
        self.assertEqual(source_set.ordered_source_files, (TOP,))
        self.assertEqual(source_set.included_files, (VIC,))
        self.assertEqual(source_set.compile_order, (VIC, TOP))
        self.assertEqual(source_set.top_closure_files, ())

        with tempfile.TemporaryDirectory(prefix="t118-order-") as temporary:
            reverse = Path(temporary) / "reverse.f"
            reverse.write_text(f"{TOP}\n{VIC}\n", encoding="utf-8")
            reordered = self._source_set(reverse)
        self.assertEqual(reordered.compile_order, (VIC, TOP))

    def test_vic_reuses_filelist_path_rules(self):
        with tempfile.TemporaryDirectory(prefix="t118-paths-") as temporary:
            root = Path(temporary)
            absolute = root / "absolute.f"
            absolute.write_text(
                f"{FIXTURE / VIC}\n{FIXTURE / TOP}\n", encoding="utf-8"
            )
            plain_variable = root / "plain-variable.f"
            plain_variable.write_text(
                "$T118_ROOT/rtl/dmac_parameters_64bit.vic\n"
                "$T118_ROOT/rtl/top.sv\n",
                encoding="utf-8",
            )
            braced_variable = root / "braced-variable.f"
            braced_variable.write_text(
                "${T118_ROOT}/rtl/dmac_parameters_64bit.vic\n"
                "${T118_ROOT}/rtl/top.sv\n",
                encoding="utf-8",
            )
            nested = root / "nested.f"
            nested.write_text(f"-f {FIXTURE / 'design.f'}\n", encoding="utf-8")

            source_sets = [
                from_filelist(filelist=absolute, source_root=FIXTURE, top="t118_top"),
                from_filelist(filelist=nested, source_root=FIXTURE, top="t118_top"),
            ]
            with mock.patch.dict(
                os.environ, {"T118_ROOT": str(FIXTURE)}, clear=False
            ):
                source_sets.extend(
                    [
                        from_filelist(
                            filelist=plain_variable,
                            source_root=FIXTURE,
                            top="t118_top",
                        ),
                        from_filelist(
                            filelist=braced_variable,
                            source_root=FIXTURE,
                            top="t118_top",
                        ),
                    ]
                )

        for source_set in source_sets:
            self.assertEqual(source_set.ordered_source_files, (TOP,))
            self.assertEqual(source_set.included_files, (VIC,))
            self.assertEqual(source_set.compile_order, (VIC, TOP))

    def test_vic_boundaries_fail_closed(self):
        with tempfile.TemporaryDirectory(prefix="t118-boundaries-") as temporary:
            root = Path(temporary)
            shutil.copytree(FIXTURE / "rtl", root / "rtl")

            cases = (
                (
                    "rtl/dmac_parameters_64bit.VIC\nrtl/top.sv\n",
                    "SOURCESET_UNSUPPORTED_FILE",
                ),
                (
                    f"{VIC}\n{VIC}\n{TOP}\n",
                    "SOURCESET_DUPLICATE_FILE",
                ),
                (
                    f"-v {VIC}\n{TOP}\n",
                    "SOURCESET_UNSUPPORTED_FILE",
                ),
                ("rtl/missing.vic\nrtl/top.sv\n", "SOURCESET_FILE_NOT_FOUND"),
            )
            (root / "rtl" / "dmac_parameters_64bit.VIC").write_bytes(
                (FIXTURE / VIC).read_bytes()
            )
            for index, (contents, expected_code) in enumerate(cases):
                filelist = root / f"case-{index}.f"
                filelist.write_text(contents, encoding="utf-8")
                with self.subTest(contents=contents):
                    with self.assertRaises(SourceSetError) as raised:
                        from_filelist(filelist=filelist, source_root=root)
                    self.assertEqual(raised.exception.code, expected_code)

            with self.assertRaises(SourceSetError) as single:
                from_single_file(
                    source_file=FIXTURE / VIC,
                    source_root=FIXTURE,
                )
            self.assertEqual(single.exception.code, "SOURCESET_UNSUPPORTED_FILE")

            project = root / "project"
            project.mkdir()
            (project / "standalone.sv").write_text(
                "module standalone; endmodule\n", encoding="utf-8"
            )
            (project / "ignored.vic").write_text(
                "parameter IGNORED = 1;\n", encoding="utf-8"
            )
            project_set = from_project_root(project_root=project, top="standalone")
            self.assertNotIn("ignored.vic", project_set.included_files)
            self.assertNotIn("ignored.vic", project_set.compile_order)

            include_filelist = root / "include-only.f"
            (root / "rtl" / "include_only.sv").write_text(
                '`include "dmac_parameters_64bit.vic"\n'
                "module include_only(output logic [DATA_BITS-1:0] y); "
                "assign y = '0; endmodule\n",
                encoding="utf-8",
            )
            include_filelist.write_text("rtl/include_only.sv\n", encoding="utf-8")
            with self.assertRaises(SourceSetError) as implicit_filelist_context:
                from_filelist(
                    filelist=include_filelist,
                    source_root=root,
                    top="include_only",
                )
            self.assertEqual(
                implicit_filelist_context.exception.code,
                "SOURCESET_UNSUPPORTED_FILE",
            )

            project_include = root / "project-include"
            project_include.mkdir()
            (project_include / "params.vic").write_text(
                "parameter WIDTH = 2;\n", encoding="utf-8"
            )
            (project_include / "top.sv").write_text(
                '`include "params.vic"\n'
                "module project_include(output logic [WIDTH-1:0] y); "
                "assign y = '0; endmodule\n",
                encoding="utf-8",
            )
            with self.assertRaises(SourceSetError) as implicit_project_context:
                from_project_root(
                    project_root=project_include,
                    top="project_include",
                )
            self.assertEqual(
                implicit_project_context.exception.code,
                "SOURCESET_FILE_NOT_FOUND",
            )

    def test_actual_gate_restore_and_formal_positive_negative(self):
        with tempfile.TemporaryDirectory(prefix="t118-formal-") as temporary:
            root = Path(temporary)
            gate = root / "gate"
            encrypted = self._run(
                PUBLIC_ENCRYPT,
                "--filelist",
                str(FIXTURE / "design.f"),
                "--top",
                "t118_top",
                "--category",
                "all",
                "--output-dir",
                str(gate),
            )
            self.assertEqual(encrypted.returncode, 0, encrypted.stderr)
            payload = json.loads(encrypted.stdout)
            self.assertTrue(payload["summary"]["strict_compile_passed"])
            self.assertTrue(payload["summary"]["restored_byte_identical"])
            self.assertGreater(payload["summary"]["rename"], 0)
            self.assertGreater(payload["summary"]["modified_tokens"], 0)
            self.assertEqual(
                (gate / "design.f").read_text(encoding="utf-8"),
                f"{VIC}\n{TOP}\n",
            )
            self.assertEqual((gate / VIC).read_bytes(), (FIXTURE / VIC).read_bytes())
            self.assertNotEqual((gate / TOP).read_bytes(), (FIXTURE / TOP).read_bytes())

            mapping = json.loads((gate / "mapping.json").read_text(encoding="utf-8"))
            vic_records = [
                record
                for record in mapping["mapping"]["records"]
                if record["declaration"]["file"] == VIC
                or any(
                    occurrence["source_range"]["file"] == VIC
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
            for relative in (VIC, TOP):
                self.assertEqual(
                    (restored / relative).read_bytes(),
                    (FIXTURE / relative).read_bytes(),
                )

            formal_arguments = (
                "--gold-filelist",
                str(FIXTURE / "design.f"),
                "--gold-root",
                str(FIXTURE),
                "--gate-filelist",
                str(gate / "design.f"),
                "--gate-root",
                str(gate),
                "--top",
                "t118_top",
                "--seq",
                "5",
            )
            positive = self._run(FORMAL, *formal_arguments)
            self.assertEqual(positive.returncode, 0, positive.stdout + positive.stderr)
            positive_json = json.loads(positive.stdout.strip().splitlines()[-1])
            self.assertEqual(positive_json["formal_equivalence"], "pass")
            self.assertEqual(positive_json["top"], "t118_top")
            self.assertEqual(positive_json["seq"], 5)
            print(
                "T118_FORMAL_POSITIVE "
                + json.dumps(
                    {
                        "gold_filelist": str(FIXTURE / "design.f"),
                        "gold_root": str(FIXTURE),
                        "gate_filelist": str(gate / "design.f"),
                        "gate_root": str(gate),
                        "top": "t118_top",
                        "seq": 5,
                        "exit": positive.returncode,
                        "json": positive_json,
                    },
                    sort_keys=True,
                )
            )

            negative = root / "negative"
            shutil.copytree(gate, negative)
            target = negative / TOP
            original = target.read_bytes()
            self.assertEqual(original.count(b" ^ "), 1)
            target.write_bytes(original.replace(b" ^ ", b" | ", 1))

            negative_set = from_filelist(
                filelist=negative / "design.f", top="t118_top"
            )
            strict = subprocess.run(
                [
                    "iverilog",
                    "-g2012",
                    "-t",
                    "null",
                    "-s",
                    "t118_top",
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
            negative_result = self._run(
                FORMAL,
                "--gold-filelist",
                str(FIXTURE / "design.f"),
                "--gold-root",
                str(FIXTURE),
                "--gate-filelist",
                str(negative / "design.f"),
                "--gate-root",
                str(negative),
                "--top",
                "t118_top",
                "--seq",
                "5",
            )
            combined = (negative_result.stdout + negative_result.stderr).lower()
            self.assertNotEqual(negative_result.returncode, 0)
            self.assertIn("unproven", combined)
            self.assertIn("equiv_status -assert", combined)
            print(
                "T118_FORMAL_NEGATIVE "
                + json.dumps(
                    {
                        "gold_filelist": str(FIXTURE / "design.f"),
                        "gold_root": str(FIXTURE),
                        "gate_filelist": str(negative / "design.f"),
                        "gate_root": str(negative),
                        "top": "t118_top",
                        "seq": 5,
                        "strict_compile_exit": strict.returncode,
                        "exit": negative_result.returncode,
                        "mutation": "xor to or in actual gate top.sv",
                        "evidence": "unproven; equiv_status -assert",
                    },
                    sort_keys=True,
                )
            )


if __name__ == "__main__":
    unittest.main()
