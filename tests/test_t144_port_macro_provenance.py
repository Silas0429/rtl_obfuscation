"""T144: named port labels retain their real SourceManager provenance."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from rtl_obfuscator import rename_index as ri
from rtl_obfuscator.mapping_vnext import build_mapping_vnext
from rtl_obfuscator.rewrite_vnext import restore_gate_vnext, write_gate_vnext
from rtl_obfuscator.source_catalog import build_source_catalog
from rtl_obfuscator.source_set import from_filelist
from rtl_obfuscator.systemverilog_names import secure_name_factory


ROOT = Path(__file__).resolve().parents[1]
SHARED_FILES = {
    "lib/cells.sv": """module cell_a(input logic CLK, CEN, output logic Q);
  assign Q = CLK & CEN;
endmodule
module cell_b(input logic CLK, CEN, output logic Q);
  assign Q = CLK ^ CEN;
endmodule
""",
    "lib/wrapper.sv": """`define CELL(C,I,O) C I(.Q(O), .CLK(clk), .CEN(en));
module wrapper(input logic clk, en, output logic lib_result);
  wire qa, qb;
  `CELL(cell_a, a, qa)
  `CELL(cell_b, b, qb)
  assign lib_result = qa | qb;
endmodule
`undef CELL
""",
    "own/leaf.sv": """module own_leaf(input logic own_input, output logic own_output);
  assign own_output = ~own_input;
endmodule
""",
    "own/top.sv": """module top(input logic [2:0] stimulus, output logic result);
  wire own_wire, lib_wire;
  own_leaf leaf(.own_input(stimulus[0]), .own_output(own_wire));
  wrapper lib_inst(.clk(stimulus[1]), .en(stimulus[2]), .lib_result(lib_wire));
  assign result = own_wire ^ lib_wire;
endmodule
""",
}
CELL = """module leaf(input logic data_in, output logic data_out);
  assign data_out = ~data_in;
endmodule
"""
PROVENANCE_CASES = {
    "body": (
        """`define CONNECT(I,O) leaf I(.data_in(top_in), .data_out(O));
module top(input logic top_in, output logic top_out);
  wire first, second;
  `CONNECT(a,first)
  `CONNECT(b,second)
  assign top_out = first ^ second;
endmodule
""", "semantic_macro_body",
    ),
    "argument": (
        """`define CONNECT(I,P,Q,O) leaf I(.P(top_in), .Q(O));
module top(input logic top_in, output logic top_out);
  wire first, second;
  `CONNECT(a,data_in,data_out,first)
  `CONNECT(b,data_in,data_out,second)
  assign top_out = first ^ second;
endmodule
""", "semantic_macro_argument",
    ),
    "nested_body": (
        """`define INNER(I,O) leaf I(.data_in(top_in), .data_out(O));
`define OUTER(I,O) `INNER(I,O)
module top(input logic top_in, output logic top_out);
  `OUTER(a,top_out)
endmodule
""", "semantic_macro_body",
    ),
    "nested_argument": (
        """`define INNER(I,P,Q,O) leaf I(.P(top_in), .Q(O));
`define OUTER(I,P,Q,O) `INNER(I,P,Q,O)
module top(input logic top_in, output logic top_out);
  `OUTER(a,data_in,data_out,top_out)
endmodule
""", "semantic_macro_argument",
    ),
    "ordinary_label_macro_expression": (
        """`define VALUE(X) X
module top(input logic top_in, output logic top_out);
  leaf a(.data_in(`VALUE(top_in)), .data_out(top_out));
