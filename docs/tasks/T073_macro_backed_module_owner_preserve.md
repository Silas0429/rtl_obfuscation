# T073：普通物理 module 内宏来源安全保留

- 状态：`ACCEPTED`
- 合同版本：1.0
- 设计时间：2026-07-31
- 设计负责人：主 Agent
- 实现负责人：Luna 子 Agent（`gpt-5.6-luna`，`xhigh`）
- 前置任务：T072 `ACCEPTED`，交付提交 `ef20c6d`
- 设计基线 HEAD：`ef20c6d7a861ea7602260012406ace0d857b0b45`
- 任务类型：SymbolGraph owner quarantine 修复；产生 rewritten RTL

## 1. 单一目标

T073 不改写宏定义或宏调用文本，只把已有普通物理 `ModuleOwner` 内的不可写宏来源从
whole-graph failure 转换为 module-owner 安全保留：

1. 宏生成 declaration、reference、register/assert 语句位置都保护其普通物理 owner；
2. owner 内已物理收集的全部 symbol 固定为
   `support="unsupported"`、`reason="owner_contains_macro_source"`；
3. 宏生成且没有独立可写物理 token 的 declaration/occurrence 不进入 graph；
4. 宏来源跨 owner 引用时，通过 semantic target 同时保护目标普通物理 owner；
5. 同文件/其他文件 sibling 和 selected top 内部对象继续真实改名；
6. 无法取得 semantic target、唯一物理 owner 或精确 module span 时保持原子 fail-closed。

T073 不支持 ``module `TEC_RV_ICG`` 一类宏生成 module definition name。该 declaration
没有当前 `SourceCatalog.ModuleOwner` 能表示的普通物理 module identifier，必须继续在
SourceCatalog 阶段 fail-closed。

T073 不增加宏展开、宏文本 rewrite、源码拼写搜索、公开 API、schema、CLI、mapping、rewrite、
restore 或 Formal 变化。

## 2. 起始状态

```text
branch: main...origin/main
HEAD: ef20c6d7a861ea7602260012406ace0d857b0b45
staged/unstaged changes: none
main-agent frozen untracked inputs:
  docs/tasks/T073_macro_backed_module_owner_preserve.md
  tests/fixtures/t073_macro_owner/design.f
  tests/fixtures/t073_macro_owner/invalid_module_name.f
  tests/fixtures/t073_macro_owner/rtl/macro_design.sv
  tests/fixtures/t073_macro_owner/rtl/sibling.sv
  tests/fixtures/t073_macro_owner/rtl/top.sv
  tests/fixtures/t073_macro_owner/rtl/invalid_module_name.sv
```

上述输入由主 Agent 建立并冻结。T040/T041/T042 的六个既有 macro negative fixture 在
T073 中迁移为 ordinary-owner safe-preserve 回归；全部 fixture 对子 Agent只读。

## 3. 冻结 fixture

### 3.1 T073 正例

```text
source root: tests/fixtures/t073_macro_owner
filelist: design.f
top: t073_top
compile order:
  rtl/macro_design.sv
  rtl/sibling.sv
  rtl/top.sv
```

模块角色：

```text
t073_macro_target:
  ordinary physical module
  被 t073_macro_owner 的宏生成 module-type token 语义引用
t073_macro_owner:
  宏生成 signal declaration
  宏生成 signal reference
  register/assert 宏语句
  宏生成 module-type token，physical instance name 仍可定位
t073_macro_statement_owner:
  只有 register/assert 宏来源，没有宏 declaration 或 macro-type
t073_sibling:
  不受宏影响的独立 sibling
t073_top:
  selected top，实例化上述 owner
```

### 3.2 明确不支持的 module name

```text
filelist: invalid_module_name.f
source: rtl/invalid_module_name.sv
construct: module `T073_GENERATED_MODULE_NAME (...)
expected: SourceCatalogError
code: CATALOG_RANGE_INVALID
message contains: declaration is outside the SourceSet root
```

不得为该文件构造伪 `ModuleOwner`，不得把宏 invocation 或 definition token 当作 module
declaration。

### 3.3 迁移的既有 fixture

只允许迁移以下六项旧 whole-graph failure 测试；fixture 不得修改：

