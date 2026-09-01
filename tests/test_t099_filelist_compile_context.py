from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from rtl_obfuscator.project_discovery import compile_pyslang_source_set
from rtl_obfuscator.source_catalog import SourceCatalogError, build_source_catalog
from rtl_obfuscator.source_set import SourceSetError, from_filelist


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "t099_filelist_compile_context"
PUBLIC_ENCRYPT = ROOT / "rtl_encrypt.py"
PUBLIC_DECRYPT = ROOT / "rtl_decrypt.py"


class T099FilelistCompileContextTests(unittest.TestCase):
    SOURCES = (
        "rtl/t099_top.sv",
        "rtl/t099_child.v",
        "rtl/t099_pkg.sv",
        "rtl/t099_if.sv",
        "rtl/t099_unused.v",
    )
    HEADERS = ("include/t099_config.h", "include/t099_width.svh")
    COMPILE_ORDER = HEADERS + SOURCES

    @staticmethod
    def _run(script: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(script), *arguments],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )

    def test_filelist_order_headers_and_top_closure(self):
        all_sources = from_filelist(filelist=FIXTURE_ROOT / "design.f")
        self.assertEqual(all_sources.ordered_source_files, self.SOURCES)
        self.assertEqual(all_sources.included_files, self.HEADERS)
        self.assertEqual(all_sources.compile_order, self.COMPILE_ORDER)
        self.assertEqual(all_sources.top_closure_files, ())

        selected = from_filelist(
            filelist=FIXTURE_ROOT / "design.f", top="t099_top"
        )
        self.assertEqual(selected.ordered_source_files, self.SOURCES)
        self.assertEqual(selected.included_files, self.HEADERS)
        self.assertEqual(selected.compile_order, self.COMPILE_ORDER)
        self.assertEqual(selected.top_closure_files, ())
        catalog = build_source_catalog(selected)
        self.assertEqual(
            {module.name for module in catalog.modules if module.in_top_closure},
            {"t099_top", "t099_child"},
        )

    def test_missing_time_scale_is_nonblocking_for_sourceset_and_catalog(self):
        source_set = from_filelist(
            filelist=FIXTURE_ROOT / "design.f", top="t099_top"
        )
        view = compile_pyslang_source_set(
            root=FIXTURE_ROOT,
            compilation_files=source_set.compile_order,
            include_files=source_set.included_files,
            defines=dict(source_set.defines),
            top=source_set.top,
        )
        self.assertTrue(view.raw_errors)
        self.assertTrue(view.nonblocking_errors)
        self.assertTrue(
            all(str(error.code) == "DiagCode(MissingTimeScale)" for error in view.nonblocking_errors)
        )
        self.assertEqual(view.parse_errors, ())
        self.assertEqual(view.semantic_errors, ())

        catalog = build_source_catalog(source_set)
        self.assertEqual(
            catalog.to_report()["compile"],
            {
                "catalog": {"parse_errors": 0, "semantic_errors": 0},
                "top_overlay": {"parse_errors": 0, "semantic_errors": 0},
            },
        )

    def test_blocking_parse_and_semantic_errors_are_separate(self):
        missing_header_set = from_filelist(
            filelist=FIXTURE_ROOT / "missing_header.f", top="t099_top"
        )
        with self.assertRaises(SourceCatalogError) as missing_header:
            build_source_catalog(missing_header_set)
        self.assertEqual(missing_header.exception.code, "CATALOG_PARSE_FAILED")

        missing_child_set = from_filelist(
            filelist=FIXTURE_ROOT / "missing_child.f", top="t099_top"
        )
        with self.assertRaises(SourceCatalogError) as missing_child:
            build_source_catalog(missing_child_set)
        self.assertEqual(missing_child.exception.code, "CATALOG_SEMANTIC_FAILED")

        with tempfile.TemporaryDirectory(prefix="t099-public-failure-") as temporary:
            output = Path(temporary) / "gate"
            result = self._run(
                PUBLIC_ENCRYPT,
                "--filelist",
                str(FIXTURE_ROOT / "missing_header.f"),
                "--top",
                "t099_top",
                "--category",
                "signals",
                "--output-dir",
                str(output),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")
            self.assertIn("ORCHESTRATION_MAPPING_INVALID", result.stderr)
            self.assertFalse(output.exists())

            semantic_output = Path(temporary) / "semantic-gate"
            semantic_result = self._run(
                PUBLIC_ENCRYPT,
                "--filelist",
                str(FIXTURE_ROOT / "missing_child.f"),
                "--top",
                "t099_top",
                "--category",
                "signals",
                "--output-dir",
                str(semantic_output),
            )
            self.assertNotEqual(semantic_result.returncode, 0)
            self.assertEqual(semantic_result.stdout, "")
            self.assertIn("ORCHESTRATION_MAPPING_INVALID", semantic_result.stderr)
            self.assertFalse(semantic_output.exists())

    def _canonical_gold(self, root: Path) -> Path:
        shutil.copytree(FIXTURE_ROOT / "rtl", root / "rtl")
        shutil.copytree(FIXTURE_ROOT / "include", root / "include")
        design = root / "design.f"
        design.write_text("".join(f"{path}\n" for path in self.COMPILE_ORDER), encoding="utf-8")
        return design

    def test_public_signals_gate_restore_and_canonical_design(self):
        with tempfile.TemporaryDirectory(prefix="t099-public-") as temporary:
            root = Path(temporary)
            gate = root / "gate"
            result = self._run(
                PUBLIC_ENCRYPT,
                "--filelist",
                str(FIXTURE_ROOT / "design.f"),
                "--top",
                "t099_top",
                "--category",
                "signals",
                "--output-dir",
                str(gate),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            report = json.loads((gate / "mapping.json").read_text(encoding="utf-8"))
            self.assertGreater(payload["action_counts"]["rename"], 0)
            self.assertTrue(report["summary"]["strict_compile_passed"])
            self.assertTrue(report["summary"]["restored_byte_identical"])
            self.assertEqual(
                (gate / "design.f").read_text(encoding="utf-8"),
                "".join(f"{path}\n" for path in self.COMPILE_ORDER),
            )
            for relative in self.HEADERS:
                self.assertEqual(
                    (gate / relative).read_bytes(), (FIXTURE_ROOT / relative).read_bytes()
                )
                self.assertFalse(
                    any(
                        record["declaration"]["file"] == relative
                        or any(
                            occurrence["source_range"]["file"] == relative
                            for occurrence in record["occurrences"]
                        )
                        for record in report["mapping"]["records"]
                    )
                )

            restored = root / "restored"
            restored_result = self._run(
                PUBLIC_DECRYPT,
                "--map",
                str(gate / "mapping.json"),
                "--gate-dir",
                str(gate),
                "--output-dir",
                str(restored),
            )
            self.assertEqual(restored_result.returncode, 0, restored_result.stderr)
            for relative in (*self.SOURCES, *self.HEADERS):
                self.assertEqual(
                    (restored / relative).read_bytes(), (FIXTURE_ROOT / relative).read_bytes()
                )

    def test_actual_gate_formal_positive_and_functional_negative(self):
        with tempfile.TemporaryDirectory(prefix="t099-formal-") as temporary:
            root = Path(temporary)
            gate = root / "gate"
            result = self._run(
                PUBLIC_ENCRYPT,
                "--filelist",
                str(FIXTURE_ROOT / "design.f"),
                "--top",
                "t099_top",
                "--category",
                "signals",
                "--output-dir",
                str(gate),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            gold_design = self._canonical_gold(root / "gold")
            formal_arguments = [
                "scripts/formal_equivalence.py",
                "--gold-filelist",
                str(gold_design),
                "--gold-root",
                str(gold_design.parent),
                "--gate-filelist",
                str(gate / "design.f"),
                "--gate-root",
                str(gate),
                "--top",
                "t099_top",
                "--seq",
                "5",
            ]
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
            self.assertEqual(positive_json["top"], "t099_top")

            negative = root / "negative"
            shutil.copytree(gate, negative)
            top = negative / "rtl" / "t099_top.sv"
            contents = top.read_bytes()
            marker = contents.find(b"assign out_y =")
            self.assertGreaterEqual(marker, 0)
            line_end = contents.find(b"\n", marker)
            self.assertGreater(line_end, marker)
            contents = contents[:marker] + b"assign out_y = 1'b0;" + contents[line_end:]
            top.write_bytes(contents)
            negative_source_set = from_filelist(
                filelist=negative / "design.f", top="t099_top"
            )
            self.assertEqual(negative_source_set.compile_order, self.COMPILE_ORDER)
            negative_catalog = build_source_catalog(negative_source_set)
            self.assertEqual(
                negative_catalog.to_report()["compile"],
                {
                    "catalog": {"parse_errors": 0, "semantic_errors": 0},
                    "top_overlay": {"parse_errors": 0, "semantic_errors": 0},
                },
            )
            strict = subprocess.run(
                [
                    "iverilog",
                    "-g2012",
                    "-t",
                    "null",
                    "-s",
                    "t099_top",
                    "-D",
                    "YOSYS",
                    "-I",
                    str(negative / "include"),
                    *[str(negative / path) for path in self.COMPILE_ORDER],
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
