# T014：单文件 struct_fields 与 union_fields 端到端重命名

- 状态：`READY`
- 设计负责人：主 Agent
- 实现负责人：子 Agent
- 前置任务：T013 已达到 `ACCEPTED`

## 1. 单一目标

为统一重命名流水线增加两个 category：

1. `struct_fields`：packed struct 内的 member 声明名及其 member access 引用。
2. `union_fields`：packed union 内的 member 声明名及其 member access 引用。

两个 category 共用现有随机名称、semantic symbol、source range、byte edit、mapping、decrypt、metrics 和 Yosys formal 流水线。

## 2. 固定输入与输出

### 2.1 struct_fields

```text
gold        = tests/fixtures/t014_struct_field.sv
category    = struct_fields
name_length = 8
top         = t014_struct_field
```

固定输出：

```text
/tmp/rtl_obfuscation_t014/struct_fields/gate.sv
/tmp/rtl_obfuscation_t014/struct_fields/restored.sv
/tmp/rtl_obfuscation_t014/struct_fields/mapping.json
/tmp/rtl_obfuscation_t014/struct_fields/metrics.json
```

### 2.2 union_fields

```text
gold        = tests/fixtures/t014_union_field.sv
category    = union_fields
name_length = 8
top         = t014_union_field
```

固定输出：

```text
/tmp/rtl_obfuscation_t014/union_fields/gate.sv
/tmp/rtl_obfuscation_t014/union_fields/restored.sv
/tmp/rtl_obfuscation_t014/union_fields/mapping.json
/tmp/rtl_obfuscation_t014/union_fields/metrics.json
```

## 3. 固定 CLI

### 3.1 struct_fields

正向改写：

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite encrypt \
  --input tests/fixtures/t014_struct_field.sv \
  --output /tmp/rtl_obfuscation_t014/struct_fields/gate.sv \
  --map /tmp/rtl_obfuscation_t014/struct_fields/mapping.json \
  --metrics /tmp/rtl_obfuscation_t014/struct_fields/metrics.json \
  --category struct_fields \
  --name-length 8
```

反向恢复：

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite decrypt \
  --input /tmp/rtl_obfuscation_t014/struct_fields/gate.sv \
  --output /tmp/rtl_obfuscation_t014/struct_fields/restored.sv \
  --map /tmp/rtl_obfuscation_t014/struct_fields/mapping.json
```

### 3.2 union_fields

正向改写：

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite encrypt \
  --input tests/fixtures/t014_union_field.sv \
  --output /tmp/rtl_obfuscation_t014/union_fields/gate.sv \
  --map /tmp/rtl_obfuscation_t014/union_fields/mapping.json \
  --metrics /tmp/rtl_obfuscation_t014/union_fields/metrics.json \
  --category union_fields \
  --name-length 8
```

反向恢复：

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite decrypt \
  --input /tmp/rtl_obfuscation_t014/union_fields/gate.sv \
  --output /tmp/rtl_obfuscation_t014/union_fields/restored.sv \
  --map /tmp/rtl_obfuscation_t014/union_fields/mapping.json
```

## 4. 精确 mapping 预期

### 4.1 struct_fields

两个 entry，按 SymbolKey 排序（offset 升序）：

```text
entry 0:
  category    = struct_fields
  scope       = t014_struct_field
  original    = low_nibble
  declaration = [142, 152)
  references  = [301, 311), [475, 485)
  tokens      = 3

entry 1:
  category    = struct_fields
  scope       = t014_struct_field
  original    = high_nibble
  declaration = [174, 185)
  references  = [349, 360), [448, 459)
  tokens      = 3
```

汇总：entries=2, tokens=6。

### 4.2 union_fields

两个 entry，按 SymbolKey 排序（offset 升序）：

```text
entry 0:
  category    = union_fields
  scope       = t014_union_field
  original    = word
  declaration = [143, 147)
  references  = [282, 286)
  tokens      = 2

entry 1:
  category    = union_fields
  scope       = t014_union_field
  original    = reversed
  declaration = [170, 178)
  references  = [362, 370)
  tokens      = 2
```

汇总：entries=2, tokens=4。

## 5. 精确 metrics 预期

### 5.1 struct_fields

```text
affected_lines: changed=4, total=9, rate=0.444...
symbols: renamed=2, eligible=2, coverage=1.0
occurrences: renamed=6, eligible=6, coverage=1.0
plaintext_leakage_rate: 0.0
effective_coverage: 1.0
```

### 5.2 union_fields

```text
affected_lines: changed=3, total=9, rate=0.333...
symbols: renamed=2, eligible=2, coverage=1.0
occurrences: renamed=4, eligible=4, coverage=1.0
plaintext_leakage_rate: 0.0
effective_coverage: 1.0
```

## 6. 实现要求

### 6.1 新增 collector

在 `rtl_obfuscator/inventory.py` 中新增 `_collect_struct_union_fields` 函数，接受 `compilation` 和 `category` 参数：

- 遍历 AST，收集所有 `SymbolKind.TypeAlias` 符号。
- 只收集 `declaringDefinition.definitionKind == DefinitionKind.Module` 的 TypeAlias。
- 对每个 TypeAlias，取 `targetType.type`（resolved type）。
- 当 `category == "struct_fields"` 时，只处理 `resolved.isStruct == True` 的 TypeAlias。
- 当 `category == "union_fields"` 时，只处理 `resolved.isPackedUnion == True` 或 `resolved.isUnpackedUnion == True` 的 TypeAlias。
- 对匹配的 resolved type，遍历其子符号收集 `SymbolKind.Field` 符号。
- 使用 `_symbol_sort_key` 去重和排序。
- 返回 `(ordered_targets, existing_identifiers)`。

