# T116：加密过程的实时进度、可读报告与可定位的失败说明

- 状态：`ACCEPTED`
- 主 Agent：Claude Fable 5
- 起始 HEAD：`0a46999`
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
status: READY_FOR_REVIEW
starting_head: 0a46999
tool_form: /Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python
          （`conda run -n rtl_obfuscation` 在本机报 `__conda_exe: permission denied`，
            与 T110–T115 相同的替代形式）
first_command: /Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python -c
               'import sys, pyslang; print(sys.version); print(pyslang.__version__)'
               -> 3.12.13 / pyslang 11.0.0
```

### 10.1 变更文件

| 文件 | 变更 |
| --- | --- |
| `rtl_obfuscator/rewrite.py` | 进度计时器 `_CliVNextProgress`、加密总结 `_cli_vnext_terminal_report`、落地编辑统计 `_cli_vnext_landed_edits`、失败位置 `_cli_vnext_failure_position` / `_cli_vnext_diagnostic_positions` / `_cli_vnext_filelist_origin` / `_cli_vnext_line_column`、宽度与行格式化、`--quiet`、`_CliVNextError.position` |
| `rtl_obfuscator/orchestration_vnext.py` | 仅新增可选 `stage_observer` 及 `_observe`；阶段顺序、判定和返回值不变，`stage_observer=None` 时与改动前完全一致 |
| `tests/test_t116_cli_report.py` | 新增，17 个用例 |
| `README.md` | 新增“终端输出：stdout 是机器接口，stderr 是给人看的”、“需要补依赖时用包装 filelist”，`--quiet` 进入常用参数表 |
| `docs/tasks/T116_cli_report.md` | 本执行记录 |

未新增任何 fixture 文件：三类失败样例由测试在临时目录内生成，仓库既有 RTL fixture 一个字节没动。
成功路径复用只读的 `tests/fixtures/t115_name_completeness`。

### 10.2 §8 五条验收命令的实际输出

```text
1) $PY -m unittest tests.test_t116_cli_report -v
   Ran 17 tests in 1.103s
   OK
   exit_code: 0

2) $PY -m unittest tests.test_public_cli tests.test_t108_public_core_flow
   tests.test_t092_filelist_input_mode tests.test_t096_public_frontend_input_modes
   tests.test_t091_h_macro_header tests.test_t088_verilog_suffix
   tests.test_t078_direct_restore_headers tests.test_t110_binding_fixes
   tests.test_t115_name_completeness tests.test_binding_coverage -v
   Ran 70 tests in 6.514s
   FAILED (failures=6, errors=2)
   exit_code: 1
   —— 见 §10.6：这 8 个失败在起始 HEAD 0a46999 上逐条同样失败，与本任务无关。

3) $PY -m py_compile rtl_obfuscator/rewrite.py tests/test_t116_cli_report.py
   exit_code: 0
   （另外单独 py_compile rtl_obfuscator/orchestration_vnext.py -> exit_code: 0）

4) git diff --check HEAD
   （无输出）
   exit_code: 0

5) $PY -c '...assert s=="- 状态：`READY_FOR_REVIEW`"...'
   t116_ready_for_review=pass
   exit_code: 0
```

### 10.3 §6 第一条：stdout 与改动前的比对方式和结果

比对不是“断言 JSON 存在”，而是把改动前的代码整份取出来跑同一个 fixture：

```sh
git archive 0a46999 | tar -x -C /tmp/t116_head          # 改动前的产品
diff -r tests/fixtures/t115_name_completeness \
        /tmp/t116_head/tests/fixtures/t115_name_completeness   # 输入相同 -> 无差异
（cd /tmp/t116_head && $PY rtl_encrypt.py --filelist tests/fixtures/t115_name_completeness/design.f \
   --top t115_top --category all --output-dir /tmp/t116_cmp/gate_head > /tmp/t116_cmp/head.json）
$PY rtl_encrypt.py --filelist tests/fixtures/t115_name_completeness/design.f \
   --top t115_top --category all --output-dir /tmp/t116_cmp/gate_mine > /tmp/t116_cmp/mine.json
