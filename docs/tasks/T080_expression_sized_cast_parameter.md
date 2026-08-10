# T080：`$clog2(identifier)` expression-sized cast 参数引用精确绑定

- 状态：`ACCEPTED`
- 合同版本：1.0
- 设计日期：2026-08-10
- 设计负责人：主 Agent
- 实现负责人：代码子 Agent（请求模型：Luna extra high / standard speed；当前执行器无 Luna，实际配置必须如实记录）
- 前置任务：T079 v1.1 `ACCEPTED`，交付提交 `d3072b56f86969936441927efdb5dffedcef67ee`
- 设计基线 HEAD/origin/main：`d3072b56f86969936441927efdb5dffedcef67ee`
- 任务类型：SymbolGraph parameter occurrence 修复；产生 rewritten RTL
- 执行规范：[`refactor_subagent_protocol.md`](../development/process/refactor_subagent_protocol.md)
- Formal 依据：[`formal_verification.md`](../formal_verification.md)

## 1. 单一目标

只支持下面一个已经由 pinned riscv-dbg 复现的 parameter cast-type reference：

```systemverilog
$clog2(RomSize)'(RomSize)
```

当前 `RomSize` declaration 和 cast operand 已进入同一个 parameter record，但
`CastExpressionSyntax.left` 内 `$clog2(...)` 的 size-expression token 没有 occurrence。parameter
declaration 被改名、cast-left token 保留旧名，strict gate compile 报 `UndeclaredIdentifier` 并原子拒绝。

T080 只从固定 typed path 提取 `$clog2(<direct IdentifierName>)` 的唯一参数 token，通过 T069 已有
最小 source-backed semantic scope 与 exact declaration identity 绑定，并用新 provenance
`expression_sized_cast_type` 加入现有 parameter record。

不支持通用 expression-sized cast。任一 typed path、scope、target、macro 或 physical range 证据不足时，
不得猜测或发布半改名 gate。

## 2. 起始状态与冻结 baseline

```text
branch: main
HEAD/origin/main: d3072b56f86969936441927efdb5dffedcef67ee
worktree: clean
active implementation tasks: none
related regression baseline: 32/32 PASS
```

主 Agent 已运行：

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_t069_sized_cast_parameter \
  tests.test_t070_keyword_cast \
  tests.test_t071_type_parameter_defparam \
  tests.test_t079_parameter_default_occurrence -v
```

结果：exit 0，Ran 32 tests，OK。四组已有 compact actual-gate Formal 正例通过，固定功能负例按预期
失败。T080 不得修改这些任务的 fixture、test 或 provenance 合同。

## 3. 冻结 compact fixture

子 Agent 必须逐字创建：

```text
tests/fixtures/t080_expression_sized_cast/design.f
tests/fixtures/t080_expression_sized_cast/design.sv
```

`design.f`：

```text
design.sv
```

精确 bytes 为 `64657369676e2e73760a`，10 bytes，SHA-256：

```text
2bd824b8fab1c3ebc159191ce9f58bbaadd30a5ddbea38fa8a4fcfc4b94d1aea
```

`design.sv`：

```systemverilog
module t080_expression_sized_cast (
  input  logic [5:0] addr_i,
  output logic       hit_o
);
  localparam int unsigned RomSize = 20;

  assign hit_o = addr_i < $clog2(RomSize)'(RomSize);
endmodule
```

199 bytes，SHA-256：

```text
0e5bd165bc458e231220e6f1e6bce0f031a604ff59cf2eb11cfc19fea9204cb0
```

固定 public profile：filelist、top=`t080_expression_sized_cast`、category=`parameters`、ABI opt-in
`parameters`、无 include-dir/define/rate。

## 4. 主 Agent preflight 与当前缺陷

证据根：`/private/tmp/t080-preflight.zJN3O0`；机器 oracle：`machine_oracle.json`。

当前产品：

```text
catalog/top overlay: 0/0 + 0/0
graph symbols/declarations/occurrences/total_ranges: 4/4/3/7
mapping total/rename/preserve/unsupported: 4/1/3/0
planned edits: 2
RomSize declaration: design.sv:121..128
RomSize cast-left: design.sv:169..176, missing
RomSize operand: design.sv:179..186, semantic_expression
write_gate: REWRITE_GATE_COMPILE_FAILED
nested cause: CATALOG_SEMANTIC_FAILED / UndeclaredIdentifier RomSize
public output: absent
```

只读 typed simulation 精确新增一条 occurrence 后：

```text
graph: 4/4/4/8
mapping: 4/1/3/0
edits: 3
strict: 0/0 + 0/0
restore: one file byte-identical
actual renamed-gate Formal: exit 0, complete JSON pass
fixed `assign hit_o = ~` negative: strict 0/0 + 0/0, Formal exit 1,
  one unproven cell, contains equiv_status -assert
