"""Black-box tests for automatic per-category debug encryption."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


SINGLE_CATEGORIES = {
    "signals": (10, 37),
    "parameters": (4, 10),
    "enum_values": (3, 8),
    "genvars": (1, 5),
    "functions": (1, 2),
    "tasks": (1, 2),
    "arguments": (4, 9),
    "instances": (1, 1),
    "generate_blocks": (1, 1),
    "typedefs": (1, 2),
    "struct_types": (2, 5),
    "struct_fields": (2, 4),
    "union_fields": (2, 4),
}

PROJECT_CATEGORIES = {
    "signals": (14, 67),
    "parameters": (9, 51),
    "enum_values": (3, 6),
    "genvars": (2, 10),
    "functions": (2, 7),
    "tasks": (1, 2),
    "arguments": (4, 9),
    "instances": (2, 2),
    "generate_blocks": (2, 2),
    "typedefs": (2, 7),
    "struct_types": (2, 5),
    "struct_fields": (2, 4),
    "union_fields": (2, 6),
}


def _expected_runs(
    categories: dict[str, tuple[int, int]], files: int
) -> list[dict[str, int | str]]:
    return [
        {
            "category": category,
            "files": files,
            "mapping_entries": entries,
            "modified_tokens": tokens,
        }
        for category, (entries, tokens) in categories.items()
    ]


def _apply_mapping(source: bytes, entries: list[dict[str, object]]) -> bytes:
    edits = [
        (record, str(entry["renamed_name"]).encode("utf-8"))
        for entry in entries
        for record in [entry["declaration"], *entry["references"]]
    ]
    result = source
    for record, replacement in sorted(
        edits, key=lambda item: item[0]["start"], reverse=True
    ):
        result = (
            result[: record["start"]]
            + replacement
            + result[record["end"] :]
        )
    return result


class DebugModeCliTest(unittest.TestCase):
    def test_single_file_debug_runs_thirteen_categories(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        gold = repository / "rtl_samples" / "11_supported_obfuscation.sv"
        with TemporaryDirectory() as temporary_directory:
            debug_root = Path(temporary_directory) / "debug"
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "rtl_obfuscator.rewrite",
                    "encrypt",
                    "--input",
                    str(gold),
                    "--debug",
                    str(debug_root),
                    "--name-length",
                    "8",
                ],
                cwd=repository,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                json.loads(result.stdout),
                {
                    "debug": True,
                    "mode": "single-file",
                    "category_count": 13,
                    "runs": _expected_runs(SINGLE_CATEGORIES, 1),
                },
            )

            source = gold.read_bytes()
            self.assertEqual(
                sorted(path.name for path in debug_root.iterdir()),
                sorted(SINGLE_CATEGORIES),
            )
            for category in SINGLE_CATEGORIES:
                category_root = debug_root / category
                mapping = json.loads(
                    (category_root / "mapping.json").read_text(encoding="utf-8")
                )
                self.assertEqual(mapping["version"], 1)
                self.assertEqual(
                    {entry["category"] for entry in mapping["entries"]},
                    {category} if mapping["entries"] else set(),
                )
                self.assertEqual(
                    (category_root / "gate.sv").read_bytes(),
                    _apply_mapping(source, mapping["entries"]),
                )
                self.assertTrue((category_root / "metrics.json").is_file())

    def test_project_debug_runs_thirteen_categories(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        gold_root = repository / "rtl_samples" / "example_fifo"
        with TemporaryDirectory() as temporary_directory:
            debug_root = Path(temporary_directory) / "debug"
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "rtl_obfuscator.rewrite",
                    "encrypt-project",
                    "--filelist",
                    str(gold_root / "design.f"),
                    "--source-root",
                    str(gold_root),
                    "--top",
                    "fifo_top",
                    "--debug",
                    str(debug_root),
                    "--name-length",
                    "8",
                ],
                cwd=repository,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                json.loads(result.stdout),
                {
                    "debug": True,
                    "mode": "project",
                    "category_count": 13,
                    "runs": _expected_runs(PROJECT_CATEGORIES, 4),
                },
            )

            self.assertEqual(
                sorted(path.name for path in debug_root.iterdir()),
                sorted(PROJECT_CATEGORIES),
            )
            for category in PROJECT_CATEGORIES:
                category_root = debug_root / category
                mapping = json.loads(
                    (category_root / "mapping.json").read_text(encoding="utf-8")
                )
                self.assertEqual(mapping["version"], 2)
                self.assertEqual(mapping["top"], "fifo_top")
                self.assertEqual(
                    {entry["category"] for entry in mapping["entries"]},
                    {category},
                )
                self.assertEqual(
                    sorted(path.name for path in (category_root / "maps").glob("*.json")),
                    ["fifo_ctrl.json", "fifo_if.json", "fifo_storage.json", "fifo_top.json"],
                )
                self.assertTrue((category_root / "gate" / "design.f").is_file())
                self.assertTrue((category_root / "metrics.json").is_file())

    def test_debug_rejects_normal_mode_options(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        gold = repository / "rtl_samples" / "11_supported_obfuscation.sv"
        project = repository / "rtl_samples" / "example_fifo"
        with TemporaryDirectory() as temporary_directory:
            base = Path(temporary_directory)
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "rtl_obfuscator.rewrite",
                    "encrypt",
                    "--input",
                    str(gold),
                    "--debug",
                    str(base / "debug"),
                    "--category",
                    "signals",
                    "--name-length",
                    "8",
                ],
                cwd=repository,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "--debug cannot be combined with --category", result.stderr
            )
            self.assertFalse((base / "debug").exists())

            project_result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "rtl_obfuscator.rewrite",
                    "encrypt-project",
                    "--filelist",
                    str(project / "design.f"),
                    "--source-root",
                    str(project),
                    "--top",
                    "fifo_top",
                    "--debug",
                    str(base / "project-debug"),
                    "--output-dir",
                    str(base / "gate"),
                    "--name-length",
                    "8",
                ],
                cwd=repository,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(project_result.returncode, 0)
            self.assertIn(
                "--debug cannot be combined with --output-dir",
                project_result.stderr,
            )
            self.assertFalse((base / "project-debug").exists())

            decrypt_result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "rtl_obfuscator.rewrite",
                    "decrypt",
                    "--input",
                    str(base / "gate.sv"),
                    "--output",
                    str(base / "restored.sv"),
                    "--map",
                    str(base / "mapping.json"),
                    "--debug",
                    str(base / "decrypt-debug"),
                ],
                cwd=repository,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(decrypt_result.returncode, 0)
            self.assertIn("unrecognized arguments: --debug", decrypt_result.stderr)


if __name__ == "__main__":
    unittest.main()
