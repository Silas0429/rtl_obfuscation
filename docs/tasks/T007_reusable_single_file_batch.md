# T007：高复用单文件批次

- 状态：`ACCEPTED`
- 设计负责人：主 Agent
- 实现负责人：子 Agent
- 前置任务：T005 已达到 `ACCEPTED`；T006 按开发者要求暂缓

## 1. 批次目标

一次完成并统一验收三个高度复用的单文件子项：

1. T007-A：支持单文件多个 mapping entry，并正式验证内部 `logic`、`reg`、`wire`、`tri`。
2. T007-B：`parameters` 类别加入 module `localparam`。
3. T007-C：加入组合逻辑中的 `enum_values`。

三个子项共用现有随机名称、semantic symbol、source range、byte edit、mapping、decrypt、metrics 和 Yosys formal 流水线。T006、genvar、function/task 和多文件均不属于本批次。

## 2. 固定输入与机器输出

| 子项 | gold | category | top | mapping entries | modified tokens |
| --- | --- | --- | --- | ---: | ---: |
| A | `tests/fixtures/t007_multi_signal.sv` | `signals` | `t007_multi_signal` | 4 | 12 |
| B | `rtl_samples/05_case_statement.sv` | `parameters` | `sample05_case_statement` | 4 | 8 |
| C | `tests/fixtures/t007_enum_values.sv` | `enum_values` | `t007_enum_values` | 3 | 7 |

每个子项固定输出到 `/tmp/rtl_obfuscation_t007/<name>/`：

```text
gate.sv
restored.sv
mapping.json
metrics.json
```

其中 `<name>` 依次为 `signals`、`localparams`、`enums`。所有命令使用 `--name-length 8`，CLI 必须创建不存在的输出目录。

encrypt stdout 分别必须为：

```json
{"files": 1, "mapping_entries": 4, "modified_tokens": 12}
{"files": 1, "mapping_entries": 4, "modified_tokens": 8}
{"files": 1, "mapping_entries": 3, "modified_tokens": 7}
```

对应 decrypt stdout 的计数必须相同。

## 3. 固定 ranges

### T007-A signals

```text
logic_value: declaration [185,196), references [373,384), [419,430)
legacy_reg:  declaration [208,218), references [406,416), [463,473)
wire_value:  declaration [230,240), references [275,285), [330,340)
tri_value:   declaration [252,261), references [318,327), [387,396)
```

mapping 顺序必须为 `logic_value`、`legacy_reg`、`wire_value`、`tri_value`；ports 不得进入 mapping。

### T007-B localparams

```text
OP_ADD: declaration [264,270), reference [499,505)
OP_SUB: declaration [307,313), reference [557,563)
OP_AND: declaration [350,356), reference [615,621)
OP_OR:  declaration [393,398), reference [673,678)
```

四个 entry 的 category 都是 `parameters`，顺序按声明位置。普通 signal 和 ports 不得进入 mapping。

### T007-C enum values

```text
STATE_IDLE: declaration [181,191), reference [348,358)
STATE_RUN:  declaration [201,210), references [389,398), [484,493)
STATE_DONE: declaration [220,230), reference [429,439)
```

三个 entry 的 category 都是 `enum_values`。PySlang collection root 暴露 `TransparentMemberSymbol`；真正被 NamedValueExpression 引用的 target 是其 `wrapped` EnumValueSymbol。

## 4. 固定 metrics

| 子项 | affected lines | symbols | occurrences | leakage | effective coverage |
| --- | --- | --- | --- | --- | --- |
| A | `9/17`, rate `0.5294117647058824` | `4/4`, `1.0` | `12/12`, `1.0` | `0.0` | `1.0` |
| B | `8/22`, rate `0.36363636363636365` | `4/4`, `1.0` | `8/8`, `1.0` | `0.0` | `1.0` |
| C | `7/19`, rate `0.3684210526315789` | `3/3`, `1.0` | `7/7`, `1.0` | `0.0` | `1.0` |

## 5. 最小实现要求

- inventory 增加 `enum_values` 分派；`parameters` 同时收集 module value parameter 和 localparam，仍排除 type parameter。
- enum collector 将 `TransparentMemberSymbol.wrapped` 作为 target，按声明位置去重和排序。
- encrypt 必须先汇总所有 entry 的全部 edits，在原始 source 上全局验证重复、重叠和 expected bytes，再按 start 全局倒序一次应用。禁止逐 entry 修改已变化的 buffer。
- decrypt 必须先为所有 entry 重新收集 gate ranges，再在原始 gate bytes 上全局倒序一次恢复。
- mapping validator 允许并逐条验证多个 entries；拒绝重复 renamed name；每个新名称必须合法、长度等于 `name_length`。不得只校验第一条。
- 保持 version 1 mapping，不增加兼容分支、配置文件、缓存、类框架或新依赖。
- 保留 T001—T005 全部行为。

## 6. 固定 CLI

