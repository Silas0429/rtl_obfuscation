# T020：四文件 FIFO 工程样例与 per-file mapping 输出

- 状态：`READY`
- 设计负责人：主 Agent
- 实现负责人：子 Agent
- 前置任务：T019 已达到 `ACCEPTED`

## 1. 单一目标

为交付审核提供一个真实、可解析、可 formal 验证的四文件同步 FIFO 工程样例，并在
现有 project pipeline 上增加可选的 per-file mapping 输出：

1. 固定 gold 输入为 `rtl_samples/example_fifo/` 下的四个 `.sv` 文件；
2. 最终 project 加密同时覆盖当前实现支持的 19 个 category；
3. 除现有全局 mapping v2 外，为每个 gold `.sv` 输出一个对应 JSON；
4. 保持 `mapping.json` v2、`decrypt-project` 和旧 project CLI 调用兼容；
5. 支持逐个 category 的 debug 加密，每次只启用一个 category；
6. 对最终四文件 gate 执行 PySlang、Verible、Icarus 和 Yosys formal。

本任务不实现新的重命名 category。`modport_ports` 仍不是独立 entry，interface 中的
modport member 引用继续由 `interface_ports` 负责。

## 2. 固定 gold 输入

输入目录是主 Agent 冻结的只读样例：

```text
rtl_samples/example_fifo/design.f
rtl_samples/example_fifo/fifo_if.sv
rtl_samples/example_fifo/fifo_storage.sv
rtl_samples/example_fifo/fifo_ctrl.sv
rtl_samples/example_fifo/fifo_top.sv
```

`design.f` 的顺序必须保持：

```text
fifo_if.sv
fifo_storage.sv
fifo_ctrl.sv
fifo_top.sv
```

顶层为 `fifo_top`。FIFO 使用默认 `DATA_WIDTH=8`、`DEPTH=4`、`ADDR_WIDTH=2`，包含
写入、读取、环形指针、计数、`full`、`empty` 和 `valid` 行为。样例有意包含不同
scope 中的同名符号，包括 `DATA_WIDTH`、`DEPTH`、`clk`、`rst_n`、`data`、`valid`、
`i`、function/task argument `value`，用于验证语义绑定而不是文本替换。

样例不包含 package、class、DPI、bind、virtual interface、clocking block、宏或
`parameter type`。

## 3. Category 覆盖矩阵

最终组合命令必须使用：

```text
all
modules
ports
interfaces
interface_instances
interface_ports
modports
```

其中 `all` 展开为当前 13 个安全 category：

```text
signals parameters enum_values genvars functions tasks arguments instances
generate_blocks typedefs struct_types struct_fields union_fields
```

最终 mapping 必须恰好覆盖以下 19 个 category，且每个 category 至少有一个 entry：

```text
signals parameters enum_values genvars functions tasks arguments instances
generate_blocks typedefs struct_types struct_fields union_fields modules ports
interfaces interface_instances interface_ports modports
```

基于冻结 gold 的当前 collector 预期，每次从 gold 单独执行一个 category 时，摘要应为：

| Category | mapping_entries | modified_tokens |
| --- | ---: | ---: |
| `signals` | 14 | 67 |
| `parameters` | 9 | 21 |
| `enum_values` | 3 | 6 |
| `genvars` | 2 | 10 |
| `functions` | 1 | 4 |
| `tasks` | 1 | 2 |
| `arguments` | 3 | 7 |
| `instances` | 2 | 2 |
| `generate_blocks` | 2 | 2 |
| `typedefs` | 2 | 4 |
| `struct_types` | 2 | 3 |
| `struct_fields` | 2 | 4 |
| `union_fields` | 2 | 4 |
| `modules` | 2 | 4 |
| `ports` | 17 | 59 |
| `interfaces` | 1 | 2 |
| `interface_instances` | 1 | 17 |
| `interface_ports` | 9 | 41 |
| `modports` | 2 | 2 |

最终组合加密的固定 stdout 为：

```json
{"files": 4, "mapping_entries": 77, "modified_tokens": 261}
```

随机加密名称不属于固定预期；测试只检查合法性、唯一性和 mapping 关系。

## 4. Per-file mapping 输出契约

在不改变全局 mapping v2 schema 的前提下，为 `encrypt-project` 增加可选参数：

