# T079：被实例覆盖的参数默认值引用精确绑定

- 状态：`READY`
- 合同版本：1.1（2026-08-10 post-acceptance rework）
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
formal_verification: PASS
gold: tests/fixtures/t079_parameter_default
gate: /private/tmp/t079-compact-evidence.tfih2Q/gate（actual public rtl_encrypt output）
top: t079_top
seq: 5
positive_command: conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold-filelist tests/fixtures/t079_parameter_default/design.f --gold-root tests/fixtures/t079_parameter_default --gate-filelist /private/tmp/t079-compact-evidence.tfih2Q/gate/design.f --gate-root /private/tmp/t079-compact-evidence.tfih2Q/gate --top t079_top --seq 5
positive_exit_code: 0
positive_result: {"formal_equivalence": "pass", "gate": "/private/tmp/t079-compact-evidence.tfih2Q/gate", "gold": "tests/fixtures/t079_parameter_default", "seq": 5, "top": "t079_top"}
negative_gate: /private/tmp/t079-compact-evidence.tfih2Q/negative（actual gate copy；只在 top.sv 唯一 `assign data_o = ` 后增加 `~`）
negative_compile: catalog 0/0；top overlay 0/0
negative_command: conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold-filelist tests/fixtures/t079_parameter_default/design.f --gold-root tests/fixtures/t079_parameter_default --gate-filelist /private/tmp/t079-compact-evidence.tfih2Q/negative/design.f --gate-root /private/tmp/t079-compact-evidence.tfih2Q/negative --top t079_top --seq 5
negative_exit_code: 1
negative_result: `Found 8 unproven $equiv cells in 'equiv_status -assert'`；未弱化 `equiv_status -assert`
external_gold: /private/tmp/t079-serv-replay.1rZFr6/source（fresh materialized pinned SERV source）
external_gate: /private/tmp/t079-serv-replay.1rZFr6/matrix/abi__parameters/gate
external_top: serv_rf_top
external_seq: 5
external_command: /Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python /Users/lufengchi/Desktop/workspace/rtl_obfuscation/scripts/formal_equivalence.py --gold-filelist /Users/lufengchi/Desktop/workspace/rtl_obfuscation_realworld_stability/projects/serv/prepared/design.f --gold-root /private/tmp/t079-serv-replay.1rZFr6/source --gate-filelist /private/tmp/t079-serv-replay.1rZFr6/matrix/abi__parameters/gate/design.f --gate-root /private/tmp/t079-serv-replay.1rZFr6/matrix/abi__parameters/gate --top serv_rf_top --seq 5
external_exit_code: 0
external_result: FORMAL_PASS；{"formal_equivalence": "pass", "gate": "/private/tmp/t079-serv-replay.1rZFr6/matrix/abi__parameters/gate", "gold": "/private/tmp/t079-serv-replay.1rZFr6/source", "seq": 5, "top": "serv_rf_top"}
```

## 12. 子 Agent 执行记录

```text
status: READY_FOR_REVIEW
actual_model: gpt-5.6-sol / xhigh; 当前调度器未提供 Luna 模型或 standard speed 参数，未声称使用 Luna
starting_head: e402cdfb3c7fa31c9096bd50b01ee84342b174d5; origin/main 同提交；branch main；worktree clean；start_time 2026-08-07T15:43:58+0800
allowed_files_check: PASS; 合同第 8 节八个允许路径无既有未提交修改；唯一活动任务为 T079 READY；无 staged/unstaged/untracked 文件
baseline: PASS; `conda run -n rtl_obfuscation python -m unittest tests.test_symbol_graph_parameters tests.test_t069_sized_cast_parameter tests.test_t071_type_parameter_defparam -v`; exit 0; Ran 36 tests; OK
pre_fix_characterization: PASS; frozen fixture bytes/SHA-256 all match section 3; catalog/top overlay 0/0 + 0/0; graph 19/19/25/44; six parameter records/seven occurrences; `child.sv:88..98` absent; mapping 19/6/13/0 with 13 planned edits; public encrypt exit 1 `CLI_VNEXT_ORCHESTRATION_INVALID`, gate absent
changed_files: 第 8 节八个允许路径；`rtl_obfuscator/symbol_graph.py`、T079 target unittest、四个冻结 fixture、`docs/development/future_work.md` 与本任务记录；允许列表外零修改
commands: baseline 见上；实现后严格执行第 10 节恰好五条验收：四模块 unittest；pinned SERV 单 `abi__parameters` replay + jq oracle；py_compile；`git diff --check HEAD`；精确 READY_FOR_REVIEW guard；未运行 blanket discovery、历史 driver 或 RISC-V-Vector Formal
results: PASS；目标+回归 exit 0，Ran 41 tests，OK；py_compile exit 0；diff check exit 0；READY_FOR_REVIEW guard exit 0；finish_time 2026-08-07T15:55:36+0800
schema_or_behavior: 只在既有 `_collect_parameter_symbols()` 内增加 exact `DeclaratorSyntax` / `EqualsValueClauseSyntax` initializer typed-token recovery；使用当前 declaration `parentScope.lookupName()` 与 `_parameter_source_key()` 精确绑定已有 module value/local parameter record；same-target range 保留既有 provenance，other-target range `SYMBOL_GRAPH_RANGE_CONFLICT`；无 API/schema/category/policy/rewrite/CLI 变化
compact_oracle: PASS；graph 19/19/26/45；parameter 6 symbols/8 occurrences；唯一 `parameter_default` 为 `child.sv:88..98`，target `COMPRESSED` declaration `41..51`；DOUBLE_WIDTH/sibling DERIVED 的 WIDTH 仍为 `semantic_expression`；T069 `sized_cast_type` 回归通过；mapping 19/6/13/0，actual edits 14
strict_and_restore: PASS；public encrypt exit 0，summary files=3/mapping_records=19/modified_tokens=14/strict=true/internal restore=true；gate catalog/top overlay 0/0 + 0/0；COMPRESSED declaration/default/body 与 ALIGN declaration/body/named override 各同 record 一致改名；public decrypt 不读 original source，exit 0，恢复三个 `.sv` 逐字节一致且无 `design.f`
external_replay: PASS；stability `b99f5e43128964cc78a5c123a31f84e46df76934` 与 SERV `41e8aeedfd1e9ad5f95902c5b0dfc83d1c99e5d2` replay 前后 clean；output `/private/tmp/t079-serv-replay.1rZFr6/matrix`；`abi__parameters`=`PASS_EFFECTIVE`，rename=59，files=17，records=726，edits=421，strict/gate/decrypt/restore all pass，restore.files=17，Formal PASS exit 0
documentation: `future_work.md` 记录 T079 已支持的 exact default initializer direct identifier 与仍不支持的 type/package/class、macro、hierarchical/scoped/text-recovery 边界
boundaries: 不支持 type/package/class parameter、macro default、hierarchical/scoped name、expression-sized cast 或文本扫描；不宣称其他 SERV profile/工程/ABI/non-ABI 类别支持；不能证明 binding/location/record 时不增加 occurrence，同 range 多 target 原子失败
cleanup_candidates: none
formal_verification: PASS；compact actual renamed gate seq=5 正例 exit 0 完整 JSON pass；固定单处 `~` 负例 strict 0/0 + 0/0、exit 1、8 unproven 且命中 `equiv_status -assert`；pinned SERV actual gate seq=5 FORMAL_PASS，完整证据见第 11 节与 `/private/tmp/t079-serv-replay.1rZFr6/matrix/abi__parameters/formal.log`
review_request: READY_FOR_REVIEW；请主 Agent 独立执行第 10 节五条命令与 actual-gate Formal 后决定是否 ACCEPTED；子 Agent 未 stage/commit/push，未设置 ACCEPTED，未创建 T080
```

## 13. 主 Agent 验收

```text
review_date: 2026-08-07
reviewer: 主 Agent
starting_head: e402cdfb3c7fa31c9096bd50b01ee84342b174d5；origin/main 同提交
allowed_files: PASS；最终变更精确为第 8 节八个允许路径，无额外 tracked/untracked 文件
implementation_review: PASS；产品 diff 只在既有 `_collect_parameter_symbols()` 中从 exact
  DeclaratorSyntax/EqualsValueClauseSyntax initializer 提取 direct IdentifierNameSyntax token，经当前
  declaration parentScope.lookupName 与 `_parameter_source_key()` 绑定已有 module value/local parameter
  record；same-target range 保留既有 provenance，other-target range 原子报
  SYMBOL_GRAPH_RANGE_CONFLICT；无 schema/category/policy/rewrite/CLI 变化
