# T151：FAST 分支的展平源码交付与 include 检测

- 状态：`ACCEPTED`
- Main Agent：冻结合同和测试、独立验收、提交推送
- 实现：Luna extra high 子 Agent；停在 `READY_FOR_REVIEW`
- 起点：`ef916f2`，`delivery/fast-local-signals` 与 origin 一致，创建本合同和冻结测试前工作区干净
- 前置：T150 已 `ACCEPTED`、提交并推送；本任务是唯一活动任务

## 单一目标与输出合同

有界移植 main 已验收 T149 的公开显式 `--filelist` 展平交付到 FAST 分支。gate 中增加 `src_flattened/`（每个显式 `.sv/.v` source unit、含 `-v`，从 canonical encrypted gate 复制同名字节副本；basename 重名原子拒绝）、`design_flattened.f`（按有效递归 `-f` 顺序就地展开，source 写 `$OUT_FLAT/<basename>`，`-v` 保留，context 和 `+incdir+` 写 `$OUT/<source-root-relative-path>`，`+define+` 保留值和顺序）、`src_flattened_log`（UTF-8 JSON、include 原目标与展平目标、same/missing/changed/unresolved、`compile_ready` 和风险原因）。不改写 flat 副本中的 include 文本；扫描无法证明安全、目标变化或需要 CLI-only context 时 `compile_ready=false`，仍交付产物。`compile_ready=true` 仅说明扫描未发现迁移风险，不表示真实工程已编译。canonical gate 层级和三份旧 filelist 保持。

schema 2 顶层 `mapping.json.flattened_delivery` 记录 flat list、日志及按显式 source 顺序的字节摘要；restore 校验 manifest 形状、摘要、flat/canonical 字节一致、普通物理文件和精确集合，任意篡改拒绝 `RESTORE_VNEXT_GATE_INVALID`。此 manifest 只能与 T150 `delivery_filelists` 一起出现。非 filelist 模式不产生 flat artifacts，FAST 语义路径不变。无需新增 CLI 选项或重写 include 文本。

## 冻结输入、基线与白名单

Main Agent 从 main 已验收 T149 黑盒复制 `tests/test_t151_fast_flattened_delivery.py`，并在正例及本地 include 用例增加 `--rewrite-root`，直接覆盖 FAST 路径。冻结测试不得由子 Agent 修改。覆盖 `.v`/`-v`、nested 展开及顺序、实际 flat gate Formal、byte restore、include 风险日志、三种篡改拒绝、basename collision 原子失败。T150 和 T137 回归保持通过。

允许修改：新增 `rtl_obfuscator/flattened_delivery.py`，`rtl_obfuscator/rewrite.py`、`rtl_obfuscator/restore_vnext.py`、必要时 `rtl_obfuscator/source_set.py`（仅瞬态条目，不改 schema）、`README.md`、`docs/development/project_structure.md`、`docs/formal_verification.md`、本任务单。不得改冻结测试、既有测试、RTL fixtures、Mapping 核心或 Formal 脚本。若 FAST 的 SourceSet/API 与 main helper 不兼容，先写任务偏差并通知 Main Agent，不自行扩大范围。

