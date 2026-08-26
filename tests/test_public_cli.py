from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "t108_pyslang_rename_index"
ENCRYPT = ROOT / "rtl_encrypt.py"
DECRYPT = ROOT / "rtl_decrypt.py"


class PublicCliTests(unittest.TestCase):
    def _run(self, script: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(script), *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )

    def test_category_is_required_and_old_categories_are_rejected(self):
        with tempfile.TemporaryDirectory(prefix="t108-cli-input-") as temp:
            root = Path(temp)
            missing = self._run(
                ENCRYPT,
                "--filelist", str(FIXTURE / "design.f"),
                "--top", "top",
                "--output-dir", str(root / "missing"),
            )
            self.assertNotEqual(missing.returncode, 0)
            self.assertIn("CLI_VNEXT_CATEGORY_REQUIRED", missing.stderr)
            invalid = self._run(
                ENCRYPT,
                "--filelist", str(FIXTURE / "design.f"),
                "--top", "top",
                "--category", "parameters",
                "--output-dir", str(root / "invalid"),
            )
            self.assertNotEqual(invalid.returncode, 0)
            self.assertIn("CLI_VNEXT_CATEGORY_INVALID", invalid.stderr)
            self.assertIn("signals,ports,interface,struct,all", invalid.stderr)

    def test_filelist_rejects_source_root_and_public_restore_is_portable(self):
        with tempfile.TemporaryDirectory(prefix="t108-cli-flow-") as temp:
            root = Path(temp)
            conflict = self._run(
                ENCRYPT,
                "--filelist", str(FIXTURE / "design.f"),
                "--source-root", str(FIXTURE),
                "--category", "signals",
                "--output-dir", str(root / "conflict"),
            )
            self.assertNotEqual(conflict.returncode, 0)
            self.assertIn("CLI_VNEXT_INPUT_MODE_CONFLICT", conflict.stderr)
            gate = root / "gate"
            encrypted = self._run(
                ENCRYPT,
                "--filelist", str(FIXTURE / "design.f"),
                "--top", "top",
                "--category", "all",
                "--output-dir", str(gate),
            )
            self.assertEqual(encrypted.returncode, 0, encrypted.stderr)
            self.assertEqual(json.loads(encrypted.stdout)["schema_version"], 2)
            report = json.loads((gate / "mapping.json").read_text(encoding="utf-8"))
            self.assertEqual(report["mapping"]["format"], "rtl-obfuscation.mapping")
            self.assertEqual(report["mapping"]["schema_version"], 2)
            restored = root / "restored"
            decrypted = self._run(
                DECRYPT,
                "--map", str(gate / "mapping.json"),
                "--gate-dir", str(gate),
                "--output-dir", str(restored),
            )
            self.assertEqual(decrypted.returncode, 0, decrypted.stderr)
            self.assertEqual(json.loads(decrypted.stdout)["schema_version"], 2)
            for file in ("macros.svh", "bus_if.sv", "design.sv"):
                self.assertEqual(
                    (restored / file).read_bytes(),
                    (FIXTURE / file).read_bytes(),
                )
