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
| `rtl_obfuscator/project_discovery.py` | 运行 PySlang 编译/elaboration；按诊断码和物理字节精确分类已验证供应商诊断 |
| `rtl_obfuscator/source_catalog.py` | 保存 compilation、top overlay、模块物理 declaration，并给出诊断文件与 include-only 只读清单 |
| `rtl_obfuscator/rename_index.py` | 建立四核心组物理索引；对跨入供应商诊断文件、rewrite root 之外或 include-only 文件的整条记录应用只读 firewall |
| `rtl_obfuscator/mapping_vnext.py` | 消费 RenameIndex，生成 mapping schema 2 和 range/manifest 审计 |
| `rtl_obfuscator/rewrite_vnext.py` | 一次性应用物理 ranges，生成 gate、严格编译并从 gate 恢复 |
| `rtl_obfuscator/orchestration_vnext.py` | 串联 mapping、rewrite、restore、metrics 和 rate |
| `rtl_obfuscator/restore_vnext.py` | 只使用持久化 schema 2 证据恢复；拒绝 schema 1 |
| `rtl_obfuscator/formal_vnext.py` | 提供 Formal 相关的 PySlang/source-range 视图 |
| `rtl_obfuscator/rewrite.py` | 共享 CLI 参数、三种输入模式检查、filelist-only `--rewrite-root` 和公共错误输出 |

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
仍使用 schema 1。`.sv/.v` 是 source unit；由 include closure 唯一发现、且未显式列为 standalone source 的 `.sv/.v`
是只读物理依赖，不进入 compile order。`.svh/.vh/.h` 作为上下文物理文件；显式 filelist 裸路径
还可列出 `.vic` compilation-unit 参数上下文。上下文文件不进入 rename target；source/header 只有在
同一规范化 `.vic` 路径已作为裸 filelist 条目显式列出时才能 include 它。`.vic` 不由 single-file、
project-root 或 include-only 输入自动发现，也不接受 `-v`。

authoritative filelist 的 SourceSet 阶段只做结构归一化：保留每个有效 source、library source、context、
include-dir 和 define 的 live-only `FilelistEntry`（含 canonical value、物理 filelist 和行号），并按展开顺序
生成 `compile_order`；`-f` 本身不生成 entry。该阶段不建立 PySlang compilation，`top_closure_files` 固定为空；
top、parse 和 semantic 诊断由 SourceCatalog 在后续阶段报告。Filelist entry 不进入 SourceSet report、mapping
或 restore 持久化 schema。

`compile_pyslang_source_set()` 保留全部原始 syntax error key 做 parse/semantic 去重；只有物理位置可验证的
`IfNoneEdgeSensitive` 和六个固定 legacy directive 进入独立 vendor compatibility 分类。`MissingTimeScale`
仍是另一种 nonblocking 原因；其他 parse/semantic error 不放宽。诊断文件参与 definition、hierarchy、port/type
绑定，但任一 declaration/occurrence 跨入它时整条记录不改写。

## 验证边界

gate 发布前必须通过物理 range/manifest 审计、PySlang 严格编译和逐字节 restore。实际 gate Formal 需比较
公开生成的改名 gate 与 gold；固定功能负例必须以非零退出和 `unproven`/`equiv_status -assert` 证明流程能
拒绝错误 gate。filelist 的输出边界保护实际物理输入；当多物理根使 `source_root` 为 `/` 时，不把这个
相对路径边界误当成整个源码目录。RISC-V-Vector 不属于常规验收。
