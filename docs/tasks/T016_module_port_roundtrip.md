# T016：多文件非 top modules 与 child ports 端到端重命名

- 状态：`ACCEPTED`
- 设计负责人：主 Agent
- 实现负责人：子 Agent
- 前置任务：T015 已达到 `ACCEPTED`

## 1. 单一目标

在多文件 Compilation 下增加两个 ABI category：

1. `modules`：非 top module 定义名及其所有 instance type 引用。
2. `ports`：非 top child module 的 port 声明及其所有 named connection 左侧 `.port_name(...)`。

两个 category 只通过 `encrypt-project` / `decrypt-project` CLI 使用，不加入单文件 CLI。`modules` 和 `ports` 不属于 `--category all` 的安全集合，必须显式指定。

## 2. 固定输入与输出

```text
filelist    = tests/fixtures/t016_module_port/design.f
source_root = tests/fixtures/t016_module_port
top         = t016_top
categories  = modules ports
name_length = 8
```

filelist 内容：

```text
child.sv
top.sv
```

固定输出目录：

```text
/tmp/rtl_obfuscation_t016/gate/child.sv
/tmp/rtl_obfuscation_t016/gate/top.sv
/tmp/rtl_obfuscation_t016/gate/design.f
/tmp/rtl_obfuscation_t016/mapping.json
/tmp/rtl_obfuscation_t016/metrics.json
```

## 3. 固定 CLI

### 3.1 正向改写

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite encrypt-project \
  --filelist tests/fixtures/t016_module_port/design.f \
  --source-root tests/fixtures/t016_module_port \
  --output-dir /tmp/rtl_obfuscation_t016/gate \
  --map /tmp/rtl_obfuscation_t016/mapping.json \
  --metrics /tmp/rtl_obfuscation_t016/metrics.json \
  --top t016_top \
  --category modules \
  --category ports \
  --name-length 8
```

### 3.2 反向恢复

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite decrypt-project \
  --gate-dir /tmp/rtl_obfuscation_t016/gate \
  --source-root tests/fixtures/t016_module_port \
  --map /tmp/rtl_obfuscation_t016/mapping.json \
  --output-dir /tmp/rtl_obfuscation_t016/restored
```

### 3.3 多文件 formal

```sh
conda run -n rtl_obfuscation python scripts/formal_equivalence.py \
  --gold-filelist tests/fixtures/t016_module_port/design.f \
  --gold-root tests/fixtures/t016_module_port \
  --gate-filelist design.f \
  --gate-root /tmp/rtl_obfuscation_t016/gate \
  --top t016_top
```

## 4. 精确 mapping 预期

mapping v2，3 个 entry，按 `(declaration.file, declaration.start, category)` 排序：

```text
entry 0:
  category    = modules
  scope       = t016_child
  original    = t016_child
  declaration = {file: "child.sv", start: 7, end: 17}
  references  = [{file: "top.sv", start: 89, end: 99}]
  tokens      = 2

entry 1:
  category    = ports
  scope       = t016_child
  original    = data_in
  declaration = {file: "child.sv", start: 43, end: 50}
  references  = [{file: "top.sv", start: 119, end: 126}]
  tokens      = 2

entry 2:
  category    = ports
  scope       = t016_child
  original    = data_out
  declaration = {file: "child.sv", start: 75, end: 83}
  references  = [{file: "top.sv", start: 146, end: 154}]
  tokens      = 2
```

汇总：files=2, entries=3, tokens=6。

## 5. 精确 metrics 预期

硬约束：

- symbols: renamed=3, eligible=3, coverage=1.0
- occurrences: renamed=6, eligible=6, coverage=1.0
- plaintext_leakage_rate: 0.0
- effective_coverage: 1.0

affected_lines 具体值由现有 `_metrics` 函数实际输出，子 Agent 记录实际值。

## 6. 实现要求

### 6.1 modules collector

在 `rtl_obfuscator/inventory.py` 中新增 `_collect_modules` 函数：

- 遍历 AST，收集所有 `SymbolKind.Instance` 符号。
- 对每个 instance，取 `instance.definition`。
- 排除 `definition.name == top` 的 module（top 保留）。
- 排除 `definition.definitionKind != DefinitionKind.Module`。
- 使用 instance 的 `definition.location` 作为 declaration。
- 使用 `instance.syntax.parent.type`（Token）的 `location` 作为 reference。
- 去重：同一个 module definition 只产生一个 entry，所有 instance type 引用合并为 references。
- 使用 `_symbol_sort_key` 去重和排序。

### 6.2 ports collector

新增 `_collect_ports` 函数：

- 遍历 AST，收集所有 `SymbolKind.Port` 符号。
- 排除 `port.declaringDefinition.name == top` 的 port（top ports 保留）。
- 只收集 `port.declaringDefinition.definitionKind == DefinitionKind.Module` 的 port。
- 使用 `port.location` 作为 declaration。
- reference 收集：遍历所有 `SymbolKind.Instance` 符号的 `syntax.connections`，对每个 `NamedPortConnectionSyntax`，取 `conn.name`（Token）的 `location` 作为 reference。
- 校验 reference 的 port name 与 declaration 的 port name 匹配（通过 instance 的 definition 绑定）。
- positional connection 不产生 port edit。

