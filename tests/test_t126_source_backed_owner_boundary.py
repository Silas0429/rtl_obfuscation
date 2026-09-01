from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

import pyslang

import rtl_obfuscator.source_catalog as source_catalog_module
from rtl_obfuscator.mapping_vnext import build_mapping_vnext
from rtl_obfuscator.rename_index import build_rename_index
from rtl_obfuscator.source_catalog import SourceCatalogError, build_source_catalog
from rtl_obfuscator.source_set import from_filelist
from rtl_obfuscator.systemverilog_names import secure_name_factory


class T126SourceBackedOwnerBoundaryTests(unittest.TestCase):
    @staticmethod
    def _write_case(root: Path) -> object:
        (root / "external").mkdir()
        (root / "owned").mkdir()
        (root / "external" / "context.sv").write_text(
            """class rand_class;
    rand int value;
endclass

covergroup cg (int sample_value);
coverpoint sample_value;
endgroup

package t126_pkg;
    function automatic int shared_name(input int x);
        return x;
    endfunction
endpackage

interface t126_if(input logic clk);
    logic member;
    modport mp(input clk, output member);
endinterface
""",
            encoding="utf-8",
        )
        (root / "owned" / "top.sv").write_text(
            """typedef struct packed { logic field; } t126_t;
module t126_top(input logic in_i, output logic out_o);
    logic shared_name;
    t126_t obj;
    function automatic int user_function(input int x);
        return x;
    endfunction
    task user_task;
    endtask
    assign out_o = in_i;
endmodule
""",
            encoding="utf-8",
        )
        filelist = root / "design.f"
        filelist.write_text(
            "external/context.sv\nowned/top.sv\n", encoding="utf-8"
        )
        return from_filelist(
            filelist=filelist,
            source_root=root,
            top="t126_top",
            rewrite_roots=(root / "owned",),
        )

    @staticmethod
    def _owner_id(root: Path, relative: str, name: str, prefix: str) -> str:
        data = (root / relative).read_bytes()
        start = data.index(name.encode("utf-8"))
        return f"{prefix}:{relative}:{start}:{start + len(name)}"

    def test_source_backed_registry_skips_synthetic_nodes_and_validates_mapping(self):
        with tempfile.TemporaryDirectory(prefix="t126-owner-boundary-") as temporary:
            root = Path(temporary)
            source_set = self._write_case(root)
            catalog = build_source_catalog(source_set)
            owners = set(catalog.semantic_owner_ids)

            self.assertIn("$unit", owners)
            self.assertIn(
                self._owner_id(root, "owned/top.sv", "t126_top", "module"),
                owners,
            )
            self.assertIn(
                self._owner_id(root, "external/context.sv", "t126_if", "interface"),
                owners,
            )
            self.assertIn(
                self._owner_id(root, "owned/top.sv", "t126_t", "type"),
                owners,
            )
            self.assertFalse(any(item.startswith("subroutine:") for item in owners))
            self.assertFalse(any(item.startswith("generate:") for item in owners))

            nodes = []
            catalog.catalog_root.visit(nodes.append)
            package_function = next(
                node
                for node in nodes
                if type(node).__name__ == "SubroutineSymbol"
                and str(getattr(node, "name", "")) == "shared_name"
            )
            function_range = source_catalog_module._semantic_name_range(
                source_set,
                catalog.catalog_source_manager,
                package_function,
            )
            self.assertEqual(function_range.file, "external/context.sv")

            rename_index = build_rename_index(catalog, categories=("all",))
            mapping = build_mapping_vnext(
                rename_index,
                name_length=8,
                name_factory=secure_name_factory,
            )
            self.assertTrue(mapping.records)
            self.assertTrue(
                all(record.semantic_owner in owners for record in mapping.records)
            )
            shared_signal = next(
                symbol
                for symbol in rename_index.symbols
                if symbol.category == "signals"
                and symbol.name == "shared_name"
                and symbol.declaration.file == "owned/top.sv"
            )
            self.assertEqual(shared_signal.support, "eligible")
            self.assertNotEqual(shared_signal.reason, "incomplete_name_coverage")

    def test_physical_kinds_are_allowed_but_nonphysical_kinds_never_resolve_path(self):
        with tempfile.TemporaryDirectory(prefix="t126-buffer-boundary-") as temporary:
            root = Path(temporary)
            source_set = self._write_case(root)
            physical_path = root / "owned" / "top.sv"

            class Manager:
                def __init__(self, kind, path):
                    self.kind = kind
                    self.path = path
                    self.full_path_calls = 0

                def getBufferKind(self, _buffer):
                    return self.kind

                def getFullPath(self, _buffer):
                    self.full_path_calls += 1
                    return self.path

            for kind in (
                pyslang.BufferKind.DesignFile,
                pyslang.BufferKind.LibraryFile,
                pyslang.BufferKind.IncludeFile,
            ):
                manager = Manager(kind, physical_path)
                self.assertEqual(
                    source_catalog_module._relative_file(
                        source_set, manager, object()
                    ),
                    "owned/top.sv",
                )
                self.assertEqual(manager.full_path_calls, 1)

            # Use root '/' and a full path of '.' to lock out the historical
            # Unknown-buffer-to-cwd fallback before getFullPath is consulted.
            root_source_set = replace(source_set, source_root=Path("/"))
            for kind in (
                pyslang.BufferKind.Unknown,
                pyslang.BufferKind.LibraryMap,
                pyslang.BufferKind.Macro,
                pyslang.BufferKind.MacroArg,
            ):
                manager = Manager(kind, Path("."))
                with self.assertRaises(SourceCatalogError) as raised:
                    source_catalog_module._relative_file(
                        root_source_set, manager, object()
                    )
                self.assertEqual(raised.exception.code, "CATALOG_RANGE_INVALID")
                self.assertNotIn(str(Path.cwd()), str(raised.exception))
                self.assertEqual(manager.full_path_calls, 0)

            known_non_regular = replace(
                source_set,
                compile_order=(*source_set.compile_order, "owned/known_directory"),
            )
            (root / "owned" / "known_directory").mkdir()
            manager = Manager(
                pyslang.BufferKind.DesignFile, root / "owned" / "known_directory"
            )
            with self.assertRaises(SourceCatalogError) as raised:
                source_catalog_module._relative_file(known_non_regular, manager, object())
            self.assertEqual(raised.exception.code, "CATALOG_RANGE_INVALID")
            self.assertEqual(raised.exception.file, "owned/known_directory")
            self.assertEqual(manager.full_path_calls, 1)

            fifo = root / "owned" / "known_fifo"
            os.mkfifo(fifo)
            fifo_source_set = replace(
                source_set,
                compile_order=(*source_set.compile_order, "owned/known_fifo"),
            )
            manager = Manager(pyslang.BufferKind.IncludeFile, fifo)
            with self.assertRaises(SourceCatalogError) as raised:
                source_catalog_module._relative_file(fifo_source_set, manager, object())
            self.assertEqual(raised.exception.code, "CATALOG_RANGE_INVALID")
            self.assertEqual(raised.exception.file, "owned/known_fifo")
            self.assertEqual(manager.full_path_calls, 1)

    def test_source_less_type_alias_wrapper_does_not_create_physical_owner(self):
        with tempfile.TemporaryDirectory(prefix="t126-source-less-") as temporary:
            root = Path(temporary)
            source_set = self._write_case(root)
            source_less_type = type("TypeAliasType", (), {})()
            source_less_type.syntax = None
            source_less_type.location = SimpleNamespace(
                buffer=object(), offset=68719476735
            )

            class Root:
                def visit(self, callback):
                    callback(source_less_type)

            class Manager:
                def getBufferKind(self, _buffer):
                    return pyslang.BufferKind.Unknown

            view = source_catalog_module._CompiledView(
                compilation=None,
                root=Root(),
                source_manager=Manager(),
                syntax_tree=None,
                parse_errors=(),
                semantic_errors=(),
                nonblocking_errors=(),
                vendor_compatibility_errors=(),
                vendor_compatibility_files=(),
            )
            self.assertEqual(
                source_catalog_module._semantic_owner_ids(source_set, view, ()),
                ("$unit",),
            )


if __name__ == "__main__":
    unittest.main()
