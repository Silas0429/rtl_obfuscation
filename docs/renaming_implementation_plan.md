# SystemVerilog 重命名功能实施计划

## 1. 目标与唯一范围

本项目只实现 [systemverilog_renaming_table.md](systemverilog_renaming_table.md) 中列出的重命名类别。该表是“重命名什么、哪些位置必须同步修改、默认是否启用”的唯一事实来源。

实现原则：

- 一次只实现一个可独立验收的小功能。
- 每个功能必须提供明确输入、机器可读输出、边界和黑盒验证命令。
- PySlang semantic AST 是符号身份和引用绑定的事实来源。
- PySlang syntax API 提供源码 token/range；Verible 和 Icarus 只用于验证，不参与第一版重命名决策。
- 不做字符串全局替换。
- 不要求开发者通过深入阅读实现代码来判断功能是否正确。

## 2. 第一版明确不做

为了保持实现可审核，第一版不处理：

- 宏定义或宏展开中的声明与引用。
- 缺失源码、未解析符号、外部层次引用和 DPI ABI。
- include 路径、宏 define、library/config 的自动发现。
- 原地修改输入文件。
- 旧配置、旧映射格式或不同 PySlang 版本的兼容。
- 并行处理、缓存、插件系统、通用 parser abstraction。
- 加密映射文件、密码学安全或对攻击强度的承诺。

输入必须是 UTF-8、可由当前 Conda 环境中的 PySlang 完整解析并且没有 error diagnostic 的 SystemVerilog 源文件。遇到范围外情况应停止并报告，不增加 fallback。

## 3. 最小数据模型

实现只需要三个核心对象：

```text
SymbolKey
  category          表中的重命名类别
  scope             PySlang 语义作用域路径
  original_name     原名称
  declaration       文件路径和声明 token 的 [start, end) 字节区间

RenameEntry
  symbol_key
  renamed_name

SourceEdit
  file
  start
  end
  replacement
```

不要在实际需要前增加继承层次、数据库或框架。

## 4. 最小实现流水线

每个类别沿同一条纵向路径实现：

1. PySlang 解析全部显式输入文件并建立 `Compilation`。
2. 按语义对象收集该类别的声明，生成稳定 `SymbolKey`。
3. 排除端口底层变量等重复语义对象，并按声明源码区间去重。
4. 按 `文件路径、声明起始位置、类别` 排序，使映射条目顺序稳定。
5. 生成固定长度的随机合法名称和 JSON 映射。
6. 收集声明及所有已绑定引用的 `SourceEdit`。
7. 验证 edit 不重叠、原文与预期旧名称一致。
8. 每个文件从后向前应用 edit，写入独立输出目录。
9. 重新用 PySlang、Verible、Icarus 检查输出。
10. 按 [formal_verification.md](formal_verification.md) 使用 Yosys 证明 gold/gate 等价。
11. 使用反向映射恢复，再进行文本级往返比较。

新增类别时只扩展第 2、3、6 步的“类别规则”，不得复制整条流水线。

### 4.1 内部信号统一定义

公开重命名类别使用单一 `signals`，不再分别暴露 `variables` 和 `nets`。`signals` 只收集 module 作用域内、非 port 的具名 PySlang `VariableSymbol` 与 `NetSymbol`；源码可以写成 `logic`、`reg`、`wire` 或 `tri`。两种 symbol kind 只影响内部收集，不影响 mapping、source edit、metrics 或反向恢复流程。

端口的 `internalSymbol` 必须从集合中排除。parameter、genvar、subroutine argument、interface member 和 aggregate field 不并入 `signals`。

## 5. 名称和映射格式

第一版使用由 `name_length` 控制的随机合法名称：

```text
首字符：A-Z 或 a-z
后续字符：A-Z、a-z、0-9 或下划线
```

例如名称长度为 8 时，可能生成 `Q7m2_xAa`。约束如下：

- `name_length >= 4`；当前 CLI 要求显式传入 `--name-length`，项目示例统一使用 8。
- 输出长度必须严格等于 `name_length`。
- 使用 Python 标准库 `secrets` 作为生产随机源，不暴露随机 seed 参数。
- 新名称不得是 SystemVerilog 关键字。
- 新名称不得等于 compilation 中已有的用户标识符，也不得与本次运行已分配的新名称重复。
- 发生关键字或名称冲突时重新生成；同一名称连续尝试 1000 次仍未成功时直接失败。
- 映射 entry 的顺序稳定，但每次不加载已有映射的新运行可以产生不同的新名称。
- 映射 JSON 是可逆恢复的依据；该算法本身不宣称密码学安全。

