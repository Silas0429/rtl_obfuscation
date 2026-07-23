# T044：RewritePolicy category 与 ABI 选择

- 状态：`READY`
- 设计负责人：主 Agent
- 实现负责人：子 Agent
- 所属重构阶段：R3-A
- 前置任务：T043 `ACCEPTED`，交付提交 `6e80b18`
- 设计依据：`docs/three_mode_refactor_plan.md` 第 2、3、4、5、6、7 节
- 执行规范：`docs/refactor_subagent_protocol.md`
- 验收类型：SymbolGraph/range（纯 policy/report，不产生 rewritten RTL）
- Formal verification：`N/A`，本任务不生成名称、mapping 或 rewritten RTL

## 1. 当前项目位置与拆分决策

```text
SourceSet -> SourceCatalog -> SymbolGraph (R2 complete)
                                  |
                                  +-> T044 RewritePolicy selection
                                  +-> 后续 mapping vNext / naming
                                  +-> 后续 rewrite / gate / decrypt / metrics / Formal
```

T039–T043 已经把三种输入归一化为同一 SourceSet/Catalog/Graph，并冻结 `signals`、`parameters`、
`genvars` 的 source identity、provenance 与 `internal/module_abi/top_boundary`。R3 不能把 policy、mapping、
命名、文件编辑和 Formal 一次实现，否则任何数量差异都无法定位属于选择、命名还是改写。

T044 因此只实现可序列化 RewritePolicy：对每个现有 SourceSymbol给出 `rename/preserve/unsupported`
决定和稳定 reason。它不生成新名称，不产生 edits，不修改 RTL。

## 2. 单一目标

新增 `rtl_obfuscator/rewrite_policy.py`，只消费一个已经成功建立的 `SymbolGraph`，根据普通 category
选择与独立 ABI opt-in 生成一对一、确定、可审计的 policy decisions。

必须满足：

1. 全部决定只读取 SymbolGraph 字段，不遍历 AST/CST，不重新编译；
2. 普通 category 选择控制 `internal` 对象；
3. `module_abi` 即使 category 已选择，也必须额外出现在 `abi_categories` 才可 rename；
4. ABI opt-in 必须有 top，且当前只能是 `parameters`；
5. `top_boundary`、closure 外对象和无 top 的 module ABI 永远不能 rename；
6. 每个 graph symbol 恰好一个 decision，顺序与 SymbolGraph canonical 顺序相同；
7. graph 中 preserved/unsupported 原因优先于 policy 未选择原因，不得被覆盖。

## 3. 固定输入

不新增 fixture。只读复用 T043 已提交并冻结的：

```text
tests/fixtures/refactor_symbol_graph_parameters/design.f
tests/fixtures/refactor_symbol_graph_parameters/closure.f
tests/fixtures/refactor_symbol_graph_parameters/positional.f
tests/fixtures/refactor_symbol_graph_parameters/single.f
tests/fixtures/refactor_symbol_graph_parameters/single.sv
tests/fixtures/refactor_symbol_graph_parameters/rtl/*.sv
```

文件 hash 以 `docs/tasks/T043_symbol_graph_parameters.md` 第 3.3 节和提交 `22fee37` 为准。T044 不得
修改这些 fixture，也不新增 policy 专用 RTL。

T044 的 routine acceptance 只构造 single-file 与显式 filelist SourceSet。project-root policy adapter
和三入口端到端对等属于 R4；本任务的 policy 实现不得读取或按 `SourceSet.origin` 分支。

## 4. 主 Agent预检事实

T043 已验收 graph 的固定分类：

| input | graph symbols | internal eligible | module_abi eligible | graph-preserved module_abi/top_boundary |
| --- | ---: | ---: | ---: | ---: |
| full filelist，无 top | 20 | 13 | 0 | 7 |
| full filelist + `parameter_top` | 20 | 13 | 3 | 4 |
| closure filelist + `parameter_top` | 17 | 11 | 3 | 3 |
| single，无 top | 3 | 2 | 0 | 1 |
| positional + `positional_top` | 1 | 0 | 1 | 0 |

其中 full/top 的 graph-preserved 4 项为 selected top parameter 3项和 closure 外 parameter 1项。
这些是 T043 classification 的只读输入，不得在 policy 中重新计算 module closure或 semantic owner。

