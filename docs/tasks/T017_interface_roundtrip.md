# T017：多文件 interface 定义名端到端重命名

- 状态：`ACCEPTED`
- 设计负责人：主 Agent
- 实现负责人：子 Agent
- 前置任务：T016 已达到 `ACCEPTED`

## 1. 单一目标

在多文件 Compilation 下增加一个 ABI category：

1. `interfaces`：interface 定义名及其所有 type 引用（instance type 和 InterfacePort header）。

`interfaces` 不属于 `--category all` 的安全集合，必须显式指定。`interface_instances`、`interface_ports`、`modports`、`modport_ports` 不属于本任务。

## 2. 固定输入与输出

```text
filelist    = tests/fixtures/t017_interface/design.f
source_root = tests/fixtures/t017_interface
top         = t017_top
category    = interfaces
name_length = 8
```

filelist 内容：

```text
bus_if.sv
child.sv
top.sv
```

固定输出目录：

```text
/tmp/rtl_obfuscation_t017/gate/bus_if.sv
/tmp/rtl_obfuscation_t017/gate/child.sv
/tmp/rtl_obfuscation_t017/gate/top.sv
/tmp/rtl_obfuscation_t017/gate/design.f
/tmp/rtl_obfuscation_t017/mapping.json
/tmp/rtl_obfuscation_t017/metrics.json
```

## 3. 固定 CLI

### 3.1 正向改写

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite encrypt-project \
  --filelist tests/fixtures/t017_interface/design.f \
  --source-root tests/fixtures/t017_interface \
  --output-dir /tmp/rtl_obfuscation_t017/gate \
  --map /tmp/rtl_obfuscation_t017/mapping.json \
  --metrics /tmp/rtl_obfuscation_t017/metrics.json \
  --top t017_top \
  --category interfaces \
  --name-length 8
```

### 3.2 反向恢复

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite decrypt-project \
  --gate-dir /tmp/rtl_obfuscation_t017/gate \
  --source-root tests/fixtures/t017_interface \
  --map /tmp/rtl_obfuscation_t017/mapping.json \
  --output-dir /tmp/rtl_obfuscation_t017/restored
```

### 3.3 多文件 formal

```sh
conda run -n rtl_obfuscation python scripts/formal_equivalence.py \
  --gold-filelist tests/fixtures/t017_interface/design.f \
  --gold-root tests/fixtures/t017_interface \
  --gate-filelist design.f \
  --gate-root /tmp/rtl_obfuscation_t017/gate \
  --top t017_top
```

## 4. 精确 mapping 预期

mapping v2，1 个 entry：

```text
entry 0:
  category    = interfaces
  scope       = t017_bus_if
  original    = t017_bus_if
  declaration = {file: "bus_if.sv", start: 10, end: 21}
  references  = [
    {file: "child.sv", start: 24, end: 35},
    {file: "top.sv", start: 138, end: 149}
  ]
  tokens      = 3
```

汇总：files=3, entries=1, tokens=3。

## 5. 精确 metrics 预期

硬约束：

- symbols: renamed=1, eligible=1, coverage=1.0
- occurrences: renamed=3, eligible=3, coverage=1.0
- plaintext_leakage_rate: 0.0
- effective_coverage: 1.0

affected_lines 具体值由现有 `_metrics` 函数实际输出，子 Agent 记录实际值。

## 6. 实现要求

### 6.1 interfaces collector

在 `rtl_obfuscator/inventory.py` 中新增 `_collect_interfaces` 函数：

- 遍历 AST，收集所有 `SymbolKind.Instance` 符号。
- 对每个 instance，取 `instance.definition`。
- 只收集 `definition.definitionKind == DefinitionKind.Interface` 的符号。
- 使用 `definition.location` 作为 declaration。
- reference 收集有两种来源：
  1. **Instance type reference**：`instance.syntax.parent.type`（Token）的 `location`。出现在实例化 interface 的文件中（如 top.sv 中的 `t017_bus_if u_bus (...)`）。
  2. **InterfacePort header**：遍历所有 `SymbolKind.InterfacePort` 符号，取 `port.syntax.parent.header` 的 `sourceRange`。出现在 module 中声明 interface-typed port 的文件中（如 child.sv 中的 `t017_bus_if bus_inst`）。
