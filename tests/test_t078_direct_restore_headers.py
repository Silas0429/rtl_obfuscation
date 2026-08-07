from __future__ import annotations

import argparse
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from rtl_obfuscator import orchestration_vnext
from rtl_obfuscator import restore_vnext
from rtl_obfuscator import rewrite as rewrite_module
from rtl_obfuscator.source_catalog import build_source_catalog
from rtl_obfuscator.source_set import from_filelist


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "t078_direct_restore_headers"
PUBLIC_SCRIPTS = {
    "rtl_encrypt": ROOT / "rtl_encrypt.py",
    "rtl_decrypt": ROOT / "rtl_decrypt.py",
}
PHYSICAL_FILES = ("top.sv", "defs.svh")


class T078DirectRestoreHeaderTests(unittest.TestCase):
    @staticmethod
    def _run_public(
        command: str, *arguments: str
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(PUBLIC_SCRIPTS[command]), *arguments],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )

    def _encrypt(self, root: Path) -> tuple[Path, Path, dict[str, object]]:
        root.mkdir(parents=True, exist_ok=True)
        gate = root / "gate"
        result = self._run_public(
            "rtl_encrypt",
            "--filelist",
            "design.f",
            "--source-root",
            str(FIXTURE_ROOT),
            "--top",
            "t078_header_top",
            "--category",
            "signals",
            "--output-dir",
            str(gate),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        mapping = gate / "mapping.json"
        report = json.loads(mapping.read_text(encoding="utf-8"))
        self.assertEqual(
            json.loads(result.stdout)["summary"], report["summary"]
        )
        return gate, mapping, report

    @staticmethod
    def _formal(gate_dir: Path):
        command = [
            sys.executable,
            "scripts/formal_equivalence.py",
            "--gold-filelist",
            "tests/fixtures/t078_direct_restore_headers/design.f",
            "--gold-root",
            "tests/fixtures/t078_direct_restore_headers",
            "--gate-filelist",
            str(gate_dir / "design.f"),
            "--gate-root",
            str(gate_dir),
            "--top",
            "t078_header_top",
            "--seq",
            "5",
        ]
        return subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        ), command

    @staticmethod
    def _manifest_files(value: object) -> tuple[str, ...]:
        assert isinstance(value, list)
        return tuple(item["file"] for item in value)

    def _assert_public_failure(
        self,
        gate: Path,
        *,
        code: str,
        label: str,
    ) -> None:
        output = gate.parent / f"{label}-restore"
        restore_report = gate.parent / f"{label}-restore.json"
        result = self._run_public(
            "rtl_decrypt",
            "--map",
            str(gate / "mapping.json"),
            "--gate-dir",
            str(gate),
            "--output-dir",
            str(output),
            "--report",
            str(restore_report),
        )
        self.assertNotEqual(result.returncode, 0, label)
        self.assertTrue(
            result.stderr.startswith(f"error: {code}"),
            (label, result.stderr),
        )
        self.assertNotIn("Traceback", result.stderr)
        self.assertFalse(output.exists())
        self.assertFalse(restore_report.exists())

    def test_public_encrypt_persists_compile_and_physical_orders(self):
        with tempfile.TemporaryDirectory(prefix="t078-encrypt-") as temporary:
            gate, _mapping, report = self._encrypt(Path(temporary))
            self.assertEqual(
                report["source_set"],
                {
                    "schema_version": 1,
                    "origin": "filelist",
                    "ordered_source_files": ["top.sv"],
                    "included_files": ["defs.svh"],
                    "include_dirs": [],
                    "defines": [],
                    "top": "t078_header_top",
                    "top_closure_files": ["top.sv"],
                    "compile_order": ["top.sv"],
                },
            )
            self.assertEqual((gate / "design.f").read_bytes(), b"top.sv\n")
            self.assertTrue((gate / "top.sv").is_file())
            self.assertTrue((gate / "defs.svh").is_file())
            for manifest in (
                report["mapping"]["input_manifest"],
                report["mapping_execution"]["mapping"]["input_manifest"],
                report["mapping_execution"]["input_manifest"],
                report["mapping_execution"]["gate_manifest"],
                report["mapping_execution"]["restored_manifest"],
            ):
                self.assertEqual(self._manifest_files(manifest), PHYSICAL_FILES)
            summary = report["summary"]
            self.assertEqual(
                (
                    summary["files"],
                    summary["mapping_records"],
                    summary["modified_tokens"],
                    summary["strict_compile_passed"],
                    summary["restored_byte_identical"],
                ),
                (2, 4, 3, True, True),
            )
            records = report["mapping"]["records"]
            self.assertEqual(
                [
                    record
                    for record in records
                    if record["action"] == "rename"
                ][0]["category"],
                "signals",
            )
            self.assertEqual(
                sum(record["action"] == "rename" for record in records), 1
            )
            task = (
                ROOT / "docs/tasks/T078_direct_restore_header_physical_order.md"
            ).read_text(encoding="utf-8")
            self.assertIn(
                "direct API 精确 code=`RESTORE_VNEXT_INPUT_INVALID`、message=`source_set physical order is invalid`",
                task,
            )

    def test_public_direct_restore_without_original_source_or_design_file(self):
        with tempfile.TemporaryDirectory(prefix="t078-public-restore-") as temporary:
            root = Path(temporary)
            gate, mapping, _report = self._encrypt(root / "encrypt")
            output = root / "restore"
            result = self._run_public(
                "rtl_decrypt",
                "--map",
                str(mapping),
                "--gate-dir",
                str(gate),
                "--output-dir",
                str(output),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                {
                    path.relative_to(output).as_posix()
                    for path in output.rglob("*")
                    if path.is_file()
                },
                set(PHYSICAL_FILES),
            )
            for file in PHYSICAL_FILES:
                self.assertEqual(
                    (output / file).read_bytes(),
                    (FIXTURE_ROOT / file).read_bytes(),
                )
            self.assertFalse((output / "design.f").exists())

            report_output = root / "restore-with-report"
            restore_report = root / "restore.json"
            reported = self._run_public(
                "rtl_decrypt",
                "--map",
                str(mapping),
                "--gate-dir",
                str(gate),
                "--output-dir",
                str(report_output),
                "--report",
                str(restore_report),
            )
            self.assertEqual(reported.returncode, 0, reported.stderr)
            persisted = json.loads(restore_report.read_text(encoding="utf-8"))
            self.assertTrue(
                persisted["summary"]["restored_input_manifest_equal"]
            )
            self.assertEqual(
                self._manifest_files(persisted["restored_manifest"]),
                PHYSICAL_FILES,
            )
            for file in PHYSICAL_FILES:
                self.assertEqual(
                    (report_output / file).read_bytes(),
                    (FIXTURE_ROOT / file).read_bytes(),
                )

    def test_direct_api_and_public_adapter_share_gate_audit(self):
        with tempfile.TemporaryDirectory(prefix="t078-shared-audit-") as temporary:
            root = Path(temporary)
            gate, mapping, _report = self._encrypt(root / "encrypt")
            original_loader = (
                restore_vnext._load_orchestration_gate_inputs_vnext
            )
            with mock.patch.object(
                orchestration_vnext,
                "run_vnext",
                side_effect=AssertionError("regenerate orchestration"),
            ), mock.patch.object(
                restore_vnext,
                "_load_orchestration_gate_inputs_vnext",
                wraps=original_loader,
            ) as direct_audit:
                direct = restore_vnext.load_direct_restore_vnext(
                    mapping,
                    gate_dir=gate,
                    output_dir=root / "direct",
                )
            self.assertEqual(direct_audit.call_count, 1)
            self.assertEqual(
                direct.restore_result.restored_manifest,
                direct.mapping_vnext.input_manifest,
            )

            args = argparse.Namespace(
                public_cli=True,
                map_file=mapping,
                gate_dir=gate,
                output_dir=root / "public",
                report=None,
            )
            with mock.patch.object(
                orchestration_vnext,
                "run_vnext",
                side_effect=AssertionError("regenerate orchestration"),
            ), mock.patch.object(
                restore_vnext,
                "_load_orchestration_gate_inputs_vnext",
                wraps=original_loader,
            ) as public_audit:
                summary = rewrite_module._decrypt_vnext(args)
            self.assertEqual(public_audit.call_count, 1)
            self.assertEqual(summary["format"], "rtl-obfuscation.restore-vnext-cli")
            for directory in (root / "direct", root / "public"):
                for file in PHYSICAL_FILES:
                    self.assertEqual(
                        (directory / file).read_bytes(),
                        (FIXTURE_ROOT / file).read_bytes(),
                    )

    def test_persisted_source_set_noncanonical_orders_fail_closed(self):
        with tempfile.TemporaryDirectory(prefix="t078-order-tamper-") as temporary:
            root = Path(temporary)
            gate, _mapping, _report = self._encrypt(root / "encrypt")
            mutations = {
                "compile-header": lambda value: value["source_set"][
                    "compile_order"
                ].append("defs.svh"),
                "ordered-duplicate": lambda value: value["source_set"][
                    "ordered_source_files"
                ].append("top.sv"),
                "included-duplicate": lambda value: value["source_set"][
                    "included_files"
                ].append("defs.svh"),
                "source-header-overlap": lambda value: value["source_set"][
                    "included_files"
                ].append("top.sv"),
            }
            for label, mutate in mutations.items():
                tampered = root / label
                shutil.copytree(gate, tampered)
                value = json.loads(
                    (tampered / "mapping.json").read_text(encoding="utf-8")
                )
                mutate(value)
                (tampered / "mapping.json").write_text(
                    json.dumps(value), encoding="utf-8"
                )
                self._assert_public_failure(
                    tampered,
                    code="RESTORE_VNEXT_INPUT_INVALID",
                    label=label,
                )

    def test_gate_design_header_hash_and_file_set_tampering_fail_closed(self):
        with tempfile.TemporaryDirectory(prefix="t078-gate-tamper-") as temporary:
            root = Path(temporary)
            gate, _mapping, _report = self._encrypt(root / "encrypt")

            design = root / "design-header"
            shutil.copytree(gate, design)
            (design / "design.f").write_bytes(b"top.sv\ndefs.svh\n")
            self._assert_public_failure(
                design,
                code="RESTORE_VNEXT_GATE_INVALID",
                label="design-header",
            )

            header = root / "header-bytes"
            shutil.copytree(gate, header)
            header_file = header / "defs.svh"
            header_file.write_bytes(header_file.read_bytes() + b" ")
            self._assert_public_failure(
                header,
                code="RESTORE_VNEXT_GATE_INVALID",
                label="header-bytes",
            )

            unexpected = root / "unexpected-file"
            shutil.copytree(gate, unexpected)
            (unexpected / "unexpected.sv").write_bytes(
                b"module unexpected; endmodule\n"
            )
            self._assert_public_failure(
                unexpected,
                code="RESTORE_VNEXT_GATE_INVALID",
                label="unexpected-file",
            )

    def test_actual_gate_strict_compile_restore_and_formal_positive(self):
        with tempfile.TemporaryDirectory(
            prefix="t078-formal-positive-"
        ) as temporary:
            root = Path(temporary)
            gate, mapping, _report = self._encrypt(root / "encrypt")
            gate_set = from_filelist(
                filelist=gate / "design.f",
                source_root=gate,
                top="t078_header_top",
            )
            self.assertEqual(
                build_source_catalog(gate_set).to_report()["compile"],
                {
                    "catalog": {"parse_errors": 0, "semantic_errors": 0},
                    "top_overlay": {
                        "parse_errors": 0,
                        "semantic_errors": 0,
                    },
                },
            )
            output = root / "restore"
            result = self._run_public(
                "rtl_decrypt",
                "--map",
                str(mapping),
                "--gate-dir",
                str(gate),
                "--output-dir",
                str(output),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            formal, command = self._formal(gate)
            print(f"T078_FORMAL_GATE {gate}")
            print(f"T078_FORMAL_COMMAND {shlex.join(command)}")
            print(f"T078_FORMAL_EXIT {formal.returncode}")
            print(f"T078_FORMAL_JSON {formal.stdout.strip()}")
            self.assertEqual(formal.returncode, 0, formal.stdout + formal.stderr)
            self.assertEqual(
                json.loads(formal.stdout.strip().splitlines()[-1]),
                {
                    "formal_equivalence": "pass",
                    "gate": str(gate),
                    "gold": "tests/fixtures/t078_direct_restore_headers",
                    "seq": 5,
                    "top": "t078_header_top",
                },
            )

    def test_fixed_function_negative_strict_compiles_and_formal_fails(self):
        with tempfile.TemporaryDirectory(
            prefix="t078-formal-negative-"
        ) as temporary:
            root = Path(temporary)
            gate, _mapping, _report = self._encrypt(root / "encrypt")
            negative = root / "negative"
            shutil.copytree(gate, negative)
            top = negative / "top.sv"
            original = top.read_bytes()
            marker = b"assign data_o = "
            self.assertEqual(original.count(marker), 1)
            top.write_bytes(original.replace(marker, b"assign data_o = ~", 1))
            negative_set = from_filelist(
                filelist=negative / "design.f",
                source_root=negative,
                top="t078_header_top",
            )
            negative_compile = build_source_catalog(negative_set).to_report()[
                "compile"
            ]
            self.assertEqual(
                negative_compile,
                {
                    "catalog": {"parse_errors": 0, "semantic_errors": 0},
                    "top_overlay": {
                        "parse_errors": 0,
                        "semantic_errors": 0,
                    },
                },
            )
            formal, command = self._formal(negative)
            combined_output = formal.stdout + formal.stderr
            key_output = "\n".join(
                line
                for line in combined_output.splitlines()
                if "unproven" in line.lower()
                or "equiv_status -assert" in line.lower()
            )
            print(f"T078_FORMAL_NEGATIVE_GATE {negative}")
            print(f"T078_FORMAL_NEGATIVE_COMMAND {shlex.join(command)}")
            print(
                "T078_FORMAL_NEGATIVE_COMPILE "
                + json.dumps(negative_compile, sort_keys=True)
            )
            print(f"T078_FORMAL_NEGATIVE_EXIT {formal.returncode}")
            print(f"T078_FORMAL_NEGATIVE_OUTPUT {key_output}")
            combined = combined_output.lower()
            self.assertNotEqual(formal.returncode, 0)
            self.assertIn("unproven", combined)
            self.assertIn("equiv_status -assert", combined)

    def test_future_work_records_t078_without_claiming_ibex_groups(self):
        future = (
            ROOT / "docs/development/future_work.md"
        ).read_text(encoding="utf-8")
        self.assertIn("T078", future)
        self.assertIn("compile_order", future)
        self.assertIn("included_files", future)
        self.assertIn("Ibex", future)
        self.assertIn("abi_group", future)
        self.assertIn("non_abi_group", future)


if __name__ == "__main__":
    unittest.main()
