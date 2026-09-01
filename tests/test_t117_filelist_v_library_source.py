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

from rtl_obfuscator.source_set import SourceSetError, from_filelist


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "t117_filelist_v_library_source"
PUBLIC_ENCRYPT = ROOT / "rtl_encrypt.py"
PUBLIC_DECRYPT = ROOT / "rtl_decrypt.py"
FORMAL = ROOT / "scripts" / "formal_equivalence.py"
ORDER = ("rtl/library_cell.v", "rtl/top.sv")


class T117FilelistVLibrarySourceTests(unittest.TestCase):
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

    def test_v_matches_bare_order_and_reuses_all_path_rules(self):
        bare = from_filelist(filelist=FIXTURE / "bare.f", source_root=FIXTURE)
        relative = from_filelist(filelist=FIXTURE / "design.f", source_root=FIXTURE)
        self.assertEqual(relative.ordered_source_files, ORDER)
        self.assertEqual(relative.compile_order, ORDER)
        self.assertEqual(relative.to_report(), bare.to_report())
        self.assertEqual(
            [(entry.kind, entry.value, entry.line) for entry in relative.filelist_entries],
            [
                ("library_source", "rtl/library_cell.v", 1),
                ("source", "rtl/top.sv", 2),
            ],
        )

        with tempfile.TemporaryDirectory(prefix="t117-paths-") as temporary:
            root = Path(temporary)
            absolute_filelist = root / "absolute.f"
            absolute_filelist.write_text(
                f"-v {FIXTURE / ORDER[0]}\n{FIXTURE / ORDER[1]}\n",
                encoding="utf-8",
            )
            variable_filelist = root / "variable.f"
            variable_filelist.write_text(
                "-v $T117_ROOT/rtl/library_cell.v\n"
                "$T117_ROOT/rtl/top.sv\n",
                encoding="utf-8",
            )
            outer_filelist = root / "outer.f"
            outer_filelist.write_text(
                f"-f {FIXTURE / 'design.f'}\n", encoding="utf-8"
            )

            absolute = from_filelist(
                filelist=absolute_filelist, source_root=FIXTURE
            )
            with mock.patch.dict(
                os.environ, {"T117_ROOT": str(FIXTURE)}, clear=False
            ):
                variable = from_filelist(
                    filelist=variable_filelist, source_root=FIXTURE
                )
            nested = from_filelist(filelist=outer_filelist, source_root=FIXTURE)

        for source_set in (absolute, variable, nested):
            self.assertEqual(source_set.ordered_source_files, ORDER)
            self.assertEqual(source_set.compile_order, ORDER)

    def test_v_failures_are_exact_and_duplicate_with_bare_entry(self):
        cases = (
            ("-v\n", "SOURCESET_INVALID_ARGUMENT"),
            (
                "-v rtl/library_cell.v rtl/top.sv\n",
                "SOURCESET_UNSUPPORTED_FILELIST_DIRECTIVE",
            ),
            (
                "-vrtl/library_cell.v\n",
                "SOURCESET_UNSUPPORTED_FILELIST_DIRECTIVE",
            ),
            ("-y rtl\n", "SOURCESET_UNSUPPORTED_FILELIST_DIRECTIVE"),
            (
                "-v rtl/library_cell.v\nrtl/library_cell.v\n",
                "SOURCESET_DUPLICATE_FILE",
            ),
            ("-v rtl/not_source.svh\n", "SOURCESET_UNSUPPORTED_FILE"),
        )
        with tempfile.TemporaryDirectory(prefix="t117-errors-") as temporary:
            root = Path(temporary)
            shutil.copytree(FIXTURE / "rtl", root / "rtl")
            (root / "rtl" / "not_source.svh").write_text(
                "`define T117_UNUSED 1\n", encoding="utf-8"
            )
            for index, (contents, expected_code) in enumerate(cases):
                filelist = root / f"case_{index}.f"
                filelist.write_text(contents, encoding="utf-8")
                with self.subTest(contents=contents):
                    with self.assertRaises(SourceSetError) as raised:
                        from_filelist(filelist=filelist, source_root=root)
                    self.assertEqual(raised.exception.code, expected_code)

            missing = root / "missing.f"
            missing.write_text("-v rtl/missing.v\n", encoding="utf-8")
            with self.assertRaises(SourceSetError) as raised:
                from_filelist(filelist=missing, source_root=root)
            self.assertEqual(raised.exception.code, "SOURCESET_FILE_NOT_FOUND")
            self.assertEqual(raised.exception.path, "rtl/missing.v")

    def test_cli_missing_v_source_reports_filelist_line(self):
        with tempfile.TemporaryDirectory(prefix="t117-cli-error-") as temporary:
            root = Path(temporary)
            filelist = root / "missing.f"
            output = root / "gate"
            filelist.write_text("// first line\n-v rtl/missing.v\n", encoding="utf-8")
            result = self._run(
                PUBLIC_ENCRYPT,
                "--filelist",
                str(filelist),
                "--category",
                "all",
                "--output-dir",
                str(output),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")
            self.assertIn("detail: SOURCESET_FILE_NOT_FOUND", result.stderr)
            self.assertIn(f"filelist: {filelist.resolve()}:2", result.stderr)
            self.assertFalse(output.exists())

    def test_actual_gate_restore_and_formal_positive_negative(self):
        with tempfile.TemporaryDirectory(prefix="t117-formal-") as temporary:
            root = Path(temporary)
            gate = root / "gate"
            encrypted = self._run(
                PUBLIC_ENCRYPT,
                "--filelist",
                str(FIXTURE / "design.f"),
                "--top",
                "t117_top",
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
                "rtl/library_cell.v\nrtl/top.sv\n",
            )
            self.assertTrue(
                any(
                    (gate / relative).read_bytes() != (FIXTURE / relative).read_bytes()
                    for relative in ORDER
                )
            )

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
            for relative in ORDER:
                self.assertEqual(
                    (restored / relative).read_bytes(),
                    (FIXTURE / relative).read_bytes(),
                )

            formal_arguments = (
                "--gold-filelist",
                str(FIXTURE / "bare.f"),
                "--gold-root",
                str(FIXTURE),
                "--gate-filelist",
                str(gate / "design.f"),
                "--gate-root",
                str(gate),
                "--top",
                "t117_top",
                "--seq",
                "5",
            )
            positive = self._run(FORMAL, *formal_arguments)
            self.assertEqual(positive.returncode, 0, positive.stdout + positive.stderr)
            positive_json = json.loads(positive.stdout.strip().splitlines()[-1])
            self.assertEqual(positive_json["formal_equivalence"], "pass")
            self.assertEqual(positive_json["top"], "t117_top")
            print(
                "T117_FORMAL_POSITIVE "
                + json.dumps(
                    {
                        "gold": str(FIXTURE),
                        "gate": str(gate),
                        "top": "t117_top",
                        "exit": positive.returncode,
                        "json": positive_json,
                    },
                    sort_keys=True,
                )
            )

            negative = root / "negative"
            shutil.copytree(gate, negative)
            target = negative / "rtl" / "library_cell.v"
            original = target.read_bytes()
            self.assertEqual(original.count(b"1'b0"), 1)
            mutated = original.replace(b"1'b0", b"1'b1")
            self.assertNotEqual(mutated, original)
            target.write_bytes(mutated)

            negative_source_set = from_filelist(
                filelist=negative / "design.f", top="t117_top"
            )
            strict = subprocess.run(
                [
                    "iverilog",
                    "-g2012",
                    "-t",
                    "null",
                    "-s",
                    "t117_top",
                    *[
                        str(negative / relative)
                        for relative in negative_source_set.compile_order
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
                str(FIXTURE / "bare.f"),
                "--gold-root",
                str(FIXTURE),
                "--gate-filelist",
                str(negative / "design.f"),
                "--gate-root",
                str(negative),
                "--top",
                "t117_top",
                "--seq",
                "5",
            )
            self.assertNotEqual(negative_result.returncode, 0)
            combined = (negative_result.stdout + negative_result.stderr).lower()
            self.assertIn("unproven", combined)
            self.assertIn("equiv_status -assert", combined)
            print(
                "T117_FORMAL_NEGATIVE "
                + json.dumps(
                    {
                        "gold": str(FIXTURE),
                        "gate": str(negative),
                        "top": "t117_top",
                        "strict_compile_exit": strict.returncode,
                        "exit": negative_result.returncode,
                        "mutation": "1'b0 -> 1'b1 in actual gate library_cell.v",
                        "evidence": "unproven; equiv_status -assert",
                    },
                    sort_keys=True,
                )
            )


if __name__ == "__main__":
    unittest.main()
