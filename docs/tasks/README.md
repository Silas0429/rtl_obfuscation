# 子 Agent 任务单流程

本目录中的已验收任务单保留当时的合同、命令和验收证据，历史路径或数量不代表当前用户接口。
当前使用说明以根目录 `README.md`、`docs/systemverilog_renaming_table.md`、
`docs/formal_verification.md` 和 `docs/future_work.md` 为准。

## 1. 一次只允许一个活动任务

每个实现步骤对应 `docs/tasks/TNNN_*.md`。同一时间只能有一张任务单处于 `IN_PROGRESS` 或 `READY_FOR_REVIEW`。

状态及修改权限：

| 状态 | 含义 | 谁可以设置 |
| --- | --- | --- |
| `DRAFT` | 主 Agent 正在设计任务 | 主 Agent |
| `READY` | 输入、输出和验收条件已冻结，可开始 | 主 Agent |
| `IN_PROGRESS` | 子 Agent 已阅读任务并开始实现 | 子 Agent |
| `BLOCKED` | 发现任务边界内无法继续的问题 | 子 Agent |
| `READY_FOR_REVIEW` | 实现和自测完成，等待主 Agent 验收 | 子 Agent |
| `ACCEPTED` | 黑盒验收通过 | 主 Agent |

## 2. 子 Agent 强制更新点

子 Agent 必须在以下时刻先更新任务单，再继续操作：

1. **开始前**：把状态从 `READY` 改成 `IN_PROGRESS`，填写“执行记录”的开始项。
2. **发现边界变化时**：把问题写入“偏差或阻塞”。不得自行扩大范围。
3. **完成实现后**：填写变更文件、实际命令、实际输出和未覆盖边界，再把状态改成 `READY_FOR_REVIEW`。
4. **验证失败时**：保持 `IN_PROGRESS` 或改成 `BLOCKED`，不得标成完成。
5. **产生改写 RTL 时**：必须按 `docs/formal_verification.md` 运行任务合同要求的 Yosys，并在任务单记录 gold、gate、top、退出码和 JSON；失败时不得申请验收。RISC-V-Vector Formal 仅允许在专门的 RISC-V-Vector 验收任务中运行，普通任务不得触发其 formal-view/formal-align/Yosys 流程。

主 Agent 验收后负责：

- 独立执行任务单中的所有命令。
- 对产生改写 RTL 的任务独立重跑任务合同要求的 Yosys formal equivalence；RISC-V-Vector Formal
  不属于常规验收或全量回归，只有专门的 RISC-V-Vector 验收任务明确要求时才运行。
- 常规全量回归必须显式枚举并排除 `tests.test_risc_v_vector_project_root`；不得用会自动运行该
  模块的 blanket `unittest discover` 代替。只有专门的 RISC-V-Vector 验收任务或历史合同明确
  要求时，才运行包含该模块的回归。
- 对照输入输出而不是只阅读代码。
- 将状态改成 `ACCEPTED`。
- 若对外行为发生变化，同步根目录 `README.md`、重命名表或未来事项，
  然后再创建下一张任务单。
- 检查 Git diff，执行 `git add .`、带规定类型前缀的 `git commit` 和 `git push`。

## 3. 任务单必备字段

每张任务单必须包含：

- 状态和负责人。
- 单一目标。
- 固定输入。
- 预期机器可读输出。
- 明确包含和不包含的功能。
- 允许修改的文件。
- 可复制的验收命令。
- 子 Agent 的执行记录和交付证据。
- Formal verification 状态、输入和结果；不产生 RTL 的任务必须明确写 `N/A` 及原因。
- 主 Agent 的验收结果。

没有明确预期输出的任务不得进入 `READY`。

## 4. 子 Agent 行为边界

- 只修改任务单列出的文件。
- 不增加兼容层、fallback、缓存、插件或额外配置格式。
- 不顺手实现下一任务。
- 不通过放宽测试、忽略诊断或修改 fixture 来制造通过结果。
- PySlang API 与文档不一致时，记录实际 API 和最小复现，随后停止等待主 Agent。
- 所有 Python、EDA 和测试命令都使用 `conda run -n rtl_obfuscation`。
- 不得删除 `equiv_status -assert`、忽略 Yosys 非零退出码或用 gold/gate 同一文件冒充改写等价证据。
- 子 Agent 不得自行 commit 或 push；Git 提交由主 Agent 在验收通过后统一完成。

## 5. Git 交付规则

任务达到 `ACCEPTED` 后，主 Agent执行：

```sh
git add .
git commit -m "[TYPE] concise description"
git push
```

commit 类型只能使用：`[FEAT]`、`[FIX]`、`[REFACTOR]`、`[PERF]`、`[DOCS]`、`[TEST]`、`[CHORE]`、`[STYLE]`。提交与推送结果应写入已验收任务或主 Agent 交付说明。远端缺失、认证失败或网络失败时必须明确报告。

## 6. Formal verification 记录格式

产生改写 RTL 的任务必须填写：

```text
formal_verification: PASS | FAIL | BLOCKED
gold: <original .sv>
gate: <rewritten .sv>
top: <unchanged top module>
command: <exact conda run command>
exit_code: <integer>
result: <stdout JSON or failure summary>
```

只产生映射或 source range 的任务填写：

```text
formal_verification: N/A
reason: no rewritten RTL is produced by this task
```
