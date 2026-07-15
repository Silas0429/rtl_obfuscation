# RTL Obfuscation 交付边界、项目结构与 FIFO 使用指南

## 1. 交付结论

本项目对能够被当前 PySlang compilation 完整解析的 SystemVerilog 工程，按语义符号身份
生成随机新名称，并同步改写声明和已支持的引用位置。

`rtl_samples/example_fifo/` 已在当前交付边界内完成端到端验证：

```text
SystemVerilog files: 4
rename categories:   19
mapping entries:     77
modified tokens:     292
per-file union:      292 / 292
plaintext leakage:   0.0
decrypt round-trip:  4 / 4 files byte-identical
PySlang/Verible/Icarus/Yosys formal: PASS
```

这里的“完整加密”是指 FIFO 中属于第 3 节支持类别和语法边界的符号全部进入 mapping，
不是指任意 SystemVerilog 语法都能被重命名。复杂遮蔽、宏和 type parameter 等见第 5 节。

## 2. 输入与安全前提

- 输入是 UTF-8 SystemVerilog `.sv` 文件；
- filelist 显式列出文件，路径相对于 `--source-root`；
- 全部文件在同一个 PySlang `Compilation` 中无 error；
- 需要改写的声明和引用都在项目源文件内；
- top module 名和 top ports 保留，作为 formal 和外部调用入口；
- 所有项目命令使用 Conda 环境 `rtl_obfuscation`。

工具不会原地修改 gold。随机名称长度由 `--name-length` 指定且至少为 4；示例使用 8。
新名称不会使用 SystemVerilog 关键字，也不会与 compilation 中已有标识符或本次新名称冲突。

对于第 5 节的不支持输入，当前版本不保证一定在 encrypt 阶段拒绝。因此必须执行 PySlang、
Verible、Icarus 和 Yosys formal，不能只根据 encrypt 退出码判断 gate 可交付。

## 3. 可替换类别与边界

### 3.1 `all` 默认包含的 13 类

| Category | 可替换内容 | 支持的小例子 | 当前边界示例 |
| --- | --- | --- | --- |
| `signals` | module 内部、非 port 的 variable/net | `logic count; assign count=next;` | `input logic count` 属于 `ports` |
| `parameters` | module value parameter 和普通 module localparam | `parameter WIDTH=8; logic [WIDTH-1:0] d;` | 不支持 `parameter type T=logic` |
| `enum_values` | module enum member 声明和已绑定引用 | `enum {IDLE,BUSY}; s=IDLE;` | 不支持 package/class enum |
| `genvars` | generate-for genvar 声明和引用 | `for (genvar i=0; i<N; i++) a[i]=b[i];` | 不保证嵌套 generate/外部层次引用 |
| `functions` | module function 声明和普通调用 | `function next(...); x=next(a);` | 不支持 extern、DPI、package/class function |
| `tasks` | module task 声明和普通调用 | `task clear(...); clear(v);` | 不支持 extern、DPI、层次 task 调用 |
| `arguments` | function/task 形式参数及内部引用 | `function f(input logic value); f=value;` | 不支持 prototype/命名实参左侧 |
| `instances` | 具名 module instance declaration | `child u_child(...);` | 不支持层次路径、instance array、primitive/checker |
| `generate_blocks` | 直属显式 generate block label | `begin : g_lane` | 不支持隐式 `genblkN` 和外部层次路径 |
| `typedefs` | module 普通 typedef 名及已支持引用 | `typedef logic [7:0] word_t; word_t d;` | 不支持 package/class typedef 和全部 cast |
| `struct_types` | module typedef struct/union 类型名 | `typedef struct {...} item_t; item_t x;` | 不支持 package/class scope 和全部嵌套组合 |
| `struct_fields` | struct field 声明和 member access | `logic valid; if (item.valid)` | 不支持 pattern key、constraint、反射/DPI 依赖 |
| `union_fields` | union field 声明和 member access | `logic [8:0] raw; view.raw=v;` | 不支持 tagged union、pattern key、constraint |