## 五条门禁

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_t151_fast_flattened_delivery -v
conda run -n rtl_obfuscation python -m unittest tests.test_t150_fast_export_original_paths tests.test_t137_filelist_path_only_views tests.test_restore_vnext -v
conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/flattened_delivery.py rtl_obfuscator/source_set.py rtl_obfuscator/rewrite.py rtl_obfuscator/restore_vnext.py tests/test_t151_fast_flattened_delivery.py
git diff --check HEAD
conda run -n rtl_obfuscation python -c 'from pathlib import Path; p=Path("docs/tasks/T151_fast_flattened_filelist_delivery.md"); s=next(x for x in p.read_text().splitlines() if x.startswith("- 状态：")); assert s=="- 状态：`READY_FOR_REVIEW`", s; print("t151_ready_for_review=pass")'
```

第一门的 Formal 必须是原始 RTL 对实际 FAST renamed flat gate，exit 0、`formal_equivalence=pass`；第二门包含 T137 固定 XOR→OR 功能负例。不运行 RISC-V-Vector Formal、blanket discovery。Main Agent 独立重跑五门。子 Agent 开始前阅读 `AGENTS.md`、本合同、`docs/tasks/README.md`、`docs/development/process/refactor_subagent_protocol.md`、`docs/formal_verification.md`；先设 `IN_PROGRESS` 并记录 baseline，完成后记录变更文件、精确命令/结果、Formal gold/gate/top/JSON、边界，设 `READY_FOR_REVIEW` 并跑状态守卫。子 Agent 不 commit/push。

## 执行记录

- status: `READY_FOR_REVIEW`
- starting_head: `ef916f2217fafd9d57d49d56adaae5afa31e0780` (`delivery/fast-local-signals`, origin matches; only Main-created T151 contract and frozen test were untracked)
- start: `2026-09-24 12:54 Asia/Shanghai`; required docs and frozen test read before implementation edits
- allowed_files: `rtl_obfuscator/flattened_delivery.py`, `rtl_obfuscator/rewrite.py`, `rtl_obfuscator/restore_vnext.py`, `rtl_obfuscator/source_set.py` only for transient entries, `README.md`, `docs/development/project_structure.md`, `docs/formal_verification.md`, this task file
- baseline command: `conda run -n rtl_obfuscation python -m unittest tests.test_t151_fast_flattened_delivery -v`
- baseline result: exit 1; 4 test methods, 1 failure and 5 subtest errors. All flat artifacts were absent (the publication tests could not read `src_flattened`, `design_flattened.f`, or `src_flattened_log`); basename-collision input was incorrectly published with exit 0.
- changed_files: `rtl_obfuscator/flattened_delivery.py` (new), `rtl_obfuscator/rewrite.py`, `rtl_obfuscator/restore_vnext.py`, `README.md`, `docs/development/project_structure.md`, `docs/formal_verification.md`, this task file. `rtl_obfuscator/source_set.py` and frozen tests unchanged.
- schema_or_behavior: ported the accepted T149 bounded helper into the FAST branch. It uses transient `SourceSet.filelist_entries`, copies canonical encrypted bytes in `ordered_source_files` order, emits the flattened filelist and include-risk log, and writes `flattened_delivery` into mapping schema 2 only for public filelists. Rewrite translates helper I/O failures to `CLI_VNEXT_IO_ERROR`; basename/artifact conflicts fail in private staging before publication. Restore requires T150 `delivery_filelists`, verifies manifest hashes, source order, canonical/flat byte identity, regular physical files and exact flat inventory; orphan artifacts fail closed. FAST selection and non-filelist paths are unchanged.
- gate 1 command: `conda run -n rtl_obfuscation python -m unittest tests.test_t151_fast_flattened_delivery -v` -> exit 0; 4 tests passed.
- actual FAST flat-gate Formal from gate 1: encryption used `--filelist <project>/input.f --top t149_top --rewrite-root <project>/rtl --category signals`; Formal gold root `/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t149-flat-481deb5w/project`, gold filelist `/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t149-flat-481deb5w/gold.f`, gate `/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t149-flat-481deb5w/gate`, gate filelist `design_flattened.f`, `OUT=/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t149-flat-481deb5w/gate`, `OUT_FLAT=/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t149-flat-481deb5w/gate/src_flattened`, top `t149_top`, seq `5`. Exact command: `/Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python /Users/lufengchi/Desktop/workspace/rtl_obfuscation/scripts/formal_equivalence.py --gold-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t149-flat-481deb5w/gold.f --gold-root /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t149-flat-481deb5w/project --gate-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t149-flat-481deb5w/gate/design_flattened.f --gate-root /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t149-flat-481deb5w/gate --top t149_top --seq 5`; exit 0; JSON `{"formal_equivalence":"pass","gate":"/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t149-flat-481deb5w/gate","gold":"/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t149-flat-481deb5w/project","seq":5,"top":"t149_top"}`.
- include evidence: safe case JSON log had `compile_ready=true`; `rtl/helper.sv:1` included `defs.svh`, with `original_target=include/defs.svh`, `flattened_target=include/defs.svh`, status `same`. Local include case kept the copied RTL unchanged and logged `compile_ready=false`; `rtl/unsafe.sv:1` included `local.svh`, original target `rtl/local.svh`, flat target `null`, status `missing`.
- tamper/collision evidence: decrypt rejects edits to `src_flattened/top.sv`, `design_flattened.f`, and `src_flattened_log` with `RESTORE_VNEXT_GATE_INVALID` messages `flattened source content differs`, `flattened design digest differs`, and `flattened log digest differs`, respectively. Two physical sources named `same.sv` fail with `CLI_VNEXT_ORCHESTRATION_INVALID: flattened delivery failed: flattened basename collision: same.sv`; the requested gate path remains absent.
- gate 2 command: `conda run -n rtl_obfuscation python -m unittest tests.test_t150_fast_export_original_paths tests.test_t137_filelist_path_only_views tests.test_restore_vnext -v` -> exit 0; 14 tests passed, including T150 relocated Formal and T137 actual/relocated Formal with the fixed XOR-to-OR negative.
- gate 3 command: `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/flattened_delivery.py rtl_obfuscator/source_set.py rtl_obfuscator/rewrite.py rtl_obfuscator/restore_vnext.py tests/test_t151_fast_flattened_delivery.py` -> exit 0.
- gate 4 command: `git diff --check HEAD` -> exit 0, empty output.
- formal_verification: PASS; actual FAST flat gate evidence recorded above.
- boundaries: include detection is a conservative static scan, not preprocessing or proof that a full external project compiles. Dynamic, unresolved, missing, changed, or CLI-context-dependent includes keep `compile_ready=false`; differing CLI-only effective defines are conservatively recorded as external context. A true log still requires the actual downstream compile/Formal result. The schema-2 report is unsigned; coordinated changes to the report and all matching artifacts are outside the authenticity guarantee. No `-f` comments/whitespace are carried into the new flat view by contract.
- cleanup_candidates: none.
- review_request: self-gates are complete; after final `git diff --check HEAD` and READY status guard, Main Agent can independently rerun the five contract gates. No commit or push by this sub-agent.

Main Agent 验收记录：2026-09-24 独立重跑五条门禁，依次 exit 0。T151 4/4，原始 RTL 对实际 FAST renamed flat gate 的 Formal `pass`（top `t149_top`，seq 5）；T150/T137/restore 14/14，包含 T137 固定功能负例；`py_compile`、`git diff --check HEAD` 和精确 `READY_FOR_REVIEW` 守卫均通过。展平 helper 与 main 已验收 T149 版本 SHA256 相同，审查白名单中的发布、manifest 和恢复审计改动，接受本任务。
