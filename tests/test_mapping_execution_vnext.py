from pathlib import Path
import hashlib
import tempfile
import unittest

from rtl_obfuscator.mapping_vnext import build_mapping_vnext
from rtl_obfuscator.rename_index import build_rename_index
from rtl_obfuscator.rewrite_vnext import (
    build_mapping_execution_vnext,
    restore_gate_vnext,
    write_gate_vnext,
)
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


class MappingExecutionVNextTests(unittest.TestCase):
    def test_mapping_execution_schema_two_has_restored_manifest(self):
        mapping = _mapping()
        with tempfile.TemporaryDirectory(prefix="t108-mapping-execution-") as temp:
            root = Path(temp)
            gate = root / "gate"
            restore = root / "restore"
            execution = write_gate_vnext(mapping, output_dir=gate)
            restored = restore_gate_vnext(execution, gate_dir=gate, output_dir=restore)
            envelope = build_mapping_execution_vnext(execution, restored)
            report = envelope.to_report()
            self.assertEqual(envelope.schema_version, 2)
            self.assertEqual(report["schema_version"], 2)
            self.assertTrue(report["summary"]["restored_byte_identical"])
            self.assertEqual(report["input_manifest"], report["restored_manifest"])


if __name__ == "__main__":
    unittest.main()
