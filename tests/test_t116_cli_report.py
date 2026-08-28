"""T116: the demo terminal experience, without touching the machine interface.

The hard constraint of this task is negative: ten test modules of this
repository call ``json.loads`` on the encryptor's stdout, so stdout must keep
carrying exactly the one JSON line it carried before.  Progress and the human
summary therefore live on stderr, which is why the first test here pins the
stdout envelope and the ``--quiet`` test proves the flag reaches stderr only.

Two of the assertions exist to stop a test that only looks like one:

* ``test_report_numbers_equal_the_stdout_json_of_the_same_run`` compares the
  report against the JSON the same run printed, not against numbers this test
  computed the way the formatter computes them.  A formatter agreeing with
  itself proves nothing;
* ``test_landed_edit_counts_are_derived_from_per_file_mapping`` recomputes the
  two fields T116 section 3.2 had to define from ``per_file_mapping`` directly,
  by two mutually independent rules -- the per-file digest pair and the record
  actions -- and never by calling the product helper under test.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from rtl_obfuscator import rewrite


ROOT = Path(__file__).resolve().parents[1]
# Read-only: this task may not modify RTL fixtures, so the success path reuses
# one existing multi-file design that mixes renames with preserves.
FIXTURE = ROOT / "tests" / "fixtures" / "t115_name_completeness"
TOP = "t115_top"

# Section 3.2 freezes this field list, and section 3.1 this stage list.
REPORT_LABELS = (
    "用时",
    "加密类型数",
    "加密类型",
    "总代码行数",
    "实际加密行数",
    "加密率",
    "总文件数",
    "加密文件数",
    "文件覆盖率",
    "改名对象数(rename)",
    "保留对象数(preserve)",
    "不支持对象数(unsupported)",
    "实际修改对象数",
)
STAGE_LABELS = (
    "读取 filelist / 组装 SourceSet",
    "PySlang 编译与 elaborate",
    "构建改名索引",
    "生成映射",
    "写出加密结果",
    "逐字节回填校验",
)
ELAPSED = re.compile(r"^\[\s*(\d+\.\d{3})s\] (开始|完成) (.+?)(?:（本阶段 \d+\.\d{3}s）)?$")
POSITION = re.compile(r"^  (\S+):(\d+):(\d+)  (\S+)$")


def _run(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / "rtl_encrypt.py"), *arguments],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )


def _report_rows(stderr: str) -> dict[str, str]:
    """The report as ``{label: value}``, parsed the way an operator reads it."""

    rows: dict[str, str] = {}
    started = False
    for line in stderr.splitlines():
        if line == "加密总结":
            started = True
            continue
        if not started or not line.startswith("  "):
            continue
        text = line[2:]
        for label in REPORT_LABELS:
            if text.startswith(label):
                value = text[len(label):].strip()
                if value:
                    rows.setdefault(label, value)
                break
    return rows


class T116StdoutContractTests(unittest.TestCase):
    """stdout keeps the machine interface; stderr carries the demo."""

    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix="t116-report-"))
        cls.addClassCleanup(shutil.rmtree, cls.root, ignore_errors=True)
        cls.gate = cls.root / "gate"
        cls.result = _run(
            "--filelist", str(FIXTURE / "design.f"),
            "--top", TOP,
            "--category", "all",
            "--output-dir", str(cls.gate),
        )
        assert cls.result.returncode == 0, cls.result.stderr
        cls.payload = json.loads(cls.result.stdout)
        cls.summary = cls.payload["summary"]
        cls.rows = _report_rows(cls.result.stderr)
        cls.mapping = json.loads(
            (cls.gate / "mapping.json").read_text(encoding="utf-8")
        )

    def test_stdout_is_still_exactly_one_json_line_with_the_same_field_set(self):
        """Section 2: the ten stdout consumers must see no change at all."""

        self.assertEqual(len(self.result.stdout.strip().splitlines()), 1)
        self.assertEqual(self.result.stdout.count("\n"), 1)
        self.assertEqual(
            set(self.payload),
            {"format", "schema_version", "state", "action_counts", "summary"},
        )
        self.assertEqual(self.payload["format"], "rtl-obfuscation.cli-vnext")
        self.assertEqual(self.payload["schema_version"], 2)
        self.assertEqual(self.payload["state"], "restored")
        self.assertEqual(
            set(self.payload["action_counts"]), {"rename", "preserve", "unsupported"}
        )
        self.assertEqual(
            set(self.summary),
            {
                "encryption_result", "origin", "top", "rate_enabled", "files",
                "mapping_records", "effective_mapping_records", "modified_tokens",
                "strict_compile_passed", "restored_byte_identical",
                "effective_line_total", "affected_line_count", "symbol_coverage",
                "occurrence_coverage", "plaintext_leakage_rate", "effective_coverage",
                "rename", "preserve", "unsupported",
            },
        )
        # Not a vacuous run: this fixture really renames and really restores.
        self.assertGreater(self.summary["rename"], 0)
        self.assertTrue(self.summary["restored_byte_identical"])
        # And the report went to the other stream.
        self.assertNotIn("加密总结", self.result.stdout)
        self.assertIn("加密总结", self.result.stderr)

    def test_progress_names_every_stage_with_monotonic_elapsed_seconds(self):
        """Section 3.1: one clock, non-decreasing, in the frozen stage order."""

        seconds: list[float] = []
        begun: list[str] = []
        finished: list[str] = []
        for line in self.result.stderr.splitlines():
            match = ELAPSED.match(line)
            if match is None:
                continue
            seconds.append(float(match.group(1)))
            (begun if match.group(2) == "开始" else finished).append(match.group(3))
        self.assertEqual(begun, list(STAGE_LABELS))
        self.assertEqual(finished, list(STAGE_LABELS))
        self.assertEqual(len(seconds), 2 * len(STAGE_LABELS))
        for previous, current in zip(seconds, seconds[1:]):
            self.assertLessEqual(previous, current, seconds)

    def test_report_carries_every_required_field(self):
        """Section 3.2: the field list is the user's, not the formatter's."""

        self.assertEqual(set(self.rows), set(REPORT_LABELS))
        self.assertRegex(self.rows["用时"], r"^\d+\.\d{3}s$")
        # Groups are separated by blank lines, and the report is not one block.
        block = self.result.stderr.split("加密总结\n", 1)[1]
        self.assertGreaterEqual(block.count("\n\n"), 4)

    def test_report_numbers_equal_the_stdout_json_of_the_same_run(self):
        """Every reused field is checked against the run's own machine output."""

        self.assertEqual(
            self.rows["总代码行数"], str(self.summary["effective_line_total"])
        )
        self.assertEqual(
            self.rows["实际加密行数"], str(self.summary["affected_line_count"])
        )
        self.assertEqual(self.rows["总文件数"], str(self.summary["files"]))
        self.assertEqual(self.rows["改名对象数(rename)"], str(self.summary["rename"]))
        self.assertEqual(self.rows["保留对象数(preserve)"], str(self.summary["preserve"]))
        self.assertEqual(
            self.rows["不支持对象数(unsupported)"], str(self.summary["unsupported"])
        )
        effective = self.summary["effective_line_total"]
        affected = self.summary["affected_line_count"]
        self.assertGreater(effective, 0)
        self.assertEqual(
            self.rows["加密率"], f"{affected * 100 / effective:.2f}%"
        )
        # The same ratio the persisted metrics report already carries.
        metrics = json.loads((self.gate / "metrics.json").read_text(encoding="utf-8"))
        self.assertAlmostEqual(
            float(self.rows["加密率"].rstrip("%")) / 100,
            metrics["affected_lines"]["rate"],
            places=4,
        )
        # The category set is the one the mapping records support.
        categories = tuple(self.rows["加密类型"].split(", "))
        self.assertEqual(
            set(categories),
            {
                record["category"]
                for record in self.mapping["mapping"]["records"]
                if record["action"] == "rename"
            },
        )
        self.assertEqual(self.rows["加密类型数"], str(len(categories)))

    def test_landed_edit_counts_are_derived_from_per_file_mapping(self):
        """Section 3.2: the two fields this task had to define.

        Both are recomputed here straight from ``per_file_mapping`` by rules this
        test owns, and by two independent ones for the file count: a file whose
        gate digest differs from its input digest is a file that really changed,
        and a file holding a landed ``rename`` range is the same file said the
        other way.  Neither uses the product helper.
        """

        per_file = self.mapping["mapping_execution"]["per_file_mapping"]
        self.assertEqual(len(per_file), self.summary["files"])
        by_digest = [
            entry["file"]
            for entry in per_file
            if entry["input_sha256"] != entry["gate_sha256"]
        ]
        by_action = [
            entry["file"]
            for entry in per_file
            if any(
                record["action"] == "rename" and record["ranges"]
                for record in entry["records"]
            )
        ]
        self.assertEqual(by_digest, by_action)
        self.assertGreater(len(by_digest), 0)
        self.assertEqual(self.rows["加密文件数"], str(len(by_digest)))
        self.assertEqual(
            self.rows["文件覆盖率"],
            f"{len(by_digest) * 100 / self.summary['files']:.2f}%",
        )
        modified = {
            record["symbol_id"]
            for entry in per_file
            for record in entry["records"]
            if record["action"] == "rename" and record["ranges"]
        }
        self.assertGreater(len(modified), 0)
        self.assertEqual(self.rows["实际修改对象数"], str(len(modified)))
        # Decisions and landed records are both printed, whether or not they
        # agree on this input; hiding either one is what section 3.2 forbids.
        self.assertIn("改名对象数(rename)", self.rows)
        self.assertIn("实际修改对象数", self.rows)
        self.assertEqual(
            len(modified),
            sum(
                1
                for record in self.mapping["mapping"]["records"]
                if record["action"] == "rename"
            ),
        )

    def test_persisted_artifacts_are_unchanged_by_the_terminal_report(self):
        """The gate must stay what it was: the report is stderr only."""

        summary_text = (self.gate / "encryption_summary.txt").read_text(
            encoding="utf-8"
        )
        self.assertEqual(
            [line.split("：")[0] for line in summary_text.strip().splitlines()],
            [
                "改名对象（rename）", "保留对象（preserve）", "不支持对象（unsupported）",
                "修改 token 数", "加密率", "实际加密行数", "总代码行数",
                "加密类型数", "加密类型",
            ],
        )
        self.assertNotIn("加密总结", summary_text)
        self.assertNotIn("实际修改对象数", summary_text)
        self.assertFalse((self.gate / "progress.txt").exists())

    def test_quiet_silences_stderr_without_touching_stdout(self):
        """Section 2: ``--quiet`` reaches the human streams only."""

        quiet = _run(
            "--filelist", str(FIXTURE / "design.f"),
            "--top", TOP,
            "--category", "all",
            "--quiet",
            "--output-dir", str(self.root / "quiet-gate"),
        )
        self.assertEqual(quiet.returncode, 0, quiet.stderr)
        self.assertEqual(quiet.stderr, "")
        # Identical stdout bytes, with and without the flag: the summary of this
        # fixture is fully determined by its input.
        self.assertEqual(quiet.stdout, self.result.stdout)
        self.assertEqual(json.loads(quiet.stdout)["summary"], self.summary)


