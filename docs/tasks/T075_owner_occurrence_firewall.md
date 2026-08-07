# T075：受保护 owner 的跨 owner occurrence 防火墙

- 状态：`ACCEPTED`
- 合同版本：1.0
- 设计日期：2026-08-07
- 设计负责人：主 Agent
- 实现负责人：代码子 Agent（请求模型：Luna extra high / standard speed；当前执行器无 Luna，实际启动配置必须在执行记录中如实填写）
- 前置任务：T074 `ACCEPTED`，交付提交 `05c630437ff6cbb51d096b5eda8ad2b2f123b273`
- 设计基线 HEAD：`05c630437ff6cbb51d096b5eda8ad2b2f123b273`
- 任务类型：SymbolGraph 安全防火墙与 compact rewrite 验证；产生 rewritten RTL

## 1. 单一目标

在不扩大任何 SystemVerilog 支持范围的前提下，为 T071–T073 已存在的 module-owner quarantine
增加一个 fail-closed 防火墙：只要一个原本 eligible 的 `SourceSymbol` 有任一 declaration 或
occurrence 的完整物理范围落入受保护 owner，其整条 symbol record 都必须降级为

```text
support = unsupported
reason = occurrence_in_quarantined_owner
```

该 symbol 的 declaration 和全部 occurrences 都不得产生 rewrite edit。不能只删除受保护 owner
内的单个 occurrence 后继续改名，也不能依赖 strict compile 来发现半改名。

T075 的正确性目标是：**宁可少加密整个 symbol，也不能在受保护 owner 内产生任何跨 owner
rename edit。**

## 2. 起始状态与已验证基线

```text
branch: main
HEAD: 05c630437ff6cbb51d096b5eda8ad2b2f123b273
origin/main: 05c630437ff6cbb51d096b5eda8ad2b2f123b273
worktree: clean
active implementation tasks: none
T071/T072/T073 regression: 24/24 PASS
```

主 Agent 已执行冻结 baseline：

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_t071_type_parameter_defparam \
  tests.test_t072_nested_generate \
  tests.test_t073_macro_owner -v
```

结果：exit 0，24 tests，T071/T072/T073 compact gate strict compile、restore byte identity、
actual-gate Formal 正例和固定功能负例均保持原有结果。

当前 `_apply_owner_quarantine()` 只按 symbol 自身 `owner_module` 或 declaration 所在的
nested/macro span 设置 unsupported；它没有对每个外部 symbol 的 occurrences 做受保护 span
审计。因此已有 quarantine 可以阻止 owner 自身 symbol 改名，却不能证明该 owner 的物理范围内
没有来自其他 owner 的 rename edit。

## 3. 冻结 compact fixture

子 Agent 必须逐字创建以下输入；不得为了迎合实现修改结构、module 名或功能表达式。

```text
source root: tests/fixtures/t075_owner_occurrence_firewall
filelist: design.f
top: t075_top
defines: none
compile order:
  rtl/parameter_target.sv
  rtl/child.sv
  rtl/defparam_owner.sv
  rtl/sibling.sv
  rtl/top.sv
```

### 3.1 `design.f`

```text
rtl/parameter_target.sv
rtl/child.sv
rtl/defparam_owner.sv
rtl/sibling.sv
rtl/top.sv
```

### 3.2 `rtl/parameter_target.sv`

```systemverilog
module t075_parameter_target #(
    parameter int WIDTH = 8
) (
    input  logic [WIDTH-1:0] data_i,
    output logic [WIDTH-1:0] data_o
);
    assign data_o = data_i;
endmodule
```

### 3.3 `rtl/child.sv`

```systemverilog
module t075_child (
    input  logic [7:0] data_i,
    output logic [7:0] data_o
);
    logic [7:0] child_state;

    assign child_state = data_i ^ 8'h3c;
    assign data_o = child_state;
endmodule
```

### 3.4 `rtl/defparam_owner.sv`

```systemverilog
module t075_defparam_owner (
    input  logic [7:0] data_i,
    output logic [7:0] data_o
);
    logic [7:0] configured_o;
    logic [7:0] child_o;

    t075_parameter_target u_target (
        .data_i(data_i),
        .data_o(configured_o)
    );
    defparam u_target.WIDTH = 8;

    t075_child u_child (
        .data_i(configured_o),
        .data_o(child_o)
    );

    assign data_o = child_o;
endmodule
```

### 3.5 `rtl/sibling.sv`

```systemverilog
module t075_sibling (
    input  logic [7:0] data_i,
    output logic [7:0] data_o
);
    logic [7:0] sibling_state;

    assign sibling_state = ~data_i;
    assign data_o = sibling_state;
