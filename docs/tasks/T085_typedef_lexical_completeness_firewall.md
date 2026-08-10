# T085：typedef 词法覆盖完整性防火墙

- 状态：`READY`
- 创建日期：2026-08-10
- 起始分支：`main`
- 起始 HEAD：`46014d5489cc77dae899a154fd4fcbef47d36acc`
- 起始 origin/main：`d3072b56f86969936441927efdb5dffedcef67ee`
- 前置任务：T084 已 `ACCEPTED`
- 任务类型：SymbolGraph `typedefs` record 级安全防火墙；会产生 rewritten RTL，必须执行 actual-gate Formal
- 实现负责人：代码子 Agent（请求模型：Luna extra high / standard speed；当前执行器无 Luna，实际配置必须如实记录）

## 1. 单一目标

为 `typedefs` 增加 record 级词法覆盖完整性防火墙：只有一个 eligible typedef record 在全部物理输入
源码中的同名 plain identifier ranges，与该 record 已有 declaration + semantic occurrences ranges **集合精确
相等** 时，才允许它继续改名。

若两组 ranges 不相等，必须把整条 record 标为：

```text
support = unsupported
reason = typedef_lexical_coverage_incomplete
```

该 record 保留 declaration、已有 occurrences、owner、impact、ABI 与 symbol identity，但不得产生任何
rewrite edit。不得猜测缺口的类型身份、补 lexical occurrence，或等 strict gate 事后发现半改名。

这是“宁可少加密、不能加密错误”的安全闭包，不是 generic type-reference resolver。覆盖完整的 typedef
仍必须实际改名，不能整类 preserve/unsupported。

## 2. 起始状态与冻结 baseline

```text
branch: main
HEAD: 46014d5489cc77dae899a154fd4fcbef47d36acc
parent: 17fc7f9fabea37cfb8567734ab4f8a1425478f1e
origin/main: d3072b56f86969936441927efdb5dffedcef67ee
worktree: clean
active implementation tasks: none
related baseline: 68/68 PASS
```

冻结 baseline：

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
```

主 Agent 结果：exit 0，Ran 68 tests，OK；相关任务 actual renamed-gate Formal 正例 exit 0，固定功能
负例 exit 1。

## 3. 冻结 compact fixture

子 Agent 必须逐字创建：

```text
tests/fixtures/t085_typedef_lexical_firewall/design.f
tests/fixtures/t085_typedef_lexical_firewall/design.sv
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
package t085_pkg;
  typedef enum logic {WordZero, WordOne} word_t;
endpackage

module t085_top (
  input  logic data_i,
  output logic data_o
);
  typedef enum logic {SafeZero, SafeOne} safe_t;
  safe_t safe_value;
`ifdef T085_TYPEDEF_QUERY
  import t085_pkg::*;
  word_t unsafe_value;
  logic [$bits(word_t)-1:0] width_probe;
  assign unsafe_value = data_i ? WordOne : WordZero;
  assign width_probe = data_i;
`endif
  assign safe_value = data_i ? SafeOne : SafeZero;
  assign data_o = (safe_value == SafeOne);
