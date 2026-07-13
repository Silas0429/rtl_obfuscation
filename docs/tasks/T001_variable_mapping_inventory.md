# T001：单文件内部变量映射清单

- 状态：`ACCEPTED`
- 设计负责人：主 Agent
- 实现负责人：子 Agent

> 历史说明：T004 的定义调整将公开类别 `variables` 与 `nets` 合并为 `signals`。本任务保留原 CLI 和输出名称作为当时的验收证据。

## 1. 单一目标

读取一个合法 SystemVerilog 文件，使用 PySlang 找出 module 内部的 `variables`，根据 `name_length` 为它们生成随机合法名称，并把映射 JSON 输出到 stdout。

本任务只证明“内部变量语义识别 + 固定长度随机名称映射”可行，不修改任何 RTL。

## 2. 固定输入

```text
input_file  = rtl_samples/01_continuous_assign.sv
category    = variables
name_length = 8
```

运行命令固定为：

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.inventory \
  --input rtl_samples/01_continuous_assign.sv \
  --category variables \
  --name-length 8
```

## 3. 预期输出

stdout 必须是一个合法 JSON 对象，不混入日志。解析 JSON 后必须满足：

```json
{
  "version": 1,
  "name_length": 8,
  "entries": [
    {
      "category": "variables",
      "scope": "sample01_continuous_assign",
      "original_name": "and_result",
      "renamed_name": "Q7m2_xAa"
    }
  ]
}
```

`Q7m2_xAa` 只是格式示例，不是固定输出。实际 `renamed_name` 必须匹配：

```text
^[A-Za-z][A-Za-z0-9_]{7}$
```

entry 可以额外包含 `declaration.file/start/end`，但不得增加其他映射条目。

以下 port 不得被当成本任务的 `variables` 输出：

```text
input_a
input_b
output_y
```

相同命令连续运行可以产生不同的新名称，但每次输出都必须满足长度、字符集合、非关键字和无冲突要求。

## 4. 本任务包含

- 使用当前环境的 `pyslang.syntax.SyntaxTree` 和 `pyslang.ast.Compilation`。
- 识别单个 module 中的内部 `Variable`。
- 去除 ANSI port 背后的重复 `Variable`。
- 按声明位置稳定排序。
- 使用 Python 标准库 `secrets` 生成长度为 8 的名称。
- 排除 SystemVerilog 关键字、输入中已有标识符和本次已分配名称。
- 使用 Python 标准库 `argparse`、`json` 和 `secrets`。
- 一个只针对固定输入的 `unittest` 黑盒测试。

## 5. 本任务明确不包含

- 修改 SystemVerilog 源文件。
- 收集变量引用或 source edit。
- 多文件 compilation、filelist、include、define。
- 其他重命名类别。
- preserve 配置、YAML、映射文件落盘。
- 随机 seed 参数、随机性统计、反向映射。
- 宏、interface、class、package、DPI 或错误恢复。
- 为未来任务预建通用框架。

## 6. 允许修改的文件

```text
rtl_obfuscator/__init__.py
rtl_obfuscator/inventory.py
tests/__init__.py
tests/test_variable_inventory.py
docs/tasks/T001_variable_mapping_inventory.md
```

不得修改 RTL fixture、重命名表、实施计划或其他文档。

## 7. 子 Agent 自测命令

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_variable_inventory

conda run -n rtl_obfuscation python -m rtl_obfuscator.inventory \
  --input rtl_samples/01_continuous_assign.sv \
  --category variables \
  --name-length 8
```

## 8. 主 Agent 黑盒验收

- `unittest` 退出码为 0。
- CLI 退出码为 0，stdout 可直接由 `json.loads` 解析。
- 输出只有 `and_result` 一个 entry。
- `renamed_name` 长度严格为 8，并匹配 `^[A-Za-z][A-Za-z0-9_]{7}$`。
- `renamed_name` 不是 SystemVerilog 关键字，不等于任何输入标识符。
- 三个 port 均未出现在 entries。
- 实现没有修改任何 `.sv` 文件。

## 9. 执行记录（子 Agent 更新）

- 2026-07-10 18:17 CST：已阅读 `docs/tasks/README.md`、本任务合同及其范围资料；确认 T001 是唯一活动任务，开始按合同实现。
- 2026-07-10 18:23 CST：完成内部 `Variable` 收集、ANSI port 底层变量去重、声明位置排序、随机合法名称生成及固定输入黑盒测试。
- PySlang 11 实测 API 与项目文档一致：`PortSymbol.internalSymbol` 与 semantic AST 中对应的 `VariableSymbol` 是同一对象，可直接用于 ANSI port 去重。

## 10. 偏差或阻塞（子 Agent 更新）

- 无。

## 11. 交付证据（子 Agent 更新）

- 变更文件：
  - `rtl_obfuscator/__init__.py`
  - `rtl_obfuscator/inventory.py`
  - `tests/__init__.py`
  - `tests/test_variable_inventory.py`
  - `docs/tasks/T001_variable_mapping_inventory.md`
- 自测命令：

  ```sh
  conda run -n rtl_obfuscation python -m unittest tests.test_variable_inventory
  ```

  实际退出码：`0`。实际输出：

  ```text
  .
  ----------------------------------------------------------------------
  Ran 1 test in 0.059s

  OK
  ```

- CLI 命令：

  ```sh
  conda run -n rtl_obfuscation python -m rtl_obfuscator.inventory \
    --input rtl_samples/01_continuous_assign.sv \
    --category variables \
    --name-length 8
  ```

  实际退出码：`0`。实际 stdout：

  ```json
  {
    "version": 1,
    "name_length": 8,
    "entries": [
      {
        "category": "variables",
        "scope": "sample01_continuous_assign",
        "original_name": "and_result",
        "renamed_name": "YWOisugd"
      }
    ]
  }
  ```

- RTL fixture 检查：从任务开始时间起执行 `find rtl_samples -type f -name '*.sv' -newermt '2026-07-10 18:17:26' -print`，无输出；没有修改 `.sv` 文件。
- 未覆盖边界：不收集变量引用、不生成 source edit、不修改 RTL；不处理多文件、其他重命名类别、配置/映射落盘、宏/interface/class/package/DPI 或错误恢复，均保持在 T001 明确排除范围内。

## 12. Formal verification

```text
formal_verification: N/A
reason: T001 only emits a mapping inventory and does not produce rewritten RTL
```

不得使用输入文件与自身做 identity equivalence 并把它记为 T001 功能证据。

## 13. 主 Agent 验收结果

- 2026-07-13 独立验收通过，状态设为 `ACCEPTED`。
- 单元测试：

  ```sh
  conda run -n rtl_obfuscation python -m unittest tests.test_variable_inventory
  ```

  退出码 `0`，`Ran 1 test ... OK`。
- 固定 CLI 输入独立执行成功，stdout 为合法 JSON；本次得到唯一映射 `and_result -> l7OenXK4`。
- 额外连续执行 25 次黑盒检查：
  - 每次恰好一个 entry。
  - 25 个随机新名称均不同。
  - 所有新名称均匹配 `^[A-Za-z][A-Za-z0-9_]{7}$`。
  - `input_a`、`input_b`、`output_y` 均未作为 `variables` 输出。
  - 新名称均不等于固定输入中的已有标识符。
- Formal verification：`N/A`，因为 T001 不产生改写 RTL。
- 验收边界：本结论只覆盖 T001 固定单文件和 `variables` 映射清单，不代表引用收集、源码替换、映射落盘或反向恢复已经实现。
