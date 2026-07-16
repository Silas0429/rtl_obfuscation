# RTL Obfuscation

本项目使用 PySlang 对 SystemVerilog 做语义分析，将可确认绑定关系的标识符随机重命名，
同时输出可审计、可逆的 mapping。项目支持单文件和显式 filelist 多文件工程；
`rtl_samples/example_fifo/` 是当前完整交付样例。

FIFO 在当前边界内的固定验收结果为：4 个 `.sv` 文件、19 个 category、79 个重命名对象、
299 个被改写 token，PySlang 前端、Yosys formal 和字节级解密恢复均通过。样例还展示了
内部 interface signal bundle 和 packed struct 作为 function argument 的实际使用。

## 1. 项目结构

```text
rtl_obfuscation/
├── rtl_obfuscator/
│   ├── inventory.py       # PySlang compilation、语义对象和 source range 收集
│   └── rewrite.py         # CLI、随机命名、源码改写、mapping、metrics 和解密
├── scripts/
│   └── formal_equivalence.py
├── rtl_samples/
│   └── example_fifo/      # 四文件同步 FIFO 交付样例
├── tests/                 # 单元测试、语法 fixture、formal 正负例
└── docs/
    ├── systemverilog_renaming_table.md
    ├── formal_verification.md
    ├── future_work.md
    └── tasks/             # 开发任务历史，不是用户使用手册
```

核心数据流：

```text
SystemVerilog/filelist
    -> PySlang Compilation
    -> 按 category 收集声明、语义绑定和字节区间
    -> 分配随机名称并从文件末尾向前应用 source edit
    -> gate RTL + global mapping + per-file mapping + metrics
    -> PySlang/Yosys 验证
    -> 使用 mapping 逆向恢复
```

## 2. 安装与运行环境

项目的 Python 主依赖是 PySlang，当前验收版本为 `11.0.0`：

```sh
python -m pip install pyslang==11.0.0
```

形式等价验证需要安装 Yosys，当前验收版本为 `0.53`。Yosys 是独立 EDA 工具，
需要确保其可执行文件位于 `PATH` 中。

Verible 和 Icarus Verilog 也可以安装，用作附加的 SystemVerilog 语法/展开前端检查；
它们不是主改写链路的依赖。正文以 PySlang 作为唯一语义信息来源，不能用 Verible、
Icarus 或正则表达式替代 PySlang 的符号绑定。

安装后从仓库根目录确认 Python 环境：

```sh
python -c 'import pyslang; print("PySlang import OK")'
```

运行完整回归：

```sh
python -m unittest discover -s tests -v
```

当前基线为 `Ran 33 tests`、`OK`。

## 3. 基本操作

### 3.1 单文件与多文件模式

项目提供两套命令：`encrypt` / `decrypt` 处理一个 `.sv`，
`encrypt-project` / `decrypt-project` 处理一个显式 filelist 工程。

| 对比项 | 单文件模式 | 多文件模式 |
| --- | --- | --- |
| 加密命令 | `encrypt` | `encrypt-project` |
| 解密命令 | `decrypt` | `decrypt-project` |
| 输入 | `--input <file.sv>` | `--filelist <design.f>` + `--source-root <dir>` |
| PySlang 分析 | 只把一个 `.sv` 加入 compilation | filelist 中全部 `.sv` 进入同一 compilation |
| 跨文件绑定 | 不可用 | 可改写 module type、child port、interface 等已支持跨文件引用 |
| Category 参数 | 只传一个 `--category`；可用 `all` | `--category` 可重复，用于组合内部类别和 ABI 类别 |
| Top | 不需要 `--top` | 必须给出 `--top`；保留 top module 和普通 top ports |
| Gate 输出 | `--output <gate.sv>` | `--output-dir <gate-dir>`，按相对路径镜像多个文件 |
| Mapping | version 1，一个文件内的声明和引用 | version 2，包含 `files`、`top` 和跨文件 range |
| Per-file mapping | 不需要 | 可用 `--file-map-dir` 输出全局 mapping 的每文件投影 |
| `--debug <dir>` | 从同一 gold 自动独立运行 13 个 category | 从同一 filelist 自动独立运行 19 个 category |
| 适用场景 | 独立 module、最小复现、单 category debug | 真实 RTL 工程、跨文件 module/interface 关系和最终交付 |

只要设计依赖其他 `.sv` 中的 module、interface 或类型，就应使用多文件
模式。两种模式都不会原地修改 gold，输出路径必须与源码路径分开。

