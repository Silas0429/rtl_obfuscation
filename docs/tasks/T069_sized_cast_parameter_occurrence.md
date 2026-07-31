# T069：sized-cast parameter occurrence 精确绑定与 actual-gate 闭环

- 状态：`ACCEPTED`
- 合同版本：1.0
- 设计时间：2026-07-31
- 设计负责人：主 Agent
- 实现负责人：子 Agent
- 前置任务：T068 `ACCEPTED`，交付提交 `1bd4e3d`
- 设计基线 HEAD：`97c97a5b5e27c0d6dc71da3e6412778deb8782d5`
- 任务类型：SymbolGraph parameter occurrence 修复；产生 rewritten RTL
- 执行规范：[`refactor_subagent_protocol.md`](../development/process/refactor_subagent_protocol.md)
- 架构依据：[`three_mode_refactor_plan.md`](../development/architecture/three_mode_refactor_plan.md)
- Formal 依据：[`formal_verification.md`](../formal_verification.md)
- Formal verification：必须使用 T069 compact fixture 的 actual renamed gate 执行正例和固定功能负例

## 1. 当前项目位置与唯一目标

当前产品数据流保持不变：

```text
SourceSet -> SourceCatalog -> SymbolGraph -> RewritePolicy -> MappingVNext
    -> actual gate -> strict compile -> restore -> Formal
```

T069 只修正 `parameters` category 中一个已经跨真实工程复现的 occurrence 完整性缺陷：

```systemverilog
WIDTH'(0)
POINTER_WIDTH'(~0)
IrLength'(4'b0101)
```

现有 parameter collector 能收集参数 declaration、普通表达式、declared dimension、generate
control 和 named override，但没有把 identifier-sized cast 左侧的参数 token 绑定到同一个
`ParameterSymbol`。因此参数 declaration 被改名，cast token 仍保留旧名称，最终由 strict gate
compile 报 `UndeclaredIdentifier`。

本任务的唯一目标是：

> 在现有 SymbolGraph parameter collector 内，从固定 `CastExpressionSyntax` 路径取得直接
> identifier token，通过最窄且唯一的 semantic lexical scope `lookupName()` 绑定到精确的
> module value parameter 或 source localparam declaration，并以
> `provenance=sized_cast_type` 加入该参数的 occurrences。

本任务不是通用 cast、macro、type parameter、nested generate 或构建输入适配任务。

## 2. 起始状态与继承工作区

主 Agent 建立本合同时的状态：

```text
branch: main...origin/main
HEAD: 97c97a5b5e27c0d6dc71da3e6412778deb8782d5
staged changes: none
historical blocked task: T038 remains BLOCKED / NOT_ACCEPTED
current implementation task: T069 is the only READY task
```

主 Agent 已建立但尚未提交的 T069 合同输入：

```text
docs/tasks/T069_sized_cast_parameter_occurrence.md
tests/fixtures/t069_sized_cast/design.f
tests/fixtures/t069_sized_cast/rtl/child.sv
tests/fixtures/t069_sized_cast/rtl/shadow.sv
tests/fixtures/t069_sized_cast/rtl/top.sv
```

此外，工作区继承用户此前授权的：

```text
docs/development/future_work.md
```

其中只有 sized-cast 真实工程边界记录发生变化。子 Agent 不得还原、stash、移动、覆盖或删除
这些继承变化。`future_work.md` 只允许在 T069 行为全部通过后，把该边界同步为已支持并保留真实
工程复测说明；不得改写其他 future-work 项。

如果启动时出现上述列表之外的新变化，先在第 15 节记录并停止，不得自行清理工作区。

## 3. 主 Agent 冻结的 compact 输入

### 3.1 文件结构

```text
tests/fixtures/t069_sized_cast/
  design.f
  rtl/child.sv
  rtl/shadow.sv
  rtl/top.sv
```

固定 top：

```text
t069_sized_cast_top
```

固定 compile order：

```text
rtl/child.sv
rtl/shadow.sv
rtl/top.sv
```

固定选择：

```text
categories: signals, parameters, genvars
abi_categories: parameters
name_length: 16
```

fixture 覆盖：

1. child module value parameter `WIDTH`；
2. child parameter 默认值 `RESET_VALUE = WIDTH'(0)`；
3. child localparam `LOCAL_WIDTH` 及 `LOCAL_WIDTH'(data_i)`；
4. child continuous assignment 中的 `WIDTH'(RESET_VALUE)`；
5. shadow module value parameter `WIDTH`；
6. generate block 内同名 localparam `WIDTH`；
7. generate block procedure 内的 `WIDTH'(data_i)` 必须绑定内层 localparam；
8. generate block 外的 `WIDTH'(data_i)` 必须绑定 module parameter；
9. top 对 child/shadow `WIDTH` 的 named parameter override；
10. 一个 Yosys 可证明且可做单字节功能负例的组合逻辑 top。

### 3.2 冻结 bytes 与 SHA-256

