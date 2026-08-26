from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "t108_pyslang_rename_index"


class CliVNextEncryptionTests(unittest.TestCase):
    def test_public_cli_publishes_schema_two_gate_and_restore(self):
        with tempfile.TemporaryDirectory(prefix="t108-cli-vnext-") as temp:
            root = Path(temp)
            gate = root / "gate"
            encrypted = subprocess.run(
                [
                    sys.executable, "rtl_encrypt.py", "--filelist", str(FIXTURE / "design.f"),
                    "--top", "top", "--category", "all", "--output-dir", str(gate),
                ], cwd=ROOT, capture_output=True, text=True, check=False,
            )
            self.assertEqual(encrypted.returncode, 0, encrypted.stderr)
            self.assertEqual(json.loads(encrypted.stdout)["schema_version"], 2)
            report = json.loads((gate / "mapping.json").read_text())
            self.assertEqual(report["mapping"]["schema_version"], 2)
            restored = root / "restored"
            decrypted = subprocess.run(
                [
                    sys.executable, "rtl_decrypt.py", "--map", str(gate / "mapping.json"),
                    "--gate-dir", str(gate), "--output-dir", str(restored),
                ], cwd=ROOT, capture_output=True, text=True, check=False,
            )
            self.assertEqual(decrypted.returncode, 0, decrypted.stderr)
            self.assertEqual(json.loads(decrypted.stdout)["schema_version"], 2)


if __name__ == "__main__":
    unittest.main()
