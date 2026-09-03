from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "t133_fast_direct_variables"
ENCRYPT = ROOT / "rtl_encrypt.py"
DECRYPT = ROOT / "rtl_decrypt.py"
FORMAL = ROOT / "scripts" / "formal_equivalence.py"


class T133FastDirectVariablesTests(unittest.TestCase):
    @staticmethod
    def _run_cli(output: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(ENCRYPT),
                "--filelist",
                str(FIXTURE / "design.f"),
                "--rewrite-root",
                str(FIXTURE / "owned"),
                "--category",
                "signals",
                "--output-dir",
                str(output),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )

    def test_public_direct_variables_roundtrip_and_boundaries(self):
        originals = {
            path.relative_to(FIXTURE).as_posix(): path.read_bytes()
            for path in FIXTURE.rglob("*")
            if path.is_file()
        }
        with tempfile.TemporaryDirectory(prefix="t133-public-") as temporary:
            base = Path(temporary)
            gate = base / "gate"
            result = self._run_cli(gate)
            self.assertEqual(result.returncode, 0, result.stderr)
            cli_report = json.loads(result.stdout.strip().splitlines()[-1])
            report = json.loads((gate / "mapping.json").read_text())
            self.assertEqual(cli_report["format"], "rtl-obfuscation.cli-vnext")
            self.assertEqual(cli_report["schema_version"], 2)
            self.assertTrue(report["summary"]["strict_compile_passed"])
            self.assertTrue(report["summary"]["restored_byte_identical"])

            records = {
                record["original_name"]: record
                for record in report["mapping"]["records"]
            }
            self.assertEqual(
                set(records),
                {
                    "packed_signal",
                    "array_signal",
                    "typed_signal",
                    "aggregate_signal",
                    "same_label",
                    "macro_signal",
                    "formal_typed_signal",
                    "formal_selected_signal",
                },
            )
            for name in {
                "packed_signal",
                "array_signal",
                "typed_signal",
                "aggregate_signal",
                "formal_typed_signal",
                "formal_selected_signal",
            }:
                self.assertEqual(records[name]["action"], "rename", records[name])
                self.assertIsNone(records[name]["reason"])
            for name in {"same_label", "macro_signal"}:
                self.assertEqual(records[name]["action"], "preserve", records[name])
                self.assertEqual(records[name]["reason"], "syntax_local_ambiguous")

            self.assertFalse(
                {"generated_local", "function_local"} & set(records),
                records,
            )
            gate_source = "\n".join(
                (gate / "owned" / relative).read_text()
                for relative in ("design.sv", "formal.sv")
            )
            for name in {
                "packed_signal",
                "array_signal",
                "typed_signal",
                "aggregate_signal",
                "formal_typed_signal",
                "formal_selected_signal",
            }:
                self.assertIsNone(re.search(rf"\b{re.escape(name)}\b", gate_source))
            for unchanged in {
                "low",
                "high",
                "same_label",
                "macro_signal",
                "generated_local",
                "function_local",
            }:
                self.assertRegex(gate_source, rf"\b{re.escape(unchanged)}\b")
            self.assertEqual(
                (gate / "external" / "word_type.sv").read_bytes(),
                originals["external/word_type.sv"],
            )
            self.assertEqual(
                (gate / "external" / "pair_type.sv").read_bytes(),
                originals["external/pair_type.sv"],
            )

            restored = base / "restored"
            decrypted = subprocess.run(
                [
                    sys.executable,
                    str(DECRYPT),
                    "--map",
                    str(gate / "mapping.json"),
                    "--gate-dir",
                    str(gate),
                    "--output-dir",
                    str(restored),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
            self.assertEqual(decrypted.returncode, 0, decrypted.stderr)
            for relative, data in originals.items():
                if Path(relative).suffix in {".sv", ".v"}:
                    self.assertEqual((restored / relative).read_bytes(), data, relative)

    def test_actual_gate_formal_positive_and_fixed_negative(self):
        with tempfile.TemporaryDirectory(prefix="t133-formal-") as temporary:
            base = Path(temporary)
            gate = base / "gate"
            result = self._run_cli(gate)
            self.assertEqual(result.returncode, 0, result.stderr)
            (gate / "formal.f").write_bytes((FIXTURE / "formal.f").read_bytes())
            arguments = [
                "--gold-filelist",
                str(FIXTURE / "formal.f"),
                "--gold-root",
                str(FIXTURE),
                "--gate-filelist",
                str(gate / "formal.f"),
                "--gate-root",
                str(gate),
                "--top",
                "t133_fast_direct_variables_formal",
                "--seq",
                "5",
            ]
            positive = subprocess.run(
                [sys.executable, str(FORMAL), *arguments],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
            self.assertEqual(positive.returncode, 0, positive.stdout + positive.stderr)
            self.assertEqual(
                json.loads(positive.stdout.strip().splitlines()[-1])[
                    "formal_equivalence"
                ],
                "pass",
            )

            negative = base / "negative"
            shutil.copytree(gate, negative)
            target = negative / "owned" / "formal.sv"
            original = target.read_bytes()
            self.assertEqual(original.count(b" ^ 8'h3"), 1)
            target.write_bytes(original.replace(b" ^ 8'h3", b" | 8'h3", 1))
            failed = subprocess.run(
                [
                    sys.executable,
                    str(FORMAL),
                    *[
                        argument.replace(str(gate), str(negative))
                        for argument in arguments
                    ],
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
            combined = (failed.stdout + failed.stderr).lower()
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("unproven", combined)
            self.assertIn("equiv_status -assert", combined)


if __name__ == "__main__":
    unittest.main()
