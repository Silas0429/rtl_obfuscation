# T076：module closing label 的语义 occurrence 闭合

- 状态：`READY`
- 合同版本：1.1
- 设计日期：2026-08-07
- 设计负责人：主 Agent
- 实现负责人：代码子 Agent（请求模型：Luna extra high / standard speed；当前执行器无 Luna，实际启动配置必须如实记录）
- 前置任务：T075 `ACCEPTED`，交付提交 `74afee274ed95bc79181246f382b7a04d4715792`
- 设计基线 HEAD：`74afee274ed95bc79181246f382b7a04d4715792`
- 任务类型：ABI `modules` semantic occurrence 修复；产生 rewritten RTL

## 1. 单一目标

对普通物理 module 的 closing label：

```systemverilog
endmodule : module_name
```

只在 PySlang 已证明它属于同一 `ModuleDeclarationSyntax`、token 物理可写且 token 文本与 semantic
module record 完全相等时，把 label name 作为 module symbol 的一个
`semantic_module_end_label` occurrence。子 module 被选择加密时，module declaration、所有
hierarchy references 和 closing label 必须使用同一个新名称；selected top preserve 时 closing
label record 仍保留但不产生 edit。

T076 不能以 strict compile 拦截错误 gate 作为成功。目标是让 graph 在 rewrite 前已经覆盖 closing
label，actual gate 首次生成就严格编译通过。证据不足时继续 fail-closed，绝不按 `endmodule` 文本搜索。

## 2. 起始状态与 baseline

```text
branch: main
HEAD: 74afee274ed95bc79181246f382b7a04d4715792
origin/main: 74afee274ed95bc79181246f382b7a04d4715792
worktree: clean
active implementation tasks: none
T075 + category closure baseline: 15/15 PASS
```

主 Agent 已执行：

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_t075_owner_occurrence_firewall \
  tests.test_vnext_category_closure -v
```

结果：exit 0，15 tests，T075 actual-gate Formal 正例/固定功能负例与 19-category closure 均通过。

当前 module record 只包含 opening declaration 与 hierarchy references。若 eligible child 使用
`endmodule : child`，opening declaration 与 hierarchy type 会改名，而 closing label 保持旧名称；
这是 ABI `modules` 类的 occurrence 不闭合。事务 strict compile 会阻止错误 gate 发布，但这不等于
支持成功。

### 2.1 合同 1.1 重冻结

合同 1.0 将 mismatched closing label 错写为 semantic diagnostic。子 Agent 按停止条件报告后，
主 Agent 在未修改 fixture 的前提下独立复现：

```text
public SourceSet entry:
  from_filelist(invalid_label.f, top=t076_bad_label)
  -> SourceSetError
  -> code=SOURCESET_DISCOVERY_FAILED
  -> message=strict closure compilation contains parse errors

isolated SourceCatalog entry:
  use the positive SourceSet immutable fields
  replace ordered_source_files/top_closure_files/compile_order with rtl/invalid_label.sv
  replace top with t076_bad_label
  build_source_catalog(...)
  -> SourceCatalogError
  -> code=CATALOG_PARSE_FAILED
  -> message=catalog view contains parse errors
```

合同 1.1 只修订 invalid diagnostic 的阶段与错误码，不改变 positive fixture、单一目标、允许文件、
semantic token 合同、strict/restore/Formal 强度或文档范围。1.0 的阻塞记录保留为历史证据；恢复执行
从主 Agent 的 1.1 重冻结提交开始，并重新运行 baseline。

## 3. 主 Agent 冻结的 PySlang 事实

在 Conda `rtl_obfuscation` 环境的 PySlang 11.0.0 中，只读 probe 已确认：

```text
ModuleDeclarationSyntax.header.name:
  opening module identifier token

ModuleDeclarationSyntax.blockName:
  no closing label -> None
  `endmodule : child` -> NamedBlockClauseSyntax

NamedBlockClauseSyntax:
  colon -> Token(TokenKind.Colon)
  name  -> Token(TokenKind.Identifier)
  name.rawText == "child"
  name.location is a direct physical SourceLocation

