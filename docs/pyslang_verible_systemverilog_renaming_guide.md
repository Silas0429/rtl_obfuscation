# 使用 PySlang 与 Verible 分析并重命名 SystemVerilog 标识符

本文面向本仓库当前工具环境，目标是先理解语法分析的基本原理，再为后续“按配置选择要混淆的实体”建立清晰边界。当前已验证版本：

```text
PySlang 11.0.0
Verible v0.0-3946-g851d3ff4 (2025-02-17 build)
```

> 重要版本差异：PySlang 11 的发行包名和 Python 导入名都是 `pyslang`，但主要 API 已放入子命名空间，例如 `pyslang.syntax.SyntaxTree` 和 `pyslang.ast.Compilation`。旧资料里的 `import slang` 或 `pyslang.SyntaxTree` 不适用于本环境。

## 1. 先建立正确的工具分工

SystemVerilog 中的同一个 `SymbolIdentifier`，可能是声明、普通引用、模块类型名、instance 名、命名端口名或层次路径的一部分。仅靠文本搜索无法可靠地区分它们。

- **Verible**：适合词法分析、具体语法树（CST）分析、保留源代码结构、获得 token 的字节区间，以及重写前后的快速语法检查。它能回答“这个单词在什么语法结构中”。
- **PySlang syntax API**：提供无损 SystemVerilog 语法树，适合查看声明和表达式的具体语法节点。
- **PySlang semantic AST**：建立 `Compilation` 后进行名字查找、类型检查和 elaboration，适合回答“这个引用实际绑定到哪个声明”。这是可靠重命名最重要的一层。
- **Icarus Verilog / Verible**：可作为重命名后的额外编译、语法回归检查，但不能代替 PySlang 的符号绑定。

推荐的后续实现流程是：

```text
读取源文件
  -> Verible / PySlang syntax 做语法检查
  -> PySlang Compilation 建立声明、作用域和引用绑定
  -> 根据配置筛选允许重命名的符号
  -> 为声明及其每个引用生成 source-range edit
  -> 按字节位置从后往前应用 edit
  -> 再用 PySlang、Verible、Icarus 检查
```

## 2. 可替换项目清单

### 2.1 第一阶段建议支持

这些实体覆盖本仓库已有 RTL 样例，也是较适合最先实现和验证的一组。

| 配置项建议 | 可替换实体 | SystemVerilog 示例 | 常见 PySlang `SymbolKind` | 必须同步修改的位置 | 建议默认值 |
| --- | --- | --- | --- | --- | --- |
| `rename_modules` | module 名 | `module fifo` | `Definition`；elaboration 后也会出现顶层 `Instance` | module 声明、实例化处的模块类型、可能的 `bind`/层次引用 | `false`，常是外部入口 |
| `rename_parameters` | `parameter` / `localparam` | `parameter int WIDTH=8` | `Parameter` | 表达式引用、参数覆盖左侧 `.WIDTH(...)` | `true`；顶层公开参数可排除 |
| `rename_ports` | input/output/inout/ref port | `input logic data_i` | `Port`，并可能有底层 `Variable`/`Net` | 模块内引用、命名连接左侧 `.data_i(...)`、接口/modport 引用 | `false`，默认保留接口 ABI |
| `rename_signals` | module 内部、非 port 的具名 variable 和 net | `logic masked_data`、`reg stored_data`、`wire ready`、`tri shared_bus` | `Variable`、`Net` | 声明以及全部绑定到该 symbol 的赋值、读取、select 和连接引用 | `true` |
| `rename_functions` | function 名 | `function calc_crc` | `Subroutine` | 函数调用、作用域/层次引用 | `true`；DPI/export 除外 |
| `rename_tasks` | task 名 | `task drive_bus` | `Subroutine` | task 调用、作用域/层次引用 | `true`；DPI/export 除外 |
| `rename_arguments` | function/task 形式参数 | `input logic value` | `FormalArgument` | subroutine 内引用、命名实参左侧 | `true` |
| `rename_instances` | module/interface/checker/primitive instance 名 | `child u_child (...)` | `Instance`、`InstanceArray` 等 | 所有层次路径，例如 `u_child.ready` | `true`；外部 testbench 路径可能要求保留 |
| `rename_genvars` | `genvar` | `genvar lane` | `Genvar`；展开后还可能出现迭代 `Parameter` | generate 条件、索引表达式 | `true` |
| `rename_generate_blocks` | 显式 generate block label | `begin : g_lane` | `GenerateBlockArray` / `GenerateBlock` | 层次路径，例如 `g_lane[0].x` | `true`；外部层次引用存在时慎用 |
| `rename_enum_values` | enum 枚举值 | `IDLE, BUSY` | `EnumValue` | case item、比较、赋值、作用域引用 | `true` |

