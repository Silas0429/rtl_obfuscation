# T009：function、task 与 arguments 批次

- 状态：`DRAFT`
- 设计负责人：主 Agent
- 实现负责人：子 Agent
- 前置任务：T008 必须先达到 `ACCEPTED`

> 本文用于固化下一批次范围。T008 接受前禁止子 Agent启动 T009；主 Agent 还需冻结 fixtures、byte ranges、metrics 和完整 formal 命令后才能将状态设置为 `READY`。

## 1. 批次目标

在单文件、ordered arguments 和 Yosys 可综合语法边界内，一次实现并统一验收：

1. `functions`：function 声明、普通 ordered call、传统 function 返回赋值。
2. `tasks`：task 声明、普通 ordered call。
3. `arguments`：function/task 形式参数声明及 subroutine 内部引用。

## 2. 计划固定输入

主 Agent 将在 T009 进入 `READY` 前创建并冻结：

```text
tests/fixtures/t009_function_argument.sv
tests/fixtures/t009_task_argument.sv
```

两个 fixture 必须分别通过 PySlang、Verible、Icarus 和手工重命名后的 Yosys formal probe。

## 3. 已确认的 PySlang 机制

- function/task 均由 `SubroutineSymbol` 表示。
- 普通调用由 `CallExpression.subroutine` 绑定目标，不是 NamedValueExpression；调用 token 位于 invocation syntax 左侧 identifier。
- 传统 function 返回赋值左侧绑定 `Subroutine.returnValVar`，function 名改写必须包含该 token。
- argument 是 `FormalArgumentSymbol`，正文普通引用按 symbol identity 收集。
- element-select 等位置的 NamedValueExpression 可能没有 `node.syntax`；range collector 必须支持 semantic sourceRange 定位，不得因 `node.syntax is None` 崩溃。
- ordered actual expressions 属于调用者，不随 formal argument 重命名。

## 4. 计划实现结构

- inventory/rewrite CLI 增加 `functions`、`tasks`、`arguments`。
- functions/tasks 共用最小 SubroutineSymbol collector 和 CallExpression reference collector。
- arguments 共用 FormalArgumentSymbol collector 和现有 NamedValue source identity，增加无 syntax 时的最小 range fallback。
- 所有类别复用现有 multi-entry mapping、全局 source edits、decrypt、metrics 和 formal 流程。
- 每个 category 使用独立 encrypt/decrypt 输出，最后统一运行累计回归和 formal。

## 5. 当前明确排除

- 命名实参 `.argument(...)`：当前 Yosys frontend 不支持，无法满足 formal 门禁。
- `return expression;`：当前 Yosys frontend 对现有样例语法不支持；function fixture 使用传统 `function_name = result;`。
- extern/prototype、DPI import/export、recursive function、package/class method。
- 多文件、package scope、hierarchical subroutine call。
- T006 type parameter、genvar、module/port 或 instance。

## 6. READY 前主 Agent 必须补齐

- 两个冻结 fixture 的完整源码。
- 每个 category 的 declaration/reference byte ranges。
- 每个 CLI 的 mapping entry 和 modified token 数。
- 五项 metrics 固定值。
- unittest 模块名、输出路径和可复制命令。
- 每个 rewritten RTL 的 gold、gate、top 和已预探测可通过的 formal 命令。
- 允许修改文件清单、负测和未覆盖边界。

## 7. 子 Agent 状态

- 尚未授权开始。
