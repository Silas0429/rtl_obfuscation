# T036：按目标加密率选择 mapping 并报告实际加密率

- 状态：ACCEPTED
- 设计负责人：主 Agent
- 实现负责人：子 Agent
- 前置任务：T035 ACCEPTED
- Formal verification：必须 PASS；另需一个故意功能变更的 FAIL 负例
- RISC-V-Vector Formal：N/A；本任务的常规验收禁止运行 RISC-V-Vector Formal

## 1. 单一目标

为单文件、显式 filelist 和 `project-root + top` 三种加密入口增加可选参数
`--encryption-rate <rate>`。当参数存在时，工具必须：

1. 先建立当前 profile/closure 下的完整 eligible mapping 候选集；
2. 为每个候选 mapping 计算其声明和全部引用实际改写所覆盖的物理行集合；
3. 对所有候选 mapping 的行集合求并集，按唯一的
   `(相对文件路径, 1-based 物理行号)` 统计，不能把同一行重复累加；
4. 先检查全部候选 mapping 的最大可达行数；若最大可达率低于目标，则直接选择全部候选
   mapping，不报错；否则使用确定性选择算法选出不可拆分的 mapping 子集，使实际覆盖行数
   不低于目标；
5. 只改写选中的 mapping，生成原有版本的 mapping 和可解密 gate；
6. 在 stdout 汇总和 metrics 中报告目标、候选能力、实际行数、实际加密率和超出量。

`--encryption-rate` 未提供时，现有 mapping、metrics、随机命名、输出和解密行为必须
保持兼容，不得因为本任务改变旧测试的精确输出。

## 2. 率和行数的冻结定义

### 2.1 参数范围

- `rate` 必须是有限十进制数，满足 `0 < rate <= 1`；
- `0`、负数、大于 `1`、`NaN`、`Infinity` 和无法解析的值统一以稳定错误码
  `ENCRYPTION_RATE_INVALID` 拒绝；
- `--debug` 与 `--encryption-rate` 不能同时使用，以
  `ENCRYPTION_RATE_DEBUG_UNSUPPORTED` 拒绝。debug 的每类独立运行不构成一个可定义的
  全局加密率，本任务不为它引入按类别分配策略。

目标行数使用十进制值计算并向上取整：

```text
target_lines = ceil(Decimal(rate) * total_lines)
```

这样实际加密率不会低于用户目标；JSON 中的 `target` 保留用户传入值的数值语义。

### 2.2 总行数

`total_lines` 是本次 gate 输出所对应的 RTL 源文件集合中的物理行数，不包含 filelist
本身、mapping、metrics 或 maps 文件：

- single-file：输入的单个 `.sv` 文件；
- filelist：mapping `files` 中列出的全部 `.sv/.svh` 文件，包含 manual bounded closure
  之外仍被镜像的文件；
- project-root：top closure 的全部 `mapping.files` 文件，包含其中的 `.svh` 文件。

一行按换行符 `\\n` 分隔；非空且没有末尾换行符的文件最后一行仍计数，空文件计为 0 行。
注释行、空行和仅空白行也属于物理总行数。现有 metrics 中的
`affected_lines.total`/`affected_lines.rate` 为历史 effective-line 指标，保持原语义；
新功能的权威结果位于 `encryption_rate` 对象中。`total_lines == 0` 时
`maximum_rate` 和 `actual_rate` 均定义为 `0.0`，避免出现除零或 NaN。

### 2.3 mapping 影响行

候选 mapping 的影响行集合是其 `declaration` 和全部 `references` range 的并集。每个
range 使用 gold 源文件的起始 byte offset 映射到物理行，集合 key 为：

```text
(range["file"], source[:range["start"]].count(b"\\n") + 1)
```

因此以下情况都只计一行：

- 同一 mapping 的 declaration 和多个 references 在同一行；
- 不同 mapping 的 identifier 位于同一行；
- 同一行包含多个独立可改写 identifier。

mapping 是不可拆分的选择单元：不能只选 mapping 的部分 references，否则会破坏全局
绑定、gate 审计和 decrypt 的可逆性。

