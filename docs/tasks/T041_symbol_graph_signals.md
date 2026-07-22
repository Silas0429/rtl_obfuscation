# T041：SymbolGraph 基础合同与内部 signal source identity

- 状态：`READY`
- 设计负责人：主 Agent
- 实现负责人：子 Agent
- 所属重构阶段：R2-B
- 前置任务：T040 `ACCEPTED`，交付提交 `019f14d`
- 设计依据：`docs/three_mode_refactor_plan.md` 第 2、3、5、6、7 节
- 执行规范：`docs/refactor_subagent_protocol.md`
- 验收类型：SymbolGraph/range
- Formal verification：`N/A`，本任务只产生 source symbol/range report，不产生 rewritten RTL

## 1. 项目位置

统一核心流水线保持为：

```text
single-file -----------+
filelist --------------+--> SourceSet --> SourceCatalog --> SymbolGraph
project-root adapter --+                                         --> RewritePolicy
                                                                  --> mapping/rewrite/audit
```

T039 已冻结 SourceSet，T040 已建立 catalog/top-overlay 共用的 module owner registry。T041 只在
T040 的 catalog semantic view 上建立第一版 SymbolGraph，并迁移一个低风险、非 ABI category：
module 内部 `signals`。

本任务的重点不是扩大 category 数量，而是先证明：一个 source declaration 即使因 repeated
instance 被 elaboration 多次，也只能形成一个 source symbol；它的物理引用必须由 semantic binding
归属到同一 symbol，并带有明确 provenance。

## 2. 单一目标

新增 `rtl_obfuscator/symbol_graph.py`，输入一个已经成功建立的 `SourceCatalog`，输出确定、可序列化、
owner 完整且 range 无冲突的 signals-only SymbolGraph。

实现必须：

1. 复用 `SourceCatalog.catalog_compilation/catalog_root/catalog_source_manager`；
2. 不重新编译 SourceSet，不调用 top overlay，不调用 legacy inventory/rewrite；
3. 将 semantic elaboration 中同一物理 signal declaration 的多个 symbol copy 归一化为一个
   `SourceSymbol`；
4. 只通过 PySlang semantic binding 收集声明和直接 expression references；
5. 对 declaration、occurrence、module owner 和 source bytes 做一次全局审计；
6. 输出稳定 report，为后续 parameter/genvar、其他 category 和 RewritePolicy 提供唯一图模型。

## 3. 固定公开 API

`rtl_obfuscator/symbol_graph.py` 提供：

```python
@dataclass(frozen=True)
class SymbolOccurrence:
    source_range: SourceRange
    provenance: str

@dataclass(frozen=True)
class SourceSymbol:
    symbol_id: str
    category: str
    name: str
    declaration: SourceRange
    owner_module: str
    semantic_owner: str
    occurrences: tuple[SymbolOccurrence, ...]
    impact: str
    abi: str
    support: str
    reason: str | None

@dataclass(frozen=True)
class SymbolGraph:
    schema_version: int
    source_catalog: SourceCatalog
    symbols: tuple[SourceSymbol, ...]

    def to_report(self) -> dict[str, object]: ...

class SymbolGraphError(ValueError):
    code: str
    message: str
    file: str | None
    start: int | None

def build_symbol_graph(source_catalog: SourceCatalog) -> SymbolGraph: ...
```

`SymbolGraph.source_catalog` 必须标记为 `repr=False, compare=False`。`to_report()` 输出其
`source_catalog.to_report()`，不得序列化 PySlang 对象。T041 不要求从
`rtl_obfuscator/__init__.py` 重导出这些 API。

T041 不增加 category 参数。当前 graph 固定生成完整的 `signals` 子图；后续任务在同一个 builder
中增加 category，不得为每类建立并行 graph 实现。

## 4. T041 signal 范围

### 4.1 包含

一个对象只有同时满足以下条件才进入本任务的 graph：

- semantic kind 是 `Variable` 或 `Net`；
- 名称是非空、非 `$` 开头的 source identifier；
- `declaringDefinition` 是 SourceCatalog 中的 module definition；
- declaration 能映射到 SourceSet 内一个直接物理 UTF-8 byte range；
- 不是 module/interface port 的 `internalSymbol`；
- 不是 function 的 `returnValVar`；
- 所有被本任务接受的引用都能通过 semantic expression identity 绑定到该对象。

未使用的内部 signal 也建立 symbol，允许 `occurrences=()`。同一 source declaration 被不同
instance 或同一 module 的 repeated instance elaboration 多次时，仍只建立一个 symbol。

