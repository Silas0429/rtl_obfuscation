from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path, PurePosixPath
import unittest
from unittest.mock import patch

from rtl_obfuscator.rename_index import (
    RenameIndexError,
    _RangePathContext,
    _range_for_location,
    build_rename_index,
)
from rtl_obfuscator.source_catalog import build_source_catalog
from rtl_obfuscator.source_set import from_filelist


ROOT = Path(__file__).resolve().parents[1]
T108_FIXTURE = ROOT / "tests" / "fixtures" / "t108_pyslang_rename_index"
T115_FIXTURE = ROOT / "tests" / "fixtures" / "t115_name_completeness"


def _range_projection(value):
    return {"file": value.file, "start": value.start, "end": value.end}


def _decision_projection(index):
    return {
        "categories": list(index.selected_categories),
        "symbols": [
            {
                "symbol_id": symbol.symbol_id,
                "category": symbol.category,
                "kind": symbol.kind,
                "semantic_kind": symbol.semantic_kind,
                "name": symbol.name,
                "declaration": _range_projection(symbol.declaration),
                "owner_module": symbol.owner_module,
                "semantic_owner": symbol.semantic_owner,
                "occurrences": [
                    {
                        "source_range": _range_projection(item.source_range),
                        "provenance": item.provenance,
                    }
                    for item in symbol.occurrences
                ],
                "impact": symbol.impact,
                "abi": symbol.abi,
                "support": symbol.support,
                "reason": symbol.reason,
            }
            for symbol in index.symbols
        ],
        "decisions": [
            {
                "symbol_id": decision.symbol_id,
                "category": decision.category,
                "action": decision.action,
                "reason": decision.reason,
            }
            for decision in index.decisions
        ],
        "category_outcomes": [dict(item) for item in index.category_outcomes],
    }