endmodule
```

固定为 522 bytes，SHA-256：

```text
80695d0a8ef7325fe00c046db6b20c7df514ab966559016545f7d1ea0eb64eff
```

固定 public profile：filelist、top=`t085_top`、define=`T085_TYPEDEF_QUERY`、category=`typedefs`；
project/filelist scope 自动选择 ABI category，不增加其他 include-dir/define/rate。

## 4. 主 Agent compact preflight

证据根：`/private/tmp/t085-compact`、`/private/tmp/t085-compact-firewall-v7.8SrxJY`。

起始产品、启用 public define：

```text
catalog/top overlay: 0/0 + 0/0
graph symbols/declarations/occurrences/total_ranges: 12/12/15/27
word_t declaration: design.sv:59..65
word_t known semantic use: design.sv:265..271
word_t missing raw use: design.sv:301..307 in $bits(word_t)
safe_t declaration/use: design.sv:186..192 / 196..202
mapping total/rename/preserve/unsupported: 12/2/10/0
planned edits: 5
public encrypt: exit 1, CLI_VNEXT_ORCHESTRATION_INVALID
gate: absent
```

只读 runtime simulation 应用第 7 节防火墙后：

```text
graph ranges: unchanged 12/12/15/27
word_t: unsupported / typedef_lexical_coverage_incomplete; zero edits
safe_t: eligible; exact raw == known ranges; action rename; two edits
mapping: 12 total / 1 rename / 10 preserve / 1 unsupported
actual edits: 2
strict compile: 0/0 + 0/0
restore: 1 file byte-identical
```

simulation 只冻结 oracle，不是产品交付证据；子 Agent 必须从实际产品 public gate 重做。

## 5. 当前 Ibex 失败与根因边界

固定 pins：

```text
product starting HEAD: 46014d5489cc77dae899a154fd4fcbef47d36acc
stability: b99f5e43128964cc78a5c123a31f84e46df76934
Ibex: 3250d99482f1963891ef1cf19356eeaeeaa71d30
top: ibex_top
physical files: 45
define: SYNTHESIS
profile: abi__typedefs
```

fresh public preflight 根：`/private/tmp/t085-typedef-public-prefix.Oe087f`。当前结果：

```text
classification: FAIL_STRICT
effective renamed records: 0
strict_compile_passed: false
gate_published: false
restore: not run / false
formal.status: FORMAL_NOT_RUN
public error: CLI_VNEXT_ORCHESTRATION_INVALID
```

缺口不是单一语法形状：包括 `$bits(type)`、package-qualified type use、未实例化物理 module 中的 type
use，以及多个 elaboration 未暴露的 type reference。代表性缺口：

```text
csr_num_e declaration: rtl/ibex_pkg.sv:17784..17793
missing $bits(csr_num_e): rtl/ibex_cs_registers.sv:12733..12742
prim_secded_type_e declaration: vendor/lowrisc_ip/ip/prim/rtl/prim_secded_pkg.sv:401..419
missing qualified use: rtl/ibex_top.sv:12429..12447
```

不得用一个 generic/name-only resolver 将这些互不相同的 context 一次性猜绑。

## 6. 安全决策与模拟闭包

选择 record-level raw lexical completeness firewall，而不是继续扩展 type resolver：

1. 任一漏改 type token 都可能使 gate 无法编译或把同名不同 owner 错绑；
2. raw inventory 对 comments/string/macro/disabled text 的 false positive 只会减少加密；
3. exact set equality 才允许 edit，安全条件可直接审计；
4. 完整 record 继续实际 rename，防火墙不是 category-wide disable。

主 Agent在 `/private/tmp/t085-typedef-firewall-fresh.Be9rYs` 的 runtime simulation：

```text
graph: 3129 symbols / 3129 declarations / 11675 occurrences / 14804 ranges
quarantined eligible typedef records: 10
mapping: 3129 total / 19 rename / 2591 preserve / 519 unsupported
actual edits: 79
strict compile: 0/0 + 0/0
restore: 45 files byte-identical
```

精确 10 条新 quarantine：

```text
symbol:typedefs:rtl/ibex_pkg.sv:892:901       regfile_e
symbol:typedefs:rtl/ibex_pkg.sv:1308:1316     rv32zc_e
symbol:typedefs:rtl/ibex_pkg.sv:1719:1727     opcode_e
symbol:typedefs:rtl/ibex_pkg.sv:3818:3828     priv_lvl_e
symbol:typedefs:rtl/ibex_pkg.sv:10038:10047   pmp_req_e
symbol:typedefs:rtl/ibex_pkg.sv:17784:17793   csr_num_e
symbol:typedefs:rtl/ibex_pkg.sv:19748:19759   lfsr_seed_t
symbol:typedefs:rtl/ibex_pkg.sv:19816:19827   lfsr_perm_t
symbol:typedefs:rtl/ibex_pkg.sv:20437:20448   ibex_mubi_t
symbol:typedefs:vendor/lowrisc_ip/ip/prim/rtl/prim_secded_pkg.sv:401:419 prim_secded_type_e
```

非真空正例固定为 `symbol:typedefs:rtl/ibex_pkg.sv:3659:3667` (`csr_op_e`)：raw 与 known
ranges 完整，修复后仍 action=`rename`。

## 7. 唯一实现合同

1. 只在 `rtl_obfuscator/symbol_graph.py` 增加一个小型内部 typedef completeness helper；不得改 policy、
   mapping、rewrite、restore、orchestration、CLI 或 Formal；
2. 复用 T081 已有 physical-file raw identifier inventory 机制；若为最小共享实现需要重命名内部 helper，
   必须保持 T081 输出逐项不变，不得重复读取或建立第二套 scanner；
3. inventory 文件集合固定为 `SourceSet.ordered_source_files + included_files` 的去重物理文件，按 file
   排序并读取原始 bytes；固定 byte regex `[A-Za-z_][A-Za-z0-9_$]*`；
4. inventory value 固定为 exact `(file,start,end)` ranges；不得 substring、Unicode case-fold、spelling
   normalization、跨文件合并或 token category 推断；
5. raw scan 故意覆盖 comments、strings、macro text、disabled branches 与未 elaborated syntax。它们可能
   造成 false-positive quarantine，但只能少加密，不得为提高 rename 数而跳过；
6. 对每条 `category == "typedefs" and support == "eligible"` record，known ranges 固定为 declaration +
   已有 occurrences；只有 observed raw ranges 与 known ranges 集合精确相等时保持原 record；
7. 任一 extra 或 missing range 都用 `dataclasses.replace` 标为 `support="unsupported"`、
   `reason="typedef_lexical_coverage_incomplete"`；不新增、删除或重写 occurrence，不改 symbol_id、owner、
   declaration、impact、ABI；
8. 同名 typedef records 位于不同 scope 时，只要 raw token 无法分别证明属于某一 record，就保守地将
   相关 eligible records unsupported；不得 name-only 合并、按最近 owner分配或共享 ranges；
9. 只处理仍 eligible 的 typedef records；preexisting preserved/unsupported typedef 的 support/reason/ranges
   identity 必须保持，非 typedef category 全部不变；
10. 应用顺序固定在现有 `_apply_owner_quarantine()` 之后、T081 enum lexical firewall 之前；owner quarantine
    的原 reason 优先，T081 enum records/counts/reasons 必须完全不变；
11. 防火墙必须非真空：compact `safe_t` 与 Ibex 19 条完整 typedef 继续 rename；不得整类禁用；
12. 不新增公开 API/schema/category/reason enum、配置、dependency、fallback、cache、second parser 或 Ibex
    hard-code。

## 8. NO-GO 与目标测试

T085 不支持：

- 给 `$bits`、qualified name、cast、uninstantiated module 或任意缺口补 semantic occurrence；
- 从 raw token 推断 target、scope、package、owner 或 type identity；
- 修改 ABI/category 选择语义，或把整个 `typedefs` category preserve；
- 只靠 strict compile 事后发现半改名；
- 跳过 comments/string/macro/disabled text 来提高 rename 数；
- 覆盖 existing owner quarantine、T081 enum reason，或修改其他 category record。

目标 unittest 至少证明：

1. fixture bytes/hash、修复前 graph/mapping 与 public atomic failure；
2. `word_t` raw ranges 比 known ranges 多 `301..307`，变为 exact reason 且零 edit；
3. `safe_t` exact equality，保持 eligible/rename，declaration/use 使用同一 renamed name与两个 edits；
4. comments、string、macro text 中额外同名 token 都只触发保守 quarantine；
5. 两个 scope 中同名 typedef不做 name-only 合并，证据不足时相关 record均零 edit；
6. complete typedef保持原 support/reason/ranges；existing preserve/unsupported typedef身份逐项不变；
7. 非 typedef categories完全不变；
8. T081 enum firewall 的 MODE_SAFE/MODE_GAP action、reason、range/edit oracle完全不变；
9. duplicate/overlapping/nonphysical ranges 的既有 fail-closed审计不弱化；
10. actual public gate strict 0/0+0/0、source-free restore逐字节一致；
11. 第 10 节 actual renamed-gate Formal正例与固定功能负例。

## 9. pinned Ibex post-fix oracle

fresh `/private/tmp`、`formal-policy none`：

```text
profile: abi__typedefs
classification: PASS_EFFECTIVE
files: 45
mapping records: 3129
actions: 19 rename / 2591 preserve / 519 unsupported
effective renamed records: 19
modified tokens: 79
typedef_lexical_coverage_incomplete records: 10
strict_compile_passed: true
gate_published: true
decrypt_exit_code: 0
restore.files: 45
restore_byte_identical: true
formal.status: FORMAL_NOT_RUN
```

`csr_num_e`、`ibex_mubi_t` 与 `prim_secded_type_e` 三条冻结 record 必须 action=unsupported、reason精确、
renamed_name=null；`csr_op_e` 必须 action=rename。external Formal为 none，不得描述为等价证明。

## 10. compact Formal 边界

- public encrypt/strict 带 `T085_TYPEDEF_QUERY`，必须证明 `$bits(word_t)` 保持原名且 gate可编译；
- Yosys gold/gate均不传 define，避开 package import/`$bits(type)` frontend边界；
- actual gate仍必须真实改写宏外 module-local `safe_t` declaration/use，不是 identity/copy-gold；
- 正例：top=`t085_top`、seq=5、exit 0、完整 JSON `formal_equivalence=pass`；
- 固定负例从 actual gate copy，只把宏外
  `assign data_o = (safe_value == SafeOne);` 改为逻辑取反；
- 负例带 public define 的 PySlang strict必须 0/0+0/0，Formal必须 exit 1、最终至少1个 unproven并含
  `equiv_status -assert`。

主 Agent simulation：actual gate `/private/tmp/t085-compact-firewall-v7.8SrxJY/gate` 正例 exit 0/JSON
pass；负例 `/private/tmp/t085-compact-negative.72EuKk/negative` strict通过、Formal exit 1、最终1个
unproven。

## 11. 允许修改与文档交付

只允许：

```text
docs/tasks/T085_typedef_lexical_completeness_firewall.md
rtl_obfuscator/symbol_graph.py
tests/test_t085_typedef_lexical_completeness_firewall.py
tests/fixtures/t085_typedef_lexical_firewall/design.f
tests/fixtures/t085_typedef_lexical_firewall/design.sv
docs/systemverilog_renaming_table.md
docs/development/future_work.md
```

- renaming table 的 `typedefs` 行补充 raw lexical ranges 与 semantic ranges exact equality 才允许改名；
- future work记录 false-positive只减少加密、未实现 generic type-reference recovery及仍未知的缺口语境；
- README不改：公开命令、category、schema没有变化。

禁止修改其他文件；stability、Ibex checkout 与 prepared input全程只读；临时 source/gate/restore/matrix/log
只能写新 `/private/tmp` 或 unittest临时目录。子 Agent不得 stage/commit/push、设置 `ACCEPTED` 或创建 T086。

## 12. 子 Agent 执行顺序

1. 完整阅读 AGENTS、T085、task workflow、subagent protocol、T081、T084、category closure、SymbolGraph、
   renaming table、future work与 Formal文档；
2. 核对 exact HEAD/origin/main、clean、唯一 T085 READY；第一次实现/测试编辑前将状态改为
   `IN_PROGRESS`，记录实际模型与第 11 节七个允许路径；
3. 运行第 13 节 baseline，逐字创建 fixture/test，并在产品修改前复现第 4/5 节；
4. 只实现第 7 节 typedef record firewall；先跑目标 coverage/NO-GO/T081 identity，再跑 compact public flow；
5. 运行 compact actual-gate Formal正负例及 fresh pinned Ibex replay；
6. 执行第 13 节五条验收，记录 exact counts/reasons/symbol_id/zero-edit/repo clean；
7. 设置 `READY_FOR_REVIEW` 后停止；不得 stage、commit、push、设置 `ACCEPTED` 或创建 T086。

若 compact hash、T081 identity、Ibex 10/19/79 oracle或 Formal发生冲突，必须记录最小事实并停止；不得改成
lexical occurrence recovery、整个 category preserve或放松 strict/Formal。

## 13. 验收命令（固定五条）

开始前 baseline 见第 2 节。实现后五条：

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_t085_typedef_lexical_completeness_firewall \
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
replay_root=$(mktemp -d /private/tmp/t085-ibex-replay.XXXXXX)
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
  --profiles abi__typedefs --formal-policy none
jq -e '
  (.results | length) == 1 and
  .results[0].profile == "abi__typedefs" and
  .results[0].classification == "PASS_EFFECTIVE" and
  .results[0].effective_renamed_records == 19 and
  .results[0].cli_summary.summary.files == 45 and
  .results[0].cli_summary.summary.mapping_records == 3129 and
  .results[0].cli_summary.summary.modified_tokens == 79 and
  ([.results[0].mapping_counts[] | .rename // 0] | add) == 19 and
  ([.results[0].mapping_counts[] | .preserve // 0] | add) == 2591 and
  ([.results[0].mapping_counts[] | .unsupported // 0] | add) == 519 and
  .results[0].strict_compile_passed == true and
  .results[0].gate_published == true and
  .results[0].decrypt_exit_code == 0 and
  .results[0].restore_byte_identical == true and
  .results[0].restore.files == 45 and
  .results[0].formal.status == "FORMAL_NOT_RUN"
' "$replay_root/matrix/matrix.json"
jq -e '
  ([.mapping.records[]
    | select(.category == "typedefs" and
             .action == "unsupported" and
             .reason == "typedef_lexical_coverage_incomplete")]
    | length) == 10 and
  ([.mapping.records[]
    | select(.symbol_id == "symbol:typedefs:rtl/ibex_pkg.sv:17784:17793" or
             .symbol_id == "symbol:typedefs:rtl/ibex_pkg.sv:20437:20448" or
             .symbol_id == "symbol:typedefs:vendor/lowrisc_ip/ip/prim/rtl/prim_secded_pkg.sv:401:419")
    | select(.action == "unsupported" and
             .reason == "typedef_lexical_coverage_incomplete" and
             .renamed_name == null)] | length) == 3 and
  ([.mapping.records[]
    | select(.symbol_id == "symbol:typedefs:rtl/ibex_pkg.sv:3659:3667")
    | select(.action == "rename" and .renamed_name != null)] | length) == 1
' "$replay_root/matrix/abi__typedefs/gate/mapping.json"
test -z "$(git -C "$external_root" status --short)"
test -z "$(git -C "$external_root/repos/ibex" status --short)"

conda run -n rtl_obfuscation python -m py_compile \
  rtl_obfuscator/symbol_graph.py tests/test_t085_typedef_lexical_completeness_firewall.py

git diff --check HEAD

rg -x -- '- 状态：`READY_FOR_REVIEW`' \
  docs/tasks/T085_typedef_lexical_completeness_firewall.md
```