`module child; endmodule : wrong`:
  PySlang parse diagnostic
```

`blockName.name` 是 closing label 唯一允许的物理 token 来源。不得从 module syntax span、last token、
source bytes、正则或 `endmodule` 后字符串推导 label。

## 4. 冻结 fixture

子 Agent 必须逐字创建以下文件。

```text
source root: tests/fixtures/t076_module_end_label
positive filelist: design.f
invalid filelist: invalid_label.f
positive top: t076_top
invalid top: t076_bad_label
defines: none
```

### 4.1 `design.f`

```text
rtl/labeled_child.sv
rtl/plain_sibling.sv
rtl/top.sv
```

### 4.2 `invalid_label.f`

```text
rtl/invalid_label.sv
```

### 4.3 `rtl/labeled_child.sv`

```systemverilog
module t076_labeled_child (
    input  logic [7:0] data_i,
    output logic [7:0] data_o
);
    logic [7:0] child_state;

    assign child_state = data_i ^ 8'h5a;
    assign data_o = child_state;
endmodule : t076_labeled_child
```

### 4.4 `rtl/plain_sibling.sv`

```systemverilog
module t076_plain_sibling (
    input  logic [7:0] data_i,
    output logic [7:0] data_o
);
    logic [7:0] sibling_state;

    assign sibling_state = ~data_i;
    assign data_o = sibling_state;
endmodule
```

### 4.5 `rtl/top.sv`

```systemverilog
module t076_top (
    input  logic [7:0] data_i,
    output logic [7:0] data_o
);
    logic [7:0] child_o;
    logic [7:0] sibling_o;

    t076_labeled_child u_child (
        .data_i(data_i),
        .data_o(child_o)
    );
    t076_plain_sibling u_sibling (
        .data_i(data_i),
        .data_o(sibling_o)
    );

    assign data_o = child_o ^ sibling_o;
