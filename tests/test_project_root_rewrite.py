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

from rtl_obfuscator import project


REPOSITORY = Path(__file__).resolve().parents[1]
FIXTURES = REPOSITORY / "tests" / "fixtures" / "t027_project_root"
INTEGRATION = FIXTURES / "integration"
FIFO = REPOSITORY / "rtl_samples" / "example_fifo"
GROUPS = ("signals", "ports", "instances", "struct", "interface")
GROUP_ORACLE = {
    "signals": (7, 27),
    "ports": (12, 37),
    "instances": (2, 2),
    "struct": (3, 13),
    "interface": (7, 21),
}
DEBUG_GROUPS = (
    "signals",
    "parameters",
    "enum_values",
    "genvars",
    "functions",
    "tasks",
    "arguments",
    "instances",
    "generate_blocks",
    "typedefs",
    "struct_types",
    "struct_fields",
    "union_fields",
)
DEBUG_ORACLE = {
    "signals": (7, 27),
    "parameters": (0, 0),
    "enum_values": (0, 0),
    "genvars": (0, 0),
    "functions": (0, 0),
    "tasks": (0, 0),
    "arguments": (0, 0),
    "instances": (2, 2),
    "generate_blocks": (0, 0),
    "typedefs": (0, 0),
    "struct_types": (0, 0),
    "struct_fields": (0, 0),
    "union_fields": (0, 0),
}


