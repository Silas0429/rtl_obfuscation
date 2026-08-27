from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from rtl_obfuscator.mapping_vnext import build_mapping_vnext
from rtl_obfuscator.rename_index import build_rename_index
from rtl_obfuscator.rewrite_vnext import restore_gate_vnext, write_gate_vnext
from rtl_obfuscator.source_catalog import build_source_catalog
from rtl_obfuscator.source_set import from_filelist
from rtl_obfuscator.systemverilog_names import secure_name_factory


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "t110_binding_fixes"
CORE_CATEGORIES = ("signals", "ports", "interface", "struct")


def _label_offset(data: bytes, text: str) -> int:
    """Offset of the identifier inside a `.name(` connection label."""

    index = data.index(text.encode("utf-8"))
    return index + 1


class T110BindingFixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source_set = from_filelist(filelist=FIXTURE / "design.f", top="t110_top")
        cls.catalog = build_source_catalog(cls.source_set)
        cls.index = build_rename_index(cls.catalog, categories=("all",))
        cls.files = tuple(cls.source_set.ordered_source_files)
        cls.data = {file: (FIXTURE / file).read_bytes() for file in cls.files}

    def _category_outcome(self, category: str) -> dict:
        # Deliberately not named `_outcome`: `unittest.TestCase` already binds an
        # instance attribute of that name to the runner's internal `_Outcome`
        # object, so a helper called `_outcome` is shadowed per instance and every
        # call raises `TypeError: '_Outcome' object is not callable`.
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

    def _bytes_at(self, source_range) -> bytes:
        return self.data[source_range.file][source_range.start : source_range.end]

    def _run(self, script: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(script), *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )

    # --- T110 6: four groups rename, no residual binding signature -----------

    def test_all_four_core_groups_have_real_renames(self):
        for category in CORE_CATEGORIES:
            outcome = self._category_outcome(category)
            self.assertGreater(outcome["rename"], 0, category)
            self.assertEqual(outcome["unsupported"], 0, category)

    def test_no_source_binding_incomplete_and_no_server_signature_remains(self):
        for category in CORE_CATEGORIES:
            outcome = self._category_outcome(category)
            for issue in outcome["issues"]:
                self.assertNotEqual(
                    issue["message"], "source_binding_incomplete", issue
                )
                self.assertNotIn(
                    "semantic target has no unique physical typed token",
                    str(issue.get("detail", "")),
                    issue,
                )
                self.assertNotIn(
                    issue.get("semantic_kind"),
                    {"PortSymbol", "DefinitionSymbol", "FieldSymbol"},
                    issue,
                )
        self.assertTrue(
            all(symbol.reason != "source_binding_incomplete" for symbol in self.index.symbols)
        )

    def test_only_explained_preserve_reasons_are_used(self):
        allowed = {
            "selected_top_boundary",
            "outside_top_closure",
            "macro_origin_conflict",
            "hierarchical_prefix_unsupported",
        }
        used = {
            symbol.reason for symbol in self.index.symbols if symbol.reason is not None
        }
        self.assertTrue(used)
        self.assertEqual(used - allowed, set())

    # --- T110 2.2: named port connection labels -----------------------------

    def test_every_port_connection_label_matches_its_port_declaration(self):
        labels = [
            (symbol, occurrence)
            for symbol in self.index.symbols
            for occurrence in symbol.occurrences
            if occurrence.provenance == "semantic_port_connection"
        ]
        self.assertTrue(labels)
        for symbol, occurrence in labels:
            self.assertEqual(symbol.category, "ports")
            self.assertEqual(
                self._bytes_at(occurrence.source_range),
                symbol.name.encode("utf-8"),
            )
            self.assertEqual(
                self.data[occurrence.source_range.file][
                    occurrence.source_range.start - 1
                ],
                ord("."),
            )

    def test_reordered_named_connections_bind_without_crosswiring(self):
        cone = self.data["formal_cone.sv"]
        design = self.data["design.sv"]
        expected = {
            "c_third": _label_offset(cone, ".c_third(z0)"),
            "b_second": _label_offset(cone, ".b_second(z1)"),
            "a_first": _label_offset(cone, ".a_first(z2)"),
        }
        again = {
            "c_third": _label_offset(design, ".c_third(in_a)"),
            "a_first": _label_offset(design, ".a_first(in_b)"),
            "b_second": _label_offset(design, ".b_second(in_a)"),
        }
        # The port declaration order is a_first, b_second, c_third while both
        # instantiations write the labels in a different order, so an index
        # pairing would cross-wire every label.
        self.assertNotEqual(
            sorted(expected, key=expected.get), ["a_first", "b_second", "c_third"]
        )
        offsets_by_name = {}
        for name in ("a_first", "b_second", "c_third"):
            record = self._one(category="ports", name=name)
            offsets_by_name[name] = {
                (occurrence.source_range.file, occurrence.source_range.start)
                for occurrence in record.occurrences
                if occurrence.provenance == "semantic_port_connection"
            }
        for name, offset in expected.items():
            self.assertIn(("formal_cone.sv", offset), offsets_by_name[name])
        for name, offset in again.items():
            self.assertIn(("design.sv", offset), offsets_by_name[name])
        claimed = [
            offset for offsets in offsets_by_name.values() for offset in offsets
        ]
        self.assertEqual(len(claimed), len(set(claimed)))

    def test_wildcard_and_positional_connections_produce_no_label_occurrence(self):
        design = self.data["design.sv"]
        cone = self.data["formal_cone.sv"]
        self.assertIn(b"t110_wild_child u_wild (.*);", design)
        self.assertIn(b"t110_leaf u_leaf3 (in_b, in_b, z3);", cone)
        self.assertIn(b"t110_leaf u_leaf_pos (in_a, in_b, out_pos);", design)
        wild_start = design.index(b"module t110_wild_child")
        wild_end = design.index(b"endmodule", wild_start)
        # `.*` names no label token, so no port of the wildcard child may own a
        # connection occurrence.  The selection is bounded by the child module's
        # own byte span: comparing `rfind` of two module headers only bounds the
        # span from below, so it also swept up every port declared after
        # t110_wild_child (t110_wild_parent and t110_top, 16 ports in total).
        wild_child_ports = sorted(
            (
                symbol
                for symbol in self._records(category="ports")
                if symbol.declaration.file == "design.sv"
                and wild_start <= symbol.declaration.start < wild_end
            ),
            key=lambda symbol: symbol.declaration.start,
        )
        self.assertEqual(
            [symbol.name for symbol in wild_child_ports], ["x", "y", "z"]
        )
        for symbol in wild_child_ports:
            self.assertEqual(
                [
                    occurrence
                    for occurrence in symbol.occurrences
                    if occurrence.provenance == "semantic_port_connection"
                ],
                [],
                symbol.name,
            )
            self.assertEqual(symbol.support, "preserved")
            self.assertEqual(symbol.reason, "outside_top_closure")
        # Positional connections have no label either: the reused leaf is
        # instantiated five times but only the three named ones are labelled.
        for name in ("x", "y", "z"):
            leaf_port = next(
                symbol
                for symbol in self._records(category="ports", name=name)
                if symbol.declaration.file == "formal_cone.sv"
            )
            self.assertEqual(
                len(
                    [
                        occurrence
                        for occurrence in leaf_port.occurrences
                        if occurrence.provenance == "semantic_port_connection"
                    ]
                ),
                3,
                name,
            )

    # --- T110 2.3: interface port header ------------------------------------

    def test_interface_port_header_binds_type_and_modport_tokens(self):
        design = self.data["design.sv"]
        interface_type = self._one(category="interface", kind="interface_type")
        self.assertEqual(interface_type.name, "t110_if")
        type_offsets = {
            occurrence.source_range.start
            for occurrence in interface_type.occurrences
            if occurrence.provenance == "semantic_interface_port_type"
        }
        expected_headers = {
            design.index(b"t110_if.Master mp_port"),
            design.index(b"t110_if            plain_port"),
            design.index(b"t110_if.Slave mp2"),
        }
        self.assertEqual(len(expected_headers), 3)
        self.assertEqual(expected_headers - type_offsets, set())
        for name, text in (("Master", "t110_if.Master"), ("Slave", "t110_if.Slave")):
            modport = self._one(category="interface", kind="modport", name=name)
            offsets = {
                occurrence.source_range.start
                for occurrence in modport.occurrences
                if occurrence.provenance == "semantic_interface_port_modport"
            }
            self.assertEqual(
                offsets, {design.index(text.encode()) + len("t110_if.")}, name
            )
            for occurrence in modport.occurrences:
                self.assertEqual(
                    self._bytes_at(occurrence.source_range), name.encode()
                )

    # --- T110 2.4 / 12.2: struct member selects, nested members, sized casts --

    def test_struct_member_selects_and_nested_same_name_members_bind(self):
        design = self.data["design.sv"]
        user = self._one(category="struct", kind="struct_field", name="user")
        offsets = {
            occurrence.source_range.start for occurrence in user.occurrences
        }
        bit_select = design.index(b"word.user[2]") + len("word.")
        part_select = design.index(b"word.user[7:4]") + len("word.")
        self.assertIn(bit_select, offsets)
        self.assertIn(part_select, offsets)
        for occurrence in user.occurrences:
            self.assertEqual(self._bytes_at(occurrence.source_range), b"user")
        # Two different members are spelled `a`: the outer member of
        # t110_word_t and the member of the named typedef t110_inner_t.
        same_name = self._records(category="struct", kind="struct_field", name="a")
        self.assertEqual(len(same_name), 2)
        first, second = same_name
        self.assertNotEqual(first.declaration, second.declaration)
        claims = [
            (occurrence.source_range.file, occurrence.source_range.start)
            for record in same_name
            for occurrence in record.occurrences
        ]
        self.assertEqual(len(claims), len(set(claims)))
        outer_offset = design.index(b"word.a.a  = ok_i;") + len("word.")
        inner_offset = outer_offset + len("a.")
        owner = [
            record
            for record in same_name
            if any(
                occurrence.source_range.start == outer_offset
                for occurrence in record.occurrences
            )
        ]
        self.assertEqual(len(owner), 1)
        # The anonymous inner aggregate owns no record, so the second `a` of
        # `word.a.a` must never be claimed by the outer member.
        self.assertFalse(
            any(
                occurrence.source_range.start == inner_offset
                for record in self.index.symbols
                for occurrence in record.occurrences
            )
        )

    def test_all_member_access_shapes_bind_through_one_path(self):
        """Bit select, part select, nested member and sized cast, one path.

        Only `data.member` exposes ScopedNameSyntax.  A trailing select drops the
        syntax link to None and a sized cast replaces it with
        ParenthesizedExpressionSyntax, so while the end-anchor fallback was gated
        behind `syntax is None` it never fired on the cast shape.  Every shape
        must now reach the member token itself, with the same `semantic_member`
        provenance and the same byte content.
        """

        design = self.data["design.sv"]
        shapes = {
            "bit_select": (design.index(b"word.user[2]") + len("word."), "user"),
            "part_select": (design.index(b"word.user[7:4]") + len("word."), "user"),
            "nested_same_name": (
                design.index(b"word.a.a  = ok_i;") + len("word."),
                "a",
            ),
            "sized_cast_parameter_width": (
                design.index(b"(CAST_W)'(word.ok)") + len("(CAST_W)'(word."),
                "ok",
            ),
            "sized_cast_literal_width": (
                design.index(b"(1)'(inner.a)") + len("(1)'(inner."),
                "a",
            ),
        }
        claims = {
            (occurrence.source_range.start, occurrence.provenance): symbol
            for symbol in self.index.symbols
            for occurrence in symbol.occurrences
            if occurrence.source_range.file == "design.sv"
        }
        for label, (offset, name) in shapes.items():
            self.assertEqual(
                design[offset : offset + len(name)], name.encode("utf-8"), label
            )
            owner = claims.get((offset, "semantic_member"))
            self.assertIsNotNone(owner, label)
            self.assertEqual(owner.category, "struct", label)
            self.assertEqual(owner.kind, "struct_field", label)
            self.assertEqual(owner.name, name, label)
            self.assertEqual(owner.support, "eligible", label)
            self.assertIsNone(owner.reason, label)

    def test_sized_cast_members_do_not_regress_the_struct_group(self):
        """The cast shape must not reintroduce the server's struct signature.

        On StCache every residual struct issue was `source_binding_incomplete /
        FieldSymbol`, and the group transaction turned that into
        `candidate=541 rename=0 preserve=541`.  The fixture now carries the same
        shape, so the struct group must stay fully renamed with no issue at all.
        """

        outcome = self._category_outcome("struct")
        self.assertGreater(outcome["rename"], 0)
        self.assertEqual(outcome["preserve"], 0)
        self.assertEqual(outcome["unsupported"], 0)
        self.assertEqual(outcome["rename"], outcome["candidate"])
        self.assertEqual(outcome["issues"], [])
        for symbol in self._records(category="struct"):
            self.assertEqual(symbol.support, "eligible", symbol.name)
            self.assertIsNone(symbol.reason, symbol.name)

    # --- T110 2.5: interface instances are preserved explicitly -------------

    def test_interface_instances_are_preserved_without_group_rollback(self):
        instances = [
            symbol
            for symbol in self._records(category="interface")
            if symbol.kind in {"interface_instance", "interface_instance_array"}
        ]
        self.assertEqual(
            {symbol.kind for symbol in instances},
            {"interface_instance", "interface_instance_array"},
        )
        for symbol in instances:
            self.assertEqual(symbol.support, "preserved", symbol.name)
            self.assertEqual(symbol.reason, "hierarchical_prefix_unsupported")
        renamed = [
            symbol
            for symbol in self._records(category="interface")
            if symbol.support == "eligible"
        ]
        self.assertEqual(
            {symbol.kind for symbol in renamed},
            {"interface_type", "interface_member", "modport"},
        )
        outcome = self._category_outcome("interface")
        self.assertEqual(outcome["rename"], len(renamed))
        self.assertEqual(outcome["preserve"], len(instances))

    # --- T110 2.1: one owner per physical declaration ------------------------

    def test_reused_module_symbols_have_one_record_and_no_range_conflict(self):
        cone = self.data["formal_cone.sv"]
        self.assertEqual(cone.count(b"t110_leaf u_leaf"), 4)
        for name in ("x", "y", "z", "mixed"):
            matches = [
                symbol
                for symbol in self.index.symbols
                if symbol.name == name
                and symbol.declaration.file == "formal_cone.sv"
            ]
            self.assertEqual(len(matches), 1, name)
        for category in CORE_CATEGORIES:
            for issue in self._category_outcome(category)["issues"]:
                self.assertNotIn(
                    issue["message"],
                    {"cross_record_range_conflict", "macro_origin_conflict"},
                    issue,
                )

    def test_range_audit_has_no_duplicate_or_overlapping_ranges(self):
        report = self.index.to_report()["range_audit"]
        self.assertEqual(report["symbols"], len(self.index.symbols))
        self.assertEqual(
            report["total_ranges"],
            report["declarations"] + report["occurrences"],
        )
        by_file: dict[str, list[tuple[int, int, str]]] = {}
        for symbol in self.index.symbols:
            for source_range in (
                symbol.declaration,
                *[item.source_range for item in symbol.occurrences],
            ):
                by_file.setdefault(source_range.file, []).append(
                    (source_range.start, source_range.end, symbol.symbol_id)
                )
        total = 0
        for file, ranges in by_file.items():
            ranges.sort()
            total += len(ranges)
            self.assertEqual(
                len({(start, end) for start, end, _ in ranges}),
                len(ranges),
                file,
            )
            for previous, current in zip(ranges, ranges[1:]):
                self.assertLessEqual(previous[1], current[0], (file, previous, current))
        self.assertEqual(total, report["total_ranges"])

    # --- T110 6: gate and restore evidence ----------------------------------

    def test_actual_gate_strict_compiles_and_restores_byte_identical(self):
        mapping = build_mapping_vnext(
            self.index, name_length=20, name_factory=secure_name_factory
        )
        physical = tuple(
            dict.fromkeys(
                (*self.source_set.ordered_source_files, *self.source_set.included_files)
            )
        )
        gold = {file: (FIXTURE / file).read_bytes() for file in physical}
        with tempfile.TemporaryDirectory(prefix="t110-gate-") as temporary:
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
                {file: (root / "restore" / file).read_bytes() for file in physical},
                gold,
            )

    def test_public_cli_reports_four_group_renames_and_byte_identical_restore(self):
        with tempfile.TemporaryDirectory(prefix="t110-cli-") as temporary:
            root = Path(temporary)
            gate = root / "gate"
            encrypted = self._run(
                ROOT / "rtl_encrypt.py",
                "--filelist", str(FIXTURE / "design.f"),
                "--top", "t110_top",
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
                self.assertEqual(outcomes[category]["unsupported"], 0, category)
                for issue in outcomes[category]["issues"]:
                    self.assertNotEqual(
                        issue["message"], "source_binding_incomplete", issue
                    )
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
                    (restored / file).read_bytes(), (FIXTURE / file).read_bytes(), file
                )

    def test_actual_gate_formal_positive_and_fixed_functional_negative(self):
        with tempfile.TemporaryDirectory(prefix="t110-formal-") as temporary:
            root = Path(temporary)
            gate = root / "gate"
            encrypted = self._run(
                ROOT / "rtl_encrypt.py",
                "--filelist", str(FIXTURE / "formal.f"),
                "--top", "t110_formal_top",
                "--category", "all",
                "--output-dir", str(gate),
            )
            self.assertEqual(encrypted.returncode, 0, encrypted.stderr)
            summary = json.loads(encrypted.stdout)["summary"]
            self.assertTrue(summary["strict_compile_passed"])
            self.assertGreater(summary["rename"], 0)
            self.assertGreater(summary["modified_tokens"], 0)
            # The proof must run against a gate that really changed: an
            # identity comparison is not evidence.
            self.assertNotEqual(
                (gate / "formal_cone.sv").read_bytes(),
                (FIXTURE / "formal_cone.sv").read_bytes(),
            )
            arguments = (
                "--gold-filelist", str(FIXTURE / "formal.f"),
                "--gold-root", str(FIXTURE),
                "--gate-filelist", str(gate / "design.f"),
                "--gate-root", str(gate),
                "--top", "t110_formal_top",
                "--seq", "5",
            )
            positive = self._run(
                ROOT / "scripts" / "formal_equivalence.py", *arguments
            )
            self.assertEqual(
                positive.returncode, 0, positive.stdout + positive.stderr
            )
            positive_json = json.loads(positive.stdout.strip().splitlines()[-1])
            self.assertEqual(positive_json["formal_equivalence"], "pass")
            print(
                "T110_FORMAL_POSITIVE "
                + json.dumps(
                    {
                        "gold": str(FIXTURE),
                        "gate": str(gate),
                        "top": "t110_formal_top",
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
                filelist=negative / "design.f", top="t110_formal_top"
            )
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
                "--top", "t110_formal_top",
                "--seq", "5",
            )
            self.assertNotEqual(negative_result.returncode, 0)
            combined = (negative_result.stdout + negative_result.stderr).lower()
            self.assertIn("unproven", combined)
            self.assertIn("equiv_status -assert", combined)
            print(
                "T110_FORMAL_NEGATIVE "
                + json.dumps(
                    {
                        "gold": str(FIXTURE),
                        "gate": str(negative),
                        "top": "t110_formal_top",
                        "exit": negative_result.returncode,
                        "mutation": "1'b0 -> 1'b1 in t110_reorder",
                        "evidence": "unproven; equiv_status -assert",
                    },
                    sort_keys=True,
                )
            )
