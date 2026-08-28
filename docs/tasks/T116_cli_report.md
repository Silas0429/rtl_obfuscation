# T116：加密过程的实时进度、可读报告与可定位的失败说明

- 状态：`READY`
- 主 Agent：Claude Fable 5
- 起始 HEAD：待 T115 提交后填入
- 任务类型：**展示层**改动，不触碰加密判定逻辑
- 目的：服务器演示。不是面向用户的最终交付，Formal 验证仍在后续。

## 0. 为什么这是展示层任务

用户当前看到的是一行 JSON：

```text
{"format":"rtl-obfuscation.cli-vnext","schema_version":2,"state":"restored",...}
```

演示时需要的是：跑的过程中能看到进度与已用时间，跑完给一份人能读的总结，
失败时能直接定位到文件与位置。这些都不改变任何 rename/preserve 判定。

## 1. 单一目标

在不改变任何加密判定、不改变 stdout 机器接口的前提下，让 `rtl_encrypt.py` 的
终端体验可用于演示。

## 2. 硬约束：stdout 的机器接口一个字节都不能变

仓库中**10 个测试文件**对 stdout 做 `json.loads`：

```text
test_t108_public_core_flow  test_t088_verilog_suffix  test_t078_direct_restore_headers
test_t110_binding_fixes     test_t091_h_macro_header  test_t092_filelist_input_mode
test_t096_public_frontend_input_modes  test_binding_coverage
test_t115_name_completeness  test_public_cli
```

因此：

- **stdout 继续只输出原有的单行 JSON**，schema 与字段不变；
- **进度与可读报告一律输出到 stderr**；
- 新增 `--quiet` 抑制 stderr 的进度与报告（`--quiet` 已存在于部分子命令时复用同名语义）。

这条约束的好处是零测试改动：演示时终端同时显示两个流，把 stdout 重定向到文件即可只看报告。

不得为了"让终端好看"而把 JSON 改成人类格式或移出 stdout。

## 3. 冻结的做法

### 3.1 实时进度（stderr）

按既有流水线阶段输出，每阶段给出开始与完成的累计用时：

| 阶段 | 触发点 |
| --- | --- |
| 读取 filelist / 组装 SourceSet | `from_filelist` / `from_project_root` 前后 |
| PySlang 编译与 elaborate | `build_source_catalog` 前后 |
| 构建改名索引 | `build_rename_index` 前后 |
| 生成映射 | `build_mapping_vnext` 前后 |
| 写出加密结果 | `write_gate_vnext` 前后 |
| 逐字节回填校验 | `restore_gate_vnext` 前后 |

要求：单调递增的累计秒数；不得引入第二套计时口径；不得因为进度输出改变阶段顺序。
StCache 规模上编译与索引是主要耗时段（T115 §12.4 实测 19 文件索引 2.71s），
所以每阶段单独计时比只报总时间有用。

### 3.2 加密总结（stderr，用户指定字段）

必须包含下列全部字段，字段名用中文，数值右对齐，分组之间留空行：

```text
用时
加密类型数 / 加密类型
总代码行数 / 实际加密行数 / 加密率
总文件数   / 加密文件数   / 文件覆盖率
改名对象数(rename) / 保留对象数(preserve) / 不支持对象数(unsupported) / 实际修改对象数
```

字段来源必须复用**已有**度量，不得新增第二套统计：

| 字段 | 来源 |
| --- | --- |
| 总代码行数 | `summary.effective_line_total` |
| 实际加密行数 | `summary.affected_line_count` |
| 加密率 | `affected_line_count / effective_line_total` |
| 总文件数 | `summary.files` |
| rename / preserve / unsupported | `summary` 同名字段 |

两个字段今天没有现成来源，必须在本任务中定义清楚并在报告脚注一行说明其口径：

- **加密文件数**：`mapping_execution.per_file_mapping` 中至少落地一处编辑的文件数；
  文件覆盖率 = 加密文件数 / 总文件数。
- **实际修改对象数**：至少落地一处编辑的**记录**数。它与 `rename` 不同——`rename` 是
  决策数，本字段是真正改到了字节的记录数，两者不等时必须能解释。
  报告中两个数都要出现，不得只留一个。

若 `effective_line_total` 为 0 等除零情况，显示 `n/a` 而非崩溃或显示 0%。

### 3.3 失败时可定位（stderr）

