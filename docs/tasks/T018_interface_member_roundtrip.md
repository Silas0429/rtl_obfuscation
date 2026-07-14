# T018：多文件 interface instance、member 和 modport 端到端重命名

- 状态：`READY`
- 设计负责人：主 Agent
- 实现负责人：子 Agent
- 前置任务：T017 已达到 `ACCEPTED`

## 1. 单一目标

在多文件 Compilation 下增加三个 ABI category：

1. `interface_instances`：interface instance 名（如 `u_bus`）的声明和所有引用。
2. `interface_ports`：interface 内部 member（如 `data`、`valid`、`ready`）的声明、member access 引用和 modport port 引用。
3. `modports`：modport 名（如 `master`、`slave`）的声明。

三个 category 不属于 `--category all` 的安全集合，必须显式指定。`modport_ports` 不生成独立 entry——modport port 的 location 作为对应 `interface_ports` entry 的 reference。

## 2. 固定输入与输出

```text
filelist    = tests/fixtures/t018_interface_member/design.f
source_root = tests/fixtures/t018_interface_member
top         = t018_top
categories  = interface_instances interface_ports modports
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
/tmp/rtl_obfuscation_t018/gate/bus_if.sv
/tmp/rtl_obfuscation_t018/gate/child.sv
/tmp/rtl_obfuscation_t018/gate/top.sv
/tmp/rtl_obfuscation_t018/gate/design.f
/tmp/rtl_obfuscation_t018/mapping.json
/tmp/rtl_obfuscation_t018/metrics.json
```

## 3. 固定 CLI

### 3.1 正向改写

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite encrypt-project \
  --filelist tests/fixtures/t018_interface_member/design.f \
  --source-root tests/fixtures/t018_interface_member \
  --output-dir /tmp/rtl_obfuscation_t018/gate \
  --map /tmp/rtl_obfuscation_t018/mapping.json \
  --metrics /tmp/rtl_obfuscation_t018/metrics.json \
  --top t018_top \
  --category interface_instances \
  --category interface_ports \
  --category modports \
  --name-length 8
```

### 3.2 反向恢复

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite decrypt-project \
  --gate-dir /tmp/rtl_obfuscation_t018/gate \
  --source-root tests/fixtures/t018_interface_member \
  --map /tmp/rtl_obfuscation_t018/mapping.json \
  --output-dir /tmp/rtl_obfuscation_t018/restored
```

### 3.3 多文件 formal

```sh
conda run -n rtl_obfuscation python scripts/formal_equivalence.py \
  --gold-filelist tests/fixtures/t018_interface_member/design.f \
  --gold-root tests/fixtures/t018_interface_member \
  --gate-filelist design.f \
  --gate-root /tmp/rtl_obfuscation_t018/gate \
  --top t018_top
```

## 4. 精确 mapping 预期

mapping v2，10 个 entry，按 `(declaration.file, declaration.start, category)` 排序：

### 4.1 interface_instances

```text
entry:
  category    = interface_instances
  scope       = t018_top
  original    = u_bus
  declaration = {file: "top.sv", start: 150, end: 155}
  references  = [{file: "top.sv", start: 250, end: 255}, {file: "top.sv", start: 287, end: 292}, {file: "top.sv", start: 322, end: 327}]
  tokens      = 4
```

### 4.2 interface_ports

5 个 entry（clk, rst_n, data, valid, ready），每个的 declaration 在 bus_if.sv：

