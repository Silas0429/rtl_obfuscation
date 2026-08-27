"""Deterministic checks for the read-only binding coverage probe.

The fixture reproduces the three shapes that made the StCache server run
report ``rename=0`` for ports, interface and struct.  These tests assert that
the probe attributes what PySlang can already prove and reports the rest as a
short list of grammar positions, so the residual is a work list rather than a
failure.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
FIXTURE = REPOSITORY / "tests" / "fixtures" / "t109_binding_coverage"
PROBE = REPOSITORY / "scripts" / "binding_coverage.py"


def _load_probe():
    name = "t109_binding_coverage_probe"
    cached = sys.modules.get(name)
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location(name, PROBE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclass resolves annotations through sys.modules, so the module must be
    # registered before it is executed.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _report(**overrides) -> dict:
    module = _load_probe()
    args = argparse.Namespace(
        filelist=str(FIXTURE / "design.f"),
        source_root=None,
        input_file=None,
        top="t109_top",
        include_dirs=[],
        defines=[],
        json=None,
        examples=8,
        worst_names=20,
        quiet=True,
    )
    for key, value in overrides.items():
        setattr(args, key, value)
    return module.build_report(args)


class BindingCoverageProbeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = _report()

    def test_report_identity_and_clean_compile(self) -> None:
        self.assertEqual(self.report["format"], "rtl-obfuscation.binding-coverage")
        self.assertEqual(self.report["schema_version"], 1)
        self.assertEqual(self.report["compile"]["parse_errors"], 0)
        self.assertEqual(self.report["compile"]["semantic_errors"], 0)

    def test_every_attributed_token_is_byte_verified(self) -> None:
        # A non-zero mismatch would mean a physical location was accepted
        # without the source bytes agreeing, which is the one failure this
        # model may never tolerate.
        self.assertEqual(self.report["tokens"]["byte_mismatch"], 0)
        self.assertEqual(self.report["tokens"]["outside_source_set"], 0)

    def test_struct_field_reference_is_attributed_with_and_without_select(self) -> None:
        # design.sv references struct fields five times: data.user[3:0] once,
        # data.a.a twice and data.a.b twice.  data.user[3:0] is the shape whose
        # MemberAccessExpression.syntax is None; it must be attributed by the
        # same rule as the shapes that keep their syntax.
        self.assertEqual(
            self.report["join"]["attributed_by_target_kind"].get("FieldSymbol"), 5
        )

    def test_nested_equal_spellings_resolve_without_ambiguity(self) -> None:
        # data.a.a spells the same name at three nesting levels.  The smallest
        # enclosing reference rule must separate them, so the fixture, which
        # contains no macros, has no ambiguous token at all.
        self.assertEqual(self.report["join"]["overall"]["ambiguous"], 0)
        self.assertEqual(self.report["join"]["in_scope"]["ambiguous"], 0)

    def test_aggregate_field_declarations_are_reachable(self) -> None:
        # Compilation.getRoot().visit does not reach aggregate members, so the
        # probe walks canonicalType.  t109_inner_t and t109_outer_t declare
        # four fields between them.
        self.assertEqual(
            self.report["declarations"]["attributed_by_semantic_kind"].get(
                "FieldSymbol"
            ),
            4,
        )

    def test_in_scope_filter_narrows_the_denominator(self) -> None:
        overall = self.report["join"]["overall"]["identifier_tokens"]
        scoped = self.report["join"]["in_scope"]["identifier_tokens"]
        self.assertGreater(overall, scoped)
        self.assertGreater(scoped, 0)
        groups = self.report["declarations"]["in_scope_names_by_group"]
        self.assertEqual(
            set(groups),
            {
                "signals_or_interface_member",
                "ports_or_interface_port",
                "interface",
                "struct",
            },
        )

    def test_residual_locates_the_three_server_root_causes(self) -> None:
        kinds = {
            entry["syntax_kind"]
            for entry in self.report["residual_in_scope_by_syntax_kind"]
        }
        # Root cause 1: the named port connection label.  design.sv writes the
        # labels in an order that differs from the port declaration order.
        self.assertIn("NamedPortConnection", kinds)
        # Root cause 2: the modport-qualified interface port header, which
        # PySlang exposes without a dataType attribute.
        self.assertIn("InterfacePortHeader", kinds)
        # The residual is a short grammar list, not an open tail.
        self.assertLessEqual(len(self.report["residual_in_scope_by_syntax_kind"]), 12)

    def test_residual_entries_carry_locatable_evidence(self) -> None:
        for entry in self.report["residual_in_scope_by_syntax_kind"]:
            self.assertGreater(entry["tokens"], 0)
            self.assertTrue(entry["examples"])
            for example in entry["examples"]:
                self.assertEqual(example["file"], "design.sv")
                self.assertIsInstance(example["start"], int)
                self.assertTrue(example["text"])

    def test_completeness_reports_both_denominators(self) -> None:
        completeness = self.report["completeness"]
        self.assertIn("overall", completeness)
        self.assertIn("in_scope", completeness)
        scoped = completeness["in_scope"]
        self.assertEqual(
            scoped["distinct_names"],
            scoped["names_fully_accounted"] + scoped["names_with_unaccounted_tokens"],
        )

    def test_cli_is_read_only_when_json_is_not_requested(self) -> None:
        before = sorted(path.name for path in FIXTURE.iterdir())
        completed = subprocess.run(
            [
                sys.executable,
                str(PROBE),
                "--filelist",
                str(FIXTURE / "design.f"),
                "--top",
                "t109_top",
                "--quiet",
            ],
            cwd=REPOSITORY,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["format"], "rtl-obfuscation.binding-coverage")
        self.assertEqual(sorted(path.name for path in FIXTURE.iterdir()), before)

    def test_input_modes_are_mutually_exclusive(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(PROBE),
                "--filelist",
                str(FIXTURE / "design.f"),
                "--source-root",
                str(FIXTURE),
                "--top",
                "t109_top",
            ],
            cwd=REPOSITORY,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(
            json.loads(completed.stdout)["error"], "PROBE_INPUT_MODE_INVALID"
        )


if __name__ == "__main__":
    unittest.main()
