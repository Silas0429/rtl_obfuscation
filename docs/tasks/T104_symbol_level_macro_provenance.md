# T104：所选符号级宏来源映射与冲突保护

- 状态：`ACCEPTED`
- 设计负责人：主 Agent
- 实现负责人：GPT-5.6 Luna Extra High 子 Agent
- 前置任务：T103 已 `ACCEPTED`
- 起始 HEAD：`f6fac8b`
- 任务类型：rewrite/mapping + compact end-to-end/Formal
- 执行规范：[`refactor_subagent_protocol.md`](../development/process/refactor_subagent_protocol.md)

## 1. 单一目标

删除 T100 的“module 内出现宏就保护整个 owner/target”行为，改为所选 RTL 符号级来源映射与冲突保护：
PySlang 已绑定的名称即使来自宏实参或宏正文，也必须尽量映射回唯一、拼写完全一致的物理 identifier
token；只有无法证明唯一物理来源的相关符号局部 `unsupported`，或在 declaration 本身没有可表示的物理
identifier 时原子拒绝。普通 object-like 常量宏和同 module 内无关符号不得降低加密覆盖率。

同一套来源解析必须服务于用户确认的四组核心对象，不得只为 `signals` 写特判：

1. module 内部 `signals`；
2. module `ports`；
3. `interfaces`、`interface_instances`、`interface_ports`、`modports`；
4. `struct_types`、`struct_fields`、`union_fields`。

本任务直接替换 T100 的 module-level macro quarantine，不保留兼容层、旧 reason 分支或第二套 collector。

## 2. 冻结实现计划

计划固定为四步，执行期间不得增加或拆分：

1. 冻结本合同、PySlang 物理来源事实和 compact 输入；
2. 子 Agent 实现统一的 selected-symbol 宏来源解析、局部冲突保护及测试；
3. 主 Agent 独立审查并运行合同门禁与 actual-gate Formal 正负例；
4. 验收后提交推送，并把服务器 StCache 重跑列为唯一外部下一步。

## 3. 冻结设计与行为合同

### 3.1 宏与 selected RTL symbol 的边界

- 宏定义名、宏形式参数名和宏调用名永远不是 rename target，不新增 macro category；
- “宏本身不加密”不等于“凡是经过宏展开的 RTL symbol 都不加密”。若 PySlang semantic target 属于本次
  selected category，其 declaration/reference 的物理 spelling 恰好位于宏调用实参或宏正文，该物理
  identifier 可以作为这个 RTL symbol 的 range；mapping 仍只记录 RTL symbol，不记录宏对象；
- `.h/.svh/.vh` 继续是正常物理输入。只有被唯一 selected RTL symbol 使用的精确 identifier range 才能
  进入 edit；常量、运算符、宏控制文本和未绑定 token 不进入 graph/mapping/edit；
- object-like 常量宏（例如 `` `WIDTH``、`` `STL_MAX``）自身不得触发 owner、file 或 symbol 保护。

### 3.2 唯一来源解析

在 `symbol_graph.py` 内建立一个 category-independent 的物理来源解析入口，所有上述四组 collector 复用：

1. 普通 file location：保持现有精确 `file/start/end`；
2. macro argument location：只允许通过 PySlang `SourceManager.getFullyOriginalLoc()` 回到调用处实参的
   单个原始 identifier，验证原始 bytes 与 semantic symbol name 完全一致，provenance 使用稳定值
   `semantic_macro_argument`；
3. macro body location：只允许回到宏定义正文中的单个原始 identifier，执行相同 bytes/范围验证，
   provenance 使用稳定值 `semantic_macro_body`；
4. 不得使用 `getFullyExpandedLoc()` 的合成展开位置作为 edit，不得用文本搜索、宏名白名单、module 名、
   fixture 路径或异常吞掉补 range；
5. 同一 symbol 的相同物理 range 去重后只改一次。declaration 与 occurrences 继续满足现有
   `SourceSymbol`、MappingVNext、range audit 和 source-free restore 不变量，不增加 schema。

