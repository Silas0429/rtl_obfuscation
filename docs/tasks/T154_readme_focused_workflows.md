# T154：README 只保留实际使用的 FAST / FULL 教程

- 状态：`ACCEPTED`
- 负责人：Main Agent；文档修正，无子 Agent
- 前置：T153 已验收并推送；两个分支工作区干净

## 目标与范围

按用户反馈，将两个分支 README 缩成快速上手教程。只展示实际推荐的 filelist 加密：FAST 用 `delivery/fast-local-signals` 的 `signals` 且不传 `--top`；FULL 用 `main` 的 `all` 并在教程中明确传入 `--top "$TOP"`。删除单文件/filelist/project-root 三模式分类及冗长内部说明。解释教程中每个加密参数，保留简短结果检查和恢复。

允许修改两分支各自的 `README.md` 和本任务单。不改 CLI、RTL、测试或其他文档。Formal verification：N/A，文档修正不修改 RTL 改写实现。

## 验收

- 两分支 README 不出现 `--input`、`--source-root`、project-root 或三模式分类；FULL 命令实际含 `--top "$TOP"`，FAST 命令无 `--top`、无 rate。
- 分别在 FAST 和 main 分支用仓库样例重放教程风格加密与解密，检查严格编译、逐字节恢复；FULL 检查四组类别与传入的 top。
- 两分支 `git diff --check HEAD`、README 相对链接检查通过；只提交允许文件。

## 执行记录

- status: ACCEPTED；2026-09-29 Main Agent 完成两个分支的精简文档和黑盒验收
- changed_files: 两分支各自的 `README.md` 与本任务单；未改 CLI、RTL 或测试
- commands_and_results:
  - FAST：`conda run -n rtl_obfuscation python rtl_encrypt.py --filelist tests/fixtures/t130_fast_local_signals/design.f --rewrite-root tests/fixtures/t130_fast_local_signals/owned --category signals --output-dir /private/tmp/t154-fast.RKU96C/gate`，exit 0；strict compile、restore byte identical 均为 true，仅有 signals 记录；decrypt 后 4 个 `.sv` 与输入逐字节相同。FAST 路由测试 `tests.test_t130_fast_local_signals.T130FastLocalSignalsTests.test_fast_path_skips_slow_catalog_index_and_forbidden_stages` 1/1 PASS。
  - FULL：在 main worktree 运行 `conda run -n rtl_obfuscation python rtl_encrypt.py --filelist rtl_samples/example_fifo/design.f --rewrite-root rtl_samples/example_fifo --top fifo_top --category all --output-dir /private/tmp/t154-full.gxy0Fi/gate`，exit 0；报告 top=`fifo_top`，四组记录齐全，strict compile、restore byte identical 均为 true；decrypt 后 4 个 `.sv` 与输入逐字节相同。
  - 两分支 README 都为 109 行；禁用入口关键字 0、断链 0、`git diff --check HEAD` exit 0。
- Main_Agent_acceptance: 文档只保留两条推荐工程加密命令和其参数；FULL 命令明确含 `--top "$TOP"`。Formal verification N/A，本次无 RTL 实现变更。
