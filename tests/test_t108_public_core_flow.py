from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from rtl_obfuscator.source_catalog import build_source_catalog
from rtl_obfuscator.source_set import from_filelist


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "t108_pyslang_rename_index"


class T108PublicCoreFlowTests(unittest.TestCase):
    def _run(self, script: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(script), *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )

    def test_actual_gate_formal_positive_and_fixed_functional_negative(self):
        with tempfile.TemporaryDirectory(prefix="t108-formal-") as temp:
            root = Path(temp)
            gate = root / "gate"
            encrypted = self._run(
                ROOT / "rtl_encrypt.py",
                "--filelist", str(FIXTURE / "formal.f"),
                "--top", "formal_top",
                "--category", "all",
                "--output-dir", str(gate),
            )
            self.assertEqual(encrypted.returncode, 0, encrypted.stderr)
            formal_arguments = (
                "--gold-filelist", str(FIXTURE / "formal.f"),
                "--gold-root", str(FIXTURE),
                "--gate-filelist", str(gate / "design.f"),
                "--gate-root", str(gate),
                "--top", "formal_top",
                "--seq", "5",
            )
            positive = self._run(ROOT / "scripts" / "formal_equivalence.py", *formal_arguments)
            self.assertEqual(positive.returncode, 0, positive.stdout + positive.stderr)
            positive_json = json.loads(positive.stdout.strip().splitlines()[-1])
            self.assertEqual(positive_json["formal_equivalence"], "pass")
            print(
                "T108_FORMAL_POSITIVE "
                + json.dumps(
                    {"gold": str(FIXTURE), "gate": str(gate), "top": "formal_top", "exit": positive.returncode, "json": positive_json},
                    sort_keys=True,
                )
            )

            negative = root / "negative"
            shutil.copytree(gate, negative)
            target = negative / "formal.sv"
            original = target.read_bytes()
            mutated = original.replace(b" <= in_a;", b" <= ~in_a;")
            self.assertNotEqual(mutated, original)
            target.write_bytes(mutated)
            negative_set = from_filelist(
                filelist=negative / "design.f", top="formal_top"
            )
            compile = build_source_catalog(negative_set).to_report()["compile"]
            self.assertEqual(
                compile,
                {
                    "catalog": {"parse_errors": 0, "semantic_errors": 0},
                    "top_overlay": {"parse_errors": 0, "semantic_errors": 0},
                },
            )
            negative_result = self._run(
                ROOT / "scripts" / "formal_equivalence.py",
                "--gold-filelist", str(FIXTURE / "formal.f"),
                "--gold-root", str(FIXTURE),
                "--gate-filelist", str(negative / "design.f"),
                "--gate-root", str(negative),
                "--top", "formal_top",
                "--seq", "5",
            )
            combined = (negative_result.stdout + negative_result.stderr).lower()
            self.assertNotEqual(negative_result.returncode, 0)
            self.assertIn("unproven", combined)
            self.assertIn("equiv_status -assert", combined)
            print(
                "T108_FORMAL_NEGATIVE "
                + json.dumps(
                    {"gold": str(FIXTURE), "gate": str(negative), "top": "formal_top", "exit": negative_result.returncode, "evidence": "unproven; equiv_status -assert"},
                    sort_keys=True,
                )
            )

    def test_macro_backed_interface_locations_complete_schema_two_flow(self):
        with tempfile.TemporaryDirectory(prefix="t108-macro-interface-") as temp:
            root = Path(temp)
            gate = root / "gate"
            encrypted = self._run(
                ROOT / "rtl_encrypt.py",
                "--filelist", str(FIXTURE / "macro_interface.f"),
                "--top", "macro_interface_top",
                "--category", "interface",
                "--output-dir", str(gate),
            )
            self.assertEqual(encrypted.returncode, 0, encrypted.stderr)
            payload = json.loads(encrypted.stdout)
            self.assertEqual(payload["schema_version"], 2)
            report = json.loads((gate / "mapping.json").read_text(encoding="utf-8"))
            self.assertEqual(report["mapping"]["schema_version"], 2)
            outcome = next(
                item
                for item in report["mapping"]["category_outcomes"]
                if item["category"] == "interface"
            )
            self.assertEqual(outcome["status"], "preserved")
            self.assertGreater(outcome["rename"], 0)
            self.assertEqual(outcome["preserve"], 2)
            self.assertFalse(
                any(issue["message"] == "source_binding_incomplete" for issue in outcome["issues"])
            )
            actions = {
                item["original_name"]: item["action"]
                for item in report["mapping"]["records"]
                if item["category"] == "interface"
            }
            self.assertEqual(actions["macro_if"], "rename")
            self.assertEqual(actions["value"], "rename")
            self.assertEqual(actions["macro_mp"], "rename")
            self.assertEqual(actions["if0"], "preserve")
            self.assertEqual(actions["if_array"], "preserve")
            restored = root / "restored"
            decrypted = self._run(
                ROOT / "rtl_decrypt.py",
                "--map", str(gate / "mapping.json"),
                "--gate-dir", str(gate),
                "--output-dir", str(restored),
            )
            self.assertEqual(decrypted.returncode, 0, decrypted.stderr)
            self.assertEqual(json.loads(decrypted.stdout)["schema_version"], 2)
            for file in ("macro_interface.svh", "macro_interface.sv"):
                self.assertEqual(
                    (restored / file).read_bytes(),
                    (FIXTURE / file).read_bytes(),
                )