endmodule
""", "semantic_port_connection",
    ),
}


def _sources(root: Path, files: dict[str, str], *, own_only: bool = False):
    for file, source in files.items():
        path = root / file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)
    filelist = root / "design.f"
    filelist.write_text("".join(file + "\n" for file in files))
    return from_filelist(
        filelist=filelist, top="top",
        rewrite_roots=(root / "own",) if own_only else (root,),
    )


def _labels(catalog):
    nodes = []
    catalog.catalog_root.visit(nodes.append)
    return [
        connection.name
        for node in nodes
        if type(node).__name__ == "InstanceSymbol" and node.isModule
        for connection in ri._named_port_connection_syntax(node)
    ]


class T144PortMacroProvenanceTests(unittest.TestCase):
    def _record(self, index, name, owner="leaf"):
        found = [s for s in index.symbols if s.name == name and s.owner_module == owner]
        self.assertEqual(len(found), 1, (name, owner, found))
        return found[0]

    def _run(self, script, *args):
        command = [sys.executable, str(ROOT / script), *map(str, args)]
        run = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=120)
        return command, run

    def _audit_ranges(self, index, source_root):
        by_file = {}
        for symbol in index.symbols:
            for value in (symbol.declaration, *(o.source_range for o in symbol.occurrences)):
                data = (source_root / value.file).read_bytes()
                self.assertTrue(0 <= value.start < value.end <= len(data))
                self.assertEqual(data[value.start:value.end], symbol.name.encode())
                by_file.setdefault(value.file, []).append((value.start, value.end))
        for file, ranges in by_file.items():
            self.assertEqual(len(ranges), len(set(ranges)), file)
            ranges.sort()
            for left, right in zip(ranges, ranges[1:]):
                self.assertLessEqual(left[1], right[0], file)

    def test_shared_macro_retains_only_real_conflict_and_releases_own_ports(self):
        with tempfile.TemporaryDirectory(prefix="t144-shared-") as temporary:
            root = Path(temporary)
            source = _sources(root, SHARED_FILES, own_only=True)
            index = ri.build_rename_index(build_source_catalog(source), categories=("all",))
            for owner in ("cell_a", "cell_b"):
                for name in ("Q", "CLK", "CEN"):
                    record = self._record(index, name, owner)
                    self.assertEqual((record.support, record.reason),
                                     ("unsupported", "macro_origin_conflict"))
            for name in ("own_input", "own_output"):
                record = self._record(index, name, "own_leaf")
                self.assertEqual((record.support, record.reason), ("eligible", None))
            for name in ("stimulus", "result"):
                self.assertEqual(self._record(index, name, "top").reason, "selected_top_boundary")
            self.assertFalse(any(s.reason == "cross_record_range_conflict" for s in index.symbols))
            self._audit_ranges(index, source.source_root)

    def test_label_provenance_and_exact_physical_bytes_for_repeated_and_nested_macros(self):
        for case, (body, expected) in PROVENANCE_CASES.items():
            with self.subTest(case=case), tempfile.TemporaryDirectory(prefix="t144-label-") as temporary:
                root = Path(temporary)
                source = _sources(root / "source", {"design.sv": CELL + body})
                catalog = build_source_catalog(source)
                index = ri.build_rename_index(catalog, categories=("all",))
                manager = catalog.catalog_source_manager
                # Build an independent physical-label oracle directly from SourceManager.
                expected_labels = {}
                for token in _labels(catalog):
                    location = token.location
                    macro = manager.isMacroLoc(location)
                    provenance = ("semantic_macro_argument" if manager.isMacroArgLoc(location)
                                  else "semantic_macro_body") if macro else "semantic_port_connection"
                    self.assertEqual(provenance, expected)
                    physical = manager.getFullyOriginalLoc(location) if macro else location
                    expected_labels.setdefault(str(token.rawText), set()).add(int(physical.offset))
                for name in ("data_in", "data_out"):
                    record = self._record(index, name)
                    self.assertEqual(record.support, "eligible", record)
                    occurrences = [o for o in record.occurrences if o.source_range.start in expected_labels[name]]
                    self.assertEqual({o.source_range.start for o in occurrences}, expected_labels[name])
                    self.assertTrue(all(o.provenance == expected for o in occurrences), occurrences)
                self._audit_ranges(index, source.source_root)
                mapping = build_mapping_vnext(index, name_length=20, name_factory=secure_name_factory)
                execution = write_gate_vnext(mapping, output_dir=root / "gate")
                report = restore_gate_vnext(execution, gate_dir=root / "gate", output_dir=root / "restore")
                self.assertTrue(report.to_report()["summary"]["byte_identical"])
                self.assertEqual((root / "restore/design.sv").read_bytes(), (root / "source/design.sv").read_bytes())
                original = (root / "source/design.sv").read_bytes()
                edits = []
                for record in mapping.records:
                    if record.action == "rename":
                        for value in (record.declaration, *(o.source_range for o in record.occurrences)):
                            edits.append((value.start, value.end, record.renamed_name.encode()))
                expected_gate = original
                for start, end, renamed in sorted(edits, reverse=True):
                    expected_gate = expected_gate[:start] + renamed + expected_gate[end:]
                self.assertNotEqual(expected_gate, original)
                self.assertEqual((root / "gate/design.sv").read_bytes(), expected_gate)

    def test_ordinary_shorthand_keeps_unknown_cross_record_rule(self):
        code = """module leaf(input logic data_in, output logic data_out);
  assign data_out = ~data_in;
