# T082：function closing label 的语义 occurrence 闭合

- 状态：`ACCEPTED`
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
formal_verification: PASS
gold: tests/fixtures/t082_function_end_label
gate: /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t082-formal-positive-y5mhvb4h/encrypt/gate（目标 unittest 生成的 actual public gate）
top: t082_top
seq: 5
public_define: T082_LABEL_CLOSURE
positive_yosys_define: none（对称选择 Yosys-supported branch）
positive_command: `/Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python /Users/lufengchi/Desktop/workspace/rtl_obfuscation/scripts/formal_equivalence.py --gold-filelist /Users/lufengchi/Desktop/workspace/rtl_obfuscation/tests/fixtures/t082_function_end_label/design.f --gold-root /Users/lufengchi/Desktop/workspace/rtl_obfuscation/tests/fixtures/t082_function_end_label --gate-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t082-formal-positive-y5mhvb4h/encrypt/gate/design.f --gate-root /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t082-formal-positive-y5mhvb4h/encrypt/gate --top t082_top --seq 5`
positive_exit_code: 0
positive_result: `{"formal_equivalence":"pass","gate":"/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t082-formal-positive-y5mhvb4h/encrypt/gate","gold":"/Users/lufengchi/Desktop/workspace/rtl_obfuscation/tests/fixtures/t082_function_end_label","seq":5,"top":"t082_top"}`
actual_gate_non_identity: PASS；宏外 `passthrough` declaration/return reference/call 三处实际改为同一非原名，Yosys读取的是该 actual public gate
negative_gate: /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t082-formal-negative-2beeu998/negative；从 actual gate copy，仅把宏外 `assign base = <renamed_passthrough>(data_i);` 固定改为 `assign base = ~<renamed_passthrough>(data_i);`
negative_compile_with_public_define: catalog 0/0；top overlay 0/0
negative_command: `/Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python /Users/lufengchi/Desktop/workspace/rtl_obfuscation/scripts/formal_equivalence.py --gold-filelist /Users/lufengchi/Desktop/workspace/rtl_obfuscation/tests/fixtures/t082_function_end_label/design.f --gold-root /Users/lufengchi/Desktop/workspace/rtl_obfuscation/tests/fixtures/t082_function_end_label --gate-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t082-formal-negative-2beeu998/negative/design.f --gate-root /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t082-formal-negative-2beeu998/negative --top t082_top --seq 5`
negative_exit_code: 1
negative_result: PASS；`Found 1 unproven $equiv cells`，`ERROR: Found 1 unproven $equiv cells in 'equiv_status -assert'.`
closing_label_boundary: Yosys cannot parse `endfunction : name`；actual public gate 保留并实际改名该 label，其 exact identity 由 PySlang strict、同 symbol edits 与 source-free restore 验证
external_formal: N/A; pinned Ibex uses formal-policy none
```

## 14. 子 Agent 执行记录

```text
status: READY_FOR_REVIEW
actual_model: gpt-5.6-sol / xhigh；当前调度器未提供 Luna 模型或 standard speed 参数，未声称使用 Luna
starting_head: 4338687a2c7edfd208947314947a3ae3eb699367；parent=1576936624faa518203c778b3c814ac56d7f8cce；origin/main=d3072b56f86969936441927efdb5dffedcef67ee；branch main ahead 5；start_time=2026-08-10T12:29:01+0800
allowed_files_check: PASS；启动 worktree clean；唯一活动任务 T082 READY；允许路径精确为本任务单、`rtl_obfuscator/symbol_graph.py`、`tests/test_t082_function_end_label.py`、两个 T082 fixture、`docs/systemverilog_renaming_table.md` 与 `docs/development/future_work.md`
baseline: PASS；`conda run -n rtl_obfuscation python -m unittest tests.test_t076_module_end_label tests.test_vnext_category_closure tests.test_t079_parameter_default_occurrence tests.test_t080_expression_sized_cast_parameter tests.test_t081_enum_lexical_completeness_firewall -v`；exit 0；Ran 40 tests；OK；T076/T079/T080/T081 actual-gate Formal 正例 exit 0、固定功能负例 exit 1
pre_fix_characterization: PASS；fixture `design.f`=10 bytes/SHA-256 `2bd824b8fab1c3ebc159191ce9f58bbaadd30a5ddbea38fa8a4fcfc4b94d1aea`，`design.sv`=421 bytes/SHA-256 `decd2aaf72d4a15abf49b677aee82b26c016b4d8a4001505714ee53a98537eaf`；PySlang `passthrough.syntax`/`invert.syntax` 均为 exact `FunctionDeclarationSyntax`，前者 `endBlockName is None`，后者 direct `endBlockName.name` rawText=`invert`/offset=334；current graph=8/8/10/18，mapping=8/2/6/0、planned edits=6，`invert` declaration=270..276、return reference=301..307、call=359..365，closing label 334..340 缺失；public encrypt exit 1=`CLI_VNEXT_ORCHESTRATION_INVALID` 且 gate absent；修复前目标测试 exit 1，Ran 8，7 个预期缺口失败、task 非 function 边界通过
changed_files: PASS；仅修改合同第 10 节七个允许路径：本任务单、`rtl_obfuscator/symbol_graph.py`、`tests/test_t082_function_end_label.py`、两个冻结 fixture、renaming table、future work；无允许列表外改动
commands: PASS；执行 baseline；修复前 `conda run -n rtl_obfuscation python -m unittest tests.test_t082_function_end_label -v`；第 12 节实现后五条命令均逐条执行，其中 external block 使用 fresh `/private/tmp/t082-ibex-replay.JZA3vL`；未运行 blanket discovery、历史 driver 或 RISC-V-Vector Formal
results: PASS；最终 target+regression exit 0，Ran 49 tests，OK；`py_compile` exit 0；external 两条 `jq -e` 均输出 true；`git diff --check HEAD` exit 0；精确 READY_FOR_REVIEW guard exit 0 并输出唯一匹配状态行
typed_identity_contract: PASS；只在现有 `SubroutineSymbol` collector、已有 function record 建立后处理 exact `isinstance(node.syntax, pyslang.syntax.FunctionDeclarationSyntax)` 的 direct `endBlockName.name`；non-missing physical token 经 `_token_source_range(..., function_record["name"])` 精确校验并以 `semantic_function_end_label` 进入同一 record；无 label 不新增 range，task 不进入该路径，macro token 不变成物理 edit；重复 exact range 由现有去重，mismatch/exact occupied/partial overlap 继续稳定 fail-closed
compact_oracle: PASS；catalog/top=0/0+0/0；graph=8 symbols/8 declarations/11 occurrences/19 total ranges；mapping=8 total/2 rename/6 preserve/0 unsupported；7 actual edits；`invert` declaration 270..276、return 301..307、label 334..340、call 359..365 四个 edits 同 symbol_id/renamed_name；public summary files=1/mapping=8/modified_tokens=7/strict=true/restore=true；source-free restore 仅输出 `design.sv` 且逐字节一致
ibex_replay: PASS；证据根 `/private/tmp/t082-ibex-replay.JZA3vL`；stability=`b99f5e43128964cc78a5c123a31f84e46df76934`、Ibex=`3250d99482f1963891ef1cf19356eeaeeaa71d30`，前后均 clean；`non_abi__functions`=`PASS_EFFECTIVE`，45 files/3129 records/161 rename/2459 preserve/509 unsupported/326 modified tokens，strict=true、gate published、decrypt exit 0、45-file restore byte-identical；Formal=`FORMAL_NOT_RUN`；目标 record declaration=1169..1187、唯一 label occurrence=1268..1286；`mapping_execution` 对该 record 精确只有 declaration 与 `semantic_function_end_label` 两个 ranges，均使用 renamed_name=`nrTDQ7a3OTXak7eO4yLs`
formal_verification: PASS；完整 gold/gate/top/seq/命令/exit/JSON 与固定负例见第 13 节；正例 actual renamed gate exit 0/`formal_equivalence=pass`；固定 `~` 负例带 public define strict 0/0+0/0 后 Formal exit 1，1 个 unproven，`equiv_status -assert` 生效
documentation: PASS；`functions` 行说明 ordinary direct function closing-label 同名改写、无 label 不制造 occurrence、宏 label 不支持；future work 记录 T082 闭包及 task/macro/method/class/interface/package/program/checker/generate 与 Yosys syntax 边界；README 未修改
boundaries: task closing label、method/class/interface/package/program/checker/generate label、宏生成 label、extern/DPI/prototype、name-only/source-text recovery 均未扩展；Yosys 不解析 function closing label，故其 label 一致性只由 actual-gate PySlang strict、exact edit identity 和 byte-identical restore证明；pinned Ibex formal-policy none，未声称 external Formal 等价
review_request: READY_FOR_REVIEW；等待主 Agent 独立复验，不得由子 Agent 设置 ACCEPTED
```

## 15. 主 Agent 验收

```text
review_date: 2026-08-10
reviewer: 主 Agent
allowed_files: PASS；最终 worktree 精确为第 10 节七个路径；两个 fixture 仅含 design.f/design.sv，
  10/421 bytes 与冻结 SHA-256 完全匹配；允许列表外零修改