### 6.3 注册到流水线

- 在 `_collect_targets` 中增加 `modules` 和 `ports` 分支。
- 在 `_SUPPORTED_CATEGORIES` 中增加 `"modules"` 和 `"ports"`。
- 在 `encrypt-project` 的 `--category` choices 中增加 `"modules"` 和 `"ports"`。
- `modules` 和 `ports` 不加入 `all` 的展开集合。
- 在 `decrypt-project` 的 mapping v2 validator 中增加 `"modules"` 和 `"ports"` 到合法 category 列表。
- 不修改现有单文件 CLI 或 mapping v1。

### 6.4 scope

- `modules` 的 scope 使用 module definition 名（如 `t016_child`）。
- `ports` 的 scope 使用 port 所属的 module definition 名（如 `t016_child`）。

## 7. 黑盒验收点

- `encrypt-project` stdout 为 `{"files": 2, "mapping_entries": 3, "modified_tokens": 6}`。
- mapping v2 的 3 个 entry 的 declaration 和 reference ranges 精确匹配第 4 节。
- gate 目录中 `child.sv` 的 `t016_child`、`data_in`、`data_out` 被替换；`top.sv` 的 `t016_child`（instance type）、`.data_in`、`.data_out`（connection 左侧）被替换。
- top module 名 `t016_top` 和 top ports `data_in`、`data_out`（在 top.sv 中）未被替换。
- `decrypt-project` 后 `restored/child.sv` 和 `restored/top.sv` 与 gold 逐文件 `cmp -s` 退出码为 `0`。
- metrics 的 symbols/occurrences/leakage/effective_coverage 精确匹配第 5 节硬约束。
- 多文件 PySlang Compilation 无 error。
- Verible 对两个 gate 文件退出码为 `0`。
- Icarus `iverilog -g2012 -t null -s t016_top` 退出码为 `0`。
- 多文件 Yosys formal equivalence 退出码为 `0`，JSON `formal_equivalence=pass`。
- 现有 20 项 unittest 全部通过。
- `git diff --check` 退出码为 `0`。

## 8. Formal verification

```text
formal_verification: PASS (子 Agent 自测) / PASS (主 Agent 独立重跑)
gold: tests/fixtures/t016_module_port/design.f (child.sv, top.sv)
gate: /tmp/rtl_obfuscation_t016/gate/design.f (child.sv, top.sv)
top: t016_top
command: conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold-filelist tests/fixtures/t016_module_port/design.f --gold-root tests/fixtures/t016_module_port --gate-filelist design.f --gate-root /tmp/rtl_obfuscation_t016/gate --top t016_top
exit_code: 0
result: {"formal_equivalence": "pass", "gate": "/tmp/rtl_obfuscation_t016/gate", "gold": "tests/fixtures/t016_module_port", "seq": 5, "top": "t016_top"}
```

## 9. 本任务明确不包含

- top module 或 top port 重命名。
- `interfaces`、`interface_instances`、`interface_ports`、`modports`、`modport_ports`。
- `type_parameters`（T006 保持 `DRAFT`）。
- positional connection、`.*`、parameter port 列表。
- bind、config、defparam、hierarchical reference。
- 修改现有单文件 CLI 或 mapping v1。
- 修改 formal 脚本。

## 10. 允许修改的文件

```text
rtl_obfuscator/inventory.py
rtl_obfuscator/rewrite.py
tests/test_module_port_rewrite.py
docs/tasks/T016_module_port_roundtrip.md
```

`tests/fixtures/t016_module_port/` 是主 Agent 已冻结的只读输入。不得修改其他文件。

## 11. 子 Agent 文档流程

1. 开始前将状态从 `READY` 改为 `IN_PROGRESS` 并记录开始时间。
2. 若 PySlang API 与第 6 节描述不一致，记录最小复现并停止。
3. 完成后记录变更文件、所有命令、stdout/stderr、退出码和未覆盖边界。
4. Formal 必须按第 8 节格式记录结果。
5. 全部门禁通过后设置为 `READY_FOR_REVIEW`；不得设置 `ACCEPTED`，不得 commit 或 push。

## 12. 执行记录（子 Agent 更新）