```text
tests/test_symbol_graph_signals.py:
  test_macro_signal_declaration_fails_closed
  test_macro_signal_reference_fails_closed
tests/test_symbol_graph_parameters.py:
  test_macro_parameter_declaration_fails_closed
  test_macro_parameter_reference_fails_closed
tests/test_symbol_graph_genvars.py:
  test_macro_genvar_declaration_fails_closed
  test_macro_genvar_reference_fails_closed
```

迁移后名称必须表达 `safe_preserve`。所有可物理收集 symbol 都必须为
`unsupported/owner_contains_macro_source`，宏生成且没有独立可写物理 token 的 symbol 或
occurrence 必须缺席：

```text
signal macro declaration: 1/1/0/1
signal macro reference:   2/2/1/3
parameter macro declaration: 2/2/0/2
parameter macro reference:   3/3/0/3
genvar macro declaration: 3/3/0/3
genvar macro reference:   4/4/3/7
```

顺序均为 `symbols/declarations/occurrences/total_ranges`。

### 3.4 SHA-256 与字节数

T073 新 fixture：

| file | bytes | SHA-256 |
| --- | ---: | --- |
| `t073_macro_owner/design.f` | 46 | `bd7924d0e395132b811be56761cd98d2c3441d1fb125613dd417bc0d1383b119` |
| `t073_macro_owner/invalid_module_name.f` | 27 | `b7031eacccc33e4dd61ab6ebc148a1b7def22da6d6291cdd982f977e0de22ca9` |
| `t073_macro_owner/rtl/macro_design.sv` | 1180 | `3c43b72edb547d3da8c978f5fe61c0a3a08fa0fda9ead44afa8e4564e2e48b62` |
| `t073_macro_owner/rtl/sibling.sv` | 181 | `3435e2e32f3fa319d44a079827703be09b0cf989b8a5e2048b103f456e396cfa` |
| `t073_macro_owner/rtl/top.sv` | 552 | `1d6acf48a38c03ca0ad4bb482c8b2b89061711d69fd7120adc709e6e3e9fd5d5` |
| `t073_macro_owner/rtl/invalid_module_name.sv` | 185 | `c54c04d3f96f6621a65c3bff1683dc3a6701a517bc8622403215229736498176` |

迁移 fixture：

| file | bytes | SHA-256 |
| --- | ---: | --- |
| `refactor_symbol_graph_signals_invalid/macro_declaration.f` | 25 | `8a487027e235f5e64676db6d94acf31fac3ba41d31c0809309916f6b542b897a` |
| `refactor_symbol_graph_signals_invalid/macro_reference.f` | 23 | `b3738dfc81f16b979969cb837cfb97eb75c20ab7cdc555099838ac2c8eb34daa` |
| `refactor_symbol_graph_signals_invalid/rtl/macro_declaration.sv` | 142 | `3388554b0856f0f437a632d4b1a6c943928b55d39a6a50bbd10ce0834364a65f` |
| `refactor_symbol_graph_signals_invalid/rtl/macro_reference.sv` | 133 | `c7c85d2ddbce9640c3e896d7dfc6496a1c6389a31f1385db3b21af4c3ab2cabc` |
| `refactor_symbol_graph_parameters_invalid/macro_declaration.f` | 25 | `8a487027e235f5e64676db6d94acf31fac3ba41d31c0809309916f6b542b897a` |
| `refactor_symbol_graph_parameters_invalid/macro_reference.f` | 23 | `b3738dfc81f16b979969cb837cfb97eb75c20ab7cdc555099838ac2c8eb34daa` |
| `refactor_symbol_graph_parameters_invalid/rtl/macro_declaration.sv` | 179 | `eb6fe663e8fe0d77459421f38a58a8b59d1ada6e0f84f77b6aea246111fcaf43` |
| `refactor_symbol_graph_parameters_invalid/rtl/macro_reference.sv` | 158 | `dc08df0b277c689311adacd1fcbade51d5a3d328503e8d680dda5cf81fc2dedb` |
| `refactor_symbol_graph_genvars_invalid/macro.f` | 13 | `e80759aef554c40fe00a9b5706a191d075b00999ebf75688080b9832f12c97d6` |
| `refactor_symbol_graph_genvars_invalid/macro_reference.f` | 23 | `b3738dfc81f16b979969cb837cfb97eb75c20ab7cdc555099838ac2c8eb34daa` |
| `refactor_symbol_graph_genvars_invalid/rtl/macro.sv` | 181 | `039aa722eb1068d000f08e8fa524ddecfa8968beac0ef9ffaef543be01bed955` |
| `refactor_symbol_graph_genvars_invalid/rtl/macro_reference.sv` | 203 | `64cb9cabe9428dd88e031320fe026e65e508b66274c2614b823a4f30112c3098` |

