# T010：当前已支持 category 的单文件串联验证

- 状态：`ACCEPTED`
- 设计负责人：主 Agent
- 实现负责人：子 Agent
- 前置任务：T009 已达到 `ACCEPTED`

## 1. 单一目标

修正 `parameters` collector 将 generate iteration `ParameterSymbol` 误当作源码 parameter 的问题，并用一个综合样例证明当前 7 个 category 可以按单 category CLI 串联加密、整体 formal、再逆序恢复。

## 2. 冻结输入和顺序

```text
gold = rtl_samples/11_supported_obfuscation.sv
top = sample11_supported_obfuscation
name_length = 8
categories = signals parameters enum_values genvars functions tasks arguments
output_root = /tmp/rtl_obfuscation_t010
```

主 Agent 已冻结 gold。子 Agent 不得修改 `rtl_samples`、README 或 filelist。

## 3. 唯一实现修正

- `_collect_parameters` 必须继续收集 module value parameter 和普通 module localparam。
- 只排除与源码 `GenvarSymbol` 同名、同 buffer、同声明 offset 的 elaborated iteration `ParameterSymbol`。
- 不得简单排除全部 `isBodyParam`，因为普通 module localparam 同样可能为 `isBodyParam=True`。
- 不修改 genvar、rewrite、mapping、metrics 或 CLI 结构，不增加新 category。

## 4. 固定阶段结果

| category | mapping entries | modified tokens | affected lines |
| --- | ---: | ---: | --- |
| `signals` | 7 | 24 | `21 / 61 = 0.3442622950819672` |
| `parameters` | 4 | 10 | `9 / 61 = 0.14754098360655737` |
| `enum_values` | 3 | 8 | `8 / 61 = 0.13114754098360656` |
| `genvars` | 1 | 5 | `2 / 61 = 0.03278688524590164` |
| `functions` | 1 | 2 | `2 / 61 = 0.03278688524590164` |
| `tasks` | 1 | 2 | `2 / 61 = 0.03278688524590164` |
| `arguments` | 4 | 9 | `8 / 61 = 0.13114754098360656` |

合计为 21 个 mapping entries、60 个 modified tokens。每阶段 metrics 的 symbol/occurrence coverage 和 effective coverage 均为 `1.0`，plaintext leakage rate 为 `0.0`。

`parameters` 直接作用于 gold 的独立检查中，mapping 必须按声明顺序且只能包含：

```text
WIDTH        declaration [59,64)   references [300,305)
XOR_MASK     declaration [96,104)  references [808,816), [1949,1957)
ACTIVE_BITS  declaration [286,297) references [1467,1478)
RESET_VALUE  declaration [334,345) references [1105,1116), [1997,2008)
```

`bit_index` 不得出现在 `parameters/mapping.json`，只能出现在 `genvars/mapping.json`。

7 阶段串联时，由于前序 category 的改名会改变文件字节长度，后续 mapping 的 offset 以该阶段实际输入为基准，不固定为相对 gold 的 offset；串联验证必须检查 mapping source slices 和 gate edits 精确一致。

## 5. 固定加密命令

```sh
rm -rf /tmp/rtl_obfuscation_t010
mkdir -p /tmp/rtl_obfuscation_t010
CURRENT=rtl_samples/11_supported_obfuscation.sv
for CATEGORY in signals parameters enum_values genvars functions tasks arguments; do
    OUTPUT=/tmp/rtl_obfuscation_t010/$CATEGORY
    conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite encrypt \
      --input "$CURRENT" \
      --output "$OUTPUT/gate.sv" \
      --map "$OUTPUT/mapping.json" \
      --metrics "$OUTPUT/metrics.json" \
      --category "$CATEGORY" \
      --name-length 8 || exit 1
    CURRENT="$OUTPUT/gate.sv"
done
```

每次 stdout 必须符合第 4 节对应 entry/token 数。最终 gate 为：

```text
/tmp/rtl_obfuscation_t010/arguments/gate.sv
```

## 6. 固定门禁

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
  tests.test_supported_integration

conda run -n rtl_obfuscation python -c \
  'import pyslang; t=pyslang.syntax.SyntaxTree.fromFile("/tmp/rtl_obfuscation_t010/arguments/gate.sv"); c=pyslang.ast.Compilation(); c.addSyntaxTree(t); raise SystemExit(any(d.isError() for d in c.getAllDiagnostics()))'
conda run -n rtl_obfuscation verible-verilog-syntax \
  --lang=sv /tmp/rtl_obfuscation_t010/arguments/gate.sv
conda run -n rtl_obfuscation iverilog -g2012 -t null \
  -s sample11_supported_obfuscation \
  /tmp/rtl_obfuscation_t010/arguments/gate.sv