implementation_review: PASS；只在现有 SubroutineSymbol collector 已建立 function record 后读取 exact
  `FunctionDeclarationSyntax.endBlockName.name`；仅 category=functions，non-missing token 复用
  `_token_source_range()` 和 `add_occurrence()`，provenance=`semantic_function_end_label`；无 label、task 和
  macro 均不制造物理 edit；重复 range、名称不一致、跨 record 占用和 partial overlap 继续由既有防火墙
  fail-closed；无 policy/mapping/rewrite/restore/orchestration/CLI/Formal 特例或 source-text recovery
target_and_regression: PASS；合同第 12 节第 1 条 exit 0；Ran 49 tests；OK
compact_oracle: PASS；graph 8/8/11/19；mapping 8 total、2 rename、6 preserve、0 unsupported；7 edits；
  invert declaration 270..276、return 301..307、label 334..340、call 359..365 同 symbol_id/renamed name；
  public strict 0/0+0/0，source-free restore 仅输出 design.sv 且逐字一致
ibex_replay: PASS；Main-Agent fresh root=/private/tmp/t082-main-ibex.YmhUEY；stability
  b99f5e43128964cc78a5c123a31f84e46df76934、Ibex
  3250d99482f1963891ef1cf19356eeaeeaa71d30 前后 clean；non_abi__functions=PASS_EFFECTIVE，45 files、
  3129 records、161 rename/2459 preserve/509 unsupported、326 modified tokens；strict/gate/decrypt/
  45-file byte restore 全通过；mubi4_test_invalid declaration 1169..1187 的唯一
  semantic_function_end_label occurrence 为 1268..1286
