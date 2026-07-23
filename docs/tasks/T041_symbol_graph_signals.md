# T041：SymbolGraph 基础合同与内部 signal source identity

- 状态：`ACCEPTED`
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

T041 采用临时的严格输入边界：只有第 4.3 节 preflight 对整个 catalog view 全部通过，才允许
返回 SymbolGraph。本任务成功输出的每个 SourceSymbol 固定为：

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

T041 不输出逐 symbol preserved/unsupported 记录。任一不支持形状会使整个 build 稳定失败，因此
成功 graph 中的 `eligible/local/internal` 不会与未审计引用并存。把 whole-graph failure 细化为逐
symbol preserved/unsupported 属于后续 R2 任务，不得在 T041 中扩大 schema。

### 4.3 严格 preflight 与 fail-closed 边界

在建立任何 `eligible` SourceSymbol 前，builder 必须对同一个 catalog semantic tree 执行以下固定
preflight；失败时不返回部分 graph：

1. candidate signal declaration 或已绑定 reference 的 location 若为
   `catalog_source_manager.isMacroLoc(location)`，返回 `SYMBOL_GRAPH_UNSUPPORTED_SOURCE`；
2. candidate signal 的 declaration/reference 若没有直接物理 identifier token，返回
   `SYMBOL_GRAPH_UNSUPPORTED_SOURCE`；
3. 任一 `HierarchicalValueExpression` 绑定到 candidate internal signal，返回
   `SYMBOL_GRAPH_UNSUPPORTED_REFERENCE`；
4. 任一 `UninstantiatedDefSymbol` 均返回 `SYMBOL_GRAPH_UNSUPPORTED_REFERENCE`。T041 禁止 lexical
   fallback，不能证明该 syntax 中 signal actual 的 owner，因此采用保守 whole-graph failure；
5. `NamedValueExpression`/`ElementSelectExpression` 存在 source syntax 但没有可用 semantic target，
   返回 `SYMBOL_GRAPH_UNSUPPORTED_REFERENCE`；
6. 非 macro 的物理 location 若文件、边界或 source bytes 校验失败，返回
   `SYMBOL_GRAPH_RANGE_INVALID`；
7. signal 的 declaring module 无法映射到一个 T040 ModuleOwner，返回
   `SYMBOL_GRAPH_OWNER_MISMATCH`。

preflight 的顺序必须保证 macro/no-token 与普通 range corruption 使用不同错误码。禁止用全局文本
搜索、同名匹配、正则或旧 lexical fallback 补引用。后续 R2 任务可以把受控 syntax provenance
和逐 symbol preserved 状态加入同一 graph；T041 不提前实现。

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

## 8. 稳定失败合同与完整负例矩阵

| code | 条件 |
| --- | --- |
| `SYMBOL_GRAPH_OWNER_MISMATCH` | signal declaringDefinition 无法映射到一个 T040 ModuleOwner |
| `SYMBOL_GRAPH_RANGE_INVALID` | declaration/reference 越界、文件不属于 SourceSet 或 bytes 不匹配 |
| `SYMBOL_GRAPH_UNSUPPORTED_SOURCE` | declaration/reference 来自 macro 或无直接物理 identifier token |
| `SYMBOL_GRAPH_UNSUPPORTED_REFERENCE` | hierarchical、uninstantiated、syntax-only 或其他无 semantic target 的引用 |

异常字符串固定以 `"<code>: "` 开头，并保存首个稳定 `file/start`（若可用）。失败时不输出部分
report，不调用 legacy fallback。

每个上述稳定 code 必须由第 10 节公开 API 黑盒测试直接触发。`SYMBOL_GRAPH_RANGE_CONFLICT` 仍可
作为实现内部 invariant 防御，但 T041 不把无法由合法公开输入构造的冲突冻结为用户合同，也不允许
通过直接调用私有 `_audit_ranges()` 伪造验收。

冻结映射如下：

| 负例输入 | 前置条件 | 预期 code |
| --- | --- | --- |
| macro-generated signal declaration | SourceCatalog 建立成功 | `SYMBOL_GRAPH_UNSUPPORTED_SOURCE` |
| macro-generated signal reference | SourceCatalog 建立成功，declaration 为普通物理 token | `SYMBOL_GRAPH_UNSUPPORTED_SOURCE` |
| hierarchical internal-signal reference | SourceCatalog 建立成功 | `SYMBOL_GRAPH_UNSUPPORTED_REFERENCE` |
| 合法 inactive generate 中的 `UninstantiatedDefSymbol` | parse/semantic errors 均为 0 | `SYMBOL_GRAPH_UNSUPPORTED_REFERENCE` |
| catalog 建立后物理 signal bytes 被测试替身改变 | module owner bytes 保持不变 | `SYMBOL_GRAPH_RANGE_INVALID` |
| 合法 catalog 的 `modules` registry 被替换为空 | semantic tree 保持不变 | `SYMBOL_GRAPH_OWNER_MISMATCH` |

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
  macro_declaration.f
  macro_reference.f
  uninstantiated.f
  rtl/hierarchical.sv
  rtl/macro_declaration.sv
  rtl/macro_reference.sv
  rtl/uninstantiated.sv
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
- `macro_declaration.sv` 通过本文件内 function-like macro 声明 `macro_state`，SourceCatalog 必须成功，
  graph 必须返回 `SYMBOL_GRAPH_UNSUPPORTED_SOURCE`；
