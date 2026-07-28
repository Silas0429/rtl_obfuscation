# T063：区分 CSV 模块名与作用域

- 状态：ACCEPTED
- 合同版本：1.0
- 设计时间：2026-07-28
- 设计负责人：主 Agent
- 前置任务：T062 `ACCEPTED`
- 起始 HEAD：`d69efe8`
- 任务类型：mapping_table.csv 可读性修正

## 1. 目标

修正 `mapping_table.csv` 的用户可读性，不改变 mapping、metrics、加密选择或 RTL 输出：

- CSV 增加独立的“作用域”列；
- “模块名”始终表示声明所在的最外层 SystemVerilog module；
- `pair_t`、`select_value`、generate block 名称等局部 owner 不得再显示为模块名；
- generate 作用域不得输出完整 `for (...) begin ... end` 语句。

## 2. 固定 CSV 格式

表头固定为：

```text
文件名,模块名,作用域,加密类型,原名,替换后名
```

模块名规则：

- 用声明位置落入的最外层 module 名称；
- 顶层 module 外的 interface/type 等声明使用 `global`；
- module 自身记录的模块名为自身名称。

作用域规则：

| owner | 作用域输出 |
| --- | --- |
| module | `module` |
| type | `type:<名称>` |
| interface | `interface:<名称>` |
| functions | `function:<名称>` |
| tasks | `task:<名称>` |
| 有名 generate | `generate:<名称>` |
| 无名 generate | `generate:line <起始行号>` |
| `$unit` | `global` |

generate 名称只提取 `begin : name` 的短标签；无名 generate 不猜造名称，直接使用 owner
语法范围起始行号。其它未知 owner 必须 fail-closed，不得把完整语法片段写入 CSV。

行顺序、rename record 过滤、UTF-8、换行符和原有文件位置保持 T062 约定。

## 3. 验收边界

必须覆盖：

1. `rtl_samples/11_supported_obfuscation.sv` 中 `pair_t`、`apply_mask`、`select_value`、
   `generate_input` 的模块名/作用域分列且短格式正确；
2. 一个无名 generate 的临时 SystemVerilog 输入，作用域使用 `generate:line N`；
3. CSV header、字段数量、deterministic 行顺序和原有 rename 行数保持；
4. public project FIFO 仍可加密、直接解密，新 gate 仍可恢复；
5. T062 的 31 个定向测试、常规回归、py_compile 和 diff check 继续通过。

本任务只改变可读摘要展示，不新增 RTL 语义；仍独立复跑 T061/T062 compact Formal 正例和单个
`~` 负例，正例必须 pass，负例必须非零且含 `unproven`、`equiv_status -assert`。不得运行
RISC-V-Vector Formal。

## 4. 允许修改

```text
README.md
rtl_obfuscator/rewrite.py
tests/test_cli_vnext_encryption.py
tests/test_public_cli.py
docs/tasks/T063_readable_mapping_scope_columns.md
```

不得修改 RTL fixture、mapping/rate/metrics 核心语义、restore 核心校验、Formal 脚本或历史
任务记录。

## 5. 状态要求

- 实现完成并记录实际命令、结果和边界后，状态才能设为 `READY_FOR_REVIEW`；
- `ACCEPTED` 由主 Agent 独立验收后设置。

## 6. 执行记录与主 Agent 验收

- 修改文件：

  ```text
  README.md
  rtl_obfuscator/rewrite.py
  tests/test_cli_vnext_encryption.py
  docs/tasks/T063_readable_mapping_scope_columns.md
  ```

- CSV 表头已固定为 `文件名,模块名,作用域,加密类型,原名,替换后名`。
- `11_supported_obfuscation.sv` 验证通过：`pair_t` 显示为
  `模块名=sample11_supported_obfuscation`、`作用域=type:pair_t`；函数和任务分别显示
  `function:apply_mask`、`task:select_value`；命名 generate 显示短格式
  `generate:generate_input`。
- 临时无名 generate 验证通过：内部声明的作用域显示为 `generate:line N`，没有完整
  `for (...) begin ... end` 文本。
- T062 相关定向与新增测试：33/33 通过，exit code 0。
- 常规全量回归：192/192 通过，显式排除 `tests.test_risc_v_vector_project_root`。
- `py_compile`：exit code 0；`git diff --check HEAD`：通过。
- FIFO project public encrypt/decrypt smoke 通过；4 个 RTL 文件恢复 byte-identical。
- compact Formal：正例 exit 0 且 `formal_equivalence=pass`；负例只插入一个 `~`，
  catalog/top-overlay strict compile 均为 0/0，Formal exit 1 且含 `unproven`、
  `equiv_status -assert`。
- 未运行 RISC-V-Vector Formal。
- 结论：T063 合同全部满足，主 Agent 已将状态设为 `ACCEPTED`。