`--category all` 只展开以上 13 类。

### 3.2 必须显式启用的 6 类 ABI 类别

| Category | 可替换内容 | 支持的小例子 | 当前边界示例 |
| --- | --- | --- | --- |
| `modules` | 非 top module 名及 instance type | `module child; child u(...);` | top module 保留 |
| `ports` | child port、body 引用和 named connection 左侧 | `input data; child u(.data(x));` | top ports 和外部约束不改 |
| `interfaces` | interface 名及已支持 type 引用 | `interface bus_if; bus_if bus();` | 不支持 virtual interface/package/config |
| `interface_instances` | interface instance 及已支持引用 | `bus_if fifo_bus(); fifo_bus.valid` | 不支持外部层次和 virtual interface 赋值 |
| `interface_ports` | interface member、member access、connection/modport member | `logic valid; bus.valid; modport m(input valid);` | 不支持 clocking block 和复杂 import/export |
| `modports` | modport declaration name | `modport producer(...);` | 当前主要是 declaration-only |

这些类别可能改变 ABI，不会被 `all` 隐式启用。FIFO 完整加密需要显式增加这 6 类。
`modport_ports` 不是独立 category；其中的 signal 归入 `interface_ports`。

## 4. Parameter 的交付能力

### 4.1 已支持

声明、localparam 和普通表达式：

```systemverilog
module fifo #(parameter WIDTH=8, parameter DEPTH=16);
    localparam LAST=DEPTH-1;
    logic [WIDTH-1:0] data;
endmodule
```

Packed/unpacked dimension：

```systemverilog
logic [WIDTH-1:0] word;
logic [WIDTH-1:0] memory [0:DEPTH-1];
```

Named override 左右分别绑定：

```systemverilog
child #(.WIDTH(WIDTH), .DEPTH(DEPTH)) u_child(...);
```

左侧绑定 child parameter，右侧绑定调用方 parameter；相同拼写不会被合并。

Generate-loop 中 parameter 与 genvar 分离：

```systemverilog
for (genvar i=0; i<DEPTH; i++) begin : g_lane
    assign valid[i]=memory[i][0];
end
```

`i` 归入 `genvars`，`DEPTH` 归入 `parameters`。

### 4.2 已识别的常见遮蔽

不同 module 的同名 parameter：

```systemverilog
module child #(parameter WIDTH=8); endmodule
module top #(parameter WIDTH=16);
    child #(.WIDTH(WIDTH)) u();
endmodule
```

child/top 的 `WIDTH` 是不同 mapping entry，override 左右分别改写。

Parameter 与 generate-local genvar 同名：

```systemverilog
module m #(parameter DEPTH=4);
    for (genvar DEPTH=0; DEPTH<2; DEPTH++) begin
        logic [DEPTH:0] local_data;
    end
endmodule
```

module parameter 可改名；generate-local `DEPTH` 的声明、header 和 dimension 不会被
parameter collector 误改。

不同 aggregate 类型中的同名 field：

```systemverilog
typedef struct { logic valid; } request_t;
typedef struct { logic valid; } response_t;
```

两个 `valid` 属于不同类型作用域，不合并。

## 5. 不支持或不保证识别的边界

### 5.1 Parameter 与 field 同名且出现在该 field 自身 dimension

```systemverilog
module m #(parameter WIDTH=8);
    typedef struct packed {
        logic [WIDTH-1:0] WIDTH;
    } item_t;
endmodule
```

dimension 中第一个 `WIDTH` 应绑定外层 parameter，第二个是 field。当前 PySlang 11 在该
FieldSymbol API 上没有直接暴露完整 dimension expression；本版本不保证这种刻意同名写法。
请把 field 改成 `payload` 等其他名称。

### 5.2 任意嵌套 lexical shadow