```

simulation 只用于冻结输入/oracle，不是产品交付证据。T080 必须用修复后的 actual public gate 重做。

## 5. 冻结 PySlang typed path

PySlang 11.0.0 正例唯一允许形状：

```text
ConversionExpression
  syntax: CastExpressionSyntax
    left: InvocationExpressionSyntax
      left: SystemNameSyntax
        systemIdentifier.rawText == "$clog2"
      arguments: ArgumentListSyntax
        parameters: exactly one OrderedArgumentSyntax
          expr: SimplePropertyExprSyntax
            expr: SimpleSequenceExprSyntax
              repetition is None
              expr: IdentifierNameSyntax
                identifier: direct physical token
    right: ParenthesizedExpressionSyntax
```

Compact ranges：cast syntax `162..187`，left invocation `162..177`，callee `$clog2` `162..168`，candidate
`RomSize` `169..176`，right operand `179..186`。

真实 riscv-dbg 固定事实：

```text
file: debug_rom/debug_rom.sv
cast syntax: 2006..2031
candidate RomSize: 2013..2020
right operand RomSize: 2023..2030
target declaration: debug_rom/debug_rom.sv:963..970
owner definition: module debug_rom, 768..777
semantic node: ConversionExpression; getSymbolReference() is None
smallest scope: StatementBlockSymbol p_outmux, 1954..2081
scope lookup target: exact ParameterSymbol RomSize declaration 963..970
```

现有 `_sized_cast_target_from_scopes()` 已使用同 buffer、包含 token、最小 source-backed semantic scope 和
唯一 parameter declaration key；T080 必须复用，不得按 name/owner text 另建 resolver。

## 6. 最小实现合同

1. 保持 T069 `_sized_cast_identifier_token()` 的 direct `IdentifierNameSyntax` 定义与调用行为不变；
2. 新增独立内部 helper，只接受第 5 节完整 `$clog2` fixed path；不得递归 syntax visit 后选择任意
   identifier；
3. `ArgumentListSyntax.parameters` 必须恰好一项，类型必须为 `OrderedArgumentSyntax`；argument wrapper、
   `SimpleSequenceExprSyntax.repetition` 和最终 direct identifier 必须精确匹配；
4. callee 必须是 exact `SystemNameSyntax.systemIdentifier.rawText == "$clog2"`；user function、其他
   system function 或 scoped callee 不匹配；
5. candidate token 必须非空、单一物理 file location、非 macro/macro argument；继续使用现有
   SourceSet/range/bytes 审计；
6. body conversion 使用 `_sized_cast_target_from_scopes()`；parameter default 如匹配同一 fixed path，也
   必须通过其 exact declaration `parentScope.lookupName()` 或相同 existing resolver 绑定；
7. target 必须经 `_parameter_source_key()` 命中已有非-type module value/local parameter record，且不在
   genvar keys；non-parameter、package/class/type parameter 或 records 外 target 不增加；
8. same-target same-range 保留一个 occurrence；other-target range 使用既有
   `SYMBOL_GRAPH_RANGE_CONFLICT` 原子失败；不得重复 cast-right 的 `semantic_expression`；
9. 新 occurrence provenance 固定为 `expression_sized_cast_type`；不得扩大或改写 T069
   `sized_cast_type` 的冻结含义；
10. 不新增公开 API/schema/category/policy/mapping/rewrite/restore/CLI/Formal 分支，不按 fixture/project/
    module/name 硬编码。

建议最小内部结构是让现有 nested `add_sized_cast_occurrence()` 接收明确 provenance，direct cast 继续传
`sized_cast_type`，本任务 fixed path 传 `expression_sized_cast_type`；不得复制第二套 range/conflict 逻辑。

## 7. 明确 NO-GO 与 fail-closed 边界

T080 不支持：

```systemverilog
$bits(P)'(P)
$clog2(P + 1)'(P)
$clog2((P))'(P)
$clog2($clog2(P))'(P)
($clog2(P) + 1)'(P)
$clog2(pkg::SIZE)'(P)
width_fn(P)'(P)
`MACRO_GENERATED_CLOG2_CAST(P)
```

