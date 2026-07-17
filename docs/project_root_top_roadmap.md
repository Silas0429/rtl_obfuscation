# `project-root + top` 通用能力实施路线图

## 1. 目标与任务粒度

本路线图把 `project-root + top` 能力拆成三张粗粒度任务单，而不是为文件发现、宏、闭包、
inventory 和每一种重命名对象分别建立任务。三张任务单分别交付一条可独立运行的纵向能力：

| 任务 | 状态 | 一次性交付的能力 | 是否产生重写 RTL |
| --- | --- | --- | --- |
| T027 | `ACCEPTED` | 工程发现、预处理依赖、top 闭包、严格编译、AST inventory 和精确 source ranges | 否 |
| T028 | `ACCEPTED` | 对闭包执行五类对象的选择、加密、mapping、重编译、解密和小型工程 formal | 是 |
| T029 | `ACCEPTED` | RISC-V-Vector 可综合视图、真实工程加密、解密和 formal 集成验收 | 是 |

每张任务单内部可以有多个按顺序执行的门禁，但只在整张任务完成后发生一次
`READY_FOR_REVIEW -> ACCEPTED` 交接。仍然遵守
[`docs/tasks/README.md`](tasks/README.md) 的规则：同一时间只有一张任务单可处于 `READY`、
`IN_PROGRESS` 或 `READY_FOR_REVIEW`；前一任务未 `ACCEPTED` 时不得启动后一任务。

本路线图不是活动任务合同。T027、T028、T029 已验收。T006 继续保持 `DRAFT`，
本路线图不实现或重命名 parameter。

## 2. 最终使用模型

目标命令为：

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite inspect-project \
  --project-root <rtl-project> \
  --top <top-module> \
  --report <inspect.json>

conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite encrypt-project \
  --project-root <rtl-project> \
  --top <top-module> \
  --output-dir <gate-dir> \
  --map <mapping.json> \
  --metrics <metrics.json> \
  --category signals \
  --category ports \
  --category instances \
  --category struct \
  --category interface

conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite decrypt-project \
  --gate-dir <gate-dir> \
  --map <mapping.json> \
  --output-dir <restored-dir>