## 5. 固定公开 API

```python
@dataclass(frozen=True)
class RewriteDecision:
    symbol_id: str
    category: str
    action: str
    reason: str | None

@dataclass(frozen=True)
class RewritePolicy:
    schema_version: int
    symbol_graph: SymbolGraph
    selected_categories: tuple[str, ...]
    abi_categories: tuple[str, ...]
    decisions: tuple[RewriteDecision, ...]

    def to_report(self) -> dict[str, object]: ...

class RewritePolicyError(ValueError):
    code: str
    message: str

def build_rewrite_policy(
    symbol_graph: SymbolGraph,
    *,
    categories: Iterable[str],
    abi_categories: Iterable[str] = (),
) -> RewritePolicy: ...
```

`RewritePolicy.symbol_graph` 必须 `repr=False, compare=False`。不要求从 `rtl_obfuscator/__init__.py`
重导出。不得修改 SymbolGraph schema/version。

当前 policy canonical categories 固定为：

```text
signals, parameters, genvars
```

这是 R2 已验收 graph category 的新核心 registry，不得调用 legacy `category_profile.resolve()`，也不得
提前声明尚未进入 SymbolGraph 的其他 category。后续 category 由独立任务扩展。

## 6. 请求归一化与稳定错误

### 6.1 普通 category

- `categories` 必须是非字符串 iterable，至少包含一个 category；
- 重复项去重，输出永远按 `signals,parameters,genvars` canonical 顺序；
- 输入顺序不得影响 decisions/report；
- 未知 category 返回 `REWRITE_POLICY_UNKNOWN_CATEGORY`；
- 空选择返回 `REWRITE_POLICY_EMPTY_SELECTION`。

### 6.2 ABI opt-in

- `abi_categories` 同样去重并按 canonical 顺序；
- 当前唯一 ABI-capable category 是 `parameters`；
- ABI category 必须同时位于普通 `categories`；
- `signals`、`genvars` 或未选择的 `parameters` 作为 ABI category，返回
  `REWRITE_POLICY_INVALID_ABI_CATEGORY`；
- `abi_categories` 非空但 SourceSet没有 top，返回 `REWRITE_POLICY_TOP_REQUIRED`；
- 未知 ABI category先返回 `REWRITE_POLICY_UNKNOWN_CATEGORY`。

T044 不接受 `all`、alias、profile名称或 `None`；这些是后续 CLI adapter 的责任。

## 7. decision 规则与优先级

固定 action：`rename`、`preserve`、`unsupported`。

按以下顺序为每个 SourceSymbol产生一个 decision：

1. `support=unsupported`：action=`unsupported`，沿用 graph reason；
2. `support=preserved`：action=`preserve`，沿用 graph reason；
3. `support=eligible` 但 category未选择：action=`preserve`，reason=`category_not_selected`；
4. `support=eligible, abi=internal` 且 category已选择：action=`rename`，reason=null；
5. `support=eligible, abi=module_abi`、category已选择但没有 ABI opt-in：action=`preserve`，
   reason=`abi_not_selected`；
6. `support=eligible, abi=module_abi`、category和ABI均已选择：action=`rename`，reason=null；
7. `abi=top_boundary` 不能是 eligible；出现时返回 `REWRITE_POLICY_GRAPH_INVALID`。

graph validation：

- category、support、abi 必须属于上述已知集合；
- eligible 必须 `reason is None`；preserved/unsupported 必须有非空 reason；
- module_abi eligible 必须存在 top；
- action=rename 的对象只能是 graph eligible，且不能是 top_boundary；
- 任一违反返回 `REWRITE_POLICY_GRAPH_INVALID`，不产生部分 policy。

graph 原因优先于 policy 原因。例如 top parameter 即使 category未选择，仍保留
`selected_top_boundary`，不能改写为 `category_not_selected`。

## 8. 固定 report schema

`RewritePolicy.to_report()`：

```text
schema_version: 1
symbol_graph: <SymbolGraph.to_report()>
selected_categories: [canonical strings]
abi_categories: [canonical strings]
decisions:
  - symbol_id
    category
    action
    reason
summary:
  rename
  preserve
  unsupported
  total
```

decisions顺序与 `symbol_graph.symbols` 一致。每个 decision 的 `symbol_id/category` 必须等于对应
SourceSymbol；不复制 name、owner、ranges或classification，后续 mapping从同一个 SymbolGraph读取。
连续两次 canonical JSON序列化必须byte-identical。

