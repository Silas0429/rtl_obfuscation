# T006：单个 type parameter 映射与类型引用范围

- 状态：`DRAFT`
- 设计负责人：主 Agent
- 实现负责人：子 Agent
- 前置任务：T005 已达到 `ACCEPTED`

> 2026-07-13：按开发者要求暂缓 T006。不得启动实现；恢复时由主 Agent 重新检查并设置为 `READY`。

## 1. 单一目标

使用 PySlang 找出固定 module 的 type parameter `DATA_T`、其声明 token 和一个绑定到该类型参数的内部 signal 类型引用，只输出带 source ranges 的 mapping JSON，不改写 RTL。

## 2. 固定输入

```text
input       = tests/fixtures/t006_type_parameter.sv
category    = type_parameters
name_length = 8
top         = t006_type_parameter
```

固定命令：

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.inventory \
  --input tests/fixtures/t006_type_parameter.sv \
  --category type_parameters \
  --name-length 8 \
  --include-ranges
```

stdout 必须是单个 version 1 JSON 文档，不产生 gate、restored、mapping 文件或 metrics 文件。

## 3. 固定输出

随机名称除外，输出必须等价于：

```json
{
  "version": 1,
  "name_length": 8,
  "entries": [
    {
      "category": "type_parameters",
      "scope": "t006_type_parameter",
      "original_name": "DATA_T",
      "renamed_name": "<8-character legal random identifier>",
      "declaration": {
        "file": "tests/fixtures/t006_type_parameter.sv",
        "start": 113,
        "end": 119
      },
      "references": [
        {
          "file": "tests/fixtures/t006_type_parameter.sv",
          "start": 216,
          "end": 222
        }
      ]
    }
  ]
}
```

两个范围切出的源字节都必须严格等于 `DATA_T`。

## 4. 最小实现方案

- inventory CLI 在现有 `signals`、`parameters` 之外接受 `type_parameters`。
- 只收集 module 定义中的 `SymbolKind.TypeParameter`，固定目标必须唯一。
- declaration 使用 `TypeParameterSymbol.location`。
- 本任务的类型引用不是 `NamedValueExpression`：内部变量 `internal_data.type` 必须与目标 `TypeParameterSymbol.typeAlias` 是同一语义类型对象。
- 从该变量的 syntax 向上取得固定 `DataDeclarationSyntax.type`；它必须是 `NamedTypeSyntax`，引用 token 为 `type.name.identifier`，offset 为 216。
- 为 type parameter 单独增加最小 range 收集分支；不得把文本搜索伪装成语义绑定，不得改坏 signals/parameters 的 NamedValueExpression 路径。
- 复用既有随机合法名称、range record、去重和非重叠校验。
- 不修改 `rewrite.py`，不生成或改写 RTL。

## 5. 验收命令

联合回归：

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_variable_inventory \
  tests.test_variable_ranges \
  tests.test_variable_rewrite \
  tests.test_signal_net_rewrite \
  tests.test_value_parameter_rewrite \
  tests.test_type_parameter_ranges
```

固定输入前端检查：

```sh
conda run -n rtl_obfuscation python -c \
  'import pyslang; t=pyslang.syntax.SyntaxTree.fromFile("tests/fixtures/t006_type_parameter.sv"); c=pyslang.ast.Compilation(); c.addSyntaxTree(t); raise SystemExit(any(d.isError() for d in c.getAllDiagnostics()))'

conda run -n rtl_obfuscation verible-verilog-syntax \
  --lang=sv tests/fixtures/t006_type_parameter.sv

conda run -n rtl_obfuscation iverilog -g2012 -t null \
  -s t006_type_parameter tests/fixtures/t006_type_parameter.sv
```

随后执行第 2 节 CLI，并以 `json.loads` 检查第 3 节全部字段、ranges 和随机名称格式。

## 6. 黑盒验收点

- 六个 unittest 全部通过。
- stdout 是合法 JSON，只有一个 `type_parameters` entry。
- `DATA_T` declaration 为 `[113,119)`，唯一 type reference 为 `[216,222)`。
- `internal_data`、ports 和普通 signals 不进入 mapping。
- 新名称匹配 `^[A-Za-z][A-Za-z0-9_]{7}$` 且不与输入标识符冲突。
- PySlang、Verible、Icarus 均接受冻结输入。
- 仓库中没有任何 `.sv` 被修改。

## 7. Formal verification

```text
formal_verification: N/A
reason: T006 only emits a mapping and source ranges; it does not produce rewritten RTL
```

不得运行 gold/gate identity comparison 并将其称为改写正确性证据。

主 Agent 预研记录：当前 Conda 环境中的 Yosys Verilog frontend 在 `parameter type DATA_T` 处返回语法错误。因此 T006 不授权 type parameter RTL 改写，也不修改 formal 脚本。

## 8. 本任务明确不包含

- type parameter 源码改写、反向恢复、metrics 或 Yosys formal。
- module port 类型中的 type parameter 引用、多个变量类型引用或多个 type parameter。
- parameter type override、作用域引用、typedef、class/interface type parameter 或跨文件引用。
- value parameter 的 dimension 引用。
- 修改 fixture、`rewrite.py`、formal 脚本或其他重命名类别。

## 9. 允许修改的文件

```text
rtl_obfuscator/inventory.py
tests/test_type_parameter_ranges.py
docs/tasks/T006_type_parameter_ranges.md
```

`tests/fixtures/t006_type_parameter.sv` 是主 Agent 已冻结的只读输入。不得修改其他文件。

## 10. 子 Agent 文档流程

1. 开始前将状态从 `READY` 改为 `IN_PROGRESS` 并记录开始时间。
2. 若 `TypeParameterSymbol.typeAlias`、`VariableSymbol.type` 或 syntax 路径与合同不一致，记录最小复现并停止，不得退回字符串搜索。
3. 完成后记录变更文件、所有命令、stdout/stderr、退出码和未覆盖边界。
4. Formal 明确记录为 `N/A` 及“不产生 rewritten RTL”的原因，不运行 identity comparison。
5. 全部门禁通过后设置为 `READY_FOR_REVIEW`；不得设置 `ACCEPTED`，不得 commit 或 push。

## 11. 执行记录（子 Agent 更新）

- 尚未开始。

## 12. 偏差或阻塞（子 Agent 更新）

- 无。

## 13. 交付证据（子 Agent 更新）

- 尚未交付。

## 14. 主 Agent 验收结果

- 尚未验收。
