from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from rtl_obfuscator.category_registry_vnext import (
    CANONICAL_CATEGORIES,
    MODULE_ABI_CATEGORIES,
)
from rtl_obfuscator.mapping_vnext import build_mapping_vnext
from rtl_obfuscator.rewrite_policy import build_rewrite_policy
from rtl_obfuscator.rewrite_vnext import restore_gate_vnext, write_gate_vnext
from rtl_obfuscator.source_catalog import SourceCatalogError, build_source_catalog
from rtl_obfuscator.source_set import SourceSetError, from_filelist
from rtl_obfuscator.symbol_graph import build_symbol_graph


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "t076_module_end_label"
T075_ROOT = ROOT / "tests" / "fixtures" / "t075_owner_occurrence_firewall"


def _deterministic_factory(
    symbol_id: str, name_length: int, unavailable: frozenset[str]
) -> str:
    del unavailable
    return "n" + hashlib.sha256(symbol_id.encode("utf-8")).hexdigest()[: name_length - 1]


class T076ModuleEndLabelTests(unittest.TestCase):
    @staticmethod
    def _source_set(root: Path = FIXTURE_ROOT):
        return from_filelist(
            filelist=root / "design.f",
            source_root=root,
            top="t076_top",
        )

    @classmethod
    def _catalog_graph(cls):
        source_set = cls._source_set()
        catalog = build_source_catalog(source_set)
        return source_set, catalog, build_symbol_graph(catalog)

    @classmethod
    def _mapping(cls):
        _source_set, _catalog, graph = cls._catalog_graph()
        policy = build_rewrite_policy(
            graph,
            categories=CANONICAL_CATEGORIES,
            abi_categories=MODULE_ABI_CATEGORIES,
        )
        return build_mapping_vnext(
            policy,
            name_length=16,
            name_factory=_deterministic_factory,
        )

    @staticmethod
    def _owner_ids(catalog):
        return {module.name: module.owner_id for module in catalog.modules}

    @staticmethod
    def _physical_files(source_set):
        return tuple(
            dict.fromkeys(
                (*source_set.ordered_source_files, *source_set.included_files)
            )
        )

    @staticmethod
    def _module_symbol(graph, owner: str, name: str):
        return next(
            symbol
            for symbol in graph.symbols
            if symbol.owner_module == owner
            and symbol.category == "modules"
            and symbol.name == name
        )

    @staticmethod
    def _formal(gate_dir: Path):
        command = [
            sys.executable,
            "scripts/formal_equivalence.py",
            "--gold-filelist",
            "tests/fixtures/t076_module_end_label/design.f",
            "--gold-root",
            "tests/fixtures/t076_module_end_label",
            "--gate-filelist",
            str(gate_dir / "design.f"),
            "--gate-root",
            str(gate_dir),
            "--top",
            "t076_top",
            "--seq",
            "5",
        ]
        return subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=180,
        ), command

    def test_catalog_reuses_semantic_view_and_invalid_labels_fail_closed(self):
        source_set = self._source_set()
        catalog = build_source_catalog(source_set)
        self.assertEqual(
            catalog.to_report()["compile"],
            {
                "catalog": {"parse_errors": 0, "semantic_errors": 0},
                "top_overlay": {"parse_errors": 0, "semantic_errors": 0},
            },
        )
        with mock.patch(
            "rtl_obfuscator.source_catalog._compile_view",
            side_effect=AssertionError("T076 graph rebuilt a semantic view"),
        ):
            graph = build_symbol_graph(catalog)
        self.assertIs(graph.source_catalog, catalog)
        self.assertEqual(
            tuple(source_set.compile_order),
            ("rtl/labeled_child.sv", "rtl/plain_sibling.sv", "rtl/top.sv"),
        )

        with self.assertRaises(SourceSetError) as public_error:
            from_filelist(
                filelist=FIXTURE_ROOT / "invalid_label.f",
                source_root=FIXTURE_ROOT,
                top="t076_bad_label",
            )
        self.assertEqual(public_error.exception.code, "SOURCESET_DISCOVERY_FAILED")
        self.assertIn("parse errors", str(public_error.exception))

        isolated_invalid = replace(
            source_set,
            ordered_source_files=("rtl/invalid_label.sv",),
            included_files=(),
            top="t076_bad_label",
            top_closure_files=("rtl/invalid_label.sv",),
            compile_order=("rtl/invalid_label.sv",),
        )
        with self.assertRaises(SourceCatalogError) as catalog_error:
            build_source_catalog(isolated_invalid)
        self.assertEqual(catalog_error.exception.code, "CATALOG_PARSE_FAILED")
        self.assertIn("parse errors", str(catalog_error.exception))

    def test_module_records_close_semantic_occurrences_without_duplicates(self):
        _source_set, catalog, graph = self._catalog_graph()
        owners = self._owner_ids(catalog)
        child = self._module_symbol(
            graph, owners["t076_labeled_child"], "t076_labeled_child"
        )
        self.assertEqual(
            [occurrence.provenance for occurrence in child.occurrences],
            ["semantic_module_end_label", "semantic_hierarchy"],
        )
        child_by_provenance = {
            occurrence.provenance: occurrence for occurrence in child.occurrences
        }
        self.assertEqual(len(child_by_provenance), 2)
        label = child_by_provenance["semantic_module_end_label"].source_range
        self.assertEqual(
            (FIXTURE_ROOT / label.file).read_bytes()[label.start : label.end],
            b"t076_labeled_child",
        )

        top = self._module_symbol(graph, owners["t076_top"], "t076_top")
        self.assertEqual((top.support, top.reason), ("preserved", "selected_top_boundary"))
        self.assertEqual(
            [occurrence.provenance for occurrence in top.occurrences],
            ["semantic_module_end_label"],
        )
        top_label = top.occurrences[0].source_range
        self.assertEqual(
            (FIXTURE_ROOT / top_label.file).read_bytes()[top_label.start : top_label.end],
            b"t076_top",
        )

        sibling = self._module_symbol(
            graph, owners["t076_plain_sibling"], "t076_plain_sibling"
        )
        self.assertEqual(
            [occurrence.provenance for occurrence in sibling.occurrences],
            ["semantic_hierarchy"],
        )

        all_ranges = []
        for symbol in graph.symbols:
            all_ranges.extend(
                (
                    symbol.declaration,
                    *(occurrence.source_range for occurrence in symbol.occurrences),
                )
            )
        keys = [(item.file, item.start, item.end) for item in all_ranges]
        self.assertEqual(len(keys), len(set(keys)))
        for first, second in zip(
            sorted(all_ranges, key=lambda item: (item.file, item.start, item.end)),
            sorted(all_ranges, key=lambda item: (item.file, item.start, item.end))[1:],
        ):
            if first.file == second.file:
                self.assertLessEqual(first.end, second.start)

    def test_mapping_and_actual_gate_edit_the_complete_child_module_symbol(self):
        mapping = self._mapping()
        graph = mapping.rewrite_policy.symbol_graph
        catalog = graph.source_catalog
        owners = self._owner_ids(catalog)
        symbols = {symbol.symbol_id: symbol for symbol in graph.symbols}
        records = {record.symbol_id: record for record in mapping.records}
        self.assertEqual(set(symbols), set(records))
        for symbol_id, symbol in symbols.items():
            self.assertEqual(records[symbol_id].declaration, symbol.declaration)
            self.assertEqual(records[symbol_id].occurrences, symbol.occurrences)

        child = self._module_symbol(
            graph, owners["t076_labeled_child"], "t076_labeled_child"
        )
        child_record = records[child.symbol_id]
        self.assertEqual(child_record.action, "rename")
        self.assertIsNotNone(child_record.renamed_name)
        expected_child_ranges = {
            child.declaration,
            *(occurrence.source_range for occurrence in child.occurrences),
        }
        self.assertEqual(len(expected_child_ranges), 3)

        top = self._module_symbol(graph, owners["t076_top"], "t076_top")
        self.assertEqual(
            (records[top.symbol_id].action, records[top.symbol_id].reason),
            ("preserve", "selected_top_boundary"),
        )

        with tempfile.TemporaryDirectory(prefix="t076-edits-") as temporary:
            gate_dir = Path(temporary) / "gate"
            execution = write_gate_vnext(mapping, output_dir=gate_dir)
            child_edits = [
                edit for edit in execution.edits if edit.symbol_id == child.symbol_id
            ]
            self.assertEqual(len(child_edits), 3)
            self.assertEqual(
                {edit.source_range for edit in child_edits}, expected_child_ranges
            )
            self.assertTrue(all(
                edit.original_name == "t076_labeled_child"
                and edit.renamed_name == child_record.renamed_name
                for edit in child_edits
            ))
            for edit in child_edits:
                gate_bytes = (gate_dir / edit.gate_range.file).read_bytes()
                self.assertEqual(
                    gate_bytes[edit.gate_range.start : edit.gate_range.end],
                    child_record.renamed_name.encode("utf-8"),
                )
            self.assertNotIn(
                b"endmodule : t076_labeled_child",
                (gate_dir / "rtl/labeled_child.sv").read_bytes(),
            )
            self.assertFalse(any(
                edit.symbol_id == top.symbol_id for edit in execution.edits
            ))
            top_gate = (gate_dir / "rtl/top.sv").read_bytes()
            self.assertEqual(top_gate.count(b"module t076_top"), 1)
            self.assertEqual(top_gate.count(b"endmodule : t076_top"), 1)

            edited_owners = {
                symbols[edit.symbol_id].owner_module for edit in execution.edits
            }
            self.assertIn(owners["t076_labeled_child"], edited_owners)
            self.assertIn(owners["t076_plain_sibling"], edited_owners)
            self.assertIn(owners["t076_top"], edited_owners)

    def test_actual_gate_strict_compile_and_restore_are_byte_identical(self):
        mapping = self._mapping()
        source_set = mapping.rewrite_policy.symbol_graph.source_catalog.source_set
        physical_files = self._physical_files(source_set)
        self.assertEqual(len(physical_files), 3)
        gold = {file: (FIXTURE_ROOT / file).read_bytes() for file in physical_files}
        with tempfile.TemporaryDirectory(prefix="t076-gate-") as temporary:
            root = Path(temporary)
            gate_dir = root / "gate"
            restore_dir = root / "restore"
            execution = write_gate_vnext(mapping, output_dir=gate_dir)
            self.assertEqual(
                (
                    execution.compile_evidence.catalog_parse_errors,
                    execution.compile_evidence.catalog_semantic_errors,
                    execution.compile_evidence.top_overlay_parse_errors,
                    execution.compile_evidence.top_overlay_semantic_errors,
                ),
                (0, 0, 0, 0),
            )
            restored = restore_gate_vnext(
                execution,
                gate_dir=gate_dir,
                output_dir=restore_dir,
            )
            self.assertTrue(restored.to_report()["summary"]["byte_identical"])
            self.assertEqual(
                {file: (restore_dir / file).read_bytes() for file in physical_files},
                gold,
            )

    def test_actual_renamed_gate_formal_positive(self):
        mapping = self._mapping()
        with tempfile.TemporaryDirectory(prefix="t076-formal-positive-") as temporary:
            gate_dir = Path(temporary) / "gate"
            execution = write_gate_vnext(mapping, output_dir=gate_dir)
            self.assertTrue(execution.edits)
            result, command = self._formal(gate_dir)
            print(f"T076_FORMAL_GATE {gate_dir}")
            print(f"T076_FORMAL_COMMAND {shlex.join(command)}")
            print(f"T076_FORMAL_EXIT {result.returncode}")
            print(f"T076_FORMAL_JSON {result.stdout.strip()}")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            payload = json.loads(result.stdout.strip().splitlines()[-1])
            self.assertEqual(payload["formal_equivalence"], "pass")
            self.assertEqual((payload["top"], payload["seq"]), ("t076_top", 5))

    def test_fixed_function_negative_strict_compiles_and_formal_fails(self):
        mapping = self._mapping()
        source_set = mapping.rewrite_policy.symbol_graph.source_catalog.source_set
        with tempfile.TemporaryDirectory(prefix="t076-formal-negative-") as temporary:
            root = Path(temporary)
            gate_dir = root / "gate"
            write_gate_vnext(mapping, output_dir=gate_dir)
            negative_dir = root / "negative"
            shutil.copytree(gate_dir, negative_dir)
            top = negative_dir / "rtl/top.sv"
            original = top.read_bytes()
            marker = b"assign data_o = "
            self.assertEqual(original.count(marker), 1)
            top.write_bytes(original.replace(marker, b"assign data_o = ~", 1))
            negative_set = replace(source_set, source_root=negative_dir.resolve())
            negative_compile = build_source_catalog(negative_set).to_report()["compile"]
            self.assertEqual(
                negative_compile,
                {
                    "catalog": {"parse_errors": 0, "semantic_errors": 0},
                    "top_overlay": {"parse_errors": 0, "semantic_errors": 0},
                },
            )
            result, command = self._formal(negative_dir)
            combined_output = result.stdout + result.stderr
            key_output = "\n".join(
                line
                for line in combined_output.splitlines()
                if "unproven" in line.lower()
                or "equiv_status -assert" in line.lower()
            )
            print(f"T076_FORMAL_NEGATIVE_GATE {negative_dir}")
            print(f"T076_FORMAL_NEGATIVE_COMMAND {shlex.join(command)}")
            print(
                "T076_FORMAL_NEGATIVE_COMPILE "
                + json.dumps(negative_compile, sort_keys=True)
            )
            print(f"T076_FORMAL_NEGATIVE_EXIT {result.returncode}")
            print(f"T076_FORMAL_NEGATIVE_OUTPUT {key_output}")
            combined = combined_output.lower()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unproven", combined)
            self.assertIn("equiv_status -assert", combined)

    def test_documentation_is_synchronized_and_t075_firewall_remains_active(self):
        table = (ROOT / "docs/systemverilog_renaming_table.md").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "一致加密子 module 声明、实例化引用和直接 closing label "
            "`endmodule : name`；top module 名称及 closing label 保留",
            table,
        )
        future = (ROOT / "docs/development/future_work.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("T075 已增加 **owner occurrence firewall**", future)
        self.assertIn(
            "整条跨 owner symbol 标为 unsupported，并禁止其\n  产生任何 rewrite edit",
            future,
        )
        self.assertIn("T076 已支持普通物理 module 的直接 closing label", future)
        for unresolved in (
            "expression-sized cast",
            "package-qualified enum/member",
            "conflicting quarantine reasons",
            "syntax-less implicit typedef conversion",
            "工程输入与验证",
        ):
            self.assertIn(unresolved, future)

        t075_source_set = from_filelist(
            filelist=T075_ROOT / "design.f",
            source_root=T075_ROOT,
            top="t075_top",
        )
        t075_graph = build_symbol_graph(build_source_catalog(t075_source_set))
        firewall = [
            symbol
            for symbol in t075_graph.symbols
            if symbol.reason == "occurrence_in_quarantined_owner"
        ]
        self.assertEqual(len(firewall), 3)
        self.assertTrue(all(symbol.support == "unsupported" for symbol in firewall))


if __name__ == "__main__":
    unittest.main()
