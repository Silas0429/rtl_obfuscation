# T081：枚举值词法覆盖完整性防火墙

- 状态：`ACCEPTED`
- 合同版本：1.1（2026-08-10 public mapping evidence path correction；行为与范围不变）
- 设计日期：2026-08-10
- 设计负责人：主 Agent
- 实现负责人：代码子 Agent（请求模型：Luna extra high / standard speed；当前执行器无 Luna，实际配置必须如实记录）
- 前置任务：T080 `ACCEPTED`，本地交付提交 `8e01a1ebbcd2ddfa724f6743e15adaac1945e176`
- 设计基线 HEAD：`8e01a1ebbcd2ddfa724f6743e15adaac1945e176`
- 设计基线 origin/main：`d3072b56f86969936441927efdb5dffedcef67ee`
- 任务类型：SymbolGraph `enum_values` 安全防火墙；产生 rewritten RTL
- 执行规范：[`refactor_subagent_protocol.md`](../development/process/refactor_subagent_protocol.md)
- Formal 依据：[`formal_verification.md`](../formal_verification.md)

## 1. 单一目标

为 `enum_values` 增加 record 级词法覆盖完整性防火墙：只有一个枚举 record 在全部物理输入源码中的
同名 plain identifier ranges，和该 record 已有 declaration + occurrences ranges **精确相等** 时，才允许
它保持 `eligible` 并被改名。

若存在任一未被语义图覆盖的同名 token，或语义 ranges 与原始词法 ranges 不相等，必须将整条 enum record
标为：

```text
support = unsupported
reason = enum_lexical_coverage_incomplete
```

该 record 的 declaration、已有 occurrences 和缺口事实仍可审计，但不得为它产生任何 rewrite edit。T081
不猜测未绑定 token 的语义身份、不补 lexical occurrence，也不把缺口转移到 strict gate 才发现。

这是“宁可少加密、不能加密错误”的安全修复，不是 generic enum reference resolver。覆盖完整的其他 enum
record 必须继续实际改名，不能整类 preserve。

## 2. 起始状态与冻结 baseline

```text
branch: main
HEAD: 8e01a1ebbcd2ddfa724f6743e15adaac1945e176
origin/main: d3072b56f86969936441927efdb5dffedcef67ee
worktree: clean
active implementation tasks: none
related baseline: 25/25 PASS
```

主 Agent 已运行：

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_vnext_category_closure \
  tests.test_t079_parameter_default_occurrence \
  tests.test_t080_expression_sized_cast_parameter -v
```

结果：exit 0，Ran 25 tests，OK。T079/T080 actual renamed-gate Formal 正例 exit 0，固定负例 exit 1。

## 3. 冻结 compact fixture

子 Agent 必须逐字创建：

```text
tests/fixtures/t081_enum_lexical_firewall/design.f
tests/fixtures/t081_enum_lexical_firewall/design.sv
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
module t081_child (
  input  logic data_i,
  output logic data_o
);
  typedef enum logic {
    MODE_SAFE,
    MODE_GAP
  } mode_e;
  parameter logic MODE = MODE_GAP;

  if (MODE == MODE_GAP) begin : g_gap
    assign data_o = 1'b0;
  end else begin : g_safe
    assign data_o = (MODE == MODE_SAFE) ? data_i : 1'b0;
  end
endmodule

module t081_top (
  input  logic data_i,
  output logic data_o
);
  t081_child #(.MODE(1'b0)) u_child (
    .data_i(data_i),
    .data_o(data_o)
  );
