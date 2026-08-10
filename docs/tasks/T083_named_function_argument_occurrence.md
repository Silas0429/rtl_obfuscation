# T083：named function argument label 的语义 occurrence 闭合

- 状态：`READY`
- 合同版本：1.0（2026-08-10）
- 设计日期：2026-08-10
- 设计负责人：主 Agent
- 实现负责人：代码子 Agent（请求模型：Luna extra high / standard speed；当前执行器无 Luna，实际配置必须如实记录）
- 前置任务：T082 `ACCEPTED`，本地交付提交 `e6db7d7386bc46e69c4fc0220588cf09d784293c`
- 设计基线 HEAD：`e6db7d7386bc46e69c4fc0220588cf09d784293c`
- 设计基线 origin/main：`d3072b56f86969936441927efdb5dffedcef67ee`
- 任务类型：SymbolGraph `arguments` named-function-call occurrence；产生 rewritten RTL
- 执行规范：[`refactor_subagent_protocol.md`](../development/process/refactor_subagent_protocol.md)
- Formal 依据：[`formal_verification.md`](../formal_verification.md)

## 1. 单一目标

对普通物理 function 的 named argument call：

```systemverilog
function automatic logic choose(input logic lhs, input logic rhs);
  choose = lhs ^ rhs;
endfunction

assign data_o = choose(.rhs(data_i), .lhs(1'b0));
```

只有当同一个 semantic `CallExpression` 能同时证明：

1. exact `subroutine` 是已有普通物理 `functions` record；
2. exact callee `SubroutineSymbol.arguments` 中存在唯一同名 `FormalArgumentSymbol`；
3. 该 formal declaration identity 命中已有 `arguments` record；
4. call syntax 是 `InvocationExpressionSyntax.arguments` 下的 direct
   `NamedArgumentSyntax.name` 物理 identifier token；

才把 `.rhs` / `.lhs` 的 name token 加入相应 argument record，provenance 固定为：

```text
semantic_named_argument
```

被选择加密的 function argument 必须对 declaration、function-body references 和全部已证明 named-call
labels 使用同一个 renamed name。ordered call 不新增 label occurrence。证据不足时继续 fail-closed，绝不
按全局名字、参数位置或 source text 猜测。

本任务只闭合普通物理 function calls；task/method/class/DPI/system/randomize named arguments 不在范围内。

## 2. 起始状态与冻结 baseline

```text
branch: main
HEAD: e6db7d7386bc46e69c4fc0220588cf09d784293c
origin/main: d3072b56f86969936441927efdb5dffedcef67ee
worktree: clean
active implementation tasks: none
related baseline: 49/49 PASS
```

主 Agent 已运行：

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_t082_function_end_label \
  tests.test_t076_module_end_label \
  tests.test_vnext_category_closure \
  tests.test_t079_parameter_default_occurrence \
  tests.test_t080_expression_sized_cast_parameter \
  tests.test_t081_enum_lexical_completeness_firewall -v
```

结果：exit 0，Ran 49 tests，OK。T076/T079/T080/T081/T082 actual renamed-gate Formal 正例
exit 0，各冻结功能负例 exit 1。

## 3. 冻结 compact fixture

子 Agent 必须逐字创建：

```text
tests/fixtures/t083_named_function_argument/design.f
tests/fixtures/t083_named_function_argument/design.sv
```

`design.f`：

```text
design.sv
```

10 bytes，SHA-256：

```text
2bd824b8fab1c3ebc159191ce9f58bbaadd30a5ddbea38fa8a4fcfc4b94d1aea
```

`design.sv`：

```systemverilog
module t083_top (
  input  logic data_i,
  output logic data_o
);
  function automatic logic choose(input logic lhs, input logic rhs);
    choose = lhs ^ rhs;
  endfunction

  logic base;
  assign base = data_i;

