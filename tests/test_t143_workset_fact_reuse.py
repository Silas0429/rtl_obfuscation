"""Main-Agent frozen ordered-traversal, retry and policy extension guards."""

from dataclasses import replace
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

import rtl_obfuscator.rename_index as ri
from rtl_obfuscator.source_catalog import SourceRange, build_source_catalog
from rtl_obfuscator.source_set import from_filelist
from tests.test_t128_rename_index_range_cache import ROOT, T108_FIXTURE, _decision_projection


class _TrackedTuple(tuple):
    def __new__(cls, values):
        result=super().__new__(cls,values)
        result.visits=[]
        return result

    def __iter__(self):
        for item in super().__iter__():
            self.visits.append(item.ordinal)
            yield item


class _RootView:
    def __init__(self,root):
        self.root=root
        self.visits=0

    def visit(self,callback):
        self.visits+=1
        return self.root.visit(callback)

    def __getattr__(self,name):
        return getattr(self.root,name)


def _changing_node(*, outer_failure=None, inner_failure=None, alias=True):
    counts={"outer":0,"inner":0}
    state={"alias":alias}
    alias_type=type("TypeAliasType",(),{})()

    class Declared:
        @property
        def type(self):
            counts["inner"]+=1
            if counts["inner"]==1 and inner_failure is not None:
                raise inner_failure("initial inner getter failure")
            return alias_type if state["alias"] else None

    class FutureSemanticNode:
        name="future_name"

        @property
        def declaredType(self):
            counts["outer"]+=1
            if counts["outer"]==1 and outer_failure is not None:
                raise outer_failure("initial outer getter failure")
            return Declared()

    return FutureSemanticNode(), counts, state


def _workset(nodes, *, shared=True, top=True):
    ordered=_TrackedTuple(ri._OrderedSemanticNode(17+3*i,node) for i,node in enumerate(nodes))
    overlay=ordered if shared else _TrackedTuple(ordered)
    ordered.visits.clear()
    if overlay is not ordered:
        overlay.visits.clear()
    result=ri._SemanticWorkset(catalog=ordered,top=overlay if top else ())
    return result,ordered,overlay