endmodule
```

### 3.6 `rtl/top.sv`

```systemverilog
module t075_top (
    input  logic [7:0] data_i,
    output logic [7:0] data_o
);
    logic [7:0] protected_o;
    logic [7:0] sibling_o;

    t075_defparam_owner u_protected (
        .data_i(data_i),
        .data_o(protected_o)
    );
    t075_sibling u_sibling (
        .data_i(data_i),
        .data_o(sibling_o)
    );

    assign data_o = protected_o ^ sibling_o;
endmodule
```

`t075_defparam_owner` 与 `t075_parameter_target` 沿用 T071 的
`defparam_binding_not_renamed` quarantine。`t075_child` 自身不是 quarantined owner，但其
module-type occurrence 与 named-port member occurrences 位于 `t075_defparam_owner` 的受保护
物理 span 内；它们是 T075 防火墙的核心跨 owner 输入。`t075_sibling` 和 selected top 提供不受
影响的真实改名证据，防止实现退化成全图 preserve。

## 4. 最小实现合同

### 4.1 受保护 owner 与 span 的唯一来源

只允许复用当前 semantic compilation、`SourceCatalog.modules`、T071 type/defparam owner 证据、
T072 nested span 和 T073 macro span。对每个已 quarantine 的 ordinary physical
`ModuleOwner`，必须取得唯一、source-backed、覆盖完整 module syntax 的 `SourceRange`。

- 不得扫描 `module` / `endmodule` 文本猜 span；
- 不得按 fixture、文件名、module 名、symbol spelling 或固定 offset 分支；
- 不得创建第二套 compilation、collector、SourceCatalog 或 public owner API；
- 无法为 quarantine owner 证明唯一 physical module span 时，抛出现有
  `SymbolGraphError` 家族的稳定 fail-closed 诊断，不得继续发布 mapping。

T075 只为现有 quarantine 补足 occurrence firewall，不改变产生 quarantine 的条件或原有 reason。

### 4.2 整 symbol 防火墙

owner quarantine 完成后，对每个 `SourceSymbol` 审计：

1. declaration 与每个 occurrence 都使用现有精确 `SourceRange`；
2. 一个 range 必须完全落在零个或一个受保护 module span 内；
3. 与 span 仅部分重叠、落入多个 span、或物理 owner 无法唯一证明时必须 fail-closed；
4. symbol 已因自身 owner、type parameter、nested 或 macro 原因 unsupported 时保留原 reason；
5. 只有原本 `support="eligible"` 且至少一个 range 落入不同 quarantined owner span 的 symbol，
   整条 record 降级为 `unsupported/occurrence_in_quarantined_owner`；
6. 降级后 declaration 与所有 occurrences 都保留在 graph/range audit 中；不得删除 range、拆 record
   或只抑制局部 edit；
7. 同一外部 symbol 穿入多个已证明受保护 owner 时仍使用同一 firewall reason 并整体降级；这不
   赋予 T075 合并 owner 自身 conflicting quarantine reasons 的权限。

`MappingVNext`、rewrite 和 restore 不增加特例：它们只消费 SymbolGraph 的完整 unsupported record。

### 4.3 冻结 machine oracle

目标 unittest 必须至少证明：

- catalog 与 top overlay 均为 `parse_errors=0, semantic_errors=0`；
- graph 与 mapping 保持一条 semantic symbol 对应一条 record，range audit 无重叠/重复；
- `t075_defparam_owner` 和 `t075_parameter_target` 保持
  `unsupported/defparam_binding_not_renamed`；
- `t075_child` 的 module symbol，以及能由当前 graph 语义绑定到 child port 的 named-port member
  symbols，全部为 `unsupported/occurrence_in_quarantined_owner`；
- 上述 firewall symbols 的 declaration 与全部 occurrences 保留，mapping action 为 unsupported，
  rewrite edit 数为 0；
- `t075_child.child_state` 等只在安全 child owner 内出现的内部 symbol 仍 eligible 并真实改名；
- `t075_sibling` 至少有一个 module/port/internal symbol 真实改名；selected top 内部至少有一个
  symbol 真实改名，证明不是全图 preserve；
- rewrite execution 的每个 edit 都能回指唯一 symbol record，且 **没有任何 edit range 落入
  `t075_defparam_owner` 或 `t075_parameter_target` 的受保护 module span**；
- actual gate strict compile 通过，restore 的 5 个 `.sv` 文件与输入逐字节相同；
- compact actual renamed gate Formal：top=`t075_top`、seq=`5`、exit 0、JSON
  `formal_equivalence="pass"`；
- 固定功能负例只在 gate 副本中把 `rtl/top.sv` 唯一的
  `assign data_o = ` 替换成 `assign data_o = ~`；负例 strict compile 仍为 0/0，Formal 必须非零，
  输出包含 `unproven` 与 `equiv_status -assert`。

不得只断言固定 symbol 数量或 edit 数量；数量可以作为 compact fixture 的辅助 oracle，但必须同时
完成上述 owner/span/action/strict/restore/Formal 证明。

## 5. 明确不包含

- 不支持新的 category、SystemVerilog syntax、macro expansion、package/member、cast 或 end label；
- 不合并 type-parameter、nested-generate、macro 的 conflicting quarantine reasons；
- 不修改现有 reason、schema、symbol_id、impact、ABI、category 或 mapping report；
- 不修改 `mapping_vnext.py`、`rewrite_vnext.py`、`restore_vnext.py`、orchestration、CLI 或 Formal 脚本；
- 不增加 fallback、warning-only、best-effort、文本搜索或 compile-failure 后降级成功；
- 不运行 RISC-V-Vector Formal、blanket discovery 或历史 acceptance driver；
- 不修复 `register_interface` 之外的真实仓库输入，不引入外部仓库；外部工程扩测属于后续独立任务。

## 6. 允许修改

```text
docs/tasks/T075_owner_occurrence_firewall.md
rtl_obfuscator/symbol_graph.py
tests/test_t075_owner_occurrence_firewall.py
tests/fixtures/t075_owner_occurrence_firewall/design.f
tests/fixtures/t075_owner_occurrence_firewall/rtl/parameter_target.sv
tests/fixtures/t075_owner_occurrence_firewall/rtl/child.sv
tests/fixtures/t075_owner_occurrence_firewall/rtl/defparam_owner.sv
tests/fixtures/t075_owner_occurrence_firewall/rtl/sibling.sv
tests/fixtures/t075_owner_occurrence_firewall/rtl/top.sv
```

除此之外不得修改、删除、格式化或生成仓库文件。fixture 只服务于 T075，必须使用 `.sv`。

## 7. 子 Agent 强制执行顺序

1. 完整阅读 `AGENTS.md`、本合同、`docs/tasks/README.md`、
   `docs/development/process/refactor_subagent_protocol.md`、T071/T072/T073 owner quarantine 合同相关
   章节和 `docs/formal_verification.md`；
2. 检查 HEAD、origin/main、工作树和唯一活动任务；第一次实现编辑前将本合同状态改为
   `IN_PROGRESS`，记录真实模型配置、starting HEAD、允许文件和开始命令；
3. 运行第 8 节 baseline；然后逐字创建第 3 节 fixture；
4. 在改产品代码前用只读 probe 或预期失败测试记录当前跨 owner symbol 仍 eligible/产生 protected
   span edit 的基线事实；不得把该旧行为保留为兼容 oracle；
5. 只在 `symbol_graph.py` 实现第 4 节最小防火墙，增量运行目标测试；
6. 运行第 8 节全部验收，记录实际测试数、strict/restore、positive/negative Formal 命令、exit code
   和关键 JSON；
7. 确认允许文件外零修改、无新增兼容层/fallback，填写未覆盖边界与 cleanup candidates；
8. 将状态设置为 `READY_FOR_REVIEW` 后停止；不得 stage、commit、push、设置 `ACCEPTED` 或创建 T076。

若 PySlang 无法提供唯一 ordinary module syntax span、目标 fixture 的 child module/port 语义绑定与
合同不符、实现需要允许列表外文件或 Formal 只能通过 identity/copy-gold，必须记录具体证据并停止，
不得自行改变 fixture、oracle 或架构。

## 8. 唯一验收命令

Baseline（实现前只运行一次，并记录 24/24）：

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_t071_type_parameter_defparam \
  tests.test_t072_nested_generate \
  tests.test_t073_macro_owner -v
```

