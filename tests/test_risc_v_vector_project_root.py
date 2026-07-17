from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
RISC = ROOT / "rtl_samples" / "RISC-V-Vector"
FIFO = ROOT / "rtl_samples" / "example_fifo"
INPUT_MANIFEST = "a016dd548525346508c636b97fcc452c8f6eb4fcbf930ef5eb938a2edfa2ae9d"
ELIGIBLE_SHA256 = "6d4e0ef7d46d569d2fecda8563ccdd4012eb6043cb86b9c908d06391b291e6d0"
PRESERVED_SHA256 = "b5b31416d834ff03eda28e28c4e625108b13e36ecdf28750dc5d78f22e244d9f"
INVENTORY_SHA256 = "0b661f775f936cb15ca5c39dbafbb54c450a5062a935d7daac2d16113d6b3e93"
PORTS_SHA256 = "2dad5d96fdc98cc95a6285e2bfcad97fbc628e81849a9d91cf1d43a6c7a61d63"
GOLD_VIEW_MANIFEST = "56572fb29266c2f6cb44ef9a9846bda4585c846dc28677b9855e9bae79649872"
ALIGNED_VIEW_MANIFEST = "d3031e8f71891203f16fa8ff7d5022e8105f13e2237a188669d1698a7f8accc7"
COMPILE_ORDER = [
    "rtl/shared/and_or_mux.sv",
    "rtl/shared/eb_one_slot.sv",
    "rtl/shared/eb_buff_generic.sv",
    "rtl/shared/fifo_duth.sv",
    "rtl/vector/v_fp_alu.sv",
    "rtl/vector/vmacros.sv",
    "rtl/vector/v_int_alu.sv",
    "rtl/vector/vex_pipe.sv",
    "rtl/vector/vrat.sv",
    "rtl/vector/vrf.sv",
    "rtl/vector/vstructs.sv",
    "rtl/vector/vex.sv",
    "rtl/vector/vis.sv",
    "rtl/vector/vmu_ld_eng.sv",
    "rtl/vector/vmu_st_eng.sv",
    "rtl/vector/vmu_tp_eng.sv",
    "rtl/vector/vmu.sv",
    "rtl/vector/vrrm.sv",
    "rtl/vector/vector_top.sv",
]
MODULES = [
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
]