endmodule
```

491 bytes，SHA-256：

```text
baeb01b058156ecb707dab0aee2c86526632f15cfb487a3788bfff7984a90c81
```

固定 public profile：filelist、top=`t081_top`、category=`enum_values`、无 ABI opt-in、无 include-dir/
define/rate。

## 4. 主 Agent compact preflight

证据根：`/private/tmp/t081-compact-preflight`。

当前产品：

```text
catalog/top overlay: 0/0 + 0/0
graph symbols/declarations/occurrences/total_ranges: 11/11/12/23
MODE_SAFE: declaration 95..104; occurrence 286..295 semantic_reference
MODE_GAP: declaration 110..118; no occurrence
raw MODE_GAP tokens: 110..118, 156..164, 181..189
mapping total/rename/preserve/unsupported: 11/2/9/0
planned edits: 3
write_gate: REWRITE_GATE_COMPILE_FAILED / CATALOG_SEMANTIC_FAILED
formal output: absent
```

只读 graph simulation 应用第 6 节防火墙后：

```text
graph ranges: unchanged 11/11/12/23
MODE_SAFE: eligible; exact raw == semantic ranges; action rename
MODE_GAP: unsupported / enum_lexical_coverage_incomplete; action unsupported; zero edits
mapping: 11 total / 1 rename / 9 preserve / 1 unsupported
edits: 2
strict: 0/0 + 0/0
restore: one file byte-identical
actual simulated gate Formal: exit 0; complete JSON formal_equivalence=pass
fixed `assign data_o = ~(` negative: compile pass; Formal exit 1;
  one unproven cell; contains equiv_status -assert