## 9. 冻结正例 oracle

| input / request | rename | preserve | preserve reasons |
| --- | ---: | ---: | --- |
| full无top；全部3类；无ABI | 13 | 7 | `module_abi_requires_top=7` |
| full+top；全部3类；无ABI | 13 | 7 | `abi_not_selected=3, selected_top_boundary=3, outside_top_closure=1` |
| full+top；全部3类；ABI=`parameters` | 16 | 4 | `selected_top_boundary=3, outside_top_closure=1` |
| closure+top；全部3类；无ABI | 11 | 6 | `abi_not_selected=3, selected_top_boundary=3` |
| closure+top；全部3类；ABI=`parameters` | 14 | 3 | `selected_top_boundary=3` |
| single；`signals,parameters`；无ABI | 2 | 1 | `module_abi_requires_top=1` |
| positional+top；`parameters`；无ABI | 0 | 1 | `abi_not_selected=1` |
| positional+top；`parameters`；ABI=`parameters` | 1 | 0 | none |
| full+top；仅`signals` | 7 | 13 | `category_not_selected=9`，另有graph-preserved 4项 |

所有正例 `unsupported=0`，summary.total 等于 graph symbols。exact count 只验证 compact fixture，
不得进入产品分支。

## 10. 稳定负例矩阵

| request/graph | expected code |
| --- | --- |
| categories为空 | `REWRITE_POLICY_EMPTY_SELECTION` |
| categories含未知值、`all`或alias | `REWRITE_POLICY_UNKNOWN_CATEGORY` |
| ABI category未同时普通选择 | `REWRITE_POLICY_INVALID_ABI_CATEGORY` |
| ABI category为signals/genvars | `REWRITE_POLICY_INVALID_ABI_CATEGORY` |
| 无top请求ABI | `REWRITE_POLICY_TOP_REQUIRED` |
| graph中未知category/support/abi、eligible带reason、preserved无reason、eligible top_boundary或无topeligible module_abi | `REWRITE_POLICY_GRAPH_INVALID` |

异常字符串固定以 `'<code>: '` 开头。不修正、不跳过、不返回部分 decisions。

## 11. 目标测试（恰好 12 项）

新增 `tests/test_rewrite_policy.py`，只通过公开 API 覆盖：

1. full/no-top 13/7及7个no-top reason；
2. full/top无ABI 13/7及三类preserve reason；
3. full/top启用parameter ABI后16/4且top/outside仍保留；
4. closure/top无ABI与有ABI分别11/6、14/3；
5. single-file与single filelist normalized policy report除origin外相同且2/1；
6. positional override无ABI为0/1，启用parameter ABI为1/0；
7. 仅signals时7/13，并验证graph-preserved reason优先级；
8. category/ABI重复和输入顺序归一化为canonical顺序，连续JSON稳定；
9. decisions与graph一对一、同序、summary/schema/dataclass字段稳定，且不修改输入graph；
10. graph建立后monkeypatch T040 compile入口、legacy inventory/rewrite/category profile入口为立即失败，
    policy仍成功；
11. 第10节请求错误矩阵返回固定code；
12. 使用公开dataclass `replace()` 构造第10节malformed graph矩阵，全部fail-closed；并验证一个合法
    `support=unsupported` symbol产生unsupported decision并沿用graph reason。

测试不得调用 policy 私有 helper，不得修改 fixture，不得创建 fake semantic root。T041/T042/T043
46 tests 与 T044 12 tests 在同一命令运行，共58 tests。

## 12. 允许修改的文件

- `rtl_obfuscator/rewrite_policy.py`；
- `tests/test_rewrite_policy.py`；
- `docs/tasks/T044_rewrite_policy_selection.md`，仅状态和执行记录。

SymbolGraph、SourceSet、SourceCatalog、category_profile、legacy inventory/rewrite、fixture、README、重构
计划和其他任务均只读。需要修改允许列表外文件时记录原因并停止。

## 13. 明确不包含

