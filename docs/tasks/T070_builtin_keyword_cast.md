# T070：忽略内建 keyword cast，保留 typedef cast 严格审计

- 状态：`ACCEPTED`
- 合同版本：1.0
- 设计时间：2026-07-31
- 设计负责人：主 Agent
- 实现负责人：Luna 子 Agent（`gpt-5.6-luna`，`xhigh`）
- 前置任务：T069 `ACCEPTED`，交付提交 `ef8adb4`
- 设计基线 HEAD：`ef8adb4b5c92e6e812e5c6fdff666e833959d3a4`
- 任务类型：SymbolGraph cast 分类修复；产生 rewritten RTL

## 1. 单一目标

T070 只修复一个全图审计误报：

```systemverilog
signed'(typed_value)
unsigned'(typed_value)
```

当 keyword cast 的结果被赋给 typedef 类型对象时，PySlang 会建立一个
`TypeAliasType` 外层隐式 `ConversionExpression`。该外层节点没有自己的 syntax，operand
则保留 `SignedCastExpressionSyntax`。当前 typedef cast collector 把这个外层隐式转换误当成
用户 typedef cast，随后因没有直接 identifier token 返回：

```text
SYMBOL_GRAPH_UNSUPPORTED_SOURCE:
semantic cast has no direct type identifier token
```

T070 必须根据 PySlang typed syntax 证据忽略这个 keyword-cast wrapper，同时保持：

1. `byte_t'(data_i)` 继续绑定到精确 typedef declaration；
2. 普通 `TypeAliasType` 转换缺少直接 token 且没有 keyword-cast syntax 证据时继续 fail-closed；
3. 不根据 `"signed"` / `"unsigned"` 字符串做白名单；
4. 不改变公开 API、schema、category、mapping、rewrite、restore 或 CLI。

## 2. 起始状态

```text
branch: main...origin/main
HEAD: ef8adb4b5c92e6e812e5c6fdff666e833959d3a4
staged/unstaged changes: none
main-agent frozen untracked inputs:
  docs/tasks/T070_builtin_keyword_cast.md
  tests/fixtures/t070_keyword_cast/design.f
  tests/fixtures/t070_keyword_cast/invalid_nonkeyword.f
  tests/fixtures/t070_keyword_cast/rtl/child.sv
  tests/fixtures/t070_keyword_cast/rtl/top.sv
  tests/fixtures/t070_keyword_cast/rtl/invalid_nonkeyword.sv
```

这些冻结输入由主 Agent 建立，子 Agent 全部只读。

## 3. 冻结 fixture

固定正例 top：

```text
t070_keyword_cast_top
```

固定 compile order：

```text
rtl/child.sv
rtl/top.sv
```

固定负例 top：

```text
t070_invalid_nonkeyword
```

### 3.1 SHA-256 与字节数

| file | bytes | SHA-256 |
| --- | ---: | --- |
| `design.f` | 24 | `faaff0b637929d014ba666197d6e27ad370c7a834c36715f23b7d81a579b94d3` |
| `invalid_nonkeyword.f` | 26 | `85f03bec0bbbe8c339ab5ce1103e56af211851f3a240d3c245eadb2acdbf31be` |
| `rtl/child.sv` | 442 | `d2a4452538f94ecf831ae13f35ada72d811733730e3334daeb95b4b120cc87e3` |
| `rtl/top.sv` | 264 | `3af1fbaa7a6b3d9c2333a6b1f03b59a9719a672d0a0ba053d0538f46a0ad6b94` |
| `rtl/invalid_nonkeyword.sv` | 146 | `443aa61fadea0788ed16533c05e889ef1b48cde53e2c9c8575859edfc53e7682` |

## 4. 主 Agent 预检事实

正例 catalog 与 top overlay：

```text
parse/semantic: 0/0 + 0/0
Verible: PASS
Icarus -g2012: PASS
Yosys identity baseline: PASS, top=t070_keyword_cast_top, seq=5
```

固定 semantic API：

```text
byte_t'(data_i):
  ConversionExpression.type = TypeAliasType
  syntax = CastExpressionSyntax
  syntax.left = IdentifierNameSyntax
  direct token = byte_t at rtl/child.sv:251

signed'(typed_value):
  physical conversion syntax = SignedCastExpressionSyntax at rtl/child.sv:291

unsigned'(typed_value):
  physical conversion syntax = SignedCastExpressionSyntax at rtl/child.sv:338

keyword wrapper that currently fails:
  ConversionExpression.type = TypeAliasType
  syntax = None
  operand = ConversionExpression
  operand.syntax = SignedCastExpressionSyntax
```

