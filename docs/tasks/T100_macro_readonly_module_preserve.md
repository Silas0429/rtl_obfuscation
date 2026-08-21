# T100：宏只读边界与物理 module 局部保留

- 状态：`ACCEPTED`
- 设计负责人：主 Agent
- 实现负责人：GPT-5.6 Luna Extra high 子 Agent
- 前置任务：T073、T075、T077、T098、T099；当前基线 `ac46e4c`
- 任务类型：rewrite/mapping（SymbolGraph 边界修正，必须验证 actual rewritten gate）
- 执行规范：[`refactor_subagent_protocol.md`](../development/process/refactor_subagent_protocol.md)
- Formal verification：compact actual renamed gate 正例和固定功能负例均必需；禁止 RISC-V-Vector Formal

## 1. 单一目标

删除 SymbolGraph 对“全部宏展开位置都必须预先映射到一个 elaborated semantic module span”的全局
要求，改成宏只读、物理 module 局部保护：宏定义、宏调用、宏参数和宏展开 token 永远不成为
`SourceSymbol`、mapping record 或 rewrite edit；宏展开位置落入普通物理 module 时，只把该 module
及必要的跨 owner target 标记为安全保留，其他普通 module 继续执行用户选择的名称类别加密。

```text
完整 filelist -> PySlang compile（不变）
              -> physical syntax module spans
              -> macro location 只登记保护边界，不产生加密对象
              -> protected module: preserve/unsupported
              -> unaffected module: normal SymbolGraph/mapping/rewrite
```

本任务直接替换 T073 中“先扫描所有 macro-backed semantic location，任一位置无法映射 ordinary
semantic module span 就全局失败”的私有实现。不得保留旧预检分支、兼容开关、宏名白名单或第二套
collector。

## 2. 冻结行为合同

### 2.1 宏不是加密对象

- 宏定义名、形式参数、调用名、实参 spelling、宏正文和展开 token 均不得进入 SymbolGraph 或 mapping；
- 不得改写 `.h/.svh/.vh` 宏 context，也不得把宏正文复制成可编辑 source range；
- 不得使用 `getFullyOriginalLoc()`、宏 definition token 或 invocation argument 冒充 semantic
  occurrence；
- 不能通过 `--category`、新 CLI 开关或 compatibility mode 启用宏加密。

### 2.2 物理 module span 是保护边界

- module span 必须来自当前 `catalog_compilation.getSyntaxTrees()` 中普通物理
  `ModuleDeclarationSyntax` 的 source range，并通过 declaration name 的精确 file/start/end 与
  `SourceCatalog.modules` 对齐；不得从 `module`/`endmodule` 文本、module 名称或 fixture 路径猜测；
- `isMacroLoc()` 识别宏来源，`getFullyExpandedLoc()` 只用于定位 invocation 所在物理文件/offset；
- invocation offset 唯一落入一个普通物理 module span 时，登记该 owner 为
  `owner_contains_macro_source`，该 span 内所有已有 source symbol 都不得产生 edit；
- 一个 offset 同时落入多个普通物理 module span、物理 span 与 catalog owner 不一致、或 protected
  owner 仍产生 edit 时继续稳定 fail-closed；
- 宏位置不在普通物理 module 内时，它只是非 module 编译上下文，不得单独导致整个 SymbolGraph
  失败，也不得产生 source symbol。若后续 collector 发现它参与一个本应改写但无法安全隔离的物理
  symbol，仍按该 collector 的现有严格边界失败，不得静默发布不完整 edit。

### 2.3 局部保护与跨 owner 安全

- 宏生成 declaration/reference/register/assert/instance syntax 时，不为宏 token 建立 range；
- module 内出现任何不可写宏来源时，保持 T073/T075 的 owner quarantine 和 occurrence firewall：
  module 内声明、跨入该 module 的 occurrence，以及已精确绑定的 macro module-type target 都必须
  原子保留；
- 无宏的 sibling/top internal signal 仍可进入 `rename`，不能因为另一个 module 有宏而全局失败或
  全局 preserve；