| file | bytes | SHA-256 |
| --- | ---: | --- |
| `tests/fixtures/t069_sized_cast/design.f` | 38 | `d219132843e4e46a3757571ad9b9beed19894c5b8e2f86388a6793cfeb3cd83f` |
| `tests/fixtures/t069_sized_cast/rtl/child.sv` | 396 | `788e7cf7ca6d628421fe79d4f88e816fe69d4a4943565a1d54e6086afa29884a` |
| `tests/fixtures/t069_sized_cast/rtl/shadow.sv` | 380 | `86ea8141d9018bcab347f419a6eec44177b394b7d9142e4741aee6813edfa531` |
| `tests/fixtures/t069_sized_cast/rtl/top.sv` | 478 | `ed87610ec05e1fe0ffb32c86bfeca19000443ee120de6813094cad1cf1f78105` |

这些文件由主 Agent 冻结，子 Agent 全部只读。任何 hash 不一致都必须记录并停止；不得修改 fixture
或更新合同 oracle。

## 4. 主 Agent 预检事实

### 4.1 前端与 Formal harness

主 Agent 已在 Conda 环境 `rtl_obfuscation` 验证：

```text
PySlang catalog parse/semantic: 0/0
PySlang top overlay parse/semantic: 0/0
Verible syntax: PASS, exit 0
Icarus -g2012 elaboration: PASS, exit 0
Yosys identity baseline: PASS, formal_equivalence=pass, top=t069_sized_cast_top, seq=5
fixed one-byte `~` negative: exit 1, contains unproven and equiv_status -assert
```

identity baseline 只证明 fixture 和 Formal harness 可执行，不是 T069 的正向交付证据。T069 验收
必须使用修复后实际改名的 gate。

固定功能负例：

```text
从 actual verified gate 复制 negative gate；
在 rtl/top.sv 唯一的 `assign data_o = ` 后插入一个 ASCII `~`；
其余 gate bytes 不变；
negative gate strict compile 必须仍为 catalog/top-overlay 0/0；
Formal 必须非 0，并包含 unproven 和 equiv_status -assert。
```

### 4.2 PySlang API 与 lexical binding 事实

catalog semantic view 中的五个物理 sized-cast token：

| token | file:start | 必须绑定的 declaration |
| --- | --- | --- |
| `WIDTH` | `rtl/child.sv:93` | child module parameter `WIDTH`, declaration start `50` |
| `LOCAL_WIDTH` | `rtl/child.sv:301` | child localparam `LOCAL_WIDTH`, declaration start `202` |
| `WIDTH` | `rtl/child.sv:365` | child module parameter `WIDTH`, declaration start `50` |
| `WIDTH` | `rtl/shadow.sv:297` | generate block localparam `WIDTH`, declaration start `192` |
| `WIDTH` | `rtl/shadow.sv:354` | shadow module parameter `WIDTH`, declaration start `51` |

已确认的 API 形状：

1. 四个 body cast 暴露
   `ConversionExpression.syntax -> CastExpressionSyntax.left -> IdentifierNameSyntax.identifier`；
2. `ConversionExpression.type` 为 `PackedArrayType`，不是可直接指向参数 declaration 的
   `TypeAliasType`；
3. `ConversionExpression.getSymbolReference()` 对这五种形状返回 `None`，不得依赖它建立绑定；
4. 被 top override 的 `RESET_VALUE` semantic initializer 已变成 literal `1`，但
   `ParameterSymbol.syntax` 仍是 `DeclaratorSyntax`，其固定 `initializer` 子树保留
   `WIDTH'(0)` 的物理 token；
5. semantic `ParameterSymbol.parentScope.lookupName("WIDTH")` 可把默认值 token 精确解析到 child
   `WIDTH` declaration；
6. procedure/continuous-assign semantic container 暴露 `parentScope.lookupName()`；
7. `rtl/shadow.sv:297` 同时位于 generate scope 和更窄的 procedural scope：generate scope
   lookup 得到外层 declaration `51`，procedural scope lookup 得到正确的内层 declaration
   `192`。实现必须选择包含 token 的最窄、唯一、物理 semantic scope；不得选任意祖先 scope。

如果实际 PySlang API 与上述事实不一致，必须在第 15 节记录第一个差异并设置 `BLOCKED`，不得改用
全文搜索、owner/name 猜测或更新 oracle。

### 4.3 当前缺陷基线

当前实现对固定 fixture 的结果：

```text
whole graph symbols/declarations/occurrences/total_ranges: 20/20/32/52
parameter symbols: 5
sized_cast_type occurrences: 0
mapping total/rename/preserve/unsupported: 20/9/11/0
current modified_tokens: 27
all five parameter records: action=rename
write_gate_vnext: REWRITE_GATE_COMPILE_FAILED
inner cause: CATALOG_SEMANTIC_FAILED
gate output remains absent after failure
```

这说明失败不是 fixture、SourceSet、SourceCatalog、RewritePolicy、MappingVNext 或 Formal harness
问题，而是五个真实 cast token 没有进入 parameter occurrences。

## 5. API、schema 与 provenance 合同

不得新增或修改公开 API。继续使用：

```python
build_symbol_graph(source_catalog: SourceCatalog) -> SymbolGraph
```