target_and_regression: PASS；第 10 节合并 unittest exit 0；Ran 41 tests；OK
compact_oracle: PASS；graph 19/19/26/45，parameter 6 symbols/8 occurrences；唯一新增
  parameter_default 为 child.sv:88..98，target COMPRESSED declaration 41..51；mapping
  19/6/13/0，actual edits=14；T069 sized_cast_type 与既有 semantic_expression provenance 保持
strict_and_restore: PASS；public encrypt files=3/mapping_records=19/modified_tokens=14；actual gate
  catalog/top overlay 0/0 + 0/0；公开 decrypt 不读取 original source，恢复三个 `.sv` byte-identical，
  不发布 design.f
formal_positive: PASS；Main-Agent target unittest actual gate
  /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t079-formal-positive-1h2auqjm/encrypt/gate；
  top=t079_top；seq=5；exit 0；complete JSON formal_equivalence=pass
formal_negative: PASS as expected negative；Main-Agent actual-gate copy
  /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t079-formal-negative-6lmhab6i/negative；
  only frozen `assign data_o = ~` mutation；strict compile 0/0 + 0/0；exit 1；target assertion
  independently matched `unproven` and `equiv_status -assert`
external_replay: PASS；stability HEAD=b99f5e43128964cc78a5c123a31f84e46df76934，SERV
  HEAD=41e8aeedfd1e9ad5f95902c5b0dfc83d1c99e5d2；Main-Agent replay root
  /private/tmp/t079-main-serv-replay.y9ciVg；abi__parameters=PASS_EFFECTIVE，rename=59，
  files=17，mapping_records=726，modified_tokens=421，strict/gate/decrypt/restore 全通过；
  restore.files=17；两个只读仓库重放前后 clean
