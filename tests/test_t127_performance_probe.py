"""T127: permanent coarse-grained timing events for the public CLI."""

from __future__ import annotations

import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from rtl_obfuscator import project_discovery


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "t127_performance_probe"
TOP = "t127_probe_top"

COMPILE_STAGES = (
    "compile.parse",
    "compile.elaborate",
    "compile.diagnostics",
    "compile.catalog_inventory",
    "compile.top_closure",
    "compile.owner_registry",
)
RENAME_STAGES = (
    "rename_index.semantic_inventory",
    "rename_index.declarations",
    "rename_index.occurrences",
    "rename_index.syntax_inventory",
    "rename_index.unelaborated",
    "rename_index.name_completeness",
    "rename_index.finalize",
)
STAGES = COMPILE_STAGES + RENAME_STAGES
TIMING_PREFIX = re.compile(r"^\[\s*(\d+\.\d{3})s\] (开始|完成) ")
STAGE_ID = re.compile(r" \[([a-z][a-z_.]+)\]")
DURATION = re.compile(r"（本阶段 (\d+\.\d{3})s）$")


def _run(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / "rtl_encrypt.py"), *arguments],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )


def _events(stderr: str) -> tuple[list[tuple[str, str]], list[float], dict[str, float]]:
    events: list[tuple[str, str]] = []
    elapsed: list[float] = []
    durations: dict[str, float] = {}
    for line in stderr.splitlines():
        timing = TIMING_PREFIX.match(line)
        if timing is None:
            continue
        elapsed.append(float(timing.group(1)))
        stage_match = STAGE_ID.search(line)
        if stage_match is None:
            continue
        stage = stage_match.group(1)
        phase = timing.group(2)
        events.append((stage, phase))
        if phase == "完成":
            duration = DURATION.search(line)
            if duration is None:
                raise AssertionError(f"missing duration for {stage}: {line}")
            durations[stage] = float(duration.group(1))
    return events, elapsed, durations


class T127PerformanceProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.output_root = Path(tempfile.mkdtemp(prefix="t127-performance-"))
        cls.addClassCleanup(shutil.rmtree, cls.output_root, ignore_errors=True)
        cls.gate = cls.output_root / "gate"
        cls.result = _run(
            "--filelist", str(FIXTURE / "design.f"),
            "--top", TOP,
            "--rewrite-root", str(FIXTURE / "owned"),
            "--category", "all",
            "--output-dir", str(cls.gate),
        )
        if cls.result.returncode != 0:
            raise AssertionError(cls.result.stderr)
        cls.payload = json.loads(cls.result.stdout)
        cls.events, cls.elapsed, cls.durations = _events(cls.result.stderr)
        # This is the server-facing measurement requested by the contract.
        print(
            "T127_SINGLE_MODULE_TIMING_JSON="
            + json.dumps(cls.durations, sort_keys=True, separators=(",", ":"))
        )

    def test_each_fixed_substage_has_one_begin_and_end_in_order(self):
        begun = [stage for stage, phase in self.events if phase == "开始"]
        ended = [stage for stage, phase in self.events if phase == "完成"]
        self.assertEqual(begun, list(STAGES))
        self.assertEqual(ended, list(STAGES))
        self.assertEqual(len(self.events), 2 * len(STAGES))
        self.assertEqual(set(self.durations), set(STAGES))

    def test_substages_are_nested_inside_the_two_outer_t116_stages(self):
        lines = self.result.stderr.splitlines()
        compile_begin = next(
            index for index, line in enumerate(lines)
            if "开始 PySlang 编译与 elaborate" in line and "[compile." not in line
        )
        compile_end = next(
            index for index, line in enumerate(lines)
            if "完成 PySlang 编译与 elaborate" in line and "[compile." not in line
        )
        rename_begin = next(
            index for index, line in enumerate(lines)
            if "开始 构建改名索引" in line and "[rename_index." not in line
        )
        rename_end = next(
            index for index, line in enumerate(lines)
            if "完成 构建改名索引" in line and "[rename_index." not in line
        )
        event_lines = [
            (index, STAGE_ID.search(line).group(1))
            for index, line in enumerate(lines)
            if STAGE_ID.search(line) is not None
        ]
        self.assertTrue(all(compile_begin < index < compile_end for index, stage in event_lines if stage in COMPILE_STAGES))
        self.assertTrue(all(rename_begin < index < rename_end for index, stage in event_lines if stage in RENAME_STAGES))

    def test_one_compact_public_run_really_renames_compiles_and_restores(self):
        summary = self.payload["summary"]
        self.assertEqual(self.payload["format"], "rtl-obfuscation.cli-vnext")
        self.assertEqual(self.payload["schema_version"], 2)
        self.assertGreater(summary["rename"], 0)
        self.assertTrue(summary["strict_compile_passed"])
        self.assertTrue(summary["restored_byte_identical"])
        mapping = json.loads((self.gate / "mapping.json").read_text(encoding="utf-8"))
        self.assertTrue(any(record["action"] == "rename" for record in mapping["mapping"]["records"]))
        self.assertTrue((self.gate / "owned" / "top.sv").is_file())

    def test_elapsed_seconds_and_durations_are_finite_and_nonnegative(self):
        self.assertTrue(all(math.isfinite(value) for value in self.elapsed))
        self.assertTrue(all(math.isfinite(value) and value >= 0 for value in self.durations.values()))
        self.assertTrue(all(previous <= current for previous, current in zip(self.elapsed, self.elapsed[1:])))

    def test_failed_substage_emits_begin_without_a_fake_end(self):
        events: list[tuple[str, str]] = []
        with mock.patch.object(
            project_discovery.pyslang.syntax.SyntaxTree,
            "fromFiles",
            side_effect=RuntimeError("synthetic parse failure"),
        ):
            with self.assertRaisesRegex(RuntimeError, "synthetic parse failure"):
                project_discovery.compile_pyslang_source_set(
                    root=FIXTURE,
                    compilation_files=("owned/top.sv",),
                    stage_observer=lambda stage, phase: events.append((stage, phase)),
                )
        self.assertEqual(events, [("compile.parse", "begin")])

    def test_quiet_suppresses_outer_and_substage_progress(self):
        quiet = _run(
            "--filelist", str(FIXTURE / "design.f"),
            "--top", TOP,
            "--rewrite-root", str(FIXTURE / "owned"),
            "--category", "all",
            "--quiet",
            "--output-dir", str(self.output_root / "quiet-gate"),
        )
        self.assertEqual(quiet.returncode, 0, quiet.stderr)
        self.assertEqual(quiet.stderr, "")
        self.assertEqual(json.loads(quiet.stdout)["summary"], self.payload["summary"])
