# T072：nested generate 物理 module owner 安全保留

- 状态：`ACCEPTED`
- 合同版本：1.0
- 设计时间：2026-07-31
- 设计负责人：主 Agent
- 实现负责人：Luna 子 Agent（`gpt-5.6-luna`，`xhigh`）
- 前置任务：T071 `ACCEPTED`，交付提交 `b882169`
- 设计基线 HEAD：`b882169dae0d60cfc0b04721ea9c2f15973073e1`
- 任务类型：SymbolGraph owner quarantine 修复；产生 rewritten RTL

## 1. 单一目标

T072 不实现 nested generate 内部 genvar/层次对象改名，只把当前
`nested generate-for is outside T042 scope` whole-graph failure 转换为物理 module-owner
隔离：

1. 保留现有 typed `_loop_has_nested_loop()` 检测；
2. 当 nested loop 的 declaring module 能唯一映射到普通物理 `ModuleOwner`，冻结该 module
   的精确 syntax span；
3. 该物理 module span 内所有已收集 symbol 全部固定为
   `support="unsupported"`、`reason="owner_contains_nested_generate"`；
4. 内外同名 genvar 只保留各自精确物理 declaration，均不收集 occurrence，不按拼写合并；
5. 同文件 sibling、其他文件 sibling 和 selected top 内部对象继续真实改名；
6. 无法取得唯一物理 module owner/span 时保持原子 fail-closed。

T072 不增加 nested-generate renaming，不改变公开 API、schema、category、CLI、mapping、
rewrite、restore 或 Formal。

## 2. 起始状态

```text
branch: main...origin/main
HEAD: b882169dae0d60cfc0b04721ea9c2f15973073e1
staged/unstaged changes: none
main-agent frozen untracked inputs:
  docs/tasks/T072_nested_generate_owner_preserve.md
  tests/fixtures/t072_nested_generate/design.f
  tests/fixtures/t072_nested_generate/rtl/nested_and_same.sv
  tests/fixtures/t072_nested_generate/rtl/other_sibling.sv
  tests/fixtures/t072_nested_generate/rtl/top.sv
```

上述新输入由主 Agent 建立并冻结。T042 的既有 nested negative fixture 在 T072 中迁移为
safe-preserve 回归，所有 fixture 对子 Agent只读。

## 3. 冻结 fixture

### 3.1 正例

```text
source root: tests/fixtures/t072_nested_generate
filelist: design.f
top: t072_top
compile order:
  rtl/nested_and_same.sv
  rtl/other_sibling.sv
  rtl/top.sv
```

模块角色：

```text
t072_nested_owner:
  nested generate-for
  outer/inner inline genvar both named i
  named generate blocks g_outer/g_inner
t072_same_file_sibling:
  same physical file, immediately after nested owner
t072_other_sibling:
  separate physical file
t072_top:
  selected top instantiating all three owners
```

### 3.2 T042 迁移 fixture

```text
tests/fixtures/refactor_symbol_graph_genvars_invalid/nested.f
tests/fixtures/refactor_symbol_graph_genvars_invalid/rtl/nested.sv
```

只允许更新 `tests/test_symbol_graph_genvars.py` 中
`test_nested_same_named_genvars_fail_closed` 这一项旧 whole-graph failure 断言；其他 T042
fixture、测试与 oracle 不得改变。

### 3.3 SHA-256 与字节数

| file | bytes | SHA-256 |
| --- | ---: | --- |
| `t072_nested_generate/design.f` | 55 | `e4138e1448e120555b18ff0aba63ab3ade01e9ac54e6ffcd837c79354a28dd21` |
| `t072_nested_generate/rtl/nested_and_same.sv` | 573 | `1caad19ee8da71b25127149e24da26cd2263a076e92290ccbed129ec34a874a8` |
| `t072_nested_generate/rtl/other_sibling.sv` | 181 | `28a96b65b477713b037b3ee2814cd28ead2a5a1a975d863f6b32efe662042f24` |
| `t072_nested_generate/rtl/top.sv` | 461 | `a35fb65b31219a18df52b6b9f884ddace96ed12b9b8624d3f2391d95e381f319` |
| `refactor_symbol_graph_genvars_invalid/nested.f` | 14 | `e66de0cdce1d06172d7acd6c509aa24ca90ea9ed15b6c46b84b118d81386a14a` |
| `refactor_symbol_graph_genvars_invalid/rtl/nested.sv` | 195 | `79b017d27c1c70e5247eabee144c36f5b3410f6d36109c9461bdd4c2ca17e655` |

