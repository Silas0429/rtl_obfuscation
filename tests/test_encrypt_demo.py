"""Black-box tests for the FIFO/RISC-V-Vector encrypt.py demonstrations."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
FIFO = REPOSITORY / "rtl_samples" / "example_fifo"
RISC = REPOSITORY / "rtl_samples" / "RISC-V-Vector"
ALL_CATEGORIES = [
    "signals", "parameters", "enum_values", "genvars", "functions", "tasks",
    "arguments", "instances", "generate_blocks", "typedefs", "struct_types",
    "struct_fields", "union_fields", "modules", "ports", "interfaces",
    "interface_instances", "interface_ports", "modports",
]


class EncryptDemoTests(unittest.TestCase):
    def _run(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "encrypt.py", *arguments],
            cwd=REPOSITORY,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_default_profile_encrypts_and_decrypts_byte_identically(self) -> None:
        with TemporaryDirectory(prefix="rtl-obfuscation-encrypt-demo-") as temporary:
            work_dir = Path(temporary) / "demo"
            process = self._run("--work-dir", str(work_dir))
            self.assertEqual(process.returncode, 0, process.stderr)
            summary = json.loads(process.stdout)
            self.assertEqual(summary["status"], "pass")
            self.assertEqual(summary["sample"], "riscv")
            self.assertEqual(summary["top"], "vector_top")
            self.assertEqual(summary["mapping_version"], 4)
            self.assertEqual(summary["name_length"], 20)
            self.assertEqual(summary["categories"], ALL_CATEGORIES)
            self.assertEqual(summary["files"], 19)
            self.assertTrue(summary["byte_identical"])
            self.assertEqual(
                summary["encrypt"],
                {"files": 19, "mapping_entries": 1238, "modified_tokens": 7081},
            )
            self.assertEqual(
                summary["decrypt"],
                {"files": 19, "mapping_entries": 1238, "modified_tokens": 7081},
            )
            mapping = json.loads((work_dir / "mapping.json").read_text(encoding="utf-8"))
            self.assertEqual(mapping["selected_categories"], ALL_CATEGORIES)
            self.assertTrue(
                all(
                    len(entry["renamed_name"]) == 20
                    for entry in mapping["entries"]
                )
            )
            self.assertEqual(mapping["files"], sorted(mapping["files"]))
            self.assertIn("rtl/vector/vector_top.sv", mapping["files"])
            self.assertIn("rtl/vector/vmacros.sv", mapping["files"])
            self.assertEqual(len(mapping["files"]), 19)
            self.assertTrue(
                all(
                    (RISC / relative_file).read_bytes()
                    == (work_dir / "restored" / relative_file).read_bytes()
                    for relative_file in mapping["files"]
                )
            )

    def test_fifo_profile_encrypts_and_decrypts_byte_identically(self) -> None:
        with TemporaryDirectory(prefix="rtl-obfuscation-encrypt-demo-") as temporary:
            work_dir = Path(temporary) / "fifo"
            process = self._run(
                "--sample", "fifo", "--work-dir", str(work_dir)
            )
            self.assertEqual(process.returncode, 0, process.stderr)
            summary = json.loads(process.stdout)
            self.assertEqual(summary["sample"], "fifo")
            self.assertEqual(summary["top"], "fifo_top")
            self.assertEqual(summary["name_length"], 20)
            self.assertEqual(summary["files"], 4)
            self.assertEqual(
                summary["encrypt"],
                {"files": 4, "mapping_entries": 67, "modified_tokens": 268},
            )
            self.assertEqual(summary["encrypt"], summary["decrypt"])
            self.assertTrue(summary["byte_identical"])
            mapping = json.loads((work_dir / "mapping.json").read_text(encoding="utf-8"))
            self.assertEqual(mapping["selected_categories"], ALL_CATEGORIES)
            self.assertEqual(len(mapping["files"]), 4)
            self.assertTrue(
                all(
                    (FIFO / relative_file).read_bytes()
                    == (work_dir / "restored" / relative_file).read_bytes()
                    for relative_file in mapping["files"]
                )
            )

    def test_non_empty_work_dir_is_rejected_without_overwrite(self) -> None:
        with TemporaryDirectory(prefix="rtl-obfuscation-encrypt-demo-") as temporary:
            work_dir = Path(temporary) / "demo"
            work_dir.mkdir()
            marker = work_dir / "keep.txt"
            marker.write_text("keep", encoding="utf-8")
            process = self._run("--work-dir", str(work_dir))
            self.assertNotEqual(process.returncode, 0)
            self.assertIn("must be absent or an empty directory", process.stderr)
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")


if __name__ == "__main__":
    unittest.main()
