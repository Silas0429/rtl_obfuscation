# T003：内部变量正向改写、反向恢复与等价验证

- 状态：`READY`
- 设计负责人：主 Agent
- 实现负责人：子 Agent
- 前置任务：T002 必须先达到 `ACCEPTED`

> T002 已验收通过，本任务边界已经由主 Agent复核，可以开始执行。

## 1. 单一目标

对固定单文件样例中的内部变量 `and_result` 执行一次完整纵向切片：生成映射、改写声明和两个引用、保存 gate RTL、使用映射恢复原文件、输出五项效果指标，并通过语法、编译和 Yosys formal equivalence。

## 2. 固定输入与输出

输入：

```text
gold        = rtl_samples/01_continuous_assign.sv
category    = variables
name_length = 8
top         = sample01_continuous_assign
```

固定输出：

```text
/tmp/rtl_obfuscation_t003/gate.sv
/tmp/rtl_obfuscation_t003/restored.sv
/tmp/rtl_obfuscation_t003/mapping.json
/tmp/rtl_obfuscation_t003/metrics.json
```

CLI 必须在目录不存在时创建 `/tmp/rtl_obfuscation_t003`，使固定命令可从干净环境直接运行。

## 3. 固定 CLI

正向改写：

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite encrypt \
  --input rtl_samples/01_continuous_assign.sv \
  --output /tmp/rtl_obfuscation_t003/gate.sv \
  --map /tmp/rtl_obfuscation_t003/mapping.json \
  --metrics /tmp/rtl_obfuscation_t003/metrics.json \
  --category variables \
  --name-length 8
```

stdout 汇总必须为：

```json
{"files": 1, "mapping_entries": 1, "modified_tokens": 3}
```

反向恢复：

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite decrypt \
  --input /tmp/rtl_obfuscation_t003/gate.sv \
  --output /tmp/rtl_obfuscation_t003/restored.sv \
  --map /tmp/rtl_obfuscation_t003/mapping.json
```

stdout 汇总同样必须报告 1 个 mapping entry 和 3 个 modified tokens。

## 4. 正向改写要求

- mapping 中只有 `and_result` 一个 entry。
- gate 中 declaration 和两个 references 必须全部替换成同一个随机新名称。
- `input_a`、`input_b`、`output_y`、module 名以及其他文本保持不变。
- 不允许 AST/code generator 重新生成文件。
- 将 T002 的三个字节 range 转为 `SourceEdit`。
- 验证 edit 唯一、不重叠，且原始字节切片等于 `and_result`。
- 按 `start` 从大到小应用 byte edit，避免前一次修改改变后续 offset。
- 写入独立输出文件，不修改 gold。

## 5. 反向恢复要求

- 从 `mapping.json` 读取 `renamed_name -> original_name`。
- 重新用 PySlang 解析 gate，按 semantic symbol 重新收集 declaration 和 references；不得复用 gold 的旧 offset。
- 将 gate 中的三个随机名称 token 从后向前替换为 `and_result`。
- `restored.sv` 必须与 gold 字节完全一致。

## 6. Mapping 文件

采用实施计划中的 version 1 schema。T003 的 entry 必须包含：

```text
category
scope
original_name
renamed_name
declaration.file/start/end
references[].file/start/end
```

mapping 是反向恢复的唯一依据；decrypt 不允许重新随机生成名称或猜测原名。

## 7. 五项效果指标

`metrics.json` 只记录效果指标；formal 使用独立 PASS JSON 作为门禁证据。

固定样例预期：

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

有效代码行定义为排除空行和仅注释行后的物理行。本任务固定样例共有 9 行有效代码，其中 3 行包含被改写 token。

## 8. 验证流程

### 8.1 文本往返

```sh
cmp -s rtl_samples/01_continuous_assign.sv \
  /tmp/rtl_obfuscation_t003/restored.sv
```

退出码必须为 0。

### 8.2 PySlang

```sh
conda run -n rtl_obfuscation python -c \
  'import pyslang; t=pyslang.syntax.SyntaxTree.fromFile("/tmp/rtl_obfuscation_t003/gate.sv"); c=pyslang.ast.Compilation(); c.addSyntaxTree(t); raise SystemExit(any(d.isError() for d in c.getAllDiagnostics()))'
```

### 8.3 Verible 与 Icarus

```sh
conda run -n rtl_obfuscation verible-verilog-syntax \
  --lang=sv /tmp/rtl_obfuscation_t003/gate.sv

conda run -n rtl_obfuscation iverilog -g2012 -t null \
  -s sample01_continuous_assign \
  /tmp/rtl_obfuscation_t003/gate.sv
```

### 8.4 Yosys formal equivalence

```sh
conda run -n rtl_obfuscation python scripts/formal_equivalence.py \
  --gold rtl_samples/01_continuous_assign.sv \
  --gate /tmp/rtl_obfuscation_t003/gate.sv \
  --top sample01_continuous_assign
```

退出码必须为 0，stdout JSON 中 `formal_equivalence` 必须为 `pass`。

## 9. 本任务包含

- 单文件、单 module、单个内部变量。
- 正向 source edit。
- version 1 mapping 文件。
- 反向恢复。
- 五项效果指标。
- PySlang、Verible、Icarus、文本往返、Yosys formal 验证。
- 使用 `unittest` 和临时目录进行黑盒测试。

## 10. 本任务明确不包含

- 多文件、filelist、include、define。
- 其他变量样例或其他重命名类别。
- top/module/port 名重命名。
- HierarchicalValue、member access、宏内引用。
- preserve 规则、YAML、批量目录处理。
- 兼容旧 mapping version、部分成功或 fallback。
- 修改 Yosys formal 脚本。

## 11. 允许修改的文件

```text
rtl_obfuscator/inventory.py
rtl_obfuscator/rewrite.py
tests/test_variable_rewrite.py
docs/tasks/T003_variable_rewrite_roundtrip.md
```

不得修改 RTL fixture、T001/T002 测试、Yosys 脚本、实施计划或其他任务文档。

## 12. 子 Agent 自测命令

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_variable_inventory \
  tests.test_variable_ranges \
  tests.test_variable_rewrite
```

随后必须依次运行第 3 节和第 8 节的全部黑盒命令，并将实际输出写入本任务单。

## 13. 主 Agent 黑盒验收

- 三个 unittest 全部通过。
- encrypt/decrypt stdout 汇总符合约定。
- mapping 只有一个 entry，且三个 ranges 正确。
- gate 只修改三个 `and_result` token。
- restored 与 gold 字节一致。
- 五项指标与第 7 节一致。
- PySlang、Verible、Icarus 全部通过。
- Yosys formal 输出 PASS JSON。
- gold 和 RTL fixtures 未被修改。

## 14. Formal verification（子 Agent 完成时填写）

```text
formal_verification: PENDING
gold: rtl_samples/01_continuous_assign.sv
gate: /tmp/rtl_obfuscation_t003/gate.sv
top: sample01_continuous_assign
command: see section 8.4
exit_code: pending
result: pending
```

## 15. 执行记录（子 Agent 更新）

- 尚未开始。

## 16. 偏差或阻塞（子 Agent 更新）

- 无。

## 17. 交付证据（子 Agent 更新）

- 尚未交付。

## 18. 主 Agent 验收结果

- 尚未验收。
