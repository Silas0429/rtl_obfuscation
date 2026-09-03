# T133：FAST 安全补齐 module 直接变量与选择引用

- 状态：`ACCEPTED`
- 负责人：子 Agent（实现与自测）/ 主 Agent（合同与验收）
- 起始分支：`delivery/fast-local-signals`
- 起始提交：`cb03deb`

## 1. 单一目标

保持 T131 definition-local CST 架构、公开 CLI、SourceSet、MappingVNext schema、物理 byte-range rewrite、
strict gate、restore 和原子发布不变，把 FAST `signals` 的安全范围从“module 最外层直接 `logic/wire` +
裸 IdentifierName”精确扩展到：

1. module 最外层直接 `logic/wire` 变量在 element/bit/part/indexed selection 中的根 identifier；
2. module 最外层直接 DataDeclaration 的用户自定义数据类型变量；
3. 自定义类型变量作为 value member/select chain 根对象时只改根 identifier，不改类型名或字段名。

目标不是与 FULL rename 集合完全一致，而是在不构建 semantic Compilation、top、实例层级或依赖闭包的
前提下，补齐已由 StCache 证据确认的 module-direct 安全对象。

## 2. 固定输入

主 Agent 冻结以下输入，子 Agent 不得修改：

```text
tests/fixtures/t133_fast_direct_variables/design.f
tests/fixtures/t133_fast_direct_variables/formal.f
tests/fixtures/t133_fast_direct_variables/external/word_type.sv
tests/fixtures/t133_fast_direct_variables/external/pair_type.sv
tests/fixtures/t133_fast_direct_variables/owned/design.sv
tests/fixtures/t133_fast_direct_variables/owned/formal.sv
tests/test_t133_fast_direct_variables.py
```

公开输入固定为：

```sh
python rtl_encrypt.py \
  --filelist tests/fixtures/t133_fast_direct_variables/design.f \
  --rewrite-root tests/fixtures/t133_fast_direct_variables/owned \
  --category signals \
  --output-dir <new-output>
```

## 3. 冻结行为

### 3.1 候选声明

- 只枚举 rewrite-root 显式 source unit 中 `ModuleDeclaration.members` 的直接
  `DataDeclaration` / `NetDeclaration` declarator；
- 支持直接 `logic`、`wire` 和用户自定义数据类型的变量 declarator；
- declaration 必须是普通、非宏、非 escaped 的唯一物理 identifier token；
- ports、parameter/localparam、typedef、genvar、module/interface/class/instance/type 名本身不建 record；
- function/task/block/generate 内声明仍不建 record；
- 不通过字符串拆分、正则声明解析或名字查找猜测声明种类。

### 3.2 引用授权

- 保留 T131 已允许的唯一裸 `IdentifierName` value reference；
- 新增授权只限选中变量作为 element/bit/part/indexed selection 的根 identifier；
- 对 member/select chain，只允许改写最左侧、确认为该变量的根 identifier；字段/member token、index
  表达式中的其他名字和层次路径 token 不归属给该变量；
- 同一 module 内的同名声明、named port/parameter/argument label、宏来源、escaped identifier、scope/
  hierarchical root、无法唯一定位的 token 或未知形态，整条对象仍 `preserve / syntax_local_ambiguous`；
- CST 全拼写 completeness 保持：同一 module 内每个同名物理 token 必须能归属为该声明、授权的根引用，
  或另一个唯一物理声明，否则对象保留；
- declaration 和全部 occurrence 必须同 module、同 physical file、逐字节匹配、无重复重叠。

### 3.3 结构与兼容边界

- mapping 阶段仍不得创建 semantic `Compilation`、读取 `topInstances`、遍历实例层级或计算依赖闭包；
- 不新增 fallback、兼容层、第二套 collector、全局文本替换或 fixture/module 特判；
- 不改变 FAST 分派条件，不改变 FULL 行为；
- 不改变 category、mapping/report schema、name factory、rewrite、restore、vendor 只读或 filelist 行为；
- gate 仍使用完整 filelist strict compilation。

## 4. 预期机器可读结果

固定公开正例必须满足：

```text
CLI exit                         = 0
format                           = rtl-obfuscation.cli-vnext
schema_version                   = 2
summary.strict_compile_passed    = true
summary.restored_byte_identical  = true
mapping records                  = 8
rename                           = packed_signal, array_signal, typed_signal, aggregate_signal,
                                   formal_typed_signal, formal_selected_signal
preserve/syntax_local_ambiguous  = same_label, macro_signal
absent candidates                = generated_local, function_local, ports, typedef/type/field names
external/word_type.sv            = byte-identical
external/pair_type.sv            = byte-identical
actual rewritten gate Formal     = pass
fixed functional negative Formal = fail
```

