# T142：FULL 名字完整性按剩余 token 补证

- 状态：`ACCEPTED`
- 起始分支 / HEAD：`main@1b9feb7c74dae4ca5fbc02f022183fe18769b6f7`
- 负责人：主 Agent（冻结 oracle、独立验收）/ 实现子 Agent（仅本任务）
- 前置：T140 / T141 ACCEPTED；用户授权优化 FULL 并保持规则扩展性。
- 计划：[`full_rename_index_performance_plan.md`](../development/full_rename_index_performance_plan.md)
- 验收类型：rewrite/mapping；compact actual-gate Formal 正例与固定功能负例。

## 单一目标

在 `_apply_name_completeness` 保留完整 tokens / unverified 分母、所有当前 eligible 的 rewritten_starts，
只对 records 尚未解释的 token 补充 declaration attribution，再只对剩余 token 补充 reference attribution。
最终 incomplete 仍从完整分母得出。不改变公共 schema、类别或准入规则。

先读 AGENTS.md、docs/tasks/README.md、refactor_subagent_protocol.md、docs/formal_verification.md、
docs/systemverilog_renaming_table.md，以及本计划。主 Agent 冻结测试 `tests/test_t142_pending_name_proofs.py`。

## 实现与扩展边界

- 每次从当前 records 计算 wanted / eligible / rewritten_starts，新增候选或 policy 改变不可命中旧结果。
- 不按当前四组或已知节点形状缩小证据；generic aggregate/declaration/reference provider 原样沿用。
- 不改 `_tokens_spelling`、`_declaration_attributions`、`_reference_spans`、`_reference_attributions`，
  不去重引用、不提前采纳候选、不中途更改 eligible 集合。
- by_start 先从完整 tokens 建立，再筛选，保留同 start 最后值语义。原索引依赖 end 单调；必要时
  对 end 不单调的 `(file,name)` bucket 保留完整查询 token，保证旧算法行为。允许一个私有辅助函数。
- 无 pending 时仍应用 unverified；原有 macro、dead-source、readonly、support/reason 优先级不变。
- 无新依赖、全局/跨 build 缓存、持久化或扩展框架。未来证明定义改变仍由 canonical provider 实现。

子 Agent 只允许修改：

```text
rtl_obfuscator/rename_index.py
docs/development/project_structure.md
docs/tasks/T142_pending_name_proofs.md
```

project_structure 只说明本次内部补证和扩展边界。测试和计划归主 Agent；不修改 fixtures、历史文档或
其他性能热点。可参考 `/tmp/full-explore-completeness-L2H4fV/prototype.py` 的 pending_only，但不能
把动态源码替换/monkeypatch 写入产品。发现范围问题先在合同记录并向主 Agent 报告。

## Baseline（唯一命令）

先记录 HEAD/status 并 READY→IN_PROGRESS，再执行：

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_t142_pending_name_proofs -v
```

预期旧实现仅在省略重复证明/缩小补证工作断言失败，其余正确性与 Formal 通过。若不是此类失败，
先报告主 Agent；不能改测试。

## 冻结验收（五条）

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_t142_pending_name_proofs -v

conda run -n rtl_obfuscation python -m unittest tests.test_t128_rename_index_range_cache tests.test_t129_ordered_semantic_workset tests.test_t141_semantic_name_reuse -v

conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/rename_index.py tests/test_t142_pending_name_proofs.py

git diff --check HEAD

conda run -n rtl_obfuscation python -c 'from pathlib import Path; s=next(l for l in Path("docs/tasks/T142_pending_name_proofs.md").read_text().splitlines() if l.startswith("- 状态：")); assert s=="- 状态：`READY_FOR_REVIEW`", s; print("t142_ready_for_review=pass")'
```

第一条内含真实改名 gate、确定性完整 Mapping、strict compile、byte restore、`proof_top` seq=5 正例
和实际 gate 的 XOR 常量单 bit 负例。须记录 T142_FORMAL_JSON 中实际 gold/gate/top/命令/退出码/JSON。
正例 exit 0/pass；负例非零且含 unproven / equiv_status -assert。不得运行 identity Formal、RISC 或
blanket discovery。主 Agent 独立重跑这五条，接受后再开下一任务。

