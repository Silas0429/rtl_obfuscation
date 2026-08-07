# T077：同一 owner 多 quarantine 原因的确定性合并

- 状态：`ACCEPTED`
- 合同版本：1.0
- 设计日期：2026-08-07
- 设计负责人：主 Agent
- 实现负责人：代码子 Agent（请求模型：Luna extra high / standard speed；当前执行器无 Luna，实际配置必须如实记录）
- 前置任务：T076 `ACCEPTED`，交付提交 `56d4d648bd94c124f7939a91a7752a1cf9fa454c`
- 设计基线 HEAD：`56d4d648bd94c124f7939a91a7752a1cf9fa454c`
- 任务类型：SymbolGraph quarantine 合并与 compact rewrite 验证；产生 rewritten RTL

## 1. 单一目标

当同一个已证明的 ordinary physical `ModuleOwner` 同时命中两个或更多**现有** quarantine 条件时，
不再以 `SYMBOL_GRAPH_RANGE_CONFLICT` 拒绝整个工程；改为把该 owner 物理 module span 内的全部
SourceSymbol 原子标记为：

```text
support = unsupported
reason = owner_contains_multiple_unsupported_constructs
```

该 owner 内不得产生任何 rewrite edit；无关 sibling 和 selected-top internal symbols 继续真实改名。

T077 不增加任何 SystemVerilog 语法支持，只把“多个已知不支持条件同时存在”的全图拒绝收敛为
最小 owner 少加密。无法证明同一 owner、同一完整 module span 或 range 所有权时仍必须 fail-closed。

## 2. 起始状态与 baseline

```text
branch: main
HEAD: 56d4d648bd94c124f7939a91a7752a1cf9fa454c
origin/main: 56d4d648bd94c124f7939a91a7752a1cf9fa454c
worktree: clean
active implementation tasks: none
T071/T072/T073/T075/T076 baseline: 38/38 PASS
```

主 Agent 已执行：

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_t071_type_parameter_defparam \
  tests.test_t072_nested_generate \
  tests.test_t073_macro_owner \
  tests.test_t075_owner_occurrence_firewall \
  tests.test_t076_module_end_label -v
```

结果：exit 0，38 tests；五个 compact 工程的 strict compile、restore、actual-gate Formal 正例和
固定功能负例保持通过。

当前 `_apply_owner_quarantine()` 把 owner reason 存成单值；第二个不同 reason 会直接抛
`SYMBOL_GRAPH_RANGE_CONFLICT: physical module owner has conflicting quarantine reasons`。该行为安全，
但会拒绝本可通过“整 owner unsupported”继续处理的工程。

## 3. 冻结 quarantine 输入集合

T077 只允许合并以下已经由 T071–T073 建立的 owner 条件：

```text
owner_contains_type_parameter
defparam_binding_not_renamed
owner_contains_nested_generate
owner_contains_macro_source
```

集合大小：

- 0：owner 不受本 helper 保护；
- 1：完全保留现有单 reason 行为和已有 symbol-specific reason；
- 2–4：owner 及其精确物理 module span 内全部 symbols 使用
  `owner_contains_multiple_unsupported_constructs`。

`type_parameter_not_renamed` 是 T071 的 symbol-specific reason。若其物理 owner 只有 type parameter
一种 owner 条件，必须保持原值；若同一 owner 还有其他 quarantine 条件，则该 type parameter record
也统一使用 multiple reason，确保整个 owner 只有一个公开 quarantine 决策。

T075 的 `occurrence_in_quarantined_owner` 仍用于**其他 owner 的 eligible symbol** 穿入受保护 span；
不得被 T077 的 multiple reason 覆盖。

## 4. 冻结 compact fixture

子 Agent 必须逐字创建：

```text
source root: tests/fixtures/t077_multiple_quarantine
filelist: design.f
top: t077_top
defines: none
compile order:
  rtl/parameter_target.sv
  rtl/combined_owner.sv
  rtl/sibling.sv
  rtl/top.sv