- `macro_reference.sv` 直接声明普通物理 `state`，但通过 function-like macro 在 expression 中引用它，
  SourceCatalog 必须成功，graph 必须返回 `SYMBOL_GRAPH_UNSUPPORTED_SOURCE`；
- `uninstantiated.sv` 必须同时定义 child 与 parameterized top；top 的默认 parameter 选择一个
  generate branch，另一个合法 inactive branch 保留一个真实 `UninstantiatedDefSymbol`；
- `uninstantiated.f` 经公开 `build_source_catalog()` 必须得到 0 parse/semantic errors，再由
  `build_symbol_graph()` 返回 `SYMBOL_GRAPH_UNSUPPORTED_REFERENCE`；禁止从另一 compilation 抽取节点、
  拼接伪 catalog root 或直接调用私有 helper。

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
    incomplete eligible graph；
11. 真实、零 semantic-error 的 inactive generate fixture 确实包含 `UninstantiatedDefSymbol`，并经
    `build_symbol_graph()` 返回 `SYMBOL_GRAPH_UNSUPPORTED_REFERENCE`；
12. macro-generated signal declaration 返回 `SYMBOL_GRAPH_UNSUPPORTED_SOURCE`；
13. 普通 signal declaration 的 macro-generated reference 返回 `SYMBOL_GRAPH_UNSUPPORTED_SOURCE`；
14. 在 catalog 建立后仅替换 signal declaration bytes，返回 `SYMBOL_GRAPH_RANGE_INVALID`；
15. 使用 `dataclasses.replace(catalog, modules=())` 移除 owner registry，返回
    `SYMBOL_GRAPH_OWNER_MISMATCH`。

测试必须通过公开 `build_source_catalog()` + `build_symbol_graph()` 组合验证，不能直接调用产品私有
helper 制造 report。第 11 项必须使用同一个真实 SourceCatalog；第 14/15 项可以在成功 catalog 上
使用受限测试替身改变外部 bytes/owner registry，但不得替换 semantic root 或伪造 PySlang node。

目标模块完成后至少包含 15 个测试；每个第 8 节稳定错误码和负例输入都必须有独立断言。测试名、
fixture 名或固定数量不得进入产品分支。

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
- 不增加逐 symbol preserved/unsupported schema；T041 对不支持形状只执行第 4.3 节 whole-graph failure；
- 不修改 `__init__.py` 或公开用户命令。

## 13. 子 Agent 强制流程

本任务已经开始并因主 Agent 合同缺口暂停；不得删除、还原、stash 或重建现有允许范围内工作。
恢复执行时：

1. 完整重读修订后的第 4、8、9、10、13、16、17 节及 `docs/refactor_subagent_protocol.md`；
2. 确认 HEAD 仍包含合同提交 `5fc0309`，任务状态为 `IN_PROGRESS`，现有改动只在第 11 节允许范围；
3. 在第 15 节追加 `contract_revision_ack`，不得重跑或改写已记录的初始 baseline；
4. 先替换当前拼接 fake root 的 uninstantiated 测试，建立第 9 节真实、零诊断 fixture；
5. 再补 macro declaration/reference、range corruption、owner mismatch 四项独立黑盒测试；
6. 测试先行，逐项实现最小 preflight/error dispatch；禁止测试 fixture 名称或 module 名；
7. 若 PySlang 的真实 macro/uninstantiated location 与第 4.3 节不一致，记录实际 API 和最小输出后停止，
   不得改 oracle、拼接 semantic root 或加入 lexical fallback；
8. 完成后运行第 14 节四条命令；
9. 仅设置 `READY_FOR_REVIEW`、填写真实命令和输出后停止；
10. 不执行 `git add`、commit、push，不创建下一任务，不写主 Agent 验收记录。

本次恢复只允许一次完整 review request：现有 11-test 结果不是新的 review 依据，必须先完成第 8 节
六项负例矩阵和第 10 节至少 15 tests。除第 7 项明确的 PySlang API 不一致或第 11 节范围冲突外，
普通测试失败属于本任务内实现工作，不应拆成多次暂停并请求主 Agent 逐项补合同。