```

`struct` 和 `interface` 是 project-root 模式新增的面向用户概念组：`struct` 展开为
`struct_types`、`struct_fields`；`interface` 展开为 `interfaces`、`interface_instances`、
`interface_ports`、`modports`。报告和 mapping 仍保留实际 category，避免把不同语义对象
合并成一个 symbol。已有的底层 `interfaces` category 语义保持不变。

默认 ABI 规则：

- top module 名和 top 普通 port 名始终保留；
- parameter 参与 elaboration，但不进入 eligible inventory，也不被重命名；
- 被 top port 直接或间接使用的 interface、modport、interface member、struct type 和 field
  构成 `top_abi` 闭包，默认整体保留；
- 只修改选定 top 的可综合模块树；不可达 module 即使与可达 module 位于同一 `.sv` 文件，
  其源码区间也不得修改；
- 宏展开产生且不能映射回唯一物理 identifier token 的对象必须报告为 preserved，不能猜测
  源码位置。

## 3. 固定流水线和实现约束

工程解析按以下顺序执行：

1. 从 `project-root` 递归发现 UTF-8 `.sv` 和 `.svh`；忽略其他文件及输出目录。
2. 建立容错语法索引，记录一个文件中的全部 module/interface/package 定义。
3. 解析命令行 include directory、define、源码 `` `include``、`` `define`` 和宏引用。
4. 唯一定位 top，迭代计算 module、interface、type、include 和宏依赖闭包。
5. 只对闭包建立共享 `SourceManager` 和共享 compilation unit，执行严格 PySlang 编译。
6. 从选定 top 的语义实例开始遍历 AST，不能把 compilation root 当作天然闭包。
7. 统计 eligible、preserved、unsupported 对象及精确字节区间。
8. 按所选 category 生成全局无冲突名称，按文件和字节位置降序替换。
9. 使用完全相同的编译上下文重新编译 gate。
10. 执行 mapping 审计、metrics、解密字节恢复和形式等价验证。

“先只编译 top 文件再寻找所有依赖”不能作为实现方式，因为 top 的预处理和类型解析本身可能
依赖其他文件。语法索引用于发现候选依赖，严格 compilation 用于确认最终绑定；缺失或歧义
依赖必须报错，不能按文件遍历顺序随意选择第一个候选。

## 4. 统一机器可读报告

`inspect-project` 成功或失败都必须写出 JSON。成功退出码为 0，工程错误退出码为 1。
最小 schema 为：

```json
{
  "schema_version": 1,
  "status": "pass",
  "top": "project_top",
  "compile": {
    "compilation_unit": "single",
    "include_dirs": [],
    "defines": {}
  },
  "candidate_files": [],
  "definitions": [],
  "dependencies": {
    "includes": [],
    "macros": []
  },
  "reachable": {
    "modules": [],
    "interfaces": [],
    "files": []
  },
  "inventory": {
    "eligible": [],
    "preserved": [],
    "unsupported": []
  },
  "diagnostics": []
}
```

报告必须满足：

- 路径全部相对于 `project-root`，不得包含运行机器的绝对路径；
- 数组按固定键排序，define 等映射按 key 排序；
- 相同输入连续运行两次时，报告文件 SHA-256 完全相同；
- 每个 inventory range 包含 `file/start/end`，回读源文件后必须精确等于原 identifier；
- 错误使用稳定 code，验收不得匹配自由文本 message。

至少冻结这些诊断码：

```text
TOP_NOT_FOUND
AMBIGUOUS_TOP
AMBIGUOUS_DEFINITION
UNRESOLVED_MODULE
UNRESOLVED_INTERFACE
MISSING_INCLUDE
UNRESOLVED_MACRO
AMBIGUOUS_MACRO
PREPROCESS_ERROR
PARSE_ERROR
SEMANTIC_ERROR
UNSUPPORTED_MACRO_IDENTIFIER
```

## 5. T027：工程解析、top 闭包和 AST inventory

### 5.1 单一交付目标

给定 `project-root + top`，一次完成文件发现、定义索引、预处理依赖、top-rooted 设计闭包、
严格 compilation、AST inventory、可加密性判断和 source ranges。该任务只分析，不输出 gate。

### 5.2 交付物

- `inspect-project` CLI 和上述 JSON schema；
- 可复用的 `ProjectDiscovery`、定义索引、依赖解析和 `DesignClosure` 内部接口；
- 共享预处理上下文，支持重复 `--include-dir` 和重复 `--define NAME[=VALUE]`；
- collector 只遍历选定 top 实例树，不再无条件遍历全部 compilation root；
- compilation-unit struct/interface 类型的 inventory 支持；
- eligible/preserved/unsupported 状态及稳定原因；
- 一个提交到仓库的综合 fixture、固定 oracle 和负向 fixtures；
- RISC-V-Vector 只读分析回归，不修改该样例。

### 5.3 固定综合 fixture

T027 任务合同应冻结下面的工程结构：

```text
tests/fixtures/project_root/integration/
├── include/common.svh
├── rtl/top_bundle.sv
├── rtl/core/child.sv
├── rtl/core/leaf.sv
├── rtl/types/structs.sv
├── rtl/bus/internal_if.sv
├── rtl/unused/unrelated.sv
└── notes/readme.txt
```

固定语义关系：

- `top_bundle.sv` 同时定义 `project_top` 和 `same_file_unused`；
- `project_top -> project_child -> project_leaf`；
- `unrelated` 故意实例化缺失 module，但它不在 top 闭包中；
- `common.svh` 提供被闭包使用的宏；
- compilation-unit `packet_t` 及字段 `valid/payload` 只用于内部数据通路；
- `internal_if` 只在 top 内部使用，不出现在 top port ABI；
- top 使用普通 clock/reset/data ports。

基础定义索引必须包含 5 个 module：

```text
project_top
project_child
project_leaf
same_file_unused
unrelated
```

module 闭包必须只包含 3 个：

```text
project_top
project_child
project_leaf
```

T027 的 oracle 还必须固定每个 eligible/preserved symbol 的 category、scope、原名以及全部
`file/start/end`。主 Agent 在把任务设为 `READY` 前，用独立 PySlang 探针和字节回读脚本生成
并核对 oracle；T028、T029 不允许修改该 fixture 或 oracle。

### 5.4 自动验收

目标测试：

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_project_root_inspect -v
```

CLI 黑盒验收必须程序化断言：

