from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
FIXTURE = REPOSITORY / "tests" / "fixtures" / "t034_profile_scope"
DEFAULT_CATEGORIES = (
    "signals",
    "parameters",
    "enum_values",
    "genvars",
    "functions",
    "tasks",
    "arguments",
    "instances",
    "generate_blocks",
    "typedefs",
    "struct_types",
    "struct_fields",
    "union_fields",
)
REQUIRES_PROJECT_ROOT = (
    "modules",
    "ports",
    "interfaces",
    "interface_instances",
    "interface_ports",
    "modports",
    "struct",
    "interface",
)


class SingleFileDefaultProfileTests(unittest.TestCase):
    def _run(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "rtl_obfuscator.rewrite", *arguments],
            cwd=REPOSITORY,
            capture_output=True,
            text=True,
            check=False,
        )

    @staticmethod
    def _manifest(root: Path, files: list[str]) -> str:
        payload = "".join(
            f"{hashlib.sha256((root / name).read_bytes()).hexdigest()}  {name}\n"
            for name in sorted(files)
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _normalized(mapping: dict) -> list[dict]:
        return [
            {
                "category": item["category"],
                "scope": item["scope"],
                "original_name": item["original_name"],
                "declaration": item["declaration"],
                "references": item["references"],
                "occurrences": 1 + len(item["references"]),
            }
            for item in mapping["entries"]
        ]

    @staticmethod
    def _apply_mapping(
        source: bytes, entries: list[dict], relative_file: str | None = None
    ) -> bytes:
        edits = [
            (record, item["renamed_name"].encode("utf-8"))
            for item in entries
            for record in [item["declaration"], *item["references"]]
            if relative_file is None or record["file"] == relative_file
        ]
        result = source
        for record, replacement in sorted(
            edits, key=lambda item: item[0]["start"], reverse=True
        ):
            result = (
                result[: record["start"]]
                + replacement
                + result[record["end"] :]
            )
        return result

    def _single_encrypt(self, root: Path, category: list[str]) -> tuple[dict, dict]:
        completed = self._run(
            "encrypt",
            "--input",
            str(FIXTURE / "child.sv"),
            "--output",
            str(root / "gate.sv"),
            "--map",
            str(root / "mapping.json"),
            "--metrics",
            str(root / "metrics.json"),
            *sum((["--category", item] for item in category), []),
            "--name-length",
            "8",
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return (
            json.loads((root / "mapping.json").read_text()),
            json.loads((root / "metrics.json").read_text()),
        )

    def _filelist_encrypt(self, root: Path, category: list[str]) -> tuple[dict, dict]:
        completed = self._run(
            "encrypt-project",
            "--filelist",
            str(FIXTURE / "design.f"),
            "--source-root",
            str(FIXTURE),
            "--top",
            "t034_top",
            "--output-dir",
            str(root / "gate"),
            "--map",
            str(root / "mapping.json"),
            "--metrics",
            str(root / "metrics.json"),
            *sum((["--category", item] for item in category), []),
            "--name-length",
            "8",
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return (
            json.loads((root / "mapping.json").read_text()),
            json.loads((root / "metrics.json").read_text()),
        )

    def _assert_ranges(self, mapping: dict, source_root: Path) -> None:
        for item in mapping["entries"]:
            source = (source_root / item["declaration"]["file"]).read_bytes()
            for record in [item["declaration"], *item["references"]]:
                self.assertEqual(
                    source[record["start"] : record["end"]],
                    item["original_name"].encode("utf-8"),
                )

    def test_fixture_manifest_and_single_file_oracle(self) -> None:
        self.assertEqual(
            self._manifest(FIXTURE, ["child.sv", "top.sv", "unused.sv"]),
            "d51a7d1a4d938590c05561ece451f70060f96393f3136d3e0f33ba021b416a3e",
        )
        expected = [
            {
                "category": "signals",
                "scope": "t034_child",
                "original_name": "child_state",
                "declaration": {"file": str(FIXTURE / "child.sv"), "start": 75, "end": 86},
                "references": [
                    {"file": str(FIXTURE / "child.sv"), "start": 177, "end": 188},
                    {"file": str(FIXTURE / "child.sv"), "start": 217, "end": 228},
                ],
                "occurrences": 3,
            },
            {
                "category": "signals",
                "scope": "t034_child",
                "original_name": "child_signal",
                "declaration": {"file": str(FIXTURE / "child.sv"), "start": 98, "end": 110},
                "references": [
                    {"file": str(FIXTURE / "child.sv"), "start": 124, "end": 136},
                    {"file": str(FIXTURE / "child.sv"), "start": 191, "end": 203},
                ],
                "occurrences": 3,
            },
        ]
        with TemporaryDirectory(prefix="rtl-obfuscation-t034-single-") as temporary:
            mapping, metrics = self._single_encrypt(Path(temporary), ["all"])
            self.assertEqual(mapping["version"], 1)
            self.assertEqual(self._normalized(mapping), expected)
            self.assertEqual(metrics["symbols"], {"renamed": 2, "eligible": 2, "coverage": 1.0})
            self.assertEqual(metrics["occurrences"], {"renamed": 6, "eligible": 6, "coverage": 1.0})
            self.assertEqual(metrics["plaintext_leakage_rate"], 0.0)
            self.assertEqual(metrics["effective_coverage"], 1.0)
            self._assert_ranges(mapping, FIXTURE)
            self.assertEqual(
                (Path(temporary) / "gate.sv").read_bytes(),
                self._apply_mapping((FIXTURE / "child.sv").read_bytes(), mapping["entries"]),
            )

            restored = Path(temporary) / "restored.sv"
            completed = self._run(
                "decrypt",
                "--input",
                str(Path(temporary) / "gate.sv"),
                "--output",
                str(restored),
                "--map",
                str(Path(temporary) / "mapping.json"),
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(restored.read_bytes(), (FIXTURE / "child.sv").read_bytes())

    def test_filelist_oracle_scope_determinism_and_decrypt(self) -> None:
        expected = [
            ("signals", "t034_child", "child_state", "child.sv", 75, 86, ((177, 188), (217, 228))),
            ("signals", "t034_child", "child_signal", "child.sv", 98, 110, ((124, 136), (191, 203))),
            ("signals", "t034_top", "top_state", "top.sv", 73, 82, ((142, 151), (176, 185))),
            ("instances", "t034_top", "u_child", "top.sv", 100, 107, ()),
            ("signals", "t034_unused", "unused_state", "unused.sv", 73, 85, ((99, 111), (132, 144))),
        ]
        normalized_expected = [
            {
                "category": category,
                "scope": scope,
                "original_name": name,
                "declaration": {"file": file, "start": start, "end": end},
                "references": [
                    {"file": file, "start": ref_start, "end": ref_end}
                    for ref_start, ref_end in references
                ],
                "occurrences": 1 + len(references),
            }
            for category, scope, name, file, start, end, references in expected
        ]
        with TemporaryDirectory(prefix="rtl-obfuscation-t034-filelist-") as first_tmp, TemporaryDirectory(prefix="rtl-obfuscation-t034-filelist-") as second_tmp:
            first_mapping, first_metrics = self._filelist_encrypt(Path(first_tmp), ["all"])
            second_mapping, second_metrics = self._filelist_encrypt(Path(second_tmp), ["all"])
            self.assertEqual(first_mapping["version"], 2)
            self.assertEqual(first_mapping["files"], ["child.sv", "top.sv", "unused.sv"])
            self.assertEqual(self._normalized(first_mapping), normalized_expected)
            self.assertEqual(self._normalized(first_mapping), self._normalized(second_mapping))
            self.assertEqual(first_metrics, second_metrics)
            self.assertEqual(first_metrics["symbols"], {"renamed": 5, "eligible": 5, "coverage": 1.0})
            self.assertEqual(first_metrics["occurrences"], {"renamed": 13, "eligible": 13, "coverage": 1.0})
            self.assertEqual(first_metrics["plaintext_leakage_rate"], 0.0)
            self.assertEqual(first_metrics["effective_coverage"], 1.0)
            self._assert_ranges(first_mapping, FIXTURE)
            for name in first_mapping["files"]:
                gold = (FIXTURE / name).read_bytes()
                gate = (Path(first_tmp) / "gate" / name).read_bytes()
                self.assertEqual(
                    gate,
                    self._apply_mapping(gold, first_mapping["entries"], name),
                )
            self.assertEqual(
                (Path(first_tmp) / "gate" / "design.f").read_bytes(),
                (FIXTURE / "design.f").read_bytes(),
            )

            restored = Path(first_tmp) / "restored"
            completed = self._run(
                "decrypt-project",
                "--gate-dir",
                str(Path(first_tmp) / "gate"),
                "--source-root",
                str(FIXTURE),
                "--map",
                str(Path(first_tmp) / "mapping.json"),
                "--output-dir",
                str(restored),
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            for name in first_mapping["files"]:
                self.assertEqual((restored / name).read_bytes(), (FIXTURE / name).read_bytes())

    def test_filelist_gate_frontends_and_formal_positive_negative(self) -> None:
        with TemporaryDirectory(prefix="rtl-obfuscation-t034-formal-") as temporary:
            root = Path(temporary)
            mapping, _ = self._filelist_encrypt(root, ["all"])
            gate = root / "gate"
            frontend = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import pathlib, pyslang, sys; root=pathlib.Path(sys.argv[1]); c=pyslang.ast.Compilation(); [c.addSyntaxTree(pyslang.syntax.SyntaxTree.fromFile(str(root / f))) for f in root.joinpath('design.f').read_text().splitlines() if f.strip()]; assert not any(d.isError() for d in c.getAllDiagnostics())",
                    str(gate),
                ],
                cwd=REPOSITORY,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(frontend.returncode, 0, frontend.stderr)
            for source in (gate / "child.sv", gate / "top.sv", gate / "unused.sv"):
                verible = subprocess.run(
                    ["verible-verilog-syntax", str(source)],
                    cwd=REPOSITORY,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(verible.returncode, 0, verible.stderr)
            iverilog = subprocess.run(
                [
                    "iverilog",
                    "-g2012",
                    "-t",
                    "null",
                    "-s",
                    "t034_top",
                    str(gate / "child.sv"),
                    str(gate / "top.sv"),
                    str(gate / "unused.sv"),
                ],
                cwd=REPOSITORY,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(iverilog.returncode, 0, iverilog.stderr)

            formal_arguments = [
                "scripts/formal_equivalence.py",
                "--gold-filelist",
                str(FIXTURE / "design.f"),
                "--gold-root",
                str(FIXTURE),
                "--gate-filelist",
                str(gate / "design.f"),
                "--gate-root",
                str(gate),
                "--top",
                "t034_top",
            ]
            positive = subprocess.run(
                [sys.executable, *formal_arguments],
                cwd=REPOSITORY,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(positive.returncode, 0, positive.stderr)
            self.assertEqual(json.loads(positive.stdout)["formal_equivalence"], "pass")
            self.assertEqual(json.loads(positive.stdout)["top"], "t034_top")

            negative_gate = root / "negative-gate"
            shutil.copytree(gate, negative_gate)
            top_state = next(
                item["renamed_name"]
                for item in mapping["entries"]
                if item["original_name"] == "top_state"
            )
            negative_source = (negative_gate / "top.sv").read_text()
            self.assertIn(f"assign q = {top_state};", negative_source)
            (negative_gate / "top.sv").write_text(
                negative_source.replace(
                    f"assign q = {top_state};", f"assign q = ~{top_state};", 1
                )
            )
            negative_arguments = [
                *formal_arguments[:1],
                "--gold-filelist",
                str(FIXTURE / "design.f"),
                "--gold-root",
                str(FIXTURE),
                "--gate-filelist",
                str(negative_gate / "design.f"),
                "--gate-root",
                str(negative_gate),
                "--top",
                "t034_top",
            ]
            negative = subprocess.run(
                [sys.executable, *negative_arguments],
                cwd=REPOSITORY,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(negative.returncode, 0)
            failure = negative.stdout + negative.stderr
            self.assertIn("equiv_status -assert", failure)
            self.assertIn("$equiv", failure)
            self.assertIn("unproven $equiv", failure.lower())

    def test_debug_and_multi_abi_rejection_are_fail_closed(self) -> None:
        with TemporaryDirectory(prefix="rtl-obfuscation-t034-debug-") as temporary:
            root = Path(temporary)
            completed = self._run(
                "encrypt-project",
                "--filelist",
                str(FIXTURE / "design.f"),
                "--source-root",
                str(FIXTURE),
                "--top",
                "t034_top",
                "--debug",
                str(root / "debug"),
                "--name-length",
                "8",
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            summary = json.loads(completed.stdout)
            self.assertEqual(summary["category_count"], 13)
            self.assertEqual([item["category"] for item in summary["runs"]], list(DEFAULT_CATEGORIES))

        for mode in ("single",):
            for category in REQUIRES_PROJECT_ROOT:
                with self.subTest(mode=mode, category=category), TemporaryDirectory(prefix="rtl-obfuscation-t034-reject-") as temporary:
                    root = Path(temporary)
                    sentinel = b"sentinel"
                    if mode == "single":
                        output = root / "gate.sv"
                        arguments = [
                            "encrypt",
                            "--input",
                            str(FIXTURE / "child.sv"),
                            "--output",
                            str(output),
                            "--map",
                            str(root / "mapping.json"),
                            "--metrics",
                            str(root / "metrics.json"),
                            "--category",
                            category,
                            "--name-length",
                            "8",
                        ]
                        outputs = [output, root / "mapping.json", root / "metrics.json"]
                    else:
                        output = root / "gate"
                        output.mkdir()
                        (output / "sentinel").write_bytes(sentinel)
                        arguments = [
                            "encrypt-project",
                            "--filelist",
                            str(FIXTURE / "design.f"),
                            "--source-root",
                            str(FIXTURE),
                            "--top",
                            "t034_top",
                            "--output-dir",
                            str(output),
                            "--map",
                            str(root / "mapping.json"),
                            "--metrics",
                            str(root / "metrics.json"),
                            "--category",
                            category,
                            "--name-length",
                            "8",
                        ]
                        outputs = [root / "mapping.json", root / "metrics.json"]
                    for path in outputs:
                        path.write_bytes(sentinel)
                    completed = self._run(*arguments)
                    self.assertNotEqual(completed.returncode, 0)
                    self.assertIn("CATEGORY_REQUIRES_PROJECT_ROOT", completed.stderr)
                    self.assertEqual(completed.stdout, "")
                    for path in outputs:
                        self.assertEqual(path.read_bytes(), sentinel)
                    if mode == "filelist":
                        self.assertEqual((output / "sentinel").read_bytes(), sentinel)

        for mode in ("single", "filelist"):
            with self.subTest(mode=mode), TemporaryDirectory(prefix="rtl-obfuscation-t034-mixed-") as temporary:
                root = Path(temporary)
                if mode == "single":
                    arguments = [
                        "encrypt",
                        "--input",
                        str(FIXTURE / "child.sv"),
                        "--output",
                        str(root / "gate.sv"),
                        "--map",
                        str(root / "mapping.json"),
                        "--metrics",
                        str(root / "metrics.json"),
                    ]
                else:
                    arguments = [
                        "encrypt-project",
                        "--filelist",
                        str(FIXTURE / "design.f"),
                        "--source-root",
                        str(FIXTURE),
                        "--top",
                        "t034_top",
                        "--output-dir",
                        str(root / "gate"),
                        "--map",
                        str(root / "mapping.json"),
                        "--metrics",
                        str(root / "metrics.json"),
                    ]
                arguments.extend(("--category", "all", "--category", "ports", "--name-length", "8"))
                completed = self._run(*arguments)
                if mode == "single":
                    self.assertNotEqual(completed.returncode, 0)
                    self.assertIn("CATEGORY_REQUIRES_PROJECT_ROOT", completed.stderr)
                    self.assertEqual(completed.stdout, "")
                else:
                    self.assertEqual(completed.returncode, 0, completed.stderr)
                    self.assertEqual(json.loads(completed.stdout)["files"], 3)
                    self.assertEqual(
                        json.loads((root / "mapping.json").read_text())["version"],
                        4,
                    )


if __name__ == "__main__":
    unittest.main()