## 4. 主 Agent 预检事实

T073 正例：

```text
catalog/top overlay parse/semantic: 0/0 + 0/0
owners:
  t073_macro_target            module:rtl/macro_design.sv:263:280
  t073_macro_owner             module:rtl/macro_design.sv:447:463
  t073_macro_statement_owner   module:rtl/macro_design.sv:945:971
  t073_sibling                 module:rtl/sibling.sv:7:19
  t073_top                     module:rtl/top.sv:7:15
all owners are in selected-top closure
Yosys identity preflight: PASS, top=t073_top, seq=5
```

当前 graph：

```text
SYMBOL_GRAPH_UNSUPPORTED_SOURCE
semantic location is generated by a macro
file: None
start: 0
```

冻结 PySlang API 事实：

```text
SourceManager:
  isMacroLoc(location)
  getFullyExpandedLoc(location)
  getFullyOriginalLoc(location)
  getMacroName(location)

macro_state declaration:
  semantic location is macro-backed
  getFullyExpandedLoc maps to the invocation inside t073_macro_owner
  no independently writable declaration token exists

macro signal reference:
  NamedValueExpression.symbol is the exact target
  syntax start is macro-backed

register/assert macro semantic nodes:
  macro-backed locations
  getFullyExpandedLoc maps each invocation into t073_macro_owner or
  t073_macro_statement_owner

macro module type:
  InstanceSymbol.definition.name == t073_macro_target
  InstanceSymbol.location and instance-name syntax are physical
  hierarchy type token is macro-backed
```

`getFullyExpandedLoc()` 只允许证明 macro invocation 所在的普通物理 module owner；它不是
可编辑 token range。`getFullyOriginalLoc()` 也不得被当作 rewrite range，因为它可能指向宏
argument 或宏 definition，而不是语义 occurrence 的独立物理 token。

## 5. 最小实现合同

### 5.1 普通物理 owner 发现

只允许从已有 semantic compilation 和 `SourceCatalog.modules` 推导：

1. 宏 location 必须由 `SourceManager.isMacroLoc()` 明确识别；
2. `getFullyExpandedLoc()` 必须映射到 SourceSet physical file；
3. expanded location 必须唯一落入一个 source-backed `ModuleDeclarationSyntax` span；
4. span 必须唯一包含同一个 ordinary `ModuleOwner` declaration，不能包含其他 module owner；
5. 同一 owner 重复发现必须得到相同 span；
6. macro-backed register/assert 即使不产生 SourceSymbol，也必须触发 owner quarantine。

禁止用 file name、module name、macro name、raw spelling、下一个 module 或 `endmodule`
文本扫描猜 owner。

### 5.2 宏 declaration 与 occurrence

- macro-backed declaration 没有独立可写 token：不建立 record；
- macro-backed occurrence 没有独立可写 token：不加入 occurrence；
- 不得将 invocation argument、macro definition token 或 fully-original location 伪装成该语义
  occurrence 的 rewrite range；
- 已有普通物理 declaration/occurrence 路径保持原样；
- “跳过宏 range”只在已成功证明并登记 quarantine owner 后允许；不得捕获
  `SymbolGraphError` 后继续。

### 5.3 semantic target 与跨 owner 保护

宏 occurrence 必须保留 semantic target 证明：

- ordinary signal/parameter/genvar reference 使用其 semantic symbol；
- macro module-type 使用 `InstanceSymbol.definition` 与 existing module record 的 declaration
  identity；