cmp /tmp/t116_cmp/head.json /tmp/t116_cmp/mine.json
```

结果：

```text
stdout 逐字节相同（cmp 无输出）——不只是字段集合一致，整行完全一致
递归字段路径集合相同：True（27 个字段）
JSON 值也相同：True
stderr: 改动前 0 字节 -> 改动后 1485 字节
```

同一 fixture 的 stdout 在改动前后可以逐字节比对，是因为该行只含计数与比率，不含随机新名。

发布产物同样未变：

```text
gate 文件集合：相同
encryption_summary.txt：逐字节相同
metrics.json：逐字节相同
mapping.json（去掉 renamed_name 与 sha256 后）：相同
```

### 10.4 fixture 上报告的原样输出

命令：

```sh
$PY rtl_encrypt.py --filelist tests/fixtures/t115_name_completeness/design.f \
  --top t115_top --category all --output-dir <新目录>
```

stderr（逐字复制，stdout 的 JSON 不在此流）：

```text
[  0.000s] 开始 读取 filelist / 组装 SourceSet
[  0.004s] 完成 读取 filelist / 组装 SourceSet（本阶段 0.003s）
[  0.005s] 开始 PySlang 编译与 elaborate
[  0.010s] 完成 PySlang 编译与 elaborate（本阶段 0.005s）
[  0.010s] 开始 构建改名索引
[  0.051s] 完成 构建改名索引（本阶段 0.041s）
[  0.051s] 开始 生成映射
[  0.054s] 完成 生成映射（本阶段 0.003s）
[  0.054s] 开始 写出加密结果
[  0.061s] 完成 写出加密结果（本阶段 0.007s）
[  0.061s] 开始 逐字节回填校验
[  0.062s] 完成 逐字节回填校验（本阶段 0.001s）
加密总结

  用时                            0.084s

  加密类型数                           4
  加密类型                  signals, ports, interface, struct

  总代码行数                         140
  实际加密行数                        89
  加密率                          63.57%

  总文件数                             2
  加密文件数                           2
  文件覆盖率                     100.00%

  改名对象数(rename)                  44
  保留对象数(preserve)                12
  不支持对象数(unsupported)            0
  实际修改对象数                      44

  注：加密文件数与实际修改对象数取自 mapping_execution.per_file_mapping 中至少落地一处编辑的文件数与记录数；
      rename 是决策数，实际修改对象数是真正改到字节的记录数。
```

对应 stdout（一行，字段与改动前逐字节相同）：

```text
{"format":"rtl-obfuscation.cli-vnext","schema_version":2,"state":"restored","action_counts":{"rename":44,"preserve":12,"unsupported":0},"summary":{...,"effective_line_total":140,"affected_line_count":89,...,"rename":44,"preserve":12,"unsupported":0}}
```

`--quiet` 同一命令：stderr 0 字节，stdout 与上面逐字节相同。

两个新定义字段的口径与验证：

- 加密文件数 = `per_file_mapping` 中至少落地一处编辑的文件数；本 fixture 为 2 / 2。
  为了证明它不是 `summary.files` 的别名，另建一个含“无可改名对象”文件的输入，得到
  总文件数 2、加密文件数 1、文件覆盖率 50.00%（`test_a_file_with_nothing_to_rename_lowers_the_file_coverage`）。
- 实际修改对象数 = 至少落地一处编辑的记录数；本 fixture 为 44，与 `rename` 的 44 相等，
  因为无 rate 选择时每条 rename 决策都落地。两者会分开的情形已单独测量：
  `--encryption-rate 0.5` 时 mapping 决策 44 条、实际落地 23 条，报告中
  `改名对象数(rename)` 与 `实际修改对象数` 都是 23（= `summary.rename`），
  而published mapping 仍记录 44 条决策（`test_rate_selection_separates_landed_records_from_decisions`）。
  报告始终同时打印两个数，不隐藏任一个。
- 测试里两个字段的期望值直接从 `mapping_execution.per_file_mapping` 重新计算，且文件数用两条
  互相独立的规则交叉验证（`input_sha256 != gate_sha256` 与“存在 action=rename 且 ranges 非空的记录”），
  不调用 `_cli_vnext_landed_edits`；报告里其余数值逐个与同一次运行的 stdout JSON 相等。
- 除零：CLI 无法产出 `effective_line_total == 0` 的真实设计，因此该边界直接在格式化函数上测量，
  显示 `n/a`，且断言输出中不出现 `0.00%`。

### 10.5 三类失败的实际位置输出（退出码均仍为 1）

一、文件缺失（filelist 指向不存在的文件，第 3 行）：

```text
error: CLI_VNEXT_INPUT_INVALID
detail: SOURCESET_FILE_NOT_FOUND
path: absent_unit.sv
message: filelist entry does not exist
position: /private/tmp/t116_probe/proj/absent_unit.sv
filelist: /private/tmp/t116_probe/proj/missing.f:3
hint: ...
exit_code: 1
```

二、语法错误（缺分号）：

```text
error: CLI_VNEXT_INPUT_INVALID
detail: SOURCESET_DISCOVERY_FAILED
path: syntax.sv
message: filelist PySlang compilation contains parse errors
details: [{"code":"DiagCode(ExpectedToken)","path":"syntax.sv","start":82}]
diagnostics: 共 1 条，以下列出前 1 条
  syntax.sv:5:18  DiagCode(ExpectedToken)
      源码: logic latched