```text
entry: category=interface_ports, scope=t018_bus_if, original=clk,    declaration={file:"bus_if.sv",start:41,end:44},  references=[]
entry: category=interface_ports, scope=t018_bus_if, original=rst_n,  declaration={file:"bus_if.sv",start:63,end:68},  references=[]
entry: category=interface_ports, scope=t018_bus_if, original=data,   declaration={file:"bus_if.sv",start:88,end:92},  references=[{file:"bus_if.sv",start:179,end:183},{file:"bus_if.sv",start:271,end:275},{file:"child.sv",start:102,end:106},{file:"top.sv",start:293,end:297}]
entry: category=interface_ports, scope=t018_bus_if, original=valid,  declaration={file:"bus_if.sv",start:111,end:116}, references=[{file:"bus_if.sv",start:200,end:205},{file:"bus_if.sv",start:292,end:297},{file:"child.sv",start:68,end:73},{file:"top.sv",start:328,end:333}]
entry: category=interface_ports, scope=t018_bus_if, original=ready,  declaration={file:"bus_if.sv",start:135,end:140}, references=[{file:"bus_if.sv",start:222,end:227},{file:"bus_if.sv",start:314,end:319}]
```

tokens: clk=1, rst_n=1, data=5, valid=5, ready=3 → total=15

### 4.3 modports

2 个 entry：

```text
entry: category=modports, scope=t018_bus_if, original=master, declaration={file:"bus_if.sv",start:155,end:161}, references=[]
entry: category=modports, scope=t018_bus_if, original=slave,  declaration={file:"bus_if.sv",start:248,end:253}, references=[]
```

tokens: master=1, slave=1 → total=2

### 4.4 汇总

files=3, entries=8, tokens=21

## 5. 精确 metrics 预期

硬约束：

- symbols: renamed=8, eligible=8, coverage=1.0
- occurrences: renamed=21, eligible=21, coverage=1.0
- plaintext_leakage_rate: 0.0
- effective_coverage: 1.0

affected_lines 具体值由现有 `_metrics` 函数实际输出，子 Agent 记录实际值。

## 6. 实现要求

### 6.1 interface_instances collector

新增 `_collect_interface_instances` 函数：

- 遍历 AST，收集所有 `SymbolKind.Instance` 符号。
- 只收集 `instance.definition.definitionKind == DefinitionKind.Interface` 的符号。
- 使用 `instance.location` 作为 declaration。
- reference 收集有两种来源：
  1. **ArbitrarySymbolExpression**：遍历所有节点，检查 `type(node).__name__ == "ArbitrarySymbolExpression"`，`node.symbol` 是 `InstanceSymbol` 且 `name` 匹配。取 `node.sourceRange`。
  2. **HierarchicalValueExpression**：遍历所有节点，检查 `type(node).__name__ == "HierarchicalValueExpression"`，`node.syntax` 是 `ScopedNameSyntax`，`syntax.left.sourceRange` 的字节等于 instance name。取 `syntax.left.sourceRange`。
- 去重：同一个 instance 只产生一个 entry。
- scope 使用 instance 所在的 module definition 名。

### 6.2 interface_ports collector

新增 `_collect_interface_ports` 函数：

- 遍历 AST，收集所有 `SymbolKind.Instance` 符号。
- 只收集 `instance.definition.definitionKind == DefinitionKind.Interface` 的符号。
- 对每个 interface instance，取 `instance.body`，遍历其子符号收集 `SymbolKind.Variable` 符号。
- 只收集 `declaringDefinition.name` 等于 interface definition 名的 Variable。
- 使用 `variable.location` 作为 declaration。
- reference 收集有三种来源：
  1. **HierarchicalValueExpression**：遍历所有节点，检查 `type(node).__name__ == "HierarchicalValueExpression"`，`node.symbol` 是 `Variable` 且 `name` 匹配。取 `node.syntax.right.sourceRange`。
  2. **ModportPort**：遍历所有 `SymbolKind.ModportPort` 符号，检查 `modport_port.internalSymbol` 的 `name` 匹配。取 `modport_port.location` 作为 reference。
  3. 不收集 declaration 自身作为 reference。
- 去重：同一个 interface member 只产生一个 entry，所有引用合并为 references。
- scope 使用 interface definition 名。

### 6.3 modports collector

新增 `_collect_modports` 函数：

