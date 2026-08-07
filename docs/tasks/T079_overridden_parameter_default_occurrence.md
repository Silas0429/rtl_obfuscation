# T079：被实例覆盖的参数默认值引用精确绑定

- 状态：`READY`
- 合同版本：1.0
- 设计日期：2026-08-07
- 设计负责人：主 Agent
- 实现负责人：代码子 Agent（请求模型：Luna extra high / standard speed；当前执行器无 Luna，实际配置必须如实记录）
- 前置任务：T078 `ACCEPTED`，交付提交 `0b5a5832854e8e560fe1afcd35b26611018a49c2`
- 设计基线 HEAD：`0b5a5832854e8e560fe1afcd35b26611018a49c2`
- 任务类型：SymbolGraph parameter occurrence 修复；产生 rewritten RTL
- 执行规范：[`refactor_subagent_protocol.md`](../development/process/refactor_subagent_protocol.md)
- Formal 依据：[`formal_verification.md`](../formal_verification.md)

## 1. 单一目标

修复 module value/local parameter 的默认 initializer 在 elaboration 后被实例 override 值替换，导致默认
表达式中的物理参数引用没有进入同一 parameter record、改写后 strict compile 失败的问题。

固定缺陷形状：

```systemverilog
module child #(
    parameter logic COMPRESSED = 1'b0,
    parameter logic ALIGN = COMPRESSED
) (...);
endmodule

child #(.ALIGN(1'b1)) u_child (...);
```

PySlang 中被覆盖的 `ALIGN` semantic value 已是 `1'b1`，但其
`ParameterSymbol.syntax -> DeclaratorSyntax.initializer -> EqualsValueClauseSyntax` 仍保留物理
`COMPRESSED` token。T079 只从这个固定 declaration-default syntax 边界恢复引用，并用 declaration
所在的精确 semantic `parentScope.lookupName()` 证明它绑定到已有 module value/local parameter record。

项目最终原则保持不变：不能证明 binding、owner 或 physical range 时必须少改名或原子失败，绝不能发布
半改名 gate。

## 2. 起始状态与冻结诊断

```text
branch: main
HEAD/origin/main: 0b5a5832854e8e560fe1afcd35b26611018a49c2
worktree: clean
active implementation tasks: none
parameter baseline: 36/36 PASS
```

主 Agent 已运行：

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_symbol_graph_parameters \
  tests.test_t069_sized_cast_parameter \
  tests.test_t071_type_parameter_defparam -v
```

结果：exit 0，Ran 36 tests，OK。

第 3 节 compact 的 pre-fix 结果冻结为：

```text
catalog/top overlay diagnostics: 0/0 + 0/0
graph symbols/declarations/occurrences/total_ranges: 19/19/25/44
parameter symbols/occurrences: 6/7
missing physical token: child.sv COMPRESSED at byte 88
mapping total/rename/preserve/unsupported: 19/6/13/0
planned edits before fix: 13
public encrypt: exit 1, CLI_VNEXT_ORCHESTRATION_INVALID, gate absent
identity Formal harness: exit 0, complete JSON pass
fixed `assign data_o = ~` negative: strict 0/0 + 0/0, exit 1,
  contains unproven and equiv_status -assert
```

PySlang 冻结 API 事实：

- 被 override 的 `ALIGN` 是 `ParameterSymbol`；`syntax` 是 `DeclaratorSyntax`；`initializer` 是
  `EqualsValueClauseSyntax`；
- initializer typed subtree 中 `IdentifierNameSyntax.identifier.rawText == "COMPRESSED"`，位置为
  `child.sv:88..98`；
- `ALIGN.parentScope.lookupName("COMPRESSED")` 返回 declaration `child.sv:41..51` 的精确
  `ParameterSymbol`；
- `ALIGN` semantic value 已是 override literal `1'b1`，因此不能从 elaborated expression 恢复这段
  源码引用；
- 未被 override 的 `DOUBLE_WIDTH = WIDTH * 2` 与 sibling `DERIVED = WIDTH + 1` 已有
  `semantic_expression` occurrence；T079 不得改变其 provenance 或制造重复 range；
- T069 的 parameter-sized cast 默认 initializer 已有 `sized_cast_type` occurrence；T079 不得替换或
  重复该 provenance。

## 3. 冻结 compact fixture

子 Agent 必须逐字创建：

```text
tests/fixtures/t079_parameter_default/design.f
tests/fixtures/t079_parameter_default/child.sv
tests/fixtures/t079_parameter_default/sibling.sv
tests/fixtures/t079_parameter_default/top.sv
```

`design.f`：

```text
child.sv
sibling.sv
top.sv
```

`child.sv`：