三个 encrypt 命令：

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite encrypt --input tests/fixtures/t007_multi_signal.sv --output /tmp/rtl_obfuscation_t007/signals/gate.sv --map /tmp/rtl_obfuscation_t007/signals/mapping.json --metrics /tmp/rtl_obfuscation_t007/signals/metrics.json --category signals --name-length 8

conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite encrypt --input rtl_samples/05_case_statement.sv --output /tmp/rtl_obfuscation_t007/localparams/gate.sv --map /tmp/rtl_obfuscation_t007/localparams/mapping.json --metrics /tmp/rtl_obfuscation_t007/localparams/metrics.json --category parameters --name-length 8

conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite encrypt --input tests/fixtures/t007_enum_values.sv --output /tmp/rtl_obfuscation_t007/enums/gate.sv --map /tmp/rtl_obfuscation_t007/enums/mapping.json --metrics /tmp/rtl_obfuscation_t007/enums/metrics.json --category enum_values --name-length 8
```

每个 decrypt 使用对应的 gate、restored 和 mapping 路径。

## 7. 统一验收

联合回归：

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_variable_inventory \
  tests.test_variable_ranges \
  tests.test_variable_rewrite \
  tests.test_signal_net_rewrite \
  tests.test_value_parameter_rewrite \
  tests.test_multi_signal_rewrite \
  tests.test_localparam_rewrite \
  tests.test_enum_value_rewrite
```

每个子项必须满足：

- gate 等于按 mapping 全部 ranges 全局倒序替换得到的期望字节，不得用全局字符串 replace 作为实现。
- restored 与 gold 通过 `cmp -s`。
- PySlang、`verible-verilog-syntax --lang=sv`、`iverilog -g2012 -t null -s <top>` 全部通过。
- 主 Agent 和子 Agent 都分别运行对应 Yosys 命令并得到 PASS JSON：

```sh
conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold tests/fixtures/t007_multi_signal.sv --gate /tmp/rtl_obfuscation_t007/signals/gate.sv --top t007_multi_signal
conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold rtl_samples/05_case_statement.sv --gate /tmp/rtl_obfuscation_t007/localparams/gate.sv --top sample05_case_statement
conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold tests/fixtures/t007_enum_values.sv --gate /tmp/rtl_obfuscation_t007/enums/gate.sv --top t007_enum_values
```

mapping 负测至少覆盖：第二个或最后一个 entry schema 损坏时 decrypt 非零退出；两个 entries 使用重复 renamed name 时 decrypt 非零退出。

## 8. 本批次明确不包含

- T006 type parameter、genvar、function/task/argument。
- 多文件、filelist、include、define 或 output directory tree。
- named parameter override、dimension reference、defparam。
- enum scope reference、assignment pattern、跨文件 enum。
- declaration-only target、零 eligible target 或通用 plaintext tokenization。
- 修改 formal 脚本、固定 fixtures 或既有 RTL 样例。

## 9. 允许修改的文件

```text
rtl_obfuscator/inventory.py
rtl_obfuscator/rewrite.py
tests/test_multi_signal_rewrite.py
tests/test_localparam_rewrite.py
tests/test_enum_value_rewrite.py
docs/tasks/T007_reusable_single_file_batch.md
```

不得修改其他文件。两个 T007 fixtures 和 `rtl_samples/05_case_statement.sv` 均为只读输入。

## 10. 子 Agent 文档流程

1. 开始前将本任务从 `READY` 改为 `IN_PROGRESS` 并记录开始时间。
2. 三个子项可以连续实现，但不得跳出本合同；发现任一 API 偏差立即记录。
3. 完成后记录全部变更文件、8 项回归、3 组 CLI、3 组语法/编译、3 个 formal JSON、负测和未覆盖边界。
4. 任一子项 formal 失败则整个批次不得申请验收。
5. 全部门禁通过后设置为 `READY_FOR_REVIEW`；不得设置 `ACCEPTED`，不得 commit 或 push。

## 11. Formal verification（子 Agent 完成时填写）