以下保持不变：

```text
SourceSymbol schema_version: 1
SymbolGraph schema_version: 1
RewritePolicy schema_version: 1
MappingVNext schema_version: 1
category: parameters
symbol_id: symbol:parameters:<file>:<start>:<end>
```

T069 只新增一个 parameter occurrence provenance：

```text
sized_cast_type
```

含义限定为：`CastExpressionSyntax.left` 是直接 `IdentifierNameSyntax`，且该 token 经最窄 semantic
lexical scope 的 `lookupName()` 精确绑定到现有非-type `ParameterSymbol` declaration。

不得把 keyword cast、typedef cast、literal-sized cast 或无法解析的 identifier cast 标成
`sized_cast_type`。

## 6. 允许的最小绑定算法

### 6.1 candidate

只允许处理固定 typed syntax：

```text
CastExpressionSyntax
  -> left: IdentifierNameSyntax
  -> identifier: direct non-empty physical token
```

以下不是 T069 candidate：

- `signed'(...)`、`unsigned'(...)` 等 builtin keyword cast；
- typedef / struct / enum / package type cast；
- literal-sized cast；
- macro-generated cast type token；
- `left` 没有直接 identifier token 的 cast；
- target 不是现有 module-owned value parameter/source localparam record。

非 candidate 继续交给既有 collector 或既有 fail-closed 路径；T069 不得改变其行为。

### 6.2 lexical scope 证据

允许建立一个仅服务 T069 的私有、typed semantic scope 索引：

1. scope candidate 必须来自当前 `SourceCatalog.catalog_root` 的 semantic node；
2. semantic node 必须同时具有：
   - `parentScope.lookupName`；
   - SourceSet 内非 macro 的直接 physical syntax span；
3. cast token 必须位于该 physical span 内；
4. 对同一 token，选择 span 最小的 scope candidate；
5. 如果最小 span 不唯一且解析到不同 declaration，返回
   `SYMBOL_GRAPH_UNSUPPORTED_REFERENCE`；
6. `lookupName(token.rawText)` 的结果必须通过现有 `_parameter_source_key()` 映射到唯一
   `_ParameterRecord`；
7. token bytes 必须精确等于 parameter name，range 必须在 SourceSet physical file 内。

parameter declaration 默认 initializer 允许从已绑定 `ParameterSymbol.syntax` 的固定
`DeclaratorSyntax.initializer` 子树取得 `CastExpressionSyntax`，并直接使用该
`ParameterSymbol.parentScope` 做 lexical lookup。即使 elaboration 因 named override 让 semantic
initializer 变成 literal，也必须保留源码默认值中的物理 cast occurrence。

### 6.3 禁止的绑定方式

禁止：

- 全文件正则或字符串搜索；
- 遍历所有 identifier 后按名字猜参数；
- 按 module owner + name 选 declaration；
- 选择第一个、任意一个或最外层 enclosing scope；
- 使用 Python object identity 作为持久 owner/range 证据；
- 调用 legacy parameter/cast collector；
- 在 mapping、rewrite、strict compile 或 restore 阶段补 token；
- 捕获错误后忽略 cast 并继续生成 mapping。

### 6.4 去重和冲突

- declaration 不进入 occurrences；
- sized cast 按 `(file,start,end,provenance)` 去重；
- 同一 physical cast token 因 repeated elaboration 出现多次，只保留一个 occurrence；
- 同一 range 已属于同一 parameter 的其他 provenance 时，以精确语法上下文归一化为
  `sized_cast_type`，不得保留两个 range；
- 同一 range 绑定不同 parameter declaration 时返回 `SYMBOL_GRAPH_RANGE_CONFLICT`；
- symbols、occurrences 和全局 range 继续使用现有 canonical 排序与非重叠审计。

## 7. 修复后冻结 oracle

### 7.1 SymbolGraph

```text
whole graph symbols/declarations/occurrences/total_ranges: 20/20/37/57
parameter symbols: 5
parameter occurrences: 16
sized_cast_type occurrences: 5
```

五个 cast token 必须按第 4.2 节精确绑定，尤其：

```text
rtl/shadow.sv:297 -> localparam WIDTH declaration 192
rtl/shadow.sv:354 -> module parameter WIDTH declaration 51
```

不得仅断言“名字相同”或“gate 编译通过”；测试必须断言 declaration source range identity。

### 7.2 MappingVNext

使用第 3.1 节选择和测试专用确定性 NameFactory：

```text
mapping total/rename/preserve/unsupported: 20/9/11/0
modified_tokens: 32
parameter records: 5
all five parameter records: action=rename
```

T069 只增加五个 occurrence/edit，不改变 symbol 数量、classification、action 或 reason。

## 8. actual gate、restore 与 Formal

目标测试必须从修复后的 graph 和 policy 建立真实 MappingVNext，再调用现有
`write_gate_vnext()`，不能复制 gold 或构造 fake execution。

actual gate 必须满足：

```text
physical files: 3
mapping_records: 20
renamed_records: 9
modified_tokens: 32
catalog parse/semantic: 0/0
top overlay parse/semantic: 0/0
```

