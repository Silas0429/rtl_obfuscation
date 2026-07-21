# RTL Obfuscation

本项目使用 PySlang 对 SystemVerilog 做语义分析，将可确认绑定关系的标识符随机重命名，
同时输出可审计、可逆的 mapping。项目支持单文件、显式 filelist 多文件加密，以及
`project-root + top` 的自动工程发现、依赖闭包、严格编译、AST inventory 和 13 类 canonical
默认 profile。T031/T032 已为 project-root 增加 module parameter/localparam inventory 和显式
parameter rewrite；T035 统一了 filelist/project-root 的 default/manual profile、ownership 和
bounded closure。filelist 手动 multi/ABI category 现在使用显式 `--top` 建立 bounded closure，
单文件入口仍以 `CATEGORY_REQUIRES_PROJECT_ROOT` fail-closed。
`rtl_samples/example_fifo/` 和 `rtl_samples/RISC-V-Vector/` 是当前完整交付样例。

FIFO 在当前默认 filelist profile 下的固定验收结果为：4 个 `.sv` 文件、13 个 category、44 个重命名对象、
170 个被改写 token，PySlang 前端和字节级解密恢复均通过。样例还展示了
内部 interface signal bundle 和 packed struct 作为 function argument 的实际使用。
RISC-V-Vector 的 `vector_top` 固定闭包为 19 个文件、17 个 module、1091 个对象和 5741 个
identifier occurrences；其 formal-view/formal-align 和 Yosys formal 只在专门的 RISC 验收任务中执行。

## 1. 项目结构

```text
rtl_obfuscation/
├── rtl_obfuscator/
│   ├── inventory.py       # PySlang compilation、语义对象和 source range 收集
│   ├── project.py         # project-root 发现、依赖闭包、严格编译和报告
│   ├── formal_view.py     # AST-driven formal view 和 identifier-only alignment
│   └── rewrite.py         # CLI、随机命名、源码改写、mapping、metrics 和解密
├── scripts/
│   ├── formal_equivalence.py
│   └── t029_acceptance.py
├── rtl_samples/
│   ├── example_fifo/      # 四文件同步 FIFO 交付样例
│   └── RISC-V-Vector/     # vector_top 真实工程交付样例
├── tests/                 # 单元测试、语法 fixture、formal 正负例
└── docs/
    ├── systemverilog_renaming_table.md
    ├── formal_verification.md
    ├── future_work.md
    └── tasks/             # 开发任务历史，不是用户使用手册
```

核心数据流：

```text
SystemVerilog/filelist/project-root+top
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
conda run -n rtl_obfuscation python -m pip install pyslang==11.0.0
```

形式等价验证需要安装 Yosys，当前验收版本为 `0.53`。Yosys 是独立 EDA 工具，
需要确保其可执行文件位于 `PATH` 中。

Verible 和 Icarus Verilog 也可以安装，用作附加的 SystemVerilog 语法/展开前端检查；
它们不是主改写链路的依赖。正文以 PySlang 作为唯一语义信息来源，不能用 Verible、
Icarus 或正则表达式替代 PySlang 的符号绑定。

安装后从仓库根目录确认 Python 环境：

```sh
conda run -n rtl_obfuscation python -c 'import pyslang; print("PySlang import OK")'
```

运行非 RISC 常规回归时必须使用显式测试清单，排除
`tests.test_risc_v_vector_project_root`；不要用会自动发现该模块的 blanket discovery：

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_all_category_rewrite tests.test_debug_mode tests.test_enum_value_rewrite \
  tests.test_example_fifo_project tests.test_formal_equivalence \
  tests.test_genvar_rewrite tests.test_hierarchy_name_rewrite \
  tests.test_interface_member_rewrite tests.test_interface_rewrite \
  tests.test_localparam_rewrite tests.test_module_port_rewrite \
  tests.test_multi_signal_rewrite tests.test_multifile_project \
  tests.test_parameter_dimension_rewrite tests.test_project_regression \
  tests.test_project_root_inspect tests.test_project_root_low_risk \
  tests.test_project_root_parameter_rewrite tests.test_project_root_parameters \
  tests.test_project_root_rewrite tests.test_signal_net_rewrite \
  tests.test_struct_field_rewrite tests.test_struct_type_rewrite \
  tests.test_subroutine_rewrite tests.test_supported_integration \
  tests.test_t033_impact_category tests.test_t034_single_file_default_profile \
  tests.test_t035_profile_unification tests.test_typedef_rewrite \
  tests.test_union_field_rewrite tests.test_value_parameter_rewrite \
  tests.test_variable_inventory tests.test_variable_ranges tests.test_variable_rewrite -v