两个 external 文件使用 compilation-unit typedef 提供外部类型上下文；不使用本机 Yosys 尚不支持的
package import，但类型文件仍位于 rewrite-root 外且必须逐字节只读。公开 gate strict compile 覆盖全部
对象；compact Formal 选择同一实际 gate 中不含 Yosys packed-struct 前端限制的 `owned/formal.sv`，代表性
覆盖自定义数据类型变量和 selection 根名。

Gate 中六个 rename 对象的旧名必须为零；字段 `low/high`、两个 preserve 对象与嵌套局部名字必须仍存在。

## 5. 不包含

- 不支持 generate/block/function/task locals；
- 不加密 ports、parameters、typedef、interface/member、struct/union field；
- 不放行 named label、宏、escaped identifier、跨层级引用或未知语法；
- 不追求 FAST 与 FULL 全量 rename 数量一致；
- 不合并 `main` 的 `1d9736f`，不运行真实 StCache/AICluster，不运行 RISC-V-Vector Formal；
- 不做无关性能重构、缓存或 schema 迁移。

## 6. 允许修改文件

```text
docs/tasks/T133_fast_direct_module_variables.md
rtl_obfuscator/fast_local_signals.py
README.md
docs/systemverilog_renaming_table.md
docs/development/project_structure.md
```

第 2 节 fixture 和测试是主 Agent 冻结 oracle；子 Agent不得修改。若 PySlang CST API 无法在这些边界内
唯一证明根 identifier，或需要修改允许列表外文件，必须记录偏差并停止。

## 7. Baseline

子 Agent 修改实现前必须运行：

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_t133_fast_direct_variables.T133FastDirectVariablesTests.test_public_direct_variables_roundtrip_and_boundaries -v
```

预期失败：当前 FAST 不会同时得到第 4 节固定的 6 rename + 2 preserve 记录。

## 8. 固定验收命令

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_t133_fast_direct_variables -v

conda run -n rtl_obfuscation python -m unittest \
  tests.test_t132_separated_declarator_list \
  tests.test_t131_definition_local_signals \
  tests.test_t130_fast_local_signals -v

conda run -n rtl_obfuscation python -m py_compile \
  rtl_obfuscator/fast_local_signals.py \
  tests/test_t133_fast_direct_variables.py

git diff --check HEAD

conda run -n rtl_obfuscation python -c 'from pathlib import Path; s=next(l for l in Path("docs/tasks/T133_fast_direct_module_variables.md").read_text().splitlines() if l.startswith("- 状态：")); assert s=="- 状态：`READY_FOR_REVIEW`", s; print("t133_ready_for_review=pass")'
```

第一条必须运行公开 CLI、strict gate、decrypt byte identity，以及实际 rewritten gate Formal：

```text
gold-filelist = tests/fixtures/t133_fast_direct_variables/formal.f
gold-root     = tests/fixtures/t133_fast_direct_variables
gate-filelist = <actual gate>/formal.f
gate-root     = <actual gate>
top           = t133_fast_direct_variables_formal
seq           = 5
positive      = exit 0 and JSON formal_equivalence=pass
negative      = actual gate 中唯一 " ^ 8'h3" 改为 " | 8'h3"，exit nonzero，含 unproven 与 equiv_status -assert
```

## 9. 子 Agent 执行记录

```text
status: READY_FOR_REVIEW
starting_head: cb03deb (2026-09-03 10:40:09 +0800; branch delivery/fast-local-signals; pre-existing untracked frozen contract/tests/fixtures only)
changed_files: rtl_obfuscator/fast_local_signals.py; README.md; docs/systemverilog_renaming_table.md; docs/development/project_structure.md; docs/tasks/T133_fast_direct_module_variables.md
commands: prior Section 8 product acceptance retained; continuation preflight `git status --short --branch`; `git diff --check HEAD`; documentation scope assertion via `conda run -n rtl_obfuscation python -c ...`; exact Section 8 status guard
results: documentation scope assertion pass; diff check pass; prior T133 2 tests and T132/T131/T130 16 tests remain passing; no product-code, test, or fixture changes in this clarification turn
schema_or_behavior: implement only Section 3 direct module DataDeclaration/NetDeclaration variable and authorized selection-root scope
boundaries: do not modify frozen tests/fixtures or files outside Section 6; no Compilation/top/hierarchy/fallback/category/schema changes; NamedType docs must mean only simple unqualified CST `NamedType.name` kind `IdentifierName` (for example `word_t`), not `pkg::RspCmd_t`; direct struct-typed module variables may be renamed by this task, while struct/union type definitions and fields remain excluded
cleanup_candidates: none
formal_verification: PASS; actual gate `/tmp/t133-acceptance-evidence.o4v9VL`, gold-filelist `tests/fixtures/t133_fast_direct_variables/formal.f`, gold-root `tests/fixtures/t133_fast_direct_variables`, gate-filelist `/tmp/t133-acceptance-evidence.o4v9VL/gate/formal.f`, gate-root `/tmp/t133-acceptance-evidence.o4v9VL/gate`, top `t133_fast_direct_variables_formal`, seq 5; positive exit 0 JSON `formal_equivalence=pass`; fixed negative exit 1 with `unproven` and `equiv_status -assert`
review_request: READY_FOR_REVIEW; main Agent to independently rerun Section 8 and review allowed-file diff
```