## 14. 唯一验收命令

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_symbol_graph_signals -v
conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/symbol_graph.py tests/test_symbol_graph_signals.py
git diff --check HEAD
rg -x -- '- 状态：`READY_FOR_REVIEW`' docs/tasks/T041_symbol_graph_signals.md
```

不运行全量 unittest、legacy signal tests、HDL compile、gate、decrypt、Yosys 或 RISC-V-Vector。
目标 unittest 必须自行执行 report/range audit 和第 8 节完整负例矩阵，并至少报告 15 tests；Formal
为 N/A，因为本任务不产生 rewritten RTL。主 Agent 不增加合同外输入、历史 acceptance driver 或
隐藏 oracle。

## 15. 子 Agent 执行记录

```text
status: READY_FOR_REVIEW
starting_head: 5fc03093228f38abeed2c74582ad4f1d851ce15a
changed_files: none at start; workspace was clean and T041 allowed files had no existing changes
baseline_command: `conda run -n rtl_obfuscation python -m unittest tests.test_symbol_graph_signals -v`
baseline_result: expected non-zero; target module is not yet present and import fails with `ModuleNotFoundError`
contract_revision_ack: resumed from CONTRACT_REVISED / WAITING_FOR_USER_RESUME; will replace the cross-compilation fake-root test with a zero-diagnostic inactive-generate fixture, complete all six section-8 negative inputs and at least 15 tests, then request one review only
revision: declaration ranges use `SYMBOL_GRAPH_RANGE_INVALID`; semantic nodes without a target or with an invalid target range fail closed instead of being silently ignored; `UninstantiatedDefSymbol` is detected before collection and fails closed; the valid ElementSelect base expression remains deduplicated
commands:
  - `conda run -n rtl_obfuscation python -m unittest tests.test_symbol_graph_signals -v`
  - `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/symbol_graph.py tests/test_symbol_graph_signals.py`
  - `git diff --check HEAD`
  - `rg -x -- '- 状态：\`READY_FOR_REVIEW\`' docs/tasks/T041_symbol_graph_signals.md`
results_before_contract_revision:
  - unittest: exit 0; `Ran 11 tests in 0.093s` and `OK`
  - py_compile: exit 0; no output
  - diff check: exit 0; no output
  - status guard: exit 0; output `- 状态：\`READY_FOR_REVIEW\``
schema_or_behavior: signals-only graph produced 6 symbols, 6 declarations, 12 semantic_expression occurrences, and 18 total ranges; source identity, owner identity, source bytes, ordering, uniqueness, non-overlap, normalized entrance equivalence, and canonical report serialization are covered by the target tests
deviations_or_blockers: original contract omitted executable fixtures/tests for macro declaration/reference, real uninstantiated generate, range corruption and owner mismatch; the existing uninstantiated test splices a node from another compilation and must be replaced; implementation is paused until the revised contract is acknowledged
boundaries: parameter/genvar/ABI/mapping/rewrite/CLI and lexical fallback remain out of scope; hierarchical, syntax-only, and uninstantiated definitions fail closed with `SYMBOL_GRAPH_UNSUPPORTED_REFERENCE`; no T040 API or legacy path was changed or called
formal_verification: N/A - no rewritten RTL is produced
review_request: WITHDRAWN; resume only after acknowledging the revised sections and completing the 15-test matrix
commands_after_contract_revision:
  - `conda run -n rtl_obfuscation python -m unittest tests.test_symbol_graph_signals -v`
  - `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/symbol_graph.py tests/test_symbol_graph_signals.py`
  - `git diff --check HEAD`
  - `rg -x -- '- 状态：\`READY_FOR_REVIEW\`' docs/tasks/T041_symbol_graph_signals.md`
results_after_contract_revision:
  - unittest: exit 0; `Ran 15 tests in 0.110s` and `OK`
  - py_compile: exit 0; no output
  - diff check: exit 0; no output
  - status guard: exit 0; output `- 状态：\`READY_FOR_REVIEW\``
