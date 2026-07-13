# T005：单个 value parameter 端到端重命名

- 状态：`READY`
- 设计负责人：主 Agent
- 实现负责人：子 Agent
- 前置任务：T004 已达到 `ACCEPTED`

## 1. 单一目标

为统一重命名流水线增加 `parameters` 类别，只处理固定样例中的 module parameter `INVERT`，完成映射、声明和普通表达式引用改写、反向恢复、五项指标及 Yosys 形式等价验证。

## 2. 固定输入与输出

```text
gold        = tests/fixtures/t005_value_parameter.sv
category    = parameters
name_length = 8
top         = t005_value_parameter
```

固定输出：

```text
/tmp/rtl_obfuscation_t005/gate.sv
/tmp/rtl_obfuscation_t005/restored.sv
/tmp/rtl_obfuscation_t005/mapping.json
/tmp/rtl_obfuscation_t005/metrics.json
```

## 3. 固定 CLI

正向改写：

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite encrypt \
  --input tests/fixtures/t005_value_parameter.sv \
  --output /tmp/rtl_obfuscation_t005/gate.sv \
  --map /tmp/rtl_obfuscation_t005/mapping.json \
  --metrics /tmp/rtl_obfuscation_t005/metrics.json \
  --category parameters \
  --name-length 8
```

预期 stdout：

```json
{"files": 1, "mapping_entries": 1, "modified_tokens": 2}
```

反向恢复：

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite decrypt \
  --input /tmp/rtl_obfuscation_t005/gate.sv \
  --output /tmp/rtl_obfuscation_t005/restored.sv \
  --map /tmp/rtl_obfuscation_t005/mapping.json
```

预期 stdout 同样为 1 个 mapping entry 和 2 个 modified tokens。CLI 必须自行创建不存在的输出目录。

## 4. 固定映射结果

mapping 必须只有一个 entry：

```json
{
  "category": "parameters",
  "scope": "t005_value_parameter",
  "original_name": "INVERT",
  "renamed_name": "<8-character legal random identifier>",
  "declaration": {
    "file": "tests/fixtures/t005_value_parameter.sv",
    "start": 111,
    "end": 117
  },
  "references": [
    {
      "file": "tests/fixtures/t005_value_parameter.sv",
      "start": 250,
      "end": 256
    }
  ]
}
```

`input_a`、`output_y` 和内部 signal `selected_value` 均不得进入 `parameters` 映射。

## 5. 最小实现方案

- inventory CLI 接受 `signals` 或 `parameters`，并把 category 显式传入收集逻辑；不得根据输入文件内容猜测类别。
- `parameters` 只收集 module 定义中的 value `ParameterSymbol`，要求 `isType == False`；本任务不收集 type parameter。
- declaration 使用 ParameterSymbol 的语义 location；普通表达式引用继续使用绑定到同一 symbol 的 `NamedValueExpression`。
- 复用现有随机名称、range、source edit、metrics 和 decrypt 流程，不复制 signals 流水线。
- decrypt 根据 mapping category 重新收集 gate 中的 parameter 并定位新 ranges。
- mapping 校验不得再硬编码“三个 identifier ranges”；本任务允许 1 个 declaration 和 1 个 reference，同时必须保留 T003/T004 的三个 token 行为。
- 不增加旧 category 兼容、配置文件、新依赖或通用框架。

## 6. 五项效果指标

固定预期：

```json
{
  "affected_lines": {
    "changed": 2,
    "total": 10,
    "rate": 0.2
  },
  "symbols": {
    "renamed": 1,
    "eligible": 1,
    "coverage": 1.0
  },
  "occurrences": {
    "renamed": 2,
    "eligible": 2,
    "coverage": 1.0
  },
  "plaintext_leakage_rate": 0.0,
  "effective_coverage": 1.0
}
```

## 7. 验收命令