conda run -n rtl_obfuscation python scripts/formal_equivalence.py \
  --gold rtl_samples/11_supported_obfuscation.sv \
  --gate /tmp/rtl_obfuscation_t010/arguments/gate.sv \
  --top sample11_supported_obfuscation
```

全部退出码必须为 0，formal JSON 必须为 `pass`。

## 7. 固定逆向恢复

```sh
mkdir -p /tmp/rtl_obfuscation_t010/restored
CURRENT=/tmp/rtl_obfuscation_t010/arguments/gate.sv
for CATEGORY in arguments tasks functions genvars enum_values parameters signals; do
    OUTPUT=/tmp/rtl_obfuscation_t010/restored/$CATEGORY.sv
    conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite decrypt \
      --input "$CURRENT" \
      --output "$OUTPUT" \
      --map "/tmp/rtl_obfuscation_t010/$CATEGORY/mapping.json" || exit 1
    CURRENT="$OUTPUT"
done
cmp -s rtl_samples/11_supported_obfuscation.sv "$CURRENT"
```

最终 `cmp` 必须退出码 0。

## 8. 测试要求

新增黑盒测试必须至少断言：

- `parameters` 精确 4 entries/10 tokens，普通 localparam 保留，iteration parameter 排除。
- 7 个阶段汇总和 metrics 与第 4 节一致。
- 每个阶段 gate 只等于该阶段 mapping 所描述的 token edits。
- 最终 gate 通过 PySlang 语义解析。
- 逆序 decrypt 后与 gold 字节完全一致。

## 9. 明确不包含

- 新增或合并 category、多 category 单次 CLI、单一合并 mapping/metrics。
- type-dimension parameter 引用、generate body 中除 genvar 外的内部符号引用。
- module、port、instance、generate block label、type parameter 或多文件。
- 修改样例来规避 iteration parameter 过滤。

## 10. 允许修改的文件

```text
rtl_obfuscator/inventory.py
tests/test_supported_integration.py
docs/tasks/T010_supported_categories_integration.md
```

不得修改其他文件。

## 11. 子 Agent 流程

1. 开始前设置 `IN_PROGRESS` 并记录实际 PySlang identity 探测。
2. 只实现第 3 节过滤并新增第 8 节测试。
3. 记录 11 项回归、7 阶段输出、三前端、formal 和逆向 cmp。
4. 完成后设置 `READY_FOR_REVIEW`；不得设置 `ACCEPTED`、commit 或 push。

## 12. Formal verification（子 Agent 完成时填写）

```text
formal_verification: PASS
gold: rtl_samples/11_supported_obfuscation.sv
gate: /tmp/rtl_obfuscation_t010/arguments/gate.sv
top: sample11_supported_obfuscation
command: conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold rtl_samples/11_supported_obfuscation.sv --gate /tmp/rtl_obfuscation_t010/arguments/gate.sv --top sample11_supported_obfuscation
exit_code: 0
result: {"formal_equivalence": "pass", "gate": "/private/tmp/rtl_obfuscation_t010/arguments/gate.sv", "gold": "/Users/lufengchi/Desktop/workspace/rtl_obfuscation/rtl_samples/11_supported_obfuscation.sv", "seq": 5, "top": "sample11_supported_obfuscation"}
```

## 13. 执行记录（子 Agent 更新）

- 2026-07-13：将任务设为 `IN_PROGRESS`；开始执行 PySlang identity 探测，尚未修改实现代码。
- PySlang identity 探测：`WIDTH` `[59,64)` 与 `XOR_MASK` `[96,104)` 为普通 value parameter，`isLocalParam=False, isBodyParam=False`；`ACTIVE_BITS` `[286,297)` 与 `RESET_VALUE` `[334,345)` 为普通 module localparam，`isLocalParam=True, isBodyParam=True`。
- `bit_index` 有一个 `GenvarSymbol` 和四个不同 identity 的 elaborated `ParameterSymbol`；五者均为 buffer `1`、offset `1159`、name `bit_index`，四个 parameter 均为 `isLocalParam=True, isBodyParam=True`。因此只能使用与 `GenvarSymbol` 同 name/buffer/offset 的精确匹配排除 iteration parameter，不能使用 `isBodyParam` 筛选。
- 实现：`_collect_parameters` 在同一次 semantic visit 中收集 `GenvarSymbol`，只从 value parameter 候选中排除与 genvar 同 name/buffer/offset 的 symbol；未使用 `isBodyParam` 排除，普通 localparam 保留。
- 新增 `tests.test_supported_integration`：独立检查 gold parameter 的固定 ranges；串联检查 7 个 category 的汇总、metrics、mapping source slices 和精确 gate edits；检查最终 gate 的 PySlang 语义解析和逆序 decrypt 字节往返。
- 新测试首次因第 14 节记录的 offset 合同歧义失败；主 Agent 澄清合同后调整为独立 gold ranges 检查，后续实现与门禁无失败。

## 14. 偏差或阻塞（子 Agent 更新）

- 合同第 4 节的 parameter 固定 byte ranges 是直接以 gold 为输入时的 ranges；第 5 节串联流程中，`signals` 阶段将不同长度的原名统一改为 8 bytes，所以后续 `parameters/mapping.json` 的 offset 必然漂移。首次集成测试实测 `XOR_MASK` references 为 `[760,768)`、`[1811,1819)`，而直接作用于 gold 时为合同固定的 `[808,816)`、`[1949,1957)`。主 Agent 已确认合同澄清：集成测试断言串联 mapping 与当前阶段 gate 的精确 edit 一致，并另外直接对 gold 运行 `parameters` 以断言第 4 节的固定 ranges。

## 15. 交付证据（子 Agent 更新）

- 变更文件：`rtl_obfuscator/inventory.py`、`tests/test_supported_integration.py`、`docs/tasks/T010_supported_categories_integration.md`。未修改冻结的 RTL sample、README、filelist 或计划文档；仓库中这些文件的已有变更为主 Agent 准备合同时的变更。
- 11 项回归命令：第 6 节固定 `python -m unittest` 命令；退出码 `0`，输出 `Ran 11 tests ... OK`。
- gold 直接 `parameters` 检查：退出码 `0`，stdout `{"files": 1, "mapping_entries": 4, "modified_tokens": 10}`；固定 ranges 实际为 `WIDTH (59,64)/[(300,305)]`、`XOR_MASK (96,104)/[(808,816),(1949,1957)]`、`ACTIVE_BITS (286,297)/[(1467,1478)]`、`RESET_VALUE (334,345)/[(1105,1116),(1997,2008)]`。
- 7 阶段固定加密命令：退出码 `0`；按顺序 stdout 为 `7/24`、`4/10`、`3/8`、`1/5`、`1/2`、`1/2`、`4/9` entries/tokens，合计 `21` entries、`60` tokens。
- 7 阶段 metrics 实际 affected lines 按顺序为 `21/61`、`9/61`、`8/61`、`2/61`、`2/61`、`2/61`、`8/61`；每阶段 symbol/occurrence/effective coverage 均为 `1.0`，plaintext leakage rate 均为 `0.0`。
- 串联 mapping 名称检查：`parameters` 只包含 `WIDTH, XOR_MASK, ACTIVE_BITS, RESET_VALUE`，`genvars` 只包含 `bit_index`；黑盒测试对每个 mapping record 验证输入 source slice，并验证输出只包含 mapping 所描述的 edits。
- PySlang 命令：第 6 节固定命令；退出码 `0`。
- Verible 命令：第 6 节固定命令；退出码 `0`。
- Icarus 命令：第 6 节固定命令；退出码 `0`。
- Yosys formal：见第 12 节；退出码 `0`，JSON `formal_equivalence=pass`。
- 7 阶段固定逆向恢复：退出码 `0`；按逆序 stdout 为 `4/9`、`1/2`、`1/2`、`1/5`、`3/8`、`4/10`、`7/24` entries/tokens；最终 `cmp -s rtl_samples/11_supported_obfuscation.sv /tmp/rtl_obfuscation_t010/restored/signals.sv` 退出码 `0`。
- `git diff --check` 退出码 `0`。未 commit，未 push。
- 未覆盖边界：第 9 节所有项仍不在本任务范围；本任务未扩展 CLI、mapping、metrics、rewrite 或 category。

## 16. 主 Agent 验收结果

- 2026-07-13 16:07 CST：主 Agent 使用独立目录 `/tmp/rtl_obfuscation_t010_main` 完成黑盒验收，状态设置为 `ACCEPTED`。
- 11 项联合回归：退出码 `0`，实际运行 `11` tests，结果 `OK`。
- 7 阶段 encrypt 按顺序输出 `7/24`、`4/10`、`3/8`、`1/5`、`1/2`、`1/2`、`4/9` entries/tokens，总计 21 entries、60 tokens。
- 最终 gate 的 PySlang、Verible、Icarus 均退出码 `0`。
- 主 Agent 独立 Yosys formal：退出码 `0`，结果为 `{"formal_equivalence": "pass", "gate": "/private/tmp/rtl_obfuscation_t010_main/arguments/gate.sv", "gold": "/Users/lufengchi/Desktop/workspace/rtl_obfuscation/rtl_samples/11_supported_obfuscation.sv", "seq": 5, "top": "sample11_supported_obfuscation"}`。
- 7 阶段逆序 decrypt 均成功，最终 restored 与 gold 的 `cmp` 退出码 `0`。
- `git diff --check` 退出码 `0`；实现只修改合同允许文件，冻结样例和索引由主 Agent创建且子 Agent 未修改。
