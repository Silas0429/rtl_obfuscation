# T012：单文件 instance 与显式 generate block label

- 状态：`READY`
- 设计负责人：主 Agent
- 实现负责人：子 Agent
- 前置任务：T011 已达到 `ACCEPTED`

## 1. 单一批次目标

在单文件、无层次引用的最小边界内增加两个默认启用 category：

1. `instances`：具名 module instance 的声明 token。
2. `generate_blocks`：具名 generate-for block label 的声明 token。

同时允许 declaration-only mapping entry，并将两个 category 加入 `--category all` 的安全集合。不得实现 module type、port、跨文件或层次路径重命名。

## 2. 固定输入和输出

### 2.1 Instance

```text
gold = rtl_samples/06_module_instance.sv
top = sample06_module_instance
category = instances
output = /tmp/rtl_obfuscation_t012/instances
```

### 2.2 Generate block

```text
gold = rtl_samples/07_generate_loop.sv
top = sample07_generate_loop
category = generate_blocks
output = /tmp/rtl_obfuscation_t012/generate_blocks
```

每个输出目录包含 `gate.sv`、`restored.sv`、`mapping.json`、`metrics.json`，名称长度固定为 8。

## 3. 固定 mapping

### 3.1 instances

mapping 只有一个 declaration-only entry：

```json
{
  "category": "instances",
  "scope": "sample06_module_instance",
  "original_name": "inverter_instance",
  "renamed_name": "<8-character legal random identifier>",
  "declaration": {
    "file": "rtl_samples/06_module_instance.sv",
    "start": 437,
    "end": 454
  },
  "references": []
}
```

top elaboration instance、module 名 `sample06_inverter_cell`、ports 和 signals 均不得生成 `instances` entry。

### 3.2 generate_blocks

mapping 只有一个 declaration-only entry：

```json
{
  "category": "generate_blocks",
  "scope": "sample07_generate_loop",
  "original_name": "generate_mask",
  "renamed_name": "<8-character legal random identifier>",
  "declaration": {
    "file": "rtl_samples/07_generate_loop.sv",
    "start": 371,
    "end": 384
  },
  "references": []
}
```

4 个展开后的匿名 `GenerateBlockSymbol`、`bit_index`、`WIDTH` 和 `masked_data` 均不得生成 `generate_blocks` entry。

## 4. 固定 CLI 和 stdout

对两组运行分别执行：

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite encrypt \
  --input <gold> \
  --output <dir>/gate.sv \
  --map <dir>/mapping.json \
  --metrics <dir>/metrics.json \
  --category <category> \
  --name-length 8

conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite decrypt \
  --input <dir>/gate.sv \
  --output <dir>/restored.sv \
  --map <dir>/mapping.json