目标 unittest必须从 actual public gate执行 strict compile、source-free restore、Formal正例和固定负例；不得
identity/copy-gold。目标 unittest还必须从内部 RewriteExecution精确断言 quarantined `word_t` symbol_id的
edit数为0；public `mapping.json`不假设存在顶层 edits。external runner限时300秒，formal-policy none；
不运行 blanket discovery、历史 driver或 RISC-V-Vector Formal。

## 14. Formal verification 记录

```text
formal_verification: PENDING
gold: tests/fixtures/t085_typedef_lexical_firewall
gate: actual public rtl_encrypt output; PENDING
top: t085_top
seq: 5
public_define: T085_TYPEDEF_QUERY
positive_yosys_define: none
positive_command: PENDING
positive_exit_code: PENDING
positive_result: PENDING; require complete JSON formal_equivalence=pass
actual_gate_non_identity: PENDING; safe_t declaration/use must be genuinely renamed
negative_gate: PENDING; actual-gate copy with only frozen macro-outside logic inversion
negative_compile_with_public_define: PENDING; require 0/0 + 0/0
negative_command: PENDING
negative_exit_code: PENDING; require 1
negative_result: PENDING; require unproven and equiv_status -assert
external_formal: N/A; pinned Ibex uses formal-policy none
```