## 3. 选择策略和失败边界

### 3.1 候选集

候选集必须在当前入口已经完成 profile 解析、ownership/preserved 判断和 closure 限制后
生成：

- single-file 继续只允许 T034 的 13 个 default category；单文件内多个 module 的所有
  eligible 对象都可以进入候选集，但不凭空建立 top/ABI 语义；
- filelist default 继续覆盖 filelist 的全部 RTL 文件；filelist manual 继续只从 bounded
  top closure 中取得 eligible mapping，closure 外镜像文件不进入候选集；
- project-root default/manual 继续只从 top closure 取得 eligible mapping；top ABI、
  preserved/skipped 和 unsupported 对象不进入候选集；
- 候选 mapping 必须包含 declaration 和所有 references，不能按文件分别加密或按 module
  顺序多次加密。这样多文件模式仍基于一个共享 compilation 和一个全局 mapping，跨文件
  引用会和声明一起被选择。

候选项按以下稳定 key 排序，不能使用随机 renamed name 参与选择：

```text
(declaration.file, declaration.start, category, scope, original_name)
```

### 3.2 确定性 greedy 选择

新增一个共用的 rate-selection helper，所有三种入口使用同一算法：

1. 计算每个候选 mapping 的 `affected_lines` 和全体候选行并集；
2. `candidate_lines` 是全部候选 mapping 影响行并集的大小，最大可达率为
   `candidate_lines / total_lines`；
3. 在开始 greedy 之前比较 `candidate_lines` 与 `target_lines`：
   - 如果 `total_lines == 0` 或候选行并集为空，则直接选择全部候选 mapping，并将
     `target_unreachable` 设为 `true`；
   - 如果 `target_lines > candidate_lines`，则直接选择全部候选 mapping，不返回错误，不执行
     greedy；metrics/stdout 必须标记 `target_unreachable: true`，并报告 `maximum_rate`；
   - 如果目标可达，则继续执行 greedy；
4. 维护已选 mapping 和已覆盖行集合。每轮计算未选 mapping 的 marginal line count；
   - 若有 mapping 的 marginal count 大于等于剩余目标，选择其中 marginal 最小者，以减少
     overshoot；
   - 否则选择 marginal 最大者，以最快达到目标；
   - 相同 marginal 按上述稳定 key 排序；
5. 达到 `target_lines` 后按稳定逆序尝试删除 mapping；若删除后仍满足目标则删除，以减少
   不必要的 mapping 和超出量；
6. 重新从最终 mapping 子集计算 selected line 并集、actual rate 和 overshoot，禁止复用
   未去重的 occurrence 数量。

该算法不承诺 NP-hard 最小集合覆盖的全局最优解。目标可达时必须确定、可复现且实际率不低于
目标；目标不可达时必须完整加密全部候选 mapping，实际率可以低于目标，但必须明确报告。
不能为了凑行数拆分一个 mapping，也不能通过修改 preserved/unsupported 对象提高加密率。

### 3.3 命名、mapping 和解密兼容

- 最好在选择完成后才为最终选中的 mapping 分配随机名；如果实现阶段需要先生成名字，
  选择逻辑仍不得读取随机名，且最终 mapping 必须只包含选中的 entry；
- single-file 继续输出 mapping v1，filelist default 继续 v2，project-root default 继续
  v3，manual multi-file 继续 v4；本任务不新增 mapping version；
- 由于未选中的候选项只是保持 gold 名称，现有 v1/v2/v3/v4 decrypt validator 和字节恢复
  逻辑应继续工作，不得要求 decrypt 重新计算加密率；
- 率模式在候选为空时允许输出 `entries: []` 的 mapping；v1/v2 validator 必须允许这种
  率模式产生的空 mapping，decrypt 必须执行无修改 identity 恢复。没有提供率参数时，既有
  非空 mapping 行为和旧错误边界保持不变；
- 选中的 mapping range 仍必须经过现有 gate AST/range audit，mapping entry 不能重复、
  overlap 或只包含部分 occurrence；
