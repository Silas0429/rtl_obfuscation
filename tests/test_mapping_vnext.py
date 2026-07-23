from dataclasses import fields, replace
import hashlib
import json
from pathlib import Path
import unittest
from unittest import mock

from rtl_obfuscator import category_profile, inventory, rewrite, source_catalog
from rtl_obfuscator.source_catalog import SourceRange, build_source_catalog
from rtl_obfuscator.source_set import from_filelist, from_single_file
from rtl_obfuscator.symbol_graph import SymbolGraph, build_symbol_graph
from rtl_obfuscator import symbol_graph as symbol_graph_module
from rtl_obfuscator.rewrite_policy import (
    RewritePolicy,
    RewriteDecision,
    build_rewrite_policy,
)
from rtl_obfuscator.mapping_vnext import (
    InputFileDigest,
    MappingRecord,
    MappingVNextError,
    build_mapping_vnext,
)


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "refactor_symbol_graph_parameters"


class MappingVNextTests(unittest.TestCase):
    def _graph(self, filelist: Path, *, top: str | None = None):
        return build_symbol_graph(
            build_source_catalog(
                from_filelist(filelist=filelist, source_root=FIXTURE_ROOT, top=top)
            )
        )

    def _policy(
        self,
        filelist: Path,
        categories,
        *,
        top: str | None = None,
        abi_categories=(),
    ):
        return build_rewrite_policy(
            self._graph(filelist, top=top),
            categories=categories,
            abi_categories=abi_categories,
        )

    @staticmethod
    def _mapping(policy, calls=None, length=16):
        def factory(symbol_id, name_length, unavailable):
            if calls is not None:
                calls.append((symbol_id, name_length, unavailable))
            return "n" + hashlib.sha256(symbol_id.encode("utf-8")).hexdigest()[: name_length - 1]

        return build_mapping_vnext(
            policy,
            name_length=length,
            name_factory=factory,
        )

    @staticmethod
    def _policy_from_graph(graph, policy):
        return build_rewrite_policy(
            graph,
            categories=policy.selected_categories,
            abi_categories=policy.abi_categories,
        )

    @staticmethod
    def _assert_code(callable_obj, code):
        with unittest.TestCase().assertRaises(MappingVNextError) as raised:
            callable_obj()
        unittest.TestCase().assertEqual(raised.exception.code, code)
        unittest.TestCase().assertTrue(str(raised.exception).startswith(f"{code}: "))

    def test_full_no_top_has_20_records_13_7_summary_and_53_ranges(self):
        policy = self._policy(
            FIXTURE_ROOT / "design.f",
            ["signals", "parameters", "genvars"],
        )
        mapping = self._mapping(policy)
        self.assertEqual(len(mapping.records), 20)
        self.assertEqual(
            mapping.to_report()["summary"],
            {"rename": 13, "preserve": 7, "unsupported": 0, "total": 20},
        )
        self.assertEqual(
            mapping.to_report()["range_audit"],
            {"declarations": 20, "occurrences": 33, "total_ranges": 53},
        )

    def test_full_top_parameter_abi_has_16_4_and_preserve_reasons(self):
        policy = self._policy(
            FIXTURE_ROOT / "design.f",
            ["signals", "parameters", "genvars"],
            top="parameter_top",
            abi_categories=["parameters"],
        )
        calls = []
        mapping = self._mapping(policy, calls)
        self.assertEqual(mapping.to_report()["summary"]["rename"], 16)
        self.assertEqual(mapping.to_report()["summary"]["preserve"], 4)
        self.assertEqual(len(calls), 16)
        self.assertEqual(
            sorted(record.reason for record in mapping.records if record.action == "preserve"),
            ["outside_top_closure", "selected_top_boundary", "selected_top_boundary", "selected_top_boundary"],
        )

    def test_closure_top_parameter_abi_has_14_3_and_48_ranges(self):
        policy = self._policy(
            FIXTURE_ROOT / "closure.f",
            ["signals", "parameters", "genvars"],
            top="parameter_top",
            abi_categories=["parameters"],
        )
        calls = []
        mapping = self._mapping(policy, calls)
        self.assertEqual(mapping.to_report()["summary"], {"rename": 14, "preserve": 3, "unsupported": 0, "total": 17})
        self.assertEqual(mapping.to_report()["range_audit"], {"declarations": 17, "occurrences": 31, "total_ranges": 48})
        self.assertEqual(len(calls), 14)
        self.assertEqual(
            [item["file"] for item in mapping.to_report()["input_manifest"]],
            ["rtl/child.sv", "rtl/shadow.sv", "rtl/top.sv"],
        )

    def test_single_file_and_filelist_reports_are_byte_identical(self):
        filelist_policy = self._policy(FIXTURE_ROOT / "single.f", ["signals", "parameters"])
        single_policy = build_rewrite_policy(
            build_symbol_graph(
                build_source_catalog(
                    from_single_file(
                        source_file=FIXTURE_ROOT / "single.sv",
                        source_root=FIXTURE_ROOT,
                    )
                )
            ),
            categories=["signals", "parameters"],
        )
        first = self._mapping(filelist_policy).to_report()
        second = self._mapping(single_policy).to_report()
        self.assertEqual(
            json.dumps(first, sort_keys=True, separators=(",", ":")),
            json.dumps(second, sort_keys=True, separators=(",", ":")),
        )
        self.assertEqual(first["summary"], {"rename": 2, "preserve": 1, "unsupported": 0, "total": 3})
        self.assertEqual(
            [item["file"] for item in first["input_manifest"]],
            ["single.sv"],
        )

    def test_positional_and_signals_only_oracles(self):
        positional_policy = self._policy(
            FIXTURE_ROOT / "positional.f",
            ["parameters"],
            top="positional_top",
            abi_categories=["parameters"],
        )
        signals_policy = self._policy(
            FIXTURE_ROOT / "design.f",
            ["signals"],
            top="parameter_top",
        )
        positional_calls = []
        signals_calls = []
        positional = self._mapping(positional_policy, positional_calls)
        signals = self._mapping(signals_policy, signals_calls)
        self.assertEqual(positional.to_report()["summary"], {"rename": 1, "preserve": 0, "unsupported": 0, "total": 1})
        self.assertEqual(positional.to_report()["range_audit"], {"declarations": 1, "occurrences": 0, "total_ranges": 1})
        self.assertEqual(signals.to_report()["summary"], {"rename": 7, "preserve": 13, "unsupported": 0, "total": 20})
        self.assertEqual(len(positional_calls), 1)
        self.assertEqual(len(signals_calls), 7)
        self.assertEqual(
            [item["file"] for item in positional.to_report()["input_manifest"]],
            ["rtl/positional.sv"],
        )

    def test_records_graph_policy_dataclass_and_report_schema_are_stable(self):
        policy = self._policy(FIXTURE_ROOT / "design.f", ["signals", "parameters", "genvars"], top="parameter_top", abi_categories=["parameters"])
        mapping = self._mapping(policy)
        self.assertIsInstance(mapping, object)
        self.assertEqual([record.symbol_id for record in mapping.records], [symbol.symbol_id for symbol in policy.symbol_graph.symbols])
        self.assertEqual([record.action for record in mapping.records], [decision.action for decision in policy.decisions])
        self.assertEqual({field.name for field in fields(mapping)}, {"format", "schema_version", "rewrite_policy", "name_length", "input_manifest", "records"})
        self.assertEqual({field.name for field in fields(mapping.records[0])}, {"symbol_id", "category", "action", "reason", "original_name", "renamed_name", "owner_module", "semantic_owner", "declaration", "occurrences", "impact", "abi"})
        report = mapping.to_report()
        self.assertEqual(list(report), ["format", "schema_version", "state", "source_set", "selection", "name_length", "input_manifest", "records", "summary", "range_audit"])
        self.assertEqual(list(report["source_set"]), ["schema_version", "ordered_source_files", "included_files", "include_dirs", "defines", "top", "top_closure_files", "compile_order"])
        self.assertEqual(set(report["records"][0]), {"symbol_id", "category", "action", "reason", "original_name", "renamed_name", "owner_module", "semantic_owner", "declaration", "occurrences", "impact", "abi"})

    def test_deterministic_factory_arguments_unavailable_growth_and_json_stability(self):
        policy = self._policy(FIXTURE_ROOT / "design.f", ["signals", "parameters", "genvars"])
        calls = []
        mapping = self._mapping(policy, calls)
        rename_records = [record for record in mapping.records if record.action == "rename"]
        self.assertEqual([call[0] for call in calls], [record.symbol_id for record in rename_records])
        self.assertTrue(all(call[1] == 16 and isinstance(call[2], frozenset) for call in calls))
        for previous, current in zip(calls, calls[1:]):
            self.assertIn(mapping.records[[record.symbol_id for record in mapping.records].index(previous[0])].renamed_name, current[2])
        first = json.dumps(mapping.to_report(), sort_keys=True, separators=(",", ":"))
        second = json.dumps(mapping.to_report(), sort_keys=True, separators=(",", ":"))
        self.assertEqual(first, second)
        self.assertEqual(len({record.renamed_name for record in rename_records}), len(rename_records))

    def test_input_manifest_order_hashes_and_portable_report(self):
        policy = self._policy(FIXTURE_ROOT / "design.f", ["signals", "parameters", "genvars"])
        mapping = self._mapping(policy)
        manifest = mapping.to_report()["input_manifest"]
        self.assertEqual([item["file"] for item in manifest], ["rtl/child.sv", "rtl/shadow.sv", "rtl/top.sv", "rtl/unreachable.sv"])
        self.assertEqual([item["sha256"] for item in manifest], [
            "5912234069b2b4cba33e365361c5974929886390ae9fda123d558102c6ce4777",
            "51d9644e72641311d705ffef098d7836de8a1eaa4dd01a2421bfccc346f82aa8",
            "a59967267facc37cc1fa468daa2d4f2372080ad2f38cf9143e9bd93da225c65a",
            "2a120aa7a316a474980c31909d19f8c35d359b9761dc40fd771ea7ecbfb663aa",
        ])
        self.assertNotIn("origin", mapping.to_report()["source_set"])
        self.assertNotIn("source_root", mapping.to_report()["source_set"])

    def test_name_length_and_noncallable_factory_error_matrix(self):
        policy = self._policy(FIXTURE_ROOT / "single.f", ["signals", "parameters"])
        for value in (True, False, 3, 3.5, "16"):
            with self.subTest(value=value):
                self._assert_code(lambda value=value: build_mapping_vnext(policy, name_length=value, name_factory=lambda *_: "n" * 16), "MAPPING_NAME_LENGTH_INVALID")
        self._assert_code(lambda: build_mapping_vnext(policy, name_length=16, name_factory=None), "MAPPING_NAME_FACTORY_INVALID")

    def test_factory_exception_invalid_candidate_and_collision_errors(self):
        policy = self._policy(FIXTURE_ROOT / "single.f", ["signals", "parameters"])
        self._assert_code(lambda: build_mapping_vnext(policy, name_length=16, name_factory=lambda *_: (_ for _ in ()).throw(RuntimeError("boom"))), "MAPPING_NAME_FACTORY_FAILED")
        for candidate in (None, "short", "_" + "a" * 15):
            with self.subTest(candidate=candidate):
                self._assert_code(lambda candidate=candidate: build_mapping_vnext(policy, name_length=16, name_factory=lambda *_: candidate), "MAPPING_NAME_INVALID")
        for keyword in (
            "module",
            "cmos",
            "config",
            "endcase",
            "endconfig",
            "forever",
            "instance",
            "protected",
            "pulsestyle_ondetect",
            "pulsestyle_onevent",
            "soft",
        ):
            with self.subTest(keyword=keyword):
                self._assert_code(
                    lambda keyword=keyword: build_mapping_vnext(
                        policy,
                        name_length=len(keyword),
                        name_factory=lambda *_: keyword,
                    ),
                    "MAPPING_NAME_INVALID",
                )
        self._assert_code(lambda: build_mapping_vnext(policy, name_length=4, name_factory=lambda *_: "data"), "MAPPING_NAME_COLLISION")

    def test_replace_policy_schema_and_decision_fields_fail_closed(self):
        policy = self._policy(FIXTURE_ROOT / "design.f", ["signals", "parameters", "genvars"])
        cases = [
            replace(policy, schema_version=2),
            replace(policy, symbol_graph=replace(policy.symbol_graph, schema_version=2)),
            replace(policy, symbol_graph=replace(policy.symbol_graph, source_catalog=replace(policy.symbol_graph.source_catalog, schema_version=2))),
            replace(policy, symbol_graph=replace(policy.symbol_graph, source_catalog=replace(policy.symbol_graph.source_catalog, source_set=replace(policy.symbol_graph.source_catalog.source_set, schema_version=2)))),
            replace(policy, decisions=policy.decisions[:-1]),
            replace(policy, decisions=(replace(policy.decisions[0], symbol_id="symbol:wrong") ,) + policy.decisions[1:]),
            replace(policy, decisions=(replace(policy.decisions[0], category="signals") ,) + policy.decisions[1:]),
            replace(policy, decisions=(replace(policy.decisions[0], action="rename", reason=None),) + policy.decisions[1:]),
            replace(policy, decisions=policy.decisions[1:] + policy.decisions[:1]),
        ]
        for malformed in cases:
            with self.subTest(malformed=malformed):
                self._assert_code(lambda malformed=malformed: self._mapping(malformed), "MAPPING_POLICY_INVALID")

    def test_owner_semantic_owner_physical_file_and_range_errors_fail_closed(self):
        policy = self._policy(FIXTURE_ROOT / "design.f", ["signals", "parameters", "genvars"])
        first = policy.symbol_graph.symbols[0]
        cases = [
            replace(first, owner_module="module:missing"),
            replace(first, semantic_owner=""),
            replace(first, declaration=SourceRange("missing.sv", first.declaration.start, first.declaration.end)),
            replace(first, declaration=SourceRange(first.declaration.file, True, first.declaration.end)),
            replace(first, declaration=SourceRange(first.declaration.file, 0, 1)),
        ]
        for malformed_symbol in cases:
            graph = replace(policy.symbol_graph, symbols=(malformed_symbol,) + policy.symbol_graph.symbols[1:])
            malformed_policy = self._policy_from_graph(graph, policy)
            expected = "MAPPING_SOURCE_INVALID" if malformed_symbol in cases[:3] else "MAPPING_RANGE_INVALID"
            with self.subTest(malformed_symbol=malformed_symbol):
                self._assert_code(lambda malformed_policy=malformed_policy: self._mapping(malformed_policy), expected)

    def test_exact_duplicate_and_partial_overlap_ranges_fail_closed(self):
        policy = self._policy(FIXTURE_ROOT / "design.f", ["signals", "parameters", "genvars"])
        first, second = policy.symbol_graph.symbols[:2]
        duplicate = replace(second, name=first.name, declaration=first.declaration, occurrences=())
        duplicate_graph = replace(policy.symbol_graph, symbols=(first, duplicate) + policy.symbol_graph.symbols[2:])
        self._assert_code(lambda: self._mapping(self._policy_from_graph(duplicate_graph, policy)), "MAPPING_RANGE_OVERLAP")

        data = (FIXTURE_ROOT / first.declaration.file).read_bytes()
        overlap_range = SourceRange(first.declaration.file, first.declaration.start + 1, first.declaration.end + 1)
        overlap_name = data[overlap_range.start : overlap_range.end].decode("utf-8")
        overlap = replace(second, name=overlap_name, declaration=overlap_range, occurrences=())
        overlap_graph = replace(policy.symbol_graph, symbols=(first, overlap) + policy.symbol_graph.symbols[2:])
        self._assert_code(lambda: self._mapping(self._policy_from_graph(overlap_graph, policy)), "MAPPING_RANGE_OVERLAP")

    def test_established_graph_blocks_compile_rebuild_and_legacy_paths(self):
        policy = self._policy(FIXTURE_ROOT / "design.f", ["signals", "parameters", "genvars"], top="parameter_top", abi_categories=["parameters"])
        before_graph = policy.symbol_graph.to_report()
        before_bytes = {path: (FIXTURE_ROOT / path).read_bytes() for path in ["rtl/child.sv", "rtl/shadow.sv", "rtl/top.sv", "rtl/unreachable.sv"]}
        with (
            mock.patch.object(source_catalog, "_compile_view", side_effect=AssertionError("catalog recompile")),
            mock.patch.object(symbol_graph_module, "build_symbol_graph", side_effect=AssertionError("graph rebuild")),
            mock.patch.object(inventory, "build_top_project_inventory", side_effect=AssertionError("legacy inventory")),
            mock.patch.object(inventory, "build_filelist_default_inventory", side_effect=AssertionError("legacy inventory")),
            mock.patch.object(rewrite, "_encrypt_project", side_effect=AssertionError("legacy rewrite")),
            mock.patch.object(rewrite, "_encrypt_filelist_manual_v4", side_effect=AssertionError("legacy rewrite")),
            mock.patch.object(category_profile, "resolve", side_effect=AssertionError("legacy profile")),
            mock.patch.object(category_profile, "expand", side_effect=AssertionError("legacy profile")),
        ):
            mapping = self._mapping(policy)
        self.assertEqual(mapping.to_report()["summary"]["rename"], 16)
        self.assertEqual(policy.symbol_graph.to_report(), before_graph)
        self.assertEqual(before_bytes, {path: (FIXTURE_ROOT / path).read_bytes() for path in before_bytes})


if __name__ == "__main__":
    unittest.main()