formal_positive: PASS；Main-Agent compact actual public renamed gate
  /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t082-formal-positive-y0uzofko/encrypt/gate；
  top=t082_top；seq=5；Yosys 不传 label define，对称读取宏外 actual renamed passthrough；exit 0；
  complete JSON formal_equivalence=pass
formal_negative: PASS as expected negative；Main-Agent actual-gate copy
  /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t082-formal-negative-xzzsvqwu/negative；只在宏外
  `assign base =` 数据通路增加冻结 `~`；带 public define 的 strict compile 0/0+0/0；Formal exit 1；
  1 unproven 且命中 `equiv_status -assert`
external_formal: N/A; formal-policy none
closing_label_formal_boundary: Yosys 不解析合法 `endfunction : name`；actual public gate 中 label 确实改名，
  其一致性由 PySlang strict、同 symbol exact edit identity 和 byte-identical restore 验收；未将 external
  FORMAL_NOT_RUN 或 Yosys未解析分支描述为 label 等价证明
py_compile: PASS；合同第 12 节命令 exit 0
diff_check: PASS；`git diff --check HEAD` exit 0
ready_for_review_guard: PASS；精确 guard 在本次 ACCEPTED 状态变更前 exit 0
documentation: PASS；renaming table 与 future work 明确 ordinary direct function closing label、无 label、
  macro/task/其他 owner 与 Yosys边界；README 未改
forbidden_runs: 未运行 blanket discovery、历史 acceptance driver 或 RISC-V-Vector Formal
decision: ACCEPTED；仅改写由 semantic declaration identity 和 exact typed closing-label token 共同证明的
  range，其他语法与宏边界继续 fail-closed，符合“宁可少加密、不能加密错误”
delivery_commit: current acceptance commit；exact hash 在提交后报告并冻结进后继合同
push: forbidden without a new explicit user authorization beyond d3072b5
successor: Main Agent 仅在本地交付提交完成后决定下一任务
```
