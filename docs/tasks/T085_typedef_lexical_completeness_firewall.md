# T085：typedef 词法覆盖完整性防火墙

- 状态：`ACCEPTED`
- 合同版本：1.1（2026-08-10 修正 compact pre-fix edit 计数；行为、范围与 post-fix oracle 不变）
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
planned edits: 4
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
formal_verification: PASS；actual public renamed gate 正例通过，固定功能负例按预期失败
gold: /Users/lufengchi/Desktop/workspace/rtl_obfuscation/tests/fixtures/t085_typedef_lexical_firewall
gate: /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t085-public-jcop2ccl/encrypt/gate（actual public rtl_encrypt output）
top: t085_top
seq: 5
public_define: T085_TYPEDEF_QUERY
positive_yosys_define: none
positive_command: `/Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python /Users/lufengchi/Desktop/workspace/rtl_obfuscation/scripts/formal_equivalence.py --gold-filelist /Users/lufengchi/Desktop/workspace/rtl_obfuscation/tests/fixtures/t085_typedef_lexical_firewall/design.f --gold-root /Users/lufengchi/Desktop/workspace/rtl_obfuscation/tests/fixtures/t085_typedef_lexical_firewall --gate-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t085-public-jcop2ccl/encrypt/gate/design.f --gate-root /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t085-public-jcop2ccl/encrypt/gate --top t085_top --seq 5`
positive_exit_code: 0
positive_result: `{"formal_equivalence":"pass","gate":"/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t085-public-jcop2ccl/encrypt/gate","gold":"/Users/lufengchi/Desktop/workspace/rtl_obfuscation/tests/fixtures/t085_typedef_lexical_firewall","seq":5,"top":"t085_top"}`
actual_gate_non_identity: PASS；public define 下 `word_t` 三处全部保留原名；`safe_t` declaration/use 使用同一非原名，共1个 rename record/2 actual edits，不是 identity/copy-gold
negative_gate: /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t085-formal-negative-rc0szhqo/negative；从 actual gate copy 后只将冻结宏外 `assign data_o = (safe_value == SafeOne);` 改为逻辑取反
negative_compile_with_public_define: PASS；catalog/top overlay 0/0 + 0/0
negative_command: `/Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python /Users/lufengchi/Desktop/workspace/rtl_obfuscation/scripts/formal_equivalence.py --gold-filelist /Users/lufengchi/Desktop/workspace/rtl_obfuscation/tests/fixtures/t085_typedef_lexical_firewall/design.f --gold-root /Users/lufengchi/Desktop/workspace/rtl_obfuscation/tests/fixtures/t085_typedef_lexical_firewall --gate-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t085-formal-negative-rc0szhqo/negative/design.f --gate-root /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t085-formal-negative-rc0szhqo/negative --top t085_top --seq 5`
negative_exit_code: 1
negative_result: PASS（固定负例按预期被拒绝）；包含 `equiv_status -assert`，最终1个 unproven `$equiv` cell
external_formal: N/A; pinned Ibex uses formal-policy none
```

## 15. 子 Agent 执行记录

```text
status: READY_FOR_REVIEW
actual_model: gpt-5.6-sol / xhigh；当前执行器未提供 Luna 模型或 standard speed 参数，未声称使用 Luna
starting_head: 777cbb06c20a578b672a3bae85717a86648b6eff；parent=46014d5489cc77dae899a154fd4fcbef47d36acc；origin/main=d3072b56f86969936441927efdb5dffedcef67ee；branch main ahead 11；start_time=2026-08-10T14:30:39+08:00；启动 worktree clean；唯一活动任务 T085 READY
allowed_files_check: PASS；允许路径精确为本任务单、`rtl_obfuscator/symbol_graph.py`、`tests/test_t085_typedef_lexical_completeness_firewall.py`、两个 T085 fixture、`docs/systemverilog_renaming_table.md` 与 `docs/development/future_work.md`；启动时无用户修改重叠
baseline: PASS；`conda run -n rtl_obfuscation python -m unittest tests.test_t084_struct_pattern_field tests.test_t083_named_function_argument tests.test_t082_function_end_label tests.test_t076_module_end_label tests.test_vnext_category_closure tests.test_t079_parameter_default_occurrence tests.test_t080_expression_sized_cast_parameter tests.test_t081_enum_lexical_completeness_firewall -v`；exit 0，Ran 68 tests，OK；相关 actual renamed-gate Formal 正例 exit 0、固定功能负例 exit 1
pre_fix_characterization: PASS（冻结失败已复现）；fixture 10/522 bytes 与两条 SHA-256 精确匹配；catalog/top overlay 0/0 + 0/0；graph=12/12/15/27；`word_t` declaration `59..65`、known semantic use `265..271`、raw ranges=`59..65,265..271,301..307`，缺口为 `$bits(word_t)`；`safe_t` declaration/use=`186..192/196..202` 且 raw==known；mapping=12 total / 2 rename / 10 preserve / 0 unsupported，planned edits=4；public exit 1 `CLI_VNEXT_ORCHESTRATION_INVALID` 且 gate absent；internal `REWRITE_GATE_COMPILE_FAILED` / `CATALOG_SEMANTIC_FAILED` 且 output absent；fresh pinned Ibex root `/private/tmp/t085-ibex-prefix.eXnjnC`，`abi__typedefs=FAIL_STRICT`、effective rename 0、strict=false、gate=false、restore=false、Formal=`FORMAL_NOT_RUN`，stability/Ibex 前后 clean
changed_files: 精确为第 11 节七个路径：本任务单、`rtl_obfuscator/symbol_graph.py`、T085 target unittest、两个冻结 fixture、`docs/systemverilog_renaming_table.md` 与 `docs/development/future_work.md`；允许列表外零修改
commands: 冻结 68-test baseline；compact pre-fix graph/mapping/internal/public probe；fresh pinned Ibex pre-fix replay；开发期 target tests；第 13 节五条验收：`conda run -n rtl_obfuscation python -m unittest tests.test_t085_typedef_lexical_completeness_firewall tests.test_t084_struct_pattern_field tests.test_t083_named_function_argument tests.test_t082_function_end_label tests.test_t076_module_end_label tests.test_vnext_category_closure tests.test_t079_parameter_default_occurrence tests.test_t080_expression_sized_cast_parameter tests.test_t081_enum_lexical_completeness_firewall -v`，fresh pinned Ibex materialize/runner 与两条 exact `jq -e`，`conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/symbol_graph.py tests/test_t085_typedef_lexical_completeness_firewall.py`，`git diff --check HEAD`，exact READY_FOR_REVIEW guard
results: PASS；v1.1 目标9 tests + 冻结68回归合计 Ran 77 tests，OK；compact public strict/source-free restore、actual-gate Formal正负、fresh Ibex、py_compile全部通过；finish_time=2026-08-10T14:43:52+08:00。v1.0 planned-edit count blocker已由主 Agent独立复核并在v1.1更正为4，原始 blocker/RESOLVED 与恢复证据完整保留
resume_re_freeze: PASS；2026-08-10T14:38:00+08:00 恢复；主 Agent已用独立 internal mapping probe确认 pre-fix summary=12/2/10/0、`word_t`/`safe_t` 各2 ranges、总 planned edits=4，并以 apply_patch发布合同 v1.1；顶部状态由 READY→IN_PROGRESS；保留原始 blocker/resolution 证据；行为、允许路径、post-fix compact 与 pinned Ibex 10/19/79 oracle不变
inventory_contract: PASS；复用一次 `_physical_identifier_inventory()`：固定 byte regex `[A-Za-z_][A-Za-z0-9_$]*`，`ordered_source_files + included_files` 去重后按 file 排序读取 raw bytes，inventory 为 exact `(file,start,end)` sets；build中只读取一次并依次供 typedef与T081 enum firewall使用；owner quarantine 后、enum firewall前仅处理仍 eligible typedef；不补 occurrence、不猜 target/scope/package/owner，不改非 typedef或既有preserved/unsupported record
compact_oracle: PASS；fixture 10/522 bytes与冻结SHA-256一致；catalog/top overlay 0/0 + 0/0；graph ranges保持12/12/15/27；`word_t` raw比known多301..307，整record unsupported/reason exact，内部RewriteExecution中`symbol:typedefs:design.sv:59:65` edits精确为0；`safe_t`继续eligible/rename；mapping=12 total/1 rename/10 preserve/1 unsupported；2 actual edits；public strict=true，source-free restore 1 file byte-identical
no_go_and_non_vacuous: PASS；comments、string、unused macro中的额外同名token均保守quarantine；两个scope同名typedef不做name-only合并且两条均zero edit；complete `safe_t`保持identity/ranges并实际rename；构造的existing preserved/unsupported typedef support/reason/ranges逐项不变，非typedef records完全不变；T081 MODE_SAFE/MODE_GAP graph/action/reason/ranges及2/0 edit oracle完全不变；duplicate/overlap继续`SYMBOL_GRAPH_RANGE_CONFLICT`，nonphysical evidence只会被unsupported且不改range
ibex_replay: PASS；fresh root `/private/tmp/t085-ibex-replay.hVmcST`；stability `b99f5e43128964cc78a5c123a31f84e46df76934` 与Ibex `3250d99482f1963891ef1cf19356eeaeeaa71d30`前后clean；`abi__typedefs=PASS_EFFECTIVE`，45 files、3129 records、19 rename/2591 preserve/519 unsupported、79 modified tokens、10条reason=`typedef_lexical_coverage_incomplete`；`csr_num_e`/`ibex_mubi_t`/`prim_secded_type_e` action unsupported/reason exact/renamed_name null；`csr_op_e` action rename且renamed_name非null；strict/gate/decrypt通过，restore45 files byte-identical；formal-policy none，`FORMAL_NOT_RUN`未描述为等价证明
formal_verification: PASS；完整actual public gate正负证据见第14节
documentation: PASS；renaming table补充typedef raw lexical ranges与declaration+semantic ranges exact equality门槛；future work记录false-positive只减少加密、generic type-reference recovery未实现及`$bits`/qualified/cast/uninstantiated-module等未知缺口继续fail-closed；README/API/schema/category不变
boundaries: 不给`$bits`、qualified name、cast、uninstantiated module或其他缺口补semantic occurrence；不从raw token推断identity；不跳过comments/string/macro/disabled text；不整类disable typedef；owner quarantine原reason优先且T081 enum reason/counts逐项保持；不改policy/mapping/rewrite/restore/orchestration/CLI/Formal；未运行blanket discovery、历史driver或RISC-V-Vector Formal
review_request: READY_FOR_REVIEW；请主 Agent独立执行v1.1第13节五条验收并审查single-inventory、owner→typedef→enum ordering、eligible-only identity及zero-edit证据；子 Agent未stage/commit/push、未设置ACCEPTED、未创建T086
```

## 16. 主 Agent 验收

```text
review_date: 2026-08-10
reviewer: 主 Agent
allowed_files: PASS；最终 worktree精确为第11节七个允许路径；fixture仅为design.f/design.sv，10/522 bytes与冻结SHA-256完全匹配；无staged或允许列表外修改
implementation_review: PASS；只抽取一次raw physical identifier inventory；固定byte regex与去重排序physical files；owner quarantine后仅处理eligible typedef，再把同一inventory传给T081 enum firewall；set equality不成立时只replace support/reason，不补occurrence、不猜identity，不改policy/mapping/rewrite/CLI/Formal
target_and_regression: PASS；主Agent独立运行第13节第一条，exit0，Ran77 tests，OK
compact_oracle: PASS；graph=12/12/15/27不变；mapping=12 total/1 rename/10 preserve/1 unsupported；safe_t保持真实rename并产生2 edits；word_t为unsupported/reason exact且zero edit；public strict 0/0+0/0，source-free restore 1 file byte-identical
inventory_and_zero_edit: PASS；word_t raw ranges=59..65/265..271/301..307，known仅前两条；internal RewriteExecution中`symbol:typedefs:design.sv:59:65` exact 0 edits；comments/string/macro/双scope同名均只触发保守quarantine；existing support/reason/ranges、非typedef records与T081 enum oracle不变
ibex_replay: PASS；主Agent fresh root `/private/tmp/t085-main-ibex-replay.vi7sbU`；stability b99f5e43128964cc78a5c123a31f84e46df76934与Ibex 3250d99482f1963891ef1cf19356eeaeeaa71d30前后clean；abi__typedefs=PASS_EFFECTIVE，45 files、3129 records、19 rename/2591 preserve/519 unsupported、79 modified tokens、10条new reason；三个冻结unsafe record unsupported/null rename，csr_op_e继续rename；strict/gate/decrypt/45-file byte restore全通过
formal_positive: PASS；主Agent actual public renamed gate `/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t085-public-7gzxdvcp/encrypt/gate`；top=t085_top，seq=5，exit0，完整JSON `formal_equivalence=pass`；safe_t declaration/use实际改名，不是identity/copy-gold
formal_negative: PASS as expected negative；主Agent actual-gate copy `/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t085-formal-negative-7la3_00u/negative`；只把冻结宏外比较改为逻辑取反；public strict compile 0/0+0/0，Formal exit1，最终1个unproven，`equiv_status -assert`生效
external_formal: N/A; formal-policy none
py_compile: PASS；第13节命令exit0
diff_check: PASS；`git diff --check HEAD` exit0
ready_for_review_guard: PASS；精确guard在本次ACCEPTED状态变更前exit0
documentation: PASS；renaming table与future work准确记录exact completeness门槛、false-positive只减少加密、generic type-reference recovery未实现及owner/enum reason优先级
forbidden_runs: 未运行blanket discovery、历史acceptance driver或RISC-V-Vector Formal
decision: ACCEPTED；无法证明完整词法闭包的typedef在RewritePolicy前整条zero-edit，覆盖完整record继续实际改名，满足“宁可少加密、不能加密错误”
delivery_commit: current acceptance commit；exact hash在提交后报告并冻结进后继合同
push: NOT_RUN；此前授权只覆盖 b97b323..d3072b5，等待对本次新交付的明确授权
```
