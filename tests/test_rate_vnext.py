from dataclasses import replace
from decimal import Decimal, ROUND_CEILING
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from rtl_obfuscator import rewrite as legacy_rewrite
from rtl_obfuscator.mapping_vnext import InputFileDigest, build_mapping_vnext
from rtl_obfuscator.rate_vnext import (
    RateCandidateVNext,
    RateVNextError,
    build_rate_selection_vnext,
    greedy_unique_line_v1,
)
from rtl_obfuscator.rewrite_policy import build_rewrite_policy
from rtl_obfuscator.source_catalog import SourceRange, build_source_catalog
from rtl_obfuscator.source_set import from_filelist, from_single_file
from rtl_obfuscator.symbol_graph import build_symbol_graph


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "refactor_symbol_graph_parameters"


def _deterministic_factory(symbol_id: str, name_length: int, unavailable: frozenset[str]) -> str:
    del unavailable
    return "n" + hashlib.sha256(symbol_id.encode("utf-8")).hexdigest()[: name_length - 1]


def _range_lines(source_range: SourceRange, content: bytes) -> set[int]:
    lines: set[int] = set()
    offset = 0
    for number, line in enumerate(content.splitlines(keepends=True), start=1):
        end = offset + len(line)
        if source_range.start < end and source_range.end > offset:
            lines.add(number)
        offset = end
    return lines


