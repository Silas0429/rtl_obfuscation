# T057：vNext 产品收敛与 RISC-V-Vector 发布验收

- 状态：ACCEPTED
- 合同版本：2.3
- 修订时间：2026-07-27
- 设计负责人：主 Agent
- 实现负责人：子 Agent
- 所属阶段：R5-B（最终阶段）
- 前置任务：T056 `ACCEPTED`
- 实现基线 HEAD：`cddc79192bdefb68243eef1e15e81a124f0814d1`
- 设计依据：`docs/three_mode_refactor_plan.md` 第 6–8 节
- 执行规范：`docs/refactor_subagent_protocol.md`
- Formal 依据：`docs/formal_verification.md`
- 验收类型：用户授权的单任务、串行多阶段发布收敛例外

## 1. 修订说明和单一交付目标

本合同替代 T057 版本 1。版本 1 把 discovery、SymbolGraph、Formal、legacy cleanup 和
RISC 发布验收放进一张任务，却没有给每个子阶段提供独立机器门，也没有冻结持久化 report
的完整校验关系。版本 1 的 `READY_FOR_REVIEW` 和 Formal 证据已撤回，不可用于
`ACCEPTED`。

### 1.1 版本 2 首次执行的撤回与恢复

版本 2 首次执行中，P0、P1 和 P2 的合同命令通过，但 P3 的唯一命令在
`encrypt-vnext` 阶段以 `CLI_VNEXT_ORCHESTRATION_INVALID` 失败。子 Agent 按停止条件设为
`BLOCKED`，该处置正确。

主 Agent 在不重跑 P3/Formal 的前提下完成只读诊断：

```text
SourceSet: 19 physical/closure files; PASS
Mapping: 1327 records; PASS
current mapping_range_digest:
  4d4e8bdf8b4fe18003937777cd4f4fcb9f7fb5d93947c2616425031eed5ca8b1
required mapping_range_digest:
  217cce2e28c5c81280653fd233ba87d2a70a4a284417a3492182da2520da46fd
current/required modified_tokens: 7178 / 7182
strict gate: CATALOG_SEMANTIC_FAILED
semantic diagnostics:
  rtl/vector/vex.sv: VECTOR_LANES in exec_data_i declared type dimension
  rtl/vector/vis.sv: VECTOR_LANES in data_to_exec declared type dimension
all six lost bound occurrences:
  rtl/vector/vector_top.sv: VECTOR_LANES at [8932,8944) and [11538,11550)
  rtl/vector/vex.sv: VECTOR_LANES at [1010,1022)
  rtl/vector/vis.sv: VECTOR_LANES at [1158,1170)
  rtl/shared/eb_buff_generic.sv: fifo_push at [2362,2371)
  rtl/shared/eb_buff_generic.sv: fifo_pop at [2515,2523)
```

版本 2 的 P1 规则删除了不安全的 owner/name 和通用 syntax-subtree 搜索，这是正确方向；但它
没有定义“由已知 semantic scope 解析固定 syntax token”的安全路径。更重要的是，P1 命令没有
强制校验冻结的 mapping digest、`modified_tokens=7182`、strict gate 和 restore identity，
导致 P1 出现假绿灯，直到 P3 才暴露。该验收缺口由主 Agent 负责。

因此：

1. 版本 2 的 P1 `PASS` 撤回；P2 实现保留，但其证据必须在 P1 修正后重跑；
2. `/private/tmp/rtl-obfuscation-t057-release-3` 作为失败现场保留，不删除、不复用；
3. 本次恢复从 P1 开始，不得直接重跑 P3；
4. 只有本合同新增的发布前 oracle/gate/restore 预检通过后，才授权在全新
   `/private/tmp/rtl-obfuscation-t057-release-4` 执行一次 P3；
5. 固定 oracle、产品范围和最终目标均未改变。

### 1.2 版本 2.1 P3 失败与版本 2.2 恢复

版本 2.1 的 P1 证据有效并保留：111 tests、固定 digest、1327/1301/26/0、
`modified_tokens=7182`、strict gate 和 19-file restore 均通过。P2 的 13 个既有测试通过，
但 P3 在 alignment Yosys validation 失败：

```text
failed work_dir: /private/tmp/rtl-obfuscation-t057-release-4
error: FORMAL_VNEXT_YOSYS_FAILED
first reported object: rtl/vector/vis.sv:173
reported syntax: renamed_base[21 +: 7][6:5]
Yosys: Single range expected
```

主 Agent 对失败现场做了不写文件、不运行 Formal equivalence 的诊断：

```text
actual gate strict compile: PASS
gold formal view build: PASS
gate formal view build: PASS
actual gate audit-range/lexer-token set: 7182 / 7182; exact equality
current physical-range alignment replacements: 6671
required identifier replacements: 6914
audit-linked lexer replacements over verified gate view: 6914
audit-linked lexer candidate manifest:
  7c93970509f6844c6fb7902de6ded6878e8fa6753578a5b862e6fc3c18deae9
required aligned view manifest:
  7c93970509f6844c6fb7902de6ded6878e8fa6753578a5b862e6fc3c18deae9
```

根因是当前 alignment 把 mapping range 与 formal transformation source range overlap 时一律
跳过，并假设 identifier 已被 transformation 消耗。该假设不成立：
`lower_packed_struct_member` 会把 base/selector identifier 从 gate source 复制进 replacement。
因此 243 个仍存在于 verified gate view 的审计内 identifier 没有恢复；declaration 已恢复而
replacement 内的 use 仍为 renamed name，最终导致 alignment view 语义不完整。

固定 `6914` 和 aligned manifest oracle 已精确指向正确结果，不授权修改。版本 2.1 的 P2
`PASS` 撤回；P1 不撤回、不重做。`release-4` 作为失败现场保留。版本 2.2 只允许修正 P2
alignment 和对应测试/执行记录，然后在 P2 的 RISC preflight 通过后，使用全新的
`/private/tmp/rtl-obfuscation-t057-release-5` 执行一次 P3。

### 1.3 版本 2.2 P4 失败与版本 2.3 恢复

版本 2.2 的 P2、P3 证据有效并保留：

```text
P2: 15 tests PASS
actual gate range/token set: 7182/7182 exact
formal alignment replacements: 6914
aligned manifest and Yosys warning digest: fixed oracle PASS
P3 release-5: PASS
RISC Formal positive: pass
RISC Formal negative: expected nonzero with unproven and equiv_status -assert
restore: 19 files byte-identical
```

P4 最终回归 192 tests 中唯一失败为
`EncryptDemoTests.test_default_fifo_vnext_demo_restores_byte_identically`。CLI 外层只报告
`CLI_VNEXT_ORCHESTRATION_INVALID`；主 Agent 独立展开内层错误并重建临时 gate 后确认：

```text
inner error:
  ORCHESTRATION_EXECUTION_INVALID
  -> REWRITE_GATE_COMPILE_FAILED
  -> CATALOG_SEMANTIC_FAILED
exact diagnostic:
  fifo_storage.sv:23
  logic [DATA_WIDTH:0] raw;
  UndeclaredIdentifier(DATA_WIDTH)
current DATA_WIDTH references:
  declaration and five occurrences renamed
missing occurrence:
  fifo_storage.sv [640,650), packed union member declared-type dimension
semantic binding:
  fifo_view_t TypeAliasType.parentScope.lookupName("DATA_WIDTH")
  -> exact fifo_storage module ParameterSymbol declaration
manual diagnostic edit:
  catalog parse/semantic = 0/0
  top-overlay parse/semantic = 0/0
```

因此失败不是 CLI/orchestration API 问题，也不授权修改它们。根因是 parameter collector 只为
Variable/Net/Port 的 declared dimensions 实现了 scope-resolved syntax path，没有覆盖
semantic `TypeAliasType` 的 packed struct/union member declared-type dimensions。

版本 2.3 只恢复 P4：

1. P1 v2.1、P2 v2.2、P3 release-5 证据全部保留；
2. 不运行新的 release driver 或 RISC Formal；
3. 只修正该通用 semantic collector 形状并加入独立 scope/shadowing 回归；
4. FIFO actual CLI、strict gate 和 restore 必须通过；
5. RISC fixed digest、7182 tokens、strict gate 和 restore 必须保持不变，否则设
   `BLOCKED`，不得修改 oracle或重跑 P3；
6. 通过完整 P4 后才可设 `READY_FOR_REVIEW`。

用户明确要求不再拆分任务。因此，本合同以一个最终交付目标保留 T057，但按以下顺序执行：

```text
P0 重新进入和范围确认
  -> P1 SourceSet / SymbolGraph 语义边界
  -> P2 orchestration report 审计 / Formal transaction
  -> P3 RISC-V-Vector 唯一发布证明
  -> P4 legacy cleanup、文档和最终回归
  -> READY_FOR_REVIEW
```

每个阶段最多四条验收命令。前一阶段未通过时不得进入后一阶段；不得把后阶段的成功当作前阶段
边界的替代证据。这里对统一规范“每张任务只选一行验收”的偏离仅限用户授权的 T057 发布收敛，
不改变后续项目规则。

最终目标是：

1. 当前唯一 vNext 产品流水线可对固定 `RISC-V-Vector/vector_top` 完成真实 project-root
   加密、strict gate、跨进程恢复和 Yosys 正负等价证明；
2. 通用 Formal vNext engine 不含 RISC 场景常量，且只消费经完整审计的 actual gate、
   gate formal view 和持久化 orchestration report；
3. residual T029 legacy stack 被有 replacement coverage 地删除；
4. T057 `ACCEPTED` 即表示 R0–R5 本轮交付完成，不创建 T058。

## 2. P0：重新进入和工作区边界

### 2.1 当前事实

版本 1 子 Agent 已在基线 `cddc791...` 上留下 T057 范围内的未提交实现、测试、删除和文档
修改。主 Agent 已审计：

```text
head: cddc79192bdefb68243eef1e15e81a124f0814d1
branch: main...origin/main [ahead 1]
scope: existing changes are confined to the version-1 T057 allowed list
git staging/commit/push: none
```

这些已有修改不得 reset、checkout、stash 或删除后重做。子 Agent从现状继续修正。

### 2.2 重新开始步骤

子 Agent编辑任何文件前必须：

1. 完整阅读 `AGENTS.md`、本合同、`docs/refactor_subagent_protocol.md`、
   `docs/three_mode_refactor_plan.md` 第 6–8 节和 `docs/formal_verification.md`；