```systemverilog
module t079_child #(
    parameter logic COMPRESSED = 1'b0,
    parameter logic ALIGN = COMPRESSED,
    parameter int WIDTH = 4,
    parameter int DOUBLE_WIDTH = WIDTH * 2
) (
    input  logic [7:0] data_i,
    output logic [7:0] data_o
);
    assign data_o = (ALIGN || COMPRESSED) ? data_i : (data_i ^ DOUBLE_WIDTH);
endmodule
```

`sibling.sv`：

```systemverilog
module t079_sibling #(
    parameter int WIDTH = 3,
    parameter int DERIVED = WIDTH + 1
) (
    input  logic [7:0] data_i,
    output logic [7:0] data_o
);
    assign data_o = data_i ^ DERIVED;
endmodule
```

`top.sv`：

```systemverilog
module t079_top (
    input  logic [7:0] data_i,
    output logic [7:0] data_o
);
    logic [7:0] child_o;
    logic [7:0] sibling_o;

    t079_child #(
        .ALIGN(1'b1)
    ) u_child (
        .data_i(data_i),
        .data_o(child_o)
    );
    t079_sibling u_sibling (
        .data_i(data_i),
        .data_o(sibling_o)
    );

    assign data_o = child_o ^ sibling_o;
endmodule
```

固定 bytes 与 SHA-256：

| file | bytes | SHA-256 |
| --- | ---: | --- |
| `design.f` | 27 | `796843c56770f7b6789520664a253bf596bb245fd5dbda892f6f4203b2d3235d` |
| `child.sv` | 328 | `aa4809295ed11349ab623972a8cd2f91f08b7c3527e1b5c08c47902d45a37c57` |
| `sibling.sv` | 206 | `455edeaf904f105dfab2324da490ec9080430bc96e9696e08d8f8ec72794a365` |
| `top.sv` | 387 | `45f019baa145c94fb143be389f4853d6c1873499c239d75fd191eb9c45de936f` |

固定 public profile：filelist、top=`t079_top`、category=`parameters`、ABI opt-in=`parameters`、无
include-dir/define/rate。

## 4. 最小实现合同

只在现有 `_collect_parameter_symbols()` 内增加 declaration-default occurrence recovery：

1. candidate 必须是已有非-type `ParameterSymbol`，其 `syntax` 精确为 `DeclaratorSyntax`，且
   `syntax.initializer` 精确为 `EqualsValueClauseSyntax`；无 initializer 或 API 形状不同则不处理；
2. 只遍历该 initializer 的 typed syntax subtree，candidate token 必须来自
   `IdentifierNameSyntax.identifier`，具有非空 physical `rawText` 与 location；不得解析注释、字符串、
   macro 展开文本或做全文件文本搜索；
3. 只使用当前 parameter declaration 的 exact `parentScope.lookupName(token.rawText)`；target 必须经
   `_parameter_source_key()` 精确绑定到 `records` 中已有 module value/local parameter declaration；type
   parameter、genvar、package/class parameter、non-parameter target 或 records 外 target 全部不增加；
4. token 必须通过现有 macro/location/SourceSet/range byte 审计，且不得等于 target declaration；
5. 如果同一 physical range 已存在于同一 target 的任何 occurrence，保持既有 occurrence 与 provenance，
   不新增 `parameter_default`；这必须保留 `semantic_expression`、`sized_cast_type`、
   `declaration_dimension` 等既有证据；
6. 如果同一 physical range 已属于另一个 parameter target，使用既有稳定
   `SYMBOL_GRAPH_RANGE_CONFLICT` 原子失败；不得任选一个 target；
7. 只有上述证据全部成立且 range 尚未存在时，增加 provenance=`parameter_default`；
8. 不新增公开 API/schema/category/rewrite/policy/CLI 分支，不按 module/fixture/name 硬编码，不复制第二套
   parameter collector。

若 `lookupName()` 对冻结 token 不返回第 2 节 exact declaration，或实现需要改动允许列表外产品文件、
schema、policy、rewrite、SourceSet/SourceCatalog，子 Agent 必须记录最小事实并停止，不得扩大范围。

## 5. 冻结 machine oracle

目标 unittest 至少证明：

- fixture 四个文件的 bytes/hash 精确匹配第 3 节；
- graph 从 `19/19/25/44` 收敛为 `19/19/26/45`；parameter symbols/occurrences 从 `6/7` 收敛为
  `6/8`；唯一新增 range 为 `child.sv:88..98`，target 是 declaration `41..51` 的 `COMPRESSED`，
  provenance=`parameter_default`；
- `DOUBLE_WIDTH` 与 sibling `DERIVED` 默认值里的 `WIDTH` 仍各只有既有
  `semantic_expression`，不新增 `parameter_default`；T069 sized-cast oracle 仍保留
  `sized_cast_type`；