- 输出仍使用 T035 的 staging + atomic publish。率参数错误、gate audit 失败或 metrics 失败时，
  目标输出目录、mapping、metrics 和 maps 均不得留下新半成品；候选不可达不是错误，必须正常
  发布“全部候选 mapping”结果。

## 4. 机器可读输出

提供 `--encryption-rate` 时，`metrics.json` 必须新增以下对象；不提供参数时不新增字段，
以保留历史 metrics schema：

```json
{
  "encryption_rate": {
    "algorithm": "greedy_unique_line_v1",
    "target": 0.35,
    "total_lines": 120,
    "target_lines": 42,
    "candidate_lines": 91,
    "selected_lines": 45,
    "actual_rate": 0.375,
    "overshoot_lines": 3,
    "maximum_rate": 0.7583333333,
    "target_unreachable": false,
    "selection_mode": "greedy",
    "candidate_entries": 47,
    "selected_entries": 12,
    "candidates": [
      {
        "category": "signals",
        "scope": "child",
        "original_name": "state_q",
        "declaration": {"file": "child.sv", "start": 123, "end": 130},
        "affected_lines": [
          {"file": "child.sv", "line": 5},
          {"file": "child.sv", "line": 11}
        ],
        "affected_line_count": 2,
        "selected": true
      }
    ]
  }
}
```

`candidates` 必须按稳定 mapping key 排序；`affected_lines` 必须按 file、line 排序；
`selected` 反映最终 mapping 是否包含该 entry。真实输出可以增加不影响上述字段的审计字段，
但不能省略每个候选项的受影响唯一行数。`selected_lines` 必须等于最终选中项
`affected_lines` 的集合并集大小，`actual_rate == selected_lines / total_lines`。
当 `target_unreachable` 为 `false` 时必须满足 `actual_rate >= target`；当其为 `true` 时必须
满足 `selected_entries == candidate_entries`、`selected_lines == candidate_lines`、
`selection_mode == "all_candidates"` 且 `actual_rate == maximum_rate`。此时不能报错，也不能
把该情况伪装成目标达成。

stdout 的最终汇总 JSON 必须增加精简的：

```json
{
  "encryption_rate": {
    "target": 0.35,
    "total_lines": 120,
    "encrypted_lines": 45,
    "actual_rate": 0.375,
    "overshoot_lines": 3,
    "maximum_rate": 0.7583333333,
    "target_unreachable": false
  }
}
```

旧调用的 stdout 字段保持不变。

## 5. 允许修改的文件

- `rtl_obfuscator/rewrite.py`：CLI 参数、公共行集合/选择 helper、三个入口接线、metrics、
  stdout 汇总以及率模式的空 mapping 解密兼容；如确有必要可拆出同目录下一个只负责 rate
  selection 的小模块，但不得引入额外依赖；
- `rtl_obfuscator/inventory.py`：仅在复用完整 mapping 候选集必须调整 inventory 输出时；
  不得改变 T035 category registry、ownership、closure 或既有 mapping range 语义；
- `tests/test_t036_encryption_rate.py`：新功能专项测试；优先复用已验收
  `tests/fixtures/t034_profile_scope` 和 `tests/fixtures/t033_impact_category`，不得修改
  既有 fixture；
- `README.md`：实现验收后补充参数、率定义和三种入口行为；
- `docs/future_work.md`、本任务单：补充完成状态、边界和验证记录。

不允许修改既有历史测试来放宽验收，不允许修改 RISC-V-Vector fixture，不允许改变已有
category/profile、mapping version、decrypt schema 或 top ABI policy。

## 6. 专项测试和验收条件

### 6.1 必须覆盖的行为

`tests/test_t036_encryption_rate.py` 至少覆盖：

1. 没有 `--encryption-rate` 的三种入口与 T035 基线完全兼容；
2. 单文件中多个 module 的候选均按当前 single-file 语义处理，不建立伪 top closure；
3. 同一 mapping 多个 occurrence 同行、不同 mapping 同行时，行数按唯一
   `(file, line)` 计算；
