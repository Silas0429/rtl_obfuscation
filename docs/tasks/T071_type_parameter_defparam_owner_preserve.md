# T071：type parameter 与 defparam 物理 owner 安全保留

- 状态：`ACCEPTED`
- 合同版本：1.0
- 设计时间：2026-07-31
- 设计负责人：主 Agent
- 实现负责人：Luna 子 Agent（`gpt-5.6-luna`，`xhigh`）
- 前置任务：T070 `ACCEPTED`，交付提交 `832e551`
- 设计基线 HEAD：`832e551da63631c9fbf83384866a7f7e329f79a1`
- 任务类型：SymbolGraph owner quarantine 修复；产生 rewritten RTL

## 1. 单一目标

T071 不实现 type parameter 或 `defparam` 改名，只把两个当前 whole-graph failure 转换为
可审计的物理 module-owner 隔离：

1. 物理可定位的 module type parameter 进入现有 `parameters` category，但固定为
   `support="unsupported"`、`reason="type_parameter_not_renamed"`；
2. 该 type parameter 所属物理 module 下的其他 symbol 全部为 `unsupported`，
   `reason="owner_contains_type_parameter"`；
3. `DefParamSymbol.target` 必须精确绑定到一个物理 value parameter declaration；
4. `defparam` 所在引用 module owner 与语义目标 parameter 所属 module owner 全部为
   `unsupported`，`reason="defparam_binding_not_renamed"`；
5. 不受影响的 sibling module 和 selected top 内部对象继续产生真实 rename edits。

T071 不增加 renaming category，不改写 type parameter、`defparam` 或其 owner，不改变公开 API、
schema、CLI、mapping、rewrite、restore 或 Formal 脚本。

## 2. 起始状态

```text
branch: main...origin/main
HEAD: 832e551da63631c9fbf83384866a7f7e329f79a1
staged/unstaged changes: none
main-agent frozen untracked inputs:
  docs/tasks/T071_type_parameter_defparam_owner_preserve.md
  tests/fixtures/t071_type_parameter_defparam/design.f
  tests/fixtures/t071_type_parameter_defparam/rtl/type_owner.sv
  tests/fixtures/t071_type_parameter_defparam/rtl/defparam_target.sv
  tests/fixtures/t071_type_parameter_defparam/rtl/defparam_owner.sv
  tests/fixtures/t071_type_parameter_defparam/rtl/sibling.sv
  tests/fixtures/t071_type_parameter_defparam/rtl/top.sv
```

上述新输入由主 Agent 建立并冻结。T043 的两个既有 negative fixture 也在 T071 中转为
safe-preserve 回归，全部 fixture 对子 Agent只读。

## 3. 冻结 fixture

### 3.1 正例

```text
source root: tests/fixtures/t071_type_parameter_defparam
filelist: design.f
top: t071_top
SourceSet define: T071_TYPED_VIEW
compile order:
  rtl/type_owner.sv
  rtl/defparam_target.sv
  rtl/defparam_owner.sv
  rtl/sibling.sv
  rtl/top.sv
```

模块角色：

```text
t071_type_owner:
  physical module type parameter DATA_T
t071_defparam_owner:
  contains `defparam u_target.WIDTH = 8'h3c`
t071_defparam_target:
  physical target parameter WIDTH
t071_sibling:
  unaffected owner; must still be renamed
t071_top:
  selected top; boundary names preserved, internal signals/instances still renamed
