import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import rtl_obfuscator.orchestration_vnext as orchestration_vnext
import rtl_obfuscator.symbol_graph as symbol_graph
from rtl_obfuscator.source_catalog import build_source_catalog
from rtl_obfuscator.restore_vnext import load_direct_restore_vnext
from rtl_obfuscator.source_set import from_filelist
from rtl_obfuscator.symbol_graph import build_symbol_graph
from rtl_obfuscator.systemverilog_names import secure_name_factory


ROOT = Path(__file__).resolve().parents[1]
FIFO_ROOT = ROOT / "rtl_samples" / "example_fifo"
ISOLATION_ROOT = ROOT / "tests" / "fixtures" / "t103_selected_category_isolation"
HIERARCHICAL_ROOT = ROOT / "tests" / "fixtures" / "refactor_symbol_graph_signals_invalid"
T100_ROOT = ROOT / "tests" / "fixtures" / "t100_macro_readonly_module_preserve"
PUBLIC_ENCRYPT = ROOT / "rtl_encrypt.py"
PUBLIC_DECRYPT = ROOT / "rtl_decrypt.py"


class T103SelectedCategoryStableOutcomesTests(unittest.TestCase):
    @staticmethod
    def _run_public(*arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(PUBLIC_ENCRYPT), *arguments],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )

    @staticmethod
    def _source_set(root: Path, *, top: str):
        return from_filelist(filelist=root / "design.f", source_root=root, top=top)

    def test_selected_signal_graph_does_not_collect_parameter_initializer(self):
        source_set = self._source_set(ISOLATION_ROOT, top="t103_top")
        catalog = build_source_catalog(source_set)
        self.assertEqual(
            catalog.to_report()["compile"],
            {
                "catalog": {"parse_errors": 0, "semantic_errors": 0},
                "top_overlay": {"parse_errors": 0, "semantic_errors": 0},
            },
        )
        graph = build_symbol_graph(catalog, categories=("signals",))
        self.assertTrue(graph.symbols)
        self.assertTrue(all(symbol.category == "signals" for symbol in graph.symbols))
        self.assertIn("payload", {symbol.name for symbol in graph.symbols})

        parameter_graph = build_symbol_graph(catalog, categories=("parameters",))
        self.assertTrue(any(symbol.category == "parameters" for symbol in parameter_graph.symbols))

    def test_selected_ports_skip_signal_and_unselected_extended_collectors(self):
        source_set = self._source_set(FIFO_ROOT, top="fifo_top")
        catalog = build_source_catalog(source_set)
        original_record_range = symbol_graph._record_range

        def reject_unselected_collector(source_catalog, node):
            if type(node).__name__ in {
                "TypeAliasType",
                "TransparentMemberSymbol",
                "SubroutineSymbol",
            }:
                raise AssertionError(
                    f"unselected extended collector executed: {type(node).__name__}"
                )
            return original_record_range(source_catalog, node)

        with patch.object(
            symbol_graph,
            "_owner_for_signal",
            side_effect=AssertionError("unselected signal collector executed"),
        ), patch.object(
            symbol_graph,
            "_record_range",
            side_effect=reject_unselected_collector,
        ):
            graph = build_symbol_graph(catalog, categories=("ports",))
        self.assertTrue(graph.symbols)
        self.assertEqual({symbol.category for symbol in graph.symbols}, {"ports"})

    def test_orchestration_reuses_canonical_categories_for_generator(self):
        source_set = self._source_set(FIFO_ROOT, top="fifo_top")
        mapping = orchestration_vnext._build_mapping(
            source_set,
            categories=(category for category in ("signals",)),
            abi_categories=(),
            name_length=20,
            name_factory=secure_name_factory,
        )
        self.assertEqual(mapping.rewrite_policy.selected_categories, ("signals",))
        self.assertTrue(mapping.records)
        self.assertEqual({record.category for record in mapping.records}, {"signals"})

    def test_isolation_public_signal_run_is_pass_full(self):
        with tempfile.TemporaryDirectory(prefix="t103-isolation-") as temporary:
            output = Path(temporary) / "gate"
            result = self._run_public(
                "--filelist",
                str(ISOLATION_ROOT / "design.f"),
                "--top",
                "t103_top",
                "--category",
                "signals",
                "--output-dir",
                str(output),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads((output / "mapping.json").read_text())
            self.assertEqual(report["summary"]["encryption_result"], "PASS_FULL")
            self.assertTrue(report["summary"]["strict_compile_passed"])
            self.assertTrue(report["summary"]["restored_byte_identical"])
            self.assertTrue(report["mapping"]["records"])
            self.assertTrue(all(record["category"] == "signals" for record in report["mapping"]["records"]))
            self.assertNotIn("category_not_selected", {
                record["reason"] for record in report["mapping"]["records"]
            })

    def test_rate_unselected_uses_effective_mapping_for_both_reports(self):
        with tempfile.TemporaryDirectory(prefix="t103-rate-") as temporary:
            root = Path(temporary)
            gate = root / "gate"
            result = self._run_public(
                "--filelist",
                str(FIFO_ROOT / "design.f"),
                "--top",
                "fifo_top",
                "--category",
                "signals",
                "--encryption-rate",
                "0.01",
                "--output-dir",
                str(gate),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            persisted = json.loads((gate / "mapping.json").read_text())
            original_records = persisted["mapping"]["records"]
            effective_records = persisted["mapping_execution"]["mapping"]["records"]
            self.assertTrue(
                any(record["reason"] == "rate_unselected" for record in effective_records)
            )
            self.assertGreater(
                sum(record["action"] == "rename" for record in original_records),
                sum(record["action"] == "rename" for record in effective_records),
            )
            effective_counts = {
                action: sum(record["action"] == action for record in effective_records)
                for action in ("rename", "preserve", "unsupported")
            }
            self.assertEqual(persisted["summary"]["encryption_result"], "PASS_PARTIAL")
            for action in effective_counts:
                self.assertEqual(persisted["summary"][action], effective_counts[action])

            restored = load_direct_restore_vnext(
                gate / "mapping.json",
                gate_dir=gate,
                output_dir=root / "restored",
            )
            restored_effective_counts = {
                action: sum(
                    record.action == action
                    for record in restored.effective_mapping_vnext.records
                )
                for action in ("rename", "preserve", "unsupported")
            }
            for action in restored_effective_counts:
                self.assertEqual(persisted["summary"][action], restored_effective_counts[action])
            self.assertTrue(restored.report["summary"]["rate_enabled"])

    def test_fifo_core_categories_have_rename_and_formal_positive_negative(self):
        categories = ("signals", "ports", "interface", "struct")
        with tempfile.TemporaryDirectory(prefix="t103-fifo-") as temporary:
            root = Path(temporary)
            positive = root / "positive"
            result = self._run_public(
                "--filelist",
                str(FIFO_ROOT / "design.f"),
                "--top",
                "fifo_top",
                *sum((["--category", category] for category in categories), []),
                "--output-dir",
                str(positive),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads((positive / "mapping.json").read_text())
            self.assertEqual(report["summary"]["encryption_result"], "PASS_PARTIAL")
            renamed = {
                record["category"]
                for record in report["mapping"]["records"]
                if record["action"] == "rename"
            }
            self.assertIn("signals", renamed)
            self.assertIn("ports", renamed)
            self.assertTrue({"interfaces", "interface_instances", "interface_ports", "modports"} & renamed)
            self.assertTrue({"struct_types", "struct_fields"} & renamed)

            formal = subprocess.run(
                [
                    sys.executable,
                    "scripts/formal_equivalence.py",
                    "--gold-filelist",
                    str(FIFO_ROOT / "design.f"),
                    "--gold-root",
                    str(FIFO_ROOT),
                    "--gate-filelist",
                    str(positive / "design.f"),
                    "--gate-root",
                    str(positive),
                    "--top",
                    "fifo_top",
                    "--seq",
                    "5",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=300,
            )
            print(f"T103_FORMAL_POSITIVE_EXIT {formal.returncode}")
            print(f"T103_FORMAL_POSITIVE_JSON {formal.stdout.strip()}")
            self.assertEqual(formal.returncode, 0, formal.stdout + formal.stderr)
            self.assertIn('"formal_equivalence": "pass"', formal.stdout)

            restored = root / "restored"
            decrypt = subprocess.run(
                [
                    sys.executable,
                    str(PUBLIC_DECRYPT),
                    "--map",
                    str(positive / "mapping.json"),
                    "--gate-dir",
                    str(positive),
                    "--output-dir",
                    str(restored),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=300,
            )
            self.assertEqual(decrypt.returncode, 0, decrypt.stderr)
            for file in ("fifo_if.sv", "fifo_storage.sv", "fifo_ctrl.sv", "fifo_top.sv"):
                self.assertEqual(
                    (restored / file).read_bytes(),
                    (FIFO_ROOT / file).read_bytes(),
                )

            negative = root / "negative"
            shutil.copytree(positive, negative)
            top_file = negative / "fifo_top.sv"
            source = top_file.read_text()
            self.assertEqual(source.count("assign q = "), 1)
            top_file.write_text(source.replace("assign q = ", "assign q = ~", 1))
            negative_compile = build_source_catalog(
                from_filelist(filelist=negative / "design.f", source_root=negative, top="fifo_top")
            )
            self.assertEqual(negative_compile.to_report()["compile"]["catalog"]["parse_errors"], 0)
            self.assertEqual(negative_compile.to_report()["compile"]["catalog"]["semantic_errors"], 0)
            negative_formal = subprocess.run(
                [
                    sys.executable,
                    "scripts/formal_equivalence.py",
                    "--gold-filelist",
                    str(FIFO_ROOT / "design.f"),
                    "--gold-root",
                    str(FIFO_ROOT),
                    "--gate-filelist",
                    str(negative / "design.f"),
                    "--gate-root",
                    str(negative),
                    "--top",
                    "fifo_top",
                    "--seq",
                    "5",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=300,
            )
            print(f"T103_FORMAL_NEGATIVE_EXIT {negative_formal.returncode}")
            print(f"T103_FORMAL_NEGATIVE_OUTPUT {(negative_formal.stdout + negative_formal.stderr)[-2000:]}")
            self.assertNotEqual(negative_formal.returncode, 0)
            self.assertIn("unproven", negative_formal.stdout + negative_formal.stderr)
            self.assertIn("equiv_status -assert", negative_formal.stdout + negative_formal.stderr)

    def test_macro_boundary_is_pass_partial_and_hierarchical_is_refused_atomic(self):
        with tempfile.TemporaryDirectory(prefix="t103-outcomes-") as temporary:
            partial = Path(temporary) / "partial"
            partial_result = self._run_public(
                "--filelist",
                str(T100_ROOT / "design.f"),
                "--top",
                "t100_top",
                "--category",
                "signals",
                "--output-dir",
                str(partial),
            )
            self.assertEqual(partial_result.returncode, 0, partial_result.stderr)
            partial_report = json.loads((partial / "mapping.json").read_text())
            self.assertEqual(partial_report["summary"]["encryption_result"], "PASS_PARTIAL")
            self.assertTrue(any(record["action"] == "unsupported" for record in partial_report["mapping"]["records"]))

            refused = Path(temporary) / "refused"
            refused_result = self._run_public(
                "--filelist",
                str(HIERARCHICAL_ROOT / "hierarchical.f"),
                "--top",
                "hierarchical",
                "--category",
                "signals",
                "--output-dir",
                str(refused),
            )
            self.assertNotEqual(refused_result.returncode, 0)
            self.assertIn("REFUSED_ATOMIC", refused_result.stderr)
            self.assertIn("ORCHESTRATION_MAPPING_INVALID", refused_result.stderr)
            self.assertIn("hierarchical", refused_result.stderr)
            self.assertFalse(refused.exists())


if __name__ == "__main__":
    unittest.main()
