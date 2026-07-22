# 统一重构期子 Agent 行为与验收规范

- 文档状态：`APPROVED`
- 适用范围：`docs/three_mode_refactor_plan.md` 的 R0–R5
- 优先级：活动任务合同 > 本规范 > 历史任务单
- 目标：小步实现、证据充分、验收简洁，不为旧 oracle 增加兼容层

## 1. 角色边界

### 1.1 主 Agent

主 Agent 负责：

- 每次只冻结一个单一目标；
- 提供固定输入、输出 schema、允许文件和不超过五条的验收命令；
- 明确任务属于哪一类验收；
- 在任务开始前处理与允许文件重叠的脏工作区；
- 独立复跑任务合同中的黑盒命令；
- 决定 legacy 测试或脚本是否具备删除条件；
- 只有验收通过后才设置 `ACCEPTED`、提交并创建下一任务。

### 1.2 子 Agent

子 Agent 只负责活动任务的实现和自测，不负责重新设计架构、扩大 scope、修改 oracle 或创建下一
任务。子 Agent 不提交、不推送、不把任务设置为 `ACCEPTED`。

## 2. 开始前的强制步骤

子 Agent 在第一次编辑前必须按顺序执行：

1. 完整阅读 `AGENTS.md`、活动任务单、本规范和任务直接链接的设计章节；
2. 确认活动任务状态为 `READY`；
3. 查看 `git status --short --branch`，记录 starting HEAD 和已有未提交文件；
4. 将任务状态改为 `IN_PROGRESS`，填写开始时间、首条命令和允许文件；
5. 检查允许文件是否与用户已有修改重叠；
6. 若重叠且无法确认安全合并，停止并记录，不得覆盖、还原、stash 或移动用户修改；
7. 运行任务合同唯一指定的 baseline 命令。

未完成以上步骤不得修改实现文件。

## 3. 实现过程规范

### 3.1 小步原则

- 一次只实现一个可观察行为；
- 每个行为完成后立即运行最小目标测试；
- 先建立数据合同，再接 inventory，再接 rewrite；
- 不在同一任务中同时迁移输入模型、SymbolGraph、mapping 和 Formal；
- 不因为“顺手”修改演示、README、样例 RTL 或其他 category。

### 3.2 禁止事项

- 禁止新增 v1/v2/v3/v4 兼容写入或模式专用 encrypt 分支；
- 禁止以 fixture 名称、module 名、固定 occurrence 数量控制产品行为；
- 禁止复制旧 collector 后形成第二套 reference/owner 逻辑；
- 禁止全局文本搜索替代语义 owner；
- 禁止捕获异常后跳过对象、降级成功或发布半成品；
- 禁止修改不在任务允许列表中的测试来制造通过；
- 禁止主动运行 RISC-V-Vector Formal，除非活动任务明确是 RISC 专项；
- 禁止使用 blanket `unittest discover` 作为重构任务验收。

### 3.3 允许的最小诊断

当目标测试失败时，子 Agent 可以：

- 增加不写入仓库的只读探针；
- 使用 PySlang 打印 symbol kind、owner、location 和 diagnostics；
- 在任务允许的 compact fixture 中增加一个最小负例；
- 记录 API 实际行为。

如果修复需要新抽象、新依赖、额外文件或改变 schema，必须先记录偏差并停止等待主 Agent。

## 4. 停止条件

遇到以下任一情况，子 Agent 必须停止扩大实现并更新任务单：

- PySlang 实际 API 与冻结设计不一致；
- 同一 physical token 存在多个 owner；
- 支持对象存在无法归属的 declaration/reference；
- filelist 顺序或 compilation-unit 语义无法保持；
- gate 只有删除真实 reference 或忽略 diagnostic 才能通过；
- 需要修改任务允许列表外文件；
- 目标行为与旧 oracle 冲突；
- Formal 需要复制 gold、identity comparison 或修改证明强度才能通过；
- 同一阻塞连续出现并达到项目规定的 BLOCKED 条件。

旧测试失败本身不是扩大兼容的理由。先判断它验证的是当前语义不变量，还是已废弃的 mapping/profile
表面；后者记录到 cleanup manifest，留给授权清理任务。

