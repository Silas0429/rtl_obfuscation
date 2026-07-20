from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
FIXTURE = REPOSITORY / "tests" / "fixtures" / "t030_project_root_low_risk"
FIFO = REPOSITORY / "rtl_samples" / "example_fifo"
LOW_RISK_GROUPS = (
    "enum_values",
    "genvars",
    "functions",
    "tasks",
    "arguments",
    "generate_blocks",
    "typedefs",
    "union_fields",
)
ALL_GROUPS = (
    "signals",
    "ports",
    "instances",
    "struct",
    "interface",
    *LOW_RISK_GROUPS,
)
LOW_RISK_ORACLE = {
    "enum_values": (2, 5),
    "genvars": (1, 5),
    "functions": (1, 3),
    "tasks": (1, 2),
    "arguments": (3, 6),
    "generate_blocks": (1, 1),
    "typedefs": (2, 9),
    "union_fields": (2, 5),
}


class ProjectRootLowRiskTests(unittest.TestCase):
    maxDiff = None

    def _temporary_root(self) -> Path:
        temporary = tempfile.TemporaryDirectory(prefix="rtl-obfuscation-t030-")
        self.addCleanup(temporary.cleanup)
        return Path(temporary.name)

    def _run(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "rtl_obfuscator.rewrite", *arguments],
            cwd=REPOSITORY,
            capture_output=True,
            text=True,
            check=False,
        )

    def _encrypt(
        self,
        root: Path,
        project_root: Path,
        top: str,
        groups: tuple[str, ...] | None,
        *,
        file_maps: bool = False,
    ) -> tuple[subprocess.CompletedProcess[str], dict, dict]:
        arguments = [
            "encrypt-project",
            "--project-root",
            str(project_root),
            "--top",
            top,
            "--output-dir",
            str(root / "gate"),
            "--map",
            str(root / "mapping.json"),
            "--metrics",
            str(root / "metrics.json"),
            "--name-length",
            "8",
        ]
        if file_maps:
            arguments.extend(("--file-map-dir", str(root / "maps")))
        for group in groups or ():
            arguments.extend(("--category", group))
        completed = self._run(*arguments)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return (
            completed,
            json.loads((root / "mapping.json").read_text()),
            json.loads((root / "metrics.json").read_text()),
        )

    @staticmethod
    def _normalized_entries(mapping: dict) -> list[dict]:
        return [
            {
                "category": item["category"],
                "scope": item["scope"],
                "original_name": item["original_name"],
                "declaration": item["declaration"],
                "references": item["references"],
                "occurrences": item["occurrences"],
            }
            for item in mapping["entries"]
        ]

    @staticmethod
    def _manifest(root: Path, files: list[str]) -> str:
        content = "".join(
            f"{hashlib.sha256((root / path).read_bytes()).hexdigest()}  {path}\n"
            for path in sorted(files)
        )
        return hashlib.sha256(content.encode()).hexdigest()

    def test_each_low_risk_group_exact_oracle(self) -> None:
        for group, (entries, tokens) in LOW_RISK_ORACLE.items():
            root = self._temporary_root()
            completed, mapping, metrics = self._encrypt(
                root, FIXTURE, "lowrisk_top", (group,)
            )
            self.assertEqual(
                json.loads(completed.stdout),
                {"files": 2, "mapping_entries": entries, "modified_tokens": tokens},
            )
            self.assertEqual(mapping["selected_groups"], [group])
            self.assertTrue(all("decoy" not in item["scope"] for item in mapping["entries"]))
            self.assertEqual(metrics["symbols"]["coverage"], 1.0)
            self.assertEqual(metrics["occurrences"]["coverage"], 1.0)
            self.assertEqual(metrics["effective_coverage"], 1.0)
            self.assertEqual(metrics["plaintext_leakage_rate"], 0.0)

        source_root = self._temporary_root()
        (source_root / "defs.svh").write_text(
            "`define T030_DECLARE_FUNCTION function automatic logic macro_function(input logic value); macro_function = value; endfunction\n"
        )
        (source_root / "top.sv").write_text(
            "`include \"defs.svh\"\n"
            "module macro_lowrisk_top(input logic value_i, output logic value_o);\n"
            "    `T030_DECLARE_FUNCTION\n"
            "    always_comb value_o = macro_function(value_i);\n"
            "endmodule\n"
        )
        report_root = self._temporary_root()
        report_path = report_root / "report.json"
        inspected = self._run(
            "inspect-project",
            "--project-root",
            str(source_root),
            "--top",
            "macro_lowrisk_top",
            "--report",
            str(report_path),
            "--category",
            "functions",
        )
        self.assertEqual(inspected.returncode, 0, inspected.stderr)
        report = json.loads(report_path.read_text())
        self.assertEqual(report["inventory"]["eligible"], [])
        self.assertEqual(len(report["inventory"]["preserved"]), 1)
        self.assertEqual(report["inventory"]["preserved"][0]["reason"], "macro_expansion")
        self.assertIsNone(report["inventory"]["preserved"][0]["declaration"])

        encrypted_root = self._temporary_root()
        completed, mapping, metrics = self._encrypt(
            encrypted_root, source_root, "macro_lowrisk_top", ("functions",)
        )
        self.assertEqual(
            json.loads(completed.stdout),
            {"files": 2, "mapping_entries": 0, "modified_tokens": 0},
        )
        self.assertEqual(mapping["entries"], [])
        self.assertEqual(mapping["preserved"][0]["reason"], "macro_expansion")
        self.assertEqual(metrics["effective_coverage"], 1.0)
        restored = encrypted_root / "restored"
        decrypted = self._run(
            "decrypt-project",
            "--gate-dir",
            str(encrypted_root / "gate"),
            "--map",
            str(encrypted_root / "mapping.json"),
            "--output-dir",
            str(restored),
        )
        self.assertEqual(decrypted.returncode, 0, decrypted.stderr)
        self.assertTrue(
            all(
                (source_root / relative).read_bytes()
                == (restored / relative).read_bytes()
                for relative in mapping["files"]
            )
        )

    def test_fixture_combined_mapping_v3_exact_oracle(self) -> None:
        root = self._temporary_root()
        completed, mapping, _ = self._encrypt(
            root, FIXTURE, "lowrisk_top", LOW_RISK_GROUPS, file_maps=True
        )
        self.assertEqual(
            json.loads(completed.stdout),
            {"files": 2, "mapping_entries": 13, "modified_tokens": 36},
        )
        self.assertEqual(mapping["selected_groups"], list(LOW_RISK_GROUPS))
        self.assertEqual(mapping["selected_categories"], list(LOW_RISK_GROUPS))
        digest = hashlib.sha256(
            json.dumps(
                self._normalized_entries(mapping),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        self.assertEqual(
            digest, "7b7c98400cc47b31f4f3935e6f045c0fd7fc69bb50e63ea25fbbc139780957d7"
        )
        self.assertEqual(mapping["input_manifest_sha256"], self._manifest(FIXTURE, mapping["files"]))
        self.assertEqual(mapping["gate_manifest_sha256"], self._manifest(root / "gate", mapping["files"]))

    def test_fixture_gate_reinspect_matches_mapping(self) -> None:
        root = self._temporary_root()
        _, mapping, _ = self._encrypt(
            root, FIXTURE, "lowrisk_top", LOW_RISK_GROUPS
        )
        report_path = root / "gate-report.json"
        completed = self._run(
            "inspect-project",
            "--project-root",
            str(root / "gate"),
            "--top",
            "lowrisk_top",
            "--report",
            str(report_path),
            *sum((["--category", group] for group in LOW_RISK_GROUPS), []),
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        report = json.loads(report_path.read_text())
        self.assertEqual(len(report["inventory"]["eligible"]), 13)
        self.assertEqual(sum(item["occurrences"] for item in report["inventory"]["eligible"]), 36)
        self.assertEqual(report["reachable"]["modules"], mapping["closure"]["modules"])
        self.assertEqual(report["compile"]["parse_errors"], 0)
        self.assertEqual(report["compile"]["semantic_errors"], 0)

    def test_fixture_decrypt_byte_identical(self) -> None:
        root = self._temporary_root()
        completed, mapping, _ = self._encrypt(
            root, FIXTURE, "lowrisk_top", LOW_RISK_GROUPS
        )
        restored = root / "restored"
        completed = self._run(
            "decrypt-project",
            "--gate-dir",
            str(root / "gate"),
            "--map",
            str(root / "mapping.json"),
            "--output-dir",
            str(restored),
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout), {"files": 2, "mapping_entries": 13, "modified_tokens": 36})
        for relative in mapping["files"]:
            self.assertEqual((FIXTURE / relative).read_bytes(), (restored / relative).read_bytes())

    def test_unreachable_decoy_unchanged(self) -> None:
        root = self._temporary_root()
        _, mapping, _ = self._encrypt(root, FIXTURE, "lowrisk_top", LOW_RISK_GROUPS)
        gold = (FIXTURE / "child.sv").read_bytes()
        gate = (root / "gate" / "child.sv").read_bytes()
        marker = b"module unreachable_lowrisk_decoy"
        self.assertEqual(gold[gold.index(marker) :], gate[gate.index(marker) :])
        self.assertEqual(mapping["files"], ["child.sv", "top.sv"])
        self.assertFalse(any("unreachable_lowrisk_decoy" in json.dumps(item) for item in mapping["entries"]))

    def test_default_profile_remains_five_groups(self) -> None:
        fixture_root = self._temporary_root()
        completed, mapping, _ = self._encrypt(fixture_root, FIXTURE, "lowrisk_top", None)
        self.assertEqual(json.loads(completed.stdout), {"files": 2, "mapping_entries": 9, "modified_tokens": 26})
        self.assertEqual(mapping["selected_groups"], ["signals", "ports", "instances", "struct", "interface"])
        fifo_root = self._temporary_root()
        completed, mapping, _ = self._encrypt(fifo_root, FIFO, "fifo_top", None)
        self.assertEqual(json.loads(completed.stdout), {"files": 4, "mapping_entries": 50, "modified_tokens": 195})
        self.assertEqual(mapping["selected_groups"], ["signals", "ports", "instances", "struct", "interface"])

    def test_debug_runs_thirteen_groups(self) -> None:
        root = self._temporary_root()
        completed = self._run(
            "encrypt-project",
            "--project-root",
            str(FIXTURE),
            "--top",
            "lowrisk_top",
            "--debug",
            str(root / "debug"),
            "--name-length",
            "8",
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        summary = json.loads(completed.stdout)
        self.assertEqual(summary["mode"], "project-root")
        self.assertEqual(summary["category_count"], 13)
        self.assertEqual([run["category"] for run in summary["runs"]], list(ALL_GROUPS))
        expected = {
            "signals": (4, 14),
            "ports": (3, 9),
            "instances": (1, 1),
            "struct": (1, 2),
            "interface": (0, 0),
            **LOW_RISK_ORACLE,
        }
        for run in summary["runs"]:
            self.assertEqual((run["mapping_entries"], run["modified_tokens"]), expected[run["category"]])
            category_root = root / "debug" / run["category"]
            self.assertTrue((category_root / "gate" / "design.f").is_file())
            self.assertTrue((category_root / "mapping.json").is_file())
            self.assertTrue((category_root / "metrics.json").is_file())
            self.assertTrue((category_root / "maps").is_dir())

    def test_fifo_low_risk_matches_legacy_ranges(self) -> None:
        project_root = self._temporary_root()
        _, project_mapping, _ = self._encrypt(
            project_root, FIFO, "fifo_top", LOW_RISK_GROUPS
        )
        legacy_root = self._temporary_root()
        arguments = [
            "encrypt-project",
            "--filelist",
            str(FIFO / "design.f"),
            "--source-root",
            str(FIFO),
            "--output-dir",
            str(legacy_root / "gate"),
            "--map",
            str(legacy_root / "mapping.json"),
            "--metrics",
            str(legacy_root / "metrics.json"),
            "--top",
            "fifo_top",
            "--name-length",
            "8",
        ]
        for group in LOW_RISK_GROUPS:
            arguments.extend(("--category", group))
        completed = self._run(*arguments)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        legacy_mapping = json.loads((legacy_root / "mapping.json").read_text())
        project_keys = sorted(
            (
                item["category"],
                item["scope"],
                item["original_name"],
                json.dumps(item["declaration"], sort_keys=True),
                json.dumps(item["references"], sort_keys=True),
                item["occurrences"],
            )
            for item in project_mapping["entries"]
        )
        legacy_keys = sorted(
            (
                item["category"],
                item["scope"],
                item["original_name"],
                json.dumps(item["declaration"], sort_keys=True),
                json.dumps(item["references"], sort_keys=True),
                len(item["references"]) + 1,
            )
            for item in legacy_mapping["entries"]
        )
        self.assertEqual(project_keys, legacy_keys)

    def test_fifo_explicit_thirteen_group_summary(self) -> None:
        root = self._temporary_root()
        completed, mapping, _ = self._encrypt(root, FIFO, "fifo_top", ALL_GROUPS)
        self.assertEqual(json.loads(completed.stdout), {"files": 4, "mapping_entries": 68, "modified_tokens": 244})
        self.assertEqual(mapping["selected_groups"], list(ALL_GROUPS))
        counts = Counter(item["category"] for item in mapping["entries"])
        self.assertEqual(
            counts,
            Counter({
                "signals": 14,
                "ports": 17,
                "instances": 2,
                "struct_types": 2,
                "struct_fields": 2,
                "interfaces": 1,
                "interface_instances": 1,
                "interface_ports": 9,
                "modports": 2,
                "enum_values": 3,
                "genvars": 2,
                "functions": 2,
                "tasks": 1,
                "arguments": 4,
                "generate_blocks": 2,
                "typedefs": 2,
                "union_fields": 2,
            }),
        )

    def test_per_file_mapping_covers_all_occurrences(self) -> None:
        root = self._temporary_root()
        _, mapping, _ = self._encrypt(
            root, FIXTURE, "lowrisk_top", LOW_RISK_GROUPS, file_maps=True
        )
        global_occurrences = {
            (record["file"], record["start"], record["end"])
            for entry in mapping["entries"]
            for record in [entry["declaration"], *entry["references"]]
        }
        file_occurrences = set()
        for map_file in (root / "maps").glob("*.json"):
            payload = json.loads(map_file.read_text())
            for item in payload["entries"]:
                file_occurrences.add(
                    (payload["file"], item["range"]["start"], item["range"]["end"])
                )
        self.assertEqual(file_occurrences, global_occurrences)

    def test_mapping_v3_rejects_low_risk_category_tampering(self) -> None:
        root = self._temporary_root()
        _, mapping, _ = self._encrypt(root, FIXTURE, "lowrisk_top", LOW_RISK_GROUPS)
        tampered = json.loads(json.dumps(mapping))
        tampered["entries"][0]["category"] = "signals"
        tampered_path = root / "tampered.json"
        tampered_path.write_text(json.dumps(tampered, indent=2) + "\n")
        completed = self._run(
            "decrypt-project",
            "--gate-dir",
            str(root / "gate"),
            "--map",
            str(tampered_path),
            "--output-dir",
            str(root / "tampered-restored"),
        )
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(completed.stdout, "")
        self.assertFalse((root / "tampered-restored").exists())

    def test_formal_positive_and_functional_negative(self) -> None:
        root = self._temporary_root()
        _, mapping, _ = self._encrypt(root, FIFO, "fifo_top", ALL_GROUPS)
        positive = subprocess.run(
            [
                sys.executable,
                "scripts/formal_equivalence.py",
                "--gold-filelist",
                str(FIFO / "design.f"),
                "--gold-root",
                str(FIFO),
                "--gate-filelist",
                str(root / "gate" / "design.f"),
                "--gate-root",
                str(root / "gate"),
                "--top",
                "fifo_top",
            ],
            cwd=REPOSITORY,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(positive.returncode, 0, positive.stderr)
        self.assertEqual(json.loads(positive.stdout)["formal_equivalence"], "pass")

        negative = root / "negative"
        shutil.copytree(root / "gate", negative)
        count = next(item for item in mapping["entries"] if item["category"] == "signals" and item["original_name"] == "count")
        gate_file = negative / "fifo_ctrl.sv"
        source = gate_file.read_text()
        needle = f"{count['renamed_name']} <= {count['renamed_name']} + 1'b1;"
        self.assertEqual(source.count(needle), 1)
        gate_file.write_text(source.replace(needle, f"{count['renamed_name']} <= {count['renamed_name']} + 2;", 1))
        failed = subprocess.run(
            [
                sys.executable,
                "scripts/formal_equivalence.py",
                "--gold-filelist",
                str(FIFO / "design.f"),
                "--gold-root",
                str(FIFO),
                "--gate-filelist",
                str(negative / "design.f"),
                "--gate-root",
                str(negative),
                "--top",
                "fifo_top",
            ],
            cwd=REPOSITORY,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(failed.returncode, 0)

    def test_legacy_filelist_v2_unchanged(self) -> None:
        root = self._temporary_root()
        completed = self._run(
            "encrypt-project",
            "--filelist",
            str(FIFO / "design.f"),
            "--source-root",
            str(FIFO),
            "--output-dir",
            str(root / "gate"),
            "--map",
            str(root / "mapping.json"),
            "--metrics",
            str(root / "metrics.json"),
            "--top",
            "fifo_top",
            "--category",
            "enum_values",
            "--name-length",
            "8",
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads((root / "mapping.json").read_text())["version"], 2)
        completed = self._run(
            "decrypt-project",
            "--gate-dir",
            str(root / "gate"),
            "--source-root",
            str(FIFO),
            "--map",
            str(root / "mapping.json"),
            "--output-dir",
            str(root / "restored"),
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        missing_source = self._run(
            "decrypt-project",
            "--gate-dir",
            str(root / "gate"),
            "--map",
            str(root / "mapping.json"),
            "--output-dir",
            str(root / "missing-source"),
        )
        self.assertEqual(missing_source.returncode, 2)


if __name__ == "__main__":
    unittest.main()
