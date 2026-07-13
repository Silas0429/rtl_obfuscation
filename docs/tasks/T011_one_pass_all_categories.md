# T011：当前 7 个 category 的单次全量加密

- 状态：`ACCEPTED`
- 设计负责人：主 Agent
- 实现负责人：子 Agent
- 前置任务：T010 已达到 `ACCEPTED`

## 1. 单一目标

为 rewrite encrypt 增加 `--category all`：对一个输入文件只解析一次，统一收集当前 7 个 category、全局生成不冲突名称、一次应用全部 source edits，并直接输出一个 gate、一个混合 mapping 和一份全局 metrics。decrypt 使用该单一 mapping 一次恢复。

`all` 不是七阶段 CLI 包装，不得生成中间 RTL。

## 2. 固定输入输出

```text
gold = rtl_samples/11_supported_obfuscation.sv
top = sample11_supported_obfuscation
name_length = 8
category = all
output_root = /tmp/rtl_obfuscation_t011
```

固定输出：

```text
/tmp/rtl_obfuscation_t011/gate.sv
/tmp/rtl_obfuscation_t011/restored.sv
/tmp/rtl_obfuscation_t011/mapping.json
/tmp/rtl_obfuscation_t011/metrics.json
```

## 3. 固定 CLI

```sh
rm -rf /tmp/rtl_obfuscation_t011

conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite encrypt \
  --input rtl_samples/11_supported_obfuscation.sv \
  --output /tmp/rtl_obfuscation_t011/gate.sv \
  --map /tmp/rtl_obfuscation_t011/mapping.json \
  --metrics /tmp/rtl_obfuscation_t011/metrics.json \
  --category all \
  --name-length 8
```

预期 stdout：

```json
{"files": 1, "mapping_entries": 21, "modified_tokens": 60}
```

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite decrypt \
  --input /tmp/rtl_obfuscation_t011/gate.sv \
  --output /tmp/rtl_obfuscation_t011/restored.sv \
  --map /tmp/rtl_obfuscation_t011/mapping.json
```

decrypt stdout 同样必须为 21 entries、60 tokens；restored 必须与 gold 字节完全一致。

## 4. category 和 mapping 规则

`all` 的固定 category 顺序：

```text
signals parameters enum_values genvars functions tasks arguments
```

mapping entry 仍保留真实 category，不得写成 `all`。entry 按上述 category 分组，每组保持现有声明顺序。固定原名顺序：

```text
signals:
  generated_data function_result selected_data transformed_data
  observed_data width_enabled current_state
parameters:
  WIDTH XOR_MASK ACTIVE_BITS RESET_VALUE
enum_values:
  STATE_IDLE STATE_MASK STATE_PASS
genvars:
  bit_index
functions:
  apply_mask
tasks:
  select_value
arguments:
  function_data task_data task_mode task_result