hint: ...
exit_code: 1
```

三、elaborate 错误（实例化不存在的 module）：

```text
error: CLI_VNEXT_INPUT_INVALID
detail: SOURCESET_DISCOVERY_FAILED
path: elab.sv
message: filelist PySlang compilation contains semantic errors
details: [{"code":"DiagCode(UnknownModule)","path":"elab.sv","start":67}]
diagnostics: 共 1 条，以下列出前 1 条
  elab.sv:5:5  DiagCode(UnknownModule)
      源码: t116_absent_child child_instance (.clk(clk), .q(q));
hint: ...
exit_code: 1
```

上限与总条数（14 个未知 module）：`diagnostics: 共 14 条，以下列出前 10 条`，随后 10 行位置。
`--quiet` 不会让失败变安静：错误码、message 和 position 照常打印，退出码仍为 1。
`-f` 嵌套时报告的是真正写下该条目的那个 filelist 及其行号，已单独测量。

### 10.6 与合同不符的测量：§6 最后一条在起始 HEAD 上就不成立

§6 要求“上列 10 个测试文件全部原样通过”。实测这 10 个模块在**起始 HEAD `0a46999`
本身**就有 6 failures + 2 errors，与本任务无关：

```sh
git archive 0a46999 | tar -x -C /tmp/t116_head
（cd /tmp/t116_head && $PY -m unittest <§8 第二条的 10 个模块>）  -> Ran 70, FAILED (failures=6, errors=2)
$PY -m unittest <同样 10 个模块>                                  -> Ran 70, FAILED (failures=6, errors=2)
```

逐条比对两次运行的失败集合与失败消息：**测试名集合相同，每条的异常类型与消息也相同**
（脚本按 `======` 分块提取每个失败块的最后一行异常，8/8 全部标记 SAME）。因此本任务
新增 0 个失败，也修好 0 个失败。8 条的实际原因如下，全部与 stdout JSON 无关：

| 模块 | 用例 | 起始 HEAD 上的原因 |
| --- | --- | --- |
| t096 | `test_help_and_documents_are_filelist_first` | `ValueError: substring not found`——README 里没有 `## 三种加密模式`（现为 `## 三种输入模式`）；`--help` 的三条断言本身是通过的 |
| t078 | `test_direct_api_and_public_adapter_share_gate_audit` | `AttributeError: restore_vnext 无 _load_orchestration_gate_inputs_vnext`（测试引用了已删除的私有 API） |
| t092 | `test_public_filelist_autoroot_rejects_source_root_and_restores` | `['rtl/stl_gmacro.h','rtl/top.sv'] != ['rtl/top.sv']` |
| t088 | `test_actual_gate_formal_positive_and_functional_negative` | `1 != 0 : error: CLI_VNEXT_CATEGORY_REQUIRED`（用例未提供 `--category`） |
| t088 | `test_public_three_modes_preserve_suffixes_and_header_is_actually_rewritten` | 同上 `CLI_VNEXT_CATEGORY_REQUIRED` |
| t078 | `test_future_work_records_t078_without_claiming_ibex_groups` | `future_work.md` 中已无 `T078` |
| t078 | `test_persisted_source_set_noncanonical_orders_fail_closed` | `RESTORE_VNEXT_GATE_INVALID: gate design.f differs from compile order` |
| t078 | `test_public_encrypt_persists_compile_and_physical_orders` | `compile_order` 实际含 `defs.svh`，用例期望只有 `top.sv` |

按 CLAUDE.md 与 §4，这 8 条不在本任务范围内：修它们要么要改这 10 个被明令禁止修改的测试文件，
要么要动 frontend 判定与 compile order。**因此这里只报告，不修改，等主 Agent 裁定**是把 §6
最后一条改成“不引入新失败”，还是另立一张清理任务。

