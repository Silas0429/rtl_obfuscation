# T008：单个 genvar 端到端重命名

- 状态：`READY`
- 设计负责人：主 Agent
- 实现负责人：子 Agent
- 前置任务：T007 已达到 `ACCEPTED`

## 1. 单一目标

对 `rtl_samples/07_generate_loop.sv` 中唯一源码 genvar `bit_index` 完成映射、5 个 token 的正向改写、反向恢复、五项指标和 Yosys formal equivalence。

## 2. 固定输入与输出

```text
gold        = rtl_samples/07_generate_loop.sv
category    = genvars
name_length = 8
top         = sample07_generate_loop
```

固定输出：

```text
/tmp/rtl_obfuscation_t008/gate.sv
/tmp/rtl_obfuscation_t008/restored.sv
/tmp/rtl_obfuscation_t008/mapping.json
/tmp/rtl_obfuscation_t008/metrics.json
```

## 3. 固定 CLI 与汇总

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite encrypt \
  --input rtl_samples/07_generate_loop.sv \
  --output /tmp/rtl_obfuscation_t008/gate.sv \
  --map /tmp/rtl_obfuscation_t008/mapping.json \
  --metrics /tmp/rtl_obfuscation_t008/metrics.json \
  --category genvars \
  --name-length 8
```

预期 stdout：

```json
{"files": 1, "mapping_entries": 1, "modified_tokens": 5}
```

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite decrypt \
  --input /tmp/rtl_obfuscation_t008/gate.sv \
  --output /tmp/rtl_obfuscation_t008/restored.sv \
  --map /tmp/rtl_obfuscation_t008/mapping.json
```

decrypt 汇总同样必须为 1 个 entry、5 个 modified tokens。CLI 必须自行创建输出目录。

## 4. 固定 mapping

mapping 必须只有一个 entry：

```json
{
  "category": "genvars",
  "scope": "sample07_generate_loop",
  "original_name": "bit_index",
  "renamed_name": "<8-character legal random identifier>",
  "declaration": {
    "file": "rtl_samples/07_generate_loop.sv",
    "start": 316,
    "end": 325
  },
  "references": [
    {"file": "rtl_samples/07_generate_loop.sv", "start": 331, "end": 340},
    {"file": "rtl_samples/07_generate_loop.sv", "start": 350, "end": 359},
    {"file": "rtl_samples/07_generate_loop.sv", "start": 412, "end": 421},
    {"file": "rtl_samples/07_generate_loop.sv", "start": 436, "end": 445}
  ]
}
```

`WIDTH`、`generate_mask`、`masked_data`、ports 和 iteration parameters 均不得生成独立 mapping entry。

## 5. PySlang 语义边界与最小实现

- inventory 和 rewrite CLI 增加 `genvars` category。
- 源码声明是唯一 `GenvarSymbol bit_index`，location 为 `[316,325)`。
- elaborated semantic AST 中存在 4 个同名 iteration `ParameterSymbol`，共享原 genvar 的声明 location；它们不是独立源码声明，必须归一到同一个 mapping entry。
- 循环体两处索引引用绑定 iteration parameters，并因 WIDTH=4 重复展开；必须按源码 range 去重为 `[412,421)`、`[436,445)`。
- compilation root 不提供 generate header 条件和步进的普通 NamedValueExpression；必须从对应 `LoopGenerateSyntax` 取得 `[331,340)`、`[350,359)`。
- 允许增加一个 genvar 专用 range collector；不得用文件级字符串搜索猜测引用。
- 正向和反向都必须重新基于各自源码解析并收集 ranges；复用 T007 的全局 edit、mapping 校验、metrics 和 decrypt 流程。
- 不复制整条 rewrite 流水线，不增加框架、配置或新依赖。

## 6. 固定 metrics

```json
{
  "affected_lines": {
    "changed": 2,
    "total": 13,
    "rate": 0.15384615384615385
  },
  "symbols": {
    "renamed": 1,
    "eligible": 1,
    "coverage": 1.0
  },
  "occurrences": {
    "renamed": 5,
    "eligible": 5,
    "coverage": 1.0
  },
  "plaintext_leakage_rate": 0.0,
  "effective_coverage": 1.0
}
```

## 7. 统一验收命令

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
  tests.test_genvar_rewrite
```

执行第 3 节两条 CLI 后，继续执行：

```sh
cmp -s rtl_samples/07_generate_loop.sv /tmp/rtl_obfuscation_t008/restored.sv

conda run -n rtl_obfuscation python -c \
  'import pyslang; t=pyslang.syntax.SyntaxTree.fromFile("/tmp/rtl_obfuscation_t008/gate.sv"); c=pyslang.ast.Compilation(); c.addSyntaxTree(t); raise SystemExit(any(d.isError() for d in c.getAllDiagnostics()))'

conda run -n rtl_obfuscation verible-verilog-syntax \
  --lang=sv /tmp/rtl_obfuscation_t008/gate.sv

conda run -n rtl_obfuscation iverilog -g2012 -t null \
  -s sample07_generate_loop /tmp/rtl_obfuscation_t008/gate.sv

conda run -n rtl_obfuscation python scripts/formal_equivalence.py \
  --gold rtl_samples/07_generate_loop.sv \
  --gate /tmp/rtl_obfuscation_t008/gate.sv \
  --top sample07_generate_loop
```

全部退出码必须为 0，formal JSON 必须为 `pass`。

## 8. 黑盒验收点

- 9 项回归全部通过。
- mapping 只有 `bit_index`，5 个 gold ranges 与第 4 节完全一致。
- gate 中声明、header 条件、header 步进和两个循环体索引全部使用同一新名称。
- gate 与 gold 的唯一差异是 5 个 token；restored 与 gold 字节完全一致。
- metrics 与第 6 节完全一致。
- PySlang、Verible、Icarus 和 Yosys formal 全部通过。
- 冻结 RTL 样例没有被修改。

## 9. 本任务明确不包含

- 多个或嵌套 generate loop。
- generate block label、implicit genblk、parameter `WIDTH`。
- genvar 层次引用、跨文件引用或多文件。
- T006 type parameter、function/task/argument、instance。
- 修改 fixture、RTL 样例或 formal 脚本。

## 10. 允许修改的文件

```text
rtl_obfuscator/inventory.py
rtl_obfuscator/rewrite.py
tests/test_genvar_rewrite.py
docs/tasks/T008_genvar_roundtrip.md
```

不得修改其他文件。

## 11. 子 Agent 流程

1. 开始前将状态从 `READY` 改成 `IN_PROGRESS`，记录 PySlang API 探测结果。
2. 只实现固定单 genvar 的 5-token 路径，不扩展边界。
3. 记录 9 项回归、两条 CLI、mapping/ranges/metrics、三套前端和 formal JSON。
4. formal 失败不得申请验收。
5. 完成后设置 `READY_FOR_REVIEW`，不得设置 `ACCEPTED`，不得 commit 或 push。

## 12. Formal verification（子 Agent 完成时填写）

```text
formal_verification: PENDING
gold: rtl_samples/07_generate_loop.sv
gate: /tmp/rtl_obfuscation_t008/gate.sv
top: sample07_generate_loop
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