- selected top 名称和端口边界保持现有规则；不改变 19 category、MappingVNext schema、rate、metrics、
  restore 或 Formal API。

### 2.4 错误与原子输出

- 原始 filelist PySlang parse/semantic error、重叠 physical spans、未隔离的真实待改写 reference、
  strict gate failure 和 restore/audit failure继续全局失败；
- 普通宏存在本身不是 input/mapping error；
- 失败时不得发布部分 output、mapping 或 metrics；成功时 gate/restore manifest 继续覆盖全部物理输入。

## 3. 固定 compact 输入

新增 `tests/fixtures/t100_macro_readonly_module_preserve/`：

- `design.f`：显式 source 顺序，top 为 `t100_top`；
- `rtl/t100_cell.sv`：普通小型 cell module；
- `rtl/t100_macro_owner.sv`：一个普通参数化 module，在 module 物理范围内定义多行 function-like
  macro；宏正文生成 generate-if 分支和 cell instance，调用后由物理 `else` 接 fallback，形状对应服务器
  `STL_GenSpSpcellBM(cellname, DATA_W, DEPTH, BE_W)`；
- `rtl/t100_clean.sv`：无宏 sibling，至少一个可安全改名的内部 signal；
- `rtl/t100_context.sv`：module 外宏展开的只读编译上下文，不产生 signals rewrite target，用来证明
  非 module 宏不会全局阻断 `--category signals`；
- `rtl/t100_top.sv`：实例化 macro owner 与 clean sibling，保持 top boundary。

fixture 不得包含真实 `ChipPlatform` 文件、绝对路径、vendor 名称或按 `STL_GenSpSpcellBM` 字面控制产品
行为。

## 4. 预期机器可验收输出

目标测试必须证明：

1. baseline 的 T073/T075/T077 23 个既有 tests 保持通过；新增模块实现前精确缺失；
2. compact SourceSet 与 SourceCatalog catalog/top-overlay blocking diagnostics 均为 0；
3. `build_symbol_graph()` 不再返回
   `macro expanded location does not map to one physical module owner`；macro owner 内全部 source symbol
   使用 `owner_contains_macro_source`（或 T077 已定义的合并 reason），且没有 macro token range；
4. clean sibling 至少一个 `signals` record 为 `eligible`，并通过公开命令
   `python rtl_encrypt.py --filelist tests/fixtures/t100_macro_readonly_module_preserve/design.f --top t100_top --category signals --output-dir <gate>`
   实际产生至少一个真实 rename/edit；macro owner 及宏文本在 gate 中字节不变；
5. generated gate strict compile 为 catalog/top-overlay `0/0 + 0/0`，direct restore 全部物理文件
   byte-identical，输出 `design.f` 与 SourceSet compile order 一致；
6. actual renamed gate Formal 正例 exit 0 且 JSON `formal_equivalence=pass`；从 actual gate 制作的唯一
   功能负例仍严格编译，但 Formal 非零并包含 `unproven` 与 `equiv_status -assert`；
7. graph/mapping/report 不包含宏名称或宏参数 category，且没有新增 schema、CLI 参数、adapter、fallback
   或 compatibility 路径。

## 5. 明确不包含

- 不加密宏，不展开后重写宏，不修改服务器 `ChipPlatform` 或用户 filelist；
- 不新增宏 category、宏配置、ignore/suppress 开关、名称白名单或基于 fixture 的判断；
- 不改变 filelist normalization、SourceSet compile order、project-root discovery 或三模式参数矩阵；
- 不扩展 package/class/interface 中名称的宏改写能力；非 module 宏在本任务只证明不会阻断无关
  `signals`；
- 不重构其他 SymbolGraph category、MappingVNext、rewrite、restore、rate 或 metrics；
- 不删除历史任务、测试或脚本；不运行 blanket unittest discovery 或 RISC-V-Vector Formal；
- 不保留被本任务替换的全局 macro-owner 预检兼容分支。

## 6. 允许修改