```text
--file-map-dir <directory>
```

传入该参数时，必须为每个 source `.sv` 生成一个同名 `.json`：

```text
<file-map-dir>/fifo_if.json
<file-map-dir>/fifo_storage.json
<file-map-dir>/fifo_ctrl.json
<file-map-dir>/fifo_top.json
```

每个文件的 JSON 使用独立的 per-file mapping v1，至少包含：

```json
{
  "version": 1,
  "file": "fifo_ctrl.sv",
  "top": "fifo_top",
  "entries": [
    {
      "entry_key": {
        "category": "ports",
        "scope": "fifo_ctrl",
        "declaration": {
          "file": "fifo_ctrl.sv",
          "start": 0,
          "end": 4
        }
      },
      "category": "ports",
      "scope": "fifo_ctrl",
      "original_name": "data",
      "renamed_name": "Ab3xKp91",
      "role": "declaration",
      "range": {"start": 0, "end": 4}
    }
  ],
  "summary": {"entries": 1, "occurrences": 1}
}
```

约束：

- `file` 使用相对于 source-root 的规范路径；
- `range` 是 gold source range；
- `role` 只能是 `declaration` 或 `reference`；
- 同一个全局 entry 在其他文件中的 reference 必须出现在对应文件 JSON 中；
- per-file JSON 是全局 mapping 的审计投影，不是独立随机命名来源；
- 4 个 per-file JSON 中 occurrence 的并集必须与全局 mapping v2 的 declaration/reference
  occurrence 完全相等；
- 不得把同名但不同 scope 的 symbol 合并成一个 per-file entry。

不传 `--file-map-dir` 时，既有 `encrypt-project` 输出行为必须保持不变。

## 5. 固定输出布局

完整加密输出目录为 `/tmp/rtl_obfuscation_t020/`：

```text
/tmp/rtl_obfuscation_t020/
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

## 6. 固定 CLI 验收命令

完整组合加密：

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite encrypt-project \
  --filelist rtl_samples/example_fifo/design.f \
  --source-root rtl_samples/example_fifo \
  --output-dir /tmp/rtl_obfuscation_t020/gate \
  --map /tmp/rtl_obfuscation_t020/mapping.json \
  --metrics /tmp/rtl_obfuscation_t020/metrics.json \
  --file-map-dir /tmp/rtl_obfuscation_t020/maps \
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

stdout 必须为：

```json
{"files": 4, "mapping_entries": 77, "modified_tokens": 261}
```

解密与逐文件恢复：

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite decrypt-project \
  --gate-dir /tmp/rtl_obfuscation_t020/gate \
  --source-root rtl_samples/example_fifo \
  --map /tmp/rtl_obfuscation_t020/mapping.json \
  --output-dir /tmp/rtl_obfuscation_t020/restored

cmp -s rtl_samples/example_fifo/fifo_if.sv /tmp/rtl_obfuscation_t020/restored/fifo_if.sv
cmp -s rtl_samples/example_fifo/fifo_storage.sv /tmp/rtl_obfuscation_t020/restored/fifo_storage.sv
cmp -s rtl_samples/example_fifo/fifo_ctrl.sv /tmp/rtl_obfuscation_t020/restored/fifo_ctrl.sv
cmp -s rtl_samples/example_fifo/fifo_top.sv /tmp/rtl_obfuscation_t020/restored/fifo_top.sv
```

## 7. Debug 单类别矩阵

从同一 gold 目录分别执行第 3 节的 19 个 category，每次命令只能包含一个
`--category`，并传入独立 output、global map、metrics 和 per-file map 目录。

每次必须满足：

- stdout 与第 3 节对应摘要一致；
- mapping 只包含被请求 category；
- per-file JSON 只包含被请求 category；
- mapping ranges 与 gold bytes 一致；
- decrypt 后 4 个文件与 gold 逐字节一致。

`--category modport_ports` 必须被 CLI 明确拒绝；不得静默生成伪 entry。

## 8. Frontend 和 formal 门禁

完整 gate 必须满足：

- PySlang 四文件 Compilation error 数为 0；
- Verible 对四个 gate `.sv` 退出码均为 0；
- Icarus 对 `design.f`、top `fifo_top` 退出码为 0；
- 多文件 Yosys formal 退出码为 0，JSON 包含：

