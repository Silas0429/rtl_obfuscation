# T067：README wheel 安装指南与 PDF 同步

- 状态：ACCEPTED
- 合同版本：1.0
- 设计时间：2026-07-30
- 设计负责人：主 Agent
- 前置任务：T066 `ACCEPTED`
- 起始 HEAD：`3e8e186`
- 任务类型：用户安装文档与发布材料

## 1. 目标

在 README 开头增加仓库内离线 PySlang wheel 的安装方法，列出 `wheel/` 当前提供的文件及适用 Python、
操作系统和架构；同时重新生成 README PDF，并将 wheel、README、README PDF 和任务记录作为一次交付提交。

## 2. 固定事实

当前 wheel：

```text
wheel/pyslang-11.0.0-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.whl
```

适用范围：CPython 3.11、Linux x86_64、glibc 2.17 或更高版本。

## 3. 固定用户操作

README 必须提供：

1. 直接安装到当前 Python 环境；
2. 创建并激活 Python 3.11 虚拟环境，再安装 wheel 和运行项目；
3. 安装后的 `import pyslang` 检查；
4. 不适用平台的说明，并链接完整离线部署指南。

用户命令使用 `python` 或 `python3.11`，不得写入 Conda 前缀。

## 4. 允许修改

```text
README.md
README.pdf
docs/pyslang源码编译与离线部署指南.pdf
docs/systemverilog_renaming_table.pdf
wheel/pyslang-11.0.0-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.whl
docs/tasks/T067_wheel_installation_readme_pdf.md
```

不得修改产品代码、RTL fixture、其他用户文档或开发文档。

## 5. 验收要求

- README 安装说明与 wheel 文件名、平台标签一致；
- 直接安装和虚拟环境安装命令完整且可复制；
- 三个 PDF 与各自 Markdown 内容一致，文本可提取，页面渲染无截断、方框或重叠；
- 用户文档回归、`git diff --check HEAD` 通过；
- 不运行 RISC-V-Vector Formal；本任务不改变 rewritten RTL。

## 6. 执行记录与主 Agent 验收

- 当前 wheel 已核对：
  `wheel/pyslang-11.0.0-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.whl`，适用
  CPython 3.11、Linux x86_64、glibc 2.17+。
- README 已增加当前环境直接安装和 Python 3.11 虚拟环境安装两种命令，并提供 `import pyslang`
  验证和不适用平台说明。
- 用户文档回归：1/1 通过，exit code 0。
- `git diff --check HEAD`：通过。
- PDF 文本检查：README 6 页、PySlang 指南 12 页、类型表 2 页，关键标题和 wheel 文件名均可提取。
- PDF 已渲染检查首页、代表性中间页和末页；中文字体、表格、代码块、列表、页码无截断、方框或重叠。
- 未修改产品代码、RTL fixture 或其他用户/开发文档；未运行 RISC-V-Vector Formal。
- 结论：T067 合同全部满足，主 Agent 已将状态设为 `ACCEPTED`。