endmodule : t076_top
```

### 4.6 `rtl/invalid_label.sv`

```systemverilog
module t076_bad_label;
endmodule : t076_other_label
```

invalid fixture 必须在正常 public input 阶段以
`SourceSetError(code="SOURCESET_DISCOVERY_FAILED")` fail-closed，不得进入 SymbolGraph 或 rewrite。
目标测试还必须用第 2.1 节冻结的等价 immutable `SourceSet` 隔离 SourceCatalog 阶段，并精确得到
`SourceCatalogError(code="CATALOG_PARSE_FAILED")`。不得把 parse diagnostic 包装为 semantic error。

## 5. 最小实现合同

### 5.1 semantic target 与 token

只允许在 `_collect_extended_symbols()` 的已有 compilation/records 上增加最小 pass：

1. 从已有 semantic tree 的 `InstanceBodySymbol.definition` 取得 physical
   `ModuleDeclarationSyntax`；
2. 用 `_module_definition_key()` / declaration identity 唯一找到
   `module_records_by_declaration` 中同一 module record；不得只按 name 查找；
3. `syntax.blockName is None` 时不增加 occurrence；
4. `blockName` 存在时只能读取 `blockName.name` token；token 必须非 missing、
   `rawText == record["name"]`，并由 `_token_source_range()` 证明精确物理范围；
5. 将该范围通过现有 `add_occurrence()` 加入同一 record，provenance 固定为
   `semantic_module_end_label`；
6. 多次 elaboration 看到同一 definition 时由现有 range 去重，只保留一个 closing-label
   occurrence；
7. record/declaration/owner/token 任一不一致时抛出稳定 `SymbolGraphError`，不得跳过后继续。

macro-backed token 仍沿用 T073 owner evidence/quarantine；T076 不把 expanded/original macro
location 当成 closing-label rewrite range，也不授权宏生成 module definition name。

### 5.2 graph、mapping 与 rewrite 不变量

- 不增加 category、schema、record 字段、CLI 或 mapping 分支；
- closing label 是现有 `modules` SourceSymbol 的 occurrence，不是新 symbol；
- eligible child module 的 declaration、hierarchy occurrence、closing-label occurrence action 必须
  全部为同一 `rename` record；
- selected top module 仍是 `preserved/selected_top_boundary`，其 closing-label occurrence 保留但
  不产生 edit；
- 无 label 的 module 不制造 occurrence；
- rewrite/restore 只消费现有 record/ranges，不新增 end-label 特例。

### 5.3 文档同步

只允许做以下两处语义同步：

- `docs/systemverilog_renaming_table.md` 的 `modules` 行明确：提供 `--top` 时子 module declaration、
  实例化引用和直接 closing label `endmodule : name` 一致改名，selected top 名称/label 保留；
- `docs/development/future_work.md` 将 owner-occurrence firewall 标为 T075 已完成，将普通物理
  module end label 标为 T076 已支持；保留 expression-sized cast、package-qualified member、
  conflicting quarantine、syntax-less conversion 和外部工程边界为未解决项。

不得改 README 工作流、支持类别数量或其他文档段落。

## 6. 冻结 machine oracle

目标 unittest 必须至少证明：

- positive catalog/top overlay 为 0/0 + 0/0，并复用同一 semantic view；
- invalid fixture 正常 `from_filelist()` 精确抛出 `SOURCESET_DISCOVERY_FAILED`；第 2.1 节隔离
  SourceCatalog probe 精确抛出 `CATALOG_PARSE_FAILED`；
- child module record 只有一个 declaration，并恰好包含一个 `semantic_hierarchy` 与一个
  `semantic_module_end_label` occurrence；end-label range bytes 等于 `t076_labeled_child`；
- top module record 为 selected-top preserve，同时包含一个
  `semantic_module_end_label` occurrence；mapping/rewrite 不编辑其 declaration 或 label；
- plain sibling module 没有 `semantic_module_end_label` occurrence，但 module hierarchy rename
  仍正常；
- child module mapping action 为 rename，opening declaration、hierarchy reference 与 closing label
  产生三个同 symbol_id、同 original/renamed name 的实际 edits；gate 三处 bytes 均为该 renamed
  name，原 child closing label 不残留；
- graph/mapping ranges 一对一、无重复/重叠；sibling/child/top internal symbols继续真实改名，
  不是 whole-graph preserve；
- actual gate strict compile 0/0 + 0/0，restore 的三个 `.sv` 文件与输入逐字节相同；
- compact actual renamed gate Formal：top=`t076_top`、seq=5、exit 0、完整 JSON
  `formal_equivalence="pass"`；
- 固定功能负例只在 actual gate 副本中把 top 的唯一 `assign data_o = ` 改为
  `assign data_o = ~`；负例 strict compile 仍 0/0 + 0/0，Formal 非零并含 `unproven` 与
  `equiv_status -assert`；
- type table 与 future-work 两处冻结文本同步通过，T075 防火墙不得回退。

修复前 characterization 必须在产品代码修改前记录：child closing-label range 不在 graph/edit
中；opening/hierarchy 已改名；strict compile 原子失败且目标 output path 未发布。不得把这项旧失败
保留为修复后 oracle。

## 7. 明确不包含

- 不支持 `endinterface`、`endpackage`、`endclass`、subroutine/task/generate closing label；
- 不支持宏生成/宏 argument closing label，不修改 macro text；
- 不处理 expression-sized cast、enum/base dimension、package-qualified member、implicit
  conversion 或 conflicting quarantine reasons；
- 不改变 module/port ABI 分类、selected top boundary、category 选择或名称生成；
- 不修改 mapping/rewrite/restore/orchestration/CLI/Formal 脚本；
- 不引入外部仓库，不运行 RISC-V-Vector Formal、blanket discovery 或历史 acceptance driver。

## 8. 允许修改

```text
docs/tasks/T076_module_end_label_occurrence.md
rtl_obfuscator/symbol_graph.py
tests/test_t076_module_end_label.py
tests/fixtures/t076_module_end_label/design.f
tests/fixtures/t076_module_end_label/invalid_label.f
tests/fixtures/t076_module_end_label/rtl/labeled_child.sv
tests/fixtures/t076_module_end_label/rtl/plain_sibling.sv
tests/fixtures/t076_module_end_label/rtl/top.sv
tests/fixtures/t076_module_end_label/rtl/invalid_label.sv
docs/systemverilog_renaming_table.md
docs/development/future_work.md
```

除此之外不得修改、删除、格式化或生成仓库文件。

## 9. 子 Agent 执行顺序

1. 完整阅读 `AGENTS.md`、本合同、`docs/tasks/README.md`、subagent protocol、T075 合同、
   renaming table、future work 和 Formal 文档；
2. 确认 starting HEAD、origin/main、clean worktree、唯一 T076 READY；完整保留第 12.1 节 1.0
   阻塞证据；第一次实现编辑前把状态改为 `IN_PROGRESS`，新增第 12.2 节恢复记录并如实填写实际
   模型与 v1.1 starting HEAD；
3. 运行第 10 节 baseline，逐字创建 fixture；
4. 在产品代码修改前记录第 6 节 pre-fix characterization；
5. 只实现第 5 节最小 semantic occurrence，并增加目标测试；
6. 逐条执行第 10 节五条验收，填写真实命令、输出、strict/restore、Formal 正负证据和边界；
7. 确认只有第 8 节路径变化，设置 `READY_FOR_REVIEW` 后停止；不得 stage、commit、push、设置
   `ACCEPTED` 或创建 T077。

若 PySlang API、token identity、v1.1 当前 failure code 或 Yosys 行为与合同不符，先在任务记录写明
最小复现并停止，不得改 fixture、放宽 oracle 或用 source text 搜索替代语义证据。

## 10. 唯一验收命令

Baseline（实现前一次）：

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_t075_owner_occurrence_firewall \
  tests.test_vnext_category_closure -v
```

