"""Nested named aggregate types keep live types and physical references together."""

from pathlib import Path
import json
import re
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

from rtl_obfuscator import rename_index as ri
from rtl_obfuscator.mapping_vnext import build_mapping_vnext
from rtl_obfuscator.rewrite_vnext import restore_gate_vnext, write_gate_vnext
from rtl_obfuscator.source_catalog import build_source_catalog
from rtl_obfuscator.source_set import from_filelist
from rtl_obfuscator.systemverilog_names import secure_name_factory
from tests.test_t146_struct_array_type_reachability import sources

ROOT = Path(__file__).resolve().parents[1]
FORMAL_SOURCE = """module top(input logic [3:0] a, output logic [3:0] y);
typedef struct packed {logic [3:0] field;} payload_t;
typedef struct packed {payload_t inner;} envelope_t;
envelope_t word;
assign word.inner.field = a;
assign y = word.inner.field ^ 4'ha;
endmodule
"""


class T147NestedAggregateTypeReferencesTests(unittest.TestCase):
    def _one(self, index, name):
        record, = [r for r in index.symbols if r.category == "struct" and r.name == name]
        return record

    def _audit(self, index, source):
        ranges = {}
        for record in index.symbols:
            for value in (record.declaration, *(o.source_range for o in record.occurrences)):
                data = (source.source_root / value.file).read_bytes()
                self.assertTrue(0 <= value.start < value.end <= len(data))
                self.assertEqual(data[value.start:value.end], record.name.encode())
                ranges.setdefault(value.file, []).append((value.start, value.end))
        for file, values in ranges.items():
            self.assertEqual(len(values), len(set(values)), file)
            for left, right in zip(sorted(values), sorted(values)[1:]):
                self.assertLessEqual(left[1], right[0], file)

    def _roundtrip(self, root, source, index):
        mapping = build_mapping_vnext(index, name_length=20, name_factory=secure_name_factory)
        execution = write_gate_vnext(mapping, output_dir=root / "gate")
        restored = restore_gate_vnext(execution, gate_dir=root / "gate", output_dir=root / "restore")
        self.assertTrue(restored.to_report()["summary"]["byte_identical"])
        for entry in mapping.input_manifest:
            self.assertEqual((root / "restore" / entry.file).read_bytes(),
                             (source.source_root / entry.file).read_bytes())

    def test_nested_type_and_real_field_type_token_are_both_supported(self):
        for category in ("all", "struct"):
            with self.subTest(category=category), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source = sources(root / "gold", FORMAL_SOURCE)
                index = ri.build_rename_index(build_source_catalog(source), categories=(category,))
                for name in ("payload_t", "envelope_t", "inner", "field"):
                    record = self._one(index, name)
                    self.assertEqual((record.support, record.reason), ("eligible", None))
                    self.assertEqual({record.declaration.start, *(o.source_range.start for o in record.occurrences)},
                                     {m.start() for m in re.finditer(r"\b" + name + r"\b", FORMAL_SOURCE)})
                self._audit(index, source)
                self._roundtrip(root, source, index)

    def test_multilevel_arrays_inline_carriers_and_shared_type_token(self):
        cases = {
            "multilevel": ("typedef struct packed {payload_t inner;} middle_t;\n"
                           "typedef struct packed {middle_t middle;} envelope_t;\nenvelope_t word;", "word.middle.inner.field"),
            "field_array": ("typedef struct {payload_t inner[2];} envelope_t;\nenvelope_t word;", "word.inner[0].field"),
            "packed_field_array": ("typedef struct packed {payload_t[1:0] inner;} envelope_t;\nenvelope_t word;", "word.inner[0].field"),
            "array_carrier": ("typedef struct packed {payload_t inner;} envelope_t;\nenvelope_t word[2];", "word[0].inner.field"),
            "alias_array_field": ("typedef payload_t array_t[2];\n"
                                  "typedef struct {array_t inner;} envelope_t;\nenvelope_t word;", "word.inner[0].field"),
            "inline": ("struct packed {payload_t inner;} word;", "word.inner.field"),
            "shared_token": ("typedef struct packed {payload_t inner, second;} envelope_t;\nenvelope_t word;", "word.inner.field"),
            "union": ("typedef union packed {payload_t inner;} envelope_t;\nenvelope_t word;", "word.inner.field"),
        }
        prefix = FORMAL_SOURCE[:FORMAL_SOURCE.index("typedef struct packed {payload_t")]
        for case, (declaration, access) in cases.items():
            code = prefix + declaration + f"\nassign {access} = a;\nassign y = {access};\nendmodule\n"
            for category in ("all", "struct"):
                with self.subTest(case=case, category=category), tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    source = sources(root / "gold", code)
                    index = ri.build_rename_index(build_source_catalog(source), categories=(category,))
                    for name in ("payload_t", "field"):
                        record = self._one(index, name)
                        self.assertEqual((record.support, record.reason), ("eligible", None))
                        self.assertEqual({record.declaration.start, *(o.source_range.start for o in record.occurrences)},
                                         {m.start() for m in re.finditer(r"\b" + name + r"\b", code)})
                    self.assertEqual(len(self._one(index, "payload_t").occurrences), 1)
                    self._audit(index, source)
                    self._roundtrip(root, source, index)

    def test_physical_types_and_parameter_specializations_do_not_merge(self):
        module = """module CELL #(parameter W=4)(input logic [W-1:0] a, output logic [W-1:0] y);
typedef struct packed {logic [W-1:0] field;} payload_t;
typedef struct packed {payload_t inner;} envelope_t;
envelope_t word;
assign word.inner.field = a;
assign y = word.inner.field;
endmodule
"""
        code = module.replace("CELL", "first") + module.replace("CELL", "second") + """module top(
input logic [7:0] a, output logic [7:0] y);
wire [3:0] narrow_value;
wire [7:0] wide;
first #(.W(4)) u0(.a(a[3:0]), .y(narrow_value));
first #(.W(8)) u1(.a(a), .y(wide));
second #(.W(8)) u2(.a(wide ^ {narrow_value, narrow_value}), .y(y));
endmodule
"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = sources(root / "gold", code)
            index = ri.build_rename_index(build_source_catalog(source), categories=("all",))
            boundary = code.index("module second")
            for name in ("payload_t", "envelope_t", "field", "inner"):
                records = [r for r in index.symbols if r.category == "struct" and r.name == name]
                self.assertEqual(len(records), 2)
                self.assertEqual(len({r.symbol_id for r in records}), 2)
                for record in records:
                    self.assertEqual(record.support, "eligible")
                    self.assertTrue(all((o.source_range.start < boundary) ==
                                        (record.declaration.start < boundary) for o in record.occurrences))
            self._audit(index, source)
            self._roundtrip(root, source, index)

    def test_unused_type_definitions_and_selected_category_remain_boundaries(self):
        code = FORMAL_SOURCE.replace("envelope_t word;", "").replace(
            "assign word.inner.field = a;\nassign y = word.inner.field ^ 4'ha;", "assign y = a;")
        with tempfile.TemporaryDirectory() as temporary:
            source = sources(Path(temporary), code)
            catalog = build_source_catalog(source)
            index = ri.build_rename_index(catalog, categories=("all",))
            for name in ("payload_t", "envelope_t", "inner", "field"):
                self.assertEqual(self._one(index, name).reason, "outside_top_closure")
            signals = ri.build_rename_index(catalog, categories=("signals",))
            self.assertFalse(any(r.category == "struct" for r in signals.symbols))

    def test_catalog_field_references_outside_top_readonly_and_root_are_retained(self):
        for case in ("header", "outside_root", "outside_top"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                gold = root / "gold"
                if case == "header":
                    code = FORMAL_SOURCE.replace("typedef struct packed {payload_t inner;} envelope_t;",
                                                 '`include "nested.svh"')
                    extra = {"nested.svh": "typedef struct packed {payload_t inner;} envelope_t;\n"}
                    source = sources(gold, code, extra=extra)
                    expected = "readonly_include_file"
                else:
                    types = "package types; typedef struct packed {logic [3:0] field;} payload_t; endpackage\n"
                    code = """module top(input logic [3:0] a, output logic [3:0] y);
