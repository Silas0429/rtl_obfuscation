from __future__ import annotations

import json
import hashlib
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from dataclasses import replace
from unittest.mock import patch

from rtl_obfuscator.formal_vnext import (
    FormalVNextError,
    _audited_rename_dictionary,
    _effective_gate_ranges,
    _lexer_identifier_tokens,
    align_formal_view_vnext,
    build_formal_view_vnext,
)
from rtl_obfuscator.restore_vnext import audit_orchestration_gate_vnext
from rtl_obfuscator.source_catalog import build_source_catalog
from rtl_obfuscator.source_set import from_filelist, from_project_root
import rtl_obfuscator.symbol_graph as symbol_graph
from rtl_obfuscator.symbol_graph import SourceSymbol, SymbolGraphError, build_symbol_graph
from rtl_obfuscator.category_registry_vnext import CANONICAL_CATEGORIES, MODULE_ABI_CATEGORIES
from rtl_obfuscator.orchestration_vnext import run_vnext
from scripts.risc_v_vector_acceptance import (
    COMPILE_ORDER,
    INPUT_MANIFEST,
    canonical,
    mapping_counts,
    normalized_mapping_range_digest,
    normalized_source_set,
)


ROOT = Path(__file__).resolve().parents[1]
RISC = ROOT / "rtl_samples" / "RISC-V-Vector"
T033 = ROOT / "tests" / "fixtures" / "t033_impact_category"


