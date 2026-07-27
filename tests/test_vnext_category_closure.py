from __future__ import annotations

from collections import Counter
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from rtl_obfuscator.category_registry_vnext import (
    ALIASES,
    CANONICAL_CATEGORIES,
    DEFAULT_CATEGORIES,
    MODULE_ABI_CATEGORIES,
    normalize_abi_categories,
    normalize_categories,
)
from rtl_obfuscator import orchestration_vnext
from rtl_obfuscator.source_catalog import build_source_catalog
from rtl_obfuscator.source_set import (
    SourceSetError,
    from_filelist,
    from_project_root,
    from_single_file,
)
from rtl_obfuscator.mapping_vnext import build_mapping_vnext
from rtl_obfuscator.rewrite_policy import build_rewrite_policy
from rtl_obfuscator.symbol_graph import (
    SourceSymbol,
    SymbolGraphError,
    _collect_extended_symbols,
    build_symbol_graph,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "t033_impact_category"


class VNextCategoryClosureTests(unittest.TestCase):
    @staticmethod
    def _deterministic_factory(symbol_id: str, name_length: int, unavailable: frozenset[str]) -> str:
        digest = hashlib.sha256(symbol_id.encode("utf-8")).hexdigest()
        candidate = ("v" + digest)[:name_length]
        if candidate in unavailable:
            raise AssertionError("test factory collision")
        return candidate

    def test_registry_order_default_all_aliases_and_abi_contract(self):
        self.assertEqual(len(CANONICAL_CATEGORIES), 19)
        self.assertEqual(normalize_categories(None), DEFAULT_CATEGORIES)
        self.assertEqual(normalize_categories(["modports", "signals", "signals"]), ("signals", "modports"))
        self.assertEqual(normalize_categories(["struct", "interface"]), (
            "struct_types", "struct_fields", "interfaces", "interface_instances",
            "interface_ports", "modports",
        ))
        self.assertEqual(normalize_categories(["all"]), DEFAULT_CATEGORIES)
        self.assertEqual(normalize_abi_categories(["modports", "parameters", "ports", "parameters"]), (
            "parameters", "ports", "modports",
        ))
        self.assertEqual(set(ALIASES), {"struct", "interface"})
        with self.assertRaises(ValueError):
            normalize_categories(["unknown"])
        with self.assertRaises(ValueError):
            normalize_categories([""])
        with self.assertRaises(ValueError):
            normalize_abi_categories(["signals"])

    def _graph(self, *, origin: str):
        if origin == "project-root":
            source_set = from_project_root(project_root=FIXTURE, top="t033_top")
            return build_symbol_graph(build_source_catalog(source_set))
        with tempfile.TemporaryDirectory(prefix="t056-closure-") as temporary:
            filelist = Path(temporary) / "closure.f"
            filelist.write_text("bus_if.sv\nshared.sv\nchild.sv\ntop.sv\n", encoding="utf-8")
            source_set = from_filelist(filelist=filelist, source_root=FIXTURE, top="t033_top")
            return build_symbol_graph(build_source_catalog(source_set))

    def test_t033_graph_has_all_categories_and_portable_ranges(self):
        graph = self._graph(origin="project-root")
        self.assertEqual(set(graph.to_report()["categories"]), set(CANONICAL_CATEGORIES))
        self.assertEqual(set(symbol.category for symbol in graph.symbols), set(CANONICAL_CATEGORIES))
        self.assertNotIn("decoy.sv", graph.source_catalog.source_set.top_closure_files)
        ranges = []
        for symbol in graph.symbols:
            self.assertTrue(symbol.owner_module)
            self.assertEqual(symbol.owner_module, symbol.semantic_owner)
            for source_range in (symbol.declaration,) + tuple(
                occurrence.source_range for occurrence in symbol.occurrences
            ):
                source = (FIXTURE / source_range.file).read_bytes()
                self.assertEqual(source[source_range.start:source_range.end], symbol.name.encode())
                ranges.append((source_range.file, source_range.start, source_range.end))
        self.assertEqual(len(ranges), len(set(ranges)))
        for file in sorted({item[0] for item in ranges}):
            ordered = sorted(item for item in ranges if item[0] == file)
            self.assertTrue(all(left[2] <= right[1] for left, right in zip(ordered, ordered[1:])))

    def test_project_root_and_equivalent_closure_have_same_graph_and_mapping_identity(self):
        project_graph = self._graph(origin="project-root")
        filelist_graph = self._graph(origin="filelist")

        def without_origin(report: dict[str, object]) -> dict[str, object]:
            def normalize(value: object) -> object:
                if isinstance(value, dict):
                    return {
                        key: normalize(item)
                        for key, item in value.items()
                        if key != "origin"
                    }
                if isinstance(value, list):
                    return [normalize(item) for item in value]
                return value

            return normalize(json.loads(json.dumps(report)))

        self.assertEqual(without_origin(project_graph.to_report()), without_origin(filelist_graph.to_report()))
        self.assertEqual(
            Counter(symbol.category for symbol in project_graph.symbols),
            Counter(symbol.category for symbol in filelist_graph.symbols),
        )
        project_mapping = build_mapping_vnext(
            build_rewrite_policy(
                project_graph,
                categories=CANONICAL_CATEGORIES,
                abi_categories=MODULE_ABI_CATEGORIES,
            ),
            name_length=16,
            name_factory=self._deterministic_factory,
        )
        filelist_mapping = build_mapping_vnext(
            build_rewrite_policy(
                filelist_graph,
                categories=CANONICAL_CATEGORIES,
                abi_categories=MODULE_ABI_CATEGORIES,
            ),
            name_length=16,
            name_factory=self._deterministic_factory,
        )
        self.assertEqual(
            without_origin(project_mapping.to_report()),
            without_origin(filelist_mapping.to_report()),
        )

    def test_sample11_default_thirteen_actual_gate_compile_restore(self):
        sample = ROOT / "rtl_samples" / "11_supported_obfuscation.sv"
        source_set = from_single_file(
            source_file=sample,
            source_root=ROOT / "rtl_samples",
        )
        with tempfile.TemporaryDirectory(prefix="t056-sample11-gate-") as temporary:
            root = Path(temporary)
            result = orchestration_vnext.run_vnext(
                source_set,
                categories=DEFAULT_CATEGORIES,
                abi_categories=(),
                name_factory=self._deterministic_factory,
                name_length=16,
                gate_dir=root / "gate",
                restore_dir=root / "restore",
            )
            renamed_categories = {
                record.category
                for record in result.mapping_vnext.records
                if record.action == "rename"
            }
            self.assertEqual(renamed_categories, set(DEFAULT_CATEGORIES))
            self.assertTrue(result.to_report()["summary"]["strict_compile_passed"])
            self.assertTrue(result.to_report()["summary"]["restored_byte_identical"])
            for record in result.mapping_vnext.records:
                if record.category in {"typedefs", "struct_types", "struct_fields", "union_fields"}:
                    self.assertEqual(record.abi, "internal")
                    self.assertEqual(record.action, "rename")
            for name, provenance in (
                ("apply_mask", "semantic_call"),
                ("select_value", "semantic_call"),
            ):
                record = next(
                    record
                    for record in result.mapping_vnext.records
                    if record.original_name == name
                )
                self.assertTrue(
                    any(item.provenance == provenance for item in record.occurrences),
                    (name, provenance),
                )

    def test_full_nineteen_category_project_gate_compile_restore_and_negative_selection(self):
        source_set = from_project_root(project_root=FIXTURE, top="t033_top")
        with tempfile.TemporaryDirectory(prefix="t056-category-gate-") as temporary:
            root = Path(temporary)
            result = orchestration_vnext.run_vnext(
                source_set,
                categories=CANONICAL_CATEGORIES,
                abi_categories=MODULE_ABI_CATEGORIES,
                name_factory=self._deterministic_factory,
                name_length=16,
                gate_dir=root / "gate",
                restore_dir=root / "restore",
            )
            report = result.to_report()
            self.assertEqual(report["mapping"]["selection"]["selected_categories"], list(CANONICAL_CATEGORIES))
            self.assertEqual(report["mapping"]["selection"]["abi_categories"], list(MODULE_ABI_CATEGORIES))
            action_reasons = {
                (record.action, record.reason)
                for record in result.mapping_vnext.records
            }
            self.assertEqual(action_reasons, {("rename", None), ("preserve", "selected_top_boundary")})
            self.assertTrue(
                all(
                    record.action == "preserve"
                    and record.reason == "selected_top_boundary"
                    for record in result.mapping_vnext.records
                    if record.abi == "top_boundary"
                )
            )
            self.assertTrue(report["summary"]["strict_compile_passed"])
            self.assertTrue(report["summary"]["restored_byte_identical"])
            self.assertEqual(report["mapping_execution"]["restored_manifest"], report["mapping_execution"]["input_manifest"])
            renamed = {
                (record.category, record.original_name)
                for record in result.mapping_vnext.records
                if record.action == "rename"
            }
            self.assertIn(("modules", "t033_child"), renamed)
            self.assertIn(("ports", "data"), renamed)
            self.assertIn(("interfaces", "t033_bus_if"), renamed)
            self.assertIn(("interface_ports", "bus"), renamed)
            self.assertIn(("modports", "sink"), renamed)
            self.assertIn(("struct_fields", "valid"), renamed)
            self.assertIn(("union_fields", "raw"), renamed)
            self.assertIn(("functions", "child_fn"), renamed)
            self.assertIn(("tasks", "child_task"), renamed)
            self.assertTrue(
                all(
                    record.action == "preserve"
                    for record in result.mapping_vnext.records
                    if record.owner_module == "module:top.sv:7:15"
                    and record.abi == "top_boundary"
                )
            )

    def test_semantic_collection_handles_plain_module_without_keyword_activation(self):
        with tempfile.TemporaryDirectory(prefix="t056-semantic-") as temporary:
            root = Path(temporary)
            source = root / "plain.sv"
            source.write_text(
                "module plain(input logic data, output logic q);\n"
                "  logic internal;\n"
                "  assign internal = data;\n"
                "  assign q = internal;\nendmodule\n",
                encoding="utf-8",
            )
            (root / "design.f").write_text("plain.sv\n", encoding="utf-8")
            graph = build_symbol_graph(
                build_source_catalog(
                    from_filelist(
                        filelist=(root / "design.f"),
                        source_root=root,
                    )
                )
            )
            categories = {symbol.category for symbol in graph.symbols}
            self.assertIn("modules", categories)
            self.assertIn("ports", categories)
            self.assertIn("signals", categories)

    def test_semantic_range_conflicts_fail_closed(self):
        catalog = build_source_catalog(
            from_project_root(project_root=FIXTURE, top="t033_top")
        )
        module = next(item for item in catalog.modules if item.name == "t033_top")
        fake = SourceSymbol(
            symbol_id="symbol:test:conflict",
            category="signals",
            name="t033_top",
            declaration=module.declaration,
            owner_module=module.owner_id,
            semantic_owner=module.owner_id,
            occurrences=(),
            impact="local",
            abi="internal",
            support="eligible",
            reason=None,
        )
        with self.assertRaises(SymbolGraphError) as raised:
            _collect_extended_symbols(catalog, [fake])
        self.assertEqual(raised.exception.code, "SYMBOL_GRAPH_RANGE_CONFLICT")

        partial = replace(
            fake,
            declaration=type(module.declaration)(
                module.declaration.file,
                module.declaration.start,
                module.declaration.end + 1,
            ),
        )
        with self.assertRaises(SymbolGraphError) as raised:
            _collect_extended_symbols(catalog, [partial])
        self.assertEqual(raised.exception.code, "SYMBOL_GRAPH_RANGE_CONFLICT")

    def test_fail_closed_top_and_source_boundaries(self):
        with self.assertRaises(SourceSetError) as raised:
            from_project_root(project_root=FIXTURE, top="missing_top")
        self.assertEqual(raised.exception.code, "SOURCESET_TOP_NOT_FOUND")
        with self.assertRaises(SourceSetError):
            from_filelist(filelist=FIXTURE / "design.f", source_root=FIXTURE / "missing")


if __name__ == "__main__":
    unittest.main()