```

必须满足：

- 21 个 `renamed_name` 全局唯一，长度均为 8，且不与输入已有 identifier 冲突。
- 所有 declaration/reference ranges 均直接相对原始 gold，不存在阶段 offset 漂移。
- gate 必须严格等于按 mapping 的 60 个 ranges 对 gold 一次性倒序应用 edits。
- mapping schema 版本仍为 1，不增加新字段。

## 5. 类别所有权修正

PySlang 将传统 function 的隐式返回变量表示为 `VariableSymbol`。它不属于 module 内部 `signals`，必须从 signals collector 排除，由 `functions` 独占 function 声明、传统返回赋值和调用。

固定负验收输入：`tests/fixtures/t009_function_argument.sv`。

对该文件执行 `--category all` 时必须只有：

```text
functions: transform_value, 3 tokens
arguments: function_data, 2 tokens
total: 2 entries / 5 tokens
```

不得生成 `signals / transform_value` entry。该 gate 必须 formal PASS，并能用单 mapping 一次恢复。

T010 已处理的 genvar iteration parameter 所有权保持不变：它只属于 `genvars`，不得归入 `parameters`。

## 6. 最小实现方案

- rewrite encrypt CLI 只新增一个公开值 `all`；原单 category 行为保持不变，继续作为 debug 模式。
- inventory 内部允许用固定 category 列表建立一个 combined inventory；每个 target 与其真实 category 并行保存。
- unavailable identifier 集合和本次新名称集合必须跨全部 category 共用。
- 复用现有 `_add_ranges` 的 mixed-category 能力和 rewrite 的全局 edit 应用，不复制七条 rewrite 流水线。
- decrypt mapping validator 不接受 entry category=`all`；它继续验证每个真实 category。现有 mixed mapping gate range 收集应直接复用。
- signals collector 只增加 function return variable 排除，不增加其他 scope 推断或兼容逻辑。
- 不新增配置文件、wrapper script、依赖、并发、缓存或多文件抽象。

## 7. 固定全局 metrics

```json
{
  "affected_lines": {
    "changed": 40,
    "total": 61,
    "rate": 0.6557377049180327
  },
  "symbols": {
    "renamed": 21,
    "eligible": 21,
    "coverage": 1.0
  },
  "occurrences": {
    "renamed": 60,
    "eligible": 60,
    "coverage": 1.0
  },
  "plaintext_leakage_rate": 0.0,
  "effective_coverage": 1.0
}
```

这是一份对原始 gold 和最终 gate 的全局指标，不是七阶段指标求和。

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
  tests.test_all_category_rewrite
```

新增测试必须覆盖：

- 综合样例单命令 21/60、固定 entry 顺序、全局唯一名称、精确 gate、metrics 和单次恢复。
- function fixture 的 2/5 所有权负测和单次恢复。
- 原有 7 个单 category CLI 行为全部回归。

## 9. 前端与 formal

```sh
conda run -n rtl_obfuscation python -c \
  'import pyslang; t=pyslang.syntax.SyntaxTree.fromFile("/tmp/rtl_obfuscation_t011/gate.sv"); c=pyslang.ast.Compilation(); c.addSyntaxTree(t); raise SystemExit(any(d.isError() for d in c.getAllDiagnostics()))'
conda run -n rtl_obfuscation verible-verilog-syntax \
  --lang=sv /tmp/rtl_obfuscation_t011/gate.sv
conda run -n rtl_obfuscation iverilog -g2012 -t null \
  -s sample11_supported_obfuscation /tmp/rtl_obfuscation_t011/gate.sv
conda run -n rtl_obfuscation python scripts/formal_equivalence.py \
  --gold rtl_samples/11_supported_obfuscation.sv \
  --gate /tmp/rtl_obfuscation_t011/gate.sv \
  --top sample11_supported_obfuscation
```

全部退出码必须为 0，formal JSON 必须为 `pass`。

function fixture 的 all gate 也必须独立运行项目 formal 并为 `pass`。

## 10. 明确不包含

- 多文件、多个输入、输出目录树或 include/macro 发现。
- module、port、instance、generate block、type parameter 或后续表内类别。
- 命名实参、type-dimension parameter 引用或已记录的各 category 边界扩展。
- 单一 mapping 加密、密码学安全声明或 mapping 合并旧格式。
- 删除单 category debug 模式。

## 11. 允许修改的文件

```text
rtl_obfuscator/inventory.py
rtl_obfuscator/rewrite.py
tests/test_all_category_rewrite.py
docs/tasks/T011_one_pass_all_categories.md
```

不得修改综合样例、fixtures、现有测试、用户文档、计划文档或 formal 脚本。

## 12. 子 Agent 流程

1. 开始前设置 `IN_PROGRESS`，记录 function return variable identity 探测。
2. 先修正 signals 所有权，再实现一次 combined inventory。
3. 记录 12 项回归、两组 all round-trip、前端和两次 formal。
4. 完成后设置 `READY_FOR_REVIEW`；不得设置 `ACCEPTED`、commit 或 push。

## 13. Formal verification（子 Agent 完成时填写）

