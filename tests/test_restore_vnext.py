from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from rtl_obfuscator import restore_vnext
from rtl_obfuscator.orchestration_vnext import run_vnext
from rtl_obfuscator.source_set import from_filelist


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "t108_pyslang_rename_index"


class RestoreVNextTests(unittest.TestCase):
    def test_schema_one_is_rejected_without_compatibility_hydration(self):
        source_set = from_filelist(filelist=FIXTURE / "design.f", top="top")
        with tempfile.TemporaryDirectory(prefix="t108-restore-") as temp:
            root = Path(temp)
            result = run_vnext(
                source_set,
                categories=("signals",),
                gate_dir=root / "gate",
                restore_dir=root / "restore",
            )
            report_path = root / "gate" / "mapping.json"
            report_path.write_text(json.dumps(result.to_report()), encoding="utf-8")
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["schema_version"] = 1
            report_path.write_text(json.dumps(report), encoding="utf-8")
            with self.assertRaises(restore_vnext.RestoreVNextError) as raised:
                restore_vnext.load_direct_restore_vnext(
                    report_path,
                    gate_dir=root / "gate",
                    output_dir=root / "rejected",
                )
            self.assertEqual(
                raised.exception.code, "RESTORE_MAPPING_VERSION_UNSUPPORTED"
            )

    def _persisted_flow(self, root: Path):
        source_set = from_filelist(filelist=FIXTURE / "design.f", top="top")
        result = run_vnext(
            source_set,
            categories=("all",),
            gate_dir=root / "gate",
            restore_dir=root / "restore",
        )
        report_path = root / "gate" / "mapping.json"
        report_path.write_text(json.dumps(result.to_report()), encoding="utf-8")
        return report_path, root / "gate"

    def test_direct_restore_checks_manifest_tamper_and_restores_original_bytes(self):
        with tempfile.TemporaryDirectory(prefix="t108-restore-audit-") as temp:
            root = Path(temp)
            report_path, gate = self._persisted_flow(root)
            restored = root / "direct-restore"
            result = restore_vnext.load_direct_restore_vnext(
                report_path, gate_dir=gate, output_dir=restored
            )
            self.assertEqual(result.schema_version, 2)
            for file in ("bus_if.sv", "design.sv", "macros.svh"):
                self.assertEqual(
                    (restored / file).read_bytes(),
                    (FIXTURE / file).read_bytes(),
                )

            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["mapping"]["input_manifest"][0]["sha256"] = "0" * 64
            report_path.write_text(json.dumps(report), encoding="utf-8")
            with self.assertRaises(restore_vnext.RestoreVNextError) as manifest:
                restore_vnext.load_direct_restore_vnext(
                    report_path,
                    gate_dir=gate,
                    output_dir=root / "manifest-rejected",
                )
            self.assertEqual(
                manifest.exception.code, "RESTORE_VNEXT_REPORT_INVALID"
            )

    def test_gate_tamper_and_output_path_conflict_are_rejected(self):
        with tempfile.TemporaryDirectory(prefix="t108-restore-paths-") as temp:
            root = Path(temp)
            report_path, gate = self._persisted_flow(root)
            target = gate / "design.sv"
            target.write_bytes(target.read_bytes() + b"\n")
            with self.assertRaises(restore_vnext.RestoreVNextError) as tamper:
                restore_vnext.load_direct_restore_vnext(
                    report_path,
                    gate_dir=gate,
                    output_dir=root / "tamper-rejected",
                )
            self.assertEqual(tamper.exception.code, "RESTORE_VNEXT_GATE_INVALID")

            with self.assertRaises(restore_vnext.RestoreVNextError) as conflict:
                restore_vnext.load_direct_restore_vnext(
                    report_path, gate_dir=gate, output_dir=gate
                )
            self.assertEqual(
                conflict.exception.code, "RESTORE_VNEXT_OUTPUT_INVALID"
            )