- mapping 保持 `19 total / 6 rename / 13 preserve / 0 unsupported`，实际 edits 从 13 增为 14；
- public encrypt exit 0，summary 固定 `files=3`、`mapping_records=19`、`modified_tokens=14`、strict true、
  internal restore true，gate 已发布；
- actual gate 的 declaration、body、named override 及新增默认 token 同 record 一致改名；catalog/top
  overlay strict compile 0/0 + 0/0；
- public `rtl_decrypt` 不读取 original source，恢复三个 `.sv` 文件逐字节一致且不发布 `design.f`；
- compact actual renamed gate Formal top=`t079_top`, seq=5，正例 exit 0 且完整 JSON pass；
- 固定负例只在 actual gate 副本 `top.sv` 唯一 `assign data_o = ` 后增加 `~`；其 strict compile 仍为
  0/0 + 0/0，Formal 非零且输出含 `unproven` 与 `equiv_status -assert`；
- 负向 semantic fixture 至少覆盖：type parameter、genvar、non-parameter identifier 不被误收集；同一
  physical range 若被构造成两个 parameter target 则 fail-closed，不得发布 gate。

## 6. pinned SERV delta oracle

固定只读输入：

```text
stability HEAD: b99f5e43128964cc78a5c123a31f84e46df76934
SERV HEAD: 41e8aeedfd1e9ad5f95902c5b0dfc83d1c99e5d2
project: serv
top: serv_rf_top
prepared compile units: 17
profile: abi__parameters
```

T079 前冻结重放：`FAIL_STRICT`、rename=0、strict=false、restore=false、gate 未发布，公开首个稳定错误
只有 `CLI_VNEXT_ORCHESTRATION_INVALID`。内部只读诊断确认：

```text
graph/mapping records: 726/726
planned parameter rename records: 59
planned edits: 420
unique missing default token: rtl/serv_top.sv byte 486, COMPRESSED
target declaration: the serv_top module parameter COMPRESSED
serv_rf_top equivalent default reference: already collected semantically
```

修复后该单 profile 必须为：

```text
classification: PASS_EFFECTIVE
effective_renamed_records: 59
cli summary: files=17, mapping_records=726, modified_tokens=421
strict_compile_passed: true
gate_published: true
decrypt_exit_code: 0
restore_byte_identical: true
restore.files: 17
formal.status: FORMAL_PASS
formal.exit_code: 0
```

这只证明 pinned SERV 的 `parameters` 边界，不宣称 SERV `abi_group`、其他工程参数、其他 ABI/non-ABI
类别或全部真实工程已支持。外部 stability repo、SERV checkout 和 prepared input 全程只读。

## 7. 明确不包含

- 不修 typedef/struct/enum/function/argument 或 group profile；
- 不实现 expression-sized cast、package-qualified member、macro parameter default、type parameter、class/
  package parameter、复杂 hierarchical/scoped name 或通用 syntax text recovery；
- 不修改 SourceSet、SourceCatalog、owner registry、RewritePolicy、MappingVNext、rewrite、restore、metrics、
  CLI 或 Formal 脚本；
- 不修改 fixture oracle，不通过 preserve/unsupported、减少 rename 数或删除 reference 制造 strict 成功；
- 不更新外部 stability repo、第三方 checkout 或 pinned input；
- 不运行 RISC-V-Vector Formal、blanket discovery 或历史 acceptance driver。

## 8. 允许修改

```text
docs/tasks/T079_overridden_parameter_default_occurrence.md
rtl_obfuscator/symbol_graph.py
tests/test_t079_parameter_default_occurrence.py
tests/fixtures/t079_parameter_default/design.f
tests/fixtures/t079_parameter_default/child.sv
tests/fixtures/t079_parameter_default/sibling.sv
tests/fixtures/t079_parameter_default/top.sv
docs/development/future_work.md
```

除此之外不得修改、删除、格式化或生成仓库文件。所有 gate/restore/log 与 external replay 只能写入新的
`/private/tmp` 或测试临时目录。

## 9. 子 Agent 执行顺序

1. 完整阅读 AGENTS、T079、task workflow、subagent protocol、T069、parameter tests、future work 和 Formal
   文档；
2. 确认 HEAD/origin/main、clean worktree、唯一 T079 READY；第一次实现编辑前设置 `IN_PROGRESS`，记录
   实际模型、允许文件和 36-test baseline；
3. 逐字创建 fixture 与目标测试，产品修改前记录第 2 节 compact pre-fix 失败；
4. 只实现第 4 节 default initializer binding，先跑目标测试，再跑冻结 parameter regression；
5. 运行 compact actual-gate strict/restore/Formal 正负例，再按第 10 节重放 SERV 单 profile actual-gate
   Formal；
6. 记录 exact counts、range/provenance、public restore、Formal 和 external oracle，确认允许路径外零修改，
   设置 `READY_FOR_REVIEW` 后停止；不得 stage、commit、push、设置 `ACCEPTED` 或创建 T080。