### 4.2 T041 固定分类

本任务成功输出的每个 SourceSymbol 固定为：

```text
category: signals
impact: local
abi: internal
support: eligible
reason: null
semantic_owner: 与 owner_module 相同的 T040 ModuleOwner.owner_id
```

T041 不把 port、function return、parameter、genvar、enum、subroutine、instance、generate label、
typedef、aggregate field、module/interface/port/modport 伪装成 `signals`。

### 4.3 fail-closed 边界

- 跨 module hierarchical reference 不在 T041 支持范围；若它绑定到已收集 signal，必须返回
  `SYMBOL_GRAPH_UNSUPPORTED_REFERENCE`，不能仍把该 symbol 标记为 local/eligible；
- macro-generated declaration/reference、没有直接物理 identifier token 的 semantic reference，或
  只存在于 uninstantiated syntax 且无法由 semantic identity 证明 owner 的 reference，必须稳定失败；
- 禁止用全局文本搜索、同名匹配、正则或旧 lexical fallback 补引用；
- 不得静默忽略一个已确认绑定到目标 signal、但无法生成合法 physical range 的 reference。

后续 R2 任务可以把受控 syntax provenance 加入同一 graph；T041 不为未来形状提前增加 fallback。

## 5. source identity、owner 与 range 不变量

### 5.1 declaration 与 symbol_id

`declaration` 只覆盖 signal identifier token，使用 T040 的 source-root-relative POSIX
`SourceRange`：

```text
0 <= start < end <= len(source_bytes)
source_bytes[start:end] == name.encode("utf-8")
```

固定 symbol id：

```text
symbol:signals:<file>:<start>:<end>
```

禁止使用 instance path、elaborated index、对象地址、随机值或 signal name 单独构造 symbol id。

### 5.2 module owner

- 使用 semantic signal 的 `declaringDefinition` declaration location 映射 T040 ModuleOwner；
- 映射键必须是 module declaration 的 `(file, start, end)`，不能只按 module name；
- `owner_module` 和本任务的 `semantic_owner` 都记录该 ModuleOwner.owner_id；
- 任一 source signal 无法映射 owner 时整个 build 失败，不返回部分 graph。

### 5.3 occurrences 与 provenance

- `occurrences` 只记录 reference，不重复 declaration；
- T041 唯一允许的 provenance 字符串为 `semantic_expression`；
- reference 必须由 `NamedValueExpression.symbol` 的 semantic identity 绑定；
- 每个 occurrence 的 `source_range` 必须精确覆盖 signal 名称 bytes；
- repeated elaboration 产生的相同 physical range 必须归一化为一个 occurrence；
- occurrences 按 `(file, start, end, provenance)` 排序。

### 5.4 全局排序与冲突审计

- `symbols` 按 `(declaration.file, declaration.start, declaration.end, category, name)` 排序；
- declaration range 和 symbol id 各自全局唯一；
- 全部 declaration + occurrence physical ranges 全局唯一且不重叠；
- 同名 signal 位于不同 module 时必须形成不同 symbol 和 owner；
- 一个 physical range 不能属于两个 symbol；
- range 所在文件必须属于 SourceSet 的 source/include 物理文件集合。

## 6. catalog/top 规则

- graph 只读取 T040 catalog view；optional top 不改变 signals 的收集范围；
- filelist 提供 top 时，closure 外 module 的内部 signals 仍必须进入 graph；
- top module 的内部 signals 仍是 `internal`，但 top ports 不进入 graph；
- project-root 的 SourceSet 本身只包含自动发现闭包，因此只对该 canonical SourceSet 建图；
- T041 不读取 top overlay 来增删 signals，不实现 ABI category 或 top-boundary policy。

## 7. 固定 report schema

`SymbolGraph.to_report()` 返回：

```text
schema_version: 1
source_catalog: <source_catalog.to_report() 的完整结果>
categories: [signals]
symbols:
  - symbol_id
    category
    name
    declaration: {file, start, end}
    owner_module
    semantic_owner
    occurrences:
      - source_range: {file, start, end}
        provenance
    impact
    abi
    support
    reason
range_audit:
  symbols
  declarations
  occurrences
  total_ranges
```

对于第 9 节 `design.f` fixture，report 固定为 6 symbols、6 declarations、12 occurrences、18
total ranges。该 compact 数量只验证本任务输入，不得进入产品分支或成为 RISC oracle。