```

encrypt/decrypt stdout 均必须为：

```json
{"files": 1, "mapping_entries": 1, "modified_tokens": 1}
```

两组 gate 都必须只改变 declaration token；restored 必须与 gold 字节一致。

## 5. 固定 metrics

Instance：

```json
{
  "affected_lines": {"changed": 1, "total": 19, "rate": 0.05263157894736842},
  "symbols": {"renamed": 1, "eligible": 1, "coverage": 1.0},
  "occurrences": {"renamed": 1, "eligible": 1, "coverage": 1.0},
  "plaintext_leakage_rate": 0.0,
  "effective_coverage": 1.0
}
```

Generate block：

```json
{
  "affected_lines": {"changed": 1, "total": 13, "rate": 0.07692307692307693},
  "symbols": {"renamed": 1, "eligible": 1, "coverage": 1.0},
  "occurrences": {"renamed": 1, "eligible": 1, "coverage": 1.0},
  "plaintext_leakage_rate": 0.0,
  "effective_coverage": 1.0
}
```

## 6. PySlang 11 最小实现边界

- `instances` 只收集 `InstanceSymbol` 且 `syntax.kind == HierarchicalInstance`、有 module declaringDefinition 的显式源码 instance；排除 compilation root 的 syntax-less top instance。
- `generate_blocks` 只收集有名称的 `GenerateBlockArraySymbol` 且 `syntax.kind == LoopGenerate`；排除 4 个展开后的匿名 `GenerateBlockSymbol`。
- 两者直接使用 symbol location 作为 declaration range；本任务没有 reference collector。
- mapping validator 必须允许 `references=[]`，但字段仍必须是 list；declaration 始终必需。
- 复用现有随机命名、全局 edits、metrics、mixed mapping 和 decrypt，不增加 hierarchy 字符串搜索。

## 7. `all` 集成变化

`_SUPPORTED_CATEGORIES` 在现有顺序末尾追加：

```text
instances generate_blocks
```

综合样例 `rtl_samples/11_supported_obfuscation.sv` 没有 module instance，但包含显式 label `generate_input [1210,1224)`。因此单命令 `--category all` 的固定结果更新为：

```json
{"files": 1, "mapping_entries": 22, "modified_tokens": 61}
```

原 21 entries 顺序不变，最后追加：

```text
generate_blocks / generate_input / 1 token
```

全局 metrics 更新为：

```json
{
  "affected_lines": {"changed": 40, "total": 61, "rate": 0.6557377049180327},
  "symbols": {"renamed": 22, "eligible": 22, "coverage": 1.0},
  "occurrences": {"renamed": 61, "eligible": 61, "coverage": 1.0},
  "plaintext_leakage_rate": 0.0,
  "effective_coverage": 1.0
}
```

affected lines 仍为 40，因为 `generate_input` 与已改写 genvar 位于同一行。

## 8. 统一回归

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_variable_inventory \
  tests.test_variable_ranges \
  tests.test_variable_rewrite \
  tests.test_signal_net_rewrite \
  tests.test_value_parameter_rewrite \
  tests.test_multi_signal_rewrite \
  tests.test_localparam_rewrite \
  tests.test_enum_value_rewrite \
  tests.test_genvar_rewrite \
  tests.test_subroutine_rewrite \
  tests.test_supported_integration \
  tests.test_all_category_rewrite \
  tests.test_hierarchy_name_rewrite
```

新增测试必须断言两组 1/1 mappings、空 references、精确 gate、metrics 和 round-trip；同时更新 all 测试为 22/61。

## 9. 前端和 formal

Instance gate：

```sh
conda run -n rtl_obfuscation python scripts/formal_equivalence.py \
  --gold rtl_samples/06_module_instance.sv \
  --gate /tmp/rtl_obfuscation_t012/instances/gate.sv \
  --top sample06_module_instance
```

Generate block gate：

```sh
conda run -n rtl_obfuscation python scripts/formal_equivalence.py \
  --gold rtl_samples/07_generate_loop.sv \
  --gate /tmp/rtl_obfuscation_t012/generate_blocks/gate.sv \
  --top sample07_generate_loop
```

更新后的 all demo gate 也必须按 T011 命令重跑 formal。三组 gate 均须通过 PySlang、Verible、Icarus，三次 formal 均须为 `pass`。

主 Agent 已用手工改名 gate 对 instance 和 generate block 两组完成三前端及 formal 预探测，全部通过。

## 10. 明确不包含

- instance 的层次引用、array of instances、primitive/checker/interface instance。
- module type 名、module 声明、named port/parameter 左侧。
- generate block 的层次引用、嵌套 generate、conditional generate、implicit `genblkN`。
- 多文件、port、interface、type 或 field 类别。
- 修改冻结 RTL 样例和 fixtures。

## 11. 允许修改的文件

```text
rtl_obfuscator/inventory.py
rtl_obfuscator/rewrite.py
tests/test_all_category_rewrite.py
tests/test_hierarchy_name_rewrite.py
docs/tasks/T012_instance_generate_block_roundtrip.md
```

不得修改其他文件。

## 12. 子 Agent 流程

1. 开始前设置 `IN_PROGRESS` 并记录实际 Instance/GenerateBlockArray API。
2. 只实现 declaration-only 边界，不增加 hierarchy reference 推断。
3. 记录 13 个回归模块、三组 gate 前端和 formal、三组 round-trip。
4. 完成后设置 `READY_FOR_REVIEW`；不得设置 `ACCEPTED`、commit 或 push。

## 13. Formal verification（子 Agent 完成时填写）

```text
formal_verification: PENDING
instances: gold/gate/top/command/exit_code/result
generate_blocks: gold/gate/top/command/exit_code/result
all_demo: gold/gate/top/command/exit_code/result
```

## 14. 执行记录（子 Agent 更新）

- 尚未开始。

## 15. 偏差或阻塞（子 Agent 更新）

- 无。

## 16. 交付证据（子 Agent 更新）

- 尚未交付。

## 17. 主 Agent 验收结果

- 尚未验收。
