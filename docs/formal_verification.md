# RTL 改写验证流程

加密成功不代表改写后的 RTL 可交付。当前项目以 PySlang 作为主语义前端，以 Yosys
证明 gold 与 gate 的可观察行为等价；Verible 和 Icarus 可作为附加前端。

## 1. 必要门禁

每次交付依次检查：

1. mapping 中每个声明和引用 range 与 gold 原 identifier 字节一致；
2. 如果请求了 `--file-map-dir`，per-file mapping occurrence 并集等于 global mapping；
3. gate 能由 PySlang compilation 无 error 解析；
4. Yosys formal 返回成功 JSON；
5. decrypt 后每个文件与 gold 字节一致；
6. metrics coverage 为 1，`plaintext_leakage_rate` 为 0。

对 `project-root + top` 的显式 `parameters` rewrite，以上门禁与其他 project-root category
相同：T032 的正例通过 Yosys equivalence，功能变更负例必须在
`equiv_status -assert` 留下未证明 `$equiv`。仅执行 `inspect-project --category parameters`
的 T031 分析不产生 RTL，formal verification 应记录为 `N/A`，不能用 identity comparison
冒充改写正确性。

Verible 和 Icarus 可以增加语法兼容性证据，但不能替代 PySlang 的语义绑定或 Yosys formal。

### 1.1 RISC-V-Vector Formal 调度边界

RISC-V-Vector 的 `formal-view`、`formal-align` 和 Yosys equivalence 属于专门的 RISC-V-Vector
验收链路，不属于普通任务的常规验收或全量回归。普通任务可以运行 RISC-V-Vector 的只读
manifest、closure、PySlang、Verible、Icarus、mapping 和 decrypt 检查，但不得启动其 Formal。

只有活动任务合同明确声明“专门的 RISC-V-Vector Formal 验收”并冻结相应 gold/gate、oracle、
超时和正负例时，子 Agent 和主 Agent 才运行该链路。其他任务不得以跳过 RISC Formal 为由判定
自身 RTL Formal 通过；非 RISC 的 rewritten RTL 仍必须按本节执行 Yosys 正负例。常规全量回归
必须显式排除 `tests.test_risc_v_vector_project_root`，不能用 blanket `unittest discover` 触发
RISC Formal。

## 2. PySlang 前端

多文件 FIFO gate 检查：

```sh
conda run -n rtl_obfuscation python -c 'from pathlib import Path; import pyslang; root=Path("/tmp/rtl_fifo/gate"); c=pyslang.ast.Compilation(); [c.addSyntaxTree(pyslang.syntax.SyntaxTree.fromFile(str(root/p.strip()))) for p in (root/"design.f").read_text().splitlines() if p.strip()]; errors=[d for d in c.getAllDiagnostics() if d.isError()]; print("errors=",len(errors)); raise SystemExit(bool(errors))'
```

PySlang 是改写器与验证流程共同的主前端。若输入 compilation 本身有 error，不应继续生成
或交付 gate。

## 3. Yosys 形式等价

入口是 `scripts/formal_equivalence.py`，当前验证版本为 Yosys 0.53。

单文件：

```sh
conda run -n rtl_obfuscation python scripts/formal_equivalence.py \
  --gold tests/formal/variable_rename/gold.sv \
  --gate tests/formal/variable_rename/gate.sv \
  --top formal_variable_rename
```

多文件 FIFO：

```sh
conda run -n rtl_obfuscation python scripts/formal_equivalence.py \
  --gold-filelist rtl_samples/example_fifo/design.f \
  --gold-root rtl_samples/example_fifo \
  --gate-filelist /tmp/rtl_fifo/gate/design.f \
  --gate-root /tmp/rtl_fifo/gate \
  --top fifo_top
```

默认顺序证明深度为 5，可显式传入 `--seq 5`。成功时退出码为 0，stdout 为一行 JSON：

```json
{"formal_equivalence":"pass","seq":5,"top":"fifo_top"}
```

脚本对 gold 和 gate 对称执行：

```text
read_verilog -sv -formal -defer        # multifile；single-file 不加 -defer
prep -top <top> -flatten
async2sync                             # multifile
memory_map -formal
opt_clean
equiv_make gold gate equiv
hierarchy -top equiv
equiv_struct -icells
equiv_simple -seq 5
equiv_induct -seq 5
equiv_status -assert
```

`equiv_status -assert` 不可删除。只有退出码 0 且 JSON 为 `pass` 才算通过。