- 去重：同一个 interface definition 只产生一个 entry，所有 type 引用合并为 references。
- 使用 `_symbol_sort_key` 去重和排序。

### 6.2 注册到流水线

- 在 `_collect_targets` 中增加 `interfaces` 分支。
- 在 `_SUPPORTED_CATEGORIES` 中增加 `"interfaces"`。
- 在 `encrypt-project` 的 `--category` choices 中增加 `"interfaces"`。
- `interfaces` 不加入 `all` 的展开集合。
- 在 mapping v2 validator 中增加 `"interfaces"` 到合法 category 列表。
- 不修改现有单文件 CLI 或 mapping v1。

### 6.3 scope

scope 使用 interface definition 名（如 `t017_bus_if`）。

## 7. 黑盒验收点

- `encrypt-project` stdout 为 `{"files": 3, "mapping_entries": 1, "modified_tokens": 3}`。
- mapping v2 的 1 个 entry 的 declaration 和 reference ranges 精确匹配第 4 节。
- gate 目录中 `bus_if.sv` 的 `t017_bus_if` 被替换；`child.sv` 的 `t017_bus_if`（InterfacePort header）被替换；`top.sv` 的 `t017_bus_if`（instance type）被替换。
- `decrypt-project` 后三个文件与 gold 逐文件 `cmp -s` 退出码为 `0`。
- metrics 的 symbols/occurrences/leakage/effective_coverage 精确匹配第 5 节硬约束。
- 多文件 PySlang Compilation 无 error。
- Verible 对三个 gate 文件退出码为 `0`。
- Icarus 对 gold 和 gate 均不支持 ANSI-style interface port（已知限制，退出码非 0 是预期行为，不阻塞验收）。
- 多文件 Yosys formal equivalence 退出码为 `0`，JSON `formal_equivalence=pass`。
- 现有 21 项 unittest 全部通过。
- `git diff --check` 退出码为 `0`。

## 8. Formal verification

```text
formal_verification: PASS (子 Agent 自测) / PASS (主 Agent 独立重跑)
gold: tests/fixtures/t017_interface/design.f (bus_if.sv, child.sv, top.sv)
gate: /tmp/rtl_obfuscation_t017/gate/design.f (bus_if.sv, child.sv, top.sv)
top: t017_top
command: conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold-filelist tests/fixtures/t017_interface/design.f --gold-root tests/fixtures/t017_interface --gate-filelist design.f --gate-root /tmp/rtl_obfuscation_t017/gate --top t017_top
exit_code: 0
result: {"formal_equivalence": "pass", "gate": "/tmp/rtl_obfuscation_t017/gate", "gold": "tests/fixtures/t017_interface", "seq": 5, "top": "t017_top"}
```

## 9. 本任务明确不包含

- `interface_instances`（interface instance 名的引用收集）。
- `interface_ports`、`modports`、`modport_ports`。
- `type_parameters`（T006 保持 `DRAFT`）。
- virtual interface、clocking block、DPI、bind。
- 修改现有单文件 CLI 或 mapping v1。
- 修改 formal 脚本。

## 10. 允许修改的文件

```text
rtl_obfuscator/inventory.py
rtl_obfuscator/rewrite.py
tests/test_interface_rewrite.py
docs/tasks/T017_interface_roundtrip.md
```

`tests/fixtures/t017_interface/` 是主 Agent 已冻结的只读输入。不得修改其他文件。

## 11. 子 Agent 文档流程

1. 开始前将状态从 `READY` 改为 `IN_PROGRESS` 并记录开始时间。
2. 若 PySlang API 与第 6 节描述不一致，记录最小复现并停止。
3. 完成后记录变更文件、所有命令、stdout/stderr、退出码和未覆盖边界。
4. Formal 必须按第 8 节格式记录结果。
5. 全部门禁通过后设置为 `READY_FOR_REVIEW`；不得设置 `ACCEPTED`，不得 commit 或 push。

## 12. 执行记录（子 Agent 更新）

