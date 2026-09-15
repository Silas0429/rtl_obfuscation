# FULL RenameIndex 性能与规则扩展性

- 状态：`IN_PROGRESS`
- 起点：`main@1b9feb7c74dae4ca5fbc02f022183fe18769b6f7`
- 用户目标：使用主 Agent / 子 Agent 合作优化 FULL，保持未来候选变量及准入规则的扩展能力。
- 本计划接续已完成的 T140/T141；不改变其历史验收。

## 两步实施

1. T142：完整 CST 分母不变，只对 records 尚未解释的 token 补充声明 / 引用证明。
   所有 eligible / wanted / rewritten_starts 每次按本次记录重新计算；不缓存准入结果。
2. T142 接受后再创建下一张合同：复用同 root 分类中的 alias 事实，以及同次端口登记中成功的
   declaration。保留完整 top 节点遍历和唯一分类条件；不得用另一份节点类型白名单预筛选。
   每实例 owner / target / support / reason 仍重新判断；失败重试顺序不变。

主 Agent 冻结输入、回归与合同，子 Agent 实现并交付 READY_FOR_REVIEW；主 Agent 独立重跑包括
实际改名 gate Formal 的验收后才 ACCEPTED、提交与推送，一次只有一个实现任务。

## 扩展性不变量

- 优化只复用同一次构建内已验证的事实，不持久化 eligible / preserve 或规则选择结果。
- 新候选、同名新记录、不同 category 选择以及准入规则变化都重新形成完整证明义务。
- generic aggregate、完整 token/unverified、edited-target、错误/诊断顺序维持原规则。
- 新增语义节点类型时只更新原分类规则；性能分支不得再维护第二份类型名单。
- 如果未来改变证明证据的含义，或在完整性之后重新开放候选，必须重新执行适用证明并补回归。

## 验证与最终测量

每步冻结 structural work counts、完整决策及 Mapping、strict gate、byte restore、compact actual-gate
Formal 正例和固定功能负例。新增扩展性回归只模拟未来候选 / 准入变化，不新增公共加密类别。
不运行 RISC-V-Vector 或 blanket discovery，不缩小 filelist/rewrite-root 检查范围。

最终主 Agent 在子 Agent idle 时串行比较起点与最终提交：重复实例、唯一物理信号、保留顶层端口
三种样例；记录核心阶段、公开 CLI 和独立进程峰值内存。所有同输入语义结果必须一致。
此前隔离原型的本地收益仅用于选方向；正式实现重新测量，不承诺服务器加速倍数。

## 实施结果

T142 已由主 Agent 独立接受：8 项目标测试和 21 项冻结回归通过，新增候选与准入变化、完整决策 /
Mapping、strict gate、byte restore、实际 gate Formal 正例与单 bit 功能负例通过。
第二步及最终性能测量待完成。