### 3.2 Category 选择

`--category all` 只启用 13 个默认内部类别：

```text
signals parameters enum_values genvars functions tasks arguments instances
generate_blocks typedefs struct_types struct_fields union_fields
```

下面 6 类可能改变模块或 interface ABI，必须显式启用：

```text
modules ports interfaces interface_instances interface_ports modports
```

单文件模式只接受上述 13 类或 `all`。多文件模式可重复传入
`--category`；例如先传 `all`，再显式加入需要的 ABI 类别。
`--debug <directory>` 会自动遍历对应模式的全部 category，debug 时不再传
`--category` 或普通模式的输出参数。

多文件模式始终保留 top module 名和普通 top port 名。若 testbench、SDC、Tcl、
软件模型或其他工程通过名称访问对象，不应开启对应 ABI category。
顶层使用 interface port 时，必须整体保留 interface 名、modport、member 和 top port；
该边界详见第 6 节。完整 category 语义见
[重命名表](docs/systemverilog_renaming_table.md)。

### 3.3 单文件完整流程

以独立样例 `rtl_samples/11_supported_obfuscation.sv` 为例，按“加密→formal→解密”执行。

1. 加密：

   ```sh
   python -m rtl_obfuscator.rewrite encrypt \
     --input rtl_samples/11_supported_obfuscation.sv \
     --output /tmp/rtl_single/gate.sv \
     --map /tmp/rtl_single/mapping.json \
     --metrics /tmp/rtl_single/metrics.json \
     --category all \
     --name-length 8
   ```

   预期摘要为 1 个文件、33 个 mapping entry、90 个 token。该样例覆盖单文件模式的全部
   13 个 category。输出是一个 gate、一个
   version 1 mapping 和一个 metrics。

2. 形式等价：

   ```sh
   python scripts/formal_equivalence.py \
     --gold rtl_samples/11_supported_obfuscation.sv \
     --gate /tmp/rtl_single/gate.sv \
     --top sample11_supported_obfuscation
   ```

   必须退出码为 0，并包含 `"formal_equivalence": "pass"`。

3. 解密并检查字节恢复：

   ```sh
   python -m rtl_obfuscator.rewrite decrypt \
     --input /tmp/rtl_single/gate.sv \
     --output /tmp/rtl_single/restored.sv \
     --map /tmp/rtl_single/mapping.json
   ```

   ```sh
   python -c 'from pathlib import Path; assert Path("rtl_samples/11_supported_obfuscation.sv").read_bytes()==Path("/tmp/rtl_single/restored.sv").read_bytes(); print("byte-identical")'
   ```

### 3.4 多文件样例 `rtl_samples/example_fifo`

多文件操作以 `rtl_samples/example_fifo` 为例。这是一个可综合的同步 FIFO，由 filelist 和四个
SystemVerilog 源文件组成：

```text
rtl_samples/example_fifo/
├── design.f          # 按 compilation 顺序列出下面四个 .sv
├── fifo_if.sv       # 工程内部 interface、interface signals 和 modport 声明
├── fifo_storage.sv  # RAM、parameter、typedef、struct/union、function/task、struct 传参和 generate
├── fifo_ctrl.sv     # FIFO 状态、读写指针、enum、generate 和 storage instance
└── fifo_top.sv      # 顶层标量/向量 ports、内部 interface instance 和 controller instance
```

`design.f` 内容是：

```text
fifo_if.sv
fifo_storage.sv
fifo_ctrl.sv
fifo_top.sv
```

`fifo_top` 对外是普通 ports，`fifo_if` 只在 top 内部实例化。因此本样例可以显式开启 interface 相关
category；`fifo_bus` 的成员实际承载 top 与 controller 之间的 FIFO 控制、数据和状态连接，
它不代表已支持“顶层 interface port”。`fifo_storage` 中的 `extract_payload(view.entry)`
则展示了 `fifo_entry_t` packed struct 作为 function argument 传递。

### 3.5 多文件完整流程

下面按“加密→formal→解密”执行：

