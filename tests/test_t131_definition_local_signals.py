from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from rtl_obfuscator.fast_local_signals import build_fast_local_signals_mapping
from rtl_obfuscator.orchestration_vnext import run_vnext
from rtl_obfuscator.source_set import from_filelist


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "t131_definition_local_signals"
ENCRYPT = ROOT / "rtl_encrypt.py"
DECRYPT = ROOT / "rtl_decrypt.py"
FORMAL = ROOT / "scripts" / "formal_equivalence.py"


class T131DefinitionLocalSignalsTests(unittest.TestCase):
    @staticmethod
    def _name_factory():
        counter = 0

        def factory(_symbol_id: str, length: int, unavailable: frozenset[str]) -> str:
            nonlocal counter
            while True:
                candidate = f"q{counter:0{length - 1}d}"
                counter += 1
                if candidate not in unavailable:
                    return candidate

        return factory

    @staticmethod
    def _run_cli(output: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(ENCRYPT),
                "--filelist",
                str(FIXTURE / "design.f"),
                "--rewrite-root",
                str(FIXTURE / "owned"),
                "--category",
                "signals",
                "--output-dir",
                str(output),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )

    def test_unelaborated_modules_use_one_definition_local_policy(self):
        original = {
            path.relative_to(FIXTURE).as_posix(): path.read_bytes()
            for path in FIXTURE.rglob("*")
            if path.is_file()
        }
        with tempfile.TemporaryDirectory(prefix="t131-public-") as temporary:
            gate = Path(temporary) / "gate"
            result = self._run_cli(gate)
            self.assertEqual(result.returncode, 0, result.stderr)
            cli_report = json.loads(result.stdout.strip().splitlines()[-1])
            report = json.loads((gate / "mapping.json").read_text())
            self.assertEqual(cli_report["format"], "rtl-obfuscation.cli-vnext")
            self.assertEqual(cli_report["schema_version"], 2)
            self.assertTrue(report["summary"]["strict_compile_passed"])
            self.assertTrue(report["summary"]["restored_byte_identical"])
            records = report["mapping"]["records"]
            by_owner_and_name = {
                (record["owner_module"], record["original_name"]): record
                for record in records
            }
            self.assertEqual(
                set(by_owner_and_name),
                {
                    ("t131_unused_a", "state"),
                    ("t131_unused_a", "next_state"),
                    ("t131_unused_b", "state"),
                    ("t131_shadowed", "state"),
                },
            )
            for key in {
                ("t131_unused_a", "state"),
                ("t131_unused_a", "next_state"),
                ("t131_unused_b", "state"),
            }:
                self.assertEqual(by_owner_and_name[key]["action"], "rename")
            shadowed = by_owner_and_name[("t131_shadowed", "state")]
            self.assertEqual(shadowed["action"], "preserve")
            self.assertEqual(shadowed["reason"], "syntax_local_ambiguous")
            renamed_states = [
                by_owner_and_name[("t131_unused_a", "state")]["renamed_name"],
                by_owner_and_name[("t131_unused_b", "state")]["renamed_name"],
            ]
            self.assertEqual(len(set(renamed_states)), 2)
            self.assertEqual(
                (gate / "external" / "top.sv").read_bytes(),
                original["external/top.sv"],
            )

            restored = Path(temporary) / "restored"
            decrypted = subprocess.run(
                [
                    sys.executable,
                    str(DECRYPT),
                    "--map",
                    str(gate / "mapping.json"),
                    "--gate-dir",
                    str(gate),
                    "--output-dir",
                    str(restored),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
            self.assertEqual(decrypted.returncode, 0, decrypted.stderr)
            for relative, data in original.items():
                if relative.endswith((".sv", ".v")):
                    self.assertEqual((restored / relative).read_bytes(), data)

    def test_mapping_phase_does_not_construct_or_walk_semantic_hierarchy(self):
        source_set = from_filelist(
            filelist=FIXTURE / "design.f",
            rewrite_roots=(FIXTURE / "owned",),
        )
        with mock.patch(
            "pyslang.ast.Compilation",
            side_effect=AssertionError("mapping constructed a semantic Compilation"),
        ):
            mapping = build_fast_local_signals_mapping(
                source_set,
                name_length=20,
                name_factory=self._name_factory(),
            )
        self.assertEqual(mapping.schema_version, 2)
        self.assertEqual(
            sum(record.action == "rename" for record in mapping.records),
            3,
        )

    def test_definition_local_inventory_is_built_once_per_module(self):
        import rtl_obfuscator.fast_local_signals as fast

        source_set = from_filelist(
            filelist=FIXTURE / "design.f",
            rewrite_roots=(FIXTURE / "owned",),
        )
        with mock.patch.object(
            fast, "_module_inventory", wraps=fast._module_inventory
        ) as inventory:
            mapping = build_fast_local_signals_mapping(
                source_set,
                name_length=20,
                name_factory=self._name_factory(),
            )
        self.assertEqual(inventory.call_count, 3)
        self.assertEqual(len(mapping.records), 4)

    def test_compact_ambiguity_matrix_is_object_level_and_nonfatal(self):
        with tempfile.TemporaryDirectory(prefix="t131-ambiguity-") as temporary:
            project = Path(temporary)
            owned = project / "owned"
            owned.mkdir()
            filelist = project / "design.f"
            filelist.write_text("owned/ambiguity.sv\n", encoding="utf-8")
            (owned / "ambiguity.sv").write_text(
                """`define MACRO_STATE macro_state
module t131_ambiguity(input logic in_i, output logic out_o);
  logic macro_state;
  logic member_state;
  logic named_state;
  logic value;
  assign macro_state = in_i;
  assign member_state = top.member_state;
  child child_i (.named_state(named_state));
  assign value = function_call(value);
  function automatic logic function_call(input logic arg);
    function_call = arg;
  endfunction
  assign out_o = `MACRO_STATE ^ member_state ^ named_state ^ value;
endmodule
""",
                encoding="utf-8",
            )
            source_set = from_filelist(
                filelist=filelist,
                rewrite_roots=(owned,),
            )
            mapping = build_fast_local_signals_mapping(
                source_set,
                name_length=20,
                name_factory=self._name_factory(),
            )
        records = {
            record.original_name: record
            for record in mapping.records
        }
        self.assertEqual(set(records), {"macro_state", "member_state", "named_state", "value"})
        for name in ("macro_state", "member_state", "named_state"):
            self.assertEqual(records[name].action, "preserve")
            self.assertEqual(records[name].reason, "syntax_local_ambiguous")
        self.assertEqual(records["value"].action, "rename")
        self.assertIsNone(records["value"].reason)

    def test_actual_unelaborated_gate_formal_positive_and_negative(self):
        with tempfile.TemporaryDirectory(prefix="t131-formal-") as temporary:
            base = Path(temporary)
            gate = base / "gate"
            result = self._run_cli(gate)
            self.assertEqual(result.returncode, 0, result.stderr)
            (gate / "formal.f").write_bytes((FIXTURE / "formal.f").read_bytes())
            arguments = [
                "--gold-filelist",
                str(FIXTURE / "formal.f"),
                "--gold-root",
                str(FIXTURE),
                "--gate-filelist",
                str(gate / "formal.f"),
                "--gate-root",
                str(gate),
                "--top",
                "t131_unused_a",
                "--seq",
                "5",
            ]
            positive = subprocess.run(
                [sys.executable, str(FORMAL), *arguments],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
            self.assertEqual(positive.returncode, 0, positive.stdout + positive.stderr)
            self.assertEqual(
                json.loads(positive.stdout.strip().splitlines()[-1])[
                    "formal_equivalence"
                ],
                "pass",
            )

            negative = base / "negative"
            shutil.copytree(gate, negative)
            target = negative / "owned" / "unused_a.sv"
            original = target.read_bytes()
            self.assertEqual(original.count(b" ^ "), 1)
            target.write_bytes(original.replace(b" ^ ", b" | ", 1))
            failed = subprocess.run(
                [
                    sys.executable,
                    str(FORMAL),
                    *[
                        argument.replace(str(gate), str(negative))
                        for argument in arguments
                    ],
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
            combined = (failed.stdout + failed.stderr).lower()
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("unproven", combined)
            self.assertIn("equiv_status -assert", combined)


if __name__ == "__main__":
    unittest.main()