class T143WorksetFactReuseTests(unittest.TestCase):
    def test_successful_facts_reused_without_filtering_full_top_iteration(self):
        unknown,counts,_=_changing_node()
        unrelated=NS(name="still_reserved")
        workset,catalog,_=_workset([unknown,unrelated])
        self.assertEqual(counts,{"outer":1,"inner":1})
        self.assertEqual(catalog.visits,[17,20,17,20])
        self.assertEqual(workset.top_type_nodes,(unknown,))
        self.assertIn(unknown,workset.completeness_nodes)
        self.assertEqual(workset.semantic_names,frozenset({"future_name","still_reserved"}))

    def test_missing_or_failed_outer_fact_is_retried(self):
        for error in (AttributeError,RuntimeError):
            node,counts,_=_changing_node(outer_failure=error)
            workset,_,_=_workset([node])
            self.assertEqual(counts,{"outer":2,"inner":1})
            self.assertEqual(workset.top_type_nodes,(node,))

    def test_missing_or_failed_inner_fact_is_retried(self):
        for error in (AttributeError,RuntimeError):
            node,counts,_=_changing_node(inner_failure=error)
            workset,_,_=_workset([node])
            self.assertEqual(counts,{"outer":2,"inner":2})
            self.assertEqual(workset.top_type_nodes,(node,))

    def test_same_nodes_new_build_recomputes_facts(self):
        node,counts,state=_changing_node(alias=False)
        for alias in (False,True,False):
            state["alias"]=alias
            before=counts.copy()
            workset,_,_=_workset([node])
            self.assertEqual(workset.top_type_nodes,(node,) if alias else ())
            self.assertEqual(counts["outer"]-before["outer"],1)
            self.assertEqual(counts["inner"]-before["inner"],1)

    def test_distinct_and_absent_top_do_not_share_facts(self):
        for top in (False,True):
            node,counts,_=_changing_node()
            workset,catalog,overlay=_workset([node],shared=False,top=top)
            self.assertEqual(counts,{"outer":2 if top else 1,"inner":2 if top else 1})
            self.assertEqual(catalog.visits,[17])
            self.assertEqual(overlay.visits,[17] if top else [])
            self.assertEqual(workset.top_type_nodes,(node,) if top else ())

    def test_mixed_success_and_retry_keep_positional_facts_aligned(self):
        first,first_counts,_=_changing_node()
        second,second_counts,_=_changing_node(outer_failure=RuntimeError)
        third,third_counts,_=_changing_node(alias=False)
        fourth,fourth_counts,_=_changing_node(inner_failure=AttributeError)
        workset,catalog,_=_workset([first,second,third,fourth])
        self.assertEqual(workset.top_type_nodes,(first,second,fourth))
        self.assertEqual(catalog.visits,[17,20,23,26]*2)
        self.assertEqual([counts["outer"] for counts in (first_counts,second_counts,third_counts,fourth_counts)],
                         [1,2,1,2])

    def test_distinct_top_new_nodes_and_different_length_are_not_truncated(self):
        only_catalog,catalog_counts,_=_changing_node(alias=False)
        first,first_counts,_=_changing_node()
        second,second_counts,_=_changing_node()
        catalog=_TrackedTuple([ri._OrderedSemanticNode(0,only_catalog)])
        top=_TrackedTuple([ri._OrderedSemanticNode(0,first),ri._OrderedSemanticNode(1,second)])
        workset=ri._SemanticWorkset(catalog=catalog,top=top)
        self.assertEqual(workset.top_type_nodes,(first,second))
        self.assertEqual(top.visits,[0,1])
        self.assertEqual([counts["outer"] for counts in (catalog_counts,first_counts,second_counts)],[1,1,1])

    def test_top_specific_getters_keep_late_order(self):
        events=[]
        def node(kind):
            def declared(_self):
                events.append(kind+".declared")
                return NS(type=None)
            def name(_self):
                events.append(kind+".name")
                return kind
            def interface(_self):
                events.append("top.interface")
                return True
            def converted(_self):
                events.append("top.conversion")
                return type("TypeAliasType",(),{})()
            return type(kind,(),{"declaredType":property(declared),"name":property(name),
                                 "isInterface":property(interface),"type":property(converted)})()
        instance=node("InstanceSymbol");conversion=node("ConversionExpression")
        workset,_,_=_workset([instance,conversion])
        self.assertLess(events.index("ConversionExpression.name"),events.index("top.interface"))
        self.assertLess(events.index("top.interface"),events.index("top.conversion"))
        self.assertEqual(workset.top_interface_nodes,(instance,))
        self.assertEqual(workset.top_type_nodes,(conversion,))

    def _ports(self):
        cls=type("PortSymbol",(),{})
        ports=[]
        for i in range(2):
            port=cls();port.name="same";port.syntax=object();port.location=10
            port.internalSymbol=object();port.declaringDefinition=f"owner{i}"
            ports.append(port)
        return ports

    def _register(self,ports,*,mode="success",selected=True,support="eligible"):
        tries=[];additions=[];issues={};owner_calls=[];events=[]
        counts={id(p):0 for p in ports}
        def resolve(catalog,issues,category,node,syntax,name,**kwargs):
            counts[id(node)]+=1;tries.append((id(node),category))
            events.append(("range",node.declaringDefinition))
            if mode=="failure" or (mode=="retry" and counts[id(node)]==1):
                issues.setdefault(category,[]).append({"owner":node.declaringDefinition,"message":"failed"})
                return None
            return SourceRange("ports.sv",10,14)
        def owner(catalog,definition,*args,**kwargs):
            owner_calls.append(definition)
            events.append(("owner",definition))
            return definition,definition,definition,"module"
        def add(*args,**kwargs):
            additions.append({key:value for key,value in kwargs.items() if key!="catalog"})
        cat=NS(source_set=NS(top="top"))
        with patch.object(ri,"_try_declaration_range",side_effect=resolve), \
             patch.object(ri,"_owner_info",side_effect=owner), \
             patch.object(ri,"_category_support",return_value=(support,"new_rule" if support=="preserved" else None,"internal")), \
             patch.object(ri,"_add_working",side_effect=add):
            ri._register_core_declarations(cat,{"ports"} if selected else set(),{},{},ports,{},{},{},{},set(),issues)
        self._port_events=events
        return tries,additions,issues,owner_calls

    def test_port_success_reuse_does_not_merge_same_physical_instances(self):
        ports=self._ports()
        tries,added,issues,owners=self._register(ports)
        self.assertEqual(len(tries),2)
        self.assertEqual(issues,{})
        self.assertEqual(owners,["owner0","owner1"])
        self.assertEqual([a["owner_module"] for a in added],owners)
        self.assertEqual(added[0]["declaration"],added[1]["declaration"])
        self.assertEqual([a["targets"] for a in added],[(p,p.internalSymbol) for p in ports])
        self.assertEqual(self._port_events,[("range","owner0"),("range","owner1"),
                                           ("owner","owner0"),("owner","owner1")])

    def test_port_failed_prescan_retries_with_original_issue_order(self):
        for mode in ("failure","retry"):
            ports=self._ports()
            tries,added,issues,owners=self._register(ports,mode=mode)
            self.assertEqual(len(tries),4)
            self.assertEqual([v["owner"] for v in issues["ports"]],
                             ["owner0","owner1"]*(2 if mode=="failure" else 1))
            self.assertEqual(len(added),0 if mode=="failure" else 2)
            self.assertEqual(owners,["owner0","owner1"])
            self.assertEqual(self._port_events,[("range","owner0"),("range","owner1"),
                             ("owner","owner0"),("range","owner0"),("owner","owner1"),("range","owner1")])

    def test_port_policy_selection_owner_and_targets_recomputed_each_call(self):
        ports=self._ports()
        for selected,support in ((True,"eligible"),(True,"preserved"),(False,"eligible"),(True,"eligible")):
            ports[0].declaringDefinition="new_owner_"+support
            ports[0].internalSymbol=object()
            tries,added,_,owners=self._register(ports,selected=selected,support=support)
            self.assertEqual(len(tries),2)
            self.assertEqual(owners,[ports[0].declaringDefinition,"owner1"])
            self.assertEqual(len(added),2 if selected else 0)
            if selected:
                self.assertEqual([a["support"] for a in added],[support,support])
                self.assertEqual([a["reason"] for a in added],["new_rule" if support=="preserved" else None]*2)
                self.assertEqual(added[0]["targets"],(ports[0],ports[0].internalSymbol))
                self.assertEqual(added[0]["owner_module"],ports[0].declaringDefinition)

    def test_real_same_distinct_and_no_top_keep_complete_decisions(self):
        for top in (None,"top"):
            catalog=build_source_catalog(from_filelist(filelist=T108_FIXTURE/"design.f",top=top))
            expected=ri.build_rename_index(catalog,categories=("all",))
            catalog_root=_RootView(catalog.catalog_root)
            # Compare normal execution with an explicit separate top view.
            top_root=_RootView(catalog.top_root) if catalog.top_root is not None else None
            wrapped=replace(catalog,catalog_root=catalog_root,top_root=top_root)
            actual=ri.build_rename_index(wrapped,categories=("all",))
            self.assertEqual(_decision_projection(actual),_decision_projection(expected))
            self.assertEqual(actual._live_semantic_names,expected._live_semantic_names)
            self.assertEqual(catalog_root.visits,1)
            if top_root is not None:
                self.assertEqual(top_root.visits,1)


if __name__=="__main__":
    unittest.main()