2. 确认本合同精确状态为 `READY`，记录当前 HEAD 和 `git status --short --branch`；
3. 将本合同状态改为 `IN_PROGRESS`；
4. 在执行记录填写 `P0_scope_audit`，确认没有允许列表外的新变化；
5. 不重复版本 1 的 RISC Formal；先完成 P1、P2 compact gates。

P0 通过条件：

```text
starting_head == cddc79192bdefb68243eef1e15e81a124f0814d1
no staged changes
no fixture / RISC RTL / formal_equivalence.py changes
exactly one active task == T057
```

任一条件不满足时先记录实际状态并停止，不得自行清理工作区。

### 2.3 版本 2.1 恢复步骤

版本 2.1 子 Agent 必须：

1. 确认本合同精确状态为 `READY`，完整阅读第 1.1、4、10、11、12 节；
2. 确认 HEAD 仍为合同基线、无 staged change、已有变化仍在允许列表内；
3. 确认 `/private/tmp/rtl-obfuscation-t057-release-3` 保留且
   `/private/tmp/rtl-obfuscation-t057-release-4` 不存在；
4. 将状态改为 `IN_PROGRESS`，在执行记录追加 `version_2_1_recovery`，不得覆盖版本 2
   的失败记录；
5. 只从 P1 开始修正和验收。P1 通过后重跑 P2；P1/P2 均通过后才可进入 P3。

### 2.4 版本 2.2 恢复步骤

版本 2.2 子 Agent 必须：

1. 确认本合同精确状态为 `READY`，完整阅读第 1.2、5、6、9–12 节；
2. 确认 HEAD/branch/unstaged scope 不变，`release-3`、`release-4` 均保留，
   `release-5` 不存在；
3. 将状态改为 `IN_PROGRESS` 并追加版本 2.2 记录，不覆盖 P1/P2/P3 历史；
4. 接受 P1 v2.1 证据，不重跑 P1；
5. 只修改第 9 节版本 2.2 新修改允许列表，先完成全部 P2 tests 和 RISC alignment
   preflight；
6. P2 完整通过后才运行一次 release-5 P3；失败仍按合同保留现场并停止。

### 2.5 版本 2.3 恢复步骤

版本 2.3 子 Agent 必须：

1. 确认本合同精确状态为 `READY`，完整阅读第 1.3、4.3、4.4、7、9–12 节；
2. 确认 HEAD/branch/unstaged scope 不变，release-3/4/5 均保留，无 staged change；
3. 将状态改为 `IN_PROGRESS` 并追加版本 2.3 记录，不覆盖历史；
4. 不重跑 P1/P2/P3 acceptance，不调用 release driver 或
   `scripts/formal_equivalence.py`；
5. 只在版本 2.3 新修改允许列表内修正 collector 和测试；
6. 执行完整 P4 四条命令。第一条失败时记录首个失败并停止后续命令。

## 3. 固定 RISC 输入和发布 oracle

```text
project_root: rtl_samples/RISC-V-Vector
top: vector_top
defines: none
include_dirs: none
encryption_rate: none
name_length: 20
categories: CANONICAL_CATEGORIES（19 类全部）
abi_categories: MODULE_ABI_CATEGORIES（11 类全部）
input_manifest_sha256: a016dd548525346508c636b97fcc452c8f6eb4fcbf930ef5eb938a2edfa2ae9d
reachable_modules: 17
physical/closure files: 19
```

固定 compile order：

```text
rtl/shared/and_or_mux.sv
rtl/shared/eb_one_slot.sv
rtl/shared/eb_buff_generic.sv
rtl/shared/fifo_duth.sv
rtl/vector/v_fp_alu.sv
rtl/vector/vmacros.sv
rtl/vector/v_int_alu.sv
rtl/vector/vex_pipe.sv
rtl/vector/vrat.sv
rtl/vector/vrf.sv
rtl/vector/vstructs.sv
rtl/vector/vex.sv
rtl/vector/vis.sv
rtl/vector/vmu_ld_eng.sv
rtl/vector/vmu_st_eng.sv
rtl/vector/vmu_tp_eng.sv
rtl/vector/vmu.sv
rtl/vector/vrrm.sv
rtl/vector/vector_top.sv
```

固定 normalized oracle：

```text
source_set_digest:
  b359a1340ba461ce941ab68c6dcd34f33b365935e239af4e606710204f477fc7
mapping_range_digest:
  217cce2e28c5c81280653fd233ba87d2a70a4a284417a3492182da2520da46fd
mapping total/rename/preserve/unsupported:
  1327 / 1301 / 26 / 0
modified_tokens:
  7182
formal transformations:
  total=260
  lower_packed_aggregate_type=25
  lower_packed_struct_member=233
  remove_concurrent_assertion=2
formal signature digest:
  63a9ef753fdb55f735359b4e65ec8e5c6d61a9b0626ceec21486d9786ac0a925
normalized Yosys warning digest:
  82364328ba2442aea6429d2a1ec8ab406784f0fcfb4d9d3b681589de8e5a6b8f
alignment identifier replacements:
  6914
aligned view manifest:
  7c93970509f6844c6fb7902de6ded6878e8fae6753578a5b862e6fc3c18deae9
```

19 类 action oracle（每项为 `rename/preserve/unsupported`）：

```text
arguments=0/0/0
enum_values=33/0/0
functions=0/0/0
generate_blocks=8/0/0
genvars=7/0/0
instances=19/0/0
interface_instances=0/0/0
interface_ports=0/0/0
interfaces=0/0/0
modports=0/0/0
modules=16/1/0
parameters=120/14/0
ports=348/11/0
signals=675/0/0
struct_fields=66/0/0
struct_types=7/0/0
tasks=0/0/0
typedefs=2/0/0
union_fields=0/0/0
```

这些 oracle 来自两个 normalized run 和一个 clean literal run。版本 2 不授权修改 oracle。
若 P1 合规实现不能保持它们，记录第一个不同的 `symbol_id/category/file/range` 并设
`BLOCKED`，由主 Agent决定是否需要重新设计；不得自行“更新期望值”。

## 4. P1：SourceSet / SymbolGraph 语义边界

### 4.1 `.sv` include provider

- project-root discovery 允许 closure candidate 中 `.sv` 和 `.svh` 作为 include provider；
- `.sv` provider 仍是唯一 compile order 中的 source unit，不复制内容、不改后缀；
- `.svh` 是 included physical file，不作为独立 source unit；
- physical manifest 去重，filelist 顺序和既有 `.svh` 行为不变；
- 产品代码不得按 RISC 路径、文件名、top 或固定数量分支。

### 4.2 owner、anonymous generate 与 source identity

- explicit generate label 继续产生 `generate_blocks` record；
- 自动生成的 `genblkN` 没有 source token，不产生 declaration 或 rename record；
- anonymous generate 只以同一 physical file 内的有效 syntax span 注册 owner；
- owner key 只由稳定 source identity 构成，不得使用 Python object identity；
- `UninstantiatedDefSymbol` placeholder 本身不进入 graph，但其余 byte-backed、实际
  elaborated source symbols仍按正常 owner/range 规则处理；
- 重复 elaboration 只有在
  `(category, name, owner, declaration, occurrence range)` 全部相同时才幂等；
- 不同 category、owner 或 symbol 的 exact/partial overlap 必须
  `SYMBOL_GRAPH_RANGE_CONFLICT`。

### 4.3 direct syntax evidence、semantic sourceRange 与 scope-resolved syntax

“direct syntax evidence”定义为：在已绑定 semantic target 后，通过该 syntax kind 的固定字段
路径得到的唯一 identifier token。不得通过通用 `syntax.visit()`、文件扫描或按 owner/name
猜测 target 来制造 direct token。

若 direct token 不存在，只允许：

```text
A. bound semantic target
     -> semantic sourceRange
     -> exact physical byte/range audit

或

B. known semantic owner/scope
     -> owner 对应 typed syntax 的固定字段或有界结构
     -> exact identifier token
     -> owner scope.lookupName(token.rawText) 语义解析
     -> exact source-backed semantic target
     -> target declaration identity 精确映射一个既有 graph record
     -> occurrence physical byte/range audit
```

A、B 的共同约束：

- token/range 的 start/end 在同一 buffer，且均为 non-macro location；
- relative file 属于 SourceSet physical files；
- `0 <= start < end <= len(source)`；
- `source[start:end] == bound_name.encode("utf-8")`；
- semantic kind 必须与 record category 相容；
- target declaration source identity、owner/scope 和 category 必须唯一；
- 最终仍执行统一的 declaration/occurrence 去重和 overlap fail-closed。

B 只用于 PySlang 没有把 reference 直接暴露为 expression semantic target/sourceRange 的结构，
例如 port declared-type dimension 或 generate block 内的 bound expression。允许遍历的最大边界
必须是一个已知 semantic owner 自己的 typed syntax；每个候选 identifier 必须先由该 owner 的
适用 lexical `Scope.lookupName` 解析（例如 port 使用其 `parentScope`，generate block 使用该
block scope），解析失败、歧义、scope 不同或没有 exact declaration identity 时必须
fail-closed。不得先按名称查 graph record，再把 record 当作 semantic target。

不允许：

- 在文件、任意 syntax subtree 或未知 owner 中搜索同名 token；
- 仅因 raw text 与某 record 同名就建立 occurrence；
- 仅以 owner + name 绑定一个没有 semantic target 的 reference；
- 捕获 fallback 错误后跳过 reference；
- 为 RISC 特例增加 category collector。

若 PySlang 对必需引用既不提供 direct semantic evidence、exact semantic `sourceRange`，也
不能经已知 owner scope 唯一解析，该对象是 P1 停止条件，必须记录实际 node kind、owner、
lookup result、target、file/range 和错误码。

### 4.4 declaration、genvar 与 signal

- declaration range 不得再次成为 occurrence；
- genvar declaration/reference 只属于 `genvars`，不得进入 `signals`；
- 排除基于 semantic kind 和 declaration source identity，不按名称；
- T042 parameter/genvar、repeated-instance、macro 和 range-conflict 回归保持 fail-closed。

### 4.4.1 packed aggregate member declared dimensions

对 semantic `TypeAliasType` 的 packed struct/union member declared-type dimensions，允许使用
第 4.3 节 B 路径补充 parameter occurrence，但必须满足：

```text
known semantic owner: TypeAliasType
bounded syntax:
  canonicalType.syntax
  -> StructUnionTypeSyntax.members
  -> StructUnionMemberSyntax.type
  -> declared VariableDimensionSyntax
  -> dimension expression identifier token
lexical scope:
  TypeAliasType.parentScope.lookupName(token.rawText)
target:
  exact module ParameterSymbol
  -> exact declaration source identity
  -> exactly one existing _ParameterRecord
occurrence:
  exact non-macro physical bytes
  provenance=declaration_dimension
```