class RateSelectionVNextTests(unittest.TestCase):
    def _mapping(
        self,
        filelist: Path,
        *,
        top: str | None = None,
        categories=("signals", "parameters", "genvars"),
        abi_categories=(),
        single_file: bool = False,
    ):
        if single_file:
            source_set = from_single_file(
                source_file=FIXTURE_ROOT / "single.sv",
                source_root=FIXTURE_ROOT,
                top=top,
            )
        else:
            source_set = from_filelist(
                filelist=filelist,
                source_root=FIXTURE_ROOT,
                top=top,
            )
        graph = build_symbol_graph(build_source_catalog(source_set))
        policy = build_rewrite_policy(
            graph,
            categories=categories,
            abi_categories=abi_categories,
        )
        return build_mapping_vnext(
            policy,
            name_length=16,
            name_factory=_deterministic_factory,
        )

    @staticmethod
    def _assert_code(callable_obj, code: str) -> None:
        with unittest.TestCase().assertRaises(RateVNextError) as raised:
            callable_obj()
        unittest.TestCase().assertEqual(raised.exception.code, code)
        unittest.TestCase().assertTrue(str(raised.exception).startswith(f"{code}: "))

    def test_full_top_selection_has_complete_records_and_rate_equations(self):
        mapping = self._mapping(
            FIXTURE_ROOT / "design.f",
            top="parameter_top",
            abi_categories=("parameters",),
        )
        selection = build_rate_selection_vnext(mapping, "0.5")
        report = selection.to_report()

        self.assertEqual(
            list(report),
            [
                "format",
                "schema_version",
                "state",
                "mapping_format",
                "algorithm",
                "target",
                "total_lines",
                "target_lines",
                "candidate_lines",
                "selected_lines",
                "actual_rate",
                "overshoot_lines",
                "maximum_rate",
                "target_unreachable",
                "selection_mode",
                "candidate_entries",
                "selected_entries",
                "candidates",
            ],
        )
        self.assertEqual(report["format"], "rtl-obfuscation.rate-selection-vnext")
        self.assertEqual(report["mapping_format"], "rtl-obfuscation.mapping-vnext")
        self.assertEqual(report["algorithm"], "greedy_unique_line_v1")
        self.assertEqual(report["candidate_entries"], 16)
        self.assertEqual(report["selected_entries"], sum(item["selected"] for item in report["candidates"]))

        effective_total = 0
        for file in mapping.rewrite_policy.symbol_graph.source_catalog.source_set.ordered_source_files:
            content = (FIXTURE_ROOT / file).read_bytes()
            effective_total += sum(
                line.strip() != b"" and not line.strip().startswith(b"//")
                for line in content.splitlines()
            )
        expected_target = int(
            (Decimal("0.5") * Decimal(effective_total)).to_integral_value(
                rounding=ROUND_CEILING
            )
        )
        self.assertEqual(report["total_lines"], effective_total)
        self.assertEqual(report["target_lines"], expected_target)

        candidate_lines = {
            (item["file"], item["line"])
            for candidate in report["candidates"]
            for item in candidate["affected_lines"]
        }
        selected_lines = {
            (item["file"], item["line"])
            for candidate in report["candidates"]
            if candidate["selected"]
            for item in candidate["affected_lines"]
        }
        self.assertEqual(report["candidate_lines"], len(candidate_lines))
        self.assertEqual(report["selected_lines"], len(selected_lines))
        self.assertEqual(report["actual_rate"], len(selected_lines) / effective_total)
        self.assertEqual(report["maximum_rate"], len(candidate_lines) / effective_total)
        self.assertEqual(report["overshoot_lines"], max(0, len(selected_lines) - expected_target))
        if report["target_unreachable"]:
            self.assertEqual(report["selection_mode"], "all_candidates")
            self.assertEqual(len(selected_lines), len(candidate_lines))
        else:
            self.assertEqual(report["selection_mode"], "greedy")
            self.assertGreaterEqual(len(selected_lines), expected_target)

        mapping_by_id = {record.symbol_id: record for record in mapping.records}
        for candidate in report["candidates"]:
            record = mapping_by_id[candidate["symbol_id"]]
            self.assertEqual(record.action, "rename")
            ranges = (record.declaration,) + tuple(item.source_range for item in record.occurrences)
            expected_lines = {
                (source_range.file, line)
                for source_range in ranges
                for line in _range_lines(source_range, (FIXTURE_ROOT / source_range.file).read_bytes())
            }
            actual_lines = {
                (item["file"], item["line"])
                for item in candidate["affected_lines"]
            }
            self.assertEqual(actual_lines, expected_lines)
            self.assertEqual(candidate["affected_line_count"], len(actual_lines))

        keys = [
            (
                item["declaration"]["file"],
                item["declaration"]["start"],
                item["category"],
                item["owner_module"],
                item["original_name"],
                item["symbol_id"],
            )
            for item in report["candidates"]
        ]
        self.assertEqual(keys, sorted(keys))
        self.assertNotIn(str(FIXTURE_ROOT.resolve()), json.dumps(report, ensure_ascii=False))

    def test_single_filelist_and_single_file_json_are_normalized(self):
        filelist_mapping = self._mapping(
            FIXTURE_ROOT / "single.f",
            categories=("signals", "parameters"),
        )
        single_mapping = self._mapping(
            FIXTURE_ROOT / "single.f",
            categories=("signals", "parameters"),
            single_file=True,
        )
        filelist_json = json.dumps(
            build_rate_selection_vnext(filelist_mapping, "0.5").to_report(),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        single_json = json.dumps(
            build_rate_selection_vnext(single_mapping, "0.5").to_report(),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        self.assertEqual(filelist_json, single_json)

    def test_deterministic_json_is_byte_identical_and_build_has_no_output(self):
        mapping = self._mapping(
            FIXTURE_ROOT / "design.f",
            top="parameter_top",
            abi_categories=("parameters",),
        )
        with tempfile.TemporaryDirectory() as temp:
            before = set(Path(temp).iterdir())
            first = json.dumps(
                build_rate_selection_vnext(mapping, "0.5").to_report(),
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            second = json.dumps(
                build_rate_selection_vnext(mapping, "0.5").to_report(),
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            self.assertEqual(first, second)
            self.assertEqual(set(Path(temp).iterdir()), before)
            self.assertEqual(list(Path(temp).glob("*.json")), [])
            self.assertEqual(list(Path(temp).glob(".*.tmp")), [])

    def test_no_candidates_and_zero_effective_lines_select_all_candidates_mode(self):
        no_candidate_mapping = self._mapping(
            FIXTURE_ROOT / "single.f",
            categories=("genvars",),
        )
        no_candidate = build_rate_selection_vnext(no_candidate_mapping, "0.5")
        self.assertEqual(no_candidate.candidate_lines, 0)
        self.assertEqual(no_candidate.selected_lines, 0)
        self.assertTrue(no_candidate.target_unreachable)
        self.assertEqual(no_candidate.selection_mode, "all_candidates")
        self.assertEqual(no_candidate.candidates, ())

        with tempfile.TemporaryDirectory() as temp:
            source_file = Path(temp) / "zero.sv"
            source_file.write_bytes(b"// comment\n\n   // another comment\n")
            source_set = no_candidate_mapping.rewrite_policy.symbol_graph.source_catalog.source_set
            catalog = no_candidate_mapping.rewrite_policy.symbol_graph.source_catalog
            graph = no_candidate_mapping.rewrite_policy.symbol_graph
            policy = no_candidate_mapping.rewrite_policy
            zero_source_set = replace(
                source_set,
                source_root=Path(temp),
                ordered_source_files=("zero.sv",),
                included_files=(),
                top_closure_files=(),
                compile_order=("zero.sv",),
            )
            zero_catalog = replace(catalog, source_set=zero_source_set)
            zero_graph = replace(graph, source_catalog=zero_catalog, symbols=())
            zero_policy = replace(policy, symbol_graph=zero_graph, decisions=())
            zero_mapping = replace(
                no_candidate_mapping,
                rewrite_policy=zero_policy,
                input_manifest=(
                    InputFileDigest("zero.sv", hashlib.sha256(source_file.read_bytes()).hexdigest()),
                ),
                records=(),
            )
            zero = build_rate_selection_vnext(zero_mapping, "0.5")
            self.assertEqual(zero.total_lines, 0)
            self.assertEqual(zero.target_lines, 0)
            self.assertEqual(zero.candidate_lines, 0)
            self.assertEqual(zero.selected_lines, 0)
            self.assertEqual(zero.actual_rate, 0.0)
            self.assertEqual(zero.maximum_rate, 0.0)
            self.assertTrue(zero.target_unreachable)
            self.assertEqual(zero.selection_mode, "all_candidates")

    def test_unreachable_target_selects_all_candidates(self):
        mapping = self._mapping(
            FIXTURE_ROOT / "design.f",
            top="parameter_top",
            abi_categories=("parameters",),
        )
        selection = build_rate_selection_vnext(mapping, "1")
        self.assertTrue(selection.target_unreachable)
        self.assertEqual(selection.selection_mode, "all_candidates")
        self.assertEqual(selection.selected_lines, selection.candidate_lines)
        self.assertTrue(all(candidate.selected for candidate in selection.candidates))

    def test_invalid_rates_are_rejected_without_writing(self):
        mapping = self._mapping(FIXTURE_ROOT / "single.f", categories=("signals",))
        with tempfile.TemporaryDirectory() as temp:
            for value in ("", "0", "1.1", "NaN", "Infinity", "-0.1", "not-a-rate"):
                before = set(Path(temp).iterdir())
                self._assert_code(
                    lambda value=value: build_rate_selection_vnext(mapping, value),
                    "RATE_SELECTION_INVALID",
                )
                self.assertEqual(set(Path(temp).iterdir()), before)
            self._assert_code(
                lambda: build_rate_selection_vnext(mapping, 0.5),
                "RATE_SELECTION_INVALID",
            )

    def test_manifest_range_and_selection_identity_fail_closed(self):
        mapping = self._mapping(
            FIXTURE_ROOT / "design.f",
            top="parameter_top",
            abi_categories=("parameters",),
        )
        bad_manifest = replace(
            mapping,
            input_manifest=(replace(mapping.input_manifest[0], sha256="0" * 64),) + mapping.input_manifest[1:],
        )
        self._assert_code(
            lambda: build_rate_selection_vnext(bad_manifest, "0.5"),
            "RATE_MAPPING_INVALID",
        )
        first = mapping.records[0]
        bad_range = replace(
            mapping,
            records=(replace(first, declaration=replace(first.declaration, start=first.declaration.start + 1)),)
            + mapping.records[1:],
        )
        self._assert_code(
            lambda: build_rate_selection_vnext(bad_range, "0.5"),
            "RATE_MAPPING_INVALID",
        )
        selection = build_rate_selection_vnext(mapping, "0.5")
        self._assert_code(
            lambda: replace(selection, target=Decimal("0.4")).to_report(),
            "RATE_SELECTION_FAILED",
        )
        self._assert_code(
            lambda: replace(selection, candidates=selection.candidates[:-1]).to_report(),
            "RATE_CANDIDATE_INVALID",
        )

    def test_legacy_rate_helpers_are_not_called_and_greedy_tie_is_stable(self):
        mapping = self._mapping(FIXTURE_ROOT / "single.f", categories=("signals",))
        with mock.patch.object(legacy_rewrite, "_parse_encryption_rate", side_effect=AssertionError("legacy")), mock.patch.object(
            legacy_rewrite, "_rate_selection", side_effect=AssertionError("legacy")
        ):
            selection = build_rate_selection_vnext(mapping, "0.5")
        self.assertEqual(selection.algorithm, "greedy_unique_line_v1")

        candidates = (
            RateCandidateVNext(
                "a", "signals", "m", "a", SourceRange("a.sv", 0, 1), (("a.sv", 1),), False
            ),
            RateCandidateVNext(
                "b", "signals", "m", "b", SourceRange("b.sv", 0, 1), (("b.sv", 1),), False
            ),
        )
        selected = greedy_unique_line_v1(candidates, target_lines=1, total_lines=10)
        self.assertTrue(selected[0].selected)
        self.assertFalse(selected[1].selected)


if __name__ == "__main__":
    unittest.main()