```

### 3.2 T043 迁移 fixture

```text
tests/fixtures/refactor_symbol_graph_parameters_invalid/type_parameter.f
tests/fixtures/refactor_symbol_graph_parameters_invalid/defparam.f
```

只允许更新 `tests/test_symbol_graph_parameters.py` 中对应两项旧 whole-graph failure 断言；
其他 T043 fixture、测试与 oracle 不得改变。

### 3.3 SHA-256 与字节数

| file | bytes | SHA-256 |
| --- | ---: | --- |
| `t071_type_parameter_defparam/design.f` | 89 | `82cd02e016883420f9a8fa91ef9a0778204d9de679b778b75c013612a6da31e7` |
| `t071_type_parameter_defparam/rtl/type_owner.sv` | 470 | `f8372205c717348e1fb275e50342fbca790b9c0bed1d70c75d8aefe1e7c80854` |
| `t071_type_parameter_defparam/rtl/defparam_target.sv` | 241 | `9a72ce13eab0e7681cbb3c89246b36f65de6bc906c8a04df545213f48a330a78` |
| `t071_type_parameter_defparam/rtl/defparam_owner.sv` | 304 | `28028a56725dcbb84eb4dc1b6a611dea950399ea0cc3feaab5edb708546a9cb7` |
| `t071_type_parameter_defparam/rtl/sibling.sv` | 200 | `4e0eef54135b02805608214e435de84234ae57eef1585ce9eb2f256131677963` |
| `t071_type_parameter_defparam/rtl/top.sv` | 496 | `77eb9dda8f061597c2479dada864dc2d1bb891b22219b9995d53997b12a6c03c` |
| `refactor_symbol_graph_parameters_invalid/type_parameter.f` | 22 | `4282295b7a9c54c0ac067cc573151952f88a19be3e5f9d7412f0920d7c81de34` |
| `refactor_symbol_graph_parameters_invalid/defparam.f` | 16 | `cb7063f470ba048d0bc1d48d3127bdb3a0142fdf4aad0ae650fb2d8ca27896e3` |
| `refactor_symbol_graph_parameters_invalid/rtl/type_parameter.sv` | 92 | `2f4d9a0bd8283be0a5a9f275161e384a05ef5dcd2f72bcdb1e69b7f8037b0eb2` |
| `refactor_symbol_graph_parameters_invalid/rtl/defparam.sv` | 160 | `103ab5668ce623405c57c4d607b1a12709c4b924c612b92b8f17d33f6852f534` |

## 4. 主 Agent 预检事实

正例 catalog 与 top overlay：

```text
parse/semantic: 0/0 + 0/0
owners: type_owner, defparam_owner, defparam_target, sibling, top
all five owners are in selected-top closure
```

当前 graph 的首个错误：

```text
SYMBOL_GRAPH_UNSUPPORTED_SOURCE
module type parameter is outside T043 scope
file: rtl/type_owner.sv
start: 30
```

临时只禁用旧 T043 rejection 后，现有 collector 可完整构图：

```text
symbols/declarations/occurrences/total_ranges: 27/27/39/66
```

冻结 PySlang API：

```text
type parameter:
  node = TypeParameterSymbol
  kind = SymbolKind.TypeParameter
  name = DATA_T
  syntax = TypeAssignmentSyntax
  location = rtl/type_owner.sv:68
  declaringDefinition = t071_type_owner

defparam:
  node = DefParamSymbol
  kind = SymbolKind.DefParam
  syntax = DefParamAssignmentSyntax
  declaringDefinition = t071_defparam_owner
  target = ParameterSymbol WIDTH at rtl/defparam_target.sv:49
  target.declaringDefinition = t071_defparam_target
  syntax.name = ScopedNameSyntax
  syntax.name.right = IdentifierNameSyntax WIDTH at rtl/defparam_owner.sv:244