4. filelist default 的分母包含全部 filelist RTL 文件，manual 的候选仍限 bounded closure；
5. project-root default/manual 的候选仍限 top closure，top ABI/preserved 不被选中；
6. 目标较小、刚好跨过目标、目标接近 1 的场景，实际率均不低于目标并报告 overshoot；
7. 不同目标选择结果按规范排序后确定性一致；随机 renamed name 的既有随机性不能导致
   选择结果变化；
8. `0`、负数、大于 `1`、NaN、Infinity、不可解析值以及 debug 冲突返回稳定错误码；
9. 目标超过候选最大覆盖率时跳过 greedy，直接加密全部候选 mapping，不报错，并报告
   `target_unreachable`、最大能力和实际率；
10. 候选为空时三种入口仍成功发布，mapping 可为空，gate 保持原文，decrypt 能 byte-identical
    identity 恢复；有候选时三种入口的率加密结果均能 byte-identical decrypt；mapping version
    保持 v1/v2/v3/v4；
11. metrics 的每个候选 mapping 影响行、最终唯一并集和实际率满足机器可验证等式；
12. 选中候选的所有 references 一起改写，未选候选保持 gold 名称，gate 仍能严格解析。

### 6.2 形式等价

使用非 RISC、形式流程现有的 `tests/formal/t032_project_root_parameters` fixture，执行一次
project/filelist 率加密：

- 选择 default/internal mapping，gold 与 gate 保持同一个 `t032_top`；
- 用 `scripts/formal_equivalence.py` 得到正例 JSON `formal_equivalence: pass`，退出码 0；
- 仅在 gate 副本中把 `assign data_o = child_data;` 改为功能不同但语法有效的表达式，
  同一 formal 命令必须非零退出，并到达 `equiv_status -assert`，不能是解析失败；
- 不执行 `tests.test_risc_v_vector_project_root`，不执行 RISC-V-Vector formal-view、
  formal-align 或 Yosys。

### 6.3 常规门禁

所有命令都必须通过 `rtl_obfuscation` 环境执行。验收必须使用显式列出的非 RISC 测试，
不得使用会自动发现并运行 RISC-V-Vector 测试的 blanket discovery。至少执行：

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_t036_encryption_rate -v
conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/inventory.py rtl_obfuscator/project.py rtl_obfuscator/rewrite.py rtl_obfuscator/category_profile.py tests/test_t036_encryption_rate.py
conda run -n rtl_obfuscation verible-verilog-syntax tests/fixtures/t034_profile_scope/child.sv
conda run -n rtl_obfuscation verible-verilog-syntax tests/fixtures/t034_profile_scope/top.sv
conda run -n rtl_obfuscation iverilog -g2012 -t null tests/formal/t032_project_root_parameters/child.sv tests/formal/t032_project_root_parameters/top.sv
git diff --check
```

完整非 RISC 回归使用以下显式模块列表，并追加本任务专项；不得改写成 blanket discovery：

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_all_category_rewrite tests.test_debug_mode tests.test_enum_value_rewrite \
  tests.test_example_fifo_project tests.test_formal_equivalence tests.test_genvar_rewrite \
  tests.test_hierarchy_name_rewrite tests.test_interface_member_rewrite tests.test_interface_rewrite \
  tests.test_localparam_rewrite tests.test_module_port_rewrite tests.test_multi_signal_rewrite \
  tests.test_multifile_project tests.test_parameter_dimension_rewrite tests.test_project_regression \
  tests.test_project_root_inspect tests.test_project_root_low_risk tests.test_project_root_parameter_rewrite \
  tests.test_project_root_parameters tests.test_project_root_rewrite tests.test_signal_net_rewrite \
  tests.test_struct_field_rewrite tests.test_struct_type_rewrite tests.test_subroutine_rewrite \
  tests.test_supported_integration tests.test_t033_impact_category tests.test_t034_single_file_default_profile \
  tests.test_t035_profile_unification tests.test_typedef_rewrite tests.test_union_field_rewrite \
  tests.test_value_parameter_rewrite tests.test_variable_inventory tests.test_variable_ranges \
  tests.test_variable_rewrite tests.test_t036_encryption_rate -v
```