1. 加密：

   ```sh
   python -m rtl_obfuscator.rewrite encrypt-project \
     --filelist rtl_samples/example_fifo/design.f \
     --source-root rtl_samples/example_fifo \
     --output-dir /tmp/rtl_fifo/gate \
     --map /tmp/rtl_fifo/mapping.json \
     --metrics /tmp/rtl_fifo/metrics.json \
     --file-map-dir /tmp/rtl_fifo/maps \
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

   预期摘要为 `{"files": 4, "mapping_entries": 79, "modified_tokens": 299}`。输出目录与 gold 分开：

   ```text
   /tmp/rtl_fifo/
   ├── gate/                  # 四个改写后的 .sv 和镜像 design.f
   ├── maps/                  # 每个 .sv 对应的 occurrence mapping
   ├── mapping.json           # 整个工程的 original_name <-> renamed_name
   └── metrics.json           # coverage、leakage 和 affected lines
   ```

2. 形式等价：

   ```sh
   python scripts/formal_equivalence.py \
     --gold-filelist rtl_samples/example_fifo/design.f \
     --gold-root rtl_samples/example_fifo \
     --gate-filelist /tmp/rtl_fifo/gate/design.f \
     --gate-root /tmp/rtl_fifo/gate \
     --top fifo_top
   ```

   必须退出码为 0，并包含 `"formal_equivalence": "pass"`。

3. 解密并检查四个文件：

   ```sh
   python -m rtl_obfuscator.rewrite decrypt-project \
     --gate-dir /tmp/rtl_fifo/gate \
     --source-root rtl_samples/example_fifo \
     --map /tmp/rtl_fifo/mapping.json \
     --output-dir /tmp/rtl_fifo/restored
   ```

   ```sh
   python -c 'from pathlib import Path; g=Path("rtl_samples/example_fifo"); r=Path("/tmp/rtl_fifo/restored"); fs=["fifo_if.sv","fifo_storage.sv","fifo_ctrl.sv","fifo_top.sv"]; assert all((g/f).read_bytes()==(r/f).read_bytes() for f in fs); print("byte-identical")'
   ```

### 3.6 查看加密结果

查看改写后的某个 RTL：

```sh
python -c 'from pathlib import Path; print(Path("/tmp/rtl_fifo/gate/fifo_storage.sv").read_text())'
```

格式化查看全局 mapping、某文件 mapping 和 metrics：

```sh
python -m json.tool /tmp/rtl_fifo/mapping.json
```

```sh
python -m json.tool /tmp/rtl_fifo/maps/fifo_storage.json
```

```sh
python -m json.tool /tmp/rtl_fifo/metrics.json
```

FIFO 的 symbol/occurrence coverage 应为 `1.0`，`plaintext_leakage_rate` 应为 `0.0`。

### 3.7 单文件 debug

debug 只生成分 category 加密结果，不提供 debug 解密。单文件从原始 gold 独立运行 13 个默认 category：

```sh
python -m rtl_obfuscator.rewrite encrypt \
  --input rtl_samples/11_supported_obfuscation.sv \
  --debug /tmp/rtl_single/debug \
  --name-length 8
```

每个 category 输出 `gate.sv`、`mapping.json` 和 `metrics.json`。stdout 是汇总 JSON，其中 `runs` 记录每类的数量。

### 3.8 多文件 debug

FIFO 从同一份 `design.f` 独立运行全部 19 个 category：

```sh
python -m rtl_obfuscator.rewrite encrypt-project \
  --filelist rtl_samples/example_fifo/design.f \
  --source-root rtl_samples/example_fifo \
  --top fifo_top \
  --debug /tmp/rtl_fifo/debug \
  --name-length 8