## 4. 主 Agent 预检事实

正例 catalog 与 top overlay：

```text
parse/semantic: 0/0 + 0/0
owners: nested_owner, same_file_sibling, other_sibling, top
all four owners are in selected-top closure
Yosys identity preflight: PASS, top=t072_top, seq=5
```

当前 graph：

```text
SYMBOL_GRAPH_UNSUPPORTED_REFERENCE
nested generate-for is outside T042 scope
file: rtl/nested_and_same.sv
start: 113
```

冻结 PySlang API：

```text
outer:
  LoopGenerateSyntax start=113
  GenvarSymbol i declaration=rtl/nested_and_same.sv:125..126
  GenerateBlockArraySymbol g_outer declaration=152
  declaringDefinition=t072_nested_owner

inner:
  LoopGenerateSyntax start=168
  GenvarSymbol i declaration=rtl/nested_and_same.sv:180..181
  GenerateBlockArraySymbol g_inner declaration=207
  declaringDefinition=t072_nested_owner

t072_nested_owner declaringDefinition.syntax:
  ModuleDeclarationSyntax
  physical span=rtl/nested_and_same.sv:0..395

t072_same_file_sibling:
  module identifier starts at rtl/nested_and_same.sv:404
```

现有 generate-block `SourceSymbol.owner_module` 是独立 generate scope：

```text
g_outer -> generate:rtl/nested_and_same.sv:113:306
g_inner -> generate:rtl/nested_and_same.sv:168:298
```

因此只按 `symbol.owner_module == module.owner_id` quarantine 会漏掉两个 generate block，
并产生错误 edits。T072 必须使用由 semantic declaring definition 证明的精确物理 module span；
不得用文件名、module 名或“直到下一个 module”的文本扫描猜边界。

## 5. 最小实现合同

### 5.1 nested owner 发现

保留 `_loop_has_nested_loop(loop)` 的 typed syntax 判断。对含 nested loop 的 definition：

1. genvar record 已通过 `_owner_for_signal()` 唯一映射到物理 `ModuleOwner`；
2. `record.definition` 必须通过 `_module_definition_key()` 与同一个 owner 的 declaration identity
   一致；
3. definition syntax 必须是 source-backed、同 buffer、非 macro 的精确 module span；
4. span 必须唯一包含该 module owner declaration，且不能包含其他 module owner declaration；
5. 同一 owner 重复发现必须得到完全相同的 span。

任一条件不成立，继续返回稳定 `SYMBOL_GRAPH_OWNER_MISMATCH` 或
`SYMBOL_GRAPH_UNSUPPORTED_REFERENCE`，不得忽略。

### 5.2 genvar 收集

对 nested owner：

- 仍从 semantic `GenvarSymbol.location` 建立每个独立 declaration record；
- 不执行该 owner 下任何 loop 的 `_genvar_occurrence_tokens()`；
- 外层 `i` 与内层 `i` 由 declaration `(file,start,end)` 区分；
- 两个 genvar 的 `occurrences` 都必须为空；
- 不根据 spelling、iteration parameter 或 syntax subtree 合并。

非 nested owner 的既有 T042 genvar 路径与 occurrence oracle 完全不变。

### 5.3 module-span quarantine

在所有 collector 完成后扩展现有私有 owner-quarantine 逻辑：

```text
if SourceSymbol.declaration is wholly contained in exact nested module span:
    support = unsupported
    reason = owner_contains_nested_generate
```

这必须覆盖：

