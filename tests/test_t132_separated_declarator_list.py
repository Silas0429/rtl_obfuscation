from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "t132_separated_declarator_list"
ENCRYPT = ROOT / "rtl_encrypt.py"
DECRYPT = ROOT / "rtl_decrypt.py"
FORMAL = ROOT / "scripts" / "formal_equivalence.py"


class T132SeparatedDeclaratorListTests(unittest.TestCase):
    @staticmethod
    def _run_cli(output: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(ENCRYPT),
                "--filelist",
                str(FIXTURE / "design.f"),
                "--rewrite-root",
                str(FIXTURE),
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

    def test_public_multideclarator_roundtrip(self):
        original = (FIXTURE / "design.sv").read_bytes()
        with tempfile.TemporaryDirectory(prefix="t132-public-") as temporary:
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
            records = report["mapping"]["records"]
            self.assertEqual(
                {record["original_name"] for record in records},
                {"first", "second", "third", "fourth", "fifth", "folded"},
            )
            self.assertEqual(len(records), 6)
            self.assertTrue(all(record["action"] == "rename" for record in records))

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
            self.assertEqual((restored / "design.sv").read_bytes(), original)

    def test_actual_gate_formal_positive_and_fixed_negative(self):
        with tempfile.TemporaryDirectory(prefix="t132-formal-") as temporary:
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
                "t132_multi_declarators",
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
            target = negative / "design.sv"
            original = target.read_bytes()
            self.assertEqual(original.count(b" ^ 4'h3"), 1)
            target.write_bytes(original.replace(b" ^ 4'h3", b" | 4'h3", 1))
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
