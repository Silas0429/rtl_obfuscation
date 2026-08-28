"""T113: a symbol referenced from dead source is preserved, not renamed.

T112 section 14 measured the fail-open this closes.  A module that *is* defined
but instantiated only inside an untaken generate branch becomes an
``UninstantiatedDefSymbol``: PySlang binds none of its connection actuals and
reports no diagnostic at all.  Renaming the declaration alone therefore leaves
the old name written in the gate, where it silently becomes an implicit net and
the port it used to reach is left dangling -- 1514 times on one production
design, while strict compilation, occurrence coverage, renamed range bytes and
byte-identical restore all reported success.

The fixture reproduces both dead-source shapes locally, and
``test_gate_rename_audit_is_suspect_before_the_fix_and_clean_after_it`` asserts
both directions on real published gates: the pre-T113 decision set produces
``verdict=suspect`` with the old names showing up as gate-only implicit nets,
and the shipped decision set produces ``verdict=clean``.  A fix that merely
stopped the auditor from looking would fail the second half; a fix that
preserved nothing would fail the first.
"""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from rtl_obfuscator.mapping_vnext import build_mapping_vnext
from rtl_obfuscator.rename_index import RenameIndex, build_rename_index
from rtl_obfuscator.rewrite_vnext import (
    build_mapping_execution_vnext,
    restore_gate_vnext,
    write_gate_vnext,
)
from rtl_obfuscator.source_catalog import build_source_catalog
from rtl_obfuscator.source_set import from_filelist
from rtl_obfuscator.systemverilog_names import secure_name_factory


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "t113_unelaborated_reference"
AUDIT = ROOT / "scripts" / "gate_rename_audit.py"
CORE_CATEGORIES = ("signals", "ports", "interface", "struct")
# The only reasons this fixture may report.  A new reason here is an unexplained
# preserve and must fail rather than be absorbed.
ALLOWED_REASONS = {
    "selected_top_boundary",
    "outside_top_closure",
    "macro_origin_conflict",
    "hierarchical_prefix_unsupported",
    "source_binding_incomplete",
    "unelaborated_reference",
}
# The three records this fixture must preserve, and only these three.
DEAD_RECORDS = {
    ("ports", "dead_port_o"),
    ("signals", "dead_signal"),
    ("signals", "shared_probe"),
}