允许在上述单个 dimension expression 的有界 syntax 内枚举 identifier；每个 token 必须先经
lexical scope 解析。禁止扫描整个 alias、文件或 graph，禁止 owner/name record fallback。
解析到 global/package parameter、非 ParameterSymbol、没有现有 module parameter record 或
不属于 SourceSet 的对象时不创建 occurrence；不得因此新增 category/record。相同 physical
range 继续幂等，不同 source identity overlap 继续 fail-closed。

### 4.5 P1 必需测试行为

`tests.test_risc_v_vector_project_root.AuthorizedRiscBoundaryTests` 至少包含以下独立方法：

```text
test_project_root_accepts_sv_include_provider_in_compile_order
test_uninstantiated_and_anonymous_generate_ranges_are_source_backed
test_semantic_fallback_uses_bound_exact_source_range_without_name_search
test_semantic_scope_lookup_recovers_only_bound_omitted_references
test_repeated_elaboration_is_deterministic_and_has_unique_physical_ranges
test_distinct_source_identity_overlap_remains_fail_closed
test_genvar_ranges_are_not_collected_as_signals
test_risc_mapping_oracle_strict_gate_and_restore_preflight
```

其中 fallback 测试必须定位一个真实“无 direct identifier、有 exact semantic sourceRange”的
PySlang expression，并证明调用路径不使用通用 syntax-subtree 名称搜索。所有 declaration 和
occurrence 均逐项核对 physical bytes。

scope lookup 测试必须至少证明：

- `vector_top.sv` 的两个 `VECTOR_LANES` occurrence 都解析到 top boundary preserve 的 exact
  parameter declaration，进入 range oracle 但不进入 rewrite edit；
- `vex.sv` 的 `exec_data_i` declared-type dimension 和 `vis.sv` 的 `data_to_exec`
  declared-type dimension 中，`VECTOR_LANES` 都解析到各自可见的 exact
  `ParameterSymbol` declaration；
- `eb_buff_generic.sv` 的 `gen_fifo` scope 中，`fifo_push`、`fifo_pop` 分别解析到 exact
  `VariableSymbol` declaration；
- 使用错误 owner scope、同名但不同 declaration identity 或无法解析的 token 时
  fail-closed，不回退到 graph owner/name 搜索；
- 上述四个恢复的 occurrence physical range 均唯一，且 declaration 不被重复计为 occurrence。

发布前预检测试必须使用临时目录和真实 RISC 输入，且不运行 Yosys Formal。它必须同时断言：

```text
source_set_digest == 第 3 节固定值
mapping_range_digest == 第 3 节固定值
mapping total/rename/preserve/unsupported == 1327/1301/26/0
modified_tokens == 7182
strict gate semantic compile == PASS
restore physical files == 19 and byte-identical
```

任何一项失败都属于 P1 失败，不得进入 P2/P3。测试不得调用发布驱动、不得写入 release-3 或
release-4、不得放宽 strict compile。

P1 不产生新的独立发布 gate；Formal 为 `N/A`。只有 P1 命令全部通过后才能进入 P2。

## 5. P2：持久化 report 审计与通用 Formal transaction

### 5.1 唯一 report 审计入口

为避免 `formal_vnext.py` 再实现一套 Mapping/SymbolGraph hydration，本阶段授权在
`restore_vnext.py` 增加以下程序化 API；允许名称做不改变数据流的轻微调整，但字段语义不可变：

```text
OrchestrationGateAuditVNext(
    schema_version: 1,
    source_set: SourceSet,                  # source_root 投影为已验证 gate_dir
    effective_records: tuple[MappingRecord, ...],
    input_manifest: tuple[InputFileDigest, ...],
    gate_manifest: tuple[InputFileDigest, ...],
)

audit_orchestration_gate_vnext(
    report_file: Path,
    *,
    gate_dir: Path,
) -> OrchestrationGateAuditVNext
```

该 API：

- 不写用户输出，不接 CLI；
- 不读取 external original source root、gold Formal view 或 RISC 常量；
- 失败使用既有 `RESTORE_VNEXT_*` 稳定错误族；
- 所有临时文件在成功和失败后均清理；
- 与 `load_restore_vnext()` 共用同一个内部 hydration/manifest/metrics validator；
- 不建立第二套 SymbolGraph、mapping graph 或 category policy。

### 5.2 report 精确关系

审计必须依次验证：

1. orchestration outer object exact keys：
   `format/schema_version/state/source_set/mapping/mapping_execution/metrics/rate_metrics/summary`；
2. outer format=`rtl-obfuscation.orchestration-vnext`、schema=1、state=`restored`；
3. SourceSet exact keys、origin、top、defines、portable paths、physical file 去重、
   compile/top-closure order 和 `design.f` 内容；
4. outer `mapping` 是 original mapping；
5. `mapping_execution.mapping` 是 effective mapping；
6. 下列 input manifest 内容和顺序完全相等：

   ```text
   outer mapping.input_manifest
   effective mapping.input_manifest
   mapping_execution.input_manifest
   mapping_execution.restored_manifest
   per_file_mapping[*].input_sha256
   ```

7. `mapping_execution.gate_manifest` 与
   `per_file_mapping[*].gate_sha256` 相等，并与 actual gate 每个 physical file 的 SHA-256
   相等；actual gate file set 必须恰为 physical files 加 `design.f`；
8. no-rate report：original mapping 与 effective mapping canonical report byte-for-byte 相等；
9. rate report：只允许 original rename 变为同名同 range 的 effective rename，或
   `preserve/reason=rate_unselected/renamed_name=null`；其余 record 不变，并复用现有
   rate selection equations；
10. mapping record exact shape、action/reason、declaration/occurrences、owner、impact、ABI、
    summary 和 range audit 都通过 canonical projection；
11. effective rename 的 `renamed_name` 必须是合法 plain SystemVerilog identifier、全局唯一、
    非保留字，并与全部 original names 不冲突；
12. `per_file_mapping` 必须一对一覆盖 effective records 的全部 physical ranges；
    rename range 有唯一 canonical `gate_range`，preserve/unsupported 不产生替换；
13. orchestration summary、metrics 和 nested rate metrics 与 actual gate 审计一致。

### 5.3 不读取 gold 的重建校验

为了验证 input manifest，审计入口必须使用以下固定数据流：

1. 先完成 report 的 portable schema、effective record、per-file range 和 actual gate
   manifest 结构校验；
2. 对每个文件按 `gate_range.start` 降序检查 actual gate bytes 必须等于
   `renamed_name.encode()`，并替换为 `original_name.encode()`；
3. range 必须有效、互不 overlap，且恰好覆盖所有 effective rename declaration/occurrence；
4. 临时重建文件的 SHA-256 必须等于 input manifest；
5. 以临时重建 root 调用与 `load_restore_vnext()` 共享的完整 hydration，重建
   SourceCatalog/SymbolGraph/policy，验证 original/effective mapping、metrics 和 restore；
6. 只把 gate-root SourceSet 投影、effective records 和 manifests 返回给 Formal；
7. 删除临时重建 root。

不得直接信任 report 中的 original name、range、manifest 或 summary；不得把临时重建文件当作
Formal gold 输出。

### 5.4 Formal vNext 数据流

`formal_vnext.py` 只提供：

```text
build_formal_view_vnext(source_set, *, output_dir, manifest_path) -> dict
align_formal_view_vnext(
    *,
    gate_dir,
    gate_view_dir,
    gate_view_manifest_path,
    orchestration_report_path,
    output_dir,
    manifest_path,
) -> dict
```

`align_formal_view_vnext` 必须首先调用 P2 唯一审计入口；任何 `RestoreVNextError` 统一转为
`FORMAL_VNEXT_INPUT_INVALID`，不发布输出。

Formal view chain 必须满足：

- view report exact format/schema/state 和 exact keys；
- view report SourceSet compile order、physical files、include dirs、defines、top 与 audit 相等；
- `source_manifest_sha256` 等于 actual gate aggregate manifest；
- `view_manifest_sha256` 等于 actual gate-view physical bytes；
- `design.f` 与 compile order byte-identical；
- actual gate-view file set 恰为 physical files 加 `design.f`；
- transformations 由 gate semantic view 重新计算，完整 normalized records 相等；
- alignment 的 rename dictionary 只来自 audit effective records 中 `action=rename` 且
  全局唯一的 `renamed_name -> original_name`；
- 先以 PySlang lexer 扫描 actual gate：命中 rename dictionary 的 identifier token
  physical ranges 必须与 audit canonical `gate_range` 集合逐项相等，不得有额外 token、
  缺失 range 或 text replacement；
- 再以 PySlang lexer 扫描已通过完整 transformation-chain 校验的 actual gate view；
  只替换 token kind=`Identifier` 且 raw text 在上述 audit dictionary 中的 token；
- identifier 即使位于 formal transformation replacement 内也必须替换；不得因它的原 gate
  range 与 transformation source range overlap 而跳过；
- comment、string、macro text、未在 audit dictionary 的同名/近似文本不得替换；
- lexer diagnostic、token bytes、重复/overlap edit 或 gate-range/token-set 不一致时
  fail-closed；
- replacement 数量和 aligned manifest 从 actual verified gate view 计算；
- 通用模块不得出现 RISC path/top/count/digest 常量，也不得读取 gold。

alignment 不得重新实现 mapping hydration，不得按 original owner/name 猜 target，也不得读取
external original source 或 gold view。audit 已证明 dictionary、gate ranges、gate bytes 和
restore chain；gate view 又由同一 actual gate 的 deterministic formal transformations 重新
计算并逐文件核对。因此上述 lexer pass 是 audit lineage 在 transformed view 上的投影，不是
未审计的全局文本替换。

### 5.5 路径和原子发布

定义 `overlap(a, b)` 为 `a == b`、`a` 位于 `b` 内或 `b` 位于 `a` 内。以下输出对全部输入都不得
overlap：

```text
inputs:
  gate_dir
  gate_view_dir
  gate_view_manifest_path
  orchestration_report_path
outputs:
  output_dir
  manifest_path
```

`output_dir`、`manifest_path` 彼此也不得 overlap；必须 absent 且 parent 已存在。build API
同样保护 source root。schema/tamper/path/lexer/Yosys/publish 任一失败时：

```text
input bytes unchanged
output_dir absent
manifest_path absent
temporary files absent
stable FormalVNextError code
```

### 5.6 P2 固定黑盒矩阵

