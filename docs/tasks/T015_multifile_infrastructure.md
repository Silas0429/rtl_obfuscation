# T015：多文件基础设施与跨文件回归

- 状态：`READY`
- 设计负责人：主 Agent
- 实现负责人：子 Agent
- 前置任务：T014 已达到 `ACCEPTED`

## 1. 单一目标

建立多文件 Compilation、per-file edits、mapping v2 和 project-level formal 基础设施。只对现有已验收 category 做跨文件回归，不引入新 category，不实现 module/port/interface 重命名。

新增两个 CLI 子命令：`encrypt-project` 和 `decrypt-project`。现有单文件 `encrypt`/`decrypt` 保持不变。

## 2. 固定输入与输出

```text
filelist    = tests/fixtures/t015_multi_file/design.f
source_root = tests/fixtures/t015_multi_file
top         = t015_top
category    = all
name_length = 8
```

filelist 内容：

```text
child.sv
top.sv
```

固定输出目录：

```text
/tmp/rtl_obfuscation_t015/gate/child.sv
/tmp/rtl_obfuscation_t015/gate/top.sv
/tmp/rtl_obfuscation_t015/mapping.json
/tmp/rtl_obfuscation_t015/metrics.json
```

## 3. 固定 CLI

### 3.1 正向改写

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite encrypt-project \
  --filelist tests/fixtures/t015_multi_file/design.f \
  --source-root tests/fixtures/t015_multi_file \
  --output-dir /tmp/rtl_obfuscation_t015/gate \
  --map /tmp/rtl_obfuscation_t015/mapping.json \
  --metrics /tmp/rtl_obfuscation_t015/metrics.json \
  --top t015_top \
  --category all \
  --name-length 8
```

### 3.2 反向恢复

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite decrypt-project \
  --gate-dir /tmp/rtl_obfuscation_t015/gate \
  --source-root tests/fixtures/t015_multi_file \
  --map /tmp/rtl_obfuscation_t015/mapping.json \
  --output-dir /tmp/rtl_obfuscation_t015/restored
```

### 3.3 多文件 formal

```sh
conda run -n rtl_obfuscation python scripts/formal_equivalence.py \
  --gold-filelist tests/fixtures/t015_multi_file/design.f \
  --gold-root tests/fixtures/t015_multi_file \
  --gate-filelist design.f \
  --gate-root /tmp/rtl_obfuscation_t015/gate \
  --top t015_top
```

## 4. 精确 mapping 预期

mapping v2 schema：

```json
{
  "version": 2,
  "name_length": 8,
  "files": ["child.sv", "top.sv"],
  "entries": [...]
}
```

4 个 entry，按 `(declaration.file, declaration.start, category)` 排序：

```text
entry 0:
  category    = signals
  scope       = t015_child
  original    = stored_value
  declaration = {file: "child.sv", start: 131, end: 144}
  references  = [{file: "child.sv", start: 163, end: 176}, {file: "child.sv", start: 197, end: 210}]
  tokens      = 3

entry 1:
  category    = signals
  scope       = t015_child
  original    = temp_value
  declaration = {file: "child.sv", start: 156, end: 166}
  references  = [{file: "child.sv", start: 179, end: 189}]
  tokens      = 2

entry 2:
  category    = typedefs
  scope       = t015_child
  original    = byte_t
  declaration = {file: "child.sv", start: 111, end: 117}
  references  = [{file: "child.sv", start: 124, end: 130}, {file: "child.sv", start: 149, end: 155}]
  tokens      = 3

entry 3:
  category    = instances
  scope       = t015_top
  original    = u_child
  declaration = {file: "top.sv", start: 100, end: 107}
  references  = []
  tokens      = 1
```

汇总：files=2, entries=4, tokens=9。

## 5. 精确 metrics 预期

metrics 为全项目聚合。具体数值由现有 `_metrics` 函数对全项目 gate 与 gold 逐文件计算后聚合产生。子 Agent 需要记录实际输出值；主 Agent 验收时独立确认。

必须满足的硬约束：

- symbols: renamed=4, eligible=4, coverage=1.0
- occurrences: renamed=9, eligible=9, coverage=1.0
- plaintext_leakage_rate: 0.0
- effective_coverage: 1.0

## 6. 实现要求

### 6.1 新增 `encrypt-project` 子命令

在 `rtl_obfuscator/rewrite.py` 中新增 `encrypt-project` 子命令：

- `--filelist`：UTF-8 文本文件，每行一个相对 `--source-root` 的 `.sv` 路径。
- `--source-root`：filelist 中路径的根目录。
- `--output-dir`：gate 输出目录，保持输入相对路径。
- `--map`：mapping v2 JSON 输出路径。
- `--metrics`：metrics JSON 输出路径。
- `--top`：不变的 top module 名。
- `--category`：支持 `all` 或单个 category（与现有 `encrypt` 相同的 choices）。
- `--name-length`：与现有 CLI 相同。

### 6.2 多文件 Compilation

在 `rtl_obfuscator/inventory.py` 中新增 `_build_project_inventory` 函数：

- 读取 filelist，解析每个文件路径。
- 为每个文件创建 `SyntaxTree.fromFile()`。
- 创建一个 `Compilation`，将所有 SyntaxTree 加入。
- 检查 diagnostics，有 error 则失败。
- 对 `--category all` 展开为现有 13 个已验收 category。
- 全局收集 targets 和 existing identifiers。
- 全局生成不冲突的新名称。
- 收集跨文件 declaration/reference ranges。
- range 中的 `file` 字段使用相对 `source-root` 的规范路径。
- 返回 mapping v2 dict。