- module；
- ports/signals/parameters/instances 等普通 module-owned symbol；
- 两个 genvar；
- `g_outer/g_inner` generate-block symbol，即使其 `owner_module` 是 generate scope。

一个 declaration 同时落入多个 module span、或同一 module 同时需要不同 T071/T072
quarantine reason 时必须 fail-closed，不得自行定义优先级。不得根据 occurrence 所在文件/span
改写 symbol 的 owner；只以 declaration 归属决定整个 symbol。

禁止：

- 只 quarantine genvar 而继续改写 module/generate block；
- 收集 nested owner 的 partial genvar occurrences；
- 用 rawText 同名匹配内外 `i`；
- 以 module 名、fixture 路径、固定 offset 控制产品行为；
- 用源码扫描寻找 `endmodule` 或下一个 module；
- 修改 T071 type/defparam quarantine 语义；
- 新增公开 API、schema、category、CLI、宽松模式或第二套 collector；
- 修改 mapping、rewrite、restore 或 Formal。

## 6. 冻结修复后 oracle

### 6.1 正例 graph

```text
symbols/declarations/occurrences/total_ranges: 26/26/33/59
```

nested module span 内恰好 9 symbols，全部：

```text
support=unsupported
reason=owner_contains_nested_generate
```

集合：

```text
modules: t072_nested_owner
ports: data_i, data_o
signals: owner_passthrough, lane_nested
genvars:
  i at 125..126, occurrences=0
  i at 180..181, occurrences=0
generate_blocks:
  g_outer at 152
  g_inner at 207
```

两个 genvar：

```text
symbol_id distinct
declaration distinct
same spelling i
no shared or duplicate occurrence
```

unaffected：

```text
t072_same_file_sibling: 4 eligible symbols
t072_other_sibling: 4 eligible symbols
t072_top:
  module + 2 ports preserved/selected_top_boundary
  3 internal signals + 3 instances eligible
```

### 6.2 T042 迁移 oracle

旧 `nested.f`：

```text
symbols/declarations/occurrences/total_ranges: 6/6/0/6
all 6 -> unsupported/owner_contains_nested_generate
genvar i declarations: rtl/nested.sv:38..39 and 93..94
both genvar occurrences: empty
generate blocks g_outer/g_inner: unsupported
```

### 6.3 mapping/gate/restore

全部 19 类、全部 ABI category、确定性 NameFactory：

```text
mapping total/rename/preserve/unsupported: 26/14/3/9
modified_tokens: 34
physical files: 3
nested owner actual edits: 0
same-file sibling actual edits: 11
other-file sibling actual edits: 11
selected-top internal actual edits: 12
strict compile: 0/0 + 0/0
restore: 3 files byte-identical
```

## 7. Formal

Formal 正例必须消费 `write_gate_vnext()` 的 actual renamed gate：

```text
top: t072_top
seq: 5
actual edits: 34
exit: 0
JSON formal_equivalence=pass
```

固定功能负例：复制 actual gate，在 `rtl/top.sv` 唯一的 `assign data_o = ` 后插入一个 ASCII
`~`。negative gate strict compile 仍为 `0/0 + 0/0`；Formal 必须非 0，并包含 `unproven`
和 `equiv_status -assert`。

## 8. 目标测试

新增 `tests/test_t072_nested_generate.py`，恰好 8 tests：

1. catalog/top overlay `0/0 + 0/0` 且 graph 不重建 semantic view；
2. graph 精确为 `26/26/33/59`；
3. nested span 内 9-symbol quarantine、两个同名 genvar identity/zero occurrence 与两个
   generate-block reason 精确；
4. same-file/other-file sibling 与 selected top 分类不受影响；
5. mapping `26/14/3/9`，逐个 actual edit `symbol_id` 证明总计 34、nested 0、same 11、
   other 11、top 12；
6. actual gate strict compile 与逐文件 3-file byte-identical restore；
7. actual renamed gate Formal 正例；
8. 固定 `~` gate marker 唯一、strict compile 通过且 Formal 按预期失败。

更新 `tests/test_symbol_graph_genvars.py` 中恰好一项旧断言：

