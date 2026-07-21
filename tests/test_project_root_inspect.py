from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
FIXTURES = REPOSITORY / "tests" / "fixtures" / "t027_project_root"
RISC = REPOSITORY / "rtl_samples" / "RISC-V-Vector"


class ProjectRootInspectTests(unittest.TestCase):
    maxDiff = None

    def _run(
        self,
        project_root: Path,
        top: str,
        *extra: str,
        report_name: str = "report.json",
    ) -> tuple[subprocess.CompletedProcess[str], dict, bytes]:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        report = Path(temporary.name) / report_name
        command = [
            sys.executable,
            "-m",
            "rtl_obfuscator.rewrite",
            "inspect-project",
            "--project-root",
            str(project_root),
            "--top",
            top,
            "--report",
            str(report),
            *extra,
        ]
        completed = subprocess.run(
            command,
            cwd=REPOSITORY,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertTrue(report.is_file(), completed.stderr)
        report_bytes = report.read_bytes()
        return completed, json.loads(report_bytes), report_bytes

    def _assert_error(self, fixture: str, top: str, code: str) -> None:
        completed, report, _ = self._run(FIXTURES / fixture, top)
        self.assertEqual(completed.returncode, 1, completed.stderr)
        self.assertEqual(report["status"], "error")
        self.assertEqual(len(report["diagnostics"]), 1)
        self.assertEqual(report["diagnostics"][0]["code"], code)
        self.assertEqual(json.loads(completed.stdout)["code"], code)

    def test_integration_discovery_definition_and_closure(self) -> None:
        completed, report, _ = self._run(
            FIXTURES / "integration", "project_top"
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(len(report["candidate_files"]), 7)
        self.assertEqual(len(report["definitions"]), 6)
        self.assertEqual(
            {item["name"] for item in report["definitions"] if item["kind"] == "module"},
            {
                "project_top",
                "project_child",
                "project_leaf",
                "same_file_unused",
                "unrelated",
            },
        )
        self.assertEqual(
            {item["name"] for item in report["definitions"] if item["kind"] == "interface"},
            {"internal_if"},
        )
        self.assertEqual(
            report["reachable"]["modules"],
            ["project_child", "project_leaf", "project_top"],
        )
        self.assertEqual(report["reachable"]["interfaces"], ["internal_if"])
        self.assertEqual(len(report["reachable"]["files"]), 6)
        self.assertNotIn(
            "rtl/unused/unrelated.sv", report["reachable"]["files"]
        )
        self.assertEqual(
            report["compile"]["compile_order"],
            [
                "rtl/bus/internal_if.sv",
                "rtl/types/structs.sv",
                "rtl/core/leaf.sv",
                "rtl/core/child.sv",
                "rtl/top_bundle.sv",
            ],
        )
        self.assertEqual(report["compile"]["parse_errors"], 0)
        self.assertEqual(report["compile"]["semantic_errors"], 0)

    def test_integration_inventory_exact_oracle(self) -> None:
        completed, report, _ = self._run(
            FIXTURES / "integration", "project_top"
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        expected = {
            ("signals", "project_top", "top_signal"): 3,
            ("signals", "project_top", "child_valid"): 3,
            ("signals", "project_top", "child_data"): 3,
            ("signals", "project_child", "child_packet"): 5,
            ("signals", "project_child", "child_signal"): 3,
            ("signals", "project_leaf", "leaf_packet"): 6,
            ("signals", "project_leaf", "leaf_signal"): 4,
            ("instances", "project_top", "u_child"): 1,
            ("instances", "project_child", "u_leaf"): 1,
        }
        actual = {
            (item["category"], item["scope"], item["name"]): item["occurrences"]
            for item in report["inventory"]["eligible"]
        }
        self.assertEqual(actual, expected)
        self.assertEqual(len(actual), 9)
        self.assertEqual(sum(actual.values()), 29)
        self.assertEqual(
            {
                (item["category"], item["name"], item["reason"])
                for item in report["inventory"]["preserved"]
            },
            {
                ("ports", name, "top_port")
                for name in (
                    "top_clk",
                    "top_reset_n",
                    "top_valid_i",
                    "top_data_i",
                    "top_valid_o",
                    "top_data_o",
                )
            }
            | {("interface_instances", "top_bus", "top_interface_instance")},
        )
        forbidden = {"same_file_secret", "unused_i", "unused_o", "u_missing", "value_i"}
        self.assertFalse(
            forbidden
            & {
                item["name"]
                for bucket in report["inventory"].values()
                for item in bucket
            }
        )

    def test_integration_ranges_and_determinism(self) -> None:
        first, report, first_bytes = self._run(
            FIXTURES / "integration", "project_top", report_name="first.json"
        )
        second, _, second_bytes = self._run(
            FIXTURES / "integration", "project_top", report_name="second.json"
        )
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(first.stdout.encode(), second.stdout.encode())
        self.assertEqual(first_bytes, second_bytes)
        all_ranges: dict[str, list[tuple[int, int]]] = {}
        for definition in report["definitions"]:
            source = (FIXTURES / "integration" / definition["file"]).read_bytes()
            self.assertEqual(
                source[definition["start"] : definition["end"]].decode(),
                definition["name"],
            )
        for bucket in report["inventory"].values():
            for item in bucket:
                ranges = (
                    ([] if item["declaration"] is None else [item["declaration"]])
                    + item["references"]
                )
                self.assertEqual(item["occurrences"], len(ranges))
                for source_range in ranges:
                    source = (
                        FIXTURES / "integration" / source_range["file"]
                    ).read_bytes()
                    self.assertEqual(
                        source[source_range["start"] : source_range["end"]].decode(),
                        item["name"],
                    )
                    all_ranges.setdefault(source_range["file"], []).append(
                        (source_range["start"], source_range["end"])
                    )
        for ranges in all_ranges.values():
            ordered = sorted(ranges)
            self.assertEqual(len(ordered), len(set(ordered)))
            self.assertTrue(
                all(a_end <= b_start for (_, a_end), (b_start, _) in zip(ordered, ordered[1:]))
            )

    def test_top_abi_is_preserved(self) -> None:
        completed, report, _ = self._run(FIXTURES / "top_abi", "abi_top")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(report["inventory"]["eligible"], [])
        actual = {
            (item["category"], item["name"], item["reason"])
            for item in report["inventory"]["preserved"]
        }
        self.assertEqual(
            actual,
            {
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
        self.assertEqual(report["compile"]["parse_errors"], 0)
        self.assertEqual(report["compile"]["semantic_errors"], 0)

    def test_macro_generated_identifier_is_preserved(self) -> None:
        completed, report, _ = self._run(
            FIXTURES / "macro_identifier", "macro_top"
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        signal = next(
            item
            for item in report["inventory"]["preserved"]
            if item["category"] == "signals" and item["name"] == "macro_signal"
        )
        self.assertEqual(signal["reason"], "macro_expansion")
        self.assertIsNone(signal["declaration"])
        self.assertNotIn(
            "macro_signal",
            {item["name"] for item in report["inventory"]["eligible"]},
        )
        self.assertEqual(
            {
                (item["name"], item["reason"])
                for item in report["inventory"]["preserved"]
                if item["category"] == "ports"
            },
            {("value_i", "top_port"), ("value_o", "top_port")},
        )

    def test_missing_top_error(self) -> None:
        self._assert_error("missing_top", "not_present", "TOP_NOT_FOUND")

    def test_ambiguous_top_error(self) -> None:
        self._assert_error("ambiguous_top", "duplicate_top", "AMBIGUOUS_TOP")

    def test_missing_module_error(self) -> None:
        self._assert_error(
            "missing_module", "missing_module_top", "UNRESOLVED_MODULE"
        )

    def test_ambiguous_definition_error(self) -> None:
        self._assert_error(
            "ambiguous_definition",
            "ambiguous_definition_top",
            "AMBIGUOUS_DEFINITION",
        )

    def test_missing_include_error(self) -> None:
        self._assert_error(
            "missing_include", "missing_include_top", "MISSING_INCLUDE"
        )

    def test_ambiguous_include_error(self) -> None:
        self._assert_error(
            "ambiguous_include", "ambiguous_include_top", "AMBIGUOUS_INCLUDE"
        )

    def test_unresolved_macro_error(self) -> None:
        self._assert_error(
            "unresolved_macro", "unresolved_macro_top", "UNRESOLVED_MACRO"
        )

    def test_ambiguous_macro_error(self) -> None:
        self._assert_error(
            "ambiguous_macro", "ambiguous_macro_top", "AMBIGUOUS_MACRO"
        )

    def test_explicit_include_dir_resolves_ambiguity(self) -> None:
        completed, report, _ = self._run(
            FIXTURES / "ambiguous_include",
            "ambiguous_include_top",
            "--include-dir",
            "dir_a",
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["compile"]["parse_errors"], 0)
        self.assertEqual(report["compile"]["semantic_errors"], 0)
        self.assertEqual(report["reachable"]["header_files"], ["dir_a/duplicate.svh"])

    def test_command_line_define_resolves_macro(self) -> None:
        completed, report, _ = self._run(
            FIXTURES / "unresolved_macro",
            "unresolved_macro_top",
            "--define",
            "T027_MISSING_VALUE=4",
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["compile"]["defines"], ["T027_MISSING_VALUE=4"])
        self.assertEqual(report["dependencies"]["macros"], [])

    def test_risc_v_vector_closure(self) -> None:
        first, report, first_bytes = self._run(
            RISC, "vector_top", report_name="risc-first.json"
        )
        second, _, second_bytes = self._run(
            RISC, "vector_top", report_name="risc-second.json"
        )
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(first.stdout, second.stdout)
        self.assertEqual(first_bytes, second_bytes)
        self.assertEqual(len(report["candidate_files"]), 56)
        self.assertEqual(
            set(report["reachable"]["modules"]),
            {
                "and_or_mux",
                "eb_buff_generic",
                "eb_one_slot",
                "fifo_duth",
                "v_fp_alu",
                "v_int_alu",
                "vector_top",
                "vex",
                "vex_pipe",
                "vis",
                "vmu",
                "vmu_ld_eng",
                "vmu_st_eng",
                "vmu_tp_eng",
                "vrat",
                "vrf",
                "vrrm",
            },
        )
        expected_files = {
            "rtl/shared/and_or_mux.sv",
            "rtl/shared/eb_buff_generic.sv",
            "rtl/shared/eb_one_slot.sv",
            "rtl/shared/fifo_duth.sv",
            "rtl/vector/v_fp_alu.sv",
            "rtl/vector/v_int_alu.sv",
            "rtl/vector/vector_top.sv",
            "rtl/vector/vex.sv",
            "rtl/vector/vex_pipe.sv",
            "rtl/vector/vis.sv",
            "rtl/vector/vmacros.sv",
            "rtl/vector/vmu.sv",
            "rtl/vector/vmu_ld_eng.sv",
            "rtl/vector/vmu_st_eng.sv",
            "rtl/vector/vmu_tp_eng.sv",
            "rtl/vector/vrat.sv",
            "rtl/vector/vrf.sv",
            "rtl/vector/vrrm.sv",
            "rtl/vector/vstructs.sv",
        }
        self.assertEqual(set(report["reachable"]["files"]), expected_files)
        self.assertEqual(report["reachable"]["interfaces"], [])
        self.assertNotIn("rtl/shared/params.sv", report["reachable"]["files"])
        self.assertEqual(report["compile"]["parse_errors"], 0)
        self.assertEqual(report["compile"]["semantic_errors"], 0)
        for item in report["inventory"]["eligible"]:
            ranges = [item["declaration"], *item["references"]]
            self.assertTrue(all(source_range["file"] in expected_files for source_range in ranges))


if __name__ == "__main__":
    unittest.main()