```systemverilog
module m #(parameter WIDTH=8);
    if (1) begin : g
        localparam WIDTH=2;
        logic [WIDTH-1:0] local_data;
    end
endmodule
```

module parameter、generate-local localparam 和更深 block symbol 的任意组合不属于完整保证。

### 5.3 Type parameter

```systemverilog
module m #(parameter type T=logic [7:0]) (input T data);
```

`type_parameters` 未实现；当前 Yosys 0.53 也不能读取项目现有 type-parameter formal fixture。

### 5.4 Package、class、interface parameter

```systemverilog
package cfg_pkg; parameter int WIDTH=8; endpackage
```

`parameters` 只保证 module value parameter 和普通 module localparam。

### 5.5 `defparam` 和层次 parameter

```systemverilog
defparam u_child.WIDTH=16;
assign x=u_child.WIDTH;
```

不收集 `defparam` 左侧或外部层次 parameter path。

### 5.6 未解析外部 module 的 named override

```systemverilog
external_ip #(.WIDTH(WIDTH)) u_ip(...);
```

若 `external_ip` 未加入同一 compilation，工具无法证明左侧 `WIDTH` 的归属。

### 5.7 宏和自动发现

```systemverilog
`define DECL_WIDTH 8
parameter WIDTH=`DECL_WIDTH;
```

不重命名宏中的 identifier，也不自动发现 include、define、library 或嵌套 filelist。

### 5.8 外部层次、约束和验证环境

```systemverilog
force dut.u_fifo.count='0; // testbench/Tcl/SDC 中的外部引用
```

工具只改输入 RTL，不更新 testbench、SDC、Tcl、波形脚本或软件模型。存在外部 ABI 依赖时
应保留对应类别。

## 6. 项目结构与数据流

```text
rtl_obfuscation/
├── rtl_obfuscator/
│   ├── inventory.py       # Compilation、category collector、symbol/range
│   └── rewrite.py         # CLI、随机命名、source edit、mapping、metrics、decrypt
├── scripts/formal_equivalence.py
├── rtl_samples/example_fifo/
├── tests/                 # fixture、formal 正负例、unittest
└── docs/                  # 设计、任务历史和本交付指南
```

```text
design.f -> PySlang Compilation -> collectors -> mapping v2
         -> per-file source edits -> gate/maps/metrics
         -> frontend + formal + decrypt byte comparison
```

`inventory.py` 决定可改写的语义符号和 source range；`rewrite.py` 分配名称、应用 edit、
输出审计文件并逆向恢复。

## 7. 环境与完整回归

从仓库根目录执行：

```sh
conda run -n rtl_obfuscation python -m unittest discover -s tests -v
```

交付基线为 `Ran 30 tests`、`OK`。当前环境不使用 pytest。

查看 CLI：

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite --help
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite encrypt-project --help
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite decrypt-project --help
```

## 8. 完整加密 `rtl_samples/example_fifo`

请选择一个新的输出目录，然后从同一份 gold 一次完成 19 类加密：

```sh
OUT=/tmp/rtl_obfuscation_fifo_delivery
mkdir -p "$OUT"

conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite encrypt-project \
  --filelist rtl_samples/example_fifo/design.f \
  --source-root rtl_samples/example_fifo \
  --output-dir "$OUT/gate" \
  --map "$OUT/mapping.json" \
  --metrics "$OUT/metrics.json" \
  --file-map-dir "$OUT/maps" \
  --top fifo_top \
  --category all \
  --category modules \
  --category ports \
  --category interfaces \
  --category interface_instances \
  --category interface_ports \
  --category modports \
  --name-length 8