```

每个 category 输出 `gate/`、`maps/`、`mapping.json` 和 `metrics.json`。每次都基于 gold 重新加密，不会使用前一次运行的 gate。

`--debug` 不能与 `--category`、`--output`、`--output-dir`、`--map`、`--metrics` 或 `--file-map-dir` 混用。如果只想调试一个 category，使用普通模式并传一个 `--category <name>`。

## 4. 替换实现机制

1. `inventory.py` 将 filelist 中的文件加入同一个 `pyslang.ast.Compilation`。
2. 每个 category 只收集符合当前边界的 PySlang symbol；同名字符串不会自动视为同一对象。
3. 声明和普通引用优先通过 `node.symbol is target` 证明绑定；PySlang 未直接暴露 token 时，
   只在已限定语法范围内使用 source range fallback，并核对 gold 字节。
4. 随机名称长度由 `--name-length` 指定，最小为 4；名称避开关键字、已有 identifier 和
   本轮已分配名称。
5. source edit 按字节区间从后向前应用，因此不同长度的新名称不会移动尚未处理的 gold range。
6. 单文件 mapping 使用 version 1；多文件全局 mapping 使用 version 2；per-file mapping 是
   全局 occurrence 的文件投影。
7. 解密会在 gate 上重新定位新名称并逆向应用 mapping，不依赖原始名称的文本搜索。

例如：

```systemverilog
child #(.WIDTH(WIDTH)) u_child (...);
```

左侧 `WIDTH` 绑定 child parameter，右侧 `WIDTH` 绑定当前 module parameter。即使拼写相同，
它们也属于不同 mapping entry。

## 5. 验证加密结果

加密命令成功只表示完成了改写，不表示 gate 已经可交付。至少执行 PySlang 和 Yosys。

PySlang 检查 FIFO gate：

```sh
python -c 'from pathlib import Path; import pyslang; root=Path("/tmp/rtl_fifo/gate"); c=pyslang.ast.Compilation(); [c.addSyntaxTree(pyslang.syntax.SyntaxTree.fromFile(str(root/p.strip()))) for p in (root/"design.f").read_text().splitlines() if p.strip()]; errors=[d for d in c.getAllDiagnostics() if d.isError()]; print("errors=",len(errors)); raise SystemExit(bool(errors))'
```

Yosys 形式等价：

```sh
python scripts/formal_equivalence.py \
  --gold-filelist rtl_samples/example_fifo/design.f \
  --gold-root rtl_samples/example_fifo \
  --gate-filelist /tmp/rtl_fifo/gate/design.f \
  --gate-root /tmp/rtl_fifo/gate \
  --top fifo_top
```

成功时输出包含 `"formal_equivalence": "pass"`。完整流程和限制见
[验证流程](docs/formal_verification.md)。如果已安装 Verible 或 Icarus，还可以把它们作为
附加前端检查，但不能用它们替代 PySlang 或 Yosys formal。

## 6. 当前能力边界

当前可靠覆盖常见 module value parameter/localparam、普通表达式、packed/unpacked
dimension、generate header 和可解析的 named parameter override：

```systemverilog
module fifo #(parameter WIDTH=8, parameter DEPTH=16);
    logic [WIDTH-1:0] memory [0:DEPTH-1];
    child #(.WIDTH(WIDTH)) u_child (...);
endmodule
```

已验证的常见遮蔽包括：不同 module 的同名 parameter、named override 左右同名、module
parameter 与 generate-local genvar 同名、不同 aggregate 类型中的同名 field。

以下输入不在可靠交付范围：

| 边界 | 小例子 | 当前处理建议 |
| --- | --- | --- |
| 顶层 interface port | `module top(bus_if.slave bus);` | 保留 interface 名、modport、member 和 top port；不要启用相关三类 |
| field 与外层 parameter 同名且用于自身 dimension | `logic [WIDTH-1:0] WIDTH;` | 将 field 改成 `payload` 等不同名称 |
| 任意深层 lexical shadow | generate/block 内再次声明 `localparam WIDTH` | 避免同名或先用 debug 单类别验证 |
| type parameter | `parameter type T=logic` | 当前不处理 |
| package/class/interface parameter | `package p; parameter WIDTH=8;` | 当前不处理 |
| `defparam` 或层次 parameter | `defparam u.WIDTH=16;` | 当前不处理 |
| 未解析外部 module | `ip #(.WIDTH(WIDTH)) u();`，但 `ip` 不在 filelist | 把定义加入 compilation 或保留该名称 |
| 宏、include 和库自动发现 | `` `define WIDTH 8 `` | filelist 只接受显式 `.sv`；宏内 identifier 不重命名 |
| 外部层次依赖 | `force dut.u_fifo.count=0;` | 同步维护外部文件，或保留相关对象 |
| DPI、bind、class、clocking、virtual interface | 验证环境公开 API | 当前不处理 |

特别注意：`example_fifo` 的 interface 是 `fifo_top` 内部实例，top 对外仍是普通 ports，
因此不等同于“顶层 module 使用 interface port”。后者已列入
[未来事项](docs/future_work.md)。

## 7. 文档入口

- [SystemVerilog 重命名表](docs/systemverilog_renaming_table.md)：每个 category 的当前语义和边界。
- [验证流程](docs/formal_verification.md)：PySlang、Yosys、解密和正负 formal 基线。
- [未来事项](docs/future_work.md)：未实现能力、工具链限制和推荐扩展顺序。
- [`project-root + top` 路线图](docs/project_root_top_roadmap.md)：计划中的工程发现、top 闭包、
  五类对象加密和 RISC-V-Vector 端到端验收；不代表当前已交付能力。
- `docs/tasks/`：开发与验收历史，仅用于追溯。
