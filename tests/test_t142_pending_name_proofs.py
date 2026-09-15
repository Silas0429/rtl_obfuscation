"""Main-Agent frozen behavior, extension and work-count oracles for T142."""

import copy
import json
from pathlib import Path
import random
import subprocess
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

import rtl_obfuscator.rename_index as ri
from rtl_obfuscator.orchestration_vnext import run_vnext
from rtl_obfuscator.source_catalog import build_source_catalog
from rtl_obfuscator.source_set import from_filelist
from tests.test_t128_rename_index_range_cache import _decision_projection

ROOT = Path(__file__).resolve().parents[1]


def _full_proof_oracle(catalog, nodes, syntax_nodes, records, *, context=None):
    """Pre-T142 set equation; retains the original full proof work as oracle.

    Uses the canonical evidence providers, so changing their rules affects both
    implementations. This deliberately never calls the optimized coordinator.
    """
    eligible = tuple(r for r in records.values() if r.support == "eligible" and r.name)
    wanted = frozenset(r.name for r in eligible)
    if not wanted:
        return
    if context is None:
        context = ri._RangePathContext.for_catalog(catalog)
    tokens, unverified = ri._tokens_spelling(catalog, syntax_nodes, wanted, context)
    accounted = set()
    for record in records.values():
        if record.name in wanted:
            ranges = (record.declaration, *(o.source_range for o in record.occurrences.values()))
            accounted.update((r.file, r.start, r.end) for r in ranges)
    rewritten = frozenset(
        (r.file, r.start) for record in eligible
        for r in (record.declaration, *(o.source_range for o in record.occurrences.values()))
    )
    by_start = {(t.file, t.start): t for t in tokens}
    accounted |= ri._declaration_attributions(catalog, nodes, by_start, wanted, context)
    stats = ri._ReferenceQueryStats()
    accounted |= ri._reference_attributions(
        tokens, ri._reference_spans(catalog, nodes, wanted, context), rewritten, stats,
    )
    context.reference_candidate_checks += stats.candidate_checks
    incomplete = set(unverified)
    incomplete.update(t.name for t in tokens if (t.file, t.start, t.end) not in accounted)
    for record in records.values():
        if record.support == "eligible" and record.name in incomplete:
            record.support = "preserved"
            record.reason = "incomplete_name_coverage"


def _range(start, end=None):
    return NS(file="x.sv", start=start, end=start + 1 if end is None else end)


def _record(name, start, *, support="eligible", reason=None, occurrences=(), category="future_kind"):
    return NS(name=name, declaration=_range(start), support=support, reason=reason,
              category=category, occurrences={i: NS(source_range=_range(*r)) for i, r in enumerate(occurrences)})


def _factory():
    serial = iter(range(1, 100000))
    return lambda _sid, length, _unavailable: "zz" + str(next(serial)).zfill(length - 2)


