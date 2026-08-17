from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from rtl_obfuscator.source_set import (
    SourceSetError,
    from_filelist,
    from_project_root,
    from_single_file,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "t088_verilog_suffix"
PUBLIC_SCRIPTS = {
    "encrypt": ROOT / "rtl_encrypt.py",
    "decrypt": ROOT / "rtl_decrypt.py",
}


class VerilogSuffixTests(unittest.TestCase):
    @staticmethod
    def _run(script: str, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(PUBLIC_SCRIPTS[script]), *arguments],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )

    @staticmethod
    def _physical(report: dict[str, object]) -> tuple[str, ...]:
        source_set = report["source_set"]
        assert isinstance(source_set, dict)
        return tuple(
            dict.fromkeys(
                (*source_set["ordered_source_files"], *source_set["included_files"])
            )
        )

    def _encrypt(
        self, output: Path, *arguments: str
    ) -> tuple[Path, dict[str, object]]:
        result = self._run("encrypt", *arguments, "--output-dir", str(output))
        self.assertEqual(result.returncode, 0, result.stderr)
        stdout = json.loads(result.stdout)
        self.assertGreater(stdout["action_counts"]["rename"], 0)
        report = json.loads((output / "mapping.json").read_text(encoding="utf-8"))
        self.assertGreater(
            sum(record["action"] == "rename" for record in report["mapping"]["records"]),
            0,
        )
        self.assertTrue(report["summary"]["strict_compile_passed"])
        self.assertTrue(report["summary"]["restored_byte_identical"])
        return output, report

    def test_sourceset_accepts_mixed_v_and_vh_across_three_entries(self):
        single = from_single_file(
            source_file=FIXTURE_ROOT / "single.v", source_root=FIXTURE_ROOT
        )
        filelist = from_filelist(
            filelist=FIXTURE_ROOT / "design.f",
            source_root=FIXTURE_ROOT,
            top="t088_top",
        )
        project = from_project_root(project_root=FIXTURE_ROOT, top="t088_top")

        self.assertEqual(single.ordered_source_files, ("single.v",))
        self.assertEqual(single.included_files, ())
        self.assertEqual(filelist.ordered_source_files, ("rtl/child.v", "rtl/top.v"))
        self.assertEqual(filelist.included_files, ("include/internal.vh",))
        self.assertEqual(filelist.compile_order, ("rtl/child.v", "rtl/top.v"))
        self.assertEqual(project.ordered_source_files, filelist.ordered_source_files)
        self.assertEqual(project.included_files, filelist.included_files)
        self.assertEqual(project.top_closure_files, filelist.top_closure_files)
        self.assertEqual(project.compile_order, filelist.compile_order)
        self.assertNotIn("include/internal.vh", filelist.compile_order)
        self.assertNotIn("single.v", project.ordered_source_files)

    def test_filelist_preserves_mixed_sv_v_order_and_header_classification(self):
        with tempfile.TemporaryDirectory(prefix="t088-mixed-sourceset-") as temporary:
            root = Path(temporary)
            (root / "a.sv").write_text(
                "module mixed_sv; endmodule\n", encoding="utf-8"
            )
            (root / "b.v").write_text(
                "module mixed_v; endmodule\n", encoding="utf-8"
            )
            (root / "shared.vh").write_text(
                "`define MIXED_HEADER 1\n", encoding="utf-8"
            )
            filelist = root / "mixed.f"
            filelist.write_text("b.v\nshared.vh\na.sv\n", encoding="utf-8")

            result = from_filelist(filelist=filelist, source_root=root)

            self.assertEqual(result.ordered_source_files, ("b.v", "a.sv"))
            self.assertEqual(result.compile_order, ("b.v", "a.sv"))
            self.assertEqual(result.included_files, ("shared.vh",))
            self.assertNotIn("shared.vh", result.compile_order)

    def test_public_three_modes_preserve_suffixes_and_header_is_actually_rewritten(self):
        with tempfile.TemporaryDirectory(prefix="t088-public-") as temporary:
            root = Path(temporary)
            single, single_report = self._encrypt(
                root / "single",
                "--input",
                "single.v",
                "--source-root",
                str(FIXTURE_ROOT),
            )
            filelist, filelist_report = self._encrypt(
                root / "filelist",
                "--filelist",
                "design.f",
                "--source-root",
                str(FIXTURE_ROOT),
                "--top",
                "t088_top",
            )
            project, project_report = self._encrypt(
                root / "project",
                "--source-root",
                str(FIXTURE_ROOT),
                "--top",
                "t088_top",
            )

            self.assertTrue((single / "single.v").is_file())
            for report, gate in ((filelist_report, filelist), (project_report, project)):
                physical = self._physical(report)
                self.assertEqual(
                    set(physical),
                    {"rtl/child.v", "rtl/top.v", "include/internal.vh"},
                )
                self.assertTrue(all(path.endswith((".v", ".vh")) for path in physical))
                self.assertEqual(
                    (gate / "design.f").read_text(encoding="utf-8"),
                    "rtl/child.v\nrtl/top.v\n",
                )
                self.assertNotIn("header_wire", (gate / "include/internal.vh").read_text())
                header_records = [
                    record
                    for record in report["mapping"]["records"]
                    if record["action"] == "rename"
                    and record["declaration"]["file"] == "include/internal.vh"
                ]
                self.assertTrue(header_records)
                self.assertTrue(
                    any(
                        occurrence["source_range"]["file"] == "include/internal.vh"
                        for occurrence in header_records[0]["occurrences"]
                    )
                )
            self.assertEqual(
                filelist_report["source_set"]["compile_order"],
                project_report["source_set"]["compile_order"],
            )

            restored = root / "restored"
            result = self._run(
                "decrypt",
                "--map",
                str(filelist / "mapping.json"),
                "--gate-dir",
                str(filelist),
                "--output-dir",
                str(restored),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            for relative in self._physical(filelist_report):
                self.assertEqual(
                    (restored / relative).read_bytes(),
                    (FIXTURE_ROOT / relative).read_bytes(),
                )

    def test_invalid_suffixes_fail_closed_without_publishing_gate(self):
        with tempfile.TemporaryDirectory(prefix="t088-invalid-") as temporary:
            root = Path(temporary)
            shutil.copytree(FIXTURE_ROOT, root / "fixture")
            fixture = root / "fixture"
            (fixture / "single.txt").write_bytes((fixture / "single.v").read_bytes())
            (fixture / "single.V").write_bytes((fixture / "single.v").read_bytes())
            (fixture / "include" / "internal.VH").write_bytes(
                (fixture / "include" / "internal.vh").read_bytes()
            )

            with self.assertRaises(SourceSetError) as header_single:
                from_single_file(
                    source_file=fixture / "include" / "internal.vh",
                    source_root=fixture,
                )
            self.assertEqual(header_single.exception.code, "SOURCESET_UNSUPPORTED_FILE")

            for relative in ("single.txt", "single.V", "include/internal.vh"):
                gate = root / f"{relative.replace('.', '-')}-gate"
                result = self._run(
                    "encrypt",
                    "--input",
                    relative,
                    "--source-root",
                    str(fixture),
                    "--output-dir",
                    str(gate),
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
                self.assertFalse(gate.exists())

            bad_filelist = fixture / "bad.f"
            bad_filelist.write_text("include/internal.VH\n", encoding="utf-8")
            gate = root / "bad-filelist-gate"
            result = self._run(
                "encrypt",
                "--filelist",
                "bad.f",
                "--source-root",
                str(fixture),
                "--output-dir",
                str(gate),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(gate.exists())

    def test_public_help_names_both_source_suffixes(self):
        result = self._run("encrypt", "--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(".sv", result.stdout)
        self.assertIn(".v", result.stdout)

    def test_include_escape_is_stable_and_does_not_publish(self):
        self.assertIn(
            '`include "../include/internal.vh"',
            (FIXTURE_ROOT / "rtl" / "child.v").read_text(encoding="utf-8"),
        )
        in_root = from_project_root(project_root=FIXTURE_ROOT, top="t088_top")
        self.assertIn("include/internal.vh", in_root.included_files)

        with tempfile.TemporaryDirectory(prefix="t088-include-escape-") as temporary:
            root = Path(temporary)
            rtl = root / "rtl"
            rtl.mkdir()
            (rtl / "top.v").write_text(
                'module escaped_top;\n  `include "../../outside.vh"\nendmodule\n',
                encoding="utf-8",
            )
            with self.assertRaises(SourceSetError) as raised:
                from_project_root(project_root=root, top="escaped_top")
            self.assertEqual(raised.exception.code, "SOURCESET_PATH_OUTSIDE_ROOT")

            gate = root / "gate"
            result = self._run(
                "encrypt",
                "--source-root",
                str(root),
                "--top",
                "escaped_top",
                "--output-dir",
                str(gate),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")
            self.assertFalse(gate.exists())

    def test_actual_gate_formal_positive_and_functional_negative(self):
        with tempfile.TemporaryDirectory(prefix="t088-formal-") as temporary:
            root = Path(temporary)
            gate, _report = self._encrypt(
                root / "gate",
                "--filelist",
                "design.f",
                "--source-root",
                str(FIXTURE_ROOT),
                "--top",
                "t088_top",
            )
            formal_arguments = (
                "scripts/formal_equivalence.py",
                "--gold-filelist",
                str(FIXTURE_ROOT / "design.f"),
                "--gold-root",
                str(FIXTURE_ROOT),
                "--gate-filelist",
                str(gate / "design.f"),
                "--gate-root",
                str(gate),
                "--top",
                "t088_top",
                "--seq",
                "5",
            )
            positive = subprocess.run(
                [sys.executable, *formal_arguments],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
            self.assertEqual(positive.returncode, 0, positive.stdout + positive.stderr)
            positive_json = json.loads(positive.stdout.strip().splitlines()[-1])
            self.assertEqual(positive_json["formal_equivalence"], "pass")
            self.assertEqual(positive_json["top"], "t088_top")
            self.assertEqual(positive_json["seq"], 5)

            negative = root / "negative"
            shutil.copytree(gate, negative)
            child = negative / "rtl" / "child.v"
            contents = child.read_bytes()
            self.assertEqual(contents.count(b" ^ "), 1)
            child.write_bytes(contents.replace(b" ^ ", b" | ", 1))
            strict = subprocess.run(
                [
                    "iverilog",
                    "-g2012",
                    "-t",
                    "null",
                    "-s",
                    "t088_top",
                    "-I",
                    str(negative / "rtl"),
                    str(negative / "rtl" / "child.v"),
                    str(negative / "rtl" / "top.v"),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
            self.assertEqual(strict.returncode, 0, strict.stdout + strict.stderr)
            negative_arguments = list(formal_arguments)
            negative_arguments[negative_arguments.index(str(gate / "design.f"))] = str(
                negative / "design.f"
            )
            negative_arguments[negative_arguments.index(str(gate))] = str(negative)
            negative_result = subprocess.run(
                [sys.executable, *negative_arguments],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
            combined = (negative_result.stdout + negative_result.stderr).lower()
            self.assertNotEqual(negative_result.returncode, 0)
            self.assertIn("unproven", combined)
            self.assertIn("equiv_status -assert", combined)


if __name__ == "__main__":
    unittest.main()