`tests.test_risc_v_vector_project_root.FormalVNextTransactionTests` 必须包含：

```text
test_formal_build_and_align_are_byte_deterministic
test_formal_alignment_accepts_valid_no_rate_and_rate_reports
test_formal_alignment_rejects_report_chain_tamper
test_formal_alignment_rejects_gate_view_tamper
test_formal_alignment_rejects_all_input_output_overlaps
test_formal_failure_leaves_no_partial_output_or_input_change
test_formal_alignment_restores_identifiers_copied_into_transformation_replacements
test_risc_alignment_preflight_matches_frozen_oracles_without_equivalence
test_release_oracle_helpers_are_portable_and_canonical
```

`test_formal_alignment_restores_identifiers_copied_into_transformation_replacements` 必须使用测试内
临时 SystemVerilog source 构造至少一个 packed-struct member base 后接 bit/range selector 的
真实语义表达式。它必须证明：

```text
gate view 的 transformation replacement 内仍含 renamed base identifier
alignment 后该 identifier 恢复为 audit dictionary 对应 original identifier
不再使用 physical source-range overlap == skip
unaligned/tampered dictionary 或额外 renamed token fail-closed
aligned view 通过 Yosys validation
```

`test_risc_alignment_preflight_matches_frozen_oracles_without_equivalence` 必须使用 fresh temporary
directory 运行真实 RISC project-root 的 encrypt、gate Formal build 和 alignment，但不得调用
`scripts/risc_v_vector_acceptance.py` 或 `scripts/formal_equivalence.py`。它必须断言：

```text
gate token ranges == 7182 audited effective rename ranges
gate-view identifier replacements == 6914
aligned view manifest ==
  7c93970509f6844c6fb7902de6ded6878e8fa6753578a5b862e6fc3c18deae9
gold/gate/aligned normalized Yosys warning digest ==
  82364328ba2442aea6429d2a1ec8ab406784f0fcfb4d9d3b681589de8e5a6b8f
aligned Yosys validation == PASS
temporary output cleanup == PASS
```

该 preflight 通过前不得进入 P3。不能 mock lexer、audit、formal transformation 或 Yosys。

`test_formal_alignment_rejects_report_chain_tamper` 必须用独立 fresh run 逐项修改：

```text
outer schema_version -> 2
source_set.compile_order[0] -> "../escape.sv"
mapping_execution.gate_manifest[0].sha256 -> "0" * 64
mapping_execution.input_manifest[0].sha256 -> "0" * 64
第二个 effective rename.renamed_name -> 第一个 effective rename.renamed_name
no-rate outer mapping 的首个 rename.renamed_name -> 另一个合法 identifier
```

每个 case 都必须得到 `FORMAL_VNEXT_INPUT_INVALID`，且无输出。

gate-view tamper 至少覆盖：

```text
gate-view/design.f append newline
gate-view manifest view_manifest_sha256 -> "0" * 64
一个 transformed physical file 改一个 byte
```

path matrix 至少覆盖：

```text
output_dir = gate_view_dir / "aligned-inside-input"
output_dir = gate_dir / "aligned-inside-input"
manifest_path = gate_view_dir / "aligned.json"
manifest_path = gate_dir / "aligned.json"
manifest_path = output_dir
```

不得只给测试起包含 “path_conflict” 的名字而不执行上述调用。

## 6. P3：RISC-V-Vector 权威发布证明

### 6.1 发布驱动

`scripts/risc_v_vector_acceptance.py` 唯一参数：

```text
--work-dir <absent-directory>
```

驱动必须：

1. 子进程调用 actual `encrypt-vnext`，使用第 3 节固定输入；
2. 校验固定 SourceSet、module、input manifest、mapping/range/category/metrics oracle；
3. 独立 `decrypt-vnext` 进程恢复，19 个 physical files byte-identical；
4. 对 original source root 和 actual gate 分别调用通用 Formal build；
5. alignment 只传 actual gate、gate view 和 orchestration report；
6. 由 P2 审计 report；不绕过或 mock 审计入口；
7. 比较 gold/gate transformation signature、Yosys warnings 和重复运行 determinism；
8. 运行 `scripts/formal_equivalence.py`：

   ```text
   gold: <work-dir>/formal-gold/design.f
   gate: <work-dir>/formal-aligned/design.f
   top: vector_top
   seq: 1
   ```

9. 正例退出 0，JSON `formal_equivalence=pass`；
10. 从 actual aligned gate 复制负例，仅将
    `rtl/vector/vector_top.sv` 中 `assign vector_idle_o = ...` 表达式内一个 ASCII `&`
    改为 `|`，长度不变且恰好一个 byte 不同；
11. 负例先通过相同 strict view check，再运行相同 Formal，必须非零并同时包含
    `unproven` 和 `equiv_status -assert`；
12. 输出一行 canonical JSON：

   ```text
   format=rtl-obfuscation.risc-v-vector-vnext-acceptance
   schema_version=1
   status=pass
   exact top-level keys:
     format, schema_version, status, input, mapping, metrics, restore,
     formal_view, formal_alignment, formal_positive, formal_negative
   ```

### 6.2 P3 运行次数

版本 1 的成功 Formal 因 report 信任链不完整而撤销。版本 2 和 2.1 的失败目录必须保留；
两次失败都未运行 RISC Formal equivalence。版本 2.2 只授权一次通过完整 P2 preflight 后的
权威 RISC 正负 Formal：

```text
failed historical work_dir: /private/tmp/rtl-obfuscation-t057-release-3
failed historical work_dir: /private/tmp/rtl-obfuscation-t057-release-4
authorized recovery work_dir: /private/tmp/rtl-obfuscation-t057-release-5
freeze check at contract creation: ABSENT
```

只有 P1、P2 全部通过后才能运行。若该目录届时已存在，或 P3 命令失败，不得删除目录后重跑；
记录首个失败并设 `BLOCKED`，等待主 Agent决定。

## 7. P4：legacy cleanup、文档和最终回归

只有 P3 `status=pass` 后才能完成本阶段。

### 7.1 版本 2.3 collector 回归

`tests.test_symbol_graph_parameters.SymbolGraphParameterTests` 必须新增：

```text
test_packed_aggregate_member_dimension_uses_alias_lexical_scope
```

该测试使用测试内 temporary SystemVerilog source，至少构造两个 module：

- 两个 module 都声明同名 `WIDTH` parameter；
- 每个 module 各自声明 packed struct 或 union；
- aggregate member declared dimension 引用各自 lexical `WIDTH`；
- 选定 top closure 同时包含两个 module。

必须逐项证明：

```text
两个 WIDTH token 分别绑定各自 ParameterSymbol declaration
每个 token provenance == declaration_dimension
physical bytes/range 精确，declaration 不重复为 occurrence
两个同名 parameter 不通过 owner/name 猜测串绑
graph range audit PASS
```

冻结黑盒
`EncryptDemoTests.test_default_fifo_vnext_demo_restores_byte_identically` 必须使用 unchanged
`encrypt.py` 和 unchanged FIFO sample 通过，并证明 4 files、strict gate、restore
byte-identical。现有
`AuthorizedRiscBoundaryTests.test_risc_mapping_oracle_strict_gate_and_restore_preflight`
必须同时通过，证明版本 2.3 没有改变 RISC mapping oracle。

必须删除且不得保留 shim/re-export/fallback：

```text
rtl_obfuscator/inventory.py
rtl_obfuscator/category_profile.py
rtl_obfuscator/project.py
rtl_obfuscator/formal_view.py
scripts/t029_acceptance.py
```

replacement coverage：

| 删除对象 | replacement coverage |
| --- | --- |
| `inventory.py` | SourceCatalog/SymbolGraph category、owner、range tests |
| `category_profile.py` | canonical category registry、rewrite policy、19 类 release oracle |
| `project.py` | SourceSet project-root/filelist equivalence 和唯一 discovery identity |
| `formal_view.py` | P2 generic Formal transaction tests |
| `scripts/t029_acceptance.py` | P3 RISC vNext release driver |

当前 `README.md`、`docs/formal_verification.md`、`docs/future_work.md` 和
`docs/three_mode_refactor_plan.md` 只能描述 vNext 产品和 T057 发布流程。历史任务文档可保留
历史命令，但产品 import surface 和 parser 不得恢复：

```text
inspect-project
encrypt-project
decrypt-project
formal-view
formal-align
mapping v1/v2/v3/v4 writers
```

## 8. 允许修改的文件

### 8.1 产品和服务

```text
rtl_obfuscator/project_discovery.py
rtl_obfuscator/source_set.py
rtl_obfuscator/source_catalog.py
rtl_obfuscator/symbol_graph.py
rtl_obfuscator/formal_vnext.py                 # 新增
rtl_obfuscator/restore_vnext.py                # P2 共享审计入口
rtl_obfuscator/inventory.py                    # 删除
rtl_obfuscator/category_profile.py             # 删除
rtl_obfuscator/project.py                      # 删除
rtl_obfuscator/formal_view.py                  # 删除
scripts/risc_v_vector_acceptance.py            # 新增
scripts/t029_acceptance.py                     # 删除
```

### 8.2 测试

```text
tests/test_source_set.py
tests/test_source_catalog.py
tests/test_symbol_graph_signals.py
tests/test_symbol_graph_genvars.py
tests/test_symbol_graph_parameters.py
tests/test_rewrite_policy.py
tests/test_mapping_vnext.py
tests/test_rewrite_vnext.py
tests/test_restore_vnext.py
tests/test_vnext_product_surface.py
tests/test_risc_v_vector_project_root.py
```

### 8.3 文档

```text
README.md
docs/formal_verification.md
docs/future_work.md
docs/three_mode_refactor_plan.md
docs/tasks/T057_risc_v_vector_release_acceptance.md
```

## 9. 禁止修改和明确不包含

禁止修改：

```text
rtl_samples/RISC-V-Vector/**
tests/fixtures/**
scripts/formal_equivalence.py
rtl_obfuscator/rewrite.py
rtl_obfuscator/rewrite_vnext.py
rtl_obfuscator/orchestration_vnext.py
rtl_obfuscator/mapping_vnext.py
rtl_obfuscator/rewrite_policy.py
rtl_obfuscator/metrics_vnext.py
rtl_obfuscator/rate*.py
rtl_obfuscator/systemverilog_names.py
encrypt.py
历史任务合同
```

明确不包含：

- 新 category、mapping schema、CLI operation、rate 模式或兼容层；
- RISC RTL/SVA/simulator/generated decoder 修改；
- 第二套 report parser、SymbolGraph、restore 或 Formal identity path；
- fixture/module/path/count 驱动的产品分支；
- 忽略 diagnostic、删除 `equiv_status -assert`、复制 gold 或降低证明强度；
- blanket unittest discovery、性能优化、缓存、新依赖或 T058。

