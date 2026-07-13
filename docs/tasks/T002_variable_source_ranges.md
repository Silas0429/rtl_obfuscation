# T002：内部变量声明与引用范围清单

- 状态：`ACCEPTED`
- 设计负责人：主 Agent
- 实现负责人：子 Agent
- 前置任务：T001 `ACCEPTED`

## 1. 单一目标

在 T001 映射清单的基础上，找出目标内部变量声明及所有语义绑定引用的源码字节区间，并把 range 加入 stdout JSON。

本任务只证明“同一变量的声明与引用可以被完整、精确定位”，仍不修改任何 RTL。

## 2. 固定输入

```text
input_file     = rtl_samples/01_continuous_assign.sv
category       = variables
name_length    = 8
include_ranges = true
```

固定命令：

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.inventory \
  --input rtl_samples/01_continuous_assign.sv \
  --category variables \
  --name-length 8 \
  --include-ranges
```

## 3. Range 定义

- `start` 和 `end` 是输入文件 UTF-8 原始字节中的半开区间 `[start, end)`。
- `file` 固定输出传入 CLI 的相对路径 `rtl_samples/01_continuous_assign.sv`。
- 每个区间对应且只对应 identifier token，不包含空白、标点或注释。
- 对任一区间读取 `source_bytes[start:end]`，结果必须等于 `original_name.encode()`。
- declaration 与 references 分开保存；references 按 `start` 升序排列并去重。

## 4. 预期输出

stdout 必须是合法 JSON，且只有 `and_result` 一个 entry。随机名称仅作格式示例：

```json
{
  "version": 1,
  "name_length": 8,
  "entries": [
    {
      "category": "variables",
      "scope": "sample01_continuous_assign",
      "original_name": "and_result",
      "renamed_name": "Q7m2_xAa",
      "declaration": {
        "file": "rtl_samples/01_continuous_assign.sv",
        "start": 202,
        "end": 212
      },
      "references": [
        {
          "file": "rtl_samples/01_continuous_assign.sv",
          "start": 226,
          "end": 236
        },
        {
          "file": "rtl_samples/01_continuous_assign.sv",
          "start": 280,
          "end": 290
        }
      ]
    }
  ]
}
```

预期总 occurrence 数为 3：1 个 declaration 加 2 个 references。

## 5. 最小实现机制

- 复用 T001 的目标变量收集结果，不重新实现另一套变量筛选。
- declaration 使用目标 `VariableSymbol.location.offset` 和 `len(symbol.name)`。
- reference 只接受 semantic AST 中满足 `NamedValueExpression.symbol is target_symbol` 的节点。
- reference identifier range 使用 syntax identifier token 的 location 和 raw text 长度。
- 输出前验证所有 range 位于同一输入文件、互不重复，且对应原始字节确实为 `and_result`。

## 6. 本任务包含

- 为现有 CLI 增加一个显式 `--include-ranges` 选项。
- 输出 declaration 和 references range。
- 固定样例的 range 黑盒测试。
- 保持不带 `--include-ranges` 的 T001 测试继续通过。

## 7. 本任务明确不包含

- 修改或输出 SystemVerilog RTL。
- 应用 source edit。
- 映射文件、metrics 文件或反向恢复。
- Assignment、port、net、parameter 等其他类别。
- HierarchicalValue、member access、跨文件引用、宏引用。
- 为 T003 预建 rewrite CLI 或输出目录管理。

## 8. 允许修改的文件

```text
rtl_obfuscator/inventory.py
tests/test_variable_ranges.py
docs/tasks/T002_variable_source_ranges.md
```

不得修改 RTL fixture、T001 测试、Yosys 脚本、实施计划或其他任务文档。

## 9. 子 Agent 自测命令

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_variable_inventory \
  tests.test_variable_ranges

conda run -n rtl_obfuscation python -m rtl_obfuscator.inventory \
  --input rtl_samples/01_continuous_assign.sv \
  --category variables \
  --name-length 8 \
  --include-ranges
```

## 10. 主 Agent 黑盒验收