最终映射文件采用一个固定、无兼容分支的 schema：

```json
{
  "version": 1,
  "name_length": 8,
  "entries": [
    {
      "category": "signals",
      "scope": "sample01_continuous_assign",
      "original_name": "and_result",
      "renamed_name": "Q7m2_xAa",
      "declaration": {
        "file": "rtl_samples/01_continuous_assign.sv",
        "start": 0,
        "end": 0
      }
    }
  ]
}
```

JSON 中的 entry 按 `SymbolKey` 稳定排序。字段缺失、版本不等于 1 或重复的新名称都直接报错。

本项目尚未发布外部 mapping 格式，因此此次类别合并直接用 `signals` 替换旧的 `variables` 值，schema 版本仍为 1，不增加旧值兼容分支。T004 完成后应重新生成临时 mapping；T001—T003 文档中的旧值只保留为历史验收证据。

测试不得依赖真实随机输出的具体字符串。名称生成器的单元测试可以注入或 mock 随机字符选择；CLI 黑盒测试只检查长度、字符集合、关键字、冲突和映射数量。

## 6. 最终功能输入与输出边界

### 输入

- 一组显式 `.sv` 文件路径。
- 启用的重命名类别。
- `name_length`。
- 正向操作时可选的已有映射；反向操作时必须提供映射。

### 输出

- 独立输出目录中的 SystemVerilog 文件，不修改输入。
- 一个版本固定的 JSON 双向映射。
- stdout 中只输出简短汇总：输入文件数、映射条目数、修改 token 数。
- 失败信息写 stderr，并返回非零状态。

### 成功条件

- 目标类别的声明和全部可解析引用使用同一个新名称。
- 非目标类别和注释、字符串、空白保持不变。
- 重命名后 PySlang 无新增 error，Verible 和 Icarus 通过。
- 产生改写 RTL 时，Yosys formal equivalence 必须通过；只输出映射/range 时明确记录 `N/A`。
- 反向恢复后的文件与原输入字节一致。

## 7. 实施顺序

采用纵向小切片，先完成一个类别的端到端能力，再扩展类别。

| 阶段 | 内容 | 状态 |
| --- | --- | --- |
| T001 | `signals` 的 VariableSymbol 子集映射清单（当时 CLI 名为 `variables`） | ACCEPTED |
| T002 | `signals` 的 VariableSymbol 声明与引用 range（当时 CLI 名为 `variables`） | ACCEPTED |
| T003 | `signals` 的 VariableSymbol 正向改写、恢复和文本往返（当时 CLI 名为 `variables`） | ACCEPTED |
| T004 | 公开类别迁移为 `signals`，加入内部 NetSymbol 并保持端到端流程 | ACCEPTED |
| T005 | 单个 module value parameter 的端到端流程 | ACCEPTED |
| T006 | 单个 type parameter 的语义映射与类型引用 range，不改 RTL | DEFERRED |
| T007 | 多 entry + `reg/tri` + localparam + enum values 高复用批次 | ACCEPTED |
| T008 | 单个 `genvar` 的展开归一化、5-token 改写与 formal | ACCEPTED |
| T009 | `functions`、`tasks`、`arguments` 单文件批次 | ACCEPTED |
| T010 | 当时已支持的 7 个 category 的单文件串联、整体 formal 和逆向恢复 | ACCEPTED |
| T011 | 当时已支持的 7 个 category 的单次全量加密、单 mapping 和单次恢复 | ACCEPTED |
| T012 | 单文件 `instances`、`generate_blocks` | ACCEPTED |
| T013 | 单文件 `typedefs`、`struct_types`；`type_parameters` 继续由 T006 暂缓 | READY |
| T014 | 单文件 `struct_fields`、`union_fields` | ACCEPTED |
| T015 | 多文件 Compilation、per-file edits、mapping v2 和 project formal | READY |
| T016 | 多文件非 top `modules`、child `ports` | PLANNED |
| T017 | `interfaces`、`interface_instances` | PLANNED |
| T018 | `interface_ports`、`modports`、`modport_ports` | PLANNED |
| T019 | 全类别组合、默认/显式 ABI 类别和完整项目回归 | PLANNED |

后续阶段只有在类别共享同一 collector、source-range 机制和验证 fixture 时，才允许在
一个任务合同中列成可独立验收的子项；否则必须拆分。上表只表示实现顺序，不授权
一次性实现整行。