连续两次 `to_report()` 经 canonical JSON 序列化后必须 byte-identical。等价入口比较时只允许移除
`source_catalog.source_set.origin`，不能移除 symbol id、owner、ranges、provenance、classification
或 range audit。

## 8. 稳定失败合同

| code | 条件 |
| --- | --- |
| `SYMBOL_GRAPH_OWNER_MISMATCH` | signal declaringDefinition 无法映射到一个 T040 ModuleOwner |
| `SYMBOL_GRAPH_RANGE_INVALID` | declaration/reference 越界、文件不属于 SourceSet 或 bytes 不匹配 |
| `SYMBOL_GRAPH_RANGE_CONFLICT` | 不同 symbol 共享、重复或重叠 physical range |
| `SYMBOL_GRAPH_UNSUPPORTED_SOURCE` | declaration/reference 来自 macro 或无直接物理 identifier token |
| `SYMBOL_GRAPH_UNSUPPORTED_REFERENCE` | hierarchical、syntax-only 或其他 T041 未支持但已绑定到目标 signal 的引用 |

异常字符串固定以 `"<code>: "` 开头，并保存首个稳定 `file/start`（若可用）。失败时不输出部分
report，不调用 legacy fallback。

## 9. 固定 compact fixture

新增：

```text
tests/fixtures/refactor_symbol_graph_signals/
  design.f
  closure.f
  single.f
  rtl/child.sv
  rtl/top.sv
  rtl/unreachable.sv
  rtl/standalone.sv

tests/fixtures/refactor_symbol_graph_signals_invalid/
  hierarchical.f
  rtl/hierarchical.sv
```

fixture 语义：

- `child` 声明内部 variable `state` 和 net `state_net`；
- `top` 声明内部 variable `state` 与 `child_o`，并正常实例化 `child` 两次；
- child/top 的同名 `state` 必须形成不同 symbol；
- repeated child instance 不得复制 child 的两个 source symbols 或 physical occurrences；
- `unreachable` 声明内部 `hidden`；即使 filelist 选择 top，它仍属于全 filelist 非 ABI graph；
- `standalone` 声明一个内部 net `state`，用于 single-file/filelist 对等检查；
- 所有 module ports 必须排除；
- `design.f` 顺序为 child、top、unreachable、standalone，共 6 signals / 12 references；
- 固定 reference 分布为 child `state=2`、child `state_net=2`、top `state=2`、top
  `child_o=3`、unreachable `hidden=1`、standalone `state=2`；
- `closure.f` 只列 child、top；`single.f` 只列 standalone；
- invalid fixture 使用 `u_leaf.secret` 从另一个 module 层次引用内部 signal，必须返回
  `SYMBOL_GRAPH_UNSUPPORTED_REFERENCE`。

fixture 全部使用 `.sv` 和 SystemVerilog syntax；不增加 `.v` fixture。

## 10. 目标测试

新增 `tests/test_symbol_graph_signals.py`，至少覆盖：

1. `design.f` 无 top 时精确产生 6 个内部 signal symbols，ports 不进入 graph；
2. `design.f + top` 的 symbol payload 与无 top 相同，并包含 closure 外 `hidden/state`；
3. repeated child instances 只产生一个 child `state` 和一个 `state_net` source symbol；
4. child/top/standalone 的同名 `state` 按 declaration 和 ModuleOwner 分离；
5. variable/net declaration、12 个 semantic references、provenance、source bytes、排序、唯一和
   不重叠全部满足第 5 节；
6. project-root SourceCatalog 与 `closure.f + top` 的 normalized graph report 除 origin 外相同；
7. single-file SourceCatalog 与 `single.f` 的 normalized graph report 除 origin 外相同；
8. report schema、range audit 和 canonical JSON 连续两次 byte-identical；
9. graph build 期间 monkeypatch T040 compile 入口和 legacy inventory/rewrite 入口为立即失败，仍能通过，
   证明没有重编译或旧 collector 调用；
10. hierarchical internal-signal reference 稳定返回 `SYMBOL_GRAPH_UNSUPPORTED_REFERENCE`，不返回
    incomplete eligible graph。

测试必须通过公开 `build_source_catalog()` + `build_symbol_graph()` 组合验证，不能直接调用产品私有
helper 制造 report。

## 11. 允许修改的文件

- `rtl_obfuscator/symbol_graph.py`；
- `tests/fixtures/refactor_symbol_graph_signals/**`；
- `tests/fixtures/refactor_symbol_graph_signals_invalid/**`；
- `tests/test_symbol_graph_signals.py`；
- `docs/tasks/T041_symbol_graph_signals.md`，仅允许状态和子 Agent 执行记录。