五个 source cast ranges 必须各对应一个实际 edit，edit 的 `symbol_id` 与目标 parameter record
完全相同。不得在 gate strict compile 后再次搜索并补改。

restore 必须：

```text
只消费 actual gate + execution/report
restored_manifest == mapping.input_manifest
3 files byte-identical
```

Formal 正例固定：

```text
gold_filelist: tests/fixtures/t069_sized_cast/design.f
gold_root: tests/fixtures/t069_sized_cast
gate_filelist: <TemporaryDirectory>/gate/design.f
gate_root: <TemporaryDirectory>/gate
top: t069_sized_cast_top
seq: 5
expected exit: 0
required JSON:
  formal_equivalence=pass
  top=t069_sized_cast_top
  seq=5
```

Formal 负例按第 4.1 节固定单字节 `~` 方法执行。

## 9. 目标测试：恰好 9 项新增行为

新增 `tests/test_t069_sized_cast_parameter.py`，只使用公开 SourceSet/SourceCatalog/SymbolGraph、
RewritePolicy、MappingVNext、rewrite/restore 和 Formal script 覆盖：

1. fixed fixture catalog/top-overlay 为 0/0，graph 为 `20/20/37/57`；
2. 五个 `sized_cast_type` token 的 file/start、bytes 和 declaration identity 精确符合第 4.2 节；
3. 被 top override 的 `RESET_VALUE` 仍从 declaration initializer 收集 `rtl/child.sv:93`；
4. shadow 内外 `WIDTH` 分别绑定 declaration `192` 和 `51`，不能串 owner；
5. parameter occurrences 为 16，五个新 occurrence canonical 排序、去重、无重叠；
6. mapping 为 `20/9/11/0`、`modified_tokens=32`，五个 parameter record 均 rename；
7. actual gate strict compile `0/0 + 0/0`、五个 cast edit 完整、restore 三文件 byte-identical；
8. actual renamed gate Formal 正例 exit 0，JSON 三字段精确通过；
9. 单字节 `~` negative gate strict compile 通过，Formal 非 0 且含两个固定失败标志。

第 1 项还必须在 SourceCatalog 已建立后 monkeypatch
`rtl_obfuscator.source_catalog._compile_view` 为立即失败，随后 `build_symbol_graph(catalog)` 仍成功，
证明 T069 不重新编译或建立第二个 semantic view。

测试不得调用 `symbol_graph.py` 私有 helper 直接制造 occurrence，不得按 fixture 名称、top、offset
或固定数量进入产品分支。offset/count 只允许出现在黑盒测试 oracle。

现有 `tests.test_symbol_graph_parameters` 为 19 tests；T069 新增 9 tests。验收命令固定：

```text
Ran 28 tests
OK
```

## 10. 允许修改的文件

子 Agent 只允许修改：

```text
rtl_obfuscator/symbol_graph.py
tests/test_t069_sized_cast_parameter.py
docs/development/future_work.md
docs/tasks/T069_sized_cast_parameter_occurrence.md
```

限制：

- `symbol_graph.py` 只实现第 5–7 节的 parameter sized-cast occurrence；
- 新 test 文件只覆盖第 9 节；
- `future_work.md` 只更新现有 sized-cast 条目，不得修改其他边界；
- 本任务文档只允许状态、执行记录、偏差/阻塞和主 Agent 验收区变化。

第 3 节 fixture 全部只读。其余产品代码、tests、README、renaming table、SourceSet、SourceCatalog、
RewritePolicy、MappingVNext、rewrite、restore、metrics、CLI、Formal script 和 RISC 文件均不得修改。

需要允许列表外修改时，先在第 15 节记录具体路径和原因并设置 `BLOCKED`，不得自行扩 scope。

## 11. 明确不包含

T069 不实现：

- builtin keyword cast 忽略；留给 T070；
- type parameter、`defparam`、nested/conditional generate 安全保留；
- macro-generated declaration/reference/module name；
- typedef、enum、struct、package-qualified cast 的新行为；
- project-root/filelist/package/provider 构建适配；
- 新 CLI、配置项、fallback 或 compatibility mode；
- SourceSymbol、SymbolGraph、MappingVNext、report schema/version 变化；
- rate/metrics 方程变化；
- RISC-V-Vector Formal 或真实仓库 clone 复测；
- legacy collector 清理。

非 T069 cast 形状继续维持当前行为。不得为了让其他仓库通过而顺手修改。

## 12. 子 Agent 强制行为规范

### 12.1 启动前

1. 完整阅读：
   - `AGENTS.md`；
   - 本合同全文；
   - `docs/development/process/refactor_subagent_protocol.md`；
   - `docs/development/architecture/three_mode_refactor_plan.md` 第 2–5 节；
   - `docs/formal_verification.md`。
2. 第一条命令必须是 `git status --short --branch`。
3. 记录 starting HEAD、branch、staged/unstaged/untracked 文件。
4. 确认 starting HEAD 精确为第 2 节基线。
5. 确认 T069 是唯一 `READY`，没有 `IN_PROGRESS` 或 `READY_FOR_REVIEW`；T038 的历史
   `BLOCKED / NOT_ACCEPTED` 不视为当前实现任务。