```text
formal_verification: PASS
demo:
  gold: rtl_samples/11_supported_obfuscation.sv
  gate: /tmp/rtl_obfuscation_t011/gate.sv
  top: sample11_supported_obfuscation
  command: conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold rtl_samples/11_supported_obfuscation.sv --gate /tmp/rtl_obfuscation_t011/gate.sv --top sample11_supported_obfuscation
  exit_code: 0
  result: {"formal_equivalence": "pass", "gate": "/private/tmp/rtl_obfuscation_t011/gate.sv", "gold": "/Users/lufengchi/Desktop/workspace/rtl_obfuscation/rtl_samples/11_supported_obfuscation.sv", "seq": 5, "top": "sample11_supported_obfuscation"}
function_fixture:
  gold: tests/fixtures/t009_function_argument.sv
  gate: /tmp/rtl_obfuscation_t011/function_fixture/gate.sv
  top: t009_function_argument
  command: conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold tests/fixtures/t009_function_argument.sv --gate /tmp/rtl_obfuscation_t011/function_fixture/gate.sv --top t009_function_argument
  exit_code: 0
  result: {"formal_equivalence": "pass", "gate": "/private/tmp/rtl_obfuscation_t011/function_fixture/gate.sv", "gold": "/Users/lufengchi/Desktop/workspace/rtl_obfuscation/tests/fixtures/t009_function_argument.sv", "seq": 5, "top": "t009_function_argument"}
```

## 14. 执行记录（子 Agent 更新）

- 2026-07-13：将任务设为 `IN_PROGRESS`；开始执行 function return variable identity 探测，尚未修改实现代码。
- PySlang identity 探测：`transform_value` 的 `SubroutineSymbol` 与 `returnValVar` 是不同 identity，但二者均为 buffer `1`、offset `141`、name `transform_value`；`returnValVar.kind=Variable`。传统返回赋值 `[213,228)` 的 `NamedValueExpression.symbol` 精确指向该 `returnValVar`。
- signals 所有权修正：语义遍历收集 function `returnValVar` identity，并在 signals 候选去重前精确排除；端口和其他 signal 逻辑不变。
- combined inventory：`_build_inventory` 只建立一次 `SyntaxTree` 和 `Compilation`；`all` 按固定顺序收集 targets 和真实 categories，共享同一 `unavailable` 集合生成全局唯一名称，然后一次调用 mixed-category `_add_ranges`。
- rewrite encrypt CLI 仅增加公开值 `all`；`_encrypt` 仍对 combined mapping 统一构建 edits 并一次改写，未增加七阶段 wrapper 或中间 RTL。decrypt 继续使用真实 entry category 的现有 mixed mapping 逻辑。
- 新增两个黑盒测试：综合样例 21/60 全量顺序、全局名称唯一/冲突避让、source slices、精确 gate、全局 metrics 和单 mapping 往返；function fixture 2/5 所有权负测和单 mapping 往返。

## 15. 偏差或阻塞（子 Agent 更新）

- 无。

## 16. 交付证据（子 Agent 更新）