## 10. 偏差或阻塞

```text
contract_preflight: >-
  当前实现 baseline 按预期失败，缺少 typed_signal、aggregate_signal、formal_typed_signal；
  compact Formal 正例与固定负例预检通过。初始 fixture 使用 package import 时本机 Yosys 不支持，
  主 Agent 在 READY 前改为等价 compilation-unit typedef，并拆分 compact Formal filelist；
  公开 strict gate 仍覆盖全部结构体根名场景，任务行为边界未改变。
  实现后公开目标测试的 CLI、mapping、strict gate、restore summary 和 gate 文件检查均达到合同预期，
  但测试随后按 fixture 全部文件名读取 restored/design.f 与 restored/formal.f；现有 schema 2 restore
  manifest 仅恢复源文件，gate 也只生成 canonical design.f（formal.f 由测试在 gate 中另行复制），
  因此该冻结测试在恢复目录文件缺失处失败。修复需要修改冻结测试/restore 或扩大 schema，均超出本任务允许边界；
  已停止继续扩大实现，待主 Agent 决定该 oracle 偏差。
contract_correction_2026-09-03: >-
  主 Agent 确认 schema 2 restore 的既有合同只恢复 manifest 中的物理 RTL 输入，不恢复用户 filelist；
  冻结测试错误地遍历了 design.f/formal.f。主 Agent 已将 byte-identity 断言精确限制为 .sv/.v，
  未修改产品行为、预期 mapping、strict gate 或 Formal 强度。任务恢复 READY，按原计划继续。
implementation_resolution_2026-09-03: >-
  已按修正后的冻结 oracle 完成文档同步和五条验收；selection 仅授权 IdentifierSelectName 根，
  member 仅授权 `.` ScopedName 最左根，`::`、right member、named label、宏、嵌套声明继续对象级保留。
documentation_clarification_2026-09-03: >-
  三份公开文档已明确快速路径的用户自定义类型仅限未限定简单 `NamedType.name`/`IdentifierName`，
  不支持 `pkg::RspCmd_t` 等限定类型；interface 对象、struct/union 类型定义与字段不改，
  但直接 struct-typed module 变量根名仍可按 signals 规则改写。
```

## 11. 主 Agent 验收记录

```text
status: ACCEPTED
reviewed_head: cb03deb + T133 working tree
acceptance: >-
  主 Agent 独立运行第8节五条命令：T133 2/2；T132/T131/T130 16/16；py_compile pass；
  git diff --check HEAD pass；READY_FOR_REVIEW guard pass。另生成实际 gate
  /private/tmp/t133-main-review.eHnWfP/gate：schema 2，6 rename / 2 preserve，strict compile 与
  restored byte identity 均为 true，外部类型文件逐字节不变。
code_review: >-
  PASS。候选只从 module 直接 DataDeclaration/NetDeclaration 取得；既有 logic/wire 保持，新增类型
  严格限于 NamedType.name 为简单 IdentifierName。IdentifierSelectName 只授权 identifier 根 token；
  `.` ScopedName 只授权最左根，right member、`::`、named label、宏、escaped、同名嵌套和未知形态继续
  对象级 preserve。未构造 Compilation/top/hierarchy，未改变 FULL、CLI、schema、rewrite 或 restore。
blocking_findings: none；主 Agent 冻结 oracle 的 filelist restore 误断言已在 READY 阶段按既有 schema 合同修正
resolution: >-
  ACCEPTED。额外 gate_rename_audit 对实际 gate 检查29个改写 range：leaked_old_name=0、misplaced=0、
  gate_only_implicit_nets=0、residual_old_names=0，VERDICT clean。
formal_verification: >-
  PASS。gold-filelist=tests/fixtures/t133_fast_direct_variables/formal.f；
  gold-root=tests/fixtures/t133_fast_direct_variables；
  gate-filelist=/private/tmp/t133-main-review.eHnWfP/gate/formal.f；
  gate-root=/private/tmp/t133-main-review.eHnWfP/gate；top=t133_fast_direct_variables_formal；seq=5；
  positive exact command exit 0，JSON {"formal_equivalence":"pass","top":"t133_fast_direct_variables_formal","seq":5}；
  fixed negative gate=/private/tmp/t133-main-review.eHnWfP/negative，唯一 `^ 8'h3` 改为 `| 8'h3`，
  exit 1，含2个 unproven 与 equiv_status -assert。
next_step: 按 Git 流程提交并推送 delivery/fast-local-signals；服务器使用新空 OUT 重跑 StCache FAST 和 gate audit
```