联合回归：

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_variable_inventory \
  tests.test_variable_ranges \
  tests.test_variable_rewrite \
  tests.test_signal_net_rewrite \
  tests.test_value_parameter_rewrite
```

随后依次执行第 3 节命令，并执行：

```sh
cmp -s tests/fixtures/t005_value_parameter.sv \
  /tmp/rtl_obfuscation_t005/restored.sv

conda run -n rtl_obfuscation python -c \
  'import pyslang; t=pyslang.syntax.SyntaxTree.fromFile("/tmp/rtl_obfuscation_t005/gate.sv"); c=pyslang.ast.Compilation(); c.addSyntaxTree(t); raise SystemExit(any(d.isError() for d in c.getAllDiagnostics()))'

conda run -n rtl_obfuscation verible-verilog-syntax \
  --lang=sv /tmp/rtl_obfuscation_t005/gate.sv

conda run -n rtl_obfuscation iverilog -g2012 -t null \
  -s t005_value_parameter /tmp/rtl_obfuscation_t005/gate.sv

conda run -n rtl_obfuscation python scripts/formal_equivalence.py \
  --gold tests/fixtures/t005_value_parameter.sv \
  --gate /tmp/rtl_obfuscation_t005/gate.sv \
  --top t005_value_parameter
```

所有命令退出码必须为 0；formal stdout JSON 的 `formal_equivalence` 必须为 `pass`。

## 8. 黑盒验收点

- mapping 只有 `INVERT`，category 为 `parameters`，renamed name 是合法 8 字符标识符。
- declaration 和 reference ranges 分别严格为 `[111,117)`、`[250,256)`，源字节均为 `INVERT`。
- gate 与 gold 的唯一差异是两个 `INVERT` token 被同一个新名称替换。
- restored 与 gold 字节完全一致，metrics 与第 6 节完全一致。
- PySlang、Verible、Icarus 和 Yosys formal 全部通过。
- 四个既有 signals 测试继续通过。

## 9. 本任务明确不包含

- type parameter、localparam、parameter array 或多个 parameter。
- parameter 在 packed/unpacked dimension、命名参数覆盖、defparam、层次引用或跨文件引用中的使用。
- module port、signal、module 名或其他重命名类别。
- 多文件、宏、include、配置文件或兼容旧 mapping。
- 修改既有 RTL 样例、固定 fixture 或 formal 脚本。

## 10. 允许修改的文件

```text
rtl_obfuscator/inventory.py
rtl_obfuscator/rewrite.py
tests/test_value_parameter_rewrite.py
docs/tasks/T005_value_parameter_roundtrip.md
```

`tests/fixtures/t005_value_parameter.sv` 是主 Agent 已冻结的只读输入。不得修改其他文件。

## 11. 子 Agent 文档流程

1. 开始前将状态从 `READY` 改为 `IN_PROGRESS` 并记录开始时间。
2. 若 PySlang value parameter API 或普通表达式引用绑定与合同不一致，记录最小复现并停止，不得扩大范围。
3. 完成后记录变更文件、完整命令、stdout/stderr、退出码和未覆盖边界。
4. 记录 Yosys gold、gate、top、命令和 PASS JSON；失败不得申请验收。
5. 全部门禁通过后设置为 `READY_FOR_REVIEW`；不得设置 `ACCEPTED`，不得 commit 或 push。

## 12. Formal verification（子 Agent 完成时填写）

```text
formal_verification: PENDING
gold: tests/fixtures/t005_value_parameter.sv
gate: /tmp/rtl_obfuscation_t005/gate.sv
top: t005_value_parameter
command: see section 7
exit_code: pending
result: pending
```

## 13. 执行记录（子 Agent 更新）

- 尚未开始。

## 14. 偏差或阻塞（子 Agent 更新）

- 无。

## 15. 交付证据（子 Agent 更新）

- 尚未交付。

## 16. 主 Agent 验收结果

- 尚未验收。
