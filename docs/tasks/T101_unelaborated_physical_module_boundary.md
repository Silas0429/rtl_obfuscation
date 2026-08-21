# T101：未 elaboration 物理 module 的只读边界

- 状态：`ACCEPTED`
- 设计负责人：主 Agent
- 实现负责人：GPT-5.6 Luna Extra high 子 Agent
- 前置任务：T100；当前基线 `0c9bdec`
- 任务类型：rewrite/mapping（SymbolGraph owner 边界修正，必须验证 actual rewritten gate）
- 执行规范：[`refactor_subagent_protocol.md`](../development/process/refactor_subagent_protocol.md)
- Formal verification：compact actual renamed gate 正例和固定功能负例均必需；禁止 RISC-V-Vector Formal

## 1. 单一目标

删除 T100 `_physical_module_spans()` 中“每个普通物理 `ModuleDeclarationSyntax` 都必须反向匹配一个
`SourceCatalog.modules` owner”的错误全局要求，改成单向严格关系：每个当前 elaboration 的 semantic
`ModuleOwner` 必须精确匹配唯一物理 module span；filelist 中合法存在、但因参数化 conditional generate
等当前配置未 elaboration 的普通物理 module，不建立 owner、SymbolGraph record、mapping 或 edit，作为
只读物理输入进入 gate、manifest 和 restore，不得阻断其他 module 的加密。

```text
完整 filelist + PySlang compile 成功
    ├─ elaborated semantic module -> 唯一 physical span -> 正常 graph/preserve/rename
    └─ syntax-only physical module -> no owner/no graph/no edit -> byte-preserved pass-through
```

本任务直接替换双向集合相等假设，不得保留旧失败分支、compatibility mode、fallback、module 名白名单、
ECC/generate 特判或第二套 owner collector。

## 2. 冻结行为合同

### 2.1 编译与 owner 权威

- `SourceSet`、显式 filelist 顺序、include/define context 和 `SourceCatalog` 的 PySlang compilation 保持
  当前实现，不修改 discovery 或重新计算 elaboration；
- `SourceCatalog.modules` 继续表示当前 catalog semantic view 中可建立稳定 owner 的 elaborated module；
- 普通物理 module 声明继续来自同一个 `catalog_compilation.getSyntaxTrees()` 中的
  `ModuleDeclarationSyntax`，不得从源码文本、module 名或 fixture 路径猜边界；
- semantic owner 通过 declaration name 的精确 `(file,start,end)` 映射到物理 syntax span；每个 semantic
  owner 缺少 span、映射到多个不同 span、span 重叠或 source bytes 不符时继续稳定 fail-closed。

### 2.2 Syntax-only 物理 module

- 一个普通物理 module declaration 没有对应 `SourceCatalog.modules` owner 时，表示它在当前 compilation
  配置中未进入 semantic owner registry；该事实本身不是错误；
- 不得为它伪造 `ModuleOwner`、空 graph record、preserve record 或 unsupported record；
- 不得执行常量求值、generate 分支发现或按 module 名判断它为何未 elaboration；
- 它的物理文件仍必须保留在 SourceSet manifest、canonical `design.f`、gate 和 restore 中；没有其他 edit
  时该 module 源码字节保持不变；
- 若后续现有 collector 实际产生了属于该 module 的待改写 semantic symbol、reference 或 edit，却仍没有
  owner，继续按现有 owner/range 校验 fail-closed，不得静默发布半改名结果。

### 2.3 宏局部保护保持不变

- 宏仍然不是 rename target；T100 的 macro owner quarantine、target quarantine 和 occurrence firewall
  不变；
- 宏展开位置落入已对齐 semantic owner 的物理 span 时，继续局部保护该 owner；
- 宏展开位置只落入 syntax-only 未 elaboration module 时，不建立 owner，也不全局失败；该 module 本来就
  没有 graph/edit，物理字节继续透传；
- ordinary macro owner、无宏 clean sibling 和未 elaboration candidate 必须可以同时存在：macro owner
  preserve、clean sibling rename、candidate byte-preserved。

### 2.4 对外行为与原子性