也不支持 multiple/named arguments、attributes/repetition、variable/non-constant target、macro token、
ambiguous smallest scope 或非连续 physical range。不得从 scoped tail `SIZE` 退化到当前 scope 同名参数；
已复现 package/local collision 会造成错绑定。

目标负例必须证明至少 `$bits(P)` 与 `$clog2(P + 1)` 不产生
`expression_sized_cast_type`；当 `P` 被选择 rename 时，write gate 必须 strict 原子失败且正式 output absent，
不得发布错误 gate。macro/ambiguous/range conflict 继续走现有 fail-closed 或 owner firewall。

另需一个 shadowing test：module parameter 与 generate localparam 同名，两个 fixed-path cast 必须通过各自最小
semantic scope 绑定不同 declaration record；不得 name-only 合并。

## 8. pinned riscv-dbg delta oracle

固定只读输入：

```text
stability HEAD: b99f5e43128964cc78a5c123a31f84e46df76934
riscv-dbg HEAD: 3d1205d8364fb49a2a97517d5d7029a991a82b8c
top: dm_top
filelist: projects/riscv-dbg/prepared/design.f
define: VERILATOR
profile: abi__parameters
formal-policy: none
```

当前 public runner：`FAIL_STRICT`、gate absent、公开稳定错误
`CLI_VNEXT_ORCHESTRATION_INVALID`。内部首错唯一为 `debug_rom/debug_rom.sv:2013..2020 RomSize`。

修复后必须：

```text
classification: PASS_EFFECTIVE
files: 8
mapping_records: 667
effective_renamed_records: 36
modified_tokens: 259
mapping action counts: 36 rename / 604 preserve / 27 unsupported
strict_compile_passed: true
gate_published: true
decrypt_exit_code: 0
restore.files: 8
restore_byte_identical: true
formal.status: FORMAL_NOT_RUN
```

新增 external edit 必须唯一为 `debug_rom/debug_rom.sv:2013..2020`，绑定 declaration `963..970`，
provenance=`expression_sized_cast_type`。`debug_rom_one_scratch.sv` 的同形源码不进入当前有效 semantic
instance graph，不得冻结为第二条 edit。

riscv-dbg gold 仍受 Yosys `dm_pkg.sv` frontend 边界阻挡，external `FORMAL_NOT_RUN` 不是等价证明；T080 的
功能等价证据由 compact actual-gate Formal 提供。

## 9. 允许修改

```text
docs/tasks/T080_expression_sized_cast_parameter.md
rtl_obfuscator/symbol_graph.py
tests/test_t080_expression_sized_cast_parameter.py
tests/fixtures/t080_expression_sized_cast/design.f
tests/fixtures/t080_expression_sized_cast/design.sv
docs/development/future_work.md
```

除此之外不得修改、删除、格式化或生成仓库文件。stability、riscv-dbg checkout 与 prepared input 全程只读；
所有临时 source/gate/restore/matrix/log 只能写入新的 `/private/tmp` 或测试临时目录。

## 10. 子 Agent 执行顺序

1. 完整阅读 AGENTS、T080、task workflow、subagent protocol、T069/T070/T071/T079、parameter collector、
   future work 和 Formal 文档；
2. 确认 exact starting HEAD/origin/main、clean、唯一 T080 READY；第一次实现/测试编辑前设置
   `IN_PROGRESS`，记录实际模型和第 9 节六个允许路径；