### 3.3 冲突与不可精确映射

- 构图结束前建立 `physical identifier range -> selected symbol_id` 反向索引；同一 range 只对应同一
  semantic symbol 时可写，同一 range 被两个或更多不同 selected symbols 认领时，只把这些冲突符号设为
  `unsupported`，稳定 reason 为 `macro_origin_conflict`，无关 sibling 保持 eligible；
- 宏 token-paste、字符串化、复合实参或其他展开结果若不能回到“单个、名称完全相等”的原始 identifier，
  只把已经具有普通物理 declaration 的相关 selected symbol 设为 `unsupported`，稳定 reason 为
  `macro_origin_not_exact`；不得升级为整个 module/file 保护；
- 若 selected symbol 的 declaration 本身由宏合成且没有任何可精确表示的物理 identifier range，则现有
  `SourceSymbol` 无法安全表达。构图必须稳定抛出 `SYMBOL_GRAPH_MACRO_DECLARATION_UNMAPPABLE`，公开运行表现
  为 `REFUSED_ATOMIC` 且不发布 output/mapping/metrics；不得伪造 declaration range；
- 一个宏正文 identifier 被多次展开但始终绑定同一个 semantic symbol 时，允许去重后改一次；绑定到不同
  symbols 时按 `macro_origin_conflict` 处理；
- `owner_contains_macro_source` 不得再由宏存在产生，也不得出现在本任务成功 graph/mapping/report。其他与
  宏无关的 owner quarantine reason（例如 type parameter、defparam、nested generate）保持原行为。

### 3.4 四组核心类别的共同保证

- `signals` 的 declaration、普通引用、过程赋值和连接引用均走统一来源解析；
- `ports` 的 ANSI/non-ANSI declaration、named connection label 和端口 semantic references 均不得因宏
  存在保护整个 owner；top ABI preserve 规则不变；
- interface 类型、实例、成员和 modport declaration/reference 走同一来源与冲突判定；top 内直接
  interface instance 的既有 ABI preserve 规则不变；
- struct/union 类型与字段 declaration/member reference 走同一来源与冲突判定；既有 pattern-key 和
  unsupported 边界不扩大；
- parameter、genvar 和其他非本任务核心 category 不新增宏支持承诺，但也不得借由旧 module-level 宏
  quarantine 保护上述四组对象。若其自身宏来源不能证明，继续使用现有 symbol-local fail-closed 边界。

### 3.5 输出与安全不变量

- selected category 隔离、三态结果、filelist 顺序、strict compile、manifest/range audit、direct
  byte-identical restore、原子发布及 top ABI 规则不变；
- 局部 conflict/not-exact 且 gate/restore 成功时必须是 `PASS_PARTIAL`，逐对象 reason 可见；无
  preserve/unsupported 且有真实 rename 时是 `PASS_FULL`；不可表示 declaration 是
  `REFUSED_ATOMIC`；
- 不增加 CLI 开关、compatibility/fallback 模式、MappingVNext 字段、第二 graph 或名称特判。

## 4. 固定 compact 输入

新增 `tests/fixtures/t104_symbol_level_macro_provenance/`，只使用 SystemVerilog-compatible 小型代码：

- `design.f` 与必要 source/header：包含 object-like 常量宏、function-like 宏实参 signal declaration/
  reference，以及无宏 sibling；
- 同一输入包含 submodule ANSI port、interface 类型/实例/成员/modport、packed struct/union 类型与字段，
  它们的 declaration 或 reference 至少各有一个来自宏实参；
- 包含一个宏正文固定 RTL identifier 的唯一绑定，证明宏正文物理 token 可以按 selected symbol 改一次；
- 包含一个宏正文固定 identifier 被两个不同 selected symbols 认领的冲突，以及一个 token-paste 或复合
  实参导致的 non-exact reference，证明只局部 unsupported；