def _decision_digest(index) -> str:
    serialized = json.dumps(
        _decision_projection(index),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


class T128RenameIndexRangeCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.t108_source_set = from_filelist(
            filelist=T108_FIXTURE / "design.f", top="top"
        )
        cls.t108_catalog = build_source_catalog(cls.t108_source_set)
        cls.t115_source_set = from_filelist(
            filelist=T115_FIXTURE / "design.f", top="t115_top"
        )
        cls.t115_catalog = build_source_catalog(cls.t115_source_set)

        cls.resolved_buffers = []
        cls.contexts = []
        real_resolve = _RangePathContext._resolve_buffer
        real_factory = _RangePathContext.for_catalog

        def resolve(context, catalog, buffer):
            cls.resolved_buffers.append(buffer)
            return real_resolve(context, catalog, buffer)

        def factory(catalog):
            context = real_factory(catalog)
            cls.contexts.append(context)
            return context

        with patch.object(_RangePathContext, "_resolve_buffer", new=resolve):
            with patch.object(
                _RangePathContext,
                "for_catalog",
                new=classmethod(lambda _cls, catalog: factory(catalog)),
            ):
                cls.index = build_rename_index(
                    cls.t108_catalog, categories=("all",)
                )
        cls.context = cls.contexts[0]
        cls.t108_digest = _decision_digest(cls.index)
        cls.t115_index = build_rename_index(cls.t115_catalog, categories=("all",))
        cls.t115_digest = _decision_digest(cls.t115_index)

    @classmethod
    def tearDownClass(cls):
        evidence = {
            "path_requests": cls.context.path_requests,
            "path_resolutions": cls.context.path_resolutions,
            "range_requests": cls.context.range_requests,
            "range_reads": cls.context.range_reads,
            "range_cache_hits": cls.context.range_cache_hits,
            "t108_digest": cls.t108_digest,
            "t115_digest": cls.t115_digest,
        }
        print("T128_CACHE_EVIDENCE_JSON=" + json.dumps(evidence, sort_keys=True))

    def test_exact_decisions_symbols_occurrences_and_category_outcomes(self):
        self.assertEqual(len(self.index.symbols), 42)
        self.assertEqual(sum(len(item.occurrences) for item in self.index.symbols), 70)
        self.assertEqual(len(self.t115_index.symbols), 56)
        self.assertEqual(
            sum(len(item.occurrences) for item in self.t115_index.symbols), 125
        )
        self.assertEqual(
            self.t108_digest,
            "0180e2d80e623f5677e3dbce6cf0259e9a486380d8b4ad7142c023350f23bf9f",
        )
        self.assertEqual(
            self.t115_digest,
            "dbbc8fb76135251abcd8f87dca6e78ce3a5df7c19101e1c3907f020d8dd49a78",
        )

    def test_build_uses_one_context_and_one_resolution_per_hashable_buffer(self):
        self.assertEqual(len(self.contexts), 1)
        self.assertGreater(self.context.path_requests, self.context.path_resolutions)
        self.assertGreater(self.context.path_resolutions, 0)
        self.assertTrue(self.resolved_buffers)
        self.assertTrue(all(hash(buffer) is not None for buffer in self.resolved_buffers))
        self.assertTrue(all(count == 1 for count in Counter(self.resolved_buffers).values()))

    def test_build_uses_exact_range_reads_and_cache_hits(self):
        self.assertGreater(self.context.range_requests, self.context.range_reads)
        self.assertGreater(self.context.range_reads, 0)
        self.assertGreater(self.context.range_cache_hits, 0)
        self.assertEqual(
            self.context.range_cache_hits,
            self.context.range_requests - self.context.range_reads,
        )
        self.assertEqual(len(self.context.range_bytes), self.context.range_reads)
        for (file, start, end), data in self.context.range_bytes.items():
            self.assertFalse(PurePosixPath(file).is_absolute())
            self.assertEqual(len(data), end - start)

    def test_fragment_cache_is_private_and_only_contains_requested_bytes(self):
        source = (T108_FIXTURE / "design.sv").read_bytes()
        first = _RangePathContext.for_catalog(self.t108_catalog)
        with patch.object(Path, "read_bytes", side_effect=AssertionError("full read")):
            expected = first.read_range(self.t108_catalog, "./design.sv", 0, 8)
            repeated = first.read_range(self.t108_catalog, "design.sv", 0, 8)
        self.assertEqual(expected, source[:8])
        self.assertEqual(repeated, expected)
        self.assertEqual(first.range_reads, 1)
        self.assertEqual(first.range_cache_hits, 1)
        self.assertEqual(first.range_bytes, {("design.sv", 0, 8): source[:8]})

        second = _RangePathContext.for_catalog(self.t108_catalog)
        self.assertEqual(second.range_bytes, {})
        self.assertEqual(second.read_range(self.t108_catalog, "design.sv", 0, 8), expected)
        self.assertEqual(second.range_reads, 1)
        self.assertEqual(second.range_cache_hits, 0)

    def test_failed_ranges_and_paths_remain_fail_closed(self):
        negative = _RangePathContext.for_catalog(self.t108_catalog)
        with self.assertRaises(RenameIndexError) as negative_offset:
            negative.read_range(self.t108_catalog, "design.sv", -1, 2)
        self.assertEqual(negative_offset.exception.code, "RENAME_INDEX_RANGE_INVALID")
        self.assertEqual(negative_offset.exception.file, "design.sv")
        self.assertEqual(negative_offset.exception.start, -1)

        with self.assertRaises(RenameIndexError) as reverse:
            negative.read_range(self.t108_catalog, "design.sv", 3, 3)
        self.assertEqual(reverse.exception.code, "RENAME_INDEX_RANGE_INVALID")

        source = (T108_FIXTURE / "design.sv").read_bytes()
        with self.assertRaises(RenameIndexError) as short_read:
            negative.read_range(
                self.t108_catalog, "design.sv", 0, len(source) + 1
            )
        self.assertEqual(short_read.exception.code, "RENAME_INDEX_RANGE_INVALID")
        self.assertEqual(short_read.exception.start, 0)

        node = next(
            item
            for item in self._nodes(self.t108_catalog)
            if type(item).__name__ == "PortSymbol" and str(item.name) == "clk"
        )
        with self.assertRaises(RenameIndexError) as mismatch:
            _range_for_location(
                self.t108_catalog,
                node.location,
                "bad",
                context=_RangePathContext.for_catalog(self.t108_catalog),
            )
        self.assertEqual(mismatch.exception.code, "RENAME_INDEX_RANGE_INVALID")
        self.assertEqual(mismatch.exception.file, "design.sv")
        self.assertEqual(mismatch.exception.start, int(node.location.offset))

        with self.assertRaises(RenameIndexError) as unreadable:
            negative.read_range(self.t108_catalog, "missing.sv", 0, 1)
        self.assertEqual(unreadable.exception.code, "RENAME_INDEX_SOURCE_INVALID")

        with self.assertRaises(RenameIndexError) as outside:
            negative.read_range(self.t108_catalog, "../outside.sv", 0, 1)
        self.assertEqual(outside.exception.code, "RENAME_INDEX_RANGE_INVALID")

        unknown = object()
        path_context = _RangePathContext.for_catalog(self.t108_catalog)
        self.assertIsNone(path_context.file_for_buffer(self.t108_catalog, unknown))
        self.assertIsNone(path_context.file_for_buffer(self.t108_catalog, unknown))
        self.assertEqual(path_context.path_resolutions, 1)

    @staticmethod
    def _nodes(catalog):
        nodes = []
        catalog.catalog_root.visit(nodes.append)
        return nodes


if __name__ == "__main__":
    unittest.main()
