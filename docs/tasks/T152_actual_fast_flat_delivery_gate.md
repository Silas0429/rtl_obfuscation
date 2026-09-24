# T152：实际 FAST 路径的展平交付验收与证据更正

- 状态：`ACCEPTED`
- Main Agent：冻结黑盒、独立验收、提交推送
- 实现与验证：Luna extra high 子 Agent；停在 `READY_FOR_REVIEW`
- 起点：`e13c181`，`delivery/fast-local-signals` 与 origin 一致；创建本合同和冻结测试前工作区干净
- 前置：T151 已 `ACCEPTED`、提交并推送；本任务是唯一活动任务

## 单一目标与纠正

T151 测试在加密 CLI 同时传 `--top`、`--rewrite-root`、`--category signals`。当前分支的 FAST dispatch 明确要求 `SourceSet.top is None`，所以 T151 已证实的是 FAST **分支**上的通用路径交付及 flat Formal，而不是快速执行路径。不得把此前证明追认为 FAST 路径证明。本任务用真实公开 CLI 的无 `--top`、显式 filelist、rewrite-root、恰好 `signals`、无 rate 输入建立单独黑盒：检查 flat 副本与 canonical encrypted gate 字节一致、有效顺序、日志、原字节 restore，以及原始 RTL 对实际 flat renamed gate 的 Formal `pass`。复用 T130 固定 fixture 和 route/stage 断言，确认快速 dispatch 的既有证明未退化。若黑盒已通过，产品代码无需改动；若失败，在本任务白名单内做最小修复。另在 T151 已验收任务的执行记录末尾追加勘误，保留原记录与状态，注明 T151 证据覆盖的是分支而非快速 dispatch，并引用本任务的实际证据。

Main Agent 冻结 `tests/test_t152_actual_fast_flat_delivery.py`，子 Agent 不得修改。允许修改：`rtl_obfuscator/flattened_delivery.py`、`rtl_obfuscator/rewrite.py`、`rtl_obfuscator/restore_vnext.py`（仅黑盒失败时最小修复），`docs/tasks/T151_fast_flattened_filelist_delivery.md`（仅追加勘误）、本任务单。不得改冻结测试、T130/T151 测试、FAST mapping/CST、历史 T130 合同或 fixture。