6. 校验第 3.2 节四个 fixture hash。
7. 确认继承变化只包括第 2 节所列文件。
8. 在修改实现或测试前，把本文件状态从 `READY` 改为 `IN_PROGRESS`，并填写第 15 节启动记录。
9. 状态更新后只运行第 14 节第一条 baseline 命令。

### 12.2 baseline

预期 baseline：

```text
tests.test_symbol_graph_parameters: 19/19 PASS
tests.test_t069_sized_cast_parameter: ModuleNotFoundError
Ran 20 tests
FAILED (errors=1)
exit code: nonzero
```

缺少新测试模块是实现前 baseline absence，不是合同冲突。除此以外任何既有测试失败都必须记录并
停止；不得先修改产品代码。

### 12.3 实现顺序

严格按以下顺序：

1. 创建第 9 节九项黑盒测试；
2. 运行目标 unittest，确认失败直接指向缺少五个 sized-cast occurrence 或 gate strict compile；
3. 在 `symbol_graph.py` 建立最小 typed cast/scope 绑定；
4. 先通过 graph/range/lexical shadow 测试；
5. 再通过 mapping/strict gate/restore 测试；
6. 最后通过 Formal 正例和负例；
7. 行为全部通过后，才更新 `future_work.md` 的 sized-cast 状态；
8. 运行第 14 节四条唯一验收命令；
9. 一次性填写真实执行证据并设置 `READY_FOR_REVIEW`。

普通的任务内测试、strict compile 或 Formal 失败应继续诊断和修正，不应分批请求主 Agent；只有
第 13 节停止条件触发时才暂停。

### 12.4 工具与文件边界

- 所有 Python、PySlang、测试和 EDA 命令使用
  `conda run -n rtl_obfuscation <command>`；
- 测试内部调用 Formal 使用当前 `sys.executable scripts/formal_equivalence.py`，不得在已进入
  Conda 的 unittest 内再嵌套 `conda run`；
- 所有 gate、negative gate、mapping、restore 和 Formal 工作目录必须位于
  `TemporaryDirectory` 或 `/private/tmp`；
- 不得写入 fixture、RTL samples 或真实仓库；
- 不得运行 blanket `unittest discover`；
- 不得运行 `tests.test_risc_v_vector_project_root`、RISC acceptance driver 或 RISC Formal；
- 不得 commit、push、stage、amend、rebase 或创建分支；
- 不得设置 `ACCEPTED`、创建 T070 或写主 Agent 验收结论。

## 13. 必须停止并记录的条件

只有以下情况允许设置 `BLOCKED` 或请求主 Agent：

1. fixture hash 与第 3.2 节不一致；
2. starting HEAD 或继承工作区超出第 2 节；
3. PySlang API 与第 4.2 节冲突；
4. 精确 lexical scope 无法唯一解析 token；
5. 正确实现不能保持第 7 节冻结 oracle；
6. 修复需要修改第 10 节允许列表之外的文件；
7. 修复需要新增公开 API、schema、dependency 或通用框架；
8. actual renamed gate 无法通过 strict compile 或 Formal，且根因不在 T069 collector 范围；
9. Formal identity baseline或固定负例 harness 与第 4.1 节不一致。

停止时必须记录第一个冲突的：

```text
file/start
syntax kind
semantic container/scope
lookup target kind/name/declaration
expected oracle
actual result
proposed extra file/API if any
```

不得更新 fixture、oracle、Formal top/seq 或负例方法来制造通过。

## 14. 唯一验收命令

