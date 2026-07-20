# T034：单文件/filelist 默认 single-module profile 与 multi/ABI fail-closed

- 状态：`READY`
- 设计负责人：主 Agent
- 实现负责人：子 Agent
- 前置任务：T033 `ACCEPTED`
- 计划文档：[`docs/category_profile_normalization_plan.md`](../category_profile_normalization_plan.md)
- Formal verification：必须 `PASS`；另需一个故意功能变更的 `FAIL` 负例

## 1. 单一目标

把 T033 冻结的 category policy 接入单文件和显式 filelist 工作流，使两种入口使用同一份
`single_module` 默认 profile：

1. `--category all` 只启用 `impact=single_module` 且 `abi=internal` 的默认对象；当前 canonical
   默认 category 为 `signals`、`parameters`、`enum_values`、`genvars`、`functions`、`tasks`、
   `arguments`、`instances`、`generate_blocks`、`typedefs`、`struct_types`、`struct_fields`、
   `union_fields`。
2. 单文件和显式 filelist 的普通模式只能选择默认 profile category；`modules`、`ports`、
   `interfaces`、`interface_instances`、`interface_ports`、`modports` 以及 project-root 概念
   alias `struct`、`interface` 必须以稳定错误码 `CATEGORY_REQUIRES_PROJECT_ROOT` fail-closed。
3. filelist 仍编译、镜像和输出 filelist 中列出的每个文件，不建立 top closure；但只修改默认
   profile 的 source ranges。未实例化但列在 filelist 中的 module 也必须按此规则处理。
4. 单文件和 filelist 的 `--debug` 均只运行 13 个默认 profile category；不能再通过 debug
   绕过 multi/ABI policy。project-root 的手动 category 和 debug 行为保持 T033 前基线，交给
   后续 T035 处理。
5. 保持单文件 mapping v1、filelist mapping v2、现有 decrypt、per-file mapping 和 metrics
   schema 兼容；T034 不引入 mapping v4 或持久化 `skipped` 字段，entry-level mixed skip 和
   mapping v4 audit 属于 T035。

T034 不开放 project-root 的 multi-module/ABI 改写，不实现跨 module parameter/port/interface
重命名，不改变 T033 classification report 的结构，不改变现有 project-root 默认五组。

## 2. 固定输入 fixture

主 Agent 在任务进入 `READY` 前冻结以下输入；子 Agent 不得修改 fixture、filelist 或其 hash：

```text
tests/fixtures/t034_profile_scope/
├── design.f
├── child.sv
├── top.sv
└── unused.sv
```

固定 filelist 顺序和 top：

```text
child.sv
top.sv
unused.sv
top = t034_top
```

固定文件大小与 SHA-256：

```text
child.sv  248 bytes  40a67f3039c64a29d3a0e7ecbfdc0d00c46f0a9f67d5bfa8ee22a9aff7def344
top.sv    197 bytes  b2cbdfdb8c88bd483887eac574919684898ec1adc6b18d3929d5be7115891a22
unused.sv 156 bytes  f89089699d85ed2ea14ed1e9bcdffebdb9f45deb6ed16165576099c6268b24bd
design.f   26 bytes  08c104a449fa27dc0adb11c58f3a4f701ac3f27b4d7abcf0084d5dd4be6b4f06
manifest  d51a7d1a4d938590c05561ece451f70060f96393f3136d3e0f33ba021b416a3e
```

fixture 的 Verible 和 Icarus 基线必须通过：

```sh
for f in tests/fixtures/t034_profile_scope/*.sv; do
  conda run -n rtl_obfuscation verible-verilog-syntax "$f"
done
conda run -n rtl_obfuscation iverilog -g2012 -t null -s t034_top \
  tests/fixtures/t034_profile_scope/child.sv \
  tests/fixtures/t034_profile_scope/top.sv \
  tests/fixtures/t034_profile_scope/unused.sv
```

`unused.sv` 故意不被 `t034_top` 实例化；它用于证明 filelist 模式不是 top-rooted closure。

## 3. 冻结默认 profile oracle

映射中的随机 `renamed_name` 不参与 oracle；测试必须比较 category、scope、original name、
全部 ranges、range bytes、entry 顺序和 occurrence 数量。

### 3.1 单文件 `child.sv --category all`

预期 mapping：version `1`，2 个 entry，6 个 occurrence，所有 entry 都是 `signals/t034_child`：