禁止修改：

- `rtl_obfuscator/source_set.py`、`source_catalog.py`、`project.py`；
- `rtl_obfuscator/inventory.py`、`rewrite.py`、`category_profile.py`；
- T039/T040 fixture、tests 和历史任务单；
- parameter/genvar、ABI、mapping、decrypt、metrics、formal 或 RISC 文件；
- README、renaming table、重构计划和子 Agent 规范。

## 12. 明确不包含

- 不收集 `signals` 之外任何 category；
- 不处理 parameter/genvar、generate/dimension 或 named override；
- 不使用 selected-top overlay 做 ABI binding；
- 不实现 RewritePolicy、名称生成、mapping vNext、source edit 或 gate audit；
- 不产生 rewritten RTL，不运行 decrypt、HDL compile、Yosys 或 Formal；
- 不删除、包装或适配 legacy inventory/tests；
- 不增加 lexical fallback、缓存、并行 compilation、新依赖或 CLI；
- 不修改 `__init__.py` 或公开用户命令。

## 13. 子 Agent 强制流程

1. 完整阅读 `AGENTS.md`、本任务、`docs/three_mode_refactor_plan.md` 第 2/3/5/6/7 节、
   `docs/refactor_subagent_protocol.md`；
2. 确认 starting HEAD 包含 T040 提交 `019f14d`，且工作区只有本任务合同允许的预存修改；
3. 将任务从 `READY` 改为 `IN_PROGRESS`，填写第 15 节开始记录；
4. baseline 运行目标 unittest；预期因测试模块尚不存在而非零，记录首个诊断；
5. 先新增 compact fixture 和黑盒测试，再实现最小 SymbolGraph；
6. 每个可观察行为完成后只运行目标测试；
7. 若需要修改 T040 API、调用 legacy inventory、增加 lexical fallback，或无法证明 reference
   completeness/owner/range，记录偏差并停止；
8. 完成后运行第 14 节四条命令；
9. 仅设置 `READY_FOR_REVIEW`、填写真实命令和输出后停止；
10. 不执行 `git add`、commit、push，不创建下一任务，不写主 Agent 验收记录。

## 14. 唯一验收命令

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_symbol_graph_signals -v
conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/symbol_graph.py tests/test_symbol_graph_signals.py
git diff --check HEAD
rg -x -- '- 状态：`READY_FOR_REVIEW`' docs/tasks/T041_symbol_graph_signals.md
```

不运行全量 unittest、legacy signal tests、HDL compile、gate、decrypt、Yosys 或 RISC-V-Vector。
目标 unittest 必须自行执行 report/range audit；Formal 为 N/A，因为本任务不产生 rewritten RTL。

## 15. 子 Agent 执行记录

```text
status: NOT_STARTED
starting_head:
changed_files:
baseline_command:
baseline_result:
commands:
results:
schema_or_behavior:
deviations_or_blockers:
boundaries:
formal_verification: N/A - no rewritten RTL is produced
review_request:
```

## 16. READY_FOR_REVIEW 条件

- 第 10 节全部行为由目标测试覆盖；
- 第 14 节四条命令全部退出 `0`；
- 实际 diff 只包含第 11 节允许文件；
- graph build 不重新编译、不读取 top overlay、不调用 legacy collector；
- repeated elaboration 已归一化为 source identity；
- 每个 symbol owner、declaration、occurrence 和 provenance 完整；
- 全部 source bytes 精确匹配，range 全局唯一且不重叠；
- hierarchical negative fail-closed；
- 任务状态严格为 `READY_FOR_REVIEW`；
- Formal 记录为 `N/A: no rewritten RTL is produced`。

## 17. 主 Agent 验收边界

主 Agent 将：

1. 审查 `HEAD -> working tree` 完整 diff 和允许文件；
2. 在状态仍为 `READY_FOR_REVIEW` 时独立运行第 14 节四条命令；
3. 直接检查 6/12/18 range audit、同名 owner 分离和 repeated-instance source normalization；
4. 确认 project-root/filelist、single-file/filelist normalized graph 对等；
5. 确认没有第二次 compile、legacy inventory/rewrite 或 lexical fallback；
6. 全部通过后才增加主 Agent 验收记录并设置 `ACCEPTED`。

主 Agent 验收失败时，任务回到 `IN_PROGRESS` 或 `BLOCKED`；子 Agent 产生的任何 `ACCEPTED` 文本均
构成流程失败。
