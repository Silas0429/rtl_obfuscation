"""T111: an unproven record preserves itself, not its whole core group.

The contract freezes two changes.  Section 2.1 shrinks the transaction boundary
of ``source_binding_incomplete`` from the core group to the single record that
produced the issue, and section 2.2 restores a macro location to its physical
call site before anchoring a member access instead of giving up on it.

The fixture reproduces the residual StCache signature locally: with the
pre-T111 logic its struct group reports ``candidate=8 rename=0 preserve=8``
because one unproven aggregate plus three unbindable macro-argument member
tokens roll the whole group back.  Every assertion below is written so that
losing either change fails a test.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from rtl_obfuscator.mapping_vnext import build_mapping_vnext
from rtl_obfuscator.rename_index import (
    SymbolOccurrence,
    _WorkingSymbol,
    _apply_group_binding_issues,
    _claim_occurrence,
    _resolve_range_claims,
    build_rename_index,
)
from rtl_obfuscator.rewrite_vnext import restore_gate_vnext, write_gate_vnext
from rtl_obfuscator.source_catalog import SourceRange, build_source_catalog
from rtl_obfuscator.source_set import from_filelist
from rtl_obfuscator.systemverilog_names import secure_name_factory


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "t111_record_scope_preserve"
CORE_CATEGORIES = ("signals", "ports", "interface", "struct")
# The only reasons this fixture may report.  A new reason here is an
# unexplained preserve and must fail rather than be absorbed.
ALLOWED_REASONS = {
    "selected_top_boundary",
    "outside_top_closure",
    "macro_origin_conflict",
    "hierarchical_prefix_unsupported",
    "source_binding_incomplete",
}


class T111RecordScopePreserveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source_set = from_filelist(filelist=FIXTURE / "design.f", top="t111_top")
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

    # --- T111 6: one unproven record preserves only itself -------------------

    def test_source_binding_incomplete_preserves_only_the_issuing_record(self):
        """The whole point of T111, measured on the struct core group.

        With the pre-T111 core-group transaction this same fixture reported
        ``rename=0 preserve=8``.  The macro-generated field still has no physical
        declaration and its aggregate is still fail-closed, but the seven proven
        records of the same group must now rename.
        """

        structs = self._records(category="struct")
        self.assertEqual(len(structs), 8)
        unproven = self._one(category="struct", name="t111_macro_struct_t")
        self.assertEqual(unproven.kind, "struct_type")
        self.assertEqual(unproven.support, "preserved")
        self.assertEqual(unproven.reason, "source_binding_incomplete")
        # Exactly one record in the group may be preserved, and it is that one.
        self.assertEqual(
            [
                symbol.name
                for symbol in structs
                if symbol.support != "eligible"
            ],
            ["t111_macro_struct_t"],
        )
        for symbol in structs:
            if symbol.symbol_id == unproven.symbol_id:
                continue
            self.assertEqual(symbol.support, "eligible", symbol.name)
            self.assertIsNone(symbol.reason, symbol.name)
        # The proven siblings are real aggregates and real fields, not an empty
        # set that would make the assertion above vacuous.
        self.assertEqual(
            {
                symbol.name
                for symbol in structs
                if symbol.kind == "struct_type" and symbol.support == "eligible"
            },
            {"t111_inner_t", "t111_word_t"},
        )
        self.assertEqual(
            {
                symbol.name
                for symbol in structs
                if symbol.kind == "struct_field"
            },
            {"cmd", "ok", "inner", "wide"},
        )
        # The macro-generated field itself is never guessed into existence.
        self.assertNotIn("macro_field", {symbol.name for symbol in structs})
        self.assertIn(b"`T111_FIELD(macro_field);", self.data["design.sv"])
        outcome = self._category_outcome("struct")
        self.assertEqual(outcome["candidate"], 8)
        self.assertEqual(outcome["rename"], 7)
        self.assertEqual(outcome["preserve"], 1)
        self.assertEqual(outcome["unsupported"], 0)
        self.assertEqual(outcome["status"], "preserved")

    def test_group_issues_keep_file_start_and_message_for_the_real_cause(self):
        """Narrower scope must not cost locating information."""

        unproven = self._one(category="struct", name="t111_macro_struct_t")
        issues = self._category_outcome("struct")["issues"]
        self.assertTrue(issues)
        # The record-level issue locates the preserved record itself.
        self.assertIn(
            {
                "file": unproven.declaration.file,
                "start": unproven.declaration.start,
                "message": "source_binding_incomplete",
            },
            issues,
        )
        # The detailed diagnostic still names the semantic shape that failed.
        detailed = [
            issue
            for issue in issues
            if issue.get("semantic_kind") == "FieldSymbol"
            and issue.get("name") == "macro_field"
        ]
        self.assertEqual(len(detailed), 1, issues)
        self.assertEqual(detailed[0]["message"], "source_binding_incomplete")
        self.assertEqual(detailed[0]["file"], "design.sv")
        self.assertIsInstance(detailed[0]["detail"], str)
        self.assertTrue(detailed[0]["detail"])
        # Its offset points at the macro-generated field, inside the aggregate.
        self.assertLess(detailed[0]["start"], unproven.declaration.start)
        # No issue may be attributed to a record that was never the cause.
        proven_starts = {
            symbol.declaration.start
            for symbol in self._records(category="struct")
            if symbol.support == "eligible"
        }
        self.assertEqual(
            [issue for issue in issues if issue["start"] in proven_starts], []
        )

    def test_unknown_reason_is_recorded_at_record_scope_only(self):
        """`_apply_group_binding_issues` in isolation, with no fixture noise."""

        records = {
            symbol_id: _WorkingSymbol(
                symbol_id=symbol_id,
                category="struct",
                kind="struct_field",
                semantic_kind="FieldSymbol",
                name=name,
                declaration=SourceRange("design.sv", offset, offset + len(name)),
                owner_module="owner",
                semantic_owner="owner",
                impact="aggregate_field",
                abi="internal",
            )
            for symbol_id, name, offset in (
                ("struct:unproven", "unproven", 0),
                ("struct:proven_a", "proven_a", 20),
                ("struct:proven_b", "proven_b", 40),
            )
        }
        unproven = records["struct:unproven"]
        unproven.support = "preserved"
        unproven.reason = "source_binding_incomplete"
        binding_issues = {
            "struct": [
                {
                    "message": "source_binding_incomplete",
                    "semantic_kind": "FieldSymbol",
                    "name": "unproven",
                    "file": "design.sv",
                    "start": 0,
                }
            ]
        }

        issues = _apply_group_binding_issues(records, binding_issues)

        self.assertEqual(unproven.support, "preserved")
        self.assertEqual(unproven.reason, "source_binding_incomplete")
        for symbol_id in ("struct:proven_a", "struct:proven_b"):
            self.assertEqual(records[symbol_id].support, "eligible", symbol_id)
            self.assertIsNone(records[symbol_id].reason, symbol_id)
        self.assertEqual(
            issues,
            {
                "struct": (
                    {
                        "file": "design.sv",
                        "start": 0,
                        "message": "source_binding_incomplete",
                    },
                )
            },
        )

    def test_a_category_issue_without_an_owning_record_renames_nothing_extra(self):
        """A diagnostic with no owning record must not roll the group back.

        This is the exact server shape: a category carried a
        ``source_binding_incomplete`` issue while every record of that category
        was individually proven, and the old code preserved all of them.
        """

        records = {
            "struct:proven": _WorkingSymbol(
                symbol_id="struct:proven",
                category="struct",
                kind="struct_type",
                semantic_kind="TypeAliasType",
                name="proven",
                declaration=SourceRange("design.sv", 0, 6),
                owner_module="owner",
                semantic_owner="owner",
                impact="type",
                abi="internal",
            )
        }
        binding_issues = {
            "struct": [
                {
                    "message": "source_binding_incomplete",
                    "semantic_kind": "TypeAliasType",
                    "name": "never_registered",
                    "file": "design.sv",
                    "start": 99,
                }
            ]
        }

        issues = _apply_group_binding_issues(records, binding_issues)

        self.assertEqual(records["struct:proven"].support, "eligible")
        self.assertIsNone(records["struct:proven"].reason)
        self.assertEqual(issues, {})

    def test_unknown_cross_record_conflict_still_rolls_back_its_core_group(self):
        """T111 2.1 must not weaken the one coupling that is genuinely group wide.

        A physical range claimed by two records with no macro origin is still an
        unknown ownership conflict, and `_resolve_range_claims` still keeps the
        whole affected core group fail-closed.  T111 deliberately did not touch
        that policy.
        """

        shared = SourceRange("design.sv", 0, 6)
        records = {
            symbol_id: _WorkingSymbol(
                symbol_id=symbol_id,
                category="signals",
                kind="signal",
                semantic_kind="VariableSymbol",
                name="shared",
                declaration=SourceRange("design.sv", offset, offset + 6),
                owner_module=symbol_id,
                semantic_owner=symbol_id,
                impact="internal_signal",
                abi="internal",
            )
            for symbol_id, offset in (
                ("signals:a", 0),
                ("signals:b", 7),
                ("signals:c", 14),
            )
        }
        claims: dict = {}
        _claim_occurrence(
            records["signals:a"], SymbolOccurrence(shared, "semantic_reference"), claims
        )
        _claim_occurrence(
            records["signals:b"], SymbolOccurrence(shared, "semantic_reference"), claims
        )

        issues = _resolve_range_claims(records, claims)

        self.assertEqual(
            issues["signals"],
            (
                {
                    "file": "design.sv",
                    "start": 0,
                    "end": 6,
                    "message": "cross_record_range_conflict",
                },
            ),
        )
        # `signals:c` never claimed the range and is still rolled back with it.
        for record in records.values():
            self.assertEqual(record.support, "preserved", record.symbol_id)
            self.assertEqual(record.reason, "cross_record_range_conflict")
            self.assertEqual(record.occurrences, {})

    # --- T111 6: macro-argument member access shapes -------------------------

    def test_macro_argument_member_access_shapes_bind_and_rename(self):
        """The residual StCache root causes, reproduced and now bound.

        `pkt.inner.cmd[1]`, `blk.cmd[1]` and `(^pkt.wide[6:5])` sit inside a macro
        argument, so both ends of each member expression's source range are macro
        locations and the pre-T111 guard returned None for every one of them.  The
        physical tokens do exist at the call site, so each must now resolve to the
        exact bytes written there.  No comment in the fixture spells a design
        identifier, so these byte searches can only find real code.
        """

        design = self.data["design.sv"]
        nested = design.index(b"pkt.inner.cmd[1]")
        named = design.index(b"blk.cmd[1]")
        part = design.index(b"(^pkt.wide[6:5])")
        shapes = {
            # nested member + bit select
            "nested_member_bit_select": (nested + len("pkt."), "inner"),
            # member + bit select on a named aggregate: the root-cause token type
            "named_member_bit_select": (named + len("blk."), "cmd"),
            # member + part select inside a reduction
            "member_part_select": (part + len("(^pkt."), "wide"),
        }
        claims = {
            occurrence.source_range.start: (symbol, occurrence)
            for symbol in self.index.symbols
            for occurrence in symbol.occurrences
            if occurrence.source_range.file == "design.sv"
        }
        for label, (offset, name) in shapes.items():
            self.assertEqual(
                design[offset : offset + len(name)], name.encode("utf-8"), label
            )
            self.assertIn(offset, claims, label)
            symbol, occurrence = claims[offset]
            self.assertEqual(symbol.category, "struct", label)
            self.assertEqual(symbol.kind, "struct_field", label)
            self.assertEqual(symbol.name, name, label)
            # Renamed, not merely diagnosed.
            self.assertEqual(symbol.support, "eligible", label)
            self.assertIsNone(symbol.reason, label)
            self.assertEqual(occurrence.source_range.end, offset + len(name), label)
            # A macro argument is macro provenance, so a restored range that two
            # records ever claim stays classifiable as a macro-origin conflict.
            self.assertEqual(occurrence.provenance, "semantic_macro_argument", label)

        # Restoring a macro location must not relax the byte proof: the macro
        # bodies spell none of these member names, so nothing may be anchored
        # inside the header.
        macros = self.data["t111_macros.svh"]
        for name in (b"cmd", b"wide", b"inner"):
            self.assertNotIn(name, macros)
        self.assertEqual(
            [
                (symbol.name, occurrence.source_range)
                for symbol in self._records(category="struct")
                for occurrence in symbol.occurrences
                if occurrence.source_range.file != "design.sv"
            ],
            [],
        )
        # The innermost member of the anonymous nested aggregate owns no record,
        # so it must be claimed by nobody rather than by the named aggregate's
        # member of the same spelling.
        anonymous = nested + len("pkt.inner.")
        self.assertEqual(design[anonymous : anonymous + 3], b"cmd")
        self.assertNotIn(anonymous, claims)

    def test_macro_body_expanded_twice_is_still_a_per_object_macro_conflict(self):
        """T111 2.2 must not bypass `_resolve_range_claims`.

        `t111_shared_body` is written once physically, inside the macro body, and
        names a different declaration in each of the two modules that expand it,
        so one physical range carries two semantic meanings.
        """

        macros = self.data["t111_macros.svh"]
        # The identifier is written physically exactly once, in the macro body.
        self.assertEqual(macros.count(b"t111_shared_body"), 1)
        shared_start = macros.index(b"t111_shared_body")
        shared = SourceRange(
            "t111_macros.svh", shared_start, shared_start + len("t111_shared_body")
        )
        self.assertEqual(
            macros[shared.start : shared.end], b"t111_shared_body"
        )
        self.assertEqual(self.data["design.sv"].count(b"`T111_BODY_ASSIGN(data_i);"), 2)

        conflicting = self._records(name="t111_shared_body")
        self.assertEqual(len(conflicting), 2)
        self.assertNotEqual(
            conflicting[0].declaration, conflicting[1].declaration
        )
        for symbol in conflicting:
            self.assertEqual(symbol.category, "signals")
            self.assertEqual(symbol.support, "unsupported")
            self.assertEqual(symbol.reason, "macro_origin_conflict")
            # The shared range can never be emitted as two edits.
            self.assertNotIn(
                shared, [item.source_range for item in symbol.occurrences]
            )
        outcome = self._category_outcome("signals")
        self.assertIn(
            {
                "file": shared.file,
                "start": shared.start,
                "end": shared.end,
                "message": "macro_origin_conflict",
            },
            outcome["issues"],
        )
        # Per object, not per group: every other signal still renames.
        self.assertEqual(outcome["unsupported"], 2)
        self.assertEqual(outcome["preserve"], 0)
        self.assertEqual(outcome["rename"], outcome["candidate"] - 2)
        self.assertGreater(outcome["rename"], 0)

    # --- T111 6: whole-index invariants -------------------------------------

    def test_all_four_core_groups_rename_with_only_explained_reasons(self):
        for category in CORE_CATEGORIES:
            outcome = self._category_outcome(category)
            self.assertGreater(outcome["rename"], 0, category)
        used = {
            symbol.reason
            for symbol in self.index.symbols
            if symbol.reason is not None
        }
        self.assertTrue(used)
        self.assertEqual(used - ALLOWED_REASONS, set(), used)
        for category in CORE_CATEGORIES:
            for issue in self._category_outcome(category)["issues"]:
                self.assertIn(issue["message"], ALLOWED_REASONS, issue)

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

    def test_actual_gate_strict_compiles_and_restores_byte_identical(self):
        mapping = build_mapping_vnext(
            self.index, name_length=20, name_factory=secure_name_factory
        )
        for category in CORE_CATEGORIES:
            self.assertTrue(
                any(
                    item.category == category and item.action == "rename"
                    for item in mapping.records
                ),
                category,
            )
        with tempfile.TemporaryDirectory(prefix="t111-gate-") as temporary:
            root = Path(temporary)
            execution = write_gate_vnext(mapping, output_dir=root / "gate")
            evidence = execution.compile_evidence
            self.assertEqual(
                (
                    evidence.catalog_parse_errors,
                    evidence.catalog_semantic_errors,
                    evidence.top_overlay_parse_errors,
                    evidence.top_overlay_semantic_errors,
                ),
                (0, 0, 0, 0),
            )
            restored = restore_gate_vnext(
                execution, gate_dir=root / "gate", output_dir=root / "restore"
            )
            self.assertTrue(restored.to_report()["summary"]["byte_identical"])
            self.assertEqual(
                {
                    file: (root / "restore" / file).read_bytes()
                    for file in self.files
                },
                self.data,
            )

    def test_public_cli_reports_four_group_renames_and_byte_identical_restore(self):
        with tempfile.TemporaryDirectory(prefix="t111-cli-") as temporary:
            root = Path(temporary)
            gate = root / "gate"
            encrypted = self._run(
                ROOT / "rtl_encrypt.py",
                "--filelist", str(FIXTURE / "design.f"),
                "--top", "t111_top",
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
            # The struct group is the one T110 could not move off zero.
            self.assertEqual(outcomes["struct"]["rename"], 7)
            self.assertEqual(outcomes["struct"]["preserve"], 1)
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

    # --- T111 9: compact Formal positive and fixed functional negative ------

    def test_actual_gate_formal_positive_and_fixed_functional_negative(self):
        with tempfile.TemporaryDirectory(prefix="t111-formal-") as temporary:
            root = Path(temporary)
            gate = root / "gate"
            encrypted = self._run(
                ROOT / "rtl_encrypt.py",
                "--filelist", str(FIXTURE / "formal.f"),
                "--top", "t111_formal_top",
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
                "--top", "t111_formal_top",
                "--seq", "5",
            )
            positive = self._run(ROOT / "scripts" / "formal_equivalence.py", *arguments)
            self.assertEqual(positive.returncode, 0, positive.stdout + positive.stderr)
            positive_json = json.loads(positive.stdout.strip().splitlines()[-1])
            self.assertEqual(positive_json["formal_equivalence"], "pass")
            print(
                "T111_FORMAL_POSITIVE "
                + json.dumps(
                    {
                        "gold": str(FIXTURE),
                        "gate": str(gate),
                        "top": "t111_formal_top",
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
                filelist=negative / "design.f", top="t111_formal_top"
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
                "--top", "t111_formal_top",
                "--seq", "5",
            )
            self.assertNotEqual(negative_result.returncode, 0)
            combined = (negative_result.stdout + negative_result.stderr).lower()
            self.assertIn("unproven", combined)
            self.assertIn("equiv_status -assert", combined)
            print(
                "T111_FORMAL_NEGATIVE "
                + json.dumps(
                    {
                        "gold": str(FIXTURE),
                        "gate": str(negative),
                        "top": "t111_formal_top",
                        "exit": negative_result.returncode,
                        "mutation": "1'b0 -> 1'b1 in t111_cone_mix",
                        "evidence": "unproven; equiv_status -assert",
                    },
                    sort_keys=True,
                )
            )