现有 `fail()` 已输出 `error/detail/path/message/details/hint`。本任务要求补足**位置**：

- 文件缺失：给出解析到的绝对路径，以及它来自哪个 filelist 的第几行；
- 解析错误 / elaborate 错误：给出 `文件:行:列` 与诊断原文，
  最多列出前 N 条（N 取 `--examples` 若已存在，否则固定 10）并注明总条数；
- 位置一律复用 `rtl_obfuscator/project_discovery.py` 的 `_diagnostic_position`，
  不得新写第二套定位。

不得把失败改成静默或退化为成功；退出码语义不变。

## 4. 不包含的内容

- 不改动任何 rename/preserve 判定、reason、category、mapping schema、SourceSet 语义；
- 不改动 stdout 的 JSON 内容与字段（见 §2）；
- 不改动 `scripts/gate_rename_audit.py`、`scripts/binding_coverage.py`；
- 不新增 `--extra-file` 之类的输入注入选项（依赖问题已由包装 filelist 解决，见 §7）；
- 不引入第三方终端库（colorama、rich 等），只用标准库；
- 不放宽任何既有断言；不运行 RISC-V-Vector Formal；不使用 blanket `unittest discover`。

## 5. 允许修改

- `rtl_obfuscator/rewrite.py`（CLI 输出层）
- 必要时 `rtl_obfuscator/orchestration_vnext.py`（仅为暴露阶段回调；不得改变阶段顺序与判定）
- `tests/test_t116_cli_report.py`（新增）
- `README.md`（补充演示用法、`--quiet`、包装 filelist 用法）
- 本任务单

**不得修改上列 10 个解析 stdout 的测试文件中的任何一个。** 它们全部原样通过是本任务的验收条件。

## 6. 机器可验收结果

- stdout 仍是单行 JSON，且 `--category all` 下与改动前**字段集合一致**（用同一 fixture 比对）；
- stderr 含 §3.2 全部字段；`--quiet` 时 stderr 不含报告与进度；
- 进度的累计秒数单调不减；
- 制造三类失败各一例，stderr 均给出位置：
  文件缺失（filelist 指向不存在的文件）、语法错误、elaborate 错误；
- 除零情况显示 `n/a`；
- 上列 10 个测试文件全部原样通过。

## 7. 依赖引用问题：不需要改代码（已实测确认）

用户的真实 filelist 需要额外带上 `StChAssert.sv`、`csr_if.sv` 与四个 `.h`，
但不想改原始 filelist。**解析器已支持 `$PROJ` 环境变量展开、`-f` 递归与 `//` 注释**，
所以新建一个**包装 filelist** 即可，原始文件一行不动。

必须在 README 中记录一个坑：`infer_filelist_root` 把 **filelist 自身所在目录**
算进 commonpath，所以包装文件应放在 `$PROJ` 内（例如与原始 filelist 同目录），
否则推导出的 source_root 会上移一层、改变输出里的相对路径；
无法写入 `$PROJ` 时用 `--source-root` 显式指定。

## 8. 固定验收命令（5 条）

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_t116_cli_report -v

conda run -n rtl_obfuscation python -m unittest \
  tests.test_public_cli tests.test_t108_public_core_flow tests.test_t092_filelist_input_mode \
  tests.test_t096_public_frontend_input_modes tests.test_t091_h_macro_header \
  tests.test_t088_verilog_suffix tests.test_t078_direct_restore_headers \
  tests.test_t110_binding_fixes tests.test_t115_name_completeness \
  tests.test_binding_coverage -v

conda run -n rtl_obfuscation python -m py_compile \
  rtl_obfuscator/rewrite.py tests/test_t116_cli_report.py

git diff --check HEAD

conda run -n rtl_obfuscation python -c 'from pathlib import Path; \
s=next(l for l in Path("docs/tasks/T116_cli_report.md").read_text().splitlines() if l.startswith("- 状态：")); \
assert s=="- 状态：`READY_FOR_REVIEW`", s; print("t116_ready_for_review=pass")'
```

## 9. Formal verification

```text
formal_verification: N/A
reason: 本任务只改终端输出与失败说明，不改写 RTL、不改变任何 rename/preserve 判定，
        产出的 gate 与改动前逐字节一致（§6 第一条即要求 stdout 字段集合不变）。
```

## 10. 执行记录

```text
status: READY
（子 Agent 开工前改为 IN_PROGRESS 并记录 starting_head、tool_form、first_command）
```