## 子 Agent 执行记录

- started_at：2026-09-15 14:19:13 CST。
- starting_head：`main@1b9feb7c74dae4ca5fbc02f022183fe18769b6f7`。
- starting_status：仅主 Agent 预置的本合同、`tests/test_t142_pending_name_proofs.py`、
  `docs/development/full_rename_index_performance_plan.md` 三个 untracked 文件；实现文件无已有修改。
- frozen_test_sha256：`9d787068c1d644c416f5d1bac943784777df944260d6995f6b449248fa51f770`，已核对。
- allowed_files：`rtl_obfuscator/rename_index.py`、`docs/development/project_structure.md`、本合同。
- first_command（baseline）：`conda run -n rtl_obfuscation python -m unittest tests.test_t142_pending_name_proofs -v`。
- 已完整阅读项目指令、任务流程、子 Agent 协议、Formal 文档、加密类型表和本计划。无范围偏差。
- baseline：上述唯一命令 exit 1，8 tests，3 个工作量断言 subcase 失败（两个无 pending 仍扫描、
  一个 declaration wanted 未收窄）；全部正确性断言、跨名称 edited-target 准入变更回归和
  actual-gate Formal 正例 exit 0/pass、固定功能负例 exit 1/rejected 均通过，符合预期。
  日志：`/tmp/t142-subagent-baseline.stdout`、`/tmp/t142-subagent-baseline.stderr`。
- changed_files：仅三个允许文件。`rename_index.py` 新增一个私有查询 token 选择函数并按剩余 token
  协调补证；`project_structure.md` 记录完整分母、动态准入和通用证据入口；本合同记录执行证据。
- commands / results：
  1. `conda run -n rtl_obfuscation python -m unittest tests.test_t142_pending_name_proofs -v`：
     exit 0，8 tests OK，1.047s。覆盖 6 个实际 fixture × scoped/unscoped × signals/all 的完整
     决策对照、200 组同 start/非单调 end 对照、新候选及准入变化、通用聚合声明扩展、完整 Mapping、
     actual gate、strict compile、逐字节恢复及下述 Formal 正负例。
  2. `conda run -n rtl_obfuscation python -m unittest tests.test_t128_rename_index_range_cache tests.test_t129_ordered_semantic_workset tests.test_t141_semantic_name_reuse -v`：
     exit 0，21 tests OK，0.494s。
  3. `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/rename_index.py tests/test_t142_pending_name_proofs.py`：exit 0。
  4. `git diff --check HEAD`：exit 0，无输出。
  5. 本合同冻结的精确 `READY_FOR_REVIEW` 状态守卫：exit 0，`t142_ready_for_review=pass`。
- logs：`/tmp/t142-subagent-acceptance.stdout`、`/tmp/t142-subagent-acceptance.stderr`、
  `/tmp/t142-subagent-regressions.stdout`、`/tmp/t142-subagent-regressions.stderr`。
- schema_or_behavior：无公共 schema、加密类别或准入变更；canonical token/declaration/reference
  providers 未修改。完整 CST 与 unverified 保持，全部初始 eligible 的 rewritten_starts 保持；
  无全局或跨 build 缓存。冻结测试 SHA256 再核对一致。
- boundaries：服务器原工程性能复跑不在本小步验收内，留给主 Agent 最终测量；未来若改变证据含义
  或在完整性检查后重新开放候选，仍需重新执行证明。无其他已知未覆盖边界或偏差。