`ifdef T083_NAMED_ARGUMENT
  assign data_o = choose(.rhs(base), .lhs(1'b0));
`else
  assign data_o = choose(1'b0, base);
`endif
endmodule
```

351 bytes，SHA-256：

```text
64a6a7fa56e53a0e65da21530b0a367cd5929051b8de4198acd4f998d5063db0
```

固定 public profile：filelist、top=`t083_top`、define=`T083_NAMED_ARGUMENT`、
category=`arguments`、无 ABI opt-in/include-dir/rate。

## 4. 主 Agent compact preflight

证据根：`/private/tmp/t083-compact`；simulation gate：
`/private/tmp/t083-compact-sim-gate`。

当前产品：

```text
catalog/top overlay: 0/0 + 0/0
graph symbols/declarations/occurrences/total_ranges: 7/7/8/15
mapping total/rename/preserve/unsupported: 7/2/5/0
planned edits: 4
lhs declaration/body reference: 112..115 / 148..151
rhs declaration/body reference: 129..132 / 154..157
rhs named label 266..269: missing from graph/edit
lhs named label 278..281: missing from graph/edit
public encrypt: exit 1 / CLI_VNEXT_ORCHESTRATION_INVALID
internal write_gate: REWRITE_GATE_COMPILE_FAILED / CATALOG_SEMANTIC_FAILED
gate output: absent
```

只读 exact semantic simulation 应用第 8 节 occurrence 后：

```text
graph: 7/7/10/17
mapping: unchanged 7 total / 2 rename / 5 preserve / 0 unsupported
modified tokens: 6
lhs: declaration 112..115 + body 148..151 + label 278..281，同 symbol_id/new name
rhs: declaration 129..132 + body 154..157 + label 266..269，同 symbol_id/new name
strict: 0/0 + 0/0
restore: one .sv file byte-identical
```

named labels 的 source order 固定为 `.rhs` 后 `.lhs`，而 formal declaration order 是 `lhs` 后 `rhs`；
本 fixture 用于证明实现按 exact formal name/identity 绑定，而不是把 syntax position zip 到 formal position。

simulation 只冻结 oracle，不是产品交付证据。子 Agent必须从 actual public gate 重做。

## 5. PySlang typed identity 冻结

对 Ibex `cm_stack_adj(.rlist(rlist), .spimm(spimm))`，PySlang 11.0.0 的实际对象为：

```text
CallExpression
├─ subroutine: SubroutineSymbol cm_stack_adj
│  ├─ syntax: FunctionDeclarationSyntax
│  └─ arguments:
│     ├─ FormalArgumentSymbol rlist declaration 2096..2101
│     └─ FormalArgumentSymbol spimm declaration 2121..2126
└─ syntax: InvocationExpressionSyntax
   ├─ left: IdentifierNameSyntax cm_stack_adj
   └─ arguments: ArgumentListSyntax
      └─ parameters:
         ├─ NamedArgumentSyntax.name Token rlist @2420
         ├─ Token comma
         └─ NamedArgumentSyntax.name Token spimm @2435
```

重要边界：

- `CallExpression.arguments` 是 actual value expressions，不是 named-label 到 formal 的 identity map；
- `ArgumentListSyntax.parameters` 包含 comma `Token`，不得与 semantic formal list 做 positional zip；
- 唯一允许的绑定是 exact `CallExpression.subroutine` 内的 formal list，以 label rawText 找到唯一 formal，
  再以 formal declaration range 命中已有 argument record；
- label source range 只能来自该 `NamedArgumentSyntax.name` token。

若 callee record、function syntax、formal uniqueness、formal record category/owner、token spelling 或 physical
range 任一不一致，必须稳定 fail-closed，不得 fallback 到 scope lookup 或全局 name map。

## 6. Ibex 当前缺陷

fresh public 根：`/private/tmp/t083-preflight-ibex.CowQTM`。

固定输入：stability `b99f5e43128964cc78a5c123a31f84e46df76934`，Ibex
`3250d99482f1963891ef1cf19356eeaeeaa71d30`，top=`ibex_top`，45 files，define=`SYNTHESIS`，
profile=`non_abi__arguments`。

当前 public replay：

```text
classification: FAIL_STRICT
encrypt exit: 1
gate: absent
public stable error: CLI_VNEXT_ORCHESTRATION_INVALID
Formal: FORMAL_NOT_RUN
```

当前内部 oracle：

```text
compile: 0/0 + 0/0
graph: 3129 symbols / 3129 declarations / 11498 occurrences / 14627 ranges
mapping: 3129 total / 236 rename / 2384 preserve / 509 unsupported
planned edits: 1344
write_gate: REWRITE_GATE_COMPILE_FAILED / CATALOG_SEMANTIC_FAILED
first gate diagnostic: UnconnectedArg
first file: rtl/ibex_compressed_decoder.sv
```

手工只发布到 `/private/tmp/t083-broken-gate` 的诊断 view 确认：第一组 gate diagnostics 是
`UnconnectedArg`，随后两个 `ArgDoesNotExist`；这是 formal declarations/body 已改名，但 `.rlist` / `.spimm`
labels 保持旧名导致，不是 discovery、category policy、owner quarantine 或 Formal 错误。

## 7. 两个安全方案比较与决策

主 Agent在同一 fresh source 上验证：

| 方案 | rename/preserve/unsupported | edits | strict/restore | 决策 |
| --- | --- | --- | --- | --- |
| exact named-label occurrence | 236/2384/509 | 1378 | 0/0+0/0；45 files byte-identical | GO |
| 将 17 个受影响 argument records 整条 unsupported | 219/2384/526 | 1306 | 0/0+0/0；45 files byte-identical | 安全后备，不采用 |

exact simulation 共发现：

```text
16 calls with named arguments
34 NamedArgumentSyntax labels
17 affected argument records
34 physical bound ranges
0 macro ranges
0 labels without an argument record
```

这 34 个 ranges 都由 exact semantic callee、唯一 formal declaration identity 和 direct physical token 共同
证明；不存在 name-only 或 positional ambiguity。因此采用精确 occurrence，避免无依据地少加密 17 个已证明
records。若实现时任一冻结计数或 API 事实不成立，必须停止任务，不能临时扩大成 generic resolver；主 Agent
再决定是否另开 record-quarantine 任务。

## 8. 唯一实现合同

1. 只修改现有 `_collect_extended_symbols()` 的 semantic `CallExpression` pass；不得在 policy、mapping、
   rewrite、restore、orchestration、CLI 或 Formal 增加 argument 特例；
2. 只处理 `type(node).__name__ == "CallExpression"` 且 `node.subroutine` 通过现有
   `record_for_target()` 精确命中 `category == "functions"` 的 record；callee syntax 还必须是
   `pyslang.syntax.FunctionDeclarationSyntax`；否则不进入本任务路径；
3. call syntax 必须是 `pyslang.syntax.InvocationExpressionSyntax`，`.arguments` 必须是
   `pyslang.syntax.ArgumentListSyntax`；只处理其中 direct
   `pyslang.syntax.NamedArgumentSyntax`，comma Token 只作为分隔符跳过；不得递归 syntax subtree；
4. 对每个 named label，从 exact `node.subroutine.arguments` 过滤 `str(formal.name) == token.rawText`；
   候选必须恰好一个。不得把 `CallExpression.arguments` 或 syntax 顺序与 formal 顺序 zip，不得 scope/global
   lookup；
5. 唯一 formal 必须由 `record_for_target(formal)` 命中既有 `category == "arguments"` record；其
   declaration 必须等于 `_record_range(source_catalog, formal)`，其 owner 必须与 callee function record
   的 subroutine owner 相同，record name 必须等于 token rawText；任一不一致稳定 fail-closed；
6. `NamedArgumentSyntax.name` 必须是 non-missing identifier token；用现有
   `_token_source_range(source_catalog, token, argument_record["name"])` 证明 spelling 与物理 range；
7. 非宏 token 通过现有 `add_occurrence()` 加入同一 argument record，provenance 精确为
   `semantic_named_argument`；不得新建 symbol/category/schema/API/reason；
8. named-label collection 必须独立于现有 function call-name occurrence 是否为 macro/None；不得因原
   call-name 分支的 `continue` 意外跳过后续审计。macro-backed label 继续遵守 `_token_source_range()` 的
   `None` 边界，不把虚拟 location 当物理 edit；本任务不修改 macro text；
9. 多次 elaboration 看见同一 call range 时由现有 exact-range 去重；不同 record、部分重叠或名称不一致
   继续由现有 range/source firewall fail-closed；
10. ordered arguments、actual value expressions、function call name、formal declaration/body reference、
    T082 function end label、owner quarantine 与 enum lexical firewall 行为不变；
11. 不支持 task/method/class/DPI/system/randomize/extern/constructor named arguments；不得顺手将同一 typed
    path 扩展到这些语义 owner；
12. 不增加 dependency、fallback、cache、second parser、raw regex 或 Ibex hard-code。

## 9. NO-GO 与测试边界

T083 不支持：

- task calls、class/interface methods、constructors、DPI/import/export、system calls、randomize `with`；
- macro-generated named label/call、macro argument token或虚拟 source location；
- ordered call 产生 named-label occurrence；
- 把 actual expression symbol 当作 callee formal；
- 用同名 caller variable、scope lookup、全局 argument name 或 syntax position猜 formal；
- mixed/unknown argument syntax 的部分绑定；
- 无 exact callee function record 或无 exact formal argument record 的 recovery；
- 修改 function/task body、argument direction/type/default value或调用参数值。

目标 unittest 至少必须证明：

1. 冻结 fixture bytes/hash、修复前 graph/mapping/atomic failure characterization；
2. source order `.rhs`/`.lhs` 正确绑定 declaration order `lhs`/`rhs`，不是 positional zip；
3. lhs/rhs declaration、body reference、named label各自同 record、同 renamed name和三个实际 edits；
4. ordered `else` call不新增 label occurrence；actual expressions仍绑定原 caller symbols；
5. task named labels、method/system calls不进入 `semantic_named_argument`；
6. repeated elaboration去重；macro label不产生物理 occurrence/edit，相关不安全 record由现有 quarantine或
   atomic strict failure保护；
7. missing/mismatched token、formal duplicate/no match、wrong category/owner、occupied/partial range稳定
   fail-closed；
8. actual public gate strict 0/0+0/0、source-free restore byte-identical；
9. 第 11 节 actual renamed-gate Formal正例和固定功能负例。

## 10. pinned Ibex delta oracle

修复后 fresh public runner 必须满足：

```text
classification: PASS_EFFECTIVE
files: 45
mapping_records: 3129
effective_renamed_records: 236
modified_tokens: 1378
mapping actions: 236 rename / 2384 preserve / 509 unsupported
semantic_named_argument occurrences: 34
strict_compile_passed: true
gate_published: true
decrypt_exit_code: 0
restore.files: 45
restore_byte_identical: true
formal.status: FORMAL_NOT_RUN
```

固定 records：

```text
symbol:arguments:rtl/ibex_compressed_decoder.sv:2096:2101
  name: rlist
  named-label occurrences: 2420..2425, 4809..4814

symbol:arguments:rtl/ibex_compressed_decoder.sv:2121:2126
  name: spimm
  named-label occurrences: 2435..2440, 4824..4829
```

两个 records 均必须 action=rename；declaration、existing semantic_reference 与上述两个 labels 使用同一
renamed name。目标 unittest 必须从内部 RewriteExecution 验证 edit identity；public `mapping.json` 只冻结
records/occurrences 与 summary，不虚构顶层 edits。

external Ibex 只验证 strict/restore。不得把 `FORMAL_NOT_RUN` 描述为等价证明。

## 11. compact Formal 特殊边界

Yosys 0.53 当前前端不接受 named function call；主 Agent直接带
`-D T083_NAMED_ARGUMENT` 读取冻结 fixture，在 `.rhs` 行稳定报：

```text
syntax error, unexpected '.'
```

不得删除 actual gate named labels、不得用 gold/gate同一文件、不得声称 Yosys证明了它不解析的 syntax。

冻结 fixture 用 `T083_NAMED_ARGUMENT` 明确分隔该工具边界：

- public encryption/strict/restore 必须带 define，实际解析、改名并编译 lhs/rhs declaration、body references
  和 named labels；
- Formal gold/gate均不传 define，因此 Yosys对称选择 ordered call branch，避开不支持的 named-call syntax；
- function declaration/body位于宏外，actual gate 中 lhs/rhs formal declarations与body references已实际改名，
  Yosys读取的是 actual renamed gate，不是 identity/copy-gold；
- 固定负例从 actual gate copy，只把宏外 `assign base = data_i;` 改为
  `assign base = ~data_i;`；带 public define 的 strict compile仍须 0/0+0/0，Formal必须 exit 1并包含
  `unproven` 与 `equiv_status -assert`。

Formal只证明 Yosys可解析数据通路中 actual argument rename没有改变功能；named-label语法一致性由 PySlang
strict compile、exact edit identity 和byte-identical restore验收。不得扩大 T083 去修改 Formal工具。

## 12. 允许修改与文档交付

只允许：

```text
docs/tasks/T083_named_function_argument_occurrence.md
rtl_obfuscator/symbol_graph.py
tests/test_t083_named_function_argument.py
tests/fixtures/t083_named_function_argument/design.f
tests/fixtures/t083_named_function_argument/design.sv
docs/systemverilog_renaming_table.md
docs/development/future_work.md
```

文档要求：

- renaming table 的 `arguments` 行只补充 ordinary physical function 的 declaration/body/named-call label
  同名改写，以及 task/method/macro边界；
- future work 记录 T083 exact semantic binding、Yosys边界和仍不支持的 task/method/macro/DPI/system形状；
- README不改：公开命令、category和schema没有变化。

禁止修改任何其他文件，禁止 stage/commit/push，禁止设置 `ACCEPTED`，禁止创建 T084。

## 13. 验收命令（固定五条）

开始前 baseline：

```sh
conda run -n rtl_obfuscation python -m unittest \
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
replay_root=$(mktemp -d /private/tmp/t083-ibex-replay.XXXXXX)
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
  --profiles non_abi__arguments --formal-policy none
jq -e '
  (.results | length) == 1 and
  .results[0].profile == "non_abi__arguments" and
  .results[0].classification == "PASS_EFFECTIVE" and
  .results[0].effective_renamed_records == 236 and
  .results[0].cli_summary.summary.files == 45 and
  .results[0].cli_summary.summary.mapping_records == 3129 and
  .results[0].cli_summary.summary.modified_tokens == 1378 and
  ([.results[0].mapping_counts[] | .rename // 0] | add) == 236 and
  ([.results[0].mapping_counts[] | .preserve // 0] | add) == 2384 and
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
    | select(.provenance == "semantic_named_argument")] | length) == 34 and
  ([.mapping.records[]
    | select(.symbol_id == "symbol:arguments:rtl/ibex_compressed_decoder.sv:2096:2101")
    | select(.action == "rename")
    | [.occurrences[] | select(
        .provenance == "semantic_named_argument" and
        ((.source_range.start == 2420 and .source_range.end == 2425) or
         (.source_range.start == 4809 and .source_range.end == 4814)))]
    | select(length == 2)] | length) == 1 and
  ([.mapping.records[]
    | select(.symbol_id == "symbol:arguments:rtl/ibex_compressed_decoder.sv:2121:2126")
    | select(.action == "rename")
    | [.occurrences[] | select(
        .provenance == "semantic_named_argument" and
        ((.source_range.start == 2435 and .source_range.end == 2440) or
         (.source_range.start == 4824 and .source_range.end == 4829)))]
    | select(length == 2)] | length) == 1
' "$replay_root/matrix/non_abi__arguments/gate/mapping.json"
test -z "$(git -C "$external_root" status --short)"
test -z "$(git -C "$external_root/repos/ibex" status --short)"

conda run -n rtl_obfuscation python -m py_compile \
  rtl_obfuscator/symbol_graph.py tests/test_t083_named_function_argument.py

git diff --check HEAD

rg -x -- '- 状态：`READY_FOR_REVIEW`' \
  docs/tasks/T083_named_function_argument_occurrence.md
```

目标 unittest必须执行 actual public gate strict compile、source-free restore、第 11 节 Formal正例和固定
功能负例；不得 identity/copy-gold，不得弱化 `equiv_status -assert`。external runner限时300秒，
formal-policy none，不运行 RISC-V-Vector Formal或 blanket discovery。

## 14. Formal verification 记录

```text
formal_verification: PASS | FAIL | BLOCKED
gold: tests/fixtures/t083_named_function_argument
gate: <actual public rtl_encrypt output>
top: t083_top
seq: 5
public_define: T083_NAMED_ARGUMENT
positive_yosys_define: none（对称选择 Yosys-supported ordered-call branch）
positive_command: <exact command>
positive_exit_code: <integer>
positive_result: <complete stdout JSON>
actual_gate_non_identity: lhs/rhs declarations and body references are renamed and parsed by Yosys
negative_gate: <actual gate copy with only frozen macro-outside `assign base = ~` mutation>
negative_compile_with_public_define: <catalog/top overlay counts>
negative_command: <exact command>
negative_exit_code: <nonzero integer>
negative_result: <unproven / equiv_status -assert summary>
named_label_boundary: Yosys cannot parse named function calls; exact labels checked by PySlang strict/edit/restore
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