```

预期 stdout：

```json
{"files": 4, "mapping_entries": 77, "modified_tokens": 292}
```

输出结构：

```text
$OUT/
├── gate/
│   ├── design.f
│   ├── fifo_if.sv
│   ├── fifo_storage.sv
│   ├── fifo_ctrl.sv
│   └── fifo_top.sv
├── maps/
│   ├── fifo_if.json
│   ├── fifo_storage.json
│   ├── fifo_ctrl.json
│   └── fifo_top.json
├── mapping.json
└── metrics.json
```

## 9. 查看加密结果

查看和对比某个 RTL：

```sh
sed -n '1,220p' "$OUT/gate/fifo_storage.sv"
diff -u rtl_samples/example_fifo/fifo_storage.sv \
  "$OUT/gate/fifo_storage.sv"
```

`diff` 找到差异时退出码为 1是正常行为。

查看全局 original-name/renamed-name mapping：

```sh
conda run -n rtl_obfuscation python -m json.tool "$OUT/mapping.json"
```

只打印名称对应关系：

```sh
conda run -n rtl_obfuscation python -c \
  'import json,sys; m=json.load(open(sys.argv[1])); [print(e["category"], e["scope"], e["original_name"], "->", e["renamed_name"]) for e in m["entries"]]' \
  "$OUT/mapping.json"
```

查看某个文件自己的 occurrence 审计投影和全局 metrics：

```sh
conda run -n rtl_obfuscation python -m json.tool \
  "$OUT/maps/fifo_storage.json"
conda run -n rtl_obfuscation python -m json.tool \
  "$OUT/metrics.json"
```

FIFO 应满足：

```text
symbols.coverage       = 1.0
occurrences.coverage   = 1.0
plaintext_leakage_rate = 0.0
effective_coverage     = 1.0
```

随机名称每次运行可能不同。验收比较 mapping 数量、source range、唯一性、合法性和功能，
不比较具体随机字符串。

## 10. 验证加密结果

PySlang：

```sh
conda run -n rtl_obfuscation python -c \
  'import pathlib,pyslang,sys; root=pathlib.Path(sys.argv[1]); c=pyslang.ast.Compilation(); [c.addSyntaxTree(pyslang.syntax.SyntaxTree.fromFile(str(root/x.strip()))) for x in (root/"design.f").read_text().splitlines() if x.strip()]; errors=[d for d in c.getAllDiagnostics() if d.isError()]; print(f"errors={len(errors)}"); raise SystemExit(bool(errors))' \
  "$OUT/gate"
```

Verible 和 Icarus：

```sh
conda run -n rtl_obfuscation verible-verilog-syntax --lang=sv \
  "$OUT/gate/fifo_if.sv" "$OUT/gate/fifo_storage.sv" \
  "$OUT/gate/fifo_ctrl.sv" "$OUT/gate/fifo_top.sv"

conda run -n rtl_obfuscation iverilog -g2012 -t null -s fifo_top \
  "$OUT/gate/fifo_if.sv" "$OUT/gate/fifo_storage.sv" \
  "$OUT/gate/fifo_ctrl.sv" "$OUT/gate/fifo_top.sv"
```

Icarus 可能打印 `constant selects in always_* processes` 的 `sorry` 提示；固定 FIFO 中该提示
不影响退出码 0。

Yosys formal：

```sh
conda run -n rtl_obfuscation python scripts/formal_equivalence.py \
  --gold-filelist rtl_samples/example_fifo/design.f \
  --gold-root rtl_samples/example_fifo \
  --gate-filelist "$OUT/gate/design.f" \
  --gate-root "$OUT/gate" \
  --top fifo_top
```

预期包含：

```json
{"formal_equivalence": "pass", "seq": 5, "top": "fifo_top"}
```

## 11. 解密和字节级恢复

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite decrypt-project \
  --gate-dir "$OUT/gate" \
  --source-root rtl_samples/example_fifo \
  --map "$OUT/mapping.json" \
  --output-dir "$OUT/restored"

cmp -s rtl_samples/example_fifo/fifo_if.sv "$OUT/restored/fifo_if.sv"
cmp -s rtl_samples/example_fifo/fifo_storage.sv "$OUT/restored/fifo_storage.sv"
cmp -s rtl_samples/example_fifo/fifo_ctrl.sv "$OUT/restored/fifo_ctrl.sv"
cmp -s rtl_samples/example_fifo/fifo_top.sv "$OUT/restored/fifo_top.sv"
```

