from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import tempfile
import tracemalloc
import unittest
from unittest import mock

from rtl_obfuscator.project_discovery import (
    _DIAGNOSTIC_READ_CHUNK_SIZE,
    _PhysicalDiagnosticSource,
    _classify_vendor_compatibility_errors,
    _vendor_directive_file_at,
    compile_pyslang_source_set,
)
from rtl_obfuscator.source_set import from_filelist


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "t121_vendor_model_readonly"
TOP = "t121_top"


class _Diagnostic:
    def __init__(self, code: str, buffer: object, offset: int, *, macro: bool = False):
        self.code = f"DiagCode({code})"
        self.location = SimpleNamespace(buffer=buffer, offset=offset, macro=macro)


class _Manager:
    def __init__(self, paths: dict[object, Path]):
        self.paths = paths

    @staticmethod
    def isFileLoc(location):
        return not location.macro

    @staticmethod
    def isMacroLoc(location):
        return location.macro

    def getFullPath(self, buffer):
        return self.paths[buffer]


class _TrackedStream:
    def __init__(self, stream, sizes: list[int]):
        self._stream = stream
        self._sizes = sizes

    def read(self, size=-1):
        if type(size) is not int or size < 0:
            raise AssertionError("diagnostic classifier attempted an unbounded read")
        self._sizes.append(size)
        return self._stream.read(size)

    def __getattr__(self, name):
        return getattr(self._stream, name)


@contextmanager
def _bounded_read_guard():
    original_open = Path.open
    sizes: list[int] = []

    def tracked_open(path, *arguments, **keywords):
        return _TrackedStream(original_open(path, *arguments, **keywords), sizes)

    with mock.patch.object(
        Path,
        "read_bytes",
        side_effect=AssertionError("diagnostic classifier attempted Path.read_bytes"),
    ), mock.patch.object(Path, "open", tracked_open):
        yield sizes


def _classify_file(
    path: Path,
    diagnostics: tuple[_Diagnostic, ...],
    *,
    root: Path | None = None,
    relative: str | None = None,
):
    root = path.parent if root is None else root
    relative = path.resolve().relative_to(root.resolve()).as_posix() if relative is None else relative
    buffer = diagnostics[0].location.buffer if diagnostics else "buffer"
    return _classify_vendor_compatibility_errors(
        root=root,
        manager=_Manager({buffer: path}),
        diagnostics=diagnostics,
        physical_files=frozenset({relative}),
    )