注意两个 PySlang 语义现象：

1. 一个 ANSI port 可能同时表现为 `PortSymbol` 和它背后的 `VariableSymbol` 或 `NetSymbol`。实现时应按语义对象关系去重，不能把它误认为两个独立名字。
2. generate-for 会被 elaboration 成多个实例化的 `GenerateBlock`，但源代码中通常只有一个 label 和一个 `genvar` 声明。重写计划必须按源位置去重，不能因 WIDTH=4 就对同一个 token 修改四次。

`logic` 是数据类型，不是可靠的重命名分类依据。公开配置统一使用 `rename_signals`；实现内部依据 semantic AST 同时收集 module 内部 `VariableSymbol` 和 `NetSymbol`，并排除 port 的 `internalSymbol`。

### 2.2 第二阶段可以支持

| 配置项建议 | 可替换实体 | 主要风险 |
| --- | --- | --- |
| `rename_interfaces` | interface 名、interface instance 名 | 与 module 类似，可能是跨文件公开接口 |
| `rename_packages` | package 名 | 必须同步 `pkg::name`、`import pkg::*`、显式 import |
| `rename_programs` | program 名 | 常被 testbench 或工具脚本直接引用 |
| `rename_types` | typedef、用户类型、type parameter | 必须区分类型名和同名值；语义 AST 更适合 |
| `rename_struct_fields` | struct/union member | 必须同步 member access、assignment pattern key |
| `rename_classes` | class 名 | 需要处理继承、参数化类、factory/字符串注册惯例 |
| `rename_class_members` | property、method、constructor argument | virtual override 和跨类引用需要完整语义关系 |
| `rename_modports` | modport 名及其 port | 会影响 interface port 类型和层次访问 |
| `rename_named_blocks` | 普通过程块 label、fork/join label | label 会形成层次作用域，也可能被 `disable` 引用 |
| `rename_clocking_blocks` | clocking block 名及 clockvar | testbench 和 assertion 中常使用层次引用 |
| `rename_properties_sequences` | property、sequence、let 名 | 需要同步 assertion 引用和形式参数 |
| `rename_covergroups` | covergroup、coverpoint、cross、bin 名 | 覆盖率数据库/脚本可能依赖这些名字 |
| `rename_assertion_labels` | assertion label | 仿真日志和脚本可能把 label 当稳定 ID |
| `rename_checker_names` | checker 定义和 instance | 与 module/instance 重命名类似 |

### 2.3 不应直接作为普通标识符替换

| 项目 | 原因 / 处理建议 |
| --- | --- |
| 关键字和系统名 | `module`、`logic`、`always_ff`、`$display` 等不是用户符号 |
| 数字、字符串、注释 | 字符串可能被外部工具当作协议字段；注释不影响语义，不应随普通 rename 修改 |
| 宏名和宏形参 | `` `define`` 属于预处理层；需要单独的 `rename_macros` 模式，并追踪 include、条件编译和 token paste |
| include 文件名 | 是构建系统接口，不是 HDL 符号 |
| attribute 名/值 | 综合、仿真工具可能识别 `(* keep = "true" *)` 等固定名称 |
| DPI-C import/export 名 | 与 C/C++ ABI 对接；除非同时修改外部代码，否则必须保留 |
| `$unit`、`$root` 及其他标准作用域 | 语言定义的名字，不能替换 |
| 隐式 `genblkN` | 源码中没有可替换 token；添加显式 label 属于结构变换，不是 rename |
| 未解析符号 | 可能来自缺失的 filelist/include/library；在 compilation 完整前不得猜测性替换 |
| 外部可见层次名 | testbench、Tcl、SDC、波形/覆盖率脚本可能依赖；应通过 allowlist/denylist 控制 |

## 3. 为什么不能做全局字符串替换

考虑下面两个模块：

```systemverilog
module child #(
    parameter int WIDTH = 8
) (
    input logic [WIDTH-1:0] din
);
endmodule