### 6.3 per-file edits

- 将所有 entries 的 ranges 按文件分组。
- 对每个文件读取原始 bytes，收集该文件的 edits。
- 校验 expected bytes、无重复、无重叠。
- 倒序应用 edits，写出 gate 文件。
- 未发生改写的文件也复制到输出目录。

### 6.4 mapping v2 schema

```json
{
  "version": 2,
  "name_length": 8,
  "files": ["child.sv", "top.sv"],
  "entries": [
    {
      "category": "signals",
      "scope": "t015_child",
      "original_name": "stored_value",
      "renamed_name": "Ab3CdEf4",
      "declaration": {"file": "child.sv", "start": 131, "end": 144},
      "references": [{"file": "child.sv", "start": 163, "end": 176}, ...]
    }
  ]
}
```

### 6.5 新增 `decrypt-project` 子命令

- `--gate-dir`：gate 输出目录。
- `--source-root`：用于解析 mapping 中的相对路径。
- `--map`：mapping v2 JSON。
- `--output-dir`：恢复文件输出目录。
- 读取 mapping v2，验证 schema。
- 对每个 gate 文件重新解析 Compilation，收集 gate 中的 ranges。
- 按 mapping 将 renamed_name 替换回 original_name。
- 逐文件写出恢复结果。

### 6.6 扩展 formal 脚本

在 `scripts/formal_equivalence.py` 中新增多文件模式：

- 新增 `--gold-filelist`、`--gold-root`、`--gate-filelist`、`--gate-root` 参数。
- 当使用 filelist 模式时，Yosys 脚本中 `read_verilog -sv -formal` 后跟多个文件路径。
- 保持 `equiv_status -assert` 不变。
- 现有单文件 `--gold`/`--gate` 模式保持不变。

### 6.7 全局 metrics

- 对全项目所有文件聚合计算。
- affected_lines：所有文件的变更行数之和 / 所有文件有效代码行数之和。
- symbols 和 occurrences：全项目聚合。
- plaintext_leakage_rate：全项目 gate 中原名出现次数 / 全项目 occurrence 总数。
- effective_coverage：sqrt(symbol_coverage * occurrence_coverage)。

### 6.8 stdout 输出

`encrypt-project` 成功时输出一行 JSON：

```json
{"files": 2, "mapping_entries": 4, "modified_tokens": 9}
```

`decrypt-project` 成功时输出相同格式。

## 7. 黑盒验收点

- `encrypt-project` stdout 为 `{"files": 2, "mapping_entries": 4, "modified_tokens": 9}`。
- mapping v2 的 `files`、`version`、`name_length` 正确。
- mapping 的 4 个 entry 的 declaration 和 reference ranges 精确匹配第 4 节。
- gate 目录中 `child.sv` 和 `top.sv` 都存在。
- `child.sv` 中 `byte_t`、`stored_value`、`temp_value` 被替换；`top.sv` 中 `u_child` 被替换。
- `decrypt-project` 后 `restored/child.sv` 和 `restored/top.sv` 与 gold 逐文件 `cmp -s` 退出码为 `0`。
- metrics 的 symbols/occurrences/leakage/effective_coverage 精确匹配第 5 节硬约束。
- 两组 gate 文件的 PySlang Compilation 无 error。
- 两组 gate 文件的 `verible-verilog-syntax --lang=sv` 退出码为 `0`。
- 两组 gate 文件的 `iverilog -g2012 -t null -s t015_top` 退出码为 `0`。
- 多文件 Yosys formal equivalence 退出码为 `0`，JSON `formal_equivalence=pass`。
- 现有 19 项 unittest 全部通过。
- `git diff --check` 退出码为 `0`。

## 8. Formal verification

```text
formal_verification: PASS (子 Agent 自测) / PASS (主 Agent 独立重跑)
gold: tests/fixtures/t015_multi_file/design.f (child.sv, top.sv)
gate: /tmp/rtl_obfuscation_t015/gate/design.f (child.sv, top.sv)
top: t015_top
command: conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold-filelist tests/fixtures/t015_multi_file/design.f --gold-root tests/fixtures/t015_multi_file --gate-filelist design.f --gate-root /tmp/rtl_obfuscation_t015/gate --top t015_top
exit_code: 0
result: {"formal_equivalence": "pass", "seq": 5, "top": "t015_top"}
```

## 9. 本任务明确不包含

- 新的重命名 category（module、port、interface 等）。
- `modules`、`ports`、`interfaces`、`interface_instances`、`interface_ports`、`modports`、`modport_ports`。
- `type_parameters`（T006 保持 `DRAFT`）。
- `+incdir+`、`+define+`、library、嵌套 filelist 解析。
- top module 或 top port 重命名。
- 修改现有单文件 `encrypt`/`decrypt` CLI 或 mapping v1。
- 修改现有 formal 脚本的单文件模式。

## 10. 允许修改的文件

```text
rtl_obfuscator/inventory.py
rtl_obfuscator/rewrite.py
scripts/formal_equivalence.py
tests/test_multifile_project.py
docs/tasks/T015_multifile_infrastructure.md
```

`tests/fixtures/t015_multi_file/` 是主 Agent 已冻结的只读输入。不得修改其他文件。

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
