# 单文件、filelist 与 project-root 统一重构计划

- 文档状态：`APPROVED_DESIGN`
- 决策日期：2026-07-22
- 适用范围：单文件、显式 filelist、`project-root + top`
- 实现状态：R1 已验收；R2-A 准备开始；本文不是活动任务合同
- 历史阻塞任务：T038 保持 `BLOCKED / NOT_ACCEPTED`，已由提交 `e4f3f94` 保存
- 下一步实现草案：[`docs/refactor_next_sourceset_task.md`](refactor_next_sourceset_task.md)
- 已验收输入任务：[`docs/tasks/T039_sourceset_input_contract.md`](tasks/T039_sourceset_input_contract.md)，提交 `5a8b073`
- 当前实现任务：[`docs/tasks/T040_source_catalog_owner_registry.md`](tasks/T040_source_catalog_owner_registry.md)
- 子 Agent 规范：[`docs/refactor_subagent_protocol.md`](refactor_subagent_protocol.md)

## 1. 决策摘要

后续不再把单文件、filelist 和 project-root 维护为三套加密实现。三种入口只负责建立同一种
`SourceSet`，之后统一进入语义分析、对象选择、mapping、改写、gate 审计、metrics 和解密流水线。

```text
single-file --------------------+
explicit filelist --------------+--> SourceSet --> SymbolGraph --> RewritePolicy
project-root --> discover list --+                         |
                                                           +--> mapping vNext
                                                           +--> gate audit
                                                           +--> decrypt / metrics
```

关系定义如下：

1. 单文件是只包含一个 `.sv` 的 filelist 子集；
2. project-root 是 filelist 的自动发现前端：根据必填 top 计算闭包和顺序，再把结果交给同一个
   filelist 引擎；
3. filelist 是核心多文件输入模型，必须保留用户给出的文件顺序、include directories、defines
   和 compilation-unit 语义；
4. `.svh` 作为 include 依赖进入 SourceSet 和物理改写审计，但不作为独立 top/source unit；
5. 新架构允许 breaking change，不再为历史 mapping 和旧执行路径增加兼容分支。

## 2. 三种模式的冻结语义

| 入口 | SourceSet 文件范围 | 未提供 top | 提供 top |
| --- | --- | --- | --- |
| 单文件 | 一个显式 `.sv` 及其可定位 include | 全文件所有 module 只允许非 ABI 改写 | 等价于单文件 filelist + top |
| filelist | 严格按 filelist 顺序的全部 `.sv` 及 include | 所有 module 执行非 ABI 改写 | 全部 module 执行非 ABI 改写；top 闭包内可显式选择 ABI 改写 |
| project-root | 自动发现的 top 闭包和依赖 | 不支持，top 必填 | 生成 canonical SourceSet 后调用同一 filelist 引擎 |

### 2.1 非 ABI 改写

非 ABI 改写应用于 SourceSet 中所有可严格绑定的 module，不因其是否在 selected-top 闭包中而
改变。一个对象只有在声明、全部引用和 owner 都可确认，且不会改变 module 外部名称契约时才
可以改写。存在外部 hierarchical reference、跨边界 shared type 或未解析 owner 时必须
preserve/unsupported，不能按拼写猜测。

### 2.2 ABI 改写

启用 top 后，只有 selected-top 闭包内且在 SourceSet 中闭合的对象可以选择 ABI 改写，包括：

- 非 top module 名及全部绑定的 instance type reference；
- 非 top module ports 及全部绑定的 named connection/body reference；
- 非 top module value parameters 及全部 named override/reference；
- 闭包内 interface、interface port、modport 和跨 module aggregate type；
- 其他经 SymbolGraph 证明为闭包内完整绑定的跨 module 对象。

selected top 自身的 module 名、ports、parameters、interface/type boundary 默认保持
`top_boundary`，不随 child ABI 一起改写。未来如果确有需求，只能通过独立显式能力授权，不能
隐式并入普通 ABI category。

filelist + top 被视为本次改写的 closed world。若某个 ABI 对象在 SourceSet 外仍可能有消费者，
或者 SourceSet 内存在无法解析的使用点，该对象必须 fail-closed。

## 3. 唯一核心数据模型

### 3.1 SourceSet

```text
origin: single-file | filelist | project-root
ordered_source_files: list[str]
included_files: list[str]
include_dirs: list[str]
defines: list[str]
top: str | null
top_closure_files: list[str]
compile_order: list[str]
```