3. 运行第 11 节 baseline，逐字创建 fixture/target test，产品修改前复现第 4 节 atomic failure；
4. 只实现第 6 节 fixed typed helper/provenance/现有 binding 复用；先跑目标测试，再跑 shadow/NO-GO；
5. 运行 compact actual-gate strict/restore/Formal 正负例及 pinned riscv-dbg replay；
6. 严格执行第 11 节五条验收，记录 exact counts/ranges/provenance/diagnostics/repo clean；
7. 设置 `READY_FOR_REVIEW` 后停止；不得 stage、commit、push、设置 `ACCEPTED` 或创建 T081。

若 PySlang fixed path、fixture hash、shadow binding、external count/pin 或 Formal oracle冲突，必须记录最小
事实并停止，不得扩为 generic expression traversal、name search 或 owner-wide preserve。

## 11. 唯一验收命令

Baseline（实现前一次）：

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_t069_sized_cast_parameter \
  tests.test_t070_keyword_cast \
  tests.test_t071_type_parameter_defparam \
  tests.test_t079_parameter_default_occurrence -v
```

实现后五条：

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_t080_expression_sized_cast_parameter \
  tests.test_t069_sized_cast_parameter \
  tests.test_t070_keyword_cast \
  tests.test_t071_type_parameter_defparam \
  tests.test_t079_parameter_default_occurrence -v

external_root=/Users/lufengchi/Desktop/workspace/rtl_obfuscation_realworld_stability
test "$(git -C "$external_root" rev-parse HEAD)" = b99f5e43128964cc78a5c123a31f84e46df76934
test "$(git -C "$external_root/repos/riscv-dbg" rev-parse HEAD)" = 3d1205d8364fb49a2a97517d5d7029a991a82b8c
test -z "$(git -C "$external_root" status --short)"
test -z "$(git -C "$external_root/repos/riscv-dbg" status --short)"
replay_root=$(mktemp -d /private/tmp/t080-riscv-dbg-replay.XXXXXX)
sh "$external_root/projects/riscv-dbg/commands/materialize.sh" \
  "$external_root" "$replay_root/source"
conda run -n rtl_obfuscation python "$external_root/category_matrix_runner.py" \
  --study-root "$external_root" --project riscv-dbg \
  --source-root "$replay_root/source" \
  --filelist "$external_root/projects/riscv-dbg/prepared/design.f" --top dm_top \
  --define VERILATOR --output-root "$replay_root/matrix" \
  --profiles abi__parameters --formal-policy none
jq -e '
  (.results | length) == 1 and
  .results[0].profile == "abi__parameters" and
  .results[0].classification == "PASS_EFFECTIVE" and
  .results[0].effective_renamed_records == 36 and
  .results[0].cli_summary.summary.files == 8 and
  .results[0].cli_summary.summary.mapping_records == 667 and
  .results[0].cli_summary.summary.modified_tokens == 259 and
  ([.results[0].mapping_counts[] | .rename // 0] | add) == 36 and
  ([.results[0].mapping_counts[] | .preserve // 0] | add) == 604 and
  ([.results[0].mapping_counts[] | .unsupported // 0] | add) == 27 and
  .results[0].strict_compile_passed == true and
  .results[0].gate_published == true and
  .results[0].decrypt_exit_code == 0 and
  .results[0].restore_byte_identical == true and
  .results[0].restore.files == 8 and
  .results[0].formal.status == "FORMAL_NOT_RUN"
' "$replay_root/matrix/matrix.json"
jq -e '
  ([.mapping.records[]
    | .occurrences[]
    | select(
        .provenance == "expression_sized_cast_type" and
        .source_range.file == "debug_rom/debug_rom.sv" and
        .source_range.start == 2013 and
        .source_range.end == 2020)] | length) == 1 and
  ([.mapping.records[]
    | .occurrences[]
    | select(.provenance == "expression_sized_cast_type")] | length) == 1
' "$replay_root/matrix/abi__parameters/gate/mapping.json"
test -z "$(git -C "$external_root" status --short)"
test -z "$(git -C "$external_root/repos/riscv-dbg" status --short)"

conda run -n rtl_obfuscation python -m py_compile \
  rtl_obfuscator/symbol_graph.py tests/test_t080_expression_sized_cast_parameter.py

git diff --check HEAD

rg -x -- '- 状态：`READY_FOR_REVIEW`' \
  docs/tasks/T080_expression_sized_cast_parameter.md
```

