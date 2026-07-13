# T009：function、task 与 arguments 单文件批次

- 状态：`READY`
- 设计负责人：主 Agent
- 实现负责人：子 Agent
- 前置任务：T008 已达到 `ACCEPTED`

## 1. 单一批次目标

复用现有单文件流水线，一次加入三个高度相关的 category：

1. `functions`：function 声明、传统返回赋值和普通 ordered call。
2. `tasks`：task 声明和普通 ordered call。
3. `arguments`：function/task 形式参数声明及 subroutine 内部引用。

四个固定运行分别验收，不增加多 category CLI，也不进入多文件。

## 2. 冻结输入

```text
function_gold = tests/fixtures/t009_function_argument.sv
function_top  = t009_function_argument
task_gold     = tests/fixtures/t009_task_argument.sv
task_top      = t009_task_argument
name_length   = 8
```

fixtures 已由主 Agent 创建并通过四套前端预探测，子 Agent 不得修改。

## 3. 固定运行矩阵

| 运行 | 输入 | category | 输出目录 | entries | tokens |
| --- | --- | --- | --- | ---: | ---: |
| F | function fixture | `functions` | `/tmp/rtl_obfuscation_t009/functions` | 1 | 3 |
| FA | function fixture | `arguments` | `/tmp/rtl_obfuscation_t009/function_arguments` | 1 | 2 |
| T | task fixture | `tasks` | `/tmp/rtl_obfuscation_t009/tasks` | 1 | 2 |
| TA | task fixture | `arguments` | `/tmp/rtl_obfuscation_t009/task_arguments` | 2 | 4 |

每个目录必须包含：

```text
gate.sv
restored.sv
mapping.json
metrics.json
```

encrypt/decrypt stdout 都必须为：

```json
{"files": 1, "mapping_entries": <entries>, "modified_tokens": <tokens>}
```

CLI 必须自行创建尚不存在的输出目录。

## 4. 固定 mapping 与 source ranges

所有 entry 的 `renamed_name` 都是长度 8 的随机合法标识符，`file` 等于对应输入路径。

### 4.1 F：functions

```json
{
  "category": "functions",
  "scope": "t009_function_argument",
  "original_name": "transform_value",
  "declaration": {"start": 141, "end": 156},
  "references": [
    {"start": 213, "end": 228},
    {"start": 295, "end": 310}
  ]
}
```

三个 token 依次对应声明、传统 function 返回赋值左侧和普通调用。

### 4.2 FA：function arguments

```json
{
  "category": "arguments",
  "scope": "t009_function_argument",
  "original_name": "function_data",
  "declaration": {"start": 184, "end": 197},
  "references": [
    {"start": 231, "end": 244}
  ]
}
```

### 4.3 T：tasks

```json
{
  "category": "tasks",
  "scope": "t009_task_argument",
  "original_name": "drive_value",
  "declaration": {"start": 121, "end": 132},
  "references": [
    {"start": 301, "end": 312}
  ]
}
```

### 4.4 TA：task arguments

entry 必须按声明 offset 排序：

```json
[
  {
    "category": "arguments",
    "scope": "t009_task_argument",
    "original_name": "task_data",
    "declaration": {"start": 161, "end": 170},
    "references": [{"start": 240, "end": 249}]
  },
  {
    "category": "arguments",
    "scope": "t009_task_argument",
    "original_name": "task_result",
    "declaration": {"start": 199, "end": 210},
    "references": [{"start": 226, "end": 237}]
  }
]
```

ordered actual expressions `input_data` 和 `output_data` 不得改名或生成 entry。

## 5. 固定 metrics

除下列字段外，四个 metrics 均须满足 `symbols.coverage = 1.0`、`occurrences.coverage = 1.0`、`plaintext_leakage_rate = 0.0`、`effective_coverage = 1.0`。

| 运行 | affected lines | symbols renamed/eligible | occurrences renamed/eligible |
| --- | --- | --- | --- |
| F | `3 / 11 = 0.2727272727272727` | `1 / 1` | `3 / 3` |
| FA | `2 / 11 = 0.18181818181818182` | `1 / 1` | `2 / 2` |
| T | `2 / 14 = 0.14285714285714285` | `1 / 1` | `2 / 2` |
| TA | `3 / 14 = 0.21428571428571427` | `2 / 2` | `4 / 4` |

## 6. PySlang 11 最小实现方案

- CLI choices 和 decrypt mapping validator 只增加 `functions`、`tasks`、`arguments`。
- function/task 共用一个 `SubroutineSymbol` collector，并按 `subroutineKind` 区分；只接受 module definition 内的源码定义。
- ordinary call 使用 `CallExpression.subroutine is target` 绑定，改写 `InvocationExpression.left.identifier`。
- function 返回赋值的 `NamedValueExpression.symbol` 绑定 `target.returnValVar`，其 identifier 归入同一 function entry。
- arguments 收集 `FormalArgumentSymbol`；正文引用继续使用现有 NamedValue symbol identity 路径。
- scope 继续使用当前 schema 的 module definition 名。本任务每个 module 只有一个 subroutine，不扩展嵌套 scope schema。
- 复用现有随机命名、mapping 排序、source edits、gate 重解析、decrypt、metrics 和 formal，不复制 rewrite 流水线。
- 不增加 fallback、配置、依赖或通用 AST abstraction；固定 fixture 所需 API 不支持时记录并停止。

## 7. 固定 CLI

以下模板对第 3 节四个运行分别执行，替换 `<gold>`、`<category>` 和 `<dir>`：

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite encrypt \
  --input <gold> \
  --output <dir>/gate.sv \
  --map <dir>/mapping.json \
  --metrics <dir>/metrics.json \
  --category <category> \
  --name-length 8

conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite decrypt \
  --input <dir>/gate.sv \
  --output <dir>/restored.sv \
  --map <dir>/mapping.json
```

四组替换值：

```text
F:  <gold>=tests/fixtures/t009_function_argument.sv  <category>=functions  <dir>=/tmp/rtl_obfuscation_t009/functions
FA: <gold>=tests/fixtures/t009_function_argument.sv  <category>=arguments  <dir>=/tmp/rtl_obfuscation_t009/function_arguments
T:  <gold>=tests/fixtures/t009_task_argument.sv      <category>=tasks      <dir>=/tmp/rtl_obfuscation_t009/tasks
TA: <gold>=tests/fixtures/t009_task_argument.sv      <category>=arguments  <dir>=/tmp/rtl_obfuscation_t009/task_arguments
```

## 8. 统一回归和文本验收

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_variable_inventory \
  tests.test_variable_ranges \
  tests.test_variable_rewrite \
  tests.test_signal_net_rewrite \
  tests.test_value_parameter_rewrite \
  tests.test_multi_signal_rewrite \
  tests.test_localparam_rewrite \
  tests.test_enum_value_rewrite \
  tests.test_genvar_rewrite \
  tests.test_subroutine_rewrite
```

四个 gate 必须分别等于“只按对应 mapping ranges 替换 token”的预期字节；四个 restored 必须分别与其 gold 字节完全一致。测试还必须断言：

- 所有 mapping source slice 都严格等于 entry 的 `original_name`。
- gate 中目标原名 token 数为 0，新名称 occurrence 数等于第 3 节 tokens。
- F 保持 `function_data`、ports 不变；FA 保持 `transform_value`、ports 不变。
- T 保持 task arguments、ports 不变；TA 保持 `drive_value`、ordered actuals 不变。

## 9. 前端与 formal 门禁

四个 gate 分别运行 PySlang、Verible、Icarus；top 使用第 2 节对应值。命令形式：

```sh
conda run -n rtl_obfuscation python -c \
  'import pyslang; t=pyslang.syntax.SyntaxTree.fromFile("<gate>"); c=pyslang.ast.Compilation(); c.addSyntaxTree(t); raise SystemExit(any(d.isError() for d in c.getAllDiagnostics()))'
conda run -n rtl_obfuscation verible-verilog-syntax --lang=sv <gate>
conda run -n rtl_obfuscation iverilog -g2012 -t null -s <top> <gate>
```

四个 formal 命令：

```sh
conda run -n rtl_obfuscation python scripts/formal_equivalence.py \
  --gold tests/fixtures/t009_function_argument.sv \
  --gate /tmp/rtl_obfuscation_t009/functions/gate.sv \
  --top t009_function_argument

conda run -n rtl_obfuscation python scripts/formal_equivalence.py \
  --gold tests/fixtures/t009_function_argument.sv \
  --gate /tmp/rtl_obfuscation_t009/function_arguments/gate.sv \
  --top t009_function_argument

conda run -n rtl_obfuscation python scripts/formal_equivalence.py \
  --gold tests/fixtures/t009_task_argument.sv \
  --gate /tmp/rtl_obfuscation_t009/tasks/gate.sv \
  --top t009_task_argument

conda run -n rtl_obfuscation python scripts/formal_equivalence.py \
  --gold tests/fixtures/t009_task_argument.sv \
  --gate /tmp/rtl_obfuscation_t009/task_arguments/gate.sv \
  --top t009_task_argument
```

全部退出码必须为 `0`，四个 formal JSON 均必须为 `pass`。

主 Agent 在冻结任务前已按 F、FA、T、TA 分别制作只修改目标 category 的手工 gate；四组 PySlang、Verible、Icarus 和 Yosys formal 均通过，formal 的 `seq` 均为 `5`。

## 10. 明确不包含

- 命名实参 `.argument(...)`、prototype/extern、DPI、recursive function。
- `return expression;`；fixture 只用传统 `function_name = value;`。
- package/class/interface subroutine、层次或作用域调用。
- 多个同名 subroutine、overload、同 module 多 subroutine scope 消歧。
- 多文件、macro/include、跨文件或外部层次引用。
- T006 type parameter、module/port、instance、generate block。
- 修改 CLI 使一次运行接受多个 category。

## 11. 允许修改的文件

```text
rtl_obfuscator/inventory.py
rtl_obfuscator/rewrite.py
tests/test_subroutine_rewrite.py
docs/tasks/T009_subroutine_batch.md
```

不得修改两个冻结 fixture、现有测试、RTL 样例、计划文档或 formal 脚本。

## 12. 子 Agent 流程

1. 开始前将状态从 `READY` 改成 `IN_PROGRESS`，记录实际 PySlang API。
2. 先完成 F/FA，再复用到 T/TA；不得扩展第 10 节边界。
3. 记录 10 项回归、四组 CLI、完整 mappings/ranges/metrics、12 个前端检查和 4 个 formal JSON。
4. 任一 rewritten RTL 的 formal 失败时不得申请验收。
5. 完成后填写第 13—15 节，设置 `READY_FOR_REVIEW`；不得 commit 或 push。

## 13. Formal verification（子 Agent 完成时填写）

```text
formal_verification: PENDING
F:  gold/gate/top/command/exit_code/result
FA: gold/gate/top/command/exit_code/result
T:  gold/gate/top/command/exit_code/result
TA: gold/gate/top/command/exit_code/result
```

## 14. 执行记录（子 Agent 更新）

- 尚未开始。

## 15. 偏差或阻塞（子 Agent 更新）

- 无。

## 16. 交付证据（子 Agent 更新）

- 尚未交付。

## 17. 主 Agent 验收结果

- 尚未验收。