- 遍历 AST，收集所有 `SymbolKind.Modport` 符号。
- 使用 `modport.location` 作为 declaration。
- 当前版本 `references=[]`（declaration-only，与 instances/generate_blocks 一致）。
- scope 使用 modport 所属的 interface definition 名。

### 6.4 注册到流水线

- 在 `_collect_targets` 中增加 `interface_instances`、`interface_ports`、`modports` 分支。
- 在 `_SUPPORTED_CATEGORIES` 中增加这三个 category。
- 在 `encrypt-project` 的 `--category` choices 中增加这三个 category。
- 这三个 category 不加入 `all` 的展开集合。
- 在 mapping v2 validator 中增加这三个 category 到合法 category 列表。
- 不修改现有单文件 CLI 或 mapping v1。

## 7. 黑盒验收点

- `encrypt-project` stdout 为 `{"files": 3, "mapping_entries": 8, "modified_tokens": 21}`。
- mapping v2 的 8 个 entry 的 declaration 和 reference ranges 精确匹配第 4 节。
- `decrypt-project` 后三个文件与 gold 逐文件 `cmp -s` 退出码为 `0`。
- metrics 的 symbols/occurrences/leakage/effective_coverage 精确匹配第 5 节硬约束。
- 多文件 PySlang Compilation 无 error。
- Verible 对三个 gate 文件退出码为 `0`。
- Icarus 对 gold 和 gate 均不支持 ANSI-style interface port（已知限制，不阻塞验收）。
- 多文件 Yosys formal equivalence 退出码为 `0`，JSON `formal_equivalence=pass`。
- 现有 22 项 unittest 全部通过。
- `git diff --check` 退出码为 `0`。

## 8. Formal verification

```text
formal_verification: PASS (子 Agent 自测) / PASS (主 Agent 独立重跑)
gold: tests/fixtures/t018_interface_member/design.f (bus_if.sv, child.sv, top.sv)
gate: /tmp/rtl_obfuscation_t018/gate/design.f (bus_if.sv, child.sv, top.sv)
top: t018_top
command: conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold-filelist tests/fixtures/t018_interface_member/design.f --gold-root tests/fixtures/t018_interface_member --gate-filelist design.f --gate-root /tmp/rtl_obfuscation_t018/gate --top t018_top
exit_code: 0
result: {"formal_equivalence": "pass", "seq": 5, "top": "t018_top"}
```

## 9. 本任务明确不包含

- `modport_ports` 作为独立 category（归入 `interface_ports` 的 reference）。
- `type_parameters`（T006 保持 `DRAFT`）。
- virtual interface、clocking block、DPI、bind。
- modport type 引用（如 `bus_if.master`）。
- 修改现有单文件 CLI 或 mapping v1。
- 修改 formal 脚本。

## 10. 允许修改的文件

```text
rtl_obfuscator/inventory.py
rtl_obfuscator/rewrite.py
tests/test_interface_member_rewrite.py
docs/tasks/T018_interface_member_roundtrip.md
```

`tests/fixtures/t018_interface_member/` 是主 Agent 已冻结的只读输入。不得修改其他文件。

## 11. 子 Agent 文档流程

1. 开始前将状态从 `READY` 改为 `IN_PROGRESS` 并记录开始时间。
2. 若 PySlang API 与第 6 节描述不一致，记录最小复现并停止。
3. 完成后记录变更文件、所有命令、stdout/stderr、退出码和未覆盖边界。
4. Formal 必须按第 8 节格式记录结果。
5. 全部门禁通过后设置为 `READY_FOR_REVIEW`；不得设置 `ACCEPTED`，不得 commit 或 push。

## 12. 执行记录（子 Agent 更新）

- 尚未开始。

## 13. 偏差或阻塞（子 Agent 更新）

- 无。

## 14. 交付证据（子 Agent 更新）

- 尚未交付。

## 15. 主 Agent 验收结果

- 尚未验收。