```

### 4.1 `design.f`

```text
rtl/parameter_target.sv
rtl/combined_owner.sv
rtl/sibling.sv
rtl/top.sv
```

### 4.2 `rtl/parameter_target.sv`

```systemverilog
module t077_parameter_target #(
    parameter int WIDTH = 8
) (
    input  logic [7:0] data_i,
    output logic [7:0] data_o
);
    logic [7:0] target_state;

    assign target_state = data_i ^ WIDTH;
    assign data_o = target_state;
endmodule
```

### 4.3 `rtl/combined_owner.sv`

```systemverilog
module t077_combined_owner (
    input  logic [7:0] data_i,
    output logic [7:0] data_o
);
    logic [7:0] target_o;
    logic [7:0] nested_mix;

    t077_parameter_target u_target (
        .data_i(data_i),
        .data_o(target_o)
    );
    defparam u_target.WIDTH = 8;

    for (genvar outer = 0; outer < 2; outer++) begin : g_outer
        for (genvar inner = 0; inner < 1; inner++) begin : g_inner
            logic lane_value;
            assign lane_value = data_i[outer];
        end
    end

    assign nested_mix = data_i ^ 8'h0f;
    assign data_o = target_o ^ nested_mix;
endmodule
```

### 4.4 `rtl/sibling.sv`

```systemverilog
module t077_sibling (
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
module t077_top (
    input  logic [7:0] data_i,
    output logic [7:0] data_o
);
    logic [7:0] combined_o;
    logic [7:0] sibling_o;

    t077_combined_owner u_combined (
        .data_i(data_i),
        .data_o(combined_o)
    );
    t077_sibling u_sibling (
        .data_i(data_i),
        .data_o(sibling_o)
    );

    assign data_o = combined_o ^ sibling_o;
endmodule
```

`t077_combined_owner` 同时包含 defparam binding 与 nested generate；
`t077_parameter_target` 只命中 defparam quarantine；`t077_sibling` 和 selected top 用于证明修复不是
whole-graph preserve。

## 5. 最小实现合同

### 5.1 reason 集合与确定性决策

只扩展现有 `_apply_owner_quarantine()` 私有逻辑：

1. 对每个 ordinary owner 收集第 3 节四种已证明 reason 的集合；集合与遍历顺序无关；
2. nested/macro span 必须先按现有规则证明 source-backed、唯一且覆盖对应 owner declaration；
3. 同一 owner 的 nested span、macro span 与 T075 ordinary module span 必须完全相等；相同 owner/
   相同 span 的多 reason 是 T077 支持输入；不同 span 仍 `SYMBOL_GRAPH_OWNER_MISMATCH` 或
   `SYMBOL_GRAPH_RANGE_CONFLICT`；
4. reason 集合为 1 时保持 T071/T072/T073 的现有公开 reason，不改历史 oracle；
5. reason 集合大于 1 时，该 owner 与该精确 module span 内的 module-owned、generate-owned、
   type-parameter 和 macro-physical records 全部使用 multiple reason；
6. record 的 declaration/occurrences、symbol_id、owner_module、semantic_owner、impact、ABI、category
   均保持不变；只改变 `support/reason`；
7. 先完成 owner quarantine，再运行 T075 occurrence firewall；其他 owner 的 eligible symbol 穿入
   multiple owner 时仍整 symbol `unsupported/occurrence_in_quarantined_owner`；
8. 未知 reason、同一物理 token 多 owner、重叠/部分 module span、无法取得 ordinary span 均继续
   fail-closed，不得按 reason 优先级挑一个继续。

不得把 reason 拼成顺序相关字符串，不新增 list/report/schema 字段，也不得修改 mapping/rewrite。

### 5.2 文档同步

`docs/development/future_work.md` 只把原 “conflicting quarantine reasons 仍原子失败” 更新为：

- T077 已对同一 ordinary owner 的多个**现有** quarantine reason 使用
  `owner_contains_multiple_unsupported_constructs` 原子保护；
- owner/span 证据不一致和未知 reason 仍 fail-closed；
- 其他未解决的 cast/package/conversion/工程输入边界保持原样。

## 6. 冻结 machine oracle

目标 unittest 必须至少证明：

- catalog/top overlay 0/0 + 0/0，graph 复用同一 semantic view；
- 修复前 frozen fixture 精确抛
  `SYMBOL_GRAPH_RANGE_CONFLICT: physical module owner has conflicting quarantine reasons`，不得把旧错误
  当修复后兼容行为；
- 修复后 `t077_combined_owner` 的精确 module span 内所有 SourceSymbol 均为
  `unsupported/owner_contains_multiple_unsupported_constructs`，range records 完整保留；
- `t077_parameter_target` 所有 owner symbols 继续为
  `unsupported/defparam_binding_not_renamed`，单 reason oracle 不变；
- T071/T072/T073 单 reason compact oracle 全部保持；
- mapping 中 combined owner/span records 全部 action unsupported，实际 edits 为 0；
- sibling module/ports/internal 和 selected-top internal symbols 继续真实 rename；graph/mapping/edit 可由
  symbol_id 一对一审计，所有 ranges 无重复/重叠；
- unit-level exact-span audit：同一 owner 的两个已知 reason + 相同 span 可统一；同一 owner 的 nested/
  macro span 不同、missing ordinary span、跨 owner overlapping spans 继续精确 fail-closed；
- actual gate strict compile 0/0 + 0/0，restore 四个 `.sv` 文件 byte-identical；
- compact actual renamed gate Formal：top=t077_top、seq=5、exit 0、完整 JSON pass；
- 固定功能负例只把 actual gate 副本的 top 唯一 `assign data_o = ` 改为
  `assign data_o = ~`；strict compile 0/0 + 0/0，Formal 非零并含 `unproven` 与
  `equiv_status -assert`；
- future-work 精确同步 T077，并保留其他 frozen unresolved phrases。

exact counts 可以作为辅助，但不能替代 owner/span/action/strict/restore/Formal 证明。

## 7. 明确不包含

- 不新增 quarantine 条件或 SystemVerilog syntax 支持；
- 不把未知 exception/reason 自动归入 multiple；
- 不修改 T075 firewall reason、T076 closing label、module/port ABI 或 selected top boundary；
- 不修改 schema、mapping、rewrite、restore、orchestration、CLI 或 Formal；
- 不处理 expression-sized cast、package-qualified member、implicit conversion 或外部仓库输入；
- 不运行 RISC-V-Vector Formal、blanket discovery 或历史 acceptance driver。

## 8. 允许修改

```text
docs/tasks/T077_multiple_quarantine_reason_merge.md
rtl_obfuscator/symbol_graph.py
tests/test_t077_multiple_quarantine_reason_merge.py
tests/fixtures/t077_multiple_quarantine/design.f
tests/fixtures/t077_multiple_quarantine/rtl/parameter_target.sv
tests/fixtures/t077_multiple_quarantine/rtl/combined_owner.sv
tests/fixtures/t077_multiple_quarantine/rtl/sibling.sv
tests/fixtures/t077_multiple_quarantine/rtl/top.sv
docs/development/future_work.md
```

除此之外不得修改、删除、格式化或生成仓库文件。

## 9. 子 Agent 执行顺序

1. 完整阅读 AGENTS、T077、task workflow、subagent protocol、T071–T073、T075、T076、future work
   和 Formal 文档；
2. 确认 HEAD/origin/main、clean worktree、唯一 T077 READY；第一次实现编辑前设置
   `IN_PROGRESS`，记录实际模型、允许文件和 baseline；
3. 逐字创建 fixture；产品代码修改前记录第 6 节 pre-fix conflict；
4. 只实现第 5 节的 reason-set 合并和目标测试，不改其他 collector/层；
5. 逐条运行第 10 节五条验收，记录 exact command、测试数、owner/span/edit、strict/restore 和 Formal
   正负证据；
6. 确认允许路径外零修改，设置 `READY_FOR_REVIEW` 后停止；不得 stage、commit、push、设置
   `ACCEPTED` 或创建 T078。

若 compact fixture 没有产生冻结的 defparam+nested conflict、相同 owner span 无法唯一证明、修复需要
schema/API/允许列表外文件或 Yosys 不支持组合输入，必须记录最小事实并停止，不得改 fixture/oracle。

## 10. 唯一验收命令

Baseline（实现前一次）：

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_t071_type_parameter_defparam \
  tests.test_t072_nested_generate \
  tests.test_t073_macro_owner \
  tests.test_t075_owner_occurrence_firewall \
  tests.test_t076_module_end_label -v
```

实现后五条：

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_t077_multiple_quarantine_reason_merge -v

conda run -n rtl_obfuscation python -m unittest \
  tests.test_t071_type_parameter_defparam \
  tests.test_t072_nested_generate \
  tests.test_t073_macro_owner \
  tests.test_t075_owner_occurrence_firewall \
  tests.test_t076_module_end_label -v

conda run -n rtl_obfuscation python -m py_compile \
  rtl_obfuscator/symbol_graph.py \
  tests/test_t077_multiple_quarantine_reason_merge.py

git diff --check HEAD

rg -x -- '- 状态：`READY_FOR_REVIEW`' \
  docs/tasks/T077_multiple_quarantine_reason_merge.md
```

目标 unittest 内部必须执行 actual gate strict compile、restore、compact Formal 正例与固定功能负例；
不得 identity/copy-gold 或弱化 `equiv_status -assert`。

## 11. Formal verification 记录

```text
formal_verification: PASS | FAIL | BLOCKED
gold: tests/fixtures/t077_multiple_quarantine
gate: <actual write_gate_vnext output>
top: t077_top
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
status: READY_FOR_REVIEW
actual_model: gpt-5.6-sol / xhigh；当前调度器未提供 Luna 模型或 standard speed 参数，未声称使用 Luna
starting_head: 97977ad0e5426d0ea10ab09f8bc0fea774cf37bf；origin/main 同提交；worktree clean
allowed_files_check: PASS；合同第 8 节九个允许路径无既有未提交修改；唯一活动实现任务为 T077
baseline: PASS；`conda run -n rtl_obfuscation python -m unittest tests.test_t071_type_parameter_defparam tests.test_t072_nested_generate tests.test_t073_macro_owner tests.test_t075_owner_occurrence_firewall tests.test_t076_module_end_label -v`；exit 0；Ran 38 tests；OK
pre_fix_characterization: PASS；冻结 fixture catalog/top overlay 为 0/0 + 0/0；未改产品代码时 `build_symbol_graph()` 精确抛 `SymbolGraphError(code="SYMBOL_GRAPH_RANGE_CONFLICT")`，文本 `SYMBOL_GRAPH_RANGE_CONFLICT: physical module owner has conflicting quarantine reasons`
changed_files: docs/tasks/T077_multiple_quarantine_reason_merge.md；rtl_obfuscator/symbol_graph.py；tests/test_t077_multiple_quarantine_reason_merge.py；tests/fixtures/t077_multiple_quarantine/design.f；tests/fixtures/t077_multiple_quarantine/rtl/{parameter_target,combined_owner,sibling,top}.sv；docs/development/future_work.md
commands: 第 10 节 baseline 一次；实现后目标 unittest 两次（最终证据取第二次）；冻结 38-test 回归首次暴露并修正 future-work 的历史短语兼容断言后最终重跑；目标单项文档测试一次；第 10 节 py_compile；最终 diff/status guard
results: 目标 unittest 最终 exit 0，Ran 8 tests，OK；T071/T072/T073/T075/T076 回归最终 exit 0，Ran 38 tests，OK；py_compile exit 0；git diff --check HEAD exit 0；READY_FOR_REVIEW guard exit 0
review_rework: 首次 post-change 38-test 回归仅 T076 文档测试失败，原因是 future-work 删除了历史短语 `conflicting quarantine reasons`；文档改为明确“原边界已由 T077 收敛”并保留历史名词，未改产品代码或 T077 oracle；对应单项与最终 38-test 回归均通过
schema_or_behavior: 不增加 schema/category/record/report/API；`_apply_owner_quarantine()` 只将四种冻结 owner condition 确定性收集为 set；单 reason 保持历史公开 reason，多 reason 且 ordinary/nested/macro span 完全一致时才统一为 `owner_contains_multiple_unsupported_constructs`；随后复用 T075 whole-symbol firewall，`occurrence_in_quarantined_owner` 不变
results_oracle: catalog/top overlay 0/0 + 0/0；graph 27/27/35/62；combined span 内 11 个 records 全部 unsupported/multiple reason，含 module、outer/inner genvar、g_outer/g_inner generate block；parameter target 5 个 owner records 全部保持 unsupported/defparam_binding_not_renamed；mapping total/rename/preserve/unsupported 27/8/3/16；actual edits 19，combined/target protected spans 均为 0，sibling module/ports/internal 与 selected-top internal 均有真实 edit；ranges 一对一且无重复/重叠
span_fail_closed: PASS；unit exact-span audit 证明同 owner 的 defparam+nested 相同 span 可统一，跨 owner eligible occurrence 仍为 occurrence_in_quarantined_owner；同 owner nested/macro span 不同精确 SYMBOL_GRAPH_OWNER_MISMATCH，missing ordinary span 精确 SYMBOL_GRAPH_OWNER_MISMATCH，跨 owner overlapping spans 精确 SYMBOL_GRAPH_RANGE_CONFLICT
strict_compile: PASS；actual renamed gate catalog/top overlay 0/0 + 0/0；fixed `~` negative gate 同为 0/0 + 0/0
restore: PASS；actual gate 恢复四个 `.sv` 文件并逐文件 byte-identical
documentation: PASS；future-work 记录 T077 multiple reason 原子保护、owner/span/未知 reason fail-closed，并保留 expression-sized cast、package-qualified member、syntax-less conversion 与工程输入边界
boundaries: 只合并四种既有 ordinary-owner quarantine condition；不新增 syntax/category，不自动归并未知 reason，不修改 T075/T076、mapping/rewrite/restore/CLI/Formal；未运行 RISC-V-Vector Formal、blanket discovery 或历史 driver
cleanup_candidates: none
formal_verification: PASS
gold: tests/fixtures/t077_multiple_quarantine
gate: /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t077-formal-positive-79pk8kpe/gate；actual `write_gate_vnext` output，19 个真实 edits
top: t077_top
seq: 5
positive_command: /Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python scripts/formal_equivalence.py --gold-filelist tests/fixtures/t077_multiple_quarantine/design.f --gold-root tests/fixtures/t077_multiple_quarantine --gate-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t077-formal-positive-79pk8kpe/gate/design.f --gate-root /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t077-formal-positive-79pk8kpe/gate --top t077_top --seq 5
positive_exit_code: 0
positive_result: {"formal_equivalence":"pass","gate":"/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t077-formal-positive-79pk8kpe/gate","gold":"tests/fixtures/t077_multiple_quarantine","seq":5,"top":"t077_top"}
negative_gate: /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t077-formal-negative-yqm8h74k/negative；actual gate 副本且只含冻结 `assign data_o = ~` 功能变更
negative_compile: catalog 0/0；top overlay 0/0
negative_command: /Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python scripts/formal_equivalence.py --gold-filelist tests/fixtures/t077_multiple_quarantine/design.f --gold-root tests/fixtures/t077_multiple_quarantine --gate-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t077-formal-negative-yqm8h74k/negative/design.f --gate-root /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t077-formal-negative-yqm8h74k/negative --top t077_top --seq 5
negative_exit_code: 1
negative_result: `equiv_status -assert`；16 unproven cells 初始分组，最终 module equiv 保留 8 unproven cells；ERROR 报告 unproven equivalence
review_request: 请主 Agent 独立复跑第 10 节、审计 reason set 与 owner/span/action 证据并决定验收；子 Agent 未 stage、commit、push、设置 ACCEPTED 或创建 T078
```

## 13. 主 Agent 验收

```text
status: ACCEPTED
accepted_date: 2026-08-07
accepted_head_before_commit: 97977ad0e5426d0ea10ab09f8bc0fea774cf37bf
actual_subagent_model: gpt-5.6-sol / xhigh; Luna and standard-speed controls were unavailable and were not claimed
allowed_files: PASS; exactly the nine section-8 paths changed; no existing fixture, T071–T076
  test/contract, schema, mapping, rewrite, restore, orchestration, CLI or Formal script changed
fixture_review: PASS; design.f and four .sv files match the frozen section-4 content exactly
reason_set_review: PASS; only the four frozen owner conditions are accepted; per-owner set membership is
  traversal-order independent; size one retains the T071/T072/T073 reason; size greater than one uses only
  owner_contains_multiple_unsupported_constructs; type_parameter_not_renamed remains for a type-only owner
  and is unified only when its owner has another frozen condition
owner_span_review: PASS; ordinary, nested and macro spans must resolve to the same exact source-backed
  ModuleOwner span before merging; different or missing same-owner spans raise OWNER_MISMATCH; overlapping
  protected owners and multiple containing owners raise RANGE_CONFLICT
firewall_review: PASS; owner quarantine completes before T075 whole-symbol occurrence audit; an eligible
  external symbol crossing the protected span keeps occurrence_in_quarantined_owner rather than the multiple
  owner reason
forbidden_implementation_review: PASS; no unknown-reason fallback, reason priority, order-dependent joined
  string, schema/report field, source scan, new collector, mapping/rewrite special case or syntax expansion
target_tests: PASS; exact section-10 command exit 0; Ran 8 tests; OK
regression: PASS; exact T071/T072/T073/T075/T076 command exit 0; Ran 38 tests; OK
py_compile: PASS; exact section-10 command exit 0
diff_check: PASS; `git diff --check HEAD` exit 0 with no output
ready_for_review_guard: PASS; exact guard exit 0 before this ACCEPTED status change
graph_oracle: PASS; symbols/declarations/occurrences/total_ranges 27/27/35/62; all physical ranges are
  unique and non-overlapping
combined_owner: PASS; exact combined module span contains 11 records across module, module-owned and
  generate-owned categories; every record is unsupported/owner_contains_multiple_unsupported_constructs
single_reason_regression: PASS; five t077_parameter_target records remain
  unsupported/defparam_binding_not_renamed; T071/T072/T073 exact single-reason tests remain green
mapping_oracle: PASS; total/rename/preserve/unsupported 27/8/3/16; actual edits 19; combined and target
  protected spans contain zero edits; sibling module/ports/internal and selected-top internal symbols
  produce real edits
documentation: PASS; future work records the former conflicting quarantine reasons boundary as T077
  completed while retaining owner/span/unknown-reason fail-closed and all other frozen unresolved phrases
strict_compile: PASS; Main-Agent actual renamed gate catalog/top overlay diagnostics 0/0 + 0/0
restore_byte_identity: PASS; all four restored .sv files equal frozen input bytes
formal_positive: PASS; Main-Agent actual gate
  /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t077-formal-positive-mepc8f43/gate;
  top=t077_top; seq=5; exit 0; complete JSON formal_equivalence=pass
formal_negative: PASS as expected negative; Main-Agent actual-gate copy
  /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t077-formal-negative-n63jijwj/negative;
  only the frozen `assign data_o = ~` mutation; strict compile 0/0 + 0/0; exit 1;
  eight unproven cells remain and output contains `unproven` plus `equiv_status -assert`
review_rework: PASS; T076 historical phrase remained in future work with an explicit T077 completion
  statement; no old test or product behavior was weakened
forbidden_runs: blanket discovery, historical acceptance drivers and RISC-V-Vector Formal were not run
decision: ACCEPTED; T077 safely converts known multi-reason whole-graph refusal into minimum-owner unsupported
delivery_commit: current acceptance commit; exact hash is reported after commit and frozen into the successor contract
push: pending current acceptance commit
successor: Main Agent will create the next task only after this acceptance commit is pushed
```
