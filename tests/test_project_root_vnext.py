from pathlib import Path
import tempfile
import unittest

from rtl_obfuscator.orchestration_vnext import run_vnext
from rtl_obfuscator.source_set import from_project_root


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "t108_pyslang_rename_index"


class ProjectRootVNextTests(unittest.TestCase):
    def test_project_root_uses_the_same_schema_two_pipeline(self):
        source_set = from_project_root(project_root=FIXTURE, top="top")
        self.assertEqual(source_set.origin, "project-root")
        with tempfile.TemporaryDirectory(prefix="t108-project-root-") as temp:
            root = Path(temp)
            result = run_vnext(
                source_set,
                categories=("all",),
                gate_dir=root / "gate",
                restore_dir=root / "restore",
            )
            report = result.to_report()
            self.assertEqual(report["schema_version"], 2)
            self.assertTrue(report["summary"]["strict_compile_passed"])
            self.assertTrue(report["summary"]["restored_byte_identical"])


if __name__ == "__main__":
    unittest.main()