- filelist 顺序是输入合同，不得在进入编译前按路径排序；
- project-root discovery 必须生成确定的 compile order；
- catalog 分析覆盖全部 SourceSet module；top overlay 只负责 closure 和 ABI binding；
- 如果 PySlang 需要 catalog compilation 与 selected-top elaboration 两个语义视图，它们必须共享
  同一个 SourceSet 和 token/owner registry，不能形成两套 inventory 实现。

### 3.2 SymbolGraph

每个 source symbol 只建立一个记录：

```text
symbol_id
category
declaration
owner_module
semantic_owner
occurrences[]
occurrence_provenance
impact: local | cross_module
abi: internal | module_abi | top_boundary
support: eligible | preserved | unsupported
reason
```

`occurrence_provenance` 至少区分 semantic expression、declaration type/dimension、generate syntax、
named connection/override、interface/member 和 lexical fallback。一个物理 range 只能属于一个
symbol；classification 只能读取 SymbolGraph，禁止再次遍历 AST/CST 收集另一份 references。

generate genvar、elaborated iteration parameter、真实 module parameter/localparam 必须先归一化为
source owner，再进入 category 和 policy。任何 syntax fallback 都必须同时具备限定语法上下文、
lexical/semantic owner 证据和 source-byte 校验。

### 3.3 RewritePolicy

```text
rename_internal_for_all_modules: true
rename_abi_in_top_closure: explicit category selection
preserve_top_boundary: true
fail_closed_on_external_or_ambiguous_owner: true
```

category 只决定从 SymbolGraph 选择哪些对象，不能决定使用哪条编译、inventory 或 mapping 路径。

## 4. 统一 mapping 与执行流水线

新实现只写一种 `mapping vNext`。版本号在首张实现任务中冻结；不得继续扩展 v2/v3/v4 分派。

mapping 至少记录：

- SourceSet 和 compile context；
- top、top closure 和 top-boundary policy；
- 每个 entry 的稳定 symbol id、category、owner、declaration、references、provenance 和新旧名称；
- preserved/unsupported 的稳定 reason；
- 输入、gate 和 restored manifests；
- metrics 使用的唯一 effective-line 定义。

固定流水线：

1. 输入适配器建立 SourceSet；
2. 对全部 SourceSet module 建立 catalog semantic view；
3. 如有 top，建立 selected-top overlay 和 ABI closure；
4. 生成唯一 SymbolGraph；
5. RewritePolicy 选择 entries/preserved/unsupported；
6. 全局验证 range 字节、owner、重复和重叠；
7. 一次性按文件倒序应用 edits；
8. 使用同一个 SourceSet/compile context 严格重编译 gate；
9. 审计 mapping、per-file mapping、metrics 和 manifest；
10. 解密并验证所有 SourceSet 物理文件 byte-identical；
11. 产生 rewritten RTL 的任务执行合同要求的 Formal 正例和功能负例。

## 5. 兼容与测试清理策略

### 5.1 兼容边界

- 新核心不再写 v1/v2/v3/v4；
- 新核心不为旧 mapping 保留多套 encrypt/audit 分支；
- 旧 mapping 是否需要一次性离线解密工具，在删除旧路径任务开始前单独决定；默认不进入主 CLI、
  常规回归或新 mapping validator；
- 不允许为了通过旧 oracle 在 SymbolGraph 中增加 fixture 特判或模式专用 fallback。

### 5.2 测试边界

保留能覆盖真实 SystemVerilog 语义形状的 compact fixture，删除或重写只用于冻结旧 mapping
版本、旧路径分派和不完整 occurrence 数量的测试。新核心测试优先验证不变量：

1. 同一 SourceSet 经等价入口得到相同 normalized SymbolGraph/mapping；
2. 无 top 时任何 module ABI 都不改变；
3. 有 top 时只有授权闭包内的 child ABI 改变，closure 外仍完成非 ABI 改写；
4. top boundary 始终保持；
5. 每个 physical range owner 唯一，全部 source bytes 精确匹配；
6. gate strict compilation、decrypt byte identity 和 metrics 一致；
7. compact Formal 正例通过，固定功能负例失败；
8. RISC-V-Vector 精确计数和 manifest 只属于专门发布验收，不作为通用引擎分支条件。

随机命名的连续运行不得要求 mapping/gate byte-identical。确定性测试应使用显式测试命名器，或
比较去除 `renamed_name` 和派生 manifest 后的 normalized 语义结果。

## 6. 顺序任务计划

根据 `docs/tasks/README.md`，T038 未结束前不创建新的活动任务合同。以下是已确认的后续顺序，
具体 TNNN 编号、固定 fixture 和命令在前一任务完成后逐张冻结。

### 阶段 R0：T038 停点收束与变更分流

