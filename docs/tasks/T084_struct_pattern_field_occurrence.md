# T084：struct assignment-pattern field key 的语义 occurrence 闭合

- 状态：`READY`
- 创建日期：2026-08-10
- 起始分支：`main`
- 起始 HEAD：`565d838c9fcab4b859452963431b7d5b321ceede`
- 前置任务：T083 已 `ACCEPTED`
- 任务类型：单一 SymbolGraph occurrence 闭合；会产生 rewritten RTL，必须执行 actual-gate Formal

## 1. 单一目标

只闭合普通物理 struct alias 的 direct named assignment-pattern field key：

```systemverilog
typedef struct packed {
  logic lhs;
  logic rhs;
} pair_t;

pair_t pair;
always_comb pair = '{rhs: data_i, lhs: 1'b0};
```

当 semantic `StructuredAssignmentPatternExpression.type` 精确解析到既有 `struct_types` record，且 direct
`AssignmentPatternItemSyntax.key` 的物理 identifier token 精确匹配该 alias owner 下唯一既有
`struct_fields` record 时，把 key token 加入同一 field record，provenance 固定为：

```text
semantic_struct_pattern_key
```

field declaration、普通 member references 与全部已证明 pattern keys 必须使用同一个 renamed name。
证据不足时继续 fail-closed；不得用 scope/global lookup、field 顺序、expression value 或 source text 猜测。

本任务不支持 union、array/queue、positional/default/type keys、macro-backed key、class property、tagged union
或 generic assignment-pattern traversal。

## 2. 起始状态与冻结 baseline

```text
branch: main
HEAD: 565d838c9fcab4b859452963431b7d5b321ceede
origin/main: d3072b56f86969936441927efdb5dffedcef67ee
worktree: clean
active implementation tasks: none
related baseline: 58/58 PASS
```

主 Agent 已运行：

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_t083_named_function_argument \
  tests.test_t082_function_end_label \
  tests.test_t076_module_end_label \
  tests.test_vnext_category_closure \
  tests.test_t079_parameter_default_occurrence \
  tests.test_t080_expression_sized_cast_parameter \
  tests.test_t081_enum_lexical_completeness_firewall -v
```

结果：exit 0，Ran 58 tests，OK；T076/T079/T080/T081/T082/T083 actual renamed-gate Formal
正例均 exit 0，各冻结功能负例均 exit 1。

## 3. 冻结 compact fixture

子 Agent 必须逐字创建：

```text
tests/fixtures/t084_struct_pattern_field/design.f
tests/fixtures/t084_struct_pattern_field/design.sv
```

`design.f`：

```text
design.sv
```

固定为 10 bytes，SHA-256：

```text
2bd824b8fab1c3ebc159191ce9f58bbaadd30a5ddbea38fa8a4fcfc4b94d1aea
```

`design.sv`：

```systemverilog
module t084_top (
  input  logic data_i,
  output logic data_o
);
  typedef struct packed {
    logic lhs;
    logic rhs;
  } pair_t;

  pair_t pair;
