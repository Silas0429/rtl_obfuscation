"""T145: bind simple modport value references to their physical member."""

from pathlib import Path
import json
import re
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from rtl_obfuscator import rename_index as ri
from rtl_obfuscator.mapping_vnext import build_mapping_vnext
from rtl_obfuscator.rewrite_vnext import restore_gate_vnext, write_gate_vnext
from rtl_obfuscator.source_catalog import build_source_catalog
from rtl_obfuscator.source_set import from_filelist
from rtl_obfuscator.systemverilog_names import secure_name_factory


ROOT = Path(__file__).resolve().parents[1]
FORMAL_SOURCE = """interface bus_if;
logic [3:0] req;
logic [3:0] ack;
modport sink(input req, output ack);
endinterface
module consumer(bus_if.sink bus);
assign bus.ack = bus.req ^ 4'ha;
endmodule
module top(input logic [3:0] a, output logic [3:0] y);
bus_if link();
consumer u(.bus(link));
assign link.req = a;
assign y = link.ack;
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


class T145ModportMemberReferencesTests(unittest.TestCase):
    def _member(self, index, name):
        record, = [s for s in index.symbols if s.kind == "interface_member" and s.name == name]
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

    def test_simple_named_and_positional_members_are_complete(self):
        for connection in (".bus(link)", "link"):
            with self.subTest(connection=connection), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                code = FORMAL_SOURCE.replace(".bus(link)", connection)
                source = sources(root / "gold", code)
                index = ri.build_rename_index(build_source_catalog(source), categories=("all",))
                for name in ("req", "ack"):
                    record = self._member(index, name)
                    self.assertEqual((record.support, record.reason), ("eligible", None))
                    # Independent compact source oracle: every spelling belongs to
                    # this physical member, including declaration and modport list.
                    expected = {m.start() for m in re.finditer(r"\b" + name + r"\b", code)}
                    self.assertEqual({record.declaration.start,
                                      *(o.source_range.start for o in record.occurrences)}, expected)
                    self.assertIn("semantic_modport_member", {o.provenance for o in record.occurrences})
                    self.assertEqual(record.semantic_kind, "VariableSymbol")
                self.assertFalse(any(s.kind == "modport_member" for s in index.symbols))
                self.assertEqual(next(s for s in index.symbols if s.name == "link").reason,
                                 "hierarchical_prefix_unsupported")
                self._audit(index, source)
                self._roundtrip(root, source, index)

    def test_array_port_nonansi_and_plain_interface_preserve_direct_identity(self):
        cases = {
            "array_port": FORMAL_SOURCE.replace("sink bus)", "sink bus[2])")
                .replace("bus.", "bus[0].").replace("link();", "link[2]();")
                .replace("link.req", "link[0].req").replace("link.ack", "link[0].ack"),
            "nonansi": FORMAL_SOURCE.replace("module consumer(bus_if.sink bus);",
                                              "module consumer(bus);\nbus_if.sink bus;"),
            "plain": FORMAL_SOURCE.replace("bus_if.sink bus", "bus_if bus"),
        }
        for case, code in cases.items():
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source = sources(root / "gold", code)
                index = ri.build_rename_index(build_source_catalog(source), categories=("all",))
                for name in ("req", "ack"):
                    record = self._member(index, name)
                    self.assertEqual(record.support, "eligible", record)
                    self.assertEqual(len(record.occurrences), 3)
                self._audit(index, source)
                self._roundtrip(root, source, index)

    def test_vector_selects_and_explicit_modport_expressions_remain_guarded(self):
        cases = {
            "select": FORMAL_SOURCE.replace("bus.ack = bus.req",
                        "bus.ack[3:0] = {bus.req[3:1], bus.req[0]}"),
            "alias": FORMAL_SOURCE.replace("input req", "input .rx(req)").replace("bus.req", "bus.rx"),
            "alias_select": FORMAL_SOURCE.replace("input req", "input .rx(req[0])").replace("bus.req", "bus.rx"),
        }
        for case, code in cases.items():
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source = sources(root / "gold", code)
                index = ri.build_rename_index(build_source_catalog(source), categories=("all",))
                self.assertEqual(self._member(index, "req").reason, "incomplete_name_coverage")
                if case == "select":
                    self.assertEqual(self._member(index, "ack").reason, "incomplete_name_coverage")
                else:
                    self.assertEqual(self._member(index, "ack").support, "eligible")
                    self.assertFalse(any(s.name == "rx" for s in index.symbols))
                self._audit(index, source)
                self._roundtrip(root, source, index)

    def test_same_spelling_members_do_not_merge_and_all_releases_unrelated_signal(self):
        other = """interface other_if;