## 5. 简化验收矩阵

每张任务只选择一行，禁止把所有验收叠加执行。

| 任务类型 | 必需验收 | 不需要 |
| --- | --- | --- |
| 文档/合同 | `git diff --check`，链接和状态检查 | Python、HDL、Formal |
| SourceSet/discovery | 一个目标 unittest 模块、py_compile、diff check | 全量回归、HDL、Formal |
| SymbolGraph/range | 一个目标 unittest 模块、稳定 report/range audit、py_compile | gate、decrypt、Formal |
| rewrite/mapping | 一个目标 unittest 模块、strict gate、decrypt、一个 compact Formal 正例和一个固定功能负例 | RISC、历史全量 oracle |
| adapter 迁移 | 对等入口 normalized 输出、一个 compact end-to-end、必要时复用同一个 compact Formal | 每个入口重复整套 Formal |
| legacy 清理 | replacement coverage、目标回归、无旧入口引用、diff check | 旧验收脚本本身 |
| RISC 发布验收 | 专项脚本、strict gate/decrypt、RISC 正负 Formal | 常规任务重复执行 |

约束：

- 活动任务验收命令通常不超过五条；
- 不产生 rewritten RTL 的任务一律 Formal `N/A`；
- 产生 rewritten RTL 时只要求一个代表性 compact positive 和一个明确 functional negative；
- 大型 RISC Formal 只在 R5 专项任务运行一次；
- exact count 只可作为 compact fixture 的辅助断言，不能替代 gate/decrypt/Formal；
- 主 Agent 复跑同一组命令，不额外叠加历史 acceptance driver。

## 6. 过时验收清理规则

### 6.1 可以删除的条件

旧测试或脚本只有同时满足以下条件才可删除：

1. 活动任务明确列出删除路径；
2. cleanup manifest 说明旧测试验证的行为；
3. 新测试已覆盖仍然有效的语义不变量；
4. 被删除内容只冻结旧 mapping 版本、旧模式分派、旧数量/hash 或已移除 CLI；
5. `rg` 确认产品和文档不再引用该入口；
6. 删除后目标回归通过。

### 6.2 优先清理候选

R5 优先评估：

- `scripts/t029_acceptance.py`；
- `tests/test_risc_v_vector_project_root.py` 中 1091/5741/5527 固定主流程；
- T034/T035 中只断言 default/manual 分派和 mapping v2/v3/v4 的用例；
- `tests/test_t036_encryption_rate.py` 中按 mapping version 分支的兼容矩阵；
- 只验证旧 mapping schema 版本号、旧 decrypt 分派或旧 per-file mapping 格式的用例；
- README 和 formal 文档中的 T029 专用日常命令。

### 6.3 必须保留或迁移的内容

- SystemVerilog 语义 compact fixtures；
- owner、shadowing、generate、dimension、named override 和 interface binding 负例；
- range 字节、重复、重叠和事务发布检查；
- gate strict compilation、decrypt byte identity；
- compact Formal 正例和功能负例；
- RISC 作为最终发布级规模验收的能力，但不保留其数量对产品代码的硬编码。

## 7. 子 Agent 交付记录格式

任务单执行记录保持简短，使用以下字段：

```text
status: READY_FOR_REVIEW | BLOCKED
starting_head:
changed_files:
commands:
results:
schema_or_behavior:
boundaries:
cleanup_candidates:
formal_verification: PASS | N/A | BLOCKED
review_request:
```

不得粘贴完整日志；记录退出码、测试数、关键 JSON 和首个失败诊断即可。

## 8. READY_FOR_REVIEW 条件

子 Agent 只有在以下条件全部满足时才能申请 review：

- 任务单所有目标结果通过；
- 允许文件外无新增修改；
- 没有新增兼容层、fallback 或未授权 schema；
- 目标测试和 diff check 通过；
- rewritten RTL 任务的 compact Formal 正负例符合合同；
- 未覆盖边界和 cleanup 候选已记录；
- 没有把历史 oracle 冲突描述为成功。

主 Agent 验收失败时，任务回到 `IN_PROGRESS` 或 `BLOCKED`，不得通过放宽测试直接接受。
