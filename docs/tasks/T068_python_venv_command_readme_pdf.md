# T068：修正 README 虚拟环境创建命令并同步 PDF

- 状态：ACCEPTED
- 合同版本：1.0
- 设计时间：2026-07-30
- 设计负责人：主 Agent
- 前置任务：T067 `ACCEPTED`
- 起始 HEAD：`b698297`
- 任务类型：用户安装文档修正

## 1. 目标

将 README 虚拟环境安装示例中的 `python3.11 -m venv .venv` 改为用户环境通用的
`python -m venv .venv`，并明确命令执行前应确认当前 `python` 为 CPython 3.11.x。
重新生成 README.pdf。

## 2. 允许修改

```text
README.md
README.pdf
docs/tasks/T068_python_venv_command_readme_pdf.md
```

不得修改产品代码、RTL fixture、wheel 或其他用户/开发文档。

## 3. 验收要求

- README 不再出现 `python3.11 -m venv .venv`；
- README 包含 `python -m venv .venv` 和 Python 3.11.x 前置说明；
- README.pdf 与 README 同步，文本可提取，渲染无截断、方框或重叠；
- 用户文档回归和 `git diff --check HEAD` 通过；
- 不运行 RISC-V-Vector Formal。

## 4. 执行记录与主 Agent 验收

- README 已将虚拟环境命令改为 `python -m venv .venv`，并保留 CPython 3.11.x 前置说明。
- README 中不再出现 `python3.11 -m venv .venv`。
- 用户文档回归：1/1 通过，exit code 0。
- `git diff --check HEAD`：通过。
- README.pdf：6 页，文本可提取且包含新命令；首页渲染检查通过，无截断、方框或重叠。
- 未修改产品代码、RTL fixture、wheel 或其他用户/开发文档；未运行 RISC-V-Vector Formal。
- 结论：T068 合同全部满足，主 Agent 已将状态设为 `ACCEPTED`。