```

当前 T035 非 RISC 基线为 `Ran 106 tests`、`OK`。

## 3. 基本操作

### 3.1 单文件与多文件模式

项目提供三种输入工作流：`encrypt` / `decrypt` 处理一个 `.sv`；
`encrypt-project` / `decrypt-project` 既可处理显式 filelist，也可从 `project-root + top`
自动建立闭包。

| 对比项 | 单文件模式 | 显式 filelist 模式 | `project-root + top` 模式 |
| --- | --- | --- | --- |
| 加密命令 | `encrypt` | `encrypt-project` | `encrypt-project` |
| 解密命令 | `decrypt` | `decrypt-project` | `decrypt-project` |
| 输入 | `--input <file.sv>` | `--filelist <design.f>` + `--source-root <dir>` | `--project-root <dir>` + `--top <module>` |
| PySlang 分析 | 单个 `.sv` | filelist 中全部 `.sv` | 自动发现依赖，只严格编译 top 闭包 |
| Category 参数 | 一个底层 category 或 `all` | 默认 profile 为 13 个 canonical category；手动 profile 支持 19 个 canonical category 与 `struct`/`interface` alias | 默认同一 13 类；手动 profile 支持同一套 19 类 |
| Top | 不需要 | 必须提供，保留 top module 和普通 top ports | 必须提供，保留 top module、普通 top ports 和 top ABI |
| Gate 输出 | 一个文件 | 镜像 filelist 文件 | 只镜像闭包文件并生成 `design.f` |
| Mapping | version 1 | 默认兼容 version 2；手动 profile version 4 | 默认兼容 version 3；手动 profile version 4 |
| Per-file mapping | 不需要 | 可选 | 可选；不生成无 occurrence 的 header 空映射 |
| `--debug <dir>` | 独立运行 13 类 | 独立运行 13 个默认 category | 独立运行 13 个默认 canonical category |
| 适用场景 | 独立 module、最小复现 | 已有可靠 filelist 的工程 | 只知道工程根目录和 top 的工程 |

只要设计依赖其他 `.sv` 中的 module、interface 或类型，就应使用 filelist 或
`project-root + top` 模式。三种模式都不会原地修改 gold，输出路径必须与源码路径分开。

### 3.2 Category 选择

`--category all` 只启用以下 13 个默认 canonical category：

```text
signals parameters enum_values genvars functions tasks arguments instances
generate_blocks typedefs struct_types struct_fields union_fields
```

下面 6 类可能改变模块或 interface ABI，必须显式启用：

```text
modules ports interfaces interface_instances interface_ports modports
```

单文件模式只接受上述 13 类或 `all`；选择 multi/ABI category 会以
`CATEGORY_REQUIRES_PROJECT_ROOT` 稳定拒绝。filelist 和 project-root 都接受 19 个 canonical
category，以及 `struct`/`interface` alias；filelist 手动 profile 会在 filelist 内以 `--top`
建立 bounded closure，closure 外文件只镜像并记录 `out_of_top_closure`。

`project-root + top` 使用共享 canonical registry，也接受 `all` 和 alias：

| project-root 工作流 | 用户可选集合 | 当前实际行为 |
| --- | --- | --- |
| 普通模式省略 `--category` 或选择 `all` | 13 个默认 canonical category | 自动发现 top closure |
| 普通模式显式选择 | 19 个 canonical category 与两个 alias | 选择 multi/ABI 或 alias 时为 manual profile |
| `--debug` | 13 个默认 canonical category | 独立运行 13 组 |

两种多文件入口都可重复传入 `--category`；`struct` 展开为
`struct_types + struct_fields`，`interface` 展开为
`interfaces + interface_instances + interface_ports + modports`。debug 时不再传
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
   conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite encrypt \
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
   conda run -n rtl_obfuscation python scripts/formal_equivalence.py \
     --gold rtl_samples/11_supported_obfuscation.sv \
     --gate /tmp/rtl_single/gate.sv \
     --top sample11_supported_obfuscation
   ```

   必须退出码为 0，并包含 `"formal_equivalence": "pass"`。