```text
child_state: declaration 75:86; references 177:188, 217:228; occurrences=3
child_signal: declaration 98:110; references 124:136, 191:203; occurrences=3
```

命令 stdout 的 legacy summary 必须为：

```json
{"files":1,"mapping_entries":2,"modified_tokens":6}
```

### 3.2 显式 filelist `design.f --category all`

预期 mapping：version `2`，`files` 精确为
`["child.sv", "top.sv", "unused.sv"]`，5 个 entry，13 个 occurrence：

```text
signals/t034_child/child_state:
  declaration 75:86; references 177:188, 217:228; occurrences=3
signals/t034_child/child_signal:
  declaration 98:110; references 124:136, 191:203; occurrences=3
signals/t034_top/top_state:
  declaration 73:82; references 142:151, 176:185; occurrences=3
instances/t034_top/u_child:
  declaration 100:107; references none; occurrences=1
signals/t034_unused/unused_state:
  declaration 73:85; references 99:111, 132:144; occurrences=3
```

命令 stdout 的 legacy summary 必须为：

```json
{"files":3,"mapping_entries":5,"modified_tokens":13}
```

所有 range 回读必须等于 `original_name`；gold 与 gate 的差异只能落在上述 13 个 ranges。
`t034_child`、`t034_top`、`t034_unused`、普通 port `data`/`q`/`d` 和 instance type
`t034_child` 必须保持原文；`u_child` 属于默认 `instances` category，必须被改写。

### 3.3 profile 和 scope 不变量

- 单文件 gate 只能有一个输出 `.sv`，filelist gate 必须包含三个输入 `.sv` 和复制后的
  `design.f`。
- filelist 的 `unused.sv` 必须被改写 `unused_state`；不得因为它不在 `t034_top` closure
  中而跳过整个文件。
- 同一输入连续运行时，normalized mapping（去除随机 `renamed_name`）和 metrics 完全一致；
  随机名必须满足长度、唯一性和非关键字约束。
- decrypt 后单文件和 filelist 的每个输出字节必须分别等于 gold；gate 重新 inspect/recompile
  必须通过 PySlang、Verible 和 Icarus。

## 4. multi/ABI fail-closed oracle

下列命令都必须非零退出，stderr 包含稳定 primary code
`CATEGORY_REQUIRES_PROJECT_ROOT`，且在失败前不得创建或覆盖 gate、mapping、metrics 输出：

```text
single-file: modules, ports, interfaces, interface_instances, interface_ports, modports
filelist:    modules, ports, interfaces, interface_instances, interface_ports, modports
single/filelist: struct, interface
```

`--category all --category ports` 等混合选择也必须在写入输出前失败。错误不得依赖自由文本
中的候选名称或文件遍历顺序。project-root 的相同 category 仍由现有手动 profile 处理，T034
不得把它们从 project-root CLI 删除或改为默认启用。

## 5. Formal companion 与正负例

T034 产生 rewritten RTL，必须使用真实加密输出运行 Yosys equivalence；不得用 gold/gold
identity comparison 代替。

Formal 正例：

```text
gold-filelist: tests/fixtures/t034_profile_scope/design.f
gold-root:    tests/fixtures/t034_profile_scope
top:          t034_top
gate-filelist: <temporary-gate>/design.f
gate-root:     <temporary-gate>
```

生成 gate 后运行：

```sh
conda run -n rtl_obfuscation python scripts/formal_equivalence.py \
  --gold-filelist tests/fixtures/t034_profile_scope/design.f \
  --gold-root tests/fixtures/t034_profile_scope \
  --gate-filelist <temporary-gate>/design.f \
  --gate-root <temporary-gate> \
  --top t034_top
```

正例必须退出 `0`，并输出：

```json
{"formal_equivalence":"pass","gold":"tests/fixtures/t034_profile_scope","seq":5,"top":"t034_top"}
```

负例必须从同一个真实 gate 复制一份，只将 `top.sv` 中 `assign q = top_state;` 改成一个
保持语法有效但功能不同的表达式，例如 `assign q = ~top_state;`；再运行同一 formal 命令。
负例必须非零退出，并到达 `equiv_status -assert` 后报告未证明的 `$equiv`，不能以 parse、
hierarchy 或缺少 top 作为“通过”。

## 6. 允许修改与禁止修改

允许修改：