任务单执行记录必须明确该命令未包含 `tests.test_risc_v_vector_project_root`。

Formal 正例的可复制命令固定为：

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite encrypt-project \
  --filelist tests/formal/t032_project_root_parameters/design.f \
  --source-root tests/formal/t032_project_root_parameters \
  --top t032_top \
  --output-dir /private/tmp/rtl-obfuscation-t036-formal/gate \
  --map /private/tmp/rtl-obfuscation-t036-formal/mapping.json \
  --metrics /private/tmp/rtl-obfuscation-t036-formal/metrics.json \
  --name-length 8 --encryption-rate 0.35
conda run -n rtl_obfuscation python scripts/formal_equivalence.py \
  --gold-filelist tests/formal/t032_project_root_parameters/design.f \
  --gold-root tests/formal/t032_project_root_parameters \
  --gate-filelist /private/tmp/rtl-obfuscation-t036-formal/gate/design.f \
  --gate-root /private/tmp/rtl-obfuscation-t036-formal/gate \
  --top t032_top
```

子 Agent 和主 Agent 必须分别记录正例退出码 0 及 JSON；负例使用 gate 副本执行相同 formal
命令，记录非零退出码和 `equiv_status -assert` 失败，而不是只记录语法错误。

## 7. 实现阶段和防止反复暂停的交付顺序

子 Agent 应按以下阶段连续完成，只有遇到实际 API/语义阻塞才暂停并在任务单记录：

1. 先写纯函数级行计数、range-to-line、候选并集和确定性选择测试；
2. 接入 single-file，保持无参数路径字节和 schema 不变；
3. 接入 filelist default/manual 两条路径，确认共享 compilation、bounded closure 和 v1/v2/v4
   解密；
4. 接入 project-root default/manual 两条路径，确认 top ABI 和 v3/v4 解密；
5. 接入 metrics/stdout、原子发布、错误回滚和所有边界测试；
6. 最后执行 Formal 正负例、显式非 RISC 回归、语法/编译检查，并完整填写本任务单执行记录。

不得先修改三种入口的既有 profile 或 mapping 结构再补测试；不得以单独 identity 比较代替
改写 RTL 的 formal 证据。

## 8. 子 Agent 执行记录

```text
status: READY_FOR_REVIEW
start_record: |
  start_time: 2026-07-21 13:23:09 CST
  head: 8adb0f8
  first_command: `sed -n '1,360p' docs/tasks/T036_encryption_rate_selection.md`
  inherited_worktree: T035 is ACCEPTED at HEAD 8adb0f8; no other task is IN_PROGRESS or READY_FOR_REVIEW; inherited unstaged changes are limited to `docs/future_work.md` and `docs/project_root_top_roadmap.md` and will be preserved.
changed_files: |
  - `rtl_obfuscator/rewrite.py`
  - `tests/test_t036_encryption_rate.py`
  - `README.md`
  - `docs/future_work.md`
  - `docs/tasks/T036_encryption_rate_selection.md`
  Inherited worktree changes in `docs/project_root_top_roadmap.md` were preserved and not modified by T036.