同一比对方式也用在直接覆盖被改代码的模块上：`tests.test_vnext_product_surface`、
`tests.test_orchestration_vnext`、`tests.test_cli_vnext_encryption` 在 HEAD 与本改动上都是
`Ran 10, FAILED (failures=1)`，唯一失败是 `test_actual_vnext_cli_report_is_portable_and_deterministic`
的 `unrecognized arguments: --abi-category`，同为既有问题。其中
`test_public_entrypoints_share_execution_but_keep_the_simplified_surface` 通过，说明
`--quiet` 同时加在内部与公共 encrypt 两侧后，公共与内部选项集合仍然只差
`--abi-category`/`--project-root`。

### 10.7 测试是否真的会失败（反向验证）

三处一行改动，各自跑对应用例（改完立即从备份还原，并已确认还原后文件逐字节一致）：

| 反向改动 | 结果 |
| --- | --- |
| `_cli_vnext_landed_edits` 返回 `len(per_file)` 而不是落地文件数 | `T116DefinedFieldTests` FAILED (failures=1) |
| `fail()` 去掉 `lines.extend(error.position)` | `T116FailurePositionTests` FAILED (failures=6)，全部 6 条位置用例都失败 |
| 进度与报告改写到 stdout | `T116StdoutContractTests` 直接 `json.decoder.JSONDecodeError` |

附带教训：跑完反向改动后未清 `__pycache__` 时，同一条命令出现过 `Ran 10 tests ... errors=3`
的假象；`find . -name '__pycache__' -type d -prune -exec rm -rf {} +` 后恢复 `Ran 17 ... OK`。
本记录中的所有测试结论都是清理字节码之后测得的。

### 10.8 README 中的包装 filelist 用法已实测

```text
$PROJ=/tmp/t116_wrap/proj，wrapper.f 用 -f $PROJ/original.f 引用原始 filelist 再补一个文件
包装文件放在 $PROJ 内：exit 0，输出相对路径为 rtl/core.sv、rtl/extra_if.sv
包装文件放在 $PROJ 外：源码根目录上移一层，相对路径变成 proj/rtl/core.sv、proj/rtl/extra_if.sv
                     （若输出目录仍在上移后的根内，还会先报 CLI_VNEXT_OUTPUT_INVALID）
```

原始 filelist 全程未被修改，与 §7 的判断一致；README 已按此记录那个坑。

### 10.9 未覆盖的边界

1. **诊断原文的粒度**：§3.3 要求“诊断原文”。到 CLI 层的 `details` 只带 `code`
   （如 `DiagCode(ExpectedToken)`），PySlang 渲染后的完整诊断句子在
   `project_discovery` 内部就已丢弃，而该文件不在 §5 允许修改之列。因此报告给出的是
   诊断码加该行源码原文；若主 Agent 要的是 PySlang 的完整句子，需要另立任务改
   `project_discovery` / `source_set` 的错误载荷。
2. **`_diagnostic_position` 的复用形式**：CLI 层没有 PySlang 诊断对象和 SourceManager，
   拿到的是 `_diagnostic_position` / `_pyslang_diagnostic_details` 已经解析好的
   （文件, 字节偏移）。本任务只把该偏移渲染成 `行:列`，没有第二套定位；但也确实没有直接
   调用该函数，如实记录。
3. **project-root 模式的位置精度**：`source_set._map_discovery_error` 丢弃了
   `ProjectAnalysisError.start`，所以 project-root 模式的 parse/semantic 失败到 CLI 时
   只剩文件名，没有偏移，无法给出 `行:列`。三类失败样例因此都用 filelist 模式
   （演示要用的模式，其 `details` 带 path 与 start）。修这一点要改 `source_set.py`，不在 §5 内。
4. **列号是字节列**：偏移是字节偏移，列号按字节算。RTL 标识符为 ASCII 时与字符列一致；
   若行内含非 ASCII 注释，列号会与编辑器的字符列不同。
5. **`加密类型` 在 rate 模式下的口径**：该字段复用与 `encryption_summary.txt` 同一个
   category 集合（来自 published mapping 的 rename 决策），因此 `--encryption-rate`
   下它可能比真正落地的类型集合更宽。改成按落地记录统计会引入第二套统计，并与既有
   持久化产物不一致，§3.2 明确禁止，故保持一致。
6. **失败时不打印报告**：失败路径只打印错误与位置，不打印加密总结（此时没有可报告的产物）。
   进度行会保留到失败前的最后一个阶段；文件缺失发生在参数校验阶段，因此那一例连
   第一条进度都还没有输出。