```

禁止从 `u_target.WIDTH` 文本猜 target。binding 证据只能来自 `DefParamSymbol.target` 的 exact
declaration identity，并由 typed syntax 的 final identifier 提供物理 occurrence。

## 5. 最小实现合同

### 5.1 type parameter

只接受同时满足以下条件的 module type parameter：

1. kind 精确为 `SymbolKind.TypeParameter`；
2. `_owner_for_module_symbol()` 唯一映射到普通物理 `ModuleOwner`；
3. `location` 非 macro，identifier bytes 与 `name` 精确一致；
4. declaring definition 精确为 module。

产生一个现有 `SourceSymbol`：

```text
category: parameters
impact: cross_module
abi: module_abi
support: unsupported
reason: type_parameter_not_renamed
occurrences: empty
```

不从 `DATA_T type_hold` 的拼写搜索或 syntax subtree 猜 type occurrence。整个 owner 隔离保证
类型传播不会形成半改名。

### 5.2 defparam

只接受同时满足以下条件的 `DefParamSymbol`：

1. 引用 owner 通过 `node.declaringDefinition` 唯一映射到物理 `ModuleOwner`；
2. `node.target` 精确为物理 module value `ParameterSymbol`；
3. target declaration key 与已有 parameter record 完全一致；
4. target owner 通过 `target.declaringDefinition` 唯一映射到物理 `ModuleOwner`；
5. `DefParamAssignmentSyntax.name` 的 typed final `IdentifierNameSyntax` token 与 target name、
   location 和 source bytes 完全一致，且不是 macro location。

该 final token 作为 target parameter 的一个 occurrence：

```text
provenance: defparam_binding
range: rtl/defparam_owner.sv:244..249
```

任何 target 缺失、非 parameter、非物理 declaration、owner 不唯一、typed final token 缺失、
token/target 不一致或 macro location 均保持原子 fail-closed；不得异常捕获后继续。

### 5.3 owner quarantine

只新增私有 owner-quarantine helper，在所有现有 collector 完成后按精确 `owner_id` 转换
`SourceSymbol`：

```text
type parameter owner:
  DATA_T itself -> type_parameter_not_renamed
  every other symbol -> owner_contains_type_parameter

defparam reference owner:
  every symbol -> defparam_binding_not_renamed

defparam target owner:
  every symbol -> defparam_binding_not_renamed
```

转换只使用现有 `support/reason` 字段和 `dataclasses.replace` 或等价私有实现，不增加 schema。
不同 quarantine 原因落到同一 owner、或同一物理 token 绑定到不同 target 时必须 fail-closed，
不得自行定义优先级。

禁止：

- 以 module/name/file 字符串匹配控制产品行为；
- 搜索源码猜 `defparam` target；
- 只保留 parameter 而继续改写同 owner 其他 symbol；
- 改写 type parameter、`defparam` token 或 protected owner 的任一 range；
- 新增公开 API、category、schema、CLI、宽松模式或第二套 collector；
- 修改 T069/T070、mapping、rewrite、restore 或 Formal。

## 6. 冻结修复后 oracle

### 6.1 正例 graph

```text
symbols/declarations/occurrences/total_ranges: 28/28/40/68
```

type owner 恰好 5 symbols：

```text
DATA_T:
  category=parameters
  declaration=rtl/type_owner.sv:68..74
  support=unsupported
  reason=type_parameter_not_renamed
other 4:
  module t071_type_owner
  ports data_i/data_o
  signal type_hold
  support=unsupported
  reason=owner_contains_type_parameter
```

defparam reference owner 恰好 5 symbols、target owner 恰好 5 symbols，全部：

```text
support=unsupported
reason=defparam_binding_not_renamed
```

`WIDTH`：

```text
declaration: rtl/defparam_target.sv:49..54
occurrences:
  rtl/defparam_owner.sv:244..249 provenance=defparam_binding
  rtl/defparam_target.sv:191..196 provenance=semantic_expression
