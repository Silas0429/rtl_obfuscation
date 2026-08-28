"""T115: a name is renamed only when every token that spells it is accounted for.

Three consecutive rounds of per-shape compatibility did not converge.  T110 fixed
three shapes; T113 removed 190 of 1514 bad implicit nets on one production design
and a third, still uncharacterised shape accounted for the remaining 1324.  Every
one of those rounds asked "which shapes do we know about".  This one asks the
shape-independent question of ``token_first_binding.md`` section 2 instead:

    For a symbol whose old name is ``n``: let T be every physical identifier
    token spelling ``n`` in the source set.  Rename ``n`` only if no token in T is
    unattributed, attributed meaning bound to a semantic reference or to a
    declaration.

The fixture carries two mutually independent shapes.  Shape one is the fail-open
recorded in ``token_first_binding.md`` section 2.1: a typedef used both as a
variable type and as another aggregate's member type, where the member-type
``NamedType`` reference is bound to nothing, produces no issue, and used to let
the declaration be renamed on its own -- after which the gate no longer compiled.
Shape two is a second typedef of the same core group whose every token is
attributed, and it must keep renaming, which is what proves the preserve is per
record rather than per group.

Two of the assertions here exist to stop a fix that only looks like one:

* ``test_shape_one_is_preserved_by_the_new_criterion_and_not_by_the_t113_rule``
  requires the reason to be ``incomplete_name_coverage`` and not
  ``unelaborated_reference``.  If T113's dead-source rule happened to cover this
  shape, the new criterion would never be exercised and the fixture would pass
  while proving nothing;
* ``test_the_token_denominator_is_every_physical_spelling_in_the_source`` pins
  the denominator to a raw byte search of the fixture.  Coverage can always be
  bought back by dropping a token class nobody has a rule for yet, and that token
  is precisely the one this criterion exists to catch, so narrowing the
  denominator has to fail here.
"""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from rtl_obfuscator import rename_index as rename_index_module
from rtl_obfuscator.mapping_vnext import build_mapping_vnext
from rtl_obfuscator.rename_index import RenameIndex, build_rename_index
from rtl_obfuscator.rewrite_vnext import (
    RewriteVNextError,
    build_mapping_execution_vnext,
    restore_gate_vnext,
    write_gate_vnext,
)
from rtl_obfuscator.source_catalog import build_source_catalog
from rtl_obfuscator.source_set import from_filelist
from rtl_obfuscator.systemverilog_names import secure_name_factory


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "t115_name_completeness"
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
    "incomplete_name_coverage",
}
# Shape one, and only shape one.
SHAPE_ONE = ("struct", "t115_inner_t")
SHAPE_TWO = ("struct", "t115_word_t")