3. 解密并检查字节恢复：

   ```sh
   conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite decrypt \
     --input /tmp/rtl_single/gate.sv \
     --output /tmp/rtl_single/restored.sv \
     --map /tmp/rtl_single/mapping.json
   ```

   ```sh
   conda run -n rtl_obfuscation python -c 'from pathlib import Path; assert Path("rtl_samples/11_supported_obfuscation.sv").read_bytes()==Path("/tmp/rtl_single/restored.sv").read_bytes(); print("byte-identical")'
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
   conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite encrypt-project \
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
   conda run -n rtl_obfuscation python scripts/formal_equivalence.py \
     --gold-filelist rtl_samples/example_fifo/design.f \
     --gold-root rtl_samples/example_fifo \
     --gate-filelist /tmp/rtl_fifo/gate/design.f \
     --gate-root /tmp/rtl_fifo/gate \
     --top fifo_top
   ```

   必须退出码为 0，并包含 `"formal_equivalence": "pass"`。

3. 解密并检查四个文件：

   ```sh
   conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite decrypt-project \
     --gate-dir /tmp/rtl_fifo/gate \
     --source-root rtl_samples/example_fifo \
     --map /tmp/rtl_fifo/mapping.json \
     --output-dir /tmp/rtl_fifo/restored
   ```

   ```sh
   conda run -n rtl_obfuscation python -c 'from pathlib import Path; g=Path("rtl_samples/example_fifo"); r=Path("/tmp/rtl_fifo/restored"); fs=["fifo_if.sv","fifo_storage.sv","fifo_ctrl.sv","fifo_top.sv"]; assert all((g/f).read_bytes()==(r/f).read_bytes() for f in fs); print("byte-identical")'
   ```

### 3.6 查看加密结果

查看改写后的某个 RTL：

```sh
conda run -n rtl_obfuscation python -c 'from pathlib import Path; print(Path("/tmp/rtl_fifo/gate/fifo_storage.sv").read_text())'
```

格式化查看全局 mapping、某文件 mapping 和 metrics：

```sh
conda run -n rtl_obfuscation python -m json.tool /tmp/rtl_fifo/mapping.json
```

```sh
conda run -n rtl_obfuscation python -m json.tool /tmp/rtl_fifo/maps/fifo_storage.json
```

```sh
conda run -n rtl_obfuscation python -m json.tool /tmp/rtl_fifo/metrics.json
```

FIFO 的 symbol/occurrence coverage 应为 `1.0`，`plaintext_leakage_rate` 应为 `0.0`。

### 3.7 单文件 debug

debug 只生成分 category 加密结果，不提供 debug 解密。单文件从原始 gold 独立运行 13 个默认 category：

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite encrypt \
  --input rtl_samples/11_supported_obfuscation.sv \
  --debug /tmp/rtl_single/debug \
  --name-length 8
```

每个 category 输出 `gate.sv`、`mapping.json` 和 `metrics.json`。stdout 是汇总 JSON，其中 `runs` 记录每类的数量。

### 3.8 多文件 debug

FIFO 从同一份 `design.f` 独立运行全部 13 个默认 category：

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite encrypt-project \
  --filelist rtl_samples/example_fifo/design.f \
  --source-root rtl_samples/example_fifo \
  --top fifo_top \
  --debug /tmp/rtl_fifo/debug \
  --name-length 8
```

每个 category 输出 `gate/`、`maps/`、`mapping.json` 和 `metrics.json`。每次都基于 gold 重新加密，不会使用前一次运行的 gate。

`--debug` 不能与 `--category`、`--output`、`--output-dir`、`--map`、`--metrics` 或 `--file-map-dir` 混用。如果只想调试一个 category，使用普通模式并传一个 `--category <name>`。

### 3.9 `project-root + top` 自动工程流程

`inspect-project` 从工程目录递归发现 `.sv/.svh`，唯一定位 top，解析 active include、宏和
compilation-unit 类型依赖，只严格编译 top 闭包，并输出共享 13 个 canonical category 的 AST
inventory。T035 还统一支持 19 个 canonical category、`struct`/`interface` alias、manual
profile、top ABI preserved/skipped 清单和 mapping v4；旧 mapping v1/v2/v3 继续只读解密兼容：

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite inspect-project \
  --project-root rtl_samples/example_fifo \
  --top fifo_top \
  --report /tmp/fifo-project/inspect.json