- reference owner 与 target owner 不同且 target 是普通物理 `ModuleOwner` 时，两者都加入
  macro quarantine；
- target 无法精确绑定、target owner 不唯一、或 semantic target 与物理 record 不一致时
  `SYMBOL_GRAPH_UNSUPPORTED_REFERENCE` / `SYMBOL_GRAPH_OWNER_MISMATCH` fail-closed。

不得按 target spelling 搜索源码或 module registry。

### 5.4 module-span quarantine

扩展 T071/T072 已有私有 owner-quarantine helper。所有 collector 完成后：

```text
if symbol declaration is wholly contained in a proven macro module span:
    support = unsupported
    reason = owner_contains_macro_source
```

这必须覆盖 module-owned symbol 和 generate-scope symbol。跨 owner target 使用其同样精确的
module span。一个 declaration 落入多个 span，或同一 owner 同时要求不同 T071/T072/T073
reason 时必须 fail-closed，不得定义隐式优先级。

### 5.5 明确禁止

- 展开、修改或复制宏文本；
- 把 macro argument token 当作语义生成 token 改名；
- 只保护单个 symbol 而部分改名 owner；
- 根据 fixture/module/macro 名或固定 offset 控制产品行为；
- 捕获宏 location 异常后无 owner/target 证据继续；
- 为宏生成 module definition name 构造 owner；
- 新增公开 API、schema、category、CLI、宽松模式或第二套 collector；
- 修改 mapping、rewrite、restore 或 Formal；
- 改变 T069 sized-cast、T070 keyword cast、T071 type/defparam、T072 nested-generate 语义。

## 6. 冻结修复后 oracle

### 6.1 T073 正例 graph

```text
symbols/declarations/occurrences/total_ranges: 31/31/41/72
```

恰好 17 symbols：

```text
support=unsupported
reason=owner_contains_macro_source
```

owner 集合：

```text
t073_macro_target: 4
  module + 2 ports + target_state
t073_macro_owner: 8
  module + 3 ports + ref_state + reg_q + target_o + u_target
t073_macro_statement_owner: 5
  module + 3 ports + reg_q
```

以下宏生成对象/range 必须缺席：

```text
macro_state declaration and all macro_state symbol occurrences
macro signal-reference expansion token
register/assert expansion tokens
macro module-type hierarchy occurrence token
```

`u_target` 的 physical instance declaration 保留在 graph，但因 owner quarantine 不改名。
`t073_macro_target` 因 exact semantic cross-owner target 被整体保护。

未受影响：

```text
t073_sibling: 4 eligible symbols
t073_top:
  module + 3 ports preserved/selected_top_boundary
  3 internal signals + 3 instances eligible
```

### 6.2 mapping/gate/restore

全部 19 类、全部 ABI category、确定性 NameFactory：

```text
mapping total/rename/preserve/unsupported: 31/10/4/17
modified_tokens: 23
physical files: 3
macro target/owner/statement-owner actual edits: 0
sibling actual edits: 11
selected-top internal actual edits: 12
strict compile: 0/0 + 0/0
restore: 3 files byte-identical
```

每个 actual edit 必须通过 `symbol_id` 回查 graph 分类，不接受按文本计数。

## 7. Formal

Formal 正例必须消费 `write_gate_vnext()` 的 actual renamed gate：

```text
top: t073_top
seq: 5
actual edits: 23
exit: 0
JSON formal_equivalence=pass
```

固定功能负例：复制 actual gate，在 gate 的 `rtl/top.sv` 中唯一的
`assign data_o = ` 后插入一个 ASCII `~`。negative gate strict compile 仍为
`0/0 + 0/0`；Formal 必须非 0，并包含 `unproven` 和 `equiv_status -assert`。

## 8. 目标测试

新增 `tests/test_t073_macro_owner.py`，恰好 8 tests：

1. catalog/top overlay `0/0 + 0/0` 且 graph 不重建 semantic view；
2. graph 精确 `31/31/41/72`，17-symbol owner quarantine 集合与 macro range 缺席精确；
3. standalone register/assert-only owner 被隔离，macro cross-target owner 同时被隔离，
   `u_target` physical declaration 保留；
