from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from rtl_obfuscator.source_catalog import build_source_catalog
from rtl_obfuscator.source_set import from_filelist
from rtl_obfuscator.symbol_graph import build_symbol_graph


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "t105_struct_union_implicit_conversion"
FILELIST = FIXTURE_ROOT / "design.f"
TOP = "t105_top"


class T105StructUnionImplicitConversionTests(unittest.TestCase):
    @staticmethod
    def _source_set(root: Path = FIXTURE_ROOT):
        return from_filelist(
            filelist=root / "design.f",
            source_root=root,
            top=TOP,
        )

    @classmethod
    def _graph(cls):
        source_set = cls._source_set()
        catalog = build_source_catalog(source_set)
        graph = build_symbol_graph(
            catalog,
            categories=("struct_types", "struct_fields", "union_fields"),
        )
        return source_set, catalog, graph

    @staticmethod
    def _run_script(script: str, *arguments: str):
        return subprocess.run(
            [sys.executable, str(ROOT / script), *arguments],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=180,
        )

    @staticmethod
    def _formal(gate: Path, root: Path = FIXTURE_ROOT):
        return subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "formal_equivalence.py"),
                "--gold",
                str(root / "formal.sv"),
                "--gate",
                str(gate / "formal.sv"),
                "--top",
                TOP,
                "--seq",
                "5",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=180,
        )

    def test_source_backed_cast_and_implicit_conversion_boundaries(self):
        _source_set, catalog, graph = self._graph()
        symbols = {(symbol.category, symbol.name): symbol for symbol in graph.symbols}
        self.assertTrue(
            {"t105_pair_t", "t105_payload_t"}
            <= {
                name
                for category, name in symbols
                if category == "struct_types"
            }
        )
        self.assertTrue(
            {"hi", "lo"}
            <= {
                name
                for category, name in symbols
                if category == "struct_fields"
            }
        )
        self.assertTrue(
            {"raw", "pair"}
            <= {
                name
                for category, name in symbols
                if category == "union_fields"
            }
        )

        pair = symbols["struct_types", "t105_pair_t"]
        source = (FIXTURE_ROOT / "stress.sv").read_bytes()
        stress_path = (FIXTURE_ROOT / "stress.sv").resolve()

        def syntax_span(syntax):
            source_range = getattr(syntax, "sourceRange", None)
            start = getattr(getattr(source_range, "start", None), "offset", None)
            end = getattr(getattr(source_range, "end", None), "offset", None)
            buffer = getattr(getattr(source_range, "start", None), "buffer", None)
            if start is None or end is None or buffer is None:
                return None
            if Path(catalog.catalog_source_manager.getFullPath(buffer)).resolve() != stress_path:
                return None
            return int(start), int(end)

        def source_text(syntax):
            span = syntax_span(syntax)
            return None if span is None else source[slice(*span)].decode()

        cast_start = source.index(b"t105_pair_t'(data_i)")
        cast_occurrences = [
            occurrence
            for occurrence in pair.occurrences
            if occurrence.provenance == "semantic_cast_type"
        ]
        self.assertEqual(len(cast_occurrences), 1)
        self.assertEqual(cast_occurrences[0].source_range.start, cast_start)
        pair_port_start = source.index(b"input t105_pair_t child_i") + len(b"input ")
        self.assertIn(
            pair_port_start,
            {
                occurrence.source_range.start
                for occurrence in pair.occurrences
                if occurrence.provenance == "semantic_port_type"
            },
        )
        nodes = []
        catalog.catalog_root.visit(nodes.append)
        implicit_conversions = [
            node
            for node in nodes
            if type(node).__name__ == "ConversionExpression"
            and type(getattr(node, "type", None)).__name__ == "TypeAliasType"
            and getattr(node, "syntax", None) is None
        ]
        literal_conversion = next(
            node
            for node in implicit_conversions
            if str(getattr(getattr(node, "type", None), "name", "")) == "t105_pair_t"
            and type(getattr(node, "operand", None)).__name__ == "IntegerLiteral"
        )
        literal_span = syntax_span(getattr(literal_conversion.operand, "syntax", None))
        self.assertIsNotNone(literal_span)
        self.assertEqual(source[slice(*literal_span)], b"2'b01")

        aggregate_assignments = {}
        for node in nodes:
            if type(node).__name__ != "AssignmentExpression":
                continue
            semantic_type = getattr(node, "type", None)
            if type(semantic_type).__name__ != "TypeAliasType":
                continue
            text = source_text(getattr(node, "syntax", None))
            if text in {
                "pair_implicit = {data_i[1], data_i[0]}",
                "payload = data_i",
            }:
                aggregate_assignments[text] = semantic_type
        self.assertEqual(
            str(getattr(aggregate_assignments["pair_implicit = {data_i[1], data_i[0]}"], "name", "")),
            "t105_pair_t",
        )
        self.assertEqual(
            str(getattr(aggregate_assignments["payload = data_i"], "name", "")),
            "t105_payload_t",
        )

        child_port = next(
            node
            for node in nodes
            if type(node).__name__ == "PortSymbol"
            and str(getattr(node, "name", "")) == "child_i"
        )
        self.assertEqual(type(child_port.type).__name__, "TypeAliasType")
        self.assertEqual(str(child_port.type.name), "t105_pair_t")
        port_parent = child_port.syntax.parent
        port_token = port_parent.header.dataType.name.identifier
        self.assertEqual(str(port_token.rawText), "t105_pair_t")
        self.assertEqual(
            source[int(port_token.location.offset):int(port_token.location.offset) + len("t105_pair_t")],
            b"t105_pair_t",
        )
        child_instance = next(
            node
            for node in nodes
            if type(node).__name__ == "InstanceSymbol"
            and str(getattr(node, "name", "")) == "u_child"
        )
        instance_range = getattr(
            getattr(getattr(child_instance, "syntax", None), "sourceRange", None),
            "start",
            None,
        )
        self.assertIsNotNone(instance_range)
        instance_start = int(instance_range.offset)
        self.assertTrue(source[instance_start:].decode().startswith("u_child"))
        child_connection = next(
            connection
            for connection in child_instance.syntax.connections
            if type(connection).__name__ == "NamedPortConnectionSyntax"
            and str(connection.name.rawText) == "child_i"
        )
        connection_span = syntax_span(child_connection)
        expression_span = syntax_span(child_connection.expr)
        self.assertIsNotNone(connection_span)
        self.assertIsNotNone(expression_span)
        self.assertEqual(
            source[slice(*connection_span)],
            b".child_i({data_i[1], data_i[0]})",
        )
        self.assertEqual(
            source[slice(*expression_span)],
            b"{data_i[1], data_i[0]}",
        )

    def test_public_gate_restore_and_actual_formal_positive_and_negative(self):
        with tempfile.TemporaryDirectory(prefix="t105-formal-", dir="/private/tmp") as temporary:
            root = Path(temporary)
            gate = root / "gate"
            result = self._run_script(
                "rtl_encrypt.py",
                "--filelist",
                str(FILELIST),
                "--top",
                TOP,
                "--category",
                "struct",
                "--category",
                "union_fields",
                "--output-dir",
                str(gate),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads((gate / "mapping.json").read_text(encoding="utf-8"))
            summary = report["summary"]
            self.assertEqual(summary["encryption_result"], "PASS_FULL")
            self.assertTrue(summary["strict_compile_passed"])
            self.assertTrue(summary["restored_byte_identical"])
            self.assertEqual(summary["preserve"], 0)
            self.assertEqual(summary["unsupported"], 0)
            renamed_categories = {
                record["category"]
                for record in report["mapping"]["records"]
                if record["action"] == "rename"
            }
            self.assertTrue(
                {"struct_types", "struct_fields", "union_fields"}
                <= renamed_categories
            )
            formal_records = [
                record
                for record in report["mapping"]["records"]
                if record["action"] == "rename"
                and record["declaration"]["file"] == "formal.sv"
                and record["original_name"] in {"t105_formal_pair_t", "hi", "lo"}
            ]
            self.assertEqual(
                {record["original_name"] for record in formal_records},
                {"t105_formal_pair_t", "hi", "lo"},
            )
            formal_gate_source = (gate / "formal.sv").read_bytes()
            formal_gate_evidence = [
                {
                    "category": record["category"],
                    "original_name": record["original_name"],
                    "gate_token": record["renamed_name"],
                    "gate_token_present": record["renamed_name"].encode() in formal_gate_source,
                }
                for record in formal_records
            ]
            print(
                "T105_FORMAL_ACTUAL_RENAMED_RECORDS="
                + json.dumps(formal_gate_evidence, sort_keys=True)
            )
            self.assertTrue(all(item["gate_token_present"] for item in formal_gate_evidence))

            restored = root / "restored"
            decrypt = self._run_script(
                "rtl_decrypt.py",
                "--map",
                str(gate / "mapping.json"),
                "--gate-dir",
                str(gate),
                "--output-dir",
                str(restored),
            )
            self.assertEqual(decrypt.returncode, 0, decrypt.stderr)
            self.assertEqual(
                {
                    path.relative_to(restored).as_posix()
                    for path in restored.rglob("*")
                    if path.is_file()
                },
                {"formal.sv", "stress.sv"},
            )
            for relative in ("formal.sv", "stress.sv"):
                self.assertEqual(
                    (restored / relative).read_bytes(),
                    (FIXTURE_ROOT / relative).read_bytes(),
                )

            positive = self._formal(gate)
            self.assertEqual(positive.returncode, 0, positive.stdout + positive.stderr)
            positive_payload = json.loads(positive.stdout.strip().splitlines()[-1])
            print(f"T105_FORMAL_POSITIVE_EXIT={positive.returncode}")
            print(f"T105_FORMAL_POSITIVE_JSON={json.dumps(positive_payload, sort_keys=True)}")
            self.assertEqual(positive_payload["formal_equivalence"], "pass")

            negative = root / "negative"
            shutil.copytree(gate, negative)
            negative_source = negative / "formal.sv"
            source = negative_source.read_bytes()
            marker = b"assign data_o = formal_o ^ stress_o[0];"
            self.assertEqual(source.count(marker), 1)
            position = source.index(marker) + len(b"assign data_o = ")
            negative_source.write_bytes(source[:position] + b"~" + source[position:])
            negative_catalog = build_source_catalog(self._source_set(negative))
            self.assertEqual(
                negative_catalog.to_report()["compile"],
                {
                    "catalog": {"parse_errors": 0, "semantic_errors": 0},
                    "top_overlay": {"parse_errors": 0, "semantic_errors": 0},
                },
            )
            negative_formal = self._formal(negative)
            negative_output = negative_formal.stdout + negative_formal.stderr
            print(f"T105_FORMAL_NEGATIVE_EXIT={negative_formal.returncode}")
            print(
                "T105_FORMAL_NEGATIVE_OUTPUT="
                + "\n".join(
                    line
                    for line in negative_output.splitlines()
                    if "unproven" in line or "equiv_status -assert" in line
                )
            )
            self.assertNotEqual(negative_formal.returncode, 0)
            self.assertIn("unproven", negative_output)
            self.assertIn("equiv_status -assert", negative_output)


if __name__ == "__main__":
    unittest.main()