### 6.2 reference 收集

在 `inventory.py` 的 `_build_inventory` 中，为 `struct_fields` 和 `union_fields` 的每个 entry 收集 references：

- 遍历 AST 中所有 `MemberAccessExpression` 节点（通过 `type(node).__name__ == "MemberAccessExpression"` 识别）。
- 检查 `node.member` 是否是 `SymbolKind.Field` 且 `name` 匹配当前 field。
- 如果匹配，取 `node.syntax.right.sourceRange` 作为 reference range。
- 校验 range 内的字节等于 `original_name`。
- 不收集 declaration 自身作为 reference（避免重复）。

### 6.3 注册到流水线

- 在 `_collect_targets` 中增加 `struct_fields` 和 `union_fields` 分支，调用 `_collect_struct_union_fields`。
- 在 `_SUPPORTED_CATEGORIES` 中增加 `"struct_fields"` 和 `"union_fields"`。
- 在 `rewrite.py` 的 `--category all` 安全集合中增加这两个 category。
- 不修改现有 category 的行为。

### 6.4 declaration range

使用 `Field.location.offset` 作为 declaration start，`offset + len(name)` 作为 end。使用 `_range_record` 生成 range dict。

### 6.5 scope

scope 使用 TypeAlias 的 `declaringDefinition` 的 module 名（即 `t014_struct_field` 或 `t014_union_field`），与现有 category 一致。

## 7. 黑盒验收点

- 两组 encrypt/decrypt stdout 分别为 `{"files": 1, "mapping_entries": 2, "modified_tokens": 6}` 和 `{"files": 1, "mapping_entries": 2, "modified_tokens": 4}`。
- 两组 mapping 精确匹配第 4 节的 declaration 和 reference ranges。
- 两组 restored 与 gold 的 `cmp -s` 退出码为 `0`。
- 两组 metrics 精确匹配第 5 节。
- 两组 gate 的 PySlang Compilation 无 error。
- 两组 gate 的 `verible-verilog-syntax --lang=sv` 退出码为 `0`。
- 两组 gate 的 `iverilog -g2012 -t null -s <top>` 退出码为 `0`（Icarus "sorry" 消息是 warning 不是 error，退出码为 0 即可）。
- 两组 Yosys formal equivalence 退出码为 `0`，JSON `formal_equivalence=pass`。
- 现有 17 项 unittest 全部通过。
- `git diff --check` 退出码为 `0`。

## 8. Formal verification

```text
formal_verification: PASS (子 Agent 自测) / PASS (主 Agent 独立重跑)
gold: tests/fixtures/t014_struct_field.sv
gate: /tmp/rtl_obfuscation_t014/struct_fields/gate.sv
top: t014_struct_field
command: conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold tests/fixtures/t014_struct_field.sv --gate /tmp/rtl_obfuscation_t014/struct_fields/gate.sv --top t014_struct_field
exit_code: 0
result: {"formal_equivalence": "pass", "seq": 5, "top": "t014_struct_field"}
```

```text
formal_verification: PASS (子 Agent 自测) / PASS (主 Agent 独立重跑)
gold: tests/fixtures/t014_union_field.sv
gate: /tmp/rtl_obfuscation_t014/union_fields/gate.sv
top: t014_union_field
command: conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold tests/fixtures/t014_union_field.sv --gate /tmp/rtl_obfuscation_t014/union_fields/gate.sv --top t014_union_field
exit_code: 0
result: {"formal_equivalence": "pass", "seq": 5, "top": "t014_union_field"}
```

## 9. 本任务明确不包含

- `type_parameters`（T006 保持 `DRAFT`）。
- unpacked struct/union（只处理 packed）。
- assignment pattern key（`'{field: value}` 中的 field name）。
- `with` 表达式、`inside` 操作符、assertion 或 constraint 中的 field 引用。
- 多文件、package 作用域、class property。
- 修改 formal 脚本、现有 fixtures 或现有测试。

## 10. 允许修改的文件

```text
rtl_obfuscator/inventory.py
rtl_obfuscator/rewrite.py
tests/test_struct_field_rewrite.py
tests/test_union_field_rewrite.py
docs/tasks/T014_struct_union_field_roundtrip.md
```

`tests/fixtures/t014_struct_field.sv` 和 `tests/fixtures/t014_union_field.sv` 是主 Agent 已冻结的只读输入。不得修改其他文件。

## 11. 子 Agent 文档流程

1. 开始前将状态从 `READY` 改为 `IN_PROGRESS` 并记录开始时间。
2. 若 PySlang API 与第 6 节描述不一致，记录最小复现并停止，不得退回字符串搜索。
3. 完成后记录变更文件、所有命令、stdout/stderr、退出码和未覆盖边界。
4. Formal 必须按第 8 节格式记录两组结果。
5. 全部门禁通过后设置为 `READY_FOR_REVIEW`；不得设置 `ACCEPTED`，不得 commit 或 push。

## 12. 执行记录（子 Agent 更新）

- 尚未开始。

## 13. 偏差或阻塞（子 Agent 更新）

- 无。

## 14. 交付证据（子 Agent 更新）

- 尚未交付。

## 15. 主 Agent 验收结果

- 尚未验收。