- 2026-07-14 12:00 CST：已完整阅读 AGENTS.md、docs/tasks/README.md、docs/formal_verification.md 和 T016 合同；确认 T015 已 ACCEPTED、T016 是唯一 READY 任务。已用 PySlang API 探针确认：Instance.definition 返回 module definition，definition.location.offset 是 module 名声明位置；instance.syntax.parent.type 是 instance type 引用 token；instance.syntax.connections 返回 NamedPortConnectionSyntax 列表，每个有 name token。所有 offset 与合同第 4 节精确匹配。开始实现 modules 和 ports 两个 category。
- 2026-07-14 12:15 CST：完成实现：在 inventory.py 新增 `_collect_modules`（收集非 top module definition，通过 instance.definition 绑定，通过 instance.syntax.parent.type 收集引用）和 `_collect_ports`（收集非 top port，通过 port.internalSymbol 收集 body 内 NamedValue 引用，通过 instance.syntax.connections 收集 named connection 引用）；新增 `_module_port_reference_tokens`；在 `_build_project_inventory` 中支持多 category 列表和 top 参数；在 rewrite.py 中 `encrypt-project` 支持 `--category` 多次指定和 `--top`，`decrypt-project` 从 mapping v2 读取 top；在 mapping v2 中增加 `top` 字段。新增 1 个黑盒测试。
- 2026-07-14 12:30 CST：完成 21 项回归、四组固定 CLI、前端检查和多文件 Yosys formal；全部通过。发现 mapping references 和 modified_tokens 偏差（见第 13 节）。设置为 READY_FOR_REVIEW。

## 13. 偏差或阻塞（子 Agent 更新）

- mapping references 和 modified_tokens 偏差：合同第 4 节预期 `data_in` references 只有 top.sv 中的 named connection（tokens=2），`data_out` 同理。但 port 在 child.sv body 内的使用（如 `assign internal_wire = data_in;`）也必须被重命名，否则 gate 中 port 声明被重命名但 body 内引用未重命名会导致 PySlang error。实际通过 `port.internalSymbol`（Variable 符号）收集 body 内 NamedValue 引用，`data_in` 有 2 个 references（child.sv body + top.sv named connection），`data_out` 同理。汇总 tokens=8 而非合同预期的 6。declaration offsets 与合同精确匹配。测试中使用实际输出值。
- mapping v2 schema 增加 `top` 字段：合同第 4 节的 mapping v2 schema 不包含 `top`，但 decrypt-project 需要知道 top module 名才能正确排除 top module。在 mapping v2 中增加 `top` 字段存储 top module 名。

## 14. 交付证据（子 Agent 更新）

- 变更文件：`rtl_obfuscator/inventory.py`、`rtl_obfuscator/rewrite.py`、`tests/test_module_port_rewrite.py`、`docs/tasks/T016_module_port_roundtrip.md`。`git diff --check` 退出码 `0`；fixtures 无 diff；未 commit、未 push。
- 21 项回归命令：`conda run -n rtl_obfuscation python -m unittest discover -s tests -v`。退出码 `0`；实际输出：`Ran 21 tests in 3.667s`、`OK`。
- encrypt-project stdout：`{"files": 2, "mapping_entries": 3, "modified_tokens": 8}`，退出码 `0`。
- decrypt-project stdout：`{"files": 2, "mapping_entries": 3, "modified_tokens": 8}`，退出码 `0`。
- 两组 `cmp -s` gold/restored 退出码均为 `0`（child.sv 和 top.sv）。
- 实际 mapping v2：`version=2, name_length=8, files=["child.sv","top.sv"], top="t016_top"`。3 个 entry 的 declaration 与合同第 4 节精确匹配（t016_child [7,17)、data_in [43,50)、data_out [75,83)）。references 包含 body 内引用（偏差见第 13 节），全部经过 source_bytes 验证正确。
- 实际 metrics：`symbols={renamed:3,eligible:3,coverage:1.0}, occurrences={renamed:8,eligible:8,coverage:1.0}, plaintext_leakage_rate=0.0, effective_coverage=1.0`。symbols/leakage/effective_coverage 满足合同第 5 节硬约束（occurrences 实际为 8 而非 6，与 mapping 偏差一致）。
- 前端检查：PySlang 多文件 Compilation 退出码 `0`；Verible 对 child.sv 和 top.sv 各退出码 `0`；Icarus `iverilog -g2012 -t null -s t016_top child.sv top.sv` 退出码 `0`。
- 多文件 formal：见第 8 节，`formal_equivalence=pass`、`seq=5`。

## 15. 主 Agent 验收结果

- 2026-07-14 主 Agent 独立验收通过，状态设为 `ACCEPTED`。
- 21 项回归全部通过。
- encrypt-project stdout 为 3 entries / 8 tokens（合同预期 6 tokens 有误，遗漏了 port body 内引用）。
- mapping v2 schema 正确（含 top 字段），declaration offsets 精确匹配，references 包含 child.sv body 内引用和 top.sv named connection。
- metrics 硬约束全部满足：symbols=3/3, occurrences=8/8, leakage=0.0, effective=1.0。
- decrypt-project 后 child.sv 和 top.sv 与 gold 逐文件 cmp 退出码 0。
- 多文件 PySlang、Verible、Icarus 全部退出码 0。
- 主 Agent 独立重跑多文件 Yosys formal，退出码 0、formal_equivalence=pass。
- git diff --check 退出码 0。
