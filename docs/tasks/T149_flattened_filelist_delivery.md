# T149：显式 filelist 的展平源码交付与 include 检测

- 状态：`ACCEPTED`
- Main Agent：冻结输入输出、黑盒测试、独立验收、提交和推送
- 实现：Luna extra high 子 Agent；只改白名单，停在 `READY_FOR_REVIEW`
- 起点：`8707aefbd33e48f909950fdeb521ac71588bcf05`，`main` 与 `origin/main` 一致，工作区在本任务单/冻结测试创建前干净
- 前置：T148 已 `ACCEPTED`、提交并推送；本任务是唯一活动任务
- 验收类型：adapter 迁移；actual renamed gate flattened Formal、byte restore 和 T139 固定功能负例

## 单一目标与输出合同

仅对公开显式 `--filelist` 模式，在现有 gate 输出目录内增加：

1. `src_flattened/`：按输入 filelist 的有效递归 `-f` 顺序，对每个显式 `.sv/.v` source unit（含 `-v`）从已加密 canonical gate 复制一个同名字节副本。已确认目标工程无 basename 重名，但实现仍须在重名时带 `flattened basename collision` 诊断并原子拒绝发布。include-only 物理依赖不当作显式 source unit。副本不得是 symlink，canonical gate 的原目录层级保持不变。
2. `design_flattened.f`：将 reachable `-f` 的有效条目就地展开，显式 source path 均写为 `$OUT_FLAT/<basename>`；原 `-v` 仍写 `-v $OUT_FLAT/<basename>`。显式 `.svh/.vh/.h/.vic` context entry 写 `$OUT/<source-root-relative-path>`，`+incdir+` 写 `$OUT/<source-root-relative-path>`，`+define+` 保留生效值和相对顺序。所有显式 source/context/directive 的有效顺序保持与现有 SourceSet filelist 解析顺序一致；flat 列表中不再出现 `-f`。`OUT` 指 gate，`OUT_FLAT` 指 `gate/src_flattened`。CLI-only context 不静默注入；需要时记录为外部编译上下文，并允许下游补充。无需复制注释与空白到这个新视图。原三份 filelist 的内容不变。
3. `src_flattened_log`：UTF-8 JSON，`format="rtl-obfuscation.src-flattened-log"`，`schema_version=1`，`compile_ready` 布尔，`includes` 数组。对每个 flat source 的 include 扫描，至少记录 source 相对路径、1-based line、include token、原层级目标、flat 目标和 `same/missing/changed/unresolved` 状态；不改写 flat 副本中的 `` `include``。找不到目标、目标变化、动态或无法证明的 include，以及仅来自 CLI 的必要编译上下文，必须令 `compile_ready=false` 并在日志中说明。`compile_ready=true` 仅表示没有检测到 include/context 迁移风险，不能声称对所有真实工程执行过 HDL 编译；本任务的 compact 正例须实际通过 Formal 编译。
4. 在 schema 2 `mapping.json` 顶层仅对本模式增加 `flattened_delivery`：`design_sha256`、`log_sha256` 和按显式 source 顺序排列的 `sources`，每项含 `source`（canonical gate 相对路径）、`flat`（`src_flattened/<basename>`）、`sha256`。Restore 核验清单形状、摘要、flat 副本与 canonical gate 字节相同、普通物理文件、缺失/额外项和 symlink；现有 T148 原文清单及非 filelist 模式报告行为保持。篡改任一 flat 文件、flat filelist 或日志必须 `RESTORE_VNEXT_GATE_INVALID`。不改 mapping payload、SourceSet schema、RTL 改名结果和 restored RTL 字节。

本任务不修改 include 文本，不新增严格 legacy Verilog 前端，不处理 FAST 分支，不增加新的 CLI 选项。明确记录本轮 include 检测无法证明的情况，不把日志中的 `compile_ready=false` 作为加密失败；flat artifacts 与日志仍原子发布。

## 冻结输入与 baseline

Main Agent 新增并冻结 `tests/test_t149_flattened_delivery.py`，子 Agent 不得修改。测试覆盖 `.v` 的 `-v`、nested `-f` 展开、define/incdir 顺序、加密后副本、flat actual-gate Formal、原字节恢复、同层级本地 include 的 `compile_ready=false`、三种 flat 篡改拒绝及 basename collision 原子失败。

起始命令：

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_t149_flattened_delivery -v
```

Main Agent baseline：exit `1`；4 tests 中 collision 预期失败却成功、其余因 `src_flattened` / `design_flattened.f` / `src_flattened_log` 尚不存在而报缺失；safe 和 local-include 两个现有加密入口均成功。子 Agent 先记录 baseline，再实现。