## 10. 唯一验收命令

Baseline（实现前一次）：

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_symbol_graph_parameters \
  tests.test_t069_sized_cast_parameter \
  tests.test_t071_type_parameter_defparam -v
```

实现后五条：

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_t079_parameter_default_occurrence \
  tests.test_symbol_graph_parameters \
  tests.test_t069_sized_cast_parameter \
  tests.test_t071_type_parameter_defparam -v

external_root=/Users/lufengchi/Desktop/workspace/rtl_obfuscation_realworld_stability
test "$(git -C "$external_root" rev-parse HEAD)" = b99f5e43128964cc78a5c123a31f84e46df76934
test "$(git -C "$external_root/repos/serv" rev-parse HEAD)" = 41e8aeedfd1e9ad5f95902c5b0dfc83d1c99e5d2
test -z "$(git -C "$external_root" status --short)"
test -z "$(git -C "$external_root/repos/serv" status --short)"
replay_root=$(mktemp -d /private/tmp/t079-serv-replay.XXXXXX)
sh "$external_root/projects/serv/commands/materialize.sh" \
  "$external_root" "$replay_root/source"
conda run -n rtl_obfuscation python "$external_root/category_matrix_runner.py" \
  --study-root "$external_root" --project serv \
  --source-root "$replay_root/source" \
  --filelist "$external_root/projects/serv/prepared/design.f" --top serv_rf_top \
  --output-root "$replay_root/matrix" \
  --profiles abi__parameters --formal-policy effective
jq -e '
  (.results | length) == 1 and
  .results[0].profile == "abi__parameters" and
  .results[0].classification == "PASS_EFFECTIVE" and
  .results[0].effective_renamed_records == 59 and
  .results[0].cli_summary.summary.files == 17 and
  .results[0].cli_summary.summary.mapping_records == 726 and
  .results[0].cli_summary.summary.modified_tokens == 421 and
  .results[0].strict_compile_passed == true and
  .results[0].gate_published == true and
  .results[0].decrypt_exit_code == 0 and
  .results[0].restore_byte_identical == true and
  .results[0].restore.files == 17 and
  .results[0].formal.status == "FORMAL_PASS" and
  .results[0].formal.exit_code == 0
' "$replay_root/matrix/matrix.json"
test -z "$(git -C "$external_root" status --short)"
test -z "$(git -C "$external_root/repos/serv" status --short)"

conda run -n rtl_obfuscation python -m py_compile \
  rtl_obfuscator/symbol_graph.py tests/test_t079_parameter_default_occurrence.py

git diff --check HEAD

rg -x -- '- 状态：`READY_FOR_REVIEW`' \
  docs/tasks/T079_overridden_parameter_default_occurrence.md
```

目标 unittest 内部必须执行 compact actual-gate strict compile、公开 restore、Formal 正例与固定功能负例；
不得 identity/copy-gold 或弱化 `equiv_status -assert`。external replay 必须使用 `formal-policy effective`，
不得把 `FORMAL_NOT_RUN`、strict compile 或 restore 描述为功能等价证明。

## 11. Formal verification 记录

```text
formal_verification: PASS | FAIL | BLOCKED
gold: tests/fixtures/t079_parameter_default
gate: <actual public rtl_encrypt output>
top: t079_top
seq: 5
positive_command: <exact command>
positive_exit_code: <integer>
positive_result: <complete stdout JSON>
negative_gate: <actual gate copy with only frozen top assign mutation>
negative_compile: <catalog/top overlay counts>
negative_command: <exact command>
negative_exit_code: <nonzero integer>
negative_result: <unproven / equiv_status -assert summary>
external_gold: <fresh materialized pinned SERV source>
external_gate: <category_matrix_runner actual abi__parameters gate>
external_top: serv_rf_top
external_seq: 5
external_command: <exact runner/formal command from log>
external_exit_code: 0
external_result: FORMAL_PASS + complete JSON result
```

## 12. 子 Agent 执行记录

```text
status: pending
actual_model:
starting_head:
allowed_files_check:
baseline:
pre_fix_characterization:
changed_files:
commands:
results:
schema_or_behavior:
compact_oracle:
strict_and_restore:
external_replay:
documentation:
boundaries:
cleanup_candidates:
formal_verification:
review_request:
```

## 13. 主 Agent 验收

```text
review_date: pending
reviewer: 主 Agent
starting_head:
allowed_files:
implementation_review:
target_and_regression:
compact_oracle:
strict_and_restore:
formal_positive:
formal_negative:
external_replay:
external_formal:
py_compile:
diff_check:
ready_for_review_guard:
documentation:
forbidden_runs:
decision: pending
delivery_commit: pending
push: pending
successor: pending
```