```

unaffected：

```text
t071_sibling owner: 4 eligible symbols
t071_top: module + 2 ports preserved selected_top_boundary
t071_top: 3 internal signals + 3 instances eligible
```

### 6.2 T043 迁移 oracle

`type_parameter.f`：

```text
symbols/declarations/occurrences/total_ranges: 3/3/0/3
T parameter -> unsupported/type_parameter_not_renamed
module + value signal -> unsupported/owner_contains_type_parameter
```

`defparam.f`：

```text
symbols/declarations/occurrences/total_ranges: 4/4/2/6
both owners and all 4 symbols -> unsupported/defparam_binding_not_renamed
WIDTH has rtl/defparam.sv:139 defparam_binding occurrence
```

### 6.3 mapping/gate/restore

全部 19 类、全部 ABI category、确定性 NameFactory：

```text
mapping total/rename/preserve/unsupported: 28/10/3/15
modified_tokens: 23
physical files: 5
protected-owner edits: 0
t071_sibling edits: 11
t071_top internal signal/instance edits: 12
strict compile with T071_TYPED_VIEW: 0/0 + 0/0
restore: 5 files byte-identical
```

## 7. Formal 特殊视图与非 vacuous 要求

当前 Conda Yosys 0.53 对 `parameter type` 返回：

```text
syntax error, unexpected TOK_ID
```

因此 `rtl/type_owner.sv` 冻结为两个预处理视图：

1. SourceSet/strict gate 使用 `T071_TYPED_VIEW`，PySlang 实际编译真实 type parameter；
2. `scripts/formal_equivalence.py` 不带该 define，Yosys 读取同一 gold/gate 文件中的等价
   synthesizable fallback。

不得修改 fixture、Formal 脚本或证明强度。Formal 仍必须消费 `write_gate_vnext()` 的 actual
renamed gate：sibling 与 selected-top 内部共有 23 个真实 edits，因此不是 identity/copy-gold。

Formal 正例：

```text
top: t071_top
seq: 5
exit: 0
JSON formal_equivalence=pass
```

固定功能负例：复制 actual gate，在 `rtl/top.sv` 唯一的 `assign data_o = ` 后插入一个 ASCII
`~`。negative gate 以 `T071_TYPED_VIEW` strict compile 仍为 `0/0 + 0/0`；Formal 必须非 0，
并包含 `unproven` 和 `equiv_status -assert`。

## 8. 目标测试

新增 `tests/test_t071_type_parameter_defparam.py`，恰好 8 tests：

1. catalog/top overlay `0/0 + 0/0` 且 graph 不重建 semantic view；
2. graph 精确为 `28/28/40/68`；
3. type parameter record 与 type owner 5-symbol quarantine 精确；
4. defparam target identity、`WIDTH` occurrence 与两个 5-symbol owner quarantine 精确；
5. mapping `28/10/3/15`、23 edits、protected owner 0 edits、sibling 11 和 top 12 edits；
6. actual gate strict compile 与 5-file byte-identical restore；
7. actual renamed gate Formal 正例；
8. 固定 `~` gate strict compile 通过且 Formal 按预期失败。

更新 `tests/test_symbol_graph_parameters.py` 中恰好两项旧断言：

- `test_type_parameter_safe_preserve` 覆盖冻结的 3-symbol safe-preserve oracle；
- `test_defparam_safe_preserve` 覆盖冻结的 4-symbol safe-preserve oracle。

第一条验收命令最终：

```text
Ran 35 tests
OK
```

## 9. 允许修改的文件

子 Agent 只允许修改：

```text
rtl_obfuscator/symbol_graph.py
tests/test_symbol_graph_parameters.py
tests/test_t071_type_parameter_defparam.py
docs/development/future_work.md
docs/tasks/T071_type_parameter_defparam_owner_preserve.md
```

所有 fixture 只读。`future_work.md` 只允许把 type parameter/`defparam` 从 whole-graph
fail-closed 更新为 T071 的物理 owner safe-preserve 边界；不得改写其他规划。

## 10. 不包含

- type parameter rename、type occurrence 收集、type override；
- `defparam` rewrite；
- package/class/interface type parameter；
- macro-backed declaration/reference；
- nested/conditional generate；
- project-root/filelist 构建适配；
- API/schema/CLI/report version 变化；
- RISC-V-Vector 或真实仓库复测；
- T072 合同或实现。

## 11. 子 Agent 执行规范

1. 第一条命令必须是 `git status --short --branch`；
2. 完整阅读 `AGENTS.md`、本合同、`docs/tasks/README.md`、
   `refactor_subagent_protocol.md`、三模式架构第 2–5 节和 `formal_verification.md`；
3. 校验 HEAD、唯一 READY 任务和十个 fixture hash；
4. 编辑前先把本合同状态改为 `IN_PROGRESS` 并填写启动记录；
5. 只运行第 12 节第一条命令作为 baseline；预期 27 个既有 tests 通过，新模块
   `ModuleNotFoundError`，`Ran 28 tests`、exit 非 0；
6. 先写/迁移冻结测试，再实现最小 semantic owner quarantine；
7. 普通任务内失败一次修完；
8. 完成后填写 graph/mapping/gate/restore/Formal 正负证据，设置 `READY_FOR_REVIEW`；
9. 不 commit/push/stage，不设置 `ACCEPTED`，不创建 T072。

## 12. 唯一验收命令

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_symbol_graph_parameters tests.test_vnext_category_closure tests.test_t071_type_parameter_defparam -v
conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/symbol_graph.py tests/test_symbol_graph_parameters.py tests/test_t071_type_parameter_defparam.py
git diff --check HEAD
rg -x -- '- 状态：`READY_FOR_REVIEW`' docs/tasks/T071_type_parameter_defparam_owner_preserve.md
```

