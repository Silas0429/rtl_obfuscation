# RTL 改写验证流程

当前产品使用 PySlang 建立 source catalog、semantic owner 和 rewrite gate；产生 rewritten RTL
后，再使用 `scripts/formal_equivalence.py` 做 Yosys 等价证明。mapping range、strict compile、
restore manifest 和 byte identity 是同一交付门禁的一部分。

## 必要门禁

每次产生 rewritten RTL 的交付必须满足：

1. graph/mapping 的每个 declaration 和 occurrence range 与输入字节一致；
2. gate 的 PySlang catalog 与 top overlay 无错误；
3. gate 与 gold 的 physical manifest 顺序和 hash 可审计；
4. restore 后所有 physical files 与输入逐字节相同；
5. metrics coverage 为 1，`plaintext_leakage_rate` 为 0；
6. Yosys 正例退出码为 0，且 JSON 包含 `formal_equivalence=pass`。

功能负例只能从 actual gate 复制后做一处功能修改。它必须保持 strict compile 的 0/0 结果，
Formal 非零，并包含 `unproven` 与 `equiv_status -assert`。不得删除或绕过
`equiv_status -assert`。

## 当前 vNext 流程

产品入口是 `encrypt-vnext`；它发布 actual gate、orchestration report 和 metrics report。
恢复入口是 `decrypt-vnext`，从 report hydration 后调用既有 restore engine：

```sh
conda run -n rtl_obfuscation python scripts/formal_equivalence.py \
  --gold-filelist tests/fixtures/refactor_symbol_graph_parameters/design.f \
  --gold-root tests/fixtures/refactor_symbol_graph_parameters \
  --gate-filelist <actual-gate>/design.f \
  --gate-root <actual-gate> \
  --top parameter_top --seq 5
```

脚本保持 `read_verilog -sv`、`prep`、`equiv_make`、`equiv_simple`、`equiv_induct` 和
`equiv_status -assert` 的证明强度。gold 和 gate 必须使用同一 top、端口形状和 compile context。

恢复时必须校验 report、mapping、gate manifest、range、metrics 和 restored manifest；失败不得
留下部分输出。`--project-root`、显式 filelist 和 single-file 入口都复用同一 vNext pipeline。

## RISC-V-Vector 边界

RISC-V-Vector 专项 Formal 只在活动任务合同明确要求时运行；普通 vNext 回归不得启动它，且不得
修改 RTL fixture。T057 的专用驱动为 `scripts/risc_v_vector_acceptance.py`，通用 view/alignment
API 位于 `rtl_obfuscator/formal_vnext.py`；它们只在该专项验收中组合使用。跳过该专项检查不等于
跳过当前任务实际产生的 rewritten RTL Formal。

## 输入边界

PySlang semantic binding 失败、owner 不明确、range 重叠、未解析层次引用、宏生成范围、复杂
package/class/DPI/bind/clocking/virtual-interface 语义均应 fail-closed。Verible、Icarus 或其他
前端只能作为附加诊断，不能替代 semantic owner 或 Yosys equivalence。
