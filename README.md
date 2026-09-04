# RTL Obfuscation

本项目使用 PySlang 的编译与 elaboration 结果识别 RTL 名称，并对有完整物理绑定证据的对象进行改名。
实际工程请优先使用显式 filelist；工具不修改宏对象，也不会猜测 owner、scope 或源码 token。

## 3 分钟快速开始

```sh
quick_work="$(mktemp -d /tmp/rtl-obfuscation-quick.XXXXXX)"
python rtl_encrypt.py \
  --filelist rtl_samples/example_fifo/design.f \
  --top fifo_top \
  --category signals \
  --output-dir "$quick_work/gate"
cat "$quick_work/gate/encryption_summary.txt"
python rtl_decrypt.py \
  --map "$quick_work/gate/mapping.json" \
  --gate-dir "$quick_work/gate" \
  --output-dir "$quick_work/restored"
```

成功条件：命令退出码为 `0`，`summary.strict_compile_passed` 和
`summary.restored_byte_identical` 均为 `true`。结果中的 `rename`、`preserve`、`unsupported`
分别表示实际改名、按边界保留、因证据不足保留。

## 终端输出：stdout 是机器接口，stderr 是给人看的

两个流分工固定，互不影响：

| 流 | 内容 |
| --- | --- |
| stdout | 一行 JSON，`format=rtl-obfuscation.cli-vnext`、`schema_version=2`，供脚本解析 |
| stderr | 各阶段的实时进度与累计用时，以及结束时的加密总结 |

所以运行时终端同时看到进度和总结；只想看总结就把 stdout 重定向到文件：

```sh
python rtl_encrypt.py \
  --filelist design.f \
  --category all \
  --output-dir <尚不存在的输出目录> > summary.json
```

进度按既有流水线阶段输出，每个阶段给出开始与完成时的累计秒数：读取 filelist / 组装
SourceSet、PySlang 编译与 elaborate、构建改名索引、生成映射、写出加密结果、逐字节回填校验。
真实工程上编译与索引通常是主要耗时段，所以分阶段计时比只报总时间有用。

编译和改名索引阶段还会在 stderr 中显示固定的粗粒度子阶段 ID（例如
`compile.parse`、`compile.elaborate`、`rename_index.name_completeness`），每个 ID 都有
成对的开始 / 完成行和本阶段耗时，便于长期比较不同工程的热点。成功运行会把当前 Python
executable、脚本、shell 已展开的完整 argv、工作目录以及这些计时行写入
`encryption_summary.txt`；计时行与 stderr 逐行逐字符同源。`--quiet` 仅压制 stderr，不关闭
持久化记录。失败或被 SIGKILL 的运行仍不会发布半成品 summary。

加密总结包含用时、加密类型数与类型、总代码行数 / 实际加密行数 / 加密率、
总文件数 / 加密文件数 / 文件覆盖率，以及
改名对象数(rename) / 保留对象数(preserve) / 不支持对象数(unsupported) / 实际修改对象数。
其中**加密文件数**和**实际修改对象数**指真正落地了编辑的文件数与记录数：`rename` 是决策数，
`实际修改对象数` 是字节确实被改写的记录数，使用 `--encryption-rate` 时前者会大于后者。
分母为 0 时相应比率显示 `n/a`。

提供 `--rewrite-root` 时，上述统计范围是 SourceSet 已登记的物理文件与 rewrite-root 的有序交集；未登记或目录外
文件不会进入覆盖率、代码行数或加密率分母。物理 manifest、gate、strict compile 和 decrypt 仍覆盖完整 filelist
物理文件集合。FAST 与 FULL 共用这一范围定义；恢复后的执行事实、指标和报告只构建一次。该统计范围修正不等于
优化 FAST 的 RenameIndex 前端耗时。

`--quiet` 只关闭 stderr 上的进度与总结，不影响 stdout 的 JSON，也不会让失败变安静：
失败仍然打印错误码、`message` 和位置。

输入失败会指出位置：文件缺失给出解析后的绝对路径以及它来自哪个 filelist 的第几行；
解析或 elaborate 错误给出 `文件:行:列`、诊断码和该行源码，并注明诊断总条数。

