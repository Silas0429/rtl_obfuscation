"""T035 category/profile, bounded-closure, and mapping-v4 black-box checks."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from rtl_obfuscator import category_profile


REPOSITORY = Path(__file__).resolve().parents[1]
FIXTURE = REPOSITORY / "tests" / "fixtures" / "t033_impact_category"
DEFAULT = tuple(category_profile.DEFAULT_CATEGORIES)
FULL_REQUEST = (
    "all",
    "modules",
    "ports",
    "interfaces",
    "interface_instances",
    "interface_ports",
    "modports",
)


class T035ProfileUnificationTests(unittest.TestCase):
    def _run(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "rtl_obfuscator.rewrite", *arguments],
            cwd=REPOSITORY,
            capture_output=True,
            text=True,
            check=False,
        )

    def _encrypt(
        self,
        root: Path,
        base: Path,
        *,
        project_root: bool,
        categories: tuple[str, ...],
    ) -> tuple[subprocess.CompletedProcess[str], Path, dict]:
        output = base / ("project-gate" if project_root else "filelist-gate")
        mapping_path = base / ("project.json" if project_root else "filelist.json")
        metrics_path = base / (
            "project-metrics.json" if project_root else "filelist-metrics.json"
        )
        command = [
            "encrypt-project",
            "--top",
            "t033_top",
            "--output-dir",
            str(output),
            "--map",
            str(mapping_path),
            "--metrics",
            str(metrics_path),
            "--name-length",
            "8",
        ]
        if project_root:
            command.extend(("--project-root", str(root)))
        else:
            command.extend(
                (
                    "--filelist",
                    str(root / "design.f"),
                    "--source-root",
                    str(root),
                )
            )
        for category in categories:
            command.extend(("--category", category))
        completed = self._run(*command)
        mapping = (
            json.loads(mapping_path.read_text(encoding="utf-8"))
            if mapping_path.is_file()
            else {}
        )
        return completed, output, mapping

    @staticmethod
    def _normalized_entries(mapping: dict) -> list[dict]:
        entries = []
        for item in mapping["entries"]:
            entries.append(
                {
                    "category": item["category"],
                    "scope": item["scope"],
                    "original_name": item["original_name"],
                    "declaration": item["declaration"],
                    "references": item["references"],
                    "occurrences": item["occurrences"],
                }
            )
        return sorted(
            entries,
            key=lambda item: (
                item["declaration"]["file"],
                item["declaration"]["start"],
                item["category"],
                item["scope"],
                item["original_name"],
            ),
        )

    def test_registry_profile_matrix_and_aliases(self) -> None:
        default_filelist = category_profile.resolve(
            (), mode=category_profile.MODE_FILELIST
        )
        default_project = category_profile.resolve(
            ("all",), mode=category_profile.MODE_PROJECT_ROOT
        )
        self.assertEqual(default_filelist.profile, category_profile.PROFILE_SINGLE_MODULE)
        self.assertEqual(default_filelist.selected_categories, DEFAULT)
        self.assertEqual(default_project.selected_categories, DEFAULT)
        self.assertEqual(
            category_profile.resolve(
                ("struct",), mode=category_profile.MODE_FILELIST
            ).profile,
            category_profile.PROFILE_MANUAL,
        )
        self.assertEqual(
            category_profile.resolve(
                ("struct",), mode=category_profile.MODE_FILELIST
            ).selected_categories,
            ("struct_types", "struct_fields"),
        )
        mixed = category_profile.resolve(
            ("all", "interface", "ports", "ports"),
            mode=category_profile.MODE_PROJECT_ROOT,
        )
        self.assertEqual(mixed.profile, category_profile.PROFILE_MANUAL)
        self.assertEqual(
            mixed.selected_categories,
            tuple(category for category in category_profile.CANONICAL_CATEGORIES
                  if category != "modules"),
        )
        with self.assertRaises(category_profile.ProfileResolutionError) as context:
            category_profile.resolve(("ports",), mode=category_profile.MODE_SINGLE_FILE)
        self.assertEqual(context.exception.code, category_profile.CATEGORY_REQUIRES_PROJECT_ROOT)

    def test_default_scope_and_decoy_behavior(self) -> None:
        with TemporaryDirectory(prefix="rtl-obfuscation-t035-default-") as temporary:
            base = Path(temporary)
            filelist_result, filelist_gate, filelist_mapping = self._encrypt(
                FIXTURE, base, project_root=False, categories=("all",)
            )
            self.assertEqual(filelist_result.returncode, 0, filelist_result.stderr)
            self.assertEqual(filelist_mapping["version"], 2)
            self.assertEqual(filelist_mapping["files"], [
                "bus_if.sv", "shared.sv", "child.sv", "top.sv", "decoy.sv"
            ])
            self.assertEqual(len(filelist_mapping["entries"]), 30)
            self.assertTrue(
                any(item["declaration"]["file"] == "decoy.sv"
                    for item in filelist_mapping["entries"])
            )
            self.assertNotEqual(
                (FIXTURE / "decoy.sv").read_bytes(),
                (filelist_gate / "decoy.sv").read_bytes(),
            )

            project_result, project_gate, project_mapping = self._encrypt(
                FIXTURE, base, project_root=True, categories=("all",)
            )
            self.assertEqual(project_result.returncode, 0, project_result.stderr)
            self.assertEqual(project_mapping["version"], 3)
            self.assertEqual(project_mapping["files"], [
                "bus_if.sv", "child.sv", "shared.sv", "top.sv"
            ])
            self.assertEqual(len(project_mapping["entries"]), 25)
            self.assertFalse((project_gate / "decoy.sv").exists())
            self.assertEqual(
                {item["reason"] for item in project_mapping["preserved"]},
                {"top_abi", "top_parameter", "top_port"},
            )

    def test_manual_v4_is_normalized_across_entry_points_and_decrypts(self) -> None:
        with TemporaryDirectory(prefix="rtl-obfuscation-t035-manual-") as temporary:
            base = Path(temporary)
            filelist_result, filelist_gate, filelist_mapping = self._encrypt(
                FIXTURE, base, project_root=False, categories=FULL_REQUEST
            )
            project_result, project_gate, project_mapping = self._encrypt(
                FIXTURE, base, project_root=True, categories=FULL_REQUEST
            )
            self.assertEqual(filelist_result.returncode, 0, filelist_result.stderr)
            self.assertEqual(project_result.returncode, 0, project_result.stderr)
            for mapping in (filelist_mapping, project_mapping):
                self.assertEqual(mapping["version"], 4)
                self.assertEqual(mapping["profile"], category_profile.PROFILE_MANUAL)
                self.assertEqual(
                    mapping["selected_categories"], list(category_profile.CANONICAL_CATEGORIES)
                )
                self.assertEqual(len(mapping["entries"]), 37)
                self.assertEqual(sum(item["occurrences"] for item in mapping["entries"]), 84)
                self.assertEqual(len(mapping["preserved"]), 4)
                self.assertEqual(sum(item["occurrences"] for item in mapping["preserved"]), 12)
                self.assertEqual(
                    len({
                        (record["file"], record["start"], record["end"])
                        for item in mapping["entries"] + mapping["preserved"]
                        for record in ([item["declaration"]] if item["declaration"] else []) + item["references"]
                    }),
                    96,
                )
            self.assertEqual(
                self._normalized_entries(filelist_mapping),
                self._normalized_entries(project_mapping),
            )
            self.assertEqual(filelist_mapping["closure"]["policy"], "filelist_bounded")
            self.assertEqual(project_mapping["closure"]["policy"], "project_discovered")
            self.assertEqual(filelist_mapping["skipped"][0]["file"], "decoy.sv")
            self.assertEqual(filelist_mapping["skipped"][0]["reason"], "out_of_top_closure")
            self.assertEqual(project_mapping["skipped"], [])

            alias_result, _, alias_mapping = self._encrypt(
                FIXTURE,
                base / "alias",
                project_root=False,
                categories=("all", "struct", "interface", "modules", "ports"),
            )
            self.assertEqual(alias_result.returncode, 0, alias_result.stderr)
            self.assertEqual(
                self._normalized_entries(alias_mapping),
                self._normalized_entries(filelist_mapping),
            )
            self.assertEqual(
                alias_mapping["selected_categories"],
                list(category_profile.CANONICAL_CATEGORIES),
            )

            for project_root, mapping, source_root in (
                (filelist_gate, filelist_mapping, FIXTURE),
                (project_gate, project_mapping, FIXTURE),
            ):
                restored = base / ("filelist-restored" if mapping["mode"] == "filelist" else "project-restored")
                completed = self._run(
                    "decrypt-project",
                    "--gate-dir",
                    str(project_root),
                    "--map",
                    str(base / ("filelist.json" if mapping["mode"] == "filelist" else "project.json")),
                    "--source-root",
                    str(source_root),
                    "--output-dir",
                    str(restored),
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                for relative_file in mapping["files"]:
                    self.assertEqual(
                        (restored / relative_file).read_bytes(),
                        (source_root / relative_file).read_bytes(),
                    )

    def test_filelist_manual_fail_closed_before_publish(self) -> None:
        with TemporaryDirectory(prefix="rtl-obfuscation-t035-fail-") as temporary:
            base = Path(temporary)
            missing_filelist = base / "missing.f"
            missing_filelist.write_text("top.sv\nchild.sv\nmissing.sv\n", encoding="utf-8")
            missing_out = base / "missing-gate"
            missing_map = base / "missing.json"
            missing_metrics = base / "missing-metrics.json"
            missing = self._run(
                "encrypt-project",
                "--filelist", str(missing_filelist),
                "--source-root", str(FIXTURE),
                "--output-dir", str(missing_out),
                "--map", str(missing_map),
                "--metrics", str(missing_metrics),
                "--top", "t033_top",
                "--category", "modules",
                "--name-length", "8",
            )
            self.assertNotEqual(missing.returncode, 0)
            self.assertIn("MISSING_FILELIST_ENTRY", missing.stderr)
            self.assertFalse(missing_out.exists())
            self.assertFalse(missing_map.exists())
            self.assertFalse(missing_metrics.exists())

            ambiguous_root = base / "ambiguous"
            shutil.copytree(FIXTURE, ambiguous_root)
            shutil.copy2(ambiguous_root / "top.sv", ambiguous_root / "duplicate_top.sv")
            (ambiguous_root / "design.f").write_text(
                (ambiguous_root / "design.f").read_text(encoding="utf-8")
                + "duplicate_top.sv\n",
                encoding="utf-8",
            )
            ambiguous_out = base / "ambiguous-gate"
            ambiguous_map = base / "ambiguous.json"
            ambiguous_metrics = base / "ambiguous-metrics.json"
            ambiguous = self._run(
                "encrypt-project",
                "--filelist", str(ambiguous_root / "design.f"),
                "--source-root", str(ambiguous_root),
                "--output-dir", str(ambiguous_out),
                "--map", str(ambiguous_map),
                "--metrics", str(ambiguous_metrics),
                "--top", "t033_top",
                "--category", "modules",
                "--name-length", "8",
            )
            self.assertNotEqual(ambiguous.returncode, 0)
            self.assertIn("AMBIGUOUS_TOP", ambiguous.stderr)
            self.assertFalse(ambiguous_out.exists())
            self.assertFalse(ambiguous_map.exists())
            self.assertFalse(ambiguous_metrics.exists())

            external_root = base / "external"
            external_root.mkdir()
            (external_root / "top.sv").write_text(
                "module external_top; external_ip u_ip(); endmodule\n",
                encoding="utf-8",
            )
            (external_root / "design.f").write_text("top.sv\n", encoding="utf-8")
            external_out = base / "external-gate"
            external_map = base / "external.json"
            external_metrics = base / "external-metrics.json"
            external = self._run(
                "encrypt-project",
                "--filelist", str(external_root / "design.f"),
                "--source-root", str(external_root),
                "--output-dir", str(external_out),
                "--map", str(external_map),
                "--metrics", str(external_metrics),
                "--top", "external_top",
                "--category", "modules",
                "--name-length", "8",
            )
            self.assertNotEqual(external.returncode, 0)
            self.assertFalse(external_out.exists())
            self.assertFalse(external_map.exists())
            self.assertFalse(external_metrics.exists())


if __name__ == "__main__":
    unittest.main()