```text
docs/tasks/T100_macro_readonly_module_preserve.md
docs/development/future_work.md
docs/development/project_structure.md
docs/systemverilog_renaming_table.md
rtl_obfuscator/symbol_graph.py
tests/test_t073_macro_owner.py
tests/test_t075_owner_occurrence_firewall.py
tests/test_t077_multiple_quarantine_reason_merge.py
tests/test_t100_macro_readonly_module_preserve.py
tests/fixtures/t100_macro_readonly_module_preserve/**
```

历史测试只有在旧断言精确冻结“非 module 宏必须全局失败”时才允许改为本合同的新行为；不得删除 test
method、降低 range/owner/firewall 断言或修改其他 fixture。

## 7. 唯一 baseline 与验收命令

子 Agent 第一次实现编辑前只运行第一条命令。基线预期：T073/T075/T077 23 个既有 tests 通过，新增
`tests.test_t100_macro_readonly_module_preserve` 为 `ModuleNotFoundError`，`Ran 24 tests`，exit 非 0。

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_t073_macro_owner tests.test_t075_owner_occurrence_firewall tests.test_t077_multiple_quarantine_reason_merge tests.test_t100_macro_readonly_module_preserve -v
conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/symbol_graph.py tests/test_t073_macro_owner.py tests/test_t075_owner_occurrence_firewall.py tests/test_t077_multiple_quarantine_reason_merge.py tests/test_t100_macro_readonly_module_preserve.py
git diff --check HEAD
rg -x -- '- 状态：`READY_FOR_REVIEW`' docs/tasks/T100_macro_readonly_module_preserve.md
```

第一条目标 unittest 必须直接调用并记录 `scripts/formal_equivalence.py` 的 compact actual-gate 正例与
固定功能负例；这就是本任务唯一 Formal 流程。不得叠加历史 acceptance driver 或 RISC Formal。

## 8. 子 Agent 强制执行顺序

1. 完整阅读 `AGENTS.md`、本合同、`docs/tasks/README.md`、
   `refactor_subagent_protocol.md`、三模式架构第 2–5 节、`formal_verification.md`、T073/T075/T077；
2. 核对 HEAD、唯一 READY 任务和 clean worktree；
3. 编辑前把状态改为 `IN_PROGRESS`，填写开始记录；
4. 只运行第 7 节第一条命令作为 baseline，并核对精确结果；
5. 先建立 T100 compact fixture/test，再用最小产品修改替换旧全局预检；
6. 在任务范围内一次修完目标测试、strict gate、restore 和 Formal 正负例；
7. 填写 changed files、commands、results、schema/behavior、boundaries、Formal 证据；
8. 仅在全部通过后设置 `READY_FOR_REVIEW`；不 commit/push、不设置 `ACCEPTED`、不创建 T101。

## 9. 偏差与停止条件

出现以下任一情况，记录后停止，不得扩大：

- PySlang `getSyntaxTrees()`、`ModuleDeclarationSyntax.sourceRange` 或 macro location API 与冻结事实不同；
- 物理 module syntax span 无法通过 declaration identity 与 SourceCatalog owner 唯一对齐；
- protected module 仍产生 edit，或 clean sibling 被错误保护；
- 安全实现必须改写宏文本、猜 module 边界、增加兼容分支或修改允许文件外内容；
- actual renamed gate strict compile、byte restore 或 Formal 正例失败；
- 固定功能负例无法保持 strict compile 或 Formal 未失败。

## 10. 执行记录

子 Agent 执行记录：

```text
status: READY_FOR_REVIEW
starting_head: ac46e4c
first_command: git status --short --branch && git log -1 --oneline
branch: main...origin/main
inherited_changes: only the untracked T100 contract; no other user changes
actual_model: GPT-5.6 Luna Extra high
allowed_files_check: PASS; only the section 6 paths changed
baseline: exit 1; Ran 24 tests; T073/T075/T077 existing 23 tests passed; T100 import failed as expected with ModuleNotFoundError because tests.test_t100_macro_readonly_module_preserve did not yet exist
changed_files:
  rtl_obfuscator/symbol_graph.py
  docs/development/future_work.md
  docs/development/project_structure.md
  docs/systemverilog_renaming_table.md
  tests/test_t100_macro_readonly_module_preserve.py
  tests/fixtures/t100_macro_readonly_module_preserve/design.f
  tests/fixtures/t100_macro_readonly_module_preserve/rtl/t100_cell.sv
  tests/fixtures/t100_macro_readonly_module_preserve/rtl/t100_macro_owner.sv
  tests/fixtures/t100_macro_readonly_module_preserve/rtl/t100_clean.sv
  tests/fixtures/t100_macro_readonly_module_preserve/rtl/t100_context.sv
  tests/fixtures/t100_macro_readonly_module_preserve/rtl/t100_top.sv
  docs/tasks/T100_macro_readonly_module_preserve.md
