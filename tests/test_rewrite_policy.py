from collections import Counter
from dataclasses import fields, replace
import json
from pathlib import Path
import unittest
from unittest import mock

from rtl_obfuscator import category_profile, inventory, rewrite, source_catalog
from rtl_obfuscator.source_catalog import build_source_catalog
from rtl_obfuscator.source_set import from_filelist, from_single_file
from rtl_obfuscator.symbol_graph import build_symbol_graph
from rtl_obfuscator.rewrite_policy import (
    RewritePolicy,
    RewritePolicyError,
    build_rewrite_policy,
)


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "refactor_symbol_graph_parameters"


class RewritePolicyTests(unittest.TestCase):
    def _graph(self, filelist: Path, *, top: str | None = None):
        source_set = from_filelist(
            filelist=filelist,
            source_root=FIXTURE_ROOT,
            top=top,
        )
        return build_symbol_graph(build_source_catalog(source_set))

    @staticmethod
    def _without_origin(report: dict) -> dict:
        result = dict(report)
        graph_report = dict(result["symbol_graph"])
        catalog_report = dict(graph_report["source_catalog"])
        source_set_report = dict(catalog_report["source_set"])
        source_set_report.pop("origin")
        catalog_report["source_set"] = source_set_report
        graph_report["source_catalog"] = catalog_report
        result["symbol_graph"] = graph_report
        return result

    def _policy(
        self,
        filelist: Path,
        categories,
        *,
        top: str | None = None,
        abi_categories=(),
    ):
        graph = self._graph(filelist, top=top)
        return build_rewrite_policy(
            graph,
            categories=categories,
            abi_categories=abi_categories,
        )

    @staticmethod
    def _assert_code(callable_obj, code: str):
        with unittest.TestCase().assertRaises(RewritePolicyError) as raised:
            callable_obj()
        unittest.TestCase().assertEqual(raised.exception.code, code)
        unittest.TestCase().assertTrue(
            str(raised.exception).startswith(f"{code}: ")
        )

    def test_full_without_top_all_categories_has_thirteen_renames(self):
        policy = self._policy(
            FIXTURE_ROOT / "design.f",
            ["signals", "parameters", "genvars"],
        )
        self.assertEqual(
            policy.to_report()["summary"],
            {"rename": 13, "preserve": 7, "unsupported": 0, "total": 20},
        )
        self.assertEqual(
            Counter(
                decision.reason
                for decision in policy.decisions
                if decision.action == "preserve"
            ),
            Counter({"module_abi_requires_top": 7}),
        )

    def test_full_with_top_without_abi_preserves_graph_and_abi_reasons(self):
        policy = self._policy(
            FIXTURE_ROOT / "design.f",
            ["signals", "parameters", "genvars"],
            top="parameter_top",
        )
        self.assertEqual(
            policy.to_report()["summary"],
            {"rename": 13, "preserve": 7, "unsupported": 0, "total": 20},
        )
        self.assertEqual(
            Counter(
                decision.reason
                for decision in policy.decisions
                if decision.action == "preserve"
            ),
            Counter(
                {
                    "abi_not_selected": 3,
                    "selected_top_boundary": 3,
                    "outside_top_closure": 1,
                }
            ),
        )

    def test_full_with_parameter_abi_renames_only_eligible_module_abi(self):
        policy = self._policy(
            FIXTURE_ROOT / "design.f",
            ["signals", "parameters", "genvars"],
            top="parameter_top",
            abi_categories=["parameters"],
        )
        self.assertEqual(
            policy.to_report()["summary"],
            {"rename": 16, "preserve": 4, "unsupported": 0, "total": 20},
        )
        self.assertEqual(
            Counter(
                decision.reason
                for decision in policy.decisions
                if decision.action == "preserve"
            ),
            Counter({"selected_top_boundary": 3, "outside_top_closure": 1}),
        )

    def test_closure_with_top_has_independent_abi_opt_in(self):
        without_abi = self._policy(
            FIXTURE_ROOT / "closure.f",
            ["signals", "parameters", "genvars"],
            top="parameter_top",
        )
        with_abi = self._policy(
            FIXTURE_ROOT / "closure.f",
            ["signals", "parameters", "genvars"],
            top="parameter_top",
            abi_categories=["parameters"],
        )
        self.assertEqual(
            without_abi.to_report()["summary"],
            {"rename": 11, "preserve": 6, "unsupported": 0, "total": 17},
        )
        self.assertEqual(
            with_abi.to_report()["summary"],
            {"rename": 14, "preserve": 3, "unsupported": 0, "total": 17},
        )
        self.assertEqual(
            Counter(
                decision.reason
                for decision in with_abi.decisions
                if decision.action == "preserve"
            ),
            Counter({"selected_top_boundary": 3}),
        )

    def test_single_file_and_filelist_reports_match_after_origin_normalization(self):
        single_graph = build_symbol_graph(
            build_source_catalog(
                from_single_file(
                    source_file=FIXTURE_ROOT / "single.sv",
                    source_root=FIXTURE_ROOT,
                )
            )
        )
        filelist_graph = self._graph(FIXTURE_ROOT / "single.f")
        single_policy = build_rewrite_policy(
            single_graph,
            categories=["signals", "parameters"],
        )
        filelist_policy = build_rewrite_policy(
            filelist_graph,
            categories=["signals", "parameters"],
        )
        self.assertEqual(
            self._without_origin(single_policy.to_report()),
            self._without_origin(filelist_policy.to_report()),
        )
        self.assertEqual(
            single_policy.to_report()["summary"],
            {"rename": 2, "preserve": 1, "unsupported": 0, "total": 3},
        )

    def test_positional_parameter_is_selected_only_with_abi_opt_in(self):
        without_abi = self._policy(
            FIXTURE_ROOT / "positional.f",
            ["parameters"],
            top="positional_top",
        )
        with_abi = self._policy(
            FIXTURE_ROOT / "positional.f",
            ["parameters"],
            top="positional_top",
            abi_categories=["parameters"],
        )
        self.assertEqual(
            without_abi.to_report()["summary"],
            {"rename": 0, "preserve": 1, "unsupported": 0, "total": 1},
        )
        self.assertEqual(
            with_abi.to_report()["summary"],
            {"rename": 1, "preserve": 0, "unsupported": 0, "total": 1},
        )

    def test_signals_only_keeps_graph_reasons_before_category_reason(self):
        policy = self._policy(
            FIXTURE_ROOT / "design.f",
            ["signals"],
            top="parameter_top",
        )
        self.assertEqual(
            policy.to_report()["summary"],
            {"rename": 7, "preserve": 13, "unsupported": 0, "total": 20},
        )
        self.assertEqual(
            Counter(
                decision.reason
                for decision in policy.decisions
                if decision.action == "preserve"
            ),
            Counter(
                {
                    "category_not_selected": 9,
                    "selected_top_boundary": 3,
                    "outside_top_closure": 1,
                }
            ),
        )

    def test_category_and_abi_requests_are_canonical_and_json_stable(self):
        policy = self._policy(
            FIXTURE_ROOT / "design.f",
            ["genvars", "signals", "parameters", "signals"],
            top="parameter_top",
            abi_categories=["parameters", "parameters"],
        )
        self.assertEqual(
            policy.selected_categories,
            ("signals", "parameters", "genvars"),
        )
        self.assertEqual(policy.abi_categories, ("parameters",))
        first = json.dumps(policy.to_report(), sort_keys=True, separators=(",", ":"))
        second = json.dumps(policy.to_report(), sort_keys=True, separators=(",", ":"))
        self.assertEqual(first, second)

    def test_decisions_are_one_to_one_ordered_and_input_graph_is_unchanged(self):
        graph = self._graph(FIXTURE_ROOT / "design.f", top="parameter_top")
        before = graph.to_report()
        policy = build_rewrite_policy(
            graph,
            categories=["signals", "parameters", "genvars"],
            abi_categories=["parameters"],
        )
        self.assertEqual(
            [decision.symbol_id for decision in policy.decisions],
            [symbol.symbol_id for symbol in graph.symbols],
        )
        self.assertEqual(
            [decision.category for decision in policy.decisions],
            [symbol.category for symbol in graph.symbols],
        )
        self.assertEqual(len(policy.decisions), len(graph.symbols))
        self.assertEqual(
            {field.name for field in fields(policy)},
            {"schema_version", "symbol_graph", "selected_categories", "abi_categories", "decisions"},
        )
        symbol_graph_field = next(
            field for field in fields(policy) if field.name == "symbol_graph"
        )
        self.assertFalse(symbol_graph_field.repr)
        self.assertFalse(symbol_graph_field.compare)
        self.assertEqual(policy.to_report()["schema_version"], 1)
        self.assertEqual(
            set(policy.to_report()["decisions"][0]),
            {"symbol_id", "category", "action", "reason"},
        )
        self.assertEqual(
            sum(policy.to_report()["summary"][key] for key in ("rename", "preserve", "unsupported")),
            policy.to_report()["summary"]["total"],
        )
        self.assertEqual(graph.to_report(), before)

    def test_policy_does_not_call_compile_legacy_or_profile_paths(self):
        graph = self._graph(FIXTURE_ROOT / "design.f", top="parameter_top")
        with (
            mock.patch.object(source_catalog, "_compile_view", side_effect=AssertionError("catalog recompile")),
            mock.patch.object(inventory, "build_top_project_inventory", side_effect=AssertionError("legacy inventory")),
            mock.patch.object(inventory, "build_filelist_default_inventory", side_effect=AssertionError("legacy inventory")),
            mock.patch.object(inventory, "_build_inventory", side_effect=AssertionError("legacy inventory")),
            mock.patch.object(inventory, "_build_project_inventory", side_effect=AssertionError("legacy inventory")),
            mock.patch.object(rewrite, "_encrypt_project", side_effect=AssertionError("legacy rewrite")),
            mock.patch.object(rewrite, "_encrypt_filelist_manual_v4", side_effect=AssertionError("legacy rewrite")),
            mock.patch.object(category_profile, "resolve", side_effect=AssertionError("legacy profile")),
            mock.patch.object(category_profile, "expand", side_effect=AssertionError("legacy profile")),
        ):
            policy = build_rewrite_policy(
                graph,
                categories=["signals", "parameters", "genvars"],
                abi_categories=["parameters"],
            )
        self.assertEqual(policy.to_report()["summary"]["rename"], 16)

    def test_request_error_matrix_is_stable(self):
        top_graph = self._graph(FIXTURE_ROOT / "design.f", top="parameter_top")
        no_top_graph = self._graph(FIXTURE_ROOT / "design.f")
        cases = (
            (lambda: build_rewrite_policy(top_graph, categories=[]), "REWRITE_POLICY_EMPTY_SELECTION"),
            (lambda: build_rewrite_policy(top_graph, categories=["all"]), "REWRITE_POLICY_UNKNOWN_CATEGORY"),
            (lambda: build_rewrite_policy(top_graph, categories=["struct"]), "REWRITE_POLICY_UNKNOWN_CATEGORY"),
            (lambda: build_rewrite_policy(top_graph, categories=["unknown"]), "REWRITE_POLICY_UNKNOWN_CATEGORY"),
            (lambda: build_rewrite_policy(top_graph, categories=["signals"], abi_categories=["parameters"]), "REWRITE_POLICY_INVALID_ABI_CATEGORY"),
            (lambda: build_rewrite_policy(top_graph, categories=["signals", "parameters", "genvars"], abi_categories=["signals"]), "REWRITE_POLICY_INVALID_ABI_CATEGORY"),
            (lambda: build_rewrite_policy(top_graph, categories=["signals", "parameters", "genvars"], abi_categories=["genvars"]), "REWRITE_POLICY_INVALID_ABI_CATEGORY"),
            (lambda: build_rewrite_policy(top_graph, categories=["signals", "parameters", "genvars"], abi_categories=["unknown"]), "REWRITE_POLICY_UNKNOWN_CATEGORY"),
            (lambda: build_rewrite_policy(no_top_graph, categories=["parameters"], abi_categories=["parameters"]), "REWRITE_POLICY_TOP_REQUIRED"),
        )
        for callable_obj, code in cases:
            with self.subTest(code=code):
                with self.assertRaises(RewritePolicyError) as raised:
                    callable_obj()
                self.assertEqual(raised.exception.code, code)
                self.assertTrue(str(raised.exception).startswith(f"{code}: "))

    def test_malformed_graphs_fail_closed_and_unsupported_reason_is_preserved(self):
        graph = self._graph(FIXTURE_ROOT / "design.f", top="parameter_top")
        first = graph.symbols[0]
        malformed = (
            replace(first, category="unknown"),
            replace(first, support="unknown"),
            replace(first, abi="unknown"),
            replace(first, support="eligible", reason="bad_reason"),
            replace(first, support="preserved", reason=None),
            replace(first, support="eligible", abi="top_boundary", reason=None),
        )
        for symbol in malformed:
            malformed_graph = replace(graph, symbols=(symbol,) + graph.symbols[1:])
            with self.subTest(symbol=symbol):
                with self.assertRaises(RewritePolicyError) as raised:
                    build_rewrite_policy(
                        malformed_graph,
                        categories=["signals", "parameters", "genvars"],
                    )
                self.assertEqual(raised.exception.code, "REWRITE_POLICY_GRAPH_INVALID")

        no_top_graph = self._graph(FIXTURE_ROOT / "design.f")
        no_top_symbol = replace(
            no_top_graph.symbols[0],
            support="eligible",
            abi="module_abi",
            reason=None,
        )
        with self.assertRaises(RewritePolicyError) as raised:
            build_rewrite_policy(
                replace(no_top_graph, symbols=(no_top_symbol,) + no_top_graph.symbols[1:]),
                categories=["signals", "parameters", "genvars"],
            )
        self.assertEqual(raised.exception.code, "REWRITE_POLICY_GRAPH_INVALID")

        unsupported_symbol = replace(
            first,
            support="unsupported",
            reason="graph_unsupported",
        )
        unsupported_policy = build_rewrite_policy(
            replace(graph, symbols=(unsupported_symbol,) + graph.symbols[1:]),
            categories=["signals", "parameters", "genvars"],
        )
        self.assertEqual(unsupported_policy.decisions[0].action, "unsupported")
        self.assertEqual(unsupported_policy.decisions[0].reason, "graph_unsupported")


if __name__ == "__main__":
    unittest.main()
