from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from rtl_obfuscator.orchestration_vnext import run_vnext
from rtl_obfuscator.source_set import from_filelist


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "t130_fast_local_signals"
ENCRYPT = ROOT / "rtl_encrypt.py"
DECRYPT = ROOT / "rtl_decrypt.py"
FORMAL = ROOT / "scripts" / "formal_equivalence.py"


class T130FastLocalSignalsTests(unittest.TestCase):
    @staticmethod
    def _name_factory():
        counter = 0

        def factory(_symbol_id: str, length: int, unavailable: frozenset[str]) -> str:
            nonlocal counter
            while True:
                candidate = f"z{counter:0{length - 1}d}"
                counter += 1
                if candidate not in unavailable:
                    return candidate

        return factory

    @staticmethod
    def _run_cli(output: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(ENCRYPT),
                "--filelist",
                str(FIXTURE / "design.f"),
                "--rewrite-root",
                str(FIXTURE / "owned"),
                "--category",
                "signals",
                "--output-dir",
                str(output),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )

    def test_public_filelist_fast_mapping_is_root_and_category_bounded(self):
        original = {
            path.relative_to(FIXTURE).as_posix(): path.read_bytes()
            for path in FIXTURE.rglob("*")
            if path.is_file()
        }
        with tempfile.TemporaryDirectory(prefix="t130-public-") as temporary:
            result = self._run_cli(Path(temporary) / "gate")
            self.assertEqual(result.returncode, 0, result.stderr)
            cli_report = json.loads(result.stdout.strip().splitlines()[-1])
            report = json.loads((Path(temporary) / "gate" / "mapping.json").read_text())
            self.assertEqual(cli_report["format"], "rtl-obfuscation.cli-vnext")
            self.assertEqual(cli_report["schema_version"], 2)
            self.assertTrue(report["summary"]["strict_compile_passed"])
            self.assertTrue(report["summary"]["restored_byte_identical"])
            self.assertEqual(report["summary"]["unsupported"], 0)
            records = report["mapping"]["records"]
            self.assertEqual({item["category"] for item in records}, {"signals"})
            self.assertEqual(
                {(item["owner_module"], item["original_name"]) for item in records},
                {
                    ("t130_leaf_a", "state"),
                    ("t130_leaf_a", "next_state"),
                    ("t130_leaf_b", "state"),
                    ("t130_top", "left_value"),
                    ("t130_top", "right_value"),
                    ("t130_top", "combined"),
                },
            )
            states = [item for item in records if item["original_name"] == "state"]
            self.assertEqual(len(states), 2)
            self.assertEqual(len({item["symbol_id"] for item in states}), 2)
            self.assertEqual(len({item["semantic_owner"] for item in states}), 2)
            for relative, data in original.items():
                if relative.startswith("external/"):
                    self.assertEqual(
                        (Path(temporary) / "gate" / relative).read_bytes(), data
                    )
            restored = Path(temporary) / "restored"
            decrypted = subprocess.run(
                [
                    sys.executable,
                    str(DECRYPT),
                    "--map",
                    str(Path(temporary) / "gate" / "mapping.json"),
                    "--gate-dir",
                    str(Path(temporary) / "gate"),
                    "--output-dir",
                    str(restored),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
            self.assertEqual(decrypted.returncode, 0, decrypted.stderr)
            decrypt_report = json.loads(decrypted.stdout.strip().splitlines()[-1])
            self.assertEqual(decrypt_report["schema_version"], 2)
            self.assertTrue(decrypt_report["summary"]["restored_byte_identical"])
            for relative, data in original.items():
                if relative.endswith((".sv", ".v")):
                    self.assertEqual((restored / relative).read_bytes(), data)

    def test_actual_gate_formal_positive_and_fixed_functional_negative(self):
        with tempfile.TemporaryDirectory(prefix="t130-formal-") as temporary:
            base = Path(temporary)
            gate = base / "gate"
            result = self._run_cli(gate)
            self.assertEqual(result.returncode, 0, result.stderr)

            # Formal deliberately excludes the read-only external context.  Keep
            # the filelist under the actual gate root so the proof uses rewritten
            # files emitted by the public flow.
            (gate / "formal.f").write_bytes((FIXTURE / "formal.f").read_bytes())
            formal_arguments = [
                "--gold-filelist",
                str(FIXTURE / "formal.f"),
                "--gold-root",
                str(FIXTURE),
                "--gate-filelist",
                str(gate / "formal.f"),
                "--gate-root",
                str(gate),
                "--top",
                "t130_top",
                "--seq",
                "5",
            ]
            positive = subprocess.run(
                [sys.executable, str(FORMAL), *formal_arguments],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
            self.assertEqual(positive.returncode, 0, positive.stdout + positive.stderr)
            self.assertEqual(
                json.loads(positive.stdout.strip().splitlines()[-1])["formal_equivalence"],
                "pass",
            )

            negative = base / "negative"
            shutil.copytree(gate, negative)
            top = negative / "owned" / "top.sv"
            original = top.read_bytes()
            self.assertEqual(original.count(b"1'b0"), 1)
            top.write_bytes(original.replace(b"1'b0", b"1'b1", 1))
            failed = subprocess.run(
                [
                    sys.executable,
                    str(FORMAL),
                    *[
                        argument.replace(str(gate), str(negative))
                        for argument in formal_arguments
                    ],
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
            combined = (failed.stdout + failed.stderr).lower()
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("unproven", combined)
            self.assertIn("equiv_status -assert", combined)

    def test_fast_path_skips_slow_catalog_index_and_forbidden_stages(self):
        source_set = from_filelist(
            filelist=FIXTURE / "design.f",
            rewrite_roots=(FIXTURE / "owned",),
        )
        stages: list[tuple[str, str]] = []
        with tempfile.TemporaryDirectory(prefix="t130-fast-") as temporary:
            with mock.patch(
                "rtl_obfuscator.orchestration_vnext.build_source_catalog",
                side_effect=AssertionError("slow source catalog was called"),
            ), mock.patch(
                "rtl_obfuscator.orchestration_vnext.build_rename_index",
                side_effect=AssertionError("slow rename index was called"),
            ):
                result = run_vnext(
                    source_set,
                    categories=("signals",),
                    name_factory=self._name_factory(),
                    gate_dir=Path(temporary) / "gate",
                    restore_dir=Path(temporary) / "restore",
                    stage_observer=lambda stage, phase: stages.append((stage, phase)),
                )
        self.assertTrue(result.to_report()["summary"]["strict_compile_passed"])
        envelope = {
            "compile",
            "rename_index",
            "mapping",
            "gate",
            "restore",
        }
        outer_stages = [
            (stage, phase) for stage, phase in stages if stage in envelope
        ]
        self.assertEqual(
            [stage for stage, _phase in outer_stages],
            [
                "compile",
                "compile",
                "rename_index",
                "rename_index",
                "mapping",
                "mapping",
                "gate",
                "gate",
                "restore",
                "restore",
            ],
        )
        self.assertEqual(
            [phase for _stage, phase in outer_stages],
            ["begin", "end"] * 5,
        )
        self.assertNotIn("compile.catalog_inventory", [stage for stage, _phase in stages])
        self.assertNotIn("compile.top_closure", [stage for stage, _phase in stages])
        self.assertNotIn("compile.owner_registry", [stage for stage, _phase in stages])
        self.assertNotIn("rename_index.semantic_inventory", [stage for stage, _phase in stages])

    def test_fast_path_never_visits_compilation_root(self):
        source_set = from_filelist(
            filelist=FIXTURE / "design.f",
            rewrite_roots=(FIXTURE / "owned",),
        )
        import rtl_obfuscator.fast_local_signals as fast

        real_compile = fast._compile_view

        class RootVisitGuard:
            def __init__(self, root):
                self._root = root

            def visit(self, *_args, **_kwargs):
                raise AssertionError("fast path visited the compilation root")

            def __getattr__(self, name):
                return getattr(self._root, name)

        def guarded_compile(*args, **kwargs):
            view = real_compile(*args, **kwargs)
            return replace(view, root=RootVisitGuard(view.root))

        with tempfile.TemporaryDirectory(prefix="t130-root-guard-") as temporary:
            with mock.patch.object(fast, "_compile_view", side_effect=guarded_compile):
                result = run_vnext(
                    source_set,
                    categories=("signals",),
                    name_factory=self._name_factory(),
                    gate_dir=Path(temporary) / "gate",
                    restore_dir=Path(temporary) / "restore",
                )
        self.assertEqual(result.to_report()["summary"]["rename"], 6)

    def test_generate_block_instance_reaches_owned_module_without_root_visit(self):
        with tempfile.TemporaryDirectory(prefix="t130-generate-") as temporary:
            project = Path(temporary)
            external = project / "external"
            owned = project / "owned"
            external.mkdir()
            owned.mkdir()
            filelist = project / "design.f"
            filelist.write_text("external/top.sv\nowned/child.sv\n", encoding="utf-8")
            (external / "top.sv").write_text(
                """module t130_generate_top(input logic clk, output logic data_o);
  generate
    if (1) begin : generated
      gen_child u_child (.clk(clk), .data_o(data_o));
    end
  endgenerate
endmodule
""",
                encoding="utf-8",
            )
            (owned / "child.sv").write_text(
                """module gen_child(input logic clk, output logic data_o);
  logic state;
  always_ff @(posedge clk)
    state <= ~state;
  assign data_o = state;
endmodule
""",
                encoding="utf-8",
            )
            source_set = from_filelist(
                filelist=filelist,
                rewrite_roots=(owned,),
            )
            import rtl_obfuscator.fast_local_signals as fast

            real_compile = fast._compile_view

            class RootVisitGuard:
                def __init__(self, root):
                    self._root = root

                def visit(self, *_args, **_kwargs):
                    raise AssertionError("fast path visited the compilation root")

                def __getattr__(self, name):
                    return getattr(self._root, name)

            def guarded_compile(*args, **kwargs):
                view = real_compile(*args, **kwargs)
                return replace(view, root=RootVisitGuard(view.root))

            with self.subTest("fast dispatch and generated child resolution"):
                with tempfile.TemporaryDirectory(prefix="t130-generate-out-") as output:
                    with mock.patch.object(fast, "_compile_view", side_effect=guarded_compile):
                        result = run_vnext(
                            source_set,
                            categories=("signals",),
                            name_factory=self._name_factory(),
                            gate_dir=Path(output) / "gate",
                            restore_dir=Path(output) / "restore",
                        )
            records = result.mapping_vnext.records
            self.assertEqual(
                [(record.owner_module, record.original_name) for record in records],
                [("gen_child", "state")],
            )
            self.assertEqual(result.to_report()["summary"]["rename"], 1)

    def test_hierarchy_discovery_uses_direct_scope_members_without_body_visit(self):
        import rtl_obfuscator.fast_local_signals as fast

        class Scope:
            def __init__(self, members):
                self._members = tuple(members)

            def __iter__(self):
                return iter(self._members)

            def visit(self, *_args, **_kwargs):
                raise AssertionError("hierarchy discovery called body.visit")

        module = type(
            "InstanceSymbol",
            (),
            {"isModule": True, "body": object()},
        )()
        non_module = type(
            "InstanceSymbol",
            (),
            {"isModule": False, "body": object()},
        )()
        instance_array = type("InstanceArraySymbol", (Scope,), {})(
            (non_module, module)
        )
        generate_array = type("GenerateBlockArraySymbol", (Scope,), {})(
            (instance_array,)
        )
        generate_block = type("GenerateBlockSymbol", (Scope,), {})(
            (generate_array,)
        )
        self.assertEqual(
            fast._direct_module_instances(Scope((generate_block,))),
            (module,),
        )

    def test_generate_for_and_instance_array_reach_owned_modules(self):
        with tempfile.TemporaryDirectory(prefix="t130-generate-array-") as temporary:
            project = Path(temporary)
            external = project / "external"
            owned = project / "owned"
            external.mkdir()
            owned.mkdir()
            modules = ("named_child", "for_child", "array_child")
            (project / "design.f").write_text(
                "external/top.sv\n"
                + "".join(f"owned/{name}.sv\n" for name in modules),
                encoding="utf-8",
            )
            (external / "top.sv").write_text(
                """module t130_generate_array_top(input logic clk);
  generate
    if (1) begin : named
      named_child u_named (.clk(clk));
    end
    for (genvar i = 0; i < 2; i++) begin : loop
      for_child u_for (.clk(clk));
    end
  endgenerate
  array_child u_array[2] (.clk(clk));
endmodule
""",
                encoding="utf-8",
            )
            for name in modules:
                (owned / f"{name}.sv").write_text(
                    f"""module {name}(input logic clk);
  logic state;
  always_ff @(posedge clk)
    state <= ~state;
endmodule
""",
                    encoding="utf-8",
                )
            source_set = from_filelist(
                filelist=project / "design.f",
                rewrite_roots=(owned,),
            )
            with tempfile.TemporaryDirectory(prefix="t130-generate-array-out-") as output:
                result = run_vnext(
                    source_set,
                    categories=("signals",),
                    name_factory=self._name_factory(),
                    gate_dir=Path(output) / "gate",
                    restore_dir=Path(output) / "restore",
                )
            self.assertEqual(
                {
                    (record.owner_module, record.original_name)
                    for record in result.mapping_vnext.records
                },
                {
                    ("named_child", "state"),
                    ("for_child", "state"),
                    ("array_child", "state"),
                },
            )

    def test_module_local_scope_excludes_ports_function_locals_and_external_objects(self):
        source_set = from_filelist(
            filelist=FIXTURE / "design.f",
            rewrite_roots=(FIXTURE / "owned",),
        )
        with tempfile.TemporaryDirectory(prefix="t130-scope-") as temporary:
            result = run_vnext(
                source_set,
                categories=("signals",),
                name_factory=self._name_factory(),
                gate_dir=Path(temporary) / "gate",
                restore_dir=Path(temporary) / "restore",
            )
        names = {record.original_name for record in result.mapping_vnext.records}
        self.assertNotIn("clk_i", names)
        self.assertNotIn("data_i", names)
        self.assertNotIn("data_o", names)
        self.assertNotIn("value", names)
        self.assertNotIn("global_state", names)
        self.assertNotIn("ready", names)
        self.assertNotIn("payload", names)
        self.assertTrue(all(record.declaration.file.startswith("owned/") for record in result.mapping_vnext.records))

    def test_non_fast_inputs_keep_the_existing_dispatch(self):
        source_set = from_filelist(
            filelist=FIXTURE / "design.f",
            rewrite_roots=(FIXTURE / "owned",),
            top="t130_top",
        )
        with tempfile.TemporaryDirectory(prefix="t130-slow-") as temporary:
            with mock.patch(
                "rtl_obfuscator.orchestration_vnext.build_source_catalog",
                side_effect=RuntimeError("t130 slow dispatch"),
            ):
                with self.assertRaisesRegex(Exception, "t130 slow dispatch"):
                    run_vnext(
                        source_set,
                        categories=("signals",),
                        gate_dir=Path(temporary) / "gate",
                        restore_dir=Path(temporary) / "restore",
                    )


if __name__ == "__main__":
    unittest.main()
