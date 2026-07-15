# T024：使用说明正式流程排序

- 状态：`ACCEPTED`
- 负责人：主 Agent
- 前置任务：T023 `ACCEPTED`

## 目标

调整根目录 `read.md` 第 3 节的阅读顺序：

1. 先说明单文件/多文件模式差异；
2. 先说明 Category 选择；
3. 单文件完整流程按加密、formal、解密执行；
4. 介绍 `rtl_samples/example_fifo` 的四文件构成；
5. 多文件完整流程按加密、formal、解密执行；
6. 最后分别说明单文件 debug 和多文件 debug。

## 验收结果

- `read.md` 已按指定顺序重排，所有正式操作命令均以 `python` 开头。
- 单文件流程中包含 `encrypt` 、`formal_equivalence.py` 和 `decrypt`。
- 多文件 FIFO 构成在加密流程之前说明，流程中包含 `encrypt-project`、
  `formal_equivalence.py` 和 `decrypt-project`。
- 单文件/多文件 debug 位于两套完整流程之后。
- `git diff --check` 通过。
- 本任务只修改使用说明，`formal_verification: N/A`。
- 主 Agent 验收：`ACCEPTED`。