## 允许修改的文件

- `rtl_obfuscator/flattened_delivery.py`（新增）：只实现有效条目到 flat 视图、include 检测与 JSON 日志的有界构建 helper；可写入尚未发布的 private gate staging 目录。
- `rtl_obfuscator/rewrite.py`：公开 filelist 的 staging 发布、basename guard、flat manifest。
- `rtl_obfuscator/restore_vnext.py`：新产物和清单的 fail-closed 审计。
- `rtl_obfuscator/source_set.py`：仅在现有 `FilelistEntry` 信息不足以保持有效条目顺序时补充瞬态信息；不改 SourceSet report schema。
- `README.md`、`docs/development/project_structure.md`、`docs/formal_verification.md`：同步用户和验证行为。
- 本任务单：执行记录、偏差、状态。

冻结测试、既有测试、RTL fixtures、Mapping/Rewrite 核心、SourceCatalog 和 Formal 脚本不可改。若合同与真实 parser/编译行为冲突，先记录证据并通知 Main Agent，不自行改 oracle 或扩大范围。

## 五条验收门禁

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_t149_flattened_delivery -v

conda run -n rtl_obfuscation python -m unittest tests.test_t148_export_original_paths tests.test_t139_filelist_delivery tests.test_restore_vnext -v

conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/flattened_delivery.py rtl_obfuscator/source_set.py rtl_obfuscator/rewrite.py rtl_obfuscator/restore_vnext.py tests/test_t149_flattened_delivery.py

git diff --check HEAD