commands:
  1. conda run -n rtl_obfuscation python -m unittest tests.test_t073_macro_owner tests.test_t075_owner_occurrence_firewall tests.test_t077_multiple_quarantine_reason_merge tests.test_t100_macro_readonly_module_preserve -v
  2. conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/symbol_graph.py tests/test_t073_macro_owner.py tests/test_t075_owner_occurrence_firewall.py tests/test_t077_multiple_quarantine_reason_merge.py tests/test_t100_macro_readonly_module_preserve.py
  3. git diff --check HEAD
  4. rg -x -- '- 状态：`READY_FOR_REVIEW`' docs/tasks/T100_macro_readonly_module_preserve.md
results:
  1. exit 0; Ran 29 tests; OK; T073/T075/T077 existing 23 tests and six T100 tests passed. T100 invokes the public signals CLI as a subprocess, and its public gate, restore, strict compile, mapping, macro-owner preservation, clean-sibling rename, and safety assertions all passed.
  2. exit 0
  3. exit 0
  4. exit 0; exact READY_FOR_REVIEW guard matched
schema_or_behavior: no schema/category/API/CLI option change; ordinary physical ModuleDeclarationSyntax spans come from catalog_compilation.getSyntaxTrees() and align to SourceCatalog module declaration identity; macro definitions, calls, parameters and expanded tokens produce no SourceSymbol, mapping record or rewrite edit; macro-generated syntax used only for public scope reporting is mapped to its unique physical module owner span, never published as an edit range; a macro-backed InstanceSymbol is retained only to prove and quarantine its ordinary target module; nonmodule macro context does not block unrelated signals; macro owner/target are atomically preserved while clean sibling signals rename through the public CLI
results_oracle: public command exit 0; generated design.f exactly matches the five-file compile order; public mapping contains no macro names/parameters, action_counts.rename > 0, macro-owner bytes are unchanged, clean-sibling bytes differ; public report strict compile passed and restore was byte-identical for all five physical files; catalog/top-overlay diagnostics are 0/0 + 0/0; macro owner and t100_cell target have no edits; compact safety assertion proves the physical macro argument cell_data has no graph occurrence and no eligible symbol occurrence covers that macro-backed location
boundaries: no macro text rewrite or macro category; package/class/interface macro rewrite remains out of scope; macro-generated module definitions, missing or ambiguous physical owner spans, and genuinely unisolated rewrite targets remain fail-closed; no server ChipPlatform or user filelist changed; blanket discovery and RISC-V-Vector Formal were not run
cleanup_candidates: none; no compatibility layer, fallback, second collector, fixture/name special case or obsolete test was introduced
formal_verification: PASS
gold: tests/fixtures/t100_macro_readonly_module_preserve
gate: /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t100-public-formal-positive-09jm2qb0/gate
top: t100_top
command: /Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python scripts/formal_equivalence.py --gold-filelist tests/fixtures/t100_macro_readonly_module_preserve/design.f --gold-root tests/fixtures/t100_macro_readonly_module_preserve --gate-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t100-public-formal-positive-09jm2qb0/gate/design.f --gate-root /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t100-public-formal-positive-09jm2qb0/gate --top t100_top --seq 5
exit_code: 0
result: {"formal_equivalence":"pass","gate":"/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t100-public-formal-positive-09jm2qb0/gate","gold":"tests/fixtures/t100_macro_readonly_module_preserve","seq":5,"top":"t100_top"}
negative_gate: /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t100-formal-negative-0prh5owj/negative
negative_command: /Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python scripts/formal_equivalence.py --gold-filelist tests/fixtures/t100_macro_readonly_module_preserve/design.f --gold-root tests/fixtures/t100_macro_readonly_module_preserve --gate-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t100-formal-negative-0prh5owj/negative/design.f --gate-root /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t100-formal-negative-0prh5owj/negative --top t100_top --seq 5
negative_compile: catalog/top overlay 0/0 + 0/0
negative_exit_code: 1
negative_result: fixed actual public signals gate remained strictly compilable; Formal nonzero and combined output contained unproven and equiv_status -assert
review_request: Main Agent rework completed in the same T100 scope; public signals CLI black-box, three allowed current-fact documents, and macro-ignore occurrence safety are now covered; ready for independent Main Agent review
rework: returned from READY_FOR_REVIEW to IN_PROGRESS before edits; no new task, file scope, compatibility layer, commit, push, or ACCEPTED status
```

完成时填写：

```text
status: READY_FOR_REVIEW | BLOCKED
changed_files:
commands:
results:
schema_or_behavior:
boundaries:
cleanup_candidates:
formal_verification: PASS | BLOCKED
gold:
gate:
top:
command:
exit_code:
result:
review_request:
```

## 11. 主 Agent 验收

```text
status: ACCEPTED
reviewed_head: ac46e4c
allowed_files: PASS; only section 6 paths changed
implementation_review: PASS; old global requirement that every macro-backed semantic location map to an elaborated module span was removed; ordinary module protection spans now come from catalog_compilation.getSyntaxTrees() physical ModuleDeclarationSyntax and exact SourceCatalog declaration identity; macro tokens remain absent from SourceSymbol/mapping/edit; no compatibility path, fallback, CLI option, macro category, fixture/name special case, or second collector was added
command_1: conda run -n rtl_obfuscation python -m unittest tests.test_t073_macro_owner tests.test_t075_owner_occurrence_firewall tests.test_t077_multiple_quarantine_reason_merge tests.test_t100_macro_readonly_module_preserve -v
result_1: PASS; exit 0; Ran 29 tests; OK
public_gate: PASS; public --filelist + --top t100_top + --category signals command exited 0; macro-owner bytes unchanged; clean-sibling bytes changed; action_counts.rename > 0; mapping contained no macro name or parameter; strict compile and restore byte identity passed
formal_positive_gate: /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t100-public-formal-positive-cy1_t48a/gate
formal_positive_command: /Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python scripts/formal_equivalence.py --gold-filelist tests/fixtures/t100_macro_readonly_module_preserve/design.f --gold-root tests/fixtures/t100_macro_readonly_module_preserve --gate-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t100-public-formal-positive-cy1_t48a/gate/design.f --gate-root /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t100-public-formal-positive-cy1_t48a/gate --top t100_top --seq 5
formal_positive_result: PASS; exit 0; {"formal_equivalence":"pass","top":"t100_top","seq":5}
formal_negative_gate: /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t100-formal-negative-wkfu5o4l/negative
formal_negative_command: /Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python scripts/formal_equivalence.py --gold-filelist tests/fixtures/t100_macro_readonly_module_preserve/design.f --gold-root tests/fixtures/t100_macro_readonly_module_preserve --gate-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t100-formal-negative-wkfu5o4l/negative/design.f --gate-root /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t100-formal-negative-wkfu5o4l/negative --top t100_top --seq 5
formal_negative_result: PASS; negative catalog/top overlay 0/0 + 0/0; Formal exit 1; assertions confirmed unproven and equiv_status -assert
command_2: conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/symbol_graph.py tests/test_t073_macro_owner.py tests/test_t075_owner_occurrence_firewall.py tests/test_t077_multiple_quarantine_reason_merge.py tests/test_t100_macro_readonly_module_preserve.py
result_2: PASS; exit 0
command_3: git diff --check HEAD
result_3: PASS; exit 0
ready_for_review_guard: PASS before acceptance
documentation: PASS; current project structure, renaming table, and future-work macro boundary synchronized
decision: ACCEPTED; T100 objective is complete; no T101 created
```