7. **未运行**：RISC-V-Vector Formal（CLAUDE.md 禁止常规任务触发）、blanket
   `unittest discover`、Yosys（本任务不产出改写 RTL，§9 为 N/A）。

### 10.10 §5 白名单与 10 个禁改测试文件的核对

```text
$ git status --porcelain
 M README.md
 M docs/tasks/T116_cli_report.md
 M rtl_obfuscator/orchestration_vnext.py
 M rtl_obfuscator/rewrite.py
?? tests/test_t116_cli_report.py

$ git diff HEAD --stat
 README.md                             |  55 +++++
 docs/tasks/T116_cli_report.md         | 305 +++++++++++++++++++++++-
 rtl_obfuscator/orchestration_vnext.py |  46 +++-
 rtl_obfuscator/rewrite.py             | 426 ++++++++++++++++++++++++++++++++--
```

改动集合与 §5 白名单完全一致。逐个核对 §2 列出的 10 个解析 stdout 的测试文件，
`git status --porcelain -- tests/<name>.py` 全部返回 0 行改动：
test_t108_public_core_flow、test_t088_verilog_suffix、test_t078_direct_restore_headers、
test_t110_binding_fixes、test_t091_h_macro_header、test_t092_filelist_input_mode、
test_t096_public_frontend_input_modes、test_binding_coverage、test_t115_name_completeness、
test_public_cli。

两个产品文件的删除行也已核对，确认没有夹带无关改动：

