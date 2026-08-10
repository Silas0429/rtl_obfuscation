# T082：function closing label 的语义 occurrence 闭合

- 状态：`READY`
- 合同版本：1.0（2026-08-10）
- 设计日期：2026-08-10
- 设计负责人：主 Agent
- 实现负责人：代码子 Agent（请求模型：Luna extra high / standard speed；当前执行器无 Luna，实际配置必须如实记录）
- 前置任务：T081 `ACCEPTED`，本地交付提交 `1576936624faa518203c778b3c814ac56d7f8cce`
- 设计基线 HEAD：`1576936624faa518203c778b3c814ac56d7f8cce`
- 设计基线 origin/main：`d3072b56f86969936441927efdb5dffedcef67ee`
- 任务类型：SymbolGraph `functions` closing-label occurrence；产生 rewritten RTL
- 执行规范：[`refactor_subagent_protocol.md`](../development/process/refactor_subagent_protocol.md)
- Formal 依据：[`formal_verification.md`](../formal_verification.md)

## 1. 单一目标

对普通物理 function declaration 的直接 closing label：

```systemverilog
function automatic logic invert(input logic value);
  invert = ~value;
endfunction : invert
```

只有当现有 semantic `SubroutineSymbol`、其 function declaration、现有 `functions` SourceSymbol record
以及 `FunctionDeclarationSyntax.endBlockName.name` 能以同一 declaration identity 和名称完全相互证明时，
才把 label name 加入该 function record，provenance 固定为：

```text
semantic_function_end_label
```

被选择加密的 function 必须对 declaration、return-name references、calls 和 direct closing label 使用同一
renamed name。没有 closing label 的 function 不新增 occurrence。证据不足时继续 fail-closed，绝不搜索
`endfunction` 后的文本。

这是把已经确定的 strict failure 在 SymbolGraph 阶段闭合，不是通用 subroutine label resolver，也不授权
task/interface/class/package/generate closing label。

## 2. 起始状态与冻结 baseline

```text
branch: main
HEAD: 1576936624faa518203c778b3c814ac56d7f8cce
origin/main: d3072b56f86969936441927efdb5dffedcef67ee
worktree: clean
active implementation tasks: none
related baseline: 40/40 PASS
```

主 Agent 已运行：

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_t076_module_end_label \
  tests.test_vnext_category_closure \
  tests.test_t079_parameter_default_occurrence \
  tests.test_t080_expression_sized_cast_parameter \
  tests.test_t081_enum_lexical_completeness_firewall -v
```

结果：exit 0，Ran 40 tests，OK。T076/T079/T080/T081 actual renamed-gate Formal 正例 exit 0，
各冻结功能负例 exit 1。

## 3. 冻结 compact fixture

子 Agent 必须逐字创建：

```text
tests/fixtures/t082_function_end_label/design.f
tests/fixtures/t082_function_end_label/design.sv
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
module t082_top (
  input  logic data_i,
  output logic data_o
);
  function automatic logic passthrough(input logic value);
    passthrough = value;
  endfunction

  logic base;
  assign base = passthrough(data_i);

`ifdef T082_LABEL_CLOSURE
  function automatic logic invert(input logic value);
    invert = ~value;
  endfunction : invert
  assign data_o = invert(base);
`else
  assign data_o = ~base;
`endif
endmodule
```

421 bytes，SHA-256：

```text
decd2aaf72d4a15abf49b677aee82b26c016b4d8a4001505714ee53a98537eaf
```

固定 public profile：filelist、top=`t082_top`、define=`T082_LABEL_CLOSURE`、category=`functions`、
无 ABI opt-in、include-dir/rate。

## 4. 主 Agent compact preflight

证据根：`/private/tmp/t082-compact`，simulation gate：
`/private/tmp/t082-compact-v2-sim-gate`。

当前产品：

```text
catalog/top overlay: 0/0 + 0/0
graph symbols/declarations/occurrences/total_ranges: 8/8/10/18
mapping total/rename/preserve/unsupported: 8/2/6/0
planned edits: 6
invert declaration: design.sv:270..276
invert return reference: design.sv:301..307 semantic_reference
invert closing label: design.sv:334..340 missing from graph/edit
invert call: design.sv:359..365 semantic_call
public encrypt: exit 1 / CLI_VNEXT_ORCHESTRATION_INVALID
internal write_gate: REWRITE_GATE_COMPILE_FAILED / CATALOG_PARSE_FAILED
gate output: absent
```

