from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from rtl_obfuscator.source_set import infer_filelist_root


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "t119_multi_root_filelist"
CHILD = FIXTURE / "rtl" / "child.sv"
PUBLIC_ENCRYPT = ROOT / "rtl_encrypt.py"
PUBLIC_DECRYPT = ROOT / "rtl_decrypt.py"
FORMAL = ROOT / "scripts" / "formal_equivalence.py"


class T119FilelistMultiRootOutputTests(unittest.TestCase):
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
    def _root_relative(path: Path) -> str:
        return path.resolve().relative_to(Path("/")).as_posix()

    def _make_filelist(self, root: Path) -> tuple[Path, Path, tuple[str, str]]:
        top = root / "top.sv"
        top.write_text(
            "module t119_top (input logic i, output logic o);\n"
            "    logic top_signal;\n"
            "    t119_child u_child(.i(i), .o(top_signal));\n"
            "    assign o = top_signal;\n"
            "endmodule\n",
            encoding="utf-8",
        )
        filelist = root / "design.f"
        filelist.write_text(
            f"{CHILD.resolve()}\n{top.resolve()}\n",
            encoding="utf-8",
        )
        return filelist, top, (self._root_relative(CHILD), self._root_relative(top))

    def test_multi_root_public_gate_restore_formal_and_boundaries(self):
        with tempfile.TemporaryDirectory(prefix="t119-multi-root-") as temporary:
            root = Path(temporary)
            filelist, top, files = self._make_filelist(root)
            self.assertEqual(infer_filelist_root(filelist=filelist), Path("/"))
            original = {file: Path("/").joinpath(file).read_bytes() for file in files}

            gate = root / "test01"
            encrypted = self._run(
                PUBLIC_ENCRYPT,
                "--filelist", str(filelist),
                "--top", "t119_top",
                "--category", "all",
                "--output-dir", str(gate),
            )
            self.assertEqual(encrypted.returncode, 0, encrypted.stderr)
            summary = json.loads(encrypted.stdout)
            self.assertEqual(summary["schema_version"], 2)
            self.assertGreater(summary["summary"]["rename"], 0)
            self.assertGreater(summary["summary"]["modified_tokens"], 0)
            self.assertTrue(summary["summary"]["strict_compile_passed"])
            self.assertTrue(summary["summary"]["restored_byte_identical"])

            self.assertEqual(
                (gate / "design.f").read_text(encoding="utf-8").splitlines(),
                [(gate / file).resolve().as_posix() for file in files],
            )
            self.assertEqual(
                (gate / "export_design.f").read_text(encoding="utf-8").splitlines(),
                [f"$OUT/{file}" for file in files],
            )
            self.assertEqual(
                (gate / "original_design.f").read_text(encoding="utf-8").splitlines(),
                [(Path("/") / file).resolve().as_posix() for file in files],
            )
            self.assertTrue(
                any((gate / file).read_bytes() != original[file] for file in files)
            )
            mapping = json.loads((gate / "mapping.json").read_text(encoding="utf-8"))
            self.assertEqual(mapping["source_set"]["origin"], "filelist")
            self.assertEqual(mapping["source_set"]["compile_order"], list(files))
            self.assertEqual(
                mapping["mapping_execution"]["input_manifest"],
                mapping["mapping_execution"]["restored_manifest"],
            )
            for entry in mapping["mapping_execution"]["gate_manifest"]:
                self.assertIn(entry["file"], files)

            restored = root / "restored"
            decrypted = self._run(
                PUBLIC_DECRYPT,
                "--map", str(gate / "mapping.json"),
                "--gate-dir", str(gate),
                "--output-dir", str(restored),
            )
            self.assertEqual(decrypted.returncode, 0, decrypted.stderr)
            for file in files:
                self.assertEqual((restored / file).read_bytes(), original[file])

            formal_arguments = (
                "--gold-filelist", str(filelist),
                "--gold-root", "/",
                "--gate-filelist", str(gate / "design.f"),
                "--gate-root", str(gate),
                "--top", "t119_top",
                "--seq", "5",
            )
            positive = self._run(FORMAL, *formal_arguments)
            self.assertEqual(positive.returncode, 0, positive.stdout + positive.stderr)
            self.assertEqual(
                json.loads(positive.stdout.strip().splitlines()[-1])["formal_equivalence"],
                "pass",
            )
            positive_json = json.loads(positive.stdout.strip().splitlines()[-1])
            print(
                "T119_FORMAL_POSITIVE "
                + json.dumps(
                    {
                        "gold_filelist": str(filelist),
                        "gold_root": "/",
                        "gate_filelist": str(gate / "design.f"),
                        "gate_root": str(gate),
                        "top": "t119_top",
                        "seq": 5,
                        "exit": positive.returncode,
                        "json": positive_json,
                    },
                    sort_keys=True,
                )
            )

            negative = root / "negative"
            shutil.copytree(gate, negative)
            negative_design = negative / "design.f"
            negative_design.write_text(
                negative_design.read_text(encoding="utf-8").replace(
                    gate.resolve().as_posix(), negative.resolve().as_posix()
                ),
                encoding="utf-8",
            )
            target = negative / files[0]
            mutated = target.read_bytes().replace(b" ^ ", b" | ", 1)
            self.assertNotEqual(mutated, target.read_bytes())
            target.write_bytes(mutated)
            strict = subprocess.run(
                [
                    "iverilog", "-g2012", "-t", "null", "-s", "t119_top",
                    *[str(negative / file) for file in files],
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
            self.assertEqual(strict.returncode, 0, strict.stdout + strict.stderr)
            failed = self._run(
                FORMAL,
                "--gold-filelist", str(filelist),
                "--gold-root", "/",
                "--gate-filelist", str(negative_design),
                "--gate-root", str(negative),
                "--top", "t119_top",
                "--seq", "5",
            )
            self.assertNotEqual(failed.returncode, 0)
            evidence = (failed.stdout + failed.stderr).lower()
            self.assertIn("unproven", evidence)
            self.assertIn("equiv_status -assert", evidence)
            print(
                "T119_FORMAL_NEGATIVE "
                + json.dumps(
                    {
                        "gold_filelist": str(filelist),
                        "gold_root": "/",
                        "gate_filelist": str(negative / "design.f"),
                        "gate_root": str(negative),
                        "top": "t119_top",
                        "seq": 5,
                        "strict_compile_exit": strict.returncode,
                        "formal_exit": failed.returncode,
                        "mutation": "XOR -> OR in actual gate child.sv",
                        "evidence": "unproven; equiv_status -assert",
                    },
                    sort_keys=True,
                )
            )

            existing = root / "existing"
            existing.mkdir()
            result = self._run(
                PUBLIC_ENCRYPT, "--filelist", str(filelist), "--top", "t119_top",
                "--category", "all", "--output-dir", str(existing),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("CLI_VNEXT_OUTPUT_INVALID", result.stderr)

            missing_parent = root / "missing" / "output"
            result = self._run(
                PUBLIC_ENCRYPT, "--filelist", str(filelist), "--top", "t119_top",
                "--category", "all", "--output-dir", str(missing_parent),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("CLI_VNEXT_OUTPUT_INVALID", result.stderr)
            self.assertFalse((root / "missing").exists())

            conflict_parent = root / "conflict"
            conflict_parent.mkdir()
            conflict_output = conflict_parent / "nested"
            result = self._run(
                PUBLIC_ENCRYPT, "--filelist", str(filelist), "--top", "t119_top",
                "--category", "all", "--output-dir", str(conflict_output),
                "--map", str(conflict_output),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("CLI_VNEXT_OUTPUT_INVALID", result.stderr)
            self.assertFalse(conflict_output.exists())

            symlink_output = root / "symlink-output"
            symlink_output.symlink_to(root / "dangling-target", target_is_directory=True)
            result = self._run(
                PUBLIC_ENCRYPT, "--filelist", str(filelist), "--top", "t119_top",
                "--category", "all", "--output-dir", str(symlink_output),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("CLI_VNEXT_OUTPUT_INVALID", result.stderr)
            self.assertTrue(symlink_output.is_symlink())

            project_root = root / "project"
            project_root.mkdir()
            project_top = project_root / "top.sv"
            project_top.write_bytes(top.read_bytes())
            project_child = project_root / "child.sv"
            project_child.write_bytes(CHILD.read_bytes())
            project_output = project_root / "forbidden"
            result = self._run(
                PUBLIC_ENCRYPT, "--source-root", str(project_root), "--top", "t119_top",
                "--category", "all", "--output-dir", str(project_output),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("CLI_VNEXT_OUTPUT_INVALID", result.stderr)


if __name__ == "__main__":
    unittest.main()
