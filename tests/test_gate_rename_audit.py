"""Checks for the read-only gate rename audit.

The audit exists because strict compilation cannot prove a rewrite correct.
Measured: reverting one renamed reference back to its old name leaves PySlang
with zero parse and zero semantic errors, because SystemVerilog's default
nettype absorbs the undeclared identifier as an implicit wire.  These tests
assert both directions — the auditor must flag that gate, and must not cry wolf
on an intact one.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
AUDITOR = REPOSITORY / "scripts" / "gate_rename_audit.py"
T110_FIXTURE = REPOSITORY / "tests" / "fixtures" / "t110_binding_fixes"
T112_FIXTURE = REPOSITORY / "tests" / "fixtures" / "t112_gate_rename_audit"


def _load_auditor():
    name = "t112_gate_rename_audit_module"
    cached = sys.modules.get(name)
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location(name, AUDITOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclass and annotations resolve through sys.modules, so register first.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _encrypt(filelist: Path, top: str, output: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(REPOSITORY / "rtl_encrypt.py"),
            "--filelist", str(filelist),
            "--top", top,
            "--category", "all",
            "--output-dir", str(output),
        ],
        cwd=REPOSITORY,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def _audit(map_path: Path, gate_dir: Path, gold_root: Path) -> tuple[int, dict]:
    completed = subprocess.run(
        [
            sys.executable, str(AUDITOR),
            "--map", str(map_path),
            "--gate-dir", str(gate_dir),
            "--gold-root", str(gold_root),
            "--quiet",
        ],
        cwd=REPOSITORY,
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode, json.loads(completed.stdout)


def _compile_gate(gate_dir: Path, source_set: dict) -> tuple[int, int]:
    """Compile a gate exactly as the product does and return its error counts."""

    if str(REPOSITORY) not in sys.path:
        sys.path.insert(0, str(REPOSITORY))
    from rtl_obfuscator.project_discovery import compile_pyslang_source_set

    view = compile_pyslang_source_set(
        root=gate_dir,
        compilation_files=tuple(source_set["compile_order"]),
        include_files=tuple(source_set.get("included_files", ())),
        include_dirs=tuple(source_set.get("include_dirs", ())),
        defines=dict(source_set.get("defines", ()) or ()),
        top=None,
    )
    return len(view.parse_errors), len(view.semantic_errors)


class GateRenameAuditTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = TemporaryDirectory(prefix="t112-audit-")
        base = Path(cls._temporary.name)
        cls.gate = base / "gate"
        _encrypt(T110_FIXTURE / "design.f", "t110_top", cls.gate)
        cls.mapping = json.loads((cls.gate / "mapping.json").read_text())
        cls.source_set = cls.mapping["source_set"]

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def _damaged_gate(self) -> tuple[Path, str, int]:
        """Copy the gate and revert one renamed reference to its old name.

        Not every reverted edit stays invisible to the compiler: reverting a
        connection *label* names a port that no longer exists, and strict
        compilation rightly rejects that.  This audit exists for the edits that
        the compiler accepts, so the damage point is chosen by trying candidates
        and keeping the first whose damaged gate still compiles with zero
        errors.  The search is deterministic for a fixed fixture.
        """

        candidates: list[tuple[str, str, str, dict]] = []
        for entry in self.mapping["mapping_execution"]["per_file_mapping"]:
            for record in entry["records"]:
                if record.get("action") != "rename":
                    continue
                for item in record["ranges"]:
                    if item.get("provenance") != "semantic_reference":
                        continue
                    candidates.append(
                        (
                            entry["file"],
                            record["original_name"],
                            record["renamed_name"],
                            item["gate_range"],
                        )
                    )
        self.assertTrue(candidates, "fixture has no semantic_reference edit")

        damaged = Path(self._temporary.name) / "damaged"
        for file, original, renamed, gate_range in candidates:
            if damaged.exists():
                shutil.rmtree(damaged)
            shutil.copytree(self.gate, damaged)
            path = damaged / file
            data = bytearray(path.read_bytes())
            start, end = gate_range["start"], gate_range["end"]
            if bytes(data[start:end]).decode(errors="replace") != renamed:
                continue
            data[start:end] = original.encode()
            path.write_bytes(bytes(data))
            if _compile_gate(damaged, self.source_set) == (0, 0):
                return damaged, original, start
        self.fail(
            "no reverted edit left the gate compiling cleanly; the audit's "
            "premise no longer holds for this fixture"
        )

    def test_intact_gate_is_clean(self) -> None:
        code, report = _audit(
            self.gate / "mapping.json", self.gate, T110_FIXTURE
        )
        self.assertEqual(report["verdict"], "clean", report["implicit_nets"])
        self.assertEqual(code, 0)
        self.assertEqual(report["implicit_nets"]["gate_only"], 0)
        self.assertEqual(report["renamed_range_bytes"]["mismatched"], 0)
        self.assertGreater(report["renamed_range_bytes"]["checked"], 0)
        self.assertEqual(report["compile"]["gold"]["semantic_errors"], 0)
        self.assertEqual(report["compile"]["gate"]["semantic_errors"], 0)

    def test_damaged_gate_still_compiles_but_is_flagged(self) -> None:
        damaged, original, offset = self._damaged_gate()

        # The premise of this whole audit: the damage is invisible to strict
        # compilation.  If this assertion ever fails, the compiler caught it and
        # the audit would be redundant for this shape.
        parse_errors, semantic_errors = _compile_gate(damaged, self.source_set)
        self.assertEqual((parse_errors, semantic_errors), (0, 0))

        code, report = _audit(self.gate / "mapping.json", damaged, T110_FIXTURE)
        self.assertEqual(report["verdict"], "suspect")
        self.assertEqual(code, 1)

        # Check 1 names the leftover identifier precisely.
        self.assertEqual(report["implicit_nets"]["gate_only"], 1)
        self.assertEqual(
            [item["name"] for item in report["implicit_nets"]["gate_only_detail"]],
            [original],
        )

        # Check 2 independently flags the same offset from the published bytes.
        self.assertGreater(report["renamed_range_bytes"]["mismatched"], 0)
        flagged = {
            item["start"]
            for item in report["renamed_range_bytes"]["misplaced_detail"]
            + report["renamed_range_bytes"]["leaked_detail"]
        }
        self.assertIn(offset, flagged)

    def test_gold_side_implicit_net_is_not_blamed_on_the_rewrite(self) -> None:
        """A design that already relies on an implicit net must stay clean.

        The gold net is renamed too, so the differencing has to translate gold
        names through the rename map; comparing raw spellings would report every
        renamed implicit net as newly introduced.
        """

        with TemporaryDirectory(prefix="t112-implicit-") as temporary:
            gate = Path(temporary) / "gate"
            _encrypt(
                T112_FIXTURE / "implicit_gold.f", "t112_implicit_top", gate
            )
            code, report = _audit(gate / "mapping.json", gate, T112_FIXTURE)
            self.assertGreater(
                report["implicit_nets"]["gold"], 0, "fixture must have one"
            )
            self.assertEqual(report["implicit_nets"]["gate_only"], 0)
            self.assertEqual(report["verdict"], "clean")
            self.assertEqual(code, 0)

    def test_report_identity_and_residual_is_report_only(self) -> None:
        code, report = _audit(
            self.gate / "mapping.json", self.gate, T110_FIXTURE
        )
        self.assertEqual(report["format"], "rtl-obfuscation.gate-rename-audit")
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(code, 0)
        # The residual scan is deliberately not part of the verdict: several
        # distinct symbols may share a spelling, so a hit needs human judgement.
        self.assertGreater(report["residual_old_names"]["count"], 0)
        self.assertEqual(report["verdict"], "clean")
        self.assertIn("report only", report["residual_old_names"]["note"])

    def test_schema_one_mapping_is_rejected(self) -> None:
        module = _load_auditor()
        with TemporaryDirectory(prefix="t112-schema-") as temporary:
            path = Path(temporary) / "mapping.json"
            path.write_text(
                json.dumps(
                    {
                        "format": "rtl-obfuscation.cli-vnext",
                        "mapping": {"schema_version": 1},
                    }
                )
            )
            with self.assertRaises(SystemExit) as raised:
                module._load_mapping(path)
            self.assertEqual(raised.exception.code, 2)

    def test_auditor_writes_no_file_without_json_flag(self) -> None:
        before = sorted(path.name for path in self.gate.iterdir())
        _audit(self.gate / "mapping.json", self.gate, T110_FIXTURE)
        self.assertEqual(sorted(path.name for path in self.gate.iterdir()), before)


if __name__ == "__main__":
    unittest.main()