- `test_nested_same_named_genvars_fail_closed` 改为冻结的 6-symbol safe-preserve oracle。

第一条验收命令最终：

```text
Ran 29 tests
OK
```

## 9. 允许修改的文件

子 Agent 只允许修改：

```text
rtl_obfuscator/symbol_graph.py
tests/test_symbol_graph_genvars.py
tests/test_t072_nested_generate.py
docs/development/future_work.md
docs/tasks/T072_nested_generate_owner_preserve.md
```

所有 fixture 只读。`future_work.md` 只允许把 physical module owner 可证明的 nested
generate 从 whole-graph fail-closed 更新为 T072 owner safe-preserve；不得改写其他规划。

## 10. 不包含

- nested generate 内部 rename；
- conditional generate、generate-case、instance array；
- 跨 module hierarchical generate reference；
- macro-backed generate；
- package/class/interface scope；
- project-root/filelist 构建适配；
- API/schema/CLI/report version 变化；
- RISC-V-Vector 或真实仓库复测；
- T073 合同或实现。

## 11. 子 Agent 执行规范

1. 第一条命令必须是 `git status --short --branch`；
2. 完整阅读 `AGENTS.md`、本合同、`docs/tasks/README.md`、
   `refactor_subagent_protocol.md`、三模式架构第 2–5 节和 `formal_verification.md`；
3. 校验 HEAD、唯一 READY 任务和六个 fixture hash；
4. 编辑前先把本合同状态改为 `IN_PROGRESS` 并填写启动记录；
5. 只运行第 12 节第一条命令作为 baseline；预期 21 个既有 tests 通过，新模块
   `ModuleNotFoundError`，`Ran 22 tests`、exit 非 0；
6. 先写/迁移冻结测试，再实现最小 nested owner quarantine；
7. 普通任务内失败一次修完；
8. 完成后填写 graph/mapping/gate/restore/Formal 正负证据，设置 `READY_FOR_REVIEW`；
9. 不 commit/push/stage，不设置 `ACCEPTED`，不创建 T073。