def canonical(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()


def manifest(root: Path, files: list[str]) -> str:
    payload = b"".join(
        hashlib.sha256((root / name).read_bytes()).hexdigest().encode("ascii")
        + b"  "
        + name.encode("utf-8")
        + b"\n"
        for name in sorted(files)
    )
    return hashlib.sha256(payload).hexdigest()


def signature(item: dict[str, object]) -> tuple[object, ...]:
    common = (
        item["kind"],
        item["file"],
        item["syntax_kind"],
        item["structural_ordinal"],
    )
    if item["kind"] == "lower_packed_aggregate_type":
        return (*common, item["bit_width"])
    if item["kind"] == "lower_packed_struct_member":
        return (
            *common,
            item["struct_width"],
            item["field_offset"],
            item["field_width"],
            item["base_shape"],
        )
    return common


def normalized_yosys_warnings(
    stderr: str, mapping: dict[str, object]
) -> frozenset[str]:
    replacements = {
        entry["renamed_name"]: entry["original_name"]
        for entry in mapping["entries"]
    }
    normalized: set[str] = set()
    for raw_line in stderr.splitlines():
        if "Warning:" not in raw_line:
            continue
        line = raw_line
        source_marker = line.find("/rtl/")
        if source_marker >= 0:
            line = line[source_marker + 1 :]
        for renamed_name, original_name in replacements.items():
            line = line.replace(renamed_name, original_name)
        line = re.sub(r"\$paramod\$[0-9a-f]+", "$paramod$<hash>", line)
        normalized.add(line)
    return frozenset(normalized)


class RiscVVectorProjectRootTests(unittest.TestCase):
    @classmethod
    def run_command_process(
        cls, *arguments: str
    ) -> tuple[dict[str, object], subprocess.CompletedProcess[str]]:
        process = subprocess.run(
            [sys.executable, "-m", "rtl_obfuscator.rewrite", *arguments],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if process.returncode != 0:
            raise AssertionError(process.stderr)
        return json.loads(process.stdout), process

    @classmethod
    def run_command(cls, *arguments: str) -> dict[str, object]:
        payload, _ = cls.run_command_process(*arguments)
        return payload

    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory(prefix="t029-tests-")
        cls.work = Path(cls.temporary.name)
        cls.report_path = cls.work / "gold-report.json"
        cls.inspect_summary = cls.run_command(
            "inspect-project",
            "--project-root",
            str(RISC),
            "--top",
            "vector_top",
            "--report",
            str(cls.report_path),
        )
        cls.report = json.loads(cls.report_path.read_text(encoding="utf-8"))

        cls.group_summaries: dict[str, dict[str, object]] = {}
        for group in ("signals", "ports", "instances", "struct", "interface"):
            base = cls.work / f"group-{group}"
            cls.group_summaries[group] = cls.run_command(
                "encrypt-project",
                "--project-root",
                str(RISC),
                "--top",
                "vector_top",
                "--output-dir",
                str(base / "gate"),
                "--map",
                str(base / "mapping.json"),
                "--metrics",
                str(base / "metrics.json"),
                "--category",
                group,
                "--name-length",
                "8",
            )

        cls.gate = cls.work / "combined/gate"
        cls.mapping_path = cls.work / "combined/mapping.json"
        cls.metrics_path = cls.work / "combined/metrics.json"
        categories = [
            option
            for group in ("signals", "ports", "instances", "struct", "interface")
            for option in ("--category", group)
        ]
        cls.combined_summary = cls.run_command(
            "encrypt-project",
            "--project-root",
            str(RISC),
            "--top",
            "vector_top",
            "--output-dir",
            str(cls.gate),
            "--map",
            str(cls.mapping_path),
            "--metrics",
            str(cls.metrics_path),
            "--file-map-dir",
            str(cls.work / "combined/maps"),
            *categories,
            "--name-length",
            "8",
        )
        cls.mapping = json.loads(cls.mapping_path.read_text(encoding="utf-8"))
        cls.metrics = json.loads(cls.metrics_path.read_text(encoding="utf-8"))
        cls.gate_report_path = cls.work / "combined/gate-report.json"
        cls.gate_summary = cls.run_command(
            "inspect-project",
            "--project-root",
            str(cls.gate),
            "--top",
            "vector_top",
            "--report",
            str(cls.gate_report_path),
        )
        cls.gate_report = json.loads(
            cls.gate_report_path.read_text(encoding="utf-8")
        )
        cls.restored = cls.work / "combined/restored"
        cls.decrypt_summary = cls.run_command(
            "decrypt-project",
            "--gate-dir",
            str(cls.gate),
            "--map",
            str(cls.mapping_path),
            "--output-dir",
            str(cls.restored),
        )

        cls.gold_view = cls.work / "formal-gold"
        cls.gold_view_two = cls.work / "formal-gold-two"
        cls.gate_view = cls.work / "formal-gate"
        cls.gold_manifest = cls.work / "formal-gold.json"
        cls.gold_manifest_two = cls.work / "formal-gold-two.json"
        cls.gate_manifest = cls.work / "formal-gate.json"
        cls.gold_view_summary, cls.gold_view_process = cls.run_command_process(
            "formal-view",
            "--project-root",
            str(RISC),
            "--top",
            "vector_top",
            "--output-dir",
            str(cls.gold_view),
            "--manifest",
            str(cls.gold_manifest),
        )
        cls.run_command(
            "formal-view",
            "--project-root",
            str(RISC),
            "--top",
            "vector_top",
            "--output-dir",
            str(cls.gold_view_two),
            "--manifest",
            str(cls.gold_manifest_two),
        )
        cls.gate_view_summary, cls.gate_view_process = cls.run_command_process(
            "formal-view",
            "--project-root",
            str(cls.gate),
            "--top",
            "vector_top",
            "--output-dir",
            str(cls.gate_view),
            "--manifest",
            str(cls.gate_manifest),
        )

        cls.aligned = cls.work / "formal-aligned"
        cls.aligned_two = cls.work / "formal-aligned-two"
        cls.aligned_manifest = cls.work / "formal-aligned.json"
        cls.aligned_manifest_two = cls.work / "formal-aligned-two.json"
        align_args = (
            "--gate-dir",
            str(cls.gate),
            "--gate-view-dir",
            str(cls.gate_view),
            "--gate-view-manifest",
            str(cls.gate_manifest),
            "--map",
            str(cls.mapping_path),
        )
        cls.alignment_summary, cls.alignment_process = cls.run_command_process(
            "formal-align",
            *align_args,
            "--output-dir",
            str(cls.aligned),
            "--manifest",
            str(cls.aligned_manifest),
        )
        cls.alignment_summary_two = cls.run_command(
            "formal-align",
            *align_args,
            "--output-dir",
            str(cls.aligned_two),
            "--manifest",
            str(cls.aligned_manifest_two),
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def test_fixed_input_manifest(self) -> None:
        files = self.report["reachable"]["files"]
        self.assertEqual(manifest(RISC, files), INPUT_MANIFEST)
        self.assertEqual(len(self.report["candidate_files"]), 56)

    def test_inspect_closure_compile_order_and_topology(self) -> None:
        self.assertEqual(self.report["reachable"]["modules"], MODULES)
        self.assertEqual(self.report["reachable"]["interfaces"], [])
        self.assertEqual(self.report["compile"]["compile_order"], COMPILE_ORDER)
        self.assertEqual(self.report["compile"]["parse_errors"], 0)
        self.assertEqual(self.report["compile"]["semantic_errors"], 0)

    def test_inventory_exact_canonical_oracle(self) -> None:
        inventory = self.report["inventory"]
        self.assertEqual((len(inventory["eligible"]), sum(x["occurrences"] for x in inventory["eligible"])), (1091, 5741))
        self.assertEqual((len(inventory["preserved"]), sum(x["occurrences"] for x in inventory["preserved"])), (35, 113))
        self.assertEqual(canonical(inventory["eligible"]), ELIGIBLE_SHA256)
        self.assertEqual(canonical(inventory["preserved"]), PRESERVED_SHA256)
        self.assertEqual(canonical(inventory), INVENTORY_SHA256)

    def test_packed_array_element_struct_is_included(self) -> None:
        eligible = self.report["inventory"]["eligible"]
        alias = next(x for x in eligible if x["category"] == "struct_types" and x["name"] == "to_vector_exec")
        self.assertEqual(alias["occurrences"], 5)
        fields = {x["name"]: x["occurrences"] for x in eligible if x["category"] == "struct_fields" and x["scope"] == "$unit::to_vector_exec"}
        self.assertEqual(fields, {"valid": 3, "mask": 3, "data1": 3, "data2": 3, "immediate": 3})

    def test_generate_local_signal_actual_arguments_are_included(self) -> None:
        eligible = self.report["inventory"]["eligible"]
        expected = {"fifo_push": (2362, 2371), "fifo_pop": (2515, 2523)}
        for name, location in expected.items():
            entry = next(x for x in eligible if x["category"] == "signals" and x["scope"] == "eb_buff_generic" and x["name"] == name)
            ranges = {(x["start"], x["end"]) for x in entry["references"] if x["file"] == "rtl/shared/eb_buff_generic.sv"}
            self.assertIn(location, ranges)

    def test_all_semantic_port_references_are_included(self) -> None:
        ports = [x for x in self.report["inventory"]["eligible"] if x["category"] == "ports"]
        self.assertEqual((len(ports), sum(x["occurrences"] for x in ports)), (348, 1853))
        self.assertEqual(canonical(ports), PORTS_SHA256)
        parent_ranges = {(1605, 1608), (1638, 1641), (1684, 1691), (1717, 1724), (1750, 1756), (1796, 1803), (1829, 1836), (1862, 1868), (2244, 2247), (2279, 2282), (2327, 2333), (2397, 2404), (2445, 2451), (2480, 2487)}
        actual = {(r["start"], r["end"]) for entry in ports for r in entry["references"] if r["file"] == "rtl/shared/eb_buff_generic.sv"}
        self.assertTrue(parent_ranges <= actual)

    def test_five_group_individual_summaries(self) -> None:
        expected = {"signals": (675, 3614), "ports": (348, 1853), "instances": (19, 19), "struct": (49, 255), "interface": (0, 0)}
        for group, (entries, tokens) in expected.items():
            self.assertEqual(self.group_summaries[group], {"files": 19, "mapping_entries": entries, "modified_tokens": tokens})

    def test_combined_mapping_and_metrics(self) -> None:
        self.assertEqual(self.combined_summary, {"files": 19, "mapping_entries": 1091, "modified_tokens": 5741})
        self.assertEqual(self.mapping["selected_groups"], ["signals", "ports", "instances", "struct", "interface"])
        self.assertFalse(any(x["category"] == "parameters" for x in self.mapping["entries"]))
        self.assertEqual(self.metrics["symbols"]["coverage"], 1.0)
        self.assertEqual(self.metrics["occurrences"]["coverage"], 1.0)
        self.assertEqual(self.metrics["plaintext_leakage_rate"], 0.0)

    def test_combined_gate_strict_reinspect_and_topology(self) -> None:
        self.assertEqual(self.gate_summary["reachable_modules"], 17)
        self.assertEqual(self.gate_summary["closure_files"], 19)
        self.assertEqual((self.gate_summary["eligible_symbols"], self.gate_summary["eligible_occurrences"]), (1091, 5741))
        self.assertEqual(self.gate_report["compile"]["compile_order"], COMPILE_ORDER)
        self.assertEqual(self.mapping["closure"]["modules"], MODULES)

    def test_top_abi_and_parameters_are_preserved(self) -> None:
        preserved = self.report["inventory"]["preserved"]
        self.assertEqual(Counter(x["reason"] for x in preserved), {"top_port": 11, "top_abi_type": 24})
        self.assertEqual(sum(x["occurrences"] for x in preserved if x["reason"] == "top_port"), 37)
        self.assertFalse(any(x["category"] == "parameters" for x in self.mapping["entries"]))

    def test_decrypt_restores_every_closure_file(self) -> None:
        self.assertEqual(self.decrypt_summary, {"files": 19, "mapping_entries": 1091, "modified_tokens": 5741})
        files = self.mapping["files"]
        self.assertTrue(all((RISC / name).read_bytes() == (self.restored / name).read_bytes() for name in files))
        self.assertEqual(manifest(self.restored, files), INPUT_MANIFEST)

    def test_gold_formal_view_exact_oracle_and_determinism(self) -> None:
        self.assertEqual(self.gold_view_summary, {"files": 19, "top": "vector_top", "transformations": 260, "view_manifest_sha256": GOLD_VIEW_MANIFEST})
        manifest_data = json.loads(self.gold_manifest.read_text(encoding="utf-8"))
        self.assertEqual(Counter(x["kind"] for x in manifest_data["transformations"]), {"lower_packed_aggregate_type": 25, "lower_packed_struct_member": 233, "remove_concurrent_assertion": 2})
        self.assertEqual(self.gold_manifest.read_bytes(), self.gold_manifest_two.read_bytes())
        self.assertTrue(all((self.gold_view / name).read_bytes() == (self.gold_view_two / name).read_bytes() for name in self.mapping["files"]))
        self.assertEqual((self.gold_view / "design.f").read_bytes(), (self.gold_view_two / "design.f").read_bytes())

    def test_gate_formal_view_alignment_and_symmetric_transformations(self) -> None:
        gold = json.loads(self.gold_manifest.read_text(encoding="utf-8"))
        gate = json.loads(self.gate_manifest.read_text(encoding="utf-8"))
        self.assertEqual([signature(x) for x in gold["transformations"]], [signature(x) for x in gate["transformations"]])
        self.assertEqual(self.alignment_summary, {"files": 19, "identifier_replacements": 5527, "top": "vector_top", "view_manifest_sha256": ALIGNED_VIEW_MANIFEST})
        self.assertEqual(self.alignment_summary_two, self.alignment_summary)
        self.assertEqual(self.aligned_manifest.read_bytes(), self.aligned_manifest_two.read_bytes())
        self.assertTrue(all((self.aligned / name).read_bytes() == (self.aligned_two / name).read_bytes() for name in self.mapping["files"]))
        gold_warnings = normalized_yosys_warnings(self.gold_view_process.stderr, self.mapping)
        self.assertEqual(len(gold_warnings), 18)
        self.assertEqual(normalized_yosys_warnings(self.gate_view_process.stderr, self.mapping), gold_warnings)
        self.assertEqual(normalized_yosys_warnings(self.alignment_process.stderr, self.mapping), gold_warnings)
        bad_manifest = self.work / "bad-gate-view.json"
        bad_manifest.write_text("{}\n", encoding="utf-8")
        output = self.work / "bad-aligned"
        output_manifest = self.work / "bad-aligned.json"
        process = subprocess.run([sys.executable, "-m", "rtl_obfuscator.rewrite", "formal-align", "--gate-dir", str(self.gate), "--gate-view-dir", str(self.gate_view), "--gate-view-manifest", str(bad_manifest), "--map", str(self.mapping_path), "--output-dir", str(output), "--manifest", str(output_manifest)], cwd=ROOT, capture_output=True, text=True, check=False)
        self.assertEqual(process.returncode, 1)
        self.assertFalse(output.exists())
        self.assertFalse(output_manifest.exists())

    def test_formal_view_rejects_unsupported_shape_transactionally(self) -> None:
        source_root = self.work / "unsupported"
        source_root.mkdir()
        (source_root / "top.sv").write_text("typedef struct packed { logic [3:0] data; } payload_t;\nmodule top(output logic out); payload_t [1:0][1:0] values; assign out = values[0][0].data[0]; endmodule\n", encoding="utf-8")
        output = self.work / "unsupported-view"
        output_manifest = self.work / "unsupported-view.json"
        process = subprocess.run([sys.executable, "-m", "rtl_obfuscator.rewrite", "formal-view", "--project-root", str(source_root), "--top", "top", "--output-dir", str(output), "--manifest", str(output_manifest)], cwd=ROOT, capture_output=True, text=True, check=False)
        self.assertEqual(process.returncode, 1)
        self.assertIn("nested packed arrays", process.stderr)
        self.assertFalse(output.exists())
        self.assertFalse(output_manifest.exists())

    def test_multifile_formal_script_keeps_fifo_compatible(self) -> None:
        script = (ROOT / "scripts/formal_equivalence.py").read_text(encoding="utf-8")
        self.assertEqual(script.count("read_verilog -sv -formal -defer"), 2)
        self.assertEqual(script.count("async2sync"), 2)
        fifo = self.work / "fifo"
        summary = self.run_command("encrypt-project", "--project-root", str(FIFO), "--top", "fifo_top", "--output-dir", str(fifo / "gate"), "--map", str(fifo / "mapping.json"), "--metrics", str(fifo / "metrics.json"), "--category", "signals", "--category", "ports", "--category", "instances", "--category", "struct", "--category", "interface", "--name-length", "8")
        self.assertEqual(summary, {"files": 4, "mapping_entries": 50, "modified_tokens": 195})
        process = subprocess.run([sys.executable, "scripts/formal_equivalence.py", "--gold-filelist", str(FIFO / "design.f"), "--gold-root", str(FIFO), "--gate-filelist", str(fifo / "gate/design.f"), "--gate-root", str(fifo / "gate"), "--top", "fifo_top", "--seq", "5"], cwd=ROOT, capture_output=True, text=True, check=False)
        self.assertEqual(process.returncode, 0, process.stderr)


if __name__ == "__main__":
    unittest.main()
