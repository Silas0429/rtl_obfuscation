from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from rtl_obfuscator.source_set import SourceSetError, from_filelist


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "t093_macro_fallback"
PUBLIC_ENCRYPT = ROOT / "rtl_encrypt.py"


class T093MacroFallbackAndCliTests(unittest.TestCase):
    @staticmethod
    def _run_public(*arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(PUBLIC_ENCRYPT), *arguments],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )

    @staticmethod
    def _run_internal(*arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "rtl_obfuscator.rewrite", *arguments],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )

    def test_fallback_and_unconditional_provider_is_valid(self):
        source_text = (FIXTURE_ROOT / "rtl" / "top.sv").read_text(encoding="utf-8")
        filelist_text = (FIXTURE_ROOT / "design.f").read_text(encoding="utf-8")
        self.assertNotIn("`include", source_text)
        self.assertIn("rtl/fallback.h", filelist_text)
        self.assertIn("rtl/config.h", filelist_text)
        result = from_filelist(
            filelist=FIXTURE_ROOT / "design.f",
            top="t093_top",
        )
        self.assertEqual(result.ordered_source_files, ("rtl/top.sv",))
        self.assertEqual(result.included_files, ("rtl/config.h", "rtl/fallback.h"))
        self.assertEqual(result.top_closure_files, ("rtl/top.sv",))

    def test_unconditional_ambiguity_is_fail_closed_with_provider_details(self):
        with self.assertRaises(SourceSetError) as raised:
            from_filelist(
                filelist=FIXTURE_ROOT / "ambiguous.f",
                top="t093_top",
            )
        error = raised.exception
        self.assertEqual(error.code, "SOURCESET_DISCOVERY_FAILED")
        self.assertEqual(error.path, "rtl/ambiguous_top.sv")
        self.assertEqual(error.message, "macro has multiple providers: T093_WIDTH")
        self.assertEqual(
            error.details,
            [
                {"provider": "rtl/ambiguous_one.h"},
                {"provider": "rtl/ambiguous_two.h"},
            ],
        )

    def test_public_discovery_error_prints_structured_diagnostic_and_no_output(self):
        with tempfile.TemporaryDirectory(prefix="t093-public-diagnostic-") as temporary:
            output = Path(temporary) / "gate"
            result = self._run_public(
                "--filelist",
                str(FIXTURE_ROOT / "ambiguous.f"),
                "--top",
                "t093_top",
                "--category",
                "signals",
                "--output-dir",
                str(output),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")
            self.assertIn("error: CLI_VNEXT_INPUT_INVALID\n", result.stderr)
            self.assertIn("detail: SOURCESET_DISCOVERY_FAILED\n", result.stderr)
            self.assertIn("path: rtl/ambiguous_top.sv\n", result.stderr)
            self.assertIn("message: macro has multiple providers: T093_WIDTH\n", result.stderr)
            self.assertIn("rtl/ambiguous_one.h", result.stderr)
            self.assertIn("rtl/ambiguous_two.h", result.stderr)
            self.assertIn("hint: ", result.stderr)
            self.assertFalse(output.exists())

    def test_public_filelist_source_root_conflict_is_rejected_without_output(self):
        with tempfile.TemporaryDirectory(prefix="t093-public-conflict-") as temporary:
            output = Path(temporary) / "gate"
            result = self._run_public(
                "--filelist",
                str(FIXTURE_ROOT / "design.f"),
                "--source-root",
                str(FIXTURE_ROOT),
                "--top",
                "t093_top",
                "--output-dir",
                str(output),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")
            self.assertIn("error: CLI_VNEXT_INPUT_INVALID\n", result.stderr)
            self.assertIn("filelist mode does not accept --source-root", result.stderr)
            self.assertFalse(output.exists())

    def test_public_missing_filelist_keeps_structured_path_diagnostic(self):
        with tempfile.TemporaryDirectory(prefix="t093-public-missing-filelist-") as temporary:
            root = Path(temporary)
            filelist = root / "missing.f"
            output = root / "gate"
            result = self._run_public(
                "--filelist",
                str(filelist),
                "--top",
                "t093_top",
                "--output-dir",
                str(output),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")
            self.assertIn("error: CLI_VNEXT_INPUT_INVALID\n", result.stderr)
            self.assertIn("detail: SOURCESET_FILE_NOT_FOUND\n", result.stderr)
            self.assertIn("path: missing.f\n", result.stderr)
            self.assertIn("message: filelist does not exist\n", result.stderr)
            self.assertIn("hint: ", result.stderr)
            self.assertFalse(output.exists())

    def test_internal_filelist_and_single_file_cannot_use_project_root(self):
        with tempfile.TemporaryDirectory(prefix="t093-internal-conflict-") as temporary:
            root = Path(temporary)
            for mode_arguments in (
                (
                    "--filelist",
                    str(FIXTURE_ROOT / "design.f"),
                    "--project-root",
                    str(FIXTURE_ROOT),
                ),
                (
                    "--input",
                    "rtl/top.sv",
                    "--project-root",
                    str(FIXTURE_ROOT),
                ),
            ):
                output = root / f"gate-{len(list(root.iterdir()))}"
                result = self._run_internal(
                    "encrypt-vnext",
                    *mode_arguments,
                    "--top",
                    "t093_top",
                    "--map",
                    str(root / "mapping.json"),
                    "--metrics",
                    str(root / "metrics.json"),
                    "--output-dir",
                    str(output),
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
                self.assertIn("error: CLI_VNEXT_INPUT_INVALID\n", result.stderr)
                self.assertIn("detail: CLI_VNEXT_INPUT_INVALID\n", result.stderr)
                self.assertIn("mutually exclusive", result.stderr)
                self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