1. 候选文件、定义和依赖集合与 oracle 完全一致；`readme.txt` 不进入候选文件。
2. module 定义数为 5，module 闭包数为 3，名称集合与上节完全一致。
3. `same_file_unused` 和 `unrelated` 不进入 reachable inventory。
4. `unrelated` 内的缺失 module 不影响 `project_top` 严格编译。
5. parse error 和 semantic error 均为 0。
6. parameter 只出现在 elaboration 信息中，不出现在 eligible inventory。
7. top module、top ports 和 `top_abi` 类型全部为 preserved，并有固定 reason。
8. 所有 source range 回读等于原名，且同一文件中的 ranges 不重叠。
9. 连续运行两次，报告 SHA-256 相同。
10. 缺失/重复 top、重复 module、缺失 module、include、宏及宏歧义 fixtures 分别返回对应的
    固定诊断码和退出码 1。

RISC-V-Vector 扩展验收必须断言：

- top 为 `vector_top`；
- parse errors = 0，semantic errors = 0；
- 可达 module 数为 17，名称集合为：

```text
and_or_mux
eb_buff_generic
eb_one_slot
fifo_duth
v_fp_alu
v_int_alu
vector_top
vex
vex_pipe
vis
vmu
vmu_ld_eng
vmu_st_eng
vmu_tp_eng
vrat
vrf
vrrm
```

- 闭包依赖文件为 19 个：17 个 module 文件，加 `vstructs.sv`、`vmacros.sv`；
- `params.sv` 不进入 `vector_top` 闭包。

Formal verification：`N/A`，原因是 T027 不产生重写 RTL。

### 5.5 T027 完成条件

只有目标 unittest、所有 CLI 正负例、RISC 只读分析、完整 unittest 和 `git diff --check`
全部通过时，才能进入 `READY_FOR_REVIEW`。T027 接受后，`inspect-project` 的报告 schema、
fixture 和 oracle 成为 T028 的冻结输入。

## 6. T028：闭包内五类对象的通用加密闭环

### 6.1 单一交付目标

基于 T027 的闭包和 inventory，一次支持用户要求的五个概念组：

| 用户概念组 | 实际 category |
| --- | --- |
| signals | `signals` |
| ports | `ports`，仅非 top module ports |
| instances | `instances` |
| struct | `struct_types`、`struct_fields` |
| interface | `interfaces`、`interface_instances`、`interface_ports`、`modports` |

本任务同时交付 mapping v3、按闭包输出、gate 重编译、metrics、decrypt 和小型可综合 fixture 的
formal，不再为各 category 建立单独任务。

### 6.2 交付物

- `encrypt-project --project-root` 模式；
- mapping v3，记录 top、编译上下文、闭包文件、输入 manifest hash、entries 和 preserved 对象；
- `decrypt-project` 自动识别 mapping v2/v3；
- 同文件 reachable/unreachable 定义的区间隔离；
- gate 使用原 gold 的 include、define、文件顺序和 top 重新严格编译；
- top ABI 保护闭包；
- 五个概念组单独运行和组合运行的 debug/metrics 输出；
- 保持现有 `--filelist + --source-root` 和 mapping v2 回归兼容。

mapping v3 至少包含：

```json
{
  "version": 3,
  "mode": "project-root",
  "top": "project_top",
  "compile_context": {},
  "closure": {"files": [], "modules": [], "interfaces": []},
  "input_manifest_sha256": "...",
  "entries": [],
  "preserved": []
}
```

### 6.3 自动验收

