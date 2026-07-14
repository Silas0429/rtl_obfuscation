"""Black-box tests for T018 interface instance/member/modport renaming."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


class InterfaceMemberRewriteCliTest(unittest.TestCase):
    def test_interface_member_encrypt_decrypt_round_trip(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        filelist = Path("tests/fixtures/t018_interface_member/design.f")
        source_root = Path("tests/fixtures/t018_interface_member")

        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            gate_dir = tmp_path / "gate"
            restored_dir = tmp_path / "restored"
            mapping_file = tmp_path / "mapping.json"
            metrics_file = tmp_path / "metrics.json"

            encrypt = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "rtl_obfuscator.rewrite",
                    "encrypt-project",
                    "--filelist",
                    str(filelist),
                    "--source-root",
                    str(source_root),
                    "--output-dir",
                    str(gate_dir),
                    "--map",
                    str(mapping_file),
                    "--metrics",
                    str(metrics_file),
                    "--top",
                    "t018_top",
                    "--category",
                    "interface_instances",
                    "--category",
                    "interface_ports",
                    "--category",
                    "modports",
                    "--name-length",
                    "8",
                ],
                cwd=repository,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(encrypt.returncode, 0, encrypt.stderr)
            self.assertEqual(
                json.loads(encrypt.stdout),
                {"files": 3, "mapping_entries": 8, "modified_tokens": 23},
            )

            mapping = json.loads(mapping_file.read_text(encoding="utf-8"))
            self.assertEqual(mapping["version"], 2)
            self.assertEqual(mapping["files"], ["bus_if.sv", "child.sv", "top.sv"])
            self.assertEqual(mapping["top"], "t018_top")
            entries = mapping["entries"]
            expected = [
                ("interface_ports", "clk", "bus_if.sv", 41, 44,
                 [("top.sv", 167, 170)]),
                ("interface_ports", "rst_n", "bus_if.sv", 63, 68,
                 [("top.sv", 186, 191)]),
                ("interface_ports", "data", "bus_if.sv", 88, 92,
                 [("bus_if.sv", 179, 183), ("bus_if.sv", 271, 275),
                  ("child.sv", 102, 106), ("top.sv", 293, 297)]),
                ("interface_ports", "valid", "bus_if.sv", 111, 116,
                 [("bus_if.sv", 200, 205), ("bus_if.sv", 292, 297),
                  ("child.sv", 68, 73), ("top.sv", 328, 333)]),
                ("interface_ports", "ready", "bus_if.sv", 135, 140,
                 [("bus_if.sv", 222, 227), ("bus_if.sv", 314, 319)]),
                ("modports", "master", "bus_if.sv", 155, 161, []),
                ("modports", "slave", "bus_if.sv", 248, 253, []),
                ("interface_instances", "u_bus", "top.sv", 150, 155,
                 [("top.sv", 250, 255), ("top.sv", 287, 292),
                  ("top.sv", 322, 327)]),
            ]
            self.assertEqual(len(entries), len(expected))
            for entry, (category, original, file, start, end, refs) in zip(
                entries, expected, strict=True
            ):
                self.assertEqual(entry["category"], category)
                self.assertEqual(entry["original_name"], original)
                self.assertRegex(entry["renamed_name"], r"[A-Za-z][A-Za-z0-9_]{7}")
                self.assertEqual(
                    entry["declaration"], {"file": file, "start": start, "end": end}
                )
                self.assertEqual(
                    [(r["file"], r["start"], r["end"]) for r in entry["references"]],
                    refs,
                )
                for record in [entry["declaration"], *entry["references"]]:
                    source = (source_root / record["file"]).read_bytes()
                    self.assertEqual(
                        source[record["start"] : record["end"]],
                        original.encode("utf-8"),
                    )

            metrics = json.loads(metrics_file.read_text(encoding="utf-8"))
            self.assertEqual(metrics["symbols"], {
                "renamed": 8, "eligible": 8, "coverage": 1.0,
            })
            self.assertEqual(metrics["occurrences"], {
                "renamed": 23, "eligible": 23, "coverage": 1.0,
            })
            self.assertEqual(metrics["plaintext_leakage_rate"], 0.0)
            self.assertEqual(metrics["effective_coverage"], 1.0)

            decrypt = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "rtl_obfuscator.rewrite",
                    "decrypt-project",
                    "--gate-dir",
                    str(gate_dir),
                    "--source-root",
                    str(source_root),
                    "--map",
                    str(mapping_file),
                    "--output-dir",
                    str(restored_dir),
                ],
                cwd=repository,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(decrypt.returncode, 0, decrypt.stderr)
            self.assertEqual(
                json.loads(decrypt.stdout),
                {"files": 3, "mapping_entries": 8, "modified_tokens": 23},
            )
            for relative_file in mapping["files"]:
                self.assertEqual(
                    (restored_dir / relative_file).read_bytes(),
                    (source_root / relative_file).read_bytes(),
                )


if __name__ == "__main__":
    unittest.main()