实现后五条：

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_t076_module_end_label -v

conda run -n rtl_obfuscation python -m unittest \
  tests.test_t075_owner_occurrence_firewall \
  tests.test_vnext_category_closure -v

conda run -n rtl_obfuscation python -m py_compile \
  rtl_obfuscator/symbol_graph.py \
  tests/test_t076_module_end_label.py

git diff --check HEAD

rg -x -- '- 状态：`READY_FOR_REVIEW`' \
  docs/tasks/T076_module_end_label_occurrence.md
```

第一条内部必须运行 actual gate strict compile、restore、compact Formal 正例与固定功能负例；不得
identity/copy-gold、删除 `equiv_status -assert` 或修改 proof depth。

## 11. Formal verification 记录

```text
formal_verification: PASS | FAIL | BLOCKED
gold: tests/fixtures/t076_module_end_label
gate: <actual write_gate_vnext output>
top: t076_top
seq: 5
positive_command: <exact command>
positive_exit_code: <integer>
positive_result: <complete stdout JSON>
negative_gate: <actual gate copy with only frozen top assign mutation>
negative_compile: <catalog/top overlay counts>
negative_command: <exact command>
negative_exit_code: <nonzero integer>
negative_result: <unproven / equiv_status -assert summary>
```

## 12. 子 Agent 执行记录

```text
status: BLOCKED
actual_model: gpt-5.6-sol / xhigh；当前调度器未提供 Luna 模型或 standard speed 参数，未声称使用 Luna
starting_head: 3b8d75adffb5f0e0d39a0dc14a95c1193c5d3690；origin/main 同提交；worktree clean
allowed_files_check: PASS；合同第 8 节 11 个允许路径无既有未提交修改；唯一活动实现任务为 T076
baseline: PASS；`conda run -n rtl_obfuscation python -m unittest tests.test_t075_owner_occurrence_firewall tests.test_vnext_category_closure -v`；exit 0；Ran 15 tests；OK
pre_fix_characterization: PASS；冻结 positive compile 为 0/0 + 0/0；child module declaration range `rtl/labeled_child.sv:7..25` 与 hierarchy occurrence `rtl/top.sv:139..157` 已进入同一 rename record 并产生两个 edits；closing label range `rtl/labeled_child.sv:208..226` 不在 graph/edit；`write_gate_vnext` 精确失败为 `REWRITE_GATE_COMPILE_FAILED`（内部 `CATALOG_PARSE_FAILED`），目标 output path 不存在，未发布错误 gate
changed_files: docs/tasks/T076_module_end_label_occurrence.md；tests/fixtures/t076_module_end_label/{design.f,invalid_label.f,rtl/labeled_child.sv,rtl/plain_sibling.sv,rtl/top.sv,rtl/invalid_label.sv}；已回撤未验收的 symbol_graph 与两处产品文档改动
commands: 冻结 baseline；positive pre-fix 只读 probe；invalid fixture 正常 `from_filelist` probe；等价手工 SourceSet 直接 `build_source_catalog` probe
results: BLOCKED；正常 `from_filelist(invalid_label.f, top=t076_bad_label)` 在进入 `build_source_catalog()` 前即抛出 `SOURCESET_DISCOVERY_FAILED: strict closure compilation contains parse errors`；绕过 discovery、构造同一 invalid compile order 后直接调用 `build_source_catalog()` 精确抛出 `CATALOG_PARSE_FAILED: catalog view contains parse errors`，均不符合冻结 `CATALOG_SEMANTIC_FAILED`
schema_or_behavior: 未交付产品行为、schema、category、mapping 或 rewrite 变化；发现错误码 oracle 与当前 PySlang/SourceSet 事实冲突后停止
documentation: 未同步 renaming table 或 future work；未验收的文档补丁已回撤
boundaries: 不得自行修改 invalid fixture、把 parse failure 改写为 semantic failure、绕过 SourceSet 正常入口或放宽合同错误码；需要主 Agent 根据最小复现重冻 oracle
cleanup_candidates: none
formal_verification: BLOCKED；未进入修复后目标 unittest，未运行 T076 Formal；不得在错误码冲突下申请 READY_FOR_REVIEW
review_request: 请主 Agent复核 invalid-label 最小复现并决定重冻 `SOURCESET_DISCOVERY_FAILED` / `CATALOG_PARSE_FAILED` 边界；子 Agent 未 stage、commit、push、设置 ACCEPTED 或创建 T077
```

### 12.1 偏差或阻塞

冻结第 4.6/6 节要求 invalid fixture 在 `build_source_catalog()` 阶段精确得到
`CATALOG_SEMANTIC_FAILED`，但当前环境的实际诊断分类是 parse error：

1. 通过正常 public input `from_filelist()` 时，SourceSet discovery 已经以
   `SOURCESET_DISCOVERY_FAILED` 停止，无法到达 SourceCatalog；
2. 为隔离阶段差异，用 positive SourceSet 的不可变字段构造同一 `rtl/invalid_label.sv` compile
   order 并直接调用 `build_source_catalog()`，稳定结果为 `CATALOG_PARSE_FAILED`；
3. fixture 保持合同逐字内容，PySlang、SourceSet、SourceCatalog 和测试 oracle 均未修改。

这属于合同明确列出的“当前 failure code 与冻结设计不符”停止条件。子 Agent 未把 parse error
包装成 semantic error，也未继续实现或运行 Formal。

### 12.2 合同 1.1 恢复执行记录

```text
status: pending
actual_model: pending
starting_head: pending
allowed_files_check: pending
baseline: pending
contract_delta_check: pending
pre_fix_characterization_reused: pending
changed_files: pending
commands: pending
results: pending
schema_or_behavior: pending
documentation: pending
boundaries: pending
cleanup_candidates: pending
formal_verification: pending
review_request: pending
```

## 13. 主 Agent 验收

```text
status: pending
independent_commands: pending
allowed_files: pending
semantic_identity_review: pending
range_and_edit_audit: pending
documentation: pending
strict_compile: pending
restore_byte_identity: pending
formal_positive: pending
formal_negative: pending
decision: pending
delivery_commit: pending
push: pending
successor: pending
```