class T115NameCompletenessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source_set = from_filelist(filelist=FIXTURE / "design.f", top="t115_top")
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
        cls.nodes = nodes
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

    def _byte_offsets(self, name: str) -> set[tuple[str, int]]:
        """Every physical spelling of ``name`` in the fixture, by raw byte search.

        No identifier of this fixture is written inside a comment, so a
        word-boundary byte search over the source set is an independent ground
        truth for what the source physically contains.  Independence is the point:
        it is derived from the files, never from PySlang.
        """

        pattern = re.compile(
            rb"(?<![0-9A-Za-z_$])" + re.escape(name.encode("utf-8")) + rb"(?![0-9A-Za-z_$])"
        )
        return {
            (file, match.start())
            for file in self.files
            for match in pattern.finditer(self.data[file])
        }

    def _product_accounted(self) -> set[tuple[str, int, int]]:
        """Every physical range this run's own records claim.

        These are the product's real binding rules -- declarations, named port
        connection labels, interface port types, member accesses, type references
        -- each already verified against the source bytes.
        """

        claimed: set[tuple[str, int, int]] = set()
        for symbol in self.index.symbols:
            for source_range in (
                symbol.declaration,
                *[item.source_range for item in symbol.occurrences],
            ):
                claimed.add(
                    (source_range.file, source_range.start, source_range.end)
                )
        return claimed

    def _rewritten_starts(self) -> frozenset[tuple[str, int]]:
        """Every position whose spelling this run changes.

        A reference whose target is declared at one of these cannot be left alone,
        which is what makes ``ctrl.full`` through a modport port unattributed even
        though a reference does claim it.
        """

        return frozenset(
            (source_range.file, source_range.start)
            for symbol in self.index.symbols
            if symbol.support == "eligible"
            for source_range in (
                symbol.declaration,
                *[item.source_range for item in symbol.occurrences],
            )
        )

    def _publish(self, index: RenameIndex, root: Path, name: str) -> Path:
        """Publish one gate plus the mapping report the auditor reads.

        This is the same pair of reports the public CLI persists into
        ``mapping.json``: the mapping itself and the mapping execution, the latter
        being where ``per_file_mapping`` gate ranges live.
        """

        gate = root / name
        mapping = build_mapping_vnext(
            index, name_length=20, name_factory=secure_name_factory
        )
        execution = write_gate_vnext(mapping, output_dir=gate)
        evidence = execution.compile_evidence
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
        self.assertTrue(report.is_file(), result.stdout + result.stderr)
        return result.returncode, json.loads(report.read_text(encoding="utf-8"))

    def _pre_t115_index(self) -> RenameIndex:
        """This run's own decision set with the new preserve flipped back.

        The pre-fix gate is not a hand-edited forgery.  The criterion is the last
        rule applied and only ever touches records that were still eligible, so
        flipping its preserves back to ``rename`` reproduces exactly the decision
        set the product emitted before this task.
        """

        flipped = sum(
            1
            for symbol in self.index.symbols
            if symbol.reason == "incomplete_name_coverage"
        )
        self.assertEqual(flipped, 1)
        return replace(
            self.index,
            symbols=tuple(
                replace(symbol, support="eligible", reason=None)
                if symbol.reason == "incomplete_name_coverage"
                else symbol
                for symbol in self.index.symbols
            ),
            decisions=tuple(
                replace(decision, action="rename", reason=None)
                if decision.reason == "incomplete_name_coverage"
                else decision
                for decision in self.index.decisions
            ),
        )

    # --- T115 5: the fixture is not the T113 shape --------------------------

    def test_fixture_holds_no_dead_source_so_the_t113_rule_cannot_fire(self):
        """Without this precondition the discriminator below is about nothing.

        T113 preserves a record whose spelling is written inside source PySlang
        never elaborated.  This fixture deliberately contains none of that: no
        uninstantiated definition, no untaken generate branch, and every physical
        design unit elaborated.  So the only rule that can preserve shape one is
        the new criterion.
        """

        self.assertEqual(
            self.catalog.to_report()["compile"],
            {
                "catalog": {"parse_errors": 0, "semantic_errors": 0},
                "top_overlay": {"parse_errors": 0, "semantic_errors": 0},
            },
        )
        self.assertEqual(self.node_kinds.count("UninstantiatedDefSymbol"), 0)
        self.assertEqual(
            [
                node
                for node in self.nodes
                if type(node).__name__ == "GenerateBlockSymbol"
                and getattr(node, "isUninstantiated", False)
            ],
            [],
        )
        # The dead-region detector agrees: there is no dead source at all here.
        self.assertEqual(
            rename_index_module._dead_source_regions(
                self.catalog,
                self.nodes,
                rename_index_module._syntax_nodes(self.catalog),
                {},
            ),
            (),
        )
        self.assertEqual(
            [
                symbol.name
                for symbol in self.index.symbols
                if symbol.reason == "unelaborated_reference"
            ],
            [],
        )

    def test_shape_one_is_preserved_by_the_new_criterion_and_not_by_the_t113_rule(self):
        """The core acceptance of section 5, and the discriminator of section 6."""

        category, name = SHAPE_ONE
        record = self._one(category=category, name=name)
        self.assertEqual(record.kind, "struct_type")
        self.assertEqual(record.support, "preserved")
        self.assertEqual(record.reason, "incomplete_name_coverage")
        self.assertNotEqual(record.reason, "unelaborated_reference")
        decision = next(
            item
            for item in self.index.decisions
            if item.symbol_id == record.symbol_id
        )
        self.assertEqual(decision.action, "preserve")
        self.assertEqual(decision.reason, "incomplete_name_coverage")
        # Exactly one record in the whole fixture, so nothing else is riding on
        # this reason.
        self.assertEqual(
            {
                (item.category, item.name)
                for item in self.index.symbols
                if item.reason == "incomplete_name_coverage"
            },
            {SHAPE_ONE},
        )
        # The reason locates the preserved record for the operator.
        self.assertIn(
            {
                "file": record.declaration.file,
                "start": record.declaration.start,
                "message": "incomplete_name_coverage",
            },
            self._category_outcome(category)["issues"],
        )

    def test_shape_one_really_is_the_unbound_member_type_reference(self):
        """State the shape by its result: one token that no rule accounts for.

        The typedef is written three times: its own declaration, the member type
        of the second aggregate, and a variable type.  The product binds the first
        and the third.  The second is a ``NamedType`` reference that PySlang binds
        to no reference node and reports no issue for, which is why renaming the
        declaration alone used to produce a gate that no longer compiled.
        """

        name = SHAPE_ONE[1]
        offsets = sorted(self._byte_offsets(name))
        self.assertEqual(len(offsets), 3, offsets)
        record = self._one(category=SHAPE_ONE[0], name=name)
        claimed = sorted(
            (source_range.file, source_range.start)
            for source_range in (
                record.declaration,
                *[item.source_range for item in record.occurrences],
            )
        )
        self.assertEqual(len(claimed), 2, claimed)
        self.assertEqual(claimed[0], offsets[0])
        self.assertEqual(claimed[1], offsets[2])
        # The middle spelling is claimed by no record of any category at all.
        unbound_file, unbound_start = offsets[1]
        unbound_end = unbound_start + len(name.encode("utf-8"))
        self.assertNotIn(
            (unbound_file, unbound_start, unbound_end), self._product_accounted()
        )
        design = self.data[unbound_file]
        self.assertEqual(
            design[unbound_start:unbound_end], name.encode("utf-8")
        )
        # And it really sits inside the second aggregate's declaration, as the
        # member type of one of its fields.
        second = self._one(category=SHAPE_TWO[0], name=SHAPE_TWO[1])
        aggregate_start = design.rindex(b"typedef struct packed {", 0, unbound_start)
        self.assertLess(aggregate_start, unbound_start)
        self.assertLess(unbound_start, second.declaration.start)
        self.assertEqual(
            {item.provenance for item in record.occurrences}, {"semantic_type"}
        )

    def test_shape_two_still_renames_so_the_preserve_is_per_record(self):
        """T111's boundary must not regress into a group-wide rollback.

        Shape two is in the same core group as shape one, in the same file, and it
        is even the aggregate that *contains* the unbound reference.  Every token
        spelling it is attributed, so it must still rename.
        """

        category, name = SHAPE_TWO
        record = self._one(category=category, name=name)
        self.assertEqual(record.support, "eligible")
        self.assertIsNone(record.reason)
        self.assertGreater(len(record.occurrences), 0)
        self.assertEqual(
            len(self._byte_offsets(name)), 1 + len(record.occurrences)
        )
        outcome = self._category_outcome(category)
        self.assertGreater(outcome["rename"], 0)
        self.assertEqual(outcome["preserve"], 1)
        # The aggregate fields of both typedefs keep renaming too: the preserve is
        # one record, not one aggregate and not one group.
        for field_name in ("cmd", "inner", "wide"):
            field = self._one(category="struct", name=field_name)
            self.assertEqual(field.support, "eligible", field_name)
            self.assertIsNone(field.reason, field_name)

    # --- T115 2.3: the denominator must stay honest -------------------------

    def test_the_token_denominator_is_every_physical_spelling_in_the_source(self):
        """Coverage must not be bought back by narrowing the token set.

        The enumeration is compared against a raw byte search of the fixture,
        which is ground truth derived from the files rather than from PySlang.
        Excluding any token class -- a position with no binding rule yet, a
        declaration this walk cannot reach, a macro view -- drops a spelling here
        and fails.  The one exclusion the language does justify,
        ``SystemIdentifier`` such as ``$clog2``, can never be a record name, so it
        cannot hide inside this comparison.
        """

        names = frozenset(
            symbol.name for symbol in self.index.symbols if symbol.name
        )
        self.assertGreater(len(names), 20)
        tokens, unverified = rename_index_module._tokens_spelling(
            self.catalog,
            rename_index_module._syntax_nodes(self.catalog),
            names,
            {},
        )
        # A token that cannot be verified against the source bytes is not
        # silently dropped; on this fixture there are none at all.
        self.assertEqual(unverified, frozenset())
        found: dict[str, set[tuple[str, int]]] = {}
        for token in tokens:
            self.assertEqual(
                self.data[token.file][token.start : token.end],
                token.name.encode("utf-8"),
                token,
            )
            found.setdefault(token.name, set()).add((token.file, token.start))
        for name in sorted(names):
            self.assertEqual(found.get(name, set()), self._byte_offsets(name), name)

    def test_exactly_one_token_of_this_fixture_is_unattributed(self):
        """The criterion's own input, stated as a result rather than a shape.

        Combining the three attribution sources must leave exactly one token
        unaccounted for in the whole fixture: the member-type reference of shape
        one.  A narrowed denominator makes this set empty; a broken attribution
        source makes it larger.  Both are failures.
        """

        names = frozenset(
            symbol.name for symbol in self.index.symbols if symbol.name
        )
        cache: dict[object, str | None] = {}
        tokens, unverified = rename_index_module._tokens_spelling(
            self.catalog,
            rename_index_module._syntax_nodes(self.catalog),
            names,
            cache,
        )
        self.assertEqual(unverified, frozenset())
        accounted = self._product_accounted()
        accounted |= rename_index_module._declaration_attributions(
            self.catalog,
            self.nodes,
            {(token.file, token.start): token for token in tokens},
            names,
            cache,
        )
        accounted |= rename_index_module._reference_attributions(
            tokens,
            rename_index_module._reference_spans(
                self.catalog, self.nodes, names, cache
            ),
            self._rewritten_starts(),
        )
        unattributed = sorted(
            (token.file, token.start, token.name)
            for token in tokens
            if (token.file, token.start, token.end) not in accounted
        )
        expected = sorted(self._byte_offsets(SHAPE_ONE[1]))[1]
        self.assertEqual(
            unattributed, [(expected[0], expected[1], SHAPE_ONE[1])]
        )

    # --- T115 6: whole-index invariants ------------------------------------

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
        self.assertIn("incomplete_name_coverage", used)
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

    # --- T115 6: both directions, on real published gates -------------------

    def test_gate_fails_to_publish_before_the_fix_and_audits_clean_after_it(self):
        """The point of T115, proved on this run's own two decision sets.

        Before: the pre-T115 decision set renames the typedef declaration while
        the member-type reference keeps the old name, so the gate has an unknown
        type and strict compilation refuses it.  That is the ``REFUSED_ATOMIC``
        the public entry point reports.

        After: the gate publishes, restores byte for byte, and the read-only
        rename audit returns ``clean`` with no gate-only implicit net.
        """

        before_index = self._pre_t115_index()
        with tempfile.TemporaryDirectory(prefix="t115-audit-") as temporary:
            root = Path(temporary)

            before_mapping = build_mapping_vnext(
                before_index, name_length=20, name_factory=secure_name_factory
            )
            # The renamed declaration really is planned by the pre-fix set, so the
            # failure below is caused by the missing reference and not by the
            # record having been dropped.
            renamed = {
                record["original_name"]
                for record in before_mapping.to_report()["records"]
                if record["action"] == "rename"
            }
            self.assertIn(SHAPE_ONE[1], renamed)
            with self.assertRaises(RewriteVNextError) as raised:
                write_gate_vnext(before_mapping, output_dir=root / "before")
            self.assertEqual(raised.exception.code, "REWRITE_GATE_COMPILE_FAILED")
            self.assertIn("CATALOG_SEMANTIC_FAILED", raised.exception.message)
            self.assertFalse((root / "before").exists())

            after_gate = self._publish(self.index, root, "after")
            after_exit, after = self._audit(after_gate, root / "after.json")
            self.assertEqual(after["verdict"], "clean")
            self.assertEqual(after_exit, 0)
            self.assertEqual(
                after["compile"],
                {
                    "gold": {"parse_errors": 0, "semantic_errors": 0},
                    "gate": {"parse_errors": 0, "semantic_errors": 0},
                },
            )
            self.assertEqual(after["implicit_nets"]["gate_only"], 0)
            self.assertEqual(after["implicit_nets"]["gate_only_detail"], [])
            self.assertEqual(after["renamed_range_bytes"]["mismatched"], 0)
            # The clean verdict is not bought by renaming nothing the audit can
            # see: it still checks real edits, in all four groups.
            self.assertGreater(after["renamed_range_bytes"]["checked"], 0)
            self.assertGreater(after["renamed_records"]["records"], 0)
            # Nor by removing the preserved spelling from the gate: it is still
            # physically there, three times, agreeing with a declaration that was
            # left alone.
            gate_design = (after_gate / "design.sv").read_bytes()
            self.assertEqual(
                gate_design.count(SHAPE_ONE[1].encode("utf-8")), 3
            )
            self.assertNotIn(SHAPE_TWO[1].encode("utf-8"), gate_design)

    # --- T115 6: the public entry point -------------------------------------

    def test_public_cli_reports_four_group_renames_and_byte_identical_restore(self):
        with tempfile.TemporaryDirectory(prefix="t115-cli-") as temporary:
            root = Path(temporary)
            gate = root / "gate"
            encrypted = self._run(
                ROOT / "rtl_encrypt.py",
                "--filelist", str(FIXTURE / "design.f"),
                "--top", "t115_top",
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
                if record["reason"] == "incomplete_name_coverage"
            }
            self.assertEqual(preserved, {SHAPE_ONE})
            for record in report["mapping"]["records"]:
                if record["reason"] == "incomplete_name_coverage":
                    self.assertEqual(record["action"], "preserve")
                    self.assertIsNone(record["renamed_name"])
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

    # --- T115 9: compact Formal positive and fixed functional negative ------

    def test_actual_gate_formal_positive_and_fixed_functional_negative(self):
        with tempfile.TemporaryDirectory(prefix="t115-formal-") as temporary:
            root = Path(temporary)
            gate = root / "gate"
            encrypted = self._run(
                ROOT / "rtl_encrypt.py",
                "--filelist", str(FIXTURE / "formal.f"),
                "--top", "t115_formal_top",
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
                "--top", "t115_formal_top",
                "--seq", "5",
            )
            positive = self._run(ROOT / "scripts" / "formal_equivalence.py", *arguments)
            self.assertEqual(positive.returncode, 0, positive.stdout + positive.stderr)
            positive_json = json.loads(positive.stdout.strip().splitlines()[-1])
            self.assertEqual(positive_json["formal_equivalence"], "pass")
            print(
                "T115_FORMAL_POSITIVE "
                + json.dumps(
                    {
                        "gold": str(FIXTURE),
                        "gate": str(gate),
                        "top": "t115_formal_top",
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
                filelist=negative / "design.f", top="t115_formal_top"
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
                "--top", "t115_formal_top",
                "--seq", "5",
            )
            self.assertNotEqual(negative_result.returncode, 0)
            combined = (negative_result.stdout + negative_result.stderr).lower()
            self.assertIn("unproven", combined)
            self.assertIn("equiv_status -assert", combined)
            print(
                "T115_FORMAL_NEGATIVE "
                + json.dumps(
                    {
                        "gold": str(FIXTURE),
                        "gate": str(negative),
                        "top": "t115_formal_top",
                        "exit": negative_result.returncode,
                        "mutation": "1'b0 -> 1'b1 in t115_cone_mix",
                        "evidence": "unproven; equiv_status -assert",
                    },
                    sort_keys=True,
                )
            )
