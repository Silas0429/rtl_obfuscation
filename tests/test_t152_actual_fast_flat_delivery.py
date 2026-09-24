"""Black-box flat delivery proof on the no-top FAST dispatch."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/t130_fast_local_signals"
ENCRYPT = ROOT / "rtl_encrypt.py"
DECRYPT = ROOT / "rtl_decrypt.py"
FORMAL = ROOT / "scripts/formal_equivalence.py"


class T152ActualFastFlatDeliveryTests(unittest.TestCase):
    def test_no_top_fast_route_publishes_compilable_flat_gate(self):
        with tempfile.TemporaryDirectory(prefix="t152-fast-flat-") as temporary:
            base = Path(temporary)
            project = base / "project"
            shutil.copytree(FIXTURE / "owned", project / "owned")
            (project / "input.f").write_text(
                "owned/leaf_a.sv\nowned/leaf_b.sv\nowned/top.sv\n"
            )
            gate = base / "gate"
            encrypted = subprocess.run(
                (
                    sys.executable, str(ENCRYPT),
                    "--filelist", str(project / "input.f"),
                    "--rewrite-root", str(project / "owned"),
                    "--category", "signals", "--output-dir", str(gate),
                ),
                cwd=ROOT, capture_output=True, text=True, timeout=180, check=False,
            )
            self.assertEqual(encrypted.returncode, 0, encrypted.stdout + encrypted.stderr)
            report = json.loads((gate / "mapping.json").read_text())
            self.assertIsNone(report["source_set"]["top"])
            self.assertTrue(report["summary"]["strict_compile_passed"])
            self.assertIn("flattened_delivery", report)
            self.assertEqual(
                (gate / "design_flattened.f").read_text().splitlines(),
                [
                    "$OUT_FLAT/leaf_a.sv",
                    "$OUT_FLAT/leaf_b.sv",
                    "$OUT_FLAT/top.sv",
                ],
            )
            for relative in report["source_set"]["ordered_source_files"]:
                self.assertEqual(
                    (gate / "src_flattened" / Path(relative).name).read_bytes(),
                    (gate / relative).read_bytes(),
                )
            log = json.loads((gate / "src_flattened_log").read_text())
            self.assertIs(log["compile_ready"], True)
            environment = os.environ.copy()
            environment["OUT"] = str(gate)
            environment["OUT_FLAT"] = str(gate / "src_flattened")
            formal = subprocess.run(
                (
                    sys.executable, str(FORMAL),
                    "--gold-filelist", str(project / "input.f"),
                    "--gold-root", str(project),
                    "--gate-filelist", str(gate / "design_flattened.f"),
                    "--gate-root", str(gate), "--top", "t130_top", "--seq", "5",
                ),
                cwd=ROOT, env=environment, capture_output=True, text=True,
                timeout=180, check=False,
            )
            self.assertEqual(formal.returncode, 0, formal.stdout + formal.stderr)
            self.assertEqual(json.loads(formal.stdout)["formal_equivalence"], "pass")
            restored = base / "restored"
            decrypted = subprocess.run(
                (
                    sys.executable, str(DECRYPT),
                    "--map", str(gate / "mapping.json"),
                    "--gate-dir", str(gate), "--output-dir", str(restored),
                ),
                cwd=ROOT, capture_output=True, text=True, timeout=180, check=False,
            )
            self.assertEqual(decrypted.returncode, 0, decrypted.stdout + decrypted.stderr)
            for relative in report["source_set"]["ordered_source_files"]:
                self.assertEqual((restored / relative).read_bytes(), (project / relative).read_bytes())
            print("T152_FAST_FLAT_FORMAL " + json.dumps(json.loads(formal.stdout), sort_keys=True))


if __name__ == "__main__":
    unittest.main()
