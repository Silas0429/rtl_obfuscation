from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from rtl_obfuscator.category_registry_vnext import MODULE_ABI_CATEGORIES


REPOSITORY = Path(__file__).resolve().parents[1]
FIFO = REPOSITORY / "rtl_samples" / "example_fifo"
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

    def test_default_fifo_vnext_demo_restores_byte_identically(self) -> None:
        with TemporaryDirectory(prefix="rtl-obfuscation-encrypt-demo-") as temporary:
            work_dir = Path(temporary) / "demo"
            process = self._run("--work-dir", str(work_dir))
            self.assertEqual(process.returncode, 0, process.stderr)
            summary = json.loads(process.stdout)
            self.assertEqual(summary["status"], "pass")
            self.assertEqual(summary["sample"], "fifo")
            self.assertEqual(summary["top"], "fifo_top")
            self.assertEqual(summary["name_length"], 20)
            self.assertEqual(summary["categories"], ALL_CATEGORIES)
            self.assertEqual(summary["files"], 4)
            self.assertTrue(summary["byte_identical"])
            self.assertEqual(summary["encrypt"]["strict_compile_passed"], True)
            self.assertEqual(summary["decrypt"]["restored_byte_identical"], True)
            mapping = json.loads((work_dir / "orchestration.json").read_text(encoding="utf-8"))
            self.assertEqual(mapping["mapping"]["selection"]["selected_categories"], ALL_CATEGORIES)
            self.assertEqual(
                mapping["mapping"]["selection"]["abi_categories"],
                list(MODULE_ABI_CATEGORIES),
            )
            records = mapping["mapping"]["records"]
            renamed_abi_categories = {
                record["category"]
                for record in records
                if record["category"] in MODULE_ABI_CATEGORIES
                and record["action"] == "rename"
            }
            self.assertEqual(
                renamed_abi_categories,
                set(MODULE_ABI_CATEGORIES) - {"interface_instances"},
            )
            for category, name in (
                ("modules", "fifo_ctrl"),
                ("ports", "data"),
                ("interfaces", "fifo_if"),
                ("interface_ports", "push"),
                ("modports", "consumer"),
            ):
                bound = next(
                    record
                    for record in records
                    if record["category"] == category
                    and record["original_name"] == name
                )
                self.assertEqual(bound["action"], "rename")
                self.assertTrue(bound["occurrences"], (category, name))
            self.assertEqual(mapping["source_set"]["origin"], "project-root")
            self.assertTrue(all(
                (FIFO / relative_file).read_bytes() == (work_dir / "restored" / relative_file).read_bytes()
                for relative_file in mapping["source_set"]["ordered_source_files"]
            ))

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
