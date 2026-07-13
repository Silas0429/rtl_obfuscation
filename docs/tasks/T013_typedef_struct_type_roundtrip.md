# T013：单文件 typedefs 与 struct_types 端到端重命名

- 状态：`READY`
- 设计负责人：主 Agent
- 实现负责人：子 Agent
- 前置任务：T012 已达到 `ACCEPTED`

## 1. 单一目标

为统一重命名流水线增加两个 category：

1. `typedefs`：普通 typedef 名（`typedef logic [7:0] byte_t;` 中的 `byte_t`），其 `TypeAlias` 符号的 `isStruct=False`。
2. `struct_types`：typedef struct/union 的类型名（`typedef struct packed {...} header_t;` 中的 `header_t`），其 `TypeAlias` 符号的 `isStruct=True`。

两个 category 共用现有随机名称、semantic symbol、source range、byte edit、mapping、decrypt、metrics 和 Yosys formal 流水线。`type_parameters` 不属于本任务。

## 2. 固定输入与输出

### 2.1 typedefs

```text
gold        = tests/fixtures/t013_typedef.sv
category    = typedefs
name_length = 8
top         = t013_typedef
```

固定输出：

```text
/tmp/rtl_obfuscation_t013/typedefs/gate.sv
/tmp/rtl_obfuscation_t013/typedefs/restored.sv
/tmp/rtl_obfuscation_t013/typedefs/mapping.json
/tmp/rtl_obfuscation_t013/typedefs/metrics.json
```

### 2.2 struct_types

```text
gold        = tests/fixtures/t013_struct_type.sv
category    = struct_types
name_length = 8
top         = t013_struct_type
```

固定输出：

```text
/tmp/rtl_obfuscation_t013/struct_types/gate.sv
/tmp/rtl_obfuscation_t013/struct_types/restored.sv
/tmp/rtl_obfuscation_t013/struct_types/mapping.json
/tmp/rtl_obfuscation_t013/struct_types/metrics.json
```

## 3. 固定 CLI

### 3.1 typedefs

正向改写：

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite encrypt \
  --input tests/fixtures/t013_typedef.sv \
  --output /tmp/rtl_obfuscation_t013/typedefs/gate.sv \
  --map /tmp/rtl_obfuscation_t013/typedefs/mapping.json \
  --metrics /tmp/rtl_obfuscation_t013/typedefs/metrics.json \
  --category typedefs \
  --name-length 8
```

反向恢复：

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite decrypt \
  --input /tmp/rtl_obfuscation_t013/typedefs/gate.sv \
  --output /tmp/rtl_obfuscation_t013/typedefs/restored.sv \
  --map /tmp/rtl_obfuscation_t013/typedefs/mapping.json
```

### 3.2 struct_types

正向改写：

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite encrypt \
  --input tests/fixtures/t013_struct_type.sv \
  --output /tmp/rtl_obfuscation_t013/struct_types/gate.sv \
  --map /tmp/rtl_obfuscation_t013/struct_types/mapping.json \
  --metrics /tmp/rtl_obfuscation_t013/struct_types/metrics.json \
  --category struct_types \
  --name-length 8
```

反向恢复：

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite decrypt \
  --input /tmp/rtl_obfuscation_t013/struct_types/gate.sv \
  --output /tmp/rtl_obfuscation_t013/struct_types/restored.sv \
  --map /tmp/rtl_obfuscation_t013/struct_types/mapping.json
```

## 4. 精确 mapping 预期

### 4.1 typedefs

```text
category    = typedefs
scope       = t013_typedef
original    = byte_t
declaration = [113, 119)
references  = [126, 132), [151, 157)
entries     = 1
tokens      = 3
```

### 4.2 struct_types

```text
category    = struct_types
scope       = t013_struct_type
original    = header_t
declaration = [192, 200)
references  = [207, 215), [235, 243)
entries     = 1
tokens      = 3
```

## 5. 精确 metrics 预期

### 5.1 typedefs

```text
affected_lines: changed=3, total=9, rate=0.333...
symbols: renamed=1, eligible=1, coverage=1.0
occurrences: renamed=3, eligible=3, coverage=1.0
plaintext_leakage_rate: 0.0
effective_coverage: 1.0
```

### 5.2 struct_types

```text
affected_lines: changed=3, total=11, rate=0.272...
symbols: renamed=1, eligible=1, coverage=1.0
occurrences: renamed=3, eligible=3, coverage=1.0
plaintext_leakage_rate: 0.0
effective_coverage: 1.0
```

## 6. 实现要求

### 6.1 新增 collector

在 `rtl_obfuscator/inventory.py` 中新增 `_collect_type_aliases` 函数，接受 `compilation` 和 `category` 参数：