不得运行 blanket discovery 或 RISC-V-Vector。

## 13. 停止条件

只有以下情况停止并记录：

- fixture hash 或 PySlang API 与冻结事实不同；
- exact type/defparam declaration identity 或物理 owner 无法证明；
- 同一 owner 需要两个不同 quarantine reason；
- 同一物理 `defparam` token 绑定到多个 target；
- 修复需要允许文件外变化、公开 API/schema 或通用 fallback；
- protected owner 仍产生 edit；
- actual renamed gate strict compile、restore 或 Formal 无法在本任务范围内通过。

## 14. 执行记录

启动时填写：

```text
status: IN_PROGRESS
starting_head: 832e551da63631c9fbf83384866a7f7e329f79a1
first_command: git status --short --branch
branch: main...origin/main
staged_changes: none
inherited_worktree: docs/tasks/T071_type_parameter_defparam_owner_preserve.md and tests/fixtures/t071_type_parameter_defparam/ are frozen untracked inputs; no inherited changes in implementation/test allowlist
fixture_hash_check: PASS; all ten frozen files match the contract byte counts and SHA-256 values
baseline: `conda run -n rtl_obfuscation python -m unittest tests.test_symbol_graph_parameters tests.test_vnext_category_closure tests.test_t071_type_parameter_defparam -v`; exit 1, existing 27 tests plus 1 loader error (`ModuleNotFoundError` for the not-yet-created T071 module), `Ran 28 tests`
```

完成时填写：