```text
rtl_obfuscator/rewrite.py 的全部删除行 = 3 处签名/调用点 + 被抽成
  _cli_vnext_renamed_categories 的那段 category 集合代码；其余全是新增。
  无重复定义（`^def |^class ` 名称去重后无重复项）。
rtl_obfuscator/orchestration_vnext.py 的全部删除行 = `from typing import Iterable`
  与 `return build_mapping_vnext(` 两行，均因加入 observer 而改写。
```


## 11. 主 Agent 独立验收记录

```text
reviewed_at: 2026-08-28
reviewed_head: 0a46999
tool_form: /Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python
复跑前先清空全部 __pycache__（本仓库同时存在 cpython-312/313 两份缓存）

第 8 节五条门禁，主 Agent 亲自复跑：
  1) tests.test_t116_cli_report            → Ran 17 tests，OK，exit 0
  2) 十个解析 stdout 的模块                 → Ran 70，FAILED (failures=6, errors=2)，见 11.1
  3) py_compile 三个文件                    → exit 0
  4) git diff --check HEAD                  → 无输出，exit 0
  5) T116 状态守卫                          → t116_ready_for_review=pass，exit 0

边界核对：改动仅 README、本任务单、rtl_obfuscator/rewrite.py、
  rtl_obfuscator/orchestration_vnext.py，加一个未跟踪的新增测试，全部在 §5 允许列表内。
  逐个核对那 10 个禁改测试文件的 git status，全部零改动。
```

### 11.1 第 2 条门禁的 8 个失败：主 Agent 独立确认与本任务无关

子 Agent 上报"这 8 个失败在起始 HEAD 上同样存在"。主 Agent 不采信自报，独立复现：

```sh
git archive 0a46999 | tar -x -C /tmp/t116_base    # 改动前的整份树
cd /tmp/t116_base && <同一条 10 模块命令>
diff <baseline 失败集合> <含 T116 失败集合>
```

结果：两侧失败集合**逐行相同**，唯一差异是 `Ran 70 tests in 6.839s` 与 `6.660s` 的计时行。
故 T116 **未引入任何新失败**，该上报成立。

这 8 个是仓库既有欠债（README 标题漂移、调用已删除的
`restore_vnext._load_orchestration_gate_inputs_vnext`、两处未带现已必需的 `--category`、
compile-order 与文档漂移，以及一条 Yosys `unproven $equiv`），
与 T113 §12 记录的"14 个既有失败"同源。应另立清理任务，不在本任务范围。

### 11.2 主 Agent 的契约缺陷：§6 最后一条不可满足（第四次同类错误）

§6 写"上列 10 个测试文件全部原样通过"。但它们在**起始 HEAD 上就已经有 8 个失败**，
该条件在本任务开工时即数学上不可满足。正确表述应为
"**不得引入新失败**：失败集合与起始 HEAD 逐条相同"。

同类错误在本项目已第四次由主 Agent 造成（T108 §14、T110 §2.4、T110 §1/§8、T115 §8）。
`token_first_binding.md §6.2` 已记录该模式；本条再次印证：
**写验收条件前必须先在起始 HEAD 上实测该条件是否成立**，不能凭"应该都过"的直觉。

子 Agent 的处理是正确的：实测、上报、停下等裁决，而不是去改那 10 个禁改文件。

### 11.3 主 Agent 亲眼验收演示效果（本任务的目的）

在 `tests/fixtures/t115_name_completeness` 上实跑公开 CLI，stderr 实际渲染：

```text
[  0.001s] 开始 读取 filelist / 组装 SourceSet
[  0.014s] 完成 读取 filelist / 组装 SourceSet（本阶段 0.014s）
... 六个阶段，累计秒数单调不减 ...

加密总结

  用时                            0.096s
  加密类型数                           4
  加密类型                  signals, ports, interface, struct
  总代码行数                         140
  实际加密行数                        89
  加密率                          63.57%
  总文件数                             2
  加密文件数                           2
  文件覆盖率                     100.00%
  改名对象数(rename)                  44
  保留对象数(preserve)                12
  不支持对象数(unsupported)            0
  实际修改对象数                      44
  注：……（口径脚注）
```

中文标签是双宽字符，数值列对齐正确（实现走 `unicodedata.east_asian_width` 而非 `ljust`）。
§3.2 要求的 13 个字段全部到位，分组留空行。

`--quiet`：stderr 字节数 **0**，stdout 仍是可解析的 JSON。

### 11.4 stdout 机器接口：主 Agent 独立比对

用 `/tmp/t116_base` 的改动前产品与当前产品跑同一 fixture：

```text
顶层字段集合相同      : True
summary 字段集合相同  : True
summary 数值差异      : 无
action_counts 相同    : True
```

§2 的硬约束守住，10 个解析 stdout 的测试因此无需改动。

### 11.5 主 Agent 挑战了一个数字，结论是主 Agent 自己算错

`--encryption-rate 0.5` 下报告给 `改名对象数(rename)=23`、`实际修改对象数=23`，
而主 Agent 直接从 `per_file_mapping` 复算得 **27**，一度怀疑报告有误。

追查结果：**报告是对的，主 Agent 的复算规则错了。**

```text
distinct symbol_id（报告口径）        : 23
(symbol, file) 对数（主 Agent 口径）  : 27
跨两个文件的记录                     : 4 条（端口声明在 formal_cone.sv、引用在 design.sv）
23 + 4 = 27
```

§3.2 定义的是"至少落地一处编辑的**记录**数"，一条记录跨两个文件仍是一条记录，
所以按 `symbol_id` 去重正确；按"(记录, 文件)对"计数会重复计。
实现在 `_cli_vnext_landed_edits` 中确实用 `set(symbol_id)`，与定义一致。

如实记录：这一轮是主 Agent 的复算口径错误，不是交付缺陷。

### 11.6 三类失败的定位，主 Agent 实测

```text
文件缺失      position: /private/tmp/.../no_such_file.sv
              filelist: /private/tmp/.../miss.f:2          ← 来源 filelist 与行号
语法错误      diagnostics: 共 2 条，以下列出前 2 条
              bad.sv:1:50  DiagCode(ExpectedToken)  + 源码行
elaborate     diagnostics: 共 1 条，以下列出前 1 条
              elab.sv:2:3  DiagCode(UnknownModule)  + 源码行
```

三类退出码均非零，`--quiet` 不静默失败。§3.3 达标。

一处可改进但不阻塞：三类失败的 `hint` 都是同一句"三种输入模式"的通用提示，
对语法错误帮助有限。这是改动前的既有行为，§3.3 未要求，留作后续优化。

### 11.7 未覆盖边界

- §10.9 记录的两条如实成立：CLI 侧只能给出诊断**代码**加源码行，
  PySlang 渲染好的句子在 `project_discovery.py` 内被丢弃（该文件不在 §5 允许列表内）；
  project-root 模式在 `source_set._map_discovery_error` 丢失字节偏移，
  故三个失败样例用 filelist 模式——而 filelist 正是演示模式。
- 除零显示 `n/a` 与进度单调性由新测试覆盖（模块内共 6 处相关断言），
  主 Agent 未另行构造 `effective_line_total == 0` 的真实设计。

`main_result: ACCEPTED`
`用途限定: 演示可用。Formal 验证与服务器上线门禁仍按 T115 §10 另行执行。`
