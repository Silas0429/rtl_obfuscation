# T066：用户文档与开发文档分层整理

- 状态：ACCEPTED
- 合同版本：1.0
- 设计时间：2026-07-29
- 设计负责人：主 Agent
- 前置任务：T065 `ACCEPTED`
- 起始 HEAD：`9bb439a`
- 任务类型：文档结构与用户指南整理

## 1. 目标

将仓库文档按读者分层：

- 根目录 `README.md` 和 `docs/` 直下文档只服务于用户安装、加密、解密、可加密类型和独立 Formal 验证；
- 项目结构、架构方案、重构规范、未来计划等开发资料放入更深的 `docs/development/` 层级；
- 保留 `docs/tasks/` 作为任务合同和验收记录目录。

同时完善 README 的用户文档导航，并将 `docs/formal_verification.md` 改写为用户可直接执行的独立验证说明。

## 2. 固定目录约定

```text
README.md                                  用户快速开始
docs/README.md                             用户文档索引
docs/systemverilog_renaming_table.md       可加密类型
docs/formal_verification.md                独立 Formal 验证
docs/pyslang源码编译与离线部署指南.md      PySlang 离线安装
docs/development/                          开发资料
docs/development/architecture/             架构与路线图
docs/development/process/                  开发流程与子 Agent 规范
docs/tasks/                                任务合同与历史验收
```

## 3. 允许修改

- `README.md`
- `AGENTS.md`
- `docs/README.md`
- `docs/formal_verification.md`
- `docs/pyslang源码编译与离线部署指南.md`
- `docs/development/**`
- `docs/tasks/README.md`
- `rtl_samples/README.md`
- 本任务记录

允许移动现有开发文档，但不得修改产品代码、RTL fixture 或历史任务合同正文。

## 4. 验收要求

- README 的用户命令和报告路径保持可执行，新增安装、Formal 和开发资料导航；
- Formal 文档只展示用户需要的准备条件、命令、成功/失败判断和边界，不把内部架构作为主线；
- 用户文档位于 `docs/` 直下，开发文档位于 `docs/development/` 或更深层级；
- 所有当前入口文档链接指向存在的文件；
- 文档不把 Conda 路径写入用户命令，用户命令使用 `python`；
- `git diff --check HEAD` 通过，且不运行 RISC-V-Vector Formal。

## 5. 执行记录与主 Agent 验收

- 用户文档保留在 `docs/` 直下：`README.md`、`systemverilog_renaming_table.md`、
  `formal_verification.md` 和 `pyslang源码编译与离线部署指南.md`。
- 开发文档已移动到 `docs/development/`，并按 `architecture/`、`process/` 继续分层；
  `docs/tasks/` 保持为任务合同与历史验收目录。
- README 已新增用户文档导航，并明确离线 PySlang 安装指南、类型表、Formal 和开发文档入口。
- `docs/formal_verification.md` 已重组为用户流程：使用场景、准备条件、单文件/多文件命令、结果判断、
  失败处理和 RISC-V-Vector 边界；用户命令均使用 `python`，没有写入 Conda 前缀。
- 当前入口文档本地链接检查：18 个 Markdown 文件全部通过。
- 用户文档回归：2/2 通过，exit code 0。
- `git diff --check HEAD`：通过。
- 未修改产品代码、RTL fixture 或历史任务合同正文；未运行 RISC-V-Vector Formal。
- 结论：T066 合同全部满足，主 Agent 已将状态设为 `ACCEPTED`。
