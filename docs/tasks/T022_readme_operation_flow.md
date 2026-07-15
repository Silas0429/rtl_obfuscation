# T022：使用说明操作流程调整

- 状态：`ACCEPTED`
- 负责人：主 Agent
- 前置任务：T021 `ACCEPTED`

## 目标

重排根目录 `read.md` 的“基本操作”：

1. 先说明单文件与多文件模式的输入、输出、mapping、category 和适用场景差异；
2. Category 选择必须出现在正式加密命令之前；
3. 以 `rtl_samples/example_fifo` 为操作样例，先介绍四文件构成和 filelist，
   再说明多文件加密、查看、debug、验证与解密流程；
4. 保留单文件加密与解密的完整命令。

## 允许文件

- `read.md`
- `docs/tasks/T022_readme_operation_flow.md`

## 验收

- 文档结构符合上述顺序，公开命令仍直接以 `python` 开头。
- FIFO 完整加密仍为 `77/292`，parameter debug 仍为 `9/51`。
- 单文件样例仍为 `23/63`。
- `git diff --check` 通过。

## 验收结果

- `read.md` 已按“模式差异→Category→单文件操作→FIFO 构成→多文件操作”重排。
- 单文件实际加密/解密为 `23/63`，mapping version 1，恢复字节一致。
- 多文件 FIFO 实际加密/解密为 `77/292`，mapping version 2，四个 per-file
  mapping 存在，恢复四文件字节一致。
- 结构顺序检查、公开命令 `python` 前缀检查和 `git diff --check` 通过。
- 本任务只修改文档，`formal_verification: N/A`。
- 主 Agent 验收：`ACCEPTED`。