types::payload_t word; assign word.field = a; assign y = word.field; endmodule
"""
                    extra = {"own/types.sv": types, "other.sv": """module other;
typedef struct packed {types::payload_t inner;} envelope_t;
endmodule
"""}
                    sources(gold, code, extra=extra)
                    (gold / "design.f").write_text("own/types.sv\ndesign.sv\nother.sv\n")
                    source = from_filelist(filelist=gold / "design.f", top="top",
                                           rewrite_roots=(gold / "own",) if case == "outside_root" else (gold,))
                    expected = "outside_rewrite_root" if case == "outside_root" else None
                index = ri.build_rename_index(build_source_catalog(source), categories=("all",))
                payload = self._one(index, "payload_t")
                self.assertEqual(payload.reason, expected)
                self.assertTrue(any(o.source_range.file == ("nested.svh" if case == "header" else "other.sv")
                                    for o in payload.occurrences))
                self._audit(index, source)
                self._roundtrip(root, source, index)

    def test_missing_field_range_preserves_live_type_and_getter_failures_do_not_fallback(self):
        original = ri._type_occurrence_range
        with tempfile.TemporaryDirectory() as temporary:
            source = sources(Path(temporary), FORMAL_SOURCE)
            catalog = build_source_catalog(source)
            def omit_field(catalog, node, expected, **kwargs):
                return None if type(node).__name__ == "FieldSymbol" else original(catalog, node, expected, **kwargs)
            with patch.object(ri, "_type_occurrence_range", side_effect=omit_field):
                index = ri.build_rename_index(catalog, categories=("all",))
            record = self._one(index, "payload_t")
            self.assertEqual(record.reason, "source_binding_incomplete")
            self.assertEqual(record.occurrences, ())
            self._audit(index, source)

        named = NS(kind="NamedType", name=object())
        parent = NS(kind="StructUnionMember", type=named)
        field = type("FieldSymbol", (), {})()
        field.syntax = NS(kind="Declarator", parent=parent)
        field.declaredType = NS(typeSyntax=None)
        with patch.object(ri, "_syntax_identifier_range", return_value="proven") as bound:
            self.assertEqual(ri._type_occurrence_range(NS(), field, "payload_t"), "proven")
            bound.assert_called_once()
        for bad in (NS(kind="IntegerType"), NS(kind="NamedType", name=None)):
            field.declaredType = NS(typeSyntax=bad)
            with patch.object(ri, "_syntax_identifier_range", return_value=None):
                self.assertIsNone(ri._type_occurrence_range(NS(), field, "payload_t"))
        for error in (AttributeError, RuntimeError):
            def broken(_self):
                raise error("type syntax unavailable")
            field.declaredType = type("BrokenDeclared", (), {"typeSyntax": property(broken)})()
            with patch.object(ri, "_syntax_identifier_range") as bound:
                with self.assertRaises(error):
                    ri._type_occurrence_range(NS(), field, "payload_t")
                bound.assert_not_called()
        field.declaredType = NS(typeSyntax=None)
        for syntax in (None, NS(kind="Declarator", parent=None),
                       NS(kind="Declarator", parent=NS(kind="DataDeclaration", type=named))):
            field.syntax = syntax
            with patch.object(ri, "_syntax_identifier_range") as bound:
                self.assertIsNone(ri._type_occurrence_range(NS(), field, "payload_t"))
                bound.assert_not_called()
        for error in (AttributeError, RuntimeError):
            def broken_parent(_self):
                raise error("parent syntax unavailable")
            field.syntax = type("DeclaratorSyntax", (), {"kind": "Declarator", "parent": property(broken_parent)})()
            with patch.object(ri, "_syntax_identifier_range") as bound:
                if error is AttributeError:
                    self.assertIsNone(ri._type_occurrence_range(NS(), field, "payload_t"))
                else:
                    with self.assertRaises(error):
                        ri._type_occurrence_range(NS(), field, "payload_t")
                bound.assert_not_called()

    def test_type_edges_hold_identity_reuse_success_and_retry_unknown_facts(self):
        alias = type("TypeAliasType", (), {"targetType": NS(type=NS())})()
        field = type("FieldSymbol", (), {"declaredType": NS(type=alias)})()
        state = {"reads": 0, "fields": (field,)}
        def members(_self):
            state["reads"] += 1
            return iter(state["fields"])
        aggregate = type("PackedStructType", (), {"__iter__": members})()
        self.assertEqual(list(ri._type_reference_nodes((aggregate, aggregate))), [aggregate, field, alias])
        self.assertEqual(state["reads"], 1)
        state["fields"] = ()
        self.assertEqual(list(ri._type_reference_nodes((aggregate,))), [aggregate])
        self.assertEqual(state["reads"], 2)
        for error in (AttributeError, RuntimeError):
            counts = {"reads": 0}
            def edge(_self):
                counts["reads"] += 1
                if counts["reads"] == 1:
                    raise error("field type temporarily unavailable")
                return NS(type=alias)
            unknown = type("FieldSymbol", (), {"declaredType": property(edge)})()
            nodes = list(ri._type_reference_nodes((unknown, unknown)))
            self.assertIn(alias, nodes)
            self.assertEqual(counts["reads"], 2)
        for kind in ("ErrorType", "DynamicArrayType", "AssociativeArrayType", "QueueType"):
            unknown = type(kind, (), {"elementType": alias})()
            self.assertEqual(list(ri._type_reference_nodes((unknown,))), [])

    def test_inline_declared_type_keeps_unknown_workset_nodes_and_failed_getter_retry(self):
        aggregate = type("PackedStructType", (), {"__iter__": lambda _self: iter(())})()
        for shared in (True, False):
            counts = {"reads": 0}
            def declared(_self):
                counts["reads"] += 1
                return NS(type=aggregate)
            node = type("FutureSemanticNode", (), {"declaredType": property(declared)})()
            catalog = (ri._OrderedSemanticNode(0, node),)
            top = catalog if shared else (ri._OrderedSemanticNode(1, node),)
            workset = ri._SemanticWorkset(catalog, top)
            self.assertEqual(workset.top_type_nodes, (node,))
            self.assertEqual(counts["reads"], 1 if shared else 2)
        for error in (AttributeError, RuntimeError):
            counts = {"reads": 0}
            def retrying_declared(_self):
                counts["reads"] += 1
                if counts["reads"] == 1:
                    raise error("declared type temporarily unavailable")
                return NS(type=aggregate)
            node = type("FutureSemanticNode", (), {"declaredType": property(retrying_declared)})()
            ordered = (ri._OrderedSemanticNode(0, node),)
            self.assertEqual(ri._SemanticWorkset(ordered, ordered).top_type_nodes, (node,))
            self.assertEqual(counts["reads"], 2)


    def _run(self, script, *args):
        command = [sys.executable, str(ROOT / script), *map(str, args)]
        run = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=120)
        return command, run

    def test_public_actual_gate_restore_and_formal_with_independent_vector_oracle(self):
        # Keep actual product output and every frontend warning for Main review.
        root = Path(tempfile.mkdtemp(prefix="t147-evidence-")).resolve()
        gold, gate = root / "gold", root / "gate"
        source = sources(gold, FORMAL_SOURCE)
        encrypt_command, encrypted = self._run(
            "rtl_encrypt.py", "--filelist", gold / "design.f", "--top", "top",
            "--rewrite-root", gold, "--category", "all", "--output-dir", gate, "--quiet",
        )
        self.assertEqual(encrypted.returncode, 0, encrypted.stdout + encrypted.stderr)
        summary = json.loads(encrypted.stdout)["summary"]
        self.assertTrue(summary["strict_compile_passed"])
        self.assertTrue(summary["restored_byte_identical"])
        mapping = json.loads((gate / "mapping.json").read_text())["mapping"]
        targets = [r for r in mapping["records"] if r["original_name"] in {"payload_t", "envelope_t", "inner", "field"}]
        self.assertEqual(len(targets), 4)
        self.assertTrue(all(r["action"] == "rename" for r in targets), targets)
        self.assertEqual({r["file"] for r in mapping["input_manifest"]}, {"design.sv"})
        self._audit(ri.build_rename_index(build_source_catalog(source), categories=("all",)), source)
        gate_bytes = (gate / "design.sv").read_bytes()
        by_name = {record["original_name"]: record for record in targets}
        for name, record in by_name.items():
            self.assertNotIn(name.encode(), gate_bytes)
            self.assertEqual(1 + len(record["occurrences"]),
                             len(re.findall(r"\b" + name + r"\b", FORMAL_SOURCE)))
        self.assertIn(b"typedef struct packed {" + by_name["payload_t"]["renamed_name"].encode(), gate_bytes)
        self.assertIn(b"." + by_name["inner"]["renamed_name"].encode() + b"." +
                      by_name["field"]["renamed_name"].encode(), gate_bytes)
        expected = FORMAL_SOURCE.encode()
        edits = []
        for record in mapping["records"]:
            if record["action"] == "rename":
                for value in (record["declaration"], *(o["source_range"] for o in record["occurrences"])):
                    self.assertEqual(value["file"], "design.sv")
                    self.assertEqual(expected[value["start"]:value["end"]], record["original_name"].encode())
                    edits.append((value["start"], value["end"], record["renamed_name"].encode()))
        self.assertEqual(len(edits), len({(start, end) for start, end, _ in edits}))
        for start, end, name in sorted(edits, reverse=True):
            expected = expected[:start] + name + expected[end:]
        self.assertEqual(gate_bytes, expected)
        self.assertNotEqual(gate_bytes, FORMAL_SOURCE.encode())
        restore = root / "restore"
        decrypt_command, decrypted = self._run(
            "rtl_decrypt.py", "--gate-dir", gate, "--map", gate / "mapping.json", "--output-dir", restore,
        )
        self.assertEqual(decrypted.returncode, 0, decrypted.stdout + decrypted.stderr)
        self.assertEqual((restore / "design.sv").read_bytes(), FORMAL_SOURCE.encode())

        def proof(label, gold_root, gate_root):
            command, run = self._run(
                "scripts/formal_equivalence.py", "--gold-filelist", gold_root / "design.f",
                "--gold-root", gold_root, "--gate-filelist", gate_root / "design.f",
                "--gate-root", gate_root, "--top", "top", "--seq", "5",
            )
            (root / (label + ".stdout")).write_text(run.stdout)
            (root / (label + ".stderr")).write_text(run.stderr)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            result = json.loads(run.stdout.strip().splitlines()[-1])
            self.assertEqual(result["formal_equivalence"], "pass")
            return {"command": command, "exit": run.returncode, "json": result}

        positive = proof("actual-gate", gold, gate)
        oracle = root / "oracle"
        sources(oracle, "module top(input logic [3:0] a, output logic [3:0] y); "
                        "assign y = a ^ 4'ha; endmodule\n")
        oracle_gold = proof("oracle-gold", oracle, gold)
        oracle_gate = proof("oracle-gate", oracle, gate)
        frontend = []
        for folder in (gold, gate):
            command = ["yosys", "-p", f'read_verilog -sv -formal -defer "{folder / "design.sv"}"; '
                       "prep -top top -flatten; check -assert"]
            run = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=120)
            log = root / (folder.name + "-frontend.log")
            log.write_text(run.stdout + run.stderr)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            frontend.append({"command": command, "exit": run.returncode, "log": str(log),
                             "warnings": [s for s in (run.stdout + run.stderr).splitlines()
                                          if "warning" in s.lower()]})

        negative = root / "negative"
        shutil.copytree(gate, negative)
        (negative / "design.f").write_text(str(negative / "design.sv") + "\n")
        self.assertEqual(gate_bytes.count(b"4'ha"), 1)
        (negative / "design.sv").write_bytes(gate_bytes.replace(b"4'ha", b"4'hb", 1))
        negative_source = from_filelist(filelist=negative / "design.f", top="top")
        self.assertEqual(negative_source.source_root, negative)
        self.assertEqual(negative_source.ordered_source_files, ("design.sv",))
        negative_compile = build_source_catalog(negative_source).to_report()["compile"]
        self.assertEqual(negative_compile, {
            "catalog": {"parse_errors": 0, "semantic_errors": 0},
            "top_overlay": {"parse_errors": 0, "semantic_errors": 0},
        })
        command, rejected = self._run(
            "scripts/formal_equivalence.py", "--gold-filelist", gold / "design.f", "--gold-root", gold,
            "--gate-filelist", negative / "design.f", "--gate-root", negative, "--top", "top", "--seq", "5",
        )
        self.assertNotEqual(rejected.returncode, 0)
        combined = (rejected.stdout + rejected.stderr).lower()
        self.assertIn("unproven", combined)
        self.assertIn("equiv_status -assert", combined)
        (root / "negative.stdout").write_text(rejected.stdout)
        (root / "negative.stderr").write_text(rejected.stderr)
        evidence = {
            "root": str(root), "gold": str(gold), "gate": str(gate), "top": "top", "seq": 5,
            "encrypt_command": encrypt_command, "decrypt_command": decrypt_command,
            "strict_compile": True, "byte_restore": True, "manifest": ["design.sv"],
            "aggregate_names": [{"original": r["original_name"], "renamed": r["renamed_name"]} for r in targets],
            "positive": positive, "oracle_gold": oracle_gold, "oracle_gate": oracle_gate,
            "frontend": frontend,
            "negative": {"command": command, "exit": rejected.returncode, "strict_compile": negative_compile,
                         "mutation": "4'ha -> 4'hb", "evidence": "unproven; equiv_status -assert"},
            "formal_scope": "compact nested named struct with real inner.field access; other shapes have only PySlang evidence",
        }
        (root / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
        print("T147_EVIDENCE=" + json.dumps(evidence, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