class T122VendorDiagnosticMemoryTests(unittest.TestCase):
    def test_t121_fixture_classification_uses_only_bounded_reads(self):
        source_set = from_filelist(
            filelist=FIXTURE / "design.f",
            source_root=FIXTURE,
            top=TOP,
            rewrite_roots=(FIXTURE / "project",),
        )
        with _bounded_read_guard() as sizes:
            view = compile_pyslang_source_set(
                root=FIXTURE,
                compilation_files=source_set.compile_order,
                include_files=source_set.included_files,
                include_dirs=source_set.include_dirs,
                defines=dict(source_set.defines),
                top=source_set.top,
            )

        vendor_codes = [str(item.code) for item in view.vendor_compatibility_errors]
        self.assertEqual(vendor_codes.count("DiagCode(UnknownDirective)"), 8)
        self.assertEqual(vendor_codes.count("DiagCode(IfNoneEdgeSensitive)"), 1)
        self.assertEqual(view.vendor_compatibility_files, ("project/diagnostic_inside.v",))
        self.assertEqual(view.parse_errors, ())
        self.assertEqual(view.semantic_errors, ())
        self.assertEqual(
            [str(item.code) for item in view.nonblocking_errors],
            [
                *vendor_codes,
                *["DiagCode(MissingTimeScale)"] * 4,
            ],
        )
        self.assertTrue(sizes)
        self.assertLessEqual(max(sizes), _DIAGNOSTIC_READ_CHUNK_SIZE)

    def test_sparse_high_offsets_and_repeated_ifnone_are_size_independent(self):
        with tempfile.TemporaryDirectory(prefix="t122-sparse-") as temporary:
            root = Path(temporary)
            path = root / "sparse.v"
            offsets = (64 * 1024 * 1024, 96 * 1024 * 1024)
            with path.open("wb") as stream:
                for offset in offsets:
                    stream.seek(offset)
                    stream.write(b"ifnone ")
            diagnostics = tuple(
                _Diagnostic("IfNoneEdgeSensitive", "sparse", offset)
                for offset in offsets
            )

            tracemalloc.start()
            try:
                with _bounded_read_guard() as sizes:
                    accepted, files = _classify_file(path, diagnostics)
                _current, peak = tracemalloc.get_traced_memory()
            finally:
                tracemalloc.stop()

            self.assertEqual(accepted, diagnostics)
            self.assertEqual(files, ("sparse.v",))
            self.assertGreater(path.stat().st_size, 96 * 1024 * 1024)
            self.assertTrue(sizes)
            self.assertLessEqual(max(sizes), _DIAGNOSTIC_READ_CHUNK_SIZE)
            self.assertLess(peak, 2 * 1024 * 1024)

    def test_streamed_directives_cover_long_lines_crlf_and_eof(self):
        names = (
            b"protect",
            b"endprotect",
            b"protect",
            b"endprotect",
            b"suppress_faults",
            b"enable_portfaults",
            b"disable_portfaults",
            b"nosuppress_faults",
        )
        with tempfile.TemporaryDirectory(prefix="t122-lines-") as temporary:
            root = Path(temporary)
            path = root / "directives.v"
            payload = bytearray()
            offsets: list[int] = []
            for index, name in enumerate(names):
                leading = b" " * (70_000 if index == 0 else index + 1)
                payload.extend(leading)
                offsets.append(len(payload))
                payload.extend(b"`" + name)
                if index in {0, 4}:
                    payload.extend(b" \t//" + b"c" * 90_000)
                if index != len(names) - 1:
                    payload.extend(b"\r\n")
            path.write_bytes(payload)
            diagnostics = tuple(
                _Diagnostic("UnknownDirective", "directives", offset)
                for offset in offsets
            )

            with _bounded_read_guard() as sizes:
                accepted, files = _classify_file(path, diagnostics)
            self.assertEqual(accepted, diagnostics)
            self.assertEqual(files, ("directives.v",))
            self.assertTrue(sizes)
            self.assertLessEqual(max(sizes), _DIAGNOSTIC_READ_CHUNK_SIZE)

            invalid = {
                "extra": b"`protect extra\n",
                "argument": b"`protect(1)\n",
                "comment": b"`protect / not-a-comment\n",
            }
            for name, data in invalid.items():
                candidate = root / f"{name}.v"
                candidate.write_bytes(data)
                diagnostic = _Diagnostic("UnknownDirective", name, 0)
                with self.subTest(name=name), _bounded_read_guard():
                    accepted, _files = _classify_file(candidate, (diagnostic,))
                    self.assertEqual(accepted, ())

            truncated = root / "truncated.v"
            truncated.write_bytes(b"`protect\n")
            physical = _PhysicalDiagnosticSource(
                relative="truncated.v",
                path=truncated,
                offset=0,
                size=truncated.stat().st_size,
            )
            truncated.write_bytes(b"`pro")
            with _bounded_read_guard():
                self.assertIsNone(_vendor_directive_file_at(physical))
            with mock.patch.object(Path, "open", side_effect=OSError("denied")):
                self.assertIsNone(_vendor_directive_file_at(physical))

    def test_existing_fail_closed_shapes_remain_blocking(self):
        cases = {
            "ordinary": (b"`SOME_UNKNOWN_MACRO\n", "UnknownDirective", 0),
            "argument": (b"`protect(1)\n", "UnknownDirective", 0),
            "unpaired": (b"`protect\n", "UnknownDirective", 0),
            "reverse": (b"`endprotect\n", "UnknownDirective", 0),
            "nested": (
                b"`protect\n`protect\n`endprotect\n`endprotect\n",
                "UnknownDirective",
                0,
            ),
            "pseudo_ifnone": (b"xifnone ", "IfNoneEdgeSensitive", 1),
        }
        with tempfile.TemporaryDirectory(prefix="t122-negative-") as temporary:
            root = Path(temporary)
            for name, (data, code, offset) in cases.items():
                path = root / f"{name}.v"
                path.write_bytes(data)
                if name == "nested":
                    offsets = (0, 9, 18, 30)
                    diagnostics = tuple(
                        _Diagnostic(code, name, item) for item in offsets
                    )
                else:
                    diagnostics = (_Diagnostic(code, name, offset),)
                with self.subTest(name=name), _bounded_read_guard():
                    accepted, files = _classify_file(path, diagnostics)
                    self.assertEqual(accepted, ())
                    self.assertEqual(files, ())

            macro = root / "macro.v"
            macro.write_bytes(b"`protect\n`endprotect\n")
            diagnostics = (
                _Diagnostic("UnknownDirective", "macro", 0, macro=True),
                _Diagnostic("UnknownDirective", "macro", 9, macro=True),
            )
            with _bounded_read_guard():
                accepted, files = _classify_file(macro, diagnostics)
            self.assertEqual(accepted, ())
            self.assertEqual(files, ())

            outside = root / "outside.v"
            outside.write_bytes(b"`protect\n`endprotect\n")
            diagnostics = (
                _Diagnostic("UnknownDirective", "outside", 0),
                _Diagnostic("UnknownDirective", "outside", 9),
            )
            with _bounded_read_guard():
                accepted, files = _classify_vendor_compatibility_errors(
                    root=root,
                    manager=_Manager({"outside": outside}),
                    diagnostics=diagnostics,
                    physical_files=frozenset(),
                )
            self.assertEqual(accepted, ())
            self.assertEqual(files, ())


if __name__ == "__main__":
    unittest.main()
