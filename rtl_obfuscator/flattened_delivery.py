"""Compile-oriented flattened delivery for authoritative filelists."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

from .source_set import FilelistEntry, SourceSet


_INCLUDE_HEAD = re.compile(r"^\s*`include\b(.*)$")
_STATIC_INCLUDE = re.compile(r'^\s*"([^"\\]+)"\s*$')
_DEFINE = re.compile(r"([A-Za-z_][A-Za-z0-9_$]*)(?:=(.*))?\Z")


class FlattenedDeliveryError(ValueError):
    """A flat artifact cannot be safely added to this gate."""


@dataclass(frozen=True)
class FlattenedDelivery:
    design: bytes
    log: bytes
    manifest: dict[str, object]


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _strip_comments(line: str, in_block: bool) -> tuple[str, bool]:
    """Remove SV comments while keeping quoted include tokens intact."""

    result: list[str] = []
    index = 0
    quoted = False
    escaped = False
    while index < len(line):
        if in_block:
            end = line.find("*/", index)
            if end < 0:
                return "".join(result), True
            index = end + 2
            in_block = False
            continue
        character = line[index]
        if quoted:
            result.append(character)
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                quoted = False
            index += 1
            continue
        if line.startswith("//", index):
            break
        if line.startswith("/*", index):
            in_block = True
            index += 2
            continue
        result.append(character)
        if character == '"':
            quoted = True
        index += 1
    return "".join(result), in_block


def _scan_includes(source: str, content: bytes) -> tuple[list[dict[str, object]], list[str]]:
    try:
        text = content.decode("utf-8")
    except UnicodeError:
        return [], [f"source_not_utf8:{source}"]
    includes: list[dict[str, object]] = []
    issues: list[str] = []
    in_block = False
    for line_number, line in enumerate(text.splitlines(), start=1):
        visible, in_block = _strip_comments(line, in_block)
        match = _INCLUDE_HEAD.match(visible)
        if match is None:
            continue
        operand = match.group(1).strip()
        static = _STATIC_INCLUDE.fullmatch(operand)
        if static is None:
            token = operand
            includes.append({
                "source": source,
                "line": line_number,
                "include": token,
                "original_target": None,
                "flattened_target": None,
                "status": "unresolved",
            })
            issues.append(f"include_unresolved:{source}:{line_number}")
            continue
        includes.append({
            "source": source,
            "line": line_number,
            "include": static.group(1),
            "original_target": None,
            "flattened_target": None,
            "status": "pending",
        })
    return includes, issues


def _relative_file(path: Path, root: Path) -> str | None:
    try:
        resolved = path.resolve()
        return resolved.relative_to(root.resolve()).as_posix()
    except (OSError, RuntimeError, ValueError):
        return None


def _physical_file(root: Path, relative: str) -> Path | None:
    candidate = root / relative
    current = root
    for component in PurePosixPath(relative).parts:
        current = current / component
        if current.is_symlink():
            return None
    return candidate if candidate.is_file() else None


def _find_include(
    *,
    root: Path,
    source_directory: str,
    token: str,
    include_dirs: tuple[str, ...],
) -> tuple[str, str | None] | None:
    raw = Path(token)
    if raw.is_absolute():
        candidates = ((raw, None),)
    else:
        candidates = (
            (root / source_directory / raw, None),
            *((root / include_dir / raw, include_dir) for include_dir in include_dirs),
        )
    for candidate, directory in candidates:
        relative = _relative_file(candidate, root)
        if relative is not None and _physical_file(root, relative) is not None:
            return relative, directory
    return None


def _cli_define_values(values: tuple[str, ...]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        match = _DEFINE.fullmatch(value)
        if match is not None:
            result[match.group(1)] = match.group(2) if match.group(2) is not None else "1"
    return result


def _cli_only_defines(
    source_set: SourceSet,
    cli_defines: tuple[str, ...],
) -> dict[str, str]:
    cli_values = _cli_define_values(cli_defines)
    if not cli_values:
        return {}
    filelist_values: dict[str, str] = {}
    for entry in source_set.filelist_entries:
        if entry.kind != "define":
            continue
        match = _DEFINE.fullmatch(entry.value)
        if match is not None:
            filelist_values[match.group(1)] = (
                match.group(2) if match.group(2) is not None else "1"
            )
    effective = dict(source_set.defines)
    candidates = {
        name: value
        for name, value in cli_values.items()
        if filelist_values.get(name) != value and effective.get(name) == value
    }
    # Macro use also appears in `ifdef/`ifndef branches and can affect
    # preprocessor-selected includes. Keep every CLI-only effective define
    # external instead of trying to infer whether it is semantically unused.
    return dict(sorted(candidates.items()))


def _render_design(entries: tuple[FilelistEntry, ...]) -> bytes:
    lines: list[str] = []
    for entry in entries:
        if entry.kind in {"source", "library_source"}:
            token = f"$OUT_FLAT/{PurePosixPath(entry.value).name}"
            lines.append(f"-v {token}" if entry.kind == "library_source" else token)
        elif entry.kind == "context_file":
            lines.append(f"$OUT/{entry.value}" if entry.value != "." else "$OUT")
        elif entry.kind == "include_dir":
            value = f"$OUT/{entry.value}" if entry.value != "." else "$OUT"
            lines.append(f"+incdir+{value}")
        elif entry.kind == "define":
            lines.append(f"+define+{entry.value}")
        else:
            raise FlattenedDeliveryError(f"unsupported filelist entry kind: {entry.kind}")
    return ("".join(f"{line}\n" for line in lines)).encode("utf-8")


def build_flattened_delivery(
    source_set: SourceSet,
    gate_dir: Path,
    *,
    cli_defines: tuple[str, ...] = (),
) -> FlattenedDelivery:
    """Write the flat artifacts into a private gate staging directory."""

    if source_set.origin != "filelist":
        raise FlattenedDeliveryError("flattened delivery requires filelist origin")

    source_names = tuple(source_set.ordered_source_files)
    names = [PurePosixPath(source).name for source in source_names]
    seen_names: set[str] = set()
    collisions: set[str] = set()
    for name in names:
        if name in seen_names:
            collisions.add(name)
        seen_names.add(name)
    ordered_collisions = sorted(collisions)
    if ordered_collisions:
        raise FlattenedDeliveryError(f"flattened basename collision: {ordered_collisions[0]}")

    flat_root = gate_dir / "src_flattened"
    design_path = gate_dir / "design_flattened.f"
    log_path = gate_dir / "src_flattened_log"
    if flat_root.exists() or flat_root.is_symlink():
        raise FlattenedDeliveryError("flattened artifact path collision: src_flattened")
    for path, label in ((design_path, "design_flattened.f"), (log_path, "src_flattened_log")):
        if path.exists() or path.is_symlink():
            raise FlattenedDeliveryError(f"flattened artifact path collision: {label}")

    explicit_entries = tuple(
        entry for entry in source_set.filelist_entries
        if entry.kind in {"source", "library_source"}
    )
    if tuple(entry.value for entry in explicit_entries) != source_names:
        raise FlattenedDeliveryError("filelist source order differs from SourceSet")

    design = _render_design(source_set.filelist_entries)
    flat_root.mkdir()
    source_records: list[dict[str, str]] = []
    flat_payloads: dict[str, bytes] = {}
    for source in source_names:
        canonical = _physical_file(gate_dir, source)
        if canonical is None:
            raise FlattenedDeliveryError(f"canonical gate source is not a regular file: {source}")
        payload = canonical.read_bytes()
        flat_name = PurePosixPath(source).name
        flat_path = flat_root / flat_name
        flat_path.write_bytes(payload)
        flat_payloads[source] = payload
        source_records.append({
            "source": source,
            "flat": f"src_flattened/{flat_name}",
            "sha256": _sha256(payload),
        })

    filelist_include_dirs = tuple(
        entry.value for entry in source_set.filelist_entries if entry.kind == "include_dir"
    )
    filelist_include_dir_set = set(filelist_include_dirs)
    cli_only_dirs = tuple(
        directory for directory in source_set.include_dirs
        if directory not in filelist_include_dir_set
    )
    used_cli_defines = _cli_only_defines(source_set, cli_defines)
    includes: list[dict[str, object]] = []
    reasons: list[str] = []
    required_cli_dirs: set[str] = set()

    for source in source_names:
        scanned, issues = _scan_includes(source, flat_payloads[source])
        reasons.extend(issues)
        for item in scanned:
            token = item["include"]
            if not isinstance(token, str) or item["status"] == "unresolved":
                includes.append(item)
                continue
            original_match = _find_include(
                root=source_set.source_root,
                source_directory=PurePosixPath(source).parent.as_posix(),
                token=token,
                include_dirs=source_set.include_dirs,
            )
            if original_match is None:
                item["status"] = "unresolved"
                reasons.append(f"include_original_unresolved:{source}:{item['line']}")
                includes.append(item)
                continue
            original_target, original_include_dir = original_match
            item["original_target"] = original_target
            if original_include_dir in cli_only_dirs:
                assert original_include_dir is not None
                required_cli_dirs.add(original_include_dir)
                reasons.append(f"cli_include_context_required:{source}:{item['line']}")
            flat_match = _find_include(
                root=gate_dir,
                source_directory="src_flattened",
                token=token,
                include_dirs=tuple(
                    directory for directory in filelist_include_dirs
                ),
            )
            flat_target = None if flat_match is None else flat_match[0]
            item["flattened_target"] = flat_target
            if flat_target is None:
                item["status"] = "missing"
                reasons.append(f"include_flattened_missing:{source}:{item['line']}")
            else:
                original_path = _physical_file(gate_dir, original_target)
                flattened_path = _physical_file(gate_dir, flat_target)
                if (
                    flat_target != original_target
                    or original_path is None
                    or flattened_path is None
                    or original_path.read_bytes() != flattened_path.read_bytes()
                ):
                    item["status"] = "changed"
                    reasons.append(f"include_flattened_changed:{source}:{item['line']}")
                else:
                    item["status"] = "same"
            includes.append(item)

    for name in used_cli_defines:
        reasons.append(f"cli_define_context_required:{name}")
    log_value: dict[str, object] = {
        "format": "rtl-obfuscation.src-flattened-log",
        "schema_version": 1,
        "compile_ready": not reasons,
        "includes": includes,
    }
    external_context: dict[str, object] = {
        "include_dirs": [
            directory for directory in source_set.include_dirs
            if directory in required_cli_dirs
        ],
        "defines": [
            {"name": name, "value": used_cli_defines[name]}
            for name in sorted(used_cli_defines)
        ],
    }
    if external_context["include_dirs"] or external_context["defines"]:
        log_value["external_context"] = external_context
    if reasons:
        log_value["reasons"] = list(dict.fromkeys(reasons))
    log = (json.dumps(log_value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    design_path.write_bytes(design)
    log_path.write_bytes(log)
    manifest = {
        "design_sha256": _sha256(design),
        "log_sha256": _sha256(log),
        "sources": source_records,
    }
    return FlattenedDelivery(design=design, log=log, manifest=manifest)