```

simulation 只冻结 oracle，不是产品交付证据。子 Agent 必须从 actual public gate 重做。

## 5. Ibex 当前缺陷与完整最小闭包

证据根：`/private/tmp/t081-preflight-ibex.CUcDK7`。

固定输入：stability `b99f5e43128964cc78a5c123a31f84e46df76934`，Ibex
`3250d99482f1963891ef1cf19356eeaeeaa71d30`，top=`ibex_top`，45 files，define=`SYNTHESIS`，
profile=`non_abi__enum_values`。

当前 public replay：`FAIL_STRICT`，encrypt exit 1，gate absent，公开错误
`CLI_VNEXT_ORCHESTRATION_INVALID`，Formal 未运行。内部当前 oracle：

```text
graph: 3129 symbols / 3129 declarations / 11391 occurrences / 14520 total ranges
mapping: 3129 total / 354 rename / 2352 preserve / 423 unsupported
planned edits: 1255
strict: REWRITE_GATE_COMPILE_FAILED / CATALOG_SEMANTIC_FAILED
first token: rtl/ibex_compressed_decoder.sv:546..560 RV32ZcaZcbZcmp
```

`RV32ZcaZcbZcmp` record declaration 为 `rtl/ibex_pkg.sv:1285..1299`，当前 action=rename，已有五条
semantic occurrences，但全部物理输入共有 12 个同名 token（含 declaration），仍有 6 个未覆盖：包括
compressed decoder 参数默认值 `546..560`、两个 generate 条件 `1082..1096`/`7918..7932`，以及其他
被 override/elaboration 隐藏的默认值。

只补 `546..560` 后 strict 仍失败；再补三个 decoder 缺口后仍有 16 个语义错误，说明“补首个 occurrence”
不是完整闭包。不得把这些不同 scope/owner 的 token 用 name-only 绑定到一个 record。

第 6 节防火墙 simulation：437 个 enum records 中 86 个覆盖不完整 record 被标为 unsupported，仍保留
268 个实际 rename；结果为 3129 total、268 rename、2352 preserve、509 unsupported、753 edits，45-file
strict compile 通过。该 simulation 是选择保守 record quarantine 的 GO 依据。

## 6. 唯一实现合同

1. 只在 SymbolGraph 建成 `enum_values` records 后、进入 RewritePolicy 前执行防火墙；不得在 policy、mapping、
   rewrite、restore 或 CLI 增加 enum 特例；
2. 对 `SourceSet.ordered_source_files + included_files` 的去重物理文件读取原始 bytes；文件集合必须与现有
   SymbolGraph physical-file 边界一致，按 file 排序保证确定性；
3. 一次性构建 plain SystemVerilog identifier inventory，固定 byte regex：

   ```text
   [A-Za-z_][A-Za-z0-9_$]*
   ```

   inventory value 必须是 exact `(file,start,end)` ranges；不得 substring、Unicode case-fold、token spelling
   归一化或跨文件合并；
4. raw scan 故意覆盖 comments、strings、宏定义、disabled branches 和未 elaborated syntax。它们可能造成
   false-positive quarantine，但只能减少加密，不能产生错误 edit；不得为了提高加密率跳过这些区域；
5. 每条 `enum_values` record 的 known ranges 固定为 declaration + 已有 occurrences；只有 observed raw
   ranges 与 known ranges **集合精确相等** 时保持原 support/reason；
6. 任一 extra 或 missing range 都把该 record 用 `dataclasses.replace` 标为
   `support="unsupported"`、`reason="enum_lexical_coverage_incomplete"`；保留原 declaration、occurrences、
   owner、impact、abi、symbol_id，不新增或删除 occurrence；
7. 同名 enum records 位于不同 scope 时，若任一 record 无法单独证明完整覆盖，保守地将相关 record
   unsupported；不得 name-only 合并或选择最近 owner；
8. 防火墙只处理 `category == "enum_values" and support == "eligible"` 的 records；非 `enum_values`
   records 完全不变，already preserved/unsupported enum records 的原 support/reason/ranges 必须逐项保持；
9. 防火墙必须非真空：compact `MODE_SAFE` 和 Ibex 268 个完整 record 继续 rename；不得整类 unsupported；
10. 不新增公开 API/schema/category/reason 枚举、命令选项或依赖；使用一个小型内部 helper，并在现有
    owner quarantine 已确定原 support/reason 后、最终 SymbolGraph 排序与 RewritePolicy 前只处理仍为
    `eligible` 的 enum records。

## 7. NO-GO 与测试边界

T081 不支持：

- 从 parameter default、generate condition、inactive branch、macro 或 raw token 猜测 enum semantic target；
- 给未绑定 token 新增 `semantic_reference` 或其他 occurrence；
- 按 package/module/name 硬编码 Ibex；
- 只依赖 strict compile 事后发现半改名；
- 为提高 rename 数跳过 comments、strings、宏或 disabled text；
- 修改 `enum_values` 以外 record 的 support、reason、ranges 或 action。

目标 unittest 至少必须证明：

1. compact frozen graph/ranges 与 pre-fix atomic failure；
2. `MODE_SAFE` 保持 eligible/rename 且有 2 edits；
3. `MODE_GAP` reason 精确、零 edits、strict/restore 通过；
4. comments、strings、macro text 中的同名 token 会保守 quarantine；
5. 两个 scope 中同名 enum 值不会 name-only 合并，证据不足时均不产生 edit；
6. 一个非 enum record 即使存在同名 raw gap 也完全不变；
7. actual public gate Formal 正例和固定功能负例；
8. source bytes、duplicate ranges 或非物理 range 的既有审计不弱化。

## 8. pinned Ibex delta oracle

修复后 fresh public runner 必须满足：

```text
classification: PASS_EFFECTIVE
files: 45
mapping_records: 3129
effective_renamed_records: 268
modified_tokens: 753
mapping actions: 268 rename / 2352 preserve / 509 unsupported
enum_lexical_coverage_incomplete records: 86
strict_compile_passed: true
gate_published: true
decrypt_exit_code: 0
restore.files: 45
restore_byte_identical: true
formal.status: FORMAL_NOT_RUN
```

`symbol:enum_values:rtl/ibex_pkg.sv:1285:1299` 必须 action=unsupported、reason 精确，保留原 declaration 与
已有 occurrences，但 execution edits 中该 symbol_id 数量为 0。不得把 external `FORMAL_NOT_RUN` 描述为
等价证明；等价证据只来自 compact actual renamed gate。

## 9. 允许修改

```text
docs/tasks/T081_enum_lexical_completeness_firewall.md
rtl_obfuscator/symbol_graph.py
tests/test_t081_enum_lexical_completeness_firewall.py
tests/fixtures/t081_enum_lexical_firewall/design.f
tests/fixtures/t081_enum_lexical_firewall/design.sv
docs/systemverilog_renaming_table.md
docs/development/future_work.md
```

除此之外不得修改、删除、格式化或生成仓库文件。stability、Ibex checkout 与 prepared input 全程只读；
临时 source/gate/restore/matrix/log 只能写新的 `/private/tmp` 或 unittest 临时目录。

## 10. 子 Agent 执行顺序

1. 完整阅读 AGENTS、T081、task workflow、subagent protocol、T079/T080、category closure、SymbolGraph
   extended collector、renaming table、future work 和 Formal 文档；
2. 核对 exact HEAD/origin/main、clean、唯一 T081 READY；第一次实现/测试编辑前设置 `IN_PROGRESS`，记录
   实际模型及第 9 节七个允许路径；
3. 运行第 11 节 baseline，逐字创建 fixture/test，并在产品修改前复现第 4/5 节；
4. 只实现第 6 节 inventory + record firewall；先跑目标 coverage/NO-GO，再跑 compact public flow；
5. 运行 compact actual-gate Formal 正负例及 fresh pinned Ibex replay；
6. 执行第 11 节五条验收，记录 exact counts/reasons/symbol_id/zero-edit/repo clean；
7. 设置 `READY_FOR_REVIEW` 后停止；不得 stage、commit、push、设置 `ACCEPTED` 或创建 T082。

若 compact hash、raw inventory、Ibex 86/268/753 oracle 或 Formal 发生冲突，必须记录最小事实并停止；不得
改成 lexical occurrence recovery、整个 category preserve 或放松 strict/Formal。

## 11. 唯一验收命令

Baseline（实现前一次）：

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_vnext_category_closure \
  tests.test_t079_parameter_default_occurrence \
  tests.test_t080_expression_sized_cast_parameter -v
```

