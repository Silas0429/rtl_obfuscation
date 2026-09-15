"""Main-Agent frozen full-name, provenance, error-order and report oracles."""

from dataclasses import replace
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import rtl_obfuscator.mapping_vnext as mapping_module
from rtl_obfuscator.mapping_vnext import MappingVNextError, build_mapping_vnext
from rtl_obfuscator.rename_index import SymbolOccurrence, build_rename_index
from rtl_obfuscator.source_catalog import build_source_catalog
from rtl_obfuscator.source_set import from_filelist
from rtl_obfuscator.systemverilog_names import is_plain_identifier


ROOT = Path(__file__).resolve().parents[1]
T108 = ROOT / "tests/fixtures/t108_pyslang_rename_index"
T125 = ROOT / "tests/fixtures/t125_single_view_rewrite_root_catalog"


class _RootView:
    def __init__(self, root, *, extra=None, fail=False):
        self.root = root
        self.extra = extra
        self.fail = fail
        self.visits = 0

    def __getattr__(self, name):
        return getattr(self.root, name)

    def visit(self, callback):
        self.visits += 1
        if self.fail:
            raise RuntimeError("semantic root intentionally unavailable")
        self.root.visit(callback)
        if self.extra is not None:
            callback(self.extra)


def _all_names(catalog):
    nodes = []
    catalog.catalog_root.visit(nodes.append)
    result = set()
    for node in nodes:
        name = getattr(node, "name", None)
        if isinstance(name, str) and name:
            result.add(name)
    return result


def _factory():
    serial = iter(range(1, 10000))
    return lambda _sid, length, _unavailable: "zz" + str(next(serial)).zfill(length - 2)