## 12. 唯一验收命令

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_symbol_graph_genvars tests.test_vnext_category_closure tests.test_t072_nested_generate -v
conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/symbol_graph.py tests/test_symbol_graph_genvars.py tests/test_t072_nested_generate.py
git diff --check HEAD
rg -x -- '- 状态：`READY_FOR_REVIEW`' docs/tasks/T072_nested_generate_owner_preserve.md
```

不得运行 blanket discovery 或 RISC-V-Vector。

## 13. 停止条件

只有以下情况停止并记录：

- fixture hash 或 PySlang API 与冻结事实不同；
- nested loop 无法唯一映射到物理 ModuleOwner 或 exact module syntax span；
- module spans 重叠、包含其他 module declaration，或与 T071 reason 冲突；
- 内外 genvar 无法保持两个精确 declaration identity；
- 修复需要允许文件外变化、公开 API/schema 或通用 fallback；
- protected nested owner 仍产生 edit；
- same/other sibling 被 quarantine；
- actual renamed gate strict compile、restore 或 Formal 无法在本任务范围内通过。

## 14. 执行记录

启动时填写：

```text
status: IN_PROGRESS
starting_head: b882169dae0d60cfc0b04721ea9c2f15973073e1
first_command: git status --short --branch
branch: main...origin/main
staged_changes: none
inherited_worktree: docs/tasks/T072_nested_generate_owner_preserve.md and tests/fixtures/t072_nested_generate/ were frozen untracked inputs; no allowed implementation-file overlap
fixture_hash_check: PASS; all six frozen fixture byte counts and SHA-256 values match Section 3.3
baseline: pending; will run only Section 12 first command after this status update
```

完成记录：

```text
status: READY_FOR_REVIEW
changed_files: rtl_obfuscator/symbol_graph.py; tests/test_symbol_graph_genvars.py; tests/test_t072_nested_generate.py; docs/development/future_work.md; docs/tasks/T072_nested_generate_owner_preserve.md
commands: baseline `conda run -n rtl_obfuscation python -m unittest tests.test_symbol_graph_genvars tests.test_vnext_category_closure tests.test_t072_nested_generate -v`; final Section 12 commands exactly as listed above
results: baseline exit 1 with 21 existing tests passing, `Ran 22 tests`, and the expected `ModuleNotFoundError` for the absent T072 module; final unittest exit 0, `Ran 29 tests`, `OK`; py_compile exit 0; `git diff --check HEAD` exit 0
graph_oracle: 26 symbols / 26 declarations / 33 occurrences / 59 total ranges; catalog and top overlay compile are `0/0 + 0/0`; graph retains the supplied SourceCatalog identity
nested_owner: semantic Genvar declaringDefinition uniquely matched the ordinary ModuleOwner and its source-backed ModuleDeclarationSyntax span; exactly 9 declarations are unsupported with reason `owner_contains_nested_generate`, and no nested actual edit was produced
same_named_genvars: two distinct `genvars` symbol_id and declaration identities at `rtl/nested_and_same.sv:125..126` and `:180..181`; both spelling `i`, both occurrence lists empty, no spelling merge or partial occurrence
generate_blocks: `g_outer` and `g_inner` are both unsupported with reason `owner_contains_nested_generate`, including their generate-scope owner_module values
mapping_oracle: total/rename/preserve/unsupported `26/14/3/9`; actual edit count `34`
actual_edits: symbol_id-audited counts nested `0`, same-file sibling `11`, other-file sibling `11`, selected-top internal `12`; same/other sibling and selected-top internal objects remained eligible and renamed according to the existing policy
strict_compile: actual renamed gate compiled with catalog/top overlay `0/0 + 0/0`; gate contained 34 actual edits
restore: actual gate restored all 3 physical files byte-identically to the input manifest; result `byte_identical=True`
formal_positive: actual gate `/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t072-formal-positive-3ndl3cy6/gate`; exact command `/Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python scripts/formal_equivalence.py --gold-filelist tests/fixtures/t072_nested_generate/design.f --gold-root tests/fixtures/t072_nested_generate --gate-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t072-formal-positive-3ndl3cy6/gate/design.f --gate-root /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t072-formal-positive-3ndl3cy6/gate --top t072_top --seq 5`; exit 0; complete JSON `{"formal_equivalence": "pass", "gate": "/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t072-formal-positive-3ndl3cy6/gate", "gold": "tests/fixtures/t072_nested_generate", "seq": 5, "top": "t072_top"}`
formal_negative: actual negative gate `/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t072-formal-negative-f17gt111/negative`; exact command `/Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python scripts/formal_equivalence.py --gold-filelist tests/fixtures/t072_nested_generate/design.f --gold-root tests/fixtures/t072_nested_generate --gate-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t072-formal-negative-f17gt111/negative/design.f --gate-root /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t072-formal-negative-f17gt111/negative --top t072_top --seq 5`; unique marker `assign data_o = ` occurred once and one ASCII `~` was inserted; negative strict compile `{"catalog": {"parse_errors": 0, "semantic_errors": 0}, "top_overlay": {"parse_errors": 0, "semantic_errors": 0}}`; Formal exit `1`; key output: `equiv_status -assert`; `Found 3 unproven $equiv cells (3 groups) in equiv:`; `Proved 2 previously unproven $equiv cells.`; `Found 1 unproven $equiv cells in module equiv:`; `Proved 0 previously unproven $equiv cells.`; `ERROR: Found 1 unproven $equiv cells in 'equiv_status -assert'.`
boundaries: fixtures unchanged; no public API/schema/category/CLI/mapping/rewrite/restore/Formal implementation changes; nested generate internal objects remain unsupported; ambiguous owner/span, span conflict, and T071 reason conflict remain fail-closed; no blanket discovery or RISC-V-Vector Formal run
review_request: implementation and the four frozen Section 12 commands are complete; ready for Main Agent independent review. No stage, commit, push, ACCEPTED update, or successor task was created.
```

## 15. Luna 子 Agent 启动指令

```text
你是 T072 实现子 Agent，模型为 gpt-5.6-luna，reasoning=xhigh。
工作目录：/Users/lufengchi/Desktop/workspace/rtl_obfuscation