实现后五条：

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_t081_enum_lexical_completeness_firewall \
  tests.test_vnext_category_closure \
  tests.test_t079_parameter_default_occurrence \
  tests.test_t080_expression_sized_cast_parameter -v

external_root=/Users/lufengchi/Desktop/workspace/rtl_obfuscation_realworld_stability
test "$(git -C "$external_root" rev-parse HEAD)" = b99f5e43128964cc78a5c123a31f84e46df76934
test "$(git -C "$external_root/repos/ibex" rev-parse HEAD)" = 3250d99482f1963891ef1cf19356eeaeeaa71d30
test -z "$(git -C "$external_root" status --short)"
test -z "$(git -C "$external_root/repos/ibex" status --short)"
replay_root=$(mktemp -d /private/tmp/t081-ibex-replay.XXXXXX)
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
  --profiles non_abi__enum_values --formal-policy none
jq -e '
  (.results | length) == 1 and
  .results[0].profile == "non_abi__enum_values" and
  .results[0].classification == "PASS_EFFECTIVE" and
  .results[0].effective_renamed_records == 268 and
  .results[0].cli_summary.summary.files == 45 and
  .results[0].cli_summary.summary.mapping_records == 3129 and
  .results[0].cli_summary.summary.modified_tokens == 753 and
  ([.results[0].mapping_counts[] | .rename // 0] | add) == 268 and
  ([.results[0].mapping_counts[] | .preserve // 0] | add) == 2352 and
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
    | select(
        .category == "enum_values" and
        .action == "unsupported" and
        .reason == "enum_lexical_coverage_incomplete")]
    | length) == 86 and
  ([.mapping.records[]
    | select(.symbol_id == "symbol:enum_values:rtl/ibex_pkg.sv:1285:1299")
    | select(
        .action == "unsupported" and
        .reason == "enum_lexical_coverage_incomplete" and
        .renamed_name == null and
        .declaration == {"file":"rtl/ibex_pkg.sv","start":1285,"end":1299})]
    | length) == 1
' "$replay_root/matrix/non_abi__enum_values/gate/mapping.json"
test -z "$(git -C "$external_root" status --short)"
test -z "$(git -C "$external_root/repos/ibex" status --short)"

conda run -n rtl_obfuscation python -m py_compile \
  rtl_obfuscator/symbol_graph.py tests/test_t081_enum_lexical_completeness_firewall.py

git diff --check HEAD

rg -x -- '- 状态：`READY_FOR_REVIEW`' \
  docs/tasks/T081_enum_lexical_completeness_firewall.md
```

目标 unittest 必须从 actual public gate 执行 strict compile、source-free restore、Formal 正例和固定
`assign data_o = ~(` 负例；不得 identity/copy-gold。目标 unittest 还必须从内部 RewriteExecution 精确断言
目标 unsupported symbol_id 的 edit 数为 0；public gate `mapping.json` 不含顶层 `.edits`。external 只验证
strict/restore。

## 12. Formal verification 记录

```text
formal_verification: PASS
gold: /Users/lufengchi/Desktop/workspace/rtl_obfuscation/tests/fixtures/t081_enum_lexical_firewall
gate: /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t081-formal-positive-shkmz7kk/encrypt/gate（actual public rtl_encrypt output）
top: t081_top
seq: 5
positive_command: /Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python /Users/lufengchi/Desktop/workspace/rtl_obfuscation/scripts/formal_equivalence.py --gold-filelist /Users/lufengchi/Desktop/workspace/rtl_obfuscation/tests/fixtures/t081_enum_lexical_firewall/design.f --gold-root /Users/lufengchi/Desktop/workspace/rtl_obfuscation/tests/fixtures/t081_enum_lexical_firewall --gate-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t081-formal-positive-shkmz7kk/encrypt/gate/design.f --gate-root /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t081-formal-positive-shkmz7kk/encrypt/gate --top t081_top --seq 5
positive_exit_code: 0
positive_result: {"formal_equivalence":"pass","gate":"/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t081-formal-positive-shkmz7kk/encrypt/gate","gold":"/Users/lufengchi/Desktop/workspace/rtl_obfuscation/tests/fixtures/t081_enum_lexical_firewall","seq":5,"top":"t081_top"}
negative_gate: /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t081-formal-negative-3pmu66s1/negative（actual gate copy；只增加冻结 `assign data_o = ~(` mutation）
negative_compile: catalog/top overlay 0/0 + 0/0
negative_command: /Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python /Users/lufengchi/Desktop/workspace/rtl_obfuscation/scripts/formal_equivalence.py --gold-filelist /Users/lufengchi/Desktop/workspace/rtl_obfuscation/tests/fixtures/t081_enum_lexical_firewall/design.f --gold-root /Users/lufengchi/Desktop/workspace/rtl_obfuscation/tests/fixtures/t081_enum_lexical_firewall --gate-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t081-formal-negative-3pmu66s1/negative/design.f --gate-root /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t081-formal-negative-3pmu66s1/negative --top t081_top --seq 5
negative_exit_code: 1
negative_result: combined diagnostic 包含 `unproven` 与 `equiv_status -assert`；未降低证明强度
external_formal: N/A; pinned Ibex uses formal-policy none
```

## 13. 子 Agent 执行记录

```text
status: READY_FOR_REVIEW
actual_model: gpt-5.6-sol / xhigh；当前调度器未提供 Luna 模型或 standard speed 参数，未声称使用 Luna
starting_head: 8c0222e220ff4d86e833a692353be074d5b102cf；parent=8e01a1ebbcd2ddfa724f6743e15adaac1945e176；origin/main=d3072b56f86969936441927efdb5dffedcef67ee；branch main ahead 3；start_time=2026-08-10T11:53:12+0800
allowed_files_check: PASS；启动 worktree clean；唯一活动任务 T081 READY；允许路径精确为本任务单、`rtl_obfuscator/symbol_graph.py`、`tests/test_t081_enum_lexical_completeness_firewall.py`、两个 T081 fixture、`docs/systemverilog_renaming_table.md` 与 `docs/development/future_work.md`
baseline: PASS；`conda run -n rtl_obfuscation python -m unittest tests.test_vnext_category_closure tests.test_t079_parameter_default_occurrence tests.test_t080_expression_sized_cast_parameter -v`；exit 0；Ran 25 tests；OK；T079/T080 compact actual-gate Formal 正例 exit 0、固定功能负例 exit 1
contract_evidence_correction: v1.1；主 Agent 确认 public gate `mapping.json` 无顶层 `.edits`；external record oracle 改为 action/reason/`renamed_name == null`/精确 declaration，并保留 modified_tokens=753；目标测试改由内部 RewriteExecution 直接证明该 symbol_id zero edit；产品行为与允许范围不变
pre_fix_characterization: PASS；fixture 精确为 10/491 bytes 且 SHA-256 匹配第 3 节；catalog/top overlay 0/0 + 0/0；graph 11/11/12/23；`MODE_SAFE` declaration `95..104`、occurrence `286..295 semantic_reference`；`MODE_GAP` declaration `110..118`、无 occurrence，而 raw ranges 为 `110..118,156..164,181..189`；mapping 11/2/9/0、3 planned edits；public encrypt exit 1 `CLI_VNEXT_ORCHESTRATION_INVALID`，gate absent；目标测试实现前 Ran 8，所有防火墙/public-flow 断言按预期失败，未新增产品行为
changed_files: 精确为第 9 节七个路径：本任务单、`rtl_obfuscator/symbol_graph.py`、T081 target unittest、两个冻结 fixture、`docs/systemverilog_renaming_table.md`、`docs/development/future_work.md`；允许列表外零修改
commands: baseline 见上；开发期目标测试与 pre-fix probe；实现后最终执行第 11 节五条：四模块 unittest exit 0/Ran 33/OK；fresh pinned Ibex replay + 两个 corrected jq oracle 均 true；py_compile exit 0；本记录后最终 `git diff --check HEAD` 与 READY_FOR_REVIEW guard；未运行 blanket discovery、历史 driver 或 RISC-V-Vector Formal
results: PASS；target 8/8、相关 baseline 25/25；fixture hashes、compact mapping/execution、strict/source-free restore、actual-gate Formal 正负、Ibex 86/268/753 oracle 均满足；finish_time=2026-08-10T12:08:45+0800
inventory_contract: PASS；固定 byte regex `[A-Za-z_][A-Za-z0-9_$]*`；`ordered_source_files + included_files` 去重后按 file 排序并一次读取 raw bytes，inventory 为 exact `(file,start,end)` sets；owner quarantine 后只对仍为 `eligible` 的 enum record 比较 observed 与 declaration+occurrences known set；不补 occurrence、不猜 target、不改非 enum 或既有 preserved/unsupported record
compact_oracle: PASS；catalog/top overlay 0/0 + 0/0；graph ranges 保持 11/11/12/23；`MODE_SAFE` declaration `95..104` 与 occurrence `286..295` 完整，继续 eligible/rename；`MODE_GAP` raw `110..118,156..164,181..189` 对 known 不完整，整 record unsupported/reason exact；mapping 11/1/9/1；内部 RewriteExecution 2 edits，`symbol:enum_values:design.sv:110:118` exact 0 edits；public summary 1 file/11 records/2 modified tokens、strict true，source-free restore 仅恢复 `design.sv` 且 byte-identical
no_go_and_non_vacuous: PASS；comments、strings、unused macro 中单独出现同名 token 均保守 quarantine；两个 scope 同名 enum 不合并且两 record 均 zero rename；完整 `MODE_SAFE` 继续实际改名，未整类禁用；构造的 preserved/unsupported enum 即使 lexical mismatch 也保持原 support/reason/ranges，非 enum record identity 不变；既有 duplicate physical range audit 仍 `SYMBOL_GRAPH_RANGE_CONFLICT`
ibex_replay: PASS；fresh root `/private/tmp/t081-ibex-replay.2ebGm4`；stability `b99f5e43128964cc78a5c123a31f84e46df76934` 与 Ibex `3250d99482f1963891ef1cf19356eeaeeaa71d30` 前后 clean；`non_abi__enum_values=PASS_EFFECTIVE`，45 files、3129 records、268 rename/2352 preserve/509 unsupported、753 edits、86 records reason=`enum_lexical_coverage_incomplete`；目标 `symbol:enum_values:rtl/ibex_pkg.sv:1285:1299` action unsupported/reason exact/renamed_name null/declaration `1285..1299`；strict/gate/decrypt true，restore 45 files byte-identical；formal-policy none，`FORMAL_NOT_RUN` 未描述为等价证明
formal_verification: PASS；compact actual public renamed gate top=`t081_top`, seq=5，正例 exit 0 且 complete JSON `formal_equivalence=pass`；actual-gate copy 只增加冻结 `assign data_o = ~(`，strict 0/0 + 0/0，负例 exit 1 并命中 `unproven`/`equiv_status -assert`；完整命令与路径见第 12 节；external Formal N/A
documentation: PASS；renaming table 写明 enum 仅在原始 lexical token 与 semantic ranges 完整一致时改名；future work 写明 record quarantine、raw comments/strings/macro/disabled-text 保守边界与不做 generic recovery
boundaries: 不从 raw token、parameter default、generate/inactive branch、macro 或同名 scope 猜 semantic target；不补 lexical occurrence，不新增 enum resolver；raw false positive 允许少加密；不改 API/schema/category/policy/mapping/rewrite/restore/CLI/Formal；existing owner quarantine reason 优先保持
review_request: READY_FOR_REVIEW；请主 Agent 独立执行 v1.1 第 11 节五条验收并审查 owner-quarantine-after ordering、eligible-only identity 与 zero-edit 证据；子 Agent 未 stage/commit/push、未设置 ACCEPTED、未创建 T082
```

## 14. 主 Agent 验收

```text
review_date: 2026-08-10
reviewer: 主 Agent
starting_head: 8c0222e220ff4d86e833a692353be074d5b102cf；parent=
  8e01a1ebbcd2ddfa724f6743e15adaac1945e176；origin/main=
  d3072b56f86969936441927efdb5dffedcef67ee；branch main
allowed_files: PASS；最终 worktree 精确为第 9 节七个路径；两个 fixture 仅含 design.f/design.sv，
  10/491 bytes 与冻结 SHA-256 完全匹配；允许列表外零修改
implementation_review: PASS；只新增一次 raw byte identifier inventory 与 record-level helper；固定 regex
  `[A-Za-z_][A-Za-z0-9_$]*`，物理文件去重排序；应用点在 existing owner quarantine 后，且只处理仍为
  eligible 的 enum；set equality 不成立时整 record unsupported/reason exact，不增加 occurrence、不猜 target；
  非 enum 与既有 preserved/unsupported support/reason/ranges identity 不变；无 policy/mapping/rewrite/
  restore/CLI/Formal 特例
target_and_regression: PASS；v1.1 第 11 节第 1 条 exit 0；Ran 33 tests；OK
compact_oracle: PASS；graph 11/11/12/23 不变；MODE_SAFE 保持 eligible/rename；MODE_GAP 为
  unsupported/enum_lexical_coverage_incomplete；mapping 11 total、1 rename、9 preserve、1 unsupported；
  strict compile 0/0 + 0/0；public gate 发布；source-free restore 仅恢复 design.sv 且逐字节一致
inventory_and_zero_edit: PASS；MODE_GAP raw ranges 110..118/156..164/181..189 与 known set 不相等；
  internal RewriteExecution 共 2 edits，`symbol:enum_values:design.sv:110:118` exact 0 edits；comments、
  strings、macro 和双 scope 同名 token 均只触发保守 quarantine；complete enum 继续实际 edit
ibex_replay: PASS；Main-Agent fresh root=/private/tmp/t081-main-ibex.g0MxSG；stability
  b99f5e43128964cc78a5c123a31f84e46df76934、Ibex
  3250d99482f1963891ef1cf19356eeaeeaa71d30 前后 clean；non_abi__enum_values=PASS_EFFECTIVE，45 files、
  3129 records、268 rename/2352 preserve/509 unsupported、753 edits、86 条新 reason；目标
  `symbol:enum_values:rtl/ibex_pkg.sv:1285:1299` action unsupported/reason exact/renamed_name null；
  strict/gate/decrypt/45-file byte restore 全通过
formal_positive: PASS；Main-Agent compact actual public gate
  /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t081-formal-positive-2ng9altn/encrypt/gate；
  top=t081_top；seq=5；exit 0；complete JSON formal_equivalence=pass
formal_negative: PASS as expected negative；Main-Agent actual-gate copy
  /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t081-formal-negative-ofa7kxy5/negative；只含冻结
  `assign data_o = ~(` 变更；strict compile 0/0 + 0/0；exit 1；断言匹配 `unproven` 与
  `equiv_status -assert`
external_formal: N/A；pinned Ibex 按合同 formal-policy none，结果 FORMAL_NOT_RUN，未描述为等价证明
py_compile: PASS；v1.1 第 11 节命令 exit 0
diff_check: PASS；`git diff --check HEAD` exit 0
ready_for_review_guard: PASS；精确 guard 在本次 ACCEPTED 状态变更前 exit 0
documentation: PASS；renaming table 与 future work 明确 raw inventory、单 record quarantine、false-positive
  只减少加密和不做 generic enum recovery 的边界
forbidden_runs: 未运行 blanket discovery、历史 acceptance driver 或 RISC-V-Vector Formal
decision: ACCEPTED；无法证明完整引用闭包的 enum record 提前 zero-edit，覆盖完整 record 继续实际改名，
  满足“宁可少加密、不能加密错误”
delivery_commit: current acceptance commit；exact hash 在提交后报告并冻结进后继合同
push: NOT_RUN；等待对本次新交付的明确授权
successor: Main Agent 仅在本地交付提交完成后决定下一任务
```