恢复开发时不得直接启动 T013 实现。主 Agent 必须先为 `typedefs` 和
`struct_types` 完成 PySlang API/Yosys 预探测，再创建唯一的 T013 任务合同并冻结
fixtures、精确 ranges、输出计数和 formal 命令。T006 保持 `DRAFT`；Yosys 0.53
不能读取当前 `parameter type` fixture，在没有新的可执行 formal 策略前不得把
type parameter RTL 改写并入 T013。

## 8. 黑盒验收标准

主 Agent 和开发者只需要检查任务单中的以下证据：

1. 固定输入文件。
2. 可复制的运行命令。
3. 实际 JSON/RTL 输出路径。
4. 明确列出的预期映射条目和明确不应出现的条目。
5. PySlang、Verible、Icarus 的命令及退出状态。
6. 产生改写 RTL 时，Yosys gold/gate/top、命令、退出状态和 PASS JSON。
7. 正反向文本比较结果；仅在进入实际改写阶段后要求。
8. 任务边界内与边界外项目列表。

上述证据缺一项，任务不得标记为 `ACCEPTED`。

## 9. 加密效果指标

formal verification 通过是正确性门禁，不计入效果分数。第一版只报告以下五项：

| 指标 | 定义 |
| --- | --- |
| 加密代码行覆盖率 | 包含至少一个已改名 token 的有效代码行数 / 有效代码行总数 |
| 符号覆盖率 | 已重命名的独立符号数 / 按配置可重命名的独立符号数 |
| 引用覆盖率 | 已重命名的声明和引用 token 数 / 目标符号全部声明和引用 token 数 |
| 原名残留率 | 输出可执行代码中残留的目标原名 token 数 / 输入目标原名 token 数 |
| 有效加密覆盖率 | `sqrt(符号覆盖率 * 引用覆盖率)` |

所有分母只包含配置允许重命名且 compilation 完整解析的目标；preserve 项、宏、DPI、未解析符号和范围外源码不得进入分母。

报告使用固定 JSON 结构：

```json
{
  "affected_lines": {"changed": 0, "total": 0, "rate": 0.0},
  "symbols": {"renamed": 0, "eligible": 0, "coverage": 0.0},
  "occurrences": {"renamed": 0, "eligible": 0, "coverage": 0.0},
  "plaintext_leakage_rate": 0.0,
  "effective_coverage": 0.0
}
```

效果指标 JSON 不负责运行 formal。Yosys 结果由 `scripts/formal_equivalence.py` 独立输出 PASS JSON，并作为额外正确性门禁。映射清单阶段只需要提供能够计算的计数；从 T003 实际改写开始，五项指标都必须输出。

## 10. 文档和任务入口

- 功能范围：[systemverilog_renaming_table.md](systemverilog_renaming_table.md)
- 工具和语义背景：[pyslang_verible_systemverilog_renaming_guide.md](pyslang_verible_systemverilog_renaming_guide.md)
- 形式等价流程：[formal_verification.md](formal_verification.md)
- 任务状态流程：[tasks/README.md](tasks/README.md)
- 已验收 T001：[tasks/T001_variable_mapping_inventory.md](tasks/T001_variable_mapping_inventory.md)
- 已验收 T002：[tasks/T002_variable_source_ranges.md](tasks/T002_variable_source_ranges.md)
- 已验收 T003：[tasks/T003_variable_rewrite_roundtrip.md](tasks/T003_variable_rewrite_roundtrip.md)
- 已验收 T004：[tasks/T004_internal_net_roundtrip.md](tasks/T004_internal_net_roundtrip.md)
- 已验收 T005：[tasks/T005_value_parameter_roundtrip.md](tasks/T005_value_parameter_roundtrip.md)
- 暂缓 T006：[tasks/T006_type_parameter_ranges.md](tasks/T006_type_parameter_ranges.md)
- 已验收 T007：[tasks/T007_reusable_single_file_batch.md](tasks/T007_reusable_single_file_batch.md)
- 已验收 T008：[tasks/T008_genvar_roundtrip.md](tasks/T008_genvar_roundtrip.md)
- 已验收 T009：[tasks/T009_subroutine_batch.md](tasks/T009_subroutine_batch.md)
- 已验收 T010：[tasks/T010_supported_categories_integration.md](tasks/T010_supported_categories_integration.md)
- 已验收 T011：[tasks/T011_one_pass_all_categories.md](tasks/T011_one_pass_all_categories.md)
- 后续架构设计：[multifile_interface_port_struct_design.md](multifile_interface_port_struct_design.md)
- 已验收 T012：[tasks/T012_instance_generate_block_roundtrip.md](tasks/T012_instance_generate_block_roundtrip.md)
- 当前交接入口：[project_handoff.md](project_handoff.md)
