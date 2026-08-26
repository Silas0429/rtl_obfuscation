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
| `rtl_obfuscator/source_set.py` | 归一化单文件、显式 filelist 和 project-root 输入；保留编译顺序与物理清单 |
| `rtl_obfuscator/project_discovery.py` | 运行 PySlang 编译、elaboration 和 project-root 的输入发现 |
| `rtl_obfuscator/source_catalog.py` | 保存 PySlang compilation、top overlay、模块物理 declaration 和 SourceSet |
| `rtl_obfuscator/rename_index.py` | 从 PySlang semantic nodes 建立四核心组 source-backed declaration/occurrence 索引 |
| `rtl_obfuscator/mapping_vnext.py` | 消费 RenameIndex，生成 mapping schema 2 和 range/manifest 审计 |
| `rtl_obfuscator/rewrite_vnext.py` | 一次性应用物理 ranges，生成 gate、严格编译并从 gate 恢复 |
| `rtl_obfuscator/orchestration_vnext.py` | 串联 mapping、rewrite、restore、metrics 和 rate |
| `rtl_obfuscator/restore_vnext.py` | 只使用持久化 schema 2 证据恢复；拒绝 schema 1 |
| `rtl_obfuscator/formal_vnext.py` | 提供 Formal 相关的 PySlang/source-range 视图 |
| `rtl_obfuscator/rewrite.py` | 共享 CLI 参数、三种输入模式检查和公共错误输出 |

## 四核心组边界

- `signals` 只收集 module-owned `VariableSymbol/NetSymbol`，排除端口和 aggregate/interface 成员；
- `ports` 只收集 source-backed module `PortSymbol`，selected top 对外 ABI 保留；
- `interface` 收集 interface 类型、实例 root、成员和 modport；数组 element 只作为 semantic alias；
- `struct` 只收集物理 `typedef struct/union` 及其字段；parameter type 和隐式 conversion 不建伪记录。

`ModportPortSymbol` 通过其 PySlang `internalSymbol` 作为 interface member occurrence；struct member 通过
直接 `FieldSymbol` target 的 source location 绑定。source-less node 或无法唯一绑定的对象保留并报告原因。

## 报告与输入

公共 CLI 的 `--category` 必须显式提供，只允许四组或 `all`。filelist 模式只接受 `--filelist`（top 可选），
禁止 `--source-root`；project-root 才接受 `--source-root --top`；单文件只接受 `--input`。

mapping、orchestration、mapping-execution、rate 和 restore 持久化报告使用 schema 2；嵌套 SourceSet
仍使用 schema 1。`.sv/.v` 是 source unit，`.svh/.vh/.h` 只作为上下文物理文件，不产生宏改名。

## 验证边界

gate 发布前必须通过物理 range/manifest 审计、PySlang 严格编译和逐字节 restore。实际 gate Formal 需比较
公开生成的改名 gate 与 gold；固定功能负例必须以非零退出和 `unproven`/`equiv_status -assert` 证明流程能
拒绝错误 gate。RISC-V-Vector 不属于常规验收。