## 15. 子 Agent 执行记录

```text
status: PENDING
actual_model: PENDING；必须如实记录
starting_head: PENDING；必须记录 contract commit、parent、origin/main、branch ahead、clean、唯一活动任务
allowed_files_check: PENDING
baseline: PENDING
pre_fix_characterization: PENDING
changed_files: PENDING
commands: PENDING
results: PENDING
inventory_contract: PENDING
compact_oracle: PENDING
no_go_and_non_vacuous: PENDING
ibex_replay: PENDING
formal_verification: PENDING
documentation: PENDING
boundaries: PENDING
review_request: PENDING
```

## 16. 主 Agent 验收

```text
review_date: PENDING
reviewer: 主 Agent
allowed_files: PENDING
implementation_review: PENDING
target_and_regression: PENDING
compact_oracle: PENDING
inventory_and_zero_edit: PENDING
ibex_replay: PENDING
formal_positive: PENDING
formal_negative: PENDING
external_formal: N/A; formal-policy none
py_compile: PENDING
diff_check: PENDING
ready_for_review_guard: PENDING
documentation: PENDING
forbidden_runs: PENDING
decision: PENDING
delivery_commit: PENDING
push: NOT_RUN；此前授权只覆盖 b97b323..d3072b5，等待对本次新交付的明确授权
```