class T113UnelaboratedReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source_set = from_filelist(filelist=FIXTURE / "design.f", top="t113_top")
        cls.catalog = build_source_catalog(cls.source_set)
        cls.index = build_rename_index(cls.catalog, categories=("all",))
        cls.files = tuple(
            dict.fromkeys(
                (
                    *cls.source_set.ordered_source_files,
                    *cls.source_set.included_files,
                )
            )
        )
        cls.data = {file: (FIXTURE / file).read_bytes() for file in cls.files}
        nodes: list[object] = []
        cls.catalog.catalog_root.visit(nodes.append)
        cls.node_kinds = [type(node).__name__ for node in nodes]

    def _category_outcome(self, category: str) -> dict:
        # Deliberately not named `_outcome`: `unittest.TestCase` binds an
        # instance attribute of that name to the runner's internal `_Outcome`.
        return next(
            item
            for item in self.index.category_outcomes
            if item["category"] == category
        )

    def _records(self, **filters):
        return [
            symbol
            for symbol in self.index.symbols
            if all(getattr(symbol, key) == value for key, value in filters.items())
        ]

    def _one(self, **filters):
        found = self._records(**filters)
        self.assertEqual(len(found), 1, f"{filters} -> {[i.symbol_id for i in found]}")
        return found[0]

    def _run(self, script: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(script), *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )

    def _dead_leaf_span(self) -> tuple[int, int]:
        """Return the byte span of the design unit that never elaborates."""

        design = self.data["design.sv"]
        start = design.index(b"module t113_dead_leaf")
        end = design.index(b"endmodule", start) + len(b"endmodule")
        return start, end

    def _publish(self, index: RenameIndex, root: Path, name: str) -> Path:
        """Publish one gate plus the mapping report the auditor reads.

        This is the same pair of reports the public CLI persists into
        ``mapping.json``: the mapping itself and the mapping execution, the
        latter being where ``per_file_mapping`` gate ranges live.
        """

        gate = root / name
        mapping = build_mapping_vnext(
            index, name_length=20, name_factory=secure_name_factory
        )
        execution = write_gate_vnext(mapping, output_dir=gate)
        evidence = execution.compile_evidence
        # Both gates must strict compile.  For the pre-fix gate that is the whole
        # point: the defect is invisible to the compiler.
        self.assertEqual(
            (
                evidence.catalog_parse_errors,
                evidence.catalog_semantic_errors,
                evidence.top_overlay_parse_errors,
                evidence.top_overlay_semantic_errors,
            ),
            (0, 0, 0, 0),
            name,
        )
        restored = restore_gate_vnext(
            execution, gate_dir=gate, output_dir=root / f"{name}_restore"
        )
        self.assertTrue(restored.to_report()["summary"]["byte_identical"], name)
        payload = {
            "format": "rtl-obfuscation.cli-vnext",
            "mapping": mapping.to_report(),
            "mapping_execution": build_mapping_execution_vnext(
                execution, restored
            ).to_report(),
        }
        (gate / "mapping.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
        return gate

    def _audit(self, gate: Path, report: Path) -> tuple[int, dict]:
        result = self._run(
            AUDIT,
            "--map", str(gate / "mapping.json"),
            "--gate-dir", str(gate),
            "--gold-root", str(FIXTURE),
            "--json", str(report),
            "--quiet",
        )
        self.assertTrue(
            report.is_file(), result.stdout + result.stderr
        )
        return result.returncode, json.loads(report.read_text(encoding="utf-8"))

    # --- T113 1: the fixture really is scenario C ----------------------------

    def test_fixture_reproduces_scenario_c_and_not_an_unknown_module(self):
        """Without this precondition every other assertion is about nothing.

        T112 section 14.2 separated three instantiation shapes.  Shape B, a
        module with no definition at all, raises ``UnknownModule`` and is
        therefore not this defect.  Shape C -- defined, instantiated only from an
        untaken branch -- compiles perfectly cleanly and is.
        """

        self.assertEqual(
            self.catalog.to_report()["compile"],
            {
                "catalog": {"parse_errors": 0, "semantic_errors": 0},
                "top_overlay": {"parse_errors": 0, "semantic_errors": 0},
            },
        )
        # Defined, so PySlang parked it as an uninstantiated definition rather
        # than reporting an error.
        self.assertEqual(self.node_kinds.count("UninstantiatedDefSymbol"), 1)
        self.assertIn(b"module t113_dead_leaf", self.data["design.sv"])
        # And that definition never elaborated, which is dead-source shape A:
        # the physical unit exists in the source and owns no semantic body, so
        # the catalog holds no owner for it at all.
        self.assertNotIn(
            "t113_dead_leaf", {module.name for module in self.catalog.modules}
        )
        self.assertTrue(
            all(module.in_top_closure for module in self.catalog.modules)
        )
        # Dead-source shape B: the branch that holds the only instantiation.
        design = self.data["design.sv"]
        self.assertIn(b"begin : g_dead", design)
        self.assertIn(b"t113_dead_leaf u_dead (", design)

    # --- T113 3.2: a dead-branch actual preserves its record -----------------

    def test_dead_generate_branch_actuals_preserve_their_own_records(self):
        """The exact StCache shape, reproduced and now preserved.

        ``dead_port_o`` also carries a live driver and a live named-port
        connection, so it holds complete live binding evidence.  It must still be
        preserved: the invisible reference is what decides, not the visible ones.
        """

        port = self._one(category="ports", name="dead_port_o")
        self.assertEqual(port.kind, "module_port")
        self.assertEqual(port.owner_module, "t113_branch")
        self.assertEqual(port.support, "preserved")
        self.assertEqual(port.reason, "unelaborated_reference")
        # Live evidence really exists for it, so this is not an unbound record.
        self.assertGreater(len(port.occurrences), 0)
        design = self.data["design.sv"]
        self.assertIn(b"assign dead_port_o = 1'b0;", design)
        self.assertIn(b".dead_port_o(branch_dead)", design)

        signal = self._one(category="signals", name="dead_signal")
        self.assertEqual(signal.kind, "signal")
        self.assertEqual(signal.owner_module, "t113_branch")
        self.assertEqual(signal.support, "preserved")
        self.assertEqual(signal.reason, "unelaborated_reference")
        # Referenced only from dead source, so PySlang bound no occurrence at
        # all -- the pre-T113 index still renamed its declaration.
        self.assertEqual(signal.occurrences, ())
        self.assertIn(b".d_in (dead_signal),", design)

    def test_live_records_of_the_same_module_still_rename(self):
        """The preserve is per record, in the T111 sense.

        ``t113_branch`` holds both shapes at once, so if the preserve leaked to
        its core group or to its module these four would stop renaming.
        """

        for category, name in (
            ("ports", "live_i"),
            ("ports", "live_o"),
            ("signals", "live_signal"),
            ("signals", "private_probe"),
        ):
            record = self._one(category=category, name=name)
            self.assertEqual(record.support, "eligible", name)
            self.assertIsNone(record.reason, name)
            self.assertGreater(len(record.occurrences), 0, name)
        # And the sibling records of the two affected modules keep renaming too.
        for owner in ("t113_branch", "t113_shared_user"):
            renamed = {
                record.name
                for record in self._records(owner_module=owner)
                if record.support == "eligible"
            }
            self.assertTrue(renamed, owner)

    # --- T113 3.1: the never-elaborated design unit shape -------------------

    def test_never_elaborated_unit_preserves_the_live_record_of_that_spelling(self):
        """Dead-source shape A, isolated from shape B.

        ``shared_probe`` is written only inside ``t113_dead_leaf``, whose whole
        declaration is dead because it never elaborates, and inside
        ``t113_shared_user``, where it is a fully bound live signal.  Nothing
        proves the dead tokens mean the live declaration -- per T113 section 3.3
        they may well mean the dead unit's own local -- so the live record is
        preserved rather than moved.
        """

        record = self._one(category="signals", name="shared_probe")
        self.assertEqual(record.owner_module, "t113_shared_user")
        self.assertEqual(record.support, "preserved")
        self.assertEqual(record.reason, "unelaborated_reference")
        self.assertGreater(len(record.occurrences), 0)

        design = self.data["design.sv"]
        dead_start, dead_end = self._dead_leaf_span()
        # Every dead spelling of the name sits inside that unit, and none of them
        # is inside the untaken generate branch, so shape B cannot explain this
        # preserve.
        branch = design.index(b"begin : g_dead")
        offsets = []
        cursor = design.find(b"shared_probe")
        while cursor != -1:
            offsets.append(cursor)
            cursor = design.find(b"shared_probe", cursor + 1)
        self.assertEqual(len(offsets), 6)
        inside_dead_unit = [
            offset for offset in offsets if dead_start <= offset < dead_end
        ]
        self.assertEqual(len(inside_dead_unit), 3)
        for offset in inside_dead_unit:
            self.assertLess(offset, branch)
        # The live owner is a plain module in the top closure, so its record is a
        # genuine rename candidate that this rule is giving up on.
        owner = next(
            module
            for module in self.catalog.modules
            if module.name == "t113_shared_user"
        )
        self.assertTrue(owner.in_top_closure)

    def test_dead_source_contributes_no_record_of_its_own(self):
        """T109 again: an unelaborated body produces no semantic node.

        The identifiers written only in dead source own no record, which is
        exactly why they cannot be renamed into agreement and must be answered by
        preserving the live record instead.
        """

        names = {record.name for record in self.index.symbols}
        for spelling in ("d_in", "d_out", "u_dead"):
            self.assertNotIn(spelling, names, spelling)
            self.assertIn(spelling.encode("utf-8"), self.data["design.sv"])

    # --- T113 7: whole-index invariants -------------------------------------

    def test_all_four_core_groups_rename_with_only_explained_reasons(self):
        for category in CORE_CATEGORIES:
            outcome = self._category_outcome(category)
            self.assertGreater(outcome["rename"], 0, category)
        used = {
            symbol.reason
            for symbol in self.index.symbols
            if symbol.reason is not None
        }
        # Not vacuous: the new reason really is in play on this fixture.
        self.assertIn("unelaborated_reference", used)
        self.assertEqual(used - ALLOWED_REASONS, set(), used)
        for category in CORE_CATEGORIES:
            for issue in self._category_outcome(category)["issues"]:
                self.assertIn(issue["message"], ALLOWED_REASONS, issue)
        # Exactly the three records that dead source touches, and no others.
        self.assertEqual(
            {
                (record.category, record.name)
                for record in self.index.symbols
                if record.reason == "unelaborated_reference"
            },
            DEAD_RECORDS,
        )
        # The new reason locates the preserved record for the operator.
        for category, name in DEAD_RECORDS:
            record = self._one(category=category, name=name)
            self.assertIn(
                {
                    "file": record.declaration.file,
                    "start": record.declaration.start,
                    "message": "unelaborated_reference",
                },
                self._category_outcome(category)["issues"],
            )

    def test_range_audit_has_no_duplicate_overlapping_or_out_of_range_edit(self):
        report = self.index.to_report()["range_audit"]
        self.assertEqual(report["symbols"], len(self.index.symbols))
        self.assertEqual(
            report["total_ranges"], report["declarations"] + report["occurrences"]
        )
        by_file: dict[str, list[tuple[int, int, str]]] = {}
        for symbol in self.index.symbols:
            for source_range in (
                symbol.declaration,
                *[item.source_range for item in symbol.occurrences],
            ):
                data = self.data[source_range.file]
                # In range, and really the identifier it claims to be.
                self.assertTrue(
                    0 <= source_range.start < source_range.end <= len(data),
                    (symbol.symbol_id, source_range),
                )
                self.assertEqual(
                    data[source_range.start : source_range.end],
                    symbol.name.encode("utf-8"),
                    (symbol.symbol_id, source_range),
                )
                by_file.setdefault(source_range.file, []).append(
                    (source_range.start, source_range.end, symbol.symbol_id)
                )
        total = 0
        for file, ranges in by_file.items():
            ranges.sort()
            total += len(ranges)
            self.assertEqual(
                len({(start, end) for start, end, _ in ranges}), len(ranges), file
            )
            for previous, current in zip(ranges, ranges[1:]):
                self.assertLessEqual(previous[1], current[0], (file, previous, current))
        self.assertEqual(total, report["total_ranges"])

    # --- T113 7 bullet 5: the core acceptance, both directions --------------

    def test_gate_rename_audit_is_suspect_before_the_fix_and_clean_after_it(self):
        """The point of T113, proved on two real published gates.

        The pre-fix gate is not a hand-edited forgery: it is built from this
        run's own index with the ``unelaborated_reference`` preserves flipped
        back to ``rename``, which is exactly the decision set the product emitted
        before T113, because that preserve is the last rule applied and it only
        ever touches records that were still eligible.
        """

        before_index = self._pre_t113_index()
        with tempfile.TemporaryDirectory(prefix="t113-audit-") as temporary:
            root = Path(temporary)

            before_gate = self._publish(before_index, root, "before")
            before_exit, before = self._audit(before_gate, root / "before.json")
            # The defect is invisible to every metric except this audit.
            self.assertEqual(
                before["compile"],
                {
                    "gold": {"parse_errors": 0, "semantic_errors": 0},
                    "gate": {"parse_errors": 0, "semantic_errors": 0},
                },
            )
            self.assertEqual(before["renamed_range_bytes"]["mismatched"], 0)
            self.assertGreater(before["renamed_range_bytes"]["checked"], 0)
            # And this audit catches it: the old names reappear as implicit nets.
            self.assertEqual(before["verdict"], "suspect")
            self.assertEqual(before_exit, 1)
            self.assertEqual(before["implicit_nets"]["gold"], 0)
            self.assertEqual(
                {item["name"] for item in before["implicit_nets"]["gate_only_detail"]},
                {"dead_port_o", "dead_signal"},
            )
            self.assertEqual(before["implicit_nets"]["gate_only"], 2)

            after_gate = self._publish(self.index, root, "after")
            after_exit, after = self._audit(after_gate, root / "after.json")
            self.assertEqual(after["verdict"], "clean")
            self.assertEqual(after_exit, 0)
            self.assertEqual(after["implicit_nets"]["gate_only"], 0)
            self.assertEqual(after["implicit_nets"]["gate_only_detail"], [])
            self.assertEqual(after["renamed_range_bytes"]["mismatched"], 0)
            # The fix did not buy the clean verdict by renaming less of the
            # design than the audit can see: it still checks real edits.
            self.assertGreater(after["renamed_range_bytes"]["checked"], 0)
            self.assertGreater(after["renamed_records"]["records"], 0)
            # Nor by removing the old spellings from the gate: they are still
            # physically there, in dead source, and now agree with a declaration
            # that was left alone.
            self.assertEqual(after["residual_old_names"]["count"], 0)
            gate_design = (after_gate / "design.sv").read_bytes()
            for spelling in (b"dead_port_o", b"dead_signal", b"shared_probe"):
                self.assertIn(spelling, gate_design, spelling)

    def _pre_t113_index(self) -> RenameIndex:
        symbols = tuple(
            replace(symbol, support="eligible", reason=None)
            if symbol.reason == "unelaborated_reference"
            else symbol
            for symbol in self.index.symbols
        )
        decisions = tuple(
            replace(decision, action="rename", reason=None)
            if decision.reason == "unelaborated_reference"
            else decision
            for decision in self.index.decisions
        )
        flipped = sum(
            1
            for symbol in self.index.symbols
            if symbol.reason == "unelaborated_reference"
        )
        self.assertEqual(flipped, len(DEAD_RECORDS))
        return replace(self.index, symbols=symbols, decisions=decisions)

    # --- T113 7: gate, restore and the public entry point -------------------

    def test_public_cli_reports_four_group_renames_and_byte_identical_restore(self):
        with tempfile.TemporaryDirectory(prefix="t113-cli-") as temporary:
            root = Path(temporary)
            gate = root / "gate"
            encrypted = self._run(
                ROOT / "rtl_encrypt.py",
                "--filelist", str(FIXTURE / "design.f"),
                "--top", "t113_top",
                "--category", "all",
                "--output-dir", str(gate),
            )
            self.assertEqual(encrypted.returncode, 0, encrypted.stderr)
            payload = json.loads(encrypted.stdout)
            self.assertEqual(payload["schema_version"], 2)
            self.assertTrue(payload["summary"]["strict_compile_passed"])
            self.assertTrue(payload["summary"]["restored_byte_identical"])
            report = json.loads((gate / "mapping.json").read_text(encoding="utf-8"))
            self.assertEqual(report["mapping"]["schema_version"], 2)
            outcomes = {
                item["category"]: item
                for item in report["mapping"]["category_outcomes"]
            }
            for category in CORE_CATEGORIES:
                self.assertGreater(outcomes[category]["rename"], 0, category)
                for issue in outcomes[category]["issues"]:
                    self.assertIn(issue["message"], ALLOWED_REASONS, issue)
            # The published mapping carries the new reason for the operator.
            preserved = {
                (record["category"], record["original_name"])
                for record in report["mapping"]["records"]
                if record["reason"] == "unelaborated_reference"
            }
            self.assertEqual(preserved, DEAD_RECORDS)
            for record in report["mapping"]["records"]:
                if record["reason"] == "unelaborated_reference":
                    self.assertEqual(record["action"], "preserve")
                    self.assertIsNone(record["renamed_name"])
            # The gate published by the public entry point is clean too.
            _, audited = self._audit(gate, root / "cli_audit.json")
            self.assertEqual(audited["verdict"], "clean")
            self.assertEqual(audited["implicit_nets"]["gate_only"], 0)
            restored = root / "restore"
            decrypted = self._run(
                ROOT / "rtl_decrypt.py",
                "--map", str(gate / "mapping.json"),
                "--gate-dir", str(gate),
                "--output-dir", str(restored),
            )
            self.assertEqual(decrypted.returncode, 0, decrypted.stderr)
            for file in self.files:
                self.assertEqual(
                    (restored / file).read_bytes(), self.data[file], file
                )

    # --- T113 10: compact Formal positive and fixed functional negative -----

    def test_actual_gate_formal_positive_and_fixed_functional_negative(self):
        with tempfile.TemporaryDirectory(prefix="t113-formal-") as temporary:
            root = Path(temporary)
            gate = root / "gate"
            encrypted = self._run(
                ROOT / "rtl_encrypt.py",
                "--filelist", str(FIXTURE / "formal.f"),
                "--top", "t113_formal_top",
                "--category", "all",
                "--output-dir", str(gate),
            )
            self.assertEqual(encrypted.returncode, 0, encrypted.stderr)
            summary = json.loads(encrypted.stdout)["summary"]
            self.assertTrue(summary["strict_compile_passed"])
            self.assertGreater(summary["rename"], 0)
            self.assertGreater(summary["modified_tokens"], 0)
            # The proof must run against a gate that really changed: an identity
            # comparison is not evidence.
            self.assertNotEqual(
                (gate / "formal_cone.sv").read_bytes(),
                (FIXTURE / "formal_cone.sv").read_bytes(),
            )
            arguments = (
                "--gold-filelist", str(FIXTURE / "formal.f"),
                "--gold-root", str(FIXTURE),
                "--gate-filelist", str(gate / "design.f"),
                "--gate-root", str(gate),
                "--top", "t113_formal_top",
                "--seq", "5",
            )
            positive = self._run(ROOT / "scripts" / "formal_equivalence.py", *arguments)
            self.assertEqual(positive.returncode, 0, positive.stdout + positive.stderr)
            positive_json = json.loads(positive.stdout.strip().splitlines()[-1])
            self.assertEqual(positive_json["formal_equivalence"], "pass")
            print(
                "T113_FORMAL_POSITIVE "
                + json.dumps(
                    {
                        "gold": str(FIXTURE),
                        "gate": str(gate),
                        "top": "t113_formal_top",
                        "exit": positive.returncode,
                        "json": positive_json,
                    },
                    sort_keys=True,
                )
            )

            negative = root / "negative"
            shutil.copytree(gate, negative)
            target = negative / "formal_cone.sv"
            original = target.read_bytes()
            self.assertEqual(original.count(b"1'b0"), 1)
            mutated = original.replace(b"1'b0", b"1'b1")
            self.assertNotEqual(mutated, original)
            target.write_bytes(mutated)
            negative_set = from_filelist(
                filelist=negative / "design.f", top="t113_formal_top"
            )
            # A functional negative, not a compile error.
            self.assertEqual(
                build_source_catalog(negative_set).to_report()["compile"],
                {
                    "catalog": {"parse_errors": 0, "semantic_errors": 0},
                    "top_overlay": {"parse_errors": 0, "semantic_errors": 0},
                },
            )
            negative_result = self._run(
                ROOT / "scripts" / "formal_equivalence.py",
                "--gold-filelist", str(FIXTURE / "formal.f"),
                "--gold-root", str(FIXTURE),
                "--gate-filelist", str(negative / "design.f"),
                "--gate-root", str(negative),
                "--top", "t113_formal_top",
                "--seq", "5",
            )
            self.assertNotEqual(negative_result.returncode, 0)
            combined = (negative_result.stdout + negative_result.stderr).lower()
            self.assertIn("unproven", combined)
            self.assertIn("equiv_status -assert", combined)
            print(
                "T113_FORMAL_NEGATIVE "
                + json.dumps(
                    {
                        "gold": str(FIXTURE),
                        "gate": str(negative),
                        "top": "t113_formal_top",
                        "exit": negative_result.returncode,
                        "mutation": "1'b0 -> 1'b1 in t113_cone_mix",
                        "evidence": "unproven; equiv_status -assert",
                    },
                    sort_keys=True,
                )
            )
