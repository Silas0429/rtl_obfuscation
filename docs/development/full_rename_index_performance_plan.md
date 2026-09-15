# FULL RenameIndex 性能与规则扩展性

- 状态：`COMPLETE`
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
T143 已完成主 Agent 独立验收和最终串行性能 / 内存测量，详见下节。


## 最终生产实现验收与实测（2026-09-15）

两步均已完成：T142 提交 `10cecac`，T143 完成独立验收并随本报告交付。T143 保留完整 top
遍历，并修正探索原型曾存在的失败 False 复用问题；本表只报告正式实现，不沿用原型速度。

主 Agent 最终独立运行 20 项 T143/T142 目标测试、21 项 T128/T129/T141 回归，全部通过。
新增候选、准入放开/收紧、跨名称 edited-target、generic provider、未知节点类型、两层属性失败
重试、同位置不同实例、不同 top 长度和顺序均有冻结回归。实际改名 gate 与 gold 不同；严格编译、
完整确定性 Mapping、逐字节还原、`proof_top` seq=5 的 Formal 正例和单 bit 功能负例均通过。
精确命令、gold/gate 路径和 JSON 见 T142/T143 合同的主 Agent 验收节。

升级约束：候选发现和准入判定保持原职责。声明/引用补证 helper 提供可追加的证据；将来的全局
否决规则应放入明确的准入阶段，不能藏入可能被跳过的补证扫描。端口 declaration helper 提供物理
来源事实，策略仍由 owner/category/support 阶段处理。若语义对象要在一次构建中发生变化，须使
事实复用失效或重新构建；当前复用沿用 compile 后语义结构不变的前提。

环境为 Apple M4 / macOS，Conda rtl_obfuscation，Python 3.12.13、PySlang 11.0.0。
起点 `1b9feb7c74dae4ca5fbc02f022183fe18769b6f7` 通过隔离 git archive 运行；已逐文件核对
其产品模块、CLI 与决策 digest helper 的 Git blob，未切换 main。最终 rename_index.py SHA256：
`cfb75b05310bdef7e3679d5ad34d8f4d18a416c5482b55fe8ae02b4c717891e2`；计时开始和结束均一致。

全部测量在子 Agent 停止运行后串行执行，未同时运行 profiler/tracemalloc 或测试。
核心比较顺序为基线 A → 最终 A → 最终 B → 基线 B；每批每样例预热 1 次、测 3 次，
每版本/样例合并 6 个样本中位数，共 24 条汇总、72 次正式样本。

核心计时含 SourceSet、run_vnext、gate 严格重编译、restore 和内部审计；额外 to_report/JSON
序列化单独记录，不包括 CLI 启动和公开 filelist 交付。三种规模分别改变重复实例数、唯一内部
信号数和保留顶层输出端口数；重复实例物理源码固定 489 字节，仅 filelist define 变化。
全部为 all + top + rewrite-root，同输入完整决策、确定性 Mapping、gate 哈希及计数均一致。

| 样例 | 起点核心 s | 最终核心 s | 核心耗时下降 | RenameIndex 耗时下降 |
| --- | --- | --- | --- | --- |
| instances:256 | 0.3268 | 0.2462 | 24.7% | 30.5% |
| instances:1024 | 1.2722 | 0.9608 | 24.5% | 30.3% |
| physical:256 | 0.1937 | 0.1743 | 10.0% | 18.5% |
| physical:1024 | 1.0183 | 0.9497 | 6.7% | 17.3% |
| preserved_ports:512 | 0.2670 | 0.2242 | 16.0% | 23.5% |
| preserved_ports:2048 | 1.2259 | 1.0550 | 13.9% | 22.6% |

公开 CLI 使用正常入口与随机命名，直接调用各版本 rtl_encrypt.py，未注入原型。每样例预热一轮，
再交替版本顺序测 3 轮，共 24 个进程；计时包含进程启动、正常流程、产物发布、stdout 写文件，
不包括输出目录清理。参数为 `--filelist … --top … --rewrite-root … --category all --output-dir … --quiet`。
两版本三个样例最后一次均运行公开 decrypt 并逐字节核对（6 次）；decrypt 不计入加密时间。

| 公开 CLI 样例 | 起点 s | 最终 s | 耗时下降 |
| --- | --- | --- | --- |
| instances-1024 | 1.377 | 1.063 | 22.8% |
| physical-1024 | 1.217 | 1.134 | 6.8% |
| preserved_ports-2048 | 1.467 | 1.288 | 12.2% |

独立进程内存测量另行执行：每次单一 case，0 次预热、1 次完整构建，基线→最终→最终→基线，
共 8 个进程。ru_maxrss 包含 Python 和原生内存及序列化，单位 MiB，每栏为两次实际读数。

| 样例 | 起点峰值 RSS MiB | 最终峰值 RSS MiB |
| --- | --- | --- |
| instances:1024 | 62.12 / 61.2 | 61.61 / 62.14 |
| instances:8192 | 157.16 / 154.75 | 148.64 / 159.22 |

内存读数存在分配器波动，当前规模未显示明显放大，也不能声称峰值一定降低。以上均为本地合成
样例，不代表原服务器完整工程的耗时；未取得服务器同输入新版结果，不换算 6h50m 的加速倍数。
SourceCatalog、occurrences、finalize 释放等剩余热点仍须按新服务器阶段数据选择后续任务。

主 Agent 本轮临时复跑与完整原始证据：

- `/tmp/full-production.JTQGLB/measure_final.py`：串行核心 / 公共 CLI / 独立内存入口；内部通过
  `conda run --no-capture-output -n rtl_obfuscation python /tmp/full-production.JTQGLB/measure_final.py` 执行。
- `/tmp/full-production.JTQGLB/summary.json`、`commands.json`：汇总与实际核心 / decrypt 命令。
- 同目录 `baseline-a/b.jsonl`、`final-a/b.jsonl`：全部阶段样本；`public.json` 含全部公开命令，
  `memory.json` 含独立进程命令与结果；公开 stdout/stderr 和主 Agent 测试日志均保存。
- `/tmp/full-production.JTQGLB/finish_audit.py` 校验完整样本、退出码、哈希、测试及 baseline。

临时路径可能被系统清理；持久化保护由仓库冻结 unittest 和本页汇总、任务合同提供。未创建第三个
实现任务，未新增公共类别、CLI 参数、缓存服务或外部依赖；未运行 RISC 或 blanket discovery。