只读 exact semantic simulation 应用第 6 节 occurrence 后：

```text
graph: 8/8/11/19
mapping: unchanged 8 total / 2 rename / 6 preserve / 0 unsupported
modified tokens: 7
invert: declaration + return reference + call + semantic_function_end_label，四个 edits 同 symbol_id/new name
strict: 0/0 + 0/0
restore: one .sv file byte-identical
```

simulation 只冻结 oracle，不是产品交付证据。子 Agent必须从 actual public gate 重做。

## 5. Ibex 当前缺陷与最小闭包

固定输入：stability `b99f5e43128964cc78a5c123a31f84e46df76934`，Ibex
`3250d99482f1963891ef1cf19356eeaeeaa71d30`，top=`ibex_top`，45 files，define=`SYNTHESIS`，
profile=`non_abi__functions`。

当前 public replay 根：`/private/tmp/t082-preflight-ibex.oOhLUW`：

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
graph: 3129 symbols / 3129 declarations / 11391 occurrences / 14520 ranges
mapping: 3129 total / 161 rename / 2459 preserve / 509 unsupported
planned edits: 219
first strict root: EndNameMismatch
file: vendor/lowrisc_ip/ip/prim/rtl/prim_mubi_pkg.sv
function: mubi4_test_invalid
declaration: 1169..1187
closing label: 1268..1286
current record: declaration edit only; closing label absent
```

PySlang 固定事实：semantic node 是 `SubroutineSymbol`；`node.syntax` 是
`FunctionDeclarationSyntax`；closing label 唯一物理 token 路径为
`node.syntax.endBlockName.name`，rawText=`mubi4_test_invalid`，location 与上述 source range 一致。

只读 exact simulation 对 107 个可证明 direct function labels 加 occurrence 后：

```text
graph: 3129 / 3129 / 11498 / 14627
semantic labels: 107
physical non-macro labels: 107
macro labels: 0
mapping: unchanged 161 rename / 2459 preserve / 509 unsupported
modified tokens: 326
strict: 0/0 + 0/0
restore: 45 files byte-identical
mubi4_test_invalid: declaration + semantic_function_end_label 两个 edits，同 symbol_id/new name
```

因此选择 exact closing-label occurrence，而不是整 function record quarantine：这里有完整 declaration identity
和 typed syntax token，精确修复能闭合全部 strict errors，不需要 name-only 或 raw-text recovery。

## 6. 唯一实现合同

1. 只修改现有 `_collect_extended_symbols()` 的 `SubroutineSymbol` collection；不得在 policy、mapping、
   rewrite、restore、orchestration、CLI 或 Formal 增加 function 特例；
2. 先按现有 `_record_range(source_catalog, node)` 创建 function record，以该 semantic node 的 declaration、
   `node.name`、owner/context 作为身份；不得另建 symbol 或按 name 回查其他 record；
3. 只有 `category == "functions"` 且 `node.syntax` 是
   `pyslang.syntax.FunctionDeclarationSyntax` 时允许检查 closing label；task record 完全不变；
4. closing label 唯一允许来源是 `node.syntax.endBlockName.name`；`endBlockName is None` 表示无 label，
   不增加 occurrence；不得从 syntax span、last token、source bytes、regex、line text 或 `endfunction`
   后字符串推导；
5. label clause 存在时，`.name` 必须是 non-missing physical identifier token，且
   `_token_source_range(source_catalog, token, function_record["name"])` 必须证明 rawText 与 function name
   相等；缺 token、名称不等或非法 range 必须沿现有稳定 SymbolGraphError fail-closed；
6. 非宏 token 通过现有 `add_occurrence()` 加入同一 record，provenance 精确为
   `semantic_function_end_label`；不得新建 category/schema/API/reason；
7. macro-backed label 继续遵守 `_token_source_range()` 的现有 `None` 边界，不把虚拟 location 当物理 edit；
   本任务不补 macro text。若现有 owner quarantine 未使其安全，public gate 必须原子失败而非发布错误 gate；
8. 重复 elaboration 看见同一 function definition 时，由现有 exact-range 去重只保留一个 closing-label
   occurrence；不同范围、跨 record、部分重叠仍由现有 range firewall fail-closed；
9. 现有 return-name reference、call、argument、owner quarantine、enum lexical firewall、module end label
   和 selected-top 行为不得改变；
10. 不增加 dependency、兼容层、fallback、缓存、second parser 或 real-project 硬编码。

## 7. NO-GO 与测试边界

T082 不支持：

- `endtask : name`、method/class/interface/package/program/checker/generate closing label；
- macro-generated function declaration、macro argument label 或虚拟 source location；
- function prototype、extern/DPI/import/export、forward declaration 的人工 closing label；
- name-only 匹配、跨 owner 猜测、source regex、substring 或 token spelling 归一化；
- 为通过 strict compile 而 preserve 整个 `functions` 类别；
- 修改 function body、argument、return type 或调用绑定逻辑。

目标 unittest 至少必须证明：

1. 冻结 fixture bytes/hash、修复前 graph/mapping/atomic failure characterization；
2. `invert` declaration、return reference、call、closing label 是同一 function record，label provenance/range
   精确，四个实际 edits 使用同一 renamed name；
3. 无 closing label 的 `passthrough` 不制造 label occurrence，但 declaration/reference/call 继续实际改名；
4. task closing label 不进入 function record，且 task 行为不因本任务改变；
5. repeated elaboration 不重复 range；macro-backed label 不产生物理 occurrence/edit；
6. mismatch/missing token、另一 record 占用同 range和 partial overlap 继续 fail-closed；
7. actual public gate strict 0/0+0/0、source-free restore byte-identical；
8. 第 9 节实际 renamed-gate Formal 正例与固定功能负例。

## 8. pinned Ibex delta oracle

修复后 fresh public runner 必须满足：

```text
classification: PASS_EFFECTIVE
files: 45
mapping_records: 3129
effective_renamed_records: 161
modified_tokens: 326
mapping actions: 161 rename / 2459 preserve / 509 unsupported
strict_compile_passed: true
gate_published: true
decrypt_exit_code: 0
restore.files: 45
restore_byte_identical: true
formal.status: FORMAL_NOT_RUN
```

`symbol:functions:vendor/lowrisc_ip/ip/prim/rtl/prim_mubi_pkg.sv:1169:1187` 必须 action=rename，
declaration 保持 `1169..1187`，新增且只新增一个 `semantic_function_end_label` occurrence
`1268..1286`；execution 中该 record 必须有 declaration/closing-label 两个 edits且同 renamed name。

external Ibex 只验证 strict/restore。不得把 `FORMAL_NOT_RUN` 描述为等价证明。

## 9. compact Formal 特殊边界

Yosys 当前前端不接受合法 SystemVerilog `endfunction : name`，直接读取冻结 fixture 在该行报 syntax
error。不得删除 actual gate label、不得用 gold/gate 同一文件、不得声称 Yosys证明了它不解析的 syntax。

冻结 fixture 用 `T082_LABEL_CLOSURE` 明确分隔这个工具边界：

- public encryption/strict/restore 必须带该 define，实际解析、改名并编译 `invert` declaration、body、call
  和 closing label；
- Formal gold/gate 均不传该 define，因此 Yosys对称选择 `else` 数据通路，避开它不支持的 label syntax；
- 无 label 的 `passthrough` 位于宏外，actual gate 必须把它的 declaration、return reference 和 call 实际改名，
  Yosys正例读取的仍是 actual renamed gate，不是 identity/copy-gold；
- 固定负例从 actual gate copy，只把宏外
  `assign base = <renamed_passthrough>(data_i);` 改为
  `assign base = ~<renamed_passthrough>(data_i);`；带 define 的 strict compile 仍必须 0/0+0/0，Formal
  必须 exit 1 且包含 `unproven` 和 `equiv_status -assert`。

Formal 只证明 Yosys可解析数据通路中 actual function rename 没有改变功能；closing-label 语法一致性由
PySlang strict compile、exact edit identity 和 byte-identical restore 验收。不得扩大 T082 去修改 Formal 工具。

## 10. 允许修改

只允许：

```text
docs/tasks/T082_function_end_label_occurrence.md
rtl_obfuscator/symbol_graph.py
tests/test_t082_function_end_label.py
tests/fixtures/t082_function_end_label/design.f
tests/fixtures/t082_function_end_label/design.sv
docs/systemverilog_renaming_table.md
docs/development/future_work.md
```

禁止修改任何其他文件，禁止 stage/commit/push，禁止设置 `ACCEPTED`，禁止创建 T083。

## 11. 文档交付

- `docs/systemverilog_renaming_table.md` 的 `functions` 行只补充：普通物理 function 的 declaration、
  references/calls 和 direct closing label 使用同一改名；无 label 不制造 occurrence；宏 label 不支持；
- `docs/development/future_work.md` 记录 T082 已闭合 ordinary direct function closing label，并保留 task、
  macro、method/class/interface/package/program/checker/generate label 以及 Yosys syntax boundary；
- 不修改 README：用户命令和公开类别没有变化。

## 12. 验收命令（固定五条）

开始前 baseline：

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_t076_module_end_label \
  tests.test_vnext_category_closure \
  tests.test_t079_parameter_default_occurrence \
  tests.test_t080_expression_sized_cast_parameter \
  tests.test_t081_enum_lexical_completeness_firewall -v
```