conda run -n rtl_obfuscation python -c 'from pathlib import Path; p=Path("docs/tasks/T149_flattened_filelist_delivery.md"); s=next(x for x in p.read_text().splitlines() if x.startswith("- 状态：")); assert s=="- 状态：`READY_FOR_REVIEW`", s; print("t149_ready_for_review=pass")'
```

第一条的 `T149_FORMAL` 必须是原始 RTL 对 actual renamed flat gate 的 `scripts/formal_equivalence.py` exit 0 / `formal_equivalence=pass`；第二条复用 T139 XOR→OR 固定功能负例，保持 `negative_exit=1`、`unproven=true`、`equiv_status_assert=true`。禁止 blanket discovery、RISC-V-Vector Formal。Main Agent 独立重跑五门禁；失败不得接受或提交。

## 执行与审查

子 Agent 先完整阅读 `AGENTS.md`、本合同、`docs/tasks/README.md`、`docs/development/process/refactor_subagent_protocol.md` 和 `docs/formal_verification.md`；确认 HEAD/status 后先将本任务 `READY` 改 `IN_PROGRESS`，记录开始项和 baseline。遇到边界变化先写入本任务并通知 Main Agent。完成后记录 changed files、五门禁精确命令/退出码/关键输出、actual gate Formal gold/gate/top/exit/JSON、未覆盖边界和 cleanup 候选，再设置 `READY_FOR_REVIEW` 并运行精确状态守卫。子 Agent 不设 `ACCEPTED`、不 commit、不 push。

Main Agent 验收记录：2026-09-24 独立重跑五条门禁，依次 exit 0。T149 4/4，actual renamed flat gate 对原始 RTL 的 Formal 为 `pass`（top `t149_top`，seq 5）；T148/T139/restore 23/23，固定功能负例 exit 1、`unproven=true`、`equiv_status_assert=true`；`py_compile`、`git diff --check HEAD` 和精确 `READY_FOR_REVIEW` 守卫通过。审查白名单改动及 stage 产物、日志、restore 摘要与物理文件核验，接受本任务。

## 执行记录

- status: `READY_FOR_REVIEW`
- starting_head: `8707aefbd33e48f909950fdeb521ac71588bcf05` (`main`, clean before frozen contract/test creation)
- start: `2026-09-24 12:22 Asia/Shanghai`; first command `conda run -n rtl_obfuscation python -m unittest tests.test_t149_flattened_delivery -v`
- allowed_files: `rtl_obfuscator/flattened_delivery.py` (new), `rtl_obfuscator/rewrite.py`, `rtl_obfuscator/restore_vnext.py`, optionally `rtl_obfuscator/source_set.py`, `README.md`, `docs/development/project_structure.md`, `docs/formal_verification.md`, this task file
- baseline command: `conda run -n rtl_obfuscation python -m unittest tests.test_t149_flattened_delivery -v`
- baseline result: exit 1; 4 tests run, 1 failure (basename collision encrypt unexpectedly exits 0), 5 errors (three tamper paths and positive/local-include outputs missing). Existing safe and local-include encrypt calls themselves succeeded; actual-gate Formal was not reached.
- changed_files: `rtl_obfuscator/flattened_delivery.py` (new), `rtl_obfuscator/rewrite.py`, `rtl_obfuscator/restore_vnext.py`, `README.md`, `docs/development/project_structure.md`, `docs/formal_verification.md`, this task file. `rtl_obfuscator/source_set.py` and frozen tests were not edited.
- commands/results:
  1. `conda run -n rtl_obfuscation python -m unittest tests.test_t149_flattened_delivery -v` — exit 0; 4 tests passed. Positive log: `compile_ready=true`; `rtl/helper.sv:1` include `defs.svh` resolved `include/defs.svh` → `include/defs.svh`, `same`. Local-only include: `compile_ready=false`; `rtl/unsafe.sv:1` include `local.svh` original `rtl/local.svh` → flat target `null`, `missing`.
  2. `conda run -n rtl_obfuscation python -m unittest tests.test_t148_export_original_paths tests.test_t139_filelist_delivery tests.test_restore_vnext -v` — exit 0; 23 tests passed. T139 negative JSON: `negative_exit=1`, `unproven=true`, `equiv_status_assert=true`; positive design/export Formal both pass.
  3. `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/flattened_delivery.py rtl_obfuscator/source_set.py rtl_obfuscator/rewrite.py rtl_obfuscator/restore_vnext.py tests/test_t149_flattened_delivery.py` — exit 0, no output.
  4. `git diff --check HEAD` — exit 0, empty output.
  5. `conda run -n rtl_obfuscation python -c 'from pathlib import Path; p=Path("docs/tasks/T149_flattened_filelist_delivery.md"); s=next(x for x in p.read_text().splitlines() if x.startswith("- 状态：")); assert s=="- 状态：`READY_FOR_REVIEW`", s; print("t149_ready_for_review=pass")'` — exit 0; printed `t149_ready_for_review=pass`.
- flattened tamper evidence: decrypt rejects `src_flattened/top.sv` with `flattened source content differs`, `design_flattened.f` with `flattened design digest differs`, and `src_flattened_log` with `flattened log digest differs`; each returns `RESTORE_VNEXT_GATE_INVALID`. Basename collision reports `flattened basename collision` and leaves the requested gate path absent. Restore also rejects an orphan flat artifact set when the top-level flattened manifest is absent, and requires `delivery_filelists` whenever `flattened_delivery` is present.
- schema_or_behavior: `SourceSet.filelist_entries` drives recursive effective order; flat sources follow `SourceSet.ordered_source_files`, preserve canonical gate paths, and copy their bytes. The new top-level schema-2 manifest records design/log hashes and ordered source hashes. Restore checks shape, digest, exact flat inventory, regular files and byte identity. CLI-only include dirs are external only when an original include resolves through them; differing effective CLI-only defines are conservatively external without text-use inference, covering conditional directives.
- formal_verification: PASS. Gold project `/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t149-flat-ure4r7nt/project`; gold filelist `/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t149-flat-ure4r7nt/gold.f`; gate `/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t149-flat-ure4r7nt/gate/design_flattened.f`; `OUT=/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t149-flat-ure4r7nt/gate`, `OUT_FLAT=/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t149-flat-ure4r7nt/gate/src_flattened`; top `t149_top`; exact inner command `/Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python /Users/lufengchi/Desktop/workspace/rtl_obfuscation/scripts/formal_equivalence.py --gold-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t149-flat-ure4r7nt/gold.f --gold-root /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t149-flat-ure4r7nt/project --gate-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t149-flat-ure4r7nt/gate/design_flattened.f --gate-root /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t149-flat-ure4r7nt/gate --top t149_top --seq 5`; exit 0; JSON `{"formal_equivalence":"pass","gate":"/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t149-flat-ure4r7nt/gate","gold":"/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t149-flat-ure4r7nt/project","seq":5,"top":"t149_top"}`.
- boundaries: the include scanner is a conservative static scan, not an HDL preprocessor or a claim of compile success; dynamic, unresolved, changed or unavailable targets keep `compile_ready=false`. Differing CLI-only effective defines also stay external conservatively. The schema-2 report is not signed, so jointly changing the report and all corresponding flat artifacts is outside the authenticity guarantee; an incomplete evidence set fails closed.
- cleanup_candidates: none.
- review_request: implementation and all five self-gates are complete. Main Agent may independently rerun the required gates and review the changed files.
