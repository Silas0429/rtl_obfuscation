"""Black-box test for the T002 variable range inventory."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import unittest


class VariableRangeCliTest(unittest.TestCase):
    def test_fixed_sample_declaration_and_reference_ranges(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        relative_input = Path("rtl_samples/01_continuous_assign.sv")
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "rtl_obfuscator.inventory",
                "--input",
                str(relative_input),
                "--category",
                "signals",
                "--name-length",
                "8",
                "--include-ranges",
            ],
            cwd=repository,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(len(payload["entries"]), 1)

        entry = payload["entries"][0]
        self.assertEqual(entry["original_name"], "and_result")
        self.assertEqual(
            entry["declaration"],
            {
                "file": str(relative_input),
                "start": 202,
                "end": 212,
            },
        )
        self.assertEqual(
            entry["references"],
            [
                {"file": str(relative_input), "start": 226, "end": 236},
                {"file": str(relative_input), "start": 280, "end": 290},
            ],
        )

        source_bytes = (repository / relative_input).read_bytes()
        ranges = [entry["declaration"], *entry["references"]]
        self.assertEqual(len(ranges), 3)
        self.assertEqual(
            [(item["start"], item["end"]) for item in ranges],
            [(202, 212), (226, 236), (280, 290)],
        )
        self.assertEqual(len({(item["start"], item["end"]) for item in ranges}), 3)
        for item in ranges:
            self.assertEqual(
                source_bytes[item["start"] : item["end"]], b"and_result"
            )


if __name__ == "__main__":
    unittest.main()