实现后五条：

```sh
conda run -n rtl_obfuscation python -m unittest \
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
replay_root=$(mktemp -d /private/tmp/t082-ibex-replay.XXXXXX)
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
  --profiles non_abi__functions --formal-policy none
jq -e '
  (.results | length) == 1 and
  .results[0].profile == "non_abi__functions" and
  .results[0].classification == "PASS_EFFECTIVE" and
  .results[0].effective_renamed_records == 161 and
  .results[0].cli_summary.summary.files == 45 and
  .results[0].cli_summary.summary.mapping_records == 3129 and
  .results[0].cli_summary.summary.modified_tokens == 326 and
  ([.results[0].mapping_counts[] | .rename // 0] | add) == 161 and
  ([.results[0].mapping_counts[] | .preserve // 0] | add) == 2459 and
  ([.results[0].mapping_counts[] | .unsupported // 0] | add) == 509 and
  .results[0].strict_compile_passed == true and
  .results[0].gate_published == true and
  .results[0].decrypt_exit_code == 0 and
  .results[0].restore_byte_identical == true and
  .results[0].restore.files == 45 and
  .results[0].formal.status == "FORMAL_NOT_RUN"
' "$replay_root/matrix/matrix.json"
jq -e '
  ([.mapping.records[]
    | select(.symbol_id == "symbol:functions:vendor/lowrisc_ip/ip/prim/rtl/prim_mubi_pkg.sv:1169:1187")
    | select(
        .action == "rename" and
        .declaration == {"file":"vendor/lowrisc_ip/ip/prim/rtl/prim_mubi_pkg.sv","start":1169,"end":1187} and
        ([.occurrences[] | select(
          .provenance == "semantic_function_end_label" and
          .source_range == {"file":"vendor/lowrisc_ip/ip/prim/rtl/prim_mubi_pkg.sv","start":1268,"end":1286})]
         | length) == 1)] | length) == 1
' "$replay_root/matrix/non_abi__functions/gate/mapping.json"
test -z "$(git -C "$external_root" status --short)"
test -z "$(git -C "$external_root/repos/ibex" status --short)"

conda run -n rtl_obfuscation python -m py_compile \
  rtl_obfuscator/symbol_graph.py tests/test_t082_function_end_label.py

git diff --check HEAD

rg -x -- '- 状态：`READY_FOR_REVIEW`' \
  docs/tasks/T082_function_end_label_occurrence.md
```