- 不解析CLI category、`all`、alias或legacy profile；
- 不生成renamed name、随机值、mapping版本或mapping文件；
- 不生成或应用source edits，不写gate/restored RTL；
- 不实现encryption rate、effective-line、metrics、manifest、per-file mapping；
- 不运行strict gate、decrypt、HDL compile或Formal；
- 不接入project-root产品adapter，不测试RISC；
- 不新增category，不修改SymbolGraph classification；
- 不调用/复制legacy classification、inventory或rewrite policy。

## 14. 子 Agent强制执行规范

1. 完整阅读`AGENTS.md`、本任务、`docs/refactor_subagent_protocol.md`和重构计划第2–7节；
2. 确认`6e80b18`是HEAD祖先，T044合同已由主Agent提交，工作区干净，T044是唯一READY任务；
3. 校验T043 fixture hash并通过公开API复核第4节graph counts；fixture或graph不符时记录并停止；
4. 编辑实现前将状态改为`IN_PROGRESS`，填写starting HEAD、baseline和允许文件；
5. baseline只运行第15节unittest，预期既有46 tests通过，随后仅因
   `tests.test_rewrite_policy`不存在而import失败；
6. 先创建第11节12项测试，再实现请求归一化、graph validation、decision和report；
7. 普通测试失败属于任务内实现，不得分批暂停要求主Agent补充设计；
8. 只有冻结graph/API事实冲突、需要允许文件外修改或无法满足一对一fail-closed时才停止；
9. 完成后只运行第15节四条命令，一次填写结果并设`READY_FOR_REVIEW`；
10. 不得设置`ACCEPTED`、git add/commit/push、创建T045或写主Agent验收记录。

## 15. 唯一验收命令

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_symbol_graph_signals tests.test_symbol_graph_genvars tests.test_symbol_graph_parameters tests.test_rewrite_policy -v
conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/rewrite_policy.py tests/test_rewrite_policy.py
git diff --check HEAD
rg -x -- '- 状态：`READY_FOR_REVIEW`' docs/tasks/T044_rewrite_policy_selection.md
```

不运行blanket discovery、legacy tests、HDL compile、gate、decrypt、Yosys、RISC或历史acceptance。
Formal为`N/A: no rewritten RTL is produced`。主Agent只审查本合同12项行为并独立复跑以上命令。

## 16. 子 Agent执行记录

```text
status: NOT_STARTED
starting_head:
fixture_hash_check:
graph_preflight:
baseline_command:
baseline_result:
changed_files:
commands:
results:
schema_or_behavior:
deviations_or_blockers:
boundaries:
cleanup_candidates:
formal_verification: N/A - no rewritten RTL is produced
review_request:
```

## 17. READY_FOR_REVIEW条件

- 第11节12项行为全部覆盖，四模块共58 tests通过；
- 第15节四条命令全部退出0；
- diff只包含第12节三个允许文件，T043 fixture hash不变；
- category与ABI selection分离，top/closure/no-top边界符合第7–9节；
- 每个symbol恰好一个同序decision，stable reasons和summary正确；
- 请求与malformed graph负例全部fail-closed；
- 没有recompile、legacy调用、mapping、命名、rewrite或模式分支；
- Formal准确记录N/A，状态严格为`READY_FOR_REVIEW`。

## 18. 主 Agent验收边界

主 Agent只执行：

1. 审查starting HEAD、允许文件和fixture hash；
2. 审查12项测试使用公开API和真实T043 graph；
3. 审查category/ABI分离、reason优先级和一对一decision；
4. 确认policy没有AST/CST、compile、inventory、rewrite或origin分支；
5. 在状态仍为`READY_FOR_REVIEW`时独立运行第15节四条命令；
6. 全部通过后写验收记录并设置`ACCEPTED`。

退回必须引用本合同具体条款或测试项；不得在验收时追加mapping、CLI或新category要求。

## 19. 主 Agent合同冻结记录（2026-07-23）

```text
status: READY
baseline_commit: 6e80b18
decision: isolate pure RewritePolicy before mapping vNext, naming and source rewrite
inputs: reuse committed T043 compact fixtures; no new RTL
positive_oracles: full/no-top 13/7; full/top 13/7 or 16/4; closure/top 11/6 or 14/3; single 2/1; positional 0/1 or 1/0
negative_matrix: empty/unknown selection, invalid ABI category, ABI without top, malformed graph
acceptance: exactly four commands; 58 tests; no Formal or hidden probe
formal_verification: N/A - no rewritten RTL is produced
```
