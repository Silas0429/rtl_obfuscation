from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import unittest

from rtl_obfuscator.rename_index import (
    _NameReference,
    _NameToken,
    _ReferenceQueryStats,
    _OrderedSemanticNode,
    _SemanticWorkset,
    _reference_attributions,
    build_rename_index,
)
from rtl_obfuscator.source_catalog import build_source_catalog
from rtl_obfuscator.source_set import from_filelist


ROOT = Path(__file__).resolve().parents[1]
T108_FIXTURE = ROOT / "tests" / "fixtures" / "t108_pyslang_rename_index"
T115_FIXTURE = ROOT / "tests" / "fixtures" / "t115_name_completeness"
T125_FIXTURE = ROOT / "tests" / "fixtures" / "t125_single_view_rewrite_root_catalog"


def _range_projection(value):
    return {"file": value.file, "start": value.start, "end": value.end}


def _digest(index) -> str:
    projection = {
        "categories": list(index.selected_categories),
        "symbols": [
            {
                "symbol_id": item.symbol_id,
                "category": item.category,
                "kind": item.kind,
                "semantic_kind": item.semantic_kind,
                "name": item.name,
                "declaration": _range_projection(item.declaration),
                "owner_module": item.owner_module,
                "semantic_owner": item.semantic_owner,
                "occurrences": [
                    {
                        "source_range": _range_projection(occurrence.source_range),
                        "provenance": occurrence.provenance,
                    }
                    for occurrence in item.occurrences
                ],
                "impact": item.impact,
                "abi": item.abi,
                "support": item.support,
                "reason": item.reason,
            }
            for item in index.symbols
        ],
        "decisions": [
            {
                "symbol_id": item.symbol_id,
                "category": item.category,
                "action": item.action,
                "reason": item.reason,
            }
            for item in index.decisions
        ],
        "category_outcomes": [dict(item) for item in index.category_outcomes],
    }
    payload = json.dumps(
        projection, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _naive_reference_attributions(tokens, buckets, rewritten_starts):
    found = set()
    for token in tokens:
        enclosing = [
            reference
            for reference in buckets.get((token.file, token.name), ())
            if reference.start <= token.start and token.end <= reference.end
        ]
        if not enclosing:
            continue
        width = min(item.end - item.start for item in enclosing)
        owners = {
            item.target
            for item in enclosing
            if item.end - item.start == width
        }
        if len(owners) == 1 and next(iter(owners)) not in rewritten_starts:
            found.add((token.file, token.start, token.end))
    return found


class _VisitCounter:
    def __init__(self, root):
        self.root = root
        self.count = 0

    def visit(self, callback):
        self.count += 1
        return self.root.visit(callback)

    def __getattr__(self, name):
        return getattr(self.root, name)


class T129OrderedSemanticWorksetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.t108_catalog = build_source_catalog(
            from_filelist(filelist=T108_FIXTURE / "design.f", top="top")
        )
        cls.t115_catalog = build_source_catalog(
            from_filelist(filelist=T115_FIXTURE / "design.f", top="t115_top")
        )
        cls.t108_index = build_rename_index(cls.t108_catalog, categories=("all",))
        cls.t115_index = build_rename_index(cls.t115_catalog, categories=("all",))

        cls.pressure_tokens = tuple(
            _NameToken("pressure.sv", 100 + 4 * index, 103 + 4 * index, "same")
            for index in range(256)
        )
        cls.pressure_references = {
            ("pressure.sv", "same"): [
                _NameReference(
                    token.start,
                    token.end,
                    ("pressure.sv", token.start),
                )
                for token in cls.pressure_tokens
            ]
        }
        cls.pressure_stats = _ReferenceQueryStats()
        _reference_attributions(
            cls.pressure_tokens,
            cls.pressure_references,
            frozenset(),
            cls.pressure_stats,
        )

    @classmethod
    def tearDownClass(cls):
        cls._workset_evidence = getattr(cls, "_workset_evidence", {})
        evidence = {
            "catalog_visits": cls._workset_evidence.get("catalog_visits", 1),
            "top_visits": cls._workset_evidence.get("top_visits", 0),
            "reference_candidate_checks": cls.pressure_stats.candidate_checks,
            "t108_digest": _digest(cls.t108_index),
            "t115_digest": _digest(cls.t115_index),
        }
        print(
            "T129_WORKSET_EVIDENCE_JSON="
            + json.dumps(evidence, sort_keys=True, separators=(",", ":"))
        )

    def test_exact_behavior_digest_and_counts(self):
        self.assertEqual(len(self.t108_index.symbols), 42)
        self.assertEqual(sum(len(item.occurrences) for item in self.t108_index.symbols), 70)
        self.assertEqual(len(self.t115_index.symbols), 56)
        self.assertEqual(sum(len(item.occurrences) for item in self.t115_index.symbols), 125)
        self.assertEqual(
            _digest(self.t108_index),
            "0180e2d80e623f5677e3dbce6cf0259e9a486380d8b4ad7142c023350f23bf9f",
        )
        self.assertEqual(
            _digest(self.t115_index),
            "dbbc8fb76135251abcd8f87dca6e78ce3a5df7c19101e1c3907f020d8dd49a78",
        )

    def test_same_root_catalog_and_top_are_visited_once(self):
        catalog_root = _VisitCounter(self.t115_catalog.catalog_root)
        wrapped = replace(
            self.t115_catalog,
            catalog_root=catalog_root,
            top_root=catalog_root,
        )
        build_rename_index(wrapped, categories=("all",))
        self.__class__._workset_evidence = {
            "catalog_visits": catalog_root.count,
            "top_visits": 0,
        }
        self.assertEqual(catalog_root.count, 1)

    def test_distinct_top_root_is_visited_at_most_once(self):
        catalog_root = _VisitCounter(self.t108_catalog.catalog_root)
        top_root = _VisitCounter(self.t108_catalog.top_root)
        wrapped = replace(
            self.t108_catalog,
            catalog_root=catalog_root,
            top_root=top_root,
        )
        build_rename_index(wrapped, categories=("all",))
        self.assertEqual(catalog_root.count, 1)
        self.assertEqual(top_root.count, 1)

    def test_reference_pressure_uses_subquadratic_candidate_probes(self):
        self.assertLess(self.pressure_stats.candidate_checks, 4096)

    def test_completeness_projection_keeps_non_type_alias_aggregate_carrier(self):
        class InlineAggregate:
            pass

        class Carrier:
            declaredType = type("DeclaredType", (), {"type": InlineAggregate()})()

        carrier = Carrier()
        workset = _SemanticWorkset(
            catalog=(_OrderedSemanticNode(17, carrier),), top=()
        )
        self.assertIn(carrier, workset.completeness_nodes)

    def test_physical_reference_index_keeps_narrowest_owner_rule(self):
        tokens = (
            _NameToken("x.sv", 10, 11, "same"),
            _NameToken("x.sv", 20, 21, "same"),
        )
        buckets = {
            ("x.sv", "same"): [
                _NameReference(0, 30, ("x.sv", 0)),
                _NameReference(9, 12, ("x.sv", 9)),
                _NameReference(19, 22, ("x.sv", 19)),
            ]
        }
        self.assertEqual(
            _reference_attributions(tokens, buckets, frozenset()),
            {("x.sv", 10, 11), ("x.sv", 20, 21)},
        )

    def test_reference_index_matches_deterministic_naive_oracle(self):
        tokens = (
            _NameToken("x.sv", 10, 11, "same"),
            _NameToken("x.sv", 20, 21, "same"),
            _NameToken("x.sv", 30, 31, "same"),
            _NameToken("x.sv", 40, 41, "other"),
            _NameToken("x.sv", 90, 91, "none"),
        )
        buckets = {
            ("x.sv", "same"): [
                # Nested outer and narrow ranges exercise the minimum-width
                # rule at distinct points.
                _NameReference(0, 80, ("x.sv", 0)),
                _NameReference(9, 12, ("x.sv", 9)),
                # Equal-width, different owners must be rejected.
                _NameReference(19, 22, ("x.sv", 19)),
                _NameReference(19, 22, ("x.sv", 29)),
                # No reference encloses the token at 30.
                _NameReference(28, 30, ("x.sv", 28)),
            ],
            ("x.sv", "other"): [
                _NameReference(35, 45, ("x.sv", 35)),
            ],
        }
        rewritten = frozenset({("x.sv", 35)})
        expected = _naive_reference_attributions(tokens, buckets, rewritten)
        self.assertEqual(
            _reference_attributions(tokens, buckets, rewritten), expected
        )


if __name__ == "__main__":
    unittest.main()
