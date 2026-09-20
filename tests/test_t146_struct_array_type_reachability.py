"""Fixed aggregate arrays: live semantic types and source-spelled references."""

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


ROOT = Path(__file__).resolve().parents[1]
PREFIX = """module top(input logic [3:0] a, b, output logic [3:0] y);
typedef struct packed {logic [3:0] field;} payload_t;
"""
FORMAL_SOURCE = "`default_nettype none\n" + PREFIX + """typedef payload_t array_t[0:1];
array_t word;
assign word[0] = a;
assign word[1] = b;
assign y = word[0] ^ word[1] ^ 4'ha;
endmodule
"""


def sources(root, code, *, extra=None, rewrite_roots=None):
    root.mkdir(parents=True, exist_ok=True)
    (root / "design.sv").write_text(code)
    for file, text in (extra or {}).items():
        target = root / file
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    units = ["design.sv", *(f for f in (extra or {}) if f.endswith(".sv"))]
    (root / "design.f").write_text("".join(f + "\n" for f in units))
    return from_filelist(filelist=root / "design.f", top="top",
                         rewrite_roots=rewrite_roots if rewrite_roots is not None else (root,))


class T146StructArrayTypeReachabilityTests(unittest.TestCase):
    def _one(self, index, name):
        record, = [s for s in index.symbols if s.category == "struct" and s.name == name]
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

    def test_active_fixed_arrays_and_alias_chains_bind_only_written_type_names(self):
        cases = {
            "unpacked": "payload_t word[2];",
            "packed": "payload_t[1:0] word;",
            "union": "payload_t word[2];",
            "multidimensional": "payload_t[1:0] word[2];",
            "alias_chain": "typedef payload_t array_t[2];\ntypedef array_t matrix_t[2];\nmatrix_t word;",
        }
        for case, declaration in cases.items():
            select = "word[0][0]" if case in {"multidimensional", "alias_chain"} else "word[0]"
            code = PREFIX + declaration + f"\nassign {select}.field = a;\nassign y = {select}.field;\nendmodule\n"
            if case == "union":
                code = code.replace("struct packed", "union packed")
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
                    self.assertFalse(any(s.name in {"array_t", "matrix_t"} for s in index.symbols))
                    self._audit(index, source)
                    self._roundtrip(root, source, index)

    def test_unused_alias_declarations_are_not_liveness_roots(self):
        for declaration in ("typedef payload_t scalar_t;", "typedef payload_t array_t[2];"):
            with self.subTest(declaration=declaration), tempfile.TemporaryDirectory() as temporary:
                source = sources(Path(temporary), PREFIX + declaration + "\nassign y = a;\nendmodule\n")
                index = ri.build_rename_index(build_source_catalog(source), categories=("all",))
                for name in ("payload_t", "field"):
                    self.assertEqual(self._one(index, name).reason, "outside_top_closure")

    def test_physical_names_and_parameter_specializations_stay_distinct(self):
        module = """module CELL #(parameter W=4)(input logic [W-1:0] a, output logic [W-1:0] y);
typedef struct packed {logic [W-1:0] field;} payload_t;
payload_t word[2];
assign word[0].field = a;
assign y = word[0].field;
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
            for name in ("payload_t", "field"):
                records = [r for r in index.symbols if r.category == "struct" and r.name == name]
                self.assertEqual(len(records), 2)
                self.assertEqual(len({r.symbol_id for r in records}), 2)
                self.assertTrue(all(r.support == "eligible" for r in records), records)
                for record in records:
                    boundary = code.index("module second")
                    section = 0 if record.declaration.start < boundary else 1
                    self.assertTrue(all((o.source_range.start < boundary) == (section == 0)
                                        for o in record.occurrences))
            self._audit(index, source)
            self._roundtrip(root, source, index)

    def test_top_selection_category_and_nested_field_boundaries(self):
        code = PREFIX + """typedef struct packed {payload_t inner;} outer_t;
