"""Build a deterministic, Yosys-compatible view of a selected RTL project."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Iterable

import pyslang

from . import inventory, project


@dataclass(frozen=True)
class _Edit:
    record: dict[str, Any]
    replacement: bytes


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _manifest(root: Path, files: Iterable[str]) -> str:
    payload = b"".join(
        hashlib.sha256((root / relative).read_bytes()).hexdigest().encode("ascii")
        + b"  "
        + relative.encode("utf-8")
        + b"\n"
        for relative in sorted(files)
    )
    return hashlib.sha256(payload).hexdigest()


def _relative_range(
    context: project.ProjectSemanticContext, source_range: Any
) -> tuple[str, int, int]:
    start = source_range.start
    end = source_range.end
    manager = context.source_manager
    if manager.isMacroLoc(start) or manager.isMacroLoc(end):
        raise ValueError("formal-view does not support macro-expanded ranges")
    start_path = Path(manager.getFullPath(start.buffer)).resolve()
    end_path = Path(manager.getFullPath(end.buffer)).resolve()
    if start_path != end_path:
        raise ValueError("formal-view range crosses source files")
    try:
        relative = start_path.relative_to(context.project_root).as_posix()
    except ValueError as error:
        raise ValueError("formal-view range is outside project root") from error
    if relative not in context.closure:
        raise ValueError("formal-view range is outside the selected closure")
    return relative, start.offset, end.offset


def _packed_struct_aliases(
    context: project.ProjectSemanticContext,
) -> list[Any]:
    root_nodes: list[Any] = []
    context.compilation.getRoot().visit(root_nodes.append)
    candidates = [
        node
        for node in root_nodes
        if getattr(node, "kind", None) == pyslang.ast.SymbolKind.TypeAlias
        and getattr(node, "declaringDefinition", None) is None
        and getattr(node, "isStruct", False)
        and not getattr(node, "isUnpackedStruct", False)
    ]
    selected = inventory._selected_nodes(context.top_instance)
    used: set[Any] = set()
    candidate_set = set(candidates)
    for node in selected:
        declared_type = getattr(node, "declaredType", None)
        resolved = getattr(declared_type, "type", None)
        if resolved in candidate_set:
            used.add(resolved)
            continue
        if type(resolved).__name__ == "PackedArrayType":
            element = getattr(resolved, "elementType", None)
            if element in candidate_set:
                used.add(element)
                continue
            if type(element).__name__ == "PackedArrayType" and getattr(
                element, "elementType", None
            ) in candidate_set:
                raise ValueError("formal-view does not support nested packed arrays")
        elif getattr(resolved, "elementType", None) in candidate_set:
            raise ValueError("formal-view does not support unpacked aggregate arrays")
    return sorted(
        used,
        key=lambda alias: (
            str(context.source_manager.getFullPath(alias.location.buffer)),
            alias.location.offset,
            alias.name,
        ),
    )


def _alias_for_declared_type(resolved: Any, aliases: set[Any]) -> Any | None:
    if resolved in aliases:
        return resolved
    if type(resolved).__name__ != "PackedArrayType":
        return None
    element = getattr(resolved, "elementType", None)
    if element in aliases:
        return element
    if type(element).__name__ == "PackedArrayType" and getattr(
        element, "elementType", None
    ) in aliases:
        raise ValueError("formal-view does not support nested packed arrays")
    return None


def _record(
    *,
    kind: str,
    file: str,
    start: int,
    end: int,
    syntax_kind: str,
    source: bytes,
    replacement: bytes,
    **variant: Any,
) -> dict[str, Any]:
    if start < 0 or end <= start or end > len(source):
        raise ValueError("formal-view transformation range is invalid")
    result = {
        "kind": kind,
        "file": file,
        "start": start,
        "end": end,
        "syntax_kind": syntax_kind,
        "structural_ordinal": -1,
        "source_sha256": _sha256(source[start:end]),
        "replacement_sha256": _sha256(replacement),
    }
    result.update(variant)
    return result


def _collect_type_edits(
    context: project.ProjectSemanticContext,
    sources: dict[str, bytes],
    aliases: list[Any],
) -> dict[tuple[str, int, int], _Edit]:
    alias_set = set(aliases)
    edits: dict[tuple[str, int, int], _Edit] = {}
    for node in inventory._selected_nodes(context.top_instance):
        declared_type = getattr(node, "declaredType", None)
        resolved = getattr(declared_type, "type", None)
        alias = _alias_for_declared_type(resolved, alias_set)
        if alias is None:
            continue
        type_syntax = getattr(declared_type, "typeSyntax", None)
        source_range = getattr(type_syntax, "sourceRange", None)
        if source_range is None:
            raise ValueError("formal-view aggregate type has no source syntax")
        relative, start, end = _relative_range(context, source_range)
        width = getattr(resolved, "bitWidth", None)
        if not isinstance(width, int) or width < 1:
            raise ValueError("formal-view aggregate type has invalid width")
        replacement = f"logic [{width - 1}:0]".encode("ascii")
        public = _record(
            kind="lower_packed_aggregate_type",
            file=relative,
            start=start,
            end=end,
            syntax_kind=type(type_syntax).__name__,
            source=sources[relative],
            replacement=replacement,
            bit_width=width,
        )
        key = (relative, start, end)
        edit = _Edit(public, replacement)
        previous = edits.setdefault(key, edit)
        if previous != edit:
            raise ValueError("formal-view aggregate type range is ambiguous")
    return edits


def _slice_expression(
    context: project.ProjectSemanticContext,
    sources: dict[str, bytes],
    expression: Any,
    expected_file: str,
) -> bytes:
    relative, start, end = _relative_range(context, expression.sourceRange)
    if relative != expected_file:
        raise ValueError("formal-view expression crosses source files")
    return sources[relative][start:end]


def _collect_member_edits(
    context: project.ProjectSemanticContext,
    sources: dict[str, bytes],
    aliases: list[Any],
) -> dict[tuple[str, int, int], _Edit]:
    field_owner: dict[Any, Any] = {}
    for alias in aliases:
        resolved = alias.targetType.type
        if not getattr(resolved, "isStruct", False) or getattr(
            resolved, "isUnpackedStruct", False
        ):
            raise ValueError("formal-view aggregate alias is not a packed struct")
        for field in resolved:
            field_owner[field] = alias

    edits: dict[tuple[str, int, int], _Edit] = {}
    for node in inventory._selected_nodes(context.top_instance):
        if type(node).__name__ != "MemberAccessExpression":
            continue
        field = getattr(node, "member", None)
        alias = field_owner.get(field)
        if alias is None:
            continue
        relative, start, end = _relative_range(context, node.sourceRange)
        struct_width = alias.targetType.type.bitWidth
        field_width = field.type.bitWidth
        field_offset = field.bitOffset
        if not all(
            isinstance(value, int) and value >= 0
            for value in (struct_width, field_width, field_offset)
        ) or field_width < 1:
            raise ValueError("formal-view packed member has invalid layout")

        base = node.value
        if type(base).__name__ == "NamedValueExpression":
            base_bytes = _slice_expression(context, sources, base, relative)
            replacement = (
                base_bytes
                + f"[{field_offset} +: {field_width}]".encode("ascii")
            )
            base_shape = "NamedValueExpression"
        elif type(base).__name__ == "ElementSelectExpression":
            if type(base.value).__name__ != "NamedValueExpression":
                raise ValueError(
                    "formal-view does not support nested aggregate member bases"
                )
            base_bytes = _slice_expression(context, sources, base.value, relative)
            selector_bytes = _slice_expression(
                context, sources, base.selector, relative
            )
            replacement = (
                base_bytes
                + b"[(("
                + selector_bytes
                + f")*{struct_width}+{field_offset}) +: {field_width}]".encode(
                    "ascii"
                )
            )
            base_shape = "ElementSelectExpression"
        else:
            raise ValueError(
                "formal-view does not support this packed member base shape"
            )

        public = _record(
            kind="lower_packed_struct_member",
            file=relative,
            start=start,
            end=end,
            syntax_kind=type(node).__name__,
            source=sources[relative],
            replacement=replacement,
            struct_width=struct_width,
            field_offset=field_offset,
            field_width=field_width,
            base_shape=base_shape,
        )
        key = (relative, start, end)
        edit = _Edit(public, replacement)
        previous = edits.setdefault(key, edit)
        if previous != edit:
            raise ValueError("formal-view packed member range is ambiguous")
    return edits


def _collect_assertion_edits(
    context: project.ProjectSemanticContext,
    sources: dict[str, bytes],
) -> dict[tuple[str, int, int], _Edit]:
    edits: dict[tuple[str, int, int], _Edit] = {}
    for node in inventory._selected_nodes(context.top_instance):
        if type(node).__name__ != "ConcurrentAssertionStatement":
            continue
        syntax = getattr(node, "syntax", None)
        if type(syntax).__name__ != "ConcurrentAssertionStatementSyntax":
            raise ValueError("formal-view concurrent assertion has no source syntax")
        relative, start, end = _relative_range(context, syntax.sourceRange)
        source_bytes = sources[relative][start:end]
        replacement = bytes(
            byte if byte == ord("\n") else ord(" ") for byte in source_bytes
        )
        public = _record(
            kind="remove_concurrent_assertion",
            file=relative,
            start=start,
            end=end,
            syntax_kind=type(syntax).__name__,
            source=sources[relative],
            replacement=replacement,
        )
        key = (relative, start, end)
        edit = _Edit(public, replacement)
        previous = edits.setdefault(key, edit)
        if previous != edit:
            raise ValueError("formal-view assertion range is ambiguous")
    return edits


def _ordered_edits(
    collections: Iterable[dict[tuple[str, int, int], _Edit]],
) -> list[_Edit]:
    by_range: dict[tuple[str, int, int], _Edit] = {}
    for collection in collections:
        for key, edit in collection.items():
            if key in by_range:
                raise ValueError("formal-view transformations overlap")
            by_range[key] = edit
    ordered = sorted(
        by_range.values(),
        key=lambda edit: (
            edit.record["file"],
            edit.record["start"],
            edit.record["end"],
            edit.record["kind"],
        ),
    )
    previous_by_file: dict[str, tuple[int, int]] = {}
    ordinals: dict[tuple[str, str], int] = {}
    result: list[_Edit] = []
    for edit in ordered:
        record = edit.record
        previous = previous_by_file.get(record["file"])
        if previous is not None and record["start"] < previous[1]:
            raise ValueError("formal-view transformations overlap")
        previous_by_file[record["file"]] = (record["start"], record["end"])
        ordinal_key = (record["file"], record["kind"])
        public = dict(record)
        public["structural_ordinal"] = ordinals.get(ordinal_key, 0)
        ordinals[ordinal_key] = public["structural_ordinal"] + 1
        result.append(_Edit(public, edit.replacement))
    return result


def _apply_file_edits(source: bytes, edits: list[_Edit]) -> bytes:
    result = source
    for edit in reversed(edits):
        start = edit.record["start"]
        end = edit.record["end"]
        if _sha256(source[start:end]) != edit.record["source_sha256"]:
            raise ValueError("formal-view source hash changed before rewrite")
        result = result[:start] + edit.replacement + result[end:]
    return result


def _yosys_atom(value: str) -> str:
    if any(character.isspace() or character in {'"', "'", ";"} for character in value):
        raise ValueError("formal-view Yosys paths and defines must be simple atoms")
    return value


def _validate_yosys_view(
    view_root: Path,
    compile_order: list[str],
    include_dirs: list[str],
    defines: list[str],
    top: str,
) -> None:
    options = ["-sv", "-formal", "-defer"]
    options.extend(
        f"-I{_yosys_atom(str(view_root / directory))}"
        for directory in include_dirs
    )
    options.extend(f"-D{_yosys_atom(define)}" for define in defines)
    files = [_yosys_atom(str(view_root / relative)) for relative in compile_order]
    script = (
        "read_verilog "
        + " ".join([*options, *files])
        + f"; hierarchy -check -top {_yosys_atom(top)}"
    )
    process = subprocess.run(
        ["yosys", "-Q", "-p", script],
        capture_output=True,
        text=True,
        check=False,
    )
    warning_lines = [
        line
        for output in (process.stdout, process.stderr)
        for line in output.splitlines()
        if "Warning:" in line or line.startswith("Warnings:")
    ]
    if warning_lines:
        print("\n".join(warning_lines), file=sys.stderr)
    if process.returncode != 0:
        raise ValueError(
            "formal-view Yosys validation failed: "
            + (process.stderr.strip() or process.stdout.strip())
        )


def _remove_artifact(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()


def _publish_artifacts(artifacts: list[tuple[Path, Path]]) -> None:
    prepared: list[dict[str, Any]] = []
    try:
        for source, target in artifacts:
            target.parent.mkdir(parents=True, exist_ok=True)
            container = Path(
                tempfile.mkdtemp(prefix=".formal-view-publish-", dir=target.parent)
            )
            item = {
                "target": target,
                "container": container,
                "payload": container / "payload",
                "backup": container / "backup",
                "backed_up": False,
                "published": False,
            }
            prepared.append(item)
            if source.is_dir():
                shutil.copytree(source, item["payload"])
            else:
                shutil.copy2(source, item["payload"])
        for item in prepared:
            target = item["target"]
            if target.exists() or target.is_symlink():
                target.replace(item["backup"])
                item["backed_up"] = True
            try:
                item["payload"].replace(target)
                item["published"] = True
            except Exception:
                if item["backed_up"]:
                    item["backup"].replace(target)
                    item["backed_up"] = False
                raise
    except Exception:
        for item in reversed(prepared):
            if item["published"]:
                _remove_artifact(item["target"])
            if item["backed_up"] and item["backup"].exists():
                item["backup"].replace(item["target"])
        raise
    finally:
        for item in prepared:
            shutil.rmtree(item["container"], ignore_errors=True)


def _validate_paths(project_root: Path, output_dir: Path, manifest: Path) -> None:
    root = project_root.resolve()
    output = output_dir.resolve()
    manifest_path = manifest.resolve()
    if not root.is_dir():
        raise ValueError("--project-root must be an existing directory")
    for option, path in (("--output-dir", output), ("--manifest", manifest_path)):
        try:
            path.relative_to(root)
        except ValueError:
            pass
        else:
            raise ValueError(f"{option} must be outside --project-root")
    try:
        root.relative_to(output)
    except ValueError:
        pass
    else:
        raise ValueError("--output-dir cannot contain --project-root")
    if output == root or output == manifest_path:
        raise ValueError("formal-view output paths conflict")
    try:
        manifest_path.relative_to(output)
    except ValueError:
        pass
    else:
        raise ValueError("--manifest cannot be inside --output-dir")
    if output.exists() and (not output.is_dir() or output.is_symlink()):
        raise ValueError("--output-dir must be absent or a directory")
    if manifest_path.exists() and (
        not manifest_path.is_file() or manifest_path.is_symlink()
    ):
        raise ValueError("--manifest must be absent or a regular file")


def _view_inputs(
    *,
    project_root: Path,
    top: str,
    include_dirs: Iterable[str],
    defines: Iterable[str],
) -> tuple[
    dict[str, Any],
    project.ProjectSemanticContext,
    list[str],
    dict[str, bytes],
    list[_Edit],
    dict[str, Any],
]:
    report, _, success, context = project.analyze_project_context(
        project_root=project_root,
        top=top,
        include_dirs=include_dirs,
        defines=defines,
    )
    if not success or context is None:
        diagnostic = report["diagnostics"][0]
        raise ValueError(f"formal-view project analysis failed: {diagnostic['code']}")
    files = list(report["reachable"]["files"])
    sources = {
        relative: (context.project_root / relative).read_bytes()
        for relative in files
    }
    aliases = _packed_struct_aliases(context)
    edits = _ordered_edits(
        (
            _collect_type_edits(context, sources, aliases),
            _collect_member_edits(context, sources, aliases),
            _collect_assertion_edits(context, sources),
        )
    )
    compile_context = {
        "compilation_unit": report["compile"]["compilation_unit"],
        "include_dirs": report["compile"]["include_dirs"],
        "defines": report["compile"]["defines"],
        "compile_order": report["compile"]["compile_order"],
    }
    return report, context, files, sources, edits, compile_context


def validate_formal_view(
    *,
    project_root: Path,
    view_root: Path,
    manifest_path: Path,
    top: str,
    include_dirs: Iterable[str],
    defines: Iterable[str],
) -> dict[str, Any]:
    """Rebuild the manifest model and byte-check an existing formal view."""
    if not view_root.is_dir():
        raise ValueError("gate formal-view directory does not exist")
    if not manifest_path.is_file():
        raise ValueError("gate formal-view manifest does not exist")
    try:
        with manifest_path.open(encoding="utf-8") as stream:
            actual_manifest = json.load(stream)
    except (OSError, ValueError) as error:
        raise ValueError("invalid gate formal-view manifest JSON") from error

    report, context, files, sources, edits, compile_context = _view_inputs(
        project_root=project_root,
        top=top,
        include_dirs=include_dirs,
        defines=defines,
    )
    expected_design = "".join(
        f"{relative}\n" for relative in compile_context["compile_order"]
    ).encode("utf-8")
    design_path = view_root / "design.f"
    if not design_path.is_file() or design_path.read_bytes() != expected_design:
        raise ValueError("gate formal-view design.f mismatch")
    actual_files = {
        path.relative_to(view_root).as_posix()
        for path in view_root.rglob("*")
        if path.is_file()
    }
    if actual_files != {*files, "design.f"}:
        raise ValueError("gate formal-view file set mismatch")

    edits_by_file: dict[str, list[_Edit]] = {}
    for edit in edits:
        edits_by_file.setdefault(edit.record["file"], []).append(edit)
    for relative in files:
        expected = _apply_file_edits(
            sources[relative], edits_by_file.get(relative, [])
        )
        if (view_root / relative).read_bytes() != expected:
            raise ValueError("gate formal-view transformed bytes mismatch")

    view_manifest = _manifest(view_root, files)
    expected_manifest = {
        "version": 1,
        "mode": "formal-view",
        "top": top,
        "source_files": report["reachable"]["source_files"],
        "compile_context": compile_context,
        "source_manifest_sha256": _manifest(context.project_root, files),
        "view_manifest_sha256": view_manifest,
        "design_file": "design.f",
        "transformations": [edit.record for edit in edits],
    }
    if actual_manifest != expected_manifest:
        raise ValueError("gate formal-view manifest content mismatch")
    return actual_manifest


def _validate_alignment_paths(
    *,
    gate_dir: Path,
    gate_view_dir: Path,
    gate_view_manifest: Path,
    mapping_path: Path,
    output_dir: Path,
    manifest_path: Path,
) -> None:
    for option, path, is_directory in (
        ("--gate-dir", gate_dir, True),
        ("--gate-view-dir", gate_view_dir, True),
        ("--gate-view-manifest", gate_view_manifest, False),
        ("--map", mapping_path, False),
    ):
        if is_directory and not path.is_dir():
            raise ValueError(f"{option} must be an existing directory")
        if not is_directory and not path.is_file():
            raise ValueError(f"{option} must be an existing file")
    output = output_dir.resolve()
    manifest = manifest_path.resolve()
    input_directories = [gate_dir.resolve(), gate_view_dir.resolve()]
    input_files = [gate_view_manifest.resolve(), mapping_path.resolve()]
    for directory in input_directories:
        for candidate in (output, manifest):
            try:
                candidate.relative_to(directory)
            except ValueError:
                pass
            else:
                raise ValueError("formal-align output cannot be inside an input")
        try:
            directory.relative_to(output)
        except ValueError:
            pass
        else:
            raise ValueError("--output-dir cannot contain a formal-align input")
    if output == manifest or manifest in input_files or output in input_files:
        raise ValueError("formal-align paths conflict")
    try:
        manifest.relative_to(output)
    except ValueError:
        pass
    else:
        raise ValueError("--manifest cannot be inside --output-dir")
    if output_dir.exists() and (
        not output_dir.is_dir() or output_dir.is_symlink()
    ):
        raise ValueError("--output-dir must be absent or a directory")
    if manifest_path.exists() and (
        not manifest_path.is_file() or manifest_path.is_symlink()
    ):
        raise ValueError("--manifest must be absent or a regular file")


def _identifier_edits(
    *,
    source_path: Path,
    source: bytes,
    replacements: dict[str, str],
) -> list[tuple[int, int, bytes]]:
    manager = pyslang.SourceManager()
    buffer = manager.readSource(source_path)
    allocator = pyslang.BumpAllocator()
    diagnostics = pyslang.Diagnostics()
    lexer = pyslang.parsing.Lexer(buffer, allocator, diagnostics, manager)
    result: list[tuple[int, int, bytes]] = []
    while True:
        token = lexer.lex()
        if token.kind == pyslang.parsing.TokenKind.Identifier:
            original = replacements.get(token.rawText)
            if original is not None:
                start = token.location.offset
                renamed = token.rawText.encode("utf-8")
                end = start + len(renamed)
                if source[start:end] != renamed:
                    raise ValueError("formal-align identifier bytes mismatch")
                result.append((start, end, original.encode("utf-8")))
        if token.kind == pyslang.parsing.TokenKind.EndOfFile:
            break
    if any(diagnostic.isError() for diagnostic in diagnostics):
        raise ValueError("formal-align lexer reported errors")
    return result


def align_formal_view(
    *,
    gate_dir: Path,
    gate_view_dir: Path,
    gate_view_manifest_path: Path,
    mapping_path: Path,
    mapping: dict[str, Any],
    output_dir: Path,
    manifest_path: Path,
) -> dict[str, Any]:
    """Create a mapping-linked, identifier-only aligned gate formal view."""
    _validate_alignment_paths(
        gate_dir=gate_dir,
        gate_view_dir=gate_view_dir,
        gate_view_manifest=gate_view_manifest_path,
        mapping_path=mapping_path,
        output_dir=output_dir,
        manifest_path=manifest_path,
    )
    entries = mapping["entries"]
    if len(entries) != 1091 or sum(item["occurrences"] for item in entries) != 5741:
        raise ValueError("formal-align mapping oracle mismatch")
    replacements = {
        item["renamed_name"]: item["original_name"] for item in entries
    }
    if len(replacements) != len(entries):
        raise ValueError("formal-align renamed names are not globally unique")

    view_manifest = validate_formal_view(
        project_root=gate_dir,
        view_root=gate_view_dir,
        manifest_path=gate_view_manifest_path,
        top=mapping["top"],
        include_dirs=mapping["compile_context"]["include_dirs"],
        defines=mapping["compile_context"]["defines"],
    )
    if view_manifest["source_manifest_sha256"] != mapping["gate_manifest_sha256"]:
        raise ValueError("formal-align gate and view input chain mismatch")
    if view_manifest["source_files"] != mapping["source_files"]:
        raise ValueError("formal-align source file list mismatch")
    if view_manifest["compile_context"] != mapping["compile_context"]:
        raise ValueError("formal-align compile context mismatch")

    files = mapping["files"]
    edits_by_file: dict[str, list[tuple[int, int, bytes]]] = {}
    replacement_count = 0
    for relative in files:
        path = gate_view_dir / relative
        source = path.read_bytes()
        edits = _identifier_edits(
            source_path=path, source=source, replacements=replacements
        )
        edits_by_file[relative] = edits
        replacement_count += len(edits)
    if replacement_count != 5527:
        raise ValueError("formal-align identifier replacement oracle mismatch")

    with tempfile.TemporaryDirectory(prefix="rtl-obfuscation-formal-align-") as tmp:
        staging_root = Path(tmp)
        staging_view = staging_root / "view"
        for relative in files:
            source = (gate_view_dir / relative).read_bytes()
            rewritten = source
            for start, end, replacement in reversed(edits_by_file[relative]):
                rewritten = rewritten[:start] + replacement + rewritten[end:]
            target = staging_view / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(rewritten)
        design_bytes = (gate_view_dir / "design.f").read_bytes()
        (staging_view / "design.f").write_bytes(design_bytes)
        aligned_manifest = _manifest(staging_view, files)
        manifest = {
            "version": 1,
            "mode": "formal-name-alignment",
            "top": mapping["top"],
            "source_files": mapping["source_files"],
            "compile_order": mapping["compile_context"]["compile_order"],
            "source_gate_manifest_sha256": mapping["gate_manifest_sha256"],
            "source_view_manifest_sha256": view_manifest[
                "view_manifest_sha256"
            ],
            "mapping_sha256": _sha256(mapping_path.read_bytes()),
            "mapping_entries": len(entries),
            "mapping_occurrences": sum(item["occurrences"] for item in entries),
            "identifier_replacements": replacement_count,
            "aligned_view_manifest_sha256": aligned_manifest,
            "design_file": "design.f",
        }
        staging_manifest = staging_root / "formal-align.json"
        with staging_manifest.open("w", encoding="utf-8") as stream:
            json.dump(manifest, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        _validate_yosys_view(
            staging_view,
            mapping["compile_context"]["compile_order"],
            mapping["compile_context"]["include_dirs"],
            mapping["compile_context"]["defines"],
            mapping["top"],
        )
        _publish_artifacts(
            [(staging_view, output_dir), (staging_manifest, manifest_path)]
        )
    return {
        "files": len(files),
        "identifier_replacements": replacement_count,
        "top": mapping["top"],
        "view_manifest_sha256": aligned_manifest,
    }


def build_formal_view(
    *,
    project_root: Path,
    top: str,
    output_dir: Path,
    manifest_path: Path,
    include_dirs: Iterable[str] = (),
    defines: Iterable[str] = (),
) -> dict[str, Any]:
    """Build, validate, and transactionally publish one formal-only view."""
    _validate_paths(project_root, output_dir, manifest_path)
    report, context, files, sources, edits, compile_context = _view_inputs(
        project_root=project_root,
        top=top,
        include_dirs=include_dirs,
        defines=defines,
    )
    edits_by_file: dict[str, list[_Edit]] = {}
    for edit in edits:
        edits_by_file.setdefault(edit.record["file"], []).append(edit)

    with tempfile.TemporaryDirectory(prefix="rtl-obfuscation-formal-view-") as tmp:
        staging_root = Path(tmp)
        staging_view = staging_root / "view"
        for relative in files:
            transformed = _apply_file_edits(
                sources[relative], edits_by_file.get(relative, [])
            )
            target = staging_view / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(transformed)
        design_file = "".join(
            f"{relative}\n" for relative in compile_context["compile_order"]
        )
        (staging_view / "design.f").write_text(design_file, encoding="utf-8")
        view_manifest = _manifest(staging_view, files)
        manifest = {
            "version": 1,
            "mode": "formal-view",
            "top": top,
            "source_files": report["reachable"]["source_files"],
            "compile_context": compile_context,
            "source_manifest_sha256": _manifest(context.project_root, files),
            "view_manifest_sha256": view_manifest,
            "design_file": "design.f",
            "transformations": [edit.record for edit in edits],
        }
        staging_manifest = staging_root / "formal-view.json"
        with staging_manifest.open("w", encoding="utf-8") as stream:
            json.dump(manifest, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        _validate_yosys_view(
            staging_view,
            compile_context["compile_order"],
            compile_context["include_dirs"],
            compile_context["defines"],
            top,
        )
        _publish_artifacts(
            [(staging_view, output_dir), (staging_manifest, manifest_path)]
        )

    return {
        "files": len(files),
        "top": top,
        "transformations": len(edits),
        "view_manifest_sha256": view_manifest,
    }