external_formal: PASS；actual SERV gate；top=serv_rf_top；seq=5；exit 0；FORMAL_PASS；complete
  JSON formal_equivalence=pass，timed_out=false
py_compile: PASS；第 10 节命令 exit 0
diff_check: PASS；git diff --check HEAD exit 0
ready_for_review_guard: PASS；精确 guard 在本次 ACCEPTED 状态变更前 exit 0
documentation: PASS；future work 精确记录已支持的 default initializer direct identifier 及仍不支持的
  type/package/class、macro、hierarchical/scoped/text-recovery 边界
forbidden_runs: 未运行 RISC-V-Vector Formal、blanket discovery 或历史 acceptance driver；未修改外部仓库
delivery_resume_recheck: PASS；2026-08-10 从未暂存 ACCEPTED 工作区恢复，HEAD/origin/main 仍为
  e402cdfb3c7fa31c9096bd50b01ee84342b174d5；重新运行 41 tests exit 0，compact actual-gate Formal
  正例 exit 0/负例 exit 1；fresh SERV replay=/private/tmp/t079-resume-serv.Q4g3BE，59 rename、421 edits、
  restore byte-identical、FORMAL_PASS；git diff --check HEAD 通过，无用户或外部仓库漂移
decision: WITHDRAWN 2026-08-10；第 14 节扩大 category-neutral Ibex 复测证明 v1.0 initializer
  traversal 错把 assignment-pattern key 当成参数引用；不得推送当前实现，必须完成 v1.1 rework