- 变更文件：`rtl_obfuscator/inventory.py`、`rtl_obfuscator/rewrite.py`、`tests/test_all_category_rewrite.py`、`docs/tasks/T011_one_pass_all_categories.md`。未修改 sample、fixture、现有测试、用户文档、计划文档或 formal 脚本；仓库中计划文档的已有 dirty 变更不属于本子 Agent。
- 12 项回归命令：第 8 节固定 `python -m unittest` 命令；退出码 `0`，实际运行 `13` 个 test cases，输出 `Ran 13 tests ... OK`。现有 7 个单 category CLI 回归全部通过。
- demo encrypt：第 3 节固定命令；退出码 `0`，stdout `{"files": 1, "mapping_entries": 21, "modified_tokens": 60}`。mapping 按第 4 节固定 category/原名顺序，21 个新名全局唯一且不与输入 identifier 冲突，所有 ranges 相对 gold 且 source slices 正确，gate 精确等于对 60 个 ranges 一次倒序应用 edits。
- demo metrics：`changed=40, total=61, rate=0.6557377049180327`；symbols `21/21`、occurrences `60/60`、symbol/occurrence/effective coverage 均为 `1.0`，plaintext leakage rate 为 `0.0`。
- demo decrypt：第 3 节固定命令；退出码 `0`，stdout `{"files": 1, "mapping_entries": 21, "modified_tokens": 60}`；`cmp -s rtl_samples/11_supported_obfuscation.sv /tmp/rtl_obfuscation_t011/restored.sv` 退出码 `0`。
- demo PySlang：第 9 节固定命令，退出码 `0`。Verible：第 9 节固定命令，退出码 `0`。Icarus：第 9 节固定命令，退出码 `0`。
- demo Yosys formal：见第 13 节；退出码 `0`，JSON `formal_equivalence=pass`。
- function fixture encrypt：`conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite encrypt --input tests/fixtures/t009_function_argument.sv --output /tmp/rtl_obfuscation_t011/function_fixture/gate.sv --map /tmp/rtl_obfuscation_t011/function_fixture/mapping.json --metrics /tmp/rtl_obfuscation_t011/function_fixture/metrics.json --category all --name-length 8`；退出码 `0`，stdout `{"files": 1, "mapping_entries": 2, "modified_tokens": 5}`。mapping 精确为 `functions/transform_value/3 tokens`、`arguments/function_data/2 tokens`，无 `signals/transform_value`。
- function fixture decrypt：`conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite decrypt --input /tmp/rtl_obfuscation_t011/function_fixture/gate.sv --output /tmp/rtl_obfuscation_t011/function_fixture/restored.sv --map /tmp/rtl_obfuscation_t011/function_fixture/mapping.json`；退出码 `0`，stdout `{"files": 1, "mapping_entries": 2, "modified_tokens": 5}`；与 gold 的 `cmp -s` 退出码 `0`。
- function fixture Yosys formal：见第 13 节；退出码 `0`，JSON `formal_equivalence=pass`。
- `git diff --check` 退出码 `0`。未 commit，未 push。
- 未覆盖边界：第 10 节全部仍为范围外；本任务未引入多文件、新 category、mapping schema 变更、配置或 wrapper。

## 17. 主 Agent 验收结果

- 2026-07-13 16:41 CST：主 Agent 使用独立目录 `/tmp/rtl_obfuscation_t011_main` 完成黑盒验收，状态设置为 `ACCEPTED`。
- 12 个回归模块共运行 13 个 tests，退出码 `0`，结果 `OK`。
- demo 单命令 encrypt/decrypt 均输出 `21 entries / 60 tokens`；mapping category/原名顺序、全局唯一名称、source slices 和全局 metrics 与第 4、7 节完全一致，restored 与 gold 字节一致。
- demo gate 的 PySlang、Verible、Icarus 均退出码 `0`；主 Agent 独立 formal 为 `{"formal_equivalence": "pass", "gate": "/private/tmp/rtl_obfuscation_t011_main/gate.sv", "gold": "/Users/lufengchi/Desktop/workspace/rtl_obfuscation/rtl_samples/11_supported_obfuscation.sv", "seq": 5, "top": "sample11_supported_obfuscation"}`。
- function fixture 单命令 encrypt/decrypt 均输出 `2 entries / 5 tokens`，mapping 只有 `functions/transform_value` 和 `arguments/function_data`，无重复 signal entry，restored 与 gold 字节一致。
- function fixture 独立 formal 为 `{"formal_equivalence": "pass", "gate": "/private/tmp/rtl_obfuscation_t011_main/function_gate.sv", "gold": "/Users/lufengchi/Desktop/workspace/rtl_obfuscation/tests/fixtures/t009_function_argument.sv", "seq": 5, "top": "t009_function_argument"}`。
- `git diff --check` 退出码 `0`；实现和测试变更均在第 11 节授权范围内。