4. sibling/top 分类不受影响；宏生成 module definition name 继续以冻结
   `CATALOG_RANGE_INVALID` fail-closed；
5. mapping `31/10/4/17`，逐个 actual edit `symbol_id` 证明 23 edits：
   protected 0、sibling 11、top 12；
6. actual gate strict compile 与 3-file byte-identical restore；
7. actual renamed gate Formal 正例；
8. 固定 `~` marker 唯一、negative strict compile 通过且 Formal 按预期失败。

迁移六项既有 macro tests，保持总测试数不变。第一条验收命令最终：

```text
Ran 63 tests
OK
```

## 9. 允许修改的文件

子 Agent 只允许修改：

```text
rtl_obfuscator/symbol_graph.py
tests/test_symbol_graph_signals.py
tests/test_symbol_graph_parameters.py
tests/test_symbol_graph_genvars.py
tests/test_t073_macro_owner.py
docs/development/future_work.md
docs/tasks/T073_macro_backed_module_owner_preserve.md
```

全部 fixture 只读。`future_work.md` 只允许把已有 ordinary physical ModuleOwner 的 macro
declaration/reference/register/assert 从 whole-graph failure 更新为 T073 owner safe-preserve；
宏生成 module definition name 必须继续列为 unsupported。

## 10. 不包含

- 宏定义/调用 rewrite 或预展开输出；
- 宏生成 module definition name；
- 无普通物理 ModuleOwner 的 declaration；
- package/class/interface/program scope 宏；
- `include`、条件编译、macro argument rename；
- 跨 module hierarchical signal reference 的新支持；
- project-root/filelist 构建适配；
- API/schema/CLI/report version 变化；
- RISC-V-Vector 或真实仓库复测；
- T074 合同或实现。

## 11. 子 Agent 执行规范

1. 第一条命令必须是 `git status --short --branch`；
2. 完整阅读 `AGENTS.md`、本合同、`docs/tasks/README.md`、
   `refactor_subagent_protocol.md`、三模式架构第 2–5 节和 `formal_verification.md`；
3. 校验 HEAD、唯一 READY 任务和全部 18 个 fixture hash；
4. 编辑前先把本合同状态改为 `IN_PROGRESS` 并填写启动记录；
5. 只运行第 12 节第一条命令作为 baseline；预期 55 个既有 tests 通过，新模块
   `ModuleNotFoundError`，`Ran 56 tests`、exit 非 0；
6. 先写/迁移冻结测试，再实现最小 macro owner quarantine；
7. 普通任务内实现、测试和 Formal 问题一次修完；
8. 完成后填写 graph/mapping/gate/restore/Formal 正负证据，设置
   `READY_FOR_REVIEW`；
9. 不 commit/push/stage，不设置 `ACCEPTED`，不创建 T074。

## 12. 唯一验收命令

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_symbol_graph_signals tests.test_symbol_graph_parameters tests.test_symbol_graph_genvars tests.test_vnext_category_closure tests.test_t073_macro_owner -v
conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/symbol_graph.py tests/test_symbol_graph_signals.py tests/test_symbol_graph_parameters.py tests/test_symbol_graph_genvars.py tests/test_t073_macro_owner.py
git diff --check HEAD
rg -x -- '- 状态：`READY_FOR_REVIEW`' docs/tasks/T073_macro_backed_module_owner_preserve.md
```

不得运行 blanket discovery 或 RISC-V-Vector。

## 13. 停止条件

只有以下情况停止并记录：

- fixture hash 或 PySlang API 与冻结事实不同；
- macro expanded location 无法唯一映射到普通物理 owner/exact module span；
- macro semantic target 不存在、不唯一或与物理 declaration identity 冲突；
- macro target owner 与 reference owner 的保护不能原子完成；
- module spans 重叠或与 T071/T072 reason 冲突；
- 需要修改允许文件外内容、公开 API/schema 或通用 fallback；
- protected owner 产生 edit，或 sibling/top internal 被误 quarantine；
- actual renamed gate strict compile、restore 或 Formal 无法在本任务范围内通过。

宏生成 module definition name 按第 3.2 节稳定失败不是阻塞，而是本任务明确保留的边界。

## 14. 执行记录

启动时填写：

```text
status: IN_PROGRESS
starting_head: ef20c6d7a861ea7602260012406ace0d857b0b45
first_command: git status --short --branch
branch: main...origin/main
staged_changes: none
inherited_worktree: main-agent frozen untracked T073 contract and read-only fixture inputs only
fixture_hash_check: all 18 fixture hashes matched the frozen oracle
baseline: acceptance command 1; Ran 56 tests, 55 passed, 1 expected import error for missing tests.test_t073_macro_owner (ModuleNotFoundError), exit 1
```

完成时填写：

```text
status: READY_FOR_REVIEW
changed_files:
  rtl_obfuscator/symbol_graph.py
  tests/test_symbol_graph_signals.py
  tests/test_symbol_graph_parameters.py
  tests/test_symbol_graph_genvars.py
  tests/test_t073_macro_owner.py
  docs/development/future_work.md
  docs/tasks/T073_macro_backed_module_owner_preserve.md