```

可重复使用 `--include-dir`、`--define NAME[=VALUE]` 和共享 registry 中的 19 个 canonical
category，另支持 `struct`/`interface` alias。省略 category 或选择 `all` 时分析 13 个默认类；
`struct` 展开为 struct type/field，`interface` 展开为 interface definition/instance/member/
modport。top module、top ports、top parameter 和 top ABI 类型始终进入 preserved 清单；default
profile 只改写 classification 标为 `single_module/internal` 的 parameter，manual profile 可在
已确认 closure 内处理跨 module parameter override。

成功时退出码为 0，报告包含候选文件、定义索引、include/macro 依赖、reachable modules/
interfaces/files、严格编译诊断和精确 source ranges；同时提供独立的 classification section，
报告 `single_module`、`multi_module`、`top_abi` profile 的数量、ownership 和可审计 source ranges。
缺失或歧义 top/module/include/macro 时
退出码为 1，同时生成带稳定错误码的 `status=error` 报告。

直接加密同一 top 闭包：

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite encrypt-project \
  --project-root rtl_samples/example_fifo \
  --top fifo_top \
  --output-dir /tmp/fifo-project/gate \
  --map /tmp/fifo-project/mapping.json \
  --metrics /tmp/fifo-project/metrics.json \
  --file-map-dir /tmp/fifo-project/maps \
  --name-length 8
```

省略 `--category` 默认启用 13 个 canonical category；该 FIFO project-root 样例固定摘要为
4 files / 38 entries / 127 tokens。gate 只包含 top 闭包和生成的 `design.f`，默认 mapping
version 3 记录原/gate manifest、编译上下文、精确 ranges 和 preserved top ABI；manual profile
使用 mapping version 4。解密不需要原工程路径：

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite decrypt-project \
  --gate-dir /tmp/fifo-project/gate \
  --map /tmp/fifo-project/mapping.json \
  --output-dir /tmp/fifo-project/restored
```

若只需某一组，可重复传入 `--category`；19 个 canonical category 均可显式选择，并可使用
`struct`/`interface` alias。选择 multi/ABI category、alias 或混合 profile 后，改写范围限制在
确认的 top closure 内；filelist closure 外文件只镜像并记录 `out_of_top_closure`。debug 模式会
从同一 gold 独立运行 13 个默认 category。
RISC-V-Vector/vector_top 的固定组合摘要为 19 files / 1091 entries / 5741 tokens，其中
ports 为 348 entries / 1853 tokens；该 T029 固定组合未选择 `parameters`，因此 parameter、top
module、top ports 和 top ABI 仍保持不变。

### 3.10 RISC-V-Vector `project-root + top` 完整流程

本节是专门 RISC-V-Vector 验收任务的历史/专项流程，不属于 T035 常规 Formal 或非 RISC
全量回归；T035 只保留 RISC closure inspect 证据。

`rtl_samples/RISC-V-Vector/` 是一个真实的多文件 SystemVerilog 向量处理器 datapath 样例。
以 `vector_top` 为 top 时，工程目录中有 56 个候选 `.sv/.svh` 文件，实际 top 闭包为 19 个文件、
17 个 module；`vector_simulator/`、`sva/` 以及不可达 RTL 不会进入 gate filelist。T029 固定的五组
project-root category 结果是 1091 个 eligible symbol、5741 个 identifier occurrence；该固定
组合未选择 `parameters`，因此 parameter、top module、top ports 和 top ABI 保持不变。

以下命令均从仓库根目录执行，并通过 `rtl_obfuscation` Conda 环境运行。先分析 gold，确认 top
闭包、编译顺序和 inventory：

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite inspect-project \
  --project-root rtl_samples/RISC-V-Vector \
  --top vector_top \
  --report /tmp/risc/gold-report.json
```

预期摘要包含 `candidate_files=56`、`closure_files=19`、`reachable_modules=17`、
`eligible_symbols=1091`、`eligible_occurrences=5741`，且 `status=pass`。

对同一个 top 闭包加密。这里显式列出 T029 的五组 category；省略它们也会启用默认五组：

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite encrypt-project \
  --project-root rtl_samples/RISC-V-Vector \
  --top vector_top \
  --output-dir /tmp/risc/gate \
  --map /tmp/risc/mapping.json \
  --metrics /tmp/risc/metrics.json \
  --file-map-dir /tmp/risc/maps \
  --category signals \
  --category ports \
  --category instances \
  --category struct \
  --category interface \
  --name-length 8
