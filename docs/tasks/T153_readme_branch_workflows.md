# T153：README 的 FAST / FULL 用户入口

- 状态：`ACCEPTED`
- 负责人：Main Agent；文档任务，无子 Agent 实现
- 起点：`delivery/fast-local-signals` 为 `219e768`，`main` 为 `e6070f6`；两分支工作区干净
- 前置：两分支已有 filelist、展平交付和恢复能力；当前无活动任务

## 单一目标

更新两个交付分支的 `README.md`，让真实工程用户可直接按服务器、仓库、Python 环境、路径变量、加密、检查和恢复步骤使用；清楚区分 FAST 分支的快速 signals 与 main 分支的四组全量语义流程，并解释公开加密参数。

## 范围与客观验收

- 允许修改：两分支各自的 `README.md` 和本任务单。不改 CLI、算法、RTL、fixture 或其他规划文档。
- README 命令必须满足 CLI 实际条件：FAST 必须是 filelist、rewrite-root、仅 signals、无 top/rate；main 的 `all` 展开四组。
- 输出目录须尚不存在；本地 wheel 示例须明确限定 CPython 3.11 / Linux x86_64；用户命令保持 plain `python`。
- 各分支用仓库样例或 fixture 重放 README 风格的加密、读取 JSON/summary、解密和逐字节比较；FAST 样例须确认路由，main 样例须确认四组类别。
- `conda run -n rtl_obfuscation python rtl_encrypt.py --help` 和 `git diff --check HEAD` 通过；文档相对链接存在。
- Formal verification：N/A；本任务不生成或修改 RTL 实现，黑盒试运行只验证已有 CLI 与文档一致。

## 执行记录与验收

- status: ACCEPTED；2026-09-29 Main Agent 完成两分支文档与独立验收
- changed_files: 两分支的 `README.md` 与本任务单；无产品代码、fixture 或测试改动
- commands_and_results:
  - FAST：`conda run -n rtl_obfuscation python rtl_encrypt.py --filelist tests/fixtures/t130_fast_local_signals/design.f --rewrite-root tests/fixtures/t130_fast_local_signals/owned --category signals --output-dir /private/tmp/t153-fast.RlDRXv/gate`，exit 0；`mapping.json` 中只有 signals 记录（6 条，5 个 rename），`strict_compile_passed=true`、`restored_byte_identical=true`；运行 `rtl_decrypt.py` 后 4 个 `.sv` 与原文件逐字节相同。
  - FAST 路由：`conda run -n rtl_obfuscation python -m unittest tests.test_t130_fast_local_signals.T130FastLocalSignalsTests.test_fast_path_skips_slow_catalog_index_and_forbidden_stages -v`，exit 0，1 test OK。
  - FULL：在 main worktree 运行 `conda run -n rtl_obfuscation python rtl_encrypt.py --filelist rtl_samples/example_fifo/design.f --rewrite-root rtl_samples/example_fifo --category all --output-dir /private/tmp/t153-main.EryQOF/gate`，exit 0；`mapping.json` 包含 signals、ports、interface、struct 四组，`strict_compile_passed=true`、`restored_byte_identical=true`；运行 `rtl_decrypt.py` 后 4 个 `.sv` 与原文件逐字节相同。
  - 两分支：`conda run -n rtl_obfuscation python rtl_encrypt.py --help`、README 相对链接存在性检查、`git diff --check HEAD` 全部 exit 0。
- boundaries: 不代表真实服务器工程完成编译或 Formal；示例路径由用户替换。
- Main_Agent_acceptance: 对照两分支真实 CLI、路由谓词和输出执行黑盒检查，接受文档修改；Formal verification N/A，未修改产品 RTL 改写实现。
