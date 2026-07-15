# T026：完善 FIFO 样例的 interface 与 struct 使用

- 状态：`ACCEPTED`
- 负责人：主 Agent
- 前置任务：T025 `ACCEPTED`

## 目标

只完善 `rtl_samples/example_fifo` 的可读性和覆盖场景，不新增重命名 category、collector
或 CLI 功能：

1. 让 `fifo_if` 在 `fifo_top` 中作为实际 internal interface signal bundle 使用，承载
   top adapter 与 FIFO logic 之间的 push/pop/data/status 连接；顶层 `fifo_top` 的普通
   clock/reset/data ports 保持不变。
2. 让 FIFO 的 packed struct 在真实数据通路中作为 function argument 传递，而不只是
   typedef、union member 和字段访问的静态展示。
3. 保持现有四文件结构、加密/解密、per-file mapping、前端检查和 Yosys formal 流程有效。

## 边界

- 不修改 `rtl_obfuscator/` 实现。
- 不新增 package、class、virtual interface 或顶层 interface port；这些不属于当前样例的
  已验证边界。当前 Icarus/Yosys 流程也不把 interface 作为下级 module port 作为验收
  形态；样例采用已验证的内部 interface bundle 形态。
- interface 和 struct 的使用必须是可综合的 FIFO 数据通路，而不是无效占位代码。

## 允许文件

- `README.md`
- `rtl_samples/example_fifo/fifo_top.sv`
- `rtl_samples/example_fifo/fifo_storage.sv`
- `tests/test_debug_mode.py`
- `tests/test_example_fifo_project.py`
- `tests/test_formal_equivalence.py`
- `docs/tasks/T026_fifo_interface_struct_usage.md`

## 验收要求

1. `fifo_top` 仍保留原有普通顶层 ports；`fifo_bus` 实例实际承载 top 与 `fifo_ctrl`
   之间的控制、数据和状态连接，不是未使用的 interface 声明。
2. `fifo_storage` 的 `fifo_entry_t` 通过 function argument 传递，调用点使用实际
   `view.entry`；struct field 语义保持可解析且可综合。
3. 完整 FIFO encrypt-project 的 mapping、metrics、per-file mapping 与实际输出一致，
   不出现 plaintext leakage，decrypt-project 逐文件字节恢复。
4. gold 和 gate 均通过 PySlang、Verible、Icarus；主 Agent 独立运行 Yosys formal，结果
   必须为 `formal_equivalence=pass`。
5. 既有 FIFO 功能负例和完整 unittest 继续符合预期；`py_compile`、`git diff --check`
   通过。

## 验收结果

- `fifo_top` 保持原有普通 top ports；`fifo_bus` 在 top 内部实际承载 push/pop/data/q/full/
  empty/valid 连接，测试固定检查 `fifo_if fifo_bus` 和 `fifo_bus.push`。没有新增顶层
  interface port。
- `fifo_storage` 新增 `extract_payload(input fifo_entry_t entry_value)`，调用点为
  `extract_payload(view.entry)`；测试固定检查 function、argument 和 struct type reference
  已进入 mapping。
- 完整 encrypt-project 实测：`{"files": 4, "mapping_entries": 79,
  "modified_tokens": 299}`。单类别变化为 functions `2/7`、arguments `4/9`、typedefs
  `2/7`、struct_types `2/5`；其余 category 与既有 FIFO 语义一致。
- metrics：symbols `79/79`，occurrences `299/299`，affected lines `175/233`，
  `plaintext_leakage_rate=0.0`，`effective_coverage=1.0`。
- gold 和 gate 的 PySlang 均无 error（gate diagnostics 5、errors 0）；Verible 和 Icarus
  均通过。Icarus 仅输出既有 constant-select 提示。
- 主 Agent 独立运行 Yosys formal：
  `conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold-filelist rtl_samples/example_fifo/design.f --gold-root rtl_samples/example_fifo --gate-filelist /tmp/t026_project/gate/design.f --gate-root /tmp/t026_project/gate --top fifo_top`
  退出码为 0，结果为 `{"formal_equivalence":"pass","seq":5,"top":"fifo_top"}`。
- decrypt-project 输出的四个 `.sv` 均与 gold 字节级一致；完整回归为 `Ran 33 tests`、
  `OK`；既有 FIFO formal 正例和功能变更负例保持预期结果。
- `py_compile` 和 `git diff --check` 通过。

## 工具链边界记录

- 探针尝试将 `fifo_if.consumer` 直接作为 `fifo_ctrl` 的下级 module port；Icarus 在 port
  declaration 处报 syntax error。根据当前项目的 PySlang/Icarus/Yosys 交付门禁，没有把
  这种不受支持的写法加入 gold。样例采用已验证的 internal interface bundle 连接方式，
  这与“顶层普通 ports 不改变”的交付边界一致。

## 执行记录

- 2026-07-15：主 Agent 完成 FIFO interface 使用说明强化和 struct function argument
  场景，未修改 `rtl_obfuscator/` 实现。
- 2026-07-15：主 Agent 独立完成 mapping、per-file mapping、frontend、formal、decrypt
  和完整回归验收，任务设置为 `ACCEPTED`。本任务未由子 Agent 提交或推送。