commands:
  1. conda run -n rtl_obfuscation python -m unittest tests.test_symbol_graph_signals tests.test_symbol_graph_parameters tests.test_symbol_graph_genvars tests.test_vnext_category_closure tests.test_t073_macro_owner -v
  2. conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/symbol_graph.py tests/test_symbol_graph_signals.py tests/test_symbol_graph_parameters.py tests/test_symbol_graph_genvars.py tests/test_t073_macro_owner.py
  3. git diff --check HEAD
  4. rg -x -- '- 状态：`READY_FOR_REVIEW`' docs/tasks/T073_macro_backed_module_owner_preserve.md
results:
  1. exit 0; Ran 63 tests; OK
  2. exit 0
  3. exit 0
  4. exit 0 after this status update
context_reset: forced mid-graph SymbolGraphError was followed by a clean graph build in the existing first T073 test; the wrapper finally cleared private macro evidence and the clean graph passed
graph_oracle: 31/31/41/72; 17 owner-quarantined symbols; macro-generated declaration/reference/register/assert/hierarchy ranges absent
macro_owner: t073_macro_target=4, t073_macro_owner=8, t073_macro_statement_owner=5, all unsupported/owner_contains_macro_source
macro_ranges: macro_state declaration and macro expansion ranges absent; physical u_target instance declaration retained and quarantined
semantic_target: macro module-type InstanceSymbol.definition was converted by _module_definition_key to an exact SourceCatalog ModuleOwner declaration key; target_record.declaration and target_record.owner matched that ordinary module owner; reference owner and target owner both quarantined; interface, missing-key and owner/record mismatch fail-closed; macro module definition name remains catalog fail-closed
legacy_migrations: six T040/T041/T042 macro tests migrated to safe_preserve; frozen audits 1/1/0/1, 2/2/1/3, 2/2/0/2, 3/3/0/3, 3/3/0/3, 4/4/3/7 passed
mapping_oracle: 31/10/4/17
actual_edits: 23; protected=0, sibling=11, selected-top internal=12; every edit checked by symbol_id
strict_compile: catalog/top overlay 0/0 + 0/0
restore: 3 physical files byte-identical
formal_positive: exit 0; gold=filelist tests/fixtures/t073_macro_owner/design.f; gate=actual write_gate_vnext gate; top=t073_top; seq=5; JSON formal_equivalence=pass
formal_negative: exit 1; copied actual gate with one '~' after the unique top assign marker; strict compile 0/0 + 0/0; output contained unproven and equiv_status -assert
boundaries: no macro text expansion/rewrite; macro-generated module definition name remains CATALOG_RANGE_INVALID; no include/conditional/macro-argument or package/class/interface macro support
review_request: minimal rework complete; exact module-owner identity and all-exit ContextVar reset independently reviewable
```

## 15. Luna 子 Agent 启动指令

```text
你是 T073 实现子 Agent，模型为 gpt-5.6-luna，reasoning=xhigh。
工作目录：/Users/lufengchi/Desktop/workspace/rtl_obfuscation

唯一任务：执行 docs/tasks/T073_macro_backed_module_owner_preserve.md。

