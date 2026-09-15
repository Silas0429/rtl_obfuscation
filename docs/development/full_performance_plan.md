# FULL 性能优化：两步执行计划

- 状态：`IN_PROGRESS`
- 冻结基线：`main@448647d`（2026-09-15）
- 主 Agent：边界、冻结测试、独立验收、接受与 Git 交付。
- 实现 Agent：Luna xhigh；一次只实施一张 READY 合同，不提交、不推送。

## 目标与证据

减少 FULL 中重复的基础设施工作，不降低可改名候选的判定强度。历史服务器日志提示 SourceCatalog
是优先方向；本次固定物理 RTL、仅改变实例数的本地实验同时显示 RenameIndex / Mapping 的成本。
不能把任一小样本的收益当作真实服务器的整体加速承诺。

基线只读实验：1 个 489-byte 源文件、2 个 module，INSTANCE_COUNT=1/16/64/256；物理源码 SHA256
`9864372fbd41f3ca1520dd205d605d7ad04ed23601b6bde038deb7af1826e5af`，始终 6 个候选、10 个 occurrence，
decision digest `907359d987087a31f96578b91f8bcd32fd00aa0358e9b7c3723b95f104abc5b6`。
完整物理集合重建次数为 7/22/70/262；单独声明匹配实验的 2/17/65/257 个物理 module
触发 5/170/2210/33410 次 SourceRange 相等比较。

## 第一步：SourceCatalog 的不可变元数据和声明索引（T140）

在每次构建内部，只构造一次完整 compile_order + included_files 集合，并在辅助函数之间传递。
显式 top 路径把反复线性匹配改为 `(file, start, end)` 集合查询。保留先 inventory、再 top closure、
再 owner registry 的执行顺序和全部诊断优先级。

本步不缓存已解析文件路径、物理 token 字节或完整 declaration range：路径可能被删除、替换或发生
symlink 重定向；先只复用 SourceSet 中不可变的成员关系，保留原有逐次路径与字节检查。
这是对初始 path-cache 提议的保守收敛，不为少一次路径解析引入复杂的文件失效机制。

验收：三个 compile 分支每 build 一次集合构造；声明匹配不再二次增长；文件删除、目录替换、等长字节
替换、symlink 逃逸继续拒绝；T108/T115 完整决策摘要不变；actual-gate compile、restore、Formal 正负例。
通过后单独接受、提交并推送，随后才创建第二张合同。

## 第二步：复用已完成的语义名称收集（后续合同）

在 RenameIndex 的既有完整有序遍历中收集 Mapping 所需的名称集合，避免 Mapping 再次遍历相同 root。
仅传递不可变字符串集合，不长期持有第二份全树节点，不引入全局或磁盘缓存。
复用必须绑定同一次构建的真实 catalog / compilation / root / source manager 身份；替换 envelope
不能使用旧名称。具体接口及失效负例由主 Agent 在第一步 ACCEPTED 后冻结。

NameFactory 当前收取不可变 frozenset 快照；不通过改为共享可变 set、跳过未选择类别名称、删除冲突
检查来提速。只有独立实验表明有额外兼容优化且无需扩大接口时才纳入本步，否则保留原合同。

验收：Mapping 额外完整 root.visit 从 1 降为 0；候选决策、确定性 mapping、完整禁用名称集合与每次
factory 快照内容保持一致；旧/替换 catalog 不得命中；依旧跑 actual-gate compile、restore 和 Formal
正负例。若需要改变错误优先级或候选边界，停止并与用户讨论，不自行扩大计划。

## 共同禁区与最终审计

- 不迁移 FAST；all 仍为 signals、ports、interface、struct 四组。
- 不裁剪 filelist/include 物理集合，不把 rewrite-root 变成解析边界。
- 不改 no-top ABI（已知独立正确性议题）、供应商判定、宏、dead-source、name-completeness、
  owner/binding、range/manifest、readonly 或 duplicate-provider 规则。
- 不删 gate 的重建/严格校验，不引入 token/full-file 快照、跨构建缓存、守护进程或新依赖。
- 不运行 RISC-V-Vector 或 blanket discovery，不删除历史测试。

两步各自使用一张任务合同、最多五条验收命令。主 Agent 独立重跑后才能 ACCEPTED / commit / push。
最后用相同输入和参数复测结构计数及阶段时间，明确 SourceSet / mapping / gate 的计时范围，记录仍存
的热点；没有真实服务器同输入重跑就不声明服务器加速倍数。最终审计不是第三个实现任务。

## 执行结果

T140 已由主 Agent 独立验收：5 个目标测试、46 个冻结回归均通过；三分支集合构建次数由
12/15/9 降至各 1；17/65 个物理 module 的线性 SourceRange 比较由 170/2210 降至 0，
改用物理键集合查询。actual-gate / relocated export Formal 正例通过、固定功能负例拒绝。
第二步待建立独立合同。