- 目标：保持 T038 `BLOCKED / NOT_ACCEPTED` 事实，盘点现有改动并把可复用证据映射到后续阶段；
- 不实现新架构，不提交失败的历史合同；
- parameter/genvar compact fixture 和 47-reference 证据归入 R2；
- effective-line 口径归入 R3；
- FIFO/interface/demo 扩展移出核心重构任务；
- Formal verification：`N/A`，仅文档和变更归属记录。

### 阶段 R1：SourceSet 与三入口输入合同

- 详细计划见 [`docs/refactor_next_sourceset_task.md`](refactor_next_sourceset_task.md)；
- 正式任务合同见 [`docs/tasks/T039_sourceset_input_contract.md`](tasks/T039_sourceset_input_contract.md)；
- 单一目标：实现 single-file/filelist/project-root 三个 adapter，输出同一种 SourceSet；
- 保留显式 filelist 顺序，冻结 include/define/header/top/closure 语义；
- project-root 只负责 discovery，不产生独立 inventory；
- 输出为机器可读 SourceSet report，不改写 RTL；
- Formal verification：`N/A`。

### 阶段 R2：统一 SymbolGraph 与 owner/provenance

- 单一目标：在 SourceSet 上生成唯一、无重叠、owner 完整的 SymbolGraph；
- R2-A 先由 [`T040`](tasks/T040_source_catalog_owner_registry.md) 建立 catalog/top-overlay 双语义视图
  共用的 module owner registry，不收集可重命名 symbol；
- 后续 R2 任务只能在 T040 owner registry 上逐步增加 source symbol、occurrence/provenance 和 ABI
  overlay，不得重新建立第二套 module identity；
- 覆盖全部 module 的非 ABI 对象和 optional-top ABI overlay；
- 纳入 parameter/genvar、generate/dimension、named override、module/port/interface compact fixtures；
- 删除 classification 二次收集和 fixture-specific ownership 修补；
- 只产生 inventory/mapping candidate，不改写 RTL；
- Formal verification：`N/A`。

### 阶段 R3：统一 rewrite、mapping vNext、audit 与 metrics

- 单一目标：让 single-file 和显式 filelist 共用一条改写流水线；
- 无 top：全部 module 非 ABI；有 top：全部 module 非 ABI，加上闭包内授权的 child ABI；
- 冻结 mapping vNext、effective-line 和测试命名器边界；
- strict gate、decrypt、compact Formal 正负例必须通过；
- 不在本阶段接入 project-root discovery 或 RISC 专项 Formal。

### 阶段 R4：project-root adapter 接入统一引擎

- 单一目标：project-root discovery 生成 SourceSet 后调用 R3 同一流水线；
- 对等 fixture 上，project-root 与等价显式 filelist 的 normalized SymbolGraph/mapping 必须一致；
- project-root 不得新增 category、inventory、mapping 或 gate-audit 分支；
- compact project Formal 正负例必须通过。

### 阶段 R5：删除 legacy 路径与重建发布验收

- 单一目标：删除旧 encrypt/inventory/mapping 分派和仅服务旧 oracle 的测试；
- 更新 README、renaming table、formal 文档、future work 和演示脚本；
- 将 formal-align 拆成无固定数量的通用引擎与场景级 acceptance oracle；
- 运行专门 RISC-V-Vector 正负 Formal，重新冻结新架构的 normalized range digest、replacement
  数量和 manifests；
- 旧 T029/T035/T037 数量只保留在历史任务单，不再控制产品代码。

## 7. 每阶段共同停止条件

出现以下任一情况必须记录并停止，不得增加兼容分支：

- filelist 顺序或 compilation-unit 语义无法保持；
- catalog view 与 top overlay 无法映射到同一 source symbol owner；
- 一个 token 存在多个 owner，或支持对象存在未归属 reference；
- gate 只能通过删除真实 reference、放宽 strict compile 或忽略 diagnostic 才能生成；
- mapping 数量与可编译 gate 冲突；
- Formal 只能通过 identity comparison、复制 gold 或硬编码通用引擎数量才能完成。

## 8. 当前决策记录

2026-07-22 用户确认：重新定义三种模式，单文件作为 filelist 子集，project-root 作为自动发现的
filelist 子集；filelist 对全部文件执行非 ABI 改写，提供 top 后允许 selected-top 闭包内 child
module ABI 改写；同意丢弃过多兼容方案和旧测试方案，使用一套简洁架构。

主 Agent 确认该方向合理，并补充冻结：selected top 外部 boundary 默认保留；ABI 改写要求
SourceSet closed-world；显式 filelist 顺序不得排序；后续采用 SourceSet、SymbolGraph、
RewritePolicy 和单一 mapping/改写流水线。
