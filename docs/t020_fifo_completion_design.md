# T020 FIFO 收口设计：occurrence 闭包与状态重命名 formal

## 1. 目的

本文冻结 T020 最后一轮实现方法。任务验收值和执行命令仍以
[`tasks/T020_example_fifo_per_file_mapping.md`](tasks/T020_example_fifo_per_file_mapping.md)
为准；本文只说明为什么需要这些修改，以及实现不得突破的技术边界。

本轮只解决两个已复现问题：

1. `view.entry.valid` 和 `view.entry.payload` 中的 union member `entry` 已被 PySlang
   语义绑定，但内层 `MemberAccessExpression.syntax` 为 `None`，现有 collector 丢失两个
   reference occurrence；
2. FIFO 内部 signal、state 和 memory 被重命名后，当前 Yosys 流程不能仅凭名称建立
   gold/gate 对应关系，并且 `$mem_v2` 无法直接进入现有 SAT 证明。

本轮不新增 category，不修改冻结 FIFO gold，不放宽 frontend、decrypt、metrics 或 formal
门禁。最终摘要冻结为 `77 mapping entries / 292 modified tokens`。

## 2. 根因与设计约束

### 2.1 Collector 根因

PySlang 对同一语义类别可能提供不同的 AST/CST 形态。parameter dimension、named parameter
override、type reference、generate-loop reference 和嵌套 aggregate member 不能假定都具有
`NamedValueExpression.syntax` 或 `MemberAccessExpression.syntax.right`。

collector 必须先按 PySlang symbol identity 确认引用属于目标 entry，再取得 source range。
不得先按文本搜索名称再猜测 symbol，也不得为了满足计数复制 range。

### 2.2 Union member source-range 回退

对目标 struct/union field 的 `MemberAccessExpression`，统一执行：

1. 仅当 `node.member is target` 时接受该语义引用；
2. `node.syntax.right.sourceRange` 可用时，使用现有精确 token range；
3. syntax 不可用时，从 `node.sourceRange.end.offset` 向前取 `len(target.name)` 个字节，作为
   最右侧 member identifier 的候选 range；
4. 必须验证候选源码切片严格等于 `target.name`，且 range 位于当前 source file；验证失败
   立即报错，不做全局搜索或模糊匹配；
5. declaration/reference 合并后按 `(file, start, end, role)` 去重，并继续执行 edit
   不重叠和 gold byte 校验。

该规则必须由 project 和单文件 collector 共用。对冻结 FIFO，它只应新增 `entry` 的两个
reference，使 `union_fields` 从 `2/4` 变为 `2/6`，完整组合从 `77/290` 变为 `77/292`。

### 2.3 Formal 根因

`equiv_make` 会利用可对应的名称建立 presumed equivalence。内部状态和 RAM 名称被随机改写
后，单纯的 `equiv_simple`/`equiv_induct` 无法恢复全部状态对应关系；未展开的 `$mem_v2`
也没有当前流程可用的 SAT model。

gold 和 gate 必须对称执行相同转换：

```yosys
prep -top <top> -flatten
memory_map -formal
opt_clean
```

在 `equiv_make` 和 `hierarchy -top equiv` 后增加：

```yosys
equiv_struct -icells
```

随后仍必须执行：

```yosys
equiv_simple -seq <seq>
equiv_induct -seq <seq>
equiv_status -assert
```

不得删除 `equiv_status -assert`，不得只检查部分 `$equiv` success，也不得只用 identity
comparison 证明脚本可运行。

## 3. 分阶段实现顺序

### 阶段 A：先关闭 occurrence 缺口

只修改 member reference range 提取和对应测试。完成后必须先得到：

- `union_fields = 2 entries / 6 tokens`；
- 完整组合 `77 entries / 292 tokens`；
- global mapping 与四个 per-file mapping 的 occurrence 并集完全一致；
- PySlang、Verible、Icarus 全部通过；
- decrypt 字节级恢复，`plaintext_leakage_rate = 0.0`。

任何 frontend 仍失败时不得进入 formal 修改，也不得再次调整冻结计数。

### 阶段 B：补齐专项回归

必须新增并纳入 unittest discovery：

- `tests/test_parameter_dimension_rewrite.py`；
- `tests/test_example_fifo_project.py`；
- `tests/test_formal_equivalence.py`。

测试必须覆盖 parameter dimension/named override、type reference、generate-loop `DEPTH`、
两个 `entry` reference、不同长度重命名后的 leakage offset、19 类 debug 摘要、per-file
mapping 并集和 decrypt round-trip。不得只报告既有 25 项测试通过。

### 阶段 C：增强并验证 formal

单文件和多文件脚本路径必须使用相同的对称 memory/structural flow。验收同时要求：

1. 完整 `77/292` FIFO gate 对 gold formal 通过；
2. 测试在临时目录把 FIFO 的计数增量从 1 改为 2，formal 必须非零退出；
3. 既有 `tests/formal/variable_rename` 正例继续通过、负例继续失败。

负向变体只能在测试临时目录生成，不得修改 `rtl_samples/example_fifo/` 或把负向结果提交为
产品 gate。

## 4. 停止条件

以下任一情况发生时，子 Agent 保持 `IN_PROGRESS` 或记录 `BLOCKED`，不得申请验收：

- 完整摘要不是严格的 `77/292`；
- 需要修改冻结 FIFO gold 才能继续；
- source range 不能由语义绑定加精确字节校验得到；
- 任一 frontend、decrypt、mapping union、metrics 或 unittest 失败；
- FIFO formal 正例失败，或任一 formal 负例被误判为通过；
- 需要新增 category、修改 mapping schema 或扩大到 T020 明确排除的语法。

这些情况必须先在 T020 的“偏差或阻塞”中记录最小复现、精确命令和实际输出，再交由
主 Agent 决定，不得自行修订契约数字或验收标准。

## 5. 交付责任

子 Agent 只能把 T020 设置为 `READY_FOR_REVIEW`，不得执行 Git stage、commit 或 push。
主 Agent 必须独立重跑完整黑盒回归、FIFO formal 正例和 formal 负例，确认工作区没有越界
修改后才能设置 `ACCEPTED` 并统一提交。