```text
formal_verification: PASS

signals:
gold: tests/fixtures/t007_multi_signal.sv
gate: /tmp/rtl_obfuscation_t007/signals/gate.sv
top: t007_multi_signal
command: conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold tests/fixtures/t007_multi_signal.sv --gate /tmp/rtl_obfuscation_t007/signals/gate.sv --top t007_multi_signal
exit_code: 0
result: {"formal_equivalence": "pass", "gate": "/private/tmp/rtl_obfuscation_t007/signals/gate.sv", "gold": "/Users/lufengchi/Desktop/workspace/rtl_obfuscation/tests/fixtures/t007_multi_signal.sv", "seq": 5, "top": "t007_multi_signal"}

localparams:
gold: rtl_samples/05_case_statement.sv
gate: /tmp/rtl_obfuscation_t007/localparams/gate.sv
top: sample05_case_statement
command: conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold rtl_samples/05_case_statement.sv --gate /tmp/rtl_obfuscation_t007/localparams/gate.sv --top sample05_case_statement
exit_code: 0
result: {"formal_equivalence": "pass", "gate": "/private/tmp/rtl_obfuscation_t007/localparams/gate.sv", "gold": "/Users/lufengchi/Desktop/workspace/rtl_obfuscation/rtl_samples/05_case_statement.sv", "seq": 5, "top": "sample05_case_statement"}

enum_values:
gold: tests/fixtures/t007_enum_values.sv
gate: /tmp/rtl_obfuscation_t007/enums/gate.sv
top: t007_enum_values
command: conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold tests/fixtures/t007_enum_values.sv --gate /tmp/rtl_obfuscation_t007/enums/gate.sv --top t007_enum_values
exit_code: 0
result: {"formal_equivalence": "pass", "gate": "/private/tmp/rtl_obfuscation_t007/enums/gate.sv", "gold": "/Users/lufengchi/Desktop/workspace/rtl_obfuscation/tests/fixtures/t007_enum_values.sv", "seq": 5, "top": "t007_enum_values"}
```

## 12. 执行记录（子 Agent 更新）

- 2026-07-13 14:21:28 CST：子 Agent 已完整阅读 T007 合同、任务流程与 formal 验证规范；任务由 `READY` 更新为 `IN_PROGRESS`，开始实施 T007-A/B/C。
- 2026-07-13 14:28:14 CST：完成三子项实现与全部统一门禁；任务更新为 `READY_FOR_REVIEW`，未 commit、未 push。

## 13. 偏差或阻塞（子 Agent 更新）

- 无阻塞。PySlang 11 实际 API 与合同一致：collection root 提供 `TransparentMemberSymbol`，其 `wrapped` 为表达式引用绑定的 `EnumValueSymbol`。
- 未扩展合同边界；多文件、T006、genvar、function/task、named override、dimension/defparam 与 enum scope/pattern 均未实现。

## 14. 交付证据（子 Agent 更新）

- 变更文件：`rtl_obfuscator/inventory.py`、`rtl_obfuscator/rewrite.py`、三份 T007 测试以及本任务单；未修改 fixtures、RTL 样例、规划或 formal 脚本。
- 第 7 节八项联合回归：退出码 `0`，`Ran 8 tests in 0.896s`，`OK`。
- 三组 encrypt stdout：依次为 `{"files": 1, "mapping_entries": 4, "modified_tokens": 12}`、`4/8`、`3/7`；三组 decrypt stdout 与其分别相同。
- 三组 restored 与 gold 的 `cmp -s` 均退出码 `0`；固定 ranges、entry 顺序和 metrics 由三份黑盒测试逐项断言通过，gate 期望值按 mapping ranges 全局倒序构造。
- 三组 PySlang、`verible-verilog-syntax --lang=sv`、`iverilog -g2012 -t null -s <top>` 均退出码 `0`，无 stdout/stderr。
- 三组 Yosys formal 均退出码 `0` 且 JSON 为 `formal_equivalence=pass`，完整记录见第 11 节。
- mapping 负测由 `tests.test_multi_signal_rewrite.MultiSignalRewriteCliTest.test_multi_signal_encrypt_decrypt_and_mapping_validation` 执行真实 decrypt：第二个 entry 缺少 `references` 与最后一个 entry 复用首个 `renamed_name` 均断言非零退出；目标测试 `Ran 1 test`，`OK`。
- `git diff --check` 退出码 `0`；工作区仅包含第 9 节允许文件，未 commit、未 push。

## 15. 主 Agent 验收结果

- 2026-07-13 主 Agent 对整个批次独立验收通过，状态设为 `ACCEPTED`。
- 8 项联合回归退出码为 `0`，`Ran 8 tests`，结果 `OK`；mapping 负测目标用例独立重跑通过。
- 三组 encrypt/decrypt 计数分别精确为 `4/12`、`4/8`、`3/7`。
- signals mapping 顺序、12 个 ranges、全局 edit gate 字节、`9/17` metrics 和 restored 字节均符合合同。
- localparams mapping 顺序、8 个 ranges、全局 edit gate 字节、`8/22` metrics 和 restored 字节均符合合同。
- enum values mapping 顺序、7 个 ranges、全局 edit gate 字节、`7/19` metrics 和 restored 字节均符合合同。
- 三组 PySlang、Verible、Icarus 均退出码 `0`；三组 `cmp -s` 均退出码 `0`。
- 主 Agent 独立运行三次 Yosys formal，均退出码 `0` 且 JSON `formal_equivalence` 为 `pass`：

  ```json
  {"formal_equivalence": "pass", "top": "t007_multi_signal", "seq": 5}
  {"formal_equivalence": "pass", "top": "sample05_case_statement", "seq": 5}
  {"formal_equivalence": "pass", "top": "t007_enum_values", "seq": 5}
  ```

- 冻结 fixtures、RTL 样例和 formal 脚本均未修改；批次边界外的 T006、genvar、subroutine 和多文件能力仍未实现。
