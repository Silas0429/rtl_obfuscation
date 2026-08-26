from pathlib import Path
import hashlib
import unittest

from rtl_obfuscator.mapping_vnext import build_mapping_vnext
from rtl_obfuscator.rename_index import build_rename_index
from rtl_obfuscator.rate_vnext import RateVNextError, build_rate_selection_vnext
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


class RateSelectionVNextTests(unittest.TestCase):
    def test_rate_selection_consumes_schema_two_mapping(self):
        selection = build_rate_selection_vnext(_mapping(), "0.5")
        self.assertEqual(selection.schema_version, 2)
        self.assertEqual(selection.to_report()["schema_version"], 2)
        self.assertTrue(selection.candidates)

    def test_invalid_rate_is_fail_closed(self):
        with self.assertRaises(RateVNextError) as raised:
            build_rate_selection_vnext(_mapping(), "0")
        self.assertEqual(raised.exception.code, "RATE_SELECTION_INVALID")


if __name__ == "__main__":
    unittest.main()