固定非 keyword 负例：

```text
ConversionExpression.type = TypeAliasType
syntax = None
operand = IntegerLiteral
operand.syntax = IntegerVectorExpressionSyntax
expected after T070:
  SYMBOL_GRAPH_UNSUPPORTED_SOURCE
  semantic cast has no direct type identifier token
```

当前正例同样在 graph 阶段返回上述错误；没有 mapping 或 gate。

## 5. 允许的最小实现

只修改现有 typedef cast collector 的 typed decision：

1. 如果 `ConversionExpression.type` 不是 `TypeAliasType`，保持现有行为；
2. 如果自身是带 direct `IdentifierNameSyntax` 的 `CastExpressionSyntax`，保持现有 typedef
   occurrence 收集；
3. 如果外层 conversion 没有 syntax，但 operand 的 syntax 精确为
   `SignedCastExpressionSyntax`，将其识别为 builtin keyword-cast wrapper 并忽略；
4. 如果自身 syntax 精确为 `SignedCastExpressionSyntax`，同样忽略；
5. 其余 `TypeAliasType` conversion 缺少 direct token 时仍返回现有稳定错误。

禁止：

- 按 `signed` / `unsigned` 文本比较；
- 忽略所有 `syntax=None` conversion；
- 捕获 `SymbolGraphError` 后继续；
- 搜索 syntax subtree 猜 token；
- 新增第二套 cast collector；
- 修改 T069 sized-cast parameter 逻辑。

## 6. 冻结修复后 oracle

正例 SymbolGraph：

```text
symbols/declarations/occurrences/total_ranges: 12/12/21/33
keyword cast symbols/occurrences: 0/0
byte_t declaration: rtl/child.sv:121
byte_t occurrences: starts 134, 158, 183, 251
semantic_cast_type occurrence: exactly rtl/child.sv:251
```

全部 19 类、全部 ABI category、确定性 NameFactory：

```text
mapping total/rename/preserve/unsupported: 12/9/3/0
modified_tokens: 28
physical files: 2
strict compile: 0/0 + 0/0
restore: 2 files byte-identical
keyword source ranges 291 and 338: no edit
```

Formal 正例必须消费 `write_gate_vnext()` 的 actual renamed gate：

```text
top: t070_keyword_cast_top
seq: 5
exit: 0
JSON formal_equivalence=pass
```

固定功能负例：复制 actual gate，在 `rtl/top.sv` 唯一的
`assign data_o = ` 后插入一个 ASCII `~`；negative gate strict compile 仍为 0/0 + 0/0，
Formal 必须非 0，并包含 `unproven` 和 `equiv_status -assert`。

## 7. 目标测试

新增 `tests/test_t070_keyword_cast.py`，恰好 8 tests：

1. catalog/top overlay 0/0，且 graph 不重建 semantic view；
2. graph 精确为 `12/12/21/33`，keyword ranges 不属于任何 symbol；
3. `byte_t` declaration、四个 occurrences 和 `semantic_cast_type` 精确；
4. `invalid_nonkeyword.f` 继续返回冻结错误；
5. mapping 为 `12/9/3/0`、28 edits，keyword ranges 无 edit；
6. actual gate strict compile 通过并恢复 2 文件 byte-identical；
7. actual renamed gate Formal 正例通过；
8. 固定 `~` gate strict compile 通过且 Formal 按预期失败。

与 `tests.test_vnext_category_closure` 的 8 tests 合计：

```text
Ran 16 tests
OK
```

## 8. 允许修改的文件

子 Agent 只允许修改：

```text
rtl_obfuscator/symbol_graph.py
tests/test_t070_keyword_cast.py
docs/development/future_work.md
docs/tasks/T070_builtin_keyword_cast.md
```

其余文件全部禁止修改。fixture 全部只读。

`future_work.md` 只允许增加 T070 已忽略 builtin keyword cast 的状态；不得改写其他边界。

## 9. 不包含

- sized-cast parameter 新行为；
- type parameter、defparam、nested generate 或宏来源 preserve；
- typedef/package/provider 新算法；
- project-root/filelist 构建适配；
- API/schema/CLI/report version 变化；
- RISC-V-Vector 或真实仓库复测；
- T071 合同或实现。

## 10. 子 Agent 执行规范

1. 第一条命令必须是 `git status --short --branch`；
2. 完整阅读 `AGENTS.md`、本合同、`refactor_subagent_protocol.md`、三模式架构第 2–5 节和
   `formal_verification.md`；