class T141SemanticNameReuseTests(unittest.TestCase):
    def _index(self, categories=("all",)):
        source = from_filelist(filelist=T108 / "design.f", top="top")
        return build_rename_index(build_source_catalog(source), categories=categories)

    def test_mapping_reuses_names_and_factory_receives_exact_immutable_snapshots(self):
        rows = []
        for top, scoped in ((None, False), ("t125_top", False), ("t125_top", True)):
            with self.subTest(top=top, scoped=scoped):
                source = from_filelist(filelist=T125 / "design.f", top=top,
                    rewrite_roots=(T125 / "owned",) if scoped else ())
                raw = build_source_catalog(source)
                counted = _RootView(raw.catalog_root)
                catalog = replace(raw, catalog_root=counted,
                    top_root=counted if raw.top_root is raw.catalog_root else raw.top_root)
                names = _all_names(catalog)
                counted.visits = 0
                index = build_rename_index(catalog, categories=("signals",))
                self.assertEqual(counted.visits, 1)
                expected = names | {symbol.name for symbol in index.symbols}
                captured = []
                generated = []
                plain_factory = _factory()

                def factory(sid, length, unavailable):
                    self.assertIs(type(unavailable), frozenset)
                    self.assertEqual(unavailable, expected | set(generated))
                    captured.append(unavailable)
                    result = plain_factory(sid, length, unavailable)
                    generated.append(result)
                    return result

                before = counted.visits
                with patch.object(mapping_module, "_semantic_names", wraps=mapping_module._semantic_names) as legacy:
                    mapping = build_mapping_vnext(index, name_length=20, name_factory=factory)
                self.assertEqual(counted.visits - before, 0)
                self.assertEqual(legacy.call_count, 0)
                for position, snapshot in enumerate(captured):
                    self.assertEqual(snapshot, expected | set(generated[:position]))
                self.assertEqual(len(generated), sum(item.action == "rename" for item in mapping.records))
                rows.append({"top": top, "scoped": scoped, "extra_mapping_visits": counted.visits - before})
        print("T141_REUSE_JSON=" + json.dumps(rows, sort_keys=True))

    def test_deterministic_complete_mapping_report_is_unchanged(self):
        mapping = build_mapping_vnext(self._index(), name_length=20, name_factory=_factory())
        report = mapping.to_report()
        digest = hashlib.sha256(json.dumps(report, sort_keys=True, separators=(",", ":"),
                                          ensure_ascii=False).encode()).hexdigest()
        self.assertEqual(digest, "e4bea7aee2502f833053859bf9b34a21adf81a17530aaf5faa18f9ae3b2831da")
        self.assertEqual(report["summary"], {"rename": 34, "preserve": 6, "unsupported": 2, "total": 42})
        print("T141_MAPPING_DIGEST=" + digest)

    def test_unselected_semantic_name_and_previous_generated_name_collide(self):
        index = self._index(categories=("signals",))
        unselected = _all_names(index.source_catalog) - {item.name for item in index.symbols}
        name = next(name for name in sorted(unselected) if len(name) >= 4 and is_plain_identifier(name))
        with self.assertRaises(MappingVNextError) as existing:
            build_mapping_vnext(index, name_length=len(name), name_factory=lambda *_args: name)
        self.assertEqual(existing.exception.code, "MAPPING_NAME_COLLISION")
        with self.assertRaises(MappingVNextError) as generated:
            build_mapping_vnext(index, name_length=20, name_factory=lambda *_args: "zz000000000000000001")
        self.assertEqual(generated.exception.code, "MAPPING_NAME_COLLISION")

    def test_replaced_catalog_does_not_reuse_old_names(self):
        index = self._index()
        extra = "new_collision"
        root = _RootView(index.source_catalog.catalog_root, extra=SimpleNamespace(name=extra))
        current = replace(index.source_catalog, catalog_root=root)
        changed = replace(index, source_catalog=current)
        with self.assertRaises(MappingVNextError) as raised:
            build_mapping_vnext(changed, name_length=len(extra), name_factory=lambda *_args: extra)
        self.assertEqual(raised.exception.code, "MAPPING_NAME_COLLISION")
        self.assertEqual(root.visits, 1)

    def test_separate_indexes_never_share_semantic_names(self):
        base = self._index()
        for name in ("first_reserved", "second_reserved"):
            with self.subTest(name=name):
                root = _RootView(base.source_catalog.catalog_root, extra=SimpleNamespace(name=name))
                catalog = replace(base.source_catalog, catalog_root=root)
                index = build_rename_index(catalog, categories=("signals",))
                with self.assertRaises(MappingVNextError) as raised:
                    build_mapping_vnext(index, name_length=len(name), name_factory=lambda *_args: name)
                self.assertEqual(raised.exception.code, "MAPPING_NAME_COLLISION")

    def test_replaced_index_uses_existing_validation_and_root_error_order(self):
        index = self._index()
        root = _RootView(index.source_catalog.catalog_root, fail=True)
        changed = replace(index, source_catalog=replace(index.source_catalog, catalog_root=root))
        with self.assertRaises(MappingVNextError) as raised:
            build_mapping_vnext(changed, name_length=20, name_factory=_factory())
        self.assertEqual(raised.exception.code, "MAPPING_SOURCE_INVALID")
        self.assertEqual(root.visits, 1)
        symbol = index.symbols[0]
        bad_symbol = replace(symbol, occurrences=(SymbolOccurrence(symbol.declaration, "duplicate"),))
        invalid = replace(changed, symbols=(bad_symbol,), decisions=(index.decisions[0],))
        with self.assertRaises(MappingVNextError) as overlap:
            build_mapping_vnext(invalid, name_length=20, name_factory=_factory())
        self.assertEqual(overlap.exception.code, "MAPPING_RANGE_OVERLAP")
        self.assertEqual(root.visits, 1)  # Range checks still precede name collection.

    def test_index_replace_drops_live_only_reuse_even_without_catalog_change(self):
        index = self._index()
        with patch.object(mapping_module, "_semantic_names", wraps=mapping_module._semantic_names) as legacy:
            build_mapping_vnext(replace(index), name_length=20, name_factory=_factory())
        self.assertEqual(legacy.call_count, 1)

    def test_incomplete_private_identity_is_never_treated_as_a_match(self):
        for width in (0, 1, 3, 5):
            with self.subTest(width=width):
                index = self._index()
                catalog = index.source_catalog
                identity = (catalog, catalog.catalog_compilation, catalog.catalog_root,
                            catalog.catalog_source_manager, object())[:width]
                # Fault injection: no persisted schema can supply these private fields.
                object.__setattr__(index, "_live_semantic_name_identity", identity)
                with patch.object(mapping_module, "_semantic_names", wraps=mapping_module._semantic_names) as legacy:
                    build_mapping_vnext(index, name_length=20, name_factory=_factory())
                self.assertEqual(legacy.call_count, 1)

    def test_name_attribute_failure_is_not_silently_skipped_or_moved_before_mapping_validation(self):
        class BadName:
            @property
            def name(self):
                raise RuntimeError("name intentionally unavailable")

        base = self._index()
        root = _RootView(base.source_catalog.catalog_root, extra=BadName())
        index = build_rename_index(replace(base.source_catalog, catalog_root=root), categories=("signals",))
        with self.assertRaisesRegex(RuntimeError, "name intentionally unavailable"):
            build_mapping_vnext(index, name_length=20, name_factory=_factory())
        symbol = index.symbols[0]
        invalid = replace(index, symbols=(replace(symbol, occurrences=(SymbolOccurrence(symbol.declaration, "duplicate"),)),),
                          decisions=(index.decisions[0],))
        with self.assertRaises(MappingVNextError) as overlap:
            build_mapping_vnext(invalid, name_length=20, name_factory=_factory())
        self.assertEqual(overlap.exception.code, "MAPPING_RANGE_OVERLAP")


if __name__ == "__main__":
    unittest.main()