- 遍历 AST，收集 `SymbolKind.TypeAlias` 符号。
- 只收集 `declaringDefinition.definitionKind == DefinitionKind.Module` 的符号。
- 当 `category == "typedefs"` 时，只收集 `isStruct=False` 且 `isPackedUnion=False` 且 `isUnpackedStruct=False` 且 `isUnpackedUnion=False` 的符号。
- 当 `category == "struct_types"` 时，只收集 `isStruct=True` 或 `isPackedUnion=True` 或 `isUnpackedStruct=True` 或 `isUnpackedUnion=True` 的符号。
- 使用 `_symbol_sort_key` 去重和排序。
- 返回 `(ordered_targets, existing_identifiers)`。

### 6.2 reference 收集

在 `inventory.py` 的 `_build_inventory` 中，为 `typedefs` 和 `struct_types` 的每个 entry 收集 references：

- 遍历 AST 中所有 `SymbolKind.Variable`、`SymbolKind.Net` 和 `SymbolKind.FormalArgument` 符号。
- 检查 `declaredType.type` 是否解析为当前 `TypeAlias` 符号（`kind == TypeAlias` 且 `name` 匹配）。
- 如果匹配，取 `declaredType.typeSyntax.sourceRange` 作为 reference range。
- 校验 range 内的字节等于 `original_name`。
- 不收集 declaration 自身作为 reference（避免重复）。

### 6.3 注册到流水线

- 在 `_collect_targets` 中增加 `typedefs` 和 `struct_types` 分支，调用 `_collect_type_aliases`。
- 在 `_SUPPORTED_CATEGORIES` 中增加 `"typedefs"` 和 `"struct_types"`。
- 在 `rewrite.py` 的 `--category all` 安全集合中增加这两个 category。
- 不修改现有 category 的行为。

### 6.4 declaration range

使用 `TypeAlias.location.offset` 作为 declaration start，`offset + len(name)` 作为 end。使用 `_range_record` 生成 range dict。

## 7. 黑盒验收点

- 两组 encrypt/decrypt stdout 均为 `{"files": 1, "mapping_entries": 1, "modified_tokens": 3}`。
- 两组 mapping 精确匹配第 4 节的 declaration 和 reference ranges。
- 两组 restored 与 gold 的 `cmp -s` 退出码为 `0`。
- 两组 metrics 精确匹配第 5 节。
- 两组 gate 的 PySlang Compilation 无 error。
- 两组 gate 的 `verible-verilog-syntax --lang=sv` 退出码为 `0`。
- 两组 gate 的 `iverilog -g2012 -t null -s <top>` 退出码为 `0`。
- 两组 Yosys formal equivalence 退出码为 `0`，JSON `formal_equivalence=pass`。
- 现有 15 项 unittest 全部通过。
- `git diff --check` 退出码为 `0`。

## 8. Formal verification

```text
formal_verification: PASS (子 Agent 自测) / PASS (主 Agent 独立重跑)
gold: tests/fixtures/t013_typedef.sv
gate: /tmp/rtl_obfuscation_t013/typedefs/gate.sv
top: t013_typedef
command: conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold tests/fixtures/t013_typedef.sv --gate /tmp/rtl_obfuscation_t013/typedefs/gate.sv --top t013_typedef
exit_code: 0
result: {"formal_equivalence": "pass", "seq": 5, "top": "t013_typedef"}
```

```text
formal_verification: PASS (子 Agent 自测) / PASS (主 Agent 独立重跑)
gold: tests/fixtures/t013_struct_type.sv
gate: /tmp/rtl_obfuscation_t013/struct_types/gate.sv
top: t013_struct_type
command: conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold tests/fixtures/t013_struct_type.sv --gate /tmp/rtl_obfuscation_t013/struct_types/gate.sv --top t013_struct_type
exit_code: 0
result: {"formal_equivalence": "pass", "seq": 5, "top": "t013_struct_type"}
```

## 9. 本任务明确不包含

- `type_parameters`（T006 保持 `DRAFT`）。
- `struct_fields`、`union_fields`（T014）。
- 多文件、package 作用域、class type、virtual interface、cross-scope 引用。
- typedef forward declaration、import、`$unit` 作用域。
- port 类型引用、function 返回值类型引用、parameter dimension 引用、cast 表达式。
- 修改 formal 脚本、现有 fixtures 或现有测试。

## 10. 允许修改的文件

```text
rtl_obfuscator/inventory.py
rtl_obfuscator/rewrite.py
tests/test_typedef_rewrite.py
tests/test_struct_type_rewrite.py
docs/tasks/T013_typedef_struct_type_roundtrip.md
```

`tests/fixtures/t013_typedef.sv` 和 `tests/fixtures/t013_struct_type.sv` 是主 Agent 已冻结的只读输入。不得修改其他文件。

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
