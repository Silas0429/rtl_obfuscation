from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
FIXTURE = REPOSITORY / "tests" / "fixtures" / "t031_project_root_parameters"
NEGATIVE = REPOSITORY / "tests" / "fixtures" / "t031_project_root_parameters_negative"


class ProjectRootParameterTests(unittest.TestCase):
    def _run(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "rtl_obfuscator.rewrite", *arguments],
            cwd=REPOSITORY,
            capture_output=True,
            text=True,
            check=False,
        )

    def _report(self, *, categories: tuple[str, ...] = ("parameters",)) -> tuple[Path, subprocess.CompletedProcess[str], dict]:
        temporary = tempfile.TemporaryDirectory(prefix="rtl-obfuscation-t031-")
        self.addCleanup(temporary.cleanup)
        report_path = Path(temporary.name) / "report.json"
        arguments = [
            "inspect-project",
            "--project-root",
            str(FIXTURE),
            "--top",
            "parameter_top",
            "--report",
            str(report_path),
        ]
        for category in categories:
            arguments.extend(("--category", category))
        completed = self._run(*arguments)
        report = json.loads(report_path.read_text())
        return report_path, completed, report

    @staticmethod
    def _normalized(entries: list[dict]) -> list[dict]:
        return [
            {
                "category": entry["category"],
                "scope": entry["scope"],
                "original_name": entry["name"],
                "declaration": entry["declaration"],
                "references": entry["references"],
                "occurrences": entry["occurrences"],
            }
            for entry in entries
        ]

    @staticmethod
    def _digest(entries: list[dict]) -> str:
        normalized = ProjectRootParameterTests._normalized(entries)
        normalized.sort(
            key=lambda entry: (
                entry["category"],
                entry["scope"],
                entry["declaration"]["file"] if entry["declaration"] else "\uffff",
                entry["declaration"]["start"] if entry["declaration"] else 2**63,
                entry["original_name"],
            )
        )
        return hashlib.sha256(
            json.dumps(
                normalized,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode()
        ).hexdigest()

    def test_parameters_only_exact_oracle(self) -> None:
        _, completed, report = self._report()
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(
            json.loads(completed.stdout),
            {
                "candidate_files": 3,
                "closure_files": 3,
                "definitions": 4,
                "eligible_occurrences": 9,
                "eligible_symbols": 5,
                "reachable_interfaces": 1,
                "reachable_modules": 2,
                "status": "pass",
                "top": "parameter_top",
            },
        )
        self.assertEqual(len(report["inventory"]["eligible"]), 5)
        self.assertEqual(sum(x["occurrences"] for x in report["inventory"]["eligible"]), 9)
        self.assertEqual(len(report["inventory"]["preserved"]), 6)
        self.assertEqual(sum(x["occurrences"] for x in report["inventory"]["preserved"]), 23)
        self.assertEqual(
            self._digest(report["inventory"]["eligible"]),
            "236d7147469bcd733e562242af51d13650f5729b2e1507b78eb7a1e17e1a7e65",
        )
        self.assertEqual(
            self._digest(report["inventory"]["preserved"]),
            "e77ef3efc9395ac0f671587a0c325c26019a771d24cd5fcf8cd8b30afbbbb8e6",
        )
        all_entries = report["inventory"]["eligible"] + report["inventory"]["preserved"]
        self.assertEqual(
            self._digest(all_entries),
            "4fd5b403b0c02062d0fae975eccf0fe449c3d4c4054bb3be4e62deea37728721",
        )

    def test_ranges_read_back_and_reports_are_deterministic(self) -> None:
        first_path, first_completed, first = self._report()
        second_path, second_completed, second = self._report()
        self.assertEqual(first_completed.returncode, 0, first_completed.stderr)
        self.assertEqual(second_completed.returncode, 0, second_completed.stderr)
        self.assertEqual(first_path.read_bytes(), second_path.read_bytes())
        all_ranges: dict[str, list[tuple[int, int]]] = {}
        for entry in first["inventory"]["eligible"] + first["inventory"]["preserved"]:
            records = ([] if entry["declaration"] is None else [entry["declaration"]]) + entry["references"]
            for record in records:
                source = (FIXTURE / record["file"]).read_bytes()
                self.assertEqual(source[record["start"] : record["end"]], entry["name"].encode())
                all_ranges.setdefault(record["file"], []).append((record["start"], record["end"]))
        for ranges in all_ranges.values():
            ordered = sorted(ranges)
            self.assertEqual(len(ordered), len(set(ordered)))
            self.assertFalse(any(start < previous_end for (_, previous_end), (start, _) in zip(ordered, ordered[1:])))

    def test_top_macro_and_unreachable_parameters_are_classified(self) -> None:
        _, completed, report = self._report()
        self.assertEqual(completed.returncode, 0, completed.stderr)
        preserved = {(item["scope"], item["name"]): item for item in report["inventory"]["preserved"]}
        self.assertEqual(preserved[("parameter_top", "DATA_WIDTH")]["reason"], "top_parameter")
        self.assertEqual(preserved[("parameter_top", "LANES")]["reason"], "top_parameter")
        self.assertEqual(preserved[("parameter_top", "MACRO_LOCAL")]["reason"], "macro_expansion")
        self.assertIsNone(preserved[("parameter_top", "MACRO_LOCAL")]["declaration"])
        self.assertFalse(any("unreachable_parameter_decoy" in json.dumps(item) for item in report["inventory"]["eligible"] + report["inventory"]["preserved"]))
        self.assertNotIn("unreachable_parameter_decoy", report["reachable"]["modules"])

    def test_shadowing_and_named_overrides_bind_by_identity(self) -> None:
        _, completed, report = self._report(
            categories=("parameters", "ports", "instances")
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        child_width = next(item for item in report["inventory"]["eligible"] if item["scope"] == "parameter_child" and item["name"] == "WIDTH")
        child_depth = next(item for item in report["inventory"]["eligible"] if item["scope"] == "parameter_child" and item["name"] == "DEPTH")
        self.assertIn({"file": "top.sv", "start": 752, "end": 757}, child_width["references"])
        self.assertIn({"file": "top.sv", "start": 780, "end": 785}, child_depth["references"])
        self.assertNotIn({"file": "top.sv", "start": 193, "end": 203}, child_width["references"])

    def test_existing_groups_plus_parameters_are_supported(self) -> None:
        _, completed, report = self._report(
            categories=("signals", "ports", "instances", "struct", "interface", "parameters")
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(any(item["category"] == "parameters" for item in report["inventory"]["eligible"]))
        self.assertEqual(report["reachable"]["modules"], ["parameter_child", "parameter_top"])
        self.assertEqual(report["reachable"]["interfaces"], ["bus_if"])

    def test_default_profile_includes_parameters_with_top_abi_preserved(self) -> None:
        _, completed, report = self._report(categories=())
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(report["selected_categories"], [
            "signals", "parameters", "enum_values", "genvars", "functions",
            "tasks", "arguments", "instances", "generate_blocks", "typedefs",
            "struct_types", "struct_fields", "union_fields",
        ])
        self.assertTrue(any(item["category"] == "parameters" for item in report["inventory"]["eligible"]))
        self.assertTrue(any(
            item["category"] == "parameters" and item["reason"] == "top_parameter"
            for item in report["inventory"]["preserved"]
        ))

    def test_type_parameter_fails_closed(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="rtl-obfuscation-t031-negative-")
        self.addCleanup(temporary.cleanup)
        report_path = Path(temporary.name) / "report.json"
        completed = self._run(
            "inspect-project",
            "--project-root",
            str(NEGATIVE),
            "--top",
            "parameter_type_negative",
            "--report",
            str(report_path),
            "--category",
            "parameters",
        )
        self.assertEqual(completed.returncode, 1)
        report = json.loads(report_path.read_text())
        self.assertEqual(report["status"], "error")
        self.assertEqual(report["diagnostics"][0]["code"], "UNSUPPORTED_PARAMETER_KIND")
        self.assertEqual(report["inventory"]["eligible"], [])

    def test_parameters_are_connected_to_project_encrypt(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="rtl-obfuscation-t031-encrypt-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        completed = self._run(
            "encrypt-project",
            "--project-root",
            str(FIXTURE),
            "--top",
            "parameter_top",
            "--output-dir",
            str(root / "gate"),
            "--map",
            str(root / "mapping.json"),
            "--metrics",
            str(root / "metrics.json"),
            "--category",
            "parameters",
            "--name-length",
            "8",
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        mapping = json.loads((root / "mapping.json").read_text())
        self.assertEqual(mapping["selected_groups"], ["parameters"])
        self.assertEqual(len(mapping["entries"]), 5)
        self.assertTrue((root / "gate" / "design.f").is_file())

    def test_legacy_single_file_parameter_behavior_remains_available(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="rtl-obfuscation-t031-legacy-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        gold = REPOSITORY / "tests" / "fixtures" / "t005_value_parameter.sv"
        gate = root / "gate.sv"
        mapping = root / "mapping.json"
        completed = self._run(
            "encrypt",
            "--input",
            str(gold),
            "--output",
            str(gate),
            "--map",
            str(mapping),
            "--metrics",
            str(root / "metrics.json"),
            "--category",
            "parameters",
            "--name-length",
            "8",
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(json.loads(mapping.read_text())["entries"])
        restored = root / "restored.sv"
        completed = self._run(
            "decrypt",
            "--input",
            str(gate),
            "--output",
            str(restored),
            "--map",
            str(mapping),
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(gold.read_bytes(), restored.read_bytes())


if __name__ == "__main__":
    unittest.main()