delivery_commit: current acceptance commit；exact hash 在提交后报告并冻结进后继合同
push: NOT_RUN；本地提交 b97b323ed1438870f60c92df5cdb08d661627dc0 未推送且不得单独推送
successor: 禁止创建；必须先完成第 14 节、重新验收并形成纠正提交
```

## 14. v1.1 post-acceptance rework：assignment-pattern key 语法角色防火墙

### 14.1 否决依据与起始状态

2026-08-10 主 Agent 在推送前扩大 category-neutral 真实工程复测，推翻第 13 节完成判断：

```text
local HEAD: b97b323ed1438870f60c92df5cdb08d661627dc0
origin/main: e402cdfb3c7fa31c9096bd50b01ee84342b174d5
branch: main ahead 1
worktree: clean
remote push: never performed
active implementation tasks: T079 v1.1 is the only READY task
```

Ibex 任意 profile 在 category/policy/mapping 之前共享失败：

```text
error: SYMBOL_GRAPH_UNSUPPORTED_REFERENCE
message: scope-bound identifier has no semantic target
file/range: rtl/ibex_cs_registers.sv:34842..34845
token: mie
source shape: localparam status_t MSTATUS_RST_VAL = '{mie: 1'b0, ...};
semantic parameter: MSTATUS_RST_VAL, isLocalParam=true
parentScope.lookupName("mie"): None
record/action/edit: N/A; SymbolGraph 未发布
```

`mie` 不是参数 expression reference，而是 structured assignment pattern 的 member key。v1.0 对
initializer subtree 中所有 `IdentifierNameSyntax` 无条件调用 `_scope_lookup_target()`，因此引入了
category-neutral graph regression。

冻结 PySlang typed API：

```text
IdentifierNameSyntax(token=mie)
  parent -> AssignmentPatternItemSyntax
  parent.key -> IdentifierNameSyntax(token=mie)
  parent.colon -> Token
  parent.expr -> IntegerVectorExpressionSyntax
parent chain:
  AssignmentPatternItemSyntax
  -> StructuredAssignmentPatternSyntax
  -> AssignmentPatternExpressionSyntax
  -> EqualsValueClauseSyntax
  -> DeclaratorSyntax
  -> ParameterDeclarationSyntax
```

`parent.key.identifier.location` 与 candidate token 的 buffer/offset/rawText 精确相同。只读 runtime
模拟仅跳过这种 exact key 后，Ibex `abi__parameters` 得到：

```text
graph symbols/declarations/occurrences/total_ranges: 3129/3129/11391/14520
mapping total/rename/preserve/unsupported: 3129/150/2556/423
parameter records: 213
modified_tokens: 817
strict compile: catalog/top overlay 0/0 + 0/0
physical files: 45
```

这不是 `struct_fields` 支持证据。Ibex `struct_fields`、`enum_values`、`functions`、`arguments` 仍有各自
独立 reference 缺口，必须留给后继任务；v1.1 只消除 T079 自身错误解析。

### 14.2 唯一修复目标

在 T079 initializer recovery 内，只有同时满足以下 typed identity 时，跳过 candidate 且绝不调用
lexical parameter lookup：

1. candidate 是 `IdentifierNameSyntax`；
2. candidate 的 direct parent 精确为 `AssignmentPatternItemSyntax`；
3. `parent.key` 精确为 `IdentifierNameSyntax`；
4. `parent.key.identifier` 与 candidate identifier 的 physical buffer、offset、rawText 精确一致。

同一 `AssignmentPatternItemSyntax.expr` 中的 `IdentifierNameSyntax` 不是 key，必须继续走 T079 exact
`parentScope.lookupName()`、module value/local parameter record、macro/location/range/conflict 审计。例如：

```systemverilog
localparam int WIDTH = 1;
localparam status_t RESET = '{mie: WIDTH};
```

`mie` 必须零 parameter occurrence；`WIDTH` 必须保持/新增 exact parameter occurrence。除上述 exact
key 角色外，unresolved initializer identifier 必须维持现有 fail-closed，不得把 lookup failure 全局改为
`continue`，不得按名称、拼写或 `lookupName(None)` 猜测 member。

### 14.3 明确不包含

- 不为 `struct_fields` 建立 assignment-pattern key occurrence，不改写 `mie/uie`；
- 不修 Ibex enum closing/reference、function end label、named call argument；
- 不修 CV32E40P package-qualified typedef/member 或 AXI type-parameter actual；
- 不修 riscv-dbg `$clog2(RomSize)'(...)` expression-sized cast；
- 不改变 API/schema/category/policy/mapping/rewrite/restore/CLI/Formal；
- 不修改第 3 节冻结 fixture bytes/hash；
- 不运行 RISC-V-Vector Formal、blanket discovery 或历史 acceptance driver。