- 不改变 19 category、CLI 参数、MappingVNext schema、rate、metrics、restore 或 Formal API；
- 不增加 warning suppression、ignore 开关、兼容层或降级成功路径；
- 原始 PySlang parse/semantic diagnostics、真实 owner/range 冲突、strict gate failure、restore/audit failure
  继续全局失败且不得发布部分输出；
- 当前公开 filelist `--category signals` 必须能够越过本合同 compact 输入并产生真实 rename。

## 3. 固定 compact 输入

新增 `tests/fixtures/t101_unelaborated_physical_module_boundary/`：

- `design.f`：按下列六个 source unit 的固定顺序；top 为 `t101_top`；
- `rtl/t101_candidate.sv`：普通 candidate module，只在参数恒为 false 的 generate 分支中被引用，因此物理
  declaration 存在，但当前 catalog semantic owner registry 不包含它；
- `rtl/t101_chosen.sv`：generate else 分支实际 elaboration 的普通 module；
- `rtl/t101_selector.sv`：参数默认选择 chosen，false/true 分支形状必须由 PySlang 自然决定，不得由产品
  代码识别 fixture 常量；
- `rtl/t101_macro_owner.sv`：普通 elaborated module，包含一个最小 function-like macro 调用，用于证明
  T100 physical-span/macro-owner 路径仍被实际执行并局部 preserve；
- `rtl/t101_clean.sv`：无宏 elaborated sibling，至少一个可安全改名的内部 signal；
- `rtl/t101_top.sv`：实例化 selector、macro owner 和 clean sibling，保持 top 名及 ports。

fixture 不得包含真实 `ChipPlatform` 文件、vendor/ECC 名称、绝对路径或按 fixture/module 名控制产品行为。

## 4. 预期机器可验收输出

目标测试必须证明：

1. 实现前两个指定 T100 graph tests 通过，新增 T101 模块精确缺失；
2. T101 SourceSet/SourceCatalog 的 catalog/top-overlay diagnostics 为 `0/0 + 0/0`；物理 syntax inventory
   包含 `t101_candidate`，`catalog.modules` 不包含它，并包含 `t101_chosen`、selector、macro owner、clean
   和 top；
3. `build_symbol_graph()` 成功；candidate 没有 owner、SourceSymbol、mapping record 或 edit；每个现有
   catalog semantic owner 仍可唯一对齐物理 span；
4. macro owner 内 graph symbols 使用 T100 既有安全保护 reason，clean sibling 至少一个 `signals`
   symbol 为 `eligible`；
5. 公开命令
   `python rtl_encrypt.py --filelist tests/fixtures/t101_unelaborated_physical_module_boundary/design.f --top t101_top --category signals --output-dir <gate>`
   exit 0、`action_counts.rename > 0`、strict compile true；candidate 与 macro-owner bytes 不变，clean bytes
   改变；generated `design.f` 等于六文件 compile order；
6. direct public decrypt 恢复六个物理文件且逐字节一致；mapping/report 不包含 candidate owner/record，
   manifest 仍包含 candidate file；
7. actual renamed gate Formal 正例 exit 0 且 JSON `formal_equivalence=pass`；从 actual gate 制作的唯一功能
   负例仍严格编译，但 Formal 非零并包含 `unproven` 与 `equiv_status -assert`；
8. 没有新增 schema、CLI 参数、adapter、fallback、compatibility path、第二套 collector 或名称特判。

## 5. 明确不包含

- 不修改服务器 `ChipPlatform`、用户 filelist 或真实 ECC source；
- 不扩展 SourceCatalog 让全部 syntax module 伪装成 elaborated owner；
- 不实现 generate constant evaluator、未 elaboration module 加密、宏加密或 macro-generated module；
- 不修改 filelist normalization、compile order、top overlay、project-root discovery 或三模式参数矩阵；
- 不修改公开 CLI 编排错误详情透传；该独立问题不进入本合同；
- 不删除历史代码、测试、脚本或兼容文件；如未来需要 cleanup，必须另有明确授权合同；
- 不运行 blanket unittest discovery、历史 acceptance driver 或 RISC-V-Vector Formal。