- `unmappable.f`：宏合成 selected declaration 且无精确原始 identifier，用于公开原子拒绝；
- fixture 不得包含服务器路径、ChipPlatform 名称或按 fixture/module/macro 名控制产品行为。

Formal 可使用 fixture 中不依赖 interface 的 Yosys-compatible `formal.f`/top；interface/struct 完整语义由
同一目标 unittest 的 PySlang/graph/rewrite/restore 断言覆盖。不得为了 Formal 删除宏来源 edit。

## 5. 预期机器可验收输出

目标测试必须证明：

1. SourceCatalog 编译诊断为 `0/0 + 0/0`；四组核心 category 的 macro-argument ranges 精确指向物理实参，
   provenance 正确，object-like 常量宏不产生 protection；
2. 唯一 macro-body token 只产生一个物理 edit；同 range 同 symbol 去重；mapping 中没有宏名/形式参数对象；
3. macro-body 冲突只影响冲突 symbols，reason 为 `macro_origin_conflict`；non-exact reference 只影响其
   semantic target，reason 为 `macro_origin_not_exact`；同 owner 无关 signals/ports/interface/struct
   sibling 至少各有一个真实 `rename`；
4. 既有 T073/T100/T101 宏 fixture 不再出现 `owner_contains_macro_source`；可精确映射的宏实参 symbol
   进入正常策略，宏正文冲突则只局部 unsupported；T103 的 T100 结果按真实记录重新判定，不冻结旧
   `PASS_PARTIAL` 结论；
5. public filelist gate strict compile、range/manifest audit 和 direct restore 全部通过；成功结果符合
   `PASS_FULL/PASS_PARTIAL`，输出中未被选中或冲突的宏文本保持正确；
6. `unmappable.f` 公开命令非零，stderr 包含 `REFUSED_ATOMIC`、
   `SYMBOL_GRAPH_MACRO_DECLARATION_UNMAPPABLE` 和具体文件/位置，且 output/map/metrics 均不存在；
7. compact actual renamed gate Formal 正例 exit 0、JSON `formal_equivalence=pass`；从 actual gate 制作的
   固定功能负例 strict compile 后 Formal 非零，并包含 `unproven` 与 `equiv_status -assert`；
8. 无旧 module macro quarantine、兼容层、第二 collector/schema、名称白名单、文本 range 猜测或异常吞掉。

## 6. 明确不包含

- 不加密宏定义名、形式参数名、调用名或宏控制结构；
- 不承诺 token-paste/stringify/复合实参生成的 selected declaration 可改名；此形状按合同原子拒绝；
- 不处理 inactive conditional branch、外部 testbench/SDC/DPI/VPI/UVM 字符串消费者、blackbox 或加密 IP；
- 不扩展四组核心对象以外 category 的宏能力，不改变其非宏语义；
- 不改变 SourceSet、三输入模式、category registry、rate、metrics、Formal 强度或 RISC-V-Vector；
- 不删除历史测试/fixture/脚本，不运行 blanket unittest discovery、历史 acceptance driver 或 RISC Formal；
- 不使用真实服务器 StCache 作为本地验收，不创建 T105。

## 7. 允许修改

```text
docs/tasks/T104_symbol_level_macro_provenance.md
docs/systemverilog_renaming_table.md
docs/development/project_structure.md
docs/development/future_work.md
rtl_obfuscator/symbol_graph.py
tests/test_symbol_graph_signals.py
tests/test_symbol_graph_parameters.py
tests/test_symbol_graph_genvars.py
tests/test_t073_macro_owner.py
tests/test_t100_macro_readonly_module_preserve.py
tests/test_t101_unelaborated_physical_module_boundary.py
tests/test_t103_selected_category_stable_outcomes.py
tests/test_t104_symbol_level_macro_provenance.py
tests/fixtures/t104_symbol_level_macro_provenance/**
```