只运行以下四条：

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_symbol_graph_parameters tests.test_t069_sized_cast_parameter -v
conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/symbol_graph.py tests/test_t069_sized_cast_parameter.py
git diff --check HEAD
rg -x -- '- 状态：`READY_FOR_REVIEW`' docs/tasks/T069_sized_cast_parameter_occurrence.md
```

第一条 unittest 内部必须真实运行 actual renamed gate strict compile、三文件 restore 和 Yosys Formal
正负例。不得用额外 identity/copy-gold 命令替代。

状态 guard 必须最后运行；只有前三条成功且执行记录完整后，才能把状态设置为
`READY_FOR_REVIEW`。

## 15. 子 Agent 执行记录

开始时填写：

```text
status: IN_PROGRESS
starting_head:
start_time:
first_command:
branch:
staged_changes:
inherited_worktree:
active_task_check:
fixture_hash_check:
baseline_command:
baseline_exit_code:
baseline_result:
```

发现偏差或阻塞时追加，不得覆盖历史：

```text
deviation_or_blocker:
first_conflicting_file_start:
syntax_and_scope_facts:
expected:
actual:
required_scope_change:
status_action:
```

完成时填写：

```text
status: READY_FOR_REVIEW
changed_files:
target_tests:
graph_oracle:
cast_bindings:
mapping_oracle:
strict_compile:
restore:
formal_positive:
formal_negative:
future_work_update:
acceptance_commands:
acceptance_exit_codes:
git_diff_check:
ready_for_review_guard:
remaining_boundaries:
review_request:
```

Formal 记录必须包含：

```text
formal_verification: PASS
gold: tests/fixtures/t069_sized_cast
gate: <actual TemporaryDirectory gate>
top: t069_sized_cast_top
command: <exact sys.executable scripts/formal_equivalence.py arguments>
exit_code: 0
result: <actual final JSON>
negative_gate: <actual TemporaryDirectory negative path>
negative_exit_code: <nonzero>
negative_markers: unproven; equiv_status -assert
```

### v1 启动记录

```text
status: IN_PROGRESS
starting_head: 97c97a5b5e27c0d6dc71da3e6412778deb8782d5
start_time: 2026-07-31T14:30:41+0800
first_command: git status --short --branch
branch: main...origin/main
staged_changes: none
inherited_worktree: docs/development/future_work.md; T069 contract; four untracked T069 fixture files only
active_task_check: T069 is the only READY task; no IN_PROGRESS or READY_FOR_REVIEW task; T038 historical BLOCKED/NOT_ACCEPTED
fixture_hash_check: all four hashes match section 3.2
baseline_command: conda run -n rtl_obfuscation python -m unittest tests.test_symbol_graph_parameters tests.test_t069_sized_cast_parameter -v
baseline_exit_code: 1
baseline_result: existing parameter tests 19/19 passed; tests.test_t069_sized_cast_parameter failed to import with ModuleNotFoundError; Ran 20 tests; FAILED (errors=1)
allowed_files: rtl_obfuscator/symbol_graph.py; tests/test_t069_sized_cast_parameter.py; docs/development/future_work.md; docs/tasks/T069_sized_cast_parameter_occurrence.md
```

### v1 完成记录

```text
status: READY_FOR_REVIEW
changed_files: rtl_obfuscator/symbol_graph.py; tests/test_t069_sized_cast_parameter.py; docs/development/future_work.md; docs/tasks/T069_sized_cast_parameter_occurrence.md
target_tests: tests.test_symbol_graph_parameters (19) + tests.test_t069_sized_cast_parameter (9) = 28
graph_oracle: symbols/declarations/occurrences/total_ranges=20/20/37/57; parameter symbols=5; source catalog and top overlay parse/semantic=0/0
cast_bindings: rtl/child.sv:93 -> declaration 50; rtl/child.sv:301 -> declaration 202; rtl/child.sv:365 -> declaration 50; rtl/shadow.sv:297 -> declaration 192; rtl/shadow.sv:354 -> declaration 51; all provenance=sized_cast_type; all source bytes exact; declaration not repeated
lexical_scope: direct CastExpressionSyntax.left IdentifierNameSyntax; body casts use the smallest source-backed semantic scope and lookupName(); overridden RESET_VALUE initializer uses its ParameterSymbol.parentScope; no owner/name or file-search fallback
mapping_oracle: total/rename/preserve/unsupported=20/9/11/0; parameter occurrences=16; sized_cast_type occurrences=5; modified_tokens=32; all five parameter records action=rename
strict_compile: actual renamed gate physical files=3; catalog/top-overlay parse/semantic=0/0 + 0/0; five sized-cast edits present with matching parameter symbol IDs
restore: actual gate + execution restore_manifest equals mapping.input_manifest; 3 physical files byte-identical; TemporaryDirectory outputs cleaned
formal_positive: actual renamed gate from write_gate_vnext(); per-test TemporaryDirectory gate; exit_code=0; JSON formal_equivalence=pass, top=t069_sized_cast_top, seq=5
formal_negative: actual gate copy with one ASCII '~' after unique assign data_o =; catalog/top-overlay=0/0 + 0/0; exit_code nonzero; output contains unproven and equiv_status -assert
future_work_update: only existing sized-cast boundary entry updated; CDC FIFO and riscv-dbg JTAG wrapper boundary examples retained
acceptance_commands: conda run -n rtl_obfuscation python -m unittest tests.test_symbol_graph_parameters tests.test_t069_sized_cast_parameter -v; conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/symbol_graph.py tests/test_t069_sized_cast_parameter.py; git diff --check HEAD; rg -x -- '- 状态：`READY_FOR_REVIEW`' docs/tasks/T069_sized_cast_parameter_occurrence.md
acceptance_exit_codes: unittest=0 (Ran 28 tests; OK); py_compile=0; git_diff_check=0; status_guard=pending until final command
git_diff_check: exit_code=0; no whitespace errors
ready_for_review_guard: pending until final command
remaining_boundaries: builtin keyword casts, typedef/package/type-parameter casts, macro-generated casts, and other non-T069 cast shapes remain unchanged and fail-closed/current behavior
formal_verification: PASS
review_request: T069 sized-cast parameter occurrence fix is complete within the four allowed files; ready for independent review
```

### v1 最小返工记录

```text
status: IN_PROGRESS
recovery_start_time: 2026-07-31T14:56:19+0800
starting_head: 97c97a5b5e27c0d6dc71da3e6412778deb8782d5
starting_worktree: git status --short --branch -> ## main...origin/main; inherited T069 files only; no staged changes
reason: independent review found three documentation/coverage gaps without architectural scope change
allowed_changes: rtl_obfuscator/symbol_graph.py; tests/test_t069_sized_cast_parameter.py; docs/tasks/T069_sized_cast_parameter_occurrence.md
required_fixes: filter same-buffer/containing scope before _semantic_scope_span; assert each sized-cast edit symbol_id equals its parameter record; replace pending execution evidence with actual paths, command, JSON and negative exit code
release_driver_or_risc_formal: not run
```

### v1 最小返工完成记录

```text
status: READY_FOR_REVIEW
changed_files: rtl_obfuscator/symbol_graph.py; tests/test_t069_sized_cast_parameter.py; docs/tasks/T069_sized_cast_parameter_occurrence.md
scope_fix: same-buffer and actual-containing-token checks now precede _semantic_scope_span(); unrelated macro/external spans cannot affect ordinary sized casts
edit_identity_fix: all five actual sized_cast_type edits are compared as {(file,start): edit.symbol_id} against the corresponding parameter MappingRecord.symbol_id
commands: conda run -n rtl_obfuscation python -m unittest tests.test_symbol_graph_parameters tests.test_t069_sized_cast_parameter -v; conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/symbol_graph.py tests/test_t069_sized_cast_parameter.py; git diff --check HEAD; rg -x -- '- 状态：`READY_FOR_REVIEW`' docs/tasks/T069_sized_cast_parameter_occurrence.md
results: unittest exit_code=0; Ran 28 tests in 0.844s; OK. py_compile exit_code=0. git diff --check HEAD exit_code=0. status_guard pending until final command
graph_oracle: symbols/declarations/occurrences/total_ranges=20/20/37/57; parameter occurrences=16; sized_cast_type=5
mapping_oracle: total/rename/preserve/unsupported=20/9/11/0; modified_tokens=32; five actual cast edit symbol IDs equal their parameter records
strict_compile: actual gate catalog/top-overlay parse/semantic=0/0 + 0/0
restore: actual gate execution restored 3 physical files byte-identical; restored manifest equals input manifest; TemporaryDirectory cleanup applied
formal_verification: PASS
gold: /Users/lufengchi/Desktop/workspace/rtl_obfuscation/tests/fixtures/t069_sized_cast
gate: /private/tmp/t069-formal-4887n9sb/gate
top: t069_sized_cast_top
command: /Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python scripts/formal_equivalence.py --gold-filelist /Users/lufengchi/Desktop/workspace/rtl_obfuscation/tests/fixtures/t069_sized_cast/design.f --gold-root /Users/lufengchi/Desktop/workspace/rtl_obfuscation/tests/fixtures/t069_sized_cast --gate-filelist /private/tmp/t069-formal-4887n9sb/gate/design.f --gate-root /private/tmp/t069-formal-4887n9sb/gate --top t069_sized_cast_top --seq 5
exit_code: 0
result: {"formal_equivalence": "pass", "gate": "/private/tmp/t069-formal-4887n9sb/gate", "gold": "/Users/lufengchi/Desktop/workspace/rtl_obfuscation/tests/fixtures/t069_sized_cast", "seq": 5, "top": "t069_sized_cast_top"}
negative_gate: /private/tmp/t069-negative-f043fyhv/negative
negative_command: /Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python scripts/formal_equivalence.py --gold-filelist /Users/lufengchi/Desktop/workspace/rtl_obfuscation/tests/fixtures/t069_sized_cast/design.f --gold-root /Users/lufengchi/Desktop/workspace/rtl_obfuscation/tests/fixtures/t069_sized_cast --gate-filelist /private/tmp/t069-negative-f043fyhv/negative/design.f --gate-root /private/tmp/t069-negative-f043fyhv/negative --top t069_sized_cast_top --seq 5
negative_exit_code: 1
negative_markers: unproven; equiv_status -assert
ready_for_review_guard: pending until final command
remaining_boundaries: non-T069 casts retain existing behavior; no RISC or blanket discovery was run
review_request: three local acceptance gaps corrected without changing fixture, schema, architecture, or scope
```

## 16. READY_FOR_REVIEW 条件

必须全部满足：

1. 只修改第 10 节四个允许文件；
2. fixture 四个 hash 未变化；
3. 九项 T069 行为与 19 项 parameter regression 共 28 tests 通过；
4. graph、cast bindings、mapping 和 modified token oracle 全部精确通过；
5. actual renamed gate strict compile 0/0 + 0/0；
6. restore 三文件 byte-identical；
7. actual gate Formal 正例通过，固定功能负例按预期失败；
8. `py_compile` 通过；
9. `git diff --check HEAD` 通过；
10. `future_work.md` 只同步 sized-cast 条目；
11. 第 15 节执行记录完整；
12. 状态严格为 `READY_FOR_REVIEW`；
13. 无 commit、push、stage、`ACCEPTED` 或 T070。

## 17. 主 Agent 后续验收边界

子 Agent 到 `READY_FOR_REVIEW` 后停止。主 Agent负责：

1. 审查 allowed-file diff 和 fixture hash；
2. 独立运行第 14 节四条命令；
3. 独立确认 unittest 使用 actual renamed gate，而非 identity/copy-gold；
4. 核对 Formal JSON、负例 marker、strict compile 和 restore evidence；
5. 只有全部通过后才设置 `ACCEPTED`；
6. 验收后再决定 commit/push；
7. T069 完成前不创建 T070。

## 18. 子 Agent 启动指令

将以下内容原样交给子 Agent：

```text
你是 T069 的实现子 Agent。工作目录：
/Users/lufengchi/Desktop/workspace/rtl_obfuscation