第一条命令必须是 git status --short --branch。完整阅读 AGENTS.md、T073 合同、
docs/tasks/README.md、refactor_subagent_protocol.md、three_mode_refactor_plan.md 第2—5节和
formal_verification.md。确认 HEAD=ef20c6d7a861ea7602260012406ace0d857b0b45、T073 是唯一
READY、18 个 fixture hash 全部匹配。编辑前先把 T073 状态设为 IN_PROGRESS 并填写启动记录。

只允许修改 symbol_graph.py、三个既有 macro 测试模块、test_t073_macro_owner.py、
future_work.md 和 T073 合同；全部 fixture 只读。只用 macro location +
getFullyExpandedLoc 证明普通物理 owner，不能把 expanded/original location 当 rewrite range。
macro semantic target 必须精确；跨 owner target 与 reference owner 原子保护。宏生成 range
缺席，已物理收集 symbol 由 exact module span 统一 unsupported。不得文本搜索、宏展开、
异常捕获后继续、部分改名或为宏生成 module definition name 构造 owner。

只运行合同第12节四条验收命令。完成后记录 actual gate strict compile、逐文件 restore、
Formal 正例和固定功能负例，并设置 READY_FOR_REVIEW 后停止。不得 stage/commit/push、
设置 ACCEPTED、创建 T074、运行 blanket discovery 或 RISC Formal。
```

## 16. 主 Agent 独立验收

```text
status: ACCEPTED
accepted_on: 2026-07-31
accepted_head_before_commit: ef20c6d7a861ea7602260012406ace0d857b0b45
scope_review: PASS; only the seven allowed implementation/test/documentation files changed, while all 18 frozen fixtures remained byte/hash identical
implementation_review: PASS; macro ownership uses isMacroLoc plus fully-expanded invocation containment in exact semantic module spans; generated ranges are omitted only after owner evidence exists; physical declarations remain auditable; final span quarantine covers module and nested scope symbols without macro text rewrite or source spelling search
semantic_target_review: PASS; macro hierarchy targets use InstanceSymbol.definition through _module_definition_key and exact SourceCatalog ModuleOwner declaration/owner identity; interface, missing-key and mismatched targets fail closed
context_cleanup_review: PASS; build_symbol_graph clears private ContextVar evidence in a finally block on success and all failure exits; the existing first T073 test forces a mid-graph error before rebuilding the clean graph
fixture_hashes: PASS; all six T073 files and twelve migrated T040/T041/T042 macro files match section 3.4
target_tests: exit 0; Ran 63 tests; OK
py_compile: exit 0
diff_check: exit 0
ready_for_review_guard: exit 0 before acceptance
graph_oracle: PASS; 31/31/41/72
macro_quarantine: PASS; t073_macro_target=4, t073_macro_owner=8 and t073_macro_statement_owner=5, all unsupported/owner_contains_macro_source
macro_ranges: PASS; macro_state declaration and all generated declaration/reference/register/assert/hierarchy ranges are absent; physical u_target remains present and protected
legacy_migrations: PASS; six prior whole-graph macro failures now match 1/1/0/1, 2/2/1/3, 2/2/0/2, 3/3/0/3, 3/3/0/3 and 4/4/3/7 safe-preserve audits
mapping_oracle: PASS; total/rename/preserve/unsupported 31/10/4/17
actual_edits: PASS; total 23, protected owners 0, sibling 11, selected-top internal symbols/instances 12; each edit resolved by symbol_id
strict_compile_restore: PASS; actual renamed gate 0/0 + 0/0 and all three restored files equal frozen gold bytes
formal_positive: PASS; Main-Agent actual gate /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t073-formal-positive-3g0wrviw/gate, top t073_top, seq 5, exit 0, complete JSON formal_equivalence=pass
formal_negative: PASS; Main-Agent fixed-tilde gate /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t073-formal-negative-4f2y491s/negative, strict compile 0/0 + 0/0, exit 1, assertions confirmed unproven and equiv_status -assert
macro_module_name_boundary: PASS; invalid_module_name.f remains SourceCatalog CATALOG_RANGE_INVALID and no synthetic owner is created
forbidden_runs: blanket discovery and RISC-V-Vector Formal were not run
decision: ACCEPTED
```