### 14.4 v1.1 允许修改

```text
docs/tasks/T079_overridden_parameter_default_occurrence.md
rtl_obfuscator/symbol_graph.py
tests/test_t079_parameter_default_occurrence.py
docs/development/future_work.md
```

第 3 节四个 fixture 只读，其他仓库文件、stability repo、Ibex/SERV checkout 全部不得修改。所有临时
source、gate、restore、matrix 和 log 只能写入新 `/private/tmp` 或测试临时目录。

### 14.5 v1.1 machine oracle

目标测试必须新增最小 typed pattern：

```systemverilog
typedef struct packed { logic mie; } status_t;
localparam int WIDTH = 1;
localparam status_t RESET = '{mie: WIDTH};
```

并证明：

- `mie` exact key 不调用 `_scope_lookup_target()`，不进入任何 parameter declaration/occurrence/edit；
- value-side `WIDTH` 继续精确绑定其 parameter declaration，既有 same-target provenance 去重不变；
- 非 key 的 unresolved initializer identifier 继续
  `SYMBOL_GRAPH_UNSUPPORTED_REFERENCE` fail-closed；
- 第 5 节 compact oracle、14 edits、strict/restore、actual-gate Formal 正负例全部不变；
- T069 sized-cast 与 T071 type-parameter/defparam regression 不变；
- pinned Ibex `abi__parameters` 为 `PASS_EFFECTIVE`：150 rename、3129 records、817 edits、45 files、
  strict=true、gate published、decrypt exit 0、restore byte-identical；Formal policy none，不宣称等价；
- pinned SERV `abi__parameters` 仍为 `PASS_EFFECTIVE`：59 rename、726 records、421 edits、17 files、
  strict/restore true，actual-gate Formal `FORMAL_PASS`。

### 14.6 v1.1 子 Agent 执行顺序

1. 完整重读 AGENTS、T079 第 14 节、task workflow、subagent protocol、T069/T071 target tests 和 Formal
   文档；确认本地 HEAD 是 parent=b97b323 的 v1.1 contract commit、origin=e402cdf、除本任务合同外
   clean、唯一 T079 READY；执行记录必须填写 exact starting HEAD；
2. 第一次实现/测试编辑前设置 `IN_PROGRESS`，记录实际模型与第 14.4 节四个允许路径；
3. 运行第 14.7 节 baseline，并在产品修改前用临时 source 精确复现 `mie` root cause；
4. 先新增 syntax-role 黑盒测试，再只实现第 14.2 节 exact key skip；
5. 严格执行五条验收，记录 compact、Ibex、SERV、Formal 和 repo clean 证据；
6. 设置 `READY_FOR_REVIEW` 后停止；不得 stage、commit、push、设置 `ACCEPTED` 或创建 T080。

任何 parent/key API、Ibex frozen count、fixture oracle、外部 pin 或允许路径冲突都必须记录并停止，不得
扩大到 field/member binding 或放松 lookup failure。

### 14.7 v1.1 唯一验收命令