目标 unittest 内必须执行 compact actual public gate strict compile、source-free restore、Formal 正例和固定
功能负例；不得 identity/copy-gold，不得弱化 `equiv_status -assert`。external replay 只验证
strict/restore，不得把 `FORMAL_NOT_RUN` 描述为功能等价。

## 12. Formal verification 记录

```text
formal_verification: PASS | FAIL | BLOCKED
gold: tests/fixtures/t080_expression_sized_cast
gate: <actual public rtl_encrypt output>
top: t080_expression_sized_cast
seq: 5
positive_command: <exact command>
positive_exit_code: <integer>
positive_result: <complete stdout JSON>
negative_gate: <actual gate copy with only frozen `assign hit_o = ~` mutation>
negative_compile: <catalog/top overlay counts>
negative_command: <exact command>
negative_exit_code: <nonzero integer>
negative_result: <unproven / equiv_status -assert summary>
external_formal: N/A; pinned riscv-dbg gold is blocked by documented Yosys frontend boundary
```

## 13. 子 Agent 执行记录

```text
status: READY_FOR_REVIEW
actual_model: gpt-5.6-sol / xhigh；当前调度器未提供 Luna 模型或 standard speed 参数，未声称使用 Luna
starting_head: 6d4b8025ef1a7b8f826a9a47cf1e47adfcb92f0e；parent/origin/main=d3072b56f86969936441927efdb5dffedcef67ee；branch main；start_time=2026-08-10T11:07:38+0800
allowed_files_check: PASS；启动 worktree clean；唯一活动任务 T080 READY；允许路径精确为本任务单、`rtl_obfuscator/symbol_graph.py`、`tests/test_t080_expression_sized_cast_parameter.py`、两个 T080 fixture 和 `docs/development/future_work.md`
baseline: PASS；`conda run -n rtl_obfuscation python -m unittest tests.test_t069_sized_cast_parameter tests.test_t070_keyword_cast tests.test_t071_type_parameter_defparam tests.test_t079_parameter_default_occurrence -v`；exit 0；Ran 32 tests；OK；四组既有 compact actual-gate Formal 正例 exit 0、固定功能负例 exit 1
pre_fix_characterization: PASS；fixture 精确为 10/199 bytes 且两个 SHA-256 匹配第 3 节；catalog/top overlay 0/0 + 0/0；typed path、candidate `169..176`、operand `179..186` 与第 5 节一致；现产品 graph 4/4/3/7，`RomSize` 仅有 operand `semantic_expression`；mapping 4/1/3/0、2 planned edits；目标测试实现前 Ran 10，2项 NO-GO/macro 安全边界通过，8项因缺少 `expression_sized_cast_type`、public strict 原子失败或相关 oracle 未满足而失败；public encrypt exit 1 `CLI_VNEXT_ORCHESTRATION_INVALID`，正式 gate absent
changed_files: `docs/tasks/T080_expression_sized_cast_parameter.md`；`rtl_obfuscator/symbol_graph.py`；`tests/test_t080_expression_sized_cast_parameter.py`；`tests/fixtures/t080_expression_sized_cast/design.f`；`tests/fixtures/t080_expression_sized_cast/design.sv`；`docs/development/future_work.md`；允许列表外零修改
commands: 目标开发测试 `conda run -n rtl_obfuscation python -m unittest tests.test_t080_expression_sized_cast_parameter -v` exit 0、Ran 10、OK；第 11 节实现后第 1 条完整命令 exit 0、Ran 42、OK；第 2 条 pinned riscv-dbg shell block exit 0；第 3 条 `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/symbol_graph.py tests/test_t080_expression_sized_cast_parameter.py` exit 0；最终第 4/5 条见本记录后只读 guard
results: PASS；fixture 10/199 bytes 与冻结 SHA-256 一致；target 10/10、相关回归 32/32；compact strict、source-free restore、Formal 正负和 external strict/restore oracle 全部满足；未运行 blanket discovery、RISC-V-Vector Formal 或历史 driver
typed_path_contract: PASS；新增独立 `_expression_sized_cast_identifier_token()`，只接受 exact `CastExpressionSyntax.right=ParenthesizedExpressionSyntax` 与无 attributes 的 `$clog2`/单 `OrderedArgumentSyntax`/固定 property-sequence wrapper/direct `IdentifierNameSyntax`；T069 `_sized_cast_identifier_token()` 定义未改；body 复用 `_sized_cast_target_from_scopes()`，default 复用 declaration `parentScope.lookupName()`；现有同 range/conflict/firewall 逻辑只增加显式 provenance 参数
compact_oracle: PASS；catalog/top overlay `0/0 + 0/0`；graph `4/4/4/8`；`RomSize` declaration `design.sv:121..128`，cast-left `169..176 expression_sized_cast_type`，operand `179..186 semantic_expression`；mapping `4 total / 1 rename / 3 preserve / 0 unsupported`，3 edits；public summary 1 file/4 records/3 modified tokens，strict true；decrypt 只从 gate+mapping 恢复 `design.sv`，逐字节一致且不生成 `design.f`
shadow_and_no_go: PASS；module parameter 与 generate localparam 同名时两个 fixed cast 分别绑定不同 declaration record；`$bits(P)'(P)`、`$clog2(P + 1)'(P)` 均无新 provenance，选择 rename 后 `REWRITE_GATE_COMPILE_FAILED` 且 output absent；macro token 无 occurrence/edit；other-target 同物理 range 固定 `SYMBOL_GRAPH_RANGE_CONFLICT`
riscv_dbg_replay: PASS；证据根 `/private/tmp/t080-riscv-dbg-replay.4ZUqnm`；stability `b99f5e43128964cc78a5c123a31f84e46df76934` 与 riscv-dbg `3d1205d8364fb49a2a97517d5d7029a991a82b8c` 前后 clean；`PASS_EFFECTIVE`，8 files，667 records，36 rename/604 preserve/27 unsupported，259 edits，strict/gate/decrypt true，restore 8 files byte-identical，`FORMAL_NOT_RUN`；唯一新 occurrence 为 symbol declaration `debug_rom/debug_rom.sv:963..970` 的 `2013..2020 expression_sized_cast_type`
formal_verification: PASS；gold `/Users/lufengchi/Desktop/workspace/rtl_obfuscation/tests/fixtures/t080_expression_sized_cast`；actual public gate `/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t080-formal-positive-6pz2qped/encrypt/gate`；top `t080_expression_sized_cast`；seq 5；positive command `/Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python /Users/lufengchi/Desktop/workspace/rtl_obfuscation/scripts/formal_equivalence.py --gold-filelist /Users/lufengchi/Desktop/workspace/rtl_obfuscation/tests/fixtures/t080_expression_sized_cast/design.f --gold-root /Users/lufengchi/Desktop/workspace/rtl_obfuscation/tests/fixtures/t080_expression_sized_cast --gate-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t080-formal-positive-6pz2qped/encrypt/gate/design.f --gate-root /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t080-formal-positive-6pz2qped/encrypt/gate --top t080_expression_sized_cast --seq 5`；exit 0；complete JSON `{"formal_equivalence":"pass","gate":"/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t080-formal-positive-6pz2qped/encrypt/gate","gold":"/Users/lufengchi/Desktop/workspace/rtl_obfuscation/tests/fixtures/t080_expression_sized_cast","seq":5,"top":"t080_expression_sized_cast"}`；negative gate `/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t080-formal-negative-3zu6o2i2/negative` 为 actual gate copy 且只增加冻结 `assign hit_o = ~`，catalog/top `0/0 + 0/0`；negative 同参数 Formal command exit 1，combined diagnostic 包含 `unproven` 与 `equiv_status -assert`；external Formal N/A，pinned riscv-dbg 受冻结 Yosys frontend 边界阻挡且本任务 formal-policy none
documentation: PASS；`future_work.md` 只把本任务 exact `$clog2(<direct IdentifierName>)'(...)`、lexical binding、新 provenance 与其他 expression-sized cast 保持 fail-closed 的边界写明
boundaries: 未支持第 7 节其他 system/user/scoped/compound/nested/named/multiple/attribute/repetition/macro expression-sized cast；不扩 category/API/schema/policy/mapping/rewrite/restore；非 parameter、records 外 target、ambiguous scope 与证据不足继续 fail-closed；external `FORMAL_NOT_RUN` 未描述为等价证明
review_request: 请主 Agent 仅按第 11 节五条命令独立验收 actual public gate、Formal 正负、pinned riscv-dbg oracle、py_compile、diff 与 READY_FOR_REVIEW guard；子 Agent 未 stage、commit、push、设置 ACCEPTED 或创建 T081
```

## 14. 主 Agent 验收

```text
review_date: 2026-08-10
reviewer: 主 Agent
starting_head: 6d4b8025ef1a7b8f826a9a47cf1e47adfcb92f0e；parent/origin/main=
  d3072b56f86969936441927efdb5dffedcef67ee；branch main
