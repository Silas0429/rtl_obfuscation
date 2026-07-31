from __future__ import annotations

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

import pyslang

from rtl_obfuscator import orchestration_vnext
from rtl_obfuscator.category_registry_vnext import CANONICAL_CATEGORIES, MODULE_ABI_CATEGORIES
from rtl_obfuscator import source_catalog as source_catalog_module
from rtl_obfuscator.source_catalog import build_source_catalog
from rtl_obfuscator.source_set import from_filelist
from rtl_obfuscator.symbol_graph import build_symbol_graph


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "t071_type_parameter_defparam"


class T071TypeParameterDefParamTests(unittest.TestCase):
    @staticmethod
    def _factory(symbol_id: str, name_length: int, unavailable: frozenset[str]) -> str:
        candidate = ("v" + hashlib.sha256(symbol_id.encode("utf-8")).hexdigest())[:name_length]
        if candidate in unavailable:
            raise AssertionError("test factory collision")
        return candidate

    @staticmethod
    def _source_set(root: Path = FIXTURE_ROOT):
        return from_filelist(
            filelist=root / "design.f",
            source_root=root,
            defines=["T071_TYPED_VIEW"],
            top="t071_top",
        )

    @classmethod
    def _catalog_graph(cls):
        source_set = cls._source_set()
        catalog = build_source_catalog(source_set)
        return source_set, catalog, build_symbol_graph(catalog)

    @staticmethod
    def _owner_id(catalog, name: str) -> str:
        return next(module.owner_id for module in catalog.modules if module.name == name)

    @staticmethod
    def _symbols_for_owner(graph, owner_id: str):
        return [symbol for symbol in graph.symbols if symbol.owner_module == owner_id]

    @staticmethod
    def _formal_command(gate_root: Path) -> list[str]:
        return [
            sys.executable,
            str(ROOT / "scripts" / "formal_equivalence.py"),
            "--gold-filelist",
            str(FIXTURE_ROOT / "design.f"),
            "--gold-root",
            str(FIXTURE_ROOT),
            "--gate-filelist",
            str(gate_root / "design.f"),
            "--gate-root",
            str(gate_root),
            "--top",
            "t071_top",
            "--seq",
            "5",
        ]

    @classmethod
    def _formal(
        cls, command_root: Path, gate_root: Path
    ) -> tuple[subprocess.CompletedProcess[str], list[str]]:
        command = cls._formal_command(gate_root)
        return subprocess.run(
            command,
            cwd=command_root,
            capture_output=True,
            text=True,
            check=False,
        ), command

    def test_catalog_top_overlay_and_graph_reuse(self):
        source_set, catalog, _ = self._catalog_graph()
        with mock.patch.object(
            source_catalog_module,
            "_compile_view",
            side_effect=AssertionError("T071 graph rebuilt semantic view"),
        ):
            graph = build_symbol_graph(catalog)
        self.assertEqual(source_set.defines, (("T071_TYPED_VIEW", "1"),))
        self.assertEqual(catalog.to_report()["compile"], {
            "catalog": {"parse_errors": 0, "semantic_errors": 0},
            "top_overlay": {"parse_errors": 0, "semantic_errors": 0},
        })
        self.assertIs(graph.source_catalog, catalog)
        self.assertEqual(tuple(source_set.compile_order), (
            "rtl/type_owner.sv",
            "rtl/defparam_target.sv",
            "rtl/defparam_owner.sv",
            "rtl/sibling.sv",
            "rtl/top.sv",
        ))

    def test_graph_oracle(self):
        _, _, graph = self._catalog_graph()
        self.assertEqual(graph.to_report()["range_audit"], {
            "symbols": 28,
            "declarations": 28,
            "occurrences": 40,
            "total_ranges": 68,
        })

    def test_type_parameter_record_and_owner_quarantine(self):
        _, catalog, graph = self._catalog_graph()
        owner_id = self._owner_id(catalog, "t071_type_owner")
        symbols = self._symbols_for_owner(graph, owner_id)
        self.assertEqual(len(symbols), 5)
        type_parameter = next(symbol for symbol in symbols if symbol.name == "DATA_T")
        self.assertEqual((type_parameter.category, type_parameter.impact, type_parameter.abi), (
            "parameters", "cross_module", "module_abi"
        ))
        self.assertEqual(type_parameter.declaration, type(type_parameter.declaration)(
            "rtl/type_owner.sv", 68, 74
        ))
        self.assertEqual(type_parameter.occurrences, ())
        self.assertEqual((type_parameter.support, type_parameter.reason), (
            "unsupported", "type_parameter_not_renamed"
        ))
        self.assertEqual(
            {
                (symbol.name, symbol.support, symbol.reason)
                for symbol in symbols
                if symbol.symbol_id != type_parameter.symbol_id
            },
            {
                ("t071_type_owner", "unsupported", "owner_contains_type_parameter"),
                ("data_i", "unsupported", "owner_contains_type_parameter"),
                ("data_o", "unsupported", "owner_contains_type_parameter"),
                ("type_hold", "unsupported", "owner_contains_type_parameter"),
            },
        )

    def test_defparam_target_identity_occurrence_and_owner_quarantine(self):
        _, catalog, graph = self._catalog_graph()
        nodes = []
        catalog.catalog_root.visit(nodes.append)
        defparam = next(
            node
            for node in nodes
            if getattr(node, "kind", None) == pyslang.ast.SymbolKind.DefParam
        )
        target = defparam.target
        self.assertEqual(target.kind, pyslang.ast.SymbolKind.Parameter)
        self.assertEqual(target.name, "WIDTH")
        self.assertEqual(target.declaringDefinition.name, "t071_defparam_target")

        width = next(symbol for symbol in graph.symbols if symbol.name == "WIDTH")
        self.assertEqual(width.declaration, type(width.declaration)(
            "rtl/defparam_target.sv", 49, 54
        ))
        self.assertEqual(
            [(item.source_range.file, item.source_range.start, item.source_range.end, item.provenance)
             for item in width.occurrences],
            [
                ("rtl/defparam_owner.sv", 244, 249, "defparam_binding"),
                ("rtl/defparam_target.sv", 191, 196, "semantic_expression"),
            ],
        )
        reference_owner = self._owner_id(catalog, "t071_defparam_owner")
        target_owner = self._owner_id(catalog, "t071_defparam_target")
        for owner_id in (reference_owner, target_owner):
            symbols = self._symbols_for_owner(graph, owner_id)
            self.assertEqual(len(symbols), 5)
            self.assertTrue(all(
                symbol.support == "unsupported"
                and symbol.reason == "defparam_binding_not_renamed"
                for symbol in symbols
            ))

    def test_mapping_oracle_and_unaffected_edits(self):
        source_set = self._source_set()
        with tempfile.TemporaryDirectory(prefix="t071-mapping-") as temporary:
            result = orchestration_vnext.run_vnext(
                source_set,
                categories=CANONICAL_CATEGORIES,
                abi_categories=MODULE_ABI_CATEGORIES,
                name_factory=self._factory,
                name_length=16,
                gate_dir=Path(temporary) / "gate",
                restore_dir=Path(temporary) / "restore",
            )
        summary = result.mapping_vnext.to_report()["summary"]
        self.assertEqual(summary, {"rename": 10, "preserve": 3, "unsupported": 15, "total": 28})
        execution = result.mapping_execution.rewrite_execution
        records_by_id = {
            record.symbol_id: record for record in result.mapping_vnext.records
        }
        self.assertEqual(len(records_by_id), 28)
        protected_reasons = {
            "type_parameter_not_renamed",
            "owner_contains_type_parameter",
            "defparam_binding_not_renamed",
        }
        protected_symbol_ids = {
            record.symbol_id
            for record in records_by_id.values()
            if record.reason in protected_reasons
        }
        protected_owner_ids = {
            record.owner_module
            for record in records_by_id.values()
            if record.reason in protected_reasons
        }
        graph = result.mapping_vnext.rewrite_policy.symbol_graph
        sibling_owner = self._owner_id(graph.source_catalog, "t071_sibling")
        top_owner = self._owner_id(graph.source_catalog, "t071_top")
        actual_edits = execution.edits
        self.assertEqual(len(actual_edits), 23)
        self.assertTrue(all(edit.symbol_id in records_by_id for edit in actual_edits))
        self.assertEqual(
            sum(
                1
                for edit in actual_edits
                if edit.symbol_id in protected_symbol_ids
                or records_by_id[edit.symbol_id].owner_module in protected_owner_ids
            ),
            0,
        )
        self.assertEqual(
            sum(
                1
                for edit in actual_edits
                if records_by_id[edit.symbol_id].owner_module == sibling_owner
            ),
            11,
        )
        self.assertEqual(
            sum(
                1
                for edit in actual_edits
                if records_by_id[edit.symbol_id].owner_module == top_owner
            ),
            12,
        )

    def test_actual_gate_strict_compile_and_restore(self):
        source_set = self._source_set()
        with tempfile.TemporaryDirectory(prefix="t071-gate-") as temporary:
            root = Path(temporary)
            result = orchestration_vnext.run_vnext(
                source_set,
                categories=CANONICAL_CATEGORIES,
                abi_categories=MODULE_ABI_CATEGORIES,
                name_factory=self._factory,
                name_length=16,
                gate_dir=root / "gate",
                restore_dir=root / "restore",
            )
            report = result.to_report()
            self.assertTrue(report["summary"]["strict_compile_passed"])
            self.assertTrue(report["summary"]["restored_byte_identical"])
            self.assertEqual(len(report["mapping_execution"]["gate_manifest"]), 5)
            self.assertEqual(len(report["mapping_execution"]["restored_manifest"]), 5)
            self.assertEqual(
                report["mapping_execution"]["input_manifest"],
                report["mapping_execution"]["restored_manifest"],
            )
            gold = {
                file: (FIXTURE_ROOT / file).read_bytes()
                for file in source_set.ordered_source_files
            }
            self.assertEqual(
                {
                    file: (root / "restore" / file).read_bytes()
                    for file in gold
                },
                gold,
            )

    def test_actual_renamed_gate_formal_positive(self):
        source_set = self._source_set()
        with tempfile.TemporaryDirectory(prefix="t071-formal-positive-") as temporary:
            root = Path(temporary)
            orchestration_vnext.run_vnext(
                source_set,
                categories=CANONICAL_CATEGORIES,
                abi_categories=MODULE_ABI_CATEGORIES,
                name_factory=self._factory,
                name_length=16,
                gate_dir=root / "gate",
                restore_dir=root / "restore",
            )
            formal, command = self._formal(root, root / "gate")
            print(f"T071_FORMAL_COMMAND {shlex.join(command)}")
            print(f"T071_FORMAL_EXIT {formal.returncode}")
            print(f"T071_FORMAL_JSON {formal.stdout.strip()}")
        self.assertEqual(formal.returncode, 0, formal.stderr)
        self.assertEqual(json.loads(formal.stdout)["formal_equivalence"], "pass")

    def test_fixed_function_negative_gate_strict_compile_and_formal_failure(self):
        source_set = self._source_set()
        with tempfile.TemporaryDirectory(prefix="t071-formal-negative-") as temporary:
            root = Path(temporary)
            orchestration_vnext.run_vnext(
                source_set,
                categories=CANONICAL_CATEGORIES,
                abi_categories=MODULE_ABI_CATEGORIES,
                name_factory=self._factory,
                name_length=16,
                gate_dir=root / "gate",
                restore_dir=root / "restore",
            )
            negative = root / "negative"
            shutil.copytree(root / "gate", negative)
            top = negative / "rtl" / "top.sv"
            top_source = top.read_bytes()
            marker = b"assign data_o = "
            self.assertEqual(top_source.count(marker), 1)
            top.write_bytes(top_source.replace(marker, b"assign data_o = ~", 1))
            negative_set = self._source_set(negative)
            negative_catalog = build_source_catalog(negative_set)
            self.assertEqual(negative_catalog.to_report()["compile"], {
                "catalog": {"parse_errors": 0, "semantic_errors": 0},
                "top_overlay": {"parse_errors": 0, "semantic_errors": 0},
            })
            formal, command = self._formal(root, negative)
            print(f"T071_FORMAL_NEGATIVE_COMMAND {shlex.join(command)}")
            print(f"T071_FORMAL_NEGATIVE_EXIT {formal.returncode}")
        self.assertNotEqual(formal.returncode, 0)
        combined = formal.stdout + formal.stderr
        self.assertIn("unproven", combined)
        self.assertIn("equiv_status -assert", combined)


if __name__ == "__main__":
    unittest.main()