实现完成后只运行以下五条：

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_t075_owner_occurrence_firewall -v

conda run -n rtl_obfuscation python -m unittest \
  tests.test_t071_type_parameter_defparam \
  tests.test_t072_nested_generate \
  tests.test_t073_macro_owner -v

conda run -n rtl_obfuscation python -m py_compile \
  rtl_obfuscator/symbol_graph.py \
  tests/test_t075_owner_occurrence_firewall.py

git diff --check HEAD

rg -x -- '- 状态：`READY_FOR_REVIEW`' \
  docs/tasks/T075_owner_occurrence_firewall.md
```

第一条目标 unittest 必须内部执行第 4.3 节的 strict gate、restore、compact Formal 正例和固定功能
负例；不得用 identity comparison、复制 gold 或删除 `equiv_status -assert` 代替 actual gate 证明。

## 9. Formal verification 交付格式

```text
formal_verification: PASS | FAIL | BLOCKED
gold: tests/fixtures/t075_owner_occurrence_firewall
gate: <target unittest 产生的 actual renamed gate 临时目录>
top: t075_top
seq: 5
positive_command: <exact conda-environment Python command printed by test>
positive_exit_code: <integer>
positive_result: <stdout JSON>
negative_gate: <actual gate copy with only frozen top assign mutation>
negative_command: <exact conda-environment Python command printed by test>
negative_compile: <catalog/top-overlay error counts>
negative_exit_code: <nonzero integer>
negative_result: <unproven / equiv_status -assert summary>
```

## 10. 子 Agent 执行记录

```text
status: READY_FOR_REVIEW
actual_model: gpt-5.6-sol / xhigh; 当前调度器未提供 Luna 模型或 standard speed 参数，未声称使用 Luna
starting_head: ae22c8fb17c3140fc71fbb38dd98137be4400e88; origin/main 同提交；worktree clean
allowed_files_check: PASS; 合同第 6 节九个允许路径无既有未提交修改，唯一活动任务为 T075 READY
baseline: PASS; `conda run -n rtl_obfuscation python -m unittest tests.test_t071_type_parameter_defparam tests.test_t072_nested_generate tests.test_t073_macro_owner -v`; exit 0; Ran 24 tests; OK
pre_fix_characterization: reproduced with a read-only semantic probe after adding the frozen fixture; compile 0/0 + 0/0; protected span `rtl/defparam_owner.sv:0..409`; external eligible records `t075_child` module and child ports `data_i/data_o` have occurrences at 286..296, 316..322 and 347..353 inside that span, and all three ranges become actual rewrite edits under the pre-fix implementation
changed_files: docs/tasks/T075_owner_occurrence_firewall.md; rtl_obfuscator/symbol_graph.py; tests/test_t075_owner_occurrence_firewall.py; tests/fixtures/t075_owner_occurrence_firewall/design.f; tests/fixtures/t075_owner_occurrence_firewall/rtl/{parameter_target,child,defparam_owner,sibling,top}.sv
commands: section 8 baseline once; then all five frozen acceptance commands exactly as written
results: target unittest exit 0, Ran 7 tests, OK; T071/T072/T073 regression exit 0, Ran 24 tests, OK; py_compile exit 0; git diff --check HEAD exit 0; READY_FOR_REVIEW guard exit 0
schema_or_behavior: no schema/API/category/reason changes except the authorized stable `occurrence_in_quarantined_owner` value; reused the existing semantic compilation and ordinary physical module spans; every source range is audited for zero-or-one complete protected-span containment, partial/multiple/unknown containment fails closed, and an eligible cross-owner hit downgrades the entire unchanged SourceSymbol record
results_oracle: graph range audit 26/26/38/64; mapping total/rename/preserve/unsupported 26/9/3/14; 22 actual edits; `t075_child` module and child ports `data_i/data_o` are the three firewall records; protected-owner actual edits 0; child_state, sibling module/port/internal and selected-top internal records still produce real edits; strict compile 0/0 + 0/0; five restored `.sv` files byte-identical
boundaries: existing type-parameter/defparam/nested-generate/macro quarantine discovery only; no new syntax/category or quarantine-reason merge; package/interface/cast/end-label/macro expansion and real-repository remediation remain out of scope; missing, disagreeing, overlapping or partially intersecting owner/range evidence is fail-closed
cleanup_candidates: none; no obsolete test, compatibility layer or fallback was introduced
formal_verification: PASS
gold: tests/fixtures/t075_owner_occurrence_firewall
gate: /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t075-formal-positive-2uurna3f/gate (actual `write_gate_vnext` output; 22 real edits)
top: t075_top
seq: 5
positive_command: /Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python scripts/formal_equivalence.py --gold-filelist tests/fixtures/t075_owner_occurrence_firewall/design.f --gold-root tests/fixtures/t075_owner_occurrence_firewall --gate-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t075-formal-positive-2uurna3f/gate/design.f --gate-root /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t075-formal-positive-2uurna3f/gate --top t075_top --seq 5
positive_exit_code: 0
positive_result: {"formal_equivalence":"pass","top":"t075_top","seq":5}
negative_gate: /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t075-formal-negative-ntsde222/negative; only frozen `assign data_o = ~` mutation
negative_command: /Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python scripts/formal_equivalence.py --gold-filelist tests/fixtures/t075_owner_occurrence_firewall/design.f --gold-root tests/fixtures/t075_owner_occurrence_firewall --gate-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t075-formal-negative-ntsde222/negative/design.f --gate-root /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t075-formal-negative-ntsde222/negative --top t075_top --seq 5
negative_compile: catalog 0/0; top overlay 0/0
negative_exit_code: 1
negative_result: `equiv_status -assert`; 8 unproven cells remain in module equiv; ERROR reports unproven equivalence
review_request: Main Agent independently rerun section 8, inspect owner/span/action evidence, and decide acceptance; sub-Agent did not stage, commit, push, set ACCEPTED or create T076
```

## 11. 主 Agent 验收

```text
status: ACCEPTED
accepted_date: 2026-08-07
accepted_head_before_commit: ae22c8fb17c3140fc71fbb38dd98137be4400e88
actual_subagent_model: gpt-5.6-sol / xhigh; Luna and standard-speed controls were unavailable and were not claimed
allowed_files: PASS; exactly the nine section-6 paths changed; no existing fixture, mapping, rewrite,
  restore, orchestration, CLI, schema, public documentation or Formal script changed