allowed_files: PASS；最终 worktree 精确为第 9 节六个路径；两个 fixture 仅含 design.f/design.sv，
  10/199 bytes 与冻结 SHA-256 完全匹配；允许列表外零修改
implementation_review: PASS；新增独立 fixed-path helper，只接受无 attributes 的
  `$clog2(<direct IdentifierName>)`、单 OrderedArgument 和固定 property/sequence wrapper；T069 direct
  helper 未改；body 复用最小 source-backed lexical scope 与 exact parameter declaration identity，default
  复用声明 parentScope lookup；range/macro/conflict 防火墙不变；无 category/API/schema/policy/mapping/
  rewrite/restore/CLI/Formal 分支或通用 expression traversal
target_and_regression: PASS；合同第 11 节第 1 条 exit 0；Ran 42 tests；OK
compact_oracle: PASS；graph 4/4/4/8；mapping 4 total、1 rename、3 preserve、0 unsupported；3 edits；
  strict compile 0/0 + 0/0；public gate 发布；decrypt 仅由 gate+mapping 恢复 design.sv 且逐字节一致
shadow_and_no_go: PASS；module/generate 同名参数分别绑定各自 declaration record；`$bits(P)` 与
  `$clog2(P + 1)` 不产生新 provenance，选择 rename 后严格编译原子失败且 output absent；macro 无
  occurrence/edit；other-target 同范围仍抛 SYMBOL_GRAPH_RANGE_CONFLICT