outer_t word;
assign word = a;
assign y = word;
endmodule
module unused;
typedef struct packed {logic other_field;} other_t;
other_t other[2];
endmodule
"""
        with tempfile.TemporaryDirectory() as temporary:
            source = sources(Path(temporary), code)
            catalog = build_source_catalog(source)
            index = ri.build_rename_index(catalog, categories=("all",))
            for name in ("payload_t", "field", "other_t", "other_field"):
                self.assertEqual(self._one(index, name).reason, "outside_top_closure")
            signals = ri.build_rename_index(catalog, categories=("signals",))
            self.assertFalse(any(s.category == "struct" for s in signals.symbols))
            self._audit(index, source)

    def test_readonly_and_outside_root_type_references_preserve_the_record(self):
        cases = {
            "header": (PREFIX.replace("typedef struct packed {logic [3:0] field;} payload_t;",
                                      '`include "type.svh"') +
                       "payload_t word[2]; assign word[0].field=a; assign y=word[0].field; endmodule\n",
                       {"type.svh": "typedef struct packed {logic [3:0] field;} payload_t;\n"},
                       "readonly_include_file"),
            "outside": ("module top(input logic [3:0] a,b, output logic [3:0] y);\n"
                        "types::payload_t word[2]; assign word[0].field=a; assign y=word[0].field; endmodule\n",
                        {"own/types.sv": "package types; typedef struct packed {logic [3:0] field;} payload_t; endpackage\n"},
                        "outside_rewrite_root"),
        }
        for case, (code, extra, reason) in cases.items():
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                gold = root / "gold"
                if case == "outside":
                    (gold / "own").mkdir(parents=True)
                source = sources(gold, code, extra=extra,
                                 rewrite_roots=(gold / "own",) if case == "outside" else None)
                if case == "outside":
                    (gold / "design.f").write_text("own/types.sv\ndesign.sv\n")
                    source = from_filelist(filelist=gold / "design.f", top="top", rewrite_roots=(gold / "own",))
                index = ri.build_rename_index(build_source_catalog(source), categories=("all",))
                for name in ("payload_t", "field"):
                    self.assertEqual(self._one(index, name).reason, reason)
                self._audit(index, source)
                self._roundtrip(root, source, index)

    def test_array_getters_retry_without_cross_build_or_negative_cache(self):
        alias = type("TypeAliasType", (), {})()
        for error in (AttributeError, RuntimeError):
            state = {"reads": 0, "element": alias}

            def element(_self):
                state["reads"] += 1
                if state["reads"] == 1:
                    raise error("temporary element type failure")
                return state["element"]

            array = type("PackedArrayType", (), {"elementType": property(element)})()
            self.assertIsNone(ri._source_spelled_type_alias(array))
            self.assertIs(ri._source_spelled_type_alias(array), alias)
            state["element"] = NS()
            self.assertIsNone(ri._source_spelled_type_alias(array))
            # Cycles stop by wrapper identity and keep strong references.
            state["element"] = array
            self.assertIsNone(ri._source_spelled_type_alias(array))

        for kind in ("DynamicArrayType", "AssociativeArrayType", "QueueType"):
            array = type(kind, (), {"elementType": alias})()
            self.assertIsNone(ri._source_spelled_type_alias(array))

    def test_unknown_declared_nodes_keep_workset_reuse_and_retry_boundaries(self):
        array = type("FixedSizeUnpackedArrayType", (), {})()
        for shared in (True, False):
            counts = {"reads": 0}

            def declared(_self):
                counts["reads"] += 1
                return NS(type=array)

            node = type("FutureSemanticNode", (), {"declaredType": property(declared), "name": "future"})()
            catalog = (ri._OrderedSemanticNode(0, node),)
            top = catalog if shared else (ri._OrderedSemanticNode(10, node),)
            workset = ri._SemanticWorkset(catalog, top)
            self.assertEqual(counts["reads"], 1 if shared else 2)
            self.assertEqual(workset.top_type_nodes, (node,))
            self.assertIn(node, workset.occurrence_nodes)
            ri._SemanticWorkset(catalog, top)
            self.assertEqual(counts["reads"], 2 if shared else 4)

        for error in (AttributeError, RuntimeError):
            counts = {"reads": 0}

            def declared(_self):
                counts["reads"] += 1
                if counts["reads"] == 1:
                    raise error("temporary declared type failure")
                return NS(type=array)

            node = type("FutureSemanticNode", (), {"declaredType": property(declared)})()
            ordered = (ri._OrderedSemanticNode(0, node),)
            workset = ri._SemanticWorkset(ordered, ordered)
            self.assertEqual(counts["reads"], 2)
            self.assertEqual(workset.top_type_nodes, (node,))

    def test_alias_target_failures_retry_and_no_alias_declaration_root(self):
        leaf = type("TypeAliasType", (), {"targetType": NS(type=NS())})()
        for error in (AttributeError, RuntimeError):
            state = {"reads": 0, "value": leaf}

            def target(_self):
                state["reads"] += 1
                if state["reads"] == 1:
                    raise error("temporary alias target failure")
                return NS(type=state["value"])

            alias = type("TypeAliasType", (), {"targetType": property(target)})()
            array = type("PackedArrayType", (), {"elementType": alias})()
            future = type("FutureSemanticNode", (), {"declaredType": NS(type=array)})()
            keys = {id(alias): ("design.sv", 1, 2), id(leaf): ("design.sv", 3, 4)}
            with patch.object(ri, "_definition_key", side_effect=lambda _catalog, value, **_kw: keys[id(value)]):
                catalog = NS(top_root=object())
                first = ri._top_active_types(catalog, nodes=(future,))
                self.assertEqual(first, {keys[id(alias)]})
                second = ri._top_active_types(catalog, nodes=(future,))
                self.assertEqual(second, set(keys.values()))
                state["value"] = NS()
                self.assertEqual(ri._top_active_types(catalog, nodes=(future,)), first)
                alias.declaredType = NS(type=leaf)
                self.assertEqual(ri._top_active_types(catalog, nodes=(alias,)), set())

    def test_missing_source_token_cannot_create_alias_occurrence(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = sources(Path(temporary), FORMAL_SOURCE)
            catalog = build_source_catalog(source)
            with patch.object(ri, "_type_occurrence_range", return_value=None):
                index = ri.build_rename_index(catalog, categories=("all",))
            record = self._one(index, "payload_t")
            self.assertEqual(record.reason, "source_binding_incomplete")
            self.assertEqual(record.occurrences, ())
            self._audit(index, source)

    def test_failed_array_edge_keeps_complete_token_guard_even_with_live_scalar_use(self):
        code = PREFIX + """payload_t scalar_word;