class T142PendingNameProofTests(unittest.TestCase):
    def _synthetic(self, function, records, tokens, *, unverified=frozenset(), declarations=frozenset(), references=None):
        records = copy.deepcopy(records)
        calls = {"tokens": [], "declarations": [], "references": [], "rewritten": []}

        def spelling(_catalog, _syntax, wanted, _context):
            calls["tokens"].append(wanted)
            return tuple(t for t in tokens if t.name in wanted), unverified & wanted

        def declarations_for(_catalog, _nodes, by_start, wanted, _context):
            calls["declarations"].append((dict(by_start), wanted))
            return {(t.file, t.start, t.end) for t in by_start.values()
                    if t.name in wanted and (t.file, t.start) in declarations}

        def spans(_catalog, _nodes, wanted, _context):
            calls["references"].append(wanted)
            return {key: values for key, values in (references or {}).items() if key[1] in wanted}

        original_query = ri._reference_attributions

        def query(tokens, refs, rewritten, stats):
            calls["rewritten"].append(rewritten)
            return original_query(tokens, refs, rewritten, stats)

        with patch.object(ri, "_tokens_spelling", side_effect=spelling), \
             patch.object(ri, "_declaration_attributions", side_effect=declarations_for), \
             patch.object(ri, "_reference_spans", side_effect=spans), \
             patch.object(ri, "_reference_attributions", side_effect=query):
            function(None, [], [], records, context=NS(reference_candidate_checks=0))
        return records, calls

    def test_no_pending_skips_both_supplemental_walks_but_keeps_unverified(self):
        tokens = (ri._NameToken("x.sv", 10, 11, "same"),)
        records = {"new-category": _record("same", 10),
                   "prior": _record("same", 10, support="preserved", reason="unelaborated_reference")}
        for unverified in (frozenset(), frozenset({"same"})):
            with self.subTest(unverified=unverified):
                expected, _ = self._synthetic(_full_proof_oracle, records, tokens, unverified=unverified)
                actual, calls = self._synthetic(ri._apply_name_completeness, records, tokens, unverified=unverified)
                self.assertEqual(actual, expected)
                self.assertEqual(calls["tokens"], [frozenset({"same"})])
                self.assertEqual(calls["declarations"], [])
                self.assertEqual(calls["references"], [])

    def test_partial_proof_preserves_complete_rewritten_target_set(self):
        tokens = tuple(ri._NameToken("x.sv", start, start+1, name)
                       for start, name in ((10,"done"), (20,"left"), (30,"left"), (40,"left")))
        records = {"done": _record("done",10), "left": _record("left",20)}
        refs = {("x.sv", "left"): [ri._NameReference(40,41,("x.sv",10))]}
        actual,calls = self._synthetic(ri._apply_name_completeness, records,tokens,
                                     declarations={("x.sv",30)},references=refs)
        expected,_ = self._synthetic(_full_proof_oracle, records,tokens,
                                    declarations={("x.sv",30)},references=refs)
        self.assertEqual(actual,expected)
        self.assertEqual(calls["declarations"][0][1],frozenset({"left"}))
        self.assertEqual(set(calls["declarations"][0][0]),{("x.sv",30),("x.sv",40)})
        self.assertEqual(calls["references"],[frozenset({"left"})])
        self.assertEqual(calls["rewritten"],[frozenset({("x.sv",10),("x.sv",20)})])
        self.assertEqual(actual["left"].reason,"incomplete_name_coverage")

    def test_added_candidates_and_changed_admission_are_recomputed(self):
        tokens = tuple(ri._NameToken("x.sv", start,start+1,name)
                       for start,name in ((10,"old"),(20,"added"),(30,"added")))
        initial = {"old":_record("old",10)}
        expanded = dict(initial, added=_record("added",20))
        restricted = dict(initial, added=_record("added",20,support="preserved",reason="new_policy"))
        admitted_with_proof = dict(initial, added=_record("added",20,occurrences=((30,31),)))
        for records in (initial,expanded,restricted,admitted_with_proof,expanded):
            with self.subTest(records=records):
                expected,_ = self._synthetic(_full_proof_oracle,records,tokens)
                actual,calls = self._synthetic(ri._apply_name_completeness,records,tokens)
                self.assertEqual(actual,expected)
                self.assertEqual(calls["tokens"],[frozenset(r.name for r in records.values() if r.support=="eligible")])
        actual,_ = self._synthetic(ri._apply_name_completeness,expanded,tokens)
        self.assertEqual(actual["added"].support,"preserved")
        actual,_ = self._synthetic(ri._apply_name_completeness,admitted_with_proof,tokens)
        self.assertEqual(actual["added"].support,"eligible")

    def test_same_start_and_nonmonotonic_end_match_full_oracle(self):
        rng = random.Random(142)
        for number in range(200):
            # Deliberately includes duplicate starts and exotic overlapping ends.
            tokens = tuple(ri._NameToken("x.sv", start, start+rng.randrange(1,12),"same")
                           for start in [10,10,20,30,40])
            records={"r":_record("same",100,occurrences=tuple((t.start,t.end) for t in tokens if rng.choice((True,False))))}
            refs={("x.sv","same"):[ri._NameReference(rng.randrange(0,25),rng.randrange(35,65),("x.sv",rng.choice((1,2,100)))) for _ in range(6)]}
            declared={("x.sv",start) for start in (10,20,30,40) if rng.choice((True,False))}
            expected,_=self._synthetic(_full_proof_oracle,records,tokens,declarations=declared,references=refs)
            actual,_=self._synthetic(ri._apply_name_completeness,records,tokens,declarations=declared,references=refs)
            self.assertEqual(actual,expected,number)

    def test_policy_change_updates_edited_targets_even_for_accounted_names(self):
        tokens=(ri._NameToken("x.sv",10,11,"done"),ri._NameToken("x.sv",20,21,"left"),
                ri._NameToken("x.sv",40,41,"left"))
        refs={("x.sv","left"):[ri._NameReference(40,41,("x.sv",50))]}
        for support in ("eligible","preserved","eligible"):
            records={"done":_record("done",10,support=support,reason="policy" if support=="preserved" else None,
                                    occurrences=((50,51),)),"left":_record("left",20)}
            actual,_=self._synthetic(ri._apply_name_completeness,records,tokens,references=refs)
            expected,_=self._synthetic(_full_proof_oracle,records,tokens,references=refs)
            self.assertEqual(actual,expected)
            self.assertEqual(actual["left"].support,"preserved" if support=="eligible" else "eligible")

    def test_real_fixtures_and_category_choices_match_full_oracle(self):
        cases=[("tests/fixtures/t108_pyslang_rename_index/design.f","top"),
               ("tests/fixtures/t108_pyslang_rename_index/macro_interface.f","macro_interface_top"),
               ("tests/fixtures/t108_pyslang_rename_index/server_shapes.f","t108_shape_top"),
               ("tests/fixtures/t113_unelaborated_reference/design.f","t113_top"),
               ("tests/fixtures/t115_name_completeness/design.f","t115_top"),
               ("rtl_samples/example_fifo/design.f","fifo_top")]
        for relative,top in cases:
            filelist=ROOT/relative
            for scoped in (False,True):
                catalog=build_source_catalog(from_filelist(filelist=filelist,top=top,rewrite_roots=(filelist.parent,) if scoped else ()))
                for categories in (("signals",),("all",)):
                    with self.subTest(relative=relative,scoped=scoped,categories=categories):
                        with patch.object(ri,"_apply_name_completeness",new=_full_proof_oracle):
                            expected=ri.build_rename_index(catalog,categories=categories)
                        actual=ri.build_rename_index(catalog,categories=categories)
                        self.assertEqual(_decision_projection(actual),_decision_projection(expected))

    def test_generic_declaration_provider_remains_extensible(self):
        # A future aggregate shape can add evidence without coordinator changes.
        member=NS(name="future",location=("x.sv",30))
        tokens=(ri._NameToken("x.sv",10,11,"future"),ri._NameToken("x.sv",30,31,"future"))
        for extra_members in ([],[member],[]):
            records={"new":_record("future",10)}
            with patch.object(ri,"_tokens_spelling",return_value=(tokens,frozenset())), \
                 patch.object(ri,"_aggregate_field_symbols",return_value=extra_members) as walk, \
                 patch.object(ri,"_physical_declaration_key",side_effect=lambda _c,loc,_ctx:loc), \
                 patch.object(ri,"_reference_spans",return_value={}):
                ri._apply_name_completeness(None,[NS(name="carrier")],[],records,context=NS(reference_candidate_checks=0))
            self.assertEqual(records["new"].support,"eligible" if extra_members else "preserved")
            walk.assert_called_once()

    def test_actual_gate_full_mapping_restore_and_formal(self):
        code="""module proof_leaf(input logic [3:0] data_i, output logic [3:0] data_o);
  logic [3:0] internal_value;
  assign internal_value = data_i ^ 4'b1010;
  assign data_o = internal_value;
endmodule
module proof_top(input logic [3:0] data_i, output logic [3:0] data_o);
  logic [3:0] intermediate;
  proof_leaf child(.data_i(data_i), .data_o(intermediate));
  assign data_o = intermediate;
endmodule
"""
        with tempfile.TemporaryDirectory(prefix="t142-full-") as temp:
            root=Path(temp); source_dir=root/"source";source_dir.mkdir()
            gold=source_dir/"design.sv";gold.write_text(code)
            (source_dir/"design.f").write_text("design.sv\n")
            source=from_filelist(filelist=source_dir/"design.f",top="proof_top",rewrite_roots=(source_dir,))
            with patch.object(ri,"_apply_name_completeness",new=_full_proof_oracle):
                baseline=run_vnext(source,categories=("all",),name_factory=_factory(),name_length=20,
                                   gate_dir=root/"baseline",restore_dir=root/"baseline-restore")
            result=run_vnext(source,categories=("all",),name_factory=_factory(),name_length=20,
                             gate_dir=root/"gate",restore_dir=root/"restore")
            gate=root/"gate/design.sv"
            self.assertEqual(result.mapping_vnext.to_report(),baseline.mapping_vnext.to_report())
            self.assertEqual(gate.read_bytes(),(root/"baseline/design.sv").read_bytes())
            self.assertNotEqual(gate.read_bytes(),gold.read_bytes())
            self.assertEqual((root/"restore/design.sv").read_bytes(),gold.read_bytes())
            self.assertEqual(gate.read_text().count("^ 4'b1010"),1)
            negative=root/"negative.sv";negative.write_text(gate.read_text().replace("^ 4'b1010","^ 4'b1011",1))
            for label,path in (("positive",gate),("negative",negative)):
                command=[sys.executable,str(ROOT/"scripts/formal_equivalence.py"),"--gold",str(gold),"--gate",str(path),"--top","proof_top","--seq","5"]
                run=subprocess.run(command,capture_output=True,text=True,cwd=ROOT)
                if label=="positive":
                    self.assertEqual(run.returncode,0,run.stderr)
                    payload=json.loads(run.stdout);self.assertEqual(payload["formal_equivalence"],"pass")
                else:
                    self.assertNotEqual(run.returncode,0)
                    self.assertIn("unproven",run.stdout+run.stderr)
                    self.assertIn("equiv_status -assert",run.stdout+run.stderr)
                    payload={"fixed_functional_negative":"rejected"}
                print("T142_FORMAL_JSON="+json.dumps(dict(case=label,command=command,exit_code=run.returncode,result=payload)))


if __name__ == "__main__":
    unittest.main()