riscv_dbg_replay: PASS；Main-Agent fresh root=/private/tmp/t080-main-riscv-dbg.w64lmd；stability
  b99f5e43128964cc78a5c123a31f84e46df76934、riscv-dbg
  3d1205d8364fb49a2a97517d5d7029a991a82b8c 前后 clean；abi__parameters=PASS_EFFECTIVE，8 files、
  667 records、36 rename/604 preserve/27 unsupported、259 edits；strict/gate/decrypt/restore 全通过；
  唯一 expression_sized_cast_type 为 debug_rom/debug_rom.sv:2013..2020
formal_positive: PASS；Main-Agent compact actual public gate
  /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t080-formal-positive-750ea9c5/encrypt/gate；
  top=t080_expression_sized_cast；seq=5；exit 0；complete JSON formal_equivalence=pass
formal_negative: PASS as expected negative；Main-Agent actual-gate copy
  /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t080-formal-negative-yjz9e4nd/negative；只含冻结
  `assign hit_o = ~` 变更；strict compile 0/0 + 0/0；exit 1；目标断言匹配 `unproven` 与
  `equiv_status -assert`
external_formal: N/A；pinned riscv-dbg 按合同 formal-policy none，结果 FORMAL_NOT_RUN，未描述为等价证明
py_compile: PASS；合同第 11 节命令 exit 0
diff_check: PASS；`git diff --check HEAD` exit 0
ready_for_review_guard: PASS；精确 guard 在本次 ACCEPTED 状态变更前 exit 0
documentation: PASS；future_work 只记录本任务 exact 支持边界，并保留其他 expression-sized cast 与
  enum/base dimension fail-closed
forbidden_runs: 未运行 blanket discovery、历史 acceptance driver 或 RISC-V-Vector Formal
decision: ACCEPTED；只加密由 fixed typed path、最小语义作用域和 exact declaration identity 共同证明的
  参数引用，证据不足继续 fail-closed，符合“宁可少加密、不能加密错误”
delivery_commit: current acceptance commit；exact hash 在提交后报告并冻结进后继合同
push: NOT_RUN；等待对本次新交付的明确授权
successor: Main Agent 仅在本地交付提交完成后冻结下一任务
```