payload_t array_word[2];
assign scalar_word.field = a;
assign y = scalar_word.field;
endmodule
"""
        with tempfile.TemporaryDirectory() as temporary:
            source = sources(Path(temporary), code)
            catalog = build_source_catalog(source)
            safe_attr = ri._safe_attr

            class BrokenArray:
                @property
                def elementType(self):
                    raise RuntimeError("element type unavailable")

            def damaged_attr(obj, attr, default=None):
                if type(obj).__name__ in ri._FIXED_ARRAY_TYPES and attr == "elementType":
                    return safe_attr(BrokenArray(), attr, default)
                return safe_attr(obj, attr, default)

            with patch.object(ri, "_safe_attr", side_effect=damaged_attr):
                index = ri.build_rename_index(catalog, categories=("all",))
            record = self._one(index, "payload_t")
            self.assertEqual(record.reason, "incomplete_name_coverage")
            self.assertEqual(len(record.occurrences), 1)
            self.assertEqual(record.occurrences[0].source_range.start, code.index("payload_t scalar_word"))
            self._audit(index, source)


    def _run(self, script, *args):
        command = [sys.executable, str(ROOT / script), *map(str, args)]
        run = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=120)
        return command, run

    def test_public_actual_gate_restore_and_formal_with_independent_vector_oracle(self):
        # Keep actual product output and every frontend warning for Main review.
        root = Path(tempfile.mkdtemp(prefix="t146-evidence-")).resolve()
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
        targets = [r for r in mapping["records"] if r["original_name"] in {"payload_t", "field"}]
        self.assertEqual(len(targets), 2)
        self.assertTrue(all(r["action"] == "rename" for r in targets), targets)
        self.assertEqual({r["file"] for r in mapping["input_manifest"]}, {"design.sv"})
        self._audit(ri.build_rename_index(build_source_catalog(source), categories=("all",)), source)
        gate_bytes = (gate / "design.sv").read_bytes()
        by_name = {record["original_name"]: record for record in targets}
        payload = by_name["payload_t"]
        field = by_name["field"]
        self.assertEqual(len(payload["occurrences"]), 1)
        self.assertEqual(len(field["occurrences"]), 0)
        self.assertFalse(any(r["original_name"] == "array_t" for r in mapping["records"]))
        self.assertIn(b"} " + payload["renamed_name"].encode() + b";", gate_bytes)
        self.assertIn(b"typedef " + payload["renamed_name"].encode() + b" array_t[0:1];", gate_bytes)
        self.assertIn(b"logic [3:0] " + field["renamed_name"].encode() + b";", gate_bytes)
        self.assertNotIn(b"payload_t", gate_bytes)
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
        sources(oracle, "module top(input logic [3:0] a, b, output logic [3:0] y); "
                        "assign y = a ^ b ^ 4'ha; endmodule\n")
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
            "formal_scope": "typedef-unpacked struct array; direct/packed/multidimensional arrays have only PySlang evidence",
        }
        (root / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
        print("T146_EVIDENCE=" + json.dumps(evidence, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