fixture_review: PASS; design.f and all five .sv files match the frozen section-3 content exactly;
  all files use SystemVerilog .sv syntax and t075_top is unchanged
implementation_review: PASS; the existing semantic compilation supplies unique ordinary physical
  module spans; existing type/defparam/nested/macro quarantine discovery and reasons are unchanged;
  every declaration/occurrence range is audited for complete zero-or-one protected-span containment;
  partial, multiple, missing or disagreeing evidence fails closed; an eligible cross-owner hit replaces
  only support/reason on the whole unchanged SourceSymbol record
forbidden_implementation_review: PASS; no spelling/file/module-name/offset branch, source text scan,
  second collector/compilation, range deletion, partial edit suppression, fallback, warning-only path,
  public API, category, symbol_id, schema, mapping, rewrite, restore or CLI special case was added
target_tests: PASS; exact section-8 command exit 0; Ran 7 tests; OK
regression: PASS; exact T071/T072/T073 command exit 0; Ran 24 tests; OK
py_compile: PASS; exact section-8 command exit 0
diff_check: PASS; `git diff --check HEAD` exit 0 with no output
ready_for_review_guard: PASS; exact guard exit 0 before this ACCEPTED status change
graph_oracle: PASS; symbols/declarations/occurrences/total_ranges 26/26/38/64;
  one-to-one graph/mapping records and unique physical ranges verified