目标 unittest 必须执行 actual public gate strict compile、source-free restore、第 9 节 Formal 正例和固定
功能负例；不得 identity/copy-gold，不得弱化 `equiv_status -assert`。external runner 限时 300 秒，
formal-policy none，不运行 RISC-V-Vector Formal或 blanket discovery。

## 13. Formal verification 记录

```text
formal_verification: PASS | FAIL | BLOCKED
gold: tests/fixtures/t082_function_end_label
gate: <actual public rtl_encrypt output>
top: t082_top
seq: 5
public_define: T082_LABEL_CLOSURE
positive_yosys_define: none（对称选择 Yosys-supported branch）
positive_command: <exact command>
positive_exit_code: <integer>
positive_result: <complete stdout JSON>
actual_gate_non_identity: passthrough declaration/return reference/call are renamed and are parsed by Yosys
negative_gate: <actual gate copy with only frozen macro-outside `assign base = ~` mutation>
negative_compile_with_public_define: <catalog/top overlay counts>
negative_command: <exact command>
negative_exit_code: <nonzero integer>
negative_result: <unproven / equiv_status -assert summary>
closing_label_boundary: Yosys cannot parse endfunction label; exact identity is checked by PySlang strict/edit/restore
external_formal: N/A; pinned Ibex uses formal-policy none
```

## 14. 子 Agent 执行记录

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

## 15. 主 Agent 验收

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