endmodule
module top(input logic stimulus, output logic result);
  wire data_in = stimulus;
  wire data_out;
  wire unrelated = stimulus;
  leaf a(.data_in, .data_out);
  assign result = data_out ^ unrelated;
endmodule
"""
        with tempfile.TemporaryDirectory(prefix="t144-shorthand-") as temporary:
            root = Path(temporary)
            source = _sources(root, {"design.sv": code})
            index = ri.build_rename_index(build_source_catalog(source), categories=("all",))
            for name, owner in (("data_in", "leaf"), ("data_out", "leaf"),
                                ("data_in", "top"), ("data_out", "top"), ("unrelated", "top")):
                record = self._record(index, name, owner)
                self.assertEqual((record.support, record.reason),
                                 ("preserved", "cross_record_range_conflict"))

    def test_missing_or_failed_source_manager_origin_is_fail_closed(self):
        for method, case in (("isMacroLoc", "ordinary_label_macro_expression"),
                             ("isMacroArgLoc", "body"), ("getFullyOriginalLoc", "argument")):
            for missing in (False, True):
                with self.subTest(method=method, missing=missing), tempfile.TemporaryDirectory(prefix="t144-failure-") as temporary:
                    root = Path(temporary)
                    source = _sources(root, {"design.sv": CELL + PROVENANCE_CASES[case][0]})
                    catalog = build_source_catalog(source)
                    locations = {(t.location.buffer, t.location.offset) for t in _labels(catalog)
                                 if str(t.rawText) == "data_in"}
                    manager = catalog.catalog_source_manager

                    class BrokenManager:
                        def __getattr__(self, attr):
                            if attr == method and missing:
                                raise AttributeError("injected missing " + method)
                            value = getattr(manager, attr)
                            if attr != method:
                                return value
                            def checked(location):
                                if (location.buffer, location.offset) in locations:
                                    raise RuntimeError("injected " + method + " origin failure")
                                return value(location)
                            return checked

                    collect = ri._collect_occurrences
                    def damaged_collect(actual_catalog, *args, **kwargs):
                        return collect(replace(actual_catalog, catalog_source_manager=BrokenManager()), *args, **kwargs)
                    with patch.object(ri, "_collect_occurrences", side_effect=damaged_collect):
                        index = ri.build_rename_index(catalog, categories=("ports",))
                    record = self._record(index, "data_in")
                    self.assertEqual((record.support, record.reason),
                                     ("preserved", "source_binding_incomplete"))
                    sibling = self._record(index, "data_out")
                    if missing:
                        self.assertEqual((sibling.support, sibling.reason),
                                         ("preserved", "source_binding_incomplete"))
                    else:
                        self.assertEqual(sibling.support, "eligible")
                    issues = next(o["issues"] for o in index.category_outcomes if o["category"] == "ports")
                    self.assertTrue(any(i["message"] == "source_binding_incomplete" and i.get("name") == "data_in"
                                        for i in issues), issues)

    def test_public_actual_gate_manifest_restore_and_formal_positive_negative(self):
        # Retain this compact evidence tree for the Main Agent's independent rerun.
        root = Path(tempfile.mkdtemp(prefix="t144-evidence-")).resolve()
        gold = root / "gold"
        gold.mkdir()
        source = _sources(gold, SHARED_FILES, own_only=True)
        gate = root / "gate"
        encrypt_command, encrypted = self._run(
            "rtl_encrypt.py", "--filelist", gold / "design.f", "--top", "top",
            "--rewrite-root", gold / "own", "--category", "all", "--output-dir", gate, "--quiet",
        )
        self.assertEqual(encrypted.returncode, 0, encrypted.stdout + encrypted.stderr)
        payload = json.loads(encrypted.stdout)
        summary = payload["summary"]
        self.assertTrue(summary["strict_compile_passed"])
        self.assertTrue(summary["restored_byte_identical"])
        mapping = json.loads((gate / "mapping.json").read_text())["mapping"]
        target_records = [r for r in mapping["records"] if r["original_name"] in {"own_input", "own_output"}]
        self.assertEqual(len(target_records), 2)
        self.assertTrue(all(r["action"] == "rename" for r in target_records), target_records)
        self.assertEqual({e["file"] for e in mapping["input_manifest"]}, set(SHARED_FILES))
        self._audit_ranges(ri.build_rename_index(build_source_catalog(source), categories=("all",)), gold)
        for file, original in SHARED_FILES.items():
            edits = []
            for record in mapping["records"]:
                if record["action"] != "rename":
                    continue
                for value in (record["declaration"], *(o["source_range"] for o in record["occurrences"])):
                    if value["file"] == file:
                        edits.append((value["start"], value["end"], record["renamed_name"].encode()))
            expected = original.encode()
            for start, end, renamed in sorted(edits, reverse=True):
                expected = expected[:start] + renamed + expected[end:]
            self.assertEqual((gate / file).read_bytes(), expected)
            if file.startswith("lib/"):
                self.assertEqual(expected, original.encode())
        for record in target_records:
            self.assertNotEqual(record["renamed_name"], record["original_name"])
            self.assertIn(record["renamed_name"].encode(), (gate / "own/leaf.sv").read_bytes())
            self.assertIn(("." + record["renamed_name"] + "(").encode(), (gate / "own/top.sv").read_bytes())
        restore = root / "restore"
        decrypt_command, decrypted = self._run(
            "rtl_decrypt.py", "--gate-dir", gate, "--map", gate / "mapping.json", "--output-dir", restore,
        )
        self.assertEqual(decrypted.returncode, 0, decrypted.stdout + decrypted.stderr)
        for file in SHARED_FILES:
            self.assertEqual((restore / file).read_bytes(), (gold / file).read_bytes(), file)
        formal_args = ("--gold-filelist", gate / "original_design.f", "--gold-root", gold,
                       "--gate-filelist", gate / "design.f", "--gate-root", gate, "--top", "top", "--seq", "5")
        positive_command, positive = self._run("scripts/formal_equivalence.py", *formal_args)
        self.assertEqual(positive.returncode, 0, positive.stdout + positive.stderr)
        positive_json = json.loads(positive.stdout.strip().splitlines()[-1])
        self.assertEqual(positive_json["formal_equivalence"], "pass")
        negative = root / "negative"
        shutil.copytree(gate, negative)
        # Published design.f uses absolute paths: rebuild this diagnostic filelist
        # from the exact copied physical inputs, never prove the unchanged gate.
        (negative / "design.f").write_text("".join(str(negative / f) + "\n" for f in SHARED_FILES))
        target = negative / "own/top.sv"
        original = target.read_bytes()
        self.assertEqual(original.count(b" ^ "), 1)
        target.write_bytes(original.replace(b" ^ ", b" | ", 1))
        negative_source = from_filelist(filelist=negative / "design.f", top="top")
        self.assertEqual(negative_source.source_root, negative)
        self.assertEqual(
            tuple((negative_source.source_root / f).resolve() for f in negative_source.ordered_source_files),
            tuple(negative / f for f in SHARED_FILES),
        )
        negative_compile = build_source_catalog(negative_source).to_report()["compile"]
        self.assertEqual(negative_compile, {
            "catalog": {"parse_errors": 0, "semantic_errors": 0},
            "top_overlay": {"parse_errors": 0, "semantic_errors": 0},
        })
        negative_command, rejected = self._run(
            "scripts/formal_equivalence.py", "--gold-filelist", gold / "design.f", "--gold-root", gold,
            "--gate-filelist", negative / "design.f", "--gate-root", negative, "--top", "top", "--seq", "5",
        )
        self.assertNotEqual(rejected.returncode, 0)
        combined = (rejected.stdout + rejected.stderr).lower()
        self.assertIn("unproven", combined)
        self.assertIn("equiv_status -assert", combined)
        (root / "formal-negative.stdout").write_text(rejected.stdout)
        (root / "formal-negative.stderr").write_text(rejected.stderr)
        evidence = {
            "gold": str(gold), "gate": str(gate), "top": "top", "seq": 5,
            "encrypt_command": encrypt_command, "decrypt_command": decrypt_command,
            "strict_compile": True, "byte_restore": True, "physical_manifest": sorted(SHARED_FILES),
            "target_ports": [{"original": r["original_name"], "renamed": r["renamed_name"]} for r in target_records],
            "positive": {"command": positive_command, "exit": positive.returncode, "json": positive_json},
            "negative": {"command": negative_command, "exit": rejected.returncode, "strict_compile": negative_compile,
                         "mutation": "own/top.sv sole XOR -> OR", "evidence": "unproven; equiv_status -assert"},
        }
        (root / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
        print("T144_EVIDENCE=" + json.dumps(evidence, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