mapping_oracle: PASS; total/rename/preserve/unsupported 26/9/3/14; actual edits 22
owner_span_audit: PASS; protected defparam owner span rtl/defparam_owner.sv:0..409 and protected
  parameter-target span are uniquely source-backed; t075_child module and child ports data_i/data_o
  are the three unsupported/occurrence_in_quarantined_owner records; their declaration and all
  occurrences remain auditable; both protected spans contain zero actual rewrite edits
non_vacuous_encryption: PASS; child_state, sibling module/ports/internal symbol and selected-top
  internal symbols still produce real edits, so the fix is not whole-graph preserve
strict_compile: PASS; Main-Agent actual renamed gate catalog/top overlay diagnostics 0/0 + 0/0
restore_byte_identity: PASS; all five restored .sv files equal their frozen input bytes
formal_positive: PASS; Main-Agent actual gate
  /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t075-formal-positive-v3y9auwg/gate;
  top=t075_top; seq=5; exit 0; complete JSON formal_equivalence=pass
formal_negative: PASS as expected negative; Main-Agent actual-gate copy
  /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t075-formal-negative-f09cnb1b/negative;
  only the frozen `assign data_o = ~` mutation; strict compile 0/0 + 0/0; exit 1;
  eight unproven cells remain and output contains `unproven` plus `equiv_status -assert`
forbidden_runs: blanket discovery, historical acceptance drivers and RISC-V-Vector Formal were not run
decision: ACCEPTED; T075 establishes the owner-occurrence safety firewall without expanding syntax support
delivery_commit: current acceptance commit; exact hash is reported after commit and frozen into the successor contract
push: pending current acceptance commit
successor: Main Agent will create the next task only after this acceptance commit is pushed
```