- 2026-07-14 13:00 CST：已完整阅读 AGENTS.md、docs/tasks/README.md、docs/formal_verification.md 和 T017 合同；确认 T016 已 ACCEPTED、T017 是唯一 READY 任务。已用 PySlang API 探针确认：Instance.definition 返回 interface definition（DefinitionKind.Interface），definition.location.offset=10 与合同匹配；instance.syntax.parent.type 的 location.offset=138 与合同匹配；InterfacePort 的 syntax.parent.header.sourceRange [24,35) 与合同匹配。API 与合同第 6 节一致，无偏差。开始实现 interfaces category。
- 2026-07-14 13:15 CST：完成实现：在 inventory.py 新增 `_collect_interfaces`（收集 DefinitionKind.Interface 的 definition，通过 instance.syntax.parent.type 收集 instance type 引用，通过 InterfacePort.syntax.parent.header.sourceRange 收集 interface port header 引用）和 `_interface_reference_tokens`；在 `_collect_targets`、`_SUPPORTED_CATEGORIES`、`_build_project_inventory`、`_add_project_ranges` 中注册 interfaces；在 rewrite.py 的 encrypt-project choices 和 _gate_project_ranges 中增加 interfaces。新增 1 个黑盒测试。
- 2026-07-14 13:25 CST：完成 22 项回归、四组固定 CLI、前端检查和多文件 Yosys formal；全部通过。无偏差。设置为 READY_FOR_REVIEW。

## 13. 偏差或阻塞（子 Agent 更新）

- 无。

## 14. 交付证据（子 Agent 更新）

- 变更文件：`rtl_obfuscator/inventory.py`、`rtl_obfuscator/rewrite.py`、`tests/test_interface_rewrite.py`、`docs/tasks/T017_interface_roundtrip.md`。`git diff --check` 退出码 `0`；fixtures 无 diff；未 commit、未 push。
- 22 项回归命令：`conda run -n rtl_obfuscation python -m unittest discover -s tests -v`。退出码 `0`；实际输出：`Ran 22 tests in 3.740s`、`OK`。
- encrypt-project stdout：`{"files": 3, "mapping_entries": 1, "modified_tokens": 3}`，退出码 `0`。
- decrypt-project stdout：`{"files": 3, "mapping_entries": 1, "modified_tokens": 3}`，退出码 `0`。
- 三组 `cmp -s` gold/restored 退出码均为 `0`（bus_if.sv、child.sv、top.sv）。
- 实际 mapping v2：`version=2, name_length=8, files=["bus_if.sv","child.sv","top.sv"], top="t017_top"`。1 个 entry 的 declaration 和 references 与合同第 4 节精确匹配（t017_bus_if declaration=[10,21)、references=[[24,35),[138,149)]）。
- 实际 metrics：`symbols={renamed:1,eligible:1,coverage:1.0}, occurrences={renamed:3,eligible:3,coverage:1.0}, plaintext_leakage_rate=0.0, effective_coverage=1.0`。全部满足合同第 5 节硬约束。
- 前端检查：PySlang 多文件 Compilation 退出码 `0`；Verible 对 bus_if.sv、child.sv、top.sv 各退出码 `0`。
- 多文件 formal：见第 8 节，`formal_equivalence=pass`、`seq=5`。

## 15. 主 Agent 验收结果

- 2026-07-14 CST：主 Agent 独立重跑全部验收命令，全部通过。
- encrypt-project stdout：`{"files": 3, "mapping_entries": 1, "modified_tokens": 3}`，精确匹配合同第 7 节。
- mapping v2：1 个 entry，declaration [10,21)、references [[24,35),[138,149)]，精确匹配合同第 4 节。
- metrics：symbols coverage=1.0、occurrences coverage=1.0、plaintext_leakage_rate=0.0、effective_coverage=1.0，全部满足合同第 5 节硬约束。affected_lines: changed=3, total=30。
- decrypt-project：三个文件 cmp -s 退出码均为 0。
- PySlang 多文件 Compilation：no errors。
- Verible：三个 gate 文件退出码均为 0。
- 多文件 Yosys formal：`{"formal_equivalence": "pass", "seq": 5, "top": "t017_top"}`，退出码 0。
- 22 项 unittest 全部通过。
- git diff --check 退出码 0。
- 无偏差。验收通过。