Baseline（实现前一次）：

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_t079_parameter_default_occurrence \
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
test "$(git -C "$external_root/repos/ibex" rev-parse HEAD)" = 3250d99482f1963891ef1cf19356eeaeeaa71d30
test "$(git -C "$external_root/repos/serv" rev-parse HEAD)" = 41e8aeedfd1e9ad5f95902c5b0dfc83d1c99e5d2
test -z "$(git -C "$external_root" status --short)"
test -z "$(git -C "$external_root/repos/ibex" status --short)"
test -z "$(git -C "$external_root/repos/serv" status --short)"
replay_root=$(mktemp -d /private/tmp/t079-v11-replay.XXXXXX)
sh "$external_root/projects/ibex/commands/materialize.sh" "$external_root" "$replay_root/ibex-source"
conda run -n rtl_obfuscation python "$external_root/category_matrix_runner.py" \
  --study-root "$external_root" --project ibex \
  --source-root "$replay_root/ibex-source" \
  --filelist "$external_root/projects/ibex/prepared/design.f" --top ibex_top \
  --include-dir vendor/lowrisc_ip/ip/prim/rtl \
  --include-dir vendor/lowrisc_ip/dv/sv/dv_utils --include-dir rtl --define SYNTHESIS \
  --output-root "$replay_root/ibex-matrix" \
  --profiles abi__parameters --formal-policy none
sh "$external_root/projects/serv/commands/materialize.sh" "$external_root" "$replay_root/serv-source"
conda run -n rtl_obfuscation python "$external_root/category_matrix_runner.py" \
  --study-root "$external_root" --project serv \
  --source-root "$replay_root/serv-source" \
  --filelist "$external_root/projects/serv/prepared/design.f" --top serv_rf_top \
  --output-root "$replay_root/serv-matrix" \
  --profiles abi__parameters --formal-policy effective
jq -e '
  (.results | length) == 1 and
  .results[0].classification == "PASS_EFFECTIVE" and
  .results[0].effective_renamed_records == 150 and
  .results[0].cli_summary.summary.files == 45 and
  .results[0].cli_summary.summary.mapping_records == 3129 and
  .results[0].cli_summary.summary.modified_tokens == 817 and
  .results[0].strict_compile_passed == true and
  .results[0].gate_published == true and
  .results[0].decrypt_exit_code == 0 and
  .results[0].restore_byte_identical == true and
  .results[0].restore.files == 45 and
  .results[0].formal.status == "FORMAL_NOT_RUN"
' "$replay_root/ibex-matrix/matrix.json"
jq -e '
  (.results | length) == 1 and
  .results[0].classification == "PASS_EFFECTIVE" and
  .results[0].effective_renamed_records == 59 and
  .results[0].cli_summary.summary.files == 17 and
  .results[0].cli_summary.summary.mapping_records == 726 and
  .results[0].cli_summary.summary.modified_tokens == 421 and
  .results[0].strict_compile_passed == true and
  .results[0].restore_byte_identical == true and
  .results[0].restore.files == 17 and
  .results[0].formal.status == "FORMAL_PASS" and
  .results[0].formal.exit_code == 0
' "$replay_root/serv-matrix/matrix.json"
test -z "$(git -C "$external_root" status --short)"
test -z "$(git -C "$external_root/repos/ibex" status --short)"
test -z "$(git -C "$external_root/repos/serv" status --short)"

conda run -n rtl_obfuscation python -m py_compile \
  rtl_obfuscator/symbol_graph.py tests/test_t079_parameter_default_occurrence.py

git diff --check HEAD

rg -x -- '- 状态：`READY_FOR_REVIEW`' \
  docs/tasks/T079_overridden_parameter_default_occurrence.md
```

目标 unittest 内继续负责 compact actual-gate strict/restore/Formal 正负例；Ibex external
`formal-policy none` 只证明 strict/restore，SERV `formal-policy effective` 才是 external equivalence 证据。

### 14.8 v1.1 子 Agent rework 记录

```text
status: pending
actual_model:
starting_head:
allowed_files_check:
baseline:
pre_fix_pattern_key:
changed_files:
commands:
results:
syntax_role_contract:
compact_oracle:
ibex_replay:
serv_replay:
formal_verification:
boundaries:
review_request:
```

### 14.9 v1.1 主 Agent重新验收

```text
review_date: pending
reviewer: 主 Agent
starting_head:
allowed_files:
implementation_review:
target_and_regression:
compact_oracle:
ibex_replay:
serv_replay:
formal_positive:
formal_negative:
external_formal:
py_compile:
diff_check:
ready_for_review_guard:
decision: pending
delivery_commit: pending
push: blocked until explicit user authorization
successor: forbidden before corrected T079 delivery
```
