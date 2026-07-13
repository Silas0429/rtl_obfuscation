# T004：统一内部 signals 并加入 NetSymbol

- 状态：`READY`
- 设计负责人：主 Agent
- 实现负责人：子 Agent
- 前置任务：T003 已达到 `ACCEPTED`

## 1. 单一目标

将公开 CLI 和 mapping 类别从 `variables` 迁移为统一的 `signals`，在保留 T003 内部 VariableSymbol 能力的同时增加 NetSymbol 收集；固定改写样例仍只包含一个内部 `wire combined_net`。

## 2. 固定输入与输出

```text
gold        = tests/fixtures/t004_internal_net.sv
category    = signals
name_length = 8
top         = t004_internal_net
```

固定输出：

```text
/tmp/rtl_obfuscation_t004/gate.sv
/tmp/rtl_obfuscation_t004/restored.sv
/tmp/rtl_obfuscation_t004/mapping.json
/tmp/rtl_obfuscation_t004/metrics.json
```

CLI 必须在输出目录不存在时自行创建目录。

## 3. 固定 CLI

正向改写：

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite encrypt \
  --input tests/fixtures/t004_internal_net.sv \
  --output /tmp/rtl_obfuscation_t004/gate.sv \
  --map /tmp/rtl_obfuscation_t004/mapping.json \
  --metrics /tmp/rtl_obfuscation_t004/metrics.json \
  --category signals \
  --name-length 8
```

预期 stdout：

```json
{"files": 1, "mapping_entries": 1, "modified_tokens": 3}
```

反向恢复：

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite decrypt \
  --input /tmp/rtl_obfuscation_t004/gate.sv \
  --output /tmp/rtl_obfuscation_t004/restored.sv \
  --map /tmp/rtl_obfuscation_t004/mapping.json
```

预期 stdout 同样为 1 个 mapping entry 和 3 个 modified tokens。

## 4. 固定映射结果

mapping 必须只有一个 entry：

```json
{
  "category": "signals",
  "scope": "t004_internal_net",
  "original_name": "combined_net",
  "renamed_name": "<8-character legal random identifier>",
  "declaration": {
    "file": "tests/fixtures/t004_internal_net.sv",
    "start": 170,
    "end": 182
  },
  "references": [
    {
      "file": "tests/fixtures/t004_internal_net.sv",
      "start": 196,
      "end": 208
    },
    {
      "file": "tests/fixtures/t004_internal_net.sv",
      "start": 252,
      "end": 264
    }
  ]
}
```

`output_y` 在 PySlang 中同时具有 port 与底层 NetSymbol 表示，属于外部 port，必须排除，不能生成第二条 `signals` 映射。

## 5. 最小实现方案

- 复用 T003 的随机名称、byte range、source edit、mapping、metrics 和 decrypt 流程。
- 公开 CLI 只接受 `signals`，mapping entry 只输出 `"category": "signals"`；不保留 `variables` 或 `nets` 兼容值。
- inventory 对 `signals` 同时收集 module 内部 `VariableSymbol` 和 `NetSymbol`，并排除所有 port 的 `internalSymbol`。
- 引用仍只处理语义绑定到目标 net 的 `NamedValueExpression`。
- 正向改写按 byte offset 从后向前执行；不得做字符串全局替换或重新生成 RTL。
- decrypt 必须重新解析 gate，根据 mapping 的 category、scope 和 renamed name 查找语义符号并收集新 ranges。
- 将 T001—T003 的三个回归测试迁移为 `signals` CLI 和 mapping 期望，内部 `logic and_result` 的条目、ranges、改写、恢复和指标必须保持不变。
- 不增加配置文件、兼容层、类层次或新依赖。

## 6. 五项效果指标

固定预期：