目标测试：

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_project_root_rewrite -v
```

验收必须从 T027 冻结 oracle 计算期望，禁止人工查看 gate：

1. 每个概念组独立加密一次，组合组再加密一次。
2. mapping entry 的 `(category, scope, original_name, ranges)` 与 oracle 中该 category 的
   eligible 集合完全相等；不得少项、多项或跨 scope 合并同名对象。
3. 五组组合 mapping 不包含 `parameters`。
4. top module、top ports 和 `top_abi` 对象没有 mapping entry，且出现在 preserved 清单。
5. mapping 中每个 range 在 gold 中等于 `original_name`，在 gate 中等于 `renamed_name`。
6. 所有 eligible occurrences 恰好被修改一次；symbol coverage 和 occurrence coverage 均为
   1.0，plaintext leakage rate 为 0.0。
7. `same_file_unused` 所在区间逐字节不变；不属于闭包的 `unrelated.sv` 不进入 gate filelist。
8. gate 重新运行 `inspect-project` 后 parse/semantic error 均为 0，reachable module/interface
   拓扑与 gold 一致。
9. decrypt 后，mapping v3 `closure.files` 中每个文件与 gold SHA-256 一致。
10. mapping v2 的现有 FIFO 和单文件回归继续通过。

形式验收使用 `rtl_samples/example_fifo`。T027 integration fixture 的 compilation-unit struct
与内部 interface 组合会触发当前 Yosys 0.53 前端断言，因此它用于 PySlang 重编译、mapping
和字节恢复，不作为 T028 formal gold：

```sh
conda run -n rtl_obfuscation python scripts/formal_equivalence.py \
  --gold-filelist rtl_samples/example_fifo/design.f \
  --gold-root rtl_samples/example_fifo \
  --gate-filelist <gate-dir>/design.f \
  --gate-root <gate-dir> \
  --top fifo_top
```

固定结果：

- 仅重命名 gate：退出码 0，JSON `formal_equivalence=pass`；
- 修改一个运算符或寄存器更新值的非等价 gate：退出码非 0；
- 删除一个跨文件 port、struct field、interface member 或 instance occurrence 的四个损坏 gate：
  PySlang 严格编译均失败。

### 6.4 T028 完成条件

五个独立 category 组、组合组、mapping/manifest/range 损坏负例、事务发布、formal 正负例、
解密 hash、legacy 回归、完整 unittest 和 `git diff --check` 必须在一次交付中全部通过。
不得以“某类后续任务再处理”为理由提交部分 category。

## 7. T029：RISC-V-Vector 可综合视图和端到端交付

### 7.1 单一交付目标

让 T028 的通用能力在 `RISC-V-Vector/vector_top` 上完成真实项目加密、重编译、解密和形式
等价验证，并解决当前 Yosys 0.53 无法直接读取 reachable `fifo_duth.sv` 中
`assert property` 的工具链边界。

### 7.2 READY 前置条件

主 Agent 在设置 T029 为 `READY` 前必须：

1. 固定 RISC-V-Vector 输入版本，记录闭包内所有输入文件的 SHA-256 manifest；
2. 使用已接受的 T027/T028 生成最终 inventory oracle，冻结每个 category 的 symbols、
   occurrences 和 source ranges；
3. 冻结 17 个 module、19 个闭包文件和 0 个 PySlang error 的基线；
4. 确认原工程与 gate 使用相同 include dirs、defines、编译顺序和 synthesis-view 规则。

如果样例仍是未跟踪目录，不能把可变的本地内容直接当作验收基线；应先固定 manifest，或者把
合法可分发的固定 fixture 纳入仓库。

### 7.3 可综合/formal view

gold 和 gate 必须对称生成机器可审计的 formal view：

- 只允许移除明确的非功能验证语句，例如 concurrent `assert/assume/cover property`；
- 对 selected top 实际使用的 compilation-unit packed struct，允许依据 PySlang elaborated
  bit width/field offset 对称 lower 为等宽 packed logic 和 part-select；该 lowering 只存在于
  formal view，不修改产品 gold/gate；
- 每个移除项记录 `file/start/end/syntax_kind/source_sha256`；
- 每个 lowering 项记录结构序号、语法类别、source/replacement hash 和 width/offset；
- 不得删除声明、always、assign、module/interface、端口或数据通路语句；
- 遇到未列入 allowlist 的 Yosys 不支持语法时失败，不能静默跳过；
- `equiv_status -assert` 保持不变；
- 相同输入两次生成的 view 和 manifest 哈希必须一致。

T029 READY 探针确认 Yosys 0.53 除 `assert property` 外，还不能正确处理本样例的
compilation-unit packed struct port/field access；只移除 assertion 仍会在 `genrtlil.cc` 触发
内部断言。活动合同因此冻结 25 个 aggregate type lowering、233 个 member lowering 和 2 个
assertion removal，共 260 项，并要求 gold/gate 结构签名一一对应。

真实随机命名 gate 还会使 Yosys 丢失内部 name matching，直接证明在 `equiv_struct` 后留下
67168 个 cells，无法满足 600 秒门禁。T029 因此在产品 gate 和 260 项 gate formal view 均已验证
后，增加 mapping v3 驱动的 formal-only identifier alignment：只用 PySlang lexer 将 5527 个
`renamed_name` identifier token 恢复为同 entry 的 `original_name`，禁止读取/复制 gold 或改变
任意功能 token。aligned view 有独立 manifest，仍使用完整 `equiv_status -assert`，并以固定
`vector_idle_o` 功能负例证明 alignment 不会隐藏逻辑差异。

### 7.4 自动验收

目标测试：

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_risc_v_vector_project_root -v
```