```text
status: READY_FOR_REVIEW
changed_files: rtl_obfuscator/symbol_graph.py; tests/test_symbol_graph_parameters.py; tests/test_t071_type_parameter_defparam.py; docs/development/future_work.md; docs/tasks/T071_type_parameter_defparam_owner_preserve.md
commands: `conda run -n rtl_obfuscation python -m unittest tests.test_symbol_graph_parameters tests.test_vnext_category_closure tests.test_t071_type_parameter_defparam -v`; `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/symbol_graph.py tests/test_symbol_graph_parameters.py tests/test_t071_type_parameter_defparam.py`; `git diff --check HEAD`; `rg -x -- '- 状态：`READY_FOR_REVIEW`' docs/tasks/T071_type_parameter_defparam_owner_preserve.md`
results: review-rework target suite exit 0, `Ran 35 tests`, `OK`; py_compile, diff check, and final status guard recorded below all exit 0
graph_oracle: PASS; `28/28/40/68`
type_parameter: PASS; physical `DATA_T` is `parameters`, `cross_module/module_abi`, `unsupported/type_parameter_not_renamed`; type owner has exactly 5 symbols and the other 4 are `owner_contains_type_parameter`
defparam_binding: PASS; `DefParamSymbol.target` binds the physical `WIDTH` declaration, final typed identifier records `rtl/defparam_owner.sv:244..249` as `defparam_binding`, and both reference/target owners have exactly 5 symbols with `defparam_binding_not_renamed`
owner_quarantine: PASS; conflicting owner reasons fail closed; protected-owner edits are 0
mapping_oracle: PASS; total/rename/preserve/unsupported `28/10/3/15`, modified tokens `23`, sibling edits `11`, selected-top internal edits `12`
strict_compile: PASS; actual renamed gate with `T071_TYPED_VIEW` has catalog/top diagnostics `0/0 + 0/0`; fixed `~` gate also strict-compiles `0/0 + 0/0`
restore: PASS; `test_actual_gate_strict_compile_and_restore` reads all 5 actual restored files and compares each to its frozen gold bytes; all equal
formal_positive: PASS; gold filelist `/Users/lufengchi/Desktop/workspace/rtl_obfuscation/tests/fixtures/t071_type_parameter_defparam/design.f`, gold root `/Users/lufengchi/Desktop/workspace/rtl_obfuscation/tests/fixtures/t071_type_parameter_defparam`, actual gate filelist `/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t071-formal-positive-4tu9fq4t/gate/design.f`, actual gate root `/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t071-formal-positive-4tu9fq4t/gate`, top `t071_top`, seq `5`; command `/Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python /Users/lufengchi/Desktop/workspace/rtl_obfuscation/scripts/formal_equivalence.py --gold-filelist /Users/lufengchi/Desktop/workspace/rtl_obfuscation/tests/fixtures/t071_type_parameter_defparam/design.f --gold-root /Users/lufengchi/Desktop/workspace/rtl_obfuscation/tests/fixtures/t071_type_parameter_defparam --gate-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t071-formal-positive-4tu9fq4t/gate/design.f --gate-root /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t071-formal-positive-4tu9fq4t/gate --top t071_top --seq 5`; exit_code `0`; JSON `{"formal_equivalence":"pass","gate":"/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t071-formal-positive-4tu9fq4t/gate","gold":"/Users/lufengchi/Desktop/workspace/rtl_obfuscation/tests/fixtures/t071_type_parameter_defparam","seq":5,"top":"t071_top"}`
formal_negative: PASS as expected negative; same exact gold root/filelist, actual fixed-`~` gate filelist `/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t071-formal-negative-pame1u_x/negative/design.f`, actual gate root `/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t071-formal-negative-pame1u_x/negative`, top `t071_top`, seq `5`; command `/Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python /Users/lufengchi/Desktop/workspace/rtl_obfuscation/scripts/formal_equivalence.py --gold-filelist /Users/lufengchi/Desktop/workspace/rtl_obfuscation/tests/fixtures/t071_type_parameter_defparam/design.f --gold-root /Users/lufengchi/Desktop/workspace/rtl_obfuscation/tests/fixtures/t071_type_parameter_defparam --gate-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t071-formal-negative-pame1u_x/negative/design.f --gate-root /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t071-formal-negative-pame1u_x/negative --top t071_top --seq 5`; exit_code `1`; negative gate strict compile `0/0 + 0/0`; output contains `unproven` and `equiv_status -assert`
boundaries: package/class/interface type parameters, macro-backed bindings, type occurrence rename, defparam rewrite, and RISC-V-Vector remain out of scope; fixtures unchanged
review_request: T071 implementation and the two authorized T043 assertion migrations are complete; ready for Main Agent independent review. No stage, commit, push, ACCEPTED, or T072 action performed.
```