你的唯一任务是执行：
docs/tasks/T069_sized_cast_parameter_occurrence.md

开始前必须完整阅读 AGENTS.md、T069 合同、
docs/development/process/refactor_subagent_protocol.md、
docs/development/architecture/three_mode_refactor_plan.md 第2—5节、
docs/formal_verification.md。

第一条命令必须是 git status --short --branch。随后核对 starting HEAD、
唯一 READY 任务、继承工作区和四个 fixture SHA-256。任何实现或测试编辑前，
先把 T069 状态从 READY 改为 IN_PROGRESS，并填写第15节启动记录。

然后只运行第14节第一条命令作为 baseline。预期19个既有 parameter tests通过，
新 tests.test_t069_sized_cast_parameter 因尚不存在而 ModuleNotFoundError。

只允许修改：
- rtl_obfuscator/symbol_graph.py
- tests/test_t069_sized_cast_parameter.py
- docs/development/future_work.md
- docs/tasks/T069_sized_cast_parameter_occurrence.md

四个 t069_sized_cast fixture 全部只读。不得修改其他代码、测试、fixture、CLI、
mapping/rewrite/restore/Formal脚本，不得运行RISC或blanket discovery。

严格先写合同第9节九项黑盒测试，再实现最小 typed CastExpressionSyntax +
最窄 semantic lexical scope lookupName 绑定。禁止全文搜索、按名字猜owner、
捕获异常后继续或在rewrite阶段补token。

