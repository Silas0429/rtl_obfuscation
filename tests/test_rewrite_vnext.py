from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest import mock

from rtl_obfuscator.mapping_vnext import build_mapping_vnext
from rtl_obfuscator.rename_index import build_rename_index
from rtl_obfuscator.rewrite_vnext import (
    RewriteVNextError,
    restore_gate_vnext,
    write_gate_vnext,
)
from rtl_obfuscator.source_catalog import build_source_catalog
from rtl_obfuscator.source_set import from_filelist
from rtl_obfuscator.systemverilog_names import secure_name_factory


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "t108_pyslang_rename_index"


class RewriteVNextTests(unittest.TestCase):
    def test_gate_compile_and_restore_are_byte_audited(self):
        source_set = from_filelist(filelist=FIXTURE / "design.f", top="top")
        index = build_rename_index(
            build_source_catalog(source_set), categories=("all",)
        )
        mapping = build_mapping_vnext(
            index, name_length=20, name_factory=secure_name_factory
        )
        physical = tuple(
            dict.fromkeys((*source_set.ordered_source_files, *source_set.included_files))
        )
        original = {file: (FIXTURE / file).read_bytes() for file in physical}
        with tempfile.TemporaryDirectory(prefix="t108-rewrite-") as temp:
            root = Path(temp)
            execution = write_gate_vnext(mapping, output_dir=root / "gate")
            self.assertEqual(execution.schema_version, 2)
            self.assertEqual(execution.compile_evidence.catalog_semantic_errors, 0)
            self.assertTrue(
                any(
                    (root / "gate" / file).read_bytes() != original[file]
                    for file in physical
                )
            )
            restored = restore_gate_vnext(
                execution, gate_dir=root / "gate", output_dir=root / "restore"
            )
            self.assertEqual(restored.schema_version, 2)
            self.assertEqual(
                {file: (root / "restore" / file).read_bytes() for file in physical},
                original,
            )

    def test_strict_failure_cleans_staging_and_destination_atomically(self):
        source_set = from_filelist(filelist=FIXTURE / "design.f", top="top")
        index = build_rename_index(
            build_source_catalog(source_set), categories=("all",)
        )
        mapping = build_mapping_vnext(
            index, name_length=20, name_factory=secure_name_factory
        )
        with tempfile.TemporaryDirectory(prefix="t108-rewrite-failure-") as temp:
            root = Path(temp)
            destination = root / "gate"
            with mock.patch(
                "rtl_obfuscator.rewrite_vnext.build_source_catalog",
                side_effect=RuntimeError("forced strict failure"),
            ):
                with self.assertRaises(RewriteVNextError) as raised:
                    write_gate_vnext(mapping, output_dir=destination)
            self.assertEqual(raised.exception.code, "REWRITE_GATE_COMPILE_FAILED")
            self.assertFalse(destination.exists())
            self.assertEqual(
                tuple(path.name for path in root.glob(".rewrite-vnext-*")), ()
            )

    def test_output_inside_source_root_is_rejected_before_editing(self):
        source_set = from_filelist(filelist=FIXTURE / "design.f", top="top")
        index = build_rename_index(
            build_source_catalog(source_set), categories=("signals",)
        )
        mapping = build_mapping_vnext(
            index, name_length=20, name_factory=secure_name_factory
        )
        with self.assertRaises(RewriteVNextError) as raised:
            write_gate_vnext(
                mapping,
                output_dir=Path(source_set.source_root) / "forbidden-gate",
            )
        self.assertEqual(raised.exception.code, "REWRITE_OUTPUT_INVALID")