不得修改既有 RTL/sample/fixture、其他产品模块或历史任务单。历史测试只允许把旧 module-level macro
quarantine 断言替换为本合同的新 symbol-level 结果，不得删除测试 method 或降低 strict/restore/Formal
断言。若实现需要超出列表，记录后停止。

## 8. 唯一 baseline 与验收命令

子 Agent 在第一次实现编辑前只运行第一条命令。冻结 baseline：以下既有测试通过，新增 T104 import 因文件
尚不存在失败；这是 baseline absence，不是产品验收失败。

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_symbol_graph_signals.SymbolGraphSignalsTests.test_macro_signal_declaration_safe_preserve tests.test_symbol_graph_signals.SymbolGraphSignalsTests.test_macro_signal_reference_safe_preserve tests.test_symbol_graph_parameters.SymbolGraphParameterTests.test_macro_parameter_declaration_safe_preserve tests.test_symbol_graph_parameters.SymbolGraphParameterTests.test_macro_parameter_reference_safe_preserve tests.test_symbol_graph_genvars.SymbolGraphGenvarTests.test_macro_genvar_declaration_safe_preserve tests.test_symbol_graph_genvars.SymbolGraphGenvarTests.test_macro_genvar_reference_safe_preserve tests.test_t073_macro_owner.T073MacroOwnerTests.test_graph_has_frozen_macro_quarantine_and_absent_macro_ranges tests.test_t073_macro_owner.T073MacroOwnerTests.test_statement_owner_and_macro_type_target_are_atomically_preserved tests.test_t100_macro_readonly_module_preserve.T100MacroReadonlyModulePreserveTests.test_catalog_graph_and_macro_readonly_boundary tests.test_t100_macro_readonly_module_preserve.T100MacroReadonlyModulePreserveTests.test_macro_owner_is_atomically_preserved_and_sibling_is_eligible tests.test_t101_unelaborated_physical_module_boundary.T101UnelaboratedPhysicalModuleBoundaryTests.test_macro_owner_and_clean_sibling_keep_existing_boundaries tests.test_t101_unelaborated_physical_module_boundary.T101UnelaboratedPhysicalModuleBoundaryTests.test_public_gate_preserves_candidate_and_macro_and_renames_clean tests.test_t103_selected_category_stable_outcomes.T103SelectedCategoryStableOutcomesTests.test_macro_boundary_is_pass_partial_and_hierarchical_is_refused_atomic tests.test_t104_symbol_level_macro_provenance -v
conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/symbol_graph.py tests/test_symbol_graph_signals.py tests/test_symbol_graph_parameters.py tests/test_symbol_graph_genvars.py tests/test_t073_macro_owner.py tests/test_t100_macro_readonly_module_preserve.py tests/test_t101_unelaborated_physical_module_boundary.py tests/test_t103_selected_category_stable_outcomes.py tests/test_t104_symbol_level_macro_provenance.py
git diff --check HEAD
conda run -n rtl_obfuscation python -c 'import subprocess; from pathlib import Path; exact={"docs/tasks/T104_symbol_level_macro_provenance.md","docs/systemverilog_renaming_table.md","docs/development/project_structure.md","docs/development/future_work.md","rtl_obfuscator/symbol_graph.py","tests/test_symbol_graph_signals.py","tests/test_symbol_graph_parameters.py","tests/test_symbol_graph_genvars.py","tests/test_t073_macro_owner.py","tests/test_t100_macro_readonly_module_preserve.py","tests/test_t101_unelaborated_physical_module_boundary.py","tests/test_t103_selected_category_stable_outcomes.py","tests/test_t104_symbol_level_macro_provenance.py"}; prefixes=("tests/fixtures/t104_symbol_level_macro_provenance/",); changed={line[3:] for line in subprocess.run(["git","status","--porcelain"],check=True,text=True,capture_output=True).stdout.splitlines() if line}; bad={path for path in changed if path not in exact and not path.startswith(prefixes)}; status=next(line for line in Path("docs/tasks/T104_symbol_level_macro_provenance.md").read_text().splitlines() if line.startswith("- 状态：")); assert not bad,bad; assert "docs/tasks/T104_symbol_level_macro_provenance.md" in changed,changed; assert status=="- 状态：`READY_FOR_REVIEW`",status; print("t104_ready_for_review=pass")'
```

第一条目标 unittest 必须直接运行本任务唯一一组 compact actual renamed gate Formal 正例和固定功能负例，
不得叠加 RISC Formal 或 blanket regression。

## 9. 子 Agent 强制顺序与停止条件

1. 完整阅读 `AGENTS.md`、本合同、`docs/tasks/README.md`、子 Agent 协议、架构第 2–5 节、
   `docs/formal_verification.md`、T100 与 T103；核对 HEAD、clean worktree 和唯一 `READY` 任务；
2. 第一次实现编辑前把本任务状态改为 `IN_PROGRESS`，记录 starting HEAD、实际模型、允许文件与 baseline；
3. 先建立 T104 compact test/fixture，再以最小产品 diff 删除 module macro quarantine、增加统一来源解析和
   symbol-level conflict finalization；只运行第 8 节门禁；
4. 若 PySlang API 不能把 semantic target 唯一追溯到原始物理 token，或实现需要改写允许文件外产品模块，
   必须记录并停止；不得通过 whole-owner preserve、名称特判、兼容分支或异常吞掉降级成功；
5. 全部门禁通过后记录 changed files、实际命令/退出码、四组 provenance/冲突结果、strict/restore/Formal
   正负证据和未覆盖边界，设置 `READY_FOR_REVIEW`；不得 `ACCEPTED`、commit、push 或创建下一任务。

## 10. 执行记录

子 Agent 按规范填写：

```text
status: READY_FOR_REVIEW
starting_head: f6fac8b; start_time=2026-08-24T11:49:24+08:00; workspace initially contains only the new T104 contract
actual_model: GPT-5.6 Luna Extra High (tool reasoning=max)
allowed_files_check: PASS; no pre-existing user changes overlap the section 7 allowlist
baseline: section 8 first command before implementation edits exited 1 only because tests.test_t104_symbol_level_macro_provenance did not exist; all pre-existing listed tests passed
rework_start: 2026-08-24T12:33:46+08:00; Main Agent returned the same task from READY_FOR_REVIEW to IN_PROGRESS; plan and section 7 allowlist stayed frozen
rework: removed the three stale module-level macro statements from the allowed fact documents; replaced single-byte regex boundary checks with explicit ASCII SystemVerilog identifier continuation checks and tested preceding/following A-Z/a-z/0-9/_/$; changed generate named-port occurrence creation to use _macro_provenance_for; added compact generate macro-argument provenance and macro-body conflict coverage; strengthened the public gate with explicit (category,name) rename assertions for signals:macro_signal, ports:child_in, interface_instances:bus, interface_ports:data, struct_fields:struct_field, and union_fields:union_field, plus no macro reason for interfaces/modports/struct_types
second_rework_start: 2026-08-24T12:43:43+08:00; Main Agent returned the same task for documentation/message consistency; plan and section 7 allowlist stayed frozen
second_rework: clarified in all three allowed fact documents that macro objects alone are never rename targets while a uniquely PySlang-bound physical identifier in a macro argument/body may be the selected RTL symbol edit source; removed interface from the unsupported future-work boundary; changed the unmappable declaration message to concrete reason text without repeating its error code; retained direct code/file and public atomic refusal assertions
third_rework_start: 2026-08-24T12:47:05+08:00; Main Agent returned the same task for a dead fallback; plan and section 7 allowlist stayed frozen
third_rework: removed the unreachable source_range-is-None fallback from _record_range; declaration mapping now has one error source in _resolve_source_range(..., declaration=True), with no compatibility path or behavior expansion
changed_files: docs/tasks/T104_symbol_level_macro_provenance.md; docs/systemverilog_renaming_table.md; docs/development/project_structure.md; docs/development/future_work.md; rtl_obfuscator/symbol_graph.py; tests/test_symbol_graph_signals.py; tests/test_symbol_graph_parameters.py; tests/test_symbol_graph_genvars.py; tests/test_t073_macro_owner.py; tests/test_t100_macro_readonly_module_preserve.py; tests/test_t101_unelaborated_physical_module_boundary.py; tests/test_t103_selected_category_stable_outcomes.py; tests/test_t104_symbol_level_macro_provenance.py; tests/fixtures/t104_symbol_level_macro_provenance/**
commands: final section 8 first command exit 0 (20 tests, including actual-gate Formal positive/negative); py_compile exit 0; git diff --check HEAD exit 0; all commands ran through conda run -n rtl_obfuscation
results: compact graph and public core-category gate passed; no owner_contains_macro_source; exact macro argument/body provenance is present; generated named-port macro argument is semantic_macro_argument; two generated macro-body claims are local macro_origin_conflict; token-paste target is macro_origin_not_exact; direct unmappable graph error retains code/file while its message contains only the concrete reason; public unmappable input is REFUSED_ATOMIC with no output; direct restore is byte-identical; continuation regression rejects every ASCII letter/digit/_/$ on both sides while punctuation-delimited sig remains exact
schema_or_behavior: one category-independent _resolve_source_range uses PySlang original locations plus exact physical bytes; macro argument/body provenance is attached to selected occurrences; interface-instance hierarchical macro bases are mapped; _augment_signal_generate_connection_occurrences now preserves the same provenance before _finalize_macro_origins indexes conflicts; all core SymbolOccurrence paths after _resolve_source_range/_token_source_range use the shared provenance lookup; _record_range has no unreachable declaration fallback; _finalize_macro_origins removes conflicting ranges and applies symbol-local reasons; no MappingVNext schema change
boundaries: no scope expansion; no commit, push, ACCEPTED, compatibility layer, fallback, second collector, name special case, or exception swallowing; only section 7 files changed
cleanup_candidates: none identified
formal_verification: PASS; compact actual renamed gate positive exit 0 with JSON formal_equivalence=pass; fixed functional negative strict-compiled and Formal exit 1 with unproven and equiv_status -assert; T104 direct decrypt/restore and public core-category gate also passed
review_request: READY_FOR_REVIEW; Main Agent must independently rerun the four section 8 gates and review the allowlisted diff; sub-agent did not set ACCEPTED and did not commit or push
```

## 11. 主 Agent 验收

2026-08-24 主 Agent 最终验收：`ACCEPTED`。完整审查 allowlisted diff 后，独立复跑第 8 节四条命令：
第一条 exit 0，`Ran 20 tests`、`OK`；compact actual renamed gate Formal 正例 exit 0，JSON 包含
`"formal_equivalence": "pass"`，固定功能负例 strict compile 后 Formal exit 1，包含 1 个 `unproven` 与
`equiv_status -assert`；第二、三条 exit 0；第四条 exit 0 并输出 `t104_ready_for_review=pass`。

主 Agent 核对确认：宏对象仍不是 rename target；普通、macro argument 与 macro body identifier 由一个
category-independent resolver 映射到 exact physical token；signals、ports、interface 组和 struct/union
组均有真实 rename；object-like 常量宏不再触发 owner 保护；同一宏来源的多 symbol 冲突只产生局部
`macro_origin_conflict`，token-paste/non-exact 只产生局部 `macro_origin_not_exact`；不可表示 declaration
稳定 `REFUSED_ATOMIC` 且无输出；strict gate、range/manifest audit、direct byte-identical restore 和文档
同步均通过。`owner_contains_macro_source` 的产品路径已删除，无 compatibility、fallback、第二 collector、
schema/CLI 变更、名称特判或 allowlist 外修改。服务器 StCache 重跑是交付后的唯一外部下一步。