logic [3:0] req;
logic [3:0] ack;
modport sink(input req, output ack);
endinterface
module other_consumer(other_if.sink bus);
assign bus.ack = ~bus.req;
endmodule
module peer(input logic [3:0] p, output logic [3:0] q);
logic [3:0] req;
assign req = p;
assign q = req;
endmodule
"""
        code = other + FORMAL_SOURCE.replace("consumer u(.bus(link));", """consumer u(.bus(link));
other_if other_link();
other_consumer other_u(.bus(other_link));
assign other_link.req = a;
wire [3:0] ignored;
peer peer_u(.p(other_link.ack), .q(ignored));""")
        with tempfile.TemporaryDirectory() as temporary:
            source = sources(Path(temporary), code)
            catalog = build_source_catalog(source)
            index = ri.build_rename_index(catalog, categories=("all",))
            for name in ("req", "ack"):
                members = [s for s in index.symbols if s.kind == "interface_member" and s.name == name]
                self.assertEqual(len(members), 2)
                self.assertEqual(len({s.symbol_id for s in members}), 2)
                self.assertTrue(all(s.support == "eligible" for s in members))
                first, second = sorted(members, key=lambda s: s.declaration.start)
                # The two interface definitions have distinct source sections;
                # their consumer references must remain attached to that section.
                self.assertTrue(any(o.source_range.start < code.index("module peer") for o in first.occurrences))
                self.assertTrue(all(o.source_range.start > code.index("interface bus_if") for o in second.occurrences))
            signal, = [s for s in index.symbols if s.category == "signals" and s.name == "req"]
            self.assertEqual(signal.support, "eligible")
            signals_only = ri.build_rename_index(catalog, categories=("signals",))
            self.assertEqual(next(s for s in signals_only.symbols if s.name == "req").support, "eligible")
            self._audit(index, source)

    def test_unavailable_different_or_sourceless_internal_target_never_creates_occurrences(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = sources(Path(temporary), FORMAL_SOURCE)
            catalog = build_source_catalog(source)
            safe_attr = ri._safe_attr
            for failure in ("missing", "raises", "different", "sourceless"):
                with self.subTest(failure=failure):
                    def damaged_attr(obj, attr, default=None):
                        if type(obj).__name__ == "ModportPortSymbol" and attr == "internalSymbol":
                            if failure in {"missing", "raises"}:
                                class Broken:
                                    @property
                                    def internalSymbol(self):
                                        if failure == "missing":
                                            raise AttributeError("missing internal symbol")
                                        raise RuntimeError("internal symbol unavailable")
                                return safe_attr(Broken(), attr, default)
                            return SimpleNamespace(name="different" if failure == "different" else obj.name)
                        return safe_attr(obj, attr, default)
                    with patch.object(ri, "_safe_attr", side_effect=damaged_attr):
                        index = ri.build_rename_index(catalog, categories=("all",))
                    for name in ("req", "ack"):
                        record = self._member(index, name)
                        self.assertEqual(record.reason, "incomplete_name_coverage")
                        # The existing declaration path remains independent:
                        # modport list + direct link, never the failed bus target.
                        self.assertEqual(len(record.occurrences), 2)
                    self._audit(index, source)

    def test_readonly_header_and_outside_root_references_still_preserve_members(self):
        interface, module = FORMAL_SOURCE.split("module consumer", 1)
        consumer, top = ("module consumer" + module).split("module top", 1)
        cases = {
            "header": ("`include \"bus.svh\"\n" + consumer + "module top" + top,
                       {"bus.svh": interface}, None, "readonly_include_file"),
            "outside": (interface + "module top" + top,
                        {"outside/consumer.sv": consumer}, "own", "outside_rewrite_root"),
        }
        for case, (code, extra, scope, reason) in cases.items():
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                if scope:
                    # Two source units, with declarations and direct references
                    # inside the root but modport use in the external consumer.
                    own = root / "own"
                    own.mkdir()
                    (own / "design.sv").write_text(code)
                    (root / "consumer.sv").write_text(consumer)
                    (root / "design.f").write_text("own/design.sv\nconsumer.sv\n")
                    source = from_filelist(filelist=root / "design.f", top="top", rewrite_roots=(own,))
                else:
                    source = sources(root, code, extra=extra)
                index = ri.build_rename_index(build_source_catalog(source), categories=("all",))
                for name in ("req", "ack"):
                    self.assertEqual(self._member(index, name).reason, reason)
                self._audit(index, source)

    def test_global_modport_declaration_getter_error_aborts_instead_of_downgrading(self):
        with tempfile.TemporaryDirectory() as temporary:
            catalog = build_source_catalog(sources(Path(temporary), FORMAL_SOURCE))
            collect = ri._collect_occurrences

            class ModportPortSymbol:
                def __init__(self, original):
                    self.original = original

                def __getattr__(self, name):
                    if name == "internalSymbol":
                        raise RuntimeError("global modport internal getter failure")
                    return getattr(self.original, name)

            def damaged_collect(actual_catalog, nodes, *args, **kwargs):
                nodes = [ModportPortSymbol(n) if type(n).__name__ == "ModportPortSymbol" else n
                         for n in nodes]
                return collect(actual_catalog, nodes, *args, **kwargs)

            with patch.object(ri, "_collect_occurrences", side_effect=damaged_collect):
                with self.assertRaisesRegex(RuntimeError, "global modport internal getter failure"):
                    ri.build_rename_index(catalog, categories=("all",))

    def _run(self, script, *args):
        command = [sys.executable, str(ROOT / script), *map(str, args)]
        run = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=120)
        return command, run

    def test_public_actual_gate_restore_and_formal_with_independent_vector_oracle(self):
        # Keep actual product output and every frontend warning for Main review.
        root = Path(tempfile.mkdtemp(prefix="t145-evidence-")).resolve()
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
        targets = [r for r in mapping["records"] if r["original_name"] in {"req", "ack"}]
        self.assertEqual(len(targets), 2)
        self.assertTrue(all(r["action"] == "rename" for r in targets), targets)
        self.assertEqual({r["file"] for r in mapping["input_manifest"]}, {"design.sv"})
        self._audit(ri.build_rename_index(build_source_catalog(source), categories=("all",)), source)
        gate_bytes = (gate / "design.sv").read_bytes()
        for record in targets:
            name = record["renamed_name"].encode()
            self.assertNotEqual(name, record["original_name"].encode())
            self.assertIn(b"logic [3:0] " + name + b";", gate_bytes)
            self.assertIn(b"bus." + name, gate_bytes)
            self.assertIn(b"link." + name, gate_bytes)
            self.assertEqual(len(record["occurrences"]), 3)
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
            "members": [{"original": r["original_name"], "renamed": r["renamed_name"]} for r in targets],
            "positive": positive, "oracle_gold": oracle_gold, "oracle_gate": oracle_gate,
            "frontend": frontend,
            "negative": {"command": command, "exit": rejected.returncode, "strict_compile": negative_compile,
                         "mutation": "4'ha -> 4'hb", "evidence": "unproven; equiv_status -assert"},
            "formal_scope": "named scalar modport; arrays/position/selects have only PySlang evidence",
        }
        (root / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
        print("T145_EVIDENCE=" + json.dumps(evidence, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