## 6. 允许修改

```text
docs/tasks/T101_unelaborated_physical_module_boundary.md
docs/development/future_work.md
docs/development/project_structure.md
docs/systemverilog_renaming_table.md
rtl_obfuscator/symbol_graph.py
tests/test_t101_unelaborated_physical_module_boundary.py
tests/fixtures/t101_unelaborated_physical_module_boundary/**
```

不得修改 T100 fixture/test 或其他历史测试；若新语义与历史 oracle 冲突，记录后停止，不得放宽旧断言。

## 7. 唯一 baseline 与验收命令

子 Agent 第一次实现编辑前只运行第一条命令。基线预期：两个指定 T100 tests 通过，T101 import 因文件
尚不存在而失败，`Ran 3 tests`，exit 非 0。

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_t100_macro_readonly_module_preserve.T100MacroReadonlyModulePreserveTests.test_catalog_graph_and_macro_readonly_boundary tests.test_t100_macro_readonly_module_preserve.T100MacroReadonlyModulePreserveTests.test_macro_owner_is_atomically_preserved_and_sibling_is_eligible tests.test_t101_unelaborated_physical_module_boundary -v
conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/symbol_graph.py tests/test_t101_unelaborated_physical_module_boundary.py
git diff --check HEAD
rg -x -- '- 状态：`READY_FOR_REVIEW`' docs/tasks/T101_unelaborated_physical_module_boundary.md
```

第一条目标 unittest 必须直接调用并记录 `scripts/formal_equivalence.py` 的 T101 compact actual-gate 正例
与固定功能负例；这就是本任务唯一 Formal 流程。

## 8. 子 Agent 强制执行顺序

1. 完整阅读 `AGENTS.md`、本合同、`docs/tasks/README.md`、
   `refactor_subagent_protocol.md`、三模式架构第 2–5 节、`formal_verification.md` 和 T100；
2. 核对 HEAD、唯一 READY 任务和 clean worktree；
3. 编辑实现前先把本合同状态改成 `IN_PROGRESS`，填写开始记录；
4. 只运行第 7 节第一条命令作为 baseline，并核对精确结果；
5. 先建立 compact fixture/test，再做最小产品修改；
6. 在本合同范围内一次完成 graph、public gate、strict compile、restore 和 Formal 正负例；
7. 同步三份允许的当前事实文档，明确 syntax-only module 是只读物理输入而不是 graph owner；
8. 填写 changed files、commands、results、schema/behavior、boundaries、Formal 证据；
9. 全部通过后设置 `READY_FOR_REVIEW`；不 commit/push、不设置 `ACCEPTED`、不创建 T102。

## 9. 偏差与停止条件

出现以下任一情况，记录后停止，不得扩大：

- compact 输入没有复现“物理 candidate 存在但 semantic owner 不存在”的已验证 PySlang 行为；
- 修复必须改变 SourceCatalog、SourceSet、mapping schema、CLI 或 filelist compile context；
- 任一 semantic owner 无法唯一对齐物理 span，或者真实待改写对象没有 owner；
- candidate 产生 graph/mapping/edit，macro owner 产生 edit，或 clean sibling 无法 rename；
- 实现需要名称白名单、generate 求值、异常吞掉、fallback、兼容分支或第二套 owner registry；
- actual renamed gate strict compile、byte restore 或 Formal 正例失败；
- 固定功能负例不能保持 strict compile 或 Formal 未失败。

## 10. 执行记录

子 Agent 开始时填写：

```text
status: READY_FOR_REVIEW
starting_head: 0c9bdec
first_command: pwd && git status --short --branch && printf '%s\\n' '--- task files ---' && rg --files docs/tasks | sort | tail -30
branch: main...origin/main
inherited_changes: only the untracked T101 contract; no other user changes
actual_model: GPT-5.6 Luna Extra high
allowed_files_check: PASS; no existing changes overlap section 6 paths except this contract
baseline: exit 1; Ran 3 tests; the two specified T100 tests passed and T101 import failed as expected with ModuleNotFoundError
changed_files:
  docs/tasks/T101_unelaborated_physical_module_boundary.md
  docs/development/future_work.md
  docs/development/project_structure.md
  docs/systemverilog_renaming_table.md
  rtl_obfuscator/symbol_graph.py
  tests/test_t101_unelaborated_physical_module_boundary.py
  tests/fixtures/t101_unelaborated_physical_module_boundary/design.f
  tests/fixtures/t101_unelaborated_physical_module_boundary/rtl/t101_candidate.sv
  tests/fixtures/t101_unelaborated_physical_module_boundary/rtl/t101_chosen.sv
  tests/fixtures/t101_unelaborated_physical_module_boundary/rtl/t101_selector.sv
  tests/fixtures/t101_unelaborated_physical_module_boundary/rtl/t101_macro_owner.sv
  tests/fixtures/t101_unelaborated_physical_module_boundary/rtl/t101_clean.sv
  tests/fixtures/t101_unelaborated_physical_module_boundary/rtl/t101_top.sv