3. 校验 HEAD、唯一 READY 任务和五个 fixture hash；
4. 修改实现或测试前，先将本合同状态改为 `IN_PROGRESS` 并填写启动记录；
5. 只运行第 11 节第一条命令作为 baseline；预期 8 个既有 tests 通过，新模块
   `ModuleNotFoundError`，Ran 9，exit 非 0；
6. 先写 8 项黑盒测试，再实现最小 typed syntax 分支；
7. 普通任务内失败一次修完；
8. 完成后填写实际 graph/mapping/gate/restore/Formal 正负证据，设置
   `READY_FOR_REVIEW`；
9. 不 commit/push/stage，不设置 `ACCEPTED`，不创建 T071。

## 11. 唯一验收命令

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_vnext_category_closure tests.test_t070_keyword_cast -v
conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/symbol_graph.py tests/test_t070_keyword_cast.py
git diff --check HEAD
rg -x -- '- 状态：`READY_FOR_REVIEW`' docs/tasks/T070_builtin_keyword_cast.md
```

不得运行 blanket discovery 或 RISC-V-Vector。

## 12. 停止条件

只有以下情况停止并记录：

- fixture hash 或 PySlang API 与冻结事实不同；
- 修复需要允许文件外变化、公开 API/schema 或通用 fallback；
- typedef cast 无法保持精确 declaration identity；
- keyword wrapper 无法用 typed syntax 与普通缺 token conversion 区分；
- actual renamed gate strict compile、restore 或 Formal 无法在本任务范围内通过。

## 13. 执行记录

```text
status: READY_FOR_REVIEW
starting_head: ef8adb4b5c92e6e812e5c6fdff666e833959d3a4
first_command: git status --short --branch
branch: main...origin/main
staged_changes: none
inherited_worktree: T070 contract and tests/fixtures/t070_keyword_cast/** were pre-existing untracked frozen inputs; no other inherited changes
fixture_hash_check: five fixture files matched the frozen byte counts and SHA-256 values in section 3
baseline: exit 1; `Ran 9 tests`, the 8 existing closure tests passed, and the new module was absent with ModuleNotFoundError
start_record: 2026-07-31; status was READY, T070 was the unique active task, and AGENTS.md, this contract, docs/tasks/README.md, refactor_subagent_protocol.md, three_mode_refactor_plan.md sections 2-5, and formal_verification.md were read
allowed_files: rtl_obfuscator/symbol_graph.py; tests/test_t070_keyword_cast.py; docs/development/future_work.md; docs/tasks/T070_builtin_keyword_cast.md
changed_files: rtl_obfuscator/symbol_graph.py; tests/test_t070_keyword_cast.py; docs/development/future_work.md; docs/tasks/T070_builtin_keyword_cast.md
commands:
  1. `conda run -n rtl_obfuscation python -m unittest tests.test_vnext_category_closure tests.test_t070_keyword_cast -v`
  2. `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/symbol_graph.py tests/test_t070_keyword_cast.py`
  3. `git diff --check HEAD`
  4. `rg -x -- '- 状态：`READY_FOR_REVIEW`' docs/tasks/T070_builtin_keyword_cast.md`
results: final target command exit 0, `Ran 16 tests`, `OK`; py_compile exit 0; diff check exit 0; final status guard exit 0 after this status transition
graph_oracle: catalog/top overlay compile `0/0 + 0/0`; graph `symbols/declarations/occurrences/total_ranges = 12/12/21/33`; keyword ranges at rtl/child.sv:291 and :338 have no symbol owner
typedef_cast: `byte_t` declaration rtl/child.sv:121; occurrences start at 134, 158, 183, 251; the occurrence at 251 has provenance `semantic_cast_type`; declaration identity remains exact
keyword_cast: typed `SignedCastExpressionSyntax` nodes and the syntax-less `TypeAliasType` wrapper over a `ConversionExpression` operand with that exact syntax are ignored; no signed/unsigned text whitelist and no broad syntax=None ignore were added
negative_nonkeyword: invalid_nonkeyword.f still raises `SYMBOL_GRAPH_UNSUPPORTED_SOURCE` with `semantic cast has no direct type identifier token`
mapping_oracle: total/rename/preserve/unsupported `12/9/3/0`; 9 renamed declarations plus 19 renamed occurrences produce 28 edits; keyword starts 291 and 338 produce no edit
strict_compile: actual renamed gate write passed with catalog/top overlay parse and semantic errors `0/0 + 0/0`
restore: actual gate restored 2 files; restored manifest matched input and bytes were identical
formal_positive: formal_verification PASS; gold `tests/fixtures/t070_keyword_cast/design.f` with root `tests/fixtures/t070_keyword_cast`; gate `/private/tmp/t070-formal-7hjw87ie/gate/design.f` with root `/private/tmp/t070-formal-7hjw87ie/gate`; top `t070_keyword_cast_top`; seq `5`; command was the target unittest command above, whose test invoked `sys.executable scripts/formal_equivalence.py --gold-filelist ... --gold-root ... --gate-filelist ... --gate-root ... --top t070_keyword_cast_top --seq 5`; exit 0; JSON `{"formal_equivalence":"pass","gate":"/private/tmp/t070-formal-7hjw87ie/gate","gold":"/Users/lufengchi/Desktop/workspace/rtl_obfuscation/tests/fixtures/t070_keyword_cast","seq":5,"top":"t070_keyword_cast_top"}`
formal_negative: actual gate copied to `/private/tmp/t070-negative-4z014632/negative`, unique `assign data_o = ` was prefixed with one ASCII `~`; strict compile remained `0/0 + 0/0`; Formal exit 1 and output contained `unproven` and `equiv_status -assert`
boundaries: no coverage added for section 9 exclusions such as sized-cast parameter behavior, type parameters, defparam, nested/conditional generate, macros, packages/providers, project-root adaptation, RISC-V-Vector, or real-repository regression; no cleanup candidates
review_request: Main Agent may independently rerun all four frozen commands and inspect the four changed files; this sub-agent did not stage, commit, push, set ACCEPTED, or create T071
```

## 14. Luna 子 Agent 启动指令

```text
你是 T070 实现子 Agent，模型为 gpt-5.6-luna，reasoning=xhigh。
工作目录：/Users/lufengchi/Desktop/workspace/rtl_obfuscation

唯一任务：执行 docs/tasks/T070_builtin_keyword_cast.md。

第一条命令必须是 git status --short --branch。完整阅读 AGENTS.md、T070 合同、
refactor_subagent_protocol.md、three_mode_refactor_plan.md 第2—5节和 formal_verification.md。
确认 HEAD=ef8adb4b5c92e6e812e5c6fdff666e833959d3a4、T070 是唯一 READY、fixture hash 全部匹配。
编辑前先把 T070 状态设为 IN_PROGRESS 并填写启动记录。

只允许修改 symbol_graph.py、test_t070_keyword_cast.py、future_work.md 和 T070 合同。
所有 T070 fixture 只读。先写合同规定的 8 项黑盒测试，再实现 typed
SignedCastExpressionSyntax keyword-wrapper 忽略；不得按字符串白名单、不得忽略全部
syntax=None、不得改变普通 typedef cast 或 T069。

只运行合同第11节四条验收命令。完成后记录实际证据并设置 READY_FOR_REVIEW 后停止。
不得 stage/commit/push、设置 ACCEPTED、创建 T071、运行 blanket discovery 或 RISC Formal。
```

## 15. 主 Agent 独立验收

```text
status: ACCEPTED
accepted_on: 2026-07-31
accepted_head_before_commit: ef8adb4b5c92e6e812e5c6fdff666e833959d3a4
scope_review: PASS; only the four sub-agent allowed files changed, while the five Main-Agent-frozen fixture files remained byte/hash identical
implementation_review: PASS; the typed helper accepts only SignedCastExpressionSyntax on the conversion itself or on the operand of a syntax-less wrapper; no text whitelist, broad syntax=None fallback, public API, schema, CLI, mapping, restore, or T069 behavior changed
fixture_hashes: PASS; all five byte counts and SHA-256 values match section 3
target_tests: exit 0; Ran 16 tests; OK
py_compile: exit 0
diff_check: exit 0
ready_for_review_guard: exit 0 before acceptance
graph_oracle: PASS; 12/12/21/33, typedef cast exact at rtl/child.sv:251, keyword ranges 291 and 338 unowned
mapping_oracle: PASS; 12/9/3/0 and 28 actual edits, with no keyword-cast edit
strict_compile_restore: PASS; actual renamed gate 0/0 + 0/0 and two restored files byte-identical
formal_positive: PASS; Main-Agent gate /private/tmp/t070-formal-8h291_md/gate, top t070_keyword_cast_top, seq 5, exit 0, JSON formal_equivalence=pass
formal_negative: PASS; Main-Agent gate /private/tmp/t070-negative-spxco83c/negative, strict compile 0/0 + 0/0, exit 1, output contained unproven and equiv_status -assert
review_rework: duplicate execution-record section was returned to the same Luna agent; the final contract contains one stop-condition section and one READY_FOR_REVIEW execution record
forbidden_runs: blanket discovery and RISC-V-Vector Formal were not run
decision: ACCEPTED
```