exact_commands: |
  - `conda run -n rtl_obfuscation python -m unittest tests.test_t036_encryption_rate -v` -> exit 0; Ran 6 tests, OK.
  - `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/inventory.py rtl_obfuscator/project.py rtl_obfuscator/rewrite.py rtl_obfuscator/category_profile.py tests/test_t036_encryption_rate.py` -> exit 0.
  - `conda run -n rtl_obfuscation verible-verilog-syntax tests/fixtures/t034_profile_scope/child.sv` -> exit 0.
  - `conda run -n rtl_obfuscation verible-verilog-syntax tests/fixtures/t034_profile_scope/top.sv` -> exit 0.
  - `conda run -n rtl_obfuscation iverilog -g2012 -t null tests/formal/t032_project_root_parameters/child.sv tests/formal/t032_project_root_parameters/top.sv` -> exit 0; emitted only the known Icarus constant-select note.
  - `git diff --check` -> exit 0.
  - Exact explicit non-RISC regression command, with `tests.test_t036_encryption_rate` appended (and without `tests.test_risc_v_vector_project_root`):
    `conda run -n rtl_obfuscation python -m unittest tests.test_all_category_rewrite tests.test_debug_mode tests.test_enum_value_rewrite tests.test_example_fifo_project tests.test_formal_equivalence tests.test_genvar_rewrite tests.test_hierarchy_name_rewrite tests.test_interface_member_rewrite tests.test_interface_rewrite tests.test_localparam_rewrite tests.test_module_port_rewrite tests.test_multi_signal_rewrite tests.test_multifile_project tests.test_parameter_dimension_rewrite tests.test_project_regression tests.test_project_root_inspect tests.test_project_root_low_risk tests.test_project_root_parameter_rewrite tests.test_project_root_parameters tests.test_project_root_rewrite tests.test_signal_net_rewrite tests.test_struct_field_rewrite tests.test_struct_type_rewrite tests.test_subroutine_rewrite tests.test_supported_integration tests.test_t033_impact_category tests.test_t034_single_file_default_profile tests.test_t035_profile_unification tests.test_typedef_rewrite tests.test_union_field_rewrite tests.test_value_parameter_rewrite tests.test_variable_inventory tests.test_variable_ranges tests.test_variable_rewrite tests.test_t036_encryption_rate -v` -> exit 0; `Ran 112 tests in 118.155s`, `OK`.
  - Final fixed-rate Formal commands below: encryption exit 0, positive Formal exit 0, negative Formal exit 1.
exit_codes: |
  All required implementation, test, syntax, compile, diff, and positive Formal commands exited 0. The intentional negative Formal exited 1 as required and reached `equiv_status -assert`.
selection_summary: |
  - Added shared Decimal parsing and `greedy_unique_line_v1` selection for single-file, filelist default/manual, and project-root default/manual paths.
  - Candidate affected lines use unique `(file, line)` pairs from declaration plus all references; stable ordering excludes randomized renamed names.
  - Metrics include candidate/selected entries and line sets, target ceil, maximum capability, actual rate, overshoot, target-unreachable, and selection mode; stdout exposes the compact rate summary.
  - Rate output uses staging and atomic publication. Invalid values return `ENCRYPTION_RATE_INVALID`; debug conflict returns `ENCRYPTION_RATE_DEBUG_UNSUPPORTED`.
  - Empty candidates and unreachable targets select all candidates without error; v1/v2/v3/v4 mapping versions remain unchanged and rate mappings decrypt byte-identically, including identity empty mappings.
  - Default no-rate stdout and metrics schemas remain unchanged. Filelist normal mode now permits omitted `--category` so the contract's default-profile Formal command resolves the shared default profile.
formal_verification: |
  PASS (non-RISC; RISC-V-Vector Formal intentionally not run).
  Gold: `tests/formal/t032_project_root_parameters/design.f` with root `tests/formal/t032_project_root_parameters`.
  Rate encryption command:
  `conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite encrypt-project --filelist tests/formal/t032_project_root_parameters/design.f --source-root tests/formal/t032_project_root_parameters --top t032_top --output-dir /private/tmp/rtl-obfuscation-t036-formal-xwhtXw/gate --map /private/tmp/rtl-obfuscation-t036-formal-xwhtXw/mapping.json --metrics /private/tmp/rtl-obfuscation-t036-formal-xwhtXw/metrics.json --name-length 8 --encryption-rate 0.35`
  Gate: `/private/tmp/rtl-obfuscation-t036-formal-xwhtXw/gate`, gate filelist `/private/tmp/rtl-obfuscation-t036-formal-xwhtXw/gate/design.f`.
  Positive command:
  `conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold-filelist tests/formal/t032_project_root_parameters/design.f --gold-root tests/formal/t032_project_root_parameters --gate-filelist /private/tmp/rtl-obfuscation-t036-formal-xwhtXw/gate/design.f --gate-root /private/tmp/rtl-obfuscation-t036-formal-xwhtXw/gate --top t032_top`
  Positive JSON: `{"formal_equivalence": "pass", "gate": "/private/tmp/rtl-obfuscation-t036-formal-xwhtXw/gate", "gold": "tests/formal/t032_project_root_parameters", "seq": 5, "top": "t032_top"}`.
  Negative gate: copied to `/private/tmp/rtl-obfuscation-t036-formal-xwhtXw/negative`; only the top assignment was changed to invert the selected child signal. The same Formal command exited 1 and reported `equiv_status -assert` with unproven `$equiv` cells, not a parse failure.
