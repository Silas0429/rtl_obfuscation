# T150：FAST 分支保留原始路径 token 的 export filelist

- 状态：`ACCEPTED`
- Main Agent：冻结合同和测试、独立验收、提交推送
- 实现：Luna extra high 子 Agent；停在 `READY_FOR_REVIEW`
- 起点：`e8b6b3a`，`delivery/fast-local-signals` 与 origin 一致；创建本合同和冻结测试前工作区干净
- 前置：此分支 T137 已验收；本任务是唯一活动任务

## 单一目标与输出合同

把 main 已验收的 T148 原始 token 路径规则有界移植到 FAST 分支的公开显式 `--filelist`。`design.f` 和 nested design 子清单仍按原条目行序、注释、换行和非路径字节生成 gate 绝对路径；`export_design.f` 和 nested export 子清单中，原始路径 token 含环境变量时原样保留，原始绝对路径 `/x/y` 改为 `$OUT/x/y`，相对路径保持当前 `$OUT/...` 投影规则。`-f`、`-v`、`+incdir+` 路径遵循相同规则。原始顶层清单字节写 `original_design.f`，原始 nested 字节写 `.rtl_obfuscation/filelists/original/...`，并在 schema 2 `mapping.json.delivery_filelists` 记录有序 SHA256。canonical gate 源码继续按原目录层级保存；环境变量路径所需副本与绝对路径 mirror 确保 export 在交付环境可重放。Restore 对三视图、原文快照、alias、物理集合进行 fail-closed 审计。非 filelist 模式与 FAST 语义路径不变。

## 冻结输入、基线与白名单

Main Agent 从 main 已验收 T148 黑盒复制 `tests/test_t150_fast_export_original_paths.py`（子 Agent 不得修改），覆盖原字节/顺序、两类 token、nested 环境变量、`-v`、include-dir、实际 relocated export gate Formal、byte restore、mirror/token/snapshot 篡改拒绝。移植不引入 main 的其它改名功能，不合并 main。`tests.test_t137_filelist_path_only_views` 的 `--rewrite-root` 真实 FAST 路径也须保持通过。

允许修改：`rtl_obfuscator/source_set.py`、`rtl_obfuscator/rewrite.py`、`rtl_obfuscator/restore_vnext.py`、`README.md`、`docs/development/project_structure.md`、`docs/formal_verification.md`、本任务单。不得改冻结测试、T137 历史任务/测试、RTL fixture、Mapping 核心或 Formal 脚本。若 parser/API 差异阻碍，先写本任务偏差并通知 Main Agent。