### 3.1 RISC-V-Vector formal-only 派生链

`vector_top` 先分别从原工程和真实 gate 生成 260-transform formal view。gate view 随后通过
mapping v4 做 5527 个 lexer-verified identifier alignment。当前 `formal-align` 的 1091/5741/5527
oracle 是 RISC-V-Vector 交付专用门禁，不是任意 project-root mapping 的通用 alignment 命令：

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite formal-view \
  --project-root /tmp/risc/gold --top vector_top \
  --output-dir /tmp/risc/formal-gold --manifest /tmp/risc/formal-gold.json

conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite formal-view \
  --project-root /tmp/risc/gate --top vector_top \
  --output-dir /tmp/risc/formal-gate --manifest /tmp/risc/formal-gate.json

conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite formal-align \
  --gate-dir /tmp/risc/gate \
  --gate-view-dir /tmp/risc/formal-gate \
  --gate-view-manifest /tmp/risc/formal-gate.json \
  --map /tmp/risc/mapping.json \
  --output-dir /tmp/risc/formal-gate-aligned \
  --manifest /tmp/risc/formal-gate-aligned.json
```

`formal-align` 完整验证 product gate、mapping ranges/manifests、gate view transformation manifest、
compile order 和 lexer token kind。它不能接收 gold 路径，只恢复 mapping 中的 identifier spelling。
正例使用 gold view 与 aligned gate view；固定负例只把 `vector_idle_o` 的第一个二元 `&` 改为 `|`，
并要求 `equiv_status -assert` 恰好留下该 cell。两次证明各自保持 600 秒上限。

## 4. 正例与负例

固定正例只改变内部名称：

```sh
conda run -n rtl_obfuscation python scripts/formal_equivalence.py \
  --gold tests/formal/variable_rename/gold.sv \
  --gate tests/formal/variable_rename/gate.sv \
  --top formal_variable_rename
```

固定负例把计数增量从 1 改为 2，必须失败：

```sh
conda run -n rtl_obfuscation python scripts/formal_equivalence.py \
  --gold tests/formal/variable_rename/gold.sv \
  --gate tests/formal/variable_rename/non_equivalent.sv \
  --top formal_variable_rename
```

形式验证脚本发生修改时，正例必须通过、负例必须失败，避免出现流程被弱化或 vacuous pass。

## 5. 解密恢复

mapping v2（显式 filelist）需要 `--source-root`：

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite decrypt-project \
  --gate-dir /tmp/rtl_fifo/gate \
  --source-root rtl_samples/example_fifo \
  --map /tmp/rtl_fifo/mapping.json \
  --output-dir /tmp/rtl_fifo/restored
```

mapping v4（`project-root + top`）不需要 `--source-root`；解密前会校验 gate manifest、mapping
range、gate AST inventory，解密后还会校验恢复后的输入 manifest：

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite decrypt-project \
  --gate-dir /tmp/risc/gate \
  --map /tmp/risc/mapping.json \
  --output-dir /tmp/risc/restored
```

两个版本都应再做逐文件字节比较：

```sh
conda run -n rtl_obfuscation python -c 'from pathlib import Path; g=Path("rtl_samples/example_fifo"); r=Path("/tmp/rtl_fifo/restored"); fs=["fifo_if.sv","fifo_storage.sv","fifo_ctrl.sv","fifo_top.sv"]; assert all((g/f).read_bytes()==(r/f).read_bytes() for f in fs); print("byte-identical")'
```

## 6. Yosys 输入边界

formal 要求 gold/gate 的 top module 名、top port 名、方向和位宽一致，filelist 只列显式 `.sv`
相对路径，设计可由 `prep -flatten` 完整展开且不依赖未提供 blackbox/library。

参数改写的当前支持面是 module value parameter/localparam 及其已验证的 integral expression、
dimension、generate 和 named override 引用；type/package/class/interface/`$unit` parameter、
复杂 parameter 类型、`defparam` 和复杂层次引用仍不在 formal/改写交付范围内。

Yosys 的 SystemVerilog frontend 不是完整语言实现。特别是顶层 interface/modport port 可能被
错误降级或把 member 当作隐式信号；这种情况下即使命令退出 0，也不能将结果视为有效证明。
宏、DPI、class、动态 testbench、自动 assumption/reset model 和 Yosys 无法读取的语法均不在
当前 formal 边界。

遇到这些情况应先缩小或改造验证边界，不能跳过 formal 后宣称 gate 可交付。