commands:
  1. conda run -n rtl_obfuscation python -m unittest tests.test_t100_macro_readonly_module_preserve.T100MacroReadonlyModulePreserveTests.test_catalog_graph_and_macro_readonly_boundary tests.test_t100_macro_readonly_module_preserve.T100MacroReadonlyModulePreserveTests.test_macro_owner_is_atomically_preserved_and_sibling_is_eligible tests.test_t101_unelaborated_physical_module_boundary -v
  2. conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/symbol_graph.py tests/test_t101_unelaborated_physical_module_boundary.py
  3. git diff --check HEAD
  4. rg -x -- '- 状态：`READY_FOR_REVIEW`' docs/tasks/T101_unelaborated_physical_module_boundary.md
results:
  1. exit 0; Ran 8 tests; OK; both specified T100 tests and all T101 tests passed; actual-gate Formal positive exited 0 with formal_equivalence pass and fixed functional negative remained strict-compilable with Formal exit 1
  2. exit 0
  3. exit 0
  4. exact READY_FOR_REVIEW line matched
schema_or_behavior: `_physical_module_spans()` now ignores physical ModuleDeclarationSyntax declarations without a catalog semantic owner, while retaining the reverse requirement that every semantic ModuleOwner maps to exactly one physical span; T101 graph and mapping assertions now inspect declaration/occurrence file paths directly; no SourceSet, SourceCatalog, mapping schema, CLI, category, compile context or second collector changed
results_oracle: catalog/top-overlay diagnostics were 0/0 + 0/0; physical syntax inventory contained t101_candidate while catalog.modules excluded it and contained the other five modules; graph succeeded with no candidate owner/symbol, declaration range or occurrence range in `rtl/t101_candidate.sv`; public filelist gate exited 0 with action_counts.rename > 0, no mapping declaration or occurrence range in the candidate file, candidate present in input manifest and candidate gate bytes unchanged, macro-owner bytes unchanged, clean bytes changed, generated design.f equal to the six-file compile order, strict compile true and restore byte-identical
boundaries: syntax-only ordinary modules remain read-only physical inputs; no generate evaluator, module-name special case, macro encryption, compatibility layer, fallback, schema/API/CLI change, second collector, T100 modification, server ChipPlatform change, blanket discovery or RISC-V-Vector Formal
cleanup_candidates: none
formal_verification: PASS
gold: tests/fixtures/t101_unelaborated_physical_module_boundary
gate: /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t101-public-formal-positive-_q6h3gdd/gate
top: t101_top
command: /Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python scripts/formal_equivalence.py --gold-filelist tests/fixtures/t101_unelaborated_physical_module_boundary/design.f --gold-root tests/fixtures/t101_unelaborated_physical_module_boundary --gate-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t101-public-formal-positive-_q6h3gdd/gate/design.f --gate-root /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t101-public-formal-positive-_q6h3gdd/gate --top t101_top --seq 5
exit_code: 0
result: {"formal_equivalence": "pass", "gate": "/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t101-public-formal-positive-_q6h3gdd/gate", "gold": "tests/fixtures/t101_unelaborated_physical_module_boundary", "seq": 5, "top": "t101_top"}
negative_gate: /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t101-formal-negative-mzb29per/negative
negative_command: /Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python scripts/formal_equivalence.py --gold-filelist tests/fixtures/t101_unelaborated_physical_module_boundary/design.f --gold-root tests/fixtures/t101_unelaborated_physical_module_boundary --gate-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t101-formal-negative-mzb29per/negative/design.f --gate-root /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t101-formal-negative-mzb29per/negative --top t101_top --seq 5
negative_compile: catalog/top overlay 0/0 + 0/0
negative_exit_code: 1
negative_result: fixed actual gate remained strictly compilable; Formal output/stderr contained unproven and equiv_status -assert
review_request: T101 contract-internal rework is complete; ready for independent Main Agent review; no commit, push, ACCEPTED status or T102 was created
rework: Main Agent found the prior public assertion compared module names against owner_id values and the graph name assertion did not prove candidate-file range absence; corrected both graph and mapping checks to assert candidate-file declaration/occurrence range absence; product code unchanged
```

## 11. 主 Agent 验收

```text
status: ACCEPTED
reviewed_head: 0c9bdec
allowed_files: PASS; only section 6 paths changed
implementation_review: PASS; the reverse failure for ordinary physical ModuleDeclarationSyntax without a catalog owner was removed, while exact declaration identity, duplicate-span conflict checks and the final requirement that every semantic ModuleOwner has one physical span remain; no SourceSet/SourceCatalog change, fake owner, generate evaluator, compatibility path, fallback, second collector, module-name special case or CLI/schema change was added
command_1: conda run -n rtl_obfuscation python -m unittest tests.test_t100_macro_readonly_module_preserve.T100MacroReadonlyModulePreserveTests.test_catalog_graph_and_macro_readonly_boundary tests.test_t100_macro_readonly_module_preserve.T100MacroReadonlyModulePreserveTests.test_macro_owner_is_atomically_preserved_and_sibling_is_eligible tests.test_t101_unelaborated_physical_module_boundary -v
result_1: PASS; exit 0; Ran 8 tests in 1.071s; OK
public_gate: PASS; public --filelist + --top t101_top + --category signals exited 0; action_counts.rename > 0; strict compile and restored byte identity passed; candidate and macro-owner bytes were unchanged, clean bytes changed, candidate remained in input manifest and no graph/mapping declaration or occurrence range used the candidate file
formal_positive_gate: /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t101-public-formal-positive-ugoeb_5m/gate
formal_positive_command: /Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python scripts/formal_equivalence.py --gold-filelist tests/fixtures/t101_unelaborated_physical_module_boundary/design.f --gold-root tests/fixtures/t101_unelaborated_physical_module_boundary --gate-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t101-public-formal-positive-ugoeb_5m/gate/design.f --gate-root /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t101-public-formal-positive-ugoeb_5m/gate --top t101_top --seq 5
formal_positive_result: PASS; exit 0; {"formal_equivalence":"pass","top":"t101_top","seq":5}
formal_negative_gate: /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t101-formal-negative-9dp5i04g/negative
formal_negative_command: /Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python scripts/formal_equivalence.py --gold-filelist tests/fixtures/t101_unelaborated_physical_module_boundary/design.f --gold-root tests/fixtures/t101_unelaborated_physical_module_boundary --gate-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t101-formal-negative-9dp5i04g/negative/design.f --gate-root /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t101-formal-negative-9dp5i04g/negative --top t101_top --seq 5
formal_negative_result: PASS; negative catalog/top overlay remained 0/0 + 0/0; Formal exit 1; assertions confirmed unproven and equiv_status -assert
command_2: conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/symbol_graph.py tests/test_t101_unelaborated_physical_module_boundary.py
result_2: PASS; exit 0
command_3: git diff --check HEAD
result_3: PASS; exit 0
ready_for_review_guard: PASS before acceptance; exact READY_FOR_REVIEW line matched
documentation: PASS; project structure, renaming table and future-work now describe syntax-only unelaborated modules as read-only physical inputs and retain semantic-owner fail-closed
decision: ACCEPTED; T101 objective is complete; next step is only server StCache retest; no T102 created
```