class T116DefinedFieldTests(unittest.TestCase):
    """The two fields section 3.2 had to define must not be aliases.

    On the reused fixture every file changes and every decision lands, so those
    numbers alone cannot tell 加密文件数 apart from 总文件数, nor 实际修改对象数
    apart from ``rename``.  These two inputs separate them.
    """

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="t116-defined-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def test_a_file_with_nothing_to_rename_lowers_the_file_coverage(self):
        project = self.root / "proj"
        project.mkdir()
        (project / "core.sv").write_text(
            "module t116_core (\n"
            "    input  logic clk,\n"
            "    input  logic [3:0] data_in,\n"
            "    output logic [3:0] data_out\n"
            ");\n"
            "    logic [3:0] hold_value;\n"
            "    always_ff @(posedge clk) hold_value <= data_in;\n"
            "    assign data_out = hold_value;\n"
            "endmodule\n",
            encoding="utf-8",
        )
        # No port, no signal, no interface, no struct: nothing in scope here.
        (project / "bare.sv").write_text(
            "module t116_bare;\n    initial begin\n    end\nendmodule\n",
            encoding="utf-8",
        )
        filelist = project / "design.f"
        filelist.write_text("core.sv\nbare.sv\n", encoding="utf-8")
        gate = self.root / "gate"
        result = _run(
            "--filelist", str(filelist),
            "--category", "all",
            "--output-dir", str(gate),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = _report_rows(result.stderr)
        summary = json.loads(result.stdout)["summary"]
        per_file = json.loads(
            (gate / "mapping.json").read_text(encoding="utf-8")
        )["mapping_execution"]["per_file_mapping"]
        changed = [
            entry["file"]
            for entry in per_file
            if entry["input_sha256"] != entry["gate_sha256"]
        ]
        self.assertEqual(changed, ["core.sv"])
        self.assertEqual(summary["files"], 2)
        self.assertEqual(rows["总文件数"], "2")
        self.assertEqual(rows["加密文件数"], "1")
        self.assertEqual(rows["文件覆盖率"], "50.00%")

    def test_rate_selection_separates_landed_records_from_decisions(self):
        """Under ``--encryption-rate`` the mapping decides more than it lands."""

        gate = self.root / "gate-rate"
        result = _run(
            "--filelist", str(FIXTURE / "design.f"),
            "--top", TOP,
            "--category", "all",
            "--encryption-rate", "0.5",
            "--output-dir", str(gate),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = _report_rows(result.stderr)
        summary = json.loads(result.stdout)["summary"]
        self.assertTrue(summary["rate_enabled"])
        report = json.loads((gate / "mapping.json").read_text(encoding="utf-8"))
        decided = sum(
            1
            for record in report["mapping"]["records"]
            if record["action"] == "rename"
        )
        landed = {
            record["symbol_id"]
            for entry in report["mapping_execution"]["per_file_mapping"]
            for record in entry["records"]
            if record["action"] == "rename" and record["ranges"]
        }
        # The whole point: the mapping planned more renames than landed.
        self.assertGreater(decided, len(landed))
        self.assertEqual(rows["实际修改对象数"], str(len(landed)))
        self.assertEqual(rows["改名对象数(rename)"], str(summary["rename"]))
        self.assertEqual(len(landed), summary["rename"])


class T116DivisionByZeroTests(unittest.TestCase):
    """Section 3.2: a zero denominator is ``n/a``, never a crash and never 0%.

    The CLI cannot produce a real design with zero effective lines, so the
    boundary is exercised on the formatter directly rather than faked into a
    fixture.
    """


    def test_zero_totals_report_n_a(self):
        text = rewrite._cli_vnext_terminal_report(
            {
                "summary": {
                    "effective_line_total": 0,
                    "affected_line_count": 0,
                    "files": 0,
                    "rename": 0,
                    "preserve": 0,
                    "unsupported": 0,
                },
                "mapping": {"records": []},
                "mapping_execution": {"per_file_mapping": []},
            },
            elapsed=0.5,
        )
        rows = _report_rows(text)
        self.assertEqual(rows["加密率"], "n/a")
        self.assertEqual(rows["文件覆盖率"], "n/a")
        self.assertNotIn("0.00%", text)
        self.assertEqual(rows["加密文件数"], "0")
        self.assertEqual(rows["实际修改对象数"], "0")

    def test_missing_fields_do_not_crash_the_report(self):
        rows = _report_rows(
            rewrite._cli_vnext_terminal_report({}, elapsed=0.0)
        )
        self.assertEqual(rows["总代码行数"], "n/a")
        self.assertEqual(rows["加密率"], "n/a")


class T116FailurePositionTests(unittest.TestCase):
    """Section 3.3: each failure class must name a position, and stay a failure."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="t116-failure-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.project = self.root / "proj"
        self.project.mkdir()
        self._write(
            "ok.sv",
            """
            module t116_ok (
                input  logic clk,
                input  logic [3:0] data_in,
                output logic [3:0] data_out
            );
                logic [3:0] hold_value;
                always_ff @(posedge clk) hold_value <= data_in;
                assign data_out = hold_value;
            endmodule
            """,
        )

    def _write(self, name: str, body: str) -> Path:
        path = self.project / name
        text = "\n".join(line[12:] if line.startswith(" " * 12) else line
                         for line in body.strip("\n").splitlines())
        path.write_text(text + "\n", encoding="utf-8")
        return path

    def _line_of(self, path: Path, needle: str) -> int:
        lines = path.read_text(encoding="utf-8").splitlines()
        matched = [
            number for number, line in enumerate(lines, start=1) if needle in line
        ]
        self.assertEqual(len(matched), 1, (path.name, needle))
        return matched[0]

    def _encrypt(self, filelist: Path) -> subprocess.CompletedProcess[str]:
        return _run(
            "--filelist", str(filelist),
            "--category", "all",
            "--output-dir", str(self.root / f"gate-{filelist.stem}"),
        )

    def test_missing_file_reports_its_absolute_path_and_filelist_line(self):
        filelist = self._write(
            "missing.f",
            """
            // wrapper filelist: the original one is never edited
            ok.sv
            absent_unit.sv
            """,
        )
        result = self._encrypt(filelist)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("error: CLI_VNEXT_INPUT_INVALID", result.stderr)
        self.assertIn("detail: SOURCESET_FILE_NOT_FOUND", result.stderr)
        absolute = (self.project / "absent_unit.sv").resolve()
        self.assertFalse(absolute.exists())
        self.assertIn(f"position: {absolute.as_posix()}", result.stderr)
        self.assertIn(
            f"filelist: {filelist.resolve().as_posix()}:"
            f"{self._line_of(filelist, 'absent_unit.sv')}",
            result.stderr,
        )
        self.assertFalse((self.root / "gate-missing").exists())

    def test_missing_file_named_by_a_nested_filelist_reports_that_filelist(self):
        """``-f`` recursion is why the origin has to be reported, not assumed."""

        nested = self._write(
            "nested.f",
            """
            // the entry that fails lives here, not in the wrapper
            absent_nested.sv
            """,
        )
        wrapper = self._write(
            "wrapper.f",
            """
            ok.sv
            -f nested.f
            """,
        )
        result = self._encrypt(wrapper)
        self.assertEqual(result.returncode, 1, result.stderr)
        absolute = (self.project / "absent_nested.sv").resolve()
        self.assertIn(f"position: {absolute.as_posix()}", result.stderr)
        self.assertIn(
            f"filelist: {nested.resolve().as_posix()}:"
            f"{self._line_of(nested, 'absent_nested.sv')}",
            result.stderr,
        )

    def test_parse_error_reports_file_line_and_column_with_the_diagnostic(self):
        source = self._write(
            "syntax.sv",
            """
            module t116_syntax (
                input  logic clk,
                output logic q
            );
                logic latched
                always_ff @(posedge clk) latched <= ~latched;
                assign q = latched;
            endmodule
            """,
        )
        filelist = self._write("syntax.f", "ok.sv\nsyntax.sv")
        result = self._encrypt(filelist)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("parse errors", result.stderr)
        expected_line = self._line_of(source, "logic latched")
        positions = [
            POSITION.match(line)
            for line in result.stderr.splitlines()
            if POSITION.match(line)
        ]
        self.assertEqual(len(positions), 1, result.stderr)
        file, line, column, code = positions[0].groups()
        self.assertEqual(file, "syntax.sv")
        self.assertEqual(int(line), expected_line)
        self.assertGreater(int(column), 0)
        self.assertIn("DiagCode", code)
        self.assertIn("diagnostics: 共 1 条，以下列出前 1 条", result.stderr)
        self.assertIn("源码: logic latched", result.stderr)

    def test_elaborate_error_reports_file_line_and_column_with_the_diagnostic(self):
        source = self._write(
            "elab.sv",
            """
            module t116_elab (
                input  logic clk,
                output logic q
            );
                t116_absent_child child_instance (.clk(clk), .q(q));
            endmodule
            """,
        )
        filelist = self._write("elab.f", "ok.sv\nelab.sv")
        result = self._encrypt(filelist)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("semantic errors", result.stderr)
        expected_line = self._line_of(source, "t116_absent_child")
        positions = [
            POSITION.match(line)
            for line in result.stderr.splitlines()
            if POSITION.match(line)
        ]
        self.assertEqual(len(positions), 1, result.stderr)
        file, line, _column, code = positions[0].groups()
        self.assertEqual(file, "elab.sv")
        self.assertEqual(int(line), expected_line)
        self.assertEqual(code, "DiagCode(UnknownModule)")

    def test_diagnostic_list_is_capped_and_states_the_total(self):
        body = ["module t116_many (input logic clk, output logic q);"]
        body.extend(
            f"    t116_absent_{index} u{index} (.clk(clk));" for index in range(14)
        )
        body.extend(("    assign q = clk;", "endmodule"))
        self._write("many.sv", "\n".join(body))
        filelist = self._write("many.f", "ok.sv\nmany.sv")
        result = self._encrypt(filelist)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("diagnostics: 共 14 条，以下列出前 10 条", result.stderr)
        positions = [
            line for line in result.stderr.splitlines() if POSITION.match(line)
        ]
        self.assertEqual(len(positions), rewrite._CLI_VNEXT_DIAGNOSTIC_EXAMPLES)

    def test_quiet_does_not_silence_a_failure(self):
        filelist = self._write("missing.f", "ok.sv\nabsent_unit.sv")
        result = _run(
            "--filelist", str(filelist),
            "--category", "all",
            "--quiet",
            "--output-dir", str(self.root / "gate-quiet"),
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("error: CLI_VNEXT_INPUT_INVALID", result.stderr)
        self.assertIn("position: ", result.stderr)
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