schema_or_behavior_after_contract_revision: 15 target tests cover the positive 6/6/12/18 graph and all six frozen negative inputs; macro locations fail as `SYMBOL_GRAPH_UNSUPPORTED_SOURCE`, hierarchical and real inactive-generate uninstantiated definitions fail as `SYMBOL_GRAPH_UNSUPPORTED_REFERENCE`, post-catalog source-byte corruption fails as `SYMBOL_GRAPH_RANGE_INVALID`, and an empty owner registry fails as `SYMBOL_GRAPH_OWNER_MISMATCH`
deviations_or_blockers_after_contract_revision: none
review_request_after_contract_revision: READY_FOR_REVIEW; this is the single complete review request after the revised contract; no main-agent acceptance record was added
```

## 16. READY_FOR_REVIEW 条件

- 第 10 节全部行为由目标测试覆盖；
- 第 14 节四条命令全部退出 `0`；
- 实际 diff 只包含第 11 节允许文件；
- graph build 不重新编译、不读取 top overlay、不调用 legacy collector；
- repeated elaboration 已归一化为 source identity；
- 每个 symbol owner、declaration、occurrence 和 provenance 完整；
- 全部 source bytes 精确匹配，range 全局唯一且不重叠；
- hierarchical、真实 uninstantiated、macro declaration/reference、range corruption 和 owner mismatch
  六项负例全部通过第 8 节固定错误码；
- uninstantiated 测试没有替换 semantic root、拼接跨 compilation node 或调用私有 helper；
- 目标模块至少 15 tests，且第 8 节每个稳定错误码都有独立断言；
- 任务状态严格为 `READY_FOR_REVIEW`；
- Formal 记录为 `N/A: no rewritten RTL is produced`。

## 17. 主 Agent 验收边界

主 Agent 将：

1. 审查 `HEAD -> working tree` 完整 diff 和允许文件；
2. 在状态仍为 `READY_FOR_REVIEW` 时独立运行第 14 节四条命令；
3. 直接检查 6/12/18 range audit、同名 owner 分离和 repeated-instance source normalization；
4. 确认 project-root/filelist、single-file/filelist normalized graph 对等；
5. 审查第 8 节六项负例均由真实 fixture/受限公开输入触发，尤其确认 uninstantiated fixture 自身
   SourceCatalog 为零诊断、macro 与普通 range failure 的错误码已分流；
6. 确认没有第二次 compile、legacy inventory/rewrite、lexical fallback、伪 semantic root 或私有
   helper 验收；
7. 只独立复跑第 14 节四条命令，不增加合同外行为探针；
8. 全部通过后才增加主 Agent 验收记录并设置 `ACCEPTED`。

主 Agent 验收失败时，任务回到 `IN_PROGRESS` 或 `BLOCKED`；子 Agent 产生的任何 `ACCEPTED` 文本均
构成流程失败。每条退回意见必须引用本合同的具体条款或第 10 节测试；验收期间新想到、但本合同未
冻结的行为只能记录为后续任务候选，不能作为 T041 的新增阻塞条件。

## 18. 主 Agent 合同重审记录（2026-07-22）

```text
status: IN_PROGRESS / IMPLEMENTATION PAUSED
reason: the original contract froze macro, uninstantiated, range and owner failures without corresponding fixtures/tests; Main Agent then discovered them incrementally with out-of-contract probes
user_direction: pause sub-agent execution and revise the task before any further implementation
retained_work: current allowed-scope implementation, positive fixtures/tests, 6/12/18 audit, owner normalization, hierarchical handling and prior corrections remain in the working tree; no reset or rewrite is authorized
verified_pyslang_behavior: a legal zero-diagnostic parameterized generate with one inactive branch produces one `UninstantiatedDefSymbol`, so a real public-API fixture is feasible
revised_scope: strict direct-signal graph; whole-graph fail-closed for unsupported shapes; no per-symbol preserved schema and no lexical fallback
revised_acceptance: at least 15 target tests covering the positive graph plus the complete six-input negative matrix in section 8; Main Agent will use only section 14 commands
resume_state: CONTRACT_REVISED / WAITING_FOR_USER_RESUME; task remains IN_PROGRESS until the user requests a new sub-agent instruction
formal_verification: N/A - contract revision produces no rewritten RTL
```

## 19. 主 Agent 验收记录（2026-07-23）

```text
status: ACCEPTED
reviewed_head: 5fc03093228f38abeed2c74582ad4f1d851ce15a
reviewed_scope: only section 11 allowed files; no staged files, commit or push
independent_commands:
  - `conda run -n rtl_obfuscation python -m unittest tests.test_symbol_graph_signals -v`
  - `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/symbol_graph.py tests/test_symbol_graph_signals.py`
  - `git diff --check HEAD`
  - `rg -x -- '- 状态：\`READY_FOR_REVIEW\`' docs/tasks/T041_symbol_graph_signals.md`
independent_results:
  - unittest: exit 0; `Ran 15 tests in 0.108s`; `OK`
  - py_compile: exit 0; no output
  - diff check: exit 0; no output
  - READY_FOR_REVIEW guard: exit 0 before acceptance; exact status line matched
review_findings: none within the frozen T041 contract
verified_behavior: 6/6/12/18 positive range audit, repeated-instance source normalization, owner separation, three-entry normalized reports and all six frozen fail-closed inputs passed; inactive-generate evidence uses one zero-diagnostic SourceCatalog and no fabricated semantic root
formal_verification: N/A - no rewritten RTL is produced
decision: ACCEPTED
```