- cleanup_candidates：无。
- formal_verification：PASS。由第一条 Conda 环境测试通过 `sys.executable` 启动真实 Formal；临时
  gold/gate 在该 unittest 退出后自动清理，日志保留实际路径与 JSON。
  - gold：`/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t142-full-sbwkyzr_/source/design.sv`。
  - gate：`/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t142-full-sbwkyzr_/gate/design.sv`。
  - negative：`/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t142-full-sbwkyzr_/negative.sv`，
    仅把真实 gate 中唯一 `^ 4'b1010` 改为 `^ 4'b1011`。
  - top：`proof_top`；seq：5；gate 与 gold 字节不同，且与未优化 oracle 的确定性 gate 相同。
  - positive command：`/Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python /Users/lufengchi/Desktop/workspace/rtl_obfuscation/scripts/formal_equivalence.py --gold /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t142-full-sbwkyzr_/source/design.sv --gate /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t142-full-sbwkyzr_/gate/design.sv --top proof_top --seq 5`。
  - positive exit_code：0；JSON：`{"formal_equivalence":"pass","gate":"/private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t142-full-sbwkyzr_/gate/design.sv","gold":"/private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t142-full-sbwkyzr_/source/design.sv","seq":5,"top":"proof_top"}`。
  - negative command：`/Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python /Users/lufengchi/Desktop/workspace/rtl_obfuscation/scripts/formal_equivalence.py --gold /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t142-full-sbwkyzr_/source/design.sv --gate /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t142-full-sbwkyzr_/negative.sv --top proof_top --seq 5`。
  - negative exit_code：1；测试确认输出含 `unproven` 和 `equiv_status -assert`；证据 JSON：
    `{"fixed_functional_negative":"rejected"}`。
- review_request：请主 Agent 独立复跑冻结五条；子 Agent 不设置 ACCEPTED，不 commit/push，不创建下一任务。

## 主 Agent 验收

2026-09-15 主 Agent 在正式 READY_FOR_REVIEW 后独立重跑全部五条冻结命令：

- 状态守卫 exit 0，`t142_ready_for_review=pass`；冻结测试 SHA256
  `9d787068c1d644c416f5d1bac943784777df944260d6995f6b449248fa51f770` 未变。
- 目标测试 exit 0，8 tests / 1.049s；新候选、准入切换、跨名称 edited-target、generic provider、
  24 组真实 fixture/category 对照、200 组特殊区间对照通过。
- 回归 exit 0，21 tests / 0.519s；T108/T115 决策摘要和 T141 Mapping 摘要不变。
- py_compile、`git diff --check HEAD` exit 0。审查确认只新增局部证明协调与一个私有区间辅助函数，
  四个 canonical provider、公共 schema、类别规则和所有 gate 门禁未改变。
- 实际改名 gate、确定性完整 Mapping/gate 相等、逐字节恢复均通过。

Main Formal（由第一条测试独立执行；临时目录已随测试清理）：

```text
gold: /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t142-full-7qt2uapw/source/design.sv
gate: /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t142-full-7qt2uapw/gate/design.sv
negative: /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t142-full-7qt2uapw/negative.sv
top: proof_top
seq: 5
positive command: /Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python /Users/lufengchi/Desktop/workspace/rtl_obfuscation/scripts/formal_equivalence.py --gold /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t142-full-7qt2uapw/source/design.sv --gate /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t142-full-7qt2uapw/gate/design.sv --top proof_top --seq 5
positive exit: 0
positive JSON: {"formal_equivalence":"pass","gate":"/private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t142-full-7qt2uapw/gate/design.sv","gold":"/private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t142-full-7qt2uapw/source/design.sv","seq":5,"top":"proof_top"}
negative command: /Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python /Users/lufengchi/Desktop/workspace/rtl_obfuscation/scripts/formal_equivalence.py --gold /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t142-full-7qt2uapw/source/design.sv --gate /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t142-full-7qt2uapw/negative.sv --top proof_top --seq 5
negative exit: 1; unproven / equiv_status -assert detected
negative JSON: {"fixed_functional_negative":"rejected"}
```

主 Agent 接受 T142。规则扩展性只声明证明协调器保持动态候选与通用证据职责；不声称已经支持新
公共类别，也不承诺任意未来证明定义无需适配。最终速度及内存将在第二步结束后独立测量。
主 Agent 原始日志：`/tmp/full-production.JTQGLB/t142-main.stdout` / `.stderr`、
`t142-regression.stdout` / `.stderr`。未运行 RISC 或 blanket discovery。
