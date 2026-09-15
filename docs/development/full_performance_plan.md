# FULL 性能优化：两步执行计划

- 状态：`COMPLETE`
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
T140 已提交并推送为 `457259a`。T141 已由主 Agent 独立验收：9 个目标测试、37 个冻结回归通过；
三分支 Mapping 额外 root.visit 均降为 0，完整确定性 Mapping 报告、T108/T115 决策摘要保持不变，
actual-gate / relocated export Formal 正例通过、固定功能负例拒绝。两张合同均为 ACCEPTED。

### 最终本地测量（2026-09-15）

环境：Conda rtl_obfuscation，Python 3.12.13，PySlang 11.0.0。旧版本使用 `git archive 448647d`
解出的隔离临时源码，不切换 main 或回退工作区；顺序为旧→新→旧→新，所有运行串行、子 Agent idle。
每个进程各规模先 warm-up 1 次、再测 5 次，因此每版本/规模汇总 10 个 warm 样本的中位数。
固定 489-byte / 1-file / 2-module RTL，仅 INSTANCE_COUNT 改变；所有运行均为 all + top + rewrite-root，
6 个候选 / 10 个 occurrence，decision digest 与开头基线一致，实际 gate 字节发生改名并恢复逐字节一致。

计时范围为 SourceSet + run_vnext 核心流水线，包含 gate 的严格重编译、restore 和审计；不包含
Python/CLI 启动、公开 filelist 三视图发布、终端显示和实验结束的临时目录清理。没有把核心流水线
结果称为完整 CLI 或服务器端到端收益。

| 实例数 | 旧核心流水线 ms | 新核心流水线 ms | 减少 | 旧 Mapping ms | 新 Mapping ms |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 7.771 | 7.722 | 0.6%（接近噪声） | 0.358 | 0.124 |
| 64 | 94.685 | 88.045 | 7.0% | 7.483 | 0.198 |
| 256 | 355.426 | 327.105 | 8.0% | 28.693 | 0.220 |

256 实例的其他中位阶段：SourceSet 0.468→0.465ms，SourceCatalog 28.610→28.374ms，
RenameIndex 259.567→261.183ms，gate 35.272→34.888ms，restore 0.586→0.579ms。
各阶段中位数不必恰好相加等于 total 中位数。该单文件场景主要节省 Mapping 的重复名称访问；
不能从集合构造次数的巨大下降推导 SourceCatalog 同比例加速。

结构复测：INSTANCE_COUNT=1/16/64/256 的集合重建均为 1（原为 7/22/70/262），真实路径检查和
token 读取仍为 7/22/70/262。2/17/65/257 个物理 module 的声明匹配实验，原 SourceRange equality
次数 5/170/2210/33410 变为 0，使用每声明一次的物理键查询，而非删除匹配校验。

本轮可复查的临时实验入口（非持久化公共工具，/tmp 可能被系统清理）：

```sh
conda run -n rtl_obfuscation python /tmp/full_pipeline_benchmark.py /tmp/full-perf-baseline.uh8HzC 448647d
conda run -n rtl_obfuscation python /tmp/full_pipeline_benchmark.py /Users/lufengchi/Desktop/workspace/rtl_obfuscation T140+T141
conda run -n rtl_obfuscation python /tmp/full-performance-explore.LDE5OG/probe.py
conda run -n rtl_obfuscation python /tmp/full-lookup-pressure.As3r1h/probe.py
```

持久回归由 T140/T141 合同中的冻结测试提供，不依赖这些临时路径。没有运行 RISC-V-Vector。

### 结论与未覆盖范围

本轮完成两个低风险、行为保持的优化，但不是 FULL 大规模提速的终点。256 实例样例剩余约 80%
时间在 RenameIndex，其中语义 inventory、声明、name-completeness 和 occurrence 处理仍随实例展开增长。
SourceCatalog 的逐次真实路径/字节检查与 gate 重建也保留。进一步复用 owner/range 或合并跨层遍历，
需要另行冻结来源有效性、内存与错误优先级合同，不在本轮自行扩大。

名称快照额外存活的空间为 O(唯一语义名称数)，不长期保留第二份全树；本轮未做大型工程峰值内存测量。
真实服务器的复杂项目尚未按相同输入重跑，因此没有服务器提速倍数承诺。no-top ABI 仍是单独的
正确性议题，本轮未改变它。