## 五条门禁

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_t152_actual_fast_flat_delivery -v
conda run -n rtl_obfuscation python -m unittest tests.test_t130_fast_local_signals tests.test_t151_fast_flattened_delivery -v
conda run -n rtl_obfuscation python -m py_compile tests/test_t152_actual_fast_flat_delivery.py rtl_obfuscator/flattened_delivery.py rtl_obfuscator/rewrite.py rtl_obfuscator/restore_vnext.py
git diff --check HEAD
conda run -n rtl_obfuscation python -c 'from pathlib import Path; p=Path("docs/tasks/T152_actual_fast_flat_delivery_gate.md"); s=next(x for x in p.read_text().splitlines() if x.startswith("- 状态：")); assert s=="- 状态：`READY_FOR_REVIEW`", s; print("t152_ready_for_review=pass")'
```

第一门须记录实际 gold/gate/top/exit/JSON，且 `formal_equivalence=pass`。第二门 T130 必须继续包含快速路由防退化阶段断言和固定功能负例。不得运行 RISC-V-Vector Formal 或 blanket discovery。Main Agent 独立重跑五门。子 Agent 开始前阅读 `AGENTS.md`、本合同、`docs/tasks/README.md`、`docs/development/process/refactor_subagent_protocol.md`、`docs/formal_verification.md`；先设 `IN_PROGRESS` 并记录 baseline；结束写入 changed files、命令与输出、Formal 证据和未覆盖边界，设 `READY_FOR_REVIEW` 并跑精确守卫，不 commit/push。

## 执行记录

- status: `READY_FOR_REVIEW`
- starting_head: `e13c18153cbe4f7f15daf4cf563c8042c7bc14de` (`delivery/fast-local-signals`, origin matches; only Main-created T152 contract and frozen test were untracked)
- start: `2026-09-24 13:05 Asia/Shanghai`; required docs and frozen black-box read before implementation edits
- allowed_files: `rtl_obfuscator/flattened_delivery.py`, `rtl_obfuscator/rewrite.py`, `rtl_obfuscator/restore_vnext.py` only if black-box failure requires a minimal fix, T151 task execution record erratum only, this task file
- baseline command: `conda run -n rtl_obfuscation python -m unittest tests.test_t152_actual_fast_flat_delivery -v`
- baseline result: independent rerun exit 0; 1 test passed. `T152_FAST_FLAT_FORMAL` reported `formal_equivalence=pass`, gold `/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t152-fast-flat-m9k8se1e/project`, gate `/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t152-fast-flat-m9k8se1e/gate`, top `t130_top`, seq 5. Test confirms `source_set.top is None`; encryption command has no `--top`, includes `--rewrite-root`, and uses only `signals` without a rate, selecting the FAST dispatch.
- changed_files: `docs/tasks/T151_fast_flattened_filelist_delivery.md` (append-only T152 routing erratum), this task file. No product code or frozen test changed.
- schema_or_behavior: no implementation change required. T152 exercises the true FAST dispatch on public filelist input with no `--top`, `--rewrite-root`, only `signals`, and no rate. It verifies `source_set.top is None`, strict compile, flat manifest presence, source-order list contents, byte-identical canonical/flat copies, `compile_ready=true`, public restore bytes, and actual flat Formal. T151's accepted status and previous record remain intact; an erratum at its end clarifies that its `--top` case covered the generic path on the FAST branch.
- gate 1 command: `conda run -n rtl_obfuscation python -m unittest tests.test_t152_actual_fast_flat_delivery -v` -> exit 0; 1 test passed.
- actual FAST encryption command in the test: `/Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python /Users/lufengchi/Desktop/workspace/rtl_obfuscation/rtl_encrypt.py --filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t152-fast-flat-p6yo7f74/project/input.f --rewrite-root /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t152-fast-flat-p6yo7f74/project/owned --category signals --output-dir /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t152-fast-flat-p6yo7f74/gate` (no `--top`, no encryption rate); exit 0. Report `source_set.top=null`; `strict_compile_passed=true`; flat entries are `$OUT_FLAT/leaf_a.sv`, `$OUT_FLAT/leaf_b.sv`, `$OUT_FLAT/top.sv` in source order.
- actual FAST flat-gate Formal: gold root `/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t152-fast-flat-p6yo7f74/project`, gold filelist `/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t152-fast-flat-p6yo7f74/project/input.f`; gate root `/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t152-fast-flat-p6yo7f74/gate`, gate filelist `/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t152-fast-flat-p6yo7f74/gate/design_flattened.f`; `OUT` set to gate root, `OUT_FLAT` set to `/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t152-fast-flat-p6yo7f74/gate/src_flattened`; top `t130_top`; seq 5. Exact command: `/Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python /Users/lufengchi/Desktop/workspace/rtl_obfuscation/scripts/formal_equivalence.py --gold-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t152-fast-flat-p6yo7f74/project/input.f --gold-root /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t152-fast-flat-p6yo7f74/project --gate-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t152-fast-flat-p6yo7f74/gate/design_flattened.f --gate-root /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t152-fast-flat-p6yo7f74/gate --top t130_top --seq 5`; exit 0; JSON `{"formal_equivalence":"pass","gate":"/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t152-fast-flat-p6yo7f74/gate","gold":"/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t152-fast-flat-p6yo7f74/project","seq":5,"top":"t130_top"}`.
- gate 2 command: `conda run -n rtl_obfuscation python -m unittest tests.test_t130_fast_local_signals tests.test_t151_fast_flattened_delivery -v` -> exit 0; 13 tests passed. T130 fast route/stage guard passed (`test_fast_path_skips_slow_catalog_index_and_forbidden_stages`); fixed negative in `test_actual_gate_formal_positive_and_fixed_functional_negative` remained nonzero and asserted `unproven` plus `equiv_status -assert`. T151 remained 4/4.
- gate 3 command: `conda run -n rtl_obfuscation python -m py_compile tests/test_t152_actual_fast_flat_delivery.py rtl_obfuscator/flattened_delivery.py rtl_obfuscator/rewrite.py rtl_obfuscator/restore_vnext.py` -> exit 0, no output.
- gate 4 command: `git diff --check HEAD` -> exit 0, empty output.
- gate 5 command: `conda run -n rtl_obfuscation python -c 'from pathlib import Path; p=Path("docs/tasks/T152_actual_fast_flat_delivery_gate.md"); s=next(x for x in p.read_text().splitlines() if x.startswith("- 状态：")); assert s=="- 状态：`READY_FOR_REVIEW`", s; print("t152_ready_for_review=pass")'` -> exit 0; printed `t152_ready_for_review=pass`.
- formal_verification: PASS; actual no-top FAST flat gate evidence recorded above.
- boundaries: Formal fixture copies only T130's `owned` sources to avoid unrelated package/interface constructs unsupported by this Yosys flow. This demonstrates the fast dispatch and flat delivery for the compact owned fixture; broader T130 package/interface context is not claimed by this Formal. The T130 route/stage and functional-negative tests still pass unchanged.
- cleanup_candidates: none.
- review_request: no implementation changes were needed; Main Agent can independently rerun the five frozen gates. Sub-agent does not commit or push.

Main Agent 验收记录：2026-09-24 独立重跑五条门禁，依次 exit 0。T152 1/1，实际无 top FAST dispatch 的 flat gate 对原始 RTL Formal `pass`（top `t130_top`，seq 5）；T130/T151 13/13，包含 FAST 路由阶段防退化断言和固定功能负例；`py_compile`、`git diff --check HEAD`、精确 `READY_FOR_REVIEW` 守卫通过。核对 T151 勘误只追加证据说明，原验收状态与原文保留。此任务不需产品代码修复，接受测试与证据更正。
