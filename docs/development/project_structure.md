# 项目结构

普通用户从仓库根目录运行 `python rtl_encrypt.py`，真实工程优先使用显式 filelist；
`python rtl_decrypt.py` 使用 gate 中的 schema 2 mapping 恢复源码。

## 产品流水线

```text
SourceSet -> SourceCatalog / PySlang compile+elaboration
          -> RenameIndex -> Mapping schema 2
          -> Rewrite -> strict compile -> restore / Formal
```

PySlang 是唯一语义权威。项目不再维护独立 SymbolGraph、RewritePolicy collector、文本正则语义解析或
名称查找 fallback。所有改写范围必须能回到 PySlang semantic target 和唯一物理 identifier token。

## 模块职责

| 路径 | 职责 |
| --- | --- |
| `rtl_obfuscator/source_set.py` | 归一化三种输入；filelist 模式轻量保留编译顺序、entry 来源记录、include-only 物理依赖和 root-relative rewrite allowlist |
| `rtl_obfuscator/project_discovery.py` | 运行 PySlang 编译/elaboration；parse 后在 SourceCatalog 前核对真实 source/include buffer；按诊断码和物理字节精确分类已验证供应商诊断 |
| `rtl_obfuscator/performance_probe.py` | 保存永久粗粒度阶段 ID 与无状态 observer 转发，不参与流水线计算 |
| `rtl_obfuscator/file_scope_vnext.py` | 从 SourceSet 构造有序统计范围与完整物理交付集合，不扫描目录 |
| `rtl_obfuscator/source_catalog.py` | 保存 compilation、top overlay、模块物理 declaration，并给出诊断文件与 include-only 只读清单 |
| `rtl_obfuscator/rename_index.py` | 建立四核心组物理索引；对跨入供应商诊断文件、rewrite root 之外或 include-only 文件的整条记录应用只读 firewall |
| `rtl_obfuscator/mapping_vnext.py` | 消费 RenameIndex，生成 mapping schema 2 和 range/manifest 审计 |
| `rtl_obfuscator/rewrite_vnext.py` | 一次性应用物理 ranges，生成 gate、严格编译并从 gate 恢复 |
| `rtl_obfuscator/orchestration_vnext.py` | 串联 mapping、rewrite、restore、metrics 和 rate，并缓存已验证报告与后处理阶段事实 |
| `rtl_obfuscator/restore_vnext.py` | 只使用持久化 schema 2 证据恢复；验证公开三视图及 nested filelist 闭包；拒绝 schema 1 |
| `rtl_obfuscator/formal_vnext.py` | 提供 Formal 相关的 PySlang/source-range 视图 |
| `rtl_obfuscator/rewrite.py` | 共享 CLI 参数、三种输入模式检查、filelist-only `--rewrite-root`、公开三视图、持久化运行记录和公共错误输出 |

RenameIndex 的一次性有序 catalog 遍历可附带不可变的语义名称快照。该快照只绑定同一次
SourceCatalog 的 compilation、catalog root 和 source manager，且仅存活于该 RenameIndex 实例；
Mapping 在既有 source/owner/range 校验之后才复用它。通过 `dataclasses.replace` 或替换任一绑定
对象后，Mapping 回到原有名称遍历；空快照与无效（例如名称 getter 失败）快照保持可区分。

同次 workset 构建始终完整、有序地分类 catalog 与 top。二者为同一 tuple 时，只按位置复用
`declaredType.type` 两层成功读取后的 alias 事实；任一属性缺失或失败仍在 top 阶段重试，
`isInterface` 与 conversion type 仍在原 top 阶段读取。事实随本次构建结束释放，未增加节点类型
预筛选或另一份 top 分类规则。端口声明只在同次登记内按强引用与对象身份复用预扫描成功结果；
失败保持原顺序重试，owner、category、support、reason、internalSymbol 与 targets 仍逐节点计算。
这些复用不保存候选名单或准入结论，新增语义类型、候选和准入规则继续使用原有规则入口。

名字完整性检查始终保留完整 CST token 和无法验证的名称。它先采用本次记录已有的声明与引用证据，
仅对剩余 token 补充通用声明证明，再对仍未解释的 token 补充通用引用证明；最终判定仍检查完整分母。
候选名称和所有 eligible 记录的改写位置每次重新计算，不缓存准入结论，也不按现有类别或节点形状
筛选证据来源。扩展候选或准入规则时沿用同一证明入口；若改变证据含义或在检查之后重新开放候选，
需要重新执行适用证明并验证扩展回归。

## 四核心组边界

- `signals` 只收集 module-owned `VariableSymbol/NetSymbol`，排除端口和 aggregate/interface 成员；
- `ports` 只收集 source-backed module `PortSymbol`，selected top 对外 ABI 保留；
- `interface` 收集 interface 类型、实例 root、成员和 modport；数组 element 只作为 semantic alias；
- `struct` 只收集物理 `typedef struct/union` 及其字段；parameter type 和隐式 conversion 不建伪记录。

`ModportPortSymbol` 通过其 PySlang `internalSymbol` 作为 interface member occurrence；struct member 通过
直接 `FieldSymbol` target 的 source location 绑定。source-less node 或无法唯一绑定的对象保留并报告原因。