```

预期输出为 `{"files": 19, "mapping_entries": 1091, "modified_tokens": 5741}`。随后重新
检查 gate，确认它仍然能被相同 top-rooted 工程规则解析：

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite inspect-project \
  --project-root /tmp/risc/gate \
  --top vector_top \
  --report /tmp/risc/gate-report.json
```

gate 的 reachable module/file 拓扑应与 gold 一致，parse/semantic error 都应为 0，
`/tmp/risc/mapping.json` 为 version 3，`/tmp/risc/metrics.json` 中的 coverage 应为 `1.0`，
`plaintext_leakage_rate` 应为 `0.0`。

Yosys 0.53 不能直接读取该样例中的 compilation-unit packed struct 和 concurrent assertion，
因此需要从 gold 和真实 gate 对称生成 formal-only view。这个 view 只用于验证，不会修改产品
gold 或 gate：

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite formal-view \
  --project-root rtl_samples/RISC-V-Vector \
  --top vector_top \
  --output-dir /tmp/risc/formal-gold \
  --manifest /tmp/risc/formal-gold.json

conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite formal-view \
  --project-root /tmp/risc/gate \
  --top vector_top \
  --output-dir /tmp/risc/formal-gate \
  --manifest /tmp/risc/formal-gate.json
```

两次 view 应产生相同的结构变换清单，共 260 项：25 个 aggregate type、233 个 member access
和 2 条 concurrent assertion。由于真实 gate 使用了随机名称，还需要用 mapping v3 做只恢复
identifier spelling 的 formal alignment：

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite formal-align \
  --gate-dir /tmp/risc/gate \
  --gate-view-dir /tmp/risc/formal-gate \
  --gate-view-manifest /tmp/risc/formal-gate.json \
  --map /tmp/risc/mapping.json \
  --output-dir /tmp/risc/formal-gate-aligned \
  --manifest /tmp/risc/formal-gate-aligned.json
```

alignment 只允许 PySlang lexer 识别的 identifier，并且固定产生 5527 个替换；它不读取 gold、
不调用解密，也不改变 operator、literal、string、comment 或 directive。最后对 gold view 和
aligned gate view 运行标准 multifile formal：

```sh
conda run -n rtl_obfuscation python scripts/formal_equivalence.py \
  --gold-filelist /tmp/risc/formal-gold/design.f \
  --gold-root /tmp/risc/formal-gold \
  --gate-filelist /tmp/risc/formal-gate-aligned/design.f \
  --gate-root /tmp/risc/formal-gate-aligned \
  --top vector_top \
  --seq 1
```

必须退出码为 0，并输出 `"formal_equivalence": "pass"`。验证通过后再解密产品 gate；mapping
v3 不需要原工程路径：

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite decrypt-project \
  --gate-dir /tmp/risc/gate \
  --map /tmp/risc/mapping.json \
  --output-dir /tmp/risc/restored
