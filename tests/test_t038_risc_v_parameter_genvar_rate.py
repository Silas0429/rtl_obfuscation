"""Black-box coverage for the T038 parameter/genvar and rate contracts."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
FIXTURE = REPOSITORY / "tests" / "fixtures" / "t038_risc_v_parameter_genvar"
NEGATIVE = REPOSITORY / "tests" / "fixtures" / "t038_risc_v_parameter_genvar_negative"
MANUAL_CATEGORIES = ("signals", "ports", "instances", "struct", "interface", "parameters")


class T038ParameterGenvarRateTests(unittest.TestCase):
    def _run(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "rtl_obfuscator.rewrite", *arguments],
            cwd=REPOSITORY,
            capture_output=True,
            text=True,
            check=False,
        )

    @staticmethod
    def _category_arguments(categories: tuple[str, ...]) -> list[str]:
        return [argument for category in categories for argument in ("--category", category)]

    @staticmethod
    def _effective_lines(source: bytes) -> int:
        return sum(
            1
            for line in source.decode("utf-8").splitlines()
            if line.strip() and not line.strip().startswith("//")
        )

    def _inspect(self, root: Path, top: str, categories: tuple[str, ...]) -> tuple[dict, bytes]:
        temporary = tempfile.TemporaryDirectory(prefix="rtl-obfuscation-t038-inspect-")
        self.addCleanup(temporary.cleanup)
        report_path = Path(temporary.name) / "report.json"
        completed = self._run(
            "inspect-project",
            "--project-root",
            str(root),
            "--top",
            top,
            "--report",
            str(report_path),
            *self._category_arguments(categories),
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads(report_path.read_text(encoding="utf-8")), report_path.read_bytes()

    def test_inventory_separates_parameter_and_genvar_owners(self) -> None:
        first, first_bytes = self._inspect(FIXTURE, "t038_top", MANUAL_CATEGORIES)
        second, second_bytes = self._inspect(FIXTURE, "t038_top", MANUAL_CATEGORIES)
        self.assertEqual(first_bytes, second_bytes)
        self.assertEqual(first["reachable"]["files"], ["child.sv", "shadow.sv", "top.sv"])
        self.assertEqual(first["reachable"]["modules"], ["t038_child", "t038_shadow", "t038_top"])
        self.assertEqual(first["candidate_files"], ["child.sv", "shadow.sv", "top.sv", "unreachable.sv"])
        self.assertEqual((len(first["inventory"]["eligible"]), sum(item["occurrences"] for item in first["inventory"]["eligible"])), (13, 33))

        parameters = [item for item in first["inventory"]["eligible"] if item["category"] == "parameters"]
        parameter_keys = {(item["scope"], item["name"]) for item in parameters}
        self.assertIn(("t038_child", "WIDTH"), parameter_keys)
        self.assertIn(("t038_child", "EXTRA"), parameter_keys)
        self.assertIn(("t038_shadow", "k"), parameter_keys)
        self.assertNotIn(("t038_unreachable", "HIDDEN_WIDTH"), parameter_keys)
        shadow_parameter = next(item for item in parameters if item["scope"] == "t038_shadow")
        self.assertEqual(shadow_parameter["occurrences"], 1)

        child_width = next(
            item
            for item in parameters
            if item["scope"] == "t038_child" and item["name"] == "WIDTH"
        )
        named_left = (FIXTURE / "top.sv").read_bytes().index(b".WIDTH") + 1
        named_right = (FIXTURE / "top.sv").read_bytes().index(b"(TOP_WIDTH)") + 1
        self.assertIn({"file": "top.sv", "start": named_left, "end": named_left + len("WIDTH")}, child_width["references"])
        self.assertNotIn({"file": "top.sv", "start": named_right, "end": named_right + len("TOP_WIDTH")}, child_width["references"])
        for item in parameters:
            for record in [item["declaration"], *item["references"]]:
                record_source = (FIXTURE / record["file"]).read_bytes()
                self.assertEqual(record_source[record["start"] : record["end"]], item["name"].encode())

        with_genvars, _ = self._inspect(FIXTURE, "t038_top", MANUAL_CATEGORIES + ("genvars",))
        genvars = [item for item in with_genvars["inventory"]["eligible"] if item["category"] == "genvars"]
        self.assertEqual({(item["scope"], item["name"]) for item in genvars}, {("t038_child", "j"), ("t038_shadow", "k")})
        child_j = next(item for item in genvars if item["scope"] == "t038_child")
        self.assertGreaterEqual(child_j["occurrences"], 10)
        self.assertFalse(any(item["scope"] == "t038_shadow" and item["name"] == "k" and item["category"] == "parameters" and item["occurrences"] > 1 for item in first["inventory"]["eligible"]))

    def test_mapping_gate_metrics_rate_and_decrypt(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rtl-obfuscation-t038-rewrite-") as temporary:
            root = Path(temporary)
            gate = root / "gate"
            mapping_path = root / "mapping.json"
            metrics_path = root / "metrics.json"
            completed = self._run(
                "encrypt-project",
                "--project-root",
                str(FIXTURE),
                "--top",
                "t038_top",
                "--output-dir",
                str(gate),
                "--map",
                str(mapping_path),
                "--metrics",
                str(metrics_path),
                "--file-map-dir",
                str(root / "maps"),
                *self._category_arguments(MANUAL_CATEGORIES),
                "--name-length",
                "8",
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(json.loads(completed.stdout), {"files": 3, "mapping_entries": 13, "modified_tokens": 33})
            mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
            self.assertEqual(mapping["version"], 4)
            self.assertEqual(metrics["symbols"]["coverage"], 1.0)
            self.assertEqual(metrics["occurrences"]["coverage"], 1.0)
            self.assertEqual(metrics["plaintext_leakage_rate"], 0.0)
            self.assertEqual(metrics["affected_lines"]["total"], sum(self._effective_lines((FIXTURE / name).read_bytes()) for name in mapping["files"]))

            gate_report = root / "gate-report.json"
            inspected = self._run(
                "inspect-project",
                "--project-root",
                str(gate),
                "--top",
                "t038_top",
                "--report",
                str(gate_report),
                *self._category_arguments(MANUAL_CATEGORIES),
            )
            self.assertEqual(inspected.returncode, 0, inspected.stderr)
            self.assertEqual(json.loads(gate_report.read_text(encoding="utf-8"))["compile"]["semantic_errors"], 0)

            restored = root / "restored"
            decrypted = self._run(
                "decrypt-project",
                "--gate-dir",
                str(gate),
                "--map",
                str(mapping_path),
                "--output-dir",
                str(restored),
            )
            self.assertEqual(decrypted.returncode, 0, decrypted.stderr)
            for relative_file in mapping["files"]:
                self.assertEqual((restored / relative_file).read_bytes(), (FIXTURE / relative_file).read_bytes())

            rate_gate = root / "rate-gate"
            rate_mapping_path = root / "rate-mapping.json"
            rate_metrics_path = root / "rate-metrics.json"
            rate = self._run(
                "encrypt-project",
                "--project-root",
                str(FIXTURE),
                "--top",
                "t038_top",
                "--output-dir",
                str(rate_gate),
                "--map",
                str(rate_mapping_path),
                "--metrics",
                str(rate_metrics_path),
                *self._category_arguments(MANUAL_CATEGORIES),
                "--name-length",
                "8",
                "--encryption-rate",
                "0.35",
            )
            self.assertEqual(rate.returncode, 0, rate.stderr)
            rate_mapping = json.loads(rate_mapping_path.read_text(encoding="utf-8"))
            rate_metrics = json.loads(rate_metrics_path.read_text(encoding="utf-8"))
            rate_info = rate_metrics["encryption_rate"]
            self.assertEqual(rate_info["total_lines"], rate_metrics["affected_lines"]["total"])
            self.assertAlmostEqual(rate_info["actual_rate"], rate_metrics["affected_lines"]["rate"])
            self.assertEqual(rate_info["selected_lines"], len({(line["file"], line["line"]) for candidate in rate_info["candidates"] if candidate["selected"] for line in candidate["affected_lines"]}))
            rate_restored = root / "rate-restored"
            rate_decrypted = self._run("decrypt-project", "--gate-dir", str(rate_gate), "--map", str(rate_mapping_path), "--output-dir", str(rate_restored))
            self.assertEqual(rate_decrypted.returncode, 0, rate_decrypted.stderr)
            for relative_file in rate_mapping["files"]:
                self.assertEqual((rate_restored / relative_file).read_bytes(), (FIXTURE / relative_file).read_bytes())

    def test_unsupported_type_parameter_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rtl-obfuscation-t038-negative-") as temporary:
            report_path = Path(temporary) / "report.json"
            completed = self._run(
                "inspect-project",
                "--project-root",
                str(NEGATIVE),
                "--top",
                "t038_type_parameter",
                "--report",
                str(report_path),
                "--category",
                "parameters",
            )
            self.assertEqual(completed.returncode, 1)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "error")
            self.assertEqual(report["diagnostics"][0]["code"], "UNSUPPORTED_PARAMETER_KIND")
            self.assertEqual(report["inventory"]["eligible"], [])


if __name__ == "__main__":
    unittest.main()