需要允许列表外修改时，记录第一个具体原因并设 `BLOCKED`。

版本 2.2 恢复阶段的新修改只允许：

```text
rtl_obfuscator/formal_vnext.py
tests/test_risc_v_vector_project_root.py
docs/tasks/T057_risc_v_vector_release_acceptance.md
```

此前 T057 允许列表内的已有修改继续保留。若修正必须改动 `restore_vnext.py`、发布驱动、oracle
或其他文件，先记录具体缺口并设 `BLOCKED`，不得自行扩围。

版本 2.3 恢复阶段的新修改只允许：

```text
rtl_obfuscator/symbol_graph.py
tests/test_symbol_graph_parameters.py
docs/tasks/T057_risc_v_vector_release_acceptance.md
```

不得修改 `encrypt.py`、`rtl_obfuscator/rewrite.py`、
`rtl_obfuscator/orchestration_vnext.py`、FIFO/RISC RTL、fixture、P2 Formal 实现、release
driver 或 oracle。`tests/test_encrypt_demo.py` 是冻结黑盒验收，不得为了通过而改写。

## 10. 分阶段验收命令

所有 Python、PySlang、Yosys 和测试命令必须通过 Conda 环境
`rtl_obfuscation`。不得合并阶段或跳过命令。

### 10.1 P1 命令

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_source_set tests.test_source_catalog tests.test_symbol_graph_signals tests.test_symbol_graph_genvars tests.test_symbol_graph_parameters tests.test_rewrite_policy tests.test_mapping_vnext tests.test_rewrite_vnext tests.test_risc_v_vector_project_root.AuthorizedRiscBoundaryTests -v

conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/project_discovery.py rtl_obfuscator/source_set.py rtl_obfuscator/source_catalog.py rtl_obfuscator/symbol_graph.py tests/test_source_set.py tests/test_source_catalog.py tests/test_symbol_graph_signals.py tests/test_symbol_graph_genvars.py tests/test_symbol_graph_parameters.py tests/test_risc_v_vector_project_root.py

git diff --check HEAD
```

### 10.2 P2 命令

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_restore_vnext tests.test_risc_v_vector_project_root.FormalVNextTransactionTests -v

conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/restore_vnext.py rtl_obfuscator/formal_vnext.py tests/test_restore_vnext.py tests/test_risc_v_vector_project_root.py

git diff --check HEAD
```

### 10.3 P3 唯一命令

```sh
conda run -n rtl_obfuscation python scripts/risc_v_vector_acceptance.py --work-dir /private/tmp/rtl-obfuscation-t057-release-5
```

允许最多 1200 秒。stdout 最后一条非空内容必须是第 6.1 节 canonical JSON，exit 0。
该命令已在版本 2.2 成功执行；对版本 2.3 是历史记录，禁止再次运行。

### 10.4 P4 最终命令

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_source_set tests.test_source_catalog tests.test_symbol_graph_signals tests.test_symbol_graph_genvars tests.test_symbol_graph_parameters tests.test_rewrite_policy tests.test_mapping_vnext tests.test_rewrite_vnext tests.test_mapping_execution_vnext tests.test_metrics_vnext tests.test_rate_vnext tests.test_rate_execution_vnext tests.test_rate_metrics_vnext tests.test_orchestration_vnext tests.test_cli_vnext_encryption tests.test_restore_vnext tests.test_project_root_vnext tests.test_project_root_inspect tests.test_formal_equivalence tests.test_encrypt_demo tests.test_vnext_category_closure tests.test_vnext_product_surface tests.test_risc_v_vector_project_root -v

conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/*.py encrypt.py scripts/formal_equivalence.py scripts/risc_v_vector_acceptance.py tests/test_*.py

git diff --check HEAD

rg -x -- '- 状态：READY_FOR_REVIEW' docs/tasks/T057_risc_v_vector_release_acceptance.md
```

最终 unittest 不得在测试内部再次运行完整 RISC Formal。

## 11. 阶段停止条件

出现以下任一情况立即停止，不进入下一阶段：

- P0 范围或 HEAD 不匹配；
- fixed input manifest、compile order 或 normalized oracle 不匹配；
- semantic fallback 需要无 target 名称搜索或不能满足 exact physical range；
- 不同 source identity 竞争同一 physical range；
- report 审计必须读取 external original/gold、修改 schema 或复制第二套 graph；
- actual gate manifest、temporary reconstructed input manifest 或 shared hydration 不一致；
- audit gate token/range 集合不等于 7182，或 P2 RISC preflight 不是
  6914 replacements/固定 aligned manifest/固定 warning digest；
- 版本 2.3 collector 改动改变 RISC source/mapping oracle、7182 tokens、strict gate 或
  19-file restore；
- FIFO 缺口不能仅通过 exact TypeAlias lexical-scope parameter binding 修复，或需要修改
  CLI/orchestration/demo/fixture；
- path conflict 只能通过修改输入或放宽 atomicity；
- strict gate 只能通过删除真实 reference、保留全部对象或忽略 diagnostic；
- P3 work-dir 已存在、RISC Formal 失败、超时或负例意外通过；
- 需要修改禁止文件或 oracle。

状态规则：

- 可在合同设计内修正的普通测试失败：保持 `IN_PROGRESS`；
- 遇到上述边界或架构冲突：记录并设 `BLOCKED`；
- 只有 P1–P4 全部通过：填写完整记录并设 `READY_FOR_REVIEW`；
- 子 Agent不得设置 `ACCEPTED`、创建 T058、git add/commit/push。

## 12. 子 Agent 执行记录模板

开始时填写：

```text
status: IN_PROGRESS
restart_time: 2026-07-27T13:16:12+0800
starting_head: cddc79192bdefb68243eef1e15e81a124f0814d1
starting_worktree: `git status --short --branch` -> `## main...origin/main [ahead 1]`; existing changes are exactly the audited version-1 T057 allowed-list changes; no unrelated worktree changes
P0_scope_audit: PASS; HEAD exact; branch exact; `git diff --cached --name-only` empty; `/private/tmp/rtl-obfuscation-t057-release-3` absent; no fixture, RISC RTL, Formal script, forbidden product-module, or oracle changes; exactly one active task is T057
existing_T057_changes_preserved: true
```

每阶段立即填写，不能等最终统一补记：

```text
P1_status: PASS
P1_changed_files: rtl_obfuscator/symbol_graph.py; tests/test_risc_v_vector_project_root.py; this task contract
P1_commands:
  `conda run -n rtl_obfuscation python -m unittest tests.test_source_set tests.test_source_catalog tests.test_symbol_graph_signals tests.test_symbol_graph_genvars tests.test_symbol_graph_parameters tests.test_rewrite_policy tests.test_mapping_vnext tests.test_rewrite_vnext tests.test_risc_v_vector_project_root.AuthorizedRiscBoundaryTests -v` -> exit_code=0; Ran 109 tests in 41.000s; OK
  `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/project_discovery.py rtl_obfuscator/source_set.py rtl_obfuscator/source_catalog.py rtl_obfuscator/symbol_graph.py tests/test_source_set.py tests/test_source_catalog.py tests/test_symbol_graph_signals.py tests/test_symbol_graph_genvars.py tests/test_symbol_graph_parameters.py tests/test_risc_v_vector_project_root.py` -> exit_code=0
  `git diff --check HEAD` -> exit_code=0
P1_results: `.sv` include provider, anonymous generate source-backed owner, ignored UninstantiatedDefSymbol, exact semantic fallback, declaration/occurrence separation, genvar/signal disjointness, deterministic repeated elaboration, and distinct source-identity overlap fail-closed all passed. P1 Formal is N/A because P1 only changes SourceSet/SymbolGraph source-range semantics.
P1_first_failure_or_boundary: strict audit initially exposed `CastExpressionSyntax.left.identifier` as the fixed direct path needed for a bound aggregate cast; added that direct field path. No unresolved P1 boundary remains.

P2_status: PASS
P2_changed_files: rtl_obfuscator/restore_vnext.py; rtl_obfuscator/formal_vnext.py; tests/test_risc_v_vector_project_root.py; this task contract
P2_commands:
  `conda run -n rtl_obfuscation python -m unittest tests.test_restore_vnext tests.test_risc_v_vector_project_root.FormalVNextTransactionTests -v` -> exit_code=0; Ran 13 tests in 3.884s; OK
  `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/restore_vnext.py rtl_obfuscator/formal_vnext.py tests/test_restore_vnext.py tests/test_risc_v_vector_project_root.py` -> exit_code=0
  `git diff --check HEAD` -> exit_code=0
P2_results: `OrchestrationGateAuditVNext` is the single report audit entry. It validates the portable outer/report chain, actual gate file set and hashes, reverses effective gate ranges into a temporary source root, and invokes the existing `load_restore_vnext()` hydration/metrics/restore validators. No external original/gold bytes are read. Formal alignment consumes this audit before gate-view validation, reverses only audited effective rename ranges that survive generic formal transformations, and publishes atomically with cleanup.
P2_tamper_matrix: fresh-run outer schema, compile-order escape, gate-manifest hash, input-manifest hash, duplicate effective renamed name, and no-rate original renamed name all returned `FORMAL_VNEXT_INPUT_INVALID` with no output; gate-view design.f, view-manifest hash, and transformed physical-file tamper all returned `FORMAL_VNEXT_INPUT_INVALID` with no output.
P2_path_matrix: output nested under gate-view, output nested under gate, manifest nested under gate-view, manifest nested under gate, and manifest equal to output all returned `FORMAL_VNEXT_OUTPUT_INVALID`; inputs stayed byte-identical and no output was published. Forced Yosys failure returned `FORMAL_VNEXT_YOSYS_FAILED`, left inputs unchanged, and left no output or temporary alignment directory.
P2_first_failure_or_boundary: initial audit implementation omitted canonical mapping summary/range_audit, treated repeated occurrence provenance as a duplicate without its physical range, and applied mapping reversals in report order rather than descending physical order; each was corrected. Generic formal lowering may consume an audited identifier inside a larger semantic transformation; that range is intentionally not reversed because no identifier remains in the verified view. No unresolved P2 boundary remains.

P3_status: BLOCKED
P3_command: `conda run -n rtl_obfuscation python scripts/risc_v_vector_acceptance.py --work-dir /private/tmp/rtl-obfuscation-t057-release-3` -> exit_code=1; the driver created the designated work-dir and its first child `encrypt-vnext` returned `CLI_VNEXT_ORCHESTRATION_INVALID`; stdout/stderr ended with `error: CLI_VNEXT_ORCHESTRATION_INVALID`.
P3_exit_code: 1
P3_canonical_json: none; the release driver did not reach canonical JSON emission.
P3_formal_positive: not run; actual gate was not produced.
P3_formal_negative: not run; actual gate was not produced.
P3_restore_identity: not run; actual gate was not produced.

P4_status: BLOCKED
P4_changed_files:
P4_commands:
P4_results:
legacy_replacement_coverage:
uncovered_boundaries: P3 first failure is the product CLI orchestration boundary: `rtl_obfuscator.rewrite encrypt-vnext --project-root /Users/lufengchi/Desktop/workspace/rtl_obfuscation/rtl_samples/RISC-V-Vector --top vector_top ...` failed closed with `CLI_VNEXT_ORCHESTRATION_INVALID` before gate generation. Per contract, no alternate work-dir, rerun, or P4 command was attempted; `/private/tmp/rtl-obfuscation-t057-release-3` was not deleted.
review_request: BLOCKED; main Agent must resolve the first CLI orchestration failure and explicitly resume T057 before any further phase.
```

上述版本 2 记录是不可覆盖的历史证据。版本 2.1 恢复时在其后追加：

```text
version_2_1_recovery:
  status: IN_PROGRESS
  recovery_start_time: 2026-07-27T13:55:30+0800
  starting_head: cddc79192bdefb68243eef1e15e81a124f0814d1
  starting_worktree: `git status --short --branch` -> `## main...origin/main [ahead 1]`; existing T057 changes are preserved in place and no unrelated worktree changes are present
  baseline_command: `git status --short --branch`
  baseline_result: exit_code=0; HEAD and branch exact; `git diff --cached --name-only` empty; release-3 exists as preserved failed evidence; release-4 absent
  allowed_files: existing version-1 T057 allow-list only; no staged changes, fixture/RISC RTL/Formal script/oracle changes
  release_3_preserved: true
  release_4_absent: true
  prior_P1_pass_withdrawn: true
  prior_P2_implementation_preserved_but_evidence_requires_rerun: true

P1_v2_1_status: IN_PROGRESS
P1_v2_1_changed_files:
  - rtl_obfuscator/symbol_graph.py
  - tests/test_risc_v_vector_project_root.py
  - docs/tasks/T057_risc_v_vector_release_acceptance.md
P1_v2_1_commands:
  - command: `conda run -n rtl_obfuscation python -m unittest tests.test_source_set tests.test_source_catalog tests.test_symbol_graph_signals tests.test_symbol_graph_genvars tests.test_symbol_graph_parameters tests.test_rewrite_policy tests.test_mapping_vnext tests.test_rewrite_vnext tests.test_risc_v_vector_project_root.AuthorizedRiscBoundaryTests -v`
    exit_code: 0
    result: 111 tests, OK
  - command: `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/project_discovery.py rtl_obfuscator/source_set.py rtl_obfuscator/source_catalog.py rtl_obfuscator/symbol_graph.py tests/test_source_set.py tests/test_source_catalog.py tests/test_symbol_graph_signals.py tests/test_symbol_graph_genvars.py tests/test_symbol_graph_parameters.py tests/test_risc_v_vector_project_root.py`
    exit_code: 0
    result: PASS
  - command: `git diff --check HEAD`
    exit_code: 0
    result: PASS
P1_v2_1_semantic_scope_evidence:
  vector_top.VECTOR_LANES_preserved_occurrences: `[rtl/vector/vector_top.sv:8932-8944, 11538-11550] -> parameter declaration rtl/vector/vector_top.sv:227-239; provenance=declaration_dimension; top-boundary preserve; no edit`
  vex.exec_data_i.VECTOR_LANES: `[rtl/vector/vex.sv:1010-1022] -> parameter declaration rtl/vector/vex.sv:230-242; provenance=declaration_dimension`
  vis.data_to_exec.VECTOR_LANES: `[rtl/vector/vis.sv:1158-1170] -> parameter declaration rtl/vector/vis.sv:228-240; provenance=declaration_dimension`
  gen_fifo.fifo_push: `[rtl/shared/eb_buff_generic.sv:2362-2371] -> signal declaration rtl/shared/eb_buff_generic.sv:1995-2004; provenance=semantic_generate_syntax`
  gen_fifo.fifo_pop: `[rtl/shared/eb_buff_generic.sv:2515-2523] -> signal declaration rtl/shared/eb_buff_generic.sv:2020-2028; provenance=semantic_generate_syntax`
  wrong_scope_and_ambiguous_lookup: `unresolvable fixed-field token raises SYMBOL_GRAPH_UNSUPPORTED_REFERENCE; scope lookup is required before exact target/range admission; no graph owner/name fallback; repeated source identity is deduplicated by physical range and different ranges remain under SYMBOL_GRAPH_RANGE_CONFLICT audit`
P1_v2_1_release_preflight:
  source_set_digest: `b359a1340ba461ce941ab68c6dcd34f33b365935e239af4e606710204f477fc7`
  mapping_range_digest: `217cce2e28c5c81280653fd233ba87d2a70a4a284417a3492182da2520da46fd`
  mapping_counts: `1327 total / 1301 rename / 26 preserve / 0 unsupported`
  modified_tokens: `7182`
  strict_gate: `PASS; catalog and top-overlay parse/semantic diagnostics are 0/0/0/0`
  restore_identity: `PASS; 19 physical files restored byte-identical; restored_manifest == input_manifest`
P1_v2_1_first_failure_or_boundary: `initial preflight attempt produced range digest 5fc06815148e9f37b27209bbbc8d0cce9f46f6e5703f46804055580efaaf7e04 while counts/modified_tokens matched; audit located the only field mismatch as the two gen_fifo recovered occurrences' provenance, corrected to semantic_generate_syntax, then the fresh preflight passed. No oracle value was changed.`
P1_v2_1_formal: `formal_verification: N/A; no new rewritten RTL is produced by P1`

P2_v2_1_status: PASS
P2_v2_1_commands:
  - command: `conda run -n rtl_obfuscation python -m unittest tests.test_restore_vnext tests.test_risc_v_vector_project_root.FormalVNextTransactionTests -v`
    exit_code: 0
    result: 13 tests, OK; actual report-chain tamper, gate-view tamper, path-conflict, atomic failure, deterministic build/alignment and positive/negative Formal transaction cases passed
  - command: `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/restore_vnext.py rtl_obfuscator/formal_vnext.py tests/test_restore_vnext.py tests/test_risc_v_vector_project_root.py`
    exit_code: 0
    result: PASS
  - command: `git diff --check HEAD`
    exit_code: 0
    result: PASS
P2_v2_1_results: `unique audit_orchestration_gate_vnext data flow is exercised before formal alignment; report/gate-view tamper and all required input/output overlap cases fail with no output; valid no-rate and rate reports align deterministically; Formal positive/negative transaction evidence passed`
P2_v2_1_first_failure_or_boundary: `none`

P3_v2_1_status: BLOCKED
P3_v2_1_command: `conda run -n rtl_obfuscation python scripts/risc_v_vector_acceptance.py --work-dir /private/tmp/rtl-obfuscation-t057-release-4`
P3_v2_1_exit_code: `1`
P3_v2_1_canonical_json: `not produced; release driver failed closed before acceptance JSON publication`
P3_v2_1_formal_positive: `not reached; actual alignment Yosys transaction failed before scripts/formal_equivalence.py`
P3_v2_1_formal_negative: `not reached; negative copy/mutation is not evidence`
P3_v2_1_restore_identity: `PASS before Formal alignment failure; release-4 orchestration report has strict_compile_passed=true, modified_tokens=7182, restored_byte_identical=true, and restored_manifest == input_manifest for 19 physical files`
P3_v2_1_first_failure: `FORMAL_VNEXT_YOSYS_FAILED at actual aligned gate view; first concrete object rtl/vector/vis.sv line 173 (the aligned expression contains nested range [21 +: 7][6:5]); Yosys error: ERROR: Single range expected. The transient alignment directory was cleaned by the API; release-4 remains as the preserved failed work-dir. No rerun or alternate work-dir was used.`

P4_v2_1_status: BLOCKED; not entered because P3 failed
P4_v2_1_commands: none
P4_v2_1_results: `legacy cleanup, final regression, and READY_FOR_REVIEW guard were not run`
review_request: `BLOCKED; main Agent must independently decide how to resolve the first P3 Formal alignment boundary before any rerun`
```

上述版本 2.1 记录是不可覆盖的历史证据。版本 2.2 恢复时在其后追加：

```text
version_2_2_recovery:
  status: IN_PROGRESS
  recovery_start_time: 2026-07-27T14:40:05+0800
  starting_head: cddc79192bdefb68243eef1e15e81a124f0814d1
  starting_worktree: `git status --short --branch` -> `## main...origin/main [ahead 1]`; existing changes are preserved and remain within the audited T057 allowed list; no unrelated worktree changes
  baseline_command: `git status --short --branch`
  baseline_result: `exit_code=0; HEAD exact; branch exact; git diff --cached --name-only empty; only T057 active; release-3 and release-4 exist; release-5 absent`
  release_3_preserved: true
  release_4_preserved: true
  release_5_absent: true
  P1_v2_1_evidence_retained: true
  P2_v2_1_pass_withdrawn: true
  allowed_files: `v2.2 new edits limited to rtl_obfuscator/formal_vnext.py, tests/test_risc_v_vector_project_root.py, and this task contract`

P2_v2_2_status: PASS
P2_v2_2_changed_files:
  - rtl_obfuscator/formal_vnext.py
  - tests/test_risc_v_vector_project_root.py
  - docs/tasks/T057_risc_v_vector_release_acceptance.md
P2_v2_2_commands:
  - command: `conda run -n rtl_obfuscation python -m unittest tests.test_restore_vnext tests.test_risc_v_vector_project_root.FormalVNextTransactionTests -v`
    exit_code: 0
    result: 15 tests in 48.911s, OK; restore validators, report/gate-view tamper matrix, all path conflicts, packed-struct replacement alignment, actual RISC lexer preflight, warning digest, and cleanup checks passed
  - command: `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/restore_vnext.py rtl_obfuscator/formal_vnext.py tests/test_restore_vnext.py tests/test_risc_v_vector_project_root.py`
    exit_code: 0
    result: PASS
  - command: `git diff --check HEAD`
    exit_code: 0
    result: PASS
P2_v2_2_alignment_lineage:
  actual_gate_audited_rename_ranges: 7182
  actual_gate_lexer_identifier_ranges: 7182
  range_set_relation: `expected=7182; actual=7182; missing=0; extra=0; exact set and renamed-token bytes equal`
  transformation_overlap_identifiers_restored: `6914 verified gate-view Identifier replacements; the frozen RISC audit includes 243 renamed identifiers copied into Formal transformation replacements, and the self-contained packed-struct test proves the renamed base is restored rather than skipped`
  comments_strings_macros_unchanged: `PASS; only PySlang TokenKind.Identifier tokens whose raw text is in the audited dictionary are edited; lexer diagnostics, token bytes, duplicate/overlap edits and range/token-set mismatch fail closed`
P2_v2_2_risc_preflight:
  identifier_replacements: 6914
  aligned_view_manifest: `7c93970509f6844c6fb7902de6ded6878e8fae6753578a5b862e6fc3c18deae9`
  normalized_yosys_warning_digest: `82364328ba2442aea6429d2a1ec8ab406784f0fcfb4d9d3b681589de8e5a6b8f` for gold/gate/aligned
  aligned_yosys_validation: PASS
  cleanup: PASS; fresh temporary preflight directory removed by the test; no `.formal-align-vnext-*` temporary directory remained
  formal_equivalence: N/A; P2 preflight must not invoke formal_equivalence.py
P2_v2_2_first_failure_or_boundary: `Initial test-only attempts exposed a source-root/output overlap and an invalid temporary unpacked packed-struct port; both were corrected within the allowed test file. Final P2 has no unresolved alignment boundary.`

P3_v2_2_status: PASS
P3_v2_2_command: `conda run -n rtl_obfuscation python scripts/risc_v_vector_acceptance.py --work-dir /private/tmp/rtl-obfuscation-t057-release-5`
P3_v2_2_exit_code: 0
P3_v2_2_canonical_json: `format=rtl-obfuscation.risc-v-vector-vnext-acceptance; schema_version=1; status=pass; input={origin:project-root, top:vector_top, files:19, modules:17, input_manifest_sha256:a016dd548525346508c636b97fcc452c8f6eb4fcbf930ef5eb938a2edfa2ae9d, source_set_digest:b359a1340ba461ce941ab68c6dcd34f33b365935e239af4e606710204f477fc7}; mapping={total:1327, rename:1301, preserve:26, unsupported:0, modified_tokens:7182, range_digest:217cce2e28c5c81280653fd233ba87d2a70a4a284417a3492182da2520da46fd, per_category: frozen 19-category counts 16/1 modules, 120/14 parameters, 348/11 ports, 675/0 signals, 66/0 struct_fields, 7/0 struct_types, 7/0 genvars, 8/0 generate_blocks, 19/0 instances, 33/0 enum_values, 2/0 typedefs, 0/0 for arguments/functions/tasks/interfaces/interface_instances/interface_ports/modports/union_fields}; metrics={effective_line_total:4461, affected_line_count:3387, modified_tokens:7182, symbols:{eligible:1301, renamed:1301, coverage:1.0}, occurrences:{eligible:7182, renamed:7182, coverage:1.0}, plaintext_leakage_rate:0.0}; restore={files:19, restored_manifest_equal:true, byte_identical:true}; formal_view={gold_transformations:260, gate_transformations:260, gold_signature_digest:63a9ef753fdb55f735359b4e65ec8e5c6d61a9b0626ceec21486d9786ac0a925, gate_signature_digest:63a9ef753fdb55f735359b4e65ec8e5c6d61a9b0626ceec21486d9786ac0a925, normalized_yosys_warning_digest:82364328ba2442aea6429d2a1ec8ab406784f0fcfb4d9d3b681589de8e5a6b8f}; formal_alignment={identifier_replacements:6914, aligned_view_manifest_sha256:7c93970509f6844c6fb7902de6ded6878e8fae6753578a5b862e6fc3c18deae9}`
P3_v2_2_formal_positive: `gold=/private/tmp/rtl-obfuscation-t057-release-5/formal-gold/design.f; gate=/private/tmp/rtl-obfuscation-t057-release-5/formal-aligned/design.f; top=vector_top; seq=1; command=conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold-filelist /private/tmp/rtl-obfuscation-t057-release-5/formal-gold/design.f --gold-root /private/tmp/rtl-obfuscation-t057-release-5/formal-gold --gate-filelist /private/tmp/rtl-obfuscation-t057-release-5/formal-aligned/design.f --gate-root /private/tmp/rtl-obfuscation-t057-release-5/formal-aligned --top vector_top --seq 1; exit_code=0; result contains formal_equivalence=pass`
P3_v2_2_formal_negative: `file=rtl/vector/vector_top.sv; change=one ASCII byte & -> |; strict_compile=PASS (0/0); command=conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold-filelist /private/tmp/rtl-obfuscation-t057-release-5/formal-gold/design.f --gold-root /private/tmp/rtl-obfuscation-t057-release-5/formal-gold --gate-filelist /private/tmp/rtl-obfuscation-t057-release-5/formal-negative/design.f --gate-root /private/tmp/rtl-obfuscation-t057-release-5/formal-negative --top vector_top --seq 1; exit_code=nonzero; result contains unproven and equiv_status -assert`
P3_v2_2_restore_identity: `PASS; 19 physical files byte-identical after restore; restored_manifest_equal=true`

P4_v2_2_status: BLOCKED
P4_v2_2_commands:
  - command: `conda run -n rtl_obfuscation python -m unittest tests.test_source_set tests.test_source_catalog tests.test_symbol_graph_signals tests.test_symbol_graph_genvars tests.test_symbol_graph_parameters tests.test_rewrite_policy tests.test_mapping_vnext tests.test_rewrite_vnext tests.test_mapping_execution_vnext tests.test_metrics_vnext tests.test_rate_vnext tests.test_rate_execution_vnext tests.test_rate_metrics_vnext tests.test_orchestration_vnext tests.test_cli_vnext_encryption tests.test_restore_vnext tests.test_project_root_vnext tests.test_project_root_inspect tests.test_formal_equivalence tests.test_encrypt_demo tests.test_vnext_category_closure tests.test_vnext_product_surface tests.test_risc_v_vector_project_root -v`
    exit_code: 1
    result: 192 tests; 191 passed, 1 failed; first failure `tests.test_encrypt_demo.EncryptDemoTests.test_default_fifo_vnext_demo_restores_byte_identically` at `tests/test_encrypt_demo.py:37`, stderr `error: rewrite command failed with exit code 1: error: CLI_VNEXT_ORCHESTRATION_INVALID`
  - remaining P4 commands not run after the first failure because the required correction is outside the v2.2 allow-list
P4_v2_2_results: `P3 passed and release-5 is preserved. The P4 failure is unrelated to the v2.2 changed files: this round did not modify encrypt.py, rtl_obfuscator/rewrite.py, or rtl_obfuscator/orchestration_vnext.py. Existing T057 legacy replacement deletions and coverage remain preserved, but final regression cannot be accepted without an out-of-scope product/demo correction.`
legacy_replacement_coverage: `P4 deletion set remains rtl_obfuscator/inventory.py, rtl_obfuscator/category_profile.py, rtl_obfuscator/project.py, rtl_obfuscator/formal_view.py, scripts/t029_acceptance.py; replacement coverage is retained from T057 v2.1 and P2/P3 evidence. No new legacy path or shim was added.`
uncovered_boundaries: `source_range=N/A (CLI orchestration boundary); object=FIFO demo project-root invocation via encrypt.py; file=tests/test_encrypt_demo.py:37; error_code=CLI_VNEXT_ORCHESTRATION_INVALID; required change would be in the out-of-scope encrypt.py/rewrite.py/orchestration product boundary or its contract, so no expansion was made.`
review_request: `BLOCKED; P2 and P3 are complete, but P4 has one pre-existing/out-of-scope FIFO demo failure. Main Agent direction is required before any file outside the v2.2 allow-list may be changed.`
post_failure_diagnostic: `git diff --check HEAD -> exit_code=0; no whitespace errors. The READY_FOR_REVIEW guard was not run because the task is BLOCKED.`
```

上述版本 2.2 记录是不可覆盖的历史证据。版本 2.3 恢复时在其后追加：

```text
version_2_3_recovery:
  status: READY_FOR_REVIEW
  recovery_start_time: 2026-07-27T15:23:01+0800
  starting_head: cddc79192bdefb68243eef1e15e81a124f0814d1
  starting_worktree: `git status --short --branch` -> `## main...origin/main [ahead 1]`; existing changes remain the audited historical T057 allowed-list changes; no unrelated worktree changes
  baseline_command: `git status --short --branch`
  baseline_result: `exit_code=0; HEAD exact; branch exact; git diff --cached --name-only empty; release-3, release-4 and release-5 present; exact active task T057 was READY before recovery`
  release_3_preserved: true
  release_4_preserved: true
  release_5_preserved: true
  staged_changes: none
  P1_v2_1_evidence_retained: true
  P2_v2_2_evidence_retained: true
  P3_v2_2_evidence_retained_without_rerun: true

P4_v2_3_status: PASS
P4_v2_3_changed_files:
  - rtl_obfuscator/symbol_graph.py
  - tests/test_symbol_graph_parameters.py
  - docs/tasks/T057_risc_v_vector_release_acceptance.md
P4_v2_3_semantic_binding:
  aggregate_owner: `child_a_t` and `child_b_t` TypeAliasType nodes; member declarations are owned by their respective module lexical scopes
  bounded_dimension_syntax: `TypeAliasType.canonicalType.syntax -> StructUnionTypeSyntax.members -> StructUnionMemberSyntax.type -> VariableDimensionSyntax.specifier.selector -> RangeSelectSyntax.left/right`; only bounded identifier operands in each member dimension are enumerated
  lexical_scope_lookup: `child_a_t.parentScope.lookupName("WIDTH") -> child_a ParameterSymbol`; `child_b_t.parentScope.lookupName("WIDTH") -> child_b ParameterSymbol`
  exact_parameter_declaration: `child_a WIDTH declaration [31,36)` and `child_b WIDTH declaration [180,185)`; each target maps to exactly one existing _ParameterRecord by declaration source identity
  occurrence_range_and_provenance: `child_a WIDTH occurrence [82,87)` and `child_b WIDTH occurrence [230,235)`; both physical bytes are WIDTH and provenance is declaration_dimension; declarations are not occurrences
  shadowed_same_name_isolation: `child_a occurrence [82,87) binds only to child_a declaration [31,36); child_b occurrence [230,235) binds only to child_b declaration [180,185); graph range audit passes`
  no_owner_name_fallback: `PASS; no file scan, alias subtree search, owner/name graph fallback, global/package/non-ParameterSymbol record or new record path was used`
P4_v2_3_fifo:
  cli: `PASS; unchanged encrypt.py/FIFO sample; directed check exit_code=0`
  strict_gate: `PASS; FIFO actual gate strict compile passed`
  restore_identity: `PASS; 4 FIFO physical files restored byte-identical`
P4_v2_3_risc_non_regression:
  source_set_digest: `b359a1340ba461ce941ab68c6dcd34f33b365935e239af4e606710204f477fc7`
  mapping_range_digest: `217cce2e28c5c81280653fd233ba87d2a70a4a284417a3492182da2520da46fd`
  mapping_counts: `1327 total / 1301 rename / 26 preserve / 0 unsupported`
  modified_tokens: 7182
  strict_gate: `PASS; actual RISC catalog/top-overlay semantic compile remained 0/0/0/0`
  restore_identity: `PASS; retained P3 release-5 evidence has 19 physical files byte-identical and restored_manifest_equal=true`
  formal_equivalence: NOT RERUN; retained release-5 evidence only
P4_v2_3_commands:
  - command: `conda run -n rtl_obfuscation python -m unittest tests.test_symbol_graph_parameters.SymbolGraphParameterTests.test_packed_aggregate_member_dimension_uses_alias_lexical_scope tests.test_encrypt_demo.EncryptDemoTests.test_default_fifo_vnext_demo_restores_byte_identically tests.test_risc_v_vector_project_root.AuthorizedRiscBoundaryTests.test_risc_mapping_oracle_strict_gate_and_restore_preflight -v`
    exit_code: 0
    result: 3 tests in 13.647s, OK; FIFO unchanged CLI/strict gate/4-file restore and RISC oracle/non-regression passed; no Formal equivalence ran
  - command: `conda run -n rtl_obfuscation python -m unittest tests.test_source_set tests.test_source_catalog tests.test_symbol_graph_signals tests.test_symbol_graph_genvars tests.test_symbol_graph_parameters tests.test_rewrite_policy tests.test_mapping_vnext tests.test_rewrite_vnext tests.test_mapping_execution_vnext tests.test_metrics_vnext tests.test_rate_vnext tests.test_rate_execution_vnext tests.test_rate_metrics_vnext tests.test_orchestration_vnext tests.test_cli_vnext_encryption tests.test_restore_vnext tests.test_project_root_vnext tests.test_project_root_inspect tests.test_formal_equivalence tests.test_encrypt_demo tests.test_vnext_category_closure tests.test_vnext_product_surface tests.test_risc_v_vector_project_root -v`
    exit_code: 0
    result: 193 tests in 122.102s, OK
  - command: `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/*.py encrypt.py scripts/formal_equivalence.py scripts/risc_v_vector_acceptance.py tests/test_*.py`
    exit_code: 0
    result: PASS
  - command: `git diff --check HEAD`
    exit_code: 0
    result: PASS
  - command: `rg -x -- '- 状态：READY_FOR_REVIEW' docs/tasks/T057_risc_v_vector_release_acceptance.md`
    exit_code: 0
    result: matched exactly `- 状态：READY_FOR_REVIEW`
P4_v2_3_results: `PASS; exact TypeAlias lexical-scope binding corrected the FIFO packed union member dimension without modifying CLI/orchestration/demo/fixture, and all final P4 gates passed through diff check. Existing legacy deletion set and replacement coverage remain unchanged.`
legacy_replacement_coverage: `PASS; retained deletion set: rtl_obfuscator/inventory.py, rtl_obfuscator/category_profile.py, rtl_obfuscator/project.py, rtl_obfuscator/formal_view.py, scripts/t029_acceptance.py; covered respectively by SourceCatalog/SymbolGraph, category registry/rewrite policy/19-category oracle, SourceSet/discovery equivalence, P2 Formal transaction, and release driver evidence.`
uncovered_boundaries: `none within v2.3 scope; Formal was not rerun by contract and release-5 Formal evidence is retained only`
formal_verification: `formal_equivalence: NOT RERUN; retained release-5 evidence only`
review_request: `READY_FOR_REVIEW; P4 v2.3 complete; main Agent must independently verify the three allowed-file changes and retained release-5 evidence.`
```

Formal 记录必须包含：

```text
formal_verification: PASS
gold: /private/tmp/rtl-obfuscation-t057-release-5/formal-gold/design.f
gate: /private/tmp/rtl-obfuscation-t057-release-5/formal-aligned/design.f
top: vector_top
seq: 1
positive_command:
positive_exit_code: 0
positive_result: contains formal_equivalence=pass
negative_file: rtl/vector/vector_top.sv
negative_change: one ASCII byte & -> |
negative_strict_view: PASS
negative_command:
negative_exit_code: nonzero
negative_result: contains unproven and equiv_status -assert
```

## 13. 版本 1 撤回记录

```text
version_1_starting_head: cddc79192bdefb68243eef1e15e81a124f0814d1
version_1_unittest: 180 tests; PASS
version_1_py_compile: PASS
version_1_diff_check: PASS
version_1_risc_formal_positive: PASS
version_1_risc_formal_negative: expected failure
version_1_restore: 19 files byte-identical
withdrawal_reason:
  1. tampered mapping_execution.gate_manifest was accepted by alignment
  2. alignment output inside gate_view input was accepted
  3. semantic fallback used syntax-subtree name search before exact sourceRange
disposition:
  evidence retained as history; not valid for version-2 acceptance
```

## 14. 主 Agent 最终验收

待 `READY_FOR_REVIEW` 后，主 Agent按 P1、P2、P4 顺序独立复跑 compact/final commands，
审计 P3 已产生的完整 work-dir 和 canonical JSON，不再次运行 RISC Formal。随后：

1. 检查状态、允许文件和所有新增文件；
2. 在不改变内容的前提下暂存全部 T057 文件；
3. 运行 `git diff --cached --check`，覆盖 untracked 新文件；
4. 独立核对 P2 tamper/path matrix 和 P3 report/hash chain；
5. 全部通过后才把状态设为 `ACCEPTED`、提交并推送。

### 14.1 主 Agent 独立验收记录

```text
acceptance_date: 2026-07-27
review_head: cddc79192bdefb68243eef1e15e81a124f0814d1
review_scope: all accumulated T057 allowed-list changes, including the three v2.3 recovery files

P1_command: conda run -n rtl_obfuscation python -m unittest tests.test_source_set tests.test_source_catalog tests.test_symbol_graph_signals tests.test_symbol_graph_genvars tests.test_symbol_graph_parameters tests.test_rewrite_policy tests.test_mapping_vnext tests.test_rewrite_vnext tests.test_risc_v_vector_project_root.AuthorizedRiscBoundaryTests -v
P1_result: 112 tests in 67.359s; OK; exit_code=0
P1_py_compile: PASS; exit_code=0

P2_command: conda run -n rtl_obfuscation python -m unittest tests.test_restore_vnext tests.test_risc_v_vector_project_root.FormalVNextTransactionTests -v
P2_result: 15 tests in 50.045s; OK; exit_code=0
P2_py_compile: PASS; exit_code=0
P2_audit: 7182 exact modified-token ranges; 6914 aligned replacements; persisted manifest, warning and lineage validation PASS

P4_command: conda run -n rtl_obfuscation python -m unittest tests.test_source_set tests.test_source_catalog tests.test_symbol_graph_signals tests.test_symbol_graph_genvars tests.test_symbol_graph_parameters tests.test_rewrite_policy tests.test_mapping_vnext tests.test_rewrite_vnext tests.test_mapping_execution_vnext tests.test_metrics_vnext tests.test_rate_vnext tests.test_rate_execution_vnext tests.test_rate_metrics_vnext tests.test_orchestration_vnext tests.test_cli_vnext_encryption tests.test_restore_vnext tests.test_project_root_vnext tests.test_project_root_inspect tests.test_formal_equivalence tests.test_encrypt_demo tests.test_vnext_category_closure tests.test_vnext_product_surface tests.test_risc_v_vector_project_root -v
P4_result: 193 tests in 124.285s; OK; exit_code=0
P4_py_compile: PASS; exit_code=0
diff_check: git diff --check HEAD; PASS; exit_code=0
ready_for_review_guard_before_acceptance: PASS; exit_code=0

release_work_dir: /private/tmp/rtl-obfuscation-t057-release-5
release_driver_rerun: false
release_artifact_audit:
  source_set: 19 files
  mapping: 1327 total / 1301 rename / 26 preserve / 0 unsupported
  modified_tokens: 7182
  mapping_range_digest: 217cce2e28c5c81280653fd233ba87d2a70a4a284417a3492182da2520da46fd
  restore: 19 files byte-identical
  gold_transformations: 260
  gate_transformations: 260
  transformation_digest: 63a9ef753fdb55f735359b4e65ec8e5c6d61a9b0626ceec21486d9786ac0a925
  aligned_replacements: 6914
  aligned_manifest_digest: 7c93970509f6844c6fb7902de6ded6878e8fa6753578a5b862e6fc3c18deae9
  negative_change: rtl/vector/vector_top.sv byte 1362, ASCII '&' -> '|'

formal_rerun_reason: project Main Agent rules require an independent scripts/formal_equivalence.py rerun for rewritten RTL; only the retained and audited release-5 artifacts were used, and the release driver was not rerun
formal_positive_command: conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold-filelist /private/tmp/rtl-obfuscation-t057-release-5/formal-gold/design.f --gold-root /private/tmp/rtl-obfuscation-t057-release-5/formal-gold --gate-filelist /private/tmp/rtl-obfuscation-t057-release-5/formal-aligned/design.f --gate-root /private/tmp/rtl-obfuscation-t057-release-5/formal-aligned --top vector_top --seq 1
formal_positive_exit_code: 0
formal_positive_result: formal_equivalence=pass
formal_negative_command: conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold-filelist /private/tmp/rtl-obfuscation-t057-release-5/formal-gold/design.f --gold-root /private/tmp/rtl-obfuscation-t057-release-5/formal-gold --gate-filelist /private/tmp/rtl-obfuscation-t057-release-5/formal-negative/design.f --gate-root /private/tmp/rtl-obfuscation-t057-release-5/formal-negative --top vector_top --seq 1
formal_negative_exit_code: 1
formal_negative_result: expected failure; contains "unproven" and "equiv_status -assert"

final_status: ACCEPTED
uncovered_boundaries: none within T057 v2.3
```