`ifdef T084_NAMED_PATTERN
  always_comb pair = '{rhs: data_i, lhs: 1'b0};
`else
  always_comb pair = {1'b0, data_i};
`endif
  assign data_o = pair.lhs ^ pair.rhs;
endmodule
```

固定为 323 bytes，SHA-256：

```text
9ea0f0f0b107aa9fdaeff67c537bc1c015aef3e885d7b72403a826e4334290a9
```

public compile/encrypt 使用：

```text
top=t084_top
define=T084_NAMED_PATTERN
category=struct_fields
public project/filelist scope => struct_fields 自动按 ABI 选择
```

## 4. 主 Agent compact preflight

在起始 HEAD、启用 `T084_NAMED_PATTERN` 时：

```text
catalog compile: 0/0
top overlay compile: 0/0
graph: 7 symbols / 7 declarations / 8 occurrences / 15 total ranges
mapping: 7 total / 2 rename / 5 preserve / 0 unsupported
planned edits: 4
lhs declaration/body-member: 102..105 / 297..300
rhs declaration/body-member: 117..120 / 308..311
missing rhs pattern key: 199..202
missing lhs pattern key: 212..215
public encrypt: exit 1, CLI_VNEXT_ORCHESTRATION_INVALID
gate: absent
internal: REWRITE_GATE_COMPILE_FAILED / CATALOG_SEMANTIC_FAILED
```

精确 runtime 模型只加入两个 pattern-key occurrences 后：

```text
graph: 7 / 7 / 10 / 17
mapping: 7 / 2 / 5 / 0
actual edits: 6
strict compile: 0/0 + 0/0
restore: 1 file byte-identical
rhs key: design.sv:199..202 -> field declaration 117..120
lhs key: design.sv:212..215 -> field declaration 102..105
```

fixture 的 named pattern 是合法 SystemVerilog；Icarus/Yosys不能作为 public named-pattern frontend。
public strict 以项目既有 PySlang catalog/top overlay 为准。

## 5. PySlang typed identity 冻结

Ibex 首个 pattern `ExcCauseIrqSoftwareM` 的 exact semantic path：

```text
StructuredAssignmentPatternExpression
  syntax: AssignmentPatternExpressionSyntax
    pattern: StructuredAssignmentPatternSyntax
      items:
        AssignmentPatternItemSyntax
          key: IdentifierNameSyntax
            identifier: Token(Identifier, "irq_ext")
        Token(Comma)
        AssignmentPatternItemSyntax(key="irq_int")
        Token(Comma)
        AssignmentPatternItemSyntax(key="lower_cause")
  type: TypeAliasType exc_cause_t
    canonicalType: PackedStructType, isStruct=true, isPackedUnion=false
```

`TypeAliasType exc_cause_t` 的 declaration identity 精确命中既有 `struct_types` record；field records 由同一
alias declaration 建立，owner 固定为该 alias 的 `type:<file>:<start>:<end>`。因此 key 必须按 exact alias
record + exact field owner + token name 绑定，不得 name-only。

T079 的 initializer lexical pass 继续必须跳过 `AssignmentPatternItemSyntax.key`，不得重新调用
`_scope_lookup_target()`；T084 是独立 semantic typed binding。

## 6. pinned Ibex 当前失败与候选闭包

冻结 pins：

```text
product starting HEAD: 565d838c9fcab4b859452963431b7d5b321ceede
stability: b99f5e43128964cc78a5c123a31f84e46df76934
Ibex: 3250d99482f1963891ef1cf19356eeaeeaa71d30
```

fresh pre-fix root：

```text
/private/tmp/t084-ibex-abi-refresh.GbFTIx
```

当前 public `abi__struct_fields`：

```text
classification: FAIL_STRICT
effective rename: 0
gate published: false
restore: false / not run
public error: CLI_VNEXT_ORCHESTRATION_INVALID
Formal: FORMAL_NOT_RUN
```

内部修复前：

```text
graph: 3129 / 3129 / 11532 / 14661
mapping: 109 rename / 2511 preserve / 509 unsupported
strict: REWRITE_GATE_COMPILE_FAILED / CATALOG_SEMANTIC_FAILED
first diagnostics: AssignmentPatternMissingElements / AssignmentPatternNoMember / UnknownMember
first file: rtl/ibex_pkg.sv
```

exact runtime 模型 inventory：

```text
physical aliased struct patterns: 36
exact direct identifier field keys: 143
macro-backed exact keys: 0
unmatched exact field records: 0
graph after: 3129 / 3129 / 11675 / 14804
mapping actions unchanged: 109 / 2511 / 509
actual edits: 455
strict compile: 0/0 + 0/0
restore: 45 files byte-identical
```

首个 exact records/ranges：

```text
irq_ext: declaration rtl/ibex_pkg.sv:6441..6448; key 6551..6558
irq_int: declaration rtl/ibex_pkg.sv:6416..6423; key 6566..6573
lower_cause: declaration rtl/ibex_pkg.sv:6466..6477; key 6581..6592
```

非 alias arrays、scalar patterns 与 non-identifier/default keys 不计入 36/143，不得由本任务绑定。

## 7. 安全决策

选择 exact semantic occurrence，理由：

1. semantic expression 已给出唯一 `TypeAliasType` 和 canonical packed struct identity；
2. alias declaration 精确命中既有 `struct_types` record；
3. field record 必须在同一 alias owner 下按 name 唯一命中；
4. direct identifier token 提供唯一物理 source range；
5. 143 条模型全部通过 strict 与 45-file restore，未改变 policy action。

若实现时任一 API、计数或 identity 不成立，停止 T084；不得临时扩展 generic pattern resolver，也不得把
union/array/default key 加入任务。

## 8. 唯一实现合同

1. 只修改 `rtl_obfuscator/symbol_graph.py` 的现有 `_collect_extended_symbols()`；不得改 policy、mapping、
   rewrite、restore、orchestration、CLI 或 Formal；
2. field records 与 alias identity 建立后，只处理
   `type(node).__name__ == "StructuredAssignmentPatternExpression"`；
3. `node.syntax` 必须是 exact `pyslang.syntax.AssignmentPatternExpressionSyntax`，`.pattern` 必须是 exact
   `pyslang.syntax.StructuredAssignmentPatternSyntax`；不得递归 syntax subtree；
4. `node.type` 必须是 `TypeAliasType`，其 `canonicalType.isStruct == true` 且
   `canonicalType.isPackedUnion == false`；alias declaration 必须由 `record_for_target()` 精确命中既有
   `category == "struct_types"` record；
5. `pattern.items` 中 comma Token 只作为分隔符；direct non-token item 必须是
   `AssignmentPatternItemSyntax`。非 identifier key（例如 `default`/type/literal key）不产生 occurrence；
6. direct `IdentifierNameSyntax.identifier` 必须 non-missing、spelling 非空；只从 exact alias declaration
   对应的 `field_records_by_alias[(file,start,end,name)]` 取 record；record 必须为 `struct_fields`、owner 等于
   alias record owner、name 等于 token rawText；缺失或不一致稳定 fail-closed；
7. 通过现有 `_token_source_range()` 证明 non-macro physical token；非 `None` 时用现有
   `add_occurrence()` 加入同一 field record，provenance 精确为 `semantic_struct_pattern_key`；不得新建
   symbol/category/schema/reason；
8. macro-backed key 返回 `None`，不制造 physical occurrence/edit；由现有 owner quarantine或 public strict
   atomic failure保护，不得改 macro text或映射虚拟 location；
9. repeated elaboration由现有 exact-range去重；不同 record占用同一/部分重叠 range继续 fail-closed；
10. T079 assignment-pattern key lexical skip、普通 member binding、struct declaration、owner quarantine和 enum
    firewall行为不变；
11. 不支持 union_fields、anonymous/non-alias struct、array/queue element pattern、positional/default/type key、
    class property、tagged union或宏 key；
12. 不增加 dependency、fallback、cache、second parser、raw regex或 Ibex hard-code。

## 9. NO-GO 与目标测试

目标 unittest 至少证明：

1. fixture bytes/hash、修复前 graph/mapping/atomic failure；
2. pattern source order `rhs`/`lhs` 正确绑定 declaration identity，而非 declaration position；
3. lhs/rhs declaration、ordinary member reference、pattern key各自同 record、同 renamed name、三个 edits；
4. `StructuredAssignmentPatternExpression.type`、alias declaration、canonical struct与 key token typed path；
5. T079 key skip保持，key不调用 lexical scope lookup；value-side expressions仍按既有语义处理；
6. union、array、scalar、positional、default/literal/type key不产生
   `semantic_struct_pattern_key`；
7. macro key不产生物理 occurrence/edit；不安全选择只能 quarantine或 atomic strict failure；
8. missing/mismatched token、wrong alias/category/owner、no field、occupied/partial range稳定 fail-closed；
9. repeated elaboration去重；同名 field在两个 alias owner下不合并；
10. actual public gate strict 0/0+0/0、source-free restore byte-identical；
11. 第 11 节 actual renamed-gate Formal正例与固定功能负例。

## 10. pinned Ibex post-fix oracle

fresh `/private/tmp`、`formal-policy none`：

```text
profile: abi__struct_fields
classification: PASS_EFFECTIVE
files: 45
mapping records: 3129
actions: 109 rename / 2511 preserve / 509 unsupported
effective renamed records: 109
modified_tokens: 455
semantic_struct_pattern_key occurrences: 143
strict_compile_passed: true
gate_published: true
decrypt_exit_code: 0
restore.files: 45
restore_byte_identical: true
formal.status: FORMAL_NOT_RUN
```

不得把 external `FORMAL_NOT_RUN` 描述为等价证明。

## 11. compact Formal 边界

- public encrypt/strict带 `T084_NAMED_PATTERN`，actual gate 必须真实包含并改写 named keys；
- Yosys gold/gate均不传 define，选择 concatenation branch，避开其 named assignment-pattern frontend边界；
- actual gate仍真实改写 field declarations 与宏外 `pair.<field>` references，不是 identity/copy-gold；
- 正例：top=`t084_top`、seq=5、exit 0、完整 JSON `formal_equivalence=pass`；
- 固定负例：从 actual gate copy，只把宏外
  `assign data_o = pair.<lhs> ^ pair.<rhs>;` 改为逻辑取反；
- 负例带 public define 的 PySlang strict必须 0/0+0/0，Formal必须 exit 1、至少1个 unproven并含
  `equiv_status -assert`。

主 Agent runtime oracle：正例 exit 0/JSON pass；固定负例 strict 0/0+0/0、Formal exit 1、1 unproven。

## 12. 允许修改与文档交付

只允许：

```text
docs/tasks/T084_struct_pattern_field_occurrence.md
rtl_obfuscator/symbol_graph.py
tests/test_t084_struct_pattern_field.py
tests/fixtures/t084_struct_pattern_field/design.f
tests/fixtures/t084_struct_pattern_field/design.sv
docs/systemverilog_renaming_table.md
docs/development/future_work.md
```

- renaming table 的 `struct_fields` 行补充 exact alias-backed direct named pattern key一致改写与边界；
- future work记录 T084 typed binding、Yosys边界，以及 union/array/default/macro/anonymous pattern仍不支持；
- README不改：公开命令、category、schema没有变化。

禁止修改其他文件，禁止 stage/commit/push，禁止设置 `ACCEPTED`，禁止创建 T085。

## 13. 验收命令（固定五条）

开始前 baseline：

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_t083_named_function_argument \
  tests.test_t082_function_end_label \
  tests.test_t076_module_end_label \
  tests.test_vnext_category_closure \
  tests.test_t079_parameter_default_occurrence \
  tests.test_t080_expression_sized_cast_parameter \
  tests.test_t081_enum_lexical_completeness_firewall -v
```

实现后五条：

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_t084_struct_pattern_field \
  tests.test_t083_named_function_argument \
  tests.test_t082_function_end_label \
  tests.test_t076_module_end_label \
  tests.test_vnext_category_closure \
  tests.test_t079_parameter_default_occurrence \
  tests.test_t080_expression_sized_cast_parameter \
  tests.test_t081_enum_lexical_completeness_firewall -v

external_root=/Users/lufengchi/Desktop/workspace/rtl_obfuscation_realworld_stability
test "$(git -C "$external_root" rev-parse HEAD)" = b99f5e43128964cc78a5c123a31f84e46df76934
test "$(git -C "$external_root/repos/ibex" rev-parse HEAD)" = 3250d99482f1963891ef1cf19356eeaeeaa71d30
test -z "$(git -C "$external_root" status --short)"
test -z "$(git -C "$external_root/repos/ibex" status --short)"
replay_root=$(mktemp -d /private/tmp/t084-ibex-replay.XXXXXX)
sh "$external_root/projects/ibex/commands/materialize.sh" \
  "$external_root" "$replay_root/source"
conda run -n rtl_obfuscation python "$external_root/category_matrix_runner.py" \
  --study-root "$external_root" --project ibex \
  --source-root "$replay_root/source" \
  --filelist "$external_root/projects/ibex/prepared/design.f" --top ibex_top \
  --include-dir vendor/lowrisc_ip/ip/prim/rtl \
  --include-dir vendor/lowrisc_ip/dv/sv/dv_utils \
  --include-dir rtl --define SYNTHESIS \
  --output-root "$replay_root/matrix" \
  --profiles abi__struct_fields --formal-policy none
jq -e '
  (.results | length) == 1 and
  .results[0].profile == "abi__struct_fields" and
  .results[0].classification == "PASS_EFFECTIVE" and
  .results[0].effective_renamed_records == 109 and
  .results[0].cli_summary.summary.files == 45 and
  .results[0].cli_summary.summary.mapping_records == 3129 and
  .results[0].cli_summary.summary.modified_tokens == 455 and
  ([.results[0].mapping_counts[] | .rename // 0] | add) == 109 and
  ([.results[0].mapping_counts[] | .preserve // 0] | add) == 2511 and
  ([.results[0].mapping_counts[] | .unsupported // 0] | add) == 509 and
  .results[0].strict_compile_passed == true and
  .results[0].gate_published == true and
  .results[0].decrypt_exit_code == 0 and
  .results[0].restore_byte_identical == true and
  .results[0].restore.files == 45 and
  .results[0].formal.status == "FORMAL_NOT_RUN"
' "$replay_root/matrix/matrix.json"
jq -e '
  ([.mapping.records[].occurrences[]
    | select(.provenance == "semantic_struct_pattern_key")] | length) == 143 and
  ([.mapping.records[]
    | select(.symbol_id == "symbol:struct_fields:rtl/ibex_pkg.sv:6441:6448")
    | [.occurrences[] | select(
        .provenance == "semantic_struct_pattern_key" and
        .source_range.start == 6551 and .source_range.end == 6558)]
    | select(length == 1)] | length) == 1 and
  ([.mapping.records[]
    | select(.symbol_id == "symbol:struct_fields:rtl/ibex_pkg.sv:6416:6423")
    | [.occurrences[] | select(
        .provenance == "semantic_struct_pattern_key" and
        .source_range.start == 6566 and .source_range.end == 6573)]
    | select(length == 1)] | length) == 1 and
  ([.mapping.records[]
    | select(.symbol_id == "symbol:struct_fields:rtl/ibex_pkg.sv:6466:6477")
    | [.occurrences[] | select(
        .provenance == "semantic_struct_pattern_key" and
        .source_range.start == 6581 and .source_range.end == 6592)]
    | select(length == 1)] | length) == 1
' "$replay_root/matrix/abi__struct_fields/gate/mapping.json"
test -z "$(git -C "$external_root" status --short)"
test -z "$(git -C "$external_root/repos/ibex" status --short)"

conda run -n rtl_obfuscation python -m py_compile \
  rtl_obfuscator/symbol_graph.py tests/test_t084_struct_pattern_field.py

git diff --check HEAD

rg -x -- '- 状态：`READY_FOR_REVIEW`' \
  docs/tasks/T084_struct_pattern_field_occurrence.md
```

目标 unittest必须执行 actual public strict、source-free restore、第 11 节 Formal正例和固定负例；不得
identity/copy-gold。external runner限时300秒，formal-policy none；不运行 blanket discovery、历史 driver
或 RISC-V-Vector Formal。

## 14. Formal verification 记录

```text
formal_verification: pending
gold: pending
gate: pending
top: t084_top
seq: 5
public_define: T084_NAMED_PATTERN
positive_yosys_define: none
positive_command: pending
positive_exit_code: pending
positive_result: pending
actual_gate_non_identity: pending
negative_gate: pending
negative_compile_with_public_define: pending
negative_command: pending
negative_exit_code: pending
negative_result: pending
named_pattern_boundary: Yosys cannot parse named assignment patterns; exact keys checked by PySlang strict/edit/restore
external_formal: N/A; pinned Ibex uses formal-policy none
```

## 15. 子 Agent 执行记录

```text
status: pending
actual_model: pending；不得声称使用当前执行器没有提供的 Luna / standard speed
starting_head: pending
allowed_files_check: pending
baseline: pending
pre_fix_characterization: pending
changed_files: pending
commands: pending
results: pending
typed_identity_contract: pending
compact_oracle: pending
ibex_replay: pending
formal_verification: pending
documentation: pending
boundaries: pending
review_request: pending
```

## 16. 主 Agent 验收

```text
review_date: pending
reviewer: 主 Agent
allowed_files: pending
implementation_review: pending
target_and_regression: pending
compact_oracle: pending
ibex_replay: pending
formal_positive: pending
formal_negative: pending
external_formal: N/A; formal-policy none
py_compile: pending
diff_check: pending
ready_for_review_guard: pending
decision: pending
delivery_commit: pending
push: forbidden without a new explicit user authorization beyond d3072b5
```
