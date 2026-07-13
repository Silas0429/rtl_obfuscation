# T005：单个 value parameter 端到端重命名

- 状态：`ACCEPTED`
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
formal_verification: PASS
gold: tests/fixtures/t005_value_parameter.sv
gate: /tmp/rtl_obfuscation_t005/gate.sv
top: t005_value_parameter
command: conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold tests/fixtures/t005_value_parameter.sv --gate /tmp/rtl_obfuscation_t005/gate.sv --top t005_value_parameter
exit_code: 0
result: {"formal_equivalence": "pass", "gate": "/private/tmp/rtl_obfuscation_t005/gate.sv", "gold": "/Users/lufengchi/Desktop/workspace/rtl_obfuscation/tests/fixtures/t005_value_parameter.sv", "seq": 5, "top": "t005_value_parameter"}
```

## 13. 执行记录（子 Agent 更新）

- 2026-07-13 13:30 CST：已阅读 `docs/tasks/README.md`、T005 合同及 `docs/formal_verification.md`；确认 T001—T004 已 `ACCEPTED`、T005 是唯一 `READY` 任务，开始按合同实现。范围严格限定为固定 value parameter `INVERT`，不扩展到 `WIDTH`、type parameter、localparam、命名参数覆盖或其他参数用法；子 Agent 不执行 commit/push。
- 2026-07-13 13:35 CST：完成 `parameters` 类别显式分派、固定 value `ParameterSymbol` 的声明/普通表达式引用改写、gate semantic AST 反向恢复、指标和全部门禁；Yosys formal 返回 PASS。
- PySlang 11 实测与合同一致：`INVERT` 是 `ParameterSymbol`，`isType == False`、`isLocalParam == False`，声明 offset 111；唯一普通表达式引用是绑定到同一 symbol 的 `NamedValueExpression`，offset 250。

## 14. 偏差或阻塞（子 Agent 更新）

- 无。

## 15. 交付证据（子 Agent 更新）

- 变更文件：
  - `rtl_obfuscator/inventory.py`
  - `rtl_obfuscator/rewrite.py`
  - `tests/test_value_parameter_rewrite.py`
  - `docs/tasks/T005_value_parameter_roundtrip.md`
- 联合回归命令：

  ```sh
  conda run -n rtl_obfuscation python -m unittest \
    tests.test_variable_inventory \
    tests.test_variable_ranges \
    tests.test_variable_rewrite \
    tests.test_signal_net_rewrite \
    tests.test_value_parameter_rewrite
  ```

  最终退出码：`0`。实际输出：

  ```text
  .....
  ----------------------------------------------------------------------
  Ran 5 tests in 0.440s

  OK
  ```

- 从不存在的 `/tmp/rtl_obfuscation_t005` 开始运行固定 encrypt 命令，CLI 自动创建目录及四个产物。退出码：`0`。stdout：

  ```json
  {"files": 1, "mapping_entries": 1, "modified_tokens": 2}
  ```

- 本次随机名称为 `OLh9DFPS`。`mapping.json` 只有以下 entry：

  ```json
  {
    "category": "parameters",
    "scope": "t005_value_parameter",
    "original_name": "INVERT",
    "renamed_name": "OLh9DFPS",
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

  两个源字节切片均严格等于 `INVERT`；`input_a`、`output_y`、`selected_value` 均未进入 `parameters` 映射。gate 与 gold 的唯一差异是两个 `INVERT` token 被同一随机名称替换。
- `metrics.json` 实际内容：

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

- 固定 decrypt 命令退出码：`0`。stdout：

  ```json
  {"files": 1, "mapping_entries": 1, "modified_tokens": 2}
  ```

- 文本与工具门禁：
  - `cmp -s tests/fixtures/t005_value_parameter.sv /tmp/rtl_obfuscation_t005/restored.sv`：退出码 `0`。
  - 第 7 节 PySlang 命令：退出码 `0`，无 stdout/stderr。
  - 第 7 节 Verible 命令：退出码 `0`，无 stdout/stderr。
  - 第 7 节 Icarus 命令：退出码 `0`，无 stdout/stderr。
  - 第 7 节 Yosys formal 命令：退出码 `0`，PASS JSON 见第 12 节。
- `git status --short -- '*.sv'` 无输出；冻结 fixture 和其他 RTL 均未修改。
- `git diff --check` 退出码为 `0`。子 Agent 未执行 commit 或 push。
- 范围审计：实现和新测试中没有 `WIDTH`、type parameter、命名参数覆盖或 defparam 路径；`localparam` 只以 `not node.isLocalParam` 的明确排除条件出现。
- 未覆盖边界：未实现 type parameter、localparam、parameter array、多 parameter、dimension、命名参数覆盖、defparam、层次/跨文件引用，也未修改 signals 既有测试、fixture、formal 脚本或其他类别。

## 16. 主 Agent 验收结果

- 2026-07-13 主 Agent 按固定合同独立验收通过，状态设为 `ACCEPTED`。
- 联合回归命令退出码为 `0`，共 5 个测试通过。
- 固定 encrypt/decrypt 均退出码为 `0`，stdout 均报告 1 个 mapping entry 和 2 个 modified tokens；本次随机映射只包含 value parameter `INVERT`。
- mapping category 为 `parameters`，scope 为 `t005_value_parameter`；declaration 为 `[111, 117)`，唯一普通表达式 reference 为 `[250, 256)`。
- `input_a`、`output_y` 和 `selected_value` 均未进入参数映射；gate 与 gold 的唯一差异是两个 `INVERT` token 使用同一 8 字符合法名称替换。
- restored 与 gold 字节完全一致，五项指标与第 6 节固定预期完全一致。
- PySlang、Verible、Icarus 固定验收命令退出码均为 `0`。
- 主 Agent 独立重跑 Yosys formal equivalence，退出码为 `0`，结果为：

  ```json
  {"formal_equivalence": "pass", "gate": "/private/tmp/rtl_obfuscation_t005/gate.sv", "gold": "/Users/lufengchi/Desktop/workspace/rtl_obfuscation/tests/fixtures/t005_value_parameter.sv", "seq": 5, "top": "t005_value_parameter"}
  ```

- `git status --short -- '*.sv'` 无输出，冻结 fixture 和仓库 RTL 样例均未修改。
- 验收边界只证明单个 module value parameter 在普通表达式中的声明/引用改写；不代表 dimension、localparam、type parameter 或命名参数覆盖已支持。

- 尚未验收。