module top #(
    parameter int WIDTH = 16
) (
    input logic [WIDTH-1:0] din
);
    child #(
        .WIDTH(WIDTH)
    ) u_child (
        .din(din)
    );
endmodule
```

`.WIDTH(WIDTH)` 中左侧是 `child.WIDTH`，右侧是 `top.WIDTH`；`.din(din)` 也同理。它们文本相同，却是不同作用域中的不同符号。如果配置要求保留顶层 port/parameter、只改 child 的接口，正确结果可能是：

```systemverilog
module m0 #(
    parameter int p0 = 8
) (
    input logic [p0-1:0] i0
);
endmodule

module top #(
    parameter int WIDTH = 16
) (
    input logic [WIDTH-1:0] din
);
    m0 #(
        .p0(WIDTH)
    ) u0 (
        .i0(din)
    );
endmodule
```

这要求工具按“符号身份”而不是按字符串 `WIDTH`/`din` 决定替换。

## 4. 一份覆盖主要实体的替换例子

替换前：

```systemverilog
module parity_lane #(
    parameter int unsigned WIDTH = 4
) (
    input  logic [WIDTH-1:0] input_data,
    output logic [WIDTH-1:0] output_data
);
    logic [WIDTH-1:0] masked_data;

    function automatic logic invert_bit(input logic value);
        return ~value;
    endfunction

    for (genvar bit_index = 0; bit_index < WIDTH; bit_index++) begin : generate_lane
        assign masked_data[bit_index] = invert_bit(input_data[bit_index]);
    end

    lane_sink sink_instance (
        .sink_input  (masked_data),
        .sink_output (output_data)
    );
endmodule
```

假设启用 module、parameter、port、variable、function、argument、genvar、generate block、instance 重命名，映射可以是：

| 类别 | 原名 | 新名 |
| --- | --- | --- |
| module | `parity_lane` | `m0` |
| parameter | `WIDTH` | `p0` |
| port | `input_data` / `output_data` | `i0` / `o0` |
| variable | `masked_data` | `v0` |
| function | `invert_bit` | `f0` |
| argument | `value` | `a0` |
| genvar | `bit_index` | `g0` |
| generate label | `generate_lane` | `gb0` |
| instance | `sink_instance` | `u0` |

替换后：

```systemverilog
module m0 #(
    parameter int unsigned p0 = 4
) (
    input  logic [p0-1:0] i0,
    output logic [p0-1:0] o0
);
    logic [p0-1:0] v0;

    function automatic logic f0(input logic a0);
        return ~a0;
    endfunction

    for (genvar g0 = 0; g0 < p0; g0++) begin : gb0
        assign v0[g0] = f0(i0[g0]);
    end

    lane_sink u0 (
        .sink_input  (v0),
        .sink_output (o0)
    );
endmodule
```

这里没有重命名 `lane_sink`、`sink_input`、`sink_output`，因为假设 child 定义不在当前处理范围内。若错误地只改命名连接左侧，实例将无法绑定；因此“只重命名当前 compilation 中能解析且允许修改其声明的符号”应成为基本规则。

## 5. 命令行实验：先学 Verible

以下命令都从仓库根目录运行：

```sh
cd /Users/lufengchi/Desktop/workspace/rtl_obfuscation
```

### 步骤 1：确认版本与帮助

```sh
conda run -n rtl_obfuscation verible-verilog-syntax --version
conda run -n rtl_obfuscation verible-verilog-syntax --helpfull
```

`--helpfull` 会打印帮助后返回非零状态，Conda 可能额外显示一行 `ERROR ... failed`；这不是 parser 运行失败。

### 步骤 2：只做严格 SystemVerilog-2017 语法检查

```sh
conda run -n rtl_obfuscation verible-verilog-syntax \
  --lang=sv rtl_samples/07_generate_loop.sv