```

解密后应对 mapping 中 `files` 的全部 19 个文件做字节比较：

```sh
conda run -n rtl_obfuscation python -c 'import json; from pathlib import Path; m=json.loads(Path("/tmp/risc/mapping.json").read_text()); gold=Path("rtl_samples/RISC-V-Vector"); restored=Path("/tmp/risc/restored"); assert all((gold/f).read_bytes()==(restored/f).read_bytes() for f in m["files"]); print("byte-identical", len(m["files"]), "files")'
```

### 3.11 Formal view 与真实 gate alignment

`formal-view` 是验证专用派生树生成器，不修改产品 gold/gate；它只处理代码中明确允许的
aggregate lowering 和 concurrent assertion blanking。`formal-align` 是 mapping v3 驱动的
identifier-only 对齐工具，当前 1091/5741/5527 oracle 仅适用于 RISC-V-Vector 交付。完整命令
顺序见 3.10；它不读取 gold、不调用解密，也不改变 operator、literal、string、comment 或
directive。

可用一次性验收驱动重跑 RISC-V-Vector 完整链路：

```sh
conda run -n rtl_obfuscation python scripts/t029_acceptance.py --work-dir /tmp/rtl_obfuscation_t029_acceptance
```

## 4. 替换实现机制

1. `project.py` 为 `inspect-project` 和 project-root 加密发现候选文件并构建 top-rooted 闭包；
   filelist 加密仍由 `inventory.py` 将显式文件加入同一个 `pyslang.ast.Compilation`。
2. 每个 category 只收集符合当前边界的 PySlang symbol；同名字符串不会自动视为同一对象。
3. 声明和普通引用优先通过 `node.symbol is target` 证明绑定；PySlang 未直接暴露 token 时，
   只在已限定语法范围内使用 source range fallback，并核对 gold 字节。
4. 随机名称长度由 `--name-length` 指定，最小为 4；名称避开关键字、已有 identifier 和
   本轮已分配名称。
5. source edit 按字节区间从后向前应用，因此不同长度的新名称不会移动尚未处理的 gold range。
6. 单文件 mapping 使用 version 1；多文件 default 保留 filelist v2/project-root v3 兼容表面，
   manual profile 使用 version 4；per-file mapping 是全局 occurrence 的文件投影。
7. v3/v4 解密先校验 manifest、range 宽度/边界和 gate AST occurrence，再逆向应用 mapping，
   不依赖原始名称的文本搜索。

例如：

```systemverilog
child #(.WIDTH(WIDTH)) u_child (...);
```

左侧 `WIDTH` 绑定 child parameter，右侧 `WIDTH` 绑定当前 module parameter。即使拼写相同，
它们也属于不同 mapping entry。

## 5. 验证加密结果

加密命令成功只表示完成了改写，不表示 gate 已经可交付。至少执行 PySlang 和 Yosys；T035
常规验收只覆盖非 RISC fixture，RISC-V-Vector 的 `formal-view`/`formal-align`/Yosys 仅在
专门 RISC 验收任务中执行。

PySlang 检查 FIFO gate：

```sh
conda run -n rtl_obfuscation python -c 'from pathlib import Path; import pyslang; root=Path("/tmp/rtl_fifo/gate"); c=pyslang.ast.Compilation(); [c.addSyntaxTree(pyslang.syntax.SyntaxTree.fromFile(str(root/p.strip()))) for p in (root/"design.f").read_text().splitlines() if p.strip()]; errors=[d for d in c.getAllDiagnostics() if d.isError()]; print("errors=",len(errors)); raise SystemExit(bool(errors))'
```

Yosys 形式等价：

```sh
conda run -n rtl_obfuscation python scripts/formal_equivalence.py \
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

当前可靠覆盖 module value parameter/localparam、普通 integral expression、packed/unpacked
dimension、generate header、struct/interface member dimension 和可解析的 named parameter
override。default profile 也包含 `parameters`，但只改写 `single_module/internal` 对象；top
parameter、跨 module binding 和复杂边界进入 preserved/skipped。manual profile 才在确认 closure
内处理跨 module parameter override：

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
| `$unit` parameter、parameter array/string/real/struct | `parameter string NAME="x";` | 当前不处理 |
| `defparam` 或复杂层次 parameter | `defparam u.WIDTH=16;` | 当前不处理 |
| 未解析外部 module | `ip #(.WIDTH(WIDTH)) u();`，但 `ip` 不在 filelist | 把定义加入 compilation 或保留该名称 |
| 宏、include 和库自动发现 | `` `define WIDTH 8 `` | project-root 模式消费已验收的 active include/宏闭包；宏生成且无法定位物理 token 的 identifier 默认保留 |
| 外部层次依赖 | `force dut.u_fifo.count=0;` | 同步维护外部文件，或保留相关对象 |
| DPI、bind、class、clocking、virtual interface | 验证环境公开 API | 当前不处理 |

特别注意：`example_fifo` 的 interface 是 `fifo_top` 内部实例，top 对外仍是普通 ports，
因此不等同于“顶层 module 使用 interface port”。后者已列入
[未来事项](docs/future_work.md)。

## 7. 文档入口

- [SystemVerilog 重命名表](docs/systemverilog_renaming_table.md)：每个 category 的当前语义和边界。
- [验证流程](docs/formal_verification.md)：PySlang、Yosys、解密和正负 formal 基线。
- [未来事项](docs/future_work.md)：未实现能力、工具链限制和推荐扩展顺序。
- [`project-root + top` 路线图](docs/project_root_top_roadmap.md)：T027–T032 的工程发现、默认/显式
  profile、parameter 交付，以及 T029 RISC-V-Vector synthesis/formal 端到端交付。
- `docs/tasks/`：开发与验收历史，仅用于追溯。