## Filelist 模式（真实工程首选）

```sh
python rtl_encrypt.py \
  --filelist design.f \
  --top <可选的顶层模块名> \
  --rewrite-root <允许改写的自有 RTL 目录> \
  --category signals \
  --output-dir <尚不存在的输出目录>
```

`--category` 必须显式提供，可重复使用，允许值只有：
`signals`、`ports`、`interface`、`struct`、`all`。`all` 按固定顺序展开为四个核心组。

filelist 中的 `.sv/.v` 是 source unit；`-v PATH` 也可在当前位置显式加入一个 `.sv/.v` source
unit，当前语义与同位置的裸 `PATH` 完全相同，不用它判断供应商归属，也不提供仿真器的惰性
library search。被 include 的 `.svh/.vh`、显式列出的 `.h`，以及由已列源码通过当前目录或
`+incdir+` 的字面量路径直接或递归唯一解析到的普通文件，都是只读物理依赖；任意后缀只有在这种
bounded literal include closure 中成为 include-only physical dependency，不是 standalone suffix，不能作为
裸 filelist 或 `-v` entry。include-only 文件会按规范化路径去重并进入 manifest、gate 和 restore，但不作为独立
source unit 进入 `design.f`；同名 include 同时命中多个候选时拒绝猜测。

显式 filelist 还可用裸路径列出 `.vic`
compilation-unit 参数上下文；显式列出后，source/header 可 `` `include`` 同一规范化完整路径，但不能
仅靠 include 隐式发现 `.vic`。`.vic` 不进入 rename target，也不支持 `-v`、`--input` 或 project-root
自动发现。`-f` 嵌套 filelist、
`+incdir+`、`+define+`、`$NAME` 和 `${NAME}` 按出现顺序处理。filelist 模式禁止同时提供
`--source-root`；源码根目录由 filelist 和 include 路径自动推导。

宏定义名、形式参数名、调用名和预处理结构不进入 mapping。宏正文或实参中的 token 只有在 PySlang
直接绑定到某个选中 RTL symbol 且能唯一对应物理 token 时，才作为该 symbol 的 occurrence；冲突时
保留对应对象，不发布不确定的 gate。宏计算出的 include 不自动登记；若 PySlang parse 实际打开未登记的
真实 source/include buffer，工具会在 SourceCatalog 全树遍历或 FAST 改名索引开始前带路径拒绝。

### 需要补依赖时用包装 filelist，原始 filelist 一行不动

原始 filelist 缺少若干必需文件时不必修改它：新建一个包装 filelist，用 `-f` 引用原始文件再补上
缺的条目即可。`-f` 递归、`-v PATH`、`+incdir+`、`+define+`、`$NAME`/`${NAME}` 和 `//` 注释都已支持。

```sh
cat > "$PROJ/wrapper.f" <<'EOF'
// 原始 filelist 不修改
-f $PROJ/original.f
$PROJ/rtl/extra_assert.sv
$PROJ/rtl/extra_if.sv
EOF
python rtl_encrypt.py --filelist "$PROJ/wrapper.f" --category all --output-dir <输出目录>
```

一个坑：自动推导源码根目录时会把 **filelist 自身所在目录**算进公共路径，所以包装文件应放在
`$PROJ` 内（例如与原始 filelist 同目录）。放在 `$PROJ` 之外会让推导出的源码根目录上移一层，
改变输出里的相对路径；确实无法写入 `$PROJ` 时改用 project-root 模式的 `--source-root` 显式指定。

当 filelist 同时引用多个物理根时，源码根可能是 `/`；这只是 gate 中 root-relative 路径的边界。
此时尚不存在的输出目录和报告路径只会避开 filelist 实际列出的源码、头文件和上下文文件，仍须满足
父目录存在且目标本身不存在。

### 混合工程用 `--rewrite-root` 限定改写目录

真实 filelist 同时带有自有 RTL 和外部模型时，推荐可重复提供 `--rewrite-root DIR`。只有位于至少一个目录内的
显式 source unit 才可以改写；目录外文件仍参与 PySlang 编译和绑定，但对应记录以
`outside_rewrite_root` 保留。多个目录取并集，相对路径按当前调用目录解析；目录必须存在、位于推导后的
SourceSet root 中，并命中至少一个 filelist 显式 source。该参数仅属于 filelist 加密模式。