```json
{
  "affected_lines": {
    "changed": 3,
    "total": 9,
    "rate": 0.3333333333333333
  },
  "symbols": {
    "renamed": 1,
    "eligible": 1,
    "coverage": 1.0
  },
  "occurrences": {
    "renamed": 3,
    "eligible": 3,
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
  tests.test_signal_net_rewrite
```

随后依次执行第 3 节命令，并执行：

```sh
cmp -s tests/fixtures/t004_internal_net.sv \
  /tmp/rtl_obfuscation_t004/restored.sv

conda run -n rtl_obfuscation python -c \
  'import pyslang; t=pyslang.syntax.SyntaxTree.fromFile("/tmp/rtl_obfuscation_t004/gate.sv"); c=pyslang.ast.Compilation(); c.addSyntaxTree(t); raise SystemExit(any(d.isError() for d in c.getAllDiagnostics()))'

conda run -n rtl_obfuscation verible-verilog-syntax \
  --lang=sv /tmp/rtl_obfuscation_t004/gate.sv

conda run -n rtl_obfuscation iverilog -g2012 -t null \
  -s t004_internal_net /tmp/rtl_obfuscation_t004/gate.sv

conda run -n rtl_obfuscation python scripts/formal_equivalence.py \
  --gold tests/fixtures/t004_internal_net.sv \
  --gate /tmp/rtl_obfuscation_t004/gate.sv \
  --top t004_internal_net
```

所有命令退出码必须为 0；formal stdout JSON 的 `formal_equivalence` 必须为 `pass`。

## 8. 黑盒验收点

- mapping 只有 `combined_net`，没有 `input_a`、`input_b` 或 `output_y`。
- renamed name 匹配 `^[A-Za-z][A-Za-z0-9_]{7}$`，且不与输入已有标识符冲突。
- 三个固定 range 的源字节均为 `combined_net`。
- gate 与 gold 的唯一差异是三个 `combined_net` token 被同一新名称替换。
- restored 与 gold 字节完全一致。
- metrics 与第 6 节完全一致。
- PySlang、Verible、Icarus 和 Yosys 全部通过。
- 三个既有测试迁移到 `signals` 后继续通过，并证明 VariableSymbol 路径未回归。

## 9. 本任务明确不包含

- 本任务只用 `wire` 验证 NetSymbol 新路径；`tri`、`wand`、`wor`、用户定义 nettype 或 implicit net 不作为本任务验收输入。
- bit/part select、数组 net、hierarchical reference、alias、跨文件引用或宏。
- 多 net、多 module、批量文件或多 category 同时运行。
- module、port 或 T005 之后的重命名类别。
- 修改 formal 脚本、原有 10 个 `rtl_samples` 或既有测试期望。

## 10. 允许修改的文件

```text
rtl_obfuscator/inventory.py
rtl_obfuscator/rewrite.py
tests/test_variable_inventory.py
tests/test_variable_ranges.py
tests/test_variable_rewrite.py
tests/test_signal_net_rewrite.py
docs/tasks/T004_internal_net_roundtrip.md
```

`tests/fixtures/t004_internal_net.sv` 是主 Agent 已冻结的输入，只读，不得修改。不得修改其他文件。

## 11. 子 Agent 文档流程

1. 开始前将状态从 `READY` 改为 `IN_PROGRESS`，记录开始时间。
2. 若 PySlang 的 net/port 关系与本合同不一致，记录实际 API 和最小复现并停止，不得扩展范围。
3. 完成后记录变更文件、所有实际命令、stdout/stderr、退出码和未覆盖边界。
4. 记录独立 Yosys gold、gate、top、命令和 PASS JSON；失败不得申请验收。
5. 自测全部通过后将状态改为 `READY_FOR_REVIEW`；不得设置 `ACCEPTED`，不得 commit 或 push。

## 12. Formal verification（子 Agent 完成时填写）

```text
formal_verification: PENDING
gold: tests/fixtures/t004_internal_net.sv
gate: /tmp/rtl_obfuscation_t004/gate.sv
top: t004_internal_net
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
