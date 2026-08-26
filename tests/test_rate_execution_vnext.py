from pathlib import Path
import hashlib
import tempfile
import unittest

from rtl_obfuscator.mapping_vnext import build_mapping_vnext
from rtl_obfuscator.rename_index import build_rename_index
from rtl_obfuscator.rate_execution_vnext import (
    restore_rate_selected_gate_vnext,
    write_rate_selected_gate_vnext,
)
from rtl_obfuscator.rate_vnext import build_rate_selection_vnext
from rtl_obfuscator.source_catalog import build_source_catalog
from rtl_obfuscator.source_set import from_filelist


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "t108_pyslang_rename_index"


def _factory(symbol_id: str, name_length: int, unavailable: frozenset[str]) -> str:
    del unavailable
    return "n" + hashlib.sha256(symbol_id.encode()).hexdigest()[: name_length - 1]


def _mapping():
    source_set = from_filelist(filelist=FIXTURE / "design.f", top="top")
    index = build_rename_index(build_source_catalog(source_set), categories=("all",))
    return build_mapping_vnext(index, name_length=16, name_factory=_factory)


class RateExecutionVNextTests(unittest.TestCase):
    def test_selected_gate_is_schema_two_and_restorable(self):
        mapping = _mapping()
        selection = build_rate_selection_vnext(mapping, "0.5")
        with tempfile.TemporaryDirectory(prefix="t108-rate-execution-") as temp:
            root = Path(temp)
            gate = root / "gate"
            restore = root / "restore"
            execution = write_rate_selected_gate_vnext(mapping, selection, gate)
            self.assertEqual(execution.schema_version, 2)
            self.assertEqual(execution.to_report()["schema_version"], 2)
            restored = restore_rate_selected_gate_vnext(execution, gate, restore)
            self.assertEqual(restored.schema_version, 2)
            self.assertTrue(restored.to_report()["summary"]["byte_identical"])


if __name__ == "__main__":
    unittest.main()
