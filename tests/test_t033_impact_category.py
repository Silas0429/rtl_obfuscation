from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
FIXTURE = REPOSITORY / "tests" / "fixtures" / "t033_impact_category"
ALL_CATEGORIES = (
    "signals",
    "ports",
    "instances",
    "struct",
    "interface",
    "enum_values",
    "genvars",
    "functions",
    "tasks",
    "arguments",
    "generate_blocks",
    "typedefs",
    "union_fields",
    "parameters",
)


class ImpactCategoryOracleTests(unittest.TestCase):
    def _run(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "rtl_obfuscator.rewrite", *arguments],
            cwd=REPOSITORY,
            capture_output=True,
            text=True,
            check=False,
        )

    def _report(self, categories: tuple[str, ...] = ALL_CATEGORIES) -> tuple[Path, dict]:
        temporary = tempfile.TemporaryDirectory(prefix="rtl-obfuscation-t033-")
        self.addCleanup(temporary.cleanup)
        report_path = Path(temporary.name) / "report.json"
        args = [
            "inspect-project",
            "--project-root",
            str(FIXTURE),
            "--top",
            "t033_top",
            "--report",
            str(report_path),
        ]
        for category in categories:
            args.extend(("--category", category))
        completed = self._run(*args)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return report_path, json.loads(report_path.read_text())

    @staticmethod
    def _manifest(root: Path, files: list[str]) -> str:
        content = "".join(
            f"{hashlib.sha256((root / path).read_bytes()).hexdigest()}  {path}\n"
            for path in sorted(files)
        )
        return hashlib.sha256(content.encode()).hexdigest()

    @staticmethod
    def _digest(entries: list[dict]) -> tuple[str, int, int]:
        normalized = [
            {
                "category": entry["category"],
                "scope": entry["scope"],
                "name": entry["name"],
                "declaration": entry["declaration"],
                "references": entry["references"],
                "occurrences": entry["occurrences"],
            }
            for entry in entries
        ]
        normalized.sort(
            key=lambda entry: (
                entry["category"],
                entry["scope"],
                entry["declaration"]["file"] if entry["declaration"] else "\uffff",
                entry["declaration"]["start"] if entry["declaration"] else 2**63,
                entry["name"],
            )
        )
        digest = hashlib.sha256(
            json.dumps(
                normalized,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        return digest, len(normalized), sum(item["occurrences"] for item in normalized)

    def test_fixture_closure_and_determinism(self) -> None:
        first_path, first = self._report()
        second_path, second = self._report()
        self.assertEqual(first_path.read_bytes(), second_path.read_bytes())
        self.assertEqual(first["status"], "pass")
        self.assertEqual(first["candidate_files"], ["bus_if.sv", "child.sv", "decoy.sv", "shared.sv", "top.sv"])
        self.assertEqual(first["reachable"]["files"], ["bus_if.sv", "child.sv", "shared.sv", "top.sv"])
        self.assertEqual(len(first["definitions"]), 4)
        self.assertEqual(first["reachable"]["modules"], ["t033_child", "t033_top"])
        self.assertEqual(first["reachable"]["interfaces"], ["t033_bus_if"])
        self.assertEqual(first["compile"]["parse_errors"], 0)
        self.assertEqual(first["compile"]["semantic_errors"], 0)
        self.assertEqual(
            self._manifest(FIXTURE, first["candidate_files"]),
            "07ca8b3be018cabfc14ce118791c7a8db8cbcb0618d3d243ad413de6c5e0aeea",
        )
        self.assertEqual(
            self._manifest(FIXTURE, first["reachable"]["files"]),
            "e9bca1f5787aadfe515f0b06ecb54149f536dd4ca0e6297dab1f142aea9baf9a",
        )
        self.assertEqual(first["classification"]["unreachable"], ["decoy.sv"])

    def test_raw_category_digests_and_totals(self) -> None:
        _, report = self._report()
        entries = report["inventory"]["eligible"] + report["inventory"]["preserved"]
        expected = {
            "signals": ("130583698415fd3ea8ae4f1acde19a50b048bd8e132ac8fcc9138a4aa118bd72", 8, 19),
            "ports": ("10dfd9143df6ed02ab6d016237ac301e9693523c920bc680d171023623e750fe", 5, 15),
            "instances": ("70f0ab215e2f317e7607fbc7d7adc57479435231890d7db0fe3df441e077326c", 1, 1),
            "parameters": ("0cbd6fc883f50a616d6f04dcdd696f13978d0489318b3c35cee8ab63da915222", 4, 17),
            "enum_values": ("a919b7a7c9847f8c38ee27f504ac1c24821a0150aeae02f13a94e8cf713016ef", 2, 3),
            "genvars": ("0b5b37efef2d0d44b40f5cf7cb40318230f49659f7857c81470a5258fa681941", 1, 3),
            "functions": ("84e2fe0f9aad064449ae9fd1aca1e2e7277446742e2d386a6c9058bbc2fbb184", 1, 2),
            "tasks": ("c978d61712bae393acaa3739dd306ad6968f8df7eb171791908c47c5b57b81e3", 1, 1),
            "arguments": ("0a92bd75409260d7e87882265a2c73d8f1a954e6567e77818462705779466078", 2, 4),
            "generate_blocks": ("47b3cd7207a52b87b369e4184cc64b583693de8d8b6054265d30792d753792f1", 1, 1),
            "typedefs": ("8a69afedcaa17286a033536282d607f158917e7c30bc4cc230af61733fbc178b", 1, 2),
            "union_fields": ("0ca545b00c188926b7485dbf6535d37d57dcd4a7350f5e0c5c9a4a89909b917d", 2, 3),
        }
        for category, oracle in expected.items():
            self.assertEqual(self._digest([x for x in entries if x["category"] == category]), oracle)
        self.assertEqual(
            self._digest([x for x in entries if x["category"] in {"struct_types", "struct_fields"}]),
            ("e74de69c66a5b29f3f662d36a14e33549c48e849d145ef08c4309ca427b9beb2", 6, 12),
        )
        self.assertEqual(
            self._digest([x for x in entries if x["category"] in {"interfaces", "interface_instances", "interface_ports", "modports"}]),
            ("535c43fa758201bc76c4d7f88be6b74a5dcdc6cf95753c369235e5fd1bd50e26", 4, 12),
        )
        self.assertEqual(self._digest(entries), ("1988aa06350cff1e4cb4a23cccb4a8734f513cabd666b56f8bddcc3b56bc1395", 39, 95))

    def test_classification_profiles_and_ownership(self) -> None:
        _, report = self._report()
        classification = report["classification"]
        self.assertEqual(
            {k: (v["entries"], v["occurrences"]) for k, v in classification.items() if isinstance(v, dict) and "entries" in v},
            {
                "default_profile": (25, 46),
                "manual_multi_module": (12, 38),
                "top_abi_preserved": (4, 12),
            },
        )
        default = classification["default_profile"]["items"]
        manual = classification["manual_multi_module"]["items"]
        top_abi = classification["top_abi_preserved"]["items"]
        self.assertTrue(all(item["default_eligible"] and not item["project_root_manual"] for item in default))
        self.assertTrue(all(not item["default_eligible"] and item["project_root_manual"] for item in manual))
        self.assertTrue(all(not item["default_eligible"] and not item["project_root_manual"] and item["abi"] == "top_abi" for item in top_abi))
        required_fields = {
            "category", "scope", "name", "impact", "abi", "default_eligible",
            "project_root_manual", "declaration", "references", "occurrences",
        }
        self.assertTrue(
            all(
                required_fields <= set(item)
                for profile in (default, manual, top_abi)
                for item in profile
            )
        )
        self.assertEqual({(x["category"], x["scope"], x["name"]) for x in manual if x["category"] == "modules"}, {("modules", "t033_child", "t033_child")})
        self.assertEqual({(x["category"], x["scope"], x["name"]) for x in top_abi if x["category"] == "modules"}, {("modules", "t033_top", "t033_top")})
        args = [x for x in default if x["category"] == "arguments"]
        self.assertEqual(len(args), 2)
        self.assertNotEqual(args[0]["declaration"], args[1]["declaration"])

        ranges = set()
        for profile in ("default_profile", "manual_multi_module", "top_abi_preserved"):
            for item in classification[profile]["items"]:
                for record in ([] if item["declaration"] is None else [item["declaration"]]) + item["references"]:
                    source = (FIXTURE / record["file"]).read_bytes()
                    self.assertEqual(source[record["start"] : record["end"]], item["name"].encode())
                    key = (record["file"], record["start"], record["end"])
                    self.assertNotIn(key, ranges)
                    ranges.add(key)
        child_bus = next(x for x in manual if x["category"] == "interface_ports" and x["scope"] == "t033_child")
        top_bus = next(x for x in manual if x["category"] == "interface_instances")
        self.assertEqual({r["start"] for r in child_bus["references"]}, {360, 1102})
        self.assertEqual({r["start"] for r in top_bus["references"]}, {364, 436})

    def test_each_category_standalone_passes(self) -> None:
        for category in ALL_CATEGORIES:
            _, report = self._report((category,))
            self.assertEqual(report["status"], "pass", category)
            self.assertEqual(report["reachable"]["files"], ["bus_if.sv", "child.sv", "shared.sv", "top.sv"])


if __name__ == "__main__":
    unittest.main()