四条 `cmp` 均退出 0表示恢复文件与 gold 字节完全一致。mapping 文件是恢复原名的必要依据。

## 12. 单类别 debug 加密

debug 必须每次从原始 FIFO gold 开始，不能把前一个 category 的 gate 作为下一个输入。
下面只启用 `parameters`：

```sh
DEBUG="$OUT/debug/parameters"
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite encrypt-project \
  --filelist rtl_samples/example_fifo/design.f \
  --source-root rtl_samples/example_fifo \
  --output-dir "$DEBUG/gate" \
  --map "$DEBUG/mapping.json" \
  --metrics "$DEBUG/metrics.json" \
  --file-map-dir "$DEBUG/maps" \
  --top fifo_top \
  --category parameters \
  --name-length 8
```

预期：

```json
{"files": 4, "mapping_entries": 9, "modified_tokens": 51}
```

19 类 debug 固定摘要：

| Category | Entries | Tokens | Category | Entries | Tokens |
| --- | ---: | ---: | --- | ---: | ---: |
| `signals` | 14 | 67 | `parameters` | 9 | 51 |
| `enum_values` | 3 | 6 | `genvars` | 2 | 10 |
| `functions` | 1 | 4 | `tasks` | 1 | 2 |
| `arguments` | 3 | 7 | `instances` | 2 | 2 |
| `generate_blocks` | 2 | 2 | `typedefs` | 2 | 6 |
| `struct_types` | 2 | 4 | `struct_fields` | 2 | 4 |
| `union_fields` | 2 | 6 | `modules` | 2 | 4 |
| `ports` | 17 | 59 | `interfaces` | 1 | 2 |
| `interface_instances` | 1 | 15 | `interface_ports` | 9 | 39 |
| `modports` | 2 | 2 |  |  |  |

批量生成所有 debug 输出：

```sh
for CATEGORY in \
  signals parameters enum_values genvars functions tasks arguments instances \
  generate_blocks typedefs struct_types struct_fields union_fields modules ports \
  interfaces interface_instances interface_ports modports
do
  DEBUG="$OUT/debug/$CATEGORY"
  conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite encrypt-project \
    --filelist rtl_samples/example_fifo/design.f \
    --source-root rtl_samples/example_fifo \
    --output-dir "$DEBUG/gate" \
    --map "$DEBUG/mapping.json" \
    --metrics "$DEBUG/metrics.json" \
    --file-map-dir "$DEBUG/maps" \
    --top fifo_top \
    --category "$CATEGORY" \
    --name-length 8 || exit 1
done
```

每个 `$OUT/debug/<category>/` 都包含独立 gate、global mapping、metrics 和四个 per-file
mapping，可按第 9—11 节检查。

## 13. 交付检查清单

1. 输入 filelist 的所有 `.sv` 均能被 PySlang compilation 无 error 解析；
2. encrypt 的 files/entries/tokens 与项目审计结果一致；
3. 每个 mapping range 对应 gold 中的原 identifier；
4. per-file occurrence 并集等于 global mapping；
5. coverage 为 1，`plaintext_leakage_rate` 为 0；
6. gate 通过 PySlang、Verible、Icarus；
7. Yosys 返回 `formal_equivalence=pass`；
8. decrypt 后所有 `.sv` 与 gold 字节一致；
9. 输入不依赖第 5 节的未支持遮蔽或外部 ABI；
10. 妥善保存 mapping，否则无法可靠恢复原名。

只满足“生成了 gate”不足以交付；frontend、formal 和 decrypt 是正确性流程的一部分。
