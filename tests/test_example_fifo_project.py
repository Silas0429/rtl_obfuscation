"""Black-box T020 FIFO project and per-file mapping regression tests."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


CATEGORIES = {
    "signals": (14, 67),
    "parameters": (9, 51),
    "enum_values": (3, 6),
    "genvars": (2, 10),
    "functions": (1, 4),
    "tasks": (1, 2),
    "arguments": (3, 7),
    "instances": (2, 2),
    "generate_blocks": (2, 2),
    "typedefs": (2, 6),
    "struct_types": (2, 4),
    "struct_fields": (2, 4),
    "union_fields": (2, 6),
    "modules": (2, 4),
    "ports": (17, 59),
    "interfaces": (1, 2),
    "interface_instances": (1, 15),
    "interface_ports": (9, 39),
    "modports": (2, 2),
}


def run_encrypt(repository: Path, root: Path, output: Path, mapping: Path,
                 metrics: Path, maps: Path | None, categories: list[str]) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        "-m",
        "rtl_obfuscator.rewrite",
        "encrypt-project",
        "--filelist",
        str(root / "design.f"),
        "--source-root",
        str(root),
        "--output-dir",
        str(output),
        "--map",
        str(mapping),
        "--metrics",
        str(metrics),
        "--top",
        "fifo_top",
    ]
    if maps is not None:
        command.extend(["--file-map-dir", str(maps)])
    for category in categories:
        command.extend(["--category", category])
    command.extend(["--name-length", "8"])
    return subprocess.run(
        command,
        cwd=repository,
        capture_output=True,
        text=True,
        check=False,
    )


class ExampleFifoProjectTest(unittest.TestCase):
    def test_full_project_and_all_single_category_debug_runs(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        root = repository / "rtl_samples" / "example_fifo"
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            gate = base / "gate"
            maps = base / "maps"
            mapping_file = base / "mapping.json"
            metrics_file = base / "metrics.json"
            full = run_encrypt(
                repository,
                root,
                gate,
                mapping_file,
                metrics_file,
                maps,
                [
                    "all",
                    "modules",
                    "ports",
                    "interfaces",
                    "interface_instances",
                    "interface_ports",
                    "modports",
                ],
            )
            self.assertEqual(full.returncode, 0, full.stderr)
            self.assertEqual(json.loads(full.stdout), {
                "files": 4,
                "mapping_entries": 77,
                "modified_tokens": 292,
            })
            mapping = json.loads(mapping_file.read_text(encoding="utf-8"))
            self.assertEqual(mapping["version"], 2)
            self.assertEqual(mapping["top"], "fifo_top")
            self.assertEqual({e["category"] for e in mapping["entries"]}, set(CATEGORIES))

            all_occurrences = set()
            for entry in mapping["entries"]:
                for role, record in [("declaration", entry["declaration"])] + [
                    ("reference", record) for record in entry["references"]
                ]:
                    gold = (root / record["file"]).read_bytes()
                    self.assertEqual(
                        gold[record["start"] : record["end"]],
                        entry["original_name"].encode(),
                    )
                    all_occurrences.add((
                        entry["category"], entry["scope"], role,
                        record["file"], record["start"], record["end"],
                    ))
            per_file_occurrences = set()
            self.assertEqual(sorted(p.name for p in maps.glob("*.json")), [
                "fifo_ctrl.json", "fifo_if.json", "fifo_storage.json", "fifo_top.json",
            ])
            for map_file in maps.glob("*.json"):
                per_file = json.loads(map_file.read_text(encoding="utf-8"))
                self.assertEqual(per_file["version"], 1)
                self.assertEqual(per_file["top"], "fifo_top")
                self.assertEqual(per_file["summary"]["entries"], len(per_file["entries"]))
                self.assertEqual(per_file["summary"]["occurrences"], len(per_file["entries"]))
                for item in per_file["entries"]:
                    self.assertIn(item["role"], {"declaration", "reference"})
                    per_file_occurrences.add((
                        item["category"], item["scope"], item["role"], per_file["file"],
                        item["range"]["start"], item["range"]["end"],
                    ))
            self.assertEqual(per_file_occurrences, all_occurrences)
            metrics = json.loads(metrics_file.read_text(encoding="utf-8"))
            self.assertEqual(metrics["symbols"]["coverage"], 1.0)
            self.assertEqual(metrics["occurrences"], {
                "renamed": 292, "eligible": 292, "coverage": 1.0,
            })
            self.assertEqual(metrics["plaintext_leakage_rate"], 0.0)
            self.assertEqual(metrics["effective_coverage"], 1.0)

            decrypt = subprocess.run(
                [
                    sys.executable, "-m", "rtl_obfuscator.rewrite", "decrypt-project",
                    "--gate-dir", str(gate), "--source-root", str(root),
                    "--map", str(mapping_file), "--output-dir", str(base / "restored"),
                ],
                cwd=repository, capture_output=True, text=True, check=False,
            )
            self.assertEqual(decrypt.returncode, 0, decrypt.stderr)
            for source_file in root.glob("*.sv"):
                self.assertEqual(
                    source_file.read_bytes(),
                    (base / "restored" / source_file.name).read_bytes(),
                )

            frontend_code = f"""import pathlib, pyslang
c=pyslang.ast.Compilation()
for f in [pathlib.Path({str(gate)!r}) / x.strip() for x in pathlib.Path({str(root / 'design.f')!r}).read_text().splitlines() if x.strip()]:
    c.addSyntaxTree(pyslang.syntax.SyntaxTree.fromFile(str(f)))
assert not any(d.isError() for d in c.getAllDiagnostics())
"""
            frontend = subprocess.run(
                [sys.executable, "-c", frontend_code],
                cwd=repository, capture_output=True, text=True, check=False,
            )
            self.assertEqual(frontend.returncode, 0, frontend.stderr)
            for gate_file in sorted(gate.glob("*.sv")):
                verible = subprocess.run(
                    ["verible-verilog-syntax", str(gate_file)],
                    cwd=repository, capture_output=True, text=True, check=False,
                )
                self.assertEqual(verible.returncode, 0, verible.stderr)
            iverilog = subprocess.run(
                [
                    "iverilog", "-g2012", "-s", "fifo_top", "-o", str(base / "fifo.out"),
                    *(str(gate / line.strip()) for line in (root / "design.f").read_text().splitlines() if line.strip()),
                ],
                cwd=repository, capture_output=True, text=True, check=False,
            )
            self.assertEqual(iverilog.returncode, 0, iverilog.stderr)

            for category, (entries_expected, tokens_expected) in CATEGORIES.items():
                category_base = base / "debug" / category
                result = run_encrypt(
                    repository,
                    root,
                    category_base / "gate",
                    category_base / "mapping.json",
                    category_base / "metrics.json",
                    category_base / "maps",
                    [category],
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout), {
                    "files": 4,
                    "mapping_entries": entries_expected,
                    "modified_tokens": tokens_expected,
                })
                category_mapping = json.loads(
                    (category_base / "mapping.json").read_text(encoding="utf-8")
                )
                self.assertEqual(
                    {e["category"] for e in category_mapping["entries"]},
                    {category},
                )

            rejected = run_encrypt(
                repository,
                root,
                base / "rejected" / "gate",
                base / "rejected" / "mapping.json",
                base / "rejected" / "metrics.json",
                None,
                ["modport_ports"],
            )
            self.assertNotEqual(rejected.returncode, 0)


if __name__ == "__main__":
    unittest.main()