class AuthorizedRiscBoundaryTests(unittest.TestCase):
    def test_project_root_accepts_sv_include_provider_in_compile_order(self) -> None:
        source_set = from_project_root(project_root=RISC, top="vector_top")
        self.assertEqual(source_set.compile_order, COMPILE_ORDER)
        self.assertNotIn("rtl/vector/vmacros.sv", source_set.included_files)

    def test_uninstantiated_and_anonymous_generate_ranges_are_source_backed(self) -> None:
        graph = build_symbol_graph(
            build_source_catalog(from_project_root(project_root=RISC, top="vector_top"))
        )
        ranges: list[tuple[str, int, int]] = []
        for symbol in graph.symbols:
            source = (RISC / symbol.declaration.file).read_bytes()
            self.assertEqual(source[symbol.declaration.start:symbol.declaration.end], symbol.name.encode())
            ranges.append((symbol.declaration.file, symbol.declaration.start, symbol.declaration.end))
            for occurrence in symbol.occurrences:
                source = (RISC / occurrence.source_range.file).read_bytes()
                self.assertEqual(
                    source[occurrence.source_range.start:occurrence.source_range.end],
                    symbol.name.encode(),
                )
                self.assertNotEqual(occurrence.source_range, symbol.declaration)
                ranges.append((occurrence.source_range.file, occurrence.source_range.start, occurrence.source_range.end))
        self.assertEqual(len(ranges), len(set(ranges)))
        self.assertFalse(any(symbol.name.startswith("genblk") for symbol in graph.symbols))

    def test_semantic_fallback_uses_bound_exact_source_range_without_name_search(self) -> None:
        source_set = from_project_root(project_root=RISC, top="vector_top")
        catalog = build_source_catalog(source_set)
        nodes: list[object] = []
        catalog.catalog_root.visit(nodes.append)
        candidate = None
        for node in nodes:
            if type(node).__name__ != "NamedValueExpression":
                continue
            target = getattr(node, "symbol", None)
            name = str(getattr(target, "name", ""))
            syntax = getattr(node, "syntax", None)
            identifier = getattr(syntax, "identifier", None)
            source_range = (
                getattr(syntax, "sourceRange", None)
                if syntax is not None
                else getattr(node, "sourceRange", None)
            )
            start = getattr(source_range, "start", None)
            end = getattr(source_range, "end", None)
            if not name or getattr(identifier, "rawText", "") or start is None or end is None:
                continue
            if start.buffer != end.buffer:
                continue
            relative = Path(catalog.catalog_source_manager.getFullPath(start.buffer)).resolve().relative_to(RISC.resolve()).as_posix()
            if (RISC / relative).read_bytes()[int(start.offset):int(end.offset)] == name.encode():
                candidate = (node, name, relative, int(start.offset), int(end.offset))
                break
        self.assertIsNotNone(candidate)
        node, name, relative, start, end = candidate
        with patch.object(symbol_graph, "_syntax_identifier_tokens", side_effect=AssertionError("subtree search")):
            resolved = symbol_graph._expression_range(catalog, node, name)
        self.assertEqual((resolved.file, resolved.start, resolved.end), (relative, start, end))
        self.assertEqual((RISC / relative).read_bytes()[start:end], name.encode())

    def test_semantic_scope_lookup_recovers_only_bound_omitted_references(self) -> None:
        source_set = from_project_root(project_root=RISC, top="vector_top")
        graph = build_symbol_graph(build_source_catalog(source_set))
        expected = {
            ("parameters", "rtl/vector/vector_top.sv", 227, 239): {
                ("rtl/vector/vector_top.sv", 8932, 8944),
                ("rtl/vector/vector_top.sv", 11538, 11550),
            },
            ("parameters", "rtl/vector/vex.sv", 230, 242): {
                ("rtl/vector/vex.sv", 1010, 1022),
            },
            ("parameters", "rtl/vector/vis.sv", 228, 240): {
                ("rtl/vector/vis.sv", 1158, 1170),
            },
            ("signals", "rtl/shared/eb_buff_generic.sv", 1995, 2004): {
                ("rtl/shared/eb_buff_generic.sv", 2362, 2371),
            },
            ("signals", "rtl/shared/eb_buff_generic.sv", 2020, 2028): {
                ("rtl/shared/eb_buff_generic.sv", 2515, 2523),
            },
        }
        by_key = {
            (symbol.category, symbol.declaration.file, symbol.declaration.start, symbol.declaration.end): symbol
            for symbol in graph.symbols
        }
        for key, required in expected.items():
            symbol = by_key[key]
            actual = {
                (occurrence.source_range.file, occurrence.source_range.start, occurrence.source_range.end)
                for occurrence in symbol.occurrences
            }
            self.assertTrue(required.issubset(actual), key)
            self.assertTrue(
                all(
                    (RISC / item[0]).read_bytes()[item[1]:item[2]] == symbol.name.encode()
                    for item in required
                )
            )
            self.assertTrue(
                all(occurrence.source_range != symbol.declaration for occurrence in symbol.occurrences)
            )

        # The scope resolver is deliberately fail-closed: an unresolvable
        # fixed-field token cannot fall back to a graph name search.
        class EmptyScope:
            def lookupName(self, _name: str) -> None:
                return None

        class Token:
            rawText = "VECTOR_LANES"

        with self.assertRaises(SymbolGraphError) as raised:
            symbol_graph._scope_lookup_target(EmptyScope(), Token())
        self.assertEqual(raised.exception.code, "SYMBOL_GRAPH_UNSUPPORTED_REFERENCE")

    def test_repeated_elaboration_is_deterministic_and_has_unique_physical_ranges(self) -> None:
        source_set = from_project_root(project_root=RISC, top="vector_top")
        first = build_symbol_graph(build_source_catalog(source_set)).to_report()
        second = build_symbol_graph(build_source_catalog(source_set)).to_report()
        self.assertEqual(first, second)
        ranges = []
        for symbol in first["symbols"]:
            declaration = symbol["declaration"]
            source = (RISC / declaration["file"]).read_bytes()
            self.assertEqual(source[declaration["start"]:declaration["end"]], symbol["name"].encode())
            ranges.append((declaration["file"], declaration["start"], declaration["end"]))
            for occurrence in symbol["occurrences"]:
                source_range = occurrence["source_range"]
                source = (RISC / source_range["file"]).read_bytes()
                self.assertEqual(source[source_range["start"]:source_range["end"]], symbol["name"].encode())
                self.assertNotEqual(source_range, declaration)
                ranges.append((source_range["file"], source_range["start"], source_range["end"]))
        self.assertEqual(len(ranges), len(set(ranges)))

    def test_distinct_source_identity_overlap_remains_fail_closed(self) -> None:
        first_range = symbol_graph.SourceRange("rtl/vector/vrrm.sv", 2372, 2380)
        second_range = symbol_graph.SourceRange("rtl/vector/vrrm.sv", 2375, 2384)
        first = SourceSymbol("first", "signals", "instr_in", first_range, "owner:first", "owner:first", (), "local", "internal", "eligible", None)
        second = SourceSymbol("second", "signals", "instr_out", second_range, "owner:second", "owner:second", (), "local", "internal", "eligible", None)
        with self.assertRaises(SymbolGraphError) as raised:
            symbol_graph._audit_ranges((first, second))
        self.assertEqual(raised.exception.code, "SYMBOL_GRAPH_RANGE_CONFLICT")

    def test_genvar_ranges_are_not_collected_as_signals(self) -> None:
        graph = build_symbol_graph(
            build_source_catalog(from_project_root(project_root=RISC, top="vector_top"))
        )
        genvar_ranges = {
            (source_range.file, source_range.start, source_range.end)
            for symbol in graph.symbols
            if symbol.category == "genvars"
            for source_range in (symbol.declaration, *(occurrence.source_range for occurrence in symbol.occurrences))
        }
        signal_ranges = {
            (source_range.file, source_range.start, source_range.end)
            for symbol in graph.symbols
            if symbol.category == "signals"
            for source_range in (symbol.declaration, *(occurrence.source_range for occurrence in symbol.occurrences))
        }
        self.assertTrue(genvar_ranges)
        self.assertTrue(genvar_ranges.isdisjoint(signal_ranges))

    def test_risc_mapping_oracle_strict_gate_and_restore_preflight(self) -> None:
        source_set = from_project_root(project_root=RISC, top="vector_top")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = run_vnext(
                source_set,
                categories=CANONICAL_CATEGORIES,
                abi_categories=MODULE_ABI_CATEGORIES,
                name_length=20,
                gate_dir=root / "gate",
                restore_dir=root / "restore",
            )
            report = result.to_report()
            self.assertEqual(
                canonical(normalized_source_set(report)),
                "b359a1340ba461ce941ab68c6dcd34f33b365935e239af4e606710204f477fc7",
            )
            self.assertEqual(
                normalized_mapping_range_digest(report),
                "217cce2e28c5c81280653fd233ba87d2a70a4a284417a3492182da2520da46fd",
            )
            counts = mapping_counts(report)
            self.assertEqual(
                (counts["total"], counts["rename"], counts["preserve"], counts["unsupported"]),
                (1327, 1301, 26, 0),
            )
            self.assertEqual(report["summary"]["modified_tokens"], 7182)
            self.assertTrue(report["summary"]["strict_compile_passed"])
            physical_files = tuple(dict.fromkeys((*source_set.ordered_source_files, *source_set.included_files)))
            self.assertEqual(len(physical_files), 19)
            mapping_execution = report["mapping_execution"]
            self.assertEqual(
                mapping_execution["restored_manifest"],
                mapping_execution["input_manifest"],
            )
            self.assertTrue(
                all(
                    (RISC / relative).read_bytes() == (root / "restore" / relative).read_bytes()
                    for relative in physical_files
                )
            )