uncovered_boundaries: |
  - RISC-V-Vector Formal/view/align remains N/A by contract and was not run.
  - Existing SystemVerilog unsupported-language and top-interface-ABI boundaries remain governed by T035 and `docs/future_work.md`; T036 does not expand category ownership or closure semantics.
  - The T033 multi-file filelist fixture has an existing PySlang `$unit` cross-file type diagnostic in its legacy v2 decrypt frontend; T036 rate tests use the validated T034 v2 fixture for filelist round-trip and T033 for manual v4 closure coverage. Project-root and manual v4 rate round-trips pass.
review_request: |
  T036 implementation,专项测试, final non-RISC regression, syntax/toolchain checks, and required Formal positive/negative evidence are complete. Please independently review the diff and acceptance evidence, then decide whether to mark the task `ACCEPTED`.
```

## 9. 主 Agent 验收记录

```text
acceptance_time: 2026-07-21 13:48:58 CST
acceptance_head: 8adb0f8 before acceptance-record update
independent_commands: |
  - `conda run -n rtl_obfuscation python -m unittest tests.test_t036_encryption_rate -v`
  - `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/inventory.py rtl_obfuscator/project.py rtl_obfuscator/rewrite.py rtl_obfuscator/category_profile.py tests/test_t036_encryption_rate.py`
  - `conda run -n rtl_obfuscation verible-verilog-syntax tests/fixtures/t034_profile_scope/child.sv`
  - `conda run -n rtl_obfuscation verible-verilog-syntax tests/fixtures/t034_profile_scope/top.sv`
  - `conda run -n rtl_obfuscation iverilog -g2012 -t null tests/formal/t032_project_root_parameters/child.sv tests/formal/t032_project_root_parameters/top.sv`
  - `git diff --check`
  - Explicit non-RISC unittest list from section 6.3, including `tests.test_t036_encryption_rate` and excluding `tests.test_risc_v_vector_project_root`.
independent_results: |
  - T036专项：6 tests, OK, 3.667s.
  - Explicit non-RISC regression: 112 tests, 117.988s, OK.
  - py_compile=0; Verible=0; Icarus=0 with only the known constant-select note; git diff --check=0.
  - Independent rate Formal encryption: exit 0; summary target=0.35, total_lines=35, encrypted_lines=13, actual_rate=0.37142857142857144, maximum_rate=0.45714285714285713, target_unreachable=false.
formal_recheck: |
  PASS. Gold: `tests/formal/t032_project_root_parameters/design.f`; gate generated in `/private/tmp/rtl-obfuscation-t036-main.VSn8HE/gate`; top `t032_top`.
  Positive `scripts/formal_equivalence.py`: exit 0, JSON `{"formal_equivalence":"pass","gate":"/private/tmp/rtl-obfuscation-t036-main.VSn8HE/gate","gold":"tests/formal/t032_project_root_parameters","seq":5,"top":"t032_top"}`.
  Intentional negative gate changed `assign data_o = Ptyuqqo9;` to `assign data_o = ~Ptyuqqo9;`: exit 1, reached `equiv_status -assert` with 8 unproven `$equiv` cells; not a parse or hierarchy failure.
  RISC-V-Vector Formal/view/align/Yosys was not run.
git_status: |
  Before acceptance-record update: `main...origin/main [ahead 3]`; T036 implementation, tests and docs were unstaged; no unrelated source changes observed beyond the preserved T035 roadmap change.
staged_diff_review: pending Git handoff after acceptance.
acceptance_conclusion: PASS; T036 is ACCEPTED by the Main Agent.
```