唯一任务：执行 docs/tasks/T072_nested_generate_owner_preserve.md。

第一条命令必须是 git status --short --branch。完整阅读 AGENTS.md、T072 合同、
docs/tasks/README.md、refactor_subagent_protocol.md、three_mode_refactor_plan.md 第2—5节和
formal_verification.md。确认 HEAD=b882169dae0d60cfc0b04721ea9c2f15973073e1、T072 是唯一
READY、六个 fixture hash 全部匹配。编辑前先把 T072 状态设为 IN_PROGRESS 并填写启动记录。

只允许修改 symbol_graph.py、test_symbol_graph_genvars.py、
test_t072_nested_generate.py、future_work.md 和 T072 合同；所有 fixture 只读。
必须保留 typed nested-loop check，以 semantic declaring definition 唯一证明物理 ModuleOwner
与 source-backed module span；nested owner 的 genvar 只保留两个独立 declaration、零
occurrence，所有 span 内 symbol（包括 generate-block scopes）统一 unsupported。不得按拼写
合并、按源码搜索 module 边界或部分改名。

只运行合同第12节四条验收命令。完成后记录 actual gate strict compile、逐文件 restore、
Formal 正例和固定功能负例，并设置 READY_FOR_REVIEW 后停止。不得 stage/commit/push、
设置 ACCEPTED、创建 T073、运行 blanket discovery 或 RISC Formal。
```

## 16. 主 Agent 独立验收

```text
status: ACCEPTED
accepted_on: 2026-07-31
accepted_head_before_commit: b882169dae0d60cfc0b04721ea9c2f15973073e1
scope_review: PASS; only the five allowed implementation/test/documentation files changed, while all six frozen fixtures remained byte/hash identical
implementation_review: PASS; nested detection remains typed; exact ModuleDeclarationSyntax spans are derived from semantic declaring definitions and checked against the physical ModuleOwner registry; nested genvar occurrence collection is skipped atomically; final quarantine uses declaration containment so generate-scope g_outer/g_inner are protected; no text boundary scan, spelling merge, public API, schema, category, CLI, mapping, rewrite, restore, or Formal change was added
non_nested_regression_review: PASS; new definition-key/owner/span failures apply only after an actual nested loop is detected; the prior non-nested definition_key=None continue behavior and occurrence path remain unchanged
review_rework: PASS; the same Luna agent added the semantic-view guard, accurate migrated test name, exact Formal evidence, and restored the non-nested boundary without changing oracle or fixture
fixture_hashes: PASS; all four T072 files and two migrated T042 files match section 3
target_tests: exit 0; Ran 29 tests; OK
py_compile: exit 0
diff_check: exit 0
ready_for_review_guard: exit 0 before acceptance
graph_oracle: PASS; 26/26/33/59
nested_owner: PASS; exact module span contains nine unsupported/owner_contains_nested_generate symbols, including both same-named genvars and both generate blocks
same_named_genvars: PASS; declarations 125..126 and 180..181 are distinct, with zero occurrences and no spelling merge
mapping_oracle: PASS; total/rename/preserve/unsupported 26/14/3/9
actual_edits: PASS; total 34, nested span 0, same-file sibling 11, other-file sibling 11, selected-top internal symbols/instances 12
strict_compile_restore: PASS; actual renamed gate 0/0 + 0/0 and all three restored files equal frozen gold bytes
formal_positive: PASS; Main-Agent actual gate /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t072-formal-positive-da2dg0zr/gate, top t072_top, seq 5, exit 0, complete JSON formal_equivalence=pass
formal_negative: PASS; Main-Agent fixed-tilde gate /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t072-formal-negative-3zmtqdtd/negative, strict compile 0/0 + 0/0, exit 1, output contained unproven and equiv_status -assert
forbidden_runs: blanket discovery and RISC-V-Vector Formal were not run
decision: ACCEPTED
```
