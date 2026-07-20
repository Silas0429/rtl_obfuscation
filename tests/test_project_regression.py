"""Black-box regression tests for the T019 project matrix."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


class ProjectRegressionCliTest(unittest.TestCase):
    CASES = (
        {
            "name": "t015_all",
            "fixture": "tests/fixtures/t015_multi_file",
            "top": "t015_top",
            "categories": ["all"],
            "summary": {"files": 2, "mapping_entries": 4, "modified_tokens": 10},
            "category_counts": {"signals": 2, "typedefs": 1, "instances": 1},
        },
        {
            "name": "t016_default",
            "fixture": "tests/fixtures/t016_module_port",
            "top": "t016_top",
            "categories": ["all"],
            "summary": {"files": 2, "mapping_entries": 2, "modified_tokens": 4},
            "category_counts": {"signals": 1, "instances": 1},
        },
        {
            "name": "t017_all",
            "fixture": "tests/fixtures/t017_interface",
            "top": "t017_top",
            "categories": ["all"],
            "summary": {"files": 3, "mapping_entries": 1, "modified_tokens": 1},
            "category_counts": {"instances": 1},
        },
    )

    def test_fixed_project_matrix_round_trips(self) -> None:
        repository = Path(__file__).resolve().parents[1]

        with TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            for case in self.CASES:
                fixture = repository / case["fixture"]
                case_root = tmp_root / case["name"]
                gate_dir = case_root / "gate"
                restored_dir = case_root / "restored"
                mapping_file = case_root / "mapping.json"
                metrics_file = case_root / "metrics.json"

                command = [
                    sys.executable,
                    "-m",
                    "rtl_obfuscator.rewrite",
                    "encrypt-project",
                    "--filelist",
                    str(fixture / "design.f"),
                    "--source-root",
                    str(fixture),
                    "--output-dir",
                    str(gate_dir),
                    "--map",
                    str(mapping_file),
                    "--metrics",
                    str(metrics_file),
                    "--top",
                    case["top"],
                ]
                for category in case["categories"]:
                    command.extend(["--category", category])
                command.extend(["--name-length", "8"])

                encrypt = subprocess.run(
                    command,
                    cwd=repository,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(encrypt.returncode, 0, encrypt.stderr)
                self.assertEqual(json.loads(encrypt.stdout), case["summary"])

                mapping = json.loads(mapping_file.read_text(encoding="utf-8"))
                self.assertEqual(mapping["version"], 2)
                self.assertEqual(mapping["top"], case["top"])
                entries = mapping["entries"]
                self.assertEqual(
                    Counter(entry["category"] for entry in entries),
                    Counter(case["category_counts"]),
                )
                self.assertEqual(
                    [
                        (entry["declaration"]["file"], entry["declaration"]["start"], entry["category"])
                        for entry in entries
                    ],
                    sorted(
                        (entry["declaration"]["file"], entry["declaration"]["start"], entry["category"])
                        for entry in entries
                    ),
                )
                for entry in entries:
                    records = [entry["declaration"], *entry["references"]]
                    for record in records:
                        source = (fixture / record["file"]).read_bytes()
                        self.assertEqual(
                            source[record["start"] : record["end"]],
                            entry["original_name"].encode("utf-8"),
                        )

                metrics = json.loads(metrics_file.read_text(encoding="utf-8"))
                self.assertEqual(metrics["symbols"]["coverage"], 1.0)
                self.assertEqual(metrics["occurrences"]["coverage"], 1.0)
                self.assertEqual(metrics["plaintext_leakage_rate"], 0.0)
                self.assertEqual(metrics["effective_coverage"], 1.0)

                if case["name"] == "t017_all":
                    self.assertNotIn("interfaces", {entry["category"] for entry in entries})
                    self.assertEqual(
                        (gate_dir / "bus_if.sv").read_bytes(),
                        (fixture / "bus_if.sv").read_bytes(),
                    )

                decrypt = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "rtl_obfuscator.rewrite",
                        "decrypt-project",
                        "--gate-dir",
                        str(gate_dir),
                        "--source-root",
                        str(fixture),
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
                self.assertEqual(json.loads(decrypt.stdout), case["summary"])
                for relative_file in mapping["files"]:
                    self.assertEqual(
                        (restored_dir / relative_file).read_bytes(),
                        (fixture / relative_file).read_bytes(),
                    )


if __name__ == "__main__":
    unittest.main()