```

成功时通常没有输出，退出码为 0。查看退出码：

```sh
echo $?
```

### 步骤 3：观察 lexer 产生的 token

```sh
conda run -n rtl_obfuscation verible-verilog-syntax \
  --lang=sv --printtokens rtl_samples/06_module_instance.sv
```

你会看到类似：

```text
(#SymbolIdentifier @414-436: "sample06_inverter_cell")
(#SymbolIdentifier @437-454: "inverter_instance")
```

`@start-end` 是源文件中的半开字节区间 `[start, end)`。lexer 只知道两者都是标识符，还不知道前者是 module 类型、后者是 instance。

再比较 `--printrawtokens`，它会包含被 parser 过滤的空白和注释等 token：

```sh
conda run -n rtl_obfuscation verible-verilog-syntax \
  --lang=sv --printrawtokens rtl_samples/06_module_instance.sv
```

### 步骤 4：观察 CST 如何给 token 添加语法上下文

```sh
conda run -n rtl_obfuscation verible-verilog-syntax \
  --lang=sv --printtree rtl_samples/07_generate_loop.sv
```

重点搜索这些节点：

```text
kModuleDeclaration
kParamDeclaration
kPortDeclaration
kDataDeclaration
kLoopGenerateConstruct
kGenerateBlock
```

例如 `WIDTH` 的声明位于 `kParamDeclaration` 下，引用则位于 `kReference`/`kUnqualifiedId` 下；`generate_mask` label 会出现在 generate block 对应的子树中。

### 步骤 5：输出机器可读 JSON

```sh
conda run -n rtl_obfuscation verible-verilog-syntax \
  --lang=sv --export_json --printtree rtl_samples/09_function_call.sv \
  > /tmp/verible_function_tree.json

conda run -n rtl_obfuscation python -m json.tool \
  /tmp/verible_function_tree.json | less
```

JSON 中的 leaf 通常包含 `tag`、`text`、`start`、`end`，适合程序化产生 source edits。`null` child 是 CST 中保留的可选槽位，不代表 JSON 损坏。

### 步骤 6：故意制造错误，理解诊断

不修改仓库文件，在 `/tmp` 生成一个缺少分号的代码：

```sh
printf '%s\n' 'module bad(input logic a)' 'endmodule' > /tmp/verible_bad.sv
conda run -n rtl_obfuscation verible-verilog-syntax \
  --lang=sv --show_diagnostic_context /tmp/verible_bad.sv
```

Verible 会指出 parser 期待 `;` 的位置，并返回非零状态。这个实验说明 lexer 能产生 token，并不等于 token 序列满足语法规则。

## 6. 命令行实验：再学 PySlang syntax API

### 步骤 1：确认包及新命名空间

```sh
conda run -n rtl_obfuscation python -c \
  'import pyslang; print(pyslang.__version__); print(pyslang.__file__); print(pyslang.syntax.SyntaxTree)'
```

### 步骤 2：构建单文件 SyntaxTree 并检查诊断

```sh
conda run -n rtl_obfuscation python -c \
  'import pyslang; t=pyslang.syntax.SyntaxTree.fromFile("rtl_samples/07_generate_loop.sv"); print(t.root.kind); print("diagnostics=", len(t.diagnostics)); print("valid=", t.validate())'
```

预期关键输出：

```text
SyntaxKind.CompilationUnit
diagnostics= 0
valid= True
```

### 步骤 3：遍历无损 syntax tree

```sh
conda run -n rtl_obfuscation python -c \
  'import pyslang; t=pyslang.syntax.SyntaxTree.fromFile("rtl_samples/07_generate_loop.sv"); rows=[]; t.root.visit(lambda n: rows.append((type(n).__name__, n.kind.name, str(n))) or True); print(*rows[:30], sep="\n")'
```

`visit` 会同时访问 syntax node 和 token。回调返回 `True` 表示继续进入子节点。你会依次看到 `CompilationUnitSyntax`、`ModuleDeclarationSyntax`、`ModuleHeaderSyntax`、关键字 token、identifier token 等。这一层和 Verible CST 类似，仍主要描述“代码写成了什么结构”。

### 步骤 4：把 syntax tree 导出为 JSON

```sh
conda run -n rtl_obfuscation python -c \
  'import pyslang; t=pyslang.syntax.SyntaxTree.fromFile("rtl_samples/09_function_call.sv"); open("/tmp/pyslang_function_cst.json", "w").write(t.root.to_json())'

conda run -n rtl_obfuscation python -m json.tool \
  /tmp/pyslang_function_cst.json | less
```

这一步仍是 CST，不会自动告诉你所有同名 identifier 是否引用同一声明。

## 7. 命令行实验：用 PySlang semantic AST 建立符号关系

### 步骤 1：从 SyntaxTree 建立 Compilation

```sh
conda run -n rtl_obfuscation python -c \
  'import pyslang; t=pyslang.syntax.SyntaxTree.fromFile("rtl_samples/09_function_call.sv"); c=pyslang.ast.Compilation(); c.addSyntaxTree(t); r=c.getRoot(); print([(x.name, x.definition.name) for x in r.topInstances]); print("diagnostics=", len(c.getAllDiagnostics()))'
```

调用 `getRoot()` 会触发语义处理/elaboration。该样例的顶层 instance 和 module definition 都叫 `sample09_function_call`，但它们是不同概念：definition 是模块类型，instance 是 elaborated design hierarchy 中的实例。

### 步骤 2：列出 module definitions

```sh
conda run -n rtl_obfuscation python -c \
  'import pyslang; t=pyslang.syntax.SyntaxTree.fromFile("rtl_samples/06_module_instance.sv"); c=pyslang.ast.Compilation(); c.addSyntaxTree(t); print([(d.kind.name, d.name) for d in c.getDefinitions()])'
```

预期能看到：

```text
[('Definition', 'sample06_inverter_cell'),
 ('Definition', 'sample06_module_instance')]
```

### 步骤 3：列出关心的声明符号

```sh
conda run -n rtl_obfuscation python -c \
  'import pyslang; t=pyslang.syntax.SyntaxTree.fromFile("rtl_samples/07_generate_loop.sv"); c=pyslang.ast.Compilation(); c.addSyntaxTree(t); rows=[]; c.getRoot().visit(lambda n: rows.append((n.kind.name, getattr(n,"name",""))) or True); wanted={"Instance","Port","Parameter","Net","Variable","Subroutine","FormalArgument","Genvar","GenerateBlock","GenerateBlockArray"}; print(*[x for x in rows if x[0] in wanted], sep="\n")'
```

这个实验会显示 `WIDTH`、ports、`masked_data`、`bit_index` 和 `generate_mask`。还会看到 generate elaboration 带来的重复节点，这正是实现时需要按声明 identity/source range 去重的原因。

### 步骤 4：观察引用绑定到哪个声明

```sh
conda run -n rtl_obfuscation python -c \
  'import pyslang; t=pyslang.syntax.SyntaxTree.fromFile("rtl_samples/06_module_instance.sv"); c=pyslang.ast.Compilation(); c.addSyntaxTree(t); rows=[]; c.getRoot().visit(lambda n: (rows.append((str(n.syntax), n.symbol.kind.name, n.symbol.name)) or True) if n.kind.name=="NamedValue" else True); print(*rows, sep="\n")'
```

`NamedValueExpression.symbol` 是该引用实际绑定的 symbol。例如表达式中的 `top_input` 会绑定到名为 `top_input` 的 `VariableSymbol`。后续重命名器应收集目标 symbol 的声明位置以及所有绑定到它的 expression source range，而不是搜索同名字符串。

### 步骤 5：一次解析整个 filelist

先看 filelist：

```sh
sed -n '1,40p' rtl_samples/filelist.f
```

由于其中路径相对于 `rtl_samples`，在该目录中运行：

```sh
cd rtl_samples
conda run -n rtl_obfuscation python -c \
  'from pathlib import Path; import pyslang; files=[str(p) for p in sorted(Path(".").glob("*.sv"))]; t=pyslang.syntax.SyntaxTree.fromFiles(files); c=pyslang.ast.Compilation(); c.addSyntaxTree(t); c.getRoot(); print("files=", len(files)); print("definitions=", len(c.getDefinitions())); print("diagnostics=", len(c.getAllDiagnostics()))'
cd ..
```

当前样例集会报告 1 条非 error 的语义诊断：`09_function_call.sv:14` 的 `ArithOpMismatch`。这是 `accumulated_count += function_data[loop_index]` 两侧位宽不同产生的 warning，也正好说明“语法解析成功”和“语义上没有 warning”是两个不同层次。可用 `Diagnostic.isError()` 区分 error 与 warning；重命名回归时应与重命名前的基线比较，而不是武断要求所有既有 warning 都消失。

真实项目必须提供完整 source file、include directory、macro define 和 library 配置。否则语法可能通过，语义绑定仍可能因为 unknown module 或未解析名称而失败。

## 8. 把两种工具放在同一个验证循环中

先对仓库所有 `.sv` 样例做 Verible 语法检查：

```sh
conda run -n rtl_obfuscation verible-verilog-syntax \
  --lang=sv rtl_samples/*.sv
```

再用 PySlang 构建整体语法树：

```sh
conda run -n rtl_obfuscation python -c \
  'from pathlib import Path; import pyslang; fs=[str(p) for p in sorted(Path("rtl_samples").glob("*.sv"))]; t=pyslang.syntax.SyntaxTree.fromFiles(fs); print("files=",len(fs),"parse diagnostics=",len(t.diagnostics)); raise SystemExit(bool(t.diagnostics))'
```

最后用 Icarus Verilog 做一次额外的 SystemVerilog compile check：

```sh
cd rtl_samples
conda run -n rtl_obfuscation iverilog -g2012 -t null -f filelist.f
cd ..
```

三者通过代表“重写后仍能被这些工具接受”，但还不等价于设计行为完全不变。后续应增加仿真等价测试；若有条件，再加入专业 lint、综合和形式等价检查。

## 9. 后续配置格式建议

第一版不要一次实现全部类别，可先用清晰的显式配置：

```yaml
rename:
  modules: false
  parameters: true
  ports: false
  signals: true
  functions: true
  tasks: true
  arguments: true
  instances: true
  genvars: true
  generate_blocks: true
  enum_values: true

preserve:
  names:
    - clk_i
    - rst_ni
  regex:
    - '^debug_.*'
  top_modules:
    - sample10_systemverilog_fsm
```

建议最小实现顺序：

1. 仅分析并打印 inventory，不改文件。
2. 只重命名模块内部 `signals`，先验证 `VariableSymbol`，再加入 `NetSymbol`，并排除 port 底层 symbol。
3. 加入 `Parameter`、`Genvar`、function/task local 和 argument。
4. 加入 instance 与显式 generate label，并测试层次引用。
5. 最后处理 port、module 和跨文件公开名称。

每增加一类，都先用一个最小 `.sv` fixture 验证，再扩展到全部样例。名字生成器还必须避开 SystemVerilog 关键字、同一作用域已有名字、宏名和工具保留名，并保证同一次运行的映射可复现。

## 10. 目前应记住的核心结论

- token/CST 能定位文本和语法角色，semantic AST 才能可靠判断引用属于哪个声明。
- Verible 很适合观察和校验 CST；PySlang `Compilation` 更适合作为重命名决策的语义真相来源。
- 命名端口/参数连接的左右两侧文本可能相同但符号不同。
- port 可能同时呈现为 port 和 variable/net；generate elaboration 可能制造多个语义节点；二者都要求去重。
- 默认保留外部接口名称，只对 compilation 内完整解析且可修改声明的符号做替换。
- 重写使用 source byte range，并从文件末尾向前应用，避免前面的修改使后续 offset 失效。
