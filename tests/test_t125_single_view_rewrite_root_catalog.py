from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import rtl_obfuscator.source_catalog as source_catalog_module
from rtl_obfuscator.rename_index import build_rename_index
from rtl_obfuscator.source_catalog import (
    SourceCatalogError,
    build_source_catalog,
)
from rtl_obfuscator.source_set import from_filelist


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "t125_single_view_rewrite_root_catalog"
PUBLIC_ENCRYPT = ROOT / "rtl_encrypt.py"
PUBLIC_DECRYPT = ROOT / "rtl_decrypt.py"
FORMAL = ROOT / "scripts" / "formal_equivalence.py"
TOP = "t125_top"


class T125SingleViewRewriteRootCatalogTests(unittest.TestCase):
    def _source_set(self, *, filelist: Path = FIXTURE / "design.f"):
        return from_filelist(
            filelist=filelist,
            source_root=FIXTURE,
            top=TOP,
            rewrite_roots=(FIXTURE / "owned",),
        )

    @staticmethod
    def _run(script: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(script), *arguments],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )

    @staticmethod
    def _write_duplicate_case(
        root: Path,
        *,
        providers: tuple[tuple[str, str, str], ...],
        top_body: str = "module t125_top(); endmodule\n",
    ) -> Path:
        (root / "owned").mkdir(parents=True)
        (root / "external").mkdir()
        (root / "owned" / "top.sv").write_text(top_body, encoding="utf-8")
        lines = ["owned/top.sv"]
        for relative, kind, body in providers:
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")
            lines.append(f"-v {relative}" if kind == "library_source" else relative)
        filelist = root / "design.f"
        filelist.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return filelist

    def test_single_explicit_top_view_has_cst_inventory_and_one_compile(self):
        source_set = self._source_set()
        real_compile_view = source_catalog_module._compile_view
        with mock.patch(
            "rtl_obfuscator.source_catalog._compile_view",
            wraps=real_compile_view,
        ) as compile_view:
            catalog = build_source_catalog(source_set)

        self.assertEqual(compile_view.call_count, 1)
        self.assertEqual(compile_view.call_args.kwargs["top"], TOP)
        self.assertIs(catalog.catalog_compilation, catalog.top_compilation)
        self.assertIs(catalog.catalog_root, catalog.top_root)
        self.assertIs(catalog.catalog_source_manager, catalog.top_source_manager)
        self.assertEqual(
            {module.name for module in catalog.modules},
            {"t125_child", "t125_top", "t125_unreachable"},
        )
        by_name = {module.name: module for module in catalog.modules}
        self.assertTrue(by_name["t125_top"].is_selected_top)
        self.assertTrue(by_name["t125_top"].in_top_closure)
        self.assertTrue(by_name["t125_child"].in_top_closure)
        self.assertFalse(by_name["t125_unreachable"].in_top_closure)
        self.assertEqual(catalog.readonly_duplicate_inventory, ())
        self.assertEqual(
            catalog.to_report()["compile"],
            {
                "catalog": {"parse_errors": 0, "semantic_errors": 0},
                "top_overlay": {"parse_errors": 0, "semantic_errors": 0},
            },
        )

        # The CST inventory includes the unelaborated vendor module; any
        # corresponding semantic record remains readonly outside the selected
        # top closure and is never treated as an eligible binding.
        index = build_rename_index(catalog, categories=("all",))
        external_symbols = [
            symbol
            for symbol in index.symbols
            if symbol.declaration.file == "external/unreachable.sv"
        ]
        self.assertTrue(external_symbols)
        self.assertTrue(
            all(
                symbol.support == "preserved"
                and symbol.reason == "outside_top_closure"
                for symbol in external_symbols
            )
        )

    def test_physical_inventory_reads_only_token_sized_ranges(self):
        with tempfile.TemporaryDirectory(prefix="t125-bounded-read-") as temporary:
            root = Path(temporary)
            (root / "owned").mkdir()
            (root / "external").mkdir()
            (root / "owned/top.sv").write_text(
                "module t125_top(); endmodule\n", encoding="utf-8"
            )
            padding = "/*" + ("x" * (256 * 1024)) + "*/"
            (root / "external/padded.sv").write_text(
                "module t125_padded(); " + padding + " endmodule\n",
                encoding="utf-8",
            )
            filelist = root / "design.f"
            filelist.write_text(
                "owned/top.sv\nexternal/padded.sv\n", encoding="utf-8"
            )
            source_set = from_filelist(
                filelist=filelist,
                source_root=root,
                top=TOP,
                rewrite_roots=(root / "owned",),
            )
            real_read = source_catalog_module._read_physical_token
            requests: list[tuple[str, int]] = []

            def read_token(source_set, file, start, length):
                requests.append((file, length))
                return real_read(source_set, file, start, length)

            with mock.patch(
                "rtl_obfuscator.source_catalog._read_physical_token",
                side_effect=read_token,
            ):
                catalog = build_source_catalog(source_set)

            self.assertEqual(
                {module.name for module in catalog.modules},
                {"t125_top", "t125_padded"},
            )
            expected_lengths = {
                "external/padded.sv": len("t125_padded"),
                "owned/top.sv": len(TOP),
            }
            self.assertTrue(requests)
            self.assertTrue(
                all(length == expected_lengths[file] for file, length in requests)
            )

    def test_readonly_duplicate_matrix_is_finite_and_fail_closed(self):
        duplicate_body = "module t125_duplicate(); logic duplicate_signal; endmodule\n"
        with tempfile.TemporaryDirectory(prefix="t125-duplicates-") as temporary:
            root = Path(temporary)

            allowed_cases = (
                (
                    "all-library",
                    (
                        ("external/lib_a.sv", "library_source", duplicate_body),
                        ("external/lib_b.sv", "library_source", duplicate_body),
                    ),
                ),
                (
                    "one-bare-plus-library",
                    (
                        ("external/bare.sv", "source", duplicate_body),
                        ("external/lib.sv", "library_source", duplicate_body),
                    ),
                ),
            )
            for name, providers in allowed_cases:
                case_root = root / name
                filelist = self._write_duplicate_case(
                    case_root,
                    providers=providers,
                )
                source_set = from_filelist(
                    filelist=filelist,
                    source_root=case_root,
                    top=TOP,
                    rewrite_roots=(case_root / "owned",),
                )
                catalog = build_source_catalog(source_set)
                self.assertEqual(
                    [item.name for item in catalog.readonly_duplicate_inventory],
                    ["t125_duplicate"],
                )
                duplicate = catalog.readonly_duplicate_inventory[0]
                self.assertEqual(
                    tuple(item.file for item in duplicate.declarations),
                    tuple(sorted(item.file for item in duplicate.declarations)),
                )
                self.assertTrue(
                    all(not module.in_top_closure for module in catalog.modules if module.name == "t125_duplicate")
                )
                index = build_rename_index(catalog, categories=("all",))
                external_symbols = [
                    symbol
                    for symbol in index.symbols
                    if symbol.declaration.file.startswith("external/")
                ]
                self.assertTrue(external_symbols)
                decisions = {decision.symbol_id: decision for decision in index.decisions}
                self.assertTrue(
                    all(
                        symbol.support != "eligible"
                        and symbol.reason in {"outside_top_closure", "outside_rewrite_root"}
                        and decisions[symbol.symbol_id].action == "preserve"
                        for symbol in external_symbols
                    )
                )

            rejected_cases = (
                (
                    "two-bare",
                    (
                        ("external/bare_a.sv", "source", duplicate_body),
                        ("external/bare_b.sv", "source", duplicate_body),
                    ),
                    "module t125_top(); endmodule\n",
                ),
                (
                    "rewrite-root",
                    (
                        ("owned/in_root.sv", "source", duplicate_body),
                        ("external/library.sv", "library_source", duplicate_body),
                    ),
                    "module t125_top(); endmodule\n",
                ),
                (
                    "selected-top",
                    (
                        ("external/duplicate_top.sv", "library_source", "module t125_top(); endmodule\n"),
                    ),
                    "module t125_top(); endmodule\n",
                ),
                (
                    "top-reachable",
                    (
                        ("external/lib_a.sv", "library_source", duplicate_body),
                        ("external/lib_b.sv", "library_source", duplicate_body),
                    ),
                    "module t125_top(); t125_duplicate u_dup(); endmodule\n",
                ),
                (
                    "same-file",
                    (
                        (
                            "external/same.sv",
                            "library_source",
                            "module t125_duplicate(); endmodule\nmodule t125_duplicate(); endmodule\n",
                        ),
                    ),
                    "module t125_top(); endmodule\n",
                ),
            )
            for name, providers, top_body in rejected_cases:
                case_root = root / name
                filelist = self._write_duplicate_case(
                    case_root,
                    providers=providers,
                    top_body=top_body,
                )
                source_set = from_filelist(
                    filelist=filelist,
                    source_root=case_root,
                    top=TOP,
                    rewrite_roots=(case_root / "owned",),
                )
                with self.subTest(name=name):
                    with self.assertRaises(SourceCatalogError) as raised:
                        build_source_catalog(source_set)
                    self.assertEqual(raised.exception.code, "CATALOG_DUPLICATE_MODULE")

            missing_root = root / "missing-provenance"
            filelist = self._write_duplicate_case(
                missing_root,
                providers=(
                    ("external/lib_a.sv", "library_source", duplicate_body),
                    ("external/lib_b.sv", "library_source", duplicate_body),
                ),
            )
            source_set = from_filelist(
                filelist=filelist,
                source_root=missing_root,
                top=TOP,
                rewrite_roots=(missing_root / "owned",),
            )
            with self.assertRaises(SourceCatalogError) as raised:
                build_source_catalog(replace(source_set, filelist_entries=()))
            self.assertEqual(raised.exception.code, "CATALOG_DUPLICATE_MODULE")

    def test_public_gate_restore_formal_and_two_explicit_top_views(self):
        source_set = self._source_set()
        with tempfile.TemporaryDirectory(prefix="t125-formal-") as temporary:
            root = Path(temporary)
            gate = root / "gate"
            encrypted = self._run(
                PUBLIC_ENCRYPT,
                "--filelist",
                str(FIXTURE / "design.f"),
                "--top",
                TOP,
                "--rewrite-root",
                str(FIXTURE / "owned"),
                "--category",
                "all",
                "--output-dir",
                str(gate),
            )
            self.assertEqual(encrypted.returncode, 0, encrypted.stderr)
            payload = json.loads((gate / "mapping.json").read_text(encoding="utf-8"))
            self.assertTrue(payload["summary"]["strict_compile_passed"])
            self.assertTrue(payload["summary"]["restored_byte_identical"])
            self.assertGreater(payload["summary"]["modified_tokens"], 0)
            self.assertNotEqual(
                (gate / "owned/top.sv").read_bytes(),
                (FIXTURE / "owned/top.sv").read_bytes(),
            )

            restored = root / "restored"
            decrypted = self._run(
                PUBLIC_DECRYPT,
                "--map",
                str(gate / "mapping.json"),
                "--gate-dir",
                str(gate),
                "--output-dir",
                str(restored),
            )
            self.assertEqual(decrypted.returncode, 0, decrypted.stderr)
            for relative in ("owned/child.sv", "owned/top.sv", "external/unreachable.sv"):
                self.assertEqual(
                    (restored / relative).read_bytes(),
                    (FIXTURE / relative).read_bytes(),
                )

            gate_source_set = from_filelist(
                filelist=gate / "design.f",
                source_root=gate,
                top=TOP,
                rewrite_roots=(gate / "owned",),
            )
            real_compile_view = source_catalog_module._compile_view
            with mock.patch(
                "rtl_obfuscator.source_catalog._compile_view",
                wraps=real_compile_view,
            ) as compile_view:
                original_catalog = build_source_catalog(source_set)
                gate_catalog = build_source_catalog(gate_source_set)
            self.assertEqual(compile_view.call_count, 2)
            self.assertEqual(
                [call.kwargs["top"] for call in compile_view.call_args_list],
                [TOP, TOP],
            )
            self.assertIs(original_catalog.catalog_compilation, original_catalog.top_compilation)
            self.assertIs(gate_catalog.catalog_compilation, gate_catalog.top_compilation)

            formal_arguments = (
                "--gold-filelist",
                str(FIXTURE / "design.f"),
                "--gold-root",
                str(FIXTURE),
                "--gate-filelist",
                str(gate / "design.f"),
                "--gate-root",
                str(gate),
                "--top",
                TOP,
                "--seq",
                "5",
            )
            positive = self._run(FORMAL, *formal_arguments)
            self.assertEqual(positive.returncode, 0, positive.stdout + positive.stderr)
            positive_json = json.loads(positive.stdout.strip().splitlines()[-1])
            self.assertEqual(positive_json["formal_equivalence"], "pass")
            print(
                "T125_FORMAL_POSITIVE "
                + json.dumps(
                    {
                        "gold_filelist": str(FIXTURE / "design.f"),
                        "gate_filelist": str(gate / "design.f"),
                        "top": TOP,
                        "exit": positive.returncode,
                        "json": positive_json,
                    },
                    sort_keys=True,
                )
            )

            negative = root / "negative"
            shutil.copytree(gate, negative)
            target = negative / "owned/child.sv"
            original = target.read_bytes()
            mutation = original.replace(b" = ", b" = ~", 1)
            self.assertNotEqual(mutation, original)
            target.write_bytes(mutation)
            negative_result = self._run(
                FORMAL,
                "--gold-filelist",
                str(FIXTURE / "design.f"),
                "--gold-root",
                str(FIXTURE),
                "--gate-filelist",
                str(negative / "design.f"),
                "--gate-root",
                str(negative),
                "--top",
                TOP,
                "--seq",
                "5",
            )
            self.assertNotEqual(negative_result.returncode, 0)
            combined = (negative_result.stdout + negative_result.stderr).lower()
            self.assertIn("unproven", combined)
            self.assertIn("equiv_status -assert", combined)
            print(
                "T125_FORMAL_NEGATIVE "
                + json.dumps(
                    {
                        "gold_filelist": str(FIXTURE / "design.f"),
                        "gate_filelist": str(negative / "design.f"),
                        "top": TOP,
                        "exit": negative_result.returncode,
                        "mutation": "first child assignment RHS prefixed with ~",
                        "evidence": "unproven; equiv_status -assert",
                    },
                    sort_keys=True,
                )
            )

    def test_public_gate_with_readonly_duplicate_keeps_live_provenance(self):
        duplicate_body = "module t125_duplicate(); logic duplicate_signal; endmodule\n"
        with tempfile.TemporaryDirectory(prefix="t125-public-duplicate-") as temporary, \
            tempfile.TemporaryDirectory(prefix="t125-public-duplicate-output-") as output_temporary:
            root = Path(temporary)
            output_root = Path(output_temporary)
            filelist = self._write_duplicate_case(
                root,
                providers=(
                    ("external/bare.sv", "source", duplicate_body),
                    ("external/lib.sv", "library_source", duplicate_body),
                ),
                top_body=(
                    "module t125_top(); logic top_signal; "
                    "assign top_signal = 1'b0; endmodule\n"
                ),
            )
            source_set = from_filelist(
                filelist=filelist,
                source_root=root,
                top=TOP,
                rewrite_roots=(root / "owned",),
            )
            gate = output_root / "gate"
            encrypted = self._run(
                PUBLIC_ENCRYPT,
                "--filelist",
                str(filelist),
                "--top",
                TOP,
                "--rewrite-root",
                str(root / "owned"),
                "--category",
                "all",
                "--output-dir",
                str(gate),
            )
            self.assertEqual(encrypted.returncode, 0, encrypted.stderr)
            payload = json.loads((gate / "mapping.json").read_text(encoding="utf-8"))
            self.assertTrue(payload["summary"]["strict_compile_passed"])
            self.assertTrue(payload["summary"]["restored_byte_identical"])
            self.assertGreater(payload["summary"]["mapping_records"], 2)
            self.assertGreater(payload["summary"]["rename"], 0)
            self.assertGreater(payload["summary"]["modified_tokens"], 0)
            duplicate_records = [
                record
                for record in payload["mapping"]["records"]
                if record["declaration"]["file"].startswith("external/")
            ]
            self.assertTrue(duplicate_records)
            self.assertTrue(
                all(
                    record["action"] == "preserve"
                    and record["renamed_name"] is None
                    for record in duplicate_records
                )
            )
            self.assertTrue(
                any(
                    record["action"] == "rename"
                    and record["owner_module"] == "t125_top"
                    for record in payload["mapping"]["records"]
                )
            )
            self.assertNotEqual(
                (gate / "owned/top.sv").read_bytes(),
                (root / "owned/top.sv").read_bytes(),
            )
            for relative in ("external/bare.sv", "external/lib.sv"):
                self.assertEqual(
                    (gate / relative).read_bytes(),
                    (root / relative).read_bytes(),
                )

            gate_source_set = replace(source_set, source_root=gate.resolve())
            real_compile_view = source_catalog_module._compile_view
            with mock.patch(
                "rtl_obfuscator.source_catalog._compile_view",
                wraps=real_compile_view,
            ) as compile_view:
                original_catalog = build_source_catalog(source_set)
                gate_catalog = build_source_catalog(gate_source_set)
            self.assertEqual(compile_view.call_count, 2)
            self.assertEqual(
                [call.kwargs["top"] for call in compile_view.call_args_list],
                [TOP, TOP],
            )
            self.assertEqual(
                [item.name for item in original_catalog.readonly_duplicate_inventory],
                ["t125_duplicate"],
            )
            self.assertEqual(
                [item.name for item in gate_catalog.readonly_duplicate_inventory],
                ["t125_duplicate"],
            )
            self.assertIs(original_catalog.catalog_compilation, original_catalog.top_compilation)
            self.assertIs(gate_catalog.catalog_compilation, gate_catalog.top_compilation)

            restored = output_root / "restored"
            decrypted = self._run(
                PUBLIC_DECRYPT,
                "--map",
                str(gate / "mapping.json"),
                "--gate-dir",
                str(gate),
                "--output-dir",
                str(restored),
            )
            self.assertEqual(decrypted.returncode, 0, decrypted.stderr)
            for relative in (
                "owned/top.sv",
                "external/bare.sv",
                "external/lib.sv",
            ):
                self.assertEqual(
                    (restored / relative).read_bytes(),
                    (root / relative).read_bytes(),
                )


if __name__ == "__main__":
    unittest.main()