端到端验收必须程序化执行：

1. 校验输入 manifest SHA-256，防止样例版本漂移。
2. `inspect-project`：17 个 reachable module、19 个 closure files、0 parse error、
   0 semantic error。
3. 使用五个概念组组合加密；mapping 中 parameter entries 必须为 0；最终 inventory 固定为
   1091 symbols / 5741 occurrences，其中 ports 为 348 symbols / 1853 occurrences。
4. mapping 的每个 category 数量、occurrences 和 ranges 与冻结 oracle 完全一致。
5. top module、top ports、top ABI interface/struct 仍在 preserved 清单且源码字节不变。
6. gate 再次严格编译：0 parse error、0 semantic error，实例树拓扑与 gold 一致。
7. symbols/occurrences coverage 均为 1.0，plaintext leakage rate 为 0.0。
8. decrypt 后所有 closure files 与 gold SHA-256 一致。
9. gold/gate formal view 的移除清单除名称改写造成的 hash 差异外，语法类别、文件和结构位置
   一一对应。
10. formal-only alignment 严格链接 mapping、product gate 和 gate view，固定为 5527 个
    identifier replacements；aligned manifest、确定性和事务负例通过。
11. Yosys formal 正例通过；人为修改一个 reachable 算术/控制逻辑后的负例明确留下未证明 cell。
12. T027 integration fixture 和旧 filelist FIFO 的所有回归继续通过。

T029 还必须更新：

- 根目录 `README.md` 的正式使用方式；
- [`systemverilog_renaming_table.md`](systemverilog_renaming_table.md) 的新输入边界；
- [`formal_verification.md`](formal_verification.md) 的 formal-view 规则；
- [`future_work.md`](future_work.md) 中仍不支持的外部库、blackbox、复杂宏和顶层 ABI 情况。

### 7.5 T029 完成条件

RISC 原工程分析、组合加密、gate 严格编译、mapping/metrics、解密 hash、formal 正负例、完整
unittest 和 `git diff --check` 全部通过后，才能认为 `project-root + top` 通用能力交付完成。
PySlang 通过但 Yosys formal 未通过时，任务不能进入 `READY_FOR_REVIEW`。

## 8. 每张任务的统一交付记录

子 Agent 必须在任务合同中记录以下机器证据：

```text
changed_files:
exact_commands:
exit_codes:
report_json:
oracle_comparison:
parse_error_count:
semantic_error_count:
mapping_summary:
coverage_summary:
decrypt_hash_comparison:
formal_gold:
formal_gate:
formal_top:
formal_command:
formal_json:
negative_formal_result:
full_unittest_result:
git_diff_check:
unsupported_boundaries:
```

主 Agent 独立重跑目标 unittest、CLI 正负例、oracle 比较、完整 unittest；对 T028/T029 还要
独立重跑 gate compilation、解密 hash、formal 正例和非等价负例。验收只依据退出码、JSON、
oracle、hash 和 formal 结果，不以人工阅读实现代码作为通过条件。

## 9. 兼容性和明确不包含的范围

可以复用当前仓库的 PySlang collector、语义 identity、名称冲突处理、source range 校验、降序
byte edits、mapping/metrics、decrypt 和 Yosys formal 主流程。需要新增或调整的是工程发现、
共享预处理上下文、依赖闭包、top-rooted traversal、compilation-unit 类型、mapping v3 和
formal view。

三张任务均不包含：

- parameter 重命名；
- 自动解析 Vivado/Quartus Tcl 工程、IP catalog 或预编译 library；
- 未提供定义的 blackbox/IP 自动建模；
- DPI、class、virtual interface、bind、checker、primitive；
- testbench、SDC、Tcl、软件模型和外部层次路径的同步改写；
- 顶层 interface/struct ABI 的默认重命名。

这些对象若影响 top elaboration，分析阶段仍必须解析或给出结构化错误；“不重命名”不代表
“不需要参与编译”。