```json
{"formal_equivalence": "pass", "seq": 5, "top": "fifo_top"}
```

Gold 预检已通过 PySlang、Verible 和 Icarus。当前既有 project signals collector 对
unpacked RAM array 的某些 `NamedValue` 返回 `syntax=None`，会在 source range 收集阶段
触发 `AttributeError`；T020 必须以 source range fallback 正确收集这些 occurrence，并
保持 occurrence 去重，不能通过删除 FIFO RAM array 或跳过 signals 来规避。

## 9. Metrics 和 mapping 约束

完整组合的 `metrics.json` 必须满足：

```text
symbols.coverage = 1.0
occurrences.coverage = 1.0
plaintext_leakage_rate = 0.0
effective_coverage = 1.0
```

全局 mapping 必须保持 v2、`top=fifo_top`、相对路径、稳定排序和原有 decrypt schema。
per-file mapping 的 occurrence 并集必须与全局 mapping 完全一致。

## 10. Regression test

新增 `tests/test_example_fifo_project.py`，使用黑盒 subprocess 覆盖：

1. 完整组合加密摘要、4 个 gate 文件和 4 个 per-file JSON；
2. 19 个 category 的单类别摘要及 category 隔离；
3. mapping v2、per-file mapping schema、source ranges 和同名 scope 分离；
4. metrics、decrypt byte round-trip；
5. PySlang、Verible、Icarus 和 formal 结果。

完整回归命令：

```sh
conda run -n rtl_obfuscation python -m unittest discover -s tests -v
```

## 11. 明确不包含

- `type_parameters`；T006 继续保持 `DRAFT`；
- `modport_ports` 独立 entry；
- 修改 `mapping v2` 必需字段或单文件 mapping v1；
- 增加新的 rename category；
- include/define/library/嵌套 filelist 自动发现；
- virtual interface、clocking block、DPI、bind、package/class scope；
- 修改 `rtl_samples/example_fifo/` gold 输入；
- 修改 formal 脚本；
- commit、push、amend、rebase 或 force-push。

## 12. 允许修改的文件

```text
rtl_obfuscator/inventory.py
rtl_obfuscator/rewrite.py
tests/test_example_fifo_project.py
docs/tasks/T020_example_fifo_per_file_mapping.md
```

以下目录由主 Agent 冻结，子 Agent 不得修改：

```text
rtl_samples/example_fifo/
```

## 13. 子 Agent 文档流程

1. 开始前把状态从 `READY` 改为 `IN_PROGRESS`，记录开始时间和命令。
2. 发现 PySlang API、range、类别边界或输出 schema 问题时，先记录最小复现，不得扩大范围。
3. 完成后记录修改文件、19 组 debug 命令、完整组合命令、实际摘要、mapping/metrics、
   decrypt、frontend、formal 和 unittest 输出。
4. rewritten RTL 的 formal 必须记录 gold filelist、gate filelist、gold-root、gate-root、
   top、退出码和 JSON 结果。
5. 全部门禁通过后只设置为 `READY_FOR_REVIEW`，不得设置 `ACCEPTED`，不得 commit 或 push。

## 14. Formal verification

```text
formal_verification: PENDING
reason: T020 produces rewritten RTL; the sub-agent must run the required multi-file Yosys formal after implementing per-file mapping output and the FIFO-array source-range fix.
```

## 15. 执行记录（主 Agent 初始化）

- 2026-07-14：T019 已验收；主 Agent 创建并冻结 `rtl_samples/example_fifo/` 四文件
  FIFO gold，`design.f` 顺序为 interface、storage、controller、top。
- 2026-07-14：gold 的 PySlang Compilation 为 4 files / 0 errors；Verible 四文件退出码
  均为 0；Icarus `fifo_top` 退出码为 0。
- 2026-07-14：现有 project pipeline 的 18 个非 `signals` 单类别预检均可运行；`signals`
  因 unpacked RAM array 的 `syntax=None` source-range 边界暂时失败，已纳入本任务最小修复范围。

## 16. 偏差或阻塞

- 无。T020 当前处于 `READY`，等待子 Agent 按本任务开始执行。

## 17. 主 Agent 验收结果

- `PENDING`。