## 报告与输入

公共 CLI 的 `--category` 必须显式提供，只允许四组或 `all`。filelist 模式可接受可重复的
`--rewrite-root`（top 可选），禁止 `--source-root`；project-root 才接受 `--source-root --top`；单文件只接受
`--input`。rewrite root 在 SourceSet 内以可重定位的 root-relative 路径保存，使 actual gate 在 staging root 上重新编译时
仍应用同一边界；它不进入当前 SourceSet schema 1 或 mapping schema 2。

mapping、orchestration、mapping-execution、rate 和 restore 持久化报告使用 schema 2；嵌套 SourceSet
仍使用 schema 1。`.sv/.v` 是 source unit；由 bounded literal include closure 唯一发现、且未显式列为 standalone
source 的普通文件（包括任意后缀）是只读 include-only 物理依赖，不扩展 standalone suffix，不进入 compile order。
同一规范化路径递归去重，并保留到 manifest、gate 和 restore。`.svh/.vh/.h` 作为上下文物理文件；显式 filelist 裸路径
还可列出 `.vic` compilation-unit 参数上下文。上下文文件不进入 rename target；source/header 只有在
同一规范化 `.vic` 路径已作为裸 filelist 条目显式列出时才能 include 它。`.vic` 不由 single-file、
project-root 或 include-only 输入自动发现，也不接受 `-v`。

authoritative filelist 的 SourceSet 阶段只做结构归一化：保留每个有效 source、library source、context、
include-dir 和 define 的 live-only `FilelistEntry`（含 canonical value、物理 filelist 和行号），并按展开顺序
生成 `compile_order`；`-f` 本身不生成 entry。该阶段不建立 PySlang compilation，`top_closure_files` 固定为空；
top、parse 和 semantic 诊断由 SourceCatalog 在后续阶段报告。Filelist entry 不进入 SourceSet report、mapping
或 restore 持久化 schema。

`compile_pyslang_source_set()` 保留全部原始 syntax error key 做 parse/semantic 去重；parse 完成后会核对真实
`DesignFile`、`LibraryFile`、`IncludeFile` buffer 是否已登记，未登记时在 SourceCatalog 全树遍历前带路径拒绝。
宏计算出的 include 不自动加入 SourceSet。只有物理位置可验证的
`IfNoneEdgeSensitive` 和六个固定 legacy directive 进入独立 vendor compatibility 分类。`MissingTimeScale`
仍是另一种 nonblocking 原因；其他 parse/semantic error 不放宽。诊断文件参与 definition、hierarchy、port/type
绑定，但任一 declaration/occurrence 跨入它时整条记录不改写。

公开 CLI 的 compile 与 RenameIndex 外层进度内部提供固定粗粒度子阶段（如
`compile.parse`、`compile.owner_registry`、`rename_index.name_completeness`）；restore 后还会记录
`audit.execution`、`audit.metrics`、`audit.report`、`publish` 和 `cleanup`。这些阶段共用同一个
observer 和单调时钟；成功运行把同源计时、启动命令、工作目录和最终总结写入
`encryption_summary.txt`，其中总用时不包含最后总结文件写入本身。

公开 `--filelist` 模式发布逐字节原文 `original_design.f`、gate 绝对路径 `design.f` 和可搬迁的
`export_design.f`。export 对含环境变量的路径 token 保留原文；无变量的绝对路径写作 `$OUT` 加原绝对路径，
并在 gate 内复制对应的普通物理文件或已登记的目录内物理依赖；无变量的相对路径写作 `$OUT` 加源码根相对路径。reachable
nested `-f` 仍按各自原始顺序镜像到 `.rtl_obfuscation/filelists/design` 与
`.rtl_obfuscation/filelists/export`；环境变量形式的 `-f` 还会在源码根相对位置发布 export 子文件副本。
这些路径规则覆盖 `-f`、`-v`、普通文件和 `+incdir+`。行序、注释、空白、换行符及 `+define+` 保持原样，
CLI-only context 不注入。原始 nested filelist 字节另存于 `.rtl_obfuscation/filelists/original`，
顶层 `mapping.json.delivery_filelists` 按确定顺序记录原文相对路径和 SHA256，供 restore 严格检查 token、摘要和物理文件集合。
`--input` 与 project-root 模式使用 canonical include/define/compile_order 三视图；include-only
物理依赖仍进入 manifest/gate/restore，但不成为 compile entry。

统计使用 `file_scope_vnext.py` 的有序物理范围：有 rewrite root 时，metrics 只统计 SourceSet
已登记且落在 root 内的文件；`summary.files` 是统计范围文件数，`summary.physical_files` 是完整
manifest/交付文件数。gate、strict compile、restore 和 per-file mapping 仍使用完整物理集合。

## 验证边界

gate 发布前必须通过物理 range/manifest 审计、PySlang 严格编译和逐字节 restore。实际 gate Formal 需比较
公开生成的改名 gate 与 gold；固定功能负例必须以非零退出和 `unproven`/`equiv_status -assert` 证明流程能
拒绝错误 gate。filelist 的输出边界保护实际物理输入；当多物理根使 `source_root` 为 `/` 时，不把这个
相对路径边界误当成整个源码目录。RISC-V-Vector 不属于常规验收。