```sh
python rtl_encrypt.py \
  --filelist design.f \
  --top TOP \
  --rewrite-root "$PROJ/rtl" \
  --rewrite-root "$PROJ/owned_ip" \
  --category all \
  --output-dir <输出目录>
```

未提供时保持原有的全 filelist source 改写候选语义。`--rewrite-root` 是用户授权白名单，不会按目录名、版权头或
`-v` 自动识别供应商代码；请指向真正拥有且允许改写的最小目录。

#### filelist 的 signals 快速路径边界

当输入是显式 `--filelist`、至少提供一个 `--rewrite-root`、规范化后的类别只有
`signals`、省略 `--top` 且未设置 `--encryption-rate` 时，工具使用 module-local signals
快速路径。完整 filelist 只做一次预处理和语法解析，随后只在 rewrite-root 内显式 source unit
的 `ModuleDeclaration` 中检查直接 `logic`/`wire` 或未限定的用户自定义命名类型 declarator（CST
`NamedType.name` 必须是简单 `IdentifierName`，例如 `word_t`；不支持 `pkg::RspCmd_t`）；只有能由
value-expression CST 位置和唯一物理字节范围证明的同名引用才改写。除了裸 value reference，
还允许改写 element/bit/part/indexed selection 的根 identifier，以及 `signal.field` 中
`.` 左侧的根 identifier；字段名、索引表达式中的名字、`::` scope 和层次路径保持不改。
ports、function/task locals、package/global、interface 对象、struct/union 类型定义与字段以及
rewrite-root 外文件保持不改；直接 struct-typed module 变量的根名仍按上述规则处理。
歧义对象以 `syntax_local_ambiguous` 保留。其他输入继续使用现有通用流程；快速路径自身遇到无法证明的
绑定或编译问题会原子失败，绝不静默回退慢路径。

PySlang 11.0.0 对已确认的 edge-sensitive `ifnone` 及六个 legacy directive（`protect`/
`endprotect` 和四个 fault directive）会报可恢复诊断。工具只在诊断能精确回到预期物理字节、
`protect/endprotect` 正确配对时允许继续，并把产生诊断的整个文件以 `readonly_vendor_model` 保留。普通未知宏、
带参数 directive、未配对 protect 或其他解析/语义错误仍会停止；这不是完整的供应商语法兼容层。

## 四个核心加密组

| 类别 | 内容 |
| --- | --- |
| `signals` | module 内部的 Variable/Net，不包含端口、parameter、interface 成员和 struct 字段 |
| `ports` | module 的 source-backed 端口；selected top 的对外 ABI 保留 |
| `interface` | interface 类型、source-backed 标量/数组实例、成员和 modport；数组 element 只是语义 alias |
| `struct` | 物理 `typedef struct/union` 类型及其字段；隐式 conversion 不伪造 occurrence |

无法从 PySlang semantic target 证明唯一物理 declaration/occurrence 时安全保留对应对象或核心组。
合法的 PySlang 编译不等于每个 semantic node 都有可改写的物理 token。

## 三种输入模式

| 模式 | 参数 |
| --- | --- |
| 单文件 | 仅 `--input FILE` |
| filelist | `--filelist FILE`，`--top` 可选；`--rewrite-root DIR` 可重复 |
| project-root | `--source-root DIR --top TOP` |

三种模式严格互斥：单文件不能附带 `--source-root`、`--top` 或 `--rewrite-root`；filelist 不能附带
`--source-root`；project-root 和 decrypt 不接受 `--rewrite-root`。输入模式错误会在输出创建前报告
稳定错误码和具体 detail/message。

project-root 是辅助入口，会从源码根目录发现依赖；单文件用于快速试用。两者不改变四组识别规则。

## 输出、恢复和 schema

输出目录包含完整物理层级下的加密 RTL / 只读依赖、三份等价编译上下文 filelist、
`mapping.json`、`metrics.json`、`mapping_table.csv` 和 `encryption_summary.txt`：