- `rtl_obfuscator/inventory.py`：接入 T033 canonical registry，按 impact/abi 过滤默认 profile；
- `rtl_obfuscator/rewrite.py`：单文件/filelist category 校验、debug profile 和稳定错误码；
- `tests/test_t034_single_file_default_profile.py`：本任务黑盒测试；
- 已有测试中仅用于记录 filelist debug 19 类旧行为的断言；将其更新为 T034 的 13 类 oracle；
- 本任务单的执行记录。

禁止修改：

- `tests/fixtures/t034_profile_scope/**`、T033/T030/T031/T032 fixture、FIFO/RISC-V-Vector
  fixture 或任何既有 formal gold/gate 输入；
- `scripts/formal_equivalence.py`、mapping validator 的既有 v1/v2/v3 解密兼容；
- `rtl_obfuscator/project.py` 的 project-root 行为，除非主 Agent修订合同明确授权；
- README、重命名表、路线图、T035/T036 任务或默认 project-root 五组数量；
- mapping v4、持久化 skipped schema、跨 module parameter/port/interface rewrite；
- commit、push、`ACCEPTED` 状态或创建 T035。

## 7. 验收命令

```sh
conda run -n rtl_obfuscation python -m py_compile \
  rtl_obfuscator/inventory.py rtl_obfuscator/rewrite.py \
  tests/test_t034_single_file_default_profile.py

conda run -n rtl_obfuscation python -m unittest \
  tests.test_t034_single_file_default_profile \
  tests.test_t033_impact_category \
  tests.test_multifile_project \
  tests.test_debug_mode \
  tests.test_example_fifo_project \
  tests.test_project_root_rewrite \
  tests.test_project_root_parameter_rewrite -v

conda run -n rtl_obfuscation python -m unittest discover -s tests -v
git diff --check
```

测试必须程序化断言：fixture manifest、single/filelist mapping oracle、file scope、13 类
debug 数量、稳定拒绝码、无失败输出文件、range bytes、normalized determinism、decrypt
byte identity、PySlang/Verible/Icarus gate recheck、formal 正例和功能负例，以及 project-root
T033/T030/T031/T032 回归。

## 8. READY → READY_FOR_REVIEW 门禁

只有全部满足以下条件才可申请 review：

1. 先将状态从 `READY` 改为 `IN_PROGRESS` 并记录 HEAD、开始时间、首条命令和继承工作区；
2. fixture 文件大小、SHA-256、manifest 和 source-range oracle 与本合同一致；
3. single/filelist `all` 输出严格符合 3.1/3.2，且 `unused.sv` 被处理；
4. 所有 multi/ABI category 和 alias 均以 `CATEGORY_REQUIRES_PROJECT_ROOT` fail-closed，失败不产生输出；
5. debug 仅产生 13 个默认 category，v1/v2/v3 legacy decrypt 回归保持通过；
6. gate 解析、strict reanalysis、metrics、decrypt 和 range audit 全部通过；
7. Formal 正例 PASS、功能负例 FAIL，且负例失败原因不是 parse/hierarchy；
8. 专项测试、完整回归、py_compile、Verible/Icarus 和 `git diff --check` 通过；
9. 记录所有 exact commands、exit codes、summary JSON、formal gold/gate/top/result 和未覆盖边界；
10. 只设置为 `READY_FOR_REVIEW`，不得设置 `ACCEPTED`，不得 commit/push 或创建 T035。

## 9. Formal verification 记录格式

```text
formal_verification: PASS
gold: tests/fixtures/t034_profile_scope/design.f / tests/fixtures/t034_profile_scope
gate: <temporary-gate>/design.f / <temporary-gate>
top: t034_top
command: <exact conda run command>
exit_code: 0
result: {"formal_equivalence":"pass", ...}
negative_command: <exact conda run command>
negative_exit_code: <non-zero>
negative_result: equiv_status -assert reached; unproven $equiv reported
```

## 10. 执行记录

子 Agent 开始后填写：

```text
start_time:
head:
first_command:
inherited_worktree:
changed_files:
exact_commands:
exit_codes:
single_file_summary:
filelist_summary:
debug_summary:
rejection_summary:
mapping_oracle:
decrypt_byte_identity:
formal_verification: PASS
gold:
gate:
top: t034_top
command:
exit_code:
result:
negative_command:
negative_exit_code:
negative_result:
uncovered_boundaries:
```

## 11. 主 Agent 验收结果

待 T034 实现完成并由主 Agent 独立验收后填写；子 Agent 不得提前修改本节为 `ACCEPTED`。