## 15. Luna 子 Agent 启动指令

```text
你是 T071 实现子 Agent，模型为 gpt-5.6-luna，reasoning=xhigh。
工作目录：/Users/lufengchi/Desktop/workspace/rtl_obfuscation

唯一任务：执行 docs/tasks/T071_type_parameter_defparam_owner_preserve.md。

第一条命令必须是 git status --short --branch。完整阅读 AGENTS.md、T071 合同、
docs/tasks/README.md、refactor_subagent_protocol.md、three_mode_refactor_plan.md 第2—5节和
formal_verification.md。确认 HEAD=832e551da63631c9fbf83384866a7f7e329f79a1、T071 是唯一
READY、十个 fixture hash 全部匹配。编辑前先把 T071 状态设为 IN_PROGRESS 并填写启动记录。

只允许修改 symbol_graph.py、test_symbol_graph_parameters.py、
test_t071_type_parameter_defparam.py、future_work.md 和 T071 合同；所有 fixture 只读。
必须使用 TypeParameterSymbol/DefParamSymbol.target/typed final identifier 的 semantic identity
建立 unsupported record 与 owner quarantine，不得按源码拼写猜 target，不得部分改名或捕获异常
后继续。

只运行合同第12节四条验收命令。完成后记录 actual gate strict compile、逐字节 restore、
Formal 正例和固定功能负例，并设置 READY_FOR_REVIEW 后停止。不得 stage/commit/push、
设置 ACCEPTED、创建 T072、运行 blanket discovery 或 RISC Formal。
```

## 16. 主 Agent 独立验收

```text
status: ACCEPTED
accepted_on: 2026-07-31
accepted_head_before_commit: 832e551da63631c9fbf83384866a7f7e329f79a1
scope_review: PASS; only the five allowed implementation/test/documentation files changed, while all ten frozen fixtures remained byte/hash identical
implementation_review: PASS; type parameters require exact physical TypeParameterSymbol ownership; defparam binding uses DefParamSymbol.target plus its exact physical ParameterSymbol declaration and typed final identifier; quarantine is applied only by owner_id after normal collection; no spelling fallback, exception skip, public API, schema, category, CLI, mapping, rewrite, restore, or Formal change was added
review_rework: PASS; the same Luna agent added semantic-view reuse protection, actual RewriteExecution edit ownership checks, direct restored-byte comparison, unique negative marker validation, accurate migrated test names, and exact Formal records without changing product implementation
fixture_hashes: PASS; all six T071 files and four migrated T043 files match section 3
target_tests: exit 0; Ran 35 tests; OK
py_compile: exit 0
diff_check: exit 0
ready_for_review_guard: exit 0 before acceptance
graph_oracle: PASS; 28/28/40/68
type_parameter: PASS; DATA_T is unsupported/type_parameter_not_renamed and the other four symbols in its owner are unsupported/owner_contains_type_parameter
defparam_binding: PASS; WIDTH has the exact rtl/defparam_owner.sv:244..249 defparam_binding occurrence and both five-symbol owners are unsupported/defparam_binding_not_renamed
mapping_oracle: PASS; total/rename/preserve/unsupported 28/10/3/15
actual_edits: PASS; total 23, protected owners 0, sibling 11, selected-top internal symbols/instances 12
strict_compile_restore: PASS; actual renamed gate 0/0 + 0/0 and all five restored files equal frozen gold bytes
formal_positive: PASS; Main-Agent actual gate /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t071-formal-positive-p7rbro2e/gate, top t071_top, seq 5, exit 0, JSON formal_equivalence=pass
formal_negative: PASS; Main-Agent fixed-tilde gate /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t071-formal-negative-oe4h0mn9/negative, strict compile 0/0 + 0/0, exit 1, output contained unproven and equiv_status -assert
forbidden_runs: blanket discovery and RISC-V-Vector Formal were not run
decision: ACCEPTED
```
