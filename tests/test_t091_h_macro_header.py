from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from rtl_obfuscator.source_set import SourceSetError, from_filelist, from_single_file


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "t091_h_macro_header"
PUBLIC_SCRIPTS = {
    "encrypt": ROOT / "rtl_encrypt.py",
    "decrypt": ROOT / "rtl_decrypt.py",
}


class HMacroHeaderTests(unittest.TestCase):
    @staticmethod
    def _run(script: str, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(PUBLIC_SCRIPTS[script]), *arguments],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )

    def _encrypt(self, output: Path) -> tuple[Path, dict[str, object]]:
        result = self._run(
            "encrypt",
            "--filelist",
            str(FIXTURE_ROOT / "design.f"),
            "--top",
            "t091_top",
            "--category",
            "signals",
            "--output-dir",
            str(output),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertGreater(payload["action_counts"]["rename"], 0)
        report = json.loads((output / "mapping.json").read_text(encoding="utf-8"))
        self.assertTrue(report["summary"]["strict_compile_passed"])
        self.assertTrue(report["summary"]["restored_byte_identical"])
        return output, report

    def test_filelist_h_is_context_only_and_macro_provider_is_resolved(self):
        result = from_filelist(
            filelist=FIXTURE_ROOT / "design.f",
            source_root=FIXTURE_ROOT,
            top="t091_top",
        )
        self.assertEqual(result.ordered_source_files, ("rtl/top.sv",))
        self.assertEqual(result.compile_order, ("rtl/top.sv",))
        self.assertEqual(result.included_files, ("rtl/stl_gmacro.h",))
        self.assertNotIn("rtl/stl_gmacro.h", result.compile_order)

    def test_public_signals_gate_restore_and_h_bytes(self):
        with tempfile.TemporaryDirectory(prefix="t091-public-") as temporary:
            root = Path(temporary)
            gate, report = self._encrypt(root / "gate")
            header = FIXTURE_ROOT / "rtl" / "stl_gmacro.h"
            self.assertEqual((gate / "rtl/stl_gmacro.h").read_bytes(), header.read_bytes())
            header_records = [
                record
                for record in report["mapping"]["records"]
                if record["declaration"]["file"] == "rtl/stl_gmacro.h"
                or any(
                    occurrence["source_range"]["file"] == "rtl/stl_gmacro.h"
                    for occurrence in record["occurrences"]
                )
            ]
            self.assertEqual(header_records, [])
            self.assertTrue((gate / "rtl/top.sv").is_file())
            self.assertEqual(
                (gate / "design.f").read_text(encoding="utf-8"),
                "rtl/top.sv\n",
            )

            restored = root / "restored"
            result = self._run(
                "decrypt",
                "--map",
                str(gate / "mapping.json"),
                "--gate-dir",
                str(gate),
                "--output-dir",
                str(restored),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((restored / "rtl/stl_gmacro.h").read_bytes(), header.read_bytes())
            self.assertEqual(
                (restored / "rtl/top.sv").read_bytes(),
                (FIXTURE_ROOT / "rtl/top.sv").read_bytes(),
            )

    def test_actual_gate_formal_positive_and_functional_negative(self):
        with tempfile.TemporaryDirectory(prefix="t091-formal-") as temporary:
            root = Path(temporary)
            gate, _report = self._encrypt(root / "gate")
            formal_arguments = [
                "scripts/formal_equivalence.py",
                "--gold-filelist",
                str(FIXTURE_ROOT / "design.f"),
                "--gold-root",
                str(FIXTURE_ROOT),
                "--gate-filelist",
                str(gate / "design.f"),
                "--gate-root",
                str(gate),
                "--top",
                "t091_top",
                "--seq",
                "5",
            ]
            positive = subprocess.run(
                [sys.executable, *formal_arguments],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
            self.assertEqual(positive.returncode, 0, positive.stdout + positive.stderr)
            positive_json = json.loads(positive.stdout.strip().splitlines()[-1])
            self.assertEqual(positive_json["formal_equivalence"], "pass")
            self.assertEqual(positive_json["top"], "t091_top")
            self.assertEqual(positive_json["seq"], 5)

            negative = root / "negative"
            shutil.copytree(gate, negative)
            top = negative / "rtl" / "top.sv"
            contents = top.read_bytes()
            self.assertEqual(contents.count(b" ^ "), 1)
            top.write_bytes(contents.replace(b" ^ ", b" | ", 1))
            strict = subprocess.run(
                [
                    "iverilog",
                    "-g2012",
                    "-t",
                    "null",
                    "-s",
                    "t091_top",
                    "-I",
                    str(negative / "rtl"),
                    str(negative / "rtl" / "top.sv"),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
            self.assertEqual(strict.returncode, 0, strict.stdout + strict.stderr)
            negative_arguments = list(formal_arguments)
            negative_arguments[negative_arguments.index(str(gate / "design.f"))] = str(
                negative / "design.f"
            )
            negative_arguments[negative_arguments.index(str(gate))] = str(negative)
            negative_result = subprocess.run(
                [sys.executable, *negative_arguments],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
            combined = (negative_result.stdout + negative_result.stderr).lower()
            self.assertNotEqual(negative_result.returncode, 0)
            self.assertIn("unproven", combined)
            self.assertIn("equiv_status -assert", combined)

    def test_h_filelist_boundaries_fail_closed(self):
        with tempfile.TemporaryDirectory(prefix="t091-boundaries-") as temporary:
            root = Path(temporary)
            unlisted = root / "unlisted.f"
            unlisted.write_text("rtl/top.sv\n", encoding="utf-8")
            with self.assertRaises(SourceSetError) as missing:
                from_filelist(filelist=unlisted, source_root=FIXTURE_ROOT, top="t091_top")
            self.assertEqual(missing.exception.code, "SOURCESET_FILE_NOT_FOUND")

            duplicate = root / "duplicate.f"
            duplicate.write_text(
                "rtl/stl_gmacro.h\nrtl/stl_gmacro.h\nrtl/top.sv\n",
                encoding="utf-8",
            )
            with self.assertRaises(SourceSetError) as repeated:
                from_filelist(filelist=duplicate, source_root=FIXTURE_ROOT)
            self.assertEqual(repeated.exception.code, "SOURCESET_DUPLICATE_FILE")

            upper = root / "upper.f"
            upper.write_text("rtl/stl_gmacro.H\nrtl/top.sv\n", encoding="utf-8")
            with self.assertRaises(SourceSetError) as unsupported:
                from_filelist(filelist=upper, source_root=FIXTURE_ROOT)
            self.assertEqual(unsupported.exception.code, "SOURCESET_UNSUPPORTED_FILE")

            result = self._run(
                "encrypt",
                "--input",
                "rtl/stl_gmacro.h",
                "--source-root",
                str(FIXTURE_ROOT),
                "--output-dir",
                str(root / "single-h-gate"),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((root / "single-h-gate").exists())


if __name__ == "__main__":
    unittest.main()