class FormalVNextTransactionTests(unittest.TestCase):
    def _actual_gate(self, root: Path, *, rate: str | None = None) -> tuple[object, Path, Path]:
        source_set = from_filelist(filelist=T033 / "design.f", source_root=T033, top="t033_top")
        result = run_vnext(
            source_set,
            categories=CANONICAL_CATEGORIES,
            abi_categories=MODULE_ABI_CATEGORIES,
            name_length=16,
            encryption_rate=rate,
            gate_dir=root / "gate",
            restore_dir=root / "restore",
        )
        report_path = root / "orchestration.json"
        report_path.write_text(json.dumps(result.to_report(), sort_keys=True), encoding="utf-8")
        return source_set, root / "gate", report_path

    def _gate_view(self, root: Path, source_set: object, gate: Path) -> None:
        gate_set = replace(source_set, source_root=gate)
        build_formal_view_vnext(
            gate_set,
            output_dir=root / "gate-view",
            manifest_path=root / "gate-view.json",
        )

    def _assert_input_invalid(self, root: Path, *, output: Path | None = None, manifest: Path | None = None) -> None:
        with self.assertRaises(FormalVNextError) as raised:
            align_formal_view_vnext(
                gate_dir=root / "gate",
                gate_view_dir=root / "gate-view",
                gate_view_manifest_path=root / "gate-view.json",
                orchestration_report_path=root / "orchestration.json",
                output_dir=output or root / "aligned",
                manifest_path=manifest or root / "aligned.json",
            )
        self.assertEqual(raised.exception.code, "FORMAL_VNEXT_INPUT_INVALID")
        self.assertFalse((output or root / "aligned").exists())
        self.assertFalse((manifest or root / "aligned.json").exists())

    def test_formal_build_and_align_are_byte_deterministic(self) -> None:
        with tempfile.TemporaryDirectory(prefix="t057-formal-", dir="/private/tmp") as temporary:
            root = Path(temporary)
            source_set, gate, report_path = self._actual_gate(root)
            gate_set = replace(source_set, source_root=gate)
            gold = build_formal_view_vnext(source_set, output_dir=root / "gold", manifest_path=root / "gold.json")
            gold_again = build_formal_view_vnext(source_set, output_dir=root / "gold-again", manifest_path=root / "gold-again.json")
            self.assertEqual(gold, gold_again)
            gate_view = build_formal_view_vnext(gate_set, output_dir=root / "gate-view", manifest_path=root / "gate-view.json")
            aligned = align_formal_view_vnext(
                gate_dir=gate,
                gate_view_dir=root / "gate-view",
                gate_view_manifest_path=root / "gate-view.json",
                orchestration_report_path=report_path,
                output_dir=root / "aligned",
                manifest_path=root / "aligned.json",
            )
            self.assertEqual(gold["transformations"], gate_view["transformations"])
            self.assertGreaterEqual(aligned["identifier_replacements"], 0)
            self.assertEqual((root / "gold.json").read_bytes(), (root / "gold-again.json").read_bytes())
            self.assertEqual(aligned["aligned_view_manifest_sha256"], json.loads((root / "aligned.json").read_text())["aligned_view_manifest_sha256"])

    def test_formal_alignment_accepts_valid_no_rate_and_rate_reports(self) -> None:
        for rate in (None, "0.35"):
            with self.subTest(rate=rate), tempfile.TemporaryDirectory(prefix="t057-formal-valid-", dir="/private/tmp") as temporary:
                root = Path(temporary)
                source_set, gate, _report_path = self._actual_gate(root, rate=rate)
                self._gate_view(root, source_set, gate)
                result = align_formal_view_vnext(
                    gate_dir=gate,
                    gate_view_dir=root / "gate-view",
                    gate_view_manifest_path=root / "gate-view.json",
                    orchestration_report_path=root / "orchestration.json",
                    output_dir=root / "aligned",
                    manifest_path=root / "aligned.json",
                )
                self.assertEqual(result["top"], "t033_top")
                self.assertTrue((root / "aligned").is_dir())
                self.assertTrue((root / "aligned.json").is_file())

    def test_formal_alignment_rejects_report_chain_tamper(self) -> None:
        cases = ("outer_schema", "compile_order", "gate_hash", "input_hash", "duplicate_effective", "no_rate_name")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory(prefix="t057-formal-report-", dir="/private/tmp") as temporary:
                root = Path(temporary)
                source_set, gate, report_path = self._actual_gate(root, rate=None)
                self._gate_view(root, source_set, gate)
                report = json.loads(report_path.read_text(encoding="utf-8"))
                if case == "outer_schema":
                    report["schema_version"] = 2
                elif case == "compile_order":
                    report["source_set"]["compile_order"][0] = "../escape.sv"
                elif case == "gate_hash":
                    report["mapping_execution"]["gate_manifest"][0]["sha256"] = "0" * 64
                elif case == "input_hash":
                    report["mapping_execution"]["input_manifest"][0]["sha256"] = "0" * 64
                elif case == "duplicate_effective":
                    records = report["mapping_execution"]["mapping"]["records"]
                    records[1]["renamed_name"] = records[0]["renamed_name"]
                else:
                    for record in report["mapping"]["records"]:
                        if record["action"] == "rename":
                            record["renamed_name"] = "LegalAlternativeName"
                            break
                report_path.write_text(json.dumps(report, sort_keys=True), encoding="utf-8")
                self._assert_input_invalid(root)

    def test_formal_alignment_rejects_gate_view_tamper(self) -> None:
        for case in ("design", "manifest", "physical"):
            with self.subTest(case=case), tempfile.TemporaryDirectory(prefix="t057-formal-view-", dir="/private/tmp") as temporary:
                root = Path(temporary)
                source_set, gate, _report_path = self._actual_gate(root)
                self._gate_view(root, source_set, gate)
                if case == "design":
                    path = root / "gate-view" / "design.f"
                    path.write_bytes(path.read_bytes() + b"\n")
                elif case == "manifest":
                    view_report = json.loads((root / "gate-view.json").read_text(encoding="utf-8"))
                    view_report["view_manifest_sha256"] = "0" * 64
                    (root / "gate-view.json").write_text(json.dumps(view_report, sort_keys=True), encoding="utf-8")
                else:
                    path = root / "gate-view" / source_set.compile_order[0]
                    content = bytearray(path.read_bytes())
                    content[0] ^= 1
                    path.write_bytes(bytes(content))
                self._assert_input_invalid(root)

    def test_formal_alignment_rejects_all_input_output_overlaps(self) -> None:
        with tempfile.TemporaryDirectory(prefix="t057-formal-paths-", dir="/private/tmp") as temporary:
            root = Path(temporary)
            source_set, gate, _report_path = self._actual_gate(root)
            self._gate_view(root, source_set, gate)
            cases = (
                (root / "gate-view" / "aligned-inside-input", root / "aligned.json"),
                (root / "gate" / "aligned-inside-input", root / "aligned.json"),
                (root / "aligned-view", root / "gate-view" / "aligned.json"),
                (root / "aligned-gate", root / "gate" / "aligned.json"),
                (root / "aligned-same", root / "aligned-same"),
            )
            for output, manifest in cases:
                with self.subTest(output=output, manifest=manifest):
                    with self.assertRaises(FormalVNextError) as raised:
                        align_formal_view_vnext(
                            gate_dir=gate,
                            gate_view_dir=root / "gate-view",
                            gate_view_manifest_path=root / "gate-view.json",
                            orchestration_report_path=root / "orchestration.json",
                            output_dir=output,
                            manifest_path=manifest,
                        )
                    self.assertEqual(raised.exception.code, "FORMAL_VNEXT_OUTPUT_INVALID")
                    self.assertFalse(output.exists())
                    self.assertFalse(manifest.exists())

    def test_formal_failure_leaves_no_partial_output_or_input_change(self) -> None:
        with tempfile.TemporaryDirectory(prefix="t057-formal-failure-", dir="/private/tmp") as temporary:
            root = Path(temporary)
            source_set, gate, _report_path = self._actual_gate(root)
            self._gate_view(root, source_set, gate)
            before = {
                path: path.read_bytes()
                for path in (root / "gate-view.json", root / "orchestration.json", root / "gate-view" / "design.f")
            }
            with patch.object(symbol_graph, "_audit_ranges", wraps=symbol_graph._audit_ranges):
                with patch("rtl_obfuscator.formal_vnext._validate_yosys", side_effect=FormalVNextError("FORMAL_VNEXT_YOSYS_FAILED", "forced")):
                    with self.assertRaises(FormalVNextError) as raised:
                        align_formal_view_vnext(
                            gate_dir=gate,
                            gate_view_dir=root / "gate-view",
                            gate_view_manifest_path=root / "gate-view.json",
                            orchestration_report_path=root / "orchestration.json",
                            output_dir=root / "aligned",
                            manifest_path=root / "aligned.json",
                        )
            self.assertEqual(raised.exception.code, "FORMAL_VNEXT_YOSYS_FAILED")
            self.assertFalse((root / "aligned").exists())
            self.assertFalse((root / "aligned.json").exists())
            self.assertEqual(before, {path: path.read_bytes() for path in before})
            self.assertFalse(any(path.name.startswith(".formal-align-vnext-") for path in root.iterdir()))

    def test_formal_alignment_tamper_and_path_conflict_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="t057-formal-tamper-", dir="/private/tmp") as temporary:
            root = Path(temporary)
            source_set, gate, report_path = self._actual_gate(root)
            gate_set = replace(source_set, source_root=gate)
            build_formal_view_vnext(gate_set, output_dir=root / "gate-view", manifest_path=root / "gate-view.json")
            tampered = root / "gate-view" / "design.f"
            tampered.write_bytes(tampered.read_bytes() + b"\n")
            with self.assertRaises(FormalVNextError):
                align_formal_view_vnext(
                    gate_dir=gate,
                    gate_view_dir=root / "gate-view",
                    gate_view_manifest_path=root / "gate-view.json",
                    orchestration_report_path=report_path,
                    output_dir=root / "aligned",
                    manifest_path=root / "aligned.json",
                )
            self.assertFalse((root / "aligned").exists())
            self.assertFalse((root / "aligned.json").exists())

    def test_formal_alignment_restores_identifiers_copied_into_transformation_replacements(self) -> None:
        source = b"""typedef struct packed {
  logic [7:0] field;
} packed_t;

module packed_top(
  input logic [7:0] raw_data,
  output logic [1:0] out
);
  packed_t data;
  assign data = raw_data;
  assign out = data.field[1:0];
endmodule
"""

        def factory(symbol_id: str, name_length: int, unavailable: frozenset[str]) -> str:
            digest = hashlib.sha256(symbol_id.encode("utf-8")).hexdigest()
            candidate = "n" + digest[: name_length - 1]
            if candidate in unavailable:
                raise AssertionError("deterministic test name collision")
            return candidate

        with tempfile.TemporaryDirectory(prefix="t057-formal-member-", dir="/private/tmp") as temporary:
            root = Path(temporary)
            input_root = root / "input"
            input_root.mkdir()
            (input_root / "design.sv").write_bytes(source)
            (input_root / "design.f").write_text("design.sv\n", encoding="utf-8")
            source_set = from_filelist(filelist=input_root / "design.f", source_root=input_root, top="packed_top")
            result = run_vnext(
                source_set,
                categories=CANONICAL_CATEGORIES,
                abi_categories=MODULE_ABI_CATEGORIES,
                name_length=16,
                name_factory=factory,
                gate_dir=root / "gate",
                restore_dir=root / "restore",
            )
            report_path = root / "orchestration.json"
            report_path.write_text(json.dumps(result.to_report(), sort_keys=True), encoding="utf-8")
            gate = root / "gate"
            gate_set = replace(source_set, source_root=gate)
            build_formal_view_vnext(
                gate_set,
                output_dir=root / "gate-view",
                manifest_path=root / "gate-view.json",
            )
            audit = audit_orchestration_gate_vnext(report_path, gate_dir=gate)
            replacements = _audited_rename_dictionary(audit.effective_records)
            data_renamed = next(renamed for renamed, original in replacements.items() if original == "data")
            gate_view_source = (root / "gate-view" / "design.sv").read_bytes()
            self.assertIn(data_renamed.encode("utf-8"), gate_view_source)
            self.assertIn(data_renamed.encode("utf-8") + b"[0 +: 8]", gate_view_source)
            audited_range_count = len(_effective_gate_ranges(audit.effective_records))
            gate_view_tokens = _lexer_identifier_tokens(root / "gate-view" / "design.sv", gate_view_source, replacements)
            aligned = align_formal_view_vnext(
                gate_dir=gate,
                gate_view_dir=root / "gate-view",
                gate_view_manifest_path=root / "gate-view.json",
                orchestration_report_path=report_path,
                output_dir=root / "aligned",
                manifest_path=root / "aligned.json",
            )
            self.assertEqual(aligned["identifier_replacements"], len(gate_view_tokens))
            aligned_source = (root / "aligned" / "design.sv").read_bytes()
            self.assertIn(b"data[0 +: 8]", aligned_source)
            self.assertNotIn(data_renamed.encode("utf-8"), aligned_source)
            self.assertLess(aligned["identifier_replacements"], audited_range_count)

            extra = root / "gate-view" / "design.sv"
            extra.write_bytes(gate_view_source + b"\n// " + data_renamed.encode("utf-8") + b"\n")
            self._assert_input_invalid(root, output=root / "aligned-extra", manifest=root / "aligned-extra.json")

            report = json.loads(report_path.read_text(encoding="utf-8"))
            for record in report["mapping"]["records"]:
                if record.get("original_name") == "data" and record.get("action") == "rename":
                    record["renamed_name"] = "nwrong_dictionary"
                    break
            report_path.write_text(json.dumps(report, sort_keys=True), encoding="utf-8")
            self._assert_input_invalid(root, output=root / "aligned-dictionary", manifest=root / "aligned-dictionary.json")

    def test_risc_alignment_preflight_matches_frozen_oracles_without_equivalence(self) -> None:
        def warning_digest(root: Path, source_set: object, replacements: dict[str, str]) -> str:
            files = [str(root / relative) for relative in source_set.compile_order]
            script = "read_verilog -sv -formal -defer " + " ".join(files) + f"; hierarchy -check -top {source_set.top}"
            process = subprocess.run(["yosys", "-Q", "-p", script], capture_output=True, text=True, check=False)
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            warnings: set[str] = set()
            for output in (process.stdout, process.stderr):
                for raw_line in output.splitlines():
                    if "Warning:" not in raw_line and not raw_line.startswith("Warnings:"):
                        continue
                    line = raw_line.replace(str(root), "<root>")
                    for renamed, original in sorted(replacements.items(), key=lambda item: -len(item[0])):
                        line = line.replace(renamed, original)
                    line = re.sub(r"\$paramod\$[0-9a-f]+", "$paramod$<hash>", line)
                    warnings.add(line)
            return canonical(sorted(warnings))

        with tempfile.TemporaryDirectory(prefix="t057-risc-preflight-", dir="/private/tmp") as temporary:
            root = Path(temporary)
            source_set = from_project_root(project_root=RISC, top="vector_top")
            result = run_vnext(
                source_set,
                categories=CANONICAL_CATEGORIES,
                abi_categories=MODULE_ABI_CATEGORIES,
                name_length=20,
                gate_dir=root / "gate",
                restore_dir=root / "restore",
            )
            report_path = root / "orchestration.json"
            report_path.write_text(json.dumps(result.to_report(), sort_keys=True), encoding="utf-8")
            gate = root / "gate"
            audit = audit_orchestration_gate_vnext(report_path, gate_dir=gate)
            replacements = _audited_rename_dictionary(audit.effective_records)
            expected = {
                (file, start, end): renamed
                for file, start, end, _original, renamed in _effective_gate_ranges(audit.effective_records)
            }
            actual = {
                (relative, start, end): raw_text.encode("utf-8")
                for relative in source_set.compile_order
                for start, end, raw_text in _lexer_identifier_tokens(
                    gate / relative, (gate / relative).read_bytes(), replacements
                )
            }
            self.assertEqual(len(expected), 7182)
            self.assertEqual(len(actual), 7182)
            self.assertEqual(actual, expected)
            gate_set = replace(source_set, source_root=gate)
            gold_summary = build_formal_view_vnext(
                source_set,
                output_dir=root / "formal-gold",
                manifest_path=root / "formal-gold.json",
            )
            gate_summary = build_formal_view_vnext(
                gate_set,
                output_dir=root / "formal-gate",
                manifest_path=root / "formal-gate.json",
            )
            self.assertEqual(gold_summary["transformations"], gate_summary["transformations"])
            gold_digest = warning_digest(root / "formal-gold", source_set, {})
            gate_digest = warning_digest(root / "formal-gate", source_set, replacements)
            alignment = align_formal_view_vnext(
                gate_dir=gate,
                gate_view_dir=root / "formal-gate",
                gate_view_manifest_path=root / "formal-gate.json",
                orchestration_report_path=report_path,
                output_dir=root / "formal-aligned",
                manifest_path=root / "formal-aligned.json",
            )
            aligned_digest = warning_digest(root / "formal-aligned", source_set, {})
            self.assertEqual(gold_digest, "82364328ba2442aea6429d2a1ec8ab406784f0fcfb4d9d3b681589de8e5a6b8f")
            self.assertEqual(gate_digest, gold_digest)
            self.assertEqual(aligned_digest, gold_digest)
            self.assertEqual(alignment["identifier_replacements"], 6914)
            self.assertEqual(
                alignment["aligned_view_manifest_sha256"],
                "7c93970509f6844c6fb7902de6ded6878e8fae6753578a5b862e6fc3c18deae9",
            )
            self.assertTrue((root / "formal-aligned").is_dir())
            self.assertFalse(any(path.name.startswith(".formal-align-vnext-") for path in root.iterdir()))

    def test_release_oracle_helpers_are_portable_and_canonical(self) -> None:
        source_set = from_project_root(project_root=RISC, top="vector_top")
        report = {
            "source_set": {
                **source_set.to_report(),
                "source_root": "/private/not-portable",
            },
            "mapping": {
                "records": [],
            },
            "summary": {"modified_tokens": 0},
        }
        normalized = normalized_source_set(report)
        self.assertNotIn("source_root", normalized)
        self.assertEqual(tuple(normalized["compile_order"]), COMPILE_ORDER)
        self.assertEqual(canonical(normalized), canonical(normalized_source_set(report)))
        self.assertEqual(normalized_mapping_range_digest(report), normalized_mapping_range_digest(report))
        counts = mapping_counts(report)
        self.assertEqual(counts["total"], 0)
        self.assertEqual(INPUT_MANIFEST, "a016dd548525346508c636b97fcc452c8f6eb4fcbf930ef5eb938a2edfa2ae9d")


if __name__ == "__main__":
    unittest.main()
