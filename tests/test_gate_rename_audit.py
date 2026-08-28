"""Checks for the read-only gate rename audit.

The audit exists because strict compilation cannot prove a rewrite correct.
Measured: reverting one renamed reference back to its old name leaves PySlang
with zero parse and zero semantic errors, because SystemVerilog's default
nettype absorbs the undeclared identifier as an implicit wire.  These tests
assert both directions — the auditor must flag that gate, and must not cry wolf
on an intact one.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
AUDITOR = REPOSITORY / "scripts" / "gate_rename_audit.py"
T110_FIXTURE = REPOSITORY / "tests" / "fixtures" / "t110_binding_fixes"
T112_FIXTURE = REPOSITORY / "tests" / "fixtures" / "t112_gate_rename_audit"
T114_FIXTURE = REPOSITORY / "tests" / "fixtures" / "t114_implicit_net_collision"


def _load_auditor():
    name = "t112_gate_rename_audit_module"
    cached = sys.modules.get(name)
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location(name, AUDITOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclass and annotations resolve through sys.modules, so register first.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _encrypt(filelist: Path, top: str, output: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(REPOSITORY / "rtl_encrypt.py"),
            "--filelist", str(filelist),
            "--top", top,
            "--category", "all",
            "--output-dir", str(output),
        ],
        cwd=REPOSITORY,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def _audit(map_path: Path, gate_dir: Path, gold_root: Path) -> tuple[int, dict]:
    completed = subprocess.run(
        [
            sys.executable, str(AUDITOR),
            "--map", str(map_path),
            "--gate-dir", str(gate_dir),
            "--gold-root", str(gold_root),
            "--quiet",
        ],
        cwd=REPOSITORY,
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode, json.loads(completed.stdout)


def _compile_gate(gate_dir: Path, source_set: dict) -> tuple[int, int]:
    """Compile a gate exactly as the product does and return its error counts."""

    if str(REPOSITORY) not in sys.path:
        sys.path.insert(0, str(REPOSITORY))
    from rtl_obfuscator.project_discovery import compile_pyslang_source_set

    view = compile_pyslang_source_set(
        root=gate_dir,
        compilation_files=tuple(source_set["compile_order"]),
        include_files=tuple(source_set.get("included_files", ())),
        include_dirs=tuple(source_set.get("include_dirs", ())),
        defines=dict(source_set.get("defines", ()) or ()),
        top=None,
    )
    return len(view.parse_errors), len(view.semantic_errors)


def _revert_one_renamed_reference(
    gate: Path,
    mapping: dict,
    source_set: dict,
    destination: Path,
    only_old_name: str | None = None,
) -> tuple[Path, str, int] | None:
    """Copy the gate and revert one renamed reference to its old name.

    Not every reverted edit stays invisible to the compiler: reverting a
    connection *label* names a port that no longer exists, and strict
    compilation rightly rejects that.  This audit exists for the edits that the
    compiler accepts, so the damage point is chosen by trying candidates and
    keeping the first whose damaged gate still compiles with zero errors.  The
    search is deterministic for a fixed fixture.

    ``only_old_name`` narrows the search to one spelling, which is how a fixture
    can demand that the damage land on the identifier it was built around.

    Returns ``(damaged gate, reverted old name, gate offset)``, or ``None`` when
    no candidate left the gate compiling cleanly -- which means the audit's
    premise no longer holds for that fixture.
    """

    candidates: list[tuple[str, str, str, dict]] = []
    for entry in mapping["mapping_execution"]["per_file_mapping"]:
        for record in entry["records"]:
            if record.get("action") != "rename":
                continue
            if only_old_name is not None and record["original_name"] != only_old_name:
                continue
            for item in record["ranges"]:
                if item.get("provenance") != "semantic_reference":
                    continue
                candidates.append(
                    (
                        entry["file"],
                        record["original_name"],
                        record["renamed_name"],
                        item["gate_range"],
                    )
                )
    assert candidates, "fixture has no semantic_reference edit"

    for file, original, renamed, gate_range in candidates:
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(gate, destination)
        path = destination / file
        data = bytearray(path.read_bytes())
        start, end = gate_range["start"], gate_range["end"]
        if bytes(data[start:end]).decode(errors="replace") != renamed:
            continue
        data[start:end] = original.encode()
        path.write_bytes(bytes(data))
        if _compile_gate(destination, source_set) == (0, 0):
            return destination, original, start
    return None


class GateRenameAuditTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = TemporaryDirectory(prefix="t112-audit-")
        base = Path(cls._temporary.name)
        cls.gate = base / "gate"
        _encrypt(T110_FIXTURE / "design.f", "t110_top", cls.gate)
        cls.mapping = json.loads((cls.gate / "mapping.json").read_text())
        cls.source_set = cls.mapping["source_set"]

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def _damaged_gate(self) -> tuple[Path, str, int]:
        """Copy the gate and revert one renamed reference to its old name.

        The damage point is searched for rather than fixed, because reverting a
        connection label is rejected by strict compilation while reverting an
        actual is not; see ``_revert_one_renamed_reference``.
        """

        found = _revert_one_renamed_reference(
            self.gate,
            self.mapping,
            self.source_set,
            Path(self._temporary.name) / "damaged",
        )
        if found is None:
            self.fail(
                "no reverted edit left the gate compiling cleanly; the audit's "
                "premise no longer holds for this fixture"
            )
        return found

    def test_intact_gate_is_clean(self) -> None:
        code, report = _audit(
            self.gate / "mapping.json", self.gate, T110_FIXTURE
        )
        self.assertEqual(report["verdict"], "clean", report["implicit_nets"])
        self.assertEqual(code, 0)
        self.assertEqual(report["implicit_nets"]["gate_only"], 0)
        self.assertEqual(report["renamed_range_bytes"]["mismatched"], 0)
        self.assertGreater(report["renamed_range_bytes"]["checked"], 0)
        self.assertEqual(report["compile"]["gold"]["semantic_errors"], 0)
        self.assertEqual(report["compile"]["gate"]["semantic_errors"], 0)

    def test_damaged_gate_still_compiles_but_is_flagged(self) -> None:
        damaged, original, offset = self._damaged_gate()

        # The premise of this whole audit: the damage is invisible to strict
        # compilation.  If this assertion ever fails, the compiler caught it and
        # the audit would be redundant for this shape.
        parse_errors, semantic_errors = _compile_gate(damaged, self.source_set)
        self.assertEqual((parse_errors, semantic_errors), (0, 0))

        code, report = _audit(self.gate / "mapping.json", damaged, T110_FIXTURE)
        self.assertEqual(report["verdict"], "suspect")
        self.assertEqual(code, 1)

        # Check 1 names the leftover identifier precisely.
        self.assertEqual(report["implicit_nets"]["gate_only"], 1)
        self.assertEqual(
            [item["name"] for item in report["implicit_nets"]["gate_only_detail"]],
            [original],
        )

        # Check 2 independently flags the same offset from the published bytes.
        self.assertGreater(report["renamed_range_bytes"]["mismatched"], 0)
        flagged = {
            item["start"]
            for item in report["renamed_range_bytes"]["misplaced_detail"]
            + report["renamed_range_bytes"]["leaked_detail"]
        }
        self.assertIn(offset, flagged)

    def test_gold_side_implicit_net_is_not_blamed_on_the_rewrite(self) -> None:
        """A design that already relies on an implicit net must stay clean.

        The gold net is renamed too, so the differencing has to translate gold
        names through the rename map; comparing raw spellings would report every
        renamed implicit net as newly introduced.
        """

        with TemporaryDirectory(prefix="t112-implicit-") as temporary:
            gate = Path(temporary) / "gate"
            _encrypt(
                T112_FIXTURE / "implicit_gold.f", "t112_implicit_top", gate
            )
            code, report = _audit(gate / "mapping.json", gate, T112_FIXTURE)
            self.assertGreater(
                report["implicit_nets"]["gold"], 0, "fixture must have one"
            )
            self.assertEqual(report["implicit_nets"]["gate_only"], 0)
            self.assertEqual(report["verdict"], "clean")
            self.assertEqual(code, 0)

    def test_report_identity_and_residual_is_report_only(self) -> None:
        code, report = _audit(
            self.gate / "mapping.json", self.gate, T110_FIXTURE
        )
        self.assertEqual(report["format"], "rtl-obfuscation.gate-rename-audit")
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(code, 0)
        # The residual scan is deliberately not part of the verdict: several
        # distinct symbols may share a spelling, so a hit needs human judgement.
        self.assertGreater(report["residual_old_names"]["count"], 0)
        self.assertEqual(report["verdict"], "clean")
        self.assertIn("report only", report["residual_old_names"]["note"])

    def test_schema_one_mapping_is_rejected(self) -> None:
        module = _load_auditor()
        with TemporaryDirectory(prefix="t112-schema-") as temporary:
            path = Path(temporary) / "mapping.json"
            path.write_text(
                json.dumps(
                    {
                        "format": "rtl-obfuscation.cli-vnext",
                        "mapping": {"schema_version": 1},
                    }
                )
            )
            with self.assertRaises(SystemExit) as raised:
                module._load_mapping(path)
            self.assertEqual(raised.exception.code, 2)

    def test_auditor_writes_no_file_without_json_flag(self) -> None:
        before = sorted(path.name for path in self.gate.iterdir())
        _audit(self.gate / "mapping.json", self.gate, T110_FIXTURE)
        self.assertEqual(sorted(path.name for path in self.gate.iterdir()), before)


class GoldRootDerivationTest(unittest.TestCase):
    """The mapping stores only relative paths, so the root must be derived.

    A filelist commonly sits deep inside the tree it describes: StCache's is at
    ``<root>/aic_ss/src/stcache/StCache.f`` while its compile order is relative
    to ``<root>``, because the include directories pull the inferred root up.
    Taking the filelist's own directory as the root produced a duplicated path
    on the server, so the resolver walks up until the compile order resolves.
    """

    def setUp(self) -> None:
        self.module = _load_auditor()
        self._temporary = TemporaryDirectory(prefix="t112-root-")
        base = Path(self._temporary.name)
        self.root = base / "ChipPlatform"
        (self.root / "aic_ss/src/stcache/src/Csr").mkdir(parents=True)
        (self.root / "aic_ss/src/stcache/src/Csr/StChCsr.sv").write_text(
            "module m; endmodule\n"
        )
        self.filelist = self.root / "aic_ss/src/stcache/StCache.f"
        self.filelist.write_text("src/Csr/StChCsr.sv\n")
        self.source_set = {
            "compile_order": ["aic_ss/src/stcache/src/Csr/StChCsr.sv"]
        }

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def _args(self, **overrides) -> object:
        import argparse

        values = {"gold_root": None, "gold_filelist": str(self.filelist)}
        values.update(overrides)
        return argparse.Namespace(**values)

    def test_root_is_derived_by_walking_up_from_the_filelist(self) -> None:
        derived = self.module._resolve_gold_root(self._args(), self.source_set)
        self.assertEqual(derived, self.root.resolve())
        # The filelist's own directory is explicitly the wrong answer here.
        self.assertNotEqual(derived, self.filelist.parent.resolve())

    def test_explicit_gold_root_wins(self) -> None:
        derived = self.module._resolve_gold_root(
            self._args(gold_root=str(self.root)), self.source_set
        )
        self.assertEqual(derived, self.root.resolve())

    def test_undecidable_root_fails_loudly(self) -> None:
        missing = Path(self._temporary.name) / "nowhere" / "x.f"
        with self.assertRaises(SystemExit) as raised:
            self.module._resolve_gold_root(
                self._args(gold_filelist=str(missing)), self.source_set
            )
        self.assertEqual(raised.exception.code, 2)

    def test_missing_both_inputs_fails_loudly(self) -> None:
        with self.assertRaises(SystemExit) as raised:
            self.module._resolve_gold_root(
                self._args(gold_filelist=None), self.source_set
            )
        self.assertEqual(raised.exception.code, 2)


class ImplicitNetCollisionTest(unittest.TestCase):
    """Translating a gold implicit net must be decided by position, not by name.

    Measured on ``rtl_samples/RISC-V-Vector``: 169 old names are renamed to more
    than one new name, ``i`` to 27 of them.  A global ``old name -> new name``
    dictionary keeps only the last of them, so a gold implicit net gets
    translated to a spelling the gate does not hold and a correct gate is
    reported ``suspect``.  T113 hit exactly that on ``valid`` in
    ``rtl/vector/vmu.sv``, which carries no declaration at all.

    That sample can no longer reproduce it: T113 now preserves every ``valid``
    as ``unelaborated_reference``, so the spelling has no rename record left to
    collide with.  Hence this dedicated fixture, which holds the shape open.

    Three directions are asserted: the name-keyed translation must false-report
    the intact gate, the position-keyed one must call it clean, and the
    position-keyed one must still flag a gate whose reference was reverted --
    otherwise ``gate_only == 0`` could have been bought by simply widening
    ``expected_gate``.
    """

    COLLIDING_NAME = "valid"

    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = TemporaryDirectory(prefix="t114-collision-")
        base = Path(cls._temporary.name)
        cls.gate = base / "gate"
        _encrypt(T114_FIXTURE / "collision.f", "t114_collision_top", cls.gate)
        cls.payload = json.loads((cls.gate / "mapping.json").read_text())
        cls.source_set = cls.payload["source_set"]
        cls.renames = [
            record
            for record in cls.payload["mapping"]["records"]
            if record.get("action") == "rename"
        ]

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def _implicit_nets(self, root: Path) -> set[tuple[str, int, str]]:
        """Ask the auditor itself for the positioned implicit nets of a tree."""

        module = _load_auditor()
        view = module._View("probe", root, self.source_set)
        self.assertEqual((view.parse_errors, view.semantic_errors), (0, 0))
        return view.implicit_nets()

    def _gold_implicit_collision(self) -> tuple[str, int, str]:
        gold = self._implicit_nets(T114_FIXTURE)
        matching = sorted(
            item for item in gold if item[2] == self.COLLIDING_NAME
        )
        self.assertEqual(
            len(matching),
            1,
            f"fixture must hold exactly one gold implicit {self.COLLIDING_NAME}",
        )
        return matching[0]

    def test_fixture_really_reproduces_the_key_collision(self) -> None:
        """Without these preconditions the fixture would prove nothing.

        If the colliding spelling also appeared in dead source, T113's
        ``unelaborated_reference`` rule would preserve every one of its records,
        nothing would be renamed, and the key collision could not happen -- while
        the fixture still passed.  So the preconditions are asserted, not assumed.
        """

        records = [
            record
            for record in self.payload["mapping"]["records"]
            if record.get("original_name") == self.COLLIDING_NAME
        ]
        self.assertGreaterEqual(len(records), 3, records)

        # No record of this spelling may be preserved at all, and in particular
        # not for T113's dead-source reason.
        self.assertEqual(
            [record for record in records if record.get("action") != "rename"],
            [],
            "the colliding spelling must be fully renamed",
        )
        self.assertNotIn(
            "unelaborated_reference",
            {str(record.get("reason")) for record in records},
        )

        # The new names must be pairwise distinct; that is what a single-valued
        # dictionary cannot represent.
        new_names = [record["renamed_name"] for record in records]
        self.assertEqual(len(set(new_names)), len(new_names), new_names)

        # And the value a global dictionary would keep must differ from the one
        # the gold implicit net actually got, or there would be nothing to fix.
        file, offset, _ = self._gold_implicit_collision()
        implicit_new_name = {
            (record["declaration"]["file"], record["declaration"]["start"]):
                record["renamed_name"]
            for record in records
        }[(file, offset)]
        name_keyed = {
            record["original_name"]: record["renamed_name"]
            for record in self.renames
        }[self.COLLIDING_NAME]
        self.assertNotEqual(name_keyed, implicit_new_name)

    def test_name_keyed_translation_false_reports_the_intact_gate(self) -> None:
        """The old behaviour, rebuilt locally: it must blame a correct gate.

        Rebuilt in the test rather than kept in the product script, so there is
        only one translation path shipped.  The fingerprint asserted here is the
        one T113 recorded: the flagged name is a *new* obfuscated name, not an
        old name a rewrite could have missed.
        """

        gold = self._implicit_nets(T114_FIXTURE)
        gate = self._implicit_nets(self.gate)

        name_keyed = {
            record["original_name"]: record["renamed_name"]
            for record in self.renames
        }
        expected = {
            (file, name_keyed.get(name, name)) for file, _, name in gold
        }
        gate_only = sorted({(file, name) for file, _, name in gate} - expected)

        self.assertTrue(gate_only, "the collision must produce a false report")
        old_names = {record["original_name"] for record in self.renames}
        new_names = {record["renamed_name"] for record in self.renames}
        for _, name in gate_only:
            self.assertIn(name, new_names, name)
            self.assertNotIn(name, old_names, name)

    def test_position_keyed_translation_keeps_the_intact_gate_clean(self) -> None:
        code, report = _audit(
            self.gate / "mapping.json", self.gate, T114_FIXTURE
        )
        implicit = report["implicit_nets"]
        self.assertGreater(implicit["gold"], 0, "fixture must have one")
        self.assertEqual(implicit["gate_only"], 0, implicit["gate_only_detail"])
        self.assertEqual(report["verdict"], "clean")
        self.assertEqual(code, 0)
        # Every gold implicit net was located, so no expectation was widened by
        # falling back to an old name.
        self.assertEqual(
            implicit["gold_fallback_to_old_name"], 0, implicit["gold_fallback_detail"]
        )
        self.assertIn("report only", implicit["gold_fallback_note"])
        self.assertEqual(report["compile"]["gold"]["semantic_errors"], 0)
        self.assertEqual(report["compile"]["gate"]["semantic_errors"], 0)

    def test_position_keyed_translation_still_flags_a_damaged_gate(self) -> None:
        """The anti-cheat: ``gate_only == 0`` must not come from a wider net.

        Widening ``expected_gate`` would reach a clean verdict trivially, so the
        same fixture is damaged the way the compiler cannot see -- one already
        renamed reference reverted to its old name -- and the audit must name
        precisely that old name.
        """

        found = _revert_one_renamed_reference(
            self.gate,
            self.payload,
            self.source_set,
            Path(self._temporary.name) / "damaged",
        )
        if found is None:
            self.fail(
                "no reverted edit left the gate compiling cleanly; the audit's "
                "premise no longer holds for this fixture"
            )
        damaged, original, offset = found

        # The premise: the damage is invisible to strict compilation.
        self.assertEqual(_compile_gate(damaged, self.source_set), (0, 0))

        code, report = _audit(self.gate / "mapping.json", damaged, T114_FIXTURE)
        self.assertEqual(report["verdict"], "suspect")
        self.assertEqual(code, 1)
        self.assertEqual(report["implicit_nets"]["gate_only"], 1)
        self.assertEqual(
            [item["name"] for item in report["implicit_nets"]["gate_only_detail"]],
            [original],
        )
        self.assertEqual(report["implicit_nets"]["gold_fallback_to_old_name"], 0)

        # Check 2 independently flags the same offset from the published bytes.
        flagged = {
            item["start"]
            for item in report["renamed_range_bytes"]["misplaced_detail"]
            + report["renamed_range_bytes"]["leaked_detail"]
        }
        self.assertIn(offset, flagged)

    def test_damage_on_the_colliding_spelling_itself_is_still_flagged(self) -> None:
        """The cheapest wrong fix is masked exactly here.

        Widening ``expected_gate`` to hold both the old and the new spelling of a
        colliding name would reach ``gate_only == 0`` on the intact gate and
        would also swallow a genuinely missed reference to that same name.  The
        previous test cannot see that, because its damage point is whichever
        reference the search happens to reach first.  This one forces the damage
        onto the colliding spelling and requires the audit to still name it.
        """

        found = _revert_one_renamed_reference(
            self.gate,
            self.payload,
            self.source_set,
            Path(self._temporary.name) / "damaged-colliding",
            only_old_name=self.COLLIDING_NAME,
        )
        if found is None:
            self.fail(
                f"no reverted {self.COLLIDING_NAME} reference left the gate "
                "compiling cleanly; the audit's premise no longer holds here"
            )
        damaged, original, offset = found
        self.assertEqual(original, self.COLLIDING_NAME)
        self.assertEqual(_compile_gate(damaged, self.source_set), (0, 0))

        code, report = _audit(self.gate / "mapping.json", damaged, T114_FIXTURE)
        self.assertEqual(report["verdict"], "suspect")
        self.assertEqual(code, 1)
        self.assertEqual(report["implicit_nets"]["gate_only"], 1)
        self.assertEqual(
            [item["name"] for item in report["implicit_nets"]["gate_only_detail"]],
            [self.COLLIDING_NAME],
        )
        self.assertEqual(report["implicit_nets"]["gold_fallback_to_old_name"], 0)
        flagged = {
            item["start"]
            for item in report["renamed_range_bytes"]["misplaced_detail"]
            + report["renamed_range_bytes"]["leaked_detail"]
        }
        self.assertIn(offset, flagged)


if __name__ == "__main__":
    unittest.main()