完成后只运行第14节四条验收命令，记录实际 graph/mapping/strict compile/
restore/Formal正负结果，将状态设置为 READY_FOR_REVIEW 后停止。

不得设置 ACCEPTED、git add/commit/push、创建T070或写主Agent验收记录。
普通任务内失败应在允许范围内一次修完；只有合同第13节条件触发时才记录并停止。
```

## 19. 主 Agent 最终验收记录（2026-07-31）

```text
status: ACCEPTED
reviewed_head: 97c97a5b5e27c0d6dc71da3e6412778deb8782d5
scope: PASS; product and test changes are limited to symbol_graph.py, test_t069_sized_cast_parameter.py, and future_work.md; the T069 contract and frozen compact fixture are the only added task inputs
fixture_integrity: PASS; all four byte counts and SHA-256 values match section 3.2
acceptance_commands:
  - conda run -n rtl_obfuscation python -m unittest tests.test_symbol_graph_parameters tests.test_t069_sized_cast_parameter -v
  - conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/symbol_graph.py tests/test_t069_sized_cast_parameter.py
  - git diff --check HEAD
  - rg -x -- '- 状态：`READY_FOR_REVIEW`' docs/tasks/T069_sized_cast_parameter_occurrence.md
independent_results: unittest exit 0, Ran 28 tests in 0.826s, OK; py_compile exit 0; diff check exit 0; READY_FOR_REVIEW guard exit 0 before this acceptance update
graph_oracle: PASS; symbols/declarations/occurrences/total_ranges=20/20/37/57; five sized_cast_type occurrences use the frozen declaration identities and lexical shadow separation
mapping_oracle: PASS; total/rename/preserve/unsupported=20/9/11/0; parameter occurrences=16; modified_tokens=32
scope_review: PASS; same-buffer and enclosing-token checks precede semantic span validation
actual_gate: PASS; five sized-cast edits match their parameter MappingRecord symbol_id; catalog/top-overlay parse/semantic=0/0 + 0/0
restore: PASS; three physical files restore byte-identically and restored_manifest equals input_manifest
formal_positive_gate: /private/tmp/t069-formal-wbzjszi_/gate
formal_positive_result: {"formal_equivalence": "pass", "gate": "/private/tmp/t069-formal-wbzjszi_/gate", "gold": "/Users/lufengchi/Desktop/workspace/rtl_obfuscation/tests/fixtures/t069_sized_cast", "seq": 5, "top": "t069_sized_cast_top"}
formal_negative_gate: /private/tmp/t069-negative-5ol84t1s/negative
formal_negative_result: exit 1; unittest assertions confirmed unproven and equiv_status -assert
formal_verification: PASS; actual renamed gate used, not identity/copy-gold
boundaries: builtin keyword casts and all non-T069 special syntax retain their existing behavior; no RISC-V-Vector or blanket discovery command was run
decision: all frozen T069 requirements passed; ACCEPTED
delivery: ready for Main Agent commit and push; T070 was not created
```
