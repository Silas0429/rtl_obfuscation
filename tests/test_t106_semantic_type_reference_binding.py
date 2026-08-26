from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from rtl_obfuscator.mapping_vnext import build_mapping_vnext
from rtl_obfuscator.rewrite_policy import build_rewrite_policy
from rtl_obfuscator.source_catalog import build_source_catalog
from rtl_obfuscator.source_set import from_filelist
from rtl_obfuscator.symbol_graph import build_symbol_graph


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "t106_semantic_type_reference_binding"
TOP = "t106_top"


def _deterministic_factory(
    symbol_id: str, name_length: int, unavailable: frozenset[str]
) -> str:
    candidate = ("s" + hashlib.sha256(symbol_id.encode("utf-8")).hexdigest())[
        :name_length
    ]
    if candidate in unavailable:
        raise AssertionError("test factory collision")
    return candidate


class T106SemanticTypeReferenceBindingTests(unittest.TestCase):
    @classmethod
    def _graph(cls):
        source_set = from_filelist(
            filelist=FIXTURE_ROOT / "design.f",
            source_root=FIXTURE_ROOT,
            top=TOP,
        )
        catalog = build_source_catalog(source_set)
        return source_set, catalog, build_symbol_graph(
            catalog,
            categories=("struct_types", "struct_fields", "union_fields"),
        )

    def test_same_spelling_aggregate_references_bind_to_physical_aliases(self):
        _source_set, catalog, graph = self._graph()
        aggregate = [
            symbol
            for symbol in graph.symbols
            if symbol.category in {"struct_types", "union_fields"}
            and symbol.name in {"shared_t", "shared_u"}
        ]
        self.assertGreaterEqual(len(aggregate), 8)
        shared_types = [
            symbol
            for symbol in graph.symbols
            if symbol.category == "struct_types" and symbol.name == "shared_t"
        ]
        self.assertGreaterEqual(len(shared_types), 4)
        self.assertEqual(
            len({symbol.symbol_id for symbol in shared_types}), len(shared_types)
        )
        self.assertEqual(
            len({symbol.declaration for symbol in shared_types}), len(shared_types)
        )
        expected = {
            "rtl/left.sv": {
                "semantic_port_type": b"shared_t typed_i",
                "semantic_type": b"shared_t value",
                "semantic_return_type": b"shared_t make_value",
                "semantic_cast_type": b"shared_t'(",
            },
            "rtl/right.sv": {
                "semantic_port_type": b"shared_t typed_i",
                "semantic_type": b"shared_t value",
                "semantic_return_type": b"shared_t make_value",
                "semantic_cast_type": b"shared_t'(",
            },
        }
        for file, snippets in expected.items():
            source = (FIXTURE_ROOT / file).read_bytes()
            symbol = next(
                item
                for item in shared_types
                if item.declaration.file == file
            )
            self.assertEqual(
                source[symbol.declaration.start : symbol.declaration.end],
                b"shared_t",
            )
            for provenance, snippet in snippets.items():
                token_start = source.index(b"shared_t", source.index(snippet))
                occurrences = [
                    occurrence
                    for occurrence in symbol.occurrences
                    if occurrence.provenance == provenance
                    and occurrence.source_range.file == file
                ]
                self.assertEqual(len(occurrences), 1, (file, provenance))
                occurrence = occurrences[0]
                self.assertEqual(occurrence.source_range.start, token_start)
                self.assertEqual(
                    source[
                        occurrence.source_range.start : occurrence.source_range.end
                    ],
                    b"shared_t",
                )

            member = next(
                item
                for item in graph.symbols
                if item.category == "struct_types"
                and item.name == "member_t"
                and item.declaration.file == file
            )
            member_start = source.index(b"member_t nested")
            member_occurrences = [
                occurrence
                for occurrence in member.occurrences
                if occurrence.provenance == "semantic_type"
                and occurrence.source_range.start == member_start
            ]
            self.assertEqual(len(member_occurrences), 1, (file, "member_t"))
            self.assertEqual(
                source[
                    member_occurrences[0].source_range.start : member_occurrences[0].source_range.end
                ],
                b"member_t",
            )

            raw = next(
                item
                for item in graph.symbols
                if item.category == "union_fields"
                and item.name == "raw"
                and item.declaration.file == file
            )
            raw_start = source.index(b"union_value.raw") + len(b"union_value.")
            raw_occurrences = [
                occurrence
                for occurrence in raw.occurrences
                if occurrence.provenance == "semantic_member"
                and occurrence.source_range.start == raw_start
            ]
            self.assertEqual(len(raw_occurrences), 1, (file, "raw"))
            self.assertEqual(
                source[
                    raw_occurrences[0].source_range.start : raw_occurrences[0].source_range.end
                ],
                b"raw",
            )

        mapping = build_mapping_vnext(
            build_rewrite_policy(
                graph,
                categories=("struct_types", "struct_fields", "union_fields"),
                abi_categories=("struct_types", "struct_fields", "union_fields"),
            ),
            name_length=16,
            name_factory=_deterministic_factory,
        )
        same_name_records = [
            record
            for record in mapping.records
            if record.original_name == "shared_t"
        ]
        self.assertGreaterEqual(len(same_name_records), 4)
        self.assertEqual(
            len({record.symbol_id for record in same_name_records}),
            len(same_name_records),
        )
        self.assertEqual(
            len({record.declaration for record in same_name_records}),
            len(same_name_records),
        )
        self.assertEqual(
            len({record.renamed_name for record in same_name_records}),
            len(same_name_records),
        )
        self.assertTrue(
            all(
                record.action == "rename"
                and all(
                    (FIXTURE_ROOT / occurrence.source_range.file).read_bytes()[
                        occurrence.source_range.start : occurrence.source_range.end
                    ]
                    == record.original_name.encode("utf-8")
                    for occurrence in record.occurrences
                )
                for record in same_name_records
            )
        )

    def test_ports_only_does_not_enter_aggregate_type_resolver(self):
        source_set = from_filelist(
            filelist=FIXTURE_ROOT / "design.f",
            source_root=FIXTURE_ROOT,
            top=TOP,
        )
        graph = build_symbol_graph(
            build_source_catalog(source_set),
            categories=("ports",),
        )
        self.assertTrue(graph.symbols)
        self.assertTrue(all(symbol.category == "ports" for symbol in graph.symbols))

    def test_selected_port_category_keeps_aggregate_port_reference_bound(self):
        source_set = from_filelist(
            filelist=FIXTURE_ROOT / "design.f",
            source_root=FIXTURE_ROOT,
            top=TOP,
        )
        graph = build_symbol_graph(
            build_source_catalog(source_set),
            categories=("ports", "struct_types", "struct_fields", "union_fields"),
        )
        source = (FIXTURE_ROOT / "rtl/left.sv").read_bytes()
        shared_t = next(
            symbol
            for symbol in graph.symbols
            if symbol.category == "struct_types"
            and symbol.name == "shared_t"
            and symbol.declaration.file == "rtl/left.sv"
        )
        port_start = source.index(b"shared_t typed_i")
        occurrences = [
            occurrence
            for occurrence in shared_t.occurrences
            if occurrence.provenance == "semantic_port_type"
            and occurrence.source_range.start == port_start
        ]
        self.assertEqual(len(occurrences), 1)
        self.assertEqual(
            source[occurrences[0].source_range.start : occurrences[0].source_range.end],
            b"shared_t",
        )

    def test_public_gate_restore_and_actual_formal_positive_and_negative(self):
        with tempfile.TemporaryDirectory(prefix="t106-formal-", dir="/private/tmp") as temporary:
            root = Path(temporary)
            gate = root / "gate"
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "rtl_encrypt.py"),
                    "--filelist",
                    str(FIXTURE_ROOT / "design.f"),
                    "--top",
                    TOP,
                    "--category",
                    "struct",
                    "--category",
                    "union_fields",
                    "--output-dir",
                    str(gate),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads((gate / "mapping.json").read_text(encoding="utf-8"))
            summary = report["summary"]
            self.assertEqual(summary["encryption_result"], "PASS_FULL")
            self.assertTrue(summary["strict_compile_passed"])
            self.assertTrue(summary["restored_byte_identical"])
            self.assertEqual(summary["preserve"], 0)
            self.assertEqual(summary["unsupported"], 0)
            self.assertEqual(
                {record["action"] for record in report["mapping"]["records"]},
                {"rename"},
            )
            range_audit = report["mapping"]["range_audit"]
            self.assertEqual(
                range_audit,
                {"declarations": 28, "occurrences": 46, "total_ranges": 74},
            )
            manifest = report["mapping"]["input_manifest"]
            self.assertEqual(
                {entry["file"] for entry in manifest},
                {"rtl/left.sv", "rtl/right.sv", "rtl/top.sv", "formal.sv"},
            )
            for entry in manifest:
                self.assertEqual(
                    entry["sha256"],
                    hashlib.sha256(
                        (FIXTURE_ROOT / entry["file"]).read_bytes()
                    ).hexdigest(),
                )
            print("T106_MAPPING_SUMMARY=" + json.dumps(summary, sort_keys=True))
            print("T106_RANGE_AUDIT=" + json.dumps(range_audit, sort_keys=True))
            formal_records = [
                record
                for record in report["mapping"]["records"]
                if record["declaration"]["file"] == "formal.sv"
                and record["original_name"] in {"shared_t", "shared_u"}
            ]
            self.assertEqual(
                {record["original_name"] for record in formal_records},
                {"shared_t", "shared_u"},
            )
            formal_source = (gate / "formal.sv").read_bytes()
            self.assertTrue(
                all(
                    record["renamed_name"].encode("ascii") in formal_source
                    for record in formal_records
                )
            )

            restored = root / "restored"
            decrypt = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "rtl_decrypt.py"),
                    "--map",
                    str(gate / "mapping.json"),
                    "--gate-dir",
                    str(gate),
                    "--output-dir",
                    str(restored),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
            self.assertEqual(decrypt.returncode, 0, decrypt.stderr)
            for relative in ("formal.sv", "rtl/left.sv", "rtl/right.sv", "rtl/top.sv"):
                self.assertEqual(
                    (restored / relative).read_bytes(),
                    (FIXTURE_ROOT / relative).read_bytes(),
                )

            formal = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "formal_equivalence.py"),
                    "--gold",
                    str(FIXTURE_ROOT / "formal.sv"),
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
                check=False,
            )
            self.assertEqual(formal.returncode, 0, formal.stdout + formal.stderr)
            formal_payload = json.loads(formal.stdout.strip().splitlines()[-1])
            self.assertEqual(formal_payload["formal_equivalence"], "pass")
            print(
                "T106_FORMAL_POSITIVE="
                + json.dumps(formal_payload, sort_keys=True)
            )

            negative = root / "negative"
            shutil.copytree(gate, negative)
            negative_source = negative / "formal.sv"
            source = negative_source.read_bytes()
            marker = b"assign data_o = left_o ^ right_o ^ stress_o[0];"
            self.assertEqual(source.count(marker), 1)
            position = source.index(marker) + len(b"assign data_o = ")
            negative_source.write_bytes(source[:position] + b"~" + source[position:])
            negative_formal = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "formal_equivalence.py"),
                    "--gold",
                    str(FIXTURE_ROOT / "formal.sv"),
                    "--gate",
                    str(negative / "formal.sv"),
                    "--top",
                    TOP,
                    "--seq",
                    "5",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
            negative_output = negative_formal.stdout + negative_formal.stderr
            self.assertNotEqual(negative_formal.returncode, 0)
            self.assertIn("unproven", negative_output)
            self.assertIn("equiv_status -assert", negative_output)
            print(
                f"T106_FORMAL_NEGATIVE_EXIT={negative_formal.returncode} "
                "markers=unproven,equiv_status -assert"
            )


if __name__ == "__main__":
    unittest.main()