## 五条门禁

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_t150_fast_export_original_paths -v
conda run -n rtl_obfuscation python -m unittest tests.test_t137_filelist_path_only_views tests.test_restore_vnext -v
conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/source_set.py rtl_obfuscator/rewrite.py rtl_obfuscator/restore_vnext.py tests/test_t150_fast_export_original_paths.py
git diff --check HEAD
conda run -n rtl_obfuscation python -c 'from pathlib import Path; p=Path("docs/tasks/T150_fast_export_original_paths.md"); s=next(x for x in p.read_text().splitlines() if x.startswith("- 状态：")); assert s=="- 状态：`READY_FOR_REVIEW`", s; print("t150_ready_for_review=pass")'
```

第一门实际 Formal 必须是 gold 原始 RTL 对 relocated actual renamed gate，exit 0 和 `formal_equivalence=pass`。第二门 T137 的正例及固定 XOR→OR 功能负例必须继续通过；不得运行 RISC-V-Vector Formal 或 blanket discovery。Main Agent 独立重跑五门。子 Agent 开始前阅读 `AGENTS.md`、本合同、`docs/tasks/README.md`、`docs/development/process/refactor_subagent_protocol.md` 和 `docs/formal_verification.md`，先将状态改 `IN_PROGRESS`，记录 baseline，再实现；结束记录修改文件、精确命令、Formal gold/gate/top/JSON、未覆盖边界，改 `READY_FOR_REVIEW` 并跑状态守卫。子 Agent 不 commit/push。

## 执行记录

- status: `READY_FOR_REVIEW`
- starting_head: `e8b6b3a9ffce99a2b528551f9212b8122a95c1a4` (`delivery/fast-local-signals`, only Main-created task contract and frozen test were untracked)
- start: `2026-09-24 12:41 Asia/Shanghai`; first command `conda run -n rtl_obfuscation python -m unittest tests.test_t150_fast_export_original_paths -v`
- allowed_files: `rtl_obfuscator/source_set.py`, `rtl_obfuscator/rewrite.py`, `rtl_obfuscator/restore_vnext.py`, `README.md`, `docs/development/project_structure.md`, `docs/formal_verification.md`, this task file
- baseline command: `conda run -n rtl_obfuscation python -m unittest tests.test_t150_fast_export_original_paths -v`
- baseline result: exit 1; 5 tests run, 1 failure (`export_design.f` rewrites original env `-f` token and collapses the expected entries) and 3 errors (absolute mirror, original nested snapshot, and env-token tamper paths are absent). Relocated export Formal already passes (`formal_equivalence=pass`, top `t148_top`).
- implementation: `source_set.py` now retains the original path-token rules, original reachable nested bytes, and alias metadata; `rewrite.py` writes the ordered original-filelist digest manifest and nested snapshots, then materializes the physical file/directory aliases required by `export_design.f`; `restore_vnext.py` verifies original snapshots, token transformations, byte-identical aliases, nested closure, and gate physical membership. Public docs describe the filelist export behavior. FAST source selection and non-filelist paths were not changed.
- changed files: `rtl_obfuscator/source_set.py`, `rtl_obfuscator/rewrite.py`, `rtl_obfuscator/restore_vnext.py`, `README.md`, `docs/development/project_structure.md`, `docs/formal_verification.md`, this task file. Frozen test unchanged.
- gate 1 command: `conda run -n rtl_obfuscation python -m unittest tests.test_t150_fast_export_original_paths -v` -> exit 0; 5 tests passed.
- actual Formal executed by gate 1: `/Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python /Users/lufengchi/Desktop/workspace/rtl_obfuscation/scripts/formal_equivalence.py --gold-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t148-export-paths-k7dpg9be/gold_formal.f --gold-root /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t148-export-paths-k7dpg9be/project --gate-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t148-export-paths-k7dpg9be/relocated/export_design.f --gate-root /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t148-export-paths-k7dpg9be/relocated --top t148_top --seq 5`; environment set `OUT` and `COMM_HDL_PATH` to the relocated gate. Gold root: `/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t148-export-paths-k7dpg9be/project`; gate: `/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t148-export-paths-k7dpg9be/relocated`; top: `t148_top`; exit 0; JSON: `{"formal_equivalence":"pass","gate":"/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t148-export-paths-k7dpg9be/relocated","gold":"/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t148-export-paths-k7dpg9be/project","seq":5,"top":"t148_top"}`.
- tamper diagnostics asserted by the frozen tests: absolute mirror byte edit -> `RESTORE_VNEXT_GATE_INVALID: delivery alias content differs`; simultaneous edit of exported nested filelist and its environment-path alias -> `RESTORE_VNEXT_GATE_INVALID: export path token differs from original token rule`; original nested snapshot byte edit -> `RESTORE_VNEXT_GATE_INVALID: original filelist snapshot digest differs`.
- gate 2 command: `conda run -n rtl_obfuscation python -m unittest tests.test_t137_filelist_path_only_views tests.test_restore_vnext -v` -> exit 0; 9 tests passed, including T137 actual/relocated Formal and its XOR-to-OR functional negative.
- gate 3 command: `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/source_set.py rtl_obfuscator/rewrite.py rtl_obfuscator/restore_vnext.py tests/test_t150_fast_export_original_paths.py` -> exit 0.
- gate 4 command: `git diff --check HEAD` -> exit 0.
- boundaries: exported tokens containing environment variables require those variables to be rebound at the delivery location; gate 1 verifies this for the relocated compile. Old schema-2 reports without `delivery_filelists` retain the existing compatibility path; a snapshot tree without a manifest fails closed. Reports are not signed, so coordinated edits to `mapping.json` and all matching delivery evidence are outside the authenticity guarantee.

Main Agent 验收记录：2026-09-24 独立重跑五条门禁，依次 exit 0。T150 5/5，原始 RTL 对 relocated actual renamed gate 的 Formal `pass`（top `t148_top`，seq 5）；T137/restore 9/9，包含 T137 固定功能负例；`py_compile`、`git diff --check HEAD` 和精确 `READY_FOR_REVIEW` 守卫均通过。白名单改动只涉及 filelist 交付和恢复审计，接受本任务。
