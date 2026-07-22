"""T036 encryption-rate selection and compatibility black-box tests."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from rtl_obfuscator.rewrite import _rate_selection


REPOSITORY = Path(__file__).resolve().parents[1]
T033 = REPOSITORY / "tests" / "fixtures" / "t033_impact_category"
T034 = REPOSITORY / "tests" / "fixtures" / "t034_profile_scope"
DEFAULT_CATEGORIES = (
    "all",
)
FULL_CATEGORIES = (
    "all",
    "modules",
    "ports",
    "interfaces",
    "interface_instances",
    "interface_ports",
    "modports",
)


class EncryptionRateTests(unittest.TestCase):
    def _run(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "rtl_obfuscator.rewrite", *arguments],
            cwd=REPOSITORY,
            capture_output=True,
            text=True,
            check=False,
        )

    @staticmethod
    def _read_json(path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _effective_lines(source: bytes) -> int:
        return sum(
            1
            for line in source.decode("utf-8").splitlines()
            if line.strip() and not line.strip().startswith("//")
        )

    @staticmethod
    def _category_arguments(categories: tuple[str, ...]) -> list[str]:
        return [argument for category in categories for argument in ("--category", category)]

    def _encrypt_single(
        self,
        base: Path,
        *,
        source: Path,
        categories: tuple[str, ...] = DEFAULT_CATEGORIES,
        rate: str | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], dict, dict]:
        command = [
            "encrypt",
            "--input",
            str(source),
            "--output",
            str(base / "gate.sv"),
            "--map",
            str(base / "mapping.json"),
            "--metrics",
            str(base / "metrics.json"),
            *self._category_arguments(categories),
            "--name-length",
            "8",
        ]
        if rate is not None:
            command.extend(("--encryption-rate", rate))
        completed = self._run(*command)
        mapping = self._read_json(base / "mapping.json") if (base / "mapping.json").is_file() else {}
        metrics = self._read_json(base / "metrics.json") if (base / "metrics.json").is_file() else {}
        return completed, mapping, metrics

    def _encrypt_project(
        self,
        base: Path,
        *,
        source_root: Path,
        project_root: bool,
        categories: tuple[str, ...] = DEFAULT_CATEGORIES,
        rate: str | None = None,
        top: str | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], Path, dict, dict]:
        prefix = "project" if project_root else "filelist"
        gate = base / f"{prefix}-gate"
        mapping_path = base / f"{prefix}.json"
        metrics_path = base / f"{prefix}-metrics.json"
        command = [
            "encrypt-project",
            "--top",
            top or ("t033_top" if source_root == T033 else "t034_top"),
            "--output-dir",
            str(gate),
            "--map",
            str(mapping_path),
            "--metrics",
            str(metrics_path),
            *self._category_arguments(categories),
            "--name-length",
            "8",
        ]
        if project_root:
            command.extend(("--project-root", str(source_root)))
        else:
            command.extend(("--filelist", str(source_root / "design.f"), "--source-root", str(source_root)))
        if rate is not None:
            command.extend(("--encryption-rate", rate))
        completed = self._run(*command)
        mapping = self._read_json(mapping_path) if mapping_path.is_file() else {}
        metrics = self._read_json(metrics_path) if metrics_path.is_file() else {}
        return completed, gate, mapping, metrics

    def _assert_rate_metrics(self, metrics: dict, mapping: dict, source_root: Path) -> None:
        rate = metrics["encryption_rate"]
        if mapping["version"] == 1:
            total_lines = self._effective_lines(source_root.read_bytes())
        else:
            total_lines = sum(
                self._effective_lines((source_root / relative_file).read_bytes())
                for relative_file in mapping["files"]
            )
        self.assertEqual(rate["total_lines"], total_lines)
        self.assertEqual(metrics["affected_lines"]["total"], rate["total_lines"])
        self.assertAlmostEqual(metrics["affected_lines"]["rate"], rate["actual_rate"])
        candidate_lines = {
            (item["file"], item["line"])
            for candidate in rate["candidates"]
            for item in candidate["affected_lines"]
        }
        selected_lines = {
            (item["file"], item["line"])
            for candidate in rate["candidates"]
            if candidate["selected"]
            for item in candidate["affected_lines"]
        }
        self.assertEqual(rate["candidate_lines"], len(candidate_lines))
        self.assertEqual(rate["selected_lines"], len(selected_lines))
        self.assertEqual(rate["candidate_entries"], len(rate["candidates"]))
        self.assertEqual(
            rate["selected_entries"],
            sum(candidate["selected"] for candidate in rate["candidates"]),
        )
        self.assertAlmostEqual(
            rate["actual_rate"],
            rate["selected_lines"] / rate["total_lines"] if rate["total_lines"] else 0.0,
        )
        self.assertAlmostEqual(
            rate["maximum_rate"],
            rate["candidate_lines"] / rate["total_lines"] if rate["total_lines"] else 0.0,
        )
        selected_keys = {
            (
                item["category"],
                item["scope"],
                item["original_name"],
                item["declaration"]["file"],
                item["declaration"]["start"],
            )
            for item in mapping["entries"]
        }
        metric_selected_keys = {
            (
                item["category"],
                item["scope"],
                item["original_name"],
                item["declaration"]["file"],
                item["declaration"]["start"],
            )
            for item in rate["candidates"]
            if item["selected"]
        }
        self.assertEqual(selected_keys, metric_selected_keys)
        if rate["target_unreachable"]:
            self.assertEqual(rate["selection_mode"], "all_candidates")
            self.assertEqual(rate["selected_entries"], rate["candidate_entries"])
            self.assertEqual(rate["selected_lines"], rate["candidate_lines"])
        else:
            self.assertEqual(rate["selection_mode"], "greedy")
            self.assertGreaterEqual(rate["actual_rate"], rate["target"])

    def _assert_project_round_trip(
        self, base: Path, gate: Path, mapping: dict, source_root: Path
    ) -> None:
        restored = base / f"restored-{mapping['version']}"
        completed = self._run(
            "decrypt-project",
            "--gate-dir",
            str(gate),
            "--source-root",
            str(source_root),
            "--map",
            str(base / ("project.json" if "project" in base.name else "filelist.json")),
            "--output-dir",
            str(restored),
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        for relative_file in mapping["files"]:
            self.assertEqual(
                (restored / relative_file).read_bytes(),
                (source_root / relative_file).read_bytes(),
            )

    def test_pure_selector_deduplicates_lines_and_ignores_random_names(self) -> None:
        source = b"alpha\nbeta beta\ngamma"
        def entry(name: str, renamed: str, declaration: tuple[int, int], references: list[tuple[int, int]]) -> dict:
            return {
                "category": "signals",
                "scope": "m",
                "original_name": name,
                "renamed_name": renamed,
                "declaration": {"file": "synthetic.sv", "start": declaration[0], "end": declaration[1]},
                "references": [
                    {"file": "synthetic.sv", "start": start, "end": end}
                    for start, end in references
                ],
            }

        entries = [
            entry("a", "random_a", (0, 1), [(1, 2)]),
            entry("b", "random_b", (6, 7), [(8, 9)]),
            entry("c", "random_c", (11, 12), [(16, 17)]),
        ]
        selected, info = _rate_selection(
            entries,
            source_files={"synthetic.sv": source},
            total_sources=[source],
            rate_value="0.67",
        )
        self.assertEqual(info["total_lines"], 3)
        self.assertEqual(info["candidate_lines"], 3)
        self.assertEqual(info["target_lines"], 3)
        self.assertEqual(info["selected_lines"], 3)
        self.assertEqual(info["selected_entries"], 2)
        self.assertEqual(
            {(item["original_name"], item["renamed_name"]) for item in selected},
            {("a", "random_a"), ("c", "random_c")},
        )
        renamed = copy.deepcopy(entries)
        for index, item in enumerate(renamed):
            item["renamed_name"] = f"different_{index}"
        _, renamed_info = _rate_selection(
            renamed,
            source_files={"synthetic.sv": source},
            total_sources=[source],
            rate_value="0.67",
        )
        self.assertEqual(
            [item["original_name"] for item in info["candidates"] if item["selected"]],
            [item["original_name"] for item in renamed_info["candidates"] if item["selected"]],
        )
        self.assertEqual(info["candidates"][0]["affected_line_count"], 1)

    def test_single_file_multiple_modules_and_rate_round_trip(self) -> None:
        with TemporaryDirectory(prefix="rtl-obfuscation-t036-single-") as temporary:
            base = Path(temporary)
            source = base / "multi.sv"
            source.write_text(
                "module first;\n  logic first_state;\n  assign first_state = first_state;\nendmodule\n\n"
                "module second;\n  logic second_state;\n  assign second_state = second_state;\nendmodule\n",
                encoding="utf-8",
            )
            completed, mapping, metrics = self._encrypt_single(
                base, source=source, rate="0.35"
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(mapping["version"], 1)
            self.assertEqual({item["scope"] for item in mapping["entries"]}, {"first", "second"})
            self.assertTrue(all(item["category"] == "signals" for item in mapping["entries"]))
            self._assert_rate_metrics(metrics, mapping, source)
            restored = base / "restored.sv"
            decrypted = self._run(
                "decrypt",
                "--input",
                str(base / "gate.sv"),
                "--output",
                str(restored),
                "--map",
                str(base / "mapping.json"),
            )
            self.assertEqual(decrypted.returncode, 0, decrypted.stderr)
            self.assertEqual(restored.read_bytes(), source.read_bytes())

    def test_rate_modes_versions_closure_metrics_and_decrypt(self) -> None:
        with TemporaryDirectory(prefix="rtl-obfuscation-t036-modes-") as temporary:
            base = Path(temporary)
            single_result, single_mapping, single_metrics = self._encrypt_single(
                base / "single", source=T034 / "child.sv", rate="0.35"
            )
            self.assertEqual(single_result.returncode, 0, single_result.stderr)
            self.assertEqual(single_mapping["version"], 1)
            self._assert_rate_metrics(single_metrics, single_mapping, T034 / "child.sv")

            filelist_result, filelist_gate, filelist_mapping, filelist_metrics = self._encrypt_project(
                base / "filelist", source_root=T034, project_root=False, rate="0.35"
            )
            project_result, project_gate, project_mapping, project_metrics = self._encrypt_project(
                base / "project", source_root=T033, project_root=True, rate="0.35"
            )
            manual_filelist_result, manual_filelist_gate, manual_filelist_mapping, manual_filelist_metrics = self._encrypt_project(
                base / "manual-filelist",
                source_root=T033,
                project_root=False,
                categories=FULL_CATEGORIES,
                rate="0.35",
            )
            manual_project_result, manual_project_gate, manual_project_mapping, manual_project_metrics = self._encrypt_project(
                base / "manual-project",
                source_root=T033,
                project_root=True,
                categories=FULL_CATEGORIES,
                rate="0.35",
            )
            for result in (
                filelist_result,
                project_result,
                manual_filelist_result,
                manual_project_result,
            ):
                self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(filelist_mapping["version"], 2)
            self.assertEqual(project_mapping["version"], 3)
            self.assertEqual(manual_filelist_mapping["version"], 4)
            self.assertEqual(manual_project_mapping["version"], 4)
            self.assertEqual(
                filelist_metrics["encryption_rate"]["total_lines"],
                sum(self._effective_lines((T034 / name).read_bytes()) for name in filelist_mapping["files"]),
            )
            self.assertEqual(
                manual_filelist_mapping["skipped"][0]["file"],
                "decoy.sv",
            )
            self.assertTrue(
                all(
                    item["declaration"]["file"] in manual_filelist_mapping["closure"]["files"]
                    for item in manual_filelist_metrics["encryption_rate"]["candidates"]
                )
            )
            self.assertNotIn(
                "decoy.sv",
                {item["declaration"]["file"] for item in manual_filelist_metrics["encryption_rate"]["candidates"]},
            )
            for mapping, metrics in (
                (filelist_mapping, filelist_metrics),
                (project_mapping, project_metrics),
                (manual_filelist_mapping, manual_filelist_metrics),
                (manual_project_mapping, manual_project_metrics),
            ):
                self._assert_rate_metrics(
                    metrics,
                    mapping,
                    T034 if mapping is filelist_mapping else T033,
                )
            self._assert_project_round_trip(base / "filelist", filelist_gate, filelist_mapping, T034)
            self._assert_project_round_trip(base / "project", project_gate, project_mapping, T033)
            self._assert_project_round_trip(base / "manual-filelist", manual_filelist_gate, manual_filelist_mapping, T033)
            self._assert_project_round_trip(base / "manual-project", manual_project_gate, manual_project_mapping, T033)

    def test_no_rate_preserves_legacy_summary_and_metrics_schema(self) -> None:
        with TemporaryDirectory(prefix="rtl-obfuscation-t036-compat-") as temporary:
            base = Path(temporary)
            single_result, single_mapping, single_metrics = self._encrypt_single(
                base / "single", source=T034 / "child.sv"
            )
            filelist_result, _, filelist_mapping, filelist_metrics = self._encrypt_project(
                base / "filelist", source_root=T034, project_root=False
            )
            project_result, _, project_mapping, project_metrics = self._encrypt_project(
                base / "project", source_root=T034, project_root=True
            )
            for result in (single_result, filelist_result, project_result):
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn("encryption_rate", json.loads(result.stdout))
            for metrics in (single_metrics, filelist_metrics, project_metrics):
                self.assertNotIn("encryption_rate", metrics)
            self.assertEqual(single_mapping["version"], 1)
            self.assertEqual(filelist_mapping["version"], 2)
            self.assertEqual(project_mapping["version"], 3)

    def test_invalid_rate_and_debug_conflict_are_stable(self) -> None:
        invalid_values = ("0", "-0.1", "1.1", "NaN", "Infinity", "not-a-rate")
        for value in invalid_values:
            with self.subTest(value=value), TemporaryDirectory(prefix="rtl-obfuscation-t036-invalid-") as temporary:
                base = Path(temporary)
                completed = self._run(
                    "encrypt",
                    "--input",
                    str(T034 / "child.sv"),
                    "--output",
                    str(base / "gate.sv"),
                    "--map",
                    str(base / "mapping.json"),
                    "--metrics",
                    str(base / "metrics.json"),
                    "--category",
                    "all",
                    "--name-length",
                    "8",
                    "--encryption-rate",
                    value,
                )
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn("ENCRYPTION_RATE_INVALID", completed.stderr)
                self.assertFalse((base / "gate.sv").exists())
                self.assertFalse((base / "mapping.json").exists())
                self.assertFalse((base / "metrics.json").exists())

        with TemporaryDirectory(prefix="rtl-obfuscation-t036-debug-") as temporary:
            completed = self._run(
                "encrypt",
                "--input",
                str(T034 / "child.sv"),
                "--debug",
                str(Path(temporary) / "debug"),
                "--name-length",
                "8",
                "--encryption-rate",
                "0.35",
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("ENCRYPTION_RATE_DEBUG_UNSUPPORTED", completed.stderr)

    def test_empty_candidates_publish_identity_for_all_project_versions(self) -> None:
        with TemporaryDirectory(prefix="rtl-obfuscation-t036-empty-") as temporary:
            root = Path(temporary) / "source"
            root.mkdir()
            source = root / "empty.sv"
            source.write_text(
                "module empty_top (input logic data, output logic q);\n"
                "  assign q = data;\n"
                "endmodule\n",
                encoding="utf-8",
            )
            (root / "design.f").write_text("empty.sv\n", encoding="utf-8")
            single_result, single_mapping, single_metrics = self._encrypt_single(
                Path(temporary) / "single", source=source, rate="0.35"
            )
            self.assertEqual(single_result.returncode, 0, single_result.stderr)
            self.assertEqual(single_mapping["entries"], [])
            self.assertTrue(single_metrics["encryption_rate"]["target_unreachable"])
            self.assertEqual((Path(temporary) / "single" / "gate.sv").read_bytes(), source.read_bytes())
            single_restored = Path(temporary) / "single-restored.sv"
            single_decrypt = self._run(
                "decrypt",
                "--input",
                str(Path(temporary) / "single" / "gate.sv"),
                "--output",
                str(single_restored),
                "--map",
                str(Path(temporary) / "single" / "mapping.json"),
            )
            self.assertEqual(single_decrypt.returncode, 0, single_decrypt.stderr)
            self.assertEqual(single_restored.read_bytes(), source.read_bytes())

            filelist_result, filelist_gate, filelist_mapping, filelist_metrics = self._encrypt_project(
                Path(temporary) / "filelist", source_root=root, project_root=False, rate="0.35", top="empty_top"
            )
            project_result, project_gate, project_mapping, project_metrics = self._encrypt_project(
                Path(temporary) / "project", source_root=root, project_root=True, rate="0.35", top="empty_top"
            )
            for result in (filelist_result, project_result):
                self.assertEqual(result.returncode, 0, result.stderr)
            for gate, mapping, metrics, base in (
                (filelist_gate, filelist_mapping, filelist_metrics, Path(temporary) / "filelist"),
                (project_gate, project_mapping, project_metrics, Path(temporary) / "project"),
            ):
                self.assertEqual(mapping["entries"], [])
                self.assertTrue(metrics["encryption_rate"]["target_unreachable"])
                self.assertEqual((gate / "empty.sv").read_bytes(), source.read_bytes())
                self._assert_project_round_trip(base, gate, mapping, root)


if __name__ == "__main__":
    unittest.main()