- 两个 unittest 均通过。
- stdout 可由 `json.loads` 直接解析。
- 只有 `and_result` 一个 entry，端口仍被排除。
- declaration 精确为 `[202, 212)`。
- references 精确为 `[226, 236)`、`[280, 290)`。
- 三个区间切出的字节都严格等于 `and_result`。
- 所有 range 唯一、升序、无重叠。
- 不带 `--include-ranges` 时仍保持 T001 JSON 结构。
- 没有新增或修改任何 `.sv` 文件。

## 11. Formal verification

```text
formal_verification: N/A
reason: T002 only emits declaration/reference ranges and does not produce rewritten RTL
```

## 12. 执行记录（子 Agent 更新）

- 2026-07-13 11:18 CST：已阅读 `docs/tasks/README.md` 和本任务合同；确认 T001 已 `ACCEPTED`、T002 是唯一 `READY` 任务，开始按合同实现。
- 2026-07-13 11:21 CST：完成声明与 `NamedValueExpression` 绑定引用的 identifier byte range 收集、排序、去重和源码字节验证，并完成 T001/T002 联合回归。
- PySlang 11 实测与任务合同一致：目标引用的 `NamedValueExpression.symbol is target_symbol` 为真，`syntax.identifier.location.offset` 和 `rawText` 可直接构造精确字节区间。

## 13. 偏差或阻塞（子 Agent 更新）

- 无。

## 14. 交付证据（子 Agent 更新）

- 变更文件：
  - `rtl_obfuscator/inventory.py`
  - `tests/test_variable_ranges.py`
  - `docs/tasks/T002_variable_source_ranges.md`
- 联合回归命令：

  ```sh
  conda run -n rtl_obfuscation python -m unittest \
    tests.test_variable_inventory \
    tests.test_variable_ranges
  ```

  实际退出码：`0`。实际输出：

  ```text
  ..
  ----------------------------------------------------------------------
  Ran 2 tests in 0.128s

  OK
  ```

- Range CLI 命令：

  ```sh
  conda run -n rtl_obfuscation python -m rtl_obfuscator.inventory \
    --input rtl_samples/01_continuous_assign.sv \
    --category variables \
    --name-length 8 \
    --include-ranges
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
        "renamed_name": "EuWhnq1p",
        "declaration": {
          "file": "rtl_samples/01_continuous_assign.sv",
          "start": 202,
          "end": 212
        },
        "references": [
          {
            "file": "rtl_samples/01_continuous_assign.sv",
            "start": 226,
            "end": 236
          },
          {
            "file": "rtl_samples/01_continuous_assign.sv",
            "start": 280,
            "end": 290
          }
        ]
      }
    ]
  }
  ```

- T001 兼容性检查：不带 `--include-ranges` 的 CLI 退出码为 `0`，entry 仍只有 `category`、`scope`、`original_name`、`renamed_name`，未出现 range 字段。
- RTL fixture 检查：从任务开始时间起执行 `find . -type f -name '*.sv' -newermt '2026-07-13 11:18:56' -print`，无输出；没有新增或修改 `.sv` 文件。
- Formal verification：`N/A`，本任务只输出 declaration/reference ranges，不产生 rewritten RTL；未运行 identity equivalence。
- 未覆盖边界：不应用 source edit、不输出或修改 RTL；不处理其他类别、hierarchical/member access、跨文件或宏引用，也未预建 T003 rewrite 功能。

## 15. 主 Agent 验收结果

- 2026-07-13 独立验收通过，状态设为 `ACCEPTED`。
- 联合回归：

  ```sh
  conda run -n rtl_obfuscation python -m unittest \
    tests.test_variable_inventory \
    tests.test_variable_ranges
  ```

  退出码 `0`，共 2 个测试通过。
- CLI 独立执行成功，本次随机映射为 `and_result -> qpXeLP9D`。
- declaration 为 `[202, 212)`；references 为 `[226, 236)`、`[280, 290)`。
- 三个范围切出的源字节均严格等于 `and_result`，范围唯一、升序且无重叠。
- 端口 `input_a`、`input_b`、`output_y` 均未进入 `variables` entry。
- 不带 `--include-ranges` 的 T001 JSON 字段保持不变。
- Formal verification：`N/A`，因为 T002 不产生改写 RTL。
- 验收边界：只覆盖固定单文件的 `NamedValueExpression` 引用，不代表源码改写、反向恢复或跨文件引用已经实现。