class ProjectRootRewriteTests(unittest.TestCase):
    maxDiff = None

    def _temporary_root(self) -> Path:
        temporary = tempfile.TemporaryDirectory()
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
        project_root: Path = INTEGRATION,
        top: str = "project_top",
        groups: tuple[str, ...] = GROUPS,
        *,
        file_maps: bool = False,
    ) -> tuple[Path, subprocess.CompletedProcess[str], dict, dict]:
        root = self._temporary_root()
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
        for group in groups:
            arguments.extend(("--category", group))
        completed = self._run(*arguments)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        mapping = json.loads((root / "mapping.json").read_text())
        metrics = json.loads((root / "metrics.json").read_text())
        return root, completed, mapping, metrics

    def _assert_group(self, group: str) -> None:
        _, completed, mapping, metrics = self._encrypt(groups=(group,))
        entries, tokens = GROUP_ORACLE[group]
        self.assertEqual(
            json.loads(completed.stdout),
            {"files": 6, "mapping_entries": entries, "modified_tokens": tokens},
        )
        if group in {"ports", "struct", "interface"}:
            self.assertEqual(mapping["version"], 4)
            self.assertEqual(mapping["profile"], "manual")
        else:
            self.assertEqual(mapping["selected_groups"], [group])
        self.assertEqual(len(mapping["entries"]), entries)
        self.assertEqual(sum(item["occurrences"] for item in mapping["entries"]), tokens)
        self.assertEqual(metrics["symbols"]["coverage"], 1.0)
        self.assertEqual(metrics["occurrences"]["coverage"], 1.0)
        self.assertEqual(metrics["plaintext_leakage_rate"], 0.0)

    @staticmethod
    def _manifest(root: Path, files: list[str]) -> str:
        manifest = "".join(
            f"{hashlib.sha256((root / path).read_bytes()).hexdigest()}  {path}\n"
            for path in sorted(files)
        )
        return hashlib.sha256(manifest.encode()).hexdigest()

    def _assert_byte_identical(self, gold: Path, restored: Path, files: list[str]) -> None:
        self.assertTrue(
            all((gold / path).read_bytes() == (restored / path).read_bytes() for path in files)
        )

    def test_integration_signals_group(self) -> None:
        self._assert_group("signals")

    def test_integration_ports_group(self) -> None:
        self._assert_group("ports")

    def test_integration_instances_group(self) -> None:
        self._assert_group("instances")

    def test_integration_struct_group(self) -> None:
        self._assert_group("struct")

    def test_integration_interface_group(self) -> None:
        self._assert_group("interface")

    def test_integration_combined_mapping_v4_exact_oracle(self) -> None:
        root, completed, mapping, metrics = self._encrypt(file_maps=True)
        self.assertEqual(
            json.loads(completed.stdout),
            {"files": 6, "mapping_entries": 31, "modified_tokens": 100},
        )
        self.assertEqual(
            list(mapping),
            [
                "version",
                "mode",
                "profile",
                "top",
                "requested_categories",
                "selected_categories",
                "files",
                "source_files",
                "header_files",
                "closure",
                "compile_context",
                "entries",
                "preserved",
                "skipped",
                "name_length",
                "input_manifest_sha256",
                "gate_manifest_sha256",
            ],
        )
        self.assertEqual(mapping["version"], 4)
        self.assertEqual(mapping["mode"], "project-root")
        self.assertEqual(mapping["profile"], "manual")
        self.assertEqual(mapping["requested_categories"], list(GROUPS))
        self.assertEqual(
            mapping["selected_categories"],
            [
                "signals",
                "instances",
                "struct_types",
                "struct_fields",
                "ports",
                "interfaces",
                "interface_instances",
                "interface_ports",
                "modports",
            ],
        )
        report, _, success = project.analyze_project(
            project_root=INTEGRATION, top="project_top", categories=GROUPS
        )
        self.assertTrue(success)
        classification = report["classification"]
        selected = set(mapping["selected_categories"])
        classification_items = [
            *classification["default_profile"]["items"],
            *classification["manual_multi_module"]["items"],
        ]
        expected = sorted(
            [
                {
                    "category": item["category"],
                    "scope": item["scope"],
                    "original_name": item["name"],
                    "declaration": item["declaration"],
                    "references": item["references"],
                    "occurrences": item["occurrences"],
                }
                for item in classification_items
                if item["category"] in selected and item.get("reason") is None
            ],
            key=lambda item: (
                item["declaration"]["file"],
                item["declaration"]["start"],
                item["category"],
                item["scope"],
                item["original_name"],
            ),
        )
        actual = [
            {key: value for key, value in item.items() if key != "renamed_name"}
            for item in mapping["entries"]
        ]
        self.assertEqual(actual, expected)
        self.assertEqual(len(mapping["preserved"]), 8)
        renamed = [item["renamed_name"] for item in mapping["entries"]]
        self.assertEqual(len(renamed), len(set(renamed)))
        self.assertTrue(all(len(name) == 8 for name in renamed))
        self.assertEqual(mapping["input_manifest_sha256"], self._manifest(INTEGRATION, mapping["files"]))
        self.assertEqual(mapping["gate_manifest_sha256"], self._manifest(root / "gate", mapping["files"]))
        self.assertEqual(metrics["symbols"], {"renamed": 31, "eligible": 31, "coverage": 1.0})
        self.assertEqual(metrics["occurrences"], {"renamed": 100, "eligible": 100, "coverage": 1.0})
        occurrences = {
            (str(path.relative_to(root / "maps")), record["range"]["start"], record["range"]["end"])
            for path in (root / "maps").rglob("*.json")
            for record in json.loads(path.read_text())["entries"]
        }
        self.assertEqual(len(occurrences), 100)
        self.assertFalse((root / "maps" / "include" / "common.json").exists())

    def test_integration_gate_reinspect_matches_renamed_inventory(self) -> None:
        root, _, mapping, _ = self._encrypt()
        completed = self._run(
            "inspect-project",
            "--project-root",
            str(root / "gate"),
            "--top",
            "project_top",
            "--report",
            str(root / "gate-report.json"),
            *sum((["--category", group] for group in GROUPS), []),
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        report = json.loads((root / "gate-report.json").read_text())
        self.assertEqual(len(report["inventory"]["eligible"]), 31)
        self.assertEqual(sum(item["occurrences"] for item in report["inventory"]["eligible"]), 100)
        self.assertEqual(report["reachable"]["modules"], mapping["closure"]["modules"])
        self.assertEqual(len(report["reachable"]["interfaces"]), 1)
        self.assertEqual(report["compile"]["parse_errors"], 0)
        self.assertEqual(report["compile"]["semantic_errors"], 0)

    def test_integration_decrypt_is_byte_identical(self) -> None:
        root, _, mapping, _ = self._encrypt()
        completed = self._run(
            "decrypt-project",
            "--gate-dir",
            str(root / "gate"),
            "--map",
            str(root / "mapping.json"),
            "--output-dir",
            str(root / "restored"),
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout), {"files": 6, "mapping_entries": 31, "modified_tokens": 100})
        self._assert_byte_identical(INTEGRATION, root / "restored", mapping["files"])

    def test_unreachable_same_file_module_unchanged_and_unrelated_absent(self) -> None:
        root, _, mapping, _ = self._encrypt()
        gold = (INTEGRATION / "rtl" / "top_bundle.sv").read_bytes()
        gate = (root / "gate" / "rtl" / "top_bundle.sv").read_bytes()
        marker = b"module same_file_unused"
        self.assertEqual(gold[gold.index(marker) :], gate[gate.index(marker) :])
        self.assertNotIn("rtl/unused/unrelated.sv", mapping["files"])
        self.assertFalse((root / "gate" / "rtl" / "unused" / "unrelated.sv").exists())
        self.assertEqual(
            (INTEGRATION / "include" / "common.svh").read_bytes(),
            (root / "gate" / "include" / "common.svh").read_bytes(),
        )

    def test_top_abi_zero_entry_round_trip(self) -> None:
        root, completed, mapping, metrics = self._encrypt(
            FIXTURES / "top_abi", "abi_top", ()
        )
        self.assertEqual(json.loads(completed.stdout), {"files": 3, "mapping_entries": 0, "modified_tokens": 0})
        self.assertEqual(mapping["entries"], [])
        self.assertEqual(
            {(item["category"], item["name"], item["reason"]) for item in mapping["preserved"]},
            {
                ("modules", "abi_top", "top_abi"),
                ("ports", "packet_i", "top_port"),
                ("ports", "bus", "top_port"),
                ("ports", "result_o", "top_port"),
                ("struct_types", "abi_packet_t", "top_abi_type"),
                ("struct_fields", "abi_field", "top_abi_type"),
                ("interfaces", "abi_if", "top_abi_type"),
                ("interface_ports", "abi_signal", "top_abi_type"),
                ("modports", "sink", "top_abi_type"),
            },
        )
        self.assertEqual(metrics["effective_coverage"], 1.0)
        completed = self._run("decrypt-project", "--gate-dir", str(root / "gate"), "--map", str(root / "mapping.json"), "--output-dir", str(root / "restored"))
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self._assert_byte_identical(FIXTURES / "top_abi", root / "restored", mapping["files"])

        boolean_preserved = json.loads(json.dumps(mapping))
        single = next(
            item for item in boolean_preserved["preserved"]
            if item["occurrences"] == 1
        )
        single["occurrences"] = True
        (root / "boolean-preserved.json").write_text(
            json.dumps(boolean_preserved, indent=2) + "\n"
        )
        completed = self._run(
            "decrypt-project",
            "--gate-dir",
            str(root / "gate"),
            "--map",
            str(root / "boolean-preserved.json"),
            "--output-dir",
            str(root / "boolean-preserved-restored"),
        )
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(completed.stdout, "")
        self.assertFalse((root / "boolean-preserved-restored").exists())

    def test_macro_generated_identifier_zero_entry_round_trip(self) -> None:
        root, completed, mapping, _ = self._encrypt(
            FIXTURES / "macro_identifier", "macro_top", ()
        )
        self.assertEqual(json.loads(completed.stdout), {"files": 2, "mapping_entries": 0, "modified_tokens": 0})
        self.assertEqual(mapping["entries"], [])
        macro_signal = next(item for item in mapping["preserved"] if item["name"] == "macro_signal")
        self.assertEqual(macro_signal["reason"], "macro_expansion")
        self.assertIsNone(macro_signal["declaration"])
        completed = self._run("decrypt-project", "--gate-dir", str(root / "gate"), "--map", str(root / "mapping.json"), "--output-dir", str(root / "restored"))
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self._assert_byte_identical(FIXTURES / "macro_identifier", root / "restored", mapping["files"])

    def test_mapping_v3_rejects_mutated_gate_manifest(self) -> None:
        root, _, mapping, _ = self._encrypt()
        gate_file = root / "gate" / mapping["files"][0]
        original = gate_file.read_bytes()
        gate_file.write_bytes(original + b"\n")
        completed = self._run("decrypt-project", "--gate-dir", str(root / "gate"), "--map", str(root / "mapping.json"), "--output-dir", str(root / "manifest-restored"))
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(completed.stdout, "")
        self.assertFalse((root / "manifest-restored").exists())

        gate_file.write_bytes(original)
        overflow = json.loads(json.dumps(mapping))
        struct_records = [
            record
            for item in overflow["entries"]
            for record in [item["declaration"], *item["references"]]
            if record["file"] == "rtl/types/structs.sv"
        ]
        struct_records[-1]["end"] = (
            root / "gate" / "rtl" / "types" / "structs.sv"
        ).stat().st_size + 100
        (root / "overflow.json").write_text(json.dumps(overflow, indent=2) + "\n")
        completed = self._run(
            "decrypt-project", "--gate-dir", str(root / "gate"),
            "--map", str(root / "overflow.json"), "--output-dir", str(root / "overflow-restored"),
        )
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(completed.stdout, "")
        self.assertFalse((root / "overflow-restored").exists())

        shifted = json.loads(json.dumps(mapping))
        interface = next(
            item for item in shifted["entries"]
            if item["category"] == "interfaces"
            and item["original_name"] == "internal_if"
        )
        interface["declaration"]["start"] += 1
        interface["declaration"]["end"] += 1
        (root / "shifted-range.json").write_text(
            json.dumps(shifted, indent=2) + "\n"
        )
        completed = self._run(
            "decrypt-project", "--gate-dir", str(root / "gate"),
            "--map", str(root / "shifted-range.json"), "--output-dir", str(root / "shifted-restored"),
        )
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(completed.stdout, "")
        self.assertFalse((root / "shifted-restored").exists())

        boolean_entry = json.loads(json.dumps(mapping))
        single = next(
            item for item in boolean_entry["entries"] if item["occurrences"] == 1
        )
        single["occurrences"] = True
        (root / "boolean-entry.json").write_text(
            json.dumps(boolean_entry, indent=2) + "\n"
        )
        completed = self._run(
            "decrypt-project", "--gate-dir", str(root / "gate"),
            "--map", str(root / "boolean-entry.json"), "--output-dir", str(root / "boolean-entry-restored"),
        )
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(completed.stdout, "")
        self.assertFalse((root / "boolean-entry-restored").exists())

        instance = next(item for item in mapping["entries"] if item["category"] == "instances")
        instance_file = root / "gate" / instance["declaration"]["file"]
        source = instance_file.read_bytes()
        renamed = instance["renamed_name"].encode()
        self.assertEqual(source.count(renamed), 1)
        instance_file.write_bytes(source.replace(renamed, instance["original_name"].encode(), 1))
        mapping["gate_manifest_sha256"] = self._manifest(root / "gate", mapping["files"])
        (root / "mapping-audit.json").write_text(json.dumps(mapping, indent=2) + "\n")
        completed = self._run("decrypt-project", "--gate-dir", str(root / "gate"), "--map", str(root / "mapping-audit.json"), "--output-dir", str(root / "audit-restored"))
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(completed.stdout, "")
        self.assertFalse((root / "audit-restored").exists())

    def test_project_root_debug_runs_thirteen_groups(self) -> None:
        root = self._temporary_root()
        completed = self._run(
            "encrypt-project",
            "--project-root",
            str(INTEGRATION),
            "--top",
            "project_top",
            "--debug",
            str(root / "debug"),
            "--name-length",
            "8",
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        summary = json.loads(completed.stdout)
        self.assertEqual(summary["mode"], "project-root")
        self.assertEqual(summary["category_count"], 13)
        self.assertEqual([run["category"] for run in summary["runs"]], list(DEBUG_GROUPS))
        for run in summary["runs"]:
            self.assertEqual((run["mapping_entries"], run["modified_tokens"]), DEBUG_ORACLE[run["category"]])
            category_root = root / "debug" / run["category"]
            self.assertTrue((category_root / "gate" / "design.f").is_file())
            self.assertTrue((category_root / "mapping.json").is_file())
            self.assertTrue((category_root / "metrics.json").is_file())
            self.assertTrue((category_root / "maps").is_dir())

    def test_fifo_filelist_manual_category_is_bounded(self) -> None:
        root = self._temporary_root()
        completed = self._run(
            "encrypt-project", "--filelist", str(FIFO / "design.f"), "--source-root", str(FIFO),
            "--output-dir", str(root / "gate"), "--map", str(root / "mapping.json"),
            "--metrics", str(root / "metrics.json"), "--top", "fifo_top", "--name-length", "8",
            "--category", "ports",
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        mapping = json.loads((root / "mapping.json").read_text())
        self.assertEqual(mapping["version"], 4)
        self.assertEqual(mapping["profile"], "manual")
        self.assertEqual(mapping["closure"]["policy"], "filelist_bounded")
        self.assertTrue((root / "gate").is_dir())

    def test_fifo_project_root_mapping_exact_oracle(self) -> None:
        root, completed, mapping, metrics = self._encrypt(FIFO, "fifo_top")
        self.assertEqual(json.loads(completed.stdout), {"files": 4, "mapping_entries": 41, "modified_tokens": 174})
        counts = Counter((item["category"] for item in mapping["entries"]))
        tokens = Counter()
        for item in mapping["entries"]:
            tokens[item["category"]] += item["occurrences"]
        self.assertEqual(
            counts,
            Counter({"signals": 14, "ports": 9, "instances": 2, "struct_types": 2, "struct_fields": 2, "interfaces": 1, "interface_ports": 9, "modports": 2}),
        )
        self.assertEqual(
            tokens,
            Counter({"signals": 67, "ports": 43, "instances": 2, "struct_types": 5, "struct_fields": 4, "interfaces": 3, "interface_ports": 47, "modports": 3}),
        )
        self.assertEqual(mapping["compile_context"]["compile_order"], ["fifo_if.sv", "fifo_storage.sv", "fifo_ctrl.sv", "fifo_top.sv"])
        self.assertEqual(metrics["symbols"], {"renamed": 41, "eligible": 41, "coverage": 1.0})
        self.assertEqual(metrics["occurrences"], {"renamed": 174, "eligible": 174, "coverage": 1.0})
        completed = self._run("decrypt-project", "--gate-dir", str(root / "gate"), "--map", str(root / "mapping.json"), "--output-dir", str(root / "restored"))
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self._assert_byte_identical(FIFO, root / "restored", mapping["files"])

    @unittest.skip(
        "example_fifo now uses fifo_if.consumer ctrl; the repository's Icarus/Yosys formal path does not support interface module ports"
    )
    def test_fifo_project_root_formal_positive(self) -> None:
        root, _, _, _ = self._encrypt(FIFO, "fifo_top")
        completed = subprocess.run(
            [sys.executable, "scripts/formal_equivalence.py", "--gold-filelist", str(FIFO / "design.f"), "--gold-root", str(FIFO), "--gate-filelist", str(root / "gate" / "design.f"), "--gate-root", str(root / "gate"), "--top", "fifo_top"],
            cwd=REPOSITORY, capture_output=True, text=True, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["formal_equivalence"], "pass")

    @unittest.skip(
        "example_fifo now uses fifo_if.consumer ctrl; the repository's Icarus/Yosys formal path does not support interface module ports"
    )
    def test_fifo_project_root_formal_functional_negative(self) -> None:
        root, _, mapping, _ = self._encrypt(FIFO, "fifo_top")
        negative = root / "negative"
        shutil.copytree(root / "gate", negative)
        count = next(item for item in mapping["entries"] if item["category"] == "signals" and item["original_name"] == "count")
        gate_file = negative / "fifo_ctrl.sv"
        source = gate_file.read_text()
        needle = f"{count['renamed_name']} <= {count['renamed_name']} + 1'b1;"
        self.assertEqual(source.count(needle), 1)
        gate_file.write_text(source.replace(needle, f"{count['renamed_name']} <= {count['renamed_name']} + 2;", 1))
        completed = subprocess.run(
            [sys.executable, "scripts/formal_equivalence.py", "--gold-filelist", str(FIFO / "design.f"), "--gold-root", str(FIFO), "--gate-filelist", str(negative / "design.f"), "--gate-root", str(negative), "--top", "fifo_top"],
            cwd=REPOSITORY, capture_output=True, text=True, check=False,
        )
        self.assertNotEqual(completed.returncode, 0)

    def test_legacy_mapping_v2_and_cli_mode_validation(self) -> None:
        root = self._temporary_root()
        completed = self._run(
            "encrypt-project", "--filelist", str(FIFO / "design.f"), "--source-root", str(FIFO),
            "--output-dir", str(root / "gate"), "--map", str(root / "mapping.json"), "--metrics", str(root / "metrics.json"),
            "--top", "fifo_top", "--category", "signals", "--name-length", "8",
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads((root / "mapping.json").read_text())["version"], 2)
        completed = self._run("decrypt-project", "--gate-dir", str(root / "gate"), "--source-root", str(FIFO), "--map", str(root / "mapping.json"), "--output-dir", str(root / "restored"))
        self.assertEqual(completed.returncode, 0, completed.stderr)

        missing_source = self._run("decrypt-project", "--gate-dir", str(root / "gate"), "--map", str(root / "mapping.json"), "--output-dir", str(root / "missing-source"))
        self.assertEqual(missing_source.returncode, 2)
        parameter_category = self._run(
            "encrypt-project", "--project-root", str(INTEGRATION), "--top", "project_top", "--output-dir", str(root / "invalid-gate"),
            "--map", str(root / "invalid-map.json"), "--metrics", str(root / "invalid-metrics.json"), "--category", "parameters", "--name-length", "8",
        )
        self.assertEqual(parameter_category.returncode, 0, parameter_category.stderr)
        self.assertEqual(json.loads((root / "invalid-map.json").read_text())["selected_groups"], ["parameters"])
        conflicting_input = self._run(
            "encrypt-project", "--project-root", str(INTEGRATION), "--filelist", str(FIFO / "design.f"), "--top", "project_top",
            "--output-dir", str(root / "conflict-gate"), "--map", str(root / "conflict-map.json"), "--metrics", str(root / "conflict-metrics.json"), "--name-length", "8",
        )
        self.assertEqual(conflicting_input.returncode, 2)

        map_parent = root / "map-parent"
        map_parent.write_text("not a directory\n")
        partial_gate = root / "partial-gate"
        partial_metrics = root / "partial-metrics.json"
        invalid_parent = self._run(
            "encrypt-project", "--project-root", str(INTEGRATION), "--top", "project_top",
            "--output-dir", str(partial_gate), "--map", str(map_parent / "mapping.json"),
            "--metrics", str(partial_metrics), "--name-length", "8",
        )
        self.assertEqual(invalid_parent.returncode, 2)
        self.assertEqual(invalid_parent.stdout, "")
        self.assertFalse(partial_gate.exists())
        self.assertFalse((map_parent / "mapping.json").exists())
        self.assertFalse(partial_metrics.exists())


if __name__ == "__main__":
    unittest.main()