- `design.f` 使用当前输出目录的绝对路径，可从任意工作目录直接使用；
- `export_design.f` 使用 `$OUT/<相对路径>`，移动整个交付目录后先把 `OUT` 设为新 gate 根；
- `original_design.f` 使用本次运行的原始物理绝对路径，便于 gold/gate 对照。

三份 filelist 以相同顺序保存规范化 include directories、defines 和 `compile_order`，仅路径根表示
不同。由 literal include closure 发现的 include-only 文件会复制，但不会被错误地添加为独立
compilation unit。mapping 使用
`format=rtl-obfuscation.mapping`、`schema_version=2`；每条记录包含 category、kind、
semantic kind、物理 declaration/occurrences、action 和 reason。

```sh
python rtl_decrypt.py \
  --map <gate>/mapping.json \
  --gate-dir <gate> \
  --output-dir <尚不存在的恢复目录>
```

恢复只依赖本次 gate 的 mapping 和物理文件。schema 1 不兼容读取，错误码为
`RESTORE_MAPPING_VERSION_UNSUPPORTED`。

`PASS_FULL` 表示本次选中对象全部改名；存在明确边界或安全保留时为 `PASS_PARTIAL`；验证或绑定失败为
`REFUSED_ATOMIC`，不会发布半成品。

保留记录的 `reason` 说明为什么该对象没有改名。常见值：

| `reason` | 含义 |
| --- | --- |
| `selected_top_boundary` | selected top 的 ABI 对象按边界保留 |
| `outside_top_closure` | 对象不在 selected top 的层次闭包内 |
| `macro_origin_conflict` | 一个物理 token 被多个符号共享，来源无法唯一确定 |
| `hierarchical_prefix_unsupported` | 该对象需要层次引用前缀改写，当前不支持 |
| `source_binding_incomplete` | 该记录缺少完整的声明与引用绑定证据 |
| `unelaborated_reference` | 旧名还写在未被 elaborate 的源码里，那里的引用语义不可见 |
| `incomplete_name_coverage` | 源码里还有拼写该旧名的 token 无法归属给任何引用或声明 |
| `readonly_vendor_model` | 该记录跨入产生精确供应商兼容诊断的只读文件 |
| `outside_rewrite_root` | 该记录的声明或引用不在任一授权改写目录中 |
| `readonly_include_file` | 该记录跨入只作为 include 物理依赖的文件 |

`unelaborated_reference` 覆盖只在未选中 generate 分支或从未 elaborate 的设计单元里出现的引用。
那些 token 物理存在但不产生任何语义引用，严格编译也不报错，所以只改声明会把旧名留在加密结果里
变成隐式 net。工具选择保留该符号：宁可少改，不可改错。

`incomplete_name_coverage` 是改名的通用前置条件：只有当源码里拼写该旧名的每一个 token 都能归属
给某个语义引用或某个声明时才改名，否则保留所有拼写该名字的记录。它与具体语法形态无关，因此
同时覆盖已知和未知的漏改面，代价是可改名的对象变少。这是有意的取舍：改得少但可证明正确，
优于编译通过但功能错误。

## 常用参数

| 选项 | 说明 |
| --- | --- |
| `--include-dir PATH` | include 目录，可重复 |
| `--rewrite-root DIR` | 仅 filelist 加密模式；允许改写的目录，可重复 |
| `--define NAME[=VALUE]` | 预处理宏，可重复 |
| `--category NAME` | 四组之一或 `all`，可重复且必填 |
| `--name-length N` | 新名称长度，最小 4，默认 20 |
| `--encryption-rate RATE` | 目标行加密率，`0 < RATE <= 1` |
| `--map PATH` | 自定义 mapping 路径 |
| `--metrics PATH` | 自定义 metrics 路径 |
| `--quiet` | 不在 stderr 输出进度与加密总结；stdout 的 JSON 不受影响 |

## 安装

准备 Python 3.10+ 和 PySlang 11.x 后，在仓库根目录运行：

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install --no-index --no-deps \
  wheel/pyslang-11.0.0-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.whl
```

更多开发者说明见 [SystemVerilog 可加密类型表](docs/systemverilog_renaming_table.md)、
[Formal 流程](docs/formal_verification.md) 和 [开发文档索引](docs/development/README.md)。
